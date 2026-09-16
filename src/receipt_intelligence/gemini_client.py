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
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

DEFAULT_MODEL = "gemini-3.6-flash"
_ENDPOINT_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


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
