"""하루의 주제 단계를 순서대로 돌린다: 묶기 → LLM 검토 → 번호 저장 → 점수와 순위.

도구(fastembed)가 없으면 주제 단계를 건너뛰고 이유를 알린다. LLM 키가 없으면 검토만 건너뛴다.
"""

from __future__ import annotations

from datetime import datetime

from . import db, rank, score, topics, topicstore


def run(conn, day: str, settings: dict, *, review: bool = True, client=None, say=print) -> dict:
    """결과 요약을 돌려준다: {"ok", "note", "found"(주제들), "score"(점수 요약)}."""
    entries = rank.now_popular(conn, day, settings)
    if not entries:
        return {"ok": False, "note": "오늘 순위에 든 항목이 없어 주제 단계를 건너뜀", "review_notes": [], "usage": None, "found": [], "score": None}
    notes: list[str] = []
    usage = None
    try:
        texts = [topics.text_of(e, settings["sources"][e["source"]].get("phrase_ignore_chars", "")) for e in entries]
        vectors = topics.embed(texts, settings["topics"])
        found = topics.cluster(entries, vectors, settings)
    except topics.Unavailable as e:
        # 묶기 도구가 없으면 글 하나를 주제 하나로 두고 계속한다(번호·점수·피드는 그대로 돈다)
        vectors = None
        found = topics.singletons(entries, settings)
        notes.append(f"{e} — 글 하나를 주제 하나로 둠")
    if review and vectors is not None:
        found, notes, usage = topics.review(found, settings, client=client, vectors=vectors)
        if usage:
            with conn:
                db.save_llm_call(conn, day, created_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                                 purpose="topics", ref=day, model=settings["llm"]["model"], **usage)
    found = topicstore.save_day(conn, day, found, settings)
    summary = score.compute(conn, day, settings)
    return {"ok": True, "note": "", "review_notes": notes, "usage": usage, "found": found, "score": summary}
