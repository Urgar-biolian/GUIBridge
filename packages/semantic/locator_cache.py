"""Locator registry persistence with per-app-version sections and audited heal patches."""

from __future__ import annotations

import yaml

from semantic.element import Locator


class LocatorVersionMismatch(KeyError):
    pass


class LocatorCache:
    def __init__(self, yaml_path: str):
        self.yaml_path = yaml_path
        self._raw: dict | None = None

    def _load_raw(self) -> dict:
        if self._raw is None:
            with open(self.yaml_path, encoding="utf-8") as f:
                self._raw = yaml.safe_load(f) or {}
        return self._raw

    def load(self, app: str, app_version: str | None = None) -> dict[str, Locator]:
        data = self._load_raw()
        if data.get("app") and data["app"] != app:
            raise LocatorVersionMismatch(f"registry app is {data.get('app')!r}, requested {app!r}")
        file_version = str(data.get("app_version", ""))
        if app_version and file_version and app_version != file_version:
            raise LocatorVersionMismatch(
                f"registry version {file_version!r} != requested {app_version!r}; re-run probe")
        registry: dict[str, Locator] = {}
        for semantic_id, entry in (data.get("locators") or {}).items():
            registry[semantic_id] = Locator(
                semantic_id=semantic_id,
                app_version=file_version,
                chain=list(entry.get("chain") or []),
                verification=entry.get("verification", ""),
            )
        return registry

    def propose_heal_patch(self, app: str, app_version: str, locator: Locator) -> str:
        """Write a candidate patch file for human review; never overwrite silently."""
        raise NotImplementedError("S4")