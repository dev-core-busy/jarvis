#!/usr/bin/env python3
"""Waechter: Code-Kommentare und Docstrings sind DEUTSCH.

Festlegung des Betreibers (2026-10-15): alle Kommentare im Code ausschliesslich
auf Deutsch. Der Bestand wurde an diesem Tag uebersetzt; dieser Waechter sorgt
dafuer, dass kein englischer Kommentar zurueckkommt.

WAS ER MISST
  Je Datei werden die Kommentare extrahiert (Python: ``tokenize`` fuer ``#`` und
  ``ast`` fuer Docstrings - ``tokenize`` allein kennt keine Docstrings, Register;
  JS/Go/Kotlin/CSS/Shell: ein Scanner, der Zeichenketten UEBERSPRINGT, damit ein
  ``//`` in einer URL kein Kommentar ist). Aufeinanderfolgende Kommentarzeilen
  werden zu EINEM Block verbunden - ein Zitat, das ueber zwei Zeilen laeuft,
  wird so als Zitat erkannt und nicht als englischer Satz.
  Aus jedem Block fallen Zitate (``"..."``, ``„..."``, Backticks) und
  Code-Bruchstuecke heraus; der Rest wird ueber FUNKTIONSWOERTER beurteilt:
  englisch ist ein Block mit mindestens zwei englischen Funktionswoertern und
  keinem einzigen deutschen.

WAS ER NICHT KANN (bewusst, damit er keine Fehlalarme produziert)
  * Zwei-Wort-Kommentare ohne Funktionswort (``# Create image``) sieht er nicht -
    an ihnen ist die Sprache nicht entscheidbar, ohne Fachbegriffe wie
    ``# Fallback`` oder ``── Init ──`` anzuschlagen.
  * Englische Fachbegriffe in einem deutschen Satz sind erlaubt und gemeint.
  * Zitierte englische Fehlermeldungen sind Belege, keine Kommentarsprache.

AUSGENOMMEN (mit Grund - ein Geltungsbereich ohne Grund ist eine Luecke):
  * Fremdcode: ``vendor/``, ``*.min.js``, ``node_modules/``, noVNC - nicht
    unser Text, wird beim Aktualisieren ueberschrieben.
  * ``tests/gegen_kommentare_deutsch.py`` - traegt englische Probesaetze als
    Daten, anders laesst sich nicht messen, ob dieser Waechter beisst.

Exit 0 = gruen, 1 = englische Kommentare gefunden, 2 = konnte nicht messen.
"""
import ast
import io
import re
import subprocess
import sys
import tokenize
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent

ENDUNGEN_HASH = {".py", ".sh"}
ENDUNGEN_C = {".js", ".mjs", ".cjs", ".ts", ".go", ".kt", ".java", ".css"}

AUSNAHME_MUSTER = re.compile(
    r"(^|/)(vendor|node_modules)/|\.min\.js$|novnc", re.IGNORECASE)
AUSNAHME_DATEIEN = {"tests/gegen_kommentare_deutsch.py"}

# Funktionswoerter. Bewusst DISJUNKT und ohne Woerter, die in beiden Sprachen
# vorkommen ("an", "so", "also", "in", "will") oder als Code-Schluesselwort in
# deutschen Saetzen stehen ("else", "none", "true", "return", "set", "get").
EN = set("""
the a this that these those with from to of and or not when then which what
because should would could must can don't doesn't isn't can't won't
is are was were be been being has have had does do it its we you they our your
if for on at by into only each any all but just than there here how why where
used using uses
""".split())
DE = set("""
der die das den dem des ein eine einen einem einer eines und oder nicht ist
sind wird werden wurde wurden wenn dann sonst mit fuer für von zu zum zur im
kein keine keinen keiner auch nur alle bei als aber weil damit dass daß hier
wie wer noch schon muss soll kann darf nach vor ueber über aus sich es ob
bis beim vom am ohne gegen durch seit hat haben jede jeder jedes diese dieser
dieses man nie immer liefert gibt steht liegt
""".split())

_ZITAT = re.compile(
    r'"[^"\n]*"|“[^”\n]*”|„[^“”\n]*[“”]|«[^»\n]*»|`[^`]*`|'
    r"(?<![A-Za-z])'[^'\n]*'(?![A-Za-z])", re.S)
_CODEWORT = re.compile(r"\S*[_./\\=<>(){}\[\]:#@$0-9]\S*")


def _woerter(text: str):
    """Woerter eines Kommentars ohne Zitate und Code-Bruchstuecke."""
    text = _ZITAT.sub(" ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = _CODEWORT.sub(" ", text)
    return re.findall(r"[A-Za-zÄÖÜäöüß']+", text.lower())


def ist_englisch(text: str) -> bool:
    w = _woerter(text)
    if re.search(r"[äöüßÄÖÜ]", _ZITAT.sub(" ", text)):
        return False
    en = sum(x in EN for x in w)
    de = sum(x in DE for x in w)
    return en >= 2 and de == 0


# ── Extraktion ──────────────────────────────────────────────────────────────

def _bloecke(zeilen):
    """[(zeile, text)] -> zusammenhaengende Bloecke [(erste_zeile, text)]."""
    out = []
    for nr, txt in sorted(zeilen):
        if out and nr == out[-1][2] + 1:
            out[-1] = (out[-1][0], out[-1][1] + "\n" + txt, nr)
        else:
            out.append((nr, txt, nr))
    return [(a, t) for a, t, _e in out]


def kommentare_py(src: str):
    zeilen = []
    try:
        for t in tokenize.generate_tokens(io.StringIO(src).readline):
            if t.type == tokenize.COMMENT and not t.string.startswith("#!"):
                zeilen.append((t.start[0], t.string.lstrip("#")))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    bl = _bloecke(zeilen)
    try:
        baum = ast.parse(src)
    except SyntaxError:
        return None
    for k in ast.walk(baum):          # enthaelt die Wurzel bereits
        if isinstance(k, (ast.Module, ast.ClassDef, ast.FunctionDef,
                          ast.AsyncFunctionDef)):
            ds = ast.get_docstring(k, clean=False)
            if ds and k.body:
                bl.append((k.body[0].lineno, ds))
    return bl


_C_SCAN = re.compile(
    r'"(?:\\.|[^"\\\n])*"|\'(?:\\.|[^\'\\\n])*\'|`(?:\\.|[^`\\])*`'
    r"|(?P<z>//[^\n]*)|(?P<b>/\*.*?\*/)", re.S)


def kommentare_c(src: str, endung: str):
    zeilen, bloecke = [], []
    for m in _C_SCAN.finditer(src):
        nr = src.count("\n", 0, m.start()) + 1
        if m.group("z") is not None:
            if endung == ".css":
                continue          # in CSS ist // kein Kommentar (URLs)
            txt = m.group("z")[2:]
            if txt.startswith("go:build") or txt.startswith("/ <reference"):
                continue
            zeilen.append((nr, txt))
        elif m.group("b") is not None:
            bloecke.append((nr, m.group("b")[2:-2]))
    return _bloecke(zeilen) + bloecke


_SH_ZITAT = re.compile(r'"(?:\\.|[^"\\\n])*"|\'[^\'\n]*\'')


def kommentare_sh(src: str):
    zeilen = []
    for nr, z in enumerate(src.split("\n"), 1):
        if nr == 1 and z.startswith("#!"):
            continue
        ohne = _SH_ZITAT.sub(lambda m: " " * len(m.group(0)), z)
        m = re.search(r"(^|\s)#(?!!)", ohne)
        if m:
            zeilen.append((nr, z[m.end():]))
    return _bloecke(zeilen)


def kommentare(pfad: Path, src: str):
    e = pfad.suffix
    if e == ".py":
        return kommentare_py(src)
    if e == ".sh":
        return kommentare_sh(src)
    return kommentare_c(src, e)


# ── Positivkontrolle der Messmethode ───────────────────────────────────────
# Ohne sie waere ein blinder Klassifikator oder Scanner von "alles deutsch"
# nicht zu unterscheiden.

def positivkontrolle():
    fehler = []
    englisch = [
        "Check if the pixel is close to the background color",
        "sameDay returns true if two times are on the same calendar day.",
        "Try to find a sans-serif font",
        "We allow a small tolerance for anti-aliasing artifacts if any",
        "Mandatory TLS to the domain controller (BSI H5)",
    ]
    deutsch = [
        "Liegt der Bildpunkt nahe an der Hintergrundfarbe?",
        "Fallback: eigene minimale QR-Darstellung",
        "── Init ──",
        "Fehlermeldung von EWS (\"EWS does not support filtering on field 'id'\")",
        "Isolation: Vorgabe AN, deshalb `is not False` – bei `is True` waere es",
        "Rueckfall: was bietet dieses Konto ueberhaupt an?",
    ]
    for s in englisch:
        if not ist_englisch(s):
            fehler.append("Klassifikator erkennt Englisch nicht: %r" % s)
    for s in deutsch:
        if ist_englisch(s):
            fehler.append("Klassifikator meldet Deutsch als Englisch: %r" % s)

    py = ('"""Modul-Doku with the text."""\n'
          'x = "# kein Kommentar"\n'
          '# Kommentarzeile eins\n'
          '# Kommentarzeile zwei\n'
          'def f():\n    """Doku der Funktion."""\n')
    k = kommentare_py(py) or []
    texte = sorted(t.strip() for _n, t in k)
    soll = sorted(["Kommentarzeile eins\n Kommentarzeile zwei",
                   "Modul-Doku with the text.", "Doku der Funktion."])
    if texte != soll:
        fehler.append("Python-Extraktion falsch: %r" % texte)

    js = ('const u = "https://beispiel.de/x"; // echter Kommentar\n'
          "const s = '// kein Kommentar';\n/* Block */\n")
    k = [t.strip() for _n, t in kommentare_c(js, ".js")]
    if sorted(k) != ["Block", "echter Kommentar"]:
        fehler.append("JS-Extraktion falsch: %r" % k)

    sh = '#!/bin/bash\necho "a # b"\nx=${#arr[@]}\n# echter Kommentar\n'
    k = [t.strip() for _n, t in kommentare_sh(sh)]
    if k != ["echter Kommentar"]:
        fehler.append("Shell-Extraktion falsch: %r" % k)
    return fehler


# ── Lauf ────────────────────────────────────────────────────────────────────

def dateien():
    erg = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=WURZEL, capture_output=True)
    if erg.returncode != 0:
        return None
    out = []
    for roh in erg.stdout.split(b"\0"):
        rel = roh.decode("utf-8", "replace")
        if not rel:
            continue
        p = WURZEL / rel
        if p.suffix not in ENDUNGEN_HASH | ENDUNGEN_C:
            continue
        if AUSNAHME_MUSTER.search(rel) or rel in AUSNAHME_DATEIEN:
            continue
        if p.is_file():
            out.append((rel, p))
    return out


def main():
    fehler = positivkontrolle()
    if fehler:
        print("ABBRUCH (Exit 2): die Messmethode selbst ist defekt:")
        for f in fehler:
            print("  - " + f)
        return 2

    liste = dateien()
    if liste is None:
        print("ABBRUCH (Exit 2): git ls-files ist gescheitert.")
        return 2
    je_endung = {}
    for rel, _p in liste:
        je_endung[Path(rel).suffix] = je_endung.get(Path(rel).suffix, 0) + 1
    fehlend = [e for e in (".py", ".js", ".go", ".sh", ".css")
               if not je_endung.get(e)]
    if fehlend:
        print("ABBRUCH (Exit 2): keine Dateien mit Endung %s gefunden - "
              "Geltungsbereich kaputt." % ", ".join(fehlend))
        return 2

    funde, unlesbar, n_bloecke = [], [], 0
    for rel, p in liste:
        try:
            src = p.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            unlesbar.append(rel)
            continue
        bl = kommentare(p, src)
        if bl is None:
            unlesbar.append(rel)
            continue
        for nr, txt in bl:
            n_bloecke += 1
            if ist_englisch(txt):
                kurz = " ".join(txt.split())[:110]
                funde.append("%s:%d: %s" % (rel, nr, kurz))

    print("Geprueft: %d Dateien, %d Kommentarbloecke (%s)" % (
        len(liste), n_bloecke,
        ", ".join("%s %d" % kv for kv in sorted(je_endung.items()))))
    if unlesbar:
        print("Nicht auswertbar (Syntax/Kodierung), uebersprungen: %d" % len(unlesbar))
        for r in unlesbar:
            print("  ~ " + r)
    if funde:
        print("\nENGLISCHE KOMMENTARE (%d) - bitte auf Deutsch fassen:" % len(funde))
        for f in funde:
            print("  FAIL " + f)
        print("\nErgebnis: %d Fund(e)" % len(funde))
        return 1
    print("Ergebnis: alle Kommentare deutsch (0 Funde)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
