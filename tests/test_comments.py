"""유튜브 댓글에서 반복되는 말 세기. 원문은 어디에도 남지 않아야 한다(가짜 응답 사용)."""

import json
import unittest

from trendfeed import archive, config, db, phrases
from trendfeed.run import collect_all
from trendfeed.sources import youtube as yt
from tests.test_youtube import KEY, api_error, video, with_key

OPTS = dict(max_words=3, min_comments=3, top=5, min_chars=3)
CFG = {"enabled": True, "api_base": "https://example.invalid/youtube/v3", "regions": ["KR"], "limit": 3,
       "comments_per_video": 20, "comment_workers": 2, "phrase_min_comments": 3, "phrase_max_words": 3,
       "phrase_min_chars": 3, "phrase_top": 5}
SECRET_WORDS = "아무도모르는비밀원문"


class RepeatedTest(unittest.TestCase):
    def test_counts_distinct_comments_not_repeats_inside_one(self):
        comments = ["L을 가져가 L을 가져가 L을 가져가", "와 L을 가져가 ㅋㅋ", "L을 가져가!!", "노래 좋다"]
        self.assertEqual(phrases.repeated(comments, **OPTS), [{"text": "l을 가져가", "count": 3}])

    def test_nothing_repeats_enough(self):
        self.assertEqual(phrases.repeated(["하나", "둘 셋", "넷 다섯 여섯"], **OPTS), [])

    def test_short_noise_is_ignored_and_order_is_by_count(self):
        comments = ["ㅋㅋ 스카프 아저씨", "ㅋㅋ 스카프 아저씨 최고", "ㅋㅋ 남대문 스카프 아저씨", "ㅋㅋ 최고", "최고 ㅋㅋ"]
        found = phrases.repeated(comments, **OPTS)
        self.assertEqual(found[0], {"text": "스카프 아저씨", "count": 3})
        self.assertNotIn("ㅋㅋ", [f["text"] for f in found])


class Fetch:
    def __init__(self, comments_by_video, error_for=None):
        self.comments, self.error_for, self.calls = comments_by_video, error_for or {}, []

    def get_json(self, url, headers=None):
        self.calls.append(url)
        if "/commentThreads" in url:
            vid = url.split("videoId=")[1].split("&")[0]
            if vid in self.error_for:
                raise self.error_for[vid]
            return {"items": [{"snippet": {"topLevelComment": {"snippet": {"textOriginal": t}}}}
                              for t in self.comments.get(vid, [])]}
        return {"items": [video(1), video(2), video(3)]}


class YoutubeCommentsTest(unittest.TestCase):
    def collect(self, fetch):
        with with_key():
            return yt.collect(CFG, fetch)

    def test_phrases_are_attached_and_raw_text_is_not(self):
        fetch = Fetch({"vid1": [f"{SECRET_WORDS} 스카프 아저씨", "스카프 아저씨 봤다", "나도 스카프 아저씨"], "vid2": ["그냥 댓글"]})
        result = self.collect(fetch)
        by_id = {r.external_id: r for r in result.records}
        self.assertEqual(by_id["vid1"].snap_extra["comment_phrases"], [{"text": "스카프 아저씨", "count": 3}])
        self.assertEqual(by_id["vid1"].snap_extra["comments_read"], 3)
        self.assertNotIn("comment_phrases", by_id["vid2"].snap_extra)
        self.assertNotIn(SECRET_WORDS, json.dumps([r.__dict__ for r in result.records], ensure_ascii=False))
        asked = [u for u in fetch.calls if "/commentThreads" in u]
        self.assertEqual(len(asked), 3)
        self.assertTrue(all("order=relevance" in u and "maxResults=20" in u and KEY not in u for u in asked))

    def test_video_with_comments_turned_off_is_skipped_quietly(self):
        fetch = Fetch({"vid2": ["a b c"]}, error_for={"vid1": api_error(403, "commentsDisabled")})
        result = self.collect(fetch)
        self.assertEqual(result.problems, [])
        self.assertNotIn("comments_read", result.records[0].snap_extra)
        self.assertEqual(result.records[1].snap_extra["comments_read"], 1)

    def test_running_out_of_quota_keeps_the_videos_and_says_so(self):
        fetch = Fetch({}, error_for={f"vid{i}": api_error(403, "quotaExceeded") for i in (1, 2, 3)})
        result = self.collect(fetch)
        self.assertEqual(len(result.records), 3)
        self.assertEqual(len(result.problems), 1)
        self.assertIn("댓글 읽기를 멈춤", result.problems[0])

    def test_zero_turns_comment_reading_off(self):
        fetch = Fetch({"vid1": ["a"]})
        with with_key():
            yt.collect({**CFG, "comments_per_video": 0}, fetch)
        self.assertFalse(any("/commentThreads" in u for u in fetch.calls))

    def test_nothing_raw_reaches_the_database_or_the_day_file(self):
        import tempfile
        from pathlib import Path

        conn = db.connect(":memory:")
        self.addCleanup(conn.close)
        fetch = Fetch({"vid1": [f"{SECRET_WORDS} 스카프 아저씨", "스카프 아저씨 봤다", "나도 스카프 아저씨"]})
        with with_key():
            collect_all({"sources": {"youtube": CFG}}, conn, "2026-11-16", fetch=fetch)
        dumped = "\n".join(conn.iterdump())
        self.assertIn("스카프 아저씨", dumped)
        self.assertNotIn(SECRET_WORDS, dumped)
        with tempfile.TemporaryDirectory() as tmp:
            text = archive.export_day(conn, "2026-11-16", Path(tmp)).read_text(encoding="utf-8")
        self.assertNotIn(SECRET_WORDS, text)

    def test_shipped_settings_have_the_comment_options(self):
        cfg = config.load()["sources"]["youtube"]
        self.assertEqual(cfg["comments_per_video"], 20)
        for name in ("comment_workers", "phrase_min_comments", "phrase_max_words", "phrase_min_chars", "phrase_top"):
            self.assertIn(name, cfg)


if __name__ == "__main__":
    unittest.main()
