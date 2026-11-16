"""매일 자동 실행 등록.

- 윈도우: 작업 스케줄러. 놓친 실행은 컴퓨터를 켠 뒤 가능한 한 빨리 돌린다.
- 맥: launchd(맥의 예약 실행기).

둘 다 `python -m trendfeed daily` 를 하루 한 번 돌리게 한다. 시각은 설정 파일에서 온다.
"""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path
from xml.sax.saxutils import escape

from .config import ROOT

LABEL = "com.trendfeed.daily"      # 맥에서의 이름
TASK_NAME = "TrendFeed Daily"      # 윈도우 작업 스케줄러에서의 이름
ARGS = ["-m", "trendfeed", "daily"]


class Unsupported(RuntimeError):
    pass


# ---------- 윈도우 ----------

def windows_python() -> str:
    """검은 창이 뜨지 않는 pythonw.exe 가 옆에 있으면 그것을 쓴다."""
    exe = Path(sys.executable)
    quiet = exe.with_name("pythonw.exe")
    return str(quiet if quiet.exists() else exe)


def build_windows_xml(settings: dict, python: str | None = None) -> str:
    s, limits = settings["schedule"], settings["schedule"]["windows"]
    start = f"2026-01-01T{s['hour']:02d}:{s['minute']:02d}:00"  # 날짜는 형식상 필요할 뿐, 매일 이 시각에 돈다
    yes_no = lambda b: "true" if b else "false"  # noqa: E731
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>유행 피드: 매일 수집하고 피드를 만든다</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay>
        <DaysInterval>1</DaysInterval>
      </ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <StartWhenAvailable>{yes_no(limits["run_missed_asap"])}</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <WakeToRun>{yes_no(limits["wake_to_run"])}</WakeToRun>
    <ExecutionTimeLimit>PT{limits["time_limit_hours"]}H</ExecutionTimeLimit>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(python or windows_python())}</Command>
      <Arguments>{escape(" ".join(ARGS))}</Arguments>
      <WorkingDirectory>{escape(str(ROOT))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def _install_windows(settings: dict) -> str:
    xml = build_windows_xml(settings)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "trendfeed-task.xml"
        path.write_text(xml, encoding="utf-16")  # 작업 스케줄러가 읽는 글자 형식
        subprocess.run(["schtasks", "/Create", "/TN", TASK_NAME, "/XML", str(path), "/F"], check=True)
    return f"작업 스케줄러의 '{TASK_NAME}'"


def _uninstall_windows() -> None:
    subprocess.run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], check=True)


# ---------- 맥 ----------

def build_plist(settings: dict) -> bytes:
    log = str(ROOT / "data" / "logs" / "launchd.log")  # 프로그램이 아예 못 뜬 경우의 오류만 여기 남는다
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": [sys.executable, *ARGS],
            "WorkingDirectory": str(ROOT),
            "StartCalendarInterval": {
                "Hour": settings["schedule"]["hour"],
                "Minute": settings["schedule"]["minute"],
            },
            "StandardOutPath": log,
            "StandardErrorPath": log,
        }
    )


def _mac_plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _install_mac(settings: dict) -> str:
    path = _mac_plist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "logs").mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_plist(settings))
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True)  # 없으면 실패해도 된다
    subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
    return str(path)


def _uninstall_mac() -> None:
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    _mac_plist_path().unlink(missing_ok=True)


# ---------- 공통 ----------

def install(settings: dict) -> str:
    """예약을 등록한다. 이미 있으면 새 내용으로 바꾼다. 등록한 곳을 돌려준다."""
    if sys.platform == "win32":
        return _install_windows(settings)
    if sys.platform == "darwin":
        return _install_mac(settings)
    raise Unsupported("자동 실행 등록은 윈도우와 맥에서만 됩니다.")


def uninstall() -> None:
    if sys.platform == "win32":
        _uninstall_windows()
    elif sys.platform == "darwin":
        _uninstall_mac()
    else:
        raise Unsupported("자동 실행 등록은 윈도우와 맥에서만 됩니다.")


def preview(settings: dict, target: str | None = None) -> str:
    """등록될 내용을 글자로 보여 준다. target: "windows" | "mac" | None(지금 컴퓨터)."""
    target = target or {"win32": "windows", "darwin": "mac"}.get(sys.platform)
    if target == "windows":
        return build_windows_xml(settings)
    if target == "mac":
        return build_plist(settings).decode()
    raise Unsupported("자동 실행 등록은 윈도우와 맥에서만 됩니다.")
