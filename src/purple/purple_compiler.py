"""
Vanguard Purple Team Compiler.

Default path: compiles Purple Team defensive artifacts directly from the
verified, run-scoped structured Stage 4 execution plan
(stage4_execution_plan.json) -- which has already passed deterministic
referential validation against Stage 3 (stage4_execution_plan_validation.json)
before this tool will touch it. No prose parsing occurs in this path.

Legacy path (--legacy-markdown, explicit only): the original
formatting-sensitive Markdown regex parser (parse_legacy_mdmp_plan),
preserved unchanged for compatibility with runs that predate structured
Stage 4. It is never triggered automatically -- a missing or invalid
structured plan is an error, not a silent fallback trigger. That
automatic-fallback behavior would defeat the entire point of the new
trust boundary.

    Purple Team output must derive from the exact structured Stage 4
    plan that passed deterministic validation for the selected run --
    not from a copied, regex-parsed prose file.
"""
import argparse
import json
import os
import re
import urllib.request
import warnings
from dataclasses import dataclass, asdict, field
from typing import Optional

import yaml

from src import run_context
from src.schemas import StageStatus
from src.stage4_schema import Stage4ExecutionPlan
from src.state import load_assessment_state, run_output_dir, canonical_json_sha256

ART_INDEX_URL = "https://raw.githubusercontent.com/redcanaryco/atomic-red-team/master/atomics/Indexes/index.yaml"
CACHE_DIR = "corpus-index"
CACHE_FILE = os.path.join(CACHE_DIR, "art_index.json")

ATTACK_TECHNIQUE_PATTERN = re.compile(r"^T\d{4}(?:\.\d{3})?$", re.IGNORECASE)


# ============================================================================
#  Atomic Red Team index -- plain function, not a side effect of
#  constructing anything. The original PurplePlanCompiler.__init__ fetched
#  this unconditionally (real network I/O on every `PurplePlanCompiler(...)`
#  call, including in tests); this is the fix for that specific problem.
# ============================================================================

def load_art_index(*, refresh: bool = False) -> dict:
    """Load the cached Atomic Red Team index, fetching and flattening it
    if the cache is absent or refresh=True. Same fetch/flatten logic as
    the original implementation, unchanged, just no longer implicit in
    an object constructor."""
    if os.path.exists(CACHE_FILE) and not refresh:
        with open(CACHE_FILE) as f:
            return json.load(f)

    print("Fetching live Atomic Red Team index...")
    try:
        with urllib.request.urlopen(ART_INDEX_URL, timeout=30) as r:
            raw = yaml.safe_load(r.read())
    except Exception as e:
        print(f"ERROR fetching ART index: {e}")
        return {}

    flat = {}
    for tactic, techniques in raw.items():
        if not isinstance(techniques, dict):
            continue
        for tid, entry in techniques.items():
            tests = entry.get("atomic_tests", []) or []
            flat[tid.upper()] = {
                "technique_name": entry.get("technique", {}).get("name", ""),
                "tactic": tactic,
                "test_count": len(tests),
                "test_names": [t.get("name", "") for t in tests],
            }

    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(CACHE_FILE, "w") as f:
        json.dump(flat, f, indent=2)
    return flat


# ============================================================================
#  Run trust boundary
# ============================================================================

@dataclass(frozen=True)
class PurpleRunContext:
    run_id: str
    out_dir: str
    state: object
    execution_plan: dict
    validation_report: dict


def load_structured_stage4_run(run_id: str, *, base: str = "outputs") -> PurpleRunContext:
    """Establish the run trust boundary before any compilation happens.

    Requires: Stage 4 state == PASS, AND the structured validation
    report == PASS, AND the structured artifact's run/corpus stamp
    matches the active run (enforced automatically by
    run_context.read_stamped_json), AND the current
    stage4_execution_plan.json and stage3_test_plan.json hash exactly to
    the values the validation report recorded when it ran.

    This protects against: running Purple compilation before the
    assessment finishes; compiling a rejected Stage 4 plan; manually
    copying an artifact from another run; using an artifact from a
    different corpus; and -- the hash checks specifically -- a same-run
    swap where a validated Plan A is replaced by a merely schema-valid
    Plan B that was never actually checked against Stage 3.
    """
    try:
        state = load_assessment_state(run_id, base=base)
    except FileNotFoundError:
        raise RuntimeError(f"No assessment_state.json found for run '{run_id}' under {base}/.")

    stage4_record = state.stages.get("stage4")
    if stage4_record is None:
        raise RuntimeError(f"Run '{run_id}' has no Stage 4 state record.")
    if stage4_record.status != StageStatus.PASS:
        raise RuntimeError(
            f"Run '{run_id}' Stage 4 status is {stage4_record.status.value}; PASS is "
            f"required before Purple Team compilation."
        )

    out_dir = run_output_dir(run_id, base)
    run_context.set_active_run(run_id, state.corpus_manifest_hash, out_dir)

    plan_path = run_context.artifact_path("stage4_execution_plan.json")
    validation_path = run_context.artifact_path("stage4_execution_plan_validation.json")

    try:
        plan = run_context.read_stamped_json(plan_path)
    except FileNotFoundError:
        raise RuntimeError(
            f"{plan_path} not found. Structured Stage 4 JSON is required and this tool "
            f"never silently falls back to Markdown parsing — pass --legacy-markdown "
            f"explicitly if this run predates structured Stage 4."
        )
    try:
        validation = run_context.read_stamped_json(validation_path)
    except FileNotFoundError:
        raise RuntimeError(f"{validation_path} not found. Cannot confirm Stage 4 passed validation.")

    if not validation.get("is_valid"):
        raise RuntimeError(
            f"Run '{run_id}' stage4_execution_plan_validation.json does not report "
            f"is_valid=True. Purple Team compilation refuses a rejected Stage 4 plan."
        )

    # ---- Bind this exact plan to the exact plan the report validated ----
    # Without this, a same-run swap is possible: Plan A passes full Stage
    # 3 referential validation and gets a passing report written; Plan A
    # is then replaced by a DIFFERENT, merely schema-valid Plan B; Plan B
    # still satisfies Stage4ExecutionPlan's Pydantic shape, still carries
    # the same run/corpus stamp, and the (stale) report still says
    # is_valid=True -- none of the checks above would catch that Plan B's
    # Stage 3 bindings, inherited criteria, or safety controls were never
    # actually checked against anything. A hash mismatch here is not a
    # corruption warning; it means the plan on disk is not the plan that
    # was validated, and compiling it would defeat the entire point of
    # the structured Stage 4 trust boundary.
    source_identity = validation.get("source_identity") or {}
    expected_plan_hash = source_identity.get("stage4_execution_plan_sha256")
    if not expected_plan_hash:
        raise RuntimeError(
            f"Run '{run_id}' stage4_execution_plan_validation.json does not identify "
            f"the execution plan it validated (missing source_identity.stage4_execution_"
            f"plan_sha256). Refusing to trust an unbound validation report."
        )
    actual_plan_hash = canonical_json_sha256(plan)
    if actual_plan_hash != expected_plan_hash:
        raise RuntimeError(
            f"Run '{run_id}' stage4_execution_plan.json has changed since deterministic "
            f"Stage 4 validation ran (hash mismatch). Refusing to compile an execution "
            f"plan that does not match its own validation report."
        )

    stage3_plan_path = run_context.artifact_path("stage3_test_plan.json")
    try:
        stage3_plan = run_context.read_stamped_json(stage3_plan_path)
    except FileNotFoundError:
        raise RuntimeError(
            f"{stage3_plan_path} not found. A run that reached Stage 4 PASS must have "
            f"a Stage 3 test plan -- refusing to compile without it."
        )
    expected_stage3_hash = source_identity.get("stage3_test_plan_sha256")
    if not expected_stage3_hash:
        raise RuntimeError(
            f"Run '{run_id}' stage4_execution_plan_validation.json does not identify "
            f"the Stage 3 test plan it validated against (missing source_identity."
            f"stage3_test_plan_sha256). Refusing to trust an unbound validation report."
        )
    if canonical_json_sha256(stage3_plan) != expected_stage3_hash:
        raise RuntimeError(
            f"Run '{run_id}' stage3_test_plan.json has changed since deterministic "
            f"Stage 4 validation ran (hash mismatch). Refusing to compile against a "
            f"Stage 3 test plan that does not match what Stage 4 was actually validated "
            f"against."
        )

    # Defense in depth against schema drift -- re-validate against the
    # CURRENT schema, don't just trust the stamp and the hash match.
    Stage4ExecutionPlan.model_validate(plan)

    return PurpleRunContext(run_id=run_id, out_dir=out_dir, state=state,
                            execution_plan=plan, validation_report=validation)


# ============================================================================
#  Structured compilation -- default path, no prose parsing
# ============================================================================

@dataclass
class PurpleActionRecord:
    """One record per Stage 4 action (not one per phase, as the legacy
    EngagementPhase did) -- structured Stage 4 supports multiple actions
    per phase, and collapsing that back down to one record per phase
    would lose the provenance chain from Stage 2 vector, through the
    Stage 3 test concept, through the Stage 4 binding, to this specific
    action."""
    phase_id: str
    phase_sequence: int
    phase_name: str
    phase_purpose: str
    action_id: str
    action_summary: str

    categories: list = field(default_factory=list)
    stage2_vector_ids: list = field(default_factory=list)
    kcag_path: list = field(default_factory=list)
    technique_ids: list = field(default_factory=list)

    responsible_roles: list = field(default_factory=list)
    preconditions: list = field(default_factory=list)
    success_criteria: list = field(default_factory=list)
    abort_criteria: list = field(default_factory=list)
    rollback_or_recovery_steps: list = field(default_factory=list)

    telemetry_requirements: list = field(default_factory=list)
    alert_triggers: list = field(default_factory=list)
    opsec_measures: list = field(default_factory=list)

    atomic_test_references: list = field(default_factory=list)
    test_id: Optional[str] = None
    provenance_status: str = "STRUCTURED"


def compile_structured_plan(plan: dict) -> list:
    """Build one PurpleActionRecord per Stage 4 action, directly from the
    verified structured plan -- no Markdown, no regex.

    The structured Stage 4 validator (src/stage4_validation.py) has
    already proven, for any plan that reached PASS, that every action's
    test_id has a real binding, and that binding's categories, Stage 2
    vector IDs, KCAG path, and technique IDs agree exactly with Stage 3.
    This function consumes that already-proven result rather than
    reimplementing Stage 4 validation -- the RuntimeError below is
    defense in depth for a plan that somehow reached this function
    without actually passing that gate (e.g. a hand-edited file), not
    the primary enforcement mechanism.
    """
    bindings = {b["test_id"]: b for b in plan["test_bindings"]}
    records = []
    phases = sorted(plan["phases"], key=lambda p: p["sequence"])
    for phase in phases:
        for action in phase["actions"]:
            test_id = action["test_id"]
            binding = bindings.get(test_id)
            if binding is None:
                raise RuntimeError(
                    f"Action {action['action_id']} references unbound test "
                    f"'{test_id}'. This should be impossible for a plan that "
                    f"passed validate_stage4_execution_plan() -- refusing to "
                    f"compile rather than guess."
                )
            records.append(PurpleActionRecord(
                phase_id=phase["phase_id"], phase_sequence=phase["sequence"],
                phase_name=phase["name"], phase_purpose=phase["purpose"],
                action_id=action["action_id"], action_summary=action["action_summary"],
                categories=list(binding["categories"]),
                stage2_vector_ids=list(binding["stage2_vector_ids"]),
                kcag_path=list(binding["kcag_path"]),
                technique_ids=list(binding["technique_ids"]),
                responsible_roles=list(action["responsible_roles"]),
                preconditions=list(action["preconditions"]),
                success_criteria=list(action["success_criteria"]),
                abort_criteria=list(action["abort_criteria"]),
                rollback_or_recovery_steps=list(action["rollback_or_recovery_steps"]),
                telemetry_requirements=list(action["telemetry_requirements"]),
                alert_triggers=list(action["alert_triggers"]),
                opsec_measures=list(action["opsec_measures"]),
                test_id=test_id,
                provenance_status="STRUCTURED",
            ))
    return records


# ============================================================================
#  Atomic Red Team crosswalk
# ============================================================================

def crosswalk_techniques(records: list, art_index: dict) -> list:
    """Annotate each record's technique_ids against the Atomic Red Team
    index. Does not modify the source plan -- only the derived
    PurpleActionRecord objects passed in.

    VETTED_REFERENCE_AVAILABLE means a published Atomic Red Team test
    exists for this technique ID. It does NOT mean the test is approved,
    safe, applicable, or ready for this specific environment -- the
    Purple operator still decides that. (Deliberately not named just
    "VETTED", which the original implementation used and which
    overstates what this check actually establishes.)
    """
    for record in records:
        references = []
        for technique_id in record.technique_ids:
            normalized = technique_id.upper()

            if not ATTACK_TECHNIQUE_PATTERN.fullmatch(normalized):
                references.append({
                    "id": technique_id, "status": "COVERAGE_GAP", "framework": "NON_ATTACK",
                    "reason": "Atomic Red Team crosswalk applies only to ATT&CK technique IDs.",
                    "test_count": 0, "test_names": [],
                })
                continue

            entry = art_index.get(normalized)
            if entry is None:
                references.append({
                    "id": technique_id, "status": "COVERAGE_GAP", "framework": "Atomic Red Team",
                    "reason": "No published Atomic Red Team entry was found.",
                    "test_count": 0, "test_names": [],
                })
                continue

            references.append({
                "id": technique_id, "status": "VETTED_REFERENCE_AVAILABLE", "framework": "Atomic Red Team",
                "technique_name": entry.get("technique_name", ""),
                "test_count": entry.get("test_count", 0),
                "test_names": entry.get("test_names", []),
            })
        record.atomic_test_references = references
    return records


def build_coverage_summary(records: list) -> dict:
    total = vetted = gap = 0
    for record in records:
        for ref in record.atomic_test_references:
            total += 1
            if ref["status"] == "VETTED_REFERENCE_AVAILABLE":
                vetted += 1
            else:
                gap += 1
    return {"total_technique_references": total, "vetted_reference_available": vetted, "coverage_gap": gap}


# ============================================================================
#  Purple graph -- action-level nodes, replaces the old phase-level
#  export_graph_data()/kcag_data.json (misleadingly named -- it was never
#  the KCAG).
# ============================================================================

def build_purple_graph(records: list) -> dict:
    nodes = []
    for record in records:
        has_gap = any(ref["status"] == "COVERAGE_GAP" for ref in record.atomic_test_references)
        nodes.append({
            "id": record.action_id,
            "label": f"{record.action_id} — {record.test_id}" if record.test_id else record.action_id,
            "phase_id": record.phase_id,
            "test_id": record.test_id,
            "coverage_status": "COVERAGE_GAP" if has_gap else "FULLY_CROSSWALKED",
            "color": "#FF4B4B" if has_gap else "#00A86B",
        })

    edges = []
    for i in range(len(records) - 1):
        source, target = records[i], records[i + 1]
        transition_type = "WITHIN_PHASE" if source.phase_id == target.phase_id else "PHASE_TRANSITION"
        edges.append({"source": source.action_id, "target": target.action_id, "transition_type": transition_type})

    return {"nodes": nodes, "edges": edges}


# ============================================================================
#  Legacy Markdown parser -- ISOLATED, UNCHANGED regex logic, preserved for
#  compatibility with runs that predate structured Stage 4. Only reachable
#  via --legacy-markdown; never an automatic fallback.
# ============================================================================

def parse_legacy_mdmp_plan(plan_path: str) -> list:
    """DEPRECATED. The original formatting-sensitive Markdown regex
    parser (previously PurplePlanCompiler.parse_mdmp_plan), preserved
    unchanged for compatibility with runs that predate structured
    Stage 4. Structured provenance (test_id, categories, Stage 2 vector
    IDs, KCAG path) is unavailable for a legacy-parsed run -- those
    fields are left as explicit empty lists / None with
    provenance_status='LEGACY_PARTIAL', never invented values.
    """
    warnings.warn(
        "Legacy Markdown parsing is deprecated and format-sensitive. "
        "Structured Stage 4 JSON is preferred.",
        DeprecationWarning, stacklevel=2,
    )
    try:
        with open(plan_path) as f:
            content = f.read()
    except FileNotFoundError:
        print(f"ERROR: Could not find {plan_path}")
        return []

    records = []
    # Unchanged from the original parse_mdmp_plan().
    phase_blocks = re.split(r'###\s+\*\*Phase\s+\d+:', content)[1:]

    for i, block in enumerate(phase_blocks, 1):
        phase_name_raw = block.split('\n')[0]
        phase_name = phase_name_raw.replace('**', '').strip()

        action_match = re.search(r'\*\s+\*\*Action:\*\*\s+(.*?)\n\*', block, re.DOTALL)
        action_summary = action_match.group(1).strip() if action_match else "Unknown"

        mitre_section = re.search(
            r'\*\s+\*\*MITRE ATT&CK Mapping:\*\*(.*?)(?=\n\*\s+\*\*Execution Timeline)', block, re.DOTALL)
        technique_ids = []
        if mitre_section:
            technique_ids = re.findall(r'(T\d{4}(?:\.\d{3})?|CAPEC-\d+)', mitre_section.group(1))

        telemetry_match = re.search(r'\*\s+\*\*Telemetry:\*\*\s+(.*?)\n', block)
        alert_match = re.search(r'\*\s+\*\*Alert Trigger:\*\*\s+(.*?)(?=\n|$)', block)
        telemetry = telemetry_match.group(1).strip() if telemetry_match else ""
        alert = alert_match.group(1).strip() if alert_match else ""

        records.append(PurpleActionRecord(
            phase_id=f"PHASE-{i:02d}", phase_sequence=i, phase_name=phase_name, phase_purpose="",
            action_id=f"ACT-{i:03d}", action_summary=action_summary,
            technique_ids=technique_ids,
            telemetry_requirements=[telemetry] if telemetry else [],
            alert_triggers=[alert] if alert else [],
            test_id=None,
            provenance_status="LEGACY_PARTIAL",
        ))
    return records


# ============================================================================
#  Artifact writing
# ============================================================================

def write_purple_artifacts(context: Optional[PurpleRunContext], records: list, art_index: dict,
                           *, legacy: bool = False, legacy_path: Optional[str] = None) -> tuple:
    records = crosswalk_techniques(records, art_index)
    coverage_summary = build_coverage_summary(records)
    graph = build_purple_graph(records)

    if legacy:
        source = {
            "format": "legacy_markdown",
            "artifact": legacy_path,
            "warning": "Generated through deprecated formatting-sensitive compatibility mode.",
        }
        safety = {"execution_authorization": None, "phase0_execution_release": None}
    else:
        source = {
            "format": "stage4_execution_plan",
            "artifact": "stage4_execution_plan.json",
            "validation_artifact": "stage4_execution_plan_validation.json",
            "run_id": context.run_id,
        }
        safety = {
            "execution_authorization": context.execution_plan["execution_authorization"],
            "phase0_execution_release": context.execution_plan["phase0_safety_gate"]["execution_release"],
        }

    scaffold = {
        "schema_version": 2,
        "source": source,
        "safety": safety,
        "coverage_summary": coverage_summary,
        "actions": [asdict(r) for r in records],
    }

    run_context.write_stamped_json(run_context.artifact_path("purple_scaffold.json"), scaffold, schema_version="2")
    run_context.write_stamped_json(run_context.artifact_path("purple_graph.json"), graph, schema_version="1")

    return scaffold, graph


def print_coverage_map(records: list) -> None:
    print("\n" + "=" * 60)
    print("PURPLE TEAM COVERAGE MAP: SUT ENGAGEMENT")
    print("=" * 60)
    for record in records:
        print(f"\n[{record.phase_id}] {record.phase_name}")
        print(f"[{record.action_id}] {record.action_summary}" +
              (f" (test {record.test_id})" if record.test_id else ""))
        print("-" * 40)
        for ref in record.atomic_test_references:
            if ref["status"] == "VETTED_REFERENCE_AVAILABLE":
                print(f"  [\u2713] {ref['id']}: {ref['test_count']} published test(s) — {ref['technique_name']}")
            else:
                print(f"  [!] {ref['id']}: {ref['status']} — {ref.get('reason', '')}")


# ============================================================================
#  CLI
# ============================================================================

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Compile a completed Vanguard Stage 4 plan into run-scoped Purple Team defensive artifacts."
    )
    parser.add_argument("--run-id", required=True, help="Completed Vanguard assessment run ID.")
    parser.add_argument(
        "--legacy-markdown", default=None,
        help=("Explicit compatibility mode for an older run that lacks stage4_execution_plan.json. "
             "No automatic fallback occurs."),
    )
    parser.add_argument("--refresh-art-index", action="store_true", help="Refresh the cached Atomic Red Team index.")
    return parser


def main(argv=None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    art_index = load_art_index(refresh=args.refresh_art_index)
    print(f"Loaded {len(art_index)} technique(s) from the Atomic Red Team index.")

    if args.legacy_markdown:
        out_dir = run_output_dir(args.run_id)
        try:
            state = load_assessment_state(args.run_id)
        except FileNotFoundError:
            raise RuntimeError(
                f"No assessment_state.json found for run '{args.run_id}'. "
                f"--legacy-markdown compensates for a missing stage4_execution_plan.json, "
                f"not for a run ID that doesn't belong to a real Vanguard assessment."
            )
        run_context.set_active_run(args.run_id, state.corpus_manifest_hash, out_dir)

        print(f"Parsing legacy Markdown plan: {args.legacy_markdown}")
        records = parse_legacy_mdmp_plan(args.legacy_markdown)
        scaffold, graph = write_purple_artifacts(None, records, art_index,
                                                 legacy=True, legacy_path=args.legacy_markdown)
    else:
        print(f"Loading structured Stage 4 plan for run: {args.run_id}")
        context = load_structured_stage4_run(args.run_id)
        records = compile_structured_plan(context.execution_plan)
        scaffold, graph = write_purple_artifacts(context, records, art_index, legacy=False)

    print_coverage_map(records)
    print(f"\nCompiled {len(records)} Purple Team action record(s).")
    print(f"Coverage summary: {scaffold['coverage_summary']}")
    print(f"Scaffold written to {run_context.artifact_path('purple_scaffold.json')}")
    print(f"Graph written to {run_context.artifact_path('purple_graph.json')}")


if __name__ == "__main__":
    main()