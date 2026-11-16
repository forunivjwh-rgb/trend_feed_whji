"""롤업 — 일·주·월 요약 (명세 7번). 전부 코드가 계산한다. 기준선 14일 전에는 피드에서 숨긴다.

- 일: 어제와 오늘을 같은 점수식으로 계산한 순위를 비교한다. 5위 안에 새로 든 주제, 밖으로 나간 주제,
      가장 많이 오른 주제.
- 주: 지속 — 최근 7일 중 4위 안에 든 날이 많은 주제. 신규 — 처음 나타난 지 7일 안이고 오늘 8위 안.
      이탈 — 지난 6일 중 4위 안에 든 적이 있으나 오늘은 밖.
- 월: 한 주제(기본: 오늘 1위)를 플랫폼별로 나눈 28일 곡선(각 플랫폼 최대치 = 100)과, 각 플랫폼이
      최대치의 50%를 처음 넘은 날로 잰 플랫폼 간 시차.
"""

from __future__ import annotations

import json
from datetime import date

from . import score


def _ranks(conn, day: str) -> dict[str, int]:
    return {r[0]: r[1] for r in conn.execute(
        "SELECT topic_code, rank FROM topic_score WHERE date = ? AND rank IS NOT NULL", (day,))}


def _names(conn, codes) -> dict[str, str]:
    codes = list(codes)
    if not codes:
        return {}
    return dict(conn.execute(f"SELECT code, name FROM topics WHERE code IN ({','.join('?' * len(codes))})", codes))


def daily(conn, day: str, cfg: dict) -> dict:
    days = score.run_days(conn, day)
    if len(days) < 2:
        return {"entered": [], "left": [], "risers": []}
    today, yesterday = _ranks(conn, days[-1]), _ranks(conn, days[-2])
    top = cfg["daily_top"]
    now_in = {c for c, r in today.items() if r <= top}
    was_in = {c for c, r in yesterday.items() if r <= top}
    risers = sorted(((yesterday[c] - r, c) for c, r in today.items() if c in yesterday and yesterday[c] > r),
                    key=lambda x: (-x[0], today[x[1]]))[: cfg["daily_risers"]]
    names = _names(conn, now_in | was_in | {c for _, c in risers})
    return {
        "entered": [(c, names[c], yesterday.get(c), today[c]) for c in sorted(now_in - was_in, key=lambda c: today[c])],
        "left": [(c, names[c], yesterday[c], today.get(c)) for c in sorted(was_in - now_in, key=lambda c: yesterday[c])],
        "risers": [(c, names[c], yesterday[c], today[c]) for _, c in risers],
    }


def weekly(conn, day: str, cfg: dict) -> dict:
    days = score.run_days(conn, day)[-7:]
    top = cfg["weekly_top"]
    counts: dict[str, int] = {}
    for d in days:
        for c, r in _ranks(conn, d).items():
            if r <= top:
                counts[c] = counts.get(c, 0) + 1
    today = _ranks(conn, day)
    lasting = sorted((c for c, n in counts.items() if n >= 2), key=lambda c: (-counts[c], today.get(c, 10**6)))
    lasting = lasting[: cfg["weekly_n"]]
    past_in = set()
    for d in days[:-1]:
        past_in |= {c for c, r in _ranks(conn, d).items() if r <= top}
    left = sorted(past_in - {c for c, r in today.items() if r <= top})[: cfg["weekly_n"]]
    new_limit = date.fromisoformat(day).toordinal() - cfg["new_within_days"]
    rows = conn.execute(
        "SELECT s.topic_code, t.first_seen FROM topic_score s JOIN topics t ON t.code = s.topic_code "
        "WHERE s.date = ? AND s.rank IS NOT NULL AND s.rank <= ? ORDER BY s.rank", (day, cfg["new_top"])
    ).fetchall()
    fresh = [code for code, first_seen in rows if date.fromisoformat(first_seen).toordinal() > new_limit]
    names = _names(conn, set(lasting) | set(left) | set(fresh))
    return {
        "lasting": [(c, names[c], counts[c], len(days)) for c in lasting],
        "new": [(c, names[c], today[c]) for c in fresh[: cfg["weekly_n"]]],
        "left": [(c, names[c]) for c in left],
    }


def monthly(conn, day: str, code: str | None, cfg: dict) -> dict | None:
    """한 주제의 플랫폼별 28일 곡선(최대치 = 100)과 플랫폼 간 시차."""
    if code is None:
        return None
    days = score.run_days(conn, day)[-cfg["monthly_days"]:]
    raw: dict[str, list[float]] = {}
    by_day = {d: json.loads(p) for d, p in conn.execute(
        "SELECT date, platforms FROM topic_daily WHERE topic_code = ? AND date >= ? AND date <= ?",
        (code, days[0], day))}
    platforms = sorted({p for v in by_day.values() for p in v})
    for p in platforms:
        raw[p] = [by_day.get(d, {}).get(p, 0.0) for d in days]
    curves, first_half = {}, {}
    for p, values in raw.items():
        peak = max(values) or 1.0
        curves[p] = [round(100 * v / peak, 1) for v in values]
        first_half[p] = next(d for d, v in zip(days, values) if v >= peak * cfg["lag_ratio"])
    order = sorted(first_half, key=lambda p: first_half[p])
    lead = date.fromisoformat(first_half[order[0]]) if order else None
    lags = [(p, first_half[p], (date.fromisoformat(first_half[p]) - lead).days) for p in order]
    name = conn.execute("SELECT name FROM topics WHERE code = ?", (code,)).fetchone()[0]
    return {"code": code, "name": name, "days": days, "curves": curves, "lags": lags}
