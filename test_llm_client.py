# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""Backend selection and transport for llm_client. Run: python3 -m pytest test_llm_client.py -v"""
import io
import json
import socket
import sys
import types
from urllib.error import URLError

import pytest

import llm_client


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Every test starts from an unconfigured environment."""
    for var in (
        "DOCUBROWSE_LLM_BACKEND",
        "DOCUBROWSE_LLM_MODEL",
        "DOCUBROWSE_LLM_API_BASE",
        "DOCUBROWSE_LLM_API_KEY",
        "DOCUBROWSE_LLM_MAX_TOKENS",
    ):
        monkeypatch.delenv(var, raising=False)


class _Resp(io.BytesIO):
    """Minimal stand-in for the object urlopen yields as a context manager."""

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _ollama_ok(text="a synopsis"):
    return _Resp(json.dumps({"response": text}).encode("utf-8"))


# ── backend selection ─────────────────────────────────────────────────────────

def test_backend_defaults_to_ollama():
    assert llm_client.backend() == "ollama"


def test_backend_honours_the_env_var(monkeypatch):
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    assert llm_client.backend() == "litellm"


def test_backend_is_case_and_space_insensitive(monkeypatch):
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "  LiteLLM ")
    assert llm_client.backend() == "litellm"


def test_unknown_backend_is_rejected(monkeypatch):
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "gpt4all")
    with pytest.raises(llm_client.LLMError, match="Unknown DOCUBROWSE_LLM_BACKEND"):
        llm_client.backend()


# ── model resolution ──────────────────────────────────────────────────────────

def test_ollama_uses_the_per_language_model():
    assert llm_client.resolve_model("dolphin3:latest") == "dolphin3:latest"


def test_litellm_requires_its_own_model(monkeypatch):
    # The per-language names are bare Ollama tags with no provider, so LiteLLM
    # cannot route them; failing loudly beats sending "dolphin3:latest".
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    with pytest.raises(llm_client.LLMError, match="requires DOCUBROWSE_LLM_MODEL"):
        llm_client.resolve_model("dolphin3:latest")


def test_litellm_model_overrides_the_default(monkeypatch):
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    monkeypatch.setenv("DOCUBROWSE_LLM_MODEL", "anthropic/claude-opus-4-7")
    assert llm_client.resolve_model("dolphin3:latest") == "anthropic/claude-opus-4-7"


def test_describe_reports_each_backend(monkeypatch):
    assert llm_client.describe("dolphin3:latest") == "ollama (dolphin3:latest)"

    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    monkeypatch.setenv("DOCUBROWSE_LLM_MODEL", "gpt-5.5")
    assert llm_client.describe("dolphin3:latest") == "litellm (gpt-5.5) direct"

    monkeypatch.setenv("DOCUBROWSE_LLM_API_BASE", "http://localhost:4000")
    assert "via http://localhost:4000" in llm_client.describe("dolphin3:latest")


def test_describe_does_not_raise_when_unconfigured(monkeypatch):
    # Status output must never blow up just because the model is unset.
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    assert "unconfigured" in llm_client.describe("dolphin3:latest")


# ── ollama backend ────────────────────────────────────────────────────────────

def test_ollama_posts_the_native_payload(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["body"] = json.loads(request.data.decode("utf-8"))
        captured["timeout"] = timeout
        return _ollama_ok()

    monkeypatch.setattr(llm_client, "urlopen", fake_urlopen)

    text = llm_client.generate(
        "summarise this",
        model="dolphin3:latest",
        host="http://localhost:11434",
        timeout=180,
        options={"num_predict": 1},
        think=False,
    )

    assert text == "a synopsis"
    assert captured["url"] == "http://localhost:11434/api/generate"
    assert captured["timeout"] == 180
    assert captured["body"] == {
        "model": "dolphin3:latest",
        "prompt": "summarise this",
        "stream": False,
        "options": {"num_predict": 1},
        "think": False,
    }


def test_ollama_omits_optional_keys_when_unset(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=None):
        captured["body"] = json.loads(request.data.decode("utf-8"))
        return _ollama_ok()

    monkeypatch.setattr(llm_client, "urlopen", fake_urlopen)
    llm_client.generate("hi", model="m", host="http://h:1", timeout=5)

    assert "options" not in captured["body"]
    assert "think" not in captured["body"]


def test_ollama_returns_empty_string_for_an_empty_response(monkeypatch):
    # The caller distinguishes empty from failed, so this must not raise.
    monkeypatch.setattr(llm_client, "urlopen", lambda *a, **k: _Resp(b'{"response": ""}'))
    assert llm_client.generate("hi", model="m", host="http://h:1", timeout=5) == ""


def test_ollama_socket_timeout_becomes_llm_timeout(monkeypatch):
    def fake_urlopen(*_a, **_k):
        raise socket.timeout("timed out")

    monkeypatch.setattr(llm_client, "urlopen", fake_urlopen)
    with pytest.raises(llm_client.LLMTimeout):
        llm_client.generate("hi", model="m", host="http://h:1", timeout=5)


def test_ollama_urlerror_wrapping_a_timeout_becomes_llm_timeout(monkeypatch):
    # urllib wraps a read timeout in URLError, so the reason has to be unwrapped
    # or a slow model load gets misreported as a hard error.
    def fake_urlopen(*_a, **_k):
        raise URLError(socket.timeout("timed out"))

    monkeypatch.setattr(llm_client, "urlopen", fake_urlopen)
    with pytest.raises(llm_client.LLMTimeout):
        llm_client.generate("hi", model="m", host="http://h:1", timeout=5)


def test_ollama_connection_refused_becomes_llm_error(monkeypatch):
    def fake_urlopen(*_a, **_k):
        raise URLError(ConnectionRefusedError("refused"))

    monkeypatch.setattr(llm_client, "urlopen", fake_urlopen)
    with pytest.raises(llm_client.LLMError) as excinfo:
        llm_client.generate("hi", model="m", host="http://h:1", timeout=5)
    assert not isinstance(excinfo.value, llm_client.LLMTimeout)


def test_ollama_malformed_json_becomes_llm_error(monkeypatch):
    monkeypatch.setattr(llm_client, "urlopen", lambda *a, **k: _Resp(b"not json"))
    with pytest.raises(llm_client.LLMError):
        llm_client.generate("hi", model="m", host="http://h:1", timeout=5)


# ── litellm backend ───────────────────────────────────────────────────────────

def _install_fake_litellm(monkeypatch, *, content="a synopsis", raises=None):
    """Install a stub litellm module and return the captured request dict."""
    captured = {}

    def completion(**kwargs):
        captured.update(kwargs)
        if raises is not None:
            raise raises
        message = types.SimpleNamespace(content=content)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=message)])

    module = types.ModuleType("litellm")
    module.completion = completion
    monkeypatch.setitem(sys.modules, "litellm", module)
    return captured


def test_litellm_sends_messages_and_drops_params(monkeypatch):
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    monkeypatch.setenv("DOCUBROWSE_LLM_MODEL", "anthropic/claude-opus-4-7")
    captured = _install_fake_litellm(monkeypatch)

    text = llm_client.generate(
        "summarise this", model="dolphin3:latest", host="http://unused", timeout=180
    )

    assert text == "a synopsis"
    assert captured["model"] == "anthropic/claude-opus-4-7"
    assert captured["messages"] == [{"role": "user", "content": "summarise this"}]
    assert captured["timeout"] == 180
    # Providers reject each other's parameters; without this one prompt cannot
    # serve every model.
    assert captured["drop_params"] is True


def test_litellm_direct_mode_sends_no_endpoint(monkeypatch):
    # No gateway configured means LiteLLM routes to the vendor itself, which is
    # the mode that needs no extra infrastructure at all.
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    monkeypatch.setenv("DOCUBROWSE_LLM_MODEL", "gpt-5.5")
    captured = _install_fake_litellm(monkeypatch)

    llm_client.generate("hi", model="m", host="http://unused", timeout=5)

    assert "api_base" not in captured
    assert "api_key" not in captured


def test_litellm_gateway_mode_forwards_endpoint_and_key(monkeypatch):
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    monkeypatch.setenv("DOCUBROWSE_LLM_MODEL", "gpt-5.5")
    monkeypatch.setenv("DOCUBROWSE_LLM_API_BASE", "http://localhost:4000/")
    monkeypatch.setenv("DOCUBROWSE_LLM_API_KEY", "sk-gateway")
    captured = _install_fake_litellm(monkeypatch)

    llm_client.generate("hi", model="m", host="http://unused", timeout=5)

    assert captured["api_base"] == "http://localhost:4000"   # trailing slash trimmed
    assert captured["api_key"] == "sk-gateway"


def test_litellm_gateway_mode_prefixes_the_model_for_forwarding(monkeypatch):
    # Regression: without the litellm_proxy/ prefix LiteLLM resolves the vendor
    # from the model name and calls it directly, so a configured gateway is
    # silently bypassed. Caught live: "gemini-2.5-flash" went to Vertex AI and
    # failed on missing Google credentials despite api_base being set.
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    monkeypatch.setenv("DOCUBROWSE_LLM_MODEL", "gemini-2.5-flash")
    monkeypatch.setenv("DOCUBROWSE_LLM_API_BASE", "http://localhost:4000")
    captured = _install_fake_litellm(monkeypatch)

    llm_client.generate("hi", model="m", host="http://unused", timeout=5)

    assert captured["model"] == "litellm_proxy/gemini-2.5-flash"


def test_litellm_direct_mode_does_not_prefix_the_model(monkeypatch):
    # With no gateway, the bare name is what lets LiteLLM route to the vendor.
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    monkeypatch.setenv("DOCUBROWSE_LLM_MODEL", "anthropic/claude-opus-4-7")
    captured = _install_fake_litellm(monkeypatch)

    llm_client.generate("hi", model="m", host="http://unused", timeout=5)

    assert captured["model"] == "anthropic/claude-opus-4-7"


def test_litellm_does_not_double_prefix(monkeypatch):
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    monkeypatch.setenv("DOCUBROWSE_LLM_MODEL", "litellm_proxy/gpt-5.5")
    monkeypatch.setenv("DOCUBROWSE_LLM_API_BASE", "http://localhost:4000")
    captured = _install_fake_litellm(monkeypatch)

    llm_client.generate("hi", model="m", host="http://unused", timeout=5)

    assert captured["model"] == "litellm_proxy/gpt-5.5"


def test_litellm_maps_num_predict_to_max_tokens(monkeypatch):
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    monkeypatch.setenv("DOCUBROWSE_LLM_MODEL", "gpt-5.5")
    captured = _install_fake_litellm(monkeypatch)

    llm_client.generate(
        "hi", model="m", host="http://unused", timeout=5, options={"num_predict": 1}
    )

    assert captured["max_tokens"] == 1


def test_litellm_max_tokens_env_wins(monkeypatch):
    # The env cap is the guard against hybrid reasoning models spending the
    # whole budget thinking, which is what `think: False` does for Ollama.
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    monkeypatch.setenv("DOCUBROWSE_LLM_MODEL", "gpt-5.5")
    monkeypatch.setenv("DOCUBROWSE_LLM_MAX_TOKENS", "512")
    captured = _install_fake_litellm(monkeypatch)

    llm_client.generate(
        "hi", model="m", host="http://unused", timeout=5, options={"num_predict": 1}
    )

    assert captured["max_tokens"] == 512


def test_litellm_rejects_a_non_integer_max_tokens(monkeypatch):
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    monkeypatch.setenv("DOCUBROWSE_LLM_MODEL", "gpt-5.5")
    monkeypatch.setenv("DOCUBROWSE_LLM_MAX_TOKENS", "lots")
    _install_fake_litellm(monkeypatch)

    with pytest.raises(llm_client.LLMError, match="must be an integer"):
        llm_client.generate("hi", model="m", host="http://unused", timeout=5)


def test_litellm_think_is_not_forwarded(monkeypatch):
    # `think` is an Ollama parameter; forwarding it would be dropped anyway.
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    monkeypatch.setenv("DOCUBROWSE_LLM_MODEL", "gpt-5.5")
    captured = _install_fake_litellm(monkeypatch)

    llm_client.generate("hi", model="m", host="http://unused", timeout=5, think=False)

    assert "think" not in captured


def test_litellm_timeout_becomes_llm_timeout(monkeypatch):
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    monkeypatch.setenv("DOCUBROWSE_LLM_MODEL", "gpt-5.5")

    class APITimeoutError(Exception):
        pass

    _install_fake_litellm(monkeypatch, raises=APITimeoutError("took too long"))

    with pytest.raises(llm_client.LLMTimeout):
        llm_client.generate("hi", model="m", host="http://unused", timeout=5)


def test_litellm_other_failures_become_llm_error(monkeypatch):
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    monkeypatch.setenv("DOCUBROWSE_LLM_MODEL", "gpt-5.5")

    class AuthenticationError(Exception):
        pass

    _install_fake_litellm(monkeypatch, raises=AuthenticationError("bad key"))

    with pytest.raises(llm_client.LLMError) as excinfo:
        llm_client.generate("hi", model="m", host="http://unused", timeout=5)
    assert not isinstance(excinfo.value, llm_client.LLMTimeout)


def test_litellm_empty_content_returns_empty_string(monkeypatch):
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    monkeypatch.setenv("DOCUBROWSE_LLM_MODEL", "gpt-5.5")
    _install_fake_litellm(monkeypatch, content=None)

    assert llm_client.generate("hi", model="m", host="http://unused", timeout=5) == ""


def test_litellm_missing_package_explains_how_to_install(monkeypatch):
    monkeypatch.setenv("DOCUBROWSE_LLM_BACKEND", "litellm")
    monkeypatch.setenv("DOCUBROWSE_LLM_MODEL", "gpt-5.5")
    monkeypatch.setitem(sys.modules, "litellm", None)   # import returns None -> ImportError

    with pytest.raises(llm_client.LLMError, match="pip install"):
        llm_client.generate("hi", model="m", host="http://unused", timeout=5)
