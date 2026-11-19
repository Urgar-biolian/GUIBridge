"""UIA perception channel: native Win32/WPF/WinForms; Electron exposes frame-level tree only."""

from __future__ import annotations

import ctypes

from semantic.element import GUIElement

CHANNEL_WEIGHT = 0.8

_ROLE_MAP = {
    "ButtonControl": "button",
    "EditControl": "textbox",
    "DocumentControl": "document",
    "TextControl": "text",
    "ComboBoxControl": "combobox",
    "MenuItemControl": "menuitem",
    "GroupControl": "group",
    "PaneControl": "pane",
    "WindowControl": "window",
}


class UIAUnavailable(RuntimeError):
    pass


def _auto():
    try:
        import uiautomation as auto
    except ImportError as e:
        raise UIAUnavailable("uiautomation is not installed or not on Windows") from e
    return auto


def _process_name(pid: int) -> str:
    buf = ctypes.create_unicode_buffer(260)
    handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
    if not handle:
        return ""
    try:
        size = ctypes.c_uint(260)
        ctypes.windll.kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
        return buf.value
    finally:
        ctypes.windll.kernel32.CloseHandle(handle)


def _window_id(ctrl) -> str:
    return f"{ctrl.NativeWindowHandle:x}"


class UIAChannel:
    def list_windows(self, process_names: list[str] | None = None) -> list[dict]:
        auto = _auto()
        names = [n.lower() for n in process_names] if process_names else None
        out = []
        for w in auto.GetRootControl().GetChildren():
            try:
                if not w.Name:
                    continue
                proc = _process_name(w.ProcessId)
                if names and not any(n in proc.lower() for n in names):
                    continue
                r = w.BoundingRectangle
                out.append({
                    "window_id": _window_id(w),
                    "process_name": proc,
                    "title": w.Name,
                    "bounds": [r.left, r.top, r.right, r.bottom],
                })
            except Exception:
                continue
        return out

    def _find_window(self, window_id: str):
        auto = _auto()
        for w in auto.GetRootControl().GetChildren():
            try:
                if _window_id(w) == window_id:
                    return w
            except Exception:
                continue
        return None

    def inspect_window(self, window_id: str, max_depth: int = 18,
                       max_nodes: int = 20000) -> list[dict]:
        auto = _auto()
        win = self._find_window(window_id)
        if win is None:
            return []
        nodes: list[dict] = []

        def walk(ctrl, depth: int) -> None:
            if depth > max_depth or len(nodes) >= max_nodes:
                return
            try:
                r = ctrl.BoundingRectangle
                nodes.append({
                    "control_type": ctrl.ControlTypeName,
                    "name": (ctrl.Name or "")[:120],
                    "automation_id": (ctrl.AutomationId or "")[:80],
                    "class_name": (ctrl.ClassName or "")[:80],
                    "bounds": [r.left, r.top, r.right, r.bottom],
                    "patterns": _patterns(ctrl, auto),
                })
            except Exception:
                return
            try:
                for child in ctrl.GetChildren():
                    walk(child, depth + 1)
            except Exception:
                pass

        walk(win, 0)
        return nodes


def _patterns(ctrl, auto) -> list[str]:
    found = []
    for name, pid in (("invoke", auto.PatternId.InvokePattern),
                      ("value", auto.PatternId.ValuePattern),
                      ("text", auto.PatternId.TextPattern),
                      ("toggle", auto.PatternId.TogglePattern)):
        try:
            if ctrl.GetPattern(pid):
                found.append(name)
        except Exception:
            pass
    return found


def elements_from_uia(nodes: list[dict], window_id: str, offset: tuple[int, int] = (0, 0)) -> list[GUIElement]:
    elements = []
    for i, n in enumerate(nodes):
        role = _ROLE_MAP.get(n.get("control_type", ""), n.get("control_type", "").lower())
        b = n.get("bounds", [0, 0, 0, 0])
        elements.append(GUIElement(
            id=f"{window_id}:uia:{i}",
            window_id=window_id,
            role=role,
            name=n.get("name", ""),
            bounds=(b[0] - offset[0], b[1] - offset[1], b[2] - offset[0], b[3] - offset[1]),
            actions=["invoke"] if "invoke" in n.get("patterns", []) else ["click"],
            source=["uia"],
            confidence=CHANNEL_WEIGHT if n.get("name") else CHANNEL_WEIGHT - 0.2,
            evidence={"uia": {k: n.get(k) for k in ("control_type", "automation_id", "class_name", "patterns")}},
        ))
    return elements