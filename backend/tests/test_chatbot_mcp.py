from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch

import httpx
from fastapi.testclient import TestClient
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from starlette.responses import JSONResponse

from app.modules.chatbot import mcp_server
from app.modules.chatbot.mcp_server import (
    BackendAPIClient,
    MCPServiceAuthMiddleware,
    MCPSettings,
    _context_user_token,
    create_mcp_application,
)


SERVICE_TOKEN = "test-service-token-that-is-at-least-32-bytes"
USER_TOKEN = "test-user-access-token"
MCP_SETTINGS = MCPSettings(
    service_token=SERVICE_TOKEN,
    backend_api_base_url="https://crm.example.test",
    api_v1_prefix="/api/v1",
    allowed_hosts=("localhost", "localhost:*"),
    request_timeout_seconds=10,
)


class MCPSettingsTests(unittest.TestCase):
    def test_requires_a_dedicated_service_token(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MCP_SERVICE_TOKEN": SERVICE_TOKEN,
                "MCP_ENABLED": "true",
                "JWT_SECRET_KEY": SERVICE_TOKEN,
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "must not reuse"):
                MCPSettings.from_environment()

    def test_rejects_non_loopback_backend_http(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MCP_SERVICE_TOKEN": SERVICE_TOKEN,
                "MCP_ENABLED": "true",
                "BACKEND_API_BASE_URL": "http://crm.example.test",
            },
            clear=True,
        ):
            with self.assertRaisesRegex(RuntimeError, "must use HTTPS"):
                MCPSettings.from_environment()

    def test_allows_loopback_http_for_local_development(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MCP_SERVICE_TOKEN": SERVICE_TOKEN,
                "MCP_ENABLED": "true",
                "BACKEND_API_BASE_URL": "http://127.0.0.1:8000",
            },
            clear=True,
        ):
            settings = MCPSettings.from_environment()

        self.assertEqual(settings.backend_api_base_url, "http://127.0.0.1:8000")


class MCPServiceAuthTests(unittest.TestCase):
    def test_service_requires_both_service_and_user_credentials(self) -> None:
        async def protected_app(scope, receive, send) -> None:
            await JSONResponse({"ok": True})(scope, receive, send)

        app = MCPServiceAuthMiddleware(protected_app, SERVICE_TOKEN)
        client = TestClient(app)
        missing = client.post("/mcp")
        invalid_service = client.post(
            "/mcp",
            headers={
                "Authorization": "Bearer wrong-service-token",
                "X-UrbanNest-User-Token": USER_TOKEN,
            },
        )
        missing_user = client.post(
            "/mcp",
            headers={"Authorization": f"Bearer {SERVICE_TOKEN}"},
        )
        valid = client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {SERVICE_TOKEN}",
                "X-UrbanNest-User-Token": USER_TOKEN,
            },
        )

        self.assertEqual(missing.status_code, 401)
        self.assertEqual(invalid_service.status_code, 401)
        self.assertEqual(missing_user.status_code, 401)
        self.assertEqual(valid.status_code, 200)

    def test_service_rejects_ambiguous_or_malformed_credentials(self) -> None:
        async def protected_app(scope, receive, send) -> None:
            await JSONResponse({"ok": True})(scope, receive, send)

        app = MCPServiceAuthMiddleware(protected_app, SERVICE_TOKEN)
        client = TestClient(app)
        whitespace_token = client.post(
            "/mcp",
            headers={
                "Authorization": f"Bearer {SERVICE_TOKEN}",
                "X-UrbanNest-User-Token": "token with spaces",
            },
        )

        self.assertEqual(whitespace_token.status_code, 401)


class MCPBackendAdapterTests(unittest.IsolatedAsyncioTestCase):
    async def test_forwards_only_the_original_user_token_to_backend(self) -> None:
        requests: list[httpx.Request] = []

        def backend_handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(200, json=[{"ok": True}], request=request)

        async with httpx.AsyncClient(
            base_url="https://crm.example.test",
            transport=httpx.MockTransport(backend_handler),
        ) as client:
            backend = BackendAPIClient(client, "/api/v1")
            result = await backend.get_json(
                "/leads",
                user_token=USER_TOKEN,
                params={"limit": 11},
            )

        self.assertEqual(result, [{"ok": True}])
        self.assertEqual(len(requests), 1)
        self.assertEqual(requests[0].url.path, "/api/v1/leads")
        self.assertEqual(
            requests[0].headers["Authorization"],
            f"Bearer {USER_TOKEN}",
        )
        self.assertNotIn("X-UrbanNest-User-Token", requests[0].headers)
        self.assertNotIn(SERVICE_TOKEN, requests[0].headers["Authorization"])

    async def test_backend_forbidden_response_is_sanitized_without_fallback(self) -> None:
        requests: list[httpx.Request] = []

        def backend_handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                403,
                json={"detail": "sensitive authorization diagnostic"},
                request=request,
            )

        async with httpx.AsyncClient(
            base_url="https://crm.example.test",
            transport=httpx.MockTransport(backend_handler),
        ) as client:
            backend = BackendAPIClient(client, "/api/v1")
            with self.assertRaises(ToolError) as raised:
                await backend.get_json("/leads", user_token=USER_TOKEN)

        self.assertNotIn("sensitive authorization diagnostic", str(raised.exception))
        self.assertEqual(
            requests[0].headers["Authorization"],
            f"Bearer {USER_TOKEN}",
        )

    async def test_backend_unauthorized_response_does_not_use_service_token(self) -> None:
        requests: list[httpx.Request] = []

        def backend_handler(request: httpx.Request) -> httpx.Response:
            requests.append(request)
            return httpx.Response(
                401,
                json={"detail": "sensitive authentication diagnostic"},
                request=request,
            )

        async with httpx.AsyncClient(
            base_url="https://crm.example.test",
            transport=httpx.MockTransport(backend_handler),
        ) as client:
            backend = BackendAPIClient(client, "/api/v1")
            with self.assertRaises(ToolError) as raised:
                await backend.get_json("/leads", user_token=USER_TOKEN)

        self.assertNotIn(
            "sensitive authentication diagnostic",
            str(raised.exception),
        )
        self.assertEqual(
            requests[0].headers["Authorization"],
            f"Bearer {USER_TOKEN}",
        )

    async def test_context_requires_the_original_user_token(self) -> None:
        context = Mock()
        context.headers = None
        with self.assertRaises(ToolError):
            _context_user_token(context)

        context.headers = {"x-urbannest-user-token": USER_TOKEN}
        self.assertEqual(_context_user_token(context), USER_TOKEN)


class MCPToolRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_streamable_http_tool_call_propagates_user_token(self) -> None:
        backend_requests: list[httpx.Request] = []

        def backend_handler(request: httpx.Request) -> httpx.Response:
            backend_requests.append(request)
            return httpx.Response(
                403,
                json={"detail": "sensitive authorization diagnostic"},
                request=request,
            )

        real_async_client = httpx.AsyncClient

        def backend_client_factory(**kwargs) -> httpx.AsyncClient:
            return real_async_client(
                **kwargs,
                transport=httpx.MockTransport(backend_handler),
            )

        settings = MCPSettings(
            service_token=SERVICE_TOKEN,
            backend_api_base_url="https://crm.example.test",
            api_v1_prefix="/api/v1",
            allowed_hosts=("testserver", "testserver:*"),
            request_timeout_seconds=10,
        )
        _, app = create_mcp_application(settings)
        mcp_headers = {
            "Authorization": f"Bearer {SERVICE_TOKEN}",
            "X-UrbanNest-User-Token": USER_TOKEN,
        }

        with patch.object(mcp_server.httpx, "AsyncClient", backend_client_factory):
            async with app.router.lifespan_context(app):
                async with httpx.AsyncClient(
                    transport=httpx.ASGITransport(app=app),
                    headers=mcp_headers,
                ) as http_client:
                    transport = streamable_http_client(
                        "http://testserver/mcp",
                        http_client=http_client,
                    )
                    async with Client(transport) as client:
                        with self.assertRaises(MCPError):
                            await client.call_tool(
                                "search_leads",
                                {"q": "Aditi", "user_id": "another-user"},
                            )
                        self.assertEqual(backend_requests, [])
                        result = await client.call_tool(
                            "search_leads",
                            {"q": "Aditi"},
                        )

        self.assertTrue(result.is_error)
        self.assertEqual(len(backend_requests), 1)
        self.assertEqual(backend_requests[0].url.path, "/api/v1/leads")
        self.assertEqual(
            backend_requests[0].headers["Authorization"],
            f"Bearer {USER_TOKEN}",
        )
        self.assertNotIn(
            SERVICE_TOKEN,
            backend_requests[0].headers["Authorization"],
        )

    async def test_only_the_five_read_only_tools_are_registered(self) -> None:
        server, _ = create_mcp_application(MCP_SETTINGS)

        async with Client(server) as client:
            result = await client.list_tools()

        self.assertEqual(
            {tool.name for tool in result.tools},
            {
                "search_leads",
                "get_lead_summary",
                "list_tasks",
                "search_estates",
                "get_estate_details",
            },
        )
        for tool in result.tools:
            with self.subTest(tool=tool.name):
                self.assertNotIn("user_id", tool.input_schema.get("properties", {}))
                self.assertNotIn("team_id", tool.input_schema.get("properties", {}))
                self.assertNotIn("role", tool.input_schema.get("properties", {}))
                self.assertNotIn(
                    "assigned_to", tool.input_schema.get("properties", {})
                )
                self.assertTrue(tool.annotations.read_only_hint)


if __name__ == "__main__":
    unittest.main()
