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

_EUROPEAN_AMOUNT_PATTERN = re.compile(r"[-+]?\d[\d.,]*")
_EUROPEAN_QUANTITY_PATTERN = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


def parse_amount(raw: str) -> Decimal:
    """Parse a European-style amount, e.g. from a German receipt.

    Unlike :func:`parse_cord_amount`, a comma here is a decimal separator
    (German convention), not a thousands grouping mark. Handles the common
    cases: "7,00" -> 7.00, "1.234,56" -> 1234.56 (period as thousands
    grouping when a comma is also present), and tolerates a bare
    "1234.56" (US-style decimal point) when no comma is present.

    A lone period followed by exactly three digits ("1.234") is treated as
    a thousands grouping ("1234"), since receipts do not normally print
    amounts with three decimal places. This is a heuristic, not a
    guarantee - genuinely ambiguous input is accepted best-effort rather
    than rejected, because rejecting it outright would make the baseline
    parser drop otherwise-usable lines.
    """

    match = _EUROPEAN_AMOUNT_PATTERN.search(raw.strip())
    if match is None:
        raise NormalizationError(f"no numeric amount found in {raw!r}")

    token = match.group(0)
    negative = token.startswith("-")
    token = token.lstrip("+-")

    if "," in token and "." in token:
        if token.rindex(",") > token.rindex("."):
            token = token.replace(".", "").replace(",", ".")
        else:
            token = token.replace(",", "")
    elif "," in token:
        token = token.replace(",", ".")
    elif "." in token:
        _integer_part, _, fractional = token.rpartition(".")
        if len(fractional) == 3:
            token = token.replace(".", "")

    try:
        value = Decimal(token)
    except InvalidOperation as exc:
        raise NormalizationError(f"invalid amount {raw!r}") from exc
    return -value if negative else value


def parse_quantity(raw: str) -> Decimal:
    """Extract a positive quantity from forms such as "2 x", "x2", "1,5"."""

    match = _EUROPEAN_QUANTITY_PATTERN.search(raw.strip())
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

