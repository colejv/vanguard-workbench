import streamlit as st
import os

def render_sigma_viewer(phase_idx=None):
    rules_dir = "outputs/sigma_rules"
    if not os.path.exists(rules_dir):
        st.warning("No Sigma rules found.")
        return

    rule_files = sorted([f for f in os.listdir(rules_dir) if f.endswith('.yml')])
    
    # NEW LOGIC: If phase_idx is None, show a selector for all rules
    if phase_idx is None:
        selected_rule = st.selectbox(
            "Select Sigma Rule to View (Global)", 
            rule_files, 
            key="sigma_global_selector"
        )
    else:
        # If phase_idx is present, filter for that specific phase
        selected_rule = rule_files[phase_idx] if phase_idx < len(rule_files) else None
        st.info(f"Displaying rules for Phase {phase_idx + 1}")
    
    if selected_rule:
        with open(os.path.join(rules_dir, selected_rule), "r") as f:
            st.code(f.read(), language="yaml")