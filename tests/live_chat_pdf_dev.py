"""Abnahme im ECHTEN Chrome auf DEV: "Chat als PDF" mit echten Bildern.

WARUM DAS NOETIG IST – der jsdom-Waechter kann drei Dinge nicht:
  * jsdom rechnet kein Layout und rendert kein <canvas>: dass ein Chart.js-
    Diagramm wirklich als Bild im PDF landet, sagt nur ein echter Browser.
  * jsdom laedt keine Bilder: ob der Abruf-Schluessel beim Einbetten
    tatsaechlich akzeptiert wird, entscheidet der echte Server.
  * Ein PDF entsteht ueberhaupt erst im Browser. Geprueft wird deshalb das
    ERGEBNIS: Seitenzahl, Text und die enthaltenen BILDER (pdfimages).

Laeuft AUF DEV im Produktiv-venv:
    /opt/jarvis/venv/bin/python /opt/jarvis/tests/live_chat_pdf_dev.py
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

import websocket

sys.path.insert(0, "/opt/jarvis")
sys.argv = ["x"]
import urllib3  # noqa: E402
urllib3.disable_warnings()
from backend.main import generate_token  # noqa: E402

TOK = generate_token("jarvis")
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if not isinstance(name, str):
        print("ABBRUCH: check() falsch herum")
        sys.exit(2)
    if cond:
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))


# Echte Bilder auf diesem Server: eines ueber die Capability-URL
# (/api/generated), eines ueber den Abruf-Schluessel (/api/documents).
GEN_DIR = "/opt/jarvis/data/generated_images"
DOC_DIR = "/opt/jarvis/data/documents"
gen = sorted(f for f in os.listdir(GEN_DIR) if f.endswith(".png"))
doc = sorted(f for f in os.listdir(DOC_DIR) if f.endswith(".png") and "__" in f)
if not gen or not doc:
    print("ABBRUCH: kein Testbild auf dem Server (generated=%d documents=%d)" % (len(gen), len(doc)))
    sys.exit(2)
GEN_URL = "/api/generated/" + gen[0]
DOC_URL = "/api/documents/" + doc[0]
print("Testbilder: %s | %s" % (GEN_URL, DOC_URL))

PORT = int(os.environ.get("CDP_PORT", "9371"))
prof = "/tmp/chrome-chatpdf-%s" % os.environ.get("JARVIS_THEMA", "light")
PDF = "/tmp/chatpdf-abnahme-%s.pdf" % os.environ.get("JARVIS_THEMA", "light")
subprocess.run(["rm", "-rf", prof], check=False)
subprocess.run(["rm", "-f", PDF], check=False)
p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                      "--remote-allow-origins=*", "--window-size=1400,900", "--no-first-run",
                      "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(6)


def targets():
    return json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))


def verbinde(t):
    return websocket.create_connection(t["webSocketDebuggerUrl"], timeout=30)


class Sitzung:
    def __init__(self, t):
        self.ws = verbinde(t)
        self.n = 0

    def cmd(self, m, params=None):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": m, "params": params or {}}))
        while True:
            d = json.loads(self.ws.recv())
            if d.get("id") == self.n:
                if "error" in d:
                    raise RuntimeError("%s: %s" % (m, d["error"]))
                return d.get("result", {})

    def js(self, code, geste=False):
        r = self.cmd("Runtime.evaluate", {"expression": code, "returnByValue": True,
                                          "awaitPromise": True, "userGesture": geste})
        if r.get("exceptionDetails"):
            raise RuntimeError(str(r["exceptionDetails"].get("exception", {}).get("description"))[:300])
        return (r.get("result") or {}).get("value")


try:
    s = Sitzung([t for t in targets() if t["type"] == "page"][0])
    s.cmd("Page.navigate", {"url": "https://127.0.0.1/chat"})
    time.sleep(2)
    # Thema per Umgebungsvariable: der Grund unter Diagramm und Schaubild folgt
    # dem Thema – im DUNKLEN Modus ist die Schrift hell, und pauschal Weiss zu
    # unterlegen ergaebe ein unlesbares Bild. Beide Laeufe gehoeren dazu.
    THEMA = os.environ.get("JARVIS_THEMA", "light")
    print("Thema: %s" % THEMA)
    s.js("localStorage.setItem('jarvis_token', %s);localStorage.setItem('jarvis_chat_user','jarvis');"
         "localStorage.setItem('jarvis_theme', %s);"
         % (json.dumps(TOK), json.dumps(THEMA)))
    s.cmd("Page.navigate", {"url": "https://127.0.0.1/chat"})
    time.sleep(9)

    check("/chat ist angemeldet geladen",
          s.js("!!document.getElementById('messages') && "
               "!document.getElementById('chat-screen').classList.contains('hidden')"))
    check("chatlib bringt exportTranscriptPdf mit",
          s.js("typeof (window.JarvisChatLib||{}).exportTranscriptPdf === 'function'"))
    check("der Abruf-Schluessel ist da (JarvisDL)",
          bool(s.js("!!(window.JarvisDL && /JDL1\\./.test(window.JarvisDL.url('%s')))" % DOC_URL)),
          str(s.js("window.JarvisDL && window.JarvisDL.url('%s')" % DOC_URL))[:80])

    # ── Verlauf setzen: zwei echte Bilder, ein echt gemaltes Canvas, ein
    #    Mermaid-artiges SVG, Bedienelemente und ein Abspieler.
    aufbau = """
    (function(){
      var m = document.getElementById('messages');
      var dl = window.JarvisDL ? window.JarvisDL.url('%(doc)s') : '%(doc)s';
      m.innerHTML =
        '<div class="date-sep"><span>Heute</span></div>'
      + '<div class="msg-row user"><div><div class="msg-time">'
      +   '<button class="msg-retry-btn">R</button><button class="msg-edit-btn">E</button>'
      +   '<span>10:15</span></div><div class="msg-bubble">Zeige mir den Umsatz</div></div></div>'
      + '<div class="msg-row bot"><div class="msg-avatar">J</div><div><div class="msg-time">10:16</div>'
      +   '<div class="msg-bubble"><p>Hier der <strong>Umsatz</strong>:</p>'
      +     '<img class="chat-img" src="' + dl + '" alt="Umsatz">'
      +     '<img class="chat-img" src="%(gen)s" alt="Generiert">'
      +     '<div class="jarvis-chart"><div class="jarvis-chart-tools"><button class="jarvis-chart-btn">PNG</button></div>'
      +       '<canvas id="probe-canvas" width="420" height="200"></canvas></div>'
      +     '<div class="jarvis-mermaid"><svg xmlns="http://www.w3.org/2000/svg" width="240" height="80">'
      +       '<style>.k{fill:#e11d48}</style><rect class="k" x="4" y="4" width="230" height="70" rx="8"/>'
      +       '<text x="20" y="45" font-size="18" fill="#fff">Ablauf</text></svg></div>'
      +     '<pre><code>print("hallo")</code></pre>'
      +     '<div class="uc-file-chip"><span class="uc-fc-name">ton.mp3</span>'
      +       '<audio controls src="data:audio/mp3;base64,AA"></audio></div>'
      +   '</div><div class="msg-stats">1200 Token</div>'
      +   '<div class="bubble-actions"><button class="bubble-act-btn">c</button></div></div></div>'
      + '<div class="msg-row bot" style="display:none"><div><div class="msg-time">10:17</div>'
      +   '<div class="msg-bubble">FREMDER-AGENT-TEXT</div></div></div>';
      // Canvas ECHT bemalen – so wird die toDataURL-Kette wirklich geprueft.
      var c = document.getElementById('probe-canvas');
      var x = c.getContext('2d');
      x.fillStyle = '#2563eb'; x.fillRect(10, 10, 400, 60);
      x.fillStyle = '#f8fafc'; x.font = '20px sans-serif';
      x.fillText('DIAGRAMM-PROBE', 24, 50);
      return m.querySelectorAll('.msg-row, .date-sep').length;
    })()
    """ % {"doc": DOC_URL, "gen": GEN_URL}
    check("Testverlauf gesetzt", s.js(aufbau) == 4, str(s.js("document.querySelectorAll('.msg-row').length")))

    # Bilder wirklich geladen? Sonst prueft der Export nichts.
    time.sleep(3)
    geladen = s.js("Array.from(document.querySelectorAll('#messages img'))"
                   ".map(function(i){return i.naturalWidth;})")
    check("beide Bilder sind im Chat geladen (Server liefert sie aus)",
          isinstance(geladen, list) and len(geladen) == 2 and all(w and w > 0 for w in geladen),
          str(geladen))

    # ── OHNE Benutzergeste: der Popup-Blocker greift, und der Code sagt es ──
    # Das ist keine Nebenprobe: sie belegt LIVE, dass `open()` ohne Geste null
    # liefert – genau deshalb muss der Aufruf synchron im Klick stehen.
    ohne = s.js("""
    (function(){
      var rows = Array.from(document.querySelectorAll('#messages .msg-row'));
      return window.JarvisChatLib.exportTranscriptPdf({ rows: rows, titel: 'Ohne Geste' })
        .then(function(r){ return r; });
    })()
    """)
    check("ohne Benutzergeste: Chrome blockt das Fenster, der Export meldet false",
          ohne is False, str(ohne))
    check("und der Benutzer bekommt einen Hinweis (Toast)",
          bool(s.js("!!document.querySelector('.jv-media-toast')")),
          str(s.js("(document.querySelector('.jv-media-toast')||{}).textContent"))[:80])

    # ── Export ausloesen (der echte Weg, inkl. echtem window.open) ──────────
    s.js("""
    (function(){
      var rows = Array.from(document.querySelectorAll('#messages .msg-row, #messages .date-sep'))
                      .filter(function(r){ return r.style.display !== 'none'; });
      window.__pdfFertig = null;
      window.JarvisChatLib.exportTranscriptPdf({
        rows: rows, titel: 'Abnahme Umsatz', userName: 'nexus\\\\jarvis',
        botName: (window.jarvisMarke ? window.jarvisMarke() : 'Jarvis'),
        hinweise: ['1 Nachricht(en) anderer Agenten sind nicht enthalten.'],
      }).then(function(r){ window.__pdfFertig = r; });
      return true;
    })()
    """, geste=True)
    time.sleep(8)
    check("Export meldet Erfolg", s.js("window.__pdfFertig") is True,
          str(s.js("window.__pdfFertig")))

    # ── Das Druckfenster ist ein eigenes Target ────────────────────────────
    seiten = [t for t in targets() if t["type"] == "page"]
    check("ein zweites Fenster wurde geoeffnet", len(seiten) >= 2,
          str([t.get("title") for t in seiten]))
    kind = None
    for t in seiten:
        if "Abnahme Umsatz" in (t.get("title") or ""):
            kind = t
    check("der Fenstertitel traegt den Sitzungsnamen (Dateinamen-Vorschlag)", kind is not None,
          str([t.get("title") for t in seiten]))

    if kind:
        k = Sitzung(kind)
        txt = k.js("document.body.innerText")
        check("Titel steht im Dokument", "Abnahme Umsatz" in (txt or ""))
        check("beide Sprecher benannt",
              "nexus\\jarvis" in (txt or "") and (k.js("!!document.querySelector('.jv-pdf-msg.bot')")),
              (txt or "")[:120].replace("\n", " | "))
        check("der Hinweis auf die ausgeblendeten Agenten steht im Kopf",
              "anderer Agenten" in (txt or ""))
        check("die ausgeblendete Zeile ist NICHT im PDF",
              "FREMDER-AGENT-TEXT" not in (txt or ""))
        check("Codeblock uebernommen", 'print("hallo")' in (txt or ""))
        check("Dateiname des Anhangs uebernommen", "ton.mp3" in (txt or ""))
        check("kein Bedienelement im Druckdokument",
              k.js("document.querySelectorAll('.jv-pdf-verlauf button, .jv-pdf-verlauf input, "
                   ".jv-pdf-verlauf audio').length") == 0)
        srcs = k.js("Array.from(document.querySelectorAll('.jv-pdf-verlauf img'))"
                    ".map(function(i){return i.src.slice(0,24);})")
        check("JEDES Bild ist eingebettet (data:) – kein ablaufender Link",
              isinstance(srcs, list) and len(srcs) == 3 and all(str(x).startswith("data:") for x in srcs),
              str(srcs))
        masse = k.js("Array.from(document.querySelectorAll('.jv-pdf-verlauf img'))"
                     ".map(function(i){return i.naturalWidth + 'x' + i.naturalHeight;})")
        check("alle eingebetteten Bilder sind wirklich dekodierbar",
              isinstance(masse, list) and all("x" in m and not m.startswith("0x") for m in masse),
              str(masse))
        grund = k.js("(function(){var e=document.querySelector('.jv-pdf-verlauf .jarvis-mermaid');"
                     "return e ? e.style.background : '';})()")
        check("der Grund unter dem Schaubild ist der GEMESSENE, nicht pauschal Weiss",
              bool(grund) and grund not in ("rgb(255, 255, 255)", "#fff", "white")
              if THEMA == "dark" else bool(grund), str(grund))
        check("das Schaubild ist als SVG erhalten und hat einen Grund",
              bool(k.js("(function(){var e=document.querySelector('.jv-pdf-verlauf .jarvis-mermaid');"
                        "return !!e && !!e.querySelector('svg') && !!e.style.background;})()")))
        check("kein waagerechter Ueberlauf",
              k.js("document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1"),
              str(k.js("document.documentElement.scrollWidth + '/' + document.documentElement.clientWidth")))

        # ── DAS ECHTE PDF ─────────────────────────────────────────────────
        r = k.cmd("Page.printToPDF", {"printBackground": True, "preferCSSPageSize": True})
        with open(PDF, "wb") as f:
            f.write(base64.b64decode(r["data"]))
        gr = os.path.getsize(PDF)
        check("ein PDF ist entstanden", gr > 20000, "%d Bytes" % gr)
        info = subprocess.run(["pdfinfo", PDF], capture_output=True, text=True).stdout
        check("das PDF hat mindestens eine Seite", "Pages:" in info,
              info.splitlines()[0] if info else "")
        ptxt = subprocess.run(["pdftotext", PDF, "-"], capture_output=True, text=True).stdout
        check("der Verlaufstext steht im PDF", "Zeige mir den Umsatz" in ptxt)
        check("der Druckknopf wird NICHT mitgedruckt", "Als PDF speichern" not in ptxt)
        bilder = subprocess.run(["pdfimages", "-list", PDF], capture_output=True, text=True).stdout
        zeilen = [l for l in bilder.splitlines() if l.strip() and l.split()[0].isdigit()]
        check("die Bilder sind IM PDF enthalten (pdfimages)", len(zeilen) >= 3,
              "%d Bilder\n%s" % (len(zeilen), bilder[:300]))
        print("\n  PDF liegt unter %s (%d Bytes, %d Bilder)" % (PDF, gr, len(zeilen)))
finally:
    try:
        p.terminate()
    except Exception:
        pass

print("\n" + "─" * 40)
print("\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
