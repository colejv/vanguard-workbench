from crewai import Crew, Process, Task
import sys, os
from src.agents import (researcher, decomposer, mapper,
                        modeler, red_team_lead, orchestrator)
from src.tasks import (t_research, t_synthesize_stage0, t_stage1,t_stage2, 
                       t_annexB, t_annexC, t_stage3, t_stage4)
from src.tools import extract_to_scratch, verify_corpus_lock, verify_stage2_vectors


if __name__ == "__main__":
    import sys, os, glob, json, hashlib

    def snapshot_corpus(src_dir="sources", index_dir="corpus-index"):
        """Hashes the corpus, compares to the latest manifest, and versions it if changed."""
        os.makedirs(index_dir, exist_ok=True)
        
        def hash_file(filepath):
            with open(filepath, "rb") as f:
                return hashlib.sha256(f.read()).hexdigest()

        # Get current files
        current_files = sorted([
            f for f in os.listdir(src_dir) 
            if f.endswith((".md", ".txt", ".pdf", ".json")) 
            and not f.startswith("_") 
            and f != "corpus_manifest.md"
        ])
        
        # Hash state
        current_state = {f: hash_file(os.path.join(src_dir, f)) for f in current_files}
        current_hash = hashlib.sha256(json.dumps(current_state, sort_keys=True).encode()).hexdigest()

        # Find latest version
        manifests = glob.glob(os.path.join(index_dir, "manifest_v*.json"))
        latest_v = 0
        latest_hash = ""
        for m in manifests:
            try:
                # Extract version integer from filename (e.g., manifest_v2.json -> 2)
                v = int(os.path.basename(m).split("_v")[1].split(".json")[0])
                if v > latest_v:
                    latest_v = v
                    with open(m, 'r') as mf:
                        latest_hash = json.load(mf).get("corpus_hash", "")
            except (IndexError, ValueError, json.JSONDecodeError):
                continue

        # Compare and version
        if current_hash != latest_hash:
            new_v = latest_v + 1
            manifest_data = {
                "version": new_v,
                "corpus_hash": current_hash,
                "file_count": len(current_files),
                "files": current_state
            }
            with open(os.path.join(index_dir, f"manifest_v{new_v}.json"), "w") as f:
                json.dump(manifest_data, f, indent=2)
            return new_v, len(current_files), "UPDATED"
        else:
            return latest_v, len(current_files), "UNCHANGED"

    # ==========================================
    # PRE-FLIGHT & SNAPSHOT
    # ==========================================
    print("Running pre-flight corpus snapshot...")
    c_version, c_count, c_status = snapshot_corpus()
    print(f"Corpus Version: v{c_version} | File Count: {c_count} | Status: {c_status}")

    print("Reading assessment brief...")
    with open("collection/brief.md") as f:
        brief_text = f.read()

    # Robust Dedup: Ensure scratchpad is zeroed out to prevent duplicate 
    # entries if a previous run crashed mid-extraction.
    scratch_path = "outputs/_stage0_scratch.md"
    if os.path.exists(scratch_path):
        os.remove(scratch_path)
        # Touch the file so the tool doesn't throw a FileNotFoundError if read early
        open(scratch_path, 'a').close() 

    # Read and assemble corpus chunks
    print("Assembling corpus from chunks...")
    src = "sources"
    files = sorted(
        f for f in os.listdir(src)
        if f.endswith((".md", ".txt"))
        and not f.startswith("_")
        and f != "corpus_manifest.md"
    )
    
    CHUNK = 60000
    chunks = []
    current = []
    current_len = 0
    for fn in files:
        content = f"\n===== {fn} =====\n" + open(os.path.join(src, fn)).read()
        if current_len + len(content) > CHUNK and current:
            chunks.append("".join(current))
            current, current_len = [], 0
        current.append(content)
        current_len += len(content)
    if current:
        chunks.append("".join(current))

    total_chars = sum(len(c) for c in chunks)
    print(f"Corpus: {len(files)} files, {total_chars:,} chars, {len(chunks)} chunks")

    with open("corpus-index/corpus_chunks.json", "w") as f:
        json.dump({"chunks": chunks, "total": len(chunks), "files": len(files)}, f)
    
    # ==========================================
    # DYNAMIC TASK ASSEMBLY
    # ==========================================
    chunk_tasks = []
    for i, chunk in enumerate(chunks):
        chunk_tasks.append(Task(
            description=(
                f"You are processing corpus chunk index {i}.\n\n"
                f"=== CHUNK CONTENT ===\n{chunk}\n=====================\n\n"
                f"Extract EVERY: named system, AAMCAT or other subsystem, vendor product, "
                f"interface, protocol, version, exercise event, named person, and organization. "
                f"Call `extract_to_scratch` with the chunk index ({i}) on the first line and your findings below it."
            ),
            expected_output=f"Confirmation that chunk {i} findings were written to scratchpad.",
            agent=decomposer,
            tools=[extract_to_scratch],
        ))

    # ---- CREW 1: through Stage 2 (produces stage2_vectors.json) ----
    pre_tasks = [t_research] + chunk_tasks + [t_synthesize_stage0, t_stage1, t_stage2]

    pre_crew = Crew(
        agents=[researcher, decomposer, mapper],
        tasks=pre_tasks,
        process=Process.sequential,
        verbose=True,
    )
    pre_crew.kickoff(inputs={
        "sut_brief": brief_text,
        "file_count": c_count,
        "corpus_version": c_version,
    })

    # ---- DETERMINISTIC GATE (plain Python — the actual enforcement point) ----
    verification = verify_stage2_vectors(
        vectors_path="outputs/stage2_vectors.json",
        index_path="corpus-index/technique_index.json",
    )
    with open("outputs/stage2_verification.md", "w") as f:
        f.write(f"# Stage 2 Verification\n\nSTATUS: {verification['status']}\n\n")
        f.write(verification["summary"] + "\n\n")
        for ie in verification["invalid_edges"]:
            sug = ie["suggestion"][0]["id"] if ie["suggestion"] else "none"
            f.write(f"- INVALID edge[{ie['edge_index']}] `{ie['technique']}` "
                    f"({ie['reason']}) — suggest `{sug}`\n")
        for ge in verification["gap_edges"]:
            f.write(f"- GAP edge[{ge['edge_index']}] `{ge['technique']}`\n")

    if not verification["is_valid"]:
        raise RuntimeError(
            f"Stage 2 verification FAILED: {verification['summary']} "
            f"See outputs/stage2_verification.md. Annex B and downstream NOT executed."
        )

    # ---- CREW 2: Annex B onward (only reached if gate passed) ----
    post_crew = Crew(
        agents=[modeler, red_team_lead, orchestrator],
        tasks=[t_annexB, t_annexC, t_stage3, t_stage4],
        process=Process.sequential,
        verbose=True,
    )
    result = post_crew.kickoff(inputs={
        "sut_brief": brief_text,
        "file_count": c_count,
        "corpus_version": c_version,
    })

    # Stamp the final mission plan with the corpus version
    try:
        with open("outputs/stage4_mission_plan.md", "a") as f:
            f.write(f"\n\n---\n*Analysis grounded in Corpus Version v{c_version} ({c_count} files)*")
    except Exception:
        pass

    print("\n\n=== PIPELINE FINISHED ===")
    print(result)