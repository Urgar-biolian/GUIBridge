"""Heal proposal -> store.heal_patches registration (S4-a integration for REST review).

Real Resolver/heal/LocatorCache/EventStore; only the DOM scan is faked. Locks that a
unique verified heal produces BOTH an audit file and a pending store row keyed by the
same patch_id, that ambiguity/verifier-rejection produce NEITHER, and that the store
row is reviewable through the same path desktop-agent's heal-review endpoint uses."""

import asyncio
from pathlib import Path

import pytest
import yaml

from events.store import EventStore
from perception.cdp import elements_from_dom
from semantic.element import Locator
from semantic.heal import HealAmbiguous, HealError
from semantic.heal_store import recording_patch_writer
from semantic.locator_cache import LocatorCache
from semantic.resolver import Resolver

YAML = Path(__file__).parents[1] / "packages" / "adapters" / "trae" / "locators.yaml"


def raw(cls="", aria=None, rect=(0, 0, 40, 30)):
    return {"tag": "BUTTON", "role": None, "aria": aria, "placeholder": None,
            "contenteditable": None, "testid": None, "cls": cls, "id": "",
            "disabled": False, "rect": list(rect), "text": ""}


def _heal(registry, elements, cache, store, *, verifier=None):
    async def scan(window_id):
        return elements

    r = Resolver(registry, {}, scanner=scan, verifier=verifier,
                 patch_writer=recording_patch_writer(cache, store), app="trae")
    return asyncio.run(r.heal("w", "sid"))


@pytest.fixture()
def store(tmp_path):
    s = EventStore(str(tmp_path / "heal.db"))
    yield s
    s.close()


def test_unique_heal_registers_pending_store_row(tmp_path, store):
    els = elements_from_dom([raw(cls="chat-input-v2-send-button-new", aria="发送")], "w")
    cache = LocatorCache(str(YAML), patches_dir=str(tmp_path / "patches"))
    reg = {"sid": Locator("sid", "3.6.13", [{"cdp_selector": ".chat-input-v2-send-button"}],
                          "message_submitted")}
    result = _heal(reg, els, cache, store)

    rows = store.list_heal_patches("pending")
    assert len(rows) == 1
    row = rows[0]
    assert row["patch_id"] == Path(result.patch_path).stem
    assert row["semantic_id"] == "sid"
    assert row["app"] == "trae" and row["app_version"] == "3.6.13"
    assert row["proposed_chain"] == result.proposed_chain
    assert Path(result.patch_path).exists()
    assert reg["sid"].chain == [{"cdp_selector": ".chat-input-v2-send-button"}]


def test_ambiguous_heal_writes_no_file_and_no_store_row(tmp_path, store):
    els = elements_from_dom([
        raw(cls="action-label-a", aria="删除", rect=(0, 0, 40, 30)),
        raw(cls="action-label-b", aria="删除", rect=(45, 0, 85, 30)),
    ], "w")
    patches = tmp_path / "patches"
    cache = LocatorCache(str(YAML), patches_dir=str(patches))
    reg = {"sid": Locator("sid", "3.6.13", [{"cdp_selector": ".action-label"}], "")}
    with pytest.raises(HealAmbiguous) as ei:
        _heal(reg, els, cache, store)
    assert ei.value.code == "conflict"
    assert store.list_heal_patches() == []
    assert not patches.exists() or list(patches.iterdir()) == []


def test_verifier_rejection_writes_no_file_and_no_store_row(tmp_path, store):
    els = elements_from_dom([raw(cls="send-btn-v2")], "w")
    patches = tmp_path / "patches"
    cache = LocatorCache(str(YAML), patches_dir=str(patches))

    async def reject(window_id, element):
        return False

    reg = {"sid": Locator("sid", "3.6.13", [{"cdp_selector": ".send-btn"}], "")}
    with pytest.raises(HealError):
        _heal(reg, els, cache, store, verifier=reject)
    assert store.list_heal_patches() == []
    assert not patches.exists() or list(patches.iterdir()) == []


def test_registered_patch_is_reviewable(tmp_path, store):
    els = elements_from_dom([raw(cls="chat-input-v2-send-button-new")], "w")
    cache = LocatorCache(str(YAML), patches_dir=str(tmp_path / "patches"))
    reg = {"sid": Locator("sid", "3.6.13", [{"cdp_selector": ".chat-input-v2-send-button"}], "")}
    result = _heal(reg, els, cache, store)
    patch_id = Path(result.patch_path).stem

    store.review_heal_patch(patch_id, "approved", "owner")
    assert store.list_heal_patches("pending") == []
    approved = store.list_heal_patches("approved")
    assert len(approved) == 1
    assert approved[0]["patch_id"] == patch_id
    assert approved[0]["reviewed_by"] == "owner"
    file_payload = yaml.safe_load(Path(result.patch_path).read_text(encoding="utf-8"))
    assert file_payload["patch_id"] == patch_id