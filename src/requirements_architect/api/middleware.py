"""Security headers and request-size limit as plain ASGI middleware (no body is buffered twice)."""

from __future__ import annotations

import json
from typing import Any

from starlette.types import ASGIApp, Message, Receive, Scope, Send

CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)
HEADERS = {
    b"x-content-type-options": b"nosniff",
    b"x-frame-options": b"DENY",
    b"referrer-policy": b"no-referrer",
    b"content-security-policy": CSP.encode(),
    b"cross-origin-resource-policy": b"same-origin",
}


class SecurityHeaders:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        api = scope["path"].startswith("/api/")

        async def wrapped(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message["headers"] if k.lower() not in HEADERS]
                headers += list(HEADERS.items())
                if api:  # responses are per-user and may hold project content
                    headers = [(k, v) for k, v in headers if k.lower() != b"cache-control"]
                    headers.append((b"cache-control", b"no-store"))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, wrapped)


class BodyLimit:
    """Reject bodies over `max_bytes`, whether declared in Content-Length or streamed."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        declared = dict(scope["headers"]).get(b"content-length")
        if declared and declared.isdigit() and int(declared) > self.max:
            await self._reject(send)
            return
        seen = 0
        too_big = False

        async def limited() -> Message:
            nonlocal seen, too_big
            message = await receive()
            if message["type"] == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max:
                    too_big = True
                    return {"type": "http.request", "body": b"", "more_body": False}
            return message

        started = False

        async def guarded(message: Message) -> None:
            nonlocal started
            if too_big and not started:
                return  # swallow the app's response; a 413 is sent below
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        await self.app(scope, limited, guarded)
        if too_big and not started:
            await self._reject(send)

    @staticmethod
    async def _reject(send: Send) -> None:
        body: dict[str, Any] = {"error": "request_too_large"}
        data = json.dumps(body).encode()
        await send(
            {
                "type": "http.response.start",
                "status": 413,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(data)).encode()),
                ],
            }
        )
        await send({"type": "http.response.body", "body": data})
