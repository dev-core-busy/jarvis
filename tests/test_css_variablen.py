#!/usr/bin/env python3
"""Jede ``var(--x)``-Referenz muss eine definierte Variable treffen (2026-08-20).

DIE REGEL, die dieser Test durchsetzt:

    Steht irgendwo ``var(--x)`` OHNE Rueckfallwert, dann muss ``--x`` in einer
    der Frontend-CSS-Dateien (oder per ``setProperty``/Inline-Style) auch
    wirklich DEKLARIERT sein.

WARUM DAS TEUER IST: CSS meldet einen Tippfehler nicht. Eine unbekannte
Variable macht die GANZE Deklaration ungueltig – bei einem Shorthand wie
``border: 1px solid var(--border-color)`` faellt damit nicht nur die Farbe aus,
sondern der Rahmen komplett. Nichts bricht sichtbar, es fehlt nur etwas, und
niemand bringt das mit einem Namen in Verbindung.

Gefunden am 2026-08-20 an ``.kb-hdr-btn``: der Knopf hatte projektweit keinen
Rahmen und sah aus wie Fliesstext. Die Spur fuehrte zu NEUN nie definierten
Variablen mit zusammen 58 Fundstellen – ``--border-color`` (27x) war nur die
auffaelligste:

    --border-color   -> --border          27x  style.css
    --bg-input       ->  neu in theme.css  7x  style.css
    --accent-color   -> --accent           3x  style.css
    --accent-primary -> --accent           3x  style.css
    --border-focus   -> --accent           2x  style.css  (Fokus = Akzent)
    --radius         -> --radius-md        2x  style.css
    --text-main      -> --text-primary     2x  style.css
    --bg-card        -> --bg-secondary     1x  style.css
    --text           -> --text-primary     2x  chat.css
    --border-color   -> --border           9x  cron.js / knowledge.js (inline)

RUECKFALL IST ZULAESSIG: ``var(--x, wert)`` ist ausdruecklich in Ordnung – da
ist die Abwesenheit eingeplant. Geprueft wird nur die Form ohne Rueckfall.

MIT AUFGERAEUMT (2026-08-20): ``frontend/style.css`` war eine tote Zweitfassung
von ``frontend/css/style.css`` – 63 KB, von keiner Seite geladen, 352 der 359
Selektoren Dubletten, die uebrigen sieben (``.speed-*``) nirgends benutzt. Sie
trug dieselben toten Namen. Geloescht; eine Pruefung unten haelt fest, dass sie
nicht unbemerkt zurueckkehrt.

DEFINITIONEN werden aus ALLEN Frontend-CSS-Dateien gesammelt, nicht nur aus
``:root``/``body``: eine Komponente darf eine Variable auf ihrem eigenen
Container deklarieren, und ein Tippfehler ist trotzdem nirgends definiert.
Dazu ``setProperty('--x', …)`` aus dem JS (branding.js setzt die Markenfarbe
so) und ``style="--x: …"`` aus dem Markup – sonst meldet der Waechter Variablen
als fehlend, die zur Laufzeit sehr wohl gesetzt werden.

    python3 tests/test_css_variablen.py
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FE = ROOT / "frontend"
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}" + (f" – {detail}" if detail else ""))


def entkommentieren(text: str) -> str:
    """/* … */ durch Leerzeichen ersetzen, ZEILENUMBRUECHE ERHALTEN.

    Der Erhalt ist kein Schoenheitsfehler: ohne ihn verschieben sich alle
    Zeilennummern hinter dem ersten mehrzeiligen Kommentar, und die Meldung
    schickt den Leser an die falsche Stelle.
    """
    return re.sub(r"/\*.*?\*/", lambda m: re.sub(r"[^\n]", " ", m.group(0)), text, flags=re.S)


# ── Was geprueft wird ───────────────────────────────────────────────────────
# Die drei CSS-Dateien, die JEDE Seite (bzw. settings/wissen) laedt, plus alles,
# was Markup mit Inline-Styles erzeugt. Die JS-Dateien gehoeren dazu, weil genau
# dort neun der gefundenen Fundstellen lagen (cron.js, knowledge.js).
CSS_DATEIEN = [FE / "css" / n for n in ("style.css", "theme.css", "chat.css")]

# frontend/style.css war eine tote Zweitfassung von css/style.css (63 KB, von
# keiner Seite geladen, 352 der 359 Selektoren Dubletten) und ist am 2026-08-20
# geloescht worden. Der Name bleibt als Ausnahme stehen, damit der Waechter auch
# auf einem Stand laeuft, auf dem die Datei noch existiert – und die Pruefung
# ganz unten sorgt dafuer, dass sie nicht unbemerkt wiederkehrt.
ALTBESTAND = FE / "style.css"


def ist_fremd(p: Path) -> bool:
    """Fremdcode (mermaid, Chart.js-Plugins, clippy, jQuery) gehoert uns nicht.

    mermaid.min.js referenziert ``var(--mermaid-font-family)`` und setzt die
    Variable zur Laufzeit in seinem eigenen eingespritzten CSS – fuer uns nicht
    sichtbar. Ein Waechter, der Fremdcode beanstandet, wird abgeschaltet.
    """
    return "vendor" in p.parts

for p in CSS_DATEIEN:
    check(p.is_file(), "gepruefte Datei vorhanden: %s" % p.name)

# ── Definitionen einsammeln ────────────────────────────────────────────────
definiert: dict[str, str] = {}
for p in sorted(FE.rglob("*.css")):
    if p == ALTBESTAND:
        continue
    for m in re.finditer(r"(--[A-Za-z0-9_-]+)\s*:", entkommentieren(p.read_text(encoding="utf-8"))):
        definiert.setdefault(m.group(1), p.name)
for p in sorted(list(FE.rglob("*.js")) + list(FE.rglob("*.html"))):
    t = p.read_text(encoding="utf-8", errors="replace")
    for m in re.finditer(r"""setProperty\(\s*['"](--[A-Za-z0-9_-]+)['"]""", t):
        definiert.setdefault(m.group(1), p.name)
    for m in re.finditer(r"""style\s*=\s*["'][^"']*?(--[A-Za-z0-9_-]+)\s*:""", t):
        definiert.setdefault(m.group(1), p.name)
    # <style>-Bloecke im Markup zaehlen genauso. Ohne sie meldete der Waechter
    # support-api.html falsch: --bg-body steht dort in einem <style>, nicht in
    # einer .css-Datei (beim ersten Lauf genau so passiert).
    for block in re.findall(r"<style[^>]*>(.*?)</style>", t, flags=re.S | re.I):
        for m in re.finditer(r"(--[A-Za-z0-9_-]+)\s*:", entkommentieren(block)):
            definiert.setdefault(m.group(1), p.name)

print("\n%d Variablen definiert." % len(definiert))
check(len(definiert) >= 40, "Definitionen wirklich eingelesen (%d)" % len(definiert))
# Gegenprobe: waeren die Definitionen aus dem falschen Ordner gelesen, faende der
# Waechter nichts und WAERE TROTZDEM GRUEN. Diese vier muessen dabei sein.
for name in ("--border", "--accent", "--text-primary", "--bg-secondary"):
    check(name in definiert, "Grundvariable gefunden: %s" % name)


def fehlende_referenzen(text: str):
    """(Name, Zeile) fuer jede var(--x)-Referenz OHNE Rueckfall auf ein Unbekanntes."""
    roh = entkommentieren(text)
    treffer = []
    for m in re.finditer(r"var\(\s*(--[A-Za-z0-9_-]+)\s*([,)])", roh):
        if m.group(2) == ",":       # hat Rueckfall -> ausdruecklich zulaessig
            continue
        if m.group(1) not in definiert:
            treffer.append((m.group(1), roh[:m.start()].count("\n") + 1))
    return treffer


# ── Die eigentliche Regel ──────────────────────────────────────────────────
gesamt = 0
for p in CSS_DATEIEN + sorted(list(FE.rglob("*.js")) + list(FE.rglob("*.html"))):
    if p == ALTBESTAND or ist_fremd(p):
        continue
    fehlt = fehlende_referenzen(p.read_text(encoding="utf-8", errors="replace"))
    gesamt += len(fehlt)
    rel = p.relative_to(FE)
    check(not fehlt, "%s: alle var(--x) treffen eine definierte Variable" % rel,
          "; ".join("%s (Zeile %d)" % (n, z) for n, z in fehlt[:8]))

check(gesamt == 0, "keine einzige unbekannte Variable im Frontend (%d gefunden)" % gesamt)

# ── Der Waechter muss auch wirklich anschlagen ─────────────────────────────
# Ohne diese Probe waere ein Test, der aus Versehen nichts einliest, gruen.
check(fehlende_referenzen("a{border:1px solid var(--gibt-es-nicht)}") ==
      [("--gibt-es-nicht", 1)], "Waechter erkennt eine unbekannte Variable")
check(fehlende_referenzen("a{color:var(--gibt-es-nicht, #f00)}") == [],
      "Rueckfall var(--x, wert) gilt NICHT als Fehler")
check(fehlende_referenzen("a{color:var(--auch-nicht, var(--immer-noch-nicht))}") ==
      [("--immer-noch-nicht", 1)], "verschachtelter Rueckfall wird mitgeprueft")
check(fehlende_referenzen("/* var(--nur-im-kommentar) */\na{color:var(--border)}") == [],
      "Kommentare zaehlen nicht als Referenz")
_z = fehlende_referenzen("/* mehrzeilig\n\n\n*/\na{color:var(--nicht-da)}")
check(_z == [("--nicht-da", 5)], "Zeilennummer bleibt nach Kommentar korrekt", str(_z))

# ── Die tote Zweitfassung darf nicht zurueckkehren ─────────────────────────
# Sie ist geloescht. Existiert sie wieder, ist das entweder ein versehentliches
# Wiedereinspielen oder eine bewusste Entscheidung – in beiden Faellen soll es
# jemand SEHEN, statt dass eine ungepruefte Dublette still mitlaeuft.
check(not ALTBESTAND.exists(),
      "frontend/style.css ist geloescht (tote Dublette von css/style.css)",
      "Datei ist wieder da – entweder entfernen oder hier bewusst freigeben")

# Und sie darf erst recht nicht eingebunden werden.
verweise = []
for p in sorted(FE.rglob("*.html")):
    for m in re.finditer(r"""(?:href|src)\s*=\s*["']([^"']+)["']""", p.read_text(encoding="utf-8")):
        pfad = m.group(1).split("?")[0]
        if pfad.endswith("/style.css") and "/css/" not in pfad:
            verweise.append("%s -> %s" % (p.name, pfad))
check(not verweise, "keine Seite bindet frontend/style.css ein",
      "; ".join(verweise) + " – die Datei ist geloescht, der Verweis laeuft ins Leere")


# ── Zweite Regel: aus --fg-rgb/--shadow-rgb abgeleitete Variablen ──────────
# Beim Beheben des --border-color-Fehlers selbst hineingelaufen (2026-08-20):
# --bg-input: rgba(var(--fg-rgb), 0.06) allein in :root deklariert blieb im
# Hell-Theme bei rgba(255,255,255,.06) – im Browser gemessen. Grund ist wieder,
# dass eine Custom Property auf dem Element BERECHNET wird, auf dem sie steht:
# :root ist <html>, --fg-rgb kippt aber erst auf body.light.
# --border macht es seit jeher richtig (in beiden Bloecken); --shadow-sm/md/lg
# machten denselben Fehler und lieferten in Hell reines Schwarz.
THEME = entkommentieren((FE / "css" / "theme.css").read_text(encoding="utf-8"))


def theme_block(sel: str) -> str:
    m = re.search(re.escape(sel) + r"\s*\{(.*?)\n\}", THEME, re.S)
    return m.group(1) if m else ""


_root, _light = theme_block(":root"), theme_block("body.light")
check(bool(_root) and bool(_light), "theme.css: :root- und body.light-Block gefunden")
abgeleitet = sorted({m.group(1) for m in
                     re.finditer(r"(--[\w-]+)\s*:\s*[^;]*var\(--(?:fg|shadow)-rgb\)", _root)})
check(len(abgeleitet) >= 4, "abgeleitete Variablen gefunden (%d)" % len(abgeleitet),
      str(abgeleitet))
for name in abgeleitet:
    # Geprueft wird nur, DASS neu deklariert wird – nicht, dass dieselbe Formel
    # dasteht: --border traegt in Hell bewusst 0.12 statt 0.08. Eine
    # Gleichheitspruefung waere hier falsch und wuerde echtes Theming melden.
    check(re.search(re.escape(name) + r"\s*:", _light) is not None,
          "theme.css: %s wird in body.light neu berechnet" % name,
          "steht nur in :root -> friert auf dem Dunkel-Wert ein")

print(f"\n{'=' * 62}")
print(f"  {_ok} OK, {_fail} FAIL")
print(f"{'=' * 62}")
sys.exit(1 if _fail else 0)
