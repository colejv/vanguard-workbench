import streamlit as st
from src.ui.components.coverage_map import render_coverage_map
from src.ui.components.threat_graph import render_threat_graph
from src.ui.components.sigma_viewer import render_sigma_viewer

st.set_page_config(page_title="Vanguard Command Dashboard", layout="wide")

# Navigation Controller
if 'selected_phase_idx' not in st.session_state:
    st.session_state.selected_phase_idx = None

# Sidebar Reset
if st.sidebar.button("Reset View (Show All)"):
    st.session_state.selected_phase_idx = None
    st.rerun()

st.title("Vanguard Command Dashboard")

tabs = st.tabs(["Threat Surface", "Coverage Map", "Defensive Validation"])

with tabs[0]:
    # Capture the return value here in the main loop
    clicked_id = render_threat_graph()
    if clicked_id is not None:
        st.session_state.selected_phase_idx = int(clicked_id)

with tabs[1]:
    render_coverage_map(phase_idx=st.session_state.selected_phase_idx)

with tabs[2]:
    render_sigma_viewer(phase_idx=st.session_state.selected_phase_idx)