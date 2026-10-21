#!/usr/bin/env python3
"""Gegenproben zur automatischen Gruppenzuordnung ueber Speicherordner.

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob
``tests/test_auto_gruppe.py`` das meldet. Eine Probe, die nicht beisst, ist ein
Testmangel – oder die Zusage existiert gar nicht (dann gehoert die Probe
gestrichen, nicht der Waechter geschaerft).

Wie in den uebrigen Harnessen: jede angefasste Datei steht geprueft in der
Sicherung (Exit 2), eine Laufmarke nimmt den Rueckstand eines abgeschossenen
Laufs beim naechsten Start zurueck, ein gruener Basislauf ist Bedingung, und
gelaufen wird ohne Bytecode (Register: sonst laedt ein spaeterer Lauf eine
Sabotage aus einer .pyc bei byte-gleicher Quelle).
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
ABL = Path.home() / ".gegen-auto-gruppe"
MARKE = ABL / "LAUF"

KG = "backend/knowledge_groups.py"
KN = "backend/tools/knowledge.py"
MAIN = "backend/main.py"
TW = "tests/test_auto_gruppe.py"
KJS = "frontend/js/knowledge.js"
DATEIEN = [KG, KN, MAIN, TW, KJS]

W = [sys.executable, str(ROOT / "tests" / "test_auto_gruppe.py")]
W_UI = ["node", str(ROOT / "tests" / "test_auto_gruppe_ui.js")]
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
        # Ein Abbruch ohne Bilanz ist KEIN Biss (Register) – er wird als stumm
        # gemeldet, damit ein kaputter Pruefstand nicht wie eine Messung aussieht.
        return False, f"ABGEBROCHEN rc={rc} (keine Bilanz)"
    fails = sum(1 for z in aus.splitlines() if "✗" in z or "❌" in z)
    return (rc == 1 and fails > 0), f"{b[-1].strip()}"


PROBEN = [
    # (Name, Datei, alt, neu[, Waechter]) – ohne Waechter: der Python-Waechter
    ("Markierung wird ignoriert (ausgetragene Datei kommt zurueck)", KG,
     "            if key in gesehen:\n                continue\n", ""),
    ("Praefix ohne Schraegstrich (share_2 trifft share_20)", KG,
     'gids = [gid for rel, gid in ordner if key.startswith(rel + "/")]',
     'gids = [gid for rel, gid in ordner if key.startswith(rel)]'),
    ("Vorhandene Zuordnung wird ueberschrieben", KG,
     "            if not assignments.get(key):\n                assignments[key]",
     "            if True:\n                assignments[key]"),
    ("Auch Dateien ausserhalb jedes Speicherordners werden markiert", KG,
     "            if not gids:\n                continue\n            gesehen.add(key)",
     "            gesehen.add(key)\n            if not gids:\n                continue"),
    ("Gruppen-Reihenfolge ignoriert", KG,
     'for g in sorted(data.get("groups", []), key=lambda g: g.get("order", 0)):',
     'for g in data.get("groups", []):'),
    ("relocate_prefix laesst die Markierung stehen", KG,
     "            if gesehen_changed:\n                data[AUTO_GESEHEN] = neu_gesehen\n", ""),
    ("prune raeumt Markierungen nicht ab", KG,
     "        if gesehen_weg:\n            data[AUTO_GESEHEN] = kept_gesehen\n", ""),
    ("remove_prefix ohne Ordnergrenze (trifft 'xy')", KG,
     "        kept_gesehen = [x for x in gesehen if not _rel(x).startswith(pref)]",
     "        kept_gesehen = [x for x in gesehen if not _rel(x).startswith(pref_dir)]"),
    ("gesehen_verschieben: Loeschfall entfernt nichts", KG,
     "        rest = {x for x in gesehen if x != a}", "        rest = set(gesehen)"),
    ("Indexlauf ruft die Zuordnung nicht mehr", KN,
     "neu_zugeordnet = _kg.automatisch_zuordnen(vs.get_indexed_files())",
     "neu_zugeordnet = 0"),
    ("Endpunkt ruft die Zuordnung nicht mehr", MAIN,
     "            zugeordnet = await asyncio.to_thread(kg.automatisch_zuordnen,\n"
     "                                                 list(vs.get_indexed_files()))",
     "            zugeordnet = 0"),
    ("Endpunkt ruft sie im Event-Loop statt im Thread", MAIN,
     "            zugeordnet = await asyncio.to_thread(kg.automatisch_zuordnen,\n"
     "                                                 list(vs.get_indexed_files()))",
     "            zugeordnet = kg.automatisch_zuordnen(list(vs.get_indexed_files()))"),
    ("Datei loeschen vergisst die Markierung nicht", KN,
     "        kg.gesehen_verschieben(file_s)    # geloescht: Markierung der Automatik weg\n", ""),
    ("Datei verschieben zieht die Markierung nicht mit", KN,
     "        kg.gesehen_verschieben(old_rel, new_rel)\n", ""),
    # Lage herstellen, die die Positivkontrolle abfangen soll: findet die
    # Funktionssuche nichts, waeren alle Regeln in Abschnitt 9 trivial falsch/wahr.
    ("Waechter findet _vector_index_lauf nicht mehr (Positivkontrolle muss melden)", TW,
     'lauf = funktion("backend/tools/knowledge.py", "_vector_index_lauf")',
     'lauf = funktion("backend/tools/knowledge.py", "_gibt_es_nicht")'),
    # ── Oberflaeche ──
    ("Dialog vergleicht wieder roh (Freigabe ohne Haken)", KJS,
     "if ((g.folders || []).some(f => ohneSlash(f) === ohneSlash(folder))) assigned.add(g.id);",
     "if ((g.folders || []).includes(folder)) assigned.add(g.id);", W_UI),
    # Seit 2026-10-21 zeigt der Editor JEDEN zugeordneten Ordner; die frueher
    # hier sabotierte Zeile "nicht angebotene behalten" ist damit entfallen.
    # Dieselbe Zusage (Freigabe ueberlebt das Speichern) haengt jetzt an der Anzeige.
    ("Gruppen-Editor zeigt die Freigabe nicht (und verliert sie beim Speichern)", KJS,
     "        const extra = (g.folders || []).filter(f => !wurzeln.has(ohneSlash(f)));",
     "        const extra = [];", W_UI),
    ("Kein Knopf an der Freigabe-Zeile", KJS,
     """data-kb-aktion="editFolder" data-kb-pfad="${this._escHtml(m.mountpoint || '')}">""",
     """data-kb-aktion="nichts" data-kb-pfad="${this._escHtml(m.mountpoint || '')}">""", W_UI),
    ("Dialog sagt bei einer Freigabe weiter 'Speicherordner (/wissen)'", KJS,
     "        const istFreigabe = folder.startsWith('/');",
     "        const istFreigabe = false;", W_UI),
]

fehlt = {rel for _, rel, *_ in PROBEN} - set(DATEIEN)
if fehlt:
    print(f"ABBRUCH: nicht gesicherte Dateien in den Proben: {sorted(fehlt)}")
    sys.exit(2)

sichern()
atexit.register(aufraeumen)
signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))

print("Basislauf")
for cmd, name in ((W, "test_auto_gruppe"), (W_UI, "test_auto_gruppe_ui")):
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
