// Day-1 probe: end-to-end submit -> status -> read-back over CDP (authorized harmless ask test).
const TEXT = "请只回复 OK 两个字母，不要执行任何其他操作。";
const list = await (await fetch("http://127.0.0.1:9222/json/list")).json();
const page = list.find((t) => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
let nextId = 1;
const pending = new Map();
const send = (method, params = {}) => {
  const id = nextId++;
  ws.send(JSON.stringify({ id, method, params }));
  return new Promise((res, rej) => {
    pending.set(id, { res, rej });
    setTimeout(() => { if (pending.has(id)) { pending.delete(id); rej(new Error("timeout " + method)); } }, 10000);
  });
};
const ev = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, returnByValue: true });
  if (r.exceptionDetails) throw new Error(JSON.stringify(r.exceptionDetails).slice(0, 300));
  return r.result.value;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const STATE = `(() => {
  const sendBtn = document.querySelector('.chat-input-v2-send-button');
  const stopBtn = [...document.querySelectorAll('button')].find(b => /stop|停止/i.test(b.className + (b.getAttribute('aria-label') || '')));
  const root = document.querySelector('.ai-chat-v2-ide-root');
  const thinking = root ? /思考中|生成中|运行中/.test(root.innerText) : false;
  return JSON.stringify({
    sendCls: sendBtn ? sendBtn.className : null,
    running: !!stopBtn || thinking,
    chatText: root ? root.innerText.slice(0, 900) : null
  });
})()`;

ws.onmessage = (evMsg) => {
  const m = JSON.parse(evMsg.data);
  if (m.id && pending.has(m.id)) {
    const { res, rej } = pending.get(m.id);
    pending.delete(m.id);
    m.error ? rej(new Error(JSON.stringify(m.error))) : res(m.result);
  }
};

ws.onopen = async () => {
  try {
    console.log("mode menu:", await ev(`(() => { const b = document.querySelector('.v2-agent-entry-btn'); if (!b) return 'NO_MODE_BTN'; b.click(); return 'opened'; })()`));
    await sleep(800);
    const pick = await ev(`(() => {
      const pop = document.querySelector('.popup-menu');
      if (!pop) return JSON.stringify({ picked: null, names: ['NO_POPUP'] });
      const items = [...pop.querySelectorAll('*')].filter(el => el.children.length <= 2 && (el.textContent || '').trim() && el.getBoundingClientRect().height > 0);
      const names = [...new Set(items.map(el => (el.textContent || '').trim().slice(0, 30)))];
      const target = items.find(el => /^(Chat|Ask|对话|问答)$/i.test((el.textContent || '').trim()));
      if (target) { target.click(); return JSON.stringify({ picked: (target.textContent || '').trim().slice(0, 30), names }); }
      return JSON.stringify({ picked: null, names });
    })()`);
    console.log("mode pick:", pick);
    if (JSON.parse(pick).picked === null) { console.log("ABORT: no ask/chat mode option found"); ws.close(); process.exit(2); }
    await sleep(800);
    console.log("mode now:", await ev(`(() => { const n = document.querySelector('.v2-agent-entry-btn__name'); return n ? n.textContent : null; })()`));
    console.log("focus:", await ev(`(() => { const el = document.querySelector('.chat-input-v2-input-box-editable'); if (!el) return 'NO_COMPOSER'; el.focus(); return document.activeElement === el ? 'focused' : 'focus_failed'; })()`));
    await send("Input.insertText", { text: TEXT });
    await sleep(500);
    console.log("after type:", await ev(STATE));
    console.log("click:", await ev(`(() => { const b = document.querySelector('.chat-input-v2-send-button'); if (!b) return 'NO_BTN'; if (/disabled/.test(b.className)) return 'STILL_DISABLED'; b.click(); return 'clicked'; })()`));
    for (let i = 0; i < 12; i++) {
      await sleep(3000);
      const s = JSON.parse(await ev(STATE));
      console.log(`T+${(i + 1) * 3}s running=${s.running} send=${(s.sendCls || "").slice(-25)}`);
      if (i === 1 || i === 11 || (!s.running && i > 1)) console.log("chatText:", JSON.stringify(s.chatText));
      if (!s.running && i > 1 && s.chatText && /(^|\n)OK(\n|$)/.test(s.chatText)) break;
    }
  } catch (e) {
    console.log("PROBE_ERROR", e.message);
  }
  ws.close();
  process.exit(0);
};
ws.onerror = (e) => { console.log("WS_ERROR", e.message); process.exit(1); };