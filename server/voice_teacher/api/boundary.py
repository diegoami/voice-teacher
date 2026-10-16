"""Bearer/origin/body boundary before request parsing, including chunked uploads."""
from urllib.parse import urlsplit

from starlette.responses import JSONResponse


def error(status, code, message):
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status,
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"})


class Guard:
    def __init__(self, app, *, auth, origin, max_json_bytes, max_audio_bytes):
        self.app, self.auth, self.origin = app, auth, origin
        parsed = urlsplit(origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
            raise ValueError("configure one exact HTTP(S) origin without trailing slash")
        self.host = parsed.netloc.lower()
        self.max_json_bytes, self.max_audio_bytes = max_json_bytes, max_audio_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] == "websocket":
            await send({"type": "websocket.close", "code": 1008}); return
        if scope["type"] != "http": return await self.app(scope, receive, send)
        headers = {}
        for key, value in scope.get("headers", []): headers.setdefault(key.lower(), []).append(value.decode("latin-1"))

        async def reject(status, code, message):
            await error(status, code, message)(scope, receive, send)

        if headers.get(b"host") != [self.host]: return await reject(400, "invalid_host", "Host is not configured")
        origin = headers.get(b"origin")
        if origin is not None and origin != [self.origin]: return await reject(403, "invalid_origin", "Origin is not allowed")
        if headers.get(b"sec-fetch-site") == ["cross-site"]: return await reject(403, "invalid_origin", "Cross-site requests are not allowed")
        path = scope["path"]
        if path.startswith("/api/"):
            pairing = path == "/api/v1/pair" and scope["method"] == "POST"
            if not pairing:
                authorization = headers.get(b"authorization", [])
                principal = None
                if len(authorization) == 1 and authorization[0].startswith("Bearer "):
                    principal = self.auth.authenticate(authorization[0][7:])
                if principal is None: return await reject(401, "unauthenticated", "A valid bearer token is required")
                operator = path.startswith("/api/v1/operator/")
                if operator != principal.operator: return await reject(403, "forbidden", "This identity cannot access this endpoint")
                scope.setdefault("state", {})["principal"] = principal
            limit = self.max_audio_bytes if path.endswith("/audio") and scope["method"] == "POST" else self.max_json_bytes
            sizes = headers.get(b"content-length", [])
            if sizes:
                if len(sizes) != 1 or not sizes[0].isdigit(): return await reject(400, "invalid_length", "Invalid content length")
                if int(sizes[0]) > limit: return await reject(413, "body_too_large", "Request body exceeds the configured limit")
            parts, size = [], 0
            while True:
                message = await receive()
                if message["type"] == "http.disconnect": return
                data = message.get("body", b""); size += len(data)
                if size > limit: return await reject(413, "body_too_large", "Request body exceeds the configured limit")
                parts.append(data)
                if not message.get("more_body", False): break
            body = b"".join(parts)
            sent = False
            original_receive = receive
            async def replay():
                nonlocal sent
                if not sent:
                    sent = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await original_receive()
        else:
            replay = receive

        async def secure(message):
            if message["type"] == "http.response.start":
                extra = [(b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer")]
                if path.startswith("/api/"): extra.append((b"cache-control", b"no-store"))
                message = {**message, "headers": [*message.get("headers", []), *extra]}
            await send(message)
        await self.app(scope, replay, secure)
