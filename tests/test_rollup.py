"""롤업(일·주·월): 가상의 15일 기록으로 손으로 계산한 결과와 맞춰 본다. 14일 전에는 피드에서 숨긴다."""

import json
import unittest

from trendfeed import config, db, feed, rollup, score

SETTINGS = config.load()
CFG = SETTINGS["rollup"]


def day_of(n):
    return f"2026-11-{n:02d}"


class RollupTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)

    def add_day(self, n, topics_today: dict, first_seen=None):
        """topics_today: 주제 번호 → {플랫폼: 어텐션}. 출처는 3곳으로 둔다(점수 모드 순위 조건)."""
        day = day_of(n)
        db.save_run(self.conn, day, "hackernews", item_count=1, followed_count=0, status="ok", memo="",
                    started_at=day + "T19:00:00+00:00", duration_sec=1)
        for code, plats in topics_today.items():
            self.conn.execute("INSERT OR IGNORE INTO topics (code, name, field, first_seen) VALUES (?, ?, '개발·OSS', ?)",
                              (code, f"주제 {code}", (first_seen or {}).get(code, day)))
            self.conn.execute(
                "INSERT INTO topic_daily (topic_code, date, attention, platforms, origins, item_count) VALUES (?, ?, ?, ?, 3, 3)",
                (code, day, sum(plats.values()), json.dumps(plats)))
        self.conn.commit()
        score.compute(self.conn, day, SETTINGS)
        return day

    def build_history(self):
        """1~13일: A~F 가 고르게 있고(어텐션 A>B>C>D>E>F), 14·15일에 순위가 바뀐다."""
        base = {"T-000A": 6.0, "T-000B": 5.0, "T-000C": 4.0, "T-000D": 3.0, "T-000E": 2.0, "T-000F": 1.0}
        for n in range(1, 14):
            self.add_day(n, {c: {"HN": v} for c, v in base.items()})
        # 14일: E 가 크게 오른다
        self.add_day(14, {**{c: {"HN": v} for c, v in base.items()}, "T-000E": {"HN": 2.0, "GN": 30.0}})
        # 15일: 새 주제 N 이 나타나 크게 오르고, A 는 사라진다. E 는 GN 쪽이 계속 크다
        today = {c: {"HN": v} for c, v in base.items() if c != "T-000A"}
        today["T-000E"] = {"HN": 2.0, "GN": 30.0, "YT": 8.0}
        today["T-000N"] = {"HN": 20.0, "WK": 10.0}
        return self.add_day(15, today)

    def test_daily_compares_yesterday_and_today(self):
        day = self.build_history()
        d = rollup.daily(self.conn, day, CFG)
        ranks_today = {c: r for c, r in self.conn.execute("SELECT topic_code, rank FROM topic_score WHERE date = ?", (day,))}
        self.assertLessEqual(ranks_today["T-000N"], CFG["daily_top"])
        self.assertIn("T-000N", [r[0] for r in d["entered"]])
        self.assertIn("T-000A", [r[0] for r in d["left"]])
        self.assertTrue(all(r[2] > r[3] for r in d["risers"]))  # 오른 주제는 순위 숫자가 작아진다

    def test_weekly_lasting_new_and_left(self):
        day = self.build_history()
        w = rollup.weekly(self.conn, day, CFG)
        self.assertEqual([r[0] for r in w["new"]], ["T-000N"])          # 오늘 처음 나타나 8위 안
        self.assertIn("T-000A", [r[0] for r in w["left"]])              # 4위 안에 있다가 오늘은 없음
        lasting = {r[0]: r[2] for r in w["lasting"]}
        self.assertGreaterEqual(lasting.get("T-000E", 0), 2)

    def test_monthly_curves_are_scaled_per_platform_and_lag_is_measured(self):
        day = self.build_history()
        m = rollup.monthly(self.conn, day, "T-000E", CFG)
        self.assertEqual(sorted(m["curves"]), ["GN", "HN", "YT"])
        self.assertEqual(max(m["curves"]["GN"]), 100.0)
        self.assertEqual(m["curves"]["HN"][-1], 100.0)  # HN 은 내내 같은 값 → 날마다 100
        lags = {p: (first, gap) for p, first, gap in m["lags"]}
        self.assertEqual(lags["HN"], (day_of(1), 0))     # HN 이 가장 먼저
        self.assertEqual(lags["GN"], (day_of(14), 13))   # GN 은 13일 늦게
        self.assertEqual(lags["YT"], (day_of(15), 14))

    def test_feed_shows_rollups_only_in_score_mode(self):
        for n in range(1, 3):
            self.add_day(n, {"T-000A": {"HN": 1.0}})
        early = feed.build(self.conn, day_of(2), SETTINGS)
        self.assertNotIn("<h2>롤업</h2>", early)
        for n in range(3, 16):
            self.add_day(n, {"T-000A": {"HN": 1.0}, "T-000B": {"HN": 0.5 if n < 15 else 9.0, "GN": 3.0}})
        html = feed.build(self.conn, day_of(15), SETTINGS)
        for text in ("<h2>롤업</h2>", "일 — 어제와 오늘", "주 — 최근 7일", "월 — ", "최대치의 50%를 처음 넘은 날",
                     "일 값 표 펼치기", "교차 플랫폼 Top 5"):
            self.assertIn(text, html)


if __name__ == "__main__":
    unittest.main()
