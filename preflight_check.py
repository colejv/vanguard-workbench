#!/usr/bin/env python3
"""
Vanguard pre-flight check — run this from the project root BEFORE kicking off
crew.py, to catch the four things a slow local-Ollama run shouldn't have to
discover for you:

  1. Corpus lock status (sources/corpus_manifest.md vs. actual sources/)
  2. config/bbn_priors.json completeness (every prior bbn_threat_score
     actually reads, derived from tools.py itself so this can't drift out
     of sync with the real function)
  3. Whether sources/ contains .pdf files and, if so, whether pypdf is
     installed
  4. A reminder about the one known gap: corpus-lock result isn't yet
     written into assessment_state.json

No CrewAI kickoff, no Ollama calls — this only touches the filesystem and
reuses the real functions from src.tools (not a reimplementation), so a
PASS here means the actual gates will also pass, not just this script's
own guess.

Usage:  python3 preflight_check.py
Exit code 0 if everything is clear to run, 1 if something needs attention.
"""
import os
import re
import sys
import json

FAILED = False


def section(title):
    print(f"\n{'='*70}\n{title}\n{'='*70}")


def ok(msg):
    print(f"  [OK]   {msg}")


def warn(msg):
    print(f"  [WARN] {msg}")


def fail(msg):
    global FAILED
    FAILED = True
    print(f"  [FAIL] {msg}")


# ---------------------------------------------------------------------------
# 1. CORPUS LOCK
# ---------------------------------------------------------------------------
section("1. Corpus lock (sources/corpus_manifest.md)")
try:
    from src.tools import discover_corpus_files, verify_corpus_lock_gate
except ImportError as e:
    fail(f"Could not import from src.tools ({e}). Run this from the project "
         f"root with the same environment crew.py uses.")
    discover_corpus_files = verify_corpus_lock_gate = None

if verify_corpus_lock_gate is not None:
    if not os.path.exists("sources/corpus_manifest.md"):
        fail("sources/corpus_manifest.md not found. The corpus has not been "
             "locked yet — Gate 1 will halt the real run here too.")
    else:
        lock = verify_corpus_lock_gate()
        if lock["is_valid"]:
            ok(lock["summary"])
        else:
            fail(lock["summary"])
            if lock["missing"]:
                print(f"         missing: {lock['missing'][:10]}"
                      f"{' ...' if len(lock['missing']) > 10 else ''}")
            if lock["added"]:
                print(f"         added:   {lock['added'][:10]}"
                      f"{' ...' if len(lock['added']) > 10 else ''}")
            if lock["changed"]:
                print(f"         changed: {lock['changed'][:10]}"
                      f"{' ...' if len(lock['changed']) > 10 else ''}")

    if os.path.exists("sources"):
        n = len(discover_corpus_files("sources"))
        print(f"  ({n} files currently in sources/ match the "
              f".md/.txt/.pdf/.json discovery filter)")


# ---------------------------------------------------------------------------
# 2. BBN PRIORS COMPLETENESS
# ---------------------------------------------------------------------------
section("2. config/bbn_priors.json completeness")

PRIORS_PATH = "config/bbn_priors.json"
TOOLS_PATH = "src/tools.py"

if not os.path.exists(PRIORS_PATH):
    fail(f"{PRIORS_PATH} not found. bbn_threat_score will refuse to run "
         f"without it (by design — no embedded fallback).")
elif not os.path.exists(TOOLS_PATH):
    warn(f"{TOOLS_PATH} not found from this working directory — can't "
         f"derive the required-key list. Run from the project root.")
else:
    try:
        priors_doc = json.load(open(PRIORS_PATH))
        priors = priors_doc["priors"]
    except (json.JSONDecodeError, KeyError) as e:
        fail(f"{PRIORS_PATH} malformed or missing 'priors' key ({e}).")
        priors = None

    if priors is not None:
        # Derive the required path list from the live function itself, not
        # a hand-maintained copy, so this check can't silently go stale.
        src = open(TOOLS_PATH).read()
        s = src.index('@tool("bbn_threat_score")')
        e = src.index('\n\n\n# --- write_stage0_output')
        block = src[s:e]

        static_calls = re.findall(r'prior\(((?:"[^"]*"(?:,\s*)?)+)\)', block)
        paths = [tuple(a.strip().strip('"') for a in c.split(",") if a.strip())
                 for c in static_calls]
        # The one dynamic call (tempo is a runtime variable, not a literal):
        # prior("operational_tempo_distribution", tempo) -- check all three
        # values it could resolve to at runtime.
        for t in ("LOW", "MEDIUM", "HIGH"):
            paths.append(("operational_tempo_distribution", t))

        n_ok, n_missing = 0, 0
        for path in paths:
            node = priors
            found = True
            for key in path:
                if not isinstance(node, dict) or key not in node:
                    found = False
                    break
                node = node[key]
            if found and isinstance(node, dict) and "value" in node:
                n_ok += 1
            else:
                n_missing += 1
                fail(f"required prior '{'.'.join(path)}' missing or malformed "
                     f"in {PRIORS_PATH}")

        if n_missing == 0:
            ok(f"all {n_ok} required priors present (derived live from "
               f"{TOOLS_PATH}'s actual prior() calls)")


# ---------------------------------------------------------------------------
# 3. PDF SOURCES / pypdf
# ---------------------------------------------------------------------------
section("3. PDF sources / pypdf")
if os.path.exists("sources"):
    pdfs = [f for f in os.listdir("sources") if f.endswith(".pdf")]
    if not pdfs:
        ok("no .pdf files in sources/ — pypdf not required for this run")
    else:
        try:
            import pypdf  # noqa: F401
            ok(f"{len(pdfs)} PDF source(s) found and pypdf is installed")
        except ImportError:
            fail(f"{len(pdfs)} PDF source(s) found in sources/ but pypdf is "
                 f"not installed. read_corpus_file will raise on the first "
                 f"one. Run: pip install pypdf --break-system-packages")
else:
    warn("sources/ directory not found — skipping PDF check")


# ---------------------------------------------------------------------------
# 4. KNOWN GAP REMINDER (not a failure)
# ---------------------------------------------------------------------------
section("4. Known gaps (informational only)")
warn("Corpus-lock result does not write into assessment_state.json — not "
     "because the wiring is missing (schemas.py/state.py are the real "
     "files now), but because STAGE_NAMES is ('stage0','stage1','stage2',"
     "'stage3') and corpus_lock isn't one of them. A lock failure still "
     "halts the run via RuntimeError; it just isn't a row in the audit "
     "trail's stages dict.")
warn("Item 8's Phase 0 Safety Gate check fires AFTER t_stage3/t_stage4's "
     "human_input approvals already happened inside post_crew.kickoff(). "
     "A non-compliant kinetic payload will still halt the run, but only "
     "after you've already approved both gates.")
warn("NEW since run-isolation: several task descriptions (t_annexB, "
     "t_annexC) now tell the agent to call tools with NO path argument, "
     "relying on automatic run-scoped path resolution, instead of stating "
     "an explicit path like before. This hasn't been tested against a real "
     "local model. If the model supplies its own (stale-style, unscoped) "
     "path anyway, the tool will cleanly return a 'not found' ERROR the "
     "agent can see and retry from — not a silent bug — but it may cost a "
     "wasted tool-call cycle. Worth watching the first real run for this.")


# ---------------------------------------------------------------------------
# 5. ASSESSMENT BRIEF
# ---------------------------------------------------------------------------
section("5. Assessment brief (collection/brief.md)")
if os.path.exists("collection/brief.md"):
    ok("collection/brief.md found")
else:
    fail("collection/brief.md not found. crew.py reads this unconditionally "
         "near the top of __main__, before any gate — a missing file here "
         "is an unhandled FileNotFoundError, not a clean error message.")


# ---------------------------------------------------------------------------
# 6. IMPORT SMOKE TEST
# ---------------------------------------------------------------------------
# The single cheapest, highest-value check possible: does the whole module
# graph even resolve? This is what caught the agents.py stale-import
# regression during development — a broken import is a syntax-valid,
# py_compile-clean file that still can't actually run.
section("6. Import smoke test (python -c \"import src.crew\")")
try:
    import subprocess
    result = subprocess.run(
        [sys.executable, "-c", "import src.crew"],
        capture_output=True, text=True, timeout=30,
    )
    if result.returncode == 0:
        ok("import src.crew succeeded")
    else:
        fail(f"import src.crew failed:\n{result.stderr.strip()[-800:]}")
except Exception as e:
    warn(f"could not run the import smoke test ({e}) — run it manually: "
         f"python -c \"import src.crew\"")


# ---------------------------------------------------------------------------
section("SUMMARY")
if FAILED:
    print("  Result: NOT CLEAR TO RUN — see [FAIL] items above.")
    sys.exit(1)
else:
    print("  Result: CLEAR TO RUN.")
    sys.exit(0)