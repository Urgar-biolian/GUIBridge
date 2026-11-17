"""Locator registry persistence with per-app-version sections and audited heal patches."""

from semantic.element import Locator


class LocatorCache:
    def __init__(self, yaml_path: str):
        self.yaml_path = yaml_path

    def load(self, app: str, app_version: str) -> dict[str, Locator]:
        raise NotImplementedError("S1")

    def propose_heal_patch(self, app: str, app_version: str, locator: Locator) -> str:
        """Write a candidate patch file for human review; never overwrite silently."""
        raise NotImplementedError("S4")