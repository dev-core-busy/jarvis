#!/usr/bin/env python3
"""Waechter: der in Pillow gebuendelte Brotli-Decoder (CVE-2026-111497).

LAGE (gemessen 2026-10-26): die Pillow-Wheels bringen einen eigenen Brotli-
Decoder mit (``pillow.libs/libbrotlidec-<kennung>.so.<fassung>``). Pillow 13.0.0
(gesperrt in requirements.lock, neueste Fassung) buendelt 1.2.0 – verwundbar
bis einschliesslich 1.2.0, behoben in 1.2.1. Kein System-Update erreicht diese
Kopie (Debians libbrotli1 1.1.0-2+deb13u1 ist auf DEV und ECHT gepatcht, Node
24.22.1 ebenfalls). Pillow zieht 1.2.1 ueber seine automatische Abhaengigkeits-
Aktualisierung am 2026-11-03 nach (Pillow-PR 10305); ein Release dazu gab es
noch nicht.

BEWERTUNG (Betreiberentscheid 2026-10-26: bewerten + Wiedervorlage): Pillow
benutzt Brotli nur ueber FreeType zum Entpacken von WOFF2-Schriften. Jarvis
laedt in Pillow ausschliesslich feste Systemschriften; der Branding-Upload
nimmt nur TrueType/OpenType an (Inhaltskennung) und geht an fontconfig, nicht
an Pillow. Ein Angreifer erreicht den Decoder damit nicht.

Diese Bewertung darf NICHT still veralten. Geprueft wird deshalb:
  1. Fassung des gebuendelten Decoders im Interpreter dieses Laufs:
     >= 1.2.1 -> gruen mit Hinweis "Ausnahme streichen"; darunter nur bis FRIST.
  2. Regel: jede Schriftstelle von Pillow in backend/ und skills/ laedt nur
     Pfade aus Konstanten unter /usr/share/fonts/ (am Syntaxbaum).
  3. Der Branding-Upload weist WOFF/WOFF2 ab – AUSGEFUEHRT, nach Endung UND
     nach Inhalt.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Wiedervorlage: bis hierhin gilt die Bewertung. Danach rot, bis entweder ein
# Pillow mit Brotli >= 1.2.1 gesperrt ist oder neu bewertet (und die Frist
# begruendet verschoben) wurde.
FRIST = datetime.date(2026, 12, 1)
BEHOBEN = (1, 2, 1)
SCHRIFT_WURZEL = "/usr/share/fonts/"

OK = FAIL = 0


def check(name, bed, info=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(info)[:300] + "]") if info != "" else ""))


def abbruch(grund):
    print("ABBRUCH (konnte nicht laufen): " + grund)
    sys.exit(2)


def fassung(dateiname: str):
    """``libbrotlidec-7e5462ba.so.1.2.0`` -> (1, 2, 0); ohne Fassung None."""
    m = re.search(r"libbrotlidec[^/]*?\.so\.(\d+)\.(\d+)\.(\d+)$", dateiname)
    return tuple(int(x) for x in m.groups()) if m else None


# ═════════════════════════════════════════════════════════════════════════════
print("[0] Positivkontrollen")
check("Fassung aus einem echten Wheel-Namen gelesen",
      fassung("libbrotlidec-7e5462ba.so.1.2.0") == (1, 2, 0))
check("ohne Fassung im Namen: None (kein Raten)", fassung("libbrotlidec.so") is None)

# ═════════════════════════════════════════════════════════════════════════════
print("\n[1] Gebuendelter Brotli-Decoder in Pillow")
try:
    import PIL
except Exception as e:  # noqa: BLE001
    abbruch("Pillow nicht importierbar: %s" % e)
libs = Path(PIL.__file__).resolve().parent.parent / "pillow.libs"
gefunden = sorted(p.name for p in libs.glob("libbrotlidec*")) if libs.is_dir() else []
heute = datetime.date.today()
print("       Pillow %s, %s" % (PIL.__version__, ", ".join(gefunden) or "kein gebuendelter Decoder"))
if not gefunden:
    check("kein gebuendelter Decoder (Pillow nutzt die System-Bibliothek)", True)
else:
    fassungen = [fassung(n) for n in gefunden]
    if any(f is None for f in fassungen):
        abbruch("Fassung des gebuendelten Decoders nicht lesbar: %s" % gefunden)
    alt = min(fassungen)
    if alt >= BEHOBEN:
        check("gebuendelter Decoder %s >= 1.2.1 – AUSNAHME STREICHEN (requirements.txt, "
              "BSI-Seite M6, diese Frist)" % ".".join(map(str, alt)), True)
    else:
        check("gebuendelter Decoder %s < 1.2.1 nur bis zur Wiedervorlage %s (bewertet: "
              "nicht erreichbar)" % (".".join(map(str, alt)), FRIST.isoformat()),
              heute <= FRIST,
              "Frist abgelaufen – Pillow mit Brotli >= 1.2.1 sperren oder neu bewerten")

# ═════════════════════════════════════════════════════════════════════════════
print("\n[2] Regel: Pillow laedt nur feste Systemschriften")
SCHRIFT_AUFRUFE = {"truetype", "FreeTypeFont", "load", "load_path"}


def _sichere_namen(baum: ast.Module) -> set:
    """Modulkonstanten, die nur aus Pfaden unter SCHRIFT_WURZEL bestehen."""
    aus = set()
    for n in baum.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            werte = n.value.elts if isinstance(n.value, (ast.Tuple, ast.List)) else [n.value]
            if werte and all(isinstance(w, ast.Constant) and isinstance(w.value, str)
                             and w.value.startswith(SCHRIFT_WURZEL) for w in werte):
                aus.add(n.targets[0].id)
    return aus


def _blaetter(ausdruck):
    """Namen und Konstanten, aus denen ein Ausdruck seinen Wert nimmt."""
    if isinstance(ausdruck, ast.IfExp):
        return _blaetter(ausdruck.body) + _blaetter(ausdruck.orelse)
    return [ausdruck]


def _sicher(arg, fn, sichere) -> bool:
    for b in _blaetter(arg):
        if isinstance(b, ast.Constant):
            if not (isinstance(b.value, str) and b.value.startswith(SCHRIFT_WURZEL)):
                return False
            continue
        if not isinstance(b, ast.Name):
            return False
        if b.id in sichere:
            continue
        # lokale Variable: jede Zuweisung bzw. Schleife muss aus sicheren Quellen kommen
        quellen = []
        for k in ast.walk(fn):
            if isinstance(k, ast.Assign) and any(isinstance(t, ast.Name) and t.id == b.id
                                                 for t in k.targets):
                quellen.append(("wert", k.value))
            if isinstance(k, ast.For) and isinstance(k.target, ast.Name) and k.target.id == b.id:
                quellen.append(("schleife", k.iter))
            if isinstance(k, ast.arguments) and b.id in [a.arg for a in k.args + k.kwonlyargs]:
                return False          # Parameter: Herkunft unbekannt
        if not quellen:
            return False
        for art, q in quellen:
            if art == "schleife":
                if not (isinstance(q, ast.Name) and q.id in sichere):
                    return False
            elif not all((isinstance(x, ast.Name) and x.id in sichere)
                         or (isinstance(x, ast.Constant) and isinstance(x.value, str)
                             and x.value.startswith(SCHRIFT_WURZEL))
                         for x in _blaetter(q)):
                return False
    return True


def schriftstellen(quelltext: str):
    """[(zeile, sicher?)] fuer jeden Pillow-Schriftaufruf einer Datei."""
    baum = ast.parse(quelltext)
    if "ImageFont" not in quelltext:
        return []
    sichere = _sichere_namen(baum)
    aus = []
    for fn in [n for n in ast.walk(baum) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))] + [baum]:
        for k in ast.walk(fn):
            if (isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute)
                    and k.func.attr in SCHRIFT_AUFRUFE
                    and isinstance(k.func.value, ast.Name) and k.func.value.id == "ImageFont"):
                if fn is baum and any(k in ast.walk(f) for f in ast.walk(baum)
                                      if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))):
                    continue      # schon ueber die Funktion erfasst
                arg = k.args[0] if k.args else None
                aus.append((k.lineno, arg is not None and _sicher(arg, fn, sichere)))
    return aus


# Positivkontrollen der Regel – sie muss beide Richtungen unterscheiden
GUT = ('S = ("/usr/share/fonts/a.ttf", "/usr/share/fonts/b.ttf")\n'
       'def f(g):\n    from PIL import ImageFont\n'
       '    for p in S:\n        return ImageFont.truetype(p, g)\n')
SCHLECHT = ('def f(pfad, g):\n    from PIL import ImageFont\n'
            '    return ImageFont.truetype(pfad, g)\n')
if schriftstellen(GUT) != [(5, True)] or schriftstellen(SCHLECHT) != [(3, False)]:
    abbruch("Regel unterscheidet nicht (gut=%s, schlecht=%s)"
            % (schriftstellen(GUT), schriftstellen(SCHLECHT)))
check("Positivkontrolle: Regel trennt feste Schrift von Parameter", True)

dateien = [p for d in ("backend", "skills") for p in (ROOT / d).rglob("*.py")]
if len(dateien) < 50:
    abbruch("nur %d Python-Dateien gefunden – Geltungsbereich falsch?" % len(dateien))
stellen, unsicher = 0, []
for p in dateien:
    try:
        for zeile, ok in schriftstellen(p.read_text(encoding="utf-8")):
            stellen += 1
            if not ok:
                unsicher.append("%s:%d" % (p.relative_to(ROOT), zeile))
    except SyntaxError as e:
        abbruch("nicht parsebar: %s (%s)" % (p, e))
check("Positivkontrolle: Schriftstellen gefunden (%d)" % stellen, stellen >= 2)
check("jede Pillow-Schriftstelle laedt nur Konstanten unter %s" % SCHRIFT_WURZEL,
      not unsicher, "; ".join(unsicher))

# ═════════════════════════════════════════════════════════════════════════════
print("\n[3] Branding-Upload weist WOFF/WOFF2 ab (ausgefuehrt)")
try:
    from backend import branding_schriften as bs
except Exception as e:  # noqa: BLE001
    abbruch("branding_schriften nicht importierbar: %s" % e)
ttf = b"\x00\x01\x00\x00" + b"\x00" * 64
ok, _, _ = bs.pruefen(ttf, "probe.ttf")
if not ok:
    abbruch("Positivkontrolle: eine gueltige TrueType-Kennung wird abgewiesen")
check("Positivkontrolle: TrueType wird angenommen", True)
for name in ("probe.woff2", "probe.woff"):
    check("Endung %s abgewiesen" % name.split(".")[-1], not bs.pruefen(ttf, name)[0])
check("WOFF2-Inhalt unter .ttf-Namen abgewiesen (Inhalt entscheidet)",
      not bs.pruefen(b"wOF2" + b"\x00" * 64, "probe.ttf")[0])
check("WOFF-Inhalt unter .ttf-Namen abgewiesen",
      not bs.pruefen(b"wOFF" + b"\x00" * 64, "probe.ttf")[0])

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
