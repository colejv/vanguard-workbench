import streamlit as st
import pandas as pd
import json

def render_coverage_map(phase_idx=None): # <--- Add the argument here
    scaffold_path = "outputs/purple_scaffold.json"
    
    try:
        with open(scaffold_path, "r") as f:
            data = json.load(f)
            
        # If a phase_idx is provided, filter the data
        if phase_idx is not None and phase_idx < len(data):
        # We now have the option to show only one, or show all. 
        # Let's keep it to only the selected one for the "Drill Down" effect.
            data = [data[phase_idx]]
            
        rows = []
        for phase in data:
            for ref in phase["test_references"]:
                rows.append({
                    "Phase": phase["phase_name"],
                    "Technique": ref["id"],
                    "Status": ref["status"],
                    "Framework": ref["framework"],
                    "Test Count": ref["test_count"]
                })
        
        df = pd.DataFrame(rows)
        
        def color_status(val):
            color = 'green' if val == 'VETTED' else 'red'
            return f'color: {color}'
            
        # Remove the previous st.dataframe call and replace it with this:
        st.dataframe(
            df.style.map(color_status, subset=['Status']),
            width=None, # Clear any previous width references
            use_container_width=True # Ensure this is the only width-related toggle
        )
        
    except FileNotFoundError:
        st.error("Purple scaffold not found.")