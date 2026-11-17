"""Hacker News 인기글 — 공식 공개 API. 키가 필요 없다.

본문과 댓글은 여기서 읽지 않는다(실탐 단계의 일). 숫자는 점수와 댓글 수다.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlsplit

from . import CollectResult, Record

DISCUSS_URL = "https://news.ycombinator.com/item?id={id}"

# 하루 증가량을 잴 때 보는 숫자 (rank.py)
VELOCITY = {"metric": "score", "unit": "점"}


def origin_of(url: str | None, author: str | None) -> str | None:
    """출처. 링크가 있으면 그 사이트, 없으면(Ask HN 등) 글쓴이.

    github.com 은 한 사이트에 수많은 조직이 있어 'github.com/소유자'까지 본다.
    """
    if not url:
        return f"hn-user:{author}" if author else None
    parts = urlsplit(url)
    host = (parts.hostname or "").removeprefix("www.")
    if host == "github.com":
        owner = parts.path.strip("/").split("/")[0]
        if owner:
            return f"github.com/{owner.lower()}"
    return host or None


def to_record(data: dict | None, rank: int | None, listed: bool) -> Record | None:
    """API가 준 글 하나를 공통 모양으로 바꾼다. 지워졌거나 구인 공고면 None."""
    if not data or data.get("deleted") or data.get("dead"):
        return None
    if data.get("type") != "story" or not data.get("title"):
        return None
    discuss = DISCUSS_URL.format(id=data["id"])
    link = data.get("url")
    published = None
    if data.get("time"):
        published = datetime.fromtimestamp(data["time"], timezone.utc).isoformat()
    return Record(
        external_id=str(data["id"]),
        title=data["title"],
        url=link or discuss,
        origin=origin_of(link, data.get("by")),
        published_at=published,
        rank=rank,
        listed=listed,
        metrics={"score": data.get("score", 0), "comments": data.get("descendants", 0)},
        item_extra={"by": data.get("by"), "discuss_url": discuss},
    )


def _fetch_items(cfg: dict, fetch, ids: list) -> list[dict | None]:
    """글 여러 개를 동시에 읽는다. 읽지 못한 글은 Exception 으로 자리를 채운다."""

    def one(item_id):
        try:
            return fetch.get_json(f"{cfg['api_base']}/item/{item_id}.json")
        except Exception as e:  # 한 글의 실패가 전체를 멈추지 않게 한다
            return e

    with ThreadPoolExecutor(max_workers=cfg["workers"]) as pool:
        return list(pool.map(one, ids))


def collect(cfg: dict, fetch) -> CollectResult:
    """인기글 목록 위에서부터 limit 개를 모은다. 구인 공고·삭제된 글은 건너뛴다."""
    ids = fetch.get_json(f"{cfg['api_base']}/topstories.json")
    limit = cfg["limit"]
    records: list[Record] = []
    failed = 0
    pos = 0
    while len(records) < limit and pos < len(ids):
        batch = ids[pos : pos + limit - len(records)]
        pos += len(batch)
        results = _fetch_items(cfg, fetch, batch)
        errors = [r for r in results if isinstance(r, Exception)]
        failed += len(errors)
        for data in results:
            if isinstance(data, Exception):
                continue
            rec = to_record(data, rank=len(records) + 1, listed=True)
            if rec:
                records.append(rec)
        if len(errors) == len(batch):  # 한 묶음이 통째로 실패하면 더 두드리지 않는다
            break
    problems = [f"글 {failed}개를 읽지 못함"] if failed else []
    return CollectResult(records, problems)


def refetch(cfg: dict, fetch, external_ids: list[str]) -> CollectResult:
    """목록에서 빠진 글의 숫자만 다시 읽는다(어제와 오늘을 비교할 수 있게)."""
    results = _fetch_items(cfg, fetch, external_ids)
    failed = sum(isinstance(r, Exception) for r in results)
    records = []
    for data in results:
        if isinstance(data, Exception):
            continue
        rec = to_record(data, rank=None, listed=False)
        if rec:
            records.append(rec)
    problems = [f"다시 확인할 글 {failed}개를 읽지 못함"] if failed else []
    return CollectResult(records, problems)


def explore(cfg: dict, fetch, rng, n: int, exclude: set[str]) -> CollectResult:
    """탐색(명세 2번): 인기글 목록 밖, 최신 글(newstories)에서 무작위로 n개."""
    ids = [i for i in fetch.get_json(f"{cfg['api_base']}/newstories.json") if str(i) not in exclude]
    picked = rng.sample(ids, min(len(ids), n * 2))  # 지워진 글·구인 공고가 섞여 있어 넉넉히 읽는다
    records = []
    for data in _fetch_items(cfg, fetch, picked):
        if isinstance(data, Exception):
            continue
        rec = to_record(data, rank=None, listed=True)
        if rec and len(records) < n:
            records.append(rec)
    return CollectResult(records)
