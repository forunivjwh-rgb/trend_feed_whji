"""주제 단위 점수와 순위 (명세 5번). 전부 코드가 계산한다.

    score = min(max(z, 0), z_cap) + accel_weight·ln(max(a, 1)) + breadth_weight·(P − 1)
    z = (오늘 어텐션 − 중앙값) / (1.4826·MAD + z_floor)       기준선: 오늘 이전 최대 28일
    a = 최근 3일 평균 ÷ 최근 14일 평균 (오늘 포함)
    P = 주제가 나타난 플랫폼 수

- 날은 "수집이 돈 날"로 센다. 그날 주제가 없으면 그날 어텐션은 0이다.
- 기준선이 baseline_days(14일) 쌓이기 전에는 "지금 인기" 모드다: z와 가속을 끄고 오늘 어텐션 순으로만 매긴다.
- 순위에는 출처가 min_origins 곳 이상인 주제만 오른다("지금 인기" 모드에서는 early_min_origins).
- 점수가 threshold 이상이고 출처 조건도 맞으면 "임계 통과"다. "지금 인기" 모드에는 임계가 없다.
"""

from __future__ import annotations

import json
import math
import random
from statistics import median


def run_days(conn, day: str) -> list[str]:
    """수집이 돈 날들(오늘 포함, 오래된 날부터)."""
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT date FROM source_runs WHERE status != 'empty' AND date <= ? ORDER BY date", (day,)
    )]


def stats(series: list[float], cfg: dict) -> dict:
    """series 의 마지막 값이 오늘이다. z·가속을 계산한다(샘플 logic.js 의 statsAt 과 같은 식)."""
    today = series[-1]
    base = series[-1 - cfg["baseline_max_days"]:-1]
    med = median(base) if base else 0.0
    mad = median(abs(x - med) for x in base) if base else 0.0
    z = (today - med) / (cfg["mad_scale"] * mad + cfg["z_floor"])
    short, long_ = series[-cfg["accel_short_days"]:], series[-cfg["accel_long_days"]:]
    a_long = sum(long_) / len(long_)
    accel = (sum(short) / len(short)) / a_long if a_long > 0 else 1.0
    return {"median": med, "mad": mad, "z": z, "accel": accel}


def compute(conn, day: str, settings: dict) -> dict:
    """그날의 주제 점수와 순위를 계산해 topic_score 에 저장하고 요약을 돌려준다."""
    cfg = settings["score"]
    days = run_days(conn, day)
    early = len(days) < cfg["baseline_days"]
    window = days[-(cfg["baseline_max_days"] + 1):]
    rows = conn.execute(
        "SELECT d.*, t.field FROM topic_daily d JOIN topics t ON t.code = d.topic_code WHERE d.date = ?", (day,)
    ).fetchall()
    history: dict[str, dict[str, float]] = {}
    for r in conn.execute(
        "SELECT topic_code, date, attention FROM topic_daily WHERE date >= ? AND date <= ?", (window[0] if window else day, day)
    ):
        history.setdefault(r["topic_code"], {})[r["date"]] = r["attention"]

    scored = []
    for r in rows:
        platforms = json.loads(r["platforms"])
        breadth = len(platforms)
        entry = {"code": r["topic_code"], "attention": r["attention"], "origins": r["origins"],
                 "breadth": breadth, "field": r["field"], "z": None, "accel": None, "score": None}
        if not early:
            series = [history.get(r["topic_code"], {}).get(d, 0.0) for d in window]
            st = stats(series, cfg)
            entry["z"], entry["accel"] = st["z"], st["accel"]
            entry["score"] = (min(max(st["z"], 0.0), cfg["z_cap"])
                              + cfg["accel_weight"] * math.log(max(st["accel"], 1.0))
                              + cfg["breadth_weight"] * (breadth - 1))
        min_origins = cfg["early_min_origins"] if early else cfg["min_origins"]
        entry["eligible"] = r["origins"] >= min_origins
        entry["passed"] = (not early) and entry["eligible"] and entry["score"] >= cfg["threshold"]
        scored.append(entry)

    key = (lambda e: (-e["attention"], e["code"])) if early else (lambda e: (-e["score"], -e["attention"], e["code"]))
    scored.sort(key=key)
    place = 0
    for e in scored:
        if e["eligible"]:
            place += 1
            e["rank"] = place
        else:
            e["rank"] = None

    with conn:
        conn.execute("DELETE FROM topic_score WHERE date = ?", (day,))
        conn.executemany(
            "INSERT INTO topic_score (topic_code, date, mode, z, accel, breadth, origins, score, rank, passed) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(e["code"], day, "early" if early else "score", e["z"], e["accel"], e["breadth"], e["origins"],
              e["score"], e["rank"], int(e["passed"])) for e in scored],
        )
    return {"mode": "early" if early else "score", "days": len(days), "need": cfg["baseline_days"],
            "ranked": place, "passed": sum(e["passed"] for e in scored), "total": len(scored)}


def explore_picks(conn, day: str, settings: dict, exclude: set[str]) -> list[str]:
    """탐색 슬롯: 순위와 상관없이 무작위로 뽑은 주제 번호들(명세 6번).

    고르는 규칙은 명세의 열린 항목이라 시작값으로 정했다: 위에 이미 나온 주제를 빼고, 오늘 순위가
    explore_skip_top 위 밖인 주제 중에서 날짜를 씨앗으로 고르게 뽑는다(같은 날 다시 만들어도 같다).
    그 밖의 주제가 모자라면 위에 이미 나온 것만 빼고 나머지에서 채운다.
    첫 번째 것이 Top 5의 다섯째 자리에 오른다.
    """
    cfg = settings["score"]
    rows = conn.execute(
        "SELECT topic_code, rank FROM topic_score WHERE date = ? ORDER BY topic_code", (day,)
    ).fetchall()
    rng = random.Random(day)
    outside = [r["topic_code"] for r in rows
               if r["topic_code"] not in exclude and (r["rank"] is None or r["rank"] > cfg["explore_skip_top"])]
    picks = rng.sample(outside, min(cfg["explore_n"], len(outside)))
    if len(picks) < cfg["explore_n"]:  # 주제가 적은 날: 위에 이미 나온 것만 빼고 나머지에서 채운다
        rest = [r["topic_code"] for r in rows if r["topic_code"] not in exclude and r["topic_code"] not in picks]
        picks += rng.sample(rest, min(cfg["explore_n"] - len(picks), len(rest)))
    return picks
