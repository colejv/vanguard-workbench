from crewai import Crew, Process, Task
import sys, os, json

from src.agents import (
    researcher,
    decomposer,
    mapper,
    modeler,
    red_team_lead,
    orchestrator,
)
from src.tasks import (
    build_tasks,
    build_stage4_task,
    build_kcag_review_task,
    build_analysis_tasks,
    finalize_kcag_review_artifact,
)
from src.tools import (
    extract_to_scratch,
    verify_corpus_lock_gate,
    discover_corpus_files,
    read_corpus_file,
    check_attribution_boundary,
    check_phase0_safety_gate,
    check_stage3_safety_gate,
    verify_stage2_vectors,
    validate_kcag,
)
from src.stage3_validation import (
    validate_stage3_test_plan,
    check_stage3_artifact_consistency,
    build_stage3_validation_report,
    stage3_candidate_hash,
)
from src.stage3_flow import (
    compile_stage3_until_valid,
    stage3_is_semantically_complete,
)
from src.stage3_writer import (
    compile_stage3_structured_output,
    build_referential_context,
)
from src.stage4_validation import (
    validate_stage4_execution_plan,
    check_stage4_artifact_consistency,
    build_stage4_validation_report,
    stage4_candidate_hash,
)
from src.stage4_writer import compile_stage4_structured_output
from src.stage4_flow import (
    compile_stage4_until_valid,
    stage4_is_semantically_complete,
)
from src.schemas import StageStatus
from src.state import (
    new_run_id,
    run_output_dir,
    init_assessment_state,
    save_assessment_state,
    commit_stage_output,
    set_stage_status,
    finalize_stage4_state,
    enforce_stage3_safety_gate,
    enforce_stage3_test_plan_validation,
    enforce_stage4_execution_plan_validation,
    canonical_json_sha256,
)
from src import run_context
from src.heartbeat import heartbeat


if __name__ == "__main__":
    import glob
    import hashlib

    def snapshot_corpus(
        src_dir="sources",
        index_dir="corpus-index",
    ):
        """
        Hash the corpus, compare it to the latest manifest, and create a
        new corpus version when its contents change.
        """
        os.makedirs(index_dir, exist_ok=True)

        def hash_file(filepath):
            with open(filepath, "rb") as file:
                return hashlib.sha256(file.read()).hexdigest()

        current_files = discover_corpus_files(src_dir)

        current_state = {
            filename: hash_file(
                os.path.join(src_dir, filename)
            )
            for filename in current_files
        }

        current_hash = hashlib.sha256(
            json.dumps(
                current_state,
                sort_keys=True,
            ).encode()
        ).hexdigest()

        manifests = glob.glob(
            os.path.join(
                index_dir,
                "manifest_v*.json",
            )
        )

        latest_version = 0
        latest_hash = ""

        for manifest in manifests:
            try:
                version = int(
                    os.path.basename(manifest)
                    .split("_v")[1]
                    .split(".json")[0]
                )

                if version > latest_version:
                    latest_version = version

                    with open(manifest, "r") as manifest_file:
                        latest_hash = json.load(
                            manifest_file
                        ).get("corpus_hash", "")
            except (
                IndexError,
                ValueError,
                json.JSONDecodeError,
            ):
                continue

        if current_hash != latest_hash:
            new_version = latest_version + 1

            manifest_data = {
                "version": new_version,
                "corpus_hash": current_hash,
                "file_count": len(current_files),
                "files": current_state,
            }

            with open(
                os.path.join(
                    index_dir,
                    f"manifest_v{new_version}.json",
                ),
                "w",
            ) as manifest_file:
                json.dump(
                    manifest_data,
                    manifest_file,
                    indent=2,
                )

            return (
                new_version,
                len(current_files),
                "UPDATED",
            )

        return (
            latest_version,
            len(current_files),
            "UNCHANGED",
        )

    def detect_resume_progress(out_dir):
        """
        Detect which expensive steps completed in a previous interrupted
        attempt for this exact run ID.

        Artifacts are considered present based on their defining files,
        rather than only assessment-state flags, because CrewAI can write
        task output before kickoff() returns and before crew.py commits the
        result into assessment_state.json.

        Stage 3 prose and structured output are tracked separately to
        support compile-only resume.

        Stage 4 prose is handled later using the same compile-only resume
        principle: an existing approved mission-plan file is preserved and
        is not regenerated merely because structured compilation failed.
        """
        scratch_path = os.path.join(
            out_dir,
            "_stage0_scratch.md",
        )

        chunking_done = (
            os.path.exists(scratch_path)
            and os.path.getsize(scratch_path) > 0
        )

        stage0_done = (
            os.path.exists(
                os.path.join(
                    out_dir,
                    "stage0_output.json",
                )
            )
            and os.path.exists(
                os.path.join(
                    out_dir,
                    "stage0.md",
                )
            )
        )

        stage1_done = (
            os.path.exists(
                os.path.join(
                    out_dir,
                    "stage1_output.json",
                )
            )
            and os.path.exists(
                os.path.join(
                    out_dir,
                    "stage1.md",
                )
            )
        )

        stage2_done = (
            os.path.exists(
                os.path.join(
                    out_dir,
                    "stage2_vectors.json",
                )
            )
            and os.path.exists(
                os.path.join(
                    out_dir,
                    "stage2.md",
                )
            )
        )

        annexB_done = os.path.exists(
            os.path.join(
                out_dir,
                "kcag_report.json",
            )
        )

        annexC_done = os.path.exists(
            os.path.join(
                out_dir,
                "bbn_report.json",
            )
        )

        stage3_prose_done = os.path.exists(
            os.path.join(
                out_dir,
                "stage3.md",
            )
        )

        stage3_structured_done = os.path.exists(
            os.path.join(
                out_dir,
                "stage3_test_plan.json",
            )
        )

        return (
            chunking_done,
            stage0_done,
            stage1_done,
            stage2_done,
            annexB_done,
            annexC_done,
            stage3_prose_done,
            stage3_structured_done,
        )

    # ------------------------------------------------------------------
    # CLI: --resume <run_id>
    # ------------------------------------------------------------------

    resume_run_id = None

    if "--resume" in sys.argv:
        resume_index = sys.argv.index("--resume")

        if resume_index + 1 >= len(sys.argv):
            raise SystemExit(
                "--resume requires a run_id argument, for example "
                "--resume vaf_20260709_143022"
            )

        resume_run_id = sys.argv[
            resume_index + 1
        ]

    # ------------------------------------------------------------------
    # Preflight and corpus snapshot
    # ------------------------------------------------------------------

    print("Running pre-flight corpus snapshot...")

    (
        corpus_version,
        corpus_file_count,
        corpus_status,
    ) = snapshot_corpus()

    print(
        f"Corpus Version: v{corpus_version} | "
        f"File Count: {corpus_file_count} | "
        f"Status: {corpus_status}"
    )

    manifest_path = os.path.join(
        "corpus-index",
        f"manifest_v{corpus_version}.json",
    )

    with open(manifest_path, "rb") as manifest_file:
        corpus_manifest_hash = (
            "sha256:"
            + hashlib.sha256(
                manifest_file.read()
            ).hexdigest()
        )

    if resume_run_id:
        run_id = resume_run_id
        out_dir = run_output_dir(run_id)

        if not os.path.isdir(out_dir):
            raise SystemExit(
                f"--resume {run_id}: {out_dir} does not exist. "
                "Nothing to resume."
            )

        print(f"Resuming run: {run_id}")

        from src.state import load_assessment_state

        state = load_assessment_state(run_id)

        if (
            state.corpus_manifest_hash
            != corpus_manifest_hash
        ):
            raise RuntimeError(
                f"Cannot resume {run_id}: corpus has changed "
                "since this run started "
                f"(was {state.corpus_manifest_hash}, "
                f"now {corpus_manifest_hash}). "
                "Start a fresh run instead."
            )
    else:
        run_id = new_run_id()
        out_dir = run_output_dir(run_id)

        print(f"Run ID: {run_id}")

        state = init_assessment_state(
            run_id,
            corpus_manifest_hash,
        )

        save_assessment_state(
            state,
            run_id,
        )

    run_context.set_active_run(
        run_id,
        corpus_manifest_hash,
        out_dir,
    )

    # ------------------------------------------------------------------
    # Corpus lock gate
    # ------------------------------------------------------------------

    lock = verify_corpus_lock_gate()

    print(
        f"Corpus lock: {lock['status']} — "
        f"{lock['summary']}"
    )

    if not lock["is_valid"]:
        raise RuntimeError(
            "Corpus lock verification FAILED: "
            f"{lock['summary']} "
            "Stage 0 NOT started. Re-freeze the corpus or "
            "restore the drifted files before rerunning. "
            f"Run audit trail: "
            f"{out_dir}/assessment_state.json"
        )

    print("Reading assessment brief...")

    with open("collection/brief.md") as brief_file:
        brief_text = brief_file.read()

    # ------------------------------------------------------------------
    # Resume progress
    # ------------------------------------------------------------------

    chunking_done = False
    stage0_done = False
    stage1_done = False
    stage2_done = False
    annexB_done = False
    annexC_done = False
    stage3_prose_done = False
    stage3_structured_done = False

    if resume_run_id:
        (
            chunking_done,
            stage0_done,
            stage1_done,
            stage2_done,
            annexB_done,
            annexC_done,
            stage3_prose_done,
            stage3_structured_done,
        ) = detect_resume_progress(out_dir)

        print(
            "Resume progress: "
            f"chunking_done={chunking_done}, "
            f"stage0_done={stage0_done}, "
            f"stage1_done={stage1_done}, "
            f"stage2_done={stage2_done}, "
            f"annexB_done={annexB_done}, "
            f"annexC_done={annexC_done}"
        )

    # ------------------------------------------------------------------
    # Corpus chunking
    # ------------------------------------------------------------------

    scratch_path = run_context.artifact_path(
        "_stage0_scratch.md"
    )

    chunks_path = run_context.artifact_path(
        "corpus_chunks.json"
    )

    if chunking_done:
        print(
            "Skipping corpus chunking — "
            f"{scratch_path} is already populated."
        )

        chunks = []
    else:
        open(
            scratch_path,
            "a",
        ).close()

        print("Assembling corpus from chunks...")

        source_directory = "sources"
        source_files = discover_corpus_files(
            source_directory
        )

        chunk_size = 60000
        chunks = []
        current_chunk = []
        current_length = 0

        for filename in source_files:
            content = (
                f"\n===== {filename} =====\n"
                + read_corpus_file(
                    os.path.join(
                        source_directory,
                        filename,
                    )
                )
            )

            if (
                current_length + len(content)
                > chunk_size
                and current_chunk
            ):
                chunks.append(
                    "".join(current_chunk)
                )

                current_chunk = []
                current_length = 0

            current_chunk.append(content)
            current_length += len(content)

        if current_chunk:
            chunks.append(
                "".join(current_chunk)
            )

        total_chars = sum(
            len(chunk)
            for chunk in chunks
        )

        print(
            f"Corpus: {len(source_files)} files, "
            f"{total_chars:,} chars, "
            f"{len(chunks)} chunks"
        )

        run_context.write_stamped_json(
            chunks_path,
            {
                "chunks": chunks,
                "total": len(chunks),
                "files": len(source_files),
            },
        )

    # ------------------------------------------------------------------
    # Resume context
    # ------------------------------------------------------------------

    resume_context = {}

    if annexB_done:
        annexB_prose_path = run_context.artifact_path(
            "annexB_kcag.md"
        )

        run_context.stamp_prose_file(
            annexB_prose_path
        )

        annexB_content = run_context.read_stamped_prose(
            annexB_prose_path
        )

        if not annexC_done:
            resume_context["t_annexC"] = (
                annexB_content
            )

            print(
                "Injecting completed Annex B output into "
                "Annex C."
            )
    elif stage2_done:
        stage2_prose_path = run_context.artifact_path(
            "stage2.md"
        )

        run_context.stamp_prose_file(
            stage2_prose_path
        )

        resume_context["t_annexB"] = (
            run_context.read_stamped_prose(
                stage2_prose_path
            )
        )

        print(
            "Injecting completed Stage 2 output into "
            "Annex B."
        )
    elif stage1_done:
        stage1_prose_path = run_context.artifact_path(
            "stage1.md"
        )

        run_context.stamp_prose_file(
            stage1_prose_path
        )

        resume_context["t_stage2"] = (
            run_context.read_stamped_prose(
                stage1_prose_path
            )
        )

        print(
            "Injecting completed Stage 1 output into "
            "Stage 2."
        )
    elif stage0_done:
        stage0_prose_path = run_context.artifact_path(
            "stage0.md"
        )

        run_context.stamp_prose_file(
            stage0_prose_path
        )

        resume_context["t_stage1"] = (
            run_context.read_stamped_prose(
                stage0_prose_path
            )
        )

        print(
            "Injecting completed Stage 0 output into "
            "Stage 1."
        )

    if stage2_done:
        stage2_prose_path = run_context.artifact_path(
            "stage2.md"
        )

        run_context.stamp_prose_file(
            stage2_prose_path
        )

        resume_context["t_stage3_stage2"] = (
            run_context.read_stamped_prose(
                stage2_prose_path
            )
        )

    if annexB_done:
        annexB_prose_path = run_context.artifact_path(
            "annexB_kcag.md"
        )

        run_context.stamp_prose_file(
            annexB_prose_path
        )

        resume_context["t_stage3_annexb"] = (
            run_context.read_stamped_prose(
                annexB_prose_path
            )
        )

    if stage2_done or annexB_done:
        completed_context = []

        if stage2_done:
            completed_context.append(
                "Stage 2"
            )

        if annexB_done:
            completed_context.append(
                "Annex B"
            )

        print(
            "Stage 3 will receive injected context for: "
            f"{' and '.join(completed_context)}."
        )

    # ------------------------------------------------------------------
    # Task assembly
    # ------------------------------------------------------------------

    tasks = build_tasks(
        out_dir,
        resume_context=resume_context,
    )

    t_research = tasks["t_research"]
    t_synthesize_stage0 = tasks[
        "t_synthesize_stage0"
    ]
    t_stage1 = tasks["t_stage1"]
    t_stage1_write = tasks["t_stage1_write"]
    t_stage2 = tasks["t_stage2"]
    t_annexB = tasks["t_annexB"]
    t_annexC = tasks["t_annexC"]
    t_stage3 = tasks["t_stage3"]

    chunk_tasks = []

    for index, chunk in enumerate(chunks):
        chunk_tasks.append(
            Task(
                description=(
                    f"You are processing corpus chunk index "
                    f"{index}.\n\n"
                    f"=== CHUNK CONTENT ===\n"
                    f"{chunk}\n"
                    f"=====================\n\n"
                    "Extract EVERY named system, AAMCAT or "
                    "other subsystem, vendor product, interface, "
                    "protocol, version, exercise event, named "
                    "person, and organization. Call "
                    "extract_to_scratch with the chunk index on "
                    "the first line and your findings below it."
                ),
                expected_output=(
                    f"Confirmation that chunk {index} findings "
                    "were written to the scratchpad."
                ),
                agent=decomposer,
                tools=[extract_to_scratch],
            )
        )

    heartbeat_log = run_context.artifact_path(
        "heartbeat.log"
    )

    print(
        f"Heartbeat log: {heartbeat_log} "
        "(tail -f it in a second terminal)"
    )

    # ------------------------------------------------------------------
    # Stage 0
    # ------------------------------------------------------------------

    stage0_tasks = []

    if not chunking_done:
        stage0_tasks += (
            [t_research]
            + chunk_tasks
        )

    if not stage0_done:
        stage0_tasks.append(
            t_synthesize_stage0
        )

    if stage0_tasks:
        print(
            f"stage0_crew will run "
            f"{len(stage0_tasks)} task(s)."
        )

        stage0_crew = Crew(
            agents=[
                researcher,
                decomposer,
            ],
            tasks=stage0_tasks,
            process=Process.sequential,
            verbose=True,
        )

        with heartbeat(
            "stage0_crew",
            log_path=heartbeat_log,
        ):
            stage0_crew.kickoff(
                inputs={
                    "sut_brief": brief_text,
                    "file_count": corpus_file_count,
                    "corpus_version": corpus_version,
                }
            )
    else:
        print(
            "stage0_crew: nothing to run."
        )

    stage0_prose_path = run_context.artifact_path(
        "stage0.md"
    )

    if os.path.exists(stage0_prose_path):
        run_context.stamp_prose_file(
            stage0_prose_path
        )

    stage0_json_path = run_context.artifact_path(
        "stage0_output.json"
    )

    if not os.path.exists(stage0_json_path):
        set_stage_status(
            state,
            "stage0",
            StageStatus.FAIL,
        )

        state.current_stage = "stage0"

        save_assessment_state(
            state,
            run_id,
        )

        raise RuntimeError(
            f"Stage 0 did not produce "
            f"{stage0_json_path}. "
            "Stage 1 cannot proceed. "
            f"Run audit trail: "
            f"{out_dir}/assessment_state.json"
        )

    commit_stage_output(
        state,
        "stage0",
        stage0_json_path,
        status=StageStatus.PENDING,
    )

    state.current_stage = "stage1"

    save_assessment_state(
        state,
        run_id,
    )

    # ------------------------------------------------------------------
    # Stage 1
    # ------------------------------------------------------------------

    stage1_prose_path = run_context.artifact_path(
        "stage1.md"
    )

    stage1_json_path = run_context.artifact_path(
        "stage1_output.json"
    )

    stage1_prose_done = os.path.exists(
        stage1_prose_path
    )

    stage1_structured_done = os.path.exists(
        stage1_json_path
    )

    stage1_tasks = (
        []
        if stage1_prose_done
        else [t_stage1]
    )

    if stage1_tasks:
        print(
            f"stage1_crew will run "
            f"{len(stage1_tasks)} task(s)."
        )

        stage1_crew = Crew(
            agents=[decomposer],
            tasks=stage1_tasks,
            process=Process.sequential,
            verbose=True,
        )

        with heartbeat(
            "stage1_crew",
            log_path=heartbeat_log,
        ):
            stage1_crew.kickoff(
                inputs={
                    "sut_brief": brief_text,
                    "file_count": corpus_file_count,
                    "corpus_version": corpus_version,
                }
            )
    else:
        print(
            "stage1_crew: Stage 1 prose already exists."
        )

    if os.path.exists(stage1_prose_path):
        run_context.stamp_prose_file(
            stage1_prose_path
        )

    if not stage1_structured_done:
        if not os.path.exists(stage1_prose_path):
            set_stage_status(
                state,
                "stage1",
                StageStatus.FAIL,
            )

            state.current_stage = "stage1"

            save_assessment_state(
                state,
                run_id,
            )

            raise RuntimeError(
                f"Stage 1 did not produce "
                f"{stage1_prose_path}."
            )

        from config.llm import reason_llm
        from src.tools import write_stage1_output
        from src.stage1_writer import (
            compile_stage1_structured_output,
        )

        stage1_prose = (
            run_context.read_stamped_prose(
                stage1_prose_path
            )
        )

        try:
            compile_stage1_structured_output(
                stage1_prose=stage1_prose,
                llm=reason_llm,
                writer_tool=write_stage1_output,
                artifact_path=stage1_json_path,
            )
        except RuntimeError as exc:
            set_stage_status(
                state,
                "stage1",
                StageStatus.FAIL,
            )

            state.current_stage = "stage1"

            save_assessment_state(
                state,
                run_id,
            )

            raise RuntimeError(
                f"{exc} Run audit trail: "
                f"{out_dir}/assessment_state.json"
            )

    if not os.path.exists(stage1_json_path):
        set_stage_status(
            state,
            "stage1",
            StageStatus.FAIL,
        )

        state.current_stage = "stage1"

        save_assessment_state(
            state,
            run_id,
        )

        raise RuntimeError(
            f"Stage 1 did not produce "
            f"{stage1_json_path}."
        )

    commit_stage_output(
        state,
        "stage1",
        stage1_json_path,
        status=StageStatus.PENDING,
    )

    state.current_stage = "stage2"

    save_assessment_state(
        state,
        run_id,
    )

    # ------------------------------------------------------------------
    # Attribution boundary
    # ------------------------------------------------------------------

    prose = ""

    for prose_path in (
        stage0_prose_path,
        stage1_prose_path,
    ):
        if os.path.exists(prose_path):
            prose += (
                run_context.read_stamped_prose(
                    prose_path
                )
                + "\n"
            )

    scratch_text = (
        open(scratch_path).read()
        if os.path.exists(scratch_path)
        else ""
    )

    corpus_text = ""

    if os.path.exists(chunks_path):
        corpus_text = "\n".join(
            run_context.read_stamped_json(
                chunks_path
            )["chunks"]
        )

    attribution = check_attribution_boundary(
        prose,
        scratch_text,
        corpus_text,
    )

    attribution_path = run_context.artifact_path(
        "attribution_check.md"
    )

    with open(attribution_path, "w") as report_file:
        report_file.write(
            "# Attribution Boundary Check "
            "(Stage 0 + Stage 1)\n\n"
        )

        report_file.write(
            f"Entities checked: "
            f"{attribution['checked']}\n\n"
        )

        report_file.write(
            "## High-confidence\n"
        )

        report_file.write(
            "- Traceable: "
            f"{attribution['high_confidence']['traceable']}\n"
        )

        report_file.write(
            "- Extraction gap: "
            f"{attribution['high_confidence']['extraction_gap']}\n"
        )

        report_file.write(
            "- Untraceable: "
            f"{attribution['high_confidence']['untraceable']}\n\n"
        )

        report_file.write(
            "## Advisory\n"
        )

        report_file.write(
            "- Traceable: "
            f"{attribution['advisory']['traceable']}\n"
        )

        report_file.write(
            "- Extraction gap: "
            f"{attribution['advisory']['extraction_gap']}\n"
        )

        report_file.write(
            "- Untraceable: "
            f"{attribution['advisory']['untraceable']}\n"
        )

    run_context.stamp_prose_file(
        attribution_path
    )

    if attribution["is_clean"]:
        print(
            "Attribution check: CLEAN."
        )
    else:
        print(
            "Attribution check: FLAGGED — human review "
            f"required. See {attribution_path}."
        )

    # ------------------------------------------------------------------
    # Stage 2
    # ------------------------------------------------------------------

    stage2_tasks = (
        []
        if stage2_done
        else [t_stage2]
    )

    if stage2_tasks:
        print(
            f"stage2_crew will run "
            f"{len(stage2_tasks)} task(s)."
        )

        stage2_crew = Crew(
            agents=[mapper],
            tasks=stage2_tasks,
            process=Process.sequential,
            verbose=True,
        )

        with heartbeat(
            "stage2_crew",
            log_path=heartbeat_log,
        ):
            stage2_crew.kickoff(
                inputs={
                    "sut_brief": brief_text,
                    "file_count": corpus_file_count,
                    "corpus_version": corpus_version,
                }
            )
    else:
        print(
            "stage2_crew: Stage 2 already complete."
        )

    stage2_prose_path = run_context.artifact_path(
        "stage2.md"
    )

    if os.path.exists(stage2_prose_path):
        run_context.stamp_prose_file(
            stage2_prose_path
        )

    stage2_vectors_path = run_context.artifact_path(
        "stage2_vectors.json"
    )

    if not os.path.exists(stage2_vectors_path):
        set_stage_status(
            state,
            "stage2",
            StageStatus.FAIL,
        )

        state.current_stage = "stage2"

        save_assessment_state(
            state,
            run_id,
        )

        raise RuntimeError(
            f"Stage 2 did not produce "
            f"{stage2_vectors_path}."
        )

    commit_stage_output(
        state,
        "stage2",
        stage2_vectors_path,
        status=StageStatus.PENDING,
    )

    save_assessment_state(
        state,
        run_id,
    )

    verification = verify_stage2_vectors(
        index_path=(
            "corpus-index/"
            "technique_index.json"
        )
    )

    stage2_verification_path = (
        run_context.artifact_path(
            "stage2_verification.md"
        )
    )

    with open(
        stage2_verification_path,
        "w",
    ) as report_file:
        report_file.write(
            "# Stage 2 Verification\n\n"
        )

        report_file.write(
            f"STATUS: "
            f"{verification['status']}\n\n"
        )

        report_file.write(
            verification["summary"]
            + "\n\n"
        )

        for invalid_edge in verification[
            "invalid_edges"
        ]:
            suggestion = (
                invalid_edge["suggestion"][0]["id"]
                if invalid_edge["suggestion"]
                else "none"
            )

            report_file.write(
                f"- INVALID edge"
                f"[{invalid_edge['edge_index']}] "
                f"`{invalid_edge['technique']}` "
                f"({invalid_edge['reason']}) — "
                f"suggest `{suggestion}`\n"
            )

        for gap_edge in verification[
            "gap_edges"
        ]:
            report_file.write(
                f"- GAP edge"
                f"[{gap_edge['edge_index']}] "
                f"`{gap_edge['technique']}`\n"
            )

    run_context.stamp_prose_file(
        stage2_verification_path
    )

    if not verification["is_valid"]:
        set_stage_status(
            state,
            "stage2",
            StageStatus.FAIL,
        )

        save_assessment_state(
            state,
            run_id,
        )

        raise RuntimeError(
            "Stage 2 verification FAILED: "
            f"{verification['summary']} "
            f"See {stage2_verification_path}."
        )

    kcag_validation = validate_kcag()

    kcag_validation_path = (
        run_context.artifact_path(
            "kcag_validation.json"
        )
    )

    run_context.write_stamped_json(
        kcag_validation_path,
        kcag_validation,
    )

    print(
        "KCAG structural validation: "
        f"{kcag_validation['status']} — "
        f"{kcag_validation['summary']}"
    )

    if not kcag_validation["is_valid"]:
        set_stage_status(
            state,
            "stage2",
            StageStatus.FAIL,
        )

        save_assessment_state(
            state,
            run_id,
        )

        raise RuntimeError(
            "KCAG structural validation FAILED: "
            f"{kcag_validation['summary']}"
        )

    set_stage_status(
        state,
        "stage2",
        StageStatus.PASS,
    )

    save_assessment_state(
        state,
        run_id,
    )

    # ------------------------------------------------------------------
    # Annex B, Annex C, and Stage 3 prose
    # ------------------------------------------------------------------

    t_kcag_review = None

    if not annexB_done:
        stage2_graph = (
            run_context.read_stamped_json(
                stage2_vectors_path
            )
        )

        validation_report = (
            run_context.read_stamped_json(
                kcag_validation_path
            )
        )

        t_kcag_review = build_kcag_review_task(
            out_dir,
            stage2_graph=stage2_graph,
            validation_report=validation_report,
        )

    annexB_prose_path = run_context.artifact_path(
        "annexB_kcag.md"
    )

    annexC_prose_path = run_context.artifact_path(
        "annexC_bbn.md"
    )

    stage3_prose_path = run_context.artifact_path(
        "stage3.md"
    )

    stage3_plan_path = run_context.artifact_path(
        "stage3_test_plan.json"
    )

    if (
        stage3_structured_done
        and not stage3_prose_done
    ):
        state.current_stage = "stage3"

        set_stage_status(
            state,
            "stage3",
            StageStatus.FAIL,
        )

        save_assessment_state(
            state,
            run_id,
        )

        raise RuntimeError(
            "Inconsistent Stage 3 state: "
            "stage3_test_plan.json exists without "
            "stage3.md."
        )

    stage3_compile_only = (
        stage3_prose_done
        and not stage3_structured_done
    )

    if stage3_compile_only:
        if not annexB_done:
            state.current_stage = "stage3"

            set_stage_status(
                state,
                "stage3",
                StageStatus.FAIL,
            )

            save_assessment_state(
                state,
                run_id,
            )

            raise RuntimeError(
                "Stage 3 prose exists but "
                "kcag_report.json is missing."
            )

        print(
            "Stage 3 compile-only resume: stage3.md "
            "exists and stage3_test_plan.json is missing."
        )
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

        print(
            f"analysis_crew will run "
            f"{len(analysis_tasks)} task(s)."
        )

        if analysis_tasks:
            analysis_crew = Crew(
                agents=[
                    modeler,
                    red_team_lead,
                ],
                tasks=analysis_tasks,
                process=Process.sequential,
                verbose=True,
            )

            with heartbeat(
                "analysis_crew",
                log_path=heartbeat_log,
            ):
                analysis_crew.kickoff(
                    inputs={
                        "sut_brief": brief_text,
                        "file_count": corpus_file_count,
                        "corpus_version": corpus_version,
                    }
                )

        finalize_kcag_review_artifact(
            review_was_required=(
                t_kcag_review is not None
            )
        )

        if not os.path.exists(stage3_prose_path):
            state.current_stage = "stage3"

            set_stage_status(
                state,
                "stage3",
                StageStatus.FAIL,
            )

            save_assessment_state(
                state,
                run_id,
            )

            raise RuntimeError(
                f"Stage 3 did not produce "
                f"{stage3_prose_path}."
            )

        for prose_path in (
            annexB_prose_path,
            annexC_prose_path,
            stage3_prose_path,
        ):
            if os.path.exists(prose_path):
                run_context.stamp_prose_file(
                    prose_path
                )

    # ------------------------------------------------------------------
    # Stage 3 structured compilation
    # ------------------------------------------------------------------

    stage2_vectors_for_stage3 = (
        run_context.read_stamped_json(
            stage2_vectors_path
        )
    )

    kcag_report_for_stage3 = (
        run_context.read_stamped_json(
            run_context.artifact_path(
                "kcag_report.json"
            )
        )
    )

    with open(
        "corpus-index/technique_index.json"
    ) as technique_index_file:
        technique_index_for_stage3 = json.load(
            technique_index_file
        )

    stage3_validation_path = (
        run_context.artifact_path(
            "stage3_test_plan_validation.json"
        )
    )

    stage3_already_complete = False

    if os.path.exists(stage3_plan_path):
        try:
            existing_stage3_plan = (
                run_context.read_stamped_json(
                    stage3_plan_path
                )
            )

            stage3_already_complete = (
                stage3_is_semantically_complete(
                    artifact_path=stage3_plan_path,
                    validation_report_path=(
                        stage3_validation_path
                    ),
                    current_candidate_hash=(
                        stage3_candidate_hash(
                            existing_stage3_plan
                        )
                    ),
                )
            )
        except Exception:
            stage3_already_complete = False

    if not stage3_already_complete:
        stage3_prose_for_compile = (
            run_context
            .read_or_migrate_legacy_stamped_prose(
                stage3_prose_path
            )
        )

        stage3_referential_context = (
            build_referential_context(
                stage2_vectors=(
                    stage2_vectors_for_stage3
                ),
                kcag_report=(
                    kcag_report_for_stage3
                ),
            )
        )

        from config.llm import reason_llm
        from src.tools import write_stage3_test_plan

        def _compile_candidate(
            *,
            external_feedback="",
        ):
            compile_stage3_structured_output(
                stage3_prose=(
                    stage3_prose_for_compile
                ),
                referential_context=(
                    stage3_referential_context
                ),
                llm=reason_llm,
                writer_tool=write_stage3_test_plan,
                artifact_path=stage3_plan_path,
                external_feedback=external_feedback,
            )

        def _validate_candidate():
            candidate_plan = (
                run_context.read_stamped_json(
                    stage3_plan_path
                )
            )

            candidate_prose = (
                run_context.read_stamped_prose(
                    stage3_prose_path
                )
            )

            plan_validation = (
                validate_stage3_test_plan(
                    plan=candidate_plan,
                    stage2_vectors=(
                        stage2_vectors_for_stage3
                    ),
                    kcag_report=(
                        kcag_report_for_stage3
                    ),
                    technique_index=(
                        technique_index_for_stage3
                    ),
                )
            )

            consistency = (
                check_stage3_artifact_consistency(
                    stage3_text=candidate_prose,
                    test_plan=candidate_plan,
                )
            )

            report = build_stage3_validation_report(
                plan=candidate_plan,
                plan_validation=plan_validation,
                consistency=consistency,
                artifact_path=stage3_plan_path,
            )

            print(
                "Stage 3 structured test-plan validation: "
                f"{'PASS' if report['is_valid'] else 'FAIL'} — "
                f"{plan_validation['summary']} "
                f"{consistency['summary']}"
            )

            return report

        def _write_validation_report(report):
            run_context.write_stamped_json(
                stage3_validation_path,
                report,
            )

        try:
            compile_stage3_until_valid(
                compile_candidate=(
                    _compile_candidate
                ),
                validate_candidate=(
                    _validate_candidate
                ),
                write_validation_report=(
                    _write_validation_report
                ),
                artifact_path=stage3_plan_path,
                validation_report_path=(
                    stage3_validation_path
                ),
            )
        except RuntimeError as exc:
            state.current_stage = "stage3"

            set_stage_status(
                state,
                "stage3",
                StageStatus.FAIL,
            )

            save_assessment_state(
                state,
                run_id,
            )

            raise RuntimeError(
                f"{exc} Run audit trail: "
                f"{out_dir}/assessment_state.json"
            )

    if not os.path.exists(stage3_plan_path):
        state.current_stage = "stage3"

        set_stage_status(
            state,
            "stage3",
            StageStatus.FAIL,
        )

        save_assessment_state(
            state,
            run_id,
        )

        raise RuntimeError(
            f"Stage 3 did not produce "
            f"{stage3_plan_path}."
        )

    stage3_text = run_context.read_stamped_prose(
        stage3_prose_path
    )

    stage3_plan = run_context.read_stamped_json(
        stage3_plan_path
    )

    stage3_validation_report = (
        run_context.read_stamped_json(
            stage3_validation_path
        )
    )

    state.current_stage = "stage3"

    commit_stage_output(
        state,
        "stage3",
        stage3_prose_path,
        status=StageStatus.PENDING,
    )

    save_assessment_state(
        state,
        run_id,
    )

    stage3_plan_validation = (
        stage3_validation_report.get(
            "plan_validation",
            {},
        )
    )

    stage3_consistency = (
        stage3_validation_report.get(
            "artifact_consistency",
            {},
        )
    )

    enforce_stage3_test_plan_validation(
        state,
        run_id,
        is_valid=(
            stage3_validation_report["is_valid"]
        ),
        summary=(
            f"{stage3_plan_validation.get('summary', '')} "
            f"{stage3_consistency.get('summary', '')}"
        ),
    )

    stage3_safety = check_stage3_safety_gate(
        stage3_text
    )

    stage3_gate_path = run_context.artifact_path(
        "stage3_safety_gate.json"
    )

    run_context.write_stamped_json(
        stage3_gate_path,
        stage3_safety,
    )

    print(
        "Pre-Stage-4 safety gate: "
        f"{'COMPLIANT' if stage3_safety['is_compliant'] else 'NON-COMPLIANT'} "
        f"— {stage3_safety['summary']}"
    )

    enforce_stage3_safety_gate(
        state,
        run_id,
        is_compliant=(
            stage3_safety["is_compliant"]
        ),
        summary=stage3_safety["summary"],
    )

    # ------------------------------------------------------------------
    # Stage 4 prose: generate once, preserve on resume
    # ------------------------------------------------------------------

    stage4_prose_path = run_context.artifact_path(
        "stage4_mission_plan.md"
    )

    stage4_plan_path = run_context.artifact_path(
        "stage4_execution_plan.json"
    )

    stage4_validation_path = (
        run_context.artifact_path(
            "stage4_execution_plan_validation.json"
        )
    )

    stage4_prose_done = (
        os.path.exists(stage4_prose_path)
        and os.path.getsize(stage4_prose_path) > 0
    )

    stage4_plan_exists = os.path.exists(
        stage4_plan_path
    )

    if stage4_plan_exists and not stage4_prose_done:
        set_stage_status(
            state,
            "stage4",
            StageStatus.FAIL,
        )

        state.current_stage = "stage4"

        save_assessment_state(
            state,
            run_id,
        )

        raise RuntimeError(
            "Inconsistent Stage 4 state: "
            "stage4_execution_plan.json exists without "
            "stage4_mission_plan.md. "
            f"Run audit trail: "
            f"{out_dir}/assessment_state.json"
        )

    result = None

    if stage4_prose_done:
        print(
            "Stage 4 compile-only resume: approved "
            "stage4_mission_plan.md already exists — "
            "skipping stage4_crew.kickoff() and preserving "
            "the reviewed prose."
        )

        stage4_prose_for_validation = (
            run_context
            .read_or_migrate_legacy_stamped_prose(
                stage4_prose_path
            )
        )
    else:
        t_stage4 = build_stage4_task(
            out_dir,
            stage3_content=stage3_text,
            stage3_test_plan=stage3_plan,
        )

        stage4_crew = Crew(
            agents=[red_team_lead],
            tasks=[t_stage4],
            process=Process.sequential,
            verbose=True,
        )

        stage4_heartbeat_log = (
            run_context.artifact_path(
                "heartbeat.log"
            )
        )

        with heartbeat(
            "stage4_crew",
            log_path=stage4_heartbeat_log,
        ):
            result = stage4_crew.kickoff(
                inputs={
                    "sut_brief": brief_text,
                    "file_count": corpus_file_count,
                    "corpus_version": corpus_version,
                }
            )

        if not os.path.exists(stage4_prose_path):
            set_stage_status(
                state,
                "stage4",
                StageStatus.FAIL,
            )

            state.current_stage = "stage4"

            save_assessment_state(
                state,
                run_id,
            )

            raise RuntimeError(
                f"Stage 4 did not produce "
                f"{stage4_prose_path}. "
                f"Run audit trail: "
                f"{out_dir}/assessment_state.json"
            )

        with open(
            stage4_prose_path,
            "a",
        ) as stage4_prose_file:
            stage4_prose_file.write(
                "\n\n---\n"
                "*Analysis grounded in Corpus Version "
                f"v{corpus_version} "
                f"({corpus_file_count} files)*"
            )

        run_context.stamp_prose_file(
            stage4_prose_path
        )

        stage4_prose_for_validation = (
            run_context.read_stamped_prose(
                stage4_prose_path
            )
        )

    # ------------------------------------------------------------------
    # Stage 4 structured compilation and semantic repair
    # ------------------------------------------------------------------

    stage4_already_complete = False

    if os.path.exists(stage4_plan_path):
        try:
            existing_stage4_plan = (
                run_context.read_stamped_json(
                    stage4_plan_path
                )
            )

            stage4_already_complete = (
                stage4_is_semantically_complete(
                    artifact_path=stage4_plan_path,
                    validation_report_path=(
                        stage4_validation_path
                    ),
                    current_candidate_hash=(
                        stage4_candidate_hash(
                            existing_stage4_plan
                        )
                    ),
                )
            )
        except Exception:
            stage4_already_complete = False

    if not stage4_already_complete:
        stage4_referential_context = (
            build_referential_context(
                stage2_vectors=(
                    stage2_vectors_for_stage3
                ),
                kcag_report=(
                    kcag_report_for_stage3
                ),
            )
        )

        from config.llm import reason_llm
        from src.tools import write_stage4_execution_plan

        def _compile_candidate4(
            *,
            external_feedback="",
        ):
            compile_stage4_structured_output(
                stage4_prose=(
                    stage4_prose_for_validation
                ),
                referential_context=(
                    stage4_referential_context
                ),
                stage3_test_plan=stage3_plan,
                llm=reason_llm,
                writer_tool=(
                    write_stage4_execution_plan
                ),
                artifact_path=stage4_plan_path,
                external_feedback=external_feedback,
            )

        def _validate_candidate4():
            candidate_plan = (
                run_context.read_stamped_json(
                    stage4_plan_path
                )
            )

            plan_validation = (
                validate_stage4_execution_plan(
                    plan=candidate_plan,
                    stage3_test_plan=stage3_plan,
                )
            )

            consistency = (
                check_stage4_artifact_consistency(
                    stage4_text=(
                        stage4_prose_for_validation
                    ),
                    execution_plan=candidate_plan,
                )
            )

            report = build_stage4_validation_report(
                plan=candidate_plan,
                stage3_test_plan=stage3_plan,
                plan_validation=plan_validation,
                consistency=consistency,
            )

            print(
                "Stage 4 structured execution-plan "
                "validation: "
                f"{'PASS' if report['is_valid'] else 'FAIL'} "
                f"— {plan_validation['summary']} "
                f"{consistency['summary']}"
            )

            return report

        def _write_validation_report4(report):
            run_context.write_stamped_json(
                stage4_validation_path,
                report,
            )

        try:
            compile_stage4_until_valid(
                compile_candidate=(
                    _compile_candidate4
                ),
                validate_candidate=(
                    _validate_candidate4
                ),
                write_validation_report=(
                    _write_validation_report4
                ),
                artifact_path=stage4_plan_path,
                validation_report_path=(
                    stage4_validation_path
                ),
            )
        except RuntimeError as exc:
            set_stage_status(
                state,
                "stage4",
                StageStatus.FAIL,
            )

            state.current_stage = "stage4"

            save_assessment_state(
                state,
                run_id,
            )

            raise RuntimeError(
                f"{exc} Run audit trail: "
                f"{out_dir}/assessment_state.json"
            )

    if not os.path.exists(stage4_plan_path):
        set_stage_status(
            state,
            "stage4",
            StageStatus.FAIL,
        )

        state.current_stage = "stage4"

        save_assessment_state(
            state,
            run_id,
        )

        raise RuntimeError(
            f"Stage 4 did not produce "
            f"{stage4_plan_path}. "
            f"Run audit trail: "
            f"{out_dir}/assessment_state.json"
        )

    if not os.path.exists(stage4_validation_path):
        set_stage_status(
            state,
            "stage4",
            StageStatus.FAIL,
        )

        state.current_stage = "stage4"

        save_assessment_state(
            state,
            run_id,
        )

        raise RuntimeError(
            "Stage 4 validation report is missing: "
            f"{stage4_validation_path}."
        )

    stage4_plan = run_context.read_stamped_json(
        stage4_plan_path
    )

    stage4_validation_report = (
        run_context.read_stamped_json(
            stage4_validation_path
        )
    )

    stage4_plan_validation = (
        stage4_validation_report.get(
            "plan_validation",
            {},
        )
    )

    stage4_consistency = (
        stage4_validation_report.get(
            "artifact_consistency",
            {},
        )
    )

    enforce_stage4_execution_plan_validation(
        state,
        run_id,
        is_valid=(
            stage4_validation_report["is_valid"]
        ),
        summary=(
            f"{stage4_plan_validation.get('summary', '')} "
            f"{stage4_consistency.get('summary', '')}"
        ),
    )

    # ------------------------------------------------------------------
    # Final Stage 4 prose safety check
    # ------------------------------------------------------------------

    stage4_text = stage4_prose_for_validation

    safety = check_phase0_safety_gate(
        stage3_text,
        stage4_text,
    )

    phase0_check_path = (
        run_context.artifact_path(
            "phase0_safety_check.md"
        )
    )

    with open(
        phase0_check_path,
        "w",
    ) as report_file:
        report_file.write(
            "# Phase 0 Safety Gate "
            "Compliance Check\n\n"
        )

        report_file.write(
            "Category 2/3 payload detected: "
            f"{safety['category_2_3_detected']}\n"
        )

        report_file.write(
            f"Matched terms: "
            f"{safety['matched_terms']}\n"
        )

        report_file.write(
            "Phase 0 Safety Gate section present: "
            f"{safety['phase0_gate_present']}\n\n"
        )

        report_file.write(
            "STATUS: "
            f"{'COMPLIANT' if safety['is_compliant'] else 'NON-COMPLIANT'}\n"
        )

        report_file.write(
            safety["summary"]
            + "\n"
        )

    run_context.stamp_prose_file(
        phase0_check_path
    )

    print(
        "Phase 0 Safety Gate check: "
        f"{'COMPLIANT' if safety['is_compliant'] else 'NON-COMPLIANT'} "
        f"— {safety['summary']}"
    )

    finalize_stage4_state(
        state,
        run_id,
        stage4_path=stage4_prose_path,
        is_compliant=safety["is_compliant"],
        safety_summary=safety["summary"],
    )

    print("\n\n=== PIPELINE FINISHED ===")
    print(
        f"Run audit trail: "
        f"{out_dir}/assessment_state.json"
    )

    if result is not None:
        print(result)