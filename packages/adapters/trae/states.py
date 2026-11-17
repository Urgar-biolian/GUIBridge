"""Trae task-state detectors.

Signal basis is PROBE_REPORT F6 (conversation innerText readback + 「思考中」 runtime text).
`awaiting_approval` has no verified DOM signature yet — PROBE_REPORT 未验证项 3 — so the marker
list stays empty and the detector reports `unknown` rather than guessing.
"""

RUNNING_TEXT = ("思考中", "生成中", "运行中")
AWAITING_APPROVAL_MARKERS: tuple[str, ...] = ()
MODE_MENU = ".popup-menu"
AUTO_APPROVAL_TRIGGER = "button[aria-label='自动审批']"


def has_running_signal(conversation_text: str) -> bool:
    return any(marker in conversation_text for marker in RUNNING_TEXT)


def has_approval_prompt(conversation_text: str) -> bool:
    return any(marker in conversation_text for marker in AWAITING_APPROVAL_MARKERS)


def collect_signals(conversation_text: str, stop_control_present: bool,
                    approval_control_present: bool = False) -> dict:
    return {"running_text": has_running_signal(conversation_text),
            "stop_control": bool(stop_control_present),
            "approval_prompt": bool(approval_control_present) or has_approval_prompt(conversation_text)}


def detect_state(conversation_text: str, has_stop_control: bool, new_assistant_reply: bool,
                 approval_prompt_visible: bool) -> str:
    running = has_running_signal(conversation_text) or bool(has_stop_control)
    if approval_prompt_visible and running:
        return "unknown"
    if approval_prompt_visible:
        return "awaiting_approval"
    if running:
        return "running"
    if new_assistant_reply:
        return "claimed_done"
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
        "approval_mode_manual": lambda w, sel, args: not present(AUTO_APPROVAL_TRIGGER),
        "text_readable": lambda w, sel, args: bool(conversation().strip()),
    }
