""""몰랐는데 흥미로움" 표시: GitHub 이슈로 남긴 것을 읽어 기록하고 닫는다(가짜 GitHub)."""

import unittest
import urllib.parse
from unittest import mock

from trendfeed import config, db, feed, feedback
from tests.test_feed import make_topics
from tests.test_hackernews import story
from trendfeed.sources import hackernews

DAY = "2026-11-17"
REPO = "owner-name/trend_feed_whji"


def settings_with_repo():
    s = config.load()
    s["feedback"] = {**s["feedback"], "repo": REPO}
    return s


class FakeGitHub:
    def __init__(self, issues):
        self.issues, self.closed, self.headers = issues, [], []

    def get_json(self, url, headers=None):
        self.headers.append(headers)
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        assert query["creator"] == ["owner-name"] and query["state"] == ["open"]
        return self.issues

    def send_json(self, method, url, data, headers=None):
        self.closed.append((method, url.rsplit("/", 1)[1], data))


def issue(number, title, login="owner-name", pr=False):
    out = {"number": number, "title": title, "user": {"login": login}}
    if pr:
        out["pull_request"] = {}
    return out


class FeedbackTest(unittest.TestCase):
    def setUp(self):
        self.settings = settings_with_repo()
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        records = [hackernews.to_record(story(i, time=1794826996), rank=i, listed=True) for i in range(1, 9)]
        db.save_records(self.conn, DAY, "hackernews", records, DAY + "T19:00:00+00:00")
        db.save_run(self.conn, DAY, "hackernews", item_count=8, followed_count=0, status="ok", memo="",
                    started_at=DAY + "T19:00:00+00:00", duration_sec=1)
        make_topics(self.conn, DAY, self.settings)
        self.top = self.conn.execute("SELECT topic_code FROM topic_score WHERE rank = 1").fetchone()[0]

    def sync(self, gh, token="tok"):
        with mock.patch.object(config, "secret", lambda name: token if name == "GITHUB_TOKEN" else None):
            return feedback.sync(self.conn, self.settings, gh, say=lambda s: None)

    def test_records_only_the_owners_marked_issues_and_closes_them(self):
        gh = FakeGitHub([
            issue(5, f"[흥미로움] {self.top} {DAY}"),
            issue(6, f"[흥미로움] {self.top} {DAY}", login="someone-else"),  # 다른 사람 → 무시
            issue(7, f"[흥미로움] T-9999 {DAY}"),                              # 없는 주제 → 무시
            issue(8, "버그 보고"),                                              # 다른 이슈 → 무시
            issue(9, f"[흥미로움] {self.top} {DAY}", pr=True),                  # PR → 무시
        ])
        result = self.sync(gh)
        self.assertEqual(result["recorded"], 1)
        self.assertEqual(self.conn.execute("SELECT topic_code, date, interesting, issue FROM feedback").fetchall()[0][:],
                         (self.top, DAY, 1, 5))
        self.assertEqual(gh.closed, [("PATCH", "5", {"state": "closed", "state_reason": "completed"})])
        self.assertEqual(gh.headers[0]["Authorization"], "Bearer tok")

    def test_without_a_token_it_is_skipped(self):
        gh = FakeGitHub([issue(5, f"[흥미로움] {self.top} {DAY}")])
        result = self.sync(gh, token=None)
        self.assertEqual(result["recorded"], 0)
        self.assertIn("건너뜀", result["note"])

    def test_feed_shows_the_link_then_the_mark_and_the_count(self):
        html = feed.build(self.conn, DAY, self.settings)
        self.assertIn(f"https://github.com/{REPO}/issues/new?", html)
        self.assertIn(urllib.parse.quote_plus(f"[흥미로움] {self.top} {DAY}"), html)
        self.assertIn('"몰랐는데 흥미로움" 0개', html)
        self.sync(FakeGitHub([issue(5, f"[흥미로움] {self.top} {DAY}")]))
        html = feed.build(self.conn, DAY, self.settings)
        self.assertIn("✓ 몰랐는데 흥미로움", html)
        self.assertIn('"몰랐는데 흥미로움" 1개', html)

    def test_no_repo_means_no_link(self):
        settings = config.load()
        settings["feedback"] = {**settings["feedback"], "repo": ""}
        with mock.patch.dict("os.environ", {}, clear=False):
            import os
            os.environ.pop("GITHUB_REPOSITORY", None)
            html = feed.build(self.conn, DAY, settings)
        self.assertNotIn("issues/new", html)


if __name__ == "__main__":
    unittest.main()
