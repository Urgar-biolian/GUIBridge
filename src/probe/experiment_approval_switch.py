"""Experiment: can CDP clicks switch Trae approval auto->manual on the DEMO window?

Authorized live interaction experiment (owner 2026-11-18), isolated demo page ONLY.
Refuses the real project. Tries trusted mouse click then JS click on the approval
trigger, broadly searches for any menu container (not just .popup-menu), enumerates
leaves, and if a unique manual leaf appears, clicks it and reads back the label.
Read-back at every step; raw snapshots go to gitignored var/experiments/. This is
evidence about the F10 'menu does not open' finding, not a guaranteed switch.
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages"))

from perception.cdp import CDPChannel, list_targets  # noqa: E402

PORT = 9222
DEMO_BASENAME = "guibridge-demo-workspace"
BLOCKLIST = ("agui",)

SNAPSHOT_EXPR = r"""(() => {
  const trigger = document.querySelector("button[aria-label='自动审批']") ||
                  document.querySelector("button[aria-label='手动审批']") ||
                  document.querySelector('[class*=permissionModeTrigger]');
  const label = trigger ? (trigger.getAttribute('aria-label') || trigger.textContent || '').trim() : null;
  const rc = trigger ? trigger.getBoundingClientRect() : null;
  const menus = [];
  for (const el of document.querySelectorAll('*')) {
    const cls = String(el.className || '');
    if (!/popup|menu|listbox|dropdown|popover|overlay|select/i.test(cls)) continue;
    const r = el.getBoundingClientRect();
    if (r.height <= 0 || r.width <= 0) continue;
    const items = [...el.querySelectorAll('*')]
      .filter(c => c.children.length === 0 && (c.innerText || '').trim())
      .slice(0, 12).map(c => (c.innerText || '').trim().slice(0, 40));
    menus.push({cls: cls.slice(0, 80), role: el.getAttribute('role'),
                rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
                items});
  }
  return JSON.stringify({approvalLabel: label,
                         trigger: rc ? {x: rc.x + rc.width / 2, y: rc.y + rc.height / 2,
                                        tag: trigger.tagName, cls: String(trigger.className).slice(0, 80)} : null,
                         menus});
})()"""


async def _click(ch, x, y):
    for kind in ("mouseMoved", "mousePressed", "mouseReleased"):
        params = {"type": kind, "x": x, "y": y}
        if kind != "mouseMoved":
            params.update(button="left", clickCount=1)
        await ch._request("Input.dispatchMouseEvent", params)
        await asyncio.sleep(0.05)


async def _snap(ch):
    return await ch.evaluate_json(SNAPSHOT_EXPR)


def _manual_leaf(snap):
    hits = []
    for m in snap.get("menus", []):
        for it in m.get("items", []):
            if "手动" in it or "manual" in it.lower():
                hits.append((m, it))
    return hits


async def main():
    pages = [t for t in list_targets(PORT) if t.type == "page" and DEMO_BASENAME in t.title.lower()]
    if not pages or any(b in pages[0].title.lower() for b in BLOCKLIST):
        print("refusing: demo page not found or looks like real project", file=sys.stderr)
        return 2
    ch = CDPChannel(PORT)
    await ch.connect(pages[0].ws_url)
    await ch.attach_sessions()
    log = {"page": pages[0].title, "steps": []}
    try:
        before = await _snap(ch)
        log["steps"].append({"step": "before", "snap": before})
        if before.get("trigger"):
            await _click(ch, before["trigger"]["x"], before["trigger"]["y"])
            await asyncio.sleep(0.5)
        after_trusted = await _snap(ch)
        log["steps"].append({"step": "after_trusted_click", "snap": after_trusted})

        opened = len(after_trusted.get("menus", [])) > len(before.get("menus", []))
        if not opened and before.get("trigger"):
            await ch.evaluate_json(r"""(() => {
              const t = document.querySelector("button[aria-label='自动审批']") ||
                        document.querySelector('[class*=permissionModeTrigger]');
              if (t) t.click(); return 'clicked';
            })()""")
            await asyncio.sleep(0.5)
            after_js = await _snap(ch)
            log["steps"].append({"step": "after_js_click", "snap": after_js})
            after_trusted = after_js

        hits = _manual_leaf(after_trusted)
        log["manual_leaf_hits"] = [{"menu_cls": m["cls"], "text": it} for m, it in hits]
        if len(hits) == 1:
            m = hits[0][0]
            # click center of the menu container item region (leaf text matched uniquely)
            rx, ry, rw, rh = m["rect"]
            await _click(ch, rx + rw / 2, ry + rh / 2)
            await asyncio.sleep(0.6)
            final = await _snap(ch)
            log["steps"].append({"step": "after_manual_click", "snap": final})
            log["final_label"] = final.get("approvalLabel")
            log["switched"] = bool(final.get("approvalLabel") and
                                   ("手动" in final["approvalLabel"] or "manual" in final["approvalLabel"].lower()))
        else:
            log["switched"] = False
            log["reason"] = "no_unique_manual_leaf" if not hits else "ambiguous_manual_leaves"
    finally:
        await ch.close()

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = ROOT / "var" / "experiments" / f"approval_switch_{run_id}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(log, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"switched": log.get("switched"), "final_label": log.get("final_label"),
                      "manual_leaf_hits": log.get("manual_leaf_hits"),
                      "reason": log.get("reason"), "raw": str(out)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))