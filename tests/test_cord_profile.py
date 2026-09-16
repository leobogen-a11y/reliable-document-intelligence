import json

from receipt_intelligence.analysis import profile_cord_annotations


def annotation(payload: dict) -> str:
    return json.dumps(payload)


def test_profile_counts_fields_shapes_and_splits() -> None:
    annotations = [
        annotation(
            {
                "gt_parse": {
                    "menu": {
                        "nm": "Coffee",
                        "cnt": "1 x",
                        "unitprice": "25.000",
                        "price": "25,000",
                    },
                    "sub_total": {"subtotal_price": "25,000"},
                    "total": {"total_price": "25,000"},
                },
                "meta": {"split": "train", "image_id": 1},
            }
        ),
        annotation(
            {
                "gt_parse": {
                    "menu": [
                        {"nm": "Tea", "cnt": "x2", "price": "20.000"},
                        {"nm": "Water", "price": "0"},
                    ],
                    "sub_total": {"tax_price": "Rp 2.000"},
                    "total": {"total_price": "22.000"},
                },
                "meta": {"split": "test", "image_id": 2},
            }
        ),
    ]

    profile = profile_cord_annotations(annotations)

    assert profile["documents"] == {
        "total": 2,
        "valid_json": 2,
        "adapter_successes": 2,
        "adapter_errors": 0,
        "by_split": {"test": 1, "train": 1},
    }
    assert profile["line_items"]["total"] == 3
    assert profile["menu_shape"] == {"list": 1, "object": 1}
    assert profile["document_field_presence"]["tax"] == {"count": 1, "rate": 0.5}
    assert profile["line_item_field_presence"]["unit_price"] == {
        "count": 1,
        "rate": 0.3333,
    }
    assert profile["quantity_formats"] == {
        "x_after_number": 1,
        "x_before_number": 1,
    }
    assert profile["canonical_document_field_statuses"]["currency"] == {
        "not_annotated": 2
    }
    assert profile["canonical_line_item_field_statuses"]["unit_price"] == {
        "extracted": 1,
        "not_present": 2,
    }


def test_profile_records_invalid_json_without_crashing() -> None:
    profile = profile_cord_annotations(["{invalid"])

    assert profile["documents"]["total"] == 1
    assert profile["documents"]["valid_json"] == 0
    assert profile["documents"]["adapter_errors"] == 1
    assert profile["adapter_error_details"] == {"invalid_json": 1}
    assert profile["adapter_error_examples"] == []
