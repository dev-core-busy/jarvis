#!/usr/bin/env python3
"""Waechter: VEMAS "Anmeldung ueber die Portal-Kachel fordern" (2026-11-05,
analog zu SAP, tests/test_sap_kachel_anmeldung.py).

Zusagen (backend/vemas_accounts.py, Abschnitt "Anmeldung ueber die Portal-Kachel",
backend/main.py::update_skill_config / logout / vemas_status / vemas_admin_accounts):

* Mit dem Schalter liegt kein VEMAS-Kennwort/-Token auf der Platte.
* Beim Einschalten verlieren alle eigenen Zugaenge ihre Kennwoerter; die Zugaenge
  (Anmeldeart, Benutzer) bleiben und gelten weiter als EINGERICHTET.
* Ein Kennwort gilt nur im Arbeitsspeicher: Ablauf, Abmelden, Anmeldefehler.
* Ohne Anmeldung kein Zugang und KEIN Rueckfall auf den Sammelzugang.
* Die Anmeldekarte fragt nur, wenn der Zugang schon einmal funktioniert hat.

Sabotierte Kopien fuer die Gegenprobe ueber VEMAS_KACHEL_MODUL / VEMAS_KACHEL_MAIN.
Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.

    python3 tests/test_vemas_kachel_anmeldung.py
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


TMP = Path(tempfile.mkdtemp(prefix="vemaskachel_test_"))
_skill_states = {"vemas": {"enabled": True, "config": {}}}
_cfg_mod = types.ModuleType("backend.config")


class _Cfg:
    def get_skill_states(self):
        return _skill_states

    def get_setting(self, key, default=None):
        return default

    def save_setting(self, key, value):
        pass


_cfg_mod.config = _Cfg()
sys.modules["backend.config"] = _cfg_mod

MODUL = Path(os.environ.get("VEMAS_KACHEL_MODUL") or ROOT / "backend" / "vemas_accounts.py")
MAIN = Path(os.environ.get("VEMAS_KACHEL_MAIN") or ROOT / "backend" / "main.py")
try:
    import backend  # noqa: F401
    _spec = importlib.util.spec_from_file_location("backend.vemas_accounts", MODUL)
    va = importlib.util.module_from_spec(_spec)
    sys.modules["backend.vemas_accounts"] = va
    _spec.loader.exec_module(va)
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: vemas_accounts nicht importierbar: {e}")
    sys.exit(2)

va.DATA_DIR = TMP
va.KONTEN_DATEI = TMP / "vemas_accounts.json"
va.SCHLUESSEL_DATEI = TMP / ".vemaskey"
for pfad in (va.KONTEN_DATEI, va.SCHLUESSEL_DATEI):
    if not str(pfad).startswith(str(TMP)):
        print(f"SANDKASTEN VERLETZT: {pfad}")
        sys.exit(2)

KENNWORT = "Vemas-Probe-4711"
SAMMEL = dict(base_url="https://vemas.beispiel.de/api", auth_kind="basic",
              username="SAMMEL", password="sammel-kennwort")


def admin(pflicht: bool):
    c = dict(SAMMEL)
    if pflicht:
        c["kachel_anmeldung"] = True
        c["password"] = ""
    _skill_states["vemas"]["config"] = c


def dateitext() -> str:
    return va.KONTEN_DATEI.read_text(encoding="utf-8") if va.KONTEN_DATEI.exists() else ""


ZUGANG = {"auth_kind": "basic", "username": "MUSTER"}

# ═══════════════════════════════════════════════════════════════════════════
section("0. Positivkontrolle: ohne Schalter wird das Kennwort gespeichert")
# ═══════════════════════════════════════════════════════════════════════════
admin(False)
try:
    va.speichern("m.mustermann", dict(ZUGANG, password=KENNWORT))
    va.speichern("e.beispiel", {"auth_kind": "bearer", "api_token": "tok-1"})
except va.VemasKontoFehler as e:
    print(f"ABBRUCH: Speichern ohne Schalter scheitert ({e})")
    sys.exit(2)
roh = json.loads(dateitext() or "{}")
if not (roh.get("m.mustermann", {}).get("password_enc") and roh.get("e.beispiel", {}).get("api_token_enc")):
    print("ABBRUCH: ohne Schalter liegt kein verschluesseltes Kennwort – Pruefungen waeren trivial")
    sys.exit(2)
z = va.aufloesen("m.mustermann")
if z["quelle"] != va.QUELLE_PERSOENLICH:
    print(f"ABBRUCH: ohne Schalter gilt der persoenliche Zugang nicht ({z['quelle']})")
    sys.exit(2)
check(va.kennwort_gespeichert("FIRMA\\M.Mustermann") is True,
      "Positivkontrolle: kennwort_gespeichert erkennt das gespeicherte Kennwort")
check(va.kachel_pflicht() is False, "Schalter aus -> kachel_pflicht() False")

# ═══════════════════════════════════════════════════════════════════════════
section("1. Einschalten: Kennwoerter weg, Zugaenge bleiben eingerichtet")
# ═══════════════════════════════════════════════════════════════════════════
admin(True)
n = va.kennwoerter_entfernen()
check(n == 2, "zwei Zugaenge verloren ihr Kennwort/Token", f"n={n}")
check("_enc" not in dateitext(), "kein *_enc mehr in der Kontendatei")
roh = json.loads(dateitext() or "{}")
check(roh.get("m.mustermann", {}).get("username") == "MUSTER", "Benutzer bleibt erhalten")
check(va.zugang_info("m.mustermann").get("vorhanden") is True,
      "Zugang gilt ohne Kennwort weiter als eingerichtet")
check(va.kennwoerter_entfernen() == 0, "zweiter Lauf entfernt nichts mehr")

# ═══════════════════════════════════════════════════════════════════════════
section("2. Ohne Anmeldung: kein Zugang, kein Rueckfall")
# ═══════════════════════════════════════════════════════════════════════════
z = va.aufloesen("m.mustermann")
check(z["quelle"] == va.QUELLE_KEINE, "Quelle 'keine' statt Sammelzugang", z["quelle"])
check(not z["client"].configured, "Client ist nicht konfiguriert")
check(va.ANMELDEN_TEXT in (z["hinweis"] or ""), "Hinweis verlangt die Anmeldung", z["hinweis"])
check(va.aufloesen("unbekannt")["quelle"] == va.QUELLE_KEINE, "Benutzer ohne Zugang: kein Rueckfall")
check(va.aufloesen("wa:+4917012345")["quelle"] == va.QUELLE_KEINE, "Kanal-Kennung: kein Rueckfall")

# ═══════════════════════════════════════════════════════════════════════════
section("3. Anmelden: Kennwort nur im Arbeitsspeicher")
# ═══════════════════════════════════════════════════════════════════════════
try:
    va.speichern("m.mustermann", {"password": KENNWORT})
    check(True, "Anmelden (nur das Kennwort) wird angenommen")
except va.VemasKontoFehler as e:
    check(False, "Anmelden (nur das Kennwort) wird angenommen", str(e))
text = dateitext()
check("_enc" not in text and KENNWORT not in text, "weder verschluesselt noch im Klartext auf der Platte")
z = va.aufloesen("m.mustermann")
check(z["quelle"] == va.QUELLE_PERSOENLICH, "angemeldet -> persoenlicher Zugang", z["quelle"])
check(getattr(z["client"], "password", None) == KENNWORT, "Client traegt das eingegebene Kennwort")
info = va.zugang_info("m.mustermann")
check(info.get("angemeldet") is True and info.get("passwort_gesetzt") is True
      and info.get("sitzung_bis", 0) > time.time(), "zugang_info: angemeldet mit Ablaufzeit")
check(va.aufloesen("e.beispiel")["quelle"] == va.QUELLE_KEINE, "Anmeldung gilt nur fuer DIESEN Benutzer")
alle = json.loads(dateitext())
alle["e.beispiel"]["api_token_enc"] = va.verschluesseln("altrest")
va._speichern(alle)
va.speichern("e.beispiel", {"aktiv": True})
check("api_token_enc" not in json.loads(dateitext()).get("e.beispiel", {}),
      "Speichern mit Schalter raeumt einen Token-Rest ab")

# ═══════════════════════════════════════════════════════════════════════════
section("4. Ende der Anmeldung")
# ═══════════════════════════════════════════════════════════════════════════
_eintrag = va._SITZUNG.get("m.mustermann")
check(isinstance(_eintrag, dict), "Anmeldung liegt im Arbeitsspeicher")
if isinstance(_eintrag, dict):
    _eintrag["bis"] = time.time() - 1
    check(va.aufloesen("m.mustermann")["quelle"] == va.QUELLE_KEINE, "abgelaufen -> kein Zugang")
va.speichern("m.mustermann", {"password": KENNWORT})
check(va.sitzung_beenden("FIRMA\\M.Mustermann") is True, "Abmelden (andere Schreibweise) trifft")
check(va.aufloesen("m.mustermann")["quelle"] == va.QUELLE_KEINE, "abgemeldet -> kein Zugang")
va.speichern("m.mustermann", {"password": KENNWORT})
va.merke_ergebnis("m.mustermann", False, "401 Unauthorized", anmeldefehler=True)
check(va.aufloesen("m.mustermann")["quelle"] == va.QUELLE_KEINE, "Anmeldefehler beendet die Anmeldung")
va.speichern("m.mustermann", {"password": KENNWORT})
va.merke_ergebnis("m.mustermann", False, "403 keine Berechtigung", anmeldefehler=False)
check(va.aufloesen("m.mustermann")["quelle"] == va.QUELLE_PERSOENLICH,
      "Berechtigungsfehler laesst die Anmeldung stehen")

# ═══════════════════════════════════════════════════════════════════════════
section("5. Anmeldekarte")
# ═══════════════════════════════════════════════════════════════════════════
va.sitzung_beenden("m.mustermann")
alle = json.loads(dateitext()); alle["m.mustermann"]["letzter_erfolg"] = 0; va._speichern(alle)
check(va.anmeldung_anbieten("m.mustermann") == {}, "nie erfolgreich verbunden -> keine Abfrage")
va.merke_ergebnis("m.mustermann", True)
a5 = va.anmeldung_anbieten("m.mustermann")
check(a5.get("feld") == "password" and a5.get("benutzer") == "MUSTER",
      "schon einmal verbunden -> Abfrage mit Benutzer und Feld", str(a5))
va.speichern("m.mustermann", {"password": "x"})
check(va.anmeldung_anbieten("m.mustermann") == {}, "angemeldet -> keine Abfrage")
va.merke_ergebnis("e.beispiel", True)
check(va.anmeldung_anbieten("e.beispiel").get("feld") == "api_token", "Token-Anmeldung fragt nach dem Token")
admin(False)
check(va.anmeldung_anbieten("e.beispiel") == {}, "Schalter aus -> keine Abfrage")
admin(True)
va.loeschen("m.mustermann")
check("m.mustermann" not in va._SITZUNG, "Zugang entfernen beendet die Anmeldung")

# ═══════════════════════════════════════════════════════════════════════════
section("6. Regeln in main.py (Syntaxbaum)")
# ═══════════════════════════════════════════════════════════════════════════
try:
    baum = ast.parse(MAIN.read_text(encoding="utf-8"))
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: main.py nicht lesbar: {e}")
    sys.exit(2)
fn = {n.name: n for n in ast.walk(baum) if isinstance(n, ast.AsyncFunctionDef)}
if not all(k in fn for k in ("update_skill_config", "logout", "vemas_status", "vemas_admin_accounts")):
    print("ABBRUCH: Endpunkte nicht gefunden")
    sys.exit(2)


def _aufrufe(knoten, name):
    return [n for n in ast.walk(knoten) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == name]


usc = fn["update_skill_config"]
gilt_vemas = any(isinstance(n, ast.Constant) and n.value == "vemas"
                 for c in ast.walk(usc) if isinstance(c, ast.Compare) for n in ast.walk(c))
check(gilt_vemas, "update_skill_config behandelt den Schalter auch fuer 'vemas'")
check(any(isinstance(n, ast.ImportFrom) and any(a.name == "vemas_accounts" for a in n.names)
          for n in ast.walk(usc)), "update_skill_config nutzt dabei vemas_accounts")
# Nicht nur "irgendein sitzung_beenden": der SAP-Aufruf daneben machte die
# Pruefung sonst trivial wahr (von der Gegenprobe gefunden). Gemessen wird der
# Aufruf auf genau dem Namen, unter dem vemas_accounts importiert wurde.
vm_namen = {(a.asname or a.name) for n in ast.walk(fn["logout"]) if isinstance(n, ast.ImportFrom)
            for a in n.names if a.name == "vemas_accounts"}
vm_ruf = [c for c in _aufrufe(fn["logout"], "sitzung_beenden")
          if isinstance(c.func.value, ast.Name) and c.func.value.id in vm_namen]
check(bool(vm_namen) and bool(vm_ruf), "Jarvis-Abmeldung beendet auch die VEMAS-Anmeldung",
      str(vm_namen))
check(bool(_aufrufe(fn["vemas_status"], "anmeldung_anbieten")), "Status liefert die Anmeldekarte mit")
check(bool(_aufrufe(fn["vemas_admin_accounts"], "kennwort_gespeichert")),
      "Admin-Liste meldet gespeicherte Kennwoerter")

print("\n" + "=" * 60)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
