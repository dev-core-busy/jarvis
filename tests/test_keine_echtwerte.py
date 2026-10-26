#!/usr/bin/env python3
"""Waechter: keine Echtwerte (Hosts, AD-Domaenen, Konten) im Repository.

WARUM GEHASHT UND NICHT IM KLARTEXT
-----------------------------------
Eine Liste der verbotenen Werte im Klartext waere selbst das Leck, das sie
verhindern soll: eine einzige Datei, die alle echten Hostnamen, AD-Domaenen und
Anmeldenamen aufzaehlt, ist ein besseres Aufklaerungsziel als die verstreuten
Vorkommen. Gespeichert sind deshalb nur gesalzene Kuerzel (sha256, 16 Hex).

Das ist **keine Geheimhaltung** - wer den Wert raet, kann ihn nachrechnen, das
Salz steht hier. Es nimmt der Datei nur die Eigenschaft, durchsuchbar,
indizierbar und abschreibbar zu sein. Genau darum geht es.

WARUM EINE SPERRLISTE UND KEINE EIGENSCHAFTSREGEL
-------------------------------------------------
Die erste Fassung mass Eigenschaften (IPv4 ausserhalb der Beispielbereiche,
DC=-Teile, Mail-Domaenen, NetBIOS-Praefixe). Ergebnis am echten Bestand:
**1508 Fehlalarme** - Versionsnummern wie ``1.0.2.0`` sind gueltige oeffentliche
IPv4-Adressen, ``gradle\\`` sieht aus wie ein NetBIOS-Praefix, und minifiziertes
Fremd-JS enthaelt zufaellig ``DC=``. Ein Waechter mit dieser Trefferquote wird beim
ersten Lauf abgeschaltet und schuetzt danach nichts mehr (Register: "Eine falsche
Sonde ist schlimmer als keine").

Eine Sperrliste kennt nur echte Werte - Fehlalarme sind damit baulich
ausgeschlossen. Der Preis ist bekannt und steht hier, damit ihn niemand
uebersieht: **sie findet nur, was in ihr steht.** Wer einen neuen Echtwert
einfuehrt, muss ihn eintragen (Kuerzel erzeugen: siehe ``KUERZEL_BAUEN`` unten).

WAS ALS ECHTWERT GILT (seit 2026-10-01/02)
------------------------------------------
Jede interne IP-Adresse, jeder FQDN und jede E-Mail-Adresse - ausdruecklich
auch Netzwerkkomponenten: DNS-Server, Gateways, Exchange und andere Dienste.
Generell gesperrt sind ``*.`` und ``*@`` unter den Firmendomaenen: die
Sperrliste traegt die DOMAENE, und ``kandidaten()`` prueft jedes Punkt-Suffix -
``exchange.<firma>.de`` und ``wer@<firma>.int`` treffen damit, ohne dass jeder
Rechnername einzeln eingetragen werden muss. Seit 2026-10-20 ebenso jedes
Punkt-PRAEFIX und jede CamelCase-Grenze, damit auch ``<firma>.atlassian.net``
und ``<Firma>Adapter`` greifen (Begruendung an ``kandidaten()``). Adressen im
internen Netz faengt die Netzregel unten, auch wenn sie in keiner Liste stehen.

Exit 0 = sauber, 1 = Fund, 2 = konnte nicht laufen.
"""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
SALZ = "jarvis-echtwerte-v1"

KUERZEL_BAUEN = """    python3 -c "import hashlib; print(hashlib.sha256(
    ('jarvis-echtwerte-v1' + 'DERWERT'.lower()).encode()).hexdigest()[:16])" """

# 31 Kuerzel: interne Hosts, AD-Domaenen, Anmeldenamen, Freigabenamen.
#
# NICHT enthalten ist die PRODUKTMARKE. Der Markenname steckt auch im Hostnamen
# des Servers - gesperrt gehoert deshalb der volle Rechnername, nicht die Marke:
# sonst meldet der Waechter die Avatar-Gestaltung, die i18n-Texte und die
# Portal-Kacheln, also genau die Stellen, an denen der Name hingehoert.
#
# Die letzten sechs sind Namen DRITTER. Sie kamen erst ans Licht, als ein
# Kommentar in `chatlib.js` auffiel - die erste Runde hatte nur nach den Namen
# gesucht, die schon bekannt waren. Personenbezogene Daten Dritter wiegen
# schwerer als die eigenen: sie stehen hier, damit die naechste Runde sie nicht
# wieder suchen muss.
GESPERRT = {
    "01d829610764e932", "05cc4f0bdeaa5a83", "33a88325f496a71d", "388fe3cbdc40c64b",
    "3a119185fb0d70bc", "42693761c53244e9", "442f5f3a99dda37c", "501f9958fa227bc1",
    "519bdb2e934717d8", "5cb54637d080e37d", "688ff4d479ec3797", "6a094356dc99f8d1",
    "7bfe0991e028cca8", "96aa544d2f4b684c", "a39b62a61f9d21fb", "a6be159898cfe1f5",
    "a6f5da01dd2be5e3", "bf2be9182990e689", "ccdf1de673f9e287", "d224954e0da8e6c4",
    "d41a483f51566846", "e05e6a307b98bf34", "f0c2c7abd6637a87",
    "f9f398579bf2f1ba", "fe79bbf3813fe861",
    "07f987e2be77a00d", "2e7fc2fc9ffc2b3f", "35b05d03414f6117", "43582ad49bad97ef",
    "8111c3e1855245e2", "9f833a7a72da4c64",
    # 2026-10-01: Regel "keine IP-Adressen, FQDNs und E-Mail-Adressen im Repo".
    # Neue DEV-Adresse, Landing-Host, Tailscale-Adresse, interne Dateiserver,
    # eine Kunden- und eine Schwesterdomaene, Name einer dritten Person.
    "f1a0cd679b9e04b2", "e58fa2755a0b481e", "8d40bcccef0a7265", "d0d1d129d647e5f3",
    "5bd51d7ff2ace219", "e7ad10560fd138a3", "1cd6516bcd576163", "a722d3cb3358e151",
    "ef761db2cc7aaa94", "315f6f1ea9d71fad",
    # 2026-10-02: Rechnername nach dem internen Namensschema (Testdatum).
    "87edfafb90aeed0d",
    # 2026-10-15 (Inhaltspruefung vor dem Neustart der Historie): Firmen- und
    # Markenname, Vorname aus einem Freigabenamen, interne Jira-Projektkuerzel,
    # CRM-Kundennummern und eine Telefonnummer samt ihren Schreibweisen;
    # dazu vier Anmeldekennungen aus Vorfallbeschreibungen und Tests.
    "93084a9551581ffe", "20fcad51c2497f0f", "d27f594773aaa5d6", "43dbc49b79bf026d",
    "bd444a950a36888d", "db7461d8e19184f5", "a56c7698f3afb3fa", "df0498271763451b",
    "940de1e77f075387", "387690174eaab84d", "a8aa302a4ea8e5ca", "a84b678a81b9e328",
    "4c9d730d42b68927", "c50bd72ebd05e3ec", "134303bbd311e55b", "478837e9e17b25f9",
    "2790eb528952c763", "8709b4a5275d8991", "777713b557718d59", "609b70d46663b302",
    "e2fd9e73edc665e4",
    # 2026-10-26: interne Confluence-Seitennummern (Benutzerhandbuch alt/neu,
    # BSI-Seite). Eine blanke Zahl traegt keine Domaene, die Domaenen-Eintraege
    # greifen deshalb nicht - die Nummer selbst gehoert gesperrt.
    "012bbf888993cccc", "5bc199baab01b3ae", "3fb4fbcafa145d4d",
}

# Interne NETZE (die ersten beiden Oktette, gehasht wie oben). Die Sperrliste
# kennt nur einzelne Adressen - jede neue (ein Adresswechsel, ein weiterer
# Server) waere bis zum Nachtragen unsichtbar. Genau so ist es passiert: die
# neue DEV-Adresse stand am Tag des Wechsels schon in Dateien, die Liste kannte
# nur die alte. Ein /16-Praefix trifft keine Versionsnummer, die nicht zufaellig
# mit denselben zwei Zahlen beginnt - der Grund, warum die Eigenschaftsregel
# (1508 Fehlalarme) hier nicht wiederkehrt.
GESPERRTE_NETZE = {"28f40481d0bf3e22"}
RE_IPV4 = re.compile(r"(?<![\w.])(\d{1,3})\.(\d{1,3})\.\d{1,3}\.\d{1,3}(?![\w.])")

# Dateien, deren Echtwerte im Betrieb gebraucht werden. Jeder Eintrag traegt
# seinen Grund; ein Eintrag ohne passende Datei ist selbst ein Fund (sonst
# verrottet die Liste still).
#
# Seit 2026-10-01 gilt: "im Betrieb gebraucht" ist KEIN Grund mehr. Server-Ziele
# kommen aus der Umgebung bzw. der gitignorierten .env (deploy/ziele.py,
# deploy/ziele.js), Vorgaben fuer Clients setzt der Build. Die frueheren
# Ausnahmen fuer live_-/messung_-Proben, Deploy-Werkzeuge, Firewall, Windows-
# Client und Kamera-Feed sind deshalb gestrichen - eine Ausnahme hier ist ein
# Leck mit Begruendung, kein sauberer Zustand.
#
# Die gecko-id der Firefox-Erweiterung war bis 2026-10-01 eine Adresse unter der
# Firmendomaene und hier ausgenommen. Sie ist jetzt eine GUID - die Kennung
# braucht keine Domaene.
#
# Seit 2026-10-15 auch KEINE Ausnahme mehr fuer diesen Waechter und seine
# Gegenprobe: beide tragen keinen Klartext mehr (synthetische Positivkontrolle,
# Proben aus einer gitignorierten Datei) und werden selbst mitgeprueft.
AUSNAHMEN = {}

# Ein Wort-Zeichen, dann Buchstaben/Ziffern/Punkt/Strich/Unterstrich. Trennt an
# @ \ / " ' < > ( ) usw. - damit wird aus "FIRMA\\m.mustermann@beispiel.de"
# die Folge "FIRMA", "m.mustermann", "beispiel.de".
RE_WORT = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?")

# Grenze eines zusammengeschriebenen Bezeichners: Kleinbuchstabe/Ziffer vor
# Grossbuchstabe, oder Akronym-Ende vor einem neuen Wort ("AGWert" -> "AG",
# "Wert"). Siehe kandidaten(), Abschnitt "zusammengeschrieben".
RE_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
# Die unteilbaren Stuecke eines Wortes - Grundlage der CamelCase-Zerlegung.
RE_ATOM = re.compile(r"[-_.]")

# ── Zweite Regel: AD-Domaenenteile ──────────────────────────────────────────
# Die Sperrliste kann den DN-Fall nicht vollstaendig abdecken: ein DN zerfaellt
# in Einzelwoerter, und nicht jeder echte Domaenenteil steht auf der Liste. Die
# Gegenprobe hat genau diese Luecke gefunden: der DN-Fall, mit dem die
# Bereinigung begann, blieb unentdeckt.
#
# Im DN-Zusammenhang ist eine Positivliste dagegen tragfaehig: ``DC=`` kommt in
# handgeschriebenem Code nur in echten Unterscheidungsnamen vor.
ERLAUBTE_DC = {"firma", "local", "company", "example", "com", "test", "beispiel",
               "domain", "corp", "intern", "lan"}
RE_DC = re.compile(r"\bDC=([A-Za-z0-9_-]+)", re.IGNORECASE)
RE_DN_KONTEXT = re.compile(r"\b(?:CN|OU)=|DC=[^,\s]+,\s*DC=", re.IGNORECASE)
# Minifiziertes Fremd-JS enthaelt zufaellig "DC=" - drei Fehlalarme allein in
# mermaid.min.js. Solche Dateien schreibt hier niemand von Hand.
RE_FREMDCODE = re.compile(r"(^|/)vendor/|\.min\.(js|css)$|^frontend/js/vendor/")

# ── Dritte Regel: Kontonamen der Form vorname.nachname ──────────────────────
# ⚠ WARUM (2026-10-21): in einem Kommentar von main.py standen zwei echte
# AD-Konten samt Gruppenname, in einem Test zwei weitere aus einem Vorfall –
# seit dem Neustart der Historie oeffentlich, und dieser Waechter war gruen.
# Die Sperrliste kann sie strukturell nicht kennen: zwei der vier Konten waren
# auf keinem Server mehr konfiguriert, eine Liste haette sie nie bekommen.
# Deshalb die FORM: ein gaengiger Vorname, ein Punkt, ein Nachname. Zugelassen
# sind nur ausdrueckliche Platzhalter. Ein Vorname allein ist kein Echtwert;
# trotzdem fehlen hier ausdruecklich die Vornamen echter Personen aus dem
# Betrieb (sie stehen auf der Sperrliste), und ``max`` fehlt, weil es als
# Variablenname ueberall vorkommt (``max.replace(...)``).
VORNAMEN = set("""
    alexander andrea andreas angelika anja anke annette antje barbara bernd
    bernhard bettina birgit brigitte carsten christian christina christine
    christoph claudia daniel daniela dennis dieter dirk dominik doris elke
    erik fabian felix florian frank franz gabriele georg gerhard gisela hans
    harald heike heinz helga helmut holger ines ingrid irene jan jana
    jens joachim jochen johannes jonas joerg jutta juergen julia julian karin
    karl katharina katja kerstin klaus kurt lars laura lisa lukas manfred
    manuela marco marcus maria marie marina marion mario markus martin
    martina matthias melanie michael michaela monika nadine natalie nicole
    niklas nils nina norbert olaf oliver patrick paul peter petra philipp
    rainer ralf ralph regina reinhard renate robert roland rolf ruth
    sabine sabrina sandra sarah sascha sebastian silke simon simone sonja
    stefan stefanie steffen stephan susanne sven tanja thomas thorsten tobias
    torsten udo ulrich ulrike ursula uwe verena volker walter werner wolfgang
    yvonne anna lena
""".split())
ERLAUBTE_PERSONEN = {
    "anna.beispiel", "anna.beispielmann", "anna.muster", "lena.musterfrau",
    "max.muster", "max.mustermann", "max.mueller", "erika.musterfrau",
}
# Zweiter Teil, der ein Code-Zugriff oder eine Dateiendung ist (``anna.json``).
TECHNISCH = {"length", "name", "value", "size", "text", "id", "json", "cls",
             "txt", "md", "py", "js", "csv", "xlsx", "docx", "pdf", "png", "log"}
RE_PERSON = re.compile(r"(?<![A-Za-z0-9_.@])([A-Za-z]{3,12})\.([A-Za-z]{3,24})(?![A-Za-z0-9_])")


def personen(zeile: str):
    """Kontonamen der Form vorname.nachname, die kein Platzhalter sind."""
    for m in RE_PERSON.finditer(zeile):
        vor, nach = m.group(1).lower(), m.group(2).lower()
        wort = vor + "." + nach
        if vor in VORNAMEN and nach not in TECHNISCH and wort not in ERLAUBTE_PERSONEN:
            yield "<Kontoname %s>" % kuerzel(wort)


_ok = _fail = 0


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  ok   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  -> " + detail) if detail else ""))


def kuerzel(wort: str) -> str:
    return hashlib.sha256((SALZ + wort.lower()).encode()).hexdigest()[:16]


def kandidaten(zeile: str):
    """Jedes Wort und zusaetzlich seine Teilformen.

    ``dp-rechner.ai.beispiel.de`` ist EIN Wort; ohne die Suffixe wuerde der
    Eintrag fuer die Domaene darin nicht greifen.

    Die Zeile wird zweimal zerlegt: einmal roh und einmal ohne Rueckstriche.
    Ein Name in einem regulaeren Ausdruck steht escaped da (``m\\.mustermann``);
    der Rueckstrich trennt das Wort, und der Eintrag greift nicht. Vier solche
    Stellen standen genau so im Bestand - in einer davon war die BESCHRIFTUNG der
    Pruefung ersetzt und der Ausdruck daneben nicht, was den Bericht wie einen
    Selbstwiderspruch aussehen liess.

    ZWEI BLINDE FLECKEN, GESCHLOSSEN 2026-10-20
    -------------------------------------------
    Bis dahin entstanden nur das Wort, seine Punkt-SUFFIXE und die Teile an
    Bindestrich/Unterstrich. Daraus folgten zwei Luecken, beide gemessen:

    *Praefix vor dem ersten Punkt.* ``<firma>.de`` ist EIN Wort; sein einziges
    Suffix ist ``de``, der Firmenname selbst entstand nie. Ein Host bei einem
    FREMDEN Anbieter rutschte damit durch - ``<firma>.atlassian.net``,
    ``<firma>.sharepoint.com`` - also genau die Form, die dieses Projekt mit
    seinen Jira-, Confluence- und OneNote-Anbindungen erzeugen kann. Gesperrt
    ist der Firmenname, nicht die Fremddomaene: ohne das Praefix greift kein
    Eintrag. Deshalb entstehen jetzt Praefixe UND Suffixe, und bei mehr als
    zwei Marken zusaetzlich jede Einzelmarke (die Mitte von ``a.<firma>.de``
    ist weder Praefix noch Suffix).

    *Zusammengeschrieben.* ``class <Firma>Adapter`` und ``const <firma>ApiUrl``
    sind je ein Wort ohne Trennzeichen - die Zerlegung an ``[-_]`` fasst sie
    nicht. Ein Bezeichner ist der naheliegendste Ort, an dem ein Firmenname in
    Code landet. Zerlegt wird deshalb zusaetzlich an den CamelCase-Grenzen.

    Der Preis ist gemessen, nicht geschaetzt: +14,3 % Kandidaten je Zeile
    (3.277.991 -> 3.745.880 ueber 532.674 Zeilen, Stand 2026-10-20) und
    **null** zusaetzliche Treffer auf dem sauberen Baum - die alte und die neue
    Sonde liefen dafuer Zeile fuer Zeile gegeneinander. Diese Zahl steht hier,
    weil ein Waechter mit Fehlalarmen abgeschaltet wird und diese Datei genau
    daran schon einmal gescheitert ist (1508 Fehlalarme, siehe
    Modul-Docstring)."""
    gesehen = set()
    for fassung in (zeile, zeile.replace("\\", "")):
        for wort in RE_WORT.findall(fassung):
            kette = [wort]
            if "." in wort:
                marken = wort.split(".")
                for i in range(1, len(marken)):
                    kette.append(".".join(marken[i:]))   # Suffixe
                    kette.append(".".join(marken[:i]))   # Praefixe
                if len(marken) > 2:
                    kette += marken                      # Einzelmarken der Mitte
            # Die Teile an Bindestrich und Unterstrich: der Eintrag fuer einen
            # Namen griff nur in EINER Schreibweise (``OneNote_text_<Name>``),
            # ``OneNote-<Name>`` rutschte als ein einziges Wort durch
            # (gefunden 2026-10-15).
            if "-" in wort or "_" in wort:
                kette += [x for x in re.split(r"[-_]", wort) if x and x != wort]
            # Zusammengeschrieben, auf den ATOMEN (an Punkt, Strich und
            # Unterstrich getrennt). Die beiden Vorfilter sind nicht Kosmetik,
            # sondern gemessen (derselbe Baum, je drei Laeufe): ohne sie kostet
            # die Erweiterung +78 % Laufzeit, mit dem Gross-/Kleinwechsel-Test
            # +41 %, mit dem Schnellweg fuer trennerfreie Woerter +14 % - also
            # so viel, wie die Kandidatenzahl waechst. Keine Sekundenwerte hier:
            # die haengen am Rechner und an der Baumgroesse (Register: eine
            # feste Zahl in einem Verweis ist eine Zeitbombe). Ein Stueck ohne
            # Gross-/Kleinwechsel kann gar keine CamelCase-Grenze haben, und das
            # trennerfreie Wort ist der haeufigste Fall.
            for stueck in (RE_ATOM.split(wort) if RE_ATOM.search(wort)
                           else (wort,)):
                if not stueck or stueck.islower() or stueck.isupper() \
                        or stueck.isdigit():
                    continue
                teile = RE_CAMEL.split(stueck)
                if len(teile) > 1:
                    kette += teile
            for teil in kette:
                if teil and teil not in gesehen:
                    gesehen.add(teil)
                    yield teil


def netze(zeile: str, gesperrt=None):
    """IPv4-Adressen der Zeile, deren /16-Praefix gesperrt ist (ausgegeben ohne
    die Adresse selbst - der Bericht soll das Leck nicht wiederholen)."""
    for m in RE_IPV4.finditer(zeile):
        liste = GESPERRTE_NETZE if gesperrt is None else gesperrt
        if kuerzel("%s.%s" % (m.group(1), m.group(2))) in liste:
            yield "<internes Netz %s>" % kuerzel(m.group(0))


def ausgenommen(rel: str):
    for muster, grund in AUSNAHMEN.items():
        if re.search(muster, rel):
            return muster, grund
    return None, None


# ════════════════════════════════════════════════════════════════════════════
# POSITIVKONTROLLE - vor jeder inhaltlichen Pruefung.
# Ohne sie waere ein gruener Lauf bedeutungslos: ein Waechter, dessen Sonde
# nichts erkennt, meldet auf jedem Bestand "sauber".
# ════════════════════════════════════════════════════════════════════════════
# SYNTHETISCH, ohne einen einzigen Echtwert (seit 2026-10-15): vorher stand
# hier ein echter Host und die Firmendomaene, aus Teilen zusammengesetzt - in
# einem lesbaren Repo ist das kein Schutz. Gemessen wird die SONDE (Zerlegung,
# Suffixe, Kuerzel, Nachschlagen) gegen eine Probe-Sperrliste; dass die echte
# Liste die echten Werte kennt, misst ``gegen_keine_echtwerte.py`` mit einer
# gitignorierten Probendatei.
_PROBE_GESPERRT = {kuerzel("sonde.invalid"), kuerzel("sondenname"),
                   kuerzel("sondenmarke")}
PROBE = ("\\\\192.0.2.77\\Freigabe und Mail p.mueller@dp.sonde.invalid, "
         "Ordner OneNote-sondenname")
# Getrennte Literale: die Quellzeile selbst darf kein "D"+"C=" tragen,
# sonst meldet die DN-Regel ihre eigene Probe.
PROBE_DN = "CN=X,D" "C=sondenfirma,D" "C=int"
# Die Formen, die bis 2026-10-20 blind waren (siehe kandidaten()). Jede Probe
# isoliert GENAU EINEN neuen Zweig - sonst ist die Kontrolle trivial wahr:
#
# ⚠ Die erste Fassung dieser Kontrolle benutzte ``sondenmarke.beispiel.de`` fuer
# den Praefix-Fall. Das sind DREI Marken, und damit traf sie ueber den
# Einzelmarken-Zweig: eine Sabotage, die die Praefixe entfernte, blieb GRUEN
# (gemessen, Exit 0 statt 2). Die Probe muss die Stelle treffen, die sie meint -
# zwei Marken fuer das Praefix, drei fuer die Mitte.
PROBE_PRAEFIX = "host = 'sondenmarke.de'"          # nur ueber das Praefix
PROBE_MARKE = "cdn = 'a.sondenmarke.de'"           # nur ueber die Einzelmarke
PROBE_CAMEL = "class SondenmarkeAdapter:  # und ProSondenmarkeGmbH"

_getroffen = {w for w in kandidaten(PROBE) if kuerzel(w) in _PROBE_GESPERRT}
_getroffen_dn = ([t for t in RE_DC.findall(PROBE_DN) if t.lower() not in ERLAUBTE_DC]
                 if RE_DN_KONTEXT.search(PROBE_DN) else [])
_getroffen_praefix = {w for w in kandidaten(PROBE_PRAEFIX)
                      if kuerzel(w) in _PROBE_GESPERRT}
_getroffen_marke = {w for w in kandidaten(PROBE_MARKE)
                    if kuerzel(w) in _PROBE_GESPERRT}
_getroffen_camel = {w for w in kandidaten(PROBE_CAMEL)
                    if kuerzel(w) in _PROBE_GESPERRT}

if len(_getroffen) < 2:
    print("ABBRUCH (Exit 2): die Sonde erkennt ihre Probe nicht.")
    print("  Gefunden: %r - erwartet waren Domaenen-Suffix UND Namensteil." % sorted(_getroffen))
    print("  Ohne funktionierende Sonde ist jeder gruene Lauf bedeutungslos.")
    sys.exit(2)
if not _getroffen_praefix:
    print("ABBRUCH (Exit 2): die Sonde erkennt den Namen nicht als Praefix einer")
    print("  fremden Domaene (<name>.de) - genau die Form, in der ein Host bei")
    print("  einem Fremdanbieter steht. Bis 2026-10-20 war sie blind.")
    sys.exit(2)
if not _getroffen_marke:
    print("ABBRUCH (Exit 2): die Sonde erkennt den Namen nicht als MITTLERE")
    print("  Marke (a.<name>.de) - die ist weder Praefix noch Suffix und")
    print("  braucht den eigenen Zweig fuer Woerter mit mehr als zwei Marken.")
    sys.exit(2)
if not _getroffen_camel:
    print("ABBRUCH (Exit 2): die Sonde erkennt den Namen nicht in einem")
    print("  zusammengeschriebenen Bezeichner (CamelCase) - der naheliegendste")
    print("  Ort, an dem ein Name in Code landet. Bis 2026-10-20 blind.")
    sys.exit(2)
if not all(re.fullmatch(r"[0-9a-f]{16}", x) for x in GESPERRT | GESPERRTE_NETZE):
    print("ABBRUCH (Exit 2): die Sperrliste enthaelt einen Eintrag, der kein Kuerzel ist.")
    sys.exit(2)
# Netzregel: eine Adresse im (synthetisch) gesperrten Netz wird erkannt, eine
# Versionsnummer mit denselben Ziffern nicht - und die echte Liste meldet weder
# Versionsnummer noch Beispieladresse.
_probe_netz = {kuerzel("198.51")}
if (not list(netze("ziel=198.51.100.7", _probe_netz))
        or list(netze("v198.51.100.7", _probe_netz))
        or list(netze("v1.0.2.0 und 10.0.0.10"))):
    print("ABBRUCH (Exit 2): die Netzregel erkennt ihre Probe nicht oder meldet")
    print("  eine Versionsnummer bzw. eine Beispieladresse.")
    sys.exit(2)
# Kontonamen-Regel: synthetisch, mit einem Nachnamen, den es nicht gibt.
# Klein (AD-Form), gross (Anzeigeform) und mit Domaenen-Praefix muessen treffen;
# Platzhalter, Code-Zugriffe und Dateinamen duerfen es nicht.
_probe_personen = [list(personen(z)) for z in (
    # Getrennte Literale: die Quellzeile selbst darf nicht treffen.
    "editors_users='jutta." "sondenfrau'", "fuer Jutta." "Sondenfrau:",
    "FIRMA\\jutta." "sondenfrau")]
_falsch_personen = [z for z in (
    "user = 'anna.beispiel'", "anna.json", "peter.length", "self.name", "a.peter.b")
    if list(personen(z))]
if not all(_probe_personen) or _falsch_personen:
    print("ABBRUCH (Exit 2): die Kontonamen-Regel erkennt ihre Probe nicht oder")
    print("  meldet einen Platzhalter/Code-Zugriff -> %r / %r"
          % ([bool(x) for x in _probe_personen], _falsch_personen))
    sys.exit(2)
if not _getroffen_dn:
    print("ABBRUCH (Exit 2): die DN-Regel erkennt ihre eigene Probe nicht.")
    print("  Genau diese Luecke hat die Gegenprobe einmal gefunden - der Fall,")
    print("  mit dem die Bereinigung begann, blieb unentdeckt.")
    sys.exit(2)

SAUBER = "\\\\10.0.0.10\\Freigabe und Mail m.mustermann@beispiel.de"
SAUBER_DN = "CN=Jarvis-Users,OU=Groups,DC=firma,DC=local"
_falsch = {w for w in kandidaten(SAUBER) if kuerzel(w) in GESPERRT}
_falsch |= {"DC=" + t for t in RE_DC.findall(SAUBER_DN)
            if t.lower() not in ERLAUBTE_DC}
if _falsch:
    print("ABBRUCH (Exit 2): die Sonde meldet einen sauberen Text -> %r" % sorted(_falsch))
    sys.exit(2)

print("Positivkontrolle: Sperrliste erkennt %d Echtwerte, die DN-Regel %d, "
      "Praefix %d,\nEinzelmarke %d und CamelCase %d - und der saubere Text "
      "loest nichts aus.\n"
      % (len(_getroffen), len(_getroffen_dn), len(_getroffen_praefix),
         len(_getroffen_marke), len(_getroffen_camel)))

# ════════════════════════════════════════════════════════════════════════════
# Verzeichnete UND noch nicht verzeichnete Dateien (ohne die ignorierten).
# Ein Echtwert in einer frisch angelegten, noch nicht hinzugefuegten Datei ist
# derselbe Fund - er faellt sonst erst nach dem Commit auf, also zu spaet.
dateien = []
for befehl in (["git", "ls-files"],
               ["git", "ls-files", "--others", "--exclude-standard"]):
    try:
        roh = subprocess.run(befehl, cwd=WURZEL, capture_output=True,
                             text=True, check=True, timeout=120).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        print("ABBRUCH (Exit 2): %s nicht ausfuehrbar -> %s" % (" ".join(befehl), exc))
        sys.exit(2)
    dateien.extend(d for d in roh.split("\n") if d)
if len(dateien) < 100:
    print("ABBRUCH (Exit 2): nur %d verzeichnete Dateien - kein vollstaendiger Baum."
          % len(dateien))
    sys.exit(2)

benutzte_ausnahmen = set()
funde = []
gelesen = 0

for rel in dateien:
    pfad = WURZEL / rel
    if not pfad.is_file():
        continue
    muster, _grund = ausgenommen(rel)
    if muster:
        benutzte_ausnahmen.add(muster)
        continue
    try:
        text = pfad.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        continue                      # Binaerdateien ueberspringen
    gelesen += 1
    fremd = bool(RE_FREMDCODE.search(rel))
    for nr, zeile in enumerate(text.splitlines(), 1):
        for wort in kandidaten(zeile):
            if kuerzel(wort) in GESPERRT:
                funde.append((rel, nr, wort))
        for netz in netze(zeile):
            funde.append((rel, nr, netz))
        if not fremd:
            for person in personen(zeile):
                funde.append((rel, nr, person))
        if not fremd and RE_DN_KONTEXT.search(zeile):
            for teil in RE_DC.findall(zeile):
                if teil.lower() not in ERLAUBTE_DC:
                    funde.append((rel, nr, "DC=" + teil))

print("Gelesen: %d von %d verzeichneten Dateien "
      "(Rest binaer oder ausgenommen)\n" % (gelesen, len(dateien)))

pruefe(gelesen > len(dateien) // 2,
       "Positivkontrolle: der Lauf hat den Baum wirklich gelesen",
       "nur %d Dateien" % gelesen)

pruefe(not funde, "kein gesperrter Echtwert im Arbeitsbaum",
       "%d Stellen, z.B. %s" % (len(funde), funde[:5]) if funde else "")

verwaist = sorted(set(AUSNAHMEN) - benutzte_ausnahmen)
pruefe(not verwaist, "jede Ausnahme deckt noch mindestens eine Datei",
       "verwaist: %s" % verwaist if verwaist else "")

if funde:
    print("\nAlle Fundstellen:")
    for rel, nr, wort in funde:
        print("  %s:%d  %s" % (rel, nr, wort))
    print("\nEntweder den Wert durch einen Platzhalter ersetzen oder - wenn er "
          "im Betrieb\ngebraucht wird - die Datei mit Begruendung in AUSNAHMEN "
          "eintragen.")

print("\n" + "=" * 70)
print("Ergebnis: %d ok, %d fehlgeschlagen" % (_ok, _fail))
sys.exit(1 if _fail else 0)
