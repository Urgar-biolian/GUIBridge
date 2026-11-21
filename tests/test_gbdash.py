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
                "mirroropen", "mirrorclose", "mirrorwidth", "mirrorfps", "mirroract",
                "livesess", "livefps", "livewidth", "livestart", "livestop",
                "livepriv", "liveconfirm", "livemeta", "livewrap", "liveimg"):
        assert f'id="{eid}"' in page, eid
    for zh in ("保活会话", "镜像 / 录制", "能力表与待评审提案", "按需快照",
               "应用", "操作", "影响", "幂等", "通道（实测风险）", "证据",
               "光标位移", "外部输入", "检出率", "已运行", "调试端口",
               "无干扰", "有干扰", "未确认", "微信快照含私聊画面",
               "打开镜像窗口", "关闭镜像窗口", "主机可见动作",
               "实时镜像（web）", "开始实时画面", "微信实时画面含私聊内容",
               "未做归因", "不写磁盘"):
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


# ---------------------------------------------------------------- live web mirror (no capture)

class _ShortReader:
    """Pipe stand-in that returns at most `chunk` bytes per read (Windows short reads)."""

    def __init__(self, data, chunk=3):
        self.data, self.chunk, self.pos = data, chunk, 0

    def read(self, n):
        out = self.data[self.pos:self.pos + min(n, self.chunk)]
        self.pos += len(out)
        return out


def test_read_exact_reassembles_short_reads_and_stops_at_eof():
    payload = bytes(range(256)) * 4
    assert gd._read_exact(_ShortReader(payload, chunk=7), len(payload)) == payload
    assert gd._read_exact(_ShortReader(b"abc", chunk=1), 10) == b"abc"
    assert gd._read_exact(_ShortReader(b"", chunk=1), 4) == b""


def test_live_gate_privacy_liveness_and_exe(monkeypatch, tmp_path):
    import hidden_sessions

    exe = tmp_path / "gbmirror.exe"
    exe.write_bytes(b"")
    monkeypatch.setattr(gd, "GBMIRROR_EXE", exe)
    rec = {"name": "wechat", "kind": "wechat", "desktop": "GBWeChatKeepAlive", "pid": 1, "alive": True}
    monkeypatch.setattr(hidden_sessions, "get_session", lambda name: rec if name == "wechat" else None)

    body, code = gd.live_gate("wechat", False)[1]
    assert code == 403 and "live view exposes private chats" in body["error"]
    assert gd.live_gate("wechat", True)[1] is None
    assert gd.live_gate("nope", False)[1][1] == 404

    dead = dict(rec, alive=False)
    monkeypatch.setattr(hidden_sessions, "get_session", lambda name: dead)
    assert gd.live_gate("wechat", True)[1][1] == 409

    monkeypatch.setattr(hidden_sessions, "get_session", lambda name: rec)
    monkeypatch.setattr(gd, "GBMIRROR_EXE", tmp_path / "missing.exe")
    assert gd.live_gate("wechat", True)[1][1] == 500


def test_live_hub_clamps_stream_params():
    rec = {"desktop": "GBTraeKeepAlive", "pid": 7, "kind": "trae"}
    hub = gd.LiveHub("trae", rec, fps=999, width=99999, quality=200)
    assert (hub.fps, hub.width, hub.quality) == (30, 2560, 95)
    low = gd.LiveHub("trae", rec, fps=0, width=1, quality=1)
    assert (low.fps, low.width, low.quality) == (1, 320, 30)
    assert hub.dead() is True  # never started: no subprocess
    hub.acquire(); hub.acquire(); hub.release()
    assert hub.viewers == 1 and hub.status()["seq"] == 0


class _StubHub:
    def __init__(self, session="trae", dead=False, viewers=0, idle=0.0):
        self.session, self._dead, self.viewers = session, dead, viewers
        self.last_view = time.time() - idle
        self.stopped = False

    def dead(self):
        return self._dead

    def shutdown(self):
        self.stopped = True


def test_live_hub_replaces_a_dead_stream(monkeypatch):
    monkeypatch.setattr(gd, "live_gate", lambda s, c: ({"desktop": "D", "pid": 1, "kind": "trae"}, None))
    made = []

    class Fresh(_StubHub):
        def __init__(self, session, rec, fps, width, quality):
            super().__init__(session)
            made.append(self)

        def start(self):
            pass

    old = _StubHub(dead=True)
    monkeypatch.setattr(gd, "LIVE", {"trae": old})
    monkeypatch.setattr(gd, "LiveHub", Fresh)
    hub, err = gd.live_hub("trae", False)
    assert err is None and hub is made[0] and old.stopped is True
    assert gd.LIVE["trae"] is hub


def test_live_hub_caps_concurrent_streams(monkeypatch):
    monkeypatch.setattr(gd, "live_gate", lambda s, c: ({"desktop": "D", "pid": 1, "kind": "trae"}, None))
    monkeypatch.setattr(gd, "LiveHub", _StubHub)
    monkeypatch.setattr(gd, "LIVE", {"trae": _StubHub("trae"), "wechat": _StubHub("wechat")})
    hub, err = gd.live_hub("third", False)
    assert hub is None and err[1] == 429 and "too many live streams" in err[0]["error"]
    assert len(gd.LIVE) == gd.LIVE_MAX_HUBS


def test_live_stop_and_status_without_a_stream(monkeypatch):
    monkeypatch.setattr(gd, "LIVE", {})
    assert gd.live_status("trae")["running"] is False
    body, code = gd.live_stop("trae")
    assert code == 409 and body["error"] == "live stream not running"
    hub = _StubHub()
    monkeypatch.setattr(gd, "LIVE", {"trae": hub})
    body, code = gd.live_stop("trae")
    assert code == 200 and body["stopped"] is True and hub.stopped is True
    assert gd.LIVE == {}


def test_live_reap_once_stops_only_unwatched_idle_streams(monkeypatch):
    watched = _StubHub(viewers=1, idle=999)
    idle = _StubHub(viewers=0, idle=gd.LIVE_IDLE_S + 1)
    fresh = _StubHub(viewers=0, idle=0)
    dead = _StubHub(dead=True, viewers=0, idle=0)
    monkeypatch.setattr(gd, "LIVE", {"a": watched, "b": idle, "c": fresh, "d": dead})
    assert gd.live_reap_once() == 2
    assert watched.stopped is False and fresh.stopped is False
    assert idle.stopped is True and dead.stopped is True
    assert set(gd.LIVE) == {"a", "c"}


class _FakeSock:
    def __init__(self, fail_after=None):
        self.buf, self.writes, self.fail_after = bytearray(), 0, fail_after

    def write(self, b):
        if self.fail_after is not None and self.writes >= self.fail_after:
            raise BrokenPipeError("viewer closed the tab")
        self.writes += 1
        self.buf += b

    def flush(self):
        pass


class _FakeHandler:
    def __init__(self, sock):
        self.wfile, self.headers, self.close_connection = sock, {}, False

    def send_response(self, code):
        self.code = code

    def send_header(self, k, v):
        self.headers[k] = v

    def end_headers(self):
        pass


class _FrameHub:
    def __init__(self, frames):
        self.frames, self.viewers, self.touches = frames, 0, 0
        self.stop = gd.threading.Event()

    def acquire(self):
        self.viewers += 1

    def release(self):
        self.viewers -= 1

    def touch(self):
        self.touches += 1

    def next_frame(self, last, timeout=2.0):
        if last < len(self.frames):
            return last + 1, self.frames[last], False
        self.stop.set()
        return last, None, True


def test_stream_live_writes_mjpeg_parts_and_releases_viewer():
    hub = _FrameHub([b"\xff\xd8frame-one\xff\xd9", b"\xff\xd8frame-two\xff\xd9"])
    sock = _FakeSock()
    h = _FakeHandler(sock)
    gd.Handler._stream_live(h, hub)
    assert h.code == 200 and h.close_connection is True
    assert h.headers["Content-Type"] == f"multipart/x-mixed-replace; boundary={gd.LIVE_BOUNDARY}"
    body = bytes(sock.buf)
    assert body.count(b"--gbframe\r\nContent-Type: image/jpeg\r\n") == 2
    assert b"X-GB-Seq: 1" in body and b"X-GB-Seq: 2" in body
    assert b"frame-one" in body and b"frame-two" in body
    assert hub.viewers == 0 and hub.touches == 2  # released even after normal eof


def test_stream_live_survives_a_disconnected_viewer():
    hub = _FrameHub([b"jpeg-a", b"jpeg-b"])
    h = _FakeHandler(_FakeSock(fail_after=2))
    gd.Handler._stream_live(h, hub)  # must not raise
    assert hub.viewers == 0