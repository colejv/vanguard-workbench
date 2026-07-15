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
from src.stage3_validation import (validate_stage3_test_plan, check_stage3_artifact_consistency,
                                   build_stage3_validation_report, stage3_candidate_hash)
from src.stage3_flow import compile_stage3_until_valid, stage3_is_semantically_complete
from src.stage3_identity import SemanticIdentityMutation
from src.stage_transition import evaluate_stage3_transition, StageTransitionBlocked
from src.safety_timeline import (build_safety_timeline_contract,
                                 SafetyTimelineContradiction, SafetyTimelineAmbiguous)
from src.stage3_writer import compile_stage3_structured_output, build_referential_context
from src.stage4_validation import (validate_stage4_execution_plan, check_stage4_artifact_consistency,
                                   build_stage4_validation_report, stage4_candidate_hash)
from src.stage4_writer import compile_stage4_structured_output
from src.stage4_flow import compile_stage4_until_valid, stage4_is_semantically_complete
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
        annexB_done, annexC_done, stage3_prose_done, stage3_structured_done).
        Stage 3/4 are NEVER auto-skipped as full stages — both
        are human_input=True gates the analyst always re-approves fresh,
        and stage3 in particular is often exactly the stage being resumed
        TO (e.g. after fixing its prompt), never the stage being resumed
        PAST. The stage3_prose_done / stage3_structured_done split exists
        only to enable a compile-only resume: when the approved stage3.md
        prose already exists but stage3_test_plan.json does not, the
        structured plan is compiled from the existing prose without
        rerunning the prose task or any analysis-crew task."""
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
        stage3_prose_done = os.path.exists(os.path.join(out_dir, "stage3.md"))
        stage3_structured_done = os.path.exists(os.path.join(out_dir, "stage3_test_plan.json"))
        return (chunking_done, stage0_done, stage1_done, stage2_done,
                annexB_done, annexC_done, stage3_prose_done, stage3_structured_done)

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
    stage3_prose_done = stage3_structured_done = False
    if resume_run_id:
        (chunking_done, stage0_done, stage1_done,
         stage2_done, annexB_done, annexC_done,
         stage3_prose_done, stage3_structured_done) = detect_resume_progress(out_dir)
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
    t_stage1_write = tasks["t_stage1_write"]
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

    # ---- STAGE 0 CREW: corpus research/chunking + Reverse IPB signatures ----
    # Split from Stage 1/2 (previously one shared pre_crew.kickoff()) so a
    # missing stage0_output.json is caught HERE, before Stage 1's crew is
    # even constructed -- not discovered only after a whole shared crew
    # finished, by which point Stage 2 may already have run against prose
    # with no real Stage 0 artifact behind it. Same reasoning as the
    # Stage 3 -> Stage 4 trust boundary elsewhere in this file.
    stage0_tasks = []
    if not chunking_done:
        stage0_tasks += [t_research] + chunk_tasks
    if not stage0_done:
        stage0_tasks += [t_synthesize_stage0]

    heartbeat_log = run_context.artifact_path("heartbeat.log")
    print(f"Heartbeat log: {heartbeat_log} (tail -f it in a second terminal)")

    if stage0_tasks:
        print(f"stage0_crew will run {len(stage0_tasks)} task(s): "
              f"{[t.output_file.split('/')[-1] if t.output_file else t.agent.role for t in stage0_tasks][:6]}"
              f"{' ...' if len(stage0_tasks) > 6 else ''}")
        stage0_crew = Crew(
            agents=[researcher, decomposer],
            tasks=stage0_tasks,
            process=Process.sequential,
            verbose=True,
        )
        with heartbeat("stage0_crew", log_path=heartbeat_log):
            stage0_crew.kickoff(inputs={
                "sut_brief": brief_text,
                "file_count": c_count,
                "corpus_version": c_version,
            })
    else:
        print("stage0_crew: nothing to run — chunking and Stage 0 already complete "
              "for this run. Skipping stage0_crew.kickoff() entirely.")

    stage0_prose_path = run_context.artifact_path("stage0.md")
    if os.path.exists(stage0_prose_path):
        run_context.stamp_prose_file(stage0_prose_path)

    stage0_json_path = run_context.artifact_path("stage0_output.json")
    if not os.path.exists(stage0_json_path):
        set_stage_status(state, "stage0", StageStatus.FAIL)
        state.current_stage = "stage0"
        save_assessment_state(state, run_id)
        raise RuntimeError(
            f"Stage 0 did not produce {stage0_json_path} — the Reverse IPB agent may not "
            f"have called write_stage0_output. Stage 1 cannot proceed without it. Run "
            f"audit trail: {out_dir}/assessment_state.json"
        )
    commit_stage_output(state, "stage0", stage0_json_path, status=StageStatus.PENDING)
    state.current_stage = "stage1"
    save_assessment_state(state, run_id)

    # ---- STAGE 1 CREW: three-layer decomposition (prose only) ----
    # The write step is handled OUTSIDE CrewAI's agent executor (see
    # src/stage1_writer.py) to work around a reproducible CrewAI
    # agent-executor failure in which the Stage 1 writer task receives
    # an empty native-tool response. Direct reason_llm.call() with the
    # same model and Stage 1 content has been verified to return native
    # tool calls successfully. The underlying executor-level cause
    # remains unconfirmed.
    stage1_prose_path = run_context.artifact_path("stage1.md")
    stage1_json_path = run_context.artifact_path("stage1_output.json")
    stage1_prose_done = os.path.exists(stage1_prose_path)
    stage1_structured_done = os.path.exists(stage1_json_path)

    # Only rerun the prose task if stage1.md is actually missing — when
    # resuming a run where prose succeeded but the structured write
    # failed, skip straight to the direct write step below rather than
    # regenerating (and potentially overwriting) the valid prose.
    stage1_tasks = [] if stage1_prose_done else [t_stage1]

    if stage1_tasks:
        print(f"stage1_crew will run {len(stage1_tasks)} task(s): "
              f"{[t.output_file.split('/')[-1] if t.output_file else t.agent.role for t in stage1_tasks]}")
        stage1_crew = Crew(
            agents=[decomposer],
            tasks=stage1_tasks,
            process=Process.sequential,
            verbose=True,
        )
        with heartbeat("stage1_crew", log_path=heartbeat_log):
            stage1_crew.kickoff(inputs={
                "sut_brief": brief_text,
                "file_count": c_count,
                "corpus_version": c_version,
            })
    else:
        print("stage1_crew: nothing to run — Stage 1 prose already exists. "
              "Skipping stage1_crew.kickoff() entirely.")

    if os.path.exists(stage1_prose_path):
        run_context.stamp_prose_file(stage1_prose_path)

    # ---- STAGE 1 STRUCTURED WRITE (direct LLM call, not via CrewAI agent) ----
    if not stage1_structured_done:
        if not os.path.exists(stage1_prose_path):
            set_stage_status(state, "stage1", StageStatus.FAIL)
            state.current_stage = "stage1"
            save_assessment_state(state, run_id)
            raise RuntimeError(
                f"Stage 1 did not produce {stage1_prose_path} — the decomposer "
                f"agent's prose task failed. Stage 1 write cannot proceed without "
                f"the decomposition to translate."
            )

        from config.llm import reason_llm
        from src.tools import write_stage1_output
        from src.stage1_writer import compile_stage1_structured_output

        stage1_prose = run_context.read_stamped_prose(stage1_prose_path)

        try:
            compile_stage1_structured_output(
                stage1_prose=stage1_prose,
                llm=reason_llm,
                writer_tool=write_stage1_output,
                artifact_path=stage1_json_path,
            )
        except RuntimeError as e:
            set_stage_status(state, "stage1", StageStatus.FAIL)
            state.current_stage = "stage1"
            save_assessment_state(state, run_id)
            raise RuntimeError(
                f"{e} Run audit trail: {out_dir}/assessment_state.json"
            )

    if not os.path.exists(stage1_json_path):
        set_stage_status(state, "stage1", StageStatus.FAIL)
        state.current_stage = "stage1"
        save_assessment_state(state, run_id)
        raise RuntimeError(
            f"Stage 1 did not produce {stage1_json_path}. Run "
            f"audit trail: {out_dir}/assessment_state.json"
        )
    commit_stage_output(state, "stage1", stage1_json_path, status=StageStatus.PENDING)
    state.current_stage = "stage2"
    save_assessment_state(state, run_id)

    # ---- ATTRIBUTION-BOUNDARY CHECK (deterministic, warn-only) ----
    # Runs here, now that both stage0_output.json and stage1_output.json
    # are confirmed to actually exist (the hard checks above already
    # raised if either was missing) -- rather than trusting the
    # "ATTRIBUTION DISCIPLINE" prompt text alone. Checks every named
    # person/unit/component mentioned in the Stage 0 + Stage 1 prose
    # against the scratchpad (the documented boundary) and, as a
    # fallback, the raw locked corpus. High-confidence findings
    # (rank+name, ordinal+unit) are the enforcement signal; bare-phrase
    # findings are reported but not counted against is_clean (see the
    # false-positive calibration note in tools.py). This is warn-only,
    # not a RuntimeError, because unlike the corpus-lock and Stage 2
    # gates, regex-based entity extraction has a real residual
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

    # ---- STAGE 2 CREW: attack surface characterization ----
    stage2_tasks = [] if stage2_done else [t_stage2]

    if stage2_tasks:
        print(f"stage2_crew will run {len(stage2_tasks)} task(s): "
              f"{[t.output_file.split('/')[-1] if t.output_file else t.agent.role for t in stage2_tasks]}")
        stage2_crew = Crew(
            agents=[mapper],
            tasks=stage2_tasks,
            process=Process.sequential,
            verbose=True,
        )
        with heartbeat("stage2_crew", log_path=heartbeat_log):
            stage2_crew.kickoff(inputs={
                "sut_brief": brief_text,
                "file_count": c_count,
                "corpus_version": c_version,
            })
    else:
        print("stage2_crew: nothing to run — Stage 2 already complete for this run. "
              "Skipping stage2_crew.kickoff() entirely.")

    stage2_prose_path = run_context.artifact_path("stage2.md")
    if os.path.exists(stage2_prose_path):
        run_context.stamp_prose_file(stage2_prose_path)

    # ---- COMMIT STAGE 2 OUTPUT TO ASSESSMENT STATE ----
    # Stage 2 is committed PENDING here and promoted to PASS/FAIL immediately
    # below, once verify_stage2_vectors and validate_kcag actually run.
    stage2_vectors_path = run_context.artifact_path("stage2_vectors.json")
    if not os.path.exists(stage2_vectors_path):
        set_stage_status(state, "stage2", StageStatus.FAIL)
        state.current_stage = "stage2"
        save_assessment_state(state, run_id)
        raise RuntimeError(
            f"Stage 2 did not produce {stage2_vectors_path} — the mapper agent may not "
            f"have called write_stage2_vectors. Annex B and downstream cannot proceed "
            f"without it. Run audit trail: {out_dir}/assessment_state.json"
        )
    commit_stage_output(state, "stage2", stage2_vectors_path, status=StageStatus.PENDING)
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

    annexB_prose_path = run_context.artifact_path("annexB_kcag.md")
    annexC_prose_path = run_context.artifact_path("annexC_bbn.md")
    stage3_prose_path = run_context.artifact_path("stage3.md")
    stage3_plan_path = run_context.artifact_path("stage3_test_plan.json")

    # ---- INCONSISTENT-STATE CHECK (hard fail) ----
    # A structured Stage 3 plan without its approved source prose has
    # broken provenance — the plan claims to derive from a stage3.md that
    # doesn't exist. Refuse to continue rather than trust it.
    if stage3_structured_done and not stage3_prose_done:
        state.current_stage = "stage3"
        set_stage_status(state, "stage3", StageStatus.FAIL)
        save_assessment_state(state, run_id)
        raise RuntimeError(
            "Inconsistent Stage 3 state: stage3_test_plan.json exists "
            "without its source stage3.md. Run audit trail: "
            f"{out_dir}/assessment_state.json"
        )

    # ---- COMPILE-ONLY RESUME BRANCH ----
    # When the approved prose already exists but the structured plan does
    # not, compile the plan directly from the existing stage3.md WITHOUT
    # rerunning analysis_crew (no Annex B, no Annex C, no Stage 3 prose).
    # The structured compile still needs the KCAG report for referential
    # context, so a missing Annex B here is a hard error, not a silent
    # skip. Annex C is a separate concern and is intentionally NOT required
    # to compile the Stage 3 plan — only Stage 4 construction depends on it.
    stage3_compile_only = stage3_prose_done and not stage3_structured_done

    if stage3_compile_only:
        if not annexB_done:
            state.current_stage = "stage3"
            set_stage_status(state, "stage3", StageStatus.FAIL)
            save_assessment_state(state, run_id)
            raise RuntimeError(
                "Stage 3 prose exists but kcag_report.json is missing; "
                "structured compilation lacks required referential context. "
                f"Run audit trail: {out_dir}/assessment_state.json"
            )
        print("Stage 3 compile-only resume: stage3.md exists, "
              "stage3_test_plan.json missing — compiling the structured "
              "plan from existing prose without rerunning analysis_crew.")
    else:
        analysis_tasks = build_analysis_tasks(
            t_kcag_review=t_kcag_review,
            t_annexB=t_annexB,
            t_annexC=t_annexC,
            t_stage3=t_stage3,
            annexB_done=annexB_done,
            annexC_done=annexC_done,
            stage3_prose_done=stage3_prose_done,
        )

        print(f"analysis_crew will run {len(analysis_tasks)} task(s): "
              f"{[t.output_file.split('/')[-1] if t.output_file else t.agent.role for t in analysis_tasks]}")

        if analysis_tasks:
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
        # See finalize_kcag_review_artifact()'s docstring in tasks.py for
        # why this is a shared helper rather than inline logic, and for
        # what exactly is/isn't enforced.
        finalize_kcag_review_artifact(review_was_required=t_kcag_review is not None)

        # Stamp any prose newly produced by this crew run. stamp_prose_file
        # is idempotent (no-op on already-stamped files), but we only stamp
        # files that could be new this invocation — existing stamped prose
        # is validated by read_stamped_prose below, not re-stamped.
        if not os.path.exists(stage3_prose_path):
            state.current_stage = "stage3"
            set_stage_status(state, "stage3", StageStatus.FAIL)
            save_assessment_state(state, run_id)
            raise RuntimeError(
                f"Stage 3 did not produce {stage3_prose_path} — Stage 4 "
                f"cannot be constructed. Run audit trail: "
                f"{out_dir}/assessment_state.json"
            )
        for p in (annexB_prose_path, annexC_prose_path, stage3_prose_path):
            if os.path.exists(p):
                run_context.stamp_prose_file(p)

    # ---- ANNEX C -> STAGE 3 TRANSITION GATE (fail closed) ----
    # The framework requires the Annex C BBN threat score/phase estimate
    # BEFORE the authoritative Stage 3 artifact. Annex C deliberately BLOCKS
    # (rather than fabricating priors) when analyst inputs are absent. This
    # gate enforces that a blocked Annex C stops Stage 3 by default: the
    # structured compile begins only when Annex C is PASS or an authorized
    # waiver bound to this exact run/corpus/Annex-C-artifact is present.
    #
    # Placed at the compile convergence point (both the post-analysis and
    # compile-only-resume branches reach here) so that Annex C has been
    # produced by now, AND so no authoritative Stage 3 artifact
    # (stage3_test_plan.json) is ever created when the transition is blocked.
    # Previously the pipeline failed open, producing Stage 3/4 artifacts
    # while Annex C remained blocked.
    bbn_report_path = os.path.join(out_dir, "bbn_report.json")
    annex_c_report_for_gate = None
    if os.path.exists(bbn_report_path):
        try:
            annex_c_report_for_gate = run_context.read_stamped_json(bbn_report_path)
        except Exception:
            annex_c_report_for_gate = None

    stage3_waiver = None
    waiver_path = os.path.join(out_dir, "annexC_stage3_waiver.json")
    if os.path.exists(waiver_path):
        try:
            stage3_waiver = run_context.read_stamped_json(waiver_path)
        except Exception:
            stage3_waiver = None

    transition = evaluate_stage3_transition(
        annex_c_report=annex_c_report_for_gate,
        waiver=stage3_waiver,
        run_id=run_id,
        corpus_manifest_hash=state.corpus_manifest_hash,
    )
    state.current_stage = "stage3"
    if isinstance(getattr(state, "gate_decisions", None), list):
        state.gate_decisions.append(transition.audit_record())
    if not transition.allowed:
        # A missing prerequisite is BLOCKED, not an analytical FAIL.
        set_stage_status(state, "stage3", StageStatus.BLOCKED)
        save_assessment_state(state, run_id)
        raise StageTransitionBlocked(
            f"{transition.code}\n{transition.reason}\n"
            f"Run audit trail: {out_dir}/assessment_state.json"
        )
    print(f"Annex C -> Stage 3 transition gate: ALLOWED ({transition.code}) — "
          f"{transition.reason}")

    # ---- STAGE 3 STRUCTURED COMPILE + SEMANTIC REPAIR (both paths converge) ----
    # This is the actual trust boundary Stage 4 depends on. The structured
    # plan is compiled OUTSIDE CrewAI's agent executor (same rationale as
    # Stage 1). A schema-valid, writer-accepted candidate is NOT sufficient:
    # it must also pass the deep referential/semantic validator. The
    # stage3_flow orchestrator owns that loop (compile -> deep-validate ->
    # archive rejected -> regenerate with accumulated feedback), returning
    # only when a candidate passes both. crew.py stays thin: it loads
    # artifacts, builds the two callables, and calls the orchestrator.
    stage2_vectors_for_stage3 = run_context.read_stamped_json(stage2_vectors_path)
    kcag_report_for_stage3 = run_context.read_stamped_json(
        run_context.artifact_path("kcag_report.json"))
    technique_index_for_stage3 = json.load(open("corpus-index/technique_index.json"))

    stage3_validation_path = run_context.artifact_path("stage3_test_plan_validation.json")

    # Resume-state: a candidate that merely EXISTS is not "done" — it must
    # exist AND have a passing, hash-matched validation report. An
    # invalid-but-present candidate (e.g. a prior run's rejected plan) is
    # recompiled, not accepted.
    already_complete = False
    if os.path.exists(stage3_plan_path):
        try:
            existing_plan = run_context.read_stamped_json(stage3_plan_path)
            already_complete = stage3_is_semantically_complete(
                artifact_path=stage3_plan_path,
                validation_report_path=stage3_validation_path,
                current_candidate_hash=stage3_candidate_hash(existing_plan),
            )
        except Exception:
            already_complete = False

    if not already_complete:
        stage3_prose_for_compile = run_context.read_or_migrate_legacy_stamped_prose(
            stage3_prose_path)
        referential_context = build_referential_context(
            stage2_vectors=stage2_vectors_for_stage3,
            kcag_report=kcag_report_for_stage3,
        )
        from config.llm import reason_llm
        from src.tools import write_stage3_test_plan

        def _compile_candidate(*, external_feedback=""):
            compile_stage3_structured_output(
                stage3_prose=stage3_prose_for_compile,
                referential_context=referential_context,
                llm=reason_llm,
                writer_tool=write_stage3_test_plan,
                artifact_path=stage3_plan_path,
                external_feedback=external_feedback,
            )

        def _validate_candidate():
            # Read the candidate the compiler just wrote and deep-validate it.
            candidate_plan = run_context.read_stamped_json(stage3_plan_path)
            candidate_prose = run_context.read_stamped_prose(stage3_prose_path)
            plan_validation = validate_stage3_test_plan(
                plan=candidate_plan,
                stage2_vectors=stage2_vectors_for_stage3,
                kcag_report=kcag_report_for_stage3,
                technique_index=technique_index_for_stage3,
            )
            consistency = check_stage3_artifact_consistency(
                stage3_text=candidate_prose, test_plan=candidate_plan)
            report = build_stage3_validation_report(
                plan=candidate_plan,
                plan_validation=plan_validation,
                consistency=consistency,
                artifact_path=stage3_plan_path,
            )
            print(f"Stage 3 structured test-plan validation: "
                  f"{'PASS' if report['is_valid'] else 'FAIL'} — "
                  f"{plan_validation['summary']} {consistency['summary']}")
            return report

        def _write_validation_report(report):
            run_context.write_stamped_json(stage3_validation_path, report)

        try:
            compile_stage3_until_valid(
                compile_candidate=_compile_candidate,
                validate_candidate=_validate_candidate,
                write_validation_report=_write_validation_report,
                read_candidate=lambda: run_context.read_stamped_json(stage3_plan_path),
                identity_baseline_path=run_context.artifact_path("stage3_identity_baseline.json"),
                read_stamped_json=run_context.read_stamped_json,
                write_stamped_json=run_context.write_stamped_json,
                artifact_path=stage3_plan_path,
                validation_report_path=stage3_validation_path,
            )
        except (RuntimeError, SemanticIdentityMutation) as e:
            state.current_stage = "stage3"
            set_stage_status(state, "stage3", StageStatus.FAIL)
            save_assessment_state(state, run_id)
            raise type(e)(
                f"{e}\nRun audit trail: {out_dir}/assessment_state.json"
            )

    # ---- HARD GATE: a valid structured plan + report must now exist ----
    if not os.path.exists(stage3_plan_path):
        state.current_stage = "stage3"
        set_stage_status(state, "stage3", StageStatus.FAIL)
        save_assessment_state(state, run_id)
        raise RuntimeError(
            f"Stage 3 did not produce {stage3_plan_path} — Stage 4 cannot "
            f"be constructed. Run audit trail: {out_dir}/assessment_state.json"
        )

    stage3_text = run_context.read_stamped_prose(stage3_prose_path)
    stage3_plan = run_context.read_stamped_json(stage3_plan_path)
    stage3_validation_report = run_context.read_stamped_json(stage3_validation_path)

    state.current_stage = "stage3"
    commit_stage_output(state, "stage3", stage3_prose_path, status=StageStatus.PENDING)
    save_assessment_state(state, run_id)

    # enforce_stage3_test_plan_validation raises RuntimeError (after
    # persisting FAIL state) on an invalid result -- nothing below this
    # call is reachable on the failure path. After the orchestrator, the
    # report on disk is authoritative (valid, hash-matched). This call
    # remains the state-transition enforcement point: it does NOT mark
    # Stage 3 PASS on success (the prose safety gate below remains the
    # single place that transition happens), the same separation of
    # concerns as enforce_stage3_safety_gate/finalize_stage4_state.
    _pv = stage3_validation_report.get("plan_validation", {})
    _cons = stage3_validation_report.get("artifact_consistency", {})
    enforce_stage3_test_plan_validation(
        state, run_id,
        is_valid=stage3_validation_report["is_valid"],
        summary=f"{_pv.get('summary', '')} {_cons.get('summary', '')}",
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

    # ---- BUILD AND RUN STAGE 4 PROSE (separate crew, no live context=[t_stage3];
    # stage3_text/stage3_plan above are verified, stamped, run-and-corpus-
    # bound content — see build_stage4_task()'s docstring in tasks.py). This
    # crew now produces ONLY the human-reviewed MDMP prose; the structured
    # execution plan is compiled OUTSIDE the executor below (same rationale
    # and pattern as Stage 3), so Ollama's native-tool parser can't mangle
    # the large nested JSON. t_stage4 keeps human_input=True for analyst
    # approval of the prose. ----
    t_stage4 = build_stage4_task(out_dir, stage3_content=stage3_text, stage3_test_plan=stage3_plan)

    stage4_prose_path = run_context.artifact_path("stage4_mission_plan.md")
    stage4_plan_path = run_context.artifact_path("stage4_execution_plan.json")
    stage4_validation_path = run_context.artifact_path("stage4_execution_plan_validation.json")

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

    # ---- FINALIZE STAGE 4 PROSE BEFORE ANY STAMPING/HASHING ----
    # The corpus-version footer must be appended BEFORE stamp_prose_file
    # and commit_stage_output run on this file -- committing first and
    # appending after (a prior bug) leaves the recorded hash describing
    # content that no longer matches what's on disk.
    if os.path.exists(stage4_prose_path):
        try:
            with open(stage4_prose_path, "a") as f:
                f.write(f"\n\n---\n*Analysis grounded in Corpus Version v{c_version} ({c_count} files)*")
        except Exception:
            pass
    run_context.stamp_prose_file(stage4_prose_path)

    # ---- HARD GATE: the approved prose must exist before we can compile ----
    if not os.path.exists(stage4_prose_path):
        set_stage_status(state, "stage4", StageStatus.FAIL)
        state.current_stage = "stage4"
        save_assessment_state(state, run_id)
        raise RuntimeError(
            f"Stage 4 did not produce {stage4_prose_path} — the run cannot "
            f"be finalized. Run audit trail: {out_dir}/assessment_state.json"
        )

    # ---- STAGE 4 STRUCTURED COMPILE + SEMANTIC REPAIR ----
    # A schema-valid, writer-accepted candidate is not sufficient: it must
    # also pass the deep referential/consistency validator (Stage 3 test-ID
    # bindings, inherited criteria, phase/action structure, Phase 0 gate).
    # The stage4_flow orchestrator owns that loop; the Phase 0 gate is
    # overlaid deterministically from the VALIDATED Stage 3 plan (never the
    # model). crew.py stays thin: load artifacts, build callables, call the
    # orchestrator.
    stage4_prose_for_validation = run_context.read_stamped_prose(stage4_prose_path)

    # ---- SAFETY-TIMELINE CONTRACT (hard safety-contract enforcement) ----
    # Before compiling/overlaying anything, assemble the authoritative safety
    # timelines from Stage 3 prose, Stage 3 JSON, and Stage 4 prose, and
    # require ONE value per control. A contradiction (e.g. Stage 4 Phase 0
    # prose says active signals cease in 15s while the structured gate says
    # 900s) or an unclassifiable timeline is a HARD STOP — no value is
    # selected or normalized, and no Stage 4 artifact is produced. This is
    # the fix for the overlay defect that previously propagated one of two
    # conflicting numbers silently. The failure is NOT feedback the repair
    # loop can rewrite; it stops the run for analyst resolution.
    stage3_prose_for_timeline = run_context.read_stamped_prose(stage3_prose_path)
    safety_contract = build_safety_timeline_contract(
        stage3_prose=stage3_prose_for_timeline,
        stage3_plan=stage3_plan,
        stage4_prose=stage4_prose_for_validation,
    )
    try:
        safety_contract.require_consistent()
    except (SafetyTimelineContradiction, SafetyTimelineAmbiguous) as e:
        set_stage_status(state, "stage4", StageStatus.FAIL)
        state.current_stage = "stage4"
        save_assessment_state(state, run_id)
        raise type(e)(
            f"{e}\nRun audit trail: {out_dir}/assessment_state.json"
        )

    already_complete4 = False
    if os.path.exists(stage4_plan_path):
        try:
            existing_plan4 = run_context.read_stamped_json(stage4_plan_path)
            already_complete4 = stage4_is_semantically_complete(
                artifact_path=stage4_plan_path,
                validation_report_path=stage4_validation_path,
                current_candidate_hash=stage4_candidate_hash(existing_plan4),
            )
        except Exception:
            already_complete4 = False

    if not already_complete4:
        stage4_referential_context = build_referential_context(
            stage2_vectors=stage2_vectors_for_stage3,
            kcag_report=kcag_report_for_stage3,
        )
        from config.llm import reason_llm
        from src.tools import write_stage4_execution_plan

        def _compile_candidate4(*, external_feedback=""):
            compile_stage4_structured_output(
                stage4_prose=stage4_prose_for_validation,
                referential_context=stage4_referential_context,
                stage3_test_plan=stage3_plan,
                llm=reason_llm,
                writer_tool=write_stage4_execution_plan,
                artifact_path=stage4_plan_path,
                external_feedback=external_feedback,
                safety_timeline_contract=safety_contract,
            )

        def _validate_candidate4():
            candidate_plan = run_context.read_stamped_json(stage4_plan_path)
            plan_validation4 = validate_stage4_execution_plan(
                plan=candidate_plan, stage3_test_plan=stage3_plan)
            consistency4 = check_stage4_artifact_consistency(
                stage4_text=stage4_prose_for_validation, execution_plan=candidate_plan)
            report = build_stage4_validation_report(
                plan=candidate_plan, stage3_test_plan=stage3_plan,
                plan_validation=plan_validation4, consistency=consistency4,
            )
            print(f"Stage 4 structured execution-plan validation: "
                  f"{'PASS' if report['is_valid'] else 'FAIL'} — "
                  f"{plan_validation4['summary']} {consistency4['summary']}")
            return report

        def _write_validation_report4(report):
            run_context.write_stamped_json(stage4_validation_path, report)

        try:
            compile_stage4_until_valid(
                compile_candidate=_compile_candidate4,
                validate_candidate=_validate_candidate4,
                write_validation_report=_write_validation_report4,
                artifact_path=stage4_plan_path,
                validation_report_path=stage4_validation_path,
            )
        except RuntimeError as e:
            set_stage_status(state, "stage4", StageStatus.FAIL)
            state.current_stage = "stage4"
            save_assessment_state(state, run_id)
            raise RuntimeError(
                f"{e} Run audit trail: {out_dir}/assessment_state.json"
            )

    # ---- HARD GATE: valid structured plan + report must now exist ----
    if not os.path.exists(stage4_plan_path):
        set_stage_status(state, "stage4", StageStatus.FAIL)
        state.current_stage = "stage4"
        save_assessment_state(state, run_id)
        raise RuntimeError(
            f"Stage 4 did not produce {stage4_plan_path} — the run cannot "
            f"be finalized. Run audit trail: {out_dir}/assessment_state.json"
        )
    stage4_plan = run_context.read_stamped_json(stage4_plan_path)
    stage4_validation_report = run_context.read_stamped_json(stage4_validation_path)

    # enforce_stage4_execution_plan_validation raises RuntimeError (after
    # persisting FAIL state) on an invalid result -- nothing below this
    # call is reachable on the failure path. After the orchestrator, the
    # report on disk is authoritative (valid, hash-bound). It does NOT mark
    # Stage 4 PASS on success: finalize_stage4_state below remains the
    # single place that transition happens, same separation of concerns as
    # enforce_stage3_test_plan_validation/enforce_stage3_safety_gate.
    _pv4 = stage4_validation_report.get("plan_validation", {})
    _cons4 = stage4_validation_report.get("artifact_consistency", {})
    enforce_stage4_execution_plan_validation(
        state, run_id,
        is_valid=stage4_validation_report["is_valid"],
        summary=f"{_pv4.get('summary', '')} {_cons4.get('summary', '')}",
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