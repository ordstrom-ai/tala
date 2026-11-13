"""Bounded, text-free correlation metadata for internal HTTP requests.

These identifiers are diagnostic context, never authorization or routing input.
Header values are percent-encoded UTF-8; consumers decode and validate them.
"""

import re
from urllib.parse import quote, unquote

import structlog

MAX_IDENTIFIER_BYTES = 256
MAX_ENCODED_IDENTIFIER_CHARACTERS = MAX_IDENTIFIER_BYTES * 3
CORRELATION_HEADERS = {
    "correlation_id": "X-Tala-Correlation-Id",
    "request_id": "X-Tala-Request-Id",
    "session_id": "X-Tala-Session-Id",
    "offer_id": "X-Tala-Offer-Id",
    "utterance_id": "X-Tala-Utterance-Id",
    "turn_id": "X-Tala-Turn-Id",
    "attempt_id": "X-Tala-Attempt-Id",
}


def correlation_headers(logger, request_id=None):
    """Return headers without altering the logger, payload, or request ID semantics."""
    try:
        context = structlog.get_context(logger)
    except (AttributeError, TypeError):
        context = {}

    values = {field: _value_at(context, field) for field in CORRELATION_HEADERS}
    for candidate in (values["correlation_id"], values["request_id"], request_id):
        root_id = _safe_identifier(candidate, "correlation_id")
        if root_id is not None:
            values["correlation_id"] = root_id
            break
    if request_id is not None:
        values["request_id"] = request_id

    headers = {}
    for field, header in CORRELATION_HEADERS.items():
        value = _safe_identifier(values[field], field)
        if value is not None:
            headers[header] = quote(value, safe="-._~")
    return headers


def correlation_context(headers):
    """Read only the known correlation headers and ignore malformed values."""
    try:
        incoming = {name.lower(): value for name, value in headers.items()}
    except (AttributeError, TypeError):
        return {}

    context = {}
    for field, header in CORRELATION_HEADERS.items():
        encoded_value = incoming.get(header.lower())
        try:
            if len(encoded_value) > MAX_ENCODED_IDENTIFIER_CHARACTERS:
                continue
            if not encoded_value.isascii() or re.search(r"%(?![0-9a-fA-F]{2})", encoded_value):
                continue
            decoded_value = unquote(encoded_value, encoding="utf-8", errors="strict")
        except (TypeError, AttributeError, UnicodeDecodeError):
            continue
        value = _safe_identifier(decoded_value, field)
        if value is not None:
            context[field] = int(value) if field == "turn_id" else value
    return context


def request_id_from_payload(payload):
    """Prefer the payload's local request ID over any transport metadata."""
    request_id = _value_at(payload, "request_id")
    if request_id is not None:
        return request_id
    for field in ("request", "session", "gpt_request"):
        request_id = _value_at(_value_at(payload, field), "request_id")
        if request_id is not None:
            return request_id
    return None


def validated_correlation_context(values):
    """Copy only known diagnostic identifiers; never copy payload or credential fields."""
    context = {}
    for field in CORRELATION_HEADERS:
        value = _safe_identifier(_value_at(values, field), field)
        if value is not None:
            context[field] = int(value) if field == "turn_id" else value
    return context


def _safe_identifier(value, field):
    if field == "turn_id":
        try:
            value = str(value)
            if not value.isdecimal() or len(value) > MAX_IDENTIFIER_BYTES:
                return None
            value = str(int(value))
        except (TypeError, ValueError, OverflowError):
            return None
    try:
        encoded_value = value.encode("utf-8")
        if not value.strip() or len(encoded_value) > MAX_IDENTIFIER_BYTES:
            return None
        if any(ord(character) < 32 or ord(character) == 127 for character in value):
            return None
    except (AttributeError, TypeError, UnicodeEncodeError):
        return None
    return value


def _value_at(value, key):
    try:
        return value[key]
    except (KeyError, TypeError):
        return None
