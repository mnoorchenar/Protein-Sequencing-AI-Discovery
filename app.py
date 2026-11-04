"""Biomedical Protein Target Explorer: Flask application and HTTP API."""

import logging
import os

from flask import Flask, jsonify, render_template, request
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from services import config, knowledge, llm, prompts, structure, uniprot
from services.ratelimit import rate_limited

logger = logging.getLogger(__name__)

CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        # 3Dmol and NGL compile WebGL helpers with eval and start blob workers.
        "script-src 'self' https://cdnjs.cloudflare.com 'unsafe-eval' blob:",
        "worker-src 'self' blob:",
        "style-src 'self' 'unsafe-inline'",
        "img-src 'self' data: blob:",
        "connect-src 'self' blob: data:",
        "object-src 'none'",
        "base-uri 'none'",
        "form-action 'self'",
        # Hugging Face shows the app inside an iframe.
        "frame-ancestors 'self' https://huggingface.co https://*.hf.space",
    ]
)


def _text_field(data, name, limit):
    """Return (value, error) for a required string field."""
    value = data.get(name)
    if not isinstance(value, str) or not value.strip():
        return None, f"'{name}' is required."
    value = value.strip()
    if len(value) > limit:
        return None, f"'{name}' must be at most {limit} characters."
    return value, None


def _clean_answers(raw):
    """Keep only well-formed question and answer pairs from the client."""
    answers = []
    if not isinstance(raw, list):
        return answers
    for item in raw[: config.MAX_REFINE_ANSWERS]:
        if not isinstance(item, dict):
            continue
        question = item.get("question")
        answer = item.get("answer")
        if isinstance(question, str) and isinstance(answer, str) and answer.strip():
            answers.append(
                {
                    "question": question.strip()[: config.MAX_QUESTION_CHARS],
                    "answer": answer.strip()[: config.MAX_QUESTION_CHARS],
                }
            )
    return answers


def _public_protein(record, *, relevance="", drugs="", source):
    """The protein shape every endpoint returns to the frontend."""
    return {
        "uniprot_id": record["uniprot_id"],
        "name": record["name"],
        "gene": record.get("gene", ""),
        "organism": record.get("organism", ""),
        "length": record.get("length", 0),
        "function": record.get("function", ""),
        "diseases": record.get("diseases", []),
        "relevance": relevance,
        "drugs": drugs,
        "source": source,
    }


def _verify_ai_targets(targets):
    """Keep only AI suggestions confirmed as human UniProt proteins, by accession and name.

    A wrong accession is corrected by looking the name up, and dropped if that fails.
    Displayed names and functions come from UniProt, not from the model.
    """
    verified = []
    seen = set()
    for target, record in zip(targets, uniprot.resolve_targets(targets), strict=True):
        if record and record["uniprot_id"] not in seen:
            seen.add(record["uniprot_id"])
            verified.append(
                _public_protein(
                    record,
                    relevance=target["relevance"],
                    drugs=target["drugs"],
                    source="ai",
                )
            )
    return verified


def _curated_proteins(query):
    entries = knowledge.lookup(query, limit=config.MAX_RESULTS)
    records = uniprot.get_proteins([entry["uniprot_id"] for entry in entries])
    proteins = []
    for entry, record in zip(entries, records, strict=True):
        # Curated entries stay usable if UniProt is down.
        base = record or {
            "uniprot_id": entry["uniprot_id"],
            "name": entry["name"],
            "function": entry.get("function", ""),
            "organism": "Homo sapiens",
        }
        proteins.append(
            _public_protein(
                base,
                relevance=entry.get("relevance", ""),
                drugs=entry.get("drugs", ""),
                source="curated",
            )
        )
    return proteins


def _uniprot_proteins(query):
    records = uniprot.search(query, limit=config.MAX_RESULTS)
    return [
        _public_protein(
            record,
            relevance=uniprot.describe_relevance(record, query),
            source="uniprot",
        )
        for record in records
    ]


def create_app(test_config=None):
    app = Flask(__name__)
    app.config.update(
        LLM_RATE_LIMIT_PER_MINUTE=config.LLM_RATE_LIMIT_PER_MINUTE,
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    if test_config:
        app.config.update(test_config)

    if config.TRUST_PROXY_HOPS > 0:
        hops = config.TRUST_PROXY_HOPS
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=hops, x_proto=hops, x_host=hops)

    @app.after_request
    def set_security_headers(response):
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        return response

    @app.errorhandler(HTTPException)
    def handle_http_error(error):
        if request.path.startswith("/api/"):
            return jsonify({"error": error.description}), error.code
        return error

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        logger.exception("Unhandled error on %s", request.path)
        return jsonify({"error": "Something went wrong. Please try again."}), 500

    @app.errorhandler(llm.LLMUnavailable)
    def handle_llm_error(error):
        return jsonify({"error": str(error)}), 503

    @app.errorhandler(uniprot.UpstreamError)
    def handle_upstream_error(error):
        logger.warning("Upstream failure: %s", error)
        return jsonify({"error": "UniProt is unavailable right now. Please try again."}), 502

    @app.get("/")
    def index():
        return render_template("index.html", models=config.catalog())

    @app.get("/healthz")
    def health():
        return jsonify({"status": "ok", "curated_diseases": len(knowledge.DATABASE)})

    @app.post("/api/analyze")
    @rate_limited
    def analyze():
        """Find targets: AI verified against UniProt, then curated data, then UniProt search."""
        data = request.get_json(silent=True) or {}
        query, error = _text_field(data, "prompt", config.MAX_QUERY_CHARS)
        if error:
            return jsonify({"error": error}), 400

        proteins, insights, model_used = [], "", None
        try:
            text, model_used = llm.complete(
                prompts.TARGETS_SYSTEM,
                f"Research query: {query}",
                model=data.get("model"),
            )
            targets, insights = llm.parse_targets(text)
            proteins = _verify_ai_targets(targets)
            if not proteins:
                logger.warning("%s gave %d targets, and none were confirmed", model_used, len(targets))
        except llm.LLMUnavailable as unavailable:
            logger.warning("LLM unavailable: %s", unavailable)

        if proteins:
            return jsonify(
                {
                    "proteins": proteins[: config.MAX_RESULTS],
                    "insights": insights,
                    "source": "ai",
                    "model_used": model_used,
                }
            )

        proteins = _curated_proteins(query)
        if proteins:
            return jsonify({"proteins": proteins, "insights": "", "source": "curated"})

        return jsonify(
            {"proteins": _uniprot_proteins(query), "insights": "", "source": "uniprot"}
        )

    @app.post("/api/deep_search")
    def deep_search():
        data = request.get_json(silent=True) or {}
        query, error = _text_field(data, "query", config.MAX_QUERY_CHARS)
        if error:
            return jsonify({"error": error}), 400
        return jsonify({"proteins": _uniprot_proteins(query), "source": "uniprot"})

    @app.post("/api/structure")
    def get_structure():
        data = request.get_json(silent=True) or {}
        accession, error = _text_field(data, "uniprot_id", 10)
        if error:
            return jsonify({"error": error}), 400
        accession = accession.upper()
        if not uniprot.is_valid_accession(accession):
            return jsonify({"error": "That is not a valid UniProt accession."}), 400

        record = uniprot.get_protein(accession)
        if not record:
            return jsonify({"error": f"Could not load UniProt entry {accession}."}), 404

        preferred = "pdb" if data.get("source") == "pdb" else "auto"
        result = structure.get_structure(record, preferred)
        return jsonify(
            {
                "protein": _public_protein(record, source="uniprot"),
                "structure": result,
                "best_pdb": record.get("best_pdb"),
            }
        )

    @app.post("/api/ask")
    @rate_limited
    def ask():
        data = request.get_json(silent=True) or {}
        question, error = _text_field(data, "question", config.MAX_QUESTION_CHARS)
        if error:
            return jsonify({"error": error}), 400

        accession = str(data.get("uniprot_id", "")).upper()
        record = uniprot.get_protein(accession)
        if not record:
            return jsonify({"error": "Load a valid protein before asking about it."}), 400

        raw_context = data.get("context")
        raw_context = raw_context if isinstance(raw_context, dict) else {}
        context = {
            key: raw_context[key][: config.MAX_CONTEXT_CHARS]
            for key in ("relevance", "drugs")
            if isinstance(raw_context.get(key), str)
        }

        answer, model_used = llm.complete(
            prompts.qa_system(record, context),
            question,
            model=data.get("model"),
        )
        return jsonify({"response": answer, "model_used": model_used})

    @app.post("/api/refine/question")
    @rate_limited
    def refine_question():
        data = request.get_json(silent=True) or {}
        query, error = _text_field(data, "original_query", config.MAX_QUERY_CHARS)
        if error:
            return jsonify({"error": error}), 400

        answers = _clean_answers(data.get("answers"))
        text, _ = llm.complete(
            prompts.REFINE_QUESTION_SYSTEM,
            prompts.refine_question_user(query, answers),
            model=data.get("model"),
            max_tokens=1200,
        )
        question = llm.clean_question(text)
        if not question:
            raise llm.LLMUnavailable("The AI did not return a question. Please try again.")
        return jsonify({"question": question})

    @app.post("/api/refine/keywords")
    @rate_limited
    def refine_keywords():
        data = request.get_json(silent=True) or {}
        query, error = _text_field(data, "original_query", config.MAX_QUERY_CHARS)
        if error:
            return jsonify({"error": error}), 400

        answers = _clean_answers(data.get("answers"))
        keywords = ""
        if answers:
            try:
                text, _ = llm.complete(
                    prompts.REFINE_KEYWORDS_SYSTEM,
                    prompts.refine_keywords_user(query, answers),
                    model=data.get("model"),
                    max_tokens=1200,
                )
                keywords = llm.clean_keywords(text)
            except llm.LLMUnavailable as unavailable:
                logger.warning("Keyword refinement fell back to the query: %s", unavailable)

        return jsonify({"keywords": keywords or query})

    return app


logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

app = create_app()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "7860")))
