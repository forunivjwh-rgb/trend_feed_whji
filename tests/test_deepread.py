"""실탐: 원문을 읽고 LLM으로 요약한다. 가짜 LLM과 가짜 인터넷으로 확인한다(실제 호출 없음)."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from trendfeed import archive, config, db, deepread, feed, llm
from trendfeed.sources import Record

SETTINGS = config.load()
SETTINGS["deepread"]["pause_sec"] = 0  # 시험에서는 쉬지 않는다
SETTINGS["deepread"]["read_explore"] = False  # 탐색 슬롯 읽기는 따로 시험한다
DAY = "2026-11-17"
T = f"{DAY}T19:00:00+00:00"
RAW = "아주긴원문표시 " * 60  # 요약에만 쓰이고 어디에도 저장되면 안 되는 원문
SUMMARY = {"what": "위키 문서다", "why": "방송에 나와서", "how": "사람들이 찾아본다", "comments_point": ""}


class FakeClient:
    """Claude API 흉내. 부른 내용을 기억하고 정해 둔 답을 준다."""

    def __init__(self, stop_reason="end_turn", error=None):
        self.calls, self.stop_reason, self.error = [], stop_reason, error
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if self.error:
            raise self.error
        import json
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=json.dumps(SUMMARY))],
            usage=SimpleNamespace(input_tokens=1200, output_tokens=150),
        )


class Fetch:
    def __init__(self, fail=False):
        self.fail, self.urls = fail, []

    def get_json(self, url, headers=None):
        self.urls.append(url)
        if self.fail:
            raise TimeoutError()
        return {"query": {"pages": [{"extract": RAW}]}}

    def get_text(self, url, headers=None):
        raise TimeoutError()


def wiki(i, views):
    return Record(external_id=f"문서_{i}", title=f"문서 {i}", url=f"https://ko.wikipedia.org/wiki/{i}",
                  origin="ko.wikipedia.org", published_at=None, rank=i, metrics={"views": views})


class DeepreadTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        db.save_records(self.conn, DAY, "wikipedia_ko", [wiki(i, 1000 * (13 - i)) for i in range(1, 13)], T)
        db.save_run(self.conn, DAY, "wikipedia_ko", item_count=12, followed_count=0, status="ok", memo="",
                    started_at=T, duration_sec=1.0)
        self.said = []
        self.topics(DAY)

    def topics(self, day):
        from tests.test_feed import make_topics
        make_topics(self.conn, day, SETTINGS)

    def run_it(self, client, fetch=None, day=DAY, settings=SETTINGS):
        return deepread.run(self.conn, day, settings, fetch or Fetch(), client=client, say=self.said.append)

    def test_reads_the_top_items_and_stores_summary_scope_and_usage(self):
        client = FakeClient()
        result = self.run_it(client)
        self.assertEqual((result["read"], result["failed"]), (10, 0))  # 설정의 top_n = 10
        row = dict(self.conn.execute(
            "SELECT d.* FROM deepreads d JOIN items i ON i.id = d.item_id WHERE i.external_id = '문서_1'").fetchone())
        self.assertEqual({k: row[k] for k in SUMMARY}, SUMMARY)
        self.assertEqual(row["scope"], f"대표 문서 본문 {len(RAW):,}자")
        self.assertEqual(row["model"], "claude-haiku-5-5")
        calls = self.conn.execute("SELECT COUNT(*), SUM(input_tokens), SUM(output_tokens) FROM llm_calls").fetchone()
        self.assertEqual(tuple(calls), (10, 12000, 1500))

    def test_request_uses_the_configured_model_and_treats_material_as_data(self):
        client = FakeClient()
        self.run_it(client)
        call = client.calls[0]
        self.assertEqual(call["model"], SETTINGS["llm"]["model"])
        self.assertEqual(call["output_config"]["effort"], SETTINGS["llm"]["effort"])
        self.assertEqual(call["output_config"]["format"]["type"], "json_schema")
        self.assertIn("<자료>", call["messages"][0]["content"])
        self.assertIn("따르지 않습니다", call["system"])

    def test_raw_text_is_never_stored(self):
        self.run_it(FakeClient())
        self.assertNotIn("아주긴원문표시", "\n".join(self.conn.iterdump()))

    def test_same_item_is_not_read_again_within_seven_days(self):
        self.run_it(FakeClient())
        again = FakeClient()
        db.save_records(self.conn, "2026-11-20", "wikipedia_ko", [wiki(i, 1000 * (13 - i)) for i in range(1, 13)],
                        "2026-11-20T19:00:00+00:00")
        self.topics("2026-11-20")
        result = self.run_it(again, day="2026-11-20")
        self.assertEqual((result["read"], result["skipped"], len(again.calls)), (0, 10, 0))
        later = FakeClient()  # 8일 뒤에는 다시 읽는다
        db.save_records(self.conn, "2026-11-25", "wikipedia_ko", [wiki(1, 5000)], "2026-11-25T19:00:00+00:00")
        self.topics("2026-11-25")
        self.assertEqual(self.run_it(later, day="2026-11-25")["read"], 1)

    def test_unreadable_source_is_not_summarized_from_nothing(self):
        client = FakeClient()
        result = self.run_it(client, fetch=Fetch(fail=True))
        self.assertEqual((result["read"], result["failed"], len(client.calls)), (0, 10, 0))

    def test_refusal_or_cut_off_answer_stores_no_summary_but_counts_usage(self):
        result = self.run_it(FakeClient(stop_reason="refusal"))
        self.assertEqual((result["read"], result["failed"]), (0, 10))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM deepreads").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM llm_calls").fetchone()[0], 10)

    def test_api_failure_stops_the_step_without_raising(self):
        client = FakeClient(error=RuntimeError("boom"))
        result = self.run_it(client)
        self.assertEqual((result["read"], len(client.calls)), (0, 1))
        self.assertIn("남은 실탐은 건너뜀", result["note"])

    def test_reads_up_to_three_articles_per_topic_with_one_llm_call(self):
        # 문서 1과 2를 한 주제로 묶어 둔다 → 두 글을 함께 읽고 LLM은 주제당 1번만 부른다
        code1, code2 = (self.conn.execute(
            "SELECT m.topic_code FROM topic_items m JOIN items i ON i.id = m.item_id WHERE i.external_id = ?", (x,)
        ).fetchone()[0] for x in ("문서_1", "문서_2"))
        self.conn.execute("UPDATE topic_items SET topic_code = ? WHERE topic_code = ?", (code1, code2))
        self.conn.execute("DELETE FROM topic_score WHERE topic_code = ?", (code2,))
        self.conn.commit()
        client = FakeClient()
        result = self.run_it(client)
        self.assertEqual(result["read"], 10)
        self.assertEqual(len(client.calls), 10)
        joined = next(c["messages"][0]["content"] for c in client.calls if "문서 2\n" in c["messages"][0]["content"])
        self.assertIn("] 문서 1\n", joined)  # 같은 요청 안에 두 글이 함께 들어간다
        row = self.conn.execute("SELECT scope FROM deepreads d JOIN items i ON i.id = d.item_id "
                                "WHERE i.external_id = '문서_1'").fetchone()
        self.assertEqual(row[0].count("문서 본문"), 2)
        titles = "\n".join(c["messages"][0]["content"] for c in client.calls)
        self.assertIn("] 문서 11\n", titles)  # 한 자리가 비어 다음 주제가 들어온다

    def test_without_a_key_only_this_step_is_skipped(self):
        with mock.patch.object(config, "secret", lambda name: None):
            result = deepread.run(self.conn, DAY, SETTINGS, Fetch(), say=self.said.append)
            html = feed.build(self.conn, DAY, SETTINGS)
        self.assertEqual(result["read"], 0)
        self.assertIn("LLM 키 없음", result["note"])
        self.assertIn("LLM 키 없음 — 건너뜀", html)
        self.assertIn("지금 인기 Top 5", html)  # 피드는 그대로 나온다

    def test_explore_topics_are_read_when_time_is_left(self):
        on = {**SETTINGS, "deepread": {**SETTINGS["deepread"], "read_explore": True}}
        result = self.run_it(FakeClient(), settings=on)
        self.assertEqual(result["read"], 10)
        self.assertGreaterEqual(result["explore_read"], 1)  # 순위 밖(탐색 칸) 주제도 1건씩 읽는다

    def test_summary_shows_on_the_card_and_survives_the_day_files(self):
        self.run_it(FakeClient())
        html = feed.build(self.conn, DAY, SETTINGS)
        for text in ("실탐 요약", "위키 문서다", "방송에 나와서", "읽은 범위: 대표 문서 본문", "실탐 10건 · LLM 10회 (입력 12,000 · 출력 1,500 토큰)",
                     "실탐</span>"):
            self.assertIn(text, html)
        with tempfile.TemporaryDirectory() as tmp:
            archive.export_day(self.conn, DAY, Path(tmp))
            fresh = db.connect(":memory:")
            self.addCleanup(fresh.close)
            loose = {**SETTINGS, "score": {**SETTINGS["score"], "min_origins": 1}}  # make_topics 와 같은 조건
            archive.import_all(fresh, Path(tmp), loose)
        # 예전 방식 파일에는 주제 키워드가 없어 그것만 다르다. 요약·숫자는 그대로 옮겨진다.
        restored = feed.build(fresh, DAY, SETTINGS)
        for text in ("실탐 요약", "위키 문서다", "방송에 나와서", "읽은 범위: 대표 문서 본문", "실탐 10건 · LLM 10회"):
            self.assertIn(text, restored)


class LlmSettingsTest(unittest.TestCase):
    def test_default_model_is_haiku_and_changeable_in_settings(self):
        self.assertEqual(SETTINGS["llm"]["model"], "claude-haiku-5-5")
        client = FakeClient()
        llm.summarize(client, {**SETTINGS["llm"], "model": "claude-sonnet-5-5"}, "제목", "자료")
        self.assertEqual(client.calls[0]["model"], "claude-sonnet-5-5")

    def test_no_key_means_unavailable_with_a_plain_reason(self):
        with mock.patch.object(config, "secret", lambda name: None), self.assertRaises(llm.Unavailable) as ctx:
            llm.make_client()
        self.assertIn("ANTHROPIC_API_KEY", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()


class NewReadersTest(unittest.TestCase):
    """유튜브(설명란·댓글)와 GeekNews(피드의 요약 본문)를 읽는 법."""

    CFG = {**SETTINGS["deepread"], "max_chars": 12000, "comments": 20}

    def test_youtube_reads_description_and_top_comments(self):
        from tests.test_youtube import with_key

        class Fetch:
            def __init__(self):
                self.urls = []

            def get_json(self, url, headers=None):
                self.urls.append(url)
                if "/commentThreads" in url:
                    return {"items": [{"snippet": {"topLevelComment": {"snippet": {"textOriginal": f"댓글 {i}"}}}}
                                      for i in range(3)]}
                return {"items": [{"id": "vid1", "snippet": {"title": "t", "description": "신곡 'Angel Bite' 공식 뮤직비디오"}}]}

        e = {"source": "youtube", "external_id": "vid1"}
        fetch = Fetch()
        with with_key():
            material, scope = deepread._read_youtube(e, self.CFG, SETTINGS["sources"], fetch)
        self.assertIn("[설명란]\n신곡 'Angel Bite' 공식 뮤직비디오", material)
        self.assertIn("[댓글]\n- 댓글 0\n- 댓글 1", material)
        self.assertEqual(scope, "설명란 24자 · 댓글 상위 3")
        self.assertTrue(any("maxResults=20" in u and "order=relevance" in u for u in fetch.urls))

    def test_youtube_without_a_key_reads_nothing(self):
        from tests.test_youtube import with_key
        from trendfeed.sources import SourceProblem

        with with_key(None), self.assertRaises(SourceProblem):
            deepread._read_youtube({"source": "youtube", "external_id": "v"}, self.CFG, SETTINGS["sources"], None)

    def test_geeknews_reads_the_summary_inside_the_feed(self):
        from tests.test_geeknews import FEED

        class Fetch:
            def get_text(self, url, headers=None):
                assert url == SETTINGS["sources"]["geeknews"]["feed_url"]
                return FEED

        e = {"source": "geeknews", "external_id": "37285"}
        material, scope = deepread._read_geeknews(e, self.CFG, SETTINGS["sources"], Fetch())
        self.assertEqual(material, "긴 요약 본문은 저장하지 않는다")
        self.assertEqual(scope, "GeekNews 요약 17자")
        e2 = {"source": "geeknews", "external_id": "99999"}  # 피드에서 이미 빠진 글
        self.assertEqual(deepread._read_geeknews(e2, self.CFG, SETTINGS["sources"], Fetch())[0], "")

    def test_every_source_now_has_a_reader(self):
        modules = {cfg.get("module", name) for name, cfg in SETTINGS["sources"].items()}
        self.assertEqual(modules - set(deepread.READERS), set())
