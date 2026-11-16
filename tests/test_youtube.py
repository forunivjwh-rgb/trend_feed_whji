"""유튜브 수집: 키가 없으면 건너뛰고, 키는 주소·기록 어디에도 남지 않아야 한다(가짜 응답 사용)."""

import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

from trendfeed import config, db
from trendfeed.run import collect_all
from trendfeed.sources import SourceProblem
from trendfeed.sources import youtube as yt

CFG = {"enabled": True, "api_base": "https://example.invalid/youtube/v3", "regions": ["KR"], "limit": 5, "follow_days": 2}
KEY = "TEST-KEY-do-not-leak"


def video(i, **stats):
    statistics = {"viewCount": str(i * 1000), "likeCount": str(i * 10), "commentCount": str(i)}
    statistics.update(stats)
    return {
        "id": f"vid{i}",
        "snippet": {"title": f"Video {i}", "channelId": f"UC{i}", "channelTitle": f"Channel {i}",
                    "categoryId": "10", "publishedAt": "2026-11-15T09:00:00Z"},
        "statistics": {k: v for k, v in statistics.items() if v is not None},
    }


def api_error(code, reason, in_details=False):
    error = {"code": code, "message": "nope", "errors": [] if in_details else [{"reason": reason}]}
    if in_details:
        error["details"] = [{"reason": reason}]
    body = json.dumps({"error": error}).encode()
    return urllib.error.HTTPError("https://example.invalid", code, "err", None, io.BytesIO(body))


class Fetch:
    """차트를 3개씩 두 쪽으로 나눠 주는 가짜 API."""

    def __init__(self, error=None):
        self.calls, self.error = [], error

    def get_json(self, url, headers=None):
        self.calls.append((url, headers))
        if self.error:
            raise self.error
        if "id=" in url:
            ids = url.split("id=")[1].split("&")[0].split("%2C")
            return {"items": [video(int(i.removeprefix("vid"))) for i in ids if i != "vid404"]}
        if "pageToken=P2" in url:
            return {"items": [video(4), video(5), video(6)]}
        return {"items": [video(1), video(2), video(3)], "nextPageToken": "P2"}


def with_key(value=KEY):
    return mock.patch.object(config, "secret", lambda name: value if name == "YOUTUBE_API_KEY" else None)


class CollectTest(unittest.TestCase):
    def test_without_a_key_it_says_so_and_calls_nothing(self):
        fetch = Fetch()
        with with_key(None), self.assertRaises(SourceProblem) as ctx:
            yt.collect(CFG, fetch)
        self.assertIn("API 키 없음", str(ctx.exception))
        self.assertEqual(fetch.calls, [])

    def test_pages_through_the_chart_up_to_the_limit(self):
        fetch = Fetch()
        with with_key():
            result = yt.collect(CFG, fetch)
        self.assertEqual([(r.external_id, r.rank) for r in result.records],
                         [("vid1", 1), ("vid2", 2), ("vid3", 3), ("vid4", 4), ("vid5", 5)])
        self.assertEqual(len(fetch.calls), 2)
        first_url = fetch.calls[0][0]
        self.assertIn("chart=mostPopular", first_url)
        self.assertIn("regionCode=KR", first_url)

    def test_key_travels_in_a_header_never_in_the_address(self):
        fetch = Fetch()
        with with_key():
            yt.collect(CFG, fetch)
        for url, headers in fetch.calls:
            self.assertNotIn(KEY, url)
            self.assertEqual(headers, {"X-Goog-Api-Key": KEY})

    def test_maps_fields_and_tolerates_hidden_counts(self):
        r = yt.to_record(video(7, likeCount=None, commentCount=None), rank=1, listed=True, region="KR")
        self.assertEqual(r.external_id, "vid7")
        self.assertEqual(r.url, "https://www.youtube.com/watch?v=vid7")
        self.assertEqual(r.origin, "youtube.com/channel/UC7")
        self.assertEqual(r.published_at, "2026-11-15T09:00:00+00:00")
        self.assertEqual(r.metrics, {"views": 7000})
        self.assertEqual(r.item_extra, {"channel_title": "Channel 7", "category_id": "10"})
        self.assertEqual(r.snap_extra, {"region": "KR"})

    def test_refusals_are_explained_without_leaking_anything(self):
        cases = [
            (api_error(400, "API_KEY_INVALID", in_details=True), "API 키가 올바르지 않음"),
            (api_error(403, "quotaExceeded"), "요청 한도를 넘김"),
            (api_error(403, "accessNotConfigured"), "YouTube Data API v3 가 켜져 있지 않음"),
            (api_error(500, "somethingElse"), "유튜브가 요청을 거절함 (HTTP 500)"),
        ]
        for error, expected in cases:
            with self.subTest(expected=expected), with_key(), self.assertRaises(SourceProblem) as ctx:
                yt.collect(CFG, Fetch(error=error))
            self.assertIn(expected, str(ctx.exception))
            self.assertNotIn(KEY, str(ctx.exception))

    def test_refetch_asks_in_batches_and_marks_not_listed(self):
        fetch = Fetch()
        with with_key():
            result = yt.refetch(CFG, fetch, [f"vid{i}" for i in range(1, 61)] + ["vid404"])
        self.assertEqual(len(fetch.calls), 2)  # 50개 + 11개
        self.assertEqual(len(result.records), 60)  # 지워진 영상은 응답에 없다
        self.assertTrue(all(not r.listed and r.rank is None for r in result.records))


class SkipWithoutKeyTest(unittest.TestCase):
    """키가 없으면 유튜브만 '입력 없음'으로 남고 다른 소스는 정상으로 돈다."""

    def test_other_sources_run_normally(self):
        from tests.test_hackernews import FakeFetch, story

        settings = {"sources": {
            "youtube": CFG,
            "hackernews": {"enabled": True, "api_base": "https://example.invalid/v0", "limit": 2, "workers": 2},
        }}
        conn = db.connect(":memory:")
        self.addCleanup(conn.close)
        with with_key(None):
            out = {s["source"]: s for s in collect_all(settings, conn, "2026-11-16",
                                                         fetch=FakeFetch([1, 2], {1: story(1), 2: story(2)}))}
        self.assertEqual((out["hackernews"]["status"], out["hackernews"]["item_count"]), ("ok", 2))
        self.assertEqual((out["youtube"]["status"], out["youtube"]["item_count"]), ("empty", 0))
        self.assertEqual(out["youtube"]["memo"], "API 키 없음 — .env 파일에 YOUTUBE_API_KEY 를 넣으면 켜집니다")


class EnvFileTest(unittest.TestCase):
    def read(self, text, encoding="utf-8"):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ".env"
            path.write_text(text, encoding=encoding)
            with mock.patch.object(config, "ENV_PATH", path):
                return config.secret("YOUTUBE_API_KEY")

    def test_reads_plain_quoted_and_notepad_saved_files(self):
        self.assertEqual(self.read("# 설명\nOTHER=1\nYOUTUBE_API_KEY=abc123\n"), "abc123")
        self.assertEqual(self.read('YOUTUBE_API_KEY = "abc123" \n'), "abc123")
        self.assertEqual(self.read("YOUTUBE_API_KEY=abc123\r\n", encoding="utf-8-sig"), "abc123")

    def test_blank_or_missing_means_no_key(self):
        self.assertIsNone(self.read("YOUTUBE_API_KEY=\n"))
        self.assertIsNone(self.read("OTHER=1\n"))
        with mock.patch.object(config, "ENV_PATH", Path("/nonexistent/.env")):
            self.assertIsNone(config.secret("YOUTUBE_API_KEY"))


if __name__ == "__main__":
    unittest.main()
