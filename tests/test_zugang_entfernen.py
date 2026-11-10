#!/usr/bin/env python3
"""Waechter: "Eigenen Zugang entfernen" – die Auskunft des Servers (2026-11-10).

GEMELDET: der Knopf stand unter "Mein SAP-Zugang" immer da, auch ohne
hinterlegten Zugang, und ein Klick meldete dann "Eigener Zugang entfernt.".

Zusagen (backend/sap_accounts.py, backend/vemas_accounts.py, backend/main.py):

* ``zugang_info()`` traegt ``gespeichert`` – wahr genau dann, wenn fuer den
  Benutzer ein Datensatz in der Kontendatei liegt.
* ``gespeichert`` ist NICHT ``vorhanden``: ein halb ausgefuellter Zugang ist
  nicht verbindungsfaehig (``vorhanden`` falsch), aber entfernbar.
* ``gespeichert`` und ``loeschen()`` beantworten DIESELBE Frage: was die
  Auskunft als entfernbar meldet, entfernt ``loeschen()`` auch – und umgekehrt.
* Der DELETE-Endpunkt reicht das Ergebnis als ``removed`` durch (daran haengt
  die Meldung der Oberflaeche).

Die Sichtbarkeit selbst misst ``test_zugang_entfernen_ui.js`` (Verhalten) und
``test_zugang_knopf_chrome.py`` (ob ``hidden`` im Browser ueberhaupt wirkt).

Laeuft ohne fastapi und ohne Zielsystem; ``backend.config`` ist eine Attrappe
(der echte Import schreibt die Live-settings.json zurueck). Die Zugaenge
entstehen ueber das ECHTE ``speichern()``, nicht von Hand in der Datei.

ZUGANG_SAP_MODUL / ZUGANG_VEMAS_MODUL / ZUGANG_MAIN legen sabotierte KOPIEN vor
(Gegenprobe tests/gegen_zugang_entfernen.py).
Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.

    python3 tests/test_zugang_entfernen.py
"""
import ast
import importlib.util
import os
import sys
import tempfile
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


def abbruch(text):
    print(f"ABBRUCH: {text}")
    sys.exit(2)


# ── Attrappe fuer backend.config VOR dem Import ─────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="zugang_entfernen_test_"))
_skill_states = {
    "sap": {"enabled": True, "config": {
        "connection_type": "odata", "odata_base_url": "https://s4.firma.local/sap/opu/odata",
        "username": "SAMMEL", "password": "sammel-kennwort", "allowed_hosts": "firma.local"}},
    "vemas": {"enabled": True, "config": {
        "base_url": "https://vemas.beispiel.de/api", "auth_kind": "basic",
        "username": "SAMMEL", "password": "sammel-kennwort"}},
}
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


def laden(name: str, umgebung: str, kontendatei: str, schluessel: str):
    pfad = Path(os.environ.get(umgebung) or ROOT / "backend" / f"{name}.py")
    try:
        import backend  # noqa: F401  – Paket zuerst, sonst kein backend.<client>
        spec = importlib.util.spec_from_file_location(f"backend.{name}", pfad)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[f"backend.{name}"] = mod
        spec.loader.exec_module(mod)
    except Exception as e:  # noqa: BLE001
        abbruch(f"{name} nicht importierbar: {e}")
    ablage = TMP / name
    ablage.mkdir()
    mod.DATA_DIR = ablage
    mod.KONTEN_DATEI = ablage / kontendatei
    mod.SCHLUESSEL_DATEI = ablage / schluessel
    for p in (mod.KONTEN_DATEI, mod.SCHLUESSEL_DATEI):
        if not str(p).startswith(str(TMP)):
            abbruch(f"SANDKASTEN VERLETZT: {p}")
    return mod


sa = laden("sap_accounts", "ZUGANG_SAP_MODUL", "sap_accounts.json", ".sapkey")
va = laden("vemas_accounts", "ZUGANG_VEMAS_MODUL", "vemas_accounts.json", ".vemaskey")

# (Titel, Modul, vollstaendiger Zugang, halb ausgefuellter Zugang)
FAELLE = [
    ("SAP", sa,
     {"connection_type": "odata", "odata_base_url": "https://s4.firma.local/sap/opu/odata",
      "username": "MUSTER", "password": "Probe-4711"},
     {"connection_type": "odata"}),
    ("VEMAS", va,
     {"auth_kind": "basic", "username": "MUSTER", "password": "Probe-4711"},
     {"auth_kind": "basic", "username": "MUSTER"}),
]

for nr, (titel, mod, voll, halb) in enumerate(FAELLE, 1):
    # ═══════════════════════════════════════════════════════════════════════
    section(f"{nr}. {titel}: gespeichert folgt dem Datensatz, nicht der Vollstaendigkeit")
    # ═══════════════════════════════════════════════════════════════════════
    # Positivkontrolle: der Messaufbau stellt die drei Lagen wirklich her –
    # sonst waeren die Pruefungen darunter trivial wahr.
    try:
        vor = mod.zugang_info("anna")
        mod.speichern("anna", dict(voll))
        ganz = mod.zugang_info("anna")
        mod.speichern("bert", dict(halb))
        teil = mod.zugang_info("bert")
    except Exception as e:  # noqa: BLE001
        abbruch(f"{titel}: Speichern im Sandkasten scheitert ({type(e).__name__}: {e})")
    if vor.get("vorhanden") is not False or ganz.get("vorhanden") is not True:
        abbruch(f"{titel}: 'vorhanden' folgt dem vollstaendigen Zugang nicht "
                f"(vorher {vor.get('vorhanden')!r}, nachher {ganz.get('vorhanden')!r})")
    if teil.get("vorhanden") is not False:
        abbruch(f"{titel}: der halb ausgefuellte Zugang gilt als vollstaendig – "
                "die Trennung von 'vorhanden' waere nicht messbar")

    check(vor.get("gespeichert") is False,
          "ohne Datensatz: gespeichert ist False", repr(vor.get("gespeichert")))
    check(ganz.get("gespeichert") is True,
          "vollstaendiger Zugang: gespeichert ist True", repr(ganz.get("gespeichert")))
    check(teil.get("gespeichert") is True,
          "halb ausgefuellter Zugang: gespeichert ist True, obwohl vorhanden False ist",
          repr(teil.get("gespeichert")))
    check(mod.zugang_info("FIRMA\\Anna").get("gespeichert") is True,
          "die Anmeldeform FIRMA\\Anna trifft denselben Datensatz")
    check(mod.zugang_info("carla").get("gespeichert") is False,
          "ein fremder Datensatz macht den eigenen nicht entfernbar")

    # Dieselbe Frage wie loeschen(): je Lage die Auskunft VOR dem Loeschen
    # gegen das Ergebnis des Loeschens.
    paare = []
    for wer in ("bert", "anna", "carla", "anna"):
        gemeldet = mod.zugang_info(wer).get("gespeichert")
        paare.append((wer, gemeldet, mod.loeschen(wer)))
    check(any(p[2] for p in paare) and any(not p[2] for p in paare),
          "Positivkontrolle: Loeschen traf beide Faelle (entfernt / nichts da)", repr(paare))
    check(all(p[1] is p[2] for p in paare),
          "gespeichert sagt voraus, was loeschen() meldet", repr(paare))
    check(mod.zugang_info("anna").get("gespeichert") is False
          and mod.zugang_info("bert").get("gespeichert") is False,
          "nach dem Loeschen: gespeichert ist False")

# ═══════════════════════════════════════════════════════════════════════════
section("3. Endpunkte: das Ergebnis des Loeschens geht als 'removed' hinaus")
# ═══════════════════════════════════════════════════════════════════════════
MAIN = Path(os.environ.get("ZUGANG_MAIN") or ROOT / "backend" / "main.py")
try:
    baum = ast.parse(MAIN.read_text(encoding="utf-8"))
except Exception as e:  # noqa: BLE001
    abbruch(f"main.py nicht lesbar: {e}")


def removed_aus_loeschen(fn) -> bool:
    """Traegt eine Rueckgabe den Schluessel 'removed', gespeist aus dem Wert,
    den ``<modul>.loeschen(...)`` geliefert hat?"""
    quellen = set()
    for n in ast.walk(fn):
        if (isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
                and isinstance(n.value.func, ast.Attribute) and n.value.func.attr == "loeschen"):
            quellen |= {z.id for z in n.targets if isinstance(z, ast.Name)}
    for n in ast.walk(fn):
        if not isinstance(n, ast.Dict):
            continue
        for k, v in zip(n.keys, n.values):
            if isinstance(k, ast.Constant) and k.value == "removed":
                if any(isinstance(x, ast.Name) and x.id in quellen for x in ast.walk(v)):
                    return True
    return False


for name in ("sap_account_del", "vemas_account_del"):
    fn = next((n for n in ast.walk(baum)
               if isinstance(n, ast.AsyncFunctionDef) and n.name == name), None)
    if fn is None:
        abbruch(f"Endpunkt {name} nicht gefunden – die Pruefung waere leer")
    check(removed_aus_loeschen(fn), f"{name}: 'removed' kommt aus loeschen()")

print("\n" + "=" * 60)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
