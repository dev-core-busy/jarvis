#!/usr/bin/env python3
"""Regressionstest: `GET /api/skills/{name}/config` ist Administratoren vorbehalten.

Bis 2026-08-02 hing der Endpunkt an ``require_auth`` – jeder angemeldete
Benutzer konnte damit die Zugangsdaten SAEMTLICHER Skills im Klartext lesen
(HANA-/RFC-Kennwort und Bearer-Token, Jira-/Confluence-Token, IBS-API-Key,
Google-Client-Secret). Die Antwort ist die rohe Skill-Config, es gibt keine
Feld-Filterung.

Geprueft wird deshalb zweierlei:
  1. der Endpunkt selbst haengt an ``require_local_auth``
  2. es kommt kein Aufrufer hinzu, der NICHT auf der Einstellungsseite sitzt –
     genau das waere der Grund, aus dem jemand die Schranke wieder loesen will

Laeuft ohne fastapi:  python3 tests/test_skill_config_rights.py
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_ok = _fail = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  ✓ {name}")
    else:
        _fail += 1
        print(f"  ✗ {name}" + (f"  → {detail}" if detail else ""))


src = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")

print("── Endpunkt-Rechte ──")


def dependency_of(decorator: str) -> str:
    """Liest die Signatur-Zeile(n) der Funktion direkt hinter dem Dekorator."""
    teil = src.split(decorator, 1)[1]
    kopf = teil.split("):", 1)[0]      # bis zum Ende der Parameterliste
    return " ".join(kopf.split())


get_sig = dependency_of('@app.get("/api/skills/{name}/config")')
post_sig = dependency_of('@app.post("/api/skills/{name}/config")')

check("GET verlangt require_local_auth", "require_local_auth" in get_sig, get_sig)
check("GET verlangt NICHT mehr nur require_auth",
      "Depends(require_auth)" not in get_sig, get_sig)
check("POST bleibt require_local_auth", "require_local_auth" in post_sig, post_sig)

# Das oeffentliche Branding darf NICHT mitgesperrt werden: es wird schon auf der
# Loginseite gebraucht, also bevor irgendjemand angemeldet ist.
brand = dependency_of('@app.get("/api/branding")')
check("GET /api/branding bleibt ohne Anmeldung erreichbar",
      "Depends(" not in brand, brand)

print("\n── Aufrufer sitzen alle auf der Einstellungsseite ──")

# Welche JS-Dateien laedt eine Seite? settings.html ist die Admin-Flaeche.
frontend = ROOT / "frontend"
settings_html = (frontend / "settings.html").read_text(encoding="utf-8")
settings_js = set(re.findall(r'/static/js/([A-Za-z0-9_.-]+\.js)', settings_html))
# app.js verdrahtet die Reiter und wird nur von settings.html geladen.
check("settings.html laedt app.js", "app.js" in settings_js)

PAT = re.compile(r"/api/skills/[^'\"]*?/config|/api/skills/'\s*\+|/api/skills/\"\s*\+")
aufrufer = set()
for f in sorted((frontend / "js").glob("*.js")):
    txt = f.read_text(encoding="utf-8")
    for zeile in txt.splitlines():
        if "/api/skills/" in zeile and "/config" in zeile and "fetch(" in zeile:
            aufrufer.add(f.name)
check("Aufrufer gefunden", len(aufrufer) >= 5, str(sorted(aufrufer)))

# Jede aufrufende Datei muss von settings.html geladen werden. branding.js ist
# die Ausnahme, die man pruefen MUSS: sie liegt auf JEDER Seite – der
# Config-Aufruf steckt aber im Admin-Teil (brandingAdmin), der nur von app.js
# angestossen wird.
fremd = sorted(a for a in aufrufer if a not in settings_js)
check("kein Aufrufer ausserhalb der Einstellungsseite", not fremd, str(fremd))

if "branding.js" in aufrufer:
    bj = (frontend / "js" / "branding.js").read_text(encoding="utf-8")
    check("branding.js: Config-Aufruf liegt im Admin-Teil (brandingAdmin)",
          "window.brandingAdmin" in bj
          and bj.index("var BrandingAdmin") < bj.index("/api/skills/branding/config"))
    appjs = (frontend / "js" / "app.js").read_text(encoding="utf-8")
    check("brandingAdmin wird nur aus app.js gestartet",
          "brandingAdmin.init()" in appjs)
    andere = [f.name for f in (frontend / "js").glob("*.js")
              if f.name not in ("branding.js", "app.js")
              and "brandingAdmin" in f.read_text(encoding="utf-8")]
    check("kein weiterer Starter fuer brandingAdmin", not andere, str(andere))

# Seiten ausserhalb der Einstellungen duerfen den Endpunkt nicht direkt rufen.
inline = []
for html in sorted(frontend.glob("*.html")):
    if html.name == "settings.html":
        continue
    t = html.read_text(encoding="utf-8")
    if "/api/skills/" in t and "/config" in t:
        inline.append(html.name)
check("keine andere Seite ruft den Endpunkt im Markup", not inline, str(inline))

print(f"\n{'═' * 46}\nErgebnis: {_ok}/{_ok + _fail} bestanden")
sys.exit(0 if _fail == 0 else 1)
