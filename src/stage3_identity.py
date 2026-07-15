"""
Semantic-identity immutability for Stage 3 repair.

The single most dangerous failure this pipeline produced: the semantic
repair loop changed RT-003's technique from AML.T0099 (AI Agent Tool Data
Poisoning — the correct binding) to CAPEC-628 (a carry-off GPS attack —
semantically unrelated) purely to force the concept onto a KCAG path that
ended at a goal node. The mutated plan then passed every validator.

The rule this module enforces: the FIRST compiled candidate establishes a
per-concept semantic baseline. Repair may fill omissions and fix structure,
but it may NOT change a concept's semantic identity:

    test_id
    technique_ids
    stage2_vector_ids
    target_node_ids
    categories

If a repaired candidate mutates any of these, repair STOPS with a hard
error. The correct resolution of "correct technique + incomplete KCAG" is
an explicit analytical failure that sends the analyst back to the KCAG or
source analysis — NOT a retry that relabels the technique to close the
graph.

A technique change is only legitimate through a separate, audited
re-analysis operation (new framework lookup + mechanism-match + analyst
approval). That operation is deliberately NOT reachable from the repair
loop — this module provides no path to authorize a mutation.
"""
from collections.abc import Iterable


# The fields that constitute a concept's immutable semantic identity.
IDENTITY_FIELDS = (
    "technique_ids",
    "stage2_vector_ids",
    "target_node_ids",
    "categories",
)


class SemanticIdentityMutation(Exception):
    """Raised when repair attempts to change a concept's semantic identity."""


def _concept_technique_ids(concept: dict) -> list:
    """Extract the technique IDs a concept binds, tolerant of the two shapes
    the schema uses: an explicit technique_ids list, and/or the technique_id
    on each execution_techniques entry."""
    ids = set()
    for t in concept.get("technique_ids", []) or []:
        if t:
            ids.add(t)
    for et in concept.get("execution_techniques", []) or []:
        if isinstance(et, dict) and et.get("technique_id"):
            ids.add(et["technique_id"])
    return sorted(ids)


def _concept_vector_ids(concept: dict) -> list:
    ids = set()
    for v in concept.get("stage2_vector_ids", []) or []:
        if v:
            ids.add(v)
    for et in concept.get("execution_techniques", []) or []:
        if isinstance(et, dict) and et.get("vector_id"):
            ids.add(et["vector_id"])
    return sorted(ids)


def concept_identity(concept: dict) -> dict:
    """Return the semantic-identity fingerprint of a single test concept.
    Order-insensitive (sorted) so a pure reordering is not a mutation."""
    return {
        "technique_ids": _concept_technique_ids(concept),
        "stage2_vector_ids": _concept_vector_ids(concept),
        "target_node_ids": sorted(str(n) for n in (concept.get("target_node_ids") or [])),
        "categories": sorted(concept.get("categories") or []),
    }


def capture_identity_baseline(plan: dict) -> dict:
    """Capture the per-test_id semantic-identity baseline from the FIRST
    compiled candidate. This is the signed baseline repair must preserve."""
    baseline = {}
    for concept in plan.get("test_concepts", []) or []:
        tid = concept.get("test_id")
        if tid:
            baseline[tid] = concept_identity(concept)
    return baseline


def load_or_capture_baseline(*, plan: dict, baseline_path: str,
                             read_stamped_json, write_stamped_json) -> dict:
    """Return the run's authoritative identity baseline, persisting it on
    first capture so it SURVIVES RESUME.

    Without persistence there is a live hole: a resumed run starts with no
    in-memory baseline and would re-capture identity from whatever candidate
    exists now — which, after a repair, could be an already-mutated concept.
    That would silently bless exactly the RT-003 swap this module exists to
    stop. So the baseline is written once, on first capture, and every later
    process (including a resume) loads that persisted baseline rather than
    re-deriving one.

    read_stamped_json/write_stamped_json are injected so this module stays
    free of I/O-layer imports.
    """
    import os
    if os.path.exists(baseline_path):
        try:
            persisted = read_stamped_json(baseline_path)
        except Exception:
            persisted = None
        if persisted:
            # A persisted baseline is authoritative and is never overwritten.
            return persisted

    baseline = capture_identity_baseline(plan)
    write_stamped_json(baseline_path, baseline)
    return baseline


def _diff_identity(test_id: str, base: dict, current: dict) -> list:
    """Return human-readable descriptions of each identity field that changed."""
    changes = []
    for field in IDENTITY_FIELDS:
        if base.get(field) != current.get(field):
            changes.append(
                f"{test_id} attempted {field} change:\n"
                f"  baseline: {base.get(field)}\n"
                f"  repaired: {current.get(field)}"
            )
    return changes


def assert_identity_preserved(baseline: dict, plan: dict) -> None:
    """Compare a repaired candidate against the signed baseline. Raise
    SemanticIdentityMutation (aborting repair) if any concept's semantic
    identity changed, or if a baseline concept vanished / a new one appeared.

    Filling omissions or fixing structure is allowed; changing what a
    concept fundamentally IS (its technique, vectors, targets, category) is
    not — that indicates the repair loop is optimizing for graph closure
    over technique-mechanism fidelity, exactly the RT-003 failure.
    """
    current_by_id = {
        c.get("test_id"): concept_identity(c)
        for c in plan.get("test_concepts", []) or []
        if c.get("test_id")
    }

    problems = []

    # A baseline concept must still exist with the same identity.
    for tid, base in baseline.items():
        if tid not in current_by_id:
            problems.append(f"{tid} was dropped by repair (baseline concept missing).")
            continue
        problems.extend(_diff_identity(tid, base, current_by_id[tid]))

    # Repair must not invent a new test concept either.
    for tid in current_by_id:
        if tid not in baseline:
            problems.append(f"{tid} was added by repair (not in the signed baseline).")

    if problems:
        raise SemanticIdentityMutation(
            "SEMANTIC_IDENTITY_MUTATION\n"
            + "\n".join(problems)
            + "\n\nRepair aborted. A concept's technique/vector/target/category "
            "is immutable during repair. The KCAG or source analysis must be "
            "corrected — a technique binding may only change through an "
            "audited re-analysis, never to close a graph path."
        )