#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_h4_cookie.py und tests/test_bsi_h4_cookie_ui.js
(BSI H4: Sitzung im Cookie).

Jede Probe dreht EINEN Teil des Verfahrens zurueck (Python-Ersetzung ganzer
Zeilen), laesst den Waechter laufen und erwartet mindestens einen FAIL. Vorher
ein gruener Basislauf, danach Byte-Gleichheit aller Dateien per md5. Ohne
Bytecode – sonst laedt ein spaeterer Lauf ggf. die Sabotage aus einer .pyc.

Laufmarke: vor jeder Probe liegt die Sicherung auf Platte (im HOME, nicht in
/tmp). Wird der Lauf abgeschossen, nimmt der naechste Start den Rueckstand
zurueck, bevor er irgendetwas misst.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = ROOT / "tests" / "test_bsi_h4_cookie.py"
JS = ROOT / "tests" / "test_bsi_h4_cookie_ui.js"
SC = "backend/sitzung_cookie.py"
MAIN = "backend/main.py"
SJS = "frontend/js/sitzung.js"
WJS = "frontend/js/wissen.js"
MARKE = Path.home() / ".cache" / "jarvis_gegen" / "bsi_h4_cookie.json"

PROBEN = [
    ("Middleware laesst falsches Paar stehen", PY, SC,
     "        else:\n            del kopf[auth_i]\n",
     "        else:\n            pass\n"),
    ("CSRF-Bindung wird nicht geprueft", PY, SC,
     "    if hmac.compare_digest(erwartet.encode(\"utf-8\"), csrf.encode(\"utf-8\")):\n",
     "    if True:\n"),
    ("Cookie allein meldet an", PY, SC,
     "        if auth_i is None:\n            return await self.app(scope, receive, send)\n",
     "        if auth_i is None and cookie_aus_kopf(cookie_kopf):\n"
     "            auth_i = len(scope[\"headers\"])\n"
     "            auth_wert = \"Bearer \" + csrf_fuer(cookie_aus_kopf(cookie_kopf))\n"
     "            scope = dict(scope)\n"
     "            scope[\"headers\"] = list(scope[\"headers\"]) + [(b\"authorization\", auth_wert.encode())]\n"
     "        if auth_i is None:\n            return await self.app(scope, receive, send)\n"),
    ("Cookie traegt das Token roh (DEV-Befund: AD-Backslash)", PY, SC,
     "    response.set_cookie(COOKIE_NAME, wert_kodieren(token), max_age=max(int(max_age), 60), path=\"/\",\n",
     "    response.set_cookie(COOKIE_NAME, token, max_age=max(int(max_age), 60), path=\"/\",\n"),
    ("Lesen ohne Dekodierung", PY, SC,
     "            return wert_lesen(wert)\n",
     "            return wert.strip().strip('\"')\n"),
    ("WebSocket/Koerper lesen das Cookie roh", PY, MAIN,
     "        roh = _sitzung_cookie.wert_lesen(verbindung.cookies.get(_sitzung_cookie.COOKIE_NAME, \"\"))\n",
     "        roh = verbindung.cookies.get(_sitzung_cookie.COOKIE_NAME, \"\")\n"),
    ("Cookie ohne HttpOnly", PY, SC,
     "    response.set_cookie(COOKIE_NAME, wert_kodieren(token), max_age=max(int(max_age), 60), path=\"/\",\n"
     "                        secure=True, httponly=True, samesite=\"strict\")\n",
     "    response.set_cookie(COOKIE_NAME, wert_kodieren(token), max_age=max(int(max_age), 60), path=\"/\",\n"
     "                        secure=True, httponly=False, samesite=\"strict\")\n"),
    ("Cookie SameSite=Lax", PY, SC,
     "    response.set_cookie(COOKIE_NAME, wert_kodieren(token), max_age=max(int(max_age), 60), path=\"/\",\n"
     "                        secure=True, httponly=True, samesite=\"strict\")\n",
     "    response.set_cookie(COOKIE_NAME, wert_kodieren(token), max_age=max(int(max_age), 60), path=\"/\",\n"
     "                        secure=True, httponly=True, samesite=\"lax\")\n"),
    ("CSRF-Token traegt das Token", PY, SC,
     "    return PRAEFIX + mac\n",
     "    return PRAEFIX + token.replace(\":\", \".\")\n"),
    ("Anmelde-Kopf wirkungslos", PY, MAIN,
     "    cookie = (_sitzung_cookie.gewuenscht(request.headers)\n",
     "    cookie = (False\n"),
    ("Cookie auch ohne https", PY, MAIN,
     "    if not token or not cookie or not _sitzung_cookie.moeglich(request.url.scheme):\n",
     "    if not token or not cookie:\n"),
    ("echtes Token bleibt im Koerper", PY, MAIN,
     "    daten[\"token\"] = _sitzung_cookie.csrf_fuer(token)\n",
     "    daten[\"token\"] = token\n"),
    ("Anmeldung gibt das Token direkt aus", PY, MAIN,
     "    return _sitzung_antwort(request, {\"success\": True, \"token\": token, \"username\": username,\n"
     "                                      \"must_change_password\": must_change,\n",
     "    return JSONResponse({\"success\": True, \"token\": token, \"username\": username,\n"
     "                                      \"must_change_password\": must_change,\n"),
    ("Middleware nicht registriert", PY, MAIN,
     "app.add_middleware(_sitzung_cookie.SitzungCookieMiddleware)\n",
     "\n"),
    ("Chat-WebSocket loest nicht auf", PY, MAIN,
     "    token = _token_aufloesen(ws, _roh_token)\n",
     "    token = _roh_token\n"),
    ("Benutzer-Chat-WebSocket loest nicht auf", PY, MAIN,
     "        token_str = _token_aufloesen(ws, raw.get(\"token\", \"\"))\n",
     "        token_str = raw.get(\"token\", \"\")\n"),
    ("_token_aufloesen ohne Bindung", PY, MAIN,
     "    return _sitzung_cookie.aufloesen(wert, roh) or \"\"\n",
     "    return roh or \"\"\n"),
    ("verify-token loest nicht auf (Browser-Befund)", PY, MAIN,
     "    tok = _token_aufloesen(request, body.get(\"token\", \"\"))\n",
     "    tok = body.get(\"token\", \"\")\n"),
    ("Feedback-Koerper loest nicht auf", PY, MAIN,
     "        or _token_aufloesen(request, str(body.get(\"token\") or \"\"))\n",
     "        or str(body.get(\"token\") or \"\")\n"),
    ("Abmelden laesst das Cookie stehen", PY, MAIN,
     "        _sitzung_cookie.loeschen(resp)\n",
     "        pass\n"),
    ("Umstellung gibt das echte Token aus", PY, MAIN,
     "                         \"token\": _sitzung_cookie.csrf_fuer(token)})\n",
     "                         \"token\": token})\n"),    # ── Frontend (sitzung.js / Anmeldestellen) ──
    ("Rahmen wird nicht erkannt", JS, SJS,
     "            if (window.top !== window.self) return false;\n",
     ""),
    ("Cookie-Verfahren auch ueber http", JS, SJS,
     "            if (location.protocol !== 'https:') return false;\n",
     ""),
    ("Add-in-Seiten stellen um", JS, SJS,
     "    var ADDIN_PFADE = ['/addin/', '/excel-addin/', '/jira-addon', '/confluence-addon'];\n",
     "    var ADDIN_PFADE = [];\n"),
    ("fremdes echtes Token bleibt liegen", JS, SJS,
     "                    else localStorage.removeItem(TOKEN_SCHLUESSEL[j]);\n",
     ""),
    ("Antwort mit echtem Token wird abgelegt", JS, SJS,
     "            if (!d || !d.token || d.token.indexOf(':') >= 0) return;\n",
     "            if (!d || !d.token) return;\n"),
    ("Anmelde-Kopf ueberall", JS, SJS,
     "            if (cookieTauglich()) h['X-Jarvis-Sitzung'] = 'cookie';\n",
     "            h['X-Jarvis-Sitzung'] = 'cookie';\n"),
    ("Umstellung laeuft nie", JS, SJS,
     # seit 2026-10-13 folgt der Maskenschutz – Aufruf statt Dateiende
     "\n    umstellen();\n",
     "\n"),
    ("eine Anmeldestelle ohne Anmelde-Kopf", JS, WJS,
     "headers: window.JarvisSitzung.anmeldeKopf({ 'Content-Type': 'application/json' }), body: JSON.stringify(payload) })",
     "headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })"),
]

DATEIEN = sorted({p[2] for p in PROBEN})


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf(w: Path) -> tuple[int, int]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    cmd = ["node", str(w)] if w.suffix == ".js" else [sys.executable, str(w)]
    r = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=300, cwd=str(ROOT), env=env)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(2)), r.returncode


def rueckstand_zuruecknehmen() -> None:
    if not MARKE.exists():
        return
    alt = json.loads(MARKE.read_text(encoding="utf-8"))
    for d, inhalt in alt.items():
        (ROOT / d).write_text(inhalt, encoding="utf-8")
    MARKE.unlink()
    print("Rueckstand eines abgebrochenen Laufs zurueckgenommen: %s" % sorted(alt))


def main() -> int:
    if {p[2] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    rueckstand_zuruecknehmen()
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    for w in (PY, JS):
        fails, rc = lauf(w)
        if fails != 0:
            print("ABBRUCH: Basislauf %s nicht gruen (FAIL=%s, rc=%s)" % (w.name, fails, rc))
            return 2
    print("Basislaeufe gruen.\n")

    MARKE.parent.mkdir(parents=True, exist_ok=True)
    MARKE.write_text(json.dumps({d: b.decode("utf-8") for d, b in sicherung.items()}),
                     encoding="utf-8")
    beissen = 0
    try:
        for name, waechter, datei, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu), encoding="utf-8")
            try:
                fails, rc = lauf(waechter)
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-50s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-50s Waechter konnte nicht laufen (rc=%s)" % (name, rc))
            else:
                print("  ZAHN %-50s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)
        if {d: md5(d) for d in DATEIEN} == vorher and MARKE.exists():
            MARKE.unlink()

    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("\nABBRUCH: Dateien nach der Probe nicht byte-gleich: %s"
              % [d for d in DATEIEN if nachher[d] != vorher[d]])
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)"
          % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
