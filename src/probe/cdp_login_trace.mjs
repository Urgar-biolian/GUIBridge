const port = process.argv[2] || "9333";
const text = process.argv[3] || "个人用户";
setTimeout(() => { console.log(JSON.stringify({ ok: false, error: "timeout" })); process.exit(0); }, 15000);
const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = list.find((t) => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0; const pending = new Map();
const send = (method, params) => new Promise((res) => { const i = ++id; pending.set(i, res); ws.send(JSON.stringify({ id: i, method, params })); });
const requests = []; const consoleMsgs = []; const exceptions = [];
const result = await new Promise((resolve) => {
  ws.onopen = async () => {
    await send("Network.enable", {});
    await send("Runtime.enable", {});
    await send("Log.enable", {});
    await send("Runtime.evaluate", { expression: `(() => { const b = [...document.querySelectorAll('button')].find(e => (e.innerText||'').trim() === ${JSON.stringify(text)}); if (!b) return 'no_btn'; b.click(); return 'clicked'; })()`, returnByValue: true });
    await new Promise((r) => setTimeout(r, 5000));
    resolve({ ok: true, requests: requests.slice(0, 30), console: consoleMsgs.slice(0, 30), exceptions: exceptions.slice(0, 15) });
    ws.close();
  };
  ws.onmessage = (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return; }
    if (m.method === "Network.requestWillBeSent") requests.push({ url: (m.params.request.url || "").slice(0, 120), method: m.params.request.method });
    if (m.method === "Runtime.consoleAPICalled") consoleMsgs.push((m.params.args || []).map(a => a.value ?? a.description ?? "").join(" ").slice(0, 200));
    if (m.method === "Runtime.exceptionThrown") exceptions.push(JSON.stringify(m.params.exceptionDetails?.exception?.description || m.params.exceptionDetails?.text || "").slice(0, 200));
    if (m.method === "Log.entryAdded") consoleMsgs.push("LOG:" + (m.params.entry?.text || "").slice(0, 200));
  };
  ws.onerror = () => resolve({ ok: false, error: "ws error" });
});
console.log(JSON.stringify(result));
process.exit(0);