"""저장소 — SQLite 파일 하나. 1단계에 필요한 표 세 개만 만든다(명세 8번).

- source_runs    : 소스별 하루 실행 기록
- items          : 수집한 글·저장소 하나
- item_snapshots : 항목의 하루치 숫자. 오래 남기는 것은 이 숫자다
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from pathlib import Path

from .sources import Record

# 숫자 열 이름. 소스마다 있는 것만 채우고 나머지는 비워 둔다.
METRICS = ("views", "stars", "score", "comments", "likes")

SCHEMA = """
CREATE TABLE IF NOT EXISTS source_runs (
    date            TEXT NOT NULL,      -- 실행한 날 (YYYY-MM-DD)
    source          TEXT NOT NULL,
    item_count      INTEGER NOT NULL,   -- 그날 목록에서 모은 건수
    followed_count  INTEGER NOT NULL DEFAULT 0,  -- 목록 밖에서 숫자만 다시 적은 건수
    status          TEXT NOT NULL,      -- ok(정상) | warn(주의) | empty(입력 없음)
    memo            TEXT NOT NULL DEFAULT '',
    started_at      TEXT NOT NULL,      -- 시작 시각 (UTC)
    duration_sec    REAL NOT NULL,
    PRIMARY KEY (date, source)
);

CREATE TABLE IF NOT EXISTS items (
    id            INTEGER PRIMARY KEY,
    source        TEXT NOT NULL,
    external_id   TEXT NOT NULL,        -- 소스 안에서의 고유 번호·이름
    title         TEXT NOT NULL,
    origin        TEXT,                 -- 출처: 올린 계정·조직·사이트
    url           TEXT NOT NULL,
    published_at  TEXT,                 -- 올라온 시각 (UTC)
    first_seen    TEXT NOT NULL,        -- 처음 수집한 날
    extra         TEXT NOT NULL DEFAULT '{}',   -- 그 밖의 정보 (JSON)
    UNIQUE (source, external_id)
);

CREATE TABLE IF NOT EXISTS item_snapshots (
    item_id   INTEGER NOT NULL REFERENCES items(id),
    date      TEXT NOT NULL,
    captured_at TEXT NOT NULL,          -- 숫자를 읽은 시각 (UTC). 하루 증가량을 잴 때 실제 간격을 쓴다
    listed    INTEGER NOT NULL,         -- 1: 그날 목록에 있었음, 0: 목록 밖에서 숫자만 다시 적음
    rank      INTEGER,                  -- 목록에서의 순서
    views     INTEGER,
    stars     INTEGER,
    score     INTEGER,
    comments  INTEGER,
    likes     INTEGER,
    extra     TEXT NOT NULL DEFAULT '{}',       -- 그 밖의 숫자 (JSON)
    PRIMARY KEY (item_id, date)
);

CREATE TABLE IF NOT EXISTS deepreads (
    item_id         INTEGER NOT NULL REFERENCES items(id),
    date            TEXT NOT NULL,      -- 읽은 날. 7일 재탐색 금지 판단에도 쓴다
    scope           TEXT NOT NULL,      -- 읽은 범위 ("README 앞 12,000자" 등)
    what            TEXT NOT NULL,      -- 무엇
    why             TEXT NOT NULL,      -- 왜 나왔나
    how             TEXT NOT NULL,      -- 어떻게 쓰이나
    comments_point  TEXT NOT NULL,      -- 댓글 논점 한 줄
    model           TEXT NOT NULL,
    PRIMARY KEY (item_id, date)
);

CREATE TABLE IF NOT EXISTS llm_calls (
    date           TEXT NOT NULL,
    created_at     TEXT NOT NULL,       -- 부른 시각 (UTC)
    purpose        TEXT NOT NULL,       -- 용도 (deepread 등)
    ref            TEXT NOT NULL,       -- 무엇에 대해 불렀나 (소스:외부id)
    model          TEXT NOT NULL,
    input_tokens   INTEGER NOT NULL,
    output_tokens  INTEGER NOT NULL,
    PRIMARY KEY (created_at, purpose, ref)
);

CREATE TABLE IF NOT EXISTS topics (
    code          TEXT PRIMARY KEY,     -- 주제 번호 (T-0731 꼴)
    name          TEXT NOT NULL,
    field         TEXT NOT NULL,        -- 분야
    aliases       TEXT NOT NULL DEFAULT '[]',   -- 같은 주제에 붙었던 다른 이름들 (JSON)
    first_seen    TEXT NOT NULL,        -- 처음 나타난 날
    named_by_llm  INTEGER NOT NULL DEFAULT 0,   -- 0이면 이름이 임시(가장 큰 항목의 제목)
    keywords      TEXT NOT NULL DEFAULT '[]'    -- 주제 글 제목에서 코드가 뽑은 낱말 (JSON)
);

CREATE TABLE IF NOT EXISTS daily_runs (
    date         TEXT PRIMARY KEY,
    started_at   TEXT NOT NULL,         -- 그날 매일 실행이 시작한 시각 (UTC)
    finished_at  TEXT                   -- 끝난 시각 (피드를 쓸 때 적는다)
);

CREATE TABLE IF NOT EXISTS topic_items (
    item_id     INTEGER NOT NULL REFERENCES items(id),
    date        TEXT NOT NULL,
    topic_code  TEXT NOT NULL REFERENCES topics(code),
    PRIMARY KEY (item_id, date)         -- 한 항목은 하루에 한 주제에만 속한다
);

CREATE TABLE IF NOT EXISTS topic_daily (
    topic_code  TEXT NOT NULL REFERENCES topics(code),
    date        TEXT NOT NULL,
    attention   REAL NOT NULL,          -- 그날 주제에 묶인 항목들의 어텐션 합
    platforms   TEXT NOT NULL,          -- 플랫폼별 값 (JSON)
    origins     INTEGER NOT NULL,       -- 서로 다른 출처 수
    item_count  INTEGER NOT NULL,
    PRIMARY KEY (topic_code, date)
);

CREATE TABLE IF NOT EXISTS feedback (
    topic_code   TEXT NOT NULL REFERENCES topics(code),
    date         TEXT NOT NULL,         -- 표시한 피드의 날짜
    interesting  INTEGER NOT NULL,      -- 1: 몰랐는데 흥미로움
    issue        INTEGER,               -- 표시에 쓰인 GitHub 이슈 번호
    PRIMARY KEY (topic_code, date)
);

CREATE TABLE IF NOT EXISTS topic_why (
    topic_code  TEXT NOT NULL REFERENCES topics(code),
    date        TEXT NOT NULL,
    sentence    TEXT NOT NULL,          -- "왜 올랐나" 한 문장 (LLM이 코드가 준 숫자로만 씀)
    model       TEXT NOT NULL,
    PRIMARY KEY (topic_code, date)
);

CREATE TABLE IF NOT EXISTS topic_score (
    topic_code  TEXT NOT NULL REFERENCES topics(code),
    date        TEXT NOT NULL,
    mode        TEXT NOT NULL,          -- early("지금 인기", 기준선 쌓이는 중) | score(평소 대비 점수)
    z           REAL,                   -- 평소 대비 정도. early 에서는 비어 있다
    accel       REAL,                   -- 가속(최근 3일 ÷ 14일)
    breadth     INTEGER NOT NULL,       -- 플랫폼 수(폭)
    origins     INTEGER NOT NULL,       -- 출처 수
    score       REAL,
    rank        INTEGER,                -- 순위. 출처 조건을 못 채우면 비어 있다
    passed      INTEGER NOT NULL,       -- 임계 통과 여부
    explore     INTEGER NOT NULL DEFAULT 0,  -- 1: 탐색 슬롯에서 온 주제(순위와 따로 센다)
    PRIMARY KEY (topic_code, date)
);
"""


# 나중에 더한 칸: 예전 저장 파일을 열 때 없으면 더한다 (표, 칸, 정의)
_ADDED_COLUMNS = [
    ("topics", "keywords", "TEXT NOT NULL DEFAULT '[]'"),
    ("topic_score", "explore", "INTEGER NOT NULL DEFAULT 0"),
]


def connect(path: Path | str) -> sqlite3.Connection:
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for table, column, ddl in _ADDED_COLUMNS:
        have = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        if column not in have:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    conn.commit()
    return conn


def _json(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False, sort_keys=True)


def save_records(
    conn: sqlite3.Connection, day: str, source: str, records: list[Record], captured_at: str
) -> None:
    """항목과 그날의 숫자를 저장한다.

    같은 항목을 다시 보면 제목 등은 최신으로 고치되 '처음 수집한 날'은 그대로 둔다.
    같은 날 다시 돌리면 그날 숫자를 덮어쓴다(하루에 한 줄).
    """
    for r in records:
        item_id = conn.execute(
            """
            INSERT INTO items (source, external_id, title, origin, url, published_at, first_seen, extra)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT (source, external_id) DO UPDATE SET
                title = excluded.title, origin = excluded.origin, url = excluded.url,
                published_at = COALESCE(excluded.published_at, items.published_at),
                extra = excluded.extra
            RETURNING id
            """,
            (source, r.external_id, r.title, r.origin, r.url, r.published_at, day, _json(r.item_extra)),
        ).fetchone()[0]
        conn.execute(
            f"""
            INSERT OR REPLACE INTO item_snapshots
                (item_id, date, captured_at, listed, rank, {", ".join(METRICS)}, extra)
            VALUES (?, ?, ?, ?, ?, {", ".join("?" * len(METRICS))}, ?)
            """,
            (item_id, day, captured_at, int(r.listed), r.rank, *(r.metrics.get(m) for m in METRICS), _json(r.snap_extra)),
        )


def recently_listed(conn: sqlite3.Connection, day: str, source: str, days: int) -> list[str]:
    """오늘 이전 `days`일 안에 목록에 있었던 항목의 외부 id."""
    since = (date.fromisoformat(day) - timedelta(days=days)).isoformat()
    rows = conn.execute(
        """
        SELECT DISTINCT i.external_id FROM items i
        JOIN item_snapshots s ON s.item_id = i.id
        WHERE i.source = ? AND s.listed = 1 AND s.date >= ? AND s.date < ?
        ORDER BY i.id
        """,
        (source, since, day),
    ).fetchall()
    return [r[0] for r in rows]


def save_deepread(conn, day: str, item_id: int, *, scope: str, what: str, why: str, how: str,
                  comments_point: str, model: str) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO deepreads (item_id, date, scope, what, why, how, comments_point, model) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (item_id, day, scope, what, why, how, comments_point, model),
    )


def save_llm_call(conn, day: str, *, created_at: str, purpose: str, ref: str, model: str,
                  input_tokens: int, output_tokens: int) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO llm_calls (date, created_at, purpose, ref, model, input_tokens, output_tokens) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (day, created_at, purpose, ref, model, input_tokens, output_tokens),
    )


def save_feedback(conn, code: str, day: str, *, issue: int | None = None, interesting: int = 1) -> None:
    conn.execute("INSERT OR REPLACE INTO feedback (topic_code, date, interesting, issue) VALUES (?, ?, ?, ?)",
                 (code, day, interesting, issue))


def listed_count(conn: sqlite3.Connection, day: str, source: str) -> int:
    """그날 이 소스의 목록에 있었던 항목 수(하루에 여러 번 돌려도 한 항목은 한 번)."""
    return conn.execute(
        "SELECT COUNT(*) FROM item_snapshots s JOIN items i ON i.id = s.item_id "
        "WHERE i.source = ? AND s.date = ? AND s.listed = 1",
        (source, day),
    ).fetchone()[0]


def save_run(
    conn: sqlite3.Connection,
    day: str,
    source: str,
    *,
    item_count: int,
    followed_count: int,
    status: str,
    memo: str,
    started_at: str,
    duration_sec: float,
) -> None:
    conn.execute(
        """
        INSERT OR REPLACE INTO source_runs
            (date, source, item_count, followed_count, status, memo, started_at, duration_sec)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (day, source, item_count, followed_count, status, memo, started_at, round(duration_sec, 1)),
    )


def start_daily(conn, day: str, started_at: str) -> None:
    conn.execute("INSERT OR REPLACE INTO daily_runs (date, started_at, finished_at) VALUES (?, ?, NULL)",
                 (day, started_at))
    conn.commit()


def finish_daily(conn, day: str, finished_at: str) -> None:
    conn.execute("UPDATE daily_runs SET finished_at = ? WHERE date = ?", (finished_at, day))
    conn.commit()
