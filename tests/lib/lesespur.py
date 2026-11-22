"""Lesespur eines Waechters: welche Dateien und Verzeichnisse er (samt Kindprozessen) beruehrt.

WARUM (2026-11-22): ``ci_lauf.py --nur-betroffene`` laesst einen Waechter nur
dann aus, wenn sich seit seinem letzten GRUENEN Lauf nichts geaendert hat,
wovon er abhaengt. "Wovon er abhaengt" wird nicht geraten (Importliste,
Textsuche), sondern beim Lauf AUFGEZEICHNET - mit ``strace -f`` ueber den
ganzen Prozessbaum, denn viele Waechter starten bash, git, node oder weitere
Pruefstaende. Eine Python- oder Node-Instrumentierung saehe diese Kinder nicht.

Erfasst wird (Ueberschaetzen ist die SICHERE Richtung - eine Abhaengigkeit zu
viel kostet einen Lauf, eine zu wenig ist ein Loch):

  * jeder Pfad, den ein Datei-Systemaufruf nennt (open, stat, access,
    readlink, execve, ...) - auch wenn er FEHLT: entsteht er spaeter, muss
    der Waechter laufen;
  * jedes zum Auflisten geoeffnete Verzeichnis (``O_DIRECTORY``): kommt dort
    eine Datei hinzu oder verschwindet eine, muss er laufen;
  * NICHT, was nur zum Schreiben geoeffnet, angelegt oder geloescht wird.

Relative Pfade werden gegen das Arbeitsverzeichnis des jeweiligen Prozesses
aufgeloest (chdir je Prozess verfolgt, Kinder erben es); ist es unbekannt,
gegen die Wurzel - wieder die sichere Richtung.

Der ZUSTAND einer Abhaengigkeit: sha256 fuer Dateien im Repo, Groesse +
Aenderungszeit ausserhalb (Bibliotheken, jsdom), "fehlt", und fuer
Verzeichnisse die sortierte Namensliste. Fluechtiges (/proc, /tmp, Caches)
zaehlt nicht. Waechter: tests/test_nur_betroffene.py.
"""
import hashlib
import os
import re
from pathlib import Path

# strace-Aufruf: Datei- und Prozess-Systemaufrufe, Deskriptoren mit Pfad (-y)
STRACE_ARGUMENTE = ["-f", "-qq", "-y", "-e", "trace=%file,%process"]

_ZEILE = re.compile(r"^(\d+)\s+(?:<\.\.\. (\w+) resumed>|(\w+)\()(.*)$")
_TEXT = re.compile(r'"((?:[^"\\]|\\.)*)"')
_FD_PFAD = re.compile(r"^\s*-?\d+<([^>]*)>")
_RUECKGABE = re.compile(r"\)\s*=\s*(-?\d+)")
# Systemaufrufe, die ein Kind anlegen (Rueckgabe = Kind-PID)
_KIND = {"clone", "clone3", "fork", "vfork"}
# nur schreibend: diese Pfade sind KEINE Abhaengigkeit
_SCHREIBEND = {"unlink", "unlinkat", "rmdir", "mkdir", "mkdirat", "rename", "renameat",
               "renameat2", "creat", "symlink", "symlinkat", "link", "linkat", "chmod",
               "fchmodat", "chown", "lchown", "fchownat", "truncate", "utimensat", "utimes",
               "mknod", "mknodat"}
# fluechtig: aendert sich ohne Bezug zum Code
_FLUECHTIG = ("/proc/", "/sys/", "/dev/", "/tmp/", "/run/", "/var/tmp/")


def _unescape(s):
    try:
        return bytes(s, "utf-8").decode("unicode_escape").encode("latin-1").decode("utf-8")
    except (UnicodeDecodeError, UnicodeEncodeError):
        return s


def fluechtig(pfad, home=None):
    home = home or str(Path.home())
    if pfad.startswith(_FLUECHTIG) or pfad in ("/proc", "/sys", "/dev", "/tmp"):
        return True
    for d in (".cache", ".harness-schreibschutz", ".npm", ".node_repl_history"):
        if pfad == f"{home}/{d}" or pfad.startswith(f"{home}/{d}/"):
            return True
    return any(fluechtiger_name(teil) for teil in pfad.split("/"))


# Ablagen der Laeufe selbst (Prolog-Sammlung, Gegenproben, Wegwerf-Ordner der
# Waechter) - entstehen und verschwinden bei jedem Lauf.
_FLUECHTIGE_NAMEN = (".prolog_sammlung_", ".prolog_pruefung_", ".gegen", ".waechter-",
                     ".harness-schreibschutz")


def fluechtiger_name(name):
    return name.startswith(_FLUECHTIGE_NAMEN)


def auswerten(spur_text, wurzel):
    """strace-Ausgabe -> (gelesen: set[str], verzeichnisse: set[str]) als absolute Pfade."""
    wurzel = str(Path(wurzel))
    cwd = {}
    gelesen, verzeichnisse = set(), set()
    erster = None
    offen = {}   # pid -> (aufruf, argumente) einer unterbrochenen Zeile

    def aufloesen(pid, p, basis=None):
        if p.startswith("/"):
            return os.path.normpath(p)
        b = basis or cwd.get(pid) or wurzel
        return os.path.normpath(os.path.join(b, p))

    for zeile in spur_text.splitlines():
        m = _ZEILE.match(zeile)
        if not m:
            continue
        pid = int(m.group(1))
        if erster is None:
            erster = pid
            cwd.setdefault(pid, wurzel)
        rest = m.group(4)
        if m.group(2):                       # "<... x resumed>": Argumente der unterbrochenen Zeile
            aufruf, anfang = offen.pop(pid, (m.group(2), ""))
            rest = anfang + rest
        else:
            aufruf = m.group(3)
            if rest.endswith("<unfinished ...>"):
                offen[pid] = (aufruf, rest[: -len("<unfinished ...>")])
                continue
        rueck = _RUECKGABE.search(rest)
        rc = int(rueck.group(1)) if rueck else None
        if aufruf in _KIND:
            if rc and rc > 0:
                cwd[rc] = cwd.get(pid, wurzel)
            continue
        texte = [_unescape(t) for t in _TEXT.findall(rest)]
        if aufruf in ("execve", "execveat"):
            if texte:
                gelesen.add(aufloesen(pid, texte[0]))
            continue
        if aufruf == "chdir":
            if texte and rc == 0:
                cwd[pid] = aufloesen(pid, texte[0])
            continue
        if aufruf == "fchdir":
            fd = _FD_PFAD.match(rest)
            if fd and rc == 0:
                cwd[pid] = fd.group(1)
            continue
        if aufruf in _SCHREIBEND or not texte:
            continue
        # Basis fuer *at-Aufrufe: ein Verzeichnis-Deskriptor mit Pfad (-y);
        # AT_FDCWD steht als Wort da und trifft das Muster nicht.
        fd = _FD_PFAD.match(rest)
        basis = fd.group(1) if fd else None
        pfad = aufloesen(pid, texte[0], basis)
        if aufruf in ("open", "openat", "openat2"):
            # Flags stehen HINTER dem Pfad - ein Komma im Pfad verschoebe sonst alles
            flags = rest[_TEXT.search(rest).end():]
            if ("O_WRONLY" in flags) and "O_RDWR" not in flags:
                continue
            if "O_DIRECTORY" in flags:
                verzeichnisse.add(pfad)
                continue
        gelesen.add(pfad)
    return gelesen, verzeichnisse


def einteilen(pfade, wurzel, home=None):
    """Absolute Pfade -> (im Repo relativ, ausserhalb absolut); .git und Fluechtiges fallen weg."""
    wurzel = str(Path(wurzel))
    repo, draussen = set(), set()
    for p in pfade:
        if p == wurzel:
            continue
        if p.startswith(wurzel + "/"):
            rel = p[len(wurzel) + 1:]
            if rel == ".git" or rel.startswith(".git/") or rel.startswith("node_modules/.cache/"):
                continue
            # Uebersetzter Bytecode: massgeblich ist die .py-Quelle (wird mitgelesen);
            # ein neu erzeugtes .pyc loeste sonst grundlos Laeufe aus.
            if "__pycache__/" in rel or rel.endswith("/__pycache__"):
                continue
            repo.add(rel)
        elif not fluechtig(p, home) and not fluechtig(os.path.realpath(p), home):
            # realpath: /etc/mtab zeigt auf /proc/self/mounts (Aenderungszeit
            # immer "jetzt") - ein Verweis auf Fluechtiges ist fluechtig.
            draussen.add(p)
    return repo, draussen


def _datei_zustand(p, inhalt):
    try:
        if p.is_dir():
            return "verzeichnis"
        if not p.exists():
            return "fehlt"
        if inhalt:
            return hashlib.sha256(p.read_bytes()).hexdigest()
        st = p.stat()
        return f"{st.st_size}:{st.st_mtime_ns}"
    except OSError:
        return "unlesbar"


def _liste_zustand(p):
    """Sortierte Namensliste ohne fluechtige Ablagen (das Home sieht sonst bei
    jedem Lauf anders aus: Prolog-Sammlung, Wegwerf-Ordner der Waechter)."""
    try:
        namen = sorted(n for n in os.listdir(p) if not fluechtiger_name(n))
        return hashlib.sha256("\0".join(namen).encode()).hexdigest()
    except OSError:
        return "fehlt"


class Zustaende:
    """Zustand je Pfad, je Lauf nur einmal berechnet (viele Waechter teilen Dateien)."""

    def __init__(self, wurzel):
        self.wurzel = Path(wurzel)
        self._d, self._v = {}, {}

    def datei(self, rel_oder_abs):
        z = self._d.get(rel_oder_abs)
        if z is None:
            if rel_oder_abs.startswith("/"):
                z = _datei_zustand(Path(rel_oder_abs), inhalt=False)
            else:
                z = _datei_zustand(self.wurzel / rel_oder_abs, inhalt=True)
            self._d[rel_oder_abs] = z
        return z

    def verzeichnis(self, rel_oder_abs):
        z = self._v.get(rel_oder_abs)
        if z is None:
            p = Path(rel_oder_abs) if rel_oder_abs.startswith("/") else self.wurzel / rel_oder_abs
            z = self._v[rel_oder_abs] = _liste_zustand(p)
        return z

    def vergessen(self):
        """Nach Laeufen, die Dateien geaendert haben koennten, neu messen."""
        self._d.clear()
        self._v.clear()

    def summe(self, dateien, verzeichnisse):
        """Ein Fingerabdruck ueber alle Abhaengigkeiten und ihren Zustand."""
        h = hashlib.sha256()
        for d in sorted(dateien):
            h.update(b"D\0" + d.encode() + b"\0" + self.datei(d).encode() + b"\n")
        for v in sorted(verzeichnisse):
            h.update(b"V\0" + v.encode() + b"\0" + self.verzeichnis(v).encode() + b"\n")
        return h.hexdigest()
