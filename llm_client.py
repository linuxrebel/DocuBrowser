#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 James Sparenberg
"""Text-generation transport for DocuBrowse, with a pluggable backend.

DocuBrowse talks to Ollama's native ``/api/generate`` endpoint. That keeps the
default install dependency-free and entirely local, but it also means the only
models reachable are the ones Ollama itself serves: anything speaking the
OpenAI wire format (including a self-hosted LiteLLM gateway) cannot be used,
because the request shape and the response shape are both different.

This module isolates that transport behind one ``generate()`` call so a second
backend can exist without the rest of the codebase caring which one is active:

``ollama`` (default)
    Exactly the previous behaviour: ``urllib`` POST to ``{host}/api/generate``,
    no third-party dependency, no network beyond the configured Ollama host.

``litellm``
    Routes through `LiteLLM <https://docs.litellm.ai/>`_, which speaks one
    interface to 100+ providers. With no endpoint configured it calls the
    vendor directly using that vendor's own key; with ``DOCUBROWSE_LLM_API_BASE``
    set it forwards to a self-hosted gateway, which adds centralized cost
    tracking, budgets, rate limiting and fallbacks. Opt-in, and ``litellm`` is
    an optional dependency imported lazily, so nothing changes for a default
    install.

Environment:
    DOCUBROWSE_LLM_BACKEND    "ollama" (default) or "litellm"
    DOCUBROWSE_LLM_MODEL      model name for the litellm backend. Required
                              there, because the per-language models in
                              lang_models.py are bare Ollama tags
                              ("dolphin3:latest") that LiteLLM cannot route.
    DOCUBROWSE_LLM_API_BASE   optional gateway URL for the litellm backend
    DOCUBROWSE_LLM_API_KEY    optional key for the litellm backend
    DOCUBROWSE_LLM_MAX_TOKENS optional output cap for the litellm backend

Both backends raise only :class:`LLMTimeout` and :class:`LLMError`, so callers
map failures the same way regardless of which one is in use.
"""

import json
import os
import socket
from urllib.error import URLError
from urllib.request import Request, urlopen

OLLAMA_BACKEND = "ollama"
LITELLM_BACKEND = "litellm"

# LiteLLM's own prefix meaning "forward this to my gateway rather than
# resolving the vendor yourself".
PROXY_PREFIX = "litellm_proxy/"

_LITELLM_IMPORT_HINT = (
    "The 'litellm' package is required for DOCUBROWSE_LLM_BACKEND=litellm. "
    "Install it with: pip install 'litellm>=1.92.0,<1.101.0'"
)


class LLMError(RuntimeError):
    """A generation request failed for any non-timeout reason."""


class LLMTimeout(LLMError):
    """A generation request timed out.

    Kept distinct because the synopsis path reports a timeout differently: it
    usually means the model is still being loaded into memory after a fresh
    start, which is worth retrying, unlike a genuine error.
    """


def backend() -> str:
    """Return the active backend name, defaulting to Ollama."""
    choice = (os.environ.get("DOCUBROWSE_LLM_BACKEND") or OLLAMA_BACKEND).strip().lower()
    if choice not in (OLLAMA_BACKEND, LITELLM_BACKEND):
        raise LLMError(
            f"Unknown DOCUBROWSE_LLM_BACKEND {choice!r}; "
            f"expected {OLLAMA_BACKEND!r} or {LITELLM_BACKEND!r}"
        )
    return choice


def resolve_model(default_model: str) -> str:
    """Return the model name for the active backend.

    The Ollama backend uses the per-language model from lang_models.py. The
    litellm backend cannot: those are bare Ollama tags with no provider, so it
    requires DOCUBROWSE_LLM_MODEL (e.g. "anthropic/claude-opus-4-7", or a name
    your gateway serves).
    """
    if backend() == OLLAMA_BACKEND:
        return default_model

    configured = (os.environ.get("DOCUBROWSE_LLM_MODEL") or "").strip()
    if not configured:
        raise LLMError(
            "DOCUBROWSE_LLM_BACKEND=litellm requires DOCUBROWSE_LLM_MODEL "
            "(the per-language Ollama tags cannot be routed by LiteLLM)"
        )
    return configured


def describe(default_model: str) -> str:
    """One-line description of the active backend, for status output."""
    if backend() == OLLAMA_BACKEND:
        return f"ollama ({default_model})"

    try:
        model = resolve_model(default_model)
    except LLMError:
        model = "unconfigured"
    base = (os.environ.get("DOCUBROWSE_LLM_API_BASE") or "").strip()
    return f"litellm ({model})" + (f" via {base}" if base else " direct")


def generate(
    prompt: str,
    *,
    model: str,
    host: str,
    timeout: int,
    options: dict | None = None,
    think: bool | None = None,
) -> str:
    """Generate text and return it, or raise LLMTimeout / LLMError.

    Args:
        prompt: the full prompt to send.
        model: the default (Ollama) model name; the litellm backend overrides
            it via DOCUBROWSE_LLM_MODEL.
        host: Ollama base URL, used only by the ollama backend.
        timeout: seconds to wait for a response.
        options: Ollama ``options`` block (e.g. ``{"num_predict": 1}``). The
            litellm backend maps only ``num_predict`` to ``max_tokens``; other
            keys are Ollama-specific and ignored.
        think: Ollama's reasoning toggle. See the note in _litellm_generate for
            why the litellm backend handles this differently.

    """
    resolved = resolve_model(model)
    if backend() == OLLAMA_BACKEND:
        return _ollama_generate(
            prompt, model=resolved, host=host, timeout=timeout, options=options, think=think
        )
    return _litellm_generate(prompt, model=resolved, timeout=timeout, options=options)


def _ollama_generate(
    prompt: str,
    *,
    model: str,
    host: str,
    timeout: int,
    options: dict | None,
    think: bool | None,
) -> str:
    """POST to Ollama's native /api/generate. Unchanged from the original path."""
    body: dict = {"model": model, "prompt": prompt, "stream": False}
    if options:
        body["options"] = options
    if think is not None:
        body["think"] = think

    request = Request(
        f"{host}/api/generate", data=json.dumps(body).encode("utf-8"), method="POST"
    )
    request.add_header("Content-Type", "application/json")

    try:
        with urlopen(request, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))
    except socket.timeout as exc:
        raise LLMTimeout(str(exc)) from exc
    except URLError as exc:
        # urllib wraps a read timeout in URLError rather than raising it
        # directly, so the reason has to be unwrapped to tell the two apart.
        if isinstance(exc.reason, socket.timeout):
            raise LLMTimeout(str(exc)) from exc
        raise LLMError(str(exc)) from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise LLMError(str(exc)) from exc

    return (data.get("response") or "").strip()


def _litellm_generate(
    prompt: str,
    *,
    model: str,
    timeout: int,
    options: dict | None,
) -> str:
    """Generate through LiteLLM, directly or via a self-hosted gateway."""
    try:
        import litellm  # noqa: PLC0415  (optional dependency, imported lazily)
    except ImportError as exc:
        raise LLMError(_LITELLM_IMPORT_HINT) from exc

    api_base = (os.environ.get("DOCUBROWSE_LLM_API_BASE") or "").strip().rstrip("/")

    request: dict = {
        "model": _route(model, api_base),
        "messages": [{"role": "user", "content": prompt}],
        "timeout": timeout,
        # Providers reject each other's parameters, so let LiteLLM drop what a
        # given model does not support rather than failing the request.
        "drop_params": True,
    }

    if api_base:
        request["api_base"] = api_base
    api_key = (os.environ.get("DOCUBROWSE_LLM_API_KEY") or "").strip()
    if api_key:
        request["api_key"] = api_key

    # Ollama's `think: False` cannot be forwarded: it is not an OpenAI
    # parameter, and drop_params would discard it anyway. The failure it
    # guards against is real for hybrid reasoning models, which spend the
    # whole budget thinking and return empty, so the defence here is an
    # explicit output cap instead.
    max_tokens = _max_tokens(options)
    if max_tokens:
        request["max_tokens"] = max_tokens

    try:
        response = litellm.completion(**request)
    except Exception as exc:  # litellm raises OpenAI-compatible exception types
        if "timeout" in type(exc).__name__.lower():
            raise LLMTimeout(str(exc)) from exc
        raise LLMError(str(exc)) from exc

    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError, KeyError, TypeError) as exc:
        raise LLMError(f"unexpected LiteLLM response shape: {response!r}") from exc

    return (content or "").strip()


def _route(model: str, api_base: str) -> str:
    """Prefix the model so a configured gateway is actually used.

    Without this, LiteLLM resolves the vendor from the model name and calls it
    directly: "gemini-2.5-flash" goes to Vertex AI even with ``api_base`` set,
    so a gateway is silently bypassed and the request fails on missing vendor
    credentials. LiteLLM's ``litellm_proxy/`` prefix is what tells it to
    forward instead of resolving.

    See https://docs.litellm.ai/docs/providers/litellm_proxy
    """
    if not api_base:
        return model
    if model.startswith(PROXY_PREFIX):
        return model
    return f"{PROXY_PREFIX}{model}"


def _max_tokens(options: dict | None) -> int | None:
    """Output cap for the litellm backend, from env or Ollama's num_predict."""
    configured = (os.environ.get("DOCUBROWSE_LLM_MAX_TOKENS") or "").strip()
    if configured:
        try:
            value = int(configured)
        except ValueError as exc:
            raise LLMError(
                f"DOCUBROWSE_LLM_MAX_TOKENS must be an integer, got {configured!r}"
            ) from exc
        if value > 0:
            return value

    if options and isinstance(options.get("num_predict"), int):
        predict = options["num_predict"]
        if predict > 0:
            return predict

    return None
