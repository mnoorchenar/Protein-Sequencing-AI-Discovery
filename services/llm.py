"""Hugging Face chat completion with model fallback, and parsing of LLM output."""

import json
import logging
import re

from huggingface_hub import InferenceClient

from . import config
from .uniprot import is_valid_accession

logger = logging.getLogger(__name__)


class LLMUnavailable(Exception):
    """No model produced an answer. The message is safe to show to users."""


class LLMAuthError(LLMUnavailable):
    """The Hugging Face token is missing, invalid or lacks permission."""


def resolve_model(requested):
    """Only allow catalogue models, so the endpoint can't be used to run arbitrary ones."""
    return requested if requested in config.MODEL_IDS else config.DEFAULT_MODEL


def _attempt_order(model):
    first = resolve_model(model)
    others = [m for m in config.MODEL_IDS if m != first]
    return [first, *others][: config.LLM_MAX_ATTEMPTS]


def _status_code(error):
    return getattr(getattr(error, "response", None), "status_code", None)


def complete(system, user, *, model=None, token=None, max_tokens=900, temperature=0.3):
    """Return (text, model_used), trying fallback models when one fails."""
    effective_token = token or config.hf_token()
    if not effective_token:
        raise LLMAuthError("AI is not configured: no Hugging Face token is available.")

    client = InferenceClient(token=effective_token, timeout=config.LLM_TIMEOUT_SECONDS)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    for candidate in _attempt_order(model):
        try:
            response = client.chat_completion(
                messages=messages,
                model=candidate,
                max_tokens=max_tokens,
                temperature=temperature,
            )
        except Exception as error:  # Provider errors have no shared base class.
            status = _status_code(error)
            if status in (401, 403) and token:
                raise LLMAuthError(
                    "Hugging Face rejected the token you provided."
                ) from error
            if status == 401:
                raise LLMAuthError(
                    "Hugging Face rejected the server's token."
                ) from error
            # A token without this permission fails the same way for every model.
            if status == 403 and "sufficient permissions" in str(error):
                logger.error(
                    "HF_TOKEN lacks the 'Make calls to Inference Providers' permission."
                )
                raise LLMAuthError(
                    "AI is unavailable: the server's Hugging Face token can't call Inference Providers."
                ) from error
            logger.warning(
                "Model %s failed (%s, status %s)",
                candidate,
                type(error).__name__,
                status,
            )
            continue

        text = (response.choices[0].message.content or "").strip()
        if text:
            logger.info("Answered by %s", candidate)
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
