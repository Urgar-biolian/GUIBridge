"""GUIBridge read-only localhost observation dashboard (probe-side, single approve).

A single-file stdlib HTTP server + embedded single-page UI that aggregates the EXISTING
probe artefacts into one management/observation view. It never writes to the engine, the
frozen capability table, or any keep-alive session; the only side effects are (a) reading
files and (b) an on-demand one-frame hidden-desktop snapshot via `gbmirror --desktop`
(read-only, zero-interference, re-measured per call). WeChat snapshots expose private
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
import json
import re
import subprocess
import sys
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
                self._send(200, mirror_status())
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


PAGE = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>GUIBridge 观测台</title>
<style>
:root{color-scheme:dark}
*{box-sizing:border-box}
body{margin:0;background:#0d1117;color:#e6edf3;font:14px/1.5 "Segoe UI",system-ui,sans-serif}
header{padding:14px 20px;background:#161b22;border-bottom:1px solid #30363d;display:flex;gap:14px;align-items:baseline;flex-wrap:wrap}
header h1{font-size:17px;margin:0}
header .sub{color:#8b949e;font-size:12px}
main{padding:18px 20px;display:grid;gap:18px;grid-template-columns:repeat(auto-fit,minmax(340px,1fr))}
section{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:14px}
section.wide{grid-column:1/-1}
h2{font-size:13px;margin:0 0 10px;color:#8b949e;text-transform:uppercase;letter-spacing:.06em}
.cards{display:grid;gap:10px;grid-template-columns:repeat(auto-fit,minmax(220px,1fr))}
.card{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:10px}
.card .name{font-weight:600;font-size:15px}
.kv{display:flex;justify-content:space-between;gap:8px;color:#8b949e;font-size:12px;margin-top:3px}
.kv b{color:#e6edf3;font-weight:500;word-break:break-all}
.badge{display:inline-block;padding:1px 8px;border-radius:10px;font-size:11px;font-weight:600}
.ok{background:#12261e;color:#3fb950;border:1px solid #238636}
.warn{background:#2b2110;color:#d29922;border:1px solid #9e6a03}
.bad{background:#2d1517;color:#f85149;border:1px solid #da3633}
.mut{background:#21262d;color:#8b949e;border:1px solid #30363d}
table{width:100%;border-collapse:collapse;font-size:12px}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid #21262d;vertical-align:top}
th{color:#8b949e;font-weight:600;position:sticky;top:0;background:#161b22}
.scroll{max-height:340px;overflow:auto}
button,select{background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:6px;padding:5px 10px;font-size:12px;cursor:pointer}
button:hover{background:#30363d}
.row{display:flex;gap:8px;align-items:center;flex-wrap:wrap;margin-bottom:10px}
img.snap{max-width:100%;border:1px solid #30363d;border-radius:6px;background:#000}
.note{color:#8b949e;font-size:12px;margin-top:8px}
.priv{color:#d29922;font-size:12px}
code{background:#21262d;padding:0 4px;border-radius:4px;font-size:11px}
</style></head><body>
<header><h1>GUIBridge 观测台</h1>
<span class="sub">localhost 只读 · 不写引擎/契约/会话</span>
<span class="sub" id="ts"></span>
<span class="sub"><label><input type="checkbox" id="auto" checked> 3s 自动刷新</label></span>
</header>
<main>
<section><h2>保活会话</h2><div class="cards" id="sessions"></div></section>
<section><h2>镜像 / 录制</h2><div id="mirror"></div></section>
<section class="wide"><h2>能力表（frozen）+ 待评审提案</h2>
<div class="scroll"><table id="cap"></table></div>
<div class="note" id="props"></div></section>
<section class="wide"><h2>FocusGuard / 捕获 事件流</h2>
<div class="row"><select id="filter">
<option value="">全部状态</option>
<option>success_no_interference_observed</option>
<option>success_with_interference</option>
<option>failed</option><option>unconfirmed</option>
<option value="__capture">捕获/verdict</option>
</select><select id="limit"><option>30</option><option>60</option><option>120</option></select>
<button id="reload">刷新</button><span class="note" id="evcount"></span></div>
<div class="scroll"><table id="events"></table></div></section>
<section class="wide"><h2>按需快照（只读·零干扰重测）</h2>
<div class="row"><select id="snapsess"></select>
<label class="priv" id="privwrap" hidden><input type="checkbox" id="confirm"> 我确认查看微信私聊画面</label>
<button id="snap">抓取快照</button><span class="note" id="snapmeta"></span></div>
<img class="snap" id="snapimg" hidden alt="snapshot">
<div class="note">快照为单帧 PrintWindow 拼接，调用后 BMP 立即删除；微信需显式确认。实时画面请用原生镜像窗口。</div>
</section>
</main>
<script>
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const badge=(t,c)=>`<span class="badge ${c}">${esc(t)}</span>`;
function stateBadge(s){if(!s)return '';
 if(s==='success_no_interference_observed')return badge('no-interf','ok');
 if(s==='success_with_interference')return badge('interf','warn');
 if(s==='failed')return badge('failed','bad');
 if(s==='unconfirmed')return badge('unconf','mut');
 return badge(s,'mut');}
async function j(p){const r=await fetch(p);if(!r.ok)throw new Error((await r.json()).error||r.status);return r.json();}
let SESSIONS=[];
async function loadSessions(){const d=await j('/api/sessions');SESSIONS=d.sessions;
 $('sessions').innerHTML=d.sessions.map(s=>`<div class="card">
  <div class="name">${esc(s.name)} ${s.alive?badge('alive','ok'):badge('dead','bad')}</div>
  <div class="kv"><span>kind</span><b>${esc(s.kind)}</b></div>
  <div class="kv"><span>desktop</span><b>${esc(s.desktop)}</b></div>
  <div class="kv"><span>pid / hwnd</span><b>${esc(s.pid)} / ${esc(s.hwnd)}</b></div>
  <div class="kv"><span>port</span><b>${esc(s.port??'—')}</b></div>
  <div class="kv"><span>uptime</span><b>${esc(s.uptime??'—')}</b></div></div>`).join('')||'<div class="note">无会话</div>';
 const sel=$('snapsess');const cur=sel.value;
 sel.innerHTML=d.sessions.map(s=>`<option value="${esc(s.name)}">${esc(s.name)}</option>`).join('');
 if(cur&&d.sessions.some(s=>s.name===cur))sel.value=cur; else if(d.sessions.some(s=>s.name==='trae'))sel.value='trae';
 syncPriv();}
function syncPriv(){const s=SESSIONS.find(x=>x.name===$('snapsess').value);
 $('privwrap').hidden=!(s&&s.kind==='wechat'); if($('privwrap').hidden)$('confirm').checked=false;}
async function loadMirror(){const m=await j('/api/mirror');
 $('mirror').innerHTML=`<div class="card">
  <div class="name">gbmirror ${m.running?badge('running','ok'):badge('stopped','bad')}</div>
  <div class="kv"><span>current</span><b>${esc(m.current??'—')}</b></div>
  <div class="kv"><span>desktop</span><b>${esc(m.desktop??'—')}</b></div>
  <div class="kv"><span>fps / zoom</span><b>${m.fps?m.fps.toFixed(1):'—'} / ${m.zoom??'—'}x</b></div>
  <div class="kv"><span>frames</span><b>${esc(m.seq??'—')}</b></div>
  <div class="kv"><span>status age</span><b>${esc(m.age_s??'—')}s</b></div>
  <div class="kv"><span>REC</span><b>${m.rec_on?badge('on','bad'):badge('off','mut')} ${esc(m.rec_info??'')}</b></div>
  <div class="kv"><span>rec mp4</span><b>${m.rec_size?(m.rec_size/1024).toFixed(0)+' KB':'—'}</b></div></div>`;}
async function loadCap(){const c=await j('/api/capability');
 $('cap').innerHTML='<tr><th>app</th><th>operation</th><th>impact</th><th>idem</th><th>channels (risk)</th><th>evidence</th></tr>'+
  c.entries.map(e=>`<tr><td>${esc(e.app)}</td><td>${esc(e.operation)}</td>
   <td>${e.impact==='high'?badge('high','warn'):badge('low','mut')}</td>
   <td>${e.idempotent?'yes':'no'}</td>
   <td>${e.channels.map(ch=>`${esc(ch.channel)}:${ch.supported?badge(ch.risk,ch.risk==='none'?'ok':(ch.risk==='unknown'?'mut':'warn')):badge('off','mut')}`).join(' ')}</td>
   <td>${e.evidence.length}</td></tr>`).join('');
 $('props').innerHTML='status=<code>'+esc(c.status)+'</code> · 待评审提案: '+
  (c.proposals.map(p=>`<code>${esc(p.file)}</code> ${esc(p.title)}`).join(' · ')||'无');}
let EVENTS=[];
async function loadEvents(){const d=await j('/api/events?limit='+$('limit').value);EVENTS=d.events;renderEvents();}
function renderEvents(){const f=$('filter').value;
 const rows=EVENTS.filter(e=>!f||(f==='__capture'?(!e.state&&(e.zero!==null&&e.zero!==undefined||e.verdict)):e.state===f));
 $('evcount').textContent=rows.length+' / '+EVENTS.length+' 条';
 $('events').innerHTML='<tr><th>run</th><th>file·label</th><th>state/verdict</th><th>cursor</th><th>focus</th><th>ext</th><th>rate</th></tr>'+
  rows.map(e=>`<tr><td><code>${esc(e.run)}</code></td><td>${esc(e.file)}<br><code>${esc(e.label)}</code></td>
   <td>${stateBadge(e.state)||(e.zero===true?badge('zero-interf','ok'):e.zero===false?badge('interf','warn'):(e.verdict?badge(e.verdict,'mut'):''))}</td>
   <td>${esc(e.cursor??'—')}</td><td>${e.focus_switch===true?badge('switch','warn'):e.focus_switch===false?'—':esc(e.focus_switch??'—')}</td>
   <td>${e.external===true?badge('ext','bad'):e.external===false?'—':esc(e.external??'—')}</td>
   <td>${e.detection_rate!=null?(e.detection_rate*100).toFixed(0)+'%':e.fp_rate!=null?'fp '+(e.fp_rate*100).toFixed(0)+'%':'—'}</td></tr>`).join('');}
async function snap(){const s=$('snapsess').value;const conf=$('confirm').checked?1:0;
 $('snapmeta').textContent='抓取中…';$('snapimg').hidden=true;
 try{const d=await j(`/api/snapshot?session=${encodeURIComponent(s)}&confirm=${conf}`);
  $('snapimg').src='data:image/bmp;base64,'+d.image_b64;$('snapimg').hidden=false;
  $('snapmeta').innerHTML=`zero_interference=${d.zero_interference_observed} · ${d.avg_capture_ms}ms · bbox ${esc(JSON.stringify(d.content_bbox))}`;
 }catch(e){$('snapmeta').textContent='失败: '+e.message;}}
async function refreshFast(){try{await Promise.all([loadSessions(),loadMirror()]);$('ts').textContent='updated '+new Date().toLocaleTimeString();}catch(e){$('ts').textContent='err '+e.message;}}
$('reload').onclick=loadEvents;$('filter').onchange=renderEvents;$('limit').onchange=loadEvents;
$('snap').onclick=snap;$('snapsess').onchange=syncPriv;
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