import datetime
import unittest
import updater

ARXIV = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
 <entry><id>http://arxiv.org/abs/2610.01234v1</id><published>2026-10-01T10:00:00Z</published>
  <title>LapNew: A Laparoscopic
  Sigmoidectomy Video Dataset</title>
  <summary>We release 40 videos with phase labels from two centers.</summary></entry>
 <entry><id>http://arxiv.org/abs/2610.09999v1</id><published>2026-10-02T10:00:00Z</published>
  <title>A new transformer for phase recognition</title>
  <summary>We propose a method evaluated on Cholec80.</summary></entry>
</feed>"""

ZENODO = {"hits": {"hits": [
    {"id": 555, "links": {"self_html": "https://zenodo.org/records/555"},
     "metadata": {"resource_type": {"type": "dataset"}, "title": "LapNew-Clips",
                  "publication_date": "2026-10-03", "description": "<p>200 clips &amp; masks</p>",
                  "access_right": "open", "license": {"id": "cc-by-4.0"}}},
    {"id": 557, "links": {"self_html": "https://zenodo.org/records/557"},
     "metadata": {"resource_type": {"type": "publication"}, "title": "A paper",
                  "publication_date": "2026-10-03", "description": "x", "access_right": "open"}},
    {"id": 556, "links": {"self_html": "https://zenodo.org/records/556"},
     "metadata": {"resource_type": {"type": "dataset"}, "title": "Restricted set",
                  "publication_date": "2026-10-03", "description": "x", "access_right": "restricted"}}]}}

DATASETS = [{"name": "Cholec80", "url": "http://camma.u-strasbg.fr/datasets", "category": "Cholecystectomy"},
            {"name": "SLAM", "url": "https://figshare.com/x", "category": "Abdominal and Other Procedures"}]


class T(unittest.TestCase):
    def test_parse_arxiv(self):
        h = updater.parse_arxiv(ARXIV)
        self.assertEqual(h[0]["source_id"], "arxiv:2610.01234v1")
        self.assertEqual(h[0]["title"], "LapNew: A Laparoscopic Sigmoidectomy Video Dataset")
        self.assertEqual(h[0]["date"], "2026-10-01")

    def test_parse_zenodo(self):
        h = updater.parse_zenodo(ZENODO)
        self.assertEqual(len(h), 2)  # the publication record is dropped
        self.assertEqual(h[0]["text"], "200 clips & masks")
        self.assertEqual(h[0]["access"], "direct")
        self.assertEqual(h[1]["access"], "unconfirmed")

    def test_drop_known(self):
        hits = updater.parse_arxiv(ARXIV) + [{"source_id": "z:1", "title": "slam", "url": "u", "text": "", "date": "", "access": ""}]
        out = updater.drop_known(hits, DATASETS, seen=["arxiv:2610.09999v1"], candidates=[])
        self.assertEqual([h["source_id"] for h in out], ["arxiv:2610.01234v1"])

    def test_entry_validation(self):
        cats = ["Cholecystectomy", "Gynecology"]
        hit = {"source": "arxiv", "source_id": "a:1", "url": "https://x", "date": "2026-10-01", "access": "unconfirmed"}
        ok = {"is_dataset": True, "name": "N", "category": "Gynecology", "bullets": ["a", "b"]}
        self.assertEqual(updater.to_entry(hit, ok, cats, "d")["status"], "pending_review")
        self.assertIsNone(updater.to_entry(hit, {"is_dataset": False}, cats, "d"))
        self.assertIsNone(updater.to_entry(hit, dict(ok, category="Nope"), cats, "d"))
        self.assertIsNone(updater.to_entry(hit, dict(ok, bullets=["only one"]), cats, "d"))
        self.assertIsNone(updater.to_entry(hit, None, cats, "d"))

    def test_parse_reply_tolerates_chatter(self):
        self.assertEqual(updater.parse_reply('Sure! {"is_dataset": false} done')["is_dataset"], False)
        self.assertIsNone(updater.parse_reply("no json"))

    def test_end_to_end_with_fake_sources(self):
        today = datetime.date.today().isoformat()
        hits = [dict(h, date=today) for h in updater.parse_arxiv(ARXIV) + updater.parse_zenodo(ZENODO)]
        updater.discover = lambda days: hits

        def fake_claude(prompt):
            if "LapNew: A" in prompt:
                return '{"is_dataset": true, "name": "LapNew", "category": "Abdominal and Other Procedures", "bullets": ["40 videos", "Phase labels from two centers"]}'
            return '{"is_dataset": false}'
        entries, processed = updater.find_candidates(DATASETS, [], [], extract=fake_claude, log=lambda m: None)
        self.assertEqual([e["name"] for e in entries], ["LapNew"])
        self.assertEqual(len(processed), 4)  # one arXiv paper is screened out by the keyword check


class Run(unittest.TestCase):
    def hits(self):
        today = datetime.date.today().isoformat()
        base = {"source": "arxiv", "url": "https://a/", "date": today, "access": "unconfirmed"}
        return [dict(base, source_id="a:1", title="PhaKIR video dataset", text="We release data."),
                dict(base, source_id="a:2", title="A new method", text="We propose a network."),
                dict(base, source_id="a:3", title="Another dataset", text="A benchmark.")]

    def reply(self, name):
        return '{"is_dataset": true, "name": "%s", "category": "Cholecystectomy", "bullets": ["a", "b"]}' % name

    def test_prefilter_known_name_and_limit(self):
        updater.discover = lambda days: self.hits()
        known = [{"name": "PhaKIR", "url": "", "category": "Cholecystectomy"}]
        entries, processed = updater.find_candidates(known, [], [], extract=lambda p: self.reply("PhaKIR Dataset"),
                                                     log=lambda m: None)
        self.assertEqual(entries, [])            # duplicate of a listed dataset
        self.assertEqual(sorted(processed), ["a:1", "a:2", "a:3"])
        entries, processed = updater.find_candidates(known, [], [], extract=lambda p: self.reply("Fresh"),
                                                     limit=1, log=lambda m: None)
        self.assertEqual([e["name"] for e in entries], ["Fresh"])
        self.assertEqual(sorted(processed), ["a:1", "a:2"])  # a:3 waits for the next run

    def test_failure_keeps_finished_work(self):
        updater.discover = lambda days: self.hits()
        calls = []

        def flaky(prompt):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("429 quota")
            return self.reply("Fresh%d" % len(calls))
        logs = []
        entries, processed = updater.find_candidates(DATASETS, [], [], extract=flaky, log=logs.append)
        self.assertEqual([e["name"] for e in entries], ["Fresh1"])
        self.assertIn("a:1", processed)
        self.assertNotIn("a:3", processed)
        self.assertTrue(any("Stopped early" in m for m in logs))


class Gemini(unittest.TestCase):
    def test_retries_on_503_then_returns_text(self):
        import io, os, urllib.error, urllib.request
        os.environ["GEMINI_API_KEY"] = "x"
        calls = []

        def fake_urlopen(req, timeout=0):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.HTTPError("u", 503, "busy", {}, io.BytesIO(b"{}"))
            return io.BytesIO(b'{"candidates":[{"content":{"parts":[{"text":"hello"}]}}]}')
        real_open, real_sleep = urllib.request.urlopen, updater.time.sleep
        urllib.request.urlopen, updater.time.sleep = fake_urlopen, lambda s: None
        try:
            self.assertEqual(updater.call_gemini("p"), "hello")
        finally:
            urllib.request.urlopen, updater.time.sleep = real_open, real_sleep
        self.assertEqual(len(calls), 2)


if __name__ == "__main__":
    unittest.main()
