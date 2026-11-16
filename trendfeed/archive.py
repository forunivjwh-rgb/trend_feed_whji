"""숫자 기록을 날짜별 글자 파일로 내보내고 다시 읽어 들인다.

GitHub Actions 에는 저장 파일(SQLite)을 계속 둘 곳이 없어서, 하루치를 글자 파일 하나
(days/2026-11-16.jsonl)로 `data` 브랜치에 쌓는다. 실행할 때마다 그 파일들로 저장 파일을
다시 만들고, 수집한 뒤 오늘 치 파일을 새로 쓴다.

한 줄이 기록 하나다(JSON). kind 가 "run" 이면 소스 실행 기록, "item" 이면 항목과 그날의 숫자다.
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
    path = Path(out_dir) / DAYS_DIR / f"{day}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join(json.dumps(line, ensure_ascii=False, sort_keys=True) + "\n" for line in lines)
    path.write_text(text, encoding="utf-8", newline="\n")
    return path


def import_all(conn, in_dir: Path) -> int:
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
