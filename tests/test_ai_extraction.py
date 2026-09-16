import json
from decimal import Decimal

from receipt_intelligence.ai_extraction import extract_with_gemini
from receipt_intelligence.gemini_client import HttpResponse
from receipt_intelligence.ocr import OcrLine


def _stub_returning(payload: dict, *, calls: list):
    def http_post(url, json_body, headers):
        calls.append((url, json_body, headers))
        return HttpResponse(
            status_code=200,
            body={"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]},
        )

    return http_post


def test_extract_with_gemini_adapts_the_mocked_response() -> None:
    payload = {
        "line_items": [
            {
                "description": {"status": "extracted", "value": "Cappuccino"},
                "quantity": {"status": "extracted", "value": "2"},
                "unit_price": {"status": "extracted", "value": "3,50"},
                "line_total": {"status": "extracted", "value": "7,00"},
            }
        ],
        "subtotal": {"status": "extracted", "value": "7,00"},
        "tax": {"status": "not_present", "value": None},
        "total": {"status": "extracted", "value": "7,00"},
        "currency": {"status": "extracted", "value": "EUR"},
    }
    calls: list = []
    lines = [OcrLine(text="Cappuccino 2 x 3,50 7,00", confidence=90.0), OcrLine(text="Gesamt 7,00", confidence=90.0)]

    extraction = extract_with_gemini(
        lines, document_id="doc-1", api_key="test-key", http_post=_stub_returning(payload, calls=calls)
    )

    assert extraction.document_id == "doc-1"
    assert extraction.total.value == Decimal("7.00")
    assert extraction.line_items[0].description.value == "Cappuccino"

    # the prompt actually sent to Gemini contains the OCR text
    _, request_body, _ = calls[0]
    prompt_text = request_body["contents"][0]["parts"][0]["text"]
    assert "Cappuccino 2 x 3,50 7,00" in prompt_text
    assert "Gesamt 7,00" in prompt_text
