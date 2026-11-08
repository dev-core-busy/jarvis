#!/usr/bin/env python3
"""Waechter: CSP-Nachschaerfung vor dem Pentest (2026-11-05), backend/csp.py.

  D3  img-src ohne ``https:`` – ein fremdes Markdown-Bild darf nicht laden
      (Datenabfluss ohne Klick). Ausnahme nur Add-in-Seiten (office.js).
  D4  frame-src ohne ``data:`` (Phishing-Rahmen); /novnc/ bekommt eine EIGENE
      Richtlinie statt gar keiner: nur eigene Skripte + die Hashes genau der
      Inline-Skripte des installierten Pakets.
  D5  CSP-Meldungen: nur Berichte, deren Seite auf dem angefragten Host liegt;
      Hosts ausserhalb der eigenen Namen haben ein eigenes, kleines Kontingent
      und koennen das der echten Meldungen nicht aufbrauchen.

Gemessen wird die WIRKUNG am echten Modul (Richtlinie zerlegt, Meldungen in
einen Sandkasten geschrieben); die Einbindung in main.py am Syntaxbaum.
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht messen.
"""
import ast
import base64
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.dont_write_bytecode = True
ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print(f"  OK   {name}")
    else:
        fail += 1
        print(f"  FAIL {name}" + (f"  -> {detail}" if detail else ""))


try:
    from backend import csp
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: backend.csp laedt nicht: {e!r}")
    sys.exit(2)

csp.einstellungen_quelle(lambda k, d=None: "erzwingen" if k == "csp_modus" else d)


def direktiven(text):
    aus = {}
    for teil in str(text or "").split(";"):
        w = teil.split()
        if w:
            aus[w[0]] = w[1:]
    return aus


chat = direktiven(csp.richtlinie("/chat", "jarvis.beispiel.de"))
addin = direktiven(csp.richtlinie("/addin/taskpane.html", "jarvis.beispiel.de"))
if not chat.get("img-src") or not addin.get("script-src"):
    print("ABBRUCH: Richtlinie liess sich nicht zerlegen")
    sys.exit(2)

print("── D3 img-src ──")
check("Chat: img-src = 'self' data: blob:", chat["img-src"] == ["'self'", "data:", "blob:"], str(chat["img-src"]))
check("Chat: kein https: / * in img-src", not any(x in ("https:", "http:", "*") for x in chat["img-src"]))
for pfad in ("/wissen", "/support", "/static/email.html", "/tracks", "/userchat", "/portal"):
    d = direktiven(csp.richtlinie(pfad, ""))
    check(f"{pfad}: kein https: in img-src", "https:" not in d.get("img-src", ["https:"]))
check("Add-in: img-src behaelt https: (benannte Ausnahme)", "https:" in addin.get("img-src", []))

print("── D4 frame-src / noVNC ──")
for name, d in (("Chat", chat), ("Add-in", addin)):
    check(f"{name}: kein data: in frame-src", "data:" not in d.get("frame-src", ["data:"]),
          str(d.get("frame-src")))
check("Chat: frame-src erlaubt weiter 'self' blob: (Vorschauen)",
      d is not None and chat.get("frame-src", [])[:2] == ["'self'", "blob:"])

with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    inline = "\n        import UI from './app/ui.js';\n        UI.start();\n    "
    (t / "vnc.html").write_text(
        "<html><head><script type=\"module\" src=\"app/e.js\"></script>"
        f"<script type=\"module\">{inline}</script></head><body></body></html>", encoding="utf-8")
    erwartet = "'sha256-%s'" % base64.b64encode(hashlib.sha256(inline.encode()).digest()).decode()
    csp.novnc_ordner(t)
    k = csp.kopfzeilen("/novnc/vnc.html", "jarvis.beispiel.de:443")
    nv = direktiven(k.get("Content-Security-Policy", ""))
    # Kein Abbruch: "keine Richtlinie" ist genau der Altzustand, also ein Befund.
    check("noVNC: /novnc/ bekommt im Modus erzwingen eine Richtlinie", bool(nv), str(k))
    check("noVNC: Hash des Inline-Skripts steht in script-src", erwartet in nv.get("script-src", []),
          str(nv.get("script-src")))
    check("noVNC: kein 'unsafe-inline' fuer Skripte, wenn lesbar",
          "'unsafe-inline'" not in nv.get("script-src", []))
    check("noVNC: script-src nur 'self' + Hashes",
          all(x == "'self'" or x.startswith("'sha256-") for x in nv.get("script-src", [])))
    check("noVNC: kein 'unsafe-eval'", "'unsafe-eval'" not in " ".join(sum(nv.values(), [])))
    check("noVNC: WebSocket zum eigenen Host", "wss://jarvis.beispiel.de:443" in nv.get("connect-src", []))
    check("noVNC: frame-ancestors nur 'self'", nv.get("frame-ancestors") == ["'self'"])
    check("noVNC: object-src 'none'", nv.get("object-src") == ["'none'"])
    check("noVNC: img-src ohne https:", "https:" not in nv.get("img-src", ["https:"]))
    # Paket-Update: anderer Inhalt -> anderer Hash (Cache je mtime/Groesse)
    (t / "vnc.html").write_text("<script>neu();;</script>", encoding="utf-8")
    nv2 = direktiven(csp.kopfzeilen("/novnc/vnc.html").get("Content-Security-Policy", ""))
    check("noVNC: geaendertes Paket -> neuer Hash, alter weg",
          erwartet not in nv2.get("script-src", []) and len(nv2.get("script-src", [])) == 2,
          str(nv2.get("script-src")))
csp.novnc_ordner(Path(tmp) / "fehlt")
nv3 = direktiven(csp.kopfzeilen("/novnc/vnc.html").get("Content-Security-Policy", ""))
check("noVNC: Paket unlesbar -> Rueckfall 'unsafe-inline', fremde Hosts trotzdem nicht",
      nv3.get("script-src") == ["'self'", "'unsafe-inline'"], str(nv3.get("script-src")))
check("/novnc-x ist NICHT noVNC (allgemeine Richtlinie)",
      "frame-src 'none'" not in str(csp.kopfzeilen("/novnc-x")))
check("/novnc/../portal.html ist NICHT noVNC",
      "frame-src 'none'" not in str(csp.kopfzeilen("/novnc/../portal.html")))
csp.novnc_ordner(None)

print("── D5 Meldungen ──")


def bericht(seite):
    return json.dumps({"csp-report": {"document-uri": seite, "violated-directive": "img-src",
                                      "blocked-uri": "https://x.beispiel.de/a.png"}}).encode()


with tempfile.TemporaryDirectory() as tmp:
    csp._ordner = lambda: Path(tmp)
    for d in (csp._gesehen, csp._gesehen_tag, csp._rate, csp._tag_zeilen, csp._tag_fremd):
        d.clear()
    csp.eigene_namen_quelle(lambda: ["jarvis.beispiel.de", "*.intern.beispiel.de"])
    # Positivkontrolle: ein echter Bericht wird geschrieben
    if csp.melden(bericht("https://jarvis.beispiel.de/chat"), "192.0.2.1", "", host="jarvis.beispiel.de:443") != 1:
        print("ABBRUCH: Positivkontrolle – echter Bericht wird nicht geschrieben")
        sys.exit(2)
    check("Seite auf fremdem Host -> verworfen",
          csp.melden(bericht("https://boese.beispiel.org/x"), "192.0.2.2", "", host="jarvis.beispiel.de") == 0)
    check("ohne Host-Kopf -> verworfen",
          csp.melden(bericht("https://jarvis.beispiel.de/y"), "192.0.2.3", "", host="") == 0)
    check("Platzhalter-Name aus dem Zertifikat gilt als eigen",
          csp.herkunft("https://a.intern.beispiel.de/z", "a.intern.beispiel.de") == "eigen")
    check("Platzhalter deckt nur EINE Ebene",
          csp.herkunft("https://a.b.intern.beispiel.de/z", "a.b.intern.beispiel.de") == "fremd")
    # Flut ueber einen nicht eigenen Host (z. B. untergeschobener Host-Kopf)
    n_fremd = 0
    for i in range(csp.TAG_MAX_FREMD * 3):
        csp._rate.clear()
        n_fremd += csp.melden(bericht("https://192.0.2.50/f%d" % i), "198.51.100.%d" % (i % 250), "",
                              host="192.0.2.50")
    check(f"fremder Host: hoechstens TAG_MAX_FREMD ({csp.TAG_MAX_FREMD}) am Tag, gemessen {n_fremd}",
          0 < n_fremd <= csp.TAG_MAX_FREMD)
    check("TAG_MAX_FREMD ist ein Bruchteil (<= 1/10) des Tageskontingents",
          csp.TAG_MAX_FREMD * 10 <= csp.TAG_MAX_ZEILEN)
    csp._rate.clear()
    check("nach der fremden Flut wird ein eigener Bericht weiter geschrieben",
          csp.melden(bericht("https://jarvis.beispiel.de/danach"), "192.0.2.9", "",
                     host="jarvis.beispiel.de") == 1)
    csp.eigene_namen_quelle(lambda: [])
    check("ohne bekannte eigene Namen: passender Host gilt als eigen (Diagnose bleibt)",
          csp.herkunft("https://192.0.2.50/x", "192.0.2.50:443") == "eigen")
    csp.eigene_namen_quelle(None)

print("── Einbindung main.py ──")
MAIN = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))


def aufrufe(name):
    return [n for n in ast.walk(MAIN) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == name
            and getattr(n.func.value, "id", "") == "_csp"]


mel = aufrufe("melden")
check("_csp.melden bekommt host= aus dem Host-Kopf",
      len(mel) == 1 and any(k.arg == "host" and "host" in ast.unparse(k.value) for k in mel[0].keywords))
check("_csp.eigene_namen_quelle wird gesetzt", len(aufrufe("eigene_namen_quelle")) == 1)
nv_calls = aufrufe("novnc_ordner")
mount_ok = False
for n in ast.walk(MAIN):
    if isinstance(n, ast.For) and "_NOVNC_DIRS" in ast.unparse(n.iter):
        src = ast.unparse(n)
        mount_ok = "app.mount('/novnc'" in src and "_csp.novnc_ordner(_nvdir)" in src
check("noVNC-Ordner wird im selben Zweig wie app.mount an die CSP gegeben",
      len(nv_calls) == 1 and mount_ok)

print(f"\nBilanz: {ok} OK, {fail} FAIL")
sys.exit(0 if fail == 0 else 1)
