from __future__ import annotations

import json
import os
import unittest
from unittest.mock import AsyncMock, Mock, patch

from app.modules.ai.schemas import MessageDraftResult
from app.modules.ai.service import (
    AIServiceError,
    AIToolCall,
    AIChatResult,
    complete_structured,
    complete_chat_with_tools,
    redact_contact_details,
)


class AIServiceTests(unittest.TestCase):
    def test_ollama_structured_response_is_parsed_with_usage_metadata(self) -> None:
        response = Mock()
        response.json.return_value = {
            "message": {"content": json.dumps({"body": "Hello, would you like to visit?"})},
            "prompt_eval_count": 24,
            "eval_count": 9,
        }
        client = Mock()
        client.post.return_value = response
        client_context = Mock()
        client_context.__enter__ = Mock(return_value=client)
        client_context.__exit__ = Mock(return_value=False)

        with (
            patch.dict(
                os.environ,
                {
                    "AI_PROVIDER": "ollama",
                    "AI_SERVICES_ENABLED": "true",
                    "OLLAMA_MODEL": "test-model",
                    "OLLAMA_BASE_URL": "http://localhost:11434",
                    "OLLAMA_TIMEOUT_SECONDS": "10",
                },
            ),
            patch("app.modules.ai.service.httpx.Client", return_value=client_context),
        ):
            result = complete_structured(
                "Draft a safe message",
                MessageDraftResult,
            )

        self.assertEqual(result.value.body, "Hello, would you like to visit?")
        self.assertEqual(result.provider, "ollama")
        self.assertEqual(result.model, "test-model")
        self.assertEqual(result.input_tokens, 24)
        self.assertEqual(result.output_tokens, 9)
        self.assertGreaterEqual(result.latency_ms, 0)
        request = client.post.call_args
        self.assertEqual(request.args[0], "http://localhost:11434/api/chat")
        self.assertEqual(request.kwargs["json"]["stream"], False)
        self.assertIn("format", request.kwargs["json"])

    def test_unavailable_provider_is_reported_without_success_fallback(self) -> None:
        with patch.dict(os.environ, {"AI_PROVIDER": "not-configured", "AI_SERVICES_ENABLED": "true"}):
            with self.assertRaises(AIServiceError) as error:
                complete_structured("No PII", MessageDraftResult)
        self.assertEqual(error.exception.category, "provider_not_configured")

    def test_contact_redaction_removes_email_and_phone(self) -> None:
        result = redact_contact_details(
            "Call alex@example.test on +91 98765 43210",
        )
        self.assertNotIn("alex@example.test", result)
        self.assertNotIn("98765 43210", result)
        self.assertIn("[email]", result)
        self.assertIn("[phone]", result)


class AIChatToolServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_tool_call_response_is_parsed(self) -> None:
        response = Mock()
        response.json.return_value = {
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "search_estates",
                            "arguments": '{"q":"Juniper Row"}',
                        }
                    }
                ],
            }
        }
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        client.post.return_value = response
        with (
            patch.dict(
                os.environ,
                {
                    "AI_PROVIDER": "ollama",
                    "AI_SERVICES_ENABLED": "true",
                    "OLLAMA_MODEL": "test-model",
                    "OLLAMA_BASE_URL": "http://localhost:11434",
                },
            ),
            patch("app.modules.ai.service.httpx.AsyncClient", return_value=client),
        ):
            result = await complete_chat_with_tools(
                [{"role": "user", "content": "Search estates"}],
                [],
            )

        self.assertEqual(
            result,
            AIChatResult(
                content="",
                tool_calls=(
                    AIToolCall(
                        name="search_estates",
                        arguments={"q": "Juniper Row"},
                    ),
                ),
            ),
        )
        self.assertEqual(client.post.call_args.kwargs["json"]["stream"], False)

    async def test_oversized_tool_arguments_are_rejected(self) -> None:
        response = Mock()
        response.json.return_value = {
            "message": {
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "search_estates",
                            "arguments": '{"q":"' + ("x" * 8000) + '"}',
                        }
                    }
                ],
            }
        }
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.__aexit__.return_value = False
        client.post.return_value = response
        with (
            patch.dict(
                os.environ,
                {
                    "AI_PROVIDER": "ollama",
                    "AI_SERVICES_ENABLED": "true",
                    "OLLAMA_MODEL": "test-model",
                    "OLLAMA_BASE_URL": "http://localhost:11434",
                },
            ),
            patch("app.modules.ai.service.httpx.AsyncClient", return_value=client),
        ):
            with self.assertRaises(AIServiceError) as error:
                await complete_chat_with_tools(
                    [{"role": "user", "content": "Search estates"}],
                    [],
                )

        self.assertEqual(error.exception.category, "invalid_provider_response")


if __name__ == "__main__":
    unittest.main()
