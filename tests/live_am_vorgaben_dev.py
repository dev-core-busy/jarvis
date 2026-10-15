#!/usr/bin/env python3
"""Live auf DEV: Vorgabe-Fragen über die ECHTEN Endpunkte und den ECHTEN Bestand.

Gemessen wird, was ein Einheitentest nicht kann:
  * greifen die Endpunkte (Routen-Reihenfolge gegen `/api/ai-mouse/fragen`),
  * sind sie wirklich Administratoren vorbehalten,
  * WAS PASSIERT MIT DEM ECHTEN BESTAND – die fünf alten gemeinsamen Fragen
    sollen verschwinden, und ein Benutzer soll die sechs Vorgaben als EIGENE
    bekommen.

⚠ Der VORGEFUNDENE Zustand wird gemessen und berichtet, nicht geraten. Die
   Testbenutzer werden restlos entfernt; an vorhandenen Benutzern wird nichts
   geändert (Register 2026-09-09).

Aufruf: cd /opt/jarvis && ./venv/bin/python tests/live_am_vorgaben_dev.py
"""
import json
import ssl
import sys
import urllib.error
import urllib.request

sys.path.insert(0, "/opt/jarvis")

BASIS = "https://127.0.0.1"
_ctx = ssl.create_default_context()
_ctx.check_hostname = False
_ctx.verify_mode = ssl.CERT_NONE
_ok = _fail = 0


def check(text, bed, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f"  [{info}]" if info else ""))


def ruf(pfad, methode="GET", rumpf=None, token=None):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    if daten is not None:
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, context=_ctx, timeout=25) as a:
            roh = a.read().decode("utf-8", "replace")
            try:
                return a.status, json.loads(roh)
            except Exception:  # noqa: BLE001
                return a.status, roh
    except urllib.error.HTTPError as e:
        roh = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(roh)
        except Exception:  # noqa: BLE001
            return e.code, roh


print("=" * 74)
print("LIVE auf DEV: Vorgabe-Fragen der AI-Maus")
print("=" * 74)

from backend import main as bm            # noqa: E402
from backend import ai_mouse_fragen as amf  # noqa: E402

U = "jarvis"
TOKEN = bm.generate_token(U)

# ── Der Bestand VOR dem Eingriff ────────────────────────────────────────────
d = amf._laden()
print("  vorgefunden: %d gemeinsame · %d Benutzer · Raeum-Marker=%s"
      % (len(d.get("global_") or []), len(d.get("benutzer") or {}),
         d.get("_global_geraeumt")))

# ── Endpunkte ───────────────────────────────────────────────────────────────
st, dd = ruf("/api/ai-mouse/admin/vorgaben", token=TOKEN)
check("Vorgaben-Endpunkt erreichbar (nicht von /fragen gefangen)",
      st == 200 and isinstance(dd, dict) and "vorgaben" in dd, f"{st} {str(dd)[:90]}")
vorg = dd.get("vorgaben") or []
SOLL = ["Text erkennen (OCR)", "extrahiere Adressdaten (OCR)", "was ist das ?",
        "Tabelle zusammenfassen", "suche homepage", "übersetze nach Deutsch"]
check("die sechs vorgegebenen Eintraege stehen da (Reihenfolge inbegriffen)",
      [v["titel"] for v in vorg] == SOLL, str([v["titel"] for v in vorg]))
lang = next((v for v in vorg if v["titel"] == "extrahiere Adressdaten (OCR)"), {})
check("der lange Adress-Prompt ist vollstaendig angekommen",
      "strukturierten Daten zurück" in lang.get("prompt", ""),
      str(len(lang.get("prompt", ""))))

st, _ = ruf("/api/ai-mouse/admin/vorgaben")
check("ohne Token: 401", st == 401, str(st))
st, _ = ruf("/api/ai-mouse/admin/vorgaben", "POST", {"titel": "X", "prompt": "Y"})
check("ohne Token wird auch nicht geschrieben (401)", st == 401, str(st))
NICHT_ADMIN = bm.generate_token("kein.admin.hier")
st, _ = ruf("/api/ai-mouse/admin/vorgaben", token=NICHT_ADMIN)
check("ein nicht berechtigter Benutzer wird abgewiesen", st in (401, 403), str(st))

st, dd = ruf("/api/ai-mouse/admin/vorgaben/gibtsnicht", "DELETE", token=TOKEN)
check("unbekannte Vorgabe: 404", st == 404, str(st))

# ── Der Altbestand ist geraeumt ─────────────────────────────────────────────
d = amf._laden()
check("⚠ die alten gemeinsamen Fragen sind weg (Vorgabe des Betreibers)",
      not (d.get("global_") or []), str([e.get("titel") for e in d.get("global_") or []]))
check("und der Raeum-Marker steht (eine neue gemeinsame Frage ueberlebt)",
      d.get("_global_geraeumt") is True)

# ── Was ein neuer Benutzer bekommt ──────────────────────────────────────────
PROBE = "live.probe.vorgaben"
try:
    fragen = amf.liste(PROBE)
    check("ein neuer Benutzer bekommt genau die sechs", len(fragen) == 6, str(len(fragen)))
    check("⚠ als EIGENE (anpassbar), nicht als gemeinsame",
          all((not f["gemeinsam"]) and f["darf_aendern"] for f in fragen))
    check("mit eigenen Kennungen",
          not ({f["id"] for f in fragen} & {v["id"] for v in vorg}))

    # Er darf sie anpassen – das ist die Zusage.
    erste = fragen[0] if fragen else {}
    amf.speichern(PROBE, erste.get("id", ""), "Von mir geaendert", "Mein Text")
    check("er darf eine Vorgabe aendern",
          "Von mir geaendert" in [f["titel"] for f in amf.liste(PROBE)])

    # Und Geloeschtes kommt nicht zurueck.
    for f in amf.liste(PROBE):
        amf.loeschen(PROBE, f["id"])
    check("⚠ nach dem Loeschen bleibt die Liste leer", amf.liste(PROBE) == [])
finally:
    dd = amf._laden()
    dd.get("benutzer", {}).pop(amf._norm(PROBE), None)
    g = dd.get("gesaet_fuer")
    if isinstance(g, list) and amf._norm(PROBE) in g:
        g.remove(amf._norm(PROBE))
    amf._speichern(dd)
    check("Testbenutzer restlos entfernt",
          amf._norm(PROBE) not in (amf._laden().get("benutzer") or {}))

# ── Pflege ueber den Endpunkt, danach zurueckbauen ──────────────────────────
st, dd = ruf("/api/ai-mouse/admin/vorgaben", "POST",
             {"titel": "LIVE Probe-Vorgabe", "prompt": "Nur fuer die Messung."}, TOKEN)
neu_id = (dd or {}).get("vorgabe", {}).get("id", "")
check("Vorgabe anlegen gelingt", st == 200 and bool(neu_id), f"{st} {str(dd)[:80]}")
st, dd = ruf("/api/ai-mouse/admin/vorgaben", "POST",
             {"id": neu_id, "titel": "LIVE geaendert", "prompt": "Neu."}, TOKEN)
check("aendern behaelt die Kennung",
      st == 200 and (dd or {}).get("vorgabe", {}).get("id") == neu_id)
st, _ = ruf("/api/ai-mouse/admin/vorgaben/" + neu_id, "DELETE", token=TOKEN)
check("und entfernen gelingt", st == 200)
st, dd = ruf("/api/ai-mouse/admin/vorgaben", token=TOKEN)
check("⚠ der Ausgangszustand ist wiederhergestellt (wieder genau die sechs)",
      [v["titel"] for v in (dd.get("vorgaben") or [])] == SOLL,
      str([v["titel"] for v in (dd.get("vorgaben") or [])]))

st, dd = ruf("/api/ai-mouse/admin/vorgaben", "POST", {"titel": "  ", "prompt": "x"}, TOKEN)
check("leerer Titel: 400 mit Grund", st == 400 and "Titel" in str(dd), f"{st} {str(dd)[:80]}")

print("\n" + "=" * 74)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
print("=" * 74)
sys.exit(1 if _fail else 0)
