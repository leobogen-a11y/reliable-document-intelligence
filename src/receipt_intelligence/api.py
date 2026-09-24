"""Small documented HTTP API wrapping both extraction approaches.

This is deliberately thin: it does no extraction logic of its own. It reads
an uploaded receipt image, runs OCR once, hands the OCR lines to whichever
approach the caller picked (baseline.py or ai_extraction.py - both already
built, tested, and compared independently of this layer), then runs the same
validation and decision policy from validation.py that every other entry
point in this project uses. The response is the project's own
``ReceiptResult`` - extraction, validation issues, and the auto-accept/review
decision together, per SCHEMA_DESIGN.md's product promise that the API never
returns "just JSON" without that context attached.

PDF input (mentioned as in-scope in PROJECT_BRIEF.md) is not implemented yet
- only JPEG/PNG. Documented here rather than silently accepted and mishandled
until there is a concrete need and a chosen PDF-to-image dependency.

    uvicorn receipt_intelligence.api:app --reload
"""

from __future__ import annotations

import io
import os
import uuid
from typing import Literal

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from PIL import Image, UnidentifiedImageError

from receipt_intelligence.ai_extraction import extract_with_gemini
from receipt_intelligence.baseline import extract_baseline
from receipt_intelligence.domain.models import ReceiptExtraction, ReceiptResult
from receipt_intelligence.gemini_client import GeminiError
from receipt_intelligence.ocr import run_tesseract_ocr
from receipt_intelligence.validation import build_processing_decision, validate_receipt

_SUPPORTED_CONTENT_TYPES = {"image/jpeg", "image/png"}

app = FastAPI(
    title="Reliable Document Intelligence API",
    description=(
        "Extracts structured data from a single receipt image, validates it, "
        "and returns an auto-accept/review decision. See SCHEMA_DESIGN.md and "
        "PROJECT_BRIEF.md in the project repository for the design rationale."
    ),
    version="0.1.0",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/extract", response_model=ReceiptResult)
async def extract(
    file: UploadFile = File(...),
    approach: Literal["baseline", "gemini"] = Query(
        default="baseline",
        description="Which extraction approach to run. 'gemini' requires GOOGLE_API_KEY to be set.",
    ),
) -> ReceiptResult:
    if file.content_type not in _SUPPORTED_CONTENT_TYPES:
        raise HTTPException(
            status_code=415,
            detail=(
                f"unsupported content type {file.content_type!r}; "
                f"expected one of {sorted(_SUPPORTED_CONTENT_TYPES)} (PDF is not yet supported)"
            ),
        )

    raw_bytes = await file.read()
    try:
        image = Image.open(io.BytesIO(raw_bytes))
        image.load()
    except UnidentifiedImageError as exc:
        raise HTTPException(status_code=400, detail="uploaded file is not a readable image") from exc

    document_id = f"upload-{uuid.uuid4().hex[:12]}"
    lines = run_tesseract_ocr(image)
    extraction = _run_approach(approach, lines, document_id=document_id)

    issues = validate_receipt(extraction)
    decision = build_processing_decision(issues)
    return ReceiptResult(extraction=extraction, validation_issues=issues, decision=decision)


def _run_approach(approach: Literal["baseline", "gemini"], lines, *, document_id: str) -> ReceiptExtraction:
    if approach == "baseline":
        return extract_baseline(lines, document_id=document_id)

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="the 'gemini' approach is not available: GOOGLE_API_KEY is not configured on the server",
        )
    try:
        return extract_with_gemini(lines, document_id=document_id, api_key=api_key)
    except GeminiError as exc:
        raise HTTPException(status_code=502, detail=f"Gemini extraction failed: {exc}") from exc
