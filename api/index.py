"""Vercel Python entry point. Vercel detects the `app` ASGI callable."""

from oakland_mcp.http_server import app

__all__ = ["app"]
