"""Pre-G1 locator loader: reads packages/adapters/trae/locators.yaml into `Locator` objects.

`semantic.locator_cache.LocatorCache.load` is the A-line S1 deliverable; this shim exists only so the
control plane and Dashboard are runnable before the two lanes integrate. It is deleted at gate G1.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "packages"))

import yaml
from semantic.element import Locator

DEFAULT_YAML = Path(__file__).resolve().parents[2] / "packages" / "adapters" / "trae" / "locators.yaml"


def load_registry(yaml_path: Path | str = DEFAULT_YAML) -> tuple[dict, dict]:
    raw = yaml.safe_load(Path(yaml_path).read_text(encoding="utf-8"))
    app_version = str(raw["app_version"])
    registry = {}
    for semantic_id, entry in raw["locators"].items():
        registry[semantic_id] = Locator(semantic_id=semantic_id, app_version=app_version,
                                        chain=list(entry.get("chain", [])),
                                        verification=entry.get("verification", ""))
    meta = {"app": raw.get("app", "trae"), "app_version": app_version, "window": raw.get("window", {}),
            "safety": raw.get("safety", {}),
            "roles": {sid: entry.get("role", "") for sid, entry in raw["locators"].items()}}
    return registry, meta
