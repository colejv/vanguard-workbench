from crewai import Task
from src.agents import (researcher, decomposer, mapper,
                        modeler, red_team_lead, orchestrator, verifier)
from src.tools import (lookup_technique, kcag_min_cut, bbn_threat_score,
                       verify_corpus_lock, read_corpus_chunk,
                       extract_to_scratch, read_scratch,
                       verify_and_fix_stage2)

# Gate 1: corpus lock confirmation (human authorizes before analysis)
t_research = Task(
    description=(
        "The corpus lock has been verified pre-flight. "
        "State verbatim: 'CORPUS LOCK VERIFIED: {file_count} files match manifest version {corpus_version}. "
        "Corpus is fixed. Stage 0 authorized to proceed.' "
        "Do not call any tools. Do not add analysis."
    ),
    expected_output="Verbatim corpus version confirmation statement.",
    agent=researcher,
    human_input=True,
    output_file="outputs/corpus_manifest.md",
)

'''
t_extract_chunk = Task(
    description=(
        "You are processing a single corpus chunk: {chunk_content}\n\n"
        "Extract EVERY: named system, AAMCAT or other subsystem, vendor product, "
        "interface, protocol, version, exercise event, named person, and organization. "
        "Call `extract_to_scratch` with the chunk index ({chunk_index}) and your findings."
    ),
    expected_output="Confirmation that findings were written to scratchpad.",
    agent=decomposer,
    tools=[extract_to_scratch],
)
'''

t_synthesize_stage0 = Task(
    description=(
        "Assessment brief:\n{sut_brief}\n\n"
        "1. Call `read_scratch('EXECUTE')` to retrieve all extracted findings.\n"
        "2. Produce Stage 0 Reverse IPB from the scratchpad: technical, procedural, "
        "and cognitive signatures from a nation-state AI-fusion perspective.\n"
        "3. Produce Stage 1 decomposition (Data→Information→Knowledge→Understanding→Decision→Behavior) "
        "applied to the Cognitive layer per ADP 3-13.\n"
        "Flag missing elements with [GAP]."
    ),
    expected_output="Exhaustive Stage 0 assessment and Stage 1 decomposition.",
    agent=decomposer,
    tools=[read_scratch],
    output_file="outputs/stage0_1.md",
)

t_stage2 = Task(
    description=(
        "Stage 2 attack surface characterization. For each vector give: \n"
        "(1) technique ID, (2) cognitive hierarchy stage affected, \n"
        "(3) whether it exploits a Stage 0 friendly signature.\n\n"
        "CRITICAL INSTRUCTION: You must use the lookup_technique tool to ground EVERY vector. "
        "Do not stop at Enterprise ATT&CK. If the vector involves AI/ML (like model poisoning), "
        "you MUST search for ATLAS techniques (AML.Txxxx). If it involves physical hardware, "
        "sensors, or PNT/GPS spoofing, you MUST search the EMB3D or ICS matrices.\n\n"
        "Lead with IDs before prose. Annotate (HIGH)/(MEDIUM)/(LOW). Flag [GAP] inline ONLY "
        "if multiple searches confirm the concept does not exist in any framework."
    ),
    expected_output="Ranked vectors with cross-framework technique IDs (Enterprise, ATLAS, ICS, EMB3D).",
    agent=mapper,
    tools=[lookup_technique],
    output_file="outputs/stage2.md",
)

t_verify_stage2 = Task(
    description=(
        "You are an adversarial verifier. Your job is mechanical, not analytical.\n"
        "Step 1: Read the contents of outputs/stage2.md.\n"
        "Step 2: Call verify_and_fix_stage2 with the full text of that file.\n"
        "Step 3: Report the tool's output VERBATIM — do not paraphrase or interpret.\n"
        "Step 4: If STATUS is FAIL, list every hallucinated ID and what it should "
        "be corrected to by searching the index with lookup_technique using keywords "
        "from the vector description.\n"
        "Step 5: Do NOT pass a FAIL result downstream. State that Stage 2 must be "
        "corrected before Annex B can proceed.\n"
        "You may not produce analysis. Only verification and correction suggestions."
    ),
    expected_output=(
        "Verbatim ID verification report (PASS or FAIL). "
        "If FAIL: list of hallucinated IDs with suggested corrections from index lookup."
    ),
    agent=verifier,
    tools=[verify_and_fix_stage2, lookup_technique],
    output_file="outputs/stage2_verification.md",
)

t_annexB = Task(
    description="Annex B: build the KCAG DAG from Stage 2 output and compute the "
                "minimum node cut to identify the priority kill-chain path. "
                "You must use the kcag_min_cut tool and provide valid JSON nodes and edges.",
    expected_output="KCAG min-cut nodes + priority path.",
    agent=modeler,
    tools=[kcag_min_cut],
    output_file="outputs/annexB_kcag.md",
)

t_annexC = Task(
    description="Annex C: build the five-layer pgmpy BBN, infer threat probability "
                "and phase estimate. Guard against cyclic pathways.",
    expected_output="BBN threat score + phase estimate.",
    agent=modeler,
    tools=[bbn_threat_score],
    output_file="outputs/annexC_bbn.md",
)

# Gate 2: authorization confirmation before payload design
# Gate 2: authorization confirmation before payload design
t_stage3 = Task(
    description=(
        "Confirm all preconditions are met (corpus fixed; explicit authorization for SUT testing granted). "
        "Review the CORRECTED attack vectors from Stage 2 (provided in the verifier output context) and the priority kill-chain path from Annex B. "
        "Design testable payloads for these specific vulnerabilities using the four-category taxonomy: "
        "C2 & Data Flow Disruption / Degradation & Destruction / Physical Behavior Alteration / Decision-Making Corruption.\n\n"
        "CRITICAL INSTRUCTION 1: For every payload designed, you MUST use the `lookup_technique` tool to cross-reference "
        "and assign specific Red Team execution IDs (MITRE ATT&CK/CAPEC/ATLAS) and corresponding Blue Team defensive/mitigation concepts.\n"
        "CRITICAL INSTRUCTION 2: If a vector is marked [GAP], you have two choices: use your `lookup_technique` tool to search for a valid framework ID yourself, "
        "or explicitly write `[UNMAPPED]` for the technique ID. DO NOT fabricate or hallucinate a MITRE ID. Do not assign IDs like T1606 to AI poisoning unless the index confirms it."
    ),
    expected_output="Authorized payload set keyed directly to Stage 2 vectors, rigorously cross-referenced with real MITRE IDs.",
    agent=red_team_lead,
    context=[t_verify_stage2, t_annexB],  # <-- Changed t_stage2 to t_verify_stage2
    human_input=True,              
    output_file="outputs/stage3.md",
)

# Gate 3: final mission-plan release
t_stage4 = Task(
    description=(
        "Draft the Stage 4 MDMP mission plan based on the payloads developed in Stage 3. "
        "Provide a phased execution timeline. For each phase, explicitly map the planned actions "
        "to the MITRE technique IDs identified previously. "
        "Define explicit OPSEC measures and Blue Team assessment/detection criteria for each test payload "
        "so the defenders know what telemetry to look for during the test."
    ),
    expected_output="MDMP-format red team mission plan with phased ATT&CK mapping and Blue Team assessment criteria.",
    agent=red_team_lead,
    context=[t_stage3],            # <-- Explicitly feeds the payload taxonomy
    human_input=True,              # Doctrinal gate: plan release
    output_file="outputs/stage4_mission_plan.md",
)