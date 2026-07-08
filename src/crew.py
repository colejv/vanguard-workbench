from crewai import Crew, Process, Task
import sys, os
from src.agents import (researcher, decomposer, mapper,
                        modeler, red_team_lead, orchestrator)
from src.tasks import (t_research, t_synthesize_stage0, t_stage1,t_stage2, 
                       t_annexB, t_annexC, t_stage3, t_stage4)
from src.tools import (extract_to_scratch, verify_corpus_lock_gate,
                       discover_corpus_files, read_corpus_file,
                       check_attribution_boundary, check_phase0_safety_gate,
                       verify_stage2_vectors)
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

        # Get current files — via the shared discover_corpus_files, so this
        # hash scope is by construction the same set the chunk assembler
        # below reads for analysis. Do not re-inline this filter.
        current_files = discover_corpus_files(src_dir)
        
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

    # ---- GATE 1: CORPUS LOCK (deterministic — plain Python, not an agent
    # task) ----
    # Doctrinal Annex A Phase 1 requirement: the corpus must not have moved
    # since it was frozen (sources/corpus_manifest.md, written at the
    # collection/lock step) before Stage 0 may begin. t_research previously
    # only asserted a verbatim confirmation string and never actually
    # checked this — verify_corpus_lock_gate() re-hashes sources/ against
    # the frozen manifest and this call raises on any drift, so a moved,
    # added, or edited source file now genuinely blocks the run instead of
    # being silently accepted.
    lock = verify_corpus_lock_gate()
    print(f"Corpus lock: {lock['status']} — {lock['summary']}")
    if not lock["is_valid"]:
        raise RuntimeError(
            f"Corpus lock verification FAILED: {lock['summary']} "
            f"Stage 0 NOT started. Re-freeze the corpus or restore the "
            f"drifted file(s) before re-running. "
            f"Run audit trail: {run_output_dir(run_id)}/assessment_state.json"
        )
    # NOTE: this does not yet write the lock result into assessment_state.json
    # the way the Stage 2 gate does (commit_stage_output/set_stage_status) —
    # I haven't seen src/state.py or src/schemas.py in this session and don't
    # want to guess at stage-name validation. Share those two files and I'll
    # wire it in with the same two-step commit/promote pattern used below.

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

    # Read and assemble corpus chunks — discover_corpus_files is the exact
    # same file set snapshot_corpus() just hashed above, so every file in
    # the frozen manifest is guaranteed to enter analysis (previously .pdf/
    # .json were hashed here but silently never read).
    print("Assembling corpus from chunks...")
    src = "sources"
    files = discover_corpus_files(src)

    CHUNK = 60000
    chunks = []
    current = []
    current_len = 0
    for fn in files:
        content = f"\n===== {fn} =====\n" + read_corpus_file(os.path.join(src, fn))
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

    # ---- ATTRIBUTION-BOUNDARY CHECK (deterministic, warn-only) ----
    # Item 7: replaces trusting the "ATTRIBUTION DISCIPLINE" prompt text
    # alone. Checks every named person/unit/component mentioned in the
    # Stage 0 + Stage 1 prose against the scratchpad (the documented
    # boundary) and, as a fallback, the raw locked corpus. High-confidence
    # findings (rank+name, ordinal+unit) are the enforcement signal;
    # bare-phrase findings are reported but not counted against is_clean
    # (see the false-positive calibration note in tools.py). This is
    # warn-only, not a RuntimeError, because unlike the corpus-lock and
    # Stage 2 gates, regex-based entity extraction has a real residual
    # false-positive rate even after tiering — flip the `if not attr["...` block
    # below to `raise RuntimeError(...)` if you want it to hard-block instead.
    prose = ""
    for p in ("outputs/stage0.md", "outputs/stage1.md"):
        if os.path.exists(p):
            prose += open(p).read() + "\n"
    scratch_text = open(scratch_path).read() if os.path.exists(scratch_path) else ""
    corpus_text = ""
    if os.path.exists("corpus-index/corpus_chunks.json"):
        corpus_text = "\n".join(json.load(open("corpus-index/corpus_chunks.json"))["chunks"])

    attr = check_attribution_boundary(prose, scratch_text, corpus_text)
    with open("outputs/attribution_check.md", "w") as f:
        f.write("# Attribution Boundary Check (Stage 0 + Stage 1)\n\n")
        f.write(f"Entities checked: {attr['checked']}\n\n")
        f.write("## High-confidence (rank+name / ordinal+unit) — drives verdict\n")
        f.write(f"- Traceable: {attr['high_confidence']['traceable']}\n")
        f.write(f"- Extraction gap (in corpus, missed by scratchpad): "
                f"{attr['high_confidence']['extraction_gap']}\n")
        f.write(f"- **UNTRACEABLE (possible fabrication): "
                f"{attr['high_confidence']['untraceable']}**\n\n")
        f.write("## Advisory (bare capitalized phrase) — review only, not enforced\n")
        f.write(f"- Traceable: {attr['advisory']['traceable']}\n")
        f.write(f"- Extraction gap: {attr['advisory']['extraction_gap']}\n")
        f.write(f"- Untraceable: {attr['advisory']['untraceable']}\n")

    if attr["is_clean"]:
        print(f"Attribution check: CLEAN — {attr['checked']} entities checked, "
              f"none untraceable at high confidence.")
    else:
        print(f"Attribution check: FLAGGED — possible fabrication, human review "
              f"required: {attr['high_confidence']['untraceable']}. "
              f"See outputs/attribution_check.md. (Not blocking this run — see "
              f"comment above this block to make it a hard gate.)")

    # ---- COMMIT PRE-CREW STAGE OUTPUTS TO ASSESSMENT STATE ----
    # pre_crew runs Stage 0, Stage 1, and Stage 2 sequentially inside one
    # kickoff() with no per-task hook exposed, so all three are committed
    # here, after the crew finishes, from whatever artifacts exist on disk.
    # Stage 0/1 land as PENDING — the attribution-boundary check above is
    # deterministic but warn-only (not a PASS/FAIL gate the way Stage 2's
    # verify_stage2_vectors is), so it doesn't change commit status here;
    # its verdict lives in outputs/attribution_check.md instead. Stage 2 is
    # committed PENDING here and promoted to PASS/FAIL immediately below,
    # once verify_stage2_vectors actually runs.
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

    # ---- ITEM 8: PHASE 0 SAFETY GATE COMPLIANCE CHECK (deterministic, HARD
    # BLOCK) ----
    # Unlike the attribution check (warn-only, item 7), this is a hard gate:
    # a missing safety-review section on a payload with a real physical/
    # destructive effect is a compliance failure, not an analytical nicety.
    # IMPORTANT CAVEAT: t_stage3 and t_stage4 both already ran their
    # human_input=True approval INSIDE post_crew.kickoff() above, so this
    # check fires AFTER a human has already approved the mission plan
    # content — it cannot intercept that approval. What it CAN do is refuse
    # to let the run complete/stamp the plan as final if the safety gate is
    # missing, which still surfaces the compliance gap immediately rather
    # than silently shipping a Category 2/3 mission plan with no safety
    # section. If you want this enforced *before* the human sees Stage 4 at
    # all, that requires splitting post_crew at the Stage 3/Stage 4 boundary
    # the same way pre_crew/post_crew are already split around the Stage 2
    # gate — a bigger structural change I didn't make unprompted; say the
    # word and I will.
    stage3_text = open("outputs/stage3.md").read() if os.path.exists("outputs/stage3.md") else ""
    stage4_text = (open("outputs/stage4_mission_plan.md").read()
                   if os.path.exists("outputs/stage4_mission_plan.md") else "")
    safety = check_phase0_safety_gate(stage3_text, stage4_text)
    with open("outputs/phase0_safety_check.md", "w") as f:
        f.write("# Phase 0 Safety Gate Compliance Check\n\n")
        f.write(f"Category 2/3 payload detected: {safety['category_2_3_detected']}\n")
        f.write(f"Matched terms: {safety['matched_terms']}\n")
        f.write(f"Phase 0 Safety Gate section present: {safety['phase0_gate_present']}\n\n")
        f.write(f"STATUS: {'COMPLIANT' if safety['is_compliant'] else 'NON-COMPLIANT'}\n")
        f.write(safety["summary"] + "\n")
    print(f"Phase 0 Safety Gate check: "
          f"{'COMPLIANT' if safety['is_compliant'] else 'NON-COMPLIANT'} — {safety['summary']}")
    if not safety["is_compliant"]:
        raise RuntimeError(
            f"Phase 0 Safety Gate compliance FAILED: {safety['summary']} "
            f"See outputs/phase0_safety_check.md. Mission plan NOT finalized — "
            f"revise Stage 4 to add the required safety section (or an explicit "
            f"'NO CATEGORY 2/3 PAYLOADS' statement if this is a false positive) "
            f"and re-run. Run audit trail: {run_output_dir(run_id)}/assessment_state.json"
        )

    # ---- COMMIT POST-CREW STAGE OUTPUT TO ASSESSMENT STATE ----
    # Stage 3 (t_stage3) is the payload-design gate; no structured schema
    # exists for it yet, so it lands as PENDING against its prose artifact,
    # same as Stage 0/1. (The Phase 0 safety check above does deterministically
    # verify one specific cross-cutting property of Stage 3+4 together —
    # category/safety-gate correlation — but that's not the same as a full
    # structural verifier the way Stage 2 has one.)
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