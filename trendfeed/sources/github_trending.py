"""GitHub trending — 공식 API가 없어 공개 목록 페이지를 읽는다(로그인 없음).

일간·주간 목록을 합친다. 숫자는 전체 별 수, 포크 수, 그 기간에 늘어난 별 수다.
GitHub가 화면 구조를 바꾸면 여기가 깨질 수 있다. 그때는 0건이 되고
실행 기록에 "입력 없음"과 이유가 남는다.
"""

from __future__ import annotations

import re
import time
from html.parser import HTMLParser

from . import CollectResult, Record

_REPO_HREF = re.compile(r"^/([^/\s]+)/([^/\s]+)$")
_PERIOD_STARS = re.compile(r"([\d,]+)\s+stars?\s+(?:today|this\s+week|this\s+month)")


def _count(text: str) -> int | None:
    """'12,345' → 12345. 숫자를 못 찾으면 None."""
    m = re.search(r"\d[\d,]*", text)
    return int(m.group().replace(",", "")) if m else None


class _TrendingParser(HTMLParser):
    """목록의 저장소 한 칸(<article>)마다 이름·설명·언어·별·포크를 뽑는다.

    꾸밈용 클래스 이름 대신 링크 주소(/소유자/저장소/stargazers 등)를 단서로 써서
    화면이 조금 바뀌어도 덜 깨지게 했다.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.repos: list[dict] = []
        self._cur: dict | None = None
        self._in_h2 = self._in_p = self._in_lang = False
        self._link: str | None = None  # 지금 읽는 링크의 종류: "stars" | "forks"

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "article":
            self._cur = {"repo": None, "text": [], "desc": [], "lang": [], "stars": [], "forks": []}
            self._in_h2 = self._in_p = self._in_lang = False
            self._link = None
            return
        cur = self._cur
        if cur is None:
            return
        if tag == "h2":
            self._in_h2 = True
        elif tag == "p":
            self._in_p = True
        elif tag == "span" and a.get("itemprop") == "programmingLanguage":
            self._in_lang = True
        elif tag == "a":
            href = (a.get("href") or "").split("?")[0]
            if self._in_h2 and cur["repo"] is None:
                m = _REPO_HREF.match(href)
                if m:
                    cur["repo"] = f"{m.group(1)}/{m.group(2)}"
            elif cur["repo"]:
                base = f"/{cur['repo']}"
                if href == f"{base}/stargazers":
                    self._link = "stars"
                elif href in (f"{base}/forks", f"{base}/network/members"):
                    self._link = "forks"

    def handle_endtag(self, tag):
        if self._cur is None:
            return
        if tag == "article":
            self._finish()
        elif tag == "h2":
            self._in_h2 = False
        elif tag == "p":
            self._in_p = False
        elif tag == "span":
            self._in_lang = False
        elif tag == "a":
            self._link = None

    def handle_data(self, data):
        cur = self._cur
        if cur is None:
            return
        cur["text"].append(data)
        if self._in_p:
            cur["desc"].append(data)
        if self._in_lang:
            cur["lang"].append(data)
        if self._link:
            cur[self._link].append(data)

    def _finish(self):
        cur, self._cur = self._cur, None
        if not cur["repo"]:
            return
        text = " ".join(" ".join(cur["text"]).split())
        m = _PERIOD_STARS.search(text)
        self.repos.append(
            {
                "repo": cur["repo"],
                "description": " ".join("".join(cur["desc"]).split()) or None,
                "language": "".join(cur["lang"]).strip() or None,
                "stars": _count("".join(cur["stars"])),
                "forks": _count("".join(cur["forks"])),
                "period_stars": _count(m.group(1)) if m else None,
            }
        )


def parse(html: str) -> list[dict]:
    """목록 페이지 하나에서 저장소들을 화면 순서대로 뽑는다."""
    parser = _TrendingParser()
    parser.feed(html)
    parser.close()
    return parser.repos


def merge(by_period: dict[str, list[dict]]) -> list[Record]:
    """기간별 목록을 저장소 기준으로 합친다. 양쪽에 다 있으면 한 항목에 두 숫자를 담는다."""
    merged: dict[str, Record] = {}
    for period, repos in by_period.items():
        for i, r in enumerate(repos, start=1):
            rec = merged.get(r["repo"])
            if rec is None:
                owner = r["repo"].split("/")[0]
                rec = merged[r["repo"]] = Record(
                    external_id=r["repo"],
                    title=r["repo"],
                    url=f"https://github.com/{r['repo']}",
                    origin=f"github.com/{owner.lower()}",
                    published_at=None,  # 목록 페이지에는 만든 날짜가 없다
                    rank=len(merged) + 1,
                    item_extra={"description": r["description"], "language": r["language"]},
                )
            if r["stars"] is not None:
                rec.metrics["stars"] = r["stars"]
            if r["forks"] is not None:
                rec.snap_extra["forks"] = r["forks"]
            rec.snap_extra[f"rank_{period}"] = i
            if r["period_stars"] is not None:
                rec.snap_extra[f"stars_{period}"] = r["period_stars"]
    return list(merged.values())


def collect(cfg: dict, fetch) -> CollectResult:
    by_period: dict[str, list[dict]] = {}
    problems: list[str] = []
    for n, period in enumerate(cfg["periods"]):
        if n:
            time.sleep(cfg["pause_sec"])
        try:
            html = fetch.get_text(f"{cfg['base_url']}?since={period}")
        except Exception as e:
            problems.append(f"{period} 목록을 받지 못함 ({_reason(e)})")
            continue
        repos = parse(html)
        if not repos:
            problems.append(f"{period} 목록 페이지에서 저장소를 찾지 못함 (화면 구조가 바뀌었을 수 있음)")
            continue
        by_period[period] = repos
    return CollectResult(merge(by_period), problems)


def _reason(e: Exception) -> str:
    code = getattr(e, "code", None)
    return f"HTTP {code}" if code else type(e).__name__
