import unittest
from pathlib import Path

from trendfeed.sources import github_trending as gh

FIXTURES = Path(__file__).parent / "fixtures"
SAMPLE = (FIXTURES / "github_trending_sample.html").read_text(encoding="utf-8")
REAL_SHAPE = (FIXTURES / "github_trending_real_shape.html").read_text(encoding="utf-8")


class ParseTest(unittest.TestCase):
    def test_reads_each_repo_in_page_order(self):
        repos = gh.parse(SAMPLE)
        self.assertEqual([r["repo"] for r in repos], ["acme/rocket", "Solo-Dev/notes.app"])

    def test_reads_numbers_description_language(self):
        first, second = gh.parse(SAMPLE)
        self.assertEqual(first["stars"], 12345)
        self.assertEqual(first["forks"], 678)
        self.assertEqual(first["period_stars"], 1234)
        self.assertEqual(first["language"], "Rust")
        self.assertEqual(first["description"], "A tiny 🚀 launcher & toolkit, see docs")
        # 설명·언어가 없는 저장소, "1 star today" 단수 표기
        self.assertEqual(second["stars"], 987)
        self.assertEqual(second["period_stars"], 1)
        self.assertIsNone(second["description"])
        self.assertIsNone(second["language"])

    def test_page_without_repos_gives_nothing(self):
        self.assertEqual(gh.parse("<html><body><h1>Sign in</h1></body></html>"), [])


class RealShapeTest(unittest.TestCase):
    """실제 페이지에서 뽑은 뼈대. 로그인 화면의 숨은 안내창(제목·문단)이 저장소 칸 안에 섞여 있다."""

    def test_reads_real_page_structure(self):
        repos = gh.parse(REAL_SHAPE)
        self.assertEqual(
            [(r["repo"], r["stars"], r["forks"], r["period_stars"], r["language"]) for r in repos],
            [
                ("ag-ui-protocol/ag-ui", 18406, 1894, 790, "TypeScript"),
                ("backnotprop/plannotator", 12238, 1148, 689, "TypeScript"),
                ("dream-num/univer", 27481, 2507, 1878, "TypeScript"),
            ],
        )

    def test_description_is_the_repo_text_not_a_hidden_dialog(self):
        first = gh.parse(REAL_SHAPE)[0]
        self.assertEqual(
            first["description"],
            "AG-UI: the Agent-User Interaction Protocol. Bring Agents into Frontend Applications.",
        )


class RealPageTest(unittest.TestCase):
    """실제 페이지를 저장한 파일(tests/fixtures/real/*.html)이 있으면 그것으로도 확인한다.

    로그인한 채 저장한 페이지에는 계정 정보가 들어 있어 이 폴더는 git에 올리지 않는다.
    """

    def test_saved_real_pages(self):
        pages = sorted((FIXTURES / "real").glob("*.html"))
        if not pages:
            self.skipTest("저장해 둔 실제 페이지가 없음")
        for page in pages:
            with self.subTest(page=page.name):
                repos = gh.parse(page.read_text(encoding="utf-8", errors="replace"))
                self.assertGreaterEqual(len(repos), 5)
                for r in repos:
                    self.assertRegex(r["repo"], r"^[^/\s]+/[^/\s]+$")
                    self.assertIsNotNone(r["stars"], r["repo"])
                    self.assertIsNotNone(r["forks"], r["repo"])
                    self.assertNotIn("{{", r["description"] or "", r["repo"])
                with_period = [r for r in repos if r["period_stars"] is not None]
                self.assertGreaterEqual(len(with_period), len(repos) // 2)


class MergeTest(unittest.TestCase):
    def test_repo_on_both_lists_becomes_one_item_with_both_numbers(self):
        daily = [
            {"repo": "a/x", "description": "d", "language": "Go", "stars": 100, "forks": 5, "period_stars": 10},
            {"repo": "b/y", "description": None, "language": None, "stars": 50, "forks": 1, "period_stars": 7},
        ]
        weekly = [
            {"repo": "c/z", "description": None, "language": None, "stars": 900, "forks": 9, "period_stars": 300},
            {"repo": "a/x", "description": "d", "language": "Go", "stars": 100, "forks": 5, "period_stars": 60},
        ]
        records = gh.merge({"daily": daily, "weekly": weekly})
        self.assertEqual([r.external_id for r in records], ["a/x", "b/y", "c/z"])
        self.assertEqual([r.rank for r in records], [1, 2, 3])
        ax = records[0]
        self.assertEqual(ax.metrics, {"stars": 100})
        self.assertEqual(
            ax.snap_extra,
            {"forks": 5, "rank_daily": 1, "stars_daily": 10, "rank_weekly": 2, "stars_weekly": 60},
        )
        self.assertEqual(ax.origin, "github.com/a")
        self.assertEqual(ax.url, "https://github.com/a/x")
        self.assertEqual(records[2].snap_extra, {"forks": 9, "rank_weekly": 1, "stars_weekly": 300})


class CollectTest(unittest.TestCase):
    CFG = {"base_url": "https://example.invalid/trending", "periods": ["daily", "weekly"], "pause_sec": 0}

    def test_one_period_failing_keeps_the_other_and_reports_it(self):
        class Fetch:
            def get_text(self, url):
                if "weekly" in url:
                    raise TimeoutError()
                return SAMPLE

        result = gh.collect(self.CFG, Fetch())
        self.assertEqual(len(result.records), 2)
        self.assertEqual(result.problems, ["weekly 목록을 받지 못함 (TimeoutError)"])

    def test_changed_page_layout_is_reported_not_silent(self):
        class Fetch:
            def get_text(self, url):
                return "<html><body>nothing here</body></html>"

        result = gh.collect(self.CFG, Fetch())
        self.assertEqual(result.records, [])
        self.assertEqual(len(result.problems), 2)
        self.assertIn("화면 구조", result.problems[0])


if __name__ == "__main__":
    unittest.main()
