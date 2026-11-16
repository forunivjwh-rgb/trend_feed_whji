"""댓글 여러 개에서 반복되는 말을 센다 — 코드로만 한다(LLM 없음, 명세 4번).

같은 말을 한 사람이 여러 번 써도 한 번으로 치고, "서로 다른 댓글 몇 개에 나왔는가"를 센다.
원문은 받지도 돌려주지도 않고, 반복된 짧은 말과 횟수만 돌려준다.
"""

from __future__ import annotations

import re
from collections import Counter

_WORD = re.compile(r"[0-9A-Za-z가-힣ㄱ-ㆎ]+")


def _runs(comment: str, noise: set[str]) -> list[list[str]]:
    """댓글을 단어로 나누되, 웃음·울음소리(ㅋㅋㅋ, ㅎㅎ, ㅠㅠ 등)에서 끊는다.

    그런 단어는 "반복되는 말"에 들어가지 않고, 그 앞뒤 단어가 한 말로 이어 붙지도 않는다.
    """
    runs: list[list[str]] = [[]]
    for word in (w.lower() for w in _WORD.findall(comment)):
        if noise and set(word) <= noise:
            runs.append([])
        else:
            runs[-1].append(word)
    return runs


def repeated(
    comments: list[str], *, max_words: int, min_comments: int, top: int, min_chars: int, ignore_chars: str = ""
) -> list[dict]:
    """[{"text": 반복된 말, "count": 그 말이 나온 댓글 수}, ...] 를 많이 나온 순으로.

    ignore_chars 의 글자만으로 된 단어(예: "ㅋㅎㅠ" → ㅋㅋㅋ, ㅎㅎ, ㅠㅠ, ㅋㅎㅋㅎ)는 세지 않는다.
    """
    noise = set(ignore_chars)
    counts: Counter[tuple[str, ...]] = Counter()
    for comment in comments:
        seen = set()
        for words in _runs(comment, noise):
            for n in range(1, max_words + 1):
                for i in range(len(words) - n + 1):
                    gram = tuple(words[i : i + n])
                    if sum(len(w) for w in gram) >= min_chars:
                        seen.add(gram)
        counts.update(seen)

    kept = {g: c for g, c in counts.items() if c >= min_comments}
    # 긴 말에 그대로 들어 있는 짧은 말은, 횟수가 같으면 긴 말만 남긴다("가져가" ⊂ "l을 가져가").
    result = []
    for gram, count in kept.items():
        covered = any(
            len(other) > len(gram) and c == count and _contains(other, gram) for other, c in kept.items()
        )
        if not covered:
            result.append((gram, count))
    result.sort(key=lambda x: (-x[1], -len(x[0]), x[0]))
    return [{"text": " ".join(g), "count": c} for g, c in result[:top]]


def _contains(longer: tuple[str, ...], shorter: tuple[str, ...]) -> bool:
    n = len(shorter)
    return any(longer[i : i + n] == shorter for i in range(len(longer) - n + 1))
