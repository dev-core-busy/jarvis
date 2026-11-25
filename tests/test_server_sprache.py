#!/usr/bin/env python3
"""Waechter: Servertexte in der Sprache der Oberflaeche (backend/sprache.py).

Gemeldet 2026-11-24: bei FR kamen Fehler und Hinweise des Servers deutsch.
Seitdem legt i18n.js die Sprache als Cookie ``jarvis_lang`` ab, die
Middleware in main.py setzt sie je Anfrage und uebersetzt die Textfelder der
JSON-Antwort aus ``backend/server_texte.json``.

Die Zusagen:
  1. Sprache der Anfrage: ``?lang=`` > Cookie > de; Unbekanntes -> de.
  2. Uebersetzung: feste Saetze und Saetze mit Werten (Muster), nur die
     Textfelder der obersten Ebene, Unbekanntes und Deutsch bleiben unberuehrt,
     zu grosse Antworten und Nicht-Objekte werden nicht angefasst.
  3. Die ECHTE Middleware aus main.py (am Syntaxbaum geschnitten) in einer
     FastAPI-App: Cookie fr -> franzoesisch, ohne Cookie -> deutsch, Status
     und Kopfzeilen bleiben, HTML bleibt unberuehrt, Content-Length stimmt.
  4. server_texte.json: jeder Eintrag hat de/en/fr, EN/FR benutzen nur
     Platzhalter, die DE hat, kein deutscher Satz doppelt.
  5. REGEL: jeder deutsche Antwortsatz in main.py (Felder error/detail/
     meldung/…, HTTPException(detail=…)) hat eine Uebersetzung. Geltungsbereich
     main.py – Saetze aus anderen Modulen sind (noch) nicht erfasst, und ein
     Satz, den die Muster-Erkennung nicht als deutsch erkennt, ebenfalls nicht.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
OK = FAIL = 0


def pruefe(bed, text):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + text)
    else:
        FAIL += 1
        print("  FAIL " + text)


def abbruch(text):
    print("ABBRUCH: " + text)
    sys.exit(2)


sys.path.insert(0, str(REPO / "tests" / "lib"))
from backend import sprache as S  # noqa: E402
from quell_ausschnitt import segment  # noqa: E402

FELDER = S.FELDER
DE = re.compile(r"[äöüÄÖÜß]|\b(nicht|kein|keine|keinen|bitte|nur|wurde|werden|ist|sind|der|die|das|und|oder|"
                r"fuer|für|mit|ohne|zuerst|fehlt|ungültig|ungueltig|unbekannt|fehlgeschlagen|gesperrt|"
                r"erlaubt|Zugriff|Konto|Datei|Ordner|Benutzer)\b", re.I)


def muster(js: ast.JoinedStr) -> str:
    teile, n = [], 0
    for v in js.values:
        if isinstance(v, ast.Constant):
            teile.append(str(v.value))
        else:
            n += 1
            teile.append("{w%d}" % n)
    return "".join(teile)


def antwortsaetze(pfad: Path) -> set:
    """(art, satz) aller deutsch aussehenden Saetze in Antwortfeldern."""
    baum = ast.parse(pfad.read_text(encoding="utf-8"))
    funde = set()

    def wert(v):
        if isinstance(v, ast.Constant) and isinstance(v.value, str):
            funde.add(("fest", v.value))
        elif isinstance(v, ast.JoinedStr):
            funde.add(("muster", muster(v)))
    for n in ast.walk(baum):
        if isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if isinstance(k, ast.Constant) and k.value in FELDER:
                    wert(v)
        if isinstance(n, ast.Call) and getattr(n.func, "id", getattr(n.func, "attr", "")) == "HTTPException":
            for k in n.keywords:
                if k.arg == "detail":
                    wert(k.value)
            if len(n.args) >= 2:
                wert(n.args[1])
    return {f for f in funde if DE.search(f[1]) and len(f[1]) >= 4}


class Anfrage:
    def __init__(self, q=None, c=None):
        self.query_params = q or {}
        self.cookies = c or {}


# ── 1. Sprache der Anfrage ───────────────────────────────────────────────────
print("[1] Sprache der Anfrage")
pruefe(S.aus_anfrage(Anfrage()) == "de", "ohne Angabe: de")
pruefe(S.aus_anfrage(Anfrage(c={"jarvis_lang": "fr"})) == "fr", "Cookie fr")
pruefe(S.aus_anfrage(Anfrage(q={"lang": "en"}, c={"jarvis_lang": "fr"})) == "en", "?lang= gewinnt gegen das Cookie")
pruefe(S.aus_anfrage(Anfrage(c={"jarvis_lang": "xx<script>"})) == "de", "unbekannter Wert -> de")

# ── 2. Uebersetzung ──────────────────────────────────────────────────────────
print("[2] Uebersetzung")
alle = S.texte()
if len(alle) < 300:
    abbruch("server_texte.json nicht geladen (%d Eintraege)" % len(alle))
pruefe(True, "Positivkontrolle: %d Saetze geladen" % len(alle))
pruefe(S.satz_uebersetzen("Nicht authentifiziert", "fr") == "Non authentifié", "fester Satz -> fr")
pruefe(S.satz_uebersetzen("Nicht authentifiziert", "en") == "Not authenticated", "fester Satz -> en")
pruefe(S.satz_uebersetzen("Nicht authentifiziert", "de") is None, "de: nichts zu tun")
pruefe(S.satz_uebersetzen("Ordner 'Handbuch' existiert bereits", "fr") == "Le dossier « Handbuch » existe déjà",
       "Satz mit Wert (Muster) -> fr, Wert bleibt")
pruefe(S.satz_uebersetzen("Nicht authentifiziert", "nl") not in (None, "Nicht authentifiziert",
       S.satz_uebersetzen("Nicht authentifiziert", "en")), "fester Satz -> nl (eigener Text, kein Rueckfall)")
pruefe(S.aus_anfrage(Anfrage(c={"jarvis_lang": "nl"})) == "nl", "Cookie nl")
pruefe(S.satz_uebersetzen("Satz, den es nicht gibt", "fr") is None, "unbekannter Satz bleibt unberuehrt")
roh = json.dumps({"ok": False, "detail": "Nicht authentifiziert", "liste": ["Nicht authentifiziert"],
                  "error": 5}).encode()
neu = json.loads(S.antwort_uebersetzen(roh, "fr"))
pruefe(neu["detail"] == "Non authentifié" and neu["liste"] == ["Nicht authentifiziert"] and neu["error"] == 5,
       "nur Textfelder der obersten Ebene, andere Werte unberuehrt")
pruefe(S.antwort_uebersetzen(b'["Nicht authentifiziert"]', "fr") is None, "Liste statt Objekt: unberuehrt")
gross = json.dumps({"detail": "Nicht authentifiziert", "x": "a" * (S.ANTWORT_MAX + 1)}).encode()
pruefe(S.antwort_uebersetzen(gross, "fr") is None, "zu grosse Antwort: unberuehrt")
pruefe(S.antwort_uebersetzen(b"kein json", "fr") is None, "kein JSON: unberuehrt")

# ── 3. Die echte Middleware ──────────────────────────────────────────────────
print("[3] Middleware aus main.py")
try:
    from fastapi import FastAPI, HTTPException, Request
    from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
    from fastapi.testclient import TestClient
except Exception as e:  # noqa: BLE001
    abbruch("fastapi/TestClient fehlt: %s" % e)
main_src = (REPO / "backend/main.py").read_text(encoding="utf-8")
fn = next((n for n in ast.walk(ast.parse(main_src)) if isinstance(n, ast.AsyncFunctionDef)
           and n.name == "_sprache_setzen"), None)
if fn is None:
    abbruch("_sprache_setzen nicht in main.py")
app = FastAPI()
# Namensraum wie in main.py (dort importiert): fehlt hier ein Name, den die
# Middleware braucht, faellt das als Absturz auf statt als stiller Fehler.
ns = {"app": app, "Request": Request, "Response": Response, "StreamingResponse": StreamingResponse,
      "_sprache": S}
quelle = segment(main_src, fn)
dek = "\n".join("@" + segment(main_src, d) for d in fn.decorator_list)
exec(compile(dek + "\n" + quelle, "main.py", "exec"), ns)


@app.get("/fehler")
def _fehler():
    raise HTTPException(status_code=403, detail="Nicht authentifiziert")


@app.get("/json")
def _json():
    return JSONResponse({"ok": False, "error": "Ordner 'X' existiert bereits", "n": 2}, status_code=409,
                        headers={"X-Probe": "1"})


@app.get("/html")
def _html():
    return HTMLResponse("<p>Nicht authentifiziert</p>")


@app.get("/strom")
def _strom():
    from fastapi.responses import StreamingResponse as _SR

    def _gen():
        yield b'{"detail": "Nicht authentifiziert", "x": "'
        for _ in range(40):
            yield b"a" * 10000
        yield b'"}'
    return _SR(_gen(), media_type="application/json")


@app.get("/sprache")
def _sprache():
    return {"sprache": S.aktuell()}


tc = TestClient(app)
r = tc.get("/fehler", cookies={"jarvis_lang": "fr"})
pruefe(r.status_code == 403 and r.json().get("detail") == "Non authentifié", "HTTPException + Cookie fr -> franzoesisch")
pruefe(int(r.headers.get("content-length", "0")) == len(r.content), "Content-Length passt zum neuen Inhalt")
r = tc.get("/fehler")
pruefe(r.json().get("detail") == "Nicht authentifiziert", "ohne Cookie: deutsch")
r = tc.get("/json", cookies={"jarvis_lang": "en"})
pruefe(r.status_code == 409 and r.json() == {"ok": False, "error": "Folder 'X' already exists", "n": 2}
       and r.headers.get("x-probe") == "1", "JSONResponse: Status, Werte und eigene Kopfzeile bleiben")
r = tc.get("/html", cookies={"jarvis_lang": "fr"})
pruefe("Nicht authentifiziert" in r.text, "HTML wird nicht angefasst")
r = tc.get("/strom", cookies={"jarvis_lang": "fr"})
pruefe(r.status_code == 200 and len(r.content) == len('{"detail": "Nicht authentifiziert", "x": ""}') + 400000
       and r.content.startswith(b'{"detail": "Nicht authentifiziert"'),
       "gestreamte grosse JSON-Antwort ohne Laenge: vollstaendig und unveraendert durchgereicht")
r = tc.get("/sprache", cookies={"jarvis_lang": "fr"})
pruefe(r.json().get("sprache") == "fr", "die Anfrage sieht die Sprache (ContextVar)")

# ── 4. Textdatei ─────────────────────────────────────────────────────────────
print("[4] server_texte.json")
schlecht, doppelt, gesehen = [], [], set()
for e in alle:
    de = e["de"]
    if de in gesehen:
        doppelt.append(de)
    gesehen.add(de)
    p = set(re.findall(r"\{w\d+\}", de))
    for sp in ("en", "fr", "nl"):
        t = e.get(sp) or ""
        if not t.strip() or not set(re.findall(r"\{w\d+\}", t)) <= p:
            schlecht.append("%s:%s" % (sp, de[:40]))
pruefe(not schlecht, "jeder Eintrag hat EN, FR und NL mit passenden Platzhaltern%s"
       % (" – " + ", ".join(schlecht[:5]) if schlecht else ""))
pruefe(not doppelt, "kein deutscher Satz doppelt%s" % (" – " + ", ".join(doppelt[:3]) if doppelt else ""))

# ── 5. Regel: jeder deutsche Antwortsatz in main.py ist uebersetzt ─────────
print("[5] Regel ueber main.py")
saetze = antwortsaetze(REPO / "backend/main.py")
pruefe(len(saetze) >= 300, "Positivkontrolle: Antwortsaetze in main.py gefunden (%d)" % len(saetze))
fehlt = sorted(s for _, s in saetze if s not in gesehen)
pruefe(not fehlt, "jeder deutsche Antwortsatz in main.py hat EN/FR/NL in server_texte.json%s"
       % ((" – %d fehlen, z.B. %r" % (len(fehlt), fehlt[:3])) if fehlt else ""))

print("\nERGEBNIS: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
