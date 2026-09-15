"""Werkzeug: fremdsprachlichen Text IM BILD durch eine Uebersetzung ersetzen.

═══ WARUM ES DAS GIBT (Vorfall 2026-09-15) ═══

Auf ECHT bat ein Benutzer in /chat: "uebersetze das Bild nach Deutsch in dem Du
die fremdsprachlichen Texte direkt im Bild durch die Deutsche Uebersetzung
ueberschreibst. Generiere dazu ein neues Bild" - mit einer englischen
Praesentationsfolie als Anhang.

Das konnte Jarvis nicht: ``generate_image`` erzeugt ein NEUES Bild aus einer
TEXTBESCHREIBUNG und kann in einem gelieferten Bild nichts austauschen. Das
Modell hat daraufhin `steps=0` geliefert, eine `/api/generated/...`-Adresse
FREI ERFUNDEN und "Hier ist das generierte Bild" geschrieben - es gab keines.
(Der Anzeigepfad faengt das jetzt ab, siehe `agent._KEIN_BILD_HINWEIS`.)

⚠ DIE DATEN GEHEN NICHT DURCH DAS SPRACHMODELL - nur der TEXT.
Dieselbe Regel wie in ``skills/office/tabellen.py`` und ``pdf_formular.py``:
das Modell nennt die Datei, die Arbeit passiert hier. Es bekommt die erkannten
Absaetze als Text zu sehen und gibt die Uebersetzung zurueck; Pixel sieht es
nie, und das fertige Bild geht als kurze URL heraus.

═══ WAS DAS LEISTET - UND WAS NICHT ═══

Gemessen an einer echten Folie (dem gemeldeten `sample.gif`, 1310x727):
Titel, Zitat und Fliesstext werden sauber ersetzt, der Grund bleibt nahtlos,
Seitenzahl und Firmenname bleiben unangetastet.

NICHT geleistet - und das steht auch im Ergebnis, damit es niemand erwartet:
  - Die ORIGINALSCHRIFT wird nicht getroffen (es wird DejaVu gesetzt).
  - Auf einem FOTO als Untergrund funktioniert das Ueberdecken nicht; das
    Werkzeug ist fuer flaechige Untergruende (Folien, Diagramme, Screenshots).
  - Mehrere Textstile IN EINEM Absatz werden vereinheitlicht.
"""

import json
import re
import subprocess
import uuid
from collections import Counter, defaultdict
from pathlib import Path

from backend.tools.base import BaseTool

# ⚠ `llm` und `image_gen` werden ERST IN DEN FUNKTIONEN importiert. Beide ziehen
# ueber `backend.config` den halben Backend-Stack (inkl. dotenv) nach - und die
# Bildarbeit hier braucht davon nichts. So laeuft der Waechter ohne Stubs gegen
# die ECHTEN Funktionen; und `backend.config` in einem Test zu importieren
# schreibt die Live-settings.json zurueck (Register).


def _bildordner():
    """Der Ordner fuer erzeugte Bilder - lazy, damit das Modul ohne den
    Backend-Stack importierbar bleibt. Ein Test biegt DIESE Funktion um."""
    from backend.tools.image_gen import _IMG_DIR
    return _IMG_DIR


def _bild_merken(pfad, url):
    """`record_task_image`, lazy und fail-safe: ohne den Eintrag wuerde
    `_mit_bildern` das Bild nicht nachtragen, wenn das Modell die Zeile
    weglaesst - aber ein Fehler hier darf das fertige Bild nicht kosten."""
    try:
        from backend.tools.image_gen import record_task_image
        record_task_image(pfad, url)
    except Exception:  # noqa: BLE001
        pass

# Schriften: DejaVu liegt auf Debian in jedem Standardbild.
_SCHRIFT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
_SCHRIFT_FETT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# tesseract-Konfidenz, unter der ein Wort als Rauschen gilt.
_MIN_KONF = 45
# Polster um die ueberdeckte Flaeche (Antialiasing-Rand des Originaltextes).
_RAND = 3
# Mehr als das ist keine Folie mehr, sondern ein Textdokument - und der
# LLM-Aufruf fuer die Uebersetzung wuerde unverhaeltnismaessig.
_MAX_ABSAETZE = 60
# ⚠ Eine horizontale Luecke ab diesem Anteil der Bildbreite trennt Elemente,
# die tesseract in EINE Zeile gruppiert. Am gemeldeten Bild gemessen: "68"
# (links) und "futurice" (rechts) liegen 1000 px auseinander und wurden zu
# einem Absatz "68 futurice" - wer den ersetzt, schreibt beides nach links.
_LUECKE_ANTEIL = 0.12


def _tesseract_da() -> bool:
    try:
        subprocess.run(["tesseract", "--version"], capture_output=True, timeout=20)
        return True
    except Exception:  # noqa: BLE001
        return False


def _als_png(pfad):
    """Das Bild nach RGB-PNG normalisieren - und WARUM das noetig ist.

    ⚠ GEMESSEN AM GEMELDETEN BILD (2026-09-15): tesseract liest dasselbe Bild
    als GIF SCHLECHTER als als PNG. Beim GIF fehlte die halbe Zeile
    ("If only HP knew what HP knows, we would be three-times more" war weg),
    beim PNG war sie da - gleiche Datei, gleicher Inhalt, nur das Containerformat
    anders. Ein GIF ist palettenbasiert; die Binarisierung faellt dort anders aus.

    Der Prototyp hatte vorher konvertiert und den Fehler deshalb NICHT gezeigt -
    gefunden erst am echten Anhang. Ohne diese Zeile verliert das Werkzeug
    stillschweigend Text, und die Uebersetzung ist unvollstaendig.

    Gibt (pfad, temporaeres_verzeichnis_oder_None) zurueck.
    """
    from PIL import Image  # noqa: PLC0415
    import tempfile  # noqa: PLC0415

    p = Path(pfad)
    if p.suffix.lower() == ".png":
        try:
            if Image.open(p).mode == "RGB":
                return p, None
        except Exception:  # noqa: BLE001
            return p, None
    try:
        tmp = tempfile.mkdtemp(prefix="jv-bildtext-")
        ziel = Path(tmp) / "quelle.png"
        Image.open(p).convert("RGB").save(ziel)
        return ziel, tmp
    except Exception:  # noqa: BLE001
        # Fail-open: lieber mit dem Original arbeiten als gar nicht.
        return p, None


def ocr_absaetze(pfad, sprache: str = "eng") -> list:
    """tesseract TSV -> Absaetze mit Box, Text und Zeilenhoehe.

    ⚠ ABSATZWEISE, NICHT ZEILENWEISE: beim Uebersetzen aendert sich die
    Wortstellung, eine Zeile-zu-Zeile-Zuordnung gibt es nicht. Wer zeilenweise
    ersetzt, bekommt Stueckwerk.
    """
    quelle, _tmp = _als_png(pfad)
    try:
        return _ocr_roh(quelle, sprache)
    finally:
        if _tmp:
            import shutil  # noqa: PLC0415
            shutil.rmtree(_tmp, ignore_errors=True)


def _ocr_roh(pfad, sprache: str) -> list:
    r = subprocess.run(
        ["tesseract", str(pfad), "stdout", "-l", sprache, "tsv"],
        capture_output=True, text=True, timeout=180,
        # OMP_THREAD_LIMIT=1: tesseract belegt sonst alle Kerne und wird bei
        # mehreren gleichzeitigen Laeufen langsamer, nicht schneller (am
        # Haus-Server gemessen, siehe pdf_formular.py).
        env={"OMP_THREAD_LIMIT": "1", "PATH": "/usr/bin:/bin"})
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "").strip()[:300] or "tesseract meldet einen Fehler")

    zeilen = r.stdout.splitlines()
    if not zeilen:
        return []
    kopf = zeilen[0].split("\t")
    idx = {n: i for i, n in enumerate(kopf)}
    noetig = ("conf", "text", "left", "top", "width", "height",
              "block_num", "par_num", "line_num")
    if any(n not in idx for n in noetig):
        raise RuntimeError("tesseract liefert ein unerwartetes TSV-Format")

    woerter = []
    for z in zeilen[1:]:
        t = z.split("\t")
        if len(t) < len(kopf):
            continue
        try:
            konf = float(t[idx["conf"]])
        except ValueError:
            continue
        wort = t[idx["text"]].strip()
        if konf < _MIN_KONF or not wort:
            continue
        woerter.append({
            "block": int(t[idx["block_num"]]), "par": int(t[idx["par_num"]]),
            "line": int(t[idx["line_num"]]),
            "l": int(t[idx["left"]]), "t": int(t[idx["top"]]),
            "w": int(t[idx["width"]]), "h": int(t[idx["height"]]),
            "text": wort, "konf": konf,
        })

    gruppen = defaultdict(list)
    for w in woerter:
        gruppen[(w["block"], w["par"])].append(w)

    roh = []
    for _schluessel, ws in sorted(gruppen.items()):
        roh.extend(_nach_luecken_trennen(ws))

    absaetze = []
    for ws in roh:
        zeilen_map = defaultdict(list)
        for w in ws:
            zeilen_map[w["line"]].append(w)
        text = " ".join(
            " ".join(x["text"] for x in sorted(zeilen_map[ln], key=lambda a: a["l"]))
            for ln in sorted(zeilen_map))
        hoehen = sorted(w["h"] for w in ws)
        absaetze.append({
            "id": len(absaetze),
            "text": text,
            "l": min(w["l"] for w in ws), "t": min(w["t"] for w in ws),
            "r": max(w["l"] + w["w"] for w in ws), "b": max(w["t"] + w["h"] for w in ws),
            "zeilen": len(zeilen_map),
            "zeilenhoehe": hoehen[len(hoehen) // 2],
            "konf": sum(w["konf"] for w in ws) / len(ws),
        })
    return absaetze


def _nach_luecken_trennen(ws: list, bildbreite: int = 0) -> list:
    """Einen tesseract-Absatz an grossen horizontalen Luecken aufteilen.

    Gilt nur fuer EINZEILIGE Gruppen: bei mehrzeiligem Fliesstext ist eine
    Luecke am Zeilenende normal und darf nicht trennen.
    """
    if len({w["line"] for w in ws}) != 1 or len(ws) < 2:
        return [ws]
    sortiert = sorted(ws, key=lambda w: w["l"])
    spanne = sortiert[-1]["l"] + sortiert[-1]["w"] - sortiert[0]["l"]
    grenze = max(60, int(spanne * _LUECKE_ANTEIL))
    teile, akt = [], [sortiert[0]]
    for vor, w in zip(sortiert, sortiert[1:]):
        if w["l"] - (vor["l"] + vor["w"]) > grenze:
            teile.append(akt)
            akt = [w]
        else:
            akt.append(w)
    teile.append(akt)
    return teile


def farben(img, box):
    """Grund- und Textfarbe MESSEN, nicht raten.

    Grund = haeufigste Farbe im Ring UM die Box (dort steht kein Text).
    Text  = die Farbe IN der Box, die am weitesten vom Grund entfernt liegt.

    Eine geratene Grundfarbe (etwa pauschal Weiss) hinterlaesst auf jeder
    getoenten Folie einen sichtbaren Kasten.
    """
    l, t, r, b = box
    W, H = img.size
    ring = []
    for x in range(max(0, l - 6), min(W, r + 6), 2):
        for y in (max(0, t - 6), min(H - 1, b + 5)):
            ring.append(img.getpixel((x, y)))
    for y in range(max(0, t - 6), min(H, b + 6), 2):
        for x in (max(0, l - 6), min(W - 1, r + 5)):
            ring.append(img.getpixel((x, y)))
    grund = Counter(ring).most_common(1)[0][0] if ring else (255, 255, 255)

    innen = Counter()
    for x in range(l, min(W, r), 2):
        for y in range(t, min(H, b), 2):
            innen[img.getpixel((x, y))] += 1
    kandidaten = [(c, n) for c, n in innen.items() if n >= 3]
    if not kandidaten:
        return grund, (0, 0, 0)
    text = max(kandidaten, key=lambda cn: sum((a - b2) ** 2 for a, b2 in zip(cn[0], grund)))[0]
    return grund, text


def strichstaerke(img, box, grund) -> float:
    """Mittlere horizontale Strichbreite, bezogen auf die Zeilenhoehe.

    ⚠ NUR IM VERGLEICH AUSSAGEKRAEFTIG, nie absolut: bei kleiner Schrift ist
    das Verhaeltnis systematisch hoeher (ein Stamm ist mindestens ein Pixel
    breit). Gemessen an zwei echten Folien lag der Titel einmal bei 0.094
    (leichte Schrift) und einmal bei 0.189 (fett) - waehrend normaler
    Fliesstext bei 0.115 bis 0.182 lag. Eine feste Schwelle trennt das nicht,
    der Median DESSELBEN Bildes schon.
    """
    l, t, r, b = box
    W, H = img.size
    laeufe = []
    for y in range(t, min(b, H)):
        lauf = 0
        for x in range(l, min(r, W)):
            p = img.getpixel((x, y))
            if sum((a - c) ** 2 for a, c in zip(p, grund)) > 12000:
                lauf += 1
            elif lauf:
                if lauf <= 40:          # breite Flaechen sind kein Buchstabenstamm
                    laeufe.append(lauf)
                lauf = 0
    if not laeufe:
        return 0.0
    laeufe.sort()
    return laeufe[len(laeufe) // 2] / max(1, (b - t))


def _umbrechen(draw, text, font, breite):
    zeilen, akt = [], ""
    for wort in text.split():
        probe = (akt + " " + wort).strip()
        if draw.textlength(probe, font=font) <= breite or not akt:
            akt = probe
        else:
            zeilen.append(akt)
            akt = wort
    if akt:
        zeilen.append(akt)
    return zeilen


def _einpassen(draw, text, box, zeilenhoehe, fett):
    """Die groesste Schriftgroesse, mit der der Text in die Box passt.

    Deutsch ist rund 30 % laenger als Englisch; ohne Verkleinern laeuft der
    Text regelmaessig aus seinem Kasten.
    """
    from PIL import ImageFont

    l, t, r, b = box
    bw, bh = r - l, b - t
    pfad = _SCHRIFT_FETT if fett else _SCHRIFT
    start = max(8, int(zeilenhoehe)) + 4
    for groesse in range(start, 6, -1):
        font = ImageFont.truetype(pfad, groesse)
        zeilen = _umbrechen(draw, text, font, bw)
        zh = groesse * 1.25
        if len(zeilen) * zh <= bh + zeilenhoehe * 0.6:
            return font, zeilen, zh
    font = ImageFont.truetype(pfad, 8)
    return font, _umbrechen(draw, text, font, bw), 10.0


def ersetzen(quelle, ziel, absaetze, uebersetzungen: dict) -> list:
    """Schreibt das neue Bild. Gibt einen Bericht je Absatz zurueck."""
    from PIL import Image, ImageDraw

    img = Image.open(quelle).convert("RGB")
    d = ImageDraw.Draw(img)

    # Fettschrift relativ zum Median DIESES Bildes (siehe strichstaerke).
    staerken = {}
    for a in absaetze:
        g, _ = farben(img, (a["l"], a["t"], a["r"], a["b"]))
        staerken[a["id"]] = strichstaerke(img, (a["l"], a["t"], a["r"], a["b"]), g)
    werte = sorted(v for v in staerken.values() if v > 0)
    median = werte[len(werte) // 2] if werte else 0.0

    bericht = []
    for a in absaetze:
        neu = (uebersetzungen.get(a["id"]) or "").strip()
        if not neu or neu == a["text"]:
            bericht.append({"id": a["id"], "aktion": "unveraendert"})
            continue
        box = (a["l"], a["t"], a["r"], a["b"])
        grund, textfarbe = farben(img, box)
        d.rectangle([box[0] - _RAND, box[1] - _RAND, box[2] + _RAND, box[3] + _RAND],
                    fill=grund)
        fett = median > 0 and staerken.get(a["id"], 0) > median * 1.15
        font, zeilen, zh = _einpassen(d, neu, box, a["zeilenhoehe"], fett)
        y = a["t"]
        for z in zeilen:
            d.text((a["l"], y), z, font=font, fill=textfarbe)
            y += zh
        bericht.append({"id": a["id"], "aktion": "ersetzt",
                        "groesse": font.size, "orig": a["zeilenhoehe"],
                        "zeilen": len(zeilen), "fett": fett})
    img.save(ziel)
    return bericht


_UE_PROMPT = (
    "Du uebersetzt Textbausteine aus einem Bild (Folie, Diagramm oder Screenshot) "
    "nach {ziel}.\n\n"
    "REGELN:\n"
    "- Gib AUSSCHLIESSLICH ein JSON-Objekt zurueck: {{\"0\": \"...\", \"1\": \"...\"}} - "
    "Schluessel ist die Nummer des Bausteins, Wert die Uebersetzung.\n"
    "- FASSE DICH KURZ. Der Text muss in denselben Platz passen wie das Original. "
    "Lieber knapp als ausufernd.\n"
    "- Eigennamen, Firmennamen, Produktnamen, Zahlen, Seitenzahlen und Abkuerzungen "
    "bleiben UNVERAENDERT.\n"
    "- Ist ein Baustein bereits in der Zielsprache oder ein blosser Name/eine Zahl, "
    "gib ihn UNVERAENDERT zurueck.\n"
    "- Keine Erklaerungen, kein Markdown, keine Code-Zaeune.\n\n"
    "BAUSTEINE:\n{bausteine}"
)


async def _uebersetzen(absaetze: list, ziel: str) -> dict:
    """EIN Modellaufruf fuer alle Bausteine - nicht einer je Absatz."""
    bausteine = "\n".join(f'{a["id"]}: {a["text"]}' for a in absaetze)
    prompt = _UE_PROMPT.format(ziel=ziel, bausteine=bausteine)
    # ⚠ DIE SIGNATUR IST (model, system_prompt, contents) MIT types.Content -
    # NICHT `messages=[{"role": ...}]`. Ein geratener Aufruf wirft
    # "unexpected keyword argument 'messages'" und die Uebersetzung faellt
    # komplett aus (am 2026-09-15 live gemessen). Der tragende Weg steht in
    # backend/prompt_check.py; die Antwort kommt als Objekt mit `.parts`,
    # nicht als String.
    from backend import llm  # noqa: PLC0415 - siehe Kopf
    from google.genai import types  # noqa: PLC0415

    provider, modell = llm.provider_fuer_lauf()
    antwort = await provider.generate_response(
        model=modell,
        system_prompt="Du uebersetzt praezise und knapp. Antworte NUR mit JSON.",
        contents=[types.Content(role="user",
                                parts=[types.Part.from_text(text=prompt)])],
        # OHNE WERKZEUGE: hier wird uebersetzt, nicht gehandelt.
        tools=[])
    roh = ""
    for teil in (getattr(antwort, "parts", None) or []):
        roh += getattr(teil, "text", "") or ""
    if not roh:
        roh = str(getattr(antwort, "text", "") or "")
    roh = roh.strip()
    # Tolerant: Modelle legen gern Code-Zaeune drumherum.
    m = re.search(r"\{.*\}", roh, re.S)
    if not m:
        raise RuntimeError("die Uebersetzung kam nicht als JSON zurueck")
    daten = json.loads(m.group(0))
    return {int(k): str(v) for k, v in daten.items() if str(k).lstrip("-").isdigit()}


class BildTextErsetzenTool(BaseTool):
    # Der Dispatch prueft diesen Parameter generisch gegen authorize_fs("read").
    # OHNE DAS waere das Werkzeug der bequemste Weg am Pfad-Confinement und an
    # der Eigentuemer-Schranke in data/documents vorbei.
    pfad_parameter = ("pfad",)

    @property
    def name(self) -> str:
        return "bild_text_ersetzen"

    @property
    def description(self) -> str:
        return (
            "Ersetzt den TEXT IN EINEM VORHANDENEN BILD durch seine Uebersetzung und gibt "
            "das Bild zurueck. Genau dafuer, wenn der Nutzer sagt: 'uebersetze das Bild', "
            "'schreibe die Uebersetzung ins Bild', 'ersetze den Text im Bild', "
            "'uebersetze die Folie und behalte das Layout'.\n"
            "NICHT generate_image dafuer verwenden - das erzeugt ein NEUES Bild aus einer "
            "Textbeschreibung und kann in einem gelieferten Bild nichts austauschen.\n"
            "Geeignet fuer Folien, Diagramme und Screenshots (flaechiger Untergrund). "
            "Auf Fotos als Untergrund funktioniert das Ueberdecken nicht."
        )

    def parameters_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pfad": {
                    "type": "string",
                    "description": "Pfad zur Bilddatei (z.B. die Arbeitskopie eines Anhangs "
                                   "unter /tmp). PNG, JPEG, GIF, BMP oder WebP.",
                },
                "zielsprache": {
                    "type": "string",
                    "description": "Sprache, in die uebersetzt wird. Vorgabe: Deutsch.",
                },
                "quellsprache": {
                    "type": "string",
                    "description": "Sprache IM BILD als tesseract-Kuerzel: 'eng' (Vorgabe) "
                                   "oder 'deu'. Nur eine angeben - zwei Sprachmodelle "
                                   "gleichzeitig erkennen messbar schlechter.",
                },
            },
            "required": ["pfad"],
        }

    async def execute(self, **kwargs) -> str:
        pfad = str(kwargs.get("pfad") or kwargs.get("datei") or kwargs.get("bild") or "").strip()
        if not pfad:
            return "Fehler: Es wurde kein Bildpfad (pfad) angegeben."
        ziel_sprache = str(kwargs.get("zielsprache") or "Deutsch").strip() or "Deutsch"
        quelle_sprache = str(kwargs.get("quellsprache") or "eng").strip().lower()
        if not re.fullmatch(r"[a-z]{3}", quelle_sprache):
            quelle_sprache = "eng"

        p = Path(pfad)
        if not p.is_file():
            return f"Fehler: Die Datei existiert nicht: {pfad}"
        if not _tesseract_da():
            return ("HINWEIS_AN_NUTZER: Fuer das Ersetzen von Text im Bild wird die "
                    "Texterkennung (tesseract) gebraucht, sie ist auf diesem Server nicht "
                    "verfuegbar. Ein Administrator kann sie mit "
                    "'apt install tesseract-ocr tesseract-ocr-deu' nachinstallieren.")
        try:
            from PIL import Image  # noqa: F401
        except Exception:
            return ("HINWEIS_AN_NUTZER: Fuer das Ersetzen von Text im Bild wird Pillow "
                    "gebraucht, es ist auf diesem Server nicht verfuegbar.")

        try:
            absaetze = ocr_absaetze(p, quelle_sprache)
        except Exception as e:  # noqa: BLE001
            return f"HINWEIS_AN_NUTZER: Die Texterkennung ist fehlgeschlagen: {e}"
        if not absaetze:
            return ("HINWEIS_AN_NUTZER: In diesem Bild wurde kein Text erkannt - es gibt "
                    "also nichts zu ersetzen. Moeglich bei Handschrift, sehr kleiner "
                    "Schrift oder starker Kompression.")
        if len(absaetze) > _MAX_ABSAETZE:
            return (f"HINWEIS_AN_NUTZER: Das Bild enthaelt {len(absaetze)} Textbloecke "
                    f"(hoechstens {_MAX_ABSAETZE} werden bearbeitet). Fuer ein ganzes "
                    "Textdokument ist dieses Werkzeug nicht gedacht.")

        try:
            ue = await _uebersetzen(absaetze, ziel_sprache)
        except Exception as e:  # noqa: BLE001
            return f"HINWEIS_AN_NUTZER: Die Uebersetzung ist fehlgeschlagen: {e}"
        if not ue:
            return "HINWEIS_AN_NUTZER: Die Uebersetzung kam leer zurueck."

        ordner = _bildordner()
        ordner.mkdir(parents=True, exist_ok=True)
        name = f"{uuid.uuid4().hex}.png"
        ziel = ordner / name
        try:
            bericht = ersetzen(p, ziel, absaetze, ue)
        except Exception as e:  # noqa: BLE001
            return f"HINWEIS_AN_NUTZER: Das Bild konnte nicht geschrieben werden: {e}"

        geaendert = sum(1 for b in bericht if b["aktion"] == "ersetzt")
        if not geaendert:
            try:
                ziel.unlink()
            except Exception:  # noqa: BLE001
                pass
            return ("HINWEIS_AN_NUTZER: Es wurde nichts ersetzt - die erkannten Texte sind "
                    "offenbar schon in der Zielsprache oder bestehen nur aus Namen und Zahlen.")

        url = f"/api/generated/{name}"
        _bild_merken(ziel, url)
        # Die REIHENFOLGE ist bewusst wie bei generate_image: erst die Marke,
        # dann die Zeile, die das Modell unveraendert uebernehmen soll.
        return (
            "BILD_ERZEUGT. Gib in deiner finalen Antwort EXAKT die folgende Markdown-Bildreferenz "
            "unveraendert aus (zusammen mit einem kurzen Satz), damit das Bild angezeigt wird:\n\n"
            f"![Uebersetztes Bild]({url})\n"
            # ⚠ "3 von 5" ALLEIN WIRD ALS FEHLSCHLAG GELESEN. Im echten Lauf
            # (DEV, 2026-09-15) machte das Modell daraus "Zwei Bloecke konnten
            # nicht erkannt oder uebersetzt werden" - dabei waren es "68" und
            # "futurice", die absichtlich stehen bleiben. Eine Zahl ohne ihre
            # Bedeutung ist eine Einladung zur Falschaussage an den Benutzer.
            f"Uebersetzt: {geaendert} von {len(absaetze)} Textbloecken; die uebrigen "
            f"{len(absaetze) - geaendert} sind Namen, Zahlen oder standen schon in der "
            "Zielsprache und bleiben BEWUSST unveraendert - das ist KEIN Fehler und "
            "gehoert nicht als Einschraenkung gemeldet.\n"
            "Die Originalschrift wird nicht getroffen (es wird eine Standardschrift "
            "gesetzt) - nenne das dem Nutzer nur, wenn er nach der Optik fragt."
        )
