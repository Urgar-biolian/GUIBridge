"""Real-measured validation of the draft formal UiaPatternChannel against the
controlled native target (no Trae/WeChat, no messages, no frozen wiring).

Builds the channel with real adapters (uiautomation pattern access, Win32
FocusGuard, target readback) and runs invoke/set_value/toggle once each,
confirming the formal channel reproduces the probe's measured FOCUS_SWITCH
four-state results. Writes var/experiments/<run_id>/uia_channel.json.
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

import uiautomation as auto  # noqa: E402

import win32_helpers as wh  # noqa: E402
import uia_exec as ux  # noqa: E402
import run_experiments as rx  # noqa: E402
from packages.execution.uia_channel import UiaPatternChannel  # noqa: E402
from packages.focusguard.monitor import Win32FocusGuard  # noqa: E402
from packages.routing.capability import InterferenceRisk  # noqa: E402

PATTERN_ID = {
    "invoke": auto.PatternId.InvokePattern,
    "set_value": auto.PatternId.ValuePattern,
    "toggle": auto.PatternId.TogglePattern,
}


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = rx.RUNS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    target_proc = rx.start_app(x=220, y=180, auto_close=120)
    try:
        target = ux.find_window(rx.TARGET_TITLE, rx.TARGET_CLASS, timeout=8)
        if target is None:
            print("ABORT: target window not found")
            return 2
        target_hwnd = int(target.NativeWindowHandle)
        guard = Win32FocusGuard(target_hwnd)
        wh.ensure_foreground(target_hwnd)

        def resolve(window_id, semantic_id):
            return ux.find_control(target, semantic_id)

        def pattern_of(control, action):
            return ux._pattern(control, PATTERN_ID[action]) if control is not None else None

        def read_state(window_id, semantic_id):
            if semantic_id == ux.BUTTON_ID:
                return ux.read_status(target)
            if semantic_id == ux.EDIT_ID:
                return ux.read_edit(target)
            if semantic_id == ux.CHECKBOX_ID:
                return ux.toggle_state(target)
            return None

        def verify(action, before, after, args):
            if action == "invoke":
                return ux.clicked_count(after) is not None and after != before
            if action == "set_value":
                return after == args["value"]
            if action == "toggle":
                return before is not None and after is not None and after != before
            return False

        channel = UiaPatternChannel(
            resolve=resolve, pattern_of=pattern_of, guard_for=lambda wid: guard,
            read_state=read_state, verify=verify,
        )

        actions = {
            "invoke": lambda: channel.invoke("target", ux.BUTTON_ID),
            "set_value": lambda: channel.set_value("target", ux.EDIT_ID, "channel-value"),
            "toggle": lambda: channel.toggle("target", ux.CHECKBOX_ID),
        }
        records = {}
        for name, fn in actions.items():
            result = fn()
            records[name] = {
                "state": result.state.value,
                "channel": result.channel.value,
                "risk": result.risk.value,
                "effect_verified": result.effect_verified,
                "unexpected_focus_switch": result.unexpected_focus_switch,
                "cursor_displacement": result.evidence.get("cursor_displacement"),
            }
            print(f"{name}: state={records[name]['state']} risk={records[name]['risk']} verified={result.effect_verified}")

        risk_ok = all(r["risk"] == InterferenceRisk.FOCUS_SWITCH.value for r in records.values())
        verified_ok = all(r["effect_verified"] for r in records.values())
        result = {
            "run_id": run_id,
            "env": {
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "git_head": rx.subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=rx.ROOT, capture_output=True, text=True
                ).stdout.strip(),
            },
            "target_hwnd": target_hwnd,
            "purpose": "validate formal draft UiaPatternChannel on real measured UIA actions",
            "records": records,
            "all_report_focus_switch": risk_ok,
            "all_effect_verified": verified_ok,
        }
        (out_dir / "uia_channel.json").write_text(
            json.dumps(rx.jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"WROTE {out_dir / 'uia_channel.json'} focus_switch={risk_ok} verified={verified_ok}")
        return 0 if (risk_ok and verified_ok) else 1
    finally:
        target_proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())