"""하루 수집: 소스마다 모으고 → 저장하고 → 실행 기록 한 줄을 남긴다.

한 소스가 실패해도 다른 소스는 계속한다.
"""

from __future__ import annotations

import random
import time
from statistics import median
from datetime import datetime, timezone

from . import db
from .fetch import Fetcher
from .sources import Blocked, SourceProblem, module_for

STATUS_LABEL = {"ok": "정상", "warn": "주의", "empty": "입력 없음"}


def collect_all(settings: dict, conn, day: str, only: str | None = None, fetch=None) -> list[dict]:
    fetch = fetch or Fetcher(settings["http"])
    summaries = []
    for name, cfg in settings["sources"].items():
        if not cfg.get("enabled") or (only and name != only):
            continue
        summaries.append(_collect_one(conn, day, name, module_for(name, cfg), cfg, fetch, settings.get("status"),
                                      settings.get("explore")))
    return summaries


def _usual_count(conn, day: str, source: str, status_cfg: dict | None) -> float | None:
    """이 소스가 평소 하루에 모은 건수(지난 며칠의 중앙값). 기록이 모자라면 None."""
    if not status_cfg or not status_cfg["drop_ratio"]:
        return None  # 기준을 정하지 않았으면(0) 판단하지 않는다
    counts = [r[0] for r in conn.execute(
        "SELECT item_count FROM source_runs WHERE source = ? AND date < ? AND status != 'empty' ORDER BY date DESC LIMIT ?",
        (source, day, status_cfg["lookback_days"]),
    )]
    if len(counts) < status_cfg["min_days"]:
        return None
    return float(median(counts))


def _explore(day: str, name: str, module, cfg: dict, fetch, explore_cfg: dict | None, main_count: int,
             exclude: set[str]) -> tuple[list, list[str]]:
    """탐색 슬롯(명세 2번): 목록 밖에서 무작위로 뽑은 글. (글들, 알릴 말들). 실패해도 수집은 계속한다."""
    if not explore_cfg or not explore_cfg["enabled"] or not hasattr(module, "explore") or not main_count:
        return [], []
    share = explore_cfg["share"]
    n = round(main_count * share / (1 - share))
    rng = random.Random(f"{day}:{name}")  # 같은 날 다시 돌려도 같은 것을 뽑는다
    try:
        result = module.explore(cfg, fetch, rng, n, exclude)
    except Exception as e:
        return [], [f"탐색 실패 ({e if isinstance(e, SourceProblem) else _reason(e)})"]
    for rec in result.records:
        rec.snap_extra["explore"] = 1
    return result.records, list(result.problems)


def _collect_one(conn, day: str, name: str, module, cfg: dict, fetch, status_cfg: dict | None = None,
                 explore_cfg: dict | None = None) -> dict:
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    t0 = time.monotonic()
    records, followed, problems = [], [], []
    blocked = False
    try:
        result = module.collect(cfg, fetch)
        records, problems = result.records, list(result.problems)
    except SourceProblem as e:  # 소스가 이유를 직접 알려 준 경우(예: 키 없음, 서버에서 막힘)
        problems.append(str(e))
        blocked = isinstance(e, Blocked)
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
            except SourceProblem as e:
                if str(e) not in problems:
                    problems.append(str(e))
            except Exception as e:
                problems.append(f"다시 확인 실패 ({_reason(e)})")

    explored, notes = _explore(day, name, module, cfg, fetch, explore_cfg, len(records),
                               {r.external_id for r in records + followed})

    with conn:  # 한 소스의 저장은 전부 되거나 전부 안 되거나
        db.save_records(conn, day, name, records + followed + explored, captured_at=started)
        # 하루에 여러 번 돌 수 있으므로 건수는 "오늘 하루 목록에 있었던 항목 수"로 센다.
        # 이번 실행이 실패해도 앞선 실행이 모은 것은 그대로 남는다.
        day_count = db.listed_count(conn, day, name)
        # 주의: 일부만 실패했거나, 상대 서버가 막았거나, 평소보다 크게 줄었을 때(명세 3번).
        usual = _usual_count(conn, day, name, status_cfg)
        if day_count and usual and day_count < usual * status_cfg["drop_ratio"]:
            problems.append(f"평소보다 크게 줄었음 (평소 {usual:.0f}건 → 오늘 {day_count}건)")
        if problems and (day_count or blocked):
            status = "warn"
        else:
            status = "ok" if day_count else "empty"
        summary = {
            "source": name,
            "item_count": day_count,
            "followed_count": len(followed),
            "status": status,
            "memo": " · ".join(problems + notes),  # 탐색에서 생긴 일은 알리기만 하고 "주의"로 치지 않는다
            "started_at": started,
            "duration_sec": time.monotonic() - t0,
        }
        db.save_run(conn, day, **summary)
        summary["explore_count"] = db.explore_count(conn, day, name)
    return summary


def _reason(e: Exception) -> str:
    code = getattr(e, "code", None)
    return f"HTTP {code}" if code else type(e).__name__
