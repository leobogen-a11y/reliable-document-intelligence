import json

import pytest

from receipt_intelligence.gemini_client import GeminiError, HttpResponse, call_gemini

SCHEMA = {"type": "OBJECT", "properties": {"foo": {"type": "STRING"}}}


def _stub(response: HttpResponse, *, calls: list):
    def http_post(url, json_body, headers):
        calls.append((url, json_body, headers))
        return response

    return http_post


def test_successful_call_returns_parsed_json() -> None:
    payload = {"foo": "bar"}
    response = HttpResponse(
        status_code=200,
        body={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]},
    )
    calls: list = []

    result = call_gemini(
        "a prompt", response_schema=SCHEMA, api_key="k", http_post=_stub(response, calls=calls)
    )

    assert result == payload
    assert len(calls) == 1


def test_request_uses_the_api_key_header_and_schema() -> None:
    response = HttpResponse(
        status_code=200,
        body={"candidates": [{"content": {"parts": [{"text": "{}"}]}}]},
    )
    calls: list = []

    call_gemini(
        "hello", response_schema=SCHEMA, api_key="secret-key", http_post=_stub(response, calls=calls)
    )

    url, body, headers = calls[0]
    assert headers["x-goog-api-key"] == "secret-key"
    assert body["contents"][0]["parts"][0]["text"] == "hello"
    assert body["generationConfig"]["responseSchema"] == SCHEMA
    assert body["generationConfig"]["responseMimeType"] == "application/json"
    assert "gemini" in url


def test_non_200_status_raises_gemini_error() -> None:
    response = HttpResponse(status_code=429, body={"error": {"message": "rate limited"}})

    with pytest.raises(GeminiError, match="rate limited"):
        call_gemini("x", response_schema=SCHEMA, api_key="k", http_post=_stub(response, calls=[]))


def test_missing_candidates_raises_gemini_error() -> None:
    response = HttpResponse(status_code=200, body={})

    with pytest.raises(GeminiError, match="unexpected Gemini response shape"):
        call_gemini("x", response_schema=SCHEMA, api_key="k", http_post=_stub(response, calls=[]))


def test_empty_text_raises_gemini_error() -> None:
    response = HttpResponse(
        status_code=200, body={"candidates": [{"content": {"parts": [{"text": "  "}]}}]}
    )

    with pytest.raises(GeminiError, match="empty response"):
        call_gemini("x", response_schema=SCHEMA, api_key="k", http_post=_stub(response, calls=[]))


def test_invalid_json_text_raises_gemini_error() -> None:
    response = HttpResponse(
        status_code=200, body={"candidates": [{"content": {"parts": [{"text": "not json"}]}}]}
    )

    with pytest.raises(GeminiError, match="not valid JSON"):
        call_gemini("x", response_schema=SCHEMA, api_key="k", http_post=_stub(response, calls=[]))


def test_non_object_json_raises_gemini_error() -> None:
    response = HttpResponse(
        status_code=200, body={"candidates": [{"content": {"parts": [{"text": "[1, 2, 3]"}]}}]}
    )

    with pytest.raises(GeminiError, match="not an object"):
        call_gemini("x", response_schema=SCHEMA, api_key="k", http_post=_stub(response, calls=[]))
