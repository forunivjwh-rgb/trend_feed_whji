""""왜 올랐나" 한 문장: LLM은 코드가 준 사실만 쓰고, 사실에 없는 숫자가 든 문장은 버린다(가짜 LLM)."""

import json
import unittest
from types import SimpleNamespace
from unittest import mock

from trendfeed import config, db, why
from tests.test_feed import make_topics
from tests.test_hackernews import story
from trendfeed.sources import hackernews

SETTINGS = config.load()
DAY = "2026-11-17"


class Client:
    def __init__(self, answer):
        self.answer, self.calls = answer, []
        self.messages = SimpleNamespace(create=self.create)

    def create(self, **kw):
        self.calls.append(kw)
        return SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=700, output_tokens=90),
                               content=[SimpleNamespace(type="text", text=json.dumps(self.answer))])


class WhyTest(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        records = [hackernews.to_record(story(i, time=1794826996), rank=i, listed=True) for i in range(1, 9)]
        db.save_records(self.conn, DAY, "hackernews", records, DAY + "T19:00:00+00:00")
        db.save_run(self.conn, DAY, "hackernews", item_count=8, followed_count=0, status="ok", memo="",
                    started_at=DAY + "T19:00:00+00:00", duration_sec=1)
        make_topics(self.conn, DAY, SETTINGS)
        self.codes = [r[0] for r in self.conn.execute(
            "SELECT topic_code FROM topic_score WHERE date = ? AND rank IS NOT NULL ORDER BY rank", (DAY,))]

    def test_facts_hold_only_code_computed_numbers(self):
        facts = why.facts_for(self.conn, DAY, self.codes[0], SETTINGS)
        self.assertIn(f"주제 {self.codes[0]}: Story 8", facts)
        self.assertIn("플랫폼별 처음 나타난 날: Hacker News 2026-11-17", facts)
        self.assertIn("서로 다른 출처 1곳 · 글 1건", facts)
        self.assertNotIn("평소 대비 z", facts)  # "지금 인기" 모드에는 z 가 없다

    def test_numbers_must_come_from_the_facts(self):
        facts = "오늘 어텐션 합 13.8 · 서로 다른 출처 3곳 · 처음 나타난 날 2026-11-17"
        self.assertTrue(why.keeps_to_facts("Hacker News에서 먼저 올라 출처 3곳으로 번졌어요.", facts))
        self.assertTrue(why.keeps_to_facts("숫자 없이 쓴 문장이에요.", facts))
        self.assertFalse(why.keeps_to_facts("하루 만에 2배로 뛰었어요.", facts))
        self.assertFalse(why.keeps_to_facts("조회수 50만을 넘었어요.", facts))

    def test_writes_sentences_for_the_top_topics_in_one_call(self):
        top = self.codes[:4]
        answer = {"sentences": [{"id": c, "text": "Hacker News에서 오늘 처음 나타났어요."} for c in top]
                  + [{"id": top[0], "text": "평소의 7배로 뛰었어요."},       # 사실에 없는 숫자 → 버림
                     {"id": "T-9999", "text": "없는 주제"}]}               # 목록에 없는 주제 → 무시
        client = Client(answer)
        result = why.run(self.conn, DAY, SETTINGS, client=client, say=lambda s: None)
        self.assertEqual(len(client.calls), 1)
        sent = client.calls[0]["messages"][0]["content"]
        self.assertTrue(sent.startswith("<사실>"))
        self.assertEqual(sum(f"주제 {c}:" in sent for c in self.codes), 5)  # 위 4개 + 탐색 1개
        self.assertEqual(result["dropped"], 1)
        saved = dict(self.conn.execute("SELECT topic_code, sentence FROM topic_why").fetchall())
        self.assertEqual(saved[top[0]], "Hacker News에서 오늘 처음 나타났어요.")
        self.assertNotIn("T-9999", saved)
        self.assertEqual(self.conn.execute("SELECT purpose, input_tokens FROM llm_calls").fetchone()[:], ("why", 700))

    def test_topics_that_already_have_a_sentence_today_are_not_asked_again(self):
        answer = {"sentences": [{"id": c, "text": "먼저 올랐어요."} for c in self.codes]}
        why.run(self.conn, DAY, SETTINGS, client=Client(answer), say=lambda s: None)
        again = Client(answer)
        result = why.run(self.conn, DAY, SETTINGS, client=again, say=lambda s: None)
        self.assertEqual((len(again.calls), result["written"]), (0, 0))

    def test_without_a_key_it_is_skipped(self):
        with mock.patch.object(config, "secret", lambda name: None):
            result = why.run(self.conn, DAY, SETTINGS, say=lambda s: None)
        self.assertIn("LLM 키 없음", result["note"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM topic_why").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
