from crewai import Agent
from config.llm import light_llm, reason_llm
from src.tools import (lookup_technique, kcag_min_cut, bbn_threat_score,
                       verify_corpus_lock, read_corpus_chunk,
                       extract_to_scratch, read_scratch,
                       verify_technique_ids, verify_and_fix_stage2)

researcher = Agent(
    role="IW Researcher",
    goal="Confirm corpus lock status before Stage 0 proceeds.",
    backstory="Enforces pre-analysis corpus discipline per Annex A Phase 1.",
    llm=reason_llm,    # changed from light_llm
    allow_delegation=False,
    verbose=True,
)

decomposer = Agent(
    role="System Decomposer",
    goal="Stage 0 Reverse IPB and Stage 1 decomposition using corpus chunks.",
    backstory="Reads corpus in chunks; never produces templates or awaits input.",
    llm=reason_llm,
    allow_delegation=False,
    verbose=True,
    tools=[read_corpus_chunk, extract_to_scratch, read_scratch],
)

mapper = Agent(
    role="Attack Surface Mapper",
    goal="Stage 2: map components to ATT&CK/CAPEC/ATLAS/EMB3D/SPARTA "
         "with technique IDs and confidence annotations.",
    backstory="Selects frameworks by system type; flags [GAP] items inline.",
    llm=reason_llm, allow_delegation=False, verbose=True,
)

modeler = Agent(
    role="Graph & Probability Modeler",
    goal="Annex B KCAG minimum-cut analysis and Annex C BBN threat scoring.",
    backstory="Runs NetworkX and pgmpy pipelines via tools; guards against cycles.",
    llm=reason_llm, allow_delegation=False, verbose=True,
)

red_team_lead = Agent(
    role="Red Team Lead",
    goal="Stage 3 payload design and Stage 4 MDMP plan mapped to strict MITRE frameworks.",
    backstory="Enforces authorization gates; translates vulnerability paths into testable payloads grounded in MITRE corpora.",
    llm=reason_llm, 
    allow_delegation=False, 
    verbose=True,
    tools=[lookup_technique]  # <-- CRITICAL FIX: Grants access to the MITRE index
)

orchestrator = Agent(
    role="Orchestrator",
    goal="Track stage state, verify upstream outputs, log gaps.",
    backstory="Maintains the analytical record and gap log across stages.",
    llm=light_llm, allow_delegation=False, verbose=True,
)

verifier = Agent(
    role="Adversarial Verifier",
    goal="Verify every technique ID in stage outputs against the indexed corpus. "
         "Pass only outputs where every ID resolves. Fail and block any output "
         "containing hallucinated or unresolvable IDs.",
    backstory="Treats every ID as wrong until the index proves it right. "
              "Precision on framework identifiers is correctness, not style.",
    llm=reason_llm,
    allow_delegation=False,
    verbose=True,
    tools=[verify_technique_ids, verify_and_fix_stage2, lookup_technique],
)