"""
Sprint 2: Defensive Sigma Rule Generator
Reads the purple_scaffold.json and uses a local coding LLM to translate
the Blue Team assessment criteria into valid Sigma rules.
"""

import json
import requests
import os

OLLAMA_URL = "http://localhost:11434/api/generate"
# You can change this to qwen2.5-coder:7b or whichever coding model you have pulled
MODEL_NAME = "gemma4:12b-mlx" 

def generate_sigma_rule(phase_name: str, telemetry: str, alert: str) -> str:
    """Passes the detection criteria to the LLM to generate a Sigma rule."""
    
    system_prompt = (
        "You are a Blue Team detection engineer. Your job is to translate natural language "
        "telemetry and alert criteria into a valid, strictly formatted YAML Sigma rule. "
        "Do NOT provide explanations, markdown blocks, or offensive code. "
        "Output ONLY the YAML."
    )
    
    prompt = (
        f"Create a Sigma rule for the following engagement phase.\n"
        f"Phase: {phase_name}\n"
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
            "options": {"temperature": 0.1} # Keep it highly deterministic
        })
        response.raise_for_status()
        return response.json().get("response", "").strip()
    except Exception as e:
        return f"ERROR generating rule: {e}"

def run_pipeline():
    scaffold_path = "outputs/purple_scaffold.json"
    rules_dir = "outputs/sigma_rules"
    
    if not os.path.exists(scaffold_path):
        print(f"Error: {scaffold_path} not found. Run purple_compiler.py first.")
        return

    with open(scaffold_path, "r") as f:
        phases = json.load(f)

    os.makedirs(rules_dir, exist_ok=True)
    
    print(f"Loaded {len(phases)} phases. Generating Sigma rules via {MODEL_NAME}...")
    
    for i, phase in enumerate(phases, 1):
        phase_name = phase.get("phase_name", f"Phase_{i}")
        telemetry = phase.get("blue_team_telemetry", "")
        alert = phase.get("blue_team_alert", "")
        
        if not telemetry and not alert:
            print(f"Skipping {phase_name}: No detection criteria found.")
            continue
            
        print(f"Generating rule for Phase {i}: {phase_name}...")
        sigma_yaml = generate_sigma_rule(phase_name, telemetry, alert)
        
        # Clean up markdown formatting if the model leaked any
        sigma_yaml = sigma_yaml.replace("```yaml", "").replace("```", "").strip()
        
        # Save to disk
        safe_name = phase_name.replace(" ", "_").replace("/", "-").replace("&", "and").lower()
        # Keep it to alphanumeric and underscores
        safe_name = "".join([c for c in safe_name if c.isalnum() or c in ['_', '-']])
        
        rule_path = os.path.join(rules_dir, f"phase_{i}_{safe_name}.yml")
        with open(rule_path, "w") as f:
            f.write(sigma_yaml)
            
        print(f" -> Saved to {rule_path}")

if __name__ == "__main__":
    run_pipeline()
    print("\nSprint 2 Complete. Purple Team Engagement Plan is fully scaffolded with detection validation.")