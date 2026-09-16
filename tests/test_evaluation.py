from decimal import Decimal

import pytest

from receipt_intelligence.domain.models import (
    ExtractedField,
    FieldStatus,
    LineItem,
    ReceiptExtraction,
)
from receipt_intelligence.evaluation import (
    FieldOutcome,
    aggregate_evaluation,
    compare_field,
    evaluate_document,
    evaluate_line_items,
    try_parse_extraction,
)


def extracted(value: object, raw_text: str = "") -> ExtractedField:
    return ExtractedField(value=value, raw_text=raw_text or None, status=FieldStatus.EXTRACTED)


def not_present() -> ExtractedField:
    return ExtractedField(value=None, status=FieldStatus.NOT_PRESENT)


def not_annotated() -> ExtractedField:
    return ExtractedField(value=None, status=FieldStatus.NOT_ANNOTATED)


def item(
    description: str = "Cappuccino",
    quantity: str = "2",
    unit_price: str = "3.50",
    line_total: str = "7.00",
) -> LineItem:
    return LineItem(
        description=extracted(description),
        quantity=extracted(Decimal(quantity)),
        unit_price=extracted(Decimal(unit_price)),
        line_total=extracted(Decimal(line_total)),
    )


def extraction(
    *,
    document_id: str = "receipt-001",
    line_items: list[LineItem] | None = None,
    subtotal: ExtractedField | None = None,
    tax: ExtractedField | None = None,
    total: ExtractedField | None = None,
    currency: ExtractedField | None = None,
) -> ReceiptExtraction:
    return ReceiptExtraction(
        document_id=document_id,
        line_items=line_items if line_items is not None else [item()],
        subtotal=subtotal or extracted(Decimal("7.00")),
        tax=tax or not_present(),
        total=total or extracted(Decimal("7.00")),
        currency=currency or extracted("EUR"),
    )


# --- compare_field -----------------------------------------------------------


def test_not_annotated_ground_truth_is_never_evaluable() -> None:
    comparison = compare_field(extracted("EUR"), not_annotated(), field_path="currency")

    assert comparison.outcome is FieldOutcome.NOT_EVALUABLE
    assert comparison.exact_match is None


def test_both_absent_is_correct() -> None:
    comparison = compare_field(not_present(), not_present(), field_path="tax")

    assert comparison.outcome is FieldOutcome.CORRECT
    assert comparison.exact_match is True


def test_hallucinated_value_is_incorrect() -> None:
    comparison = compare_field(extracted(Decimal("5.00")), not_present(), field_path="tax")

    assert comparison.outcome is FieldOutcome.INCORRECT


def test_missed_value_is_incorrect() -> None:
    comparison = compare_field(not_present(), extracted(Decimal("5.00")), field_path="tax")

    assert comparison.outcome is FieldOutcome.INCORRECT


def test_matching_decimal_values_are_correct() -> None:
    comparison = compare_field(
        extracted(Decimal("7.00")), extracted(Decimal("7.00")), field_path="total"
    )

    assert comparison.outcome is FieldOutcome.CORRECT
    assert comparison.exact_match is True


def test_mismatching_decimal_values_are_incorrect() -> None:
    comparison = compare_field(
        extracted(Decimal("7.00")), extracted(Decimal("7.01")), field_path="total"
    )

    assert comparison.outcome is FieldOutcome.INCORRECT
    assert comparison.exact_match is False


def test_text_fields_match_case_and_whitespace_insensitively() -> None:
    comparison = compare_field(
        extracted("  cappuccino "), extracted("CAPPUCCINO"), field_path="description"
    )

    assert comparison.outcome is FieldOutcome.CORRECT
    assert comparison.exact_match is False


def test_text_fields_exact_match_when_identical() -> None:
    comparison = compare_field(extracted("Cappuccino"), extracted("Cappuccino"), field_path="description")

    assert comparison.outcome is FieldOutcome.CORRECT
    assert comparison.exact_match is True


# --- line item matching --------------------------------------------------------


def test_identical_line_items_match_perfectly() -> None:
    result = evaluate_line_items([item()], [item()])

    assert result.matched_count == 1
    assert result.precision == 1.0
    assert result.recall == 1.0
    assert result.f1 == 1.0


def test_extra_predicted_item_lowers_precision_not_recall() -> None:
    result = evaluate_line_items([item(), item("Water", line_total="1.50")], [item()])

    assert result.matched_count == 1
    assert result.precision == 0.5
    assert result.recall == 1.0


def test_missed_ground_truth_item_lowers_recall_not_precision() -> None:
    result = evaluate_line_items([item()], [item(), item("Water", line_total="1.50")])

    assert result.matched_count == 1
    assert result.precision == 1.0
    assert result.recall == 0.5


def test_no_predicted_and_no_ground_truth_items_is_undefined() -> None:
    result = evaluate_line_items([], [])

    assert result.precision is None
    assert result.recall is None
    assert result.f1 is None


def test_completely_unrelated_items_are_not_matched() -> None:
    predicted = [item("Sandwich", quantity="1", unit_price="4.00", line_total="4.00")]
    ground_truth = [item("Cappuccino", quantity="2", unit_price="3.50", line_total="7.00")]

    result = evaluate_line_items(predicted, ground_truth)

    assert result.matched_count == 0
    assert result.precision == 0.0
    assert result.recall == 0.0
    assert result.f1 == 0.0


def test_matched_items_expose_field_level_comparisons() -> None:
    predicted = [item(unit_price="3.00")]  # description, quantity, line_total identical
    ground_truth = [item()]

    result = evaluate_line_items(predicted, ground_truth)

    outcomes = {c.field_path: c.outcome for c in result.field_comparisons}
    # matched despite the unit_price mismatch: description + line_total already
    # outweigh a lost unit_price point
    assert result.matched_count == 1
    assert outcomes["line_items.unit_price"] is FieldOutcome.INCORRECT
    assert outcomes["line_items.description"] is FieldOutcome.CORRECT


# --- evaluate_document / aggregate_evaluation ------------------------------------


def test_evaluate_document_against_itself_is_fully_correct() -> None:
    receipt = extraction()

    result = evaluate_document(receipt, receipt)

    assert result.is_fully_correct is True
    assert result.has_arithmetic_issue is False


def test_evaluate_document_flags_hallucinated_total() -> None:
    ground_truth = extraction()
    predicted = extraction(total=extracted(Decimal("999.00")))

    result = evaluate_document(predicted, ground_truth)

    assert result.is_fully_correct is False
    assert result.decision.requires_review is True


def test_aggregate_evaluation_rejects_empty_input() -> None:
    with pytest.raises(ValueError, match="empty"):
        aggregate_evaluation([])


def test_aggregate_evaluation_over_identical_documents_is_perfect() -> None:
    receipt = extraction()
    evaluations = [evaluate_document(receipt, receipt) for _ in range(3)]

    report = aggregate_evaluation(evaluations)

    assert report.document_count == 3
    assert report.line_item_precision == 1.0
    assert report.line_item_recall == 1.0
    assert report.arithmetic_consistency_rate == 1.0
    assert all(rate == 1.0 for rate in report.field_accuracy.values())


def test_coverage_and_false_accept_rate_reflect_the_review_policy() -> None:
    correct_receipt = extraction()
    wrong_prediction = extraction(total=extracted(Decimal("999.00")))
    # correct_receipt validates cleanly and is auto-accepted (coverage);
    # wrong_prediction disagrees with its own arithmetic, so it is *correctly*
    # sent to review, not auto-accepted - it must not count as a false accept.
    evaluations = [
        evaluate_document(correct_receipt, correct_receipt),
        evaluate_document(wrong_prediction, correct_receipt),
    ]

    report = aggregate_evaluation(evaluations)

    assert report.coverage == 0.5
    assert report.false_accept_rate == 0.0


def test_false_accept_rate_is_none_when_nothing_is_accepted() -> None:
    ground_truth = extraction()
    predicted = extraction(total=not_present())  # missing critical field -> always reviewed

    report = aggregate_evaluation([evaluate_document(predicted, ground_truth)])

    assert report.coverage == 0.0
    assert report.false_accept_rate is None


def test_currency_not_annotated_ground_truth_is_excluded_from_field_accuracy() -> None:
    ground_truth = extraction(currency=not_annotated())
    predicted = extraction(currency=extracted("EUR"))

    report = aggregate_evaluation([evaluate_document(predicted, ground_truth)])

    assert "currency" not in report.field_accuracy


# --- try_parse_extraction --------------------------------------------------------


def test_try_parse_extraction_returns_model_for_valid_payload() -> None:
    payload = extraction().model_dump(mode="json")

    result = try_parse_extraction(payload)

    assert result is not None
    assert result.document_id == "receipt-001"


def test_try_parse_extraction_returns_none_for_invalid_payload() -> None:
    result = try_parse_extraction({"document_id": "x", "currency": {"status": "not_a_real_status"}})

    assert result is None
