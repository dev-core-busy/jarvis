#!/usr/bin/env python3
"""Waechter: SAP "Anmeldung ueber die Portal-Kachel fordern" (2026-11-05).

Zusagen (backend/sap_accounts.py, Abschnitt "Anmeldung ueber die Portal-Kachel",
und backend/main.py::update_skill_config / logout):

* Mit dem Schalter liegt KEIN SAP-Kennwort auf der Platte – weder neu
  gespeichert noch als Rest von vorher.
* Beim Einschalten verlieren alle persoenlichen Zugaenge ihre Kennwoerter, die
  Zugaenge selbst (Server, Benutzer) bleiben.
* Ein eingegebenes Kennwort gilt nur im Arbeitsspeicher: Ablauf, Abmelden und
  ein Anmeldefehler beenden es.
* Ohne Anmeldung gibt es KEINEN Zugang – auch keinen Rueckfall auf den
  Sammelzugang.
* Das Einstellungs-Speichern leert die Geheimfelder des Sammelzugangs NACH dem
  "leer = unveraendert"-Schritt (sonst setzte der sie wieder ein).

Laeuft ohne fastapi und ohne SAP-System; ``backend.config`` ist eine Attrappe
(der echte Import schreibt die Live-settings.json zurueck).
Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.

    python3 tests/test_sap_kachel_anmeldung.py
"""
import ast
import importlib.util
import json
import os
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def section(t):
    print(f"\n{t}")


# ── Attrappe fuer backend.config VOR dem Import ─────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="sapkachel_test_"))
(TMP / "data").mkdir(parents=True)
_skill_states = {"sap": {"enabled": True, "config": {}}}
_cfg_mod = types.ModuleType("backend.config")


class _Cfg:
    def get_skill_states(self):
        return _skill_states

    def get_setting(self, key, default=None):
        return default

    def save_setting(self, key, value):
        pass


_cfg_mod.config = _Cfg()
sys.modules.setdefault("backend.config", _cfg_mod)

# Gegenprobe (tests/gegen_sap_kachel_anmeldung.py): sabotierte KOPIEN statt der
# echten Dateien – ueber die Umgebung, die Originale werden nie angefasst.
MODUL = Path(os.environ.get("SAP_KACHEL_MODUL") or ROOT / "backend" / "sap_accounts.py")
MAIN = Path(os.environ.get("SAP_KACHEL_MAIN") or ROOT / "backend" / "main.py")
try:
    import backend  # noqa: E402,F401  – Paket zuerst, sonst kein backend.sap_client
    _spec = importlib.util.spec_from_file_location("backend.sap_accounts", MODUL)
    sa = importlib.util.module_from_spec(_spec)
    sys.modules["backend.sap_accounts"] = sa
    _spec.loader.exec_module(sa)
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: sap_accounts nicht importierbar: {e}")
    sys.exit(2)

sa.DATA_DIR = TMP / "data"
sa.KONTEN_DATEI = TMP / "data" / "sap_accounts.json"
sa.SCHLUESSEL_DATEI = TMP / "data" / ".sapkey"
for pfad in (sa.KONTEN_DATEI, sa.SCHLUESSEL_DATEI):
    if not str(pfad).startswith(str(TMP)):
        print(f"SANDKASTEN VERLETZT: {pfad}")
        sys.exit(2)

KENNWORT = "Geheim-Probe-4711"
SAMMEL = dict(connection_type="odata", odata_base_url="https://s4.firma.de/sap/opu/odata",
              username="SAMMEL", password="sammel-kennwort", allowed_hosts="firma.de")


def admin(pflicht: bool):
    c = dict(SAMMEL)
    if pflicht:
        c["kachel_anmeldung"] = True
        c["password"] = ""          # so wie update_skill_config es hinterlaesst
    _skill_states["sap"]["config"] = c


def dateitext() -> str:
    return sa.KONTEN_DATEI.read_text(encoding="utf-8") if sa.KONTEN_DATEI.exists() else ""


ZUGANG = {"connection_type": "odata", "odata_base_url": "https://s4.firma.de/sap/opu/odata",
          "auth_kind": "basic", "username": "MUSTER"}

# ═══════════════════════════════════════════════════════════════════════════
section("0. Positivkontrolle: ohne Schalter wird das Kennwort gespeichert")
# ═══════════════════════════════════════════════════════════════════════════
admin(False)
try:
    sa.speichern("m.mustermann", dict(ZUGANG, password=KENNWORT))
    sa.speichern("e.beispiel", dict(ZUGANG, username="BEISPIEL", password="anderes"))
except sa.SapKontoFehler as e:
    print(f"ABBRUCH: Speichern ohne Schalter scheitert ({e}) – Messaufbau kaputt")
    sys.exit(2)
roh = json.loads(dateitext())
if not (roh.get("m.mustermann", {}).get("password_enc") and roh.get("e.beispiel", {}).get("password_enc")):
    print("ABBRUCH: ohne Schalter liegt kein verschluesseltes Kennwort – die "
          "folgenden 'kein Kennwort'-Pruefungen waeren trivial wahr")
    sys.exit(2)
z = sa.aufloesen("m.mustermann")
if z["quelle"] != sa.QUELLE_PERSOENLICH or z["client"].cfg.get("password") != KENNWORT:
    print("ABBRUCH: ohne Schalter gilt der persoenliche Zugang nicht – Messaufbau kaputt")
    sys.exit(2)
check(sa.kennwort_gespeichert("FIRMA\\M.Mustermann") is True,
      "Positivkontrolle: kennwort_gespeichert erkennt das gespeicherte Kennwort")
check(sa.kachel_pflicht() is False, "Schalter aus -> kachel_pflicht() False")

# ═══════════════════════════════════════════════════════════════════════════
section("1. Einschalten: Kennwoerter weg, Zugaenge bleiben")
# ═══════════════════════════════════════════════════════════════════════════
admin(True)
check(sa.kachel_pflicht() is True, "Schalter an -> kachel_pflicht() True")
n = sa.kennwoerter_entfernen()
check(n == 2, "zwei Zugaenge verloren ihr Kennwort", f"n={n}")
roh = json.loads(dateitext())
check("_enc" not in dateitext(), "kein *_enc mehr in der Kontendatei")
check(not sa.kennwort_gespeichert("m.mustermann") and not sa.kennwort_gespeichert("e.beispiel"),
      "kennwort_gespeichert meldet fuer beide 'nein'")
check(set(roh) == {"m.mustermann", "e.beispiel"}, "beide Zugaenge stehen noch", str(set(roh)))
check(roh.get("m.mustermann", {}).get("username") == "MUSTER"
      and roh.get("m.mustermann", {}).get("odata_base_url") == ZUGANG["odata_base_url"],
      "Server und Benutzer bleiben erhalten")
check(sa.kennwoerter_entfernen() == 0, "zweiter Lauf entfernt nichts mehr")

# ═══════════════════════════════════════════════════════════════════════════
section("2. Ohne Anmeldung: kein Zugang, kein Rueckfall")
# ═══════════════════════════════════════════════════════════════════════════
z = sa.aufloesen("m.mustermann")
check(z["quelle"] == sa.QUELLE_KEINE, "Quelle 'keine' statt Sammelzugang", z["quelle"])
check(not z["client"].configured, "Client ist nicht konfiguriert")
check(sa.ANMELDEN_TEXT in (z["hinweis"] or ""), "Hinweis verlangt die Anmeldung", z["hinweis"])
check(sa.aufloesen("unbekannt")["quelle"] == sa.QUELLE_KEINE,
      "Benutzer ohne Zugang: ebenfalls kein Rueckfall")
check(sa.aufloesen("wa:+4917012345")["quelle"] == sa.QUELLE_KEINE,
      "Kanal-Kennung: kein Rueckfall")
info = sa.zugang_info("m.mustermann")
check(info.get("kachel_pflicht") is True and info.get("angemeldet") is False
      and info.get("passwort_gesetzt") is False, "zugang_info: Pflicht an, nicht angemeldet")

# ═══════════════════════════════════════════════════════════════════════════
section("3. Anmelden: Kennwort nur im Arbeitsspeicher")
# ═══════════════════════════════════════════════════════════════════════════
sa.speichern("m.mustermann", dict(ZUGANG, password=KENNWORT))
text = dateitext()
check("_enc" not in text, "nach dem Anmelden kein *_enc in der Datei")
check(KENNWORT not in text, "Kennwort steht auch nicht im Klartext in der Datei")
z = sa.aufloesen("m.mustermann")
check(z["quelle"] == sa.QUELLE_PERSOENLICH, "angemeldet -> persoenlicher Zugang", z["quelle"])
check(z["client"].cfg.get("password") == KENNWORT, "Client traegt das eingegebene Kennwort")
info = sa.zugang_info("m.mustermann")
check(info.get("angemeldet") is True and info.get("passwort_gesetzt") is True
      and info.get("sitzung_bis", 0) > time.time(), "zugang_info: angemeldet mit Ablaufzeit")
check(sa.aufloesen("e.beispiel")["quelle"] == sa.QUELLE_KEINE,
      "die Anmeldung gilt nur fuer DIESEN Benutzer")
# Ein Rest, der vor dem Einschalten liegen blieb, wird beim Speichern entfernt
alle = json.loads(dateitext())
alle["e.beispiel"]["password_enc"] = sa.verschluesseln("altrest")
sa._speichern(alle)
sa.speichern("e.beispiel", {"sap_client": "100"})
check("password_enc" not in json.loads(dateitext()).get("e.beispiel", {}),
      "Speichern mit Schalter raeumt einen Kennwort-Rest ab")
check(sa.aufloesen("e.beispiel")["quelle"] == sa.QUELLE_KEINE,
      "ein Kennwort-Rest auf der Platte meldet NICHT an")

# ═══════════════════════════════════════════════════════════════════════════
section("4. Ende der Anmeldung: Ablauf, Abmelden, Anmeldefehler")
# ═══════════════════════════════════════════════════════════════════════════
# Kein Index-Zugriff: fehlt die Anmeldung (Sabotage), soll das ein FAIL sein,
# kein Absturz ohne Bilanzzeile.
_eintrag = sa._SITZUNG.get("m.mustermann")
check(isinstance(_eintrag, dict), "Anmeldung liegt im Arbeitsspeicher")
if isinstance(_eintrag, dict):
    _eintrag["bis"] = time.time() - 1
    check(sa.aufloesen("m.mustermann")["quelle"] == sa.QUELLE_KEINE, "abgelaufen -> kein Zugang")
sa.speichern("m.mustermann", {"password": KENNWORT})
check(sa.aufloesen("m.mustermann")["quelle"] == sa.QUELLE_PERSOENLICH, "neu angemeldet")
check(sa.sitzung_beenden("FIRMA\\M.Mustermann") is True, "Abmelden (andere Schreibweise) trifft")
check(sa.aufloesen("m.mustermann")["quelle"] == sa.QUELLE_KEINE, "abgemeldet -> kein Zugang")
sa.speichern("m.mustermann", {"password": KENNWORT})
sa.merke_ergebnis("m.mustermann", False, "401 Unauthorized", anmeldefehler=True)
check(sa.aufloesen("m.mustermann")["quelle"] == sa.QUELLE_KEINE,
      "Anmeldefehler beendet die Anmeldung (kein Wiederholen im Takt)")
sa.speichern("m.mustermann", {"password": KENNWORT})
sa.merke_ergebnis("m.mustermann", False, "insufficient privilege", anmeldefehler=False)
check(sa.aufloesen("m.mustermann")["quelle"] == sa.QUELLE_PERSOENLICH,
      "Berechtigungsfehler laesst die Anmeldung stehen")
try:
    sa.speichern("m.mustermann", {"odata_base_url": "https://boese.example.org/x",
                                   "password": "neu"})
    check(False, "fremder Server wird abgelehnt")
except sa.SapKontoFehler:
    check(sa.aufloesen("m.mustermann")["client"].cfg.get("password") == KENNWORT,
          "abgelehntes Speichern aendert die Anmeldung nicht")
sa.loeschen("m.mustermann")
check("m.mustermann" not in sa._SITZUNG, "Zugang entfernen beendet die Anmeldung")

# ═══════════════════════════════════════════════════════════════════════════
section("6. Anmeldekarte: direkt nach dem Kennwort fragen")
# ═══════════════════════════════════════════════════════════════════════════
# e.beispiel: Zugang vorhanden, nicht angemeldet, noch NIE erfolgreich verbunden
sa.sitzung_beenden("e.beispiel")
check(sa.anmeldung_anbieten("e.beispiel") == {},
      "nie erfolgreich verbunden -> keine Kennwort-Abfrage (erst einrichten)")
sa.merke_ergebnis("e.beispiel", True)
a6 = sa.anmeldung_anbieten("e.beispiel")
check(a6.get("feld") == "password" and a6.get("benutzer") == "BEISPIEL",
      "schon einmal verbunden -> Abfrage mit SAP-Benutzer und Feld", str(a6))
sa.speichern("e.beispiel", {"password": "x"})
check(sa.anmeldung_anbieten("e.beispiel") == {}, "angemeldet -> keine Abfrage")
sa.sitzung_beenden("e.beispiel")
sa.speichern("e.beispiel", {"aktiv": False})
check(sa.anmeldung_anbieten("e.beispiel") == {}, "inaktiver Zugang -> keine Abfrage")
sa.speichern("e.beispiel", {"aktiv": True, "auth_kind": "bearer"})
check(sa.anmeldung_anbieten("e.beispiel").get("feld") == "bearer_token",
      "Token-Anmeldung fragt nach dem Token")
sa.speichern("e.beispiel", {"auth_kind": "basic"})
check(sa.anmeldung_anbieten("wa:+4917012345") == {}, "Kanal-Kennung -> keine Abfrage")
admin(False)
check(sa.anmeldung_anbieten("e.beispiel") == {}, "Schalter aus -> keine Abfrage")
admin(True)
check("Kachel" not in sa.ANMELDEN_TEXT and len(sa.ANMELDEN_TEXT) < 80,
      "Hinweistext ist kurz", sa.ANMELDEN_TEXT)

# ═══════════════════════════════════════════════════════════════════════════
section("5. Regeln in main.py (Syntaxbaum)")
# ═══════════════════════════════════════════════════════════════════════════
try:
    baum = ast.parse(MAIN.read_text(encoding="utf-8"))
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: main.py nicht lesbar: {e}")
    sys.exit(2)
fn = {n.name: n for n in ast.walk(baum) if isinstance(n, ast.AsyncFunctionDef)}
usc, lo = fn.get("update_skill_config"), fn.get("logout")
if usc is None or lo is None:
    print("ABBRUCH: update_skill_config/logout nicht gefunden")
    sys.exit(2)


def _aufrufe(knoten, name):
    return [n for n in ast.walk(knoten) if isinstance(n, ast.Call)
            and ((isinstance(n.func, ast.Attribute) and n.func.attr == name)
                 or (isinstance(n.func, ast.Name) and n.func.id == name))]


def _leer_zuweisungen(knoten):
    """Zeilen von ``body[<x>] = ""`` in einer Schleife ueber GEHEIMFELDER."""
    out = []
    for f in ast.walk(knoten):
        if not (isinstance(f, ast.For) and isinstance(f.iter, ast.Attribute)
                and f.iter.attr == "GEHEIMFELDER"):
            continue
        for a in ast.walk(f):
            if (isinstance(a, ast.Assign) and isinstance(a.targets[0], ast.Subscript)
                    and isinstance(a.targets[0].value, ast.Name)
                    and a.targets[0].value.id == "body"
                    and isinstance(a.value, ast.Constant) and a.value.value == ""):
                out.append(a.lineno)
    return out


behalten = [c.lineno for c in _aufrufe(usc, "leere_geheimfelder_behalten")]
speichern = [c.lineno for c in _aufrufe(usc, "update_skill_config")]
leer = _leer_zuweisungen(usc)
check(bool(behalten) and bool(speichern), "Positivkontrolle: Behalten und Speichern gefunden")
check(any(min(behalten) < z_ < min(speichern) for z_ in leer),
      "Geheimfelder werden NACH dem Behalten und VOR dem Speichern geleert",
      f"behalten={behalten} leer={leer} speichern={speichern}")
check(any(c.lineno > min(speichern) for c in _aufrufe(usc, "kennwoerter_entfernen")),
      "nach dem Speichern werden die Kennwoerter der eigenen Zugaenge entfernt")
# Auf genau dem Namen, unter dem sap_accounts importiert wurde – seit auch
# VEMAS dort eine Sitzung beendet, waere "irgendein Aufruf" trivial wahr.
sap_namen = {(a.asname or a.name) for n in ast.walk(lo) if isinstance(n, ast.ImportFrom)
             for a in n.names if a.name == "sap_accounts"}
check(bool(sap_namen) and any(isinstance(c.func.value, ast.Name) and c.func.value.id in sap_namen
                              for c in _aufrufe(lo, "sitzung_beenden")),
      "Jarvis-Abmeldung beendet die SAP-Anmeldung", str(sap_namen))
st = next((n for n in ast.walk(baum) if isinstance(n, ast.AsyncFunctionDef)
           and n.name == "sap_portal_status"), None)
adm = next((n for n in ast.walk(baum) if isinstance(n, ast.AsyncFunctionDef)
            and n.name == "sap_admin_accounts"), None)
check(adm is not None and bool(_aufrufe(adm, "kennwort_gespeichert"))
      and bool(_aufrufe(adm, "kachel_pflicht")),
      "Admin-Liste meldet gespeicherte Kennwoerter und den Schalter")
check(st is not None and bool(_aufrufe(st, "anmeldung_anbieten")),
      "Status-Endpunkt liefert die Anmeldekarte mit")

print("\n" + "=" * 60)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
