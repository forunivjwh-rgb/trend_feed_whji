"""탐색 슬롯(명세 2번): 수집의 약 20%를 목록 밖에서 무작위로 뽑는다. 탐색 글은 순위와 따로 센다."""

import random
import unittest
from datetime import date
from unittest import mock

from trendfeed import config, db, rank, score
from trendfeed.run import collect_all
from trendfeed.sources import github_trending, huggingface, wikipedia
from tests.test_feed import make_topics
from tests.test_hackernews import FakeFetch, story
from tests.test_run import SAMPLE

SETTINGS = config.load()
DAY = "2026-11-17"


class HNFetch(FakeFetch):
    """인기글 1~10, 최신 글 101~130."""

    def __init__(self):
        super().__init__(list(range(1, 11)), {i: story(i) for i in list(range(1, 11)) + list(range(101, 131))})

    def get_json(self, url, headers=None):
        if url.endswith("/newstories.json"):
            return list(range(101, 131)) + [1, 2]  # 인기글에도 있는 1, 2 는 탐색에서 빠져야 한다
        return super().get_json(url)


def hn_settings(share=0.2):
    return {"explore": {"enabled": True, "share": share},
            "sources": {"hackernews": {**SETTINGS["sources"]["hackernews"], "api_base": "https://x.invalid/v0",
                                       "limit": 8, "follow_days": 2}},
            "attention": SETTINGS["attention"]}


class CollectExploreTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)

    def test_about_twenty_percent_from_outside_the_list_and_stable_for_the_day(self):
        out = collect_all(hn_settings(), self.conn, DAY, fetch=HNFetch())[0]
        self.assertEqual((out["item_count"], out["explore_count"]), (8, 2))  # 8 × 0.2 ÷ 0.8 = 2
        rows = self.conn.execute(
            "SELECT i.external_id FROM item_snapshots s JOIN items i ON i.id = s.item_id "
            "WHERE json_extract(s.extra, '$.explore') = 1").fetchall()
        explored = sorted(int(r[0]) for r in rows)
        self.assertTrue(all(101 <= x <= 130 for x in explored))
        again = db.connect(":memory:")
        self.addCleanup(again.close)
        collect_all(hn_settings(), again, DAY, fetch=HNFetch())
        rows2 = again.execute("SELECT i.external_id FROM item_snapshots s JOIN items i ON i.id = s.item_id "
                              "WHERE json_extract(s.extra, '$.explore') = 1").fetchall()
        self.assertEqual(sorted(int(r[0]) for r in rows2), explored)  # 같은 날 = 같은 뽑기

    def test_explore_items_stay_out_of_ranking_and_follow_ups(self):
        collect_all(hn_settings(), self.conn, DAY, fetch=HNFetch())
        main = rank.now_popular(self.conn, DAY, hn_settings())
        explored = rank.now_popular(self.conn, DAY, hn_settings(), explore=True)
        self.assertEqual((len(main), len(explored)), (8, 2))
        self.assertTrue(all(not e["explore"] for e in main) and all(e["explore"] for e in explored))
        self.assertEqual(explored[0]["typical"], main[0]["typical"])  # 보통 값은 목록 글로만 잰다
        ids = db.recently_listed(self.conn, "2026-11-18", "hackernews", 2)
        self.assertEqual(sorted(int(i) for i in ids), list(range(1, 9)))  # 탐색 글은 다음 날 다시 적지 않는다

    def test_off_means_no_explore(self):
        out = collect_all(hn_settings() | {"explore": {"enabled": False, "share": 0.2}}, self.conn, DAY,
                          fetch=HNFetch())[0]
        self.assertEqual(out["explore_count"], 0)

    def test_explore_failure_is_a_note_not_a_warning(self):
        class Broken(HNFetch):
            def get_json(self, url, headers=None):
                if url.endswith("/newstories.json"):
                    raise TimeoutError()
                return super().get_json(url)

        out = collect_all(hn_settings(), self.conn, DAY, fetch=Broken())[0]
        self.assertEqual(out["status"], "ok")
        self.assertIn("탐색 실패 (TimeoutError)", out["memo"])


class SourceExploreTest(unittest.TestCase):
    rng = staticmethod(lambda: random.Random("seed"))

    def test_github_picks_from_a_random_language_page(self):
        urls = []

        class Fetch:
            def get_text(self, url, headers=None):
                urls.append(url)
                return SAMPLE

        cfg = {**SETTINGS["sources"]["github_trending"], "base_url": "https://x.invalid/trending"}
        result = github_trending.explore(cfg, Fetch(), self.rng(), 1, exclude={"acme/rocket"})
        self.assertRegex(urls[0], r"^https://x.invalid/trending/[^?]+\?since=daily$")
        self.assertEqual([r.external_id for r in result.records], ["Solo-Dev/notes.app"])
        self.assertIsNone(result.records[0].rank)
        self.assertIn("trending", result.records[0].item_extra["explore_from"])

    def test_huggingface_picks_beyond_the_top_list(self):
        class Fetch:
            def get_json(self, url, headers=None):
                assert "limit=200" in url
                return [{"id": f"o/m{i}", "likes": i} for i in range(200)]

        result = huggingface.explore(SETTINGS["sources"]["huggingface"], Fetch(), self.rng(), 5, exclude=set())
        self.assertEqual(len(result.records), 5)
        self.assertTrue(all(int(r.external_id[3:]) >= 40 for r in result.records))  # 위 40개 밖

    def test_wikipedia_picks_beyond_rank_100(self):
        articles = [{"article": f"문서_{i}", "views": 10000 - i, "rank": i} for i in range(1, 1001)]

        class Fetch:
            def get_json(self, url, headers=None):
                return {"items": [{"articles": articles}]}

        cfg = {**SETTINGS["sources"]["wikipedia_ko"], "pause_sec": 0}
        with mock.patch.object(wikipedia, "_utc_today", lambda: date(2026, 11, 17)):
            result = wikipedia.explore(cfg, Fetch(), self.rng(), 25, exclude=set())
        self.assertEqual(len(result.records), 25)
        self.assertTrue(all(int(r.external_id.split("_")[1]) > 100 for r in result.records))


class ExploreTopicsTest(unittest.TestCase):
    def test_explore_topics_feed_the_slot_and_never_get_a_rank(self):
        conn = db.connect(":memory:")
        self.addCleanup(conn.close)
        collect_all(hn_settings(), conn, DAY, fetch=HNFetch())
        db.save_run(conn, DAY, "hackernews", item_count=8, followed_count=0, status="ok", memo="",
                    started_at=DAY + "T19:00:00+00:00", duration_sec=1)
        step = make_topics(conn, DAY, {**SETTINGS, "sources": {**SETTINGS["sources"], **hn_settings()["sources"]}})
        self.assertEqual(step["score"]["explore"], 2)
        rows = conn.execute("SELECT topic_code, rank, explore FROM topic_score WHERE date = ?", (DAY,)).fetchall()
        explore_codes = {r[0] for r in rows if r[2]}
        self.assertEqual(len(explore_codes), 2)
        self.assertTrue(all(r[1] is None for r in rows if r[2]))  # 탐색 주제는 순위가 없다
        picks = score.explore_picks(conn, DAY, SETTINGS, exclude=set())
        self.assertEqual(set(picks), explore_codes)


if __name__ == "__main__":
    unittest.main()
