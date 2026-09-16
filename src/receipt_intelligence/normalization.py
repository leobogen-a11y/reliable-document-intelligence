"""Dataset-specific normalization of text, quantities, and monetary values."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation


class NormalizationError(ValueError):
    """Raised when a raw value cannot be normalized without guessing."""


_CORD_AMOUNT_PATTERN = re.compile(r"[-+]?\d[\d.,]*")
_CORD_QUANTITY_PATTERN = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def normalize_text(raw: str) -> str:
    """Collapse surrounding and repeated whitespace without changing content."""

    return " ".join(raw.split())


def parse_cord_amount(raw: str) -> Decimal:
    """Parse a CORD amount using Indonesian-rupiah dataset conventions.

    CORD monetary annotations represent whole rupiah values. Dots and commas
    therefore act as grouping separators rather than decimal separators. This
    rule is intentionally dataset-specific and must not be reused unchanged for
    European receipts.
    """

    match = _CORD_AMOUNT_PATTERN.search(raw.strip())
    if match is None:
        raise NormalizationError(f"no numeric amount found in {raw!r}")

    token = match.group(0)
    normalized = token.replace(",", "").replace(".", "")
    try:
        return Decimal(normalized)
    except InvalidOperation as exc:
        raise NormalizationError(f"invalid amount {raw!r}") from exc


def parse_cord_quantity(raw: str) -> Decimal:
    """Extract a positive quantity from common CORD forms such as `1 x` or `x2`."""

    match = _CORD_QUANTITY_PATTERN.search(raw.strip())
    if match is None:
        raise NormalizationError(f"no numeric quantity found in {raw!r}")

    token = match.group(0).replace(",", ".")
    try:
        value = Decimal(token)
    except InvalidOperation as exc:
        raise NormalizationError(f"invalid quantity {raw!r}") from exc

    if value <= 0:
        raise NormalizationError(f"quantity must be positive: {raw!r}")
    return value

