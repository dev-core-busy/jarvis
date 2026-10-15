"""Einzelne Zellen einer .xlsx aendern, ohne die Mappe neu zu bauen.

**WARUM ES DAS GIBT.** `openpyxl` kann nicht in-place patchen: `load_workbook`
parst die ganze Mappe in ein Objektmodell, `save()` serialisiert sie vollstaendig
neu. Alles, was die Bibliothek nicht versteht, faellt dabei heraus – Diagramme,
Bilder, Pivot-Tabellen, Druckeinstellungen, Blatt-Beziehungen. An der echten
Produktionsdatei gemessen (2026-08-24): von 16 ZIP-Teilen kamen 10 zurueck, und
`xl/workbook.xml` schrumpfte von 2277 auf 833 Byte. Fuer diese Datei war das
folgenlos (Excel baut `calcChain` und `sharedStrings` selbst neu), aber eine
Mappe mit einem Diagramm verliert es – dafuer gibt es bisher nur eine Warnung.

**DER ANSATZ.** Eine .xlsx ist ein ZIP. Es wird ein NEUES ZIP geschrieben, in das
jeder Teil **byte-gleich** uebernommen wird; nur drei Teile werden angefasst:

* ``xl/worksheets/sheetN.xml`` – dort werden die Zielzellen ersetzt, per gezielter
  Textmanipulation. **Bewusst kein ElementTree**: die Blatt-XML echter Dateien
  traegt ``mc:Ignorable`` und mehrere Namespaces (``x14ac``, ``xr``, ``xr2``,
  ``xr3``); ein Rundlauf durch einen XML-Serialisierer aendert Praefixe,
  Attributreihenfolge und Selbstschliessung – und damit womoeglich mehr, als hier
  gewollt ist. Was nicht angefasst wird, bleibt Zeichen fuer Zeichen stehen.
* ``xl/calcChain.xml`` – wird ENTFERNT (samt Eintrag in ``[Content_Types].xml``
  und in ``xl/_rels/workbook.xml.rels``; eine Beziehung auf einen fehlenden Teil
  laesst Excel die Datei als beschaedigt melden). Die Kette ist ein
  Berechnungs-Cache und wird neu aufgebaut.
* ``xl/workbook.xml`` – ``calcPr`` bekommt ``fullCalcOnLoad="1"``. **Ohne das ist
  der Patch gefaehrlich statt nuetzlich:** die gecachten ``<v>``-Werte der
  Formelzellen, die auf eine geaenderte Zelle zeigen, stehen sonst veraltet in
  der Datei und Excel zeigt sie an.

**GRENZE, die fail-closed behandelt wird: shared formulas.** In echten Mappen ist
die Formel einer Zeile als Gruppe gespeichert – eine MASTER-Zelle
(``<f t="shared" ref="B3:BL3" si="0">…</f>``) und viele Folger
(``<f t="shared" si="0"/>``). Wer die Master-Zelle ueberschreibt, nimmt allen
Folgern ihre Definition. Die echte Datei hat 435 bzw. 492 solcher Zellen.
Ein Schreibversuch auf eine Master-Zelle wird deshalb **abgelehnt und benannt**,
nicht stillschweigend ausgefuehrt.
"""

from __future__ import annotations

import re
import shutil
import zipfile
from pathlib import Path

# Teile, die nie unveraendert uebernommen werden.
_CALCCHAIN = "xl/calcChain.xml"
_MAX_SPALTE = 16384          # XFD
# Abstand zur bisherigen Tabellengrenze, ab dem ein Schreibziel im Bericht
# auffaellt. GRUND (Register, tabellen.py): jedes dreibuchstabige Wort ist eine
# gueltige Spaltenbezeichnung – "Ort" ergibt Spalte 10.628. Ein Vertipper
# schreibt damit klaglos ins Nichts, und niemand sieht es. Ablehnen waere
# falsch (die Spalte gibt es), Verschweigen auch – also benennen.
_WARN_SPALTEN = 50
_WARN_ZEILEN = 1000


class PatchFehler(Exception):
    """Fachlicher Fehlschlag mit Text fuer das Werkzeug-Ergebnis."""


# ── Adressen ────────────────────────────────────────────────────────────────

_ADR = re.compile(r"^([A-Za-z]{1,3})([0-9]{1,7})$")


def spalte_zu_index(b: str) -> int:
    """``"A"`` -> 1. Nur ASCII-Buchstaben, hoechstens drei, im Excel-Bereich.

    Dieselbe Haerte wie in ``tabellen.py``: dort hat ``_buchstabe_zu_index``
    fuer das Wort "Unbekannt" die Spalte 4.498.495.991.152 geliefert, weil jedes
    Wort ``.isalpha()`` ist. Ein Umlaut ist es auch – deshalb ``isascii()``.
    """
    b = (b or "").strip().upper()
    if not b or len(b) > 3 or not b.isascii() or not b.isalpha():
        raise PatchFehler("Ungueltige Spaltenangabe: %r" % b)
    n = 0
    for z in b:
        n = n * 26 + (ord(z) - 64)
    if not 1 <= n <= _MAX_SPALTE:
        raise PatchFehler("Spalte %s liegt ausserhalb des Excel-Bereichs" % b)
    return n


def index_zu_spalte(n: int) -> str:
    """1 -> ``"A"``."""
    if not 1 <= n <= _MAX_SPALTE:
        raise PatchFehler("Spaltenindex %d liegt ausserhalb" % n)
    s = ""
    while n:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def adresse_teilen(adr: str) -> tuple:
    """``"B12"`` -> ``("B", 12, 2)``."""
    m = _ADR.match((adr or "").strip())
    if not m:
        raise PatchFehler("Ungueltige Zelladresse: %r" % adr)
    zeile = int(m.group(2))
    if zeile < 1 or zeile > 1048576:
        raise PatchFehler("Zeile %d liegt ausserhalb des Excel-Bereichs" % zeile)
    sp = m.group(1).upper()
    return (sp, zeile, spalte_zu_index(sp))


# ── XML-Bausteine ───────────────────────────────────────────────────────────

def x(text: str) -> str:
    """Maskiert Text fuer XML – auch Anfuehrungszeichen (Attribute).

    ``xml.sax.saxutils.escape`` laesst ``"`` stehen; im Outlook-Manifest hat
    genau das ein Attribut zerlegt. Eine Maskierung fuer Text UND Attribute.
    """
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&#39;"))


_STEUER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _zelle_xml(adr: str, wert, stil: str | None) -> str:
    """Die neue ``<c>``-Zelle.

    * Formel (Text mit ``=``): ``<f>`` OHNE ``<v>`` – der Wert kommt aus der
      Neuberechnung; ein mitgeschriebener alter Wert waere eine Behauptung.
    * Text: ``t="inlineStr"``. **Bewusst kein sharedString**: dann muesste
      ``xl/sharedStrings.xml`` samt aller Indizes umgeschrieben werden, und die
      Zusage "alles andere bleibt byte-gleich" waere weg.
    * Zahl/Bool: ``<v>``; ``None``/``""`` leert die Zelle (nur Stil bleibt).

    ``stil`` ist das ``s``-Attribut der ALTEN Zelle und wird uebernommen –
    sonst verliert die Zelle ihr Zahlenformat, und aus einem Datum wird eine
    fuenfstellige Zahl.
    """
    sa = ' s="%s"' % x(stil) if stil else ""
    if wert is None or (isinstance(wert, str) and wert == ""):
        return '<c r="%s"%s/>' % (adr, sa)
    if isinstance(wert, bool):
        return '<c r="%s"%s t="b"><v>%d</v></c>' % (adr, sa, 1 if wert else 0)
    if isinstance(wert, (int, float)):
        return '<c r="%s"%s><v>%s</v></c>' % (adr, sa, repr(wert)
                                              if isinstance(wert, float) else wert)
    text = _STEUER.sub("", str(wert))
    if text.startswith("="):
        formel = text[1:].strip()
        if not formel:
            raise PatchFehler("Leere Formel in %s" % adr)
        return '<c r="%s"%s><f>%s</f></c>' % (adr, sa, x(formel))
    # Fuehrende/abschliessende Leerzeichen gehen ohne xml:space verloren.
    raum = ' xml:space="preserve"' if text != text.strip() else ""
    return ('<c r="%s"%s t="inlineStr"><is><t%s>%s</t></is></c>'
            % (adr, sa, raum, x(text)))


# ── Blatt finden ────────────────────────────────────────────────────────────

def blaetter(z: zipfile.ZipFile) -> dict:
    """``{Blattname: ZIP-Pfad}`` – ueber workbook.xml und dessen Beziehungen.

    Der Weg ist Pflicht: die Reihenfolge in ``xl/worksheets/`` sagt NICHTS ueber
    die Blattreihenfolge, und ``sheet1.xml`` ist nicht zwingend das erste Blatt.
    """
    wb = z.read("xl/workbook.xml").decode("utf-8", "replace")
    rels = z.read("xl/_rels/workbook.xml.rels").decode("utf-8", "replace")
    ziel = {}
    for m in re.finditer(r'<Relationship\b[^>]*>', rels):
        t = m.group(0)
        rid = re.search(r'Id="([^"]+)"', t)
        tgt = re.search(r'Target="([^"]+)"', t)
        if rid and tgt:
            p = tgt.group(1).lstrip("/")
            ziel[rid.group(1)] = p if p.startswith("xl/") else "xl/" + p
    raus = {}
    for m in re.finditer(r"<sheet\b[^>]*/?>", wb):
        t = m.group(0)
        nm = re.search(r'name="([^"]*)"', t)
        rid = re.search(r'r:id="([^"]+)"', t)
        if nm and rid and rid.group(1) in ziel:
            raus[_entmaskieren(nm.group(1))] = ziel[rid.group(1)]
    return raus


def blaetter_von(datei: Path) -> dict:
    """``blaetter()`` fuer einen Pfad – die Reihenfolge ist die der Mappe.

    Wichtig fuer "Standard: erstes Blatt": ``xl/worksheets/sheet1.xml`` ist NICHT
    zwingend das erste Blatt der Mappe; verlaesslich ist nur die Reihenfolge der
    ``<sheet>``-Elemente in ``xl/workbook.xml``.
    """
    with zipfile.ZipFile(Path(datei)) as z:
        return blaetter(z)


def _entmaskieren(s: str) -> str:
    return (s.replace("&quot;", '"').replace("&#39;", "'").replace("&gt;", ">")
            .replace("&lt;", "<").replace("&amp;", "&"))


# ── Blatt-XML patchen ───────────────────────────────────────────────────────

def _zeilen_spanne(xml: str) -> list:
    """Alle ``<row>``-Bloecke als ``(zeilennummer, start, ende)``."""
    raus = []
    for m in re.finditer(r'<row\b[^>]*\br="(\d+)"[^>]*(?:/>|>)', xml):
        nr = int(m.group(1))
        if m.group(0).endswith("/>"):
            raus.append((nr, m.start(), m.end()))
            continue
        ende = xml.find("</row>", m.end())
        if ende < 0:
            raise PatchFehler("Blatt-XML beschaedigt: <row r=\"%d\"> ohne Ende" % nr)
        raus.append((nr, m.start(), ende + len("</row>")))
    return raus


_SHARED_MASTER = re.compile(r'<f\b[^>]*\bt="shared"[^>]*\bref="')


def patch_blatt(xml: str, werte: dict) -> tuple:
    """Ersetzt Zellen in einer Blatt-XML. Gibt ``(xml, bericht)`` zurueck.

    ``werte``: ``{"B12": wert}``. Der Rest der Datei bleibt unveraendert – auch
    Formatierung, bedingte Formatierung, Kommentar-Verweise, Autofilter.
    """
    geschrieben, angelegt, abgelehnt = [], [], []
    # Zellen je Zeile buendeln: eine Zeile wird EINMAL angefasst.
    je_zeile: dict = {}
    for adr, wert in werte.items():
        sp, zeile, idx = adresse_teilen(adr)
        je_zeile.setdefault(zeile, []).append((idx, sp + str(zeile), wert))

    zeilen = {nr: (a, b) for nr, a, b in _zeilen_spanne(xml)}
    max_sp, max_zeile = 0, 0

    # Von HINTEN nach vorn ersetzen, damit frueher berechnete Positionen gueltig
    # bleiben (ein Ersatz aendert die Laenge der Datei).
    for zeile in sorted(je_zeile.keys(), reverse=True):
        eintraege = sorted(je_zeile[zeile])
        max_zeile = max(max_zeile, zeile)
        max_sp = max(max_sp, max(i for i, _, _ in eintraege))
        if zeile in zeilen:
            a, b = zeilen[zeile]
            block = xml[a:b]
            neu, g, ab = _zeile_patchen(block, eintraege)
            geschrieben.extend(g)
            abgelehnt.extend(ab)
            xml = xml[:a] + neu + xml[b:]
        else:
            block = _neue_zeile(zeile, eintraege)
            xml = _zeile_einsetzen(xml, zeile, block, zeilen)
            angelegt.append(zeile)
            geschrieben.extend(adr for _, adr, _ in eintraege)

    weit = _weit_draussen(xml, je_zeile)
    xml = _dimension_erweitern(xml, max_sp, max_zeile)
    return xml, {"geschrieben": geschrieben, "neue_zeilen": angelegt,
                 "abgelehnt": abgelehnt, "weit_draussen": weit}


def _weit_draussen(xml: str, je_zeile: dict) -> list:
    """Adressen, die weit hinter der bisherigen Tabellengrenze liegen.

    Kein Fehler – ein neuer Bereich kann gewollt sein. Aber ein Ziel 10.000
    Spalten hinter den Daten ist fast immer ein Vertipper, und ohne diesen
    Hinweis faellt er niemandem auf: die Datei ist gueltig, die Zelle steht da,
    nur sieht sie kein Mensch.
    """
    m = re.search(r'<dimension\s+ref="[A-Z]+\d+:([A-Z]+)(\d+)"\s*/>', xml)
    if not m:
        return []
    sp_max, z_max = spalte_zu_index(m.group(1)), int(m.group(2))
    raus = []
    for zeile, eintraege in je_zeile.items():
        for idx, adr, _ in eintraege:
            if idx > sp_max + _WARN_SPALTEN or zeile > z_max + _WARN_ZEILEN:
                raus.append(adr)
    return sorted(raus)


def _zelle_finden(block: str, adr: str) -> tuple:
    """``(start, ende, stil, alt)`` der Zelle ``adr`` im Zeilenblock, sonst
    ``(-1, -1, None, "")``."""
    for m in re.finditer(r'<c\b[^>]*\br="([A-Z]{1,3}\d+)"[^>]*(?:/>|>)', block):
        if m.group(1) != adr:
            continue
        stil = re.search(r'\bs="([^"]*)"', m.group(0))
        if m.group(0).endswith("/>"):
            return (m.start(), m.end(), stil.group(1) if stil else None, m.group(0))
        e = block.find("</c>", m.end())
        if e < 0:
            raise PatchFehler("Blatt-XML beschaedigt: <c r=\"%s\"> ohne Ende" % adr)
        e += len("</c>")
        return (m.start(), e, stil.group(1) if stil else None, block[m.start():e])
    return (-1, -1, None, "")


def _zeile_patchen(block: str, eintraege: list) -> tuple:
    """Ersetzt/ergaenzt Zellen in EINEM ``<row>``-Block."""
    geschrieben, abgelehnt = [], []
    # Ebenfalls von hinten, gleiche Begruendung wie oben.
    for idx, adr, wert in sorted(eintraege, reverse=True):
        a, b, stil, alt = _zelle_finden(block, adr)
        if a >= 0 and _SHARED_MASTER.search(alt):
            # FAIL-CLOSED: diese Zelle definiert die Formel einer ganzen Gruppe.
            # Sie zu ueberschreiben nimmt allen Folgezellen ihre Definition –
            # das Ergebnis waere eine Mappe, die Excel oeffnet und in der
            # Dutzende Zellen leer bleiben.
            abgelehnt.append(adr)
            continue
        neu = _zelle_xml(adr, wert, stil)
        if a >= 0:
            block = block[:a] + neu + block[b:]
        else:
            block = _zelle_einsetzen(block, idx, neu)
        geschrieben.append(adr)
    return block, geschrieben, abgelehnt


def _zelle_einsetzen(block: str, idx: int, neu: str) -> str:
    """Setzt eine neue Zelle an die richtige Stelle der Zeile.

    Die ``r``-Attribute innerhalb einer Zeile muessen aufsteigend sein; Excel
    meldet eine Datei mit falscher Reihenfolge als beschaedigt.
    """
    letzte_ende = block.find(">") + 1          # hinter <row …>
    for m in re.finditer(r'<c\b[^>]*\br="([A-Z]{1,3})(\d+)"[^>]*(?:/>|>)', block):
        if spalte_zu_index(m.group(1)) > idx:
            return block[:m.start()] + neu + block[m.start():]
        if m.group(0).endswith("/>"):
            letzte_ende = m.end()
        else:
            e = block.find("</c>", m.end())
            letzte_ende = (e + len("</c>")) if e >= 0 else m.end()
    return block[:letzte_ende] + neu + block[letzte_ende:]


def _neue_zeile(zeile: int, eintraege: list) -> str:
    zellen = "".join(_zelle_xml(adr, wert, None)
                     for _, adr, wert in sorted(eintraege))
    return '<row r="%d">%s</row>' % (zeile, zellen)


def _zeile_einsetzen(xml: str, zeile: int, block: str, zeilen: dict) -> str:
    """Setzt eine neue ``<row>`` in aufsteigender Reihenfolge ein."""
    nach = sorted(nr for nr in zeilen if nr > zeile)
    if nach:
        return xml[:zeilen[nach[0]][0]] + block + xml[zeilen[nach[0]][0]:]
    i = xml.find("</sheetData>")
    if i < 0:
        # Ein leeres <sheetData/> hat kein Endtag.
        m = re.search(r"<sheetData\s*/>", xml)
        if not m:
            raise PatchFehler("Blatt-XML ohne sheetData")
        return xml[:m.start()] + "<sheetData>" + block + "</sheetData>" + xml[m.end():]
    return xml[:i] + block + xml[i:]


def _dimension_erweitern(xml: str, max_sp: int, max_zeile: int) -> str:
    """Zieht ``<dimension ref="A1:…"/>`` nach, wenn ausserhalb geschrieben wurde.

    Excel repariert eine zu kleine Dimension beim Oeffnen still, andere Programme
    (LibreOffice, pandas) lesen sie aber als Bereichsgrenze – dort fehlten die
    neuen Zellen dann.
    """
    m = re.search(r'<dimension\s+ref="([A-Z]+)(\d+):([A-Z]+)(\d+)"\s*/>', xml)
    if not m:
        return xml
    sp2, z2 = spalte_zu_index(m.group(3)), int(m.group(4))
    if max_sp <= sp2 and max_zeile <= z2:
        return xml
    neu = '<dimension ref="%s%s:%s%d"/>' % (
        m.group(1), m.group(2), index_zu_spalte(max(sp2, max_sp)),
        max(z2, max_zeile))
    return xml[:m.start()] + neu + xml[m.end():]


# ── workbook.xml / Content_Types / rels ─────────────────────────────────────

def _voll_neuberechnen(wb_xml: str) -> str:
    """``fullCalcOnLoad="1"`` in ``calcPr`` – Excel rechnet beim Oeffnen neu.

    Ohne das bleiben die gecachten Werte der Formelzellen stehen, die auf eine
    geaenderte Zelle zeigen: die Datei zeigte dann alte Summen zu neuen Zahlen.
    """
    m = re.search(r"<calcPr\b[^>]*/>", wb_xml)
    if m:
        t = m.group(0)
        if "fullCalcOnLoad" in t:
            t = re.sub(r'fullCalcOnLoad="[^"]*"', 'fullCalcOnLoad="1"', t)
        else:
            t = t[:-2] + ' fullCalcOnLoad="1"/>'
        return wb_xml[:m.start()] + t + wb_xml[m.end():]
    i = wb_xml.find("</workbook>")
    if i < 0:
        return wb_xml
    return wb_xml[:i] + '<calcPr fullCalcOnLoad="1"/>' + wb_xml[i:]


def _ohne_calcchain(text: str) -> str:
    """Entfernt Content-Types-Override bzw. Beziehung auf calcChain.xml."""
    text = re.sub(r'<Override\b[^>]*calcChain\.xml[^>]*/>', "", text)
    return re.sub(r'<Relationship\b[^>]*calcChain\.xml[^>]*/>', "", text)


# ── Hauptfunktion ───────────────────────────────────────────────────────────

def patch_datei(quelle: Path, ziel: Path, aenderungen: dict) -> dict:
    """Schreibt ``ziel`` als Kopie von ``quelle`` mit geaenderten Zellen.

    ``aenderungen``: ``{Blattname: {"B12": wert, …}}``.
    Rueckgabe: ``{"geschrieben": [...], "abgelehnt": [...], "neue_zeilen": {...},
    "uebernommen": n, "erhalten": [Teile, die openpyxl verloren haette]}``.

    Wirft ``PatchFehler`` mit Klartext – der Aufrufer gibt ihn 1:1 weiter.
    """
    quelle, ziel = Path(quelle), Path(ziel)
    if not quelle.is_file():
        raise PatchFehler("Quelldatei nicht gefunden: %s" % quelle.name)
    if not zipfile.is_zipfile(quelle):
        raise PatchFehler("%s ist keine .xlsx (kein ZIP-Container)." % quelle.name)

    bericht = {"geschrieben": [], "abgelehnt": [], "neue_zeilen": {},
               "weit_draussen": [], "uebernommen": 0, "blaetter": []}
    tmp = ziel.with_suffix(ziel.suffix + ".patch.tmp")
    try:
        with zipfile.ZipFile(quelle) as q:
            karte = blaetter(q)
            for name in aenderungen:
                if name not in karte:
                    raise PatchFehler(
                        "Blatt '%s' gibt es nicht. Vorhanden: %s"
                        % (name, ", ".join(sorted(karte)) or "keines"))
            neu_teile: dict = {}
            for name, werte in aenderungen.items():
                if not werte:
                    continue
                pfad = karte[name]
                try:
                    roh = q.read(pfad).decode("utf-8")
                except KeyError as e:
                    raise PatchFehler("Blatt-Teil %s fehlt im Container" % pfad) from e
                gepatcht, b = patch_blatt(roh, werte)
                neu_teile[pfad] = gepatcht.encode("utf-8")
                bericht["geschrieben"].extend("%s!%s" % (name, a)
                                              for a in b["geschrieben"])
                bericht["abgelehnt"].extend("%s!%s" % (name, a)
                                            for a in b["abgelehnt"])
                bericht["weit_draussen"].extend("%s!%s" % (name, a)
                                                for a in b.get("weit_draussen", []))
                if b["neue_zeilen"]:
                    bericht["neue_zeilen"][name] = sorted(b["neue_zeilen"])
                bericht["blaetter"].append(name)

            if not neu_teile:
                raise PatchFehler("Keine Aenderung angegeben.")

            # calcChain entfernen; workbook.xml und die zwei Verweis-Dateien
            # nachziehen.
            wb = q.read("xl/workbook.xml").decode("utf-8")
            neu_teile["xl/workbook.xml"] = _voll_neuberechnen(wb).encode("utf-8")
            for p in ("[Content_Types].xml", "xl/_rels/workbook.xml.rels"):
                try:
                    t = q.read(p).decode("utf-8")
                except KeyError:
                    continue
                neu_teile[p] = _ohne_calcchain(t).encode("utf-8")

            with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as w:
                for info in q.infolist():
                    if info.filename == _CALCCHAIN:
                        continue
                    if info.filename in neu_teile:
                        w.writestr(info.filename, neu_teile[info.filename])
                        continue
                    # BYTE-GLEICH uebernehmen – das ist der ganze Zweck.
                    w.writestr(info, q.read(info.filename))
                    bericht["uebernommen"] += 1
        # Erst nach vollstaendigem Schreiben an den Zielort (halbe Datei =
        # Datei, die Excel als beschaedigt meldet).
        shutil.move(str(tmp), str(ziel))
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    return bericht


def teile(datei: Path) -> set:
    """Die ZIP-Teile einer Mappe – fuer Vergleiche und Berichte."""
    with zipfile.ZipFile(Path(datei)) as z:
        return {i.filename for i in z.infolist()}
