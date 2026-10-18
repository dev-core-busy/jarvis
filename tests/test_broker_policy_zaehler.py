#!/usr/bin/env python3
"""Waechter: Policy-Zaehler gebuendelt, Entscheidungen sofort (Code-Review 2026-10-18).

``policy.check()`` schrieb bei JEDER Op die ganze Freigabedatei neu. Jetzt
sammeln sich Zaehler im Speicher; neue Eintraege und Entscheidungen gehen
weiter sofort auf die Platte, und eine Aenderung von Hand wird gesehen.

Gemessen an der echten ``backend/broker/policy.py`` gegen eine Datei im
Wegwerf-Verzeichnis:
  [1] neuer Eintrag sofort geschrieben; Wiederholungen schreiben NICHT neu,
      ``flush()`` bringt die Zaehler vollstaendig auf die Platte
  [2] ``decide`` wirkt beim naechsten ``check`` sofort; eine Aenderung der
      Datei von Hand ebenso (Zwischenspeicher haengt an mtime/Groesse)
  [3] Deckel fuer offene Eintraege
  [4] fail-closed bei kaputter Datei bleibt
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  -> " + detail) if detail else ""))


SK = Path(tempfile.mkdtemp(prefix="policy_zaehler_"))
os.environ["JARVIS_BROKER_POLICY"] = str(SK / "policy.json")
os.environ["JARVIS_BROKER_AUDIT"] = str(SK / "audit.jsonl")
from backend.broker import policy as P  # noqa: E402

if str(P.POLICY_FILE).startswith(str(SK)) is False:
    print("ABBRUCH: Sandkasten greift nicht")
    sys.exit(2)


def datei():
    return json.loads(P.POLICY_FILE.read_text())


try:
    print("\n[1] Zaehler")
    r = P.check("systemctl:restart:jarvis.service", "systemctl", "d", "jarvis", True)
    check("(Positivkontrolle) neuer Eintrag erlaubt und sofort geschrieben",
          r == P.ALLOW and "systemctl:restart:jarvis.service" in datei()["ops"])
    vorher = P.POLICY_FILE.stat().st_mtime_ns
    time.sleep(0.02)
    for _ in range(50):
        P.check("systemctl:restart:jarvis.service", "systemctl", "d", "jarvis", True)
    check("50 Wiederholungen schreiben die Datei NICHT neu", P.POLICY_FILE.stat().st_mtime_ns == vorher)
    P.flush()
    check("flush(): Zaehler vollstaendig (1 + 50)",
          datei()["ops"]["systemctl:restart:jarvis.service"]["count"] == 51,
          str(datei()["ops"]["systemctl:restart:jarvis.service"]["count"]))

    print("\n[2] Entscheidungen sofort")
    k = "shell_root:sha256:" + "a" * 64
    check("neuer Root-Befehl: pending", P.check(k, "shell_root", "x", "jarvis", False) == P.PENDING)
    P.decide(k, P.ALLOW, "admin")
    check("decide(allow) wirkt beim naechsten check sofort", P.check(k, "shell_root", "x", "jarvis", False) == P.ALLOW)
    d = datei()
    d["ops"][k]["decision"] = P.DENY
    d["ops"][k]["decided_by"] = "von Hand, laengerer Text damit sich die Groesse aendert"
    P.POLICY_FILE.write_text(json.dumps(d, indent=2))
    check("Aenderung der Datei von Hand wird gesehen (deny)",
          P.check(k, "shell_root", "x", "jarvis", False) == P.DENY)

    print("\n[3] Deckel fuer offene Eintraege")
    alt = P.PENDING_MAX
    P.PENDING_MAX = 5
    for i in range(10):
        P.check("shell_root:sha256:%064d" % i, "shell_root", "x", "jarvis", False)
    offen = [e for e in datei()["ops"].values() if e.get("decision") == P.PENDING]
    check("nicht mehr als PENDING_MAX offene Eintraege angelegt", len(offen) == 5, str(len(offen)))
    check("ueber dem Deckel: trotzdem nicht erlaubt",
          P.check("shell_root:sha256:" + "f" * 64, "shell_root", "x", "jarvis", False) == P.PENDING)
    check("automatisch erlaubte Ops sind vom Deckel nicht betroffen",
          P.check("unlock_screen", "unlock_screen", "x", "system", True) == P.ALLOW)
    P.PENDING_MAX = alt

    print("\n[4] fail-closed")
    P.POLICY_FILE.write_text("{kaputt")
    check("kaputte Datei: deny", P.check("systemctl:restart:jarvis.service", "systemctl", "d", "jarvis", True) == P.DENY)
    check("... und die Datei bleibt zur Reparatur stehen", P.POLICY_FILE.read_text() == "{kaputt")
finally:
    shutil.rmtree(SK, ignore_errors=True)

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
