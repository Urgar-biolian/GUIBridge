"""Unit tests for the read-only observation dashboard (src/probe/gbdash.py).

Pure helpers only: no live sessions, no server traffic, no hidden-desktop capture.
The capability view reads the frozen yaml read-only.
"""

import importlib.util
import json
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROBE = ROOT / "src" / "probe" / "gbdash.py"
spec = importlib.util.spec_from_file_location("gbdash", PROBE)
gd = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gd)


def _run(tmp_path, name, files):
    d = tmp_path / name
    d.mkdir(parents=True)
    for fname, obj in files.items():
        (d / fname).write_text(json.dumps(obj), encoding="utf-8")
    return d


def test_collect_events_four_state_and_capture(tmp_path):
    _run(tmp_path, "20261117T090104Z", {
        "results.json": {"experiments": {"E1": {"toggle": {
            "state": "success_with_interference", "channel": "uia",
            "cursor_displacement": 0, "unexpected_focus_switch": True,
            "external_input_during_window": False,
            "evidence": {"cursor_displacement": 0}}}}},
    })
    _run(tmp_path, "20261118T044436Z", {
        "trae_send_focus.json": {"send_focus": {
            "cursor_displacement": 0, "unexpected_focus_switch": False,
            "external_input_during_window": False}},
    })
    _run(tmp_path, "20261119T141758Z", {
        "hidden_fullscreen.json": {"verdict": "captured",
                                   "host_cursor_displacement": 0,
                                   "host_foreground_changed": False},
    })
    ev = gd.collect_events(tmp_path, limit=10)
    states = [e["state"] for e in ev if e["state"]]
    assert "success_with_interference" in states
    send = [e for e in ev if e["file"] == "trae_send_focus.json"]
    assert send and send[0]["focus_switch"] is False and send[0]["cursor"] == 0
    cap = [e for e in ev if e["file"] == "hidden_fullscreen.json"]
    assert cap and cap[0]["verdict"] == "captured" and cap[0]["focus_switch"] is False
    # newest run first
    assert ev[0]["run"] == "20261119T141758Z"


def test_collect_events_reliability_summary(tmp_path):
    _run(tmp_path, "20261117T093120Z", {
        "focusguard_reliability.json": {"detection_rate": 1.0, "false_positive_rate": 0.0,
                                        "negatives": [{"trial": 0, "unexpected": False}]},
    })
    ev = gd.collect_events(tmp_path, limit=5)
    rel = [e for e in ev if e["label"] == "$reliability"]
    assert rel and rel[0]["detection_rate"] == 1.0 and rel[0]["fp_rate"] == 0.0


def test_collect_events_ignores_non_run_dirs_and_bad_json(tmp_path):
    (tmp_path / "not_a_run").mkdir()
    (tmp_path / "not_a_run" / "x.json").write_text("{}", encoding="utf-8")
    d = tmp_path / "20261117T090104Z"
    d.mkdir()
    (d / "broken.json").write_text("{not json", encoding="utf-8")
    assert gd.collect_events(tmp_path, limit=5) == []


def test_collect_events_tolerates_dict_valued_state(tmp_path):
    # some probe json carries "state" as an object (task state), not a four-state string;
    # membership test against a set must not raise TypeError(unhashable).
    _run(tmp_path, "20261120T075816Z", {
        "hidden_trae_chain.json": {"state": {"task": "claimed_done"}, "verdict": "hidden_chain_verified"},
    })
    ev = gd.collect_events(tmp_path, limit=5)
    assert ev and ev[0]["state"] is None and ev[0]["verdict"] == "hidden_chain_verified"


def test_mirror_status_staleness(tmp_path):
    p = tmp_path / "gbmirror_status.json"
    now = 1_000_000.0
    p.write_text(json.dumps({"ts": now - 1, "fps": 30, "rec_on": False}), encoding="utf-8")
    assert gd.mirror_status(p, now=now)["running"] is True
    p.write_text(json.dumps({"ts": now - 30}), encoding="utf-8")
    assert gd.mirror_status(p, now=now)["running"] is False
    assert gd.mirror_status(tmp_path / "missing.json", now=now)["running"] is False


def test_snapshot_gate_wechat_requires_confirm():
    assert gd.snapshot_gate("wechat", False)[0] is False
    assert gd.snapshot_gate("wechat", True)[0] is True
    assert gd.snapshot_gate("trae", False)[0] is True


def test_uptime_formats():
    now = 1_000_000.0
    from datetime import datetime, timezone
    iso = datetime.fromtimestamp(now - 90061, tz=timezone.utc).isoformat()
    assert gd.uptime(iso, now=now) == "1d 1h 1m"
    assert gd.uptime(None, now=now) is None


def test_capability_view_reads_frozen_table():
    view = gd.capability_view()
    assert view["status"] == "frozen"
    assert view["entries"]
    trae = [e for e in view["entries"] if e["app"] == "trae" and e["operation"] == "send_task"]
    assert trae
    ap = [c for c in trae[0]["channels"] if c["channel"] == "app_protocol"]
    assert ap and ap[0]["supported"] is True and ap[0]["risk"] == "none"
    assert trae[0]["impact"] == "high"


def test_server_binds_loopback_only():
    from http.server import ThreadingHTTPServer
    srv = ThreadingHTTPServer(("127.0.0.1", 0), gd.Handler)
    try:
        assert srv.server_address[0] == "127.0.0.1"
    finally:
        srv.server_close()


def test_page_localized_keeps_ids_enums_and_offline():
    import re

    page = gd.PAGE
    for eid in ("sessions", "mirror", "cap", "props", "events", "evcount", "filter",
                "limit", "reload", "snapsess", "privwrap", "confirm", "snap",
                "snapmeta", "snapimg", "ts", "auto",
                "mirroropen", "mirrorclose", "mirrorwidth", "mirrorfps", "mirroract"):
        assert f'id="{eid}"' in page, eid
    for zh in ("保活会话", "镜像 / 录制", "能力表与待评审提案", "按需快照",
               "应用", "操作", "影响", "幂等", "通道（实测风险）", "证据",
               "光标位移", "外部输入", "检出率", "已运行", "调试端口",
               "无干扰", "有干扰", "未确认", "微信快照含私聊画面",
               "打开镜像窗口", "关闭镜像窗口", "主机可见动作"):
        assert zh in page, zh
    # raw enums stay visible as technical identifiers (legend / options / tooltips)
    for raw in gd.FOUR_STATES | {"focus_switch", "physical_input", "unknown", "none"}:
        assert raw in page, raw
    # offline: no remote stylesheet/script/font/image fetches (svg xmlns is not a fetch)
    assert re.search(r"""(?:src|href)\s*=\s*["']https?:""", page) is None
    assert "@import" not in page and "url(http" not in page


def test_launch_args_clamps_width_and_fps():
    a = gd.launch_args(1400, 30)
    assert a[0] == str(gd.GBMIRROR_EXE)
    assert a[a.index("--width") + 1] == "1400"
    assert a[a.index("--fps") + 1] == "30"
    assert a[a.index("--registry") + 1] == str(gd.REGISTRY_PATH)
    assert gd.launch_args(10, 999)[a.index("--width") + 1] == "400"
    assert gd.launch_args(99999, 0)[a.index("--fps") + 1] == "1"


def test_interference_summary_counts_switches_and_cursor():
    fg0, c0 = 111, (100, 100)
    clean = gd.interference_summary([(111, (100, 100)), (111, (100, 100))], fg0, c0)
    assert clean["fg_switches"] == 0 and clean["max_disp_during"] == 0
    assert clean["zero_interference_observed"] is True
    dirty = gd.interference_summary([(222, (100, 100)), (111, (103, 104))], fg0, c0)
    assert dirty["fg_switches"] == 2  # 111->222->111
    assert dirty["max_disp_during"] == 5 and dirty["cursor_displacement"] == 5
    assert dirty["fg_changed"] is False and dirty["zero_interference_observed"] is False
    assert gd.interference_summary([], fg0, c0)["zero_interference_observed"] is True


def test_running_mirror_pid_never_selects_a_keepalive_session(monkeypatch):
    # a stale/foreign pid in the status export must not become a close target
    monkeypatch.setattr(gd, "mirror_status", lambda: {"running": True, "pid": 70788})
    monkeypatch.setattr(gd, "pid_alive", lambda pid: True)
    monkeypatch.setattr(gd, "pid_image", lambda pid: "Weixin.exe")
    monkeypatch.setattr(gd, "LAUNCHED", {})
    assert gd.running_mirror_pid() is None
    monkeypatch.setattr(gd, "pid_image", lambda pid: "gbmirror.exe")
    assert gd.running_mirror_pid() == 70788


def test_close_mirror_refuses_non_gbmirror_target(monkeypatch):
    monkeypatch.setattr(gd, "running_mirror_pid", lambda: 4242)
    monkeypatch.setattr(gd, "pid_image", lambda pid: "Trae.exe")
    monkeypatch.setattr(gd, "_post_close", lambda pid: pytest.fail("must not message a foreign process"))
    body, code = gd.close_mirror()
    assert code == 403 and body["ok"] is False and "refuse to close" in body["error"]


def test_close_mirror_reports_not_running(monkeypatch):
    monkeypatch.setattr(gd, "running_mirror_pid", lambda: None)
    body, code = gd.close_mirror()
    assert code == 409 and body["error"] == "mirror window not running"


def test_open_mirror_does_not_relaunch_a_running_window(monkeypatch, tmp_path):
    exe = tmp_path / "gbmirror.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(gd, "GBMIRROR_EXE", exe)
    monkeypatch.setattr(gd, "running_mirror_pid", lambda: 4242)
    monkeypatch.setattr(gd.subprocess, "Popen",
                        lambda *a, **k: pytest.fail("must not spawn a second mirror"))
    body, code = gd.open_mirror()
    assert code == 200 and body["already_running"] is True and body["pid"] == 4242
    assert body["host_visible"] is True


def test_open_mirror_requires_built_exe(monkeypatch, tmp_path):
    monkeypatch.setattr(gd, "GBMIRROR_EXE", tmp_path / "missing.exe")
    body, code = gd.open_mirror()
    assert code == 500 and body["error"] == "gbmirror.exe not built"