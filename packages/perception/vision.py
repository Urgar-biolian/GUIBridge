"""Optional vision channel (P2): icon-level grounding only."""


class VisionChannel:
    def detect_icons(self, image_path: str) -> list[dict]:
        raise NotImplementedError("P2")