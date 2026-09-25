import io
from unittest.mock import patch

from fastapi.testclient import TestClient
from PIL import Image

from receipt_intelligence.api import app
from receipt_intelligence.baseline import extract_baseline
from receipt_intelligence.domain.models import ExtractedField, FieldStatus, ReceiptExtraction
from receipt_intelligence.gemini_client import GeminiError
from receipt_intelligence.ocr import OcrLine

client = TestClient(app)

_ocr_lines = [
    OcrLine(text="Cappuccino 2 x 3,50 7,00", confidence=90.0),
    OcrLine(text="Gesamt 7,00", confidence=90.0),
]


def _png_upload() -> tuple[str, io.BytesIO, str]:
    buffer = io.BytesIO()
    Image.new("RGB", (10, 10), "white").save(buffer, format="PNG")
    buffer.seek(0)
    return "receipt.png", buffer, "image/png"


def test_health() -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_extract_with_baseline_approach() -> None:
    with patch("receipt_intelligence.api.run_tesseract_ocr", return_value=_ocr_lines):
        response = client.post("/extract", files={"file": _png_upload()}, params={"approach": "baseline"})

    assert response.status_code == 200
    body = response.json()
    assert body["extraction"]["total"]["value"] == "7.00"
    assert body["extraction"]["line_items"][0]["description"]["value"] == "Cappuccino"
    assert "decision" in body and "validation_issues" in body


def test_extract_defaults_to_baseline_when_approach_is_omitted() -> None:
    with patch("receipt_intelligence.api.run_tesseract_ocr", return_value=_ocr_lines):
        response = client.post("/extract", files={"file": _png_upload()})

    assert response.status_code == 200
    assert response.json()["extraction"]["total"]["value"] == "7.00"


def test_extract_with_gemini_approach_uses_the_configured_api_key() -> None:
    fake_extraction = ReceiptExtraction(
        document_id="doc-1",
        line_items=[],
        subtotal=ExtractedField(value=None, status=FieldStatus.NOT_PRESENT),
        tax=ExtractedField(value=None, status=FieldStatus.NOT_PRESENT),
        total=ExtractedField(value=None, status=FieldStatus.NOT_PRESENT),
        currency=ExtractedField(value=None, status=FieldStatus.NOT_PRESENT),
    )

    with (
        patch("receipt_intelligence.api.run_tesseract_ocr", return_value=_ocr_lines),
        patch("receipt_intelligence.api.os.environ.get", return_value="test-key"),
        patch("receipt_intelligence.api.extract_with_gemini", return_value=fake_extraction) as mock_extract,
    ):
        response = client.post("/extract", files={"file": _png_upload()}, params={"approach": "gemini"})

    assert response.status_code == 200
    assert mock_extract.call_args.kwargs["api_key"] == "test-key"
    assert response.json()["extraction"]["document_id"] == "doc-1"


def test_extract_with_gemini_approach_without_api_key_returns_503() -> None:
    with (
        patch("receipt_intelligence.api.run_tesseract_ocr", return_value=_ocr_lines),
        patch("receipt_intelligence.api.os.environ.get", return_value=None),
    ):
        response = client.post("/extract", files={"file": _png_upload()}, params={"approach": "gemini"})

    assert response.status_code == 503
    assert "GOOGLE_API_KEY" in response.json()["detail"]


def test_extract_with_gemini_failure_returns_502() -> None:
    with (
        patch("receipt_intelligence.api.run_tesseract_ocr", return_value=_ocr_lines),
        patch("receipt_intelligence.api.os.environ.get", return_value="test-key"),
        patch("receipt_intelligence.api.extract_with_gemini", side_effect=GeminiError("boom")),
    ):
        response = client.post("/extract", files={"file": _png_upload()}, params={"approach": "gemini"})

    assert response.status_code == 502
    assert "boom" in response.json()["detail"]


def test_extract_rejects_unsupported_content_type() -> None:
    response = client.post(
        "/extract",
        files={"file": ("notes.txt", io.BytesIO(b"not an image"), "text/plain")},
    )

    assert response.status_code == 415


def test_extract_rejects_unreadable_image_bytes() -> None:
    response = client.post(
        "/extract",
        files={"file": ("receipt.png", io.BytesIO(b"not actually a png"), "image/png")},
    )

    assert response.status_code == 400


def test_extract_rejects_invalid_approach_value() -> None:
    response = client.post("/extract", files={"file": _png_upload()}, params={"approach": "not-a-real-approach"})

    assert response.status_code == 422


def test_baseline_extraction_reference_stays_consistent_with_direct_call() -> None:
    # Sanity check that the API doesn't reimplement extraction logic: it must
    # produce exactly what calling baseline.py directly would.
    direct = extract_baseline(_ocr_lines, document_id="doc-x")

    with patch("receipt_intelligence.api.run_tesseract_ocr", return_value=_ocr_lines):
        response = client.post("/extract", files={"file": _png_upload()}, params={"approach": "baseline"})

    body_total = response.json()["extraction"]["total"]["value"]
    assert body_total == str(direct.total.value)
