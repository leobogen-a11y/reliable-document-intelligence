import json

import pytest

from receipt_intelligence.gemini_client import GeminiError, HttpResponse, call_gemini, with_retry

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


def _flaky_http_post(responses: list[HttpResponse], *, calls: list):
    responses_iter = iter(responses)

    def http_post(url, json_body, headers):
        calls.append((url, json_body, headers))
        return next(responses_iter)

    return http_post


def test_with_retry_retries_a_transient_503_then_succeeds() -> None:
    success = HttpResponse(status_code=200, body={"foo": "bar"})
    responses = [HttpResponse(status_code=503, body={"error": {"message": "high demand"}}), success]
    calls: list = []
    sleeps: list[float] = []

    wrapped = with_retry(_flaky_http_post(responses, calls=calls), sleep=sleeps.append)
    result = wrapped("url", {}, {})

    assert result is success
    assert len(calls) == 2
    assert sleeps == [2.0]


def test_with_retry_does_not_retry_a_non_transient_status() -> None:
    response = HttpResponse(status_code=400, body={"error": {"message": "bad request"}})
    calls: list = []
    sleeps: list[float] = []

    wrapped = with_retry(_flaky_http_post([response], calls=calls), sleep=sleeps.append)
    result = wrapped("url", {}, {})

    assert result is response
    assert len(calls) == 1
    assert sleeps == []


def test_with_retry_does_not_retry_a_daily_quota_429() -> None:
    # A 429 on this API has been observed to mean the daily free-tier quota
    # is exhausted, not a short-lived rate limit - retrying would only burn
    # through the remaining quota faster. See the _RETRYABLE_STATUS_CODES
    # comment in gemini_client.py.
    response = HttpResponse(status_code=429, body={"error": {"message": "quota exceeded"}})
    calls: list = []
    sleeps: list[float] = []

    wrapped = with_retry(_flaky_http_post([response], calls=calls), sleep=sleeps.append)
    result = wrapped("url", {}, {})

    assert result is response
    assert len(calls) == 1
    assert sleeps == []


def test_with_retry_gives_up_after_max_attempts() -> None:
    failure = HttpResponse(status_code=503, body={"error": {"message": "high demand"}})
    calls: list = []
    sleeps: list[float] = []

    wrapped = with_retry(
        _flaky_http_post([failure, failure, failure], calls=calls),
        max_attempts=3,
        sleep=sleeps.append,
    )
    result = wrapped("url", {}, {})

    assert result is failure
    assert len(calls) == 3
    assert sleeps == [2.0, 4.0]
