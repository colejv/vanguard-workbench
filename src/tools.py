from crewai.tools import tool, BaseTool
from pydantic import BaseModel, Field
from typing import List, Type, Any, Optional
import networkx as nx
import json
import re
import os
import math

from src import run_context


# --- Annex B: KCAG minimum node cut over the real DAG ---
class KCAGSchema(BaseModel):
    # Agent passes ONE string: the path to the Stage 2 edge-list artifact.
    # Topology is derived from that file, NOT authored by the LLM.
    # Default is None, not a literal path — a Python default evaluated at
    # import time would bake in whatever run (if any) happened to be active
    # then. None lets _run() resolve run_context.artifact_path() fresh on
    # every call, using whichever run is actually active right now.
    stage2_vectors_path: Optional[str] = Field(
        default=None,
        description="Path to the structured Stage 2 edge list (JSON). "
                    "Do NOT hand-author nodes/edges; they are read from this file. "
                    "Leave unset — it resolves to the current run's Stage 2 output automatically."
    )
 
# 1. Move the dictionary OUTSIDE the class
# difficulty -> configured heuristic traversal score (NOT a calibrated
# probability -- see TRAVERSAL_SCORE_BY_DIFFICULTY's own note below).
TRAVERSAL_SCORE_BY_DIFFICULTY = {'LOW': 0.8, 'MEDIUM': 0.5, 'HIGH': 0.2}

class KCAGMinCutTool(BaseTool):
    name: str = Field(default="kcag_min_cut")
    description: str = Field(
        default="Read the validated Stage 2 graph, compute minimum cuts "
                "and betweenness, rank candidate paths using configured "
                "heuristic traversal scores, and write kcag_report.json. "
                "The traversal scores are not calibrated probabilities."
    )
    args_schema: Type[BaseModel] = KCAGSchema
 
    def _run(self, stage2_vectors_path: Optional[str] = None) -> str:
        # ---- 1. Load topology from the artifact (deterministic) -------------
        if stage2_vectors_path is None:
            stage2_vectors_path = run_context.artifact_path("stage2_vectors.json")
        if not os.path.exists(stage2_vectors_path):
            return (f"ERROR: {stage2_vectors_path} not found. Stage 2 must emit a "
                    f"structured edge list before Annex B can run. Expected schema: "
                    f'{{"nodes":[{{"id","node_type","criticality"}}],'
                    f'"edges":[{{"source","target","technique","difficulty","effect","vec"}}]}}')
        try:
            data = run_context.read_stamped_json(stage2_vectors_path)
            raw_nodes = data["nodes"]
            raw_edges = data["edges"]
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            return f"ERROR: {stage2_vectors_path} malformed or failed run-isolation check ({e})."
 
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
            # validate_kcag() already rejects invalid difficulty values
            # upstream in the real pipeline, so this fallback should almost
            # never be reached there -- it remains as defense in depth for
            # any direct call to this tool that bypasses that gate.
            traversal_score = TRAVERSAL_SCORE_BY_DIFFICULTY.get(diff, 0.50)
            G.add_edge(src, tgt,
                       technique=(e.get("technique", "") if isinstance(e, dict) else ""),
                       difficulty=diff,
                       traversal_score=traversal_score,
                       effect=(e.get("effect") if isinstance(e, dict) else None),
                       vec=(e.get("vec", "") if isinstance(e, dict) else ""))
 
        if G.number_of_nodes() == 0 or G.number_of_edges() == 0:
            return "ERROR: Graph is empty after loading artifact."
 
        # ---- 2. Identify the root and ALL goals ------------------------------
        # Explicit ADV_START, never an order-dependent sources[0] pick.
        # validate_kcag() already gates this upstream in the real pipeline
        # (crew.py runs it before Annex B), but this check stays here too
        # as defense in depth for any direct call that bypasses that gate.
        goals = [n for n, a in G.nodes(data=True) if a.get("type") == "goal"]
        if "ADV_START" not in G:
            return "ERROR: Required KCAG root ADV_START is missing."
        if G.in_degree("ADV_START") != 0:
            return "ERROR: ADV_START has incoming edges."
        unexpected_roots = sorted(n for n, d in G.in_degree() if d == 0 and n != "ADV_START")
        if unexpected_roots:
            return (f"ERROR: ADV_START is not the sole KCAG root; "
                    f"additional roots: {unexpected_roots}.")
        if not goals:
            return "ERROR: No goal node (node_type='goal') found."
        src = "ADV_START"
 
        # ---- 3. Path score helper --------------------------------------------
        # "traversal_score", not "difficulty_score" -- lower difficulty
        # produces a HIGHER value under this model, so "difficulty_score"
        # would read backwards. This is a configured heuristic for relative
        # ranking, not an empirically calibrated probability -- see
        # TRAVERSAL_SCORE_BY_DIFFICULTY and the scoring_model block below.
        def path_score(path):
            s = 1.0
            for i in range(len(path) - 1):
                s *= G[path[i]][path[i + 1]]["traversal_score"]
            return round(s, 5)
 
        # ---- 4. Min cut against EVERY goal; aggregate shared chokepoints ----
        objective_results = {}
        cut_frequency = {}
        all_paths_flat = []
        for goal in goals:
            if not nx.has_path(G, src, goal):
                objective_results[goal] = {"top_path": [], "top_path_score": 0,
                                           "min_cut": [], "min_cut_size": 0, "path_count": 0}
                continue
            paths = list(nx.all_simple_paths(G, src, goal, cutoff=8))
            ranked = sorted(paths, key=path_score, reverse=True)
            try:
                cut = nx.minimum_node_cut(G, src, goal)
            except Exception:
                cut = set()
            for c in cut:
                cut_frequency[c] = cut_frequency.get(c, 0) + 1
            top = ranked[0] if ranked else []
            objective_results[goal] = {
                "top_path": top,
                "top_path_score": path_score(top) if top else 0,
                "min_cut": sorted(cut),
                "min_cut_size": len(cut),
                "path_count": len(paths),
            }
            for pth in ranked[:10]:
                all_paths_flat.append({"path": pth, "score": path_score(pth), "objective": goal})
 
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
 
        # ---- 7. Highest-RISK priority path (highest score, not lowest cost)
        all_paths_flat.sort(key=lambda x: x["score"], reverse=True)
        priority_path = all_paths_flat[0] if all_paths_flat else None
 
        # ---- 8. Emit kcag_report.json for Annex C ---------------------------
        # schema_version 2: score-terminology migration. New reports never
        # emit "top_path_prob" or "probability" -- see
        # extract_kcag_objective_score() for the backward-compatible reader
        # that still accepts pre-migration reports on resume. Old reports on
        # disk are never rewritten in place; their hashes and audit history
        # stay intact.
        report = {
            "schema_version": 2,
            "scoring_model": {
                "name": "configured_multiplicative_traversal_score",
                "version": 1,
                "semantics": "heuristic_relative_ranking",
                "calibrated_probability": False,
                "range": [0.0, 1.0],
                "aggregation": "product",
                "score_by_difficulty": TRAVERSAL_SCORE_BY_DIFFICULTY,
            },
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
        kcag_report_path = run_context.artifact_path("kcag_report.json")
        run_context.write_stamped_json(kcag_report_path, report)
 
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
            lines.append(f"Priority path (highest heuristic traversal score S={priority_path['score']}):")
            lines.append(f"  {' -> '.join(priority_path['path'])}  [{priority_path['objective']}]")
        lines.append("Score semantics: configured heuristic for relative ranking; "
                      "not an empirically calibrated probability.")
        lines.append(f"Report written: {kcag_report_path}")
        lines.append("STATUS: SUCCESS")
        return "\n".join(lines)
 
 
kcag_min_cut = KCAGMinCutTool()

# ============================================================================
#  CORPUS FILE DISCOVERY — single source of truth
#  Used identically by corpus hashing/versioning (snapshot_corpus, crew.py)
#  AND by chunk assembly for LLM analysis (crew.py). A file that gets
#  fingerprinted into the manifest is now guaranteed to also enter analysis,
#  and vice versa — the old .md/.txt/.pdf/.json vs .md/.txt split is gone.
# ============================================================================
CORPUS_EXTENSIONS = (".md", ".txt", ".pdf", ".json")

def discover_corpus_files(src_dir="sources"):
    """Return the sorted list of corpus source filenames in src_dir.
    Do not duplicate this filter anywhere else — import this function."""
    return sorted(
        f for f in os.listdir(src_dir)
        if f.endswith(CORPUS_EXTENSIONS)
        and not f.startswith("_")
        and f != "corpus_manifest.md"
    )

def read_corpus_file(path: str) -> str:
    """Return the textual content of one corpus source file for chunk
    assembly. .md/.txt/.json are read as plain text. .pdf is extracted via
    pypdf. Raises — does NOT silently skip — if pypdf is missing, because a
    missing extractor is a setup error, not a reason to hash a file that
    then never gets read (that silent mismatch was the original bug)."""
    if path.endswith(".pdf"):
        try:
            from pypdf import PdfReader
        except ImportError as e:
            raise RuntimeError(
                f"{path} is a PDF source but pypdf is not installed "
                f"(`pip install pypdf`). Refusing to silently exclude a "
                f"hashed corpus file from analysis."
            ) from e
        reader = PdfReader(path)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    return open(path, encoding="utf-8").read()


# ============================================================================
#  DETERMINISTIC CORPUS LOCK GATE  (plain Python — NOT a CrewAI tool)
#  Called directly from crew.py before pre_crew.kickoff(). Same contract
#  shape as verify_stage2_vectors: {"is_valid": bool, ...}. crew.py raises
#  on is_valid=False and refuses to start Stage 0 — the doctrinal Gate 1
#  check can no longer be satisfied by an agent reciting a verbatim string.
# ============================================================================
def verify_corpus_lock_gate(src: str = "sources",
                            manifest_path: str = "sources/corpus_manifest.md") -> dict:
    """Re-hash sources/ (via discover_corpus_files) against the frozen
    manifest written at corpus-lock time. Fails closed: a missing manifest,
    an unparsable manifest, or any missing/added/changed file all return
    is_valid=False — there is no path that defaults to PASS."""
    import re, hashlib

    result = {"is_valid": False, "status": "FAIL", "summary": "",
              "missing": [], "added": [], "changed": []}

    if not os.path.exists(manifest_path):
        result["summary"] = (f"{manifest_path} not found — corpus has not been "
                              f"locked yet. Run the collection/lock step before Stage 0.")
        return result

    m = re.search(r'```json\s*(\{.*\})\s*```', open(manifest_path).read(), re.S)
    if not m:
        result["summary"] = f"{manifest_path} has no embedded JSON block — cannot verify."
        return result

    try:
        frozen = json.loads(m.group(1))
        frozen_map = {e["file"]: e["sha256"] for e in frozen["files"]}
    except (json.JSONDecodeError, KeyError) as e:
        result["summary"] = f"{manifest_path} JSON block malformed ({e})."
        return result

    current = {}
    for fn in discover_corpus_files(src):
        with open(os.path.join(src, fn), "rb") as fh:
            current[fn] = hashlib.sha256(fh.read()).hexdigest()

    result["missing"] = sorted(set(frozen_map) - set(current))
    result["added"]   = sorted(set(current) - set(frozen_map))
    result["changed"] = sorted(f for f in (set(frozen_map) & set(current))
                                if frozen_map[f] != current[f])

    if result["missing"] or result["added"] or result["changed"]:
        result["summary"] = (f"CORPUS LOCK VIOLATION — missing: {result['missing']}, "
                              f"added: {result['added']}, changed: {result['changed']}")
        return result

    result["is_valid"] = True
    result["status"] = "PASS"
    result["summary"] = f"CORPUS LOCK VERIFIED: {len(current)} files match frozen manifest."
    return result


# ============================================================================
#  ATTRIBUTION-BOUNDARY CHECK  (plain Python — NOT a CrewAI tool)
#  Called directly from crew.py after Stage 0/1 prose is written. Same
#  reasoning as the corpus lock and Stage 2 gates: whether a named entity
#  traces to the scratchpad is a mechanical text-membership question, not
#  something to trust an agent's self-report on ("ATTRIBUTION DISCIPLINE"
#  in the task prompt was necessary but not sufficient — see stage0/stage1's
#  "MG Patrick Ellis" / "Shane Taylor" fabrication history).
#
#  This is regex-based candidate-entity extraction, not real NER, so it is
#  split into two confidence tiers:
#    - RANK_NAME / UNIT_DESIGNATION: a military rank abbreviation or an
#      ordinal+unit-noun phrase almost never precedes generic doctrinal
#      vocabulary. These drive the hard "untraceable" verdict.
#    - BARE_PHRASE: any other 2-4 word Title Case sequence. This also
#      catches real fabricated program/vendor names, but calibration
#      against pure-doctrine text (zero real entities) still produced
#      false positives on terms like "Common Operating Picture" —
#      reported as advisory only, never drives is_clean.
#  If you want the advisory tier to also block, that's a one-line change
#  in check_attribution_boundary's is_clean calculation — I left it
#  warn-only given the tier's real false-positive rate, but the mechanism
#  to escalate it is already there.
# ============================================================================
RANKS = {
    "GEN", "LTG", "MG", "BG", "COL", "LTC", "MAJ", "CPT", "LT", "2LT", "1LT",
    "CSM", "SGM", "1SG", "MSG", "SFC", "SSG", "SGT", "CPL", "SPC", "PFC", "PVT",
}
UNIT_WORDS = {"division", "brigade", "battalion", "regiment", "corps",
              "squadron", "company", "platoon", "task force"}

# Phrases that are legitimately Title Case in IW/military prose but are
# framework/document scaffolding, not named entities — excluded so the
# report isn't flooded with structural noise.
ATTRIBUTION_GENERIC_PHRASES = {
    "reverse ipb", "stage 0", "stage 1", "stage 2", "stage 3", "stage 4",
    "annex a", "annex b", "annex c", "united states", "not applicable",
}

_ATTR_WORD = r"[A-Z][a-z]+(?:['\-][A-Z][a-z]+)?"
_ATTR_PATTERNS = [
    ("RANK_NAME", re.compile(
        rf"\b((?:{'|'.join(RANKS)})\s+{_ATTR_WORD}(?:\s+{_ATTR_WORD}){{0,2}})")),
    ("UNIT_DESIGNATION", re.compile(
        rf"\b(\d+(?:st|nd|rd|th)(?:\s+{_ATTR_WORD}){{0,3}}\s+"
        rf"(?:{'|'.join(w.title() for w in UNIT_WORDS)}))\b", re.I)),
    ("BARE_PHRASE", re.compile(rf"\b({_ATTR_WORD}(?:\s+{_ATTR_WORD}){{1,3}})")),
]

def extract_attribution_candidates(text: str) -> dict:
    """Return {span: tier} for candidate named entities in text, after
    subsumption filtering (a shorter span fully inside a longer one is
    dropped — 'Patrick Ellis' inside 'MG Patrick Ellis' is one finding,
    not two). tier is one of RANK_NAME / UNIT_DESIGNATION / BARE_PHRASE;
    the first two are high-confidence, the third is advisory (see
    check_attribution_boundary)."""
    HIGH_CONF = {"RANK_NAME", "UNIT_DESIGNATION"}
    found = {}
    for tier, pat in _ATTR_PATTERNS:
        for m in pat.finditer(text):
            span = (m.group(1) if m.groups() else m.group(0)).strip()
            key = span.lower()
            if key in ATTRIBUTION_GENERIC_PHRASES:
                continue
            is_new_high_conf = tier in HIGH_CONF
            if key not in found or (is_new_high_conf and found[key][1] not in HIGH_CONF):
                found[key] = (span, tier)

    ordered = sorted(found.values(), key=lambda x: len(x[0]), reverse=True)
    kept = []
    for span, tier in ordered:
        if not any(span.lower() in longer.lower() and span != longer for longer, _ in kept):
            kept.append((span, tier))
    return dict(kept)

def check_attribution_boundary(text: str, scratch_text: str, corpus_text: str = "") -> dict:
    """Extract candidate named entities from `text` and classify each
    against `scratch_text` (the documented attribution boundary per the
    task prompts) and, as a fallback, `corpus_text` (the raw locked corpus).

    Three-tier verdict per entity, mirroring the confidence-tier pattern
    already used elsewhere in this pipeline (CONFIRMED/PLAUSIBLE/GAP style):
      TRACEABLE       — found in the scratchpad. Fine.
      EXTRACTION_GAP   — not in the scratchpad, but present in the raw
                         corpus. The scratchpad extraction missed it; not
                         fabricated, but Stage 0/1 should not have used it
                         without re-extracting.
      UNTRACEABLE      — not in the scratchpad or the raw corpus. Possible
                         fabrication — this is what a hallucinated
                         "MG Patrick Ellis" looks like.
    """
    candidates = extract_attribution_candidates(text)
    scratch_low = scratch_text.lower()
    corpus_low = (corpus_text or "").lower()

    result = {
        "checked": len(candidates),
        "high_confidence": {"traceable": [], "extraction_gap": [], "untraceable": []},
        "advisory": {"traceable": [], "extraction_gap": [], "untraceable": []},
    }
    for span, tier in candidates.items():
        bucket = "high_confidence" if tier in ("RANK_NAME", "UNIT_DESIGNATION") else "advisory"
        e = span.lower()
        if e in scratch_low:
            result[bucket]["traceable"].append(span)
        elif corpus_low and e in corpus_low:
            result[bucket]["extraction_gap"].append(span)
        else:
            result[bucket]["untraceable"].append(span)

    result["is_clean"] = len(result["high_confidence"]["untraceable"]) == 0
    return result


@tool("read_corpus_chunk")
def read_corpus_chunk(chunk_index: str = "0") -> str:
    """Return one pre-assembled chunk of the locked corpus.
    Chunks are built from all source files before crew kickoff.
    Call with chunk_index '0' through N-1. The response tells you total chunks."""
    import json
    chunks_path = run_context.artifact_path("corpus_chunks.json")
    data = run_context.read_stamped_json(chunks_path)
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
    scratch_path = run_context.artifact_path("_stage0_scratch.md")
    lines = chunk_index_and_findings.split("\n", 1)
    idx = lines[0].strip()
    findings = lines[1] if len(lines) > 1 else ""
    with open(scratch_path, "a") as f:
        f.write(f"\n## Extraction — chunk {idx}\n{findings}\n")
    return f"Chunk {idx} findings appended to scratchpad."

@tool("read_scratch")
def read_scratch(trigger: str) -> str:
    """Return the full accumulated extraction scratchpad.
    You MUST pass the string 'EXECUTE' as the trigger argument."""
    if trigger != "EXECUTE":
         return "ERROR: You must pass the string 'EXECUTE' to read the scratchpad."
    scratch_path = run_context.artifact_path("_stage0_scratch.md")
    try:
        return open(scratch_path).read()
    except FileNotFoundError:
        return "[scratchpad empty — no extractions recorded]"
    
@tool("verify_and_fix_stage2")
def verify_and_fix_stage2(_: str = "") -> str:
    """Read the active run's stage2.md, verify EVERY framework ID across all
    schemas, auto-correct hallucinated IDs via keyword search, and FAIL on
    any [GAP]/[UNMAPPED] marker or category-mismatched SPARTA ID.

    A FAIL blocks Annex B. This is mechanical, not analytical.

    NOTE: this tool is currently not assigned to any agent in pre_crew or
    post_crew (the 'verifier' agent that holds it isn't a member of either
    crew) -- it's unreachable from the actual pipeline. Paths here are kept
    run-scoped for consistency regardless.
    """
    stage2_path = run_context.artifact_path("stage2.md")
    try:
        idx = json.load(open("corpus-index/technique_index.json"))
    except FileNotFoundError:
        return "ERROR: corpus-index/technique_index.json not found — cannot verify."
    try:
        stage2 = open(stage2_path).read()
    except FileNotFoundError:
        return f"ERROR: {stage2_path} not found — Stage 2 has not been written yet."
 
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
 
    corrected_path = run_context.artifact_path("stage2_corrected.md")
    with open(corrected_path, "w") as f:
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
        f"Corrected output: {corrected_path}",
        f"STATUS: {status}",
    ]
    return "\n".join(report) + "\n\n=== CORRECTED STAGE 2 VECTORS ===\n" + corrected_text

# ============================================================================
#  DETERMINISTIC STAGE 2 GATE  (plain Python — NOT a CrewAI tool)
#  Add to src/tools.py. Called directly from src/crew.py between crews.
#  Single function, single return contract: {"is_valid": bool, ...}
# ============================================================================
def verify_stage2_vectors(vectors_path: Optional[str] = None,
                          index_path: str = "corpus-index/technique_index.json") -> dict:
    """Deterministically verify every technique ID in the Stage 2 attack GRAPH
    (not the prose) against the indexed corpus. This is the enforcement gate:
    crew.py raises on is_valid=False and never builds the downstream crew.

    Verifies the authoritative artifact (stage2_vectors.json) — the file Annex B
    actually consumes — so prose/graph drift cannot pass unverified IDs to the KCAG.

    vectors_path defaults to the active run's Stage 2 output (run_context);
    index_path stays a plain default since the technique index is corpus-level,
    not per-run, data.

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

    if vectors_path is None:
        vectors_path = run_context.artifact_path("stage2_vectors.json")

    if not os.path.exists(vectors_path):
        result["summary"] = f"{vectors_path} not found — Stage 2 did not emit an edge list."
        return result
    if not os.path.exists(index_path):
        result["summary"] = f"{index_path} not found — cannot verify."
        return result

    try:
        data = run_context.read_stamped_json(vectors_path)
        index = json.load(open(index_path))
    except (json.JSONDecodeError, ValueError) as e:
        result["summary"] = f"{vectors_path} failed to load or run-isolation check ({e})."
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


# ============================================================================
#  PHASE 0 SAFETY GATE COMPLIANCE CHECK  (plain Python — NOT a CrewAI tool)
#  Called from crew.py after stage4_crew.kickoff() completes. Unlike the
#  attribution-boundary check (item 7), this IS a hard gate: a missing
#  safety-review section on a payload with a real physical/destructive
#  effect is a safety compliance failure, not an analytical nicety, so this
#  errs toward over-detecting kinetic payloads rather than under-detecting
#  them. See the crew.py wiring for the important caveat that this runs
#  AFTER t_stage4's human_input approval already happened inside kickoff()
#  — it is a post-hoc compliance check, defense in depth alongside the
#  separate, earlier check_stage3_safety_gate (which DOES run before Stage 4
#  is even constructed, in the pre-Stage-4 gate — see that function above).
# ============================================================================
KINETIC_CATEGORY_MARKERS = [
    r"degradation\s*&?\s*destruction",
    r"physical\s+behavior\s+alteration",
    r"\bcategory\s*[:\s]*2\b",
    r"\bcategory\s*[:\s]*3\b",
]
KINETIC_KEYWORD_MARKERS = [
    r"\bkinetic\b", r"\blive[\s-]fire\b", r"\bphysical[\s-]layer\b",
    r"\brange safety\b", r"\bactuator\b", r"\bfires?\s+(?:effect|solution)\b",
]
SAFETY_GATE_MARKERS = [
    r"phase\s*0.{0,60}safety",
    r"safety\s*gate",
    r"\brso\b|\brange safety officer\b",
    r"abort\s+(?:criteria|circuit|authority|trigger)",
]
NO_GATE_NEEDED_MARKER = r"no\s+category\s*2\s*/?\s*3\s+payloads?"


def _strip_markdown_emphasis(text: str) -> str:
    """Strip **bold**, *italic*, and `code` markers before running any
    field/category-line regex against LLM-generated prose. Real Stage 3
    output routinely bolds field labels (observed in this project's own
    transcripts: '**Category:** 3, 4', '**Category:** `1, 4`'), and a
    regex that only matches unstyled 'Category: 3, 4' would silently fail
    to detect a real Category 2/3 declaration — a dangerous false
    negative for a safety gate, not a cosmetic miss."""
    return re.sub(r"[*_`]+", "", text)


STAGE3_CATEGORY_LINE = re.compile(
    r"^\s*(?:[-+]\s*)?category\s*:\s*([^\n]+)$",
    re.IGNORECASE | re.MULTILINE,
)

STAGE3_SAFETY_SECTION = re.compile(
    r"^#{1,6}\s+PRE-STAGE-4 SAFETY REVIEW\s*$",
    re.IGNORECASE | re.MULTILINE,
)

_NEXT_MARKDOWN_HEADING = re.compile(r"^#{1,6}\s+.+$", re.MULTILINE)


def _extract_stage3_safety_section(text: str):
    """Return the body of the PRE-STAGE-4 SAFETY REVIEW section only —
    from right after its heading up to the next markdown heading (or end
    of document if it's the last section) — or None if the heading isn't
    present at all. Required-field and no-gate-declaration checks must
    run against this extracted section, NOT the whole document: without
    this, field labels that happen to appear anywhere else (e.g. legitimately
    repeated per-payload, which CRITICAL INSTRUCTION 5 also asks for) would
    let a document with an incomplete or empty safety-review section pass
    anyway, exactly as long as the same labels happened to occur elsewhere."""
    heading = STAGE3_SAFETY_SECTION.search(text)
    if not heading:
        return None
    remainder = text[heading.end():]
    next_heading = _NEXT_MARKDOWN_HEADING.search(remainder)
    if next_heading:
        return remainder[:next_heading.start()].strip()
    return remainder.strip()

STAGE3_NO_GATE_REQUIRED = "NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED."

STAGE3_REQUIRED_SAFETY_FIELDS = {
    "affected_assets": r"^\s*(?:[-+]\s*)?affected assets\s*:\s*(.+)$",
    "approving_roles": r"^\s*(?:[-+]\s*)?required approving roles\s*:\s*(.+)$",
    "safety_authority": r"^\s*(?:[-+]\s*)?(?:rso or domain-equivalent safety authority|safety authority)\s*:\s*(.+)$",
    "abort_authority": r"^\s*(?:[-+]\s*)?abort authority\s*:\s*(.+)$",
    "abort_criteria": r"^\s*(?:[-+]\s*)?abort criteria\s*:\s*(.+)$",
    "termination_time": r"^\s*(?:[-+]\s*)?maximum termination time\s*:\s*(.+)$",
    "rollback": r"^\s*(?:[-+]\s*)?(?:rollback or recovery procedure|rollback procedure)\s*:\s*(.+)$",
    "release_condition": r"^\s*(?:[-+]\s*)?release condition\s*:\s*(.+)$",
}

STAGE3_INVALID_VALUES = {
    "", "tbd", "unknown", "n/a", "none", "not determined", "to be determined",
}


def check_stage3_safety_gate(stage3_text: str) -> dict:
    """Deterministic pre-Stage-4 gate: verifies that any Category 2/3 test
    concept in Stage 3 is accompanied by a complete PRE-STAGE-4 SAFETY
    REVIEW section, BEFORE Stage 4 is ever constructed. Plain Python, not
    a CrewAI tool — crew.py calls this directly between analysis_crew and
    stage4_crew, the same fail-closed pattern verify_stage2_vectors uses
    between pre_crew and post_crew.

    Detection is markdown-emphasis-agnostic (see _strip_markdown_emphasis)
    and only matches structured 'Label: value' lines — never a bare
    substring search for 'Category 2'/'Category 3', which the
    no-gate-required sentence itself would false-positive against (it
    contains the literal text 'CATEGORY 2/3').

    Result contract: {is_compliant, category_2_3_detected,
    matched_categories, safety_review_present, missing_fields,
    invalid_fields, explicit_not_required, summary}.
    """
    text = _strip_markdown_emphasis(stage3_text or "")
    section = _extract_stage3_safety_section(text)

    # Category detection scans the WHOLE document, deliberately NOT scoped
    # to the safety-review section -- category labels legitimately live in
    # each payload's own header (e.g. "### RT-001\nCategory: 2"), not in
    # the aggregate section.
    category_values = STAGE3_CATEGORY_LINE.findall(text)
    category_numbers = set()
    for value in category_values:
        category_numbers.update(int(n) for n in re.findall(r"\b[1-4]\b", value))
    detected = bool(category_numbers & {2, 3})

    # The no-gate override, in contrast, MUST be scoped to the section --
    # otherwise the sentinel phrase appearing anywhere in the document
    # (e.g. stray, or copy-pasted into an unrelated payload's notes) would
    # satisfy compliance even with a missing or empty safety-review section.
    explicit_not_required = section is not None and STAGE3_NO_GATE_REQUIRED.lower() in section.lower()

    result = {
        "is_compliant": False,
        "category_2_3_detected": detected,
        "matched_categories": sorted(category_numbers & {2, 3}),
        "safety_review_present": section is not None,
        "missing_fields": [],
        "invalid_fields": [],
        "explicit_not_required": explicit_not_required,
        "summary": "",
    }

    if not detected:
        if explicit_not_required:
            result["is_compliant"] = True
            result["summary"] = ("No Category 2/3 concepts were declared and the required "
                                  "not-applicable statement is present.")
        else:
            result["summary"] = ("No Category 2/3 concepts were detected, but the required "
                                  "explicit not-applicable statement is missing.")
        return result

    if explicit_not_required:
        result["summary"] = ("Stage 3 declares Category 2/3 concepts but also states that "
                              "the safety gate is not required — contradictory, not compliant.")
        result["invalid_fields"].append("contradictory_not_required_statement")
        return result

    if section is None:
        result["summary"] = ("Category 2/3 concepts were detected, but the "
                              "PRE-STAGE-4 SAFETY REVIEW section is missing.")
        return result

    # All required-field checks run against the extracted SECTION only,
    # never the whole document -- a field label appearing elsewhere (e.g.
    # legitimately repeated per-payload, which CRITICAL INSTRUCTION 5 also
    # asks for) must not let an incomplete or near-empty safety-review
    # section pass just because the same labels happened to occur nearby.
    values = {}
    for field, pattern in STAGE3_REQUIRED_SAFETY_FIELDS.items():
        m = re.search(pattern, section, re.IGNORECASE | re.MULTILINE)
        if not m:
            result["missing_fields"].append(field)
            continue
        value = m.group(1).strip()
        values[field] = value
        if value.lower() in STAGE3_INVALID_VALUES:
            result["invalid_fields"].append(field)

    release_condition = values.get("release_condition", "").lower()
    if release_condition and not any(
        phrase in release_condition for phrase in ("may not begin", "must not begin", "shall not begin")
    ):
        result["invalid_fields"].append("release_condition")

    result["is_compliant"] = not result["missing_fields"] and not result["invalid_fields"]

    if result["is_compliant"]:
        result["summary"] = ("Category 2/3 concepts are present and the required pre-Stage-4 "
                              "safety controls are documented.")
    else:
        result["summary"] = (f"Category 2/3 concepts are present, but required safety controls "
                              f"are incomplete. Missing={result['missing_fields']}; "
                              f"invalid={result['invalid_fields']}.")

    return result


def check_phase0_safety_gate(stage3_text: str, stage4_text: str) -> dict:
    """Checks whether any Category 2 (Degradation & Destruction) or
    Category 3 (Physical Behavior Alteration) payload in Stage 3 output is
    matched by a Phase 0 Safety Gate section in the Stage 4 mission plan.
    Requires an explicit 'no Category 2/3 payloads' statement to treat the
    gate as not-applicable — silence is never treated as compliant."""
    s3, s4 = stage3_text or "", stage4_text or ""

    # Strip the required override sentence out of s3 before scanning it:
    # KINETIC_CATEGORY_MARKERS matches raw "category 2"/"category 3"
    # substrings anywhere in the text, and the override sentence itself
    # ("NO CATEGORY 2/3 PAYLOADS...") contains that exact substring. Since
    # Stage 3's own prompt (CRITICAL INSTRUCTION 5) now requires this
    # sentence to appear IN stage3_text whenever no Category 2/3 concepts
    # exist, leaving it unstripped would make category_2_3_detected always
    # true on a genuinely clean Stage 3 output -- a false positive that
    # only started happening once Stage 3 itself began emitting this
    # sentence, not a pre-existing issue with unrelated causes.
    s3_for_category_scan = re.sub(NO_GATE_NEEDED_MARKER, "", s3, flags=re.I)

    matched = [m.group(0) for pat in KINETIC_CATEGORY_MARKERS + KINETIC_KEYWORD_MARKERS
               for m in [re.search(pat, s3_for_category_scan, re.I)] if m]
    category_2_3_detected = len(matched) > 0

    gate_present = any(re.search(pat, s4, re.I) for pat in SAFETY_GATE_MARKERS)
    explicit_not_needed = bool(re.search(NO_GATE_NEEDED_MARKER, s4, re.I))

    if not category_2_3_detected:
        is_compliant, summary = True, (
            "No Category 2/3 (kinetic/destructive) payload detected in Stage 3 — "
            "Phase 0 Safety Gate not required.")
    elif explicit_not_needed:
        # Checked BEFORE gate_present so the override phrase (which itself
        # contains "phase 0 ... safety gate") isn't misattributed as a
        # real gate section. Category 2/3 WAS detected in Stage 3 at this
        # point, so Stage 4 stating no Category 2/3 payloads apply is a
        # direct contradiction, not an acceptable override — fail closed
        # rather than accept-with-a-flag.
        is_compliant, summary = False, (
            "COMPLIANCE GAP: Stage 3 contains Category 2/3 concepts, but Stage 4 "
            "states that no Category 2/3 payloads apply.")
    elif gate_present:
        is_compliant, summary = True, (
            f"Category 2/3 payload detected ({matched[:3]}) and a Phase 0 Safety Gate "
            f"section was found in the Stage 4 mission plan.")
    else:
        is_compliant, summary = False, (
            f"COMPLIANCE GAP: Category 2/3 payload detected in Stage 3 ({matched[:3]}) "
            f"but no Phase 0 Safety Gate section (and no explicit not-needed statement) "
            f"found in the Stage 4 mission plan.")

    return {"category_2_3_detected": category_2_3_detected, "matched_terms": matched,
            "phase0_gate_present": gate_present, "is_compliant": is_compliant,
            "summary": summary}


# ============================================================================
#  SHARED KCAG STRUCTURAL CONSTANTS
#  Used by both write_stage2_vectors() (shallow, writer-time shape check)
#  and validate_kcag() (deeper structural gate run later, right before
#  Annex B). Centralized here so the two checks cannot drift into separate
#  definitions of what a valid node/edge looks like. Framework technique-ID
#  formats deliberately do NOT live here -- that remains exclusively
#  verify_stage2_vectors()'s responsibility.
# ============================================================================
KCAG_NODE_TYPES = frozenset({
    "privilege", "technique", "property", "countermeasure", "goal",
})
KCAG_DIFFICULTIES = frozenset({"LOW", "MEDIUM", "HIGH"})
KCAG_EFFECTS = frozenset({None, "DECEIVE", "DISRUPT", "DEGRADE", "DESTROY"})
KCAG_VECTOR_ID_PATTERN = re.compile(r"^V-\d{2,}$")


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

    This is a shallow, writer-time shape check only — it does not enforce
    that the entry node is specifically ADV_START, that it's the sole
    root, or that every goal is reachable from it. That deeper structural
    validation is validate_kcag()'s job, run later as its own gate right
    before Annex B. Left deliberately unchanged/unexpanded here: the two
    checks are meant to stay layered, not merged.
    """
    import json, os

    VALID_TYPES = KCAG_NODE_TYPES
    VALID_DIFF = KCAG_DIFFICULTIES

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

    out_path = run_context.artifact_path("stage2_vectors.json")
    run_context.write_stamped_json(out_path, {"nodes": nodes, "edges": edges})

    return (f"WRITTEN: {out_path} | "
            f"{len(nodes)} nodes, {len(edges)} edges, {len(goal_nodes)} goal(s), "
            f"entry node(s): {entry_nodes}. Annex B may now build the KCAG.")


MAX_REPORTED_KCAG_CYCLES = 20


def validate_kcag(vectors_path: Optional[str] = None) -> dict:
    """Validate the structure of the active run's Stage 2 KCAG artifact.

    Plain Python, not a CrewAI tool — crew.py calls this directly between
    verify_stage2_vectors() and analysis_crew, the same fail-closed
    pattern as every other deterministic gate in this pipeline.

    This function does NOT verify framework technique IDs — that remains
    exclusively verify_stage2_vectors()'s responsibility, kept as a
    separate, non-overlapping check. This function also does NOT mutate
    the graph: it reads the original stamped stage2_vectors.json and only
    ever reports on it. Annex B continues reading that same original
    artifact; nothing here produces a "validated" replacement file.

    Missing active run propagates RuntimeError uncaught (from
    run_context.artifact_path()/read_stamped_json() internally) — this is
    NOT caught and converted into a returned dict, matching the
    established fail-closed pattern everywhere else in this codebase
    (write_stage0_output, etc.). A cross-run or cross-corpus artifact
    raises ValueError from read_stamped_json(), also uncaught here, for
    the same reason.
    """
    import hashlib
    import itertools
    from collections import Counter
    from pathlib import Path

    result = {
        "is_valid": False,
        "status": "FAIL",
        "source_artifact": "",
        "source_artifact_sha256": None,
        "node_count": 0,
        "edge_count": 0,
        "root": None,
        "roots": [],
        "goals": [],
        "reachable_goals": [],
        "unreachable_goals": [],
        "unreachable_nodes": [],
        "self_loops": [],
        "cycles": [],
        "cycles_truncated": False,
        "dead_end_nodes": [],
        "countermeasure_warnings": [],
        "errors": [],
        "warnings": [],
        "summary": "",
    }

    if vectors_path is None:
        vectors_path = run_context.artifact_path("stage2_vectors.json")

    result["source_artifact"] = vectors_path
    path = Path(vectors_path)

    if not path.exists():
        result["errors"].append(f"{vectors_path} does not exist.")
        result["summary"] = "KCAG validation failed: artifact missing."
        return result

    result["source_artifact_sha256"] = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()

    data = run_context.read_stamped_json(vectors_path)

    nodes = data.get("nodes")
    edges = data.get("edges")

    if not isinstance(nodes, list):
        result["errors"].append("'nodes' must be a list.")
    if not isinstance(edges, list):
        result["errors"].append("'edges' must be a list.")

    if result["errors"]:
        result["summary"] = "KCAG validation failed: malformed payload."
        return result

    result["node_count"] = len(nodes)
    result["edge_count"] = len(edges)

    node_ids = []
    node_types = {}

    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            result["errors"].append(f"node[{index}] must be an object.")
            continue

        node_id = str(node.get("id", "")).strip()
        if not node_id:
            result["errors"].append(f"node[{index}] has no valid id.")
            continue

        node_ids.append(node_id)
        node_types[node_id] = node.get("node_type")

        if node.get("node_type") not in KCAG_NODE_TYPES:
            result["errors"].append(
                f"node '{node_id}' has invalid node_type '{node.get('node_type')}'."
            )

        criticality = node.get("criticality")
        if not isinstance(criticality, int) or not 1 <= criticality <= 10:
            result["errors"].append(f"node '{node_id}' criticality must be an integer 1-10.")

    duplicate_nodes = sorted(nid for nid, count in Counter(node_ids).items() if count > 1)
    for node_id in duplicate_nodes:
        result["errors"].append(f"Duplicate node id '{node_id}'.")

    declared_nodes = set(node_ids)
    edge_pairs = []
    valid_edges = []

    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            result["errors"].append(f"edge[{index}] must be an object.")
            continue

        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()

        if not source or not target:
            result["errors"].append(f"edge[{index}] must define source and target.")
            continue

        if source not in declared_nodes:
            result["errors"].append(f"edge[{index}] source '{source}' is undeclared.")
        if target not in declared_nodes:
            result["errors"].append(f"edge[{index}] target '{target}' is undeclared.")

        if source == target:
            result["self_loops"].append(source)
            result["errors"].append(f"edge[{index}] is a self-loop on '{source}'.")

        difficulty = str(edge.get("difficulty", "")).upper()
        if difficulty not in KCAG_DIFFICULTIES:
            result["errors"].append(f"edge[{index}] has invalid difficulty '{difficulty}'.")

        effect = edge.get("effect")
        normalized_effect = effect.upper() if isinstance(effect, str) else effect
        if normalized_effect not in KCAG_EFFECTS:
            result["errors"].append(f"edge[{index}] has invalid effect '{effect}'.")

        vector_id = str(edge.get("vec", "")).strip()
        if not KCAG_VECTOR_ID_PATTERN.fullmatch(vector_id):
            result["errors"].append(f"edge[{index}] has invalid vec '{vector_id}'.")

        edge_pairs.append((source, target))
        valid_edges.append(edge)

    duplicate_pairs = sorted(pair for pair, count in Counter(edge_pairs).items() if count > 1)
    for source, target in duplicate_pairs:
        result["errors"].append(f"Duplicate directed edge '{source}' -> '{target}'.")

    # Do not build NetworkX topology until raw-reference checks pass --
    # dangling/malformed references must never reach graph construction.
    if result["errors"]:
        result["summary"] = f"KCAG validation failed with {len(result['errors'])} error(s)."
        return result

    graph = nx.DiGraph()
    for node in nodes:
        graph.add_node(node["id"], node_type=node["node_type"], criticality=node["criticality"])
    for edge in valid_edges:
        graph.add_edge(edge["source"], edge["target"])

    roots = sorted(node for node, indegree in graph.in_degree() if indegree == 0)
    result["roots"] = roots

    if "ADV_START" not in graph:
        result["errors"].append("Required root node ADV_START is missing.")
    else:
        result["root"] = "ADV_START"
        if node_types.get("ADV_START") != "privilege":
            result["errors"].append("ADV_START must have node_type='privilege'.")
        if graph.in_degree("ADV_START") != 0:
            result["errors"].append("ADV_START must have zero incoming edges.")

    if roots != ["ADV_START"]:
        result["errors"].append(f"ADV_START must be the sole root; roots found: {roots}.")

    goals = sorted(node for node, attrs in graph.nodes(data=True) if attrs.get("node_type") == "goal")
    result["goals"] = goals

    if not goals:
        result["errors"].append("At least one goal node is required.")

    for goal in goals:
        if graph.out_degree(goal) != 0:
            result["errors"].append(f"Goal '{goal}' must be terminal.")

    if "ADV_START" in graph:
        reachable = nx.descendants(graph, "ADV_START") | {"ADV_START"}
        result["unreachable_nodes"] = sorted(set(graph.nodes) - reachable)
        result["reachable_goals"] = sorted(g for g in goals if g in reachable)
        result["unreachable_goals"] = sorted(g for g in goals if g not in reachable)

        if result["unreachable_nodes"]:
            result["errors"].append(f"Nodes unreachable from ADV_START: {result['unreachable_nodes']}.")
        if result["unreachable_goals"]:
            result["errors"].append(f"Goals unreachable from ADV_START: {result['unreachable_goals']}.")

    result["dead_end_nodes"] = sorted(
        node for node in graph.nodes
        if graph.out_degree(node) == 0 and node_types.get(node) != "goal"
    )
    if result["dead_end_nodes"]:
        result["warnings"].append(f"Non-goal sink nodes found: {result['dead_end_nodes']}.")

    cycle_iterator = nx.simple_cycles(graph)
    cycles_plus_one = list(itertools.islice(cycle_iterator, MAX_REPORTED_KCAG_CYCLES + 1))
    result["cycles_truncated"] = len(cycles_plus_one) > MAX_REPORTED_KCAG_CYCLES
    result["cycles"] = cycles_plus_one[:MAX_REPORTED_KCAG_CYCLES]
    if result["cycles"]:
        result["warnings"].append(
            f"{len(result['cycles'])} directed cycle(s) found"
            + (" (report truncated)." if result["cycles_truncated"] else ".")
        )

    goal_set = set(goals)
    for node, attrs in graph.nodes(data=True):
        if attrs.get("node_type") != "countermeasure":
            continue
        can_reach_goal = any(nx.has_path(graph, node, goal) for goal in goal_set)
        if graph.out_degree(node) == 0 or not can_reach_goal:
            warning = f"Countermeasure '{node}' is not positioned on a path that continues to a goal."
            result["countermeasure_warnings"].append(warning)
            result["warnings"].append(warning)

    result["is_valid"] = not result["errors"]
    result["status"] = "PASS" if result["is_valid"] else "FAIL"
    result["summary"] = (
        f"KCAG validation {result['status']}: {result['node_count']} nodes, "
        f"{result['edge_count']} edges, {len(result['goals'])} goals, "
        f"{len(result['errors'])} errors, {len(result['warnings'])} warnings."
    )
    return result

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

# ============================================================================
#  BACKWARD-COMPATIBLE KCAG SCORE READER
#  Reads either schema_version 2 reports (top_path_score) or legacy,
#  pre-migration reports (top_path_prob) -- needed because a resumed run
#  may skip Annex B entirely (it already completed under old code) while
#  Annex C still needs to run. Legacy values retain their original
#  numerical meaning; they are read as heuristic traversal scores, not
#  probabilities, same as current-schema values. Old kcag_report.json
#  files on disk are never rewritten -- their hashes and audit history
#  stay intact regardless of which schema version produced them.
# ============================================================================


def _validate_kcag_score(value, *, objective_id, field):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"KCAG objective '{objective_id}' field '{field}' must be numeric.")
    score = float(value)
    if not math.isfinite(score):
        raise ValueError(f"KCAG objective '{objective_id}' field '{field}' must be finite.")
    if not 0.0 <= score <= 1.0:
        raise ValueError(f"KCAG objective '{objective_id}' field '{field}' must be between 0 and 1.")
    return score


def extract_kcag_objective_score(kcag_report: dict) -> dict:
    """Return the maximum KCAG objective traversal score.

    Supports:
    - schema v2: top_path_score
    - legacy schema: top_path_prob

    Legacy values retain their original numerical meaning but are
    interpreted as heuristic traversal scores, not probabilities.

    Fails closed (raises ValueError) on: missing/empty objective_results,
    a non-object objective entry, an objective with neither field present,
    a non-numeric/non-finite/out-of-range value in either field, or
    conflicting current+legacy values for the same objective -- silently
    preferring one would let a corrupted transitional artifact pass.
    """
    objectives = kcag_report.get("objective_results")
    if not isinstance(objectives, dict) or not objectives:
        raise ValueError("KCAG report has no non-empty objective_results.")

    values = []
    used_legacy = False

    for objective_id, result in objectives.items():
        if not isinstance(result, dict):
            raise ValueError(f"KCAG objective '{objective_id}' must be an object.")

        has_current = "top_path_score" in result
        has_legacy = "top_path_prob" in result

        if not has_current and not has_legacy:
            raise ValueError(
                f"KCAG objective '{objective_id}' has neither 'top_path_score' "
                "nor legacy 'top_path_prob'."
            )

        current = (_validate_kcag_score(result["top_path_score"], objective_id=objective_id,
                                        field="top_path_score") if has_current else None)
        legacy = (_validate_kcag_score(result["top_path_prob"], objective_id=objective_id,
                                       field="top_path_prob") if has_legacy else None)

        if current is not None and legacy is not None and current != legacy:
            raise ValueError(
                f"KCAG objective '{objective_id}' contains conflicting current "
                "and legacy score values."
            )

        if current is not None:
            values.append(current)
        else:
            values.append(legacy)
            used_legacy = True

    return {
        "score": max(values),
        "used_legacy_field": used_legacy,
        "source_field": "top_path_prob" if used_legacy else "top_path_score",
    }


# --- Annex C: pgmpy five-layer BBN threat inference ---
@tool("bbn_threat_score")
def bbn_threat_score(cpd_config_json: str = "", priors_path: str = "config/bbn_priors.json") -> str:
    """Construct an evidence-driven Bayesian threat model, run inference, and
    return a threat score, kill-chain phase estimate, and a CPD audit log.

    Unlike a flat risk-propagation model, this ingests the Annex B KCAG
    heuristic objective-traversal score and real conditional structure so
    the score reflects the computed attack graph, not a default constant.
    That score is a configured heuristic for relative path ranking, not a
    Bayesian prior in its own right and not a calibrated probability -- it
    enters this BBN as a scaling factor on specific CPD values (see the
    KCAG-anchored lines below), same as the other per-assessment inputs.

    STRUCTURAL CPD VALUES (how nodes relate to each other -- e.g. phishing
    rate by adversary capability, kill-chain phase base rates, defensive/
    geopolitical multipliers) are NOT embedded in this function. They are
    read from `priors_path` (default config/bbn_priors.json), each with a
    documented source. This tool refuses to run -- returns an ERROR string,
    does not fall back to a hardcoded default -- if that file is missing, is
    malformed, or is missing any required prior. See bbn_priors.json itself
    for the full schema and honest provenance notes on every value (most are
    inherited analyst-judgment template defaults, not empirically fit --
    review before scored use).

    PER-ASSESSMENT INPUTS are required in cpd_config_json with no silent
    defaults -- this also fails closed if any are missing:
      {
        "kcag_report_path": null,   // optional; omit to auto-resolve to the active run's kcag_report.json
        "adversary": {
            "capability_prior": [0.0, 0.05, 0.95],        // REQUIRED: [hacktivist,criminal,nation-state]
            "tempo": "HIGH"                                // REQUIRED: LOW|MEDIUM|HIGH
        },
        "defensive_posture": {                             // REQUIRED: true=control active
            "mfa": true, "edr": false, "segmentation": false,
            "integrity_monitor": false, "email_filtering": true
        },
        "geopolitical_trigger_prior": 0.55,                // REQUIRED
        "evidence": {                                      // optional -- absence is a legitimate "no observations yet" baseline, not a hidden prior
            "GeopoliticalTrigger": 1, "AdversaryCapability": 2,
            "PhishingAttempt": 1, "ScanningDetected": 1, "AuthAnomaly": 1
        }
      }
    outputs/kcag_report.json is also required (Annex B must run before Annex C)
    -- this fails closed rather than substituting a fallback objective prior.

    Returns a human-readable report plus writes bbn_report.json under the
    active run's output directory.
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

    # ---- Load structural priors file (fail closed -- no embedded defaults) --
    if not os.path.exists(priors_path):
        return (f"ERROR: {priors_path} not found. Refusing to run with embedded "
                f"default CPD values. Create {priors_path} with sourced priors "
                f"(see this tool's docstring for the schema) before calling "
                f"bbn_threat_score.")
    try:
        priors = json.load(open(priors_path))["priors"]
    except (json.JSONDecodeError, KeyError) as e:
        return f"ERROR: {priors_path} malformed or missing 'priors' key ({e}). Refusing to run."

    def prior(*path):
        """Walk a dotted path into the priors dict. Fails closed with a specific
        missing-key message instead of raising a raw KeyError or defaulting."""
        node = priors
        for i, key in enumerate(path):
            if not isinstance(node, dict) or key not in node:
                raise LookupError(f"required prior '{'.'.join(path[:i+1])}' missing from {priors_path}")
            node = node[key]
        if not (isinstance(node, dict) and "value" in node):
            raise LookupError(f"prior '{'.'.join(path)}' in {priors_path} is missing its 'value' field")
        return node["value"], node.get("source", "(no source field in priors file)")

    # ---- Parse per-run config -- REQUIRED, no silent defaults ---------------
    cfg = {}
    if cpd_config_json and cpd_config_json.strip():
        try:
            cfg = json.loads(cpd_config_json)
        except json.JSONDecodeError as e:
            return f"ERROR: cpd_config_json is not valid JSON ({e}). Refusing to run on undefined input."

    adversary = cfg.get("adversary", {})
    missing = [f"adversary.{k}" for k in ("capability_prior", "tempo") if k not in adversary]
    missing += [k for k in ("defensive_posture", "geopolitical_trigger_prior") if k not in cfg]
    if missing:
        return (f"ERROR: cpd_config_json is missing required field(s): {missing}. "
                f"These vary per assessment and are never silently assumed — supply "
                f"them explicitly. See this tool's docstring for the expected shape.")

    cap_prior = adversary["capability_prior"]
    tempo = adversary["tempo"]
    if tempo not in ("LOW", "MEDIUM", "HIGH"):
        return f"ERROR: adversary.tempo must be one of LOW/MEDIUM/HIGH, got {tempo!r}."
    posture = cfg["defensive_posture"]
    geo_prior = float(cfg["geopolitical_trigger_prior"])
    evidence = cfg.get("evidence", {})  # absent evidence = legitimate baseline state, not a hidden prior

    # ---- Ingest Annex B KCAG heuristic factor -- REQUIRED, fail closed -------
    kcag_path = cfg.get("kcag_report_path") or run_context.artifact_path("kcag_report.json")
    if not os.path.exists(kcag_path):
        return (f"ERROR: {kcag_path} not found. Annex B must run before Annex C — "
                f"refusing to substitute a fallback objective-path score. Run "
                f"kcag_min_cut first.")
    try:
        kcag = run_context.read_stamped_json(kcag_path)
    except (json.JSONDecodeError, ValueError) as e:
        return f"ERROR: {kcag_path} failed to load or run-isolation check ({e}). Refusing to run."
    objs = kcag.get("objective_results", {})
    if not objs:
        return f"ERROR: {kcag_path} has no objective_results — Annex B did not complete successfully."
    try:
        kcag_score_result = extract_kcag_objective_score(kcag)
    except ValueError as exc:
        return f"ERROR: {kcag_path} has an invalid objective score contract ({exc}). Refusing to run."
    kcag_objective_score = kcag_score_result["score"]
    source_field = kcag_score_result["source_field"]
    log("KCAG.objective_traversal_score", kcag_objective_score,
        f"{kcag_path} objective_results (maximum {source_field}; configured heuristic, "
        f"not a calibrated probability)")
    if kcag_score_result["used_legacy_field"]:
        log("KCAG.compatibility", "legacy_field_used",
            "Read legacy top_path_prob as a heuristic traversal score for resume compatibility.")


    try:
        # ---- Defensive multiplier --------------------------------------------
        dm_floor, dm_floor_src = prior("defensive_multiplier_floor")
        dm_scale, dm_scale_src = prior("defensive_multiplier_scale")
        active = sum(1 for v in posture.values() if v)
        total = max(1, len(posture))
        dm = max(dm_floor, 1.0 - (active / total) * dm_scale)
        log("DefensiveMultiplier", round(dm, 4),
            f"{active}/{total} controls active; floor={dm_floor} ({dm_floor_src}); "
            f"scale={dm_scale} ({dm_scale_src})")

        # ---- Build the DAG -----------------------------------------------------
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

        # AdversaryCapability (root, 3 states) -- analyst-supplied, required
        cap = [max(0.001, p) for p in cap_prior]
        s = sum(cap); cap = [p / s for p in cap]
        cpds.append(TabularCPD("AdversaryCapability", 3, [[cap[0]], [cap[1]], [cap[2]]]))
        log("AdversaryCapability", cap, "adversary.capability_prior (analyst-supplied, required)")

        # OperationalTempo (root, 3 states) -- distribution from priors file
        tempo_dist, tempo_src = prior("operational_tempo_distribution", tempo)
        cpds.append(TabularCPD("OperationalTempo", 3, [[p] for p in tempo_dist]))
        log("OperationalTempo", tempo_dist, f"adversary.tempo={tempo}; {tempo_src}")

        # PhishingAttempt | AdversaryCapability -- from priors file
        phish_cpd, phish_src = prior("phishing_given_capability")
        cpds.append(TabularCPD(
            "PhishingAttempt", 2, phish_cpd,
            evidence=["AdversaryCapability"], evidence_card=[3]))
        log("PhishingAttempt|cap", phish_cpd, phish_src)

        # ScanningDetected | OperationalTempo -- from priors file
        scan_cpd, scan_src = prior("scanning_given_tempo")
        cpds.append(TabularCPD(
            "ScanningDetected", 2, scan_cpd,
            evidence=["OperationalTempo"], evidence_card=[3]))
        log("ScanningDetected|tempo", scan_cpd, scan_src)

        # AuthAnomaly (root observable) -- from priors file
        auth_root, auth_src = prior("auth_anomaly_root")
        cpds.append(TabularCPD("AuthAnomaly", 2, [[auth_root[0]], [auth_root[1]]]))
        log("AuthAnomaly", auth_root, auth_src)

        # GeopoliticalTrigger (root) -- analyst-supplied, required
        cpds.append(TabularCPD("GeopoliticalTrigger", 2,
                               [[1 - geo_prior], [geo_prior]]))
        log("GeopoliticalTrigger", [1 - geo_prior, geo_prior],
            "geopolitical_trigger_prior (analyst-supplied, required)")

        # DefensivePosture (root, 3 states weak/moderate/strong from active count)
        dp_floor, dp_floor_src = prior("defensive_posture_floor")
        frac = active / total
        dp = [max(dp_floor, 1 - frac), 0.0, max(dp_floor, frac)]
        dp[1] = max(0.0, 1 - dp[0] - dp[2]); s = sum(dp); dp = [p / s for p in dp]
        cpds.append(TabularCPD("DefensivePosture", 3, [[dp[0]], [dp[1]], [dp[2]]]))
        log("DefensivePosture", dp, f"{active}/{total} controls active; floor={dp_floor} ({dp_floor_src})")

        # KillChainPhase | cap(3) x phish(2) x scan(2) x auth(2) = 24 cols, 4 states
        kcp_base = {
            2: prior("killchain_phase_base", "nation_state"),
            1: prior("killchain_phase_base", "criminal"),
            0: prior("killchain_phase_base", "hacktivist"),
        }
        delta_phish, delta_phish_src = prior("killchain_phase_evidence_delta_phishing")
        delta_scan, delta_scan_src = prior("killchain_phase_evidence_delta_scanning")
        delta_auth, delta_auth_src = prior("killchain_phase_evidence_delta_auth_anomaly")

        def phase_probs(cap_i, phish, scan, auth):
            base = list(kcp_base[cap_i][0])
            if phish:
                base = [b + d for b, d in zip(base, delta_phish)]
            if scan:
                base = [b + d for b, d in zip(base, delta_scan)]
            if auth:
                base = [b + d for b, d in zip(base, delta_auth)]   # auth anomaly => lateral
            base[2] *= dm
            base[3] *= dm * kcag_objective_score                     # KCAG-anchored
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
        log("KillChainPhase", "computed",
            f"base rates: nation_state=({kcp_base[2][1]}), criminal=({kcp_base[1][1]}), "
            f"hacktivist=({kcp_base[0][1]}); deltas: phishing=({delta_phish_src}), "
            f"scanning=({delta_scan_src}), auth_anomaly=({delta_auth_src}); KCAG-anchored")

        # IWEffectAchieved | phase(4) x posture(3) x geo(2) = 24 cols, 2 states
        recon_base, recon_src = prior("iw_effect_phase_base_recon")
        ia_base, ia_src = prior("iw_effect_phase_base_initial_access")
        lat_base, lat_src = prior("iw_effect_phase_base_lateral")
        conv_factor, conv_src = prior("iw_effect_objective_convergence_factor")
        obj_cap, obj_cap_src = prior("iw_effect_objective_cap")
        strong_mult, strong_src = prior("iw_effect_posture_multiplier_strong")
        mod_mult, mod_src = prior("iw_effect_posture_multiplier_moderate")
        geo_mult, geo_mult_src = prior("iw_effect_geo_multiplier")
        geo_cap, geo_cap_src = prior("iw_effect_geo_cap")

        obj_base = round(min(obj_cap, kcag_objective_score * conv_factor), 4)
        PHASE_BASE = [
            log("IWEffect|Recon", recon_base, recon_src),
            log("IWEffect|InitAccess", ia_base, ia_src),
            log("IWEffect|Lateral", lat_base, lat_src),
            log("IWEffect|Objective", obj_base, f"{conv_src} capped by ({obj_cap_src})"),
        ]

        def iw_probs(phase, dposture, geo):
            p = PHASE_BASE[phase]
            if dposture == 2:   p *= strong_mult    # strong defense
            elif dposture == 1: p *= mod_mult        # moderate
            if geo:              p = min(geo_cap, p * geo_mult)
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
        log("IWEffectAchieved", "computed",
            f"phase x posture ({strong_src}; {mod_src}) x geopolitical "
            f"({geo_mult_src}; capped {geo_cap_src})")

    except LookupError as e:
        return f"ERROR: {e}. Refusing to run with an incomplete priors file."

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
        "kcag_objective_score": round(kcag_objective_score, 4),
        "kcag_used_legacy_field": kcag_score_result["used_legacy_field"],
        "defensive_multiplier": round(dm, 4),
        "priors_file": priors_path,
        "cpd_audit_log": AUDIT,
    }
    bbn_report_path = run_context.artifact_path("bbn_report.json")
    run_context.write_stamped_json(bbn_report_path, report)

    lines = [
        "=== ANNEX C: BBN THREAT ASSESSMENT ===",
        f"Threat Score:  {score:.4f}  ({level(score)})",
        f"Baseline:      {base_score:.4f}  (delta {score-base_score:+.4f})",
        f"Likely Phase:  {PHASE_LABELS[phase_idx]}",
        f"KCAG heuristic factor: {kcag_objective_score:.4f}   Defensive mult: {dm:.3f}",
        "Phase distribution:",
        *[f"  {PHASE_LABELS[i]:16s} {float(phase_dist[i]):.4f}" for i in range(4)],
        f"Evidence applied: {ev or '(none — baseline)'}",
        f"Priors file: {priors_path}",
        f"CPD audit entries: {len(AUDIT)} (full log in {bbn_report_path})",
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

    out_path = run_context.artifact_path("stage0_output.json")
    run_context.write_stamped_json(out_path, parsed.model_dump(mode="json"))

    return (f"WRITTEN: {out_path} | "
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

    out_path = run_context.artifact_path("stage1_output.json")
    run_context.write_stamped_json(out_path, parsed.model_dump(mode="json"))

    return (f"WRITTEN: {out_path} | "
            f"{len(parsed.technical_nodes)} technical, {len(parsed.procedural_nodes)} procedural, "
            f"{len(parsed.cognitive_nodes)} cognitive node(s), {len(parsed.trust_boundaries)} trust "
            f"boundary(ies), {parsed.gap_count} flagged [GAP]. "
            f"Cognitive-layer candidate touchpoint: {cog_note}. "
            f"(Note: the graph-theoretic COG is computed by Annex B, not fixed here.) "
            f"Stage 2 may now build on this node inventory.")