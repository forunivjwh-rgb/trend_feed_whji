"""날짜별 파일로 내보냈다가 다시 읽으면 저장 파일이 그대로 되살아나는지 확인한다."""

import tempfile
import unittest
from pathlib import Path

from trendfeed import archive, config, db, feed
from trendfeed.sources import Record

SETTINGS = config.load()


def rec(ext_id, score, title=None, listed=True):
    return Record(external_id=ext_id, title=title or f"글 {ext_id}", url=f"https://example.com/{ext_id}",
                  origin="example.com", published_at="2026-11-16T01:00:00+00:00",
                  rank=1 if listed else None, listed=listed, metrics={"score": score, "comments": 2},
                  item_extra={"by": "누구"}, snap_extra={"note": "한글"})


def fill(conn):
    db.save_records(conn, "2026-11-16", "hackernews", [rec("1", 10), rec("2", 20)], "2026-11-16T19:00:00+00:00")
    db.save_run(conn, "2026-11-16", "hackernews", item_count=2, followed_count=0, status="ok", memo="",
                started_at="2026-11-16T19:00:00+00:00", duration_sec=1.5)
    db.save_records(conn, "2026-11-17", "hackernews",
                    [rec("2", 90, title="글 2 (고침)"), rec("1", 15, listed=False)], "2026-11-17T19:00:00+00:00")
    db.save_run(conn, "2026-11-17", "hackernews", item_count=1, followed_count=1, status="warn",
                memo="글 1개를 읽지 못함", started_at="2026-11-17T19:00:00+00:00", duration_sec=2.0)
    db.save_run(conn, "2026-11-17", "youtube", item_count=0, followed_count=0, status="empty",
                memo="API 키 없음", started_at="2026-11-17T19:00:05+00:00", duration_sec=0.0)


def dump(conn):
    return {
        "runs": [tuple(r) for r in conn.execute("SELECT * FROM source_runs ORDER BY date, source")],
        "items": [tuple(r) for r in conn.execute(
            "SELECT source, external_id, title, origin, url, published_at, first_seen, extra FROM items ORDER BY external_id")],
        "snaps": [tuple(r) for r in conn.execute(
            "SELECT i.external_id, s.date, s.captured_at, s.listed, s.rank, s.views, s.stars, s.score, s.comments, s.likes, s.extra "
            "FROM item_snapshots s JOIN items i ON i.id = s.item_id ORDER BY i.external_id, s.date")],
    }


class ArchiveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        fill(self.conn)

    def export_both(self):
        for day in ("2026-11-16", "2026-11-17"):
            archive.export_day(self.conn, day, self.dir)

    def test_round_trip_rebuilds_the_same_database(self):
        self.export_both()
        fresh = db.connect(":memory:")
        self.addCleanup(fresh.close)
        self.assertEqual(archive.import_all(fresh, self.dir), 2)
        self.assertEqual(dump(fresh), dump(self.conn))
        # 되살린 것으로 만든 피드도 같다
        self.assertEqual(feed.build(fresh, "2026-11-17", SETTINGS), feed.build(self.conn, "2026-11-17", SETTINGS))

    def test_importing_twice_changes_nothing(self):
        self.export_both()
        fresh = db.connect(":memory:")
        self.addCleanup(fresh.close)
        archive.import_all(fresh, self.dir)
        archive.import_all(fresh, self.dir)
        self.assertEqual(dump(fresh), dump(self.conn))

    def test_one_file_per_day_with_stable_readable_lines(self):
        self.export_both()
        files = sorted(p.name for p in (self.dir / "days").iterdir())
        self.assertEqual(files, ["2026-11-16.jsonl", "2026-11-17.jsonl"])
        first = (self.dir / "days" / "2026-11-17.jsonl").read_text(encoding="utf-8")
        self.assertIn("글 2 (고침)", first)  # 한글이 그대로 보인다
        archive.export_day(self.conn, "2026-11-17", self.dir)
        self.assertEqual((self.dir / "days" / "2026-11-17.jsonl").read_text(encoding="utf-8"), first)

    def test_no_files_yet_means_an_empty_start(self):
        fresh = db.connect(":memory:")
        self.addCleanup(fresh.close)
        self.assertEqual(archive.import_all(fresh, self.dir / "nothing-here"), 0)


if __name__ == "__main__":
    unittest.main()
