"""Integrity guards on the draft measured capability table: enforce the
task-book discipline that every channel declares a measured focus risk and no
risk is silently assumed. Protects the real data file against future edits.
Draft layer pending B-line approval."""

import yaml

from packages.routing.capability import Channel, InterferenceRisk, OperationImpact
from packages.routing.capability_table import DEFAULT_TABLE, load_capability_table


_DEFINITE_RISKS = {r.value for r in InterferenceRisk if r is not InterferenceRisk.UNKNOWN}


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


def test_definite_risk_requires_evidence():
    """Principle 4: every definite risk claim (none/logical_only/focus_switch/
    physical_input) must be backed by measurement evidence, not assumed. Only
    UNKNOWN is exempt (it surfaces a gap, guarded separately)."""
    for entry in _raw_entries():
        for name, spec in (entry.get("channels") or {}).items():
            if spec.get("supported") and spec.get("risk") in _DEFINITE_RISKS:
                assert entry.get("evidence"), (
                    f"{entry['app']}.{entry['operation']} channel {name} claims "
                    f"risk={spec.get('risk')} without measurement evidence"
                )


def test_unsupported_only_entries_carry_reason():
    for cap in load_capability_table().values():
        if not cap.supported():
            assert cap.unsupported_reason, f"{cap.app}.{cap.operation} unsupported without reason"


def test_every_entry_parses_impact_and_idempotent():
    for cap in load_capability_table().values():
        assert isinstance(cap.impact, OperationImpact)
        assert isinstance(cap.idempotent, bool)


_WRITE_OPERATIONS = {"invoke", "set_value", "toggle", "send_message", "send_task"}


def test_ocr_vision_not_a_background_execution_channel_for_writes():
    """Principle 3: OCR/vision is locate-only, never background input. A write
    operation must not declare OCR_VISION as a supported execution channel.
    Read/locate operations may legitimately use OCR with NONE risk; how the
    router should enforce this at selection time is B-line decision R6."""
    for cap in load_capability_table().values():
        if cap.operation in _WRITE_OPERATIONS:
            assert Channel.OCR_VISION not in cap.supported(), (
                f"{cap.app}.{cap.operation} declares OCR_VISION as a background "
                "execution channel; OCR is locate-only (principle 3)"
            )