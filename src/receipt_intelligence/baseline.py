"""Simple OCR-plus-rules extraction baseline.

This is deliberately the "simple baseline" from PROJECT_BRIEF.md ("OCR plus
deterministische Normalisierung und Regeln"), not a sophisticated parser -
its purpose is to be a reference point that a later AI-based approach is
compared against, not to solve receipt parsing in general. It only ever
extracts what it can identify with reasonable confidence, following the
"never invent values" principle used throughout this project: no field is
guessed when the text does not clearly support it, and known limitations
below are locked in by tests rather than silently mis-parsed.

Known limitations:
- Totals/subtotal/tax must appear on the same OCR line as their keyword
  (e.g. "Gesamt 10,12"); a value printed on the following line instead is
  not picked up.
- A line item's quantity and unit price are only extracted when an
  explicit multiplication marker ("2 x 3,50") is present. A line with an
  implicit quantity of 1 (e.g. "Wasser 1,50 1,50", unit price repeated as
  the line total) is not specially handled - see SCHEMA_DESIGN.md, "Noch
  nicht entschieden: Verhalten bei impliziter Menge 1". The extra number is
  absorbed into the raw line rather than the line_total in that case (see
  tests for the exact, intentional behavior).
- Currency is only recognized from an explicit symbol or ISO code
  appearing somewhere on the receipt; it is never inferred from language
  or store location.
"""

from __future__ import annotations

import re
from decimal import Decimal

from receipt_intelligence.domain.models import ExtractedField, FieldStatus, LineItem, ReceiptExtraction
from receipt_intelligence.normalization import NormalizationError, normalize_text, parse_amount, parse_quantity
from receipt_intelligence.ocr import OcrLine

# Order matters where keywords overlap as substrings: "summe" alone would
# match inside "zwischensumme", so subtotal is always checked first (see
# extract_baseline) and the generic "summe" is deliberately left out of the
# total keywords below.
_TOTAL_KEYWORDS = ("gesamtbetrag", "endbetrag", "gesamt", "total", "zu zahlen")
_SUBTOTAL_KEYWORDS = ("zwischensumme", "subtotal", "netto")
_TAX_KEYWORDS = ("mwst", "ust", "steuer", "tax", "vat")

_CURRENCY_SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP"}
_CURRENCY_CODE_PATTERN = re.compile(r"\b(EUR|USD|GBP|CHF)\b")

_TRAILING_AMOUNT_PATTERN = re.compile(r"(-?\d[\d.,]*)\s*$")
_ITEM_WITH_QUANTITY_PATTERN = re.compile(
    r"^(?P<description>.+?)\s+"
    r"(?P<quantity>\d+(?:[.,]\d+)?)\s*[x×X]\s*(?P<unit_price>\d[\d.,]*)\s+"
    r"(?P<line_total>-?\d[\d.,]*)\s*$"
)
_ITEM_SIMPLE_PATTERN = re.compile(r"^(?P<description>.+?)\s+(?P<line_total>-?\d[\d.,]*)\s*$")


def extract_baseline(lines: list[OcrLine], *, document_id: str) -> ReceiptExtraction:
    """Parse OCR-reconstructed receipt lines into the canonical schema.

    Each line is classified in order: a document-total keyword, then
    subtotal, then tax, then (if none matched) a candidate line item.
    Lines that match none of these - store name, address, footer text - are
    ignored rather than guessed at.
    """

    subtotal = _empty_money_field()
    tax = _empty_money_field()
    total = _empty_money_field()
    line_items: list[LineItem] = []

    for ocr_line in lines:
        text = normalize_text(ocr_line.text)
        if not text:
            continue
        lower = text.lower()

        # Checked in this order because keywords can overlap as substrings
        # (e.g. "zwischensumme" contains no total keyword, but a broader
        # total keyword list could otherwise shadow it - see the keyword
        # comment above).
        if subtotal.status is FieldStatus.NOT_PRESENT and _contains_any(lower, _SUBTOTAL_KEYWORDS):
            field = _trailing_money_field(text)
            if field is not None:
                subtotal = field
                continue

        if tax.status is FieldStatus.NOT_PRESENT and _contains_any(lower, _TAX_KEYWORDS):
            field = _trailing_money_field(text)
            if field is not None:
                tax = field
                continue

        if total.status is FieldStatus.NOT_PRESENT and _contains_any(lower, _TOTAL_KEYWORDS):
            field = _trailing_money_field(text)
            if field is not None:
                total = field
                continue

        item = _try_parse_line_item(text)
        if item is not None:
            line_items.append(item)

    return ReceiptExtraction(
        document_id=document_id,
        line_items=line_items,
        subtotal=subtotal,
        tax=tax,
        total=total,
        currency=_detect_currency(lines),
    )


def _contains_any(lower_text: str, keywords: tuple[str, ...]) -> bool:
    return any(keyword in lower_text for keyword in keywords)


def _empty_money_field() -> ExtractedField[Decimal]:
    return ExtractedField[Decimal](value=None, status=FieldStatus.NOT_PRESENT)


def _trailing_money_field(text: str) -> ExtractedField[Decimal] | None:
    match = _TRAILING_AMOUNT_PATTERN.search(text)
    if match is None:
        return None
    try:
        value = parse_amount(match.group(1))
    except NormalizationError:
        return None
    return ExtractedField[Decimal](value=value, raw_text=text, status=FieldStatus.EXTRACTED)


def _try_parse_line_item(text: str) -> LineItem | None:
    match = _ITEM_WITH_QUANTITY_PATTERN.match(text)
    if match is not None:
        item = _line_item_from_quantity_match(match, text)
        if item is not None:
            return item

    match = _ITEM_SIMPLE_PATTERN.match(text)
    if match is None:
        return None
    return _line_item_from_simple_match(match, text)


def _line_item_from_quantity_match(match: re.Match[str], text: str) -> LineItem | None:
    description = match.group("description").strip()
    if not description:
        return None
    try:
        quantity = parse_quantity(match.group("quantity"))
        unit_price = parse_amount(match.group("unit_price"))
        line_total = parse_amount(match.group("line_total"))
    except NormalizationError:
        return None

    return LineItem(
        description=ExtractedField[str](value=description, raw_text=text, status=FieldStatus.EXTRACTED),
        quantity=ExtractedField[Decimal](
            value=quantity, raw_text=match.group("quantity"), status=FieldStatus.EXTRACTED
        ),
        unit_price=ExtractedField[Decimal](
            value=unit_price, raw_text=match.group("unit_price"), status=FieldStatus.EXTRACTED
        ),
        line_total=ExtractedField[Decimal](
            value=line_total, raw_text=match.group("line_total"), status=FieldStatus.EXTRACTED
        ),
    )


def _line_item_from_simple_match(match: re.Match[str], text: str) -> LineItem | None:
    description = match.group("description").strip()
    if not description:
        return None
    try:
        line_total = parse_amount(match.group("line_total"))
    except NormalizationError:
        return None

    return LineItem(
        description=ExtractedField[str](value=description, raw_text=text, status=FieldStatus.EXTRACTED),
        quantity=_empty_money_field(),
        unit_price=_empty_money_field(),
        line_total=ExtractedField[Decimal](value=line_total, raw_text=text, status=FieldStatus.EXTRACTED),
    )


def _detect_currency(lines: list[OcrLine]) -> ExtractedField[str]:
    for ocr_line in lines:
        for symbol, code in _CURRENCY_SYMBOLS.items():
            if symbol in ocr_line.text:
                return ExtractedField[str](value=code, raw_text=ocr_line.text, status=FieldStatus.EXTRACTED)

    for ocr_line in lines:
        match = _CURRENCY_CODE_PATTERN.search(ocr_line.text.upper())
        if match is not None:
            return ExtractedField[str](
                value=match.group(1), raw_text=ocr_line.text, status=FieldStatus.EXTRACTED
            )

    return ExtractedField[str](value=None, status=FieldStatus.NOT_PRESENT)
