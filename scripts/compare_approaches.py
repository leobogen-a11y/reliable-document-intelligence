"""Compare the baseline (OCR+rules) and Gemini-based approaches on a CORD-v2 sample.

Reads a locally downloaded CORD-v2 parquet split (image bytes + ground truth
embedded together - see DATA_AUDIT.md for how that file was obtained), runs
both extraction approaches on the same OCR output per receipt (keeping the
comparison fair, as ai_extraction.py's docstring explains), scores each
against the CORD ground truth via evaluation.py, and writes a JSON report.

Deliberately uses the validation split, not test: DATA_AUDIT.md's own
conclusion is that the test split stays untouched until models and
thresholds have been chosen on train/validation data.

Supports incremental runs (--offset/--limit) because the free tier's daily
Gemini quota does not comfortably cover all 100 validation documents in one
sitting (see DATA_AUDIT.md, "Nebenbefund: Gemini-Free-Tier-Kontingent"):
each run merges its results into the existing report by document_id rather
than overwriting it, so the comparison can be built up across several runs
(and days) and re-running an already-covered offset/limit range just
refreshes those documents instead of duplicating them.

    export $(grep -v '^#' .env | xargs)
    .venv/bin/python scripts/compare_approaches.py --offset 0 --limit 10
    .venv/bin/python scripts/compare_approaches.py --offset 10 --limit 40
"""

from __future__ import annotations

import argparse
import io
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import duckdb
from PIL import Image

from receipt_intelligence.adapters.cord import adapt_cord_ground_truth
from receipt_intelligence.ai_extraction import extract_with_gemini
from receipt_intelligence.baseline import extract_baseline
from receipt_intelligence.evaluation import DocumentEvaluation, aggregate_evaluation, evaluate_document
from receipt_intelligence.gemini_client import GeminiError
from receipt_intelligence.ocr import run_tesseract_ocr

# Free-tier courtesy delay between Gemini calls; see CLAUDE.md on the earlier
# 503 ("high demand") observed during the manual smoke test.
_GEMINI_CALL_DELAY_SECONDS = 1.0


def load_sample(parquet_path: Path, *, limit: int, offset: int) -> list[tuple[dict[str, Any], str]]:
    connection = duckdb.connect()
    try:
        return connection.execute(
            f"SELECT image, ground_truth FROM read_parquet(?) LIMIT {int(limit)} OFFSET {int(offset)}",
            [str(parquet_path)],
        ).fetchall()
    finally:
        connection.close()


def load_existing_results(output: Path) -> dict[str, dict[str, Any]]:
    """Load a prior report's per-document results, keyed by document_id.

    Returns an empty mapping when no report exists yet. Kept separate from
    the aggregate metrics: those are always recomputed from this raw data
    rather than trusted from a prior run, so the merge logic has one source
    of truth.
    """

    if not output.exists():
        return {}
    payload = json.loads(output.read_text())
    return payload.get("document_results", {})


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", type=Path, default=Path("data/cord-v2/validation/0000.parquet"))
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--output", type=Path, default=Path("reports/baseline_vs_gemini_sample.json"))
    args = parser.parse_args()

    api_key = os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        print("GOOGLE_API_KEY is not set (check your .env file).", file=sys.stderr)
        return 1

    document_results = load_existing_results(args.output)
    print(f"Loaded {len(document_results)} previously evaluated documents from {args.output}")

    rows = load_sample(args.parquet, limit=args.limit, offset=args.offset)
    print(f"Fetched {len(rows)} receipts from {args.parquet} (offset={args.offset}, limit={args.limit})")

    for index, (image_struct, ground_truth_json) in enumerate(rows):
        ground_truth = adapt_cord_ground_truth(ground_truth_json)
        document_id = ground_truth.document_id
        print(f"[{index + 1}/{len(rows)}] {document_id}")

        image = Image.open(io.BytesIO(bytes(image_struct["bytes"])))

        ocr_start = time.perf_counter()
        lines = run_tesseract_ocr(image)
        ocr_seconds = time.perf_counter() - ocr_start

        baseline_start = time.perf_counter()
        baseline_prediction = extract_baseline(lines, document_id=document_id)
        baseline_seconds = ocr_seconds + (time.perf_counter() - baseline_start)
        baseline_eval = evaluate_document(baseline_prediction, ground_truth)

        gemini_error: str | None = None
        gemini_eval: DocumentEvaluation | None = None
        gemini_start = time.perf_counter()
        try:
            gemini_prediction = extract_with_gemini(lines, document_id=document_id, api_key=api_key)
        except (GeminiError, OSError) as exc:
            gemini_prediction = None
            gemini_error = str(exc)
        gemini_seconds = ocr_seconds + (time.perf_counter() - gemini_start)

        if gemini_prediction is not None:
            gemini_eval = evaluate_document(gemini_prediction, ground_truth)
        else:
            print(f"  Gemini failed: {gemini_error}", file=sys.stderr)

        document_results[document_id] = {
            "baseline_seconds": baseline_seconds,
            "gemini_seconds": gemini_seconds,
            "gemini_error": gemini_error,
            "baseline_evaluation": json.loads(baseline_eval.model_dump_json()),
            "gemini_evaluation": json.loads(gemini_eval.model_dump_json()) if gemini_eval is not None else None,
        }

        time.sleep(_GEMINI_CALL_DELAY_SECONDS)

    baseline_evals = [
        DocumentEvaluation.model_validate(entry["baseline_evaluation"]) for entry in document_results.values()
    ]
    gemini_evals = [
        DocumentEvaluation.model_validate(entry["gemini_evaluation"])
        for entry in document_results.values()
        if entry["gemini_evaluation"] is not None
    ]

    baseline_report = aggregate_evaluation(baseline_evals)
    gemini_report = aggregate_evaluation(gemini_evals) if gemini_evals else None

    result = {
        "sample_size": len(document_results),
        "source": str(args.parquet),
        "baseline": json.loads(baseline_report.model_dump_json()),
        "gemini": json.loads(gemini_report.model_dump_json()) if gemini_report is not None else None,
        "gemini_failures": sum(1 for entry in document_results.values() if entry["gemini_error"]),
        "document_results": document_results,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2))

    print(f"\nWrote report to {args.output} ({len(document_results)} documents total)")
    print(json.dumps({"baseline": result["baseline"], "gemini": result["gemini"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
