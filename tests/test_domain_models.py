from decimal import Decimal

import pytest
from pydantic import ValidationError

from receipt_intelligence.domain.models import (
    BoundingBox,
    ExtractedField,
    FieldStatus,
    LineItem,
    ProcessingDecision,
    ReceiptExtraction,
    ReceiptResult,
    ReviewReason,
)


def extracted(value: object, raw_text: str) -> ExtractedField[object]:
    return ExtractedField(value=value, raw_text=raw_text, status=FieldStatus.EXTRACTED)


def not_present() -> ExtractedField[object]:
    return ExtractedField(value=None, status=FieldStatus.NOT_PRESENT)


def valid_extraction() -> ReceiptExtraction:
    return ReceiptExtraction(
        document_id="receipt-001",
        line_items=[
            LineItem(
                description=extracted("Cappuccino", "CAPPUCCINO"),
                quantity=extracted(Decimal("2"), "2 x"),
                unit_price=extracted(Decimal("3.50"), "3,50"),
                line_total=extracted(Decimal("7.00"), "7,00"),
            )
        ],
        subtotal=extracted(Decimal("7.00"), "Zwischensumme 7,00"),
        tax=extracted(Decimal("1.12"), "MwSt 1,12"),
        total=extracted(Decimal("8.12"), "Gesamt 8,12"),
        currency=extracted("EUR", "€"),
    )


def test_valid_result_serializes_money_as_decimal_strings() -> None:
    result = ReceiptResult(
        extraction=valid_extraction(),
        decision=ProcessingDecision(requires_review=False),
    )

    payload = result.model_dump(mode="json")

    assert payload["extraction"]["line_items"][0]["unit_price"]["value"] == "3.50"
    assert payload["extraction"]["total"]["value"] == "8.12"


def test_optional_receipt_fields_have_an_explicit_state() -> None:
    payload = valid_extraction().model_dump()
    payload["tax"] = not_present().model_dump()
    payload["subtotal"] = not_present().model_dump()

    extraction = ReceiptExtraction.model_validate(payload)

    assert extraction.tax.value is None
    assert extraction.tax.status is FieldStatus.NOT_PRESENT


def test_extracted_field_requires_a_value() -> None:
    with pytest.raises(ValidationError, match="must contain a value"):
        ExtractedField(value=None, status=FieldStatus.EXTRACTED)


def test_not_present_field_rejects_a_value() -> None:
    with pytest.raises(ValidationError, match="cannot contain a value"):
        ExtractedField(value="invented", status=FieldStatus.NOT_PRESENT)


def test_not_annotated_field_rejects_a_value() -> None:
    with pytest.raises(ValidationError, match="cannot contain a value"):
        ExtractedField(value="IDR", status=FieldStatus.NOT_ANNOTATED)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_confidence_must_be_between_zero_and_one(confidence: float) -> None:
    with pytest.raises(ValidationError):
        ExtractedField(value="value", status=FieldStatus.EXTRACTED, confidence=confidence)


def test_currency_must_be_an_uppercase_iso_code() -> None:
    payload = valid_extraction().model_dump()
    payload["currency"] = extracted("eur", "€").model_dump()

    with pytest.raises(ValidationError, match="uppercase"):
        ReceiptExtraction.model_validate(payload)


def test_review_decision_requires_a_reason() -> None:
    with pytest.raises(ValidationError, match="at least one reason"):
        ProcessingDecision(requires_review=True)


def test_accepted_receipt_rejects_review_reasons() -> None:
    with pytest.raises(ValidationError, match="cannot contain review reasons"):
        ProcessingDecision(
            requires_review=False,
            reasons=[ReviewReason.VALIDATION_ERROR],
        )


def test_bounding_box_rejects_invalid_geometry() -> None:
    with pytest.raises(ValidationError, match="right must be greater than left"):
        BoundingBox(left=10, top=5, right=10, bottom=20)


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        ProcessingDecision(requires_review=False, unexpected=True)
