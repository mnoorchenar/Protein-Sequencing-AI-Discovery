"""Central configuration: AI providers, limits and environment settings."""

import os

# The first provider with an API key set is used. Both offer free access and the
# same OpenAI-compatible API. List only models the provider serves for free accounts,
# because a model it can't route fails with a 400.
PROVIDERS = [
    {
        "name": "Groq",
        "key_env": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        "models": [
            {
                "id": "openai/gpt-oss-20b",
                "label": "gpt-oss 20B",
                "note": "Fast, with good reasoning.",
            },
            {
                "id": "qwen/qwen3.8-27b",
                "label": "Qwen 3.8 27B",
                "note": "A good alternative for structured answers.",
            },
            {
                "id": "openai/gpt-oss-120b",
                "label": "gpt-oss 120B",
                "note": "Largest model, but slower.",
            },
        ],
    },
    {
        "name": "Hugging Face",
        "key_env": "HF_TOKEN",
        "base_url": "https://router.huggingface.co/v1",
        "models": [
            {
                "id": "meta-llama/Llama-3.1-8B-Instruct",
                "label": "Llama 3.1 8B Instruct",
                "note": "Fast and reliable.",
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
        ],
    },
]

# LLM behaviour. Attempts x timeout must stay below the gunicorn worker timeout.
LLM_MAX_ATTEMPTS = 3
LLM_TIMEOUT_SECONDS = 40

# Request limits
MAX_QUERY_CHARS = 500
MAX_QUESTION_CHARS = 1000
MAX_CONTEXT_CHARS = 500
MAX_REFINE_ANSWERS = 5
MAX_RESULTS = 5

# Rate limit for endpoints that use the AI provider (requests per client per minute).
LLM_RATE_LIMIT_PER_MINUTE = int(os.environ.get("LLM_RATE_LIMIT_PER_MINUTE", "20"))

# Number of reverse proxies in front of the app, used to find the real client IP.
# The Dockerfile sets this to 1 for Hugging Face Spaces. 0 means direct connections.
TRUST_PROXY_HOPS = int(os.environ.get("TRUST_PROXY_HOPS", "0"))


def api_key(provider):
    """Read at call time so tests and deployments can change it."""
    return os.environ.get(provider["key_env"], "").strip()


def active_provider():
    """Return the first provider with an API key, or None."""
    return next((provider for provider in PROVIDERS if api_key(provider)), None)


def catalog():
    """Models to offer. Without a key, list the preferred provider's models."""
    return (active_provider() or PROVIDERS[0])["models"]


def model_ids():
    return [model["id"] for model in catalog()]
