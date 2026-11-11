from __future__ import annotations

import ipaddress
import socket
from functools import lru_cache
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


class URLPolicyError(ValueError):
    """A target URL violates the configured browser egress policy."""


def _is_allowed_host(host: str, allowlist: tuple[str, ...]) -> bool:
    normalized = host.rstrip(".").lower()
    for entry in allowlist:
        candidate = entry.strip().lower().rstrip(".")
        if candidate.startswith("*."):
            suffix = candidate[2:]
            if normalized == suffix or normalized.endswith("." + suffix):
                return True
        elif normalized == candidate:
            return True
    return False


@lru_cache(maxsize=512)
def _resolved_addresses(host: str, port: int) -> tuple[str, ...]:
    return tuple(
        sorted({item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)})
    )


def validate_target_url(
    url: str,
    *,
    allowed_hosts: tuple[str, ...],
    allow_private_targets: bool = False,
    allow_loopback_targets: bool = False,
) -> str:
    """Validate a URL before navigation and for every browser network request.

    Only HTTP(S) and explicitly allowlisted hosts are accepted. Private, loopback,
    link-local, reserved and unspecified addresses are blocked unless a local
    development environment explicitly opts in.
    """
    try:
        parsed = urlsplit(url.strip())
    except ValueError as exc:
        raise URLPolicyError("Invalid URL.") from exc

    if parsed.scheme not in {"http", "https"}:
        raise URLPolicyError("Only HTTP and HTTPS URLs are allowed.")
    if not parsed.hostname:
        raise URLPolicyError("The URL must include a hostname.")
    if parsed.username or parsed.password:
        raise URLPolicyError("Credentials embedded in URLs are not allowed.")
    try:
        port_value = parsed.port
    except ValueError as exc:
        raise URLPolicyError("Invalid port.") from exc
    if port_value is not None and not (1 <= port_value <= 65535):
        raise URLPolicyError("Invalid port.")

    host = parsed.hostname.rstrip(".").lower()
    if not _is_allowed_host(host, allowed_hosts):
        raise URLPolicyError(f"Host '{host}' is not in ALLOWED_TARGET_HOSTS.")

    port = port_value or (443 if parsed.scheme == "https" else 80)
    try:
        addresses = (str(ipaddress.ip_address(host)),)
    except ValueError:
        try:
            addresses = _resolved_addresses(host, port)
        except OSError as exc:
            raise URLPolicyError(f"Could not safely resolve target host '{host}'.") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_global:
            continue
        if ip.is_loopback and allow_loopback_targets:
            continue
        if ip.is_private and not ip.is_loopback and not ip.is_link_local and allow_private_targets:
            continue
        raise URLPolicyError(
            f"Target resolves to a non-public IP address ({address}); this address range is disabled."
        )

    normalized = urlunsplit((parsed.scheme, parsed.netloc, parsed.path or "/", parsed.query, ""))
    return normalized


def redact_sensitive_text(value: str, limit: int = 1500) -> str:
    """Best-effort redaction before browser text is stored or sent to an LLM."""
    import re

    text = value[:limit]
    patterns = [
        (r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,'\"]+", r"\1[REDACTED]"),
        (r"(?i)(api[_-]?key\s*[:=]\s*)[^\s,'\"]+", r"\1[REDACTED]"),
        (r"(?i)([?&](?:token|access_token|refresh_token|api_key|apikey|key|password|passwd|secret|authorization|client_secret|code|session|sessionid)=)[^&\s]+", r"\1[REDACTED]"),
        (r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", "[EMAIL_REDACTED]"),
        (r"(?<!\d)(?:\+?\d[\d .()-]{7,}\d)(?!\d)", "[PHONE_REDACTED]"),
    ]
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text)
    return text


def redact_sensitive_url(url: str) -> str:
    """Redact common credential-like query parameters before URLs enter reports."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return "[INVALID_URL]"
    sensitive = {
        "token", "access_token", "refresh_token", "api_key", "apikey", "key",
        "password", "passwd", "secret", "authorization", "client_secret",
        "code", "session", "sessionid",
    }
    query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        query.append((key, "[REDACTED]" if key.casefold() in sensitive else value))
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
