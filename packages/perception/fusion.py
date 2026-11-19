"""Multi-channel element fusion: spatial match, semantic merge, conflict detection.

Conflicts are returned as flagged entries; callers must refuse to act on them (PRD §3).
Confidence is a heuristic score only and is always marked calibrated=False.
"""

from __future__ import annotations

from semantic.element import GUIElement

CHANNEL_PRIORITY = {"cdp": 4, "uia": 3, "ocr": 2, "vision": 1}
CHANNEL_WEIGHT = {"cdp": 0.9, "uia": 0.8, "ocr": 0.5, "vision": 0.4}
MATCH_IOU = 0.5
CONTAIN_OVERLAP = 0.7
SIBLING_GAP_PX = 20
SIBLING_ROLES = {"button", "link", "menuitem", "combobox"}


def iou(a, b) -> float:
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    iw = max(0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    if inter == 0:
        return 0.0
    area_a = max(0, ax2 - ax1) * max(0, ay2 - ay1)
    area_b = max(0, bx2 - bx1) * max(0, by2 - by1)
    union = area_a + area_b - inter
    return inter / union if union else 0.0


def _containment(a, b) -> float:
    """Share of the smaller rect covered by the intersection (OCR label inside a control)."""
    ax1, ay1, ax2, ay2 = a
    bx1, by1, bx2, by2 = b
    iw = max(0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0, min(ay2, by2) - max(ay1, by1))
    inter = iw * ih
    if inter == 0:
        return 0.0
    smaller = min(max(0, ax2 - ax1) * max(0, ay2 - ay1),
                  max(0, bx2 - bx1) * max(0, by2 - by1))
    return inter / smaller if smaller else 0.0


def _matches(a, b) -> bool:
    return iou(a, b) >= MATCH_IOU or _containment(a, b) >= CONTAIN_OVERLAP


def _gap(a, b) -> int:
    dx = max(a[0] - b[2], b[0] - a[2], 0)
    dy = max(a[1] - b[3], b[1] - a[3], 0)
    return max(dx, dy)


def _priority(el: GUIElement) -> int:
    return max((CHANNEL_PRIORITY.get(s, 0) for s in el.source), default=0)


def _roles_compatible(r1: str, r2: str) -> bool:
    return r1 == r2 or "text" in (r1, r2)


def _confidence(sources: set[str]) -> float:
    base = max((CHANNEL_WEIGHT.get(s, 0.3) for s in sources), default=0.3)
    bonus = 0.03 * (len(sources) - 1)
    return round(min(0.95, base + bonus), 3)


def fuse(elements: list[GUIElement]) -> list[dict]:
    groups: list[dict] = []
    for el in sorted(elements, key=lambda e: (-_priority(e), -e.confidence)):
        pending_conflict = ""
        best, best_score = None, 0.0
        for g in groups:
            if not _matches(g["bounds"], el.bounds):
                continue
            if not _roles_compatible(g["role"], el.role):
                reason = f"cross-channel role mismatch: {g['role']} vs {el.role}"
                _flag(g, reason)
                pending_conflict = reason
                continue
            score = max(iou(g["bounds"], el.bounds), _containment(g["bounds"], el.bounds))
            if score > best_score:
                best, best_score = g, score

        if best is not None:
            best["sources"].update(el.source)
            for k, v in el.evidence.items():
                best["evidence"].setdefault(k, {}).update(v)
            if not best["name"] and el.name:
                best["name"] = el.name
            best["confidence"] = _confidence(best["sources"])
            continue

        group = {
            "role": el.role, "name": el.name, "bounds": el.bounds,
            "sources": set(el.source), "evidence": dict(el.evidence),
            "confidence": _confidence(set(el.source)),
            "conflict": False, "conflict_reason": "",
        }
        if pending_conflict:
            _flag(group, pending_conflict)
        for g in groups:
            if (group["role"] in SIBLING_ROLES and g["role"] == group["role"]
                    and group["name"] and g["name"] == group["name"]
                    and _gap(group["bounds"], g["bounds"]) <= SIBLING_GAP_PX):
                reason = f"similar sibling controls for {group['name']!r}; ambiguous"
                _flag(group, reason)
                _flag(g, reason)
        groups.append(group)

    out = []
    for i, g in enumerate(groups):
        out.append({
            "id": f"fused:{i}",
            "role": g["role"], "name": g["name"], "bounds": g["bounds"],
            "sources": sorted(g["sources"]),
            "confidence": g["confidence"], "calibrated": False,
            "conflict": g["conflict"], "conflict_reason": g["conflict_reason"],
            "evidence": g["evidence"],
        })
    return out


def _flag(group: dict, reason: str) -> None:
    group["conflict"] = True
    group["conflict_reason"] = (group["conflict_reason"] + "; " + reason).lstrip("; ")