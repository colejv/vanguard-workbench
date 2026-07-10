import streamlit as st
import pandas as pd

from src import run_context


def _color_for_status(val: str) -> str:
    # VETTED_REFERENCE_AVAILABLE means a published Atomic Red Team test
    # exists for this technique ID -- not that it is approved, safe,
    # applicable, or ready for this environment.
    return "color: green" if val == "VETTED_REFERENCE_AVAILABLE" else "color: red"


def render_coverage_map(action_id=None):
    """Render the Atomic Red Team coverage table for the active run's
    Purple Team scaffold. Filters to one action when action_id is given
    (e.g. from a threat-graph click), otherwise shows every action.

    Reads the current scaffold shape: a versioned object with an
    'actions' list (one record per Stage 4 action), not the legacy bare
    list of phase-level records with a 'test_references' key.
    """
    try:
        scaffold = run_context.read_stamped_json(run_context.artifact_path("purple_scaffold.json"))
    except FileNotFoundError:
        st.error("purple_scaffold.json not found for this run. Run the Purple Team compiler first.")
        return
    except Exception as e:
        st.error(f"Could not read purple_scaffold.json: {e}")
        return

    actions = scaffold.get("actions", [])
    if action_id is not None:
        actions = [a for a in actions if a.get("action_id") == action_id]

    rows = []
    for action in actions:
        for ref in action.get("atomic_test_references", []):
            rows.append({
                "Phase": action.get("phase_name", ""),
                "Action": action.get("action_id", ""),
                "Technique": ref["id"],
                "Status": ref["status"],
                "Framework": ref["framework"],
                "Test Count": ref.get("test_count", 0),
            })

    if not rows:
        st.info("No technique references to display for the current selection.")
        return

    df = pd.DataFrame(rows)
    st.dataframe(
        df.style.map(_color_for_status, subset=["Status"]),
        width="stretch",
    )