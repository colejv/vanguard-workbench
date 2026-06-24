from crewai import Crew, Process, Task
import sys, os
from src.agents import (researcher, decomposer, mapper,
                        modeler, red_team_lead, orchestrator, verifier)
from src.tasks import (t_research, t_synthesize_stage0, t_stage1,t_stage2, 
                       t_verify_stage2, t_annexB, t_annexC, t_stage3, t_stage4)
from src.tools import extract_to_scratch, verify_corpus_lock

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
    dynamic_tasks = [t_research]

    for i, chunk in enumerate(chunks):
        chunk_task = Task(
            description=(
                f"You are processing corpus chunk index {i}.\n\n"
                f"=== CHUNK CONTENT ===\n{chunk}\n=====================\n\n"
                f"Extract EVERY: named system, AAMCAT or other subsystem, vendor product, "
                f"interface, protocol, version, exercise event, named person, and organization. "
                f"Call `extract_to_scratch` with the chunk index ({i}) on the first line and your findings below it."
            ),
            expected_output=f"Confirmation that chunk {i} findings were written to scratchpad.",
            agent=decomposer,
            tools=[extract_to_scratch]
        )
        dynamic_tasks.append(chunk_task)

    dynamic_tasks.extend([
        t_synthesize_stage0, 
        t_stage1,
        t_stage2, 
        t_verify_stage2, 
        t_annexB, 
        t_annexC, 
        t_stage3, 
        t_stage4
    ])
    '''
    # --- TEMPORARY OVERRIDE TO RESUME AT ANNEX B ---
    dynamic_tasks = [
        t_annexB, 
        t_annexC, 
        t_stage3, 
        t_stage4
    ]
    '''
    
    vanguard_crew = Crew(
        agents=[researcher, decomposer, mapper, modeler, red_team_lead, orchestrator, verifier],
        tasks=dynamic_tasks,
        process=Process.sequential,
        verbose=True,
    )

    # Pass the versioning variables into the kickoff inputs
    result = vanguard_crew.kickoff(inputs={
        "sut_brief": brief_text,
        "file_count": c_count,
        "corpus_version": c_version
    })
    
    # Optional: Stamp the final mission plan with the corpus version
    try:
        with open("outputs/stage4_mission_plan.md", "a") as f:
            f.write(f"\n\n---\n*Analysis grounded in Corpus Version v{c_version} ({c_count} files)*")
    except Exception:
        pass

    print("\n\n=== PIPELINE FINISHED ===")
    print(result)