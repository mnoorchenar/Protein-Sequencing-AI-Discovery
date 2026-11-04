"""Central configuration: model catalogue, limits and environment settings."""

import os

# Only models that Hugging Face routes under default provider settings belong here.
# A model served only by a provider the account hasn't enabled fails with a 400.
MODELS = [
    {
        "id": "meta-llama/Llama-3.1-8B-Instruct",
        "label": "Llama 3.1 8B Instruct",
        "note": "Fast and reliable. Served by several providers.",
    },
    {
        "id": "openai/gpt-oss-20b",
        "label": "gpt-oss 20B",
        "note": "Strongest reasoning, but slower.",
    },
    {
        "id": "google/gemma-3-27b-it",
        "label": "Gemma 3 27B",
        "note": "Large model with detailed answers.",
    },
]
MODEL_IDS = [model["id"] for model in MODELS]
DEFAULT_MODEL = MODEL_IDS[0]

# LLM behaviour. Attempts x timeout must stay below the gunicorn worker timeout.
LLM_MAX_ATTEMPTS = 3
LLM_TIMEOUT_SECONDS = 40

# Request limits
MAX_QUERY_CHARS = 500
MAX_QUESTION_CHARS = 1000
MAX_CONTEXT_CHARS = 500
MAX_REFINE_ANSWERS = 5
MAX_RESULTS = 5

# Rate limit for endpoints that spend LLM credits (requests per client per minute).
LLM_RATE_LIMIT_PER_MINUTE = int(os.environ.get("LLM_RATE_LIMIT_PER_MINUTE", "20"))

# Number of reverse proxies in front of the app, used to find the real client IP.
# The Dockerfile sets this to 1 for Hugging Face Spaces. 0 means direct connections.
TRUST_PROXY_HOPS = int(os.environ.get("TRUST_PROXY_HOPS", "0"))


def hf_token():
    """Read at call time so tests and deployments can change it."""
    return os.environ.get("HF_TOKEN", "").strip()
