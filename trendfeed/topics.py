"""주제 묶기 — 비슷한 항목을 한 주제로 모은다 (명세 5번). 숫자와 묶기는 전부 코드가 한다.

두 가지 방법을 쓴다.
- 뜻으로 묶기: 제목(과 설명)을 작은 다국어 모델로 숫자 벡터로 바꿔, 충분히 비슷한 것끼리 묶는다.
  한국어 글과 영어 글도 같은 소식이면 묶인다.
- 이름으로 붙이기: 제목이 짧은 이름뿐인 소스(Wikipedia)는 뜻으로 묶으면 관계없는 문서끼리 뭉친다.
  그래서 그 이름이 다른 글의 제목에 그대로 나올 때만 그 주제에 붙이고, 아니면 혼자 한 주제가 된다.

아직은 "주제 후보"를 계산해 보여 주기만 한다. 저장, 주제 번호, 이름 붙이기(LLM), 주제 단위 순위는 다음 일이다.
"""

from __future__ import annotations

import re


class Unavailable(Exception):
    """주제 묶기에 필요한 도구가 없다(사람이 읽을 말)."""


def embed(texts: list[str], cfg: dict):
    """글들을 숫자 벡터로 바꾼다(길이 1로 맞춤). 모델은 처음 한 번 내려받는다."""
    try:
        import numpy as np
        from fastembed import TextEmbedding
    except ImportError:
        raise Unavailable("주제 묶기 도구(fastembed)가 설치돼 있지 않음") from None
    vectors = np.array(list(TextEmbedding(cfg["model"]).embed(texts)))
    return vectors / np.linalg.norm(vectors, axis=1, keepdims=True)


def text_of(e: dict, ignore_chars: str = "") -> str:
    """뜻을 볼 글자: 제목과, 있으면 설명·채널 이름·댓글에서 반복되는 말.

    유튜브 제목은 "정말 달콤해"처럼 그것만으로는 뜻을 알 수 없는 것이 많아서, 이미 모아 둔
    채널 이름과 댓글의 반복되는 말을 보탠다. '소유자/저장소-이름' 꼴은 단어로 풀어 쓴다.
    """
    title = e["title"]
    if "/" in title and " " not in title:
        title = re.sub(r"[/_\-.]+", " ", title)
    parts = [title]
    if e["item_extra"].get("description"):
        parts.append(e["item_extra"]["description"])
    if e["item_extra"].get("channel_title"):
        parts.append(f"채널: {e['item_extra']['channel_title']}")
    noise = set(ignore_chars)
    said = [p["text"] for p in e.get("extra", {}).get("comment_phrases", [])
            if not (noise and set(p["text"].replace(" ", "")) <= noise)]
    if said:
        parts.append("댓글: " + ", ".join(said))
    return ". ".join(parts)


def _name_of(title: str) -> str:
    """'김유정 (배우)' → '김유정'."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", title).strip().lower()


def _mentions(name: str, title: str) -> bool:
    """제목에 그 이름이 한 낱말로 나오는가. 'Nvidia는'처럼 한글 토씨가 붙은 것은 인정한다."""
    for m in re.finditer(re.escape(name), title.lower()):
        before = title[m.start() - 1] if m.start() else " "
        after = title[m.end()] if m.end() < len(title) else " "
        if before.isalnum():
            continue
        if name[-1].isascii() and after.isascii() and after.isalnum():
            continue  # 'go' 가 'google' 에 걸리는 것 방지
        return True
    return False


def cluster(entries: list[dict], vectors, settings: dict) -> list[dict]:
    """항목들을 주제로 묶는다. entries 는 어텐션이 큰 순서(rank.now_popular 의 결과)."""
    cfg, sources = settings["topics"], settings["sources"]
    by_name = [i for i, e in enumerate(entries) if sources[e["source"]].get("topic_match") == "name"]
    by_meaning = [i for i in range(len(entries)) if i not in set(by_name)]
    meaning_set = set(by_meaning)

    # 1) 뜻으로 묶기: 묶음 안 모든 항목과의 평균 비슷함이 기준 이상인, 가장 비슷한 묶음에 넣는다.
    groups: list[list[int]] = []
    for i in by_meaning:
        best, best_sim = None, cfg["threshold"]
        for g in groups:
            sim = float((vectors[g] @ vectors[i]).mean())
            if sim >= best_sim:
                best, best_sim = g, sim
        if best is None:
            groups.append([i])
        else:
            best.append(i)

    # 2) 이름으로 붙이기: 이름이 제목에 나오는 묶음 중 어텐션 합이 가장 큰 곳에 붙인다.
    def weight(g):
        return sum(entries[j]["attention"] for j in g)

    for i in by_name:
        name = _name_of(entries[i]["title"])
        # 제목에 괄호가 붙은 문서('Scene (2026 film)')는 위키가 "헷갈리는 이름"이라고 표시한 것이다.
        # 그런 이름은 글자가 나오는 것만으로는 붙이지 않고, 뜻도 어느 정도 비슷해야 붙인다.
        ambiguous = entries[i]["title"].rstrip().endswith(")")

        def matches(j, i=i, name=name, ambiguous=ambiguous):
            if j not in meaning_set or not _mentions(name, entries[j]["title"]):
                return False
            return not ambiguous or float(vectors[i] @ vectors[j]) >= cfg["name_min_similarity"]

        hits = []
        if len(name) >= cfg["name_min_chars"]:
            hits = [g for g in groups if any(matches(j) for j in g)]
        if hits:
            max(hits, key=weight).append(i)
        else:
            groups.append([i])

    topics = []
    for g in groups:
        items = sorted((entries[j] for j in g), key=lambda e: -e["attention"])
        topics.append(
            {
                "items": items,
                "attention": sum(e["attention"] for e in items),
                "platforms": sorted({sources[e["source"]]["code"] for e in items}),
                "origins": len({e["origin"] for e in items}),
            }
        )
    topics.sort(key=lambda t: -t["attention"])
    return topics
