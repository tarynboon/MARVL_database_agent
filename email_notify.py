#!/usr/bin/env python3
"""Email new dataset candidates (for example to a Stanford Outlook address).

Sends from a Gmail account through Gmail's SMTP server using an App Password.
Reads candidates.json, emails every entry that is "pending_review" and not yet
emailed, then marks those entries "emailed". Slack's "notified" flag is separate,
so the two notifications never block each other.

Setup
  1. Turn on 2-step verification for the sending Gmail account, then create an App
     Password (Google Account > Security > App passwords). It is 16 characters.
  2. export SMTP_USER='sender@gmail.com'
     export SMTP_PASS='the app password'
     export EMAIL_TO='you@stanford.edu'        # several addresses: separate with commas
  3. Optional: export SHEET_URL='https://docs.google.com/...'

Usage
  python email_notify.py --dry-run    # print the email, send nothing
  python email_notify.py              # send it
"""
import argparse
import json
import os
import smtplib
import sys
from email.message import EmailMessage

ACCESS = {"direct": "direct download", "request": "request or agreement",
          "unconfirmed": "terms not confirmed"}
MAX_LISTED = 30


def pending(entries):
    return [e for e in entries if e.get("status") == "pending_review" and not e.get("emailed")]


def build_email(entries, sheet_url=""):
    """Returns (subject, plain-text body)."""
    n = len(entries)
    subject = "%d new laparoscopic dataset candidate%s to review" % (n, "" if n == 1 else "s")
    lines = [subject + ":", ""]
    for e in entries[:MAX_LISTED]:
        lines.append("- %s (%s, %s)" % (e["name"], e.get("category", ""),
                                         ACCESS.get(e.get("access"), ACCESS["unconfirmed"])))
        if e.get("url"):
            lines.append("  " + e["url"])
        for b in e.get("bullets", []):
            lines.append("    * " + b)
        lines.append("")
    if n > MAX_LISTED:
        lines.append("...and %d more." % (n - MAX_LISTED))
    lines.append("Check each against its source page before approving.")
    if sheet_url:
        lines.append("Review queue: " + sheet_url)
    return subject, "\n".join(lines)


def send_mail(user, password, to, subject, body, server="smtp.gmail.com", port=465):
    msg = EmailMessage()
    msg["From"], msg["To"], msg["Subject"] = user, to, subject
    msg.set_content(body)
    with smtplib.SMTP_SSL(server, port, timeout=30) as s:
        s.login(user, password)
        s.send_message(msg)


def notify(entries, send, sheet_url=""):
    """Emails new entries once and marks them. Returns how many were included."""
    new = pending(entries)
    if not new:
        return 0
    send(*build_email(new, sheet_url))
    for e in new:
        e["emailed"] = True
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
        if not new:
            print("Nothing new to email.")
        else:
            subject, body = build_email(new, sheet)
            print("Subject: %s\n\n%s" % (subject, body))
        return
    user, pw, to = (os.environ.get(k) for k in ("SMTP_USER", "SMTP_PASS", "EMAIL_TO"))
    if not (user and pw and to):
        sys.exit("Set SMTP_USER, SMTP_PASS and EMAIL_TO. See the setup steps at the top of this file.")
    try:
        n = notify(entries, lambda s, b: send_mail(user, pw, to, s, b), sheet)
    except smtplib.SMTPAuthenticationError:
        sys.exit("Gmail refused the login. Use an App Password (not the normal password) and check SMTP_USER.")
    except (smtplib.SMTPException, OSError) as exc:
        sys.exit("Could not send the email: %s" % exc)
    if n:
        with open(a.file, "w") as f:
            json.dump(entries, f, indent=2)
            f.write("\n")
    print("Emailed %d candidate(s) to %s." % (n, to) if n else "Nothing new to email.")


if __name__ == "__main__":
    main()
