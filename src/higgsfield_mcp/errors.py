"""Structured error taxonomy for backend failures.

Each subclass maps a class of HTTP/transport failure to an actionable message.
``classify_http`` turns a raw HTTP failure into the right typed error so callers
(and the retry layer) can branch on type instead of parsing strings.
"""

from __future__ import annotations

from collections.abc import Mapping

from higgsfield_mcp.backends.base import BackendError


class AuthError(BackendError):
    """401/403 with no bot-challenge signal: credentials are missing or invalid."""


class RateLimitError(BackendError):
    """429: too many requests. ``retry_after`` is seconds from the Retry-After header."""

    def __init__(
        self,
        message: str,
        *,
        retry_after: float | None = None,
        status_code: int | None = None,
        body: str | None = None,
    ) -> None:
        super().__init__(message, status_code=status_code, body=body)
        self.retry_after = retry_after


class BotChallengeError(BackendError):
    """403 Cloudflare managed challenge (TLS fingerprint). Not an auth problem."""


class SchemaError(BackendError):
    """2xx response whose body is missing required fields (e.g. no job id)."""


class NetworkError(BackendError):
    """Transport-level failure (connection reset, timeout, DNS)."""


class CircuitOpenError(BackendError):
    """The circuit breaker is open: the backend is failing and is cooling down."""


class EndpointUnavailableError(BackendError):
    """A capability has no working route in the current API version.

    Distinct from a plain 404 (which usually means a *resource* wasn't found):
    this means the *route itself* isn't real — confirmed by comparing its
    response against a deliberately fabricated path and finding them identical.
    """


def parse_retry_after(value: str | None) -> float | None:
    """Parse a Retry-After header value in delta-seconds form. HTTP-date form is ignored."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def classify_http(
    status_code: int,
    body: str | None = None,
    headers: Mapping[str, str] | None = None,
) -> BackendError:
    """Map an HTTP failure to a typed error."""
    headers = headers or {}
    text = (body or "")[:500]
    lower_headers = {k.lower(): v for k, v in headers.items()}

    if status_code == 403:
        cf = str(lower_headers.get("cf-mitigated", "")).lower()
        if "challenge" in cf or "just a moment" in text.lower():
            return BotChallengeError(
                "Cloudflare TLS-fingerprint challenge (HTTP 403). "
                "Upgrade curl-cffi or retry later from a residential IP.",
                status_code=status_code,
                body=text,
            )
    if status_code in (401, 403):
        return AuthError(
            f"Authentication failed (HTTP {status_code}). Check credentials. {text}",
            status_code=status_code,
            body=text,
        )
    if status_code == 429:
        return RateLimitError(
            "Rate limited (HTTP 429).",
            retry_after=parse_retry_after(lower_headers.get("retry-after")),
            status_code=status_code,
            body=text,
        )
    return BackendError(f"HTTP {status_code}: {text}", status_code=status_code, body=text)
