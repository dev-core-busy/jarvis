"""Browser Control Skill – Hochlevel-Steuerung des Webbrowsers via xdotool/wmctrl."""

import asyncio
import os

from backend.tools.base import BaseTool


def _get_env() -> dict:
    return os.environ.copy()


class BrowserControlTool(BaseTool):
    """Steuert den Webbrowser (Chrome/Firefox) auf dem Linux-Desktop."""

    BROWSER_CMD = "google-chrome --no-sandbox --remote-debugging-port=9222 --user-data-dir=/tmp/jarvis-chrome"

    @property
    def name(self) -> str:
        return "browser_control"

    @property
    def description(self) -> str:
        return (
            "Steuert den Webbrowser (Chrome) auf dem Desktop. Aktionen: "
            "'open' – Browser öffnen (optional mit URL). "
            "'close' – Browser komplett schließen. "
            "'navigate' – Zu URL navigieren (im aktuellen Tab). "
            "'back' – Zurück-Navigation. "
            "'forward' – Vorwärts-Navigation. "
            "'refresh' – Seite neu laden. "
            "'new_tab' – Neuen Tab öffnen (optional mit URL). "
            "'close_tab' – Aktuellen Tab schließen. "
            "'next_tab' – Zum nächsten Tab wechseln. "
            "'prev_tab' – Zum vorherigen Tab wechseln. "
            "'switch_tab' – Zu Tab Nr. wechseln (tab_number: 1-8, 9=letzter). "
            "'zoom_in' – Hineinzoomen. "
            "'zoom_out' – Herauszoomen. "
            "'zoom_reset' – Zoom zurücksetzen. "
            "'find_text' – Text auf Seite suchen (Ctrl+F). "
            "'scroll_page' – Seite scrollen (direction: up/down, amount: Seiten). "
            "'fullscreen' – Vollbild umschalten (F11). "
            "'get_url' – Aktuelle URL auslesen (via Adressleiste)."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": (
                        "Aktion: open, close, navigate, back, forward, refresh, "
                        "new_tab, close_tab, next_tab, prev_tab, switch_tab, "
                        "zoom_in, zoom_out, zoom_reset, find_text, scroll_page, "
                        "fullscreen, get_url"
                    ),
                },
                "url": {
                    "type": "STRING",
                    "description": "URL zum Navigieren (für open, navigate, new_tab)",
                },
                "text": {
                    "type": "STRING",
                    "description": "Suchtext (für find_text)",
                },
                "direction": {
                    "type": "STRING",
                    "description": "Scroll-Richtung: up oder down (für scroll_page)",
                },
                "amount": {
                    "type": "INTEGER",
                    "description": "Anzahl Seiten zum Scrollen (Standard: 1)",
                },
                "tab_number": {
                    "type": "INTEGER",
                    "description": "Tab-Nummer 1-8, 9=letzter Tab (für switch_tab)",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str,
        url: str = "",
        text: str = "",
        direction: str = "down",
        amount: int = 1,
        tab_number: int = 1,
        **kwargs,
    ) -> str:
        """Führt Browser-Aktion aus."""
        try:
            if action == "open":
                cmd = self.BROWSER_CMD
                if url:
                    cmd += f" '{url}'"
                proc = await asyncio.create_subprocess_shell(
                    f"setsid {cmd} &",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=_get_env(),
                )
                await asyncio.sleep(2)
                return f"Browser geöffnet{' mit URL: ' + url if url else ''}"

            elif action == "close":
                return await self._run("wmctrl -c 'Google Chrome' 2>/dev/null; wmctrl -c 'Chromium' 2>/dev/null; wmctrl -c 'Mozilla Firefox' 2>/dev/null || pkill -f 'chrome|chromium|firefox' 2>/dev/null")

            elif action == "navigate":
                if not url:
                    return "Fehler: Keine URL angegeben."
                # Fokus auf Adressleiste, URL eingeben, Enter
                await self._focus_browser()
                await self._run("xdotool key --clearmodifiers ctrl+l")
                await asyncio.sleep(0.2)
                await self._run("xdotool key --clearmodifiers ctrl+a")
                await asyncio.sleep(0.1)
                await self._run(f"xdotool type --clearmodifiers --delay 10 -- '{url}'")
                await asyncio.sleep(0.1)
                await self._run("xdotool key --clearmodifiers Return")
                return f"Navigation zu: {url}"

            elif action == "back":
                await self._focus_browser()
                return await self._run("xdotool key --clearmodifiers alt+Left")

            elif action == "forward":
                await self._focus_browser()
                return await self._run("xdotool key --clearmodifiers alt+Right")

            elif action == "refresh":
                await self._focus_browser()
                return await self._run("xdotool key --clearmodifiers F5")

            elif action == "new_tab":
                await self._focus_browser()
                await self._run("xdotool key --clearmodifiers ctrl+t")
                if url:
                    await asyncio.sleep(0.3)
                    await self._run(f"xdotool type --clearmodifiers --delay 10 -- '{url}'")
                    await asyncio.sleep(0.1)
                    await self._run("xdotool key --clearmodifiers Return")
                    return f"Neuer Tab geöffnet mit URL: {url}"
                return "Neuer Tab geöffnet"

            elif action == "close_tab":
                await self._focus_browser()
                return await self._run("xdotool key --clearmodifiers ctrl+w")

            elif action == "next_tab":
                await self._focus_browser()
                return await self._run("xdotool key --clearmodifiers ctrl+Tab")

            elif action == "prev_tab":
                await self._focus_browser()
                return await self._run("xdotool key --clearmodifiers ctrl+shift+Tab")

            elif action == "switch_tab":
                await self._focus_browser()
                return await self._run(f"xdotool key --clearmodifiers ctrl+{tab_number}")

            elif action == "zoom_in":
                await self._focus_browser()
                return await self._run("xdotool key --clearmodifiers ctrl+plus")

            elif action == "zoom_out":
                await self._focus_browser()
                return await self._run("xdotool key --clearmodifiers ctrl+minus")

            elif action == "zoom_reset":
                await self._focus_browser()
                return await self._run("xdotool key --clearmodifiers ctrl+0")

            elif action == "find_text":
                if not text:
                    return "Fehler: Kein Suchtext angegeben."
                await self._focus_browser()
                await self._run("xdotool key --clearmodifiers ctrl+f")
                await asyncio.sleep(0.3)
                await self._run(f"xdotool type --clearmodifiers --delay 10 -- '{text}'")
                return f"Suche nach: {text}"

            elif action == "scroll_page":
                await self._focus_browser()
                pages = max(1, amount)
                key = "Page_Down" if direction == "down" else "Page_Up"
                for _ in range(pages):
                    await self._run(f"xdotool key --clearmodifiers {key}")
                    await asyncio.sleep(0.1)
                return f"{pages}x {direction} gescrollt"

            elif action == "fullscreen":
                await self._focus_browser()
                return await self._run("xdotool key --clearmodifiers F11")

            elif action == "get_url":
                await self._focus_browser()
                # Adressleiste fokussieren, alles markieren, kopieren
                await self._run("xdotool key --clearmodifiers ctrl+l")
                await asyncio.sleep(0.2)
                await self._run("xdotool key --clearmodifiers ctrl+a")
                await asyncio.sleep(0.1)
                await self._run("xdotool key --clearmodifiers ctrl+c")
                await asyncio.sleep(0.2)
                url = await self._run("xclip -selection clipboard -o 2>/dev/null || xsel --clipboard --output 2>/dev/null")
                # Escape drücken um Adressleiste zu verlassen
                await self._run("xdotool key --clearmodifiers Escape")
                return f"Aktuelle URL: {url}"

            else:
                return f"Unbekannte Browser-Aktion: {action}"

        except Exception as e:
            return f"Browser-Fehler: {str(e)}"

    async def _focus_browser(self):
        """Bringt den Browser in den Vordergrund."""
        await self._run(
            "wmctrl -a 'Google Chrome' 2>/dev/null || "
            "wmctrl -a 'Chromium' 2>/dev/null || "
            "wmctrl -a 'Mozilla Firefox' 2>/dev/null || true"
        )
        await asyncio.sleep(0.2)

    async def _run(self, cmd: str) -> str:
        """Hilfsfunktion für Shell-Befehle."""
        env = _get_env()
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout, stderr = await proc.communicate()
        result = stdout.decode("utf-8", errors="replace").strip()
        if stderr:
            err = stderr.decode("utf-8", errors="replace").strip()
            if err:
                result += f"\n(stderr: {err})"
        return result or "(OK)"


class BrowserCDPTool(BaseTool):
    """Programmatischer Browser-Zugriff via Chrome DevTools Protocol (CDP)."""

    @property
    def name(self) -> str:
        return "browser_cdp"

    @property
    def description(self) -> str:
        return (
            "Programmatischer Zugriff auf den Browser via Chrome DevTools Protocol. "
            "Damit kannst du Webseiten-Inhalte lesen, Formulare ausfuellen, "
            "JavaScript ausfuehren, Cookies verwalten und auf Elemente warten. "
            "WICHTIG: Der Browser muss vorher mit browser_control 'open' geoeffnet sein! "
            "Aktionen: "
            "'get_page_content' – Seiteninhalt als Text oder HTML (format: text/html). "
            "'get_page_info' – Titel, URL und Ladestatus der Seite. "
            "'get_element' – Element per CSS-Selector finden (selector, attribute). "
            "'get_elements' – Mehrere Elemente per Selector (selector, limit). "
            "'click_element' – Element per CSS-Selector klicken (selector). "
            "'fill_field' – Formularfeld ausfuellen (selector, value). "
            "'execute_js' – JavaScript ausfuehren (code). "
            "'get_cookies' – Cookies lesen (optional: domain). "
            "'set_cookie' – Cookie setzen (name, value, domain). "
            "'delete_cookies' – Cookies loeschen (name, domain). "
            "'wait_for' – Warten bis Element erscheint (selector, timeout). "
            "'get_links' – Alle Links auflisten (optional: filter). "
            "'list_tabs' – Alle offenen Tabs anzeigen. "
            "'navigate' – Zu URL navigieren (url)."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "OBJECT",
            "properties": {
                "action": {
                    "type": "STRING",
                    "description": (
                        "Aktion: get_page_content, get_page_info, get_element, get_elements, "
                        "click_element, fill_field, execute_js, get_cookies, set_cookie, "
                        "delete_cookies, wait_for, get_links, list_tabs, navigate"
                    ),
                },
                "selector": {
                    "type": "STRING",
                    "description": "CSS-Selector (fuer get_element, get_elements, click_element, fill_field, wait_for)",
                },
                "value": {
                    "type": "STRING",
                    "description": "Wert (fuer fill_field, set_cookie)",
                },
                "code": {
                    "type": "STRING",
                    "description": "JavaScript-Code (fuer execute_js)",
                },
                "url": {
                    "type": "STRING",
                    "description": "URL (fuer navigate)",
                },
                "format": {
                    "type": "STRING",
                    "description": "Format: 'text' oder 'html' (fuer get_page_content, Standard: text)",
                },
                "name": {
                    "type": "STRING",
                    "description": "Cookie-Name (fuer set_cookie, delete_cookies)",
                },
                "domain": {
                    "type": "STRING",
                    "description": "Cookie-Domain (fuer set_cookie, delete_cookies, get_cookies)",
                },
                "timeout": {
                    "type": "INTEGER",
                    "description": "Timeout in Sekunden (fuer wait_for, Standard: 10)",
                },
                "attribute": {
                    "type": "STRING",
                    "description": "Attribut-Name zum Lesen (fuer get_element, z.B. 'href', 'innerText')",
                },
                "limit": {
                    "type": "INTEGER",
                    "description": "Max. Ergebnisse (fuer get_elements, get_links, Standard: 20)",
                },
                "filter": {
                    "type": "STRING",
                    "description": "Filtertext (fuer get_links)",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str = "", **kwargs) -> str:
        """Fuehrt CDP-Aktion aus."""
        from backend.tools.cdp_client import CDPClient, CDPConnectionError, CDPTimeoutError, CDPError

        cdp = CDPClient()

        try:
            if action == "get_page_content":
                fmt = kwargs.get("format", "text")
                content = await cdp.get_page_content(fmt=fmt)
                if isinstance(content, str) and len(content) > 5000:
                    return content[:5000] + f"\n\n... (gekuerzt, {len(content)} Zeichen gesamt)"
                return str(content) if content else "(Leere Seite)"

            elif action == "get_page_info":
                info = await cdp.get_page_info()
                if isinstance(info, dict):
                    return f"Titel: {info.get('title', '?')}\nURL: {info.get('url', '?')}\nStatus: {info.get('readyState', '?')}"
                return str(info)

            elif action == "get_element":
                selector = kwargs.get("selector", "")
                if not selector:
                    return "Fehler: 'selector' ist erforderlich."
                attribute = kwargs.get("attribute")
                result = await cdp.query_selector(selector, attribute=attribute)
                if result is None:
                    return f"Kein Element gefunden fuer: {selector}"
                if isinstance(result, dict):
                    parts = [f"<{result.get('tag', '?').lower()}>"]
                    if result.get("id"):
                        parts.append(f"id=\"{result['id']}\"")
                    if result.get("class"):
                        parts.append(f"class=\"{result['class'][:100]}\"")
                    if result.get("text"):
                        parts.append(f"Text: {result['text'][:300]}")
                    if result.get("href"):
                        parts.append(f"href: {result['href']}")
                    if result.get("value"):
                        parts.append(f"value: {result['value']}")
                    return " | ".join(parts)
                return str(result)

            elif action == "get_elements":
                selector = kwargs.get("selector", "")
                if not selector:
                    return "Fehler: 'selector' ist erforderlich."
                limit = int(kwargs.get("limit", 20))
                elements = await cdp.query_selector_all(selector, limit=limit)
                if not elements:
                    return f"Keine Elemente gefunden fuer: {selector}"
                lines = [f"{len(elements)} Elemente gefunden:"]
                for i, el in enumerate(elements):
                    text = (el.get("text", "") or "")[:80]
                    href = el.get("href", "")
                    line = f"  {i+1}. <{el.get('tag', '?').lower()}>"
                    if text:
                        line += f" {text}"
                    if href:
                        line += f" → {href}"
                    lines.append(line)
                return "\n".join(lines)

            elif action == "click_element":
                selector = kwargs.get("selector", "")
                if not selector:
                    return "Fehler: 'selector' ist erforderlich."
                ok = await cdp.click_element(selector)
                return f"Element '{selector}' geklickt." if ok else f"Element '{selector}' nicht gefunden."

            elif action == "fill_field":
                selector = kwargs.get("selector", "")
                value = kwargs.get("value", "")
                if not selector:
                    return "Fehler: 'selector' ist erforderlich."
                ok = await cdp.fill_field(selector, value)
                return f"Feld '{selector}' mit '{value}' ausgefuellt." if ok else f"Feld '{selector}' nicht gefunden."

            elif action == "execute_js":
                code = kwargs.get("code", "")
                if not code:
                    return "Fehler: 'code' ist erforderlich."
                result = await cdp.execute_js(code)
                text = str(result)
                if len(text) > 3000:
                    return text[:3000] + f"\n... (gekuerzt)"
                return text

            elif action == "get_cookies":
                domain = kwargs.get("domain")
                cookies = await cdp.get_cookies(domain=domain)
                if not cookies:
                    return "Keine Cookies gefunden."
                lines = [f"{len(cookies)} Cookies:"]
                for c in cookies[:30]:
                    lines.append(f"  {c.get('name', '?')}={c.get('value', '')[:50]} (domain: {c.get('domain', '?')})")
                return "\n".join(lines)

            elif action == "set_cookie":
                name = kwargs.get("name", "")
                value = kwargs.get("value", "")
                domain = kwargs.get("domain", "")
                if not name or not domain:
                    return "Fehler: 'name' und 'domain' sind erforderlich."
                ok = await cdp.set_cookie(name, value, domain)
                return f"Cookie '{name}' gesetzt." if ok else "Cookie konnte nicht gesetzt werden."

            elif action == "delete_cookies":
                name = kwargs.get("name")
                domain = kwargs.get("domain")
                if not name and not domain:
                    return "Fehler: 'name' oder 'domain' erforderlich."
                ok = await cdp.delete_cookies(name=name, domain=domain)
                return "Cookies geloescht." if ok else "Fehler beim Loeschen."

            elif action == "wait_for":
                selector = kwargs.get("selector", "")
                if not selector:
                    return "Fehler: 'selector' ist erforderlich."
                timeout = int(kwargs.get("timeout", 10))
                found = await cdp.wait_for_selector(selector, timeout=timeout)
                return f"Element '{selector}' gefunden." if found else f"Element '{selector}' nicht gefunden (Timeout {timeout}s)."

            elif action == "get_links":
                filter_text = kwargs.get("filter")
                limit = int(kwargs.get("limit", 50))
                links = await cdp.get_links(filter_text=filter_text, limit=limit)
                if not links:
                    return "Keine Links gefunden."
                lines = [f"{len(links)} Links:"]
                for i, l in enumerate(links[:50]):
                    text = l.get("text", "").strip() or "(kein Text)"
                    lines.append(f"  {i+1}. {text} → {l.get('href', '')}")
                return "\n".join(lines)

            elif action == "list_tabs":
                tabs = await cdp.list_tabs()
                if not tabs:
                    return "Keine Tabs gefunden."
                lines = [f"{len(tabs)} Tabs:"]
                for i, t in enumerate(tabs):
                    lines.append(f"  {i+1}. {t.get('title', '?')} – {t.get('url', '')}")
                return "\n".join(lines)

            elif action == "navigate":
                url = kwargs.get("url", "")
                if not url:
                    return "Fehler: 'url' ist erforderlich."
                await cdp.navigate(url)
                return f"Navigation zu: {url}"

            else:
                return f"Unbekannte CDP-Aktion: {action}. Verfuegbar: get_page_content, get_page_info, get_element, get_elements, click_element, fill_field, execute_js, get_cookies, set_cookie, delete_cookies, wait_for, get_links, list_tabs, navigate"

        except CDPConnectionError as e:
            return f"CDP-Fehler: Chrome nicht erreichbar. Bitte zuerst den Browser oeffnen (browser_control action='open'). Details: {e}"
        except CDPTimeoutError as e:
            return f"CDP-Fehler: Timeout – {e}"
        except CDPError as e:
            return f"CDP-Fehler: {e}"
        except Exception as e:
            return f"Unerwarteter CDP-Fehler: {e}"


def get_tools():
    """Gibt die Tools dieses Skills zurueck."""
    return [BrowserControlTool(), BrowserCDPTool()]
