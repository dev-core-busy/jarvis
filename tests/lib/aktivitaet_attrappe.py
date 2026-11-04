"""Attrappe fuer ``main._aktivitaet`` in Pruefstaenden, die Endpunkte aus
main.py SCHNEIDEN und ausfuehren.

Seit 2026-11-04 rufen die aendernden Endpunkte ``_aktivitaet(...)`` (siehe
backend/aktivitaet.py). Ein Pruefstand, der sich seinen Namensraum selbst baut,
kennt den Namen nicht und stirbt mit NameError – im Register steht genau diese
Klasse ("eine neue Modulvariable in einer geschnittenen Funktion bricht jeden
fremden Harness").

Die Attrappe ZEICHNET AUF statt zu schreiben (kein echtes Protokoll aus einem
Test) und hat die ECHTE Signatur: ``signatur_passt()`` vergleicht sie am
Syntaxbaum mit main.py, damit eine Aenderung dort nicht unbemerkt eine
bequemere Attrappe zuruecklaesst (Register: Attrappen bilden die echte
Signatur nach). Die eigentliche Pruefung des Protokolls steht in
tests/test_aktivitaet.py.
"""
import ast
from pathlib import Path

MAIN = Path(__file__).resolve().parent.parent.parent / "backend" / "main.py"


def aktivitaet_attrappe(aufzeichnung=None):
    """Liefert eine Funktion mit der Signatur von ``main._aktivitaet``; jeder
    Aufruf landet als dict in ``aufzeichnung`` (falls uebergeben)."""
    def _aktivitaet(user, bereich, aktion, objekt="", *, rechte=False, **details):
        if aufzeichnung is not None:
            aufzeichnung.append({"user": user, "bereich": bereich, "aktion": aktion,
                                 "objekt": objekt, "rechte": rechte, "details": details})
    return _aktivitaet


def signatur_passt() -> bool:
    """Stimmt die Attrappe noch mit der echten Funktion ueberein?"""
    baum = ast.parse(MAIN.read_text(encoding="utf-8"))
    for n in baum.body:
        if isinstance(n, ast.FunctionDef) and n.name == "_aktivitaet":
            a = n.args
            return ([x.arg for x in a.args] == ["user", "bereich", "aktion", "objekt"]
                    and [x.arg for x in a.kwonlyargs] == ["rechte"]
                    and a.kwarg is not None and a.vararg is None)
    return False
