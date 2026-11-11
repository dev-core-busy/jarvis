#!/usr/bin/env python3
"""Gegenprobe zu tests/test_schema_graph_html.py: beisst der Waechter?

Jede Probe dreht EINE Zusage des HTML-Wegs im Parser zurueck und erwartet
mindestens einen FAIL. Im Baum wird NICHTS gepatcht: der Waechter nimmt den
Pfad eines Parsers entgegen, die sabotierte Fassung liegt in einem eigenen
Temp-Verzeichnis (Vorbild: gegen_schema_graph_dokumente.py).

Aufruf:  python3 tests/gegen_schema_graph_html.py
Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_schema_graph_html.py"
PARSER = ROOT / "backend" / "schema_graph_parser.py"

# (Name, [(alt, neu), ...]) – mehrere Paare, wo eine Zusage zweifach gehalten wird
PROBEN = [
    ("Fassung nicht hochgezaehlt", [("FASSUNG = 7", "FASSUNG = 6")]),
    ("HTML geht in den SQL-Parser", [("    if str(pfad).lower().endswith(HTML_ENDUNGEN):", "    if False:")]),
    ("Diagramme/Skripte nicht entfernt",
     [('        text = _HTML_WEG.sub(" ", f.read())', "        text = f.read()")]),
    ("Name aus der Ueberschrift statt dem Anker",
     [('        name = bezeichner(html.unescape(k.group("anker"))) or bezeichner(html.unescape(k.group("titel")))',
       '        name = bezeichner(html.unescape(k.group("titel")))')]),
    ("Tabellenbeschreibung nicht gelesen", [("    bm = _HTML_BESCHR.match(rumpf)", "    bm = None")]),
    ("Typ mit COLLATE/DEFAULT",
     [('            typ = (definition[:te.start()] if te else definition).strip()[:80]',
       '            typ = definition.strip()[:80]')]),
    ("Pflichtfeld nicht erkannt",
     [('                            "null": "*" not in _html_text(zellen[0]),', '                            "null": True,')]),
    ("<br> nicht als Umbruch", [('    s = re.sub(r"<br\\s*/?>", "\\n", roh or "", flags=re.I)', '    s = roh or ""')]),
    ("Entities nicht aufgeloest",
     [('    s = html.unescape(re.sub(r"<[^>]*>", "", s))', '    s = re.sub(r"<[^>]*>", "", s)')]),
    ("PK aus jedem Index",
     [('            if im and im.group("art").lower().startswith("primary"):', "            if im:")]),
    ("Index/Kante aus der LETZTEN Zelle (der erste Fehler dieses Wegs)",
     [('            im = _HTML_INDEX.match(_html_text(zellen[2])', '            im = _HTML_INDEX.match(_html_text(zellen[-1])'),
      ('            fm = _HTML_FK.match(_html_text(zellen[2])', '            fm = _HTML_FK.match(_html_text(zellen[-1])')]),
    ("Kante ohne Zielspalte verloren",
     [(r'(?P<ziel>[^()]+?)\s*(?:\((?P<nach>[^()]*)\))?\s*$")', r'(?P<ziel>[^()]+?)\s*\((?P<nach>[^()]*)\)\s*$")')]),
    # Zweifach gehalten: Abschnitt UND Pfeil (rueckwaertig steht ein anderer
    # Pfeil) – die Probe trifft beide Stellen in einem Zug
    ("Rueckwaertige Kanten mitgelesen",
     [('        elif abschnitt == "foreign key":', '        elif abschnitt in ("foreign key", "referring foreign key"):'),
      (r'(?P<von>.+?)\s*\u2197\s*', r'(?P<von>.+?)\s*[\u2197\u2199]\s*')]),
    ("Fremde HTML-Seite still ohne Hinweis",
     [('        stat["anweisungen"] += 1\n        stat["unverstanden"] += 1\n        return []',
       "        return []")]),
]


def lauf(parser: Path) -> tuple[int, int]:
    r = subprocess.run([sys.executable, "-W", "ignore", str(WAECHTER), str(parser)], capture_output=True,
                       text=True, timeout=300, cwd=str(ROOT), env={"PYTHONDONTWRITEBYTECODE": "1", "PATH": "/usr/bin:/bin"})
    m = re.search(r"Bilanz: (\d+) OK, (\d+) FAIL", r.stdout)
    return (int(m.group(2)) if m and r.returncode != 2 else -1), r.returncode


def main() -> int:
    quelle = PARSER.read_text(encoding="utf-8")
    tmp = Path(tempfile.mkdtemp(prefix="gegen_sg_html_"))
    try:
        basis = tmp / "schema_graph_parser.py"
        basis.write_text(quelle, encoding="utf-8")
        f, rc = lauf(basis)
        if f != 0:
            print(f"ABBRUCH: Basislauf nicht gruen (FAIL={f}, rc={rc})")
            return 2
        print("Basislauf gruen.\n")
        beissen = 0
        for i, (name, paare) in enumerate(PROBEN):
            t = quelle
            ok = True
            for alt, neu in paare:
                if t.count(alt) != 1:
                    print(f"  ???  {name:60} Anker {t.count(alt)}x gefunden")
                    ok = False
                    break
                t = t.replace(alt, neu)
            if not ok:
                continue
            ziel = tmp / f"p{i}" / "schema_graph_parser.py"
            ziel.parent.mkdir()
            ziel.write_text(t, encoding="utf-8")
            f, rc = lauf(ziel)
            if f > 0:
                beissen += 1
                print(f"  BISS {name:60} {f} FAIL")
            elif f < 0:
                print(f"  ABBR {name:60} rc={rc} (kein Biss: Lauf ohne Bilanz)")
            else:
                print(f"  ZAHN {name:60} 0 FAIL – beisst NICHT")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    if PARSER.read_text(encoding="utf-8") != quelle:
        print("ABBRUCH: der Parser im Baum hat sich waehrend des Laufs geaendert")
        return 2
    print(f"\n{beissen}/{len(PROBEN)} Proben beissen (im Baum nichts veraendert)")
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
