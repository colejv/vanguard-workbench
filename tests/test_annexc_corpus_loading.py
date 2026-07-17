"""Tests for loading the exact frozen corpus used by Annex C."""

from __future__ import annotations

import hashlib
import json

import pytest

from src.annexc_derivation import (
    DerivationError,
    load_frozen_corpus_sources,
)


def _write_manifest(
    path,
    entries,
):
    payload = {
        "files": entries,
    }

    path.write_text(
        "# Frozen Corpus Manifest\n\n"
        "```json\n"
        + json.dumps(
            payload,
            indent=2,
        )
        + "\n```\n",
        encoding="utf-8",
    )


def test_loads_hash_bound_text_source(
    tmp_path,
):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()

    source_path = (
        source_dir
        / "actor-report.txt"
    )
    source_text = (
        "The actor demonstrated sustained access and "
        "disciplined operational security."
    )

    source_path.write_text(
        source_text,
        encoding="utf-8",
    )

    source_hash = hashlib.sha256(
        source_path.read_bytes()
    ).hexdigest()

    manifest_path = (
        source_dir
        / "corpus_manifest.md"
    )

    _write_manifest(
        manifest_path,
        [
            {
                "file": (
                    "actor-report.txt"
                ),
                "sha256": source_hash,
            }
        ],
    )

    frozen = (
        load_frozen_corpus_sources(
            str(
                tmp_path
                / "outputs"
                / "vaf_test"
            ),
            source_dir=str(source_dir),
            lock_manifest_path=str(
                manifest_path
            ),
        )
    )

    assert set(frozen) == {
        "actor-report.txt"
    }
    assert frozen[
        "actor-report.txt"
    ]["sha256"] == (
        f"sha256:{source_hash}"
    )
    assert frozen[
        "actor-report.txt"
    ]["text"] == source_text


def test_accepts_sha256_prefix(
    tmp_path,
):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()

    source_path = (
        source_dir
        / "actor-report.txt"
    )
    source_path.write_text(
        "Frozen source content.",
        encoding="utf-8",
    )

    source_hash = hashlib.sha256(
        source_path.read_bytes()
    ).hexdigest()

    manifest_path = (
        source_dir
        / "corpus_manifest.md"
    )

    _write_manifest(
        manifest_path,
        [
            {
                "file": (
                    "actor-report.txt"
                ),
                "sha256": (
                    f"sha256:{source_hash}"
                ),
            }
        ],
    )

    frozen = (
        load_frozen_corpus_sources(
            str(
                tmp_path
                / "outputs"
                / "vaf_test"
            ),
            source_dir=str(source_dir),
            lock_manifest_path=str(
                manifest_path
            ),
        )
    )

    assert frozen[
        "actor-report.txt"
    ]["sha256"] == (
        f"sha256:{source_hash}"
    )


def test_rejects_hash_drift(
    tmp_path,
):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()

    source_path = (
        source_dir
        / "actor-report.txt"
    )
    source_path.write_text(
        "changed source content",
        encoding="utf-8",
    )

    manifest_path = (
        source_dir
        / "corpus_manifest.md"
    )

    _write_manifest(
        manifest_path,
        [
            {
                "file": (
                    "actor-report.txt"
                ),
                "sha256": "0" * 64,
            }
        ],
    )

    with pytest.raises(
        DerivationError,
        match="SHA-256 mismatch",
    ):
        load_frozen_corpus_sources(
            str(
                tmp_path
                / "outputs"
                / "vaf_test"
            ),
            source_dir=str(source_dir),
            lock_manifest_path=str(
                manifest_path
            ),
        )


def test_rejects_missing_manifest(
    tmp_path,
):
    with pytest.raises(
        DerivationError,
        match="does not exist",
    ):
        load_frozen_corpus_sources(
            str(
                tmp_path
                / "outputs"
                / "vaf_test"
            ),
            source_dir=str(
                tmp_path
                / "sources"
            ),
            lock_manifest_path=str(
                tmp_path
                / "sources"
                / "corpus_manifest.md"
            ),
        )


def test_rejects_manifest_without_json_block(
    tmp_path,
):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()

    manifest_path = (
        source_dir
        / "corpus_manifest.md"
    )
    manifest_path.write_text(
        "# No JSON here\n",
        encoding="utf-8",
    )

    with pytest.raises(
        DerivationError,
        match="no embedded JSON object",
    ):
        load_frozen_corpus_sources(
            str(
                tmp_path
                / "outputs"
                / "vaf_test"
            ),
            source_dir=str(source_dir),
            lock_manifest_path=str(
                manifest_path
            ),
        )


def test_rejects_zero_sources(
    tmp_path,
):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()

    manifest_path = (
        source_dir
        / "corpus_manifest.md"
    )

    _write_manifest(
        manifest_path,
        [],
    )

    with pytest.raises(
        DerivationError,
        match="no non-empty files list",
    ):
        load_frozen_corpus_sources(
            str(
                tmp_path
                / "outputs"
                / "vaf_test"
            ),
            source_dir=str(source_dir),
            lock_manifest_path=str(
                manifest_path
            ),
        )


def test_rejects_missing_source_file(
    tmp_path,
):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()

    manifest_path = (
        source_dir
        / "corpus_manifest.md"
    )

    _write_manifest(
        manifest_path,
        [
            {
                "file": "missing.txt",
                "sha256": "0" * 64,
            }
        ],
    )

    with pytest.raises(
        DerivationError,
        match="frozen source file is missing",
    ):
        load_frozen_corpus_sources(
            str(
                tmp_path
                / "outputs"
                / "vaf_test"
            ),
            source_dir=str(source_dir),
            lock_manifest_path=str(
                manifest_path
            ),
        )


def test_rejects_empty_extraction(
    tmp_path,
):
    source_dir = tmp_path / "sources"
    source_dir.mkdir()

    source_path = (
        source_dir
        / "empty.txt"
    )
    source_path.write_text(
        "",
        encoding="utf-8",
    )

    source_hash = hashlib.sha256(
        source_path.read_bytes()
    ).hexdigest()

    manifest_path = (
        source_dir
        / "corpus_manifest.md"
    )

    _write_manifest(
        manifest_path,
        [
            {
                "file": "empty.txt",
                "sha256": source_hash,
            }
        ],
    )

    with pytest.raises(
        DerivationError,
        match=(
            "text extraction produced no content"
        ),
    ):
        load_frozen_corpus_sources(
            str(
                tmp_path
                / "outputs"
                / "vaf_test"
            ),
            source_dir=str(source_dir),
            lock_manifest_path=str(
                manifest_path
            ),
        )