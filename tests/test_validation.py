from decimal import Decimal

import pytest

from receipt_intelligence.domain.models import (
    ExtractedField,
    FieldStatus,
    LineItem,
    ReceiptExtraction,
    ReviewReason,
    ValidationIssue,
    ValidationSeverity,
)
from receipt_intelligence.validation import build_processing_decision, validate_receipt


def extracted(value: object, raw_text: str, *, confidence: float | None = None) -> ExtractedField:
    return ExtractedField(
        value=value, raw_text=raw_text, status=FieldStatus.EXTRACTED, confidence=confidence
    )


def not_present() -> ExtractedField:
    return ExtractedField(value=None, status=FieldStatus.NOT_PRESENT)


def unreadable() -> ExtractedField:
    return ExtractedField(value=None, status=FieldStatus.UNREADABLE)


def uncertain(raw_text: str) -> ExtractedField:
    return ExtractedField(value=None, raw_text=raw_text, status=FieldStatus.UNCERTAIN)


def line_item(
    *,
    description: ExtractedField | None = None,
    quantity: ExtractedField | None = None,
    unit_price: ExtractedField | None = None,
    line_total: ExtractedField | None = None,
) -> LineItem:
    return LineItem(
        description=description or extracted("Cappuccino", "CAPPUCCINO"),
        quantity=quantity if quantity is not None else extracted(Decimal("2"), "2 x"),
        unit_price=unit_price if unit_price is not None else extracted(Decimal("3.50"), "3,50"),
        line_total=line_total if line_total is not None else extracted(Decimal("7.00"), "7,00"),
    )


def consistent_extraction(**overrides: object) -> ReceiptExtraction:
    defaults = dict(
        document_id="receipt-001",
        line_items=[line_item()],
        subtotal=extracted(Decimal("7.00"), "Zwischensumme 7,00"),
        tax=extracted(Decimal("1.12"), "MwSt 1,12"),
        total=extracted(Decimal("8.12"), "Gesamt 8,12"),
        currency=extracted("EUR", "€"),
    )
    defaults.update(overrides)
    return ReceiptExtraction(**defaults)


# --- critical fields -------------------------------------------------------


def test_fully_consistent_receipt_has_no_issues() -> None:
    assert validate_receipt(consistent_extraction()) == []


def test_missing_line_item_description_is_flagged() -> None:
    extraction = consistent_extraction(
        line_items=[line_item(description=not_present())]
    )

    issues = validate_receipt(extraction)

    assert len(issues) == 1
    assert issues[0].code == "MISSING_CRITICAL_FIELD"
    assert issues[0].severity is ValidationSeverity.ERROR
    assert issues[0].field_paths == ["line_items[0].description"]


def test_missing_line_total_is_flagged() -> None:
    extraction = consistent_extraction(line_items=[line_item(line_total=not_present())])

    issues = validate_receipt(extraction)

    assert any(
        issue.code == "MISSING_CRITICAL_FIELD" and issue.field_paths == ["line_items[0].line_total"]
        for issue in issues
    )


def test_missing_total_is_flagged() -> None:
    extraction = consistent_extraction(total=not_present())

    issues = validate_receipt(extraction)

    assert any(
        issue.code == "MISSING_CRITICAL_FIELD" and issue.field_paths == ["total"]
        for issue in issues
    )


def test_missing_currency_is_flagged() -> None:
    extraction = consistent_extraction(currency=not_present())

    issues = validate_receipt(extraction)

    assert any(
        issue.code == "MISSING_CRITICAL_FIELD" and issue.field_paths == ["currency"]
        for issue in issues
    )


def test_unreadable_critical_field_uses_its_own_code() -> None:
    extraction = consistent_extraction(total=unreadable())

    issues = validate_receipt(extraction)

    assert any(
        issue.code == "UNREADABLE_CRITICAL_FIELD" and issue.field_paths == ["total"]
        for issue in issues
    )


def test_missing_quantity_or_unit_price_is_not_a_critical_field() -> None:
    # Optional per SCHEMA_DESIGN.md: quantity and unit_price may be absent.
    extraction = consistent_extraction(
        line_items=[line_item(quantity=not_present(), unit_price=not_present())]
    )

    issues = validate_receipt(extraction)

    assert issues == []


# --- low confidence ---------------------------------------------------------


def test_uncertain_field_is_flagged_as_low_confidence() -> None:
    extraction = consistent_extraction(total=uncertain("8,12?"))

    issues = validate_receipt(extraction)

    assert any(issue.code == "LOW_CONFIDENCE" and issue.field_paths == ["total"] for issue in issues)


def test_confidence_below_threshold_is_flagged() -> None:
    extraction = consistent_extraction(currency=extracted("EUR", "€", confidence=0.2))

    issues = validate_receipt(extraction, low_confidence_threshold=0.5)

    assert any(issue.code == "LOW_CONFIDENCE" and issue.field_paths == ["currency"] for issue in issues)


def test_confidence_at_or_above_threshold_is_not_flagged() -> None:
    extraction = consistent_extraction(currency=extracted("EUR", "€", confidence=0.5))

    issues = validate_receipt(extraction, low_confidence_threshold=0.5)

    assert issues == []


# --- line total consistency -------------------------------------------------


def test_line_total_mismatch_is_flagged() -> None:
    extraction = consistent_extraction(
        line_items=[
            line_item(
                quantity=extracted(Decimal("2"), "2 x"),
                unit_price=extracted(Decimal("3.00"), "3,00"),
                line_total=extracted(Decimal("7.00"), "7,00"),
            )
        ],
        subtotal=extracted(Decimal("7.00"), "Zwischensumme 7,00"),
    )

    issues = validate_receipt(extraction)

    mismatches = [issue for issue in issues if issue.code == "LINE_TOTAL_MISMATCH"]
    assert len(mismatches) == 1
    assert mismatches[0].field_paths == [
        "line_items[0].quantity",
        "line_items[0].unit_price",
        "line_items[0].line_total",
    ]


def test_line_total_within_tolerance_is_not_flagged() -> None:
    extraction = consistent_extraction(
        line_items=[
            line_item(
                quantity=extracted(Decimal("3"), "3 x"),
                unit_price=extracted(Decimal("3.33"), "3,33"),
                line_total=extracted(Decimal("10.00"), "10,00"),
            )
        ],
        subtotal=extracted(Decimal("10.00"), "Zwischensumme 10,00"),
        tax=not_present(),
        total=extracted(Decimal("10.00"), "Gesamt 10,00"),
    )

    issues = validate_receipt(extraction)

    assert not any(issue.code == "LINE_TOTAL_MISMATCH" for issue in issues)


def test_line_total_check_is_skipped_when_quantity_is_missing() -> None:
    extraction = consistent_extraction(
        line_items=[
            line_item(
                quantity=not_present(),
                unit_price=extracted(Decimal("3.00"), "3,00"),
                line_total=extracted(Decimal("7.00"), "7,00"),
            )
        ]
    )

    issues = validate_receipt(extraction)

    assert not any(issue.code == "LINE_TOTAL_MISMATCH" for issue in issues)


# --- document total consistency ---------------------------------------------


def test_subtotal_not_matching_line_items_is_flagged() -> None:
    extraction = consistent_extraction(subtotal=extracted(Decimal("9.00"), "Zwischensumme 9,00"))

    issues = validate_receipt(extraction)

    assert any(
        issue.code == "DOCUMENT_TOTAL_MISMATCH" and "subtotal" in issue.field_paths
        for issue in issues
    )


def test_subtotal_plus_tax_not_matching_total_is_flagged() -> None:
    extraction = consistent_extraction(total=extracted(Decimal("99.00"), "Gesamt 99,00"))

    issues = validate_receipt(extraction)

    assert any(
        issue.code == "DOCUMENT_TOTAL_MISMATCH" and issue.field_paths == ["subtotal", "tax", "total"]
        for issue in issues
    )


def test_line_items_vs_total_used_when_no_subtotal_or_tax() -> None:
    extraction = consistent_extraction(
        subtotal=not_present(),
        tax=not_present(),
        total=extracted(Decimal("99.00"), "Gesamt 99,00"),
    )

    issues = validate_receipt(extraction)

    assert any(
        issue.code == "DOCUMENT_TOTAL_MISMATCH" and "total" in issue.field_paths
        for issue in issues
    )


def test_document_total_checks_do_not_fire_on_incomplete_data() -> None:
    # One line item's total is missing, so nothing can be safely summed;
    # a naive sum would silently understate the receipt.
    extraction = consistent_extraction(
        line_items=[line_item(), line_item(line_total=not_present())],
        subtotal=not_present(),
    )

    issues = validate_receipt(extraction)

    assert not any(issue.code == "DOCUMENT_TOTAL_MISMATCH" for issue in issues)


def test_empty_line_items_do_not_trigger_document_total_checks() -> None:
    extraction = consistent_extraction(line_items=[], subtotal=not_present())

    issues = validate_receipt(extraction)

    assert not any(issue.code == "DOCUMENT_TOTAL_MISMATCH" for issue in issues)


# --- currency ----------------------------------------------------------------


def test_currency_check_is_skipped_by_default() -> None:
    extraction = consistent_extraction(currency=extracted("IDR", "Rp"))

    issues = validate_receipt(extraction)

    assert not any(issue.code == "UNSUPPORTED_CURRENCY" for issue in issues)


def test_currency_outside_allowed_set_is_flagged() -> None:
    extraction = consistent_extraction(currency=extracted("IDR", "Rp"))

    issues = validate_receipt(extraction, allowed_currencies=frozenset({"EUR"}))

    assert any(issue.code == "UNSUPPORTED_CURRENCY" for issue in issues)


def test_currency_inside_allowed_set_is_not_flagged() -> None:
    extraction = consistent_extraction(currency=extracted("EUR", "€"))

    issues = validate_receipt(extraction, allowed_currencies=frozenset({"EUR"}))

    assert not any(issue.code == "UNSUPPORTED_CURRENCY" for issue in issues)


# --- decision policy ----------------------------------------------------------


def test_no_issues_means_no_review() -> None:
    decision = build_processing_decision([])

    assert decision.requires_review is False
    assert decision.reasons == []


def test_error_issue_requires_review_with_mapped_reason() -> None:
    issues = [
        ValidationIssue(
            code="LINE_TOTAL_MISMATCH",
            severity=ValidationSeverity.ERROR,
            field_paths=["line_items[0].line_total"],
            message="mismatch",
        )
    ]

    decision = build_processing_decision(issues)

    assert decision.requires_review is True
    assert decision.reasons == [ReviewReason.VALIDATION_ERROR]


def test_low_confidence_warning_alone_still_requires_review() -> None:
    # Precision-first policy: confidence alone is not sufficient (PROJECT_BRIEF.md).
    issues = [
        ValidationIssue(
            code="LOW_CONFIDENCE",
            severity=ValidationSeverity.WARNING,
            field_paths=["total"],
            message="uncertain",
        )
    ]

    decision = build_processing_decision(issues)

    assert decision.requires_review is True
    assert decision.reasons == [ReviewReason.LOW_CONFIDENCE]


def test_info_only_issues_do_not_require_review() -> None:
    issues = [
        ValidationIssue(
            code="SOME_FUTURE_INFO_CODE",
            severity=ValidationSeverity.INFO,
            field_paths=["total"],
            message="informational only",
        )
    ]

    decision = build_processing_decision(issues)

    assert decision.requires_review is False


def test_multiple_issues_produce_deduplicated_sorted_reasons() -> None:
    issues = [
        ValidationIssue(
            code="MISSING_CRITICAL_FIELD",
            severity=ValidationSeverity.ERROR,
            field_paths=["total"],
            message="missing",
        ),
        ValidationIssue(
            code="LINE_TOTAL_MISMATCH",
            severity=ValidationSeverity.ERROR,
            field_paths=["line_items[0].line_total"],
            message="mismatch",
        ),
        ValidationIssue(
            code="DOCUMENT_TOTAL_MISMATCH",
            severity=ValidationSeverity.ERROR,
            field_paths=["total"],
            message="mismatch",
        ),
    ]

    decision = build_processing_decision(issues)

    assert decision.requires_review is True
    assert decision.reasons == sorted(
        {ReviewReason.MISSING_CRITICAL_FIELD, ReviewReason.VALIDATION_ERROR},
        key=lambda reason: reason.value,
    )


def test_end_to_end_inconsistent_receipt_requires_review() -> None:
    extraction = consistent_extraction(total=extracted(Decimal("999.00"), "Gesamt 999,00"))

    issues = validate_receipt(extraction)
    decision = build_processing_decision(issues)

    assert decision.requires_review is True
    assert ReviewReason.VALIDATION_ERROR in decision.reasons
