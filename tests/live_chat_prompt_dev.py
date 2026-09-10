#!/usr/bin/env python3
"""Live auf DEV: Prompt fuer EINEN Chat ueber die ECHTEN Endpunkte.

Gemessen wird, was ein Einheitentest NICHT beantworten kann:
  * ist die Route ueberhaupt erreichbar (Routen-Reihenfolge gegen
    `/api/chat/sessions/{sid}`, das den Pfad sonst faengt),
  * antwortet sie ohne Anmeldung mit 401 und bei fremder Sitzung mit 404,
  * landet der Text wirklich in der meta.json der Sitzung – und NUR dort,
  * meldet die Sitzungsliste danach `has_prompt`.

⚠ AUFGERAEUMT WIRD DER VORGEFUNDENE ZUSTAND, nicht ein geratener: die
   Testsitzungen werden am Ende geloescht; an vorhandenen Chats wird NICHTS
   angefasst (Register 2026-09-09).

Aufruf auf DEV im Produktiv-venv:
    cd /opt/jarvis && ./venv/bin/python tests/live_chat_prompt_dev.py
"""
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path

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
    """(status, json|text)."""
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
print("LIVE auf DEV: Prompt fuer EINEN Chat")
print("=" * 74)

# Token wie der Endpunkt es nach erfolgreicher Anmeldung ausstellt. /api/login
# laeuft gegen PAM und ist von der Kommandozeile nicht bedienbar (Register).
from backend import main as bm  # noqa: E402

U = "jarvis"
TOKEN = bm.generate_token(U)
FREMD = bm.generate_token("ein.anderer")

st, d = ruf("/api/chat/sessions", token=TOKEN)
check("angemeldet: Sitzungsliste erreichbar", st == 200 and isinstance(d, dict) and d.get("ok"),
      f"{st} {str(d)[:80]}")
vorher = {s["id"] for s in (d.get("sessions") or [])} if isinstance(d, dict) else set()
print(f"       (vorgefunden: {len(vorher)} Chats – sie werden nicht angefasst)")

st, d = ruf("/api/chat/sessions", "POST", {"title": "LIVE Prompt-Probe"}, TOKEN)
SID = (d or {}).get("session", {}).get("id") if isinstance(d, dict) else None
check("Testsitzung angelegt", bool(SID), f"{st} {str(d)[:80]}")
if not SID:
    print("ABBRUCH: ohne Sitzung ist nichts messbar.")
    sys.exit(2)

# ── Routen-Reihenfolge: der Pfad darf NICHT von /api/chat/sessions/{sid}
#    gefangen werden (dort kaeme eine Antwort mit `transcript` heraus).
st, d = ruf(f"/api/chat/sessions/{SID}/preprompt", token=TOKEN)
check("⚠ die Route ist erreichbar und wird nicht von /{sid} gefangen",
      st == 200 and isinstance(d, dict) and "preprompt" in d and "transcript" not in d,
      f"{st} {str(d)[:100]}")
check("frische Sitzung: leerer Prompt", d.get("preprompt") == "")

# ── Rundlauf
TEXT = "LIVE-PROBE: antworte in diesem Chat ausschliesslich auf Englisch."
st, d = ruf(f"/api/chat/sessions/{SID}/preprompt", "PUT", {"preprompt": TEXT}, TOKEN)
check("Speichern liefert den Text und has_prompt zurueck",
      st == 200 and d.get("preprompt") == TEXT and d.get("has_prompt") is True,
      f"{st} {str(d)[:120]}")

st, d = ruf(f"/api/chat/sessions/{SID}/preprompt", token=TOKEN)
check("Lesen liefert byte-gleich denselben Text", d.get("preprompt") == TEXT)

st, d = ruf("/api/chat/sessions", token=TOKEN)
eintrag = next((s for s in d.get("sessions", []) if s["id"] == SID), {})
check("die Sitzungsliste meldet has_prompt=True", eintrag.get("has_prompt") is True,
      str(eintrag))
check("⚠ und sie enthaelt den TEXT nirgends",
      TEXT not in json.dumps(d, ensure_ascii=False))

st, d = ruf(f"/api/chat/sessions/{SID}", token=TOKEN)
check("der Einzelabruf meldet has_prompt, gibt den Text aber nicht heraus",
      d.get("has_prompt") is True and TEXT not in json.dumps(d, ensure_ascii=False))

# ── Auf der PLATTE: liegt er wirklich an der Sitzung?
from backend import chat_sessions as cs  # noqa: E402
meta = json.loads((Path(cs._sess_dir(U, SID)) / "meta.json").read_text(encoding="utf-8"))
check("er steht in der meta.json GENAU DIESER Sitzung", meta.get("preprompt") == TEXT)
check("der Titel der Sitzung ist unangetastet", meta.get("title") == "LIVE Prompt-Probe")

# ── Der persoenliche Preprompt des Benutzers bleibt unberuehrt
pp_vor = cs.get_preprompt(U)
check("der persoenliche Preprompt wurde NICHT angefasst", cs.get_preprompt(U) == pp_vor)

# ── Rechte
st, _ = ruf(f"/api/chat/sessions/{SID}/preprompt")
check("ohne Token: 401", st == 401, str(st))
st, _ = ruf(f"/api/chat/sessions/{SID}/preprompt", "PUT", {"preprompt": "X"})
check("ohne Token wird auch nicht geschrieben (401)", st == 401, str(st))
# ⚠ EIN NICHT ANMELDEBERECHTIGTER BENUTZER BEWEIST HIER NICHTS: auf DEV gilt
#    "leer = niemand", `require_auth` weist ihn schon vor dem Endpunkt mit 403
#    ab. Gemessen wird deshalb nur, DASS er abgewiesen wird und nichts schreibt –
#    die Zugehoerigkeits-Schranke selbst kommt eine Zeile weiter.
st, d = ruf(f"/api/chat/sessions/{SID}/preprompt", "PUT",
            {"preprompt": "GEKAPERT", "user": U, "username": U}, FREMD)
check("ein nicht freigegebener Benutzer wird abgewiesen (401/403 von require_auth)",
      st in (401, 403), f"{st} {str(d)[:80]}")
check("und hat dabei nichts geschrieben", cs.get_session_preprompt(U, SID) == TEXT)

# DIE EIGENTLICHE SCHRANKE: eine Sitzung, die einem ANDEREN Benutzer gehoert,
# ist ueber die Kennung nicht erreichbar – auch nicht mit gueltiger Anmeldung.
# Sie wird auf Dateiebene angelegt, weil dafuer keine zweite Anmeldung noetig
# ist (und die auf DEV nicht herstellbar waere).
FREMD_U = "pruef.fremd.live"
fs = cs.create_session(FREMD_U, "Fremder Chat")
cs.save_session_preprompt(FREMD_U, fs["id"], "FREMDER PROMPT")
try:
    st, d = ruf(f"/api/chat/sessions/{fs['id']}/preprompt", token=TOKEN)
    check("⚠ FREMDE Sitzung: 404 – und kein Wort ihres Inhalts",
          st == 404 and "FREMDER PROMPT" not in json.dumps(d, ensure_ascii=False),
          f"{st} {str(d)[:80]}")
    st, d = ruf(f"/api/chat/sessions/{fs['id']}/preprompt", "PUT",
                {"preprompt": "GEKAPERT"}, TOKEN)
    check("⚠ und sie ist auch nicht beschreibbar", st == 404, f"{st} {str(d)[:80]}")
    check("der fremde Prompt ist unveraendert",
          cs.get_session_preprompt(FREMD_U, fs["id"]) == "FREMDER PROMPT")
finally:
    # Der Testbenutzer wird restlos entfernt – er ist nur fuer diese Messung
    # entstanden.
    import shutil
    shutil.rmtree(cs._user_dir(FREMD_U), ignore_errors=True)
    check("Testbenutzer restlos entfernt", not cs._user_dir(FREMD_U).exists())

st, d = ruf("/api/chat/sessions/gibtsnicht/preprompt", token=TOKEN)
check("unbekannte Sitzung: 404", st == 404, str(st))

# ── Deckel + Entfernen
st, d = ruf(f"/api/chat/sessions/{SID}/preprompt", "PUT", {"preprompt": "y" * 9000}, TOKEN)
check(f"Deckel greift ({cs._PREPROMPT_MAX})", len(d.get("preprompt", "")) == cs._PREPROMPT_MAX,
      str(len(d.get("preprompt", ""))))
st, d = ruf(f"/api/chat/sessions/{SID}/preprompt", "PUT", {"preprompt": "  "}, TOKEN)
check("leerer Text entfernt ihn (has_prompt=False)",
      d.get("preprompt") == "" and d.get("has_prompt") is False, str(d))
meta = json.loads((Path(cs._sess_dir(U, SID)) / "meta.json").read_text(encoding="utf-8"))
check("und der Schluessel ist aus der meta.json verschwunden", "preprompt" not in meta)

# ── Aufraeumen: NUR die eigene Testsitzung
st, _ = ruf(f"/api/chat/sessions/{SID}", "DELETE", token=TOKEN)
st, d = ruf("/api/chat/sessions", token=TOKEN)
nachher = {s["id"] for s in d.get("sessions", [])}
check("Testsitzung entfernt", SID not in nachher)
check("⚠ der vorgefundene Bestand ist unveraendert",
      vorher.issubset(nachher) and (nachher - vorher) == set(),
      f"vorher={len(vorher)} nachher={len(nachher)}")

print("\n" + "=" * 74)
print(f"Ergebnis: {_ok} OK, {_fail} FAIL")
print("=" * 74)
sys.exit(1 if _fail else 0)
