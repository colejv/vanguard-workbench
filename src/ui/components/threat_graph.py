import streamlit as st
from streamlit_agraph import agraph, Node, Edge, Config

from src import run_context


def render_threat_graph():
    """Render the Purple Team action graph for the active run. Node IDs
    are Stage 4 action IDs (e.g. 'ACT-001') -- not the old sequential
    phase-index strings ('0', '1', ...) the legacy kcag_data.json used.
    Returns the clicked node's action_id string, or None if nothing was
    clicked. Callers must NOT int()-cast the return value; the old
    dashboard.py did, which assumed node IDs were numeric phase indices."""
    try:
        graph_data = run_context.read_stamped_json(run_context.artifact_path("purple_graph.json"))
    except FileNotFoundError:
        st.error("purple_graph.json not found for this run. Run the Purple Team compiler first.")
        return None
    except Exception as e:
        st.error(f"Could not read purple_graph.json: {e}")
        return None

    nodes = []
    for n in graph_data.get("nodes", []):
        color_val = n.get("color", "#FFA500")
        nodes.append(Node(
            id=n["id"],
            label=n["label"],
            color=color_val,
            size=30,
        ))

    edges = [Edge(source=e["source"], target=e["target"]) for e in graph_data.get("edges", [])]

    config = Config(height=400, width=700, directed=True, physics=False, clickToFocus=True)
    return agraph(nodes=nodes, edges=edges, config=config)