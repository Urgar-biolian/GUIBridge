from pathlib import Path

import pytest

from semantic.locator_cache import LocatorCache, LocatorVersionMismatch

YAML = Path(__file__).parents[1] / "packages" / "adapters" / "trae" / "locators.yaml"


def test_loads_all_entries():
    reg = LocatorCache(str(YAML)).load("trae")
    assert len(reg) == 8
    composer = reg["trae.chat.composer"]
    assert composer.app_version == "3.6.13"
    assert "cdp_selector" in composer.chain[0]
    assert len(composer.chain) == 3


def test_version_mismatch_raises():
    with pytest.raises(LocatorVersionMismatch):
        LocatorCache(str(YAML)).load("trae", app_version="3.7.0")


def test_wrong_app_raises():
    with pytest.raises(LocatorVersionMismatch):
        LocatorCache(str(YAML)).load("cursor")