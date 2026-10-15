#!/usr/bin/env python3
"""Probe: rendert das einvendorte Mermaid-Bundle – und bleiben die Beschriftungen SVG?

ANLASS (2026-10-01): Tausch von Mermaid 11.12.0 auf 11.17.2. Ein Bundle, das
nicht laedt, faellt im Betrieb nur als LEERER RAHMEN auf – `mermaid_blocks.js`
faengt den Fehlschlag ab und schreibt eine Fehlerklasse ins DOM. Es gab fuer
diesen Pfad bis dahin keine Messung.

GEMESSEN WIRD DIE WIRKUNG, nicht das Vorkommen:
 1. das Bundle setzt `window.mermaid` (esbuild-IIFE, globalThis-Zuweisung),
 2. `render()` liefert wirklich ein <svg>,
 3. mit der Konfiguration aus `mermaid_blocks.js` (securityLevel 'strict',
    htmlLabels false) entstehen KEINE <foreignObject>-Knoten.

⚠ ZUR VERSION, und das ist eine EINSCHRAENKUNG dieser Probe: Mermaid 11
veroeffentlicht keine Laufzeit-Auskunft. Am 2026-10-01 nachgesehen – das globale
Objekt hat 15 Schluessel (`render`, `initialize`, `parse`, `mermaidAPI` …) und
**kein** `version`; ein `mermaid.version()` gibt `undefined`, nicht die Fassung.
Die Fassung wird deshalb aus dem BUNDLE-TEXT gelesen, also ein Vorkommen und
keine Wirkung. Dagegen die Schranke: es muss GENAU EINE Fassungsangabe darin
stehen – finden sich mehrere, ist die Aussage nicht eindeutig und die Probe
bricht mit Exit 2 ab, statt sich eine davon auszusuchen.

Punkt 4 ist der teure: steht `htmlLabels` nur unter `flowchart` statt auf der
obersten Ebene, bleiben die KANTEN-Beschriftungen HTML – und HTML im Diagramm
ist der Weg, auf dem eine LLM-Antwort Markup in den Origin des Portals bringt.
Deshalb traegt die Probe eine Kantenbeschriftung im Testdiagramm.

⚠ Ueber einen HTTP-Server, NICHT ueber file:// – das Bundle wird unter
`/static/js/vendor/...` geladen (Register).

    python3 tests/live_mermaid_rendern.py              # im Repo
    python3 live_mermaid_rendern.py /opt/jarvis/frontend   # auf einem Server

Das zweite ist kein Komfort, sondern Notwendigkeit: ECHT traegt **kein**
`tests/`-Verzeichnis (am 2026-10-01 festgestellt). Ohne Parameter leitet die
Probe ihre Wurzel aus `__file__` ab – aus `/tmp` gestartet zeigt die nach `/`,
und die Probe bricht mit Exit 2 ab. Das ist richtig so (sie besteht nicht
still), macht die Produktion aber unmessbar. Der Parameter schliesst genau
diese Luecke.

Exit 0 = alles gut, Exit 1 = Befund, Exit 2 = konnte nicht laufen
"""
import functools
import http.server
import json
import pathlib
import re
import socket
import subprocess
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
# Frontend-Verzeichnis als Argument (siehe Docstring: auf ECHT gibt es kein
# tests/, die Probe liegt dort nicht neben dem Repo).
FRONT = (pathlib.Path(sys.argv[1]).resolve() if len(sys.argv) > 1
         else ROOT / "frontend")
BUNDLE = FRONT / "js" / "vendor" / "mermaid.min.js"
BLOCKS = FRONT / "js" / "mermaid_blocks.js"

MINDEST = (11, 15, 0)

ok = 0
fehler = 0


def pruefe(was, bedingung, detail=""):
    global ok, fehler
    if bedingung:
        ok += 1
        print(f"  \033[32m✓\033[0m {was}")
    else:
        fehler += 1
        print(f"  \033[31m✗\033[0m {was}" + (f"\n      {detail}" if detail else ""))


def version_tupel(text):
    teile = []
    for stueck in str(text).strip().split("."):
        m = re.match(r"^(\d+)", stueck)
        if not m:
            return None
        teile.append(int(m.group(1)))
    return tuple(teile) if teile else None


# ── Voraussetzungen ──────────────────────────────────────────────────────────
if not BUNDLE.exists():
    print(f"Exit 2: {BUNDLE} fehlt")
    sys.exit(2)
if not BLOCKS.exists():
    print(f"Exit 2: {BLOCKS} fehlt")
    sys.exit(2)

chrome = None
for kandidat in ("google-chrome", "chromium", "chromium-browser"):
    import shutil as _sh
    if _sh.which(kandidat):
        chrome = kandidat
        break
if not chrome:
    print("Exit 2: kein Chrome gefunden. Gesucht: google-chrome, chromium, "
          "chromium-browser")
    sys.exit(2)

# Der Cache-Buster von LIB muss zum Bundle passen – sonst liefert der Browser
# des Benutzers nach dem Tausch weiter die alte Fassung aus dem Cache.
lib_zeile = re.search(r"var LIB\s*=\s*'([^']+)'", BLOCKS.read_text(encoding="utf-8"))

# Fassung aus dem Bundle-Text (siehe Einschraenkung im Docstring).
#
# NICHT einfach nach `version:"x.y.z"` suchen: in 11.17.2 stehen ZWEI Treffer
# im Bundle – `globalThis.injected ??= {... version:"0.0.0"}` aus einer
# eingebetteten Abhaengigkeit und Mermaids eigene Angabe. Eine Regex ueber beide
# haette sich eine davon ausgesucht.
#
# Und die Form hat sich zwischen den Fassungen GEAENDERT (beide am 2026-10-01
# an den echten Dateien gemessen):
#   11.12.0:  {name:"mermaid",version:"11.12.0",description:...}
#   11.17.2:  {version:"11.17.2"},X=s(()=>Y.version,"getVersion")
# Ein Anker auf nur eine Form liefert beim anderen Bundle 0 Treffer – die Probe
# saehe eine zu alte Fassung dann als "nicht messbar" (Exit 2) statt als Befund.
# Deshalb beide Anker, und das Ergebnis muss EINDEUTIG sein.
_roh_bundle = BUNDLE.read_text(encoding="utf-8", errors="replace")
_ANKER = (
    r'name:"mermaid",version:"(\d+\.\d+\.\d+)"',               # bis ~11.12
    r'version:"(\d+\.\d+\.\d+)"\}[^;]{0,60}"getVersion"',      # ab ~11.17
)
_gefunden = sorted({v for a in _ANKER for v in re.findall(a, _roh_bundle)})
if len(_gefunden) != 1:
    print(f"Exit 2: Mermaids Fassungsangabe nicht eindeutig auffindbar "
          f"({len(_gefunden)} Treffer: {_gefunden[:5]}). Entweder hat das Bundle "
          f"seine Struktur erneut geaendert oder kein Anker trifft – in beiden "
          f"Faellen ist die Fassung NICHT belegt, und das ist kein Bestehen.")
    sys.exit(2)
BUNDLE_VERSION = _gefunden[0]

# ── Probeseite: laedt das Bundle und rendert mit DER Konfiguration aus dem Code
# Die Seite schreibt ihr Ergebnis als JSON in #ergebnis; --dump-dom liest es.
SEITE = """<!DOCTYPE html><html><head><meta charset="utf-8"></head><body>
<div id="ergebnis">{"stand":"laeuft"}</div>
<script src="/static/js/vendor/mermaid.min.js"></script>
<script>
(function () {
  var raus = { stand: 'begonnen', global: !!window.mermaid,
               hat_render: false, svg: null, foreign: null,
               kantentext: null, fehler: null };
  function fertig() {
    document.getElementById('ergebnis').textContent = JSON.stringify(raus);
  }
  try {
    if (!window.mermaid) { raus.stand = 'kein-global'; fertig(); return; }
    // Mermaid 11 hat KEINE version-Auskunft (siehe Docstring) – gemessen wird,
    // dass die benutzte Schnittstelle da ist.
    raus.hat_render = typeof window.mermaid.render === 'function';
    // identisch zu initMermaid() in mermaid_blocks.js: htmlLabels auf OBERSTER Ebene
    window.mermaid.initialize({
      startOnLoad: false, securityLevel: 'strict', theme: 'dark',
      fontFamily: 'inherit', htmlLabels: false,
      flowchart: { htmlLabels: false }
    });
    // Kantenbeschriftung ("ja") ist der Fall, der bei falsch platziertem
    // htmlLabels als <foreignObject> herauskommt.
    var quelle = 'flowchart TD\\n  A[Start] -->|ja| B[Ende]\\n  B --> C[Danach]';
    window.mermaid.render('probe1', quelle).then(function (res) {
      var svg = (res && res.svg) || '';
      raus.svg = svg.indexOf('<svg') !== -1;
      raus.foreign = (svg.match(/<foreignObject/g) || []).length;
      raus.kantentext = svg.indexOf('ja') !== -1;
      raus.stand = 'fertig';
      fertig();
    }).catch(function (e) {
      raus.stand = 'render-fehler'; raus.fehler = String(e); fertig();
    });
  } catch (e) {
    raus.stand = 'ausnahme'; raus.fehler = String(e); fertig();
  }
})();
</script></body></html>"""


class Handler(http.server.SimpleHTTPRequestHandler):
    """Liefert /probe.html aus dem Speicher, alles andere aus frontend/."""

    def do_GET(self):
        if self.path.split("?")[0] == "/probe.html":
            roh = SEITE.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(roh)))
            self.end_headers()
            self.wfile.write(roh)
            return
        # /static/... auf frontend/ abbilden
        if self.path.startswith("/static/"):
            self.path = self.path[len("/static"):]
        super().do_GET()

    def log_message(self, *a):
        pass


def freier_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


port = freier_port()
srv = http.server.ThreadingHTTPServer(
    ("127.0.0.1", port),
    functools.partial(Handler, directory=str(FRONT)))
threading.Thread(target=srv.serve_forever, daemon=True).start()

print(f"Mermaid-Bundle: {BUNDLE.stat().st_size} Bytes | Testserver auf Port {port}")

dom = ""
try:
    with tempfile.TemporaryDirectory(prefix="mermaid-probe-") as profil:
        p = subprocess.run(
            [chrome, "--headless=new", "--no-sandbox", "--disable-gpu",
             f"--user-data-dir={profil}", "--virtual-time-budget=25000",
             "--dump-dom", f"http://127.0.0.1:{port}/probe.html"],
            capture_output=True, text=True, timeout=120)
        dom = p.stdout
finally:
    srv.shutdown()

m = re.search(r'<div id="ergebnis">(.*?)</div>', dom, re.S)
if not m:
    print("Exit 2: Probeseite lieferte kein Ergebnisfeld – Chrome-Ausgabe "
          f"({len(dom)} Zeichen) nicht deutbar")
    print(dom[:800])
    sys.exit(2)

roh = m.group(1).strip()
# Chrome maskiert den JSON-Text im DOM
roh = roh.replace("&quot;", '"').replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
try:
    erg = json.loads(roh)
except Exception as e:  # noqa: BLE001
    print(f"Exit 2: Ergebnisfeld nicht lesbar ({e}): {roh[:300]}")
    sys.exit(2)

# ── Positivkontrolle VOR den inhaltlichen Pruefungen ────────────────────────
# Ohne geladenes Bundle ist jede Aussage unten trivial – "0 foreignObject" waere
# dann richtig und bedeutungslos.
if erg.get("stand") == "laeuft":
    print("Exit 2: das Skript der Probeseite lief nicht (Zeitbudget zu klein?)")
    sys.exit(2)
if not erg.get("global"):
    print(f"Exit 2: das Bundle setzt window.mermaid NICHT (Stand: "
          f"{erg.get('stand')}). Positivkontrolle gescheitert – keine weitere "
          f"Aussage moeglich.")
    sys.exit(2)
print(f"  \033[32m✓\033[0m Positivkontrolle: Bundle geladen, window.mermaid gesetzt")

print(f"\n\033[1mMermaid-Fassung (aus dem Bundle-Text, nicht zur Laufzeit)\033[0m")
v = version_tupel(BUNDLE_VERSION)
pruefe("Fassungsangabe lesbar", v is not None,
       f"nicht als Zahlenfolge deutbar: {BUNDLE_VERSION!r}")
if v is not None:
    pruefe(f"Fassung >= {'.'.join(map(str, MINDEST))} (ist {BUNDLE_VERSION})",
           v >= MINDEST,
           f"{BUNDLE_VERSION} liegt unter der Untergrenze")
pruefe("render() ist als Funktion vorhanden", bool(erg.get("hat_render")),
       "mermaid_blocks.js ruft mermaid.render – fehlt sie, bleibt der Rahmen leer")

print(f"\n\033[1mRendering\033[0m")
pruefe("render() lief ohne Fehler",
       erg.get("stand") == "fertig",
       f"Stand {erg.get('stand')!r}, Fehler: {erg.get('fehler')!r}")
pruefe("Ergebnis enthaelt ein <svg>", bool(erg.get("svg")),
       "kein <svg> im Rueckgabewert – im Betrieb bliebe ein leerer Rahmen")
pruefe("Kantenbeschriftung im SVG vorhanden", bool(erg.get("kantentext")),
       "die Beschriftung 'ja' fehlt – Beschriftungen gingen verloren "
       "(siehe Register: foreignObject NICHT als Haertung entfernen)")

print(f"\n\033[1mHaertung: keine HTML-Beschriftungen\033[0m")
pruefe("0 <foreignObject> im gerenderten SVG",
       erg.get("foreign") == 0,
       f"{erg.get('foreign')} <foreignObject> gefunden. htmlLabels greift nicht "
       f"global – HTML aus einer LLM-Antwort liefe damit im Origin des Portals")

print(f"\n\033[1mCache-Buster\033[0m")
pruefe("LIB in mermaid_blocks.js traegt ein ?v=",
       lib_zeile is not None and "?v=" in lib_zeile.group(1),
       f"LIB-Zeile: {lib_zeile.group(1) if lib_zeile else 'nicht gefunden'} – "
       f"ohne Cache-Buster liefert der Browser nach einem Tausch die alte Fassung")

print(f"\n{'─' * 60}")
print(f"OK: {ok}   Fehler: {fehler}")
sys.exit(1 if fehler else 0)
