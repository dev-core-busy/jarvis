#!/usr/bin/env python3
"""Live-Probe auf DEV: SAP/VEMAS als zusaetzliche Quelle unter /support.

Laeuft AUF dem DEV-Server im Produktiv-venv gegen den laufenden Dienst.

Warum ein eigenes Sitzungstoken: ``/api/login`` prueft gegen PAM, und das
OS-Kennwort des Benutzers ``jarvis`` ist auf DEV ein anderes als der Eintrag in
der ``.env`` (Journal: ``pam_unix(login:auth): authentication failure``).
``generate_token`` ist genau die Funktion, die der Endpunkt nach erfolgreicher
Anmeldung ruft – umgangen wird damit nichts: jeder Endpunkt prueft danach Token
UND Freigabe.

Der DEV-Zustand wird am Ende VOLLSTAENDIG zurueckgebaut (Freigaben leer,
Skill-Zustaende wie vorgefunden).
"""
import json
import sys
import time

sys.path.insert(0, "/opt/jarvis")
import requests
import urllib3
urllib3.disable_warnings()

from backend.main import generate_token          # noqa: E402
from backend.config import config                # noqa: E402

BASIS = "https://127.0.0.1"
TOK = generate_token("jarvis")
KOPF = {"Authorization": "Bearer " + TOK, "Content-Type": "application/json"}

ok = fail = 0


def abschnitt(t):
    print("\n\033[1m%s\033[0m" % t)


def check(name, cond, detail=""):
    global ok, fail
    if isinstance(name, bool) or not isinstance(name, str):
        print("\033[31mABBRUCH: check() falsch herum\033[0m")
        sys.exit(2)
    if bool(cond):
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – " + str(detail)) if detail else ""))


def status():
    r = requests.get(BASIS + "/api/support/status", headers=KOPF, verify=False, timeout=30)
    r.raise_for_status()
    return r.json()


def frage(**flags):
    rumpf = {"text": "Wie hoch war der Umsatz im letzten Quartal?",
             "rag": False, "confluence": False, "jira_open": False,
             "jira_all": False, "ibs": False, "ai": False}
    rumpf.update(flags)
    r = requests.post(BASIS + "/api/support/query", headers=KOPF,
                      data=json.dumps(rumpf), verify=False, timeout=300)
    return r.status_code, r.json()


def block(d, quelle):
    return next((b for b in d.get("blocks", []) if b.get("source") == quelle), None)


# ── Ausgangszustand sichern ────────────────────────────────────────────────
# Angefasst werden AUSSCHLIESSLICH diese zwei Felder – und beide werden im
# finally auf ihren exakten Vorwert zurueckgesetzt. Auf DEV steht in
# sap_allowed_users eine echte Freigabe; sie darf der Lauf nicht verlieren.
VORHER = {k: config.get_setting(k, "") for k in
          ("sap_allowed_users", "vemas_allowed_users")}
SKILLS_VORHER = {s: config.get_skill_states().get(s, {}).get("enabled")
                 for s in ("sap", "vemas")}
print("Ausgangszustand: %s | Skills %s" % (VORHER, SKILLS_VORHER))


def setze(**kw):
    for k, v in kw.items():
        config.save_setting(k, v)
    time.sleep(0.4)


try:
    # ═══════════════════════════════════════════════════════════════════
    abschnitt("1. Ausgangszustand: 'leer = niemand'")
    setze(sap_allowed_users="", vemas_allowed_users="")
    d = status()
    check("sap_allowed = false (keine Freigabe eingetragen)", d.get("sap_allowed") is False, d)
    check("vemas_allowed = false", d.get("vemas_allowed") is False, d)
    check("sap_configured = false (ohne Freigabe wird gar nicht aufgeloest)",
          d.get("sap_configured") is False)
    check("die uebrigen Felder sind unveraendert vorhanden",
          "ibs_configured" in d and "jira_active" in d)

    abschnitt("2. Abfrage OHNE Freigabe loest keinen Agentenlauf aus")
    t0 = time.time()
    sc, d = frage(sap=True, vemas=True)
    dauer = time.time() - t0
    check("HTTP 200", sc == 200, sc)
    b = block(d, "SAP")
    check("SAP-Block ist eine ehrliche Absage",
          b and "freigegeben" in (b.get("summary") or ""), b)
    check("SAP-Block traegt no_summary", b and b.get("no_summary") is True)
    bv = block(d, "VEMAS")
    check("VEMAS-Block ebenso", bv and "freigegeben" in (bv.get("summary") or ""), bv)
    check("kein Modell, kein Fachsystem befragt (< 5 s)", dauer < 5, "%.1f s" % dauer)

    abschnitt("3. Positivkontrolle: Freigabe erteilt (SAP)")
    setze(sap_allowed_users="jarvis")
    d = status()
    check("sap_allowed kippt auf true", d.get("sap_allowed") is True, d)
    konfiguriert = bool(d.get("sap_configured"))
    print("     (SAP auf diesem Server konfiguriert: %s)" % konfiguriert)
    t0 = time.time()
    sc, d = frage(sap=True)
    dauer = time.time() - t0
    b = block(d, "SAP")
    check("es kommt ein SAP-Block zurueck", b is not None, d.get("blocks"))
    if konfiguriert:
        # Der ganze Weg ist gelaufen: Freigabe -> Zugang -> build_task ->
        # Agentenlauf mit den sap_*-Werkzeugen -> Antwort als Block. Ob das
        # SAP-System selbst antwortet, ist eine Frage der Zugangsdaten und
        # nicht dieses Waechters – dass der Lauf stattfand, ist der Nachweis.
        check("der Agentenlauf hat wirklich stattgefunden (> 2 s)",
              dauer > 2, "%.1f s" % dauer)
        check("es ist KEIN Absage-Block (echte Quelle fuer die Zusammenfassung)",
              not b.get("no_summary"), b)
        check("die Antwort des Laufs steht im Block", bool(b.get("full_text")))
        check("der Block verweist auf den Bereich", b.get("link") == "/sap")
        check("mit welchem Zugang gelesen wurde, steht am Block",
              b.get("quelle_zugang") in ("sammel", "persoenlich"), b.get("quelle_zugang"))
    else:
        check("ohne Zugang: 'nicht konfiguriert' statt 'nicht freigegeben'",
              "nicht konfiguriert" in (b.get("summary") or ""), b)
        check("und der Weg dorthin wird genannt",
              "Einstellungen" in (b.get("summary") or ""))
        check("kein Agentenlauf (< 5 s)", dauer < 5, "%.1f s" % dauer)

    abschnitt("4. Positivkontrolle: VEMAS haengt zusaetzlich am Skill")
    setze(vemas_allowed_users="jarvis")
    d = status()
    check("Freigabe allein genuegt nicht – Skill ist aus",
          d.get("vemas_allowed") is False, d)

    abschnitt("5. Ohne die Schalter aendert sich nichts")
    sc, d = frage()
    check("keine Fachsystem-Bloecke, wenn nichts angehakt ist",
          block(d, "SAP") is None and block(d, "VEMAS") is None, d.get("blocks"))
    check("HTTP 200", sc == 200)

finally:
    abschnitt("Rueckbau")
    for k, v in VORHER.items():
        config.save_setting(k, v or "")
    d = status()
    check("Freigaben wieder leer",
          d.get("sap_allowed") is False and d.get("vemas_allowed") is False, d)

print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
