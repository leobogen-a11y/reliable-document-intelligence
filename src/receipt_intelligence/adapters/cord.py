"""Translate CORD v2 ground-truth JSON into the canonical receipt schema."""

from __future__ import annotations

import json
from collections.abc import Mapping
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
    parse_cord_amount,
    parse_cord_quantity,
)


class CordAdapterError(ValueError):
    """Raised when a CORD annotation cannot be converted safely."""


def adapt_cord_ground_truth(
    ground_truth: str | Mapping[str, Any],
    *,
    document_id: str | None = None,
) -> ReceiptExtraction:
    """Convert one CORD v2 annotation into the canonical extraction format.

    The adapter only maps annotated ground truth. It does not run OCR and does
    not infer values that CORD does not annotate, such as currency.
    """

    payload = _load_payload(ground_truth)
    gt_parse = _required_mapping(payload, "gt_parse")
    meta = _optional_mapping(payload, "meta")

    resolved_document_id = document_id or _document_id_from_meta(meta)
    line_items = [
        _adapt_line_item(item, index=index)
        for index, item in enumerate(_normalize_menu(gt_parse.get("menu")))
    ]

    subtotal_data, subtotal_section_ambiguous = _optional_section(gt_parse, "sub_total")
    total_data, total_section_ambiguous = _optional_section(gt_parse, "total")

    return ReceiptExtraction(
        document_id=resolved_document_id,
        line_items=line_items,
        subtotal=(
            _not_annotated_decimal_field(subtotal_data)
            if subtotal_section_ambiguous
            else _money_field(
                subtotal_data.get("subtotal_price"),
                field_path="sub_total.subtotal_price",
            )
        ),
        tax=(
            _not_annotated_decimal_field(subtotal_data)
            if subtotal_section_ambiguous
            else _money_field(
                subtotal_data.get("tax_price"),
                field_path="sub_total.tax_price",
            )
        ),
        total=(
            _not_annotated_decimal_field(total_data)
            if total_section_ambiguous
            else _money_field(
                total_data.get("total_price"),
                field_path="total.total_price",
            )
        ),
        currency=ExtractedField[str](
            value=None,
            status=FieldStatus.NOT_ANNOTATED,
        ),
    )


def _load_payload(ground_truth: str | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(ground_truth, str):
        try:
            payload = json.loads(ground_truth)
        except json.JSONDecodeError as exc:
            raise CordAdapterError("ground_truth is not valid JSON") from exc
    elif isinstance(ground_truth, Mapping):
        payload = ground_truth
    else:
        raise CordAdapterError("ground_truth must be a JSON string or mapping")

    if not isinstance(payload, Mapping):
        raise CordAdapterError("ground_truth JSON must contain an object")
    return payload


def _required_mapping(parent: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if not isinstance(value, Mapping):
        raise CordAdapterError(f"{key} must be an object")
    return value


def _optional_mapping(parent: Mapping[str, Any], key: str) -> Mapping[str, Any]:
    value = parent.get(key)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise CordAdapterError(f"{key} must be an object when present")
    return value


def _optional_section(
    parent: Mapping[str, Any],
    key: str,
) -> tuple[Mapping[str, Any], bool]:
    """Return a section and whether its top-level annotation is ambiguous."""

    value = parent.get(key)
    if value is None:
        return {}, False
    if isinstance(value, Mapping):
        return value, False
    if isinstance(value, list) and all(isinstance(item, Mapping) for item in value):
        return {"raw_sections": value}, True
    raise CordAdapterError(f"{key} must be an object or a list of objects")


def _document_id_from_meta(meta: Mapping[str, Any]) -> str:
    split = str(meta.get("split", "unknown"))
    image_id = meta.get("image_id")
    if image_id is None:
        raise CordAdapterError("document_id is required when meta.image_id is missing")
    return f"cord-{split}-{image_id}"


def _normalize_menu(value: Any) -> list[Mapping[str, Any]]:
    if value is None:
        return []
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, list) and all(isinstance(item, Mapping) for item in value):
        return value
    raise CordAdapterError("gt_parse.menu must be an object or a list of objects")


def _adapt_line_item(item: Mapping[str, Any], *, index: int) -> LineItem:
    prefix = f"menu[{index}]"
    return LineItem(
        description=_text_field(item.get("nm")),
        quantity=_quantity_field(item.get("cnt"), field_path=f"{prefix}.cnt"),
        unit_price=_money_field(
            item.get("unitprice"),
            field_path=f"{prefix}.unitprice",
        ),
        line_total=_money_field(item.get("price"), field_path=f"{prefix}.price"),
    )


def _text_field(raw: Any) -> ExtractedField[str]:
    if raw is None:
        return ExtractedField[str](value=None, status=FieldStatus.NOT_PRESENT)

    raw_values = _string_values(raw, field_path="annotated text field")
    meaningful = [
        normalize_text(value)
        for value in raw_values
        if not _is_missing_placeholder(value)
    ]
    if not meaningful:
        return ExtractedField[str](
            value=None,
            raw_text=_joined_raw_text(raw_values),
            status=FieldStatus.NOT_PRESENT,
        )
    return ExtractedField[str](
        value=" ".join(meaningful),
        raw_text=_joined_raw_text(raw_values),
        status=FieldStatus.EXTRACTED,
    )


def _quantity_field(raw: Any, *, field_path: str) -> ExtractedField[Decimal]:
    if raw is None:
        return ExtractedField[Decimal](value=None, status=FieldStatus.NOT_PRESENT)

    raw_values = _string_values(raw, field_path=field_path)
    meaningful = [value for value in raw_values if not _is_missing_placeholder(value)]
    if not meaningful:
        return ExtractedField[Decimal](
            value=None,
            raw_text=_joined_raw_text(raw_values),
            status=FieldStatus.NOT_PRESENT,
        )

    parsed_values = []
    for candidate in meaningful:
        try:
            parsed_values.append(parse_cord_quantity(candidate))
        except NormalizationError:
            continue

    unique_values = set(parsed_values)
    if len(unique_values) != 1:
        return ExtractedField[Decimal](
            value=None,
            raw_text=_joined_raw_text(raw_values),
            status=FieldStatus.NOT_ANNOTATED,
        )
    value = unique_values.pop()

    return ExtractedField[Decimal](
        value=value,
        raw_text=_joined_raw_text(raw_values),
        status=FieldStatus.EXTRACTED,
    )


def _money_field(raw: Any, *, field_path: str) -> ExtractedField[Decimal]:
    if raw is None:
        return ExtractedField[Decimal](value=None, status=FieldStatus.NOT_PRESENT)

    raw_values = _string_values(raw, field_path=field_path)
    meaningful = [value for value in raw_values if not _is_missing_placeholder(value)]
    if not meaningful:
        return ExtractedField[Decimal](
            value=None,
            raw_text=_joined_raw_text(raw_values),
            status=FieldStatus.NOT_PRESENT,
        )

    parsed_values = []
    for candidate in meaningful:
        if "%" in candidate:
            continue
        try:
            parsed_values.append(parse_cord_amount(candidate))
        except NormalizationError:
            continue

    unique_values = set(parsed_values)
    if len(unique_values) != 1:
        return ExtractedField[Decimal](
            value=None,
            raw_text=_joined_raw_text(raw_values),
            status=FieldStatus.NOT_ANNOTATED,
        )
    value = unique_values.pop()

    return ExtractedField[Decimal](
        value=value,
        raw_text=_joined_raw_text(raw_values),
        status=FieldStatus.EXTRACTED,
    )


def _not_annotated_decimal_field(raw: Any) -> ExtractedField[Decimal]:
    return ExtractedField[Decimal](
        value=None,
        raw_text=json.dumps(raw, ensure_ascii=False, sort_keys=True),
        status=FieldStatus.NOT_ANNOTATED,
    )


def _string_values(raw: Any, *, field_path: str) -> list[str]:
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list) and all(isinstance(value, str) for value in raw):
        return raw
    raise CordAdapterError(f"{field_path} must contain a string or list of strings")


def _joined_raw_text(values: list[str]) -> str | None:
    return " | ".join(values) if values else None


def _is_missing_placeholder(raw: str) -> bool:
    return normalize_text(raw) in {"", "-"}
