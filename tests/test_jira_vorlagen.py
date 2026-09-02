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
# GEPRUEFT WIRD DIE VORLAGE, NICHT DIE ANZAHL: seit 2026-09-02 traegt `saeen()`
# in eine bestehende Datei einmalig die Antwort-Vorlage nach - eine feste Zahl
# meldete hier einen Fehler, den es nicht gibt (Register).
check("und die Vorlage ist unveraendert lesbar",
      any(v["id"] == "g1" and v["text"] == "Text." for v in d["global"]))
check("eine Vorlage ohne 'art' gilt als Zusammenfassung (fail-safe)",
      [v for v in d["global"] if v["id"] == "g1"][0]["art"] == "zusammenfassung")
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

# ═════════════════════════════════════════════════════════════════════════════
section("14) Die ART einer Vorlage (2026-09-02)")
# ═════════════════════════════════════════════════════════════════════════════
# Seit die Erweiterung nur noch EIN Startsymbol hat, sagt die Vorlage selbst,
# was sie tut. Der Unterschied ist nicht kosmetisch: eine Zusammenfassung liest
# ein Mitarbeiter, ein Antworttext geht an einen KUNDEN und laeuft unter eigenen
# Regeln im System-Prompt.
check("es gibt genau zwei Arten", list(jv.ARTEN) == ["zusammenfassung", "antwort"],
      str(jv.ARTEN))
check("die Zusammenfassung ist die erste – und damit die Vorgabe",
      jv.ARTEN[0] == "zusammenfassung")

# ── art_von: fail-safe in die STRENGERE Richtung ────────────────────────────
# Alles Unklare wird zur Zusammenfassung. In den strengeren Modus zu fallen ist
# harmlos; umgekehrt entstuende aus einem Altbestand ungefragt Kundentext.
for roh, soll, warum in [
    ({}, "zusammenfassung", "fehlendes Feld (Altbestand)"),
    ({"art": None}, "zusammenfassung", "None"),
    ({"art": ""}, "zusammenfassung", "leer"),
    ({"art": "quatsch"}, "zusammenfassung", "unbekannter Wert"),
    ({"art": "ANTWORT"}, "antwort", "Grossschreibung wird erkannt"),
    ({"art": " antwort "}, "antwort", "Leerraum wird erkannt"),
    ({"art": "antwort"}, "antwort", "der Normalfall"),
]:
    check("art_von: %s -> %s" % (warum, soll), jv.art_von(roh) == soll,
          jv.art_von(roh))
check("art_von nimmt auch den blossen Wert", jv.art_von("antwort") == "antwort")

# ── Speichern: unbekannte Art wird ABGEWIESEN, nicht ersetzt ───────────────
# Hier kommt der Wert aus einem Pulldown - ein Fehlgriff ist ein Fehler des
# Aufrufers, und eine Vorlage, die etwas anderes tut als bestellt, faellt
# niemandem auf.
v = jv.speichern("artuser", "Antwortform", "freundlich", art="antwort")
check("angelegt mit der gewaehlten Art", v["art"] == "antwort", v.get("art"))
check("und sie steht auch auf Platte",
      jv.eintrag_fuer("artuser", v["id"])["art"] == "antwort")
# ⚠ IM try: ein Speichern OHNE `art` DARF nicht werfen. Genau das war der Fall,
# als die Gegenprobe zu dieser Zeile nicht biss - der Lauf brach mit einer
# Ausnahme ab, und weil nur FAILs gezaehlt wurden, sah das wie ein bestandener
# Test aus (Register). Eine Pruefung darf nicht werfen.
try:
    v2 = jv.speichern("artuser", "Antwortform", "freundlich", vid=v["id"])
    check("ein FEHLENDES Feld laesst die Art unangetastet (aeltere Erweiterung)",
          v2["art"] == "antwort", v2.get("art"))
except Exception as _e:  # noqa: BLE001
    check("ein FEHLENDES Feld laesst die Art unangetastet (aeltere Erweiterung)",
          False, "es wirft: %s" % _e)
v3 = jv.speichern("artuser", "Antwortform", "freundlich", vid=v["id"],
                  art="zusammenfassung")
check("ausdruecklich umgestellt wird sie aber", v3["art"] == "zusammenfassung",
      v3.get("art"))
try:
    jv.speichern("artuser", "X", "y", art="ueberarbeiten")
    check("eine unbekannte Art wird abgewiesen", False)
except jv.VorlagenFehler as f:
    check("eine unbekannte Art wird abgewiesen und BENANNT",
          "ueberarbeiten" in str(f) and "zusammenfassung" in str(f), str(f))
try:
    ohne = jv.speichern("artuser", "Ohne Angabe", "x")
    check("neu ohne Angabe = Zusammenfassung (fail-safe)",
          ohne["art"] == "zusammenfassung", ohne.get("art"))
except Exception as _e:  # noqa: BLE001
    check("neu ohne Angabe = Zusammenfassung (fail-safe)", False,
          "es wirft: %s" % _e)

# ═════════════════════════════════════════════════════════════════════════════
section("15) Die Antwort-Vorlage wird EINMALIG nachgetragen")
# ═════════════════════════════════════════════════════════════════════════════
# WARUM ES DAS BRAUCHT: `saeen()` legt die Vorschlaege nur an, wenn die Datei
# fehlt. Auf jedem laufenden Server existiert sie langst - ohne Nachtrag waere
# die Aktion "Antwort vorschlagen" nach dem Update ersatzlos weg (der Knopf ist
# entfernt, und die Vorlage, die ihn ersetzt, gaebe es nicht).
_sicherung = jv._DATEI.read_bytes() if jv._DATEI.exists() else None

# (a) Frisches System: alles auf einmal, Marker gesetzt.
jv._DATEI.unlink(missing_ok=True)
jv.saeen()
d = json.loads(jv._DATEI.read_text(encoding="utf-8"))
check("frisch gesaet: alle mitgelieferten Vorlagen",
      len(d["global"]) == len(jv.SAAT), str(len(d["global"])))
check("darunter die Antwort-Vorlage",
      any(v["art"] == "antwort" for v in d["global"]))
check("und der Marker steht (sonst kaeme sie ein zweites Mal)",
      bool(d.get(jv._MARKE_ANTWORT)))
jv.saeen(); jv.saeen()
check("mehrfaches Saeen aendert nichts",
      len(json.loads(jv._DATEI.read_text(encoding="utf-8"))["global"])
      == len(jv.SAAT))

# (b) Bestandssystem: nur die Antwort-Vorlage kommt dazu, sonst nichts.
jv._DATEI.write_text(json.dumps({
    "global": [{"id": "alt1", "name": "Bestand", "text": "T."}],
    "benutzer": {"bob": [{"id": "b1", "name": "Meine", "text": "M."}]},
    "standard": {"bob": "b1"},
}), encoding="utf-8")
jv.saeen()
d = json.loads(jv._DATEI.read_text(encoding="utf-8"))
check("Bestand: genau EINE Vorlage kommt dazu", len(d["global"]) == 2,
      str(len(d["global"])))
check("und es ist die Antwort-Vorlage",
      [v for v in d["global"] if v.get("art") == "antwort"][0]["name"]
      == jv.ANTWORT_VORSCHLAG["name"])
check("die bestehende bleibt unangetastet",
      d["global"][0] == {"id": "alt1", "name": "Bestand", "text": "T."})
check("eigene Vorlagen und der Standard bleiben ebenfalls",
      d["benutzer"]["bob"][0]["id"] == "b1" and d["standard"]["bob"] == "b1")
jv.saeen()
check("ein zweiter Lauf traegt NICHTS mehr nach",
      len(json.loads(jv._DATEI.read_text(encoding="utf-8"))["global"]) == 2)

# (c) Geloescht heisst geloescht - die Entscheidung des Administrators haelt.
_antw = [v for v in d["global"] if v.get("art") == "antwort"][0]
jv.loeschen("bob", _antw["id"], ist_admin=True)
jv.saeen()
check("nach dem Loeschen kommt sie NICHT zurueck",
      not any(v.get("art") == "antwort"
              for v in json.loads(jv._DATEI.read_text(encoding="utf-8"))["global"]))

# (d) ⚠ EINE BESCHAEDIGTE DATEI WIRD NICHT ANGEFASST. `_laden()` gibt bei einem
#     Parse-Fehler bewusst einen leeren Bestand zurueck, damit der Bereich nicht
#     sperrt. Wuerde der Nachtrag darauf schreiben, waere der Bestand des Kunden
#     weg - obwohl der Administrator ihn noch ansehen wollte.
jv._DATEI.write_text("{kaputt", encoding="utf-8")
jv.saeen()
check("eine beschaedigte Datei bleibt unveraendert",
      jv._DATEI.read_text(encoding="utf-8") == "{kaputt")

if _sicherung is not None:
    jv._DATEI.write_bytes(_sicherung)

# ═════════════════════════════════════════════════════════════════════════════
section("16) 'Fuer alle Benutzer' ist ein VERSCHIEBEN (Fix 2026-09-02)")
# ═════════════════════════════════════════════════════════════════════════════
# ⚠ GEMELDET: "wenn ich in der Vorlage 'Loesung suchen' versuche 'fuer alle
# Benutzer' auszuwaehlen und zu speichern, kommt 'Die Vorlage wurde nicht
# gefunden.'" Zutreffend, und in BEIDE Richtungen: gesucht wurde die Kennung
# nur in der ZIELliste, und die ergibt sich aus `global_`. Eine eigene Vorlage
# lag aber in `benutzer[...]` - die Suche fand nichts, und die Meldung
# behauptete, es gaebe die Vorlage nicht.
_v = jv.speichern("chef", "Lösung suchen", "Suche nach der Lösung.")
check("angelegt als eigene Vorlage",
      any(x["id"] == _v["id"] for x in jv.liste("chef")["eigene"]))

# ⚠ IM try, UND ZWAR GERADE HIER: der gemeldete Fehler ist eine Ausnahme
# ("Die Vorlage wurde nicht gefunden"). Ungefangen bricht der Lauf ab und
# liefert KEINE Bilanz - der Waechter saehe aus, als waere er nicht gelaufen,
# statt den Fehler zu melden. Register, und in dieser Sitzung mehrfach bezahlt.
_r = {"id": ""}
try:
    _r = jv.speichern("chef", "Lösung suchen", "Suche nach der Lösung.",
                      vid=_v["id"], global_=True, ist_admin=True)
    _d = jv.liste("chef", ist_admin=True)
    check("eigen -> gemeinsam: sie liegt jetzt in den gemeinsamen",
          any(x["id"] == _v["id"] for x in _d["global"]))
    check("und nicht mehr in den eigenen",
          not any(x["id"] == _v["id"] for x in _d["eigene"]))
except Exception as _e:  # noqa: BLE001
    check("eigen -> gemeinsam: sie liegt jetzt in den gemeinsamen", False,
          "es wirft: %s" % _e)
    check("und nicht mehr in den eigenen", False, "s.o.")
# ⚠ DIE KENNUNG BLEIBT. Persoenliche Standards (`standard`) und die Automatik
# der Erweiterung (`auto_vorlage`) zeigen darauf - eine neue Kennung waere ein
# stiller Verlust dieser Zuordnungen bei ALLEN Benutzern.
check("die Kennung bleibt dieselbe", _r["id"] == _v["id"], _r["id"])

# Und zurueck. ⚠ IM try: wechselt die Kennung beim Verschieben, findet die
# zweite Stufe sie nicht mehr und WIRFT - der Lauf braeche ab und lieferte keine
# Bilanz, also genau das, was von "nicht gelaufen" nicht zu unterscheiden ist.
try:
    jv.speichern("chef", "Lösung suchen", "x", vid=_v["id"], global_=False,
                 ist_admin=True)
    _d = jv.liste("chef", ist_admin=True)
    check("gemeinsam -> eigen geht ebenfalls",
          any(x["id"] == _v["id"] for x in _d["eigene"])
          and not any(x["id"] == _v["id"] for x in _d["global"]))
except Exception as _e:  # noqa: BLE001
    check("gemeinsam -> eigen geht ebenfalls", False, "es wirft: %s" % _e)

# Der persoenliche Standard ueberlebt das Verschieben - er haengt an der
# Kennung, und die aendert sich nicht.
# ⚠ IM try: wechselt die Kennung beim Verschieben (das waere der Fehler, den
# diese Pruefung sucht), findet `standard_setzen` sie nicht mehr und WIRFT - der
# Lauf braeche ab und lieferte keine Bilanz (Register).
try:
    jv.standard_setzen("chef", _v["id"], ist_admin=True)
    jv.speichern("chef", "Lösung suchen", "x", vid=_v["id"], global_=True,
                 ist_admin=True)
    check("der persoenliche Standard ueberlebt das Verschieben",
          jv.liste("chef", ist_admin=True)["standard"] == _v["id"])
except Exception as _e:  # noqa: BLE001
    check("der persoenliche Standard ueberlebt das Verschieben", False,
          "es wirft: %s" % _e)

# ── Rechte ─────────────────────────────────────────────────────────────────
# Eine gemeinsame zu einer eigenen zu machen nimmt sie ALLEN anderen weg. Das
# ist eine Entscheidung des Administrators, nicht die eines Benutzers.
_g = jv.speichern("chef", "Gemeinsame", "x", global_=True, ist_admin=True)
try:
    jv.speichern("bob", "Gemeinsame", "x", vid=_g["id"], global_=False,
                 ist_admin=False)
    check("ein Nicht-Admin darf eine gemeinsame nicht 'privatisieren'", False)
except jv.VorlagenFehler as f:
    check("ein Nicht-Admin darf eine gemeinsame nicht 'privatisieren'",
          "Administrator" in str(f), str(f))

# Und der Weg nach oben bleibt Admins vorbehalten (Bestandsregel).
_e = jv.speichern("bob", "Bobs eigene", "x")
try:
    jv.speichern("bob", "Bobs eigene", "x", vid=_e["id"], global_=True,
                 ist_admin=False)
    check("ein Nicht-Admin darf nichts gemeinsam machen", False)
except jv.VorlagenFehler as f:
    check("ein Nicht-Admin darf nichts gemeinsam machen",
          "Administrator" in str(f), str(f))

# ── Was NICHT verschoben werden darf ──────────────────────────────────────
# Eine wirklich unbekannte Kennung bleibt ein Fehler - sonst wuerde ein
# Tippfehler stillschweigend eine neue Vorlage anlegen.
try:
    jv.speichern("chef", "Neu?", "y", vid="gibtsnicht", ist_admin=True)
    check("eine unbekannte Kennung bleibt ein Fehler", False)
except jv.VorlagenFehler as f:
    check("eine unbekannte Kennung bleibt ein Fehler",
          "nicht gefunden" in str(f), str(f))

# Eine FREMDE eigene Vorlage ist unerreichbar - auch fuer einen Admin, auch
# ueber den Verschiebe-Weg: gesucht wird nur in der eigenen Liste.
_bob = jv.speichern("bob", "Bobs zweite", "x")
try:
    jv.speichern("chef", "Bobs zweite", "x", vid=_bob["id"], global_=True,
                 ist_admin=True)
    check("eine FREMDE eigene Vorlage bleibt unerreichbar", False)
except jv.VorlagenFehler as f:
    check("eine FREMDE eigene Vorlage bleibt unerreichbar",
          "nicht gefunden" in str(f), str(f))

print("\n%d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
