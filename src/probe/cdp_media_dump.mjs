const port = process.argv[2] || "9333";
setTimeout(() => { console.log(JSON.stringify({ ok: false, error: "timeout" })); process.exit(0); }, 12000);
const list = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = list.find((t) => t.type === "page");
const ws = new WebSocket(page.webSocketDebuggerUrl);
const r = await new Promise((res) => {
  ws.onopen = () => ws.send(JSON.stringify({ id: 1, method: "Runtime.evaluate", params: {
    expression: `(() => {
      const imgs = [...document.querySelectorAll('img')].map(i => ({ src: (i.src||'').slice(0,80), w: i.width, h: i.height, alt: i.alt||'' }));
      const iframes = [...document.querySelectorAll('iframe')].map(f => ({ src: (f.src||'').slice(0,100), w: f.width, h: f.height }));
      const canvas = [...document.querySelectorAll('canvas')].map(c => ({ w: c.width, h: c.height }));
      const svgs = document.querySelectorAll('svg').length;
      return JSON.stringify({ imgs, iframes, canvas, svgs, htmlLen: document.body.innerHTML.length,
        htmlSnippet: document.body.innerHTML.slice(0, 600) });
    })()`, returnByValue: true } }));
  ws.onmessage = (ev) => { const m = JSON.parse(ev.data); if (m.id === 1) { res(m.result?.result?.value); ws.close(); } };
});
console.log(r); process.exit(0);