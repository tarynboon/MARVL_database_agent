import unittest
import agent

DATASETS = [{"name": "Cholec80", "url": "http://camma.u-strasbg.fr/datasets", "category": "Cholecystectomy"},
            {"name": "SLAM", "url": "https://figshare.com/x", "category": "Abdominal and Other Procedures"}]

FINAL = '''Here is what I found:
[{"name": "LapNew", "url": "https://zenodo.org/records/1", "category": "Cholecystectomy", "access": "direct", "bullets": ["40 videos", "Phase labels"]},
 {"name": "Cholec80", "url": "https://x.org", "category": "Cholecystectomy", "bullets": ["a", "b"]},
 {"name": "NoHttps", "url": "http://x.org", "category": "Cholecystectomy", "bullets": ["a", "b"]},
 {"name": "OneBullet", "url": "https://y.org", "category": "Cholecystectomy", "bullets": ["a"]},
 {"name": "BadCat", "url": "https://z.org", "category": "Nope", "bullets": ["a", "b"]}]'''


class T(unittest.TestCase):
    def test_loop_handles_pause_and_logs_searches(self):
        replies = [
            {"stop_reason": "pause_turn", "content": [
                {"type": "server_tool_use", "input": {"query": "laparoscopic dataset 2026"}}]},
            {"stop_reason": "end_turn", "content": [
                {"type": "server_tool_use", "input": {"query": "zenodo laparoscopic videos"}},
                {"type": "text", "text": FINAL}]}]
        seen = []
        text, n = agent.run_agent("p", 10, call=lambda m, k: replies.pop(0), log=seen.append)
        self.assertEqual(n, 2)
        self.assertEqual(len(seen), 2)
        self.assertIn("LapNew", text)

    def test_entries_are_validated_and_deduped(self):
        out = agent.to_entries(agent.parse_items(FINAL), DATASETS, [], "2026-10-19")
        self.assertEqual([e["name"] for e in out], ["LapNew"])
        self.assertEqual(out[0]["status"], "pending_review")
        again = agent.to_entries(agent.parse_items(FINAL), DATASETS, out, "2026-10-19")
        self.assertEqual(again, [])

    def test_no_json(self):
        self.assertEqual(agent.parse_items("I found nothing."), [])


if __name__ == "__main__":
    unittest.main()
