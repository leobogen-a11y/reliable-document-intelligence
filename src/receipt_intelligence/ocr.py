"""Tesseract OCR wrapper that reconstructs left-to-right reading order.

Tesseract's own page segmentation frequently treats a receipt's price
column as a separate text block from its description column: naive
``image_to_string`` output interleaves the columns instead of reading each
printed line left-to-right (verified against a rendered two-column receipt
during development). This module instead groups recognized words by their
vertical position and sorts each group left-to-right, which is the layout
:mod:`receipt_intelligence.baseline` expects.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

# Words are grouped onto the same output line when their vertical positions
# (in pixels) differ by no more than this. Not yet tuned against real
# photographed receipts - revisit once the baseline runs against actual
# images rather than rendered test fixtures.
DEFAULT_LINE_GROUPING_TOLERANCE_PX = 10


class OcrLine(BaseModel):
    """One reconstructed line of OCR text with its average word confidence."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    text: str
    confidence: float  # Tesseract's native 0-100 scale, averaged over the line's words


def run_tesseract_ocr(
    image: Path | str | Any,
    *,
    line_tolerance_px: int = DEFAULT_LINE_GROUPING_TOLERANCE_PX,
) -> list[OcrLine]:
    """Run Tesseract on an image and return its text as reading-ordered lines.

    ``image`` is anything ``pytesseract`` accepts (a file path or a
    ``PIL.Image``). Requires the ``tesseract`` binary to be installed on the
    system; the ``pytesseract``/``pillow`` Python packages alone are not
    sufficient.
    """

    import pytesseract
    from pytesseract import Output

    data = pytesseract.image_to_data(image, output_type=Output.DICT)
    return lines_from_ocr_data(data, line_tolerance_px=line_tolerance_px)


def lines_from_ocr_data(
    data: Mapping[str, list[Any]],
    *,
    line_tolerance_px: int = DEFAULT_LINE_GROUPING_TOLERANCE_PX,
) -> list[OcrLine]:
    """Reconstruct reading-ordered lines from raw ``pytesseract.image_to_data`` output.

    Separated from :func:`run_tesseract_ocr` so the grouping logic can be
    tested with a hand-built ``data`` mapping, independent of whether
    Tesseract is installed or how accurately it reads a given image.
    """

    word_count = len(data["text"])
    words = [
        (data["top"][i], data["left"][i], data["text"][i].strip(), float(data["conf"][i]))
        for i in range(word_count)
        if data["text"][i].strip() and float(data["conf"][i]) >= 0
    ]
    words.sort(key=lambda word: (word[0], word[1]))

    bins: list[dict[str, Any]] = []
    for top, left, text, confidence in words:
        target = next(
            (b for b in bins if abs(b["top"] - top) <= line_tolerance_px),
            None,
        )
        if target is None:
            target = {"top": top, "words": []}
            bins.append(target)
        target["words"].append((left, text, confidence))

    bins.sort(key=lambda b: b["top"])

    lines = []
    for group in bins:
        ordered_words = sorted(group["words"], key=lambda word: word[0])
        text = " ".join(word[1] for word in ordered_words)
        confidence = sum(word[2] for word in ordered_words) / len(ordered_words)
        lines.append(OcrLine(text=text, confidence=confidence))
    return lines
