"""서버(GitHub Actions)에서 하루 여러 번 돌 때의 동작: 막힌 소스는 '주의'로 건너뛰고,
한 번 실패해도 그날 앞서 모은 것은 남는다."""

import unittest
import urllib.error

from trendfeed import db
from trendfeed.run import collect_all
from tests.test_hackernews import FakeFetch, story
from tests.test_run import SAMPLE

SETTINGS = {
    "sources": {
        "hackernews": {"enabled": True, "api_base": "https://example.invalid/v0", "limit": 2, "workers": 2},
        "github_trending": {"enabled": True, "base_url": "https://example.invalid/trending",
                            "periods": ["daily", "weekly"], "pause_sec": 0},
    }
}


class Fetch(FakeFetch):
    github = "ok"  # "ok" | 403 | 429 | "timeout"

    def get_text(self, url, headers=None):
        if self.github == "timeout":
            raise TimeoutError()
        if self.github != "ok":
            raise urllib.error.HTTPError(url, self.github, "refused", None, None)
        return SAMPLE


class ServerRunTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)

    def run_once(self, day, github, top=(1, 2)):
        fetch = Fetch(list(top), {i: story(i) for i in range(1, 9)})
        fetch.github = github
        return {s["source"]: s for s in collect_all(SETTINGS, self.conn, day, fetch=fetch)}

    def test_blocked_github_is_a_warning_and_the_rest_runs(self):
        for code in (403, 429):
            with self.subTest(code=code):
                out = self.run_once(f"2026-11-1{code % 10}", code)
                self.assertEqual(out["hackernews"]["status"], "ok")
                gh = out["github_trending"]
                self.assertEqual((gh["status"], gh["item_count"]), ("warn", 0))
                self.assertEqual(gh["memo"], f"GitHub가 요청을 막아 건너뜀 (HTTP {code})")

    def test_other_failures_stay_no_input(self):
        gh = self.run_once("2026-11-16", "timeout")["github_trending"]
        self.assertEqual(gh["status"], "empty")

    def test_later_blocked_run_keeps_what_the_morning_run_collected(self):
        morning = self.run_once("2026-11-16", "ok")["github_trending"]
        self.assertEqual((morning["status"], morning["item_count"]), ("ok", 2))
        evening = self.run_once("2026-11-16", 403)["github_trending"]
        self.assertEqual((evening["status"], evening["item_count"]), ("warn", 2))
        self.assertEqual(self.conn.execute(
            "SELECT COUNT(*) FROM item_snapshots s JOIN items i ON i.id = s.item_id "
            "WHERE i.source = 'github_trending' AND s.date = '2026-11-16'").fetchone()[0], 2)

    def test_day_count_is_the_union_of_all_runs_that_day(self):
        self.run_once("2026-11-16", "ok", top=(1, 2))
        out = self.run_once("2026-11-16", "ok", top=(2, 3))  # 1번 글은 빠지고 3번이 새로 들어옴
        self.assertEqual((out["hackernews"]["status"], out["hackernews"]["item_count"]), ("ok", 3))
        self.assertEqual(out["github_trending"]["item_count"], 2)  # 같은 저장소는 한 번만 센다


if __name__ == "__main__":
    unittest.main()
