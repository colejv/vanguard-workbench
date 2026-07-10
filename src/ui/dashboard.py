import streamlit as st
from pathlib import Path

from src import run_context
from src.state import load_assessment_state, run_output_dir
from src.ui.components.coverage_map import render_coverage_map
from src.ui.components.threat_graph import render_threat_graph
from src.ui.components.sigma_viewer import render_sigma_viewer

st.set_page_config(page_title="Vanguard Command Dashboard", layout="wide")


def _available_runs(base: str = "outputs") -> list:
    """Every run directory that actually has assessment_state.json --
    matches how every other part of Vanguard identifies a real run,
    rather than just listing every subdirectory of outputs/."""
    root = Path(base)
    if not root.exists():
        return []
    return sorted(
        (p.name for p in root.iterdir() if p.is_dir() and (p / "assessment_state.json").exists()),
        reverse=True,
    )


# ---- Run selection (sidebar) -----------------------------------------------
# Purple Team artifacts are run-scoped (outputs/<run_id>/purple_scaffold.json,
# purple_graph.json, sigma_rules/) -- the dashboard has to know which run's
# artifacts to read before any component can load anything. Re-established
# at the top of every script run (Streamlit reruns the whole script on each
# interaction) rather than assumed to persist from a prior run of this script.
runs = _available_runs()

if "selected_run_id" not in st.session_state:
    st.session_state.selected_run_id = runs[0] if runs else None

if not runs:
    st.sidebar.warning("No assessment runs found under outputs/.")
    st.session_state.selected_run_id = None
else:
    st.session_state.selected_run_id = st.sidebar.selectbox(
        "Assessment run", runs,
        index=runs.index(st.session_state.selected_run_id) if st.session_state.selected_run_id in runs else 0,
    )

run_id = st.session_state.selected_run_id
run_active = False
if run_id:
    try:
        state = load_assessment_state(run_id)
        run_context.set_active_run(run_id, state.corpus_manifest_hash, run_output_dir(run_id))
        run_active = True
    except Exception as e:
        st.sidebar.error(f"Could not load run '{run_id}': {e}")

# ---- Navigation controller --------------------------------------------------
if "selected_action_id" not in st.session_state:
    st.session_state.selected_action_id = None

if st.sidebar.button("Reset View (Show All)"):
    st.session_state.selected_action_id = None
    st.rerun()

st.title("Vanguard Command Dashboard")

if not run_active:
    st.info("Select an assessment run with a completed Stage 4 in the sidebar to view Purple Team data.")
else:
    tabs = st.tabs(["Threat Surface", "Coverage Map", "Defensive Validation"])

    with tabs[0]:
        clicked_id = render_threat_graph()
        if clicked_id is not None:
            st.session_state.selected_action_id = clicked_id

    with tabs[1]:
        render_coverage_map(action_id=st.session_state.selected_action_id)

    with tabs[2]:
        render_sigma_viewer(action_id=st.session_state.selected_action_id)