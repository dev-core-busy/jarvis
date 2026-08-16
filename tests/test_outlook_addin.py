#!/usr/bin/env python3
"""Waechter fuer das Outlook-Add-in (Manifest, Endpunkte, Aufgabenfenster).

Laeuft OHNE fastapi: die Endpunkte werden per Quelltext geprueft. ``backend.config``
wird ausdruecklich NICHT importiert – der echte Import migriert Profile und
schriebe die Live-``settings.json`` zurueck. Der Test bricht mit **Exit 2** ab,
wenn das echte Modul doch geladen ist: "konnte nicht laufen" muss von
"bestanden" unterscheidbar bleiben.

Nicht abgedeckt und bewusst nicht nachgebaut: die Gueltigkeit gegen die
XML-Schemata von Microsoft. Die wurde mit dem offiziellen Werkzeug geprueft
(``npx office-addin-manifest validate``, Ergebnis "The manifest is valid.");
ein nachgebauter Schema-Test waere eine zweite Meinung, die beim naechsten
Schema-Update falsch liegt. Was hier geprueft wird, ist das, was WIR
kaputtmachen koennen: Reihenfolge, URLs, Maskierung, Rechte.
"""

import os
import re
import sys
import types
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Sandkasten: config-Stub VOR jedem Import aus backend ────────────────────
_stub = types.ModuleType("backend.config")


class _Cfg:
    def __init__(self):
        self.marke = ""

    def get_setting(self, key, vorgabe=None):
        return vorgabe

    def get_skill_states(self):
        if not self.marke:
            return {}
        return {"branding": {"enabled": True, "config": {"assistant_name": self.marke}}}


_stub.config = _Cfg()
sys.modules["backend.config"] = _stub

from backend import addin  # noqa: E402

if getattr(sys.modules.get("backend.config"), "__file__", None):
    print("ABBRUCH: das ECHTE backend.config wurde geladen – der Test wuerde die "
          "Live-settings.json zurueckschreiben.", file=sys.stderr)
    sys.exit(2)

MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
RUNNER = (ROOT / "backend" / "mail_runner.py").read_text(encoding="utf-8")
TASKPANE = (ROOT / "frontend" / "addin" / "taskpane.html").read_text(encoding="utf-8")
ADDINJS = (ROOT / "frontend" / "addin" / "addin.js").read_text(encoding="utf-8")
I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")

BASIS = "https://jarvis.example.local"
_ok = _fail = 0


def pruefe(bedingung, text):
    global _ok, _fail
    if bedingung:
        _ok += 1
    else:
        _fail += 1
        print("  FAIL: %s" % text)


def abschnitt(titel):
    print("\n── %s" % titel)


# ═══ 1. Manifest: Aufbau ════════════════════════════════════════════════════
abschnitt("1. Manifest – Aufbau und Schema-Reihenfolge")
xml_text = addin.manifest(BASIS)
root = ET.fromstring(xml_text)          # wirft, wenn nicht wohlgeformt
pruefe(root.tag.endswith("OfficeApp"), "Wurzelelement ist OfficeApp")
pruefe(root.get("{http://www.w3.org/2001/XMLSchema-instance}type") == "MailApp",
       "xsi:type=MailApp")

# Die Reihenfolge ist Schema-Vorgabe. Ein vertauschtes Element laesst Exchange
# das Manifest mit einer generischen Meldung ablehnen, die nicht sagt, welche.
ERWARTET = ["Id", "Version", "ProviderName", "DefaultLocale", "DisplayName",
            "Description", "IconUrl", "HighResolutionIconUrl", "SupportUrl",
            "AppDomains", "Hosts", "Requirements", "FormSettings", "Permissions",
            "Rule", "DisableEntityHighlighting", "VersionOverrides"]
ist = [k.tag.split("}")[-1] for k in root]
pruefe(ist == ERWARTET, "Element-Reihenfolge entspricht dem Schema: %s" % ist)

pruefe(root.find("{*}Permissions").text == "ReadItem",
       "Permissions ist ReadItem – mehr braucht das Fenster nicht")
pruefe(root.find("{*}Requirements/{*}Sets/{*}Set").get("MinVersion") == addin.MAILBOX_MIN,
       "Mailbox-MinVersion aus der Konstante")
pruefe(addin.MAILBOX_MIN in ("1.1", "1.2", "1.3"),
       "MinVersion bleibt <= 1.3 – hoeher waere auf einem Exchange im Haus "
       "nicht installierbar")
pruefe(root.find("{*}Version").text == addin.ADDIN_VERSION, "Version aus der Konstante")
pruefe(re.match(r"^\d+\.\d+\.\d+\.\d+$", addin.ADDIN_VERSION or ""),
       "Version hat die vierteilige Form, die Outlook erwartet")

# ═══ 2. Manifest: URLs ══════════════════════════════════════════════════════
abschnitt("2. Manifest – URLs")
urls = re.findall(r'DefaultValue="(https?://[^"]+)"', xml_text)
urls += [e.text for e in root.iter() if e.tag.endswith("AppDomain")]
pruefe(len(urls) >= 8, "mindestens 8 URLs im Manifest (%d)" % len(urls))
pruefe(all(u.startswith("https://") for u in urls),
       "ALLE URLs sind https – Office laedt nichts ueber http")
pruefe(all(u.startswith(BASIS) for u in urls),
       "ALLE URLs zeigen auf die uebergebene Basis (kein fremder Host)")
pruefe("%s/addin/taskpane.html" % BASIS in xml_text, "SourceLocation zeigt aufs Fenster")
pruefe("/static/addin/icon-16.png" in xml_text and "/static/addin/icon-80.png" in xml_text,
       "Menueband-Symbole in 16/32/80 vorhanden")
for grosse in (16, 32, 64, 80, 128):
    pruefe((ROOT / "frontend" / "addin" / ("icon-%d.png" % grosse)).exists(),
           "Symboldatei icon-%d.png liegt im Repo" % grosse)

# ═══ 3. Manifest: Maskierung (Branding ist Fremdeingabe) ════════════════════
abschnitt("3. Manifest – Maskierung")
_stub.config.marke = 'Nex"us & <b>Co</b>'
boese = addin.manifest(BASIS)
r2 = ET.fromstring(boese)               # muss trotzdem wohlgeformt sein
pruefe(r2.find("{*}DisplayName").get("DefaultValue").startswith('Nex"us & <b>'),
       "Sonderzeichen kommen beim Parser unveraendert an (also korrekt maskiert)")
pruefe("<b>Co</b>" not in boese, "kein rohes Markup im XML")
pruefe("&quot;" in boese, "Anfuehrungszeichen wird maskiert – escape() allein tut das NICHT")
pruefe(addin.x('a"b<c&d') == "a&quot;b&lt;c&amp;d", "x() maskiert alle vier Zeichen")
_stub.config.marke = ""

# XML verbietet "--" INNERHALB eines Kommentars, und dafuer gibt es keine
# Entity. Eine Umlaut-Domaene ist im Punycode genau so geschrieben
# (xn--mller-kva): ohne Entschaerfung waere das Manifest unlesbar, und Exchange
# meldete nur "Das Manifest ist ungueltig".
for _host in ("https://xn--mller-kva.example", "https://a--b.local"):
    try:
        _r = ET.fromstring(addin.manifest(_host))
        _urls = [e.get("DefaultValue") for e in _r.iter()
                 if (e.get("DefaultValue") or "").startswith("http")]
        pruefe(bool(_urls) and all(u.startswith(_host) for u in _urls),
               "Doppel-Bindestrich im Host: XML gueltig UND Adresse unveraendert (%s)"
               % _host)
    except Exception as _e:  # noqa: BLE001
        pruefe(False, "Doppel-Bindestrich im Host bricht das Manifest: %s (%s)"
               % (_host, _e))

# ═══ 4. Kennung und Basis-URL ═══════════════════════════════════════════════
abschnitt("4. Kennung und Basis-URL")
pruefe(addin.addin_id(BASIS) == addin.addin_id(BASIS),
       "Kennung ist stabil – sonst gilt jede Aktualisierung als neues Add-in")
pruefe(addin.addin_id("https://a.local") != addin.addin_id("https://b.local"),
       "zwei Instanzen am selben Exchange kollidieren nicht")
pruefe(addin.addin_id(BASIS) == addin.addin_id(BASIS.upper()),
       "Gross/Kleinschreibung der Basis aendert die Kennung nicht")
try:
    uuid.UUID(addin.addin_id(BASIS))
    pruefe(True, "Kennung ist eine gueltige UUID")
except ValueError:
    pruefe(False, "Kennung ist eine gueltige UUID")


class _Req:
    def __init__(self, b):
        self.base_url = b


os.environ.pop("JARVIS_ADDIN_BASE", None)
pruefe(addin.basis_url(_Req("http://x.local/")) == "https://x.local",
       "http wird zu https erzwungen")
pruefe(addin.basis_url(_Req("https://x.local/")) == "https://x.local",
       "abschliessender Schraegstrich faellt weg")
pruefe(addin.basis_url(None) == "", "ohne Anfrage und ohne Einstellung: leer")
os.environ["JARVIS_ADDIN_BASE"] = "jarvis.intern"
pruefe(addin.basis_url(_Req("https://falsch.local/")) == "https://jarvis.intern",
       "die Einstellung hat Vorrang vor dem Host-Kopf (Rueckwaertsproxy)")
os.environ.pop("JARVIS_ADDIN_BASE")

# Ein Manifest mit "localhost" laesst sich klaglos installieren und das
# Aufgabenfenster bleibt danach leer – ein Fehler, den niemand mit dem Abruf in
# Verbindung bringt. Deshalb fail-closed.
for lokal in ("https://localhost", "https://127.0.0.1:443", "http://LOCALHOST/",
              "https://[::1]", "https://0.0.0.0"):
    pruefe(addin.ist_lokale_basis(lokal), "als lokal erkannt: %s" % lokal)
for echt in ("https://jarvis.firma.intern", "https://192.168.10.5",
             "https://mail.example.com:8443", "https://localhost.firma.de"):
    pruefe(not addin.ist_lokale_basis(echt), "NICHT als lokal erkannt: %s" % echt)

# ═══ 5. Endpunkte ═══════════════════════════════════════════════════════════
abschnitt("5. Endpunkte in main.py")
pruefe('@app.get("/addin/manifest.xml")' in MAIN, "Manifest-Route registriert")
_mf = MAIN.split('@app.get("/addin/manifest.xml")', 1)[1].split("@app.", 1)[0]
pruefe("ist_lokale_basis(basis)" in _mf and "status_code=400" in _mf,
       "ein ueber localhost abgerufenes Manifest wird verweigert, nicht ausgeliefert")
pruefe("JARVIS_ADDIN_BASE" in _mf,
       "die Meldung nennt den Ausweg (JARVIS_ADDIN_BASE)")
pruefe('@app.get("/addin/taskpane.html"' in MAIN, "Aufgabenfenster-Route registriert")

for route, name in (("/addin/manifest.xml", "Manifest"), ("/addin/taskpane.html", "Fenster")):
    block = MAIN.split('@app.get("%s"' % route, 1)[1].split("@app.", 1)[0]
    kopf = block.split("\n\n", 1)[0]
    pruefe("Depends(" not in kopf.split(":")[0] or "Depends" not in kopf.split("):")[0],
           "%s haengt bewusst an keiner Anmeldung (Sideload holt es ohne Sitzung)" % name)

blk = MAIN.split('@app.post("/api/email/rules/{regel_id}/run_message")', 1)
pruefe(len(blk) == 2, "Endpunkt run_message registriert")
rm = blk[1].split("@app.", 1)[0]
pruefe("Depends(require_email_access)" in rm,
       "run_message haengt an require_email_access")
pruefe('r.get("owner") != mail_rules.norm_user(user)' in rm,
       "run_message prueft den Besitzer der Regel")
pruefe("status_code=404" in rm and "Regel nicht gefunden" in rm,
       "fremde Regel -> 404, kein Existenz-Orakel")
pruefe('body or {}).get("msg_id")' in rm, "msg_id kommt aus dem Rumpf")
pruefe(not re.search(r'\(body or \{\}\)\.get\("(user|owner|postfach|adresse|konto)"', rm),
       "KEIN Postfach/Benutzer aus dem Rumpf – sonst waere es der Weg in ein "
       "fremdes Postfach")
pruefe("_email_skill_hinweis()" in rm, "abgeschalteter Skill wird abgefangen")

# ═══ 6. mail_runner: eine Buchhaltung, nicht zwei ═══════════════════════════
abschnitt("6. mail_runner – gemeinsame Verarbeitung")
pruefe(RUNNER.count("async def _verarbeite_eine(") == 1,
       "_verarbeite_eine existiert genau einmal")
pruefe(RUNNER.count("async def nachricht_lauf(") == 1,
       "nachricht_lauf existiert genau einmal")
lauf = RUNNER.split("async def regel_lauf(", 1)[1].split("\nasync def _verarbeite_eine", 1)[0]
pruefe("await _verarbeite_eine(" in lauf,
       "regel_lauf benutzt die gemeinsame Verarbeitung")
# Geprueft wird die SCHLEIFE, nicht die ganze Funktion: ein Protokolleintrag im
# Fehlerpfad davor (Postfach nicht erreichbar) ist ein anderer Fall und
# ausdruecklich erwuenscht.
schleife = lauf.split("for n in nachrichten:", 1)[1].split("    finally:", 1)[0]
for stelle in ("merke_verarbeitet", "merke_fehlversuch", "_lesestatus_wahren",
               "protokoll_schreiben", "ergebnis_merken"):
    pruefe(stelle not in schleife,
           "%s steht NICHT mehr doppelt in der Schleife (Drift-Gefahr)" % stelle)
    pruefe(RUNNER.count(stelle + "(") >= 1, "%s ist weiterhin vorhanden" % stelle)
pruefe(len([z for z in schleife.strip().splitlines() if z.strip()]) <= 3,
       "die Schleife besteht nur noch aus dem Aufruf (%d Zeilen)"
       % len([z for z in schleife.strip().splitlines() if z.strip()]))

nl = RUNNER.split("async def nachricht_lauf(", 1)[1].split("\nasync def ", 1)[0]
pruefe("mail_accounts.konto_fuer, owner" in nl,
       "nachricht_lauf laedt das Postfach des BESITZERS")
pruefe("client.lesen" in nl, "nachricht_lauf liest genau die benannte Nachricht")
pruefe("await _verarbeite_eine(" in nl, "nachricht_lauf teilt die Buchhaltung")
pruefe('if not owner' in nl, "Regel ohne Besitzer laeuft nicht (fail-closed)")
pruefe("client.schliessen()" in nl, "Verbindung wird in jedem Fall geschlossen")

ve = RUNNER.split("async def _verarbeite_eine(", 1)[1].split("\nasync def ", 1)[0]
pruefe("_lesestatus_wahren" in ve and "if not testlauf:" in ve,
       "Lesestatus wird AUSNAHMSLOS gewahrt, der Vermerk nur ausserhalb des Testlaufs")
pruefe(ve.index("if not testlauf:") < ve.index("await _lesestatus_wahren"),
       "Lesestatus zuletzt – die Antwort kann laengst heraus sein")

# ═══ 7. Aufgabenfenster: i18n vollstaendig ══════════════════════════════════
abschnitt("7. Aufgabenfenster – Sprachen")
de_block = I18N.split("de:", 1)[1].split("\n    en:", 1)[0] if "\n    en:" in I18N else I18N
en_block = I18N.split("\n    en:", 1)[1] if "\n    en:" in I18N else ""


def hat_key(block, key):
    return ("'%s'" % key) in block


benutzt = set(re.findall(r"T\('([a-z_]+\.[a-z0-9_]+)'", ADDINJS))
benutzt |= set(re.findall(r'data-i18n(?:-title|-placeholder)?="([a-z_]+\.[a-z0-9_]+)"', TASKPANE))
pruefe(len(benutzt) >= 30, "mindestens 30 Sprachschluessel im Fenster (%d)" % len(benutzt))
fehlt_de = sorted(k for k in benutzt if not hat_key(de_block, k))
fehlt_en = sorted(k for k in benutzt if not hat_key(en_block, k))
pruefe(not fehlt_de, "alle Schluessel auf Deutsch vorhanden – fehlt: %s" % fehlt_de)
pruefe(not fehlt_en, "alle Schluessel auf Englisch vorhanden – fehlt: %s" % fehlt_en)
addin_keys = sorted(k for k in benutzt if k.startswith("addin."))
pruefe(len(addin_keys) >= 15, "eigene addin.*-Schluessel angelegt (%d)" % len(addin_keys))

# ═══ 8. Aufgabenfenster: Gestaltung und Verhalten ═══════════════════════════
abschnitt("8. Aufgabenfenster – Gestaltung und Verhalten")
# Harte Farben brechen Branding und Hell-Modus. Erlaubt ist #fff auf dem
# Verlauf-Knopf (wie in /email) – geprueft wird auf alles ANDERE.
farben = [f for f in re.findall(r"#[0-9a-fA-F]{3,6}\b", TASKPANE)
          if f.lower() not in ("#fff", "#ffffff")]
pruefe(not farben, "keine harten Farben ausser #fff – gefunden: %s" % farben)
pruefe("var(--text-primary)" in TASKPANE and "var(--border)" in TASKPANE,
       "Farben kommen aus den Theme-Variablen")
pruefe("theme.css" in TASKPANE, "theme.css ist eingebunden")
pruefe("jarvis_theme" in TASKPANE, "Hell-Modus wird vor dem ersten Zeichnen gesetzt")

# Emoji werden je nach System farbig gerendert und folgen keinem Theme.
emoji = re.findall(r"[\U0001F300-\U0001FAFF☀-⛿]", TASKPANE + ADDINJS)
pruefe(not emoji, "keine farbig voreingestellten Emoji als Symbole: %s" % emoji)

pruefe("appsforoffice.microsoft.com/lib/1/hosted/office.js" in TASKPANE,
       "office.js wird von Microsoft eingebunden (Vorgabe)")
# `async`, NICHT `defer`: ein defer-Skript verzoegert `DOMContentLoaded`, und
# `addin.js` startet daran. Mit defer blieb das Fenster weiss, solange die
# Anfrage lief – bei einer blockierenden Firewall die volle TCP-Zeitgrenze
# (30–75 s), und die 4-Sekunden-Grenze kam nie zum Zug.
_tag = re.search(r"<script([^>]*)src=\"https://appsforoffice[^\"]*\"", TASKPANE)
pruefe(bool(_tag) and " async" in _tag.group(1),
       "office.js wird mit async geladen: %s" % (_tag and _tag.group(1).strip()))
pruefe(bool(_tag) and " defer" not in _tag.group(1),
       "NICHT mit defer – das wuerde DOMContentLoaded und damit das Fenster blockieren")
pruefe("OFFICE_WARTE_MS" in ADDINJS and "setTimeout" in ADDINJS,
       "Zeitgrenze fuer office.js – ohne Internet bleibt das Fenster nutzbar")
pruefe("setInterval" in ADDINJS and "wennBereit" in ADDINJS,
       "auf spaeter eintreffendes office.js wird gewartet (async laedt nebenlaeufig)")
pruefe("addin.no_office" in ADDINJS, "Ausfall von office.js wird im Klartext gemeldet")

# Ohne Rueckfall im Arbeitsspeicher entsteht eine Anmeldeschleife mit RICHTIGEM
# Kennwort: im iframe von Outlook im Web ist der Speicher fremder Herkunft je
# nach Browsereinstellung gesperrt, `setItem` scheitert still, und `start()`
# faende keinen Token.
pruefe("_tokenRam" in ADDINJS and "return _tokenRam" in ADDINJS,
       "der Token hat einen Rueckfall im Arbeitsspeicher")
pruefe("_speicherGeht" in ADDINJS and "addin.no_storage" in ADDINJS,
       "ein gesperrter Speicher wird dem Benutzer gemeldet, nicht verschluckt")

# Der Aussetzer haelt die Regeln an, damit das Domaenenkonto nicht gesperrt
# wird. Wer nur in Outlook arbeitet, saehe sie sonst stillschweigend aufhoeren.
pruefe("_konto.ausgesetzt" in ADDINJS and "mail.paused_head" in ADDINJS,
       "ein ausgesetztes Postfach wird im Fenster erklaert")
pruefe("ausgesetzt_grund" in ADDINJS, "der Grund wird mitgenannt")

pruefe("if (pw) d.passwort = pw" in ADDINJS,
       "leeres Kennwortfeld heisst UNVERAENDERT – sonst loescht jedes Speichern das Kennwort")
pruefe("passwort_gesetzt" in ADDINJS and "d.passwort =" in ADDINJS,
       "das Kennwort wird nie angezeigt, nur sein Vorhandensein")
pruefe("'/api/logout'" in ADDINJS and "keepalive: true" in ADDINJS,
       "Abmeldesignal mit keepalive vor dem Verwerfen des Tokens")
pruefe(ADDINJS.index("fetch('/api/logout'") < ADDINJS.index("tokenLoeschen();\n            _status"),
       "Abmeldesignal geht VOR dem Verwerfen des Tokens raus")
pruefe("{ enabled: r.enabled === false }" in ADDINJS,
       "der Zeilen-Schalter sendet NUR enabled, nicht den Formularstand")
pruefe("_editHeim" in ADDINJS and "formularHeim()" in ADDINJS,
       "das wandernde Formular wird vor dem Neuaufbau heimgeholt")
pruefe("if (!_editHeim) _editHeim = f.parentNode" in ADDINJS,
       "Heimatplatz nur beim ERSTEN Verschieben merken")
pruefe("formularStand()" in ADDINJS and "formularStandSetzen" in ADDINJS,
       "Sprachwechsel verliert keine Eingaben")
pruefe("status.grenzen" in ADDINJS or "_status && _status.grenzen" in ADDINJS,
       "Grenzen kommen vom Server, nicht aus fest verdrahteten Zahlen")
pruefe("me.permissions && me.permissions.email" in ADDINJS,
       "fehlende Berechtigung fail-closed")
pruefe("imapKonto" in ADDINJS and "addin.imap_only" in ADDINJS,
       "IMAP-Postfach bekommt einen Klartext-Hinweis statt eines toten Knopfes")
pruefe("s.ews" in ADDINJS,
       "der wirksame Kanal beruecksichtigt die Vorgabe des Administrators")
pruefe("item.itemId" in ADDINJS, "die EWS-Kennung der Nachricht wird gelesen")
pruefe("window.confirm" in ADDINJS and "addin.run_confirm" in ADDINJS,
       "die echte Verarbeitung wird bestaetigt – die Aktionen sind echt")

# Fremdtext (Betreff, Absender, Regelname, Protokoll) darf nie roh ins DOM.
# Geprueft wird die KONKATENATION: bei `+ esc(x.betreff` steht `esc(` zwischen
# Plus und Feld, bei `+ x.betreff` nicht. Ein Muster ueber den ganzen
# innerHTML-Ausdruck ist zu grob – es findet auch die korrekt maskierten
# Stellen und meldet sie als Fehler (erste Fassung dieses Tests).
FREMD = r"(?:betreff|von|name|ergebnis|regel|mail_betreff|mail_von|adresse)"
roh = re.findall(r"\+\s*([A-Za-z_]\w*\.%s)\b" % FREMD, ADDINJS)
pruefe(not roh, "kein Fremdtext ohne esc() ins innerHTML: %s" % roh)
# Gegenprobe, damit das Muster nicht aus Versehen nie greift:
pruefe(re.findall(r"\+\s*([A-Za-z_]\w*\.%s)\b" % FREMD,
                  "html = '<b>' + x.betreff + '</b>'") == ["x.betreff"],
       "das Muster erkennt eine ungeschuetzte Stelle wirklich")
pruefe(ADDINJS.count("function esc(") == 1, "esc() existiert genau einmal")

pruefe("?v=" in TASKPANE, "Cache-Buster an den Skripten – WebView2 cacht hartnaeckig")

# ═══ 9. Auffindbarkeit: der Download steht in /email ════════════════════════
abschnitt("9. Auffindbarkeit fuer normale Benutzer")
EMAILHTML = (ROOT / "frontend" / "email.html").read_text(encoding="utf-8")
PORTALJS = (ROOT / "frontend" / "js" / "email_portal.js").read_text(encoding="utf-8")

# Ein Add-in, das nur in der Doku steht, findet niemand. Der Bereich /email
# steht JEDEM E-Mail-berechtigten Benutzer offen – kein Administrator noetig.
pruefe('href="/addin/manifest.xml"' in EMAILHTML,
       "der Manifest-Download ist in /email verlinkt")
pruefe("em-addin-help" in EMAILHTML and "em-addin-steps" in EMAILHTML,
       "eine Anleitung steht daneben")
pruefe(EMAILHTML.index("em-addin-dl") < EMAILHTML.index('id="em-rules"'),
       "der Abschnitt steht VOR den Regeln (nicht am Seitenende, wo ihn niemand liest)")
pruefe("require_local_auth" not in MAIN.split('@app.get("/addin/manifest.xml")', 1)[1]
       .split("@app.", 1)[0],
       "der Download verlangt keine Administrator-Rechte")

pruefe("em-addin-help" in PORTALJS and "addin_howto_hide" in PORTALJS,
       "der Umschalter ist verdrahtet und die Beschriftung folgt dem Zustand")

# DER FEHLER, DEN NUR DER DOM-ABZUG ZEIGTE: `binde()` benutzt eine geteilte
# Variable `var b`, die mehrfach zugewiesen wird. Eine Inline-Closure darueber
# sieht beim Klick den ZULETZT zugewiesenen Wert – der Handler beschriftete
# dadurch den Abmelde-Knopf oben rechts. Im Markup ist davon nichts zu sehen.
_h = PORTALJS.split("em-addin-help", 1)[1].split("});", 1)[0]
pruefe(not re.search(r"\bb\.(textContent|dataset|classList)", _h),
       "der Anleitung-Handler benutzt NICHT die geteilte Variable b")
pruefe("hilfeKnopf" in _h, "er benutzt eine eigene Variable")

# Ein <a> mit Knopf-Klasse ist ohne das hier unterstrichen und sieht aus wie
# ein Textlink im Knopf (im Screenshot gesehen).
pruefe(re.search(r"\.em-btn\s*\{[^}]*text-decoration:\s*none", EMAILHTML, re.S),
       ".em-btn setzt text-decoration: none (der Download ist ein Link)")

addin_i18n = sorted(set(re.findall(r'data-i18n(?:-html)?="(mail\.addin_[a-z0-9_]+)"',
                                   EMAILHTML)))
addin_i18n += ["mail.addin_howto_hide"]     # nur im JS gesetzt
pruefe(len(addin_i18n) >= 9, "mindestens 9 Sprachschluessel im Abschnitt (%d)" % len(addin_i18n))
f_de = [k for k in addin_i18n if not hat_key(de_block, k)]
f_en = [k for k in addin_i18n if not hat_key(en_block, k)]
pruefe(not f_de, "Add-in-Abschnitt vollstaendig auf Deutsch – fehlt: %s" % f_de)
pruefe(not f_en, "Add-in-Abschnitt vollstaendig auf Englisch – fehlt: %s" % f_en)

# Schluessel mit eingebetteter Auszeichnung MUESSEN data-i18n-html benutzen:
# `applyLang()` setzt bei data-i18n den textContent und wuerde <code>/<b>
# ersatzlos entfernen (Lehre vom E-Mail-Reiter, 2026-08-13).
for k in ("mail.addin_s1", "mail.addin_s2", "mail.addin_s3", "mail.addin_note"):
    pruefe('data-i18n="%s"' % k not in EMAILHTML,
           "%s benutzt nicht data-i18n (das wuerde das Markup loeschen)" % k)
    pruefe('data-i18n-html="%s"' % k in EMAILHTML, "%s benutzt data-i18n-html" % k)
for block, spr in ((de_block, "DE"), (en_block, "EN")):
    w = re.search(r"'mail\.addin_s2':\s*'([^']*)'", block)
    pruefe(bool(w) and "<b>" in w.group(1),
           "der %s-Text von mail.addin_s2 traegt seine Auszeichnung" % spr)

_note = re.search(r"'mail\.addin_note':\s*'([^']*)'", de_block)
pruefe(bool(_note) and "Exchange" in _note.group(1) and "Zertifikat" in _note.group(1),
       "der Hinweis nennt beides: die Grenze des neuen Outlook und das Zertifikat "
       "(die zwei Faelle, in denen es beim Benutzer nicht laeuft)")

# Cache-Buster: ohne Erhoehung behaelt der Browser die Fassung ohne den Abschnitt.
m_i18n = re.search(r"i18n\.js\?v=(\d+)", EMAILHTML)
m_js = re.search(r"email_portal\.js\?v=(\d+)", EMAILHTML)
pruefe(bool(m_i18n) and int(m_i18n.group(1)) >= 45,
       "i18n.js-Cache-Buster in email.html erhoeht (%s)" % (m_i18n and m_i18n.group(1)))
pruefe(bool(m_js) and int(m_js.group(1)) >= 4,
       "email_portal.js-Cache-Buster erhoeht (%s)" % (m_js and m_js.group(1)))

# ═══ 10. /email: einklappbare Karten ════════════════════════════════════════
abschnitt("10. Einklappbare Karten in /email")
karten = re.findall(r'<div class="em-card" data-klapp="([a-z]+)">', EMAILHTML)
pruefe(sorted(karten) == ["acct", "addin", "log", "rules"],
       "alle vier Karten sind klappbar: %s" % karten)
pruefe(EMAILHTML.count('class="em-card-head"') == 4
       and EMAILHTML.count('class="em-card-body"') == 4,
       "jede Karte hat Kopfzeile und Koerper")
pruefe(EMAILHTML.count('aria-expanded="true"') == 4 and 'role="button"' in EMAILHTML
       and 'tabindex="0"' in EMAILHTML,
       "die Kopfzeile ist als Schalter ausgezeichnet und fokussierbar")

# REIHENFOLGE: Titel zuerst, Pfeil als zweites Kind. Bei `space-between` schoebe
# die umgekehrte Reihenfolge den Titel an den rechten Rand – genau der Fehler,
# der am 2026-08-13 im Add-in-Fenster auftrat.
for kopf in re.findall(r'<div class="em-card-head"[^>]*>(.*?)</div>', EMAILHTML, re.S):
    pruefe(kopf.index("<h2") < kopf.index("em-caret"),
           "in der Kopfzeile steht der Titel VOR dem Pfeil")

pruefe(re.search(r"\.em-card\.is-zu\s+\.em-card-body\s*\{[^}]*display:\s*none", EMAILHTML),
       "zugeklappt blendet den Koerper aus")
pruefe("klappInit" in PORTALJS and "jarvis_email_zu" in PORTALJS,
       "die Logik ist verdrahtet und merkt sich den Zustand")
# OHNE die Ausnahme klappt jeder Knopf in einer Kopfzeile die Karte zu.
pruefe("closest('button, input, label, a, select, textarea')" in PORTALJS,
       "Klicks auf Bedienelemente klappen NICHT")
pruefe("'Enter'" in PORTALJS and "keydown" in PORTALJS,
       "mit der Tastatur bedienbar (role=button verlangt das)")
# Gespeichert werden die ZUGEKLAPPTEN: Vorgabe ist damit "alles offen"
# (verhaltensgleich zu vorher), und eine spaeter ergaenzte Karte ist automatisch
# offen statt still versteckt.
_ki = PORTALJS.split("function klappInit", 1)[1].split("\n    function ", 1)[0]
pruefe("zu.indexOf(id) >= 0" in _ki,
       "die gespeicherte Liste enthaelt die ZUGEKLAPPTEN, nicht die offenen")

m_js2 = re.search(r"email_portal\.js\?v=(\d+)", EMAILHTML)
pruefe(bool(m_js2) and int(m_js2.group(1)) >= 5,
       "Cache-Buster erneut erhoeht (%s)" % (m_js2 and m_js2.group(1)))

# ═══ Ergebnis ═══════════════════════════════════════════════════════════════
print("\n%s  %d bestanden, %d fehlgeschlagen" %
      ("OK  " if not _fail else "FEHL", _ok, _fail))
sys.exit(0 if not _fail else 1)
