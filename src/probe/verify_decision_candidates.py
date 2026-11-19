"""Ground the R2/R3/R4/R6 decision candidates in REAL measured data (controlled
native target only; no Trae/WeChat, no messages, no frozen engine wiring).

The candidate unit tests use synthetic fixtures; this probe exercises them on a
live controlled run so B-review sees them composed with measured UIA risk:
  - R3 attribution: classify_with_attribution on the real FocusRun fields; on a
    clean window it must agree with classify, and if external input polluted the
    window it must downgrade a verified success to UNCONFIRMED.
  - R2 extended envelope: to_extended_envelope carries the measured four-state
    risk and keeps UNCONFIRMED distinguishable from FAILED.
  - R6 OCR-aware routing: route_ocr_aware on the real native-test capability
    (UIA only) must still select UIA, undisturbed.
  - R4 crosswalk: operation_names maps the real table's Trae operations to the
    frozen TOOL_SPECS names consistently.

Writes var/experiments/<run_id>/decision_candidates.json.
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(Path(__file__).parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import win32_helpers as wh  # noqa: E402
import uia_exec as ux  # noqa: E402
import run_experiments as rx  # noqa: E402
from packages.focusguard.attribution import classify_with_attribution  # noqa: E402
from packages.focusguard.extended_envelope import to_extended_envelope  # noqa: E402
from packages.focusguard.monitor import FocusRun, Win32FocusGuard  # noqa: E402
from packages.focusguard.outcome import ResultState  # noqa: E402
from packages.routing.capability import Channel, InterferenceRisk  # noqa: E402
from packages.routing.capability_table import load_capability_table  # noqa: E402
from packages.routing.ocr_guard import route_ocr_aware  # noqa: E402
from packages.routing.operation_names import capability_key, tool_name  # noqa: E402
from packages.routing.policy import InterferencePolicy  # noqa: E402

_SUCCEEDED = (
    ResultState.SUCCESS_NO_INTERFERENCE_OBSERVED,
    ResultState.SUCCESS_WITH_INTERFERENCE,
)
_FROZEN_TRAE_TOOLS = {"trae.send_task", "trae.get_status", "trae.read_result"}


def _real_run(result) -> FocusRun:
    """Reconstruct the FocusRun from the ActionResult's REAL measured fields."""
    return FocusRun(
        result=None,
        before=result.focus_before,
        after=result.focus_after,
        unexpected_focus_switch=result.unexpected_focus_switch,
        cursor_displacement=result.evidence.get("cursor_displacement", 0),
        external_input_during_window=result.evidence.get("external_input_during_window"),
    )


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = rx.RUNS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    table = load_capability_table()
    target_proc = rx.start_app(x=220, y=180, auto_close=120)
    try:
        target = ux.find_window(rx.TARGET_TITLE, rx.TARGET_CLASS, timeout=8)
        if target is None:
            print("ABORT: target window not found")
            return 2
        target_hwnd = int(target.NativeWindowHandle)
        guard = Win32FocusGuard(target_hwnd)
        wh.ensure_foreground(target_hwnd)

        actions = {
            "invoke": lambda: ux.invoke_button(target, guard),
            "set_value": lambda: ux.set_edit(target, guard, "candidate-value"),
            "toggle": lambda: ux.toggle_checkbox(target, guard),
        }
        records = {}
        for name, fn in actions.items():
            cap = table[("native-test", name)]
            result = fn()
            base_state = result.state
            external = result.evidence.get("external_input_during_window")
            attr_state = classify_with_attribution(
                _real_run(result), result.effect_verified, None, Channel.UIA
            )
            expected_attr = (
                ResultState.UNCONFIRMED
                if (external is True and base_state in _SUCCEEDED)
                else base_state
            )
            extended = to_extended_envelope(result)
            ocr_decision = route_ocr_aware(cap, InterferencePolicy.BALANCED)
            records[name] = {
                "base_state": base_state.value,
                "external_input_during_window": external,
                "attribution_state": attr_state.value,
                "attribution_expected": expected_attr.value,
                "attribution_correct": attr_state is expected_attr,
                "extended": {
                    "success": extended.success,
                    "verified": extended.verified,
                    "state": extended.state.value,
                    "risk": extended.risk.value,
                    "interference_observed": extended.interference_observed,
                },
                "ocr_aware_channel": ocr_decision.channel.value if ocr_decision.channel else None,
            }
            print(
                f"{name}: base={base_state.value} external={external} "
                f"attr={attr_state.value} ext_state={extended.state.value} "
                f"ext_risk={extended.risk.value} ocr_aware={records[name]['ocr_aware_channel']}"
            )

        # R4 crosswalk against the real loaded table (no target needed).
        trae_ops = sorted(op for (app, op) in table if app == "trae")
        crosswalk = {op: tool_name("trae", op) for op in trae_ops}
        crosswalk_consistent = (
            set(crosswalk.values()) == _FROZEN_TRAE_TOOLS
            and all(capability_key(t) in table for t in _FROZEN_TRAE_TOOLS)
        )

        attribution_correct = all(r["attribution_correct"] for r in records.values())
        extended_carries_risk = all(
            r["extended"]["risk"] == InterferenceRisk.FOCUS_SWITCH.value
            and r["extended"]["state"] == r["base_state"]
            for r in records.values()
        )
        extended_success = all(
            r["extended"]["success"] and r["extended"]["verified"] for r in records.values()
        )
        ocr_aware_uia = all(
            r["ocr_aware_channel"] == Channel.UIA.value for r in records.values()
        )
        candidates_ok = (
            attribution_correct and extended_carries_risk and extended_success
            and ocr_aware_uia and crosswalk_consistent
        )
        result = {
            "run_id": run_id,
            "env": {
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "git_head": rx.subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=rx.ROOT, capture_output=True, text=True
                ).stdout.strip(),
            },
            "target_hwnd": target_hwnd,
            "purpose": "R2/R3/R4/R6 decision candidates grounded in real measured UIA",
            "records": records,
            "crosswalk": crosswalk,
            "checks": {
                "attribution_correct_on_real_flags": attribution_correct,
                "extended_carries_measured_risk_and_state": extended_carries_risk,
                "extended_success_verified": extended_success,
                "ocr_aware_native_selects_uia": ocr_aware_uia,
                "crosswalk_consistent_with_table_and_frozen": crosswalk_consistent,
            },
            "candidates_ok": candidates_ok,
        }
        (out_dir / "decision_candidates.json").write_text(
            json.dumps(rx.jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"WROTE {out_dir / 'decision_candidates.json'} candidates_ok={candidates_ok}")
        return 0 if candidates_ok else 1
    finally:
        target_proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())