from decimal import Decimal

import pytest

from receipt_intelligence.normalization import (
    NormalizationError,
    normalize_text,
    parse_cord_amount,
    parse_cord_quantity,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("75,000", Decimal("75000")),
        ("43.636", Decimal("43636")),
        ("Rp 0.000", Decimal("0")),
        ("@20.000", Decimal("20000")),
        ("40,000.", Decimal("40000")),
        ("-45", Decimal("-45")),
    ],
)
def test_parse_cord_amount(raw: str, expected: Decimal) -> None:
    assert parse_cord_amount(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1", Decimal("1")),
        ("1 x", Decimal("1")),
        ("x2", Decimal("2")),
        ("1.5x", Decimal("1.5")),
    ],
)
def test_parse_cord_quantity(raw: str, expected: Decimal) -> None:
    assert parse_cord_quantity(raw) == expected


@pytest.mark.parametrize("raw", ["", "unknown", "x"])
def test_quantity_without_number_is_rejected(raw: str) -> None:
    with pytest.raises(NormalizationError, match="no numeric quantity"):
        parse_cord_quantity(raw)


@pytest.mark.parametrize("raw", ["0", "-1"])
def test_non_positive_quantity_is_rejected(raw: str) -> None:
    with pytest.raises(NormalizationError, match="must be positive"):
        parse_cord_quantity(raw)


def test_text_whitespace_is_normalized() -> None:
    assert normalize_text("  Iced   Lemon\nTea ") == "Iced Lemon Tea"

