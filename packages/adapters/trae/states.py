"""Trae task-state detectors. Signals verified on 3.6.13 (PROBE_REPORT F6).

claimed_done is a UI claim only; verified is granted by the independent verifier (S3).
"""

RUNNING_TEXT = ("思考中", "生成中", "运行中")
APPROVAL_HINTS = ("等待审批", "需要审批", "需审批", "approval required")


def has_running_signal(conversation_text: str, has_stop_control: bool = False) -> bool:
    return has_stop_control or any(t in (conversation_text or "") for t in RUNNING_TEXT)


def has_approval_prompt(conversation_text: str, visible: bool = False) -> bool:
    return visible or any(t in (conversation_text or "") for t in APPROVAL_HINTS)


def detect_state(conversation_text: str, has_stop_control: bool, new_assistant_reply: bool,
                 approval_prompt_visible: bool) -> str:
    """Return submitted/running/awaiting_approval/claimed_done/unknown.

    Contradictory signals (reply node while still running) are unknown, never guessed.
    """
    running = has_running_signal(conversation_text, has_stop_control)
    awaiting = has_approval_prompt(conversation_text, approval_prompt_visible)
    if awaiting:
        return "awaiting_approval"
    if running and new_assistant_reply:
        return "unknown"
    if running:
        return "running"
    if new_assistant_reply:
        return "claimed_done"
    return "unknown"
