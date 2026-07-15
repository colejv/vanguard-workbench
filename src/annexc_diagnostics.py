"""
Diagnostic artifact capture for the Annex C prior proposer.

The first live run against a real corpus is an INSTRUMENTED MODEL
EVALUATION, not merely a pipeline run: the objective is to classify every
failure (truncation, quote drift, malformed vectors, unresolved controls),
not just get a score. This module collects and writes the artifacts needed
to do that.

Because the corpus may be sensitive, everything here is written run-local
under outputs/<run_id>/annexc_proposer/ and NEVER to general/shared logs.
This module performs plain file I/O only — it holds no derivation logic and
makes no pass/fail decisions; it just records what happened.
"""
from __future__ import annotations

import json
import os


class ProposerDiagnostics:
    """Accumulates diagnostic records during a propose_priors_from_corpus run.
    Nothing here affects the derivation outcome -- this is observability
    only, collected in memory and written once at the end (safe because the
    proposer never raises out of its own run; every failure is caught and
    converted into a record)."""

    def __init__(self, *, model: str = ""):
        self.model = model
        self.chunk_manifest: list[dict] = []
        self.truncated_chunks: list[str] = []
        self.failed_chunks: list[str] = []
        self.extraction_records: dict[str, dict] = {}     # chunk_id -> record
        self.synthesis_records: dict[str, dict] = {}       # prior -> record
        self.rejected_candidates: list[dict] = []           # reason-coded rejects
        self.accepted_candidate_count = 0

    # ---- extraction ----

    def record_chunk(self, chunk) -> None:
        self.chunk_manifest.append({
            "chunk_id": chunk.chunk_id, "source_file": chunk.source_file,
            "source_sha256": chunk.source_sha256,
            "start_char": chunk.start_char, "end_char": chunk.end_char,
        })

    def record_extraction(self, *, chunk_id: str, request_prompt: str = "",
                          raw_response: str = "", parsed: dict | None = None,
                          error: str | None = None) -> None:
        self.extraction_records[chunk_id] = {
            "request_prompt_chars": len(request_prompt or ""),
            "raw_response": raw_response,
            "parsed": parsed,
            "error": error,
        }

    def record_truncated(self, chunk_id: str) -> None:
        self.truncated_chunks.append(chunk_id)

    def record_failed_chunk(self, chunk_id: str, reason: str) -> None:
        self.failed_chunks.append(chunk_id)
        rec = self.extraction_records.setdefault(chunk_id, {})
        rec["failure_reason"] = reason

    def record_rejected_candidate(self, *, reason: str, prior: str,
                                   diagnostic: dict) -> None:
        entry = dict(diagnostic)
        entry["reason"] = reason
        entry["prior"] = prior
        self.rejected_candidates.append(entry)

    def record_accepted_candidate(self) -> None:
        self.accepted_candidate_count += 1

    # ---- synthesis ----

    def record_synthesis(self, *, prior: str, request_prompt: str = "",
                         raw_response: str = "", parsed: dict | None = None,
                         error: str | None = None,
                         offered_candidate_ids: list | None = None) -> None:
        self.synthesis_records[prior] = {
            "request_prompt_chars": len(request_prompt or ""),
            "offered_candidate_ids": offered_candidate_ids or [],
            "raw_response": raw_response,
            "parsed": parsed,
            "error": error,
        }

    # ---- summary + write ----

    def summary(self, *, resolved_priors: list, blocked_priors: list) -> dict:
        extracted = self.accepted_candidate_count + len(self.rejected_candidates)
        rate = (self.accepted_candidate_count / extracted) if extracted else None
        return {
            "model": self.model,
            "expected_chunks": len(self.chunk_manifest),
            "successful_chunks": len(self.chunk_manifest) - len(self.failed_chunks),
            "truncated_chunks": list(self.truncated_chunks),
            "failed_chunks": list(self.failed_chunks),
            "extracted_candidates": extracted,
            "verified_candidates": self.accepted_candidate_count,
            "rejected_candidates": len(self.rejected_candidates),
            "quote_verification_rate": rate,
            "synthesis_calls": len(self.synthesis_records),
            "resolved_priors": list(resolved_priors),
            "blocked_priors": list(blocked_priors),
        }

    def write(self, out_dir: str, *, resolved_priors: list, blocked_priors: list) -> str:
        """Write every diagnostic artifact under out_dir/annexc_proposer/.
        Returns that directory path. Run-local only; never a shared log."""
        base = os.path.join(out_dir, "annexc_proposer")
        extraction_dir = os.path.join(base, "extraction")
        synthesis_dir = os.path.join(base, "synthesis")
        os.makedirs(extraction_dir, exist_ok=True)
        os.makedirs(synthesis_dir, exist_ok=True)

        def _dump(path, payload):
            with open(path, "w") as f:
                json.dump(payload, f, indent=2, default=str)

        _dump(os.path.join(base, "chunk_manifest.json"), self.chunk_manifest)

        for chunk_id, rec in self.extraction_records.items():
            safe = chunk_id.replace("/", "_").replace("#", "_")
            _dump(os.path.join(extraction_dir, f"{safe}.raw.json"),
                  {"raw_response": rec.get("raw_response"), "error": rec.get("error")})
            _dump(os.path.join(extraction_dir, f"{safe}.parsed.json"),
                  {"parsed": rec.get("parsed"), "failure_reason": rec.get("failure_reason")})

        for prior, rec in self.synthesis_records.items():
            _dump(os.path.join(synthesis_dir, f"{prior}.raw.json"),
                  {"raw_response": rec.get("raw_response"), "error": rec.get("error")})
            _dump(os.path.join(synthesis_dir, f"{prior}.parsed.json"),
                  {"parsed": rec.get("parsed"),
                   "offered_candidate_ids": rec.get("offered_candidate_ids")})

        _dump(os.path.join(base, "proposer_diagnostics.json"),
              {"rejected_candidates": self.rejected_candidates})

        run_summary = self.summary(resolved_priors=resolved_priors, blocked_priors=blocked_priors)
        _dump(os.path.join(base, "proposer_run.json"), run_summary)

        return base