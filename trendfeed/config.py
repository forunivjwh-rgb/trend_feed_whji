"""설정 파일(config/settings.toml)을 읽는다. 숫자와 한도는 코드에 박지 않고 여기서만 온다."""

from __future__ import annotations

import tomllib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "config" / "settings.toml"


def load(path: Path | None = None) -> dict:
    with open(path or DEFAULT_PATH, "rb") as f:
        return tomllib.load(f)


def db_path(settings: dict) -> Path:
    p = Path(settings["general"]["db_path"])
    return p if p.is_absolute() else ROOT / p


def today(settings: dict) -> str:
    """설정한 시간대 기준 오늘 날짜(YYYY-MM-DD)."""
    return datetime.now(ZoneInfo(settings["general"]["timezone"])).date().isoformat()
