import pytest

from adapters.trae.states import detect_state, has_running_signal


@pytest.mark.parametrize("text", ["思考中", "正在生成中…", "运行中"])
def test_running_text(text):
    assert detect_state(text, False, False, False) == "running"


def test_stop_control_means_running():
    assert has_running_signal("", True)
    assert detect_state("", True, False, False) == "running"


def test_claimed_done_needs_no_running_and_new_reply():
    assert detect_state("已为你完成修改", False, True, False) == "claimed_done"
    assert detect_state("已为你完成修改", False, False, False) == "unknown"


def test_reply_while_running_is_unknown():
    assert detect_state("思考中", False, True, False) == "unknown"


def test_approval_prompt_wins():
    assert detect_state("需要审批", False, False, True) == "awaiting_approval"
    assert detect_state("思考中", False, False, True) == "awaiting_approval"


def test_no_signals_unknown():
    assert detect_state("", False, False, False) == "unknown"