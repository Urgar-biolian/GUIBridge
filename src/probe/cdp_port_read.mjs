// Read-only CDP evaluate on a caller-supplied port (argv[2]). No clicks/input/messages.
// Used by experiment_trae_hidden.py to read a hidden-desktop Trae second instance.
const port = process.argv[2] || "9333";
setTimeout(() => { console.log(JSON.stringify({ ok: false, error: "timeout" })); process.exit(0); }, 12000);
let list;
try {
  list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
} catch (e) {
  console.log(JSON.stringify({ ok: false, error: "cdp_unreachable: " + String(e) })); process.exit(0);
}
const page = list.find((t) => t.type === "page");
if (!page) { console.log(JSON.stringify({ ok: false, error: "no page target", targets: list.length })); process.exit(0); }
const ws = new WebSocket(page.webSocketDebuggerUrl);
const result = await new Promise((resolve) => {
  ws.onopen = () => ws.send(JSON.stringify({
    id: 1,
    method: "Runtime.evaluate",
    params: {
      expression: "JSON.stringify({title: document.title, url: location.href.slice(0,120), hasChatRoot: !!document.querySelector('.ai-chat-v2-ide-root'), chatLen: (document.querySelector('.ai-chat-v2-ide-root')?.innerText || '').length, bodyLen: (document.body?.innerText || '').length})",
      returnByValue: true,
    },
  }));
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id === 1) {
      const val = m.result?.result?.value;
      resolve({ ok: !m.error && !m.result?.exceptionDetails, value: val ?? null, pageUrl: page.url?.slice(0, 120) });
      ws.close();
    }
  };
  ws.onerror = () => resolve({ ok: false, error: "ws error" });
});
console.log(JSON.stringify(result));
process.exit(0);