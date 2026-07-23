# Vanguard Workbench

**Local-first threat modeling and human-governed assessment planning**

Vanguard Workbench is an agentic analysis pipeline for authorized Information Warfare, Red Team, and Purple Team assessment planning.

It uses locally hosted language models and deterministic Python tooling to turn an approved source corpus into structured threat analysis, assessment concepts, mission-planning artifacts, and defensive validation material.

> [!IMPORTANT]
> **Project status: Experimental / research prototype**
>
> This is a privately developed, independently maintained research project made publicly available for reference and collaboration.
>
> Interfaces, schemas, workflows, and generated artifacts may change as the project evolves.

> [!WARNING]
> Use Vanguard only on systems you own or are explicitly authorized to assess.
>
> Vanguard does not autonomously execute tests against a System Under Test. Human operators remain responsible for authorization, implementation, execution, safety, model review, and final assessment decisions.

## What Vanguard Does

Vanguard processes an approved source corpus through a staged assessment workflow:

```text
Assessment brief and approved sources
                ↓
        Frozen corpus verification
                ↓
        System and threat analysis
                ↓
       Attack-surface and graph analysis
                ↓
        Quantitative threat modeling
                ↓
       Human-reviewed test concepts
                ↓
      Human-reviewed mission planning
                ↓
       Final assessment artifacts
```

The pipeline combines:

* Local language models for analysis and drafting
* Deterministic validation and safety checks
* Run-scoped artifact storage
* Human approval gates
* Resume support for interrupted runs
* Optional Purple Team and dashboard workflows

Vanguard is a decision-support system:

> **Vanguard proposes, prioritizes, explains, and documents. Humans authorize, implement, execute, and decide.**

## Requirements

### Required

* macOS or Linux
* Python 3.12 is the currently tested version
* Git
* Ollama or another compatible local inference service
* Sufficient local memory for the selected models and source corpus

### Optional

* Docker with Docker Compose for the source-collection workflow
* A second terminal for monitoring active runs

Runtime depends on the selected models, available hardware, corpus size, context-window requirements, and generated output size.

## Installation

Clone the repository:

```bash
git clone https://github.com/colejv/vanguard-workbench.git
cd vanguard-workbench
```

Create and activate a virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

Upgrade the Python packaging tools:

```bash
python -m pip install --upgrade pip setuptools wheel
```

Install the project dependencies:

```bash
python -m pip install -r requirements.txt
```

Create the runtime directories:

```bash
mkdir -p sources outputs corpus-index
```

Confirm that the project imports successfully:

```bash
python -c "import src.crew; print('Vanguard imports successfully')"
```

Run all commands from the repository root.

## Configure a Local Model

Vanguard is designed to use locally hosted language models.

The core model configuration is stored in:

```text
config/llm.py
```

You may use the local model that best fits your hardware and assessment requirements.

The selected model should provide:

* Sufficient context capacity for the source corpus
* Reliable structured output
* Reliable tool calling
* Adequate reasoning performance
* Compatibility with the configured inference endpoint

For Ollama, install your selected model:

```bash
ollama pull <model-name>
```

Update the model name and endpoint in:

```text
config/llm.py
```

Confirm that Ollama is running:

```bash
ollama list
curl http://localhost:11434/api/tags
```

The configured model name must match the name reported by:

```bash
ollama list
```

Optional components may maintain separate local-model settings in their respective configuration files.

Model quality varies significantly. Generated analysis must be reviewed by a qualified operator before it is used for assessment planning or operational decisions.

## Prepare an Assessment

### 1. Edit the Assessment Brief

Open:

```text
collection/brief.md
```

For example:

```bash
nano collection/brief.md
```

The brief should identify:

* The System Under Test
* The assessment objective
* The authorizing authority
* Authorized assets and environments
* Explicit exclusions
* Prohibited actions or effects
* Collection priorities
* Required reviewers and approvers
* Abort and rollback requirements

Do not include credentials, classified data, export-controlled information, or sensitive operational material unless the workstation and repository are approved to handle it.

### 2. Add Approved Source Material

Place approved files in:

```text
sources/
```

Supported source types are:

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

Files beginning with `_` are treated as metadata and are not included in the analytical corpus.

For example:

```text
sources/_provenance.jsonl
```

Text-based PDFs can be processed directly. Scanned or image-only PDFs must be converted with an approved OCR process before they are added to the corpus.

## Freeze the Source Corpus

Vanguard requires a frozen manifest at:

```text
sources/corpus_manifest.md
```

The manifest binds the assessment to the exact source files and file hashes reviewed by the operator.

Run the following command from the repository root after adding or changing source files:

````bash
python - <<'PY'
import hashlib
import json
from pathlib import Path

source_dir = Path("sources")
source_dir.mkdir(parents=True, exist_ok=True)

supported = {".md", ".txt", ".json", ".pdf"}

files = sorted(
    path
    for path in source_dir.iterdir()
    if path.is_file()
    and path.suffix.lower() in supported
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

Review the generated manifest:

```bash
cat sources/corpus_manifest.md
```

Vanguard will refuse to begin the assessment when:

* The manifest is missing
* The manifest is malformed
* A listed source is missing
* A new source has been added
* A source file has changed
* A source file cannot be read

After intentionally changing the source corpus:

1. Review the changed material.
2. Regenerate `sources/corpus_manifest.md`.
3. Start a new assessment run.

Do not resume an older run against a changed corpus.

## Run the Preflight Check

Before starting an assessment, run:

```bash
python preflight_check.py
```

The preflight check validates the local project configuration without starting the full workflow or calling the language model.

Resolve any reported failures before beginning the assessment.

## Run Vanguard

Start a new assessment from the repository root:

```bash
python -m src.crew
```

Vanguard will print a run ID near the beginning of execution.

Example:

```text
Run ID: vaf_20260709_143022
```

All artifacts for that assessment are stored under:

```text
outputs/<run_id>/
```

The workflow contains interactive human-review prompts.

Do not approve a stage unless:

* The System Under Test is authorized
* The proposed activity is within scope
* The proposed effects are permitted
* Required owners and operators are available
* Abort authority has been assigned
* Rollback procedures are understood
* Required safety personnel have approved the activity

A generated plan is not execution authorization.

## Monitor a Running Assessment

Each run writes a heartbeat log:

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

Local model operations may take significant time, especially with large corpora or larger models.

## Resume an Interrupted Assessment

Resume a run with:

```bash
python -m src.crew --resume <run_id>
```

Example:

```bash
python -m src.crew --resume vaf_20260709_143022
```

Vanguard detects eligible completed artifacts and avoids repeating work that can be safely reused.

Human-reviewed stages may require fresh approval when resumed.

Vanguard refuses to resume when the current corpus differs from the corpus associated with the original run. Start a new assessment instead of forcing artifacts from different corpora into the same run.

List existing runs:

```bash
find outputs -maxdepth 1 -type d -name 'vaf_*' | sort
```

Inspect the files from a run:

```bash
find outputs/<run_id> -maxdepth 1 -type f | sort
```

## Assessment Outputs

Each assessment receives an isolated output directory:

```text
outputs/<run_id>/
```

Depending on how far the run progresses, the directory may contain:

* Assessment state and audit information
* Heartbeat logs
* Corpus snapshots and extracted chunks
* System-decomposition artifacts
* Attack-surface and graph artifacts
* Framework-validation results
* Quantitative threat-model reports
* Human-reviewed test concepts
* Mission-planning artifacts
* Safety-gate results
* Final assessment reports

Markdown files provide human-readable reports. JSON files provide structured artifacts used by later stages and deterministic validators.

Protect the following directories according to the sensitivity of the assessment:

```text
sources/
outputs/
corpus-index/
```

These files may reveal system architecture, trust relationships, defensive gaps, candidate attack paths, operational assumptions, or assessment procedures.

## Optional Source Collection

Vanguard includes an optional internet-connected source-collection workflow using a local SearXNG service.

Start SearXNG:

```bash
docker compose \
  -f collection/searxng/docker-compose.yml \
  up -d
```

Confirm that it is available:

```bash
curl http://localhost:8080
```

Run the collector:

```bash
python collection/collector.py collection/brief.md
```

The collector saves retained material under:

```text
sources/
```

Review every collected document before including it in an assessment.

After collection:

1. Remove irrelevant or unapproved material.
2. Review the retained sources.
3. Freeze the source corpus.
4. Run the preflight check.
5. Start a new assessment.

Stop SearXNG when collection is complete:

```bash
docker compose \
  -f collection/searxng/docker-compose.yml \
  down
```

SearXNG running locally does not make web collection offline, anonymous, or isolated. The collector still communicates with internet destinations.

## Optional Dashboard

The experimental Streamlit dashboard is located at:

```text
src/ui/dashboard.py
```

Start it from the repository root:

```bash
streamlit run src/ui/dashboard.py
```

The dashboard reads assessment data from run-specific directories under:

```text
outputs/
```

Some dashboard views require a completed assessment and generated Purple Team artifacts.

## Troubleshooting

### Import Errors

Confirm that the virtual environment is active:

```bash
source .venv/bin/activate
```

Confirm that you are in the repository root:

```bash
pwd
ls
```

Reinstall the dependencies:

```bash
python -m pip install -r requirements.txt
```

### Local Model Connection Errors

Check the local Ollama service:

```bash
curl http://localhost:11434/api/tags
ollama list
```

Confirm that the model names and endpoints in `config/llm.py` match the local service.

### Missing Corpus Manifest

Regenerate:

```text
sources/corpus_manifest.md
```

using the corpus-freeze command above.

### Corpus-Lock Failure

A source was added, removed, or changed after the corpus was frozen.

Review the changes, regenerate the manifest, and start a new assessment.

### Resume Refused

The current corpus does not match the corpus used by the original run.

Do not force the old run to continue. Start a new run:

```bash
python -m src.crew
```

### PDF Produces No Useful Text

The PDF may be scanned or image-only.

Use an approved OCR process, verify the extracted text, replace the source file, and regenerate the corpus manifest.

## Limitations

Vanguard is an active research prototype.

Local models may generate:

* Unsupported claims
* Incorrect system assumptions
* Incorrect framework mappings
* Inconsistent structured artifacts
* Overconfident conclusions
* Incomplete safety considerations

Deterministic validation reduces some failure modes but does not establish that generated analysis is correct, complete, safe, or operationally appropriate.

Graph scores, Bayesian outputs, threat rankings, and other quantitative results are decision-support artifacts. They are not objective ground truth and must be reviewed in the context of the source material, model assumptions, and analyst judgment.

The project has not been qualified for safety-critical or production deployment.

## Responsible Use

Use Vanguard only for:

* Authorized defensive research
* Authorized Red Team assessments
* Purple Team exercises
* Controlled test ranges
* Training environments
* Systems with explicit owner authorization

The operator is responsible for:

* Confirming written authorization
* Maintaining assessment boundaries
* Protecting sensitive inputs and outputs
* Reviewing generated claims
* Validating framework mappings
* Reviewing quantitative assumptions
* Approving test concepts
* Defining abort and rollback procedures
* Preventing unauthorized or unsafe execution

Vanguard does not grant authorization, replace professional judgment, or remove the need for qualified human review.
