# Anleitung: Browser- und Desktop-Steuerung

Keywords: öffne die seite, internetseite aufrufen, webseite öffnen, ibsv3.de, google, url, chrome, browser, tab, navigation, scrollen, zoom, fenster, clipboard, zwischenablage, drag, drop, seiteninhalt, formular, cookies, javascript, dom, element, link, selector

## Browser öffnen und Webseiten aufrufen

Zum Öffnen einer Webseite gibt es zwei Möglichkeiten:

### Option 1: `desktop_control` (einfach, schnell)
```json
{
  "action": "open_app",
  "text": "chrome https://ibsv3.de"
}
```

### Option 2: `browser_control` (empfohlen für erweiterte Steuerung)
```json
{
  "action": "open",
  "url": "https://ibsv3.de"
}
```

## Browser-Navigation (`browser_control` Tool)

| Aktion | Beschreibung | Beispiel |
|--------|-------------|----------|
| `open` | Browser öffnen (optional mit URL) | `{"action": "open", "url": "https://google.de"}` |
| `close` | Browser komplett schließen | `{"action": "close"}` |
| `navigate` | Zu URL im aktuellen Tab | `{"action": "navigate", "url": "https://google.de"}` |
| `back` | Zurück-Navigation | `{"action": "back"}` |
| `forward` | Vorwärts-Navigation | `{"action": "forward"}` |
| `refresh` | Seite neu laden | `{"action": "refresh"}` |

## Tab-Verwaltung (`browser_control` Tool)

| Aktion | Beschreibung | Beispiel |
|--------|-------------|----------|
| `new_tab` | Neuen Tab öffnen | `{"action": "new_tab", "url": "https://google.de"}` |
| `close_tab` | Aktuellen Tab schließen | `{"action": "close_tab"}` |
| `next_tab` | Nächster Tab | `{"action": "next_tab"}` |
| `prev_tab` | Vorheriger Tab | `{"action": "prev_tab"}` |
| `switch_tab` | Zu Tab Nr. wechseln (1-9) | `{"action": "switch_tab", "tab_number": 3}` |

## Suche und Zoom (`browser_control` Tool)

| Aktion | Beschreibung | Beispiel |
|--------|-------------|----------|
| `find_text` | Text auf Seite suchen | `{"action": "find_text", "text": "Suchbegriff"}` |
| `zoom_in` | Hineinzoomen | `{"action": "zoom_in"}` |
| `zoom_out` | Herauszoomen | `{"action": "zoom_out"}` |
| `zoom_reset` | Zoom zurücksetzen | `{"action": "zoom_reset"}` |
| `scroll_page` | Seite scrollen | `{"action": "scroll_page", "direction": "down", "amount": 3}` |
| `fullscreen` | Vollbild umschalten | `{"action": "fullscreen"}` |
| `get_url` | Aktuelle URL auslesen | `{"action": "get_url"}` |

## Seiteninhalt lesen und DOM-Zugriff (`browser_cdp` Tool)

WICHTIG: Der Browser muss vorher mit browser_control 'open' geöffnet sein!

### Seiten-Informationen
| Aktion | Beschreibung | Beispiel |
|--------|-------------|----------|
| `get_page_content` | Seitentext oder HTML | `{"action": "get_page_content"}` oder `{"action": "get_page_content", "format": "html"}` |
| `get_page_info` | Titel, URL, Ladestatus | `{"action": "get_page_info"}` |
| `get_links` | Alle Links auflisten | `{"action": "get_links"}` oder `{"action": "get_links", "filter": "login"}` |
| `list_tabs` | Offene Tabs anzeigen | `{"action": "list_tabs"}` |

### Elemente finden und interagieren
| Aktion | Beschreibung | Beispiel |
|--------|-------------|----------|
| `get_element` | Element per CSS-Selector | `{"action": "get_element", "selector": "#login-btn"}` |
| `get_elements` | Mehrere Elemente | `{"action": "get_elements", "selector": "a.nav-link", "limit": 10}` |
| `click_element` | Element klicken | `{"action": "click_element", "selector": "button[type=submit]"}` |
| `fill_field` | Formularfeld füllen | `{"action": "fill_field", "selector": "input[name=email]", "value": "test@test.de"}` |
| `wait_for` | Auf Element warten | `{"action": "wait_for", "selector": ".result", "timeout": 10}` |
| `navigate` | Zu URL navigieren | `{"action": "navigate", "url": "https://example.com"}` |

### JavaScript und Cookies
| Aktion | Beschreibung | Beispiel |
|--------|-------------|----------|
| `execute_js` | JavaScript ausführen | `{"action": "execute_js", "code": "document.title"}` |
| `get_cookies` | Cookies lesen | `{"action": "get_cookies"}` oder `{"action": "get_cookies", "domain": "google.de"}` |
| `set_cookie` | Cookie setzen | `{"action": "set_cookie", "name": "test", "value": "123", "domain": "example.com"}` |
| `delete_cookies` | Cookies löschen | `{"action": "delete_cookies", "domain": "example.com"}` |

### Typischer Workflow mit CDP
1. Browser öffnen: `browser_control` → `{"action": "open", "url": "https://example.com"}`
2. Seiteninhalt lesen: `browser_cdp` → `{"action": "get_page_content"}`
3. Element finden: `browser_cdp` → `{"action": "get_element", "selector": "input[name=q]"}`
4. Formular füllen: `browser_cdp` → `{"action": "fill_field", "selector": "input[name=q]", "value": "Suchbegriff"}`
5. Button klicken: `browser_cdp` → `{"action": "click_element", "selector": "button[type=submit]"}`
6. Auf Ergebnis warten: `browser_cdp` → `{"action": "wait_for", "selector": ".results"}`
7. Ergebnis lesen: `browser_cdp` → `{"action": "get_page_content"}`

## Desktop-Steuerung (`desktop_control` Tool)

### Maus-Aktionen
| Aktion | Beschreibung |
|--------|-------------|
| `click` | Linksklick an (x, y) |
| `double_click` | Doppelklick an (x, y) |
| `right_click` | Rechtsklick an (x, y) |
| `middle_click` | Mittelklick an (x, y) |
| `triple_click` | Dreifachklick an (x, y) – z.B. Zeile markieren |
| `move_mouse` | Maus zu (x, y) bewegen |
| `scroll` | Scrollen: `{"action": "scroll", "direction": "down", "amount": 5}` |
| `drag_and_drop` | Drag & Drop: `{"action": "drag_and_drop", "x": 100, "y": 100, "x2": 300, "y2": 300}` |

### Fenster-Management
| Aktion | Beschreibung |
|--------|-------------|
| `focus_window` | Fenster fokussieren (per `text` oder `window_id`) |
| `close_window` | Aktives Fenster schließen (oder per `window_id`) |
| `minimize_window` | Fenster minimieren |
| `maximize_window` | Fenster maximieren |
| `resize_window` | Fenstergröße: `{"action": "resize_window", "width": 1024, "height": 768}` |
| `move_window` | Fenster verschieben: `{"action": "move_window", "x": 0, "y": 0}` |
| `get_active_window` | Info über aktives Fenster |
| `list_windows` | Alle offenen Fenster auflisten |

### Zwischenablage
| Aktion | Beschreibung |
|--------|-------------|
| `clipboard_get` | Zwischenablage lesen |
| `clipboard_set` | Text in Zwischenablage: `{"action": "clipboard_set", "text": "Inhalt"}` |

## Wichtige Regeln

1. **CDP fuer Inhalte, xdotool fuer Navigation:** Wenn du Seiteninhalt lesen, Formulare ausfüllen oder JavaScript ausführen willst → `browser_cdp`. Wenn du den Browser öffnen, Tabs wechseln oder scrollen willst → `browser_control`.

2. **Screenshots bei visuellen Aktionen!** Wenn du auf der Webseite etwas per Koordinaten anklicken sollst (Buttons, Links, Cookies), MUSST DU ZUERST `screenshot` aufrufen. Rate niemals Koordinaten blind!

3. **URL-Format:** URLs immer vollständig mit `https://` angeben.

4. **CDP braucht offenen Browser:** Bevor du `browser_cdp` nutzt, muss Chrome mit `browser_control action=open` gestartet sein.
