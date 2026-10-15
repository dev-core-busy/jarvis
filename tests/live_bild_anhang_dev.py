#!/usr/bin/env python3
"""Live auf DEV: der ECHTE Weg eines Bild-Anhangs, als Dienstbenutzer.

Gemessen wird die Kette, die im Vorfall gefehlt hat – mit dem ECHTEN
`lauf_tmp` (also echten Kennungen, echtem ANH_ROOT) und dem ECHTEN
`_anhang_ablegen`. Der Unit-Waechter laeuft gegen Attrappen; hier faellt auf,
was nur die Umgebung zeigt (Rechte, Eigentuemer, Pfadform).

RAEUMT HINTER SICH AUF: jede angelegte Datei wird am Ende entfernt und das
Ergebnis geprueft. Der VORGEFUNDENE Bestand bleibt unangetastet.
"""
import ast
import os
import sys
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")

OK = 0
FAIL = 0


def check(was, bed):
    global OK, FAIL
    if bed:
        OK += 1
        print(f"  OK   {was}")
    else:
        FAIL += 1
        print(f"  FAIL {was}")


PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4"
    "890000000a49444154789c6360000002000100ffff03000006000557bfabd400"
    "00000049454e44ae426082"
)

from backend import lauf_tmp as LT          # noqa: E402
from backend import sandbox as SBX          # noqa: E402
from backend import attachments as ATT      # noqa: E402

BENUTZER = "live.testbenutzer"
KENNUNG = LT.benutzer_kennung(BENUTZER)
print(f"Benutzer: {BENUTZER} -> Kennung {KENNUNG}")
print(f"ANH_ROOT: {LT.ANH_ROOT}  (echt)")

# Vorzustand merken – es darf nichts Fremdes angefasst werden.
VORHER = set()
if LT.ANH_ROOT.is_dir():
    VORHER = {p.name for p in LT.ANH_ROOT.iterdir()}
print(f"vorgefunden: {len(VORHER)} Kennungs-Verzeichnis(se)\n")
if KENNUNG in VORHER:
    print("ABBRUCH: Testkennung existiert bereits – kein sauberer Ausgangszustand")
    sys.exit(2)

MAIN = Path("/opt/jarvis/backend/main.py").read_text(encoding="utf-8")
_baum = ast.parse(MAIN)
teile = {}
for k in ast.walk(_baum):
    if isinstance(k, ast.FunctionDef) and k.name in (
            "_bild_als_datei", "_anhang_ablegen", "_anhang_merken"):
        teile[k.name] = ast.get_source_segment(MAIN, k) or ""
if len(teile) != 3:
    print(f"ABBRUCH: Funktionen nicht geschnitten ({sorted(teile)})")
    sys.exit(2)

from backend import documents as _docs_modul  # noqa: E402

ns = {
    "Path": Path, "os": os, "print": print,
    "_documents": _docs_modul,
    "__file__": "/opt/jarvis/backend/main.py",
    "_SESSION_ANHAENGE": {}, "_SESSION_ANHAENGE_MAX": 6,
    "_SESSION_ANHAENGE_SITZUNGEN": 200,
}
exec(compile("\n\n".join(teile[n] for n in
                         ("_anhang_ablegen", "_anhang_merken", "_bild_als_datei")),
             "<kette>", "exec"), ns)

import base64  # noqa: E402
B64 = base64.b64encode(PNG).decode()

angelegt = []
try:
    print("1) Bild-Anhang ueber den ECHTEN Weg")
    hinweis = ns["_bild_als_datei"](B64, "vorfall_probe.gif", BENUTZER, "live-sid",
                                    {"bild_text_ersetzen"})
    check("Hinweis entstanden", bool(hinweis))
    verz = LT.ANH_ROOT / KENNUNG
    kopien = sorted(verz.glob("anhang_*")) if verz.is_dir() else []
    angelegt += kopien
    check("DER FIX: Arbeitskopie liegt im eigenen Kennungs-Verzeichnis",
          len(kopien) == 1)
    if kopien:
        k = kopien[0]
        check("Hinweis nennt genau diesen Pfad", k.as_posix() in hinweis)
        check("Datei ist byte-gleich zum Bild", k.read_bytes() == PNG)
        st = os.stat(k)
        check("Rechte 0644 (nicht ausfuehrbar)", oct(st.st_mode)[-3:] == "644")
        check("Eigentuemer ist der Dienstbenutzer", st.st_uid == os.getuid())
        # Genau die Frage des Vorfalls: findet ein Werkzeug den Pfad?
        ok_read, grund = SBX.authorize_fs("read", str(k), username=BENUTZER)
        check("authorize_fs laesst den EIGENEN Anhang lesen", ok_read is True)
        ok_fremd, _ = SBX.authorize_fs("read", str(k), username="jemand.anders")
        check("... und einem FREMDEN nicht", ok_fremd is False)
    print()

    print("2) Die Enumeration aus dem Vorfall – ueber den echten Weg")
    ok_w, grund_w = SBX.authorize_fs("list", str(LT.ANH_ROOT), username=BENUTZER)
    check("DER VORFALL: list auf die Wurzel wird abgewiesen", ok_w is False)
    check("Meldung nennt das Verwaltungsverzeichnis",
          "Verwaltungsverzeichnis" in (grund_w or ""))
    check("Meldung nennt den Weg (Anhang-Hinweis)",
          "Anhang-Hinweis" in (grund_w or ""))
    ok_arb, _ = SBX.authorize_fs("list", str(LT.ARBEIT_ROOT), username=BENUTZER)
    check("ARBEIT_ROOT ebenso", ok_arb is False)
    ok_eigen, _ = SBX.authorize_fs("list", str(LT.ANH_ROOT / KENNUNG), username=BENUTZER)
    check("POSITIVKONTROLLE: eigenes Verzeichnis bleibt auflistbar", ok_eigen is True)
    # Die fremden Kennungen des ECHTEN Bestands bleiben zu.
    fremde = [n for n in VORHER if n != KENNUNG]
    if fremde:
        ok_f, _ = SBX.authorize_fs("list", str(LT.ANH_ROOT / fremde[0]), username=BENUTZER)
        check(f"fremdes Verzeichnis ({fremde[0]}) bleibt gesperrt", ok_f is False)
    print()

    print("3) Leere Kennungs-Verzeichnisse verschwinden (in EIGENER Wurzel)")
    for k in list(angelegt):
        k.unlink()
        angelegt.remove(k)
    check("Testverzeichnis ist jetzt leer", verz.is_dir() and not any(verz.iterdir()))

    # ⚠ DIESER TEIL LAEUFT IN EINER EIGENEN WURZEL, und das ist eine Lehre aus
    # dem ersten Lauf: gegen den ECHTEN ANH_ROOT gefahren hat das Aufraeumen
    # korrekt gearbeitet – und dabei NEBEN dem Testverzeichnis eine echte,
    # laengst leere Leiche entfernt ("2 Verzeichnisse entfernt"). Fachlich
    # richtig, als MESSUNG aber falsch: eine Probe stellt den vorgefundenen
    # Zustand wieder her, sie veraendert ihn nicht. Die Aufraeum-Logik ist reine
    # Dateisystem-Arbeit und braucht die echte Wurzel nicht.
    import shutil
    import tempfile
    import time
    sk = Path(tempfile.mkdtemp(prefix="live_leer_"))
    _echte_wurzel = LT.ANH_ROOT
    try:
        LT.ANH_ROOT = sk / "jarvis-anhaenge"
        LT.ANH_ROOT.mkdir(parents=True)
        if LT.ANH_ROOT == _echte_wurzel:
            print("ABBRUCH: Wurzel nicht umgebogen")
            sys.exit(2)
        leer = LT.ANH_ROOT / "deadbeef"
        voll = LT.ANH_ROOT / "cafebabe"
        leer.mkdir()
        voll.mkdir()
        (voll / "anhang_001122334455_wichtig.xlsx").write_bytes(b"daten")
        alt = time.time() - 86400
        os.utime(leer, (alt, alt))
        os.utime(voll, (alt, alt))

        weg = ATT._leere_kennungen_entfernen(0, os.getuid())   # nichts ist "alt"
        check("frisch/ungealtert: nichts wird entfernt", weg == [] and leer.is_dir())

        weg = ATT._leere_kennungen_entfernen(time.time() - 3600, os.getuid())
        check("DER BEFUND: altes LEERES Verzeichnis wird entfernt", not leer.exists())
        check("... und gemeldet", "deadbeef" in weg)
        check("VOLLES Verzeichnis bleibt (rmdir statt rmtree)", voll.is_dir())
        check("... und seine Datei ist unangetastet",
              (voll / "anhang_001122334455_wichtig.xlsx").read_bytes() == b"daten")
    finally:
        LT.ANH_ROOT = _echte_wurzel
        shutil.rmtree(sk, ignore_errors=True)
    check("echte Wurzel ist wieder gesetzt", LT.ANH_ROOT == _echte_wurzel)
finally:
    for k in angelegt:
        try:
            k.unlink()
        except Exception:  # noqa: BLE001
            pass
    verz = LT.ANH_ROOT / KENNUNG
    if verz.is_dir():
        try:
            for p in verz.iterdir():
                p.unlink()
            verz.rmdir()
        except Exception as e:  # noqa: BLE001
            print(f"  ⚠ Aufraeumen unvollstaendig: {e}")

print()
nachher = {p.name for p in LT.ANH_ROOT.iterdir()} if LT.ANH_ROOT.is_dir() else set()
check("AUSGANGSZUSTAND WIEDERHERGESTELLT (kein Rueckstand)", nachher == VORHER)
print(f"\nErgebnis: {OK} OK, {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
