"""Schreibschutz fuer die ``gegen_*``-Harnesse: keine fremde Arbeit ueberschreiben.

WARUM (2026-11-18): ``gegen_settings_suche.py`` sicherte seine Dateien beim
Start und legte die Sicherung am Ende blind zurueck. Waehrend des ueber 15
Minuten langen Laufs committete der Betreiber eine Aenderung an zwei dieser
Dateien – das Ende schrieb den Vor-Commit-Stand darueber. Dasselbe Muster
(Startsicherung + blindes ``zurueck()``) stand in ueber hundert Harnessen,
jeder von Hand anders gebaut. Statt jeden Steuerfluss umzuschreiben, setzt
dieses Modul die Regel an den SCHREIBWEGEN durch, die alle gemeinsam haben
(``Path.write_text/write_bytes``, ``open(..., 'w')``, ``shutil.copyfile``
(darueber auch ``copy``/``copy2``),
``os.replace``).

Zwei Regeln, nur fuer Dateien im Repo, die der Prozess schon gelesen oder
selbst geschrieben hat (eine fremde, nie gesehene Datei ist kein Gegenstand
dieser Pruefung – sonst traefe der Schutz jedes Backend-Modul, das der
Harness importiert und das seine eigenen Daten schreibt):

1. FREMD GEAENDERT: ueberschrieben wird eine Datei nur, wenn sie noch so
   aussieht, wie der Prozess sie zuletzt gelesen oder selbst geschrieben hat.
2. VERALTETE SICHERUNG: hat der Prozess eine Datei inzwischen in einer
   NEUEREN Fassung gelesen, darf er keine AELTERE, frueher gelesene Fassung
   mehr darueberschreiben. Genau das war der Vorfall: die Proben lasen die
   neue Fassung (Regel 1 allein haette sie also durchgelassen), das Ende
   schrieb die Startsicherung darueber.

Ein verweigerter Schreibvorgang wird UEBERSPRUNGEN, laut gemeldet, und der
Prozess endet mit Exit 2 („konnte nicht laufen"). Bewusst kein Abbruch an
Ort und Stelle: der Harness soll seine uebrigen Dateien noch zuruecklegen
koennen – ein Wurf mitten im ``zurueck()`` liesse sie sabotiert liegen.

Fuer ``kill -9`` fuehrt jeder Prozess ein Journal (vorher/nachher je Datei,
VOR dem Schreiben geschrieben) unter ``~/.harness-schreibschutz/``. Der
naechste Lauf desselben Harness kennt damit seine eigene liegengebliebene
Sabotage und darf sie zuruecklegen; ein geordnetes Ende ohne Verweigerung
loescht das Journal.

Einbindung (vor dem ersten Lesen/Schreiben, direkt nach den Importen):

    import sys as _sys, pathlib as _pathlib  # noqa: E401
    _sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
    import schreibschutz  # noqa: E402
    schreibschutz.aktivieren(__file__)
"""
import atexit
import builtins
import hashlib
import io
import json
import os
import pathlib
import shutil
import sys
import threading

_ORIG = {}
_zustand = None
_lokal = threading.local()


def _md5(daten):
    return hashlib.md5(daten).hexdigest()


# ⚠ INTERNE ZUGRIFFE GEHEN AM HAKEN VORBEI. ``pathlib`` liest und schreibt
# intern ueber ``io.open`` – das ist hier selbst gehakt; ein ``read_bytes`` im
# Pruefcode liefe sonst durch die eigene Pruefung und rief sich endlos auf.
def _roh_lesen(p):
    with _ORIG["open"](os.fspath(p), "rb") as f:
        return f.read()


def _roh_schreiben(p, daten):
    with _ORIG["open"](os.fspath(p), "wb") as f:
        f.write(daten)


class _Zustand:
    def __init__(self, root, journal):
        self.root = pathlib.Path(root).resolve()
        self.git = self.root / ".git"
        self.journal = pathlib.Path(journal)
        self.gelesen = {}       # pfad -> md5 der juengsten sauberen Lesung
        self.frueher = {}       # pfad -> Menge aller frueher gelesenen md5
        self.eigen = {}         # pfad -> Menge {vorher, nachher} der eigenen Schreibvorgaenge
        self.verweigert = []
        self._journal_laden()

    # ── Journal ─────────────────────────────────────────────────────────────
    def _journal_laden(self):
        try:
            roh = _roh_lesen(self.journal)
        except FileNotFoundError:
            return
        try:
            daten = json.loads(roh.decode("utf-8"))
            for p, werte in daten.items():
                self.eigen[p] = set(werte)
        except Exception:  # noqa: BLE001
            # Ein unlesbares Journal ist kein Freibrief: es bleibt leer, und
            # der Rueckstand gilt als „nie gesehen" – ueberschrieben wird er
            # dann nach Regel „nie gesehen" (erlaubt), aber ohne Rueckhalt.
            print("⚠ Schreibschutz: Journal %s unlesbar – ignoriert" % self.journal,
                  file=sys.stderr)

    def _journal_schreiben(self):
        self.journal.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        tmp = self.journal.with_suffix(".tmp")
        inhalt = json.dumps({p: sorted(w) for p, w in self.eigen.items()}).encode("utf-8")
        _roh_schreiben(tmp, inhalt)
        _ORIG["os_replace"](tmp, self.journal)

    # ── Pruefung ────────────────────────────────────────────────────────────
    def betrifft(self, pfad):
        try:
            p = pathlib.Path(pfad).resolve()
        except Exception:  # noqa: BLE001
            return None
        if p == self.git or self.git in p.parents:
            return None
        if p != self.root and self.root not in p.parents:
            return None
        return str(p)

    def _aktuell(self, p):
        try:
            return _md5(_roh_lesen(p))
        except FileNotFoundError:
            return None
        except IsADirectoryError:
            return None

    def gelesen_melden(self, p, md5=None):
        if md5 is None:
            md5 = self._aktuell(p)
        if md5 is None:
            return
        # Die eigene Sabotage zu lesen ist keine saubere Fassung.
        if md5 in self.eigen.get(p, ()) and md5 != self.gelesen.get(p):
            if md5 not in self.frueher.get(p, set()):
                return
        self.gelesen[p] = md5
        self.frueher.setdefault(p, set()).add(md5)

    def darf_schreiben(self, p, neu_md5):
        """None = erlaubt, sonst der Grund der Verweigerung."""
        bekannt = set()
        if p in self.gelesen:
            bekannt.add(self.gelesen[p])
        bekannt |= self.eigen.get(p, set())
        if not bekannt:
            return None                     # nie gesehen: nicht unser Gegenstand
        jetzt = self._aktuell(p)
        if jetzt is not None and jetzt not in bekannt:
            return ("Datei wurde von aussen geaendert, seit dieser Prozess sie "
                    "zuletzt gesehen hat")
        juengst = self.gelesen.get(p)
        if (neu_md5 is not None and juengst is not None and neu_md5 != juengst
                and neu_md5 in self.frueher.get(p, set())):
            return ("es wuerde eine AELTERE, frueher gelesene Fassung ueber eine "
                    "neuere geschrieben (veraltete Sicherung)")
        return None

    def vor_schreiben(self, p, neu_md5):
        grund = self.darf_schreiben(p, neu_md5)
        if grund:
            self.verweigert.append((p, grund))
            print("\n⚠ SCHREIBSCHUTZ: %s NICHT geschrieben – %s." % (p, grund),
                  file=sys.stderr, flush=True)
            print("⚠ SCHREIBSCHUTZ: %s NICHT geschrieben – %s." % (p, grund), flush=True)
            return False
        vorher = self._aktuell(p)
        werte = self.eigen.setdefault(p, set())
        werte.clear()
        if vorher is not None:
            werte.add(vorher)
        if neu_md5 is not None:
            werte.add(neu_md5)
        self._journal_schreiben()
        return True

    def nach_schreiben(self, p):
        md5 = self._aktuell(p)
        if md5 is not None:
            self.eigen.setdefault(p, set()).add(md5)
            self._journal_schreiben()

    def ende(self):
        if self.verweigert:
            print("\n⚠ SCHREIBSCHUTZ: %d Schreibvorgang/-vorgaenge verweigert – fremde "
                  "Aenderungen blieben erhalten, das Ergebnis dieses Laufs ist NICHT "
                  "deutbar (Exit 2). Betroffen:" % len(self.verweigert), flush=True)
            for p, grund in self.verweigert:
                print("   %s – %s" % (p, grund), flush=True)
            print("   Journal (fuer den naechsten Lauf): %s" % self.journal, flush=True)
            sys.stdout.flush()
            sys.stderr.flush()
            os._exit(2)
        try:
            self.journal.unlink()
        except FileNotFoundError:
            pass


# ── Haken ───────────────────────────────────────────────────────────────────

def _innen():
    return getattr(_lokal, "tief", 0) > 0


class _Innen:
    def __enter__(self):
        _lokal.tief = getattr(_lokal, "tief", 0) + 1

    def __exit__(self, *a):
        _lokal.tief -= 1


def _als_bytes(daten, encoding, errors, newline=None):
    if isinstance(daten, (bytes, bytearray)):
        return bytes(daten)
    text = str(daten)
    if newline not in (None, "", "\n"):
        text = text.replace("\n", newline)
    return text.encode(encoding or "utf-8", errors or "strict")


def _write_text(self, data, encoding=None, errors=None, newline=None):
    p = None if _innen() else _zustand.betrifft(self)
    if p is None:
        with _Innen():
            return _ORIG["write_text"](self, data, encoding=encoding, errors=errors, newline=newline)
    try:
        neu = _md5(_als_bytes(data, encoding, errors, newline))
    except Exception:  # noqa: BLE001
        neu = None
    if not _zustand.vor_schreiben(p, neu):
        return len(data)
    with _Innen():
        r = _ORIG["write_text"](self, data, encoding=encoding, errors=errors, newline=newline)
    _zustand.nach_schreiben(p)
    return r


def _write_bytes(self, data):
    p = None if _innen() else _zustand.betrifft(self)
    if p is None:
        with _Innen():
            return _ORIG["write_bytes"](self, data)
    if not _zustand.vor_schreiben(p, _md5(bytes(data))):
        return len(data)
    with _Innen():
        r = _ORIG["write_bytes"](self, data)
    _zustand.nach_schreiben(p)
    return r


def _read_text(self, *a, **k):
    with _Innen():
        r = _ORIG["read_text"](self, *a, **k)
    p = _zustand.betrifft(self)
    if p is not None:
        _zustand.gelesen_melden(p)
    return r


def _read_bytes(self):
    with _Innen():
        r = _ORIG["read_bytes"](self)
    p = _zustand.betrifft(self)
    if p is not None:
        _zustand.gelesen_melden(p, _md5(r))
    return r


class _VerworfeneDatei:
    """Ersatz fuer eine verweigerte Schreib-Datei: nimmt alles an, schreibt nichts."""
    def __init__(self, binaer):
        self._puffer = io.BytesIO() if binaer else io.StringIO()

    def __getattr__(self, name):
        return getattr(self._puffer, name)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def close(self):
        pass


class _SchreibDatei:
    """Echte Datei, deren ``close`` den eigenen Schreibvorgang verbucht."""
    def __init__(self, f, p):
        self._f = f
        self._p = p

    def __getattr__(self, name):
        return getattr(self._f, name)

    def __iter__(self):
        return iter(self._f)

    def __enter__(self):
        self._f.__enter__()
        return self

    def __exit__(self, *a):
        r = self._f.__exit__(*a)
        _zustand.nach_schreiben(self._p)
        return r

    def close(self):
        self._f.close()
        _zustand.nach_schreiben(self._p)


def _open(file, mode="r", *a, **k):
    if _innen() or not isinstance(file, (str, bytes, os.PathLike)):
        return _ORIG["open"](file, mode, *a, **k)
    p = _zustand.betrifft(os.fsdecode(file))
    if p is None:
        return _ORIG["open"](file, mode, *a, **k)
    schreibend = any(c in mode for c in "wax+")
    if not schreibend:
        _zustand.gelesen_melden(p)
        return _ORIG["open"](file, mode, *a, **k)
    # Inhalt ist hier noch unbekannt: Regel 1 gilt, Regel 2 nicht.
    if not _zustand.vor_schreiben(p, None):
        return _VerworfeneDatei("b" in mode)
    with _Innen():
        f = _ORIG["open"](file, mode, *a, **k)
    return _SchreibDatei(f, p)


def _kopie(name):
    orig = _ORIG[name]

    def haken(src, dst, *a, **k):
        if _innen():
            return orig(src, dst, *a, **k)
        ps = _zustand.betrifft(src)
        ziel = pathlib.Path(dst)
        if ziel.is_dir():
            ziel = ziel / pathlib.Path(src).name
        pd = _zustand.betrifft(ziel)
        try:
            inhalt = _roh_lesen(src)
        except Exception:  # noqa: BLE001
            inhalt = None
        if ps is not None and inhalt is not None:
            _zustand.gelesen_melden(ps, _md5(inhalt))
        if pd is not None and not _zustand.vor_schreiben(pd, _md5(inhalt) if inhalt is not None else None):
            return str(ziel)
        with _Innen():
            r = orig(src, dst, *a, **k)
        if pd is not None:
            _zustand.nach_schreiben(pd)
        return r
    return haken


def _os_replace_haken(name):
    orig = _ORIG[name]

    def haken(src, dst, *a, **k):
        if _innen():
            return orig(src, dst, *a, **k)
        pd = _zustand.betrifft(os.fsdecode(dst)) if isinstance(dst, (str, bytes, os.PathLike)) else None
        if pd is not None:
            try:
                neu = _md5(_roh_lesen(os.fsdecode(src)))
            except Exception:  # noqa: BLE001
                neu = None
            if not _zustand.vor_schreiben(pd, neu):
                return None
        with _Innen():
            r = orig(src, dst, *a, **k)
        if pd is not None:
            _zustand.nach_schreiben(pd)
        return r
    return haken


def aktivieren(harness_datei, root=None, journal_dir=None):
    """Schaltet den Schutz fuer diesen Prozess ein. ``root`` = Repo-Wurzel
    (Vorgabe: zwei Ebenen ueber ``tests/lib``), ``journal_dir`` = Ablage des
    Journals (Vorgabe ``~/.harness-schreibschutz``). Mehrfacher Aufruf ist
    wirkungslos."""
    global _zustand
    if _zustand is not None:
        return _zustand
    if root is None:
        root = pathlib.Path(__file__).resolve().parent.parent.parent
    if journal_dir is None:
        journal_dir = pathlib.Path.home() / ".harness-schreibschutz"
    _ORIG.update({
        "write_text": pathlib.Path.write_text, "write_bytes": pathlib.Path.write_bytes,
        "read_text": pathlib.Path.read_text, "read_bytes": pathlib.Path.read_bytes,
        "open": builtins.open, "io_open": io.open,
        "copyfile": shutil.copyfile,
        "os_replace": os.replace, "os_rename": os.rename,
    })
    name = pathlib.Path(harness_datei).stem
    _zustand = _Zustand(root, pathlib.Path(journal_dir) / (name + ".json"))
    pathlib.Path.write_text = _write_text
    pathlib.Path.write_bytes = _write_bytes
    pathlib.Path.read_text = _read_text
    pathlib.Path.read_bytes = _read_bytes
    builtins.open = _open
    io.open = _open
    # ⚠ NUR copyfile: ``shutil.copy`` und ``shutil.copy2`` rufen intern das
    # Modul-Global ``copyfile`` und laufen damit durch diesen Haken. Ein
    # eigener Haken je Funktion waere eine zweite Schranke fuer dieselbe Frage
    # – die Gegenprobe blieb dann stumm, weil jede Sabotage nur eine Haelfte
    # traf (Register: zwei Schranken machen jede Gegenprobe stumm).
    shutil.copyfile = _kopie("copyfile")
    os.replace = _os_replace_haken("os_replace")
    os.rename = _os_replace_haken("os_rename")
    # Zuerst registriert = zuletzt ausgefuehrt: laeuft NACH dem atexit-
    # ``zurueck()`` des Harness, sieht also auch dessen Verweigerungen.
    atexit.register(_zustand.ende)
    return _zustand
