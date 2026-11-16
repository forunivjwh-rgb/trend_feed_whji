"""주제 묶기: 뜻으로 묶기와 이름으로 붙이기. 벡터는 손으로 만든 것을 쓴다(모델 없이)."""

import unittest

try:
    import numpy as np
except ImportError:  # 주제 묶기 도구를 설치하지 않은 곳에서는 건너뛴다
    np = None

from trendfeed import config, topics

SETTINGS = config.load()
SETTINGS["topics"] = {**SETTINGS["topics"], "threshold": 0.85, "name_min_chars": 3}


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

    def test_text_for_meaning_unpacks_repo_names_and_adds_description(self):
        e = entry("github_trending", "acme/rocket-launcher", 1.0, desc="A tiny launcher")
        self.assertEqual(topics.text_of(e), "acme rocket launcher. A tiny launcher")
        self.assertEqual(topics.text_of(entry("hackernews", "TCP/IP is fine", 1.0)), "TCP/IP is fine")


if __name__ == "__main__":
    unittest.main()
