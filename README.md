# Vanguard Workbench: Autonomous Information Warfare Analysis

Vanguard Workbench is an agentic AI pipeline designed for Information Warfare (IW) analysis, Reverse Intelligence Preparation of the Battlefield (IPB), and Red Team mission planning against friendly Systems Under Test (SUT). 

Powered by CrewAI and local MLX-optimized LLMs, Vanguard completely isolates the analytical environment from the public internet to maintain OPSEC. It ingests unstructured intelligence, maps system architectures to adversarial frameworks (MITRE ATT&CK, ATLAS, EMB3D, SPARTA), computes mathematical threat probabilities via Bayesian Belief Networks (BBN), and outputs actionable Military Decision Making Process (MDMP) payload designs.

## System Requirements
* **OS:** macOS (Optimized for Apple Silicon / M-Series Unified Memory)
* **Python:** 3.12+
* **Local LLM Engine:** [Ollama](https://ollama.com/)
* **Containerization:** Docker Desktop (for local SearXNG collection)

## Core Architecture
* **Orchestration:** CrewAI (Sequential Process)
* **Reasoning Engine:** `gemma4:12b-mlx` (Tool execution, Pydantic validation, synthesis)
* **Extraction Engine:** `gemma4:e4b` (Fast, high-temperature document decomposition)
* **Graph/Math:** `NetworkX` (KCAG Min-Cut paths), `pgmpy` (Discrete BBN Scoring)

---

## 1. Installation & Setup

### Clone and Isolate
```bash
git clone [https://github.com/YOUR_USERNAME/vanguard-workbench.git](https://github.com/YOUR_USERNAME/vanguard-workbench.git)
cd vanguard-workbench
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

```

### Configure Local Models

Vanguard relies entirely on local inference to prevent data leakage of sensitive SUT architectures. Ensure Ollama is running, then pull the required models:

```bash
ollama pull gemma4:e4b
ollama pull gemma4:12b-mlx

```

---

## 2. Phase 1: OPSEC-Safe Collection & Research

Before analyzing a system, you must gather Open Source Intelligence (OSINT) and structure the intelligence requirements. Vanguard uses a local instance of SearXNG to prevent fingerprinting or search-engine tracking during the collection phase.

### Step 2A: Spin up SearXNG

Navigate to the collection directory and start the Docker container:

```bash
cd collection/searxng
docker-compose up -d

```

*SearXNG is now running locally on `http://localhost:8080`.*

### Step 2B: Define the Assessment Brief (Target SUT)

Open `collection/brief.md`. This file acts as the single source of truth for the entire operation. Define your System Under Test (SUT) designation, the vendor, and specific collection priorities.

### Step 2C: Execute Autonomous Collection
Run the collector script to query the local SearXNG instance for technical documentation, vendor whitepapers, and exercise reports regarding the SUT. It will read your `brief.md`, autonomously generate iterative search queries using Gemma 4, scrape the results via SearXNG, score them for relevance, and save the best documents to the corpus.

```bash
cd ..
python collection/collector.py collection/brief.md

```

* Saves the downloaded PDF, TXT, or MD reports directly into the root `sources/` directory.
* A provenance log is automatically generated at `sources/_provenance.jsonl` to track the origin and hash of every piece of intelligence gathered.
* **Note:** The pipeline supports dynamic ingestion. You can drop new files into `sources/` at any time between runs.


---

## 3. Phase 2: Execution & Analysis

Once your `sources/` directory is populated and your `brief.md` is set, execute the CrewAI pipeline from the project root:

```bash
python -m src.crew

```

### The Autonomous Pipeline

Vanguard executes via a strict, doctrinal sequential process:

1. **Pre-Flight Snapshot:** The system hashes all files in `sources/`, compares them to the last run, and generates a versioned `manifest_vX.json`. This stamps all downstream outputs with the exact corpus version used.
2. **Chunking & Extraction:** Large documents are chunked into 60K segments. The `decomposer` agent iteratively extracts every named system, subsystem, protocol, and human terrain element into a scratchpad.
3. **Stage 0 & 1 (Synthesis):** The scratchpad is synthesized into a formal Reverse IPB and decomposed into the ADP 3-13 Cognitive Hierarchy (Data $\rightarrow$ Information $\rightarrow$ Knowledge $\rightarrow$ Understanding $\rightarrow$ Decision $\rightarrow$ Behavior).
4. **Stage 2 (Attack Surface Mapping):** The `mapper` cross-references vulnerabilities against local indices of MITRE Enterprise, ICS, Mobile, ATLAS (AI), and EMB3D.
5. **Verification Gate:** An adversarial `verifier` agent mechanically checks every generated technique ID against the v18.1 local index, auto-correcting hallucinations and blocking upstream failures.
6. **Annex B & C (Graph Modeling):** The `modeler` agent converts the attack surface into a Directed Acyclic Graph (DAG) to find the minimum node cut, and scores the phase probability via a 5-layer Bayesian Belief Network.
7. **Stage 3 & 4 (MDMP):** The `red_team_lead` reviews the priority kill-chain path and develops testable, four-category payloads (C2 Disruption, Degradation, Physical Alteration, Decision Corruption), culminating in a phased Red Team Mission Plan.

All outputs are saved to the `outputs/` directory in Markdown format.

---

## Future Sprints / Roadmap

* [ ] **Streamlit GUI:** Transition from CLI to a web-based dashboard for dynamic SUT selection and individual stage execution.
* [ ] **Corpus Chat (Local RAG):** Implementation of ChromaDB and local embedding models (`mxbai-embed-large`) for conversational Q&A against the versioned SUT corpus.
* [ ] **Dynamic Tooling:** Direct Shodan/Nmap parsing integration for Live-Environment testing.


