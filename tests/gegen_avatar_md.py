#!/usr/bin/env python3
"""Gegenproben zum Avatar-Markdown: beisst der Waechter WIRKLICH?

Jede Probe dreht GENAU EINE Zusage zurueck und verlangt, dass
`tests/test_avatar_md.js` das meldet. Eine Probe, die nicht beisst, ist ein
Testmangel - kein Beweis.

⚠ GEMESSEN WIRD AM EXIT-CODE **UND** AN DER BILANZZEILE: ein Lauf, der ohne
Bilanz abbricht, ist von "nicht gelaufen" nicht zu unterscheiden und zaehlt
NICHT als Treffer.
"""
import atexit, os, re, shutil, signal, subprocess, sys, tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_avatar_md.js"

# ⚠ JEDE Datei, die eine Probe anfasst, MUSS hier stehen - sonst bleibt eine
# Sabotage liegen und der naechste Lauf meldet einen Fehler, den es nicht gibt.
DATEIEN = [
    ROOT / "frontend" / "js" / "avatar.js",
    ROOT / "frontend" / "css" / "avatar.css",
    ROOT / "tests" / "test_avatar_md.js",
    ROOT / "frontend" / "chat.html",
]
ABLAGE = Path(tempfile.gettempdir()) / ("avatar-md-sicherung-%d" % os.getuid())
MARKE = ABLAGE / ".laeuft"


def _ablage(d):
    """Schluessel ist der RELATIVE PFAD, nicht der Basisname.

    ⚠ Mit `d.name` wuerden zwei gleichnamige Dateien (etwa `frontend/js/chat.js`
    neben einem gleichnamigen Modul) einander still ueberschreiben - und
    `zurueck()` spielte fremden Inhalt in die falsche Datei zurueck, ohne dass
    etwas meldet.
    """
    return ABLAGE / str(d.relative_to(ROOT)).replace("/", "_")


def sichern():
    ABLAGE.mkdir(parents=True, exist_ok=True)
    for d in DATEIEN:
        shutil.copy2(d, _ablage(d))


def zurueck():
    for d in DATEIEN:
        q = _ablage(d)
        if q.exists():
            shutil.copy2(q, d)


def lauf():
    p = subprocess.run(["node", str(WAECHTER)], capture_output=True, text=True, cwd=str(ROOT))
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", p.stdout)
    if not m:
        return None, p.stdout[-400:]
    return int(m.group(2)), ""


def probe(name, datei, alt, neu, anzahl=1):
    d = ROOT / datei
    s = d.read_text(encoding="utf-8")
    assert s.count(alt) == anzahl, "Anker trifft %dx statt %dx: %s" % (s.count(alt), anzahl, name)
    d.write_text(s.replace(alt, neu), encoding="utf-8")
    fails, grund = lauf()
    zurueck()
    if fails is None:
        print("  ⚠ %-52s OHNE BILANZ (%s)" % (name, grund.strip()[:60]))
        return False
    print("  %s %-52s %d FAIL" % ("✓" if fails else "✗", name, fails))
    return fails > 0


# --- Rueckstand eines abgeschossenen Laufs zuruecknehmen -------------------
if MARKE.exists():
    print("⚠ Rueckstand eines abgebrochenen Laufs gefunden - nehme ihn zurueck")
    zurueck()
    MARKE.unlink()

sichern()
MARKE.write_text("1")
atexit.register(lambda: (zurueck(), MARKE.unlink(missing_ok=True)))
signal.signal(signal.SIGTERM, lambda *a: sys.exit(1))

basis, grund = lauf()
if basis is None or basis > 0:
    print("⚠ BASIS IST NICHT GRUEN (%s) - ohne gruene Basis ist keine Gegenprobe deutbar" % (basis,))
    sys.exit(2)
print("Basis gruen.\n")

AV = "frontend/js/avatar.js"
proben = [
    # Die Regel selbst
    ("Fett-Regel driftet vom Plugin ab", AV,
     "(?<=\\\\S)\\\\*\\\\*'", "\\\\*\\\\*'"),
    ("die \\S-Waechter fallen weg", AV,
     "'\\\\*\\\\*(?=\\\\S)([^\\\\n]+?)(?<=\\\\S)\\\\*\\\\*'", "'\\\\*\\\\*([^\\\\n]+?)\\\\*\\\\*'"),
    ("Zeilengrenze faellt weg (Punkt statt [^\\n])", AV,
     "([^\\\\n]+?)", "([\\\\s\\\\S]+?)"),
    # Parse-Sicherheit
    ("Regel als LITERAL statt als String", AV,
     "try { return new RegExp('\\\\*\\\\*(?=\\\\S)([^\\\\n]+?)(?<=\\\\S)\\\\*\\\\*'); }",
     "try { return /\\*\\*(?=\\S)([^\\n]+?)(?<=\\S)\\*\\*/; }"),
    # Anwendung
    ("fett() wird gar nicht gerufen", AV, "if (md) html = fett(html);", ""),
    ("fett() greift auch ohne Schalter", AV, "if (md) html = fett(html);", "html = fett(html);"),
    ("Fett VOR der Maskierung (Einschleusen moeglich)", AV,
     "        var html = esc(s).replace(", "        var html = (md ? fett(String(s)) : String(s)).replace("),
    ("kein Rueckfall ohne Lookbehind-Unterstuetzung", AV,
     "        if (!_FETT_RE) return html;", ""),
    # Verdrahtung
    ("eine Fehlermeldung deutet Markdown mit", AV,
     "                addBot(T('avatar.error', 'Es ist ein Fehler aufgetreten.'));",
     "                addBot(T('avatar.error', 'Es ist ein Fehler aufgetreten.'), true);"),
    ("die Servermeldung (detail) deutet Markdown mit", AV,
     "addBot((res.d && res.d.detail) || T('avatar.error', 'Es ist ein Fehler aufgetreten.'));",
     "addBot((res.d && res.d.detail) || T('avatar.error', 'Es ist ein Fehler aufgetreten.'), true);"),
    ("die Modellantwort wird NICHT mehr gedeutet", AV,
     "\n            if (ans) addBot(ans, true);", "\n            if (ans) addBot(ans);"),
    ("die Teilantwort nach Abbruch wird nicht gedeutet", AV,
     "\n                if (ans) addBot(ans, true);", "\n                if (ans) addBot(ans);"),
    # URL-Zusammenspiel
    ("URL-Trim ohne Sternchen (Fett am Zeilenende stirbt)", AV,
     "/(?:\\*\\*|[)\\].,;:!?])+$/", "/[)\\].,;:!?]+$/"),
    ("Platzhalter wieder mit fester Marke (aus der Antwort nachbaubar)", AV,
     "'@@' + marke + (urls.length - 1) + '@@' + tail;", "'@@U' + (urls.length - 1) + '@@' + tail;"),
    ("und die Rueckersetzung dazu", AV,
     "new RegExp('@@' + marke + '(\\\\d+)@@', 'g')", "/@@U(\\d+)@@/g"),
    ("URL-Trim schneidet wieder EINZELNE Sternchen", AV,
     "/(?:\\*\\*|[)\\].,;:!?])+$/", "/[)\\].,;:!?*]+$/"),
    ("tail wieder IM Platzhalter versteckt", AV,
     "+ '</a>');\n            return '@@' + marke + (urls.length - 1) + '@@' + tail;",
     "+ '</a>' + tail);\n            return '@@' + marke + (urls.length - 1) + '@@';"),
    # Anzeige
    ("pre-wrap aus der Bot-Blase entfernt", "frontend/css/avatar.css",
     "    white-space: pre-wrap;\n", ""),
    ("Link-Kontrast im hellen Thema wieder ungeloest", "frontend/css/avatar.css",
     "body.light .jav-msg a { color: color-mix(in srgb, var(--accent, #6366f1) 55%, #000); }", ""),
    ("fester Ton statt --accent (Branding ignoriert)", "frontend/css/avatar.css",
     "color-mix(in srgb, var(--accent, #6366f1) 55%, #000)", "#4a2d72"),
    ("Cache-Buster auf einer Seite vergessen", "frontend/chat.html",
     "avatar.js?v=15", "avatar.js?v=14"),
]

# ⚠ REGEL STATT GEPFLEGTER LISTE: jede Datei, die eine Probe anfasst, muss in
# DATEIEN stehen. Genau das hat beim ersten Lauf gefehlt (chat.html), der
# Rueckstand blieb liegen und ein FREMDER Waechter meldete ihn.
_gesichert = {str(d.relative_to(ROOT)) for d in DATEIEN}
_fehlend = {p[1] for p in proben} - _gesichert
if _fehlend:
    print("⚠ nicht gesichert, aber von einer Probe angefasst: %s" % ", ".join(sorted(_fehlend)))
    sys.exit(2)

print("Gegenproben:")
treffer = sum(1 for p in proben if probe(*p))
print("\n%d von %d Proben beissen." % (treffer, len(proben)))

# Zusaetzlich: der komplette Altstand.
d = ROOT / AV
s = d.read_text(encoding="utf-8")
s2 = s.replace("if (md) html = fett(html);", "").replace(", true)", ")")
d.write_text(s2, encoding="utf-8")
fails, _ = lauf()
zurueck()
print("Kompletter Altstand: %s FAIL" % fails)

sys.exit(0 if treffer == len(proben) else 1)
