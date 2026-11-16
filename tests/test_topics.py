"""주제 묶기: 뜻으로 묶기와 이름으로 붙이기. 벡터는 손으로 만든 것을 쓴다(모델 없이)."""

import unittest

try:
    import numpy as np
except ImportError:  # 주제 묶기 도구를 설치하지 않은 곳에서는 건너뛴다
    np = None

from trendfeed import config, topics

SETTINGS = config.load()
SETTINGS["topics"] = {**SETTINGS["topics"], "threshold": 0.85, "name_min_chars": 3, "name_min_similarity": 0.45}


def entry(source, title, attention, origin=None, desc=None):
    return {"source": source, "title": title, "attention": attention, "origin": origin or f"{source}.example",
            "item_extra": {"description": desc} if desc else {}}


def unit(*v):
    a = np.array(v, dtype=float)
    return a / np.linalg.norm(a)


@unittest.skipIf(np is None, "numpy 가 없어 건너뜀")
class ClusterTest(unittest.TestCase):
    def test_similar_meaning_merges_across_sources_and_languages(self):
        entries = [
            entry("hackernews", "Vulcan rocket fails during return-to-flight", 5.0, "arstechnica.com"),
            entry("geeknews", "Vulcan 로켓, 비행 재개 발사 실패", 1.0, "news.hada.io/@a"),
            entry("hackernews", "A NES emulator written in Odin", 2.0),
        ]
        vectors = np.array([unit(1, 0, 0), unit(0.95, 0.2, 0), unit(0, 1, 0)])
        found = topics.cluster(entries, vectors, SETTINGS)
        self.assertEqual([[e["title"][:6] for e in t["items"]] for t in found], [["Vulcan", "Vulcan"], ["A NES "]])
        self.assertEqual(found[0]["platforms"], ["GN", "HN"])
        self.assertEqual(found[0]["origins"], 2)
        self.assertAlmostEqual(found[0]["attention"], 6.0)

    def test_below_threshold_stays_separate(self):
        entries = [entry("hackernews", "one", 2.0), entry("geeknews", "two", 1.0)]
        vectors = np.array([unit(1, 0), unit(0.8, 0.6)])  # 비슷함 0.8 < 0.85
        self.assertEqual(len(topics.cluster(entries, vectors, SETTINGS)), 2)

    def test_wikipedia_joins_only_when_its_name_appears_in_another_title(self):
        entries = [
            entry("wikipedia_en", "Nvidia", 9.0),
            entry("hackernews", "What's Next for Nvidia?", 3.0),
            entry("geeknews", "젠슨 황 이후, Nvidia는 어디로 가나?", 1.0),
            entry("wikipedia_ko", "젠슨 황", 4.0),
            entry("wikipedia_ko", "김유정 (배우)", 8.0),
            entry("wikipedia_ko", "김윤석 (배우)", 7.0),
        ]
        same = unit(1, 0)
        vectors = np.array([same, same, same, same, same, same])  # 뜻으로는 전부 똑같아 보여도
        found = topics.cluster(entries, vectors, SETTINGS)
        titles = [sorted(e["title"] for e in t["items"]) for t in found]
        self.assertIn(sorted(["Nvidia", "What's Next for Nvidia?", "젠슨 황 이후, Nvidia는 어디로 가나?", "젠슨 황"]), titles)
        self.assertIn(["김유정 (배우)"], titles)  # 위키 문서끼리는 묶지 않는다
        self.assertIn(["김윤석 (배우)"], titles)

    def test_name_matching_needs_a_whole_word_and_a_long_enough_name(self):
        self.assertTrue(topics._mentions("nvidia", "젠슨 황 이후, Nvidia는 어디로 가나?"))
        self.assertTrue(topics._mentions("젠슨 황", "젠슨 황, Nvidia CEO 복귀"))
        self.assertFalse(topics._mentions("go", "Google ships something"))
        self.assertFalse(topics._mentions("rust", "Trust issues in open source"))
        entries = [entry("wikipedia_ko", "가야", 5.0), entry("geeknews", "집에 가야 한다", 1.0)]
        found = topics.cluster(entries, np.array([unit(1, 0), unit(1, 0)]), SETTINGS)
        self.assertEqual(len(found), 2)  # 두 글자 이름은 쓰지 않는다

    def test_ambiguous_names_with_parentheses_also_need_similar_meaning(self):
        # 실제로 나온 틀린 짝: 위키 'Scene (2026 film)' ↔ 'Print Scene' 이 들어간 글 (뜻 비슷함 0.40)
        entries = [
            entry("wikipedia_en", "Scene (2026 film)", 5.0),
            entry("hackernews", "Has the Independent Print Scene Outgrown Expozine?", 2.0),
            entry("wikipedia_ko", "김지원 (배우)", 4.0),
            entry("youtube", "[최종회 예고] 환자의 수술을 중단한 김지원", 3.0),
            entry("wikipedia_ko", "에이티즈", 6.0),
            entry("youtube", "ATEEZ(에이티즈) - 'UP' Official MV", 9.0),
        ]
        vectors = np.array([
            unit(1, 0, 0, 0, 0, 0), unit(0.40, 0.92, 0, 0, 0, 0),   # 비슷함 0.40 → 붙이지 않는다
            unit(0, 0, 1, 0, 0, 0), unit(0, 0, 0.50, 0.87, 0, 0),   # 비슷함 0.50 → 붙인다
            unit(0, 0, 0, 0, 1, 0), unit(0, 0, 0, 0, 0.27, 0.96),   # 괄호 없는 이름은 뜻을 묻지 않는다
        ])
        titles = [sorted(e["title"] for e in t["items"]) for t in topics.cluster(entries, vectors, SETTINGS)]
        self.assertIn(["Scene (2026 film)"], titles)
        self.assertIn(sorted(["김지원 (배우)", "[최종회 예고] 환자의 수술을 중단한 김지원"]), titles)
        self.assertIn(sorted(["에이티즈", "ATEEZ(에이티즈) - 'UP' Official MV"]), titles)

    def test_youtube_text_adds_channel_and_repeated_comment_words_without_laughter(self):
        e = entry("youtube", "정말 달콤해", 1.0)
        e["item_extra"] = {"channel_title": "빵굽는집"}
        e["extra"] = {"comment_phrases": [{"text": "ㅋㅋㅋㅋㅋ", "count": 5}, {"text": "소금빵 레시피", "count": 4}]}
        self.assertEqual(topics.text_of(e, "ㅋㅎㅠ"), "정말 달콤해. 채널: 빵굽는집. 댓글: 소금빵 레시피")
        self.assertEqual(topics.text_of(entry("youtube", "제목만", 1.0), "ㅋㅎㅠ"), "제목만")

    def test_text_for_meaning_unpacks_repo_names_and_adds_description(self):
        e = entry("github_trending", "acme/rocket-launcher", 1.0, desc="A tiny launcher")
        self.assertEqual(topics.text_of(e), "acme rocket launcher. A tiny launcher")
        self.assertEqual(topics.text_of(entry("hackernews", "TCP/IP is fine", 1.0)), "TCP/IP is fine")


@unittest.skipIf(np is None, "numpy 가 없어 건너뜀")
class ReviewTest(unittest.TestCase):
    """LLM의 판단(이름·합치기·떼어 내기)을 코드가 적용한다. 가짜 LLM을 쓴다."""

    def setUp(self):
        entries = [
            entry("youtube", "[예비군] 대한민국 군필자라면 꼭 해봐야 하는 국산게임", 2.0, "youtube.com/channel/a"),
            entry("wikipedia_ko", "대한민국", 1.0),
            entry("hackernews", "What's Next for Nvidia?", 3.0, "example.com"),
            entry("wikipedia_en", "Nvidia", 1.5),
            entry("geeknews", "젠슨 황 이후, Nvidia는 어디로 가나?", 1.0, "news.hada.io/@a"),
            entry("wikipedia_ko", "젠슨 황", 2.0),
            entry("hackernews", "혼자 있는 글", 0.5),
        ]
        vectors = np.array([unit(1, 0, 0, 0), unit(1, 0, 0, 0), unit(0, 1, 0, 0), unit(0, 1, 0, 0),
                            unit(0, 0, 1, 0), unit(0, 0, 1, 0), unit(0, 0, 0, 1)])
        self.found = topics.cluster(entries, vectors, SETTINGS)
        self.picked = topics.pick_for_review(self.found, SETTINGS["topics"])
        self.text, self.where = topics.listing(self.picked, SETTINGS["sources"])

    def number_of(self, title):
        lines = self.text.splitlines()
        return next(int(l.split("항목 ")[1].split(":")[0]) for l in lines if l.strip().endswith(title))

    def topic_of(self, title):
        return self.where[self.number_of(title)][0]

    def test_listing_numbers_topics_and_items_for_the_llm(self):
        self.assertTrue(self.text.startswith("주제 1\n  항목 1: ["))
        self.assertIn("[Wikipedia (한국어)] 대한민국", self.text)
        self.assertEqual(len(self.where), 7)

    def test_names_merges_and_removals_are_applied(self):
        nvidia, jensen, korea = self.topic_of("Nvidia"), self.topic_of("젠슨 황"), self.topic_of("대한민국")
        review = {
            "topics": [
                {"id": nvidia, "name": "Nvidia의 다음 행보", "remove_items": []},
                {"id": jensen, "name": "젠슨 황 이후의 Nvidia", "remove_items": []},
                {"id": korea, "name": "예비군 게임", "remove_items": [self.number_of("대한민국")]},
            ],
            "merges": [{"ids": [nvidia, jensen]}],
        }
        result = topics.apply_review(self.found, self.picked, self.where, review, SETTINGS["sources"])
        by_name = {t["name"]: t for t in result}
        merged = by_name["Nvidia의 다음 행보"]  # 어텐션이 더 큰 쪽의 이름을 쓴다
        self.assertEqual(len(merged["items"]), 4)
        self.assertEqual(merged["platforms"], ["GN", "HN", "WK"])
        self.assertAlmostEqual(merged["attention"], 7.5)
        self.assertEqual([e["title"] for e in by_name["예비군 게임"]["items"]],
                         ["[예비군] 대한민국 군필자라면 꼭 해봐야 하는 국산게임"])
        self.assertIn("대한민국", by_name)  # 떼어 낸 문서는 혼자 한 주제가 된다
        self.assertFalse(by_name["대한민국"]["named_by_llm"])
        self.assertEqual(sum(len(t["items"]) for t in result), 7)  # 항목은 하나도 사라지지 않는다

    def test_nonsense_from_the_llm_is_ignored(self):
        korea = self.topic_of("대한민국")
        review = {
            "topics": [{"id": 999, "name": "없는 주제", "remove_items": [1]},
                       {"id": korea, "name": "", "remove_items": [9999, self.number_of("Nvidia")]}],
            "merges": [{"ids": [korea, 999]}, {"ids": [korea]}],
        }
        result = topics.apply_review(self.found, self.picked, self.where, review, SETTINGS["sources"])
        self.assertEqual(sorted(len(t["items"]) for t in result), sorted(len(t["items"]) for t in self.found))

    def test_review_asks_once_and_survives_no_key_or_no_answer(self):
        from types import SimpleNamespace
        from unittest import mock
        import json

        class Client:
            def __init__(self, stop="end_turn"):
                self.calls, self.stop = [], stop
                self.messages = SimpleNamespace(create=self.create)

            def create(self, **kw):
                self.calls.append(kw)
                return SimpleNamespace(stop_reason=self.stop, usage=SimpleNamespace(input_tokens=900, output_tokens=80),
                                       content=[SimpleNamespace(type="text", text=json.dumps({"topics": [], "merges": []}))])

        client = Client()
        result, note, usage = topics.review(self.found, SETTINGS, client=client)
        self.assertEqual((len(client.calls), note, usage), (1, "", {"input_tokens": 900, "output_tokens": 80}))
        self.assertEqual(client.calls[0]["model"], SETTINGS["llm"]["model"])
        self.assertIn("<주제후보>", client.calls[0]["messages"][0]["content"])
        self.assertEqual(len(result), len(self.found))
        _, note, _ = topics.review(self.found, SETTINGS, client=Client(stop="refusal"))
        self.assertIn("건너뜀", note)
        with mock.patch.object(config, "secret", lambda name: None):
            same, note, usage = topics.review(self.found, SETTINGS)
        self.assertIs(same, self.found)
        self.assertIn("LLM 키 없음", note)
        self.assertIsNone(usage)


if __name__ == "__main__":
    unittest.main()
