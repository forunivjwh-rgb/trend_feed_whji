"""유튜브 인기 차트 — YouTube Data API v3 (무료 키 필요).

키는 .env 의 YOUTUBE_API_KEY 에서만 읽는다. 키가 없으면 이 소스만 건너뛴다.
키는 주소가 아니라 요청 머리말(헤더)로 보내서, 주소가 기록에 남더라도 키가 섞이지 않게 한다.

숫자는 조회수(주 숫자), 좋아요 수, 댓글 수다. 한 번 부르는 데 할당량 1을 쓴다(하루 한도 10,000).
이 차트는 2025-07-21부터 음악·영화·게임 차트의 영상으로 채워진다(명세 4번).
영상마다 댓글 위에서 20개(관련순)를 읽어 여러 댓글에 반복되는 말만 세고, 댓글 원문은 저장하지 않는다.
"""

from __future__ import annotations

import json
import urllib.error
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.parse import urlencode

from .. import config, phrases
from . import CollectResult, Record, SourceProblem

KEY_NAME = "YOUTUBE_API_KEY"
_PAGE_MAX = 50  # API가 한 번에 주는 최대 개수 (API의 규칙)

# 하루 증가량을 잴 때 보는 숫자 (rank.py)
VELOCITY = {"metric": "views", "unit": "회"}

# API가 알려 주는 거절 이유 → 사람이 읽을 말. 응답 본문은 그대로 옮기지 않는다.
_REASONS = {
    "API_KEY_INVALID": "API 키가 올바르지 않음 — .env 의 YOUTUBE_API_KEY 를 확인하세요",
    "keyInvalid": "API 키가 올바르지 않음 — .env 의 YOUTUBE_API_KEY 를 확인하세요",
    "quotaExceeded": "오늘 쓸 수 있는 요청 한도를 넘김 — 내일 다시 됩니다",
    "dailyLimitExceeded": "오늘 쓸 수 있는 요청 한도를 넘김 — 내일 다시 됩니다",
    "accessNotConfigured": "이 키의 프로젝트에서 YouTube Data API v3 가 켜져 있지 않음",
    "SERVICE_DISABLED": "이 키의 프로젝트에서 YouTube Data API v3 가 켜져 있지 않음",
    "API_KEY_SERVICE_BLOCKED": "이 키는 YouTube Data API v3 에 쓸 수 없게 제한돼 있음",
    "API_KEY_HTTP_REFERRER_BLOCKED": "이 키에 걸린 '웹사이트 제한' 때문에 거절됨 — 키 제한을 '없음'으로 바꾸세요",
    "API_KEY_IP_ADDRESS_BLOCKED": "이 키에 걸린 'IP 주소 제한' 때문에 거절됨 — 키 제한을 '없음'으로 바꾸세요",
}


def _key() -> str:
    key = config.secret(KEY_NAME)
    if not key:
        raise SourceProblem(f"API 키 없음 — .env 파일에 {KEY_NAME} 를 넣으면 켜집니다")
    return key


def _explain(e: urllib.error.HTTPError) -> str:
    try:
        error = json.loads(e.read().decode("utf-8", errors="replace"))["error"]
        reasons = [x.get("reason") for x in error.get("errors", []) + error.get("details", [])]
    except Exception:
        reasons = []
    for reason in reasons:
        if reason in _REASONS:
            return _REASONS[reason]
    return f"유튜브가 요청을 거절함 (HTTP {e.code})"


def _call(cfg: dict, fetch, key: str, params: dict) -> dict:
    url = f"{cfg['api_base']}/videos?{urlencode({'part': 'snippet,statistics', **params})}"
    try:
        return fetch.get_json(url, headers={"X-Goog-Api-Key": key})
    except urllib.error.HTTPError as e:
        raise SourceProblem(_explain(e)) from None


def _int(value) -> int | None:
    return int(value) if value is not None else None


def to_record(item: dict, rank: int | None, listed: bool, region: str | None) -> Record | None:
    snippet, stats = item.get("snippet") or {}, item.get("statistics") or {}
    video_id = item.get("id")
    if not video_id or not snippet.get("title"):
        return None
    published = None
    if snippet.get("publishedAt"):
        published = datetime.fromisoformat(snippet["publishedAt"]).astimezone(timezone.utc).isoformat()
    metrics = {  # 좋아요·댓글 수를 숨긴 영상은 그 숫자가 없다
        "views": _int(stats.get("viewCount")),
        "likes": _int(stats.get("likeCount")),
        "comments": _int(stats.get("commentCount")),
    }
    channel = snippet.get("channelId")
    return Record(
        external_id=video_id,
        title=snippet["title"],
        url=f"https://www.youtube.com/watch?v={video_id}",
        origin=f"youtube.com/channel/{channel}" if channel else "youtube.com",
        published_at=published,
        rank=rank,
        listed=listed,
        metrics={k: v for k, v in metrics.items() if v is not None},
        item_extra={"channel_title": snippet.get("channelTitle"), "category_id": snippet.get("categoryId")},
        snap_extra={"region": region} if region else {},
    )


def collect(cfg: dict, fetch) -> CollectResult:
    """지역마다 인기 차트를 위에서부터 limit 개까지 모은다. 여러 지역에 다 있는 영상은 한 번만 담는다."""
    key = _key()
    records: dict[str, Record] = {}
    for region in cfg["regions"]:
        params = {"chart": "mostPopular", "regionCode": region, "maxResults": _PAGE_MAX}
        while len(records) < cfg["limit"]:
            data = _call(cfg, fetch, key, params)
            for item in data.get("items", []):
                rec = to_record(item, rank=len(records) + 1, listed=True, region=region)
                if rec and rec.external_id not in records and len(records) < cfg["limit"]:
                    records[rec.external_id] = rec
            if not data.get("nextPageToken"):
                break
            params = {**params, "pageToken": data["nextPageToken"]}
    problems = _add_comment_phrases(cfg, fetch, key, list(records.values()))
    return CollectResult(list(records.values()), problems)


def top_comments(cfg: dict, fetch, key: str, video_id: str) -> list[str] | None:
    """영상의 댓글 위에서 몇 개(관련순)의 글자. 댓글이 막힌 영상은 None.

    받은 글자는 실행 중에만 쓰고 어디에도 저장하지 않는다. 한 번 부르는 데 할당량 1.
    """
    query = urlencode({"part": "snippet", "videoId": video_id, "order": "relevance",
                       "maxResults": cfg["comments_per_video"], "textFormat": "plainText"})
    try:
        data = fetch.get_json(f"{cfg['api_base']}/commentThreads?{query}", headers={"X-Goog-Api-Key": key})
    except urllib.error.HTTPError as e:
        message = _explain(e)
        if "한도" in message or "API 키" in message:  # 더 불러 봐야 소용없는 경우
            raise SourceProblem(message) from None
        return None  # 댓글 사용 중지 등: 이 영상만 건너뛴다
    texts = []
    for item in data.get("items", []):
        snippet = (((item.get("snippet") or {}).get("topLevelComment") or {}).get("snippet")) or {}
        text = snippet.get("textOriginal") or snippet.get("textDisplay")
        if text:
            texts.append(text)
    return texts


def _add_comment_phrases(cfg: dict, fetch, key: str, records: list[Record]) -> list[str]:
    """영상마다 댓글에서 반복되는 말을 세어 그날의 숫자 옆에 적는다(명세 4번). 원문은 버린다."""
    if not cfg.get("comments_per_video"):
        return []
    stopped: list[str] = []

    def one(rec: Record):
        if stopped:
            return
        try:
            texts = top_comments(cfg, fetch, key, rec.external_id)
        except SourceProblem as e:
            stopped.append(str(e))
            return
        except Exception:
            return
        if texts is None:
            return
        rec.snap_extra["comments_read"] = len(texts)
        found = phrases.repeated(
            texts, max_words=cfg["phrase_max_words"], min_comments=cfg["phrase_min_comments"],
            top=cfg["phrase_top"], min_chars=cfg["phrase_min_chars"],
            ignore_chars=cfg["phrase_ignore_chars"],
        )
        if found:
            rec.snap_extra["comment_phrases"] = found

    with ThreadPoolExecutor(max_workers=cfg["comment_workers"]) as pool:
        list(pool.map(one, records))
    return [f"댓글 읽기를 멈춤 — {stopped[0]}"] if stopped else []


def refetch(cfg: dict, fetch, external_ids: list[str]) -> CollectResult:
    """차트에서 빠진 영상의 숫자만 다시 읽는다. 50개씩 묶어 한 번에 부른다."""
    key = _key()
    records = []
    for i in range(0, len(external_ids), _PAGE_MAX):
        batch = external_ids[i : i + _PAGE_MAX]
        data = _call(cfg, fetch, key, {"id": ",".join(batch), "maxResults": _PAGE_MAX})
        for item in data.get("items", []):
            rec = to_record(item, rank=None, listed=False, region=None)
            if rec:
                records.append(rec)
    return CollectResult(records)
