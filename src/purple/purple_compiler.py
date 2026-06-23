"""
Vanguard Purple Team Compiler
Parses Stage 4 MDMP plans, crosswalks techniques against the published
Atomic Red Team index, and generates an engagement scaffold.
"""

import re
import json
import os
import urllib.request
import yaml
from dataclasses import dataclass, asdict
from typing import List, Dict

ART_INDEX_URL = "https://raw.githubusercontent.com/redcanaryco/atomic-red-team/master/atomics/Indexes/index.yaml"
CACHE_DIR = "corpus-index"
CACHE_FILE = os.path.join(CACHE_DIR, "art_index.json")

@dataclass
class EngagementPhase:
    phase_name: str
    action: str
    technique_ids: List[str]
    blue_team_telemetry: str
    blue_team_alert: str
    test_references: List[Dict[str, str]]

class PurplePlanCompiler:
    def __init__(self, plan_path: str):
        self.plan_path = plan_path
        self.art_index = self._fetch_art_index()
        
    def _fetch_art_index(self, force=False):
        """Fetch and cache the published ART index."""
        if os.path.exists(CACHE_FILE) and not force:
            with open(CACHE_FILE, 'r') as f:
                return json.load(f)

        print("Fetching live Atomic Red Team index...")
        try:
            with urllib.request.urlopen(ART_INDEX_URL, timeout=30) as r:
                raw = yaml.safe_load(r.read())
        except Exception as e:
            print(f"ERROR fetching ART index: {e}")
            return {}

        flat = {}
        for tactic, techniques in raw.items():
            if not isinstance(techniques, dict):
                continue
            for tid, entry in techniques.items():
                tests = entry.get("atomic_tests", []) or []
                flat[tid.upper()] = {
                    "technique_name": entry.get("technique", {}).get("name", ""),
                    "tactic": tactic,
                    "test_count": len(tests),
                    "test_names": [t.get("name", "") for t in tests],
                }

        os.makedirs(CACHE_DIR, exist_ok=True)
        with open(CACHE_FILE, "w") as f:
            json.dump(flat, f, indent=2)
        return flat

    def parse_mdmp_plan(self) -> List[EngagementPhase]:
        """Parses the Stage 4 MDMP output into structured phase objects."""
        try:
            with open(self.plan_path, "r") as f:
                content = f.read()
        except FileNotFoundError:
            print(f"ERROR: Could not find {self.plan_path}")
            return []

        phases = []
        # BUG 1 FIX: Match exact Stage 4 header formatting
        phase_blocks = re.split(r'###\s+\*\*Phase\s+\d+:', content)[1:] 
        
        for block in phase_blocks:
            # Clean up the phase name extraction
            phase_name_raw = block.split('\n')[0]
            phase_name = phase_name_raw.replace('**', '').strip()
            
            # BUG 3 FIX: Robust regex for Action, Telemetry, and Alerts
            action_match = re.search(r'\*\s+\*\*Action:\*\*\s+(.*?)\n\*', block, re.DOTALL)
            action = action_match.group(1).strip() if action_match else "Unknown"
            
            mitre_section = re.search(r'\*\s+\*\*MITRE ATT&CK Mapping:\*\*(.*?)(?=\n\*\s+\*\*Execution Timeline)', block, re.DOTALL)
            ids = []
            if mitre_section:
                ids = re.findall(r'(T\d{4}(?:\.\d{3})?|CAPEC-\d+)', mitre_section.group(1))
            
            telemetry_match = re.search(r'\*\s+\*\*Telemetry:\*\*\s+(.*?)\n', block)
            alert_match = re.search(r'\*\s+\*\*Alert Trigger:\*\*\s+(.*?)(?=\n|$)', block)
            
            telemetry = telemetry_match.group(1).strip() if telemetry_match else ""
            alert = alert_match.group(1).strip() if alert_match else ""
            
            phases.append(EngagementPhase(
                phase_name=phase_name,
                action=action,
                technique_ids=ids,
                blue_team_telemetry=telemetry,
                blue_team_alert=alert,
                test_references=[]
            ))
            
        return phases

    def perform_crosswalk(self, phases: List[EngagementPhase]) -> List[EngagementPhase]:
        """Maps extracted techniques to the published test index."""
        for phase in phases:
            for tid in phase.technique_ids:
                t = tid.upper()
                if t.startswith("T") and t in self.art_index:
                    rec = self.art_index[t]
                    phase.test_references.append({
                        "id": tid,
                        "status": "VETTED",
                        "framework": "Atomic Red Team",
                        "technique_name": rec["technique_name"],
                        "test_count": rec["test_count"]
                    })
                else:
                    # BUG 2 FIX: Correctly flag non-ATT&CK and missing IDs as coverage gaps
                    reason = "Non-ATT&CK framework" if not t.startswith("T") else "No published atomic"
                    phase.test_references.append({
                        "id": tid,
                        "status": "COVERAGE GAP",
                        "framework": "None",
                        "technique_name": reason,
                        "test_count": 0
                    })
        return phases

    def print_coverage_map(self, phases: List[EngagementPhase]):
        """Renders the immediate coverage map for the Purple Team."""
        print("\n" + "="*60)
        print("PURPLE TEAM COVERAGE MAP: SUT ENGAGEMENT")
        print("="*60)
        
        for i, phase in enumerate(phases, 1):
            print(f"\n[PHASE {i}] {phase.phase_name}")
            print(f"Action: {phase.action}")
            print("-" * 40)
            
            for ref in phase.test_references:
                if ref["status"] == "VETTED":
                    print(f"  [✓] {ref['id']}: {ref['test_count']} published test(s) — {ref['technique_name']}")
                else:
                    print(f"  [!] {ref['id']}: {ref['status']} — {ref['technique_name']}")

if __name__ == "__main__":
    # Ensure pip install pyyaml is run before execution
    compiler = PurplePlanCompiler("outputs/stage4_mission_plan.md")
    
    print(f"Loaded {len(compiler.art_index)} techniques from index.")
    print("Parsing MDMP Plan...")
    parsed_phases = compiler.parse_mdmp_plan()
    
    print("Executing Index Crosswalk...")
    mapped_phases = compiler.perform_crosswalk(parsed_phases)
    
    compiler.print_coverage_map(mapped_phases)
    
    scaffold_path = "outputs/purple_scaffold.json"
    with open(scaffold_path, "w") as f:
        json.dump([asdict(p) for p in mapped_phases], f, indent=2)
    print(f"\nScaffold exported to {scaffold_path} for Phase 2 Sigma generation.")