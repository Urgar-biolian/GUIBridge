"""Trae task-state detectors. Signals verified on 3.6.13; awaiting_approval features pending S2 live probe."""

RUNNING_TEXT = ("思考中", "生成中", "运行中")


def detect_state(conversation_text: str, has_stop_control: bool, new_assistant_reply: bool,
                 approval_prompt_visible: bool) -> str:
    raise NotImplementedError("S2")