#!/usr/bin/env python3
"""Dataset scout: a Claude agent that searches the web for new public
laparoscopic datasets and proposes list entries.

Unlike updater.py (fixed pipeline), the agent chooses its own searches, follows
leads, and checks the source pages. It prints every search as it happens, so it
works as a live demo.

It never edits datasets.json. Proposals are appended to candidates.json with
status "pending_review". Load that file into the review page to approve them.

Setup
  export ANTHROPIC_API_KEY=...      (web search must be enabled for your org in
                                     the Anthropic Console settings)
Usage
  python agent.py                   # look back 90 days
  python agent.py --days 365 --max-searches 25
"""
import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request

MODEL = os.environ.get("CLAUDE_MODEL", "claude-sonnet-5-5")
ACCESS = {"direct", "request", "unconfirmed"}


def call_api(messages, max_searches):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("ANTHROPIC_API_KEY is not set.")
    body = json.dumps({
        "model": MODEL,
        "max_tokens": 4000,
        "tools": [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_searches}],
        "messages": messages,
    }).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return json.load(r)
    except urllib.error.HTTPError as exc:
        sys.exit("Claude API error %s: %s" % (exc.code, exc.read().decode("utf-8", "replace")[:400]))


def build_prompt(datasets, days):
    cats = sorted({d["category"] for d in datasets})
    known = ", ".join(d["name"] for d in datasets)
    since = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    return """You are a research agent keeping a directory of public laparoscopic surgery datasets up to date.

Find datasets (video or image) released or first published since %s that are NOT already in this list:
%s

Search the web yourself: try arXiv, Zenodo, PhysioNet, Figshare, Hugging Face, Kaggle, Scientific Data, MICCAI/EndoVis challenges, and journal sites. Open the paper or data page before including anything.
Include a dataset only if it is laparoscopic (not robotic-only, endoscopic-only, or simulated), publicly obtainable (direct download or by request), and you confirmed the facts below on its page. Do not guess numbers; leave a fact out if the page does not state it.

When you are done, reply with ONLY a JSON array (at most 8 items, [] if nothing qualifies). Each item:
{"name": str, "url": https link to the paper or data page,
 "category": one of %s (closest fit),
 "access": "direct" (download without a form), "request" (form or agreement needed) or "unconfirmed",
 "bullets": [2 to 4 short factual strings: size, procedure, labels, what sets it apart]}""" % (
        since, known, json.dumps(cats))


def run_agent(prompt, max_searches, call=call_api, log=print):
    """Loop until the agent finishes. Returns its final text."""
    messages = [{"role": "user", "content": prompt}]
    searches, text = 0, ""
    for _ in range(12):
        resp = call(messages, max_searches)
        for block in resp.get("content", []):
            if block.get("type") == "server_tool_use":
                searches += 1
                log("  search %d: %s" % (searches, (block.get("input") or {}).get("query", "")))
        text = "".join(b.get("text", "") for b in resp.get("content", []) if b.get("type") == "text")
        if resp.get("stop_reason") == "pause_turn":
            messages.append({"role": "assistant", "content": resp["content"]})
            continue
        return text, searches
    return text, searches


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def parse_items(text):
    a, b = text.find("["), text.rfind("]")
    if a == -1 or b == -1:
        return []
    try:
        items = json.loads(text[a:b + 1])
    except json.JSONDecodeError:
        return []
    return items if isinstance(items, list) else []


def to_entries(items, datasets, existing, today):
    cats = {d["category"] for d in datasets}
    names = {norm(d["name"]) for d in datasets} | {norm(c["name"]) for c in existing}
    urls = {d["url"] for d in datasets if d.get("url")} | {c["url"] for c in existing}
    out = []
    for c in items:
        try:
            name, url, cat = c["name"].strip(), c["url"].strip(), c["category"]
            bullets = [b.strip() for b in c["bullets"] if isinstance(b, str) and b.strip()]
        except (KeyError, AttributeError, TypeError):
            continue
        if not (name and url.startswith("https://") and cat in cats and 2 <= len(bullets) <= 4):
            continue
        if norm(name) in names or url in urls:
            continue
        names.add(norm(name))
        urls.add(url)
        out.append({"name": name, "url": url, "category": cat,
                    "access": c.get("access") if c.get("access") in ACCESS else "unconfirmed",
                    "bullets": bullets, "status": "pending_review",
                    "source": "agent web search", "found": today})
    return out


def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", default="datasets.json")
    ap.add_argument("--out", default="candidates.json")
    ap.add_argument("--days", type=int, default=90)
    ap.add_argument("--max-searches", type=int, default=15)
    a = ap.parse_args()

    datasets = load(a.list, {"datasets": []})["datasets"]
    existing = load(a.out, [])
    print("Scouting for laparoscopic datasets released in the last %d days..." % a.days)
    text, n = run_agent(build_prompt(datasets, a.days), a.max_searches)
    entries = to_entries(parse_items(text), datasets, existing, datetime.date.today().isoformat())
    with open(a.out, "w") as f:
        json.dump(existing + entries, f, indent=2)
        f.write("\n")
    print("Ran %d searches. Proposed %d new dataset(s) for review." % (n, len(entries)))
    for e in entries:
        print("  +", e["name"], "-", e["url"])


if __name__ == "__main__":
    main()
