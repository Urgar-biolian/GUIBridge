"""Live heal tests: simulated class drift on the real Trae DOM. Read-only (scan + query only)."""

import asyncio
import os
from pathlib import Path

import pytest

from perception.cdp import CDPChannel, list_targets
from semantic.element import Locator
from semantic.heal import HealAmbiguous
from semantic.locator_cache import LocatorCache
from semantic.providers import CDPSelectorProvider
from semantic.resolver import Resolver

PORT = int(os.environ.get("GUIBRIDGE_CDP_PORT", "9222"))
YAML = Path(__file__).parents[1] / "packages" / "adapters" / "trae" / "locators.yaml"


async def _connect():
    try:
        targets = list_targets(PORT)
    except Exception as e:
        pytest.skip(f"CDP unreachable on {PORT}: {e}")
    page = next((t for t in targets if t.type == "page" and "trae" in (t.title + t.url).lower()), None)
    if page is None:
        pytest.skip("no Trae page target on debug port")
    ch = CDPChannel(PORT)
    await ch.connect(page.ws_url)
    await ch.attach_sessions()
    sid = next((s for s, info in ch.sessions.items() if info.get("type") == "page"), None)
    return ch, CDPSelectorProvider(ch, sid)


@pytest.mark.live
def test_live_heal_unique_candidate_after_drift(tmp_path):
    asyncio.run(_unique(tmp_path))


async def _unique(tmp_path):
    ch, provider = await _connect()
    try:
        registry = {"live.send": Locator(
            "live.send", "3.6.13", [{"cdp_selector": ".chat-input-v2-send"}],
            "message_submitted")}

        async def verify(window_id, element):
            probes = await provider.find(window_id, {"cdp_selector": "button.chat-input-v2-send-button"})
            return any(p.bounds == element.bounds for p in probes)

        cache = LocatorCache(str(YAML), patches_dir=str(tmp_path))
        resolver = Resolver(registry, {"cdp_selector": provider}, scanner=provider.scan,
                            verifier=verify, patch_writer=cache.propose_heal_patch, app="trae")
        result = await resolver.heal("live", "live.send", expected_role="button")

        assert result.proposed_chain == [{"cdp_selector": "button.chat-input-v2-send-button"}]
        assert result.verified is True
        assert result.patch_path and Path(result.patch_path).exists()
        assert registry["live.send"].chain == [{"cdp_selector": ".chat-input-v2-send"}]
    finally:
        await ch.close()


@pytest.mark.live
def test_live_heal_ambiguous_hint_stops(tmp_path):
    asyncio.run(_ambiguous(tmp_path))


async def _ambiguous(tmp_path):
    ch, provider = await _connect()
    try:
        registry = {"live.chat": Locator(
            "live.chat", "3.6.13", [{"cdp_selector": ".chat-input-v2"}], "")}
        cache = LocatorCache(str(YAML), patches_dir=str(tmp_path))
        resolver = Resolver(registry, {"cdp_selector": provider}, scanner=provider.scan,
                            patch_writer=cache.propose_heal_patch, app="trae")
        with pytest.raises(HealAmbiguous) as ei:
            await resolver.heal("live", "live.chat")
        assert ei.value.code == "conflict"
        assert list(tmp_path.iterdir()) == []
    finally:
        await ch.close()