#!/usr/bin/env python3
"""Waechter: die Umbruch-Regel in theme.css erfasst JEDE Titelleiste.

Die Regel (2026-09-22) zaehlt fuenf Leisten-Familien auf, weil es keine
gemeinsame Quelle gibt – zwoelf Seiten definieren ihre Leiste inline. Eine
Aufzaehlung ist eine gepflegte Liste und damit an dem Tag unvollstaendig, an
dem jemand eine Seite mit eigener Klasse ergaenzt (Register).

DESHALB WIRD SIE NICHT GEPFLEGT, SONDERN ABGELEITET: die Klassen werden aus dem
MARKUP ermittelt – Symbolgruppe = Elternteil des Theme-Umschalters, Leiste =
deren Elternteil – und gegen die Regel gehalten. Kommt morgen eine Seite dazu,
meldet dieser Waechter sie, ohne dass jemand hier etwas eintraegt.

Die WIRKUNG (laeuft wirklich nichts ueber?) misst `live_topbar_umbruch_dev.py`
im echten Chrome – ein Blick ins CSS kann das grundsaetzlich nicht beantworten.
"""
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
HTML = WURZEL / "frontend"
CSS = WURZEL / "frontend" / "css" / "theme.css"

# Fenster, die IN Office laufen – sie haben keine Jarvis-Titelleiste und sollen
# auch keine bekommen (eine Navigation dorthin waere dort ein Fehler).
AUSNAHMEN = {"addin/taskpane.html", "excel-addin/taskpane.html"}

# ⚠ EIN DIALOGKOPF IST KEINE TITELLEISTE – einzeln eingetragen und begruendet,
# keine Sammelfreigabe. `.modal-header` ist der Kopf von Dialogen (Kennwort
# aendern, Zertifikat-Hilfe, Einstellungen); der Anker greift dort, seit der
# Einstellungs-Dialog mit dem Suchfeld (2026-09-20) ein Haus-Symbol traegt.
# Er hat eigene Maasse (`.modal-content` mit `max-width`), und die Eindaemmung
# darin ist an derselben Stelle schon geloest: das Trefferpanel des Suchfelds
# misst seit dem Tag gegen die KOPFbreite (`max-width: calc(100% - 4rem)`),
# nachdem es bei 520 px 115 px links aus dem Dialog ragte.
# ⚠ NICHT GEMESSEN: ob der Kopf selbst ueberlaeuft. Der Dialog liess sich im
# Messaufbau nicht oeffnen (`_openSettingsModal` griff ueber CDP nicht), und
# ohne Ueberlauf waere die Regel dort eine Zeile ohne Wirkung. Wer es misst und
# einen Ueberlauf findet, nimmt `.modal-header` in die Regel auf und diesen
# Eintrag heraus.
LEISTEN_AUSNAHMEN = {"modal-header"}

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}

_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  \033[32m✓\033[0m %s" % text)
    else:
        _fail += 1
        print("  \033[31m✗\033[0m %s%s" % (text, ("  [%s]" % info) if info else ""))


# ⚠ DER ANKER IST DAS HAUS- BZW. ABMELDE-SYMBOL, NICHT DER THEME-KNOPF.
# Erster Anlauf ankerte am Theme-Umschalter und nahm den ERSTEN Fund – der steht
# aber auch im Login-Schirm von /chat und im Einstellungs-Dialog: drei
# Fehlalarme, und "der erste ist keine Identitaet" (Register). Haus und Abmelden
# stehen ausschliesslich in einer Titelleiste; gemessen: `nav.home` auf 16
# Seiten (nicht auf /portal – das verlinkt nicht auf sich selbst), die
# Abmelde-Knoepfe tragen `chat.logout` bzw. `nav.logout`.
ANKER = {"nav.home", "chat.logout", "nav.logout", "portal.logout"}


class Leisten(HTMLParser):
    """Findet Symbolgruppe und Leiste ueber die ELTERNKETTE des Ankers.

    Ein Suchmuster auf Klassennamen (`*-icons`) waere wieder eine gepflegte
    Liste – die Elternkette ist die Eigenschaft."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stapel = []
        self.funde = []          # (Gruppen-Klassen, Leisten-Klassen)

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        kl = (d.get("class") or "").split()
        if tag not in VOID:
            self.stapel.append(kl)
        if d.get("data-i18n-title") in ANKER and len(self.stapel) >= 3:
            # stapel[-1] ist das Element selbst (falls kein void)
            tiefe = len(self.stapel) - (0 if tag in VOID else 1)
            gruppe = self.stapel[tiefe - 1] if tiefe >= 1 else []
            leiste = self.stapel[tiefe - 2] if tiefe >= 2 else []
            self.funde.append((gruppe, leiste))

    def handle_endtag(self, tag):
        if tag not in VOID and self.stapel:
            self.stapel.pop()


def regel_klassen(css: str, muster: str) -> set:
    """Die Klassen EINER Regel in theme.css – ueber die Deklaration gefunden,
    nicht ueber eine Zeilennummer."""
    aus = set()
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        if muster in m.group(2).replace(" ", ""):
            for teil in m.group(1).split(","):
                for kl in re.findall(r"\.([A-Za-z0-9_-]+)", teil):
                    aus.add(kl)
    return aus


print("\033[1m1. Die Regel steht in theme.css\033[0m")
css = CSS.read_text(encoding="utf-8")
WRAP = regel_klassen(css, "flex-wrap:wrap")
MINW = regel_klassen(css, "min-width:0")
check("es gibt eine flex-wrap-Regel mit Leisten-Klassen", bool(WRAP), "keine")
# ⚠ `bool(MINW)` WAR ZAHNLOS: theme.css hat weitere `min-width: 0`-Regeln
# (Suchpanel, Flex-Kinder anderswo) – die Gegenprobe "Titel-Regel raus" blieb
# damit gruen. Gemessen wird die EIGENSCHAFT: die Titel-Klassen der gefundenen
# Leisten muessen darin stehen.
check("es gibt eine min-width:0-Regel FUER DIE TITEL",
      bool(MINW & {"topbar-title", "wi-title", "pt-title"}),
      "gefunden: %s" % sorted(MINW)[:6])

print("\n\033[1m2. Jede Titelleiste im Markup ist erfasst\033[0m")
seiten, offen = [], []
for p in sorted(HTML.rglob("*.html")):
    rel = str(p.relative_to(HTML))
    if rel in AUSNAHMEN:
        continue
    p_ = Leisten()
    try:
        p_.feed(p.read_text(encoding="utf-8"))
    except Exception as e:                                         # noqa: BLE001
        offen.append("%s: Parser (%s)" % (rel, e))
        continue
    if not p_.funde:
        continue
    seiten.append(rel)
    gesehen = set()
    for gruppe, leiste in p_.funde:
        schluessel = (tuple(gruppe), tuple(leiste))
        if schluessel in gesehen:
            continue
        gesehen.add(schluessel)
        if set(leiste) & LEISTEN_AUSNAHMEN:
            continue
        if leiste and not (set(leiste) & WRAP):
            offen.append("%s: Leiste .%s nicht in der flex-wrap-Regel"
                         % (rel, ".".join(leiste)))
        if gruppe and not (set(gruppe) & WRAP):
            offen.append("%s: Symbolgruppe .%s bricht selbst nicht um"
                         % (rel, ".".join(gruppe)))

# Ohne Fundmenge waere die Pruefung ueber einer leeren Menge trivial wahr.
check("PK: es wurden ueberhaupt Titelleisten gefunden", len(seiten) >= 10,
      "%d: %s" % (len(seiten), ", ".join(seiten)))
check("⚠ JEDE gefundene Titelleiste ist von der Regel erfasst", not offen,
      "; ".join(offen))

print("\n\033[1m3. Der Live-Waechter, der die WIRKUNG misst, existiert\033[0m")
lw = WURZEL / "tests" / "live_topbar_umbruch_dev.py"
check("live_topbar_umbruch_dev.py liegt bereit", lw.is_file(), "fehlt")
if lw.is_file():
    q = lw.read_text(encoding="utf-8")
    check("er misst den Ueberlauf bei schmalem Fenster",
          "scrollWidth" in q and "520" in q, "misst etwas anderes")
    # ⚠ `"BREIT" in q` WAR ZAHNLOS: eine Sabotage auf `BREIT = 0` laesst den
    # Namen stehen. Gemessen wird der WERT der Zuweisung.
    _br = re.search(r"^BREIT\s*=\s*(\d+)", q, re.M)
    check("und hat eine Referenzbreite, bei der sich nichts aendern darf",
          bool(_br) and int(_br.group(1)) >= 1000,
          "BREIT = %s" % (_br.group(1) if _br else "fehlt"))

print("\n\033[1mErgebnis: %d/%d\033[0m" % (_ok, _ok + _fail))
sys.exit(0 if _fail == 0 else 1)
