"""Streamable-HTTP MCP server with bearer-token auth, suitable for Vercel.

Exposes an ASGI `app` that serves the MCP protocol at `/mcp`. Each request is
authenticated against the `MCP_AUTH_TOKEN` env var via the `Authorization:
Bearer <token>` header.

The underlying FastMCP is configured with `stateless_http=True` so that each
request is self-contained — required for serverless runtimes where successive
requests may land on different instances.
"""

from __future__ import annotations

import os

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from .server import build_server


class BearerTokenMiddleware(BaseHTTPMiddleware):
    """Reject requests that don't carry the expected bearer token.

    The token is read from the `MCP_AUTH_TOKEN` env var at request time, not
    at import time, so Vercel can inject it before the first invocation.
    """

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/health":
            return await call_next(request)

        expected = os.environ.get("MCP_AUTH_TOKEN")
        if not expected:
            return JSONResponse(
                {"error": "server missing MCP_AUTH_TOKEN"}, status_code=500
            )

        header = request.headers.get("authorization", "")
        scheme, _, token = header.partition(" ")
        if scheme.lower() != "bearer" or token != expected:
            return JSONResponse({"error": "unauthorized"}, status_code=401)

        return await call_next(request)


async def _health(_: Request) -> Response:
    return JSONResponse({"ok": True})


def create_app() -> Starlette:
    mcp = build_server(stateless_http=True)
    mcp_app = mcp.streamable_http_app()

    return Starlette(
        routes=[
            Route("/health", _health),
            Mount("/", app=mcp_app),
        ],
        middleware=[Middleware(BearerTokenMiddleware)],
        lifespan=mcp_app.router.lifespan_context,
    )


app = create_app()
