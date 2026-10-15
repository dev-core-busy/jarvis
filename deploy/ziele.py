#!/usr/bin/env python3
"""Server-Ziele (DEV, ECHT, ...) aus der Umgebung statt aus dem Repo.

WARUM
-----
IP-Adressen, FQDNs und E-Mail-Adressen sind interne Angaben und stehen NIE im
Repository - auch nicht als Vorgabewert in einem Werkzeug. Werkzeuge und Proben,
die einen echten Server brauchen, holen ihn deshalb hier ab:

  1. aus der Umgebungsvariable (``JARVIS_DEV_SSH=... python3 tests/...``),
  2. sonst aus der ``.env`` im Repo-Wurzelverzeichnis (gitignored).

Fehlt der Wert, bricht ``wert()`` mit Exit 2 ab ("konnte nicht laufen") - ein
geratener Ersatz waere schlimmer: eine Probe gegen den falschen Server sieht wie
eine echte Messung aus.

Bekannte Schluessel (Platzhalter siehe ``.env.example``):
  JARVIS_DEV_SSH    ssh-Ziel DEV, z.B. root@<dev-host>
  JARVIS_DEV_URL    HTTPS-Basis DEV, z.B. https://<dev-host>
  JARVIS_ECHT_SSH   ssh-Ziel ECHT (nur lesen/messen, siehe CLAUDE.md)
  JARVIS_ECHT_PASS  Kennwort dazu – NUR per stdin weitergeben (sudo -S)
  JARVIS_SFTP_PASS  jarvis-ai.info, SFTP Port 8023 (deploy/jarvis_ai_sftp.py)
  ⚠ Die *_PASS-Schluessel NIE ueber den Shell-Aufruf unten abfragen – er gibt
  den Wert auf stdout aus (Terminal, Protokolle). Im Code: ``finde()``.

Aufruf aus der Shell:  python3 deploy/ziele.py JARVIS_DEV_SSH
"""
import os
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
ENV_DATEI = WURZEL / ".env"


def _aus_env_datei(name):
    """Einfacher .env-Leser (KEY=WERT, # Kommentare, optionale Anfuehrungszeichen).

    Bewusst ohne python-dotenv: die Proben laufen auch dort, wo das Paket fehlt."""
    try:
        zeilen = ENV_DATEI.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for zeile in zeilen:
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        schluessel, _, wert = zeile.partition("=")
        if schluessel.strip().removeprefix("export ").strip() == name:
            wert = wert.strip()
            if len(wert) >= 2 and wert[0] == wert[-1] and wert[0] in "\"'":
                wert = wert[1:-1]
            return wert or None
    return None


def finde(name):
    """Wert oder None - fuer Aufrufer, die selbst entscheiden, was fehlt."""
    return os.environ.get(name) or _aus_env_datei(name)


def wert(name):
    """Wert oder Exit 2 mit Hinweis, wo er einzutragen ist."""
    w = finde(name)
    if not w:
        print("ABBRUCH (Exit 2): %s ist nicht gesetzt." % name, file=sys.stderr)
        print("  Interne Adressen stehen nicht im Repo. Eintragen in %s" % ENV_DATEI,
              file=sys.stderr)
        print("  (Vorlage: .env.example) oder als Umgebungsvariable setzen.",
              file=sys.stderr)
        sys.exit(2)
    return w


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Aufruf: python3 deploy/ziele.py <SCHLUESSEL>", file=sys.stderr)
        sys.exit(2)
    print(wert(sys.argv[1]))
