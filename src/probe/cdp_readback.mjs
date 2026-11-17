// Read-only poll: wait for assistant reply and dump final conversation text.
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const send = (method, params) =>
  new Promise((res) => {
    const i = ++id;
    const h = (ev) => {
      const m = JSON.parse(ev.data);
      if (m.id === i) { ws.removeEventListener("message", h); res(m); }
    };
    ws.addEventListener("message", h);
    ws.send(JSON.stringify({ id: i, method, params }));
  });
const ev = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, returnByValue: true });
  return r.result?.result?.value ?? JSON.stringify(r.exceptionDetails ?? r.error ?? r).slice(0, 300);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

ws.onopen = async () => {
  for (let i = 0; i < 20; i++) {
    const s = JSON.parse(await ev(`(() => {
      const root = document.querySelector('.ai-chat-v2-ide-root');
      const text = root ? root.innerText : '';
      return JSON.stringify({ thinking: /思考中|生成中|运行中/.test(text), text: text.slice(0, 1200) });
    })()`));
    console.log(`T+${i * 3}s thinking=${s.thinking}`);
    if (!s.thinking && i > 0) { console.log("FINAL:\n" + s.text); break; }
    if (i === 19) console.log("LAST:\n" + s.text);
    await sleep(3000);
  }
  ws.close();
  process.exit(0);
};
setTimeout(() => { console.log("TIMEOUT"); process.exit(1); }, 70000);