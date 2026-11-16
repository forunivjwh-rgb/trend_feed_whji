"""실탐(깊게 읽기) — "그게 뭔데?"에 답하는 단계 (명세 6번).

위에 오른 항목의 원문을 읽고 LLM으로 요약한다. 숫자와 순위는 이미 코드가 계산했다.

지금은 임시 방식이다:
- 주제 묶기와 "평소 대비" 점수가 아직 없어, "지금 인기" 위에서 몇 건을 대상으로 한다.
- 읽는 도구는 명세의 Agent Reach 대신 각 소스의 공개 주소에서 직접 읽는다.
읽은 원문은 요약에만 쓰고 저장하지 않는다. 남는 것은 요약과 "어디까지 읽었나"뿐이다.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from html import unescape
from urllib.parse import quote, urlencode

from . import db, llm, rank

_TAG = re.compile(r"<[^>]+>")
_DROP = re.compile(r"<(script|style|noscript|svg|head)\b.*?</\1>", re.S | re.I)


def html_to_text(html: str) -> str:
    """웹 페이지에서 글자만 남긴다(대강)."""
    return " ".join(unescape(_TAG.sub(" ", _DROP.sub(" ", html))).split())


def _clip(text: str, limit: int) -> tuple[str, bool]:
    return (text[:limit], True) if len(text) > limit else (text, False)


# ---------- 소스별로 읽는 법. (읽은 글자, 읽은 범위 설명)을 돌려준다. 못 읽으면 예외. ----------

def _read_hackernews(e: dict, cfg: dict, sources: dict, fetch) -> tuple[str, str]:
    parts, scope = [], []
    if e["url"] != e["item_extra"].get("discuss_url"):
        try:
            body, cut = _clip(html_to_text(fetch.get_text(e["url"])), cfg["max_chars"])
            if body:
                parts.append(f"[링크된 글]\n{body}")
                scope.append(f"링크 원문 {'앞 ' if cut else ''}{len(body):,}자")
        except Exception:
            scope.append("링크 원문은 열지 못함")
    api = sources["hackernews"]["api_base"]
    story = fetch.get_json(f"{api}/item/{e['external_id']}.json") or {}
    kids = (story.get("kids") or [])[: cfg["comments"]]

    def one(kid):
        try:
            return fetch.get_json(f"{api}/item/{kid}.json") or {}
        except Exception:
            return {}

    with ThreadPoolExecutor(max_workers=sources["hackernews"]["workers"]) as pool:
        comments = [html_to_text(c.get("text") or "") for c in pool.map(one, kids)]
    comments = [c for c in comments if c]
    if story.get("text"):
        parts.append(f"[본문]\n{html_to_text(story['text'])}")
    if comments:
        joined, _ = _clip("\n- ".join(comments), cfg["max_chars"])
        parts.append(f"[댓글]\n- {joined}")
        scope.append(f"HN 댓글 상위 {len(comments)}")
    return "\n\n".join(parts), " · ".join(scope)


def _read_readme(url: str, label: str, cfg: dict, fetch) -> tuple[str, str]:
    body, cut = _clip(fetch.get_text(url), cfg["max_chars"])
    return body, f"{label} {'앞 ' if cut else ''}{len(body):,}자"


def _read_github(e, cfg, sources, fetch):
    return _read_readme(f"https://raw.githubusercontent.com/{e['external_id']}/HEAD/README.md", "README", cfg, fetch)


def _read_huggingface(e, cfg, sources, fetch):
    return _read_readme(f"https://huggingface.co/{e['external_id']}/raw/main/README.md", "모델 카드", cfg, fetch)


def _read_wikipedia(e, cfg, sources, fetch):
    host = e["origin"]  # 예: ko.wikipedia.org
    query = urlencode({"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1,
                       "format": "json", "formatversion": 2, "titles": e["external_id"].replace("_", " ")})
    pages = fetch.get_json(f"https://{host}/w/api.php?{query}")["query"]["pages"]
    body, cut = _clip(pages[0].get("extract") or "", cfg["max_chars"])
    return body, f"문서 본문 {'앞 ' if cut else ''}{len(body):,}자"


READERS = {
    "hackernews": _read_hackernews,
    "github_trending": _read_github,
    "huggingface": _read_huggingface,
    "wikipedia": _read_wikipedia,
    # GeekNews 는 글 페이지가 자동 읽기를 거절(403)해서 읽지 않는다. 유튜브는 아직 읽는 법이 없다.
}


def run(conn, day: str, settings: dict, fetch, client=None, say=print) -> dict:
    """오늘의 실탐. 결과 요약(읽은 건수 등)을 돌려준다. LLM을 못 쓰면 이 단계만 건너뛴다."""
    cfg, llm_cfg, sources = settings["deepread"], settings["llm"], settings["sources"]
    result = {"read": 0, "skipped": 0, "failed": 0, "note": ""}
    if not cfg["enabled"]:
        result["note"] = "실탐이 설정에서 꺼져 있음"
        return result
    if client is None:
        try:
            client = llm.make_client()
        except llm.Unavailable as e:
            result["note"] = f"{e} — 실탐·요약은 건너뜀"
            say(f"  실탐: {result['note']}")
            return result

    since = (date.fromisoformat(day) - timedelta(days=cfg["no_reread_days"])).isoformat()
    recent = {r[0] for r in conn.execute("SELECT item_id FROM deepreads WHERE date > ?", (since,))}
    deadline = time.monotonic() + cfg["budget_minutes"] * 60
    for e in rank.now_popular(conn, day, settings)[: cfg["top_n"]]:
        module_name = sources[e["source"]].get("module", e["source"])
        reader = READERS.get(module_name)
        if e["item_id"] in recent or reader is None:
            result["skipped"] += 1  # 7일 안에 이미 읽었거나, 아직 읽는 법이 없는 소스
            continue
        if time.monotonic() > deadline:
            result["note"] = f"시간 예산 {cfg['budget_minutes']}분을 다 써서 멈춤"
            break
        if result["read"] or result["failed"]:
            time.sleep(cfg["pause_sec"])  # 같은 곳을 연달아 두드리지 않는다
        try:
            material, scope = reader(e, cfg, sources, fetch)
        except Exception:
            material, scope = "", ""
        if len(material) < cfg["min_chars"]:
            result["failed"] += 1  # 원문을 못 읽었으면 지어내지 않고 넘어간다
            continue
        try:
            summary, usage = llm.summarize(client, llm_cfg, e["title"], material)
        except Exception as err:
            result["note"] = f"{llm.explain_error(err)} — 남은 실탐은 건너뜀"
            break
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with conn:
            db.save_llm_call(conn, day, created_at=now, purpose="deepread",
                             ref=f"{e['source']}:{e['external_id']}", model=llm_cfg["model"], **usage)
            if summary:
                db.save_deepread(conn, day, e["item_id"], scope=scope, model=llm_cfg["model"], **summary)
        if summary:
            result["read"] += 1
        else:
            result["failed"] += 1
    say(f"  실탐: 요약 {result['read']}건 · 건너뜀 {result['skipped']}건 · 실패 {result['failed']}건"
        + (f" — {result['note']}" if result["note"] else ""))
    return result
