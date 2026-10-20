#!/usr/bin/env python3
"""Post new dataset candidates to Slack.

Reads candidates.json (written by updater.py, agent.py or agent_gemini.py),
posts every entry that is still "pending_review" and has not been announced
before, then marks those entries "notified" so nobody gets the same message twice.

Setup
  1. Create a Slack incoming webhook (api.slack.com/apps > Create New App >
     From scratch > Incoming Webhooks > on > Add New Webhook to Workspace,
     then pick the channel).
  2. export SLACK_WEBHOOK_URL='https://hooks.slack.com/services/...'
  3. Optional: export SHEET_URL='https://docs.google.com/...'  (link added to the message)

Usage
  python notify.py --dry-run    # print the message, send nothing
  python notify.py              # send it
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

ACCESS = {"direct": "direct download", "request": "request or agreement",
          "unconfirmed": "terms not confirmed"}
MAX_LISTED = 20


def esc(s):
    """Slack treats & < > as markup, and | splits a link from its label."""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("|", "/")


def link_url(u):
    return u.replace(">", "%3E").replace("|", "%7C").replace(" ", "%20")


def build_message(entries, sheet_url=""):
    n = len(entries)
    lines = ["%d new laparoscopic dataset candidate%s to review:" % (n, "" if n == 1 else "s")]
    for e in entries[:MAX_LISTED]:
        label = esc(e["name"])
        name = "<%s|%s>" % (link_url(e["url"]), label) if e.get("url") else "*%s*" % label
        lines.append("• %s (%s, %s)" % (name, esc(e.get("category", "")),
                                         ACCESS.get(e.get("access"), ACCESS["unconfirmed"])))
    if n > MAX_LISTED:
        lines.append("...and %d more." % (n - MAX_LISTED))
    lines.append("Check each against its source page before approving.")
    if sheet_url:
        lines.append("Review queue: <%s|open>" % link_url(sheet_url))
    return "\n".join(lines)


def pending(entries):
    return [e for e in entries if e.get("status") == "pending_review" and not e.get("notified")]


def post(webhook, text):
    req = urllib.request.Request(webhook, data=json.dumps({"text": text}).encode(),
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            r.read()
    except urllib.error.HTTPError as exc:
        sys.exit("Slack rejected the message (%s): %s" % (exc.code, exc.read().decode("utf-8", "replace")[:300]))
    except urllib.error.URLError as exc:
        sys.exit("Could not reach Slack: %s" % exc.reason)


def notify(entries, send, sheet_url=""):
    """Sends one message for new entries and marks them. Returns how many were announced."""
    new = pending(entries)
    if not new:
        return 0
    send(build_message(new, sheet_url))
    for e in new:
        e["notified"] = True
    return len(new)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default="candidates.json")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    try:
        with open(a.file) as f:
            entries = json.load(f)
    except FileNotFoundError:
        sys.exit("%s not found. Run a finder script first." % a.file)
    sheet = os.environ.get("SHEET_URL", "")

    if a.dry_run:
        new = pending(entries)
        print(build_message(new, sheet) if new else "Nothing new to announce.")
        return
    hook = os.environ.get("SLACK_WEBHOOK_URL")
    if not hook:
        sys.exit("SLACK_WEBHOOK_URL is not set. See the setup steps at the top of this file.")
    n = notify(entries, lambda t: post(hook, t), sheet)
    if n:
        with open(a.file, "w") as f:
            json.dump(entries, f, indent=2)
            f.write("\n")
    print("Announced %d candidate(s) in Slack." % n if n else "Nothing new to announce.")


if __name__ == "__main__":
    main()
