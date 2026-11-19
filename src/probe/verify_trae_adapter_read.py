"""Ground capability C's FORMAL TraeAdapter read path in real measured data.

trae_cdp_focus.py measured a raw read-only Runtime.evaluate; this probe drives
the actual TraeAdapter code path (probe_channels + the full STATE_EXPR _state
read used by get_status/read_result) over loopback CDP, wrapped in FocusGuard,
to confirm the formal adapter reproduces the measured interference-free read
risk. STRICTLY READ-ONLY: no send_task, no clicks, no mode switch, no messages;
only DOM-query reads. Chat text is untrusted — only lengths/booleans are
recorded, never raw content. Writes var/experiments/<run_id>/trae_adapter_read.json.

send_task's send click is NOT exercised; its risk stays unknown pending an
authorized live measurement (R5).
"""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "packages"), str(Path(__file__).parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import win32_helpers as wh  # noqa: E402
import run_experiments as rx  # noqa: E402
from trae_cdp_focus import find_trae_hwnd  # noqa: E402
from adapters.trae.adapter import AdapterError  # noqa: E402
from adapters.trae.cdp_direct import CdpTraeAdapter  # noqa: E402
from packages.focusguard.monitor import Win32FocusGuard  # noqa: E402

PORT = 9222
TRIALS = 5


def _state_metrics(state: dict) -> dict:
    return {
        "has_root": bool(state.get("hasRoot")),
        "has_composer": bool(state.get("hasComposer")),
        "mode_name": state.get("modeName"),
        "text_len": len(state.get("text") or ""),
        "send_disabled": state.get("sendDisabled"),
        "stop_control": bool(state.get("stopControl")),
    }


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = rx.RUNS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    trae_hwnd = find_trae_hwnd()
    if trae_hwnd is None:
        print("ABORT: Trae top-level window not found")
        return 2
    guard = Win32FocusGuard(trae_hwnd)
    adapter = CdpTraeAdapter(port=PORT, store=None)
    print(f"trae_hwnd={trae_hwnd} title={wh.window_title(trae_hwnd)!r}")

    try:
        channels = adapter.probe_channels()
    except AdapterError as exc:
        print(f"ABORT: adapter probe_channels failed: {exc.code}")
        return 2
    if not channels.get("cdp"):
        print(f"ABORT: adapter CDP read path not reachable: {channels}")
        return 2
    print(f"probe_channels={channels}")

    trials = []
    for i in range(TRIALS):
        wh.wait_for_quiescence(min_idle_ms=500, timeout=4.0)

        def adapter_read():
            return adapter._run(adapter._with_channel(lambda ch: adapter._state(ch)))

        run = guard.wrap_with_events(adapter_read)
        state = run.result if isinstance(run.result, dict) else {}
        record = {
            "trial": i,
            "read_ok": bool(state.get("hasRoot")),
            "state": _state_metrics(state),
            "trae_foreground_at_start": run.before.target_active,
            "cursor_displacement": run.cursor_displacement,
            "unexpected_focus_switch": run.unexpected_focus_switch,
            "external_input_during_window": run.external_input_during_window,
            "event_hook_active": run.event_hook_active,
            "poll_events": [fg for _, fg in run.foreground_events],
            "hook_events": [fg for _, fg in run.hook_foreground_events],
        }
        trials.append(record)
        print(
            f"trial {i}: read_ok={record['read_ok']} cursor={record['cursor_displacement']} "
            f"focus_switch={record['unexpected_focus_switch']} ext={record['external_input_during_window']}"
        )
        time.sleep(0.3)

    clean = [t for t in trials if t["read_ok"] and not t["external_input_during_window"]]
    no_interference = [
        t for t in clean if not t["unexpected_focus_switch"] and t["cursor_displacement"] == 0
    ]
    measured = "none" if clean and len(no_interference) == len(clean) else "unknown"
    result = {
        "run_id": run_id,
        "env": {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "git_head": subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=rx.ROOT, capture_output=True, text=True
            ).stdout.strip(),
        },
        "trae_hwnd": trae_hwnd,
        "cdp_port": PORT,
        "adapter": "packages/adapters/trae/cdp_direct.py CdpTraeAdapter (formal read path)",
        "action": "read-only probe_channels + full STATE_EXPR _state; no clicks/input/messages/mode-switch",
        "interfaces_covered": ["get_task_status", "read_task_result (read mechanism)"],
        "interfaces_not_covered": ["send_task (send click requires authorized live measurement, R5)"],
        "probe_channels": channels,
        "trials": trials,
        "clean_trials": len(clean),
        "no_interference_trials": len(no_interference),
        "measured_read_risk": measured,
    }
    (out_dir / "trae_adapter_read.json").write_text(
        json.dumps(rx.jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"WROTE {out_dir / 'trae_adapter_read.json'}")
    print(f"clean={len(clean)}/{TRIALS} no_interference={len(no_interference)} measured_read_risk={measured}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())