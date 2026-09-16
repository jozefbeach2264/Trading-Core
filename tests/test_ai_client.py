"""Defects B, C (findings 2, 6) + the Grok → local llama-server swap: every failure path
returns a Reanalyze verdict (no UnboundLocalError), the fallback confidence is a real
mean, confidence is clamped, and the request is shaped for an OpenAI-compatible local server."""
import json
import math

import httpx
import pytest

import ai_client as ai_client_module
from ai_client import AIClient
from conftest import run

STRONG_LONG = {"open": 2854.85, "close": 2856.41, "volume": 63.81, "direction": "LONG",
               "reversal_likelihood_score": 0.10, "cts_score": 0.91, "orderbook_score": 0.95}


@pytest.fixture
def records(monkeypatch):
    seen = []
    monkeypatch.setattr(ai_client_module, "log_ai_decision", lambda _logger, entry: seen.append(entry))
    return seen


@pytest.fixture
def client(config):
    c = AIClient(config)
    yield c
    run(c.close())


def _mock_post(client, *, raises=None, status=200, payload=None, capture=None):
    async def fake_post(url, **kwargs):
        if capture is not None:
            capture.update({"url": url, **kwargs})
        if raises is not None:
            raise raises
        request = httpx.Request("POST", url)
        return httpx.Response(status, json=payload if payload is not None else {}, request=request)
    client.client.post = fake_post


def _chat_payload(content, finish_reason="stop"):
    return {"choices": [{"message": {"role": "assistant", "content": content}, "finish_reason": finish_reason}],
            "usage": {"prompt_tokens": 120, "completion_tokens": 30, "total_tokens": 150}, "created": 1}


def test_timeout_returns_reanalyze_with_latency(client, records):
    _mock_post(client, raises=httpx.ReadTimeout("slow"))
    verdict = run(client.get_ai_verdict(STRONG_LONG))
    assert verdict["action"] == "Reanalyze" and verdict["confidence"] == 0.0
    timeout_records = [r for r in records if r["type"] == "timeout"]
    assert len(timeout_records) == 1
    assert isinstance(timeout_records[0]["latency_ms"], float)


def test_connect_error_returns_reanalyze(client, records):
    _mock_post(client, raises=httpx.ConnectError("refused"))
    verdict = run(client.get_ai_verdict(STRONG_LONG))
    assert verdict["action"] == "Reanalyze"
    assert any(r["type"] == "api_error" and isinstance(r["latency_ms"], float) for r in records)


def test_http_error_returns_reanalyze(client, records):
    _mock_post(client, status=500, payload={"error": "boom"})
    verdict = run(client.get_ai_verdict(STRONG_LONG))
    assert verdict["action"] == "Reanalyze"
    assert any(r["type"] == "api_error" for r in records)


def test_valid_verdict_is_parsed_and_confidence_clamped(client, records):
    _mock_post(client, payload=_chat_payload(json.dumps({"action": "execute", "confidence": 1.7, "reasoning": "ok"})))
    verdict = run(client.get_ai_verdict(STRONG_LONG))
    assert verdict["action"] == "Execute"
    assert verdict["confidence"] == 1.0
    assert verdict["reasoning"] == "ok"
    assert any(r["type"] == "api_verdict" for r in records)


def test_negative_confidence_clamped_to_zero(client, records):
    _mock_post(client, payload=_chat_payload(json.dumps({"action": "Abort", "confidence": -0.2, "reasoning": "x"})))
    assert run(client.get_ai_verdict(STRONG_LONG))["confidence"] == 0.0


def test_nan_confidence_is_rejected(client, records):
    _mock_post(client, payload=_chat_payload('{"action": "Execute", "confidence": NaN, "reasoning": "x"}'))
    verdict = run(client.get_ai_verdict(STRONG_LONG))
    assert not (verdict["action"] == "Execute" and math.isnan(verdict["confidence"]))
    assert 0.0 <= verdict["confidence"] <= 1.0


def test_empty_content_uses_fallback_but_never_executes_by_default(client, records):
    _mock_post(client, payload=_chat_payload(""))
    verdict = run(client.get_ai_verdict(STRONG_LONG))
    assert verdict["action"] == "Reanalyze"
    assert verdict["confidence"] >= 0.7          # the corrected mean is still reported
    assert "AI_FALLBACK_CAN_EXECUTE" in verdict["reasoning"]
    assert any(r["type"] == "fallback" for r in records)


def test_fallback_execute_is_an_operator_opt_in(config, records):
    config.ai_fallback_can_execute = True
    client = AIClient(config)
    _mock_post(client, payload=_chat_payload(""))
    verdict = run(client.get_ai_verdict(STRONG_LONG))
    run(client.close())
    assert verdict["action"] == "Execute" and verdict["confidence"] >= 0.7


def test_malformed_json_uses_fallback(client, records):
    _mock_post(client, payload=_chat_payload("not json at all"))
    assert run(client.get_ai_verdict(STRONG_LONG))["action"] in ("Execute", "Abort", "Reanalyze")
    assert any(r["type"] == "fallback" for r in records)


def test_unknown_action_uses_fallback(client, records):
    _mock_post(client, payload=_chat_payload(json.dumps({"action": "Buy", "confidence": 0.9, "reasoning": "x"})))
    verdict = run(client.get_ai_verdict(STRONG_LONG))
    assert verdict["action"] in ("Execute", "Abort", "Reanalyze")
    assert any(r["type"] == "fallback" for r in records)


def test_fallback_confidence_is_a_mean_not_capped(client):
    verdict = client._fallback_from_context(STRONG_LONG)
    expected = ((1.0 - 0.10) + 0.91 + 0.95) / 3.0
    assert verdict["action"] == "Reanalyze"       # default: heuristic may not open a position
    assert abs(verdict["confidence"] - expected) < 1e-4
    client.config.ai_fallback_can_execute = True
    assert client._fallback_from_context(STRONG_LONG)["action"] == "Execute"


def test_fallback_unknown_direction_is_reanalyze(client):
    client.config.ai_fallback_can_execute = True
    verdict = client._fallback_from_context({**STRONG_LONG, "direction": "N/A"})
    assert verdict["action"] == "Reanalyze" and verdict["confidence"] == 0.0


def test_fallback_high_reversal_risk_does_not_execute(client):
    risky = {**STRONG_LONG, "reversal_likelihood_score": 0.95}
    assert client._fallback_from_context(risky)["action"] != "Execute"


def test_request_is_shaped_for_local_openai_compatible_server(client, config, records):
    captured = {}
    _mock_post(client, payload=_chat_payload(json.dumps({"action": "Abort", "confidence": 0.5, "reasoning": "x"})), capture=captured)
    run(client.get_ai_verdict(STRONG_LONG))
    body = captured["json"]
    assert captured["url"] == f"{config.ai_provider_url}/chat/completions"
    assert body["model"] == config.ai_model
    assert "max_tokens" in body and "max_completion_tokens" not in body
    assert body["max_tokens"] == config.ai_max_tokens
    assert body["chat_template_kwargs"]["enable_thinking"] is False
    assert body["response_format"]["type"] == "json_schema"
    schema = body["response_format"]["json_schema"]["schema"]
    assert schema["additionalProperties"] is False
    assert schema["properties"]["reasoning"]["maxLength"] == config.ai_reasoning_max_chars
    assert body["stream"] is False
    assert "Authorization" not in captured.get("headers", {})
    assert json.loads(body["messages"][1]["content"].split("Market Data: ", 1)[1]) == STRONG_LONG


def test_authorization_header_sent_when_key_configured(config, records):
    config.ai_api_key = "sk-test"
    client = AIClient(config)
    captured = {}
    _mock_post(client, payload=_chat_payload(json.dumps({"action": "Abort", "confidence": 0.5, "reasoning": "x"})), capture=captured)
    run(client.get_ai_verdict(STRONG_LONG))
    run(client.close())
    assert captured["headers"]["Authorization"] == "Bearer sk-test"


def test_reasoning_can_be_dropped_from_the_schema(config, records):
    config.ai_reasoning_max_chars = 0
    client = AIClient(config)
    captured = {}
    _mock_post(client, payload=_chat_payload(json.dumps({"action": "Abort", "confidence": 0.5})), capture=captured)
    verdict = run(client.get_ai_verdict(STRONG_LONG))
    run(client.close())
    schema = captured["json"]["response_format"]["json_schema"]["schema"]
    assert "reasoning" not in schema["properties"] and schema["required"] == ["action", "confidence"]
    assert verdict["action"] == "Abort" and verdict["reasoning"] == ""
