"""Suche nach einer Kennung in der Paketliste – echter Chrome auf DEV.

Anlass (2026-11-16): die Suche nach CVE-2026-99270 blieb auf ECHT leer, weil
der laufende Kernel die Behebung schon trug; eine leere Liste sah aus wie
„unbekannt". Gemessen wird hier, was jsdom nicht kann: der Kasten erscheint
im ECHTEN Ablauf (Tippen -> Pause -> Abruf -> neu zeichnen), mit echten
Daten des Servers, deckend, ohne Ueberlauf, in beiden Themen.

Lagen, alle gegen den Bestand von DEV (Positivkontrollen VOR den Pruefungen
ueber die API – stimmt die Lage nicht, ist die Probe nicht deutbar, Exit 2):
  - Kennung mit Befund        -> Paketzeile, KEIN Kasten
  - bekannt und behoben       -> Kasten „betrifft dieses System nicht (mehr)"
  - lokal unbekannt, online da -> Kasten „fehlt im lokalen Datenbestand" (OSV)
  - nirgends bekannt          -> Kasten „weder lokal noch online"
Dazu die Rechte: ein Konto ohne Rolle bekommt 403 mit dem Admin-Text, eine
ungueltige Kennung 400. Nur lesend: es wird nichts geprueft, behoben oder
quittiert.

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_cve_kennung_ui_dev.py
"""
import json
import os
import ssl
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

import websocket

sys.path.insert(0, "/opt/jarvis")
sys.argv = ["x"]
import urllib3
urllib3.disable_warnings()
from backend.main import generate_token

TOK = generate_token("jarvis")
TOK_NIEMAND = generate_token("pentest.niemand")
MIT_BEFUND = "CVE-2026-99270"     # DEV: Kernel 6.12.117 installiert, 6.12.116 laeuft
BEHOBEN = "CVE-2024-3094"         # xz-utils, auf trixie laengst behoben
NUR_ONLINE = "GHSA-q675-qj96-32m9"  # OSV kennt sie, der Debian-Tracker fuehrt kein GHSA
UNBEKANNT = "CVE-2099-99999"
ok = fail = 0
ABLAGE = tempfile.mkdtemp(prefix="cve_kennung_ui_", dir=os.path.expanduser("~"))


def check(name, cond, detail=""):
    global ok, fail
    if not isinstance(name, str):
        print("ABBRUCH: check() falsch herum"); sys.exit(2)
    if cond:
        ok += 1; print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1; print("  \033[31m✗\033[0m %s%s" % (name, (" – %s" % detail) if detail else ""))


_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE


def api(k, tok=TOK):
    anf = urllib.request.Request("https://127.0.0.1/api/system/cve/kennung?k=" + k,
                                 headers={"Authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(anf, context=_ctx, timeout=60) as a:
            return a.status, json.loads(a.read())
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except ValueError:
            return e.code, {}


# ── Positivkontrollen: stellt der Bestand die Lagen her? ─────────────────
print("\n\033[1m0. Lage auf DEV (ueber die API)\033[0m")
lage = {}
for k, soll in ((MIT_BEFUND, "betroffen"), (BEHOBEN, "nicht_betroffen"),
                (NUR_ONLINE, "lokal_fehlt"), (UNBEKANNT, "unbekannt")):
    st, d = api(k)
    lage[k] = d
    print("  %s -> %s %s" % (k, st, d.get("urteil")))
    if st != 200 or d.get("urteil") != soll:
        print("ABBRUCH: %s liefert nicht die erwartete Lage (%s) – Probe nicht deutbar" % (k, soll))
        sys.exit(2)
if not lage[MIT_BEFUND].get("befunde"):
    print("ABBRUCH: %s hat auf DEV keinen Befund mehr (Neustart?) – Probe nicht deutbar" % MIT_BEFUND)
    sys.exit(2)

print("\n\033[1m1. Rechte und Eingabe\033[0m")
st, d = api(BEHOBEN, TOK_NIEMAND)
check("ein Konto ohne Rolle bekommt 403", st == 403, st)
check("…und zwar von der Admin-Schranke (Text), nicht von der Anmeldung",
      "Administrator" in json.dumps(d, ensure_ascii=False), d)
st, d = api("CVE-2026-1;rm")
check("ungueltige Kennung: 400 mit Grund", st == 400 and "gültige Kennung" in (d.get("fehler") or ""), (st, d))
on = lage[NUR_ONLINE].get("online") or {}
check("Websuche: OSV kennt die GHSA-Kennung (Datum + Titel)", bool(on.get("veroeffentlicht") and on.get("titel")), on)

PORT, prof = 9343, os.path.join(ABLAGE, "chrome")
p = subprocess.Popen(["google-chrome", "--headless=new", f"--remote-debugging-port={PORT}",
                      f"--user-data-dir={prof}", "--ignore-certificate-errors", "--no-sandbox",
                      "--remote-allow-origins=*", "--window-size=1400,900", "--no-first-run",
                      "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(6)
tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{PORT}/json"))
ws = websocket.create_connection([t for t in tabs if t["type"] == "page"][0]["webSocketDebuggerUrl"])
n = [0]


def cmd(m, params=None):
    n[0] += 1
    ws.send(json.dumps({"id": n[0], "method": m, "params": params or {}}))
    while True:
        d = json.loads(ws.recv())
        if d.get("id") == n[0]:
            return d.get("result", {})


def js(code):
    r = cmd("Runtime.evaluate", {"expression": code, "returnByValue": True, "awaitPromise": True})
    return (r.get("result") or {}).get("value")


def schuss(datei):
    import base64
    r = cmd("Page.captureScreenshot", {"format": "png"})
    if r.get("data"):
        open(os.path.join(ABLAGE, datei), "wb").write(base64.b64decode(r["data"]))


def suche(text, warten=True):
    js("var s=document.getElementById('jv-pkg-suche'); s.value=%s; s.dispatchEvent(new Event('input'));"
       % json.dumps(text))
    if not warten:
        return
    # Tipp-Pause (500 ms) + Abruf: warten, bis der Kasten NICHT mehr laedt.
    for _ in range(60):
        time.sleep(0.5)
        if not js("!!document.querySelector('.jv-pkg-kenn.ist-laedt')"):
            break


def kasten():
    return js("(function(){var k=document.querySelector('.jv-pkg-kenn');"
              "return k ? {text:k.textContent, klasse:k.className} : null;})()")


try:
    for thema in ("dark", "light"):
        print("\n\033[1m2. Thema '%s'\033[0m" % thema)
        cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
        time.sleep(1)
        js("localStorage.setItem('jarvis_token', %s); localStorage.setItem('jarvis_theme', %s);"
           % (json.dumps(TOK), json.dumps(thema)))
        cmd("Page.navigate", {"url": "https://127.0.0.1/portal"})
        time.sleep(5)
        js("document.getElementById('jv-pkg-btn').click()")
        time.sleep(5)
        if not js("document.querySelectorAll('.jv-pkg-tab tbody tr').length > 50"):
            print("ABBRUCH: Paket-Kasten nicht geladen – Probe nicht deutbar")
            sys.exit(2)

        # Lage 1: Befund vorhanden -> Paketzeile, kein Kasten.
        suche(MIT_BEFUND.lower())
        time.sleep(1)
        zeilen = js("Array.from(document.querySelectorAll('.jv-pkg-tab tbody tr')).map(function(r){return r.textContent;})")
        check("[%s] Kennung mit Befund: die Paketzeile erscheint" % thema,
              any("linux-image" in z for z in zeilen or []), (zeilen or [])[:2])
        check("[%s] …mit offenem Befund und seinem Stand" % thema,
              any(MIT_BEFUND in z and "Neustart" in z for z in zeilen or []))
        check("[%s] …und OHNE Auskunftskasten (die Zeile ist die Antwort)" % thema, kasten() is None, kasten())

        # Lage 2: bekannt und behoben.
        suche(BEHOBEN)
        k = kasten() or {}
        check("[%s] behoben: Kasten mit klarer Antwort" % thema,
              "betrifft dieses System nicht (mehr)" in (k.get("text") or ""), (k.get("text") or "")[:160])
        check("[%s] …mit Bearbeitungsstand je Quellpaket" % thema,
              "xz-utils: behoben" in (k.get("text") or ""), (k.get("text") or "")[:240])
        check("[%s] …keine Paketzeilen darunter (die Liste bleibt leer)" % thema,
              js("document.querySelectorAll('.jv-pkg-tab tbody tr').length") == 0)
        masse = js("(function(){var k=document.querySelector('.jv-pkg-kenn'),b=document.querySelector('.jv-pkg-box'),"
                   "s=document.getElementById('jv-pkg-suche'),t=document.querySelector('.jv-pkg-scroll');"
                   "var rk=k.getBoundingClientRect(),rb=b.getBoundingClientRect(),rs=s.getBoundingClientRect(),rt=t.getBoundingClientRect();"
                   "return {imKasten: rk.left>=rb.left && rk.right<=rb.right+1, unterSuche: rk.top>=rs.bottom-1,"
                   "ueberTabelle: rk.bottom<=rt.top+1, quer: b.scrollWidth<=b.clientWidth+1,"
                   "flaeche: getComputedStyle(k).backgroundColor};})()")
        check("[%s] Kasten liegt zwischen Suchfeld und Tabelle, im Rahmen" % thema,
              bool(masse and masse["imKasten"] and masse["unterSuche"] and masse["ueberTabelle"]), masse)
        check("[%s] kein waagerechter Ueberlauf" % thema, bool(masse and masse["quer"]), masse)
        check("[%s] deckende Flaeche" % thema, bool(masse) and "rgba" not in masse["flaeche"], masse)
        check("[%s] das Suchfeld behaelt den Fokus nach dem Neuzeichnen" % thema,
              js("document.activeElement && document.activeElement.id") == "jv-pkg-suche")
        schuss("kennung_behoben_%s.png" % thema)

        # Lage 3: lokal unbekannt, online bekannt (Websuche).
        suche(NUR_ONLINE)
        k = kasten() or {}
        check("[%s] lokal unbekannt: „fehlt im lokalen Datenbestand, ist online aber bekannt“" % thema,
              "fehlt im lokalen Datenbestand" in (k.get("text") or ""), (k.get("text") or "")[:200])
        check("[%s] …mit dem Stand von OSV" % thema, "Online (OSV)" in (k.get("text") or ""))
        check("[%s] …und Verweis auf OSV" % thema,
              js("!!document.querySelector('.jv-pkg-kenn a[href*=\"osv.dev/vulnerability/%s\"]')" % NUR_ONLINE) is True)
        check("[%s] …und „Jetzt prüfen“" % thema,
              js("!!document.querySelector('.jv-pkg-kenn [data-cve-aktion=\"pruefen\"]')") is True)
        schuss("kennung_online_%s.png" % thema)

        # Lage 4: nirgends bekannt.
        suche(UNBEKANNT)
        k = kasten() or {}
        check("[%s] unbekannt: „weder lokal noch online“" % thema,
              "weder lokal noch online" in (k.get("text") or ""), (k.get("text") or "")[:160])

        # Waehrend des Tippens: unvollstaendige Kennung loest nichts aus.
        suche("CVE-2026-9", warten=False)
        time.sleep(1.2)
        check("[%s] unvollstaendige Kennung: kein Kasten" % thema, kasten() is None, kasten())
        suche("", warten=False)
        js("document.querySelector('.jv-pkg-close').click()")
        time.sleep(0.5)
finally:
    try: ws.close()
    except Exception: pass
    p.kill()
    time.sleep(1)
    subprocess.run(["rm", "-rf", prof], check=False)

print("\nBilder: %s" % ABLAGE)
print("\n\033[1m%d OK, %d FAIL\033[0m" % (ok, fail))
sys.exit(1 if fail else 0)
