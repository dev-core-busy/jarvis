#!/usr/bin/env python3
"""Live auf DEV: Spracheingabe ueber ``POST /api/stt`` mit dem lokalen Whisper.

Laeuft AUF dem Server (wie die uebrigen live_*_dev.py) gegen den echten
HTTPS-Endpunkt des laufenden Dienstes. Das Testmaterial baut der ERZEUGER, nicht
der Test: gesprochener Satz aus ``/api/tts``, dann mit ffmpeg in genau das
Format gebracht, das Chrome/Edge per MediaRecorder liefern (WebM/Opus, mono).

Veraendert NICHTS am Serverzustand.

Aufruf (als Dienstbenutzer, ohne Bytecode):
    cd /opt/jarvis && runuser -u jarvis -- env PYTHONDONTWRITEBYTECODE=1 \
        HOME=/home/jarvis venv/bin/python tests/live_stt_dev.py

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import json
import os
import ssl
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import ziele  # noqa: E402  (Testkonto aus .env, nie aus dem Repo)

BASIS = "https://127.0.0.1"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
SATZ = "Wie wird das Wetter morgen in Berlin?"
WIEDERHOLUNGEN = 2
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s%s" % (label, (" – %s" % detail) if detail else ""))


def ruf(pfad, token=None, daten=None, typ=None, methode=None):
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode or ("POST" if daten is not None else "GET"))
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if typ:
        r.add_header("Content-Type", typ)
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=300) as a:
            roh = a.read()
            return a.status, roh, a.headers.get("content-type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers.get("content-type", "")


def js(roh):
    try:
        return json.loads(roh.decode() or "{}")
    except Exception:  # noqa: BLE001
        return {}


def nach_webm(eingabe: bytes, arbeitsdir: str, ffmpeg_eingabe=None) -> bytes:
    """Wie Chrome: WebM-Container, Opus, mono, 48 kHz."""
    ziel = os.path.join(arbeitsdir, "aufnahme.webm")
    if ffmpeg_eingabe is None:
        quelle = os.path.join(arbeitsdir, "quelle.mp3")
        with open(quelle, "wb") as f:
            f.write(eingabe)
        ffmpeg_eingabe = ["-i", quelle]
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *ffmpeg_eingabe,
                    "-ac", "1", "-ar", "48000", "-c:a", "libopus", ziel],
                   check=True, timeout=60)
    with open(ziel, "rb") as f:
        return f.read()


from backend import main as M  # noqa: E402

BENUTZER = ziele.wert("JARVIS_DEV_TESTUSER")
tok = M.generate_token(BENUTZER)

print("Live DEV: Spracheingabe ueber /api/stt")
st, _r, _t = ruf("/api/me", tok)
if st != 200:
    print("NICHT PRUEFBAR: /api/me -> %s (Testkonto %s nicht anmeldbar?)" % (st, BENUTZER))
    sys.exit(2)
check(True, "(Positivkontrolle) Testkonto angemeldet")

st, mp3, typ = ruf("/api/tts", tok, json.dumps({"text": SATZ}).encode(), "application/json")
if st != 200 or not typ.startswith("audio/") or len(mp3) < 2000:
    print("NICHT PRUEFBAR: /api/tts lieferte kein Audio (%s, %s, %d B)" % (st, typ, len(mp3)))
    sys.exit(2)

with tempfile.TemporaryDirectory() as d:
    sprache = nach_webm(mp3, d)
    stille = nach_webm(b"", d, ["-f", "lavfi", "-t", "2", "-i", "anullsrc=r=48000:cl=mono"])
check(sprache[:4] == b"\x1aE\xdf\xa3", "(Positivkontrolle) Testmaterial ist WebM (%d B)" % len(sprache))

# ── Regelfall, wiederholt (eine Modellantwort ist erst nach Wiederholung eine Messung)
for i in range(WIEDERHOLUNGEN):
    st, roh, _t = ruf("/api/stt?lang=de", tok, sprache, "audio/webm")
    text = str(js(roh).get("text", ""))
    check(st == 200, "Lauf %d: 200" % (i + 1), "%s %s" % (st, roh[:200]))
    klein = text.lower()
    check("wetter" in klein and "berlin" in klein,
          "Lauf %d: Satz erkannt" % (i + 1), repr(text))

# ── Stille ──────────────────────────────────────────────────────────────────
st, roh, _t = ruf("/api/stt?lang=de", tok, stille, "audio/webm")
check(st == 200 and js(roh).get("text") == "",
      "reine Stille -> leerer Text (kein erfundener Satz, kein Klammertext)", "%s %r" % (st, roh[:200]))

# ── Schranken ───────────────────────────────────────────────────────────────
st, _r, _t = ruf("/api/stt", None, sprache, "audio/webm")
check(st == 401, "ohne Anmeldung -> 401", str(st))
st, _r, _t = ruf("/api/stt", tok, b"", "audio/webm", "POST")
check(st == 400, "leere Aufnahme -> 400", str(st))

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
