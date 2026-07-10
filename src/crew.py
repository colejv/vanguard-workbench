from crewai import Crew, Process, Task
import sys, os, json
from src.agents import (researcher, decomposer, mapper,
                        modeler, red_team_lead, orchestrator)
from src.tasks import (build_tasks, build_stage4_task, build_kcag_review_task,
                       build_analysis_tasks, finalize_kcag_review_artifact)
from src.tools import (extract_to_scratch, verify_corpus_lock_gate,
                       discover_corpus_files, read_corpus_file,
                       check_attribution_boundary, check_phase0_safety_gate,
                       check_stage3_safety_gate, verify_stage2_vectors,
                       validate_kcag)
from src.stage3_validation import validate_stage3_test_plan, check_stage3_artifact_consistency
from src.stage4_validation import validate_stage4_execution_plan, check_stage4_artifact_consistency
from src.schemas import StageStatus
from src.state import (new_run_id, run_output_dir, init_assessment_state,
                        save_assessment_state, commit_stage_output, set_stage_status,
                        finalize_stage4_state, enforce_stage3_safety_gate,
                        enforce_stage3_test_plan_validation, enforce_stage4_execution_plan_validation,
                        canonical_json_sha256)
from src import run_context
from src.heartbeat import heartbeat


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

        # Compare and version. NOTE: manifest_v{N}.json under corpus-index/
        # is deliberately NOT run-scoped -- it tracks corpus drift over time
        # across many runs, not one assessment's artifacts, so it stays
        # shared by design (unlike everything under outputs/<run_id>/).
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

    def detect_resume_progress(out_dir):
        """Check which expensive pre_crew/post_crew steps already completed in a
        previous, interrupted attempt at this exact run_id. Only trusts an
        artifact as 'done' if its defining file(s) exist — presence, not a
        state-file flag, since assessment_state.json's commit code runs
        AFTER kickoff() returns, which never happens on a crash mid-crew.
        Returns (chunking_done, stage0_done, stage1_done, stage2_done,
        annexB_done, annexC_done). Stage 3/4 are NEVER auto-skipped — both
        are human_input=True gates the analyst always re-approves fresh,
        and stage3 in particular is often exactly the stage being resumed
        TO (e.g. after fixing its prompt), never the stage being resumed
        PAST."""
        scratch_path = os.path.join(out_dir, "_stage0_scratch.md")
        chunking_done = os.path.exists(scratch_path) and os.path.getsize(scratch_path) > 0

        stage0_done = (os.path.exists(os.path.join(out_dir, "stage0_output.json"))
                       and os.path.exists(os.path.join(out_dir, "stage0.md")))
        stage1_done = (os.path.exists(os.path.join(out_dir, "stage1_output.json"))
                       and os.path.exists(os.path.join(out_dir, "stage1.md")))
        stage2_done = (os.path.exists(os.path.join(out_dir, "stage2_vectors.json"))
                       and os.path.exists(os.path.join(out_dir, "stage2.md")))
        annexB_done = os.path.exists(os.path.join(out_dir, "kcag_report.json"))
        annexC_done = os.path.exists(os.path.join(out_dir, "bbn_report.json"))
        return chunking_done, stage0_done, stage1_done, stage2_done, annexB_done, annexC_done

    # ---- CLI: --resume <run_id> -------------------------------------------
    resume_run_id = None
    if "--resume" in sys.argv:
        idx = sys.argv.index("--resume")
        if idx + 1 >= len(sys.argv):
            raise SystemExit("--resume requires a run_id argument, e.g. "
                             "--resume vaf_20260709_143022")
        resume_run_id = sys.argv[idx + 1]

    # ==========================================
    # PRE-FLIGHT & SNAPSHOT
    # ==========================================
    print("Running pre-flight corpus snapshot...")
    c_version, c_count, c_status = snapshot_corpus()
    print(f"Corpus Version: v{c_version} | File Count: {c_count} | Status: {c_status}")

    # ---- RUN IDENTITY: fresh run, or resume an interrupted one ----
    manifest_path = os.path.join("corpus-index", f"manifest_v{c_version}.json")
    with open(manifest_path, "rb") as f:
        corpus_manifest_hash = f"sha256:{hashlib.sha256(f.read()).hexdigest()}"

    if resume_run_id:
        run_id = resume_run_id
        out_dir = run_output_dir(run_id)
        if not os.path.isdir(out_dir):
            raise SystemExit(f"--resume {run_id}: {out_dir} does not exist. "
                             f"Nothing to resume.")
        print(f"Resuming run: {run_id}")

        from src.state import load_assessment_state
        state = load_assessment_state(run_id)

        # FAIL CLOSED: refuse to resume against a corpus that has moved
        # since the original attempt. Resuming here would silently mix
        # artifacts from two different corpus snapshots into one run — the
        # exact failure mode run-isolation exists to prevent, just
        # approached from a different angle (time, not concurrency).
        if state.corpus_manifest_hash != corpus_manifest_hash:
            raise RuntimeError(
                f"Cannot resume {run_id}: corpus has changed since this run "
                f"started (was {state.corpus_manifest_hash}, now "
                f"{corpus_manifest_hash}). Start a fresh run instead — "
                f"resuming against a different corpus snapshot would mix "
                f"artifacts from two different assessments."
            )
    else:
        run_id = new_run_id()
        out_dir = run_output_dir(run_id)
        print(f"Run ID: {run_id}")
        state = init_assessment_state(run_id, corpus_manifest_hash)
        save_assessment_state(state, run_id)

    # ---- RUN ISOLATION: set the active run BEFORE any task or tool runs ----
    # Every tool that reads/writes a per-run artifact resolves its path via
    # run_context.artifact_path() from this point on -- there is no shared
    # "outputs/<filename>" path left anywhere in tools.py. Two runs, whether
    # sequential or concurrent, cannot collide: each gets its own directory,
    # and every JSON/prose artifact is stamped with this run's id + corpus
    # hash, so even a code bug that points at the wrong path is caught by
    # read_stamped_json/read_stamped_prose rather than silently succeeding.
    run_context.set_active_run(run_id, corpus_manifest_hash, out_dir)

    # ---- GATE 1: CORPUS LOCK (deterministic — plain Python, not an agent
    # task) ----
    # Doctrinal Annex A Phase 1 requirement: the corpus must not have moved
    # since it was frozen (sources/corpus_manifest.md, written at the
    # collection/lock step) before Stage 0 may begin. verify_corpus_lock_gate()
    # re-hashes sources/ against the frozen manifest and this call raises on
    # any drift.
    lock = verify_corpus_lock_gate()
    print(f"Corpus lock: {lock['status']} — {lock['summary']}")

    # NOT committed into assessment_state.json: STAGE_NAMES in schemas.py is
    # ('stage0','stage1','stage2','stage3') and both commit_stage_output and
    # set_stage_status raise ValueError on any other stage name, so
    # 'corpus_lock' has no slot to commit into. The Gate 1 doctrinal check
    # still fully enforces below (RuntimeError halts the run on any drift).
    if not lock["is_valid"]:
        raise RuntimeError(
            f"Corpus lock verification FAILED: {lock['summary']} "
            f"Stage 0 NOT started. Re-freeze the corpus or restore the "
            f"drifted file(s) before re-running. "
            f"Run audit trail: {out_dir}/assessment_state.json"
        )

    print("Reading assessment brief...")
    with open("collection/brief.md") as f:
        brief_text = f.read()

    # ---- RESUME-PROGRESS DETECTION ----
    chunking_done = stage0_done = stage1_done = stage2_done = annexB_done = annexC_done = False
    if resume_run_id:
        (chunking_done, stage0_done, stage1_done,
         stage2_done, annexB_done, annexC_done) = detect_resume_progress(out_dir)
        print(f"Resume progress: chunking_done={chunking_done}, stage0_done={stage0_done}, "
              f"stage1_done={stage1_done}, stage2_done={stage2_done}, "
              f"annexB_done={annexB_done}, annexC_done={annexC_done}")

    scratch_path = run_context.artifact_path("_stage0_scratch.md")
    chunks_path = run_context.artifact_path("corpus_chunks.json")
    if chunking_done:
        print(f"Skipping corpus chunking — {scratch_path} already populated "
              f"from the interrupted run.")
        chunks = []  # chunk_tasks below is only built from this; empty means none built
    else:
        # Scratchpad lives under the run directory now, so there is nothing to
        # dedup against a previous run's leftovers -- a fresh run_id always
        # means a fresh, empty scratch file. Still touch it so read_scratch
        # doesn't hit FileNotFoundError if called before the first extraction.
        open(scratch_path, "a").close()

        # Read and assemble corpus chunks — discover_corpus_files is the exact
        # same file set snapshot_corpus() just hashed above, so every file in
        # the frozen manifest is guaranteed to enter analysis.
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

        # Run-scoped and stamped -- moved off corpus-index/ (shared, and the
        # original location of the collision risk between concurrent runs).
        run_context.write_stamped_json(
            chunks_path, {"chunks": chunks, "total": len(chunks), "files": len(files)}
        )

    # ---- RESUME CONTEXT: retroactively stamp + read already-completed
    # prose so it can be injected into whichever task resumes first ----
    # (CrewAI writes output_file content directly from the agent's answer
    # as each task completes, not deferred to kickoff() returning — so
    # stage0.md/stage1.md already exist even though the run crashed before
    # crew.py's own post-kickoff stamping code ever ran on them.)
    resume_context = {}
    if annexB_done:
        # Annex C not done (or also skipped separately below) -- if Annex C
        # itself still needs to run, it needs Annex B injected (context=
        # [t_annexB] would otherwise reference a task not in this crew).
        annexB_prose_path = run_context.artifact_path("annexB_kcag.md")
        run_context.stamp_prose_file(annexB_prose_path)
        annexB_content = run_context.read_stamped_prose(annexB_prose_path)
        if not annexC_done:
            resume_context["t_annexC"] = annexB_content
            print("Injecting completed Annex B output into Annex C (skipping Annex B task execution).")
    elif stage2_done:
        stage2_prose_path = run_context.artifact_path("stage2.md")
        run_context.stamp_prose_file(stage2_prose_path)
        resume_context["t_annexB"] = run_context.read_stamped_prose(stage2_prose_path)
        print("Injecting completed Stage 2 output into Annex B (skipping Stage 2 task execution).")
    elif stage1_done:
        # Failure was actually at/after Stage 2 — Stage 0 AND Stage 1 both
        # already complete. Inject Stage 1 into Stage 2, skip both upstream tasks.
        stage1_prose_path = run_context.artifact_path("stage1.md")
        run_context.stamp_prose_file(stage1_prose_path)
        resume_context["t_stage2"] = run_context.read_stamped_prose(stage1_prose_path)
        print(f"Injecting completed Stage 1 output into Stage 2 (skipping "
              f"Stage 0 and Stage 1 task execution).")
    elif stage0_done:
        stage0_prose_path = run_context.artifact_path("stage0.md")
        run_context.stamp_prose_file(stage0_prose_path)
        resume_context["t_stage1"] = run_context.read_stamped_prose(stage0_prose_path)
        print(f"Injecting completed Stage 0 output into Stage 1 (skipping "
              f"Stage 0 task execution).")

    # ---- t_stage3's TWO upstream dependencies (t_stage2, t_annexB) are
    # each independently skippable, unlike every task above (which each
    # have exactly one). Handle separately from the elif chain: whichever
    # of stage2_done/annexB_done is true gets its content injected here,
    # regardless of which branch above fired (that chain only determines
    # the FIRST resume point for the single-dependency tasks upstream).
    if stage2_done:
        stage2_prose_path = run_context.artifact_path("stage2.md")
        run_context.stamp_prose_file(stage2_prose_path)
        resume_context["t_stage3_stage2"] = run_context.read_stamped_prose(stage2_prose_path)
    if annexB_done:
        annexB_prose_path = run_context.artifact_path("annexB_kcag.md")
        run_context.stamp_prose_file(annexB_prose_path)
        resume_context["t_stage3_annexb"] = run_context.read_stamped_prose(annexB_prose_path)
    if stage2_done or annexB_done:
        parts = []
        if stage2_done: parts.append("Stage 2")
        if annexB_done: parts.append("Annex B")
        print(f"Stage 3 will receive injected context for: {' and '.join(parts)} "
              f"(skipped task execution for whichever is listed).")

    # ==========================================
    # TASK ASSEMBLY (run-scoped output_file paths, built fresh each run)
    # ==========================================
    tasks = build_tasks(out_dir, resume_context=resume_context)
    t_research = tasks["t_research"]
    t_synthesize_stage0 = tasks["t_synthesize_stage0"]
    t_stage1 = tasks["t_stage1"]
    t_stage2 = tasks["t_stage2"]
    t_annexB = tasks["t_annexB"]
    t_annexC = tasks["t_annexC"]
    t_stage3 = tasks["t_stage3"]

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
    # Resume-aware: only include tasks for stages that haven't already
    # completed against THIS run_id. chunk_tasks is already [] when
    # chunking_done (chunks was set to [] above in that branch), so the
    # list-comprehension there is naturally a no-op.
    pre_tasks = []
    if not chunking_done:
        pre_tasks += [t_research] + chunk_tasks
    if not stage0_done:
        pre_tasks += [t_synthesize_stage0]
    if not stage1_done:
        pre_tasks += [t_stage1]
    if not stage2_done:
        pre_tasks += [t_stage2]

    if not pre_tasks:
        print("pre_crew: nothing to run — chunking through Stage 2 all already "
              "complete for this run. Skipping pre_crew.kickoff() entirely.")
    else:
        print(f"pre_crew will run {len(pre_tasks)} task(s): "
              f"{[t.output_file.split('/')[-1] if t.output_file else t.agent.role for t in pre_tasks][:6]}"
              f"{' ...' if len(pre_tasks) > 6 else ''}")

        pre_crew = Crew(
            agents=[researcher, decomposer, mapper],
            tasks=pre_tasks,
            process=Process.sequential,
            verbose=True,
        )
        pre_heartbeat_log = run_context.artifact_path("heartbeat.log")
        print(f"Heartbeat log: {pre_heartbeat_log} (tail -f it in a second terminal)")
        with heartbeat("pre_crew", log_path=pre_heartbeat_log):
            pre_crew.kickoff(inputs={
                "sut_brief": brief_text,
                "file_count": c_count,
                "corpus_version": c_version,
            })

    # ---- STAMP PRE-CREW PROSE ARTIFACTS ----
    # CrewAI writes output_file content directly from each agent's final
    # answer -- there's no Python write call to route through
    # write_stamped_json for these, so stamp them here as a deterministic
    # post-processing step instead of asking the model to do it.
    stage0_prose_path = run_context.artifact_path("stage0.md")
    stage1_prose_path = run_context.artifact_path("stage1.md")
    stage2_prose_path = run_context.artifact_path("stage2.md")
    for p in (stage0_prose_path, stage1_prose_path, stage2_prose_path):
        run_context.stamp_prose_file(p)

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
    for p in (stage0_prose_path, stage1_prose_path):
        if os.path.exists(p):
            prose += run_context.read_stamped_prose(p) + "\n"
    scratch_text = open(scratch_path).read() if os.path.exists(scratch_path) else ""
    corpus_text = ""
    if os.path.exists(chunks_path):
        corpus_text = "\n".join(run_context.read_stamped_json(chunks_path)["chunks"])

    attr = check_attribution_boundary(prose, scratch_text, corpus_text)
    attr_check_path = run_context.artifact_path("attribution_check.md")
    with open(attr_check_path, "w") as f:
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
    run_context.stamp_prose_file(attr_check_path)

    if attr["is_clean"]:
        print(f"Attribution check: CLEAN — {attr['checked']} entities checked, "
              f"none untraceable at high confidence.")
    else:
        print(f"Attribution check: FLAGGED — possible fabrication, human review "
              f"required: {attr['high_confidence']['untraceable']}. "
              f"See {attr_check_path}. (Not blocking this run — see "
              f"comment above this block to make it a hard gate.)")

    # ---- COMMIT PRE-CREW STAGE OUTPUTS TO ASSESSMENT STATE ----
    # pre_crew runs Stage 0, Stage 1, and Stage 2 sequentially inside one
    # kickoff() with no per-task hook exposed, so all three are committed
    # here, after the crew finishes, from whatever artifacts exist on disk.
    # Stage 0/1 land as PENDING — the attribution-boundary check above is
    # deterministic but warn-only, so it doesn't change commit status here;
    # its verdict lives in attribution_check.md instead. Stage 2 is
    # committed PENDING here and promoted to PASS/FAIL immediately below,
    # once verify_stage2_vectors actually runs.
    stage0_json_path = run_context.artifact_path("stage0_output.json")
    stage1_json_path = run_context.artifact_path("stage1_output.json")
    for stage_name, artifact_path in (
        ("stage0", stage0_json_path),
        ("stage1", stage1_json_path),
    ):
        if os.path.exists(artifact_path):
            commit_stage_output(state, stage_name, artifact_path, status=StageStatus.PENDING)
        else:
            print(f"WARNING: {artifact_path} not found — {stage_name} agent may not have "
                  f"called its write tool. assessment_state.json will show {stage_name} "
                  f"as NOT_STARTED.")
    state.current_stage = "stage2"
    save_assessment_state(state, run_id)

    # ---- GATE 1 OF 2: FRAMEWORK-ID VERIFICATION (plain Python) ----
    # No vectors_path passed -- verify_stage2_vectors resolves it via
    # run_context automatically now, same as every other tool.
    verification = verify_stage2_vectors(index_path="corpus-index/technique_index.json")
    stage2_verification_path = run_context.artifact_path("stage2_verification.md")
    with open(stage2_verification_path, "w") as f:
        f.write(f"# Stage 2 Verification\n\nSTATUS: {verification['status']}\n\n")
        f.write(verification["summary"] + "\n\n")
        for ie in verification["invalid_edges"]:
            sug = ie["suggestion"][0]["id"] if ie["suggestion"] else "none"
            f.write(f"- INVALID edge[{ie['edge_index']}] `{ie['technique']}` "
                    f"({ie['reason']}) — suggest `{sug}`\n")
        for ge in verification["gap_edges"]:
            f.write(f"- GAP edge[{ge['edge_index']}] `{ge['technique']}`\n")
    run_context.stamp_prose_file(stage2_verification_path)

    # Register stage2_vectors.json in the audit trail regardless of outcome.
    # Stage 2 is deliberately NOT promoted to PASS here anymore -- only
    # FAIL on this gate's own failure. PASS now requires BOTH this ID gate
    # AND the structural gate below to succeed; promoting early here (the
    # previous behavior) meant "Stage 2: PASS" only ever reflected
    # framework-ID correctness, never graph structure.
    stage2_vectors_path = run_context.artifact_path("stage2_vectors.json")
    if os.path.exists(stage2_vectors_path):
        commit_stage_output(state, "stage2", stage2_vectors_path, status=StageStatus.PENDING)
    if not verification["is_valid"]:
        set_stage_status(state, "stage2", StageStatus.FAIL)
        save_assessment_state(state, run_id)
        raise RuntimeError(
            f"Stage 2 verification FAILED: {verification['summary']} "
            f"See {stage2_verification_path}. Annex B and downstream NOT executed. "
            f"Run audit trail: {out_dir}/assessment_state.json"
        )
    save_assessment_state(state, run_id)

    # ---- GATE 2 OF 2: KCAG STRUCTURAL VALIDATION (plain Python) ----
    # A separate, non-overlapping check from the ID gate above: this one
    # verifies graph structure and internal consistency (ADV_START is the
    # sole root, every goal is reachable, no duplicate directed edges,
    # etc.) and does NOT verify framework technique IDs at all -- that
    # stays exclusively the ID gate's job. Neither gate mutates
    # stage2_vectors.json; Annex B always reads the same original stamped
    # artifact regardless of which gates ran.
    kcag_validation = validate_kcag()
    kcag_validation_path = run_context.artifact_path("kcag_validation.json")
    run_context.write_stamped_json(kcag_validation_path, kcag_validation)
    print(f"KCAG structural validation: {kcag_validation['status']} — {kcag_validation['summary']}")

    if not kcag_validation["is_valid"]:
        set_stage_status(state, "stage2", StageStatus.FAIL)
        save_assessment_state(state, run_id)
        raise RuntimeError(
            f"KCAG structural validation FAILED: {kcag_validation['summary']} "
            f"See {kcag_validation_path}. Annex B and downstream NOT executed. "
            f"Run audit trail: {out_dir}/assessment_state.json"
        )

    # Both gates passed.
    set_stage_status(state, "stage2", StageStatus.PASS)
    save_assessment_state(state, run_id)

    # ---- ANALYSIS CREW: KCAG review, Annex B, Annex C, Stage 3 (Stage 4
    # is now a separate crew — see below) ----
    # Stage 3 is never skipped on resume (see detect_resume_progress) --
    # it's a human_input=True gate the analyst re-approves fresh every
    # time, and is very often exactly the stage BEING resumed to (e.g.
    # after correcting its prompt), never one to skip past.
    #
    # The KCAG review is tied to Annex B's own resume rule: it only runs
    # when Annex B is about to run this invocation. Re-reading through
    # read_stamped_json() here (not reusing the in-memory kcag_validation
    # dict from the gate above) matches this codebase's established
    # verify-by-reading-back convention rather than trusting an in-memory
    # value, even though both would agree in this same process.
    t_kcag_review = None
    if not annexB_done:
        stage2_graph = run_context.read_stamped_json(stage2_vectors_path)
        validation_report = run_context.read_stamped_json(kcag_validation_path)
        t_kcag_review = build_kcag_review_task(
            out_dir, stage2_graph=stage2_graph, validation_report=validation_report
        )

    analysis_tasks = build_analysis_tasks(
        t_kcag_review=t_kcag_review,
        t_annexB=t_annexB,
        t_annexC=t_annexC,
        t_stage3=t_stage3,
        annexB_done=annexB_done,
        annexC_done=annexC_done,
    )

    print(f"analysis_crew will run {len(analysis_tasks)} task(s): "
          f"{[t.output_file.split('/')[-1] if t.output_file else t.agent.role for t in analysis_tasks]}")

    analysis_crew = Crew(
        agents=[modeler, red_team_lead],
        tasks=analysis_tasks,
        process=Process.sequential,
        verbose=True,
    )
    analysis_heartbeat_log = run_context.artifact_path("heartbeat.log")
    with heartbeat("analysis_crew", log_path=analysis_heartbeat_log):
        analysis_crew.kickoff(inputs={
            "sut_brief": brief_text,
            "file_count": c_count,
            "corpus_version": c_version,
        })

    # ---- FINALIZE KCAG REVIEW ARTIFACT (advisory; existence enforced,
    # content is not) ----
    # See finalize_kcag_review_artifact()'s docstring in tasks.py for why
    # this is a shared helper rather than inline logic, and for what
    # exactly is/isn't enforced.
    finalize_kcag_review_artifact(review_was_required=t_kcag_review is not None)

    # ---- VERIFY STAGE 3 BEFORE STAGE 4 CAN EVEN BE CONSTRUCTED ----
    # This is the actual trust boundary the crew split exists to create.
    # Stage 4 is not merely sequenced after Stage 3 now — there is no code
    # path from here to a Stage 4 Task object that skips
    # read_stamped_prose(). Annex B/C get stamped here too since this is
    # the first point after analysis_crew where their files are final.
    annexB_prose_path = run_context.artifact_path("annexB_kcag.md")
    annexC_prose_path = run_context.artifact_path("annexC_bbn.md")
    stage3_prose_path = run_context.artifact_path("stage3.md")
    stage3_plan_path = run_context.artifact_path("stage3_test_plan.json")

    for required_path in (stage3_prose_path, stage3_plan_path):
        if not os.path.exists(required_path):
            state.current_stage = "stage3"
            set_stage_status(state, "stage3", StageStatus.FAIL)
            save_assessment_state(state, run_id)
            raise RuntimeError(
                f"Stage 3 did not produce {required_path} — Stage 4 cannot "
                f"be constructed. Run audit trail: {out_dir}/assessment_state.json"
            )

    for p in (annexB_prose_path, annexC_prose_path, stage3_prose_path):
        run_context.stamp_prose_file(p)

    stage3_text = run_context.read_stamped_prose(stage3_prose_path)
    stage3_plan = run_context.read_stamped_json(stage3_plan_path)
    stage2_vectors_for_stage3 = run_context.read_stamped_json(stage2_vectors_path)
    kcag_report_for_stage3 = run_context.read_stamped_json(run_context.artifact_path("kcag_report.json"))
    technique_index_for_stage3 = json.load(open("corpus-index/technique_index.json"))

    state.current_stage = "stage3"
    commit_stage_output(state, "stage3", stage3_prose_path, status=StageStatus.PENDING)
    save_assessment_state(state, run_id)

    # ---- STRUCTURED TEST-PLAN VALIDATION (deterministic, HARD BLOCK) ----
    # Runs BEFORE the existing prose safety gate. An LLM-generated plan
    # that is incomplete or references a nonexistent graph node, edge, or
    # technique ID must never reach Stage 4 merely because its prose
    # sounds convincing -- this is the actual referential check;
    # write_stage3_test_plan() (the writer tool) only performed shallow,
    # writer-time checks (schema shape, size, placeholders).
    plan_validation = validate_stage3_test_plan(
        plan=stage3_plan, stage2_vectors=stage2_vectors_for_stage3,
        kcag_report=kcag_report_for_stage3, technique_index=technique_index_for_stage3,
    )
    consistency = check_stage3_artifact_consistency(stage3_text=stage3_text, test_plan=stage3_plan)
    stage3_validation_report = {
        "is_valid": plan_validation["is_valid"] and consistency["is_consistent"],
        "plan_validation": plan_validation,
        "artifact_consistency": consistency,
    }
    stage3_validation_path = run_context.artifact_path("stage3_test_plan_validation.json")
    run_context.write_stamped_json(stage3_validation_path, stage3_validation_report)
    print(f"Stage 3 structured test-plan validation: "
          f"{'PASS' if stage3_validation_report['is_valid'] else 'FAIL'} — "
          f"{plan_validation['summary']} {consistency['summary']}")

    # enforce_stage3_test_plan_validation raises RuntimeError (after
    # persisting FAIL state) on an invalid result -- nothing below this
    # call is reachable on the failure path. It does NOT mark Stage 3
    # PASS on success: the existing prose safety gate below remains the
    # single place that transition happens, same separation of concerns
    # as enforce_stage3_safety_gate/finalize_stage4_state elsewhere in
    # this pipeline.
    enforce_stage3_test_plan_validation(
        state, run_id,
        is_valid=stage3_validation_report["is_valid"],
        summary=f"{plan_validation['summary']} {consistency['summary']}",
    )

    # ---- PRE-STAGE-4 SAFETY GATE (deterministic, HARD BLOCK) ----
    # This is the actual fix for the gap the crew split was built to close:
    # unlike check_phase0_safety_gate below (defense in depth, runs after
    # Stage 4's own human_input approval), this gate runs BEFORE Stage 4 is
    # even constructed. A non-compliant Stage 3 output now never reaches a
    # human approval prompt for Stage 4 at all. Independent of, and defense
    # in depth alongside, the structured validation above -- one validates
    # the STRUCTURED artifact, this one remains an independent check over
    # the human-readable prose, and is the check that actually promotes
    # Stage 3 to PASS.
    stage3_safety = check_stage3_safety_gate(stage3_text)
    stage3_gate_path = run_context.artifact_path("stage3_safety_gate.json")
    run_context.write_stamped_json(stage3_gate_path, stage3_safety)
    print(f"Pre-Stage-4 safety gate: "
          f"{'COMPLIANT' if stage3_safety['is_compliant'] else 'NON-COMPLIANT'} — {stage3_safety['summary']}")

    # enforce_stage3_safety_gate raises RuntimeError (after persisting FAIL
    # state) on a non-compliant result -- nothing below this call is
    # reachable on the failure path.
    enforce_stage3_safety_gate(
        state, run_id,
        is_compliant=stage3_safety["is_compliant"],
        summary=stage3_safety["summary"],
    )

    # ---- BUILD AND RUN STAGE 4 (separate crew, no live context=[t_stage3];
    # stage3_text/stage3_plan above are verified, stamped, run-and-corpus-
    # bound content — see build_stage4_task()'s docstring in tasks.py) ----
    t_stage4 = build_stage4_task(out_dir, stage3_content=stage3_text, stage3_test_plan=stage3_plan)

    stage4_crew = Crew(
        agents=[red_team_lead],
        tasks=[t_stage4],
        process=Process.sequential,
        verbose=True,
    )
    stage4_heartbeat_log = run_context.artifact_path("heartbeat.log")
    with heartbeat("stage4_crew", log_path=stage4_heartbeat_log):
        result = stage4_crew.kickoff(inputs={
            "sut_brief": brief_text,
            "file_count": c_count,
            "corpus_version": c_version,
        })

    # ---- FINALIZE STAGE 4 CONTENT BEFORE ANY STAMPING/HASHING ----
    # The corpus-version footer must be appended BEFORE stamp_prose_file
    # and commit_stage_output run on this file -- committing first and
    # appending after (a prior bug) leaves the recorded hash describing
    # content that no longer matches what's on disk.
    stage4_prose_path = run_context.artifact_path("stage4_mission_plan.md")
    if os.path.exists(stage4_prose_path):
        try:
            with open(stage4_prose_path, "a") as f:
                f.write(f"\n\n---\n*Analysis grounded in Corpus Version v{c_version} ({c_count} files)*")
        except Exception:
            pass
    run_context.stamp_prose_file(stage4_prose_path)

    # ---- VERIFY BOTH STRUCTURED AND PROSE STAGE 4 ARTIFACTS EXIST ----
    # Both are products of t_stage4's own human_input task and cannot
    # exist before it -- this check necessarily runs AFTER
    # stage4_crew.kickoff() above, so it cannot intercept that human
    # approval, only prevent the run from completing on top of a missing
    # or invalid structured plan.
    stage4_plan_path = run_context.artifact_path("stage4_execution_plan.json")
    for required_path in (stage4_prose_path, stage4_plan_path):
        if not os.path.exists(required_path):
            set_stage_status(state, "stage4", StageStatus.FAIL)
            state.current_stage = "stage4"
            save_assessment_state(state, run_id)
            raise RuntimeError(
                f"Stage 4 did not produce {required_path} — the run cannot "
                f"be finalized. Run audit trail: {out_dir}/assessment_state.json"
            )
    stage4_plan = run_context.read_stamped_json(stage4_plan_path)

    # ---- STRUCTURED STAGE 4 VALIDATION (deterministic, HARD BLOCK) ----
    # A plan that silently drops, alters, or invents a Stage 3 test
    # concept, weakens an inherited abort/recovery/telemetry requirement,
    # or weakens the approved Category 2/3 termination time or approving
    # roles must never let the run reach PASS merely because its prose
    # reads convincingly. write_stage4_execution_plan() (the writer tool)
    # only performed shallow, writer-time checks; this is the actual
    # referential check, run once, here, against the final artifacts.
    stage4_prose_for_validation = run_context.read_stamped_prose(stage4_prose_path)
    plan_validation4 = validate_stage4_execution_plan(plan=stage4_plan, stage3_test_plan=stage3_plan)
    consistency4 = check_stage4_artifact_consistency(stage4_text=stage4_prose_for_validation,
                                                      execution_plan=stage4_plan)
    stage4_validation_report = {
        "is_valid": plan_validation4["is_valid"] and consistency4["is_consistent"],
        "source_identity": {
            # Binds this report to the EXACT plan contents it validated --
            # canonical (sorted-key) content hash, not a Python repr, so
            # the check below can't be defeated by re-serializing the
            # same data with different key order. Without this, a
            # same-run Plan A -> Plan B swap after validation would pass
            # every check load_structured_stage4_run() previously ran
            # (state PASS, stamps matching, current schema valid) while
            # Plan B's Stage 3 bindings/inherited criteria/safety
            # controls were never actually checked against anything.
            "stage4_execution_plan_sha256": canonical_json_sha256(stage4_plan),
            "stage3_test_plan_sha256": canonical_json_sha256(stage3_plan),
        },
        "plan_validation": plan_validation4,
        "artifact_consistency": consistency4,
    }
    stage4_validation_path = run_context.artifact_path("stage4_execution_plan_validation.json")
    run_context.write_stamped_json(stage4_validation_path, stage4_validation_report)
    print(f"Stage 4 structured execution-plan validation: "
          f"{'PASS' if stage4_validation_report['is_valid'] else 'FAIL'} — "
          f"{plan_validation4['summary']} {consistency4['summary']}")

    # enforce_stage4_execution_plan_validation raises RuntimeError (after
    # persisting FAIL state) on an invalid result -- nothing below this
    # call is reachable on the failure path. It does NOT mark Stage 4
    # PASS on success: finalize_stage4_state below remains the single
    # place that transition happens, same separation of concerns as
    # enforce_stage3_test_plan_validation/enforce_stage3_safety_gate.
    enforce_stage4_execution_plan_validation(
        state, run_id,
        is_valid=stage4_validation_report["is_valid"],
        summary=f"{plan_validation4['summary']} {consistency4['summary']}",
    )

    # ---- FINAL PHASE 0 SAFETY CHECK: DEFENSE IN DEPTH ----
    # Stage 3 has already passed the deterministic pre-Stage-4 gate above
    # (enforce_stage3_safety_gate) before Stage 4 was ever constructed, and
    # the structured Stage 4 plan has already passed its own deterministic
    # gate immediately above. This third check confirms that the generated
    # Stage 4 mission plan PROSE carries forward the required safety-gate
    # language and does not contradict the already-approved Stage 3
    # assessment. It still fires after t_stage4's own human_input=True
    # approval inside stage4_crew.kickoff() above, so it cannot intercept
    # THAT approval — only the pre-Stage-4 gate can do that, and it
    # already ran.
    stage4_text = stage4_prose_for_validation
    safety = check_phase0_safety_gate(stage3_text, stage4_text)
    phase0_check_path = run_context.artifact_path("phase0_safety_check.md")
    with open(phase0_check_path, "w") as f:
        f.write("# Phase 0 Safety Gate Compliance Check\n\n")
        f.write(f"Category 2/3 payload detected: {safety['category_2_3_detected']}\n")
        f.write(f"Matched terms: {safety['matched_terms']}\n")
        f.write(f"Phase 0 Safety Gate section present: {safety['phase0_gate_present']}\n\n")
        f.write(f"STATUS: {'COMPLIANT' if safety['is_compliant'] else 'NON-COMPLIANT'}\n")
        f.write(safety["summary"] + "\n")
    run_context.stamp_prose_file(phase0_check_path)
    print(f"Phase 0 Safety Gate check: "
          f"{'COMPLIANT' if safety['is_compliant'] else 'NON-COMPLIANT'} — {safety['summary']}")

    # ---- FINALIZE STAGE 4 (single shared implementation — see src/state.py) ----
    finalize_stage4_state(
        state, run_id,
        stage4_path=stage4_prose_path,
        is_compliant=safety["is_compliant"],
        safety_summary=safety["summary"],
    )

    print("\n\n=== PIPELINE FINISHED ===")
    print(f"Run audit trail: {out_dir}/assessment_state.json")
    print(result)