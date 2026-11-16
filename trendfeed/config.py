"""설정 파일(config/settings.toml)을 읽는다. 숫자와 한도는 코드에 박지 않고 여기서만 온다."""

from __future__ import annotations

import tomllib
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PATH = ROOT / "config" / "settings.toml"
ENV_PATH = ROOT / ".env"  # 키를 두는 유일한 곳. git에 올리지 않는다


def load(path: Path | None = None) -> dict:
    with open(path or DEFAULT_PATH, "rb") as f:
        return tomllib.load(f)


def db_path(settings: dict) -> Path:
    p = Path(settings["general"]["db_path"])
    return p if p.is_absolute() else ROOT / p


def today(settings: dict) -> str:
    """설정한 시간대 기준 오늘 날짜(YYYY-MM-DD)."""
    return datetime.now(ZoneInfo(settings["general"]["timezone"])).date().isoformat()


def secret(name: str) -> str | None:
    """키 하나를 읽는다. .env 파일(이름=값 한 줄씩)에서 찾고, 없으면 None.

    값은 어디에도 출력하거나 저장하지 않는다. 메모장이 붙이는 보이지 않는 머리글자(BOM)와
    값을 감싼 따옴표는 걷어 낸다.
    """
    try:
        text = ENV_PATH.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip().removeprefix("export ").strip() == name:
            return value.strip().strip("\"'") or None
    return None
