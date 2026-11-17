"""End-to-end demonstration that the draft contracts compose on REAL measured
data (controlled native target only; no Trae/WeChat, no messages, no frozen
engine/mcp_gateway wiring).

For each native-test operation it runs the full draft chain:
  capability table -> StaticRouter (STRICT unapproved / STRICT approved /
  BALANCED) -> real UIA action via FocusGuard -> four-state classify ->
  decide_retry (principle 6) -> to_legacy_envelope (frozen two-state bridge).

The composition unit tests use synthetic results; this probe grounds the same
chain in a live controlled run so B-review can see measured risk, routing
gating, retry denial and the legacy-envelope degradation together. Writes
var/experiments/<run_id>/contract_chain.json.
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
from packages.focusguard.retry_policy import decide_retry  # noqa: E402
from packages.focusguard.legacy_bridge import to_legacy_envelope  # noqa: E402
from packages.routing.capability import Channel, InterferenceRisk  # noqa: E402
from packages.routing.capability_table import load_capability_table  # noqa: E402
from packages.routing.policy import InterferencePolicy  # noqa: E402
from packages.routing.router import StaticRouter  # noqa: E402


def _decision_record(decision) -> dict:
    return {
        "channel": decision.channel.value if decision.channel else None,
        "risk": decision.risk.value,
        "requires_approval": decision.requires_approval,
        "fallbacks": [c.value for c in decision.fallbacks],
        "reason": decision.reason,
    }


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = rx.RUNS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    table = load_capability_table()
    router = StaticRouter()
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
            "set_value": lambda: ux.set_edit(target, guard, "chain-value"),
            "toggle": lambda: ux.toggle_checkbox(target, guard),
        }
        records = {}
        for name, fn in actions.items():
            cap = table[("native-test", name)]
            routing = {
                "strict_unapproved": _decision_record(
                    router.route(cap, InterferencePolicy.STRICT_NO_INTERFERENCE, approved=False)),
                "strict_approved": _decision_record(
                    router.route(cap, InterferencePolicy.STRICT_NO_INTERFERENCE, approved=True)),
                "balanced_unapproved": _decision_record(
                    router.route(cap, InterferencePolicy.BALANCED, approved=False)),
            }
            result = fn()
            retry = decide_retry(result.state, cap.idempotent)
            envelope = to_legacy_envelope(result)
            records[name] = {
                "impact": cap.impact.value,
                "idempotent": cap.idempotent,
                "routing": routing,
                "executed": {
                    "state": result.state.value,
                    "channel": result.channel.value,
                    "risk": result.risk.value,
                    "effect_verified": result.effect_verified,
                    "unexpected_focus_switch": result.unexpected_focus_switch,
                    "cursor_displacement": result.evidence.get("cursor_displacement"),
                },
                "retry": {
                    "allow_retry": retry.allow_retry,
                    "requires_approval": retry.requires_approval,
                    "reason": retry.reason,
                },
                "legacy_envelope": {
                    "success": envelope.success,
                    "verified": envelope.verified,
                    "error_code": envelope.error_code,
                    "state": envelope.state.value,
                    "risk": envelope.risk.value,
                    "interference_observed": envelope.interference_observed,
                },
            }
            print(
                f"{name}: strict_unapproved={routing['strict_unapproved']['channel']} "
                f"balanced={routing['balanced_unapproved']['channel']} "
                f"state={result.state.value} risk={result.risk.value} "
                f"retry={retry.allow_retry} legacy_success={envelope.success}"
            )

        strict_denied = all(
            r["routing"]["strict_unapproved"]["channel"] is None for r in records.values())
        strict_approved_uia = all(
            r["routing"]["strict_approved"]["channel"] == Channel.UIA.value for r in records.values())
        balanced_uia = all(
            r["routing"]["balanced_unapproved"]["channel"] == Channel.UIA.value for r in records.values())
        measured_focus_switch = all(
            r["executed"]["risk"] == InterferenceRisk.FOCUS_SWITCH.value for r in records.values())
        success_no_retry = all(
            not r["retry"]["allow_retry"] for r in records.values())
        chain_ok = (strict_denied and strict_approved_uia and balanced_uia
                    and measured_focus_switch and success_no_retry)
        result = {
            "run_id": run_id,
            "env": {
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "git_head": rx.subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=rx.ROOT, capture_output=True, text=True
                ).stdout.strip(),
            },
            "target_hwnd": target_hwnd,
            "purpose": "draft contract chain (route->exec->classify->retry->legacy) on real measured UIA",
            "records": records,
            "checks": {
                "strict_unapproved_denies_focus_switch": strict_denied,
                "strict_approved_selects_uia": strict_approved_uia,
                "balanced_selects_uia": balanced_uia,
                "executed_risk_focus_switch": measured_focus_switch,
                "succeeded_operations_no_retry": success_no_retry,
            },
            "chain_ok": chain_ok,
        }
        (out_dir / "contract_chain.json").write_text(
            json.dumps(rx.jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"WROTE {out_dir / 'contract_chain.json'} chain_ok={chain_ok}")
        return 0 if chain_ok else 1
    finally:
        target_proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())