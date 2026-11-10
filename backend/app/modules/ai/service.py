from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import TypeVar

import httpx
from pydantic import BaseModel, ValidationError

ModelT = TypeVar("ModelT", bound=BaseModel)
LOGGER = logging.getLogger(__name__)
PII_EMAIL = re.compile(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b")
PII_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")


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
    provider, model, timeout, credential = _settings()
    schema = response_model.model_json_schema()
    started = time.monotonic()
    try:
        with httpx.Client(timeout=timeout) as client:
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
                base_url = os.getenv(
                    "OLLAMA_BASE_URL", "http://localhost:11434"
                ).rstrip("/")
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
