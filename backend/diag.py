import json
import requests
import websocket

PROBE = r"""
(() => {
    const results = [];
    for (const el of document.querySelectorAll('*')) {
        if (el.children.length > 15) continue;         // skip big containers
        const text = (el.innerText || '').trim();
        if (!/\bliked\s+songs?\b/i.test(text)) continue;
        const r = el.getBoundingClientRect();
        if (r.width <= 1 || r.height <= 1) continue;
        if (r.left > window.innerWidth / 2) continue;  // left half only
        results.push({
            tag: el.tagName,
            role: el.getAttribute('role'),
            testid: el.getAttribute('data-testid'),
            ariaLabel: el.getAttribute('aria-label'),
            className: (el.className || '').toString().slice(0, 100),
            rect: {
                left: Math.round(r.left), top: Math.round(r.top),
                w: Math.round(r.width), h: Math.round(r.height),
            },
            x: Math.round(r.left + r.width / 2),
            y: Math.round(r.top + r.height / 2),
            textSnippet: text.slice(0, 80),
        });
    }
    results.sort((a, b) => (a.rect.w * a.rect.h) - (b.rect.w * b.rect.h));
    return {
        viewport: { w: window.innerWidth, h: window.innerHeight },
        count: results.length,
        candidates: results.slice(0, 15),
    };
})()
"""

CDP = "http://127.0.0.1:9227"
targets = requests.get(f"{CDP}/json/list", timeout=2).json()
ws_url = next(
    (t["webSocketDebuggerUrl"] for t in targets
     if t.get("type") == "page" and "spotify" in t.get("url", "").lower()),
    None,
)
if not ws_url:
    raise SystemExit("CDP not reachable")

ws = websocket.create_connection(ws_url, timeout=2)
ws.settimeout(15)
ws.send(json.dumps({
    "id": 1,
    "method": "Runtime.evaluate",
    "params": {"expression": PROBE, "returnByValue": True, "awaitPromise": True},
}))
for _ in range(100):
    msg = json.loads(ws.recv())
    if msg.get("id") == 1:
        print(json.dumps(msg.get("result", {}).get("result", {}).get("value"), indent=2))
        break
ws.close()