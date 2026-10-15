"""Keine EXTERNE Einbindung unter `frontend/` - Bibliotheken liegen lokal.

DER FEHLER, DEN DAS VERHINDERT: ein `<link>` auf `fonts.googleapis.com` hat in
diesem Projekt schon eine Admin-Oberflaeche gekostet (Ladezeit-Vorfall; im
Register steht seit damals woertlich "Nie wieder extern einbinden"). Trotzdem
stand bis 2026-10-05 in `frontend/js/whatsapp.js` ein
`script.src = 'https://cdn.jsdelivr.net/npm/qrcodejs@1.0.0/qrcode.min.js'`.

⚠ DER ZWEITE GRUND IST SCHWERER ALS DIE LADEZEIT: Jarvis laeuft in Umgebungen
mit Egress-Sperre (nftables, siehe Register). Dort scheitert ein CDN-Aufruf -
und zwar STILL, wenn der Aufrufer den Fehlschlag abfaengt: der QR-Code der
WhatsApp-Anmeldung blieb einfach aus, ohne erkennbaren Grund. Eine Abhaengigkeit,
die nur mit Internetzugang funktioniert, ist in einer abgeschotteten
Installation keine Abhaengigkeit, sondern ein Ausfall.

⚠ KEINE GEPFLEGTE LISTE. Der Waechter sucht die Fundstellen selbst (jede HTML-,
JS- und CSS-Datei unter `frontend/`) - eine Liste waere an dem Tag
unvollstaendig, an dem jemand eine Bibliothek ergaenzt.

⚠ EIN `<a href="https://...">` IST KEINE EINBINDUNG. Ein Hyperlink auf
crontab.guru oder die Google Cloud Console ist eine Navigation, die der Benutzer
ausloest - nichts, was der Browser beim Aufbau der Seite holt. Wer das mitzaehlt,
baut einen Waechter, der staendig Fehlalarm gibt und deshalb abgeschaltet wird.
Gemessen wird deshalb das umschliessende TAG, nicht das Attribut allein.

AUSNAHMEN STEHEN IN DER DATEI, NICHT HIER (Hausstil, vgl. Abschnitt 3 von
test_jsdom_einbindung.js): eine Zeile mit `jarvis-extern-erlaubt: <grund>` in
derselben oder der vorhergehenden Zeile nimmt die Einbindung heraus. So sieht
ein Leser den Grund an der Stelle, und eine neue Ausnahme kostet einen
bewussten Kommentar statt einer Zeile in einer Liste.
Heute genutzt von `frontend/addin/taskpane.html` und
`frontend/excel-addin/taskpane.html` fuer Office.js: Microsoft dokumentiert das
eigene CDN als den vorgesehenen Bezugsweg und stellt die Bibliothek unter eigene
Lizenzbedingungen - eine lokale Kopie ist dort nicht der Weg (am 2026-10-05an
der Microsoft-Doku nachgelesen, nicht aus dem Gedaechtnis behauptet).

⚠ GELTUNGSBEREICH: `frontend/`, `skills/` UND `browser-addon/` - also alles,
was HTML/JS/CSS an einen Browser ausliefert.

`skills/` kam am 2026-10-05 dazu, und der Weg dorthin gehoert zur Regel:
`skills/jarvis-vision/templates/index.html` band `fonts.googleapis.com` ein -
genau den Vorfall, der hier schon eine Admin-Oberflaeche gekostet hat. Beim
ersten Bau dieses Waechters stand der Bereich deshalb bewusst DRAUSSEN und der
Fall als benannter Rueckstand im Docstring: die Schrift wird benutzt
(`static/style.css`, `font-family: 'Inter'`), ein blosses Entfernen des Links
haette die Darstellung geaendert. Inzwischen liegt die Schrift lokal
(`static/fonts/inter-latin.woff2` + `@font-face`), der Bereich ist sauber, und
die Regel deckt ihn ab.
**Merkregel: einen Bereich aus dem Geltungsbereich zu nehmen ist nur dann
vertretbar, wenn der GRUND dafuer im Waechter steht - sonst sieht ein
Geltungsbereich wie eine Messung aus und ist eine Luecke.**

Lauf:  python3 tests/test_keine_externen_einbindungen.py
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Alles, was HTML/JS/CSS an einen Browser ausliefert. Mehrere Wurzeln statt
# einer: ein Bereich, der nur deshalb sauber bleibt, weil niemand hinsieht,
# ist keine Zusage (Begruendung zu `skills/` im Docstring).
WURZELN = ("frontend", "skills", "browser-addon")

# Attribute, mit denen der Browser etwas HOLT. `<a href>` ist absichtlich nicht
# dabei (Navigation) - welches Tag es ist, entscheidet _tag_vor().
_ATTR = re.compile(r'\b(src|href)\s*=\s*["\'](https?://[^"\']+)["\']', re.I)
# Zuweisung im JS: element.src = 'http...'
_JS_ZUW = re.compile(r'\.\s*(src|href)\s*=\s*["\'](https?://[^"\']+)["\']', re.I)
# CSS: url(http...) - Schriften, Hintergrundbilder
_CSS_URL = re.compile(r'url\(\s*["\']?(https?://[^"\')]+)', re.I)

_NAVIGATION = {"a", "area", "base"}
_MARKE = "jarvis-extern-erlaubt"
_AUS = ("node_modules", ".git", ".claude", "venv", "__pycache__")

res = []


def check(name, cond, detail=""):
    res.append(bool(cond))
    mark = "\033[32m✓\033[0m" if cond else "\033[31m✗\033[0m"
    print(f"  {mark} {name}" + ("" if cond else f" – {detail}"))


def abbruch(text):
    """Exit 2 = konnte nicht laufen. Muss von Exit 1 (= beisst) unterscheidbar
    bleiben, sonst sieht ein kaputter Messaufbau wie ein Befund aus."""
    print(f"\n\033[31mABBRUCH: {text}\033[0m")
    print("Exit 2 = konnte nicht laufen, NICHT 'Waechter beisst'.")
    sys.exit(2)


def _tag_vor(text, pos):
    """Das Tag, zu dem ein Attribut an Stelle `pos` gehoert.

    Rueckwaerts bis zum naechsten `<name` - damit wird auch ein Tag erfasst, das
    sich ueber mehrere Zeilen zieht (`<script\\n  async\\n  src=...>`). Ein
    Vergleich je Zeile wuerde die verfehlen und waere damit zahnlos.
    """
    ab = text.rfind("<", 0, pos)
    if ab < 0:
        return ""
    m = re.match(r"<\s*([A-Za-z][A-Za-z0-9-]*)", text[ab:pos + 1])
    return m.group(1).lower() if m else ""


def _zeile(text, pos):
    return text.count("\n", 0, pos) + 1


def _befreit(zeilen, nr):
    """Marke in DERSELBEN Zeile - oder im Kommentarblock DIREKT darueber.

    ⚠ EIN PRUEFFENSTER FESTER GROESSE WAERE HIER FALSCH (Register: es greift in
    den Nachbarblock). Zwei Zeilen waren die erste Fassung, und sie haben die
    beiden Office-Ausnahmen NICHT erfasst: deren Begruendung steht - voellig
    richtig - oben in einem mehrzeiligen `<!-- ... -->` ueber dem Tag, zehn
    Zeilen entfernt. Wer dann das Fenster aufzieht, baut die Zeitbombe.
    Gesucht wird deshalb der ZUSAMMENHAENGENDE Kommentar, der unmittelbar vor
    der Fundzeile endet - bei HTML von `-->` aufwaerts bis `<!--`, bei JS ueber
    die `//`-Zeilen bzw. einen hier endenden `/* */`-Block. Damit darf die
    Begruendung so lang sein, wie sie sein muss, und sie kann trotzdem nicht aus
    einem fremden Block hereinwirken.
    """
    i = nr - 1
    if 0 <= i < len(zeilen) and _MARKE in zeilen[i]:
        return True

    j = i - 1
    while j >= 0 and not zeilen[j].strip():
        j -= 1
    if j < 0:
        return False

    if zeilen[j].strip().endswith("-->"):
        k = j
        while k >= 0:
            if _MARKE in zeilen[k]:
                return True
            if "<!--" in zeilen[k]:
                return False
            k -= 1
        return False

    k = j
    while k >= 0:
        t = zeilen[k].strip()
        if _MARKE in zeilen[k]:
            return True
        if t.startswith("//") or t.startswith("*") or t.endswith("*/"):
            if t.startswith("/*"):
                return False
            k -= 1
            continue
        return False
    return False


def funde_in(text, dateiname):
    """Alle externen EINBINDUNGEN - ohne Navigation, ohne data:-URIs."""
    zeilen = text.split("\n")
    treffer = []
    ist_html = dateiname.endswith(".html")

    if ist_html:
        for m in _ATTR.finditer(text):
            if _tag_vor(text, m.start()) in _NAVIGATION:
                continue
            treffer.append((_zeile(text, m.start()), m.group(2)))
    if dateiname.endswith(".js") or ist_html:
        for m in _JS_ZUW.finditer(text):
            treffer.append((_zeile(text, m.start()), m.group(2)))
    if dateiname.endswith(".css") or ist_html:
        for m in _CSS_URL.finditer(text):
            treffer.append((_zeile(text, m.start()), m.group(1)))

    # Doppelte (ein Treffer kann von zwei Mustern kommen) zusammenfassen
    einmalig = sorted(set(treffer))
    return [(nr, url) for nr, url in einmalig if not _befreit(zeilen, nr)]


# ── Grundlage und Positivkontrollen ─────────────────────────────────────────
# ⚠ JEDE Wurzel muss existieren. Ein stillschweigend uebersprungener Bereich
# waere genau die Luecke, gegen die der Geltungsbereich gebaut ist - ein Tippfehler
# im Namen machte den Waechter dort dauerhaft blind, ohne eine Zeile Ausgabe.
fehlende = [w for w in WURZELN if not os.path.isdir(os.path.join(ROOT, w))]
if fehlende:
    abbruch("Geltungsbereich unvollstaendig - es gibt nicht: " + ", ".join(fehlende))

dateien = []
for wurzel in WURZELN:
    for muster in ("**/*.html", "**/*.js", "**/*.css"):
        for p in glob.glob(os.path.join(ROOT, wurzel, muster), recursive=True):
            rel = os.path.relpath(p, ROOT)
            if any(t in _AUS for t in rel.split(os.sep)):
                continue
            dateien.append(p)
dateien = sorted(set(dateien))

print("\n\033[1m1. Grundlage und Positivkontrollen\033[0m")
if len(dateien) < 30:
    abbruch(f"nur {len(dateien)} Dateien in {WURZELN} gefunden (erwartet: Dutzende)")
check(f"{len(dateien)} Dateien unter {'/, '.join(WURZELN)}/ gelesen", True)

# ⚠ DAS MESSWERKZEUG GEGEN EINEN BEKANNTEN FALL. Ohne diese Kontrolle ist jede
# gruene Bilanz unten wertlos: ein Muster, das NIE trifft, sieht genauso aus wie
# "es gibt keine externen Einbindungen".
_PROBE = (
    '<a href="https://example.com/doku">Hilfe</a>\n'
    '<script src="https://cdn.example.com/lib.js"></script>\n'
    '<link rel="stylesheet" href="https://fonts.example.com/css?family=X">\n'
    '<script src="/static/js/vendor/lokal.min.js?v=1"></script>\n'
    "<img src=\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'%3E\">\n"
    '<script\n  async\n  src="https://mehrzeilig.example.com/o.js"></script>\n'
)
p_funde = {u for _, u in funde_in(_PROBE, "probe.html")}
check("die Probeseite liefert genau die DREI externen Einbindungen",
      p_funde == {"https://cdn.example.com/lib.js",
                  "https://fonts.example.com/css?family=X",
                  "https://mehrzeilig.example.com/o.js"},
      str(sorted(p_funde)))
check("ein <a href> zaehlt NICHT als Einbindung (sonst Dauer-Fehlalarm)",
      "https://example.com/doku" not in p_funde)
check("ein lokaler Pfad und eine data:-URI zaehlen nicht",
      not any("lokal" in u or "w3.org" in u for u in p_funde), str(sorted(p_funde)))
check("ein mehrzeiliges <script>-Tag wird erfasst",
      "https://mehrzeilig.example.com/o.js" in p_funde)

# Die Ausnahme-Marke muss WIRKEN - sonst ist sie eine Zeile ohne Funktion, und
# die beiden Office-Add-ins unten waeren dauerhaft rot.
_PROBE_M = ('<!-- jarvis-extern-erlaubt: Testgrund -->\n'
            '<script src="https://cdn.example.com/lib.js"></script>\n')
check("die Marke jarvis-extern-erlaubt nimmt eine Einbindung heraus",
      funde_in(_PROBE_M, "probe.html") == [], str(funde_in(_PROBE_M, "probe.html")))
_PROBE_O = '<script src="https://cdn.example.com/lib.js"></script>\n'
check("und OHNE Marke bleibt dieselbe Zeile ein Befund (Marke ist nicht trivial)",
      len(funde_in(_PROBE_O, "probe.html")) == 1)

# Der Regelfall im Haus: die Begruendung steht OBEN in einem langen Kommentar.
# Eine erste Fassung mit Zwei-Zeilen-Fenster hat genau das nicht erfasst.
_PROBE_L = ('<!--\n    Irgendeine lange Begruendung,\n    die mehrere Zeilen\n'
            '    braucht.\n\n    jarvis-extern-erlaubt: Testgrund\n'
            '    und danach noch zwei\n    Zeilen Text.\n-->\n'
            '<script src="https://cdn.example.com/lib.js"></script>\n')
check("die Marke wirkt auch aus einem MEHRZEILIGEN Kommentar darueber",
      funde_in(_PROBE_L, "probe.html") == [], str(funde_in(_PROBE_L, "probe.html")))

# ⚠ UND SIE DARF NICHT AUS EINEM FREMDEN BLOCK HEREINWIRKEN - sonst befreit
# eine Begruendung weiter oben stillschweigend eine ganz andere Einbindung.
_PROBE_F = ('<!-- jarvis-extern-erlaubt: gilt nur fuer das Skript darunter -->\n'
            '<script src="https://a.example.com/eins.js"></script>\n'
            '<p>Dazwischen etwas, das kein Kommentar ist.</p>\n'
            '<script src="https://b.example.com/zwei.js"></script>\n')
f_funde = {u for _, u in funde_in(_PROBE_F, "probe.html")}
check("eine Marke befreit NICHT die naechste Einbindung dahinter",
      f_funde == {"https://b.example.com/zwei.js"}, str(sorted(f_funde)))

# ⚠ EIN KAPUTTES MESSWERKZEUG IST "KONNTE NICHT LAUFEN", NICHT "BEISST".
# Faellt eine der Kontrollen oben durch, sagt Abschnitt 2 nichts mehr aus - ein
# blindes Muster meldete dann 0 Befunde und saehe wie Entwarnung aus, ein zu
# breites ueberschwemmte die Bilanz. Beides gehoert nach Exit 2, damit es von
# einem echten Befund (Exit 1) unterscheidbar bleibt. Von einer Gegenprobe
# erzwungen: mit blindem `_ATTR` meldete der Waechter vorher Exit 1.
if res.count(False):
    abbruch(f"{res.count(False)} Positivkontrolle(n) durchgefallen - das "
            "Messwerkzeug selbst ist defekt, Abschnitt 2 ist damit wertlos")

# ── Die Regel ───────────────────────────────────────────────────────────────
print("\n\033[1m2. Keine externe Einbindung in " + ", ".join(WURZELN) + "\033[0m")

alle = []
for p in dateien:
    with open(p, encoding="utf-8", errors="replace") as fh:
        txt = fh.read()
    rel = os.path.relpath(p, ROOT)
    for nr, url in funde_in(txt, os.path.basename(p)):
        alle.append((rel, nr, url))

for rel, nr, url in alle:
    check(f"{rel}:{nr} bindet nichts Externes ein", False,
          f"{url} – lokal nach frontend/js/vendor/ legen (HERKUNFT.txt pflegen) "
          f"oder mit '{_MARKE}: <grund>' begruenden")
if not alle:
    check(f"keine externe Einbindung in {len(dateien)} Dateien", True)

schlecht = res.count(False)
print(f"\n\033[1mErgebnis: {len(res) - schlecht}/{len(res)}\033[0m")
sys.exit(1 if schlecht else 0)
