"""Minimal OpenAI-compatible inference adapter with evidence receipts.

This is a provider adapter, not an AIOS authority engine. The caller must obtain
DECISION / permit / lineage identifiers before calling it. It never retries
requests automatically: a timeout after dispatch is UNKNOWN, not proof of failure.
Only a syntactically valid HTTP response is OBSERVED; semantic/model correctness
must be verified by a separate caller-owned verifier.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
import time
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


Transport = Callable[[str, bytes, dict[str, str], float], tuple[int, bytes]]


@dataclass(frozen=True)
class InferenceRequest:
    decision_id: str
    permit_id: str
    effect_id: str
    attempt_id: str
    model: str
    prompt: str
    base_url: str = "http://127.0.0.1:8000/v1"
    timeout_seconds: float = 60.0
    max_tokens: int = 256
    temperature: float = 0.0


@dataclass(frozen=True)
class InferenceReceipt:
    schema_version: str
    state: str
    provider: str
    decision_id: str
    permit_id: str
    effect_id: str
    attempt_id: str
    model: str
    dispatched: bool
    http_status: int | None
    elapsed_ms: int
    output: str | None
    output_sha256: str | None
    usage: dict[str, int]
    error_code: str | None
    error: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class RequestBlocked(ValueError):
    """Request rejected before any network dispatch."""


def _validate(req: InferenceRequest) -> None:
    for field in ("decision_id", "permit_id", "effect_id", "attempt_id", "model"):
        value = getattr(req, field)
        if not isinstance(value, str) or not value.strip():
            raise RequestBlocked(f"{field} is required")
    if not isinstance(req.prompt, str) or not req.prompt.strip():
        raise RequestBlocked("prompt is required")
    if not isinstance(req.timeout_seconds, (int, float)) or req.timeout_seconds <= 0:
        raise RequestBlocked("timeout_seconds must be positive")
    if not isinstance(req.max_tokens, int) or isinstance(req.max_tokens, bool) or req.max_tokens < 1:
        raise RequestBlocked("max_tokens must be a positive integer")
    if not isinstance(req.temperature, (int, float)) or not 0 <= req.temperature <= 2:
        raise RequestBlocked("temperature must be between 0 and 2")
    parsed = urlsplit(req.base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise RequestBlocked("base_url must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise RequestBlocked("base_url must not contain credentials, query, or fragment")


def _http_transport(url: str, body: bytes, headers: dict[str, str], timeout: float) -> tuple[int, bytes]:
    request = Request(url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except HTTPError as exc:
        # An HTTP response was received; return it to the protocol parser.
        return exc.code, exc.read()
    except (URLError, TimeoutError, OSError) as exc:
        raise ConnectionError(type(exc).__name__) from exc


def infer(req: InferenceRequest, *, api_key: str | None = None,
          transport: Transport = _http_transport) -> InferenceReceipt:
    """Execute one inference attempt and return a lineage-bearing receipt.

    Never auto-retries. If transport fails after the call was initiated, the
    receipt is UNKNOWN because the server may have completed the generation.
    """
    started = time.monotonic()
    try:
        _validate(req)
    except RequestBlocked as exc:
        return InferenceReceipt(
            "1.0", "BLOCKED", "kyojin-openai-compatible", req.decision_id,
            req.permit_id, req.effect_id, req.attempt_id, req.model, False,
            None, 0, None, None, {}, "INVALID_REQUEST", str(exc),
        )

    base = req.base_url.rstrip("/")
    url = base + "/chat/completions"
    payload = json.dumps({
        "model": req.model,
        "messages": [{"role": "user", "content": req.prompt}],
        "max_tokens": req.max_tokens,
        "temperature": req.temperature,
    }, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = "Bearer " + api_key

    status: int | None = None
    try:
        status, raw = transport(url, payload, headers, float(req.timeout_seconds))
        elapsed = int((time.monotonic() - started) * 1000)
        if not 200 <= status < 300:
            return InferenceReceipt(
                "1.0", "UNKNOWN", "kyojin-openai-compatible", req.decision_id,
                req.permit_id, req.effect_id, req.attempt_id, req.model, True,
                status, elapsed, None, None, {}, "HTTP_ERROR",
                f"provider returned HTTP {status}; no automatic retry",
            )
        data = json.loads(raw.decode("utf-8"))
        choices = data.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise ValueError("missing choices[0]")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise ValueError("missing choices[0].message")
        content = message.get("content")
        if not isinstance(content, str):
            raise ValueError("message.content must be a string")
        usage_obj = data.get("usage") or {}
        usage = {}
        if isinstance(usage_obj, dict):
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage_obj.get(key)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    usage[key] = value
        digest = sha256(content.encode("utf-8")).hexdigest()
        return InferenceReceipt(
            "1.0", "OBSERVED", "kyojin-openai-compatible", req.decision_id,
            req.permit_id, req.effect_id, req.attempt_id, req.model, True,
            status, elapsed, content, digest, usage, None, None,
        )
    except (ConnectionError, TimeoutError, OSError) as exc:
        return InferenceReceipt(
            "1.0", "UNKNOWN", "kyojin-openai-compatible", req.decision_id,
            req.permit_id, req.effect_id, req.attempt_id, req.model, True,
            status, int((time.monotonic() - started) * 1000), None, None, {},
            "TRANSPORT_UNKNOWN", str(exc),
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, TypeError, AttributeError) as exc:
        return InferenceReceipt(
            "1.0", "UNKNOWN", "kyojin-openai-compatible", req.decision_id,
            req.permit_id, req.effect_id, req.attempt_id, req.model, True,
            status, int((time.monotonic() - started) * 1000), None, None, {},
            "INVALID_PROVIDER_RESPONSE", str(exc),
        )
