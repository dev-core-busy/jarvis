"""Waechter: AI-Maus-Aktion „Anonymisieren" (backend/anonymisieren.py & Co.).

Gemessen wird die WIRKUNG, nicht das Vorkommen:
  1. reine Bausteine (Zeilen, Trefferzuordnung, Balken, Ergebnistext, Frist),
  2. die ganze Kette auf einem ECHTEN Bild mit ECHTEM tesseract – nach dem Lauf
     liest die Texterkennung den Namen NICHT mehr, den Nicht-Namen schon; die
     Gesichtsbox ist veraendert, der Rest des Bildes nicht,
  3. Teilausfaelle werden im Ergebnistext GENANNT,
  4. die 30-Minuten-Frist raeumt genau das Eigene ab,
  5. das Feld ``aktion`` (nur Vorgaben, Whitelist, Erhalt beim Aendern,
     exakter Abgleich je Benutzer),
  6. ``ai_mouse.analysieren`` verzweigt OHNE Modellaufruf mit dem Bild.

Der Hilfsprozess (Presidio/YuNet) ist hier GESTELLT – lokal sind die Pakete
nicht installiert. Die echte Kette misst ``tests/live_anonymisieren_dev.py``.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen (kein tesseract/deu).
"""
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = FAIL = 0


def check(text: str, bedingung) -> None:
    global OK, FAIL
    if not isinstance(text, str):
        print("ABBRUCH: check() mit vertauschten Argumenten")
        sys.exit(2)
    if bedingung:
        OK += 1
        print("  OK   " + text)
    else:
        FAIL += 1
        print("  FAIL " + text)


def abbruch(grund: str) -> None:
    print("ABBRUCH (Exit 2): " + grund)
    sys.exit(2)


# ── Voraussetzungen ─────────────────────────────────────────────────────────
try:
    r = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=20)
    if "deu" not in (r.stdout + r.stderr):
        abbruch("tesseract ohne Sprachpaket deu")
except Exception as e:  # noqa: BLE001
    abbruch("tesseract nicht aufrufbar: %s" % e)
try:
    from PIL import Image, ImageDraw, ImageFont
except Exception as e:  # noqa: BLE001
    abbruch("Pillow fehlt: %s" % e)

SANDKASTEN = Path(tempfile.mkdtemp(prefix="jv-test-anon-", dir=os.path.expanduser("~")))
BILDER = SANDKASTEN / "generated_images"
FRIST = SANDKASTEN / "anonym_frist"
FRAGEN = SANDKASTEN / "ai_mouse_fragen.json"
BILDER.mkdir()

from backend import anonymisieren as AN  # noqa: E402
from backend import ai_mouse_fragen as AMF  # noqa: E402
from backend.tools import bild_text as BT  # noqa: E402

AN._bildordner = lambda: BILDER
AN._frist_ordner = lambda: FRIST
AMF._pfad = lambda: FRAGEN

# Sandkasten-Waechter: kein Pfad darf aus dem Wegwerfverzeichnis zeigen –
# sonst schriebe der Test in den echten Bestand (Register).
for p in (AN._bildordner(), AN._frist_ordner(), AMF._pfad()):
    if SANDKASTEN not in Path(p).resolve().parents:
        abbruch("Pfad ausserhalb des Sandkastens: %s" % p)
if "backend.config" in sys.modules:
    abbruch("backend.config wurde importiert – der Test darf die Live-Konfiguration nicht laden")

SCHRIFT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"


def ocr_text(pfad: Path) -> str:
    """Was tesseract im Bild liest – vergroessert wie im Produkt."""
    img = Image.open(pfad)
    gross = SANDKASTEN / "ocr_probe.png"
    img.resize((img.width * 2, img.height * 2), Image.LANCZOS).save(gross)
    return " ".join(w["text"] for w in BT.ocr_woerter(gross, "deu", min_konf=0, psm=11))


def testbild() -> tuple[bytes, tuple]:
    """Ein Bildschirmausschnitt: drei Zeilen Text und ein „Gesicht" (Muster)."""
    img = Image.new("RGB", (620, 200), (255, 255, 255))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(SCHRIFT, 15)
    d.text((10, 10), "Bearbeiter: Erika Mustermann    Status: offen", font=f, fill=(20, 20, 20))
    d.text((10, 40), "Kontakt: erika.mustermann@beispiel.de", font=f, fill=(20, 20, 20))
    d.text((10, 70), "Rückfrage bei Schmidt wegen Lieferung", font=f, fill=(20, 20, 20))
    # Das „Gesicht": ein kraeftiges Schachbrett – nach dem Verpixeln muss es
    # sichtbar anders sein, und seine Lage ist bekannt.
    gx, gy, gw, gh = 470, 100, 80, 80
    for x in range(gx, gx + gw, 8):
        for y in range(gy, gy + gh, 8):
            farbe = (0, 0, 0) if ((x - gx) // 8 + (y - gy) // 8) % 2 else (240, 200, 160)
            d.rectangle([x, y, x + 7, y + 7], fill=farbe)
    p = SANDKASTEN / "eingang.png"
    img.save(p)
    return p.read_bytes(), (gx, gy, gw, gh)


class GestellterHelfer:
    """Attrappe mit der ECHTEN Antwortform von ``anonym_helfer``."""

    def __init__(self, personen=True, gesichter=True, gesicht_box=None, start_fehler=False):
        self.personen, self.gesichter = personen, gesichter
        self.box, self.start_fehler = gesicht_box, start_fehler
        self.auftraege = []

    async def faehigkeiten(self):
        if self.start_fehler:
            raise RuntimeError("Hilfsprozess startet nicht")
        return {"personen": self.personen, "gesichter": self.gesichter, "fehler": {}}

    async def anfrage(self, auftrag):
        self.auftraege.append(auftrag)
        if auftrag["op"] == "personen":
            text = auftrag["text"]
            treffer = []
            for wort, typ in (("Erika Mustermann", "PERSON"),
                              ("erika.mustermann@beispiel.de", "EMAIL_ADDRESS")):
                i = text.find(wort)
                if i >= 0:
                    treffer.append({"start": i, "end": i + len(wort), "typ": typ, "score": 0.85})
            return {"ok": True, "treffer": treffer}
        if auftrag["op"] == "gesichter":
            # Die Datei muss WAEHREND des Laufs da sein (Pfad, nicht base64).
            check("der Hilfsprozess bekommt einen existierenden Bildpfad",
                  Path(auftrag["pfad"]).is_file())
            return {"ok": True, "boxen": [list(self.box) + [0.9]] if self.box else []}
        return {"ok": False, "fehler": "unbekannte Operation"}


async def llm_findet_schmidt(woerter, abschnitte):
    """Gestellte Ergaenzung: das Modell findet den Namen, den Presidio uebersah."""
    return {i for i, w in enumerate(woerter) if w["text"].startswith("Schmidt")}


async def llm_faellt_aus(woerter, abschnitte):
    raise RuntimeError("Modell nicht erreichbar")


def main() -> None:
    # ── 1. Bausteine ─────────────────────────────────────────────────────────
    print("\n=== 1. Bausteine ===")
    w = [
        {"text": "Erika", "l": 10, "t": 10, "w": 40, "h": 14},
        {"text": "Mustermann,", "l": 55, "t": 11, "w": 90, "h": 14},
        {"text": "Status", "l": 400, "t": 10, "w": 50, "h": 14},
        {"text": "Max", "l": 10, "t": 40, "w": 30, "h": 14},
    ]
    text, spannen, ab = AN.zeilen_bilden(w)
    check("jedes Wort steht an seiner Spanne im Text",
          all(text[s:e] == w[i]["text"] for i, (s, e) in enumerate(spannen)))
    check("Vor- und Nachname stehen in DERSELBEN Zeile",
          any(0 in a and 1 in a for a in ab))
    check("eine weite Luecke trennt Spalten (Name und Status nicht verbunden)",
          not any(0 in a and 2 in a for a in ab))
    check("verschiedene Hoehen ergeben verschiedene Zeilen",
          not any(0 in a and 3 in a for a in ab))
    s0 = text.find("Erika")
    zu = AN.treffer_zuordnen(spannen, [{"start": s0, "end": s0 + len("Erika Mustermann"),
                                        "typ": "PERSON"}])
    check("ein Treffer trifft auch das Wort mit anhaengendem Komma", set(zu) == {0, 1})
    b = AN.balken(w, ab, {0, 1})
    check("benachbarte Namensteile werden EIN Balken", len(b) == 1)
    check("der Balken umfasst beide Woerter",
          len(b) == 1 and b[0][0] <= 10 and b[0][2] >= 145)
    t = AN.ergebnistext({"PERSON": 2, "GESICHT": 1}, ["l_gesichter"], "de")
    check("Ergebnistext nennt Zahl und Art", "2 Name" in t and "1 Gesicht" in t)
    check("Ergebnistext nennt die Luecke", "Nicht vollständig geprüft" in t
          and "Gesichtserkennung" in t)
    check("Ergebnistext ohne Fund sagt das", "keine Namen" in AN.ergebnistext({}, [], "de"))
    check("englischer Ergebnistext", "Made unrecognisable" in
          AN.ergebnistext({"PERSON": 1}, [], "en"))

    alt = os.environ.get("JARVIS_ANONYM_TTL_MIN")
    try:
        for roh, soll in (("0", 30), ("-5", 30), ("x", 30), ("10", 10), ("99999", 1440)):
            os.environ["JARVIS_ANONYM_TTL_MIN"] = roh
            check("Frist %r -> %d Minuten" % (roh, soll), AN.ttl_minuten() == soll)
        os.environ.pop("JARVIS_ANONYM_TTL_MIN", None)
        check("Vorgabe der Frist: 30 Minuten", AN.ttl_minuten() == 30)
    finally:
        if alt is None:
            os.environ.pop("JARVIS_ANONYM_TTL_MIN", None)
        else:
            os.environ["JARVIS_ANONYM_TTL_MIN"] = alt

    # ── 2. Die ganze Kette ──────────────────────────────────────────────────
    print("\n=== 2. Ganze Kette (echtes tesseract, gestellter Hilfsprozess) ===")
    daten, (gx, gy, gw, gh) = testbild()
    vorher = ocr_text(SANDKASTEN / "eingang.png")
    # Positivkontrolle: ohne sie waere „Name nicht mehr lesbar" trivial wahr.
    if not ("Mustermann" in vorher and "Schmidt" in vorher and "Status" in vorher):
        abbruch("Positivkontrolle: tesseract liest das Testbild nicht (%r)" % vorher[:120])
    check("Positivkontrolle: das Original enthaelt lesbar alle Namen", True)

    helfer = GestellterHelfer(gesicht_box=(gx + 10, gy + 10, gw - 20, gh - 20))
    AN._helfer = helfer
    AN._llm_namen = llm_findet_schmidt
    erg = asyncio.run(AN.ausfuehren(daten, "de"))
    name = erg["bild"].rsplit("/", 1)[-1]
    ziel = BILDER / name
    check("Adresse in der Form, die der Client annimmt",
          bool(__import__("re").fullmatch(r"/api/generated/[0-9a-f]{32}\.png", erg["bild"])))
    check("das Ergebnisbild existiert", ziel.is_file())
    nachher = ocr_text(ziel) if ziel.is_file() else ""
    check("Presidio-Treffer: „Mustermann“ ist nicht mehr lesbar", "Mustermann" not in nachher)
    check("Presidio-Treffer: „Erika“ ist nicht mehr lesbar", "Erika" not in nachher)
    check("E-Mail-Adresse ist nicht mehr lesbar", "beispiel.de" not in nachher)
    check("Modell-Ergaenzung wirkt (Vereinigung): „Schmidt“ ist nicht mehr lesbar",
          "Schmidt" not in nachher)
    check("Nicht-Namen bleiben lesbar („Status“, „Lieferung“)",
          "Status" in nachher and "Lieferung" in nachher)
    a = Image.open(SANDKASTEN / "eingang.png").convert("RGB")
    b = Image.open(ziel).convert("RGB") if ziel.is_file() else a
    mitte = (gx + gw // 2, gy + gh // 2)
    box = (gx + 4, gy + 4, gx + gw - 4, gy + gh - 4)
    diff_innen = sum(1 for x in range(box[0], box[2], 3) for y in range(box[1], box[3], 3)
                     if a.getpixel((x, y)) != b.getpixel((x, y)))
    check("die Gesichtsbox ist veraendert (mehr als die Haelfte der Proben)",
          diff_innen > ((box[2] - box[0]) // 3) * ((box[3] - box[1]) // 3) // 2)
    # Ein Bereich ohne Text und ohne Gesicht bleibt Pixel fuer Pixel gleich.
    frei = [(x, y) for x in range(10, 400, 7) for y in range(140, 195, 5)]
    check("ein unberuehrter Bereich bleibt Pixel fuer Pixel gleich",
          all(a.getpixel(p) == b.getpixel(p) for p in frei))
    check("Ergebnis zaehlt Namen, E-Mail und Gesicht",
          erg["zaehler"].get("PERSON", 0) >= 2 and erg["zaehler"].get("EMAIL_ADDRESS") == 1
          and erg["zaehler"].get("GESICHT") == 1)
    check("kein Teilausfall gemeldet, wenn alles lief", erg["luecken"] == [])
    check("die Frist-Marke zum Ergebnis ist angelegt", (FRIST / name).is_file())
    check("das Original liegt nach dem Lauf NIRGENDS mehr (Arbeitsordner weg)",
          not any(Path(au["pfad"]).exists() for au in helfer.auftraege if "pfad" in au))
    check("der Hilfsprozess bekam Text und Bildpfad, nie Bildbytes",
          all(set(au) <= {"op", "text", "pfad"} for au in helfer.auftraege))

    # ── 3. Teilausfaelle werden genannt ─────────────────────────────────────
    print("\n=== 3. Teilausfaelle ===")
    AN._helfer = GestellterHelfer(start_fehler=True)
    AN._llm_namen = llm_faellt_aus
    erg2 = asyncio.run(AN.ausfuehren(daten, "de"))
    check("trotz Ausfall entsteht ein Bild", (BILDER / erg2["bild"].rsplit("/", 1)[-1]).is_file())
    check("Ausfall des Hilfsprozesses wird genannt", "l_helfer" in erg2["luecken"]
          and "Erkennungsdienst" in erg2["text"])
    check("Ausfall des Modells wird genannt", "l_llm" in erg2["luecken"]
          and "Sprachmodell" in erg2["text"])
    check("der Text behauptet bei Ausfall NICHT, alles sei geprueft",
          "Nicht vollständig geprüft" in erg2["text"])
    AN._helfer = GestellterHelfer(personen=False, gesichter=False)
    AN._llm_namen = llm_findet_schmidt
    erg3 = asyncio.run(AN.ausfuehren(daten, "de"))
    check("fehlende Namenserkennung wird genannt", "l_personen" in erg3["luecken"])
    check("fehlende Gesichtserkennung wird genannt", "l_gesichter" in erg3["luecken"])

    # ── 4. Frist ────────────────────────────────────────────────────────────
    print("\n=== 4. 30-Minuten-Frist ===")
    jetzt = time.time()
    # ⚠ Den Ordner HIER anlegen, nicht auf Abschnitt 2 verlassen: fehlt die
    # Marke dort (genau die Sabotage „keine Frist-Marke"), gibt es den Ordner
    # nicht, und der Aufbau unten stuerzte OHNE Bilanzzeile ab statt die
    # Abschnitt-2-Pruefung als FAIL zu melden (Gegenprobe 2026-10-27).
    FRIST.mkdir(exist_ok=True)
    alt_name, neu_name, fremd_name = "a" * 32 + ".png", "b" * 32 + ".png", "c" * 32 + ".png"
    for n in (alt_name, neu_name, fremd_name):
        (BILDER / n).write_bytes(b"x")
    for n in (alt_name, neu_name):
        (FRIST / n).write_bytes(b"")
    os.utime(FRIST / alt_name, (jetzt - 31 * 60, jetzt - 31 * 60))
    # Ein Symlink als Marke darf nicht verfolgt werden.
    ziel_link = SANDKASTEN / "nicht_anfassen.txt"
    ziel_link.write_text("bleibt")
    link_name = "d" * 32 + ".png"
    os.symlink(ziel_link, FRIST / link_name)
    os.utime(FRIST / link_name, (jetzt - 99 * 60, jetzt - 99 * 60), follow_symlinks=False)
    weg = AN.aufraeumen(now=jetzt)
    check("abgelaufenes Ergebnis ist geloescht", not (BILDER / alt_name).exists())
    check("seine Marke ist geloescht", not (FRIST / alt_name).exists())
    check("ein junges Ergebnis bleibt", (BILDER / neu_name).exists() and (FRIST / neu_name).exists())
    check("ein Bild OHNE Marke (fremder Schreibweg) bleibt unberuehrt", (BILDER / fremd_name).exists())
    check("ein Symlink als Marke wird nicht verfolgt", ziel_link.read_text() == "bleibt")
    check("Rueckgabe zaehlt die geloeschten Bilder", weg == 1)
    alle_marken = [p for p in FRIST.iterdir() if AN._NAME_RE.fullmatch(p.name)]
    check("nach 31 Minuten raeumt die Frist auch die Lauf-Ergebnisse ab",
          AN.aufraeumen(now=jetzt + 31 * 60) >= 3 and
          not any((BILDER / p.name).exists() for p in alle_marken if not p.is_symlink()))

    # ── 5. Feld `aktion` ─────────────────────────────────────────────────────
    print("\n=== 5. Aktionsfeld an Vorgaben ===")
    try:
        AMF.vorgabe_speichern("", "X", "y", "loeschen_alles")
        check("eine unbekannte Aktion wird ABGELEHNT", False)
    except AMF.FragenFehler:
        check("eine unbekannte Aktion wird ABGELEHNT", True)
    v = AMF.vorgabe_speichern("", "Anonymisieren", "Namen unkenntlich machen.", "anonymisieren")
    check("Vorgabe mit Aktion gespeichert", v.get("aktion") == "anonymisieren")
    liste = AMF.liste("erika")
    kopie = next((e for e in liste if e.get("von_vorgabe") == v["id"]), None)
    check("die Kopie beim Benutzer traegt die Aktion", bool(kopie) and kopie.get("aktion") == "anonymisieren")
    check("exakter Abgleich findet die Aktion",
          AMF.aktion_fuer("erika", "Namen unkenntlich machen.") == "anonymisieren")
    check("Leerraum am Rand stoert nicht",
          AMF.aktion_fuer("erika", "  Namen unkenntlich machen.\n") == "anonymisieren")
    check("ein TEILSTRING loest nichts aus",
          AMF.aktion_fuer("erika", "Bitte: Namen unkenntlich machen. Danke") == "")
    check("die Aktion gilt nur fuer Benutzer, die die Frage HABEN",
          AMF.aktion_fuer("max", "Namen unkenntlich machen.") == "")
    if kopie:
        AMF.speichern("erika", kopie["id"], "Umbenannt", kopie["prompt"])
        neu = next((e for e in AMF.liste("erika") if e["id"] == kopie["id"]), {})
        check("Umbenennen der Kopie erhaelt die Aktion", neu.get("aktion") == "anonymisieren")
    eigen = AMF.speichern("erika", "", "Eigene", "Eigene Frage")
    check("eine selbst angelegte Frage hat KEINE Aktion", "aktion" not in eigen)
    v2 = AMF.vorgabe_speichern(v["id"], "Anonymisieren", "Namen unkenntlich machen.", "")
    check("Zuruecksetzen der Art entfernt die Aktion an der Vorgabe", "aktion" not in v2)

    # ── 6. Verzweigung in analysieren ───────────────────────────────────────
    print("\n=== 6. ai_mouse.analysieren verzweigt ohne Modell ===")
    from backend import ai_mouse as AM  # noqa: E402
    import base64  # noqa: E402

    aufrufe = {"anon": 0, "agent": 0, "modell": 0}

    async def anon_attrappe(daten_, lang_):
        aufrufe["anon"] += 1
        return {"text": "Unkenntlich gemacht: 1 Name(n).", "bild": "/api/generated/" + "e" * 32 + ".png"}

    async def agent_attrappe(*a, **k):
        aufrufe["agent"] += 1
        return "Antwort", "m", []

    AN.ausfuehren = anon_attrappe
    AM._agent_lauf = agent_attrappe
    AM.freigegebene_bereiche = lambda: []
    AM.werkzeuge_fuer = lambda *a, **k: {"x"}
    uri = "data:image/png;base64," + base64.b64encode(daten).decode()
    AMF.vorgabe_speichern("", "Anon2", "Bitte anonymisieren.", "anonymisieren")
    AMF.liste("erika")  # uebernimmt die neue Vorgabe in seine Liste
    r1 = asyncio.run(AM.analysieren(uri, "Bitte anonymisieren.", "erika"))
    check("Frage mit Aktion: Anonymisieren lief", aufrufe["anon"] == 1)
    check("Frage mit Aktion: KEIN Agent und kein Modell mit dem Bild", aufrufe["agent"] == 0)
    check("Antwort traegt das Bild und die Antwortform des Clients",
          r1.get("ok") is True and r1.get("bild", "").startswith("/api/generated/")
          and r1.get("aktion") == "anonymisieren" and r1.get("modell") == "")
    AM._letzte.clear()
    AM._fenster.clear()
    asyncio.run(AM.analysieren(uri, "Was ist das?", "erika"))
    check("Frage OHNE Aktion: der gewoehnliche Weg laeuft", aufrufe["agent"] == 1)
    check("Frage OHNE Aktion: kein Anonymisieren", aufrufe["anon"] == 1)


try:
    main()
finally:
    shutil.rmtree(SANDKASTEN, ignore_errors=True)

print("\n%d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
