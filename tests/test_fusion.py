import json
from pathlib import Path

from perception.cdp import elements_from_dom
from perception.fusion import fuse, iou
from perception.ocr import elements_from_ocr
from perception.uia import elements_from_uia
from semantic.element import GUIElement

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def el(role, name, bounds, source, confidence=0.9):
    return GUIElement(id=f"{source}-1", window_id="w", role=role, name=name,
                      bounds=bounds, source=[source], confidence=confidence)


def test_iou_basic():
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0


def test_ocr_label_merges_into_composer():
    dom = elements_from_dom(load("trae_dom_sample.json"), "w")
    ocr = elements_from_ocr(load("trae_ocr_sample.json"), "w")
    fused = fuse(dom + ocr)
    composer = next(f for f in fused if f["role"] == "textbox")
    assert set(composer["sources"]) == {"cdp", "ocr"}
    assert composer["name"] == "添加上下文，"
    assert composer["calibrated"] is False


def test_ocr_label_merges_into_model_select():
    fused = fuse(elements_from_dom(load("trae_dom_sample.json"), "w")
                 + elements_from_ocr(load("trae_ocr_sample.json"), "w"))
    combo = next(f for f in fused if f["role"] == "combobox")
    assert set(combo["sources"]) == {"cdp", "ocr"}
    assert combo["confidence"] > 0.9


def test_cross_channel_role_mismatch_flags_conflict():
    fused = fuse([
        el("button", "发送", (0, 0, 40, 40), "cdp"),
        el("textbox", "", (0, 0, 40, 40), "uia", 0.8),
    ])
    assert len(fused) == 2
    assert all(f["conflict"] for f in fused)
    assert "role mismatch" in fused[0]["conflict_reason"] + fused[1]["conflict_reason"]


def test_similar_sibling_delete_buttons_conflict():
    fused = fuse([
        el("button", "删除", (0, 0, 40, 30), "cdp"),
        el("button", "删除", (45, 0, 85, 30), "uia", 0.8),
    ])
    assert len(fused) == 2
    assert all(f["conflict"] for f in fused)
    assert "sibling" in fused[0]["conflict_reason"]


def test_distant_same_name_not_conflict():
    fused = fuse([
        el("button", "删除", (0, 0, 40, 30), "cdp"),
        el("button", "删除", (300, 0, 340, 30), "uia", 0.8),
    ])
    assert len(fused) == 2
    assert not any(f["conflict"] for f in fused)


def test_confidence_heuristic_capped():
    fused = fuse([
        el("button", "确定", (0, 0, 40, 30), "cdp"),
        el("button", "确定", (0, 0, 40, 30), "uia", 0.8),
        el("button", "确定", (0, 0, 40, 30), "ocr", 0.5),
    ])
    assert len(fused) == 1
    assert fused[0]["confidence"] == 0.95
    assert fused[0]["calibrated"] is False


def test_uia_fixture_roles():
    roles = {e.role for e in elements_from_uia(load("trae_uia_sample.json"), "w")}
    assert {"button", "document", "group"} <= roles