// Recon: open the composer mode menu and dump its popup options.
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
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

ws.onopen = async () => {
  const r1 = await send("Runtime.evaluate", {
    expression: "(() => { const b = document.querySelector('.v2-agent-entry-btn'); if (!b) return 'NO_BTN'; b.click(); return 'clicked'; })()",
    returnByValue: true,
  });
  console.log("step1:", JSON.stringify(r1.result ?? r1.error).slice(0, 200));
  await sleep(1000);
  const r2 = await send("Runtime.evaluate", {
    expression: `(() => {
      const pops = [...document.querySelectorAll('[class*=popup], [class*=overlay], [class*=dropdown], [class*=Popover], [class*=menu], [class*=Modal], [class*=modal]')]
        .filter(el => { const r = el.getBoundingClientRect(); return r.height > 40 && r.width > 80 && el.innerText && el.innerText.trim(); });
      return JSON.stringify(pops.slice(-8).map(el => ({ cls: String(el.className).slice(0, 70), text: el.innerText.slice(0, 250).replace(/\\n/g, '|') })));
    })()`,
    returnByValue: true,
  });
  console.log("step2:", JSON.stringify(r2.result ?? r2.error).slice(0, 2000));
  ws.close();
  process.exit(0);
};
setTimeout(() => { console.log("TIMEOUT"); process.exit(1); }, 10000);