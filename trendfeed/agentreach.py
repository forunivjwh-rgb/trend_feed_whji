"""Agent Reach — 실탐에서 원문을 읽는 도구 (명세 6번).

사용자가 포크한 저장소의 한 커밋으로 고정해서, 이 repo 안의 따로 된 폴더(.agent-reach/)에 설치한다.
PyPI의 같은 이름 패키지는 다른 프로젝트라서 쓰지 않는다.

안전하게 쓰는 규칙
- 로그인이 필요한 채널(인스타·레딧·X 등)은 부르지 않는다. 쿠키·프록시·브라우저 설정도 넘기지 않는다.
- 도구를 부를 때 환경 변수는 꼭 필요한 것(경로, 인터넷 프록시 설정)만 넘긴다. API 키는 넘기지 않는다.
- 플랫폼이 "로봇 아님 확인"을 요구하거나(PLATFORM_BLOCKED) 횟수 제한에 걸리면(RATE_LIMITED)
  그 채널은 그날 더 부르지 않는다. 우회하지 않는다.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from . import config

STOP_CODES = {"PLATFORM_BLOCKED", "RATE_LIMITED"}
# 인터넷 연결에 필요한 설정만 넘긴다(회사·학교 망의 프록시 등). 키·토큰은 여기에 없다.
_PASS_ENV = ("PATH", "LANG", "LC_ALL", "TZ", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "COMSPEC",
             "HTTPS_PROXY", "HTTP_PROXY", "NO_PROXY", "https_proxy", "http_proxy", "no_proxy",
             "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")
_CHANNEL_NAMES = {"youtube": "유튜브", "github": "GitHub", "web": "웹"}


class Unavailable(Exception):
    """설치되지 않았거나 설정에서 꺼져 있다."""


class ReachError(Exception):
    def __init__(self, message: str, code: str = ""):
        super().__init__(message)
        self.code = code  # Agent Reach 가 준 오류 이름(예: PLATFORM_BLOCKED)


class Stopped(ReachError):
    """플랫폼이 막아서 그 채널을 그날 멈췄다."""


class Failed(ReachError):
    """이번 한 건만 못 읽었다(글이 없음, 자막이 없음 등)."""


def home(cfg: dict) -> Path:
    return config.ROOT / cfg["home"]


def binary(cfg: dict) -> Path | None:
    base = home(cfg) / "venv"
    for p in (base / "bin" / "agent-reach", base / "Scripts" / "agent-reach.exe"):
        if p.exists():
            return p
    return None


def spec(cfg: dict) -> str:
    """pip 에 넘길 설치 주소. 저장소와 커밋은 설정 파일에만 있다."""
    return f"agent-reach @ git+{cfg['repo']}@{cfg['commit']}"


def install(cfg: dict, say=print) -> int:
    """따로 된 가상환경(.agent-reach/venv)을 만들고 고정한 커밋을 설치한다."""
    venv = home(cfg) / "venv"
    if not venv.exists():
        say(f"가상환경 만들기: {venv}")
        subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    py = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    say(f"설치: {spec(cfg)}")
    done = subprocess.run([str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check", spec(cfg)])
    return done.returncode


def _env(cfg: dict) -> dict:
    env = {k: os.environ[k] for k in _PASS_ENV if k in os.environ}
    state = home(cfg) / "state"  # 도구가 쓰는 설정·기록 폴더. 사용자의 홈 폴더를 건드리지 않는다
    state.mkdir(parents=True, exist_ok=True)
    env["HOME"] = env["USERPROFILE"] = str(state)
    bin_dir = str(binary(cfg).parent)
    env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    return env


class Reach:
    """하루 실탐 동안 쓰는 Agent Reach. 막힌 채널과 쓴 횟수를 기억한다."""

    def __init__(self, cfg: dict, runner=None):
        if not cfg.get("enabled"):
            raise Unavailable("Agent Reach가 설정에서 꺼져 있음")
        if runner is None and binary(cfg) is None:
            raise Unavailable("Agent Reach가 설치되지 않음 — python -m trendfeed agent-reach install")
        self.cfg, self.runner = cfg, runner or self._run
        self.stopped: dict[str, str] = {}   # 채널 → 멈춘 이유
        self.stopped_codes: dict[str, str] = {}
        self.used: dict[str, int] = {}      # 채널 → 성공한 횟수

    def allowed(self, channel: str) -> bool:
        return channel in self.cfg["channels"] and channel not in self.stopped

    def call(self, channel: str, action: str, *args: str) -> list[dict]:
        """한 번 부르고 읽은 것(items)을 돌려준다. 막히면 Stopped, 이번 건만 못 읽으면 Failed."""
        if channel not in self.cfg["channels"]:
            raise Unavailable(f"{channel} 채널은 설정에서 쓰지 않음")
        if channel in self.stopped:
            raise Stopped(self.stopped[channel], self.stopped_codes.get(channel, ""))
        out = self.runner([channel, action, *args])
        if out.get("ok"):
            self.used[channel] = self.used.get(channel, 0) + 1
            return out.get("items") or []
        err = out.get("error") or {}
        code = err.get("code", "")
        if code in STOP_CODES:
            why = "로봇 아님 확인을 요구함" if code == "PLATFORM_BLOCKED" else "횟수 제한에 걸림"
            self.stopped[channel] = f"{_CHANNEL_NAMES.get(channel, channel)}: {why} — 오늘은 더 부르지 않음"
            self.stopped_codes[channel] = code
            raise Stopped(self.stopped[channel], code)
        raise Failed(f"{code}: {str(err.get('message', ''))[:200]}", code)

    def _run(self, args: list[str]) -> dict:
        with tempfile.TemporaryDirectory(prefix="trendfeed-reach-") as tmp:  # repo 폴더(.env 가 있는 곳) 밖에서 돈다
            try:
                done = subprocess.run([str(binary(self.cfg)), *args], cwd=tmp, env=_env(self.cfg),
                                      capture_output=True, timeout=self.cfg["timeout_sec"])
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": {"code": "TIMEOUT", "message": f"{self.cfg['timeout_sec']}초 안에 끝나지 않음"}}
        try:
            return json.loads(done.stdout.decode("utf-8", errors="replace"))
        except ValueError:
            return {"ok": False, "error": {"code": "BAD_OUTPUT", "message": f"종료 코드 {done.returncode}"}}

    def summary(self) -> str:
        """피드에 적을 한 줄. 예: "Agent Reach(c70ae6d) 유튜브 자막 4 · GitHub 3 · 멈춤: 유튜브: …"."""
        used = " · ".join(f"{_CHANNEL_NAMES.get(k, k)} {v}회" for k, v in self.used.items()) or "부른 적 없음"
        text = f"Agent Reach({self.cfg['commit'][:7]}) {used}"
        if self.stopped:
            text += " · 멈춤: " + " / ".join(self.stopped.values())
        return text


def check(cfg: dict, say=print) -> int:
    """설치와 공개 채널이 이 컴퓨터(또는 Actions 서버)에서 되는지 한 번씩 확인한다. 저장하지 않는다.

    설정의 known_limits 에 적힌 (채널, 오류) 조합은 이미 알려진 한계라 "주의"로만 적고 실패로 치지 않는다.
    그 밖의 실패가 하나라도 있으면 1을 돌려준다(Actions 에서 빨간 ×).
    """
    known = {(c, code) for c, code in cfg.get("known_limits", [])}
    on_actions = os.environ.get("GITHUB_ACTIONS") == "true"
    try:
        reach = Reach(cfg)
    except Unavailable as e:
        say(f"Agent Reach: {e}")
        return 1
    version = reach.runner(["version"])
    say(f"Agent Reach 버전: {(version.get('result') or {}).get('version', '알 수 없음')} "
        f"(고정 커밋 {cfg['commit'][:12]})")
    bad = 0
    for channel, action, args in cfg["check_samples"]:
        if channel not in cfg["channels"]:
            continue
        label = f"{_CHANNEL_NAMES.get(channel, channel)} {action} {' '.join(args)}"
        try:
            items = reach.call(channel, action, *args)
            text = (items[0].get("text") or "") if items else ""
            say(f"  [정상] {label} → {len(items)}건, 글자 {len(text):,}자")
        except (Stopped, Failed) as e:
            if (channel, e.code) in known:
                say(f"  [주의] {label} → {e} (이미 알려진 한계)")
                if on_actions:  # Actions 화면에 노란 "주의"로 보이게
                    say(f"::warning title=Agent Reach 주의::{_CHANNEL_NAMES.get(channel, channel)} — {e} (이미 알려진 한계)")
            else:
                bad += 1
                say(f"  [안 됨] {label} → {e}")
                if on_actions:
                    say(f"::error title=Agent Reach 실패::{_CHANNEL_NAMES.get(channel, channel)} — {e}")
    return 1 if bad else 0
