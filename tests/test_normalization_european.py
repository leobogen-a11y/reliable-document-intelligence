from decimal import Decimal

import pytest

from receipt_intelligence.normalization import (
    NormalizationError,
    parse_amount,
    parse_quantity,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("7,00", Decimal("7.00")),
        ("7", Decimal("7")),
        ("1.234,56", Decimal("1234.56")),
        ("1234.56", Decimal("1234.56")),
        ("1.234", Decimal("1234")),  # thousands grouping, not 1.234
        ("-45,50", Decimal("-45.50")),
        ("€ 8,50", Decimal("8.50")),
        ("19%", Decimal("19")),
    ],
)
def test_parse_amount(raw: str, expected: Decimal) -> None:
    assert parse_amount(raw) == expected


def test_parse_amount_without_number_is_rejected() -> None:
    with pytest.raises(NormalizationError, match="no numeric amount"):
        parse_amount("EUR")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2", Decimal("2")),
        ("2 x", Decimal("2")),
        ("x3", Decimal("3")),
        ("1,5", Decimal("1.5")),
    ],
)
def test_parse_quantity(raw: str, expected: Decimal) -> None:
    assert parse_quantity(raw) == expected


def test_parse_quantity_rejects_non_positive() -> None:
    with pytest.raises(NormalizationError, match="must be positive"):
        parse_quantity("0")
