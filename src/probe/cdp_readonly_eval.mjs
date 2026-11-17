// Read-only CDP evaluate: no clicks, no input, no messages. Used by
// trae_cdp_focus.py to measure whether CDP logical access interferes with focus.
setTimeout(() => { console.log(JSON.stringify({ ok: false, error: "timeout" })); process.exit(0); }, 12000);
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page");
if (!page) { console.log(JSON.stringify({ ok: false, error: "no page target" })); process.exit(0); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
const result = await new Promise((resolve) => {
  ws.onopen = () => ws.send(JSON.stringify({
    id: 1,
    method: "Runtime.evaluate",
    params: {
      expression: "JSON.stringify({title: document.title, chatLen: (document.querySelector('.ai-chat-v2-ide-root')?.innerText || '').length})",
      returnByValue: true,
    },
  }));
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id === 1) {
      const val = m.result?.result?.value;
      resolve({ ok: !m.error && !m.result?.exceptionDetails, value: val ?? null });
      ws.close();
    }
  };
  ws.onerror = () => resolve({ ok: false, error: "ws error" });
});
console.log(JSON.stringify(result));
process.exit(0);