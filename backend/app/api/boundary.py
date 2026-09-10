"""Local-only browser boundary, small request bodies and non-reflecting error responses."""

from urllib.parse import urlparse

import httpx
from starlette.responses import JSONResponse

LOCAL = {"127.0.0.1", "localhost", "::1"}
MAX_BODY = 16384


def error(status, code, message):
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def failure(exc):
    if isinstance(exc, ImportError):
        return error(503, "dependency_unavailable", "A required local dependency is unavailable.")
    try:
        from sqlalchemy.exc import SQLAlchemyError

        from backend.app.repositories.postgres import ConflictError, EvidenceError
    except ImportError:
        return error(500, "internal_error", "The operation failed; no result was accepted.")
    if isinstance(exc, ConflictError):
        return error(
            409, "immutable_conflict", "Stored immutable evidence differs from this operation."
        )
    if isinstance(exc, EvidenceError | ValueError):
        return error(
            409, "evidence_mismatch", "Evidence or version validation failed; no result accepted."
        )
    if isinstance(exc, SQLAlchemyError | httpx.HTTPError | OSError):
        return error(
            503, "dependency_unavailable", "A local service, artifact or model is unavailable."
        )
    return error(500, "internal_error", "The operation failed; no result was accepted.")


class LocalBoundary:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope["headers"]}
        origin = headers.get("origin")
        try:
            host = urlparse("http://" + headers.get("host", "")).hostname
            origin_host = urlparse(origin).hostname if origin else None
        except ValueError:
            host, origin_host = None, None
        if host not in LOCAL or (origin is not None and origin_host not in LOCAL):
            return await error(403, "local_only", "This research API accepts local requests only.")(
                scope, receive, send
            )
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > MAX_BODY:
                return await error(
                    413, "request_too_large", "Request body exceeds the research API limit."
                )(scope, receive, send)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        started = False

        async def guarded_send(message):
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, replay, guarded_send)
        except Exception as exc:
            # Consume failures before ServerErrorMiddleware can re-raise raw data into server logs.
            if not started:
                await failure(exc)(scope, replay, send)
            else:
                await send({"type": "http.response.body", "body": b"", "more_body": False})
