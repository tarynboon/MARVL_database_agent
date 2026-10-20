import unittest
import sheet_sync as s

E = [{"name": "LapNew", "url": "https://x.org", "category": "Gynecology", "access": "direct",
      "bullets": ["a", "b"], "source": "arxiv", "found": "2026-10-19", "status": "pending_review"},
     {"name": "Already Listed", "url": "u", "category": "c", "status": "pending_review"},
     {"name": "Synced", "url": "u", "category": "c", "status": "pending_review", "synced": True},
     {"name": "Approved", "url": "u", "category": "c", "status": "published"}]


class T(unittest.TestCase):
    def test_row_matches_sheet_columns(self):
        row = s.to_row(E[0])
        self.assertEqual(row, ["pending_review", "LapNew", "https://x.org", "Gynecology",
                               "Direct download", "a • b", "arxiv", "2026-10-19", ""])
        self.assertEqual(len(row), 9)

    def test_select_skips_synced_listed_and_non_pending(self):
        got = s.select(E, ["Cholec80", "already-listed"])
        self.assertEqual([e["name"] for e in got], ["LapNew"])

    def test_missing_fields_do_not_crash(self):
        row = s.to_row({"name": "Bare"})
        self.assertEqual(row[1], "Bare")
        self.assertEqual(row[4], "Terms not confirmed")


if __name__ == "__main__":
    unittest.main()
