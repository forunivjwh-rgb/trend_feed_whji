"""Hugging Face 인기(trending) 모델 — 공개 API. 키가 필요 없다.

숫자는 좋아요 수(주 숫자), 다운로드 수, Hugging Face가 매긴 trending 점수다.
모델 카드 본문은 여기서 읽지 않는다(실탐 단계의 일).
"""

from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlencode

from . import CollectResult, Record

# 하루 증가량을 잴 때 보는 숫자 (rank.py)
VELOCITY = {"metric": "likes", "unit": " 좋아요"}


def to_record(data: dict, rank: int) -> Record | None:
    model_id = data.get("id")
    if not model_id or data.get("private"):
        return None
    owner = model_id.split("/")[0] if "/" in model_id else None
    published = None
    if data.get("createdAt"):
        published = datetime.fromisoformat(data["createdAt"]).astimezone(timezone.utc).isoformat()
    snap_extra = {}
    if data.get("downloads") is not None:
        snap_extra["downloads"] = data["downloads"]
    if data.get("trendingScore") is not None:
        snap_extra["trending_score"] = data["trendingScore"]
    return Record(
        external_id=model_id,
        title=model_id,
        url=f"https://huggingface.co/{model_id}",
        origin=f"huggingface.co/{owner.lower()}" if owner else "huggingface.co",
        published_at=published,
        rank=rank,
        metrics={"likes": data.get("likes", 0)},
        item_extra={"kind": data.get("pipeline_tag")},
        snap_extra=snap_extra,
    )


def collect(cfg: dict, fetch) -> CollectResult:
    query = urlencode({"sort": "trendingScore", "direction": -1, "limit": cfg["limit"]})
    data = fetch.get_json(f"{cfg['api_base']}/models?{query}")
    records = []
    for entry in data:
        rec = to_record(entry, rank=len(records) + 1)
        if rec:
            records.append(rec)
    return CollectResult(records)


def explore(cfg: dict, fetch, rng, n: int, exclude: set[str]) -> CollectResult:
    """탐색(명세 2번): 인기 모델 위 limit 개 밖(limit+1 ~ explore_pool 위)에서 무작위로 n개."""
    query = urlencode({"sort": "trendingScore", "direction": -1, "limit": cfg["explore_pool"]})
    data = fetch.get_json(f"{cfg['api_base']}/models?{query}")[cfg["limit"]:]
    candidates = [d for d in data if d.get("id") and d["id"] not in exclude and not d.get("private")]
    records = []
    for d in rng.sample(candidates, min(len(candidates), n)):
        rec = to_record(d, rank=0)
        if rec:
            rec.rank = None
            records.append(rec)
    return CollectResult(records)
