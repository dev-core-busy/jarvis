#!/usr/bin/env python3
"""Live auf DEV: Spracherkennung ueber den Fern-Dienst (Einstellung + /api/stt).

Laeuft AUF dem Server gegen den laufenden Dienst. Die Adresse des Fern-Dienstes
steht nicht im Repo – sie kommt als Umgebungsvariable ``STT_FERN_URL``; fehlt
sie, bricht die Probe mit Exit 2 ab.

Misst:
  - GET/POST /api/settings/stt (nur Admin), Erreichbarkeit in der Antwort,
    ungueltige Adresse -> 400
  - /api/stt mit gesprochenem Satz (Material aus /api/tts, als WebM/Opus wie
    Chrome) – und dass ihn WIRKLICH der Fern-Dienst erkannt hat (Journalzeile
    "Fern-Transkription OK" aus diesem Lauf)
  - unerreichbarer Dienst -> trotzdem erkannt (Ersatz: lokales Modell)
Stellt am Ende den VORGEFUNDENEN Zustand der Einstellung wieder her.

Aufruf (Token braucht den Hauptschluessel, daher ueber als_dienst.sh):
    cd /opt/jarvis && STT_FERN_URL=ws://<stt-host>:8090/ws/stt \\
        bash deploy/als_dienst.sh venv/bin/python tests/live_stt_fern_dev.py

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import json
import os
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")

BASIS = "https://127.0.0.1"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
SATZ = "Kannst du mir erklären, wie ich im Outlook eine Abwesenheitsnotiz einrichte?"
FERN = os.environ.get("STT_FERN_URL", "").strip()
_ok = _fail = 0

if not FERN:
    print("ABBRUCH (Exit 2): STT_FERN_URL nicht gesetzt")
    sys.exit(2)


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s%s" % (label, (" – %s" % detail) if detail else ""))


def ruf(pfad, token=None, daten=None, typ=None):
    r = urllib.request.Request(BASIS + pfad, data=daten, method="POST" if daten is not None else "GET")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if typ:
        r.add_header("Content-Type", typ)
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=300) as a:
            return a.status, a.read(), a.headers.get("content-type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("content-type", "")


def js(roh):
    try:
        return json.loads(roh.decode() or "{}")
    except Exception:  # noqa: BLE001
        return {}


def journal_seit(t0):
    erg = subprocess.run(["journalctl", "-u", "jarvis.service", "--no-pager", "-o", "cat",
                          "--since", "@%d" % int(t0)], capture_output=True, text=True, timeout=30)
    return erg.stdout


def setzen(tok, quelle, url):
    st, roh, _t = ruf("/api/settings/stt", tok, json.dumps({"quelle": quelle, "url": url}).encode(),
                      "application/json")
    return st, js(roh)


from backend import main as M  # noqa: E402

TOK = M.generate_token("jarvis")
print("Live DEV: Spracherkennung ueber den Fern-Dienst")
st, roh, _t = ruf("/api/settings/stt", TOK)
if st != 200:
    print("NICHT PRUEFBAR: GET /api/settings/stt -> %s %r" % (st, roh[:200]))
    sys.exit(2)
vorher = js(roh)
check(vorher.get("quelle") in ("lokal", "fern"), "(Positivkontrolle) Einstellung lesbar", vorher)

st, mp3, typ = ruf("/api/tts", TOK, json.dumps({"text": SATZ}).encode(), "application/json")
if st != 200 or not typ.startswith("audio/") or len(mp3) < 2000:
    print("NICHT PRUEFBAR: /api/tts lieferte kein Audio (%s, %s, %d B)" % (st, typ, len(mp3)))
    sys.exit(2)
with tempfile.TemporaryDirectory() as d:
    quelle = os.path.join(d, "q.mp3")
    ziel = os.path.join(d, "a.webm")
    with open(quelle, "wb") as f:
        f.write(mp3)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", quelle, "-ac", "1", "-ar", "48000",
                    "-c:a", "libopus", ziel], check=True, timeout=60)
    with open(ziel, "rb") as f:
        sprache = f.read()

try:
    # ── Einstellung ─────────────────────────────────────────────────────────
    st, d = setzen(TOK, "fern", "http://kein-ws.beispiel.de/x")
    check(st == 400, "ungueltige Adresse -> 400", st)
    st, d = setzen(TOK, "fern", FERN)
    check(st == 200 and d.get("quelle") == "fern", "fern gespeichert", (st, d))
    check(bool((d.get("erreichbar") or {}).get("ok")), "Antwort meldet: Dienst erreichbar", d.get("erreichbar"))
    st, roh, _t = ruf("/api/settings/stt", TOK)
    check(js(roh).get("quelle") == "fern" and js(roh).get("url") == FERN, "GET liefert den gespeicherten Stand")

    # ── Erkennung ueber den Fern-Dienst, wiederholt ─────────────────────────
    for i in range(2):
        t0 = time.time() - 1
        st, roh, _t = ruf("/api/stt?lang=de", TOK, sprache, "audio/webm")
        text = str(js(roh).get("text", ""))
        dauer = time.time() - t0
        klein = text.lower()
        check(st == 200 and "outlook" in klein and "abwesenheit" in klein,
              "Lauf %d: Satz erkannt (%.1f s)" % (i + 1, dauer), "%s %r" % (st, text))
        time.sleep(1)
        log = journal_seit(t0)
        check("Fern-Transkription OK" in log and "Ersatz: lokales Modell" not in log,
              "Lauf %d: erkannt hat der Fern-Dienst (Journal)" % (i + 1))

    # ── Ausfall: Ersatz durch das lokale Modell ─────────────────────────────
    st, d = setzen(TOK, "fern", "ws://127.0.0.1:1/ws/stt")
    check(st == 200 and not (d.get("erreichbar") or {}).get("ok"), "unerreichbare Adresse: Antwort meldet es", d)
    t0 = time.time() - 1
    st, roh, _t = ruf("/api/stt?lang=de", TOK, sprache, "audio/webm")
    check(st == 200 and "outlook" in str(js(roh).get("text", "")).lower(),
          "Dienst unerreichbar: trotzdem erkannt (lokal)", "%s %r" % (st, roh[:200]))
    time.sleep(1)
    check("Ersatz: lokales Modell" in journal_seit(t0), "der Ausfall steht im Journal")
finally:
    st, d = setzen(TOK, vorher.get("quelle") or "lokal", vorher.get("url") or "")
    st2, roh, _t = ruf("/api/settings/stt", TOK)
    nachher = js(roh)
    check(nachher.get("quelle") == vorher.get("quelle") and nachher.get("url") == vorher.get("url"),
          "vorgefundener Zustand wiederhergestellt", (vorher, nachher))

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
