import pytest

from receipt_intelligence.ocr import lines_from_ocr_data, run_tesseract_ocr


def _ocr_data(words: list[tuple[int, int, str, int]]) -> dict[str, list]:
    """Build a minimal pytesseract.image_to_data-shaped dict from (top, left, text, conf)."""

    return {
        "top": [w[0] for w in words],
        "left": [w[1] for w in words],
        "text": [w[2] for w in words],
        "conf": [w[3] for w in words],
    }


def test_words_on_the_same_row_are_joined_left_to_right() -> None:
    # Deliberately out of order and interleaved across two visual rows, as
    # Tesseract emits when it treats description/price as separate blocks.
    data = _ocr_data(
        [
            (80, 200, "3,50", 90),
            (20, 10, "Cappuccino", 95),
            (80, 10, "Wasser", 92),
            (20, 200, "7,00", 88),
        ]
    )

    lines = lines_from_ocr_data(data, line_tolerance_px=10)

    assert [line.text for line in lines] == ["Cappuccino 7,00", "Wasser 3,50"]


def test_rows_within_tolerance_are_merged_rows_outside_are_not() -> None:
    data = _ocr_data(
        [
            (100, 10, "A", 90),
            (104, 60, "B", 90),  # within tolerance of row at top=100
            (130, 10, "C", 90),  # a separate row
        ]
    )

    lines = lines_from_ocr_data(data, line_tolerance_px=5)

    assert [line.text for line in lines] == ["A B", "C"]


def test_low_confidence_and_empty_words_are_dropped() -> None:
    data = _ocr_data(
        [
            (10, 10, "Real", 90),
            (10, 60, "   ", 90),  # blank OCR token
            (10, 90, "Word", -1),  # Tesseract uses -1 confidence for non-text regions
        ]
    )

    lines = lines_from_ocr_data(data)

    assert len(lines) == 1
    assert lines[0].text == "Real"


def test_confidence_is_averaged_over_the_line() -> None:
    data = _ocr_data([(10, 10, "A", 80), (10, 50, "B", 100)])

    lines = lines_from_ocr_data(data)

    assert lines[0].confidence == 90.0


def test_empty_input_returns_no_lines() -> None:
    assert lines_from_ocr_data(_ocr_data([])) == []


# --- integration smoke test (requires the tesseract binary) -----------------


def test_run_tesseract_ocr_reads_a_rendered_receipt(tmp_path) -> None:
    pytest.importorskip("pytesseract")
    from PIL import Image, ImageDraw, ImageFont

    font_path = "/usr/share/fonts/truetype/liberation/LiberationMono-Regular.ttf"
    pytest.importorskip("PIL")
    try:
        font = ImageFont.truetype(font_path, 28)
    except OSError:
        pytest.skip(f"test font not available at {font_path}")

    image = Image.new("RGB", (700, 200), "white")
    draw = ImageDraw.Draw(image)
    draw.text((20, 20), "Cappuccino 2 x 3,50 7,00", fill="black", font=font)
    draw.text((20, 75), "Gesamt 7,00", fill="black", font=font)

    lines = run_tesseract_ocr(image)
    texts = [line.text for line in lines]

    assert any("Cappuccino" in text for text in texts)
    assert any("Gesamt" in text and "7,00" in text for text in texts)
