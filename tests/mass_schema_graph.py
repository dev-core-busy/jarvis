#!/usr/bin/env python3
"""Massstabsprobe Schema-Graph: traegt Ableitung und Suche bei ~100.000 Tabellen?

Der Parser-Durchsatz ist einzeln gemessen; offen ist, ob die ABLEITUNG
(Aufloesen, Bereiche, Volltext) und die SUCHE je Frage (Volltext, Steiner-
Naeherung, Kontext) bei einem Bestand dieser Groesse in vertretbarer Zeit
und mit vertretbarem Speicher laufen. Erzeugt synthetisches DDL (zufaellige
Fremdschluessel, eine Hub-Tabelle "mandant", auf die alles verweist), misst
Lauf, Wiederholungslauf, Speicherspitze und Suchlatenz.

Schreibt NUR unter ``--ziel`` (Vorgabe: ein neuer Ordner unter /var/tmp, NICHT
/tmp – das ist oft ein tmpfs im Arbeitsspeicher) und raeumt am Ende ab.

    python3 tests/mass_schema_graph.py [--tabellen 100000] [--prozesse 4] [--ziel DIR]
Exit 0 = gelaufen (Messwerte stehen in der Ausgabe), 2 = konnte nicht laufen.
"""
from __future__ import annotations

import argparse
import json
import random
import resource
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

WOERTER = ["kunde", "auftrag", "artikel", "lager", "rechnung", "konto", "buchung", "lieferant",
           "bestellung", "position", "preis", "waehrung", "werk", "material", "charge", "kosten",
           "stelle", "projekt", "vertrag", "anlage"]


def erzeugen(q: Path, n: int, je_datei: int = 5000) -> int:
    rnd = random.Random(7)
    namen = []
    for i in range(n):
        a, b = rnd.choice(WOERTER), rnd.choice(WOERTER)
        namen.append(f"s{i % 50}.{a}_{b}_{i}")
    with open(q / "mandant.sql", "w") as f:
        f.write("CREATE TABLE s0.mandant (id int PRIMARY KEY, name varchar(50));\n")
    for d in range(0, n, je_datei):
        with open(q / f"teil_{d // je_datei:03d}.sql", "w") as f:
            for i in range(d, min(n, d + je_datei)):
                t = namen[i]
                cols = ",\n".join(f"  {rnd.choice(WOERTER)}_{c} varchar(40)" for c in range(28))
                f.write(f"CREATE TABLE {t} (\n  id bigint PRIMARY KEY,\n  mandant_id int REFERENCES "
                        f"s0.mandant(id),\n  ref_id bigint,\n{cols}\n);\n")
                teile = t.split(".")[1].split("_")
                f.write(f"COMMENT ON TABLE {t} IS '{teile[0].capitalize()} zu {teile[1]}';\n")
                # Datenblock wie in einem Dump (wird ueberlesen)
                f.write(f"INSERT INTO {t} VALUES " + ",".join(f"({k},'w''{k}')" for k in range(50)) + ";\n")
    with open(q / "fk.sql", "w") as f:
        for t in namen:
            f.write(f"ALTER TABLE {t} ADD FOREIGN KEY (ref_id) REFERENCES {rnd.choice(namen)}(id);\n")
    return sum(p.stat().st_size for p in q.iterdir())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tabellen", type=int, default=100000)
    ap.add_argument("--prozesse", type=int, default=4)
    ap.add_argument("--ziel", default="")
    a = ap.parse_args()
    try:
        from backend import schema_graph_index as I
        from backend import schema_graph_rag as R
        from backend import schema_graph_store as S
    except Exception as e:  # noqa: BLE001
        print(f"ABBRUCH (Exit 2): {e}")
        return 2
    basis = Path(a.ziel) if a.ziel else Path(tempfile.mkdtemp(prefix="mass_schema_graph_", dir="/var/tmp"))
    basis.mkdir(parents=True, exist_ok=True)
    try:
        q = basis / "quelle"
        q.mkdir(exist_ok=True)
        S.ORDNER = basis / "ablage"
        t = time.time()
        groesse = erzeugen(q, a.tabellen)
        print(f"Erzeugt: {a.tabellen} Tabellen, {groesse / 1e6:.0f} MB in {time.time() - t:.0f} s")
        t = time.time()
        st = I.lauf([str(q)], prozesse=a.prozesse)
        print(f"Lauf: {time.time() - t:.1f} s, {st['ergebnis']}, Fehler: {st['fehler'][:2]}")
        print("Graph: " + json.dumps(st.get("graph")))
        print(f"Speicherspitze Elternprozess: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024} MB")
        print(f"roh.sqlite {S.roh_pfad().stat().st_size / 1e6:.0f} MB, "
              f"graph.sqlite {S.graph_pfad().stat().st_size / 1e6:.0f} MB")
        g = S.graph_lesen()
        for begr in (["kunde", "rechnung"], ["lieferant", "vertrag", "projekt"],
                     ["charge", "material", "werk", "lager"]):
            for kalt in ("kalt", "warm"):
                t0 = time.time()
                tr = R.suche(g, begr)
                t1 = time.time()
                w = R.auswahl(g, tr, 12)
                t2 = time.time()
                k, _ = R.kontext_bauen(g, w["ids"], begr, 40)
                t3 = time.time()
                print(f"{','.join(begr):32s} {kalt}: Suche {1000 * (t1 - t0):5.0f} ms, Auswahl "
                      f"{1000 * (t2 - t1):5.0f} ms (Glieder {len(w['verbinder'])}, ohne Pfad "
                      f"{len(w['unverbunden'])}), Kontext {1000 * (t3 - t2):4.0f} ms, {len(k)} Zeichen")
        g.close()
        t = time.time()
        st = I.lauf([str(q)], prozesse=a.prozesse)
        print(f"Wiederholungslauf: {time.time() - t:.1f} s, {st['ergebnis']}")
        (q / "teil_000.sql").write_text((q / "teil_000.sql").read_text() + "\nCREATE TABLE s1.neu (id int);\n")
        t = time.time()
        st = I.lauf([str(q)], prozesse=a.prozesse)
        print(f"Eine Datei geaendert: {time.time() - t:.1f} s, {st['ergebnis']}, {st['dateien_neu']} neu")
        return 0
    finally:
        if not a.ziel:
            shutil.rmtree(basis, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
