"""주제 번호: 같은 날 다시 돌려도, 다음 날 다시 묶어도 같은 주제는 같은 번호를 이어받아야 한다."""

import tempfile
import unittest
from pathlib import Path

from trendfeed import archive, config, db, rank, topics, topicstore
from trendfeed.sources import Record

SETTINGS = config.load()
SOURCES = SETTINGS["sources"]
FRESH = "T10:00:00+00:00"


def story(ext_id, score, day):
    return Record(external_id=ext_id, title=f"글 {ext_id}", url=f"https://example.com/{ext_id}",
                  origin=f"site{ext_id}.example", published_at=day + FRESH, rank=1, metrics={"score": score})


class TopicStoreTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)

    def collect(self, day, scores: dict):
        db.save_records(self.conn, day, "hackernews", [story(k, v, day) for k, v in scores.items()], day + "T19:00:00+00:00")
        return {e["external_id"]: e for e in rank.now_popular(self.conn, day, SETTINGS)}

    def save(self, day, entries, groups, names=None):
        """groups: 항목 id 묶음들. names: 묶음 번호 → LLM이 붙인 이름."""
        found = [topics._make_topic([entries[i] for i in g], SOURCES, (names or {}).get(n)) for n, g in enumerate(groups)]
        saved = topicstore.save_day(self.conn, day, found, SETTINGS)
        return {frozenset(e["external_id"] for e in t["items"]): t for t in saved}

    def codes(self, saved):
        return {"+".join(sorted(k)): t["code"] for k, t in saved.items()}

    def test_first_day_numbers_topics_biggest_first(self):
        e = self.collect("2026-11-16", {"a": 400, "b": 100, "c": 50, "d": 10})
        saved = self.save("2026-11-16", e, [["c"], ["a", "b"], ["d"]])
        self.assertEqual(self.codes(saved), {"a+b": "T-0001", "c": "T-0002", "d": "T-0003"})
        row = dict(self.conn.execute("SELECT * FROM topic_daily WHERE topic_code = 'T-0001'").fetchone())
        self.assertEqual((row["item_count"], row["origins"]), (2, 2))
        self.assertAlmostEqual(row["attention"], sum(x["attention"] for x in (e["a"], e["b"])), places=3)
        self.assertEqual(self.conn.execute("SELECT field, first_seen FROM topics WHERE code = 'T-0001'").fetchone()[:],
                         ("개발·OSS", "2026-11-16"))

    def test_running_again_the_same_day_keeps_the_numbers(self):
        e = self.collect("2026-11-16", {"a": 400, "b": 100, "c": 50})
        first = self.codes(self.save("2026-11-16", e, [["a", "b"], ["c"]]))
        again = self.codes(self.save("2026-11-16", e, [["c"], ["a", "b"]]))
        self.assertEqual(first, again)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM topic_items").fetchone()[0], 3)

    def test_next_day_inherits_by_shared_items_and_new_things_get_new_numbers(self):
        e1 = self.collect("2026-11-16", {"a": 400, "b": 100, "c": 50, "d": 10})
        self.save("2026-11-16", e1, [["a", "b"], ["c"], ["d"]])
        e2 = self.collect("2026-11-17", {"a": 500, "b": 150, "c": 60, "d": 20, "x": 90, "y": 30})
        saved = self.codes(self.save("2026-11-17", e2, [["a", "b", "x"], ["c", "d"], ["y"]]))
        self.assertEqual(saved["a+b+x"], "T-0001")   # 새 글 x 가 붙어도 같은 주제
        self.assertEqual(saved["c+d"], "T-0002")     # 두 주제가 합쳐지면 더 앞 번호를 잇는다
        self.assertEqual(saved["y"], "T-0004")       # 처음 보는 것은 새 번호
        # T-0003(d 혼자였던 주제)은 어제 기록이 있으니 지워지지 않는다
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM topics").fetchone()[0], 4)
        self.assertEqual([r[0] for r in self.conn.execute(
            "SELECT date FROM topic_daily WHERE topic_code = 'T-0001' ORDER BY date")], ["2026-11-16", "2026-11-17"])

    def test_topic_that_splits_keeps_its_number_on_the_bigger_part(self):
        e1 = self.collect("2026-11-16", {"a": 400, "b": 100, "c": 50})
        self.save("2026-11-16", e1, [["a", "b", "c"]])
        e2 = self.collect("2026-11-17", {"a": 500, "b": 150, "c": 60})
        saved = self.codes(self.save("2026-11-17", e2, [["a"], ["b", "c"]]))
        self.assertEqual(sorted(saved.values()), ["T-0001", "T-0002"])
        self.assertEqual(saved["a"], "T-0001")  # 어텐션이 큰 쪽이 먼저 이어받는다

    def test_same_day_rerun_drops_numbers_that_no_longer_have_items(self):
        e = self.collect("2026-11-16", {"a": 400, "b": 100})
        self.save("2026-11-16", e, [["a"], ["b"]])
        saved = self.codes(self.save("2026-11-16", e, [["a", "b"]]))  # 검토 뒤 하나로 합쳐짐
        self.assertEqual(saved, {"a+b": "T-0001"})
        self.assertEqual([r[0] for r in self.conn.execute("SELECT code FROM topics")], ["T-0001"])

    def test_first_llm_name_sticks_and_later_names_become_aliases(self):
        e = self.collect("2026-11-16", {"a": 400, "b": 100})
        self.save("2026-11-16", e, [["a", "b"]])
        self.assertEqual(self.conn.execute("SELECT name, named_by_llm FROM topics").fetchone()[:], ("글 a", 0))
        self.save("2026-11-16", e, [["a", "b"]], names={0: "엔비디아 전망"})
        self.save("2026-11-16", e, [["a", "b"]], names={0: "Nvidia 향후 전망"})
        saved = self.save("2026-11-16", e, [["a", "b"]])  # LLM 없이 돌린 날에도 이름은 남는다
        self.assertEqual(self.conn.execute("SELECT name, aliases, named_by_llm FROM topics").fetchone()[:],
                         ("엔비디아 전망", '["Nvidia 향후 전망"]', 1))
        self.assertEqual(next(iter(saved.values()))["name"], "엔비디아 전망")

    def test_topics_survive_the_day_files(self):
        e1 = self.collect("2026-11-16", {"a": 400, "b": 100, "c": 50})
        self.save("2026-11-16", e1, [["a", "b"], ["c"]], names={0: "큰 주제"})
        e2 = self.collect("2026-11-17", {"a": 500, "b": 150, "x": 60})
        self.save("2026-11-17", e2, [["a", "b", "x"]])
        with tempfile.TemporaryDirectory() as tmp:
            for day in ("2026-11-16", "2026-11-17"):
                archive.export_day(self.conn, day, Path(tmp))
            fresh = db.connect(":memory:")
            self.addCleanup(fresh.close)
            archive.import_all(fresh, Path(tmp))

        def dump(conn):
            return (
                [tuple(r) for r in conn.execute("SELECT * FROM topics ORDER BY code")],
                [tuple(r) for r in conn.execute("SELECT * FROM topic_daily ORDER BY topic_code, date")],
                [tuple(r) for r in conn.execute(
                    "SELECT i.external_id, m.date, m.topic_code FROM topic_items m JOIN items i ON i.id = m.item_id "
                    "ORDER BY i.external_id, m.date")],
            )

        self.assertEqual(dump(fresh), dump(self.conn))
        # 되살린 뒤 다음 날을 저장해도 번호가 이어진다
        db.save_records(fresh, "2026-11-18", "hackernews", [story("a", 600, "2026-11-18"), story("z", 9, "2026-11-18")],
                        "2026-11-18T19:00:00+00:00")
        e3 = {e["external_id"]: e for e in rank.now_popular(fresh, "2026-11-18", SETTINGS)}
        found = [topics._make_topic([e3["a"]], SOURCES), topics._make_topic([e3["z"]], SOURCES)]
        saved = {t["items"][0]["external_id"]: t["code"] for t in topicstore.save_day(fresh, "2026-11-18", found, SETTINGS)}
        self.assertEqual(saved, {"a": "T-0001", "z": "T-0003"})


if __name__ == "__main__":
    unittest.main()
