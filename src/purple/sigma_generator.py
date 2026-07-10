"""
Vanguard Sigma Rule Generator.

Reads the run-scoped, stamped purple_scaffold.json produced by
purple_compiler.py and uses a local coding LLM to translate each Stage 4
action's structured telemetry and alert-trigger requirements into a
draft Sigma rule. One rule per action -- not one per phase, matching the
action-level granularity purple_compiler.py already migrated to.

Sigma rules are drafts. A generated rule requires human validation before
operational use -- an LLM-authored detection rule is not itself a
detection engineering review.
"""
import argparse
import json
import os

import requests

from src import run_context
from src.state import load_assessment_state, run_output_dir

OLLAMA_URL = "http://localhost:11434/api/generate"
# Unchanged from the original -- matches the README's existing documented
# limitation that the optional/local-tooling path still uses this model
# while the core reasoning agents use a different one. Not in scope here.
MODEL_NAME = "gemma4:12b-mlx"


def generate_sigma_rule(*, action_summary: str, telemetry: str, alert: str,
                        test_id: str = None, technique_ids: list = None) -> str:
    """Call the local LLM to draft one Sigma rule. telemetry/alert are
    already-joined strings (the scaffold stores these as lists; callers
    join them before calling this function so the prompt reads as
    natural text rather than a Python list repr)."""
    system_prompt = (
        "You are a Blue Team detection engineer. Your job is to translate natural language "
        "telemetry and alert criteria into a valid, strictly formatted YAML Sigma rule. "
        "Do NOT provide explanations, markdown blocks, or offensive code. "
        "Output ONLY the YAML."
    )

    technique_line = f"Technique IDs: {', '.join(technique_ids)}\n" if technique_ids else ""
    test_line = f"Stage 3 Test: {test_id}\n" if test_id else ""

    prompt = (
        f"Create a Sigma rule for the following Stage 4 action.\n"
        f"Action: {action_summary}\n"
        f"{test_line}"
        f"{technique_line}"
        f"Telemetry to monitor: {telemetry}\n"
        f"Alert Trigger: {alert}\n\n"
        f"Ensure it includes title, status, description, logsource, detection, and condition fields."
    )

    try:
        response = requests.post(OLLAMA_URL, json={
            "model": MODEL_NAME,
            "system": system_prompt,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1},
        })
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as e:
        return f"ERROR generating rule: {e}"


def _safe_filename_component(value: str) -> str:
    """action_id/test_id are already guaranteed filename-safe by the
    Stage 4 schema's own ACT-NNN/RT-NNN patterns (letters, digits,
    hyphens only) -- this only strips anything unexpected (e.g. a
    legacy-parsed or hand-edited value) without changing case, so
    structured runs get the natural ACT-001_RT-001.yml form."""
    safe = (value or "unknown").replace(" ", "_").replace("/", "-").replace("&", "and")
    return "".join(c for c in safe if c.isalnum() or c in ("_", "-"))


def generate_rules_for_run(run_id: str, *, base: str = "outputs",
                           rule_generator=generate_sigma_rule) -> dict:
    """Read the run-scoped stamped purple_scaffold.json and generate one
    Sigma rule per action that has at least one telemetry requirement or
    alert trigger. rule_generator is injectable so tests never perform
    live network/LLM calls -- pass a stub that returns fixed YAML text.

    Returns the stamped manifest dict (not yet written to disk by this
    function's caller in isolation -- see main(), which writes it).
    """
    state = load_assessment_state(run_id, base=base)
    out_dir = run_output_dir(run_id, base=base)
    run_context.set_active_run(run_id, state.corpus_manifest_hash, out_dir)

    scaffold_path = run_context.artifact_path("purple_scaffold.json")
    if not os.path.exists(scaffold_path):
        raise RuntimeError(
            f"{scaffold_path} not found. Run purple_compiler.py for this run first."
        )
    scaffold = run_context.read_stamped_json(scaffold_path)
    actions = scaffold.get("actions", [])

    rules_dir = run_context.artifact_path("sigma_rules")
    os.makedirs(rules_dir, exist_ok=True)

    manifest_rules = []
    print(f"Loaded {len(actions)} action(s). Generating Sigma rules via {MODEL_NAME}...")

    for action in actions:
        action_id = action.get("action_id", "UNKNOWN")
        test_id = action.get("test_id")
        telemetry_list = action.get("telemetry_requirements") or []
        alert_list = action.get("alert_triggers") or []

        if not telemetry_list and not alert_list:
            print(f"Skipping {action_id}: no detection criteria found.")
            continue

        telemetry = "; ".join(telemetry_list)
        alert = "; ".join(alert_list)

        print(f"Generating rule for {action_id} ({test_id or 'no test_id'})...")
        sigma_yaml = rule_generator(
            action_summary=action.get("action_summary", ""), telemetry=telemetry, alert=alert,
            test_id=test_id, technique_ids=action.get("technique_ids") or [],
        )
        sigma_yaml = sigma_yaml.replace("```yaml", "").replace("```", "").strip()

        filename = f"{_safe_filename_component(action_id)}_{_safe_filename_component(test_id or 'unbound')}.yml"
        rule_path = os.path.join(rules_dir, filename)
        with open(rule_path, "w") as f:
            f.write(sigma_yaml)
        print(f" -> Saved to {rule_path}")

        status = "GENERATED" if not sigma_yaml.startswith("ERROR generating rule") else "GENERATION_FAILED"
        manifest_rules.append({
            "action_id": action_id, "test_id": test_id,
            "path": f"sigma_rules/{filename}", "status": status,
        })

    manifest = {
        "schema_version": 1,
        "model": MODEL_NAME,
        "source_scaffold": "purple_scaffold.json",
        "rules": manifest_rules,
    }
    run_context.write_stamped_json(run_context.artifact_path("sigma_rules_manifest.json"), manifest, schema_version="1")
    return manifest


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate draft Sigma detection rules from a run's Purple Team scaffold."
    )
    parser.add_argument("--run-id", required=True, help="Vanguard assessment run ID with a compiled Purple scaffold.")
    return parser


def main(argv=None) -> None:
    parser = build_arg_parser()
    args = parser.parse_args(argv)
    manifest = generate_rules_for_run(args.run_id)
    generated = sum(1 for r in manifest["rules"] if r["status"] == "GENERATED")
    print(f"\nGenerated {generated}/{len(manifest['rules'])} Sigma rule(s).")
    print(f"Manifest written to {run_context.artifact_path('sigma_rules_manifest.json')}")
    print("\nSigma rules are drafts and require human validation before operational use.")


if __name__ == "__main__":
    main()