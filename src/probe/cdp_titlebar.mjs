// Recon: titlebar SOLO/IDE segmented control structure.
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
  console.log("structure:", await ev(`(() => {
    const leaf = [...document.querySelectorAll('*')].find(el => (el.textContent || '').trim() === 'IDE' && el.children.length === 0 && el.getBoundingClientRect().height > 0);
    if (!leaf) return 'NO_LEAF';
    const chain = [];
    let el = leaf;
    for (let i = 0; i < 5 && el; i++) {
      chain.push({ tag: el.tagName, cls: String(el.className).slice(0, 80), role: el.getAttribute && el.getAttribute('role') });
      el = el.parentElement;
    }
    return JSON.stringify(chain);
  })()`));
  console.log("click parent:", await ev(`(() => {
    const leaf = [...document.querySelectorAll('*')].find(el => (el.textContent || '').trim() === 'IDE' && el.children.length === 0 && el.getBoundingClientRect().height > 0);
    if (!leaf) return 'NO_LEAF';
    let target = leaf;
    for (let i = 0; i < 4 && target.parentElement; i++) {
      target = target.parentElement;
      if (/switch|segment|tab|mode|toggle/i.test(String(target.className))) break;
    }
    target.click();
    return 'clicked ' + String(target.className).slice(0, 60);
  })()`));
  await sleep(3000);
  console.log("after:", await ev(`(() => JSON.stringify({ head: document.body.innerText.slice(0, 100).replace(/\\n/g, '|'), mode: (document.querySelector('.v2-agent-entry-btn__name') || {}).textContent }))()`));
  ws.close();
  process.exit(0);
};
setTimeout(() => { console.log("TIMEOUT"); process.exit(1); }, 15000);