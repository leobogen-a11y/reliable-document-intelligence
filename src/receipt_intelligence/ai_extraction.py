"""AI-based extraction approach: OCR text plus a schema-constrained LLM call.

The second of the two approaches to compare from PROJECT_BRIEF.md
("AI-basierter Ansatz: multimodales Modell oder OCR plus Sprachmodell mit
schema-validierter strukturierter Ausgabe"). This project uses the
OCR-plus-language-model variant rather than sending the raw image: the same
reconstructed OCR text that baseline.py parses with rules is instead handed
to Gemini with a schema-constrained prompt, then adapted into the canonical
schema. Reusing the OCR step keeps this a fair comparison against the
baseline (both start from identical input) and keeps API cost down (text
tokens, not image tokens).
"""

from __future__ import annotations

from receipt_intelligence.adapters.gemini import (
    RESPONSE_SCHEMA,
    adapt_gemini_response,
    build_prompt,
)
from receipt_intelligence.domain.models import ReceiptExtraction
from receipt_intelligence.gemini_client import DEFAULT_HTTP_POST, HttpPost, call_gemini
from receipt_intelligence.ocr import OcrLine


def extract_with_gemini(
    lines: list[OcrLine],
    *,
    document_id: str,
    api_key: str,
    http_post: HttpPost = DEFAULT_HTTP_POST,
) -> ReceiptExtraction:
    """Run the AI-based approach on already-OCR'd receipt lines.

    ``http_post`` defaults to a real network call with retry-and-backoff for
    transient failures (see ``gemini_client.with_retry``); pass a stub here
    (as the test suite does) to exercise this function with zero network
    access.
    """

    prompt = build_prompt([line.text for line in lines])
    raw = call_gemini(prompt, response_schema=RESPONSE_SCHEMA, api_key=api_key, http_post=http_post)
    return adapt_gemini_response(raw, document_id=document_id)
