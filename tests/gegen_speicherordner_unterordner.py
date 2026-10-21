#!/usr/bin/env python3
"""Gegenproben: Unterordner als Speicherordner einer Wissensgruppe.

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob
``tests/test_speicherordner_unterordner.py`` (bzw. fuer den Knopf
``tests/test_csp_h4_wissen_klick.js``) das meldet. Eine Probe, die nicht
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
ABL = Path.home() / ".gegen-speicherordner-unterordner"
MARKE = ABL / "LAUF"

MAIN = "backend/main.py"
KJS = "frontend/js/knowledge.js"
DATEIEN = [MAIN, KJS]

W = [sys.executable, str(ROOT / "tests" / "test_speicherordner_unterordner.py")]
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
    ("Praefix ohne Schraegstrich (nxREHA trifft nxREHA2)", MAIN,
     '        if fn and (rel == fn or rel.startswith(fn + "/")):\n            return True',
     '        if fn and (rel == fn or rel.startswith(fn)):\n            return True'),
    ("'..' im Pfad wird nicht mehr abgewiesen", MAIN,
     '    if not rel or any(t in ("", ".", "..") for t in rel.split("/")):\n        return False',
     '    if not rel:\n        return False'),
    ("Unterordner zaehlen nicht als Speicherordner", MAIN,
     "        elif (_kb_configured_root_for(f, configured) not in (None, _kb_norm_rel(f))",
     "        elif (False"),
    ("Unterordner einer Freigabe wird /wissen-Ziel", MAIN,
     "              and _kb_safe_within_data(f) is not None):\n            out.append(f)",
     "              ):\n            out.append(f)"),
    ("Freigabe-Wurzel normalisiert verglichen (wird /wissen-Ziel)", MAIN,
     "        if f in configured:\n            out.append(f)",
     "        if _kb_norm_rel(f) in {_kb_norm_rel(c) for c in configured}:\n            out.append(f)"),
    ("Keine Entdopplung Wurzel/Unterordner", MAIN,
     "    allowed = {f for f in allowed\n"
     "               if not any(a != f and _wissen_unter(f, [a]) for a in allowed)}\n", ""),
    ("Schreibpruefung wieder ueber die Wurzel", MAIN,
     "    if not _wissen_unter(rel, _wissen_allowed_folders(user, _editable_groups_for(user))):",
     "    if root_rel not in _wissen_allowed_folders(user, _editable_groups_for(user)):"),
    ("Upload wieder ueber die Wurzel", MAIN,
     "    if not _wissen_unter(target_rel, _wissen_allowed_folders(user, sel_groups)):",
     "    if root_rel not in _wissen_allowed_folders(user, sel_groups):"),
    ("/wissen-Umbenennen ohne Speicherordner-Sperre", MAIN,
     "    anker = _wissen_anker_im_weg(rel)\n", "    anker = None\n"),
    ("/wissen-Verschieben ohne Speicherordner-Sperre", MAIN,
     "    anker = _wissen_anker_im_weg(src)\n", "    anker = None\n"),
    ("Sperre nur fuer den Anker selbst, nicht fuer seine Eltern", MAIN,
     "            if fn and _wissen_unter(fn, [rel]):\n                return fn",
     "            if fn and fn == rel:\n                return fn"),
    ("Unterordner-Pruefung ohne Aufloesung (Symlink nach draussen kommt durch)", MAIN,
     "            ziel.relative_to(basis)\n", ""),
    ("Unterordner-Pruefung laesst '..' innerhalb der Wurzel durch", MAIN,
     '    if any(t in ("", ".", "..") for t in rel.split("/")):\n        return None\n    root = _kb_configured_root_for(rel)',
     '    root = _kb_configured_root_for(rel)'),
    ("Wurzel selbst gilt als Unterordner", MAIN,
     "    if not rel or root is None or root == rel:\n        return None",
     "    if not rel or root is None:\n        return None"),
    ("Nicht vorhandener Ordner wird angenommen", MAIN,
     "        return rel if ziel.is_dir() else None", "        return rel"),
    ("Zuweisungs-Endpunkt nimmt keine Unterordner", MAIN,
     "_bounded_call, lambda: _kb_unterordner_rel(path_arg), 10, None)",
     "_bounded_call, lambda: None, 10, None)"),
    ("Gruppen-PATCH weist Unterordner wieder ab", MAIN,
     "                     if not isinstance(f, str) or _kb_unterordner_rel(f) is None],",
     "                     if True],"),
    # ── Oberflaeche ──
    ("Kein Etikett-Knopf am Unterordner", KJS,
     "${addSub}${share}${gruppen}<button", "${addSub}${share}<button", W_UI),
    ("Wurzel: Bleistift oeffnet wieder den Gruppen-Dialog", KJS,
     'data-kb-aktion="renameFolder" data-kb-pfad="${sp}">${JarvisIcons.pencil()}',
     'data-kb-aktion="editFolder" data-kb-pfad="${sp}">${JarvisIcons.pencil()}', W_UI),
    ("Wurzel: kein Etikett", KJS,
     "            ? `${stift}${addSub}${share}${wurzelGruppen}${wurzelSchieben}<button",
     "            ? `${stift}${addSub}${share}${wurzelSchieben}<button", W_UI),
    ("Wurzel ausserhalb data/rag bekommt doch einen Bleistift", KJS,
     "        const stift = umbenennbar\n", "        const stift = true\n", W_UI),
    ("renameFolder nicht gestoppt (Klick klappt den Ordner mit)", KJS,
     "    'renameFolder', 'renameSubfolder',", "    'renameSubfolder',", W_UI),
    ("renameFolder schickt den alten Namen", KJS,
     "                body: JSON.stringify({ path: folder, new_name: name })",
     "                body: JSON.stringify({ path: folder, new_name: cur })", W_UI2),
    ("Gruppen-Dialog hat wieder ein Namensfeld", KJS,
     "                <div class=\"modal-body\" style=\"overflow-y:auto;\">\n                    <label class=\"kb-form-label\" style=\"display:block;margin:16px 0 4px;\">${istFreigabe",
     "                <div class=\"modal-body\" style=\"overflow-y:auto;\">\n                    <input id=\"kbfld-name\">\n                    <label class=\"kb-form-label\" style=\"display:block;margin:16px 0 4px;\">${istFreigabe", W_UI2),
    ("Gruppen-Editor zeigt wieder nur Wurzelordner", KJS,
     "        const extra = (g.folders || []).filter(f => !wurzeln.has(ohneSlash(f)));",
     "        const extra = [];", W_UI2),
]

fehlt = {rel for _, rel, *_ in PROBEN} - set(DATEIEN)
if fehlt:
    print(f"ABBRUCH: nicht gesicherte Dateien in den Proben: {sorted(fehlt)}")
    sys.exit(2)

sichern()
atexit.register(aufraeumen)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

print("Basislauf")
for cmd, name in ((W, "test_speicherordner_unterordner"), (W_UI, "test_csp_h4_wissen_klick"),
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
