#!/usr/bin/env python3
"""Live-Probe: SQL-Assistent (Schema-Graph) mit dem ECHTEN Modell.

Der Waechter ``test_schema_graph.py`` prueft die Kette mit einer Attrappe –
er belegt die Verdrahtung, nicht, dass ein echtes Modell damit gutes SQL
schreibt. Diese Probe baut aus einem synthetischen ERP-Schema (kryptische
Namen, deutsche Kommentare, ein Verbindungsglied ohne passenden Namen) einen
Graphen in einem Wegwerf-Ordner und stellt jede Frage ZWEIMAL: eine
Modellantwort ist erst nach Wiederholung eine Messung (Register).

Erwartet je Frage: Pruefung bestanden, und die Abfrage benutzt die Tabellen,
ohne die die Frage nicht zu beantworten ist (Positivliste je Frage).

Auf dem Server (Modellschluessel im Dienst verpackt, BSI M5):
    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_schema_graph.py
Exit 0 = alle Laeufe bestanden, 1 = Befund, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import asyncio
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

SCHEMA = """
CREATE TABLE stm.kdst (kdnr integer PRIMARY KEY, kdname varchar(120) NOT NULL, lnd char(2), erfdat date);
COMMENT ON TABLE stm.kdst IS 'Kundenstamm (Debitoren)';
COMMENT ON COLUMN stm.kdst.lnd IS 'Laenderschluessel ISO';
CREATE TABLE stm.lnd (lnd char(2) PRIMARY KEY, lndbez varchar(80));
COMMENT ON TABLE stm.lnd IS 'Laender';
CREATE TABLE stm.matst (matnr varchar(18) PRIMARY KEY, matbez varchar(120), mgrp varchar(10), basme varchar(3));
COMMENT ON TABLE stm.matst IS 'Materialstamm / Artikel';
CREATE TABLE stm.lgort (lgnr integer PRIMARY KEY, lgbez varchar(60), werk varchar(4));
COMMENT ON TABLE stm.lgort IS 'Lagerorte';
CREATE TABLE vk.vbkopf (vbeln bigint PRIMARY KEY, kdnr integer NOT NULL, audat date NOT NULL, waerk char(3), lgnr integer);
COMMENT ON TABLE vk.vbkopf IS 'Verkaufsbeleg Kopf (Kundenauftrag)';
COMMENT ON COLUMN vk.vbkopf.audat IS 'Auftragsdatum';
CREATE TABLE vk.vbpos (vbeln bigint, posnr integer, matnr varchar(18), menge numeric(13,3), netwr numeric(15,2),
  PRIMARY KEY (vbeln, posnr));
COMMENT ON TABLE vk.vbpos IS 'Verkaufsbeleg Position';
COMMENT ON COLUMN vk.vbpos.netwr IS 'Nettowert der Position';
CREATE TABLE vs.lfkopf (lfnr bigint PRIMARY KEY, vbeln bigint, wadat_ist date, lgnr integer);
COMMENT ON TABLE vs.lfkopf IS 'Lieferung Kopf';
COMMENT ON COLUMN vs.lfkopf.wadat_ist IS 'Tatsaechliches Warenausgangsdatum';
ALTER TABLE vk.vbkopf ADD CONSTRAINT fk1 FOREIGN KEY (kdnr) REFERENCES stm.kdst(kdnr);
ALTER TABLE stm.kdst ADD CONSTRAINT fk2 FOREIGN KEY (lnd) REFERENCES stm.lnd(lnd);
ALTER TABLE vk.vbpos ADD CONSTRAINT fk3 FOREIGN KEY (vbeln) REFERENCES vk.vbkopf(vbeln);
ALTER TABLE vk.vbpos ADD CONSTRAINT fk4 FOREIGN KEY (matnr) REFERENCES stm.matst(matnr);
ALTER TABLE vs.lfkopf ADD CONSTRAINT fk5 FOREIGN KEY (vbeln) REFERENCES vk.vbkopf(vbeln);
ALTER TABLE vs.lfkopf ADD CONSTRAINT fk6 FOREIGN KEY (lgnr) REFERENCES stm.lgort(lgnr);
CREATE TABLE fi.bkpf (belnr bigint PRIMARY KEY, bldat date, blart char(2));
COMMENT ON TABLE fi.bkpf IS 'Buchhaltungsbeleg Kopf';
CREATE TABLE hr.pa0001 (pernr integer PRIMARY KEY, ename varchar(80), orgeh integer);
COMMENT ON TABLE hr.pa0001 IS 'Personal: organisatorische Zuordnung';
"""

FRAGEN = [
    ("Wie hoch war der Nettoumsatz je Land im Jahr 2025?", {"vk.vbpos", "vk.vbkopf", "stm.kdst"}),
    ("Welche Artikel wurden noch nie verkauft?", {"stm.matst", "vk.vbpos"}),
    ("Wie viele Tage liegen im Durchschnitt zwischen Auftragsdatum und Warenausgang, je Lagerort?",
     {"vk.vbkopf", "vs.lfkopf", "stm.lgort"}),
]
WIEDERHOLUNGEN = 2


def main() -> int:
    try:
        from backend import schema_graph_index as I
        from backend import schema_graph_rag as R
        from backend import schema_graph_store as S
    except Exception as e:  # noqa: BLE001
        print(f"ABBRUCH (Exit 2): Module nicht ladbar: {e}")
        return 2
    tmp = Path(tempfile.mkdtemp(prefix="live_schema_graph_"))
    try:
        S.ORDNER = tmp / "ablage"
        (tmp / "quelle").mkdir()
        (tmp / "quelle" / "erp.sql").write_text(SCHEMA)
        st = I.lauf([str(tmp / "quelle")], prozesse=1)
        if st.get("ergebnis") != "fertig":
            print(f"ABBRUCH (Exit 2): Indexlauf {st.get('ergebnis')}: {st.get('fehler')}")
            return 2
        print(f"Graph: {st['graph']}")

        async def alle():
            out = []
            for frage, muss in FRAGEN:
                for n in range(WIEDERHOLUNGEN):
                    t0 = time.time()
                    erg = await R.sql_erzeugen(frage, dialekt="postgresql")
                    out.append((frage, muss, n + 1, erg, time.time() - t0))
            return out

        laeufe = asyncio.run(alle())
        fail = 0
        # Positivkontrolle: mindestens ein Lauf hat das Modell ueberhaupt erreicht
        if all(e.get("fehler") and not e.get("verlauf") for _f, _m, _n, e, _d in laeufe):
            print("ABBRUCH (Exit 2): kein Lauf erreichte das Modell: " + laeufe[0][3].get("fehler", ""))
            return 2
        for frage, muss, n, erg, dauer in laeufe:
            pr = erg.get("pruefung") or {}
            sql = erg.get("sql") or ""
            benutzt = set(pr.get("tabellen") or [])
            fehlt = muss - benutzt
            ok = bool(pr.get("ok")) and not fehlt
            fail += 0 if ok else 1
            print(f"\n{'OK  ' if ok else 'FAIL'} [{n}/{WIEDERHOLUNGEN}] {frage}  ({dauer:.1f} s, "
                  f"{erg.get('runden')} Runden, Begriffe aus {erg.get('begriffe_quelle')})")
            if erg.get("fehler"):
                print("  Fehler: " + erg["fehler"])
            if pr.get("fehler"):
                print("  Pruefung: " + "; ".join(pr["fehler"]))
            for v in erg.get("verlauf") or []:
                if v.get("befunde"):
                    print(f"  Runde {v['runde']} Befunde: " + "; ".join(v["befunde"]))
            if fehlt:
                print("  fehlende Pflichttabellen: " + ", ".join(sorted(fehlt)))
            print("  Kontext: " + ", ".join(erg.get("tabellen_kontext") or []))
            print("  " + re.sub(r"\s+", " ", sql)[:600])
        print(f"\nBilanz: {len(laeufe) - fail} OK, {fail} FAIL")
        return 1 if fail else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
