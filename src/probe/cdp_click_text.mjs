// Click ONE button by exact leaf text over CDP (argv[2]=port, argv[3]=text), then re-dump DOM.
// Uses Input.dispatchMouseEvent at the button center (trusted-event path, same as TraeAdapter
// _click_at). For first-run setup navigation only — never chat send. Returns post-click DOM.
const port = process.argv[2] || "9333";
const text = process.argv[3] || "";
setTimeout(() => { console.log(JSON.stringify({ ok: false, error: "timeout" })); process.exit(0); }, 15000);
const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = list.find((t) => t.type === "page");
if (!page) { console.log(JSON.stringify({ ok: false, error: "no page target" })); process.exit(0); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const pending = new Map();
const send = (method, params) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const evaluate = async (expression) => { const r = await send("Runtime.evaluate", { expression, returnByValue: true }); return r.result?.result?.value ?? null; };
const DUMP = `(() => {
  const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
  const btns = [...document.querySelectorAll('button, a, [role=button], input[type=submit]')]
    .filter(vis).map(el => ({ text: (el.innerText || el.value || '').trim().slice(0, 40), cls: String(el.className||'').slice(0,50) })).slice(0, 40);
  const inputs = [...document.querySelectorAll('input, textarea, [contenteditable=true]')]
    .filter(vis).map(el => ({ tag: el.tagName, type: el.type || '', ph: el.placeholder || '' })).slice(0, 20);
  return JSON.stringify({ title: document.title, url: location.href.slice(0, 140),
    hasChatRoot: !!document.querySelector('.ai-chat-v2-ide-root'),
    bodyText: (document.body?.innerText || '').slice(0, 1500), buttons: btns, inputs });
})()`;
const result = await new Promise((resolve) => {
  ws.onopen = async () => {
    const find = await evaluate(`(() => {
      const t = ${JSON.stringify(text)};
      const els = [...document.querySelectorAll('button, a, [role=button], input[type=submit]')];
      let el = els.find(e => (e.innerText || e.value || '').trim() === t);
      if (!el) el = [...document.querySelectorAll('*')].find(e => e.children.length === 0
        && (e.innerText || '').trim() === t && e.getBoundingClientRect().width > 0);
      if (!el) return JSON.stringify({ found: false, names: els.map(e => (e.innerText||e.value||'').trim().slice(0,30)).filter(Boolean).slice(0,30) });
      const r = el.getBoundingClientRect();
      return JSON.stringify({ found: true, x: r.x + r.width / 2, y: r.y + r.height / 2 });
    })()`);
    const f = JSON.parse(find);
    if (!f.found) { resolve({ ok: false, error: "button_not_found", text, names: f.names }); ws.close(); return; }
    for (const type of ["mouseMoved", "mousePressed", "mouseReleased"]) {
      const p = { type, x: f.x, y: f.y };
      if (type !== "mouseMoved") { p.button = "left"; p.clickCount = 1; }
      await send("Input.dispatchMouseEvent", p);
      await new Promise((r) => setTimeout(r, 60));
    }
    await new Promise((r) => setTimeout(r, 1200));
    const dom = await evaluate(DUMP);
    resolve({ ok: true, clicked: text, at: [f.x, f.y], dom: dom ? JSON.parse(dom) : null });
    ws.close();
  };
  ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
  ws.onerror = () => resolve({ ok: false, error: "ws error" });
});
console.log(JSON.stringify(result));
process.exit(0);