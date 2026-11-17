"""Loader for the draft measured capability table (pending B-line approval).

Builds Capability objects from capabilities.draft.yaml. Risk values come from
Phase 1 measurements; this module performs no online probing and does not wire
into the frozen engine. It exists so the StaticRouter consumes real measured
data rather than only test fixtures.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from .capability import Capability, Channel, InterferenceRisk

DEFAULT_TABLE = Path(__file__).with_name("capabilities.draft.yaml")


def build_capability(entry: dict) -> Capability:
    channels: dict[Channel, bool] = {}
    risk: dict[Channel, InterferenceRisk] = {}
    for name, spec in (entry.get("channels") or {}).items():
        channel = Channel(name)
        channels[channel] = bool(spec.get("supported", False))
        risk[channel] = InterferenceRisk(spec.get("risk", "unknown"))
    return Capability(
        app=entry["app"],
        operation=entry["operation"],
        channels=channels,
        risk=risk,
        unsupported_reason=entry.get("unsupported_reason"),
    )


def load_capability_table(path: str | Path | None = None) -> dict[tuple[str, str], Capability]:
    source = Path(path) if path is not None else DEFAULT_TABLE
    with open(source, encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    table: dict[tuple[str, str], Capability] = {}
    for entry in data.get("entries") or []:
        cap = build_capability(entry)
        table[(cap.app, cap.operation)] = cap
    return table