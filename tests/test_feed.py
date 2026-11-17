"""피드 페이지가 계산된 순위를 그대로 보여 주고, 수집한 글자를 안전하게 넣는지 확인한다."""

import unittest
from unittest import mock

from trendfeed import config, db, feed, topicrun, topics
from trendfeed.sources import Record

T = "2026-11-17T19:00:00+00:00"
FRESH = "2026-11-17T10:00:00+00:00"


def hn(ext_id, title, score, url="https://example.com/a"):
    return Record(external_id=ext_id, title=title, url=url, origin="example.com", published_at=FRESH,
                  rank=1, metrics={"score": score, "comments": 3},
                  item_extra={"discuss_url": f"https://news.ycombinator.com/item?id={ext_id}"})


def make_topics(conn, day, settings, min_origins=1):
    """주제 단계를 돌린다. 묶기 도구 없이(글 하나 = 주제 하나), LLM 검토 없이.

    글 하나짜리 주제는 출처가 1곳이라 명세의 "출처 3곳" 조건으로는 순위에 하나도 오르지 않는다.
    출처 조건과 상관없는 것을 보는 시험이 많아, 기본으로 그 조건을 1곳으로 낮춰 돌린다.
    """
    def no_tool(*args, **kwargs):
        raise topics.Unavailable("시험에서는 묶기 도구를 쓰지 않음")

    loose = {**settings, "score": {**settings["score"], "min_origins": min_origins}}
    with mock.patch.object(topics, "embed", no_tool):
        return topicrun.run(conn, day, loose, review=False)


class FeedTest(unittest.TestCase):
    def setUp(self):
        self.settings = config.load()
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        records = [hn(str(i), f"Story {i}", i * 10) for i in range(1, 13)]
        records.append(hn("90", "<script>alert(1)</script> & co", 900))
        records.append(hn("91", "Sneaky link", 5, url="javascript:alert(1)"))
        db.save_records(self.conn, "2026-11-17", "hackernews", records, T)
        gh = Record(external_id="acme/rocket", title="acme/rocket", url="https://github.com/acme/rocket",
                    origin="github.com/acme", published_at=None, rank=1, metrics={"stars": 5000},
                    item_extra={"description": "A <b>tiny</b> launcher"}, snap_extra={"stars_daily": 300, "forks": 7})
        db.save_records(self.conn, "2026-11-17", "github_trending", [gh], T)
        for source, n in (("hackernews", 14), ("github_trending", 1)):
            db.save_run(self.conn, "2026-11-17", source, item_count=n, followed_count=0, status="ok",
                        memo="", started_at=T, duration_sec=1.5)
        db.save_run(self.conn, "2026-11-16", "hackernews", item_count=0, followed_count=0, status="empty",
                    memo="수집 실패 (TimeoutError)", started_at=T, duration_sec=1.0)
        self.step = make_topics(self.conn, "2026-11-17", self.settings)
        self.html = feed.build(self.conn, "2026-11-17", self.settings)

    def test_now_popular_mode_with_baseline_progress(self):
        self.assertIn("기준선이 쌓이는 중이에요 (1/14일)", self.html)  # 실패한 날은 세지 않는다
        self.assertIn("지금 인기 Top 5", self.html)
        self.assertNotIn("롤업 ·", self.html)

    def test_top_card_is_the_top_topic_with_its_numbers(self):
        # 가운데 값은 65점(1~12번 글 + 900점 + 5점). 900 ÷ 65 = 13.8 → 오늘 어텐션 13.8
        top = self.html.split('<article class="card">')[1]
        self.assertIn("#1", top)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; co", top)
        self.assertIn("<b>13.8</b>", top)
        self.assertIn("하루 +900점", top)  # 근거 글의 숫자
        self.assertIn("T-0001", top)
        self.assertIn("대표", top)

    def test_spec_origin_rule_keeps_single_source_topics_out_even_in_now_popular_mode(self):
        # 명세 3번: 같은 주제가 출처 3곳 미만이면 순위에 올리지 않는다("지금 인기" 모드도 같다)
        step = make_topics(self.conn, "2026-11-17", self.settings, min_origins=3)
        self.assertEqual((step["score"]["mode"], step["score"]["ranked"]), ("early", 0))
        html = feed.build(self.conn, "2026-11-17", self.settings)
        cards = html.split('<article class="card">')[1:]
        self.assertEqual(len(cards), 1)                 # 순위 카드는 없고 탐색 카드 1장만
        self.assertIn("무작위 추첨으로 올라왔어요", cards[0])
        self.assertNotIn("지금 인기</span>", cards[0])

    def test_fallback_without_the_grouping_tool_still_makes_topics(self):
        self.assertTrue(self.step["ok"])
        self.assertIn("글 하나를 주제 하나로 둠", self.step["review_notes"][0])
        self.assertEqual(self.step["score"]["mode"], "early")
        self.assertEqual(self.step["score"]["total"], 15)

    def test_top5_is_four_ranked_topics_and_one_random_explore_topic(self):
        cards = self.html.split('<article class="card">')[1:]
        self.assertEqual(len(cards), 5)
        self.assertTrue(all("지금 인기" in c for c in cards[:4]))
        self.assertIn("탐색", cards[4])
        self.assertIn("무작위 추첨으로 올라왔어요", cards[4])
        self.assertIn("Top 5로 올라감", self.html)

    def test_why_sentence_and_summary_show_on_the_card(self):
        code = self.conn.execute("SELECT topic_code FROM topic_score WHERE rank = 1").fetchone()[0]
        item_id = self.conn.execute("SELECT item_id FROM topic_items WHERE topic_code = ?", (code,)).fetchone()[0]
        self.conn.execute("INSERT INTO topic_why VALUES (?, '2026-11-17', 'Hacker News에서 먼저 올랐어요.', 'm')", (code,))
        db.save_deepread(self.conn, "2026-11-17", item_id, scope="링크 원문 1,000자", what="무엇이다", why="왜다",
                         how="어떻게다", comments_point="", model="m")
        top = feed.build(self.conn, "2026-11-17", self.settings).split('<article class="card">')[1]
        for text in ("Hacker News에서 먼저 올랐어요.", "실탐 요약", "무엇이다", "읽은 범위: 링크 원문 1,000자"):
            self.assertIn(text, top)

    def test_collected_text_is_escaped_and_bad_links_are_not_linked(self):
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt; &amp; co", self.html)
        self.assertNotIn("<script>alert(1)", self.html)
        self.assertNotIn("javascript:", self.html)
        self.assertNotIn("<b>tiny</b>", self.html)

    def test_every_section_and_source_row_is_there(self):
        for text in ("분야별 Top 3", "탐색 슬롯", "수집 상태와 오늘의 실행", "Hacker News", "GitHub trending", "14건", "정상",
                     "메타만", "수집 15건 → 주제 15개 → 순위 15개",
                     "실탐 시간 예산 90분 · 임계 5.0 (기준선 14일 뒤부터 씀) · LLM 0회(이름·병합 0 · 실탐 0 · 왜 올랐나 0)"):
            self.assertIn(text, self.html)

    def test_same_day_rebuild_is_identical(self):
        self.assertEqual(self.html, feed.build(self.conn, "2026-11-17", self.settings))

    def test_day_with_nothing_collected_still_renders(self):
        html = feed.build(self.conn, "2026-11-16", self.settings)
        self.assertIn("수집 실패 (TimeoutError)", html)
        self.assertIn("입력 없음", html)


if __name__ == "__main__":
    unittest.main()
