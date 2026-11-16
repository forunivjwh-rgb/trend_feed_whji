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

from . import llm


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
    for n, e in enumerate(entries):
        e["_vec"] = n  # 이 항목의 벡터가 몇 번째인지(합치기 확인에 쓴다)
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

    topics = [_make_topic([entries[j] for j in g], sources) for g in groups]
    topics.sort(key=lambda t: -t["attention"])
    return topics


def singletons(entries: list[dict], settings: dict) -> list[dict]:
    """묶기 도구를 쓸 수 없을 때: 글 하나를 주제 하나로 둔다(물러서는 길)."""
    found = [_make_topic([e], settings["sources"]) for e in entries]
    found.sort(key=lambda t: -t["attention"])
    return found


def _make_topic(items: list[dict], sources: dict, name: str | None = None) -> dict:
    items = sorted(items, key=lambda e: -e["attention"])
    return {
        "name": name or items[0]["title"],  # 이름을 못 받았으면 가장 큰 항목의 제목
        "named_by_llm": name is not None,
        "items": items,
        "attention": sum(e["attention"] for e in items),
        "platforms": sorted({sources[e["source"]]["code"] for e in items}),
        "origins": len({e["origin"] for e in items}),
    }


def pick_for_review(found: list[dict], cfg: dict) -> list[dict]:
    """LLM에게 보일 주제: 2건 이상 묶인 것 전부와, 혼자인 것 중 어텐션이 큰 순으로 몇 개."""
    multi = [t for t in found if len(t["items"]) > 1]
    single = [t for t in found if len(t["items"]) == 1][: cfg["review_singles"]]
    return multi + single


def listing(picked: list[dict], sources: dict) -> tuple[str, dict[int, tuple[int, int]]]:
    """LLM에게 보일 목록 글자와, 항목 번호 → (주제 번호, 주제 안 순서) 표를 만든다.

    주제는 T1, T2…, 항목은 I1, I2… 로 적어 두 번호가 섞이지 않게 한다.
    """
    lines, where, n = [], {}, 0
    for t_no, t in enumerate(picked, start=1):
        lines.append(f"주제 T{t_no}")
        for k, e in enumerate(t["items"]):
            n += 1
            where[n] = (t_no, k)
            lines.append(f"  항목 I{n}: [{sources[e['source']]['label']}] {e['title']}")
    return "\n".join(lines), where


def _number(value, prefix: str) -> int | None:
    """'T12' → 12. 모양이 다르면 None (그 판단은 버린다)."""
    m = re.fullmatch(rf"\s*{prefix}(\d+)\s*", str(value))
    return int(m.group(1)) if m else None


def _closeness(a: list[dict], b: list[dict], vectors) -> float:
    """두 주제에서 가장 비슷한 항목 쌍의 뜻 비슷함."""
    return max(float(vectors[x["_vec"]] @ vectors[y["_vec"]]) for x in a for y in b)


def apply_review(found: list[dict], picked: list[dict], where: dict, review: dict, settings: dict,
                 vectors=None) -> tuple[list[dict], list[str]]:
    """LLM의 판단(이름·합치기·떼어 내기)을 주제에 적용한다. (주제들, 무엇을 했는지 적은 줄들).

    LLM의 말을 그대로 믿지 않는다. 목록에 없는 번호는 버리고, 합치기는 두 주제의 뜻이
    merge_min_similarity 이상 비슷할 때만 받아들인다(vectors 가 있을 때).
    """
    cfg, sources = settings["topics"], settings["sources"]
    names: dict[int, str] = {}
    members: dict[int, list[dict]] = {i: list(t["items"]) for i, t in enumerate(picked, start=1)}
    loose: list[dict] = []
    log: list[str] = []
    for row in review.get("topics", []):
        t_no = _number(row.get("id"), "T")
        if t_no not in members:
            continue
        if str(row.get("name", "")).strip():
            names[t_no] = str(row["name"]).strip()
        for raw in row.get("remove_items", []):
            item_no = _number(raw, "I")
            # 그 주제에 실제로 들어 있는 항목만, 그리고 주제가 비지 않을 때만 떼어 낸다
            if where.get(item_no, (None,))[0] == t_no and len(members[t_no]) > 1:
                item = picked[t_no - 1]["items"][where[item_no][1]]
                # LLM이 스스로 붙인 주제 이름에 그 항목의 이름이 들어 있으면 앞뒤가 안 맞는 판단이다
                # (예: '에이티즈 신곡 MV' 주제에서 '에이티즈' 문서를 떼어 내라). 떼어 내지 않는다.
                own = _name_of(item["title"])
                if len(own) >= cfg["name_min_chars"] and own in names.get(t_no, "").lower():
                    log.append(f"떼어 내기 거절(주제 이름에 그 이름이 있음): '{item['title'][:30]}' ← '{names[t_no][:30]}'")
                    continue
                if item in members[t_no]:
                    members[t_no].remove(item)
                    loose.append(item)
                    log.append(f"떼어 냄: '{item['title'][:30]}' ← '{names.get(t_no, picked[t_no - 1]['name'])[:30]}'")

    def label(i):
        return names.get(i) or members[i][0]["title"]

    for group in review.get("merges", []):
        ids = [i for i in dict.fromkeys(_number(x, "T") for x in group.get("ids", [])) if i in members]
        if len(ids) < 2:
            continue
        keep = max(ids, key=lambda i: sum(e["attention"] for e in members[i]))  # 가장 큰 주제의 이름을 쓴다
        for i in ids:
            if i == keep:
                continue
            if vectors is not None:
                close = _closeness(members[keep], members[i], vectors)
                if close < cfg["merge_min_similarity"]:
                    log.append(f"합치기 거절(뜻 비슷함 {close:.2f}): '{label(keep)[:30]}' + '{label(i)[:30]}'")
                    continue
            log.append(f"합침: '{label(keep)[:30]}' + '{label(i)[:30]}'")
            members[keep] += members.pop(i)

    picked_ids = {id(t) for t in picked}
    result = [t for t in found if id(t) not in picked_ids]
    result += [_make_topic(items, sources, names.get(t_no)) for t_no, items in members.items()]
    result += [_make_topic([item], sources) for item in loose]
    result.sort(key=lambda t: -t["attention"])
    return result, log


def review(found: list[dict], settings: dict, client=None, vectors=None) -> tuple[list[dict], list[str], dict | None]:
    """LLM 검토를 한 번 하고 적용한다. (주제들, 알릴 줄들, 사용량)을 돌려준다.

    LLM을 쓸 수 없거나 답을 못 받으면 주제는 그대로 두고 이유만 알린다.
    """
    if client is None:
        try:
            client = llm.make_client()
        except llm.Unavailable as e:
            return found, [f"{e} — 이름 붙이기·합치기는 건너뜀"], None
    picked = pick_for_review(found, settings["topics"])
    text, where = listing(picked, settings["sources"])
    try:
        answer, usage = llm.review_topics(client, settings["llm"], text)
    except Exception as err:
        return found, [f"{llm.explain_error(err)} — 이름 붙이기·합치기는 건너뜀"], None
    if not answer:
        return found, ["LLM이 답을 주지 않아 이름 붙이기·합치기는 건너뜀"], usage
    result, log = apply_review(found, picked, where, answer, settings, vectors)
    return result, log, usage
