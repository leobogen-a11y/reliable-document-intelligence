"""Thin HTTP client for Gemini's structured-output generateContent endpoint.

Deliberately minimal and side-effect-isolated: the actual network call is a
single injectable function (``http_post``), so callers - and this project's
automated test suite - can substitute a stub without any real network
access. Production code passes :func:`urllib_http_post` (or an equivalent);
tests pass a fake that returns a canned response and records what it was
called with. See scripts/gemini_smoke_test.py for a real, live check meant
to be run locally with an actual API key.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# gemini-3.6-flash's free tier turned out to allow only 20 requests/day
# (observed via a 429 "generate_content_free_tier_requests" quota error),
# too tight for even a single 100-document comparison run. Free-tier quotas
# are per-model (confirmed empirically: switching model here unblocks
# requests immediately even while gemini-3.6-flash is still exhausted), and
# the "flash-lite" variants are positioned by Google as the cheaper/higher-
# throughput tier - gemini-3.1-flash-lite specifically as "frontier-class
# performance...at a fraction of the cost" per ai.google.dev/gemini-api/docs/models,
# which made it the more promising trade than gemini-3.5-flash-lite for this
# project's precision-first comparison. Re-check this if quota errors return.
DEFAULT_MODEL = "gemini-3.1-flash-lite"
_ENDPOINT_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

# Status codes worth retrying: transient server-side unavailability, where a
# short wait plausibly helps. A 503 "high demand" response from the free
# tier is the one actually observed in practice so far - see CLAUDE.md.
# Deliberately excludes 429: observed free-tier responses ("limit: 20,
# model: gemini-3.6-flash", with a suggested retry delay of 10-35+ seconds)
# indicate a request-rate quota that will not clear within this function's
# few-second backoff window. Retrying it here would just burn through the
# quota faster for no realistic chance of success - a 429 should surface to
# the caller immediately instead.
_RETRYABLE_STATUS_CODES = frozenset({500, 502, 503, 504})
_DEFAULT_MAX_ATTEMPTS = 3
_DEFAULT_INITIAL_DELAY_SECONDS = 2.0


@dataclass(frozen=True)
class HttpResponse:
    status_code: int
    body: dict[str, Any]


HttpPost = Callable[[str, dict[str, Any], dict[str, str]], HttpResponse]


class GeminiError(RuntimeError):
    """Raised when Gemini returns an error, or a response this client cannot use."""


def call_gemini(
    prompt: str,
    *,
    response_schema: dict[str, Any],
    api_key: str,
    http_post: HttpPost,
    model: str = DEFAULT_MODEL,
    temperature: float = 0.0,
) -> dict[str, Any]:
    """Call Gemini with a prompt and a JSON response schema; return the parsed JSON body.

    ``temperature=0.0`` by default: for structured extraction we want the
    most likely reading, not creative variation.
    """

    url = _ENDPOINT_TEMPLATE.format(model=model)
    request_body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json",
            "responseSchema": response_schema,
        },
    }
    headers = {"Content-Type": "application/json", "x-goog-api-key": api_key}

    response = http_post(url, request_body, headers)
    if response.status_code != 200:
        raise GeminiError(
            f"Gemini request failed ({response.status_code}): {_error_message(response.body)}"
        )
    return _extract_json_payload(response.body)


def _error_message(body: dict[str, Any]) -> str:
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("message", body))
    return str(body)


def _extract_json_payload(body: dict[str, Any]) -> dict[str, Any]:
    try:
        parts = body["candidates"][0]["content"]["parts"]
        text = "".join(part.get("text", "") for part in parts)
    except (KeyError, IndexError, TypeError) as exc:
        raise GeminiError(f"unexpected Gemini response shape: {body!r}") from exc

    if not text.strip():
        raise GeminiError("Gemini returned an empty response")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise GeminiError(f"Gemini response was not valid JSON: {text!r}") from exc

    if not isinstance(payload, dict):
        raise GeminiError(f"Gemini response JSON was not an object: {payload!r}")
    return payload


def with_retry(
    http_post: HttpPost,
    *,
    max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    initial_delay_seconds: float = _DEFAULT_INITIAL_DELAY_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
) -> HttpPost:
    """Wrap an ``HttpPost`` with retry-and-backoff for transient failures.

    Only retries responses whose status code indicates transient server-side
    unavailability (see ``_RETRYABLE_STATUS_CODES``); a persistent error
    (e.g. a 400 for a malformed request, or a 429 quota/rate-limit error) is
    returned on the first attempt so :func:`call_gemini` can raise its usual
    ``GeminiError`` without delay. ``sleep`` is injectable so tests can
    exercise the retry loop without waiting in real time.
    """

    def wrapped(url: str, json_body: dict[str, Any], headers: dict[str, str]) -> HttpResponse:
        delay = initial_delay_seconds
        response = http_post(url, json_body, headers)
        for _ in range(max_attempts - 1):
            if response.status_code not in _RETRYABLE_STATUS_CODES:
                return response
            sleep(delay)
            delay *= 2
            response = http_post(url, json_body, headers)
        return response

    return wrapped


def urllib_http_post(url: str, json_body: dict[str, Any], headers: dict[str, str]) -> HttpResponse:
    """Real HTTP POST via the standard library only - no extra SDK dependency."""

    data = json.dumps(json_body).encode("utf-8")
    request = urllib.request.Request(url, data=data, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            return HttpResponse(status_code=response.status, body=json.loads(response.read()))
    except urllib.error.HTTPError as exc:
        body_bytes = exc.read()
        try:
            body = json.loads(body_bytes)
        except json.JSONDecodeError:
            body = {"error": {"message": body_bytes.decode(errors="replace")}}
        return HttpResponse(status_code=exc.code, body=body)


# What production callers should pass by default: a real network call with
# retry-and-backoff for the free tier's occasional transient 503s.
DEFAULT_HTTP_POST: HttpPost = with_retry(urllib_http_post)
