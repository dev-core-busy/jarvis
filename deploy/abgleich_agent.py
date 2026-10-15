#!/usr/bin/env python3
"""Serverseitige Haelfte von ``deploy/abgleich.py``.

Wird per scp abgelegt und dort ausgefuehrt; laeuft mit dem System-Python und
braucht KEINE Fremdmodule (der Server hat kein venv fuer Wartungsskripte).

Zwei Auftraege, beide reine LESE-Operationen:

* ``hashes`` – md5 je Datei aus einer Liste. Fehlende melden ``-``.
* ``fremde``  – alle Dateien unter den genannten Wurzeln, die NICHT in der
  Liste stehen (Kandidaten fuer „verirrt"); die Bewertung, ob sie legitim
  sind, faellt der Aufrufer, weil nur DORT die ``.gitignore`` liegt.

Ausgabe ist zeilenweise ``<wert>\\t<pfad>`` mit NUL-freien Pfaden – die
Dateiliste kommt NUL-getrennt herein, damit Leerzeichen in Namen nicht
zerbrechen.
"""
import hashlib
import os
import sys

# Verzeichnisse, die auf einem laufenden Server IMMER existieren und nie ins
# Repo gehoeren. Sie hier auszunehmen ist kein Kosmetik-Filter: ohne das
# meldet der Lauf zehntausende venv-Dateien als „verirrt" und die eine
# Datei, auf die es ankommt, geht darin unter.
UEBERGEHEN = {".git", "venv", "__pycache__", "node_modules", ".mypy_cache",
              ".pytest_cache", ".ruff_cache", "data", "logs"}


def _md5(pfad):
    h = hashlib.md5()
    with open(pfad, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def hashes(wurzel, dateien):
    for rel in dateien:
        voll = os.path.join(wurzel, rel)
        try:
            # lstat, nicht stat: ein Symlink ist keine Datei, deren Inhalt
            # hier verglichen werden darf.
            if not os.path.isfile(voll) or os.path.islink(voll):
                print("-\t%s" % rel)
                continue
            print("%s\t%s" % (_md5(voll), rel))
        except OSError as e:
            print("FEHLER:%s\t%s" % (e.__class__.__name__, rel))


def fremde(wurzel, bekannt, praefixe):
    for p in praefixe:
        # Startpunkt selbst pruefen, nicht nur den Abstieg: "data" steht in
        # der Praefixliste, weil data/instructions_default/ git-verfolgt ist –
        # ohne diese Zeile laeuft der Suchlauf mitten IN data/ los und meldet
        # die gesamte Laufzeitablage (gemessen: 197 Eintraege) als "verirrt".
        # Der eine Fund, auf den es ankommt, geht darin unter.
        if p.split("/", 1)[0] in UEBERGEHEN:
            continue
        start = os.path.join(wurzel, p) if p else wurzel
        if not os.path.isdir(start):
            continue
        for ordner, unter, namen in os.walk(start):
            unter[:] = [u for u in unter if u not in UEBERGEHEN]
            for n in namen:
                voll = os.path.join(ordner, n)
                rel = os.path.relpath(voll, wurzel)
                if rel in bekannt:
                    continue
                art = "link" if os.path.islink(voll) else "datei"
                try:
                    groesse = os.path.getsize(voll)
                except OSError:
                    groesse = -1
                print("%s:%d\t%s" % (art, groesse, rel))


def main():
    if len(sys.argv) < 4:
        sys.stderr.write("Aufruf: abgleich_agent.py <auftrag> <wurzel> <listendatei> [praefixe...]\n")
        return 2
    auftrag, wurzel, liste = sys.argv[1], sys.argv[2], sys.argv[3]
    if not os.path.isdir(wurzel):
        sys.stderr.write("Zielverzeichnis fehlt: %s\n" % wurzel)
        return 2
    with open(liste, "rb") as f:
        roh = f.read()
    dateien = [x.decode("utf-8", "surrogateescape") for x in roh.split(b"\0") if x]

    if auftrag == "hashes":
        hashes(wurzel, dateien)
    elif auftrag == "fremde":
        fremde(wurzel, set(dateien), sys.argv[4:] or [""])
    else:
        sys.stderr.write("Unbekannter Auftrag: %s\n" % auftrag)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
