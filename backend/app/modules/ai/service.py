from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import TypeVar
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)
LOGGER = logging.getLogger(__name__)
PII_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
PII_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")
MAX_TOOL_CALLS_PER_RESPONSE = 4
MAX_TOOL_ARGUMENTS_CHARS = 8000


class AIServiceError(Exception):
    def __init__(self, category: str, *, timed_out: bool = False) -> None:
        super().__init__(category)
        self.category = category
        self.timed_out = timed_out


@dataclass(frozen=True)
class AIResult:
    value: BaseModel
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int


@dataclass(frozen=True)
class AIToolCall:
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class AIChatResult:
    content: str
    tool_calls: tuple[AIToolCall, ...]


def redact_contact_details(value: str, *, maximum_length: int = 1000) -> str:
    value = PII_EMAIL.sub("[email]", value)
    value = PII_PHONE.sub("[phone]", value)
    return value[:maximum_length]


def hash_context(context: dict[str, object]) -> str:
    encoded = json.dumps(context, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _settings() -> tuple[str, str, float, str | None]:
    provider = os.getenv("AI_PROVIDER", "").strip().lower()
    if provider == "gemini":
        model = os.getenv("GEMINI_MODEL", "").strip()
        credential = os.getenv("GEMINI_API_KEY", "").strip()
        timeout_raw = os.getenv("AI_TIMEOUT_SECONDS", "30")
    elif provider == "ollama":
        model = os.getenv("OLLAMA_MODEL", "").strip()
        credential = None
        timeout_raw = os.getenv("OLLAMA_TIMEOUT_SECONDS", "120")
    else:
        raise AIServiceError("provider_not_configured")

    if not model or (provider == "gemini" and not credential):
        raise AIServiceError("provider_not_configured")
    try:
        timeout = float(timeout_raw)
    except ValueError as exc:
        raise AIServiceError("invalid_provider_configuration") from exc
    if not 1 <= timeout <= 180:
        raise AIServiceError("invalid_provider_configuration")
    return provider, model, timeout, credential


def complete_structured(
    prompt: str,
    response_model: type[ModelT],
) -> AIResult:
    if os.getenv("AI_SERVICES_ENABLED", os.getenv("CHAT_ENABLED", "false")).strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        raise AIServiceError("ai_services_disabled")
    service_url = os.getenv("INFERENCE_SERVICE_URL", "").strip()
    service_token = os.getenv("INFERENCE_SERVICE_TOKEN", "")
    if service_url:
        return _complete_structured_remote(
            service_url, service_token, prompt, response_model
        )

    provider, model, timeout, credential = _settings()
    schema = response_model.model_json_schema()
    started = time.monotonic()
    try:
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            if provider == "gemini":
                response = client.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                    headers={"x-goog-api-key": credential or ""},
                    json={
                        "contents": [{"parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "responseMimeType": "application/json",
                            "responseSchema": schema,
                        },
                    },
                )
            else:
                base_url = _ollama_base_url()
                response = client.post(
                    f"{base_url}/api/chat",
                    json={
                        "model": model,
                        "stream": False,
                        "format": schema,
                        "messages": [
                            {
                                "role": "system",
                                "content": "Return only data matching the supplied JSON schema.",
                            },
                            {"role": "user", "content": prompt},
                        ],
                    },
                )
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        LOGGER.warning("AI provider request timed out")
        raise AIServiceError("provider_timeout", timed_out=True) from exc
    except httpx.HTTPStatusError as exc:
        LOGGER.warning("AI provider returned HTTP status %s", exc.response.status_code)
        raise AIServiceError("provider_http_error") from exc
    except httpx.RequestError as exc:
        LOGGER.warning("AI provider request failed: %s", type(exc).__name__)
        raise AIServiceError("provider_unavailable") from exc

    try:
        payload = response.json()
        if provider == "gemini":
            content = payload["candidates"][0]["content"]["parts"][0]["text"]
            usage = payload.get("usageMetadata", {})
            input_tokens = usage.get("promptTokenCount")
            output_tokens = usage.get("candidatesTokenCount")
        else:
            content = payload["message"]["content"]
            input_tokens = payload.get("prompt_eval_count")
            output_tokens = payload.get("eval_count")
        value = response_model.model_validate_json(content)
    except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
        LOGGER.warning("AI provider response failed structured validation")
        raise AIServiceError("invalid_provider_response") from exc

    return AIResult(
        value=value,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=max(0, round((time.monotonic() - started) * 1000)),
    )


def _complete_structured_remote(
    base_url: str,
    service_token: str,
    prompt: str,
    response_model: type[ModelT],
) -> AIResult:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or (
            parsed.scheme == "http"
            and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            and os.getenv("INFERENCE_ALLOW_REMOTE_HTTP", "false").strip().lower()
            not in {"1", "true", "yes"}
        )
    ):
        raise AIServiceError("invalid_inference_service_configuration")
    if (
        len(service_token) < 32
        or not service_token.isascii()
        or any(c.isspace() for c in service_token)
    ):
        raise AIServiceError("invalid_inference_service_configuration")
    provider = os.getenv("AI_PROVIDER", "ollama").strip().lower()
    model = os.getenv("OLLAMA_MODEL", "").strip()
    if provider != "ollama" or not model:
        raise AIServiceError("provider_not_configured")
    started = time.monotonic()
    try:
        with httpx.Client(timeout=180, follow_redirects=False, trust_env=False) as client:
            response = client.post(
                f"{base_url.rstrip('/')}/v1/structured",
                headers={"Authorization": f"Bearer {service_token}"},
                json={"prompt": prompt, "schema": response_model.model_json_schema(), "model": model},
            )
        response.raise_for_status()
        payload = response.json()
        value = response_model.model_validate(payload["value"])
        return AIResult(
            value=value,
            provider="ollama",
            model=str(payload.get("model") or model),
            input_tokens=payload.get("input_tokens"),
            output_tokens=payload.get("output_tokens"),
            latency_ms=max(0, round((time.monotonic() - started) * 1000)),
        )
    except httpx.TimeoutException as exc:
        raise AIServiceError("provider_timeout", timed_out=True) from exc
    except httpx.HTTPStatusError as exc:
        LOGGER.warning("Inference service returned HTTP status %s", exc.response.status_code)
        raise AIServiceError("provider_http_error") from exc
    except httpx.RequestError as exc:
        raise AIServiceError("provider_unavailable") from exc
    except (KeyError, TypeError, ValueError, ValidationError) as exc:
        raise AIServiceError("invalid_provider_response") from exc


def _ollama_chat_url() -> str:
    return f"{_ollama_base_url()}/api/chat"


def _ollama_base_url() -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").strip().rstrip("/")
    try:
        parsed = urlsplit(base_url)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise AIServiceError("invalid_provider_configuration") from exc

    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or (port is not None and not 1 <= port <= 65535)
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
    ):
        raise AIServiceError("invalid_provider_configuration")
    if parsed.scheme == "http" and hostname not in {"localhost", "127.0.0.1", "::1"}:
        raise AIServiceError("invalid_provider_configuration")
    return base_url


async def complete_chat_with_tools(
    messages: list[dict[str, object]],
    tools: list[dict[str, object]],
) -> AIChatResult:
    if os.getenv("AI_SERVICES_ENABLED", os.getenv("CHAT_ENABLED", "false")).strip().lower() not in {
        "1",
        "true",
        "yes",
    }:
        raise AIServiceError("ai_services_disabled")
    service_url = os.getenv("INFERENCE_SERVICE_URL", "").strip()
    service_token = os.getenv("INFERENCE_SERVICE_TOKEN", "")
    if service_url:
        return await _complete_chat_remote(service_url, service_token, messages, tools)

    provider, model, timeout, _ = _settings()
    if provider != "ollama":
        raise AIServiceError("tool_calling_provider_not_supported")

    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            response = await client.post(
                _ollama_chat_url(),
                json={
                    "model": model,
                    "stream": False,
                    "messages": messages,
                    "tools": tools,
                    "options": {"num_predict": 1024},
                },
            )
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        LOGGER.warning("Chat model request timed out")
        raise AIServiceError("provider_timeout", timed_out=True) from exc
    except httpx.HTTPStatusError as exc:
        LOGGER.warning("Chat model returned HTTP status %s", exc.response.status_code)
        raise AIServiceError("provider_http_error") from exc
    except httpx.RequestError as exc:
        LOGGER.warning("Chat model request failed: %s", type(exc).__name__)
        raise AIServiceError("provider_unavailable") from exc

    try:
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Expected an object response")
        message = payload.get("message")
        if not isinstance(message, dict):
            raise ValueError("Expected a message object")

        content = message.get("content", "")
        if content is None:
            content = ""
        if not isinstance(content, str) or len(content) > 8000:
            raise ValueError("Invalid message content")

        raw_tool_calls = message.get("tool_calls", [])
        if not isinstance(raw_tool_calls, list):
            raise ValueError("Invalid tool calls")
        if len(raw_tool_calls) > MAX_TOOL_CALLS_PER_RESPONSE:
            raise ValueError("Too many tool calls")
        tool_calls: list[AIToolCall] = []
        for raw_tool_call in raw_tool_calls:
            if not isinstance(raw_tool_call, dict):
                raise ValueError("Invalid tool call")
            function = raw_tool_call.get("function")
            if not isinstance(function, dict):
                raise ValueError("Invalid tool function")
            name = function.get("name")
            raw_arguments = function.get("arguments", {})
            if not isinstance(name, str) or not name or len(name) > 80:
                raise ValueError("Invalid tool name")
            if isinstance(raw_arguments, str):
                if len(raw_arguments) > MAX_TOOL_ARGUMENTS_CHARS:
                    raise ValueError("Tool arguments are too large")
                raw_arguments = json.loads(raw_arguments)
            if not isinstance(raw_arguments, dict):
                raise ValueError("Invalid tool arguments")
            encoded_arguments = json.dumps(
                raw_arguments,
                ensure_ascii=True,
                separators=(",", ":"),
            )
            if len(encoded_arguments) > MAX_TOOL_ARGUMENTS_CHARS:
                raise ValueError("Tool arguments are too large")
            tool_calls.append(AIToolCall(name=name, arguments=raw_arguments))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        LOGGER.warning("Chat model response failed validation")
        raise AIServiceError("invalid_provider_response") from exc

    return AIChatResult(content=content, tool_calls=tuple(tool_calls))


async def _complete_chat_remote(
    base_url: str,
    service_token: str,
    messages: list[dict[str, object]],
    tools: list[dict[str, object]],
) -> AIChatResult:
    parsed = urlsplit(base_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.path
        or parsed.query
        or parsed.fragment
        or parsed.username
        or parsed.password
        or (
            parsed.scheme == "http"
            and parsed.hostname not in {"localhost", "127.0.0.1", "::1"}
            and os.getenv("INFERENCE_ALLOW_REMOTE_HTTP", "false").strip().lower()
            not in {"1", "true", "yes"}
        )
        or len(service_token) < 32
        or not service_token.isascii()
        or any(c.isspace() for c in service_token)
    ):
        raise AIServiceError("invalid_inference_service_configuration")
    try:
        async with httpx.AsyncClient(
            timeout=180, follow_redirects=False, trust_env=False
        ) as client:
            response = await client.post(
                f"{base_url.rstrip('/')}/v1/chat",
                headers={"Authorization": f"Bearer {service_token}"},
                json={"messages": messages, "tools": tools},
            )
        response.raise_for_status()
        payload = response.json()
        message = {"content": payload["content"], "tool_calls": payload["tool_calls"]}
        if not isinstance(message["content"], str) or not isinstance(
            message["tool_calls"], list
        ):
            raise ValueError("Invalid inference response")
        tool_calls: list[AIToolCall] = []
        if len(message["tool_calls"]) > MAX_TOOL_CALLS_PER_RESPONSE:
            raise ValueError("Too many tool calls")
        for raw in message["tool_calls"]:
            function = raw["function"]
            name = function["name"]
            arguments = function.get("arguments", {})
            if isinstance(arguments, str):
                arguments = json.loads(arguments)
            if not isinstance(name, str) or not isinstance(arguments, dict):
                raise ValueError("Invalid tool call")
            if (
                len(json.dumps(arguments, separators=(",", ":")))
                > MAX_TOOL_ARGUMENTS_CHARS
            ):
                raise ValueError("Tool arguments are too large")
            tool_calls.append(AIToolCall(name, arguments))
        return AIChatResult(message["content"], tuple(tool_calls))
    except httpx.TimeoutException as exc:
        raise AIServiceError("provider_timeout", timed_out=True) from exc
    except httpx.HTTPStatusError as exc:
        raise AIServiceError("provider_http_error") from exc
    except httpx.RequestError as exc:
        raise AIServiceError("provider_unavailable") from exc
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AIServiceError("invalid_provider_response") from exc
