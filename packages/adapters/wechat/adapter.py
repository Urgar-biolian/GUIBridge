"""WeChat adapter: message-oriented foreground OCR + clipboard send with productized gates.

Unlike the task-oriented Trae adapter (AppAdapter.send_task -> TaskRecord), WeChat is
message-oriented: send_message(target, text, approve) -> four-state ActionResult.

WeChat 4.x has NO background semantic channel (measured E10: the MMUIRenderSubWindowHW
chat surface is fully self-drawn with zero UIA semantic nodes; hidden-desktop isolation
reaches only a login QR window, not the logged-in session — E12). The only verified path
is FOREGROUND OCR locate + clipboard paste + physical input, which moves the real cursor
and requires WeChat in the foreground. This adapter therefore declares PHYSICAL_INPUT and
classifies success as SUCCESS_WITH_INTERFERENCE; it never claims background or
zero-interference operation.

Safety gates (principles 3/6/7):
  * approve=False by default; a high-impact send raises approval_required BEFORE any
    window action. The adapter never auto-approves.
  * window whitelist: the driver only locates WeChat's Qt main + render child.
  * anti-mis-send: OCR-verify the right-panel title == target before staging or sending.
  * staged-text OCR re-check before send; fail-stop at any gate.
  * non-idempotent: a single attempt, UNCONFIRMED is never auto-retried.
  * FocusGuard wraps the send action; four-state via focusguard.classify.
  * privacy: OCR-derived evidence keeps only the target label and the user-authored test
    text; all other chat/contact text is redacted. Readable PNGs live outside the repo and
    are deleted right after OCR (driver).
  * leave-as-found: WeChat re-minimized and the original foreground restored in finally.

The capability-table change (wechat x send_message gaining a foreground_input channel)
is a PROPOSAL pending B-line review + owner approval; the frozen table is NOT modified here.
"""

from __future__ import annotations

import os
import tempfile
import time

from packages.focusguard.classify import classify
from packages.focusguard.outcome import ActionResult, ResultState
from packages.routing.capability import Channel, InterferenceRisk

from . import win32
from .driver import WeChatDriver, Win32WeChatDriver

CHANNEL = Channel.FOREGROUND_INPUT
RISK = InterferenceRisk.PHYSICAL_INPUT


class AdapterError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _center(box: dict) -> tuple[int, int]:
    x1, y1, x2, y2 = box["bounds"]
    return (x1 + x2) // 2, (y1 + y2) // 2


def _redact(box: dict, keep: bool) -> dict:
    return {"bounds": box["bounds"], "text": box["text"] if keep else "<redacted>"}


class WeChatAdapter:
    app = "wechat"

    def __init__(self, driver: WeChatDriver | None = None):
        self.driver = driver or Win32WeChatDriver()

    def probe_channels(self) -> dict[str, bool]:
        """Measured channel availability (E10/E10b/E11), not a live window probe.
        uia: zero semantic nodes on the chat surface (unavailable). ocr_vision:
        locate-only (never a write-execution channel, principle 3). foreground_input:
        the verified send path (PHYSICAL_INPUT)."""
        return {"uia": False, "ocr_vision": True, "foreground_input": True}

    def send_message(self, target: str, text: str, approve: bool = False) -> ActionResult:
        if not approve:
            raise AdapterError("approval_required",
                               "wechat send_message is high-impact; explicit per-send approval required")
        target = (target or "").strip()
        text = (text or "").strip()
        if not target or not text:
            raise AdapterError("invalid_argument", "target and text must be non-empty")

        tmp_dir = tempfile.mkdtemp(prefix="gb_wx_adapter_")
        ws = None
        run = None
        verified = False
        error: str | None = None
        evidence: dict = {"target": target, "channel": CHANNEL.value, "risk": RISK.value}
        try:
            ws = self.driver.locate()
            if ws is None:
                error = "wechat_window_not_found"
            else:
                evidence["restore"] = {"render_hwnd": ws["render_hwnd"], "rect": ws["rect"],
                                       "original_fg": ws["original_fg"]}
                if not self.driver.restore(ws):
                    error = "restore_did_not_surface"
                else:
                    ok, nav = self._navigate(ws, target, tmp_dir)
                    evidence.update(nav)
                    if not ok:
                        error = "navigate_gate_failed:" + nav.get("gate", "unknown")
                    else:
                        ok, stage = self._stage(ws, text, tmp_dir)
                        evidence.update(stage)
                        if not ok:
                            error = "stage_gate_failed:" + stage.get("gate", "unknown")
                        else:
                            run, verified, send_ev = self._send(ws, text, tmp_dir)
                            evidence.update(send_ev)
                            if run is None:
                                error = "send_failed:" + send_ev.get("send_error", "unknown")

            if run is not None:
                state = classify(run, verified, error, CHANNEL)
            else:
                state = ResultState.FAILED if error else ResultState.UNCONFIRMED
            return ActionResult(
                state=state, channel=CHANNEL, risk=RISK, effect_verified=verified,
                evidence=evidence,
                focus_before=run.before if run else None,
                focus_after=run.after if run else None,
                unexpected_focus_switch=run.unexpected_focus_switch if run else False,
            )
        finally:
            if ws is not None:
                try:
                    evidence["cleanup"] = self.driver.cleanup(ws)
                except Exception as exc:  # noqa: BLE001
                    evidence["cleanup"] = {"error": repr(exc)}
            try:
                os.rmdir(tmp_dir)
            except OSError:
                pass

    # -- gates ----------------------------------------------------------
    def _navigate(self, ws: dict, target: str, tmp_dir: str) -> tuple[bool, dict]:
        ev: dict = {}
        boxes = self.driver.read_boxes(ws, tmp_dir)
        search = [b for b in boxes if "搜索" in b["text"]]
        if search:
            self.driver.click_rel(ws, *_center(search[0]))
        else:
            self.driver.combo(win32.VK_F)
        time.sleep(0.6)
        self.driver.clipboard_write(target)
        self.driver.combo(win32.VK_V)
        time.sleep(1.2)
        boxes = self.driver.read_boxes(ws, tmp_dir)
        hits = [b for b in boxes if target in b["text"]]
        ev["search_target_hits"] = [_redact(b, b["text"].strip() == target) for b in hits]
        # Clean exact-match contact rows below the search-input echo; topmost first.
        # Excludes 聊天记录 rows (private contact names) and the bottom 搜一搜 footer.
        rows = [b for b in hits if b["text"].strip() == target and b["bounds"][1] > 100]
        rows.sort(key=lambda b: b["bounds"][1])
        if not rows:
            ev["gate"] = "no_search_result_row"
            return False, ev
        self.driver.click_rel(ws, *_center(rows[0]))
        time.sleep(1.2)
        boxes = self.driver.read_boxes(ws, tmp_dir)
        title = [b for b in boxes if b["bounds"][3] < 90 and b["bounds"][0] > 340]
        ev["title_region"] = [_redact(b, target in b["text"]) for b in title]
        verified = any(target in b["text"] for b in title)
        ev["title_verified_target"] = verified
        if not verified:
            ev["gate"] = "title_not_target"
            return False, ev
        return True, ev

    def _stage(self, ws: dict, text: str, tmp_dir: str) -> tuple[bool, dict]:
        ev: dict = {}
        _, _, rw, rh = ws["rect"]
        self.driver.click_rel(ws, int(rw * 0.55), rh - 75)
        time.sleep(0.4)
        self.driver.combo(win32.VK_A)
        self.driver.key(win32.VK_DELETE)
        self.driver.key(win32.VK_DELETE, up=True)
        self.driver.clipboard_write(text)
        self.driver.combo(win32.VK_V)
        time.sleep(0.8)
        boxes = self.driver.read_boxes(ws, tmp_dir)
        staged = [b for b in boxes if text[:8] in b["text"]]
        ev["staged_hits"] = [{"bounds": b["bounds"], "text": b["text"]} for b in staged]
        ev["text_staged_verified"] = bool(staged)
        if not staged:
            ev["gate"] = "text_not_staged"
            return False, ev
        return True, ev

    def _send(self, ws: dict, text: str, tmp_dir: str):
        guard = self.driver.guard(ws)

        def action():
            boxes = self.driver.read_boxes(ws, tmp_dir)
            send = [b for b in boxes if "发送" in b["text"]]
            if not send:
                raise RuntimeError("send button not located")
            self.driver.click_rel(ws, *_center(send[0]))
            time.sleep(1.0)
            after = self.driver.read_boxes(ws, tmp_dir)
            bubble = [b for b in after if text[:8] in b["text"]]
            return {"send_button": send[0]["bounds"], "bubble_verified": bool(bubble),
                    "bubble_hits": [{"bounds": b["bounds"], "text": b["text"]} for b in bubble]}

        try:
            run = guard.wrap_with_events(action)
        except Exception as exc:  # noqa: BLE001
            return None, False, {"send_error": repr(exc)}
        res = run.result
        verified = bool(res.get("bubble_verified"))
        ev = {"send": res, "effect_verified": verified,
              "send_interference": {
                  "cursor_displacement": run.cursor_displacement,
                  "unexpected_focus_switch": run.unexpected_focus_switch,
                  "external_input_during_window": run.external_input_during_window,
                  "event_hook_active": run.event_hook_active}}
        return run, verified, ev