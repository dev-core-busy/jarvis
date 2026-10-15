#!/usr/bin/env python3
"""Live auf DEV: BSI M5 – Hauptschluessel ausserhalb data/, settings.json
verpackt, Klartext nur nach erneuter Anmeldung.

Gefahren wird gegen den LAUFENDEN Dienst (HTTPS) und die echte Ablage:
  A. Ablage: Hauptschluessel /etc/jarvis/geheimnis.key fuer den Dienstbenutzer
     NICHT lesbar, Drop-in mit LoadCredential vorhanden, alle Modulschluessel
     in data/ verpackt, in settings.json kein Geheimfeld im Klartext.
  B. Der Dienst meldet den Tresor aktiv mit Quelle "systemd-Credential".
  C. Die Formulare bekommen nichts: Skill-Config, Agent-Key-Liste, WebDAV-Status.
  D. Klartext-Wege ohne Bestaetigung: 403 + reauth (reveal, Profil-Key, Agent-Key).
  E. Ein falscher CODE gibt nichts frei; der richtige (TOTP aus auth_state)
     schon – danach kommt der Wert. Eine ZWEITE Sitzung desselben Kontos bleibt
     gesperrt.
  F. Positivkontrolle der Entschluesselung: der Dienst erreicht den LLM-Anbieter
     mit dem gespeicherten (verpackten) Schluessel.

⚠ KONTO: das lokale Konto ``jarvis`` (2FA eingerichtet). NICHT das AD-Testkonto
– ein falsches Kennwort dort zaehlt beim Domain-Controller (3 Fehlversuche =
30 min Sperre). Der Fehlfall wird mit einem falschen CODE gemessen, der geht
nie an PAM/AD.

Zustand: die Probe-Sitzungen werden am Ende widerrufen; geschrieben wird nichts.

Aufruf (root): bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_bsi_m5_dev.py
  ⚠ NICHT mehr per `runuser -u jarvis`: ohne den Hauptschluessel (LoadCredential)
  sind .secret_key und die 2FA-Secrets verpackt – ausgestellte Tokens gelten im
  Dienst nicht, und der TOTP-Code liesse sich nicht bilden.
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")

BASIS = "https://127.0.0.1"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
DATA = Path("/opt/jarvis/data")
KONTO = "jarvis"
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s%s" % (label, (" – %s" % str(detail)[:300]) if detail else ""))


def abbruch(text):
    print("NICHT PRUEFBAR: %s" % text)
    sys.exit(2)


def ruf(pfad, token=None, methode="GET", body=None):
    daten = json.dumps(body).encode() if body is not None else (b"" if methode == "POST" else None)
    r = urllib.request.Request(BASIS + pfad, method=methode, data=daten)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if body is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=90) as a:
            roh = a.read()
            st = a.status
    except urllib.error.HTTPError as e:
        roh, st = e.read(), e.code
    try:
        return st, json.loads(roh or b"{}")
    except ValueError:
        return st, {"_roh": roh[:200].decode("utf-8", "replace")}


if os.geteuid() == 0:
    abbruch("als root gestartet – die Probe misst, was der DIENSTBENUTZER sieht (runuser -u jarvis)")

from backend import geheimnis_tresor as T  # noqa: E402

# ── A. Ablage ───────────────────────────────────────────────────────────────
print("A. Ablage")
haupt = Path("/etc/jarvis/geheimnis.key")
try:
    haupt.read_bytes()
    lesbar = True
except PermissionError:
    lesbar = False
except FileNotFoundError:
    abbruch("/etc/jarvis/geheimnis.key fehlt – Broker neu gestartet?")
check(not lesbar, "⚠ der Dienstbenutzer kann den Hauptschluessel NICHT lesen")
dropin = Path("/etc/systemd/system/jarvis.service.d/40-geheimnis.conf")
check(dropin.exists() and "LoadCredential=geheimnis:/etc/jarvis/geheimnis.key" in dropin.read_text(),
      "Drop-in reicht ihn per LoadCredential an den Dienst")
for name in (".mailkey", ".sapkey", ".vemaskey", ".jirakey", ".confluencekey", ".mountkey",
             ".aimousesignkey"):
    p = DATA / name
    if p.exists():
        check(p.read_bytes().startswith(T.PRAEFIX_SCHLUESSEL), "⚠ data/%s ist verpackt" % name)
sk_inhalt = (DATA / ".secret_key").read_text().strip()
check(sk_inhalt.startswith("JGK1:"), "⚠ data/.secret_key (Signierschluessel der Tokens) ist verpackt")
for name in ("auth_state.json", "knowledge_sync.json"):
    p = DATA / name
    if p.exists():
        r = json.loads(p.read_text())
        check(T.klartext_felder(r) == [], "⚠ data/%s: kein Geheimnis im Klartext" % name,
              T.klartext_felder(r))
if T.hauptfernet() is None:
    abbruch("der Hauptschluessel fehlt in DIESEM Prozess – ueber deploy/als_dienst.sh starten")
roh = json.loads((DATA / "settings.json").read_text())
offen = T.klartext_felder(roh)
anzahl = json.dumps(roh).count(T.PRAEFIX_WERT)
check(anzahl >= 3, "Positivkontrolle: settings.json traegt verpackte Werte", anzahl)
check(offen == [], "⚠ settings.json: kein Geheimfeld im Klartext", offen)

# ── Sitzungen ───────────────────────────────────────────────────────────────
from backend import main as M  # noqa: E402
import pyotp  # noqa: E402

st_auth = M._get_user_auth_state(KONTO)
if not (st_auth.get("totp_enabled") and st_auth.get("totp_secret")):
    abbruch("Konto %s hat keine 2FA – Bestaetigung per Code nicht messbar" % KONTO)
TOK = M.generate_token(KONTO, mit_2fa=True)
# ⚠ Eine Sekunde Abstand: zwei Tokens desselben Kontos in derselben Sekunde
# sind IDENTISCH (Zeitstempel + Signatur) – die erste Fassung mass damit
# "zweite Sitzung entsperrt" an ein und derselben Sitzung.
import time  # noqa: E402
time.sleep(1.2)
TOK2 = M.generate_token(KONTO, mit_2fa=True)
M._sitzung.flush()
if TOK == TOK2:
    abbruch("Positivkontrolle: die zweite Sitzung ist keine andere")

try:
    st, d = ruf("/api/auth/bestaetigen", TOK)
    if st != 200:
        abbruch("Positivkontrolle: Sitzung nicht nutzbar (%s %s)" % (st, d))

    # ── B. Dienst ──────────────────────────────────────────────────────────
    print("B. Dienst")
    st, d = ruf("/api/security/geheimnisse", TOK)
    check(st == 200 and d.get("tresor", {}).get("aktiv") is True, "Tresor im Dienst aktiv", d)
    check(d.get("tresor", {}).get("quelle") == "systemd-Credential",
          "⚠ … mit dem Schluessel aus LoadCredential", d.get("tresor"))
    check(d.get("klartext_felder") == [], "… meldet keine Klartext-Felder", d.get("klartext_felder"))

    # ── C. Formulare ───────────────────────────────────────────────────────
    print("C. Formulare bekommen nichts")
    st, d = ruf("/api/skills/jira/config", TOK)
    check(st == 200 and d.get("config", {}).get("api_token") == "", "⚠ Skill-Config: api_token leer", d.get("config", {}).get("api_token"))
    check("api_token" in (d.get("geheim_gesetzt") or []), "… aber als gesetzt gemeldet", d.get("geheim_gesetzt"))
    check(T.PRAEFIX_WERT not in json.dumps(d), "… und kein verpackter Wert im Formular")
    st, d = ruf("/api/agent/keys", TOK)
    check(st == 200 and all(k.get("key") == "" for k in d.get("keys", [])),
          "⚠ Agent-Key-Liste ohne Schluessel", [k.get("key") for k in d.get("keys", [])])
    st, d = ruf("/api/knowledge/webdav/status", TOK)
    check(st in (200, 403) and d.get("password", "") == "", "WebDAV-Status ohne Kennwort", (st, d.get("password")))

    # ── D. ohne Bestaetigung ───────────────────────────────────────────────
    print("D. Klartext ohne Bestaetigung")
    st, d = ruf("/api/secret/reveal", TOK, "POST", {"bereich": "skill", "kennung": "jira:api_token"})
    check(st == 403 and d.get("reauth") is True and "wert" not in d, "⚠ reveal: 403 + reauth", (st, d))
    pid = (M.config.profiles or [{}])[0].get("id", "")
    st, d = ruf("/api/profiles/%s/key" % pid, TOK)
    check(st == 403 and d.get("reauth") is True, "⚠ Profil-Key: 403 + reauth", (st, d))
    st, d = ruf("/api/settings/agentkey", TOK)
    check(st == 403 and d.get("reauth") is True, "⚠ Agent-Key: 403 + reauth", (st, d))

    # ── E. Bestaetigen ─────────────────────────────────────────────────────
    print("E. Bestaetigung")
    richtig = pyotp.TOTP(st_auth["totp_secret"]).now()
    falsch = "%06d" % ((int(richtig) + 500000) % 1000000)
    st, d = ruf("/api/auth/bestaetigen", TOK, "POST", {"code": falsch})
    check(st == 403 and not d.get("ok"), "falscher Code: 403", (st, d))
    st, d = ruf("/api/secret/reveal", TOK, "POST", {"bereich": "skill", "kennung": "jira:api_token"})
    check(st == 403, "⚠ … und danach weiter gesperrt", st)
    st, d = ruf("/api/auth/bestaetigen", TOK, "POST", {"code": richtig})
    check(st == 200 and d.get("ok") is True, "richtiger Code: frei", (st, d))
    st, d = ruf("/api/auth/bestaetigen", TOK)
    check(0 < int(d.get("restzeit_s") or 0) <= 300, "Fenster hoechstens 5 Minuten", d)
    st, d = ruf("/api/secret/reveal", TOK, "POST", {"bereich": "skill", "kennung": "jira:api_token"})
    wert = d.get("wert") or ""
    check(st == 200 and wert and not wert.startswith(T.PRAEFIX_WERT),
          "⚠ danach kommt der GEOEFFNETE Wert", (st, len(wert), wert[:5]))
    st, d = ruf("/api/profiles/%s/key" % pid, TOK)
    check(st == 200 and "api_key" in d, "Profil-Key nach Bestaetigung", st)
    st, d = ruf("/api/secret/reveal", TOK2, "POST", {"bereich": "skill", "kennung": "jira:api_token"})
    check(st == 403 and d.get("reauth") is True, "⚠ eine ZWEITE Sitzung desselben Kontos bleibt gesperrt", st)

    # ── F. Entschluesselung im Betrieb ─────────────────────────────────────
    print("F. Der Dienst benutzt die geoeffneten Werte")
    # Mindestens EIN Profil mit Schluessel muss seinen Anbieter erreichen – ein
    # einzelnes Profil kann aus eigenem Grund scheitern (auf DEV: Gemini 401,
    # Schluessel in OAuth-Form; Laenge vor/nach der Verpackung gleich).
    erreicht = []
    for p in M.config.profiles or []:
        if not p.get("api_key"):
            continue
        st, d = ruf("/api/profiles/%s/test" % p["id"], TOK)
        print("       %s: %s" % (p.get("name"), "erreichbar" if d.get("success") else str(d.get("error"))[:80]))
        if st == 200 and d.get("success") is True:
            erreicht.append(p.get("name"))
    check(bool(erreicht), "⚠ der Dienst erreicht LLM-Anbieter mit den verpackt gespeicherten Schluesseln",
          "keines erreicht")
finally:
    for t in (TOK, TOK2):
        try:
            u, ts, sig = t.split(":", 2)
            M._sitzung.widerrufe(sig, int(ts))
        except Exception as e:  # noqa: BLE001
            print("  (Widerruf: %s)" % e)
    try:
        M._sitzung.flush()
    except Exception:  # noqa: BLE001
        pass

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
