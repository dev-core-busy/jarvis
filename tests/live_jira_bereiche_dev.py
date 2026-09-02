#!/usr/bin/env python3
"""LIVE-Probe auf DEV: Werkzeug-Bereiche des Jira-Assistenten.

Laeuft AUF DEM SERVER im Produktiv-venv gegen den laufenden Dienst, ein echtes
Jira und das echte Modell. Gemessen wird, was ein Waechter nicht kann: ob der
Agentenlauf wirklich ein Werkzeug benutzt (Tool-Audit-Log) und ob ohne Freigabe
wirklich keiner startet.

⚠ SIE VERAENDERT DEN DEV-ZUSTAND und stellt ihn am Ende wieder her:
Freigabe-Feld der Skill-Config und die angelegte Testvorlage. Der VORGEFUNDENE
Wert wird gesichert, nicht ein geratener Leerwert – eine Wiederherstellung gegen
einen erratenen Ausgangsstand beweist nichts (Register, Vorfall 2026-08-30).

Aufruf auf DEV:  cd /opt/jarvis && ./venv/bin/python tests/live_jira_bereiche_dev.py
"""
import json
import ssl
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")

BASIS = "https://127.0.0.1"
_ok = _fail = 0


def check(bed, text, extra=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, (" – %s" % extra) if extra else ""))


def ruf(pfad, methode="GET", rumpf=None, token=""):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if daten:
        r.add_header("Content-Type", "application/json")
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with urllib.request.urlopen(r, context=ctx, timeout=300) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:  # noqa: BLE001
            return e.code, {}


# ── Token wie der Endpunkt nach erfolgreicher Anmeldung ────────────────────
# Umgangen wird damit nichts: jeder Endpunkt prueft danach Token UND Freigabe.
from backend import main as bm                                  # noqa: E402
from backend import jira_assist as ja                           # noqa: E402
from backend.config import config                               # noqa: E402

USER = "andreas.bender"
TOKEN = bm.generate_token(USER)
ADMIN = bm.generate_token("jarvis")

print("═══ 0) Ausgangszustand sichern")
_st = config.get_skill_states().get("jira", {}) or {}
VORHER = (_st.get("config", {}) or {}).get(ja.FREIGABE_FELD)
print("  vorgefundenes %s: %r" % (ja.FREIGABE_FELD, VORHER))
check(bm._is_admin_user("jarvis"), "der lokale jarvis ist Administrator")

TESTVORLAGE = None


def aufraeumen():
    from backend import jira_vorlagen as jv
    sm = bm._get_skill_manager()
    if VORHER is None:
        # Das Feld war NICHT gesetzt und wird auch nicht mit "" hinterlassen –
        # sonst bleibt eine Spur, die niemand erklaeren kann. `update_skill_config`
        # kann nur MERGEN, ein Schluessel muss deshalb direkt entfernt werden.
        st = config.get_skill_states().get("jira", {}) or {}
        cfg = dict(st.get("config", {}) or {})
        cfg.pop(ja.FREIGABE_FELD, None)
        config.save_skill_state("jira", {"config": cfg})
    else:
        sm.update_skill_config("jira", {ja.FREIGABE_FELD: VORHER})
    if TESTVORLAGE:
        jv.loeschen(USER, TESTVORLAGE, False)


try:
    # ══════════════════════════════════════════════════════════════════════
    print("\n═══ 1) Vorgabe: keine Bereiche, kein Agent")
    # ══════════════════════════════════════════════════════════════════════
    s, d = ruf("/api/jira/admin/areas", "POST", {"bereiche": []}, ADMIN)
    check(s == 200 and d.get("bereiche") == [], "Freigabe leeren geht", str(d))
    check(ja.freigegebene_bereiche() == [], "und wirkt sofort im Modul")

    s, d = ruf("/api/jira/assist/vorlagen?lang=de", token=TOKEN)
    check(s == 200 and d.get("ok"), "GET /vorlagen antwortet", str(s))
    kat = d.get("bereiche") or []
    check(len(kat) == len(ja.BEREICHE), "der Katalog kommt mit", str(len(kat)))
    check(all(not b["freigegeben"] for b in kat), "und nichts ist freigegeben")
    check(all(b.get("name") and b.get("hinweis") for b in kat),
          "Name und Hinweis kommen vom Server")

    s, d = ruf("/api/jira/assist/health", token=TOKEN)
    check(s == 200 and d.get("assist_bereiche") == [],
          "health meldet: keine Bereiche", str(d.get("assist_bereiche")))

    # Eine Vorlage MIT Bereich darf jetzt gar nicht gespeichert werden.
    s, d = ruf("/api/jira/assist/vorlagen", "POST",
               {"name": "Live-Probe", "text": "Kurz.", "bereiche": ["wissen"]}, TOKEN)
    check(s == 400 and "freigeschaltet" in (d.get("error") or ""),
          "ohne Freigabe wird eine Vorlage mit Bereich abgewiesen", str(d))

    # ══════════════════════════════════════════════════════════════════════
    print("\n═══ 2) Freigabe setzen – NUR das eine Feld")
    # ══════════════════════════════════════════════════════════════════════
    vor_cfg = dict((config.get_skill_states().get("jira", {}) or {}).get("config", {}) or {})
    s, d = ruf("/api/jira/admin/areas", "POST",
               {"bereiche": ["wissen", "unsinn"]}, ADMIN)
    check(s == 200 and d.get("bereiche") == ["wissen"],
          "unbekannte Kennungen fallen heraus", str(d))
    nach_cfg = (config.get_skill_states().get("jira", {}) or {}).get("config", {}) or {}
    check(nach_cfg.get("base_url") == vor_cfg.get("base_url")
          and nach_cfg.get("api_token") == vor_cfg.get("api_token"),
          "der Jira-Zugang hat den Schreibvorgang UEBERLEBT")

    s, d = ruf("/api/jira/assist/health", token=TOKEN)
    check([b["id"] for b in (d.get("assist_bereiche") or [])] == ["wissen"],
          "health nennt jetzt 'wissen' – die Anleitung sagt die Wahrheit")

    # DER TEXT VERLANGT DAS NACHSCHLAGEN. Ohne diese Positivkontrolle ist
    # "kein Werkzeug-Aufruf" nicht von "Werkzeuge nicht verdrahtet" zu
    # unterscheiden – der Prompt sagt ausdruecklich, nur bei Bedarf
    # nachzuschlagen, und bei einem klaren Ticket ist das richtig.
    s, d = ruf("/api/jira/assist/vorlagen", "POST",
               {"name": "Live-Probe Bereiche",
                "text": ("Fasse kurz zusammen. Schlage dazu ZWINGEND in der "
                         "Wissensdatenbank nach, ob es zu diesem Thema eigene "
                         "Unterlagen gibt, und sage ausdruecklich, was du dort "
                         "gefunden oder nicht gefunden hast."),
                "bereiche": ["wissen"]}, TOKEN)
    check(s == 200 and d.get("ok"), "die Vorlage laesst sich jetzt speichern", str(d))
    TESTVORLAGE = (d.get("vorlage") or {}).get("id")
    check((d.get("vorlage") or {}).get("bereiche") == ["wissen"],
          "und traegt den Bereich")

    # ══════════════════════════════════════════════════════════════════════
    print("\n═══ 3) Ein ECHTER Lauf – benutzt er wirklich ein Werkzeug?")
    # ══════════════════════════════════════════════════════════════════════
    s, d = ruf("/api/jira/search?limit=1&q=", token=ADMIN)
    treffer = (d.get("results") or [])
    if not treffer:
        check(False, "ein echtes Ticket zum Messen gefunden", str(d)[:200])
        raise SystemExit
    KEY = treffer[0].get("key")
    check(bool(KEY), "echtes Ticket: %s" % KEY)

    from backend import audit_log

    def werkzeuge_seit(t):
        """Die Werkzeug-Aufrufe DIESES Benutzers ab Zeitpunkt ``t``.

        ⚠ GEZAEHLT WIRD UEBER DEN ZEITSTEMPEL, nicht ueber die Laenge der
        Liste: `read_log(limit=N)` liefert hoechstens N Eintraege, und das
        Protokoll auf DEV ist laengst gesaettigt – ein Laengenvergleich ergab
        deshalb IMMER 0, und die Probe meldete "kein Werkzeug", waehrend im
        Protokoll ein `knowledge_search` stand. Eine Messung, die immer
        dasselbe sagt, ist keine.
        """
        return [e.get("tool") for e in (audit_log.read_log(limit=200) or [])
                if int(e.get("ts") or 0) >= int(t)]

    t0 = time.time()
    s, d = ruf("/api/jira/assist", "POST",
               {"key": KEY, "modus": "zusammenfassung", "lang": "de",
                "vorlage": TESTVORLAGE,
                # POSITIVKONTROLLE: der Zusatzwunsch verlangt das Nachschlagen
                # ausdruecklich. Ohne ihn ist "kein Werkzeug-Aufruf" nicht von
                # "Werkzeuge nicht verdrahtet" zu unterscheiden – der Prompt
                # sagt selbst, nur bei Bedarf nachzuschlagen, und bei einem
                # klaren Ticket ist genau das richtig.
                "hinweis": ("Suche vorher in der Wissensdatenbank nach dem "
                            "Begriff \"Urlaubsantrag\" und schreibe in einem "
                            "Satz, was du dort gefunden hast.")}, TOKEN)
    dauer = time.time() - t0
    check(s == 200 and d.get("ok"), "der Lauf kommt durch (%.1f s)" % dauer, str(d)[:300])
    check(d.get("bereiche") == ["wissen"],
          "das Ergebnis nennt den wirksamen Bereich", str(d.get("bereiche")))
    txt = d.get("text") or ""
    check(len(txt) > 50, "es kam eine Zusammenfassung (%d Zeichen)" % len(txt))
    check("[[ERGEBNIS" not in txt, "keine Ergebnis-Marke im Text", txt[:120])
    check("[[ABGLEICH" not in txt, "und keine Abgleich-Marke")

    namen = werkzeuge_seit(t0 - 1)
    check("knowledge_search" in namen,
          "der Lauf hat WIRKLICH nachgeschlagen (knowledge_search im Audit-Log)",
          str(namen))
    verboten = [n for n in namen if n and n not in ja.werkzeuge_fuer(["wissen"])]
    check(not verboten, "und KEIN Werkzeug ausserhalb der Whitelist", str(verboten))
    print("      Werkzeuge dieses Laufs: %s" % (namen or "(keins)"))

    # ══════════════════════════════════════════════════════════════════════
    print("\n═══ 4) Gegenprobe: Freigabe zurueck – kein Agent mehr")
    # ══════════════════════════════════════════════════════════════════════
    s, d = ruf("/api/jira/admin/areas", "POST", {"bereiche": []}, ADMIN)
    check(s == 200, "Freigabe zurueckgenommen")
    time.sleep(3.2)          # die Drosselung des Assistenten
    t0 = time.time()
    s, d = ruf("/api/jira/assist", "POST",
               {"key": KEY, "modus": "zusammenfassung", "lang": "de",
                "vorlage": TESTVORLAGE}, TOKEN)
    check(s == 200 and d.get("ok"), "der Lauf kommt weiter durch (%.1f s)"
          % (time.time() - t0), str(d)[:200])
    check(d.get("bereiche") == [],
          "aber OHNE Bereiche – die Vorlage traegt 'wissen' noch, es wirkt nicht",
          str(d.get("bereiche")))
    check(werkzeuge_seit(t0) == [],
          "und es lief KEIN einziger Werkzeug-Aufruf",
          str(werkzeuge_seit(t0)))

finally:
    print("\n═══ 5) Ausgangszustand wiederherstellen")
    try:
        aufraeumen()
        jetzt = (config.get_skill_states().get("jira", {}) or {}).get("config", {}) or {}
        check(jetzt.get(ja.FREIGABE_FELD) == VORHER
              or (VORHER is None and ja.FREIGABE_FELD not in jetzt),
              "Freigabe-Feld wieder im Ausgangszustand",
              repr(jetzt.get(ja.FREIGABE_FELD)))
        from backend import jira_vorlagen as jv
        rest = [v for v in jv.liste(USER).get("eigene", [])
                if str(v.get("name", "")).startswith("Live-Probe")]
        check(not rest, "keine Testvorlage zurueckgeblieben", str(rest))
    except Exception as e:  # noqa: BLE001
        check(False, "Aufraeumen lief", str(e))

print("\n%d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
