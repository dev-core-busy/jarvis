#!/usr/bin/env python3
"""Live auf DEV: AI-Maus-Aktion „Anonymisieren" mit ECHTEM Presidio, YuNet und Modell.

Was ``test_anonymisieren.py`` nicht kann (dort ist der Hilfsprozess gestellt):
  A. die echte Kette im Dienstprozess: Hilfsprozess startet, Presidio findet die
     Namen, YuNet das Gesicht, nach dem Lauf liest die Texterkennung keinen
     Namen mehr; Zeiten fuer kalten und warmen Lauf,
  B. der Admin-Endpunkt nimmt ``aktion`` an, lehnt Unbekanntes ab,
  C. der Durchstich ueber ``/api/ai-mouse/analyze`` mit einem Benutzer, der die
     AI-Maus WIRKLICH benutzen darf (keine Freigabe wird umgestellt), und der
     Abruf des Ergebnisbildes mit seinem Token.

⚠ ZUSTAND: ``data/ai_mouse_fragen.json`` wird VOR dem Eingriff byte-genau
gesichert und am Ende zurueckgelegt (md5 geprueft) – C legt eine Vorgabe an
und kopiert sie in die Liste des Benutzers. Erzeugte Ergebnisbilder raeumt die
Probe selbst ab.

Das Testgesicht wird zur Laufzeit aus dem OpenCV-Beispielbestand geholt und
liegt nur im Wegwerfordner (nicht im Repo). Ohne Netz: Exit 2.

Aufruf AUF DEV (Token muessen im Dienst gelten, seit BSI M5):
    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_anonymisieren_dev.py
"""
import asyncio
import base64
import hashlib
import json
import shutil
import ssl
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")

BASIS = "https://127.0.0.1"
_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE
_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f"  [{info}]" if info else ""))


def abbruch(grund):
    print("ABBRUCH (Exit 2): " + grund)
    sys.exit(2)


def ruf(pfad, methode="GET", rumpf=None, token=None, roh=False, timeout=130):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    if daten is not None:
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, context=_ctx, timeout=timeout) as a:
            inhalt = a.read()
            if roh:
                return a.status, inhalt
            try:
                return a.status, json.loads(inhalt.decode("utf-8", "replace"))
            except Exception:  # noqa: BLE001
                return a.status, inhalt.decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        inhalt = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(inhalt)
        except Exception:  # noqa: BLE001
            return e.code, inhalt


print("=" * 74)
print("LIVE auf DEV: AI-Maus – Anonymisieren")
print("=" * 74)

from PIL import Image, ImageDraw, ImageFont  # noqa: E402

from backend import ai_mouse_fragen as amf  # noqa: E402
from backend import anonymisieren as anon  # noqa: E402
from backend import main as bm  # noqa: E402
from backend.config import config  # noqa: E402
from backend.tools import bild_text as BT  # noqa: E402

ARBEIT = Path(tempfile.mkdtemp(prefix="live-anon-"))
FRAGEN = amf._pfad()
SICHERUNG = FRAGEN.read_bytes() if FRAGEN.exists() else None
MD5_VOR = hashlib.md5(SICHERUNG or b"").hexdigest()
ERZEUGT = []


def testbild() -> Path:
    """Bildschirmausschnitt mit drei Namen, E-Mail, Telefon und einem Gesicht."""
    try:
        with urllib.request.urlopen(
                "https://raw.githubusercontent.com/opencv/opencv/4.x/samples/data/messi5.jpg",
                timeout=30) as a:
            (ARBEIT / "gesicht.jpg").write_bytes(a.read())
    except Exception as e:  # noqa: BLE001
        abbruch("Testgesicht nicht ladbar: %s" % e)
    img = Image.new("RGB", (900, 360), (250, 250, 250))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
    zeilen = ["Ticket PRJA-123 · Bearbeiter: Erika Mustermann · Status: offen",
              "Von: Max Müller <max.mueller@beispiel.de>",
              "Rückruf an Frau Schmidt, Tel. 0151 23456789",
              "Kunde: Contoso GmbH, Lieferung KW 44"]
    for i, z in enumerate(zeilen):
        d.text((12, 12 + i * 26), z, font=f, fill=(30, 30, 30))
    # Seitenverhaeltnis erhalten – ein verzerrtes Gesicht misst den Detektor
    # an einem Bild, das so nie auf einem Bildschirm steht.
    g = Image.open(ARBEIT / "gesicht.jpg").convert("RGB")
    g = g.resize((260, round(g.height * 260 / g.width)))
    img.paste(g, (620, 160))
    p = ARBEIT / "eingang.png"
    img.save(p)
    return p


def lesbar(pfad: Path) -> str:
    i = Image.open(pfad)
    gross = ARBEIT / "probe.png"
    i.resize((i.width * 2, i.height * 2), Image.LANCZOS).save(gross)
    return " ".join(w["text"] for w in BT.ocr_woerter(gross, "deu", min_konf=0, psm=11))


NAMEN = ("Mustermann", "Müller", "Schmidt", "mueller@beispiel")

try:
    eingang = testbild()
    vorher = lesbar(eingang)
    if not all(n in vorher for n in NAMEN):
        abbruch("Positivkontrolle: Testbild nicht lesbar (%r)" % vorher[:160])
    check("Positivkontrolle: Original enthaelt alle Namen lesbar", True)
    daten = eingang.read_bytes()

    # ── A. Echte Kette im Prozess ───────────────────────────────────────────
    print("\n=== A. Echte Kette (Presidio, YuNet, Modell) ===")

    async def zwei_laeufe():
        t0 = time.time()
        e1 = await anon.ausfuehren(daten, "de")
        t1 = time.time()
        e2 = await anon.ausfuehren(daten, "de")
        t2 = time.time()
        faehig = await anon._helfer.faehigkeiten()
        await anon.helfer_beenden()
        return e1, e2, t1 - t0, t2 - t1, faehig

    e1, e2, kalt, warm, faehig = asyncio.run(zwei_laeufe())
    print("  Zeiten: kalt %.1f s, warm %.1f s" % (kalt, warm))
    for e in (e1, e2):
        ERZEUGT.append(e["bild"].rsplit("/", 1)[-1])
    check("Namenserkennung im Hilfsprozess verfuegbar", faehig.get("personen"), str(faehig))
    check("Gesichtserkennung im Hilfsprozess verfuegbar", faehig.get("gesichter"), str(faehig))
    check("kein Teilausfall gemeldet", e1["luecken"] == [], str(e1["luecken"]))
    check("das Gesicht wurde gefunden", e1["zaehler"].get("GESICHT", 0) >= 1, str(e1["zaehler"]))
    ziel = anon._bildordner() / ERZEUGT[0]
    nachher = lesbar(ziel)
    for n in NAMEN:
        check("nach dem Lauf nicht mehr lesbar: %s" % n, n not in nachher, nachher[:160])
    check("Nicht-Namen bleiben lesbar (Status, Lieferung)",
          "Status" in nachher and "Lieferung" in nachher, nachher[:160])
    check("kalter Lauf bleibt unter dem Client-Timeout (120 s)", kalt < 110, "%.1f" % kalt)
    check("warmer Lauf ist schneller als der kalte", warm < kalt, "%.1f/%.1f" % (warm, kalt))
    check("Frist-Marke angelegt", (anon._frist_ordner() / ERZEUGT[0]).is_file())
    print("  Ergebnistext:\n    " + e1["text"].replace("\n", "\n    "))

    # ── B. Admin-Endpunkt ───────────────────────────────────────────────────
    print("\n=== B. Admin-Endpunkt ===")
    ADMIN = bm.generate_token("jarvis")
    st, d = ruf("/api/ai-mouse/admin/vorgaben", "POST",
                {"titel": "Live-Anon", "prompt": "Live-Probe anonymisieren.",
                 "aktion": "unsinn"}, ADMIN)
    check("unbekannte Aktion -> 400", st == 400, f"{st} {d}")
    st, d = ruf("/api/ai-mouse/admin/vorgaben", "POST",
                {"titel": "Live-Anon", "prompt": "Live-Probe anonymisieren.",
                 "aktion": "anonymisieren"}, ADMIN)
    vid = (d.get("vorgabe") or {}).get("id") if isinstance(d, dict) else None
    check("Vorgabe mit Aktion angelegt", st == 200 and (d.get("vorgabe") or {}).get("aktion")
          == "anonymisieren", f"{st} {d}")

    # ── C. Durchstich ueber /api/ai-mouse/analyze ───────────────────────────
    print("\n=== C. Durchstich ueber HTTP ===")
    erlaubt = [x.strip() for x in config.get_setting("aimouse_allowed_users", "").split(",")
               if x.strip()]
    U = next((x for x in erlaubt if bm._user_may_use_aimouse(x)), "")
    if not U:
        print("  (kein freigegebener AI-Maus-Benutzer auf DEV – Teil C uebersprungen)")
        check("Teil C laeuft (freigegebener Benutzer vorhanden)", False)
    else:
        TOK = bm.generate_token(U)
        st, d = ruf("/api/ai-mouse/fragen", token=TOK)
        check("Positivkontrolle: Benutzer erreicht seine Fragen", st == 200, f"{st}")
        kopie = next((f for f in (d.get("fragen") or []) if f.get("von_vorgabe") == vid), {})
        check("die Vorgabe kam samt Aktion in seine Liste",
              kopie.get("aktion") == "anonymisieren", str(kopie)[:120])
        time.sleep(3.5)  # Mindestabstand der Drossel im Dienst
        uri = "data:image/png;base64," + base64.b64encode(daten).decode()
        t0 = time.time()
        st, d = ruf("/api/ai-mouse/analyze", "POST",
                    {"image": uri, "prompt": "Live-Probe anonymisieren.", "lang": "de"}, TOK)
        dauer = time.time() - t0
        print("  Dauer ueber HTTP: %.1f s" % dauer)
        check("analyze antwortet 200 mit Bild", st == 200 and isinstance(d, dict)
              and str(d.get("bild", "")).startswith("/api/generated/"), f"{st} {str(d)[:160]}")
        check("Antwort traegt die Aktion, kein Modell", isinstance(d, dict)
              and d.get("aktion") == "anonymisieren" and d.get("modell") == "", str(d)[:160])
        if isinstance(d, dict) and d.get("bild"):
            ERZEUGT.append(d["bild"].rsplit("/", 1)[-1])
            st2, inhalt = ruf(d["bild"], token=TOK, roh=True)
            check("Ergebnisbild mit dem Token abrufbar", st2 == 200 and inhalt[:8] == b"\x89PNG\r\n\x1a\n",
                  str(st2))
            (ARBEIT / "http.png").write_bytes(inhalt if isinstance(inhalt, bytes) else b"")
            if st2 == 200:
                txt = lesbar(ARBEIT / "http.png")
                check("ueber HTTP: kein Name mehr lesbar", not any(n in txt for n in NAMEN), txt[:160])
        time.sleep(3.5)
        st, d = ruf("/api/ai-mouse/analyze", "POST",
                    {"image": uri, "prompt": "Bitte: Live-Probe anonymisieren. Danke", "lang": "de"},
                    TOK)
        check("ein Teilstring loest NICHT aus (gewoehnlicher Weg, kein aktion-Feld)",
              not (isinstance(d, dict) and d.get("aktion")), f"{st} {str(d)[:120]}")
        if isinstance(d, dict) and d.get("bild"):
            ERZEUGT.append(d["bild"].rsplit("/", 1)[-1])
    if vid:
        st, _ = ruf("/api/ai-mouse/admin/vorgaben/" + vid, "DELETE", token=ADMIN)
        check("Vorgabe wieder entfernt", st == 200, str(st))
finally:
    # Zustand byte-genau zuruecklegen – und PRUEFEN, nicht annehmen.
    with amf._SPERRE:
        if SICHERUNG is None:
            if FRAGEN.exists():
                FRAGEN.unlink()
        else:
            FRAGEN.write_bytes(SICHERUNG)
    md5_nach = hashlib.md5(FRAGEN.read_bytes() if FRAGEN.exists() else b"").hexdigest()
    check("Fragenbestand byte-genau wiederhergestellt", md5_nach == MD5_VOR)
    for n in ERZEUGT:
        for p in (anon._bildordner() / n, anon._frist_ordner() / n):
            try:
                p.unlink()
            except FileNotFoundError:
                pass
    shutil.rmtree(ARBEIT, ignore_errors=True)

print("\n%d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
