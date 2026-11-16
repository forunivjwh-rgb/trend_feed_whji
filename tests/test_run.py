"""수집 → 저장 → 실행 기록이 하루하루 어떻게 쌓이는지 확인한다(가짜 응답 사용, 인터넷 없음)."""

import json
import plistlib
import unittest
from pathlib import Path
from xml.etree import ElementTree

from trendfeed import config, db, schedule
from trendfeed.run import collect_all
from tests.test_hackernews import FakeFetch, story

SAMPLE = (Path(__file__).parent / "fixtures" / "github_trending_sample.html").read_text(encoding="utf-8")

SETTINGS = {
    "sources": {
        "hackernews": {
            "enabled": True,
            "api_base": "https://example.invalid/v0",
            "limit": 2,
            "workers": 2,
            "follow_days": 2,
        },
        "github_trending": {
            "enabled": True,
            "base_url": "https://example.invalid/trending",
            "periods": ["daily"],
            "pause_sec": 0,
        },
    }
}


class Fetch(FakeFetch):
    github_ok = True

    def get_text(self, url):
        if not self.github_ok:
            raise TimeoutError()
        return SAMPLE


def rows(conn, sql, *args):
    return [tuple(r) for r in conn.execute(sql, args).fetchall()]


class DailyRunTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)

    def run_day(self, day, fetch):
        return {s["source"]: s for s in collect_all(SETTINGS, self.conn, day, fetch=fetch)}

    def test_first_day_stores_items_snapshots_and_run_rows(self):
        out = self.run_day("2026-11-16", Fetch([1, 2, 3], {i: story(i) for i in (1, 2, 3)}))
        self.assertEqual((out["hackernews"]["status"], out["hackernews"]["item_count"]), ("ok", 2))
        self.assertEqual((out["github_trending"]["status"], out["github_trending"]["item_count"]), ("ok", 2))
        self.assertEqual(
            rows(self.conn, "SELECT source, external_id, origin, first_seen FROM items ORDER BY id"),
            [
                ("hackernews", "1", "site1.example", "2026-11-16"),
                ("hackernews", "2", "site2.example", "2026-11-16"),
                ("github_trending", "acme/rocket", "github.com/acme", "2026-11-16"),
                ("github_trending", "Solo-Dev/notes.app", "github.com/solo-dev", "2026-11-16"),
            ],
        )
        self.assertEqual(
            rows(self.conn, "SELECT item_id, date, listed, rank, stars, score, comments FROM item_snapshots ORDER BY item_id"),
            [
                (1, "2026-11-16", 1, 1, None, 10, 1),
                (2, "2026-11-16", 1, 2, None, 20, 2),
                (3, "2026-11-16", 1, 1, 12345, None, None),
                (4, "2026-11-16", 1, 2, 987, None, None),
            ],
        )
        extra = json.loads(self.conn.execute("SELECT extra FROM item_snapshots WHERE item_id = 3").fetchone()[0])
        self.assertEqual(extra, {"forks": 678, "rank_daily": 1, "stars_daily": 1234})
        self.assertEqual(
            rows(self.conn, "SELECT date, source, item_count, status, memo FROM source_runs ORDER BY source"),
            [("2026-11-16", "github_trending", 2, "ok", ""), ("2026-11-16", "hackernews", 2, "ok", "")],
        )

    def test_same_day_rerun_overwrites_instead_of_duplicating(self):
        self.run_day("2026-11-16", Fetch([1, 2], {1: story(1), 2: story(2)}))
        self.run_day("2026-11-16", Fetch([1, 2], {1: story(1, score=99), 2: story(2)}))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM items").fetchone()[0], 4)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM item_snapshots").fetchone()[0], 4)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM source_runs").fetchone()[0], 2)
        self.assertEqual(self.conn.execute("SELECT score FROM item_snapshots WHERE item_id = 1").fetchone()[0], 99)

    def test_next_day_adds_a_snapshot_keeps_first_seen_and_follows_dropped_posts(self):
        self.run_day("2026-11-16", Fetch([1, 2], {1: story(1), 2: story(2)}))
        # 다음 날: 1번 글은 목록에서 빠지고 3번이 들어온다. 1번은 숫자만 다시 적힌다.
        items = {1: story(1, score=500), 2: story(2, score=25, title="Story 2 (edited)"), 3: story(3)}
        out = self.run_day("2026-11-17", Fetch([2, 3], items))
        self.assertEqual((out["hackernews"]["item_count"], out["hackernews"]["followed_count"]), (2, 1))
        self.assertEqual(
            rows(
                self.conn,
                "SELECT i.external_id, s.date, s.listed, s.rank, s.score FROM item_snapshots s "
                "JOIN items i ON i.id = s.item_id WHERE i.source = 'hackernews' ORDER BY i.external_id, s.date",
            ),
            [
                ("1", "2026-11-16", 1, 1, 10),
                ("1", "2026-11-17", 0, None, 500),
                ("2", "2026-11-16", 1, 2, 20),
                ("2", "2026-11-17", 1, 1, 25),
                ("3", "2026-11-17", 1, 2, 30),
            ],
        )
        self.assertEqual(
            rows(self.conn, "SELECT title, first_seen FROM items WHERE external_id = '2'"),
            [("Story 2 (edited)", "2026-11-16")],
        )

    def test_dropped_posts_are_followed_only_for_follow_days(self):
        self.run_day("2026-11-16", Fetch([1, 2], {1: story(1), 2: story(2)}))
        later = {i: story(i) for i in (1, 2, 3, 4)}
        for day in ("2026-11-17", "2026-11-18"):
            self.assertEqual(self.run_day(day, Fetch([3, 4], later))["hackernews"]["followed_count"], 2)
        # 목록에 마지막으로 있던 날(16일)에서 2일이 지나면 그만 따라간다.
        self.assertEqual(self.run_day("2026-11-19", Fetch([3, 4], later))["hackernews"]["followed_count"], 0)

    def test_one_source_failing_does_not_stop_the_other(self):
        fetch = Fetch([1, 2], {1: story(1), 2: story(2)})
        fetch.github_ok = False
        out = self.run_day("2026-11-16", fetch)
        self.assertEqual(out["hackernews"]["status"], "ok")
        self.assertEqual(out["github_trending"]["status"], "empty")
        self.assertEqual(out["github_trending"]["memo"], "daily 목록을 받지 못함 (TimeoutError)")

    def test_partial_failure_is_marked_warn(self):
        fetch = Fetch([1, 2, 3], {i: story(i) for i in (1, 2, 3)}, broken=[1])
        out = self.run_day("2026-11-16", fetch)
        self.assertEqual((out["hackernews"]["status"], out["hackernews"]["item_count"]), ("warn", 2))
        self.assertEqual(out["hackernews"]["memo"], "글 1개를 읽지 못함")

    def test_disabled_source_is_skipped(self):
        settings = {"sources": {**SETTINGS["sources"], "github_trending": {"enabled": False}}}
        out = collect_all(settings, self.conn, "2026-11-16", fetch=Fetch([1], {1: story(1)}))
        self.assertEqual([s["source"] for s in out], ["hackernews"])


class SettingsFileTest(unittest.TestCase):
    def test_shipped_settings_have_what_the_code_reads(self):
        s = config.load()
        self.assertEqual(s["sources"]["hackernews"]["limit"], 60)
        self.assertEqual(s["sources"]["github_trending"]["periods"], ["daily", "weekly"])
        self.assertRegex(config.today(s), r"^\d{4}-\d{2}-\d{2}$")

    def test_mac_schedule_uses_configured_time(self):
        plist = plistlib.loads(schedule.build_plist(config.load()))
        self.assertEqual(plist["StartCalendarInterval"], {"Hour": 4, "Minute": 0})
        self.assertEqual(plist["ProgramArguments"][1:], ["-m", "trendfeed", "daily"])
        self.assertEqual(plist["WorkingDirectory"], str(config.ROOT))

    def test_windows_schedule_runs_daily_and_catches_up_missed_runs(self):
        ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        python = r"C:\Users\홍 길동\trend & feed\.venv\Scripts\pythonw.exe"
        xml = schedule.build_windows_xml(config.load(), python=python)
        root = ElementTree.fromstring(xml.encode("utf-16"))  # 윈도우가 읽는 것과 같은 글자 형식으로 읽어 본다
        find = lambda path: root.find(path, ns).text  # noqa: E731
        self.assertEqual(find("t:Triggers/t:CalendarTrigger/t:StartBoundary")[-8:], "04:00:00")
        self.assertEqual(find("t:Triggers/t:CalendarTrigger/t:ScheduleByDay/t:DaysInterval"), "1")
        self.assertEqual(find("t:Settings/t:StartWhenAvailable"), "true")
        self.assertEqual(find("t:Settings/t:WakeToRun"), "false")
        self.assertEqual(find("t:Settings/t:DisallowStartIfOnBatteries"), "false")
        self.assertEqual(find("t:Settings/t:ExecutionTimeLimit"), "PT3H")
        self.assertEqual(find("t:Actions/t:Exec/t:Command"), python)
        self.assertEqual(find("t:Actions/t:Exec/t:Arguments"), "-m trendfeed daily")
        self.assertEqual(find("t:Actions/t:Exec/t:WorkingDirectory"), str(config.ROOT))


if __name__ == "__main__":
    unittest.main()
