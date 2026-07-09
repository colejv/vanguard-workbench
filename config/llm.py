from crewai import LLM

# Ollama exposes an OpenAI-compatible endpoint at /v1
OLLAMA_BASE = "http://localhost:11434/v1"
# Ollama's native endpoint (no /v1). Used for reason_llm below because
# Gemma4's tool-call parsing is currently broken specifically on the /v1
# OpenAI-compat path (open Ollama issues #15241, #15539, #15288 — the model
# generates a correct tool call, but the /v1 layer's parser fails to
# extract it into tool_calls and the JSON leaks into plain content instead,
# which is exactly what we observed: valid JSON landing in the agent's
# Final Answer instead of a successful write_stage0_output/write_stage1_output
# call). The native endpoint avoids that translation layer entirely.
OLLAMA_NATIVE = "http://localhost:11434"

# No timeout was previously set on either LLM below, so both ran on
# whatever CrewAI's client default is (~600s / 10 min in most Ollama+CrewAI
# setups per the CrewAI community forums — this exact symptom, a local
# model timing out on a bigger generation, is one of the most commonly
# reported CrewAI+Ollama issues). Stage 1 (three-layer decomposition + a
# ~25-30 node structured JSON write via reason_llm, a 27B dense model
# running locally) is meaningfully bigger than Stage 0's generation, which
# completed fine on the same model/config — that size difference, not a
# routing or endpoint problem, is the most likely cause of the timeout.
# Set generously rather than tightly: the cost of guessing too low is
# hitting this same failure again on an even bigger prompt later (Stage 2's
# edge list, Annex C's BBN config), each time re-running Stage 0 from
# scratch (run-isolation gives every retry a fresh run_id, no checkpoint).
LOCAL_LLM_TIMEOUT_SECONDS = 1800  # 30 min ceiling per call
LOCAL_LLM_MAX_RETRIES = 2

# Light edge model for extraction/decomposition. Gemma 4 sampling defaults.
light_llm = LLM(
    model="ollama/gemma4:e4b", 
    base_url=OLLAMA_BASE,
    temperature=1.0, 
    top_p=0.95,
    timeout=LOCAL_LLM_TIMEOUT_SECONDS,
    max_retries=LOCAL_LLM_MAX_RETRIES,
)

# 27B Qwen3.6 (dense) for reasoning, coding/agentic, and tool execution.
# Replaces gemma4:12b-mlx here specifically because this is the model used
# by every tool-calling agent (decomposer, mapper, modeler, red_team_lead,
# verifier) — the role most exposed to the Gemma4/v1 tool-parsing bug.
# Qwen3 has Hermes-style tool use trained directly into its chat template
# (not bolted on via a parser), which has a materially more mature/stable
# track record for tool calling through Ollama than Gemma4 currently does.
#
# enable_thinking=False: Qwen3.6 reasons by default before responding: this
# can interfere with clean tool-call extraction (documented quirk — thinking
# content competing with the tool-call channel), so it's disabled for the
# tool-calling role. Passed via extra_body, LiteLLM's passthrough for
# provider-specific chat_template_kwargs.
#
# Lower temperature for the deterministic structured-output / tool stages.
reason_llm = LLM(
    model="ollama/qwen3.6:27b",
    base_url=OLLAMA_NATIVE,
    temperature=0.1,
    top_p=0.95,
    extra_body={"chat_template_kwargs": {"enable_thinking": False}},
    timeout=LOCAL_LLM_TIMEOUT_SECONDS,
    max_retries=LOCAL_LLM_MAX_RETRIES,
)