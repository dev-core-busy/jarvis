"""WebDAV-Server fuer die Jarvis Knowledge Base.

Stellt Knowledge-Ordner per WebDAV ueber den bestehenden Port 443 bereit.
Nutzung: Windows/Mac/Linux Dateimanager koennen sich verbinden.
"""

import logging
import re
from pathlib import Path

from backend.config import config

_log = logging.getLogger("jarvis.webdav")

PROJECT_ROOT = Path(__file__).parent.parent


def _get_webdav_config() -> dict:
    """Liest WebDAV-Konfiguration aus settings.json."""
    try:
        states = config.get_skill_states()
        return states.get("knowledge", {}).get("config", {}).get("webdav", {})
    except Exception:
        return {}


def is_webdav_enabled() -> bool:
    return _get_webdav_config().get("enabled", False)


# ─── Styled Dir-Browser Wrapper ───────────────────────────────────────────────

_DIR_STYLE = """<!DOCTYPE html>
<html lang="de">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Jarvis WebDAV – {path}</title>
<style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{background:#0d1117;color:#c9d1d9;font-family:'Segoe UI',Inter,system-ui,sans-serif;padding:28px 32px;min-height:100vh}}
header{{display:flex;align-items:center;gap:12px;margin-bottom:20px;padding-bottom:16px;border-bottom:1px solid rgba(255,255,255,0.08)}}
.logo{{width:32px;height:32px;background:linear-gradient(135deg,#4f46e5,#7c3aed);border-radius:8px;display:flex;align-items:center;justify-content:center;font-weight:700;color:#fff;font-size:14px;flex-shrink:0}}
h1{{font-size:1.1rem;font-weight:600;color:#e2e8f0}}
h1 span{{color:#818cf8;font-family:monospace;font-weight:400}}
.meta{{font-size:0.78rem;color:#6e7681;margin-left:auto}}
.breadcrumb{{font-size:0.82rem;color:#8b949e;margin-bottom:14px}}
.breadcrumb a{{color:#818cf8;text-decoration:none}}
.breadcrumb a:hover{{color:#a5b4fc}}
table{{width:100%;border-collapse:collapse;background:rgba(255,255,255,0.02);border:1px solid rgba(255,255,255,0.07);border-radius:10px;overflow:hidden}}
thead tr{{background:rgba(79,70,229,0.12);border-bottom:1px solid rgba(255,255,255,0.08)}}
th{{padding:10px 16px;text-align:left;font-size:0.72rem;font-weight:600;color:#818cf8;letter-spacing:0.06em;text-transform:uppercase;white-space:nowrap}}
th:last-child{{text-align:right}}
tbody tr{{border-bottom:1px solid rgba(255,255,255,0.04);transition:background 0.12s}}
tbody tr:hover{{background:rgba(129,140,248,0.07)}}
tbody tr:last-child{{border-bottom:none}}
td{{padding:9px 16px;font-size:0.84rem;white-space:nowrap}}
td:last-child{{text-align:right;color:#6e7681}}
td:nth-child(2){{color:#6e7681;font-size:0.78rem}}
td:nth-child(3){{color:#6e7681;font-size:0.78rem;text-align:right}}
a{{color:#a5b4fc;text-decoration:none;display:flex;align-items:center;gap:7px}}
a:hover{{color:#c7d2fe}}
.icon{{font-size:1rem;width:20px;text-align:center;flex-shrink:0}}
.footer{{margin-top:20px;font-size:0.75rem;color:#30363d;text-align:right}}
</style>
</head>
<body>
<header>
  <div class="logo">J</div>
  <h1>Jarvis WebDAV &nbsp;<span>{path}</span></h1>
  <div class="meta">Benutzer: {user} &nbsp;·&nbsp; Lese-/Schreibzugriff</div>
</header>
{breadcrumb}
<table>
<thead><tr><th>Name</th><th>Typ</th><th>Größe</th><th>Geändert</th></tr></thead>
<tbody>
{rows}
</tbody>
</table>
<div class="footer">Jarvis Knowledge Base</div>
</body></html>"""


def _icon(is_dir: bool, name: str) -> str:
    if is_dir:
        return "📁"
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return {"pdf": "📄", "doc": "📝", "docx": "📝", "md": "📋",
            "xls": "📊", "xlsx": "📊", "txt": "📃", "png": "🖼️",
            "jpg": "🖼️", "jpeg": "🖼️", "zip": "🗜️", "url": "🔗"}.get(ext, "📄")


class _StyledBrowser:
    """WSGI-Middleware: ersetzt WsgiDAV-HTML durch gestylten Jarvis-Browser."""

    def __init__(self, app):
        self._app = app

    def __call__(self, environ, start_response):
        method = environ.get("REQUEST_METHOD", "")
        accept = environ.get("HTTP_ACCEPT", "")

        if method == "GET" and "text/html" in accept:
            cap = {"status": None, "headers": [], "body": []}

            def _cap(status, headers, exc_info=None):
                cap["status"] = status
                cap["headers"] = list(headers)

            it = self._app(environ, _cap)
            try:
                for chunk in it:
                    cap["body"].append(chunk)
            finally:
                if hasattr(it, "close"):
                    it.close()

            body = b"".join(cap["body"])

            if cap["status"] and cap["status"].startswith("200") and b"WsgiDAV" in body:
                new_body = self._restyle(body)
                hdrs = [(k, v) for k, v in cap["headers"]
                        if k.lower() not in ("content-length", "content-type")]
                hdrs += [("Content-Type", "text/html; charset=utf-8"),
                         ("Content-Length", str(len(new_body)))]
                start_response(cap["status"], hdrs)
                return [new_body]

            start_response(cap["status"], cap["headers"])
            return [body]

        return self._app(environ, start_response)

    def _restyle(self, body: bytes) -> bytes:
        html = body.decode("utf-8", errors="replace")

        # Pfad aus Titel
        m = re.search(r"Index of\s*(.*?)</(?:h1|title)>", html, re.IGNORECASE)
        path = (m.group(1).strip() if m else "/") or "/"

        # Auth-User
        m2 = re.search(r'Authenticated user:\s*"([^"]*)"', html)
        user = m2.group(1) if m2 else "jarvis"

        # Breadcrumb
        parts = [p for p in path.split("/") if p]
        crumb_html = '<div class="breadcrumb"><a href="/webdav/">/</a>'
        acc = "/webdav"
        for part in parts:
            acc += "/" + part
            crumb_html += f' / <a href="{acc}/">{part}</a>'
        crumb_html += "</div>"

        # Tabellenzeilen parsen
        rows = []
        # Eltern-Link
        if path.rstrip("/") not in ("", "/"):
            rows.append('<tr><td><a href="../"><span class="icon">⬆️</span> ..</a></td>'
                        '<td></td><td></td><td></td></tr>')

        for m in re.finditer(
            r'<a[^>]+href="([^"]*)"[^>]*>(.*?)</a>.*?'
            r'<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>\s*<td[^>]*>(.*?)</td>',
            html, re.DOTALL
        ):
            href, name_raw, typ, size, modified = (
                m.group(1), m.group(2), m.group(3), m.group(4), m.group(5)
            )
            name = re.sub(r"<[^>]+>", "", name_raw).strip()
            if not name or href.startswith("/:"):
                continue
            is_dir = "Directory" in typ or href.endswith("/")
            ico = _icon(is_dir, name)
            size_s = re.sub(r"<[^>]+>", "", size).strip() or "–"
            mod_s = re.sub(r"<[^>]+>", "", modified).strip()
            rows.append(
                f'<tr><td><a href="{href}"><span class="icon">{ico}</span>{name}</a></td>'
                f'<td>{"Ordner" if is_dir else typ.strip()}</td>'
                f'<td>{size_s}</td><td>{mod_s}</td></tr>'
            )

        rows_html = "\n".join(rows) if rows else '<tr><td colspan="4" style="padding:20px;text-align:center;color:#6e7681;">Leer</td></tr>'

        result = _DIR_STYLE.format(
            path=path, user=user,
            breadcrumb=crumb_html if parts else "",
            rows=rows_html
        )
        return result.encode("utf-8")


# ─── WebDAV App Factory ───────────────────────────────────────────────────────

def get_webdav_app():
    cfg = _get_webdav_config()
    if not cfg.get("enabled", False):
        return None

    try:
        from wsgidav.wsgidav_app import WsgiDAVApp
    except ImportError:
        _log.warning("wsgidav nicht installiert – WebDAV deaktiviert")
        return None

    # WebDAV zeigt nur den lokalen Knowledge-Ordner (data/knowledge).
    # SMB/NFS-Mounts sind read-only für die Indizierung und werden NICHT per WebDAV freigegeben.
    local_kb = PROJECT_ROOT / "data" / "knowledge"
    local_kb.mkdir(parents=True, exist_ok=True)

    provider_mapping = {"/": str(local_kb)}

    username = cfg.get("username", "jarvis")
    password = cfg.get("password", "jarvis")

    dav_config = {
        "provider_mapping": provider_mapping,
        "verbose": 0,
        "logging": {"enable": False},
        "http_authenticator": {
            "domain_controller": None,
            "accept_basic": True,
            "accept_digest": False,
            "default_to_digest": False,
        },
        "simple_dc": {
            "user_mapping": {"*": {username: {"password": password}}},
        },
        "dir_browser": {"enable": True},
    }

    try:
        dav_app = WsgiDAVApp(dav_config)
        styled_app = _StyledBrowser(dav_app)
        _log.info(f"WebDAV-Server konfiguriert: {list(provider_mapping.keys())}")
        return styled_app
    except Exception as e:
        _log.error(f"WebDAV-Initialisierung fehlgeschlagen: {e}")
        return None
