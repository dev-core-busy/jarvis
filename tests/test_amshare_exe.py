#!/usr/bin/env python3
"""Bereitstellung im Netz (AI-Maus): der Server liefert die EXE auch OHNE ZIP.

Der Ordner-Knopf in *Einstellungen → AI-Maus → Bereitstellung im Netz*
schreibt die Anwendung direkt auf die Freigabe; das Pfadfeld nennt
``…\\AiMouse.exe``, also gehoert die EXE dorthin und nicht das ZIP.

Gemessen wird die WIRKUNG, nicht ein Vorkommen:
  1. ``exe_holen`` liefert byte-gleich die Datei, die im ZIP steckt – beide
     Wege gehen durch DIESELBE Vorbereitung (``_exe_bereit``), sonst luede der
     Ordner-Knopf eine andere Anwendung als der Download.
  2. Fehlt die Anwendung, wirft ``exe_holen`` wie ``paket_bauen``.
  3. Die Route ``/api/ai-mouse/paket`` ruft ``exe_holen`` NUR bei
     ``form=exe`` (am Syntaxbaum, Docstrings zaehlen nicht) und bleibt sonst
     beim ZIP.

    python3 tests/test_amshare_exe.py      Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen
"""
import ast
import io
import os
import sys
import tempfile
import zipfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ok = fail = 0


def check(text, bed):
    global ok, fail
    if bed:
        ok += 1
        print("  OK   " + text)
    else:
        fail += 1
        print("  FAIL " + text)


try:
    from backend import ai_mouse as am  # noqa: E402
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: backend.ai_mouse nicht ladbar: %s" % e)
    sys.exit(2)

# ── 1+2: Wirkung von exe_holen ────────────────────────────────────────────
# ⚠ `_vorgaben_sicherstellen` SCHREIBT Vorgaben.cs und stoesst einen Bau an –
#   hier eine Attrappe, die nur zaehlt. Der Sandkasten traegt die EXE.
print("── exe_holen liefert dieselbe Anwendung wie das ZIP")
alt = (am._vorgaben_sicherstellen, am.exe_pfad, am.paket_vorhanden)
aufrufe = []
with tempfile.TemporaryDirectory() as tmp:
    exe = Path(tmp) / "AiMouse.exe"
    inhalt = b"MZ\x90\x00" + os.urandom(4096)
    exe.write_bytes(inhalt)
    try:
        am._vorgaben_sicherstellen = lambda b, m, a: aufrufe.append((b, m, a)) or False
        am.exe_pfad = lambda: exe
        am.paket_vorhanden = lambda: True

        # Positivkontrolle: der Sandkasten wird wirklich benutzt.
        if am.exe_pfad() != exe or not am.paket_vorhanden():
            print("ABBRUCH: Attrappen greifen nicht")
            sys.exit(2)

        name, daten = am.exe_holen("https://h", "M", "#000000")
        check("Dateiname ist EXE_NAME (%r)" % name, name == am.EXE_NAME)
        check("Inhalt byte-gleich mit der EXE", daten == inhalt)
        check("Vorbereitung (Hauswerte) lief fuer den EXE-Weg", len(aufrufe) == 1)

        zname, zdaten = am.paket_bauen("https://h", "M", "#000000")
        with zipfile.ZipFile(io.BytesIO(zdaten)) as z:
            namen = z.namelist()
            zinhalt = z.read(am.EXE_NAME) if am.EXE_NAME in namen else b""
        check("ZIP-Weg unveraendert: genau die EXE im ZIP (%r)" % namen,
              namen == [am.EXE_NAME])
        check("EXE-Weg und ZIP-Weg liefern dieselben Bytes", zinhalt == daten)
        check("ZIP-Name traegt weiter die Marke (%r)" % zname, zname == "m-ai-mouse.zip")
        check("Vorbereitung lief auch fuer den ZIP-Weg", len(aufrufe) == 2)

        print("── fehlt die Anwendung, wirft exe_holen")
        am.paket_vorhanden = lambda: False
        am.bau_zustand_alt = am.bau_zustand
        am.bau_zustand = lambda: {}
        try:
            am.exe_holen("", "", "")
            geworfen = False
        except am.MausFehler:
            geworfen = True
        finally:
            am.bau_zustand = am.bau_zustand_alt
            del am.bau_zustand_alt
        check("MausFehler statt leerer Datei", geworfen)
    finally:
        am._vorgaben_sicherstellen, am.exe_pfad, am.paket_vorhanden = alt

# ── 3: Route am Syntaxbaum ────────────────────────────────────────────────
print("── Route /api/ai-mouse/paket")
baum = ast.parse((WURZEL / "backend" / "main.py").read_text(encoding="utf-8"))
route = None
for k in ast.walk(baum):
    if isinstance(k, ast.AsyncFunctionDef) and k.name == "ai_mouse_paket":
        route = k
        break
if route is None:
    print("ABBRUCH: Route ai_mouse_paket nicht gefunden")
    sys.exit(2)


def rufe(knoten, name):
    return [c for c in ast.walk(knoten) if isinstance(c, ast.Call)
            and isinstance(c.func, ast.Attribute) and c.func.attr == name]


# Positivkontrolle: der ZIP-Weg ist am Baum ueberhaupt auffindbar.
if not rufe(route, "paket_bauen"):
    print("ABBRUCH: paket_bauen in der Route nicht gefunden – Sonde blind")
    sys.exit(2)

# Die Weiche: ein `if`, dessen Rumpf exe_holen ruft und dessen else-Zweig
# paket_bauen ruft; die Bedingung haengt an einem Namen, der aus dem
# Abfrageparameter `form` mit dem Wert "exe" entsteht.
weiche = None
for k in ast.walk(route):
    if isinstance(k, ast.If):
        rumpf = ast.Module(body=k.body, type_ignores=[])
        sonst = ast.Module(body=k.orelse, type_ignores=[])
        if rufe(rumpf, "exe_holen") and rufe(sonst, "paket_bauen"):
            weiche = k
check("Weiche: exe_holen im if, paket_bauen im else", weiche is not None)
check("exe_holen wird genau einmal gerufen", len(rufe(route, "exe_holen")) == 1)

bed_name = weiche.test.id if weiche is not None and isinstance(weiche.test, ast.Name) else None
quelle_ok = False
for k in ast.walk(route):
    if (isinstance(k, ast.Assign) and bed_name
            and any(isinstance(z, ast.Name) and z.id == bed_name for z in k.targets)):
        konst = {c.value for c in ast.walk(k.value) if isinstance(c, ast.Constant)}
        quelle_ok = "form" in konst and "exe" in konst
check("Bedingung entsteht aus ?form=exe", quelle_ok)

print("\n%d OK, %d FAIL" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
