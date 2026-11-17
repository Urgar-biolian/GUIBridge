"""Brief end-to-end verification of the classify/risk corrections against the
controlled native target (no Trae/WeChat, no messages).

Validates that real UIA actions now report the measured FOCUS_SWITCH risk (not
the stale LOGICAL_ONLY hardcode) and that classify() yields the four-state
result on real FocusRuns. Runs three patterns once each (a few seconds of
controlled foreground activity), writes var/experiments/<run_id>/verify_classify.json.
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
from packages.focusguard.monitor import Win32FocusGuard  # noqa: E402
from packages.routing.capability import InterferenceRisk  # noqa: E402


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

        actions = {
            "invoke": lambda: ux.invoke_button(target, guard),
            "set_value": lambda: ux.set_edit(target, guard, "verify-value"),
            "toggle": lambda: ux.toggle_checkbox(target, guard),
        }
        records = {}
        for name, fn in actions.items():
            result = fn()
            records[name] = {
                "state": result.state.value,
                "risk": result.risk.value,
                "effect_verified": result.effect_verified,
                "unexpected_focus_switch": result.unexpected_focus_switch,
                "cursor_displacement": result.evidence.get("cursor_displacement"),
            }
            print(f"{name}: state={records[name]['state']} risk={records[name]['risk']} verified={result.effect_verified}")

        risk_ok = all(r["risk"] == InterferenceRisk.FOCUS_SWITCH.value for r in records.values())
        result = {
            "run_id": run_id,
            "env": {
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "git_head": rx.subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=rx.ROOT, capture_output=True, text=True
                ).stdout.strip(),
            },
            "target_hwnd": target_hwnd,
            "purpose": "verify classify four-state + measured FOCUS_SWITCH risk on real UIA actions",
            "records": records,
            "all_report_focus_switch": risk_ok,
        }
        (out_dir / "verify_classify.json").write_text(
            json.dumps(rx.jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"WROTE {out_dir / 'verify_classify.json'} all_report_focus_switch={risk_ok}")
        return 0 if risk_ok else 1
    finally:
        target_proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())