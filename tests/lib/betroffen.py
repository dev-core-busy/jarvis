"""Welche Waechter muessen laufen? - Karte "Waechter -> Abhaengigkeiten" fuer ``ci_lauf.py --nur-betroffene``.

WARUM (2026-11-22): der volle Sammellauf ist durch die Rechenleistung
begrenzt (Summe ~3650 s auf 12 Plaetzen = ~310 s), nicht mehr durch einen
Langlaeufer. Bei einer typischen Aenderung sind aber nur wenige Dutzend der
~570 Waechter betroffen.

DIE REGEL - uebersprungen wird ein Waechter NUR, wenn ALLES gilt:
  * sein letzter Lauf war GRUEN (rot, "konnte nicht laufen" und Zeitdeckel
    laufen immer wieder),
  * der liegt hoechstens ``JARVIS_BETROFFEN_MAX_ALTER_H`` Stunden zurueck
    (Vorgabe 24 - manche Waechter haengen am Datum, z.B. ablaufende
    Ausnahmen, und das sieht keine Lesespur),
  * die Umgebung ist dieselbe (Python, Node, strace, ci_lauf.py, diese
    Datei, lesespur.py - sonst gilt kein Eintrag),
  * und KEINE seiner aufgezeichneten Abhaengigkeiten hat einen anderen
    Zustand als bei diesem Lauf (Inhalt, Existenz, Verzeichnisliste;
    ``tests/lib/lesespur.py``).

Verglichen wird gegen den Stand beim LETZTEN LAUF des Waechters, nicht
gegen git: eine Karte, die bei Commit A entstand, kennt eine Abhaengigkeit
nicht, die ein spaeterer Commit eingefuehrt hat - der Vergleich gegen HEAD
liesse den Waechter dann zu Unrecht aus. Hier dagegen hat sich, damit der
Waechter etwas Neues liest, eine seiner bisherigen Abhaengigkeiten aendern
muessen (der Code, der es liest) - also laeuft er und wird neu aufgezeichnet.

Grenzen (bewusst, deshalb bleibt die CI beim VOLLEN Lauf): Netz, Uhrzeit
innerhalb der Altersgrenze, Umgebungsvariablen und Zustand ausserhalb von
Dateien sieht keine Lesespur. Die Karte liegt lokal
(``~/.cache/jarvis/waechter_karte.json``, ``JARVIS_WAECHTER_KARTE``).
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

_HIER = Path(__file__).resolve().parent


def karten_datei():
    eigen = os.environ.get("JARVIS_WAECHTER_KARTE")
    if eigen:
        return Path(eigen)
    basis = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(basis) / "jarvis" / "waechter_karte.json"


def max_alter_s():
    try:
        return float(os.environ.get("JARVIS_BETROFFEN_MAX_ALTER_H") or 24) * 3600
    except ValueError:
        return 24 * 3600.0


def _ausgabe(befehl):
    try:
        return subprocess.run(befehl, capture_output=True, text=True, timeout=30).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "fehlt"


def umgebung_kennung(weitere):
    """Fingerabdruck der Umgebung: aendert er sich, gilt kein Karteneintrag."""
    h = hashlib.sha256()
    h.update(sys.version.encode())
    h.update(_ausgabe([shutil.which("node") or "node", "--version"]).encode())
    h.update("".join(_ausgabe([shutil.which("strace") or "strace", "-V"]).splitlines()[:1]).encode())
    for p in [Path(__file__), _HIER / "lesespur.py", *map(Path, weitere)]:
        h.update(p.name.encode() + b"\0" + p.read_bytes() + b"\0")
    return h.hexdigest()[:16]


class Karte:
    def __init__(self, kennung, datei=None):
        self.datei = Path(datei) if datei else karten_datei()
        self.kennung = kennung
        self.hinweis = ""
        self._eintraege = {}
        try:
            roh = json.loads(self.datei.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            roh = None
            self.hinweis = "noch keine Karte - alle laufen und werden aufgezeichnet"
        if isinstance(roh, dict):
            if roh.get("kennung") != kennung:
                self.hinweis = "Umgebung geaendert (Python/Node/strace/ci_lauf.py) - alle laufen"
            else:
                pfade = roh.get("pfade") or []
                for name, e in (roh.get("waechter") or {}).items():
                    try:
                        self._eintraege[name] = {
                            "rc": e["rc"], "zeit": float(e["zeit"]), "summe": e["summe"],
                            "dateien": [pfade[i] for i in e["dateien"]],
                            "verzeichnisse": [pfade[i] for i in e["verzeichnisse"]],
                        }
                    except (KeyError, IndexError, TypeError, ValueError):
                        continue          # ein kaputter Eintrag heisst: laufen

    def grund(self, name, zustaende, jetzt=None):
        """None = darf entfallen; sonst der Grund, warum der Waechter laufen muss."""
        e = self._eintraege.get(name)
        if e is None:
            return "kein Eintrag"
        if e["rc"] != 0:
            return "zuletzt nicht gruen"
        if (jetzt if jetzt is not None else time.time()) - e["zeit"] > max_alter_s():
            return "letzter Lauf aelter als die Altersgrenze"
        if zustaende.summe(e["dateien"], e["verzeichnisse"]) != e["summe"]:
            return "Abhaengigkeit geaendert"
        return None

    def eintragen(self, name, rc, zeit, dateien, verzeichnisse, zustaende):
        self._eintraege[name] = {"rc": rc, "zeit": zeit, "dateien": sorted(dateien),
                                 "verzeichnisse": sorted(verzeichnisse),
                                 "summe": zustaende.summe(dateien, verzeichnisse)}

    def vergessen(self, name):
        self._eintraege.pop(name, None)

    def behalten_nur(self, namen):
        for n in list(self._eintraege):
            if n not in namen:
                del self._eintraege[n]

    def speichern(self):
        """Pfade als Tabelle, je Waechter nur Verweise (sonst ~15 MB Klartext)."""
        tabelle, index = [], {}

        def nr(p):
            if p not in index:
                index[p] = len(tabelle)
                tabelle.append(p)
            return index[p]

        waechter = {n: {"rc": e["rc"], "zeit": e["zeit"], "summe": e["summe"],
                        "dateien": [nr(p) for p in e["dateien"]],
                        "verzeichnisse": [nr(p) for p in e["verzeichnisse"]]}
                    for n, e in sorted(self._eintraege.items())}
        try:
            self.datei.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.datei.with_name(self.datei.name + ".%d.tmp" % os.getpid())
            tmp.write_text(json.dumps({"kennung": self.kennung, "pfade": tabelle, "waechter": waechter}),
                           encoding="utf-8")
            os.replace(tmp, self.datei)
        except OSError as exc:
            print(f"   Karte nicht gespeichert ({exc}) - der naechste Lauf faehrt alles", flush=True)
