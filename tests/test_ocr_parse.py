import pytest

from perception.ocr import parse_rapidocr_result


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