import unittest

from trendfeed.sources import hackernews as hn

CFG = {"api_base": "https://example.invalid/v0", "limit": 3, "workers": 2}


def story(i, **over):
    data = {
        "id": i,
        "type": "story",
        "by": f"user{i}",
        "title": f"Story {i}",
        "url": f"https://site{i}.example/post",
        "score": i * 10,
        "descendants": i,
        "time": 1794826996,
    }
    data.update(over)
    return data


class FakeFetch:
    def __init__(self, top, items, broken=()):
        self.top, self.items, self.broken = top, items, set(broken)
        self.asked = []

    def get_json(self, url):
        if url.endswith("/topstories.json"):
            return self.top
        item_id = int(url.rsplit("/", 1)[1].removesuffix(".json"))
        self.asked.append(item_id)
        if item_id in self.broken:
            raise TimeoutError()
        return self.items.get(item_id)


class OriginTest(unittest.TestCase):
    def test_link_post_uses_site(self):
        self.assertEqual(hn.origin_of("https://www.example.com/a/b", "pg"), "example.com")

    def test_github_link_keeps_owner(self):
        self.assertEqual(hn.origin_of("https://github.com/Acme/rocket", "pg"), "github.com/acme")

    def test_text_post_uses_author(self):
        self.assertEqual(hn.origin_of(None, "pg"), "hn-user:pg")


class ToRecordTest(unittest.TestCase):
    def test_maps_fields(self):
        r = hn.to_record(story(7), rank=2, listed=True)
        self.assertEqual(r.external_id, "7")
        self.assertEqual(r.title, "Story 7")
        self.assertEqual(r.url, "https://site7.example/post")
        self.assertEqual(r.origin, "site7.example")
        self.assertEqual(r.published_at, "2026-11-16T11:03:16+00:00")
        self.assertEqual(r.metrics, {"score": 70, "comments": 7})
        self.assertEqual(r.item_extra["discuss_url"], "https://news.ycombinator.com/item?id=7")

    def test_text_post_links_to_discussion(self):
        r = hn.to_record(story(7, url=None), rank=1, listed=True)
        self.assertEqual(r.url, "https://news.ycombinator.com/item?id=7")
        self.assertEqual(r.origin, "hn-user:user7")

    def test_skips_jobs_deleted_dead_and_missing(self):
        self.assertIsNone(hn.to_record(story(1, type="job"), 1, True))
        self.assertIsNone(hn.to_record(story(1, deleted=True), 1, True))
        self.assertIsNone(hn.to_record(story(1, dead=True), 1, True))
        self.assertIsNone(hn.to_record(None, 1, True))


class CollectTest(unittest.TestCase):
    def test_fills_the_limit_past_skipped_posts_in_list_order(self):
        items = {i: story(i) for i in range(1, 7)}
        items[2] = story(2, type="job")
        fetch = FakeFetch([1, 2, 3, 4, 5, 6], items)
        result = hn.collect(CFG, fetch)
        self.assertEqual([r.external_id for r in result.records], ["1", "3", "4"])
        self.assertEqual([r.rank for r in result.records], [1, 2, 3])
        self.assertEqual(result.problems, [])
        self.assertNotIn(5, fetch.asked)  # 채우고 나면 더 읽지 않는다

    def test_reports_posts_it_could_not_read(self):
        fetch = FakeFetch([1, 2, 3, 4], {i: story(i) for i in range(1, 5)}, broken=[2])
        result = hn.collect(CFG, fetch)
        self.assertEqual([r.external_id for r in result.records], ["1", "3", "4"])
        self.assertEqual(result.problems, ["글 1개를 읽지 못함"])

    def test_stops_when_everything_fails(self):
        fetch = FakeFetch(list(range(1, 100)), {}, broken=range(1, 100))
        result = hn.collect(CFG, fetch)
        self.assertEqual(result.records, [])
        self.assertEqual(len(fetch.asked), 3)  # 첫 묶음만 두드리고 멈춘다

    def test_refetch_marks_records_as_not_listed(self):
        fetch = FakeFetch([], {5: story(5), 6: story(6, dead=True)})
        result = hn.refetch(CFG, fetch, ["5", "6"])
        self.assertEqual([(r.external_id, r.listed, r.rank) for r in result.records], [("5", False, None)])


if __name__ == "__main__":
    unittest.main()
