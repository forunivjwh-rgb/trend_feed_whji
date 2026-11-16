"""매일 자동 실행 등록(맥 전용). 맥의 예약 실행기 launchd 에 하루 한 번 돌리라고 알려 준다."""

from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

from .config import ROOT

LABEL = "com.trendfeed.daily"


def build_plist(settings: dict) -> bytes:
    log = str(ROOT / "data" / "logs" / "daily.log")
    return plistlib.dumps(
        {
            "Label": LABEL,
            "ProgramArguments": [sys.executable, "-m", "trendfeed", "collect"],
            "WorkingDirectory": str(ROOT),
            "StartCalendarInterval": {
                "Hour": settings["schedule"]["hour"],
                "Minute": settings["schedule"]["minute"],
            },
            "StandardOutPath": log,
            "StandardErrorPath": log,
        }
    )


def install(settings: dict) -> Path:
    """예약 파일을 쓰고 등록한다. 이미 등록돼 있으면 새 내용으로 바꾼다."""
    if sys.platform != "darwin":
        raise RuntimeError("자동 실행 등록은 맥에서만 됩니다.")
    path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    path.parent.mkdir(parents=True, exist_ok=True)
    (ROOT / "data" / "logs").mkdir(parents=True, exist_ok=True)
    path.write_bytes(build_plist(settings))
    domain = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", f"{domain}/{LABEL}"], capture_output=True)  # 없으면 실패해도 된다
    subprocess.run(["launchctl", "bootstrap", domain, str(path)], check=True)
    return path


def uninstall() -> None:
    if sys.platform != "darwin":
        raise RuntimeError("자동 실행 등록은 맥에서만 됩니다.")
    path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    subprocess.run(["launchctl", "bootout", f"gui/{os.getuid()}/{LABEL}"], capture_output=True)
    path.unlink(missing_ok=True)
