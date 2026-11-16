"""하루 증가량과 "보통의 몇 배" 계산을 손으로 계산한 값과 맞춰 본다."""

import unittest

from trendfeed import db, rank
from trendfeed.sources import Record

CFG = {"min_gap_hours": 6, "compare_within_days": 3, "median_floor": 1.0}
SETTINGS = {
    "attention": CFG,
    "sources": {"hackernews": {"weight": 1.0}, "github_trending": {"weight": 1.0}},
}
HN = {"metric": "score", "unit": "점"}
GH = {"metric": "stars", "unit": "별", "reported_daily": "stars_daily", "reported_weekly": "stars_weekly"}


def snap(captured_at, date="2026-11-17", extra=None, **metrics):
    return {"captured_at": captured_at, "date": date, "extra": extra or {}, "score": None, "stars": None, **metrics}


class VelocityTest(unittest.TestCase):
    def test_source_reported_daily_gain_wins(self):
        s = snap("2026-11-17T19:00:00+00:00", stars=5000, extra={"stars_daily": 300, "stars_weekly": 700})
        prev = snap("2026-11-16T19:00:00+00:00", date="2026-11-16", stars=4000)
        self.assertEqual(rank.velocity(GH, s, prev, None, CFG), (300.0, "오늘 늘어난 양(소스 제공)"))

    def test_difference_from_previous_day_uses_the_real_gap(self):
        # 36시간 사이에 300점 → 하루로 치면 200점
        s = snap("2026-11-18T07:00:00+00:00", score=400)
        prev = snap("2026-11-16T19:00:00+00:00", date="2026-11-16", score=100)
        self.assertEqual(rank.velocity(HN, s, prev, None, CFG), (200.0, "11/16 기록 대비"))

    def test_a_falling_number_counts_as_zero(self):
        s = snap("2026-11-17T19:00:00+00:00", score=90)
        prev = snap("2026-11-16T19:00:00+00:00", date="2026-11-16", score=100)
        self.assertEqual(rank.velocity(HN, s, prev, None, CFG)[0], 0)

    def test_previous_record_too_close_is_not_compared(self):
        s = snap("2026-11-17T03:00:00+00:00", score=400)
        prev = snap("2026-11-17T00:00:00+00:00", date="2026-11-16", score=100)  # 3시간 전
        v, basis = rank.velocity(HN, s, prev, "2026-11-16T23:00:00+00:00", CFG)
        self.assertEqual((v, basis), (400.0, "처음 봄 · 올라온 지 하루 안 됨"))

    def test_weekly_only_is_divided_by_seven(self):
        s = snap("2026-11-17T19:00:00+00:00", stars=5000, extra={"stars_weekly": 700})
        self.assertEqual(rank.velocity(GH, s, None, None, CFG), (100.0, "이번 주 늘어난 양 ÷ 7"))

    def test_first_seen_older_post_uses_its_daily_average(self):
        s = snap("2026-11-17T12:00:00+00:00", score=300)
        v, basis = rank.velocity(HN, s, None, "2026-11-15T12:00:00+00:00", CFG)
        self.assertEqual((v, basis), (150.0, "처음 봄 · 올라온 뒤 2.0일 평균"))

    def test_nothing_to_go_on(self):
        self.assertEqual(rank.velocity(GH, snap("2026-11-17T19:00:00+00:00", stars=10), None, None, CFG), (None, None))


def rec(ext_id, published_at=None, extra=None, **metrics):
    return Record(external_id=ext_id, title=ext_id, url="u", origin="o", published_at=published_at,
                  rank=1, metrics=metrics, snap_extra=extra or {})


class NowPopularTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        t = "2026-11-17T19:00:00+00:00"
        fresh = "2026-11-17T10:00:00+00:00"
        # HN: 처음 본 글 셋(하루 안 됨) → 속도 = 점수. 가운데 값 100
        db.save_records(self.conn, "2026-11-17", "hackernews",
                        [rec("a", fresh, score=50), rec("b", fresh, score=100), rec("c", fresh, score=400)], t)
        # GitHub: 오늘 +별 200 / 1000 / 600 → 가운데 값 600
        db.save_records(self.conn, "2026-11-17", "github_trending",
                        [rec("x/1", extra={"stars_daily": 200}, stars=9000),
                         rec("x/2", extra={"stars_daily": 1000}, stars=3000),
                         rec("x/3", extra={"stars_daily": 600}, stars=100)], t)

    def test_ranks_across_sources_by_times_typical(self):
        ranked = rank.now_popular(self.conn, "2026-11-17", SETTINGS)
        self.assertEqual(
            [(e["title"], round(e["times_typical"], 2)) for e in ranked],
            [("c", 4.0), ("x/2", 1.67), ("x/3", 1.0), ("b", 1.0), ("a", 0.5), ("x/1", 0.33)],
        )
        self.assertEqual([e["place"] for e in ranked], [1, 2, 3, 4, 5, 6])

    def test_source_weight_scales_attention(self):
        settings = {"attention": CFG, "sources": {"hackernews": {"weight": 0.3}, "github_trending": {"weight": 1.0}}}
        ranked = rank.now_popular(self.conn, "2026-11-17", settings)
        self.assertEqual(ranked[0]["title"], "x/2")
        c = next(e for e in ranked if e["title"] == "c")
        self.assertAlmostEqual(c["attention"], 1.2)

    def test_items_only_followed_today_are_not_ranked(self):
        dropped = rec("old", "2026-11-15T10:00:00+00:00", score=9999)
        dropped.listed, dropped.rank = False, None
        db.save_records(self.conn, "2026-11-17", "hackernews", [dropped], "2026-11-17T19:00:00+00:00")
        self.assertNotIn("old", [e["title"] for e in rank.now_popular(self.conn, "2026-11-17", SETTINGS)])

    def test_next_day_uses_the_difference(self):
        db.save_records(self.conn, "2026-11-18", "hackernews", [rec("c", score=460)], "2026-11-18T19:00:00+00:00")
        (only,) = rank.now_popular(self.conn, "2026-11-18", SETTINGS)
        self.assertEqual((only["velocity"], only["basis"]), (60.0, "11/17 기록 대비"))


if __name__ == "__main__":
    unittest.main()
