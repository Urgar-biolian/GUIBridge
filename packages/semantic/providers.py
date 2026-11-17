"""Element providers used by the semantic resolver: one implementation per locator strategy kind."""

from __future__ import annotations

import asyncio

from perception.cdp import CDPChannel, elements_from_dom
from perception.ocr import OCRChannel, elements_from_ocr, grab_window_png
from perception.uia import UIAChannel, elements_from_uia
from semantic.element import GUIElement


class CDPSelectorProvider:
    kind = "cdp_selector"

    def __init__(self, channel: CDPChannel, session_id: str | None = None):
        self.channel = channel
        self.session_id = session_id

    async def find(self, window_id: str, spec: dict) -> list[GUIElement]:
        raw = await self.channel.query_selector(spec["cdp_selector"], self.session_id)
        if raw is None:
            return []
        return elements_from_dom([raw], window_id)

    async def scan(self, window_id: str) -> list[GUIElement]:
        raws = await self.channel.scan_elements(self.session_id)
        return elements_from_dom(raws, window_id)


class UIACriteriaProvider:
    kind = "uia_criteria"

    def __init__(self, channel: UIAChannel):
        self.channel = channel

    async def find(self, window_id: str, spec: dict) -> list[GUIElement]:
        nodes = await asyncio.to_thread(self.channel.inspect_window, window_id)
        wanted = spec.get("control_type", "")
        if wanted and not wanted.endswith("Control"):
            wanted += "Control"
        name_part = spec.get("name_contains", "")
        automation_id = spec.get("automation_id", "")
        matched = [
            n for n in nodes
            if (not wanted or n.get("control_type") == wanted)
            and (not name_part or name_part in n.get("name", ""))
            and (not automation_id or n.get("automation_id") == automation_id)
        ]
        return elements_from_uia(matched, window_id)


class OCRTextProvider:
    kind = "ocr_text"

    def __init__(self, channel: OCRChannel):
        self.channel = channel

    async def find(self, window_id: str, spec: dict) -> list[GUIElement]:
        image = await asyncio.to_thread(grab_window_png, window_id)
        boxes = await asyncio.to_thread(self.channel.read_text_boxes, image)
        wanted = spec.get("ocr_text", "")
        matched = [b for b in boxes if wanted in b["text"]] if wanted else boxes
        return elements_from_ocr(matched, window_id)