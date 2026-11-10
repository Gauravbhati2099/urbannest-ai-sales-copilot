from __future__ import annotations

import json
import os
import unittest
from unittest.mock import Mock, patch

from app.modules.ai.schemas import MessageDraftResult
from app.modules.ai.service import (
    AIServiceError,
    complete_structured,
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
        with patch.dict(os.environ, {"AI_PROVIDER": "not-configured"}):
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


if __name__ == "__main__":
    unittest.main()
