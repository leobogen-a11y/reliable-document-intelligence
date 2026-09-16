"""Deterministic validation rules and the auto-accept/review policy.

These checks never invent values. A field that was not extracted is reported
as missing; it is never treated as zero or silently skipped in a sum. Only
fields with status ``extracted`` participate in arithmetic checks, because a
missing or uncertain value cannot be verified.
"""

from __future__ import annotations

from decimal import Decimal

from receipt_intelligence.domain.models import (
    ExtractedField,
    FieldStatus,
    ProcessingDecision,
    ReceiptExtraction,
    ReviewReason,
    ValidationIssue,
    ValidationSeverity,
)

# Absolute rounding tolerance applied to every money comparison below. Two
# decimal places is the common case for the currencies this project targets;
# not yet informed by real receipt data, and may need to become
# currency-aware once the baseline runs against actual receipts (see
# SCHEMA_DESIGN.md, "Noch nicht entschieden").
DEFAULT_MONEY_TOLERANCE = Decimal("0.01")

# Below this confidence, a field that a model did extract is still routed to
# review. Provisional until confidence is calibrated against real model
# output (see SCHEMA_DESIGN.md, "Noch nicht entschieden").
DEFAULT_LOW_CONFIDENCE_THRESHOLD = 0.5

_CRITICAL_FIELD_TO_REVIEW_REASON = {
    "MISSING_CRITICAL_FIELD": ReviewReason.MISSING_CRITICAL_FIELD,
    "UNREADABLE_CRITICAL_FIELD": ReviewReason.UNREADABLE_CONTENT,
    "LOW_CONFIDENCE": ReviewReason.LOW_CONFIDENCE,
    "LINE_TOTAL_MISMATCH": ReviewReason.VALIDATION_ERROR,
    "DOCUMENT_TOTAL_MISMATCH": ReviewReason.VALIDATION_ERROR,
    "UNSUPPORTED_CURRENCY": ReviewReason.VALIDATION_ERROR,
}


def validate_receipt(
    extraction: ReceiptExtraction,
    *,
    money_tolerance: Decimal = DEFAULT_MONEY_TOLERANCE,
    allowed_currencies: frozenset[str] | None = None,
    low_confidence_threshold: float = DEFAULT_LOW_CONFIDENCE_THRESHOLD,
) -> list[ValidationIssue]:
    """Run every deterministic check and return all findings.

    ``allowed_currencies`` is ``None`` by default, which skips the currency
    check entirely (useful for reference data such as CORD, where currency is
    not annotated). Pass an explicit set, e.g. ``frozenset({"EUR"})``, for a
    production deployment scoped to specific currencies.
    """

    issues: list[ValidationIssue] = []
    issues.extend(_check_critical_fields(extraction))
    issues.extend(_check_low_confidence(extraction, threshold=low_confidence_threshold))
    issues.extend(_check_line_total_consistency(extraction, tolerance=money_tolerance))
    issues.extend(_check_document_total_consistency(extraction, tolerance=money_tolerance))
    issues.extend(_check_currency_supported(extraction, allowed=allowed_currencies))
    return issues


def build_processing_decision(issues: list[ValidationIssue]) -> ProcessingDecision:
    """Turn validation findings into an auto-accept/review decision.

    Per the project's precision-first policy (PROJECT_BRIEF.md: "Im Zweifel
    wird ein Beleg nicht automatisch akzeptiert"), any issue of severity
    ``warning`` or ``error`` blocks automatic acceptance - including
    low-confidence findings, which are not errors but still not acceptable to
    wave through unreviewed. Only ``info``-severity issues (reserved for
    future informational findings; no current check produces them) never
    trigger a review on their own.
    """

    reasons = {
        _CRITICAL_FIELD_TO_REVIEW_REASON.get(issue.code, ReviewReason.VALIDATION_ERROR)
        for issue in issues
        if issue.severity is not ValidationSeverity.INFO
    }
    if not reasons:
        return ProcessingDecision(requires_review=False)
    return ProcessingDecision(
        requires_review=True,
        reasons=sorted(reasons, key=lambda reason: reason.value),
    )


def _check_critical_fields(extraction: ReceiptExtraction) -> list[ValidationIssue]:
    issues = []
    if extraction.total.status is not FieldStatus.EXTRACTED:
        issues.append(_critical_field_issue("total", extraction.total))
    if extraction.currency.status is not FieldStatus.EXTRACTED:
        issues.append(_critical_field_issue("currency", extraction.currency))
    for index, item in enumerate(extraction.line_items):
        prefix = f"line_items[{index}]"
        if item.description.status is not FieldStatus.EXTRACTED:
            issues.append(_critical_field_issue(f"{prefix}.description", item.description))
        if item.line_total.status is not FieldStatus.EXTRACTED:
            issues.append(_critical_field_issue(f"{prefix}.line_total", item.line_total))
    return issues


def _critical_field_issue(field_path: str, field: ExtractedField) -> ValidationIssue:
    if field.status is FieldStatus.UNREADABLE:
        return ValidationIssue(
            code="UNREADABLE_CRITICAL_FIELD",
            severity=ValidationSeverity.ERROR,
            field_paths=[field_path],
            message=f"{field_path} is unreadable and cannot be used for automatic acceptance",
        )
    return ValidationIssue(
        code="MISSING_CRITICAL_FIELD",
        severity=ValidationSeverity.ERROR,
        field_paths=[field_path],
        message=(
            f"{field_path} is required for automatic acceptance but was not "
            f"extracted (status={field.status.value})"
        ),
    )


def _check_low_confidence(
    extraction: ReceiptExtraction,
    *,
    threshold: float,
) -> list[ValidationIssue]:
    issues = []
    for field_path, field in _iter_all_fields(extraction):
        if field.status is FieldStatus.UNCERTAIN:
            issues.append(
                ValidationIssue(
                    code="LOW_CONFIDENCE",
                    severity=ValidationSeverity.WARNING,
                    field_paths=[field_path],
                    message=f"{field_path} was extracted but marked uncertain",
                )
            )
        elif field.status is FieldStatus.EXTRACTED and field.confidence is not None:
            if field.confidence < threshold:
                issues.append(
                    ValidationIssue(
                        code="LOW_CONFIDENCE",
                        severity=ValidationSeverity.WARNING,
                        field_paths=[field_path],
                        message=(
                            f"{field_path} has confidence {field.confidence:.2f}, "
                            f"below threshold {threshold:.2f}"
                        ),
                    )
                )
    return issues


def _iter_all_fields(extraction: ReceiptExtraction):
    yield "subtotal", extraction.subtotal
    yield "tax", extraction.tax
    yield "total", extraction.total
    yield "currency", extraction.currency
    for index, item in enumerate(extraction.line_items):
        prefix = f"line_items[{index}]"
        yield f"{prefix}.description", item.description
        yield f"{prefix}.quantity", item.quantity
        yield f"{prefix}.unit_price", item.unit_price
        yield f"{prefix}.line_total", item.line_total


def _check_line_total_consistency(
    extraction: ReceiptExtraction,
    *,
    tolerance: Decimal,
) -> list[ValidationIssue]:
    issues = []
    for index, item in enumerate(extraction.line_items):
        quantity, unit_price, line_total = item.quantity, item.unit_price, item.line_total
        if not (
            quantity.status is FieldStatus.EXTRACTED
            and unit_price.status is FieldStatus.EXTRACTED
            and line_total.status is FieldStatus.EXTRACTED
        ):
            continue

        expected = quantity.value * unit_price.value
        if abs(expected - line_total.value) > tolerance:
            prefix = f"line_items[{index}]"
            issues.append(
                ValidationIssue(
                    code="LINE_TOTAL_MISMATCH",
                    severity=ValidationSeverity.ERROR,
                    field_paths=[
                        f"{prefix}.quantity",
                        f"{prefix}.unit_price",
                        f"{prefix}.line_total",
                    ],
                    message=(
                        f"{prefix}: quantity ({quantity.value}) * unit_price "
                        f"({unit_price.value}) = {expected} does not match "
                        f"line_total ({line_total.value})"
                    ),
                )
            )
    return issues


def _check_document_total_consistency(
    extraction: ReceiptExtraction,
    *,
    tolerance: Decimal,
) -> list[ValidationIssue]:
    issues = []
    line_totals = [item.line_total for item in extraction.line_items]
    all_line_totals_extracted = bool(line_totals) and all(
        field.status is FieldStatus.EXTRACTED for field in line_totals
    )
    sum_of_line_totals = (
        sum((field.value for field in line_totals), start=Decimal("0"))
        if all_line_totals_extracted
        else None
    )
    line_total_paths = [f"line_items[{i}].line_total" for i in range(len(line_totals))]

    if (
        sum_of_line_totals is not None
        and extraction.subtotal.status is FieldStatus.EXTRACTED
        and abs(sum_of_line_totals - extraction.subtotal.value) > tolerance
    ):
        issues.append(
            ValidationIssue(
                code="DOCUMENT_TOTAL_MISMATCH",
                severity=ValidationSeverity.ERROR,
                field_paths=["subtotal", *line_total_paths],
                message=(
                    f"sum of line_total values ({sum_of_line_totals}) does not "
                    f"match subtotal ({extraction.subtotal.value})"
                ),
            )
        )

    has_subtotal_and_tax = (
        extraction.subtotal.status is FieldStatus.EXTRACTED
        and extraction.tax.status is FieldStatus.EXTRACTED
    )
    if has_subtotal_and_tax and extraction.total.status is FieldStatus.EXTRACTED:
        expected_total = extraction.subtotal.value + extraction.tax.value
        if abs(expected_total - extraction.total.value) > tolerance:
            issues.append(
                ValidationIssue(
                    code="DOCUMENT_TOTAL_MISMATCH",
                    severity=ValidationSeverity.ERROR,
                    field_paths=["subtotal", "tax", "total"],
                    message=(
                        f"subtotal ({extraction.subtotal.value}) + tax "
                        f"({extraction.tax.value}) = {expected_total} does not "
                        f"match total ({extraction.total.value})"
                    ),
                )
            )
    elif (
        not has_subtotal_and_tax
        and sum_of_line_totals is not None
        and extraction.total.status is FieldStatus.EXTRACTED
        and abs(sum_of_line_totals - extraction.total.value) > tolerance
    ):
        issues.append(
            ValidationIssue(
                code="DOCUMENT_TOTAL_MISMATCH",
                severity=ValidationSeverity.ERROR,
                field_paths=["total", *line_total_paths],
                message=(
                    f"sum of line_total values ({sum_of_line_totals}) does not "
                    f"match total ({extraction.total.value}), and no complete "
                    f"subtotal/tax breakdown is available to explain the "
                    f"difference"
                ),
            )
        )

    return issues


def _check_currency_supported(
    extraction: ReceiptExtraction,
    *,
    allowed: frozenset[str] | None,
) -> list[ValidationIssue]:
    if allowed is None:
        return []
    currency = extraction.currency
    if currency.status is not FieldStatus.EXTRACTED or currency.value in allowed:
        return []
    return [
        ValidationIssue(
            code="UNSUPPORTED_CURRENCY",
            severity=ValidationSeverity.ERROR,
            field_paths=["currency"],
            message=f"currency {currency.value!r} is not in the supported set {sorted(allowed)}",
        )
    ]
