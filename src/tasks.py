from crewai import Task
from src.agents import (researcher, decomposer, mapper,
                        modeler, red_team_lead, orchestrator)
from src.tools import (lookup_technique, kcag_min_cut, bbn_threat_score,
                       extract_to_scratch, read_scratch, write_stage2_vectors)

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

t_synthesize_stage0 = Task(
    description=(
        "Assessment brief:\n{sut_brief}\n\n"
        "1. Call `read_scratch('EXECUTE')` to retrieve all extracted findings.\n"
        "2. Produce Stage 0 Reverse IPB from the scratchpad: technical, procedural, "
        "and cognitive signatures from a nation-state AI-fusion perspective.\n"
        "   For each signature give a confidence rating (HIGH/MEDIUM/LOW) and note "
        "whether it is a candidate DECEIVE injection point for Stage 3.\n"
        "3. ATTRIBUTION DISCIPLINE: every named person, unit, vendor, or component "
        "you assert MUST trace to a finding in the scratchpad. Do NOT introduce any "
        "entity that is not in the extracted corpus. If you cannot trace it, omit it.\n"
        "Flag missing elements with [GAP]."
    ),
    expected_output=(
        "Stage 0 Reverse IPB: technical, procedural, cognitive, and social/personnel "
        "signatures, each with a confidence rating and DECEIVE-candidate flag. "
        "Every named entity traceable to the scratchpad."
    ),
    agent=decomposer,
    tools=[read_scratch],
    output_file="outputs/stage0.md",
)

t_stage1 = Task(
    description=(
        "Stage 1 system decomposition per ADP 3-13. You have the Stage 0 signatures "
        "in context and may call `read_scratch('EXECUTE')` for source detail.\n\n"
        "Produce THREE layers — not just the cognitive layer:\n\n"
        "LAYER 1 — TECHNICAL: every hardware, software, network, and data-flow "
        "component. For each, give: component_id (C-T-NN), name, asset_control_levels "
        "(ordered adversary states, e.g. No Access -> API Reach -> Write Access), "
        "information_flows (inputs -> outputs), and downstream_dependencies "
        "(which components break if this one is compromised).\n\n"
        "LAYER 2 — PROCEDURAL: SOPs, kill-chain workflow, PACE plan, update/CI-CD "
        "cycle, coalition data-sharing, exercise rhythm. Same fields (C-P-NN).\n\n"
        "LAYER 3 — COGNITIVE: apply the ADP 3-13 cognitive hierarchy "
        "(Data -> Information -> Knowledge -> Understanding -> Decision -> Behavior). "
        "For each stage: what feeds it, what corrupts it, the downstream effect, and "
        "detection probability. Identify the cognitive Center of Gravity (C-C-NN).\n\n"
        "Also produce a TRUST BOUNDARY inventory: each boundary between components "
        "where the adversary can traverse a trust relationship.\n\n"
        "ATTRIBUTION DISCIPLINE: every node id must correspond to a Stage 0 signature "
        "or a scratchpad finding. Do not invent components.\n\n"
        "Flag missing elements with [GAP]."
    ),
    expected_output=(
        "Three-layer decomposition (Technical / Procedural / Cognitive) with a "
        "structured node inventory (component_id, layer, asset_control_levels, "
        "information_flows, downstream_dependencies) and a trust-boundary inventory. "
        "This node inventory is the required input to Annex B (Stage 2 edge list)."
    ),
    agent=decomposer,
    context=[t_synthesize_stage0],
    tools=[read_scratch],
    output_file="outputs/stage1.md",
)

t_stage2 = Task(
    description=(
        "Stage 2 attack surface characterization. For each vector give: \n"
        "(1) technique ID, (2) cognitive hierarchy stage affected, \n"
        "(3) whether it exploits a Stage 0 friendly signature.\n\n"
        "CRITICAL INSTRUCTION 1: You must use the lookup_technique tool to ground EVERY vector. "
        "Do not stop at Enterprise ATT&CK. If the vector involves AI/ML (like model poisoning), "
        "you MUST search for ATLAS techniques (AML.Txxxx). If it involves physical hardware, "
        "sensors, or PNT/GPS spoofing, you MUST search the EMB3D or ICS matrices.\n\n"
        "Lead with IDs before prose. Annotate (HIGH)/(MEDIUM)/(LOW). Flag [GAP] inline ONLY "
        "if multiple searches confirm the concept does not exist in any framework.\n\n"
        "CRITICAL INSTRUCTION 2 — STRUCTURED EDGE LIST (REQUIRED FOR ANNEX B):\n"
        "After writing the prose analysis, you MUST call `write_stage2_vectors` exactly once "
        "with a JSON object that encodes the attack graph as nodes and edges. Annex B reads "
        "this file; without it the KCAG cannot be built. Rules:\n"
        "  - Every node has: id, node_type (one of: privilege, technique, property, "
        "countermeasure, goal), criticality (1-10; CDL/fires/OT = 10).\n"
        "  - Every edge has: source, target, technique (the grounded ID), "
        "difficulty (LOW|MEDIUM|HIGH), effect (DECEIVE|DISRUPT|DEGRADE|DESTROY or null), vec (V-NN).\n"
        "  - There MUST be at least one entry node (a 'privilege' node named ADV_START with "
        "no incoming edges) and at least one node with node_type 'goal'.\n"
        "  - Goal nodes are terminal IW effects (e.g. G_CDL_ALL, G_FIRES_WRONG). The graph must "
        "be connected from ADV_START to each goal.\n"
        "  - Do NOT invent components. Every node id must trace to a Stage 1 decomposition "
        "node or a Stage 0 signature."
    ),
    expected_output=(
        "Ranked vectors with cross-framework technique IDs (Enterprise, ATLAS, ICS, EMB3D) in prose, "
        "AND confirmation that the structured edge list was written to outputs/stage2_vectors.json "
        "via the write_stage2_vectors tool."
    ),
    context=[t_stage1],
    agent=mapper,
    tools=[lookup_technique, write_stage2_vectors],
    output_file="outputs/stage2.md",
)

t_annexB = Task(
    description=(
        "Annex B: build the Kill Chain Attack Graph and compute the minimum node "
        "cut and betweenness centrality to identify the priority kill-chain path.\n\n"
        "CRITICAL: You do NOT author the graph. The topology was written to "
        "outputs/stage2_vectors.json by the Stage 2 mapper. Call `kcag_min_cut` with "
        "stage2_vectors_path='outputs/stage2_vectors.json'. The tool reads that file, "
        "builds the DiGraph, runs the computation, and writes outputs/kcag_report.json.\n\n"
        "Do NOT pass hand-authored nodes or edges. Do NOT invent components or paths. "
        "If the tool returns an ERROR (missing or malformed artifact), report it "
        "verbatim and state that Stage 2 must emit a valid edge list before Annex B "
        "can proceed — do not work around it by fabricating a graph.\n\n"
        "After the tool succeeds, report its output verbatim: the dominant min-cut "
        "node, the number of objectives it cuts, the top betweenness node and its "
        "ratio to the next, and the highest-probability priority path. Do not "
        "substitute your own analysis for the computed numbers."
    ),
    expected_output=(
        "Verbatim kcag_min_cut tool output: dominant min-cut node (with objectives-cut "
        "count), top betweenness centrality, and the highest-probability priority path. "
        "Confirmation that outputs/kcag_report.json was written for Annex C ingestion."
    ),
    agent=modeler,
    context=[t_stage2],
    tools=[kcag_min_cut],
    output_file="outputs/annexB_kcag.md",
)

t_annexC = Task(
    description=(
        "Annex C: construct the evidence-driven BBN, ingest the Annex B KCAG priors "
        "from outputs/kcag_report.json, run inference, and return the threat score, "
        "kill-chain phase estimate, and CPD audit log.\n\n"
        "Call `bbn_threat_score` with a JSON config containing the adversary profile "
        "(capability_prior, tempo), defensive_posture, geopolitical_trigger_prior, and "
        "observed evidence indicators. Every CPD value must come from the config you "
        "supply — do not rely on the tool to invent priors. The tool ingests "
        "kcag_report.json automatically for the objective-phase prior.\n\n"
        "Report the tool output verbatim: threat score, level, baseline delta, phase "
        "distribution. The BBN is acyclic by construction; if the tool reports a "
        "validation error, report it verbatim and do not fabricate a score."
    ),
    expected_output="Verbatim BBN threat score, level, phase distribution, and CPD audit reference.",
    agent=modeler,
    context=[t_annexB],
    tools=[bbn_threat_score],
    output_file="outputs/annexC_bbn.md",
)

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
    context=[t_annexB],  
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