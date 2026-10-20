import unittest
import agent_gemini as g

RESP = {"candidates": [{
    "content": {"parts": [{"text": 'Found: [{"name": "LapNew", "url": "https://zenodo.org/records/1", '
                                    '"category": "Cholecystectomy", "access": "direct", "bullets": ["a", "b"]}]'}]},
    "groundingMetadata": {
        "webSearchQueries": ["laparoscopic dataset 2026", "zenodo laparoscopic videos"],
        "groundingChunks": [{"web": {"uri": "https://vertexaisearch.example/x", "title": "zenodo.org"}},
                            {"web": {"uri": "https://vertexaisearch.example/y", "title": "arxiv.org"}}]}}]}


class T(unittest.TestCase):
    def test_parse_response(self):
        text, queries, domains = g.parse_response(RESP)
        self.assertIn("LapNew", text)
        self.assertEqual(len(queries), 2)
        self.assertEqual(domains, {"zenodo.org", "arxiv.org"})

    def test_empty_response(self):
        self.assertEqual(g.parse_response({}), ("", [], set()))

    def test_grounding_flag(self):
        es = [{"url": "https://www.zenodo.org/records/1"}, {"url": "https://example.com/p"}]
        out = g.mark_grounded(es, {"zenodo.org"})
        self.assertEqual([e["grounded"] for e in out], [True, False])


if __name__ == "__main__":
    unittest.main()
