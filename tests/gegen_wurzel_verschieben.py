#!/usr/bin/env python3
"""Gegenproben: Wurzelordner in einen anderen Wissensordner verschieben.

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob
``tests/test_wurzel_verschieben.py`` (bzw. fuer die Oberflaeche
``tests/test_csp_h4_wissen_klick.js`` / ``tests/test_auto_gruppe_ui.js``) das
meldet. Eine Probe, die nicht
beisst, ist ein Testmangel – oder die Zusage existiert gar nicht.

Wie in den uebrigen Harnessen: jede angefasste Datei steht geprueft in der
Sicherung (Exit 2), eine Laufmarke nimmt den Rueckstand eines abgeschossenen
Laufs beim naechsten Start zurueck, ein gruener Basislauf ist Bedingung, und
gelaufen wird ohne Bytecode.
"""
from __future__ import annotations

import atexit
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABL = Path.home() / ".gegen-wurzel-verschieben"
MARKE = ABL / "LAUF"

MAIN = "backend/main.py"
KN = "backend/tools/knowledge.py"
KS = "backend/knowledge_sync.py"
KJS = "frontend/js/knowledge.js"
DATEIEN = [MAIN, KN, KS, KJS]

W = [sys.executable, str(ROOT / "tests" / "test_wurzel_verschieben.py")]
W_UI = ["node", str(ROOT / "tests" / "test_csp_h4_wissen_klick.js")]
W_UI2 = ["node", str(ROOT / "tests" / "test_auto_gruppe_ui.js")]
UMG = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def sichern() -> None:
    ABL.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, ABL / rel.replace("/", "__"))
    MARKE.write_text("laeuft\n", encoding="utf-8")


def zurueck() -> None:
    for rel in DATEIEN:
        q = ABL / rel.replace("/", "__")
        if q.is_file():
            shutil.copy2(q, ROOT / rel)


def aufraeumen() -> None:
    zurueck()
    if MARKE.exists():
        MARKE.unlink()


if MARKE.exists():
    print("⚠ Rueckstand eines frueheren Laufs gefunden – wird zurueckgenommen.")
    zurueck()
    MARKE.unlink()


def lauf(cmd) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300, env=UMG)
    return p.returncode, p.stdout + p.stderr


def bilanz(aus: str) -> list[str]:
    return [z for z in aus.splitlines() if "ergebnis:" in z.lower()]


def bewerte(cmd) -> tuple[bool, str]:
    rc, aus = lauf(cmd)
    b = bilanz(aus)
    if not b:
        # Ein Abbruch ohne Bilanz ist KEIN Biss (Register).
        return False, f"ABGEBROCHEN rc={rc} (keine Bilanz)"
    fails = sum(1 for z in aus.splitlines() if z.lstrip().startswith(("FAIL", "❌")))
    return (rc == 1 and fails > 0), f"{b[-1].strip()}"


PROBEN = [
    # (Name, Datei, alt, neu[, Waechter]) – ohne Waechter: der Python-Waechter
    ("Admin-Endpunkt laesst Wurzeln nicht zu", MAIN,
     '    res, err, code = _kb_move_folder(data.get("path") or "", data.get("target") or "",\n'
     '                                     wurzel_erlaubt=True)',
     '    res, err, code = _kb_move_folder(data.get("path") or "", data.get("target") or "")'),
    ("/wissen darf Wurzeln verschieben", MAIN,
     "    res, err, code = _kb_move_folder(src, dst)",
     "    res, err, code = _kb_move_folder(src, dst, wurzel_erlaubt=True)"),
    ("Schalter wird ignoriert (Wurzel immer erlaubt)", MAIN,
     "    if ist_wurzel and not wurzel_erlaubt:", "    if False:"),
    ("Wurzel ausserhalb data/rag wird angenommen", MAIN,
     "    if ist_wurzel and (not _rag.ist_rag_ordner(src)\n"
     "                       or src.rsplit(\"/\", 1)[0] != _rag.RAG_REL):",
     "    if False:"),
    ("Ordnerliste wird VOR der Relokation gespeichert", MAIN,
     "    moved = relocate_folder_index(old_abs, new_abs)\n    if ist_wurzel:",
     "    if ist_wurzel:\n"
     "        _kb_save_folder_list([f for f in _kb_current_folder_list() if _kb_norm_rel(f) != src])\n"
     "    moved = relocate_folder_index(old_abs, new_abs)\n    if ist_wurzel:"),
    ("Wurzel bleibt in der Ordnerliste", MAIN,
     "        liste = [f for f in _kb_current_folder_list() if _kb_norm_rel(f) != src]",
     "        liste = _kb_current_folder_list()"),
    ("Freigaben: Praefix ohne Schraegstrich (beispiel trifft beispiel2)", KS,
     '            if f == alt or f.startswith(alt + "/"):',
     '            if f == alt or f.startswith(alt):'),
    ("relocate_folder_index zieht Freigaben nicht mit", KN,
     "        moved_shares = ks.freigaben_verschieben(_folder_rel(old_folder), _folder_rel(new_folder))",
     "        moved_shares = 0"),
    # ── Gegenrichtung: Ziel data/rag ──
    ("Ziel data/rag auch ohne Schalter (/wissen)", MAIN,
     "    zur_wurzel = wurzel_erlaubt and dst_parent == _rag.RAG_REL",
     "    zur_wurzel = dst_parent == _rag.RAG_REL"),
    ("Ziel data/rag wird nie angenommen", MAIN,
     "    zur_wurzel = wurzel_erlaubt and dst_parent == _rag.RAG_REL",
     "    zur_wurzel = False"),
    ("Namensregel der Anlage fehlt", MAIN,
     "        fehler = _kb_validate_folder_name(name)\n", "        fehler = None\n"),
    ("Neue Wurzel wird nicht eingetragen", MAIN,
     "        if not _kb_save_folder_list(_kb_current_folder_list() + [new_rel]):",
     "        if not _kb_save_folder_list(_kb_current_folder_list()):"),
    ("Kein Zurueckverschieben, wenn die Liste scheitert", MAIN,
     "            try:\n                new_abs.rename(old_abs)\n            except OSError as e:",
     "            try:\n                pass\n            except OSError as e:"),
    ("Eintrag NACH der Relokation (falsche Reihenfolge)", MAIN,
     "    if zur_wurzel:\n        # ⚠ HIER ANDERSHERUM",
     "    moved = relocate_folder_index(old_abs, new_abs)\n    if zur_wurzel:\n        # ⚠ HIER ANDERSHERUM"),
    ("Oberflaeche bietet 'oberste Ebene' nicht an", KJS,
     "        if (path.startsWith(RAG + '/') && parent !== RAG) {",
     "        if (false) {", W_UI2),
    ("Oberflaeche bietet 'oberste Ebene' auch der Wurzel an", KJS,
     "        if (path.startsWith(RAG + '/') && parent !== RAG) {",
     "        if (path.startsWith(RAG + '/')) {", W_UI2),
    ("Meldung sagt nicht 'eigener Wissensordner'", KJS,
     "                : r.now_root\n", "                : false\n", W_UI2),
    # ── Oberflaeche ──
    ("Kein Verschieben-Knopf an der Wurzel", KJS,
     "${wurzelGruppen}${wurzelSchieben}<button", "${wurzelGruppen}<button", W_UI),
    ("Verschieben-Knopf auch an Wurzeln ausserhalb data/rag", KJS,
     "        const wurzelSchieben = umbenennbar\n", "        const wurzelSchieben = true\n", W_UI),
    ("Meldung sagt nicht, dass die Wurzel jetzt Unterordner ist", KJS,
     "            const meldung = r.was_root\n", "            const meldung = false\n", W_UI2),
]

fehlt = {rel for _, rel, *_ in PROBEN} - set(DATEIEN)
if fehlt:
    print(f"ABBRUCH: nicht gesicherte Dateien in den Proben: {sorted(fehlt)}")
    sys.exit(2)

sichern()
atexit.register(aufraeumen)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

print("Basislauf")
for cmd, name in ((W, "test_wurzel_verschieben"), (W_UI, "test_csp_h4_wissen_klick"),
                  (W_UI2, "test_auto_gruppe_ui")):
    rc, aus = lauf(cmd)
    b = bilanz(aus)
    print(f"  {name}: {b[-1].strip() if b else 'KEINE BILANZ'}")
    if rc != 0 or not b:
        print("ABBRUCH: Basis nicht gruen – Gegenproben waeren nicht deutbar")
        sys.exit(2)

print(f"\n{len(PROBEN)} Gegenproben")
beissen, stumm = 0, []
for name, rel, alt, neu, *wahl in PROBEN:
    cmd = wahl[0] if wahl else W
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    if s.count(alt) != 1:
        print(f"  ⚠ {name}: SABOTAGE TRIFFT NICHT ({s.count(alt)}x) – Probe unbrauchbar")
        stumm.append(name + " (trifft nicht)")
        continue
    p.write_text(s.replace(alt, neu, 1), encoding="utf-8")
    try:
        gemeldet, info = bewerte(cmd)
    finally:
        zurueck()
    if gemeldet:
        beissen += 1
        print(f"  ✓ {name} → {info}")
    else:
        stumm.append(name)
        print(f"  ✗ {name} → BEISST NICHT ({info})")

abweichend = [rel for rel in DATEIEN
              if (ROOT / rel).read_bytes() != (ABL / rel.replace("/", "__")).read_bytes()]
print(f"\nErgebnis: {beissen}/{len(PROBEN)} Proben beissen")
print(f"Arbeitsbaum wiederhergestellt: {'ja' if not abweichend else 'NEIN – ' + str(abweichend)}")
if stumm:
    print("Stumm: " + "; ".join(stumm))
sys.exit(1 if (stumm or abweichend) else 0)
