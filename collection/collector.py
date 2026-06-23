#!/usr/bin/env python3
"""Vanguard PAI Deep Research collector (Phase 1.5).
Iterative collection that TERMINATES in a freeze. Open-web PAI only."""
import os, json, time, hashlib, requests, trafilatura
from datetime import datetime, timezone

SEARXNG = "http://localhost:8080/search"
OLLAMA  = "http://localhost:11434/api/generate"
SOURCES = "sources"
PROV    = os.path.join(SOURCES, "_provenance.jsonl")

# --- Collection bounds (hard stops — collection is not open-ended) ---
MAX_DEPTH        = 3      # rounds of query expansion
MAX_QUERIES      = 24     # total searches across all rounds
MAX_DOCS         = 60     # documents retained in the corpus
RELEVANCE_FLOOR  = 0.5    # discard documents the model scores below this
DOMAIN_DENYLIST  = set()  # add domains to exclude (e.g. low-quality aggregators)

def ask(model, prompt, system=""):
    r = requests.post(OLLAMA, json={"model": model, "system": system,
                                    "prompt": prompt, "stream": False,
                                    "options": {"temperature": 0.3}})
    r.raise_for_status()
    return r.json().get("response", "")

def plan_queries(brief, found_titles, n):
    """Gemma 4 proposes the next search queries. Returns a list of strings."""
    sys = ("You plan PAI/OSINT search queries for an authorized red-team "
           "assessment of a named system. Output ONLY a JSON array of short "
           "search-engine queries, no prose.")
    prompt = (f"Assessment brief:\n{brief}\n\n"
              f"Already found ({len(found_titles)}): {found_titles[:20]}\n\n"
              f"Propose {n} NEW, non-overlapping queries that widen technical, "
              f"procedural, and program/personnel coverage. JSON array only.")
    raw = ask("gemma4:12b-mlx", prompt, sys).strip()
    raw = raw[raw.find("["): raw.rfind("]") + 1]   # isolate the array
    try:    return json.loads(raw)[:n]
    except: return []

def score(brief, title, text):
    """Gemma 4 scores relevance 0.0-1.0. Returns a float."""
    sys = "Rate document relevance to the assessment brief. Output ONLY a number 0.0-1.0."
    out = ask("gemma4:e4b", f"Brief:\n{brief}\n\nDoc: {title}\n{text[:1500]}", sys)
    try:    return float(out.strip().split()[0])
    except: return 0.0

def search(query):
    r = requests.get(SEARXNG, params={"q": query, "format": "json"}, timeout=30)
    r.raise_for_status()
    return r.json().get("results", [])

def fetch_clean(url):
    """Fetch a page and extract main text. Returns clean text or None."""
    dl = trafilatura.fetch_url(url)
    return trafilatura.extract(dl, include_comments=False) if dl else None

def save(url, title, text, query, score_val):
    os.makedirs(SOURCES, exist_ok=True)
    h = hashlib.sha256(url.encode()).hexdigest()[:16]
    path = os.path.join(SOURCES, f"pai_{h}.md")
    with open(path, "w") as f:
        f.write(f"# {title}\n\n<!-- source: {url} -->\n\n{text}\n")
    with open(PROV, "a") as f:
        f.write(json.dumps({
            "file": os.path.basename(path), "url": url, "title": title,
            "query": query, "relevance": score_val,
            "collected_utc": datetime.now(timezone.utc).isoformat(),
            "sha256": hashlib.sha256(text.encode()).hexdigest(),
        }) + "\n")

def collect(brief):
    seen_urls, titles, queries_used, docs = set(), [], 0, 0
    pending = plan_queries(brief, [], 6)
    for depth in range(MAX_DEPTH):
        next_round = []
        for q in pending:
            if queries_used >= MAX_QUERIES or docs >= MAX_DOCS: break
            queries_used += 1
            print(f"[d{depth}] query: {q}")
            for res in search(q):
                url = res.get("url", "")
                dom = url.split("/")[2] if "://" in url else ""
                if not url or url in seen_urls or dom in DOMAIN_DENYLIST: continue
                seen_urls.add(url)
                text = fetch_clean(url)
                if not text or len(text) < 400: continue
                s = score(brief, res.get("title", ""), text)
                if s < RELEVANCE_FLOOR: continue
                save(url, res.get("title", url), text, q, s)
                titles.append(res.get("title", "")); docs += 1
                if docs >= MAX_DOCS: break
            time.sleep(1)   # be polite to upstream engines
        if queries_used >= MAX_QUERIES or docs >= MAX_DOCS: break
        pending = plan_queries(brief, titles, 6)   # expand for next round
    print(f"\nCollected {docs} documents across {queries_used} queries.")
    print(f"Provenance: {PROV}")

if __name__ == "__main__":
    import sys
    brief_path = sys.argv[1] if len(sys.argv) > 1 else "collection/brief.md"
    with open(brief_path) as f:
        collect(f.read())