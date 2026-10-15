#!/usr/bin/env python3
"""Waechter: Code-Review 2026-10-07, NIEDRIG – Root-Broker.

  [1] policy.py: eine kaputte Policy-Datei galt als LEER; das naechste
      ``check()`` legte sie neu an, und jedes Admin-``deny`` auf einer
      automatischen Op wurde wieder ``allow``. Jetzt: abweisen, nichts
      schreiben, Broker-Start stuerzt nicht ab, Admin-Ops melden den Grund.
  [2] ops.py (WebDAV-Mount): Benutzer/Kennwort gingen ungeprueft und
      ungequotet in /etc/davfs2/secrets – ein Zeilenumbruch erzeugte fremde
      Eintraege; ``mp not in content`` (Teilstring) liess geaenderte Kennwoerter
      nie ankommen und hielt share_1 fuer vorhanden, sobald share_10 da war.

Gemessen an den ECHTEN Modulen in einem Sandkasten (Pfade per Umgebung bzw.
Argument), nichts unter /etc wird angefasst.

    python3 tests/test_broker_niedrig.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import hashlib
import json
import os
import shlex
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
SK = Path(tempfile.mkdtemp(prefix="waechter-broker-niedrig-"))
os.environ["JARVIS_BROKER_POLICY"] = str(SK / "broker-policy.json")
os.environ["JARVIS_BROKER_AUDIT"] = str(SK / "audit.jsonl")
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % (detail,)) if detail else ""))


def abbruch(grund):
    print("\n\033[31mABBRUCH\033[0m: %s" % grund)
    sys.exit(2)


try:
    from backend.broker import meta, ops, policy  # noqa: E402
except Exception as e:  # noqa: BLE001
    abbruch("Broker-Module nicht ladbar: %s" % e)
if not str(policy.POLICY_FILE).startswith(str(SK)):
    abbruch("Policy-Datei zeigt aus dem Sandkasten heraus: %s" % policy.POLICY_FILE)

# ─── [1] Policy ──────────────────────────────────────────────────────────────
print("\n\033[1m[1] Broker-Policy: kaputte Datei = fail-closed\033[0m")
check("Positivkontrolle: neue automatische Op wird erlaubt",
      policy.check("svc:x", "svc", "x", "jarvis", True) == policy.ALLOW)
policy.decide("svc:x", policy.DENY, "admin")
check("Positivkontrolle: Admin-deny greift", policy.check("svc:x", "svc", "x", "jarvis", True) == policy.DENY)
policy.check("svc:y", "svc", "y", "jarvis", True)
kaputt = policy.POLICY_FILE.read_text()[:-40]          # abgeschnitten wie nach Absturz
policy.POLICY_FILE.write_text(kaputt)
md5 = hashlib.md5(kaputt.encode()).hexdigest()
check("⚠ kaputte Datei: das abgelehnte svc:x bleibt abgelehnt",
      policy.check("svc:x", "svc", "x", "jarvis", True) == policy.DENY)
check("⚠ … auch eine sonst automatische Op wird abgewiesen",
      policy.check("svc:y", "svc", "y", "jarvis", True) == policy.DENY)
check("⚠ … und die Datei wird NICHT neu angelegt (Admin-Entscheidungen bleiben zur Reparatur)",
      hashlib.md5(policy.POLICY_FILE.read_bytes()).hexdigest() == md5)
try:
    erg = policy.herabstufen({"svc"})
    check("Broker-Start (herabstufen) stuerzt nicht ab und schreibt nichts",
          erg == [] and hashlib.md5(policy.POLICY_FILE.read_bytes()).hexdigest() == md5, erg)
except Exception as e:  # noqa: BLE001
    check("Broker-Start (herabstufen) stuerzt nicht ab und schreibt nichts", False, e)
for op_, args in (("broker.policy_list", {}),
                  ("broker.policy_decide", {"key": "svc:x", "decision": "deny", "by": "a"})):
    try:
        a = meta.behandeln(op_, args)
    except Exception as e:  # noqa: BLE001
        a = {"geworfen": str(e)}
    check("%s meldet den Grund statt abzustuerzen" % op_,
          isinstance(a, dict) and a.get("ok") is False and "unlesbar" in str(a.get("error")), a)
policy.POLICY_FILE.unlink()
check("Positivkontrolle: ohne Datei (Erstinstallation) wird wieder angelegt",
      policy.check("svc:z", "svc", "z", "jarvis", True) == policy.ALLOW
      and policy.POLICY_FILE.exists())

# ─── [2] davfs2 ──────────────────────────────────────────────────────────────
print("\n\033[1m[2] WebDAV-Zugang in den davfs2-Secrets\033[0m")
SEC = SK / "davfs2" / "secrets"
setzen = ops._davfs_secrets_setzen


def eintraege():
    out = {}
    for z in (SEC.read_text().splitlines() if SEC.exists() else []):
        f = shlex.split(z, comments=True)
        if f:
            out.setdefault(f[0], []).append(f[1:])
    return out


check("Positivkontrolle: Eintrag geschrieben",
      setzen("/mnt/jarvis/share_10", "anna", "geheim", SEC) == ""
      and eintraege().get("/mnt/jarvis/share_10") == [["anna", "geheim"]], eintraege())
check("Datei nur fuer root lesbar (0600)", (SEC.stat().st_mode & 0o077) == 0, oct(SEC.stat().st_mode))
vorher = SEC.read_bytes()
fehler = setzen("/mnt/jarvis/share_2", "bert", "pw\n/mnt/jarvis/share_10 boese boese", SEC)
check("⚠ Zeilenumbruch im Kennwort -> abgewiesen", bool(fehler), fehler)
check("⚠ … und KEIN zusaetzlicher Eintrag (Datei unveraendert)", SEC.read_bytes() == vorher)
check("⚠ Zeilenumbruch im Benutzernamen -> abgewiesen", bool(setzen("/mnt/jarvis/share_2", "b\nx", "pw", SEC)))
setzen("/mnt/jarvis/share_1", "carl", 'mit leer "und" \\ zeichen', SEC)
check("⚠ share_1 wird angelegt, obwohl share_10 schon steht (kein Teilstring-Vergleich)",
      eintraege().get("/mnt/jarvis/share_1") == [["carl", 'mit leer "und" \\ zeichen']], eintraege())
setzen("/mnt/jarvis/share_1", "carl", "neu", SEC)
check("⚠ geaendertes Kennwort kommt an (genau EIN Eintrag fuer share_1)",
      eintraege().get("/mnt/jarvis/share_1") == [["carl", "neu"]], eintraege())
check("… share_10 bleibt unberuehrt", eintraege().get("/mnt/jarvis/share_10") == [["anna", "geheim"]])

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
