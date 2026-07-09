#!/usr/bin/env python3
"""
Vanguard pre-flight check — run this from the project root BEFORE kicking off
crew.py, to catch the four things a slow local-Ollama run shouldn't have to
discover for you:

  1. Corpus lock status (sources/corpus_manifest.md vs. actual sources/)
  2. config/bbn_priors.json deterministic numeric validation -- shape,
     range, probability/delta sums, CPD column sums, provenance, and
     cross-field modeling invariants, via the SAME validator function
     bbn_threat_score() itself calls at runtime (src/bbn_validation.py),
     not a separate presence-only check that could drift out of sync
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
# 2. BBN PRIORS DETERMINISTIC VALIDATION
# ---------------------------------------------------------------------------
section("2. config/bbn_priors.json deterministic validation")

PRIORS_PATH = "config/bbn_priors.json"

if not os.path.exists(PRIORS_PATH):
    fail(f"{PRIORS_PATH} not found. bbn_threat_score will refuse to run "
         f"without it (by design — no embedded fallback).")
else:
    try:
        priors_doc = json.load(open(PRIORS_PATH))
    except json.JSONDecodeError as e:
        fail(f"{PRIORS_PATH} is not valid JSON ({e}).")
        priors_doc = None

    if priors_doc is not None:
        try:
            from src.bbn_validation import validate_bbn_priors_document
        except ImportError as e:
            fail(f"Could not import validate_bbn_priors_document from "
                 f"src.bbn_validation ({e}). Run this from the project root "
                 f"with the same environment crew.py uses.")
            validate_bbn_priors_document = None

        if validate_bbn_priors_document is not None:
            # Same function bbn_threat_score() itself calls at runtime -- a
            # PASS here means the real Annex C gate will also pass on this
            # file, not just this script's own guess. Deliberately not a
            # second, independent implementation of "is this prior valid."
            validation = validate_bbn_priors_document(priors_doc)
            if validation["is_valid"]:
                ok(f"{validation['summary']}")
            else:
                fail(f"BBN priors validation: FAIL "
                     f"({len(validation['errors'])} error(s), "
                     f"{validation['checked_fields']} field(s) checked)")
                for error in validation["errors"]:
                    print(f"         {error['path']}: {error['message']} [{error['code']}]")


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