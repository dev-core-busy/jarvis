"""Jede Datei unter `frontend/js/` ist in mindestens EINER HTML-Seite eingebunden.

DER FEHLER, DEN DAS VERHINDERT: `86c7b718` (2026-07-21) nahm beim Umzug ins
/wissen-Portal die `<script>`-Tags von `kbmatrix.js` UND `extractor.js` aus
`settings.html`. `kbmatrix.js` zog nach `wissen.html` um, `extractor.js` nicht –
und blieb als 1381-Zeilen-Datei im Repo liegen, in KEINER Seite eingebunden.

⚠ ES WAR 2,5 MONATE UNSICHTBAR, UND ZWAR AUS EINEM GRUND, DEN KEIN
VORKOMMENS-TEST ERREICHT: `init()` kehrt ohne seinen Container sofort zurueck.
Kein Markup, keine Listener, keine Requests, **keine Fehlermeldung** – und
`app.js` fragt mit `if (window.extractorManager)` ab, es gibt also nicht einmal
eine Konsolenzeile. Danach wurde die Datei noch zweimal gepflegt (`b9f81320`
ausdruecklich als „tote Zweitimplementierung", `d40491a8` im pauschalen
Icon-Sweep ueber ~50 Dateien, inklusive eines sorgfaeltigen Kommentars ueber die
Symbolwahl – in totem Code).

DER PREIS STAND WOANDERS: `kbmatrix.js` behielt einen Vorrang-Zweig auf
`window.extractorManager._openReview`, der damit von Anfang an unerreichbar war.
Die Spalte „Bearb." versprach seither Bearbeiten und oeffnete eine Leseansicht.
Gemeldet wurde das erst am 2026-10-03 – ein Vierteljahr spaeter.

⚠ KEINE GEPFLEGTE LISTE. Der Waechter sucht beide Seiten selbst (jede Datei in
`frontend/js/`, jede HTML-Seite im Repo) – eine Liste waere an dem Tag
unvollstaendig, an dem jemand ein Modul hinzufuegt, und die fehlende Zeile
meldet sich nicht. Genau das ist der Unterschied zur Merkregel im Register
(„ein `grep` ueber die Script-Tags ist billiger als der naechste Sweep"): ein
grep muss jemand ausfuehren, eine Regel beisst von selbst.

⚠ GEMESSEN WIRD DIE EINBINDUNG, NICHT DIE BENUTZUNG. Ein Modul kann eingebunden
und trotzdem nutzlos sein (fehlender Container) – das kann dieser Waechter nicht
sehen und behauptet es auch nicht. Er beantwortet genau die eine Frage, die
`86c7b718` offen gelassen hat: liefert der Server diese Datei ueberhaupt an
irgendeinen Browser aus?

⚠ GELTUNGSBEREICH: `frontend/js/*.js`, NICHT rekursiv. `frontend/js/vendor/` bleibt
ausdruecklich draussen – diese Dateien werden zur Laufzeit nachgeladen (z.B.
`mermaid_blocks.js:35` holt `vendor/mermaid.min.js`), stehen also zu Recht in
keinem `<script>`-Tag. Ein unbenutztes Vendor-Paket faellt damit NICHT auf; das
ist der bewusste Preis dafuer, dass der Waechter keine Fehlalarme produziert.

Gemessen beim Anlegen: 80 Dateien in `frontend/js/`, 79 davon eingebunden –
`websocket.js` als einzige nicht (seit `9d2a2a8b`, dem Initial Release, nie
angefasst). Seine einzige Erwaehnung stand in der Vorladeliste des
Service Workers `frontend/sw.js` – der war selbst toter Bestand (von nichts
registriert, `chat.js` meldet jede Registrierung aktiv ab) und ist am
2026-10-05 mitsamt seiner Route `/sw.js` entfernt worden.

Lauf:  python3 tests/test_js_einbindung.py
"""
import glob
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
JS_DIR = os.path.join(ROOT, "frontend", "js")

# Nur das src-Attribut eines <script>-Tags zaehlt. Ein Dateiname im Kommentar,
# in einer Zeichenkette oder in einem <link> ist KEINE Einbindung - genau diese
# Verwechslung macht einen Waechter zahnlos (Register: ein Vorkommen ist keine
# Aussage ueber die Wirkung).
_SCRIPT = re.compile(r'<script\b[^>]*\bsrc\s*=\s*["\']([^"\']+)["\']', re.I)

# Verzeichnisse, die nicht zum Auslieferungsstand gehoeren. `.claude` traegt die
# Arbeitsbaeume der Worktrees - ohne diesen Ausschluss liest der Waechter in
# einem Worktree die Seiten ALLER Zweige mit und haelt eine dort eingebundene
# Datei fuer eingebunden.
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


def kurz(liste, zeige=6):
    """Eine Fundliste lesbar halten - 80 Dateinamen in einer Zeile liest
    niemand, und die Zahl ist die eigentliche Aussage."""
    if not liste:
        return ""
    rest = len(liste) - zeige
    return (f"{len(liste)} Stueck: " + ", ".join(sorted(liste)[:zeige])
            + (f", … ({rest} weitere)" if rest > 0 else ""))


def seiten_finden():
    gefunden = []
    for pfad in glob.glob(os.path.join(ROOT, "**", "*.html"), recursive=True):
        rel = os.path.relpath(pfad, ROOT)
        if any(teil in _AUS for teil in rel.split(os.sep)):
            continue
        gefunden.append(pfad)
    return sorted(gefunden)


def eingebundene_namen(seiten):
    """Die Basisnamen aller per <script src> eingebundenen Dateien.

    Der Stand (`?v=N`) wird abgeschnitten - ob er stimmt, prueft
    test_cache_buster.py; hier geht es nur um das OB.
    """
    namen = set()
    for pfad in seiten:
        with open(pfad, encoding="utf-8", errors="replace") as fh:
            txt = fh.read()
        for m in _SCRIPT.finditer(txt):
            src = m.group(1).split("?")[0].split("#")[0]
            namen.add(os.path.basename(src))
    return namen


def ist_eingebunden(datei, srcs):
    """Ein Modul gilt als eingebunden, wenn sein Basisname in einem src steht.

    Die Seiten benutzen ZWEI Schreibweisen fuer dieselbe Datei
    (`js/app.js?v=216` und `/static/js/app.js?v=216`) - ein Vergleich auf den
    ganzen Pfad wuerde die eine Haelfte uebersehen.
    """
    return datei in srcs


# ── Grundlage ───────────────────────────────────────────────────────────────
if not os.path.isdir(JS_DIR):
    abbruch(f"{os.path.relpath(JS_DIR, ROOT)} gibt es nicht")

module = sorted(os.path.basename(p) for p in glob.glob(os.path.join(JS_DIR, "*.js")))
seiten = seiten_finden()

print("\n\033[1m1. Grundlage und Positivkontrollen\033[0m")

# Ohne Fundstellen misst dieser Waechter nichts - das ist kein "bestanden".
if len(module) < 20:
    abbruch(f"nur {len(module)} Module in frontend/js/ gefunden (erwartet: Dutzende)")
if len(seiten) < 10:
    abbruch(f"nur {len(seiten)} HTML-Seiten gefunden (erwartet: Dutzende)")

check(f"{len(module)} Module in frontend/js/ gelesen", True)
check(f"{len(seiten)} HTML-Seiten gelesen", True)

srcs = eingebundene_namen(seiten)
check(f"{len(srcs)} verschiedene Skript-Einbindungen gefunden", len(srcs) >= 20, str(len(srcs)))

# ⚠ DIE WICHTIGSTE KONTROLLE: der Vergleich darf nicht trivial WAHR sein.
# Ein Matcher, der alles fuer eingebunden haelt (z.B. nach einem Umbau auf
# "Name kommt irgendwo in der Datei vor"), waere dauerhaft gruen und damit
# schlimmer als kein Waechter.
erfunden = "zzz_dieses_modul_gibt_es_nicht.js"
check("eine erfundene Datei gilt NICHT als eingebunden (Matcher ist nicht trivial wahr)",
      not ist_eingebunden(erfunden, srcs), erfunden)

# ⚠ UND DAS MESSWERKZEUG SELBST GEGEN EINEN BEKANNTEN FALL. Ein zu breites
# Muster (z.B. "irgendein <name>.js im Quelltext") haelt eine Datei fuer
# eingebunden, die nur ERWAEHNT wird - im Kommentar, in einer Zeichenkette, in
# einem <link>. Der Waechter waere dann dauerhaft gruen und damit schlimmer als
# keiner; die Pruefung mit dem erfundenen Namen darueber kann das NICHT sehen,
# weil ein erfundener Name nirgends vorkommt. Gefunden von einer Gegenprobe.
_PROBE = (
    '<link rel="stylesheet" href="/static/css/nur_ein_link.js">\n'
    '<!-- nur_im_kommentar.js -->\n'
    '<script>var p = "nur_in_zeichenkette.js";</script>\n'
    '<script src="/static/js/echt_eingebunden.js?v=7"></script>\n'
)
probe_funde = {os.path.basename(m.group(1).split("?")[0])
               for m in _SCRIPT.finditer(_PROBE)}
check("das Muster findet die ECHTE Einbindung einer Probeseite",
      "echt_eingebunden.js" in probe_funde, str(sorted(probe_funde)))
check("und NUR sie - Kommentar, Zeichenkette und <link> zaehlen nicht",
      probe_funde == {"echt_eingebunden.js"}, str(sorted(probe_funde)))

# Gegenrichtung: der Matcher muss ueberhaupt etwas finden. Ohne diese Kontrolle
# waere ein Matcher, der NIE trifft, von echtem Befund nicht zu unterscheiden -
# er meldete dann 80 FAIL und sah nach einem Grossbefund aus.
treffer = [m for m in module if ist_eingebunden(m, srcs)]
check(f"{len(treffer)} Module werden als eingebunden erkannt",
      len(treffer) >= len(module) // 2, f"{len(treffer)} von {len(module)}")
if len(treffer) < len(module) // 2:
    abbruch(f"nur {len(treffer)} von {len(module)} Modulen gelten als eingebunden - "
            "das ist eher ein kaputter Matcher als echter Rueckstand")

# ── Die Regel ───────────────────────────────────────────────────────────────
print("\n\033[1m2. Jedes Modul ist in mindestens einer Seite eingebunden\033[0m")

fehlend = [m for m in module if not ist_eingebunden(m, srcs)]
for m in fehlend:
    check(f"{m} ist eingebunden", False,
          "in KEINER HTML-Seite - entweder nachtragen (mit ?v=N) oder entfernen")
if not fehlend:
    check(f"alle {len(module)} Module sind eingebunden", True)

schlecht = res.count(False)
print(f"\n\033[1mErgebnis: {len(res) - schlecht}/{len(res)}\033[0m")
if fehlend:
    print("  " + kurz(fehlend))
sys.exit(1 if schlecht else 0)
