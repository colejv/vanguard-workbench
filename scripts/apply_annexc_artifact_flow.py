"""Move Annex B before Annex C and use artifact-based derivation."""

from __future__ import annotations

import re
import shutil
from pathlib import Path


crew_path = Path("src/crew.py")
backup_path = Path(
    "src/crew.py.before_annexc_artifact_flow"
)

text = crew_path.read_text(
    encoding="utf-8"
)

if not backup_path.exists():
    shutil.copy2(
        crew_path,
        backup_path,
    )

if (
    "from src.annexc_artifact_gate import"
    not in text
):
    import_pattern = re.compile(
        r"from src\.annexc_derivation import\s*"
        r"\(\s*run_annexc_derivation_gate\s*,\s*"
        r"DerivationApprovalBlocked\s*\)"
    )

    text, count = import_pattern.subn(
        "from src.annexc_artifact_gate import (\n"
        "    run_annexc_derivation_gate,\n"
        "    DerivationApprovalBlocked,\n"
        ")",
        text,
        count=1,
    )

    if count != 1:
        raise RuntimeError(
            "Could not replace the Annex C gate import "
            "in src/crew.py."
        )

start_marker = (
    "    else:\n"
    "        # ---- ANNEX C DERIVATION + APPROVAL GATE"
)
end_marker = (
    "    # ---- ANNEX C -> STAGE 3 TRANSITION GATE"
)

if start_marker in text:
    start = text.index(start_marker)
    end = text.index(
        end_marker,
        start,
    )

    replacement = '''    else:
        # ---- ANNEX B FIRST -------------------------------------------------
        # Annex C now consumes completed Stage 0/1/2 and Annex B artifacts.
        # Run Annex B in its own crew before the Annex C derivation gate.

        stage2_prose_path = run_context.artifact_path(
            "stage2.md"
        )

        if not os.path.exists(stage2_prose_path):
            raise RuntimeError(
                "Stage 2 prose is missing before Annex B: "
                f"{stage2_prose_path}"
            )

        run_context.stamp_prose_file(
            stage2_prose_path
        )
        stage2_content_for_downstream = (
            run_context.read_stamped_prose(
                stage2_prose_path
            )
        )

        # Rebuild Annex B with injected Stage 2 content. A task in a separate
        # CrewAI kickoff cannot rely on a live context reference to a task
        # that ran in a different crew.
        resume_context["t_annexB"] = (
            stage2_content_for_downstream
        )
        resume_context["t_stage3_stage2"] = (
            stage2_content_for_downstream
        )

        annexb_task_set = build_tasks(
            out_dir,
            resume_context=resume_context,
        )
        t_annexB = annexb_task_set[
            "t_annexB"
        ]

        if not annexB_done:
            if t_kcag_review is None:
                raise RuntimeError(
                    "Annex B is incomplete but its KCAG "
                    "review task was not constructed."
                )

            annexb_tasks = [
                t_kcag_review,
                t_annexB,
            ]

            print(
                "annexb_crew will run "
                f"{len(annexb_tasks)} task(s): "
                f"{[t.output_file.split('/')[-1] if t.output_file else t.agent.role for t in annexb_tasks]}"
            )

            annexb_crew = Crew(
                agents=[modeler],
                tasks=annexb_tasks,
                process=Process.sequential,
                verbose=True,
            )

            annexb_heartbeat_log = (
                run_context.artifact_path(
                    "heartbeat.log"
                )
            )

            with heartbeat(
                "annexb_crew",
                log_path=(
                    annexb_heartbeat_log
                ),
            ):
                annexb_crew.kickoff(
                    inputs={
                        "sut_brief": brief_text,
                        "file_count": c_count,
                        "corpus_version": (
                            c_version
                        ),
                    }
                )

            finalize_kcag_review_artifact(
                review_was_required=True
            )

            kcag_report_path = (
                run_context.artifact_path(
                    "kcag_report.json"
                )
            )

            if not os.path.exists(
                kcag_report_path
            ):
                raise RuntimeError(
                    "Annex B did not produce "
                    f"{kcag_report_path}."
                )

            annexB_done = True

        # Whether Annex B ran above or was already complete on resume, load
        # its stamped prose and inject it into fresh Annex C / Stage 3 tasks.
        annexB_prose_path = (
            run_context.artifact_path(
                "annexB_kcag.md"
            )
        )

        if not os.path.exists(
            annexB_prose_path
        ):
            raise RuntimeError(
                "Annex B report prose is missing: "
                f"{annexB_prose_path}"
            )

        run_context.stamp_prose_file(
            annexB_prose_path
        )
        annexB_content_for_downstream = (
            run_context.read_stamped_prose(
                annexB_prose_path
            )
        )

        resume_context["t_annexC"] = (
            annexB_content_for_downstream
        )
        resume_context["t_stage3_annexb"] = (
            annexB_content_for_downstream
        )

        downstream_task_set = build_tasks(
            out_dir,
            resume_context=resume_context,
        )
        t_annexC = downstream_task_set[
            "t_annexC"
        ]
        t_stage3 = downstream_task_set[
            "t_stage3"
        ]

        # ---- ARTIFACT-BASED ANNEX C DERIVATION + APPROVAL GATE ------------
        # This performs one structured model call over Stage 0/1/2 and Annex B
        # artifacts. It does not rescan the frozen source corpus.
        run_annexc_derivation_gate(
            state=state,
            run_id=run_id,
            out_dir=out_dir,
            corpus_manifest_hash=(
                corpus_manifest_hash
            ),
            run_context=run_context,
            set_stage_status=(
                set_stage_status
            ),
            save_assessment_state=(
                save_assessment_state
            ),
            StageStatus=StageStatus,
        )

        # Annex B is already complete. The remaining analysis crew contains
        # only Annex C scoring and Stage 3 prose as required.
        analysis_tasks = (
            build_analysis_tasks(
                t_kcag_review=None,
                t_annexB=t_annexB,
                t_annexC=t_annexC,
                t_stage3=t_stage3,
                annexB_done=True,
                annexC_done=annexC_done,
                stage3_prose_done=(
                    stage3_prose_done
                ),
            )
        )

        print(
            "analysis_crew will run "
            f"{len(analysis_tasks)} task(s): "
            f"{[t.output_file.split('/')[-1] if t.output_file else t.agent.role for t in analysis_tasks]}"
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

            analysis_heartbeat_log = (
                run_context.artifact_path(
                    "heartbeat.log"
                )
            )

            with heartbeat(
                "analysis_crew",
                log_path=(
                    analysis_heartbeat_log
                ),
            ):
                analysis_crew.kickoff(
                    inputs={
                        "sut_brief": brief_text,
                        "file_count": c_count,
                        "corpus_version": (
                            c_version
                        ),
                    }
                )

        if not os.path.exists(
            stage3_prose_path
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
                "Stage 3 did not produce "
                f"{stage3_prose_path} — Stage 4 "
                "cannot be constructed. Run audit "
                "trail: "
                f"{out_dir}/assessment_state.json"
            )

        for path in (
            annexC_prose_path,
            stage3_prose_path,
        ):
            if os.path.exists(path):
                run_context.stamp_prose_file(
                    path
                )

'''

    text = (
        text[:start]
        + replacement
        + text[end:]
    )

elif (
    "ARTIFACT-BASED ANNEX C DERIVATION"
    not in text
):
    raise RuntimeError(
        "Could not find the existing Annex C "
        "derivation block in src/crew.py."
    )

crew_path.write_text(
    text,
    encoding="utf-8",
)

print(
    "Updated src/crew.py"
)
print(
    f"Backup: {backup_path}"
)
