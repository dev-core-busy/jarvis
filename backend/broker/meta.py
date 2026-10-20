"""Meta-Operationen des Brokers (Freigabeliste, Audit) – EINE Fassung fuer beide Wege.

Bis 2026-09-29 standen sie zweimal: im Daemon und im root-Fallback des Clients
(``broker_client._local_dispatch``). Die zweite Fassung protokollierte beim
Loeschen nicht einmal – zwei Fassungen derselben Regel laufen auseinander.

Befund K2: ``broker.policy_decide`` war "immer erlaubt". Seitdem gilt:

* Eine Entscheidung, die etwas EINSCHRAENKT (``deny``, ``pending``), braucht
  keinen Nachweis – schlimmstenfalls kann ein kompromittiertes Backend eine
  Funktion sperren, aber keine Rechte gewinnen.
* ``allow`` und ``remove`` brauchen den Freigabe-Code (``freigabe.pruefen``).
  ``remove`` gehoert dazu, weil ein geloeschter Eintrag einer Systemoperation
  beim naechsten Aufruf wieder AUTOMATISCH erlaubt angelegt wird – das Loeschen
  einer Ablehnung waere sonst eine Freigabe durch die Hintertuer.
* Jede Entscheidung und jeder abgewiesene Versuch steht im Audit, mit der
  uid des Aufrufers aus dem Kernel (SO_PEERCRED), nicht mit dessen Angabe.
"""

import os

from backend.broker import freigabe, policy


def _stand() -> dict:
    """Woher kommt der laufende Broker-Code? (STAND-Datei der Installation)"""
    from backend.broker import CODE_ROOT
    try:
        import json
        return json.loads((CODE_ROOT / "STAND").read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"quelle": "arbeitsbaum", "pfad": str(CODE_ROOT)}


def _nachweis(args: dict, by: str, op: str, key: str, peer: str) -> dict | None:
    """None = Nachweis gueltig; sonst die Fehlerantwort (bereits auditiert)."""
    ok, grund = freigabe.pruefen(args.get("nachweis"))
    if ok:
        return None
    policy.audit(by, op, key, "abgewiesen", detail=f"Freigabe-Code: {grund}", peer=peer)
    return {"ok": False, "grund": grund,
            "error": freigabe.MELDUNG.get(grund, "Freigabe-Code ungueltig")}


def behandeln(op: str, args: dict, peer: str = "") -> dict | None:
    """Antwort fuer eine Meta-Op, oder None, wenn ``op`` keine ist."""
    try:
        return _behandeln(op, args, peer)
    except policy.PolicyUnlesbar as e:
        return {"ok": False, "error": policy.MELDUNG_UNLESBAR % e}


def _behandeln(op: str, args: dict, peer: str = "") -> dict | None:
    args = args or {}
    by = str(args.get("by", ""))
    key = str(args.get("key", ""))
    if op == "broker.ping":
        return {"ok": True, "pid": os.getpid(), "euid": os.geteuid(),
                "stand": _stand(), "freigabe_code": freigabe.eingerichtet()}
    if op == "broker.policy_list":
        return {"ok": True, "ops": policy.list_ops(),
                "freigabe_code": freigabe.eingerichtet()}
    if op == "broker.audit_tail":
        return {"ok": True, "entries": policy.audit_tail(int(args.get("n") or 100))}
    if op == "broker.policy_decide":
        decision = str(args.get("decision", ""))
        if decision == policy.ALLOW:
            fehler = _nachweis(args, by, op, key, peer)
            if fehler:
                return fehler
        entry = policy.decide(key, decision, by)
        if entry is None:
            return {"ok": False, "error": "Unbekannter Key oder ungueltige Entscheidung"}
        policy.audit(by, op, key, decision, peer=peer)
        return {"ok": True, "entry": entry}
    # ── Fernzugang/SSH (BSI M7 in der Oberflaeche, Regeln in fernzugang.py) ──
    if op == "broker.ssh_status":
        from backend.broker import fernzugang
        return fernzugang.status()
    if op in ("broker.ssh_haertung", "broker.ssh_netze"):
        from backend.broker import fernzugang
        aktion = str(args.get("aktion", ""))
        audit_key = f"{op}:{aktion}"
        # verwerfen stellt nur den bestaetigten Stand her – wie der Timer
        if aktion != "verwerfen":
            fehler = _nachweis(args, by, op, audit_key, peer)
            if fehler:
                return fehler
        if op == "broker.ssh_haertung":
            erg = fernzugang.haertung(aktion, str(args.get("root_modus", "")))
            info = f"root_modus={args.get('root_modus', '')}" if aktion == "test" else ""
        else:
            erg = fernzugang.netze(aktion, str(args.get("netze", "")))
            info = f"netze={str(args.get('netze', ''))[:200]}" if aktion == "test" else ""
        policy.audit(by, op, audit_key, "executed", rc=erg.get("rc"),
                     detail=str(erg.get("meldung", ""))[:200], info=info, peer=peer)
        return erg
    # ── Zwei-Faktor-Code der ANMELDUNG gegen denselben Schluessel pruefen ──
    # Betreiberentscheid 2026-10-20: genau EIN Eintrag in der Authenticator-App.
    # Deshalb liegt das Geheimnis nur noch hier (root-eigen) und die Anmeldung
    # fragt den Broker, statt es selbst in ``data/auth_state.json`` zu halten –
    # die Richtung ist entscheidend, denn andersherum (Broker prueft gegen das
    # Geheimnis des Backends) waere Befund K2 wieder offen.
    #
    # ⚠ KEIN Nachweis-Aufruf hier: diese Op IST die Nachweispruefung. Sie ist
    # damit ein Orakel, das jeder Prozess des Dienstbenutzers befragen kann –
    # die einzige Schranke dagegen ist die Fehlversuch-Sperre in
    # ``freigabe.pruefen`` (eigener Zaehler fuer ``login``, siehe dort).
    #
    # ⚠ DER SCHLUESSEL GILT JE SERVER, NICHT JE KONTO. ``konto`` steht nur im
    # Audit. Mehrere Konten mit ``totp_secret == "broker"`` teilen sich denselben
    # Code – das ist fuer EINEN Administrator gedacht; Waechter
    # ``tests/test_broker_totp.py`` prueft, dass es bei einem bleibt.
    if op == "broker.totp_pruefen":
        konto = str(args.get("konto", ""))
        audit_key = f"login:{konto}"
        ok, grund = freigabe.pruefen(args.get("code"), zweck=freigabe.ZWECK_LOGIN)
        policy.audit(by, op, audit_key, "ok" if ok else "abgewiesen",
                     detail="" if ok else f"2FA-Code: {grund}", peer=peer)
        return {"ok": ok, "grund": grund,
                "error": "" if ok else freigabe.MELDUNG.get(grund, "Code ungueltig")}
    if op == "broker.policy_remove":
        fehler = _nachweis(args, by, op, key, peer)
        if fehler:
            return fehler
        ok = policy.remove(key)
        if ok:
            policy.audit(by, op, key, "removed", peer=peer)
        return {"ok": ok}
    return None
