"""GeekNews — 공개 RSS(Atom) 피드. 키가 필요 없다.

표결 수 같은 숫자가 없어서, 새로 올라온 글을 1건으로 세는 등장 빈도로 계산한다(명세 3번).
피드에 들어 있는 요약 본문은 저장하지 않는다. 제목·링크·올린 사람·올라온 시각만 남긴다.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from xml.etree import ElementTree

from . import CollectResult, Record

# 하루 증가량을 잴 때 보는 숫자 (rank.py): 숫자가 없어 등장 횟수로 센다.
VELOCITY = {"metric": None, "unit": "건", "count_new": True}

_ATOM = {"a": "http://www.w3.org/2005/Atom"}
_TOPIC_ID = re.compile(r"[?&]id=(\d+)")


def parse(xml: str) -> list[Record]:
    root = ElementTree.fromstring(xml)
    records = []
    for entry in root.findall("a:entry", _ATOM):
        title = (entry.findtext("a:title", "", _ATOM) or "").strip()
        url = (entry.findtext("a:id", "", _ATOM) or "").strip()  # 추적용 꼬리표가 없는 깨끗한 주소
        if not title or not url:
            continue
        m = _TOPIC_ID.search(url)
        author = (entry.findtext("a:author/a:name", "", _ATOM) or "").strip()
        published = entry.findtext("a:published", None, _ATOM) or entry.findtext("a:updated", None, _ATOM)
        if published:
            published = datetime.fromisoformat(published.strip()).astimezone(timezone.utc).isoformat()
        records.append(
            Record(
                external_id=m.group(1) if m else url,
                title=title,
                url=url,
                origin=f"news.hada.io/@{author}" if author else "news.hada.io",
                published_at=published,
                rank=len(records) + 1,
            )
        )
    return records


def collect(cfg: dict, fetch) -> CollectResult:
    return CollectResult(parse(fetch.get_text(cfg["feed_url"])))


def summary_of(xml: str, topic_id: str) -> str:
    """피드에 든 글 하나의 요약 본문(HTML)을 돌려준다. 없으면 빈 문자열. 실탐에서만 쓰고 저장하지 않는다."""
    root = ElementTree.fromstring(xml)
    for entry in root.findall("a:entry", _ATOM):
        url = (entry.findtext("a:id", "", _ATOM) or "").strip()
        m = _TOPIC_ID.search(url)
        if (m.group(1) if m else url) == topic_id:
            return entry.findtext("a:content", "", _ATOM) or ""
    return ""
