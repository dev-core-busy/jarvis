#!/usr/bin/env python3
"""Live auf DEV: GZip fuer statische Inhalte und HTML-Seiten ueber den ECHTEN
HTTPS-Weg (Waechter: test_kompression.py).

Misst je Seite: alle eingebundenen /static/-Dateien mit und ohne
``Accept-Encoding: gzip`` – entpackt byte-gleich, Uebertragung kleiner, und
ein bedingter Abruf (ETag) liefert weiterhin 304 ohne Rumpf. Dazu: eine
angemeldete /api/-Antwort bleibt unkomprimiert, und die HTML-Huelle traegt
nach wie vor die umgeschriebenen ``?v=``-Kennungen (no_cache_static liegt
INNEN und muss den unkomprimierten Rumpf gesehen haben).

Veraendert NICHTS (nur GET). Aufruf auf dem Server:
    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_kompression_dev.py
"""
import gzip
import os
import re
import ssl
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "deploy"))
import ziele  # noqa: E402

BASIS = "https://127.0.0.1"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s%s" % (label, (" – %s" % detail) if detail else ""))


def hole(pfad, gz=True, kopf=None):
    r = urllib.request.Request(BASIS + pfad)
    if gz:
        r.add_header("Accept-Encoding", "gzip")
    for k, v in (kopf or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=30) as a:
            return a.status, {k.lower(): v for k, v in a.headers.items()}, a.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()


summe_roh = summe_gz = 0
for seite in ("/portal", "/wissen", "/settings", "/chat"):
    s, h, b = hole(seite)
    check(s == 200, f"{seite}: 200", s)
    roh = gzip.decompress(b) if h.get("content-encoding") == "gzip" else b
    check(h.get("content-encoding") == "gzip", f"{seite}: HTML gzip", h.get("content-encoding"))
    s2, h2, b2 = hole(seite, gz=False)
    check("content-encoding" not in h2, f"{seite}: ohne Accept-Encoding unkomprimiert")
    # Kennungen der inneren Middleware muessen gleich sein – sonst hat sie
    # einen anderen Rumpf gesehen (ein gepackter Rumpf haette keine ?v= mehr).
    v_gz = sorted(re.findall(rb'\?v=[0-9a-f]{8,}', roh))
    v_roh = sorted(re.findall(rb'\?v=[0-9a-f]{8,}', b2))
    check(len(v_roh) > 5 and v_gz == v_roh, f"{seite}: ?v=-Kennungen identisch ({len(v_roh)})")
    assets = sorted(set(re.findall(r'(?:src|href)="(/static/[^"#]+\.(?:js|css)[^"]*)"', roh.decode())))
    fehler = []
    for a in assets:
        sa, ha, ba = hole(a)
        sr, hr, br = hole(a, gz=False)
        entpackt = gzip.decompress(ba) if ha.get("content-encoding") == "gzip" else ba
        if sa != 200 or entpackt != br:
            fehler.append(a)
        summe_gz += len(ba)
        summe_roh += len(br)
    check(assets and not fehler, f"{seite}: {len(assets)} Assets entpackt byte-gleich", fehler[:3])
    summe_gz += len(b)
    summe_roh += len(b2)

check(summe_gz < summe_roh * 0.4, "Uebertragung insgesamt < 40 % des Originals",
      f"{summe_gz} von {summe_roh}")
print(f"  (4 Seiten samt Assets: {summe_roh // 1024} KB -> {summe_gz // 1024} KB, "
      f"{100 * summe_gz / max(summe_roh, 1):.0f} %)")

# Gefunden 2026-11-16: hinter den inneren Middlewares kam jeder Rumpf
# gestueckelt an – kleine Antworten wurden gepackt, Content-Length fehlte.
s, h, b = hole("/static/js/i18n.js")
check("i18n.js: Content-Length passt zum gepackten Rumpf", h.get("content-length") == str(len(b)),
      (h.get("content-length"), len(b), h.get("transfer-encoding")))
s, h, b = hole("/static/diese-datei-gibt-es-nicht.js")
check("kleine Antwort (404): NICHT gepackt", "content-encoding" not in h, h.get("content-encoding"))

# Bedingter Abruf: ETag + gzip -> 304 ohne Rumpf
s, h, b = hole("/static/js/i18n.js")
etag = h.get("etag")
check(bool(etag) and h.get("content-encoding") == "gzip", "i18n.js: gzip mit ETag", (etag, h.get("content-encoding")))
if etag:
    s3, h3, b3 = hole("/static/js/i18n.js", kopf={"If-None-Match": etag})
    check(s3 == 304 and not b3, "bedingter Abruf: 304 ohne Rumpf", (s3, len(b3)))

# Angemeldete /api/-Antwort bleibt unkomprimiert
from backend import main as M  # noqa: E402
BENUTZER = ziele.wert("JARVIS_DEV_TESTUSER")
if not BENUTZER:
    print("ABBRUCH (Exit 2): JARVIS_DEV_TESTUSER fehlt")
    sys.exit(2)
TOK = M.generate_token(M._display_name(BENUTZER))
s, h, b = hole("/api/wissen/scope", kopf={"Authorization": "Bearer " + TOK})
check(s == 200, "Positivkontrolle: /api/wissen/scope 200 (Token gilt)", s)
check(len(b) > 1024, "Positivkontrolle: Antwort gross genug fuer gzip", len(b))
check("content-encoding" not in h, "/api/-Antwort mit Token: NICHT komprimiert", h.get("content-encoding"))

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(0 if _fail == 0 else 1)
