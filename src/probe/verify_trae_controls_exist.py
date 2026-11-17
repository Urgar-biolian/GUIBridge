"""B-line R5 precondition step 1: READ-ONLY control-existence probe on the local Trae.

B's review (2026-11-17) asks A line to confirm, on the actually-installed Trae CN
(3.4.20) rather than the registry baseline (3.6.13), whether the three controls the
adapter depends on still exist and how the mode-selection state reads:
  * ``.popup-menu`` leaf items (mode menu structure)
  * ``.chat-input-v2-send-button`` (send button)
  * ``button[aria-label='自动审批']`` / ``[class*=permissionModeTrigger]`` (approval trigger)

STRICTLY READ-ONLY: no clicks, no Input.dispatch*, no insert_text, no focus(), no mode
switch, no send. The mode menu is enumerated ONLY if it happens to be already open; this
probe never clicks to open it (opening a dropdown is an interaction, kept out of step 1).
Chat body text is untrusted and is NOT recorded — only control labels, presence, geometry,
and lengths/booleans. The formal adapter STATE_EXPR read path is exercised to confirm the
mode-selection state read works on this build. Wrapped in Win32FocusGuard so the probe's
own zero-interference is measured, not assumed.

Writes var/experiments/<run_id>/trae_controls_exist.json (gitignored). This probe does NOT
measure send_task's send-click risk; that stays unknown pending an authorized live write (R5).
"""

from __future__ import annotations

import asyncio
import datetime
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(ROOT / "packages"), str(Path(__file__).parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import run_experiments as rx  # noqa: E402
import win32_helpers as wh  # noqa: E402
from trae_cdp_focus import find_trae_hwnd  # noqa: E402
from adapters.trae.adapter import STATE_EXPR  # noqa: E402
from packages.focusguard.monitor import Win32FocusGuard  # noqa: E402
from perception.cdp import CDPChannel, list_targets  # noqa: E402

PORT = 9222

# Read-only DOM existence/attribute read. info() deliberately omits textContent so the
# conversation root / composer can never leak untrusted chat body into the record.
CONTROLS_EXPR = r"""(() => {
  const q = s => document.querySelector(s);
  const info = el => {
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {
      present: true,
      tag: el.tagName,
      cls: String(el.className || '').slice(0, 160),
      aria: el.getAttribute('aria-label'),
      disabled: el.disabled === true || /(^|\s)disabled(\s|$)/.test(String(el.className || '')),
      visible: r.width > 0 && r.height > 0,
      rect: [Math.round(r.x), Math.round(r.y), Math.round(r.right), Math.round(r.bottom)]
    };
  };
  const modeNameEl = q('.v2-agent-entry-btn__name');
  const approvalAuto = q("button[aria-label='自动审批']");
  const approvalManual = q("button[aria-label='手动审批']");
  const approvalClass = q('[class*=permissionModeTrigger]');
  const approvalAny = approvalManual || approvalAuto || approvalClass;
  const pop = q('.popup-menu');
  const leaves = pop ? [...pop.querySelectorAll('.popup-menu-item')]
      .filter(el => el.getBoundingClientRect().height > 0)
      .map(el => (el.innerText || '').trim().slice(0, 30)) : [];
  return JSON.stringify({
    ide_tab: info(q('.icube-mode-tab-item-ide')),
    chat_root: info(q('.ai-chat-v2-ide-root')),
    composer: info(q('.chat-input-v2-input-box-editable')),
    send_button: info(q('.chat-input-v2-send-button')),
    new_session: info(q('[data-testid=ai-chat-create-new-session]')),
    mode_entry: info(q('.v2-agent-entry-btn')),
    mode_name: modeNameEl ? modeNameEl.textContent.trim() : null,
    model_select: info(q('.icd-model-select-trigger')),
    approval_by_aria_auto: info(approvalAuto),
    approval_by_aria_manual: info(approvalManual),
    approval_by_class: info(approvalClass),
    approval_label: approvalAny ? (approvalAny.getAttribute('aria-label') || approvalAny.textContent || '').trim() : null,
    popup_menu_open: !!pop,
    popup_menu_leaves: leaves,
    version_hints: {
      body_dataset: Object.assign({}, document.body.dataset),
      user_agent: navigator.userAgent
    }
  });
})()"""


def _browser_version() -> dict:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json/version", timeout=3) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def _state_metrics(state: dict) -> dict:
    return {
        "has_root": bool(state.get("hasRoot")),
        "has_composer": bool(state.get("hasComposer")),
        "mode_name": state.get("modeName"),
        "send_disabled": state.get("sendDisabled"),
        "stop_control": bool(state.get("stopControl")),
        "approval_label": state.get("approvalLabel"),
        "text_len": len(state.get("text") or ""),
    }


async def _read() -> dict:
    targets = list_targets(PORT)
    pages = [t for t in targets if t.type == "page" and "trae" in (t.title + t.url).lower()]
    if not pages:
        raise RuntimeError("no Trae page target")
    ch = CDPChannel(PORT)
    await ch.connect(pages[0].ws_url)
    try:
        controls = await ch.evaluate_json(CONTROLS_EXPR)
        state = await ch.evaluate_json(STATE_EXPR)
        return {
            "target_title": pages[0].title,
            "target_url": pages[0].url,
            "controls": controls or {},
            "state_metrics": _state_metrics(state or {}),
        }
    finally:
        await ch.close()


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = rx.RUNS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    trae_hwnd = find_trae_hwnd()
    if trae_hwnd is None:
        print("ABORT: Trae top-level window not found (is Trae running with CDP on 9222?)")
        return 2
    print(f"trae_hwnd={trae_hwnd} title={wh.window_title(trae_hwnd)!r}")
    guard = Win32FocusGuard(trae_hwnd)
    version = _browser_version()

    wh.wait_for_quiescence(min_idle_ms=500, timeout=4.0)
    run = guard.wrap_with_events(lambda: asyncio.run(_read()))
    data = run.result if isinstance(run.result, dict) else {}
    if not data.get("controls"):
        print(f"ABORT: read-only CDP existence read failed: {run.result!r}")
        return 2

    c = data["controls"]
    sm = data["state_metrics"]

    def present(key):
        v = c.get(key)
        return bool(v and v.get("present"))

    approval_present = present("approval_by_aria_auto") or present("approval_by_class") or present("approval_by_aria_manual")
    findings = {
        "send_button_present": present("send_button"),
        "send_button_disabled": (c.get("send_button") or {}).get("disabled"),
        "approval_trigger_present": approval_present,
        "approval_label": c.get("approval_label"),
        "approval_by_aria_auto_present": present("approval_by_aria_auto"),
        "approval_by_aria_manual_present": present("approval_by_aria_manual"),
        "approval_by_class_present": present("approval_by_class"),
        "mode_entry_present": present("mode_entry"),
        "mode_name": c.get("mode_name"),
        "state_mode_name": sm.get("mode_name"),
        "popup_menu_open": bool(c.get("popup_menu_open")),
        "popup_menu_leaves": c.get("popup_menu_leaves") or [],
        "ide_tab_present": present("ide_tab"),
        "chat_root_present": present("chat_root"),
        "composer_present": present("composer"),
        "new_session_present": present("new_session"),
    }

    result = {
        "run_id": run_id,
        "env": {
            "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "git_head": subprocess.run(["git", "rev-parse", "HEAD"], cwd=rx.ROOT,
                                       capture_output=True, text=True).stdout.strip(),
        },
        "trae_hwnd": trae_hwnd,
        "window_title": wh.window_title(trae_hwnd),
        "cdp_port": PORT,
        "browser_version_endpoint": version,
        "action": "READ-ONLY existence/attribute probe; no clicks/input/messages/mode-switch; "
                  "menu leaves only if already open; chat body not recorded",
        "purpose": "B-line R5 precondition step 1: confirm controls + mode-state read on installed build",
        "target_title": data.get("target_title"),
        "target_url": data.get("target_url"),
        "controls": c,
        "state_metrics": sm,
        "findings": findings,
        "probe_interference": {
            "cursor_displacement": run.cursor_displacement,
            "unexpected_focus_switch": run.unexpected_focus_switch,
            "external_input_during_window": run.external_input_during_window,
            "event_hook_active": run.event_hook_active,
        },
        "not_measured": "send_task send-click risk (requires authorized live write, R5)",
    }
    (out_dir / "trae_controls_exist.json").write_text(
        json.dumps(rx.jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"browser/product: {version.get('Browser')!r} / {version.get('Product')!r}")
    print(f"send_button: present={findings['send_button_present']} disabled={findings['send_button_disabled']}")
    print(f"approval_trigger: present={findings['approval_trigger_present']} label={findings['approval_label']!r} "
          f"(aria_auto={findings['approval_by_aria_auto_present']} aria_manual={findings['approval_by_aria_manual_present']} "
          f"class={findings['approval_by_class_present']})")
    print(f"mode_entry: present={findings['mode_entry_present']} mode_name={findings['mode_name']!r} "
          f"state_mode_name={findings['state_mode_name']!r}")
    print(f"popup_menu: open={findings['popup_menu_open']} leaves={findings['popup_menu_leaves']}")
    print(f"ide_tab={findings['ide_tab_present']} chat_root={findings['chat_root_present']} "
          f"composer={findings['composer_present']} new_session={findings['new_session_present']}")
    print(f"probe_interference: cursor={run.cursor_displacement} focus_switch={run.unexpected_focus_switch} "
          f"ext={run.external_input_during_window}")
    print(f"WROTE {out_dir / 'trae_controls_exist.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())