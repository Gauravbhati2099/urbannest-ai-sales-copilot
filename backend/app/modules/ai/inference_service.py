from __future__ import annotations

import hmac
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import httpx
from fastapi import FastAPI, Header, HTTPException, status
from jsonschema import Draft202012Validator
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.modules.ai.service import AIServiceError, _ollama_chat_url, _settings

LOGGER = logging.getLogger("urbannest.inference")


class StructuredRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=1, max_length=30000)
    output_schema: dict[str, Any] = Field(alias="schema")
    model: str = Field(min_length=1, max_length=120)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[dict[str, Any]] = Field(min_length=1, max_length=32)
    tools: list[dict[str, Any]] = Field(max_length=16)


def _token() -> str:
    token = os.getenv("INFERENCE_SERVICE_TOKEN", "")
    if len(token) < 32 or not token.isascii() or any(c.isspace() for c in token):
        raise RuntimeError(
            "INFERENCE_SERVICE_TOKEN must be a dedicated token of at least 32 characters"
        )
    return token


@asynccontextmanager
async def lifespan(_: FastAPI):
    _token()
    yield


if os.getenv("INFERENCE_SERVICE_ENABLED", "false").strip().lower() not in {
    "1",
    "true",
    "yes",
}:
    raise RuntimeError(
        "Set INFERENCE_SERVICE_ENABLED=true to start the standalone inference provider"
    )

app = FastAPI(title="UrbanNest Ollama Inference Provider", version="1.0.0", lifespan=lifespan)


def _authorize(authorization: str | None) -> None:
    scheme, _, credential = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not hmac.compare_digest(
        credential.encode(), _token().encode()
    ):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Inference authentication failed")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/structured")
def structured(
    request: StructuredRequest, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    _authorize(authorization)
    try:
        provider, model, timeout, _ = _settings()
        if provider != "ollama" or request.model != model:
            raise AIServiceError("provider_not_configured")
        with httpx.Client(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            response = client.post(
                _ollama_chat_url(),
                json={
                    "model": model,
                    "stream": False,
                    "format": request.output_schema,
                    "messages": [
                        {
                            "role": "system",
                            "content": "Return only data matching the supplied JSON schema.",
                        },
                        {"role": "user", "content": request.prompt},
                    ],
                },
            )
        response.raise_for_status()
        payload = response.json()
        value = json.loads(payload["message"]["content"])
        if not isinstance(value, dict):
            raise ValueError("Structured output must be an object")
        output_schema = request.output_schema
        if not isinstance(output_schema, dict) or output_schema.get("type") != "object":
            raise ValueError("Only object schemas are supported")
        Draft202012Validator.check_schema(output_schema)
        errors = list(Draft202012Validator(output_schema).iter_errors(value))
        if errors:
            raise ValueError("Ollama output does not match requested schema")
        return {
            "value": value,
            "model": model,
            "input_tokens": payload.get("prompt_eval_count"),
            "output_tokens": payload.get("eval_count"),
        }
    except AIServiceError as exc:
        raise HTTPException(status_code=503, detail="Inference provider is unavailable") from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Inference request timed out") from exc
    except httpx.HTTPError as exc:
        LOGGER.warning("Ollama request failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Inference provider is unavailable") from exc
    except ValidationError as exc:
        raise HTTPException(status_code=502, detail="Inference provider returned invalid output") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Inference provider returned invalid output") from exc


@app.post("/v1/chat")
async def chat(
    request: ChatRequest, authorization: str | None = Header(default=None)
) -> dict[str, Any]:
    _authorize(authorization)
    try:
        provider, model, timeout, _ = _settings()
        if provider != "ollama":
            raise AIServiceError("provider_not_configured")
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            response = await client.post(
                _ollama_chat_url(),
                json={
                    "model": model,
                    "stream": False,
                    "messages": request.messages,
                    "tools": request.tools,
                    "options": {"num_predict": 1024},
                },
            )
        response.raise_for_status()
        payload = response.json()
        message = payload["message"]
        return {"content": message.get("content", ""), "tool_calls": message.get("tool_calls", [])}
    except AIServiceError as exc:
        raise HTTPException(status_code=503, detail="Inference provider is unavailable") from exc
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="Inference request timed out") from exc
    except httpx.HTTPError as exc:
        LOGGER.warning("Ollama chat request failed: %s", type(exc).__name__)
        raise HTTPException(status_code=503, detail="Inference provider is unavailable") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="Inference provider returned invalid output") from exc
