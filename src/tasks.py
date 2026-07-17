from crewai import Task
import json
import os
from src import run_context
from src.agents import (researcher, decomposer, mapper,
                        modeler, red_team_lead, orchestrator)
from src.tools import (lookup_technique, kcag_min_cut, bbn_threat_score,
                       extract_to_scratch, read_scratch, write_stage2_vectors,
                       write_stage0_output, write_stage1_output, write_stage3_test_plan,
                       write_stage4_execution_plan)


def build_tasks(out_dir: str, resume_context: dict = None) -> dict:
    """Construct the seven pre-Stage-4 stage/annex/gate tasks with run-scoped
    output_file paths. Stage 4 is built separately by build_stage4_task()
    below, once Stage 3 has produced verified output — see that function's
    docstring for why. Tasks can't be built at module-import time the way
    they used to be — out_dir depends on run_id, which doesn't exist until
    crew.py generates it inside __main__. crew.py calls this once, right
    after run_context.set_active_run(), and unpacks the returned dict.

    resume_context: optional {"t_stage1": "<stage0 prose text>", ...}. Used
    only when resuming an interrupted run past a stage that already
    completed. CrewAI's context=[...] mechanism requires the referenced
    task to actually execute as part of THIS crew's kickoff() — it can't
    supply an already-computed answer from a task that isn't running. So
    when a prior stage is being skipped on resume, its completed content is
    injected directly into the dependent task's description instead of
    using context=[...] to reference the (now absent) upstream task. Keys
    are task names as in this function's return dict; only "t_stage1" and
    "t_stage2" are ever meaningful resume-injection points (t_synthesize_stage0
    has no upstream context dependency to begin with).

    Tool-call path references have been simplified in several descriptions
    below (t_annexB, t_annexC) since kcag_min_cut/bbn_threat_score now
    auto-resolve their input/output paths via run_context when the agent
    doesn't pass one explicitly — the agent no longer needs to know or state
    a literal path, which is one fewer thing for a local model to get right
    on every tool call.
    """
    resume_context = resume_context or {}

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
        # Deliberately NOT named corpus_manifest.md -- that name collides
        # with sources/corpus_manifest.md (the frozen lock manifest itself)
        # and risks someone reading the wrong file.
        output_file=f"{out_dir}/corpus_lock_confirmation.md",
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
            "Flag missing elements with [GAP].\n\n"
            "CRITICAL INSTRUCTION — STRUCTURED SIGNATURE LIST (REQUIRED FOR STAGE 1):\n"
            "After writing the prose Reverse IPB, you MUST call `write_stage0_output` exactly "
            "once with a real structured `signatures` argument — a list of objects, passed "
            "directly as the tool's argument, never as a JSON string you construct yourself. "
            "Stage 1 reads this file to trace attribution; without it Stage 1 cannot verify its "
            "node inventory.\n\n"
            "SIZE DISCIPLINE — this list is generated in a single tool call and WILL be rejected "
            "if too large:\n"
            "  - Select at most 15 signatures total for this structured list — the ones with the "
            "greatest analytic significance (highest confidence, clearest DECEIVE-candidate value, "
            "or most central to the SUT). The full prose Reverse IPB in your written output may "
            "still discuss more findings; the structured list is a curated top-15, not an exhaustive "
            "transcription.\n"
            "  - Keep each description to ONE short phrase (under ~12 words). Do not restate "
            "background context already covered in the prose narrative — the description field is "
            "an index label, not a summary paragraph.\n"
            "  - If the scratchpad has more than 15 candidate signatures, prioritize by category "
            "coverage (include at least one technical, one procedural, and one cognitive signature "
            "if the scratchpad supports it) and by DECEIVE-candidate relevance.\n\n"
            "Argument shape and field rules:\n"
            "  - `signatures` argument: a list of objects, e.g. "
            "[{\"signature_id\": \"S-T-01\", \"category\": \"technical\", ...}, ...] — pass this "
            "as the actual list argument to the tool call, not as a string.\n"
            "  - Every signature has: signature_id (e.g. S-T-01, S-P-03, S-C-02 — prefix matches "
            "category: T=technical, P=procedural, C=cognitive, SP=social_personnel), "
            "category (technical|procedural|cognitive|social_personnel), description, "
            "confidence (HIGH|MEDIUM|LOW), deceive_candidate (true|false).\n"
            "  - Set is_gap=true for any [GAP] placeholder entries instead of inventing a signature_id "
            "for something you could not trace to the scratchpad.\n"
            "  - signature_id must be unique across the whole list."
        ),
        expected_output=(
            "Stage 0 Reverse IPB: technical, procedural, cognitive, and social/personnel "
            "signatures, each with a confidence rating and DECEIVE-candidate flag. "
            "Every named entity traceable to the scratchpad. "
            "AND confirmation that a curated top-15 structured signature list was written "
            "via the write_stage0_output tool."
        ),
        agent=decomposer,
        tools=[read_scratch, write_stage0_output],
        output_file=f"{out_dir}/stage0.md",
    )

    _stage1_resume_prefix = (
        f"PRIOR STAGE OUTPUT (Stage 0 — already completed on a previous, interrupted "
        f"run; provided here as context since this run resumed past it, not generated "
        f"by you):\n\n{resume_context['t_stage1']}\n\n---\n\n"
    ) if "t_stage1" in resume_context else ""

    t_stage1 = Task(
        description=(
            _stage1_resume_prefix +
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
            "detection probability. Optionally flag any standout candidate touchpoint(s) "
            "within this layer (C-C-NN) — note this is advisory only: per JP 5-0/ADP 3-0, "
            "Center of Gravity is domain-agnostic, and the operational COG is computed "
            "graph-theoretically in Annex B (min-cut + betweenness) and may fall on a "
            "Technical or Procedural node instead.\n\n"
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
        context=[] if "t_stage1" in resume_context else [t_synthesize_stage0],
        tools=[read_scratch],
        output_file=f"{out_dir}/stage1.md",
    )

    # ---- Separate, single-purpose task for the structured write ----
    # Split out of t_stage1 above after a real observed failure: t_stage1's
    # combined prompt (write three full prose layers, THEN remember a
    # trailing four-argument tool call almost 70 lines later) let the model
    # treat a complete-looking prose Final Answer as satisfying the whole
    # task -- confirmed directly in a debug log with ZERO Action/tool-call
    # attempts for write_stage1_output, not a rejected or malformed one.
    # A short, freshly-started task whose ONLY job is the tool call is much
    # more reliable for actually getting that call made than a trailing
    # instruction buried at the end of a long compound one -- same
    # reasoning as the Stage 0/1/2 crew split itself, one level down.
    t_stage1_write = Task(
        description=(
            "You have just completed the Stage 1 three-layer decomposition above. "
            "Your ONLY job now is to call `write_stage1_output` exactly once, "
            "translating that decomposition into four real structured list "
            "arguments — technical_nodes, procedural_nodes, cognitive_nodes, and "
            "trust_boundaries — passed directly as the tool's arguments, never "
            "assembled into a single JSON string yourself. Do not rewrite or "
            "re-summarize the prose narrative. This task is not complete until the "
            "tool has actually been called and returned a WRITTEN confirmation — "
            "describing what you would write is not the same as writing it.\n\n"
            "Stage 2 reads this file to verify every attack-graph node traces to a "
            "real Stage 1 component; without it Stage 2 cannot be checked.\n\n"
            "SIZE DISCIPLINE — this list is generated in a single tool call and "
            "WILL be rejected if too large:\n"
            "  - Cap each layer at roughly 8-10 of the most architecturally "
            "significant components (not every item from the decomposition above) "
            "— technical components that are real attack surface, procedural "
            "elements with real exploitable timing/process gaps, cognitive stages "
            "with a real corruption path. Aim for a total around 25-30 nodes across "
            "all three layers combined, not 40+.\n"
            "  - Keep information_flows, feeds, corrupts, and downstream_effect to "
            "ONE short phrase each (under ~10 words) — these are index labels for "
            "Stage 2 to reference, not summary paragraphs.\n"
            "  - Cap trust_boundaries at roughly 5-8 entries — the boundaries with "
            "the clearest adversary-traversable trust relationship, not every "
            "possible pairing.\n\n"
            "Argument shape and field rules:\n"
            "  - Four separate list arguments: technical_nodes=[...], "
            "procedural_nodes=[...], cognitive_nodes=[...], trust_boundaries=[...] "
            "— pass each as its own real list argument to the tool call, not as a "
            "combined JSON string.\n"
            "  - technical_nodes / procedural_nodes entries: component_id "
            "(C-T-NN / C-P-NN), layer (\"technical\" or \"procedural\" — MUST match "
            "the list you put it in), name, asset_control_levels (a JSON list of "
            "strings, e.g. [\"No Access\", \"API Reach\", \"Write Access\"] — NOT "
            "a single arrow-joined string like \"No Access -> API Reach\"), "
            "information_flows (a single string), downstream_dependencies (a JSON "
            "list of component ID strings, e.g. [\"C-T-02\", \"C-P-01\"] — NOT a "
            "single joined string), is_gap (boolean).\n"
            "  EXAMPLE technical node:\n"
            "    {\"component_id\": \"C-T-01\", \"layer\": \"technical\", "
            "\"name\": \"Common Data Layer\", \"asset_control_levels\": "
            "[\"No Access\", \"API Reach\", \"Write Access\"], "
            "\"information_flows\": \"sensor data in, COP out\", "
            "\"downstream_dependencies\": [\"C-T-02\"], \"is_gap\": false}\n"
            "  - cognitive_nodes entries: component_id (C-C-NN), hierarchy_stage "
            "(one of Data, Information, Knowledge, Understanding, Decision, "
            "Behavior), feeds (string), corrupts (string), downstream_effect "
            "(string), detection_probability (HIGH|MEDIUM|LOW), "
            "is_center_of_gravity (boolean), is_gap (boolean).\n"
            "  - trust_boundaries entries: boundary_id (TB-NN), from_component, "
            "to_component, description.\n"
            "  - component_id must be unique across all three layers combined.\n"
            "  - Set is_gap=true for [GAP] placeholder entries instead of "
            "inventing a component_id."
        ),
        expected_output=(
            "Confirmation that a curated structured node inventory (~25-30 nodes "
            "total) was written via the write_stage1_output tool, quoting the "
            "tool's own WRITTEN result message verbatim."
        ),
        agent=decomposer,
        context=[t_stage1],
        tools=[write_stage1_output],
    )

    _stage2_resume_prefix = (
        f"PRIOR STAGE OUTPUT (Stage 1 — already completed on a previous, interrupted "
        f"run; provided here as context since this run resumed past it, not generated "
        f"by you):\n\n{resume_context['t_stage2']}\n\n---\n\n"
    ) if "t_stage2" in resume_context else ""

    t_stage2 = Task(
        description=(
            _stage2_resume_prefix +
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
            "After writing the prose analysis, you MUST successfully call "
            "`write_stage2_vectors` with two real structured list arguments — nodes and "
            "edges — passed directly as the tool's arguments, never assembled into a JSON "
            "string yourself. Annex B reads this file; without it the KCAG cannot be built.\n\n"
            "The task is complete only when `write_stage2_vectors` returns a response "
            "beginning with `WRITTEN:`. Merely invoking the tool is not sufficient.\n"
            "If the tool returns `REJECTED:`, read every validation error, correct the "
            "nodes or edges, and call the tool again. You may make at most 3 structured "
            "write attempts. Do not provide a Final Answer after a rejected write.\n\n"
            "Rules:\n"
            " - `nodes` argument: a list of objects. Every node has: id, node_type "
            "(one of: privilege, technique, property, countermeasure, goal), "
            "criticality (1-10; CDL/fires/OT = 10).\n"
            " - `edges` argument: a list of objects. Every edge must explicitly contain: "
            "source, target, technique, difficulty, effect, and vec.\n"
            " - `difficulty` is required on EVERY edge, including component-to-goal "
            "edges, and must be exactly LOW, MEDIUM, or HIGH. Never omit it and never "
            "represent it as `-`.\n"
            " - `effect` must be DECEIVE, DISRUPT, DEGRADE, DESTROY, or null.\n"
            " - `vec` must be a unique concrete identifier assigned sequentially in "
            "edge-list order: `V-01`, `V-02`, `V-03`, and so on.\n"
            " - Never emit the literal placeholders `V-NN`, `V-N`, `V-XX`, or `V-00`.\n"
            " - Example: if there are three edges, their vec values must be `V-01`, "
            "`V-02`, and `V-03` respectively.\n"
            "  - ADV_START MUST be the SOLE entry node — it is the only node allowed to have "
            "no incoming edge. Every other node you declare (property, technique, "
            "countermeasure, or goal) MUST be the source or target of at least one edge. "
            "Do not declare a node and then leave it unused — an unused node is a validation "
            "failure (it will show up as both an extra root and a dead end).\n"
            "  - Declare ONLY nodes that are used by the final edge list. Do not copy the "
            "complete Stage 1 component inventory into `nodes`. If a component is not the "
            "source or target of an attack-path edge, omit it from the structured graph.\n"
            "  - Before calling the writer, construct the set of every edge source and target. "
            "Every declared node ID must appear in that set.\n"
            "  - There MUST be at least one node with node_type 'goal'.\n"
            "  - Goal nodes are terminal IW effects (e.g. G_CDL_ALL, G_FIRES_WRONG). The graph "
            "must be connected from ADV_START to each goal THROUGH the components you "
            "identified — not a direct ADV_START-to-goal edge that merely mentions a "
            "technique or component in its fields. If a vector targets a specific system "
            "component (a 'property' node from Stage 1), that component MUST be an "
            "intermediate hop in the path, e.g.:\n"
            "      ADV_START --[technique: AML.T0080]--> C-T-02 --[effect: DECEIVE]--> G_OP_BIAS\n"
            "    NOT:\n"
            "      ADV_START --[technique: AML.T0080]--> G_OP_BIAS   (C-T-02 declared but never used)\n"
            "  - Do NOT invent components. Every node id must trace to a Stage 1 decomposition "
            "node or a Stage 0 signature.\n\n"
            "If the tool returns `REJECTED`, read every reported validation error, correct "
            "the nodes or edges, and call the tool again. You may make at most 3 write "
            "attempts. Do not provide a Final Answer until the tool returns a result "
            "beginning with `WRITTEN:`. Merely invoking the tool is not sufficient, and "
            "reporting a rejected call as success is a critical error — the actual tool "
            "result governs, not your description of it."
        ),
        expected_output=(
            "Ranked vectors with cross-framework technique IDs "
            "(Enterprise, ATLAS, ICS, EMB3D) in prose, followed by the "
            "`write_stage2_vectors` tool's successful `WRITTEN:` result. "
            "A `REJECTED:` result is not task completion."
        ),
        context=[] if "t_stage2" in resume_context else [t_stage1],
        agent=mapper,
        tools=[lookup_technique, write_stage2_vectors],
        output_file=f"{out_dir}/stage2.md",
    )

    _annexB_resume_prefix = (
        f"PRIOR STAGE OUTPUT (Stage 2 — already completed on a previous, interrupted "
        f"run; provided here as context since this run resumed past it, not generated "
        f"by you):\n\n{resume_context['t_annexB']}\n\n---\n\n"
    ) if "t_annexB" in resume_context else ""

    t_annexB = Task(
        description=(
            _annexB_resume_prefix +
            "Annex B: build the Kill Chain Attack Graph and compute the minimum node "
            "cut and betweenness centrality to identify the priority kill-chain path.\n\n"
            "CRITICAL: You do NOT author the graph. The topology was written by the "
            "Stage 2 mapper. Call `kcag_min_cut` with no arguments — it automatically "
            "reads the current run's Stage 2 output, builds the DiGraph, runs the "
            "computation, and writes the KCAG report for Annex C.\n\n"
            "Do NOT pass hand-authored nodes or edges. Do NOT invent components or paths. "
            "If the tool returns an ERROR (missing or malformed artifact), report it "
            "verbatim and state that Stage 2 must emit a valid edge list before Annex B "
            "can proceed — do not work around it by fabricating a graph.\n\n"
            "After the tool succeeds, report its output verbatim: the dominant min-cut "
            "node, the number of objectives it cuts, the top betweenness node and its "
            "ratio to the next, and the highest-scoring priority path. Do not substitute "
            "your own analysis for the computed numbers.\n\n"
            "NUMERICAL DISCIPLINE: the path score is a configured heuristic (fixed "
            "difficulty-to-value mappings multiplied along the path) — it is NOT a "
            "calibrated probability derived empirically, even where a legacy field "
            "name or prior report phrasing calls it one. State this distinction "
            "explicitly rather than letting 'highest' or 'probability'-adjacent "
            "language imply more statistical confidence than the number supports. "
            "The result supports relative ranking of candidate paths, not a claim "
            "about real-world likelihood of success."
        ),
        expected_output=(
            "Verbatim kcag_min_cut tool output: dominant min-cut node (with objectives-cut "
            "count), top betweenness centrality, and the highest-scoring priority path — "
            "plus a brief note naming the path score as a configured heuristic, not a "
            "calibrated probability. Confirmation that the KCAG report was written for "
            "Annex C ingestion."
        ),
        agent=modeler,
        context=[] if "t_annexB" in resume_context else [t_stage2],
        tools=[kcag_min_cut],
        output_file=f"{out_dir}/annexB_kcag.md",
    )

    _annexC_resume_prefix = (
        f"PRIOR ANNEX OUTPUT (Annex B — already completed on a previous, interrupted "
        f"run; provided here as context since this run resumed past it, not generated "
        f"by you):\n\n{resume_context['t_annexC']}\n\n---\n\n"
    ) if "t_annexC" in resume_context else ""

    t_annexC = Task(
        description=(
            _annexC_resume_prefix +
            "Annex C: run the BBN threat score against the ANALYST-APPROVED assessment "
            "configuration, ingest the Annex B KCAG heuristic factor, and return the "
            "threat score, kill-chain phase estimate, and CPD audit log.\n\n"
            "AUTHORITATIVE INPUT: you do NOT author the per-assessment configuration. The "
            "four priors (adversary.capability_prior, adversary.tempo, defensive_posture, "
            "geopolitical_trigger_prior) were derived from the frozen corpus by the Annex C "
            "derivation subsystem, each bound to cited evidence, and REVIEWED AND APPROVED "
            "by the analyst before this task runs. That approved configuration is written to "
            "the run directory as annexc_assessment_config.json.\n\n"
            "Call `bbn_threat_score` with:\n"
            "  - approved_config_path set to the run's annexc_assessment_config.json\n"
            "  - cpd_config_json left EMPTY (do not supply your own config)\n"
            "The tool loads the approved configuration, and REFUSES to score any config you "
            "supply that differs from it (SUBSTITUTED_ASSESSMENT_CONFIG). Leave "
            "kcag_report_path unset — the tool automatically ingests the current run's KCAG "
            "report for the objective-phase scaling factor.\n\n"
            "Report the tool output verbatim: threat score, level, baseline delta, phase "
            "distribution. The BBN is acyclic by construction; if the tool reports a "
            "validation error, report it verbatim and do not fabricate a score.\n\n"
            "The tool also runs deterministic one-way sensitivity analysis and reports it "
            "in the same output, in addition to the baseline result above. After the "
            "baseline BBN result, report the sensitivity summary exactly as returned by "
            "the tool. Explain:\n"
            "  - which inputs produced the largest absolute change;\n"
            "  - whether the threat-level classification changed;\n"
            "  - which parameters were masked by supplied evidence;\n"
            "  - which scenarios were skipped and why;\n"
            "  - that the results are one-way deterministic stress tests;\n"
            "  - that interaction effects and statistical uncertainty were not measured.\n"
            "Do not recalculate or replace the tool's driver ranking, and do not call the "
            "sensitivity range a confidence interval or infer empirical calibration from "
            "classification stability."
        ),
        expected_output=(
            "Either a blocking-gap report naming the specific missing input(s) and what "
            "the analyst needs to supply, OR the verbatim BBN threat score, level, phase "
            "distribution, and CPD audit reference — preceded by a short table or list "
            "showing each per-assessment input's value and source — followed by the "
            "sensitivity analysis summary (top drivers, classification stability, masked "
            "and skipped scenarios, and the stated methodological limitations)."
        ),
        agent=modeler,
        context=[] if "t_annexC" in resume_context else [t_annexB],
        tools=[bbn_threat_score],
        output_file=f"{out_dir}/annexC_bbn.md",
    )

    # Gate 2: authorization confirmation before payload design
    # t_stage3 has TWO upstream dependencies -- t_stage2 and t_annexB --
    # each independently skippable on resume, unlike every other task above
    # which only has one. resume_context["t_stage3_stage2"] and
    # ["t_stage3_annexb"] are set independently by crew.py; whichever is
    # ABSENT stays a live context=[...] reference (that upstream task is
    # actually running in this crew), whichever is PRESENT gets injected as
    # text instead (that upstream task was skipped).
    _stage3_parts = []
    _stage3_live_context = []
    if "t_stage3_stage2" in resume_context:
        _stage3_parts.append("[STAGE 2]\n" + resume_context["t_stage3_stage2"])
    else:
        _stage3_live_context.append(t_stage2)
    if "t_stage3_annexb" in resume_context:
        _stage3_parts.append("[ANNEX B]\n" + resume_context["t_stage3_annexb"])
    else:
        _stage3_live_context.append(t_annexB)

    _stage3_resume_prefix = (
        "PRIOR STAGE OUTPUT (already completed on a previous, interrupted run; "
        "provided here as context since this run resumed past it, not generated "
        "by you — section headers below mark which stage each part came from):\n\n"
        + "\n\n---\n\n".join(_stage3_parts) + "\n\n---\n\n"
    ) if _stage3_parts else ""

    t_stage3 = Task(
        description=(
            _stage3_resume_prefix +
            "Confirm all preconditions are met (corpus fixed; explicit authorization for SUT testing granted). "
            "Review the CORRECTED attack vectors from Stage 2 (provided in the verifier output context) and the priority kill-chain path from Annex B. "
            "Design testable payloads for these specific vulnerabilities using the four-category taxonomy. For "
            "EVERY payload, state its category as an explicit numbered label — do not rely on the category name "
            "alone, since Stage 4 and downstream tooling key off this number:\n"
            "  Category 1 — C2 & Data Flow Disruption\n"
            "  Category 2 — Degradation & Destruction\n"
            "  Category 3 — Physical Behavior Alteration\n"
            "  Category 4 — Decision-Making Corruption\n"
            "A payload may carry more than one category if it spans effects; list all that apply "
            "(e.g. 'Category: 3, 4').\n\n"
            "CRITICAL INSTRUCTION 1: For every payload designed, you MUST use the `lookup_technique` tool to cross-reference "
            "and assign specific Red Team execution IDs (MITRE ATT&CK/CAPEC/ATLAS) and corresponding Blue Team defensive/mitigation concepts.\n"
            "CRITICAL INSTRUCTION 2: If a vector is marked [GAP], you have two choices: use your `lookup_technique` tool to search for a valid framework ID yourself, "
            "or explicitly write `[UNMAPPED]` for the technique ID. DO NOT fabricate or hallucinate a MITRE ID. Do not assign IDs like T1606 to AI poisoning unless the index confirms it.\n"
            "CRITICAL INSTRUCTION 3 — GROUND THE MECHANISM, NOT JUST THE ID: every payload's technical description must match the "
            "ACTUAL nature of its target component as characterized in Stage 1 — check that component's `name` and `information_flows` "
            "before writing the payload, not a generic or stock attack pattern for that vector category. If Stage 1 characterizes a "
            "component as cloud-native/API/container/UI-based, the payload must describe cloud-native/API/container/UI mechanics — "
            "do NOT introduce industrial-control terminology (PLC, SCADA, Modbus, HMI, historian, holding registers, valve/actuator "
            "positions) unless Stage 1 explicitly establishes that component as an ICS/OT system. The reverse also applies: do not "
            "describe cloud-native mechanics against a component Stage 1 characterizes as embedded/ICS. A correct technique ID "
            "attached to a fabricated architecture is still a fabrication. If you genuinely lack enough characterization to ground a "
            "payload (e.g. Stage 2's vector description is too thin), say so explicitly rather than inventing detail — do not "
            "silently fall back on category-generic boilerplate either.\n"
            "CRITICAL INSTRUCTION 4 — A SUCCESSFUL LOOKUP IS NOT THE SAME AS A MATCHING LOOKUP: `lookup_technique` returning a result "
            "is not sufficient grounds to cite that ID. Read the tool's full returned `description` field — not just the id/name — and "
            "confirm it actually describes the mechanism you are writing, before citing it:\n"
            "  - Sub-techniques matter: if a technique has numbered variants (e.g. T1195.002 vs T1195.003), verify the SPECIFIC "
            "sub-technique's description matches your scenario. Do not cite a sibling sub-technique just because the parent technique "
            "matched — a hardware-supply-chain sub-technique does not correctly cite a software/CI-CD-supply-chain payload, and vice versa.\n"
            "  - SPARTA-framework results describe space-segment/spacecraft techniques specifically (onboard flight code, GNSS, "
            "crosslinks, TT&C beacons). If the SUT has no established space component in Stage 0/1, a SPARTA ID's own description will "
            "contradict your scenario — do not use it; search again with different keywords or mark [UNMAPPED] instead.\n"
            "  - If the tool's description does not match your scenario, do not silently keep the ID anyway — re-run `lookup_technique` "
            "with adjusted keywords, or fall back to [UNMAPPED] per Critical Instruction 2. A technique ID whose own description "
            "contradicts your payload narrative is a fabrication, even though the tool call itself succeeded without error.\n"
            "  - Before finalizing your answer, re-read your own payload set for internal consistency: any summary or priority-path-"
            "alignment section must reference the SAME node/vector each payload's own header states. Do not let a summary table drift "
            "from the payload details it is supposed to be summarizing.\n"
            "CRITICAL INSTRUCTION 5 — PRE-STAGE-4 SAFETY REVIEW (doctrinal, not optional): a deterministic gate reads "
            "your output for this exact structure before Stage 4 can even be constructed — get the field labels exactly "
            "right, do not paraphrase them.\n"
            "  For any payload carrying Category 2 or Category 3, also state within that payload's own section: "
            "Affected assets, Expected effect, Required approving roles, Safety authority, Abort authority, Abort "
            "criteria, Maximum termination time, and Rollback or recovery procedure.\n"
            "  After all payloads, add one assessment-wide section, headed exactly '## PRE-STAGE-4 SAFETY REVIEW'.\n"
            "  If ANY payload carries Category 2 or 3, that section MUST contain each of these exact field labels, "
            "one per line, each followed by a real, specific, non-placeholder value (never 'TBD', 'unknown', 'N/A', "
            "'none', or 'not determined' — a genuinely undetermined value is itself a gap that blocks Stage 4, not "
            "something to paper over):\n"
            "    Category 2/3 concepts present: YES\n"
            "    Covered test concepts: <every Category 2/3 payload's ID>\n"
            "    Affected assets: <specific>\n"
            "    Required approving roles: <specific>\n"
            "    RSO or domain-equivalent safety authority: <specific>\n"
            "    Abort authority: <specific>\n"
            "    Abort criteria: <specific>\n"
            "    Maximum termination time: <specific>\n"
            "    Rollback or recovery procedure: <specific>\n"
            "    Release condition: <a sentence stating execution may not/must not/shall not begin before safety "
            "clearance is approved>\n"
            "  If NO payload carries Category 2 or 3, the section must instead state, verbatim and exactly: "
            "'NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED.' Do not omit the section either way — its "
            "absence is itself a gate failure, never a silent gap. Do not state the not-required sentence if ANY "
            "payload actually carries Category 2 or 3 — that is a direct contradiction and will also fail the gate.\n"
            "CRITICAL INSTRUCTION 6 — REFERENTIAL DISCIPLINE: your prose must describe each test "
            "concept completely enough that a downstream compiler can extract a structured test plan "
            "from it. For every concept, make explicit in the prose: a unique test_id in RT-NNN format "
            "as a '### RT-NNN — <title>' heading; objective; one or more existing Stage 2 vector IDs; a "
            "complete kcag_path beginning at ADV_START and ending at a goal node; whether that path is "
            "the Annex B PRIORITY_PATH or an ALTERNATE_VALID_PATH (a valid path to a different meaningful "
            "objective is acceptable — it does not have to be the global priority path, but it must be a "
            "real one); target node IDs on that path; one or more category numbers 1-4; grounded "
            "execution technique references (a real ID from the technique index, or exactly `[UNMAPPED]` "
            "with a rationale — never an invented-looking ID); defensive concepts; preconditions; "
            "expected effects; measurable success criteria; explicit abort criteria; rollback or recovery "
            "steps; required telemetry; and explicit assumptions.\n"
            "  For a Category 2 or 3 concept, safety controls are mandatory and must be stated. For "
            "concepts containing neither category, state that no safety controls are required.\n"
            "  Do not invent Stage 2 vector IDs, graph nodes, graph paths, framework IDs, assets, "
            "approving roles, or safety authorities. A deterministic gate re-checks every reference "
            "against the real Stage 2 graph, KCAG report, and technique index after the structured plan "
            "is compiled from this prose — an invented-looking reference will fail that gate."
        ),
        expected_output=(
            "Human-reviewed Stage 3 test concepts in stage3.md, each with a complete RT-NNN heading and "
            "all the referential detail (vector IDs, kcag_path, categories, technique IDs, criteria) a "
            "downstream compiler needs to build the structured test plan."
        ),
        agent=red_team_lead,
        context=_stage3_live_context,
        tools=[lookup_technique],
        human_input=True,
        output_file=f"{out_dir}/stage3.md",
    )

    # Gate 3: final mission-plan release
    # t_stage4 is intentionally NOT built here. Stage 4 now runs in its own
    # crew (stage4_crew, constructed in crew.py) so it can never receive a
    # live context=[t_stage3] reference -- see build_stage4_task() below,
    # which requires already-verified Stage 3 text instead.

    return {
        "t_research": t_research,
        "t_synthesize_stage0": t_synthesize_stage0,
        "t_stage1": t_stage1,
        "t_stage1_write": t_stage1_write,
        "t_stage2": t_stage2,
        "t_annexB": t_annexB,
        "t_annexC": t_annexC,
        "t_stage3": t_stage3,
    }


def build_stage4_task(out_dir: str, stage3_content: str, stage3_test_plan: dict) -> Task:
    """
    Constructs t_stage4 fresh, from already-verified Stage 3 text AND the
    already-verified structured test plan -- never via a live CrewAI
    context=[...] reference. Stage 4 runs in its own crew (stage4_crew),
    and Stage 3's task object is never part of that crew's task list, so
    context=[t_stage3] is not just unnecessary here, it would silently do
    nothing (CrewAI only resolves context from tasks that execute as part
    of the SAME crew.kickoff() call).

    stage3_content must be the ALREADY-STAMPED-AND-VERIFIED body text --
    i.e. the return value of run_context.read_stamped_prose() called on
    the real stage3.md for the active run -- not raw file content, and
    never text the caller merely believes is trustworthy.

    stage3_test_plan must be the ALREADY-VALIDATED structured plan dict
    -- i.e. the return value of run_context.read_stamped_json() called on
    stage3_test_plan.json for the active run, after it has passed both
    validate_stage3_test_plan() (referential/structural) and
    check_stage3_artifact_consistency() (prose/JSON agreement). This is
    the load-bearing check the structured-Stage-3 commit exists to add:
    Stage 4 cannot be constructed from a plan that hasn't cleared the
    hard gate, any more than it could be constructed from unverified
    prose.

    Raises ValueError on empty/whitespace-only content, or an empty/falsy
    stage3_test_plan.
    """
    if not stage3_content or not stage3_content.strip():
        raise ValueError(
            "build_stage4_task requires non-empty verified Stage 3 content. "
            "Stage 3 must be stamped and read via read_stamped_prose() "
            "before Stage 4 can be constructed."
        )
    if not stage3_test_plan:
        raise ValueError(
            "build_stage4_task requires the verified structured Stage 3 test plan. "
            "stage3_test_plan.json must be validated before Stage 4 can be constructed."
        )

    structured_json = json.dumps(stage3_test_plan, indent=2, sort_keys=True)

    return Task(
        description=(
            "The following Stage 3 artifacts were produced for the active "
            "assessment run and verified through Vanguard's run-identity, "
            "corpus-identity, and structural checks before being provided "
            "here — neither is live CrewAI task context, but both are the "
            "complete, unmodified Stage 3 output for this run.\n\n"
            "=== VERIFIED STAGE 3 HUMAN-READABLE ARTIFACT ===\n"
            f"{stage3_content}\n"
            "=== END VERIFIED STAGE 3 HUMAN-READABLE ARTIFACT ===\n\n"
            "=== VERIFIED STRUCTURED STAGE 3 TEST PLAN ===\n"
            f"{structured_json}\n"
            "=== END VERIFIED STRUCTURED STAGE 3 TEST PLAN ===\n\n"
            "The structured test plan is authoritative for test IDs, category "
            "numbers, Stage 2 vector references, KCAG paths, success criteria, "
            "abort criteria, safety controls, and telemetry requirements. The "
            "prose artifact supplies explanatory context. Do not invent a test "
            "concept that is absent from the structured plan. Do not omit a "
            "structured test concept from the Stage 4 mission plan.\n\n"
            "Draft the Stage 4 MDMP mission plan based on the payloads developed in the "
            "Stage 3 artifacts provided above. "
            "Provide a phased execution timeline. For each phase, explicitly map the planned actions "
            "to the MITRE technique IDs identified previously. "
            "Define explicit OPSEC measures and Blue Team assessment/detection criteria for each test payload "
            "so the defenders know what telemetry to look for during the test.\n\n"
            "CRITICAL INSTRUCTION — PHASE 0 SAFETY GATE (doctrinal, not optional):\n"
            "Check every payload's category label from Stage 3 context. If ANY payload carries "
            "Category 2 (Degradation & Destruction) or Category 3 (Physical Behavior Alteration) — "
            "i.e. any payload capable of a real-world physical or destructive effect — you MUST insert "
            "a 'PHASE 0 — SAFETY GATE' section immediately before Phase 1 of the execution timeline. "
            "This section is mandatory and must explicitly include:\n"
            "  - Range Safety Officer (RSO) coordination requirement\n"
            "  - Abort criteria with a maximum termination time (e.g. red team lead to test operators, "
            "<15 sec termination confirmed)\n"
            "  - A statement that Phase 1 may NOT begin until Phase 0 safety clearance is signed off\n"
            "  - Any system-specific safety review required beyond the standard Stage 3/Stage 4 "
            "authorization gates\n"
            "If NO payload carries Category 2 or 3, state explicitly and verbatim: "
            "'NO CATEGORY 2/3 PAYLOADS — PHASE 0 SAFETY GATE NOT REQUIRED.' Do not simply omit the "
            "section — its absence must always be a deliberate, stated conclusion, never a silent gap. "
            "A deterministic check reads this output for exactly this language after you finish; an "
            "omitted or ambiguous safety-gate statement on a Category 2/3 payload set will halt the run.\n\n"
            "CRITICAL INSTRUCTION — STRUCTURED STAGE 4 PLAN: after drafting the human-readable MDMP plan "
            "above, make the prose COMPLETE and UNAMBIGUOUS enough that a deterministic compiler can build "
            "the structured execution plan from it after this crew finishes — you do NOT call any writer "
            "tool yourself. The Markdown you produce must fully describe every phase, action, test concept, "
            "safety disposition, telemetry requirement, and abort control, so the compiled JSON and the "
            "prose describe the same plan.\n"
            "  The structured Stage 3 test plan (embedded above) remains authoritative for test IDs, "
            "categories, Stage 2 vector references, KCAG paths, execution technique references, success "
            "criteria, abort criteria, recovery requirements, telemetry requirements, and Category 2/3 "
            "safety controls. You may sequence and elaborate those concepts across one or more actions, "
            "but you may not add a new test concept, remove an approved concept, weaken an inherited abort "
            "or recovery requirement, invent a framework ID, or change a test's category.\n"
            "  Every Stage 4 action must: have a unique ACT-NNN identifier; reference exactly one existing "
            "RT-NNN test concept; identify responsible roles; state preconditions; carry measurable success "
            "criteria; carry explicit abort criteria; carry rollback or recovery steps; identify telemetry "
            "requirements; identify one or more alert triggers; identify OPSEC measures. Every Stage 3 test "
            "concept requires at least one action — a concept may be split across multiple actions or phases "
            "as long as their combined fields still cover everything Stage 3 required for that concept.\n"
            "  Each phase requires a unique PHASE-NN identifier, and phase sequence numbers must be "
            "contiguous starting at 1. The plan itself requires a unique MP-NNN plan_id.\n"
            "  The JSON must state exactly: `\"artifact_role\": \"HUMAN_REVIEWED_MISSION_PLAN_DRAFT\"` and "
            "`\"execution_authorization\": \"NOT_GRANTED\"` — this artifact is a planning product and does "
            "not authorize execution.\n"
            "  A deterministic gate re-checks every Stage 3 binding, inherited requirement, and Phase 0 "
            "disposition against the real Stage 3 test plan after this crew finishes — a plan that silently "
            "drops, alters, or invents a test concept, or weakens the approved maximum termination time or "
            "required approving roles, will fail that gate even though the writer tool itself may accept "
            "it now."
        ),
        expected_output=(
            "A human-reviewed MDMP mission plan in stage4_mission_plan.md, complete enough for the "
            "post-crew compiler to build the matching structured execution plan."
        ),
        agent=red_team_lead,
        context=[],
        tools=[],
        human_input=True,
        output_file=f"{out_dir}/stage4_mission_plan.md",
    )


def build_kcag_review_task(out_dir: str, *, stage2_graph: dict, validation_report: dict) -> Task:
    """
    Constructs a READ-ONLY Quantitative Threat Modeler review of the
    Stage 2 KCAG graph -- analytical coherence, not structural validity
    (that's validate_kcag()'s job, already done by the time this is
    called) and not framework-ID correctness (verify_stage2_vectors()'s
    job). The review is advisory in this version: it cannot mutate the
    graph, cannot block Annex B, and Annex B never receives it as
    context, so the reviewer's prose can never influence the
    deterministic KCAG math.

    stage2_graph and validation_report must be the ALREADY-VERIFIED
    dicts returned by run_context.read_stamped_json() on the active
    run's real stage2_vectors.json / kcag_validation.json -- not raw
    file content, and never data the caller merely believes is current.

    Raises ValueError if either input is empty/falsy, or if the supplied
    validation_report itself reports is_valid=False -- a review task
    must never be constructed for a graph that failed deterministic
    validation; the caller broke the sequencing contract if it gets that
    far. This is the KCAG-review-specific equivalent of
    build_stage4_task's "empty Stage 3 content" guard.

    IMPORTANT KNOWN LIMITATION: tools=[] below does NOT actually strip
    tool access at runtime. CrewAI's own Task model has an unconditional
    post-construction validator (crewai/task.py, check_tools()) that
    falls back to the ASSIGNED AGENT's tools whenever a task's own tools
    list is empty -- "if not self.tools and self.agent and
    self.agent.tools: self.tools = self.agent.tools". Since modeler owns
    kcag_min_cut and bbn_threat_score, this task ends up with both
    available at runtime regardless of the tools=[] passed here,
    confirmed directly against the installed crewai version. There is no
    parameter to opt out of that fallback while keeping agent=modeler.
    "Read-only" is therefore enforced at the PROMPT level only ("Do not
    perform NetworkX calculations" below) for this task, same as several
    other behavioral constraints elsewhere in this codebase (e.g. "do
    not invent priors") -- not a mechanical guarantee. tools=[] is kept
    here anyway as correct documented intent, in case a future CrewAI
    version respects it, but should not be read as an actual restriction
    today.
    """
    if not stage2_graph:
        raise ValueError("KCAG review requires the verified Stage 2 graph.")
    if not validation_report:
        raise ValueError("KCAG review requires the deterministic validation report.")
    if not validation_report.get("is_valid"):
        raise ValueError(
            "KCAG review cannot be constructed for a graph that failed "
            "deterministic validation."
        )

    graph_json = json.dumps(stage2_graph, indent=2, sort_keys=True)
    validation_json = json.dumps(validation_report, indent=2, sort_keys=True)

    return Task(
        description=(
            "Perform a READ-ONLY quantitative and semantic review of the "
            "validated Kill Chain Attack Graph below.\n\n"
            "You must not add, remove, rewrite, repair, or reorder any graph "
            "node or edge. You must not invent framework identifiers, "
            "components, probabilities, prerequisites, or evidence.\n\n"
            "=== VERIFIED STAGE 2 GRAPH ===\n"
            f"{graph_json}\n"
            "=== END VERIFIED STAGE 2 GRAPH ===\n\n"
            "=== DETERMINISTIC KCAG VALIDATION REPORT ===\n"
            f"{validation_json}\n"
            "=== END VALIDATION REPORT ===\n\n"
            "Review the graph for analytical coherence. Examine:\n"
            "1. Edge direction and prerequisite logic.\n"
            "2. Whether goals represent meaningful terminal effects.\n"
            "3. Whether privilege transitions are plausible.\n"
            "4. Whether countermeasure placement is logically coherent.\n"
            "5. Whether cycles require explanation or temporal modeling.\n"
            "6. Whether difficulty labels are consistent with described "
            "preconditions.\n"
            "7. Whether effect labels match the described transition.\n"
            "8. Whether graph branches appear redundant or contradictory.\n"
            "9. Which conclusions depend on unsupported assumptions.\n"
            "10. What the graph cannot establish from topology alone.\n\n"
            "Do not repeat framework-ID verification. That was completed by "
            "the deterministic Stage 2 verifier.\n\n"
            "Do not call kcag_min_cut or bbn_threat_score, and do not perform "
            "or reproduce their NetworkX or Bayesian calculations yourself in "
            "any form. Annex B performs those calculations using the "
            "authoritative Stage 2 artifact immediately after this review, "
            "and this review's disposition does not gate or alter that "
            "calculation in this version -- your job here is qualitative "
            "reading of the graph already provided above, nothing "
            "computational.\n\n"
            "When a concern exists, cite the exact node IDs, edge endpoints, "
            "and vector IDs involved. Never describe a concern without "
            "identifying the affected graph elements.\n\n"
            "State explicit assumptions and their basis, and state plainly "
            "what the graph's topology alone cannot establish -- e.g. it "
            "does not establish real-world empirical attack-success "
            "probability, and KCAG traversal values are heuristic scores, "
            "not calibrated probabilities.\n\n"
            "The graph above carries qualitative difficulty labels "
            "(LOW/MEDIUM/HIGH) on each edge -- these become numeric heuristic "
            "traversal scores only later, when Annex B actually runs "
            "kcag_min_cut. You do not compute or see that numeric score here. "
            "Do not treat a difficulty label, or any other value in this "
            "graph or validation report, as evidence of a calibrated "
            "empirical probability. If your own review references a prior "
            "run's kcag_report.json for context and finds a legacy "
            "top_path_prob field there (from before this project's "
            "probability-to-heuristic-score terminology migration), treat "
            "that field name as a historical label only, not as evidence "
            "the value it holds is actually a probability.\n\n"
            "Use one of these review dispositions, stated exactly:\n"
            "- ACCEPT\n"
            "- ACCEPT WITH CAVEATS\n"
            "- RECOMMEND STAGE 2 REGENERATION\n\n"
            "The disposition is advisory in this version. It does not mutate "
            "the graph and does not automatically stop Annex B."
        ),
        expected_output=(
            "A read-only quantitative review saved as model_assumptions.md, "
            "with a disposition, graph-specific findings citing exact node/"
            "edge/vector IDs, explicit assumptions, limitations, and "
            "recommended analyst actions."
        ),
        agent=modeler,
        tools=[],
        context=[],
        human_input=False,
        output_file=f"{out_dir}/model_assumptions.md",
    )


def build_analysis_tasks(
    *,
    t_kcag_review=None,
    t_annexB,
    t_annexC,
    t_stage3,
    annexB_done: bool,
    annexC_done: bool,
    stage3_prose_done: bool = False,
) -> list:
    """
    Pure task-list assembly for analysis_crew -- no I/O, no run_context
    dependency, so the crew-ordering contract (KCAG review runs before
    Annex B, both skipped together on resume when Annex B is already
    done, Annex C and Stage 3 follow their own independent resume rules)
    is directly testable against real Task objects rather than
    reproduced separately in a test.

    t_kcag_review is only required (non-None) when annexB_done is False
    -- crew.py only constructs it in that branch, since building it
    needs real verified-artifact reads that are wasted work when Annex B
    won't run this invocation anyway.

    stage3_prose_done, when True, skips t_stage3 (the prose task) so a
    resume that already has stage3.md does not regenerate it. NOTE: this
    only governs the PROSE task inside the crew; the structured plan is
    compiled separately outside the crew by crew.py. A pure compile-only
    resume (prose present, plan missing) bypasses this function entirely
    -- crew.py detects that case before building analysis_tasks.
    """
    tasks = []
    if not annexB_done:
        tasks.append(t_kcag_review)
        tasks.append(t_annexB)
    if not annexC_done:
        tasks.append(t_annexC)
    if not stage3_prose_done:
        tasks.append(t_stage3)
    return tasks


def finalize_kcag_review_artifact(review_was_required: bool):
    """
    Single production implementation of the KCAG review artifact's
    fail-closed finalization -- crew.py and the test suite both call this
    directly, same reasoning as finalize_stage4_state and
    enforce_stage3_safety_gate: a test that reproduces "check existence,
    stamp, read" locally instead of calling this function can pass even
    if crew.py's actual wiring forgot to call it at all.

    review_was_required mirrors whether t_kcag_review was constructed
    this invocation (i.e. Annex B is about to run) -- when False, this is
    a no-op, since a skipped-on-resume review has nothing to finalize.

    Enforces the artifact's EXISTENCE and run/corpus IDENTITY only. The
    review's disposition (ACCEPT / ACCEPT WITH CAVEATS / RECOMMEND STAGE
    2 REGENERATION) is advisory in this version and is never inspected
    here -- all three pass this check identically.

    Returns the artifact path when a review was required and finalized,
    else None. Raises RuntimeError if the artifact is missing.
    """
    if not review_was_required:
        return None

    model_assumptions_path = run_context.artifact_path("model_assumptions.md")
    if not os.path.exists(model_assumptions_path):
        raise RuntimeError(
            "The Quantitative Threat Modeler did not produce "
            f"{model_assumptions_path}."
        )
    run_context.stamp_prose_file(model_assumptions_path)
    run_context.read_stamped_prose(model_assumptions_path)
    return model_assumptions_path