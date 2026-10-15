"""Root-Broker: privilegierte Operationen als separater root-Dienst.

Das Backend (jarvis.service) laeuft unprivilegiert; alles, was root braucht,
laeuft ueber den Broker (jarvis-broker.service, Unix-Socket) mit benannten,
validierten Operationen. Jede Operation wird als auditierbarer Policy-Eintrag
gefuehrt (allow/deny/pending) – unbekannte Root-Befehle des Agenten erscheinen
als 'pending' und muessen von einem Admin freigegeben werden.

Module:
- policy.py  – Policy-Datei (/etc/jarvis/broker-policy.json) + Audit-Log
- ops.py     – Operations-Registry (Validierung + Ausfuehrung) + Dispatch
- daemon.py  – Unix-Socket-Server (laeuft als root)

Client fuer das Backend: backend/broker_client.py (mit root-Fallback fuer
nicht migrierte Alt-Installationen).
"""

import os as _os
from pathlib import Path as _Path

# Env-Override fuer Tests/Sonderinstallationen
SOCKET_PATH = _os.environ.get("JARVIS_BROKER_SOCKET", "/run/jarvis-broker.sock")

# ── Zwei Wurzeln (Befund K1, 2026-09-29) ─────────────────────────────────────
# Der Broker laeuft als root. Bis heute lud er seinen Code aus /opt/jarvis – und
# das gehoert dem Dienstbenutzer `jarvis` (setup_broker.sh: chown -R). Wer als
# jarvis eine Zeile in backend/broker/, im venv oder im Startskript aenderte,
# hatte nach dem naechsten Broker-Neustart root. Die Trennung Backend/Broker war
# damit wirkungslos.
#
# Seitdem laeuft der Broker aus einer ROOT-EIGENEN Kopie (INSTALL_DIR, erzeugt
# von deploy/security/broker_installieren.sh) mit dem System-Python:
#   CODE_ROOT    – woher der Code kommt, der hier LAEUFT (Kopie bzw. Arbeitsbaum)
#   PROJECT_ROOT – der Baum mit den DATEN (/opt/jarvis): settings.json, certs/,
#                  vendor/, die Pfade fuer Rechte und Bindungen.
# Aus PROJECT_ROOT wird als root NICHTS ausgefuehrt, nur gelesen/geschrieben.
CODE_ROOT = _Path(__file__).resolve().parent.parent.parent
PROJECT_ROOT = _Path(_os.environ.get("JARVIS_PROJECT_ROOT") or CODE_ROOT)
INSTALL_DIR = _Path(_os.environ.get("JARVIS_BROKER_INSTALL_DIR", "/usr/local/lib/jarvis-broker"))
