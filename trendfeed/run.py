"""하루 수집: 소스마다 모으고 → 저장하고 → 실행 기록 한 줄을 남긴다.

한 소스가 실패해도 다른 소스는 계속한다.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from . import db
from .fetch import Fetcher
from .sources import registry

STATUS_LABEL = {"ok": "정상", "warn": "주의", "empty": "입력 없음"}


def collect_all(settings: dict, conn, day: str, only: str | None = None, fetch=None) -> list[dict]:
    fetch = fetch or Fetcher(settings["http"])
    summaries = []
    for name, module in registry().items():
        cfg = settings["sources"].get(name)
        if not cfg or not cfg.get("enabled") or (only and name != only):
            continue
        summaries.append(_collect_one(conn, day, name, module, cfg, fetch))
    return summaries


def _collect_one(conn, day: str, name: str, module, cfg: dict, fetch) -> dict:
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t0 = time.monotonic()
    records, followed, problems = [], [], []
    try:
        result = module.collect(cfg, fetch)
        records, problems = result.records, list(result.problems)
    except Exception as e:
        problems.append(f"수집 실패 ({_reason(e)})")

    # 목록에서 빠진 항목의 숫자 다시 적기. 오늘 목록을 받지 못한 날에도 한다.
    follow_days = cfg.get("follow_days", 0)
    if follow_days and hasattr(module, "refetch"):
        listed_today = {r.external_id for r in records}
        ids = [i for i in db.recently_listed(conn, day, name, follow_days) if i not in listed_today]
        if ids:
            try:
                again = module.refetch(cfg, fetch, ids)
                followed = again.records
                problems += again.problems
            except Exception as e:
                problems.append(f"다시 확인 실패 ({_reason(e)})")

    # 주의: 지금은 "일부만 실패"했을 때만 쓴다. "평소보다 크게 줄 때" 기준은
    # 실제 수집량을 본 뒤 정한다(명세 9번 열린 항목).
    status = "empty" if not records else ("warn" if problems else "ok")
    summary = {
        "source": name,
        "item_count": len(records),
        "followed_count": len(followed),
        "status": status,
        "memo": " · ".join(problems),
        "started_at": started,
        "duration_sec": time.monotonic() - t0,
    }
    with conn:  # 한 소스의 저장은 전부 되거나 전부 안 되거나
        db.save_records(conn, day, name, records + followed, captured_at=started)
        db.save_run(conn, day, **summary)
    return summary


def _reason(e: Exception) -> str:
    code = getattr(e, "code", None)
    return f"HTTP {code}" if code else type(e).__name__
