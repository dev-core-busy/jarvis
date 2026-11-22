"""Quelltext-Ausschnitte und Zeilenversaetze in LINEARER Zeit - fuer die Waechter.

WARUM (2026-11-22): die zwei langsamsten Python-Waechter verbrachten ihre Zeit
nicht mit Pruefen, sondern mit Zeilenzaehlen.

  * ``ast.get_source_segment`` zerlegt bei JEDEM Aufruf die ganze Quelle bis
    zur Endzeile des Knotens neu in Zeilen (Regex ueber den Text). Ueber
    ``backend/main.py`` (1,6 MB) und ein paar tausend Knoten ist das
    quadratisch: ``test_anhang_bild_mime`` 77,7 s, davon 90 % in dieser
    Zerlegung - mit einmal gebautem Zeilenindex 1,1 s, Ausgabe identisch.
  * Kommentar-Entferner rechneten den Versatz jedes Kommentars als
    ``sum(len(z) for z in zeilen[:n])`` - je Kommentar einmal ueber alle
    Zeilen davor: ``test_benutzer_pfade`` 60,3 s -> 4,6 s.

Und weil jede Gegenprobe ihren Waechter je Probe neu startet, zahlt sie diese
Zeit einmal pro Probe.

``segment(quelle, knoten, padded=False)`` liefert dasselbe wie
``ast.get_source_segment`` - Zeichen fuer Zeichen, auch fuer ``\\r``, ``\\f``
und Mehrbyte-Zeichen (die Spalten im AST sind UTF-8-Bytes). Die Zeilen
werden je Quelle EINMAL zerlegt und fuer die letzten Quellen behalten.

``ZeilenVersatz(zeilen, zusatz=0)(k)`` ist ``sum(len(z) + zusatz for z in
zeilen[:k])`` - mit derselben Slice-Bedeutung, aber aus einer einmal
gebauten Tabelle.

Waechter: ``tests/test_waechter_tempo.py`` (direkte Aufrufe von
``ast.get_source_segment`` und die quadratische Summe sind in ``tests/``
gesperrt).
"""
import ast
import re

# Dieselbe Zerlegung wie der Parser (und ``ast.get_source_segment``):
# Zeilenende ist \r\n, \n oder \r - NICHT \f oder die anderen Zeichen, die
# ``str.splitlines`` zusaetzlich trennt.
_ZEILE = re.compile(r"(.*?(?:\r\n|\n|\r|$))")

# Wenige Quellen gleichzeitig: ein Waechter liest meist eine bis drei Dateien.
# Mehr zu behalten kostet nur Speicher (je Eintrag eine Kopie der Zeilen).
_GROESSE = 8
_ablage: dict = {}


def _zerlegen(quelle: str) -> list:
    """Alle Zeilen wie ``ast._splitlines_no_ff`` (ohne Zeilenbegrenzung)."""
    zerleger = getattr(ast, "_splitlines_no_ff", None)
    if zerleger is not None:
        return zerleger(quelle)
    return [m[0] for m in _ZEILE.finditer(quelle)]


def zeilen(quelle: str) -> list:
    """Zeilen der Quelle (mit Zeilenende), je Quelle nur einmal zerlegt.

    Die Liste wird geteilt - wer sie veraendern will, kopiert sie vorher.
    """
    gefunden = _ablage.get(quelle)
    if gefunden is None:
        gefunden = _zerlegen(quelle)
        if len(_ablage) >= _GROESSE:
            _ablage.pop(next(iter(_ablage)))
        _ablage[quelle] = gefunden
    return gefunden


def _auffuellen(text: str) -> str:
    """Wie ``ast._pad_whitespace``: alles ausser \\f und \\t wird Leerzeichen."""
    return "".join(c if c in "\f\t" else " " for c in text)


def segment(quelle, knoten, *, padded=False):
    """Gleichwertig zu ``ast.get_source_segment(quelle, knoten, padded=...)``."""
    try:
        if knoten.end_lineno is None or knoten.end_col_offset is None:
            return None
        anfang = knoten.lineno - 1
        ende = knoten.end_lineno - 1
        spalte = knoten.col_offset
        end_spalte = knoten.end_col_offset
    except AttributeError:
        return None
    if anfang < 0 or ende < 0 or not isinstance(quelle, str):
        # Negative Indizes zaehlen in der begrenzten Liste der Bibliothek von
        # einem anderen Ende als in der vollen hier - solche Knoten (und
        # Nicht-Text) gehen an das Original, statt still abzuweichen.
        return ast.get_source_segment(quelle, knoten, padded=padded)
    alle = zeilen(quelle)
    if ende >= len(alle):
        # Dieselbe Ausnahme wie die Bibliothek, nicht eine eigene.
        return ast.get_source_segment(quelle, knoten, padded=padded)
    if ende == anfang:
        return alle[anfang].encode()[spalte:end_spalte].decode()
    if padded:
        polster = _auffuellen(alle[anfang].encode()[:spalte].decode())
    else:
        polster = ""
    erste = polster + alle[anfang].encode()[spalte:].decode()
    letzte = alle[ende].encode()[:end_spalte].decode()
    return "".join([erste, *alle[anfang + 1:ende], letzte])


class ZeilenVersatz:
    """``versatz(k) == sum(len(z) + zusatz for z in zeilen[:k])``, Tabelle einmal gebaut.

    ``zusatz=1`` fuer Zeilen aus ``text.split("\\n")`` (das Trennzeichen fehlt
    in den Zeilen), ``zusatz=0`` fuer ``splitlines(keepends=True)``.
    """

    def __init__(self, zeilen_liste, zusatz=0):
        self._anzahl = len(zeilen_liste)
        tabelle = [0]
        for z in zeilen_liste:
            tabelle.append(tabelle[-1] + len(z) + zusatz)
        self._tabelle = tabelle

    def __call__(self, k):
        # len(range(n)[:k]) ist genau die Laenge von zeilen[:k] - auch fuer
        # negative und zu grosse k.
        return self._tabelle[len(range(self._anzahl)[:k])]
