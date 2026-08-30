#!/usr/bin/env python3
"""Waechter: persoenlicher Jira-Zugang (backend/jira_accounts.py).

**Vorgabe 2026-08-28:** der in *Einstellungen → Jira* hinterlegte Token ist ab
jetzt nur noch der RUECKFALL. Wer unter *Mein Jira-Zugang* einen eigenen
hinterlegt, arbeitet damit – in der Erweiterung, im Chat und in der
Ticketsuche.

Geprueft wird die AUFLOESUNG (welcher Token gilt fuer welchen Lauf), die
Feld-Whitelist, die Geheimhaltung des Tokens und die Verdrahtung der vier
Konstruktionsstellen. Der Rechte-Namensraum haengt an
``tests/test_endpoint_rights.py``.

⚠ SANDKASTEN MIT EXIT 2. Konten- und Schluesseldatei werden umgebogen; zeigt
eine davon nicht ins Wegwerf-Verzeichnis, bricht der Lauf mit **2** ab – ein
Test, der die echte ``data/jira_accounts.json`` ueberschreibt, nimmt einem
Benutzer im Betrieb seinen Zugang.

Lauf:  python3 tests/test_jira_accounts.py
"""

import json
import re
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(text, bed, extra=""):
    """``check(Beschreibung, Bedingung)`` – **in DIESER Reihenfolge.**

    Der Abbruch bei vertauschten Argumenten ist kein Luxus: eine nicht-leere
    Zeichenkette ist wahr, ein vertauschter Aufruf meldet also OK, ohne die
    Bedingung je auszuwerten (am 2026-08-28 in `test_jira_vorlagen.py` fuer
    57 Aufrufe genau so passiert)."""
    global _ok, _fail
    if not isinstance(text, str):
        print("ABBRUCH: check() vertauscht – erst die Beschreibung, dann die "
              "Bedingung (bekam %r)" % (text,))
        sys.exit(2)
    if bed:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, (" – %s" % extra) if extra else ""))


def section(t):
    print("\n═══ %s" % t)


# ── Stub, damit der echte config-Import die Live-settings.json nicht anfasst ──
_SKILLCFG = {"jira": {"config": {"base_url": "https://jira.firma.de",
                                 "api_token": "SAMMEL-TOKEN"}}}
if "backend.config" not in sys.modules:
    _cfg = types.ModuleType("backend.config")

    class _C:
        def get_skill_states(self):
            return _SKILLCFG

        def get_setting(self, k, d=None):
            return d

    _cfg.config = _C()
    sys.modules["backend.config"] = _cfg

from backend import jira_accounts as ja  # noqa: E402

# ── Sandkasten ───────────────────────────────────────────────────────────────
_tmp = tempfile.mkdtemp(prefix="jiraacc-test-")
ja.DATA_DIR = Path(_tmp)
ja.KONTEN_DATEI = Path(_tmp) / "jira_accounts.json"
ja.SCHLUESSEL_DATEI = Path(_tmp) / ".jirakey"
for _n in ("KONTEN_DATEI", "SCHLUESSEL_DATEI", "DATA_DIR"):
    if not str(getattr(ja, _n)).startswith(_tmp):
        print("ABBRUCH: Sandkasten greift nicht – %s = %s" % (_n, getattr(ja, _n)))
        sys.exit(2)

try:
    import cryptography  # noqa: F401
except Exception:
    print("ABBRUCH: 'cryptography' fehlt – ohne sie ist das Modul nicht pruefbar.")
    sys.exit(2)


def frisch():
    if ja.KONTEN_DATEI.exists():
        ja.KONTEN_DATEI.unlink()


# ═════════════════════════════════════════════════════════════════════════════
section("1) Ohne eigenen Token gilt der Sammelzugang")
# ═════════════════════════════════════════════════════════════════════════════
frisch()
r = ja.aufloesen("alice")
check("Quelle ist der Sammelzugang", r["quelle"] == ja.QUELLE_SAMMEL, r["quelle"])
check("und der Client traegt dessen Token",
      r["client"].token == "SAMMEL-TOKEN", r["client"].token)
check("ohne eigenen Zugang gibt es keinen Hinweis – es ist der Normalfall",
      r["hinweis"] == "", r["hinweis"])
check("hat_zugang() sagt nein", ja.hat_zugang("alice") is False)

# ═════════════════════════════════════════════════════════════════════════════
section("2) Mit eigenem Token gilt DIESER – das ist der ganze Punkt")
# ═════════════════════════════════════════════════════════════════════════════
ja.speichern("alice", {"api_token": "ALICE-PAT"})
r = ja.aufloesen("alice")
check("Quelle ist der persoenliche Zugang",
      r["quelle"] == ja.QUELLE_PERSOENLICH, r["quelle"])
check("der Client traegt ALICES Token, nicht den des Servers",
      r["client"].token == "ALICE-PAT", r["client"].token)
check("die ADRESSE kommt weiterhin vom Administrator",
      r["client"].base == "https://jira.firma.de", r["client"].base)
check("ein anderer Benutzer bleibt beim Sammelzugang",
      ja.aufloesen("bob")["client"].token == "SAMMEL-TOKEN")

# ═════════════════════════════════════════════════════════════════════════════
section("3) Der Token verlaesst den Server NIE")
# ═════════════════════════════════════════════════════════════════════════════
info = ja.zugang_info("alice")
flach = json.dumps(info, ensure_ascii=False)
check("zugang_info nennt den Token nicht", "ALICE-PAT" not in flach, flach[:200])
check("auch nicht maskiert – es gibt nur ein Ja/Nein",
      info.get("token_gesetzt") is True and not any(
          isinstance(v, str) and "*" in v for v in info.values()))
check("die Adresse wird dagegen ANGEZEIGT (der Benutzer muss sie kennen)",
      info.get("basis_url") == "https://jira.firma.de")
roh = ja.KONTEN_DATEI.read_text(encoding="utf-8")
check("und in der Datei liegt er verschluesselt, nicht im Klartext",
      "ALICE-PAT" not in roh, roh[:160])

# ═════════════════════════════════════════════════════════════════════════════
section("4) Feld-Whitelist: die ADRESSE darf der Benutzer nicht setzen")
# ═════════════════════════════════════════════════════════════════════════════
# Ein freies Adressfeld waere eine SSRF-Flaeche ohne Gegenwert – es gibt genau
# ein Haus-Jira. Bewusster Unterschied zu sap_accounts (dort mit Freigabeliste).
check("base_url steht NICHT in AENDERBAR", "base_url" not in ja.AENDERBAR,
      str(ja.AENDERBAR))
for feld in ("base_url", "org_field", "benutzer_norm", "letzter_erfolg"):
    try:
        ja.speichern("alice", {feld: "x"})
        check("Feld %r wird abgewiesen" % feld, False)
    except ja.JiraKontoFehler as e:
        check("Feld %r wird abgewiesen" % feld, True)
        if feld == "base_url":
            check("und die Meldung nennt den Weg (Administrator)",
                  "Administrator" in str(e), str(e))
check("die Adresse blieb unveraendert",
      ja.aufloesen("alice")["client"].base == "https://jira.firma.de")

# ═════════════════════════════════════════════════════════════════════════════
section("5) Leeres Token-Feld heisst UNVERAENDERT, nicht 'loeschen'")
# ═════════════════════════════════════════════════════════════════════════════
# Sonst ueberschriebe ein Klick auf den Haken "verwenden" den Token mit einem
# Leerstring – derselbe Fehler, der beim Postfach und beim Lizenz-Dienstkonto
# behoben wurde.
ja.speichern("alice", {"aktiv": True, "api_token": ""})
check("der Token steht noch",
      ja.aufloesen("alice")["client"].token == "ALICE-PAT")
ja.speichern("alice", {"api_token": "ALICE-NEU"})
check("ein gefuelltes Feld ersetzt ihn",
      ja.aufloesen("alice")["client"].token == "ALICE-NEU")

# ═════════════════════════════════════════════════════════════════════════════
section("6) Der Haken 'verwenden' schaltet auf den Sammelzugang zurueck")
# ═════════════════════════════════════════════════════════════════════════════
ja.speichern("alice", {"aktiv": False})
r = ja.aufloesen("alice")
check("inaktiv → Sammelzugang", r["quelle"] == ja.QUELLE_SAMMEL)
check("MIT Hinweis – ein stiller Wechsel waere eine Anzeige ohne Aussage",
      "inaktiv" in r["hinweis"], r["hinweis"])
check("der Token bleibt gespeichert (nur abgeschaltet)",
      ja.zugang_info("alice")["token_gesetzt"] is True)
ja.speichern("alice", {"aktiv": True})
check("wieder an → persoenlicher Zugang",
      ja.aufloesen("alice")["quelle"] == ja.QUELLE_PERSOENLICH)

# ═════════════════════════════════════════════════════════════════════════════
section("7) Der Benutzerschluessel wird normiert")
# ═════════════════════════════════════════════════════════════════════════════
# Ohne Normalisierung haette dieselbe Person je Anmeldeform einen eigenen
# Zugang und wuerde ihren eigenen nicht wiederfinden (Register).
frisch()
ja.speichern("nexus\\Alice", {"api_token": "A-PAT"})
for form in ("alice", "ALICE", "nexus\\alice", "alice@firma.de"):
    check("dieselbe Person unter %r findet ihren Token" % form,
          ja.aufloesen(form)["client"].token == "A-PAT")

# ═════════════════════════════════════════════════════════════════════════════
section("8) Kanal-Kennungen bekommen keinen Zugang")
# ═════════════════════════════════════════════════════════════════════════════
# wa:/tg:/api: sind Telefonnummern und Quellen, keine Personen mit Jira-Konto.
for kennung in ("wa:+4915112345", "tg:99887", "api:Vision-Kamera"):
    try:
        ja.speichern(kennung, {"api_token": "X"})
        check("%r wird abgewiesen" % kennung, False)
    except ja.JiraKontoFehler:
        check("%r wird abgewiesen" % kennung, True)
    check("%r laeuft ueber den Sammelzugang" % kennung,
          ja.aufloesen(kennung)["quelle"] == ja.QUELLE_SAMMEL)

# ═════════════════════════════════════════════════════════════════════════════
section("9) Ohne Adresse nuetzt der beste Token nichts – und das wird gesagt")
# ═════════════════════════════════════════════════════════════════════════════
frisch()
ja.speichern("alice", {"api_token": "A-PAT"})
_SKILLCFG["jira"]["config"]["base_url"] = ""
r = ja.aufloesen("alice")
check("ohne Adresse gibt es keinen persoenlichen Zugang",
      r["quelle"] == ja.QUELLE_SAMMEL)
check("und der Hinweis nennt den Ort, an dem sie fehlt",
      "Einstellungen" in r["hinweis"] and "Adresse" in r["hinweis"], r["hinweis"])
check("die Oberflaeche erfaehrt es ebenfalls",
      ja.zugang_info("alice")["server_konfiguriert"] is False)
_SKILLCFG["jira"]["config"]["base_url"] = "https://jira.firma.de"

# ═════════════════════════════════════════════════════════════════════════════
section("10) Loeschen stellt den Sammelzugang wieder her")
# ═════════════════════════════════════════════════════════════════════════════
check("loeschen() meldet Erfolg", ja.loeschen("alice") is True)
check("danach gilt wieder der Sammelzugang",
      ja.aufloesen("alice")["client"].token == "SAMMEL-TOKEN")
check("ein zweites Loeschen meldet ehrlich 'nichts da'",
      ja.loeschen("alice") is False)

# ═════════════════════════════════════════════════════════════════════════════
section("11) Der ContextVar ist die EINZIGE Quelle des Benutzers")
# ═════════════════════════════════════════════════════════════════════════════
# Kaeme er aus einem Werkzeug-Argument, koennte das Modell (und damit eine
# Prompt-Injektion) waehlen, mit wessen Token es arbeitet.
frisch()
ja.speichern("alice", {"api_token": "A-PAT"})
tok = ja.current_jira_user.set("alice")
try:
    check("aufloesen() ohne Argument nimmt den ContextVar",
          ja.client_fuer_lauf().token == "A-PAT")
finally:
    ja.current_jira_user.reset(tok)
check("ausserhalb eines Laufs gilt der Sammelzugang",
      ja.client_fuer_lauf().token == "SAMMEL-TOKEN")

SKILL = (ROOT / "skills" / "jira" / "main.py").read_text(encoding="utf-8")
schemata = re.findall(r'"([a-z_]*(?:benutzer|user|zugang|token|konto)[a-z_]*)"\s*:\s*\{',
                      SKILL)
check("kein jira_*-Werkzeug hat ein Benutzer-/Token-Feld im Schema",
      not schemata, str(schemata))

# ═════════════════════════════════════════════════════════════════════════════
section("12) Alle vier Konstruktionsstellen sind umgestellt")
# ═════════════════════════════════════════════════════════════════════════════
# Waere nur eine umgestellt, lieferten Chat und Erweiterung verschiedene
# Tickets – und niemand koennte erklaeren, warum.
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
ASSIST = (ROOT / "backend" / "jira_assist.py").read_text(encoding="utf-8")
AGENT = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")

check("skills/jira/main.py::_client geht ueber jira_accounts",
      "jira_accounts" in SKILL and "client_fuer_lauf" in SKILL)
check("jira_assist::_client nimmt einen Benutzer entgegen",
      "def _client(user" in ASSIST, )
check("und ticket_laden reicht ihn durch",
      "_client(user)" in ASSIST and "ticket_laden(key, user)" in ASSIST)
check("main.py::_jira_client nimmt einen Benutzer entgegen",
      "def _jira_client(user" in MAIN)
check("und die Endpunkte geben ihn mit",
      MAIN.count("_jira_client(user)") >= 6,
      str(MAIN.count("_jira_client(user)")))
check("die health-Route fragt den Zugang DIESES Benutzers ab",
      'jira_accounts.aufloesen(user)["client"].configured' in MAIN)
check("agent.py setzt den ContextVar je Werkzeug-Aufruf",
      "current_jira_user" in AGENT)
check("und nimmt ihn im finally zurueck (sonst haengt er am naechsten Lauf)",
      "_jcv.reset(_j_token)" in AGENT)

# ═════════════════════════════════════════════════════════════════════════════
section("13) Die Dateien stehen in ALLEN vier Sperrlisten")
# ═════════════════════════════════════════════════════════════════════════════
# jira_accounts.json + .jirakey ergeben zusammen die Klartext-Token; ein PAT
# traegt die vollen Rechte seines Besitzers.
SBX = (ROOT / "backend" / "sandbox.py").read_text(encoding="utf-8")
from backend import sandbox  # noqa: E402
check("data/jira_accounts.json in _APP_DENY_REL",
      "data/jira_accounts.json" in sandbox._APP_DENY_REL)
check("data/.jirakey in _APP_DENY_REL",
      "data/.jirakey" in sandbox._APP_DENY_REL)
check("data/jira_accounts.json in PRIVATE_FILES (0640)",
      "data/jira_accounts.json" in sandbox.PRIVATE_FILES)
check("data/.jirakey in PRIVATE_FILES_STRENG (0600)",
      "data/.jirakey" in sandbox.PRIVATE_FILES_STRENG)
check("beide im SHELL_SECRET_PATHS-Muster",
      "jira_accounts" in SBX and r"\.jirakey" in SBX)

# ═════════════════════════════════════════════════════════════════════════════
section("14) Die Oberflaeche: zwei Container, Zugang oben")
# ═════════════════════════════════════════════════════════════════════════════
HTML = (ROOT / "frontend" / "jira_addon.html").read_text(encoding="utf-8")
JS = (ROOT / "frontend" / "js" / "jira_addon.js").read_text(encoding="utf-8")
PORTAL = (ROOT / "frontend" / "portal.html").read_text(encoding="utf-8")

check("es gibt einen Container 'Mein Jira-Zugang'", 'id="ja-sect-account"' in HTML)
check("und einen Container 'Browser-Plugin'", 'id="ja-sect-plugin"' in HTML)
check("der Zugang steht OBERHALB des Plugin-Containers",
      HTML.index('id="ja-sect-account"') < HTML.index('id="ja-sect-plugin"'))
# ALLE bisherigen Karten liegen im Plugin-Container – keine darf davor haengen
# geblieben sein.
_a = HTML.index('id="ja-sect-plugin"')
check("keine ja-card steht ausserhalb (vor) des Plugin-Containers",
      'class="ja-card"' not in HTML[:_a], HTML[:_a][-120:])
# ⚠ GEPRUEFT WIRD DIE EIGENSCHAFT, NICHT DIE ANZAHL. Hier stand bis 2026-08-30
# `== 7`. Beim Ergaenzen der Karte "Fenster oder Seitenleiste" meldete der
# Waechter daraufhin einen Fehler, den es nicht gab – eine feste Zahl in einem
# Test ist eine Zeitbombe (Register). Die Aussage, auf die es ankommt: JEDE
# Karte liegt im Plugin-Container, und es sind ueberhaupt welche da.
_karten = HTML[_a:].count('class="ja-card"')
check("und im Container liegen ALLE Karten der Anleitung",
      _karten == HTML.count('class="ja-card"') and _karten >= 7,
      "%d im Container / %d gesamt" % (_karten, HTML.count('class="ja-card"')))

# Geprueft wird der SICHTBARE Titel der Kachel, nicht das Vorkommen der
# Zeichenkette im ganzen File: "Jira-Assistent" steht dort weiterhin in zwei
# Kommentaren, die die Umbenennung ERKLAEREN. Ein Waechter, der seine eigene
# Begruendung mitliest, meldet einen Fehler, den es nicht gibt (Register).
_kachel = re.search(r'<div class="pt-card-title" data-i18n="portal\.card_jiraassist">'
                    r'([^<]*)</div>', PORTAL)
check("die Kachel traegt einen Titel", _kachel is not None)
check("und er heisst 'Jira'", bool(_kachel) and _kachel.group(1).strip() == "Jira",
      _kachel.group(1) if _kachel else "")
I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
check("auch in DE und EN – der Rueckfall im Markup allein genuegt nicht",
      I18N.count("'portal.card_jiraassist':       'Jira',") == 2,
      str(I18N.count("'portal.card_jiraassist':       'Jira',")))
check("die Kachel-Id bleibt (sie haengt an permissions.jira_assist)",
      'id="pt-card-jiraassist"' in PORTAL)
check("das Token-Feld ist ein Kennwortfeld", 'id="ja-acc-token" type="password"' in HTML)
check("das Serverfeld ist NUR Anzeige",
      'id="ja-acc-server" type="text" readonly' in HTML)
check("der Zugang wird geladen, auch wenn der Container zu ist",
      "accLaden();" in JS)
# Geschnitten wird der HANDLER, nicht ein Fenster von n Zeichen: eine feste
# Zahl ist eine Zeitbombe, die beim naechsten Kommentar im Handler zuschlaegt
# und einen Fehler meldet, den es nicht gibt (Register).
_lc = JS.split("addEventListener('jarvis-lang-changed'")
check("es gibt einen Sprachwechsel-Handler", len(_lc) == 2)
_body = _lc[1].split("\n        });")[0] if len(_lc) == 2 else ""
check("die gerenderte Pille folgt dem Sprachwechsel",
      "accZeichnen()" in _body, _body[-120:])
check("Fremdtext geht per textContent ins DOM, nie per innerHTML",
      "innerHTML" not in JS.split("function accZeichnen")[1].split("async function accLaden")[0])


# ═════════════════════════════════════════════════════════════════════════════
section("15) Der Admin-Ueberblick hat einen Aufrufer und gibt keinen Token her")
# ═════════════════════════════════════════════════════════════════════════════
# Ein Endpunkt ohne Aufrufer ist toter Code – und ein Reiter, der die Frage
# "warum sieht der andere andere Tickets" nicht beantworten kann, laesst sie
# im Support landen.
SETTINGS = (ROOT / "frontend" / "settings.html").read_text(encoding="utf-8")
JIRAJS = (ROOT / "frontend" / "js" / "jira.js").read_text(encoding="utf-8")
APPJS = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")

check("der Abschnitt liegt im Jira-Reiter", 'id="ji-sect-acc"' in SETTINGS)
check("und ist klappbar verdrahtet (sonst laesst er sich nicht schliessen)",
      "ji-sect-acc-hdr" in APPJS)
check("jira.js ruft den Endpunkt", "/api/jira/admin/accounts" in JIRAJS)
check("und zwar aus onShow – ein Abschnitt, der nur beim Reiter-Klick laedt, "
      "bleibt auf 'Laedt…' stehen",
      "this.loadZugaenge();" in JIRAJS.split("onShow: function")[1].split("},")[0])
_endp = MAIN.split('@app.get("/api/jira/admin/accounts")')[1].split("@app.")[0]
check("der Endpunkt ist Administratoren vorbehalten",
      "require_local_auth" in _endp)
check("und gibt WEDER Token NOCH Adresse heraus",
      "token" not in _endp.split('out.append(')[1].split("})")[0]
      and "basis_url" not in _endp)

print("\n%d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
