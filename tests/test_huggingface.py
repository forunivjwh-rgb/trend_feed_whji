import unittest

from trendfeed.sources import huggingface as hf

CFG = {"api_base": "https://example.invalid/api", "limit": 40}


def model(model_id, **over):
    data = {"id": model_id, "likes": 120, "downloads": 5000, "trendingScore": 88.5, "private": False,
            "pipeline_tag": "text-generation", "createdAt": "2026-11-03T06:34:36.000Z"}
    data.update(over)
    return data


class Fetch:
    def __init__(self, data):
        self.data, self.urls = data, []

    def get_json(self, url):
        self.urls.append(url)
        return self.data


class HuggingFaceTest(unittest.TestCase):
    def test_asks_for_trending_models_with_the_configured_limit(self):
        fetch = Fetch([])
        hf.collect(CFG, fetch)
        self.assertEqual(fetch.urls, ["https://example.invalid/api/models?sort=trendingScore&direction=-1&limit=40"])

    def test_maps_fields(self):
        (r,) = hf.collect(CFG, Fetch([model("MiniMaxAI/MiniMax-H3-Image")])).records
        self.assertEqual(r.external_id, "MiniMaxAI/MiniMax-H3-Image")
        self.assertEqual(r.url, "https://huggingface.co/MiniMaxAI/MiniMax-H3-Image")
        self.assertEqual(r.origin, "huggingface.co/minimaxai")
        self.assertEqual(r.published_at, "2026-11-03T06:34:36+00:00")
        self.assertEqual(r.metrics, {"likes": 120})
        self.assertEqual(r.snap_extra, {"downloads": 5000, "trending_score": 88.5})
        self.assertEqual(r.item_extra, {"kind": "text-generation"})
        self.assertEqual(r.rank, 1)

    def test_keeps_api_order_and_skips_private_or_nameless(self):
        data = [model("a/one"), model("b/two", private=True), {"likes": 3}, model("gpt2", createdAt=None)]
        records = hf.collect(CFG, Fetch(data)).records
        self.assertEqual([(r.external_id, r.rank) for r in records], [("a/one", 1), ("gpt2", 2)])
        self.assertEqual(records[1].origin, "huggingface.co")  # 소유자 없는 옛 모델 이름
        self.assertIsNone(records[1].published_at)


if __name__ == "__main__":
    unittest.main()
