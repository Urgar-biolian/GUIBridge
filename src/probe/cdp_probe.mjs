// Day-1 probe: read Trae chat panel DOM semantics via CDP (main page + attached OOPIF/webview sessions).
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page");
if (!page) { console.log("NO_PAGE_TARGET"); process.exit(1); }

const EXPR = `(() => {
  const out = [];
  const els = document.querySelectorAll('textarea, [contenteditable="true"], [contenteditable="plaintext-only"], [role="textbox"], button, [role="button"]');
  for (const el of els) {
    const r = el.getBoundingClientRect();
    if (r.width === 0 && r.height === 0) continue;
    out.push({
      tag: el.tagName, role: el.getAttribute('role'), aria: el.getAttribute('aria-label'),
      ph: el.getAttribute('placeholder') || el.getAttribute('data-placeholder'),
      ce: el.getAttribute('contenteditable'),
      cls: String(el.className || '').slice(0, 70), id: el.id,
      rect: [Math.round(r.x), Math.round(r.y), Math.round(r.width), Math.round(r.height)],
      text: (el.textContent || '').trim().slice(0, 40)
    });
  }
  return JSON.stringify({ url: location.href.slice(0, 90), count: out.length, els: out.slice(0, 80) });
})()`;

const ws = new WebSocket(page.webSocketDebuggerUrl);
let nextId = 1;
const pending = new Map();
const sessions = new Map();

function send(method, params = {}, sessionId) {
  const id = nextId++;
  const msg = { id, method, params };
  if (sessionId) msg.sessionId = sessionId;
  ws.send(JSON.stringify(msg));
  return new Promise((res, rej) => {
    pending.set(id, { res, rej });
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error("timeout " + method)); } }, 8000);
  });
}

ws.onmessage = async (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) {
    const { res, rej } = pending.get(m.id);
    pending.delete(m.id);
    m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
    return;
  }
  if (m.method === "Target.attachedToTarget") {
    const s = m.params.sessionId;
    sessions.set(s, m.params.targetInfo);
    try {
      const r = await send("Runtime.evaluate", { expression: EXPR, returnByValue: true }, s);
      console.log("=== SESSION", m.params.targetInfo.type, m.params.targetInfo.url.slice(0, 90));
      console.log(r.result?.value ?? JSON.stringify(r).slice(0, 300));
    } catch (e) { console.log("session eval failed:", e.message); }
  }
};

ws.onopen = async () => {
  await send("Target.setAutoAttach", { autoAttach: true, waitForDebuggerOnStart: false, flatten: true });
  await send("Runtime.enable");
  try {
    const r = await send("Runtime.evaluate", { expression: EXPR, returnByValue: true });
    console.log("=== MAIN PAGE");
    console.log(r.result?.value);
  } catch (e) { console.log("main eval failed:", e.message); }
  setTimeout(() => { console.log("attached sessions:", sessions.size); ws.close(); process.exit(0); }, 4000);
};
ws.onerror = (e) => { console.log("WS_ERROR", e.message); process.exit(1); };