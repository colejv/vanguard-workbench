from crewai import Agent
from config.llm import light_llm, reason_llm

# CRITICAL FIX 1: Consolidated imports from src.tools
from src.tools import (
    kcag_min_cut, 
    bbn_threat_score,
    lookup_technique, 
    read_corpus_chunk,
    extract_to_scratch, 
    read_scratch,
    verify_technique_ids, 
    verify_and_fix_stage2,
    write_stage2_vectors
)

researcher = Agent(
    role="IW Researcher",
    goal="Confirm corpus lock status before Stage 0 proceeds.",
    backstory="Enforces pre-analysis corpus discipline per Annex A Phase 1.",
    llm=reason_llm,
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
    # cache=False: write_stage0_output/write_stage1_output validate structured
    # JSON and can legitimately fail on a first attempt (oversized/malformed
    # payload). With the default cache=True, a failed call can be replayed
    # from cache on retry instead of the model regenerating fresh args,
    # which stalls the agent on the same broken JSON until it gives up and
    # falls back to a prose-only final answer. Disabling cache ensures every
    # retry actually re-invokes the tool with the model's latest output.
    cache=False,
    # max_iter raised from the CrewAI default (20) — Stage 0/1 tasks now
    # involve read_scratch + a validated structured-JSON write that can take
    # several corrective attempts against a local model; the default ceiling
    # was reached before the model's JSON converged (observed: agent fell
    # back to text-only output after ~8 tool attempts well under 20 calls,
    # since each failed attempt + reasoning step consumes multiple
    # iterations toward the same budget).
    max_iter=40,
)

mapper = Agent(
    role="Attack Surface Mapper",
    goal="Stage 2: map components to ATT&CK/CAPEC/ATLAS/EMB3D/SPARTA "
         "with technique IDs and confidence annotations.",
    # CRITICAL FIX 2: Instruct the mapper to assign criticality weights
    backstory=(
        "Selects frameworks by system type; flags [GAP] items inline. "
        "CRITICAL: When mapping components, you must evaluate and assign a "
        "'criticality' score (1-10) to every node, where 10 is mission-critical "
        "OT/Command systems. These scores are passed to the Modeler for Annex B analysis."
    ),
    llm=reason_llm, 
    allow_delegation=False, 
    verbose=True,
    tools=[write_stage2_vectors]
)

modeler = Agent(
    role="Graph & Probability Modeler",
    goal="Annex B KCAG minimum-cut analysis and Annex C BBN threat scoring.",
    backstory="Runs NetworkX and pgmpy pipelines via tools; guards against cycles.",
    llm=reason_llm, 
    allow_delegation=False, 
    verbose=True,
    # CRITICAL FIX 3: Give the modeler the tools to execute the math
    tools=[kcag_min_cut, bbn_threat_score]
)

red_team_lead = Agent(
    role="Red Team Lead",
    goal="Stage 3 payload design and Stage 4 MDMP plan mapped to strict MITRE frameworks.",
    backstory="Enforces authorization gates; translates vulnerability paths into testable payloads grounded in MITRE corpora.",
    llm=reason_llm, 
    allow_delegation=False, 
    verbose=True,
    tools=[lookup_technique]
)

orchestrator = Agent(
    role="Orchestrator",
    goal="Track stage state, verify upstream outputs, log gaps.",
    backstory="Maintains the analytical record and gap log across stages.",
    llm=light_llm, 
    allow_delegation=False, 
    verbose=True,
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