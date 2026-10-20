"""Root-Konsole fuer die Broker-Freigaben: ``jarvis-broker-admin <befehl>``.

Der Weg, der KEINEN Freigabe-Code braucht, weil er selbst der Nachweis ist: wer
hier etwas freigibt, ist root auf dem Server (Befund K2, 2026-09-29). Die
Oberflaeche braucht fuer dieselbe Entscheidung den Code aus ``totp-einrichten``.

    jarvis-broker-admin liste            offene und alle Eintraege
    jarvis-broker-admin erlauben <key>   Eintrag freigeben
    jarvis-broker-admin ablehnen <key>   Eintrag sperren
    jarvis-broker-admin entfernen <key>  Eintrag loeschen
    jarvis-broker-admin totp-einrichten  Freigabe-Code fuer die Oberflaeche anlegen
    jarvis-broker-admin totp-uebernehmen <konto>
                                         2FA-Geheimnis eines Kontos HIERHER holen,
                                         damit EIN App-Eintrag fuer Anmeldung und
                                         Freigaben genuegt
    jarvis-broker-admin totp-aus <konto> NOTWEG: 2FA eines Kontos abschalten
    jarvis-broker-admin stand            Herkunft des laufenden Broker-Codes
    jarvis-broker-admin audit [n]        letzte n Audit-Eintraege

Schreibt DIREKT in die Policy-Datei (root-eigen) – der laufende Broker liest sie
bei jeder Pruefung neu, ein Neustart ist nicht noetig.

⚠ ``totp-aus`` ist der Gegenpart zur FAIL-CLOSED-Anmeldung: steht das Geheimnis
eines Kontos im Broker und ist der Broker nicht erreichbar, kommt NIEMAND mehr
mit diesem Konto hinein. Dann hier abschalten, Ursache beheben, neu uebernehmen.
"""

import json
import os
import sys
import time


def _wer() -> str:
    """Wer hat entschieden? SUDO_USER, sonst root – fuer das Audit."""
    return f"root-konsole ({os.environ.get('SUDO_USER') or 'root'})"


def _auth_state_datei():
    """``data/auth_state.json`` des Dienstes – der Broker hat eine EIGENE Kopie des
    Codes, aber es gibt nur EINEN Datenbestand (``JARVIS_DIR``)."""
    from pathlib import Path
    return Path(os.environ.get("JARVIS_DIR", "/opt/jarvis")) / "data" / "auth_state.json"


def _auth_state_lesen(datei) -> dict:
    with open(datei, encoding="utf-8") as f:
        return json.load(f)


def _auth_state_schreiben(datei, daten: dict) -> None:
    """Atomar und MIT ERHALTENEM EIGENTUEMER.

    ⚠ Der Dienstbenutzer muss die Datei weiter schreiben koennen. Schreibt root
    sie neu an, gehoert sie danach root – die naechste 2FA-Aenderung des Backends
    scheitert dann still (Register: "Deploy gehoert dem Dienstbenutzer").
    """
    st = os.stat(datei)
    tmp = str(datei) + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, json.dumps(daten, ensure_ascii=False, indent=2).encode("utf-8"))
    finally:
        os.close(fd)
    os.chown(tmp, st.st_uid, st.st_gid)
    os.chmod(tmp, st.st_mode & 0o7777)   # chmod NACH chown – chown loescht setgid
    os.replace(tmp, datei)


def _konto_finden(users: dict, konto: str):
    """Schluessel in ``users``, gross-/kleinschreibungstolerant. None = nicht da."""
    if konto in users:
        return konto
    klein = konto.lower()
    for k in users:
        if k.lower() == klein:
            return k
    return None


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

    if befehl in ("totp-uebernehmen", "totp-aus"):
        if not rest:
            print(f"Aufruf: jarvis-broker-admin {befehl} <konto>", file=sys.stderr)
            return 2
        konto = rest[0]
        datei = _auth_state_datei()
        try:
            daten = _auth_state_lesen(datei)
        except Exception as e:  # noqa: BLE001
            print(f"{datei} nicht lesbar: {e}", file=sys.stderr)
            return 1
        users = daten.get("users") or {}
        schluessel = _konto_finden(users, konto)
        if schluessel is None:
            print(f"Konto nicht im Auth-State: {konto}", file=sys.stderr)
            print("Vorhanden:", ", ".join(sorted(users)) or "(keines)", file=sys.stderr)
            return 1
        st = users[schluessel]

        if befehl == "totp-aus":
            st["totp_enabled"] = False
            st["totp_secret"] = None
            st["totp_pending_secret"] = None
            _auth_state_schreiben(datei, daten)
            policy.audit(_wer(), "broker.totp_aus", f"login:{schluessel}", "abgeschaltet",
                         peer="root-konsole")
            print(f"2FA von '{schluessel}' ist AUS. Die Anmeldung geht wieder ohne Code.")
            print("Der Broker-Schluessel bleibt liegen – Freigaben funktionieren weiter.")
            return 0

        # ── totp-uebernehmen ──
        roh = st.get("totp_secret")
        if roh == freigabe.MARKE_IM_BROKER:
            print(f"'{schluessel}' fragt den Broker bereits – nichts zu tun.")
            return 0
        if not st.get("totp_enabled") or not roh:
            print(f"'{schluessel}' hat keine aktive 2FA (totp_enabled="
                  f"{st.get('totp_enabled')}, secret="
                  f"{'gesetzt' if roh else 'leer'}).", file=sys.stderr)
            print("Erst in der Oberflaeche einrichten, dann uebernehmen.", file=sys.stderr)
            return 1
        # Verpackt (BSI M5)? Dann mit dem Hauptschluessel oeffnen – als root lesbar.
        if isinstance(roh, str) and roh.startswith("JGS1:"):
            try:
                from backend import geheimnis_tresor as _t
                roh = _t.wert_entschluesseln(roh)
            except Exception as e:  # noqa: BLE001
                print(f"2FA-Geheimnis nicht zu oeffnen (Hauptschluessel?): {e}",
                      file=sys.stderr)
                return 1
            if not isinstance(roh, str) or roh.startswith("JGS1:"):
                print("2FA-Geheimnis blieb verpackt – /etc/jarvis/geheimnis.key fehlt "
                      "oder passt nicht.", file=sys.stderr)
                return 1
            # ⚠ Der Verweis kann selbst VERPACKT in der Datei stehen: bis zum
            # 2026-10-20 hielt der Tresor ihn fuer ein Klartext-Geheimnis im Feld
            # ``totp_secret``. Ohne diese Zeile liefe das hier in ein
            # "kein gueltiger Base32-Schluessel" – eine Meldung, die den
            # Administrator in die voellig falsche Richtung schickt.
            if roh == freigabe.MARKE_IM_BROKER:
                print(f"'{schluessel}' fragt den Broker bereits (der Verweis stand nur "
                      "verpackt in der Datei) – nichts zu tun.")
                return 0
        try:
            freigabe.uebernehmen(roh)
        except ValueError as e:
            print(f"Uebernahme abgelehnt: {e}", file=sys.stderr)
            return 1
        st["totp_secret"] = freigabe.MARKE_IM_BROKER
        st["totp_pending_secret"] = None
        _auth_state_schreiben(datei, daten)
        policy.audit(_wer(), "broker.totp_uebernehmen", f"login:{schluessel}",
                     "uebernommen", peer="root-konsole")
        print(f"Das 2FA-Geheimnis von '{schluessel}' liegt jetzt in {freigabe.SCHLUESSEL}.")
        print("DEIN VORHANDENER EINTRAG IN DER AUTHENTICATOR-APP GILT UNVERAENDERT –")
        print("fuer die Anmeldung UND fuer Root-Freigaben. Kein zweiter Eintrag noetig.")
        print()
        print("Der laufende Code gilt als verbraucht: fuer die naechste Aktion den")
        print("FOLGENDEN Code abwarten (bis zu 30 Sekunden).")
        print()
        print("Falls die Anmeldung danach klemmt (Broker nicht erreichbar):")
        print(f"  jarvis-broker-admin totp-aus {schluessel}")
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
