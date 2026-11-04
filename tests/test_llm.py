from types import SimpleNamespace

import pytest
import requests

from services import config, llm

GROQ_MODELS = [model["id"] for model in config.PROVIDERS[0]["models"]]
HF_MODELS = [model["id"] for model in config.PROVIDERS[1]["models"]]


def reply(content):
    return SimpleNamespace(
        status_code=200,
        text="",
        json=lambda: {"choices": [{"message": {"content": content}}]},
    )


def failure(status, text=""):
    return SimpleNamespace(status_code=status, text=text, json=lambda: {})


class FakeSession:
    """Plays back one scripted outcome per request, and records the requests."""

    def __init__(self):
        self.outcomes = []
        self.calls = []

    def post(self, url, headers, json, timeout):
        self.calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    @property
    def models(self):
        return [call["json"]["model"] for call in self.calls]


@pytest.fixture
def fake_session(monkeypatch):
    fake = FakeSession()
    monkeypatch.setattr(llm, "session", fake)
    monkeypatch.setenv("GROQ_API_KEY", "groq-key")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    return fake


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


class TestStripThinking:
    def test_removes_reasoning(self):
        assert llm._strip_thinking("<think>hmm\nmore</think>\nAnswer") == "Answer"

    def test_removes_unfinished_reasoning(self):
        assert llm._strip_thinking("<think>cut off by the token limit") == ""

    def test_leaves_normal_text(self):
        assert llm._strip_thinking("Plain answer") == "Plain answer"


class TestProviders:
    def test_groq_is_preferred(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "a")
        monkeypatch.setenv("HF_TOKEN", "b")
        assert config.active_provider()["name"] == "Groq"

    def test_hugging_face_is_used_without_groq(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.setenv("HF_TOKEN", "b")
        assert config.active_provider()["name"] == "Hugging Face"
        assert config.model_ids() == HF_MODELS

    def test_no_keys(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        monkeypatch.delenv("HF_TOKEN", raising=False)
        assert config.active_provider() is None
        assert config.model_ids() == GROQ_MODELS

    def test_blank_key_counts_as_missing(self, monkeypatch):
        monkeypatch.setenv("GROQ_API_KEY", "  ")
        monkeypatch.delenv("HF_TOKEN", raising=False)
        assert config.active_provider() is None


class TestComplete:
    def test_sends_an_openai_compatible_request(self, fake_session):
        fake_session.outcomes = [reply("  answer  ")]
        assert llm.complete("sys", "user") == ("answer", GROQ_MODELS[0])
        call = fake_session.calls[0]
        assert call["url"] == "https://api.groq.com/openai/v1/chat/completions"
        assert call["headers"]["Authorization"] == "Bearer groq-key"
        assert call["json"]["messages"] == [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "user"},
        ]
        assert call["timeout"] == config.LLM_TIMEOUT_SECONDS

    def test_uses_hugging_face_when_it_is_the_only_key(self, fake_session, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY")
        monkeypatch.setenv("HF_TOKEN", "hf-key")
        fake_session.outcomes = [reply("answer")]
        assert llm.complete("sys", "user") == ("answer", HF_MODELS[0])
        assert fake_session.calls[0]["url"].startswith("https://router.huggingface.co/")
        assert fake_session.calls[0]["headers"]["Authorization"] == "Bearer hf-key"

    def test_requested_model_goes_first(self, fake_session):
        fake_session.outcomes = [reply("answer")]
        _, used = llm.complete("sys", "user", model=GROQ_MODELS[2])
        assert used == GROQ_MODELS[2]

    def test_unknown_model_uses_default(self, fake_session):
        fake_session.outcomes = [reply("answer")]
        _, used = llm.complete("sys", "user", model="attacker/expensive-model")
        assert used == GROQ_MODELS[0]

    def test_falls_back_on_errors_and_empty_content(self, fake_session):
        fake_session.outcomes = [failure(429), reply(None), reply("answer")]
        _, used = llm.complete("sys", "user")
        assert used == GROQ_MODELS[2]

    def test_falls_back_on_network_errors(self, fake_session):
        fake_session.outcomes = [requests.Timeout("slow"), reply("answer")]
        _, used = llm.complete("sys", "user")
        assert used == GROQ_MODELS[1]

    def test_falls_back_on_malformed_responses(self, fake_session):
        bad = SimpleNamespace(status_code=200, text="", json=lambda: {"choices": []})
        fake_session.outcomes = [bad, reply("answer")]
        _, used = llm.complete("sys", "user")
        assert used == GROQ_MODELS[1]

    def test_reasoning_only_answer_counts_as_empty(self, fake_session):
        fake_session.outcomes = [reply("<think>never finished"), reply("answer")]
        _, used = llm.complete("sys", "user")
        assert used == GROQ_MODELS[1]

    def test_cut_off_answer_tries_next_model(self, fake_session):
        cut_off = SimpleNamespace(
            status_code=200,
            text="",
            json=lambda: {
                "choices": [{"finish_reason": "length", "message": {"content": '[{"name": "EG'}}]
            },
        )
        fake_session.outcomes = [cut_off, reply("answer")]
        _, used = llm.complete("sys", "user")
        assert used == GROQ_MODELS[1]

    def test_model_params_are_only_sent_to_that_model(self, fake_session):
        fake_session.outcomes = [failure(500), reply("answer")]
        llm.complete("sys", "user")
        assert fake_session.calls[0]["json"]["reasoning_effort"] == "low"
        assert "reasoning_effort" not in fake_session.calls[1]["json"]

    def test_token_cap_only_applies_to_that_model(self, fake_session):
        fake_session.outcomes = [failure(500), reply("answer")]
        llm.complete("sys", "user", max_tokens=2500)
        assert fake_session.calls[0]["json"]["max_tokens"] == 2500
        assert fake_session.calls[1]["json"]["max_tokens"] == 1000

    def test_attempts_are_capped(self, fake_session):
        fake_session.outcomes = [failure(503)] * 10
        with pytest.raises(llm.LLMUnavailable):
            llm.complete("sys", "user")
        assert len(fake_session.calls) == config.LLM_MAX_ATTEMPTS

    def test_rejected_key_stops_immediately(self, fake_session):
        fake_session.outcomes = [failure(401), reply("never reached")]
        with pytest.raises(llm.LLMAuthError, match="rejected"):
            llm.complete("sys", "user")
        assert len(fake_session.calls) == 1

    def test_generic_403_tries_next_model(self, fake_session):
        fake_session.outcomes = [failure(403, "This model is gated"), reply("answer")]
        _, used = llm.complete("sys", "user")
        assert used == GROQ_MODELS[1]

    def test_missing_permission_stops_immediately(self, fake_session):
        fake_session.outcomes = [failure(403, "does not have sufficient permissions"), reply("x")]
        with pytest.raises(llm.LLMAuthError, match="permission"):
            llm.complete("sys", "user")
        assert len(fake_session.calls) == 1

    def test_exhausted_credits_stop_immediately_with_a_clear_message(self, fake_session):
        fake_session.outcomes = [failure(402), reply("never reached")]
        with pytest.raises(llm.LLMUnavailable, match="no credits"):
            llm.complete("sys", "user")
        assert len(fake_session.calls) == 1

    def test_no_key_raises_without_calling(self, fake_session, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY")
        with pytest.raises(llm.LLMAuthError, match="not configured"):
            llm.complete("sys", "user")
        assert fake_session.calls == []

    def test_key_is_never_logged(self, fake_session, caplog):
        fake_session.outcomes = [failure(500, "server error")] * 3
        with pytest.raises(llm.LLMUnavailable):
            llm.complete("sys", "user")
        assert "groq-key" not in caplog.text
