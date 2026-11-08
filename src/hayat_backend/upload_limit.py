"""Reject oversized upload requests before their body is parsed."""

from __future__ import annotations

import json

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Room for multipart boundaries and the small form fields around the file.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


class _BodyTooLarge(Exception):
    pass


class UploadSizeLimitMiddleware:
    """Return 413 for POST/PUT bodies over the limit on the given upload routes.

    A declared Content-Length is checked before anything is read; bodies sent
    without one (chunked) are counted as they arrive and cut off at the limit."""

    def __init__(self, app: ASGIApp, *, max_body_bytes: int, prefixes: tuple[str, ...]) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes
        self.prefixes = prefixes

    def _applies(self, scope: Scope) -> bool:
        return (
            scope["type"] == "http"
            and scope["method"] in {"POST", "PUT"}
            and scope["path"].startswith(self.prefixes)
        )

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self._applies(scope):
            await self.app(scope, receive, send)
            return

        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None:
            try:
                too_large = int(declared) > self.max_body_bytes
            except ValueError:
                too_large = True
            if too_large:
                await self._reject(send)
                return

        received = 0
        exceeded = False
        responded = False

        async def counting_receive() -> Message:
            nonlocal received, exceeded
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_body_bytes:
                    exceeded = True
                    raise _BodyTooLarge
            return message

        async def limited_send(message: Message) -> None:
            # FastAPI turns a failed body read into its own 400; answer 413 instead.
            nonlocal responded
            if exceeded:
                if message["type"] == "http.response.start" and not responded:
                    responded = True
                    await self._reject(send)
                return
            if message["type"] == "http.response.start":
                responded = True
            await send(message)

        try:
            await self.app(scope, counting_receive, limited_send)
        except _BodyTooLarge:
            if not responded:
                await self._reject(send)

    @staticmethod
    async def _reject(send: Send) -> None:
        body = json.dumps({"detail": "Upload is too large."}).encode()
        await send({
            "type": "http.response.start",
            "status": 413,
            "headers": [
                (b"content-type", b"application/json"),
                (b"content-length", str(len(body)).encode()),
                (b"connection", b"close"),
            ],
        })
        await send({"type": "http.response.body", "body": body})
