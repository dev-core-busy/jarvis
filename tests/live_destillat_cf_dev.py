#!/usr/bin/env python3
"""Live-Probe auf DEV: Destillat -> neue Confluence-Seite (Ablehnungspfade).

⚠ ES WIRD KEINE SEITE ANGELEGT, und das ist Absicht: ein `create_page` traefe
das ECHTE Firmen-Confluence – eine Schreibaktion in einem fremden Produktiv-
system gehoert nicht in eine Messung, die niemand ausdruecklich freigegeben
hat. Gemessen wird deshalb alles, was OHNE Schreibzugriff messbar ist:

  * die Rechte- und Sichtbarkeitsschranken des Endpunkts (401/403/400)
  * dass nach jedem Fehlversuch nachweislich NICHTS entstanden ist
    (Seitenzahl des Zielbereichs vorher == nachher)
  * der Konverter gegen ein ECHTES Destillat-Markdown im Produktiv-venv

Laeuft AUF DEV (`python3 tests/live_destillat_cf_dev.py`), nicht von aussen.
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")
BASIS = "https://127.0.0.1"
_KTX = ssl._create_unverified_context()
_ok = _fail = 0


def check(text, bedingung, info=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print("  OK   %s" % text)
    else:
        _fail += 1
        print("  FAIL %s%s" % (text, ("  [%s]" % info) if info else ""))


from backend import main as M                                      # noqa: E402
from backend import wissen_destillat as WD                         # noqa: E402

BENUTZER = os.environ.get("DESTCF_TESTUSER") or "jarvis"
TOKEN = M.generate_token(BENUTZER)
if not M._editable_groups_for(BENUTZER):
    print("ABBRUCH: %r hat keinen Wissensbereich – die Messung waere trivial wahr."
          % BENUTZER)
    sys.exit(2)


def ruf(pfad, methode="GET", rumpf=None, token=TOKEN):
    daten = None if rumpf is None else json.dumps(rumpf).encode()
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if daten:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=120) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:  # noqa: BLE001
            return e.code, {}


MD = "# Probe Destillat\n\nEin **fetter** Satz.\n\n- eins\n- zwei\n"
EP = "/api/wissen/destillat/confluence"

print("\n\033[1m1. Voraussetzungen (ohne sie ist alles darunter trivial wahr)\033[0m")
st, d = ruf("/api/wissen/confluence/spaces")
check("Bereichsliste abrufbar", st == 200 and d.get("ok"), f"{st} {str(d)[:120]}")
SPACES = [s.get("key") for s in (d.get("spaces") or []) if s.get("key")]
check("mindestens ein sichtbarer Bereich", len(SPACES) > 0, str(len(SPACES)))
if not SPACES:
    print("ABBRUCH: kein sichtbarer Bereich – die Schranken waeren nicht pruefbar.")
    sys.exit(2)
ZIEL = SPACES[0]
print("     Zielbereich fuer die Messung: %s (von %d sichtbaren)" % (ZIEL, len(SPACES)))

st, d = ruf("/api/wissen/confluence/pages?space=" + ZIEL)
check("Seitenliste des Zielbereichs abrufbar", st == 200 and d.get("ok"),
      f"{st} {str(d)[:120]}")
SEITEN_VORHER = len(d.get("pages") or [])
IDS_VORHER = {str(p.get("id")) for p in (d.get("pages") or [])}
print("     Seiten im Bereich vorher: %d" % SEITEN_VORHER)

print("\n\033[1m2. Rechte und Eingabe – jeder Fehlversuch muss abgewiesen werden\033[0m")
st, d = ruf(EP, "POST", {"markdown": MD, "space": ZIEL, "titel": "X"}, token=None)
check("ohne Token: 401", st == 401, str(st))
st, d = ruf(EP, "POST", {"markdown": MD, "space": ZIEL, "titel": "X"}, token="muell")
check("mit Muell-Token: 401", st == 401, str(st))

st, d = ruf(EP, "POST", {"space": ZIEL, "titel": "X"})
check("ohne Markdown: 400", st == 400, f"{st} {str(d)[:120]}")
check("… und der Grund nennt das fehlende Destillat",
      "Destillat" in str(d.get("error") or ""), str(d.get("error")))

st, d = ruf(EP, "POST", {"markdown": MD, "titel": "X"})
check("ohne Bereich: 400", st == 400, f"{st} {str(d)[:120]}")
check("… und der Grund nennt den BEREICH",
      "Bereich" in str(d.get("error") or ""), str(d.get("error")))

st, d = ruf(EP, "POST", {"markdown": MD, "space": ZIEL})
check("ohne Titel: 400", st == 400, f"{st} {str(d)[:120]}")
# Gross/klein egal: die Meldung sagt "Seitentitel", nicht "Titel".
check("… und der Grund nennt den TITEL",
      "titel" in str(d.get("error") or "").lower(), str(d.get("error")))
st, d = ruf(EP, "POST", {"markdown": MD, "space": ZIEL, "titel": "   "})
check("Titel nur aus Leerraum: 400 (nicht als Rechteproblem)", st == 400,
      f"{st} {str(d)[:120]}")

# ⚠ ABGEWIESEN, NICHT GEKUERZT: ein gekuerzter Titel ist ein ANDERER Titel.
st, d = ruf(EP, "POST", {"markdown": MD, "space": ZIEL,
                         "titel": "T" * (WD.TITEL_MAX + 1)})
check("zu langer Titel: 400 statt stiller Kuerzung", st == 400, f"{st} {str(d)[:120]}")
check("… und der Grund nennt die Grenze",
      str(WD.TITEL_MAX) in str(d.get("error") or ""), str(d.get("error")))

print("\n\033[1m3. Sichtbarkeit – der Bereich muss dem Token gehoeren\033[0m")
st, d = ruf(EP, "POST", {"markdown": MD, "space": "GIBTESNICHT42",
                         "titel": "Probe nicht anlegen"})
check("unsichtbarer Bereich: 403", st == 403, f"{st} {str(d)[:120]}")
check("… und der Grund nennt die Sichtbarkeit",
      "sichtbar" in str(d.get("error") or "").lower(), str(d.get("error")))

# Elternseite aus einem FREMDEN Bereich (falls es einen zweiten gibt).
fremd = None
for k in SPACES[1:]:
    s2, d2 = ruf("/api/wissen/confluence/pages?space=" + k)
    if s2 == 200 and (d2.get("pages") or []):
        fremd = str(d2["pages"][0]["id"])
        break
if fremd:
    st, d = ruf(EP, "POST", {"markdown": MD, "space": ZIEL, "parent": fremd,
                             "titel": "Probe nicht anlegen"})
    check("Elternseite aus einem FREMDEN Bereich: 403", st == 403,
          f"{st} {str(d)[:120]}")
else:
    print("  ----  kein zweiter Bereich mit Seiten – Fremd-Eltern NICHT geprueft")

print("\n\033[1m4. Nach allen Fehlversuchen ist NICHTS entstanden\033[0m")
st, d = ruf("/api/wissen/confluence/pages?space=" + ZIEL)
IDS_NACHHER = {str(p.get("id")) for p in (d.get("pages") or [])}
check("Seitenzahl des Zielbereichs unveraendert",
      len(IDS_NACHHER) == SEITEN_VORHER,
      f"{SEITEN_VORHER} -> {len(IDS_NACHHER)}")
check("keine neue Seiten-ID im Bereich", IDS_NACHHER == IDS_VORHER,
      str(sorted(IDS_NACHHER - IDS_VORHER))[:120])

print("\n\033[1m5. Der Konverter im PRODUKTIV-venv\033[0m")
storage = WD.storage_aus_markdown(MD, [])
check("es kommt HTML heraus, kein Markdown",
      "<h1>" in storage and "<strong>" in storage and "# Probe" not in storage,
      storage[:120])
import xml.etree.ElementTree as ET
try:
    ET.fromstring('<r xmlns:ac="a" xmlns:ri="b">' + storage + "</r>")
    wohl = True
except Exception as e:  # noqa: BLE001
    wohl = False
    print("     %s" % e)
check("der Rumpf ist wohlgeformtes XML (sonst weist Confluence ihn ab)", wohl)
check("der Client kann Anhaenge aus dem Speicher laden",
      hasattr(M._confluence_client(), "upload_attachment_bytes"))

print("\n\033[1mErgebnis: %d/%d\033[0m" % (_ok, _ok + _fail))
sys.exit(1 if _fail else 0)
