#!/usr/bin/env python3
"""Proof of concept: find new public laparoscopic datasets and propose entries.

Pipeline
  1. discover  - pull recent records from arXiv and Zenodo (free APIs, no keys)
  2. filter    - skip anything already seen or already in datasets.json
  3. extract   - ask Claude to decide if a record is a dataset release and to
                 write the 2-4 bullet entry, using ONLY the record's own text
  4. output    - append proposals to candidates.json (status: pending_review)

It never edits datasets.json. Your website reads candidates.json (or imports
find_candidates) and decides what to publish.

Usage
  python updater.py --dry-run              # discovery only, no API key needed
  ANTHROPIC_API_KEY=... python updater.py  # full run with Claude
  GEMINI_API_KEY=...    python updater.py --llm gemini   # full run, free tier
"""
import argparse
import datetime
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ATOM = "{http://www.w3.org/2005/Atom}"
MODEL = os.environ.get("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
USER_AGENT = "laparoscopic-dataset-updater/0.1 (research poc)"


# ---------- discovery ----------

def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError("HTTP %s from %s: %s" % (exc.code, url, detail)) from None


def parse_arxiv(xml_bytes):
    hits = []
    for e in ET.fromstring(xml_bytes).findall(ATOM + "entry"):
        url = e.findtext(ATOM + "id", "").strip()
        hits.append({
            "source": "arxiv",
            "source_id": "arxiv:" + url.rsplit("/abs/", 1)[-1],
            "title": " ".join(e.findtext(ATOM + "title", "").split()),
            "text": " ".join(e.findtext(ATOM + "summary", "").split()),
            "url": url,
            "date": e.findtext(ATOM + "published", "")[:10],
            "access": "unconfirmed",
        })
    return hits


def parse_zenodo(payload):
    hits = []
    for h in payload.get("hits", {}).get("hits", []):
        m = h.get("metadata", {})
        if (m.get("resource_type") or {}).get("type") not in ("dataset", "video", "image"):
            continue
        desc = html.unescape(re.sub(r"<[^>]+>", " ", m.get("description", "")))
        open_access = m.get("access_right") == "open"
        hits.append({
            "source": "zenodo",
            "source_id": "zenodo:%s" % h.get("id"),
            "title": m.get("title", "").strip(),
            "text": " ".join(desc.split()),
            "url": h.get("links", {}).get("self_html", ""),
            "date": m.get("publication_date", "")[:10],
            "access": "direct" if open_access else "unconfirmed",
            "license": (m.get("license") or {}).get("id", ""),
        })
    return hits


def fetch_arxiv(max_results=50):
    q = "(all:laparoscopic OR all:laparoscopy) AND (all:dataset OR all:benchmark)"
    params = urllib.parse.urlencode({
        "search_query": q, "sortBy": "submittedDate",
        "sortOrder": "descending", "max_results": max_results})
    return parse_arxiv(http_get("http://export.arxiv.org/api/query?" + params))


def fetch_zenodo(max_results=25):
    # Plain query and a small page size: Zenodo rejected the earlier, fancier
    # query with HTTP 400. Record types are filtered in parse_zenodo instead.
    params = urllib.parse.urlencode({
        "q": "laparoscopic", "sort": "mostrecent", "size": max_results})
    return parse_zenodo(json.loads(http_get("https://zenodo.org/api/records?" + params)))


def discover(days):
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    hits = []
    for name, fn in (("arxiv", fetch_arxiv), ("zenodo", fetch_zenodo)):
        try:
            hits += fn()
        except Exception as exc:  # one source failing should not stop the run
            print("warning: %s fetch failed: %s" % (name, exc), file=sys.stderr)
    return [h for h in hits if h["date"] >= cutoff]


# ---------- filtering ----------

def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def drop_known(hits, datasets, seen, candidates):
    names = {norm(d["name"]) for d in datasets}
    urls = {d["url"] for d in datasets if d.get("url")}
    done = set(seen) | {c["source_id"] for c in candidates}
    fresh = []
    for h in hits:
        if h["source_id"] in done or h["url"] in urls:
            continue
        if norm(h["title"]) in names:
            continue
        fresh.append(h)
    return fresh


# ---------- extraction ----------

def call_claude(prompt):
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        sys.exit("ANTHROPIC_API_KEY is not set. Use --dry-run to skip extraction.")
    body = json.dumps({"model": MODEL, "max_tokens": 600,
                       "messages": [{"role": "user", "content": prompt}]}).encode()
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=body, headers={
        "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            out = json.load(r)
    except urllib.error.HTTPError as exc:
        sys.exit("Claude API error %s: %s" % (exc.code, exc.read().decode("utf-8", "replace")[:300]))
    return "".join(b.get("text", "") for b in out["content"] if b.get("type") == "text")


def call_gemini(prompt):
    """Free alternative to call_claude. Plain generation, no web search."""
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        sys.exit("GEMINI_API_KEY is not set. Get a free key at https://aistudio.google.com/apikey")
    model = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
    url = "https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % model
    body = json.dumps({"contents": [{"role": "user", "parts": [{"text": prompt}]}],
                       "generationConfig": {"temperature": 0.1}}).encode()
    for attempt in range(4):
        req = urllib.request.Request(url, data=body, headers={
            "x-goog-api-key": key, "content-type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=int(os.environ.get("GEMINI_TIMEOUT", "40"))) as r:
                out = json.load(r)
            cands = out.get("candidates") or [{}]
            return "".join(p.get("text", "") for p in (cands[0].get("content") or {}).get("parts", []))
        except urllib.error.HTTPError as exc:
            if exc.code in (429, 503) and attempt < 3:  # busy or rate limited: wait and retry
                print("  Gemini busy (%s), retrying..." % exc.code, flush=True)
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError("Gemini API error %s: %s" % (exc.code, exc.read().decode("utf-8", "replace")[:600]))
        except (TimeoutError, urllib.error.URLError, OSError) as exc:  # slow or dropped connection
            if attempt < 3:
                print("  Gemini timed out, retrying...", flush=True)
                time.sleep(3)
                continue
            raise RuntimeError("Gemini did not respond: %s" % exc)


def build_prompt(hit, categories):
    return """You screen records for a directory of public laparoscopic surgery datasets.

Record
Title: %s
Source: %s
Text: %s

Decide whether this record RELEASES a laparoscopic video or image dataset (not a method paper that only uses existing data, and not a simulator or non-laparoscopic dataset).
Use ONLY facts stated in the text above. Do not add numbers or details from memory.

Reply with ONLY a JSON object:
{"is_dataset": true or false,
 "name": the dataset's name,
 "category": one of %s (closest fit),
 "bullets": [2 to 4 short factual strings: size, procedure, labels, what sets it apart]}
If it is not a dataset release, reply {"is_dataset": false}.""" % (
        hit["title"], hit["source"], hit["text"][:3000], json.dumps(categories))


def parse_reply(text):
    a, b = text.find("{"), text.rfind("}")
    if a == -1 or b == -1:
        return None
    try:
        return json.loads(text[a:b + 1])
    except json.JSONDecodeError:
        return None


def to_entry(hit, reply, categories, today):
    if not reply or reply.get("is_dataset") is not True:
        return None
    bullets = [x.strip() for x in reply.get("bullets", []) if isinstance(x, str) and x.strip()]
    if not (reply.get("name") and reply.get("category") in categories and 2 <= len(bullets) <= 4):
        return None
    return {"name": reply["name"].strip(), "url": hit["url"], "category": reply["category"],
            "access": hit["access"], "bullets": bullets, "status": "pending_review",
            "source": hit["source"], "source_id": hit["source_id"],
            "source_date": hit["date"], "found": today}


RELEASE_WORDS = re.compile(r"\b(dataset|data set|benchmark|corpus|we release|publicly available|open[- ]source)\b", re.I)


def looks_like_release(hit):
    """Cheap pre-check so the model only reads records that might release data.
    Zenodo records are already typed as datasets, so they always pass."""
    return hit["source"] == "zenodo" or bool(RELEASE_WORDS.search(hit["title"] + " " + hit["text"]))


def already_known(name, known):
    n = norm(name)
    return any(k == n or (len(n) >= 4 and (n in k or k in n)) for k in known if len(k) >= 4)


def find_candidates(datasets, seen, candidates, days=30, extract=call_claude,
                    limit=None, prefilter=True, log=print):
    """Importable entry point. Returns (new_entries, processed_source_ids).
    If the model fails partway, returns what was finished so far."""
    categories = sorted({d["category"] for d in datasets})
    today = datetime.date.today().isoformat()
    known = {norm(d["name"]) for d in datasets} | {norm(c["name"]) for c in candidates}
    entries, processed, todo = [], [], []
    for h in drop_known(discover(days), datasets, seen, candidates):
        if prefilter and not looks_like_release(h):
            processed.append(h["source_id"])  # screened out by the keyword check
        else:
            todo.append(h)
    if limit:
        todo = todo[:limit]  # the rest stay unscreened for the next run
    log("%d record(s) to screen." % len(todo))
    for i, h in enumerate(todo, 1):
        log("[%d/%d] screening: %s" % (i, len(todo), h["title"][:70]))
        try:
            reply = parse_reply(extract(build_prompt(h, categories)))
        except Exception as exc:  # keep what we have instead of losing the whole run
            log("Stopped early: %s" % exc)
            break
        processed.append(h["source_id"])
        entry = to_entry(h, reply, categories, today)
        if entry and already_known(entry["name"], known):
            entry = None  # already in the list under another title
        if entry:
            entries.append(entry)
            known.add(norm(entry["name"]))
        log("   -> %s" % (("PROPOSED: " + entry["name"]) if entry else "skip"))
    return entries, processed


# ---------- io ----------

def load(path, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(path, obj):
    with open(path, "w") as f:
        json.dump(obj, f, indent=2)
        f.write("\n")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", default="datasets.json", help="your current published list")
    ap.add_argument("--out", default="candidates.json")
    ap.add_argument("--state", default="seen.json", help="ids already screened")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--llm", choices=["claude", "gemini"], default="claude",
                    help="which model screens the records (gemini has a free tier)")
    ap.add_argument("--limit", type=int, default=None, help="screen at most N records this run")
    ap.add_argument("--no-prefilter", action="store_true", help="send every record to the model")
    ap.add_argument("--dry-run", action="store_true", help="discovery only; print records, no API key needed")
    a = ap.parse_args()

    datasets = load(a.list, {"datasets": []})["datasets"]
    seen, candidates = load(a.state, []), load(a.out, [])

    if a.dry_run:
        hits = drop_known(discover(a.days), datasets, seen, candidates)
        for h in hits:
            print("%s  %s  %s" % (h["date"], h["source_id"], h["title"]))
        passing = sum(looks_like_release(h) for h in hits)
        print("%d unscreened records, %d would go to the model after the keyword check" % (len(hits), passing))
        return

    extract = call_claude
    if a.llm == "gemini":
        delay = float(os.environ.get("GEMINI_DELAY", "6"))  # stay under free-tier requests per minute

        def extract(prompt):
            out = call_gemini(prompt)
            time.sleep(delay)
            return out
    entries, processed = find_candidates(datasets, seen, candidates, a.days, extract=extract,
                                         limit=a.limit, prefilter=not a.no_prefilter)
    save(a.out, candidates + entries)
    save(a.state, sorted(set(seen) | set(processed)))
    print("screened %d, proposed %d" % (len(processed), len(entries)))
    for e in entries:
        print("  +", e["name"], e["url"])


if __name__ == "__main__":
    main()
