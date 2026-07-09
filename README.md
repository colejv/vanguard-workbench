# Vanguard Workbench

**AI-augmented threat modeling and human-governed assessment planning**

Vanguard Workbench is a local-first, agentic analysis pipeline for authorized Information Warfare, Red Team, and Purple Team assessment planning.

It converts an approved source corpus into:

* Reverse IPB findings
* Structured system decomposition
* Framework-grounded attack vectors
* Kill Chain Attack Graph analysis
* Bayesian threat estimates
* Human-reviewed test concepts
* MDMP-style mission plans
* Defensive coverage and Sigma-rule scaffolds

Vanguard is a **decision-support system**. It does not autonomously execute tests against a System Under Test. Human operators remain responsible for authorization, model review, implementation, execution, safety, and final assessment decisions.

> [!WARNING]
> Use Vanguard only on systems you own or are explicitly authorized to assess.
>
> Generated findings, threat scores, test concepts, mission plans, and detection rules require qualified human review before operational use.

---

## Table of Contents

* [What Vanguard Does](#what-vanguard-does)
* [How the Pipeline Works](#how-the-pipeline-works)
* [System Requirements](#system-requirements)
* [Installation](#installation)
* [Model Setup](#model-setup)
* [Quick Start](#quick-start)
* [Prepare the Assessment Brief](#prepare-the-assessment-brief)
* [Add Source Material](#add-source-material)
* [Optional Source Collection](#optional-source-collection)
* [Freeze the Corpus](#freeze-the-corpus)
* [Run an Assessment](#run-an-assessment)
* [Monitor a Running Assessment](#monitor-a-running-assessment)
* [Resume an Interrupted Assessment](#resume-an-interrupted-assessment)
* [Assessment Outputs](#assessment-outputs)
* [Pipeline Stages](#pipeline-stages)
* [Purple Team Workflow](#purple-team-workflow)
* [Dashboard](#dashboard)
* [Testing](#testing)
* [Security Considerations](#security-considerations)
* [Current Limitations](#current-limitations)
* [Troubleshooting](#troubleshooting)
* [Repository Layout](#repository-layout)
* [Responsible Use](#responsible-use)

---

## What Vanguard Does

Vanguard helps an authorized assessment team answer four questions:

1. Where should we test first?
2. Why is that path important?
3. How should the test be controlled?
4. What should defenders observe and measure?

The project combines local language models with deterministic Python tools.

AI agents organize evidence, build structured analysis, and draft planning artifacts. Deterministic tools perform corpus verification, framework-ID validation, graph calculations, Bayesian inference, artifact hashing, and safety-language checks.

The intended operating model is:

> **Vanguard proposes, prioritizes, explains, and documents. Humans authorize, implement, execute, and decide.**

---

## How the Pipeline Works

```text
Approved source corpus
        ↓
Corpus lock verification
        ↓
Stage 0 — Reverse IPB
        ↓
Stage 1 — System decomposition
        ↓
Stage 2 — Attack-surface mapping
        ↓
Deterministic framework verification
        ↓
Annex B — Kill Chain Attack Graph
        ↓
Annex C — Bayesian threat model
        ↓
Stage 3 — Human-reviewed test concepts
        ↓
Deterministic pre-Stage-4 safety gate
        ↓
Stage 4 — MDMP-style mission plan
        ↓
Final defense-in-depth safety check
        ↓
Purple Team defensive validation
```

Vanguard currently uses:

* **CrewAI** for multi-agent orchestration
* **Ollama** for local model inference
* **Pydantic** for structured artifacts
* **NetworkX** for KCAG analysis
* **pgmpy** for Bayesian inference
* **SearXNG** for optional locally brokered web search
* **Streamlit** for the experimental dashboard

---

## System Requirements

### Required

* macOS or Linux
* Python 3.12 or newer
* Git
* Ollama
* Sufficient local memory for the configured models

### Optional

* Docker with Docker Compose for the SearXNG collection workflow
* A second terminal for monitoring the heartbeat log

### Hardware considerations

The reasoning model is a 27-billion-parameter local model. Runtime depends heavily on:

* Available RAM or unified memory
* Model quantization
* CPU or GPU acceleration
* Corpus size
* Number of generated graph nodes and edges

Large Stage 1, Stage 2, and Annex C generations may take substantially longer than simple extraction tasks.

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/colejv/vanguard-workbench.git
cd vanguard-workbench
```

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

On Windows PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Upgrade the packaging tools

```bash
python -m pip install --upgrade pip setuptools wheel
```

### 4. Install the project dependencies

```bash
python -m pip install -r requirements.txt
```

This installs all required dependencies, including `pypdf` for PDF source ingestion.

### 5. Create the runtime directories

```bash
mkdir -p sources outputs corpus-index
```

### 6. Verify the Python import path

Run this command from the repository root:

```bash
python -c "import src.crew; print('Vanguard imports successfully')"
```

---

## Model Setup

Start Ollama using the normal method for your operating system.

### Core analysis models

The current core pipeline uses:

* `gemma4:e4b` for lightweight extraction
* `qwen3.6:27b` for reasoning, structured output, and tool execution

Install them:

```bash
ollama pull gemma4:e4b
ollama pull qwen3.6:27b
```

### Optional collection and Sigma model

The current collection query planner and Sigma generator still reference:

```text
gemma4:12b-mlx
```

Install it when using those optional components:

```bash
ollama pull gemma4:12b-mlx
```

### Verify the models

```bash
ollama list
```

Verify the Ollama API:

```bash
curl http://localhost:11434/api/tags
```

The core model configuration is stored in:

```text
config/llm.py
```

The default endpoints are:

```text
OpenAI-compatible endpoint: http://localhost:11434/v1
Native Ollama endpoint:     http://localhost:11434
```

---

## Quick Start

After installation and model setup:

````bash
# 1. Edit the authorized assessment brief
$EDITOR collection/brief.md

# 2. Add approved sources
cp /path/to/approved/material.md sources/
cp /path/to/approved/manual.pdf sources/

# 3. Freeze the corpus
python - <<'PY'
import hashlib
import json
from pathlib import Path

source_dir = Path("sources")
extensions = {".md", ".txt", ".json", ".pdf"}

files = sorted(
    path
    for path in source_dir.iterdir()
    if path.is_file()
    and path.suffix.lower() in extensions
    and not path.name.startswith("_")
    and path.name != "corpus_manifest.md"
)

manifest = {
    "files": [
        {
            "file": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in files
    ]
}

manifest_path = source_dir / "corpus_manifest.md"
manifest_path.write_text(
    "# Frozen Corpus Manifest\n\n"
    "This manifest binds the assessment to the exact files listed below.\n\n"
    "```json\n"
    + json.dumps(manifest, indent=2)
    + "\n```\n",
    encoding="utf-8",
)

print(f"Wrote {manifest_path}")
print(f"Locked {len(files)} source files")
PY

# 4. Run Vanguard
python -m src.crew
````

Vanguard prints the new run ID near the beginning of execution.

Example:

```text
Run ID: vaf_20260709_143022
```

All assessment artifacts are written under:

```text
outputs/<run_id>/
```

---

## Prepare the Assessment Brief

Edit:

```text
collection/brief.md
```

The brief should define the friendly System Under Test and the authorized assessment boundaries.

Recommended structure:

```markdown
# Assessment Brief

## System Under Test

- Name or designation:
- System type:
- Owner:
- Vendor:
- Mission or business purpose:
- High-level architecture:

## Assessment Purpose

- Assessment objective:
- Questions to answer:
- Intended audience:
- Required deliverables:

## Authorization

- Authorizing authority:
- Authorization reference:
- Authorized assets:
- Authorized environments:
- Authorized dates:
- Expiration date:

## Explicit Exclusions

- Out-of-scope systems:
- Prohibited actions:
- Prohibited effects:
- Restricted data:
- Restricted collection areas:

## Collection Priorities

- Technical:
- Procedural:
- Organizational:
- Cognitive:
- Defensive telemetry:
- Relevant threat actors:

## Safety Requirements

- Required approvers:
- Range or test-environment owner:
- Abort authority:
- Rollback requirements:
- Emergency contacts:
- Additional physical-safety restrictions:
```

Do not place credentials, classified data, export-controlled information, or sensitive operational material in the repository unless the system and workstation are approved to handle it.

---

## Add Source Material

Place approved files in:

```text
sources/
```

Supported extensions are:

```text
.md
.txt
.json
.pdf
```

Example:

```bash
cp ~/Documents/system-architecture.md sources/
cp ~/Documents/vendor-manual.pdf sources/
cp ~/Documents/exercise-report.txt sources/
```

Files beginning with `_` are treated as metadata and excluded from the analytical corpus.

Examples:

```text
sources/_provenance.jsonl
```

The frozen manifest is also excluded:

```text
sources/corpus_manifest.md
```

### PDF requirements

Text-based PDFs are extracted with `pypdf`.

Scanned or image-only PDFs must be processed with an approved OCR workflow before ingestion. Confirm that text can be extracted before freezing the corpus.

---

## Optional Source Collection

Vanguard includes an optional open-web collection workflow using a local SearXNG service.

> [!CAUTION]
> The collection workflow is internet-connected.
>
> SearXNG runs locally, but the collector retrieves selected destination webpages directly. Local SearXNG does not make collection offline, anonymous, or fully isolated.

### 1. Start SearXNG

From the repository root:

```bash
docker compose \
  -f collection/searxng/docker-compose.yml \
  up -d
```

Confirm that the service is available:

```bash
curl http://localhost:8080
```

Check container status:

```bash
docker compose \
  -f collection/searxng/docker-compose.yml \
  ps
```

### 2. Install the collection model

The current query planner uses `gemma4:12b-mlx`:

```bash
ollama pull gemma4:12b-mlx
```

### 3. Run the collector

```bash
python collection/collector.py collection/brief.md
```

The collector:

* Generates bounded search queries
* Queries the local SearXNG instance
* Retrieves candidate webpages
* Scores document relevance
* Saves retained documents under `sources/`
* Appends provenance records to `sources/_provenance.jsonl`

The collector currently uses hard limits for:

* Query expansion depth
* Total searches
* Retained documents
* Minimum relevance

Review all collected material before freezing the corpus.

### 4. Stop SearXNG

```bash
docker compose \
  -f collection/searxng/docker-compose.yml \
  down
```

### Collection security recommendations

For sensitive assessments:

* Run collection separately from analysis.
* Use a restricted container or virtual machine.
* Route traffic through an approved proxy.
* Apply outbound network controls.
* Block private, loopback, link-local, and metadata-service addresses.
* Review redirects and destination domains.
* Inspect all collected documents before transferring them into the analysis environment.

---

## Freeze the Corpus

Vanguard refuses to start Stage 0 unless the corpus matches:

```text
sources/corpus_manifest.md
```

The manifest must contain a JSON block listing every source filename and SHA-256 hash.

### Create the manifest

Run from the repository root:

````bash
python - <<'PY'
import hashlib
import json
from pathlib import Path

source_dir = Path("sources")
extensions = {".md", ".txt", ".json", ".pdf"}

source_dir.mkdir(parents=True, exist_ok=True)

files = sorted(
    path
    for path in source_dir.iterdir()
    if path.is_file()
    and path.suffix.lower() in extensions
    and not path.name.startswith("_")
    and path.name != "corpus_manifest.md"
)

manifest = {
    "files": [
        {
            "file": path.name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in files
    ]
}

manifest_path = source_dir / "corpus_manifest.md"
manifest_path.write_text(
    "# Frozen Corpus Manifest\n\n"
    "This manifest binds the assessment to the exact source files listed below.\n\n"
    "```json\n"
    + json.dumps(manifest, indent=2)
    + "\n```\n",
    encoding="utf-8",
)

print(f"Wrote {manifest_path}")
print(f"Locked {len(files)} source files")
PY
````

Review it:

```bash
cat sources/corpus_manifest.md
```

### Corpus-lock behavior

Before Stage 0, Vanguard re-hashes the current source files.

The run fails closed when:

* The manifest is missing
* The JSON block is malformed
* A source file is missing
* A new source was added
* A source file changed
* A source cannot be read

After intentionally changing the corpus:

1. Review the new or changed material.
2. Regenerate `sources/corpus_manifest.md`.
3. Start a new assessment run.

Do not resume an older run against a changed corpus.

---

## Run an Assessment

From the repository root:

```bash
python -m src.crew
```

The pipeline will:

1. Discover the current corpus.
2. Create or reuse a versioned corpus snapshot.
3. Generate a unique run ID.
4. Create a run-specific output directory.
5. Initialize `assessment_state.json`.
6. Verify the frozen corpus manifest.
7. Request human confirmation of the corpus lock.
8. Read and chunk the source corpus.
9. Extract named systems, interfaces, organizations, people, and events.
10. Generate Stage 0 Reverse IPB.
11. Generate Stage 1 system decomposition.
12. Generate Stage 2 attack vectors and graph topology.
13. Verify Stage 2 framework identifiers.
14. Halt if Stage 2 verification fails.
15. Run Annex B KCAG analysis.
16. Run Annex C Bayesian inference.
17. Request human review for Stage 3.
18. Run the deterministic pre-Stage-4 safety gate. Halt before Stage 4 is even constructed if it fails.
19. Request human review for Stage 4 — only reached if the gate above passed.
20. Run the final defense-in-depth Phase 0 safety-language check.
21. Preserve the artifacts in the run directory.

### Human-input prompts

Vanguard currently requests human input at:

* Corpus-lock confirmation
* Stage 3 authorization
* Stage 4 mission-plan release

Stage 4's prompt is only reached if the deterministic pre-Stage-4 safety gate passed — a Category 2/3 test concept without a complete safety review halts the run before a human ever sees a Stage 4 draft.

Do not approve a stage unless:

* The System Under Test is authorized.
* The assets are within the approved scope.
* The proposed effects are permitted.
* The required owners and operators are present.
* Abort authority is assigned.
* Rollback procedures are understood.
* Required safety personnel have approved the activity.

---

## Monitor a Running Assessment

Each run writes a heartbeat log to:

```text
outputs/<run_id>/heartbeat.log
```

Follow it from another terminal:

```bash
tail -f outputs/<run_id>/heartbeat.log
```

Example:

```bash
tail -f outputs/vaf_20260709_143022/heartbeat.log
```

The heartbeat log labels each phase by name — `pre_crew` (Stage 0-2), `analysis_crew` (Annex B, Annex C, Stage 3), and `stage4_crew` (Stage 4 alone) — so it indicates which specific crew is still active during long local-model operations, not just "still running somewhere."

---

## Resume an Interrupted Assessment

Resume an existing run with:

```bash
python -m src.crew --resume <run_id>
```

Example:

```bash
python -m src.crew --resume vaf_20260709_143022
```

Vanguard detects completed artifacts and can skip eligible completed work, including:

* Corpus chunking
* Stage 0
* Stage 1
* Stage 2
* Annex B
* Annex C

Stage 3 and Stage 4 are intentionally executed again because they contain human approval prompts.

### Resume safety

Vanguard refuses to resume when the current corpus snapshot differs from the corpus associated with the original run.

This prevents artifacts from two different corpora from being mixed under the same run ID.

### Find existing runs

```bash
find outputs -maxdepth 1 -type d -name 'vaf_*' | sort
```

Inspect a run:

```bash
find outputs/<run_id> -maxdepth 1 -type f | sort
```

---

## Assessment Outputs

Each assessment receives its own directory:

```text
outputs/<run_id>/
```

Example:

```text
outputs/vaf_20260709_143022/
├── assessment_state.json
├── heartbeat.log
├── corpus_chunks.json
├── corpus_lock_confirmation.md
├── _stage0_scratch.md
├── stage0.md
├── stage0_output.json
├── stage1.md
├── stage1_output.json
├── attribution_check.md
├── stage2.md
├── stage2_vectors.json
├── stage2_verification.md
├── annexB_kcag.md
├── kcag_report.json
├── annexC_bbn.md
├── bbn_report.json
├── stage3.md
├── stage3_safety_gate.json
├── stage4_mission_plan.md
└── phase0_safety_check.md
```

The exact set of files depends on how far the run progressed.

### Artifact isolation

Per-run tools resolve their paths through the active run context.

Structured JSON and Markdown artifacts are stamped with run and corpus identity information. This reduces the risk of accidentally accepting an artifact from another run.

### Shared corpus history

The following directory is intentionally shared across runs:

```text
corpus-index/
```

It records corpus versions and framework indexes rather than assessment-specific artifacts.

---

## Pipeline Stages

### Pre-flight corpus snapshot

Vanguard hashes all supported source files and compares the result with earlier corpus snapshots.

Versioned snapshots are written under:

```text
corpus-index/manifest_vN.json
```

This snapshot tracks corpus changes across assessments.

It is separate from the operator-approved frozen manifest:

```text
sources/corpus_manifest.md
```

### Corpus lock gate

The deterministic corpus-lock gate verifies that the current files match the frozen source manifest before Stage 0 begins.

The result is also presented to a human reviewer through the first CrewAI approval prompt.

### Chunking and extraction

The corpus is assembled into chunks of approximately 60,000 characters.

The decomposer extracts:

* Named systems
* Subsystems
* Vendor products
* Interfaces
* Protocols
* Versions
* Exercise events
* Named people
* Organizations

The extracted findings are accumulated in:

```text
_stage0_scratch.md
```

### Stage 0 — Reverse IPB

Stage 0 synthesizes technical, procedural, cognitive, and social or personnel signatures.

Outputs:

```text
stage0.md
stage0_output.json
```

The structured output contains a curated set of significant signatures with:

* Signature IDs
* Categories
* Descriptions
* Confidence levels
* Gap markers
* Deception-candidate markers

### Stage 1 — System decomposition

Stage 1 models:

* Technical components
* Procedural workflows
* Cognitive dependencies
* Asset-control states
* Information flows
* Downstream dependencies
* Trust boundaries
* Centers-of-gravity candidates

Outputs:

```text
stage1.md
stage1_output.json
```

### Attribution-boundary check

After Stage 0 and Stage 1, Vanguard checks whether named entities in the generated prose can be traced to:

1. The extraction scratchpad
2. The locked source corpus

Output:

```text
attribution_check.md
```

The attribution check is currently advisory. High-confidence untraceable entities are reported for human review but do not automatically halt the run.

### Stage 2 — Attack-surface mapping

Stage 2 maps candidate vectors against the local framework index.

It can reference identifiers from frameworks such as:

* MITRE ATT&CK Enterprise
* MITRE ATT&CK ICS
* MITRE ATT&CK Mobile
* MITRE ATLAS
* CAPEC
* EMB3D
* SPARTA
* MITRE Engage

Outputs:

```text
stage2.md
stage2_vectors.json
stage2_verification.md
```

The structured Stage 2 artifact contains graph nodes and edges used by Annex B.

### Stage 2 verification gate

A deterministic verifier checks generated technique identifiers against:

```text
corpus-index/technique_index.json
```

When verification fails:

* Stage 2 is marked as failed.
* Annex B does not run.
* Downstream stages are blocked.

Review:

```text
stage2_verification.md
```

### Annex B — Kill Chain Attack Graph

Annex B reads the Stage 2 graph artifact and uses NetworkX to calculate:

* Graph size
* Goal nodes
* Minimum node cuts
* Betweenness centrality
* Candidate attack paths
* A priority path

Outputs:

```text
annexB_kcag.md
kcag_report.json
```

> [!IMPORTANT]
> The current KCAG path values are heuristic traversal scores based on fixed difficulty mappings.
>
> They are useful for relative ranking but are not empirically calibrated real-world probabilities.

### Annex C — Bayesian threat model

Annex C uses pgmpy to build a Bayesian model from:

* Annex B results
* An adversary capability prior
* Assessed operational tempo
* Defensive posture
* A geopolitical trigger prior
* Optional observed evidence
* Structural priors from `config/bbn_priors.json`

Outputs:

```text
annexC_bbn.md
bbn_report.json
```

The BBN refuses to use silent per-assessment defaults for required inputs.

The priors file currently contains several analyst-judgment template values. These are not empirically calibrated for a specific assessment and must be reviewed before relying on the resulting scores.

A Bayesian result is conditional on:

* The model structure
* The supplied priors
* The conditional probability tables
* The observed evidence
* The analyst assumptions

It should not be treated as objective ground truth.

### Quantitative Threat Modeler

Annex B and Annex C are both executed by the Quantitative Threat Modeler agent.

The agent runs Vanguard's deterministic KCAG and Bayesian-analysis tools (`kcag_min_cut`, `bbn_threat_score`). It does not author the Stage 2 graph topology, and it may not invent priors, conditional probability values, or observed evidence. Required per-assessment inputs for Annex C (adversary capability, tempo, defensive posture, geopolitical trigger, observed evidence) must trace to an approved assessment input or an explicitly labeled analyst judgment — an untraceable required value is reported as a blocking gap, not filled in with a plausible number.

The agent also distinguishes deterministic calculations from configured heuristic scores. The current KCAG path-ranking value in particular is a configured heuristic (fixed difficulty-to-value mappings multiplied along a path), not a calibrated, empirically-derived probability, even where legacy field names or phrasing elsewhere may still call it one.

Mathematical consistency does not establish that a model accurately represents the real system. KCAG and BBN results require review by both a quantitative specialist and a system-domain expert.

> [!NOTE]
> This agent does not yet perform semantic validation of the KCAG graph itself (structural correctness, reachability, cycle detection beyond what NetworkX reports). That capability is planned as a separate, read-only `validate_kcag` addition — see [Current Limitations](#current-limitations).

### Stage 3 — Human-reviewed test concepts

Stage 3 reviews the verified attack vectors and Annex B priority path.

It drafts categorized test concepts for human review. For any test concept carrying Category 2 (Degradation & Destruction) or Category 3 (Physical Behavior Alteration), Stage 3 is required to include a complete `PRE-STAGE-4 SAFETY REVIEW` section: affected assets, required approving roles, safety authority, abort authority, abort criteria, maximum termination time, rollback procedure, and an explicit release condition. When no Category 2/3 concepts exist, Stage 3 must instead state so explicitly — silence is never treated as compliant.

Output:

```text
stage3.md
```

Stage 3 requires human input.

The human reviewer remains responsible for determining whether each concept is:

* Authorized
* Technically grounded
* Safe
* Within scope
* Appropriate for the actual system architecture

### Pre-Stage-4 safety gate

Before Stage 4 is even constructed, Vanguard deterministically checks the stamped, verified Stage 3 artifact for the safety-review requirement above.

Output:

```text
stage3_safety_gate.json
```

A noncompliant result halts the run immediately. Stage 4 is never built and the Stage 4 human-approval prompt is never reached — this is the actual enforcement point for Stage 3's safety-review requirement, not the final check described below.

### Stage 4 — MDMP-style mission plan

Stage 4 produces a phased mission plan containing:

* Planned actions
* Framework mappings
* Execution sequencing
* OPSEC measures
* Blue Team telemetry requirements
* Detection criteria
* Safety-gate language where required

Output:

```text
stage4_mission_plan.md
```

Stage 4 requires human input. This prompt is only reached if the pre-Stage-4 safety gate above passed.

### Final defense-in-depth safety check

After Stage 4 completes, Vanguard runs a second, independent check confirming the generated mission plan carries forward the required Phase 0 safety-gate language and does not contradict the already-approved Stage 3 assessment.

Output:

```text
phase0_safety_check.md
```

A noncompliant result prevents the run from completing successfully.

> [!WARNING]
> This second check runs after the Stage 4 human-input prompt, so it cannot intercept that approval — it can prevent the run from finalizing, but a human will have already seen and approved the Stage 4 draft by the time it runs.
>
> The pre-Stage-4 gate above is the check that actually runs before that prompt. This one exists as defense in depth: it also catches the case where Stage 3 and Stage 4 directly contradict each other (e.g. Stage 3 declares Category 2/3 concepts but Stage 4 claims none apply).

---

## Purple Team Workflow

Vanguard includes a separate Purple Team workflow for:

* Parsing the Stage 4 plan
* Extracting ATT&CK technique identifiers
* Crosswalking them with Atomic Red Team
* Identifying coverage gaps
* Creating defensive scaffolds
* Generating draft Sigma rules

### Current run-isolation compatibility step

The Purple Team scripts currently read legacy flat paths under `outputs/`, while the main assessment pipeline now writes Stage 4 under `outputs/<run_id>/`.

Select the run you want to process:

```bash
export VANGUARD_RUN_ID=vaf_20260709_143022
```

Copy its Stage 4 plan to the current Purple Team compatibility path:

```bash
cp \
  "outputs/${VANGUARD_RUN_ID}/stage4_mission_plan.md" \
  outputs/stage4_mission_plan.md
```

### Run the Purple Team compiler

```bash
python src/purple/purple_compiler.py
```

The compiler currently:

* Downloads or loads a cached Atomic Red Team index
* Parses Stage 4 phases
* Extracts ATT&CK and CAPEC identifiers
* Marks published Atomic Red Team coverage
* Flags coverage gaps
* Writes dashboard artifacts

Outputs:

```text
outputs/purple_scaffold.json
outputs/kcag_data.json
```

The Atomic Red Team index is cached at:

```text
corpus-index/art_index.json
```

### Generate Sigma-rule scaffolds

The current Sigma generator uses:

```text
gemma4:12b-mlx
```

Install it first:

```bash
ollama pull gemma4:12b-mlx
```

Then run:

```bash
python src/purple/sigma_generator.py
```

Outputs are written under:

```text
outputs/sigma_rules/
```

Generated rules are scaffolds, not production-ready detections.

Before deployment, validate:

* Sigma syntax
* Log-source availability
* Field mappings
* SIEM backend compatibility
* False-positive behavior
* Expected event volume
* Detection latency
* Test-case coverage

---

## Dashboard

The experimental Streamlit dashboard is located at:

```text
src/ui/dashboard.py
```

Start it from the repository root:

```bash
streamlit run src/ui/dashboard.py
```

The dashboard contains views for:

* Threat surface
* Purple Team coverage
* Defensive validation

The dashboard currently expects the legacy Purple Team output files under the root `outputs/` directory.

Run the Purple Team compiler and Sigma generator before expecting all dashboard views to contain data.

---

## Testing

Activate the virtual environment:

```bash
source .venv/bin/activate
```

Run the test suite:

```bash
pytest -q
```

Run an import smoke test:

```bash
python -c "import src.crew"
```

The current test suite includes coverage for:

* Pydantic schemas
* Stage 0 and Stage 1 schemas
* Assessment state behavior
* Stage 0 and Stage 1 tools
* Crew and state integration

The live model pipeline is significantly more expensive and less deterministic than the unit tests. Use mocked or fixture-based tests for routine development wherever practical.

---

## Security Considerations

### Vanguard is not an autonomous execution platform

The core pipeline generates analysis and planning artifacts.

It does not, by itself, establish:

* Legal authority
* Rules of engagement
* System-owner approval
* Safety approval
* Technical correctness
* Operational feasibility

Those remain human responsibilities.

### Local inference does not mean the entire project is offline

The core analysis models run through local Ollama endpoints.

However, network access may still occur during:

* Package installation
* Model installation
* Optional web collection
* Atomic Red Team index retrieval
* Repository updates

### Collection content is untrusted

External webpages and documents may contain:

* Incorrect information
* Fabricated identifiers
* Prompt-injection attempts
* Misleading instructions
* Hidden or malformed content

Treat source documents as evidence, not as trusted agent instructions.

### Review generated artifacts

LLMs can produce:

* Unsupported claims
* Incorrect architecture assumptions
* Incorrect framework mappings
* Internally inconsistent plans
* Overconfident conclusions

Deterministic validation reduces some failure modes but does not eliminate the need for expert review.

### Protect sensitive artifacts

Assessment outputs may disclose:

* System architecture
* Trust relationships
* Defensive gaps
* Candidate attack paths
* Operational procedures
* Safety assumptions

Protect `sources/`, `outputs/`, and `corpus-index/` according to the sensitivity of the assessment.

---

## Current Limitations

Vanguard is an active research prototype.

Current limitations include:

* There is no dedicated semantic KCAG-review task between Stage 2 and Annex B.
* Annex B currently selects the first zero-indegree graph source rather than strictly requiring `ADV_START`.
* KCAG traversal values are still labeled as probabilities internally.
* The BBN contains analyst-judgment template priors that require case-specific review.
* BBN sensitivity analysis is not yet implemented.
* Stage 3 remains a free-form Markdown artifact.
* There is no deterministic Stage 3 test-plan validator for general structure (Test ID, Objective, Stage 2 vector, KCAG path, success/abort criteria as a whole) — only the pre-Stage-4 safety-review fields are deterministically checked.
* The final defense-in-depth safety check still runs after the Stage 4 human-input prompt, so it cannot intercept that specific approval (the pre-Stage-4 gate is what actually runs before it, and does intercept).
* The attribution-boundary check is advisory rather than blocking.
* The optional collector still uses `gemma4:12b-mlx`, while the core reasoning agents use `qwen3.6:27b`.
* The Purple Team tools still use flat compatibility paths under `outputs/`.
* The Purple Team compiler retrieves the Atomic Red Team index from the internet.
* The project has not been qualified for safety-critical or operational deployment.

---

## Troubleshooting

### `ModuleNotFoundError`

Confirm that commands are being run from the repository root:

```bash
pwd
ls
```

The directory should contain:

```text
src/
collection/
config/
requirements.txt
```

Activate the environment:

```bash
source .venv/bin/activate
```

Reinstall dependencies:

```bash
python -m pip install -r requirements.txt
```

### Ollama connection failure

Check the API:

```bash
curl http://localhost:11434/api/tags
```

List installed models:

```bash
ollama list
```

Install the core models:

```bash
ollama pull gemma4:e4b
ollama pull qwen3.6:27b
```

Install the optional collection and Sigma model:

```bash
ollama pull gemma4:12b-mlx
```

### Model not found

Compare the names shown by:

```bash
ollama list
```

with:

```text
config/llm.py
collection/collector.py
src/purple/sigma_generator.py
```

The model name must match exactly.

### PDF source produces no useful text

If a PDF fails to ingest or produces no extractable text, first confirm dependencies are current:

```bash
python -m pip install -r requirements.txt
python -c "from pypdf import PdfReader; print('pypdf ready')"
```

If `pypdf` is present and text extraction still fails, the PDF is most likely image-only or scanned. Use an approved OCR process before adding it to the corpus, then regenerate the frozen manifest.

### `corpus_manifest.md not found`

The corpus has not been frozen.

Create:

```text
sources/corpus_manifest.md
```

using the command in [Freeze the Corpus](#freeze-the-corpus).

### Corpus lock violation

One or more source files changed after the corpus was frozen.

The error will identify:

* Missing files
* Added files
* Changed files

Review the changes, regenerate the manifest, and start a new run.

### Resume refused because the corpus changed

Do not force the old run to continue.

Start a new assessment:

```bash
python -m src.crew
```

### Stage 2 verification failure

Review:

```text
outputs/<run_id>/stage2_verification.md
```

Look for:

* Invalid framework identifiers
* Unsupported mappings
* Gap markers
* Malformed vectors
* Missing graph fields

Correct the source data, prompt, index, or mapping behavior before resuming.

### Annex B fails

Confirm that this file exists and is valid:

```text
outputs/<run_id>/stage2_vectors.json
```

Review:

```text
outputs/<run_id>/stage2_verification.md
```

Annex B should not be bypassed by manually inventing a replacement graph.

### Annex C fails

Confirm that these files exist:

```text
outputs/<run_id>/kcag_report.json
config/bbn_priors.json
```

Review the error for missing per-assessment fields such as:

* `adversary.capability_prior`
* `adversary.tempo`
* `defensive_posture`
* `geopolitical_trigger_prior`

### Phase 0 safety check fails

Review:

```text
outputs/<run_id>/phase0_safety_check.md
```

Do not satisfy the checker by adding keywords without completing the underlying safety, authorization, abort, and rollback review.

### Purple Team compiler cannot find Stage 4

Copy the selected run's Stage 4 plan into the current compatibility path:

```bash
export VANGUARD_RUN_ID=<run_id>

cp \
  "outputs/${VANGUARD_RUN_ID}/stage4_mission_plan.md" \
  outputs/stage4_mission_plan.md
```

Then run:

```bash
python src/purple/purple_compiler.py
```

### Dashboard is empty

Confirm that the Purple Team artifacts exist:

```bash
ls -l outputs/purple_scaffold.json
ls -l outputs/kcag_data.json
find outputs/sigma_rules -type f
```

Then start:

```bash
streamlit run src/ui/dashboard.py
```

---

## Repository Layout

```text
vanguard-workbench/
├── collection/
│   ├── brief.md
│   ├── collector.py
│   └── searxng/
│       ├── config/
│       └── docker-compose.yml
├── config/
│   ├── bbn_priors.json
│   └── llm.py
├── corpus-index/
│   ├── technique_index.json
│   └── manifest_vN.json
├── outputs/
│   └── <run_id>/
├── sources/
│   ├── corpus_manifest.md
│   └── _provenance.jsonl
├── src/
│   ├── agents.py
│   ├── crew.py
│   ├── heartbeat.py
│   ├── run_context.py
│   ├── schemas.py
│   ├── state.py
│   ├── tasks.py
│   ├── tools.py
│   ├── purple/
│   │   ├── purple_compiler.py
│   │   └── sigma_generator.py
│   └── ui/
│       ├── dashboard.py
│       ├── components/
│       └── utils/
├── tests/
└── requirements.txt
```

---

## Responsible Use

Use Vanguard only for:

* Authorized defensive research
* Red Team assessments
* Purple Team exercises
* Controlled test ranges
* Training environments
* Systems with explicit written owner authorization

The operator is responsible for:

* Written authorization
* Scope control
* Legal compliance
* Rules of engagement
* Safety controls
* Data classification and handling
* Source review
* Model-assumption review
* Test implementation
* Test execution
* Abort procedures
* Rollback procedures
* Defensive validation
* Final operational decisions

Do not use generated material to access, disrupt, degrade, manipulate, or damage systems without explicit authorization from the system owner.

---

## Project Status

Vanguard Workbench is an advanced research prototype.

The current development priorities are:

* Add deterministic KCAG semantic validation for the Quantitative Threat Modeler to consume (role upgrade and analytical-discipline prompts already in place; the validator itself is not yet built)
* Rename heuristic KCAG probabilities
* Add BBN validation and sensitivity analysis
* Convert Stage 3 into structured test-plan drafting
* Add a general-purpose Stage 3 test-plan structure validator (Test ID, Objective, Stage 2 vector, KCAG path, success/abort criteria) — separate from the pre-Stage-4 safety-review gate, which only checks Category 2/3 safety fields
* Update Purple Team tools to consume run-scoped artifacts directly

The project's intended direction is:

> **Evidence-backed analysis, deterministic calculation, explicit uncertainty, human authorization, and controlled external execution.**