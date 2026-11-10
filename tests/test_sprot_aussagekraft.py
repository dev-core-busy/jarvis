#!/usr/bin/env python3
"""Waechter: aussagekraeftige Eintraege im Sicherheitsprotokoll (2026-11-10).

Gemeldet: "Aenderung durch Administrator" mit nur ``methode=POST
pfad=/api/ldap/group_members`` – dreimal in derselben Sekunde, fuer eine reine
Abfrage. Auf DEV waren drei Viertel aller ``admin_aenderung``-Eintraege
Abfragen (Gruppenmitglieder, Token-Pruefung, Anmeldung).

1. Die ECHTE Middleware ``_sicherheits_protokoll_mw`` samt Helfern per AST aus
   main.py geschnitten und AUSGEFUEHRT (Attrappen fuer Request/Routen/Protokoll):
   Aktion als Satz, Objekt aus den Pfadparametern, Angaben des Endpunkts,
   Vorgaenge, Reihenfolge; gekennzeichnete Endpunkte erzeugen keinen
   ``admin_aenderung``-Eintrag, ein 403 dort aber weiterhin ``admin_verweigert``.
   Die Route wird OHNE ``scope["endpoint"]`` gefunden (die Cookie-Middleware
   kopiert den scope, das Routing traegt dort nichts ein).
2. ``_sprot_aktion``: erster Satz, Abkuerzungen, "(Admin)", Gedankenstrich, Markup.
3. Als REGEL ueber main.py: jeder aendernde Admin-Endpunkt (require_local_auth)
   ohne Kennzeichnung liefert eine nichtleere Aktion, die nicht mit "Body" beginnt;
   die gemeldeten Abfragen tragen die Kennzeichnung; /api/settings meldet nur
   Feld-NAMEN.

Laeuft ohne fastapi/starlette. Exit 2 = konnte nicht laufen.
"""

import ast
import asyncio
import contextvars
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(MAIN)
_ok = _fail = 0


def pruefe(bed, text, detail=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   " + text)
    else:
        _fail += 1
        print("  FAIL " + text + (f"  [{detail}]" if detail else ""))


def abbruch(text):
    print("ABBRUCH: " + text, file=sys.stderr)
    sys.exit(2)


# ── Schnitt ────────────────────────────────────────────────────────────────
FUNKTIONEN = ("_sprot_keine_aenderung", "_sprot_angaben", "_sprot_aktion", "_sprot_route",
              "_sprot_wert", "_sprot_details", "_sicherheits_protokoll_mw")
ZUWEISUNGEN = ("_SPROT_ABKUERZUNG", "_AENDERNDE_METHODEN", "_KONTO_PFADE")
teile = []
for n in BAUM.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in FUNKTIONEN:
        n = ast.fix_missing_locations(n)
        n.decorator_list = []          # @app.middleware("http") – hier ohne App
        teile.append(n)
    elif isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in ZUWEISUNGEN
                                           for t in n.targets):
        teile.append(n)
    elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id in ZUWEISUNGEN:
        teile.append(n)
namen = {getattr(t, "name", None) for t in teile} | {
    (t.targets[0].id if isinstance(t, ast.Assign) else t.target.id)
    for t in teile if isinstance(t, (ast.Assign, ast.AnnAssign))}
fehlt = (set(FUNKTIONEN) | set(ZUWEISUNGEN)) - namen
if fehlt:
    abbruch(f"in main.py nicht gefunden: {sorted(fehlt)}")


class Protokoll:
    def __init__(self):
        self.eintraege = []

    def ereignis(self, art, *, benutzer="", ip="", ergebnis="", **details):
        self.eintraege.append({"art": art, "benutzer": benutzer, "ip": ip,
                               "ergebnis": ergebnis, "details": details})


class Treffer:
    """Nachbildung von starlette.routing.Match (Enum mit .name)."""
    def __init__(self, name):
        self.name = name


class Route:
    """Wie eine APIRoute: ``matches(scope)`` -> (Match, child_scope)."""
    def __init__(self, methode, muster, endpoint):
        self.methode, self.endpoint = methode, endpoint
        self.re = re.compile("^" + re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", muster) + "$")

    def matches(self, scope):
        m = self.re.match(scope["path"])
        if not m:
            return Treffer("NONE"), {}
        if scope["method"] != self.methode:
            return Treffer("PARTIAL"), {}
        return Treffer("FULL"), {"endpoint": self.endpoint, "path_params": m.groupdict()}


admin_anfrage = contextvars.ContextVar("_admin_anfrage", default=None)
PROTO = Protokoll()
NS = {"re": re, "Request": object, "_admin_anfrage": admin_anfrage,
      "_routing_pfad": lambda r: r.scope["path"], "_sicherheits_log": PROTO,
      "print": lambda *a, **k: None}
exec(compile(ast.Module(body=teile, type_ignores=[]), "main.py[schnitt]", "exec"), NS)

# Endpunkte (echte Python-Funktionen mit Docstring, gekennzeichnet ueber den ECHTEN Dekorator)


def ep_mcp_aendern():
    """Aktualisiert einen MCP-Server und verbindet bzw. trennt ihn. Danach gilt die neue Konfiguration."""


def ep_gruppenmitglieder():
    """Listet die DIREKTEN Mitglieder einer AD-Gruppe (Admin) – für den Picker."""


ep_gruppenmitglieder = NS["_sprot_keine_aenderung"](ep_gruppenmitglieder)


def ep_sperren():
    """Sperrt einen Account von Hand. Administratoren (lokal ODER AD)."""


def ep_kennwort():
    """Kennwort des eigenen Kontos aendern."""


class App:
    class router:
        routes = [Route("POST", "/api/ldap/group_members", ep_gruppenmitglieder),
                  Route("PUT", "/api/mcp/servers/{server_id}", ep_mcp_aendern),
                  Route("POST", "/api/security/incidents/block", ep_sperren),
                  Route("POST", "/api/change-password", ep_kennwort)]


NS["app"] = App


class Anfrage:
    def __init__(self, methode, pfad):
        self.method = methode
        # bewusst OHNE "endpoint"/"path_params": so sieht die aeussere Middleware
        # den scope bei einer Cookie-Sitzung (SitzungCookieMiddleware kopiert ihn)
        self.scope = {"type": "http", "method": methode, "path": pfad}
        self.client = type("C", (), {"host": "192.0.2.5"})()


class Antwort:
    def __init__(self, status):
        self.status_code = status


def lauf(methode, pfad, status=200, admin=True, endpunkt_tut=None, sitzung=""):
    """Middleware einmal durchlaufen; ``endpunkt_tut`` laeuft IM Endpunkt."""
    vorher = len(PROTO.eintraege)

    async def call_next(_req):
        halter = admin_anfrage.get()
        if halter is None:             # nicht protokollierte Anfrage (GET): kein Halter
            return Antwort(status)
        if admin is not None:
            halter["benutzer"] = "FIRMA\\admin.konto"
            halter["admin"] = admin
        if sitzung:
            halter["sitzung"] = sitzung
        if endpunkt_tut:
            endpunkt_tut(halter)
        return Antwort(status)

    asyncio.run(NS["_sicherheits_protokoll_mw"](Anfrage(methode, pfad), call_next))
    return PROTO.eintraege[vorher:]


# ── Positivkontrolle: der Schnitt laeuft und protokolliert ueberhaupt ────────
neu = lauf("PUT", "/api/mcp/servers/abc-123")
if len(neu) != 1 or neu[0]["art"] != "admin_aenderung":
    abbruch(f"Positivkontrolle: eine Admin-Aenderung erzeugt keinen Eintrag ({neu})")

print("\n== 1. Middleware (geschnitten, ausgefuehrt)")
d = neu[0]["details"]
pruefe(d.get("aktion") == "Aktualisiert einen MCP-Server und verbindet bzw. trennt ihn",
       "Aktion = erster Satz des Docstrings (\"bzw.\" ist kein Satzende)", d.get("aktion"))
pruefe(d.get("objekt") == "server_id=abc-123", "Objekt aus den Pfadparametern – ohne scope['endpoint']",
       d.get("objekt"))
pruefe(list(d)[:1] == ["aktion"] and list(d)[-2:] == ["methode", "pfad"],
       "Reihenfolge: Aktion zuerst, Methode/Pfad als Beleg zuletzt", list(d))
pruefe(d.get("pfad") == "/api/mcp/servers/abc-123" and d.get("methode") == "PUT",
       "Beleg (Methode, Pfad) bleibt erhalten")

pruefe(lauf("POST", "/api/ldap/group_members") == [],
       "gekennzeichnete Abfrage (Gruppenmitglieder) -> KEIN admin_aenderung")
v = lauf("POST", "/api/ldap/group_members", status=403, admin=False)
pruefe(len(v) == 1 and v[0]["art"] == "admin_verweigert",
       "dieselbe Abfrage VERWEIGERT -> weiterhin admin_verweigert", v)


def mit_angaben(halter):
    token = admin_anfrage.set(halter)
    try:
        NS["_sprot_angaben"](konto="FIRMA\\x.y", grund="", leer=None, liste=[])
    finally:
        admin_anfrage.reset(token)
    halter.setdefault("vorgaenge", []).append("sicherheit/gesperrt: x.y")


s = lauf("POST", "/api/security/incidents/block", endpunkt_tut=mit_angaben)
ds = s[0]["details"] if s else {}
pruefe(ds.get("konto") == "FIRMA\\x.y", "Angabe des Endpunkts (Konto) steht im Eintrag", ds)
pruefe("grund" not in ds and "leer" not in ds and "liste" not in ds,
       "leere Angaben werden weggelassen", ds)
pruefe(ds.get("vorgang") == "sicherheit/gesperrt: x.y", "Vorgang aus _aktivitaet steht im Eintrag", ds)
pruefe(ds.get("aktion") == "Sperrt einen Account von Hand", "Aktion ohne Rechtehinweis", ds.get("aktion"))

k = lauf("POST", "/api/change-password", admin=None, sitzung="x.y")
pruefe(len(k) == 1 and k[0]["art"] == "konto_aenderung" and k[0]["benutzer"] == "x.y"
       and k[0]["details"].get("aktion") == "Kennwort des eigenen Kontos aendern",
       "Kontoaenderung mit Aktion und Sitzungskonto", k)

u = lauf("POST", "/api/unbekannt/weg")
pruefe(len(u) == 1 and "aktion" not in u[0]["details"] and u[0]["details"].get("pfad") == "/api/unbekannt/weg",
       "ohne passende Route: Eintrag bleibt (Beleg), keine erfundene Aktion", u)
pruefe(lauf("GET", "/api/mcp/servers/abc") == [], "GET wird nicht protokolliert")

print("\n== 2. _sprot_aktion")
A = NS["_sprot_aktion"]


def mit_doc(text):
    def f():
        pass
    f.__doc__ = text
    return f


FAELLE = [
    ("Speichert Auto-Update-Einstellungen und legt ggf. den Auftrag an.",
     "Speichert Auto-Update-Einstellungen und legt ggf. den Auftrag an"),
    ("Erfassung von Hand (z. B. nach Upload). Mehr.", "Erfassung von Hand (z. B. nach Upload)"),
    ("Laedt eine Vorlage hoch (Admin).", "Laedt eine Vorlage hoch"),
    ("Tickets ``{id}`` loeschen (nur Administratoren). Zweiter Satz.", "Tickets {id} loeschen"),
    ("Zertifikat entfernen – danach gilt die Systempruefung.", "Zertifikat entfernen"),
    ("Erste Zeile\nzweite Zeile.\n\nAbsatz.", "Erste Zeile zweite Zeile"),
    ("", ""),
]
for doc, soll in FAELLE:
    ist = A(mit_doc(doc))
    pruefe(ist == soll, f"{doc[:40]!r} -> {soll!r}", ist)
pruefe(A(mit_doc(None)) == "", "ohne Docstring -> ''")

print("\n== 3. Regeln ueber main.py")
AENDERND = {"post", "put", "patch", "delete"}


def route_von(fn):
    for d in fn.decorator_list:
        if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                and isinstance(d.func.value, ast.Name) and d.func.value.id == "app"
                and d.func.attr in AENDERND and d.args and isinstance(d.args[0], ast.Constant)):
            return d.func.attr.upper(), d.args[0].value
    return None


def gekennzeichnet(fn):
    return any(isinstance(d, ast.Name) and d.id == "_sprot_keine_aenderung" for d in fn.decorator_list)


def admin_dep(fn):
    return any(isinstance(x, ast.Call) and isinstance(x.func, ast.Name) and x.func.id == "Depends"
               and x.args and isinstance(x.args[0], ast.Name) and x.args[0].id == "require_local_auth"
               for x in ast.walk(fn.args))


endpunkte = {}
for n in BAUM.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        r = route_von(n)
        if r:
            endpunkte[r] = n
admin_aendernd = {r: n for r, n in endpunkte.items() if admin_dep(n) and not gekennzeichnet(n)}
if len(admin_aendernd) < 50:
    abbruch(f"nur {len(admin_aendernd)} aendernde Admin-Endpunkte gefunden – Erkennung blind?")
schlecht = []
for (m, p), n in sorted(admin_aendernd.items()):
    akt = A(mit_doc(ast.get_docstring(n, clean=False)))
    if not akt or akt.lower().startswith(("body", "{")) or len(akt.split()) < 2:
        schlecht.append(f"{m} {p}: {akt!r}")
pruefe(not schlecht, f"alle {len(admin_aendernd)} aendernden Admin-Endpunkte haben eine lesbare Aktion",
       "; ".join(schlecht[:8]))

for p in ("/api/ldap/group_members", "/api/ldap/groups", "/api/ldap/users", "/api/ldap/user_groups",
          "/api/verify-token", "/api/login"):
    n = endpunkte.get(("POST", p))
    pruefe(n is not None and gekennzeichnet(n), f"POST {p} ist als 'keine Aenderung' gekennzeichnet")

# /api/settings: Feld-NAMEN, nie Werte (dort stehen Kennwoerter)
ss = endpunkte.get(("POST", "/api/settings"))
aufrufe = [c for c in ast.walk(ss) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
           and c.func.id == "_sprot_angaben"] if ss else []
pruefe(len(aufrufe) == 1 and [k.arg for k in aufrufe[0].keywords] == ["felder"],
       "POST /api/settings meldet genau 'felder'")
if aufrufe:
    ausdruck = aufrufe[0].keywords[0].value
    werte_zugriff = [x for x in ast.walk(ausdruck)
                     if isinstance(x, ast.Subscript) and isinstance(x.value, ast.Name) and x.value.id == "body"
                     or isinstance(x, ast.Attribute) and x.attr in ("values", "items", "get")]
    pruefe(not werte_zugriff, "…und liest dabei keinen WERT aus dem Anfragekoerper",
           ast.unparse(ausdruck))

print(f"\n== Ergebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
