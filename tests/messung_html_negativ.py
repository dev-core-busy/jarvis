#!/usr/bin/env python3
"""MESSUNG (kein Waechter): wo wuerde ein KUENFTIGER HTML-Kommentar beissen?

``messung_html_kommentar.py`` hat am 2026-10-03 fuer 14 Waechter gezeigt, dass
heute keine Pruefung am Inhalt eines HTML-Kommentars haengt. Das ist eine
Aussage ueber HEUTE. Die Frage danach: welche Stellen wuerden umkippen, sobald
jemand einen Kommentar schreibt, der das Suchmuster enthaelt?

⚠ Die Zahl ist ein SUPERSET und keine Mangelliste – die Faerbung ist bewusst
grosszuegig (siehe Fixpunkt unten), und ein gemeldeter Treffer kann an einer
HTML-Zeichenkette im Test selbst haengen statt an einer Datei. Gelesen gehoert
jede Stelle, bevor sie geaendert wird; eine Haertung auf eine Eigenschaft, die
es nicht gibt, ist schlechter als keine.

Gefaehrlich ist dabei nur eine Richtung. Eine NEGATIVE Pruefung
(``"x" not in HTML``) wird durch einen Kommentar, der ``x`` nennt, FALSCH ROT –
genau der Vorfall vom 2026-10-02 in test_download_key.py. Eine positive
Pruefung wird durch einen Kommentar hoechstens trivial gruen, was schwaecher
aber nicht falsch ist; sie wird hier getrennt gezaehlt.

Gezaehlt wird je Testdatei die Zahl negativer Zugehoerigkeitspruefungen, deren
Vergleichspartner aus einem HTML-Dateiinhalt stammt – auch wenn der Inhalt
inline gelesen oder in einer Schleife durchlaufen wird.
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def html_quellen(baum):
    """Namen, die (irgendwie) einen HTML-Dateiinhalt halten.

    Erfasst drei Gestalten, weil genau die unterschiedlichen Schreibweisen
    die erste Messung blind gemacht haben:
      - ``V = (... / "x.html").read_text()``        (Zuweisung)
      - ``for v in ...glob("*.html") ...``          (Schleife ueber Seiten)
      - ``V = (ROOT / datei).read_text()``          (Schleifenvariable als Pfad)
    """
    namen = set()
    # Saatkorn: Schleifenvariablen ueber HTML-Pfade und direkte Lesezugriffe.
    for n in ast.walk(baum):
        if isinstance(n, ast.For) and isinstance(n.target, ast.Name):
            if ".html" in ast.unparse(n.iter):
                namen.add(n.target.id)
        if isinstance(n, ast.Assign):
            text = ast.unparse(n.value)
            if "read_text" in text and ".html" in text:
                for z in n.targets:
                    if isinstance(z, ast.Name):
                        namen.add(z.id)
    # ⚠ FIXPUNKT, und er ist der Kern: die erste Fassung dieser Messung hat
    # `h = p.read_text(...)` NICHT erkannt (der Pfad steckt in der
    # Schleifenvariablen `p`, nicht im Literal) und meldete fuer
    # test_system_packages 0 statt 1. Eine Messung, die ihre eigene
    # Nachweisgrenze nicht kennt, liefert eine Entwarnung statt eines Werts.
    # Deshalb wird weitergefaerbt, bis nichts mehr dazukommt.
    while True:
        neu = set()
        for n in ast.walk(baum):
            if not isinstance(n, ast.Assign):
                continue
            bezug = {k.id for k in ast.walk(n.value) if isinstance(k, ast.Name)}
            if not (bezug & namen):
                continue
            for z in n.targets:
                if isinstance(z, ast.Name) and z.id not in namen:
                    neu.add(z.id)
        if not neu:
            return namen
        namen |= neu


def zaehlen(pfad):
    baum = ast.parse(pfad.read_text(encoding="utf-8"))
    namen = html_quellen(baum)
    neg, pos = [], []
    for n in ast.walk(baum):
        if not isinstance(n, ast.Compare) or len(n.ops) != 1:
            continue
        if not isinstance(n.ops[0], (ast.In, ast.NotIn)):
            continue
        partner = ast.unparse(n.comparators[0])
        trifft = (any(w in {k.id for k in ast.walk(n.comparators[0])
                            if isinstance(k, ast.Name)} for w in namen)
                  or ".html" in partner)
        if not trifft:
            continue
        lit = n.left.value if isinstance(n.left, ast.Constant) else ast.unparse(n.left)
        (neg if isinstance(n.ops[0], ast.NotIn) else pos).append((n.lineno, lit))
    return neg, pos, namen


def main():
    print("%-30s %5s %5s  %s" % ("Datei", "NEG", "POS", "negative Stellen"))
    print("-" * 100)
    summe = 0
    for name in sys.argv[1:]:
        p = ROOT / "tests" / name
        try:
            neg, pos, _ = zaehlen(p)
        except SyntaxError as e:
            print("%-30s  nicht parsebar: %s" % (name, e))
            continue
        stellen = ", ".join("Z%d:%s" % (z, str(l)[:28]) for z, l in neg[:4])
        if len(neg) > 4:
            stellen += " ..."
        print("%-30s %5d %5d  %s" % (name.replace(".py", ""), len(neg),
                                     len(pos), stellen))
        summe += len(neg)
    print("-" * 100)
    print("Negative Pruefungen gegen rohes HTML insgesamt: %d" % summe)


if __name__ == "__main__":
    main()
