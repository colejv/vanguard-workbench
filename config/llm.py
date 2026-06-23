from crewai import LLM

# Ollama exposes an OpenAI-compatible endpoint at /v1
OLLAMA_BASE = "http://localhost:11434/v1"

# Light edge model for extraction/decomposition. Gemma 4 sampling defaults.
light_llm = LLM(
    model="ollama/gemma4:e4b", 
    base_url=OLLAMA_BASE,
    temperature=1.0, 
    top_p=0.95
)

# 12B (MLX) for reasoning, coding/agentic, and tool execution.
# Lower temperature for the deterministic structured-output / tool stages.
reason_llm = LLM(
    model="ollama/gemma4:12b-mlx", 
    base_url=OLLAMA_BASE,
    temperature=0.1,  
    top_p=0.95
)