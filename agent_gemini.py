#!/usr/bin/env python3
"""Dataset scout, Gemini version: searches Google for new public laparoscopic
datasets and proposes list entries. Same output as agent.py (candidates.json,
status "pending_review"), so the review page works with either.

Gemini runs its own Google searches ("grounding"). The script prints the
queries it used, and marks each proposal "grounded" when the proposal's website
appeared among the search results. Ungrounded proposals deserve extra scrutiny.

Setup
  1. Get a free key at https://aistudio.google.com/apikey
  2. export GEMINI_API_KEY=...
Usage
  python agent_gemini.py                # look back 90 days
  python agent_gemini.py --days 365
Optional: GEMINI_MODEL (default gemini-3.8-flash)
"""
import argparse
import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import agent  # shares the prompt, validation and file helpers

MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")


def call_gemini(prompt):
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY is not set. Get a free key at https://aistudio.google.com/apikey")
    url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % MODEL
    body = json.dumps({
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "tools": [{"google_search": {}}],
        "generationConfig": {"temperature": 0.2},
    }).encode()
    req = urllib.request.Request(url, data=body, headers={
        "x-goog-api-key": key, "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:2000]
        if exc.code == 429:
            sys.exit("Gemini rate limit or free-tier quota reached. Wait a minute and retry, "
                     "or try again tomorrow.\n" + detail)
        sys.exit("Gemini API error %s: %s" % (exc.code, detail))


def parse_response(resp):
    """Returns (text, search_queries, source_domains)."""
    cands = resp.get("candidates") or []
    if not cands:
        return "", [], set()
    c = cands[0]
    text = "".join(p.get("text", "") for p in (c.get("content") or {}).get("parts", []))
    gm = c.get("groundingMetadata") or {}
    queries = list(gm.get("webSearchQueries") or [])
    domains = set()
    for chunk in gm.get("groundingChunks") or []:
        title = ((chunk.get("web") or {}).get("title") or "").lower().strip()
        if title:
            domains.add(title)
    return text, queries, domains


def host_of(url):
    h = (urllib.parse.urlparse(url).hostname or "").lower()
    return h[4:] if h.startswith("www.") else h


def mark_grounded(entries, domains):
    for e in entries:
        h = host_of(e["url"])
        e["grounded"] = bool(h) and any(d == h or h.endswith("." + d) or d.endswith("." + h)
                                        for d in domains)
    return entries


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", default="datasets.json")
    ap.add_argument("--out", default="candidates.json")
    ap.add_argument("--days", type=int, default=90)
    a = ap.parse_args()

    datasets = agent.load(a.list, {"datasets": []})["datasets"]
    existing = agent.load(a.out, [])
    print("Scouting with Gemini (%s) for datasets released in the last %d days..." % (MODEL, a.days))
    text, queries, domains = parse_response(call_gemini(agent.build_prompt(datasets, a.days)))
    for i, q in enumerate(queries, 1):
        print("  search %d: %s" % (i, q))
    entries = agent.to_entries(agent.parse_items(text), datasets, existing,
                               datetime.date.today().isoformat())
    for e in entries:
        e["source"] = "gemini google search"
    mark_grounded(entries, domains)
    with open(a.out, "w") as f:
        json.dump(existing + entries, f, indent=2)
        f.write("\n")
    print("Ran %d searches. Proposed %d new dataset(s) for review." % (len(queries), len(entries)))
    for e in entries:
        print("  +", e["name"], "-", e["url"], "" if e["grounded"] else "(source not in search results: check carefully)")


if __name__ == "__main__":
    main()
