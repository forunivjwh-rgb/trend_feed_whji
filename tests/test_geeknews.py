import unittest

from trendfeed import db, rank
from trendfeed.sources import geeknews as gn

FEED = """<?xml version='1.0' encoding='UTF-8'?>
<feed xmlns='http://www.w3.org/2005/Atom'>
<title>GeekNews</title>
<author><name>GeekNews</name></author>
<entry>
  <title><![CDATA[Show GN: 악보를 코드로 & <AI> 편곡]]></title>
  <link rel='alternate' type='text/html' href='https://news.hada.io/topic?id=37285&amp;utm_source=geeknews&amp;utm_medium=rss' />
  <id>https://news.hada.io/topic?id=37285</id>
  <updated>2026-11-16T21:00:00+09:00</updated>
  <published>2026-11-16T20:49:34+09:00</published>
  <author><name>letitflow</name><uri>https://news.hada.io/user/letitflow</uri></author>
  <content type='html'><![CDATA[<p>긴 요약 본문은 저장하지 않는다</p>]]></content>
</entry>
<entry>
  <title>작성자 없는 글</title>
  <id>https://news.hada.io/topic?id=37280</id>
  <updated>2026-11-16T10:00:00+09:00</updated>
</entry>
<entry><title></title><id>https://news.hada.io/topic?id=1</id></entry>
</feed>"""


class ParseTest(unittest.TestCase):
    def test_reads_entries_without_keeping_the_body(self):
        first, second = gn.parse(FEED)
        self.assertEqual(first.external_id, "37285")
        self.assertEqual(first.title, "Show GN: 악보를 코드로 & <AI> 편곡")
        self.assertEqual(first.url, "https://news.hada.io/topic?id=37285")  # 추적용 꼬리표 없는 주소
        self.assertEqual(first.origin, "news.hada.io/@letitflow")
        self.assertEqual(first.published_at, "2026-11-16T11:49:34+00:00")
        self.assertEqual((first.metrics, first.item_extra, first.snap_extra), ({}, {}, {}))
        self.assertEqual((second.external_id, second.origin, second.rank), ("37280", "news.hada.io", 2))
        self.assertEqual(second.published_at, "2026-11-16T01:00:00+00:00")  # published 가 없으면 updated


class CountNewTest(unittest.TestCase):
    """숫자가 없는 소스는 새로 올라온 날에만 1건으로 센다."""

    def test_new_today_counts_once_then_zero(self):
        settings = {"attention": {"min_gap_hours": 6, "compare_within_days": 3, "median_floor": 1.0},
                    "sources": {"geeknews": {"weight": 1.0}}}
        conn = db.connect(":memory:")
        self.addCleanup(conn.close)
        records = gn.parse(FEED)
        db.save_records(conn, "2026-11-16", "geeknews", records, "2026-11-16T19:00:00+00:00")
        day1 = rank.now_popular(conn, "2026-11-16", settings)
        self.assertEqual([(e["velocity"], e["times_typical"]) for e in day1], [(1.0, 1.0), (1.0, 1.0)])
        # 다음 날 같은 글이 피드에 그대로 있어도 다시 세지 않는다.
        db.save_records(conn, "2026-11-17", "geeknews", records, "2026-11-17T19:00:00+00:00")
        day2 = rank.now_popular(conn, "2026-11-17", settings)
        self.assertEqual([(e["velocity"], e["basis"]) for e in day2], [(0.0, "이전에 이미 셈")] * 2)


if __name__ == "__main__":
    unittest.main()
