#!/usr/bin/env python3
"""``extra.addin_base_url`` in settings.json setzen – chirurgisch, als Dienstbenutzer.

WARUM NICHT ``config.save_setting``: der Import von ``backend.config`` ruft
``load_settings()``, und ``_save_to_file`` baut nur die BEKANNTEN Schluessel neu
auf (siehe Docstring von ``_geheimfelder_verpacken``). Ein Prozess ohne
Hauptschluessel sieht ausserdem die ``JGS1:``-Werte der Geheimfelder und wuerde
sie beim Zurueckschreiben anfassen. Beides will man auf einer Produktionsdatei
nicht.

Dieses Skript liest die Datei ROH (kein Tresor), setzt genau einen Schluessel und
schreibt im selben Format zurueck (``json.dumps(indent=4)`` wie
``_schreibe_settings_datei``). Verpackte Werte bleiben unveraendert.

EIGENTUEMER: das Skript laeuft als Dienstbenutzer, damit der Eigentuemer der
Datei erhalten bleibt – ``write_text`` behaelt Inode und Rechte. Ein Lauf als
root wird ABGELEHNT (ein root-eigenes settings.json sperrt den Dienst aus).

Ohne ``--schreiben`` wird nur gemeldet, nichts geaendert.

Aufruf (auf dem Server, als Dienstbenutzer):
  python3 deploy/setze_addin_basis.py https://<name>            # nur melden
  python3 deploy/setze_addin_basis.py https://<name> --schreiben
Exit 0 = in Ordnung, 1 = abgelehnt, 2 = konnte nicht laufen
"""
import json
import os
import shutil
import sys
import time
from pathlib import Path

SCHREIBEN = "--schreiben" in sys.argv
ARGS = [a for a in sys.argv[1:] if not a.startswith("--")]
if not ARGS:
    print("Aufruf: setze_addin_basis.py <basis-url> [--schreiben]", file=sys.stderr)
    sys.exit(2)
WERT = ARGS[0].strip().rstrip("/")
DATEI = Path(ARGS[1]) if len(ARGS) > 1 else Path("data/settings.json")

# Form pruefen, bevor etwas angefasst wird: ein Wert ohne https:// macht das
# Manifest unbrauchbar (Office laedt nichts ueber http), und ein Pfadanteil
# wuerde in jede erzeugte URL wandern.
if not WERT.startswith("https://"):
    print(f"ABGELEHNT: '{WERT}' beginnt nicht mit https:// – Office laedt "
          f"Add-in-Quellen ausschliesslich ueber HTTPS.", file=sys.stderr)
    sys.exit(1)
if "/" in WERT[len("https://"):]:
    print(f"ABGELEHNT: '{WERT}' enthaelt einen Pfad – erwartet wird nur das "
          f"Schema mit dem Host.", file=sys.stderr)
    sys.exit(1)

if os.geteuid() == 0:
    print("ABGELEHNT: nicht als root ausfuehren – ein root-eigenes "
          "settings.json sperrt den Dienst (User=jarvis) aus.", file=sys.stderr)
    sys.exit(1)

if not DATEI.is_file():
    print(f"konnte nicht laufen: {DATEI} nicht gefunden (Arbeitsverzeichnis "
          f"{Path.cwd()})", file=sys.stderr)
    sys.exit(2)

try:
    roh = DATEI.read_text()
    daten = json.loads(roh)
except Exception as e:  # noqa: BLE001
    print(f"konnte nicht laufen: {DATEI} nicht lesbar/parsebar: {e}", file=sys.stderr)
    sys.exit(2)
if not isinstance(daten.get("extra", {}), dict):
    print("konnte nicht laufen: 'extra' ist kein Objekt", file=sys.stderr)
    sys.exit(2)

st = DATEI.stat()
vorher = (daten.get("extra") or {}).get("addin_base_url", None)
print(f"Datei      : {DATEI.resolve()}")
print(f"Eigentuemer: uid={st.st_uid} gid={st.st_gid} mode={oct(st.st_mode & 0o777)}")
print(f"vorher     : {vorher!r}")
print(f"nachher    : {WERT!r}")

if vorher == WERT:
    print("unveraendert – nichts zu tun.")
    sys.exit(0)
if not SCHREIBEN:
    print("(nur gemeldet – ohne --schreiben wird nichts geaendert)")
    sys.exit(0)

# Sicherung NEBEN die Datei, nicht nach /tmp: dort ist sie demselben
# Eigentuemer zugaenglich und ueberlebt einen Dienstneustart.
sicherung = DATEI.with_suffix(".json.vor-addin-basis-%s" % time.strftime("%Y%m%d-%H%M%S"))
shutil.copy2(DATEI, sicherung)
print(f"Sicherung  : {sicherung}")

daten.setdefault("extra", {})["addin_base_url"] = WERT
# Format wie _schreibe_settings_datei; write_text behaelt Inode, Rechte und
# Eigentuemer der bestehenden Datei.
DATEI.write_text(json.dumps(daten, indent=4))

# Wirkung pruefen, nicht annehmen: neu von der Platte lesen.
nach = json.loads(DATEI.read_text())
ist = (nach.get("extra") or {}).get("addin_base_url")
st2 = DATEI.stat()
if ist != WERT:
    print(f"FEHLER: nach dem Schreiben steht {ist!r} in der Datei", file=sys.stderr)
    sys.exit(1)
if (st2.st_uid, st2.st_gid) != (st.st_uid, st.st_gid):
    print(f"FEHLER: Eigentuemer hat sich geaendert "
          f"({st.st_uid}:{st.st_gid} -> {st2.st_uid}:{st2.st_gid})", file=sys.stderr)
    sys.exit(1)
# Alle uebrigen Schluessel muessen unveraendert sein – eine Aenderung hier waere
# genau der Schaden, den der chirurgische Weg vermeiden soll.
alt = json.loads(roh)
alt.setdefault("extra", {})["addin_base_url"] = WERT
if alt != nach:
    print("FEHLER: ausser addin_base_url hat sich etwas geaendert", file=sys.stderr)
    sys.exit(1)
print("OK – gesetzt, Eigentuemer unveraendert, sonst nichts geaendert.")
