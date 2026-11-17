"""주제 점수: 샘플 logic.js 와 같은 식인지, 모드·출처 조건·순위가 맞는지 손으로 계산한 값과 맞춰 본다."""

import json
import math
import unittest

from trendfeed import config, db, score

SETTINGS = config.load()
CFG = SETTINGS["score"]


def day_of(n):
    return f"2026-11-{n:02d}" if n <= 30 else f"2026-12-{n - 30:02d}"


class StatsTest(unittest.TestCase):
    def test_flat_history_then_jump(self):
        series = [1.0] * 20 + [5.0]
        st = score.stats(series, CFG)
        self.assertEqual((st["median"], st["mad"]), (1.0, 0.0))
        self.assertAlmostEqual(st["z"], (5 - 1) / 0.8)  # MAD 가 0이면 완충값만으로 나눈다
        self.assertAlmostEqual(st["accel"], ((1 + 1 + 5) / 3) / ((13 + 5) / 14))

    def test_baseline_is_at_most_28_days_before_today(self):
        series = [100.0] * 10 + [2.0] * 28 + [2.0]
        self.assertEqual(score.stats(series, CFG)["median"], 2.0)  # 오래된 100 은 보지 않는다

    def test_mad_uses_the_robust_scale(self):
        series = [1, 2, 3, 4, 5, 10.0]
        st = score.stats(series, CFG)
        self.assertEqual((st["median"], st["mad"]), (3, 1))
        self.assertAlmostEqual(st["z"], (10 - 3) / (1.4826 * 1 + 0.8))


class ComputeTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)

    def add_day(self, n, topics_today: dict):
        """topics_today: 주제 번호 → (어텐션, 플랫폼 목록, 출처 수)."""
        day = day_of(n)
        db.save_run(self.conn, day, "hackernews", item_count=1, followed_count=0, status="ok", memo="",
                    started_at=day + "T19:00:00+00:00", duration_sec=1)
        for code, (att, plats, origins) in topics_today.items():
            self.conn.execute("INSERT OR IGNORE INTO topics (code, name, field, first_seen) VALUES (?, ?, '개발·OSS', ?)",
                              (code, f"주제 {code}", day))
            self.conn.execute(
                "INSERT INTO topic_daily (topic_code, date, attention, platforms, origins, item_count) VALUES (?, ?, ?, ?, ?, 1)",
                (code, day, att, json.dumps({p: att / len(plats) for p in plats}), origins))
        self.conn.commit()
        return day

    def ranks(self, day):
        return {r["topic_code"]: dict(r) for r in self.conn.execute("SELECT * FROM topic_score WHERE date = ?", (day,))}

    def test_early_mode_ranks_by_attention_and_still_needs_three_origins(self):
        day = self.add_day(1, {"T-0001": (2.0, ["HN"], 3), "T-0002": (5.0, ["HN", "GN"], 4),
                               "T-0003": (9.0, ["YT"], 2)})
        summary = score.compute(self.conn, day, SETTINGS)
        self.assertEqual((summary["mode"], summary["days"], summary["ranked"], summary["passed"]), ("early", 1, 2, 0))
        r = self.ranks(day)
        self.assertEqual((r["T-0002"]["rank"], r["T-0001"]["rank"]), (1, 2))
        self.assertIsNone(r["T-0003"]["rank"])  # 어텐션이 가장 커도 출처 2곳이면 순위 밖(명세 3번)
        self.assertIsNone(r["T-0002"]["score"])
        self.assertEqual(r["T-0002"]["breadth"], 2)

    def test_score_mode_after_14_days_matches_the_formula(self):
        for n in range(1, 14):
            self.add_day(n, {"T-0001": (1.0, ["HN"], 3), "T-0002": (3.0, ["HN"], 3)})
        day = self.add_day(14, {"T-0001": (9.0, ["HN", "GN", "WK"], 4), "T-0002": (3.0, ["HN"], 3),
                                "T-0003": (50.0, ["YT"], 1)})
        summary = score.compute(self.conn, day, SETTINGS)
        self.assertEqual(summary["mode"], "score")
        r = self.ranks(day)
        z = (9 - 1) / 0.8                       # 10 → 상한 8
        accel = ((1 + 1 + 9) / 3) / ((13 + 9) / 14)
        expected = min(z, 8) + 1.5 * math.log(accel) + 0.5 * 2
        self.assertAlmostEqual(r["T-0001"]["score"], expected)
        self.assertEqual((r["T-0001"]["rank"], r["T-0001"]["passed"]), (1, 1))
        self.assertAlmostEqual(r["T-0002"]["score"], 0.0)  # 평소와 같으면 0
        self.assertEqual((r["T-0002"]["rank"], r["T-0002"]["passed"]), (2, 0))
        # 출처가 1곳뿐인 주제는 어텐션이 커도 순위에 오르지 않는다
        self.assertIsNone(r["T-0003"]["rank"])
        self.assertEqual(r["T-0003"]["passed"], 0)

    def test_new_topic_with_no_history_counts_missing_days_as_zero(self):
        for n in range(1, 14):
            self.add_day(n, {"T-0001": (1.0, ["HN"], 3)})
        day = self.add_day(14, {"T-0001": (1.0, ["HN"], 3), "T-0009": (2.0, ["HN", "GN"], 3)})
        score.compute(self.conn, day, SETTINGS)
        r = self.ranks(day)["T-0009"]
        self.assertAlmostEqual(r["z"], 2 / 0.8)
        self.assertAlmostEqual(r["accel"], (2 / 3) / (2 / 14))

    def test_failed_days_do_not_count_toward_the_baseline(self):
        day = self.add_day(1, {"T-0001": (1.0, ["HN"], 3)})
        db.save_run(self.conn, day_of(2), "hackernews", item_count=0, followed_count=0, status="empty", memo="",
                    started_at="x", duration_sec=0)
        self.assertEqual(score.run_days(self.conn, day_of(2)), [day])

    def test_rerun_replaces_the_days_scores(self):
        day = self.add_day(1, {"T-0001": (2.0, ["HN"], 3)})
        score.compute(self.conn, day, SETTINGS)
        score.compute(self.conn, day, SETTINGS)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM topic_score").fetchone()[0], 1)

    def test_explore_picks_skip_the_top_and_are_stable_for_the_day(self):
        day = self.add_day(1, {f"T-{i:04d}": (100.0 - i, ["HN"], 3) for i in range(1, 41)})
        score.compute(self.conn, day, SETTINGS)
        picks = score.explore_picks(self.conn, day, SETTINGS, exclude={"T-0030"})
        self.assertEqual(len(picks), 5)
        self.assertTrue(all(int(p[2:]) > 20 for p in picks))
        self.assertNotIn("T-0030", picks)
        self.assertEqual(picks, score.explore_picks(self.conn, day, SETTINGS, exclude={"T-0030"}))

    def test_constants_live_in_the_settings_file(self):
        for name, value in {"z_cap": 8, "accel_weight": 1.5, "breadth_weight": 0.5, "threshold": 5.0,
                            "min_origins": 3, "baseline_days": 14, "baseline_max_days": 28, "z_floor": 0.8}.items():
            self.assertEqual(CFG[name], value, name)


if __name__ == "__main__":
    unittest.main()
