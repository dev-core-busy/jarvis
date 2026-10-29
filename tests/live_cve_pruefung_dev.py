"""Live-Probe auf DEV: Sicherheitsluecken-Pruefung gegen den echten Dienst.

NUR LESEND, was die Pakete angeht: es wird geprueft, NICHT behoben. Ein
angelegter Probe-Auftrag wird am Ende geloescht (er ist ausgeschaltet, laeuft
also nie). Das Pruefergebnis (data/cve/ergebnis.json) wird dabei neu
geschrieben – das ist der Zweck der Funktion, kein Fremdzustand.

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_cve_pruefung_dev.py
"""
import json
import ssl
import sys
import time
import urllib.request

sys.path.insert(0, "/opt/jarvis")
from backend import main as m          # noqa: E402

CTX = ssl._create_unverified_context()
BASIS = "https://127.0.0.1"
ok = fail = 0


def check(n, c, d=""):
    global ok, fail
    if c:
        ok += 1
        print("  OK   %s" % n)
    else:
        fail += 1
        print("  FAIL %s%s" % (n, (" – %s" % d) if d else ""))


def hol(pfad, token=None, methode="GET", daten=None):
    r = urllib.request.Request(BASIS + pfad, method=methode,
                               data=None if daten is None else json.dumps(daten).encode())
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if daten is not None:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=120) as a:
            roh = a.read()
            return a.status, json.loads(roh or b"{}")
    except urllib.error.HTTPError as e:
        roh = e.read()
        try:
            return e.code, json.loads(roh or b"{}")
        except ValueError:
            return e.code, {"roh": roh[:200].decode(errors="replace")}


tok = m.generate_token("jarvis")
tok_user = m.generate_token("contoso\\testnutzer")

print("\n0) Positivkontrolle: der Dienst antwortet einem Administrator")
s, me = hol("/api/me", tok)
if s != 200 or not me.get("is_admin"):
    print("ABBRUCH: /api/me liefert keinen Administrator (%s) – Probe nicht deutbar" % s)
    sys.exit(2)
check("/api/me traegt cve_badge (Badge am Paket-Symbol)",
      isinstance(me.get("cve_badge"), dict) and "anzahl" in me["cve_badge"], me.get("cve_badge"))
check("das Zahnrad-Badge enthaelt keine CVE-Zahl", "cve" not in (me.get("admin_badge") or {}))
s_u, me_u = hol("/api/me", tok_user)
if s_u == 200:
    check("ein Nicht-Admin bekommt eine leere cve_badge",
          (me_u.get("cve_badge") or {}).get("anzahl") == 0, me_u.get("cve_badge"))
else:
    # Der Probe-Benutzer ist auf DEV nicht zur Anmeldung freigegeben (403
    # NOT_AUTHORIZED) – dann ist der Fall hier NICHT messbar. Die Zusage prueft
    # tests/test_cve_pruefung.py am Syntaxbaum (nur im Admin-Zweig gefuellt).
    print("  --   Nicht-Admin-Fall hier nicht messbar (/api/me: %s)" % s_u)

print("\n1) Rechte")
s, _ = hol("/api/system/cve")
check("ohne Token 401", s == 401, s)
s, d = hol("/api/system/cve", tok_user)
check("Nicht-Admin 403 (nicht die Liste)", s == 403 and "ergebnis" not in d, s)
s, _ = hol("/api/system/cve/pruefen", tok_user, "POST", {"beheben": True})
check("Nicht-Admin kann keine Behebung starten", s == 403, s)

print("\n2) Pruefung starten (OHNE Behebung) und abwarten")
s, d = hol("/api/system/cve/pruefen", tok, "POST", {"beheben": False})
check("Start antwortet sofort mit 202 (oder 409, wenn schon eine laeuft)", s in (202, 409), (s, d))
s2, d2 = hol("/api/system/cve/pruefen", tok, "POST", {})
check("ein zweiter Start waehrend des Laufs wird abgewiesen (409)", s2 == 409, (s2, d2))
t0 = time.time()
z = {}
while time.time() - t0 < 900:
    s, z = hol("/api/system/cve", tok)
    if s == 200 and not z.get("laeuft"):
        break
    time.sleep(5)
dauer = time.time() - t0
check("die Pruefung endet (< 15 min)", s == 200 and not z.get("laeuft"), "%.0fs" % dauer)
erg = z.get("ergebnis") or {}
print("     -> Dauer %.0f s, Zaehler %s" % (dauer, erg.get("zaehler")))
check("das Ergebnis ist frisch (nach dem Start erzeugt)", erg.get("ts", 0) >= t0 - 5,
      (erg.get("ts"), t0))
check("es wurde NICHT behoben", erg.get("beheben") is False and erg.get("behebung") is None)
ber = erg.get("bereiche") or {}
check("Debian wurde geprueft", (ber.get("debian") or {}).get("geprueft") is True, ber.get("debian"))
check("Python wurde geprueft", (ber.get("python") or {}).get("geprueft") is True, ber.get("python"))
# Ohne installierte Bridge gibt es keinen npm-Bereich (kein "nicht geprueft"
# ohne Informationswert) – fehlen darf er also NUR, wenn node_modules fehlt.
from pathlib import Path  # noqa: E402
_bridge = (Path("/opt/jarvis") / "services" / "whatsapp-bridge" / "node_modules").is_dir()
check("npm: Bereich da, wenn die Bridge installiert ist – sonst nicht",
      ("npm" in ber and ((ber["npm"].get("geprueft") is True) or bool(ber["npm"].get("grund"))))
      if _bridge else "npm" not in ber, (_bridge, ber.get("npm")))
print("     -> npm:", ber.get("npm"), "(Bridge installiert)" if _bridge else "(Bridge nicht installiert)")
# Node.js-Laufzeit: auf DEV aus NodeSource, muss also geprueft sein und darf
# nicht mehr unter "nicht ueber Debian pruefbar" stehen.
from backend import cve_pruefung as _cp  # noqa: E402
_ni = _cp.node_installiert(_cp.release())
_nb = ber.get("node") or {}
if _ni and _ni.get("debian") is False:
    check("Node.js (Fremdquelle) wurde geprueft", _nb.get("geprueft") is True, _nb)
    check("Node.js steht nicht mehr in der Fremdliste",
          _ni["paket"] not in ((ber.get("debian") or {}).get("fremd") or []), ber.get("debian", {}).get("fremd"))
    check("Ende der Unterstuetzung ist bekannt", bool(_nb.get("unterstuetzt_bis")), _nb)
else:
    check("ohne Node.js aus Fremdquelle kein Node-Bereich", "node" not in ber, (_ni, _nb))
print("     -> node:", _nb, "| fremd:", (ber.get("debian") or {}).get("fremd"))
deb = ber.get("debian") or {}
check("Release und Tracker-Stand stehen im Ergebnis",
      bool(deb.get("release")) and bool(deb.get("tracker_stand")), deb)
check("die Debian-Pruefung hat Pakete gesehen", deb.get("pakete", 0) > 100, deb.get("pakete"))
bef = erg.get("befunde") or []
check("jeder Befund hat id, Klasse und Pakete",
      all(b.get("id") and b.get("klasse") and isinstance(b.get("pakete"), list) for b in bef))
check("Zaehler und Befunde stimmen ueberein",
      sum((erg.get("zaehler") or {}).values()) == len(bef))
check("behebbar ist nie quittierbar",
      not any(b["klasse"] == "behebbar" and b["quittierbar"] and b["bereich"] != "npm"
              and not (b["bereich"] == "node" and not b.get("beheben_mit")) for b in bef))
check("Plan liegt bei", isinstance(z.get("plan"), dict), z.get("plan"))
print("     -> Plan:", json.dumps(z.get("plan"))[:300])

print("\n3) Quittieren pruefen ohne Zustand zu aendern")
s, d = hol("/api/system/cve/quittieren", tok, "POST", {"ids": []})
check("leere Liste -> 0 quittiert", s == 200 and d.get("quittiert") == 0, (s, d))
s, d = hol("/api/system/cve/quittieren", tok, "POST", {"ids": "alle"})
check("ids als Text -> 400", s == 400, (s, d))
behebbar = [b["id"] for b in bef if b["klasse"] == "behebbar" and b["bereich"] == "debian"]
if behebbar:
    s, d = hol("/api/system/cve/quittieren", tok, "POST", {"ids": behebbar[:1]})
    check("ein behebbarer Befund wird NICHT quittiert", s == 200 and d.get("quittiert") == 0, d)

print("\n3b) Einzel-Update: nur fuer behebbare Quellpakete, nur fuer Admins")
s, d = hol("/api/system/cve/einzeln", tok_user, "POST", {"quelle": "brotli"})
check("Nicht-Admin -> 403", s == 403, s)
s, d = hol("/api/system/cve/einzeln", tok, "POST", {})
check("ohne quelle -> 400", s == 400, (s, d))
s, d = hol("/api/system/cve/einzeln", tok, "POST", {"quelle": "gibt-es-nicht-xyz"})
check("Quellpaket ohne Update -> 400 (es wird nichts angestossen)", s == 400, (s, d))
offen_q = sorted({b["quelle"] for b in bef if b["bereich"] == "debian" and b["klasse"] == "offen"})
if offen_q:
    s, d = hol("/api/system/cve/einzeln", tok, "POST", {"quelle": offen_q[0]})
    check("Quellpaket nur mit offenen Luecken -> 400", s == 400, (offen_q[0], s, d))

print("\n4) Einstellungen: ungueltig abgelehnt, gueltig unveraendert zurueckgeschrieben")
vorher = z.get("einstellungen") or {}
s, d = hol("/api/system/cve/einstellungen", tok, "PUT", {"schwelle": "kritisch"})
check("unbekannte Schwelle -> 400", s == 400, (s, d))
s, d = hol("/api/system/cve/einstellungen", tok, "PUT", vorher)
check("vorgefundener Stand wieder gesetzt", s == 200 and d.get("einstellungen") == vorher, (s, d))

print("\n5) Auftrag der Art cve_pruefung (ausgeschaltet, wird wieder geloescht)")
job_id = None
try:
    s, d = hol("/api/cron", tok, "POST", {"label": "Probe CVE", "cron": "0 3 * * *",
                                          "enabled": False, "kind": "cve_pruefung",
                                          "cve": {"beheben": False, "schwelle": "kritisch"}})
    check("ungueltige Schwelle beim Anlegen -> 400", s == 400, (s, d))
    s, d = hol("/api/cron", tok, "POST", {"label": "Probe CVE", "cron": "0 3 * * *",
                                          "enabled": False, "kind": "cve_pruefung",
                                          "cve": {"beheben": False, "schwelle": "alle"}})
    job_id = d.get("id")
    check("Auftrag angelegt, Art cve_pruefung, kein Agent", s == 201 and d.get("kind") == "cve_pruefung",
          (s, d))
    check("Optionen gespeichert", d.get("payload") == {"beheben": False, "schwelle": "alle"},
          d.get("payload"))
    s, d = hol("/api/cron/%s" % job_id, tok, "PUT", {"cve": {"beheben": True, "schwelle": ""},
                                                       "kind": "agent"})
    check("PUT setzt beheben, die Art bleibt", s == 200 and d.get("kind") == "cve_pruefung"
          and d.get("payload", {}).get("beheben") is True, (s, d))
finally:
    if job_id:
        s, _ = hol("/api/cron/%s" % job_id, tok, "DELETE")
        check("Probe-Auftrag wieder geloescht", s == 200, s)
s, jobs = hol("/api/cron", tok)
check("kein Probe-Auftrag uebrig", not any(j.get("label") == "Probe CVE" for j in jobs or []))

print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
