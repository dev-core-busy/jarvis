#!/usr/bin/env python3
"""Waechter: Entscheidungen in backend/main.py lesen den ROUTING-Pfad, nicht request.url.path.

DER ANLASS (2026-10-21, Paket-Empfehlung eines Dritten): ``request.url`` baut
Starlette aus dem Host-Header. Mit CVE-2026-48710 ("BadHost", siehe
``test_starlette_badhost.py``) verschob ein Host wie ``opfer.example/static`` den
von der Anwendung gesehenen ``request.url.path`` – ``/api/admin/...`` wurde zu
``/static/api/admin/...``, waehrend das Routing nach dem unveraenderten
``scope["path"]`` den echten Endpunkt aufrief. Die Loopback-Sperre in
``_api_local_only_mw`` fiel damit weg.

Behoben ist das seitdem NUR ueber die Starlette-Version. Dieser Waechter macht
die Anwendung unabhaengig davon: wer anhand des Pfads etwas ENTSCHEIDET
(Loopback-Sperre, Sicherheitsprotokoll, CSP, Sicherheits-Kopfzeilen, Cache,
Anwesenheit), liest ``_routing_pfad(request)`` = ``request.scope["path"]`` – also
denselben Wert, nach dem auch das Routing geht. Dann kann ein Host-Header die
Entscheidung nicht mehr vom aufgerufenen Endpunkt trennen.

Erlaubt bleibt ``request.url.path`` in f-Strings (Protokollzeilen): dort entscheidet
er nichts.

Gemessen wird am Syntaxbaum (ein Teilstring ist keine Identitaet), und die
Wirkung des Helfers wird mit einer echten Starlette-Request unter vergiftetem
Host-Header nachgerechnet.

Lauf:  python3 tests/test_routing_pfad.py [pfad/zu/main.py]
Exit 0 = Regel haelt, 1 = Verstoss, 2 = konnte nicht laufen
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Pfad als Argument, damit gegen_routing_pfad.py gebaute Verstoesse vorlegen kann.
MAIN = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "backend" / "main.py"

HELFER = "_routing_pfad"
# Middlewares, die anhand des Pfads eine Sicherheitsentscheidung treffen.
ENTSCHEIDER = ("_api_local_only_mw", "_sicherheits_protokoll_mw",
               "_csp_kopfzeilen", "_sicherheits_kopfzeilen")

ok = 0
fehler = 0


def pruefe(was, bedingung, detail=""):
    global ok, fehler
    if bedingung:
        ok += 1
        print(f"  \033[32m✓\033[0m {was}")
    else:
        fehler += 1
        print(f"  \033[31m✗\033[0m {was}" + (f"\n      {detail}" if detail else ""))


def abschnitt(t):
    print(f"\n\033[1m{t}\033[0m")


def abbruch(grund):
    print(f"\nABBRUCH (konnte nicht laufen): {grund}")
    sys.exit(2)


def url_path_ausserhalb_fstring(baum):
    """Zeilennummern aller ``<x>.url.path`` ausserhalb eines f-Strings."""
    in_fstring = set()
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.JoinedStr):
            for kind in ast.walk(knoten):
                in_fstring.add(id(kind))
    treffer = []
    for knoten in ast.walk(baum):
        if (isinstance(knoten, ast.Attribute) and knoten.attr == "path"
                and isinstance(knoten.value, ast.Attribute) and knoten.value.attr == "url"
                and id(knoten) not in in_fstring):
            treffer.append(knoten.lineno)
    return sorted(treffer)


def funktionen(baum, name):
    return [k for k in ast.walk(baum)
            if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name == name]


def ruft(fn, name):
    return any(isinstance(k, ast.Call) and isinstance(k.func, ast.Name) and k.func.id == name
               for k in ast.walk(fn))


def liest_scope_path(fn):
    """Gibt die Funktion ``<param>.scope["path"]`` zurueck (und nur das)?"""
    rueck = [k for k in ast.walk(fn) if isinstance(k, ast.Return)]
    if len(rueck) != 1 or rueck[0].value is None:
        return False
    w = rueck[0].value
    return (isinstance(w, ast.Subscript)
            and isinstance(w.value, ast.Attribute) and w.value.attr == "scope"
            and isinstance(w.slice, ast.Constant) and w.slice.value == "path")


# ── Positivkontrolle: sieht die Sonde den Fall, und NUR ihn? ──────────────────
abschnitt("Positivkontrolle der Sonde")
probe = ast.parse(
    "def f(request):\n"
    "    p = request.url.path\n"                 # Zeile 2: muss gemeldet werden
    "    print(f'{request.url.path} x')\n"       # Zeile 3: f-String, erlaubt
    "    q = request.scope['path']\n"            # Zeile 4: richtig
    "    return request.url.paths\n")            # Zeile 5: anderes Attribut
gefunden = url_path_ausserhalb_fstring(probe)
if gefunden != [2]:
    abbruch(f"Sonde blind oder zu breit: erwartet [2], gefunden {gefunden}")
print("  Sonde trifft genau die Entscheidungszeile, nicht den f-String")

if not MAIN.is_file():
    abbruch(f"{MAIN} fehlt")
try:
    baum = ast.parse(MAIN.read_text(encoding="utf-8"))
except SyntaxError as e:
    abbruch(f"{MAIN} nicht parsebar: {e}")
for name in ENTSCHEIDER:
    if not funktionen(baum, name):
        abbruch(f"Middleware {name} nicht gefunden – umbenannt? Liste ENTSCHEIDER nachziehen")

# ── Regel ─────────────────────────────────────────────────────────────────────
abschnitt("Regel: kein request.url.path als Entscheidungsgrundlage")
stellen = url_path_ausserhalb_fstring(baum)
pruefe("kein <x>.url.path ausserhalb von Protokoll-f-Strings", not stellen,
       f"Zeilen {stellen} in {MAIN.name} – {HELFER}(request) benutzen")

helfer = funktionen(baum, HELFER)
pruefe(f"{HELFER} genau einmal definiert", len(helfer) == 1, f"{len(helfer)}x")
pruefe(f"{HELFER} gibt request.scope[\"path\"] zurueck",
       len(helfer) == 1 and liest_scope_path(helfer[0]))
for name in ENTSCHEIDER:
    pruefe(f"{name} entscheidet ueber {HELFER}()",
           all(ruft(fn, HELFER) for fn in funktionen(baum, name)))

# ── Wirkung: der Helfer unter vergiftetem Host-Header ────────────────────────
abschnitt("Wirkung: echte Starlette-Request, Host-Header vergiftet")
try:
    from starlette.requests import Request
except ImportError:
    abbruch("starlette nicht installiert – Wirkung nicht messbar (venv/bin/python benutzen)")
if len(helfer) == 1:
    modul = ast.Module(body=[helfer[0]], type_ignores=[])
    raum: dict = {}
    exec(compile(ast.fix_missing_locations(modul), str(MAIN), "exec"), raum)  # nosec B102 – eigener Quelltext
    scope = {"type": "http", "method": "GET", "scheme": "https", "path": "/api/admin/geheim",
             "raw_path": b"/api/admin/geheim", "query_string": b"", "root_path": "",
             "headers": [(b"host", b"opfer.example/static")], "server": ("127.0.0.1", 443),
             "client": ("192.0.2.7", 50000)}
    anfrage = Request(scope)
    pruefe("Helfer liefert den Routing-Pfad trotz vergiftetem Host",
           raum[HELFER](anfrage) == "/api/admin/geheim", repr(raum[HELFER](anfrage)))
    # Zur Einordnung: auf einer verwundbaren Starlette weicht url.path hier ab.
    print(f"  (zum Vergleich request.url.path = {anfrage.url.path!r})")

print(f"\nErgebnis: {ok} OK, {fehler} FAIL")
sys.exit(1 if fehler else 0)
