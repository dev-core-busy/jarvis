#!/usr/bin/env python3
"""BSI H4 – Content-Security-Policy: Richtlinie, Modus, Meldungen, Einbindung.

  [A] backend/csp.py (echt importiert, ohne backend.config – Einstellungen
      ueber eine Attrappe mit der Signatur von config.get_setting):
      Richtlinie ohne 'unsafe-inline'/'unsafe-eval' in script-src, Modi,
      Kopfzeilen-Namen, Add-in-Ausnahme, noVNC-Ausnahme, Host-Pruefung.
  [B] Meldungen: beide Berichtsformate, Query/Token entfernt, Tages-Dedupe,
      Lastbremse, Muell wirft nicht, Dateirecht 0640, Kuerzen nach Alter.
  [C] backend/main.py (Syntaxbaum): Middleware setzt die Kopfzeilen fuer HTML,
      Melde-Endpunkt ohne Anmeldung, Admin-Endpunkte mit require_local_auth,
      log_retention kennt die Datei, data/logs ist privat.

Exit 0 = gruen, 1 = Regelverstoss, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import json
import os
import stat
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OK = FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global OK, FAIL
    if cond:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("\n         " + detail) if detail else ""))


def abbruch(grund: str) -> None:
    print("ABBRUCH (Exit 2): " + grund)
    sys.exit(2)


try:
    from backend import csp
except Exception as e:  # noqa: BLE001
    abbruch("backend.csp nicht importierbar: %s" % e)

if "backend.config" in sys.modules:
    abbruch("backend.csp hat backend.config importiert (schreibt die Live-settings.json)")

EINST: dict = {}


def get_setting(key, default=None):           # Signatur wie config.get_setting
    return EINST.get(key, default)


csp.einstellungen_quelle(get_setting)


def direktiven(r: str) -> dict:
    d = {}
    for teil in r.split(";"):
        w = teil.strip().split()
        if w:
            d[w[0]] = w[1:]
    return d


# ─── [A] Richtlinie und Modus ────────────────────────────────────────────────
print("[A] Richtlinie und Modus")
r = csp.richtlinie("/chat", "jarvis.beispiel.de")
d = direktiven(r)
check("Positivkontrolle: Richtlinie hat script-src und default-src",
      "script-src" in d and "default-src" in d, r)
if "script-src" not in d:
    abbruch("Richtlinie nicht lesbar")
check("script-src ohne 'unsafe-inline'", "'unsafe-inline'" not in d["script-src"], str(d["script-src"]))
check("script-src ohne 'unsafe-eval'", "'unsafe-eval'" not in d["script-src"], str(d["script-src"]))
check("script-src ohne Platzhalter/Schema-Quellen (*, https:, data:, blob:)",
      not any(q in ("*", "https:", "http:", "data:", "blob:") for q in d["script-src"]),
      str(d["script-src"]))
check("script-src auf normalen Seiten nur 'self'", d["script-src"] == ["'self'"], str(d["script-src"]))
check("object-src 'none'", d.get("object-src") == ["'none'"])
check("base-uri 'self'", d.get("base-uri") == ["'self'"])
check("form-action 'self'", d.get("form-action") == ["'self'"])
check("default-src 'self'", d.get("default-src") == ["'self'"])
check("report-uri zeigt auf den Melde-Endpunkt", d.get("report-uri") == [csp.MELDE_PFAD])
check("connect-src erlaubt den eigenen WebSocket", "wss://jarvis.beispiel.de" in d.get("connect-src", []))

da = direktiven(csp.richtlinie("/addin/taskpane.html", ""))
check("Add-in: office.js zugelassen", "https://appsforoffice.microsoft.com" in da["script-src"])
check("Add-in: trotzdem kein 'unsafe-inline'", "'unsafe-inline'" not in da["script-src"])
dx = direktiven(csp.richtlinie("/excel-addin/taskpane.html", ""))
check("Excel-Add-in: office.js zugelassen", "https://appsforoffice.microsoft.com" in dx["script-src"])
check("Add-in: Office-Telemetrie-Rahmen zugelassen",
      "https://telemetryservice.firstpartyapps.oaspapps.com" in da.get("frame-src", []))
check("normale Seite: kein Office-Rahmen",
      not any("oaspapps" in q for q in d.get("frame-src", [])), str(d.get("frame-src")))
check("normale Seite: office.js NICHT zugelassen",
      "https://appsforoffice.microsoft.com" not in d["script-src"])

boese = "x.de; script-src * 'unsafe-inline'"
db = direktiven(csp.richtlinie("/chat", boese))
check("Host mit Fremd-Direktive wird nicht eingesetzt",
      "'unsafe-inline'" not in db["script-src"] and "*" not in db.get("connect-src", []),
      csp.richtlinie("/chat", boese))
check("IPv6-Host mit Port wird eingesetzt",
      "wss://[2001:db8::1]:8443" in direktiven(csp.richtlinie("/", "[2001:db8::1]:8443"))["connect-src"])

EINST.clear()
# Vorgabe seit 2026-10-13 "erzwingen" (H4: Inline-Stile als Restrisiko angenommen).
check("Vorgabe-Modus ist 'erzwingen'", csp.modus() == "erzwingen")
k = csp.kopfzeilen("/chat")
check("ohne Einstellung -> Content-Security-Policy (scharf)",
      list(k) == ["Content-Security-Policy"], str(list(k)))
EINST["csp_modus"] = "melden"
k = csp.kopfzeilen("/chat")
check("melden -> nur Report-Only-Kopfzeile",
      list(k) == ["Content-Security-Policy-Report-Only"], str(list(k)))
EINST["csp_modus"] = "erzwingen"
k = csp.kopfzeilen("/chat")
check("erzwingen -> Content-Security-Policy", list(k) == ["Content-Security-Policy"], str(list(k)))
EINST["csp_modus"] = "aus"
check("aus -> keine Kopfzeile", csp.kopfzeilen("/chat") == {})
for falsch in ("AUS ", "off", "", None, 0, "erzwinge"):
    EINST["csp_modus"] = falsch
    erwartet = "aus" if str(falsch or "").strip().lower() == "aus" else "erzwingen"
    check("Modus %r -> %s (Tippfehler schaltet nicht ab)" % (falsch, erwartet), csp.modus() == erwartet)
EINST["csp_modus"] = "erzwingen"
check("noVNC (Systempaket) ausgenommen", csp.kopfzeilen("/novnc/vnc.html") == {})
check("Seite neben noVNC nicht ausgenommen", csp.kopfzeilen("/novnc-x") != {})
EINST.clear()

# ─── [B] Meldungen ───────────────────────────────────────────────────────────
print("[B] Meldungen")
with tempfile.TemporaryDirectory() as tmp:
    csp._ordner = lambda: Path(tmp)            # Ablage umbiegen (Funktion statt Konstante)
    csp._gesehen.clear(); csp._gesehen_tag.clear(); csp._rate.clear()
    alt = {"csp-report": {"document-uri": "https://h/chat?token=GEHEIM123#x",
                          "violated-directive": "script-src-attr",
                          "effective-directive": "script-src-attr",
                          "blocked-uri": "inline", "source-file": "https://h/static/js/a.js?v=3",
                          "line-number": 42, "script-sample": "window.x()",
                          "disposition": "report"}}
    neu_api = [{"type": "csp-violation", "url": "https://h/wissen",
                "body": {"documentURL": "https://h/wissen?q=suche", "effectiveDirective": "script-src-elem",
                         "blockedURL": "https://cdn.fremd.example/x.js?k=1", "sourceFile": "",
                         "lineNumber": 0, "sample": "", "disposition": "enforce"}},
               {"type": "deprecation", "body": {}}]
    n1 = csp.melden(json.dumps(alt).encode(), "192.0.2.1", "Mozilla/5.0 Chrome/130")
    n2 = csp.melden(json.dumps(neu_api).encode(), "192.0.2.1", "Mozilla/5.0 Firefox/131")
    check("report-uri-Format: eine Zeile geschrieben", n1 == 1, str(n1))
    check("Reporting-API-Format: eine Zeile (fremder Typ ignoriert)", n2 == 1, str(n2))
    datei = Path(tmp) / "csp_berichte.jsonl"
    text = datei.read_text() if datei.exists() else ""
    zeilen = [json.loads(z) for z in text.splitlines() if z.strip()]
    check("Positivkontrolle: Datei hat 2 Zeilen", len(zeilen) == 2, text[:300])
    check("Token aus der Seiten-URL entfernt", "GEHEIM123" not in text)
    check("Query aus blockiertem Ziel entfernt", "k=1" not in text and "q=suche" not in text)
    check("keine IP in der Datei", "192.0.2.1" not in text)
    check("nur Browser-Familie statt User-Agent", "Mozilla" not in text
          and {z.get("browser") for z in zeilen} == {"Chrome", "Firefox"})
    check("Felder normalisiert (seite/direktive/blockiert)",
          zeilen and zeilen[0].get("seite") == "https://h/chat"
          and zeilen[0].get("direktive") == "script-src-attr"
          and zeilen[1].get("blockiert") == "https://cdn.fremd.example/x.js", str(zeilen))
    modus_datei = stat.S_IMODE(os.stat(datei).st_mode) if datei.exists() else -1
    check("Datei 0640", modus_datei == 0o640, oct(modus_datei))

    n3 = csp.melden(json.dumps(alt).encode(), "192.0.2.2", "")
    check("gleicher Verstoss am selben Tag: keine neue Zeile", n3 == 0)
    gelesen = csp.lesen(10)
    check("lesen: neueste zuerst, Zaehler laeuft weiter",
          len(gelesen) == 2 and gelesen[1].get("anzahl_seit_start") == 2, str(gelesen)[:300])

    for kaputt in (b"", b"{", b"[]", b"\xff\xfe", b'{"csp-report": "x"}', b"null", b"x" * 70000):
        try:
            csp.melden(kaputt, "192.0.2.3", "")
            ok = True
        except Exception:  # noqa: BLE001
            ok = False
        check("Muell %r wirft nicht" % kaputt[:12], ok)

    lang = dict(alt); lang["csp-report"] = dict(alt["csp-report"], **{"blocked-uri": "https://x/" + "a" * 5000})
    csp.melden(json.dumps(lang).encode(), "192.0.2.4", "")
    letzte = csp.lesen(1)[0]
    check("Feldlaenge begrenzt", len(letzte.get("blockiert", "")) <= csp.FELD_MAX)

    csp._rate.clear()
    geschrieben = 0
    for i in range(csp.RATE_JE_MINUTE + 25):
        b = {"csp-report": {"document-uri": "https://h/s%d" % i, "violated-directive": "x"}}
        geschrieben += csp.melden(json.dumps(b).encode(), "192.0.2.9", "")
    check("Lastbremse je IP greift (%d von %d)" % (geschrieben, csp.RATE_JE_MINUTE + 25),
          geschrieben == csp.RATE_JE_MINUTE)
    check("andere IP wird nicht mitgebremst",
          csp.melden(json.dumps({"csp-report": {"document-uri": "https://h/z", "violated-directive": "y"}}).encode(),
                     "192.0.2.10", "") == 1)

    # Kuerzen nach Alter: eine alte Zeile dazu, eine ohne Zeitstempel
    with datei.open("a") as f:
        f.write(json.dumps({"ts": 1000, "seite": "alt"}) + "\n")
        f.write(json.dumps({"seite": "ohne-ts"}) + "\n")
    vorher = len(datei.read_text().splitlines())
    weg = csp.kuerzen(time.time() - 86400)
    nachher = datei.read_text()
    check("kuerzen entfernt genau die alte Zeile", weg == 1 and len(nachher.splitlines()) == vorher - 1)
    check("Zeile ohne Zeitstempel bleibt", "ohne-ts" in nachher)
    check("nach kuerzen weiter 0640", stat.S_IMODE(os.stat(datei).st_mode) == 0o640)

    # ⚠ Code-Review 2026-10-07: der Pfad ist ohne Anmeldung erreichbar; die
    # Bremse je IP allein liess mit vielen Adressen beliebig viel auf die Platte.
    # Flut aus 400 Adressen mit je 20 verschiedenen Verstoessen (8000 Zeilen).
    def flut():
        csp._gesehen.clear(); csp._gesehen_tag.clear(); csp._rate.clear(); csp._tag_zeilen.clear()
        if datei.exists():
            datei.unlink()
        n = 0
        for ip in range(400):
            stapel = [{"csp-report": {"document-uri": "https://h/f%d_%d" % (ip, j),
                                      "violated-directive": "x"}} for j in range(20)]
            n += csp.melden(json.dumps(stapel).encode(), "198.51.100.%d" % ip, "")
        return n, len(datei.read_text().splitlines()) if datei.exists() else 0

    geschrieben, zeilen_n = flut()
    check("Positivkontrolle: die Flut schreibt ueberhaupt (%d)" % zeilen_n, zeilen_n > 0)
    check("⚠ Flut aus vielen Adressen: hoechstens TAG_MAX_ZEILEN am Tag (%d)" % zeilen_n,
          zeilen_n == geschrieben and zeilen_n == csp.TAG_MAX_ZEILEN, str(geschrieben))
    geheim_max_vorher = csp.GESEHEN_MAX
    csp.GESEHEN_MAX = 500              # kleiner als die Flut, sonst waere die Pruefung trivial
    flut()
    check("⚠ Zaehler-Speicher begrenzt (%d Schluessel bei 8000 verschiedenen)" % len(csp._gesehen),
          0 < len(csp._gesehen) <= csp.GESEHEN_MAX)
    csp.GESEHEN_MAX = geheim_max_vorher
    # Dateigroesse: volle Datei nimmt nichts mehr an
    csp._tag_zeilen.clear()
    with datei.open("a") as f:
        f.write("x" * csp.DATEI_MAX + "\n")
    groesse = datei.stat().st_size
    n_voll = csp.melden(json.dumps({"csp-report": {"document-uri": "https://h/voll",
                                                   "violated-directive": "z"}}).encode(), "192.0.2.77", "")
    check("⚠ Datei ab DATEI_MAX: nichts mehr angehaengt", datei.stat().st_size == groesse, str(n_voll))

# ─── [C] Einbindung (Syntaxbaum) ─────────────────────────────────────────────
print("[C] Einbindung in main.py / log_retention / sandbox")
MAIN = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))


def deko_name(dek) -> tuple[str, str]:
    """('get'|'post'|'middleware', erstes Argument als Quelltext)."""
    if isinstance(dek, ast.Call) and isinstance(dek.func, ast.Attribute) \
            and isinstance(dek.func.value, ast.Name) and dek.func.value.id == "app":
        arg = ast.unparse(dek.args[0]) if dek.args else ""
        return dek.func.attr, arg
    return "", ""


funktionen = [n for n in MAIN.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
mw = [f for f in funktionen if any(deko_name(d) == ("middleware", "'http'") for d in f.decorator_list)]
check("Positivkontrolle: Middlewares gefunden (>= 2)", len(mw) >= 2, str(len(mw)))
# Genau _csp.kopfzeilen – seit BSI H7 ruft eine zweite Middleware
# _sicherheits_kopf.kopfzeilen (gleicher Methodenname, anderes Modul).
csp_mw = [f for f in mw if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                               and n.func.attr == "kopfzeilen" and isinstance(n.func.value, ast.Name)
                               and n.func.value.id == "_csp" for n in ast.walk(f))]
check("eine Middleware ruft _csp.kopfzeilen", len(csp_mw) == 1)
if csp_mw:
    q = ast.unparse(csp_mw[0])
    # Die Bedingung, unter der die Schleife laeuft – nicht nur ein Vorkommen von "text/html"
    wenn = [n for n in ast.walk(csp_mw[0]) if isinstance(n, ast.If)
            and any("kopfzeilen" in ast.unparse(m) for m in n.body)]
    check("Middleware setzt die Kopfzeilen GENAU fuer text/html",
          len(wenn) == 1 and ast.unparse(wenn[0].test)
          == "response.headers.get('content-type', '').lower().startswith('text/html')",
          ast.unparse(wenn[0].test) if wenn else "kein if")
    check("Middleware setzt die Kopfzeilen in response.headers",
          any(isinstance(n, ast.Subscript) and isinstance(n.ctx, ast.Store)
              and "response.headers" in ast.unparse(n.value) for n in ast.walk(csp_mw[0])))
quelle = any(isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
             and ast.unparse(n.value.func).endswith("csp.einstellungen_quelle")
             and ast.unparse(n.value.args[0]) == "config.get_setting" for n in MAIN.body)
check("main reicht config.get_setting an csp durch", quelle)


def route(meth: str, pfad_src: str):
    return next((f for f in funktionen if any(deko_name(d) == (meth, pfad_src) for d in f.decorator_list)), None)


def deps(f) -> set:
    return {ast.unparse(d.args[0]) for d in ast.walk(f.args) if isinstance(d, ast.Call)
            and ast.unparse(d.func) == "Depends" and d.args}


melde = route("post", "_csp.MELDE_PFAD")
check("Melde-Endpunkt registriert", melde is not None)
if melde:
    check("Melde-Endpunkt ruft _csp.melden", "_csp.melden(" in ast.unparse(melde))
    check("Melde-Endpunkt antwortet 204", "status_code=204" in ast.unparse(melde))
for meth in ("get", "post"):
    f = route(meth, "'/api/security/csp'")
    check("%s /api/security/csp vorhanden" % meth.upper(), f is not None)
    if f:
        check("%s /api/security/csp nur Admin (require_local_auth)" % meth.upper(),
              deps(f) == {"require_local_auth"}, str(deps(f)))
setzen = route("post", "'/api/security/csp'")
if setzen:
    check("Setzen prueft gegen _csp.MODI", "_csp.MODI" in ast.unparse(setzen))

LR = (ROOT / "backend" / "log_retention.py").read_text(encoding="utf-8")
LRA = ast.parse(LR)
lauf = next((n for n in ast.walk(LRA) if isinstance(n, ast.For)
             and "_prune_cron_log" in ast.unparse(n.iter)), None)
check("Positivkontrolle: Aufbewahrungsschleife gefunden", lauf is not None)
check("log_retention kuerzt die CSP-Meldungen", lauf is not None and "_prune_csp_berichte" in ast.unparse(lauf.iter))
pr = next((n for n in LRA.body if isinstance(n, ast.FunctionDef) and n.name == "_prune_csp_berichte"), None)
check("_prune_csp_berichte ruft csp.kuerzen", pr is not None and "csp.kuerzen(" in ast.unparse(pr))

SB = ast.parse((ROOT / "backend" / "sandbox.py").read_text(encoding="utf-8"))
pd = next((n.value for n in SB.body if isinstance(n, ast.Assign)
           and any(getattr(t, "id", "") == "PRIVATE_DIRS" for t in n.targets)), None)
eintraege = {e.value for e in getattr(pd, "elts", []) if isinstance(e, ast.Constant)}
check("data/logs ist privates Verzeichnis (Ablage der Meldungen)", "data/logs" in eintraege)
CS = ast.parse((ROOT / "backend" / "csp.py").read_text(encoding="utf-8"))
ordner = next((n for n in CS.body if isinstance(n, ast.FunctionDef) and n.name == "_ordner"), None)
check("Ablage liegt unter data/logs",
      ordner is not None and "'data' / 'logs'" in ast.unparse(ordner), ast.unparse(ordner) if ordner else "")

print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
