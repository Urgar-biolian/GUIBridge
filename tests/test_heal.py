import asyncio
import os
from pathlib import Path

import pytest
import yaml

from perception.cdp import elements_from_dom
from semantic.element import GUIElement, Locator
from semantic.heal import (
    HealAmbiguous,
    HealError,
    build_proposed_chain,
    extract_hints,
    match_candidates,
)
from semantic.locator_cache import LocatorCache
from semantic.resolver import IdentityMismatch, Resolver

YAML = Path(__file__).parents[1] / "packages" / "adapters" / "trae" / "locators.yaml"


def raw(tag="BUTTON", cls="", aria=None, testid=None, el_id="", rect=(0, 0, 40, 30), text=""):
    return {"tag": tag, "role": None, "aria": aria, "placeholder": None,
            "contenteditable": None, "testid": testid, "cls": cls, "id": el_id,
            "disabled": False, "rect": list(rect), "text": text}


def locator(chain):
    return {"sid": Locator("sid", "3.6.13", list(chain), "message_submitted")}


def run_heal(registry, elements, *, expected_role=None, verifier=None,
             patch_writer=None, window_checker=None):
    async def scan(window_id):
        return elements

    r = Resolver(registry, {}, scanner=scan, verifier=verifier, patch_writer=patch_writer,
                 app="trae", window_checker=window_checker)
    return asyncio.run(r.heal("w", "sid", expected_role=expected_role))


def test_extract_hints_from_mixed_chain():
    hints = extract_hints([
        {"cdp_selector": "button[aria-label='自动审批']"},
        {"cdp_selector": "[class*=permissionModeTrigger]"},
        {"cdp_selector": "[data-testid=ai-chat-create-new-session]"},
        {"uia_criteria": {"control_type": "Document", "name_contains": "上下文",
                          "automation_id": "RootWebArea"}},
        {"ocr_text": "发送"},
    ])
    assert "自动审批" in hints.texts
    assert "permissionModeTrigger" in hints.classes
    assert "ai-chat-create-new-session" in hints.testids
    assert "RootWebArea" in hints.automation_ids
    assert "上下文" in hints.texts


def test_unique_candidate_proposes_selector_and_patch(tmp_path):
    els = elements_from_dom([raw(cls="chat-input-v2-send-button-new disabled",
                                 aria="发送")], "w")
    cache = LocatorCache(str(YAML), patches_dir=str(tmp_path))
    result = run_heal(locator([{"cdp_selector": ".chat-input-v2-send-button"}]),
                      els, patch_writer=cache.propose_heal_patch)
    assert result.proposed_chain == [{"cdp_selector": "button.chat-input-v2-send-button-new"}]
    assert result.patch_path and os.path.exists(result.patch_path)
    patch = yaml.safe_load(Path(result.patch_path).read_text(encoding="utf-8"))
    assert patch["status"] == "pending"
    assert patch["semantic_id"] == "sid"
    assert patch["previous_chain"] == [{"cdp_selector": ".chat-input-v2-send-button"}]
    assert patch["proposed_chain"] == result.proposed_chain


def test_unique_candidate_does_not_mutate_registry():
    els = elements_from_dom([raw(cls="chat-input-v2-send-button-new")], "w")
    reg = locator([{"cdp_selector": ".chat-input-v2-send-button"}])
    run_heal(reg, els)
    assert reg["sid"].chain == [{"cdp_selector": ".chat-input-v2-send-button"}]


def test_ambiguous_candidates_stop_with_conflict(tmp_path):
    els = elements_from_dom([
        raw(cls="action-label-a", aria="删除", rect=(0, 0, 40, 30)),
        raw(cls="action-label-b", aria="删除", rect=(45, 0, 85, 30)),
    ], "w")
    cache = LocatorCache(str(YAML), patches_dir=str(tmp_path))
    with pytest.raises(HealAmbiguous) as ei:
        run_heal(locator([{"cdp_selector": ".action-label"}]), els,
                 patch_writer=cache.propose_heal_patch)
    assert ei.value.code == "conflict"
    assert list(tmp_path.iterdir()) == []


def test_expected_role_disambiguates():
    els = elements_from_dom([
        raw(aria="对话", cls="tab-item", rect=(0, 0, 40, 30)),
        raw(aria="对话", cls="tab-item", rect=(45, 0, 85, 30)),
    ], "w")
    els[0].role = "tab"
    els[1].role = "button"
    result = run_heal(locator([{"cdp_selector": ".tab-item"}]), els, expected_role="button")
    assert result.element.bounds == (45, 0, 85, 30)


def test_no_candidate_after_rescan():
    els = elements_from_dom([raw(cls="totally-unrelated")], "w")
    with pytest.raises(HealError) as ei:
        run_heal(locator([{"cdp_selector": ".send-btn"}]), els)
    assert not isinstance(ei.value, HealAmbiguous)


def test_verifier_rejection_writes_no_patch(tmp_path):
    els = elements_from_dom([raw(cls="send-btn-v2")], "w")

    async def reject(window_id, element):
        return False

    cache = LocatorCache(str(YAML), patches_dir=str(tmp_path))
    with pytest.raises(HealError):
        run_heal(locator([{"cdp_selector": ".send-btn"}]), els,
                 verifier=reject, patch_writer=cache.propose_heal_patch)
    assert list(tmp_path.iterdir()) == []


def test_verifier_acceptance_marks_verified():
    els = elements_from_dom([raw(cls="send-btn-v2")], "w")

    async def accept(window_id, element):
        return True

    result = run_heal(locator([{"cdp_selector": ".send-btn"}]), els, verifier=accept)
    assert result.verified is True


def test_window_identity_mismatch_blocks_heal():
    els = elements_from_dom([raw(cls="send-btn-v2")], "w")

    def checker(wid):
        raise RuntimeError("window replaced")

    with pytest.raises(IdentityMismatch):
        run_heal(locator([{"cdp_selector": ".send-btn"}]), els, window_checker=checker)


def test_unregistered_semantic_id():
    with pytest.raises(Exception) as ei:
        run_heal({}, [])
    assert getattr(ei.value, "code", "") == "locator_missing"


def test_chain_priority_testid_before_class():
    el = elements_from_dom([raw(cls="chat-input-v2-input-box-editable",
                                testid="composer-testid")], "w")[0]
    hints = extract_hints([{"cdp_selector": ".chat-input-v2-input-box-editable"}])
    assert build_proposed_chain(el, hints) == [{"cdp_selector": "[data-testid=composer-testid]"}]


def test_chain_skips_unusable_colon_id():
    el = GUIElement(id="w:cdp:0", window_id="w", role="button", name="发送",
                    bounds=(0, 0, 10, 10), source=["cdp"],
                    evidence={"cdp": {"tag": "BUTTON", "cls": "", "id": ":icube-module:",
                                      "testid": None, "disabled": False}})
    chain = build_proposed_chain(el, extract_hints([{"cdp_selector": ".x"}]))
    assert chain == [{"cdp_selector": 'button[aria-label="发送"]'}]


def test_patch_files_never_overwrite(tmp_path):
    cache = LocatorCache(str(YAML), patches_dir=str(tmp_path))
    loc = Locator("sid", "3.6.13", [{"cdp_selector": ".new"}], "v")
    p1 = cache.propose_heal_patch("trae", "3.6.13", loc, [{"cdp_selector": ".old"}])
    p2 = cache.propose_heal_patch("trae", "3.6.13", loc, [{"cdp_selector": ".old"}])
    assert p1 != p2
    assert len(list(tmp_path.iterdir())) == 2


def test_match_candidates_requires_a_hint():
    els = elements_from_dom([raw(cls="x")], "w")
    assert match_candidates(els, extract_hints([{"cdp_selector": ".other"}])) == []