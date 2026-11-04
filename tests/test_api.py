from pathlib import Path

import pytest

from app import create_app
from services import config, llm, structure, uniprot
from tests.conftest import make_record

AI_RESPONSE = (
    '[{"name": "EGFR", "uniprot_id": "P00533", "relevance": "Driver", "drugs": "Erlotinib"},'
    ' {"name": "mouse protein", "uniprot_id": "P01899"},'
    ' {"name": "hallucinated", "uniprot_id": "Q99999"}]\n'
    "INSIGHTS: Target kinases."
)
RECORDS = {
    "P00533": make_record(),
    "P01899": make_record(
        "P01899", taxon_id=10090, organism="Mus musculus", aliases=["mouse protein"]
    ),
    "P05067": make_record(
        "P05067", name="Amyloid-beta precursor protein", gene="APP", aliases=["APP"]
    ),
    "P56817": make_record("P56817", name="Beta-secretase 1", gene="BACE1", aliases=["BACE1"]),
    "P10636": make_record(
        "P10636", name="Microtubule-associated protein tau", gene="MAPT", aliases=["MAPT"]
    ),
}


@pytest.fixture
def uniprot_data(monkeypatch):
    monkeypatch.setattr(uniprot, "get_protein", lambda accession: RECORDS.get(accession))
    monkeypatch.setattr(uniprot, "search", lambda query, limit=5: [])
    monkeypatch.setattr(uniprot, "_search_gene", lambda symbol: [])


@pytest.fixture
def llm_answer(monkeypatch):
    """Make the LLM return a fixed answer, recording how it was called."""
    calls = []

    def install(answer=AI_RESPONSE):
        def fake_complete(system, user, **kwargs):
            calls.append({"system": system, "user": user, **kwargs})
            if isinstance(answer, Exception):
                raise answer
            return answer, "test-model"

        monkeypatch.setattr(llm, "complete", fake_complete)
        return calls

    return install


def post(client, path, **body):
    return client.post(path, json=body)


class TestPages:
    def test_index_lists_only_catalogue_models(self, client):
        html = client.get("/").get_data(as_text=True)
        for model in config.catalog():
            assert model["id"] in html

    def test_health(self, client):
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.json["status"] == "ok"
        assert response.json["curated_diseases"] > 0

    def test_security_headers(self, client):
        headers = client.get("/").headers
        assert "default-src 'self'" in headers["Content-Security-Policy"]
        assert headers["X-Content-Type-Options"] == "nosniff"

    def test_unknown_api_route_returns_json(self, client):
        response = client.get("/api/nope")
        assert response.status_code == 404
        assert "error" in response.json


class TestAnalyze:
    def test_ai_results_are_verified_as_human(self, client, llm_answer, uniprot_data):
        llm_answer()
        data = post(client, "/api/analyze", prompt="lung cancer").json
        assert data["source"] == "ai"
        assert [p["uniprot_id"] for p in data["proteins"]] == ["P00533"]
        assert data["insights"] == "Target kinases."

    def test_real_accession_of_a_different_protein_is_rejected(self, client, llm_answer, uniprot_data):
        llm_answer('[{"name": "Tau protein", "uniprot_id": "P00533", "relevance": "Tangles"}]')
        data = post(client, "/api/analyze", prompt="unrelated condition").json
        assert data["proteins"] == []

    def test_wrong_accession_is_corrected_by_name(self, client, llm_answer, uniprot_data, monkeypatch):
        tau = make_record(
            "P10636",
            name="Microtubule-associated protein tau",
            aliases=["Microtubule-associated protein tau", "MAPT"],
        )
        monkeypatch.setattr(uniprot, "search", lambda query, limit=5: [make_record(), tau])
        llm_answer('[{"name": "Tau protein", "uniprot_id": "P00533", "relevance": "Tangles"}]')
        protein = post(client, "/api/analyze", prompt="tauopathy").json["proteins"][0]
        assert protein["uniprot_id"] == "P10636"
        assert protein["relevance"] == "Tangles"
        assert protein["source"] == "ai"

    def test_corrected_duplicates_are_merged(self, client, llm_answer, uniprot_data, monkeypatch):
        monkeypatch.setattr(uniprot, "search", lambda query, limit=5: [make_record()])
        llm_answer(
            '[{"name": "EGFR", "uniprot_id": "P00533"}, {"name": "HER1", "uniprot_id": "P56817"}]'
        )
        proteins = post(client, "/api/analyze", prompt="tumors").json["proteins"]
        assert [p["uniprot_id"] for p in proteins] == ["P00533"]

    def test_uniprot_facts_replace_ai_text(self, client, llm_answer, uniprot_data):
        llm_answer()
        protein = post(client, "/api/analyze", prompt="lung cancer").json["proteins"][0]
        assert protein["name"] == "Epidermal growth factor receptor"
        assert protein["relevance"] == "Driver"
        assert protein["drugs"] == "Erlotinib"
        assert protein["source"] == "ai"
        assert "taxon_id" not in protein

    def test_unusable_ai_output_uses_curated_data(self, client, llm_answer, uniprot_data):
        llm_answer("I cannot help with that.")
        data = post(client, "/api/analyze", prompt="Alzheimer's disease").json
        assert data["source"] == "curated"
        assert data["proteins"][0]["uniprot_id"] == "P05067"
        assert data["proteins"][0]["source"] == "curated"

    def test_llm_outage_uses_curated_data(self, client, llm_answer, uniprot_data):
        llm_answer(llm.LLMUnavailable("down"))
        assert post(client, "/api/analyze", prompt="alzheimer").json["source"] == "curated"

    def test_curated_data_survives_uniprot_outage(self, client, llm_answer, monkeypatch):
        llm_answer(llm.LLMUnavailable("down"))
        monkeypatch.setattr(uniprot, "get_protein", lambda accession: None)
        data = post(client, "/api/analyze", prompt="alzheimer").json
        assert data["proteins"][0]["name"] == "Amyloid Precursor Protein (APP)"

    def test_no_curated_match_uses_uniprot_search(self, client, llm_answer, monkeypatch):
        llm_answer(llm.LLMUnavailable("down"))
        monkeypatch.setattr(uniprot, "search", lambda query, limit: [make_record()])
        data = post(client, "/api/analyze", prompt="rare condition xyz").json
        assert data["source"] == "uniprot"
        assert data["proteins"][0]["relevance"].startswith("Associated with")

    def test_nothing_found_returns_empty_list(self, client, llm_answer, monkeypatch):
        llm_answer(llm.LLMUnavailable("down"))
        monkeypatch.setattr(uniprot, "search", lambda query, limit: [])
        response = post(client, "/api/analyze", prompt="rare condition xyz")
        assert response.status_code == 200
        assert response.json["proteins"] == []

    def test_all_sources_down_returns_502(self, client, llm_answer, monkeypatch):
        def boom(query, limit):
            raise uniprot.UpstreamError("down")

        llm_answer(llm.LLMUnavailable("down"))
        monkeypatch.setattr(uniprot, "search", boom)
        assert post(client, "/api/analyze", prompt="rare condition xyz").status_code == 502

    def test_missing_ai_key_still_returns_results(self, client, llm_answer, uniprot_data):
        llm_answer(llm.LLMAuthError("AI is not configured"))
        response = post(client, "/api/analyze", prompt="alzheimer")
        assert response.status_code == 200
        assert response.json["source"] == "curated"

    @pytest.mark.parametrize("body", [{}, {"prompt": ""}, {"prompt": "   "}, {"prompt": 5}])
    def test_rejects_missing_prompt(self, client, body):
        assert client.post("/api/analyze", json=body).status_code == 400

    def test_rejects_long_prompt(self, client):
        response = post(client, "/api/analyze", prompt="x" * (config.MAX_QUERY_CHARS + 1))
        assert response.status_code == 400

    def test_rejects_non_json_without_crashing(self, client):
        response = client.post("/api/analyze", data="not json", content_type="text/plain")
        assert response.status_code == 400

    def test_rejects_oversized_body(self, client):
        response = client.post(
            "/api/analyze", data="x" * (65 * 1024), content_type="application/json"
        )
        assert response.status_code in (400, 413)

    def test_unexpected_errors_do_not_leak_details(self, client, llm_answer, monkeypatch):
        llm_answer()

        def boom(targets):
            raise RuntimeError("secret internal detail")

        monkeypatch.setattr(uniprot, "resolve_targets", boom)
        response = post(client, "/api/analyze", prompt="cancer")
        assert response.status_code == 500
        assert "secret" not in response.get_data(as_text=True)


class TestStructure:
    def test_returns_structure(self, client, uniprot_data, monkeypatch):
        monkeypatch.setattr(
            structure,
            "get_structure",
            lambda record, preferred: {"source": "alphafold", "pdb_data": "ATOM", "label": "AF"},
        )
        data = post(client, "/api/structure", uniprot_id="p00533").json
        assert data["structure"]["source"] == "alphafold"
        assert data["protein"]["uniprot_id"] == "P00533"
        assert data["best_pdb"]["id"] == "1M17"

    def test_missing_structure_is_null(self, client, uniprot_data, monkeypatch):
        monkeypatch.setattr(structure, "get_structure", lambda record, preferred: None)
        response = post(client, "/api/structure", uniprot_id="P00533")
        assert response.status_code == 200
        assert response.json["structure"] is None

    def test_source_preference_is_passed_on(self, client, uniprot_data, monkeypatch):
        seen = []
        monkeypatch.setattr(
            structure, "get_structure", lambda record, preferred: seen.append(preferred)
        )
        post(client, "/api/structure", uniprot_id="P00533", source="pdb")
        post(client, "/api/structure", uniprot_id="P00533", source="anything-else")
        assert seen == ["pdb", "auto"]

    @pytest.mark.parametrize("value", ["../../etc", "NOTANID", "P00533/x"])
    def test_rejects_malformed_accession(self, client, value):
        assert post(client, "/api/structure", uniprot_id=value).status_code == 400

    def test_unknown_protein_is_404(self, client, uniprot_data):
        assert post(client, "/api/structure", uniprot_id="Q99999").status_code == 404


class TestAsk:
    def test_prompt_is_built_on_the_server_from_uniprot(self, client, llm_answer, uniprot_data):
        calls = llm_answer("[KEY] An answer")
        response = post(
            client,
            "/api/ask",
            uniprot_id="P00533",
            question="What does it do?",
            context={"relevance": "Driver", "drugs": "Erlotinib"},
        )
        assert response.json["response"] == "[KEY] An answer"
        assert "Receptor tyrosine kinase." in calls[0]["system"]
        assert "Erlotinib" in calls[0]["system"]
        assert calls[0]["user"] == "What does it do?"

    def test_context_is_capped_and_type_checked(self, client, llm_answer, uniprot_data):
        calls = llm_answer("answer")
        post(
            client,
            "/api/ask",
            uniprot_id="P00533",
            question="q",
            context={"relevance": "y" * 5000, "drugs": ["not", "text"]},
        )
        assert "y" * config.MAX_CONTEXT_CHARS in calls[0]["system"]
        assert "y" * (config.MAX_CONTEXT_CHARS + 1) not in calls[0]["system"]
        assert "not" not in calls[0]["system"].split("UniProt record:")[1]

    def test_unknown_protein_is_rejected(self, client, uniprot_data):
        response = post(client, "/api/ask", uniprot_id="Q99999", question="q")
        assert response.status_code == 400

    def test_llm_outage_returns_503(self, client, llm_answer, uniprot_data):
        llm_answer(llm.LLMUnavailable("The AI models are unavailable right now."))
        response = post(client, "/api/ask", uniprot_id="P00533", question="q")
        assert response.status_code == 503
        assert "unavailable" in response.json["error"]

    def test_raw_prompt_endpoint_no_longer_exists(self, client):
        assert post(client, "/chat_question", prompt="write my essay").status_code == 404


class TestRefine:
    def test_question(self, client, llm_answer):
        llm_answer('"Which subtype?"\nextra')
        data = post(client, "/api/refine/question", original_query="cancer", answers=[]).json
        assert data["question"] == "Which subtype?"

    def test_malformed_answers_are_ignored(self, client, llm_answer):
        calls = llm_answer("Which subtype?")
        post(
            client,
            "/api/refine/question",
            original_query="cancer",
            answers=["junk", {"question": 5, "answer": "x"}, {"question": "Q1", "answer": "A1"}],
        )
        assert "Q1" in calls[0]["user"]
        assert "junk" not in calls[0]["user"]

    def test_keywords(self, client, llm_answer):
        llm_answer("Keywords: lung cancer EGFR")
        data = post(
            client,
            "/api/refine/keywords",
            original_query="cancer",
            answers=[{"question": "Q", "answer": "lung"}],
        ).json
        assert data["keywords"] == "lung cancer EGFR"

    def test_keywords_without_answers_skip_the_llm(self, client, llm_answer):
        calls = llm_answer("unused")
        data = post(client, "/api/refine/keywords", original_query="cancer", answers=[]).json
        assert data["keywords"] == "cancer"
        assert calls == []

    def test_keywords_fall_back_to_query(self, client, llm_answer):
        llm_answer(llm.LLMUnavailable("down"))
        data = post(
            client,
            "/api/refine/keywords",
            original_query="cancer",
            answers=[{"question": "Q", "answer": "lung"}],
        ).json
        assert data["keywords"] == "cancer"


class TestDeepSearch:
    def test_returns_uniform_protein_shape(self, client, monkeypatch):
        monkeypatch.setattr(uniprot, "search", lambda query, limit: [make_record()])
        protein = post(client, "/api/deep_search", query="egfr").json["proteins"][0]
        assert protein["source"] == "uniprot"
        assert protein["drugs"] == ""

    def test_requires_query(self, client):
        assert post(client, "/api/deep_search").status_code == 400


class TestRateLimit:
    def test_llm_endpoints_are_limited(self, llm_answer, uniprot_data):
        llm_answer()
        client = create_app({"LLM_RATE_LIMIT_PER_MINUTE": 2}).test_client()
        codes = [post(client, "/api/analyze", prompt="cancer").status_code for _ in range(3)]
        assert codes == [200, 200, 429]

    def test_limited_response_says_when_to_retry(self, llm_answer, uniprot_data):
        llm_answer()
        client = create_app({"LLM_RATE_LIMIT_PER_MINUTE": 1}).test_client()
        post(client, "/api/analyze", prompt="cancer")
        response = post(client, "/api/analyze", prompt="cancer")
        assert int(response.headers["Retry-After"]) > 0
        assert "error" in response.json


def test_frontend_never_builds_html_from_strings():
    """LLM output is untrusted, so these sinks would reintroduce XSS."""
    script = (Path(__file__).parent.parent / "static" / "script.js").read_text(encoding="utf-8")
    for sink in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write"):
        assert sink not in script
