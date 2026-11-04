from types import SimpleNamespace

import pytest

from services import config, llm


def chat_response(content):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])


class HttpError(Exception):
    def __init__(self, status):
        super().__init__(f"HTTP {status}")
        self.response = SimpleNamespace(status_code=status)


class FakeClient:
    """Plays back one scripted outcome per model that is tried."""

    outcomes = []
    calls = []
    tokens = []

    def __init__(self, token=None, timeout=None):
        FakeClient.tokens.append(token)

    def chat_completion(self, messages, model, max_tokens, temperature):
        FakeClient.calls.append(model)
        outcome = FakeClient.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return chat_response(outcome)


@pytest.fixture
def fake_client(monkeypatch):
    FakeClient.outcomes = []
    FakeClient.calls = []
    FakeClient.tokens = []
    monkeypatch.setattr(llm, "InferenceClient", FakeClient)
    monkeypatch.setenv("HF_TOKEN", "server-token")
    return FakeClient


class TestParseTargets:
    def test_parses_array_and_insights(self):
        text = (
            '[{"name": "EGFR", "uniprot_id": "P00533", "relevance": "Driver", "drugs": "Erlotinib"}]\n'
            "INSIGHTS: Target the kinase domain."
        )
        targets, insights = llm.parse_targets(text)
        assert targets[0]["uniprot_id"] == "P00533"
        assert targets[0]["drugs"] == "Erlotinib"
        assert insights == "Target the kinase domain."

    def test_handles_code_fences_and_leading_prose(self):
        text = 'Sure, here you go:\n```json\n[{"name": "EGFR", "uniprot_id": "P00533"}]\n```'
        targets, _ = llm.parse_targets(text)
        assert [t["uniprot_id"] for t in targets] == ["P00533"]

    def test_skips_bracketed_text_before_the_array(self):
        text = 'See [ref 1] and [2].\n[{"name": "EGFR", "uniprot_id": "P00533"}]'
        targets, _ = llm.parse_targets(text)
        assert len(targets) == 1

    def test_survives_nested_brackets_in_values(self):
        text = '[{"name": "EGFR [HER1]", "uniprot_id": "P00533", "drugs": "A [B]"}]'
        targets, _ = llm.parse_targets(text)
        assert targets[0]["name"] == "EGFR [HER1]"

    def test_drops_invalid_duplicate_and_non_object_items(self):
        text = (
            '[{"uniprot_id": "NOT-AN-ID"}, "text", {"name": "no id"},'
            ' {"uniprot_id": "p00533"}, {"uniprot_id": "P00533"}]'
        )
        targets, _ = llm.parse_targets(text)
        assert [t["uniprot_id"] for t in targets] == ["P00533"]

    @pytest.mark.parametrize("text", ["", "no json here", '[{"name": "truncated', "[1, 2"])
    def test_bad_output_returns_nothing(self, text):
        targets, _ = llm.parse_targets(text)
        assert targets == []

    def test_non_string_fields_are_blanked(self):
        targets, _ = llm.parse_targets('[{"uniprot_id": "P00533", "drugs": ["a"], "name": 5}]')
        assert targets[0]["drugs"] == ""
        assert targets[0]["name"] == ""


class TestCleaners:
    def test_keywords_strip_prefix_and_syntax(self):
        assert llm.clean_keywords('Keywords: "lung cancer" (EGFR) OR *') == "lung cancer EGFR OR"

    def test_keywords_use_first_line_and_limit(self):
        assert llm.clean_keywords("a1 b2 c3 d4 e5 f6 g7 h8 i9\nexplanation") == "a1 b2 c3 d4 e5 f6 g7 h8"

    def test_empty_keywords(self):
        assert llm.clean_keywords("  ") == ""

    def test_question_keeps_first_line(self):
        assert llm.clean_question('"Which subtype?"\nMore text') == "Which subtype?"


class TestComplete:
    def test_returns_first_success(self, fake_client):
        fake_client.outcomes = ["  answer  "]
        assert llm.complete("sys", "user") == ("answer", config.DEFAULT_MODEL)

    def test_requested_model_goes_first(self, fake_client):
        fake_client.outcomes = ["answer"]
        chosen = config.MODEL_IDS[2]
        _, used = llm.complete("sys", "user", model=chosen)
        assert used == chosen

    def test_unknown_model_uses_default(self, fake_client):
        fake_client.outcomes = ["answer"]
        _, used = llm.complete("sys", "user", model="attacker/expensive-model")
        assert used == config.DEFAULT_MODEL

    def test_falls_back_on_error_and_empty_content(self, fake_client):
        fake_client.outcomes = [HttpError(503), None, "answer"]
        _, used = llm.complete("sys", "user")
        assert used == config.MODEL_IDS[2]

    def test_attempts_are_capped(self, fake_client):
        fake_client.outcomes = [HttpError(503)] * 10
        with pytest.raises(llm.LLMUnavailable):
            llm.complete("sys", "user")
        assert len(fake_client.calls) == config.LLM_MAX_ATTEMPTS

    def test_bad_server_token_stops_immediately(self, fake_client):
        fake_client.outcomes = [HttpError(401), "never reached"]
        with pytest.raises(llm.LLMAuthError):
            llm.complete("sys", "user")
        assert len(fake_client.calls) == 1

    def test_server_403_tries_next_model(self, fake_client):
        # One gated model shouldn't stop the fallback chain.
        fake_client.outcomes = [HttpError(403), "answer"]
        _, used = llm.complete("sys", "user")
        assert used == config.MODEL_IDS[1]

    def test_token_without_inference_permission_stops_immediately(self, fake_client):
        error = HttpError(403)
        error.args = ("403 Forbidden: does not have sufficient permissions to call Inference Providers",)
        fake_client.outcomes = [error, "never reached"]
        with pytest.raises(llm.LLMAuthError, match="Inference Providers"):
            llm.complete("sys", "user")
        assert len(fake_client.calls) == 1

    def test_exhausted_credits_stop_immediately_with_a_clear_message(self, fake_client):
        fake_client.outcomes = [HttpError(402), "never reached"]
        with pytest.raises(llm.LLMUnavailable, match="no inference credits"):
            llm.complete("sys", "user")
        assert len(fake_client.calls) == 1

    def test_user_token_takes_priority(self, fake_client):
        fake_client.outcomes = ["answer"]
        llm.complete("sys", "user", token="user-token")
        assert fake_client.tokens == ["user-token"]

    def test_no_token_raises_without_calling(self, fake_client, monkeypatch):
        monkeypatch.delenv("HF_TOKEN")
        with pytest.raises(llm.LLMAuthError):
            llm.complete("sys", "user")
        assert fake_client.calls == []
