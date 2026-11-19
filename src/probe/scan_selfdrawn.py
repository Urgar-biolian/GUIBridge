"""Capability scan of a self-drawn target vs the native standard-control target.

Models the third app category (custom-rendered / self-drawn UI): a window that
paints its own controls with GDI and exposes no child HWND controls. Records
whether the UIA tree carries any Edit/Button semantic nodes or Invoke/Value/
Toggle patterns, contrasted against native_test_app (which does). This is the
reproducible negative evidence for "self-drawn apps do not support background
semantic operation; OCR/vision is locate-only". Controlled local targets only;
read-only UIA scan, no messages sent to user apps. Writes
var/experiments/<run_id>/selfdrawn_scan.json.
"""

from __future__ import annotations

import datetime
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in (str(ROOT), str(Path(__file__).parent)):
    if p not in sys.path:
        sys.path.insert(0, p)

import uiautomation as auto  # noqa: E402

import uia_exec as ux  # noqa: E402
import run_experiments as rx  # noqa: E402

SELFDRAWN_TITLE = "GUIBridge SelfDrawn Target"
SELFDRAWN_CLASS = "GUIBridgeSelfDrawnWindow"


def scan_tree(control) -> dict:
    nodes: list[str] = []
    types: dict[str, int] = {}
    patterns = {"invoke": 0, "value": 0, "toggle": 0}
    buttons: list[dict] = []
    pids = {
        "invoke": auto.PatternId.InvokePattern,
        "value": auto.PatternId.ValuePattern,
        "toggle": auto.PatternId.TogglePattern,
    }

    def walk(ctrl, depth, parent_type):
        if len(nodes) >= 400 or depth > 6:
            return
        try:
            name = ctrl.ControlTypeName
            nodes.append(name)
            types[name] = types.get(name, 0) + 1
            if name == "ButtonControl":
                try:
                    label = ctrl.Name
                except Exception:
                    label = ""
                buttons.append({"name": label, "parent_type": parent_type})
            for key, pid in pids.items():
                try:
                    if ctrl.GetPattern(pid) is not None:
                        patterns[key] += 1
                except Exception:
                    pass
            for child in ctrl.GetChildren():
                walk(child, depth + 1, name)
        except Exception:
            return

    walk(control, 0, "")
    # Non-client caption buttons (minimize/maximize/close) live under TitleBar;
    # they are window-frame chrome, not app content. A self-drawn app's painted
    # client controls should expose no Edit and no content-area Button.
    content_buttons = [b for b in buttons if b["parent_type"] != "TitleBarControl"]
    return {
        "node_count": len(nodes),
        "types": types,
        "has_edit": "EditControl" in types,
        "has_button": "ButtonControl" in types,
        "buttons": buttons,
        "content_button_count": len(content_buttons),
        "pattern_nodes": patterns,
    }


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = rx.RUNS / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    selfdrawn_proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("selfdrawn_app.py")),
         "--x", "220", "--y", "180", "--auto-close-seconds", "120"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    native_proc = rx.start_app(x=700, y=180, auto_close=120)
    try:
        sd = ux.find_window(SELFDRAWN_TITLE, SELFDRAWN_CLASS, timeout=8)
        nt = ux.find_window(rx.TARGET_TITLE, rx.TARGET_CLASS, timeout=8)
        if sd is None or nt is None:
            print("ABORT: selfdrawn/native window not found")
            return 2
        sd_scan = scan_tree(sd)
        nt_scan = scan_tree(nt)
        sd_scan["hwnd"] = int(sd.NativeWindowHandle)
        nt_scan["hwnd"] = int(nt.NativeWindowHandle)

        negative_ok = (not sd_scan["has_edit"] and sd_scan["content_button_count"] == 0)
        contrast_ok = nt_scan["has_edit"] and nt_scan["content_button_count"] > 0
        result = {
            "run_id": run_id,
            "env": {
                "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
                "git_head": rx.subprocess.run(
                    ["git", "rev-parse", "HEAD"], cwd=rx.ROOT, capture_output=True, text=True
                ).stdout.strip(),
            },
            "purpose": "self-drawn app UIA negative evidence vs native standard-control target",
            "selfdrawn": sd_scan,
            "native": nt_scan,
            "selfdrawn_no_content_semantics": negative_ok,
            "native_has_content_semantics": contrast_ok,
            "note": (
                "self-drawn window still exposes non-client caption buttons (minimize/maximize/close) "
                "under TitleBar as ButtonControl+Invoke; these are window-frame chrome, not app content. "
                "The painted client button/edit expose no EditControl and no content-area Button."
            ),
            "conclusion": (
                "self-drawn client content exposes no Edit/Button UIA semantics; background semantic "
                "operation on app content unavailable, OCR/vision locate-only (frame chrome buttons remain)"
                if negative_ok else "unexpected: self-drawn window exposed content semantic nodes"
            ),
        }
        (out_dir / "selfdrawn_scan.json").write_text(
            json.dumps(rx.jsonable(result), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"selfdrawn: nodes={sd_scan['node_count']} has_edit={sd_scan['has_edit']} content_buttons={sd_scan['content_button_count']} buttons={sd_scan['buttons']}")
        print(f"native:    nodes={nt_scan['node_count']} has_edit={nt_scan['has_edit']} content_buttons={nt_scan['content_button_count']}")
        print(f"WROTE {out_dir / 'selfdrawn_scan.json'} negative_ok={negative_ok} contrast_ok={contrast_ok}")
        return 0 if (negative_ok and contrast_ok) else 1
    finally:
        selfdrawn_proc.terminate()
        native_proc.terminate()


if __name__ == "__main__":
    raise SystemExit(main())