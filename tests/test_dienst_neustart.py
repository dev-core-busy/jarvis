#!/usr/bin/env python3
"""Waechter: „Dienst neu starten" in *Einstellungen → KI & System*.

Anlass (2026-09-07): der Aufraeum-Dialog meldet nach dem Schreiben von
Gedaechtnis-Dateien, ein Neustart sei noetig, „(Einstellungen → KI & System)".
**Dort gab es keinen Neustart-Knopf** – gemessen: der einzige Aufrufer von
``POST /api/system/restart`` war das WebDAV-Formular unter *Wissen*. Die
Meldung schickte den Administrator zu einem Bedienelement, das es nicht gibt.

Geprueft wird die REGEL, nicht ein Wortlaut:
  1. DIE DRIFT-SCHRANKE: nennt ``_nachwirkung()`` einen Weg in der
     Oberflaeche, muss dieser Weg dort auch existieren – Abschnitt UND Knopf.
     Ohne diese Pruefung laufen Text und Bedienelement wieder auseinander.
  2. der Knopf liegt im Abschnitt *System-Einstellungen* (``prof-sect-tuning``),
     nicht irgendwo auf der Seite
  3. er ruft ``POST /api/system/restart`` mit Authorization
  4. VOR dem Neustart wird gefragt – er trennt ALLE Benutzer und bricht
     laufende Agenten-Auftraege ab
  5. DER ERFOLG WIRD GEMESSEN: ``started_at`` aus ``/api/health`` wird vorher
     geholt und nachher verglichen. Ein blosses „wieder erreichbar" wuerde auch
     dann gemeldet, wenn der Neustart gar nicht stattfand – genau der Fall, in
     dem der Administrator die Meldung braucht.
  6. der Endpunkt bleibt Administratoren vorbehalten
  7. der Hinweistext sagt DIENST, nicht Rechner – das war die Rueckfrage

Laeuft OHNE fastapi: die Funktionen werden per ``ast`` geschnitten und
AUSGEFUEHRT. Kommentare und Docstrings werden vor Textpruefungen entfernt –
sonst liest der Waechter seine eigene Begruendung (im Projekt der dreizehnte
Fall dieser Klasse).
"""
import ast
import io
import re
import sys
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = fail = 0


def abschnitt(t):
    print("\n\033[1m%s\033[0m" % t)


def check(name, cond, detail=""):
    """(Beschreibung, Bedingung) – NICHT umgekehrt."""
    global ok, fail
    if isinstance(name, bool) or not isinstance(name, str):
        print("\033[31mABBRUCH: check() falsch herum aufgerufen\033[0m")
        sys.exit(2)
    if bool(cond):
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – " + str(detail)) if detail else ""))


def abbruch(text):
    print("\033[31mABBRUCH: %s\033[0m" % text)
    sys.exit(2)


def ohne_kommentare_py(quelle: str) -> str:
    """Kommentare durch Leerzeichen ersetzen, Zeichen fuer Zeichen sonst
    erhalten – ein Entferner, der den Quelltext UMBAUT, prueft nicht mehr den
    Quelltext (Register)."""
    aus = list(quelle)
    for tok in tokenize.generate_tokens(io.StringIO(quelle).readline):
        if tok.type == tokenize.COMMENT:
            zeilen = quelle.splitlines(keepends=True)
            start = sum(len(z) for z in zeilen[:tok.start[0] - 1]) + tok.start[1]
            for i in range(start, start + len(tok.string)):
                if i < len(aus):
                    aus[i] = " "
    return "".join(aus)


def ohne_js_kommentare(quelle: str) -> str:
    """Grobe, aber ausreichende Fassung fuer JS – mit POSITIVKONTROLLE beim
    Aufrufer (ein Entferner ohne Kontrolle kann still den halben Code fressen)."""
    aus = re.sub(r"/\*.*?\*/", " ", quelle, flags=re.S)
    aus = re.sub(r"(^|[^:\\\"'])//[^\n]*", lambda m: m.group(1), aus)
    return aus


MAIN = ROOT / "backend" / "main.py"
AUFR = ROOT / "backend" / "wissen_aufraeumen.py"
SETTINGS = ROOT / "frontend" / "settings.html"
APP = ROOT / "frontend" / "js" / "app.js"
I18N = ROOT / "frontend" / "js" / "i18n.js"

Q_MAIN = MAIN.read_text(encoding="utf-8")
Q_AUFR = AUFR.read_text(encoding="utf-8")
Q_SET = SETTINGS.read_text(encoding="utf-8")
Q_APP = APP.read_text(encoding="utf-8")
Q_I18N = I18N.read_text(encoding="utf-8")

# ── _nachwirkung() ausfuehren ──────────────────────────────────────────────
baum = ast.parse(Q_AUFR)
nw = next((n for n in baum.body
           if isinstance(n, ast.FunctionDef) and n.name == "_nachwirkung"), None)
if nw is None:
    abbruch("_nachwirkung nicht in backend/wissen_aufraeumen.py gefunden")
ns = {}
exec(compile(ast.fix_missing_locations(ast.Module(body=[nw], type_ignores=[])),
             "<schnitt>", "exec"), ns)
MELDUNG = ns["_nachwirkung"]([{"schluessel": "gedaechtnis:memory.json"}])


# ══ 1. DIE DRIFT-SCHRANKE ═════════════════════════════════════════════════
abschnitt("1 – Der genannte Weg existiert in der Oberflaeche")

check("die Meldung nennt ueberhaupt einen Weg", bool(MELDUNG) and "Einstellungen" in MELDUNG,
      MELDUNG)
# Jeder in Anfuehrungszeichen genannte Bedienelement-Name muss im Markup stehen.
zitate = re.findall(r"„([^\"„]{3,40})\"", MELDUNG)
check("die Meldung nennt ein Bedienelement in Anfuehrungszeichen", bool(zitate), MELDUNG)
markup_text = re.sub(r"<!--.*?-->", " ", Q_SET, flags=re.S)
for z in zitate:
    check("Bedienelement %r existiert im Markup von /settings" % z, z in markup_text)
# Die Abschnitts-Kette ebenso: was die Meldung als Ort nennt, muss dort stehen.
for teil in ("KI & System", "System-Einstellungen"):
    if teil in MELDUNG:
        check("Ort %r ist in /settings zu finden" % teil,
              teil in markup_text or teil in Q_I18N)
check("die Meldung sagt DIENST, nicht Rechner",
      "DIENSTES" in MELDUNG or "Dienst" in MELDUNG, MELDUNG)
check("und stellt klar, dass NICHT der Rechner gemeint ist",
      "Rechner" in MELDUNG, MELDUNG)


# ══ 2. Der Knopf sitzt im richtigen Abschnitt ═════════════════════════════
abschnitt("2 – Der Knopf liegt in *System-Einstellungen*")

i_btn = Q_SET.find('id="btn-service-restart"')
i_body = Q_SET.find('id="prof-sect-tuning-body"')
check("Knopf #btn-service-restart im Markup", i_btn > 0)
check("Abschnitts-Koerper prof-sect-tuning-body im Markup", i_body > 0)
if i_btn > 0 and i_body > 0:
    # Ende des Koerpers: die naechste kb-section nach dem Koerper-Anfang.
    i_ende = Q_SET.find('<!-- Agent API Key -->', i_body)
    check("der Knopf liegt INNERHALB des Abschnitts",
          i_body < i_btn < i_ende, "btn=%d body=%d ende=%d" % (i_btn, i_body, i_ende))
check("Statusfeld daneben", 'id="service-restart-status"' in Q_SET)
check("Beschriftung und Hinweis kommen aus i18n",
      'data-i18n="profile.restart_btn"' in Q_SET
      and 'data-i18n="profile.restart_hint"' in Q_SET)


# ══ 3.–5. Die Verdrahtung, AUSGEFUEHRT ════════════════════════════════════
abschnitt("3 – Der Klick: Rueckfrage, Aufruf, GEMESSENER Erfolg")

# Den Verdrahtungsblock geklammert schneiden (nicht am ersten "\n}" – das
# taugt nur fuer mehrzeilige Funktionen, Register).
start = Q_APP.find("const _btnRs = document.getElementById('btn-service-restart');")
if start < 0:
    abbruch("Verdrahtung von #btn-service-restart nicht in app.js gefunden")
tiefe, ende = 0, None
for i in range(start, len(Q_APP)):
    if Q_APP[i] == "{":
        tiefe += 1
    elif Q_APP[i] == "}":
        tiefe -= 1
        if tiefe == 0:
            ende = i + 1
            break
BLOCK = Q_APP[start:ende or len(Q_APP)]
check("Block geschnitten (%d Zeichen)" % len(BLOCK), 500 < len(BLOCK) < 8000)

B = ohne_js_kommentare(BLOCK)
# POSITIVKONTROLLE des Kommentar-Entferners: bekannter Code muss bleiben,
# bekannter Kommentartext muss weg.
check("Kommentar-Entferner arbeitet (Code bleibt, Begruendung faellt)",
      "getElementById('btn-service-restart')" in B
      and "BEHAUPTET" not in B and "wuerde auch dann gemeldet" not in B)

check("Rueckfrage vor dem Neustart", "confirm(" in B)
check("die Rueckfrage kommt VOR dem Aufruf",
      B.find("confirm(") < B.find("/api/system/restart"),
      "confirm=%d restart=%d" % (B.find("confirm("), B.find("/api/system/restart")))
check("ruft POST /api/system/restart", "/api/system/restart" in B and "'POST'" in B)
check("mit Authorization-Kopf", "Authorization" in B)
check("Knopf wird waehrend des Laufs gesperrt", ".disabled = true" in B)
check("und danach wieder freigegeben", ".disabled = false" in B)

# Der Kern: gemessen, nicht behauptet.
check("holt /api/health", "/api/health" in B)
check("liest started_at", "started_at" in B)
check("holt den Vergleichswert VOR dem Neustart",
      B.find("started_at") < B.find("/api/system/restart"),
      "started_at=%d restart=%d" % (B.find("started_at"), B.find("/api/system/restart")))
check("vergleicht nachher (ungleich = neuer Prozess)",
      "!== vorher" in B or "!= vorher" in B)
# ⚠ Die Wartezeit muss ZWISCHEN dem Neustart-Aufruf und der Schleife stehen
# und lang genug sein. Ein blosses "irgendwo steht schlaf(1234)" war trivial
# wahr – es traf das schlaf(1000) IM Schleifenrumpf (Register: die Eigenschaft
# messen, nicht ein Vorkommen).
_i_post = B.find("/api/system/restart")
_i_while = B.find("while (")
_wartezeiten = [(m.start(), int(m.group(1)))
                for m in re.finditer(r"schlaf\(\s*(\d+)\s*\)", B)]
_davor = [w for pos, w in _wartezeiten if _i_post < pos < _i_while]
check("wartet VOR dem ersten Poll, und zwar >= 2 s "
      "(der Endpunkt antwortet, bevor der Neustart laeuft)",
      _i_post > 0 and _i_while > _i_post and any(w >= 2000 for w in _davor),
      "gefunden zwischen Aufruf und Schleife: %s" % (_davor,))
check("meldet den Fall 'unveraendert weiter' eigens",
      "restart_nochange" in B)
check("meldet den Fall 'antwortet noch nicht' eigens", "restart_slow" in B)
check("`no-store` beim Health-Abruf (ein Cache machte den Vergleich wertlos)",
      "no-store" in B)


# ══ 6. /api/health liefert started_at, /api/system/restart bleibt Admin ═══
abschnitt("4 – Backend: Messgrundlage und Rechte")

m_health = re.search(r'@app\.get\("/api/health"\)\s*\nasync def health\(\):(.*?)\n@app\.',
                     Q_MAIN, flags=re.S)
check("/api/health gefunden", m_health is not None)
if m_health:
    rumpf = ohne_kommentare_py("def health():" + m_health.group(1))
    check("liefert started_at", '"started_at"' in rumpf, rumpf[-300:])
    check("aus einer beim IMPORT gesetzten Konstante (nicht pro Abruf neu)",
          "_PROZESS_START" in rumpf)
check("_PROZESS_START ist eine Modul-Zuweisung",
      re.search(r"^_PROZESS_START\s*=\s*time\.time\(\)", Q_MAIN, flags=re.M) is not None)

m_rs = re.search(r'@app\.post\("/api/system/restart"\)\s*\nasync def system_restart\(([^)]*)\)',
                 Q_MAIN)
check("/api/system/restart gefunden", m_rs is not None)
if m_rs:
    check("bleibt Administratoren vorbehalten (require_local_auth)",
          "require_local_auth" in m_rs.group(1), m_rs.group(1))


# ══ 7. i18n in DE und EN ══════════════════════════════════════════════════
abschnitt("5 – Texte in beiden Sprachen")

for key in ("profile.section_restart", "profile.restart_btn", "profile.restart_hint",
            "profile.restart_confirm", "profile.restart_sent", "profile.restart_back",
            "profile.restart_nochange", "profile.restart_slow", "profile.restart_failed"):
    n = len(re.findall(r"'" + re.escape(key) + r"'\s*:", Q_I18N))
    check("%s in DE und EN (%d)" % (key, n), n == 2, n)

m_de = re.search(r"'profile\.restart_hint':\s*'([^']*)'", Q_I18N)
check("der Hinweis sagt ausdruecklich 'nicht den Rechner'",
      m_de is not None and "nicht den Rechner" in m_de.group(1))
check("und nennt die Nebenwirkung (alle Benutzer getrennt)",
      m_de is not None and ("ALLE" in m_de.group(1) or "alle" in m_de.group(1)))
# Platzhalter muessen in beiden Sprachen gleich sein, sonst steht in einer
# Sprache eine Zahl ohne Ort.
for key in ("profile.restart_back", "profile.restart_slow"):
    werte = re.findall(r"'" + re.escape(key) + r"':\s*'([^']*)'", Q_I18N)
    check("%s: {s} in beiden Sprachen" % key,
          len(werte) == 2 and all("{s}" in w for w in werte), werte)


# ══ 6. Der Kontrast der Statusmeldung – GERECHNET ═════════════════════════
abschnitt("6 – Lesbarkeit in BEIDEN Themen")

STYLE = (ROOT / "frontend" / "css" / "style.css").read_text(encoding="utf-8")
THEME = (ROOT / "frontend" / "css" / "theme.css").read_text(encoding="utf-8")


def _rgb(h):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def _leuchte(c):
    m = [v / 255 for v in c]
    m = [(v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4) for v in m]
    return 0.2126 * m[0] + 0.7152 * m[1] + 0.0722 * m[2]


def _kontrast(a, b):
    x, y = _leuchte(_rgb(a)), _leuchte(_rgb(b))
    h, d = max(x, y), min(x, y)
    return (h + 0.05) / (d + 0.05)


# Die Farbe kommt aus KLASSEN, nicht aus einem Inline-Style – nur so laesst
# sie sich je Thema unterscheiden.
block = ohne_js_kommentare(BLOCK)
check("die Statusfarbe wird ueber Klassen gesetzt", "classList" in block)
check("kein Inline-Style auf die Farbe (waere in einem Thema unlesbar)",
      ".style.color" not in block)
for k in ("svc-ok", "svc-warn", "svc-err"):
    check("Klasse %s im CSS definiert" % k,
          ("#service-restart-status." + k) in STYLE)
    check("Klasse %s wird im Code benutzt" % k, k in block)

# ⚠ Die hellen Toene sind gerechnet, nicht geschaetzt: --success/--warning/
# --danger liegen im hellen Thema bei 2,33 / 1,97 / 3,45 auf diesem Grund.
GRUND_HELL = "#f4f5f7"
hell = re.findall(r"body\.light #service-restart-status\.svc-\w+\s*\{\s*color:\s*(#[0-9a-fA-F]{6})",
                  STYLE)
# ⚠ DIE FALLE, die erst der echte Browser gezeigt hat: ein Inline-Style
# schlaegt JEDE Klassenregel. Traegt der Status-Span `color` im style-Attribut,
# sind die drei Klassen wirkungslos – und die Meldung stand im hellen Thema bei
# 2,33:1, obwohl das CSS korrekt war.
m_span = re.search(r'<span id="service-restart-status"[^>]*style="([^"]*)"', Q_SET)
check("Status-Span gefunden", m_span is not None)
check("KEIN color im Inline-Style (sonst sind die Klassen wirkungslos)",
      m_span is not None and "color" not in m_span.group(1), m_span.group(1) if m_span else "")
check("die Grundfarbe steht stattdessen im CSS",
      re.search(r"#service-restart-status\s*\{[^}]*color:", STYLE) is not None)

check("drei eigene Toene fuer das helle Thema", len(hell) == 3, hell)
for farbe in hell:
    kk = _kontrast(farbe, GRUND_HELL)
    check("hell: %s erreicht 4,5:1 (%.2f)" % (farbe, kk), kk >= 4.5)
# Und die Gegenrichtung: im dunklen Thema muessen die Variablen taugen.
GRUND_DUNKEL = "#0a0e17"
for name in ("success", "warning", "danger"):
    m = re.search(r"--" + name + r":\s*(#[0-9a-fA-F]{6})", THEME)
    if m:
        kk = _kontrast(m.group(1), GRUND_DUNKEL)
        check("dunkel: --%s erreicht 4,5:1 (%.2f)" % (name, kk), kk >= 4.5)


print("\n\033[1mErgebnis: %d OK, %d FAIL\033[0m" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
