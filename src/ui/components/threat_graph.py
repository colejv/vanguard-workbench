import streamlit as st
import json
from streamlit_agraph import agraph, Node, Edge, Config

def render_threat_graph():
    try:
        with open("outputs/kcag_data.json", "r") as f:
            graph_data = json.load(f)
    except FileNotFoundError:
        st.error("kcag_data.json not found.")
        return None

    # Debug: Print the raw node data to the dashboard to inspect it
    # st.write("Debug Node Data:", graph_data["nodes"])

    nodes = []
    for n in graph_data.get("nodes", []):
        # Explicitly pull the color; fallback to a distinct "debug" color 
        # so you can see if it's hitting the fallback or the data
        color_val = n.get("color", "#FFA500") 
        nodes.append(Node(
            id=n["id"], 
            label=n["label"], 
            color=color_val, 
            size=30
        ))
    
    edges = [Edge(source=e["source"], target=e["target"]) for e in graph_data.get("edges", [])]
    
    config = Config(height=400, width=700, directed=True, physics=False, clickToFocus=True)
    return agraph(nodes=nodes, edges=edges, config=config)