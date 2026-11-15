#!/usr/bin/env python3
"""Waechter: "Persoenliche Zugaenge erlauben" in Confluence – und warum SAP
und VEMAS KEINEN eigenen Schalter dieser Art haben.

Vorgabe des Betreibers (2026-11-15): derselbe Schalter wie unter
Einstellungen → Jira. Fuer Confluence heisst AUS:

* ``speichern`` und ``testen`` weisen einen persoenlichen Token ab,
* ``aufloesen`` benutzt den gemeinsamen Zugang – auch wenn noch ein Rest in
  der Datei liegt (der Schalter entscheidet, nicht die Datei),
* ``alle_entfernen`` leert die Kontendatei,
* ``zugang_info`` meldet ``persoenlich_erlaubt`` (die Bereichsseite blendet
  "Mein Confluence-Zugang" damit aus).

SAP/VEMAS (Betreiber, gleicher Tag): dort IST "Persoenliche Zugaenge erlauben
= aus" die Anmeldung ueber die Portal-Kachel (gespeichert als
``kachel_anmeldung``, gemessen in test_sap_kachel_anmeldung u. a.). Ein Feld
``persoenliche_zugaenge`` – etwa ein Rest aus einem Zwischenstand – darf dort
NICHTS bewirken: kein Abweisen, kein Rueckfall, kein Ausblenden.

Gemessen wird an den ECHTEN Modulen, in einem Sandkasten (Exit 2, wenn er
nicht greift). ``backend.config`` ist eine Attrappe – der echte Import schreibt
die Live-settings.json zurueck. Die Skill-Konfiguration kommt ueber
Attrappen der ``get_*_config``-Funktionen, die die Module selbst rufen.

Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.
    python3 tests/test_persoenlich_schalter.py
"""
import os
import sys
import tempfile
import types
from pathlib import Path

# Die Gegenprobe gibt eine sabotierte KOPIE des Pakets ueber PERS_ROOT mit –
# die echten Dateien werden nie angefasst.
ROOT = Path(os.environ.get("PERS_ROOT") or Path(__file__).resolve().parent.parent)
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if not isinstance(cond, bool):
        print(f"ABBRUCH: check() erwartet eine Bedingung, bekam {type(cond).__name__} "
              f"({label!r}) – vertauschte Argumente?")
        sys.exit(2)
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def section(t):
    print(f"\n═══ {t}")


if "backend.config" not in sys.modules:
    _cfg = types.ModuleType("backend.config")

    class _C:
        def get_skill_states(self):
            return {}

        def get_setting(self, k, d=None):
            return d

    _cfg.config = _C()
    sys.modules["backend.config"] = _cfg

try:
    import cryptography  # noqa: F401
    from backend import confluence_accounts as ca  # noqa: E402
    from backend import sap_accounts as sa  # noqa: E402
    from backend import vemas_accounts as va  # noqa: E402
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Module nicht importierbar: {e}")
    sys.exit(2)

# ── Sandkasten ───────────────────────────────────────────────────────────────
_tmp = tempfile.mkdtemp(prefix="persoenlich-test-")
for mod, name in ((ca, "confluence"), (sa, "sap"), (va, "vemas")):
    mod.DATA_DIR = Path(_tmp)
    mod.KONTEN_DATEI = Path(_tmp) / f"{name}_accounts.json"
    mod.SCHLUESSEL_DATEI = Path(_tmp) / f".{name}key"
    for _n in ("KONTEN_DATEI", "SCHLUESSEL_DATEI", "DATA_DIR"):
        if not str(getattr(mod, _n)).startswith(_tmp):
            print(f"ABBRUCH: Sandkasten greift nicht – {name}.{_n}")
            sys.exit(2)

CFG = {
    "confluence": {"base_url": "https://wiki.beispiel.de", "api_token": "SAMMEL"},
    "sap": {"connection_type": "odata",
            "odata_base_url": "https://sap.beispiel.de/sap/opu/odata",
            "username": "sammel", "password": "SAMMEL",
            "allowed_hosts": "sap.beispiel.de"},
    "vemas": {"base_url": "https://vemas.beispiel.de/api", "auth_kind": "basic",
              "username": "sammel", "password": "SAMMEL"},
}
ca.get_confluence_config = lambda: CFG["confluence"]
sa.get_sap_config = lambda: CFG["sap"]
va.get_vemas_config = lambda: CFG["vemas"]
# Die Clients lesen ihre Sammel-Konfiguration selbst – ebenfalls umlenken.
import backend.confluence_client as _cc  # noqa: E402
import backend.sap_client as _sc  # noqa: E402
import backend.vemas_client as _vc  # noqa: E402
_cc.get_confluence_config = lambda: CFG["confluence"]
_sc.get_sap_config = lambda: CFG["sap"]
_vc.get_vemas_config = lambda: CFG["vemas"]

ZUGANG = {
    "confluence": {"api_token": "EIGEN"},
    "sap": {"connection_type": "odata",
            "odata_base_url": "https://sap.beispiel.de/sap/opu/odata",
            "username": "eigen", "password": "EIGEN"},
    "vemas": {"auth_kind": "basic", "username": "eigen", "password": "EIGEN"},
}
FEHLER = {"confluence": ca.ConfluenceKontoFehler, "sap": sa.SapKontoFehler,
          "vemas": va.VemasKontoFehler}
MODUL = {"confluence": ca, "sap": sa, "vemas": va}
USER = "anna.beispiel"


def schalter(name, wert):
    c = CFG[name]
    c.pop("persoenliche_zugaenge", None)
    if wert is not None:
        c["persoenliche_zugaenge"] = wert


def frisch():
    for m in MODUL.values():
        if m.KONTEN_DATEI.exists():
            m.KONTEN_DATEI.unlink()
    sa._SITZUNG.clear()
    va._SITZUNG.clear()
    CFG["sap"].pop("kachel_anmeldung", None)
    CFG["vemas"].pop("kachel_anmeldung", None)


def wirft(fn, typ):
    try:
        fn()
    except typ as e:
        return str(e)
    except Exception as e:  # noqa: BLE001
        return f"FALSCHER TYP {type(e).__name__}: {e}"
    return None


for name in ("confluence",):
    m = MODUL[name]
    F = FEHLER[name]

    section(f"{name}: Positivkontrolle – erlaubt (Feld fehlt) wirkt der eigene Zugang")
    frisch()
    schalter(name, None)
    check(m.persoenlich_erlaubt() is True, "Vorgabe (Feld fehlt) = erlaubt")
    try:
        m.speichern(USER, dict(ZUGANG[name]))
        gespeichert = True
    except Exception as e:  # noqa: BLE001
        gespeichert = False
        print(f"       ({type(e).__name__}: {e})")
    check(gespeichert, "speichern legt den eigenen Zugang an")
    z = m.aufloesen(USER)
    # Ohne diese Kontrolle waere "AUS ergibt sammel" trivial wahr.
    check(z.get("quelle") == m.QUELLE_PERSOENLICH,
          "Positivkontrolle: der eigene Zugang gilt", str(z.get("hinweis")))
    check(m.zugang_info(USER).get("persoenlich_erlaubt") is True,
          "zugang_info meldet erlaubt")

    section(f"{name}: abgeschaltet")
    schalter(name, False)
    check(m.persoenlich_erlaubt() is False, "Schalter AUS wird erkannt")
    z = m.aufloesen(USER)
    check(z.get("quelle") == m.QUELLE_SAMMEL,
          "Rest in der Datei greift NICHT – es gilt der gemeinsame Zugang",
          str(z.get("quelle")))
    check(m.zugang_info(USER).get("persoenlich_erlaubt") is False,
          "zugang_info meldet abgeschaltet (die Bereichsseite blendet aus)")
    grund = wirft(lambda: m.speichern(USER, dict(ZUGANG[name])), F)
    check(bool(grund) and "abgeschaltet" in grund,
          "speichern wird mit Grund abgewiesen", str(grund))
    if hasattr(m, "_konto_fuer_schreiben"):
        grund = wirft(lambda: m._konto_fuer_schreiben(USER), F)
        check(bool(grund) and "abgeschaltet" in grund,
              "auch jeder andere Schreibweg (_konto_fuer_schreiben)", str(grund))
    if name == "confluence":
        grund = wirft(lambda: m.testen(USER), F)
        check(bool(grund) and "abgeschaltet" in grund,
              "der Verbindungstest des eigenen Tokens wird abgewiesen", str(grund))

    section(f"{name}: alle_entfernen")
    # Drei Zugaenge auf der Platte (Inhalt egal – geloescht wird der Datensatz)
    m._speichern({"a": {"benutzer_norm": "a"}, "b": {"benutzer_norm": "b"},
                  "c": {"benutzer_norm": "c"}})
    n = m.alle_entfernen()
    check(n == 3, "gibt die Zahl der entfernten Zugaenge zurueck", str(n))
    check(m._laden() == {}, "die Kontendatei ist leer", str(m._laden()))
    check(m.alle_benutzer() == [], "niemand hat mehr einen eigenen Zugang")
    check(m.alle_entfernen() == 0, "zweiter Aufruf: nichts mehr da, 0")

    section(f"{name}: wieder erlaubt")
    schalter(name, True)
    try:
        m.speichern(USER, dict(ZUGANG[name]))
        ok = True
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"       ({type(e).__name__}: {e})")
    check(ok and m.aufloesen(USER).get("quelle") == m.QUELLE_PERSOENLICH,
          "nach dem Einschalten laesst sich wieder ein Zugang anlegen und er gilt")

for name in ("sap", "vemas"):
    m = MODUL[name]
    section(f"{name}: kein zweiter Schalter – persoenliche_zugaenge wirkt nicht")
    frisch()
    CFG[name]["persoenliche_zugaenge"] = False
    try:
        m.speichern(USER, dict(ZUGANG[name]))
        ok = True
    except Exception as e:  # noqa: BLE001
        ok = False
        print(f"       ({type(e).__name__}: {e})")
    check(ok, "speichern wird NICHT abgewiesen")
    z = m.aufloesen(USER)
    check(z.get("quelle") == m.QUELLE_PERSOENLICH,
          "der eigene Zugang gilt (kein Rueckfall auf den gemeinsamen)", str(z.get("hinweis")))
    check("persoenlich_erlaubt" not in m.zugang_info(USER),
          "zugang_info meldet keinen Schalter (die Bereichsseite blendet nichts aus)")
    # Abhaken (Betreiber 2026-11-15): ALLE Zugaenge weg, auch die Anmeldungen
    # im Arbeitsspeicher. Ausgeloest von main.update_skill_config beim Umschalten.
    m._SITZUNG[m.norm_user(USER)] = {"felder": {"password": "x"}, "bis": 9e12}
    n = m.alle_entfernen() if hasattr(m, "alle_entfernen") else None
    check(n == 1, "alle_entfernen meldet den einen Zugang", repr(n))
    check(m._laden() == {}, "danach liegt kein persoenlicher Zugang mehr auf der Platte",
          str(list(m._laden())))
    check(not m._SITZUNG, "danach ist auch keine Anmeldung im Arbeitsspeicher mehr")
    check(m.alle_entfernen() == 0 if hasattr(m, "alle_entfernen") else False,
          "zweiter Aufruf: nichts mehr zu entfernen")
    try:
        m.speichern(USER, dict(ZUGANG[name]))
    except Exception as e:  # noqa: BLE001
        # Kein Wurf ohne Bilanzzeile: die Abweisung meldet die Pruefung oben.
        print(f"       ({type(e).__name__}: {e})")
    # Gegenstueck: AUS ist die Kachelpflicht. Seit 2026-11-15 (Betreiber: wie
    # Jira/Confluence) gilt ohne Anmeldung der gemeinsame Zugang – aber nur,
    # wenn er VOLLSTAENDIG eingetragen ist (mit Kennwort).
    CFG[name]["kachel_anmeldung"] = True
    z = m.aufloesen(USER)
    check(z.get("quelle") == m.QUELLE_SAMMEL and z.get("client") is not None
          and z["client"].configured,
          "Kachelpflicht (= persoenlich aus) ohne Anmeldung: Rueckfall auf den gemeinsamen Zugang",
          str(z.get("quelle")))
    check("gemeinsame" in (z.get("hinweis") or ""),
          "der Hinweis nennt den gemeinsamen Zugang", str(z.get("hinweis")))
    _pw = CFG[name].pop("password")
    z = m.aufloesen(USER)
    check(z.get("quelle") == m.QUELLE_KEINE,
          "gemeinsamer Zugang ohne Kennwort: KEIN Rueckfall (sonst nur abgelehnte Anmeldungen)",
          str(z.get("quelle")))
    CFG[name]["password"] = _pw
    CFG[name].pop("persoenliche_zugaenge", None)
    frisch()

print("\n" + "=" * 60)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
