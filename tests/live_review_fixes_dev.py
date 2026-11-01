#!/usr/bin/env python3
"""Live-Probe auf DEV: die Fixes aus dem Code-Review vom 2026-11-01 im laufenden Dienst.

Gemessen ueber HTTPS gegen den echten Dienst (nicht ueber ein zweites Objekt):

1. MCP: eine neue Adresse OHNE neu eingegebenen Schluessel wird mit 400
   (``geheimnis_neu_eingeben``) abgewiesen und NICHT gespeichert; Umbenennen
   und "neue Adresse MIT neuem Schluessel" gehen durch.
2. JSON-Rumpf: ein Array/Skalar/kaputtes JSON ergibt 400 statt 500 – an
   einem umgestellten Endpunkt (``/api/userchat/search``) und an den
   CVE-Endpunkten; ``[]`` an ``/einstellungen`` aendert nichts.
3. Cron: ein PUT mit ungueltigem Cron-Ausdruck UND geaenderten CVE-Optionen
   wird abgelehnt und laesst die Optionen stehen (nur wenn es auf DEV einen
   CVE-Pruefauftrag gibt – sonst ausdruecklich UEBERSPRUNGEN, nicht gruen).
4. auth_state: nach einem Abruf, der den Zustand liest, liegt die Sperrdatei
   neben auth_state.json und gehoert dem Dienstbenutzer.

Der Zustand wird wiederhergestellt: der Test-MCP-Server wird GEZIELT
entfernt (vorher wird geprueft, dass kein Rueckstand eines frueheren Laufs
da ist); am CVE-Auftrag wird nur ein PUT geschickt, der abgelehnt werden MUSS
– wird er wider Erwarten angenommen, stellt die Probe den Vorzustand her.

Aufruf (als root auf DEV, das Token braucht den Hauptschluessel):
    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_review_fixes_dev.py
"""
import json
import os
import ssl
import sys
import urllib.request

sys.path.insert(0, "/opt/jarvis")
import backend.main as main  # noqa: E402

BASIS = "https://127.0.0.1"
CTX = ssl.create_default_context()
CTX.check_hostname = False
CTX.verify_mode = ssl.CERT_NONE
TESTNAME = "Live-Probe Review 2026-11-01"

ok = fail = 0


def check(name, cond, detail=""):
    global ok, fail
    if cond:
        ok += 1
        print("  OK   %s" % name)
    else:
        fail += 1
        print("  FAIL %s%s" % (name, (" - " + str(detail)) if detail else ""))


def ruf(pfad, token, methode="GET", rumpf=None, roh=None):
    if roh is not None:
        daten = roh.encode()
    else:
        daten = json.dumps(rumpf).encode() if rumpf is not None else None
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    r.add_header("Authorization", "Bearer " + token)
    if daten is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=30) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:  # noqa: BLE001
            return e.code, {}


def abbruch(grund):
    print("ABBRUCH (konnte nicht laufen): " + grund)
    sys.exit(2)


TOKEN = main.generate_token("jarvis")

# ── Positivkontrolle: Token gilt, Admin-Endpunkt antwortet ──────────────────
st, srv = ruf("/api/mcp/servers", TOKEN)
if st != 200:
    abbruch("GET /api/mcp/servers -> %s (Token gilt nicht? als_dienst.sh benutzt?)" % st)
print("Positivkontrolle: Token gilt (MCP-Liste 200)")


def mcp_liste():
    s, d = ruf("/api/mcp/servers", TOKEN)
    return d.get("servers") if isinstance(d, dict) else d


def eigene(liste):
    return [x for x in (liste or []) if isinstance(x, dict) and x.get("name") == TESTNAME]


if eigene(mcp_liste()):
    abbruch("Rueckstand eines frueheren Laufs: MCP-Server '%s' existiert – erst entfernen."
            % TESTNAME)

# ── 1. MCP: Geheimnis geht nicht still an ein neues Ziel ────────────────────
print("\n1. MCP-Schluessel und neues Ziel")
sid = None
try:
    st, neu = ruf("/api/mcp/servers", TOKEN, "POST", {
        "name": TESTNAME, "transport": "http", "enabled": False,
        "url": "https://mcp.beispiel.de/mcp", "api_key": "sonde-geheim-123456",
        "args": [], "command": "", "env": {}})
    sid = neu.get("id") if isinstance(neu, dict) else None
    if st != 200 or not sid:
        abbruch("Test-MCP-Server nicht anlegbar: %s %s" % (st, neu))
    check("Antwort enthaelt den Schluessel NICHT", "sonde-geheim" not in json.dumps(neu))
    st, d = ruf("/api/mcp/servers/" + sid, TOKEN, "PUT",
                {"url": "https://angreifer.beispiel.de/mcp", "transport": "http",
                 "command": "", "args": [], "name": TESTNAME})
    check("neue URL ohne Schluessel -> 400 geheimnis_neu_eingeben",
          st == 400 and d.get("code") == "geheimnis_neu_eingeben", (st, d))
    # Die Statusliste traegt keine Adresse – gelesen wird ueber den Formular-Abruf.
    _s, gespeichert = ruf("/api/mcp/servers/%s/konfig" % sid, TOKEN)
    check("... und die URL ist NICHT gespeichert",
          gespeichert.get("url") == "https://mcp.beispiel.de/mcp"
          and gespeichert.get("api_key_gesetzt") is True, (gespeichert.get("url"),
                                                           gespeichert.get("api_key_gesetzt")))
    st, d = ruf("/api/mcp/servers/" + sid, TOKEN, "PUT",
                {"name": TESTNAME, "url": "https://mcp.beispiel.de/mcp/", "transport": "http",
                 "command": "", "args": []})
    check("gleiches Ziel (Formular sendet alles) -> 200", st == 200, (st, d))
    st, d = ruf("/api/mcp/servers/" + sid, TOKEN, "PUT",
                {"url": "https://anders.beispiel.de/mcp", "api_key": "neu-eingegeben-7890",
                 "transport": "http", "command": "", "args": []})
    check("neue URL MIT neuem Schluessel -> 200", st == 200, (st, d))
    st, d = ruf("/api/mcp/servers/" + sid, TOKEN, "PUT", roh="[1, 2]")
    check("PUT mit Array-Rumpf -> 400", st == 400, (st, d))
finally:
    if sid:
        st, _ = ruf("/api/mcp/servers/" + sid, TOKEN, "DELETE")
        check("Test-MCP-Server entfernt", st == 200 and not eigene(mcp_liste()), st)

# ── 2. JSON-Rumpf ───────────────────────────────────────────────────────────
print("\n2. JSON-Rumpf, der kein Objekt ist")
# Messpunkt: ein Admin-Endpunkt, der den Rumpf als ERSTES liest und vorher
# nichts aendert (/api/userchat/search antwortet auf DEV mit 403, weil der
# Skill aus ist – ihn fuer eine Messung einzuschalten waere ein Eingriff).
# Gezaehlt wird nur die 400 VON _json_objekt (detail-Text), nicht die eigene
# 400 des Endpunkts ("Ungueltiger Endpunkt-Schluessel").
for roh, besch in (("[]", "Array"), ('"x"', "Skalar"), ("{kaputt", "kein JSON")):
    st, d = ruf("/api/admin/api-local-only", TOKEN, "POST", roh=roh)
    check("/api/admin/api-local-only mit %s -> 400 aus _json_objekt" % besch,
          st == 400 and str(d.get("detail", "")) in ("JSON-Objekt erwartet", "Ungültiger JSON-Rumpf"),
          (st, d))
st, vorher = ruf("/api/system/cve", TOKEN)
st2, d = ruf("/api/system/cve/einstellungen", TOKEN, "PUT", roh="[]")
check("/api/system/cve/einstellungen mit [] -> 400", st2 == 400, (st2, d))
st3, nachher = ruf("/api/system/cve", TOKEN)
check("... CVE-Einstellungen unveraendert",
      st == st3 == 200 and (vorher or {}).get("einstellungen") == (nachher or {}).get("einstellungen"),
      ((vorher or {}).get("einstellungen"), (nachher or {}).get("einstellungen")))
st, d = ruf("/api/system/cve/quittieren", TOKEN, "POST", roh='"x"')
check("/api/system/cve/quittieren mit Skalar -> 400", st == 400, (st, d))

# ── 3. Cron: abgelehnter PUT aendert die CVE-Optionen nicht ─────────────────
print("\n3. Cron-PUT mit ungueltigem Ausdruck")
st, jobs = ruf("/api/cron", TOKEN)
cve = [j for j in (jobs if isinstance(jobs, list) else (jobs or {}).get("jobs", []))
       if isinstance(j, dict) and j.get("kind") == "cve_pruefung"]
if not cve:
    print("  UEBERSPRUNGEN: kein CVE-Pruefauftrag auf DEV (nicht gruen, nicht gemessen)")
else:
    job = cve[0]
    alt = dict(job.get("payload") or {})
    umgedreht = {"beheben": not alt.get("beheben"), "schwelle": alt.get("schwelle") or ""}
    st, d = ruf("/api/cron/" + job["id"], TOKEN, "PUT", {"cron": "ungueltig", "cve": umgedreht})
    check("ungueltiger Cron + cve -> 400", st == 400, (st, d))
    st, jobs2 = ruf("/api/cron", TOKEN)
    jetzt = next((j for j in (jobs2 if isinstance(jobs2, list) else (jobs2 or {}).get("jobs", []))
                  if isinstance(j, dict) and j.get("id") == job["id"]), {})
    gleich = (jetzt.get("payload") or {}) == alt
    check("... CVE-Optionen unveraendert", gleich, (alt, jetzt.get("payload")))
    if not gleich:
        # Wider Erwarten gespeichert: Vorzustand herstellen, nicht raten.
        ruf("/api/cron/" + job["id"], TOKEN, "PUT", {"cve": alt})

# ── 4. auth_state-Sperrdatei ────────────────────────────────────────────────
print("\n4. Sperrdatei neben auth_state.json")
st, d = ruf("/api/auth/totp/status", TOKEN)
check("Status-Abruf (liest auth_state) -> 200", st == 200, st)
sperr = "/opt/jarvis/data/auth_state.json.lock"
check("Sperrdatei vorhanden", os.path.exists(sperr), sperr)
if os.path.exists(sperr):
    import pwd
    besitzer = pwd.getpwuid(os.stat(sperr).st_uid).pw_name
    check("Sperrdatei gehoert dem Dienstbenutzer", besitzer == "jarvis", besitzer)

print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
