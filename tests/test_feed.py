"""피드 페이지가 계산된 순위를 그대로 보여 주고, 수집한 글자를 안전하게 넣는지 확인한다."""

import unittest

from trendfeed import config, db, feed
from trendfeed.sources import Record

T = "2026-11-17T19:00:00+00:00"
FRESH = "2026-11-17T10:00:00+00:00"


def hn(ext_id, title, score, url="https://example.com/a"):
    return Record(external_id=ext_id, title=title, url=url, origin="example.com", published_at=FRESH,
                  rank=1, metrics={"score": score, "comments": 3},
                  item_extra={"discuss_url": f"https://news.ycombinator.com/item?id={ext_id}"})


class FeedTest(unittest.TestCase):
    def setUp(self):
        self.settings = config.load()
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        records = [hn(str(i), f"Story {i}", i * 10) for i in range(1, 13)]
        records.append(hn("90", "<script>alert(1)</script> & co", 900))
        records.append(hn("91", "Sneaky link", 5, url="javascript:alert(1)"))
        db.save_records(self.conn, "2026-11-17", "hackernews", records, T)
        gh = Record(external_id="acme/rocket", title="acme/rocket", url="https://github.com/acme/rocket",
                    origin="github.com/acme", published_at=None, rank=1, metrics={"stars": 5000},
                    item_extra={"description": "A <b>tiny</b> launcher"}, snap_extra={"stars_daily": 300, "forks": 7})
        db.save_records(self.conn, "2026-11-17", "github_trending", [gh], T)
        for source, n in (("hackernews", 14), ("github_trending", 1)):
            db.save_run(self.conn, "2026-11-17", source, item_count=n, followed_count=0, status="ok",
                        memo="", started_at=T, duration_sec=1.5)
        db.save_run(self.conn, "2026-11-16", "hackernews", item_count=0, followed_count=0, status="empty",
                    memo="수집 실패 (TimeoutError)", started_at=T, duration_sec=1.0)
        self.html = feed.build(self.conn, "2026-11-17", self.settings)

    def test_now_popular_mode_with_baseline_progress(self):
        self.assertIn("기준선이 쌓이는 중이에요 (1/14일)", self.html)  # 실패한 날은 세지 않는다
        self.assertIn("지금 인기 Top 5", self.html)
        self.assertNotIn("롤업 ·", self.html)

    def test_top_card_shows_the_computed_numbers(self):
        # 가운데 값은 65점(1~12번 글 + 900점 + 5점). 900 ÷ 65 = 13.8배
        top = self.html.split('<article class="card">')[1]
        self.assertIn("13.8배", top)
        self.assertIn("+900점", top)
        self.assertIn("+65점", top)

    def test_collected_text_is_escaped_and_bad_links_are_not_linked(self):
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; co", self.html)
        self.assertNotIn("<script>alert(1)", self.html)
        self.assertNotIn("javascript:", self.html)
        self.assertNotIn("<b>tiny</b>", self.html)

    def test_every_section_and_source_row_is_there(self):
        for text in ("분야별 Top 3", "탐색 슬롯", "수집 상태와 오늘의 실행", "Hacker News", "GitHub trending", "14건", "정상"):
            self.assertIn(text, self.html)

    def test_same_day_rebuild_is_identical(self):
        self.assertEqual(self.html, feed.build(self.conn, "2026-11-17", self.settings))

    def test_day_with_nothing_collected_still_renders(self):
        html = feed.build(self.conn, "2026-11-16", self.settings)
        self.assertIn("수집 실패 (TimeoutError)", html)
        self.assertIn("입력 없음", html)


if __name__ == "__main__":
    unittest.main()
