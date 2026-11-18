#!/usr/bin/env python3
"""Waechter: Gedaechtnisse je Benutzer liegen in einem geschlossenen Ordner
(Pentest "Hardening" F-14, "Nutzerliste mit Klarnamen sichtbar").

Befund: ``data/memory_<vorname.nachname>.json`` lag direkt in ``data/`` (0755,
muss fuer die Wissensordner begehbar bleiben). Die Inhalte waren 0640 – aber die
DATEINAMEN waren fuer jedes lokale Konto auflistbar und ergaben die
Benutzerliste mit Klarnamen (ECHT 2026-11-18: 79 Dateien, 45 Namen, sichtbar
fuer das Administrationskonto, nobody und jarvis_sandbox).

Zusagen:
  [1] Der Pfad je Benutzer liegt in ``data/gedaechtnis/``; das Gedaechtnis des
      Dienstes (``data/memory.json``, kein Name) bleibt, wo es ist.
  [2] ``umziehen()`` verschiebt den Altbestand samt ``.bak`` und Handsicherungen,
      verliert bei einem Konflikt nichts, ist idempotent, und seine Rueckgabe
      traegt KEINE Namen (sie landet im Journal).
  [3] Der Ordner ist 0750, die Dateien 0640 – fuer "other" weder auflistbar
      noch lesbar. Gemessen am Modus, ausgefuehrt im Sandkasten mit der umask
      des Dienstes.
  [4] Rueckweg: ein Altbestand, den der Start nicht verschoben hat, wird beim
      ersten Laden verschoben – auch unter ``_lock`` (main.py loescht so), ohne
      sich selbst zu blockieren.
  [5] Die vier Sperrlisten kennen den Ordner (PRIVATE_DIRS, PRIVATE_FILE_GLOBS,
      _APP_DENY_REL, SHELL_SECRET_PATHS), die Benutzer-Zusammenfuehrung und das
      Wissens-Aufraeumen suchen dort.
  [6] main.py (AST): der Umzug laeuft im Start VOR der Rechte-Haertung, und
      dieser Haken steht VOR der Benutzer-Zusammenfuehrung.

``backend.config`` nur als Stub. Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import os
import stat
import sys
import tempfile
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(text, bed, detail=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   " + text)
    else:
        _fail += 1
        print("  FAIL " + text + (" – " + str(detail) if detail else ""))


def abbruch(text):
    print("ABBRUCH: " + text)
    sys.exit(2)


def modus(p: Path) -> int:
    return p.stat().st_mode & 0o777


# Ein STUB darf schon da sein (die Gegenprobe laedt die Module vorab, um sie im
# Speicher zu sabotieren) – das echte Modul nicht.
if getattr(sys.modules.get("backend.config"), "__file__", None):
    abbruch("das ECHTE backend.config ist bereits geladen")
_cfg = types.ModuleType("backend.config")


class _C:
    def get_setting(self, k, d=None):
        return d

    def get(self, k, d=None):
        return d

    def get_skill_states(self):
        return {}


_cfg.config = _C()
SAND = Path(tempfile.mkdtemp(prefix="jarvis_f14_"))
_cfg.PROJECT_ROOT = SAND
sys.modules["backend.config"] = _cfg
os.umask(0o022)                       # die umask des Dienstes

try:
    from backend import sandbox as sb               # noqa: E402
    from backend.tools import memory as mem         # noqa: E402
    from backend import benutzer_migration as mig   # noqa: E402
    from backend import wissen_aufraeumen as wa     # noqa: E402
except Exception as e:  # noqa: BLE001
    abbruch(f"Module nicht ladbar: {e}")
if getattr(sys.modules.get("backend.config"), "__file__", None):
    abbruch("das ECHTE backend.config wurde geladen")

D = SAND / "data"
D.mkdir()
D.chmod(0o755)
sb.PROJECT_ROOT = SAND
mem._DATA_DIR = D
mem.MEMORY_FILE = D / "memory.json"
mem._user_caches.clear()
mig.DATA = D
mig.PROJECT_ROOT = SAND
wa.DATA = D
if not str(mem.gedaechtnis_dir()).startswith(str(SAND)):
    abbruch("Sandkasten nicht wirksam (gedaechtnis_dir zeigt nach draussen)")

G = D / "gedaechtnis"

# ── Altbestand wie auf ECHT ──────────────────────────────────────────────────
alt = {
    "memory_anna.muster.json": '{"farbe": {"value": "blau"}}',
    "memory_anna.muster.json.bak": '{"farbe": {"value": "rot"}}',
    "memory_anna.muster.json.bak-20260913-150733": '{}',
    "memory_bert.doppelt.json": '{"x": {"value": "gleich"}}',
    "memory_carl.konflikt.json": '{"x": {"value": "ALT"}}',
}
for n, t in alt.items():
    (D / n).write_text(t, encoding="utf-8")
    (D / n).chmod(0o644)
(D / "memory.json").write_text('{"dienst": {"value": "x"}}', encoding="utf-8")
G.mkdir(mode=0o755)
G.chmod(0o755)
(G / "memory_bert.doppelt.json").write_text(alt["memory_bert.doppelt.json"], encoding="utf-8")
(G / "memory_carl.konflikt.json").write_text('{"x": {"value": "NEU"}}', encoding="utf-8")

# Positivkontrolle: die Ausgangslage zeigt den Befund wirklich
namen_vorher = [p.name for p in D.iterdir() if p.name.startswith("memory_")]
if len(namen_vorher) != len(alt) or not (modus(D) & stat.S_IROTH):
    abbruch("Ausgangslage (Namen in data/, data/ auflistbar) nicht hergestellt")

print("\n── 1. Pfade")
p = mem._get_memory_path("anna.muster")
check("Pfad je Benutzer liegt in data/gedaechtnis", p.parent == G, p)
check("Dateiname bleibt memory_<benutzer>.json", p.name == "memory_anna.muster.json", p.name)
check("Gedaechtnis des Dienstes bleibt data/memory.json",
      mem._get_memory_path("") == D / "memory.json"
      and mem._get_memory_path("jarvis") == D / "memory.json")

print("\n── 2. Umzug")
erg = mem.umziehen()
rest = sorted(p.name for p in D.iterdir() if p.name.startswith("memory_"))
check("kein memory_<name> mehr direkt in data/", rest == [], rest)
check("data/memory.json bleibt liegen", (D / "memory.json").is_file())
check("Original, .bak und Handsicherung sind umgezogen",
      all((G / n).is_file() for n in ("memory_anna.muster.json",
                                      "memory_anna.muster.json.bak",
                                      "memory_anna.muster.json.bak-20260913-150733")))
check("Inhalt unveraendert",
      (G / "memory_anna.muster.json").read_text(encoding="utf-8")
      == alt["memory_anna.muster.json"])
check("Konflikt: das Ziel (neuer Code) gewinnt",
      '"NEU"' in (G / "memory_carl.konflikt.json").read_text(encoding="utf-8"))
vor_umzug = list(G.glob("memory_carl.konflikt.json.vor-umzug-*"))
check("Konflikt: der Altstand liegt als .vor-umzug-* im Ordner",
      len(vor_umzug) == 1 and '"ALT"' in vor_umzug[0].read_text(encoding="utf-8")
      if vor_umzug else False, [x.name for x in vor_umzug])
check("Zaehlung stimmt (4 verschoben, 1 doppelt, 1 Konflikt, 0 Fehler)",
      erg == {"verschoben": 4, "doppelt": 1, "konflikt": 1, "fehler": []}, erg)
check("Rueckgabe traegt keine Namen (sie landet im Journal)",
      "anna" not in repr(erg) and "muster" not in repr(erg), erg)
erg2 = mem.umziehen()
check("zweiter Lauf tut nichts",
      erg2 == {"verschoben": 0, "doppelt": 0, "konflikt": 0, "fehler": []}, erg2)

print("\n── 3. Rechte (umask 022, Ordner war vorher 0755)")
check("Ordner ist 0750 – fuer 'other' weder auflistbar noch begehbar",
      modus(G) == 0o750, oct(modus(G)))
# Nur was umziehen() VERSCHOBEN hat – die beiden Ziel-Attrappen oben hat der
# Test selbst mit umask 022 angelegt, die zieht erst harden_data_dirs nach.
_umgezogen = [f for f in G.iterdir()
              if f.name.startswith("memory_anna.") or ".vor-umzug-" in f.name]
check("umgezogene Dateien sind nicht fremd lesbar",
      len(_umgezogen) == 4
      and all(not (modus(f) & stat.S_IROTH) for f in _umgezogen),
      {f.name: oct(modus(f)) for f in _umgezogen})
sb.harden_data_dirs()
check("harden_data_dirs haelt den Ordner auf 0750", modus(G) == 0o750, oct(modus(G)))
check("harden_data_dirs zieht Dateien im Ordner auf 0640 (auch .vor-umzug-*)",
      all(modus(f) == 0o640 for f in G.iterdir()),
      {f.name: oct(modus(f)) for f in G.iterdir() if modus(f) != 0o640})

# Neuer Benutzer, Ordner existiert noch nicht
D2 = SAND / "data2"
D2.mkdir()
mem._DATA_DIR = D2
mem.MEMORY_FILE = D2 / "memory.json"
mem._user_caches.clear()
mem._save_memory_dict({"a": {"value": "1"}}, "dora.neu")
g2 = D2 / "gedaechtnis"
check("erstes save legt den Ordner mit 0750 an",
      g2.is_dir() and modus(g2) == 0o750, oct(modus(g2)) if g2.is_dir() else "fehlt")
check("erstes save legt die Datei im Ordner an, nicht fremd lesbar",
      (g2 / "memory_dora.neu.json").is_file()
      and not (modus(g2 / "memory_dora.neu.json") & stat.S_IROTH))
check("nichts mit Namen direkt in data/",
      not [x for x in D2.iterdir() if x.name.startswith("memory_")])

print("\n── 4. Rueckweg beim Laden (auch unter _lock)")
D3 = SAND / "data3"
D3.mkdir()
mem._DATA_DIR = D3
mem.MEMORY_FILE = D3 / "memory.json"
mem._user_caches.clear()
(D3 / "memory_emil.spaet.json").write_text('{"k": {"value": "da"}}', encoding="utf-8")
ergebnis = {}


def _laden_unter_lock():
    with mem._lock:                    # so ruft main.py beim Loeschen
        ergebnis["d"] = mem._load_memory_dict("emil.spaet")


t = threading.Thread(target=_laden_unter_lock, daemon=True)
t.start()
t.join(10)
check("Laden unter _lock blockiert nicht", not t.is_alive())
check("Altbestand wird beim Laden gefunden (kein leeres Gedaechtnis)",
      (ergebnis.get("d") or {}).get("k", {}).get("value") == "da", ergebnis.get("d"))
check("und dabei umgezogen",
      (D3 / "gedaechtnis" / "memory_emil.spaet.json").is_file()
      and not (D3 / "memory_emil.spaet.json").exists())

print("\n── 5. Listen und Nachbarn")
check("PRIVATE_DIRS fuehrt data/gedaechtnis", "data/gedaechtnis" in sb.PRIVATE_DIRS)
check("PRIVATE_FILE_GLOBS erfasst den Ordner",
      any(m.startswith("data/gedaechtnis/") for m in sb.PRIVATE_FILE_GLOBS))
check("is_sensitive: Datei im Ordner ist geschuetzt",
      sb.is_sensitive((SAND / "data" / "gedaechtnis" / "memory_x.json").resolve()))
check("Shell-Sperre trifft den Ordner",
      bool(sb.SHELL_SECRET_PATHS.search("cat /opt/jarvis/data/gedaechtnis/memory_x.json"))
      and bool(sb.SHELL_SECRET_PATHS.search("ls data/gedaechtnis")))
check("Shell-Sperre trifft das Wort allein nicht (kein Fehlalarm im Text)",
      not sb.SHELL_SECRET_PATHS.search("echo gedaechtnis_bericht > /tmp/a.txt"))
ab = {a.name: a for a in mig.ablagen()}
check("Benutzer-Zusammenfuehrung sucht im Ordner",
      "memory" in ab and ab["memory"].verzeichnis == D / "gedaechtnis",
      ab.get("memory") and ab["memory"].verzeichnis)
wa_namen = [s for s, _, _ in wa._gedaechtnis()]
check("Wissens-Aufraeumen findet Gedaechtnisse im Ordner",
      "gedaechtnis:memory_anna.muster.json" in wa_namen, wa_namen)
check("Wissens-Aufraeumen findet das des Dienstes weiter",
      "gedaechtnis:memory.json" in wa_namen, wa_namen)

print("\n── 6. Startreihenfolge (main.py, AST)")
baum = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
fn = {n.name: n for n in baum.body if isinstance(n, ast.AsyncFunctionDef)}
haerten = fn.get("startup_harden_data_dirs")
migration = fn.get("startup_benutzer_ablagen")
if haerten is None or migration is None:
    abbruch("Start-Haken in main.py nicht gefunden")


def _aufrufzeile(f, attr):
    zeilen = [n.lineno for n in ast.walk(f)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == attr]
    return min(zeilen) if zeilen else None


z_um = _aufrufzeile(haerten, "umziehen")
z_h = _aufrufzeile(haerten, "harden_data_dirs")
check("Start ruft umziehen()", z_um is not None)
check("umziehen() laeuft VOR harden_data_dirs()",
      z_um is not None and z_h is not None and z_um < z_h, (z_um, z_h))
check("Haertungs-Haken steht VOR der Benutzer-Zusammenfuehrung",
      haerten.lineno < migration.lineno, (haerten.lineno, migration.lineno))

print(f"\n{_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
