#!/usr/bin/env python3
"""Live-Probe mit Einmal-Codes aus dem Root-Broker starten (nur DEV, als root).

Startet ``<probe>`` ueber ``deploy/als_dienst.sh`` (Hauptschluessel, BSI M5) und
beantwortet ihre Code-Anfragen (``tests/lib/zweifaktor_code.py``) aus dem
root-eigenen Broker-Schluessel. Das Geheimnis bleibt in diesem Prozess; die
Probe bekommt nur Codes.

Jeder ausgegebene Code stammt aus einem Zeitschritt, den der Broker noch nicht
verbraucht hat (``letzter_schritt`` im Broker-Zustand) und den dieses Relais
noch nicht ausgegeben hat – sonst wiese der Wiederholschutz (N3) ihn ab, und
die Probe hielte ihren eigenen Messfehler fuer einen Befund. Notfalls wird bis
zum naechsten Schritt gewartet.

Nur Standardbibliothek (HOTP nach RFC 4226 wie backend/broker/freigabe.py).

Aufruf (root, auf DEV):
    python3 tests/live_mit_brokercode.py tests/live_bsi_m5_dev.py
Exit = Exit der Probe; 2 = konnte nicht laufen.
"""
import base64
import hashlib
import hmac
import json
import os
import struct
import subprocess
import sys
import time
from pathlib import Path

JARVIS = Path("/opt/jarvis")
SCHLUESSEL = Path(os.environ.get("JARVIS_BROKER_FREIGABE_KEY", "/etc/jarvis/broker-freigabe.key"))
ZUSTAND = Path(os.environ.get("JARVIS_BROKER_FREIGABE_STATE", "/etc/jarvis/broker-freigabe.state"))
SCHRITT_S = 30
ANFRAGE = "@@BROKERCODE?@@"


def abbruch(grund: str) -> None:
    print("ABBRUCH (konnte nicht laufen): " + grund, flush=True)
    sys.exit(2)


def _code(schluessel: bytes, zaehler: int) -> str:
    mac = hmac.new(schluessel, struct.pack(">Q", zaehler), hashlib.sha1).digest()
    ofs = mac[-1] & 0x0F
    return str((struct.unpack(">I", mac[ofs:ofs + 4])[0] & 0x7FFFFFFF) % 10 ** 6).zfill(6)


def _broker_letzter() -> int:
    try:
        return int(json.loads(ZUSTAND.read_text()).get("letzter_schritt", 0))
    except Exception:  # noqa: BLE001
        return 0


def main() -> int:
    if os.geteuid() != 0:
        abbruch("muss als root laufen (Broker-Schluessel ist root-eigen)")
    if len(sys.argv) != 2:
        abbruch("Aufruf: live_mit_brokercode.py <probe>")
    try:
        roh = SCHLUESSEL.read_text(encoding="ascii").strip().upper()
        schluessel = base64.b32decode(roh + "=" * (-len(roh) % 8))
    except Exception as e:  # noqa: BLE001
        abbruch("Broker-Schluessel nicht lesbar: %s" % e)
    probe = str((JARVIS / sys.argv[1]) if not sys.argv[1].startswith("/") else sys.argv[1])
    cmd = ["bash", str(JARVIS / "deploy" / "als_dienst.sh"), str(JARVIS / "venv" / "bin" / "python"), probe]
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, bufsize=1, cwd=str(JARVIS))
    ausgegeben = 0
    for zeile in p.stdout:
        if zeile.strip() != ANFRAGE:
            sys.stdout.write(zeile)
            sys.stdout.flush()
            continue
        # frischer Schritt: weder vom Broker noch von uns schon verbraucht
        while True:
            schritt = int(time.time() // SCHRITT_S)
            if schritt > max(ausgegeben, _broker_letzter()):
                break
            time.sleep(1)
        ausgegeben = schritt
        p.stdin.write(_code(schluessel, schritt) + "\n")
        p.stdin.flush()
    return p.wait()


if __name__ == "__main__":
    sys.exit(main())
