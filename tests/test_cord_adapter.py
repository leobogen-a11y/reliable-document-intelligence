from decimal import Decimal

import pytest

from receipt_intelligence.adapters.cord import CordAdapterError, adapt_cord_ground_truth
from receipt_intelligence.domain.models import FieldStatus


def test_single_menu_object_is_normalized_to_a_list() -> None:
    ground_truth = {
        "gt_parse": {
            "menu": {
                "nm": "  Iced   Tea ",
                "cnt": "1 x",
                "unitprice": "12.000",
                "price": "12,000",
            },
            "sub_total": {
                "subtotal_price": "12.000",
                "tax_price": "1,200",
            },
            "total": {"total_price": "13.200"},
        },
        "meta": {"split": "train", "image_id": 7},
    }

    extraction = adapt_cord_ground_truth(ground_truth)

    assert extraction.document_id == "cord-train-7"
    assert len(extraction.line_items) == 1
    assert extraction.line_items[0].description.value == "Iced Tea"
    assert extraction.line_items[0].quantity.value == Decimal("1")
    assert extraction.line_items[0].unit_price.value == Decimal("12000")
    assert extraction.line_items[0].line_total.value == Decimal("12000")
    assert extraction.tax.value == Decimal("1200")
    assert extraction.total.value == Decimal("13200")


def test_multiple_items_and_missing_optional_values_are_preserved() -> None:
    ground_truth = {
        "gt_parse": {
            "menu": [
                {"nm": "Coffee", "cnt": "x2", "price": "50,000"},
                {"nm": "Water", "price": "0"},
            ],
            "total": {"total_price": "50,000"},
        },
        "meta": {"split": "validation", "image_id": 3},
    }

    extraction = adapt_cord_ground_truth(ground_truth)

    assert len(extraction.line_items) == 2
    assert extraction.line_items[0].unit_price.status is FieldStatus.NOT_PRESENT
    assert extraction.line_items[1].quantity.status is FieldStatus.NOT_PRESENT
    assert extraction.subtotal.status is FieldStatus.NOT_PRESENT
    assert extraction.tax.status is FieldStatus.NOT_PRESENT
    assert extraction.currency.status is FieldStatus.NOT_ANNOTATED


def test_json_string_input_and_explicit_document_id_are_supported() -> None:
    ground_truth = """
    {
      "gt_parse": {"menu": {"nm": "Tea", "price": "25.000"}},
      "meta": {}
    }
    """

    extraction = adapt_cord_ground_truth(ground_truth, document_id="custom-id")

    assert extraction.document_id == "custom-id"
    assert extraction.line_items[0].line_total.value == Decimal("25000")


def test_invalid_json_is_rejected_with_adapter_error() -> None:
    with pytest.raises(CordAdapterError, match="not valid JSON"):
        adapt_cord_ground_truth("{invalid")


def test_missing_gt_parse_is_rejected() -> None:
    with pytest.raises(CordAdapterError, match="gt_parse must be an object"):
        adapt_cord_ground_truth({"meta": {"image_id": 1}})


def test_invalid_menu_shape_is_rejected() -> None:
    ground_truth = {
        "gt_parse": {"menu": "not-a-list-or-object"},
        "meta": {"image_id": 1},
    }

    with pytest.raises(CordAdapterError, match="menu must be an object or a list"):
        adapt_cord_ground_truth(ground_truth)


def test_missing_meta_id_requires_explicit_document_id() -> None:
    with pytest.raises(CordAdapterError, match="document_id is required"):
        adapt_cord_ground_truth({"gt_parse": {}, "meta": {}})


def test_duplicate_equal_amounts_are_safely_collapsed() -> None:
    ground_truth = {
        "gt_parse": {
            "menu": {"nm": "Coffee", "price": "20,000"},
            "sub_total": {"subtotal_price": ["20,000", "20.000"]},
            "total": {"total_price": "20,000"},
        },
        "meta": {"image_id": 10},
    }

    extraction = adapt_cord_ground_truth(ground_truth)

    assert extraction.subtotal.value == Decimal("20000")
    assert extraction.subtotal.status is FieldStatus.EXTRACTED


def test_conflicting_amount_annotations_are_marked_not_annotated() -> None:
    ground_truth = {
        "gt_parse": {
            "menu": {"nm": "Coffee", "price": "20,000"},
            "total": {"total_price": ["20,000", "21,000"]},
        },
        "meta": {"image_id": 11},
    }

    extraction = adapt_cord_ground_truth(ground_truth)

    assert extraction.total.value is None
    assert extraction.total.status is FieldStatus.NOT_ANNOTATED


def test_dash_amount_is_treated_as_not_present() -> None:
    ground_truth = {
        "gt_parse": {
            "menu": {"nm": "Coffee", "price": "20,000"},
            "sub_total": {"tax_price": "-"},
            "total": {"total_price": "20,000"},
        },
        "meta": {"image_id": 12},
    }

    extraction = adapt_cord_ground_truth(ground_truth)

    assert extraction.tax.status is FieldStatus.NOT_PRESENT


def test_multiline_description_is_joined_without_placeholder() -> None:
    ground_truth = {
        "gt_parse": {
            "menu": {"nm": ["-", "Gyro Platter"], "price": "20,000"},
            "total": {"total_price": "20,000"},
        },
        "meta": {"image_id": 13},
    }

    extraction = adapt_cord_ground_truth(ground_truth)

    assert extraction.line_items[0].description.value == "Gyro Platter"
    assert extraction.line_items[0].description.raw_text == "- | Gyro Platter"


def test_quantity_list_uses_the_single_parseable_value() -> None:
    ground_truth = {
        "gt_parse": {
            "menu": {
                "nm": "Triple Cheese",
                "cnt": ["TRIPLE CHEESE", "1"],
                "price": "20,000",
            },
            "total": {"total_price": "20,000"},
        },
        "meta": {"image_id": 14},
    }

    extraction = adapt_cord_ground_truth(ground_truth)

    assert extraction.line_items[0].quantity.value == Decimal("1")


def test_ambiguous_subtotal_section_does_not_discard_other_fields() -> None:
    ground_truth = {
        "gt_parse": {
            "menu": {"nm": "Coffee", "price": "20,000"},
            "sub_total": [
                {"subtotal_price": "18,000", "tax_price": "2,000"},
                {"subtotal_price": "20,000"},
            ],
            "total": {"total_price": "20,000"},
        },
        "meta": {"image_id": 15},
    }

    extraction = adapt_cord_ground_truth(ground_truth)

    assert extraction.subtotal.status is FieldStatus.NOT_ANNOTATED
    assert extraction.tax.status is FieldStatus.NOT_ANNOTATED
    assert extraction.total.value == Decimal("20000")
