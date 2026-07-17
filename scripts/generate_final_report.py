from __future__ import annotations

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(
        0,
        str(REPOSITORY_ROOT),
    )

from config.llm import reason_llm
from src import run_context
from src.final_report import (
    ARTIFACT_INVENTORY_NAME,
    COMPLETION_NAME,
    FINAL_CONTEXT_NAME,
    FINAL_JSON_NAME,
    FINAL_MARKDOWN_NAME,
    FINAL_VALIDATION_NAME,
    generate_and_validate_final_report,
)


def fail(message: str) -> None:
    raise SystemExit(
        f"\nERROR: {message}\n"
    )


run_id = os.environ.get("RUN")

if not run_id:
    fail(
        "Set RUN to the completed assessment run ID."
    )

run_dir = REPOSITORY_ROOT / "outputs" / run_id
state_path = run_dir / "assessment_state.json"

if not state_path.is_file():
    fail(
        f"Assessment state not found: {state_path}"
    )

state = json.loads(
    state_path.read_text(
        encoding="utf-8"
    )
)

if state.get("run_id") != run_id:
    fail(
        "assessment_state.json run_id does not "
        "match RUN."
    )

corpus_hash = state.get(
    "corpus_manifest_hash"
)

if not isinstance(corpus_hash, str):
    fail(
        "assessment_state.json has no corpus "
        "manifest hash."
    )

run_context.set_active_run(
    run_id=run_id,
    corpus_manifest_hash=corpus_hash,
    out_dir=str(run_dir),
)

timestamp = datetime.now(
    timezone.utc
).strftime("%Y%m%dT%H%M%SZ")

backup_dir = (
    run_dir
    / "quarantine"
    / "final-report-regeneration"
    / timestamp
)

final_artifacts = (
    FINAL_CONTEXT_NAME,
    ARTIFACT_INVENTORY_NAME,
    FINAL_JSON_NAME,
    FINAL_MARKDOWN_NAME,
    FINAL_VALIDATION_NAME,
    COMPLETION_NAME,
)

existing = [
    run_dir / name
    for name in final_artifacts
    if (run_dir / name).exists()
]

if existing:
    backup_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    for path in existing:
        shutil.move(
            str(path),
            str(
                backup_dir / path.name
            ),
        )

    print(
        "Previous final-report artifacts "
        f"quarantined: {backup_dir}"
    )

print(
    "Building canonical final-report context...",
    flush=True,
)

timeout_seconds = int(
    os.environ.get(
        "FINAL_REPORT_TIMEOUT_SECONDS",
        "600",
    )
)

print(
    "Ollama synthesis timeout: "
    f"{timeout_seconds} seconds",
    flush=True,
)

outputs = generate_and_validate_final_report(
    out_dir=str(run_dir),
    llm=reason_llm,
    timeout_seconds=timeout_seconds,
)

print()
print("=== FINAL REPORT COMPLETE ===")

for name, path in outputs.items():
    print(f"{name}: {path}")

print()
print("Execution authorization: NOT_GRANTED")
