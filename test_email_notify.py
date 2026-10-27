import unittest
import email_notify as en

E = [{"name": "DataA", "url": "https://a/", "category": "Cholecystectomy", "access": "direct",
      "bullets": ["one", "two"], "status": "pending_review"},
     {"name": "Old", "status": "pending_review", "emailed": True},
     {"name": "Rejected", "status": "rejected"}]


class T(unittest.TestCase):
    def test_pending_skips_emailed_and_non_pending(self):
        self.assertEqual([e["name"] for e in en.pending(E)], ["DataA"])

    def test_body(self):
        subject, body = en.build_email(en.pending(E), "https://sheet/")
        self.assertEqual(subject, "1 new laparoscopic dataset candidate to review")
        for s in ("DataA", "https://a/", "direct download", "* one", "https://sheet/"):
            self.assertIn(s, body)

    def test_notify_marks_once_and_slack_flag_untouched(self):
        entries = [dict(e) for e in E]
        sent = []
        self.assertEqual(en.notify(entries, lambda s, b: sent.append(s)), 1)
        self.assertTrue(entries[0]["emailed"])
        self.assertNotIn("notified", entries[0])
        self.assertEqual(en.notify(entries, lambda s, b: sent.append(s)), 0)
        self.assertEqual(len(sent), 1)

    def test_nothing_to_send(self):
        sent = []
        self.assertEqual(en.notify([], lambda s, b: sent.append(s)), 0)
        self.assertEqual(sent, [])

    def test_more_than_max_listed(self):
        many = [{"name": "D%d" % i, "status": "pending_review"} for i in range(35)]
        self.assertIn("...and 5 more.", en.build_email(many)[1])


if __name__ == "__main__":
    unittest.main()
