from crewai import Crew, Process, Task
import sys, os
from src.agents import (researcher, decomposer, mapper,
                        modeler, red_team_lead, orchestrator)
from src.tasks import (t_research, t_synthesize_stage0, t_stage1,t_stage2, 
                       t_annexB, t_annexC, t_stage3, t_stage4)
from src.tools import extract_to_scratch, verify_corpus_lock, verify_stage2_vectors
from src.schemas import StageStatus
from src.state import (new_run_id, run_output_dir, init_assessment_state,
                        save_assessment_state, commit_stage_output, set_stage_status)


if __name__ == "__main__":
    import sys, os, glob, json, hashlib

    def snapshot_corpus(src_dir="sources", index_dir="corpus-index"):
        """Hashes the corpus, compares to the latest manifest, and versions it if changed."""
        os.makedirs(index_dir, exist_ok=True)
        
        def hash_file(filepath):
            with open(filepath, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()

        # Get current files
        current_files = sorted([
            f for f in os.listdir(src_dir) 
            if f.endswith((".md", ".txt", ".pdf", ".json")) 
            and not f.startswith("_") 
            and f != "corpus_manifest.md"
        ])
        
        # Hash state
        current_state = {f: hash_file(os.path.join(src_dir, f)) for f in current_files}
        current_hash = hashlib.sha256(json.dumps(current_state, sort_keys=True).encode()).hexdigest()

        # Find latest version
        manifests = glob.glob(os.path.join(index_dir, "manifest_v*.json"))
        latest_v = 0
        latest_hash = ""
        for m in manifests:
            try:
                # Extract version integer from filename (e.g., manifest_v2.json -> 2)
                v = int(os.path.basename(m).split("_v")[1].split(".json")[0])
                if v > latest_v:
                    latest_v = v
                    with open(m, 'r') as mf:
                        latest_hash = json.load(mf).get("corpus_hash", "")
            except (IndexError, ValueError, json.JSONDecodeError):
                continue

        # Compare and version
        if current_hash != latest_hash:
            new_v = latest_v + 1
            manifest_data = {
                "version": new_v,
                "corpus_hash": current_hash,
                "file_count": len(current_files),
                "files": current_state
            }
            with open(os.path.join(index_dir, f"manifest_v{new_v}.json"), "w") as f:
                json.dump(manifest_data, f, indent=2)
            return new_v, len(current_files), "UPDATED"
        else:
            return latest_v, len(current_files), "UNCHANGED"

    # ==========================================
    # PRE-FLIGHT & SNAPSHOT
    # ==========================================
    print("Running pre-flight corpus snapshot...")
    c_version, c_count, c_status = snapshot_corpus()
    print(f"Corpus Version: v{c_version} | File Count: {c_count} | Status: {c_status}")

    # ---- RUN IDENTITY & ASSESSMENT STATE (audit trail) ----
    # One run_id per pipeline execution; every new audit artifact this run
    # produces is scoped under outputs/<run_id>/. Existing task output_file
    # paths (outputs/stage0.md, etc.) are intentionally left flat for now —
    # scoping those is a separate, larger change to tasks.py, not part of
    # this increment.
    run_id = new_run_id()
    out_dir = run_output_dir(run_id)
    os.makedirs(out_dir, exist_ok=True)
    print(f"Run ID: {run_id}")

    # Pin this run to the corpus manifest that snapshot_corpus() just wrote
    # or confirmed unchanged, so assessment_state.json records exactly which
    # corpus snapshot backs this run's findings.
    manifest_path = os.path.join("corpus-index", f"manifest_v{c_version}.json")
    with open(manifest_path, "rb") as f:
        corpus_manifest_hash = f"sha256:{hashlib.sha256(f.read()).hexdigest()}"

    state = init_assessment_state(run_id, corpus_manifest_hash)
    save_assessment_state(state, run_id)

    print("Reading assessment brief...")
    with open("collection/brief.md") as f:
        brief_text = f.read()

    # Robust Dedup: Ensure scratchpad is zeroed out to prevent duplicate 
    # entries if a previous run crashed mid-extraction.
    scratch_path = "outputs/_stage0_scratch.md"
    if os.path.exists(scratch_path):
        os.remove(scratch_path)
        # Touch the file so the tool doesn't throw a FileNotFoundError if read early
        open(scratch_path, 'a').close() 

    # Read and assemble corpus chunks
    print("Assembling corpus from chunks...")
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

    total_chars = sum(len(c) for c in chunks)
    print(f"Corpus: {len(files)} files, {total_chars:,} chars, {len(chunks)} chunks")

    with open("corpus-index/corpus_chunks.json", "w") as f:
        json.dump({"chunks": chunks, "total": len(chunks), "files": len(files)}, f)
    
    # ==========================================
    # DYNAMIC TASK ASSEMBLY
    # ==========================================
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

    # ---- CREW 1: through Stage 2 (produces stage2_vectors.json) ----
    pre_tasks = [t_research] + chunk_tasks + [t_synthesize_stage0, t_stage1, t_stage2]

    pre_crew = Crew(
        agents=[researcher, decomposer, mapper],
        tasks=pre_tasks,
        process=Process.sequential,
        verbose=True,
    )
    pre_crew.kickoff(inputs={
        "sut_brief": brief_text,
        "file_count": c_count,
        "corpus_version": c_version,
    })

    # ---- COMMIT PRE-CREW STAGE OUTPUTS TO ASSESSMENT STATE ----
    # pre_crew runs Stage 0, Stage 1, and Stage 2 sequentially inside one
    # kickoff() with no per-task hook exposed, so all three are committed
    # here, after the crew finishes, from whatever artifacts exist on disk.
    # Stage 0/1 land as PENDING (no deterministic gate for them yet — that's
    # item 4); Stage 2 is committed PENDING here and promoted to PASS/FAIL
    # immediately below, once verify_stage2_vectors actually runs.
    for stage_name, artifact_path in (
        ("stage0", "outputs/stage0_output.json"),
        ("stage1", "outputs/stage1_output.json"),
    ):
        if os.path.exists(artifact_path):
            commit_stage_output(state, stage_name, artifact_path, status=StageStatus.PENDING)
        else:
            print(f"WARNING: {artifact_path} not found — {stage_name} agent may not have "
                  f"called its write tool. assessment_state.json will show {stage_name} "
                  f"as NOT_STARTED.")
    state.current_stage = "stage2"
    save_assessment_state(state, run_id)

    # ---- DETERMINISTIC GATE (plain Python — the actual enforcement point) ----
    verification = verify_stage2_vectors(
        vectors_path="outputs/stage2_vectors.json",
        index_path="corpus-index/technique_index.json",
    )
    with open("outputs/stage2_verification.md", "w") as f:
        f.write(f"# Stage 2 Verification\n\nSTATUS: {verification['status']}\n\n")
        f.write(verification["summary"] + "\n\n")
        for ie in verification["invalid_edges"]:
            sug = ie["suggestion"][0]["id"] if ie["suggestion"] else "none"
            f.write(f"- INVALID edge[{ie['edge_index']}] `{ie['technique']}` "
                    f"({ie['reason']}) — suggest `{sug}`\n")
        for ge in verification["gap_edges"]:
            f.write(f"- GAP edge[{ge['edge_index']}] `{ge['technique']}`\n")

    # Register stage2_vectors.json in the audit trail regardless of outcome,
    # then promote/demote its status from the gate's actual verdict — same
    # two-step pattern (commit PENDING, then set_stage_status) used above.
    if os.path.exists("outputs/stage2_vectors.json"):
        commit_stage_output(state, "stage2", "outputs/stage2_vectors.json", status=StageStatus.PENDING)
    set_stage_status(state, "stage2", StageStatus.PASS if verification["is_valid"] else StageStatus.FAIL)
    save_assessment_state(state, run_id)

    if not verification["is_valid"]:
        raise RuntimeError(
            f"Stage 2 verification FAILED: {verification['summary']} "
            f"See outputs/stage2_verification.md. Annex B and downstream NOT executed. "
            f"Run audit trail: {run_output_dir(run_id)}/assessment_state.json"
        )

    # ---- CREW 2: Annex B onward (only reached if gate passed) ----
    post_crew = Crew(
        agents=[modeler, red_team_lead, orchestrator],
        tasks=[t_annexB, t_annexC, t_stage3, t_stage4],
        process=Process.sequential,
        verbose=True,
    )
    result = post_crew.kickoff(inputs={
        "sut_brief": brief_text,
        "file_count": c_count,
        "corpus_version": c_version,
    })

    # ---- COMMIT POST-CREW STAGE OUTPUT TO ASSESSMENT STATE ----
    # Stage 3 (t_stage3) is the payload-design gate; no structured schema or
    # deterministic verifier exists for it yet (that's item 4's scope), so
    # it lands as PENDING against its prose artifact, same as Stage 0/1.
    if os.path.exists("outputs/stage3.md"):
        commit_stage_output(state, "stage3", "outputs/stage3.md", status=StageStatus.PENDING)
    state.current_stage = "complete"
    save_assessment_state(state, run_id)

    # Stamp the final mission plan with the corpus version
    try:
        with open("outputs/stage4_mission_plan.md", "a") as f:
            f.write(f"\n\n---\n*Analysis grounded in Corpus Version v{c_version} ({c_count} files)*")
    except Exception:
        pass

    print("\n\n=== PIPELINE FINISHED ===")
    print(f"Run audit trail: {run_output_dir(run_id)}/assessment_state.json")
    print(result)