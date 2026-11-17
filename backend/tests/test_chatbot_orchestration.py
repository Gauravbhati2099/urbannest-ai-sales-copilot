from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.modules.ai.service import AIChatResult, AIServiceError, AIToolCall
from app.modules.chatbot.orchestrator import (
    ALLOWED_TOOL_NAMES,
    TOOL_FAILURE_RESPONSE,
    _run_tool_loop,
)


class ChatbotOrchestrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tools = [
            SimpleNamespace(
                name=name,
                description=f"Tool for {name}",
                input_schema={"type": "object", "properties": {}},
            )
            for name in ALLOWED_TOOL_NAMES
        ]
        self.mcp_client = SimpleNamespace(call_tool=AsyncMock())

    async def test_model_tool_call_uses_mcp_and_returns_final_answer(self) -> None:
        self.mcp_client.call_tool.return_value = SimpleNamespace(
            is_error=False,
            structured_content={"results": [{"name": "Juniper Row"}]},
        )
        with patch(
            "app.modules.chatbot.orchestrator.complete_chat_with_tools",
            new=AsyncMock(
                side_effect=[
                    AIChatResult(
                        content="",
                        tool_calls=(
                            AIToolCall(
                                name="search_estates",
                                arguments={"query": "Juniper Row"},
                            ),
                        ),
                    ),
                    AIChatResult(content="I found Juniper Row.", tool_calls=()),
                ]
            ),
        ) as complete:
            response = await _run_tool_loop(
                "Find Juniper Row",
                self.mcp_client,
                self.tools,
            )

        self.mcp_client.call_tool.assert_awaited_once_with(
            "search_estates", {"query": "Juniper Row"}
        )
        self.assertEqual(response.response, "I found Juniper Row.")
        self.assertEqual(response.tool_executions[0].status, "succeeded")
        self.assertEqual(complete.await_count, 2)

    async def test_model_cannot_invoke_unallowlisted_tool(self) -> None:
        with patch(
            "app.modules.chatbot.orchestrator.complete_chat_with_tools",
            new=AsyncMock(
                return_value=AIChatResult(
                    content="",
                    tool_calls=(
                        AIToolCall(name="run_sql", arguments={"query": "SELECT 1"}),
                    ),
                )
            ),
        ):
            response = await _run_tool_loop("Show my data", self.mcp_client, self.tools)

        self.mcp_client.call_tool.assert_not_awaited()
        self.assertEqual(response.response, TOOL_FAILURE_RESPONSE)
        self.assertEqual(response.tool_executions[0].name, "unsupported_tool")
        self.assertEqual(response.tool_executions[0].status, "failed")

    async def test_tool_call_limit_is_checked_before_invoking_any_tool(self) -> None:
        calls = tuple(
            AIToolCall(name="search_leads", arguments={"query": "prospect"})
            for _ in range(5)
        )
        with (
            patch(
                "app.modules.chatbot.orchestrator.complete_chat_with_tools",
                new=AsyncMock(return_value=AIChatResult(content="", tool_calls=calls)),
            ),
            self.assertRaises(AIServiceError) as error,
        ):
            await _run_tool_loop("Find prospects", self.mcp_client, self.tools)

        self.assertEqual(error.exception.category, "tool_call_limit_exceeded")
        self.mcp_client.call_tool.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
