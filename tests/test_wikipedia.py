import unittest
import urllib.error
from datetime import date
from unittest import mock

from trendfeed.sources import wikipedia as wk

CFG = {"api_base": "https://example.invalid/top", "project": "ko.wikipedia", "limit": 3,
       "lookback_days": 3, "pause_sec": 0}
ARTICLES = [
    {"article": "위키백과:대문", "views": 46683, "rank": 1},
    {"article": "문화방송", "views": 14514, "rank": 2},
    {"article": "특수:검색", "views": 9688, "rank": 4},
    {"article": "이진희_(배우)", "views": 6331, "rank": 9},
    {"article": "Main_Page", "views": 5000, "rank": 10},
    {"article": "2001:_스페이스_오디세이", "views": 4000, "rank": 11},
    {"article": "넘치는_문서", "views": 3000, "rank": 12},
]


class Fetch:
    def __init__(self, missing=(), broken=False):
        self.missing, self.broken, self.urls = set(missing), broken, []

    def get_json(self, url):
        self.urls.append(url)
        if self.broken:
            raise urllib.error.HTTPError(url, 429, "Too Many Requests", None, None)
        if url.rsplit("all-access/", 1)[1] in self.missing:
            raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
        return {"items": [{"articles": ARTICLES}]}


@mock.patch.object(wk, "_utc_today", lambda: date(2026, 11, 16))
class WikipediaTest(unittest.TestCase):
    def test_takes_top_articles_skipping_non_article_pages(self):
        fetch = Fetch()
        result = wk.collect(CFG, fetch)
        self.assertEqual(fetch.urls, ["https://example.invalid/top/ko.wikipedia/all-access/2026/11/15"])
        self.assertEqual(
            [(r.external_id, r.rank, r.metrics["views"]) for r in result.records],
            [("문화방송", 1, 14514), ("이진희_(배우)", 2, 6331), ("2001:_스페이스_오디세이", 3, 4000)],
        )
        first = result.records[1]
        self.assertEqual(first.title, "이진희 (배우)")
        self.assertEqual(first.url, "https://ko.wikipedia.org/wiki/%EC%9D%B4%EC%A7%84%ED%9D%AC_%28%EB%B0%B0%EC%9A%B0%29")
        self.assertEqual(first.origin, "ko.wikipedia.org")
        self.assertEqual(first.snap_extra, {"views_date": "2026-11-15"})
        self.assertEqual(result.problems, [])

    def test_falls_back_a_day_when_yesterday_is_not_published_yet(self):
        fetch = Fetch(missing=["2026/11/15"])
        result = wk.collect(CFG, fetch)
        self.assertEqual(len(fetch.urls), 2)
        self.assertEqual(result.records[0].snap_extra, {"views_date": "2026-11-14"})
        self.assertEqual(result.problems, ["어제 치가 아직 없어 11/14 조회수를 씀"])

    def test_gives_up_after_lookback_days(self):
        fetch = Fetch(missing=["2026/11/15", "2026/11/14", "2026/11/13"])
        result = wk.collect(CFG, fetch)
        self.assertEqual((result.records, len(fetch.urls)), ([], 3))
        self.assertEqual(result.problems, ["최근 3일 치 조회수가 아직 나오지 않음"])

    def test_other_errors_are_not_swallowed(self):
        with self.assertRaises(urllib.error.HTTPError):
            wk.collect(CFG, Fetch(broken=True))


if __name__ == "__main__":
    unittest.main()
