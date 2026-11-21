"""E10b WeChat VISIBLE-capture verification: one authorized foreground restore, read-only.

Closes the E10 gap "full-chat capture NOT validated (WeChat was minimized -> render
surface blank)". With explicit user authorization, this probe restores the running
WeChat to the foreground ONCE, confirms the MMUIRenderSubWindowHW render surface is
now on-screen and visible, then measures:

  * PrintWindow pixel statistics (distinct colours / blank detection) on the VISIBLE
    render surface — is the self-drawn chat content actually paintable/capturable?
  * mss screen grab of the render region + RapidOCR locate-only inference — how many
    text boxes can OCR locate? (locate feasibility, NOT a write channel)
  * FocusGuard around the passive read (WeChat already foreground) — cursor / focus.

STRICTLY READ-ONLY apart from the one authorized restore: NO send, NO click on send,
NO mode switch, NO message injection. The restore itself is a DECLARED, authorized
foreground switch (recorded honestly, not claimed as zero-interference).

PRIVACY: the readable PNG is grabbed to a TEMP dir OUTSIDE the repo and DELETED right
after OCR; only redacted statistics (box count / bounds / confidence / locate-only)
are recorded — recognized chat/contact TEXT is never logged, saved, or displayed.
After measuring, WeChat is re-minimized and the host foreground is returned to the
user's original window (leave-as-found). Raw JSON -> var/experiments/<run_id>/
(gitignored). No frozen contract change.
"""

from __future__ import annotations

import datetime
import json
import os
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for _p in (str(ROOT), str(ROOT / "packages"), str(Path(__file__).parent)):
    if _p not in sys.path:
        sys.path.insert(0, _p)
PROBE_DIR = Path(__file__).parent

import experiment_hidden_desktop as e8  # noqa: E402
import experiment_wechat_readonly as e10  # noqa: E402
import win32_helpers as wh  # noqa: E402
from packages.focusguard.monitor import Win32FocusGuard  # noqa: E402
from packages.perception.ocr import (  # noqa: E402
    OcrUnavailable,
    OCRChannel,
    elements_from_ocr,
    grab_window_png,
)

RUNS = ROOT / "var" / "experiments"
user32 = wh.user32
SW_RESTORE = 9
SW_MINIMIZE = 6


def _render_state(hwnd: int) -> dict:
    x, y, w, h = wh.window_rect(hwnd)
    return {"hwnd": hwnd, "x": x, "y": y, "w": w, "h": h,
            "visible": bool(user32.IsWindowVisible(hwnd)),
            "off_screen": x < -10000 or y < -10000,
            "on_screen_visible": (x >= -10000 and y >= -10000 and w > 1 and h > 1
                                  and bool(user32.IsWindowVisible(hwnd)))}


def _largest_render(info: dict) -> dict | None:
    if not info["render_windows"]:
        return None
    return max(info["render_windows"], key=lambda r: r["rect"]["area"])


def _ocr_redacted(png: str, window_id: str, ocr: OCRChannel) -> dict:
    """Run OCR, return ONLY redacted locate statistics; never log recognized text."""
    boxes = ocr.read_text_boxes(png)
    elements = elements_from_ocr(boxes, window_id)
    locate_only = all(e.actions == [] and e.role == "text" for e in elements)
    return {
        "text_box_count": len(boxes),
        "element_count": len(elements),
        "locate_only_no_actions": locate_only,
        "all_source_ocr": all(e.source == ["ocr"] for e in elements),
        "bounds": [list(b["bounds"]) for b in boxes],
        "confidence": [round(b["confidence"], 3) for b in boxes],
        "text_redacted": True,
    }


def main() -> int:
    run_id = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = RUNS / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results = {"run_id": run_id, "mode": "one_authorized_restore_then_read_only"}
    tmp_dir = tempfile.mkdtemp(prefix="gb_wechat_")  # OUTSIDE repo; readable PNG lives here briefly
    ocr = OCRChannel()
    restore_hwnd = 0
    original_fg = int(user32.GetForegroundWindow() or 0)
    try:
        info = e10.collect_wechat()
        results["wechat_pids"] = info["pids"]
        if not info["pids"]:
            results["verdict"] = "wechat_not_running"
        else:
            render = _largest_render(info)
            if render is None:
                results["verdict"] = "no_render_surface"
            else:
                render_hwnd = render["hwnd"]
                restore_hwnd = render["parent_hwnd"]
                results["render_before"] = _render_state(render_hwnd)
                results["restore_target_hwnd"] = restore_hwnd
                results["host_foreground_before_restore"] = original_fg

                # ONE authorized foreground restore (declared interference, not zero).
                user32.ShowWindow(restore_hwnd, SW_RESTORE)
                wh.ensure_foreground(restore_hwnd)
                time.sleep(1.2)
                info2 = e10.collect_wechat()
                render2 = _largest_render(info2) or render
                render_hwnd = render2["hwnd"]
                after = _render_state(render_hwnd)
                results["render_after_restore"] = after
                results["host_foreground_after_restore"] = int(user32.GetForegroundWindow() or 0)
                results["restore_foreground_switch"] = (
                    results["host_foreground_after_restore"] != original_fg
                )
                results["restore_success"] = after["on_screen_visible"]

                if not after["on_screen_visible"]:
                    results["verdict"] = "restore_did_not_surface_render"
                else:
                    window_id = format(render_hwnd, "x")
                    guard = Win32FocusGuard(render_hwnd)

                    def passive_read():
                        cap = e10.capture_stats(render_hwnd)
                        png = grab_window_png(window_id, out_dir=tmp_dir)
                        try:
                            stats = _ocr_redacted(png, window_id, ocr)
                        finally:
                            try:
                                os.remove(png)  # delete readable chat image immediately
                            except OSError:
                                pass
                        return {"printwindow": cap, "ocr_locate": stats}

                    try:
                        run = guard.wrap_with_events(passive_read)
                        res = run.result
                        results["printwindow_visible"] = res["printwindow"]
                        results["ocr_locate_visible"] = res["ocr_locate"]
                        results["read_interference"] = {
                            "cursor_displacement": run.cursor_displacement,
                            "unexpected_focus_switch": run.unexpected_focus_switch,
                            "external_input_during_window": run.external_input_during_window,
                            "event_hook_active": run.event_hook_active,
                            "focus_before": run.before.foreground_hwnd,
                            "focus_after": run.after.foreground_hwnd,
                        }
                        results["verdict"] = "visible_capture_observed"
                    except OcrUnavailable as exc:
                        results["ocr_unavailable"] = repr(exc)
                        results["verdict"] = "ocr_dependency_unavailable"
                    except Exception as exc:  # noqa: BLE001
                        results["error"] = repr(exc)
                        results["traceback"] = traceback.format_exc()
    except Exception as exc:  # noqa: BLE001
        results["error"] = repr(exc)
        results["traceback"] = traceback.format_exc()
    finally:
        # Leave-as-found: re-minimize WeChat, return host foreground to the user's window.
        cleanup = {}
        if restore_hwnd:
            try:
                user32.ShowWindow(restore_hwnd, SW_MINIMIZE)
                time.sleep(0.4)
                if original_fg and user32.IsWindowVisible(original_fg):
                    wh.ensure_foreground(original_fg)
                cleanup["reminimized"] = True
                cleanup["host_foreground_returned_to"] = int(user32.GetForegroundWindow() or 0)
                cleanup["render_state_after_cleanup"] = _render_state(
                    results.get("render_after_restore", {}).get("hwnd", restore_hwnd)
                )
            except Exception as exc:  # noqa: BLE001
                cleanup["error"] = repr(exc)
        results["cleanup"] = cleanup
        try:
            os.rmdir(tmp_dir)
        except OSError:
            pass

    output = run_dir / "wechat_visible.json"
    output.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    pw = results.get("printwindow_visible", {})
    oc = results.get("ocr_locate_visible", {})
    summary = {
        "run_id": run_id, "output": str(output), "verdict": results.get("verdict"),
        "render_before_off_screen": results.get("render_before", {}).get("off_screen"),
        "restore_success": results.get("restore_success"),
        "render_after_on_screen_visible": results.get("render_after_restore", {}).get("on_screen_visible"),
        "restore_foreground_switch_authorized": results.get("restore_foreground_switch"),
        "printwindow_capture_ok": pw.get("capture_ok"),
        "printwindow_distinct_colors": pw.get("non_blank_distinct_colors"),
        "printwindow_wh": pw.get("window_wh"),
        "ocr_text_box_count": oc.get("text_box_count"),
        "ocr_locate_only": oc.get("locate_only_no_actions"),
        "ocr_text_redacted": oc.get("text_redacted"),
        "read_cursor": results.get("read_interference", {}).get("cursor_displacement"),
        "read_focus_switch": results.get("read_interference", {}).get("unexpected_focus_switch"),
        "cleanup_reminimized": results.get("cleanup", {}).get("reminimized"),
        "cleanup_foreground_returned_to": results.get("cleanup", {}).get("host_foreground_returned_to"),
        "error": results.get("error"),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())