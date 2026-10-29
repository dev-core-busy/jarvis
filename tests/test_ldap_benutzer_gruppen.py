#!/usr/bin/env python3
"""Waechter: Gruppenmitgliedschaften und OU eines AD-Benutzers
(``ldap_directory.user_groups``, ``POST /api/ldap/user_groups``).

Gemessen an einer Attrappe der ldap3-Verbindung mit der ECHTEN Form
(``search(search_base=, search_filter=, attributes=, paged_size=)``, Eintraege
mit ``in``, ``[attr].values``/``.value`` und ``entry_dn``):

  1. Ort: OU-Pfad von aussen nach innen, Komma im Namen bleibt Teil des Namens,
     UTF-8-Escapes (``\\C3\\A4``) werden zu Umlauten.
  2. Suchfilter: Anmeldename, DOMAENE\\name, UPN/Mail; Sonderzeichen escaped.
  3. direkt = memberOf (dieselbe Liste wie die Anmeldung), alphabetisch.
  4. indirekt = Kettenabfrage MINUS direkt; scheitert sie -> None (unbekannt
     ist nicht leer).
  5. Primaergruppe ueber Domaenen-SID + primaryGroupID, SID als Bytes.
  6. Nicht gefunden / mehrdeutig -> RuntimeError mit Grund.
  7. REGEL: der Endpunkt haengt an require_local_auth und benutzt _ldap_creds.

    python3 tests/test_ldap_benutzer_gruppen.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import struct
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  \033[32m✓\033[0m " + name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m " + name + (" – " + str(detail) if detail != "" else ""))


def abschnitt(t):
    print("\n\033[1m" + t + "\033[0m")


# backend.config nur als Stub – der echte Import schreibt die Live-settings.json
_stub = types.ModuleType("backend.config")
_stub.config = types.SimpleNamespace(get_setting=lambda k, d="": d)
sys.modules["backend.config"] = _stub
try:
    import ldap3  # noqa: F401
    from backend import ldap_directory as L
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: ldap_directory nicht ladbar (%s)" % e)
    sys.exit(2)


class Attr:
    def __init__(self, werte):
        self.values = list(werte)
        self.value = self.values[0] if len(self.values) == 1 else self.values

    def __bool__(self):
        return bool(self.values)

    def __str__(self):
        return str(self.value)


class Eintrag:
    def __init__(self, dn, **attrs):
        self.entry_dn = dn
        self._a = {k: Attr(v if isinstance(v, list) else [v]) for k, v in attrs.items()}

    def __contains__(self, k):
        return k in self._a

    def __getitem__(self, k):
        return self._a[k]


def sid_bytes(*unter):
    return bytes([1, len(unter), 0, 0, 0, 0, 0, 5]) + struct.pack("<%dI" % len(unter), *unter)


USER_DN = r"CN=Muster\, Erika,OU=Nord,OU=Labor,OU=Benutzer,DC=firma,DC=local"
G_A = "CN=Alle Labor,OU=Gruppen,DC=firma,DC=local"
G_B = r"CN=B\, Team,OU=Gruppen,DC=firma,DC=local"
G_NEST = "CN=Ueber Kette,OU=Gruppen,DC=firma,DC=local"
G_PRIM = "CN=Domaenen-Benutzer,CN=Users,DC=firma,DC=local"


class Conn:
    def __init__(self, benutzer, kette=None, kette_wirft=False, primaer=True):
        self.benutzer = benutzer
        self.kette = kette if kette is not None else [G_A, G_NEST]
        self.kette_wirft = kette_wirft
        self.primaer = primaer
        self.filter = []
        self.entries = []
        self.unbound = False

    def search(self, search_base, search_filter, attributes=None, paged_size=None):
        self.filter.append(search_filter)
        if "objectCategory=person" in search_filter:
            self.entries = self.benutzer
        elif "1.2.840.113556.1.4.1941" in search_filter:
            if self.kette_wirft:
                raise RuntimeError("Kettenabfrage nicht unterstuetzt")
            self.entries = [Eintrag(g, distinguishedName=g) for g in self.kette]
        elif "objectSid=" in search_filter:
            self.entries = ([Eintrag(G_PRIM, distinguishedName=G_PRIM)]
                            if self.primaer and "S-1-5-21-1-2-3-513" in search_filter else [])
        else:
            self.entries = []
        return True

    def unbind(self):
        self.unbound = True


def erika():
    return Eintrag(USER_DN, sAMAccountName="erika.muster", displayName="Erika Muster",
                   mail="erika.muster@beispiel.de", userPrincipalName="erika.muster@firma.local",
                   distinguishedName=USER_DN, memberOf=[G_B, G_A], primaryGroupID="513",
                   objectSid=sid_bytes(21, 1, 2, 3, 1104))


def mit(conn, f):
    alt = L._bind
    L._bind = lambda u=None, p=None: (conn, "DC=firma,DC=local")
    try:
        return f()
    finally:
        L._bind = alt


# ── Positivkontrolle: die Attrappe liefert den Benutzer ueberhaupt ─────────
c0 = Conn([erika()])
try:
    r0 = mit(c0, lambda: L.user_groups("erika.muster"))
except Exception as e:  # noqa: BLE001
    r0 = None
    print("  (Aufruf warf: %s)" % e)
if not r0 or r0.get("dn") != USER_DN:
    print("ABBRUCH: Positivkontrolle – user_groups liefert den Benutzer der Attrappe nicht (%r)" % r0)
    sys.exit(2)

abschnitt("1. Ort im Verzeichnis")
lage = r0["lage"]
check("OU-Pfad von aussen nach innen", lage["ou"] == ["Benutzer", "Labor", "Nord"], lage["ou"])
check("Name mit Komma bleibt ganz", lage["name"] == "Muster, Erika", lage["name"])
check("Domaene aus DC-Teilen", lage["domaene"] == "firma.local", lage["domaene"])
check("Container = DN ohne eigenen RDN",
      lage["container"] == "OU=Nord,OU=Labor,OU=Benutzer,DC=firma,DC=local", lage["container"])
u = L.dn_lage(r"CN=x,OU=Labor\C3\A4,DC=firma,DC=local")
check("UTF-8-Escape wird Umlaut", u["ou"] == ["Laborä"], u["ou"])
check("kaputter DN wirft nicht", isinstance(L.dn_lage("kein dn ="), dict))
check("Container eines CN-Containers zaehlt zum Pfad",
      L.dn_lage(G_PRIM)["ou"] == ["Users"], L.dn_lage(G_PRIM)["ou"])

abschnitt("2. Suchfilter")
f = L._benutzer_filter
check("Anmeldename -> sAMAccountName", "(sAMAccountName=x.y)" in f("x.y"), f("x.y"))
check("DOMAENE\\name -> nur der Name", "(sAMAccountName=x.y)" in f("FIRMA\\x.y"), f("FIRMA\\x.y"))
fm = f("x.y@beispiel.de")
check("Mail/UPN -> UPN, mail und proxyAddresses",
      all(t in fm for t in ("(userPrincipalName=x.y@beispiel.de)", "(mail=x.y@beispiel.de)",
                            "(proxyAddresses=smtp:x.y@beispiel.de)")), fm)
fi = f("a*)(objectClass=*")
check("Sonderzeichen escaped (keine LDAP-Injection)", "*)" not in fi and "\\2a\\29" in fi, fi)
check("nur Personen", f("x").startswith("(&(objectCategory=person)(objectClass=user)"), f("x"))
check("Filter des Laufs war der Anmeldename", "(sAMAccountName=erika.muster)" in c0.filter[0], c0.filter[:1])

abschnitt("3. Direkte Gruppen = memberOf")
check("beide memberOf-Gruppen", [g["dn"] for g in r0["direkt"]] == [G_A, G_B], [g["dn"] for g in r0["direkt"]])
check("Name aus DN (Komma bleibt)", [g["cn"] for g in r0["direkt"]] == ["Alle Labor", "B, Team"],
      [g["cn"] for g in r0["direkt"]])
check("Gruppe traegt ihren Ort", r0["direkt"][0]["lage"]["ou"] == ["Gruppen"], r0["direkt"][0]["lage"])
check("Stammdaten", (r0["sam"], r0["display"], r0["mail"]) ==
      ("erika.muster", "Erika Muster", "erika.muster@beispiel.de"), (r0["sam"], r0["display"]))
check("Verbindung wird geschlossen", c0.unbound)

abschnitt("4. Indirekte Gruppen")
check("Kette minus direkt", [g["dn"] for g in r0["indirekt"]] == [G_NEST], r0["indirekt"])
kf = [x for x in c0.filter if "1.2.840.113556.1.4.1941" in x]
check("Kettenfilter mit escaptem Benutzer-DN",
      len(kf) == 1 and ("member:1.2.840.113556.1.4.1941:=" + L._esc(USER_DN)) in kf[0], kf)
c1 = Conn([erika()], kette_wirft=True)
r1 = mit(c1, lambda: L.user_groups("erika.muster"))
check("Kettenabfrage scheitert -> None, nicht []", r1["indirekt"] is None, r1["indirekt"])
check("... und direkt bleibt trotzdem", len(r1["direkt"]) == 2, r1["direkt"])
c1b = Conn([erika()], kette=[G_A, G_B])
r1b = mit(c1b, lambda: L.user_groups("erika.muster"))
check("nichts nur-indirekt -> leere Liste", r1b["indirekt"] == [], r1b["indirekt"])

abschnitt("5. Primaergruppe")
check("SID aus Bytes", L._sid_text(sid_bytes(21, 1, 2, 3, 1104)) == "S-1-5-21-1-2-3-1104",
      L._sid_text(sid_bytes(21, 1, 2, 3, 1104)))
check("SID schon als Text bleibt", L._sid_text("S-1-5-21-9-513") == "S-1-5-21-9-513")
check("kaputte SID -> leer", L._sid_text(b"\x01\x05") == "")
check("Primaergruppe aufgeloest", (r0["primaer"] or {}).get("dn") == G_PRIM, r0["primaer"])
c2 = Conn([erika()], primaer=False)
r2 = mit(c2, lambda: L.user_groups("erika.muster"))
check("nicht aufloesbar -> None", r2["primaer"] is None, r2["primaer"])

abschnitt("6. Nicht gefunden / mehrdeutig")
for name, conn, muster in (("nicht gefunden", Conn([]), "nicht im Verzeichnis"),
                           ("mehrdeutig", Conn([erika(), erika()]), "mehrere Konten")):
    try:
        mit(conn, lambda: L.user_groups("erika.muster@beispiel.de"))
        check(name + " -> RuntimeError", False, "kein Fehler")
    except RuntimeError as e:
        check(name + " -> RuntimeError mit Grund", muster in str(e), str(e))
try:
    L.user_groups("  ")
    check("leerer Name -> RuntimeError", False, "kein Fehler")
except RuntimeError:
    check("leerer Name -> RuntimeError (vor jedem Bind)", True)

abschnitt("7. REGEL: Endpunkt")
baum = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
fn = None
for n in ast.walk(baum):
    if isinstance(n, ast.AsyncFunctionDef):
        for d in n.decorator_list:
            if (isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant)
                    and d.args[0].value == "/api/ldap/user_groups"
                    and isinstance(d.func, ast.Attribute) and d.func.attr == "post"):
                fn = n
check("POST /api/ldap/user_groups existiert", fn is not None)
if fn is not None:
    deps = [d for d in fn.args.defaults if isinstance(d, ast.Call)
            and getattr(d.func, "id", "") == "Depends" and d.args
            and getattr(d.args[0], "id", "") == "require_local_auth"]
    check("haengt an require_local_auth (nur lokale Admins)", len(deps) == 1)
    aufrufe = {getattr(c.func, "id", getattr(c.func, "attr", "")) for c in ast.walk(fn)
               if isinstance(c, ast.Call)}
    check("benutzt _ldap_creds (Service-Konto oder Sitzungs-Kennwort)", "_ldap_creds" in aufrufe)
    check("Fehler ueber _ldap_error_response (428/401/400)", "_ldap_error_response" in aufrufe)

print("\n%d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
