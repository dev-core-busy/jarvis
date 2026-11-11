#!/usr/bin/env python3
"""Gegenprobe zu tests/test_schema_graph_quellen.py: beisst der Waechter?

Je Probe wird ``backend/`` samt Waechter in ein Wegwerf-Verzeichnis kopiert und
dort EINE Zusage zurueckgedreht – im Baum wird nichts gepatcht. Die erste
Probe ist der Stand VOR der Behebung (``schema_graph_store.py`` aus dem Commit
``685c19d6``, mit dem der Fehler auf ECHT lief).

Aufruf:  python3 tests/gegen_schema_graph_quellen.py
Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = "tests/test_schema_graph_quellen.py"
STORE = "backend/schema_graph_store.py"
INDEX = "backend/schema_graph_index.py"
ALTSTAND = "685c19d6"

# (Name, Datei, [(alt, neu), ...]) – alt=None heisst: ganze Datei aus ALTSTAND
PROBEN = [
    ("Altstand: Schluessel global (Fehler auf ECHT)", STORE, None),
    ("Dublette ueber Schemagrenzen",
     STORE, [("            if (q, schl) in auf.genau:", "            if any(k[1] == schl for k in auf.genau):"),
             ("                oid = auf.genau[(q, schl)]",
              "                oid = next(v for k, v in auf.genau.items() if k[1] == schl)")]),
    ("ALTER ohne Schema-Quelle", STORE, [("        oid = auf.finde(name, quelle=q)", "        oid = auf.finde(name)")]),
    ("Spaltenkommentar ohne Schema-Quelle",
     STORE, [("            oid = auf.finde(tab, quelle=q) if tab else None", "            oid = auf.finde(tab) if tab else None")]),
    ("Tabellenkommentar ohne Schema-Quelle",
     STORE, [("            oid = auf.finde(ziel_t, quelle=q)", "            oid = auf.finde(ziel_t)")]),
    ("FK ohne Schema-Quelle",
     STORE, [('        zid = auf.finde(ziel_t, auf.schema_von.get(oid, ""), auf.quelle_von.get(oid, ""))',
              '        zid = auf.finde(ziel_t, auf.schema_von.get(oid, ""))')]),
    ("Sicht-Kante ohne Schema-Quelle",
     STORE, [('            zid = auf.finde(t, auf.schema_von.get(oid, ""), auf.quelle_von.get(oid, ""))',
              '            zid = auf.finde(t, auf.schema_von.get(oid, ""))')]),
    ("Ableitung 'xxx_id' ueber Schemagrenzen",
     STORE, [('            for zid in auf.namensgleiche(kand, auf.quelle_von.get(oid, "")):',
              "            for zid in [z for k, l in auf.nach_name.items() if k[1] == kand for z in l]:")]),
    ("Ableitung 'gleicher PK' ueber Schemagrenzen",
     STORE, [('            nach_pk[(auf.quelle_von.get(oid, ""), pk.lower())].append(oid)',
              '            nach_pk[("", pk.lower())].append(oid)'),
             ('        ziele = nach_pk.get((auf.quelle_von.get(oid, ""), name_l))',
              '        ziele = nach_pk.get(("", name_l))')]),
    ("Eindeutigkeit wieder global",
     STORE, [("pk TEXT, bereich INTEGER, quelle TEXT, UNIQUE(quelle, schluessel));",
              "pk TEXT, bereich INTEGER, quelle TEXT, UNIQUE(schluessel));")]),
    ("'ohne Struktur' zaehlt uebersprungene Objekte",
     INDEX, [('                n = (int(s.get("anweisungen") or 0) - int(s.get("objekt_uebersprungen") or 0)\n'
              '                     - int(s.get("verzeichnis") or 0))',
              '                n = int(s.get("anweisungen") or 0)')]),
]


def baum(ziel: Path) -> None:
    shutil.copytree(ROOT / "backend", ziel / "backend",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    (ziel / "tests").mkdir()
    shutil.copy2(ROOT / WAECHTER, ziel / WAECHTER)


def lauf(wurzel: Path) -> tuple[int, int]:
    r = subprocess.run([sys.executable, "-W", "ignore", str(wurzel / WAECHTER)], capture_output=True, text=True,
                       timeout=300, cwd=str(wurzel), env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"})
    m = re.search(r"Bilanz: (\d+) OK, (\d+) FAIL", r.stdout)
    return (int(m.group(2)) if m and r.returncode != 2 else -1), r.returncode


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def main() -> int:
    vorher = {f: md5(ROOT / f) for f in (STORE, INDEX, WAECHTER)}
    alt = subprocess.run(["git", "show", f"{ALTSTAND}:{STORE}"], capture_output=True, text=True, cwd=str(ROOT))
    if alt.returncode != 0 or "class _Aufloeser" not in alt.stdout:
        print(f"ABBRUCH: Altstand {ALTSTAND}:{STORE} nicht lesbar")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="gegen_sg_quellen_"))
    try:
        basis = tmp / "basis"
        baum(basis)
        f, rc = lauf(basis)
        if f != 0:
            print(f"ABBRUCH: Basislauf nicht gruen (FAIL={f}, rc={rc})")
            return 2
        print("Basislauf gruen.\n")
        beissen = 0
        for i, (name, datei, paare) in enumerate(PROBEN):
            w = tmp / f"p{i}"
            baum(w)
            if paare is None:
                (w / datei).write_text(alt.stdout, encoding="utf-8")
            else:
                t = (w / datei).read_text(encoding="utf-8")
                fehlt = [a for a, _ in paare if t.count(a) != 1]
                if fehlt:
                    print(f"  ???  {name:52} Anker nicht genau einmal: {fehlt[0][:60]!r}")
                    continue
                for a, n in paare:
                    t = t.replace(a, n)
                (w / datei).write_text(t, encoding="utf-8")
            f, rc = lauf(w)
            if f > 0:
                beissen += 1
                print(f"  BISS {name:52} {f} FAIL")
            elif f < 0:
                print(f"  ABBR {name:52} rc={rc} (kein Biss: Lauf ohne Bilanz)")
            else:
                print(f"  ZAHN {name:52} 0 FAIL – beisst NICHT")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if {f: md5(ROOT / f) for f in vorher} != vorher:
        print("ABBRUCH: eine Datei im Baum hat sich waehrend des Laufs geaendert")
        return 2
    print(f"\n{beissen}/{len(PROBEN)} Proben beissen (im Baum nichts veraendert)")
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
