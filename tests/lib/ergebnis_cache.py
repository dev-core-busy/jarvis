"""Ergebnis-Cache je Datei fuer Waechter, die den ganzen Baum lesen.

WARUM (2026-11-22): ``test_keine_echtwerte`` (35-69 s) und
``test_kommentare_deutsch`` (29-59 s) lesen bei jedem Lauf jede der rund
1600 Dateien neu, obwohl sich zwischen zwei Laeufen meist eine Handvoll
geaendert hat. Ihr Ergebnis je Datei haengt nur am INHALT, am PFAD und am
Waechter selbst - also wird genau das zum Schluessel:

  * je Eintrag: Pfad + sha256 des Inhalts. Eine geaenderte Datei ist ein
    Fehlschuss und wird neu geprueft. sha256 statt md5 (2026-11-22): seit
    der Cache in der CI ueber Laeufe hinweg lebt, ist er ein gemeinsamer
    Stand - und md5-Kollisionen lassen sich gezielt bauen (eine saubere und
    eine belastete Datei mit gleicher Pruefsumme). Mehraufwand gemessen:
    warmer Lauf 0,30 -> 0,35 s (keine_echtwerte).
  * je Cache-Datei: ein FINGERABDRUCK aus dem Quelltext des Waechters, dieser
    Datei, weiteren genannten Abhaengigkeiten und der Python-Version. Aendert
    sich die Pruefung (Sperrliste, Muster, Logik), gilt kein einziger alter
    Eintrag mehr. Je Fingerabdruck eine EIGENE Datei - eine Gegenprobe, die
    den Waechter sabotiert, ueberschreibt so nicht den Cache des echten.

Gespeichert wird nur, was in DIESEM Lauf geprueft oder bestaetigt wurde -
geloeschte Dateien fallen heraus. Ein kaputter oder fremder Cache ist leer,
kein Absturz. ``JARVIS_WAECHTER_CACHE=aus`` schaltet ihn ab, ein anderer Wert
ist das Verzeichnis (Vorgabe ``~/.cache/jarvis/waechter``).

Ein Treffer liefert das gespeicherte ERGEBNIS, auch Funde - ein Cache, der
einen Fund vergaesse, waere ein Loch. Waechter: tests/test_ergebnis_cache.py.
"""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

# Andere Fingerabdruecke desselben Waechters: weg nach 7 Tagen, und nie mehr
# als 20. Nach ALTER, nicht nur nach Anzahl - eine Gegenprobe, die den
# Waechter sabotiert, erzeugt je Probe einen neuen Fingerabdruck und haette
# bei "die vier neuesten" den Cache des echten Waechters verdraengt.
_HOECHSTENS = 20
_HOECHSTALTER_S = 7 * 24 * 3600


def _verzeichnis():
    wert = os.environ.get("JARVIS_WAECHTER_CACHE", "")
    if wert == "aus":
        return None
    if wert:
        return Path(wert)
    basis = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(basis) / "jarvis" / "waechter"


class ErgebnisCache:
    """Pfad + Inhalt -> Ergebnis (JSON-faehig), gueltig nur fuer diesen Pruefer."""

    def __init__(self, name, abhaengig):
        h = hashlib.sha256()
        h.update(sys.version.encode())
        for p in [Path(__file__), *map(Path, abhaengig)]:
            h.update(str(p.name).encode() + b"\0" + p.read_bytes() + b"\0")
        self.fingerabdruck = h.hexdigest()[:16]
        self.name = name
        self.treffer = self.neu = 0
        self._alt = {}
        self._jetzt = {}
        v = _verzeichnis()
        self._datei = None if v is None else v / f"{name}-{self.fingerabdruck}.json"
        if self._datei is not None:
            try:
                roh = json.loads(self._datei.read_text(encoding="utf-8"))
                if roh.get("fingerabdruck") == self.fingerabdruck and isinstance(roh.get("eintraege"), dict):
                    self._alt = roh["eintraege"]
            except (OSError, ValueError, AttributeError):
                self._alt = {}

    @property
    def aktiv(self):
        return self._datei is not None

    @staticmethod
    def _pruefsumme(inhalt):
        return hashlib.sha256(inhalt if isinstance(inhalt, bytes) else inhalt.encode("utf-8")).hexdigest()

    def holen(self, rel, inhalt):
        """(True, Ergebnis) bei Treffer, sonst (False, None)."""
        e = self._alt.get(rel)
        if isinstance(e, list) and len(e) == 2 and e[0] == self._pruefsumme(inhalt):
            self._jetzt[rel] = e
            self.treffer += 1
            return True, e[1]
        return False, None

    def ablegen(self, rel, inhalt, ergebnis):
        self._jetzt[rel] = [self._pruefsumme(inhalt), ergebnis]
        self.neu += 1

    def speichern(self):
        """Atomar schreiben; andere Fingerabdruecke nach Alter und Anzahl abraeumen."""
        if self._datei is None:
            return
        try:
            self._datei.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._datei.with_name(self._datei.name + ".%d.tmp" % os.getpid())
            tmp.write_text(json.dumps({"fingerabdruck": self.fingerabdruck, "eintraege": self._jetzt}),
                           encoding="utf-8")
            os.replace(tmp, self._datei)
            andere = sorted((p for p in self._datei.parent.glob(f"{self.name}-*.json")
                             if p != self._datei),
                            key=lambda p: p.stat().st_mtime, reverse=True)
            grenze = time.time() - _HOECHSTALTER_S
            for i, alt in enumerate(andere):
                if i >= _HOECHSTENS - 1 or alt.stat().st_mtime < grenze:
                    alt.unlink(missing_ok=True)
        except OSError as exc:
            # Nur der naechste Lauf wird langsamer - gesagt wird es trotzdem.
            print(f"[ergebnis_cache] nicht gespeichert ({exc})", file=sys.stderr)

    def bilanz(self):
        if not self.aktiv:
            return "Cache aus (JARVIS_WAECHTER_CACHE=aus)"
        return f"{self.treffer} aus dem Cache, {self.neu} neu geprueft"
