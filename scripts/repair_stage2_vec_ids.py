"""
Audited, deterministic repair for single-digit vec IDs in an existing
run's stage2_vectors.json.

CONTEXT
-------
Runs produced before write_stage2_vectors() gained V-N -> V-0N
normalization can contain single-digit vec IDs (V-1..V-9) that the KCAG
structural gate rejects (KCAG_VECTOR_ID_PATTERN = ^V-\\d{2,}$). Resume
detection sees an existing stage2_vectors.json and skips Stage 2, so it
would just re-validate the same failing artifact forever. This script
performs a controlled, auditable repair instead of a hand-edit.

WHAT IT DOES (and deliberately does NOT do)
-------------------------------------------
- Reads the existing stamped stage2_vectors.json for the given run,
  enforcing the same _meta run/corpus binding as read_stamped_json().
- Applies ONLY normalize_vec_id() from tools.py — the exact same narrow
  V-<one digit> -> V-0<digit> rule the writer now uses. Nothing else in
  the artifact is touched.
- Rejects (aborts, writes nothing) if normalization would create a vec
  collision, mirroring the writer's own post-normalization duplicate
  check — so a repair can never silently merge two distinct vectors.
- Re-stamps via write_stamped_json() so the artifact stays a valid,
  run-bound stamped envelope (no bypass of stamp_json()).
- Prints a full before/after diff of every changed vec for the audit
  trail, and leaves a .prerepair backup.

It does NOT re-run the Stage 2 gates itself — after this script exits 0,
re-run the pipeline with --resume so verify_stage2_vectors() and
validate_kcag() re-check the repaired artifact through the normal path.

USAGE
-----
    python -m scripts.repair_stage2_vec_ids <run_id>
    # e.g. python -m scripts.repair_stage2_vec_ids vaf_20260714_165237
"""
import json
import os
import shutil
import sys

from src import run_context
from src.tools import normalize_vec_id


def repair(run_id: str) -> int:
    out_dir = os.path.join("outputs", run_id)
    artifact_path = os.path.join(out_dir, "stage2_vectors.json")

    if not os.path.exists(artifact_path):
        print(f"ERROR: {artifact_path} does not exist.", file=sys.stderr)
        return 2

    # Read the raw envelope first to recover its _meta binding, so we can
    # activate the SAME run/corpus the artifact was stamped under and let
    # read_stamped_json() enforce the binding rather than bypass it.
    with open(artifact_path) as f:
        envelope = json.load(f)
    meta = envelope.get("_meta")
    if not meta:
        print(f"ERROR: {artifact_path} has no _meta block — refusing to "
              f"repair an unstamped artifact.", file=sys.stderr)
        return 2

    run_context.reset_active_run()
    run_context.set_active_run(
        run_id=meta["run_id"],
        corpus_manifest_hash=meta["corpus_manifest_hash"],
        out_dir=out_dir,
    )

    data = run_context.read_stamped_json(artifact_path)
    edges = data.get("edges", [])

    # Apply the narrow normalization and record every change.
    changes = []
    seen_vecs = set()
    collisions = []
    for i, e in enumerate(edges):
        if not isinstance(e, dict):
            continue
        old = str(e.get("vec", ""))
        new = normalize_vec_id(old)
        if new != old:
            changes.append((i, old, new))
            e["vec"] = new
        if new in seen_vecs:
            collisions.append((i, new))
        seen_vecs.add(new)

    if collisions:
        print("ABORT: normalization would create vec collision(s); "
              "nothing written:", file=sys.stderr)
        for i, v in collisions:
            print(f"  - edge[{i}] collides on '{v}'", file=sys.stderr)
        return 3

    if not changes:
        print(f"No single-digit vec IDs found in {artifact_path}. "
              f"Nothing to repair.")
        return 0

    print(f"Repairing {len(changes)} vec ID(s) in {artifact_path}:")
    for i, old, new in changes:
        print(f"  edge[{i}]: {old} -> {new}")

    # Backup, then re-stamp the repaired data through the normal writer.
    backup_path = artifact_path + ".prerepair"
    shutil.copy2(artifact_path, backup_path)
    print(f"Backup written: {backup_path}")

    run_context.write_stamped_json(artifact_path, data)
    print(f"Repaired and re-stamped: {artifact_path}")

    # Verify the re-stamped artifact reads back cleanly.
    reread = run_context.read_stamped_json(artifact_path)
    assert [e.get("vec") for e in reread["edges"]] == [e.get("vec") for e in edges], \
        "read-back mismatch after repair"
    print("Read-back verification: OK")
    print()
    print("Next step: re-run the pipeline with --resume so the Stage 2 "
          "gates re-validate the repaired artifact:")
    print(f"  python -m src.crew --resume {run_id}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        print("ERROR: exactly one argument (run_id) required.", file=sys.stderr)
        sys.exit(1)
    sys.exit(repair(sys.argv[1]))