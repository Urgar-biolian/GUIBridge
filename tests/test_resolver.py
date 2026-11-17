import asyncio

import pytest

from semantic.element import GUIElement, Locator
from semantic.resolver import IdentityMismatch, LocatorMissing, ResolveConflict, Resolver


def el(role="button", name="x", conf=0.9, src="cdp"):
    return GUIElement(id=f"{src}-1", window_id="w", role=role, name=name,
                      bounds=(0, 0, 10, 10), source=[src], confidence=conf)


class FakeProvider:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    async def find(self, window_id, spec):
        self.calls += 1
        return self.results.pop(0) if self.results else []


def registry(*steps):
    return {"sid": Locator("sid", "3.6.13", list(steps))}


def run(coro):
    return asyncio.run(coro)


def test_falls_back_to_next_chain_step():
    cdp, ocr = FakeProvider([[]]), FakeProvider([[el(src="ocr", conf=0.5)]])
    r = Resolver(registry({"cdp_selector": ".x"}, {"ocr_text": "y"}),
                 {"cdp_selector": cdp, "ocr_text": ocr})
    out = run(r.resolve("w", "sid"))
    assert out.source == ["ocr"]
    assert cdp.calls == 1 and ocr.calls == 1


def test_unknown_semantic_id():
    r = Resolver({}, {})
    with pytest.raises(LocatorMissing) as ei:
        run(r.resolve("w", "nope"))
    assert ei.value.code == "locator_missing"


def test_multiple_candidates_is_conflict():
    p = FakeProvider([[el(name="删除"), el(name="删除")]])
    r = Resolver(registry({"cdp_selector": ".x"}), {"cdp_selector": p})
    with pytest.raises(ResolveConflict) as ei:
        run(r.resolve("w", "sid"))
    assert ei.value.code == "conflict"


def test_low_confidence_filtered_out():
    p = FakeProvider([[el(conf=0.3)]])
    r = Resolver(registry({"cdp_selector": ".x"}), {"cdp_selector": p})
    with pytest.raises(LocatorMissing):
        run(r.resolve("w", "sid"))


def test_custom_min_confidence():
    p = FakeProvider([[el(conf=0.4)]])
    r = Resolver(registry({"cdp_selector": ".x"}), {"cdp_selector": p}, min_confidence=0.4)
    assert run(r.resolve("w", "sid")).confidence == 0.4


def test_window_checker_mismatch_blocks_resolution():
    p = FakeProvider([[el()]])

    def checker(wid):
        raise RuntimeError("pid changed")

    r = Resolver(registry({"cdp_selector": ".x"}), {"cdp_selector": p},
                 window_checker=checker)
    with pytest.raises(IdentityMismatch) as ei:
        run(r.resolve("w", "sid"))
    assert ei.value.code == "identity_mismatch"
    assert p.calls == 0


def test_missing_provider_skips_step():
    p = FakeProvider([[el()]])
    r = Resolver(registry({"vision_grid": "x"}, {"cdp_selector": ".x"}),
                 {"cdp_selector": p})
    assert run(r.resolve("w", "sid")).source == ["cdp"]


def test_no_coordinate_cache_between_calls():
    p = FakeProvider([[el()], [el()]])
    r = Resolver(registry({"cdp_selector": ".x"}), {"cdp_selector": p})
    first = run(r.resolve("w", "sid"))
    second = run(r.resolve("w", "sid"))
    assert p.calls == 2
    assert first is not second