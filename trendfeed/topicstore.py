"""주제에 번호를 붙여 저장한다 (명세 8번의 topics · topic_items · topic_daily).

하루에도 여러 번, 날마다 다시 묶기 때문에 "이 묶음이 전의 어느 주제인가"를 정해야 한다.
규칙: 묶음 안의 항목이 가장 최근에 속했던 주제를 이어받는다. 여러 주제에 걸치면 항목이 가장
많이 겹치는 주제를 고르고, 전에 속한 주제가 없으면 새 번호(T-0001 꼴)를 받는다.
혼자뿐인 항목도 주제 하나다. 그래야 내일 다른 글이 붙었을 때 같은 번호로 이어진다.
"""

from __future__ import annotations

import json
from collections import Counter


def _code(n: int) -> str:
    return f"T-{n:04d}"


def save_day(conn, day: str, found: list[dict], settings: dict) -> list[dict]:
    """그날의 주제들을 저장하고, 번호(code)·처음 나타난 날(first_seen)을 붙여 돌려준다.

    같은 날 다시 부르면 그날 치를 새로 쓴다(번호는 이어받는다).
    """
    sources = settings["sources"]
    with conn:
        # 항목마다 가장 최근에 속했던 주제(오늘 앞선 실행 포함)
        prior = dict(conn.execute(
            "SELECT item_id, topic_code FROM topic_items t "
            "WHERE date = (SELECT MAX(date) FROM topic_items WHERE item_id = t.item_id)"
        ).fetchall())
        next_no = conn.execute(
            "SELECT COALESCE(MAX(CAST(SUBSTR(code, 3) AS INTEGER)), 0) FROM topics"
        ).fetchone()[0] + 1
        conn.execute("DELETE FROM topic_items WHERE date = ?", (day,))
        conn.execute("DELETE FROM topic_daily WHERE date = ?", (day,))

        taken: set[str] = set()
        for t in sorted(found, key=lambda t: -t["attention"]):  # 큰 주제가 먼저 번호를 이어받는다
            votes = Counter(prior[e["item_id"]] for e in t["items"] if e["item_id"] in prior)
            code = next((c for c, _ in sorted(votes.items(), key=lambda x: (-x[1], x[0])) if c not in taken), None)
            row = conn.execute("SELECT * FROM topics WHERE code = ?", (code,)).fetchone() if code else None
            if row is None:
                code, next_no = _code(next_no), next_no + 1
                first_seen = min([day] + [e["first_seen"] for e in t["items"]])
                conn.execute(
                    "INSERT INTO topics (code, name, field, aliases, first_seen, named_by_llm) VALUES (?, ?, ?, '[]', ?, ?)",
                    (code, t["name"], sources[t["items"][0]["source"]]["field"], first_seen, int(t["named_by_llm"])),
                )
                name = t["name"]
            else:
                name, first_seen = row["name"], row["first_seen"]
                aliases = json.loads(row["aliases"])
                if t["named_by_llm"] and not row["named_by_llm"]:
                    name = t["name"]  # 임시 이름(제목)이던 것에 LLM 이름이 생겼다
                elif t["named_by_llm"] and t["name"] != name and t["name"] not in aliases:
                    aliases.append(t["name"])  # 이름은 처음 것을 지키고, 다른 이름은 별칭으로 모은다
                conn.execute(
                    "UPDATE topics SET name = ?, aliases = ?, named_by_llm = ? WHERE code = ?",
                    (name, json.dumps(aliases, ensure_ascii=False), int(row["named_by_llm"] or t["named_by_llm"]), code),
                )
            taken.add(code)
            by_platform: dict[str, float] = {}
            for e in t["items"]:
                key = sources[e["source"]]["code"]
                by_platform[key] = round(by_platform.get(key, 0.0) + e["attention"], 4)
            conn.execute(
                "INSERT INTO topic_daily (topic_code, date, attention, platforms, origins, item_count) VALUES (?, ?, ?, ?, ?, ?)",
                (code, day, round(t["attention"], 4), json.dumps(by_platform, sort_keys=True), t["origins"], len(t["items"])),
            )
            conn.executemany(
                "INSERT OR REPLACE INTO topic_items (item_id, date, topic_code) VALUES (?, ?, ?)",
                [(e["item_id"], day, code) for e in t["items"]],
            )
            t.update(code=code, name=name, first_seen=first_seen)
        # 오늘 앞선 실행에서 만들었지만 이제 아무 항목도 없는 주제는 지운다
        conn.execute("DELETE FROM topics WHERE code NOT IN (SELECT DISTINCT topic_code FROM topic_items)")
    return found
