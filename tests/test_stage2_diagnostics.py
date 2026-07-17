import json
from pathlib import Path

import pytest

from src import run_context
from src.stage2_diagnostics import (
    describe_missing_stage2_vectors,
)


@pytest.fixture(autouse=True)
def active_run(tmp_path):
    run_context.set_active_run(
        run_id="vaf_test_stage2_diagnostics",
        corpus_manifest_hash="sha256:test-corpus",
        out_dir=str(tmp_path),
    )

    yield tmp_path

    run_context.reset_active_run()


def _paths(tmp_path: Path) -> tuple[str, str, str]:
    return (
        str(tmp_path / "stage2_vectors.json"),
        str(tmp_path / "stage2_writer_status.json"),
        str(tmp_path / "assessment_state.json"),
    )


def test_missing_status_reports_writer_likely_never_called(
    active_run,
):
    vectors_path, status_path, audit_path = _paths(active_run)

    message = describe_missing_stage2_vectors(
        vectors_path=vectors_path,
        writer_status_path=status_path,
        audit_path=audit_path,
    )

    assert vectors_path in message
    assert "likely never called" in message
    assert audit_path in message


def test_rejected_status_reports_validation_errors(active_run):
    vectors_path, status_path, audit_path = _paths(active_run)

    run_context.write_stamped_json(
        status_path,
        {
            "status": "REJECTED",
            "node_count": 7,
            "edge_count": 6,
            "errors": [
                "edge[1] missing required field(s): difficulty",
                "edge[3] missing required field(s): difficulty",
            ],
            "artifact_path": None,
        },
    )

    message = describe_missing_stage2_vectors(
        vectors_path=vectors_path,
        writer_status_path=status_path,
        audit_path=audit_path,
    )

    assert "was called" in message
    assert "REJECTED" in message
    assert "edge[1]" in message
    assert "difficulty" in message
    assert status_path in message


def test_written_status_without_artifact_reports_inconsistency(
    active_run,
):
    vectors_path, status_path, audit_path = _paths(active_run)

    run_context.write_stamped_json(
        status_path,
        {
            "status": "WRITTEN",
            "node_count": 7,
            "edge_count": 6,
            "errors": [],
            "artifact_path": vectors_path,
        },
    )

    message = describe_missing_stage2_vectors(
        vectors_path=vectors_path,
        writer_status_path=status_path,
        audit_path=audit_path,
    )

    assert "reported WRITTEN" in message
    assert "inconsistent writer state" in message
    assert repr(vectors_path) in message


def test_unknown_writer_status_is_rejected(active_run):
    vectors_path, status_path, audit_path = _paths(active_run)

    run_context.write_stamped_json(
        status_path,
        {
            "status": "MAYBE",
            "errors": [],
        },
    )

    message = describe_missing_stage2_vectors(
        vectors_path=vectors_path,
        writer_status_path=status_path,
        audit_path=audit_path,
    )

    assert "unknown status" in message
    assert "'MAYBE'" in message


def test_untrusted_writer_status_is_not_used(active_run):
    vectors_path, status_path, audit_path = _paths(active_run)

    Path(status_path).write_text(
        json.dumps(
            {
                "_meta": {
                    "run_id": "different-run",
                    "corpus_manifest_hash": "sha256:test-corpus",
                },
                "data": {
                    "status": "REJECTED",
                    "errors": ["fabricated diagnostic"],
                },
            }
        )
    )

    message = describe_missing_stage2_vectors(
        vectors_path=vectors_path,
        writer_status_path=status_path,
        audit_path=audit_path,
    )

    assert "could not be trusted" in message
    assert "different-run" in message
    assert "fabricated diagnostic" not in message