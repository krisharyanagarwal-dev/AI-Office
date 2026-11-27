"""Entry-point coverage tests for llm_decide and llm_narrate.

These two functions were previously only ever mocked in other tests — never
exercised directly. They call _chat (MLX first, then external providers), so
_chat is stubbed here to keep the tests deterministic and offline.
"""

from __future__ import annotations

from dost import dost_main


def _stub_chat(monkeypatch, result):
    monkeypatch.setattr(dost_main, "_chat", lambda messages, temperature, max_tokens: result)


def test_llm_decide_returns_command_text_when_provider_available(monkeypatch):
    _stub_chat(monkeypatch, {"text": "COMMAND:register", "provider": "mlx_local"})

    text = dost_main.llm_decide("register RELIANCE.NS", "LIVE CONTEXT")

    assert text == "COMMAND:register"


def test_llm_decide_returns_natural_text_when_provider_available(monkeypatch):
    _stub_chat(monkeypatch, {"text": "I can help with that research idea.", "provider": "mlx_local"})

    text = dost_main.llm_decide("what do you think about NSE options?", "LIVE CONTEXT")

    assert text == "I can help with that research idea."


def test_llm_decide_returns_empty_string_when_no_provider(monkeypatch):
    _stub_chat(monkeypatch, None)

    text = dost_main.llm_decide("anything at all", "LIVE CONTEXT")

    assert text == ""


def test_llm_decide_strips_whitespace(monkeypatch):
    _stub_chat(monkeypatch, {"text": "  COMMAND:gate  \n", "provider": "mlx_local"})

    text = dost_main.llm_decide("gate the strategy", "LIVE CONTEXT")

    assert text == "COMMAND:gate"


def test_llm_decide_includes_style_in_prompt(monkeypatch):
    captured = {}

    def fake_chat(messages, temperature, max_tokens):
        captured["system"] = messages[0]["content"]
        return {"text": "ok", "provider": "mlx_local"}

    monkeypatch.setattr(dost_main, "_chat", fake_chat)

    dost_main.llm_decide("register", "CTX", style="Be brief.")

    assert "Be brief." in captured["system"]
    assert "CTX" in captured["system"]
    assert "register" in captured["system"]


def test_llm_decide_without_style_omits_style_block(monkeypatch):
    captured = {}

    def fake_chat(messages, temperature, max_tokens):
        captured["system"] = messages[0]["content"]
        return {"text": "ok", "provider": "mlx_local"}

    monkeypatch.setattr(dost_main, "_chat", fake_chat)

    dost_main.llm_decide("register", "CTX")

    assert "STYLE:" not in captured["system"]


def test_llm_narrate_returns_narration_when_provider_available(monkeypatch):
    _stub_chat(monkeypatch, {
        "text": "The backtest passed with a net P&L of ₹12,345.",
        "provider": "mlx_local",
    })

    text = dost_main.llm_narrate("backtest", "net_pnl=12345\nconfirmed=true", "LIVE CONTEXT")

    assert text == "The backtest passed with a net P&L of ₹12,345."


def test_llm_narrate_returns_empty_string_when_no_provider(monkeypatch):
    _stub_chat(monkeypatch, None)

    text = dost_main.llm_narrate("backtest", "some output", "LIVE CONTEXT")

    assert text == ""


def test_llm_narrate_strips_whitespace(monkeypatch):
    _stub_chat(monkeypatch, {"text": "  All systems nominal.  \n", "provider": "mlx_local"})

    text = dost_main.llm_narrate("status", "ok", "LIVE CONTEXT")

    assert text == "All systems nominal."


def test_llm_narrate_passes_command_output_context(monkeypatch):
    captured = {}

    def fake_chat(messages, temperature, max_tokens):
        captured["system"] = messages[0]["content"]
        captured["user"] = messages[1]["content"]
        return {"text": "ok", "provider": "mlx_local"}

    monkeypatch.setattr(dost_main, "_chat", fake_chat)

    dost_main.llm_narrate("gate", "result=pass", "MY CTX")

    assert "MY CTX" in captured["system"]
    assert "gate" in captured["system"]
    assert "result=pass" in captured["system"]
    assert captured["user"] == "Narrate the output of the gate command."
