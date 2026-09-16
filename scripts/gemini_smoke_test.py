"""Live smoke test for the Gemini-based extraction approach.

Run this locally (NOT inside the Claude sandbox - generativelanguage.googleapis.com
is blocked there) with a real API key to verify the AI approach end-to-end
against a made-up example receipt:

    export $(grep -v '^#' .env | xargs)   # loads GOOGLE_API_KEY from .env
    .venv/bin/python scripts/gemini_smoke_test.py

Everything this script calls (ai_extraction.py, adapters/gemini.py,
gemini_client.py) is already covered by the automated, fully-mocked test
suite (tests/test_gemini_client.py, tests/test_gemini_adapter.py,
tests/test_ai_extraction.py) - this script exists only to confirm the real
network call and a real model response actually work, which the sandboxed
test suite cannot do.
"""

from __future__ import annotations

import os
import sys

from receipt_intelligence.ai_extraction import extract_with_gemini
from receipt_intelligence.ocr import OcrLine
from receipt_intelligence.validation import build_processing_decision, validate_receipt


def main() -> int:
    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("GOOGLE_API_KEY is not set (check your .env file).", file=sys.stderr)
        return 1

    lines = [
        OcrLine(text="CAFE MUENCHEN", confidence=95.0),
        OcrLine(text="Cappuccino 2 x 3,50 7,00", confidence=93.0),
        OcrLine(text="Croissant 2,50", confidence=94.0),
        OcrLine(text="Zwischensumme 9,50", confidence=92.0),
        OcrLine(text="MwSt 19% 1,81", confidence=91.0),
        OcrLine(text="Gesamt 11,31", confidence=93.0),
        OcrLine(text="EUR", confidence=96.0),
    ]

    print("Calling Gemini...")
    extraction = extract_with_gemini(lines, document_id="smoke-test-001", api_key=api_key)

    print("\n--- extraction ---")
    print(extraction.model_dump_json(indent=2))

    issues = validate_receipt(extraction, allowed_currencies=frozenset({"EUR"}))
    decision = build_processing_decision(issues)

    print("\n--- validation ---")
    for issue in issues:
        print(f"  [{issue.severity.value}] {issue.code}: {issue.message}")
    print(f"requires_review={decision.requires_review} reasons={decision.reasons}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
