"""GUIBridge read-only localhost observation dashboard (probe-side, single approve).

A single-file stdlib HTTP server + embedded single-page UI that aggregates the EXISTING
probe artefacts into one management/observation view. Observation is read-only: it never
writes to the engine, the frozen capability table, or any keep-alive session. Side effects
are limited to (a) reading files, (b) an on-demand one-frame hidden-desktop snapshot via
`gbmirror --desktop` (read-only, zero-interference, re-measured per call), and (c) an
EXPLICIT user-clicked open/close of the native mirror window (`POST /api/mirror/open|close`).
(c) is host-visible -- a real window appears on the user's desktop and may take the
foreground -- so its host impact is measured and reported, never claimed to be zero, and
closing refuses any target whose image is not gbmirror.exe. WeChat snapshots expose private
chats and therefore require an explicit confirm flag; the BMP is deleted right after it
is read into the response so nothing readable persists on disk.

Data sources (all read-only):
  * sessions   -> hidden_sessions.list_sessions() (live pid re-check)
  * mirror/rec -> var/experiments/gbmirror_status.json (exported by gbmirror display)
  * capability -> packages/routing/capabilities.draft.yaml (frozen) + docs/proposals/*.md
  * events     -> var/experiments/<run_id>/*.json (FocusGuard four-state / capture verdicts)

Bind is loopback-only. Not part of the frozen contract / engine control plane
(apps/desktop-agent); changing THAT would need double approve. This is probe tooling.

Run: python -X utf8 src/probe/gbdash.py [--port 8710]
"""

from __future__ import annotations

import argparse
import base64
import ctypes
import json
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[2]
PROBE = Path(__file__).resolve().parent
for _p in (ROOT / "packages", PROBE):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

RUNS = ROOT / "var" / "experiments"
STATUS_PATH = RUNS / "gbmirror_status.json"
REGISTRY_PATH = RUNS / "hidden_sessions.json"
GBMIRROR_EXE = PROBE / "gbmirror" / "target" / "release" / "gbmirror.exe"
SNAP_TMP = RUNS / "gbdash_snap.bmp"
PROPOSALS = ROOT / "docs" / "proposals"

FOUR_STATES = {
    "success_no_interference_observed",
    "success_with_interference",
    "failed",
    "unconfirmed",
}
_RUN_DIR = re.compile(r"^\d{8}T\d{6}Z$")
MIRROR_STALE_S = 5.0


# ---------------------------------------------------------------- pure helpers

def walk_records(obj, path=""):
    """Yield (label, dict) for every dict that carries a focus/capture conclusion.

    Tolerant of the per-probe json shapes: four-state action records, capture
    zero-interference blocks, and verdict blocks. Children of a matched dict are
    still walked but rarely re-match (evidence sub-dicts carry no trigger key).
    """
    if isinstance(obj, dict):
        state = obj.get("state")
        if (
            (isinstance(state, str) and state in FOUR_STATES)
            or "zero_interference_observed" in obj
            or "unexpected_focus_switch" in obj
            or "verdict" in obj
        ):
            yield (path or "$"), obj
        for key, val in obj.items():
            yield from walk_records(val, f"{path}.{key}" if path else str(key))
    elif isinstance(obj, list):
        for i, val in enumerate(obj):
            yield from walk_records(val, f"{path}[{i}]")


def normalize_event(run_id, fname, label, d):
    state = d.get("state")
    return {
        "run": run_id,
        "file": fname,
        "label": label,
        "state": state if isinstance(state, str) and state in FOUR_STATES else None,
        "channel": d.get("channel"),
        "risk": d.get("risk"),
        "cursor": d.get("cursor_displacement", d.get("host_cursor_displacement")),
        "focus_switch": d.get("unexpected_focus_switch", d.get("host_foreground_changed")),
        "external": d.get("external_input_during_window"),
        "zero": d.get("zero_interference_observed"),
        "verdict": d.get("verdict"),
        "detection_rate": d.get("detection_rate"),
        "fp_rate": d.get("false_positive_rate"),
    }


def collect_events(runs_dir=RUNS, limit=30):
    runs_dir = Path(runs_dir)
    if not runs_dir.is_dir():
        return []
    dirs = sorted(
        (p for p in runs_dir.iterdir() if p.is_dir() and _RUN_DIR.match(p.name)),
        key=lambda p: p.name,
        reverse=True,
    )[: max(1, int(limit))]
    events = []
    for d in dirs:
        for f in sorted(d.glob("*.json")):
            try:
                obj = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for label, rec in walk_records(obj):
                events.append(normalize_event(d.name, f.name, label, rec))
            if f.name == "focusguard_reliability.json" and isinstance(obj, dict):
                events.append(normalize_event(d.name, f.name, "$reliability", obj))
    return events


def mirror_status(path=STATUS_PATH, now=None):
    now = time.time() if now is None else now
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"running": False}
    if not isinstance(d, dict):
        return {"running": False}
    age = now - float(d.get("ts", 0))
    d["age_s"] = round(age, 1)
    d["running"] = age <= MIRROR_STALE_S
    rp = Path(d.get("rec_path") or "")
    if not rp.is_absolute():
        rp = ROOT / rp
    if rp.exists():
        st = rp.stat()
        d["rec_size"] = st.st_size
        d["rec_mtime"] = st.st_mtime
    return d


def snapshot_gate(kind, confirm):
    """WeChat renders private chats; only an explicit confirm may pull it."""
    if kind == "wechat" and not confirm:
        return False, "wechat snapshot exposes private chats; explicit confirm required"
    return True, ""


def uptime(created_at, now=None):
    if not created_at:
        return None
    now = time.time() if now is None else now
    try:
        ts = datetime.fromisoformat(str(created_at)).timestamp()
    except ValueError:
        return None
    sec = max(0, int(now - ts))
    d, rem = divmod(sec, 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f"{d}d {h}h {m}m"
    if h:
        return f"{h}h {m}m"
    return f"{m}m"


def capability_view():
    import yaml
    from routing.capability_table import DEFAULT_TABLE

    data = yaml.safe_load(Path(DEFAULT_TABLE).read_text(encoding="utf-8")) or {}
    entries = []
    for e in data.get("entries") or []:
        chans = [
            {"channel": name, "supported": bool(spec.get("supported", False)),
             "risk": spec.get("risk", "unknown")}
            for name, spec in (e.get("channels") or {}).items()
        ]
        entries.append({
            "app": e.get("app"),
            "operation": e.get("operation"),
            "impact": e.get("impact", "low"),
            "idempotent": bool(e.get("idempotent", True)),
            "channels": chans,
            "evidence": e.get("evidence") or [],
            "notes": (e.get("notes") or "").strip(),
            "unsupported_reason": e.get("unsupported_reason"),
        })
    proposals = []
    if PROPOSALS.is_dir():
        for f in sorted(PROPOSALS.glob("*.md")):
            first = f.read_text(encoding="utf-8").splitlines()
            title = next((ln.lstrip("# ").strip() for ln in first if ln.strip()), f.name)
            proposals.append({"file": f.name, "title": title})
    return {"status": data.get("status"), "schema_version": data.get("schema_version"),
            "entries": entries, "proposals": proposals}


def sessions_view(now=None):
    import hidden_sessions

    out = []
    for s in hidden_sessions.list_sessions():
        s = dict(s)
        s["uptime"] = uptime(s.get("created_at"), now)
        out.append(s)
    return out


def take_snapshot(session, confirm):
    """One-frame read-only hidden-desktop capture; BMP deleted after read."""
    import hidden_sessions

    rec = hidden_sessions.get_session(session)
    if not rec:
        return {"ok": False, "error": f"unknown session {session}"}, 404
    ok, reason = snapshot_gate(rec.get("kind"), confirm)
    if not ok:
        return {"ok": False, "error": reason}, 403
    if not rec.get("alive"):
        return {"ok": False, "error": "session not alive"}, 409
    if not GBMIRROR_EXE.exists():
        return {"ok": False, "error": "gbmirror.exe not built"}, 500
    SNAP_TMP.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [str(GBMIRROR_EXE), "--desktop", str(rec["desktop"]), "--pid", str(rec["pid"]),
         "--out", str(SNAP_TMP), "--frames", "1"],
        cwd=ROOT, capture_output=True, text=True, timeout=60,
    )
    meta = {}
    try:
        meta = json.loads(proc.stdout)
    except ValueError:
        meta = {"raw": proc.stdout[-500:], "stderr": proc.stderr[-500:]}
    if not SNAP_TMP.exists():
        return {"ok": False, "error": "capture produced no bmp", "meta": meta}, 500
    blob = SNAP_TMP.read_bytes()
    SNAP_TMP.unlink()  # never leave a readable (possibly private) frame on disk
    return {
        "ok": True,
        "session": session,
        "kind": rec.get("kind"),
        "zero_interference_observed": meta.get("zero_interference_observed"),
        "avg_capture_ms": meta.get("avg_capture_ms"),
        "content_bbox": meta.get("content_bbox"),
        "image_b64": base64.b64encode(blob).decode("ascii"),
    }, 200


# ------------------------------------------- native mirror window control (explicit user action)
#
# Opening the native mirror window is HOST-VISIBLE: a real window appears on the user's desktop
# and may take the foreground. It is therefore NOT a read-only observation, and it only happens
# on an explicit button click (POST). The host impact is measured around the launch and reported
# as measured -- never claimed to be zero. Closing verifies the target image is gbmirror.exe, so
# a keep-alive session (wechat/trae) can never be terminated through this path.

MIRROR_LOCK = threading.Lock()
LAUNCHED: dict = {}
STILL_ACTIVE = 259
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_TERMINATE = 0x0001
WM_CLOSE = 0x0010


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _k32():
    k = ctypes.windll.kernel32
    k.OpenProcess.restype = ctypes.c_void_p
    k.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    k.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    k.QueryFullProcessImageNameW.argtypes = [
        ctypes.c_void_p, ctypes.c_ulong, ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_ulong)]
    k.TerminateProcess.argtypes = [ctypes.c_void_p, ctypes.c_uint]
    k.CloseHandle.argtypes = [ctypes.c_void_p]
    return k


def _u32():
    u = ctypes.windll.user32
    u.GetForegroundWindow.restype = ctypes.c_void_p
    u.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
    u.GetWindowThreadProcessId.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
    u.PostMessageW.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_void_p, ctypes.c_void_p]
    u.EnumWindows.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    return u


def host_fg():
    return int(_u32().GetForegroundWindow() or 0)


def host_cursor():
    p = POINT()
    _u32().GetCursorPos(ctypes.byref(p))
    return (p.x, p.y)


def pid_alive(pid):
    k = _k32()
    h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    code = ctypes.c_ulong()
    ok = k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return bool(ok) and code.value == STILL_ACTIVE


def pid_image(pid):
    k = _k32()
    h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return None
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.c_ulong(1024)
    ok = k.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n))
    k.CloseHandle(h)
    return Path(buf.value).name if ok else None


def launch_args(width=1400, fps=30):
    w = max(400, min(3840, int(width)))
    f = max(1, min(60, int(fps)))
    return [str(GBMIRROR_EXE), "--registry", str(REGISTRY_PATH), "--width", str(w), "--fps", str(f)]


def _dist(a, b):
    return int(round(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5))


def interference_summary(samples, fg0, c0):
    """Poll-based host impact over (fg, cursor) samples. <2ms switches can be missed."""
    switches, prev, maxd = 0, fg0, 0
    for fg, c in samples:
        if fg != prev:
            switches += 1
        prev = fg
        maxd = max(maxd, _dist(c0, c))
    last_fg = samples[-1][0] if samples else fg0
    last_c = samples[-1][1] if samples else c0
    return {
        "fg_before": fg0, "fg_after": last_fg, "fg_changed": last_fg != fg0,
        "fg_switches": switches, "cursor_displacement": _dist(c0, last_c),
        "max_disp_during": maxd, "samples": len(samples),
        "zero_interference_observed": switches == 0 and maxd == 0,
    }


def measure_window(seconds=1.5, poll_s=0.005, fg0=None, c0=None):
    fg0 = host_fg() if fg0 is None else fg0
    c0 = host_cursor() if c0 is None else c0
    samples = []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        samples.append((host_fg(), host_cursor()))
        time.sleep(poll_s)
    out = interference_summary(samples, fg0, c0)
    out["window_s"] = seconds
    out["poll_ms"] = poll_s * 1000
    return out


def running_mirror_pid():
    m = mirror_status()
    pid = m.get("pid")
    if m.get("running") and pid and pid_alive(pid) and (pid_image(pid) or "").lower() == "gbmirror.exe":
        return int(pid)
    for p in list(LAUNCHED):
        if pid_alive(p) and (pid_image(p) or "").lower() == "gbmirror.exe":
            return int(p)
    return None


def open_mirror(width=1400, fps=30):
    if not GBMIRROR_EXE.exists():
        return {"ok": False, "error": "gbmirror.exe not built"}, 500
    with MIRROR_LOCK:
        pid = running_mirror_pid()
        if pid:
            return {"ok": True, "already_running": True, "pid": pid, "host_visible": True}, 200
        fg0, c0 = host_fg(), host_cursor()
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(
            launch_args(width, fps), cwd=str(ROOT),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags,
        )
        LAUNCHED[proc.pid] = {"ts": time.time(), "width": int(width), "fps": int(fps)}
        host = measure_window(1.5, fg0=fg0, c0=c0)
        return {"ok": True, "already_running": False, "pid": proc.pid,
                "host_visible": True, "host": host}, 200


def _post_close(pid):
    u = _u32()
    hits = []

    @ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
    def cb(hwnd, _lp):
        owner = ctypes.c_ulong()
        u.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid:
            u.PostMessageW(hwnd, WM_CLOSE, None, None)
            hits.append(hwnd)
        return 1

    u.EnumWindows(cb, None)
    return len(hits)


def close_mirror(timeout_s=4.0):
    with MIRROR_LOCK:
        pid = running_mirror_pid()
        if not pid:
            return {"ok": False, "error": "mirror window not running"}, 409
        img = (pid_image(pid) or "").lower()
        if img != "gbmirror.exe":
            return {"ok": False, "error": f"refuse to close pid {pid} ({img or 'unknown image'})"}, 403
        n = _post_close(pid)
        end = time.monotonic() + timeout_s
        while time.monotonic() < end and pid_alive(pid):
            time.sleep(0.05)
        forced = False
        if pid_alive(pid):
            k = _k32()
            h = k.OpenProcess(PROCESS_TERMINATE, False, pid)
            if h:
                k.TerminateProcess(h, 0)
                k.CloseHandle(h)
                forced = True
            time.sleep(0.2)
        closed = not pid_alive(pid)
        LAUNCHED.pop(pid, None)
        return {"ok": closed, "pid": pid, "windows_messaged": n, "forced": forced,
                "graceful": n > 0 and not forced, "closed": closed}, (200 if closed else 500)


# ---------------------------------------------------------------- http server

class Handler(BaseHTTPRequestHandler):
    server_version = "GBDash/1.0"

    def log_message(self, *args):  # quiet
        pass

    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        raw = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        path = u.path
        try:
            if path == "/":
                self._send(200, PAGE, "text/html; charset=utf-8")
            elif path == "/api/sessions":
                self._send(200, {"sessions": sessions_view(), "ts": time.time()})
            elif path == "/api/mirror":
                m = mirror_status()
                m["exe_built"] = GBMIRROR_EXE.exists()
                m["launched_by_dashboard"] = m.get("pid") in LAUNCHED
                self._send(200, m)
            elif path == "/api/capability":
                self._send(200, capability_view())
            elif path == "/api/events":
                limit = min(200, max(1, int(q.get("limit", "30"))))
                self._send(200, {"events": collect_events(limit=limit)})
            elif path == "/api/snapshot":
                body, code = take_snapshot(q.get("session", "trae"), q.get("confirm") == "1")
                self._send(code, body)
            else:
                self._send(404, {"ok": False, "error": "not found"})
        except Exception as exc:  # surface as json, never crash the loop
            self._send(500, {"ok": False, "error": repr(exc)})

    def do_POST(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length:
                self.rfile.read(length)
        except (OSError, ValueError):
            pass
        try:
            if u.path == "/api/mirror/open":
                body, code = open_mirror(q.get("width", 1400), q.get("fps", 30))
            elif u.path == "/api/mirror/close":
                body, code = close_mirror()
            else:
                body, code = {"ok": False, "error": "not found"}, 404
            self._send(code, body)
        except Exception as exc:
            self._send(500, {"ok": False, "error": repr(exc)})


PAGE = """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GUIBridge 观测台</title>
<style>
:root{
  color-scheme:dark;
  --bg:#080a0d; --panel:#0f141a; --panel2:#0b1015; --sunk:#070a0d;
  --line:#1c242c; --line2:#2a353f;
  --ink:#e9eff5; --dim:#93a1ae; --faint:#61707d;
  --amber:#ffb020; --amber-soft:rgba(255,176,32,.12); --amber-line:rgba(255,176,32,.38);
  --green:#3ddc84; --green-soft:rgba(61,220,132,.12);
  --red:#ff6a5e; --red-soft:rgba(255,106,94,.12);
  --slate-soft:rgba(147,161,174,.1);
  --display:"Bahnschrift SemiCondensed","Bahnschrift","DIN Alternate","Microsoft YaHei UI",sans-serif;
  --body:"Microsoft YaHei UI","Microsoft YaHei","PingFang SC","Hiragino Sans GB",sans-serif;
  --mono:"Cascadia Mono","Cascadia Code","Consolas","SF Mono",monospace;
}
*{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0;background:var(--bg);color:var(--ink);
  font:14px/1.6 var(--body);-webkit-font-smoothing:antialiased;
  font-variant-numeric:tabular-nums;overflow-x:hidden;
}
body::before{
  content:"";position:fixed;inset:0;z-index:0;pointer-events:none;
  background:
    radial-gradient(900px 420px at 12% -8%,rgba(255,176,32,.09),transparent 70%),
    radial-gradient(700px 380px at 96% 4%,rgba(61,220,132,.05),transparent 72%),
    repeating-linear-gradient(0deg,rgba(147,161,174,.045) 0 1px,transparent 1px 34px),
    repeating-linear-gradient(90deg,rgba(147,161,174,.045) 0 1px,transparent 1px 34px);
}
.grain{
  position:fixed;inset:0;z-index:60;pointer-events:none;opacity:.04;mix-blend-mode:overlay;
  background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='140' height='140'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='.85' numOctaves='3'/%3E%3C/filter%3E%3Crect width='140' height='140' filter='url(%23n)'/%3E%3C/svg%3E");
}
::selection{background:var(--amber);color:#0a0c0f}
::-webkit-scrollbar{width:10px;height:10px}
::-webkit-scrollbar-track{background:var(--sunk)}
::-webkit-scrollbar-thumb{background:#212b34;border:2px solid var(--sunk);border-radius:6px}
::-webkit-scrollbar-thumb:hover{background:#33414d}

/* ---------- header ---------- */
.top{
  position:relative;z-index:2;display:flex;align-items:center;gap:22px;flex-wrap:wrap;
  padding:16px 26px 14px;border-bottom:1px solid var(--line);
  background:linear-gradient(180deg,rgba(15,20,26,.96),rgba(8,10,13,.86));
  backdrop-filter:blur(6px);
}
.mark{display:flex;align-items:center;gap:13px;min-width:0}
.mark svg{flex:none;filter:drop-shadow(0 0 10px rgba(255,176,32,.35))}
.mark h1{
  margin:0;font:600 25px/1 var(--display);letter-spacing:.2em;color:var(--ink);
  text-transform:uppercase;
}
.mark h1 em{font-style:normal;color:var(--amber)}
.mark p{margin:5px 0 0;font-size:11.5px;color:var(--faint);letter-spacing:.14em}
.strip{display:flex;gap:8px;flex-wrap:wrap;margin-left:auto}
.chip{
  display:flex;align-items:baseline;gap:7px;padding:5px 11px;
  border:1px solid var(--line2);background:var(--panel2);border-radius:3px;
}
.chip span{font-size:10.5px;color:var(--faint);letter-spacing:.1em}
.chip b{font:600 15px/1 var(--display);color:var(--amber);letter-spacing:.04em}
.ctl{display:flex;align-items:center;gap:14px}
#ts{font:11.5px/1 var(--mono);color:var(--faint);letter-spacing:.02em}
#ts.flash{animation:flash .7s ease-out}
@keyframes flash{0%{color:var(--amber)}100%{color:var(--faint)}}
.toggle{display:flex;align-items:center;gap:7px;font-size:11.5px;color:var(--dim);cursor:pointer;user-select:none}
.toggle input{accent-color:var(--amber);width:14px;height:14px;cursor:pointer}

/* ---------- layout ---------- */
main{
  position:relative;z-index:1;display:grid;grid-template-columns:repeat(12,1fr);
  gap:16px;padding:20px 26px 8px;align-items:start;
}
.panel{
  position:relative;grid-column:span 12;padding:16px 18px 18px;
  background:linear-gradient(180deg,var(--panel),var(--panel2));
  border:1px solid var(--line);border-radius:4px;
  box-shadow:0 18px 40px -28px #000,inset 0 1px 0 rgba(255,255,255,.025);
  animation:rise .55s cubic-bezier(.2,.75,.2,1) both;animation-delay:calc(var(--i,0)*80ms);
}
@keyframes rise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
.panel::before,.panel::after{
  content:"";position:absolute;width:11px;height:11px;border:1px solid var(--amber);opacity:.45;pointer-events:none;
}
.panel::before{top:-1px;left:-1px;border-right:0;border-bottom:0}
.panel::after{bottom:-1px;right:-1px;border-left:0;border-top:0}
.p7{grid-column:span 7}.p5{grid-column:span 5}
.phead{display:flex;align-items:center;gap:11px;padding-bottom:11px;margin-bottom:14px;border-bottom:1px solid var(--line)}
.idx{font:600 11px/1 var(--mono);color:var(--amber);letter-spacing:.1em;padding-top:2px}
.phead h2{margin:0;font:600 15px/1.2 var(--display);letter-spacing:.14em;color:var(--ink)}
.hint{margin-left:auto;font-size:11px;color:var(--faint);letter-spacing:.04em;text-align:right}

/* ---------- cards / readouts ---------- */
.cards{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(238px,1fr))}
.card{
  position:relative;padding:12px 14px 13px 16px;background:var(--sunk);
  border:1px solid var(--line);border-radius:3px;overflow:hidden;
  transition:border-color .18s,transform .18s;
}
.card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:2px;background:var(--green);opacity:.75}
.card.dead::before{background:var(--faint);opacity:.5}
.card:hover{border-color:var(--line2);transform:translateY(-2px)}
.cardhead{display:flex;align-items:center;gap:9px;margin-bottom:9px}
.cardhead h3{margin:0;font:600 16px/1.2 var(--display);letter-spacing:.06em}
.cardhead .badge{margin-left:auto}
.led{flex:none;width:8px;height:8px;border-radius:50%;background:var(--faint)}
.led.live{background:var(--green);box-shadow:0 0 0 0 rgba(61,220,132,.55);animation:beat 2.4s infinite}
.led.rec{background:var(--red);box-shadow:0 0 9px rgba(255,106,94,.8);animation:beat 1.1s infinite}
@keyframes beat{0%{box-shadow:0 0 0 0 rgba(61,220,132,.5)}70%{box-shadow:0 0 0 7px rgba(61,220,132,0)}100%{box-shadow:0 0 0 0 rgba(61,220,132,0)}}
.kv{display:flex;justify-content:space-between;align-items:baseline;gap:10px;padding:3px 0;border-top:1px dashed rgba(147,161,174,.1)}
.kv:first-of-type{border-top:0}
.kv span{font-size:11.5px;color:var(--faint);letter-spacing:.05em;flex:none}
.kv b{font:500 12px/1.5 var(--mono);color:var(--ink);word-break:break-all;text-align:right}
.gauge{display:flex;align-items:flex-end;gap:22px;padding:2px 0 14px;margin-bottom:12px;border-bottom:1px solid var(--line)}
.readout{display:flex;flex-direction:column;gap:3px}
.readout .num{font:600 42px/.9 var(--display);letter-spacing:.02em;color:var(--amber);text-shadow:0 0 22px rgba(255,176,32,.28)}
.readout.sm .num{font-size:26px;color:var(--ink);text-shadow:none}
.readout .unit{font-size:10.5px;color:var(--faint);letter-spacing:.16em}
.gauge .state{margin-left:auto;display:flex;align-items:center;gap:8px;padding-bottom:6px}

/* ---------- badges ---------- */
.badge{
  display:inline-block;padding:1px 7px;border-radius:2px;border:1px solid;
  font:600 11px/1.6 var(--body);letter-spacing:.03em;white-space:nowrap;
}
.ok{background:var(--green-soft);color:var(--green);border-color:rgba(61,220,132,.4)}
.warn{background:var(--amber-soft);color:var(--amber);border-color:var(--amber-line)}
.bad{background:var(--red-soft);color:var(--red);border-color:rgba(255,106,94,.4)}
.mut{background:var(--slate-soft);color:var(--dim);border-color:var(--line2)}
.raw{display:block;font:10px/1.5 var(--mono);color:var(--faint);word-break:break-all}
code{font:11px/1.5 var(--mono);background:rgba(147,161,174,.09);border:1px solid var(--line);padding:0 4px;border-radius:2px;color:var(--dim)}
.dash{color:var(--faint)}

/* ---------- tables ---------- */
.scroll{max-height:366px;overflow:auto;border:1px solid var(--line);border-radius:3px;background:var(--sunk)}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{text-align:left;padding:7px 10px;border-bottom:1px solid rgba(28,36,44,.9);vertical-align:top}
th{
  position:sticky;top:0;z-index:1;background:#0d1217;color:var(--faint);
  font:600 10.5px/1.5 var(--body);letter-spacing:.12em;white-space:nowrap;
  border-bottom:1px solid var(--line2);
}
tbody tr{transition:background .14s}
tbody tr:hover{background:rgba(255,176,32,.045);box-shadow:inset 2px 0 0 var(--amber)}
td .badge{margin:0 3px 2px 0}
.chan{display:inline-flex;align-items:center;gap:5px;margin:0 8px 4px 0;padding:2px 6px;border:1px solid var(--line);border-radius:2px;background:rgba(147,161,174,.04)}
.chan code{border:0;background:none;padding:0;color:var(--ink);font-size:11px}
.chan i{font-style:normal;font-size:10.5px;letter-spacing:.03em}
.chan i.ok{color:var(--green)}.chan i.warn{color:var(--amber)}.chan i.bad{color:var(--red)}.chan i.mut{color:var(--faint)}
.num{font-family:var(--mono)}

/* ---------- controls ---------- */
.row{display:flex;gap:9px;align-items:center;flex-wrap:wrap;margin-bottom:12px}
button,select{
  font:500 12px/1.4 var(--body);color:var(--ink);background:#131a21;
  border:1px solid var(--line2);border-radius:3px;padding:6px 11px;cursor:pointer;
  transition:background .16s,border-color .16s,transform .08s;
}
select{appearance:none;padding-right:26px;background-image:url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6'%3E%3Cpath d='M0 0l5 6 5-6z' fill='%2393a1ae'/%3E%3C/svg%3E");background-repeat:no-repeat;background-position:right 9px center}
button:hover,select:hover{border-color:var(--amber-line);background:#182029}
button:active{transform:translateY(1px)}
button:disabled{opacity:.38;cursor:not-allowed}
button:disabled:hover{background:#131a21;border-color:var(--line2)}
button.primary:disabled:hover{background:var(--amber);border-color:var(--amber)}
button.primary{background:var(--amber);border-color:var(--amber);color:#0a0c0f;font-weight:700;letter-spacing:.06em}
button.primary:hover{background:#ffc44d;border-color:#ffc44d}
:focus-visible{outline:2px solid var(--amber);outline-offset:2px}
.count{font:11.5px/1 var(--mono);color:var(--faint);letter-spacing:.03em}
.priv{display:flex;align-items:center;gap:7px;font-size:12px;color:var(--amber);cursor:pointer}
.priv input{accent-color:var(--amber);width:14px;height:14px}
.note{font-size:11.5px;color:var(--faint);line-height:1.7;margin-top:10px}
.note b{color:var(--dim);font-weight:600}
details{margin-top:11px;border-top:1px dashed rgba(147,161,174,.14);padding-top:9px}
summary{cursor:pointer;font-size:11.5px;color:var(--dim);letter-spacing:.06em;list-style:none}
summary::-webkit-details-marker{display:none}
summary::before{content:"▸ ";color:var(--amber)}
details[open] summary::before{content:"▾ "}
.dict{display:grid;gap:6px;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));margin-top:9px}
.dict div{display:flex;align-items:center;gap:8px}

/* ---------- snapshot ---------- */
.snapframe{position:relative;margin-top:4px;border:1px solid var(--line2);border-radius:3px;background:#000;padding:6px}
.snapframe::before,.snapframe::after{content:"";position:absolute;width:14px;height:14px;border:1px solid var(--amber);opacity:.6}
.snapframe::before{top:-1px;left:-1px;border-right:0;border-bottom:0}
.snapframe::after{bottom:-1px;right:-1px;border-left:0;border-top:0}
img.snap{display:block;max-width:100%;border-radius:2px;animation:fade .4s ease-out}
@keyframes fade{from{opacity:0}to{opacity:1}}
.capbar{display:flex;gap:12px;flex-wrap:wrap;align-items:center;padding:8px 2px 0;font:11.5px/1.5 var(--mono);color:var(--dim)}
.empty{padding:22px 14px;text-align:center;color:var(--faint);font-size:12px;border:1px dashed var(--line2);border-radius:3px;background:var(--sunk)}
footer{
  position:relative;z-index:1;display:flex;gap:18px;flex-wrap:wrap;align-items:center;
  padding:14px 26px 26px;color:var(--faint);font-size:11px;letter-spacing:.04em;
}
footer .sep{width:1px;height:12px;background:var(--line2)}
@media (max-width:1080px){
  .p7,.p5{grid-column:span 12}
  .strip{margin-left:0;order:3;width:100%}
  main{padding:16px}
  .top{padding:14px 16px}
  footer{padding:12px 16px 22px}
}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body>
<div class="grain" aria-hidden="true"></div>
<header class="top">
  <div class="mark">
    <svg width="30" height="30" viewBox="0 0 30 30" aria-hidden="true">
      <path d="M2 22h26M5 22V13M25 22V13M2 13c6-8 20-8 26 0" fill="none" stroke="#ffb020" stroke-width="1.6"/>
      <circle cx="15" cy="8.4" r="2.1" fill="#3ddc84"/>
      <path d="M10 22v-4M15 22v-6M20 22v-4" stroke="#93a1ae" stroke-width="1.2"/>
    </svg>
    <div>
      <h1>GUI<em>Bridge</em></h1>
      <p>语义 GUI 控制中间件 · 只读观测台</p>
    </div>
  </div>
  <div class="strip">
    <div class="chip"><span>存活会话</span><b id="hSessions">—</b></div>
    <div class="chip"><span>镜像帧率</span><b id="hMirror">—</b></div>
    <div class="chip"><span>事件记录</span><b id="hEvents">—</b></div>
  </div>
  <div class="ctl">
    <span id="ts" aria-live="polite">连接中…</span>
    <label class="toggle"><input type="checkbox" id="auto" checked> 3 秒自动刷新</label>
  </div>
</header>
<main>
  <section class="panel p7" style="--i:0">
    <div class="phead"><span class="idx">01</span><h2>保活会话</h2><span class="hint">隐藏桌面第二实例 · 主机零干扰</span></div>
    <div class="cards" id="sessions"></div>
  </section>
  <section class="panel p5" style="--i:1">
    <div class="phead"><span class="idx">02</span><h2>镜像 / 录制</h2><span class="hint">gbmirror 状态导出</span></div>
    <div id="mirror"></div>
    <div class="row" style="margin-top:13px">
      <button id="mirroropen" class="primary">打开镜像窗口</button>
      <button id="mirrorclose">关闭镜像窗口</button>
      <select id="mirrorwidth" aria-label="镜像窗口宽度">
        <option value="1000">宽 1000</option><option value="1400" selected>宽 1400</option><option value="1800">宽 1800</option>
      </select>
      <select id="mirrorfps" aria-label="镜像帧率">
        <option value="15">15 帧/秒</option><option value="24">24 帧/秒</option><option value="30" selected>30 帧/秒</option>
      </select>
    </div>
    <div class="note" id="mirroract">打开镜像窗口是<b>主机可见动作</b>：会在你的桌面弹出真实窗口、可能切换前台，影响按实测显示。关闭仅针对 gbmirror.exe，绝不触碰保活会话。</div>
  </section>
  <section class="panel" style="--i:2">
    <div class="phead"><span class="idx">03</span><h2>能力表与待评审提案</h2><span class="hint">冻结契约 · 风险按实测声明</span></div>
    <div class="scroll"><table id="cap"></table></div>
    <div class="note" id="props"></div>
  </section>
  <section class="panel" style="--i:3">
    <div class="phead"><span class="idx">04</span><h2>FocusGuard 事件流</h2><span class="hint">四态判定 · 事件钩子证据</span></div>
    <div class="row">
      <select id="filter" aria-label="按状态筛选">
        <option value="">全部状态</option>
        <option value="success_no_interference_observed">无干扰 · success_no_interference_observed</option>
        <option value="success_with_interference">有干扰 · success_with_interference</option>
        <option value="failed">失败 · failed</option>
        <option value="unconfirmed">未确认 · unconfirmed</option>
        <option value="__capture">捕获 / 判定记录</option>
      </select>
      <select id="limit" aria-label="读取最近运行数">
        <option value="30">最近 30 次运行</option>
        <option value="60">最近 60 次运行</option>
        <option value="120">最近 120 次运行</option>
      </select>
      <button id="reload">刷新事件</button>
      <span class="count" id="evcount"></span>
    </div>
    <div class="scroll"><table id="events"></table></div>
    <details>
      <summary>状态字典（四态原始枚举）</summary>
      <div class="dict">
        <div><span class="badge ok">无干扰</span><code>success_no_interference_observed</code></div>
        <div><span class="badge warn">有干扰</span><code>success_with_interference</code></div>
        <div><span class="badge bad">失败</span><code>failed</code></div>
        <div><span class="badge mut">未确认</span><code>unconfirmed</code></div>
      </div>
      <div class="note">干扰判定以 <b>SetWinEventHook 前台事件</b> 为准；2ms 轮询存在理论盲区，外部输入污染的运行弃用但保留原始文件。</div>
    </details>
  </section>
  <section class="panel" style="--i:4">
    <div class="phead"><span class="idx">05</span><h2>按需快照</h2><span class="hint">单帧只读 · 每次调用重测零干扰</span></div>
    <div class="row">
      <select id="snapsess" aria-label="选择会话"></select>
      <label class="priv" id="privwrap" hidden><input type="checkbox" id="confirm"> 我确认查看微信私聊画面</label>
      <button id="snap" class="primary">抓取快照</button>
      <span class="count" id="snapmeta"></span>
    </div>
    <div class="snapframe" id="snapwrap" hidden><img class="snap" id="snapimg" alt="隐藏桌面单帧快照"></div>
    <div class="note">快照为 <b>PrintWindow 单帧拼接</b>，读取后 BMP 立即删除，磁盘不留可读画面；微信含私聊，须显式确认。实时画面请使用原生镜像窗口。</div>
  </section>
</main>
<footer>
  <span>观测只读：不写引擎 / 冻结能力表 / 保活会话</span><span class="sep"></span>
  <span>镜像窗口开关＝显式主机可见动作</span><span class="sep"></span>
  <span>仅绑定 127.0.0.1</span><span class="sep"></span>
  <span>数据源 <code>var/experiments</code> · <code>packages/routing/capabilities.draft.yaml</code> · <code>docs/proposals</code></span>
</footer>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const badge=(t,c,title)=>`<span class="badge ${c}"${title?` title="${esc(title)}"`:''}>${esc(t)}</span>`;
const STATE={
  success_no_interference_observed:['无干扰','ok'],
  success_with_interference:['有干扰','warn'],
  failed:['失败','bad'],
  unconfirmed:['未确认','mut']
};
const RISK={none:'无干扰',focus_switch:'焦点切换',physical_input:'物理输入',logical_only:'仅逻辑',unknown:'未测量'};
const KIND={wechat:'微信',trae:'Trae'};
const ERR_ZH=[
 [/wechat snapshot exposes private chats/i,'微信快照含私聊画面，请先勾选「我确认查看微信私聊画面」'],
 [/session not alive/i,'会话已退出，无法抓取快照'],
 [/unknown session/i,'未知会话'],
 [/gbmirror.exe not built/i,'gbmirror.exe 尚未构建（cargo build --release）'],
 [/capture produced no bmp/i,'截图未生成 BMP'],
 [/mirror window not running/i,'镜像窗口未在运行'],
 [/refuse to close/i,'拒绝关闭：目标进程不是 gbmirror.exe（保活会话受保护）'],
 [/not found/i,'接口不存在']
];
const zhErr=m=>{for(const pair of ERR_ZH)if(pair[0].test(m))return pair[1];return m;};
function stateBadge(s){if(!s)return '';const m=STATE[s];return m?badge(m[0],m[1],s):badge(s,'mut',s);}
function riskChip(ch){
  if(!ch.supported)return `<span class="chan"><code>${esc(ch.channel)}</code><i class="mut">不支持</i></span>`;
  const r=ch.risk||'unknown';const cls=r==='none'?'ok':(r==='unknown'?'mut':(r==='physical_input'?'bad':'warn'));
  return `<span class="chan"><code>${esc(ch.channel)}</code><i class="${cls}" title="${esc(r)}">${esc(RISK[r]||r)}</i></span>`;
}
const dash=v=>(v===null||v===undefined||v==='')?'<span class="dash">—</span>':esc(v);
async function j(p){const r=await fetch(p);if(!r.ok)throw new Error((await r.json()).error||r.status);return r.json();}
let SESSIONS=[];
async function loadSessions(){const d=await j('/api/sessions');SESSIONS=d.sessions;
 $('hSessions').textContent=d.sessions.filter(s=>s.alive).length+' / '+d.sessions.length;
 $('sessions').innerHTML=d.sessions.map(s=>`<article class="card${s.alive?'':' dead'}">
  <div class="cardhead"><span class="led${s.alive?' live':''}"></span><h3>${esc(s.name)}</h3>
   ${s.alive?badge('存活','ok','alive'):badge('已退出','bad','dead')}</div>
  <div class="kv"><span>类型</span><b title="${esc(s.kind)}">${esc(KIND[s.kind]||s.kind)}</b></div>
  <div class="kv"><span>隐藏桌面</span><b>${esc(s.desktop)}</b></div>
  <div class="kv"><span>进程 / 窗口</span><b>${esc(s.pid)} / ${esc(s.hwnd)}</b></div>
  <div class="kv"><span>调试端口</span><b>${dash(s.port)}</b></div>
  <div class="kv"><span>已运行</span><b>${dash(s.uptime)}</b></div></article>`).join('')
  ||'<div class="empty">暂无保活会话</div>';
 const sel=$('snapsess');const cur=sel.value;
 sel.innerHTML=d.sessions.map(s=>`<option value="${esc(s.name)}">${esc(s.name)}${s.alive?'':'（已退出）'}</option>`).join('');
 if(cur&&d.sessions.some(s=>s.name===cur))sel.value=cur; else if(d.sessions.some(s=>s.name==='trae'))sel.value='trae';
 syncPriv();}
function syncPriv(){const s=SESSIONS.find(x=>x.name===$('snapsess').value);
 $('privwrap').hidden=!(s&&s.kind==='wechat'); if($('privwrap').hidden)$('confirm').checked=false;}
async function loadMirror(){const m=await j('/api/mirror');
 $('hMirror').textContent=m.running&&m.fps?m.fps.toFixed(1):'停止';
 const size=m.rec_size?(m.rec_size>1048576?(m.rec_size/1048576).toFixed(1)+' MB':(m.rec_size/1024).toFixed(0)+' KB'):'—';
 $('mirror').innerHTML=`<div class="gauge">
   <div class="readout"><span class="num">${m.running&&m.fps?m.fps.toFixed(1):'0.0'}</span><span class="unit">帧 / 秒</span></div>
   <div class="readout sm"><span class="num">${m.zoom??'1'}×</span><span class="unit">缩放</span></div>
   <div class="state"><span class="led${m.running?' live':''}"></span>${m.running?badge('运行中','ok','running'):badge('已停止','bad','stopped')}</div>
  </div>
  <div class="kv"><span>当前会话</span><b>${dash(m.current)}</b></div>
  <div class="kv"><span>隐藏桌面</span><b>${dash(m.desktop)}</b></div>
  <div class="kv"><span>帧序号</span><b>${dash(m.seq)}</b></div>
  <div class="kv"><span>状态延迟</span><b>${m.age_s!=null?esc(m.age_s)+' 秒':'—'}</b></div>
  <div class="kv"><span>录制</span><b>${m.rec_on?badge('录制中','bad','rec on'):badge('未录制','mut','rec off')} ${esc(m.rec_info??'')}</b></div>
  <div class="kv"><span>录像文件</span><b>${size}</b></div>
  <div class="kv"><span>窗口进程</span><b>${dash(m.pid)}${m.launched_by_dashboard?' · 本页启动':''}</b></div>`;
 const op=$('mirroropen'),cl=$('mirrorclose');
 op.disabled=!m.exe_built||!!m.running;
 op.title=m.exe_built?'在主机桌面打开原生镜像窗口':'gbmirror.exe 未构建';
 cl.disabled=!m.running&&!m.launched_by_dashboard;}
async function mirrorCtl(action){
 const act=$('mirroract');
 act.textContent=action==='open'?'正在打开镜像窗口…':'正在关闭镜像窗口…';
 try{
  const qs=action==='open'?`?width=${$('mirrorwidth').value}&fps=${$('mirrorfps').value}`:'';
  const r=await fetch('/api/mirror/'+action+qs,{method:'POST'});
  const d=await r.json();
  if(!r.ok||d.ok===false)throw new Error(d.error||r.status);
  if(action==='open'){
   if(d.already_running){act.textContent=`镜像窗口已在运行（pid ${d.pid}），未重复启动。`;}
   else{const h=d.host||{};
    act.innerHTML=`已打开镜像窗口 pid ${d.pid} · 实测 ${h.window_s}s 窗口：主机前台切换 <b>${h.fg_switches}</b> 次 · 光标最大位移 <b>${h.max_disp_during}px</b> · ${h.zero_interference_observed?'未观测到干扰':'观测到前台/光标变化（打开可见窗口属预期，非零干扰）'}`;}
  }else{
   act.textContent=`已关闭镜像窗口 pid ${d.pid}（${d.graceful?'WM_CLOSE 优雅退出，录制已收尾':'强制结束'}）。`;
  }
  loadMirror();
 }catch(e){act.textContent='失败：'+zhErr(e.message);act.title=e.message;}}
async function loadCap(){const c=await j('/api/capability');
 $('cap').innerHTML='<thead><tr><th>应用</th><th>操作</th><th>影响</th><th>幂等</th><th>通道（实测风险）</th><th>证据</th></tr></thead><tbody>'+
  c.entries.map(e=>`<tr><td class="num">${esc(e.app)}</td><td class="num">${esc(e.operation)}</td>
   <td>${e.impact==='high'?badge('高','warn','high'):badge(e.impact==='low'?'低':e.impact,'mut',e.impact)}</td>
   <td>${e.idempotent?'<span class="dash">是</span>':'<span style="color:var(--amber)">否</span>'}</td>
   <td>${e.channels.map(riskChip).join('')||'<span class="dash">—</span>'}</td>
   <td class="num">${e.evidence.length} 条</td></tr>`).join('')+'</tbody>';
 $('props').innerHTML='表状态 <code>'+esc(c.status)+'</code> · 待评审提案：'+
  (c.proposals.map(p=>`<code>${esc(p.file)}</code> ${esc(p.title)}`).join(' · ')||'无');}
let EVENTS=[];
async function loadEvents(){const d=await j('/api/events?limit='+$('limit').value);EVENTS=d.events;renderEvents();}
function renderEvents(){const f=$('filter').value;
 const rows=EVENTS.filter(e=>!f||(f==='__capture'?(!e.state&&(e.zero!==null&&e.zero!==undefined||e.verdict)):e.state===f));
 $('evcount').textContent='显示 '+rows.length+' / 共 '+EVENTS.length+' 条';
 $('hEvents').textContent=EVENTS.length;
 $('events').innerHTML='<thead><tr><th>运行</th><th>文件 · 路径</th><th>状态 / 判定</th><th>光标位移</th><th>焦点</th><th>外部输入</th><th>检出率</th></tr></thead><tbody>'+
  rows.map(e=>`<tr><td><code>${esc(e.run)}</code></td>
   <td>${esc(e.file)}<span class="raw">${esc(e.label)}</span></td>
   <td>${stateBadge(e.state)||(e.zero===true?badge('零干扰','ok','zero_interference_observed=true'):e.zero===false?badge('有干扰','warn','zero_interference_observed=false'):(e.verdict?badge(e.verdict,'mut','verdict'):'<span class="dash">—</span>'))}
    ${e.state?`<span class="raw">${esc(e.state)}</span>`:''}</td>
   <td class="num">${e.cursor==null?'<span class="dash">—</span>':esc(e.cursor)+' px'}</td>
   <td>${e.focus_switch===true?badge('切换','warn','unexpected_focus_switch'):e.focus_switch===false?'<span class="dash">无</span>':dash(e.focus_switch)}</td>
   <td>${e.external===true?badge('有污染','bad','external_input_during_window'):e.external===false?'<span class="dash">无</span>':dash(e.external)}</td>
   <td class="num">${e.detection_rate!=null?'检出 '+(e.detection_rate*100).toFixed(0)+'%':e.fp_rate!=null?'误报 '+(e.fp_rate*100).toFixed(0)+'%':'<span class="dash">—</span>'}</td></tr>`).join('')+'</tbody>';}
async function snap(){const s=$('snapsess').value;const conf=$('confirm').checked?1:0;
 $('snapmeta').textContent='抓取中…';$('snapwrap').hidden=true;
 try{const d=await j(`/api/snapshot?session=${encodeURIComponent(s)}&confirm=${conf}`);
  $('snapimg').src='data:image/bmp;base64,'+d.image_b64;$('snapwrap').hidden=false;
  $('snapmeta').innerHTML=`零干扰观测=${d.zero_interference_observed} · 耗时 ${d.avg_capture_ms}ms · 内容框 ${esc(JSON.stringify(d.content_bbox))}`;
 }catch(e){$('snapmeta').textContent='失败：'+zhErr(e.message);$('snapmeta').title=e.message;}}
async function refreshFast(){try{await Promise.all([loadSessions(),loadMirror()]);
  const t=$('ts');t.textContent='已更新 '+new Date().toLocaleTimeString('zh-CN',{hour12:false});
  t.classList.remove('flash');void t.offsetWidth;t.classList.add('flash');
 }catch(e){$('ts').textContent='错误 '+zhErr(e.message);}}
$('reload').onclick=loadEvents;$('filter').onchange=renderEvents;$('limit').onchange=loadEvents;
$('snap').onclick=snap;$('snapsess').onchange=syncPriv;
$('mirroropen').onclick=()=>mirrorCtl('open');$('mirrorclose').onclick=()=>mirrorCtl('close');
loadCap();loadEvents();refreshFast();
setInterval(()=>{if($('auto').checked)refreshFast();},3000);
</script></body></html>
"""


def main() -> int:
    ap = argparse.ArgumentParser(description="GUIBridge read-only localhost observation dashboard")
    ap.add_argument("--port", type=int, default=8710)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"GUIBridge dashboard (read-only): http://127.0.0.1:{args.port}/")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())