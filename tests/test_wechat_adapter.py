"""WeChat adapter pure-logic guards with a fake driver (no real WeChat / Win32 / OCR).

Verifies the productized safety gates: default manual approval (principle 7), window
whitelist locate, anti-mis-send title gate, staged-text gate, four-state classification,
non-idempotent no-retry (principle 6), privacy redaction, and leave-as-found cleanup.
"""

import json

import pytest

from adapters.wechat.adapter import AdapterError, WeChatAdapter
from packages.focusguard.monitor import FocusRun
from packages.focusguard.outcome import FocusSnapshot, ResultState
from packages.routing.capability import Channel, InterferenceRisk

TARGET = "文件传输助手"
TEXT = "GUIBridge 测试消息"


def _box(text, bounds):
    return {"text": text, "bounds": bounds, "confidence": 0.9}


def _snap(fg=1000, xy=(0, 0)):
    return FocusSnapshot(foreground_hwnd=fg, cursor_xy=xy, target_active=False, ts=0.0)


class FakeGuard:
    def __init__(self, displacement=553, switch=False):
        self.displacement = displacement
        self.switch = switch

    def wrap_with_events(self, action):
        before = _snap()
        result = action()
        after = _snap(xy=(self.displacement, 0))
        return FocusRun(result=result, before=before, after=after,
                        cursor_displacement=self.displacement,
                        unexpected_focus_switch=self.switch,
                        external_input_during_window=True, event_hook_active=True)


class FakeDriver:
    def __init__(self, locate_result="ws", restore_ok=True, boxes=None,
                 displacement=553, switch=False):
        self.locate_result = locate_result
        self.restore_ok = restore_ok
        self.boxes = list(boxes or [])
        self.displacement = displacement
        self.switch = switch
        self.locate_calls = 0
        self.cleanup_calls = 0
        self.clicks = []
        self.clipboard = []
        self.keys = []
        self.read_calls = 0
        self.ws = {"render_hwnd": 199148, "restore_hwnd": 133592, "window_id": "309ac",
                   "rect": (100, 100, 1200, 800), "original_fg": 921150, "on_screen": True}

    def locate(self):
        self.locate_calls += 1
        if self.locate_result is None:
            return None
        return dict(self.ws)

    def restore(self, ws):
        ws["on_screen"] = self.restore_ok
        return self.restore_ok

    def read_boxes(self, ws, tmp_dir):
        self.read_calls += 1
        if self.boxes:
            return self.boxes.pop(0)
        return []

    def click_rel(self, ws, rx, ry):
        self.clicks.append((rx, ry))

    def clipboard_write(self, text):
        self.clipboard.append(text)

    def combo(self, vk):
        self.keys.append(("combo", vk))

    def key(self, vk, up=False):
        self.keys.append(("key", vk, up))

    def guard(self, ws):
        return FakeGuard(self.displacement, self.switch)

    def cleanup(self, ws):
        self.cleanup_calls += 1
        return {"reminimized": True, "foreground_returned_to": ws["original_fg"]}


def _success_boxes():
    return [
        [_box("搜索", (100, 50, 200, 80))],
        [_box(TARGET, (120, 150, 300, 180)), _box(TARGET + " 聊天记录", (120, 200, 300, 230))],
        [_box(TARGET, (400, 56, 500, 80))],
        [_box(TEXT, (400, 666, 700, 692))],
        [_box("发送", (900, 700, 960, 730))],
        [_box(TEXT, (930, 600, 1240, 628))],
    ]


def test_approval_required_by_default_no_window_action():
    drv = FakeDriver()
    with pytest.raises(AdapterError) as ei:
        WeChatAdapter(drv).send_message(TARGET, TEXT)
    assert ei.value.code == "approval_required"
    assert drv.locate_calls == 0  # refused before any window action


def test_empty_argument_raises():
    drv = FakeDriver()
    with pytest.raises(AdapterError) as ei:
        WeChatAdapter(drv).send_message(TARGET, "  ", approve=True)
    assert ei.value.code == "invalid_argument"
    assert drv.locate_calls == 0


def test_window_not_found_failed():
    drv = FakeDriver(locate_result=None)
    res = WeChatAdapter(drv).send_message(TARGET, TEXT, approve=True)
    assert res.state is ResultState.FAILED
    assert res.channel is Channel.FOREGROUND_INPUT
    assert res.risk is InterferenceRisk.PHYSICAL_INPUT
    assert res.effect_verified is False
    assert drv.cleanup_calls == 0  # nothing located, nothing to clean


def test_restore_failed_cleans_up():
    drv = FakeDriver(restore_ok=False)
    res = WeChatAdapter(drv).send_message(TARGET, TEXT, approve=True)
    assert res.state is ResultState.FAILED
    assert drv.cleanup_calls == 1


def test_navigate_title_gate_failed_no_send():
    boxes = _success_boxes()
    boxes[2] = [_box("别的联系人", (400, 56, 500, 80))]  # title != target
    drv = FakeDriver(boxes=boxes)
    res = WeChatAdapter(drv).send_message(TARGET, TEXT, approve=True)
    assert res.state is ResultState.FAILED
    assert res.evidence["title_verified_target"] is False
    assert TEXT not in drv.clipboard  # never staged the message
    assert drv.cleanup_calls == 1


def test_no_search_row_failed():
    boxes = _success_boxes()
    boxes[1] = []  # no target hit
    drv = FakeDriver(boxes=boxes)
    res = WeChatAdapter(drv).send_message(TARGET, TEXT, approve=True)
    assert res.state is ResultState.FAILED
    assert res.evidence["gate"] == "no_search_result_row"


def test_stage_gate_failed():
    boxes = _success_boxes()
    boxes[3] = []  # text not staged
    drv = FakeDriver(boxes=boxes)
    res = WeChatAdapter(drv).send_message(TARGET, TEXT, approve=True)
    assert res.state is ResultState.FAILED
    assert res.evidence["gate"] == "text_not_staged"
    assert res.evidence["text_staged_verified"] is False


def test_send_button_not_located_failed():
    boxes = _success_boxes()
    boxes[4] = []  # no 发送 button
    drv = FakeDriver(boxes=boxes)
    res = WeChatAdapter(drv).send_message(TARGET, TEXT, approve=True)
    assert res.state is ResultState.FAILED
    assert drv.cleanup_calls == 1


def test_success_with_interference():
    drv = FakeDriver(boxes=_success_boxes(), displacement=553)
    res = WeChatAdapter(drv).send_message(TARGET, TEXT, approve=True)
    assert res.state is ResultState.SUCCESS_WITH_INTERFERENCE
    assert res.effect_verified is True
    assert res.channel is Channel.FOREGROUND_INPUT
    assert res.risk is InterferenceRisk.PHYSICAL_INPUT
    assert res.evidence["send_interference"]["cursor_displacement"] == 553
    assert res.evidence["title_verified_target"] is True
    assert res.evidence["text_staged_verified"] is True
    assert drv.clipboard == [TARGET, TEXT]
    assert drv.cleanup_calls == 1
    assert res.evidence["cleanup"]["foreground_returned_to"] == 921150


def test_unconfirmed_no_auto_retry():
    boxes = _success_boxes()
    boxes[5] = []  # bubble not read back -> unconfirmed
    drv = FakeDriver(boxes=boxes)
    res = WeChatAdapter(drv).send_message(TARGET, TEXT, approve=True)
    assert res.state is ResultState.UNCONFIRMED
    assert res.effect_verified is False
    # exactly one send-button click; non-idempotent send is never retried
    send_clicks = [c for c in drv.clicks if c == ((900 + 960) // 2, (700 + 730) // 2)]
    assert len(send_clicks) == 1


def test_privacy_redaction_no_private_text():
    drv = FakeDriver(boxes=_success_boxes())
    res = WeChatAdapter(drv).send_message(TARGET, TEXT, approve=True)
    blob = json.dumps(res.evidence, ensure_ascii=False)
    assert "聊天记录" not in blob  # private contact row redacted
    hits = res.evidence["search_target_hits"]
    assert any(h["text"] == "<redacted>" for h in hits)
    assert any(h["text"] == TARGET for h in hits)


def test_probe_channels_measured():
    assert WeChatAdapter(FakeDriver()).probe_channels() == {
        "uia": False, "ocr_vision": True, "foreground_input": True}