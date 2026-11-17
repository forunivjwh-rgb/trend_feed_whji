"""예전 방식의 기록(날짜별 글자 파일)을 저장 파일로 옮긴다 — 한 번만 쓰는 옮기기 도구.

지금은 명세대로 SQLite 한 파일(data/trend.db)만 쓴다. 이 모듈은 2026-11-16~17 에 날짜별 파일로
쌓인 기록을 저장 파일로 옮길 때만 쓰인다(scripts/actions_run.sh). 아래는 예전 설명이다.

숫자 기록을 날짜별 글자 파일로 내보내고 다시 읽어 들인다.

GitHub Actions 에는 저장 파일(SQLite)을 계속 둘 곳이 없어서, 하루치를 글자 파일 하나
(days/2026-11-16.jsonl)로 `data` 브랜치에 쌓는다. 실행할 때마다 그 파일들로 저장 파일을
다시 만들고, 수집한 뒤 오늘 치 파일을 새로 쓴다.

한 줄이 기록 하나다(JSON). kind 가 "run" 이면 소스 실행 기록, "item" 이면 항목과 그날의 숫자,
"deepread" 이면 실탐 요약, "llm" 이면 LLM 호출 기록(토큰 수), "topic" 이면 주제와 그날 속한 항목, "why" 이면 주제별 "왜 올랐나" 문장, "feedback" 이면 "몰랐는데 흥미로움" 표시다.
줄 순서를 항상 같게 써서 바뀐 곳만 차이로 남게 한다.
"""

from __future__ import annotations

import json
from pathlib import Path

from .db import METRICS

DAYS_DIR = "days"
_RUN_FIELDS = ("source", "item_count", "followed_count", "status", "memo", "started_at", "duration_sec")
_ITEM_FIELDS = ("source", "external_id", "title", "origin", "url", "published_at", "first_seen")
_SNAP_FIELDS = ("captured_at", "listed", "rank", *METRICS)
_DEEPREAD_FIELDS = ("scope", "what", "why", "how", "comments_point", "model")
_LLM_FIELDS = ("created_at", "purpose", "ref", "model", "input_tokens", "output_tokens")


def export_day(conn, day: str, out_dir: Path) -> Path:
    """그날 치 실행 기록과 숫자를 파일 하나로 쓴다. 이미 있으면 덮어쓴다."""
    lines = []
    for r in conn.execute("SELECT * FROM source_runs WHERE date = ? ORDER BY source", (day,)):
        lines.append({"kind": "run", **{k: r[k] for k in _RUN_FIELDS}})
    for r in conn.execute(
        """
        SELECT i.source, i.external_id, i.title, i.origin, i.url, i.published_at, i.first_seen,
               i.extra AS item_extra, s.*
        FROM item_snapshots s JOIN items i ON i.id = s.item_id
        WHERE s.date = ? ORDER BY i.source, i.external_id
        """,
        (day,),
    ):
        line = {"kind": "item", **{k: r[k] for k in _ITEM_FIELDS}}
        line["item_extra"] = json.loads(r["item_extra"])
        line.update({k: r[k] for k in _SNAP_FIELDS if r[k] is not None})
        line["extra"] = json.loads(r["extra"])
        lines.append(line)
    for r in conn.execute(
        "SELECT i.source, i.external_id, d.* FROM deepreads d JOIN items i ON i.id = d.item_id "
        "WHERE d.date = ? ORDER BY i.source, i.external_id",
        (day,),
    ):
        lines.append({"kind": "deepread", "source": r["source"], "external_id": r["external_id"],
                      **{k: r[k] for k in _DEEPREAD_FIELDS}})
    for r in conn.execute("SELECT * FROM llm_calls WHERE date = ? ORDER BY created_at, ref", (day,)):
        lines.append({"kind": "llm", **{k: r[k] for k in _LLM_FIELDS}})
    for r in conn.execute(
        "SELECT t.*, d.attention, d.platforms, d.origins FROM topic_daily d JOIN topics t ON t.code = d.topic_code "
        "WHERE d.date = ? ORDER BY t.code",
        (day,),
    ):
        members = conn.execute(
            "SELECT i.source, i.external_id FROM topic_items m JOIN items i ON i.id = m.item_id "
            "WHERE m.topic_code = ? AND m.date = ? ORDER BY i.source, i.external_id",
            (r["code"], day),
        ).fetchall()
        lines.append({
            "kind": "topic", "code": r["code"], "name": r["name"], "field": r["field"],
            "aliases": json.loads(r["aliases"]), "first_seen": r["first_seen"], "named_by_llm": r["named_by_llm"],
            "attention": r["attention"], "platforms": json.loads(r["platforms"]), "origins": r["origins"],
            "items": [[m["source"], m["external_id"]] for m in members],
        })
    for r in conn.execute("SELECT * FROM feedback WHERE date = ? ORDER BY topic_code", (day,)):
        lines.append({"kind": "feedback", "code": r["topic_code"], "interesting": r["interesting"], "issue": r["issue"]})
    for r in conn.execute("SELECT * FROM topic_why WHERE date = ? ORDER BY topic_code", (day,)):
        lines.append({"kind": "why", "code": r["topic_code"], "sentence": r["sentence"], "model": r["model"]})
    path = Path(out_dir) / DAYS_DIR / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n" for line in lines)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def import_all(conn, in_dir: Path, settings: dict | None = None) -> int:
    """날짜별 파일을 오래된 날부터 읽어 저장 파일에 넣는다. 읽은 날 수를 돌려준다.

    여러 번 읽어도 결과가 같다(같은 날·같은 항목은 덮어쓴다).
    """
    files = sorted((Path(in_dir) / DAYS_DIR).glob("*.jsonl"))
    with conn:
        for path in files:
            day = path.stem
            for raw in path.read_text(encoding="utf-8").splitlines():
                if not raw.strip():
                    continue
                line = json.loads(raw)
                if line["kind"] == "run":
                    conn.execute(
                        f"INSERT OR REPLACE INTO source_runs (date, {', '.join(_RUN_FIELDS)}) "
                        f"VALUES (?, {', '.join('?' * len(_RUN_FIELDS))})",
                        (day, *(line[k] for k in _RUN_FIELDS)),
                    )
                elif line["kind"] == "item":
                    _import_item(conn, day, line)
                elif line["kind"] == "deepread":
                    row = conn.execute("SELECT id FROM items WHERE source = ? AND external_id = ?",
                                       (line["source"], line["external_id"])).fetchone()
                    if row:
                        conn.execute(
                            f"INSERT OR REPLACE INTO deepreads (item_id, date, {', '.join(_DEEPREAD_FIELDS)}) "
                            f"VALUES (?, ?, {', '.join('?' * len(_DEEPREAD_FIELDS))})",
                            (row[0], day, *(line[k] for k in _DEEPREAD_FIELDS)),
                        )
                elif line["kind"] == "topic":
                    _import_topic(conn, day, line)
                elif line["kind"] == "feedback":
                    conn.execute("INSERT OR REPLACE INTO feedback (topic_code, date, interesting, issue) VALUES (?, ?, ?, ?)",
                                 (line["code"], day, line["interesting"], line["issue"]))
                elif line["kind"] == "why":
                    conn.execute("INSERT OR REPLACE INTO topic_why (topic_code, date, sentence, model) VALUES (?, ?, ?, ?)",
                                 (line["code"], day, line["sentence"], line["model"]))
                elif line["kind"] == "llm":
                    conn.execute(
                        f"INSERT OR REPLACE INTO llm_calls (date, {', '.join(_LLM_FIELDS)}) "
                        f"VALUES (?, {', '.join('?' * len(_LLM_FIELDS))})",
                        (day, *(line[k] for k in _LLM_FIELDS)),
                    )
    # 주제 점수는 저장하지 않고 되살린 기록에서 다시 계산한다(같은 식이면 같은 값이 나온다).
    from . import config, score

    days_with_topics = [r[0] for r in conn.execute("SELECT DISTINCT date FROM topic_daily ORDER BY date")]
    if days_with_topics:
        settings = config.load() if settings is None else settings
        for day in days_with_topics:
            score.compute(conn, day, settings)
    return len(files)


def _import_item(conn, day: str, line: dict) -> None:
    item_id = conn.execute(
        """
        INSERT INTO items (source, external_id, title, origin, url, published_at, first_seen, extra)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT (source, external_id) DO UPDATE SET
            title = excluded.title, origin = excluded.origin, url = excluded.url,
            published_at = COALESCE(excluded.published_at, items.published_at),
            first_seen = MIN(items.first_seen, excluded.first_seen),
            extra = excluded.extra
        RETURNING id
        """,
        (*(line[k] for k in _ITEM_FIELDS), json.dumps(line["item_extra"], ensure_ascii=False, sort_keys=True)),
    ).fetchone()[0]
    conn.execute(
        f"INSERT OR REPLACE INTO item_snapshots (item_id, date, {', '.join(_SNAP_FIELDS)}, extra) "
        f"VALUES (?, ?, {', '.join('?' * len(_SNAP_FIELDS))}, ?)",
        (item_id, day, *(line.get(k) for k in _SNAP_FIELDS), json.dumps(line["extra"], ensure_ascii=False, sort_keys=True)),
    )


def _import_topic(conn, day: str, line: dict) -> None:
    conn.execute(
        """
        INSERT INTO topics (code, name, field, aliases, first_seen, named_by_llm) VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT (code) DO UPDATE SET
            name = excluded.name, field = excluded.field, aliases = excluded.aliases,
            first_seen = MIN(topics.first_seen, excluded.first_seen), named_by_llm = excluded.named_by_llm
        """,
        (line["code"], line["name"], line["field"], json.dumps(line["aliases"], ensure_ascii=False),
         line["first_seen"], line["named_by_llm"]),
    )
    conn.execute(
        "INSERT OR REPLACE INTO topic_daily (topic_code, date, attention, platforms, origins, item_count) VALUES (?, ?, ?, ?, ?, ?)",
        (line["code"], day, line["attention"], json.dumps(line["platforms"], sort_keys=True), line["origins"], len(line["items"])),
    )
    for source, external_id in line["items"]:
        row = conn.execute("SELECT id FROM items WHERE source = ? AND external_id = ?", (source, external_id)).fetchone()
        if row:
            conn.execute("INSERT OR REPLACE INTO topic_items (item_id, date, topic_code) VALUES (?, ?, ?)", (row[0], day, line["code"]))
