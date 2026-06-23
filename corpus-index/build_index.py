#!/usr/bin/env python3
"""Build the unified technique lookup index for lookup_technique().
Parses ATT&CK (Enterprise/ICS/Mobile), CAPEC, EMB3D, SPARTA into one JSON map
keyed by canonical technique ID. Run once; re-run on reference updates."""
import os, json, re, openpyxl

RAW = "corpus-index/raw"
OUT = "corpus-index/technique_index.json"
index = {}   # ID -> {id, name, framework, description, tactics, xrefs}

def add(tid, name, framework, desc="", tactics=None, xrefs=None):
    tid = tid.strip().upper()
    index[tid] = {"id": tid, "name": (name or "").strip(),
                  "framework": framework, "description": (desc or "").strip()[:1200],
                  "tactics": tactics or [], "xrefs": xrefs or []}

def parse_attack(path, framework):
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    hdr = [str(h).strip().lower() if h else "" for h in next(rows)]
    col = {name: hdr.index(name) for name in
           ("id", "name", "description", "tactics") if name in hdr}
    for r in rows:
        tid = r[col["id"]] if "id" in col else None
        if not tid: continue
        tac = r[col["tactics"]] if "tactics" in col and r[col["tactics"]] else ""
        add(tid, r[col.get("name", 1)], framework,
            r[col["description"]] if "description" in col else "",
            [t.strip() for t in str(tac).split(",") if t.strip()])
    wb.close()

def parse_capec(path):
    blocks = re.split(r'(?m)^# (CAPEC-\d+):\s*', open(path).read())
    # split yields ['', 'CAPEC-1', 'title\n\n## Description\n...', 'CAPEC-10', ...]
    for i in range(1, len(blocks), 2):
        cid = blocks[i]
        body = blocks[i+1] if i+1 < len(blocks) else ""
        title = body.splitlines()[0].strip() if body else ""
        desc = ""
        m = re.search(r'## Description\s*(.+?)(?=\n#|\Z)', body, re.S)
        if m: desc = m.group(1)
        add(cid, title, "CAPEC", desc)

def parse_emb3d(path):
    d = json.load(open(path))
    objs = d.get("objects", [])
    for o in objs:
        if o.get("type") not in ("vulnerability", "course-of-action"): continue
        eid = next((r.get("external_id") for r in o.get("external_references", [])
                    if r.get("external_id")), None)
        if not eid: continue
        add(eid, o.get("name", ""), "EMB3D", o.get("description", ""))

def parse_sparta(path):
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb.active
    rows = ws.iter_rows(values_only=True)
    hdr = [str(h).strip() if h else "" for h in next(rows)]
    idx = {h: i for i, h in enumerate(hdr)}
    for r in rows:
        sid = r[idx.get("ID", 0)]
        if not sid: continue
        xref = r[idx.get("Related MITRE ATT&CK")] if "Related MITRE ATT&CK" in idx else ""
        xrefs = [x.strip() for x in re.split(r'[,\s]+', str(xref or "")) if x.strip().startswith("T")]
        add(sid, r[idx.get("Name", 1)], "SPARTA",
            r[idx.get("Description", 2)] or "", xrefs=xrefs)
    wb.close()

def parse_atlas(path):
    """ATLAS STIX: AML.Txxxx IDs live on attack-pattern objects (not vulnerability,
    unlike EMB3D). 170 techniques + 35 course-of-action mitigations."""
    d = json.load(open(path))
    for o in d.get("objects", []):
        if o.get("type") not in ("attack-pattern", "course-of-action"): continue
        aid = next((r.get("external_id") for r in o.get("external_references", [])
                    if str(r.get("external_id", "")).startswith("AML")), None)
        if not aid: continue
        add(aid, o.get("name", ""), "ATLAS", o.get("description", ""))

def parse_engage(path):
    """Engage attack_mapping.json: flat list of ATT&CK->Engage crosswalk objects.
    Keyed on eac_id (EAC activity). Normalizes EAC0011 -> EAC-0011 to match the
    protocol's hyphenated convention. Carries attack_id as a cross-reference."""
    seen = {}
    for m in json.load(open(path)):
        raw_id = m.get("eac_id", "")
        if not raw_id: continue
        eid = re.sub(r'^EAC(\d+)$', r'EAC-\1', raw_id)   # EAC0011 -> EAC-0011
        atk = m.get("attack_id")
        seen.setdefault(eid, {"name": m.get("eac", ""), "xrefs": set()})
        if atk: seen[eid]["xrefs"].add(atk)
    for eid, v in seen.items():
        add(eid, v["name"], "Engage", "", xrefs=sorted(v["xrefs"]))

def parse_capec_xml(path):
    """CAPEC-3 XML catalog (capec.mitre.org). Namespace-agnostic via local-name
    matching; streams with iterparse + el.clear() to handle the ~4MB file.
    Keys on <Attack_Pattern ID=.. Name=..> -> CAPEC-n."""
    import xml.etree.ElementTree as ET
    def lname(t): return t.rsplit('}', 1)[-1]
    for _, el in ET.iterparse(path, events=("end",)):
        if lname(el.tag) == "Attack_Pattern":
            cid, name = el.get("ID"), el.get("Name")
            if cid:
                desc = ""
                for c in el:
                    if lname(c.tag) == "Description":
                        desc = "".join(c.itertext()).strip(); break
                add(f"CAPEC-{cid}", name, "CAPEC", desc)
            el.clear()

def parse_sparta_stix(path):
    """SPARTA STIX 2.1 bundle (sparta.aerospace.org /download/STIX). Techniques are
    attack-pattern objects, countermeasures are course-of-action; both carry a
    SPARTA external_id (e.g. REC-0001, EX-0012, CM-xxxx)."""
    d = json.load(open(path))
    for o in d.get("objects", []):
        if o.get("type") not in ("attack-pattern", "course-of-action"): continue
        sid = next((r.get("external_id") for r in o.get("external_references", [])
                    if r.get("external_id")), None)
        if not sid: continue
        add(sid, o.get("name", ""), "SPARTA", o.get("description", ""))

def main():
    jobs = [
        ("enterprise-attack.xlsx", parse_attack, "ATT&CK-Enterprise"),
        ("ics-attack.xlsx",        parse_attack, "ATT&CK-ICS"),
        ("mobile-attack.xlsx",     parse_attack, "ATT&CK-Mobile"),
    ]
    for fn, fnc, fw in jobs:
        p = os.path.join(RAW, fn)
        if os.path.exists(p): fnc(p, fw); print(f"  parsed {fn}")
    # Single-arg parsers. Each entry maps a filename to its parser. CAPEC and SPARTA
    # support multiple source formats — the first existing file wins.
    single = [
        (["capec.md"], parse_capec),               # markdown form (if you have it)
        (["capec_raw.xml", "capec.xml"], parse_capec_xml),   # XML catalog form
        (["emb3d.json"], parse_emb3d),
        (["sparta.xlsx"], parse_sparta),           # Excel export form
        (["sparta.json"], parse_sparta_stix),      # STIX bundle form
        (["atlas.json"], parse_atlas),
        (["engage.json"], parse_engage),
    ]
    for names, fnc in single:
        for fn in names:
            p = os.path.join(RAW, fn)
            if os.path.exists(p):
                fnc(p); print(f"  parsed {fn}"); break
    json.dump(index, open(OUT, "w"), indent=2)
    # framework counts for sanity
    counts = {}
    for v in index.values():
        counts[v["framework"]] = counts.get(v["framework"], 0) + 1
    print(f"\nIndexed {len(index)} IDs -> {OUT}")
    for k, v in sorted(counts.items()): print(f"  {k}: {v}")

if __name__ == "__main__":
    main()