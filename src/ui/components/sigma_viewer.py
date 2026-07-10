import os
import streamlit as st

from src import run_context


def render_sigma_viewer(action_id=None):
    """Show generated Sigma rules for the active run. When action_id is
    given, filters to rules whose filename starts with that action ID
    (sigma_generator.py names files '<action_id>_<test_id>.yml', so this
    is an exact, meaningful match) -- not a list-index lookup into an
    alphabetically sorted file list, which the legacy version used and
    which had no real relationship to which rule belonged to which
    selected phase.
    """
    rules_dir = run_context.artifact_path("sigma_rules")
    if not os.path.exists(rules_dir):
        st.warning("No Sigma rules found for this run. Run the Sigma generator first.")
        return

    rule_files = sorted(f for f in os.listdir(rules_dir) if f.endswith(".yml"))
    if not rule_files:
        st.warning("No Sigma rules found for this run. Run the Sigma generator first.")
        return

    if action_id is None:
        selected_rule = st.selectbox(
            "Select Sigma Rule to View (Global)",
            rule_files,
            key="sigma_global_selector",
        )
    else:
        matching = [f for f in rule_files if f.startswith(f"{action_id}_")]
        if not matching:
            st.info(f"No Sigma rule(s) found for action {action_id}.")
            return
        st.caption(f"Showing rule(s) for action {action_id}")
        selected_rule = matching[0] if len(matching) == 1 else st.selectbox(
            f"Select Sigma Rule for {action_id}", matching, key="sigma_action_selector",
        )

    if selected_rule:
        with open(os.path.join(rules_dir, selected_rule)) as f:
            st.code(f.read(), language="yaml")