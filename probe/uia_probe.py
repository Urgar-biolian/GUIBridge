# -*- coding: utf-8 -*-
"""Day-1 Go/No-Go probe: dump Trae's UIA control tree and look for chat input / send button."""
import json
import sys
import time

import uiautomation as auto

MAX_DEPTH = 18
MAX_NODES = 20000


def find_trae_windows():
    wins = []
    for w in auto.GetRootControl().GetChildren():
        try:
            pid = w.ProcessId
            name = auto.GetProcessName(pid) if hasattr(auto, "GetProcessName") else ""
        except Exception:
            continue
        try:
            import ctypes
            buf = ctypes.create_unicode_buffer(260)
            h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if h:
                size = ctypes.c_uint(260)
                ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
                ctypes.windll.kernel32.CloseHandle(h)
                name = buf.value
        except Exception:
            pass
        if "trae" in name.lower():
            wins.append((w, name))
    return wins


def walk(ctrl, depth, nodes):
    if depth > MAX_DEPTH or len(nodes) > MAX_NODES:
        return
    try:
        rect = ctrl.BoundingRectangle
        node = {
            "depth": depth,
            "type": ctrl.ControlTypeName,
            "name": (ctrl.Name or "")[:120],
            "auto_id": (ctrl.AutomationId or "")[:80],
            "class": (ctrl.ClassName or "")[:80],
            "rect": [rect.left, rect.top, rect.right, rect.bottom],
            "patterns": [],
        }
        for pat_name, pat_id in [
            ("Invoke", auto.PatternId.InvokePattern),
            ("Value", auto.PatternId.ValuePattern),
            ("Text", auto.PatternId.TextPattern),
            ("Toggle", auto.PatternId.TogglePattern),
        ]:
            try:
                if ctrl.GetPattern(pat_id):
                    node["patterns"].append(pat_name)
            except Exception:
                pass
        nodes.append(node)
    except Exception as e:
        nodes.append({"depth": depth, "error": str(e)[:100]})
        return
    try:
        for child in ctrl.GetChildren():
            walk(child, depth + 1, nodes)
    except Exception:
        pass


def main():
    wins = find_trae_windows()
    if not wins:
        print("NO_TRAE_WINDOW")
        sys.exit(1)
    print(f"Trae windows found: {len(wins)}")
    all_nodes = []
    for w, proc in wins:
        print(f"  window: {w.Name!r} pid={w.ProcessId} class={w.ClassName}")
        nodes = []
        walk(w, 0, nodes)
        print(f"  nodes walked: {len(nodes)}")
        all_nodes.extend(nodes)

    with open("probe/uia_dump.json", "w", encoding="utf-8") as f:
        json.dump(all_nodes, f, ensure_ascii=False, indent=1)

    from collections import Counter
    types = Counter(n.get("type", "?") for n in all_nodes)
    print("\nControl type counts:", dict(types.most_common(20)))

    print("\n--- Editable controls (chat input candidates) ---")
    for n in all_nodes:
        if n.get("type") in ("EditControl", "DocumentControl") or "Value" in n.get("patterns", []):
            print(json.dumps(n, ensure_ascii=False))

    print("\n--- Buttons with send/agent/stop keywords ---")
    kw = ("send", "发送", "agent", "stop", "停止", "submit", "chat", "builder")
    for n in all_nodes:
        if n.get("type") == "ButtonControl":
            text = (n.get("name", "") + " " + n.get("auto_id", "")).lower()
            if any(k in text for k in kw):
                print(json.dumps(n, ensure_ascii=False))

    named = sum(1 for n in all_nodes if n.get("name"))
    with_id = sum(1 for n in all_nodes if n.get("auto_id"))
    print(f"\nSummary: total={len(all_nodes)} named={named} with_automation_id={with_id}")


if __name__ == "__main__":
    main()