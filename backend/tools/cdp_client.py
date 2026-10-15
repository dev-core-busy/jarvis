"""Chrome DevTools Protocol (CDP) Client – Singleton WebSocket-Verbindung zu Chrome.

Verbindet sich ueber ws://localhost:9222 mit einem Chrome-Browser,
der mit --remote-debugging-port=9222 gestartet wurde.

Verwendung:
    cdp = CDPClient()
    await cdp.connect()
    result = await cdp.execute_js("document.title")
    content = await cdp.get_page_content()
"""

import asyncio
import json
import logging
from typing import Any, Optional

import httpx
import websockets

logger = logging.getLogger("jarvis.cdp")

CDP_PORT = 9222
CDP_HTTP = f"http://localhost:{CDP_PORT}"


class CDPError(Exception):
    """Basis-Fehler fuer CDP-Operationen."""


class CDPConnectionError(CDPError):
    """Chrome nicht erreichbar oder WebSocket getrennt."""


class CDPTimeoutError(CDPError):
    """CDP-Kommando Timeout."""


class CDPClient:
    """Singleton CDP-Client mit asyncio WebSocket-Verbindung."""

    _instance: Optional["CDPClient"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._ws = None
        self._req_id: int = 0
        self._lock = asyncio.Lock()
        self._pending: dict[int, asyncio.Future] = {}
        self._listener_task: Optional[asyncio.Task] = None
        self._connected: bool = False
        self._current_tab_url: str = ""

    async def connect(self, port: int = CDP_PORT) -> None:
        """Verbindet sich mit dem ersten Page-Tab in Chrome."""
        if self._connected and self._ws:
            return

        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"http://localhost:{port}/json")
                resp.raise_for_status()
                tabs = resp.json()
        except Exception as e:
            raise CDPConnectionError(
                f"Chrome CDP nicht erreichbar auf Port {port}. "
                f"Ist Chrome mit --remote-debugging-port={port} gestartet? Fehler: {e}"
            )

        # Ersten Page-Tab finden (keine Extensions/DevTools)
        page_tab = None
        for tab in tabs:
            if tab.get("type") == "page":
                page_tab = tab
                break

        if not page_tab:
            raise CDPConnectionError("Kein Browser-Tab gefunden. Bitte eine Webseite oeffnen.")

        ws_url = page_tab.get("webSocketDebuggerUrl")
        if not ws_url:
            raise CDPConnectionError("Kein WebSocket-Endpunkt fuer den Tab verfuegbar.")

        try:
            self._ws = await websockets.connect(ws_url, max_size=16 * 1024 * 1024)
        except Exception as e:
            raise CDPConnectionError(f"WebSocket-Verbindung fehlgeschlagen: {e}")

        self._connected = True
        self._current_tab_url = page_tab.get("url", "")
        self._req_id = 0
        self._pending.clear()

        # Listener-Task starten
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
        self._listener_task = asyncio.create_task(self._recv_loop())

        logger.info(f"CDP verbunden mit Tab: {self._current_tab_url}")

    async def disconnect(self) -> None:
        """WebSocket sauber schliessen."""
        self._connected = False
        if self._listener_task and not self._listener_task.done():
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass
        self._listener_task = None

        if self._ws:
            try:
                await self._ws.close()
            except Exception:
                pass
            self._ws = None

        # Alle wartenden Futures abbrechen
        for fut in self._pending.values():
            if not fut.done():
                fut.set_exception(CDPConnectionError("Verbindung geschlossen"))
        self._pending.clear()

    async def _ensure_connected(self) -> None:
        """Lazy-Connect: verbindet falls nicht verbunden."""
        if not self._connected or not self._ws:
            await self.connect()

    async def _send(self, method: str, params: dict = None, timeout: float = 15) -> dict:
        """Sendet CDP-Kommando und wartet auf Antwort."""
        await self._ensure_connected()

        async with self._lock:
            self._req_id += 1
            req_id = self._req_id

            msg = {"id": req_id, "method": method}
            if params:
                msg["params"] = params

            loop = asyncio.get_event_loop()
            future = loop.create_future()
            self._pending[req_id] = future

            try:
                await self._ws.send(json.dumps(msg))
            except Exception as e:
                self._pending.pop(req_id, None)
                self._connected = False
                raise CDPConnectionError(f"Senden fehlgeschlagen: {e}")

        # Auf Antwort warten (ausserhalb Lock)
        try:
            result = await asyncio.wait_for(future, timeout=timeout)
        except asyncio.TimeoutError:
            self._pending.pop(req_id, None)
            raise CDPTimeoutError(f"Timeout nach {timeout}s fuer {method}")

        if "error" in result:
            err = result["error"]
            raise CDPError(f"CDP-Fehler: {err.get('message', err)}")

        return result.get("result", {})

    async def _recv_loop(self) -> None:
        """Empfaengt Nachrichten vom WebSocket und loest Futures."""
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_id = msg.get("id")
                if msg_id is not None and msg_id in self._pending:
                    fut = self._pending.pop(msg_id)
                    if not fut.done():
                        fut.set_result(msg)
                # Events ohne id ignorieren (z.B. Network.requestWillBeSent)

        except websockets.ConnectionClosed:
            logger.warning("CDP WebSocket geschlossen")
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f"CDP recv_loop Fehler: {e}")
        finally:
            self._connected = False
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(CDPConnectionError("WebSocket getrennt"))
            self._pending.clear()

    # ─── Oeffentliche CDP-Methoden ────────────────────────────────

    async def execute_js(self, expression: str, await_promise: bool = False) -> Any:
        """Fuehrt JavaScript im Seitenkontext aus."""
        params = {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": await_promise,
        }
        result = await self._send("Runtime.evaluate", params)
        r = result.get("result", {})

        if r.get("subtype") == "error" or result.get("exceptionDetails"):
            exc = result.get("exceptionDetails", {})
            desc = exc.get("text", r.get("description", "Unbekannter JS-Fehler"))
            raise CDPError(f"JavaScript-Fehler: {desc}")

        return r.get("value", r.get("description", str(r)))

    async def get_page_content(self, fmt: str = "text") -> str:
        """Gibt Seiteninhalt als Text oder HTML zurueck."""
        if fmt == "html":
            return await self.execute_js("document.documentElement.outerHTML")
        return await self.execute_js("document.body.innerText")

    async def get_page_info(self) -> dict:
        """Titel, URL, readyState der Seite."""
        return await self.execute_js(
            "({title: document.title, url: location.href, "
            "readyState: document.readyState})"
        )

    async def query_selector(self, selector: str, attribute: str = None) -> Optional[dict]:
        """Findet ein Element per CSS-Selector."""
        escaped = selector.replace("'", "\\'")
        if attribute:
            attr_escaped = attribute.replace("'", "\\'")
            js = (
                f"(() => {{ const el = document.querySelector('{escaped}'); "
                f"if (!el) return null; "
                f"return el.getAttribute('{attr_escaped}') || el['{attr_escaped}'] || null; }})()"
            )
            return await self.execute_js(js)

        js = (
            f"(() => {{ const el = document.querySelector('{escaped}'); "
            f"if (!el) return null; "
            f"return {{tag: el.tagName, id: el.id, class: el.className, "
            f"text: (el.innerText || '').substring(0, 500), "
            f"value: el.value || '', "
            f"href: el.href || '', "
            f"type: el.type || '', "
            f"name: el.name || ''}}; }})()"
        )
        return await self.execute_js(js)

    async def query_selector_all(self, selector: str, limit: int = 20) -> list:
        """Findet mehrere Elemente per CSS-Selector."""
        escaped = selector.replace("'", "\\'")
        js = (
            f"(() => {{ const els = document.querySelectorAll('{escaped}'); "
            f"const result = []; "
            f"for (let i = 0; i < Math.min(els.length, {limit}); i++) {{ "
            f"const el = els[i]; "
            f"result.push({{tag: el.tagName, id: el.id, "
            f"text: (el.innerText || '').substring(0, 200), "
            f"href: el.href || '', value: el.value || ''}}); "
            f"}} return result; }})()"
        )
        return await self.execute_js(js)

    async def click_element(self, selector: str) -> bool:
        """Klickt ein Element per CSS-Selector."""
        escaped = selector.replace("'", "\\'")
        js = (
            f"(() => {{ const el = document.querySelector('{escaped}'); "
            f"if (!el) return false; el.click(); return true; }})()"
        )
        return await self.execute_js(js)

    async def fill_field(self, selector: str, value: str) -> bool:
        """Fuellt ein Formularfeld und dispatcht input/change Events."""
        sel_escaped = selector.replace("'", "\\'")
        val_escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        js = (
            f"(() => {{ const el = document.querySelector('{sel_escaped}'); "
            f"if (!el) return false; "
            f"const nativeSetter = Object.getOwnPropertyDescriptor("
            f"window.HTMLInputElement.prototype, 'value')?.set || "
            f"Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value')?.set; "
            f"if (nativeSetter) nativeSetter.call(el, '{val_escaped}'); "
            f"else el.value = '{val_escaped}'; "
            f"el.dispatchEvent(new Event('input', {{bubbles: true}})); "
            f"el.dispatchEvent(new Event('change', {{bubbles: true}})); "
            f"return true; }})()"
        )
        return await self.execute_js(js)

    async def get_cookies(self, domain: str = None) -> list:
        """Liest Cookies (optional gefiltert nach Domain)."""
        params = {}
        if domain:
            params["urls"] = [f"https://{domain}", f"http://{domain}"]
        result = await self._send("Network.getCookies", params)
        return result.get("cookies", [])

    async def set_cookie(self, name: str, value: str, domain: str, **kwargs) -> bool:
        """Setzt einen Cookie."""
        params = {"name": name, "value": value, "domain": domain}
        params.update(kwargs)
        result = await self._send("Network.setCookie", params)
        return result.get("success", False)

    async def delete_cookies(self, name: str = None, domain: str = None) -> bool:
        """Loescht Cookies (nach Name und/oder Domain)."""
        params = {}
        if name:
            params["name"] = name
        if domain:
            params["domain"] = domain
        if not params:
            return False
        await self._send("Network.deleteCookies", params)
        return True

    async def wait_for_selector(self, selector: str, timeout: float = 10) -> bool:
        """Wartet bis ein Element erscheint (Polling alle 500ms)."""
        escaped = selector.replace("'", "\\'")
        deadline = asyncio.get_event_loop().time() + timeout
        while asyncio.get_event_loop().time() < deadline:
            result = await self.execute_js(
                f"!!document.querySelector('{escaped}')"
            )
            if result:
                return True
            await asyncio.sleep(0.5)
        return False

    async def get_links(self, filter_text: str = None, limit: int = 50) -> list:
        """Alle Links auf der Seite (optional gefiltert)."""
        js = (
            f"(() => {{ const links = []; "
            f"document.querySelectorAll('a[href]').forEach(a => {{ "
            f"links.push({{href: a.href, text: (a.innerText || '').trim().substring(0, 100)}}); "
            f"}}); return links.slice(0, {limit}); }})()"
        )
        links = await self.execute_js(js)
        if filter_text and isinstance(links, list):
            ft = filter_text.lower()
            links = [l for l in links if ft in (l.get("text", "") + l.get("href", "")).lower()]
        return links

    async def list_tabs(self, port: int = CDP_PORT) -> list:
        """Alle offenen Tabs via HTTP-API."""
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"http://localhost:{port}/json")
                tabs = resp.json()
                return [
                    {"id": t.get("id"), "title": t.get("title", ""), "url": t.get("url", "")}
                    for t in tabs if t.get("type") == "page"
                ]
        except Exception as e:
            raise CDPConnectionError(f"Tab-Liste nicht abrufbar: {e}")

    async def switch_tab(self, tab_id: str, port: int = CDP_PORT) -> bool:
        """Wechselt die CDP-Verbindung zu einem anderen Tab."""
        await self.disconnect()
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                resp = await client.get(f"http://localhost:{port}/json")
                tabs = resp.json()
        except Exception as e:
            raise CDPConnectionError(f"Tab-Wechsel fehlgeschlagen: {e}")

        target = None
        for tab in tabs:
            if tab.get("id") == tab_id:
                target = tab
                break

        if not target:
            raise CDPError(f"Tab '{tab_id}' nicht gefunden")

        ws_url = target.get("webSocketDebuggerUrl")
        if not ws_url:
            raise CDPConnectionError("Kein WebSocket-Endpunkt fuer den Tab")

        self._ws = await websockets.connect(ws_url, max_size=16 * 1024 * 1024)
        self._connected = True
        self._current_tab_url = target.get("url", "")
        self._listener_task = asyncio.create_task(self._recv_loop())
        return True

    async def navigate(self, url: str) -> dict:
        """Navigiert den aktuellen Tab zu einer URL."""
        result = await self._send("Page.navigate", {"url": url})
        # Warten bis Seite geladen
        await asyncio.sleep(1)
        return result
