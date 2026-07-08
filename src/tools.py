from crewai.tools import tool, BaseTool
from pydantic import BaseModel, Field
from typing import List, Type, Any
import networkx as nx
import json
import re
import os


# --- Annex B: KCAG minimum node cut over the real DAG ---
class KCAGSchema(BaseModel):
    # Agent passes ONE string: the path to the Stage 2 edge-list artifact.
    # Topology is derived from that file, NOT authored by the LLM.
    stage2_vectors_path: str = Field(
        default="outputs/stage2_vectors.json",
        description="Path to the structured Stage 2 edge list (JSON). "
                    "Do NOT hand-author nodes/edges; they are read from this file."
    )
 
# 1. Move the dictionary OUTSIDE the class
# difficulty -> base traversal probability
DIFF_PROB = {'LOW': 0.8, 'MEDIUM': 0.5, 'HIGH': 0.2}

class KCAGMinCutTool(BaseTool):
    name: str = Field(default="kcag_min_cut")
    description: str = Field(
        default="Read the Stage 2 edge list from disk, build the KCAG DiGraph, "
                "compute betweenness, run minimum node cut against EVERY goal, "
                "rank paths by traversal probability, and write kcag_report.json "
                "for Annex C ingestion. Topology comes from the Stage 2 artifact, "
                "not from agent input."
    )
    args_schema: Type[BaseModel] = KCAGSchema
 
    # difficulty -> base traversal probability
    # DIFF_PROB = {"LOW": 0.80, "MEDIUM": 0.50, "HIGH": 0.20}
 
    def _run(self, stage2_vectors_path: str = "outputs/stage2_vectors.json") -> str:
        # ---- 1. Load topology from the artifact (deterministic) -------------
        if not os.path.exists(stage2_vectors_path):
            return (f"ERROR: {stage2_vectors_path} not found. Stage 2 must emit a "
                    f"structured edge list before Annex B can run. Expected schema: "
                    f'{{"nodes":[{{"id","node_type","criticality"}}],'
                    f'"edges":[{{"source","target","technique","difficulty","effect","vec"}}]}}')
        try:
            data = json.load(open(stage2_vectors_path))
            raw_nodes = data["nodes"]
            raw_edges = data["edges"]
        except (json.JSONDecodeError, KeyError) as e:
            return f"ERROR: {stage2_vectors_path} malformed ({e}). Need keys 'nodes' and 'edges'."
 
        G = nx.DiGraph()
        for n in raw_nodes:
            nid = n["id"] if isinstance(n, dict) else getattr(n, "id")
            ntype = (n.get("node_type") if isinstance(n, dict) else getattr(n, "node_type", "technique"))
            crit = (n.get("criticality", 1) if isinstance(n, dict) else getattr(n, "criticality", 1))
            G.add_node(nid, type=ntype, criticality=int(crit))
 
        for e in raw_edges:
            src = e["source"] if isinstance(e, dict) else getattr(e, "source")
            tgt = e["target"] if isinstance(e, dict) else getattr(e, "target")
            diff = (e.get("difficulty", "MEDIUM") if isinstance(e, dict)
                    else getattr(e, "difficulty", "MEDIUM")).upper()
            prob = DIFF_PROB.get(diff, 0.50)
            G.add_edge(src, tgt,
                       technique=(e.get("technique", "") if isinstance(e, dict) else ""),
                       difficulty=diff,
                       probability=prob,
                       effect=(e.get("effect") if isinstance(e, dict) else None),
                       vec=(e.get("vec", "") if isinstance(e, dict) else ""))
 
        if G.number_of_nodes() == 0 or G.number_of_edges() == 0:
            return "ERROR: Graph is empty after loading artifact."
 
        # ---- 2. Identify sources and ALL goals ------------------------------
        sources = [n for n, d in G.in_degree() if d == 0]
        goals = [n for n, a in G.nodes(data=True) if a.get("type") == "goal"]
        if not sources:
            return "ERROR: No source node (in-degree 0) found."
        if not goals:
            return "ERROR: No goal node (node_type='goal') found."
        src = sources[0]
 
        # ---- 3. Path probability helper -------------------------------------
        def path_prob(path):
            p = 1.0
            for i in range(len(path) - 1):
                p *= G[path[i]][path[i + 1]]["probability"]
            return round(p, 5)
 
        # ---- 4. Min cut against EVERY goal; aggregate shared chokepoints ----
        objective_results = {}
        cut_frequency = {}
        all_paths_flat = []
        for goal in goals:
            if not nx.has_path(G, src, goal):
                objective_results[goal] = {"top_path": [], "top_path_prob": 0,
                                           "min_cut": [], "min_cut_size": 0, "path_count": 0}
                continue
            paths = list(nx.all_simple_paths(G, src, goal, cutoff=8))
            ranked = sorted(paths, key=path_prob, reverse=True)
            try:
                cut = nx.minimum_node_cut(G, src, goal)
            except Exception:
                cut = set()
            for c in cut:
                cut_frequency[c] = cut_frequency.get(c, 0) + 1
            top = ranked[0] if ranked else []
            objective_results[goal] = {
                "top_path": top,
                "top_path_prob": path_prob(top) if top else 0,
                "min_cut": sorted(cut),
                "min_cut_size": len(cut),
                "path_count": len(paths),
            }
            for pth in ranked[:10]:
                all_paths_flat.append({"path": pth, "probability": path_prob(pth), "objective": goal})
 
        # ---- 5. Betweenness: UNWEIGHTED for chokepoint structure ------------
        # (weight in networkx = distance; using criticality as weight inverts
        #  the meaning. Compute structural betweenness, then rank by criticality
        #  separately.)
        bc = nx.betweenness_centrality(G, normalized=True)
        bc_sorted = dict(sorted(bc.items(), key=lambda x: x[1], reverse=True))
 
        # ---- 6. Dominant chokepoint = cut node reaching the MOST goals ------
        # minimum_node_cut returns the cut nearest each goal, so an upstream
        # chokepoint is only counted once. Credit each cut node for every goal
        # reachable FROM it (transitive dominance).
        goal_set = set(goals)
        cut_reach = {}
        for c in cut_frequency:
            reachable_goals = nx.descendants(G, c) & goal_set
            # a node that IS a goal counts itself too
            if c in goal_set:
                reachable_goals = reachable_goals | {c}
            cut_reach[c] = len(reachable_goals)
        if cut_reach:
            dominant_node = max(cut_reach.items(), key=lambda x: x[1])[0]
            dominant_count = cut_reach[dominant_node]
        else:
            dominant_node, dominant_count = (None, 0)
 
        # ---- 7. Highest-RISK priority path (highest probability, not lowest cost)
        all_paths_flat.sort(key=lambda x: x["probability"], reverse=True)
        priority_path = all_paths_flat[0] if all_paths_flat else None
 
        # ---- 8. Emit kcag_report.json for Annex C ---------------------------
        report = {
            "graph_stats": {"nodes": G.number_of_nodes(),
                            "edges": G.number_of_edges(),
                            "objectives": len(goals)},
            "minimum_cut": {
                "dominant_cut_node": dominant_node,
                "objectives_cut_by_dominant": dominant_count,
                "cut_frequency": cut_frequency,
                "cut_goal_reach": cut_reach,
                "aggregate_cut_nodes": sorted(cut_frequency.keys()),
                "aggregate_cut_size": len(cut_frequency),
            },
            "betweenness_centrality": {k: round(v, 5) for k, v in bc_sorted.items()},
            "priority_path": priority_path,
            "top_paths": all_paths_flat[:15],
            "objective_results": objective_results,
        }
        os.makedirs("outputs", exist_ok=True)
        with open("outputs/kcag_report.json", "w") as f:
            json.dump(report, f, indent=2)
 
        # ---- 9. Human-readable summary --------------------------------------
        top_bc = list(bc_sorted.items())
        bc_line = "n/a"
        if len(top_bc) >= 2 and top_bc[1][1] > 0:
            bc_line = f"{top_bc[0][0]} = {top_bc[0][1]:.4f} ({top_bc[0][1]/top_bc[1][1]:.1f}x next)"
        elif top_bc:
            bc_line = f"{top_bc[0][0]} = {top_bc[0][1]:.4f}"
 
        lines = [
            "=== ANNEX B: KCAG MIN-CUT ANALYSIS ===",
            f"Graph: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges, {len(goals)} objectives",
            f"Dominant min-cut node: {dominant_node} (cuts {dominant_count} of {len(goals)} objectives)",
            f"Aggregate min-cut size (all objectives): {len(cut_frequency)}",
            f"Top betweenness: {bc_line}",
        ]
        if priority_path:
            lines.append(f"Priority path (highest probability P={priority_path['probability']}):")
            lines.append(f"  {' -> '.join(priority_path['path'])}  [{priority_path['objective']}]")
        lines.append("Report written: outputs/kcag_report.json")
        lines.append("STATUS: SUCCESS")
        return "\n".join(lines)
 
 
kcag_min_cut = KCAGMinCutTool()

@tool("verify_corpus_lock")
def verify_corpus_lock(_: str = "") -> str:
    """Gate 1: re-hash sources/ against the frozen manifest. Returns PASS or a
    HALT report. This is a deterministic check, not a description task."""
    import os, re, json, hashlib
    src, manifest = "sources", "sources/corpus_manifest.md"

    def inventory(s):
        return sorted(f for f in os.listdir(s)
                      if f.endswith((".md", ".txt", ".json", ".pdf"))
                      and not f.startswith("_") and f != "corpus_manifest.md")

    frozen = json.loads(re.search(r'```json\s*(\{.*\})\s*```',
                  open(manifest).read(), re.S).group(1))
    frozen_map = {e["file"]: e["sha256"] for e in frozen["files"]}
    current = {}
    for fn in inventory(src):
        with open(os.path.join(src, fn), "rb") as fh:
            current[fn] = hashlib.sha256(fh.read()).hexdigest()

    missing = sorted(set(frozen_map) - set(current))
    added   = sorted(set(current) - set(frozen_map))
    changed = sorted(f for f in (set(frozen_map) & set(current))
                     if frozen_map[f] != current[f])
    if missing or added or changed:
        return (f"CORPUS LOCK VIOLATION — HALT.\n"
                f"missing: {missing}\nadded: {added}\nchanged: {changed}")
    return f"CORPUS LOCK VERIFIED: {len(current)} files match frozen manifest."

@tool("read_corpus_chunk")
def read_corpus_chunk(chunk_index: str = "0") -> str:
    """Return one pre-assembled chunk of the locked corpus.
    Chunks are built from all 64 source files before crew kickoff.
    Call with chunk_index '0' through N-1. The response tells you total chunks."""
    import json
    data = json.load(open("corpus-index/corpus_chunks.json"))
    chunks = data["chunks"]
    total = data["total"]
    try:
        idx = int(chunk_index)
    except ValueError:
        return f"ERROR: chunk_index must be an integer string. Got: {chunk_index}"
    if idx < 0 or idx >= total:
        return (f"ERROR: chunk_index {idx} out of range. "
                f"Valid range: 0 to {total-1}.")
    return (f"[CHUNK {idx+1} of {total} | "
            f"{data['files']} source files total]\n\n{chunks[idx]}")

@tool("extract_to_scratch")
def extract_to_scratch(chunk_index_and_findings: str) -> str:
    """Append structured findings from one chunk to the extraction scratchpad.
    Input format: first line is the chunk index, remaining lines are the
    extracted findings (named systems, personnel, exercises, interfaces, etc.)
    for that chunk. Call once per chunk after reading it."""
    import os
    os.makedirs("outputs", exist_ok=True)
    lines = chunk_index_and_findings.split("\n", 1)
    idx = lines[0].strip()
    findings = lines[1] if len(lines) > 1 else ""
    with open("outputs/_stage0_scratch.md", "a") as f:
        f.write(f"\n## Extraction — chunk {idx}\n{findings}\n")
    return f"Chunk {idx} findings appended to scratchpad."

@tool("read_scratch")
def read_scratch(trigger: str) -> str:
    """Return the full accumulated extraction scratchpad.
    You MUST pass the string 'EXECUTE' as the trigger argument."""
    if trigger != "EXECUTE":
         return "ERROR: You must pass the string 'EXECUTE' to read the scratchpad."
    try:
        return open("outputs/_stage0_scratch.md").read()
    except FileNotFoundError:
        return "[scratchpad empty — no extractions recorded]"
    
@tool("verify_and_fix_stage2")
def verify_and_fix_stage2(_: str = "") -> str:
    """Read outputs/stage2.md, verify EVERY framework ID across all schemas,
    auto-correct hallucinated IDs via keyword search, and FAIL on any
    [GAP]/[UNMAPPED] marker or category-mismatched SPARTA ID.
 
    A FAIL blocks Annex B. This is mechanical, not analytical.
    """
    try:
        idx = json.load(open("corpus-index/technique_index.json"))
    except FileNotFoundError:
        return "ERROR: corpus-index/technique_index.json not found — cannot verify."
    try:
        stage2 = open("outputs/stage2.md").read()
    except FileNotFoundError:
        return "ERROR: outputs/stage2.md not found — Stage 2 has not been written yet."
 
    # All framework ID schemas — note SPARTA prefixes split into ATTACK vs DEFENSE
    SPARTA_ATTACK = r'(?:REC|IA|EX|EXF|LM|PER|IMP|RD)-\d{4}(?:\.\d{1,2})?'
    SPARTA_DEFENSE = r'DE-\d{4}(?:\.\d{1,2})?'
    ID_PATTERN = (
        r'\b('
        r'T\d{4}(?:\.\d{3})?'          # ATT&CK Enterprise/ICS
        r'|CAPEC-\d+'                  # CAPEC
        r'|AML\.T\d{4}(?:\.\d{3})?'    # ATLAS
        r'|EMB\.[A-Z]\d{3,4}'          # EMB3D
        r'|EAC-?\d+|EAC\d+'            # Engage
        r'|SV-\d+-\d+'                 # SPARTA legacy SV form
        r'|' + SPARTA_ATTACK +         # SPARTA attack TTPs
        r'|' + SPARTA_DEFENSE +        # SPARTA defenses (category check below)
        r')\b'
    )
 
    STOPWORDS = {
        'the','a','an','is','are','was','were','be','been','being','have','has',
        'had','do','does','did','will','would','could','should','may','might',
        'can','of','in','on','at','to','for','and','or','but','not','with',
        'from','by','as','this','that','it','its','via','into','over','through',
        'across','any','all','each','which','who','when','where','how','what',
        'used','use','using','allow','allows','provide','enables','within',
        'system','data','layer','attack','network','adversary','target','access',
    }
 
    all_ids = list(dict.fromkeys(re.findall(ID_PATTERN, stage2)))
    corrected_text = stage2
    changes = []
 
    # ---- 1. [GAP] / [UNMAPPED] markers are FAIL conditions, not invisible ---
    gap_markers = re.findall(r'\[(GAP|UNMAPPED)\]', stage2)
    for marker in gap_markers:
        changes.append(f"UNRESOLVED [{marker}] marker present — vector lacks a grounded ID")
 
    # ---- 2. Per-ID verification + auto-correction ---------------------------
    for tid in all_ids:
        rec = idx.get(tid.upper())
 
        # 2a. SPARTA category check: DE- is a DEFENSE, not an attack technique
        if re.match(SPARTA_DEFENSE, tid):
            tag = (f"{tid} [CATEGORY ERROR: SPARTA DE- is a DEFENSE/countermeasure ID, "
                   f"not an attack technique. For PNT/GPS spoofing use EX-0014.04. "
                   f"Resolve before Annex B]")
            corrected_text = corrected_text.replace(tid, tag, 1)
            changes.append(f"UNRESOLVABLE {tid} -> SPARTA defense ID used as attack technique")
            continue
 
        if rec:
            changes.append(f"VERIFIED     {tid} -> {rec['name']} [{rec['framework']}]")
            continue
 
        # 2b. hallucinated ID — keyword search the surrounding context
        m = re.search(re.escape(tid), stage2)
        if not m:
            continue
        start = max(0, m.start() - 600)
        context = stage2[start:m.end() + 300]
        words = [w.lower() for w in re.findall(r'\b[a-zA-Z]{5,}\b', context)
                 if w.lower() not in STOPWORDS
                 and not re.match(r'^(T\d{4}|CAPEC|AML|EMB|EAC|SV|DE|EX)', w)]
 
        scores = {}
        for iid, entry in idx.items():
            searchable = (entry['name'] + ' ' + entry.get('description', '')).lower()
            score = sum(1 for w in words[:25] if w in searchable)
            if score > 0:
                scores[iid] = (score, entry)
 
        if not scores:
            tag = (f"{tid} [UNRESOLVABLE: no index match — vector concept may be "
                   f"hallucinated; human review required before Annex B]")
            corrected_text = corrected_text.replace(tid, tag, 1)
            changes.append(f"UNRESOLVABLE {tid} -> no keyword match; concept may be hallucinated")
            continue
 
        best_id, (score, best) = max(scores.items(), key=lambda x: x[1][0])
        conf = "HIGH" if score >= 4 else "MEDIUM" if score >= 2 else "LOW"
        tag = (f"{best['id']} [AUTO-CORRECTED from {tid} | {best['name']} | "
               f"{best['framework']} | keyword-score: {score} | conf: {conf}]")
        corrected_text = corrected_text.replace(tid, tag, 1)
        changes.append(f"AUTO-CORRECTED {tid} -> {best['id']}: {best['name']} "
                       f"[{best['framework']}] score={score} conf={conf}")
 
    # ---- 3. Malformed framework-ID sweep ------------------------------------
    MALFORMED = re.findall(
        r'\b(A\d{1,2}|ATLAS-[A-Za-z][A-Za-z-]+|CAPEC-[A-Za-z]+|AML-[A-Za-z]+)\b',
        stage2)
    for bad in dict.fromkeys(MALFORMED):
        corrected_text = corrected_text.replace(
            bad, f"{bad} [MALFORMED ID — not a valid framework identifier; "
                 f"resolve to Txxxx / CAPEC-nnn / AML.Tnnn or flag GAP]", 1)
        changes.append(f"UNRESOLVABLE {bad} -> malformed framework ID")
 
    os.makedirs("outputs", exist_ok=True)
    with open("outputs/stage2_corrected.md", "w") as f:
        f.write("<!-- AUTO-CORRECTED BY verify_and_fix_stage2 -->\n\n")
        f.write(corrected_text)
 
    verified = [c for c in changes if c.startswith("VERIFIED")]
    auto_fixed = [c for c in changes if c.startswith("AUTO-CORRECTED")]
    unresolvable = [c for c in changes if c.startswith("UNRESOLVABLE")]
    unresolved_markers = [c for c in changes if c.startswith("UNRESOLVED")]
 
    # ---- 4. PASS only if truly clean ----------------------------------------
    blocking = unresolvable + unresolved_markers
    if blocking:
        status = "FAIL — Annex B BLOCKED until resolved"
    elif not all_ids and not gap_markers:
        status = "FAIL — no framework IDs found; Stage 2 may be ungrounded"
    else:
        status = "PASS"
 
    report = [
        "=== ID VERIFICATION & AUTO-CORRECTION REPORT ===",
        f"IDs found: {len(all_ids)} | Verified: {len(verified)} | "
        f"Auto-corrected: {len(auto_fixed)} | Unresolvable: {len(unresolvable)} | "
        f"[GAP]/[UNMAPPED] markers: {len(gap_markers)}",
        "",
        "--- VERIFIED (no change) ---",
        *([f"  {c}" for c in verified] or ["  (none)"]),
        "",
        "--- AUTO-CORRECTED (review recommended) ---",
        *([f"  {c}" for c in auto_fixed] or ["  (none)"]),
        "",
        "--- BLOCKING ISSUES (human review before Annex B) ---",
        *([f"  {c}" for c in blocking] or ["  (none)"]),
        "",
        "Corrected output: outputs/stage2_corrected.md",
        f"STATUS: {status}",
    ]
    return "\n".join(report) + "\n\n=== CORRECTED STAGE 2 VECTORS ===\n" + corrected_text

# ============================================================================
#  DETERMINISTIC STAGE 2 GATE  (plain Python — NOT a CrewAI tool)
#  Add to src/tools.py. Called directly from src/crew.py between crews.
#  Single function, single return contract: {"is_valid": bool, ...}
# ============================================================================
def verify_stage2_vectors(vectors_path: str = "outputs/stage2_vectors.json",
                          index_path: str = "corpus-index/technique_index.json") -> dict:
    """Deterministically verify every technique ID in the Stage 2 attack GRAPH
    (not the prose) against the indexed corpus. This is the enforcement gate:
    crew.py raises on is_valid=False and never builds the downstream crew.

    Verifies the authoritative artifact (stage2_vectors.json) — the file Annex B
    actually consumes — so prose/graph drift cannot pass unverified IDs to the KCAG.

    Returns:
      {
        "is_valid": bool,
        "status": "PASS" | "FAIL",
        "checked": int,
        "invalid_edges": [ {edge_index, source, target, technique, reason, suggestion} ],
        "gap_edges":     [ {edge_index, source, target, technique} ],
        "summary": str
      }
    Does NOT mutate the graph. Corrections are advisory (suggestion field only).
    """
    import json, os, re

    result = {"is_valid": False, "status": "FAIL", "checked": 0,
              "invalid_edges": [], "gap_edges": [], "summary": ""}

    if not os.path.exists(vectors_path):
        result["summary"] = f"{vectors_path} not found — Stage 2 did not emit an edge list."
        return result
    if not os.path.exists(index_path):
        result["summary"] = f"{index_path} not found — cannot verify."
        return result

    try:
        data = json.load(open(vectors_path))
        index = json.load(open(index_path))
    except json.JSONDecodeError as e:
        result["summary"] = f"JSON parse error: {e}"
        return result

    edges = data.get("edges")
    if not isinstance(edges, list):
        result["summary"] = "edge list missing 'edges' array."
        return result

    # countermeasure-class prefixes must not appear as ATTACK technique IDs
    def is_countermeasure(tid):
        u = tid.upper()
        return u.startswith("DE-") or u.startswith("CM")

    GAP_MARKERS = {"[GAP]", "[UNMAPPED]", "", "NONE", "N/A"}

    def keyword_suggest(text, k=3):
        STOP = {'the','a','an','of','in','on','to','for','and','or','with','from',
                'by','as','via','into','attack','technique','system','data','access',
                'adversary','target','network','layer','using','use','used'}
        toks = [w for w in re.findall(r'[a-z0-9]{3,}', text.lower()) if w not in STOP]
        scored = []
        for v in index.values():
            hay = (v.get("name","") + " " + v.get("description","")).lower()
            score = sum(1 for t in set(toks) if t in hay)
            if score:
                scored.append((score, v["id"], v.get("name","")))
        scored.sort(reverse=True)
        return [{"id": i, "name": n, "score": s} for s, i, n in scored[:k]]

    for i, e in enumerate(edges):
        tid = str(e.get("technique", "")).strip()
        result["checked"] += 1
        ctx = f"{e.get('source','')} {e.get('target','')} {e.get('effect','') or ''}"

        if tid.upper() in GAP_MARKERS or tid == "":
            result["gap_edges"].append({
                "edge_index": i, "source": e.get("source"),
                "target": e.get("target"), "technique": tid or "(empty)"})
            continue

        if is_countermeasure(tid):
            result["invalid_edges"].append({
                "edge_index": i, "source": e.get("source"), "target": e.get("target"),
                "technique": tid,
                "reason": "countermeasure/defense ID used as attack technique",
                "suggestion": keyword_suggest(ctx)})
            continue

        if tid.upper() not in index:
            result["invalid_edges"].append({
                "edge_index": i, "source": e.get("source"), "target": e.get("target"),
                "technique": tid,
                "reason": "technique ID not found in corpus index",
                "suggestion": keyword_suggest(ctx)})

    n_bad = len(result["invalid_edges"])
    n_gap = len(result["gap_edges"])

    if n_bad == 0 and n_gap == 0:
        result["is_valid"] = True
        result["status"] = "PASS"
        result["summary"] = f"PASS — {result['checked']} edges verified, all IDs resolve."
    else:
        result["is_valid"] = False
        result["status"] = "FAIL"
        result["summary"] = (f"FAIL — {result['checked']} edges checked, "
                             f"{n_bad} invalid ID(s), {n_gap} [GAP]/unmapped edge(s). "
                             f"Annex B blocked.")
    return result

@tool("write_stage2_vectors")
def write_stage2_vectors(vectors_json: str) -> str:
    """Validate and write the Stage 2 structured edge list to
    outputs/stage2_vectors.json for Annex B (KCAG) consumption.

    Input: a JSON object with 'nodes' and 'edges'.
      nodes[]: {id, node_type, criticality}
        node_type in {privilege, technique, property, countermeasure, goal}
      edges[]: {source, target, technique, difficulty, effect, vec}
        difficulty in {LOW, MEDIUM, HIGH}

    Rejects malformed graphs (no goal, no entry node, dangling edges,
    bad enums) so Annex B never runs on a broken topology.
    """
    import json, os

    VALID_TYPES = {"privilege", "technique", "property", "countermeasure", "goal"}
    VALID_DIFF = {"LOW", "MEDIUM", "HIGH"}

    try:
        data = json.loads(vectors_json)
    except json.JSONDecodeError as e:
        return f"REJECTED: input is not valid JSON ({e}). Nothing written."

    nodes = data.get("nodes")
    edges = data.get("edges")
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return "REJECTED: JSON must contain 'nodes' (list) and 'edges' (list). Nothing written."

    errors = []
    node_ids = set()
    for i, n in enumerate(nodes):
        if not isinstance(n, dict) or "id" not in n:
            errors.append(f"node[{i}] missing 'id'"); continue
        nid = n["id"]
        if nid in node_ids:
            errors.append(f"duplicate node id '{nid}'")
        node_ids.add(nid)
        nt = n.get("node_type")
        if nt not in VALID_TYPES:
            errors.append(f"node '{nid}' has invalid node_type '{nt}' (must be one of {sorted(VALID_TYPES)})")
        crit = n.get("criticality", 1)
        if not isinstance(crit, int) or not (1 <= crit <= 10):
            errors.append(f"node '{nid}' criticality must be int 1-10, got {crit}")

    for i, e in enumerate(edges):
        if not isinstance(e, dict) or "source" not in e or "target" not in e:
            errors.append(f"edge[{i}] missing source/target"); continue
        if e["source"] not in node_ids:
            errors.append(f"edge[{i}] source '{e['source']}' is not a declared node")
        if e["target"] not in node_ids:
            errors.append(f"edge[{i}] target '{e['target']}' is not a declared node")
        diff = str(e.get("difficulty", "MEDIUM")).upper()
        if diff not in VALID_DIFF:
            errors.append(f"edge[{i}] difficulty '{diff}' invalid (LOW|MEDIUM|HIGH)")

    goal_nodes = [n["id"] for n in nodes if isinstance(n, dict) and n.get("node_type") == "goal"]
    if not goal_nodes:
        errors.append("no node with node_type='goal' — Annex B needs at least one objective")

    # entry node: a node with no incoming edges
    targets = {e.get("target") for e in edges if isinstance(e, dict)}
    entry_nodes = [nid for nid in node_ids if nid not in targets]
    if not entry_nodes:
        errors.append("no entry node (every node has an incoming edge) — graph has no start")

    if errors:
        return ("REJECTED: edge list failed validation. Nothing written. Fix and resubmit:\n  - "
                + "\n  - ".join(errors))

    os.makedirs("outputs", exist_ok=True)
    with open("outputs/stage2_vectors.json", "w") as f:
        json.dump({"nodes": nodes, "edges": edges}, f, indent=2)

    return (f"WRITTEN: outputs/stage2_vectors.json | "
            f"{len(nodes)} nodes, {len(edges)} edges, {len(goal_nodes)} goal(s), "
            f"entry node(s): {entry_nodes}. Annex B may now build the KCAG.")

# --- lookup_technique: wire to your indexed MITRE/CAPEC/EMB3D/SPARTA corpus ---
@tool("lookup_technique")
def lookup_technique(query: str) -> str:
    """Resolve a technique by ID or keyword against the indexed corpus.

    Resolution order:
      1. Exact ID hit -> full record.
      2. ID-shaped miss OR keyword -> IDF-weighted token scoring across
         name + description, ranked by (distinct query tokens matched,
         total weighted score). Returns up to 8 matches with confidence.
      3. If no match clears the relevance floor -> [GAP] (never a guess).

    Attack lookups exclude countermeasure-class IDs (SPARTA DE-/CM, Engage
    EAC defensive) so a DEFENSE never surfaces as an attack technique.
    Pass intent='defense' to look up countermeasures instead.
    """
    import json, re, math

    idx = json.load(open("corpus-index/technique_index.json"))

    # ---- intent parsing: "query | defense" or default attack ---------------
    intent = "attack"
    raw = query
    if "|" in query:
        raw, maybe = query.rsplit("|", 1)
        if maybe.strip().lower() in ("defense", "defence", "countermeasure", "mitigation"):
            intent = "defense"
        raw = raw.strip()

    STOPWORDS = {
        'the','a','an','of','in','on','at','to','for','and','or','but','with',
        'from','by','as','via','into','attack','technique','system','data',
        'access','adversary','target','network','layer','model','ai','ml',
        'using','use','used','against','based','the',
    }

    def tokens(text):
        return [w for w in re.findall(r'[a-z0-9]{3,}', text.lower())
                if w not in STOPWORDS]

    # ---- countermeasure-class prefixes to exclude from attack lookups ------
    def is_countermeasure(rec):
        cid = rec.get("id", "").upper()
        fw = rec.get("framework", "").lower()
        if cid.startswith("DE-") or cid.startswith("CM"):
            return True
        # Engage EAC are defensive engagement activities
        if cid.startswith("EAC") or "engage" in fw:
            return True
        return False

    # ---- build IDF: rare tokens are worth more than common ones ------------
    # document frequency of each token across the whole corpus
    N = len(idx)
    df = {}
    corpus_tokens = {}
    for k, v in idx.items():
        toks = set(tokens(v.get("name", "") + " " + v.get("description", "")))
        corpus_tokens[k] = toks
        for t in toks:
            df[t] = df.get(t, 0) + 1

    def idf(t):
        # smoothed inverse document frequency
        return math.log((N + 1) / (df.get(t, 0) + 1)) + 1.0

    q = raw.strip().upper()

    # 1. exact ID hit
    if q in idx:
        return json.dumps(idx[q], indent=2)

    is_id_shaped = bool(re.match(
        r'^(T\d{4}(?:\.\d{3})?|CAPEC-\d+|EMB\.[A-Z]\d+|AML\.T\d{4}(?:\.\d{3})?'
        r'|SV-\d+-\d+|EAC-?\d+|(?:REC|IA|EX|EXF|LM|PER|IMP|RD|DE)-\d{4}(?:\.\d{1,2})?'
        r'|CM\d{4})$', q))

    q_toks = tokens(raw)
    # for an ID-shaped miss, strip the ID-fragment tokens (e.g. 'aml','t9999')
    if is_id_shaped:
        q_toks = [t for t in q_toks
                  if not re.match(r'^(t\d+|aml|capec|emb|sv|eac|rec|ia|ex|exf|lm|per|imp|rd|de|cm)\d*$', t)]

    if not q_toks:
        return json.dumps({"query": query,
            "result": "[GAP] no searchable keywords (ID not in index)" if is_id_shaped
                      else "[GAP] no searchable keywords",
            "action": "do not fabricate; log as [GAP] at the flagging stage"})

    name_toks_cache = {k: set(tokens(v.get("name", ""))) for k, v in idx.items()}

    scored = []
    for k, v in idx.items():
        if intent == "attack" and is_countermeasure(v):
            continue
        if intent == "defense" and not is_countermeasure(v):
            continue
        hay = corpus_tokens[k]
        name_toks = name_toks_cache[k]
        matched_distinct = 0
        weight = 0.0
        for t in set(q_toks):
            if t in name_toks:
                matched_distinct += 1
                weight += idf(t) * 2.0       # name match: double IDF
            elif t in hay:
                matched_distinct += 1
                weight += idf(t)             # description match: single IDF
        if matched_distinct > 0:
            scored.append((matched_distinct, round(weight, 3), v))

    if not scored:
        return json.dumps({"query": query,
            "result": "[GAP] no keyword match",
            "action": "do not fabricate; log as [GAP] at the flagging stage"})

    # rank: more distinct query tokens first, then higher IDF weight,
    # then shorter (more specific) name
    scored.sort(key=lambda x: (-x[0], -x[1], len(x[2].get("name", ""))))

    # No artificial weight floor: calibration against the 2269-entry corpus showed
    # no clean cut between "meaningful" and "generic" tokens (all searchable terms
    # fall in IDF 4.0-8.0). IDF weighting + distinct-token ranking already separate
    # signal from noise. [GAP] is reserved for the "no token matched anything" case,
    # handled by the `if not scored` branch above. Ambiguity is signalled via the
    # ranked list + confidence + multi-match note, NOT suppressed into [GAP].

    def confidence(distinct, weight):
        if distinct >= 2 and weight >= 6: return "HIGH"
        if distinct >= 2 or weight >= 5:  return "MEDIUM"
        return "LOW"

    top = scored[0]
    n_at_top = sum(1 for d, w, _ in scored if d == top[0] and abs(w - top[1]) < 0.01)

    return json.dumps({
        "query": raw, "intent": intent, "id_shaped_miss": is_id_shaped,
        "matches": [
            {"id": v["id"], "name": v["name"], "framework": v.get("framework", "?"),
             "distinct_tokens": d, "weight": w, "confidence": confidence(d, w)}
            for d, w, v in scored[:8]
        ],
        "note": ("multiple matches tied at top — review before selecting"
                 if n_at_top > 1 else "clear top match")
    }, indent=2)

@tool("verify_technique_ids")
def verify_technique_ids(stage_output: str) -> str:
    """Extract every technique ID from a stage output and verify each against
    the indexed corpus. Returns a structured PASS/FAIL report. Any ID not in
    the v18.1 index is flagged as hallucinated — must be corrected before the
    stage can proceed downstream. This is a deterministic index check, not
    a model judgment."""
    import re
    import json as _j
    idx = _j.load(open("corpus-index/technique_index.json"))
    pattern = r'\b(T\d{4}(?:\.\d{3})?|CAPEC-\d+|AML\.T\d+|EMB\.T\d+|EAC-\d+|SV-\d+-\d+)\b'
    found = list(dict.fromkeys(re.findall(stage_output if stage_output else "", pattern)))
    # findall arg order fix:
    found = list(dict.fromkeys(re.findall(pattern, stage_output or "")))
    if not found:
        return "WARNING: No technique IDs found in output — stage may be ungrounded."
    verified, gaps = [], []
    for tid in found:
        rec = idx.get(tid.upper())
        if rec:
            verified.append(f"  ✓ {tid} → {rec['name']} [{rec['framework']}]")
        else:
            gaps.append(f"  ✗ {tid} → [HALLUCINATED or wrong version — not in v18.1 index]")
    lines = [f"ID VERIFICATION REPORT — {len(found)} IDs checked"]
    lines.append(f"\nVERIFIED ({len(verified)}):")
    lines += verified
    if gaps:
        lines.append(f"\nFAILED — HALLUCINATED IDs ({len(gaps)}) — MUST CORRECT BEFORE PROCEEDING:")
        lines += gaps
        lines.append("\nSTATUS: FAIL")
    else:
        lines.append("\nSTATUS: PASS — all IDs grounded in v18.1 index")
    return "\n".join(lines)

# --- Annex B: KCAG minimum node cut over the real DAG ---

# --- Annex C: pgmpy five-layer BBN threat inference ---
@tool("bbn_threat_score")
def bbn_threat_score(cpd_config_json: str = "") -> str:
    """Construct an evidence-driven Bayesian threat model, run inference, and
    return a threat score, kill-chain phase estimate, and a CPD audit log.
 
    Unlike a flat risk-propagation model, this ingests Annex B KCAG priors and
    real conditional structure so the score reflects the computed attack graph,
    not a default constant.
 
    Input JSON (all keys optional; sensible NGC2 defaults applied):
      {
        "kcag_report_path": "outputs/kcag_report.json",   // Annex B handoff
        "adversary": {
            "capability_prior": [0.0, 0.05, 0.95],        // [hacktivist,criminal,nation-state]
            "tempo": "HIGH"                                // LOW|MEDIUM|HIGH
        },
        "defensive_posture": {                             // true=control active
            "mfa": true, "edr": false, "segmentation": false,
            "integrity_monitor": false, "email_filtering": true
        },
        "geopolitical_trigger_prior": 0.55,
        "evidence": {                                      // observed indicators
            "GeopoliticalTrigger": 1, "AdversaryCapability": 2,
            "PhishingAttempt": 1, "ScanningDetected": 1, "AuthAnomaly": 1
        }
      }
 
    Returns a human-readable report plus writes outputs/bbn_report.json.
    """
    from pgmpy.models import DiscreteBayesianNetwork
    from pgmpy.factors.discrete import TabularCPD
    from pgmpy.inference import VariableElimination
 
    PHASE_LABELS = {0: "RECON", 1: "INITIAL ACCESS", 2: "LATERAL / PIVOT", 3: "OBJECTIVE"}
    THRESHOLDS = [(0.20, "LOW"), (0.50, "ELEVATED"), (0.75, "HIGH"), (1.01, "CRITICAL")]
    AUDIT = []
 
    def log(node, value, source):
        AUDIT.append({"node": node, "value": value, "source": source})
        return value
 
    def level(score):
        for t, lbl in THRESHOLDS:
            if score < t:
                return lbl
        return "CRITICAL"
 
    # ---- Parse config (never silently fall back to a magic number) ----------
    cfg = {}
    if cpd_config_json and cpd_config_json.strip():
        try:
            cfg = json.loads(cpd_config_json)
        except json.JSONDecodeError as e:
            return f"ERROR: cpd_config_json is not valid JSON ({e}). Refusing to run on undefined input."
 
    adversary = cfg.get("adversary", {})
    cap_prior = adversary.get("capability_prior", [0.0, 0.05, 0.95])  # PRC default
    tempo = adversary.get("tempo", "HIGH")
    posture = cfg.get("defensive_posture",
                      {"mfa": True, "edr": False, "segmentation": False,
                       "integrity_monitor": False, "email_filtering": True})
    geo_prior = float(cfg.get("geopolitical_trigger_prior", 0.55))
    evidence = cfg.get("evidence", {})
 
    # ---- Ingest Annex B KCAG priors (the whole point of the handoff) --------
    kcag_path = cfg.get("kcag_report_path", "outputs/kcag_report.json")
    p_objective_base = 0.32  # fallback if no KCAG report present
    kcag_note = "KCAG report not found — using fallback objective prior 0.32"
    if os.path.exists(kcag_path):
        try:
            kcag = json.load(open(kcag_path))
            objs = kcag.get("objective_results", {})
            if objs:
                p_objective_base = max(
                    (o.get("top_path_prob", 0) for o in objs.values()), default=0.32)
                kcag_note = f"KCAG max objective path probability = {p_objective_base:.4f}"
        except Exception as e:
            kcag_note = f"KCAG report present but unreadable ({e}) — using fallback 0.32"
    log("KCAG.p_objective_base", p_objective_base, kcag_note)
 
    # ---- Defensive multiplier: more controls -> harder to advance -----------
    active = sum(1 for v in posture.values() if v)
    total = max(1, len(posture))
    dm = max(0.30, 1.0 - (active / total) * 0.70)
    log("DefensiveMultiplier", round(dm, 4),
        f"{active}/{total} controls active")
 
    # ---- Build the DAG ------------------------------------------------------
    # Layer 1 priors -> Layer 2 observables -> Layer 3 phase -> Layer 5 outcome
    model = DiscreteBayesianNetwork([
        ("AdversaryCapability", "PhishingAttempt"),
        ("OperationalTempo", "ScanningDetected"),
        ("AdversaryCapability", "KillChainPhase"),
        ("PhishingAttempt", "KillChainPhase"),
        ("ScanningDetected", "KillChainPhase"),
        ("AuthAnomaly", "KillChainPhase"),
        ("KillChainPhase", "IWEffectAchieved"),
        ("DefensivePosture", "IWEffectAchieved"),
        ("GeopoliticalTrigger", "IWEffectAchieved"),
    ])
 
    cpds = []
 
    # AdversaryCapability (root, 3 states)
    cap = [max(0.001, p) for p in cap_prior]
    s = sum(cap); cap = [p / s for p in cap]
    cpds.append(TabularCPD("AdversaryCapability", 3, [[cap[0]], [cap[1]], [cap[2]]]))
    log("AdversaryCapability", cap, "adversary.capability_prior")
 
    # OperationalTempo (root, 3 states)
    tempo_dist = {"LOW": [0.6, 0.3, 0.1], "MEDIUM": [0.2, 0.6, 0.2],
                  "HIGH": [0.1, 0.2, 0.7]}.get(tempo, [0.1, 0.2, 0.7])
    cpds.append(TabularCPD("OperationalTempo", 3, [[p] for p in tempo_dist]))
    log("OperationalTempo", tempo_dist, f"adversary.tempo={tempo}")
 
    # PhishingAttempt | AdversaryCapability  (real conditional rows)
    cpds.append(TabularCPD(
        "PhishingAttempt", 2,
        [[0.90, 0.50, 0.15],   # P(no phish) | hacktivist, criminal, nation-state
         [0.10, 0.50, 0.85]],  # nation-state phishing is high (APT hallmark)
        evidence=["AdversaryCapability"], evidence_card=[3]))
    log("PhishingAttempt|cap", [[0.90, 0.50, 0.15], [0.10, 0.50, 0.85]],
        "APT spear-phishing base rates")
 
    # ScanningDetected | OperationalTempo
    cpds.append(TabularCPD(
        "ScanningDetected", 2,
        [[0.95, 0.65, 0.25],
         [0.05, 0.35, 0.75]],
        evidence=["OperationalTempo"], evidence_card=[3]))
    log("ScanningDetected|tempo", [[0.95, 0.65, 0.25], [0.05, 0.35, 0.75]],
        "tempo-driven recon activity")
 
    # AuthAnomaly (root observable)
    cpds.append(TabularCPD("AuthAnomaly", 2, [[0.82], [0.18]]))
    log("AuthAnomaly", [0.82, 0.18], "credential-reuse base rate")
 
    # GeopoliticalTrigger (root)
    cpds.append(TabularCPD("GeopoliticalTrigger", 2,
                           [[1 - geo_prior], [geo_prior]]))
    log("GeopoliticalTrigger", [1 - geo_prior, geo_prior],
        "geopolitical_trigger_prior")
 
    # DefensivePosture (root, 3 states weak/moderate/strong from active count)
    frac = active / total
    dp = [max(0.05, 1 - frac), 0.0, max(0.05, frac)]
    dp[1] = max(0.0, 1 - dp[0] - dp[2]); s = sum(dp); dp = [p / s for p in dp]
    cpds.append(TabularCPD("DefensivePosture", 3, [[dp[0]], [dp[1]], [dp[2]]]))
    log("DefensivePosture", dp, f"{active}/{total} controls active")
 
    # KillChainPhase | cap(3) x phish(2) x scan(2) x auth(2) = 24 cols, 4 states
    def phase_probs(cap_i, phish, scan, auth):
        if cap_i == 2:    base = [0.25, 0.32, 0.28, 0.15]   # nation-state long-dwell
        elif cap_i == 1:  base = [0.45, 0.30, 0.18, 0.07]
        else:             base = [0.65, 0.25, 0.08, 0.02]
        if phish: base[0] -= 0.10; base[1] += 0.10
        if scan:  base[0] -= 0.08; base[1] += 0.08
        if auth:  base[1] -= 0.12; base[2] += 0.12          # auth anomaly => lateral
        base[2] *= dm
        base[3] *= dm * p_objective_base                     # KCAG-anchored
        base = [max(0.001, b) for b in base]
        t = sum(base)
        return [b / t for b in base]
 
    rows = [[], [], [], []]
    for ci in range(3):
        for ph in range(2):
            for sc in range(2):
                for au in range(2):
                    pr = phase_probs(ci, ph, sc, au)
                    for k in range(4):
                        rows[k].append(pr[k])
    cpds.append(TabularCPD(
        "KillChainPhase", 4, rows,
        evidence=["AdversaryCapability", "PhishingAttempt",
                  "ScanningDetected", "AuthAnomaly"],
        evidence_card=[3, 2, 2, 2]))
    log("KillChainPhase", "computed", "nation-state base + evidence updates + KCAG anchor")
 
    # IWEffectAchieved | phase(4) x posture(3) x geo(2) = 24 cols, 2 states
    PHASE_BASE = [0.005,
                  log("IWEffect|InitAccess", 0.08, "early-access ceiling"),
                  log("IWEffect|Lateral", 0.40, "KCAG lateral path rates"),
                  log("IWEffect|Objective",
                      round(min(0.85, p_objective_base * 2.2), 4),
                      "KCAG objective prob x convergence factor")]
 
    def iw_probs(phase, dposture, geo):
        p = PHASE_BASE[phase]
        if dposture == 2:   p *= 0.25      # strong defense
        elif dposture == 1: p *= 0.55      # moderate
        if geo:             p = min(0.99, p * 1.45)
        p = min(0.999, max(0.001, p))
        return [1 - p, p]
 
    no_, yes_ = [], []
    for ph in range(4):
        for dpz in range(3):
            for g in range(2):
                a, b = iw_probs(ph, dpz, g)
                no_.append(a); yes_.append(b)
    cpds.append(TabularCPD(
        "IWEffectAchieved", 2, [no_, yes_],
        evidence=["KillChainPhase", "DefensivePosture", "GeopoliticalTrigger"],
        evidence_card=[4, 3, 2]))
    log("IWEffectAchieved", "computed", "phase x posture x geopolitical")
 
    model.add_cpds(*cpds)
    if not model.check_model():
        return "ERROR: BBN failed validation (cyclic or malformed CPDs)."
 
    infer = VariableElimination(model)
 
    # ---- Filter evidence to valid nodes/states ------------------------------
    valid_nodes = set(model.nodes())
    ev = {k: int(v) for k, v in evidence.items() if k in valid_nodes}
 
    score = float(infer.query(["IWEffectAchieved"], evidence=ev).values[1])
    phase_dist = infer.query(["KillChainPhase"], evidence=ev).values
    phase_idx = int(phase_dist.argmax())
 
    # ---- Baseline (no evidence) for delta ----------------------------------
    base_score = float(infer.query(["IWEffectAchieved"]).values[1])
 
    report = {
        "threat_score": round(score, 4),
        "threat_level": level(score),
        "baseline_score": round(base_score, 4),
        "delta_from_baseline": round(score - base_score, 4),
        "likely_phase": PHASE_LABELS[phase_idx],
        "phase_distribution": {PHASE_LABELS[i]: round(float(phase_dist[i]), 4)
                               for i in range(4)},
        "evidence_applied": ev,
        "kcag_objective_prior": round(p_objective_base, 4),
        "defensive_multiplier": round(dm, 4),
        "cpd_audit_log": AUDIT,
    }
    os.makedirs("outputs", exist_ok=True)
    with open("outputs/bbn_report.json", "w") as f:
        json.dump(report, f, indent=2)
 
    lines = [
        "=== ANNEX C: BBN THREAT ASSESSMENT ===",
        f"Threat Score:  {score:.4f}  ({level(score)})",
        f"Baseline:      {base_score:.4f}  (delta {score-base_score:+.4f})",
        f"Likely Phase:  {PHASE_LABELS[phase_idx]}",
        f"KCAG prior:    {p_objective_base:.4f}   Defensive mult: {dm:.3f}",
        "Phase distribution:",
        *[f"  {PHASE_LABELS[i]:16s} {float(phase_dist[i]):.4f}" for i in range(4)],
        f"Evidence applied: {ev or '(none — baseline)'}",
        f"CPD audit entries: {len(AUDIT)} (full log in outputs/bbn_report.json)",
        "STATUS: SUCCESS",
    ]
    return "\n".join(lines)


# --- write_stage0_output / write_stage1_output: schema-validated Stage 0/1 artifacts ---
# Same contract as write_stage2_vectors: REJECTED (nothing written) or WRITTEN
# (with a short summary). Validation here delegates to the Pydantic models in
# src/schemas.py rather than hand-rolled checks, since those are the actual
# source of truth for the shape.

@tool("write_stage0_output")
def write_stage0_output(stage0_json: str) -> str:
    """Validate and write the Stage 0 Reverse IPB signatures to
    outputs/stage0_output.json for downstream (Stage 1 attribution, gate)
    consumption. The prose narrative still goes to outputs/stage0.md via
    output_file; this is the structured, machine-checkable counterpart.

    Input: a JSON object with 'signatures': a list of
      {signature_id, category, description, confidence, deceive_candidate, is_gap}
      category in {technical, procedural, cognitive, social_personnel}
      confidence in {HIGH, MEDIUM, LOW}

    Rejects malformed input (bad enum values, missing fields, duplicate
    signature_ids) so downstream stages never consume a broken artifact.

    Rejects more than MAX_SIGNATURES entries. This is a defense-in-depth
    ceiling, not the primary fix for truncated-JSON tool calls — if the
    agent's model truncates output before this tool ever sees valid JSON,
    that's a generation-length problem the task prompt must address (curate
    a top-N list) rather than something this tool can catch after the fact.
    This cap exists to stop an agent that ignores that prompt guidance from
    silently writing an oversized artifact that risks the same truncation
    failure on a future run or a smaller local model.
    """
    import json, os
    from pydantic import ValidationError
    from src.schemas import Stage0Output

    MAX_SIGNATURES = 25  # generous ceiling above the requested top-15 curation target

    try:
        data = json.loads(stage0_json)
    except json.JSONDecodeError as e:
        return f"REJECTED: input is not valid JSON ({e}). Nothing written."

    try:
        parsed = Stage0Output.model_validate(data)
    except ValidationError as e:
        return f"REJECTED: Stage 0 output failed schema validation. Nothing written.\n{e}"

    if len(parsed.signatures) > MAX_SIGNATURES:
        return (f"REJECTED: {len(parsed.signatures)} signatures exceeds the {MAX_SIGNATURES} "
                f"ceiling. Curate to the most analytically significant ~15 signatures rather "
                f"than transcribing every scratchpad entry — long JSON payloads risk truncation "
                f"during generation. Nothing written.")

    ids = [s.signature_id for s in parsed.signatures]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        return f"REJECTED: duplicate signature_id(s) {sorted(dupes)}. Nothing written."

    os.makedirs("outputs", exist_ok=True)
    with open("outputs/stage0_output.json", "w") as f:
        f.write(parsed.model_dump_json(indent=2))

    return (f"WRITTEN: outputs/stage0_output.json | "
            f"{len(parsed.signatures)} signature(s), {parsed.gap_count} flagged [GAP]. "
            f"Stage 1 may now build on this signature set.")


@tool("write_stage1_output")
def write_stage1_output(stage1_json: str) -> str:
    """Validate and write the Stage 1 three-layer decomposition to
    outputs/stage1_output.json for Stage 2 (attribution check) consumption.
    The prose narrative still goes to outputs/stage1.md via output_file;
    this is the structured, machine-checkable counterpart.

    Input: a JSON object with 'technical_nodes', 'procedural_nodes',
      'cognitive_nodes' (lists), and 'trust_boundaries' (list).
      technical_nodes[] / procedural_nodes[]:
        {component_id, layer, name, asset_control_levels, information_flows,
         downstream_dependencies, is_gap}
        layer must match the list it's in (technical nodes cannot claim
        layer='procedural' or 'cognitive', and vice versa).
      cognitive_nodes[]:
        {component_id, hierarchy_stage, feeds, corrupts, downstream_effect,
         detection_probability, is_center_of_gravity, is_gap}
        hierarchy_stage in {Data, Information, Knowledge, Understanding,
        Decision, Behavior}
        is_center_of_gravity is an ADVISORY flag marking the analyst's
        candidate touchpoint within this layer only. It is NOT the doctrinal
        COG (JP 5-0 / ADP 3-0 defines COG as domain-agnostic, not restricted
        to the cognitive layer) and NOT the graph-theoretic COG that Annex B
        computes from min-cut + betweenness over the full attack graph — that
        COG may land on a Technical or Procedural node instead. This tool
        never rejects based on how many (or how few) cognitive nodes carry
        this flag.
      trust_boundaries[]: {boundary_id, from_component, to_component, description}

    Rejects malformed input, duplicate component_ids across all three
    layers, and a technical/procedural node's layer not matching the list
    it was submitted in. Does NOT verify attribution to Stage 0 (that is
    the agent's responsibility per the task's attribution discipline) —
    this tool only enforces structural correctness.
    """
    import json, os
    from pydantic import ValidationError
    from src.schemas import Stage1Output, DecompositionLayer

    try:
        data = json.loads(stage1_json)
    except json.JSONDecodeError as e:
        return f"REJECTED: input is not valid JSON ({e}). Nothing written."

    # Pre-check layer-vs-list placement before full model validation, since
    # this is a cross-field consistency rule the model alone can't express
    # (each node knows its own layer, but not which list it arrived in).
    placement_errors = []
    for n in data.get("technical_nodes", []) or []:
        if isinstance(n, dict) and n.get("layer") not in (None, "technical"):
            placement_errors.append(
                f"technical_nodes contains component '{n.get('component_id')}' "
                f"with layer='{n.get('layer')}' (expected 'technical')")
    for n in data.get("procedural_nodes", []) or []:
        if isinstance(n, dict) and n.get("layer") not in (None, "procedural"):
            placement_errors.append(
                f"procedural_nodes contains component '{n.get('component_id')}' "
                f"with layer='{n.get('layer')}' (expected 'procedural')")
    if placement_errors:
        return ("REJECTED: node(s) placed in the wrong layer list. Nothing written:\n  - "
                + "\n  - ".join(placement_errors))

    try:
        parsed = Stage1Output.model_validate(data)
    except ValidationError as e:
        return f"REJECTED: Stage 1 output failed schema validation. Nothing written.\n{e}"

    # Defense-in-depth ceiling against oversized single-tool-call JSON —
    # same rationale as write_stage0_output's MAX_SIGNATURES: this doesn't
    # fix truncated generation (that's a task-prompt curation problem), it
    # stops an agent that ignores curation guidance from writing an artifact
    # that risks truncation on a future run or a smaller local model.
    MAX_TOTAL_NODES = 40
    total_nodes = (len(parsed.technical_nodes) + len(parsed.procedural_nodes)
                   + len(parsed.cognitive_nodes))
    if total_nodes > MAX_TOTAL_NODES:
        return (f"REJECTED: {total_nodes} total nodes across all layers exceeds the "
                f"{MAX_TOTAL_NODES} ceiling. Curate to the most architecturally significant "
                f"components rather than transcribing every scratchpad entry — long JSON "
                f"payloads risk truncation during generation. Nothing written.")

    all_ids = (
        [n.component_id for n in parsed.technical_nodes]
        + [n.component_id for n in parsed.procedural_nodes]
        + [n.component_id for n in parsed.cognitive_nodes]
    )
    dupes = {i for i in all_ids if all_ids.count(i) > 1}
    if dupes:
        return f"REJECTED: duplicate component_id(s) {sorted(dupes)} across layers. Nothing written."

    # NOTE ON is_center_of_gravity: this flags an analyst's candidate touchpoint
    # within the Layer 3 (cognitive) decomposition — it is NOT the doctrinal
    # Center of Gravity (JP 5-0 / ADP 3-0: domain-agnostic source of power,
    # not restricted to the cognitive layer) and NOT the graph-theoretic COG
    # that Annex B actually computes from min-cut size + betweenness
    # centrality over the full attack graph. A Technical- or Procedural-layer
    # node can be the true COG (e.g. Lockheed Lightning's CDL_WRITE, min-cut=1,
    # ~5.5x betweenness). Enforcing exactly one flagged cognitive node here
    # would reject structurally and doctrinally valid Stage 1 output, so this
    # is advisory only — never blocks the write.
    cog_flagged = parsed.flagged_cognitive_touchpoints()
    if len(cog_flagged) == 0:
        cog_note = "(none flagged — cognitive-layer candidate touchpoint not identified; the actual COG is determined graph-theoretically in Annex B and may sit in any layer)"
    elif len(cog_flagged) == 1:
        cog_note = cog_flagged[0].component_id
    else:
        cog_note = f"multiple flagged {[n.component_id for n in cog_flagged]} — advisory only, not rejected"

    os.makedirs("outputs", exist_ok=True)
    with open("outputs/stage1_output.json", "w") as f:
        f.write(parsed.model_dump_json(indent=2))

    return (f"WRITTEN: outputs/stage1_output.json | "
            f"{len(parsed.technical_nodes)} technical, {len(parsed.procedural_nodes)} procedural, "
            f"{len(parsed.cognitive_nodes)} cognitive node(s), {len(parsed.trust_boundaries)} trust "
            f"boundary(ies), {parsed.gap_count} flagged [GAP]. "
            f"Cognitive-layer candidate touchpoint: {cog_note}. "
            f"(Note: the graph-theoretic COG is computed by Annex B, not fixed here.) "
            f"Stage 2 may now build on this node inventory.")