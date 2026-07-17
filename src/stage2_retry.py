"""Run-scoped cleanup for an incomplete Stage 2 attempt."""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src import run_context
from src.schemas import StageStatus


_STAGE2_CANONICAL_ARTIFACTS = (
    "stage2.md",
    "stage2_vectors.json",
    "stage2_verification.md",
    "kcag_validation.json",
    "stage2_writer_status.json",
)

_STAGE2_LEGACY_QUARANTINE_PATTERNS = (
    "stage2.md.rejected_*",
    "stage2_vectors.json.rejected_*",
    "stage2_verification.md.rejected_*",
    "kcag_validation.json.rejected_*",
    "stage2_writer_status.json.rejected_*",
)


def stage2_resume_is_complete(
    *,
    files_present: bool,
    stage_status: StageStatus,
) -> bool:
    """
    Return True only when Stage 2 artifacts exist and the deterministic
    Stage 2 gates previously promoted the stage to PASS.

    File presence alone is insufficient because rejected KCAG artifacts
    may remain on disk after a failed run.
    """

    return (
        files_present
        and stage_status == StageStatus.PASS
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)

    return f"sha256:{digest.hexdigest()}"


def _next_attempt_directory(
    quarantine_root: Path,
) -> Path:
    attempt_number = 1

    while True:
        candidate = (
            quarantine_root
            / f"attempt_{attempt_number:03d}"
        )

        if not candidate.exists():
            return candidate

        attempt_number += 1


def quarantine_incomplete_stage2_attempt(
    *,
    out_dir: str,
    reason: str,
) -> dict[str, Any] | None:
    """
    Move stale Stage 2 artifacts out of canonical locations.

    Returns a summary containing the quarantine directory and manifest
    path. Returns None when there is nothing to quarantine.
    """

    run_dir = Path(out_dir)

    if not run_dir.is_dir():
        raise FileNotFoundError(
            "Stage 2 retry directory does not exist: "
            f"{run_dir}"
        )

    candidates: set[Path] = set()

    for artifact_name in _STAGE2_CANONICAL_ARTIFACTS:
        candidate = run_dir / artifact_name

        if candidate.is_file():
            candidates.add(candidate)

    for pattern in _STAGE2_LEGACY_QUARANTINE_PATTERNS:
        for candidate in run_dir.glob(pattern):
            if candidate.is_file():
                candidates.add(candidate)

    if not candidates:
        return None

    quarantine_root = (
        run_dir
        / "quarantine"
        / "stage2"
    )
    quarantine_root.mkdir(
        parents=True,
        exist_ok=True,
    )

    attempt_dir = _next_attempt_directory(
        quarantine_root
    )
    attempt_dir.mkdir(
        parents=False,
        exist_ok=False,
    )

    moved: list[dict[str, Any]] = []

    for source in sorted(
        candidates,
        key=lambda path: path.name,
    ):
        if source.is_symlink():
            raise RuntimeError(
                "Refusing to quarantine a Stage 2 "
                f"artifact symlink: {source}"
            )

        destination = attempt_dir / source.name

        if destination.exists():
            raise RuntimeError(
                "Stage 2 quarantine destination "
                f"already exists: {destination}"
            )

        entry = {
            "source": str(source),
            "destination": str(destination),
            "size_bytes": source.stat().st_size,
            "sha256": _file_sha256(source),
        }

        # Same-filesystem atomic move. Nothing is deleted.
        os.replace(source, destination)
        moved.append(entry)

    manifest_path = (
        attempt_dir
        / "retry_manifest.json"
    )

    run_context.write_stamped_json(
        str(manifest_path),
        {
            "reason": reason,
            "created_at": datetime.now(
                timezone.utc
            ).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "moved_count": len(moved),
            "moved": moved,
        },
    )

    return {
        "attempt_dir": str(attempt_dir),
        "manifest_path": str(manifest_path),
        "moved_count": len(moved),
        "moved": moved,
    }