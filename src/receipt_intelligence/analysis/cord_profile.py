"""Pure profiling logic for CORD v2 ground-truth annotations."""

from __future__ import annotations

import json
import math
import re
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from statistics import mean, median
from typing import Any

from receipt_intelligence.adapters.cord import CordAdapterError, adapt_cord_ground_truth
from receipt_intelligence.normalization import (
    NormalizationError,
    parse_cord_amount,
    parse_cord_quantity,
)


def profile_cord_annotations(annotations: Iterable[str]) -> dict[str, Any]:
    """Create deterministic structural statistics for CORD annotations."""

    documents = 0
    valid_json = 0
    adapter_successes = 0
    split_counts: Counter[str] = Counter()
    menu_shapes: Counter[str] = Counter()
    document_fields: Counter[str] = Counter()
    item_fields: Counter[str] = Counter()
    amount_formats: Counter[str] = Counter()
    quantity_formats: Counter[str] = Counter()
    adapter_errors: Counter[str] = Counter()
    adapter_error_examples: list[dict[str, Any]] = []
    normalization_errors: Counter[str] = Counter()
    canonical_document_statuses: defaultdict[str, Counter[str]] = defaultdict(Counter)
    canonical_item_statuses: defaultdict[str, Counter[str]] = defaultdict(Counter)
    item_counts: list[int] = []
    items_by_split: defaultdict[str, int] = defaultdict(int)

    for annotation in annotations:
        documents += 1
        try:
            payload = json.loads(annotation)
        except (json.JSONDecodeError, TypeError):
            adapter_errors["invalid_json"] += 1
            continue

        if not isinstance(payload, Mapping):
            adapter_errors["json_root_not_object"] += 1
            continue
        valid_json += 1

        meta = payload.get("meta")
        split = str(meta.get("split", "unknown")) if isinstance(meta, Mapping) else "unknown"
        split_counts[split] += 1

        gt_parse = payload.get("gt_parse")
        if not isinstance(gt_parse, Mapping):
            adapter_errors["missing_or_invalid_gt_parse"] += 1
            continue

        raw_menu = gt_parse.get("menu")
        menu_shape, items = _menu_items(raw_menu)
        menu_shapes[menu_shape] += 1
        item_counts.append(len(items))
        items_by_split[split] += len(items)

        if items:
            document_fields["line_items"] += 1

        sub_total = _mapping_or_empty(gt_parse.get("sub_total"))
        total = _mapping_or_empty(gt_parse.get("total"))

        _count_presence(document_fields, "subtotal", sub_total, "subtotal_price")
        _count_presence(document_fields, "tax", sub_total, "tax_price")
        _count_presence(document_fields, "discount", sub_total, "discount_price")
        _count_presence(document_fields, "service_charge", sub_total, "service_price")
        _count_presence(document_fields, "other_service_charge", sub_total, "othersvc_price")
        _count_presence(document_fields, "subtotal_other", sub_total, "etc")
        _count_presence(document_fields, "total", total, "total_price")

        for field_name in (
            "subtotal_price",
            "tax_price",
            "discount_price",
            "service_price",
            "othersvc_price",
        ):
            _profile_amount(sub_total.get(field_name), amount_formats, normalization_errors)
        _profile_amount(total.get("total_price"), amount_formats, normalization_errors)

        for item in items:
            for canonical_name, cord_name in (
                ("description", "nm"),
                ("quantity", "cnt"),
                ("unit_price", "unitprice"),
                ("line_total", "price"),
            ):
                _count_presence(item_fields, canonical_name, item, cord_name)

            _profile_quantity(item.get("cnt"), quantity_formats, normalization_errors)
            _profile_amount(item.get("unitprice"), amount_formats, normalization_errors)
            _profile_amount(item.get("price"), amount_formats, normalization_errors)

        try:
            extraction = adapt_cord_ground_truth(payload)
        except CordAdapterError as exc:
            adapter_errors[str(exc)] += 1
            if len(adapter_error_examples) < 50:
                adapter_error_examples.append(
                    {
                        "document_id": _source_document_id(meta),
                        "error": str(exc),
                        "context": _adapter_error_context(gt_parse),
                    }
                )
        else:
            adapter_successes += 1
            for field_name in ("subtotal", "tax", "total", "currency"):
                field = getattr(extraction, field_name)
                canonical_document_statuses[field_name][field.status.value] += 1
            for item in extraction.line_items:
                for field_name in ("description", "quantity", "unit_price", "line_total"):
                    field = getattr(item, field_name)
                    canonical_item_statuses[field_name][field.status.value] += 1

    total_items = sum(item_counts)
    return {
        "documents": {
            "total": documents,
            "valid_json": valid_json,
            "adapter_successes": adapter_successes,
            "adapter_errors": documents - adapter_successes,
            "by_split": dict(sorted(split_counts.items())),
        },
        "line_items": {
            "total": total_items,
            "by_split": dict(sorted(items_by_split.items())),
            "per_document": _distribution(item_counts),
        },
        "menu_shape": dict(sorted(menu_shapes.items())),
        "document_field_presence": _with_rates(document_fields, valid_json),
        "line_item_field_presence": _with_rates(item_fields, total_items),
        "amount_formats": dict(sorted(amount_formats.items())),
        "quantity_formats": dict(sorted(quantity_formats.items())),
        "normalization_errors": dict(normalization_errors.most_common()),
        "canonical_document_field_statuses": _nested_counters(
            canonical_document_statuses
        ),
        "canonical_line_item_field_statuses": _nested_counters(canonical_item_statuses),
        "adapter_error_details": dict(adapter_errors.most_common()),
        "adapter_error_examples": adapter_error_examples,
    }


def _menu_items(value: Any) -> tuple[str, list[Mapping[str, Any]]]:
    if value is None:
        return "missing", []
    if isinstance(value, Mapping):
        return "object", [value]
    if isinstance(value, list):
        if all(isinstance(item, Mapping) for item in value):
            return "list", value
        return "invalid_list", []
    return "invalid", []


def _mapping_or_empty(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _source_document_id(meta: Any) -> str:
    if not isinstance(meta, Mapping):
        return "cord-unknown-unknown"
    return f"cord-{meta.get('split', 'unknown')}-{meta.get('image_id', 'unknown')}"


def _adapter_error_context(gt_parse: Mapping[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    raw_menu = gt_parse.get("menu")
    _, items = _menu_items(raw_menu)

    non_string_item_fields = []
    for index, item in enumerate(items):
        for field in ("nm", "cnt", "unitprice", "price"):
            value = item.get(field)
            if value is not None and not isinstance(value, str):
                non_string_item_fields.append(
                    {"index": index, "field": field, "value": value}
                )
    if non_string_item_fields:
        context["non_string_item_fields"] = non_string_item_fields

    for section_name, fields in (
        (
            "sub_total",
            (
                "subtotal_price",
                "tax_price",
                "discount_price",
                "service_price",
                "othersvc_price",
            ),
        ),
        ("total", ("total_price",)),
    ):
        section = gt_parse.get(section_name)
        if section is not None and not isinstance(section, Mapping):
            context[section_name] = section
            continue
        if isinstance(section, Mapping):
            unusual = {
                field: section[field]
                for field in fields
                if field in section
                and (not isinstance(section[field], str) or section[field].strip() == "-")
            }
            if unusual:
                context[section_name] = unusual

    return context


def _is_present(value: Any) -> bool:
    return value is not None and value != "" and value != [] and value != {}


def _count_presence(
    counter: Counter[str],
    canonical_name: str,
    parent: Mapping[str, Any],
    source_name: str,
) -> None:
    if _is_present(parent.get(source_name)):
        counter[canonical_name] += 1


def _profile_amount(
    raw: Any,
    formats: Counter[str],
    errors: Counter[str],
) -> None:
    if not _is_present(raw):
        return
    if not isinstance(raw, str):
        errors["amount_not_string"] += 1
        return

    formats[_amount_format(raw)] += 1
    try:
        parse_cord_amount(raw)
    except NormalizationError:
        errors["amount_unparseable"] += 1


def _profile_quantity(
    raw: Any,
    formats: Counter[str],
    errors: Counter[str],
) -> None:
    if not _is_present(raw):
        return
    if not isinstance(raw, str):
        errors["quantity_not_string"] += 1
        return

    formats[_quantity_format(raw)] += 1
    try:
        parse_cord_quantity(raw)
    except NormalizationError:
        errors["quantity_unparseable"] += 1


def _amount_format(raw: str) -> str:
    has_comma = "," in raw
    has_dot = "." in raw
    if has_comma and has_dot:
        separator = "mixed_separators"
    elif has_comma:
        separator = "comma"
    elif has_dot:
        separator = "dot"
    else:
        separator = "digits_only"

    has_affix = bool(re.search(r"[^\d\s.,+-]", raw))
    return f"{separator}_{'with_affix' if has_affix else 'plain'}"


def _quantity_format(raw: str) -> str:
    compact = re.sub(r"\s+", "", raw.lower())
    if re.fullmatch(r"\d+", compact):
        return "integer"
    if re.fullmatch(r"\d+[.,]\d+", compact):
        return "decimal"
    if re.search(r"x\d", compact):
        return "x_before_number"
    if re.search(r"\d(?:[.,]\d+)?x", compact):
        return "x_after_number"
    return "other"


def _distribution(values: list[int]) -> dict[str, int | float | None]:
    if not values:
        return {"min": None, "max": None, "mean": None, "median": None, "p95": None}

    ordered = sorted(values)
    p95_index = max(0, math.ceil(0.95 * len(ordered)) - 1)
    return {
        "min": ordered[0],
        "max": ordered[-1],
        "mean": round(mean(ordered), 3),
        "median": median(ordered),
        "p95": ordered[p95_index],
    }


def _with_rates(counter: Counter[str], denominator: int) -> dict[str, dict[str, int | float]]:
    return {
        key: {
            "count": count,
            "rate": round(count / denominator, 4) if denominator else 0.0,
        }
        for key, count in sorted(counter.items())
    }


def _nested_counters(
    counters: Mapping[str, Counter[str]],
) -> dict[str, dict[str, int]]:
    return {
        field_name: dict(sorted(statuses.items()))
        for field_name, statuses in sorted(counters.items())
    }
