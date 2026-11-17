// Recon: switch SOLO -> IDE mode and dump the IDE chat composer / mode selector.
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
  console.log("toggle:", await ev(`(() => {
    const els = [...document.querySelectorAll('div, span, button, a')].filter(el => {
      const t = (el.textContent || '').trim();
      const r = el.getBoundingClientRect();
      return t === 'IDE' && r.height > 0 && r.height < 40 && el.children.length === 0;
    });
    if (!els.length) return 'NO_IDE_TOGGLE';
    els[0].click();
    return 'clicked ' + els.length;
  })()`));
  await sleep(2500);
  console.log("composer:", await ev(`(() => {
    const c = document.querySelector('.chat-input-v2-container');
    const editable = document.querySelector('.chat-input-v2-input-box-editable');
    const modeBtn = document.querySelector('.v2-agent-entry-btn__name');
    const bar = document.querySelector('.messageInputPrimaryToolbar');
    return JSON.stringify({
      hasContainer: !!c, hasEditable: !!editable,
      modeName: modeBtn ? modeBtn.textContent : null,
      barText: bar ? bar.innerText.slice(0, 80).replace(/\\n/g, '|') : null,
      bodyHead: document.body.innerText.slice(0, 120).replace(/\\n/g, '|')
    });
  })()`));
  console.log("mode menu:", await ev(`(() => { const b = document.querySelector('.v2-agent-entry-btn'); if (!b) return 'NO_MODE_BTN'; b.click(); return 'opened'; })()`));
  await sleep(1000);
  console.log("options:", await ev(`(() => {
    const pop = document.querySelector('.popup-menu--agent, .popup-menu');
    return pop ? pop.innerText.slice(0, 300).replace(/\\n/g, '|') : 'NO_POPUP';
  })()`));
  ws.close();
  process.exit(0);
};
setTimeout(() => { console.log("TIMEOUT"); process.exit(1); }, 15000);