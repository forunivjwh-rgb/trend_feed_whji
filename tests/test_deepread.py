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

    def run_it(self, client, fetch=None, day=DAY):
        return deepread.run(self.conn, day, SETTINGS, fetch or Fetch(), client=client, say=self.said.append)

    def test_reads_the_top_items_and_stores_summary_scope_and_usage(self):
        client = FakeClient()
        result = self.run_it(client)
        self.assertEqual((result["read"], result["failed"]), (10, 0))  # 설정의 top_n = 10
        row = dict(self.conn.execute(
            "SELECT d.* FROM deepreads d JOIN items i ON i.id = d.item_id WHERE i.external_id = '문서_1'").fetchone())
        self.assertEqual({k: row[k] for k in SUMMARY}, SUMMARY)
        self.assertEqual(row["scope"], f"문서 본문 {len(RAW):,}자")
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
        result = self.run_it(again, day="2026-11-20")
        self.assertEqual((result["read"], result["skipped"], len(again.calls)), (0, 10, 0))
        later = FakeClient()  # 8일 뒤에는 다시 읽는다
        db.save_records(self.conn, "2026-11-25", "wikipedia_ko", [wiki(1, 5000)], "2026-11-25T19:00:00+00:00")
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

    def test_reads_one_representative_article_per_top_topic(self):
        from tests.test_feed import make_topics
        make_topics(self.conn, DAY, SETTINGS)
        # 문서 1과 2를 한 주제로 묶어 둔다 → 그 주제에서는 어텐션이 큰 문서 1만 읽는다
        code1, code2 = (self.conn.execute(
            "SELECT m.topic_code FROM topic_items m JOIN items i ON i.id = m.item_id WHERE i.external_id = ?", (x,)
        ).fetchone()[0] for x in ("문서_1", "문서_2"))
        self.conn.execute("UPDATE topic_items SET topic_code = ? WHERE topic_code = ?", (code1, code2))
        self.conn.execute("DELETE FROM topic_score WHERE topic_code = ?", (code2,))
        self.conn.commit()
        client = FakeClient()
        result = self.run_it(client)
        self.assertEqual(result["read"], 10)
        titles = [c["messages"][0]["content"].split("\n")[0] for c in client.calls]
        self.assertIn("제목: 문서 1", titles)
        self.assertNotIn("제목: 문서 2", titles)
        self.assertIn("제목: 문서 11", titles)  # 한 자리가 비어 다음 주제가 들어온다

    def test_without_a_key_only_this_step_is_skipped(self):
        with mock.patch.object(config, "secret", lambda name: None):
            result = deepread.run(self.conn, DAY, SETTINGS, Fetch(), say=self.said.append)
            html = feed.build(self.conn, DAY, SETTINGS)
        self.assertEqual(result["read"], 0)
        self.assertIn("LLM 키 없음", result["note"])
        self.assertIn("LLM 키 없음 — 건너뜀", html)
        self.assertIn("지금 인기 Top 5", html)  # 피드는 그대로 나온다

    def test_summary_shows_on_the_card_and_survives_the_day_files(self):
        from tests.test_feed import make_topics
        make_topics(self.conn, DAY, SETTINGS)
        self.run_it(FakeClient())
        html = feed.build(self.conn, DAY, SETTINGS)
        for text in ("실탐 요약", "위키 문서다", "방송에 나와서", "읽은 범위: 문서 본문", "실탐 10건 · LLM 10회 (입력 12,000 · 출력 1,500 토큰)",
                     "실탐</span>"):
            self.assertIn(text, html)
        with tempfile.TemporaryDirectory() as tmp:
            archive.export_day(self.conn, DAY, Path(tmp))
            fresh = db.connect(":memory:")
            self.addCleanup(fresh.close)
            archive.import_all(fresh, Path(tmp))
        self.assertEqual(feed.build(fresh, DAY, SETTINGS), html)


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
