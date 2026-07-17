from pathlib import Path

import pytest

from src import run_context
from src.schemas import StageStatus
from src.stage2_retry import (
    quarantine_incomplete_stage2_attempt,
    stage2_resume_is_complete,
)
from src.state import (
    init_assessment_state,
    reset_stage_for_retry,
)


@pytest.fixture(autouse=True)
def active_run(tmp_path):
    run_context.set_active_run(
        run_id="vaf_test_stage2_retry",
        corpus_manifest_hash=(
            "sha256:test-corpus"
        ),
        out_dir=str(tmp_path),
    )

    yield tmp_path

    run_context.reset_active_run()


@pytest.mark.parametrize(
    (
        "files_present",
        "stage_status",
        "expected",
    ),
    [
        (
            True,
            StageStatus.PASS,
            True,
        ),
        (
            True,
            StageStatus.FAIL,
            False,
        ),
        (
            True,
            StageStatus.PENDING,
            False,
        ),
        (
            True,
            StageStatus.BLOCKED,
            False,
        ),
        (
            False,
            StageStatus.PASS,
            False,
        ),
        (
            False,
            StageStatus.FAIL,
            False,
        ),
    ],
)
def test_stage2_resume_requires_files_and_pass_status(
    files_present,
    stage_status,
    expected,
):
    assert (
        stage2_resume_is_complete(
            files_present=files_present,
            stage_status=stage_status,
        )
        is expected
    )


def test_quarantines_active_and_legacy_stage2_artifacts(
    active_run,
):
    stale_files = {
        "stage2.md": (
            "latest rejected prose"
        ),
        "stage2_vectors.json": (
            "latest rejected graph"
        ),
        "stage2_verification.md": (
            "stale verification"
        ),
        "kcag_validation.json": (
            "stale validation"
        ),
        "stage2_writer_status.json": (
            "stale writer status"
        ),
        "stage2.md.rejected_orphan_nodes": (
            "older prose"
        ),
        (
            "stage2_vectors.json."
            "rejected_orphan_nodes"
        ): "older graph",
        (
            "kcag_validation.json."
            "rejected_orphan_nodes"
        ): "older validation",
    }

    for filename, content in stale_files.items():
        (
            active_run
            / filename
        ).write_text(content)

    (
        active_run
        / "heartbeat.log"
    ).write_text("heartbeat")

    (
        active_run
        / "stage2.first-attempt.md"
    ).write_text(
        "preserved first attempt"
    )

    result = (
        quarantine_incomplete_stage2_attempt(
            out_dir=str(active_run),
            reason="test_retry",
        )
    )

    assert result is not None
    assert (
        result["moved_count"]
        == len(stale_files)
    )

    attempt_dir = Path(
        result["attempt_dir"]
    )

    for filename, content in stale_files.items():
        assert not (
            active_run
            / filename
        ).exists()

        assert (
            attempt_dir
            / filename
        ).read_text() == content

    assert (
        active_run
        / "heartbeat.log"
    ).read_text() == "heartbeat"

    assert (
        active_run
        / "stage2.first-attempt.md"
    ).read_text() == (
        "preserved first attempt"
    )

    manifest = run_context.read_stamped_json(
        result["manifest_path"]
    )

    assert manifest["reason"] == "test_retry"
    assert (
        manifest["moved_count"]
        == len(stale_files)
    )
    assert (
        len(manifest["moved"])
        == len(stale_files)
    )

    for entry in manifest["moved"]:
        assert entry["sha256"].startswith(
            "sha256:"
        )
        assert entry["size_bytes"] > 0


def test_quarantine_is_noop_when_no_stage2_artifacts_exist(
    active_run,
):
    (
        active_run
        / "heartbeat.log"
    ).write_text("keep")

    result = (
        quarantine_incomplete_stage2_attempt(
            out_dir=str(active_run),
            reason="test_retry",
        )
    )

    assert result is None
    assert (
        active_run
        / "heartbeat.log"
    ).exists()
    assert not (
        active_run
        / "quarantine"
    ).exists()


def test_each_retry_uses_a_new_attempt_directory(
    active_run,
):
    (
        active_run
        / "stage2.md"
    ).write_text("attempt one")

    first = (
        quarantine_incomplete_stage2_attempt(
            out_dir=str(active_run),
            reason="first_retry",
        )
    )

    (
        active_run
        / "stage2.md"
    ).write_text("attempt two")

    second = (
        quarantine_incomplete_stage2_attempt(
            out_dir=str(active_run),
            reason="second_retry",
        )
    )

    assert first is not None
    assert second is not None

    assert (
        Path(first["attempt_dir"]).name
        == "attempt_001"
    )
    assert (
        Path(second["attempt_dir"]).name
        == "attempt_002"
    )


def test_reset_stage_for_retry_clears_old_artifact_identity():
    state = init_assessment_state(
        run_id="vaf_test_stage2_retry",
        corpus_manifest_hash=(
            "sha256:test-corpus"
        ),
    )

    stage2 = state.stages["stage2"]
    stage2.status = StageStatus.FAIL
    stage2.output_path = (
        "outputs/vaf_test_stage2_retry/"
        "stage2_vectors.json"
    )
    stage2.output_hash = (
        "sha256:old-rejected-output"
    )
    stage2.committed_at = (
        "2026-07-15T12:00:00Z"
    )
    stage2.schema_version = "1.0"
    stage2.gap_count = 3

    reset_stage_for_retry(
        state,
        "stage2",
        reason=(
            "resume_incomplete_stage2"
        ),
        quarantine_manifest=(
            "outputs/"
            "vaf_test_stage2_retry/"
            "quarantine/stage2/"
            "attempt_001/"
            "retry_manifest.json"
        ),
    )

    reset_record = state.stages["stage2"]

    assert (
        reset_record.status
        == StageStatus.PENDING
    )
    assert reset_record.output_path is None
    assert reset_record.output_hash is None
    assert reset_record.committed_at is None
    assert reset_record.schema_version is None
    assert reset_record.gap_count == 0
    assert state.current_stage == "stage2"

    event = state.gate_decisions[-1]

    assert (
        event["decision_type"]
        == "STAGE_RETRY"
    )
    assert event["stage"] == "stage2"
    assert (
        event["previous_status"]
        == "FAIL"
    )
    assert (
        event["previous_output_hash"]
        == "sha256:old-rejected-output"
    )
    assert event[
        "quarantine_manifest"
    ].endswith(
        "attempt_001/retry_manifest.json"
    )