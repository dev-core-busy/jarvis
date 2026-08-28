#!/usr/bin/env python3
"""Waechter: persoenliche Standard-Vorlage + Serveradresse im gebauten Paket.

ZWEI MELDUNGEN VOM 2026-08-28, beide hier belegt:

a) "der user muss die Moeglichkeit haben eine Vorlage als seine 'Standard'
   Vorlage zu markieren" – ``jira_vorlagen.standard_setzen``/``_standard_aus``.

b) "man muss sich 2x anmelden (vermutlich weil Chrome nach der Anmeldung eine
   Berechtigung anfordert)" – zutreffend, und die Ursache lag nicht in der
   Anmeldung: das Manifest trug die Adresse nur als
   ``optional_host_permissions``, das Fenster musste sie beim ersten Anmelden
   erfragen, und **Chrome schliesst dabei das Popup**. Der Klick endete im
   Nichts. Hier wird gemessen, dass der Server seine Adresse ins gebaute Paket
   schreibt – Manifest UND Fensterfeld.

⚠ SANDKASTEN MIT EXIT 2. Die Vorlagen liegen in ``data/jira_vorlagen.json``;
ein Test, der dorthin schreibt, verstellt einem echten Benutzer seine
Vorauswahl und kann gemeinsame Vorlagen loeschen. Zeigt der Modulpfad nach dem
Umbiegen nicht ins Wegwerf-Verzeichnis, bricht der Lauf mit **2** ab –
"konnte nicht laufen" muss von "bestanden" unterscheidbar bleiben.

Lauf:  python3 tests/test_jira_vorlagen.py
"""

import io
import json
import re
import sys
import tempfile
import types
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(text, bed, extra=""):
    """``check(Beschreibung, Bedingung)`` – **in DIESER Reihenfolge.**

    ⚠ DIE PRUEFUNG DER REIHENFOLGE IST KEIN LUXUS. Die Schwester-Datei
    ``test_jira_assist.py`` nimmt die Argumente andersherum; beim Schreiben
    dieses Waechters waren deshalb **alle 57 Aufrufe vertauscht**. Eine
    nicht-leere Zeichenkette ist wahr – der Lauf meldete "57 OK, 0 FAIL", ohne
    eine einzige Bedingung ausgewertet zu haben. Aufgefallen ist es nur daran,
    dass hinter jedem OK ein nacktes ``True`` stand.

    Ein vertauschter Aufruf bricht jetzt hart ab (Exit 2): "konnte nicht
    laufen" darf nie wie "bestanden" aussehen.
    """
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
if "backend.config" not in sys.modules:
    _cfg = types.ModuleType("backend.config")

    class _C:
        def get_setting(self, k, d=None):
            return d

    _cfg.config = _C()
    sys.modules["backend.config"] = _cfg

from backend import jira_vorlagen as jv  # noqa: E402

# ── Sandkasten ───────────────────────────────────────────────────────────────
_tmp = tempfile.mkdtemp(prefix="jvorl-test-")
jv._DATEI = Path(_tmp) / "jira_vorlagen.json"
if not str(jv._DATEI).startswith(_tmp):
    print("ABBRUCH: Sandkasten greift nicht – %s" % jv._DATEI)
    sys.exit(2)


def frisch():
    """Leerer Bestand mit den mitgelieferten Vorschlaegen."""
    if jv._DATEI.exists():
        jv._DATEI.unlink()
    jv.saeen()


# ═════════════════════════════════════════════════════════════════════════════
section("1) Setzen, Lesen, Aufheben")
# ═════════════════════════════════════════════════════════════════════════════
frisch()
d = jv.liste("alice")
check("liste() nennt das Feld 'standard'", "standard" in d)
check("und es ist anfangs leer – ohne Markierung gibt es keine Vorauswahl",
      d["standard"] == "", repr(d.get("standard")))

g0 = d["global"][0]["id"]
jv.standard_setzen("alice", g0)
check("nach dem Setzen kommt die Kennung zurueck",
      jv.liste("alice")["standard"] == g0)

jv.standard_setzen("alice", "")
check("der leere Wert hebt auf", jv.liste("alice")["standard"] == "")

# ═════════════════════════════════════════════════════════════════════════════
section("2) Eine unbekannte Kennung wird ABGEWIESEN, nicht gespeichert")
# ═════════════════════════════════════════════════════════════════════════════
# Sonst stuende beim naechsten Oeffnen wieder "ohne Vorlage" da und niemand
# wuesste warum – ein stiller Fehlschlag mit Erfolgsmeldung.
frisch()
try:
    jv.standard_setzen("alice", "gibtesnicht")
    check("unbekannte Kennung wirft VorlagenFehler", False)
except jv.VorlagenFehler:
    check("unbekannte Kennung wirft VorlagenFehler", True)
check("und wird NICHT gespeichert", jv.liste("alice")["standard"] == "")

# ═════════════════════════════════════════════════════════════════════════════
section("3) Der Standard ist persoenlich – auch auf gemeinsamen Vorlagen")
# ═════════════════════════════════════════════════════════════════════════════
frisch()
g = jv.liste("alice")["global"]
jv.standard_setzen("alice", g[0]["id"])
jv.standard_setzen("bob", g[1]["id"])
check("Alice hat ihre Wahl", jv.liste("alice")["standard"] == g[0]["id"])
check("Bob eine andere – auf DERSELBEN gemeinsamen Vorlagenliste",
      jv.liste("bob")["standard"] == g[1]["id"])
check("Carol hat gar keine – der Standard eines anderen gilt nie fuer sie",
      jv.liste("carol")["standard"] == "")

# Ein Administrator markiert fuer SICH, nicht fuer das Haus. Waere das anders,
# haette die Wahl des Ersten die Vorauswahl aller verstellt.
jv.standard_setzen("chef", g[2]["id"], ist_admin=True)
check("die Wahl eines Administrators aendert die der anderen nicht",
      jv.liste("alice")["standard"] == g[0]["id"]
      and jv.liste("carol")["standard"] == "")

# ═════════════════════════════════════════════════════════════════════════════
section("4) Der Benutzerschluessel wird normiert")
# ═════════════════════════════════════════════════════════════════════════════
# Ohne Normalisierung haette dieselbe Person je Anmeldeform eine andere
# Vorauswahl – dieselbe Fehlerklasse wie bei den Sperrlisten (Register).
frisch()
g = jv.liste("alice")["global"]
jv.standard_setzen("nexus\\Alice", g[0]["id"])
for form in ("alice", "ALICE", "nexus\\alice", "alice@firma.de"):
    check("dieselbe Person unter %r findet ihren Standard" % form,
          jv.liste(form)["standard"] == g[0]["id"])

# ═════════════════════════════════════════════════════════════════════════════
section("5) Fremde Vorlagen sind kein Ziel")
# ═════════════════════════════════════════════════════════════════════════════
frisch()
meine = jv.speichern("alice", "Meine", "Nur die offenen Punkte.")
try:
    jv.standard_setzen("bob", meine["id"])
    check("eine fremde EIGENE Vorlage laesst sich nicht setzen", False)
except jv.VorlagenFehler:
    check("eine fremde EIGENE Vorlage laesst sich nicht setzen", True)
check("Alice selbst darf sie sehr wohl setzen",
      jv.standard_setzen("alice", meine["id"]) == meine["id"])

# ═════════════════════════════════════════════════════════════════════════════
section("6) Loeschen laesst keinen Standard stehen, der auf nichts zeigt")
# ═════════════════════════════════════════════════════════════════════════════
frisch()
meine = jv.speichern("alice", "Meine", "Text.")
jv.standard_setzen("alice", meine["id"])
jv.loeschen("alice", meine["id"])
check("die eigene geloeschte Vorlage ist nicht mehr Standard",
      jv.liste("alice")["standard"] == "")
roh = json.loads(jv._DATEI.read_text(encoding="utf-8"))
check("und der Eintrag ist wirklich weg, nicht nur beim Lesen versteckt",
      not (roh.get("standard") or {}).get("alice"),
      json.dumps(roh.get("standard")))

# Der schwierigere Fall: ein ADMIN loescht eine gemeinsame Vorlage, die bei
# zwanzig Leuten der Standard ist. Ihre Eintraege einzeln aufzuraeumen hiesse,
# beim Loeschen durch alle Benutzer zu laufen – stattdessen laufen sie beim
# Lesen ins Leere und bekommen "ohne Vorlage".
frisch()
g0 = jv.liste("alice")["global"][0]["id"]
jv.standard_setzen("alice", g0)
jv.loeschen("chef", g0, ist_admin=True)
check("eine geloeschte GEMEINSAME Vorlage gilt fuer Fremde nicht mehr",
      jv.liste("alice")["standard"] == "")
vorher = jv._DATEI.read_bytes()
jv.liste("alice")
check("und das blosse LESEN schreibt die Datei nicht um",
      jv._DATEI.read_bytes() == vorher)

# ═════════════════════════════════════════════════════════════════════════════
section("7) Altbestand ohne das Feld laeuft weiter")
# ═════════════════════════════════════════════════════════════════════════════
jv._DATEI.write_text(json.dumps({
    "global": [{"id": "g1", "name": "Alt", "text": "Text."}],
    "benutzer": {"alice": []},
}), encoding="utf-8")
d = jv.liste("alice")
check("eine Datei ohne 'standard' ist kein Fehler", d["standard"] == "")
check("und die Vorlagen sind unveraendert lesbar", len(d["global"]) == 1)
jv.standard_setzen("alice", "g1")
check("das Feld entsteht beim ersten Setzen", jv.liste("alice")["standard"] == "g1")

# Ein kaputter Wert darf nicht durchschlagen.
jv._DATEI.write_text(json.dumps({
    "global": [{"id": "g1", "name": "Alt", "text": "T."}],
    "benutzer": {}, "standard": "keindict",
}), encoding="utf-8")
check("ein unbrauchbares 'standard' wird verworfen, nicht geraten",
      jv.liste("alice")["standard"] == "")

# ═════════════════════════════════════════════════════════════════════════════
section("8) Der Endpunkt nimmt den Benutzer aus der ANMELDUNG")
# ═════════════════════════════════════════════════════════════════════════════
# Sonst waere er ein Weg, fremden Leuten eine Vorauswahl vorzugeben. Gleiche
# Regel wie beim Empfaenger einer Erinnerung und beim Wiederherstellen des
# Willkommens-Chats.
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
m = re.search(r'@app\.post\("/api/jira/assist/vorlagen/standard"\)'
              r'(.*?)(?=\n@app\.)', MAIN, re.S)
check("die Route existiert", m is not None)
rumpf = m.group(1) if m else ""
check("sie haengt an require_jira_vorlagen_access",
      "require_jira_vorlagen_access" in rumpf)
check("sie uebergibt user=user – nicht etwas aus dem Rumpf",
      "user=user" in rumpf)
check("aus dem Rumpf kommt NUR die Kennung",
      re.findall(r'\(b or \{\}\)\.get\("([a-z_]+)"\)', rumpf) == ["id"],
      str(re.findall(r'\(b or \{\}\)\.get\("([a-z_]+)"\)', rumpf)))
check("ein fachlicher Fehlschlag antwortet 400 mit Klartext",
      "VorlagenFehler" in rumpf and "status_code=400" in rumpf)

# Und die Route darf nicht von DELETE /{vid} verschluckt werden: sie steht
# davor UND traegt eine andere Methode.
check("die Standard-Route steht vor der Loesch-Route",
      MAIN.index('/api/jira/assist/vorlagen/standard')
      < MAIN.index('/api/jira/assist/vorlagen/{vid}'))

# ═════════════════════════════════════════════════════════════════════════════
section("9) host_muster – nur brauchbare Adressen werden zu einem Recht")
# ═════════════════════════════════════════════════════════════════════════════
from backend import jira_assist as ja  # noqa: E402

for basis, erwartet in [
    ("https://dp.firma.de", "https://dp.firma.de/*"),
    ("https://dp.firma.de/", "https://dp.firma.de/*"),
    ("https://dp.firma.de:8443", "https://dp.firma.de:8443/*"),
    # http scheidet aus: das Token ginge im Klartext, und das Fenster laesst
    # die Adresse ohnehin nicht zu – ein Recht dafuer waere eine Zusage ins
    # Leere.
    ("http://dp.firma.de", ""),
    # Nur auf dem Server selbst gueltig: auf jedem Arbeitsplatz wertlos.
    ("https://localhost", ""),
    ("https://127.0.0.1", ""),
    ("", ""),
    ("kein url", ""),
]:
    check("host_muster(%r) → %r" % (basis, erwartet),
          ja.host_muster(basis) == erwartet, repr(ja.host_muster(basis)))

# `localhost.firma.de` ist KEIN lokaler Name – der Host wird exakt geprueft.
check("localhost.firma.de gilt nicht als lokal",
      ja.host_muster("https://localhost.firma.de") == "https://localhost.firma.de/*")

# ═════════════════════════════════════════════════════════════════════════════
section("10) Das gebaute Paket traegt die Adresse – Manifest UND Fenster")
# ═════════════════════════════════════════════════════════════════════════════
BASIS = "https://dp.firma.de"


def paket(variante, basis):
    _, roh = ja.paket_bauen(variante, basis)
    z = zipfile.ZipFile(io.BytesIO(roh))
    return (json.loads(z.read("manifest.json").decode("utf-8")),
            z.read("popup.html").decode("utf-8"))


for variante in ("chrome", "firefox"):
    man, popup = paket(variante, BASIS)
    check("%s: host_permissions steht im gebauten Manifest" % variante,
          man.get("host_permissions") == ["https://dp.firma.de/*"],
          json.dumps(man.get("host_permissions")))
    # Die Nachfrage muss weiterhin MOEGLICH bleiben: wer eine andere Adresse
    # eintraegt (zweite Instanz, Adresswechsel), kommt nur darueber ans Ziel.
    check("%s: optional_host_permissions bleibt daneben stehen" % variante,
          bool(man.get("optional_host_permissions")))
    m2 = re.search(r'<meta name="basis" content="([^"]*)"', popup)
    check("%s: das Fenster traegt die Adresse als Vorgabe" % variante,
          m2 is not None and m2.group(1) == BASIS,
          m2.group(1) if m2 else "Feld fehlt")

# OHNE Adresse entsteht genau das bisherige Paket – ein Server ohne
# `addin_base_url` und hinter einem Proxy darf nicht schlechter dastehen.
man, popup = paket("chrome", "")
check("ohne Adresse KEINE host_permissions (sonst ein falsches Recht)",
      "host_permissions" not in man, json.dumps(man.get("host_permissions")))
check("und das Feld im Fenster bleibt leer",
      '<meta name="basis" content="">' in popup)

# Eine lokale Adresse ist auf jedem Arbeitsplatz wertlos.
man, popup = paket("chrome", "https://localhost")
check("eine lokale Adresse wird nicht als Recht eingetragen",
      "host_permissions" not in man)

# ═════════════════════════════════════════════════════════════════════════════
section("11) Die Adresse steht VOR der Farbpruefung im Fenster")
# ═════════════════════════════════════════════════════════════════════════════
# ⚠ DIESE FALLE HAT DAS PROJEKT SCHON EINMAL BEZAHLT (Ordner-Knopf im
# Excel-Reiter, hinter einem fruehen `return`). Frueher endete
# `_popup_gebrandet` bei fehlender Hausfarbe mit einem `return`; ein Feld
# dahinter waere auf jedem Server OHNE Branding still leer geblieben – und das
# sind genau die Server, auf denen niemand nach einem Branding-Fehler sucht.
_echt = ja._branding_fuer_symbol
try:
    ja._branding_fuer_symbol = lambda: ("", "J", None)   # kein Branding
    roh = (ROOT / "browser-addon" / "popup.html").read_text(encoding="utf-8")
    text = ja._popup_gebrandet(roh, BASIS)
    m3 = re.search(r'<meta name="basis" content="([^"]*)"', text)
    check("ohne Hausfarbe steht die Adresse trotzdem im Fenster",
          m3 is not None and m3.group(1) == BASIS,
          m3.group(1) if m3 else "Feld fehlt")
    check("und die Farbe bleibt leer (neutraler Knopf)",
          '<meta name="akzent" content="">' in text)
finally:
    ja._branding_fuer_symbol = _echt

# Fremdeingabe: die Adresse landet in einem HTML-Attribut.
text = ja._popup_gebrandet(
    (ROOT / "browser-addon" / "popup.html").read_text(encoding="utf-8"),
    'https://x.de" onload="boese()')
check("ein Anfuehrungszeichen schliesst das Attribut NICHT",
      'onload="boese()' not in text)

# ═════════════════════════════════════════════════════════════════════════════
section("12) Im Repo bleibt die Adresse LEER")
# ═════════════════════════════════════════════════════════════════════════════
# Sonst waere sie eine zweite Wahrheit und auf jedem anderen Server falsch.
POPUP = (ROOT / "browser-addon" / "popup.html").read_text(encoding="utf-8")
check("<meta name=basis> ist im Repo leer",
      '<meta name="basis" content="">' in POPUP)
for man_datei in ("manifest.json", "manifest.firefox.json"):
    roh = json.loads((ROOT / "browser-addon" / man_datei).read_text(encoding="utf-8"))
    check("%s traegt im Repo keine host_permissions" % man_datei,
          "host_permissions" not in roh)

# ═════════════════════════════════════════════════════════════════════════════
section("13) Der Endpunkt reicht die Adresse des ABRUFS durch")
# ═════════════════════════════════════════════════════════════════════════════
# Ohne den Request faellt `basis_url` auf die Einstellung zurueck und ist auf
# einem Server ohne `addin_base_url` LEER – das Recht fehlte dann genau dort,
# wo es gebraucht wird.
m4 = re.search(r'@app\.get\("/api/jira/assist/paket"\)(.*?)(?=\n@app\.)', MAIN, re.S)
check("die Paket-Route existiert", m4 is not None)
prumpf = m4.group(1) if m4 else ""
check("sie nimmt den Request entgegen", "request: Request" in prumpf)
check("und gibt addin.basis_url(request) an paket_bauen weiter",
      "paket_bauen(" in prumpf and "basis_url(request)" in prumpf)

print("\n%d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
