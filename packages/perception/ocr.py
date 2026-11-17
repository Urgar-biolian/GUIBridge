"""OCR fallback channel: pixel text boxes for regions without CDP/UIA semantics."""

from __future__ import annotations

import ctypes
import ctypes.wintypes
import os
import tempfile

from semantic.element import GUIElement

CHANNEL_WEIGHT = 0.5


class OcrUnavailable(RuntimeError):
    pass


class WindowNotFound(RuntimeError):
    pass


def parse_rapidocr_result(raw) -> list[dict]:
    """RapidOCR returns [[box_points, text, score], ...]; box_points = 4 (x, y) pairs."""
    boxes = []
    for item in raw or []:
        try:
            pts, text, score = item[0], item[1], float(item[2])
        except (IndexError, TypeError, ValueError):
            continue
        if not text or not pts:
            continue
        xs = [float(p[0]) for p in pts]
        ys = [float(p[1]) for p in pts]
        boxes.append({
            "text": str(text),
            "bounds": (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))),
            "confidence": score,
        })
    return boxes


class OCRChannel:
    def __init__(self):
        self._engine = None

    def _lazy_engine(self):
        if self._engine is None:
            try:
                from rapidocr_onnxruntime import RapidOCR
            except ImportError as e:
                raise OcrUnavailable("pip install guibridge[ocr]") from e
            self._engine = RapidOCR()
        return self._engine

    def read_text_boxes(self, image_path: str) -> list[dict]:
        engine = self._lazy_engine()
        result, _ = engine(image_path)
        return parse_rapidocr_result(result)


def _window_rect(window_id: str) -> tuple[int, int, int, int]:
    hwnd = int(window_id, 16)
    rect = ctypes.wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        raise WindowNotFound(window_id)
    return rect.left, rect.top, rect.right, rect.bottom


def grab_window_png(window_id: str, out_dir: str | None = None) -> str:
    try:
        import mss
        import mss.tools
    except ImportError as e:
        raise OcrUnavailable("mss is not installed") from e
    left, top, right, bottom = _window_rect(window_id)
    out_dir = out_dir or os.path.join(tempfile.gettempdir(), "guibridge")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"win_{window_id}.png")
    with mss.mss() as sct:
        shot = sct.grab({"left": left, "top": top, "width": right - left, "height": bottom - top})
        mss.tools.to_png(shot.rgb, shot.size, output=path)
    return path


def elements_from_ocr(boxes: list[dict], window_id: str, offset: tuple[int, int] = (0, 0)) -> list[GUIElement]:
    elements = []
    for i, b in enumerate(boxes):
        x1, y1, x2, y2 = b["bounds"]
        elements.append(GUIElement(
            id=f"{window_id}:ocr:{i}",
            window_id=window_id,
            role="text",
            name=b["text"],
            bounds=(x1 - offset[0], y1 - offset[1], x2 - offset[0], y2 - offset[1]),
            actions=[],
            source=["ocr"],
            confidence=round(CHANNEL_WEIGHT * b["confidence"], 3),
            evidence={"ocr": {"text": b["text"], "score": b["confidence"]}},
        ))
    return elements