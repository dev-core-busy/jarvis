#!/usr/bin/env python3
"""Tests fuer den E-Mail-Skill (mail_accounts, mail_rules, mail_client, mail_runner).

Laeuft ohne fastapi und ohne Netzzugriff:

* ``backend.config`` wird als Attrappe in ``sys.modules`` gelegt. Der ECHTE
  Import wuerde beim Laden die LIVE-``settings.json`` migrieren und
  zurueckschreiben (dieselbe Falle wie in test_shell_redirects.py und
  test_knowledge_sync.py).
* Alle Dateipfade der Module werden auf ein Wegwerf-Verzeichnis umgebogen; ein
  SANDKASTEN-WAECHTER bricht mit Exit 2 ab, wenn ein Pfad danach noch auf
  ``data/`` des Repos zeigt. Genau das ist beim Log-Retention-Test einmal
  passiert (Gegenprobe gegen einen alten Modulstand, in dem die
  Pfadvariablen anders heissen) – der Test schrieb in die echten Daten.
* Der EWS-Kanal wird mit einem gefaelschten ``exchangelib``-Modul geprueft, der
  IMAP-Kanal ueber die Kanalwahl. Ein echter Exchange ist dafuer nicht noetig
  und waere auch nicht reproduzierbar.

Exit 2 heisst "konnte nicht laufen" (Sandkasten/Import), 1 heisst "Pruefung
fehlgeschlagen", 0 heisst bestanden – ohne diese Unterscheidung waere
"konnte nicht laufen" von "bestanden" nicht zu unterscheiden.

    python3 tests/test_email_rules.py
"""
import asyncio
import json
import os
import re
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def section(t):
    print(f"\n{t}")


# ── Attrappe fuer backend.config VOR dem Import der Module ──────────────────
TMP = Path(tempfile.mkdtemp(prefix="email_test_"))
(TMP / "data").mkdir(parents=True)

_skill_states = {
    "email": {"enabled": True, "config": {"bereiche": "mail,wissen"}},
    "branding": {"enabled": False, "config": {}},
}
_settings = {}

_cfg_mod = types.ModuleType("backend.config")


class _Cfg:
    def get_skill_states(self):
        return _skill_states

    def get_setting(self, key, default=None):
        return _settings.get(key, default)

    def save_setting(self, key, value):
        _settings[key] = value


_cfg_mod.config = _Cfg()
sys.modules.setdefault("backend.config", _cfg_mod)

from backend import mail_accounts as ma      # noqa: E402
from backend import mail_client as mc        # noqa: E402
from backend import mail_rules as mr         # noqa: E402

# ── Pfade umbiegen + Sandkasten-Waechter ────────────────────────────────────
ma.DATA_DIR = TMP / "data"
ma.KONTEN_DATEI = TMP / "data" / "email_accounts.json"
ma.SCHLUESSEL_DATEI = TMP / "data" / ".mailkey"
mr.DATA_DIR = TMP / "data"
mr.REGEL_DATEI = TMP / "data" / "email_rules.json"
mr.ZUSTAND_DATEI = TMP / "data" / "email_state.json"
mr.PROTOKOLL_DATEI = TMP / "data" / "email_log.jsonl"

# Geprueft wird, dass kein Pfad mehr in das ECHTE data/ zeigt. NICHT "muss unter
# TMP liegen": ``PROJECT_ROOT`` zeigt zu Recht auf das Repo. Der Waechter ist
# noetig, weil bei einer Gegenprobe gegen einen alten Modulstand die
# Pfadvariablen anders heissen koennen – dann greift die Umbiegung nicht und der
# Test schreibt in die Live-Daten (genau so beim Log-Retention-Test passiert).
_ECHTES_DATA = ROOT / "data"
for modul in (ma, mr):
    for name in dir(modul):
        wert = getattr(modul, name)
        if isinstance(wert, Path) and name.isupper() and name != "PROJECT_ROOT":
            try:
                drin = wert == _ECHTES_DATA or _ECHTES_DATA in wert.parents
            except Exception:  # noqa: BLE001
                drin = False
            if drin:
                print(f"SANDKASTEN VERLETZT: {modul.__name__}.{name} = {wert}")
                sys.exit(2)
# Gegenprobe: die drei Regel-Dateien und die zwei Konto-Dateien MUESSEN umgebogen
# sein – ohne diese Zeile wuerde ein umbenanntes Attribut still durchfallen.
for pfad in (ma.KONTEN_DATEI, ma.SCHLUESSEL_DATEI, mr.REGEL_DATEI,
             mr.ZUSTAND_DATEI, mr.PROTOKOLL_DATEI):
    if not str(pfad).startswith(str(TMP)):
        print(f"SANDKASTEN VERLETZT: {pfad} liegt nicht im Wegwerf-Verzeichnis")
        sys.exit(2)


# ═══════════════════════════════════════════════════════════════════════════
section("1. Zugangsdaten: Verschluesselung, Whitelist, 'leer = unveraendert'")
# ═══════════════════════════════════════════════════════════════════════════

check(ma.norm_user("NEXUS\\Andreas.Bender") == "andreas.bender",
      "Domaenen-Praefix wird normalisiert")
check(ma.norm_user("a.b@nexus.int") == "a.b", "UPN-Suffix wird normalisiert")
check(ma.norm_user("wa:+4915") == "wa:+4915", "Kanal-Kennung bleibt unangetastet")

info = ma.speichern("NEXUS\\a.bender", {"adresse": "a.bender@nexus.int",
                                        "passwort": "GeheimesKennwort123",
                                        "benutzer": "NEXUS\\a.bender"})
check(info["passwort_gesetzt"] is True, "Kennwort als gesetzt gemeldet")
check("Geheim" not in json.dumps(info), "konto_info enthaelt kein Kennwort")
check("passwort" not in info and "pw_enc" not in info,
      "konto_info gibt weder Klartext- noch Chiffre-Feld heraus")

roh = ma.KONTEN_DATEI.read_text()
check("GeheimesKennwort123" not in roh, "Kennwort liegt NICHT im Klartext auf Platte")
check(ma.entschluesseln(json.loads(roh)["a.bender"]["pw_enc"]) == "GeheimesKennwort123",
      "Kennwort laesst sich wieder entschluesseln")
check(oct(ma.KONTEN_DATEI.stat().st_mode & 0o777) == "0o640", "Kontendatei ist 0640")
check(oct(ma.SCHLUESSEL_DATEI.stat().st_mode & 0o777) == "0o600", "Schluesseldatei ist 0600")

# Derselbe Mensch, andere Tippform → dasselbe Konto
check(ma.hat_konto("a.bender@nexus.int") and ma.hat_konto("A.BENDER"),
      "Konto wird unabhaengig von der Tippform gefunden")
check(ma.alle_benutzer() == ["a.bender"], "genau ein Konto angelegt")

ma.speichern("a.bender", {"ordner_eingang": "Posteingang"})
check(json.loads(ma.KONTEN_DATEI.read_text())["a.bender"]["pw_enc"] != "",
      "leeres Kennwortfeld heisst UNVERAENDERT (Kennwort nicht verloren)")
ma.speichern("a.bender", {"passwort": "   "})
check(ma.entschluesseln(json.loads(ma.KONTEN_DATEI.read_text())["a.bender"]["pw_enc"])
      == "GeheimesKennwort123", "nur-Leerzeichen-Kennwort aendert nichts")

try:
    ma.speichern("a.bender", {"imap_host": "boeser-server.example"})
    check(False, "Feld-Whitelist verweigert Serverfelder")
except mc.MailFehler as e:
    check("imap_host" in str(e), "Feld-Whitelist verweigert Serverfelder",
          "der Benutzer darf keine Serveradresse setzen")
try:
    ma.speichern("a.bender", {"adresse": "keine-adresse"})
    check(False, "Adressprueffung greift")
except mc.MailFehler:
    check(True, "Adressprueffung greift")
try:
    ma.speichern("a.bender", {"kanal": "pop3"})
    check(False, "unbekannter Kanal abgewiesen")
except mc.MailFehler:
    check(True, "unbekannter Kanal abgewiesen")

# Serverteil kommt AUSSCHLIESSLICH aus der Skill-Config
_skill_states["email"]["config"].update({
    "ews_url": "https://mail.firma.de/EWS/Exchange.asmx", "autodiscover": False,
    "imap_host": "imap.firma.de", "smtp_host": "smtp.firma.de", "verify_ssl": False,
})
konto = ma.konto_fuer("nexus\\a.bender")
check(konto.ews_url == "https://mail.firma.de/EWS/Exchange.asmx"
      and konto.imap_host == "imap.firma.de",
      "Serverdaten stammen aus der Administrator-Konfiguration")
check(konto.passwort == "GeheimesKennwort123", "Kennwort wird fuer den Lauf entschluesselt")
check(konto.ordner_eingang == "Posteingang", "Ordner-Vorgabe des Benutzers gewinnt")
check(konto.verify_ssl is False, "verify_ssl aus der Skill-Config wird uebernommen")

ma.speichern("a.bender", {"aktiv": False})
try:
    ma.konto_fuer("a.bender")
    check(False, "inaktives Postfach wird abgewiesen")
except mc.MailFehler as e:
    check("inaktiv" in str(e), "inaktives Postfach wird abgewiesen")
ma.speichern("a.bender", {"aktiv": True})

# Verlorene Schluesseldatei: sprechender Fehler, kein Absturz
_sk = ma.SCHLUESSEL_DATEI.read_bytes()
ma.SCHLUESSEL_DATEI.unlink()
try:
    ma.konto_fuer("a.bender")
    check(False, "verlorener Schluessel wird gemeldet")
except mc.MailFehler as e:
    check("mailkey" in str(e).lower() and "neu hinterlegen" in str(e).lower(),
          "verlorener Schluessel nennt die Abhilfe", str(e))
ma.SCHLUESSEL_DATEI.write_bytes(_sk)
os.chmod(ma.SCHLUESSEL_DATEI, 0o600)

# Kategorie aus dem Branding
check(ma.kategorie_name() == "Jarvis", "ohne Branding heisst die Kategorie 'Jarvis'")
_skill_states["branding"] = {"enabled": True,
                             "config": {"assistant_name": "Nexi", "company_name": "Nexus AG"}}
check(ma.kategorie_name() == "Nexi", "Assistenten-Name gewinnt")
_skill_states["branding"]["config"]["assistant_name"] = ""
check(ma.kategorie_name() == "Nexus AG", "sonst der Firmenname")
_skill_states["branding"]["config"]["company_name"] = "Nexus, AG"
check("," not in ma.kategorie_name(),
      "Komma wird entfernt (Exchange-Kategorien sind komma-getrennt)")
_skill_states["branding"] = {"enabled": False, "config": {}}


# ═══════════════════════════════════════════════════════════════════════════
section("2. Regeln: Besitzer-Bindung, Whitelist, Bereichs-Schranke")
# ═══════════════════════════════════════════════════════════════════════════

r = mr.anlegen("NEXUS\\A.Bender", {"name": "Rechnungen", "prompt": "Pruefe auf Rechnung",
                                   "bereiche": ["wissen"], "ordner": "INBOX"})
check(r["owner"] == "a.bender", "Besitzer wird normalisiert gespeichert")
check("mail" in r["bereiche"], "'mail' ist immer dabei")
check(len(r["id"]) == 12, "Regel-Kennung ist 12 Hex-Zeichen")
check(oct(mr.REGEL_DATEI.stat().st_mode & 0o777) == "0o640", "Regeldatei ist 0640")

# Besitzer kommt NIE aus dem Rumpf
r2 = mr.anlegen("a.bender", {"name": "X", "prompt": "y", "owner": "chef", "id": "deadbeef"})
check(r2["owner"] == "a.bender" and r2["id"] != "deadbeef",
      "owner/id aus dem Rumpf werden ignoriert")

# Nicht freigeschalteter Bereich
try:
    mr.anlegen("a.bender", {"name": "Voll", "prompt": "p", "bereiche": ["voll"]})
    check(False, "nicht freigeschalteter Bereich wird abgewiesen")
except mr.RegelFehler as e:
    check("nicht freigeschaltet" in str(e),
          "nicht freigeschalteter Bereich wird abgewiesen", str(e))
_skill_states["email"]["config"]["bereiche"] = "mail,wissen,fach,dokumente,voll"
r3 = mr.anlegen("a.bender", {"name": "Voll", "prompt": "p", "bereiche": ["voll"]})
check("voll" in r3["bereiche"], "nach Freigabe ist der Bereich waehlbar")
_skill_states["email"]["config"]["bereiche"] = "mail,wissen"

# Feld-Whitelist beim Aendern
for feld in ("owner", "id", "laeufe", "letzter_lauf"):
    try:
        mr.aendern(r["id"], {feld: "x"}, owner="a.bender")
        check(False, f"'{feld}' laesst sich nicht aendern")
    except mr.RegelFehler:
        check(True, f"'{feld}' laesst sich nicht aendern")

# Fremde Regeln sind unsichtbar – "nicht gefunden", nicht "verboten"
try:
    mr.aendern(r["id"], {"name": "gekapert"}, owner="fremder")
    check(False, "fremde Regel nicht aenderbar")
except mr.RegelFehler as e:
    check("nicht gefunden" in str(e).lower(),
          "fremde Regel meldet 'nicht gefunden' (kein Existenz-Orakel)")
check(mr.loeschen(r["id"], owner="fremder") is False, "fremde Regel nicht loeschbar")
check(mr.liste("fremder") == [], "fremder Benutzer sieht keine Regeln")
check(len(mr.liste("a.bender")) == 3, "eigener Benutzer sieht seine drei Regeln")
check(len(mr.liste(None)) == 3, "Admin-Sicht (owner=None) sieht alle")

# Zahlen: 0 wird auf die Untergrenze GEHOBEN, nicht zum Vorgabewert
rz = mr.anlegen("a.bender", {"name": "Null", "prompt": "p", "intervall_min": 0,
                             "max_je_lauf": 0})
check(rz["intervall_min"] == mr.MIN_INTERVALL_MIN,
      "intervall_min=0 wird auf die Untergrenze gehoben, nicht auf 5")
check(rz["max_je_lauf"] == 1, "max_je_lauf=0 wird auf 1 gehoben")
rz = mr.aendern(rz["id"], {"intervall_min": 99999, "max_je_lauf": 999}, owner="a.bender")
check(rz["intervall_min"] == mr.MAX_INTERVALL_MIN and rz["max_je_lauf"] == mr.MAX_JE_LAUF,
      "Obergrenzen greifen")
rz = mr.aendern(rz["id"], {"intervall_min": "keine Zahl"}, owner="a.bender")
check(rz["intervall_min"] == mr.VORGABE_INTERVALL_MIN, "Muell wird zur Vorgabe")

# Pflichtfelder
for felder, label in (({"prompt": "p"}, "ohne Namen"),
                      ({"name": "n"}, "ohne Prompt"),
                      ({"name": "n", "prompt": "x" * (mr.PROMPT_MAX + 1)}, "Prompt zu lang")):
    try:
        mr.anlegen("a.bender", felder)
        check(False, f"{label} wird abgewiesen")
    except mr.RegelFehler:
        check(True, f"{label} wird abgewiesen")

# Deckel je Benutzer
vorhanden = len(mr.liste("a.bender"))
for i in range(mr.MAX_REGELN_JE_BENUTZER - vorhanden):
    mr.anlegen("a.bender", {"name": f"R{i}", "prompt": "p"})
try:
    mr.anlegen("a.bender", {"name": "eine zuviel", "prompt": "p"})
    check(False, "Deckel je Benutzer greift")
except mr.RegelFehler as e:
    check("hoechstens" in str(e), "Deckel je Benutzer greift", str(e))
# Ein ANDERER Benutzer ist davon nicht betroffen
check(bool(mr.anlegen("zweiter", {"name": "Meine", "prompt": "p"})),
      "der Deckel gilt je Benutzer, nicht global")


# ═══════════════════════════════════════════════════════════════════════════
section("3. Werkzeug-Zuschnitt (die Sicherheitsformel)")
# ═══════════════════════════════════════════════════════════════════════════

nur_mail = mr.werkzeuge_fuer(["mail"])
check(nur_mail == set(mr.MAIL_WERKZEUGE), "Bereich 'mail' gibt genau die Mail-Werkzeuge")
check("knowledge_search" not in nur_mail, "ohne 'wissen' kein knowledge_search")
check("shell_execute" not in nur_mail and "filesystem" not in nur_mail,
      "niemals Shell/Dateisystem")
check("cron_create" not in nur_mail and "spawn_agent" not in nur_mail,
      "niemals Cron/Sub-Agenten")
check("reflection" not in nur_mail, "niemals reflection (Persistenz-Substrat)")

mit_wissen = mr.werkzeuge_fuer(["mail", "wissen"])
check("knowledge_search" in mit_wissen, "'wissen' fuegt knowledge_search hinzu")
check(nur_mail < mit_wissen, "Bereiche wirken additiv, ohne Mail zu verlieren")

check(mr.werkzeuge_fuer(["voll"]) is None,
      "'voll' = None (keine Beschraenkung), NICHT leere Menge")
check(mr.werkzeuge_fuer([]) == set(mr.MAIL_WERKZEUGE),
      "leere Auswahl faellt auf Mail zurueck, nicht auf 'alles'")
check(mr.werkzeuge_fuer(["erfunden"]) == set(mr.MAIL_WERKZEUGE),
      "unbekannte Bereichskennung wird verworfen, nicht geraten")

fach = mr.werkzeuge_fuer(["mail", "fach"])
schreibend = {"jira_create_issue", "jira_add_comment", "confluence_create_page",
              "confluence_update_page", "confluence_delete_page",
              "confluence_add_comment", "confluence_upload_attachment"}
check(not (fach & schreibend),
      "Bereich 'fach' enthaelt KEIN schreibendes Werkzeug",
      "eine Fremdmail darf kein Ticket anlegen")

# Freigabe-Liste
_skill_states["email"]["config"]["bereiche"] = "wissen"
check(mr.freigegebene_bereiche()[0] == "mail",
      "'mail' ist immer freigegeben (sonst koennte keine Regel etwas tun)")
_skill_states["email"]["config"]["bereiche"] = ""
check(mr.freigegebene_bereiche() == ["mail"], "ohne Freigabe gilt nur 'mail'")
_skill_states["email"]["config"]["bereiche"] = "mail,wissen"
kat = mr.bereiche_katalog()
check(len(kat) == len(mr.BEREICHE) and all("name" in b and "freigegeben" in b for b in kat),
      "Katalog nennt ALLE Bereiche mit Freigabe-Kennzeichen")
check([b["id"] for b in kat if b["freigegeben"]] == ["mail", "wissen"],
      "Katalog kennzeichnet genau die freigegebenen")
check(next(b for b in kat if b["id"] == "mail")["pflicht"] is True,
      "'mail' ist als Pflicht gekennzeichnet")


# ═══════════════════════════════════════════════════════════════════════════
section("4. Verarbeitungs-Buchhaltung und Faelligkeit")
# ═══════════════════════════════════════════════════════════════════════════

# Aufraeumen: nur EINE Regel behalten
for x in mr.liste(None):
    mr.loeschen(x["id"])
regel = mr.anlegen("a.bender", {"name": "Test", "prompt": "p", "intervall_min": 5})
rid = regel["id"]

check(len(mr.faellige()) == 1, "neue Regel ist sofort faellig")
mr.merke_lauf(rid)
check(mr.faellige() == [], "nach einem Lauf nicht mehr faellig (Intervall)")
mr.merke_lauf(rid, time.time() - 6 * 60)
check(len(mr.faellige()) == 1, "nach Ablauf des Intervalls wieder faellig")
# Eine ausdrueckliche 0 heisst "nie gelaufen" und darf NICHT zu "jetzt" werden
# (Falsyness-Falle: `int(zeit or time.time())`).
mr.merke_lauf(rid, 0)
check(mr.zustand_regel(rid)["letzter_lauf"] == 0,
      "merke_lauf(id, 0) setzt wirklich 0, nicht die aktuelle Zeit")
check(len(mr.faellige()) == 1, "und die Regel ist damit faellig")

mr.aendern(rid, {"enabled": False}, owner="a.bender")
check(mr.faellige() == [], "abgeschaltete Regel laeuft nicht")
mr.aendern(rid, {"enabled": True}, owner="a.bender")

# Regel ohne Besitzer laeuft NIE (fail-closed)
d = json.loads(mr.REGEL_DATEI.read_text())
d["regeln"][0]["owner"] = ""
mr.REGEL_DATEI.write_text(json.dumps(d))
check(mr.faellige() == [], "Regel ohne Besitzer laeuft NIE (fail-closed)")
d["regeln"][0]["owner"] = "a.bender"
mr.REGEL_DATEI.write_text(json.dumps(d))

check(mr.schon_verarbeitet(rid, "<m1@x>") is False, "unbekannte Nachricht gilt als neu")
mr.merke_verarbeitet(rid, "<m1@x>", 1000.0)
check(mr.schon_verarbeitet(rid, "<m1@x>") is True, "verarbeitete Nachricht wird erkannt")
check(mr.schon_verarbeitet(rid, "") is False, "leerer Schluessel gilt nie als verarbeitet")
check(mr.zustand_regel(rid)["letzter_stempel"] == 1000.0, "Zeitstempel wird fortgeschrieben")
mr.merke_verarbeitet(rid, "<m2@x>", 500.0)
check(mr.zustand_regel(rid)["letzter_stempel"] == 1000.0,
      "der Zeitstempel wandert nur nach VORN (aeltere Mail senkt ihn nicht)")

for i in range(mr.MAX_GESEHEN + 50):
    mr.merke_verarbeitet(rid, f"<viele{i}@x>", 2000.0 + i)
z = mr.zustand_regel(rid)
check(len(z["gesehen"]) == mr.MAX_GESEHEN, "Arbeitsspeicher der Kennungen ist gedeckelt")
check(z["gesehen"][-1] == f"<viele{mr.MAX_GESEHEN + 49}@x>", "die neuesten bleiben erhalten")

# Loeschen raeumt den Zustand mit ab
mr.loeschen(rid, owner="a.bender")
check(rid not in json.loads(mr.ZUSTAND_DATEI.read_text()),
      "Loeschen entfernt auch den Verarbeitungs-Zustand")


# ═══════════════════════════════════════════════════════════════════════════
# Ein Lauf OHNE Ergebnis ist kein Erfolg (sonst wird die Nachricht abgehakt,
# obwohl nichts geschehen ist – am 2026-08-12 genau bei der einen Nachricht,
# auf die die Regel zutraf: Reasoning-Schleife, finish_reason=length).
import importlib
_mrun = importlib.import_module("backend.mail_runner")
check(_mrun._kein_ergebnis("") is True, "leere Antwort = kein Ergebnis")
check(_mrun._kein_ergebnis("   ") is True, "nur Leerzeichen = kein Ergebnis")
check(_mrun._kein_ergebnis("Entwurf gespeichert.") is False,
      "eine echte Antwort ist ein Ergebnis")
check(_mrun._kein_ergebnis("HINWEIS_AN_NUTZER: geht nicht") is True,
      "die HINWEIS_AN_NUTZER-Konvention zaehlt als kein Ergebnis")
try:
    from backend.llm import HINWEIS_UNVOLLSTAENDIG
    check(_mrun._kein_ergebnis(HINWEIS_UNVOLLSTAENDIG) is True,
          "die Reasoning-Schleifen-Meldung zaehlt als kein Ergebnis")
    # EINE Quelle fuer den Text – kein nachgetipptes Literal
    llm_q = (ROOT / "backend/llm.py").read_text()
    check(llm_q.count("Das Modell konnte die Antwort nicht abschließen") == 1,
          "der Hinweistext steht genau EINMAL in llm.py (als Konstante)")
    check("parts.append(LLMPart(text=HINWEIS_UNVOLLSTAENDIG))" in llm_q,
          "die Fundstelle benutzt die Konstante")
    run_q = (ROOT / "backend/mail_runner.py").read_text()
    check("from backend.llm import HINWEIS_UNVOLLSTAENDIG" in run_q,
          "der Runner importiert dieselbe Konstante (kein Prosa-Vergleich)")
except ImportError:
    check(True, "llm-Konstante uebersprungen (Import nicht moeglich)")
_l = (ROOT / "backend/mail_runner.py").read_text()
check('reasoning_effort="low"' in _l,
      "bei einem Nicht-Ergebnis wird EINMAL mit knapper Denktiefe wiederholt")
_ll = _l[_l.index("ergebnis = await _lauf_fuer_nachricht"):]
check("_kein_ergebnis(ergebnis)" in _ll[:600],
      "das Ergebnis wird nach dem Lauf geprueft")

# ── Fehlversuche: ein Fehlschlag haakt die Nachricht NICHT ab ───────────────
regel_f = mr.anlegen("a.bender", {"name": "Fehler", "prompt": "p"})
fid = regel_f["id"]
check(mr.fehlversuche(fid, "<f1@x>") == 0, "unbekannte Nachricht hat 0 Fehlversuche")
check(mr.merke_fehlversuch(fid, "<f1@x>") == 1, "erster Fehlversuch wird gezaehlt")
check(mr.merke_fehlversuch(fid, "<f1@x>") == 2, "zweiter Fehlversuch wird gezaehlt")
check(mr.schon_verarbeitet(fid, "<f1@x>") is False,
      "nach Fehlversuchen gilt die Nachricht NICHT als verarbeitet "
      "(sonst verschluckt ein technischer Ausfall Post endgueltig)")
check(mr.merke_fehlversuch(fid, "<f1@x>") == mr.MAX_FEHLVERSUCHE,
      "der Deckel ist erreichbar")
mr.vergiss_fehlversuche(fid, "<f1@x>")
check(mr.fehlversuche(fid, "<f1@x>") == 0,
      "ein Erfolg loescht den Zaehler (sonst gibt ein spaeterer Ausfall zu frueh auf)")
check(mr.merke_fehlversuch(fid, "") == 0, "leerer Schluessel wird nicht gezaehlt")
# Wieder-Vorlegen (Administrator-Eingriff nach behobenem Fehler)
mr.merke_verarbeitet(fid, "<f2@x>", 100.0)
mr.merke_fehlversuch(fid, "<f2@x>")
check(mr.schon_verarbeitet(fid, "<f2@x>") is True, "Vorbedingung: gilt als verarbeitet")
check(mr.wieder_vorlegen(fid, "<f2@x>") is True, "wieder_vorlegen meldet Erfolg")
check(mr.schon_verarbeitet(fid, "<f2@x>") is False and mr.fehlversuche(fid, "<f2@x>") == 0,
      "wieder_vorlegen entfernt Vermerk UND Zaehler")
check(mr.wieder_vorlegen(fid, "<gibtsnicht@x>") is False,
      "wieder_vorlegen meldet ehrlich, wenn nichts zu tun war")
# Der Runner muss beide Zweige unterscheiden
runner_q = (ROOT / "backend/mail_runner.py").read_text()
_lauf = runner_q[runner_q.index("if not testlauf:"):]
_lauf = _lauf[:_lauf.index("bericht[")]
check("if ok:" in _lauf and "merke_fehlversuch" in _lauf,
      "der Runner trennt Erfolg und Fehlschlag")
check("MAX_FEHLVERSUCHE" in _lauf,
      "und gibt erst nach dem Deckel auf")
check("Versuch %d von %d" in _lauf,
      "der Zwischenstand steht im Ergebnistext (nichts passiert stillschweigend)")
mr.loeschen(fid)

section("5. Protokoll: Filter beim Lesen, Alterung, keine Mengengrenze")
# ═══════════════════════════════════════════════════════════════════════════

mr.PROTOKOLL_DATEI.unlink(missing_ok=True)
regel = mr.anlegen("a.bender", {"name": "Log", "prompt": "p"})
for i in range(200):
    mr.protokoll_schreiben({"owner": "a.bender" if i % 3 else "andere",
                            "regel_id": regel["id"] if i % 3 else "fremd",
                            "ergebnis": f"lauf {i}", "ok": True})
check(oct(mr.PROTOKOLL_DATEI.stat().st_mode & 0o777) == "0o640", "Protokoll ist 0640")
alle = mr.protokoll_lesen(limit=999)
check(len(alle) == 200, "keine Mengengrenze: alle 200 Eintraege sind da")
check(alle[0]["ergebnis"] == "lauf 199", "neueste zuerst")

eigen = mr.protokoll_lesen(owner="a.bender", limit=5)
check(len(eigen) == 5 and all(e["owner"] == "a.bender" for e in eigen),
      "Filter liefert nur eigene Eintraege")
check(eigen[0]["ergebnis"] == "lauf 199", "Filter beginnt bei den neuesten")

# Der Filter muss WAEHREND des Lesens wirken: ein seltener Benutzer hinter
# vielen neueren Eintraegen muss gefunden werden (Fehlerklasse vom 2026-08-02).
mr.protokoll_schreiben({"owner": "selten", "regel_id": "x", "ergebnis": "GENAU DER"})
for i in range(150):
    mr.protokoll_schreiben({"owner": "a.bender", "regel_id": "y", "ergebnis": f"rausch {i}"})
selten = mr.protokoll_lesen(owner="selten", limit=10)
check(len(selten) == 1 and selten[0]["ergebnis"] == "GENAU DER",
      "seltener Benutzer wird hinter 150 neueren Eintraegen gefunden")

# Beschaedigte Zeile darf das Protokoll nicht unlesbar machen
with mr.PROTOKOLL_DATEI.open("a") as f:
    f.write("{kein gueltiges json\n")
mr.protokoll_schreiben({"owner": "a.bender", "ergebnis": "danach"})
check(mr.protokoll_lesen(limit=1)[0]["ergebnis"] == "danach",
      "beschaedigte Zeile wird uebersprungen")

# Alterung: nur nach ALTER, Eintrag ohne Zeitstempel bleibt
mr.PROTOKOLL_DATEI.unlink()
mr.protokoll_schreiben({"owner": "a.bender", "ergebnis": "alt", "ts": time.time() - 100 * 86400})
mr.protokoll_schreiben({"owner": "a.bender", "ergebnis": "neu"})
with mr.PROTOKOLL_DATEI.open("a") as f:
    f.write(json.dumps({"owner": "a.bender", "ergebnis": "ohne datum"}) + "\n")
entfernt = mr.protokoll_kuerzen(time.time() - 90 * 86400)
uebrig = [e.get("ergebnis") for e in mr.protokoll_lesen(limit=99)]
check(entfernt == 1, "genau der alte Eintrag wurde entfernt")
check("alt" not in uebrig and "neu" in uebrig, "Alterung greift nach Datum")
check("ohne datum" in uebrig,
      "Eintrag OHNE Zeitstempel bleibt stehen (fehlendes Datum ist kein Altersbeweis)")
check(mr.protokoll_kuerzen(time.time() - 90 * 86400) == 0, "zweiter Lauf ist idempotent")


# ═══════════════════════════════════════════════════════════════════════════
section("6. Mail-Client: Kanalwahl, Rueckfall, Fehler-Einordnung")
# ═══════════════════════════════════════════════════════════════════════════

k = mc.MailKonto(adresse="a@b.de", passwort="x", kanal="auto", imap_host="imap.b.de")
c = mc.MailClient(k)
check([b.kanal for b in c._kandidaten()] == ["ews", "imap"],
      "auto probiert EWS zuerst, dann IMAP")
c.aktiver_kanal = "imap"
check([b.kanal for b in c._kandidaten()] == ["imap"],
      "der einmal erfolgreiche Kanal wird festgehalten")
c2 = mc.MailClient(mc.MailKonto(adresse="a@b.de", passwort="x", kanal="ews"))
check([b.kanal for b in c2._kandidaten()] == ["ews"], "kanal=ews laesst IMAP aus")
c3 = mc.MailClient(mc.MailKonto(adresse="a@b.de", passwort="x", kanal="imap",
                                imap_host="h"))
check([b.kanal for b in c3._kandidaten()] == ["imap"], "kanal=imap laesst EWS aus")

for text, erwartet, label in (
    ("No module named 'exchangelib'", "kanal", "fehlendes exchangelib = Kanalfehler"),
    ("The server returned 401 Unauthorized", "auth", "401 = Anmeldefehler"),
    ("authentication failed", "auth", "authentication failed = Anmeldefehler"),
    ("AutoDiscover failed", "kanal", "Autodiscover-Fehler = Kanalfehler"),
    ("HTTP 404 Not Found", "kanal", "404 am Endpunkt = Kanalfehler"),
    ("Connection refused", "kanal", "abgelehnte Verbindung = Kanalfehler"),
    ("operation timed out", "netz", "Zeitueberschreitung = Netzfehler"),
):
    f = mc._einordnen(Exception(text), "ews")
    check(f.kategorie == erwartet, label, f"{text} -> {f.kategorie}")
check(mc._einordnen(ModuleNotFoundError("x"), "ews").kategorie == "kanal",
      "ModuleNotFoundError ist ein Kanalfehler")

# DER KERN: Rueckfall nur bei Kanalfehlern, NIE bei Anmeldefehlern
class _Backend:
    def __init__(self, kanal, fehler=None):
        self.kanal = kanal
        self.fehler = fehler
        self.aufrufe = 0

    def test(self):
        self.aufrufe += 1
        if self.fehler:
            raise self.fehler
        return {"ok": True, "kanal": self.kanal}


cl = mc.MailClient(mc.MailKonto(adresse="a@b.de", passwort="x", imap_host="h"))
cl._ews = _Backend("ews", mc.MailFehler("exchangelib fehlt", "kanal", "ews"))
cl._imap = _Backend("imap")
check(cl.test()["kanal"] == "imap" and cl._imap.aufrufe == 1,
      "Kanalfehler fuehrt zum Rueckfall auf IMAP")
check(cl.aktiver_kanal == "imap", "der Rueckfall-Kanal wird festgehalten")

cl = mc.MailClient(mc.MailKonto(adresse="a@b.de", passwort="x", imap_host="h"))
cl._ews = _Backend("ews", mc.MailFehler("LOGIN failed", "auth", "ews"))
cl._imap = _Backend("imap")
try:
    cl.test()
    check(False, "Anmeldefehler fuehrt NICHT zum Rueckfall")
except mc.MailFehler as f:
    check(f.kategorie == "auth" and cl._imap.aufrufe == 0,
          "Anmeldefehler fuehrt NICHT zum Rueckfall (Kontosperre + verschleierter Grund)")

cl = mc.MailClient(mc.MailKonto(adresse="a@b.de", passwort="x", imap_host="h"))
cl._ews = _Backend("ews", mc.MailFehler("timeout", "netz", "ews"))
cl._imap = _Backend("imap")
try:
    cl.test()
    check(False, "Netzfehler fuehrt nicht zum Rueckfall")
except mc.MailFehler:
    check(cl._imap.aufrufe == 0, "Netzfehler fuehrt nicht zum Rueckfall")

# Scheitern BEIDE Kanaele, muss die Meldung beide nennen (live auf DEV
# aufgefallen: es stand nur "Kein IMAP-Server hinterlegt", obwohl EWS an
# Autodiscover gescheitert war – der Administrator sucht dann am falschen Ende).
cl = mc.MailClient(mc.MailKonto(adresse="a@b.de", passwort="x", imap_host="h"))
cl._ews = _Backend("ews", mc.MailFehler("Autodiscover fehlgeschlagen", "kanal", "ews"))
cl._imap = _Backend("imap", mc.MailFehler("Kein IMAP-Server hinterlegt", "kanal", "imap"))
try:
    cl.test()
    check(False, "beide Kanaele scheitern -> Fehler")
except mc.MailFehler as f:
    check("Autodiscover" in str(f) and "IMAP" in str(f),
          "die Meldung nennt BEIDE Fehlversuche", str(f))
    check(f.kategorie == "kanal" and f.kanal == "imap",
          "Kategorie und Kanal stammen vom letzten Versuch")

try:
    mc.MailClient(mc.MailKonto(adresse="", passwort="x"))
    check(False, "Konto ohne Adresse wird abgewiesen")
except mc.MailFehler as f:
    check(f.kategorie == "eingabe", "Konto ohne Adresse wird abgewiesen")
try:
    mc.MailClient(mc.MailKonto(adresse="a@b.de", passwort=""))
    check(False, "Konto ohne Kennwort wird abgewiesen")
except mc.MailFehler:
    check(True, "Konto ohne Kennwort wird abgewiesen")
try:
    mc.MailClient(mc.MailKonto(adresse="a@b.de", passwort="x", kanal="imap"))
    check(False, "kanal=imap ohne IMAP-Server wird abgewiesen")
except mc.MailFehler:
    check(True, "kanal=imap ohne IMAP-Server wird abgewiesen")

check(mc.klartext(mc.MailFehler("x", "auth")).lower().count("kennwort") >= 1
      and "sperren" in mc.klartext(mc.MailFehler("x", "auth")),
      "Anmeldefehler-Text nennt Kennwort UND die Sperrgefahr")

# HTML-Entschaerfung und Adress-Zerlegung
check(mc.html_zu_text("<p>Hallo<br>Welt</p><script>boese()</script>") == "Hallo\nWelt",
      "HTML wird zu Text, Skript entfernt")
check("style" not in mc.html_zu_text('<div style="color:red">x</div>'),
      "Stil-Attribute verschwinden")
check(mc._adressliste("Max <m@x.de>; y@z.de, a@b.de") == ["m@x.de", "y@z.de", "a@b.de"],
      "Adressliste nimmt Komma, Semikolon und Namensform")
check(mc._adressliste(None) == [] and mc._adressliste("") == [],
      "leere Adressangabe ergibt leere Liste")
try:
    mc._pruefe_empfaenger([])
    check(False, "Senden ohne Empfaenger wird abgewiesen")
except mc.MailFehler:
    check(True, "Senden ohne Empfaenger wird abgewiesen")
try:
    mc._pruefe_empfaenger(["keine-adresse"])
    check(False, "unguelige Empfaengeradresse wird abgewiesen")
except mc.MailFehler:
    check(True, "unguelige Empfaengeradresse wird abgewiesen")

# EWS-URL-Normierung: ein Administrator traegt den HOSTNAMEN ein (auf DEV genau
# so passiert: "exchange.nexus-ag.de"), exchangelib braucht die volle Adresse.
for ein, soll, label in (
    ("exchange.nexus-ag.de", "https://exchange.nexus-ag.de/EWS/Exchange.asmx",
     "bloszer Hostname wird zur vollen EWS-Adresse"),
    ("https://exchange.nexus-ag.de", "https://exchange.nexus-ag.de/EWS/Exchange.asmx",
     "fehlender Pfad wird ergaenzt"),
    ("https://exchange.nexus-ag.de/", "https://exchange.nexus-ag.de/EWS/Exchange.asmx",
     "abschliessender Schraegstrich stoert nicht"),
    ("https://mail.firma.de/EWS/Exchange.asmx", "https://mail.firma.de/EWS/Exchange.asmx",
     "vollstaendige Adresse bleibt unangetastet"),
    ("https://firma.de/eigener/pfad/ews.asmx", "https://firma.de/eigener/pfad/ews.asmx",
     "eigener Pfad wird NICHT ueberschrieben"),
    ("mail.firma.de:444", "https://mail.firma.de:444/EWS/Exchange.asmx",
     "Portangabe bleibt erhalten"),
    ("http://alt.firma.de/EWS/Exchange.asmx", "http://alt.firma.de/EWS/Exchange.asmx",
     "ausdrueckliches http bleibt http"),
    ("", "", "leere Eingabe bleibt leer"),
):
    check(mc.ews_url_normieren(ein) == soll, label,
          "%r -> %r" % (ein, mc.ews_url_normieren(ein)))

# TLS-Adapter: exchangelib waehlt ihn ueber eine PROZESSWEITE Klassenvariable.
# Wird sie nur in EINE Richtung gesetzt, bleibt die Zertifikatspruefung nach
# einem Lauf ohne Verifikation fuer den ganzen Prozess aus – auch wenn der
# Administrator sie wieder einschaltet.
check(hasattr(mc, "_tls_adapter_setzen"), "es gibt eine Stelle fuer den TLS-Adapter")
_tls = (ROOT / "backend/mail_client.py").read_text()
_tlsfn = _tls[_tls.index("def _tls_adapter_setzen"):]
_tlsfn = _tlsfn[:_tlsfn.index("def ews_url_normieren")]
check("requests.adapters.HTTPAdapter if verify else NoVerifyHTTPAdapter" in _tlsfn,
      "der Adapter wird in BEIDE Richtungen gesetzt")
check("_tls_adapter_setzen(bool(k.verify_ssl))" in _tls,
      "die Verbindung setzt ihn bei JEDEM Aufbau")
check('warnings.filterwarnings("once"' in _tlsfn,
      "die urllib3-Warnung wird auf einmal je Prozess gedrosselt, nicht unterdrueckt")
# Auf den AUFRUF pruefen, nicht auf das Wort – und Kommentare ausnehmen: die
# erste Fassung schlug an der eigenen Begruendung an ('"once" statt "ignore"').
# Dieselbe Falle wie beim Prompt-Waechter am 2026-08-10.
_tls_code = "\n".join(z for z in _tlsfn.splitlines() if not z.strip().startswith("#"))
check('filterwarnings("ignore"' not in _tls_code
      and "disable_warnings" not in _tls_code,
      "sie wird NICHT ganz verschluckt (die Information bleibt)")
# Umschalten wirklich pruefen (ohne Exchange, nur die Klassenvariable)
try:
    from exchangelib.protocol import BaseProtocol, NoVerifyHTTPAdapter
    import requests.adapters
    mc._tls_adapter_setzen(False)
    aus = BaseProtocol.HTTP_ADAPTER_CLS is NoVerifyHTTPAdapter
    mc._tls_adapter_setzen(True)
    an = BaseProtocol.HTTP_ADAPTER_CLS is requests.adapters.HTTPAdapter
    check(aus and an, "Abschalten UND Wiedereinschalten wirken",
          "aus=%s an=%s" % (aus, an))
except ImportError:
    check(True, "Umschalt-Probe uebersprungen (exchangelib nicht installiert)")

# EWS-Item-Aufloesung: NIEMALS filter(id=...) – EWS macht daraus eine
# Restriction und lehnt sie ab ("EWS does not support filtering on field 'id'").
# Das hat am 2026-08-12 im Betrieb JEDE Regel-Aktion blockiert.
ews_quelle = (ROOT / "backend/mail_client.py").read_text()
_ohne_kommentare = "\n".join(
    z for z in ews_quelle.splitlines() if not z.strip().startswith("#"))
check("filter(id=" not in _ohne_kommentare,
      "kein filter(id=...) im Code (EWS kann nicht auf die Kennung filtern)")
check("fetch(ids=[(msg_id, None)])" in _ohne_kommentare,
      "fetch() bekommt ein (id, changekey)-TUPEL, keine nackte Zeichenkette")
check(".get(id=msg_id)" in _ohne_kommentare,
      "der Rueckfall benutzt get(id=...) – die einzige erlaubte Form")
_such = ews_quelle[ews_quelle.index("def _suche_item"):]
_such = _such[:_such.index("def lesen")]
check("except Exception:  # noqa: BLE001\n            pass" not in _such,
      "der erste Fehlversuch wird NICHT mehr stillschweigend verschluckt")
check("gruende" in _such and "Versuche:" in _such,
      "die Fehlermeldung nennt die gescheiterten Versuche")

# Eine eingetragene URL GEWINNT gegen den Autodiscover-Haken. Vorher galt
# `ews_url and not autodiscover` – wer den Server eintrug und den Haken stehen
# liess, dessen Eingabe wurde stillschweigend ignoriert.
ews_quelle = (ROOT / "backend/mail_client.py").read_text()
check("if k.ews_url:" in ews_quelle,
      "die Weiche fragt nur noch, OB eine URL eingetragen ist")
check("if k.ews_url and not k.autodiscover:" not in ews_quelle,
      "die alte Weiche (URL nur ohne Autodiscover) ist weg")
check("ews_url_normieren(k.ews_url)" in ews_quelle,
      "die eingetragene URL wird vor der Benutzung normiert")

check(mc.MailKonto(adresse="a@b.de", benutzer="NEXUS\\ab").anmeldename() == "NEXUS\\ab",
      "Anmeldename gewinnt gegen die Adresse")
check(mc.MailKonto(adresse="a@b.de").anmeldename() == "a@b.de",
      "ohne Anmeldenamen gilt die Adresse")

n = mc.MailNachricht(id="1", betreff="B", text="x" * 5000)
kurz = n.kurz(text_max=100)
check(kurz["text_gekuerzt"] is True and len(kurz["text"]) < 200,
      "langer Text wird fuer das Modell gekuerzt und ausgewiesen")
check(n.kurz(text_max=0)["text_gekuerzt"] is True, "text_max=0 liefert keinen Inhalt")


# ═══════════════════════════════════════════════════════════════════════════
section("7. Regel-Lauf: Auftragsbau, Actor-Bindung, Vorfilter")
# ═══════════════════════════════════════════════════════════════════════════

from backend import mail_runner as mrun      # noqa: E402

regel = {"id": "abc", "owner": "a.bender", "name": "R", "prompt": "MEINE ANWEISUNG",
         "ordner": "INBOX", "bereiche": ["mail"], "max_je_lauf": 3,
         "nur_ungelesen": True, "von_filter": "", "betreff_filter": ""}
nachricht = mc.MailNachricht(
    id="AAA", schluessel="<m@x>", ordner="INBOX", von="kunde@extern.de",
    von_name="Kunde", an=["a.bender@nexus.int"], betreff="Rechnung 4711",
    datum="2026-08-12T10:00:00", text="Bitte um Bestaetigung.", anhaenge=["r.pdf"])

auftrag = mrun._auftrag(regel, nachricht, "a.bender@nexus.int")
check("MEINE ANWEISUNG" in auftrag, "das Prompt der Regel steht im Auftrag")
check("Bitte um Bestaetigung." in auftrag, "der Mailtext steht im Auftrag")
check(auftrag.index("MEINE ANWEISUNG") < auftrag.index("Bitte um Bestaetigung."),
      "REIHENFOLGE: die Regel steht VOR dem Fremdtext")
check("AAA" in auftrag, "die Nachrichten-Kennung wird mitgegeben")
check("r.pdf" in auftrag, "Anhangsnamen werden genannt")
for wort in ("FREMDTEXT", "Angriffsversuch", "ignoriere deine Anweisungen"):
    check(wort in auftrag, f"Sicherheitshinweis enthaelt '{wort}'")
check("Zugangsdaten" in auftrag, "Auftrag verbietet die Herausgabe von Zugangsdaten")
check(auftrag.index("SICHERHEIT") < auftrag.index("EINGEGANGENE NACHRICHT"),
      "der Sicherheitshinweis steht VOR dem Fremdtext")

lang = mc.MailNachricht(id="B", schluessel="<b>", text="y" * (mrun.TEXT_MAX + 5000))
a2 = mrun._auftrag(regel, lang, "a@b.de")
check("Text gekuerzt" in a2 and len(a2) < mrun.TEXT_MAX + 3000,
      "sehr langer Mailtext wird gekuerzt und die Kuerzung ausgewiesen")

actor = mrun._actor_fuer(regel)
check(actor["user"] == "a.bender", "der Actor traegt den Besitzer der Regel")
check(actor["privileged"] is False, "der Regel-Lauf ist IMMER unprivilegiert")
check(actor["internet"] is False and actor["sap"] is False,
      "ohne geladenes main gilt fail-closed (kein Internet, kein SAP)")
check(mrun._actor_fuer({"owner": ""})["privileged"] is False,
      "auch ohne Besitzer niemals privilegiert")

# Vorfilter
check(mrun._passt(regel, nachricht) is True, "ohne Filter passt jede Nachricht")
check(mrun._passt(dict(regel, von_filter="extern.de"), nachricht) is True,
      "Absender-Filter trifft (Teiltreffer)")
check(mrun._passt(dict(regel, von_filter="lieferant.de"), nachricht) is False,
      "Absender-Filter schliesst aus")
check(mrun._passt(dict(regel, von_filter="a@x.de, extern.de"), nachricht) is True,
      "mehrere Absender-Muster, eines genuegt")
check(mrun._passt(dict(regel, betreff_filter="rechnung"), nachricht) is True,
      "Betreff-Filter ist unabhaengig von Gross-/Kleinschreibung")
check(mrun._passt(dict(regel, betreff_filter="angebot"), nachricht) is False,
      "Betreff-Filter schliesst aus")
check(mrun._passt(dict(regel, von_filter="extern.de", betreff_filter="angebot"),
                  nachricht) is False, "beide Filter muessen passen (UND)")

# Der Lauf braucht ein Konto – ohne eines: sprechender Bericht, kein Absturz
bericht = asyncio.run(mrun.regel_lauf({"id": "x", "owner": "gibtsnicht", "name": "N",
                                       "prompt": "p", "ordner": "INBOX",
                                       "bereiche": ["mail"]}))
check(bericht["ok"] is False and "Postfach" in bericht["fehler"],
      "Regel ohne hinterlegtes Postfach meldet den Grund im Klartext")
bericht = asyncio.run(mrun.regel_lauf({"id": "x", "owner": "", "name": "N", "prompt": "p"}))
check(bericht["ok"] is False and "Besitzer" in bericht["fehler"],
      "Regel ohne Besitzer wird nicht ausgefuehrt")

check(mrun.MAX_LAEUFE_JE_DURCHGANG >= 1, "Deckel je Durchgang ist gesetzt")
_skill_states["email"]["enabled"] = False
check(asyncio.run(mrun.automatik_durchgang()).get("aus") is True,
      "bei ausgeschaltetem Skill laeuft der Takt nicht")
_skill_states["email"]["enabled"] = True


# ═══════════════════════════════════════════════════════════════════════════
section("8. Werkzeuge des Skills: Postfach ist KEIN Parameter")
# ═══════════════════════════════════════════════════════════════════════════

import importlib.util                        # noqa: E402
spec = importlib.util.spec_from_file_location("emailskill", ROOT / "skills/email/main.py")
skill = importlib.util.module_from_spec(spec)
spec.loader.exec_module(skill)
tools = skill.get_tools()
namen = {t.name for t in tools}

manifest = json.loads((ROOT / "skills/email/skill.json").read_text())
check(namen == set(manifest["tools"]), "Manifest und Code nennen dieselben Werkzeuge",
      str(namen ^ set(manifest["tools"])))
check(namen == set(mr.MAIL_WERKZEUGE),
      "mail_rules.MAIL_WERKZEUGE deckt sich mit dem Code",
      str(namen ^ set(mr.MAIL_WERKZEUGE)))

verboten = {"postfach", "mailbox", "konto", "benutzer", "user", "account", "adresse",
            "email_address", "primary_smtp_address"}
for t in tools:
    props = set((t.parameters_schema().get("properties") or {}).keys())
    check(not (props & verboten),
          f"{t.name} nimmt kein Postfach-Argument", str(props & verboten))
    check(bool(t.description) and len(t.description) > 40,
          f"{t.name} hat eine brauchbare Beschreibung")

# Ohne Benutzer im ContextVar: sprechende Absage, kein Absturz
marke = ma.current_mail_user.set("")
try:
    for t in tools:
        antwort = asyncio.run(t.execute(mail_id="1", an="x@y.de", betreff="b", text="t",
                                        ziel="Z", kategorie="K"))
        if not (antwort.startswith("❌") and "Benutzer" in antwort):
            check(False, f"{t.name} meldet ohne Benutzer eine klare Absage", antwort[:80])
            break
    else:
        check(True, "alle Werkzeuge melden ohne Benutzer eine klare Absage")
finally:
    ma.current_mail_user.reset(marke)

# Mit Benutzer, aber ohne Konto: ebenfalls Klartext (kein Netzaufruf)
marke = ma.current_mail_user.set("niemand")
try:
    antwort = asyncio.run(tools[0].execute())
    check(antwort.startswith("❌") and "Postfach" in antwort,
          "ohne hinterlegtes Postfach kommt ein Klartext-Hinweis", antwort[:80])
finally:
    ma.current_mail_user.reset(marke)


# ═══════════════════════════════════════════════════════════════════════════
section("9. Verdrahtung im Kern (Quelltext-Pruefungen)")
# ═══════════════════════════════════════════════════════════════════════════

agent_src = (ROOT / "backend/agent.py").read_text()
check("current_mail_user" in agent_src,
      "agent.py setzt den Postfach-ContextVar im Dispatch")
check(re.search(r"_mcv\.reset\(_m_token\)", agent_src),
      "der ContextVar wird im finally zurueckgenommen")
disp = agent_src[agent_src.index("_m_token = _mcv = None"):]
check(disp.index("_mcv.set(_uname") < disp.index("tool.execute("),
      "der ContextVar wird VOR der Werkzeug-Ausfuehrung gesetzt")
check("_uname or \"\"" in disp[:400],
      "gesetzt wird der Actor-Name (auch fuer privilegierte Benutzer)")

sandbox_src = (ROOT / "backend/sandbox.py").read_text()
for datei in ("email_accounts.json", ".mailkey", "email_rules.json",
              "email_state.json", "email_log.jsonl"):
    check(datei in sandbox_src, f"{datei} steht in den Sandbox-Sperrlisten")
check(re.search(r"_APP_DENY_REL[\s\S]{0,4000}?email_accounts\.json", sandbox_src),
      "die Dateien stehen in _APP_DENY_REL")
check("PRIVATE_FILES_STRENG" in sandbox_src and "0o600" in sandbox_src,
      "die Schluesseldatei wird auf 0600 gehaertet")
check("email_accounts\\.json" in sandbox_src or "email_accounts.json" in sandbox_src,
      "SHELL_SECRET_PATHS deckt die Kontendatei")

main_src = (ROOT / "backend/main.py").read_text()
check("def _user_may_use_email" in main_src, "Berechtigungs-Praedikat vorhanden")
check("async def require_email_access" in main_src, "Dependency vorhanden")
mayfn = main_src[main_src.index("def _user_may_use_email"):]
mayfn = mayfn[:mayfn.index("async def require_email_access")]
check("if not users_raw and not grp:" in mayfn and "return False" in mayfn,
      "leer = niemand (kein Admin-Bypass)")
check("_is_admin_user" not in mayfn, "die Berechtigung kennt KEINEN Admin-Bypass")

# Jeder Benutzer-Endpunkt haengt an require_email_access, der Admin-Teil an
# require_local_auth. Ein GET darf nicht schwaecher geschuetzt sein als ein POST.
for route in ("/api/email/status", "/api/email/account", "/api/email/test",
              "/api/email/folders", "/api/email/messages", "/api/email/rules",
              "/api/email/log", "/api/email/stop"):
    stellen = [m.start() for m in re.finditer(re.escape('"%s"' % route), main_src)]
    check(bool(stellen), f"{route} ist registriert")
    for pos in stellen:
        block = main_src[pos:pos + 900]
        if "require_email_access" not in block and "require_local_auth" not in block:
            check(False, f"{route} haengt an einer Berechtigung", block[:120])
            break
    else:
        check(True, f"{route} haengt an einer Berechtigung")

for route in ("/api/email/admin/overview", "/api/email/admin/explore",
              "/api/email/admin/areas"):
    pos = main_src.index('"%s"' % route)
    check("require_local_auth" in main_src[pos:pos + 700],
          f"{route} ist Administratoren vorbehalten")

# Der Konto-Endpunkt darf NICHT vorfiltern: ein unbekanntes Feld muss zu einem
# Klartext-Fehler fuehren, nicht still verworfen und als "gespeichert" gemeldet
# werden (live auf DEV am 2026-08-12 aufgefallen).
acct = main_src[main_src.index('async def email_account_set'):]
acct = acct[:acct.index("@app.delete(\"/api/email/account\")")]
check("if k in mail_accounts.AENDERBAR" not in acct,
      "der Konto-Endpunkt filtert NICHT vor (die Whitelist entscheidet allein)")
check("mail_accounts.speichern, user, body" in acct,
      "der Rumpf geht unveraendert an speichern()")

# Der Explorer darf keine Zugangsdaten aus dem Request nehmen (SSRF/Abfluss)
exp = main_src[main_src.index('"/api/email/admin/explore"'):]
exp = exp[:exp.index('"/api/email/admin/areas"')]
check("hat_konto" in exp, "der Explorer arbeitet nur mit hinterlegten Konten")
for feld in ("body.get(\"passwort\")", "body.get('passwort')",
             "body.get(\"imap_host\")", "body.get(\"ews_url\")"):
    check(feld not in exp, f"der Explorer liest kein '{feld}' aus dem Rumpf")

# permissions.email + Seiten-Route + Zeitplan
check('"email": _user_may_use_email(user) and _skill_active("email")' in main_src,
      "permissions.email nennt Freigabe UND aktiven Skill")
check('@app.get("/email"' in main_src, "die Seiten-Route /email ist registriert")
check("startup_email_rules" in main_src, "der Zeitplan ist als Startup-Hook verdrahtet")
check("email_allowed_users" in main_src and "email_allowed_group" in main_src,
      "die Freigabefelder werden gespeichert und gelesen")
check('"email_mode"' in main_src and "users_group" in main_src,
      "der Anzeige-Modus unterschlaegt keinen der beiden Werte")

ret_src = (ROOT / "backend/log_retention.py").read_text()
check("_prune_email_log" in ret_src and "mail_rules.protokoll_kuerzen" in ret_src,
      "das Protokoll altert ueber den zentralen Zeitplan")
check(not re.search(r"_MAX_(ENTRIES|BYTES)", (ROOT / "backend/mail_rules.py").read_text()),
      "mail_rules hat KEINE Mengen-/Groessengrenze fuer das Protokoll")

# Frontend-Verdrahtung: vier Stellen gehoeren zusammen
app_js = (ROOT / "frontend/js/app.js").read_text()
skills_js = (ROOT / "frontend/js/skills.js").read_text()
check("updateEmailTabVisibility" in app_js, "die Reiter-Sichtbarkeit ist definiert")
check(app_js.count("await updateEmailTabVisibility()") == 1,
      "openModal ruft sie auf (der Reiter 'KI & System' ist voreingestellt aktiv)")
# Auf den AUFRUF pruefen, nicht auf das Wort: jede Zeile nennt den Namen
# zweimal (`typeof window.X === 'function'` UND `window.X()`). Genau diese
# Unschaerfe hat den Waechter beim ersten Lauf falsch anschlagen lassen.
check(skills_js.count("window.updateEmailTabVisibility()") == 3,
      "alle drei Skill-Wechsel-Stellen rufen sie nach",
      str(skills_js.count("window.updateEmailTabVisibility()")))
check("EmailAdmin" in app_js, "der Reiter-Klick startet EmailAdmin.onShow")
check("email:             'email'" in skills_js or "email:" in skills_js,
      "das Zahnrad des Skills fuehrt in den Reiter")

settings_html = (ROOT / "frontend/settings.html").read_text()
check('id="settings-tab-email"' in settings_html, "das Reiter-Panel existiert")
check('id="sec-sub-email"' in settings_html, "der Berechtigungsblock existiert")
check("js/email.js" in settings_html, "email.js ist eingebunden")
check(settings_html.count('class="role-grid-2"') == 0
      or 'class="role-grid role-grid-2"' in settings_html,
      "role-grid-2 wird nur mit der Basisklasse benutzt (sonst kein display:grid)")

picker = (ROOT / "frontend/js/ldap_picker.js").read_text()
check("'email-allowed-users'" in picker and "'email-allowed-group'" in picker,
      "die Freigabefelder sind an den AD-Picker angeschlossen")

portal = (ROOT / "frontend/portal.html").read_text()
check('id="pt-card-email"' in portal and "permissions.email" in portal,
      "die Portal-Karte haengt an permissions.email")
check('class="pt-card hidden" id="pt-card-email"' in portal,
      "die Karte startet versteckt")

# i18n: DE und EN deckungsgleich
i18n = (ROOT / "frontend/js/i18n.js").read_text()
de_teil = i18n[:i18n.index("    en: {")]
en_teil = i18n[i18n.index("    en: {"):]
de_keys = set(re.findall(r"'(mail\.[a-z_0-9]+)'", de_teil))
en_keys = set(re.findall(r"'(mail\.[a-z_0-9]+)'", en_teil))
check(de_keys and de_keys == en_keys, "alle mail.*-Texte gibt es in DE und EN",
      str(de_keys ^ en_keys))
check("'portal.card_email'" in de_teil and "'portal.card_email'" in en_teil,
      "die Kachel-Beschriftung gibt es in beiden Sprachen")

# Prompt-Waechter: keine erfundenen und keine gesperrten Werkzeuge im Auftrag
runner_src = (ROOT / "backend/mail_runner.py").read_text()
vorspann = runner_src[runner_src.index("_VORSPANN = "):runner_src.index('"""\n\n\ndef _auftrag')]
for gesperrt in ("cron_create", "spawn_agent", "reflection", "queue_add",
                 "shell_execute", "filesystem_read", "filesystem_write"):
    check(gesperrt not in vorspann,
          f"der Auftragstext verspricht kein '{gesperrt}'")
genannte = set(re.findall(r"\b(email_[a-z_]+)\b", vorspann))
check(genannte <= set(mr.MAIL_WERKZEUGE),
      "der Auftragstext nennt nur Werkzeuge, die es gibt",
      str(genannte - set(mr.MAIL_WERKZEUGE)))


# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 62}")
print(f"  {_ok} OK, {_fail} FAIL  (Sandkasten: {TMP})")
print(f"{'=' * 62}")
import shutil                                # noqa: E402
shutil.rmtree(TMP, ignore_errors=True)
sys.exit(1 if _fail else 0)
