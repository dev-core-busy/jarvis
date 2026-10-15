#!/usr/bin/env python3
"""MESSUNG (kein Waechter): liest ein Waechter seine eigene HTML-Begruendung?

Anlass ist der Vorfall vom 2026-10-02 in ``test_download_key.py``: die
Pruefung "JEDE ?token=-Adresse wird aus dem Abruf-Schluessel gespeist" traf
eine reine KOMMENTARZEILE in ``frontend/settings.html`` und meldete daraus
dauerhaft einen FAIL, den es im Code nicht gab.

Ob dieselbe Luecke in einem anderen Waechter traegt, laesst sich nicht durch
Lesen beantworten. Ein Literalvergleich raet, welche Pruefung gegen welchen
Dateiinhalt laeuft, und verfehlt Inline-Reads sowie
``glob("*.html")``-Schleifen – beim Bau zweimal bezahlt. Deshalb wird der
Waechter SELBST gefragt:

  Laeuft der Waechter ANDERS, wenn jeder ``<!-- ... -->``-Bereich jeder
  gelesenen HTML-Datei ausgeleert ist?

Dazu wird ``Path.read_text`` fuer ``.html`` umgebogen und der Waechter per
runpy als ``__main__`` gefahren. Aendert sich die Bilanz, HAENGT mindestens
eine Pruefung am Inhalt eines HTML-Kommentars – das ist der Befund. Bleibt sie
gleich, traegt die Luecke dort heute nicht.

Ausgeleert wird mit LEERZEICHEN, nicht geloescht: ``.find()``-Vergleiche und
gemeldete Zeilennummern bleiben sonst nicht vergleichbar (Register).

⚠ Die PROBE-BILANZ am Ende ist nicht Zierde, sondern die Positivkontrolle:
ohne sie waere ein unveraenderter Lauf nicht von "die Sonde hat nie
gegriffen" zu unterscheiden.

Aufruf: messung_html_kommentar.py <testdatei> [roh|blank]
"""
import pathlib
import re
import runpy
import sys

KOMMENTAR = re.compile(r"<!--[\s\S]*?-->")


def _leerraum(treffer):
    return re.sub(r"[^\n]", " ", treffer.group(0))


BILANZ = {"dateien": set(), "kommentare": 0, "zeichen": 0}


def patchen():
    """``read_text`` fuer HTML umbiegen und MITZAEHLEN, was weggenommen wurde.

    Die Zaehlung ist die Positivkontrolle: ohne sie waere ein unveraenderter
    Waechterlauf nicht von "die Sonde hat nie gegriffen" zu unterscheiden –
    genau die Verwechslung, die das Register als teuerste Form des Fehlalarms
    fuehrt.
    """
    echt = pathlib.Path.read_text

    def read_text(self, *a, **kw):
        text = echt(self, *a, **kw)
        if self.suffix.lower() != ".html":
            return text
        treffer = KOMMENTAR.findall(text)
        if treffer:
            BILANZ["dateien"].add(self.name)
            BILANZ["kommentare"] += len(treffer)
            BILANZ["zeichen"] += sum(len(x) for x in treffer)
        return KOMMENTAR.sub(_leerraum, text)

    pathlib.Path.read_text = read_text


def main():
    ziel, modus = sys.argv[1], (sys.argv[2] if len(sys.argv) > 2 else "roh")
    if modus == "blank":
        patchen()
    sys.argv = [ziel]
    try:
        runpy.run_path(ziel, run_name="__main__")
    finally:
        if modus == "blank":
            print("\nPROBE-BILANZ: %d HTML-Datei(en) mit Kommentaren gelesen, "
                  "%d Kommentare, %d Zeichen ausgeleert -> %s"
                  % (len(BILANZ["dateien"]), BILANZ["kommentare"],
                     BILANZ["zeichen"],
                     ", ".join(sorted(BILANZ["dateien"])) or "NICHTS"),
                  file=sys.stderr)


if __name__ == "__main__":
    main()
