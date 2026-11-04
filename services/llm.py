"""OpenAI-compatible chat completion with model fallback, and parsing of LLM output."""

import json
import logging
import re

import requests

from . import config
from .uniprot import is_valid_accession

logger = logging.getLogger(__name__)

session = requests.Session()


class LLMUnavailable(Exception):
    """No model produced an answer. The message is safe to show to users."""


class LLMAuthError(LLMUnavailable):
    """The API key is missing, invalid or lacks permission."""


def resolve_model(requested):
    """Only allow catalog models, so the endpoint can't be used to run arbitrary ones."""
    ids = config.model_ids()
    return requested if requested in ids else ids[0]


def _attempt_order(model):
    first = resolve_model(model)
    others = [m for m in config.model_ids() if m != first]
    return [first, *others][: config.LLM_MAX_ATTEMPTS]


def _strip_thinking(text):
    """Some models put their reasoning in the answer, inside <think> tags."""
    return re.sub(r"<think>.*?(?:</think>|\Z)", "", text, flags=re.DOTALL).strip()


def _raise_for_account_problem(response, provider):
    """Stop on errors that apply to the whole account, because other models would fail too."""
    status = response.status_code
    name = provider["name"]
    if status == 401:
        logger.error("%s rejected %s.", name, provider["key_env"])
        raise LLMAuthError(f"AI is unavailable: {name} rejected the server's API key.")
    if status == 402:
        logger.error("%s returned 402: the account's credits have run out.", name)
        raise LLMUnavailable(f"AI is unavailable: this demo's {name} account has no credits left.")
    if status == 403 and "sufficient permissions" in response.text:
        logger.error("%s lacks the permission to call inference.", provider["key_env"])
        raise LLMAuthError(f"AI is unavailable: the server's {name} key lacks permission.")


def complete(system, user, *, model=None, max_tokens=2500, temperature=0.3):
    """Return (text, model_used), trying fallback models when one fails.

    max_tokens has to leave room for reasoning models, whose reasoning counts against it.
    A cut-off answer counts as a failure, because truncated JSON can't be parsed.
    """
    provider = config.active_provider()
    if not provider:
        raise LLMAuthError("AI is not configured: no API key is available.")

    url = f"{provider['base_url']}/chat/completions"
    headers = {"Authorization": f"Bearer {config.api_key(provider)}"}
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    for candidate in _attempt_order(model):
        try:
            response = session.post(
                url,
                headers=headers,
                json={
                    "model": candidate,
                    "messages": messages,
                    "max_tokens": config.token_limit(candidate, max_tokens),
                    "temperature": temperature,
                    **config.model_params(candidate),
                },
                timeout=config.LLM_TIMEOUT_SECONDS,
            )
        except requests.RequestException as error:
            logger.warning("Model %s failed (%s)", candidate, type(error).__name__)
            continue

        _raise_for_account_problem(response, provider)
        if response.status_code != 200:
            logger.warning(
                "Model %s failed (status %s): %s",
                candidate,
                response.status_code,
                response.text[:200],
            )
            continue

        try:
            choice = response.json()["choices"][0]
            content = choice["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError, AttributeError):
            logger.warning("Model %s returned an unexpected response", candidate)
            continue

        if choice.get("finish_reason") == "length":
            logger.warning("Model %s ran out of tokens after %s", candidate, max_tokens)
            continue

        text = _strip_thinking(content)
        if text:
            logger.info("Answered by %s on %s", candidate, provider["name"])
            return text, candidate
        logger.warning("Model %s returned empty content", candidate)

    raise LLMUnavailable("The AI models are unavailable right now. Please try again.")


def _first_json_array(text):
    """Return the first JSON array of objects in text, and the text after it.

    Arrays without objects are skipped, because citations like "[2]" are valid JSON.
    """
    decoder = json.JSONDecoder()
    position = text.find("[")
    while position != -1:
        try:
            value, end = decoder.raw_decode(text, position)
        except json.JSONDecodeError:
            position = text.find("[", position + 1)
            continue
        if isinstance(value, list) and any(isinstance(item, dict) for item in value):
            return value, text[end:]
        position = text.find("[", position + 1)
    return None, text


def _clean_field(value, limit=400):
    return value.strip()[:limit] if isinstance(value, str) else ""


def parse_targets(text):
    """Parse LLM output into (targets, insights), dropping malformed entries."""
    items, remainder = _first_json_array(text)
    targets = []
    seen = set()
    for item in items or []:
        if not isinstance(item, dict):
            continue
        accession = _clean_field(item.get("uniprot_id")).upper()
        if not is_valid_accession(accession) or accession in seen:
            continue
        seen.add(accession)
        targets.append(
            {
                "uniprot_id": accession,
                "name": _clean_field(item.get("name")),
                "relevance": _clean_field(item.get("relevance")),
                "drugs": _clean_field(item.get("drugs")),
            }
        )

    match = re.search(r"INSIGHTS?:\s*(.+)", remainder, re.IGNORECASE | re.DOTALL)
    insights = match.group(1).strip()[:800] if match else ""
    return targets, insights


def clean_keywords(text, limit=8):
    """Reduce an LLM keyword answer to a safe, short search string."""
    first_line = text.strip().splitlines()[0] if text.strip() else ""
    first_line = re.sub(r"^(keywords?|search[ _]ready)\s*:\s*", "", first_line, flags=re.I)
    words = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", first_line)
    return " ".join(words[:limit])


def clean_question(text):
    """Keep a clarifying question to one short line of plain text."""
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return lines[0].strip('"')[:300] if lines else ""
