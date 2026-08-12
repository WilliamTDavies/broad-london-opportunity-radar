from __future__ import annotations

import asyncio
import subprocess

import httpx


class CurlTransport(httpx.AsyncBaseTransport):
    """Opt-in local transport for sandboxes that allow curl but block Python sockets.

    Arguments are passed directly to ``subprocess.run`` without a shell. Production and GitHub
    Actions use httpx's normal transport; this exists only to make an identical, auditable live
    capture possible in restricted development environments.
    """

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        command = [
            "curl",
            "--silent",
            "--show-error",
            "--location",
            "--compressed",
            "--max-time",
            "45",
            "--request",
            request.method,
        ]
        for name, value in request.headers.multi_items():
            if name.casefold() not in {"host", "content-length"}:
                command.extend(("--header", f"{name}: {value}"))
        if body:
            command.extend(("--data-binary", "@-"))
        command.extend(("--write-out", "\n%{http_code}", str(request.url)))
        process = await asyncio.to_thread(
            subprocess.run,
            command,
            input=body,
            capture_output=True,
            check=False,
        )
        if process.returncode != 0:
            message = process.stderr.decode(errors="replace").strip() or "curl request failed"
            raise httpx.ConnectError(message, request=request)
        try:
            payload, raw_status = process.stdout.rsplit(b"\n", 1)
            status = int(raw_status)
        except (ValueError, TypeError) as exc:
            raise httpx.RemoteProtocolError(
                "curl response did not include an HTTP status", request=request
            ) from exc
        return httpx.Response(status, content=payload, request=request)
