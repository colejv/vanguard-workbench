"""
Process-global pointer to the currently active run, plus artifact
stamping/verification helpers.

WHY THIS EXISTS: tool functions are called by agents deep inside a
Crew.kickoff() call, several stack frames away from crew.py's __main__
block where run_id is generated. Threading run_id through every single
tool-call argument would work, but it means every task description has to
explicitly tell a local, resource-constrained model to pass a run_id string
on every call -- more surface area for the exact kind of malformed-tool-call
problem max_iter=40 already exists to work around (see agents.py's
decomposer comment).

Instead: crew.py calls set_active_run() exactly once, right after
new_run_id() and before any task or tool executes. Tools resolve their own
run-scoped paths via artifact_path(), using a None-sentinel default
argument pattern (see tools.py) -- the agent still calls e.g. kcag_min_cut()
with no path argument, exactly as before; the tool silently resolves it to
the CURRENT run's directory instead of a shared, collision-prone path.

FAIL CLOSED: get_active_run() raises if no run is active. There is no
fallback to a bare "outputs/" directory anywhere in this module -- an
unscoped write is exactly the bug this file exists to make impossible.

ARTIFACT STAMPING: every JSON artifact this pipeline writes gets wrapped as
{"_meta": {run_id, corpus_manifest_hash, generated_at, schema_version},
"data": <payload>}. Every reader goes through read_stamped_json(), which
verifies _meta against the active run and raises on any mismatch -- this is
the "reject artifacts whose run_id or corpus hash does not match the active
assessment" requirement, enforced at read time, not just by directory
structure. Prose (.md) artifacts get an equivalent HTML-comment header via
stamp_prose_file()/read_stamped_prose(), since CrewAI writes those directly
from an agent's final answer and can't be routed through a Python writer.
"""
from __future__ import annotations

import os
import re
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class ActiveRun:
    run_id: str
    corpus_manifest_hash: str
    out_dir: str


_active: Optional[ActiveRun] = None


def set_active_run(run_id: str, corpus_manifest_hash: str, out_dir: str) -> None:
    """Called exactly once by crew.py, right after run_id/out_dir are known
    and before any task runs."""
    global _active
    os.makedirs(out_dir, exist_ok=True)
    _active = ActiveRun(run_id=run_id, corpus_manifest_hash=corpus_manifest_hash, out_dir=out_dir)


def get_active_run() -> ActiveRun:
    if _active is None:
        raise RuntimeError(
            "No active run set. crew.py must call run_context.set_active_run(...) "
            "before any task or tool runs. Refusing to fall back to a shared, "
            "unscoped output path — that fallback is the exact bug run-isolation "
            "exists to remove."
        )
    return _active


def reset_active_run() -> None:
    """Test-only: clear the active run so test cases don't leak state into
    each other. Never called anywhere in the real pipeline."""
    global _active
    _active = None


def artifact_path(filename: str) -> str:
    """Resolve a logical artifact filename (e.g. 'stage2_vectors.json') to
    its path under the active run's directory. Tools call this instead of
    hardcoding 'outputs/<filename>' — that hardcoded pattern is exactly what
    caused the original cross-run collision risk."""
    run = get_active_run()
    return os.path.join(run.out_dir, filename)


# ---------------------------------------------------------------------------
# JSON artifact stamping / verification
# ---------------------------------------------------------------------------

def stamp_json(payload: dict, schema_version: str = "1.0") -> dict:
    """Wrap a payload dict with run-isolation metadata before writing.
    Never mutates the caller's pydantic-validated payload shape — this
    wraps it as a sibling, so Stage0Output/Stage1Output's extra="forbid"
    is never touched."""
    run = get_active_run()
    return {
        "_meta": {
            "run_id": run.run_id,
            "corpus_manifest_hash": run.corpus_manifest_hash,
            "generated_at": _utcnow_iso(),
            "schema_version": schema_version,
        },
        "data": payload,
    }


def write_stamped_json(path: str, payload: dict, schema_version: str = "1.0") -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(stamp_json(payload, schema_version), f, indent=2)


def read_stamped_json(path: str) -> dict:
    """Read a stamped JSON artifact and return its 'data' payload, after
    verifying _meta.run_id and _meta.corpus_manifest_hash match the active
    run. Raises on any mismatch, missing _meta, or missing file — this is
    the actual enforcement point, not just directory-based isolation."""
    run = get_active_run()
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} not found.")
    with open(path) as f:
        envelope = json.load(f)

    meta = envelope.get("_meta")
    if not meta:
        raise ValueError(
            f"{path} has no '_meta' block — this artifact predates run "
            f"isolation or was written by a tool that bypassed stamp_json(). "
            f"Refusing to trust an unstamped artifact."
        )
    if meta.get("run_id") != run.run_id:
        raise ValueError(
            f"{path} belongs to run '{meta.get('run_id')}', but the active "
            f"run is '{run.run_id}'. Refusing to read another run's artifact."
        )
    if meta.get("corpus_manifest_hash") != run.corpus_manifest_hash:
        raise ValueError(
            f"{path} was generated against corpus hash "
            f"'{meta.get('corpus_manifest_hash')}', but the active run's "
            f"corpus hash is '{run.corpus_manifest_hash}'. Refusing to read "
            f"an artifact generated against a different corpus snapshot."
        )
    if "data" not in envelope:
        raise ValueError(f"{path} has a '_meta' block but no 'data' payload.")
    return envelope["data"]


# ---------------------------------------------------------------------------
# Prose (.md) artifact stamping / verification
# ---------------------------------------------------------------------------
# CrewAI writes task output_file content directly from the agent's final
# answer text -- there's no Python write call to route through
# write_stamped_json for these. Post-process instead: crew.py calls
# stamp_prose_file() on each known prose output right after the crew that
# produced it finishes, prepending an HTML-comment metadata header. This is
# deterministic Python doing the stamping, not something asked of the model.

_PROSE_HEADER_RE = re.compile(
    r'^<!--\s*run_id:\s*(\S+)\s*\|\s*corpus_hash:\s*(\S+)\s*\|\s*'
    r'generated_at:\s*(\S+)\s*\|\s*schema_version:\s*(\S+)\s*-->\n'
)


def stamp_prose_file(path: str, schema_version: str = "1.0") -> None:
    """Prepend a metadata header to an existing prose artifact, unless it
    already has one (idempotent — safe to call more than once on the same
    file, e.g. if a retry re-triggers stamping)."""
    run = get_active_run()
    if not os.path.exists(path):
        return  # nothing to stamp; caller already warns on missing artifacts
    with open(path) as f:
        content = f.read()
    if _PROSE_HEADER_RE.match(content):
        return  # already stamped
    header = (f"<!-- run_id: {run.run_id} | corpus_hash: {run.corpus_manifest_hash} "
              f"| generated_at: {_utcnow_iso()} | schema_version: {schema_version} -->\n")
    with open(path, "w") as f:
        f.write(header + content)


def read_stamped_prose(path: str) -> str:
    """Read a prose artifact and verify its metadata header matches the
    active run, same enforcement as read_stamped_json but for .md files.
    Returns the body with the header stripped."""
    run = get_active_run()
    if not os.path.exists(path):
        raise FileNotFoundError(f"{path} not found.")
    with open(path) as f:
        content = f.read()
    m = _PROSE_HEADER_RE.match(content)
    if not m:
        raise ValueError(
            f"{path} has no run-isolation header — refusing to trust an "
            f"unstamped artifact. Call stamp_prose_file() on it first."
        )
    header_run_id, header_corpus_hash = m.group(1), m.group(2)
    if header_run_id != run.run_id:
        raise ValueError(
            f"{path} belongs to run '{header_run_id}', but the active run "
            f"is '{run.run_id}'. Refusing to read another run's artifact."
        )
    if header_corpus_hash != run.corpus_manifest_hash:
        raise ValueError(
            f"{path} was generated against corpus hash '{header_corpus_hash}', "
            f"but the active run's corpus hash is '{run.corpus_manifest_hash}'. "
            f"Refusing to read an artifact generated against a different "
            f"corpus snapshot."
        )
    return content[m.end():]