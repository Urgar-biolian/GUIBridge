"""Trae adapter: IDE-mode precondition, manual approval default, submit->status->read state machine.

All DOM work goes through the page target over loopback CDP (PROBE_REPORT F1-F6). No coordinate
caching: every send re-checks selectors and preconditions. Mode menu items are matched by exact
leaf text, never the ChatAgent wrapper.
"""

from __future__ import annotations

import asyncio
import time
import uuid

from adapters.base import AppAdapter
from adapters.trae.states import detect_state, has_approval_prompt, has_running_signal
from events.store import utcnow
from perception.cdp import CDPChannel, list_targets
from semantic.element import TaskRecord

COMPOSER = ".chat-input-v2-input-box-editable"
SEND = ".chat-input-v2-send-button"
NEW_SESSION = "[data-testid=ai-chat-create-new-session]"
CHAT_ROOT = ".ai-chat-v2-ide-root"
MODE_BTN = ".v2-agent-entry-btn"
MODE_NAME = ".v2-agent-entry-btn__name"
APPROVAL_TRIGGER = "[class*=permissionModeTrigger]"
IDE_TAB = ".icube-mode-tab-item-ide"

MODE_LEAF = {
    "chat": r"^(Chat|Ask|对话|问答)$",
    "agent": r"^(Agent|智能体)$",
}

STATE_EXPR = r"""(() => {
  const root = document.querySelector('.ai-chat-v2-ide-root');
  const send = document.querySelector('.chat-input-v2-send-button');
  const stop = [...document.querySelectorAll('button')].find(b =>
    /stop|停止/i.test(String(b.className || '') + ' ' + (b.getAttribute('aria-label') || '')));
  const mode = document.querySelector('.v2-agent-entry-btn__name');
  const trigger = document.querySelector('[class*=permissionModeTrigger]');
  return JSON.stringify({
    hasRoot: !!root,
    hasComposer: !!document.querySelector('.chat-input-v2-input-box-editable'),
    text: root ? root.innerText.slice(0, 20000) : '',
    sendDisabled: send ? /(^|\s)disabled(\s|$)/.test(String(send.className || '')) : null,
    stopControl: !!stop,
    modeName: mode ? mode.textContent.trim() : null,
    approvalLabel: trigger ? (trigger.getAttribute('aria-label') || trigger.textContent || '').trim() : null
  });
})()"""


class AdapterError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _js(selector: str) -> str:
    import json
    return json.dumps(selector, ensure_ascii=False)


def extract_last_reply(chat_text: str, submitted_text: str) -> str:
    text = (chat_text or "").strip()
    marker = (submitted_text or "").strip()
    if marker:
        idx = text.rfind(marker)
        if idx >= 0:
            return text[idx + len(marker):].strip()
    return text


class TraeAdapter(AppAdapter):
    app = "trae"

    def __init__(self, port: int, store, allow_auto_approval: bool = False):
        self.port = port
        self.store = store
        self.allow_auto_approval = allow_auto_approval

    # -- plumbing -------------------------------------------------------
    def _run(self, coro):
        return asyncio.run(coro)

    async def _target(self):
        try:
            targets = list_targets(self.port)
        except Exception as e:
            raise AdapterError("locator_missing", f"CDP unreachable on {self.port}: {e}") from e
        pages = [t for t in targets if t.type == "page"]
        trae = [t for t in pages if "trae" in (t.title + t.url).lower()]
        if not trae:
            raise AdapterError("locator_missing", "no Trae page target")
        return trae[0]

    async def _with_channel(self, action):
        target = await self._target()
        ch = CDPChannel(self.port)
        await ch.connect(target.ws_url)
        try:
            return await action(ch)
        finally:
            await ch.close()

    async def _state(self, ch) -> dict:
        state = await ch.evaluate_json(STATE_EXPR)
        return state or {}

    async def _eval(self, ch, expression: str):
        return await ch.evaluate_json(expression)

    async def _poll(self, ch, predicate, timeout: float = 3.0, interval: float = 0.15):
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            state = await self._state(ch)
            if predicate(state):
                return state
            await asyncio.sleep(interval)
        return await self._state(ch)

    # -- preconditions --------------------------------------------------
    async def _ensure_ide_mode(self, ch) -> None:
        result = await self._eval(ch, r"""(() => {
          const tab = document.querySelector('.icube-mode-tab-item-ide');
          if (!tab) return 'NO_TAB';
          if (document.querySelector('.ai-chat-v2-ide-root')) return 'ide';
          let p = tab;
          for (let i = 0; i < 6 && p; i++) {
            if (/switch|segment|tab|mode|toggle/i.test(String(p.className || ''))) {
              p.click(); return 'switched';
            }
            p = p.parentElement;
          }
          tab.click(); return 'clicked';
        })()""")
        if result == "NO_TAB":
            raise AdapterError("locator_missing", "IDE mode tab not found")
        state = await self._poll(ch, lambda s: s.get("hasRoot"))
        if not state.get("hasRoot"):
            raise AdapterError("locator_missing", "IDE chat root not visible after mode switch")

    async def _ensure_chat_mode(self, ch, mode: str) -> str:
        import json
        import re
        pattern = MODE_LEAF[mode]
        opened = await self._eval(ch, f"""(() => {{
          if (document.querySelector('.popup-menu')) return 'already';
          const btn = document.querySelector({_js(MODE_BTN)});
          if (!btn) return 'NO_BTN';
          btn.click(); return 'opened';
        }})()""")
        if opened == "NO_BTN":
            raise AdapterError("locator_missing", "mode entry button not found")
        picked = None
        names = []
        deadline = asyncio.get_running_loop().time() + 2.0
        while asyncio.get_running_loop().time() < deadline:
            raw = await self._eval(ch, f"""(() => {{
              const pop = document.querySelector('.popup-menu');
              if (!pop) return JSON.stringify({{picked: null, names: []}});
              const items = [...pop.querySelectorAll('.popup-menu-item')].filter(el =>
                el.getBoundingClientRect().height > 0);
              const names = [...new Set(items.map(el => (el.innerText || '').trim().slice(0, 30)))];
              const re = new RegExp({_js(pattern)}, 'i');
              const hits = items.filter(el => re.test((el.innerText || '').trim()));
              if (hits.length === 1) {{
                const rc = hits[0].getBoundingClientRect();
                return JSON.stringify({{picked: (hits[0].innerText || '').trim().slice(0, 30),
                  x: rc.x + rc.width / 2, y: rc.y + rc.height / 2, names}});
              }}
              return JSON.stringify({{picked: null, names, hits: hits.length}});
            }})()""")
            data = json.loads(raw) if isinstance(raw, str) else (raw or {})
            names = data.get("names") or names
            if data.get("picked"):
                picked = data["picked"]
                await self._click_at(ch, data["x"], data["y"])
                break
            if data.get("hits", 0) > 1:
                raise AdapterError("conflict", f"ambiguous mode menu leaves: {names}")
            await asyncio.sleep(0.15)
        if not picked:
            raise AdapterError("conflict", f"mode {mode!r} option not found; menu={names}")
        expected = {"chat": re.compile(r"chat|ask|对话|问答", re.I),
                    "agent": re.compile(r"agent|智能体", re.I)}[mode]
        state = await self._poll(
            ch, lambda s: bool(expected.search(s.get("modeName") or "")), timeout=2.0)
        name = (state.get("modeName") or "").strip()
        if not name or not expected.search(name):
            raise AdapterError("conflict", f"mode switch did not stick: {name!r}")
        return name or picked

    async def _click_at(self, ch, x: float, y: float) -> None:
        for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
            params = {"type": kind, "x": x, "y": y}
            if kind != "mouseMoved":
                params.update(button="left", clickCount=1)
            await ch._request("Input.dispatchMouseEvent", params)
            await asyncio.sleep(0.05)

    async def _force_manual_approval(self, ch) -> str:
        """Best-effort switch to manual approval.

        Verified 2026-11-17 (F10): the permissionModeTrigger button opens no observable menu via
        CDP JS click or trusted mouse events on 3.6.13. Agent mode therefore requires a human to
        have set manual approval beforehand; this method never enables auto approval.
        """
        import json
        raw = await self._eval(ch, r"""(() => {
          const trigger = document.querySelector("button[aria-label='自动审批']") ||
                          document.querySelector('[class*=permissionModeTrigger]');
          if (!trigger) return 'absent';
          const label = (trigger.getAttribute('aria-label') || trigger.textContent || '').trim();
          if (/手动|manual/i.test(label)) return JSON.stringify({status: 'manual', label});
          const rc = trigger.getBoundingClientRect();
          return JSON.stringify({status: 'clicked', label,
                                 x: rc.x + rc.width / 2, y: rc.y + rc.height / 2});
        })()""")
        data = json.loads(raw) if isinstance(raw, str) else {"status": raw}
        if data.get("status") in ("absent", "manual"):
            return data["status"]
        if "x" in data:
            await self._click_at(ch, data["x"], data["y"])
        else:
            await self._eval(ch, r"""(() => {
              const t = document.querySelector("button[aria-label='自动审批']") ||
                        document.querySelector('[class*=permissionModeTrigger]');
              if (t) t.click();
            })()""")
        for _ in range(8):
            await asyncio.sleep(0.2)
            picked = await self._eval(ch, r"""(() => {
              const pop = document.querySelector('.popup-menu');
              if (!pop) return 'no_menu';
              const items = [...pop.querySelectorAll('.popup-menu-item')].filter(el =>
                el.getBoundingClientRect().height > 0 && /手动|manual/i.test((el.innerText || '').trim()));
              if (items.length === 1) {
                const rc = items[0].getBoundingClientRect();
                return JSON.stringify({status: 'hit', x: rc.x + rc.width / 2, y: rc.y + rc.height / 2});
              }
              return items.length === 0 ? 'no_option' : 'ambiguous';
            })()""")
            if isinstance(picked, dict) and picked.get("status") == "hit":
                await self._click_at(ch, picked["x"], picked["y"])
                state = await self._poll(
                    ch, lambda s: "手动" in (s.get("approvalLabel") or "") or
                    "manual" in (s.get("approvalLabel") or "").lower(), timeout=1.5)
                label = state.get("approvalLabel") or ""
                return "manual" if ("手动" in label or "manual" in label.lower()) else f"unverified:{label}"
            if picked == "ambiguous":
                return "unverified:ambiguous_options"
            if picked == "no_option":
                return "unverified:no_option"
        return "unverified:no_menu"

    # -- AppAdapter API -------------------------------------------------
    def probe_channels(self) -> dict[str, bool]:
        async def _probe(ch):
            state = await self._state(ch)
            return {"cdp": bool(state.get("hasRoot")), "uia": False, "ocr": False}

        try:
            return self._run(self._with_channel(_probe))
        except AdapterError:
            return {"cdp": False, "uia": False, "ocr": False}

    def send_task(self, project_path: str, task: str, mode: str = "chat",
                  allow_files: list[str] | None = None, acceptance: dict | None = None,
                  approve_agent: bool = False) -> TaskRecord:
        if mode not in ("chat", "agent"):
            raise AdapterError("not_submitted", f"unsupported mode: {mode}")
        if mode == "agent" and not approve_agent:
            raise AdapterError("approval_required", "agent mode requires an approved task scope")
        task_id = f"task_{uuid.uuid4().hex[:12]}"
        self.store.create_task(task_id, self.app, project_path, mode, acceptance)
        record = TaskRecord(task_id=task_id, app=self.app)

        async def _send(ch):
            await self._ensure_ide_mode(ch)
            await self._ensure_chat_mode(ch, mode)
            approval = await self._force_manual_approval(ch)
            if mode == "agent" and approval not in ("manual", "absent"):
                raise AdapterError("approval_required",
                                   f"cannot force manual approval: {approval}")

            clicked = await self._eval(ch, f"""(() => {{
              const el = document.querySelector({_js(NEW_SESSION)});
              if (!el) return 'missing';
              el.click(); return 'clicked';
            }})()""")
            if clicked == "missing":
                raise AdapterError("locator_missing", "new-session control not found")
            state = await self._poll(ch, lambda s: s.get("hasComposer") and s.get("sendDisabled") is True,
                                     timeout=4.0)
            if not state.get("hasComposer"):
                raise AdapterError("locator_missing", "composer not found")
            if state.get("sendDisabled") is not True:
                raise AdapterError("not_submitted", "composer not empty after new session")

            focused = await self._eval(ch, f"""(() => {{
              const el = document.querySelector({_js(COMPOSER)});
              if (!el) return 'missing';
              el.focus();
              return document.activeElement === el ? 'focused' : 'focus_failed';
            }})()""")
            if focused != "focused":
                raise AdapterError("not_submitted", "composer focus failed")
            await ch.insert_text(task)
            state = await self._poll(ch, lambda s: s.get("sendDisabled") is False, timeout=3.0)
            if state.get("sendDisabled") is not False:
                raise AdapterError("not_submitted", "send button stayed disabled after typing")

            clicked = await self._eval(ch, f"""(() => {{
              const btn = document.querySelector({_js(SEND)});
              if (!btn) return 'missing';
              if (/(^|\\s)disabled(\\s|$)/.test(String(btn.className || ''))) return 'disabled';
              btn.click(); return 'clicked';
            }})()""")
            if clicked != "clicked":
                raise AdapterError("not_submitted", f"send click failed: {clicked}")

            prefix = " ".join(task.split())[:12]

            def submitted(s):
                return prefix and prefix in " ".join((s.get("text") or "").split())

            state = await self._poll(ch, submitted, timeout=10.0)
            if not submitted(state):
                raise AdapterError("not_submitted", "user message echo not found after send")
            text = state.get("text") or ""
            return {"text_len": len(text), "task_prefix": prefix, "mode": state.get("modeName")}

        try:
            baseline = self._run(self._with_channel(_send))
        except AdapterError:
            self.store.transition(task_id, "failed", "")
            raise
        event_id = self.store.record("submit_baseline", baseline, task_id=task_id)
        record.transition("submitted", event_id, utcnow())
        self.store.transition(task_id, "submitted", event_id)
        self.store.record("task_submitted", {"project_path": project_path, "mode": mode,
                                             "task": task, "baseline": baseline},
                          evidence=[event_id], task_id=task_id)
        return record

    def get_status(self, task_id: str) -> TaskRecord:
        task = self.store.get_task(task_id)
        if task is None:
            raise AdapterError("unknown_state", f"unknown task: {task_id}")
        async def _status(ch):
            return await self._state(ch)
        try:
            state = self._run(self._with_channel(_status))
        except AdapterError:
            raise
        baseline = self.store.latest_event(task_id, "submit_baseline")
        baseline_payload = (baseline or {}).get("payload") or {}
        baseline_len = int(baseline_payload.get("text_len") or 0)
        text = state.get("text") or ""
        running = has_running_signal(text, bool(state.get("stopControl")))
        approval = has_approval_prompt(text)
        new_reply = (not running) and len(text) > baseline_len
        conflict = bool(state.get("stopControl")) and new_reply
        if conflict:
            new_reply = True
        new_state = detect_state(text, bool(state.get("stopControl")), new_reply, approval)
        submitted_ts = (baseline or {}).get("ts") or task["created_ts"]
        if new_state == "unknown":
            elapsed = self._elapsed(submitted_ts)
            if task["state"] == "running" and elapsed <= 180:
                # running → idle with no approval prompt is a completion claim,
                # even when virtualized text shrank back to the baseline length.
                new_state = "claimed_done"
            elif task["state"] == "submitted" and elapsed <= 180:
                new_state = "submitted"
        if new_state != task["state"]:
            event_id = self.store.record("status_observed", {
                "state": new_state, "running_text": running, "stop_control": bool(state.get("stopControl")),
                "approval_prompt": approval, "text_len": len(text), "baseline_len": baseline_len,
            }, task_id=task_id)
            self.store.transition(task_id, new_state, event_id)
        record = TaskRecord(task_id=task_id, app=self.app, state=new_state)
        record.transitions = self.store.task_transitions(task_id)
        return record

    def read_result(self, task_id: str, max_chars: int = 8000) -> dict:
        task = self.store.get_task(task_id)
        if task is None:
            raise AdapterError("unknown_state", f"unknown task: {task_id}")
        async def _read(ch):
            return await self._state(ch)
        state = self._run(self._with_channel(_read))
        baseline = self.store.latest_event(task_id, "submit_baseline")
        submitted_text = (self.store.latest_event(task_id, "task_submitted") or {}).get("payload", {}).get("task", "")
        text = state.get("text") or ""
        reply = extract_last_reply(text, submitted_text)
        truncated = len(reply) > max_chars
        reply = reply[:max_chars]
        claimed = task["state"] in ("claimed_done", "verified") or (
            not has_running_signal(text, bool(state.get("stopControl"))) and len(text) > int(
                ((baseline or {}).get("payload") or {}).get("text_len") or 0))
        event_id = self.store.record("result_read", {
            "reply_len": len(reply), "truncated": truncated, "claimed_done": claimed,
        }, task_id=task_id)
        return {"task_id": task_id, "reply_text": reply, "untrusted": True,
                "claimed_done": claimed, "truncated": truncated,
                "state": task["state"], "evidence": [event_id]}

    def _elapsed(self, iso_ts: str) -> float:
        from datetime import datetime
        try:
            return time.time() - datetime.fromisoformat(iso_ts).timestamp()
        except Exception:
            return 0.0

    def ensure_ide_mode(self) -> None:
        self._run(self._with_channel(self._ensure_ide_mode))

    def select_chat_mode(self, mode: str) -> str:
        return self._run(self._with_channel(lambda ch: self._ensure_chat_mode(ch, mode)))

    def force_manual_approval(self) -> str:
        return self._run(self._with_channel(self._force_manual_approval))
