#!/usr/bin/env python3
"""Waechter: ldap_directory.sperrrichtlinie() liest die Sperrrichtlinie der Domaene richtig.

ANLASS (2026-10-21): die Abfrage stand mitten in main.py (_ad_sperrrichtlinie_lesen)
und hatte keine eigene Pruefung – test_anmelde_spruehen ersetzt sie durch eine
Attrappe. Beim Umzug nach backend/ldap_directory.py (ldap3 an einer Stelle) ist
sie eine eigene Funktion geworden und damit messbar:
  - das Beobachtungsfenster kommt je nach Schema als timedelta ODER als negative
    Zahl in 100-ns-Schritten – beides ergibt Sekunden,
  - fehlendes Domaenenobjekt -> None, fehlende Schwelle -> 0,
  - eine gescheiterte Suche wird als RuntimeError gemeldet,
  - die Verbindung wird in JEDEM Fall geschlossen.

Geladen wird das echte Modul; backend.config und ldap3 sind Attrappen (der echte
config-Import schriebe die Live-settings.json zurueck).
Lauf:  python3 tests/test_ldap_sperrrichtlinie.py [pfad/zu/ldap_directory.py]
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen
"""
import datetime as dt
import importlib.util
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Pfad als Argument, damit gegen_ldap_sperrrichtlinie.py sabotierte Kopien vorlegt
MODUL = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "backend" / "ldap_directory.py"
ok = fail = 0


def check(name, bed, detail=""):
    global ok, fail
    if bed:
        ok += 1
        print("  OK   " + name)
    else:
        fail += 1
        print("  FAIL " + name + (" – " + str(detail) if detail else ""))


pkg = sys.modules.setdefault("backend", types.ModuleType("backend"))
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace(get_setting=lambda k, d=None: d)
sys.modules["backend.config"] = _cfg
pkg.config = _cfg
_ldap3 = types.ModuleType("ldap3")
_ldap3.BASE = "BASE"
sys.modules["ldap3"] = _ldap3
try:
    spec = importlib.util.spec_from_file_location("backend.ldap_directory", MODUL)
    L = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(L)
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: ldap_directory nicht ladbar: {e}")
    sys.exit(2)
if not hasattr(L, "sperrrichtlinie"):
    print("ABBRUCH: ldap_directory.sperrrichtlinie fehlt")
    sys.exit(2)


class _Wert:
    def __init__(self, v):
        self.value = v


class _Eintrag(dict):
    def __getitem__(self, k):
        return _Wert(dict.__getitem__(self, k))


class _Conn:
    def __init__(self, eintraege=None, fehler=None):
        self.entries, self._fehler, self.geschlossen, self.suche = eintraege or [], fehler, False, None

    def search(self, **kw):
        self.suche = kw
        if self._fehler:
            raise self._fehler

    def unbind(self):
        self.geschlossen = True


def lauf(conn):
    L._bind = lambda *a, **k: (conn, "DC=firma,DC=local")
    try:
        return L.sperrrichtlinie(), None
    except Exception as e:  # noqa: BLE001
        return None, e


print("\n── Sperrrichtlinie der Domaene")
c = _Conn([_Eintrag(lockoutThreshold=5, lockOutObservationWindow=dt.timedelta(minutes=-30))])
r, e = lauf(c)
check("Positivkontrolle: Suche am Domaenenobjekt, Basis-Bereich, beide Attribute",
      c.suche and c.suche.get("search_scope") == "BASE" and c.suche.get("search_base") == "DC=firma,DC=local"
      and set(c.suche.get("attributes", [])) == {"lockoutThreshold", "lockOutObservationWindow"}, c.suche)
check("timedelta-Fenster -> Sekunden (30 min = 1800 s), Schwelle 5",
      r == {"schwelle": 5, "fenster_s": 1800.0}, (r, e))
check("…Verbindung geschlossen", c.geschlossen)

c = _Conn([_Eintrag(lockoutThreshold=3, lockOutObservationWindow=-18000000000)])
r, e = lauf(c)
check("100-ns-Zahl (negativ) -> Sekunden (1800 s)", r == {"schwelle": 3, "fenster_s": 1800.0}, (r, e))

c = _Conn([_Eintrag()])
r, e = lauf(c)
check("fehlende Attribute -> Schwelle 0, Fenster 0", r == {"schwelle": 0, "fenster_s": 0.0}, (r, e))

c = _Conn([])
r, e = lauf(c)
check("kein Domaenenobjekt -> None, Verbindung geschlossen", r is None and e is None and c.geschlossen, (r, e))

c = _Conn(fehler=OSError("Verbindung weg"))
r, e = lauf(c)
check("gescheiterte Suche -> RuntimeError mit Grund, Verbindung geschlossen",
      isinstance(e, RuntimeError) and "Verbindung weg" in str(e) and c.geschlossen, (r, e))

print(f"\nErgebnis: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
