"""Trae task-state detectors.

Signal basis is PROBE_REPORT F6 (conversation innerText readback + 「思考中」 runtime text).
`awaiting_approval` has no verified DOM signature yet — PROBE_REPORT 未验证项 3 — so the marker
list stays empty and the detector reports `unknown` rather than guessing.

Merged surface. The detection call surface is A's (`has_running_signal(text, has_stop_control)`
and `has_approval_prompt(text, visible)` both take the extra argument), while the state vocabulary
and the refusal to name an unverified gate stay B's. A transcript that merely mentions a gate is
handled by `approval_hint`: it withholds `claimed_done` without ever asserting `awaiting_approval`.
"""

import json

RUNNING_TEXT = ("思考中", "生成中", "运行中")
AWAITING_APPROVAL_MARKERS: tuple[str, ...] = ()
# A's transcript hints. Unverified as a DOM signature, so they cannot name a state; they can only
# stop a new reply node from being read as a completion claim.
APPROVAL_HINTS = ("等待审批", "需要审批", "需审批", "approval required")
MODE_MENU = ".popup-menu"
AUTO_APPROVAL_TRIGGER = "button[aria-label='自动审批']"
# The trigger keeps one of these two labels depending on the current mode; both resolve to the same
# visible button (A-line read-only probe, run 20261117T135355Z).
MANUAL_APPROVAL_TRIGGER = "button[aria-label='手动审批']"
APPROVAL_TRIGGER_CLASS = "[class*=permissionModeTrigger]"
APPROVAL_TRIGGERS = (AUTO_APPROVAL_TRIGGER, MANUAL_APPROVAL_TRIGGER, APPROVAL_TRIGGER_CLASS)

# --- the approval menu is a popover, not a toggle (PROBE_REPORT F10, sequence re-measured live
# 2026-11-18 in run 20261118T073742Z) -------------------------------------------------------------
# Clicking the trigger changes nothing: it opens a Vue popover rendered outside the trigger's own
# subtree, and the mode only moves when one of that popover's rows is chosen. So one approved
# interaction is two DOM interactions, and the rows are matched by exact visible text — a substring
# match would land on the `permissionModeItemName` span instead of the row that accepts the click.
# The selectors stay in code because `locators.yaml` is a frozen contract; adding the popover as a
# semantic_id is a contract proposal, not a merge-time edit.
APPROVAL_POPOVER = "[class*=permissionModePopover]"
APPROVAL_OPTION_ROW = "[class*=permissionModeItem-]"
APPROVAL_OPTION_NAME = "[class*=permissionModeItemName]"
MANUAL_APPROVAL_LABEL = "手动审批"
# Only ever toward manual. 完全访问 lets an agent act unattended, which is a human decision, so no
# value arriving from a caller may select it and `select` refuses before it touches the desktop.
ALLOWED_APPROVAL_TARGETS = (MANUAL_APPROVAL_LABEL,)


def is_allowed_approval_target(value: str) -> bool:
    return str(value or "").strip() in ALLOWED_APPROVAL_TARGETS


def approval_label_is_manual(label: str) -> bool:
    """Whether the trigger's own text says manual, which is the only read-back that counts."""
    text = str(label or "").strip().lower()
    return MANUAL_APPROVAL_LABEL in text or "manual" in text


def find_approval_option(options: list[dict], label: str = MANUAL_APPROVAL_LABEL) -> dict | None:
    """The one row named exactly `label`, or None. Two rows with that name is a conflict, not a pick."""
    named = [row for row in options or [] if str(row.get("name") or row.get("text") or "").strip() == label]
    return named[0] if len(named) == 1 else None


def approval_options(channel, window_id: str) -> list[dict]:
    """What an open approval menu offers; empty when it is closed."""
    if channel.find(window_id, APPROVAL_POPOVER) is None:
        return []
    return list(channel.query(window_id, APPROVAL_OPTION_ROW) or [])


def approval_trigger_point_js() -> str:
    """Where the trigger sits, because only a trusted mouse click opens its popover (F10)."""
    return f"""(() => {{
  const t = document.querySelector({json.dumps(APPROVAL_TRIGGER_CLASS)});
  if (!t) return JSON.stringify({{status: 'absent', label: null}});
  const r = t.getBoundingClientRect();
  return JSON.stringify({{status: 'found',
    label: (t.getAttribute('aria-label') || t.textContent || '').trim(),
    x: r.x + r.width / 2, y: r.y + r.height / 2}});
}})()"""


def approval_label_js() -> str:
    """The trigger's own label, which is the only readable evidence of the current approval mode."""
    return "(() => {const t = document.querySelector(%s) || document.querySelector(%s) || " \
           "document.querySelector(%s); " \
           "return t ? ((t.getAttribute('aria-label') || t.textContent || '').trim()) : '';})()" % (
        json.dumps(MANUAL_APPROVAL_TRIGGER), json.dumps(AUTO_APPROVAL_TRIGGER),
        json.dumps(APPROVAL_TRIGGER_CLASS))


def approval_option_click_js(label: str = MANUAL_APPROVAL_LABEL) -> str:
    """Choose the row named exactly `label` in the open popover, by clicking its row and not its span."""
    return """(() => {
  const pop = document.querySelector(%s);
  if (!pop || pop.getBoundingClientRect().height <= 0) return 'no_menu';
  const named = [...pop.querySelectorAll(%s)].filter(e => (e.textContent || '').trim() === %s);
  if (!named.length) return 'no_option';
  if (named.length > 1) return 'ambiguous_option';
  let row = named[0];
  for (let i = 0; i < 6 && row.parentElement; i++) {
    row = row.parentElement;
    const c = String(row.className || '');
    if (c.indexOf('permissionModeItem-') >= 0 && !/Name|Icon|Desc|Text/.test(c)) break;
  }
  row.click();
  return 'clicked';
})()""" % (json.dumps(APPROVAL_POPOVER), json.dumps(APPROVAL_OPTION_NAME),
           json.dumps(label, ensure_ascii=False))



def has_running_signal(conversation_text: str, has_stop_control: bool = False) -> bool:
    return bool(has_stop_control) or any(marker in (conversation_text or "") for marker in RUNNING_TEXT)


def approval_hint(conversation_text: str) -> bool:
    """A mention of a gate in the readback, which is untrusted text and not an observed control."""
    return any(hint in (conversation_text or "") for hint in APPROVAL_HINTS)


def has_approval_prompt(conversation_text: str, visible: bool = False) -> bool:
    return bool(visible) or approval_hint(conversation_text) or any(
        marker in (conversation_text or "") for marker in AWAITING_APPROVAL_MARKERS)


def approval_state(auto_present: bool, manual_present: bool, class_present: bool) -> str:
    """Read the approval mode from the trigger label: manual / auto / unreadable / absent.

    `auto` wins over `manual` when both resolve, because switching to manual is the safe direction.
    """
    if auto_present:
        return "auto"
    if manual_present:
        return "manual"
    if class_present:
        return "unreadable"
    return "absent"


def collect_signals(conversation_text: str, stop_control_present: bool,
                    approval_control_present: bool = False) -> dict:
    return {"running_text": has_running_signal(conversation_text),
            "stop_control": bool(stop_control_present),
            "approval_prompt": bool(approval_control_present) or has_approval_prompt(conversation_text)}


def detect_state(conversation_text: str, has_stop_control: bool, new_assistant_reply: bool,
                 approval_prompt_visible: bool) -> str:
    """Return submitted/running/awaiting_approval/claimed_done/unknown.

    An observed gate control names `awaiting_approval` unless the UI is simultaneously running and
    has produced a reply node — that combination is a contradiction, and a contradiction is
    `unknown`. A readback that only mentions a gate withholds `claimed_done` for the same reason.
    """
    running = has_running_signal(conversation_text, has_stop_control)
    if approval_prompt_visible and not (running and new_assistant_reply):
        return "awaiting_approval"
    if running and new_assistant_reply:
        return "unknown"
    if running:
        return "running"
    if new_assistant_reply:
        return "unknown" if approval_hint(conversation_text) else "claimed_done"
    return "unknown"


def cdp_selector(registry: dict, semantic_id: str) -> str:
    locator = registry.get(semantic_id)
    if locator is None:
        raise LookupError(f"{semantic_id} is not registered")
    for strategy in locator.chain:
        if "cdp_selector" in strategy:
            return strategy["cdp_selector"]
    raise LookupError(f"{semantic_id} has no CDP strategy in its chain")


def build_verifiers(channel, window_id: str, registry: dict) -> dict:
    """PRD §7 post-conditions. Each returns the truth of the signal, never an assumption."""

    def present(selector: str) -> bool:
        return channel.find(window_id, selector) is not None

    def conversation() -> str:
        return channel.inner_text(window_id, cdp_selector(registry, "trae.chat.conversation"))

    def send_enabled() -> bool:
        element = channel.find(window_id, cdp_selector(registry, "trae.chat.send_button"))
        return bool(element) and not element.get("disabled", False)

    return {
        "ide_layout_visible": lambda w, sel, args: present(cdp_selector(registry, "trae.chat.mode_entry")),
        "mode_menu_open": lambda w, sel, args: present(MODE_MENU),
        "session_mode_selected": lambda w, sel, args: not present(MODE_MENU),
        "focusable": lambda w, sel, args: present(sel) and send_enabled(),
        "message_submitted": lambda w, sel, args: str(args.get("text", "")).strip() in conversation(),
        "approval_mode_manual": lambda w, sel, args: present(MANUAL_APPROVAL_TRIGGER),
        # F10's two evidence steps: the menu the approved interaction had to open, and the row it had
        # to find in it. A switch that failed says which of the two was missing instead of `False`.
        "approval_menu_open": lambda w, sel, args: present(APPROVAL_POPOVER),
        "approval_option_offered": lambda w, sel, args: (
            find_approval_option(approval_options(channel, w)) is not None),
        "text_readable": lambda w, sel, args: bool(conversation().strip()),
    }
