"""Wikipedia 일간 조회수 상위 문서 — 위키미디어 공개 조회수 API. 키가 필요 없다.

언어판 하나가 소스 하나다(설정의 project). 조회수는 이미 "그날 하루의 값"이다.
하루치 집계는 다음 날(UTC) 몇 시간 뒤에 나오므로, 어제 치가 아직 없으면 그 전날로 거슬러 찾는다.
문서 본문은 여기서 읽지 않는다(실탐 단계의 일).
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from . import CollectResult, Record

# 하루 증가량을 잴 때 보는 숫자 (rank.py): 조회수는 이미 하루치다.
VELOCITY = {"metric": "views", "unit": "회", "metric_is_daily": True}

# 문서가 아닌 페이지(대문, 검색, 운영용 이름공간)는 유행이 아니라서 뺀다.
_NOT_ARTICLES = {"Main_Page", "-"}
_NAMESPACES = (
    "Special:", "Wikipedia:", "File:", "Portal:", "Help:", "Category:", "Template:", "Talk:", "User:",
    "Draft:", "Media:", "MediaWiki:", "Module:", "User_talk:", "Wikipedia_talk:", "Template_talk:",
    "특수:", "위키백과:", "파일:", "포털:", "도움말:", "분류:", "틀:", "토론:", "사용자:", "초안:",
    "미디어위키:", "모듈:", "사용자토론:", "위키백과토론:", "틀토론:", "위키프로젝트:",
)


def _utc_today() -> date:
    return datetime.now(timezone.utc).date()


def is_article(name: str) -> bool:
    return name not in _NOT_ARTICLES and not name.startswith(_NAMESPACES)


def to_records(project: str, articles: list[dict], views_date: str, limit: int) -> list[Record]:
    records = []
    for a in articles:
        name = a.get("article")
        if not name or not is_article(name) or a.get("views") is None:
            continue
        records.append(
            Record(
                external_id=name,
                title=name.replace("_", " "),
                url=f"https://{project}.org/wiki/{quote(name)}",
                origin=f"{project}.org",
                published_at=None,
                rank=len(records) + 1,
                metrics={"views": a["views"]},
                snap_extra={"views_date": views_date},  # 이 조회수가 어느 날(UTC)의 것인지
            )
        )
        if len(records) == limit:
            break
    return records


def collect(cfg: dict, fetch) -> CollectResult:
    today = _utc_today()
    for back in range(1, cfg["lookback_days"] + 1):
        if back > 1:
            time.sleep(cfg["pause_sec"])
        d = today - timedelta(days=back)
        url = f"{cfg['api_base']}/{cfg['project']}/all-access/{d:%Y/%m/%d}"
        try:
            data = fetch.get_json(url)
        except Exception as e:
            if getattr(e, "code", None) == 404:  # 그날 치가 아직 안 나왔다 → 하루 더 거슬러 본다
                continue
            raise
        records = to_records(cfg["project"], data["items"][0]["articles"], d.isoformat(), cfg["limit"])
        problems = [f"어제 치가 아직 없어 {d:%m/%d} 조회수를 씀"] if back > 1 else []
        return CollectResult(records, problems)
    return CollectResult([], [f"최근 {cfg['lookback_days']}일 치 조회수가 아직 나오지 않음"])
