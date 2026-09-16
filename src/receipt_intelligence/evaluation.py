"""Model-independent evaluation: compare a prediction against ground truth.

This module never needs an actual extraction model to be useful or testable
- it operates purely on two ``ReceiptExtraction`` instances (a prediction and
a ground truth) and on the ``ValidationIssue``/``ProcessingDecision`` output
of :mod:`receipt_intelligence.validation`. That is deliberate: the harness is
built and tested against CORD's own ground truth (compared to itself) before
any real extraction approach exists, so metric bugs are not confused with
model errors later (see PROJECT_BRIEF.md, Arbeitspaket 4).

A field whose ground-truth status is ``not_annotated`` is excluded from
accuracy scoring rather than treated as a miss: the dataset itself does not
say what the correct value is, so scoring it would either invent a penalty
or invent a reward (see PROJECT_BRIEF.md / DATA_AUDIT.md on the
"nicht angegeben" vs. "nicht erkannt" distinction).
"""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from receipt_intelligence.domain.models import (
    ExtractedField,
    FieldStatus,
    LineItem,
    ProcessingDecision,
    ReceiptExtraction,
    ValidationIssue,
)
from receipt_intelligence.normalization import normalize_text
from receipt_intelligence.validation import build_processing_decision, validate_receipt

# Line-item fields, in the order used to build a matching key. description and
# line_total are weighted higher because they are extracted for >99% of CORD
# positions (see DATA_AUDIT.md); quantity and unit_price are extracted far
# less often (90.45% / 28.60%) and are therefore weaker matching signals.
_LINE_ITEM_FIELD_WEIGHTS = {
    "description": 2,
    "line_total": 2,
    "quantity": 1,
    "unit_price": 1,
}

ARITHMETIC_ISSUE_CODES = frozenset({"LINE_TOTAL_MISMATCH", "DOCUMENT_TOTAL_MISMATCH"})


class FieldOutcome(str, Enum):
    """Result of comparing one predicted field to its ground truth."""

    CORRECT = "correct"
    INCORRECT = "incorrect"
    NOT_EVALUABLE = "not_evaluable"


class FieldComparison(BaseModel):
    """One field-level comparison result."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    field_path: str
    outcome: FieldOutcome
    exact_match: bool | None = None


def compare_field(
    predicted: ExtractedField[Any],
    ground_truth: ExtractedField[Any],
    *,
    field_path: str,
) -> FieldComparison:
    """Compare one predicted field to its ground truth.

    Both "hallucinating" a value the document does not have and missing a
    value it does have count as incorrect - the comparison is symmetric.
    """

    if ground_truth.status is FieldStatus.NOT_ANNOTATED:
        return FieldComparison(field_path=field_path, outcome=FieldOutcome.NOT_EVALUABLE)

    gt_present = ground_truth.status is FieldStatus.EXTRACTED
    pred_present = predicted.status is FieldStatus.EXTRACTED

    if not gt_present and not pred_present:
        return FieldComparison(field_path=field_path, outcome=FieldOutcome.CORRECT, exact_match=True)

    if gt_present != pred_present:
        return FieldComparison(field_path=field_path, outcome=FieldOutcome.INCORRECT, exact_match=False)

    exact = predicted.value == ground_truth.value
    normalized = _values_match_normalized(predicted.value, ground_truth.value)
    outcome = FieldOutcome.CORRECT if normalized else FieldOutcome.INCORRECT
    return FieldComparison(field_path=field_path, outcome=outcome, exact_match=exact)


def _values_match_normalized(predicted: Any, ground_truth: Any) -> bool:
    if isinstance(predicted, str) and isinstance(ground_truth, str):
        return normalize_text(predicted).casefold() == normalize_text(ground_truth).casefold()
    if isinstance(predicted, Decimal) and isinstance(ground_truth, Decimal):
        return predicted == ground_truth
    return predicted == ground_truth


def _document_field_comparisons(
    predicted: ReceiptExtraction,
    ground_truth: ReceiptExtraction,
) -> list[FieldComparison]:
    return [
        compare_field(predicted.subtotal, ground_truth.subtotal, field_path="subtotal"),
        compare_field(predicted.tax, ground_truth.tax, field_path="tax"),
        compare_field(predicted.total, ground_truth.total, field_path="total"),
        compare_field(predicted.currency, ground_truth.currency, field_path="currency"),
    ]


def _line_item_similarity(predicted: LineItem, ground_truth: LineItem) -> int:
    score = 0
    for name, weight in _LINE_ITEM_FIELD_WEIGHTS.items():
        comparison = compare_field(
            getattr(predicted, name),
            getattr(ground_truth, name),
            field_path=name,
        )
        if comparison.outcome is FieldOutcome.CORRECT:
            score += weight
    return score


def _match_line_items(
    predicted: list[LineItem],
    ground_truth: list[LineItem],
) -> list[tuple[int, int]]:
    """Greedily pair predicted and ground-truth line items by field similarity.

    Each side is used at most once. A pair with zero matching fields is never
    proposed, so an item with nothing in common with any ground-truth item is
    left unmatched (counted as a false positive) rather than paired
    arbitrarily.
    """

    scored_pairs = [
        (_line_item_similarity(p_item, g_item), p_idx, g_idx)
        for p_idx, p_item in enumerate(predicted)
        for g_idx, g_item in enumerate(ground_truth)
    ]
    scored_pairs = [triple for triple in scored_pairs if triple[0] > 0]
    scored_pairs.sort(key=lambda triple: triple[0], reverse=True)

    matched_pred: set[int] = set()
    matched_gt: set[int] = set()
    matches: list[tuple[int, int]] = []
    for _score, p_idx, g_idx in scored_pairs:
        if p_idx in matched_pred or g_idx in matched_gt:
            continue
        matched_pred.add(p_idx)
        matched_gt.add(g_idx)
        matches.append((p_idx, g_idx))
    return matches


class LineItemMatchResult(BaseModel):
    """Outcome of matching a prediction's line items to ground truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    predicted_count: int
    ground_truth_count: int
    matched_count: int
    precision: float | None
    recall: float | None
    f1: float | None
    field_comparisons: list[FieldComparison]


def evaluate_line_items(
    predicted: list[LineItem],
    ground_truth: list[LineItem],
) -> LineItemMatchResult:
    matches = _match_line_items(predicted, ground_truth)
    matched_count = len(matches)

    precision = matched_count / len(predicted) if predicted else None
    recall = matched_count / len(ground_truth) if ground_truth else None
    if precision is None or recall is None:
        f1 = None
    elif precision == 0.0 and recall == 0.0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)

    field_comparisons = [
        comparison
        for p_idx, g_idx in matches
        for comparison in (
            compare_field(
                getattr(predicted[p_idx], name),
                getattr(ground_truth[g_idx], name),
                field_path=f"line_items.{name}",
            )
            for name in _LINE_ITEM_FIELD_WEIGHTS
        )
    ]

    return LineItemMatchResult(
        predicted_count=len(predicted),
        ground_truth_count=len(ground_truth),
        matched_count=matched_count,
        precision=precision,
        recall=recall,
        f1=f1,
        field_comparisons=field_comparisons,
    )


class DocumentEvaluation(BaseModel):
    """Complete evaluation of one predicted receipt against its ground truth."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    document_field_comparisons: list[FieldComparison]
    line_items: LineItemMatchResult
    validation_issues: list[ValidationIssue]
    decision: ProcessingDecision

    @property
    def all_field_comparisons(self) -> list[FieldComparison]:
        return [*self.document_field_comparisons, *self.line_items.field_comparisons]

    @property
    def is_fully_correct(self) -> bool:
        """True when every evaluable field matched and no line item was missed or invented."""

        no_incorrect_fields = all(
            comparison.outcome is not FieldOutcome.INCORRECT
            for comparison in self.all_field_comparisons
        )
        complete_line_items = self.line_items.precision in (None, 1.0) and self.line_items.recall in (
            None,
            1.0,
        )
        return no_incorrect_fields and complete_line_items

    @property
    def has_arithmetic_issue(self) -> bool:
        return any(issue.code in ARITHMETIC_ISSUE_CODES for issue in self.validation_issues)


def evaluate_document(
    predicted: ReceiptExtraction,
    ground_truth: ReceiptExtraction,
    *,
    money_tolerance: Decimal | None = None,
    allowed_currencies: frozenset[str] | None = None,
) -> DocumentEvaluation:
    """Score one prediction against its ground truth and run validation on it.

    Validation runs on the *prediction* (what a real system would have to
    decide with, at inference time, without access to ground truth) - not on
    the ground truth itself.
    """

    kwargs: dict[str, Any] = {}
    if money_tolerance is not None:
        kwargs["money_tolerance"] = money_tolerance
    issues = validate_receipt(predicted, allowed_currencies=allowed_currencies, **kwargs)
    decision = build_processing_decision(issues)

    return DocumentEvaluation(
        document_id=ground_truth.document_id,
        document_field_comparisons=_document_field_comparisons(predicted, ground_truth),
        line_items=evaluate_line_items(predicted.line_items, ground_truth.line_items),
        validation_issues=issues,
        decision=decision,
    )


class EvaluationReport(BaseModel):
    """Aggregate metrics across a set of document evaluations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_count: int
    field_accuracy: dict[str, float]
    field_exact_match_rate: dict[str, float]
    line_item_precision: float | None
    line_item_recall: float | None
    line_item_f1: float | None
    arithmetic_consistency_rate: float
    coverage: float
    false_accept_rate: float | None


def aggregate_evaluation(evaluations: list[DocumentEvaluation]) -> EvaluationReport:
    """Combine per-document evaluations into dataset-level metrics.

    ``coverage`` is the fraction of documents the policy would auto-accept.
    ``false_accept_rate`` is the fraction of *those* auto-accepted documents
    that are not actually fully correct - the metric the project's
    precision-first policy exists to keep low (see PROJECT_BRIEF.md). It is
    ``None`` when nothing was auto-accepted, since the rate is undefined for
    zero accepted documents rather than meaningfully zero.
    """

    if not evaluations:
        raise ValueError("cannot aggregate an empty list of evaluations")

    field_accuracy = _aggregate_field_outcomes(
        evaluation.document_field_comparisons for evaluation in evaluations
    )
    field_exact_match_rate = _aggregate_exact_matches(
        evaluation.document_field_comparisons for evaluation in evaluations
    )

    line_item_precision = _mean(
        [e.line_items.precision for e in evaluations if e.line_items.precision is not None]
    )
    line_item_recall = _mean(
        [e.line_items.recall for e in evaluations if e.line_items.recall is not None]
    )
    line_item_f1 = _mean([e.line_items.f1 for e in evaluations if e.line_items.f1 is not None])

    arithmetic_consistency_rate = sum(
        1 for e in evaluations if not e.has_arithmetic_issue
    ) / len(evaluations)

    accepted = [e for e in evaluations if not e.decision.requires_review]
    coverage = len(accepted) / len(evaluations)
    false_accept_rate = (
        sum(1 for e in accepted if not e.is_fully_correct) / len(accepted) if accepted else None
    )

    return EvaluationReport(
        document_count=len(evaluations),
        field_accuracy=field_accuracy,
        field_exact_match_rate=field_exact_match_rate,
        line_item_precision=line_item_precision,
        line_item_recall=line_item_recall,
        line_item_f1=line_item_f1,
        arithmetic_consistency_rate=arithmetic_consistency_rate,
        coverage=coverage,
        false_accept_rate=false_accept_rate,
    )


def _aggregate_field_outcomes(
    comparison_lists: Any,
) -> dict[str, float]:
    correct: dict[str, int] = {}
    evaluable: dict[str, int] = {}
    for comparisons in comparison_lists:
        for comparison in comparisons:
            if comparison.outcome is FieldOutcome.NOT_EVALUABLE:
                continue
            evaluable[comparison.field_path] = evaluable.get(comparison.field_path, 0) + 1
            if comparison.outcome is FieldOutcome.CORRECT:
                correct[comparison.field_path] = correct.get(comparison.field_path, 0) + 1
    return {
        field_path: correct.get(field_path, 0) / total
        for field_path, total in evaluable.items()
    }


def _aggregate_exact_matches(comparison_lists: Any) -> dict[str, float]:
    exact: dict[str, int] = {}
    considered: dict[str, int] = {}
    for comparisons in comparison_lists:
        for comparison in comparisons:
            if comparison.exact_match is None:
                continue
            considered[comparison.field_path] = considered.get(comparison.field_path, 0) + 1
            if comparison.exact_match:
                exact[comparison.field_path] = exact.get(comparison.field_path, 0) + 1
    return {
        field_path: exact.get(field_path, 0) / total for field_path, total in considered.items()
    }


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def try_parse_extraction(raw: Mapping[str, Any]) -> ReceiptExtraction | None:
    """Attempt to parse a raw model output into the canonical schema.

    Returns ``None`` instead of raising when the payload is not schema-valid,
    so callers can compute a schema-valid rate across many raw outputs
    without a try/except at every call site. This is intentionally decoupled
    from any specific model's output format - a real extraction approach is
    expected to adapt its own raw output into this schema first (like
    :mod:`receipt_intelligence.adapters.cord` does for CORD), then hand the
    result to :func:`evaluate_document`. It exists here mainly to measure how
    often *that* adaptation step fails.
    """

    try:
        return ReceiptExtraction.model_validate(raw)
    except ValidationError:
        return None
