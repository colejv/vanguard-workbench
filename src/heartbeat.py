"""
Background heartbeat for slow local-LLM Crew.kickoff() calls.

WHY A SEPARATE FILE, NOT stdout: CrewAI's verbose=True output renders as
Rich panels (the boxed "Agent Started" / "Task Failed" output you've seen).
A plain print() from a background thread while Rich is mid-render could
interleave and corrupt that output -- I have no way to verify Rich's
thread-safety here against your specific installed version, so rather than
promise clean terminal output I haven't tested, this writes to a dedicated
log file instead. tail -f it in a second terminal; it never touches
crew.py's own stdout.

Usage (see crew.py for the actual wiring):
    with heartbeat("pre_crew", log_path=run_context.artifact_path("heartbeat.log")):
        pre_crew.kickoff(...)

Each tick reports elapsed time AND (best-effort) what Ollama's own /api/ps
says is currently loaded -- so a single `tail -f` tells you both "how long
has this been running" and "does Ollama think it's actively holding a
model for this," which is exactly the ambiguity `ollama ps` alone left you
with (a "Stopping..." status could mean either finished-a-while-ago or
never-actually-reached-Ollama).
"""
import os
import time
import json
import threading
import urllib.request
from contextlib import contextmanager


def check_ollama_ps(base_url="http://localhost:11434", timeout=5):
    """Best-effort equivalent of `ollama ps` via Ollama's native /api/ps
    endpoint. Never raises -- a heartbeat that crashes the run it's
    monitoring would be worse than no heartbeat at all."""
    try:
        req = urllib.request.Request(f"{base_url}/api/ps")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read())
        models = data.get("models", [])
        if not models:
            return "no models currently loaded in Ollama"
        parts = []
        for m in models:
            name = m.get("name", m.get("model", "?"))
            until = m.get("expires_at", "?")
            parts.append(f"{name} (expires {until})")
        return "; ".join(parts)
    except Exception as e:
        return f"could not reach Ollama /api/ps ({type(e).__name__}: {e})"


def _heartbeat_loop(stop_event, log_path, label, interval, check_ollama):
    start = time.time()
    os.makedirs(os.path.dirname(log_path) or ".", exist_ok=True)
    with open(log_path, "a") as f:
        f.write(f"\n=== heartbeat started: {label} "
                f"({time.strftime('%Y-%m-%d %H:%M:%S')}) ===\n")
        f.flush()
    tick = 0
    while not stop_event.wait(interval):
        tick += 1
        elapsed = time.time() - start
        mins, secs = divmod(int(elapsed), 60)
        line = f"[{time.strftime('%H:%M:%S')}] {label}: {mins}m{secs:02d}s elapsed, still running."
        if check_ollama:
            line += f" Ollama: {check_ollama_ps()}"
        with open(log_path, "a") as f:
            f.write(line + "\n")
            f.flush()


@contextmanager
def heartbeat(label, log_path="heartbeat.log", interval=30, check_ollama=True):
    """Writes a heartbeat line to log_path every `interval` seconds while
    the wrapped block runs. Stops cleanly on normal completion OR on an
    exception -- the exception always propagates unchanged; this context
    manager only ever observes, never suppresses or alters control flow."""
    stop_event = threading.Event()
    thread = threading.Thread(
        target=_heartbeat_loop,
        args=(stop_event, log_path, label, interval, check_ollama),
        daemon=True,
    )
    thread.start()
    try:
        yield
    finally:
        stop_event.set()
        thread.join(timeout=2)
        try:
            with open(log_path, "a") as f:
                f.write(f"=== heartbeat stopped: {label} "
                        f"({time.strftime('%Y-%m-%d %H:%M:%S')}) ===\n")
        except Exception:
            pass