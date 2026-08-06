"""Neutrale PowerPoint-Vorlage aus den Branding-Farben.

WARUM ES DAS GIBT: ``office_create_powerpoint`` rief bisher ``Presentation()``
OHNE Argument auf. Damit gilt das eingebaute Standarddesign von python-pptx –
und das ist der Grund, warum erzeugte Decks „nicht wie eine Firmenpräsentation"
aussehen:

  * **4:3** (9144000 × 6858000 EMU). Seit rund zehn Jahren ist 16:9 der
    Standard; 4:3 erkennt jeder Betrachter sofort als veraltet.
  * **Calibri** und das Office-Standard-Blau – kein Bezug zum Branding.
  * Alle Farben liegen als *Theme*-Werte im Master. Wer sie pro Folie
    überschreibt (Textfarbe je Absatz setzen), bekommt eine Datei, die beim
    Bearbeiten in PowerPoint auseinanderfällt: der Designer zeigt dann andere
    Farben als die Folien. Deshalb wird hier das THEME geändert, nicht die
    einzelne Folie.

ERGEBNIS: eine .pptx mit echten Masterfolien, Layouts und Platzhaltern, die
PowerPoint wie eine von Hand angelegte Vorlage behandelt. Der Agent befüllt nur
Platzhalter – Schriftgrößen, Aufzählungsebenen und Abstände kommen aus der
Vorlage.

WARUM DAS THEME-XML DIREKT IM ZIP GEPATCHT WIRD: python-pptx hat keine API für
``a:clrScheme``/``a:fontScheme``. Der Weg über die internen Part-Objekte wäre an
die Version gebunden; eine .pptx ist ein ZIP, und ``ppt/theme/theme1.xml`` ist
eine gewöhnliche Datei darin. Das ist stabil und prüfbar (der Test liest die
Farben genau so wieder aus).

SCHRIFTWAHL – bewusst ANDERS als bei matplotlib: dort zählt, was auf dem SERVER
installiert ist (`backend/plotstyles/jarvis.mplstyle` nennt DejaVu/Liberation).
Eine .pptx wird dagegen auf einem FREMDEN Rechner geöffnet. Dort gibt es kein
Liberation Sans, und PowerPoint ersetzt es sichtbar. Deshalb ``Arial``: auf
Windows/macOS vorhanden, und LibreOffice auf dem Server bildet es metrisch
identisch auf Liberation Sans ab – der PDF-Export bleibt also maßhaltig.
"""

import re
import zipfile
from pathlib import Path

# Vorlagen liegen neben den erzeugten Dokumenten, aber in einem EIGENEN Ordner:
# data/documents wird nach Frist aufgeraeumt (documents.cleanup_old) und ist
# eigentuemergebunden – eine Vorlage darf weder verfallen noch einem Benutzer
# gehoeren.
VORLAGEN_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "vorlagen"
STANDARD_NAME = "standard.pptx"

# 16:9 in EMU (13.333 × 7.5 Zoll)
BREITE_16_9 = 12192000
HOEHE_16_9 = 6858000

# Rueckfallfarben, wenn kein Branding konfiguriert ist: das Jarvis-Lila plus
# dieselbe Reihe wie im Web-Theme (frontend/js/charts.js) und im
# matplotlib-Stil. Ein Diagramm und die Folie darum sollen nicht verschieden
# aussehen.
STANDARD_AKZENT = "9B59B6"
PALETTE = ["3B82F6", "10B981", "F59E0B", "EF4444", "06B6D4"]

# Helle, dokumententaugliche Grundfarben. Das dunkle Chat-Theme waere hier
# falsch: eine Praesentation wird gedruckt, projiziert und weitergegeben.
HELL = "FFFFFF"
DUNKEL = "1A2233"
GRAU = "4A5568"

# Deutsche Layout-Namen. Der Agent spricht Layouts ueber den NAMEN an (siehe
# main.py::_layout); englische Namen aus dem Standardtemplate waeren fuer eine
# deutschsprachige Oberflaeche eine unnoetige Huerde. Der englische Name bleibt
# als Alias in main.py erhalten, damit eine FREMDE Firmenvorlage weiter passt.
LAYOUT_NAMEN = {
    "Title Slide": "Titelfolie",
    "Title and Content": "Titel und Inhalt",
    "Section Header": "Abschnitt",
    "Two Content": "Zwei Inhalte",
    "Comparison": "Vergleich",
    "Title Only": "Nur Titel",
    "Blank": "Leer",
    "Content with Caption": "Inhalt mit Beschriftung",
    "Picture with Caption": "Bild mit Beschriftung",
}


def _hex(wert, fallback: str) -> str:
    """Normiert eine Farbangabe auf 6 Hex-Ziffern ohne '#'.

    Branding-Werte kommen aus einem Eingabefeld: '#9B59B6', '9b59b6' und '#abc'
    sind alle moeglich. Alles andere (rgb(), Farbnamen, Leerstring) faellt auf
    den Vorgabewert zurueck – eine ungueltige Farbe im Theme macht die Datei
    fuer PowerPoint unlesbar."""
    s = str(wert or "").strip().lstrip("#")
    if re.fullmatch(r"[0-9a-fA-F]{6}", s):
        return s.upper()
    if re.fullmatch(r"[0-9a-fA-F]{3}", s):
        return "".join(c * 2 for c in s).upper()
    return fallback


def branding_farben() -> dict:
    """Liest die Branding-Werte und leitet daraus die Theme-Farben ab.

    Genommen wird der Akzent aus dem HELL-Modus (``colors_light``), sonst der
    aus dem Dunkel-Modus. Hintergrund und Textfarbe kommen NICHT aus dem
    Branding: die Chat-Oberflaeche ist dunkel, eine Praesentation muss hell
    sein. Uebernommen wird also genau das, was uebertragbar ist – die
    Markenfarbe."""
    cfg = {}
    try:
        from backend.config import config
        states = config.get_skill_states()
        st = states.get("branding") or {}
        if st.get("enabled"):
            cfg = st.get("config") or {}
    except Exception:  # noqa: BLE001
        cfg = {}
    hell = (cfg.get("colors_light") or {}) if isinstance(cfg.get("colors_light"), dict) else {}
    dunkel = (cfg.get("colors") or {}) if isinstance(cfg.get("colors"), dict) else {}
    akzent = _hex(hell.get("accent") or dunkel.get("accent"), STANDARD_AKZENT)
    return {
        "akzent": akzent,
        "firma": str(cfg.get("company_name") or "").strip(),
        "hell": HELL,
        "dunkel": DUNKEL,
        "grau": GRAU,
    }


def _theme_xml(alt: bytes, farben: dict, schrift: str = "Arial") -> bytes:
    """Ersetzt Farb- und Schriftschema im Theme-XML."""
    from lxml import etree

    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    ns = {"a": A}
    root = etree.fromstring(alt)

    def srgb(el, wert):
        """Setzt den Farbwert eines Schema-Slots (dk1/lt1/accent1 …).
        Der Slot kann <a:srgbClr> ODER <a:sysClr> enthalten – letzteres bei
        dk1/lt1 im Standardtemplate ('windowText'/'window'). sysClr wird
        ersetzt, sonst blieben Text- und Hintergrundfarbe unveraendert."""
        for kind in list(el):
            el.remove(kind)
        neu = etree.SubElement(el, f"{{{A}}}srgbClr")
        neu.set("val", wert)

    clr = root.find(".//a:themeElements/a:clrScheme", ns)
    if clr is not None:
        werte = {
            "dk1": farben["dunkel"], "lt1": farben["hell"],
            "dk2": farben["grau"], "lt2": "F3F4F6",
            "accent1": farben["akzent"],
            "accent2": PALETTE[0], "accent3": PALETTE[1], "accent4": PALETTE[2],
            "accent5": PALETTE[3], "accent6": PALETTE[4],
            "hlink": farben["akzent"], "folHlink": farben["grau"],
        }
        for slot, wert in werte.items():
            el = clr.find(f"a:{slot}", ns)
            if el is not None:
                srgb(el, wert)

    fonts = root.find(".//a:themeElements/a:fontScheme", ns)
    if fonts is not None:
        for teil in ("a:majorFont", "a:minorFont"):
            f = fonts.find(teil, ns)
            if f is None:
                continue
            latin = f.find("a:latin", ns)
            if latin is not None:
                latin.set("typeface", schrift)
                # panose/pitchFamily des Standardtemplates gehoeren zu Calibri
                # und wuerden PowerPoint eine falsche Ersatzschrift waehlen
                # lassen.
                for attr in ("panose", "pitchFamily", "charset"):
                    if attr in latin.attrib:
                        del latin.attrib[attr]
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def _patch_theme(pptx_pfad: Path, farben: dict, schrift: str = "Arial") -> None:
    """Schreibt das neue Theme in die .pptx (ZIP wird neu gepackt).

    Es wird in eine TEMPORAERE Datei geschrieben und erst danach umbenannt –
    bricht der Vorgang ab, bleibt die alte (funktionierende) Vorlage stehen
    statt eines halben ZIPs."""
    tmp = pptx_pfad.with_suffix(".tmp.pptx")
    with zipfile.ZipFile(pptx_pfad) as quelle:
        namen = quelle.namelist()
        ziel_themes = [n for n in namen if re.fullmatch(r"ppt/theme/theme\d+\.xml", n)]
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as ziel:
            for eintrag in quelle.infolist():
                daten = quelle.read(eintrag.filename)
                if eintrag.filename in ziel_themes:
                    try:
                        daten = _theme_xml(daten, farben, schrift)
                    except Exception:  # noqa: BLE001
                        pass       # lieber unveraendertes Theme als kaputte Datei
                ziel.writestr(eintrag, daten)
    tmp.replace(pptx_pfad)


def _auf_breitbild_skalieren(prs, faktor: float) -> None:
    """Zieht Platzhalter in Master und Layouts auf die neue Folienbreite.

    DAS IST KEIN FEINSCHLIFF, SONDERN PFLICHT: ``prs.slide_width`` zu setzen
    aendert nur die Folienabmessung – die Platzhalter behalten ihre absoluten
    Positionen aus dem 4:3-Ausgangstemplate. Ohne diese Skalierung endet jede
    Aufzaehlung bei etwa zwei Dritteln der Folienbreite und rechts bleibt ein
    breiter, leerer Streifen. Genau so sah die erste Fassung im PDF-Test aus.

    Skaliert wird nur WAAGERECHT (links + Breite): die Folienhoehe bleibt bei
    6858000 EMU unveraendert, senkrecht passt also alles schon.

    ANGEFASST WERDEN NUR FORMEN MIT EIGENER GEOMETRIE (``spPr/a:xfrm``). Ein
    Layout-Platzhalter ohne eigenes ``xfrm`` ERBT Position und Groesse vom
    gleichnamigen Master-Platzhalter. Wer ihn trotzdem setzt, bekommt zwei
    Fehler auf einmal – gemessen an der ersten Fassung:
      * die Breite wird ZWEIMAL skaliert (Master 8229600 → 10972525, danach
        liest das Layout diesen geerbten Wert und macht 14630400 daraus – mehr
        als die Folie breit ist), und
      * ``top`` fällt auf 0, weil python-pptx beim Anlegen des neuen ``xfrm``
        nur die gesetzte Achse kennt. Im PDF standen die Titel dadurch am
        oberen Folienrand und wurden angeschnitten.
    Geerbte Platzhalter folgen dem Master von allein – man muss sie also gar
    nicht anfassen."""
    def eigene_geometrie(shape) -> bool:
        try:
            return shape._element.spPr.xfrm is not None
        except Exception:  # noqa: BLE001
            return False

    def anpassen(formen):
        for shape in formen:
            if not eigene_geometrie(shape):
                continue
            try:
                if shape.left is None or shape.width is None:
                    continue
                shape.left = int(shape.left * faktor)
                shape.width = int(shape.width * faktor)
            except Exception:  # noqa: BLE001
                continue

    for master in prs.slide_masters:
        anpassen(master.shapes)
        for layout in master.slide_layouts:
            anpassen(layout.shapes)


def _feinschliff(prs) -> None:
    """Zwei Korrekturen am Standardtemplate, die den Unterschied zwischen
    „Office-Vorgabe" und „Vorlage" ausmachen – beide im PDF-Test aufgefallen:

    1. **Titel linksbündig** auf den INHALTS-Layouts. Das Standardtemplate
       zentriert jeden Titel; bei linksbündigem Text darunter wirkt das
       unruhig, und Fließtext-Folien lesen sich schlechter. Die Titelfolie
       bleibt ausdrücklich zentriert – dort ist es die übliche Setzung.
    2. **Abschnittsfolie: Titel über den Zusatztext.** Im Standardtemplate
       liegt der Text-Platzhalter ÜBER dem Titel (y=2906713 gegen 4406900),
       die Überschrift steht also unter ihrer Unterzeile. Die beiden
       y-Positionen werden getauscht.

    Beides schreibt nur in die LAYOUTS – die Folien erben es. Fehlschläge
    werden geschluckt: eine kosmetische Korrektur darf die Vorlage nicht
    kosten."""
    from lxml import etree
    from pptx.enum.shapes import PP_PLACEHOLDER as PH

    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    P = "http://schemas.openxmlformats.org/presentationml/2006/main"

    # Titel-Ausrichtung sitzt im MASTER unter <p:txStyles><p:titleStyle>.
    # Die Ausrichtung eines Folientitels aus dem Layout-Shape heraus zu setzen
    # (paragraphs[i].alignment am Layout-Platzhalter) wirkt NICHT – der Absatz
    # auf der Folie erbt seine Eigenschaften aus diesem Stil, nicht aus dem
    # Textkoerper des Layouts. Genau daran ist die erste Fassung gescheitert
    # (im PDF blieben die Titel zentriert).
    for master in prs.slide_masters:
        try:
            stil = master.element.find(f"{{{P}}}txStyles/{{{P}}}titleStyle")
            if stil is None:
                continue
            lvl1 = stil.find(f"{{{A}}}lvl1pPr")
            if lvl1 is None:
                lvl1 = etree.SubElement(stil, f"{{{A}}}lvl1pPr")
            lvl1.set("algn", "l")
        except Exception:  # noqa: BLE001
            pass

    # …die TITELFOLIE bleibt zentriert. Dafuer bekommt ihr Titel-Platzhalter im
    # Layout eine eigene Listenformatierung, die den Master-Stil ueberstimmt.
    for layout in prs.slide_layouts:
        if (layout.name or "").lower() not in ("titelfolie", "title slide"):
            continue
        for ph in layout.placeholders:
            try:
                if ph.placeholder_format.type not in (PH.TITLE, PH.CENTER_TITLE):
                    continue
                txBody = ph.text_frame._txBody
                lst = txBody.find(f"{{{A}}}lstStyle")
                if lst is None:
                    lst = etree.SubElement(txBody, f"{{{A}}}lstStyle")
                    # lstStyle muss VOR den Absaetzen stehen (Schema-Reihenfolge:
                    # bodyPr, lstStyle, p…) – sonst lehnt PowerPoint die Datei ab.
                    txBody.remove(lst)
                    txBody.insert(1, lst)
                lvl1 = lst.find(f"{{{A}}}lvl1pPr")
                if lvl1 is None:
                    lvl1 = etree.SubElement(lst, f"{{{A}}}lvl1pPr")
                lvl1.set("algn", "ctr")
            except Exception:  # noqa: BLE001
                continue

    for layout in prs.slide_layouts:
        if (layout.name or "").lower() not in ("abschnitt", "section header"):
            continue
        titel = None
        text = None
        for ph in layout.placeholders:
            try:
                typ = ph.placeholder_format.type
            except Exception:  # noqa: BLE001
                continue
            if typ in (PH.TITLE, PH.CENTER_TITLE) and titel is None:
                titel = ph
            elif typ in (PH.BODY, PH.OBJECT, PH.SUBTITLE) and text is None:
                text = ph
        try:
            if titel is not None and text is not None and titel.top > text.top:
                titel.top, text.top = text.top, titel.top
        except Exception:  # noqa: BLE001
            pass


def _akzentbalken(master, akzent: str) -> None:
    """Setzt einen dezenten Balken in Akzentfarbe an den unteren Folienrand.

    Er sitzt im MASTER, damit er auf jeder Folie erscheint und beim Bearbeiten
    nicht versehentlich verschoben werden kann (Master-Formen sind auf der
    Folie nicht anfassbar).

    Gebaut wird das XML von Hand, weil ``MasterShapes`` in python-pptx (1.0.2)
    KEINE ``add_shape``/``add_picture``-Methoden hat – die gibt es nur auf
    Folien. Der oft genutzte Umweg „Form auf einer Wegwerf-Folie erzeugen und
    das Element in den Master verschieben" braucht anschliessend das Loeschen
    dieser Folie (python-pptx hat dafuer keine API) und bricht bei Bildern die
    Beziehung zum Medien-Part. Fuer ein Rechteck ohne Verknuepfung ist direktes
    XML der kuerzere und stabilere Weg."""
    from lxml import etree

    P = "http://schemas.openxmlformats.org/presentationml/2006/main"
    A = "http://schemas.openxmlformats.org/drawingml/2006/main"
    hoehe = 151200          # 0,42 cm in EMU
    oben = HOEHE_16_9 - hoehe

    xml = f"""<p:sp xmlns:p="{P}" xmlns:a="{A}">
  <p:nvSpPr>
    <p:cNvPr id="900" name="Akzentbalken"/>
    <p:cNvSpPr/>
    <p:nvPr/>
  </p:nvSpPr>
  <p:spPr>
    <a:xfrm><a:off x="0" y="{oben}"/><a:ext cx="{BREITE_16_9}" cy="{hoehe}"/></a:xfrm>
    <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
    <a:solidFill><a:srgbClr val="{akzent}"/></a:solidFill>
    <a:ln><a:noFill/></a:ln>
  </p:spPr>
  <p:txBody><a:bodyPr/><a:lstStyle/><a:p/></p:txBody>
</p:sp>"""
    master.shapes.element.append(etree.fromstring(xml))


def _logo_pfad():
    """Pfad zum Branding-Logo (helle Variante bevorzugt) oder None.

    Fuer eine helle Folie ist die HELL-Variante gemeint: das ist die fuer
    hellen Untergrund gemachte Fassung. Fehlt sie, wird die Dunkel-Variante
    genommen – die ist auf Weiss oft unsichtbar, deshalb nur als Rueckfall und
    nur, wenn ueberhaupt eine existiert."""
    try:
        from backend.main import _branding_logo_path
    except Exception:  # noqa: BLE001
        return None
    for variante in ("light", "dark"):
        try:
            p = _branding_logo_path(variante, "compact")
        except Exception:  # noqa: BLE001
            p = None
        if p and Path(p).exists():
            return Path(p)
    return None


def erzeuge(ziel: Path = None) -> Path:
    """Erzeugt die neutrale Vorlage und gibt ihren Pfad zurueck."""
    from pptx import Presentation
    from pptx.util import Emu

    ziel = Path(ziel) if ziel else (VORLAGEN_DIR / STANDARD_NAME)
    ziel.parent.mkdir(parents=True, exist_ok=True)
    farben = branding_farben()

    prs = Presentation()
    # 16:9 – der eigentliche Grund, warum die alten Decks „alt" aussahen.
    alt_breite = prs.slide_width
    prs.slide_width = Emu(BREITE_16_9)
    prs.slide_height = Emu(HOEHE_16_9)
    # …und die Platzhalter mitziehen, sonst bleibt rechts ein Drittel leer.
    if alt_breite and alt_breite != BREITE_16_9:
        _auf_breitbild_skalieren(prs, BREITE_16_9 / float(alt_breite))

    # Layouts deutsch benennen (nur die bekannten; unbekannte bleiben).
    for layout in prs.slide_layouts:
        neu = LAYOUT_NAMEN.get(layout.name)
        if neu:
            layout.name = neu

    _feinschliff(prs)
    # NACH dem Skalieren: der Balken wird schon in 16:9-Koordinaten gebaut und
    # duerfte nicht noch einmal gestreckt werden.
    _akzentbalken(prs.slide_masters[0], farben["akzent"])
    # Das LOGO kommt NICHT in den Master, sondern beim Erzeugen auf die
    # Titelfolie (main.py). Zwei Gruende: MasterShapes kann keine Bilder
    # aufnehmen (die Medien-Beziehung haengt an der Folie, nicht am Master),
    # und ein Logo auf JEDER Folie ist im Corporate-Design die Ausnahme –
    # ueblich ist gross auf dem Titel, dezent oder gar nicht danach.
    prs.save(str(ziel))
    # Theme (Farben + Schrift) erst NACH dem Speichern – python-pptx schreibt
    # die Datei komplett neu und wuerde einen vorher gepatchten Theme-Part
    # wieder mit dem Original ueberschreiben.
    _patch_theme(ziel, farben)
    return ziel


def sicherstellen(pfad: Path = None) -> Path:
    """Gibt die Standardvorlage zurueck und erzeugt sie beim ersten Mal.

    Bewusst KEINE Neuerzeugung bei jedem Aufruf: die Datei darf von Hand
    ausgetauscht werden (echte Firmenvorlage). Wer die Branding-Farben neu
    einziehen will, loescht sie oder ruft ``erzeuge()`` auf."""
    ziel = Path(pfad) if pfad else (VORLAGEN_DIR / STANDARD_NAME)
    if ziel.exists() and ziel.stat().st_size > 0:
        return ziel
    return erzeuge(ziel)


def verfuegbare() -> list:
    """Alle hinterlegten Vorlagen (Dateinamen), Standardvorlage zuerst."""
    try:
        dateien = sorted(p.name for p in VORLAGEN_DIR.glob("*.pptx")
                         if not p.name.startswith(".") and not p.name.endswith(".tmp.pptx"))
    except Exception:  # noqa: BLE001
        return []
    if STANDARD_NAME in dateien:
        dateien.remove(STANDARD_NAME)
        dateien.insert(0, STANDARD_NAME)
    return dateien


def loese_vorlage(name: str = "") -> Path:
    """Loest einen Vorlagennamen auf; leer = Standardvorlage.

    Pfadanteile werden VERWORFEN (nur der Dateiname zaehlt): der Name kommt aus
    einem LLM-Aufruf, und '../../data/settings.json' darf hier nicht landen.
    Eine unbekannte Vorlage faellt auf die Standardvorlage zurueck, statt den
    Lauf scheitern zu lassen – ein Deck im Hausdesign ist besser als kein Deck.
    """
    if not name:
        return sicherstellen()
    sauber = Path(str(name)).name
    if not sauber.lower().endswith(".pptx"):
        sauber += ".pptx"
    kandidat = VORLAGEN_DIR / sauber
    if kandidat.exists():
        return kandidat
    return sicherstellen()
