"""Engine: single composition point over perception, semantic resolver, execution and adapter.

The MCP server and the desktop-agent REST plane both delegate here, so every tool call is
audited in the event store exactly once.
"""

from __future__ import annotations

import asyncio
import json
import re
from dataclasses import asdict
from pathlib import Path

from adapters.trae.adapter import AdapterError, TraeAdapter
from events.store import ApprovalError, EventStore, utcnow
from execution.actions import ActionError, ActionExecutor
from execution.safety import SafetyError, SafetyGate
from perception.cdp import CDPChannel, elements_from_dom, list_targets
from perception.fusion import fuse
from semantic.element import GUIElement
from semantic.locator_cache import LocatorCache
from semantic.providers import CDPSelectorProvider
from semantic.resolver import LocatorMissing, Resolver

ROOT = Path(__file__).parents[1]
LOCATORS_PATH = ROOT / "packages" / "adapters" / "trae" / "locators.yaml"
TRAE_WINDOW = "trae"


def element_selector(el: GUIElement) -> str | None:
    cdp = (el.evidence or {}).get("cdp") or {}
    if cdp.get("testid"):
        return f"[data-testid={cdp['testid']}]"
    el_id = cdp.get("id") or ""
    if el_id and ":" not in el_id:
        return f"#{el_id}"
    tag = str(cdp.get("tag") or "").lower()
    tag = tag if re.match(r"^[a-z][a-z0-9]*$", tag) else ""
    tokens = [t for t in str(cdp.get("cls") or "").split() if t and t != "disabled"]
    if tokens:
        return f"{tag}.{tokens[0]}" if tag else f".{tokens[0]}"
    if el.name:
        attr = json.dumps(el.name, ensure_ascii=False)
        return f"{tag}[aria-label={attr}]" if tag else f"[aria-label={attr}]"
    return None


def element_dict(el: GUIElement) -> dict:
    data = asdict(el)
    data["bounds"] = list(el.bounds)
    data["calibrated"] = False
    return data


class GUIBridgeEngine:
    def __init__(self, port: int = 9222, db_path: str = "var/guibridge.db",
                 retention_days: int = 30, store: EventStore | None = None):
        self.port = port
        self.store = store or EventStore(db_path, retention_days)
        self.registry = LocatorCache(str(LOCATORS_PATH)).load("trae")
        self.allowed_windows: set[str] = set()
        self.adapter = TraeAdapter(port, self.store)
        self.safety = SafetyGate(self.allowed_windows, identity_checker=self._check_identity,
                                 approvals=self.store)

    # -- audit / plumbing ----------------------------------------------
    def _audit(self, tool: str, args: dict) -> None:
        self.store.record("tool_call", {"tool": tool, "args": args})

    def _check_identity(self, window_id: str) -> None:
        targets = list_targets(self.port)
        if not any(t.type == "page" and "trae" in (t.title + t.url).lower() for t in targets):
            raise RuntimeError("Trae page target gone")

    def _require_allowed(self, window_id: str) -> None:
        if window_id not in self.allowed_windows:
            raise SafetyError(f"window {window_id} not whitelisted")

    async def _with_cdp(self, action):
        targets = list_targets(self.port)
        pages = [t for t in targets if t.type == "page" and "trae" in (t.title + t.url).lower()]
        if not pages:
            raise RuntimeError("no Trae page target")
        ch = CDPChannel(self.port)
        await ch.connect(pages[0].ws_url)
        try:
            return await action(ch)
        finally:
            await ch.close()

    # -- windows -------------------------------------------------------
    def list_windows(self) -> list[dict]:
        self._audit("gui.list_windows", {})
        try:
            targets = list_targets(self.port)
        except Exception:
            return []
        pages = [t for t in targets if t.type == "page" and "trae" in (t.title + t.url).lower()]
        if not pages:
            return []
        title = pages[0].title
        bounds = self._trae_bounds()
        allowed = TRAE_WINDOW in self.allowed_windows
        self.store.upsert_window(TRAE_WINDOW, "Trae.exe", title, bounds, whitelisted=allowed)
        return [{"window_id": TRAE_WINDOW, "process_name": "Trae.exe", "title": title,
                 "bounds": bounds, "whitelisted": allowed}]

    def allow_window(self, window_id: str) -> dict:
        self.allowed_windows.add(window_id)
        windows = self.list_windows()
        match = next((w for w in windows if w["window_id"] == window_id), None)
        if match:
            self.store.upsert_window(window_id, match["process_name"], match["title"],
                                     match["bounds"], whitelisted=True)
        self.store.whitelist_window(window_id)
        return {"window_id": window_id, "whitelisted": True}

    def _trae_bounds(self) -> list[int]:
        try:
            from perception.uia import UIAChannel
            windows = UIAChannel().list_windows(["Trae.exe"])
            if windows:
                return list(windows[0]["bounds"])
        except Exception:
            pass
        return [0, 0, 0, 0]

    # -- perception ----------------------------------------------------
    def inspect_window(self, window_id: str, max_depth: int = 18) -> list[dict]:
        self._audit("gui.inspect_window", {"window_id": window_id, "max_depth": max_depth})
        self._require_allowed(window_id)

        async def _scan(ch):
            raws = await ch.scan_elements()
            return fuse(elements_from_dom(raws, window_id))

        return asyncio.run(self._with_cdp(_scan))

    def find_element(self, window_id: str, semantic_id: str | None = None,
                     role: str | None = None, name: str | None = None) -> list[dict]:
        self._audit("gui.find_element", {"window_id": window_id, "semantic_id": semantic_id,
                                         "role": role, "name": name})
        self._require_allowed(window_id)
        if semantic_id:
            async def _resolve(ch):
                resolver = Resolver(self.registry, {"cdp_selector": CDPSelectorProvider(ch)})
                try:
                    return [await resolver.resolve(window_id, semantic_id)]
                except LocatorMissing:
                    return []
            found = asyncio.run(self._with_cdp(_resolve))
            return [element_dict(el) for el in found]
        elements = self.inspect_window(window_id)
        if role:
            elements = [e for e in elements if e["role"] == role]
        if name:
            elements = [e for e in elements if name in (e["name"] or "")]
        return elements

    def get_snapshot(self, window_id: str) -> dict:
        self._audit("gui.get_snapshot", {"window_id": window_id})
        self._require_allowed(window_id)

        async def _scan(ch):
            raws = await ch.scan_elements()
            return fuse(elements_from_dom(raws, window_id))

        elements = asyncio.run(self._with_cdp(_scan))
        image_path = None
        try:
            from perception.ocr import grab_window_png
            from perception.uia import UIAChannel
            wins = UIAChannel().list_windows(["Trae.exe"])
            if wins:
                image_path = grab_window_png(wins[0]["window_id"])
        except Exception:
            image_path = None
        snapshot_id = self.store.add_snapshot(
            window_id, {"summary": elements[:60], "count": len(elements)}, image_path=image_path)
        return {"snapshot_id": snapshot_id, "ts": utcnow(),
                "elements_summary": elements[:60], "image_path": image_path}

    # -- actions -------------------------------------------------------
    def perform_action(self, window_id: str, semantic_id: str, action: str,
                       args: dict | None = None, approval_token: str | None = None) -> dict:
        self._audit("gui.perform_action", {"window_id": window_id, "semantic_id": semantic_id,
                                           "action": action})
        self._require_allowed(window_id)

        async def _do(ch):
            resolver = Resolver(self.registry, {"cdp_selector": CDPSelectorProvider(ch)})
            executor = ActionExecutor(
                resolver, self.safety, self.store,
                snapshotter=lambda wid: self._snapshot_async(ch, wid),
                actor=lambda wid, el, act, a: self._act(ch, el, act, a))
            return await executor.perform_async(window_id, semantic_id, action, args, approval_token)

        result = asyncio.run(self._with_cdp(_do))
        return asdict(result)

    async def _snapshot_async(self, ch, window_id: str) -> dict:
        raws = await ch.scan_elements()
        return {"elements_summary": fuse(elements_from_dom(raws, window_id))[:60], "image_path": None}

    async def _act(self, ch, el: GUIElement, action: str, args: dict) -> bool:
        selector = element_selector(el)
        if not selector:
            raise ActionError("conflict", "element has no stable selector for execution")
        sel = json.dumps(selector, ensure_ascii=False)
        if action in ("click", "invoke", "select"):
            clicked = await ch.evaluate_json(f"""(() => {{
              const el = document.querySelector({sel});
              if (!el) return 'missing';
              el.scrollIntoView({{block: 'center'}});
              el.click();
              return 'clicked';
            }})()""")
            if clicked != "clicked":
                return False
            if action == "select" and args.get("option_text"):
                option = json.dumps(args["option_text"], ensure_ascii=False)
                picked = await ch.evaluate_json(f"""(() => {{
                  const want = {option};
                  const items = [...document.querySelectorAll('[role=option], .popup-menu *')]
                    .filter(e => e.children.length <= 2 && (e.textContent || '').trim() === want);
                  if (items.length !== 1) return 'ambiguous_or_missing';
                  items[0].click();
                  return 'clicked';
                }})()""")
                return picked == "clicked"
            return True
        if action == "type":
            focused = await ch.evaluate_json(f"""(() => {{
              const el = document.querySelector({sel});
              if (!el) return 'missing';
              el.focus();
              return document.activeElement === el ? 'focused' : 'focus_failed';
            }})()""")
            if focused != "focused":
                return False
            await ch.insert_text(str(args.get("text", "")))
            return True
        return False

    # -- task API ------------------------------------------------------
    def send_task(self, project_path: str, task: str, mode: str = "chat",
                  allow_files: list[str] | None = None, acceptance: dict | None = None) -> dict:
        self._audit("trae.send_task", {"project_path": project_path, "mode": mode})
        if TRAE_WINDOW not in self.allowed_windows:
            raise SafetyError(f"window {TRAE_WINDOW} not whitelisted")
        if not Path(project_path).is_dir():
            raise AdapterError("not_submitted", f"project path not found: {project_path}")
        approve_agent = False
        if mode == "agent":
            try:
                self.store.consume_scope("trae.send_task", "agent")
                approve_agent = True
            except ApprovalError as e:
                raise ApprovalError(str(e)) from e
        record = self.adapter.send_task(project_path, task, mode, allow_files, acceptance,
                                        approve_agent=approve_agent)
        return {"task_id": record.task_id, "app": record.app, "state": record.state,
                "transitions": record.transitions}

    def get_status(self, task_id: str) -> dict:
        self._audit("trae.get_status", {"task_id": task_id})
        record = self.adapter.get_status(task_id)
        observed = self.store.latest_event(task_id, "status_observed")
        payload = (observed or {}).get("payload") or {}
        return {"task_id": record.task_id, "state": record.state,
                "signals": {"running_text": payload.get("running_text"),
                            "stop_control": payload.get("stop_control"),
                            "approval_prompt": payload.get("approval_prompt")},
                "transitions": record.transitions,
                "evidence": [observed["event_id"]] if observed else []}

    def read_result(self, task_id: str, max_chars: int = 8000) -> dict:
        self._audit("trae.read_result", {"task_id": task_id, "max_chars": max_chars})
        return self.adapter.read_result(task_id, max_chars)

    # -- registry ------------------------------------------------------
    def list_locators(self) -> list[dict]:
        return [{"semantic_id": loc.semantic_id, "app_version": loc.app_version,
                 "chain": loc.chain, "verification": loc.verification}
                for loc in self.registry.values()]

    def list_heal_patches(self, status: str | None = None) -> list[dict]:
        return self.store.list_heal_patches(status)
