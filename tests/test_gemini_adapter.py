from decimal import Decimal

import pytest

from receipt_intelligence.adapters.gemini import (
    GeminiAdapterError,
    adapt_gemini_response,
    build_prompt,
)
from receipt_intelligence.domain.models import FieldStatus


def field(status: str, value: str | None = None) -> dict:
    return {"status": status, "value": value}


def item(
    description="Cappuccino",
    quantity=("extracted", "2"),
    unit_price=("extracted", "3,50"),
    line_total=("extracted", "7,00"),
) -> dict:
    return {
        "description": field("extracted", description),
        "quantity": field(*quantity),
        "unit_price": field(*unit_price),
        "line_total": field(*line_total),
    }


def response(
    *,
    line_items: list[dict] | None = None,
    subtotal=("extracted", "7,00"),
    tax=("not_present", None),
    total=("extracted", "7,00"),
    currency=("extracted", "EUR"),
) -> dict:
    return {
        "line_items": line_items if line_items is not None else [item()],
        "subtotal": field(*subtotal),
        "tax": field(*tax),
        "total": field(*total),
        "currency": field(*currency),
    }


def test_full_valid_response_is_adapted() -> None:
    extraction = adapt_gemini_response(response(), document_id="doc-1")

    assert extraction.document_id == "doc-1"
    assert len(extraction.line_items) == 1
    li = extraction.line_items[0]
    assert li.description.value == "Cappuccino"
    assert li.quantity.value == Decimal("2")
    assert li.unit_price.value == Decimal("3.50")
    assert li.line_total.value == Decimal("7.00")
    assert extraction.subtotal.value == Decimal("7.00")
    assert extraction.tax.status is FieldStatus.NOT_PRESENT
    assert extraction.currency.value == "EUR"


def test_not_present_and_unreadable_have_no_value() -> None:
    extraction = adapt_gemini_response(
        response(tax=("not_present", None), subtotal=("unreadable", None)), document_id="doc-1"
    )

    assert extraction.tax.status is FieldStatus.NOT_PRESENT
    assert extraction.tax.value is None
    assert extraction.subtotal.status is FieldStatus.UNREADABLE
    assert extraction.subtotal.value is None


def test_extracted_with_unparseable_value_is_downgraded_to_uncertain() -> None:
    extraction = adapt_gemini_response(
        response(total=("extracted", "not a number")), document_id="doc-1"
    )

    assert extraction.total.status is FieldStatus.UNCERTAIN
    assert extraction.total.value is None
    assert extraction.total.raw_text == "not a number"


def test_extracted_with_missing_value_is_downgraded_to_uncertain() -> None:
    extraction = adapt_gemini_response(response(total=("extracted", None)), document_id="doc-1")

    assert extraction.total.status is FieldStatus.UNCERTAIN


def test_currency_symbol_instead_of_iso_code_is_downgraded() -> None:
    extraction = adapt_gemini_response(response(currency=("extracted", "€")), document_id="doc-1")

    assert extraction.currency.status is FieldStatus.UNCERTAIN
    assert extraction.currency.value is None


def test_currency_is_uppercased() -> None:
    extraction = adapt_gemini_response(response(currency=("extracted", "eur")), document_id="doc-1")

    assert extraction.currency.value == "EUR"


def test_uncertain_status_is_preserved_even_with_a_value() -> None:
    extraction = adapt_gemini_response(response(total=("uncertain", "7,00")), document_id="doc-1")

    assert extraction.total.status is FieldStatus.UNCERTAIN
    assert extraction.total.value == Decimal("7.00")


def test_line_item_without_quantity_or_unit_price_is_valid() -> None:
    li = item(quantity=("not_present", None), unit_price=("not_present", None))

    extraction = adapt_gemini_response(response(line_items=[li]), document_id="doc-1")

    item_out = extraction.line_items[0]
    assert item_out.quantity.status is FieldStatus.NOT_PRESENT
    assert item_out.unit_price.status is FieldStatus.NOT_PRESENT


def test_unknown_status_raises_adapter_error() -> None:
    payload = response(total=("made_up_status", "7,00"))

    with pytest.raises(GeminiAdapterError, match="unknown or missing status"):
        adapt_gemini_response(payload, document_id="doc-1")


def test_missing_required_key_raises_adapter_error() -> None:
    payload = response()
    del payload["currency"]

    with pytest.raises(GeminiAdapterError, match="currency"):
        adapt_gemini_response(payload, document_id="doc-1")


def test_line_items_must_be_a_list() -> None:
    payload = response()
    payload["line_items"] = "not a list"

    with pytest.raises(GeminiAdapterError, match="must be a list"):
        adapt_gemini_response(payload, document_id="doc-1")


def test_build_prompt_includes_every_ocr_line() -> None:
    prompt = build_prompt(["Cappuccino 7,00", "Gesamt 7,00"])

    assert "Cappuccino 7,00" in prompt
    assert "Gesamt 7,00" in prompt
    assert "never invent" in prompt.lower()
