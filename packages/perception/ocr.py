"""OCR fallback channel: pixel text boxes for regions without CDP/UIA semantics."""


class OCRChannel:
    def read_text_boxes(self, image_path: str) -> list[dict]:
        raise NotImplementedError("S1")