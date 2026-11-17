"""Integrity guards on the draft measured capability table: enforce the
task-book discipline that every channel declares a measured focus risk and no
risk is silently assumed. Protects the real data file against future edits.
Draft layer pending B-line approval."""

import yaml

from packages.routing.capability import OperationImpact
from packages.routing.capability_table import DEFAULT_TABLE, load_capability_table


def _raw_entries():
    with open(DEFAULT_TABLE, encoding="utf-8") as handle:
        return (yaml.safe_load(handle) or {}).get("entries") or []


def test_supported_unknown_risk_has_documented_measurement_gap():
    for entry in _raw_entries():
        notes = (entry.get("notes") or "").strip()
        for name, spec in (entry.get("channels") or {}).items():
            if spec.get("supported") and spec.get("risk", "unknown") == "unknown":
                assert notes, (
                    f"{entry['app']}.{entry['operation']} channel {name} carries "
                    "unknown risk without a documented measurement gap"
                )


def test_logical_only_requires_evidence():
    for entry in _raw_entries():
        for name, spec in (entry.get("channels") or {}).items():
            if spec.get("supported") and spec.get("risk") == "logical_only":
                assert entry.get("evidence"), (
                    f"{entry['app']}.{entry['operation']} channel {name} assumes "
                    "logical_only without measurement evidence"
                )


def test_unsupported_only_entries_carry_reason():
    for cap in load_capability_table().values():
        if not cap.supported():
            assert cap.unsupported_reason, f"{cap.app}.{cap.operation} unsupported without reason"


def test_every_entry_parses_impact_and_idempotent():
    for cap in load_capability_table().values():
        assert isinstance(cap.impact, OperationImpact)
        assert isinstance(cap.idempotent, bool)