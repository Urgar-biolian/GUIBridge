"""Read-only invariants for the B-line R5 step-1 control-existence probe.

These lock the probe's safety properties WITHOUT a live Trae: the executed DOM
expression and the CDP read path carry no write verbs, and the state metrics never
record untrusted chat body text. The probe itself is a live instrument; its measured
output lives in gitignored var/experiments/, not here."""

import importlib.util
import inspect
from pathlib import Path

PROBE = Path(__file__).resolve().parents[1] / "src" / "probe" / "verify_trae_controls_exist.py"

_WRITE_VERBS = (".click(", "dispatchMouseEvent", "insertText", "insert_text", ".focus(")


def _load_module():
    spec = importlib.util.spec_from_file_location("verify_trae_controls_exist", PROBE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_controls_expression_is_read_only():
    mod = _load_module()
    for verb in _WRITE_VERBS:
        assert verb not in mod.CONTROLS_EXPR, f"read-only probe expression must not contain {verb!r}"


def test_read_path_uses_only_read_cdp_calls():
    mod = _load_module()
    src = inspect.getsource(mod._read)
    assert "evaluate_json" in src
    for verb in ("insert_text", "Input.dispatch", "_request(", ".click("):
        assert verb not in src, f"_read must not perform write call {verb!r}"


def test_state_metrics_drop_untrusted_chat_body():
    mod = _load_module()
    metrics = mod._state_metrics({
        "hasRoot": True, "hasComposer": True, "modeName": "Chat",
        "sendDisabled": True, "stopControl": False, "approvalLabel": "自动审批",
        "text": "secret user conversation body",
    })
    assert "text" not in metrics
    assert metrics["text_len"] == len("secret user conversation body")
    assert metrics["mode_name"] == "Chat"