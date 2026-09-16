"""Reliable receipt extraction and validation."""

from receipt_intelligence.domain.models import (
    BoundingBox,
    Evidence,
    ExtractedField,
    FieldStatus,
    LineItem,
    ProcessingDecision,
    ReceiptExtraction,
    ReceiptResult,
    ReviewReason,
    ValidationIssue,
    ValidationSeverity,
)
from receipt_intelligence.validation import build_processing_decision, validate_receipt
from receipt_intelligence.baseline import extract_baseline
from receipt_intelligence.ocr import OcrLine, run_tesseract_ocr
from receipt_intelligence.evaluation import (
    DocumentEvaluation,
    EvaluationReport,
    FieldComparison,
    FieldOutcome,
    LineItemMatchResult,
    aggregate_evaluation,
    compare_field,
    evaluate_document,
    evaluate_line_items,
    try_parse_extraction,
)

__all__ = [
    "BoundingBox",
    "Evidence",
    "ExtractedField",
    "FieldStatus",
    "LineItem",
    "ProcessingDecision",
    "ReceiptExtraction",
    "ReceiptResult",
    "ReviewReason",
    "ValidationIssue",
    "ValidationSeverity",
    "build_processing_decision",
    "validate_receipt",
    "DocumentEvaluation",
    "EvaluationReport",
    "FieldComparison",
    "FieldOutcome",
    "LineItemMatchResult",
    "aggregate_evaluation",
    "compare_field",
    "evaluate_document",
    "evaluate_line_items",
    "try_parse_extraction",
    "extract_baseline",
    "OcrLine",
    "run_tesseract_ocr",
]

