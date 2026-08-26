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
section("3. Antwort-Format: Wahl > Postfach > HTML")
# ═══════════════════════════════════════════════════════════════════════════
W = "fmtuser"
# Vorgabe ist seit 2026-08-26 HTML (Entscheidung des Nutzers, vorher Text): eine
# Signatur mit Logo, Links und Farben wird im Textformat plattgeklopft.
check(ma.format_fuer(W) == "html", "ohne alles gilt HTML")
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
check(ma.format_fuer(W) == "html", "leer ist gueltig und heisst 'keine Vorgabe' = HTML")
# Text muss AUSDRUECKLICH waehlbar bleiben - sonst waere die Umstellung eine
# Abschaffung. Ein gespeichertes "text" gewinnt gegen die neue Vorgabe.
ma.speichern(W, {"antwort_format": "text"})
check(ma.format_fuer(W) == "text", "ein gespeichertes 'text' gewinnt gegen die Vorgabe")
check(ma.format_fuer(W, "html") == "html", "... und die Wahl pro Antwort dagegen")
ma.speichern(W, {"antwort_format": ""})
# Die Oberflaeche darf die Vorgabe nicht anders benennen als der Server sie
# rechnet: LEER heisst HTML, also muss auf 'text' geprueft werden. Eine Pruefung
# auf 'html' zeigte an einem unberuehrten Postfach "Nur Text", waehrend HTML
# hinausgeht - eine Anzeige, die einen Zustand behauptet, den sie nicht kennt.
for name, _pfad in (("addin.js", ROOT / "frontend" / "addin" / "addin.js"),
                    ("email_portal.js", ROOT / "frontend" / "js" / "email_portal.js")):
    _js = _pfad.read_text(encoding="utf-8")
    # Auf das FELD pruefen, nicht auf "=== 'html'" irgendwo: in derselben
    # Funktion steht `gewaehlt === 'html'` fuer die vorausgewaehlte Option -
    # ein grobes Muster meldet die als Verstoss (beim ersten Lauf genau so
    # passiert). Kommentare raus, sonst liest der Waechter die Begruendung mit.
    _fo = _ohne_kommentare(
        _js.split("function formatOptionen", 1)[1].split("\n    }", 1)[0])
    check("antwort_format === 'text'" in _fo or "antwort_format || '') === 'text'" in _fo,
          "%s: das Vorgabe-Etikett prueft auf 'text'" % name)
    check("antwort_format === 'html'" not in _js
          and "antwort_format || '') === 'html'" not in _js,
          "%s: keine Stelle vergleicht antwort_format mit 'html' "
          "(leer waere dort sonst 'Nur Text')" % name)
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
                ("post", "/api/email/signatures/import"),
                ("put", "/api/email/signatures/{sig_id}"),
                ("delete", "/api/email/signatures/{sig_id}")):
    check('@app.%s("%s")' % (m, pfad) in MAIN, "Route %s %s" % (m.upper(), pfad))
# Ausschnitt EINSCHLIESSLICH des ersten Dekorators. Ein `split()` haette ihn
# verschluckt - die Route waere dann nicht zaehlbar, ihr `Depends` aber schon,
# und der Zaehlvergleich unten haette eine unerklaerliche Differenz von 1.
_von = MAIN.index('@app.get("/api/email/signatures")')
_sig = MAIN[_von:MAIN.index('@app.post("/api/email/test")', _von)]
# ZAEHLEN statt einer festen Zahl: eine "== 4" bricht bei jedem neuen Endpunkt
# in diesem Block und verleitet dann dazu, die Zahl hochzusetzen, statt die
# Dependency zu pruefen. Geprueft wird die REGEL - jede Route hier haengt an
# require_email_access -, damit faellt auch eine kuenftige auf.
_sig_routen = len(re.findall(r"@app\.(?:get|post|put|delete)\(", _sig))
check(_sig_routen >= 5, "der Signatur-Block enthaelt alle Routen (%d)" % _sig_routen)
check(_sig.count("Depends(require_email_access)") == _sig_routen,
      "JEDE Route im Signatur-Block haengt an require_email_access "
      "(%d Routen)" % _sig_routen)
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



# ═══════════════════════════════════════════════════════════════════════════
section("9. Signatur aus dem Postfach uebernehmen (2026-08-26)")
# ═══════════════════════════════════════════════════════════════════════════
# Der Auslöser: das Postfach HAT eine Signatur (Exchange haelt sie in der
# UserConfiguration "OWA.UserOptions"), Jarvis hat sie nur nie abgeholt - und im
# Pulldown stand deshalb ausschliesslich "keine Signatur".

# --- der Lesezugriff ---
_ews = CLIENT.split("class _Ews", 1)[1].split("\nclass ", 1)[0]
_sigl = _ews.split("def signatur_lesen", 1)[1].split("\n    def ", 1)[0]
check("OWA.UserOptions" in _ews, "der EWS-Kanal kennt das Konfigurationsobjekt")
check("acc.root." in _ohne_kommentare(_sigl),
      "gelesen wird aus dem ROOT (msg_folder_root liefert ErrorItemNotFound)")
check("ErrorItemNotFound" in _sigl,
      "'es gibt keine' wird als AUSKUNFT behandelt, nicht als Fehler")
# Die Kategorie muss stimmen, sonst kann der Endpunkt nicht unterscheiden.
_sigl_c = _ohne_kommentare(_sigl)
check("lower()" in _sigl_c and "signaturetext" in _sigl_c,
      "die Schluessel werden ohne Ruecksicht auf Gross/Klein gesucht")
# `autoaddsignature` kommt als Zeichenkette "False" herein - bool("False") ist True.
check('("true", "1")' in _sigl_c,
      "autoaddsignature wird als TEXT ausgewertet, nicht per bool()")
_imap = CLIENT.split("class _Imap", 1)[1].split("\n_OPERATIONEN", 1)[0]
check("def signatur_lesen" in _imap, "der IMAP-Kanal hat den Vorgang ebenfalls")
_isig = _ohne_kommentare(_imap.split("def signatur_lesen", 1)[1].split("\n    def ", 1)[0])
check("raise MailFehler" in _isig and '"leer"' not in _isig,
      "IMAP sagt es im Klartext, statt 'leer' zu behaupten (das weiss es nicht)")
check('"signatur_lesen"' in CLIENT.split("_OPERATIONEN", 1)[1][:400],
      "der Vorgang steht in _OPERATIONEN (sonst weist die Fassade ihn ab)")

# --- die Uebernahme ---
ACC2 = (ROOT / "backend" / "mail_accounts.py").read_text(encoding="utf-8")
_ueb = ACC2.split("def sig_uebernehmen", 1)[1].split("\ndef ", 1)[0]
_uebc = _ohne_kommentare(_ueb)
check("SIG_IMPORT_NAME" in ACC2, "der Name der uebernommenen Signatur ist FEST")
# Zu lang muss ABGELEHNT werden. sig_anlegen schneidet still auf die Grenze -
# bei HTML faellt der Schnitt mitten in ein Tag und niemand sieht es.
check("SIG_TEXT_MAX" in _uebc and "SIG_HTML_MAX" in _uebc and "raise" in _uebc,
      "zu grosse Signaturen werden abgelehnt, nicht gekuerzt")

konto_probe = "uebernahme.test"
ma.speichern(konto_probe, {"adresse": "u@example.org", "passwort": "geheim"})
liste, sid, art = ma.sig_uebernehmen(konto_probe, "Gruss\nA. B.", "<p>Gruss</p>")
check(art == "neu" and len(liste) == 1, "erste Uebernahme legt an", art)
check(liste[0]["name"] == ma.SIG_IMPORT_NAME, "... unter dem festen Namen")
check(liste[0]["standard"] is True,
      "... und wird Standard, weil es die einzige ist (sonst waere sie wirkungslos)")
try:
    ma.sig_uebernehmen(konto_probe, "Neu", "")
    check(False, "zweite Uebernahme ohne 'ersetzen' wird abgelehnt")
except MailFehler as f:
    check(f.kategorie == "vorhanden",
          "zweite Uebernahme ohne 'ersetzen' wird abgelehnt (Kategorie 'vorhanden')",
          f.kategorie)
liste2, sid2, art2 = ma.sig_uebernehmen(konto_probe, "Neu\nA. B.", "<p>Neu</p>", True)
check(art2 == "aktualisiert" and len(liste2) == 1,
      "mit 'ersetzen' wird aufgefrischt statt danebengelegt", art2)
check(sid2 == sid, "... unter DERSELBEN Kennung (Regeln zeigen weiter darauf)")
check(liste2[0]["text"] == "Neu\nA. B.", "... und der Text ist der neue")
try:
    ma.sig_uebernehmen(konto_probe, "x" * (ma.SIG_TEXT_MAX + 1), "", True)
    check(False, "zu langer Text wird abgelehnt")
except MailFehler as f:
    check(str(ma.SIG_TEXT_MAX) in str(f),
          "zu langer Text wird abgelehnt UND nennt die Grenze", str(f)[:60])
try:
    ma.sig_uebernehmen("leer.test", "", "")
    check(False, "leere Signatur wird abgelehnt")
except MailFehler:
    check(True, "ein leeres Postfach-Feld wird abgelehnt (kein leerer Eintrag)")

# --- der Endpunkt ---
check('@app.post("/api/email/signatures/import")' in MAIN, "Route POST …/import")
_imp = MAIN.split('@app.post("/api/email/signatures/import")', 1)[1].split(
    "\n@app.", 1)[0]
_impc = _ohne_kommentare(_imp)
check("Depends(require_email_access)" in _imp, "… haengt an require_email_access")
check("409" in _impc, "… antwortet 409, wenn es etwas ueberschreiben wuerde")
# Der Benutzer kommt aus der Anmeldung, NIE aus dem Rumpf - sonst waere der
# Endpunkt ein Weg, in ein fremdes Postfach zu sehen.
for feld in ('"user"', '"benutzer"', '"adresse"', '"postfach"'):
    check("get(%s)" % feld not in _impc,
          "… nimmt %s NICHT aus dem Rumpf" % feld)
check("asyncio.to_thread" in _impc,
      "… laeuft im Thread (EWS blockiert, sonst friert der Event-Loop ein)")

# --- Oberflaeche: beide Wege, und der Kopie-Hinweis ist Pflicht ---
for name, js, html, praefix in (("addin", ADDJS, ADDHTML, "ad"),
                                ("portal", EMJS, EMHTML, "em")):
    check('id="%s-sig-import"' % praefix in html, "%s: Knopf vorhanden" % name)
    check("/api/email/signatures/import" in js, "%s: Knopf ruft den Endpunkt" % name)
    check('data-i18n="mail.sig_import_hint"' in html,
          "%s: der Kopie-Hinweis steht dabei (kein Abgleich wird versprochen)" % name)
    # 409 muss ueber den STATUS erkannt werden, nicht am Meldungstext.
    check("status === 409" in js or "status == 409" in js,
          "%s: die Rueckfrage haengt am Status, nicht am Text" % name)
    check("f.status = r.status" in js,
          "%s: der Fetch-Helfer reicht den Status durch" % name)
# Im Aufgabenfenster ist `confirm` unterdrueckt - dort MUSS `frage()` benutzt
# werden, sonst bricht der Knopf wortlos ab (Register).
_uebjs = ADDJS.split("function uebernehmeSig", 1)[1].split("\n    function ", 1)[0]
check("frage(" in _uebjs and "confirm(" not in _uebjs,
      "addin: Rueckfrage ueber frage(), nicht ueber confirm()")
check("zeichneNachricht()" in _uebjs,
      "addin: das Signatur-Pulldown im Reiter 'Nachricht' wird nachgezogen")
# Verlorene Bilder werden BEZIFFERT. Eine in Outlook gebaute Signatur verweist
# ihr Logo auf einen lokalen Pfad des Absenders (an der echten Signatur
# gemessen: file:///C:/Users/…/clip_image002.png) - der Server kann den nicht
# aufloesen. Ohne die Zahl fehlt hinterher das Logo und nichts erklaert warum.
_roh_img = ('<p>Gru&szlig;</p><img src="file:///C:/Users/x/clip_image002.png" '
            'width="30"><img src="https://example.org/logo.png">')
_sicher, _ber = mb.html_entschaerfen_mit_bericht(_roh_img)
check(_ber["bilder_weg"] == 1,
      "der Bericht zaehlt genau das Bild mit unbrauchbarer Quelle",
      str(_ber))
check("example.org/logo.png" in _sicher and "file:///" not in _sicher,
      "... das https-Bild bleibt, das file:-Bild faellt heraus")
check(mb.html_entschaerfen(_roh_img) == _sicher,
      "html_entschaerfen liefert unveraendert dasselbe (keine zweite Fassung)")
check('"bilder_weg"' in _impc, "der Endpunkt gibt die Zahl heraus")
for name, js in (("addin", ADDJS), ("portal", EMJS)):
    check("bilder_weg" in js and "mail.sig_import_imgs" in js,
          "%s: die Meldung nennt die nicht uebernommenen Bilder" % name)

for k in ("mail.sig_import", "mail.sig_import_hint", "mail.sig_import_run",
          "mail.sig_import_new", "mail.sig_import_upd", "mail.sig_import_ask",
          "mail.sig_import_yes", "mail.sig_import_imgs"):
    check(I18N.count("'%s'" % k) == 2, "i18n %s in DE UND EN" % k,
          str(I18N.count("'%s'" % k)))


print(f"\n{'='*62}\n  {_ok} OK, {_fail} FAIL  (Sandkasten: {TMP})\n{'='*62}")
sys.exit(1 if _fail else 0)
