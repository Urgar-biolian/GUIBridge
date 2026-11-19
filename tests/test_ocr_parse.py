import pytest

from perception.ocr import CHANNEL_WEIGHT, elements_from_ocr, parse_rapidocr_result


def test_parse_rapidocr_output():
    raw = [
        [[[10, 20], [80, 20], [80, 40], [10, 40]], "发送", 0.91],
        [[[0, 0], [50, 0], [50, 12], [0, 12]], "Agent", 0.88],
    ]
    boxes = parse_rapidocr_result(raw)
    assert boxes[0]["text"] == "发送"
    assert boxes[0]["bounds"] == (10, 20, 80, 40)
    assert boxes[0]["confidence"] == pytest.approx(0.91)


def test_parse_skips_malformed_and_empty_text():
    raw = [
        ["bad"],
        [[[0, 0], [1, 0], [1, 1], [0, 1]], "", 0.9],
        [[[0, 0], [10, 0], [10, 10], [0, 10]], "ok", 0.8],
    ]
    boxes = parse_rapidocr_result(raw)
    assert [b["text"] for b in boxes] == ["ok"]


def test_parse_empty_input():
    assert parse_rapidocr_result(None) == []


def test_elements_from_ocr_are_locate_only():
    """Principle 3: OCR yields locate-only elements with NO executable actions,
    so it can never become a background input/execution channel."""
    boxes = [
        {"text": "Run action", "bounds": (20, 50, 170, 86), "confidence": 0.9},
        {"text": "initial", "bounds": (28, 106, 80, 124), "confidence": 0.8},
    ]
    elements = elements_from_ocr(boxes, "1a2b")
    assert len(elements) == 2
    for e in elements:
        assert e.actions == []
        assert e.role == "text"
        assert e.source == ["ocr"]
    assert elements[0].name == "Run action"
    assert elements[0].id == "1a2b:ocr:0"


def test_elements_from_ocr_applies_offset_and_weight():
    boxes = [{"text": "x", "bounds": (20, 50, 170, 86), "confidence": 0.9}]
    e = elements_from_ocr(boxes, "w", offset=(10, 5))[0]
    assert e.bounds == (10, 45, 160, 81)
    assert e.confidence == round(CHANNEL_WEIGHT * 0.9, 3)


def test_elements_from_ocr_empty():
    assert elements_from_ocr([], "w") == []