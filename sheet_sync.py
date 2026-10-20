#!/usr/bin/env python3
"""Add new dataset candidates to the Google Sheet review queue.

Reads candidates.json and appends every "pending_review" entry that is not in
the sheet yet as a new row (Status = pending_review). The reviewer changes the
Status cell to "published" or "rejected". Entries already synced are skipped.

One-time setup
  1. pip install gspread
  2. console.cloud.google.com: create a project, enable the "Google Sheets API",
     then Credentials > Create credentials > Service account. Open the account,
     Keys > Add key > JSON, and save the file somewhere private (not in this folder's git repo).
  3. Share the Google Sheet with the service account's email address (Editor).
  4. export GOOGLE_SERVICE_ACCOUNT_FILE=/path/to/key.json
     export SHEET_ID=1nbTdAMphc_MhrRNcTyN9YDU22vcXM3roOytFp9NgDXo   (the ID in the sheet's URL)

Usage
  python sheet_sync.py --dry-run    # show what would be added
  python sheet_sync.py              # add the rows
"""
import argparse
import json
import os
import re
import sys

DEFAULT_SHEET_ID = "1nbTdAMphc_MhrRNcTyN9YDU22vcXM3roOytFp9NgDXo"
ACCESS = {"direct": "Direct download", "request": "Request or agreement",
          "unconfirmed": "Terms not confirmed"}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def to_row(e):
    """Column order matches the sheet: Status, Name, Link, Category, Access,
    Details, Source, Date found, Reviewer notes."""
    return ["pending_review", e["name"], e.get("url", ""), e.get("category", ""),
            ACCESS.get(e.get("access"), ACCESS["unconfirmed"]),
            " • ".join(e.get("bullets", [])), e.get("source", ""), e.get("found", ""), ""]


def select(entries, sheet_names):
    """Entries still waiting, not yet synced, and not already listed in the sheet."""
    have = {norm(n) for n in sheet_names}
    return [e for e in entries
            if e.get("status") == "pending_review" and not e.get("synced") and norm(e["name"]) not in have]


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

    keyfile = os.environ.get("GOOGLE_SERVICE_ACCOUNT_FILE")
    sheet_id = os.environ.get("SHEET_ID", DEFAULT_SHEET_ID)
    if not keyfile:
        sys.exit("GOOGLE_SERVICE_ACCOUNT_FILE is not set. See the setup steps at the top of this file.")
    try:
        import gspread
    except ImportError:
        sys.exit("gspread is not installed. Run: pip install gspread")

    ws = gspread.service_account(filename=keyfile).open_by_key(sheet_id).sheet1
    new = select(entries, ws.col_values(2)[1:])
    if a.dry_run:
        print("Would add %d row(s):" % len(new))
        for e in new:
            print("  +", e["name"])
        return
    if new:
        ws.append_rows([to_row(e) for e in new], value_input_option="RAW")
    # Mark everything pending as synced, including ones already in the sheet.
    for e in entries:
        if e.get("status") == "pending_review":
            e["synced"] = True
    with open(a.file, "w") as f:
        json.dump(entries, f, indent=2)
        f.write("\n")
    print("Added %d row(s) to the sheet." % len(new))


if __name__ == "__main__":
    main()
