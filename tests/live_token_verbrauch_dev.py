#!/usr/bin/env python3
"""LIVE auf DEV: kommt ein ECHTER Modellaufruf in der Token-Statistik an?

Drei Wege, jeder mit eigener Aussage:

1. Ein echter Aufruf ueber das aktive Profil (``llm.provider_fuer_lauf``) aus
   einem Aufrufer mit Modulnamen ``backend.prompt_check`` – misst die
   Umhuellung der ECHTEN Provider-Klasse und die Form der ECHTEN
   usage-Antwort des Anbieters (Tokens > 0, Dienst richtig).
2. Ein Aufruf IM laufenden Dienst ueber HTTP (``POST /api/prompt/pruefen``) –
   misst, dass der Dienstprozess selbst erfasst, samt Benutzer aus der Sitzung.
   Ist das Messkonto fuer Short Tracks nicht freigegeben, wird das als
   „nicht messbar" ausgewiesen, nicht als Fehler – die Freigabe wird NICHT
   umgestellt (Register: kein Eingriff in eine Rechte-Einstellung fuer eine
   Messung).
3. ``GET /api/logs/token_verbrauch`` im Dienst zeigt die neuen Zeilen; ein
   Konto ohne jede Rolle bekommt 403 mit dem Text der Admin-Schranke.

Es entstehen nur Zeilen in data/logs/token (Statistik, keine Inhalte) – sie
sind echte Modellaufrufe und bleiben stehen.

Aufruf auf DEV (braucht den Hauptschluessel):
  bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_token_verbrauch_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import asyncio
import json
import ssl
import sys
import time
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


def bilanz(code=None):
    print(f"\nBILANZ: {_ok} OK, {_fail} FAIL")
    sys.exit(code if code is not None else (1 if _fail else 0))


def ruf(pfad, methode="GET", rumpf=None, token=None, timeout=120):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    if daten is not None:
        r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, context=_ctx, timeout=timeout) as a:
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


from backend import main as bm            # noqa: E402
from backend import token_verbrauch as tv  # noqa: E402
from backend import llm                    # noqa: E402

print("=" * 74)
print("LIVE auf DEV: Token-Verbrauch")
print("=" * 74)


def neue_zeilen(seit):
    """Zeilen ab ``seit``. Das Fenster beginnt AM Aufruf (Rundung der Zeit auf ms
    abgefangen) – eine Sekunde davor zaehlte bei zwei dicht aufeinander
    folgenden Laeufen die Zeile des Vorlaufs mit (gemessen: 2,1 s Abstand)."""
    out = []
    for p in sorted(tv._DIR.glob("*.jsonl")):
        for z in p.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(z)
            except Exception:  # noqa: BLE001
                continue
            if d.get("ts", 0) >= seit:
                out.append(d)
    return out


# ── 1. echter Aufruf, Umhuellung der echten Klasse ────────────────────────────
print("\n1. Echter Modellaufruf ueber das aktive Profil")
provider, modell = llm.provider_fuer_lauf(prompt_tool_calling=False)
check("Positivkontrolle: aktive Provider-Klasse ist umhuellt",
      getattr(type(provider).generate_response, "__token_erfassung__", False), type(provider).__name__)
# contents im ECHTEN Format der Aufrufer (types.Content, wie prompt_check.py).
# Die erste Fassung schickte dicts – der Aufruf scheiterte, und die Pruefung
# "ohne Zaehlung erfasst" war aus dem falschen Grund gruen. Deshalb ist der
# GELUNGENE Aufruf jetzt Positivkontrolle (sonst Exit 2).
from google.genai import types  # noqa: E402
ns = {"__name__": "backend.prompt_check", "provider": provider, "modell": modell, "types": types}
exec(compile("async def lauf():\n"
             "    return await provider.generate_response(model=modell, system_prompt='Antworte knapp.',\n"
             "        contents=[types.Content(role='user', parts=[types.Part.from_text(text='Sage nur: ok')])],\n"
             "        tools=[], reasoning_effort='low')\n",
             "<probe>", "exec"), ns)
t0 = time.time()
try:
    resp = asyncio.run(ns["lauf"]())
except Exception as e:  # noqa: BLE001
    resp = None
    print(f"       (Aufruf scheiterte: {e!r})")
check("Positivkontrolle: der echte Modellaufruf ist gelungen", resp is not None)
if resp is None:
    bilanz(2)
z = [x for x in neue_zeilen(t0 - 0.01) if x.get("d") == "prompt_check" and x.get("u") == ""]
check("genau eine neue Zeile aus diesem Aufruf", len(z) == 1, str(z)[:300])
if z:
    z = z[0]
    print(f"       Zeile: an={z.get('an')} m={z.get('m')} ein={z.get('ein')} aus={z.get('aus')} "
          f"cl={z.get('cl')} ms={z.get('ms')} f={z.get('f')}")
    check("Anbieter-Kennung der echten Klasse", z.get("an") == type(provider).anbieter_kennung, z.get("an"))
    check("Modell des Profils", z.get("m") == modell, f"{z.get('m')} / {modell}")
    check("kein Fehlschlag vermerkt", not z.get("f"), str(z))
    if getattr(resp, "usage", None):
        check("echte Zaehlung des Anbieters uebernommen (ein > 0, aus > 0)",
              (z.get("ein") or 0) > 0 and (z.get("aus") or 0) > 0, str(resp.usage))
    else:
        check("Anbieter liefert keine Zaehlung -> als 'ohne Angabe' erfasst (nicht geschaetzt)",
              z.get("ein") is None, str(z))

# ── 2. Aufruf im laufenden Dienst ──────────────────────────────────────────────
print("\n2. Aufruf IM Dienst ueber HTTP")
U = "jarvis"
TOKEN = bm.generate_token(U)
t1 = time.time()
st, d = ruf("/api/prompt/pruefen", "POST", {"prompt": "Fasse die Mails von heute zusammen.",
                                             "kontext": "tracks", "lang": "de"}, TOKEN)
dienst_zeile = []
if st == 403:
    print(f"       NICHT MESSBAR: Messkonto nicht fuer Short Tracks freigegeben ({str(d)[:100]})")
else:
    check("Aufgabenpruefung beantwortet", st == 200, f"{st} {str(d)[:120]}")
    for _ in range(10):
        dienst_zeile = [x for x in neue_zeilen(t1 - 0.01) if x.get("d") == "prompt_check" and x.get("u")]
        if dienst_zeile:
            break
        time.sleep(0.5)
    check("der DIENSTPROZESS hat die Zeile geschrieben (Benutzer aus der Sitzung)",
          len(dienst_zeile) == 1 and bm._norm_login(dienst_zeile[0].get("u")) == bm._norm_login(U),
          str(dienst_zeile)[:300])

# ── 2b. Agentenlauf im Dienst (Agent-API) ─────────────────────────────────────
# Der wichtigste Pfad: ein headless-Agentenlauf IM Dienstprozess. Benutzer
# kommt aus dem Actor ("api:<Quelle>"), der Kanal aus der Auftragsquelle.
# Der Schluessel wird nur aus der Konfiguration genommen und nie ausgegeben.
print("\n2b. Agentenlauf im Dienst ueber die Agent-API")
schluessel = next((k for k in (bm._agent_key_kandidaten() or []) if k), "")
if not schluessel:
    print("       NICHT MESSBAR: kein Agent-API-Schluessel hinterlegt")
else:
    import uuid  # noqa: E402
    quelle = "TV-Probe " + uuid.uuid4().hex[:6]
    t2 = time.time()
    r = urllib.request.Request(BASIS + "/api/agent/task", method="POST",
                               data=json.dumps({"text": "Wie viel ist 17 mal 23? Antworte nur mit der Zahl.",
                                                "source": quelle}).encode())
    r.add_header("Content-Type", "application/json")
    r.add_header("X-API-Key", schluessel)
    try:
        with urllib.request.urlopen(r, context=_ctx, timeout=300) as a:
            st, d = a.status, json.loads(a.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as e:
        st, d = e.code, e.read().decode("utf-8", "replace")[:200]
    check("Agentenlauf beantwortet", st == 200 and isinstance(d, dict) and d.get("success"), f"{st} {str(d)[:160]}")
    agent_z = [x for x in neue_zeilen(t2 - 0.01) if x.get("u") == "api:" + quelle]
    print(f"       {len(agent_z)} Zeile(n): " + "; ".join(
        f"d={x.get('d')} k={x.get('k')} w={x.get('w')} ein={x.get('ein')} aus={x.get('aus')}" for x in agent_z))
    check("der DIENSTPROZESS hat den Agentenlauf erfasst (Benutzer = Actor des Laufs)", len(agent_z) >= 1)
    check("Dienst 'agent'", bool(agent_z) and all(x.get("d") == "agent" for x in agent_z),
          str([x.get("d") for x in agent_z]))
    check("Kanal aus der Auftragsquelle: 'Agent-API'", bool(agent_z) and all(x.get("k") == "Agent-API" for x in agent_z),
          str([x.get("k") for x in agent_z]))
    check("Tokens gezaehlt", bool(agent_z) and all((x.get("ein") or 0) > 0 for x in agent_z))

# ── 3. Endpunkt ───────────────────────────────────────────────────────────────
print("\n3. Endpunkt im Dienst")
st, d = ruf("/api/logs/token_verbrauch?tage=1&gruppe=dienst", token=TOKEN)
if st == 403:
    print(f"       Endpunkt fuer das Messkonto gesperrt ({str(d)[:120]}) – konnte nicht messen")
    bilanz(2)
check("Endpunkt antwortet", st == 200 and isinstance(d, dict), f"{st} {str(d)[:120]}")
schl = [r.get("schluessel") for r in (d.get("tabelle") or [])]
check("Dienst 'prompt_check' steht in der Auswertung", "prompt_check" in schl, str(schl))
summe = d.get("summe") or {}
check("Summe aller Reihen == Gesamtsumme (echte Daten)",
      sum(sum(r["ein"]) for r in d.get("reihen") or []) == summe.get("ein"), str(summe))
check("Stundenraster fuer 24 Stunden", d.get("raster") == "stunde")
st2, d2 = ruf("/api/logs/token_verbrauch?tage=1&kanal=", token=TOKEN)
check("leerer Kanal-Filter wird angenommen", st2 == 200 and (d2.get("filter") or {}).get("kanal") == "",
      f"{st2} {str(d2)[:120]}")
st3, d3 = ruf("/api/logs/token_verbrauch?tage=abc", token=TOKEN)
check("ungueltiger Zeitraum: 400 mit Grund", st3 == 400 and "tage" in str(d3), f"{st3} {d3}")

NIEMAND = bm.generate_token("pentest.niemand")
st4, d4 = ruf("/api/logs/token_verbrauch", token=NIEMAND)
check("Konto ohne Rolle: 403 von der Admin-Schranke",
      st4 == 403 and "Administrator" in str(d4), f"{st4} {str(d4)[:120]}")
st5, _ = ruf("/api/logs/token_verbrauch")
check("ohne Anmeldung: 401", st5 == 401, str(st5))

bilanz()
