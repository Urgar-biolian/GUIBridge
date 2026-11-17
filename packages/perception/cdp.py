"""CDP perception channel for Electron/Chromium targets (primary channel, see PROBE_REPORT F3)."""

from __future__ import annotations

import asyncio
import json
import urllib.request
from dataclasses import dataclass

import websockets

from semantic.element import GUIElement

CHANNEL_WEIGHT = 0.9
DEFAULT_TIMEOUT = 10.0


class CDPError(RuntimeError):
    code = "cdp_error"


class CDPConnectionError(CDPError):
    code = "cdp_connection"


@dataclass
class CDPTarget:
    type: str
    title: str
    url: str
    ws_url: str


def list_targets(port: int) -> list[CDPTarget]:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3) as r:
            raw = json.loads(r.read().decode("utf-8"))
    except OSError as e:
        raise CDPConnectionError(f"CDP port {port} unreachable: {e}") from e
    return [CDPTarget(t.get("type", ""), t.get("title", ""), t.get("url", ""),
                      t.get("webSocketDebuggerUrl", "")) for t in raw]


SCAN_EXPR = r"""(() => {
  const out = [];
  const seen = new Set();
  const els = document.querySelectorAll('textarea, [contenteditable="true"], [contenteditable="plaintext-only"], [role="textbox"], button, [role="button"], [role="combobox"], [data-testid]');
  for (const el of els) {
    if (seen.has(el)) continue; seen.add(el);
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    out.push({
      tag: el.tagName,
      role: el.getAttribute('role'),
      aria: el.getAttribute('aria-label'),
      placeholder: el.getAttribute('placeholder') || el.getAttribute('data-placeholder'),
      contenteditable: el.getAttribute('contenteditable'),
      testid: el.getAttribute('data-testid'),
      cls: String(el.className || '').slice(0, 120),
      id: el.id,
      disabled: el.disabled === true || /(^|\s)disabled(\s|$)/.test(String(el.className || '')),
      rect: [Math.round(r.x), Math.round(r.y), Math.round(r.right), Math.round(r.bottom)],
      text: (el.textContent || '').trim().slice(0, 60)
    });
  }
  return JSON.stringify(out);
})()"""


def _selector_expr(selector: str) -> str:
    sel = json.dumps(selector)
    return f"""(() => {{
  const el = document.querySelector({sel});
  if (!el) return 'null';
  const r = el.getBoundingClientRect();
  return JSON.stringify({{
    tag: el.tagName,
    role: el.getAttribute('role'),
    aria: el.getAttribute('aria-label'),
    placeholder: el.getAttribute('placeholder') || el.getAttribute('data-placeholder'),
    contenteditable: el.getAttribute('contenteditable'),
    testid: el.getAttribute('data-testid'),
    cls: String(el.className || '').slice(0, 120),
    id: el.id,
    disabled: el.disabled === true || /(^|\\s)disabled(\\s|$)/.test(String(el.className || '')),
    rect: [Math.round(r.x), Math.round(r.y), Math.round(r.right), Math.round(r.bottom)],
    text: (el.textContent || '').trim().slice(0, 60)
  }});
}})()"""


class CDPChannel:
    """Minimal CDP client: page target, flattened auto-attach, evaluate, scan, insertText."""

    def __init__(self, port: int, session_id: str | None = None):
        self.port = port
        self.session_id = session_id
        self.sessions: dict[str, dict] = {}
        self._ws = None
        self._reader: asyncio.Task | None = None
        self._next_id = 0
        self._pending: dict[int, asyncio.Future] = {}

    async def connect(self, ws_url: str) -> None:
        try:
            self._ws = await websockets.connect(ws_url, max_size=16 * 1024 * 1024)
        except Exception as e:
            raise CDPConnectionError(f"websocket connect failed: {e}") from e
        self._reader = asyncio.create_task(self._read_loop())

    async def attach_sessions(self) -> dict[str, dict]:
        await self._request("Target.setAutoAttach",
                            {"autoAttach": True, "waitForDebuggerOnStart": False, "flatten": True})
        deadline = asyncio.get_running_loop().time() + 2.0
        while not self.sessions and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.1)
        return self.sessions

    async def _read_loop(self) -> None:
        async for message in self._ws:
            m = json.loads(message)
            if "id" in m:
                fut = self._pending.pop(m["id"], None)
                if fut and not fut.done():
                    if "error" in m:
                        fut.set_exception(CDPError(json.dumps(m["error"])))
                    else:
                        fut.set_result(m.get("result", {}))
            elif m.get("method") == "Target.attachedToTarget":
                p = m.get("params", {})
                self.sessions[p.get("sessionId", "")] = p.get("targetInfo", {})

    async def _request(self, method: str, params: dict | None = None,
                       session_id: str | None = None, timeout: float = DEFAULT_TIMEOUT):
        if self._ws is None:
            raise CDPConnectionError("not connected")
        self._next_id += 1
        rid = self._next_id
        msg = {"id": rid, "method": method, "params": params or {}}
        sid = session_id if session_id is not None else self.session_id
        if sid:
            msg["sessionId"] = sid
        fut = asyncio.get_running_loop().create_future()
        self._pending[rid] = fut
        await self._ws.send(json.dumps(msg))
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        finally:
            self._pending.pop(rid, None)

    async def evaluate(self, expression: str, session_id: str | None = None) -> dict:
        r = await self._request("Runtime.evaluate",
                                {"expression": expression, "returnByValue": True}, session_id)
        if "exceptionDetails" in r:
            raise CDPError(str(r["exceptionDetails"])[:300])
        return r

    async def evaluate_json(self, expression: str, session_id: str | None = None):
        r = await self.evaluate(expression, session_id)
        value = r.get("result", {}).get("value")
        if value is None:
            return None
        if isinstance(value, (dict, list)):
            return value
        return json.loads(value)

    async def scan_elements(self, session_id: str | None = None) -> list[dict]:
        raws = await self.evaluate_json(SCAN_EXPR, session_id)
        return raws or []

    async def query_selector(self, selector: str, session_id: str | None = None) -> dict | None:
        raw = await self.evaluate_json(_selector_expr(selector), session_id)
        if raw in (None, "null"):
            return None
        return raw

    async def insert_text(self, text: str, session_id: str | None = None) -> None:
        await self._request("Input.insertText", {"text": text}, session_id)

    async def close(self) -> None:
        if self._reader:
            self._reader.cancel()
        if self._ws is not None:
            await self._ws.close()
            self._ws = None


_ROLE_BY_TAG = {"BUTTON": "button", "TEXTAREA": "textbox", "A": "link"}


def normalize_dom_role(raw: dict) -> str:
    if raw.get("role"):
        return raw["role"]
    if raw.get("contenteditable") == "true":
        return "textbox"
    return _ROLE_BY_TAG.get(raw.get("tag", ""), raw.get("tag", "").lower())


_ACTIONS_BY_ROLE = {
    "button": ["click", "invoke"],
    "textbox": ["click", "type"],
    "combobox": ["click", "select"],
    "link": ["click"],
}


def elements_from_dom(raws: list[dict], window_id: str) -> list[GUIElement]:
    elements = []
    for i, raw in enumerate(raws):
        role = normalize_dom_role(raw)
        name = raw.get("aria") or raw.get("placeholder") or raw.get("text") or ""
        elements.append(GUIElement(
            id=f"{window_id}:cdp:{i}",
            window_id=window_id,
            role=role,
            name=name,
            bounds=tuple(raw.get("rect", [0, 0, 0, 0])),
            actions=_ACTIONS_BY_ROLE.get(role, ["click"]),
            source=["cdp"],
            confidence=CHANNEL_WEIGHT,
            evidence={"cdp": {k: raw.get(k) for k in ("tag", "cls", "id", "testid", "disabled")}},
        ))
    return elements