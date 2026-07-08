"""
Scoped smoke test for the assessment-state integration — extends through
Stage 1.

Runs: corpus snapshot -> run_id/state init -> t_research -> a SMALL number
of chunk tasks -> t_synthesize_stage0 -> t_stage1.

Stops there. Does NOT run Stage 2, Annex B/C, or Stage 3/4 — this is meant
to answer one question with real agents and a real (small) corpus slice:
does write_stage1_output converge against a real model now that decomposer
has cache=False/max_iter=40, and does assessment_state.json correctly
record BOTH Stage 0 and Stage 1?

Usage:
    python smoke_test_stage1.py

Safe to run repeatedly — each run gets its own run_id. Writes into your
real outputs/ and corpus-index/ directories (same as crew.py) — this is
not a sandboxed dry run.

MAX_CHUNKS below controls how much of your real corpus gets sent to the
decomposer agent. Kept small for a smoke test; t_stage1 will only be as
rich as the scratchpad it's built from.
"""

import os
import sys
import glob
import json
import hashlib

from crewai import Crew, Process, Task
from src.agents import researcher, decomposer
from src.tasks import t_research, t_synthesize_stage0, t_stage1
from src.tools import extract_to_scratch
from src.schemas import StageStatus
from src.state import (new_run_id, run_output_dir, init_assessment_state,
                        save_assessment_state, commit_stage_output)

MAX_CHUNKS = 2  # how many corpus chunks to actually process — keep small for a smoke test


def snapshot_corpus(src_dir="sources", index_dir="corpus-index"):
    """Identical to crew.py's snapshot_corpus — duplicated here rather than
    imported since it's defined inline inside crew.py's __main__ block."""
    os.makedirs(index_dir, exist_ok=True)

    def hash_file(filepath):
        with open(filepath, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()

    current_files = sorted([
        f for f in os.listdir(src_dir)
        if f.endswith((".md", ".txt", ".pdf", ".json"))
        and not f.startswith("_")
        and f != "corpus_manifest.md"
    ])

    current_state = {f: hash_file(os.path.join(src_dir, f)) for f in current_files}
    current_hash = hashlib.sha256(json.dumps(current_state, sort_keys=True).encode()).hexdigest()

    manifests = glob.glob(os.path.join(index_dir, "manifest_v*.json"))
    latest_v = 0
    latest_hash = ""
    for m in manifests:
        try:
            v = int(os.path.basename(m).split("_v")[1].split(".json")[0])
            if v > latest_v:
                latest_v = v
                with open(m, 'r') as mf:
                    latest_hash = json.load(mf).get("corpus_hash", "")
        except (IndexError, ValueError, json.JSONDecodeError):
            continue

    if current_hash != latest_hash:
        new_v = latest_v + 1
        manifest_data = {"version": new_v, "corpus_hash": current_hash,
                          "file_count": len(current_files), "files": current_state}
        with open(os.path.join(index_dir, f"manifest_v{new_v}.json"), "w") as f:
            json.dump(manifest_data, f, indent=2)
        return new_v, len(current_files), "UPDATED"
    else:
        return latest_v, len(current_files), "UNCHANGED"


if __name__ == "__main__":
    print("=" * 60)
    print("SMOKE TEST — through Stage 1, real agents, scoped corpus slice")
    print("=" * 60)

    print("\nRunning pre-flight corpus snapshot...")
    c_version, c_count, c_status = snapshot_corpus()
    print(f"Corpus Version: v{c_version} | File Count: {c_count} | Status: {c_status}")

    run_id = new_run_id()
    out_dir = run_output_dir(run_id)
    os.makedirs(out_dir, exist_ok=True)
    print(f"Run ID: {run_id}")

    manifest_path = os.path.join("corpus-index", f"manifest_v{c_version}.json")
    with open(manifest_path, "rb") as f:
        corpus_manifest_hash = f"sha256:{hashlib.sha256(f.read()).hexdigest()}"

    state = init_assessment_state(run_id, corpus_manifest_hash)
    save_assessment_state(state, run_id)
    print(f"Initial assessment_state.json written to {out_dir}/")

    print("\nReading assessment brief...")
    with open("collection/brief.md") as f:
        brief_text = f.read()

    scratch_path = "outputs/_stage0_scratch.md"
    if os.path.exists(scratch_path):
        os.remove(scratch_path)
    open(scratch_path, 'a').close()

    print("\nAssembling a SMALL corpus slice (smoke test — not the full corpus)...")
    src = "sources"
    files = sorted(
        f for f in os.listdir(src)
        if f.endswith((".md", ".txt"))
        and not f.startswith("_")
        and f != "corpus_manifest.md"
    )

    CHUNK = 60000
    chunks = []
    current = []
    current_len = 0
    for fn in files:
        content = f"\n===== {fn} =====\n" + open(os.path.join(src, fn)).read()
        if current_len + len(content) > CHUNK and current:
            chunks.append("".join(current))
            current, current_len = [], 0
        current.append(content)
        current_len += len(content)
    if current:
        chunks.append("".join(current))

    chunks = chunks[:MAX_CHUNKS]
    print(f"Using {len(chunks)} of the full chunk set (MAX_CHUNKS={MAX_CHUNKS}).")

    chunk_tasks = []
    for i, chunk in enumerate(chunks):
        chunk_tasks.append(Task(
            description=(
                f"You are processing corpus chunk index {i}.\n\n"
                f"=== CHUNK CONTENT ===\n{chunk}\n=====================\n\n"
                f"Extract EVERY: named system, AAMCAT or other subsystem, vendor product, "
                f"interface, protocol, version, exercise event, named person, and organization. "
                f"Call `extract_to_scratch` with the chunk index ({i}) on the first line and your findings below it."
            ),
            expected_output=f"Confirmation that chunk {i} findings were written to scratchpad.",
            agent=decomposer,
            tools=[extract_to_scratch],
        ))

    print(f"\nRunning smoke crew: t_research + {len(chunk_tasks)} chunk task(s) "
          f"+ t_synthesize_stage0 + t_stage1...")
    smoke_tasks = [t_research] + chunk_tasks + [t_synthesize_stage0, t_stage1]
    smoke_crew = Crew(
        agents=[researcher, decomposer],
        tasks=smoke_tasks,
        process=Process.sequential,
        verbose=True,
    )
    smoke_crew.kickoff(inputs={
        "sut_brief": brief_text,
        "file_count": c_count,
        "corpus_version": c_version,
    })

    print("\n" + "=" * 60)
    print("COMMITTING STAGE 0 AND STAGE 1 TO ASSESSMENT STATE")
    print("=" * 60)
    for stage_name, artifact_path in (
        ("stage0", "outputs/stage0_output.json"),
        ("stage1", "outputs/stage1_output.json"),
    ):
        if os.path.exists(artifact_path):
            commit_stage_output(state, stage_name, artifact_path, status=StageStatus.PENDING)
            print(f"Committed: {artifact_path}")
        else:
            print(f"WARNING: {artifact_path} not found — the decomposer agent did not call "
                  f"write_{stage_name}_output. Check the crew output above for why (did it "
                  f"call the tool at all? did the tool return REJECTED?).")
    state.current_stage = "stage1"
    save_assessment_state(state, run_id)

    print("\n" + "=" * 60)
    print(f"SMOKE TEST COMPLETE — inspect: {out_dir}/assessment_state.json")
    print("=" * 60)
    with open(os.path.join(out_dir, "assessment_state.json")) as f:
        print(f.read())

    # Extra sanity check specific to Stage 1: confirm the node inventory
    # is actually usable by Stage 2 later — i.e. it has real content, not
    # just an empty shell that happened to pass schema validation.
    stage1_path = "outputs/stage1_output.json"
    if os.path.exists(stage1_path):
        with open(stage1_path) as f:
            s1 = json.load(f)
        n_tech = len(s1.get("technical_nodes", []))
        n_proc = len(s1.get("procedural_nodes", []))
        n_cog = len(s1.get("cognitive_nodes", []))
        n_tb = len(s1.get("trust_boundaries", []))
        print(f"\nStage 1 content check: {n_tech} technical, {n_proc} procedural, "
              f"{n_cog} cognitive node(s), {n_tb} trust boundary(ies).")
        if n_tech == 0 and n_proc == 0 and n_cog == 0:
            print("WARNING: all three layers are empty — schema-valid but analytically useless. "
                  "Check whether the agent had enough scratchpad content to work from.")