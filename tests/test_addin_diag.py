#!/usr/bin/env python3
"""Start-Diagnose des Outlook-Add-ins (backend/addin_diag.py, frontend/addin/diag.js).

Anlass 2026-11-05 (ECHT): Outlook im Web meldete "Add-In-Fehler beim
Starten", im Journal stand nichts – ohne Zugriffsprotokoll war nicht zu
sehen, ob das Fenster abgerufen wurde und wo der Start abbrach.

  [A] Abrufzeile: Rahmen-Kopfzeilen, Referer nur als Host, Browser kurz,
      Parameter nur als NAMEN, _host_Info nur in sauberer Form.
  [B] Meldungen: Schritt aus fester Liste, Feldlaengen, Steuerzeichen raus,
      Muell wirft nicht, Lastbremse je IP, keine IP im Journal.
  [C] main.py (Syntaxbaum): Route ohne Anmelde-Dependency UND als begruendete
      Ausnahme in zugang_regel; die Taskpane-Route ruft abruf().
  [D] taskpane.html: vor diag.js nur theme_frueh.js, ohne async/defer.
  [E] diag.js in jsdom mit Office-Attrappe: meldet html, office_da,
      office_bereit, mailbox; Fehler und CSP-Verstoesse werden gemeldet.

Exit 0 = gruen, 1 = Regelverstoss, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import contextlib
import io
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OK = FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global OK, FAIL
    if cond:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("\n         " + detail) if detail else ""))


def abbruch(grund: str) -> None:
    print("ABBRUCH (Exit 2): " + grund)
    sys.exit(2)


try:
    from backend import addin_diag as d
except Exception as e:  # noqa: BLE001
    abbruch("backend.addin_diag nicht importierbar: %s" % e)
if "backend.config" in sys.modules:
    abbruch("addin_diag hat backend.config importiert")

UA_EDGE = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
           "Chrome/131.0.0.0 Safari/537.36 Edg/131.0.2903.70")

print("[A] Abrufzeile")
z = d.abruf_zeile({"Sec-Fetch-Dest": "iframe", "Sec-Fetch-Site": "cross-site",
                   "Referer": "https://mail.firma.local/owa/?geheim=1#x",
                   "User-Agent": UA_EDGE},
                  "mv=1.2.0.0&_host_Info=Outlook$Web$16.01$de-DE$$$$0&token=GEHEIM")
if not z.startswith(d.PRAEFIX):
    abbruch("Abrufzeile ohne Praefix: %r" % z)
check("dest/site stehen drin", "dest=iframe" in z and "site=cross-site" in z, z)
check("Referer nur als Host", "referer=mail.firma.local" in z and "geheim" not in z and "/owa" not in z, z)
check("Browser kurz (Edg 131)", "browser=Edg 131" in z and "Windows NT" not in z, z)
check("Parameter nur als Namen", "params=_host_Info,mv,token" in z and "GEHEIM" not in z, z)
check("_host_Info steht drin", "host_info=Outlook$Web$16.01$de-DE$$$$0" in z, z)
z2 = d.abruf_zeile({}, "_host_Info=a b;rm")
check("unsauberes _host_Info -> ?", "host_info=?" in z2, z2)
check("ohne Kopfzeilen kein Fehler", "dest=-" in z2 and "referer=-" in z2, z2)
puffer = io.StringIO()
with contextlib.redirect_stdout(puffer):
    d.abruf(None, None)                     # darf nie werfen
check("abruf() mit Muell wirft nicht", True)

print("[B] Meldungen")
def mz(obj, ua=UA_EDGE):
    return d.meldung_zeile(json.dumps(obj).encode() if not isinstance(obj, bytes) else obj, ua)

z = mz({"lauf": "ab12cd34", "schritt": "office_bereit", "ms": 812, "detail": "host=Outlook plattform=OfficeOnline"})
check("gueltige Meldung -> Zeile", bool(z) and "lauf=ab12cd34 +812ms office_bereit" in z, str(z))
check("unbekannter Schritt verworfen", mz({"schritt": "beliebig", "detail": "x"}) is None)
check("kein JSON verworfen", mz(b"{kaputt") is None)
check("JSON-Liste verworfen", mz(b"[1,2]") is None)
check("zu grosser Koerper verworfen", mz(b"{" + b" " * (d.KOERPER_MAX + 10) + b"}") is None)
z = mz({"schritt": "fehler", "detail": "a\nb\x1b[31m" + "x" * 1000, "lauf": "<script>", "ms": "nix"})
check("Steuerzeichen ersetzt", bool(z) and "\n" not in z and "\x1b" not in z, repr(z))
check("Detail gekuerzt", bool(z) and len(z) < d.FELD_MAX + 200, str(len(z or "")))
check("Laufkennung nur alnum", bool(z) and "lauf=script " in z, str(z))
check("ms ungueltig -> 0", bool(z) and "+0ms" in z, str(z))
d._rate.clear()
with contextlib.redirect_stdout(io.StringIO()) as aus:
    ergebnisse = [d.melden(json.dumps({"schritt": "html"}).encode(), "192.0.2.7", UA_EDGE)
                  for _ in range(d.RATE_JE_MINUTE + 5)]
    anders = d.melden(json.dumps({"schritt": "html"}).encode(), "192.0.2.8", UA_EDGE)
check("Lastbremse greift je IP", ergebnisse.count(True) == d.RATE_JE_MINUTE, str(ergebnisse.count(True)))
check("andere IP unberuehrt", anders is True)
check("keine IP im Journal", "192.0.2" not in aus.getvalue())

print("[C] Einbindung in main.py und zugang_regel")
baum = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
route = taskpane = None
for n in ast.walk(baum):
    if isinstance(n, ast.AsyncFunctionDef):
        for dek in n.decorator_list:
            if (isinstance(dek, ast.Call) and isinstance(dek.func, ast.Attribute)
                    and dek.args and isinstance(dek.args[0], ast.Constant)):
                ziel = (dek.func.attr, dek.args[0].value)
                if ziel == ("post", "/api/addin/diag"):
                    route = n
                if ziel == ("get", "/addin/taskpane.html"):
                    taskpane = n
check("POST /api/addin/diag existiert", route is not None)
if route is not None:
    depends = [a for a in route.args.args + route.args.kwonlyargs if a.annotation is not None]
    deps = any(isinstance(x, ast.Call) and getattr(x.func, "id", "") == "Depends"
               for x in ast.walk(route.args))
    check("Route ohne Anmelde-Dependency", not deps)
    ruft = [x for x in ast.walk(route) if isinstance(x, ast.Call)
            and isinstance(x.func, ast.Attribute) and x.func.attr == "melden"]
    check("Route ruft addin_diag.melden", bool(ruft))
if taskpane is not None:
    ruft = [x for x in ast.walk(taskpane) if isinstance(x, ast.Call)
            and isinstance(x.func, ast.Attribute) and x.func.attr == "abruf"]
    check("Taskpane-Route ruft abruf()", bool(ruft))
else:
    check("Taskpane-Route gefunden", False)
try:
    from backend import zugang_regel
    ausn = zugang_regel.AUSNAHMEN.get(("POST", "/api/addin/diag"))
    check("M10-Ausnahme mit Art 'oeffentlich' und Grund",
          bool(ausn) and ausn[0] == "oeffentlich" and len(ausn[1]) > 10, str(ausn))
except Exception as e:  # noqa: BLE001
    check("zugang_regel lesbar", False, repr(e))

print("[D] taskpane.html")
html = (ROOT / "frontend" / "addin" / "taskpane.html").read_text(encoding="utf-8")
ohne_kommentar = re.sub(r"<!--.*?-->", "", html, flags=re.S)
skripte = re.findall(r"<script\b([^>]*)>", ohne_kommentar)
if not skripte:
    abbruch("keine <script>-Tags in taskpane.html gefunden")
# theme_frueh.js steht bewusst davor (muss direkt nach <body>, Waechter in
# test_outlook_addin); es ist eine Zeile ohne Abhaengigkeiten. Alles andere
# laedt NACH der Diagnose.
srcs = [re.search(r'src="([^"]+)"', a).group(1) if re.search(r'src="([^"]+)"', a) else "" for a in skripte]
pos = [i for i, q in enumerate(srcs) if q.startswith("/static/addin/diag.js?v=")]
davor = srcs[:pos[0]] if pos else srcs
erstes = skripte[pos[0]] if pos else ""
check("diag.js eingebunden", bool(pos), str(srcs[:3]))
check("vor diag.js nur theme_frueh.js",
      bool(pos) and all(q.startswith("/static/js/theme_frueh.js?v=") for q in davor), str(davor))
check("diag.js ohne async/defer", bool(pos) and "async" not in erstes and "defer" not in erstes, erstes)
check("diag.js existiert", (ROOT / "frontend" / "addin" / "diag.js").is_file())

print("[E] diag.js in jsdom")
node = shutil.which("node")
if not node:
    abbruch("node fehlt")
js = r"""
const { JSDOM } = require('./tests/lib/jsdom_laden')();
const fs = require('fs');
const code = fs.readFileSync('frontend/addin/diag.js', 'utf8');
const dom = new JSDOM('<!doctype html><body></body>', {
  url: 'https://jarvis.beispiel.de/addin/taskpane.html?mv=1.2.0.0&_host_Info=Outlook$Web',
  referrer: 'https://mail.firma.local/owa/', runScripts: 'outside-only' });
const w = dom.window, gesendet = [];
w.fetch = (url, opt) => { gesendet.push({ url, k: JSON.parse(opt.body) }); return Promise.resolve({}); };
w.eval(code);
setTimeout(() => {
  w.Office = { onReady: (cb) => setTimeout(() => cb({ host: 'Outlook', platform: 'OfficeOnline' }), 10),
               context: { mailbox: { item: {}, diagnostics: { hostName: 'OutlookWebApp', hostVersion: '15.20', OWAView: 'ThreeColumns' } } } };
}, 150);
setTimeout(() => {
  w.dispatchEvent(new w.ErrorEvent('error', { message: 'Boom', filename: 'x.js', lineno: 3, colno: 4 }));
  const ev = new w.Event('securitypolicyviolation');
  ev.violatedDirective = 'script-src-elem'; ev.blockedURI = 'https://cdn.beispiel.de/a.js';
  w.document.dispatchEvent(ev);
  // nicht ladbare Ressource: das error-Ereignis eines <script> blubbert NICHT –
  // nur ein Zuhoerer in der Capture-Phase am window sieht es
  const s = w.document.createElement('script');
  s.setAttribute('src', 'https://appsforoffice.microsoft.com/lib/1/hosted/office.js');
  w.document.body.appendChild(s);
  s.dispatchEvent(new w.Event('error', { bubbles: false }));
}, 400);
setTimeout(() => { console.log(JSON.stringify(gesendet)); w.close(); process.exit(0); }, 700);
"""
r = subprocess.run([node, "-e", js], cwd=str(ROOT), capture_output=True, text=True, timeout=60)
if r.returncode == 2:
    abbruch("jsdom nicht ladbar: " + (r.stdout + r.stderr)[-300:])
try:
    meldungen = json.loads(r.stdout.strip().splitlines()[-1])
except Exception:  # noqa: BLE001
    abbruch("jsdom-Lauf ohne Ergebnis: rc=%s %s" % (r.returncode, (r.stdout + r.stderr)[-400:]))
if not meldungen:
    abbruch("diag.js hat in jsdom gar nichts gesendet – Messaufbau pruefen")
schritte = [m["k"]["schritt"] for m in meldungen]
nach = {m["k"]["schritt"]: m["k"]["detail"] for m in meldungen}
check("alle an /api/addin/diag", all(m["url"] == "/api/addin/diag" for m in meldungen))
check("Schritte nur aus der Serverliste", set(schritte) <= set(d.SCHRITTE), str(schritte))
check("html gemeldet (im Rahmen? referrer, params)",
      "html" in nach and "referrer=mail.firma.local" in nach["html"]
      and "params=mv,_host_Info" in nach["html"], nach.get("html", ""))
check("office_da gemeldet", "office_da" in nach, str(schritte))
check("office_bereit mit host/plattform/diagnostics",
      "office_bereit" in nach and "plattform=OfficeOnline" in nach["office_bereit"]
      and "OutlookWebApp" in nach["office_bereit"], nach.get("office_bereit", ""))
check("mailbox gemeldet", nach.get("mailbox", "") == "mailbox=true item=true", nach.get("mailbox", ""))
fehler = [m["k"]["detail"] for m in meldungen if m["k"]["schritt"] == "fehler"]
check("JS-Fehler gemeldet", any("Boom @ x.js:3:4" in f for f in fehler), str(fehler))
check("CSP-Verstoss gemeldet", any("CSP script-src-elem blockiert https://cdn.beispiel.de/a.js" in f
                                   for f in fehler), str(fehler))
check("nicht ladbares Skript gemeldet (Capture)",
      any(f == "Ressource nicht ladbar: <script> https://appsforoffice.microsoft.com/lib/1/hosted/office.js"
          for f in fehler), str(fehler))
check("Laufkennung je Seite gleich", len({m["k"]["lauf"] for m in meldungen}) == 1)

print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
