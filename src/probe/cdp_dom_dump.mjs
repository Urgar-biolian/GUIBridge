// Read-only DOM dump on a caller-supplied CDP port (argv[2]). No clicks/input/messages.
// Reports body text (truncated) + visible buttons/links/inputs so we can plan setup/login.
const port = process.argv[2] || "9333";
setTimeout(() => { console.log(JSON.stringify({ ok: false, error: "timeout" })); process.exit(0); }, 12000);
let list;
try { list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json(); }
catch (e) { console.log(JSON.stringify({ ok: false, error: "cdp_unreachable: " + String(e) })); process.exit(0); }
const pages = list.filter((t) => t.type === "page");
if (!pages.length) { console.log(JSON.stringify({ ok: false, error: "no page target", targets: list.length })); process.exit(0); }
const out = [];
for (const page of pages) {
  const ws = new WebSocket(page.webSocketDebuggerUrl);
  const r = await new Promise((resolve) => {
    ws.onopen = () => ws.send(JSON.stringify({
      id: 1, method: "Runtime.evaluate",
      params: {
        expression: `(() => {
          const vis = el => { const r = el.getBoundingClientRect(); return r.width > 0 && r.height > 0; };
          const btns = [...document.querySelectorAll('button, a, [role=button], input[type=submit]')]
            .filter(vis).map(el => ({ tag: el.tagName, text: (el.innerText || el.value || '').trim().slice(0, 40),
              cls: String(el.className || '').slice(0, 60), aria: el.getAttribute('aria-label') || '' })).slice(0, 40);
          const inputs = [...document.querySelectorAll('input, textarea, [contenteditable=true]')]
            .filter(vis).map(el => ({ tag: el.tagName, type: el.type || '', ph: el.placeholder || '',
              cls: String(el.className || '').slice(0, 60) })).slice(0, 20);
          return JSON.stringify({ title: document.title, url: location.href.slice(0, 140),
            hasChatRoot: !!document.querySelector('.ai-chat-v2-ide-root'),
            bodyText: (document.body?.innerText || '').slice(0, 1500), buttons: btns, inputs });
        })()`,
        returnByValue: true,
      },
    }));
    ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id === 1) {
      resolve({ ok: !m.error && !m.result?.exceptionDetails, value: m.result?.result?.value ?? null }); ws.close(); } };
    ws.onerror = () => resolve({ ok: false, error: "ws error" });
  });
  out.push({ pageUrl: page.url?.slice(0, 140), ...r });
}
console.log(JSON.stringify({ ok: true, pages: out }));
process.exit(0);