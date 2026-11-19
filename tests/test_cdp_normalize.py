import json
from pathlib import Path

from perception.cdp import elements_from_dom, normalize_dom_role

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text(encoding="utf-8"))


def by_class(elements, fragment):
    return next(e for e in elements if fragment in str(e.evidence["cdp"].get("cls", "")))


def test_composer_maps_to_textbox_with_type_action():
    els = elements_from_dom(load("trae_dom_sample.json"), "w")
    composer = by_class(els, "chat-input-v2-input-box-editable")
    assert composer.role == "textbox"
    assert "type" in composer.actions
    assert composer.window_id == "w"


def test_send_button_disabled_state_in_evidence():
    els = elements_from_dom(load("trae_dom_sample.json"), "w")
    send = by_class(els, "chat-input-v2-send-button")
    assert send.evidence["cdp"]["disabled"] is True
    assert send.bounds == (595, 852, 619, 876)


def test_role_attribute_wins_over_tag():
    els = elements_from_dom(load("trae_dom_sample.json"), "w")
    combo = by_class(els, "icd-model-select-trigger")
    assert combo.role == "combobox"
    assert "select" in combo.actions


def test_name_priority_aria_then_text():
    els = elements_from_dom(load("trae_dom_sample.json"), "w")
    approval = by_class(els, "permissionModeTrigger")
    assert approval.name == "自动审批"
    combo = by_class(els, "icd-model-select-trigger")
    assert combo.name == "deepseek-flash"


def test_testid_preserved():
    els = elements_from_dom(load("trae_dom_sample.json"), "w")
    new_session = next(e for e in els if e.evidence["cdp"].get("testid") == "ai-chat-create-new-session")
    assert new_session.role == "button"


def test_normalize_dom_role_fallbacks():
    assert normalize_dom_role({"tag": "BUTTON"}) == "button"
    assert normalize_dom_role({"tag": "DIV", "contenteditable": "true"}) == "textbox"
    assert normalize_dom_role({"tag": "DIV", "role": "combobox"}) == "combobox"