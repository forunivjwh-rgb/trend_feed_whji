""""지금 인기" 순위 — 전부 코드가 계산한다(LLM 없음).

1. 항목 속도: 항목마다 하루에 숫자가 얼마나 늘었는가.
2. 어텐션: 그 속도가 그날 그 소스의 가운데(중간값) 항목의 몇 배인가 × 소스 가중치.
   소스마다 숫자 크기가 달라서(HN 점수, GitHub 별) 이렇게 같은 잣대로 바꾼다.

주제 묶기가 붙기 전이라 지금은 항목 하나를 그대로 순위에 올린다. 결과는 저장하지 않고
스냅샷에서 그때그때 계산하므로, 식을 바꿔도 지난 날짜를 다시 계산할 수 있다.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from statistics import median

from .sources import module_for


def _hours_between(later: str, earlier: str) -> float:
    return (datetime.fromisoformat(later) - datetime.fromisoformat(earlier)).total_seconds() / 3600


def velocity(spec: dict, snap: dict, prev: dict | None, published_at: str | None, cfg: dict):
    """항목의 하루 증가량과 그 근거. 계산할 수 없으면 (None, None).

    spec 은 소스가 알려 주는 것: metric(주 숫자 열), reported_daily / reported_weekly
    (소스가 직접 알려 주는 증가량이 있을 때 그 이름), metric_is_daily(주 숫자가 이미
    하루치일 때), count_new(숫자가 없어 등장 횟수로 셀 때).
    """
    extra = snap["extra"]
    # 0) 숫자가 없는 소스(표결 없는 RSS 등)는 새로 올라온 날에 1건으로 센다.
    if spec.get("count_new"):
        if snap.get("first_seen") == snap["date"]:
            return 1.0, "새로 올라옴 · 숫자가 없어 등장 횟수로 셈"
        return 0.0, "이전에 이미 셈"
    value = snap[spec["metric"]]
    # 0') 주 숫자가 이미 "그날 하루의 값"인 소스(일간 조회수 등)는 그대로 쓴다.
    if spec.get("metric_is_daily"):
        return (float(value), "그날 하루의 값(소스 제공)") if value is not None else (None, None)
    # 1) 소스가 "오늘 늘어난 양"을 직접 알려 주면 그것이 가장 정확하다.
    reported = extra.get(spec.get("reported_daily"))
    if reported is not None:
        return float(reported), "오늘 늘어난 양(소스 제공)"
    # 2) 이전 기록이 있으면 그 차이를 실제 간격으로 나눈다.
    if prev is not None and value is not None and prev[spec["metric"]] is not None:
        hours = _hours_between(snap["captured_at"], prev["captured_at"])
        if hours >= cfg["min_gap_hours"]:
            per_day = max(0, value - prev[spec["metric"]]) / (hours / 24)
            return per_day, f"{prev['date'][5:].replace('-', '/')} 기록 대비"
    # 3) 주간 증가량만 있으면 7로 나눈다.
    weekly = extra.get(spec.get("reported_weekly"))
    if weekly is not None:
        return weekly / 7, "이번 주 늘어난 양 ÷ 7"
    # 4) 처음 본 항목: 올라온 뒤 지금까지의 하루 평균. 하루가 안 됐으면 지금 값 전부.
    if value is not None and published_at:
        age_days = _hours_between(snap["captured_at"], published_at) / 24
        if age_days <= 1:
            return float(value), "처음 봄 · 올라온 지 하루 안 됨"
        return value / age_days, f"처음 봄 · 올라온 뒤 {age_days:.1f}일 평균"
    return None, None


def now_popular(conn, day: str, settings: dict, explore: bool = False) -> list[dict]:
    """그날 목록에 있던 항목을 어텐션이 큰 순서로 돌려준다.

    탐색으로 뽑은 글(명세 2번)은 순위에 넣지 않고, 소스의 "보통 값"을 잴 때도 빼다.
    explore=True 면 탐색 글만, 목록 글로 잰 보통 값에 견준 어텐션과 함께 돌려준다.
    """
    cfg = settings["attention"]
    since = (date.fromisoformat(day) - timedelta(days=cfg["compare_within_days"])).isoformat()
    prev_by_item: dict[int, dict] = {}
    for row in conn.execute(
        "SELECT * FROM item_snapshots WHERE date < ? AND date >= ? ORDER BY date", (day, since)
    ):
        prev_by_item[row["item_id"]] = dict(row)  # 날짜순이라 마지막에 남는 것이 가장 최근 기록

    entries = []
    for row in conn.execute(
        """
        SELECT s.*, i.source, i.external_id, i.title, i.url, i.origin, i.published_at, i.first_seen, i.extra AS item_extra
        FROM item_snapshots s JOIN items i ON i.id = s.item_id
        WHERE s.date = ? AND s.listed = 1
        """,
        (day,),
    ):
        snap = dict(row)
        snap["extra"] = json.loads(snap["extra"])
        snap["item_extra"] = json.loads(snap["item_extra"])
        spec = module_for(snap["source"], settings["sources"][snap["source"]]).VELOCITY
        v, basis = velocity(spec, snap, prev_by_item.get(snap["item_id"]), snap["published_at"], cfg)
        snap.update(velocity=v, basis=basis, unit=spec["unit"], explore=bool(snap["extra"].get("explore")))
        entries.append(snap)

    # 소스 안에서 "가운데 항목"(목록 글만)의 속도로 나눈다.
    for source in {e["source"] for e in entries}:
        group = [e for e in entries if e["source"] == source and e["velocity"] is not None]
        main = [e["velocity"] for e in group if not e["explore"]]
        if not group:
            continue
        typical = max(median(main) if main else median(e["velocity"] for e in group), cfg["median_floor"])
        weight = settings["sources"][source]["weight"]
        for e in group:
            e["typical"] = typical
            e["times_typical"] = e["velocity"] / typical
            e["attention"] = e["times_typical"] * weight

    ranked = [e for e in entries if e.get("attention") is not None and e["explore"] == explore]
    ranked.sort(key=lambda e: (-e["attention"], e["source"], e["rank"] or 0))
    for i, e in enumerate(ranked, start=1):
        e["place"] = i
    return ranked


def baseline_days(conn, day: str) -> int:
    """기준선을 만들 날이 며칠 쌓였는가: 수집에 성공한 날 수(오늘 포함)."""
    return conn.execute(
        "SELECT COUNT(DISTINCT date) FROM source_runs WHERE status != 'empty' AND date <= ?", (day,)
    ).fetchone()[0]
