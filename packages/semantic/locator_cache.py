"""Locator registry persistence with per-app-version sections and audited heal patches."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone

import yaml

from semantic.element import Locator


class LocatorVersionMismatch(KeyError):
    pass


def _safe(part: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", part).strip("_") or "x"


class LocatorCache:
    def __init__(self, yaml_path: str, patches_dir: str | None = None):
        self.yaml_path = yaml_path
        self.patches_dir = patches_dir or os.path.join(os.getcwd(), "var", "heal_patches")
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

    def propose_heal_patch(self, app: str, app_version: str, locator: Locator,
                           previous_chain: list[dict] | None = None) -> str:
        """Write a candidate patch file for human review; never overwrite the registry."""
        os.makedirs(self.patches_dir, exist_ok=True)
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        base = f"heal_{_safe(app)}_{_safe(app_version)}_{_safe(locator.semantic_id)}_{ts}"
        path = os.path.join(self.patches_dir, f"{base}.yaml")
        n = 1
        while os.path.exists(path):
            path = os.path.join(self.patches_dir, f"{base}_{n}.yaml")
            n += 1
        payload = {
            "patch_id": os.path.splitext(os.path.basename(path))[0],
            "status": "pending",
            "app": app,
            "app_version": app_version,
            "semantic_id": locator.semantic_id,
            "verification": locator.verification,
            "previous_chain": list(previous_chain or []),
            "proposed_chain": list(locator.chain),
            "created_ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "reviewed_by": None,
        }
        with open(path, "w", encoding="utf-8") as f:
            yaml.safe_dump(payload, f, allow_unicode=True, sort_keys=False)
        return path
