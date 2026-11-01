"""Das ECHTE ``main._json_objekt`` fuer Pruefstaende, die Endpunkte schneiden.

WARUM (2026-11-01): seit dem Code-Review lesen rund 150 Endpunkte ihren Rumpf
ueber ``await _json_objekt(request)``. Pruefstaende, die einen Endpunkt aus
``main.py`` in einen eigenen Namensraum schneiden, kennen den Namen nicht –
und zwei davon sahen das nicht einmal als ``NameError``: der Endpunkt fing ihn
mit seinem breiten ``except`` und meldete "query fehlt" bzw. "Kein Dateipfad
angegeben", also einen Fehler, den es im Produkt nicht gibt.

Geliefert wird die Funktion aus dem Syntaxbaum von ``main.py`` – keine
Attrappe, damit eine kuenftige Aenderung des Helfers in jedem Pruefstand
ankommt (Register: "eine Attrappe mit weniger als dem Original stirbt beim
naechsten Symbol").

    sys.path.insert(0, str(ROOT / "tests" / "lib"))
    from json_objekt import json_objekt_aus_main
    NS["_json_objekt"] = json_objekt_aus_main(NS.get("HTTPException"))

``http_exception``: die Klasse, die der Pruefstand fuer FastAPIs
``HTTPException`` benutzt (Signatur ``(status_code, detail)``); ohne Angabe
eine eigene mit derselben Signatur.
"""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


class HTTPException(Exception):
    """Ersatz mit der Signatur von ``fastapi.HTTPException``."""

    def __init__(self, status_code, detail=None, headers=None):
        super().__init__(detail)
        self.status_code, self.detail, self.headers = status_code, detail, headers


def json_objekt_aus_main(http_exception=None):
    """Die Funktion ``_json_objekt`` aus ``backend/main.py``, ausfuehrbar."""
    baum = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
    fn = next((n for n in baum.body
               if isinstance(n, ast.AsyncFunctionDef) and n.name == "_json_objekt"), None)
    if fn is None:
        raise RuntimeError("_json_objekt nicht in backend/main.py gefunden")
    ns = {"HTTPException": http_exception or HTTPException, "Request": object}
    exec(compile(ast.Module(body=[fn], type_ignores=[]), "main.py", "exec"), ns)
    return ns["_json_objekt"]
