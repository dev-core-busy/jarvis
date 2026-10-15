#!/usr/bin/env python3
"""Der GANZE Weg auf DEV: Ausschnitt -> Uebersetzung -> angezeigtes Bild.

Laeuft im Produktiv-venv als Dienstbenutzer und ruft `ai_mouse.analysieren`
mit einem ECHTEN Bild und dem ECHTEN Modell. Gemessen wird das ERGEBNIS:
existiert die Datei hinter der gelieferten Adresse, und steht darin wirklich
deutscher statt englischer Text?

⚠ DIE PROBE STELLT DEN VORGEFUNDENEN ZUSTAND WIEDER HER. Skill-Schalter und
Freigabe sind Zustand des Betreibers; eine Messung, die sie auf einen
geratenen Leerwert zuruecksetzt, nimmt ihm die Einstellung weg (Register,
2026-09-09 an genau dieser Datei passiert).
"""
import asyncio
import base64
import io
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
os.environ.setdefault("HOME", "/home/jarvis")

_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


def sicher(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return e


from backend import ai_mouse as am          # noqa: E402
from backend.config import config           # noqa: E402

# ── Vorzustand MERKEN ──────────────────────────────────────────────────────
_zust = config.get_skill_states()
VOR_SKILL = dict(_zust.get("ai_mouse") or {}) if "ai_mouse" in _zust else None
print("Vorzustand ai_mouse: %r" % (VOR_SKILL,))


def zurueck():
    """Den VORGEFUNDENEN Zustand herstellen – nicht einen geratenen."""
    try:
        if VOR_SKILL is None:
            config.remove_skill_state("ai_mouse")
            print("  (Skill-Eintrag entfernt – so war er vorgefunden)")
        else:
            config.save_skill_state("ai_mouse", VOR_SKILL)
            print("  (Skill-Zustand zurueckgestellt: %r)" % (VOR_SKILL,))
    except Exception as e:  # noqa: BLE001
        print("  ⚠ Zustand NICHT zurueckgestellt: %s" % e)


# ── Ein echtes Testbild: englischer Text auf flaechigem Grund ─────────────
# Genau der Anwendungsfall (Folie/Screenshot), nicht ein Foto.
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

_SCHRIFT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
bild = Image.new("RGB", (900, 320), (245, 246, 248))
zeichner = ImageDraw.Draw(bild)
gross = ImageFont.truetype(_SCHRIFT, 44)
klein = ImageFont.truetype(_SCHRIFT, 28)
zeichner.text((60, 60), "Please restart the server", font=gross, fill=(20, 20, 30))
zeichner.text((60, 150), "The connection was lost", font=klein, fill=(60, 60, 70))
zeichner.text((60, 200), "Contact your administrator", font=klein, fill=(60, 60, 70))
puffer = io.BytesIO()
bild.save(puffer, format="PNG")
PNG = puffer.getvalue()
URI = "data:image/png;base64," + base64.b64encode(PNG).decode("ascii")
print("Testbild: %d Bytes, %dx%d\n" % (len(PNG), bild.width, bild.height))

BENUTZER = "jarvis"
ordner = Path("/opt/jarvis/data/generated_images")
vorher = set(p.name for p in ordner.glob("*.png")) if ordner.is_dir() else set()
erzeugt = None

try:
    # Skill einschalten (und am Ende auf den Vorzustand zurueck).
    config.save_skill_state("ai_mouse", {"enabled": True,
                                         "config": (VOR_SKILL or {}).get("config", {})})

    print("=== 1) Voraussetzungen ===")
    check("der Skill ist fuer die Messung aktiv", am.skill_aktiv())
    check("das Bildwerkzeug ist ladbar", am.bild_werkzeug_da())
    # ⚠ KEINE ANNAHME UEBER DIE UMGEBUNG. Der erste Lauf verlangte hier "die
    # Bereiche sind leer" und meldete einen FAIL, den es nicht gab: auf DEV
    # sind `wissen,fach` freigeschaltet. Gemessen wird die EIGENSCHAFT – das
    # Bildwerkzeug kommt dazu, UNABHAENGIG davon, was freigeschaltet ist.
    _ber = am.freigegebene_bereiche()
    print("  (freigeschaltete Bereiche auf diesem Server: %s)" % (_ber or "keine"))
    check("…und steht damit im Werkzeugsatz, egal was freigeschaltet ist",
          am.BILD_WERKZEUG in am.werkzeuge_fuer(_ber))
    check("…waehrend es selbst KEINE Freigabe ist",
          am.BILD_WERKZEUG not in am.werkzeuge_fuer(_ber, mit_bild=False))

    print("\n=== 2) Die Arbeitskopie entsteht wirklich ===")
    pfad = am.ausschnitt_ablegen(PNG, "image/png", BENUTZER)
    check("ausschnitt_ablegen liefert einen Pfad", bool(pfad), repr(pfad))
    check("…die Datei existiert", bool(pfad) and Path(pfad).is_file())
    check("…mit byte-gleichem Inhalt",
          bool(pfad) and Path(pfad).read_bytes() == PNG)
    check("…0644, ohne Ausfuehrungsrecht",
          bool(pfad) and (Path(pfad).stat().st_mode & 0o777) == 0o644,
          oct(Path(pfad).stat().st_mode & 0o777) if pfad else "")
    check("…und NICHT in data/documents",
          bool(pfad) and "data/documents" not in pfad, repr(pfad))
    if pfad:
        Path(pfad).unlink(missing_ok=True)   # die Probe raeumt ihre Datei ab

    print("\n=== 3) Der ECHTE Lauf: 'uebersetze das Bild nach Deutsch' ===")

    # ⚠ BEIDE LAEUFE IN EINEM EVENT-LOOP. Ein zweites `asyncio.run()` stirbt
    # mit "Event loop is closed": der httpx-Client des Providers haengt am
    # ERSTEN Loop. Im ersten Anlauf war die Gegenprobe in Abschnitt 4 deshalb
    # GRUEN AUS DEM FALSCHEN GRUND – es lief gar kein Modellaufruf, und "kein
    # Bild erzeugt" war trivial wahr. Steht woertlich im Register.
    async def _beide():
        eins = await am.analysieren(
            bild_roh=URI,
            frage_roh="Übersetze den Text im Bild nach Deutsch und schreibe die "
                      "Übersetzung direkt ins Bild.",
            user=BENUTZER, lang="de")
        am._reset_fuer_tests()
        zwei = await am.analysieren(
            bild_roh=URI, frage_roh="Was steht auf diesem Ausschnitt?",
            user=BENUTZER, lang="de")
        return eins, zwei

    t0 = time.time()
    _paar = sicher(asyncio.run, _beide())
    dauer = time.time() - t0
    print("  (Dauer beider Laeufe: %.1f s)" % dauer)
    if isinstance(_paar, Exception):
        r = _paar
        r2 = _paar
    else:
        r, r2 = _paar

    if isinstance(r, Exception):
        check("der Lauf ist durchgelaufen", False, "%s: %s" % (type(r).__name__, r))
    else:
        check("der Lauf ist durchgelaufen", isinstance(r, dict) and r.get("ok"))
        print("  Modell : %s" % r.get("modell"))
        print("  Text   : %s" % (r.get("text") or "")[:200].replace("\n", " ⏎ "))
        print("  Bild   : %r" % r.get("bild"))

        check("die Antwort traegt das Feld `bild`", "bild" in r)
        url = r.get("bild") or ""
        check("…und es nennt eine erzeugte Adresse", url.startswith("/api/generated/"),
              repr(url))
        check("der Anzeigetext traegt KEINE rohe Markdown-Referenz",
              "/api/generated/" not in (r.get("text") or ""))

        if url.startswith("/api/generated/"):
            name = url.rsplit("/", 1)[-1]
            ziel = ordner / name
            erzeugt = ziel
            check("die Datei hinter der Adresse EXISTIERT wirklich", ziel.is_file(),
                  str(ziel))
            if ziel.is_file():
                neu = Image.open(ziel)
                check("…sie ist ein lesbares Bild", neu.width > 0 and neu.height > 0,
                      "%dx%d" % (neu.width, neu.height))
                check("…in der Groesse des Ausschnitts",
                      (neu.width, neu.height) == (bild.width, bild.height),
                      "%dx%d gegen %dx%d" % (neu.width, neu.height, bild.width, bild.height))

                # ⚠ DER EIGENTLICHE NACHWEIS: steht jetzt DEUTSCH im Bild?
                # Ohne diese Messung waere "es kam eine Datei zurueck" die
                # halbe Wahrheit – eine unveraenderte Kopie erfuellt das auch.
                import subprocess
                p = subprocess.run(["tesseract", str(ziel), "-", "-l", "deu"],
                                   capture_output=True, text=True, timeout=120)
                text_im_bild = (p.stdout or "").lower()
                print("  OCR    : %s" % " / ".join(
                    z.strip() for z in text_im_bild.splitlines() if z.strip())[:220])
                check("der englische Originaltext ist WEG",
                      "please restart" not in text_im_bild
                      and "connection was lost" not in text_im_bild)
                check("…und es steht deutscher Text darin",
                      any(w in text_im_bild for w in
                          ("server", "verbindung", "neu", "starten", "administrator",
                           "bitte", "kontakt")),
                      text_im_bild[:120])

    print("\n=== 4) Gegenprobe: eine reine FRAGE erzeugt kein Bild ===")
    if isinstance(r2, Exception):
        check("der Frage-Lauf ist durchgelaufen", False,
              "%s: %s" % (type(r2).__name__, r2))
    else:
        print("  Text   : %s" % (r2.get("text") or "")[:200].replace("\n", " ⏎ "))
        # POSITIVKONTROLLE ZUERST: ohne sie ist "kein Bild erzeugt" auch dann
        # wahr, wenn der Lauf gar nicht stattgefunden hat.
        check("der Frage-Lauf hat wirklich geantwortet",
              bool((r2.get("text") or "").strip())
              and "Event loop is closed" not in (r2.get("text") or ""))
        check("…und das Modell hat den Bildinhalt gelesen",
              any(w in (r2.get("text") or "").lower()
                  for w in ("server", "verbindung", "connection", "restart",
                            "administrator")),
              (r2.get("text") or "")[:120])
        check("eine reine Frage erzeugt KEIN Bild", r2.get("bild") == "",
              repr(r2.get("bild")))
finally:
    print("\n=== Aufraeumen ===")
    if erzeugt is not None and erzeugt.is_file():
        erzeugt.unlink()
        print("  (erzeugtes Testbild entfernt: %s)" % erzeugt.name)
    nachher = set(p.name for p in ordner.glob("*.png")) if ordner.is_dir() else set()
    rest = nachher - vorher
    check("keine Testdatei bleibt in data/generated_images liegen", not rest,
          ", ".join(sorted(rest)))
    zurueck()

print("\n%d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
