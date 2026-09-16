from decimal import Decimal

from receipt_intelligence.baseline import extract_baseline
from receipt_intelligence.domain.models import FieldStatus
from receipt_intelligence.ocr import OcrLine


def line(text: str, confidence: float = 90.0) -> OcrLine:
    return OcrLine(text=text, confidence=confidence)


def test_full_receipt_is_parsed_end_to_end() -> None:
    lines = [
        line("CAFE MUENCHEN"),
        line("Cappuccino 2 x 3,50 7,00"),
        line("Zwischensumme 8,50"),
        line("MwSt 19% 1,62"),
        line("Gesamt 10,12"),
        line("EUR"),
    ]

    extraction = extract_baseline(lines, document_id="receipt-001")

    assert len(extraction.line_items) == 1
    item = extraction.line_items[0]
    assert item.description.value == "Cappuccino"
    assert item.quantity.value == Decimal("2")
    assert item.unit_price.value == Decimal("3.50")
    assert item.line_total.value == Decimal("7.00")

    assert extraction.subtotal.value == Decimal("8.50")
    assert extraction.tax.value == Decimal("1.62")
    assert extraction.total.value == Decimal("10.12")
    assert extraction.currency.value == "EUR"


def test_line_with_no_recognizable_amount_is_ignored() -> None:
    lines = [line("CAFE MUENCHEN"), line("Vielen Dank fuer Ihren Besuch")]

    extraction = extract_baseline(lines, document_id="receipt-001")

    assert extraction.line_items == []
    assert extraction.total.status is FieldStatus.NOT_PRESENT


def test_total_subtotal_and_tax_default_to_not_present_when_absent() -> None:
    extraction = extract_baseline([line("Cappuccino 7,00")], document_id="receipt-001")

    assert extraction.subtotal.status is FieldStatus.NOT_PRESENT
    assert extraction.tax.status is FieldStatus.NOT_PRESENT
    assert extraction.total.status is FieldStatus.NOT_PRESENT


def test_only_the_first_matching_total_line_is_used() -> None:
    lines = [line("Gesamt 10,12"), line("Gesamt 99,99")]

    extraction = extract_baseline(lines, document_id="receipt-001")

    assert extraction.total.value == Decimal("10.12")


def test_currency_symbol_is_detected() -> None:
    extraction = extract_baseline([line("Gesamt € 10,12")], document_id="receipt-001")

    assert extraction.currency.value == "EUR"


def test_currency_is_not_present_when_no_symbol_or_code_appears() -> None:
    extraction = extract_baseline([line("Gesamt 10,12")], document_id="receipt-001")

    assert extraction.currency.status is FieldStatus.NOT_PRESENT


def test_item_without_explicit_quantity_has_no_quantity_or_unit_price() -> None:
    extraction = extract_baseline([line("Croissant 2,50")], document_id="receipt-001")

    assert len(extraction.line_items) == 1
    item = extraction.line_items[0]
    assert item.description.value == "Croissant"
    assert item.quantity.status is FieldStatus.NOT_PRESENT
    assert item.unit_price.status is FieldStatus.NOT_PRESENT
    assert item.line_total.value == Decimal("2.50")


def test_known_limitation_implicit_quantity_one_absorbs_extra_number_into_description() -> None:
    # Documented limitation (see module docstring and SCHEMA_DESIGN.md
    # "Verhalten bei impliziter Menge 1"): without an explicit "x" marker,
    # a second number before the trailing amount is not recognized as a
    # separate unit price and stays attached to the description text.
    extraction = extract_baseline([line("Wasser 1,50 1,50")], document_id="receipt-001")

    assert len(extraction.line_items) == 1
    item = extraction.line_items[0]
    assert item.description.value == "Wasser 1,50"
    assert item.line_total.value == Decimal("1.50")
    assert item.quantity.status is FieldStatus.NOT_PRESENT


def test_multiple_line_items_are_all_extracted() -> None:
    lines = [
        line("Cappuccino 2 x 3,50 7,00"),
        line("Croissant 2,50"),
        line("Gesamt 9,50"),
    ]

    extraction = extract_baseline(lines, document_id="receipt-001")

    assert [item.description.value for item in extraction.line_items] == ["Cappuccino", "Croissant"]


def test_empty_input_produces_an_empty_but_valid_extraction() -> None:
    extraction = extract_baseline([], document_id="receipt-001")

    assert extraction.line_items == []
    assert extraction.total.status is FieldStatus.NOT_PRESENT
    assert extraction.document_id == "receipt-001"
