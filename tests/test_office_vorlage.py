#!/usr/bin/env python3
"""Tests fuer die PowerPoint-Hausvorlage (skills/office/vorlage.py + main.py).

DER AUSGANGSPUNKT: ``office_create_powerpoint`` rief ``Presentation()`` ohne
Argument auf – also das eingebaute Standarddesign von python-pptx: 4:3,
Calibri, Office-Blau, kein Bezug zum Branding. Jetzt wird eine Vorlage mit
echten Masterfolien benutzt.

DIE WICHTIGSTEN PRUEFUNGEN sind die beiden Regressionsfaelle, die erst der
PDF-Blick gezeigt hat:
 1. Platzhalter duerfen NICHT breiter als die Folie werden (die erste Fassung
    skalierte geerbte Layout-Platzhalter ein zweites Mal: 8229600 → 10972525 →
    14630400 bei 12192000 Folienbreite), und
 2. ``top`` darf nicht auf 0 fallen (beim Anlegen eines neuen ``xfrm`` kennt
    python-pptx nur die gesetzte Achse – im PDF klebten die Titel dadurch am
    oberen Rand).

Teil 1 laeuft ueberall (Quelltext), Teil 2 nur mit python-pptx (DEV im venv).
"""

import asyncio
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = 0
_fail = 0


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  ✓ {text}")
    else:
        _fail += 1
        print(f"  ✗ {text}" + (f" – {detail}" if detail else ""))


# ═════════════════════════════════════════════════════════════════════════════
print("\n=== 1. Quelltext ===")

V = (ROOT / "skills" / "office" / "vorlage.py").read_text()
M = (ROOT / "skills" / "office" / "main.py").read_text()

pruefe("BREITE_16_9 = 12192000" in V, "Vorlage ist 16:9 (nicht das 4:3-Standardtemplate)")
pruefe("eigene_geometrie" in V,
       "Skalierung fasst nur Formen mit EIGENEM xfrm an (sonst doppelt + top=0)")
pruefe('"Arial"' in V, "Schrift ist Arial (auf Fremdrechnern vorhanden)")
pruefe("colors_light" in V and "accent" in V, "Akzentfarbe kommt aus dem Branding")
pruefe("VORLAGEN_DIR" in V and "vorlagen" in V and '"documents"' not in V,
       "Vorlagen liegen NICHT in data/documents (dort gilt Frist + Eigentuemer)")
pruefe("titleStyle" in V,
       "Titel-Ausrichtung wird im Master-titleStyle gesetzt (Layout-Absatz wirkt nicht)")
pruefe("txBody.insert(1, lst)" in V,
       "lstStyle wird an der schema-richtigen Stelle eingefuegt (bodyPr, lstStyle, p)")

pruefe("Presentation(str(_vorlage.loese_vorlage(template)))" in M,
       "das Werkzeug nutzt die Vorlage")
pruefe("_LAYOUT_ALIAS" in M and "Title and Content" in M,
       "Layouts werden ueber NAMEN gesucht, deutsch UND englisch")
pruefe("_LAYOUT_FALLBACK" in M, "Rueckfall-Index, wenn eine Fremdvorlage andere Namen nutzt")
pruefe("placeholder_format.type" in M,
       "Platzhalter werden ueber den TYP gewaehlt, nicht ueber placeholders[1]")
pruefe("PH.DATE" not in M and "erlaubt = {PH.BODY" in M,
       "Datum/Fusszeile/Foliennummer werden nie mit Inhalt befuellt")
pruefe("_leere_platzhalter_entfernen" in M,
       "leere Platzhalter werden entfernt (sonst 'Klicken Sie, um Text hinzuzufuegen')")
pruefe("TemplateInfoTool()" in M, "office_template_info ist registriert")
i_desc = M.find("KEINE Farb-, Schrift- oder Groessenangaben")
pruefe(i_desc > 0, "die Werkzeug-Beschreibung verbietet eigene Stilangaben ausdruecklich")
# Der Kern des Vorlagen-Wegs: es wird NUR Text gesetzt.
pruefe(".font.size" not in M.split("class CreatePowerPointTool")[1].split("class TemplateInfoTool")[0],
       "das Werkzeug setzt keine Schriftgroessen (die kommen aus der Vorlage)")

# ═════════════════════════════════════════════════════════════════════════════
print("\n=== 2. Erzeugte Vorlage ===")

try:
    from pptx import Presentation
    from skills.office import vorlage as VO
    HAT_PPTX = True
except Exception as e:  # noqa: BLE001
    HAT_PPTX = False
    print(f"  … uebersprungen: {type(e).__name__} ({e}) – auf DEV im venv ausfuehren")

if HAT_PPTX:
    # _hex: Farbnormierung
    faelle = [("#9B59B6", "9B59B6"), ("9b59b6", "9B59B6"), ("#abc", "AABBCC"),
              ("", "FALLBACK"), (None, "FALLBACK"), ("rgb(1,2,3)", "FALLBACK"),
              ("#12345", "FALLBACK"), ("  #10B981  ", "10B981")]
    for roh, erwartet in faelle:
        got = VO._hex(roh, "FALLBACK")
        pruefe(got == erwartet, f"_hex({roh!r}) -> {got}", f"erwartet {erwartet}")

    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="jvorl_"))
    ziel = tmp / "probe.pptx"
    VO.erzeuge(ziel)
    pruefe(ziel.exists() and ziel.stat().st_size > 10000, "Vorlage wird erzeugt")

    prs = Presentation(str(ziel))
    pruefe(prs.slide_width == 12192000 and prs.slide_height == 6858000,
           f"Format 16:9 ({prs.slide_width}×{prs.slide_height})")
    namen = [l.name for l in prs.slide_layouts]
    pruefe("Titelfolie" in namen and "Titel und Inhalt" in namen,
           f"Layouts deutsch benannt ({namen[:3]})")
    pruefe("Akzentbalken" in [s.name for s in prs.slide_masters[0].shapes],
           "Akzentbalken liegt im Master (auf jeder Folie, nicht verschiebbar)")

    # ── REGRESSION 1: nichts ist breiter als die Folie ──────────────────────
    zu_breit = []
    top_null = []
    for l in prs.slide_layouts:
        for sh in l.shapes:
            try:
                if sh.left is None or sh.width is None:
                    continue
                if sh.left + sh.width > prs.slide_width + 1000:
                    zu_breit.append(f"{l.name}/{sh.name}={sh.left + sh.width}")
                if sh.top == 0 and sh.height and sh.height < prs.slide_height:
                    top_null.append(f"{l.name}/{sh.name}")
            except Exception:  # noqa: BLE001
                continue
    pruefe(not zu_breit, "kein Platzhalter ragt aus der Folie (keine Doppel-Skalierung)",
           ", ".join(zu_breit[:3]))
    pruefe(not top_null, "kein Platzhalter auf top=0 gerutscht", ", ".join(top_null[:3]))

    # Volle Breite wird genutzt: rechter Rand = linker Rand (symmetrisch)
    inhalt = [l for l in prs.slide_layouts if l.name == "Titel und Inhalt"][0]
    titel = list(inhalt.placeholders)[0]
    links = titel.left
    rechts = prs.slide_width - (titel.left + titel.width)
    pruefe(abs(links - rechts) < 20000,
           f"Ränder symmetrisch (links {links}, rechts {rechts})")
    pruefe(titel.width > 10000000, f"Titel nutzt die Breitbild-Breite ({titel.width})")

    # ── Theme im ZIP ────────────────────────────────────────────────────────
    x = zipfile.ZipFile(str(ziel)).read("ppt/theme/theme1.xml").decode("utf-8")
    def slot(name):
        m = re.search(r"<a:" + name + r">.*?val=\"([0-9A-Fa-f]{6})\"", x, re.S)
        return (m.group(1).upper() if m else "")
    erwartet_akzent = VO.branding_farben()["akzent"]
    pruefe(slot("accent1") == erwartet_akzent,
           f"accent1 ist die Branding-/Standardfarbe ({slot('accent1')})")
    pruefe(slot("lt1") == "FFFFFF", f"heller Hintergrund ({slot('lt1')})")
    pruefe(slot("dk1") == VO.DUNKEL, f"dunkle Textfarbe ({slot('dk1')})")
    pruefe(slot("accent2") == VO.PALETTE[0],
           "Folgefarben = dieselbe Reihe wie Diagramme (charts.js/mplstyle)")
    pruefe("windowText" not in x and "sysClr" not in x.split("</a:clrScheme>")[0],
           "sysClr (windowText/window) wurde ersetzt – sonst blieben Text/Hintergrund alt")
    pruefe(len(re.findall(r"<a:latin typeface=\"Arial\"", x)) >= 2,
           "Arial fuer Ueberschrift UND Grundtext")
    pruefe("Calibri" not in x, "keine Calibri-Reste im Theme")

    # ── Titel-Ausrichtung ───────────────────────────────────────────────────
    mx = zipfile.ZipFile(str(ziel)).read("ppt/slideMasters/slideMaster1.xml").decode("utf-8")
    tstyle = mx.split("<p:titleStyle>")[1].split("</p:titleStyle>")[0] if "<p:titleStyle>" in mx else ""
    pruefe('algn="l"' in tstyle, "Master-Titelstil ist linksbuendig")
    tl = [l for l in prs.slide_layouts if l.name == "Titelfolie"][0]
    tl_xml = tl.element.xml
    pruefe('algn="ctr"' in tl_xml, "Titelfolie bleibt zentriert (eigener lstStyle)")

    # ── Abschnitt: Titel oben ───────────────────────────────────────────────
    ab = [l for l in prs.slide_layouts if l.name == "Abschnitt"][0]
    phs = {}
    for ph in ab.placeholders:
        phs[str(ph.placeholder_format.type)] = ph.top
    t_top = next((v for k, v in phs.items() if "TITLE" in k), None)
    b_top = next((v for k, v in phs.items() if "BODY" in k or "OBJECT" in k), None)
    pruefe(t_top is not None and b_top is not None and t_top < b_top,
           f"Abschnittsfolie: Titel steht ueber dem Zusatztext ({t_top} < {b_top})")

    # ── sicherstellen / loese_vorlage ───────────────────────────────────────
    vor = ziel.stat().st_mtime_ns
    gleich = VO.sicherstellen(ziel)
    pruefe(gleich == ziel and ziel.stat().st_mtime_ns == vor,
           "sicherstellen() erzeugt eine vorhandene Vorlage NICHT neu (Handaustausch bleibt)")
    echt = VO.VORLAGEN_DIR / VO.STANDARD_NAME
    pruefe(VO.loese_vorlage("../../data/settings.json").name.endswith(".pptx"),
           "Pfadanteile im Vorlagennamen werden verworfen")
    pruefe(VO.loese_vorlage("gibtsnicht") == echt or VO.loese_vorlage("gibtsnicht").exists(),
           "unbekannte Vorlage faellt auf die Standardvorlage zurueck")

    # ═════════════════════════════════════════════════════════════════════════
    print("\n=== 3. Layout-Auflösung und Befuellung ===")

    from skills.office.main import (_layout, _fuelle, _text_platzhalter,
                                    _leere_platzhalter_entfernen, _titel_setzen,
                                    CreatePowerPointTool, TemplateInfoTool)

    pruefe(_layout(prs, "inhalt").name == "Titel und Inhalt", "Kurzname 'inhalt' trifft")
    pruefe(_layout(prs, "abschnitt").name == "Abschnitt", "Kurzname 'abschnitt' trifft")
    pruefe(_layout(prs, "zwei").name == "Zwei Inhalte", "Kurzname 'zwei' trifft")
    pruefe(_layout(prs, "leer").name == "Leer", "Kurzname 'leer' trifft")
    pruefe(_layout(prs, "quatsch") is not None, "unbekannte Art liefert trotzdem ein Layout")

    # Englische Fremdvorlage: das Standardtemplate von python-pptx
    fremd = Presentation()
    pruefe(_layout(fremd, "inhalt").name == "Title and Content",
           "englische Layoutnamen werden ebenfalls getroffen")
    # Teiltreffer (Firmenvorlagen haengen gern etwas an)
    fremd.slide_layouts[1].name = "Titel und Inhalt (intern)"
    pruefe(_layout(fremd, "inhalt").name == "Titel und Inhalt (intern)",
           "Teiltreffer im Layoutnamen wird erkannt")

    # Befuellung inkl. Ebenen
    p2 = Presentation(str(ziel))
    s = p2.slides.add_slide(_layout(p2, "inhalt"))
    _titel_setzen(s, "Titel")
    felder = _text_platzhalter(s)
    pruefe(len(felder) == 1, f"genau EIN befuellbares Feld im Inhalts-Layout ({len(felder)})")
    _fuelle(felder[0], bullets=["Eins", "> Unter", ">> Tiefer", {"text": "Vier", "level": 1},
                                ("Fuenf", 2)])
    stufen = [p.level for p in felder[0].text_frame.paragraphs]
    texte = [p.text for p in felder[0].text_frame.paragraphs]
    pruefe(stufen == [0, 1, 2, 1, 2], f"Aufzaehlungsebenen: {stufen}")
    pruefe(texte == ["Eins", "Unter", "Tiefer", "Vier", "Fuenf"], f"Texte: {texte}")
    pruefe(all("font" not in p._pPr.xml if p._pPr is not None else True
               for p in felder[0].text_frame.paragraphs),
           "keine Schriftangaben in den Absaetzen (Vorlage bestimmt das Aussehen)")

    # Leere Platzhalter verschwinden
    s2 = p2.slides.add_slide(_layout(p2, "inhalt"))
    _titel_setzen(s2, "Nur Titel gesetzt")
    vorher = len(list(s2.placeholders))
    _leere_platzhalter_entfernen(s2)
    nachher = len(list(s2.placeholders))
    pruefe(nachher < vorher, f"leere Platzhalter entfernt ({vorher} -> {nachher})")
    pruefe(s2.shapes.title is not None and s2.shapes.title.text == "Nur Titel gesetzt",
           "der gefuellte Titel bleibt erhalten")

    # ── Ende zu Ende ────────────────────────────────────────────────────────
    print("\n=== 4. Ende zu Ende ===")
    r = asyncio.run(CreatePowerPointTool().execute(
        filename="test_vorlage_e2e",
        title="Titel", subtitle="Unter",
        slides=[
            {"title": "Erste", "bullets": ["A", "> a1"], "notes": "Notiz"},
            {"layout": "zwei", "title": "Zwei", "bullets": ["L1", "L2", "R1", "R2"]},
            {"layout": "abschnitt", "title": "Kapitel"},
        ]))
    pruefe("/api/documents/" in r, f"Download-Link geliefert ({r[:60]})")
    pruefe("Hinweis:" not in r, f"Vorlage war nutzbar (kein Rueckfall) – {r[-90:]}")
    m = re.search(r"/api/documents/([0-9a-f]{32}__[^)\s]+)", r)
    erzeugt = Path(ROOT / "data" / "documents" / m.group(1)) if m else None
    if erzeugt and erzeugt.exists():
        e = Presentation(str(erzeugt))
        pruefe(e.slide_width == 12192000, "erzeugte Datei ist 16:9")
        pruefe(len(e.slides) == 4, f"vier Folien ({len(e.slides)})")
        pruefe(e.slides[0].slide_layout.name == "Titelfolie", "erste Folie nutzt die Titelfolie")
        pruefe(e.slides[2].slide_layout.name == "Zwei Inhalte", "Zwei-Spalten-Layout genutzt")
        pruefe(e.slides[3].slide_layout.name == "Abschnitt", "Abschnitts-Layout genutzt")
        # Zwei-Spalten: beide Seiten befuellt
        spalten = _text_platzhalter(e.slides[2])
        gefuellt = [p for p in spalten if p.text_frame.text.strip()]
        pruefe(len(gefuellt) == 2, f"beide Spalten haben Inhalt ({len(gefuellt)})")
        pruefe(e.slides[1].has_notes_slide
               and "Notiz" in e.slides[1].notes_slide.notes_text_frame.text,
               "Sprechernotiz uebernommen")
        # Keine leeren Rahmen mehr
        leere = [sh.name for s3 in e.slides for sh in s3.placeholders
                 if sh.has_text_frame and not sh.text_frame.text.strip()]
        pruefe(not leere, f"keine leeren Platzhalter in der Datei ({leere[:3]})")
        try:
            erzeugt.unlink()
        except Exception:  # noqa: BLE001
            pass
    else:
        pruefe(False, "erzeugte Datei gefunden", str(erzeugt))

    info = asyncio.run(TemplateInfoTool().execute())
    pruefe("16:9" in info and "Titel und Inhalt" in info,
           "office_template_info nennt Format und Layouts")
    pruefe("abschnitt" in info and "nurtitel" in info, "…und die Kurznamen")

    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

print(f"\n{'=' * 62}\nErgebnis: {_ok}/{_ok + _fail} Pruefungen bestanden")
if _fail:
    print(f"FEHLGESCHLAGEN: {_fail}")
sys.exit(1 if _fail else 0)
