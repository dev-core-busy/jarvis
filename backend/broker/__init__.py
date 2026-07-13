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

# Env-Override fuer Tests/Sonderinstallationen
SOCKET_PATH = _os.environ.get("JARVIS_BROKER_SOCKET", "/run/jarvis-broker.sock")
