"""실탐(깊게 읽기) — "그게 뭔데?"에 답하는 단계 (명세 6번).

메타데이터로 순위를 매긴 뒤(코드), 어텐션이 높은 주제만 원문을 읽고 LLM으로 요약한다.
주제마다 대표·발단·최다 논의 1~3건을 읽고 LLM은 주제당 1번. 시간이 남으면 탐색 슬롯을 읽는다.

읽는 도구: Agent Reach(사용자 포크의 고정 커밋)로 유튜브 자막과 GitHub README·이슈를 읽는다.
Agent Reach가 없거나 그날 막히면, 그리고 그 밖의 소스는 각 소스의 공개 주소에서 직접 읽는다.
읽은 범위에는 Agent Reach로 읽은 부분을 "(Agent Reach)"로 표시한다.
읽은 원문은 요약에만 쓰고 저장하지 않는다. 남는 것은 요약과 "어디까지 읽었나"뿐이다.
"""

from __future__ import annotations

import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from html import unescape
from urllib.parse import quote, urlencode

from . import agentreach, db, llm, rank

_TAG = re.compile(r"<[^>]+>")
_DROP = re.compile(r"<(script|style|noscript|svg|head)\b.*?</\1>", re.S | re.I)


def html_to_text(html: str) -> str:
    """웹 페이지에서 글자만 남긴다(대강)."""
    return " ".join(unescape(_TAG.sub(" ", _DROP.sub(" ", html))).split())


def _clip(text: str, limit: int) -> tuple[str, bool]:
    return (text[:limit], True) if len(text) > limit else (text, False)


# ---------- 소스별로 읽는 법. (읽은 글자, 읽은 범위 설명)을 돌려준다. 못 읽으면 예외. ----------

def _read_hackernews(e: dict, cfg: dict, sources: dict, fetch, reach=None) -> tuple[str, str]:
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


_AR = "(Agent Reach)"
_REACH_MISS = (agentreach.Stopped, agentreach.Failed, agentreach.Unavailable)


def _reach_text(reach, channel: str, *args: str) -> str | None:
    """Agent Reach로 읽은 글자. 못 쓰거나 못 읽으면 None(직접 읽기로 넘어간다)."""
    if reach is None or not reach.allowed(channel):
        return None
    try:
        items = reach.call(channel, *args)
    except _REACH_MISS:
        return None
    return "\n\n".join(i.get("text") or "" for i in items) or None


def _read_github(e, cfg, sources, fetch, reach=None):
    """README와 댓글이 가장 많은 열린 이슈(명세 6번 "README, 이슈")."""
    repo = e["external_id"]
    parts, scope = [], []
    readme = _reach_text(reach, "github", "read", repo, "--backend", "github-api")
    tool = _AR if readme is not None else ""
    if readme is None:
        try:
            readme = fetch.get_text(f"https://raw.githubusercontent.com/{repo}/HEAD/README.md")
        except Exception:
            readme = ""
    body, cut = _clip(readme, cfg["max_chars"])
    if body:
        parts.append(f"[README]\n{body}")
        scope.append(f"README {'앞 ' if cut else ''}{len(body):,}자{tool}")
    issues = _top_issues(repo, cfg, fetch) if cfg.get("github_issues") else []
    texts, comments = [], 0
    for issue in issues:
        text = _reach_text(reach, "github", "read", issue["html_url"], "--backend", "github-api")
        tool = _AR if text is not None else ""
        text = text if text is not None else (issue.get("body") or "")
        texts.append(f"#{issue['number']} {issue['title']}\n{text}")
        comments += issue.get("comments") or 0
    if texts:
        joined, _ = _clip("\n\n".join(texts), cfg["max_chars"])
        parts.append(f"[이슈]\n{joined}")
        scope.append(f"이슈 {len(texts)}(댓글 {comments}){tool}")
    return "\n\n".join(parts), " · ".join(scope)


def _top_issues(repo: str, cfg: dict, fetch) -> list[dict]:
    """댓글이 가장 많은 열린 이슈(풀 리퀘스트 제외). 목록은 GitHub 공개 API에서 직접 받는다."""
    from urllib.parse import urlencode as _q

    from . import config

    token = config.secret("GITHUB_TOKEN")  # Actions 가 주는 읽기용 토큰. 있으면 횟수 제한이 넉넉해진다. 도구에는 넘기지 않는다
    headers = {"Accept": "application/vnd.github+json", **({"Authorization": f"Bearer {token}"} if token else {})}
    try:
        rows = fetch.get_json(f"https://api.github.com/repos/{repo}/issues?" + _q(
            {"state": "open", "sort": "comments", "direction": "desc", "per_page": 10}), headers) or []
    except Exception:
        return []
    rows = [r for r in rows if "pull_request" not in r and (r.get("comments") or 0) > 0]
    return rows[: cfg["github_issues"]]


def _read_huggingface(e, cfg, sources, fetch, reach=None):
    return _read_readme(f"https://huggingface.co/{e['external_id']}/raw/main/README.md", "모델 카드", cfg, fetch)


def _read_wikipedia(e, cfg, sources, fetch, reach=None):
    host = e["origin"]  # 예: ko.wikipedia.org
    query = urlencode({"action": "query", "prop": "extracts", "explaintext": 1, "redirects": 1,
                       "format": "json", "formatversion": 2, "titles": e["external_id"].replace("_", " ")})
    pages = fetch.get_json(f"https://{host}/w/api.php?{query}")["query"]["pages"]
    body, cut = _clip(pages[0].get("extract") or "", cfg["max_chars"])
    return body, f"문서 본문 {'앞 ' if cut else ''}{len(body):,}자"


def _read_youtube(e, cfg, sources, fetch, reach=None):
    """자막(Agent Reach), 설명란, 댓글 위 20개(관련순) — 명세 6번.

    자막은 YouTube Data API로는 영상 주인만 받을 수 있어 Agent Reach로만 읽는다.
    설명란·댓글은 YouTube Data API 키로 읽는다. 키가 없으면 자막만 읽는다.
    """
    from .sources import SourceProblem, youtube

    parts, scope = [], []
    reach_cfg = reach.cfg if reach is not None else {}
    sub = _reach_text(reach, "youtube", "subtitle", f"https://www.youtube.com/watch?v={e['external_id']}",
                      "--lang", reach_cfg.get("subtitle_langs", "ko,en"))
    if sub:
        sub, cut = _clip(" ".join(sub.split()), cfg["max_chars"])
        parts.append(f"[자막]\n{sub}")
        scope.append(f"자막 {'앞 ' if cut else ''}{len(sub):,}자{_AR}")
    yt_cfg = sources[e["source"]]
    try:
        desc, _ = _clip(youtube.description(yt_cfg, fetch, e["external_id"]).strip(), cfg["max_chars"])
        comments = youtube.top_comments({**yt_cfg, "comments_per_video": cfg["comments"]}, fetch, youtube._key(),
                                        e["external_id"]) or []
    except SourceProblem:
        if not parts:
            raise
        desc, comments = "", []
    if desc:
        parts.append(f"[설명란]\n{desc}")
        scope.append(f"설명란 {len(desc):,}자")
    if comments:
        joined, _ = _clip("\n- ".join(" ".join(c.split()) for c in comments), cfg["max_chars"])
        parts.append(f"[댓글]\n- {joined}")
        scope.append(f"댓글 상위 {len(comments)}")
    return "\n\n".join(parts), " · ".join(scope)


def _read_geeknews(e, cfg, sources, fetch, reach=None):
    """글 페이지는 자동 읽기를 거절(403)해서, 피드에 든 요약 본문을 읽는다."""
    from .sources import geeknews

    xml = fetch.get_text(sources[e["source"]]["feed_url"])
    body, cut = _clip(html_to_text(geeknews.summary_of(xml, e["external_id"])), cfg["max_chars"])
    return body, f"GeekNews 요약 {'앞 ' if cut else ''}{len(body):,}자"


READERS = {
    "hackernews": _read_hackernews,
    "github_trending": _read_github,
    "huggingface": _read_huggingface,
    "wikipedia": _read_wikipedia,
    "youtube": _read_youtube,
    "geeknews": _read_geeknews,
}


def run(conn, day: str, settings: dict, fetch, client=None, say=print, reach=None) -> dict:
    """오늘의 실탐(명세 6번). 결과 요약을 돌려준다. LLM을 못 쓰면 이 단계만 건너뛴다.

    1. 읽을 주제: 점수 모드에서는 임계를 넘은 주제, "지금 인기" 모드에서는 어텐션이 높은 주제(위 top_n 개).
    2. 주제마다 대표·발단·최다 논의 중 1~3건을 읽고, 주제 하나에 LLM 1회로 요약한다.
    3. 시간 예산이 남으면 탐색 슬롯의 주제를 읽는다.
    같은 주제는 7일 안에 다시 읽지 않는다. 읽은 원문은 요약에만 쓰고 저장하지 않는다.
    """
    cfg = settings["deepread"]
    result = {"read": 0, "explore_read": 0, "skipped": 0, "failed": 0, "note": ""}
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

    if reach is None:
        try:
            reach = agentreach.Reach(settings["agent_reach"])
        except agentreach.Unavailable as e:
            result["tool"] = f"{e} — 공개 주소에서 직접 읽음"
    since = (date.fromisoformat(day) - timedelta(days=cfg["no_reread_days"])).isoformat()
    recent = {r[0] for r in conn.execute("SELECT item_id FROM deepreads WHERE date > ?", (since,))}
    deadline = time.monotonic() + cfg["budget_minutes"] * 60
    main, explore = _targets(conn, day, settings, recent, result)
    for group, key in ((main, "read"), (explore if cfg["read_explore"] else [], "explore_read")):
        for code, name, picks in group:
            if time.monotonic() > deadline:
                result["note"] = f"시간 예산 {cfg['budget_minutes']}분을 다 써서 멈춤"
                break
            outcome = _read_topic(conn, day, settings, fetch, client, name, picks, reach)
            if isinstance(outcome, Exception):
                result["note"] = f"{llm.explain_error(outcome)} — 남은 실탐은 건너뜀"
                break
            result[key if outcome == "ok" else "failed"] += 1
        if result["note"]:
            break
    if reach is not None:
        result["tool"] = reach.summary()
    db.save_deepread_tool(conn, day, result.get("tool", ""))
    say(f"  실탐 도구: {result.get('tool', '')}")
    say(f"  실탐: 요약 {result['read']}건 · 탐색 슬롯 {result['explore_read']}건 · 건너뜀 {result['skipped']}건"
        f" · 실패 {result['failed']}건" + (f" — {result['note']}" if result["note"] else ""))
    return result


def _read_topic(conn, day, settings, fetch, client, name: str, picks: list[tuple[str, dict]], reach=None):
    """주제 하나: 고른 글들을 읽고 LLM 1회로 요약해 저장한다. "ok" | "failed" | LLM 오류(그날 실탐을 멈춤)."""
    cfg, llm_cfg, sources = settings["deepread"], settings["llm"], settings["sources"]
    parts, scopes = [], []
    for k, (role, e) in enumerate(picks):
        if k:
            time.sleep(cfg["pause_sec"])  # 같은 곳을 연달아 두드리지 않는다
        try:
            material, scope = READERS[sources[e["source"]].get("module", e["source"])](e, cfg, sources, fetch, reach)
        except Exception:
            material, scope = "", ""
        if material.strip():
            label = sources[e["source"]]["label"]
            parts.append(f"[{role} · {label}] {e['title']}\n{material}")
            scopes.append(f"{role} {scope}" if scope else role)
    material = "\n\n".join(parts)
    if len(material) < cfg["min_chars"]:
        return "failed"  # 원문을 못 읽었으면 지어내지 않고 넘어간다
    try:
        summary, usage = llm.summarize(client, llm_cfg, name, material)
    except Exception as err:
        return err
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    lead = picks[0][1]
    with conn:
        db.save_llm_call(conn, day, created_at=now, purpose="deepread",
                         ref=f"{lead['source']}:{lead['external_id']}", model=llm_cfg["model"], **usage)
        if summary:
            db.save_deepread(conn, day, lead["item_id"], scope=" · ".join(scopes), model=llm_cfg["model"], **summary)
    return "ok" if summary else "failed"


def _targets(conn, day: str, settings: dict, recent: set, result: dict):
    """(읽을 순위 주제들, 시간이 남으면 읽을 탐색 주제들). 각각 (번호, 이름, [(역할, 글), ...]).

    순위 주제: 점수 모드에서는 임계 통과 주제만, "지금 인기" 모드에서는 순위 위 top_n 개.
    주제마다 대표·발단·최다 논의 중 읽는 법이 있는 소스의 글 1~3건을 고른다(topics.evidence).
    """
    from . import score, topics

    cfg, sources = settings["deepread"], settings["sources"]
    entries = {e["item_id"]: e for e in rank.now_popular(conn, day, settings)
               + rank.now_popular(conn, day, settings, explore=True)}
    readable = {k for k, v in sources.items() if v.get("module", k) in READERS}
    members: dict[str, list[dict]] = {}
    for item_id, code in conn.execute("SELECT item_id, topic_code FROM topic_items WHERE date = ?", (day,)):
        if item_id in entries:
            members.setdefault(code, []).append(entries[item_id])
    names = dict(conn.execute("SELECT code, name FROM topics"))
    mode = conn.execute("SELECT mode FROM topic_score WHERE date = ? LIMIT 1", (day,)).fetchone()
    if mode and mode[0] == "score":
        rows = conn.execute("SELECT topic_code FROM topic_score WHERE date = ? AND passed = 1 ORDER BY rank", (day,))
    else:
        rows = conn.execute("SELECT topic_code FROM topic_score WHERE date = ? AND rank IS NOT NULL ORDER BY rank "
                            "LIMIT ?", (day, cfg["top_n"]))
    ranked_codes = [r[0] for r in rows]
    explore_codes = score.explore_picks(conn, day, settings, set(ranked_codes))

    def plan(codes, n_items):
        out = []
        for code in codes:
            items = members.get(code, [])
            if any(e["item_id"] in recent for e in items):
                result["skipped"] += 1  # 7일 안에 이미 읽은 주제(명세 6번 재탐색 금지)
                continue
            picks = [(role, e) for role, e in topics.evidence(
                [e for e in items if e["source"] in readable], n_items) if role in topics.ROLES]
            if picks:
                out.append((code, names.get(code, picks[0][1]["title"]), picks))
        return out

    return plan(ranked_codes, cfg["items_per_topic"]), plan(explore_codes, 1)
