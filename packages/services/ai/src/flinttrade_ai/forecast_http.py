"""Authenticated, bounded HTTP transport for an independently installed worker.

This is a transport, not rights, tariff or evidence authority. The app's durable
attempt owner must admit each operation in ``before_invoke`` before any I/O.
Abandoned HTTP requests do not prove remote computation was cancelled.
"""

from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import math
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from flinttrade_core.service_providers import ModelIdentity

from .forecast_protocol import (
    MAX_FORECAST_BODY_BYTES,
    ForecastOutput,
    ForecastProtocolError,
    decode_forecast_response,
    encode_forecast_request,
)
from .forecasting import ForecastCapabilities, ForecastRequest


class ForecastTransportError(RuntimeError):
    """A worker response or transport lifetime is unavailable; never retry it implicitly."""


@dataclass(frozen=True, slots=True)
class ForecastInvocation:
    """Non-secret exact input to the runtime's write-ahead admission callback."""

    attempt_id: str
    kind: str
    model: ModelIdentity
    body_digest: str
    body_bytes: int


@dataclass(frozen=True, slots=True)
class ForecastTransportResult:
    """Validated worker data, still requiring durable recording and central rights."""

    output: ForecastOutput
    body: bytes
    received_at: datetime


def _endpoint(value: object) -> str:
    if type(value) is not str or not value or len(value) > 2048 or any(ord(c) < 33 for c in value):
        raise ValueError("forecast endpoint must be bounded URL text")
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment):
        raise ValueError("forecast endpoint requires HTTP(S) without URL credentials, query or fragment")
    if parsed.port is not None and not 1 <= parsed.port <= 65535:
        raise ValueError("invalid forecast endpoint port")
    if parsed.scheme == "http":
        try:
            if not ipaddress.ip_address(parsed.hostname).is_loopback:
                raise ValueError("not loopback")
        except ValueError as exc:
            raise ValueError("plaintext forecast endpoints require a literal loopback address") from exc
    return value.rstrip("/")


def _positive_seconds(value: object) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not 0 < value <= 300:
        raise ValueError("forecast timeout must be finite and between 0 and 300 seconds")
    return float(value)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ForecastTransportError("duplicate handshake field")
        result[key] = value
    return result


class ForecastHttpTransport:
    """One app-owned transport with explicit admission, no queue and no retries.

    An authenticated matching handshake proves endpoint consistency only. It
    does not independently attest model weights or their licence. Model/data
    rights must still be resolved outside this object, defaulting to unknown.
    ``transport`` is an explicit synthetic/host injection seam, not user config.
    """

    def __init__(
        self, endpoint: str, credential: str, model: ModelIdentity, capabilities: ForecastCapabilities, *,
        before_invoke: Callable[[ForecastInvocation], Awaitable[None]],
        max_concurrent: int = 1, timeout_seconds: float = 60,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._endpoint = _endpoint(endpoint)
        if type(credential) is not str or not re.fullmatch(r"[A-Za-z0-9._~-]{16,4096}", credential):
            raise ValueError("forecast endpoint requires a bounded credential")
        if type(model) is not ModelIdentity or type(capabilities) is not ForecastCapabilities:
            raise ValueError("exact pinned model and capabilities are required")
        if not callable(before_invoke):
            raise ValueError("a write-ahead invocation callback is required")
        if type(max_concurrent) is not int or not 1 <= max_concurrent <= 8:
            raise ValueError("forecast concurrency must be between 1 and 8")
        self._timeout = _positive_seconds(timeout_seconds)
        self._model, self._capabilities, self._before_invoke = model, capabilities, before_invoke
        self._limit, self._active = max_concurrent, 0
        self._closed, self._ready = False, False
        self._pid, self._loop = os.getpid(), None
        self._client = httpx.AsyncClient(
            headers={"Authorization": f"Bearer {credential}", "Accept": "application/json", "Accept-Encoding": "identity"},
            trust_env=False, follow_redirects=False, timeout=self._timeout, transport=transport,
            limits=httpx.Limits(max_connections=max_concurrent, max_keepalive_connections=max_concurrent),
        )

    def _check_owner(self) -> None:
        if self._pid != os.getpid():
            raise ForecastTransportError("forecast transport cannot cross a process boundary")
        loop = asyncio.get_running_loop()
        if self._loop is None:
            self._loop = loop
        elif self._loop is not loop:
            raise ForecastTransportError("forecast transport cannot cross an event-loop boundary")
        if self._closed:
            raise ForecastTransportError("forecast transport is closed")

    def _remaining(self, deadline: datetime) -> float:
        if type(deadline) is not datetime or deadline.tzinfo is None or deadline.utcoffset() != UTC.utcoffset(deadline):
            raise ValueError("forecast deadline must be UTC")
        remaining = (deadline - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise ForecastTransportError("forecast deadline expired")
        return min(remaining, self._timeout)

    async def _send(self, kind: str, attempt_id: str, deadline: datetime, body: bytes) -> bytes:
        self._check_owner()
        remaining = self._remaining(deadline)
        if type(attempt_id) is not str or not attempt_id.strip() or len(attempt_id) > 256:
            raise ValueError("forecast attempt identity is required")
        if self._active >= self._limit:
            raise ForecastTransportError("forecast worker is busy")
        self._active += 1
        try:
            async with asyncio.timeout(remaining):
                await self._before_invoke(ForecastInvocation(
                    attempt_id, kind, self._model, hashlib.sha256(body).hexdigest(), len(body),
                ))
                self._check_owner()
                self._remaining(deadline)
                try:
                    async with self._client.stream(
                        "GET" if kind == "handshake" else "POST",
                        self._endpoint + ("/capabilities" if kind == "handshake" else "/forecast"),
                        content=body, headers={"Content-Type": "application/json"},
                    ) as response:
                        if response.status_code != 200:
                            raise ForecastTransportError("forecast worker returned an unsuccessful status")
                        if response.headers.get("content-encoding", "identity").lower() != "identity":
                            raise ForecastTransportError("compressed forecast bodies are not supported")
                        limit = 16 * 1024 if kind == "handshake" else MAX_FORECAST_BODY_BYTES
                        length = response.headers.get("content-length")
                        if length is not None and (not length.isascii() or not length.isdecimal() or int(length) > limit):
                            raise ForecastTransportError("forecast body size exceeds the protocol limit")
                        chunks, size = [], 0
                        async for chunk in response.aiter_bytes(chunk_size=64 * 1024):
                            size += len(chunk)
                            if size > limit:
                                raise ForecastTransportError("forecast body size exceeds the protocol limit")
                            chunks.append(chunk)
                        self._remaining(deadline)
                        if not size:
                            raise ForecastTransportError("forecast worker returned an empty body")
                        return b"".join(chunks)
                except httpx.HTTPError:
                    raise ForecastTransportError("forecast worker transport failed") from None
        except TimeoutError:
            raise ForecastTransportError("forecast deadline expired; remote outcome is unknown") from None
        finally:
            self._active -= 1

    async def handshake(self, attempt_id: str, deadline: datetime) -> None:
        """Bind the version/model/capabilities through a separate admitted probe."""
        self._ready = False
        body = await self._send("handshake", attempt_id, deadline, b"")
        expected = {"protocol_version": 1, "model": self._model.to_public_dict(), "capabilities": asdict(self._capabilities)}
        try:
            value = json.loads(body, object_pairs_hook=_unique_object)
            # Canonical JSON comparison preserves exact number/bool distinctions.
            if json.dumps(value, sort_keys=True, allow_nan=False) != json.dumps(expected, sort_keys=True, allow_nan=False):
                raise ForecastTransportError("forecast handshake does not match the pinned worker")
        except (ValueError, TypeError, RecursionError):
            raise ForecastTransportError("malformed forecast handshake") from None
        self._ready = True

    async def forecast(self, request: ForecastRequest) -> ForecastTransportResult:
        """Return validated raw output; runtime recording/policy still precedes use."""
        self._check_owner()
        if not self._ready:
            raise ForecastTransportError("a successful worker handshake is required")
        if type(request) is not ForecastRequest:
            raise ValueError("an exact forecast request is required")
        self._capabilities.validate(request)
        body = await self._send("forecast", request.request_id, request.deadline, encode_forecast_request(request))
        try:
            output = decode_forecast_response(body, request=request, expected_model=self._model)
        except ForecastProtocolError:
            raise ForecastTransportError("invalid forecast worker output") from None
        return ForecastTransportResult(output, body, datetime.now(UTC))

    async def close(self, timeout_seconds: float) -> None:
        """Close HTTP resources; this is not confirmation of remote cancellation."""
        seconds = _positive_seconds(timeout_seconds)
        if self._closed:
            return
        self._check_owner()
        self._closed, self._ready = True, False
        async with asyncio.timeout(seconds):
            await self._client.aclose()
