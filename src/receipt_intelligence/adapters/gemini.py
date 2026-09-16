"""Adapt Gemini's structured JSON output into the canonical receipt schema.

Gemini is asked to fill a deliberately small, flat JSON schema (see
RESPONSE_SCHEMA) whose per-field "status" values mirror FieldStatus
directly - except ``not_annotated``, which is reserved for reference-data
adapters such as :mod:`receipt_intelligence.adapters.cord` and must never
come from a live model. The prompt (PROMPT_TEMPLATE) instructs the model
never to invent a value; this adapter adds a second line of defense: if the
model claims a value exists but the text cannot be safely normalized (see
receipt_intelligence.normalization), the field is downgraded to
``uncertain`` with the raw text preserved, rather than either crashing the
whole document or silently guessing a number.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from receipt_intelligence.domain.models import (
    ExtractedField,
    FieldStatus,
    LineItem,
    ReceiptExtraction,
)
from receipt_intelligence.normalization import (
    NormalizationError,
    normalize_text,
    parse_amount,
    parse_quantity,
)

_STATUS_MAP = {
    "extracted": FieldStatus.EXTRACTED,
    "not_present": FieldStatus.NOT_PRESENT,
    "uncertain": FieldStatus.UNCERTAIN,
    "unreadable": FieldStatus.UNREADABLE,
}

_FIELD_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "value": {"type": "STRING", "nullable": True},
        "status": {"type": "STRING", "enum": list(_STATUS_MAP)},
    },
    "required": ["status"],
}

_LINE_ITEM_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "description": _FIELD_SCHEMA,
        "quantity": _FIELD_SCHEMA,
        "unit_price": _FIELD_SCHEMA,
        "line_total": _FIELD_SCHEMA,
    },
    "required": ["description", "quantity", "unit_price", "line_total"],
}

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "line_items": {"type": "ARRAY", "items": _LINE_ITEM_SCHEMA},
        "subtotal": _FIELD_SCHEMA,
        "tax": _FIELD_SCHEMA,
        "total": _FIELD_SCHEMA,
        "currency": _FIELD_SCHEMA,
    },
    "required": ["line_items", "subtotal", "tax", "total", "currency"],
}

PROMPT_TEMPLATE = """\
You are extracting structured data from a German receipt. Below is the \
receipt's OCR text, reconstructed line by line (OCR errors are possible).

For every field, set "status" to exactly one of:
- "extracted": the value is clearly visible in the text - put the value as \
plain text in "value", using a comma as the decimal separator for money \
(e.g. "7,00").
- "not_present": the receipt clearly does not have this field at all. \
Leave "value" null.
- "uncertain": something is present but you are not fully confident you \
read it correctly (e.g. OCR noise, ambiguous formatting). Put your best \
guess in "value" anyway.
- "unreadable": the relevant part of the text is too garbled to make any \
reasonable guess. Leave "value" null.

Never invent a value that is not supported by the text. If in doubt \
between "extracted" and "uncertain", prefer "uncertain".

Extract every line item (one purchased position) you can find. quantity \
and unit_price are frequently absent on real receipts - that is normal; \
mark them "not_present" rather than guessing a value.

OCR text:
{ocr_text}
"""


class GeminiAdapterError(ValueError):
    """Raised when Gemini's JSON does not match the expected response contract."""


def build_prompt(ocr_lines: list[str]) -> str:
    return PROMPT_TEMPLATE.format(ocr_text="\n".join(ocr_lines))


def adapt_gemini_response(raw: dict[str, Any], *, document_id: str) -> ReceiptExtraction:
    """Convert Gemini's raw JSON (matching RESPONSE_SCHEMA) into the canonical schema."""

    return ReceiptExtraction(
        document_id=document_id,
        line_items=[_adapt_line_item(item) for item in _require_list(raw, "line_items")],
        subtotal=_adapt_money_field(_require_dict(raw, "subtotal")),
        tax=_adapt_money_field(_require_dict(raw, "tax")),
        total=_adapt_money_field(_require_dict(raw, "total")),
        currency=_adapt_currency_field(_require_dict(raw, "currency")),
    )


def _require_dict(parent: dict[str, Any], key: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise GeminiAdapterError(f"{key} must be an object")
    return value


def _require_list(parent: dict[str, Any], key: str) -> list[Any]:
    value = parent.get(key)
    if not isinstance(value, list):
        raise GeminiAdapterError(f"{key} must be a list")
    return value


def _status_from_raw(raw_status: Any) -> FieldStatus:
    if raw_status not in _STATUS_MAP:
        raise GeminiAdapterError(f"unknown or missing status {raw_status!r}")
    return _STATUS_MAP[raw_status]


def _adapt_money_field(raw: dict[str, Any]) -> ExtractedField[Decimal]:
    status = _status_from_raw(raw.get("status"))
    raw_value = raw.get("value")

    if status in (FieldStatus.NOT_PRESENT, FieldStatus.UNREADABLE):
        return ExtractedField[Decimal](value=None, status=status)
    if not isinstance(raw_value, str) or not raw_value.strip():
        return ExtractedField[Decimal](value=None, status=FieldStatus.UNCERTAIN)

    try:
        value = parse_amount(raw_value)
    except NormalizationError:
        return ExtractedField[Decimal](value=None, raw_text=raw_value, status=FieldStatus.UNCERTAIN)

    return ExtractedField[Decimal](value=value, raw_text=raw_value, status=status)


def _adapt_quantity_field(raw: dict[str, Any]) -> ExtractedField[Decimal]:
    status = _status_from_raw(raw.get("status"))
    raw_value = raw.get("value")

    if status in (FieldStatus.NOT_PRESENT, FieldStatus.UNREADABLE):
        return ExtractedField[Decimal](value=None, status=status)
    if not isinstance(raw_value, str) or not raw_value.strip():
        return ExtractedField[Decimal](value=None, status=FieldStatus.UNCERTAIN)

    try:
        value = parse_quantity(raw_value)
    except NormalizationError:
        return ExtractedField[Decimal](value=None, raw_text=raw_value, status=FieldStatus.UNCERTAIN)

    return ExtractedField[Decimal](value=value, raw_text=raw_value, status=status)


def _adapt_text_field(raw: dict[str, Any]) -> ExtractedField[str]:
    status = _status_from_raw(raw.get("status"))
    raw_value = raw.get("value")

    if status in (FieldStatus.NOT_PRESENT, FieldStatus.UNREADABLE):
        return ExtractedField[str](value=None, status=status)

    normalized = normalize_text(raw_value) if isinstance(raw_value, str) else ""
    if not normalized:
        return ExtractedField[str](value=None, status=FieldStatus.UNCERTAIN)

    return ExtractedField[str](value=normalized, raw_text=raw_value, status=status)


def _adapt_currency_field(raw: dict[str, Any]) -> ExtractedField[str]:
    field = _adapt_text_field(raw)
    if field.status is not FieldStatus.EXTRACTED or field.value is None:
        return field

    code = field.value.strip().upper()
    if len(code) != 3 or not code.isalpha():
        # Model gave something that is not a 3-letter code (e.g. "€") -
        # downgrade rather than let ReceiptExtraction's own validator
        # reject the whole document over one malformed field.
        return ExtractedField[str](value=None, raw_text=field.raw_text, status=FieldStatus.UNCERTAIN)
    return ExtractedField[str](value=code, raw_text=field.raw_text, status=FieldStatus.EXTRACTED)


def _adapt_line_item(raw: Any) -> LineItem:
    if not isinstance(raw, dict):
        raise GeminiAdapterError("each line item must be an object")
    return LineItem(
        description=_adapt_text_field(_require_dict(raw, "description")),
        quantity=_adapt_quantity_field(_require_dict(raw, "quantity")),
        unit_price=_adapt_money_field(_require_dict(raw, "unit_price")),
        line_total=_adapt_money_field(_require_dict(raw, "line_total")),
    )
