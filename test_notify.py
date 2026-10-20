import unittest
import notify

E = [{"name": "Lap <A> & B|C", "url": "https://x.org/a|b", "category": "Gynecology", "access": "direct",
      "status": "pending_review"},
     {"name": "Old", "url": "https://y.org", "category": "Gynecology", "status": "pending_review", "notified": True},
     {"name": "Approved", "url": "https://z.org", "category": "Gynecology", "status": "published"}]


class T(unittest.TestCase):
    def test_only_new_pending_entries(self):
        self.assertEqual([e["name"] for e in notify.pending(E)], ["Lap <A> & B|C"])

    def test_message_escapes_slack_markup(self):
        m = notify.build_message(notify.pending(E), "https://sheet.example/s")
        self.assertIn("1 new laparoscopic dataset candidate to review", m)
        self.assertIn("<https://x.org/a%7Cb|Lap &lt;A&gt; &amp; B/C>", m)
        self.assertIn("direct download", m)
        self.assertIn("Review queue: <https://sheet.example/s|open>", m)

    def test_marks_notified_and_does_not_repeat(self):
        sent = []
        entries = [dict(e) for e in E]
        self.assertEqual(notify.notify(entries, sent.append), 1)
        self.assertEqual(notify.notify(entries, sent.append), 0)
        self.assertEqual(len(sent), 1)

    def test_long_list_is_capped(self):
        many = [{"name": "n%d" % i, "url": "", "category": "c", "status": "pending_review"} for i in range(25)]
        m = notify.build_message(many)
        self.assertIn("...and 5 more.", m)
        self.assertIn("*n0*", m)  # no url: plain bold name

    def test_nothing_to_send(self):
        self.assertEqual(notify.notify([E[1], E[2]], lambda t: self.fail("sent")), 0)


if __name__ == "__main__":
    unittest.main()
