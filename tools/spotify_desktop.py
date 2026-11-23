"""Spotify desktop controls via Chrome DevTools Protocol (CDP).

Exports (consumed by main.py):
    status() -> dict
    control(action, query) -> str
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Any

import requests
import websocket

CDP_PORT = 9227
CDP_BASE = f"http://127.0.0.1:{CDP_PORT}"

CONNECT_TIMEOUT = 2.0
EVAL_TIMEOUT = 30.0
APP_READY_TIMEOUT = 20.0
APP_READY_PROBE_TIMEOUT = 2.0
ENSURE_POLL_TIMEOUT = 25.0
ENSURE_POLL_INTERVAL = 0.4
RELAUNCH_COOLDOWN = 15.0

_AUTO_LAUNCH_STATUS = False

# ---------------------------------------------------------------------------
# Static coordinates.
#
# TOP_PLAY_BUTTON_COORD: the big green play button in search results.
# LIKED_SONGS_SIDEBAR_COORD: the "Liked Songs" entry in the left sidebar.
#   The sidebar must be expanded and the Spotify window must be the same size
#   and DPI as when these were measured, otherwise the click lands on the
#   wrong element.
#
# To (re)discover either coordinate, run with Spotify running:
#   python -c "from tools.spotify_desktop import discover_liked_songs_sidebar_coord; import json; print(json.dumps(discover_liked_songs_sidebar_coord(), indent=2))"
# ---------------------------------------------------------------------------
TOP_PLAY_BUTTON_COORD: tuple[int, int] | None = (1039, 180)
LIKED_SONGS_SIDEBAR_COORD: tuple[int, int] | None = (44, 211)

SPOTIFY_EXE = os.path.expandvars(r"%APPDATA%\Spotify\Spotify.exe")
SPOTIFY_ARGS = [
    f"--remote-debugging-port={CDP_PORT}",
    "--remote-allow-origins=*",
]

_cached_ws_url: str | None = None
_last_relaunch_attempt: float = 0.0


# ---------------------------------------------------------------------------
# CDP discovery + evaluation
# ---------------------------------------------------------------------------

def _find_ws_url() -> str | None:
    global _cached_ws_url
    try:
        resp = requests.get(f"{CDP_BASE}/json/list", timeout=CONNECT_TIMEOUT)
        targets = resp.json()
    except (requests.RequestException, ValueError):
        _cached_ws_url = None
        return None
    for target in targets:
        if target.get("type") != "page":
            continue
        url = target.get("url", "")
        if "open.spotify.com" in url or "spotify" in url.lower():
            _cached_ws_url = target["webSocketDebuggerUrl"]
            return _cached_ws_url
    _cached_ws_url = None
    return None


def _evaluate_js(expression: str, timeout: float = EVAL_TIMEOUT) -> Any:
    global _cached_ws_url

    ws_url = _cached_ws_url or _find_ws_url()
    if not ws_url:
        return {"error": "Spotify CDP not reachable."}

    def _connect(url: str) -> websocket.WebSocket | None:
        try:
            return websocket.create_connection(url, timeout=CONNECT_TIMEOUT)
        except (websocket.WebSocketException, OSError):
            return None

    ws = _connect(ws_url)
    if ws is None:
        _cached_ws_url = None
        ws_url = _find_ws_url()
        if not ws_url:
            return {"error": "Could not connect to Spotify CDP."}
        ws = _connect(ws_url)
        if ws is None:
            return {"error": "Could not connect to Spotify CDP."}

    try:
        ws.settimeout(timeout)
        ws.send(json.dumps({
            "id": 1,
            "method": "Runtime.evaluate",
            "params": {"expression": expression, "returnByValue": True, "awaitPromise": True},
        }))
        for _ in range(500):
            try:
                msg = json.loads(ws.recv())
            except websocket.WebSocketTimeoutException:
                return {"error": "Timeout waiting for Spotify to respond."}
            if msg.get("id") != 1:
                continue
            if "error" in msg:
                return {"error": str(msg["error"])}
            result = msg.get("result", {})
            if "exceptionDetails" in result:
                return {"error": str(result["exceptionDetails"].get("text", "JS exception"))}
            return result.get("result", {}).get("value")
        return {"error": "CDP returned no matching response."}
    except (websocket.WebSocketException, OSError) as exc:
        return {"error": f"CDP evaluation failed: {exc}"}
    finally:
        try:
            ws.close()
        except Exception:
            pass


def _open_cdp_ws() -> tuple[websocket.WebSocket | None, str | None]:
    global _cached_ws_url
    ws_url = _cached_ws_url or _find_ws_url()
    if not ws_url:
        return None, "Spotify CDP not reachable."
    try:
        ws = websocket.create_connection(ws_url, timeout=CONNECT_TIMEOUT)
        ws.settimeout(EVAL_TIMEOUT)
        return ws, None
    except (websocket.WebSocketException, OSError):
        _cached_ws_url = None
        ws_url = _find_ws_url()
        if not ws_url:
            return None, "Could not connect to Spotify CDP."
        try:
            ws = websocket.create_connection(ws_url, timeout=CONNECT_TIMEOUT)
            ws.settimeout(EVAL_TIMEOUT)
            return ws, None
        except (websocket.WebSocketException, OSError) as exc:
            return None, f"Could not connect to Spotify CDP: {exc}"


def _cdp_cmd(ws: websocket.WebSocket, msg_id: int, method: str, params: dict) -> dict:
    try:
        ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
    except (websocket.WebSocketException, OSError) as exc:
        return {"error": str(exc)}
    for _ in range(500):
        try:
            msg = json.loads(ws.recv())
        except websocket.WebSocketTimeoutException:
            return {"error": "Timeout waiting for CDP response."}
        except (websocket.WebSocketException, OSError) as exc:
            return {"error": str(exc)}
        if msg.get("id") != msg_id:
            continue
        return msg
    return {"error": "CDP returned no matching response."}


def _cdp_eval(ws: websocket.WebSocket, msg_id: int, expression: str) -> Any:
    resp = _cdp_cmd(ws, msg_id, "Runtime.evaluate", {
        "expression": expression, "returnByValue": True, "awaitPromise": True,
    })
    if "error" in resp:
        return {"error": resp["error"]}
    result = resp.get("result", {})
    if "exceptionDetails" in result:
        return {"error": str(result["exceptionDetails"].get("text", "JS exception"))}
    return result.get("result", {}).get("value") or {}


# ---------------------------------------------------------------------------
# Process control / CDP self-healing
# ---------------------------------------------------------------------------

def _spotify_process_running() -> bool:
    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Spotify.exe", "/NH"],
            capture_output=True, text=True, timeout=2,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        return "Spotify.exe" in result.stdout
    except Exception:
        return False


def _force_close_spotify() -> None:
    try:
        subprocess.run(
            ["taskkill", "/F", "/IM", "Spotify.exe", "/T"],
            capture_output=True, timeout=5,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception:
        pass
    for _ in range(20):
        if not _spotify_process_running():
            return
        time.sleep(0.25)


def _launch_spotify_with_flags() -> bool:
    if not os.path.isfile(SPOTIFY_EXE):
        return False
    try:
        subprocess.Popen([SPOTIFY_EXE] + SPOTIFY_ARGS)
        return True
    except Exception:
        return False


def _wait_for_cdp(timeout: float) -> str | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        url = _find_ws_url()
        if url:
            return url
        time.sleep(ENSURE_POLL_INTERVAL)
    return None


def _wait_for_spotify_ready(timeout: float) -> bool:
    probe = r"""
    (() => {
        const input = document.querySelector('[data-testid="search-input"]');
        const player = document.querySelector('[data-testid="now-playing-widget"]')
            || document.querySelector('footer');
        return { ready: !!(input && player) };
    })()
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        result = _evaluate_js(probe, timeout=APP_READY_PROBE_TIMEOUT)
        if isinstance(result, dict) and result.get("ready"):
            return True
        time.sleep(0.5)
    return False


def _ensure_cdp(allow_launch_when_closed: bool) -> str | None:
    global _last_relaunch_attempt

    url = _find_ws_url()
    if url:
        return url

    running = _spotify_process_running()
    if not running and not allow_launch_when_closed:
        return None

    now = time.monotonic()
    if now - _last_relaunch_attempt < RELAUNCH_COOLDOWN:
        return None
    _last_relaunch_attempt = now

    _force_close_spotify()
    if not _launch_spotify_with_flags():
        return None

    url = _wait_for_cdp(ENSURE_POLL_TIMEOUT)
    if url:
        _wait_for_spotify_ready(APP_READY_TIMEOUT)
    return url


# ---------------------------------------------------------------------------
# JS snippets
# ---------------------------------------------------------------------------

_STATUS_JS = r"""
(() => {
    const playerBar = document.querySelector('[data-testid="now-playing-widget"]')
        || document.querySelector('footer');
    if (!playerBar) return { hasPlayer: false };

    const titleEl = playerBar.querySelector('[data-testid="context-item-link"]')
        || playerBar.querySelector('[data-testid="context-item-info-title"]')
        || playerBar.querySelector('a[href*="/track/"]');
    const title = titleEl ? (titleEl.textContent || '').trim() : '';

    const artistEl = playerBar.querySelector('[data-testid="context-item-info-artist"]')
        || playerBar.querySelector('a[href*="/artist/"]');
    const artist = artistEl ? (artistEl.textContent || '').trim() : '';

    const playBtn = document.querySelector('[data-testid="control-button-playpause"]');
    let playing = null;
    if (playBtn) {
        const label = (playBtn.getAttribute('aria-label') || '').toLowerCase();
        if (label.includes('pause')) playing = true;
        else if (label.includes('play')) playing = false;
    }

    let image = null;
    const imgEl = playerBar.querySelector('img');
    if (imgEl) {
        image = imgEl.currentSrc || imgEl.src || null;
        if (image && image.startsWith('data:')) image = null;
    }

    return { hasPlayer: true, track: title, artist, playing, image };
})()
"""

_TOGGLE_JS = r"""
(() => {
    const btn = document.querySelector('[data-testid="control-button-playpause"]');
    if (!btn) return { ok: false, error: 'play/pause button not found' };
    btn.click();
    return { ok: true };
})()
"""

_NEXT_JS = r"""
(() => {
    const btn = document.querySelector('[data-testid="control-button-skip-forward"]');
    if (!btn) return { ok: false, error: 'next button not found' };
    btn.click();
    return { ok: true };
})()
"""

_PREV_JS = r"""
(() => {
    const btn = document.querySelector('[data-testid="control-button-skip-back"]');
    if (!btn) return { ok: false, error: 'previous button not found' };
    btn.click();
    return { ok: true };
})()
"""


# Navigate to Liked Songs by clicking the sidebar entry. Broadened to match
# whatever Spotify currently renders there — it's no longer an <a href>.
_NAVIGATE_LIKED_JS = r"""
(async () => {
    let link = document.querySelector('a[href="/collection/tracks"]');
    if (!link) {
        const sidebar = document.querySelector('nav')
            || document.querySelector('[data-testid="left-sidebar"]')
            || document.querySelector('aside');
        if (sidebar) {
            for (const el of sidebar.querySelectorAll('a, button, [role="button"], [role="link"]')) {
                const t = (el.innerText || '').trim();
                if (/^liked\s*songs?$/i.test(t)) { link = el; break; }
            }
        }
    }
    if (!link) return { ok: false, error: 'Liked Songs sidebar link not found' };
    link.click();
    await new Promise(r => setTimeout(r, 1500));
    return { ok: true };
})()
"""


# After navigation (via static click OR DOM click), wait for the Liked Songs
# page to actually render: "Liked Songs" text in main, and a reasonably
# sized play button (the header one — row-hover buttons are tiny).
_LIKED_SONGS_PAGE_PROBE_JS = r"""
(async () => {
    const deadline = Date.now() + 12000;
    while (Date.now() < deadline) {
        const main = document.querySelector('main')
            || document.querySelector('[data-testid="main-view-container"]');
        if (main && /liked\s*songs/i.test(main.innerText || '')) {
            let biggest = 0;
            for (const btn of main.querySelectorAll('[data-testid="play-button"]')) {
                const r = btn.getBoundingClientRect();
                if (r.width <= 1 || r.height <= 1) continue;
                const area = r.width * r.height;
                if (area > biggest) biggest = area;
            }
            if (biggest > 1000) return { ok: true };
        }
        await new Promise(r => setTimeout(r, 200));
    }
    return { ok: false, error: 'Liked Songs page did not load within 12s' };
})()
"""


# Locate the big green playlist-header play button (largest play-button in
# main content). Row-level hover buttons are much smaller, so the largest
# one is always the header button on a playlist/album page.
_FIND_PLAYLIST_PLAY_BUTTON_JS = r"""
(() => {
    const playerBar = document.querySelector('[data-testid="now-playing-widget"]')
        || document.querySelector('footer');
    const main = document.querySelector('main')
        || document.querySelector('[data-testid="main-view-container"]');
    if (!main) return { ok: false, error: 'main content not found' };

    const candidates = [];
    for (const btn of main.querySelectorAll('[data-testid="play-button"]')) {
        if (playerBar && playerBar.contains(btn)) continue;
        const rect = btn.getBoundingClientRect();
        if (rect.width <= 1 || rect.height <= 1) continue;
        candidates.push({ btn, rect });
    }
    if (candidates.length === 0) {
        return { ok: false, error: 'no visible play buttons in main content' };
    }

    candidates.sort((a, b) => (b.rect.width * b.rect.height) - (a.rect.width * a.rect.height));
    const top = candidates[0];

    return {
        ok: true,
        x: Math.round(top.rect.left + top.rect.width / 2),
        y: Math.round(top.rect.top + top.rect.height / 2),
        width: top.rect.width,
        height: top.rect.height,
        ariaLabel: top.btn.getAttribute('aria-label') || '',
        buttonCount: candidates.length,
    };
})()
"""


# Find the sidebar "Liked Songs" entry by text. Used only by the discovery
# helper so the user can lock in a static coordinate.
_FIND_LIKED_SONGS_SIDEBAR_JS = r"""
(() => {
    const sidebar = document.querySelector('nav')
        || document.querySelector('[data-testid="left-sidebar"]')
        || document.querySelector('aside')
        || document.body;

    const candidates = [];
    for (const el of sidebar.querySelectorAll('a, button, [role="button"], [role="link"], li')) {
        const text = (el.innerText || '').trim();
        if (!/^liked\s*songs?$/i.test(text)) continue;
        const r = el.getBoundingClientRect();
        if (r.width <= 1 || r.height <= 1) continue;
        candidates.push({ el, r });
    }
    if (candidates.length === 0) {
        return { ok: false, error: 'no Liked Songs element in sidebar' };
    }
    candidates.sort((a, b) => a.r.top - b.r.top);
    const top = candidates[0];
    return {
        ok: true,
        x: Math.round(top.r.left + top.r.width / 2),
        y: Math.round(top.r.top + top.r.height / 2),
        rect: { left: top.r.left, top: top.r.top, w: top.r.width, h: top.r.height },
        tag: top.el.tagName,
        href: top.el.getAttribute('href') || null,
        text: (top.el.innerText || '').trim(),
    };
})()
"""


def _type_query_js(query: str) -> str:
    q = json.dumps(query)
    return f"""
(async () => {{
    const query = {q};
    const searchInput = document.querySelector('[data-testid="search-input"]');
    if (!searchInput) return {{ ok: false, error: 'search input not found' }};

    searchInput.focus();
    searchInput.click();
    if (typeof searchInput.setSelectionRange === 'function') {{
        try {{ searchInput.setSelectionRange(0, searchInput.value.length); }} catch (e) {{}}
    }}
    document.execCommand('insertText', false, query);
    if (searchInput.value !== query) {{
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value').set;
        setter.call(searchInput, query);
        searchInput.dispatchEvent(new Event('input', {{ bubbles: true }}));
        searchInput.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }}

    const deadline = Date.now() + 2500;
    while (Date.now() < deadline) {{
        if (searchInput.value === query) return {{ ok: true, value: searchInput.value }};
        await new Promise(r => setTimeout(r, 100));
    }}
    return {{ ok: false, error: 'input value did not update', value: searchInput.value }};
}})()
"""


def _wait_for_results_js(query: str) -> str:
    q = json.dumps(query)
    return f"""
(async () => {{
    const query = {q};
    const tokens = query.toLowerCase().split(/\\W+/).filter(t => t.length > 1);
    if (tokens.length === 0) return {{ ok: false, error: 'query has no usable tokens' }};

    const searchInput = document.querySelector('[data-testid="search-input"]');
    const main = document.querySelector('main')
        || document.querySelector('[data-testid="main-view-container"]');
    if (!searchInput || !main) return {{ ok: false, error: 'search input or main content missing' }};

    function resultsReflectQuery() {{
        for (const el of main.querySelectorAll('[data-testid="title"], [data-testid="subtitle"]')) {{
            const text = (el.innerText || '').toLowerCase();
            for (const token of tokens) {{
                if (text.includes(token)) return true;
            }}
        }}
        return false;
    }}

    const deadline = Date.now() + 10000;
    while (Date.now() < deadline) {{
        await new Promise(r => setTimeout(r, 200));
        if (searchInput.value !== query) continue;
        if (resultsReflectQuery()) {{
            await new Promise(r => setTimeout(r, 800));
            return {{ ok: true }};
        }}
    }}
    return {{ ok: false, error: 'search results did not reflect the query within 10s' }};
}})()
"""


_FIND_TOP_PLAY_BUTTON_JS = r"""
(() => {
    const playerBar = document.querySelector('[data-testid="now-playing-widget"]')
        || document.querySelector('footer');
    const main = document.querySelector('main')
        || document.querySelector('[data-testid="main-view-container"]');
    if (!main) return { ok: false, error: 'main content not found' };

    const candidates = [];
    for (const btn of main.querySelectorAll('[data-testid="play-button"]')) {
        if (playerBar && playerBar.contains(btn)) continue;
        const rect = btn.getBoundingClientRect();
        if (rect.width <= 1 || rect.height <= 1) continue;
        candidates.push({ btn, rect });
    }

    if (candidates.length === 0) {
        return { ok: false, error: 'no visible play buttons in main content' };
    }

    candidates.sort((a, b) => {
        if (Math.abs(a.rect.top - b.rect.top) > 3) return a.rect.top - b.rect.top;
        return a.rect.left - b.rect.left;
    });
    const top = candidates[0];

    let title = '';
    let node = top.btn;
    for (let i = 0; i < 8 && node && node !== main; i++) {
        if (node.querySelector) {
            const titleEl = node.querySelector('[data-testid="title"]');
            if (titleEl) { title = (titleEl.innerText || '').trim(); break; }
        }
        node = node.parentElement;
    }

    return {
        ok: true,
        x: Math.round(top.rect.left + top.rect.width / 2),
        y: Math.round(top.rect.top + top.rect.height / 2),
        title: title,
        buttonCount: candidates.length,
    };
})()
"""


def _element_at_coord_js(x: int, y: int) -> str:
    return f"""
(() => {{
    const el = document.elementFromPoint({x}, {y});
    if (!el) return {{ el: null }};
    const cs = getComputedStyle(el);
    return {{
        tag: el.tagName,
        testid: el.getAttribute('data-testid'),
        role: el.getAttribute('role'),
        ariaLabel: el.getAttribute('aria-label'),
        pointerEvents: cs.pointerEvents,
        opacity: cs.opacity,
        text: (el.innerText || '').slice(0, 80),
    }};
}})()
"""


# ---------------------------------------------------------------------------
# Mouse helpers
# ---------------------------------------------------------------------------

def _mouse_move(ws: websocket.WebSocket, msg_id: int, x: int, y: int) -> None:
    _cdp_cmd(ws, msg_id, "Input.dispatchMouseEvent", {
        "type": "mouseMoved", "x": x, "y": y,
    })


def _single_click(ws: websocket.WebSocket, msg_id: int, x: int, y: int) -> None:
    _cdp_cmd(ws, msg_id, "Input.dispatchMouseEvent", {
        "type": "mousePressed", "x": x, "y": y,
        "button": "left", "buttons": 1, "clickCount": 1,
        "pointerType": "mouse",
    })
    _cdp_cmd(ws, msg_id + 1, "Input.dispatchMouseEvent", {
        "type": "mouseReleased", "x": x, "y": y,
        "button": "left", "buttons": 0, "clickCount": 1,
        "pointerType": "mouse",
    })


# ---------------------------------------------------------------------------
# Discovery helpers
# ---------------------------------------------------------------------------

def discover_top_play_button_coord(query: str = "timber") -> dict:
    ws, err = _open_cdp_ws()
    if not ws:
        return {"error": err or "could not open CDP session"}
    msg_id = 1
    try:
        type_info = _cdp_eval(ws, msg_id, _type_query_js(query)); msg_id += 1
        if not (isinstance(type_info, dict) and type_info.get("ok")):
            return {"error": "typing failed", "details": type_info}

        wait_info = _cdp_eval(ws, msg_id, _wait_for_results_js(query)); msg_id += 1
        if not (isinstance(wait_info, dict) and wait_info.get("ok")):
            return {"error": "results did not load", "details": wait_info}

        btn_info = _cdp_eval(ws, msg_id, _FIND_TOP_PLAY_BUTTON_JS); msg_id += 1
        if not (isinstance(btn_info, dict) and btn_info.get("ok")):
            return {"error": "no button found", "details": btn_info}

        x = int(btn_info["x"])
        y = int(btn_info["y"])
        probe = _cdp_eval(ws, msg_id, _element_at_coord_js(x, y)); msg_id += 1
        return {
            "coord": [x, y],
            "buttonTitle": btn_info.get("title", ""),
            "buttonCount": btn_info.get("buttonCount", 0),
            "elementAtCoord": probe,
            "next": (
                f"Set TOP_PLAY_BUTTON_COORD = ({x}, {y}) if elementAtCoord shows "
                f"testid='play-button'. Otherwise Spotify's layout has shifted and "
                f"the coordinate is not a play button."
            ),
        }
    finally:
        try:
            ws.close()
        except Exception:
            pass


def discover_liked_songs_sidebar_coord() -> dict:
    """Find the (x, y) of the Liked Songs entry in the left sidebar.

    Run ONCE with Spotify running, sidebar expanded:
        python -c "from tools.spotify_desktop import discover_liked_songs_sidebar_coord; import json; print(json.dumps(discover_liked_songs_sidebar_coord(), indent=2))"

    Then set LIKED_SONGS_SIDEBAR_COORD = (x, y) at the top of this file.
    """
    ws, err = _open_cdp_ws()
    if not ws:
        return {"error": err or "could not open CDP session"}
    msg_id = 1
    try:
        info = _cdp_eval(ws, msg_id, _FIND_LIKED_SONGS_SIDEBAR_JS); msg_id += 1
        if not (isinstance(info, dict) and info.get("ok")):
            return {
                "error": "could not find Liked Songs in sidebar",
                "details": info,
                "hint": "Make sure Spotify's left sidebar is expanded and shows 'Liked Songs'.",
            }
        x = int(info["x"]); y = int(info["y"])
        probe = _cdp_eval(ws, msg_id, _element_at_coord_js(x, y)); msg_id += 1
        return {
            "coord": [x, y],
            "element": info,
            "elementAtCoord": probe,
            "next": f"Set LIKED_SONGS_SIDEBAR_COORD = ({x}, {y}) at the top of this file.",
        }
    finally:
        try:
            ws.close()
        except Exception:
            pass


def test_static_click(query: str = "timber") -> dict:
    if TOP_PLAY_BUTTON_COORD is None:
        return {"error": "TOP_PLAY_BUTTON_COORD not set"}
    ws, err = _open_cdp_ws()
    if not ws:
        return {"error": err or "could not open CDP session"}
    msg_id = 1
    x, y = TOP_PLAY_BUTTON_COORD
    try:
        _cdp_eval(ws, msg_id, _type_query_js(query)); msg_id += 1
        _cdp_eval(ws, msg_id, _wait_for_results_js(query)); msg_id += 1

        pre = _cdp_eval(ws, msg_id, _element_at_coord_js(x, y)); msg_id += 1
        btn_info = _cdp_eval(ws, msg_id, _FIND_TOP_PLAY_BUTTON_JS); msg_id += 1

        _mouse_move(ws, msg_id, 0, 0); msg_id += 1
        time.sleep(0.1)
        _mouse_move(ws, msg_id, x, y); msg_id += 1
        time.sleep(0.8)

        post = _cdp_eval(ws, msg_id, _element_at_coord_js(x, y)); msg_id += 1

        inspect_js = f"""
        (() => {{
            const el = document.elementFromPoint({x}, {y});
            if (!el) return {{ found: false }};
            const btn = el.closest('[data-testid="play-button"]');
            if (!btn) return {{ found: true, element: el.tagName, noClosestButton: true }};
            const cs = getComputedStyle(btn);
            const rect = btn.getBoundingClientRect();
            return {{
                found: true,
                buttonTag: btn.tagName,
                disabled: btn.disabled,
                ariaDisabled: btn.getAttribute('aria-disabled'),
                rect: {{ x: rect.left, y: rect.top, w: rect.width, h: rect.height }},
                style: {{
                    pointerEvents: cs.pointerEvents,
                    opacity: cs.opacity,
                    visibility: cs.visibility,
                    display: cs.display,
                    zIndex: cs.zIndex,
                }},
            }};
        }})()
        """
        button_state = _cdp_eval(ws, msg_id, inspect_js); msg_id += 1

        _single_click(ws, msg_id, x, y); msg_id += 2
        played = False
        for _ in range(6):
            time.sleep(0.5)
            v = _cdp_eval(ws, msg_id, _STATUS_JS); msg_id += 1
            if isinstance(v, dict) and v.get("playing") is True:
                played = True
                break

        return {
            "coord": [x, y],
            "beforeHover": pre,
            "afterHover": post,
            "buttonState": button_state,
            "buttonFinderResult": btn_info,
            "playedAfterClick": played,
        }
    finally:
        try:
            ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Search + play
# ---------------------------------------------------------------------------

def _click_and_verify(
    ws: websocket.WebSocket, msg_id: int, x: int, y: int,
    attempts: int = 2, verify_seconds: float = 3.0,
) -> tuple[bool, dict, int]:
    _mouse_move(ws, msg_id, 0, 0); msg_id += 1
    time.sleep(0.1)
    _mouse_move(ws, msg_id, x, y); msg_id += 1
    time.sleep(0.6)

    for _attempt in range(attempts):
        _single_click(ws, msg_id, x, y); msg_id += 2
        polls = int(verify_seconds / 0.5)
        for _ in range(polls):
            time.sleep(0.5)
            verify = _cdp_eval(ws, msg_id, _STATUS_JS); msg_id += 1
            if isinstance(verify, dict) and verify.get("playing") is True:
                return True, verify, msg_id
        time.sleep(0.3)
    return False, {}, msg_id


def _search_and_play(query: str) -> dict:
    ws, err = _open_cdp_ws()
    if not ws:
        return {"ok": False, "error": err or "could not open CDP session"}

    msg_id = 1
    try:
        type_info = _cdp_eval(ws, msg_id, _type_query_js(query)); msg_id += 1
        if not (isinstance(type_info, dict) and type_info.get("ok")):
            return {"ok": False, "error": (type_info or {}).get("error", "typing failed")}

        wait_info = _cdp_eval(ws, msg_id, _wait_for_results_js(query)); msg_id += 1
        if not (isinstance(wait_info, dict) and wait_info.get("ok")):
            return {"ok": False, "error": (wait_info or {}).get("error", "results did not load")}

        attempts_log: list[dict] = []

        if TOP_PLAY_BUTTON_COORD is not None:
            x, y = TOP_PLAY_BUTTON_COORD
            probe = _cdp_eval(ws, msg_id, _element_at_coord_js(x, y)); msg_id += 1
            attempts_log.append({"via": "static", "coord": [x, y], "elementAtCoord": probe})
            played, verify, msg_id = _click_and_verify(ws, msg_id, x, y)
            if played:
                return {"ok": True, "via": "static-coord", "coord": [x, y],
                        "title": verify.get("track", "")}

        btn_info = _cdp_eval(ws, msg_id, _FIND_TOP_PLAY_BUTTON_JS); msg_id += 1
        if not (isinstance(btn_info, dict) and btn_info.get("ok")):
            return {
                "ok": False,
                "error": (btn_info or {}).get("error", "no top play button"),
                "diagnostics": {"attempts": attempts_log, "btn_info": btn_info},
            }

        x = int(btn_info["x"]); y = int(btn_info["y"])
        probe = _cdp_eval(ws, msg_id, _element_at_coord_js(x, y)); msg_id += 1
        attempts_log.append({
            "via": "dynamic", "coord": [x, y],
            "buttonTitle": btn_info.get("title", ""),
            "elementAtCoord": probe,
        })
        played, verify, msg_id = _click_and_verify(ws, msg_id, x, y)
        if played:
            return {"ok": True, "via": "dynamic", "coord": [x, y],
                    "title": verify.get("track", "")}

        return {
            "ok": False,
            "error": f"click dispatched at {[x, y]} but playback did not start",
            "diagnostics": {"attempts": attempts_log},
        }
    finally:
        try:
            ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Liked Songs
# ---------------------------------------------------------------------------

def _click_playlist_and_verify(
    ws: websocket.WebSocket, msg_id: int, x: int, y: int,
    attempts: int = 2, verify_seconds: float = 4.0,
) -> tuple[bool, dict, int]:
    """Click the playlist header play button and verify via the button label.

    `_STATUS_JS.playing === True` is not usable here because something else
    may already be playing when we arrive on the Liked Songs page. The header
    button's aria-label flips to "Pause" only when THIS playlist becomes the
    active playing context.
    """
    _mouse_move(ws, msg_id, 0, 0); msg_id += 1
    time.sleep(0.1)
    _mouse_move(ws, msg_id, x, y); msg_id += 1
    time.sleep(0.6)

    for _attempt in range(attempts):
        _single_click(ws, msg_id, x, y); msg_id += 2
        polls = int(verify_seconds / 0.5)
        for _ in range(polls):
            time.sleep(0.5)
            info = _cdp_eval(ws, msg_id, _FIND_PLAYLIST_PLAY_BUTTON_JS); msg_id += 1
            if isinstance(info, dict) and info.get("ok"):
                if "pause" in (info.get("ariaLabel") or "").lower():
                    return True, info, msg_id
        time.sleep(0.3)
    return False, {}, msg_id


def _play_liked_songs() -> dict:
    ws, err = _open_cdp_ws()
    if not ws:
        return {"ok": False, "error": err or "could not open CDP session"}

    msg_id = 1
    try:
        # 1) Navigate to Liked Songs — static coord first, DOM fallback.
        nav_via = None
        if LIKED_SONGS_SIDEBAR_COORD is not None:
            sx, sy = LIKED_SONGS_SIDEBAR_COORD
            _mouse_move(ws, msg_id, 0, 0); msg_id += 1
            time.sleep(0.1)
            _mouse_move(ws, msg_id, sx, sy); msg_id += 1
            time.sleep(0.3)
            _single_click(ws, msg_id, sx, sy); msg_id += 2
            nav_via = "static-sidebar"
        else:
            nav = _cdp_eval(ws, msg_id, _NAVIGATE_LIKED_JS); msg_id += 1
            if not (isinstance(nav, dict) and nav.get("ok")):
                return {
                    "ok": False,
                    "error": (nav or {}).get("error", "navigation to Liked Songs failed"),
                    "diagnostics": {
                        "hint": "Run discover_liked_songs_sidebar_coord() and set "
                                "LIKED_SONGS_SIDEBAR_COORD to the returned coordinate.",
                    },
                }
            nav_via = "dom-link"

        # 2) Wait for the Liked Songs page to render (works for both paths).
        page = _cdp_eval(ws, msg_id, _LIKED_SONGS_PAGE_PROBE_JS); msg_id += 1
        if not (isinstance(page, dict) and page.get("ok")):
            return {
                "ok": False,
                "error": (page or {}).get("error", "Liked Songs page did not load"),
                "diagnostics": {"navigation": nav_via},
            }

        # 3) Find the header play button and click it via real mouse events.
        btn = _cdp_eval(ws, msg_id, _FIND_PLAYLIST_PLAY_BUTTON_JS); msg_id += 1
        if not (isinstance(btn, dict) and btn.get("ok")):
            return {"ok": False, "error": (btn or {}).get("error", "playlist header play button not found"),
                    "diagnostics": {"navigation": nav_via}}

        x = int(btn["x"]); y = int(btn["y"])
        label = (btn.get("ariaLabel") or "").lower()

        if "pause" in label:
            return {"ok": True, "via": f"already-playing ({nav_via})"}

        played, verify, msg_id = _click_playlist_and_verify(ws, msg_id, x, y)
        if played:
            return {"ok": True, "via": f"header-play ({nav_via})", "coord": [x, y]}

        return {
            "ok": False,
            "error": f"click at {[x, y]} did not start Liked Songs playback",
            "diagnostics": {"navigation": nav_via, "initialAriaLabel": label, "buttonFinder": btn},
        }
    finally:
        try:
            ws.close()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_SUCCESS = {
    "previous": "Went to the previous Spotify track.",
    "next": "Skipped to the next Spotify track.",
    "toggle": "Toggled Spotify playback.",
    "play": "Resumed Spotify.",
    "pause": "Paused Spotify.",
    "liked": "Playing your Liked Songs in Spotify.",
}


def status() -> dict:
    _ensure_cdp(allow_launch_when_closed=_AUTO_LAUNCH_STATUS)
    result = _evaluate_js(_STATUS_JS)
    if not isinstance(result, dict) or result.get("error") or not result.get("hasPlayer"):
        return {"open": _spotify_process_running(), "track": "", "artist": "",
                "playing": None, "image": None}
    return {"open": True, "track": result.get("track", ""),
            "artist": result.get("artist", ""), "playing": result.get("playing"),
            "image": result.get("image")}


def control(action: str, query: str = "") -> str:
    url = _ensure_cdp(allow_launch_when_closed=True)
    if not url:
        return f"Couldn't {action} Spotify: app could not be reached or launched."

    if action in ("next", "previous", "toggle"):
        js = {"next": _NEXT_JS, "previous": _PREV_JS, "toggle": _TOGGLE_JS}[action]
        result = _evaluate_js(js)
        if not isinstance(result, dict) or not result.get("ok"):
            err = result.get("error", "no response") if isinstance(result, dict) else "no response"
            return f"Couldn't {action} Spotify: {err}"
        return _SUCCESS[action]

    if action in ("play", "pause"):
        want = (action == "play")
        current = _evaluate_js(_STATUS_JS)
        if not isinstance(current, dict) or current.get("playing") is None:
            return "Couldn't determine Spotify playback state."
        if current["playing"] == want:
            return _SUCCESS[action] + " (already there.)"
        result = _evaluate_js(_TOGGLE_JS)
        if not isinstance(result, dict) or not result.get("ok"):
            return f"Couldn't {action} Spotify."
        return _SUCCESS[action]

    if action == "liked":
        result = _play_liked_songs()
        if not result.get("ok"):
            err = result.get("error", "liked songs playback failed")
            diag = result.get("diagnostics")
            if diag:
                err += f" (diag: {diag})"
            return f"Couldn't play Liked Songs: {err}"
        return _SUCCESS["liked"]

    if action == "search_play":
        q = query.strip()
        if not q:
            return "Couldn't search: no query was provided."

        if "liked song" in q.lower():
            result = _play_liked_songs()
            if not result.get("ok"):
                err = result.get("error", "liked songs playback failed")
                diag = result.get("diagnostics")
                if diag:
                    err += f" (diag: {diag})"
                return f"Couldn't play Liked Songs: {err}"
            return _SUCCESS["liked"]

        result = _search_and_play(q)
        if not result.get("ok"):
            err = result.get("error", "search failed")
            diag = result.get("diagnostics")
            if diag:
                err += f" (diag: {diag})"
            return f"Couldn't play {q}: {err}"
        return f"Playing {q} in Spotify."

    return f"Couldn't handle unknown action {action!r}."