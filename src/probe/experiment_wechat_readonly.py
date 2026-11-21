"""E10 WeChat read-only observation: NO launch, NO send, NO click, NO mode switch.

WeChat 4.x (Weixin) is single-instance and already logged in; launching it would only
signal the running instance to pop its window on the HOST desktop (interference), and a
clean isolated instance would require killing the user's session (not allowed). So this
probe does NOT launch anything. It passively observes the ALREADY-RUNNING WeChat:

  * WeChat's real content surface is the self-drawn MMUIRenderSubWindowHW render child
    (the Qt51514QWindowIcon top-level titled "微信" is a tiny OFF-SCREEN helper window,
    not the chat UI). The probe locates the render surface and measures it.
  * UIA semantic tree STRUCTURE only (ControlTypeName + ClassName + counts). Name/text
    values are deliberately NOT collected to avoid logging private chat/contact content.
  * PrintWindow capture feasibility as PIXEL STATISTICS only (distinct colours / blank
    detection). No readable image is saved or displayed.
  * FocusGuard wraps the passive read to confirm host foreground/cursor are untouched.

Read-only, non-destructive: WeChat is left exactly as-is (no foreground change). Raw JSON
-> var/experiments/<run_id>/wechat_readonly.json (gitignored). No frozen contract change.
"""

from __future__ import annotations

import ctypes
import datetime
import json
import sys
import traceback
from ctypes import wintypes
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PROBE_DIR = Path(__file__).parent
if str(PROBE_DIR) not in sys.path:
    sys.path.insert(0, str(PROBE_DIR))

import uiautomation as auto  # noqa: E402

import experiment_hidden_desktop as e8  # noqa: E402
import win32_helpers as wh  # noqa: E402
from packages.focusguard.monitor import Win32FocusGuard  # noqa: E402

RUNS = ROOT / "var" / "experiments"
user32 = wh.user32
kernel32 = wh.kernel32

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
ENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumChildWindows.argtypes = [wintypes.HWND, ENUMPROC, wintypes.LPARAM]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


def _process_image(pid: int) -> str:
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return ""
    buf = ctypes.create_unicode_buffer(1024)
    size = wintypes.DWORD(1024)
    ok = kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
    kernel32.CloseHandle(h)
    return Path(buf.value).name.lower() if ok else ""


def _rect(hwnd: int) -> tuple:
    x, y, w, h = wh.window_rect(hwnd)
    return {"x": x, "y": y, "w": w, "h": h, "area": max(w, 0) * max(h, 0),
            "off_screen": x < -10000 or y < -10000}


def collect_wechat() -> dict:
    tops = []
    pids = set()
    for w in wh.enum_top_level_windows():
        img = _process_image(w["pid"])
        if img in ("weixin.exe", "wechat.exe"):
            pids.add(w["pid"])
            tops.append({"hwnd": w["hwnd"], "pid": w["pid"], "class": w["class"],
                         "visible": w["visible"], "title_len": len(w["title"]),
                         "process_image": img, "rect": _rect(w["hwnd"])})
    renders = []
    for t in tops:
        def cb(h, _lp, parent=t["hwnd"]):
            cl = wh.window_class(int(h))
            if "mmuirender" in cl.lower():
                renders.append({"hwnd": int(h), "class": cl, "parent_hwnd": parent,
                                "rect": _rect(int(h))})
            return True
        user32.EnumChildWindows(wintypes.HWND(int(t["hwnd"])), ENUMPROC(cb), 0)
    return {"pids": sorted(pids), "top_level": tops, "render_windows": renders}


def uia_structure(hwnd: int) -> dict:
    """Structural UIA summary. Name/text values are NOT collected (privacy)."""
    try:
        window = auto.ControlFromHandle(hwnd)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": repr(exc)}
    nodes: list[tuple] = []

    def walk(control, depth):
        if depth > 5:
            return
        try:
            children = control.GetChildren()
        except Exception:  # noqa: BLE001
            return
        for child in children:
            try:
                nodes.append((child.ControlTypeName, child.ClassName))
            except Exception:  # noqa: BLE001
                pass
            walk(child, depth + 1)

    try:
        walk(window, 0)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "error": repr(exc), "partial_nodes": len(nodes)}
    roles = [n[0] for n in nodes]
    classes = [n[1] for n in nodes]
    return {
        "available": True, "node_count": len(nodes),
        "has_edit": any("Edit" in r for r in roles),
        "has_button": any("Button" in r for r in roles),
        "has_document": any("Document" in r for r in roles),
        "has_list": any("List" in r for r in roles),
        "role_counts": {r: roles.count(r) for r in sorted(set(roles))},
        "class_sample": sorted(set(classes))[:20],
        "name_values_collected": False,
    }


def capture_stats(hwnd: int) -> dict:
    cap = e8._capture_feasibility(hwnd)
    return {"printwindow_return": cap["printwindow_return"], "window_wh": cap["window_wh"],
            "non_blank_distinct_colors": cap["non_blank_distinct_colors"],
            "capture_ok": cap["capture_ok"], "image_saved": False,
            "note": "pixel statistics only; readable chat content deliberately not captured"}


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results = {"run_id": run_id, "mode": "read_only_no_launch_no_send"}
    info = collect_wechat()
    results["wechat_pids"] = info["pids"]
    results["top_level_windows"] = info["top_level"]
    results["render_windows"] = info["render_windows"]
    if not info["pids"]:
        results["verdict"] = "wechat_not_running"
    else:
        # Prefer the largest MMUIRenderSubWindowHW render surface (the real content);
        # fall back to the largest on-screen top-level window.
        target = None
        if info["render_windows"]:
            target = max(info["render_windows"], key=lambda r: r["rect"]["area"])
            target_kind = "render_surface"
        else:
            onscreen = [t for t in info["top_level"] if not t["rect"]["off_screen"]]
            if onscreen:
                target = max(onscreen, key=lambda t: t["rect"]["area"])
                target_kind = "top_level"
        if target is None:
            results["verdict"] = "no_measurable_wechat_window"
        else:
            hwnd = target["hwnd"]
            results["target"] = {**target, "kind": target_kind}
            fg = int(user32.GetForegroundWindow() or 0)
            guard = Win32FocusGuard(fg)  # measure host; do NOT change foreground

            def passive_read():
                results["uia"] = uia_structure(hwnd)
                results["capture"] = capture_stats(hwnd)

            try:
                run = guard.wrap_with_events(passive_read)
                results["host_interference"] = {
                    "cursor_displacement": run.cursor_displacement,
                    "unexpected_focus_switch": run.unexpected_focus_switch,
                    "external_input_during_window": run.external_input_during_window,
                    "event_hook_active": run.event_hook_active,
                    "host_focus_before": run.before.foreground_hwnd,
                    "host_focus_after": run.after.foreground_hwnd,
                }
                results["verdict"] = "read_only_observed"
            except Exception as exc:  # noqa: BLE001
                results["error"] = repr(exc)
                results["traceback"] = traceback.format_exc()

    output = run_dir / "wechat_readonly.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    summary = {
        "run_id": run_id, "output": str(output), "verdict": results.get("verdict"),
        "wechat_pids": results.get("wechat_pids"),
        "target": results.get("target"),
        "render_window_count": len(results.get("render_windows", [])),
        "uia_available": results.get("uia", {}).get("available"),
        "uia_nodes": results.get("uia", {}).get("node_count"),
        "uia_has_edit": results.get("uia", {}).get("has_edit"),
        "uia_has_button": results.get("uia", {}).get("has_button"),
        "uia_role_counts": results.get("uia", {}).get("role_counts"),
        "capture_ok": results.get("capture", {}).get("capture_ok"),
        "capture_wh": results.get("capture", {}).get("window_wh"),
        "capture_distinct_colors": results.get("capture", {}).get("non_blank_distinct_colors"),
        "host_focus_switch": results.get("host_interference", {}).get("unexpected_focus_switch"),
        "host_cursor": results.get("host_interference", {}).get("cursor_displacement"),
        "error": results.get("error"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())