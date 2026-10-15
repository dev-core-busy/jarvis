"""Root-Konsole fuer die Broker-Freigaben: ``jarvis-broker-admin <befehl>``.

Der Weg, der KEINEN Freigabe-Code braucht, weil er selbst der Nachweis ist: wer
hier etwas freigibt, ist root auf dem Server (Befund K2, 2026-09-29). Die
Oberflaeche braucht fuer dieselbe Entscheidung den Code aus ``totp-einrichten``.

    jarvis-broker-admin liste            offene und alle Eintraege
    jarvis-broker-admin erlauben <key>   Eintrag freigeben
    jarvis-broker-admin ablehnen <key>   Eintrag sperren
    jarvis-broker-admin entfernen <key>  Eintrag loeschen
    jarvis-broker-admin totp-einrichten  Freigabe-Code fuer die Oberflaeche anlegen
    jarvis-broker-admin stand            Herkunft des laufenden Broker-Codes
    jarvis-broker-admin audit [n]        letzte n Audit-Eintraege

Schreibt DIREKT in die Policy-Datei (root-eigen) – der laufende Broker liest sie
bei jeder Pruefung neu, ein Neustart ist nicht noetig.
"""

import json
import os
import sys
import time


def _wer() -> str:
    """Wer hat entschieden? SUDO_USER, sonst root – fuer das Audit."""
    return f"root-konsole ({os.environ.get('SUDO_USER') or 'root'})"


def main(argv: list[str]) -> int:
    if os.geteuid() != 0:
        print("Nur als root.", file=sys.stderr)
        return 2
    from backend.broker import freigabe, meta, policy
    if not argv or argv[0] in ("-h", "--help", "hilfe"):
        print(__doc__)
        return 0
    befehl, rest = argv[0], argv[1:]

    if befehl == "liste":
        eintraege = policy.list_ops()
        offen = [e for e in eintraege if e.get("decision") == policy.PENDING]
        print(f"{len(offen)} offen, {len(eintraege)} gesamt")
        for e in eintraege:
            print(f"  [{e.get('decision'):7}] {e.get('key')}"
                  f"   ({e.get('count', 0)}x, angefordert von {e.get('requested_by') or '-'})")
        return 0

    if befehl in ("erlauben", "ablehnen"):
        if not rest:
            print(f"Aufruf: jarvis-broker-admin {befehl} <key>", file=sys.stderr)
            return 2
        key = " ".join(rest)
        entscheidung = policy.ALLOW if befehl == "erlauben" else policy.DENY
        eintrag = policy.decide(key, entscheidung, _wer())
        if eintrag is None:
            print(f"Unbekannter Eintrag: {key}", file=sys.stderr)
            return 1
        policy.audit(_wer(), "broker.policy_decide", key, entscheidung, peer="root-konsole")
        print(f"{key}: {entscheidung}")
        return 0

    if befehl == "entfernen":
        key = " ".join(rest)
        ok = policy.remove(key)
        if ok:
            policy.audit(_wer(), "broker.policy_remove", key, "removed", peer="root-konsole")
        print("entfernt" if ok else f"Unbekannter Eintrag: {key}")
        return 0 if ok else 1

    if befehl == "totp-einrichten":
        if freigabe.eingerichtet() and "--neu" not in rest:
            print("Es ist bereits ein Freigabe-Code eingerichtet. Ersetzen mit: "
                  "jarvis-broker-admin totp-einrichten --neu")
            return 1
        b32, uri = freigabe.einrichten()
        policy.audit(_wer(), "broker.freigabe_einrichten", "", "eingerichtet", peer="root-konsole")
        print("Freigabe-Code eingerichtet. In einer Authenticator-App hinzufuegen:\n")
        print(f"  Schluessel: {b32}")
        print(f"  URI:        {uri}\n")
        try:
            import shutil
            import subprocess
            if shutil.which("qrencode"):
                subprocess.run(["qrencode", "-t", "ANSIUTF8", uri], check=False)
        except Exception:  # noqa: BLE001
            pass
        print("Der Schluessel liegt root-eigen in", freigabe.SCHLUESSEL,
              "- er wird nicht noch einmal angezeigt.")
        return 0

    if befehl == "stand":
        print(json.dumps(meta._stand(), indent=2, ensure_ascii=False))
        print("Freigabe-Code eingerichtet:", "ja" if freigabe.eingerichtet() else "nein")
        return 0

    if befehl == "audit":
        n = int(rest[0]) if rest and rest[0].isdigit() else 30
        for a in policy.audit_tail(n):
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(a.get("ts", 0)))
            print(f"{ts}  {a.get('decision', ''):10} {a.get('op', ''):24} "
                  f"{a.get('key', '')[:60]}  {a.get('user', '')}  {a.get('peer', '')}")
        return 0

    print(f"Unbekannter Befehl: {befehl}\n{__doc__}", file=sys.stderr)
    return 2


def _main_sicher(argv: list[str]) -> int:
    from backend.broker import policy
    try:
        return main(argv)
    except policy.PolicyUnlesbar as e:
        print(policy.MELDUNG_UNLESBAR % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(_main_sicher(sys.argv[1:]))
