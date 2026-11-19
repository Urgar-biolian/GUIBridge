"""Heal candidate discovery: chain-hint extraction, candidate matching, patch proposal.

A heal never mutates the in-memory registry: it returns a pending patch for human review
(PRD §8, schema heal_patches). Ambiguous candidates are a stop condition, not a guess.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from semantic.element import GUIElement, Locator

TESTID_RE = re.compile(r"\[data-testid\s*=\s*['\"]?([^'\"\]]+)['\"]?\]")
ARIA_RE = re.compile(r"\[aria-label\s*=\s*['\"]?([^'\"\]]+)['\"]?\]")
CLASS_CONTAINS_RE = re.compile(r"\[class\*=\s*['\"]?([^'\"\]]+)['\"]?\]")
CLASS_RE = re.compile(r"\.([A-Za-z_][\w-]*)")
ID_RE = re.compile(r"#([A-Za-z_][\w-]*)")
TAG_RE = re.compile(r"^[a-z][a-z0-9]*$")
MIN_TEXT_HINT = 2


class HealError(RuntimeError):
    code = "locator_missing"


class HealAmbiguous(HealError):
    code = "conflict"


@dataclass
class Hints:
    testids: set[str] = field(default_factory=set)
    ids: set[str] = field(default_factory=set)
    classes: set[str] = field(default_factory=set)
    texts: set[str] = field(default_factory=set)
    automation_ids: set[str] = field(default_factory=set)


@dataclass
class HealResult:
    semantic_id: str
    element: GUIElement
    previous_chain: list[dict]
    proposed_chain: list[dict]
    verification: str
    patch_path: str | None = None
    verified: bool = False


def extract_hints(chain: list[dict]) -> Hints:
    hints = Hints()
    for step in chain or []:
        if not isinstance(step, dict):
            continue
        for kind, value in step.items():
            if kind == "cdp_selector" and isinstance(value, str):
                hints.testids.update(m.strip() for m in TESTID_RE.findall(value) if m.strip())
                hints.classes.update(m.strip() for m in CLASS_CONTAINS_RE.findall(value) if m.strip())
                hints.classes.update(m for m in CLASS_RE.findall(value) if m)
                hints.ids.update(m for m in ID_RE.findall(value) if m)
                hints.texts.update(m.strip() for m in ARIA_RE.findall(value) if m.strip())
            elif kind == "uia_criteria" and isinstance(value, dict):
                if value.get("name_contains"):
                    hints.texts.add(str(value["name_contains"]))
                if value.get("automation_id"):
                    hints.automation_ids.add(str(value["automation_id"]))
            elif kind == "ocr_text" and isinstance(value, str) and value.strip():
                hints.texts.add(value.strip())
    hints.texts = {t for t in hints.texts if len(t) >= MIN_TEXT_HINT}
    return hints


def _evidence(el: GUIElement) -> dict:
    return el.evidence or {}


def _strong_match(el: GUIElement, hints: Hints) -> bool:
    ev = _evidence(el)
    cdp, uia = ev.get("cdp") or {}, ev.get("uia") or {}
    testid = cdp.get("testid") or ""
    if testid and testid in hints.testids:
        return True
    if cdp.get("id") and cdp["id"] in hints.ids:
        return True
    cls = str(cdp.get("cls") or "")
    if cls and any(h in cls for h in hints.classes):
        return True
    if uia.get("automation_id") and uia["automation_id"] in hints.automation_ids:
        return True
    return bool(uia.get("class_name") and any(h in str(uia["class_name"]) for h in hints.classes))


def _weak_match(el: GUIElement, hints: Hints) -> bool:
    names = [el.name]
    ocr_text = (_evidence(el).get("ocr") or {}).get("text")
    if ocr_text:
        names.append(str(ocr_text))
    return any(n and (n == h or h in n) for n in names for h in hints.texts)


def match_candidates(elements: list[GUIElement], hints: Hints,
                     expected_role: str | None = None) -> list[GUIElement]:
    seen: set[tuple] = set()
    out = []
    for el in elements:
        if expected_role and el.role != expected_role:
            continue
        if not (_strong_match(el, hints) or _weak_match(el, hints)):
            continue
        key = (el.role, el.name, el.bounds)
        if key in seen:
            continue
        seen.add(key)
        out.append(el)
    return out


def _tag_prefix(el: GUIElement) -> str:
    tag = str((_evidence(el).get("cdp") or {}).get("tag") or "").lower()
    return tag if TAG_RE.match(tag) else ""


def _class_token(el: GUIElement, hints: Hints) -> str | None:
    tokens = str((_evidence(el).get("cdp") or {}).get("cls") or "").split()
    for token in tokens:
        if any(h in token for h in hints.classes):
            return token
    return None


def build_proposed_chain(el: GUIElement, hints: Hints) -> list[dict]:
    ev = _evidence(el)
    cdp = ev.get("cdp") or {}
    testid = cdp.get("testid") or ""
    if testid:
        return [{"cdp_selector": f"[data-testid={testid}]"}]

    el_id = cdp.get("id") or ""
    if el_id and ":" not in el_id:
        return [{"cdp_selector": f"#{el_id}"}]

    tag = _tag_prefix(el)
    token = _class_token(el, hints)
    if token:
        return [{"cdp_selector": f"{tag}.{token}" if tag else f".{token}"}]

    if el.name:
        attr = json.dumps(el.name, ensure_ascii=False)
        return [{"cdp_selector": f"{tag}[aria-label={attr}]" if tag else f"[aria-label={attr}]"}]

    raise HealError(f"candidate {el.id} has no selector evidence; cannot propose a patch")


def build_locator(locator: Locator, chain: list[dict]) -> Locator:
    return Locator(semantic_id=locator.semantic_id, app_version=locator.app_version,
                   chain=chain, verification=locator.verification,
                   healed_at=locator.healed_at)
