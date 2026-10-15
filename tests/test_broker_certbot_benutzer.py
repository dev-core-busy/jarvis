#!/usr/bin/env python3
"""Waechter: certbot_obtain nimmt nur einen echten Dienst-Benutzer an (Code-Review 2026-10-07).

Befund: ``service_user`` kam ungeprueft aus den Argumenten der automatisch
erlaubten Broker-Op ``certbot_obtain`` und landete UNGEQUOTET in
``/etc/letsencrypt/renewal-hooks/deploy/jarvis-copy-certs.sh`` – ein Skript,
das certbot bei jeder Erneuerung als root ausfuehrt. Ein ``service_user`` wie
``x; curl …|sh`` war damit eine Befehlsinjektion in ein Root-Skript.

Gemessen an der WIRKUNG mit dem echten ``_op_certbot_obtain``; ``_stream_shell``
ist eine Attrappe in echter Signatur, die jeden Aufruf aufzeichnet (es laeuft
also weder apt-get noch certbot):

  * Positivkontrolle: mit einem EXISTIERENDEN Benutzer kommt die Op bis zum
    certbot-Aufruf – die Pruefung laesst gueltige Namen durch.
  * ungueltige, unbekannte und root-Namen werden abgewiesen, BEVOR irgendein
    Befehl laeuft.

    python3 tests/test_broker_certbot_benutzer.py
"""
import getpass
import importlib
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  \033[32m✓\033[0m %s" % label)
    else:
        _fail += 1
        print("  \033[31m✗\033[0m %s%s" % (label, (" – %s" % detail) if detail else ""))


def abbruch(grund):
    print("\n\033[31mABBRUCH\033[0m: %s" % grund)
    sys.exit(2)


if os.geteuid() == 0:
    abbruch("als root ausgefuehrt – die Op koennte echte Dateien anlegen")
try:
    OPS = importlib.import_module("backend.broker.ops")
except Exception as e:  # noqa: BLE001
    abbruch("backend.broker.ops nicht importierbar: %s" % e)
if not hasattr(OPS, "_op_certbot_obtain") or not hasattr(OPS, "_stream_shell"):
    abbruch("_op_certbot_obtain/_stream_shell nicht gefunden")

aufrufe = []


def _stream_shell(cmd, cwd, timeout, stream):   # echte Signatur
    aufrufe.append(cmd)
    return {"rc": 1, "stdout": "", "stderr": "attrappe"}


OPS._stream_shell = _stream_shell


def op(user):
    aufrufe.clear()
    return OPS._op_certbot_obtain({"domain": "jarvis.beispiel.de", "email": "admin@beispiel.de",
                                   "service_user": user}, None)


print("\n\033[1mPositivkontrolle\033[0m")
r = op(getpass.getuser())
check(any("certonly" in c for c in aufrufe) or any("apt-get" in c for c in aufrufe),
      "gueltiger Benutzer: Op erreicht den certbot-Schritt", str(aufrufe))
if _fail:
    abbruch("Positivkontrolle gescheitert – die Abweisungen waeren trivial")

print("\n\033[1mAbweisungen vor jedem Befehl\033[0m")
for boese in ("jarvis; touch /tmp/pwn", "$(id)", "a b", "jarvis\nid", "../root",
              "root", "jv_gibt_es_nicht_123", "", "-rf"):
    r = op(boese)
    check(r.get("ok") is False and not aufrufe,
          "service_user=%r -> abgewiesen, kein Befehl" % boese, "%s / %s" % (r, aufrufe))

print("\n" + "=" * 60)
print("Ergebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)
