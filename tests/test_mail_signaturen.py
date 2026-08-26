#!/usr/bin/env python3
"""Signaturen + Antwort-Format fuer den E-Mail-Bereich (2026-08-26).

GEMELDET: "in dem Outlook-Add-In werden aktuell Entwuerfe im Text Format
erstellt. 'HTML', 'Text' und 'Rich-Text' sollten waehlbar sein. Ausserdem soll
auswaehlbar eine Signatur sein."

DIE SICHERHEITSAUSSAGE, die dieser Test festhaelt – sie ist der Grund, aus dem
Signaturen NICHT einfach ein weiterer Stil sind:

    Ein STIL ist eine Anweisung an das Modell (er geht in den Auftrag).
    Eine SIGNATUR ist ein fester Text (sie wird hinter die fertige Antwort
    gesetzt und laeuft NIE durch ein Modell).

Eine Signatur traegt Pflichtangaben – Rechtsform, Registergericht,
Geschaeftsfuehrung. Ein Modell, das sie "mitschreibt", formuliert sie um, und
bei einer Regel liest niemand gegen. Daraus folgen drei Dinge, die hier geprueft
werden: kein Werkzeug-Parameter (das Modell darf nicht waehlen), keine Erkennung
aus dem Prompt, und angehaengt wird erst beim Senden.

Laeuft ohne fastapi und ohne Netz (Muster von test_mail_styles.py):
``backend.config`` ist eine Attrappe, ein Sandkasten-Waechter bricht mit Exit 2
ab, wenn ein Modulpfad noch auf ``data/`` des Repos zeigt.

Exit 2 = konnte nicht laufen, 1 = Pruefung fehlgeschlagen, 0 = bestanden.

    python3 tests/test_mail_signaturen.py
"""
import ast
import re
import sys
import tempfile
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


# ── Attrappe fuer backend.config VOR dem Import ────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="mail_sig_"))
(TMP / "data").mkdir(parents=True)

_skill_states = {"email": {"enabled": True, "config": {"bereiche": "mail"}}}
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
from backend import mail_body as mb          # noqa: E402
from backend import mail_rules as mr         # noqa: E402
from backend.mail_client import MailFehler   # noqa: E402

ma.DATA_DIR = TMP / "data"
ma.KONTEN_DATEI = TMP / "data" / "email_accounts.json"
ma.SCHLUESSEL_DATEI = TMP / "data" / ".mailkey"
mr.DATA_DIR = TMP / "data"
mr.REGEL_DATEI = TMP / "data" / "email_rules.json"
mr.ZUSTAND_DATEI = TMP / "data" / "email_state.json"
mr.PROTOKOLL_DATEI = TMP / "data" / "email_log.jsonl"

_ECHTES_DATA = ROOT / "data"
for _modul in (ma, mr):
    for _name in dir(_modul):
        _wert = getattr(_modul, _name)
        if isinstance(_wert, Path) and _name.isupper() and _name != "PROJECT_ROOT":
            try:
                _drin = _wert == _ECHTES_DATA or _ECHTES_DATA in _wert.parents
            except Exception:  # noqa: BLE001
                _drin = False
            if _drin:
                print(f"SANDKASTEN VERLETZT: {_modul.__name__}.{_name} = {_wert}")
                sys.exit(2)
for _pfad in (ma.KONTEN_DATEI, ma.SCHLUESSEL_DATEI, mr.REGEL_DATEI):
    if not str(_pfad).startswith(str(TMP)):
        print(f"SANDKASTEN VERLETZT: {_pfad} liegt nicht im Wegwerf-Verzeichnis")
        sys.exit(2)

U = "siguser"
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
RUNNER = (ROOT / "backend" / "mail_runner.py").read_text(encoding="utf-8")
CLIENT = (ROOT / "backend" / "mail_client.py").read_text(encoding="utf-8")
SKILL = (ROOT / "skills" / "email" / "main.py").read_text(encoding="utf-8")
ACCS = (ROOT / "backend" / "mail_accounts.py").read_text(encoding="utf-8")


def _ohne_kommentare(code: str) -> str:
    """Kommentare und Docstrings weg.

    PFLICHT, NICHT KOSMETIK: die Begruendungen in diesem Bereich nennen genau
    die Dinge, gegen die geprueft wird ("kein Werkzeug-Parameter", "signatur").
    Ein Waechter, der seine eigene Begruendung liest, prueft nichts.
    """
    code = re.sub(r'"""(?:.|\n)*?"""', "", code)
    code = re.sub(r"'''(?:.|\n)*?'''", "", code)
    return "\n".join(z for z in code.split("\n")
                     if not z.strip().startswith("#"))


# ═══════════════════════════════════════════════════════════════════════════
section("1. Signaturen verwalten")
# ═══════════════════════════════════════════════════════════════════════════
check(ma.signaturen(U) == [], "frisches Postfach hat keine Signatur")
liste = ma.sig_anlegen(U, "Standard", "Max Mustermann\nNexus AG")
check(len(liste) == 1 and liste[0]["standard"] is True,
      "die ERSTE Signatur wird automatisch Standard")
sid1 = liste[0]["id"]
liste = ma.sig_anlegen(U, "Kurz", "Gruesse, Max")
check(len(liste) == 2 and not liste[1]["standard"],
      "die zweite ist NICHT automatisch Standard")
sid2 = liste[1]["id"]

try:
    ma.sig_anlegen(U, "kurz", "x")
    check(False, "doppelter Name wird abgelehnt")
except MailFehler:
    check(True, "doppelter Name wird abgelehnt (auch in anderer Schreibweise)")
try:
    ma.sig_anlegen(U, "", "x")
    check(False, "leerer Name wird abgelehnt")
except MailFehler:
    check(True, "leerer Name wird abgelehnt")
try:
    ma.sig_anlegen(U, "x" * (ma.SIG_NAME_MAX + 5), "x")
    check(False, "zu langer Name wird abgelehnt")
except MailFehler:
    check(True, "zu langer Name wird abgelehnt")

liste = ma.sig_aendern(U, sid2, {"standard": True})
check([e["standard"] for e in liste] == [False, True],
      "genau EIN Standard – der alte verliert die Markierung")
liste = ma.sig_aendern(U, sid1, {"text": ""})
check(liste[0]["text"] == "",
      "ein LEERER Text ist eine gueltige Aenderung (der Benutzer sieht ihn)")
liste = ma.sig_aendern(U, sid1, {"html": "<p>Max</p>"})
check(liste[0]["html"] == "<p>Max</p>", "die HTML-Fassung wird gespeichert")
try:
    ma.sig_aendern(U, "gibtsnicht", {"name": "x"})
    check(False, "unbekannte Kennung wird abgelehnt")
except MailFehler:
    check(True, "unbekannte Kennung wird abgelehnt")

# Deckel
lang = ma.sig_aendern(U, sid1, {"text": "y" * (ma.SIG_TEXT_MAX + 500)})
check(len(lang[0]["text"]) == ma.SIG_TEXT_MAX, "Textdeckel greift")
lang = ma.sig_aendern(U, sid1, {"html": "z" * (ma.SIG_HTML_MAX + 500)})
check(len(lang[0]["html"]) == ma.SIG_HTML_MAX, "HTML-Deckel greift")
check(ma.SIG_HTML_MAX > ma.SIG_TEXT_MAX,
      "der HTML-Deckel ist groesser (ein eingebettetes Logo ist Kilobyte)")

# Loeschen: es rueckt KEINER nach.
liste = ma.sig_loeschen(U, sid2)
check(len(liste) == 1 and not liste[0]["standard"],
      "nach dem Loeschen des Standards rueckt KEINE Signatur nach")
try:
    ma.sig_loeschen(U, sid2)
    check(False, "zweites Loeschen wird abgelehnt")
except MailFehler:
    check(True, "zweites Loeschen wird abgelehnt")

# Obergrenze
for i in range(ma.MAX_SIGNATUREN):
    try:
        ma.sig_anlegen(U, "S%d" % i, "x")
    except MailFehler:
        break
check(len(ma.signaturen(U)) == ma.MAX_SIGNATUREN,
      "hoechstens MAX_SIGNATUREN Eintraege", str(len(ma.signaturen(U))))


# ═══════════════════════════════════════════════════════════════════════════
section("2. signatur_fuer: die Reihenfolge IST die Bedeutung")
# ═══════════════════════════════════════════════════════════════════════════
V = "sigwahl"
l = ma.sig_anlegen(V, "Standard", "STD-TEXT")
std_id = l[0]["id"]
l = ma.sig_anlegen(V, "Englisch", "EN-TEXT")
en_id = l[1]["id"]

e = ma.signatur_fuer(V, en_id)
check(e["text"] == "EN-TEXT" and e["quelle"] == "feld", "ausdrueckliche Wahl gewinnt")
e = ma.signatur_fuer(V, "")
check(e["text"] == "STD-TEXT" and e["quelle"] == "standard",
      "nichts gewaehlt -> Standardsignatur")
e = ma.signatur_fuer(V, ma.SIG_KEINER)
check(e["text"] == "" and e["quelle"] == "keiner",
      "'-' heisst ausdruecklich KEINE Signatur (unterscheidbar von leer)")
e = ma.signatur_fuer(V, "verwaist")
check(e["text"] == "STD-TEXT" and e["hinweis"],
      "verwaiste Kennung -> Standard MIT Hinweis (der Lauf laeuft weiter)")
e = ma.signatur_fuer("niemand", "")
check(e["text"] == "" and not e["hinweis"], "Benutzer ohne Signaturen: leer")
check(set(ma.signatur_fuer(V, "").keys()) >=
      {"id", "name", "text", "html", "quelle", "hinweis"},
      "die Rueckgabe ist IMMER vollstaendig (kein None-Zweig)")

# KEINE Erkennung aus dem Prompt - anders als beim Stil.
check(not hasattr(ma, "signatur_aus_prompt"),
      "es gibt KEIN signatur_aus_prompt (Namen wie 'Standard' traefen ueberall)")
_sfk = _ohne_kommentare(ACCS.split("def signatur_fuer", 1)[1].split("\ndef ", 1)[0])
check("prompt" not in _sfk.lower(),
      "signatur_fuer kennt keinen Prompt-Parameter", _sfk[:120])


# ═══════════════════════════════════════════════════════════════════════════
section("3. Antwort-Format: Wahl > Postfach > Text")
# ═══════════════════════════════════════════════════════════════════════════
W = "fmtuser"
check(ma.format_fuer(W) == "text",
      "ohne alles gilt TEXT (= Verhalten vor dieser Aenderung)")
check(ma.format_fuer(W, "html") == "html", "die Wahl gewinnt")
ma.speichern(W, {"antwort_format": "html"})
check(ma.format_fuer(W) == "html", "Vorgabe des Postfachs wirkt")
check(ma.format_fuer(W, "text") == "text", "die Wahl gewinnt auch dagegen")
check(ma.format_fuer(W, "richtext") == "html",
      "ein UNGUELTIGER Wert faellt auf die Vorgabe, nicht auf einen geratenen")
try:
    ma.speichern(W, {"antwort_format": "richtext"})
    check(False, "Rich-Text wird beim Speichern abgelehnt")
except MailFehler as f:
    check("EWS" in str(f) or "html" in str(f).lower(),
          "Rich-Text wird abgelehnt UND begruendet", str(f))
try:
    ma.speichern(W, {"antwort_format": "murks"})
    check(False, "unbekanntes Format wird abgelehnt")
except MailFehler:
    check(True, "unbekanntes Format wird abgelehnt (nicht still verworfen)")
ma.speichern(W, {"antwort_format": ""})
check(ma.format_fuer(W) == "text", "leer ist gueltig und heisst Text")
check("antwort_format" in ma.AENDERBAR and "signaturen" not in ma.AENDERBAR,
      "das Format darf ans Formular, die LISTE nicht")
check("signaturen" in ma.konto_info(V) and "antwort_format" in ma.konto_info(V),
      "konto_info liefert beides an die Oberflaeche")


# ═══════════════════════════════════════════════════════════════════════════
section("4. Regelfelder: signatur und format")
# ═══════════════════════════════════════════════════════════════════════════
R = "regeluser"
rl = ma.sig_anlegen(R, "Standard", "STD")
rsig = rl[0]["id"]
regel = mr.anlegen(R, {"name": "T", "prompt": "Antworte kurz.", "ordner": "INBOX",
                       "signatur": rsig, "format": "html"})
check(regel["signatur"] == rsig and regel["format"] == "html",
      "beide Felder werden gespeichert")
check("signatur" in mr.AENDERBAR and "format" in mr.AENDERBAR,
      "beide stehen in der Whitelist (sonst waeren sie per PUT nicht aenderbar)")
try:
    mr.aendern(regel["id"], {"format": "richtext"}, owner=R)
    check(False, "Rich-Text an einer Regel wird abgelehnt")
except mr.RegelFehler as f:
    check("EWS" in str(f) or "HTML" in str(f),
          "Rich-Text an einer Regel wird abgelehnt UND begruendet", str(f))
try:
    mr.aendern(regel["id"], {"signatur": "gibtsnicht"}, owner=R)
    check(False, "unbekannte Signatur-Kennung wird abgelehnt")
except mr.RegelFehler:
    check(True, "unbekannte Signatur-Kennung wird abgelehnt")
try:
    mr.aendern(regel["id"], {"signatur": "boese/../x"}, owner=R)
    check(False, "unsaubere Kennung wird abgelehnt")
except mr.RegelFehler:
    check(True, "unsaubere Kennung wird abgelehnt")
g = mr.aendern(regel["id"], {"signatur": ma.SIG_KEINER}, owner=R)
check(g["signatur"] == ma.SIG_KEINER, "'-' ist an einer Regel erlaubt")
g = mr.aendern(regel["id"], {"format": ""}, owner=R)
check(g["format"] == "", "leeres Format = Vorgabe des Postfachs")


# ═══════════════════════════════════════════════════════════════════════════
section("5. Der Weg zum Versand (Quelltext)")
# ═══════════════════════════════════════════════════════════════════════════
# antwort_senden haengt die Signatur an – NACH dem Modell, NACH der Freigabe.
_as = RUNNER.split("async def antwort_senden", 1)[1].split("\nasync def ", 1)[0]
_asc = _ohne_kommentare(_as)
check("signatur_fuer" in _asc and "signatur_anhaengen" in _asc,
      "antwort_senden loest die Signatur auf und haengt sie an")
check("format_fuer" in _asc, "... und loest das Format auf")
check("html=rumpf_html" in _asc.replace(" ", ""),
      "... und gibt das HTML an den Client weiter")
check("run_task" not in _asc and "provider" not in _asc,
      "in antwort_senden laeuft KEIN Sprachmodell")
# Die Vorschau darf die Signatur NICHT in den Text schreiben: was im Textfeld
# steht, ist bearbeitbar - eine Pflichtangabe darf das nicht sein.
_av = RUNNER.split("async def antwort_vorschlag", 1)[1].split("\nasync def ", 1)[0]
check("signatur_anhaengen" not in _av,
      "der VORSCHLAG haengt keine Signatur an (sie darf nicht bearbeitbar sein)")
check("signatur" not in _ohne_kommentare(_av).lower(),
      "der Vorschlags-Auftrag kennt die Signatur ueberhaupt nicht")

# Der EWS-Zweig entscheidet den BodyType an der Klasse des Wertes.
check("HTMLBody" in CLIENT, "der EWS-Zweig benutzt HTMLBody")
_ews = CLIENT.split("def _rumpf", 1)[1].split("\n    def antworten", 1)[0]
check("HTMLBody" in _ews and "return text" in _ews,
      "_rumpf: HTMLBody bei HTML, sonst reiner Text")
check("add_alternative" in CLIENT,
      "der IMAP-Zweig baut multipart/alternative (der Textteil bleibt)")
check("html: str" in CLIENT.split("class _Dispatcher", 1)[-1] or
      "html=html" in CLIENT, "der Dispatcher reicht html durch")

# Das WERKZEUG: Format und Signatur kommen aus dem LAUF, nie aus Argumenten.
_tool = SKILL.split("class EmailAntwortenTool", 1)[1].split("\nclass ", 1)[0]
_schema = _tool.split("parameters_schema", 1)[1].split("async def", 1)[0]
for feld in ("signatur", "signature", "format", "html", "benutzer", "postfach"):
    check('"%s"' % feld not in _schema,
          "das Werkzeug-Schema hat KEIN Feld '%s' (sonst waehlt das Modell)" % feld)
_toolc = _ohne_kommentare(_tool)
check("current_antwort_signatur" in _toolc and "current_antwort_format" in _toolc,
      "das Werkzeug liest beide aus dem Lauf-Kontext")
check("signatur_anhaengen" in _toolc,
      "... und haengt die Signatur deterministisch an")

# Der Regel-Lauf setzt die ContextVars und nimmt sie zurueck.
_lauf = RUNNER.split("async def _lauf_fuer_nachricht", 1)[1].split("\nasync def ", 1)[0]
check("current_antwort_signatur.set" in _lauf and "current_antwort_format.set" in _lauf,
      "der Regel-Lauf setzt Format und Signatur der Regel")
check(".reset(" in _lauf.split("finally", 1)[-1],
      "... und nimmt sie im finally zurueck (sonst haengen sie am geteilten Agenten)")


# ═══════════════════════════════════════════════════════════════════════════
section("6. Endpunkte")
# ═══════════════════════════════════════════════════════════════════════════
for m, pfad in (("get", "/api/email/signatures"), ("post", "/api/email/signatures"),
                ("put", "/api/email/signatures/{sig_id}"),
                ("delete", "/api/email/signatures/{sig_id}")):
    check('@app.%s("%s")' % (m, pfad) in MAIN, "Route %s %s" % (m.upper(), pfad))
_sig = MAIN.split('@app.get("/api/email/signatures")', 1)[1].split(
    '@app.post("/api/email/test")', 1)[0]
check(_sig.count("Depends(require_email_access)") == 4,
      "alle vier Signatur-Endpunkte haengen an require_email_access")
check('"name", "text", "html", "standard"' in _sig,
      "PUT hat eine Feld-Whitelist (kein beliebiges Feld)")
# reply/send nimmt Format und Signatur - aber NICHT den Signaturtext.
_rs = MAIN.split('@app.post("/api/email/reply/send")', 1)[1].split("\n@app.", 1)[0]
check('"format"' in _rs and '"signatur"' in _rs,
      "reply/send liest Format und Signatur-KENNUNG")
_rsc = _ohne_kommentare(_rs)
check('"signatur_text"' not in _rsc and '"html"' not in _rsc,
      "reply/send nimmt KEINEN Signaturtext und kein HTML aus dem Rumpf "
      "(sonst waere es ein Weg, ungesehenen Text in eine Mail zu setzen)")
# Namensraum-Waechter: die Routen liegen unter /api/email/, also beim Benutzer -
# sie duerfen NICHT auf Admin-Ebene liegen (sonst pflegt niemand seine Signatur).
check("require_local_auth" not in _sig,
      "die Signatur-Endpunkte sind NICHT Admin-only (jeder pflegt seine eigene)")


# ═══════════════════════════════════════════════════════════════════════════
section("7. Oberflaeche: Rich-Text sichtbar, aber abgeschaltet")
# ═══════════════════════════════════════════════════════════════════════════
ADDJS = (ROOT / "frontend" / "addin" / "addin.js").read_text(encoding="utf-8")
ADDHTML = (ROOT / "frontend" / "addin" / "taskpane.html").read_text(encoding="utf-8")
EMJS = (ROOT / "frontend" / "js" / "email_portal.js").read_text(encoding="utf-8")
EMHTML = (ROOT / "frontend" / "email.html").read_text(encoding="utf-8")
I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")

for name, quelle in (("addin.js", ADDJS), ("email_portal.js", EMJS)):
    _fo = quelle.split("function formatOptionen", 1)
    check(len(_fo) == 2, "%s hat formatOptionen" % name)
    if len(_fo) == 2:
        blk = _fo[1].split("\n    }", 1)[0]
        check('value="richtext"' in blk and "disabled" in blk,
              "%s: Rich-Text steht im Pulldown und ist abgeschaltet" % name)
        check("fmt_rtf_why" in blk,
              "%s: ... mit Begruendung am Eintrag" % name)
for name, quelle in (("taskpane.html", ADDHTML), ("email.html", EMHTML)):
    check('value="richtext" disabled' in quelle,
          "%s: auch die Postfach-Vorgabe zeigt Rich-Text abgeschaltet" % name)

# Die Signatur wird NICHT ins Textfeld geschrieben - stattdessen sagt ein
# Hinweis, WAS angehaengt wird. Ohne ihn waere sie bis zum Blick ins Postfach
# unsichtbar.
check("sig_will_append" in ADDJS and "sig_will_none" in ADDJS,
      "das Add-in nennt die Signatur, die angehaengt wird")
check("ad-reply-sig" in ADDJS and "ad-reply-fmt" in ADDJS,
      "Pulldowns fuer Signatur und Format in der Vorschau")
check("signatur:" in ADDJS.split("reply/send", 1)[1][:800] and
      "format:" in ADDJS.split("reply/send", 1)[1][:800],
      "beide werden beim Senden mitgeschickt")
# Das Postfach-Formular darf die LISTE nicht als Ganzes senden.
for name, quelle in (("addin.js", ADDJS), ("email_portal.js", EMJS)):
    _sp = quelle.split("email/account", 1)[0]
    check("signaturen:" not in quelle,
          "%s sendet niemals das Feld 'signaturen' (Listen-Ueberschreiben)" % name)

# i18n in BEIDEN Sprachen - sonst steht im englischen Portal der Schluesselname.
for k in ("mail.sigs_head", "mail.sig_new", "mail.sig_text", "mail.sig_html",
          "mail.sig_pick", "mail.fmt_pick", "mail.fmt_rtf", "mail.fmt_rtf_why",
          "mail.fmt_acct", "mail.sig_will_append", "mail.help_sigs",
          "mail.sig_rule_hint", "mail.fmt_default", "mail.fmt_text"):
    check(I18N.count("'%s'" % k) == 2, "i18n %s in DE UND EN" % k,
          str(I18N.count("'%s'" % k)))
# Das ⓘ mit eingebettetem Markup braucht data-i18n-HTML, sonst loescht der
# erste Sprachwechsel die Auszeichnung (Register).
check('data-i18n-html="mail.help_sigs"' in ADDHTML,
      "die Signatur-Erklaerung nutzt data-i18n-html (sie enthaelt <b>)")


print(f"\n{'='*62}\n  {_ok} OK, {_fail} FAIL  (Sandkasten: {TMP})\n{'='*62}")
sys.exit(1 if _fail else 0)
