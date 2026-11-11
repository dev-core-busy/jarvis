#!/usr/bin/env python3
"""Live auf DEV: SQL-Assistent ueber den ECHTEN HTTPS-Weg, mit ECHTEM Modell.

Aufruf auf dem Server (Token-Ausstellung braucht den Hauptschluessel, BSI M5):

    bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_sql_assistent_dev.py

Gemessen (Stand 2026-11-07: feste Schemata, Upload, Auswahl statt
Wissensgruppen): Kachel-Recht (/api/me), Seitenrahmen, Freigabe (leer = 403),
zwei Schemata, deren Dateien UEBER DEN ECHTEN UPLOAD-WEG kommen (Ordner mit
relativen Pfaden und ein ZIP, darin ein Zip-Slip-Eintrag); die Erfassung
startet VON SELBST. Das zweite Schema traegt eine Tabelle mit frei erfundenem
Namen (``zz_geheim_q9``), die bei Auswahl des ersten in KEINER Antwort
auftauchen darf (Suche, Detail, SQL) – Positivkontrolle: bei Auswahl des
zweiten ist sie da. Ohne Auswahl 400. Dateiliste, Loeschen einer Datei (wirkt
nach der automatischen Erfassung), Pfad-Tricks ueber HTTP, Schema entfernen
nur mit Bestaetigung. Jede Frage ZWEIMAL – eine Modellantwort ist erst nach
Wiederholung eine Messung.

⚠ DIE PROBE STELLT DEN VORGEFUNDENEN ZUSTAND WIEDER HER (Register): Freigabe-
Felder, Skill-Schalter, SQL-Konfiguration und ``data/sql_schema_graph`` werden
vorher gesichert und im ``finally`` zurueckgestellt (nach dem Ende der dabei
angestossenen Erfassung – sonst schriebe sie den Graphen nach dem
Zurueckkopieren neu); am Ende wird jeder Punkt NACHGEMESSEN.
"""
import json
import os
import shutil
import ssl
import sys
import tempfile
import time
import uuid
import zipfile
import io
import urllib.error
import urllib.request
from pathlib import Path

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
        print("  FAIL %s%s" % (label, (" – %s" % str(detail)[:300]) if detail else ""))


def ruf(pfad, token, methode="GET", rumpf=None, roh=False, timeout=240):
    daten = json.dumps(rumpf).encode() if rumpf is not None else None
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    if token:
        r.add_header("Authorization", "Bearer " + token)
    if daten:
        r.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=timeout) as a:
            text = a.read().decode()
            return a.status, (text if roh else json.loads(text or "{}"))
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        if roh:
            return e.code, text
        try:
            return e.code, json.loads(text or "{}")
        except ValueError:
            return e.code, {}


from backend import main as M  # noqa: E402


def hochladen(token, sid, teile):
    """multipart/form-data wie der Reiter: Felder ``files`` + ``pfade`` (JSON)."""
    grenze = "----probe" + uuid.uuid4().hex
    koerper = io.BytesIO()
    for name, inhalt in teile:
        koerper.write((f"--{grenze}\r\nContent-Disposition: form-data; name=\"files\"; "
                       f"filename=\"{name.split('/')[-1]}\"\r\nContent-Type: application/octet-stream\r\n\r\n").encode())
        koerper.write(inhalt)
        koerper.write(b"\r\n")
    koerper.write((f"--{grenze}\r\nContent-Disposition: form-data; name=\"pfade\"\r\n\r\n"
                   + json.dumps([n for n, _ in teile]) + f"\r\n--{grenze}--\r\n").encode())
    r = urllib.request.Request(BASIS + f"/api/sql/admin/schema/{sid}/upload", data=koerper.getvalue(), method="POST")
    r.add_header("Authorization", "Bearer " + token)
    r.add_header("Content-Type", "multipart/form-data; boundary=" + grenze)
    try:
        with urllib.request.urlopen(r, context=CTX, timeout=120) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except ValueError:
            return e.code, {}


def skill_an() -> bool | None:
    """Skill-Schalter LAUT DIENST (nicht aus der Konfiguration dieses Prozesses –
    ein zweiter Prozess sieht den Zustand des Dienstes nicht)."""
    code, d = ruf("/api/skills", TA)
    liste = d if isinstance(d, list) else (d.get("skills") if isinstance(d, dict) else None) or []
    for s in liste:
        if isinstance(s, dict) and s.get("dir_name") == "schema_graph":
            return bool(s.get("enabled"))
    return None


def erfassung_abwarten(sekunden=240) -> dict:
    """Bis keine Erfassung mehr laeuft (die automatische startet nach dem
    Upload; ein Nachlauf kann folgen). Zweimal hintereinander 'laeuft nicht',
    damit der Spalt zwischen Lauf und Nachlauf nicht als Ende gilt."""
    ende = time.time() + sekunden
    still, st = 0, {}
    while time.time() < ende:
        time.sleep(1)
        _c, d = ruf("/api/sql/admin/index", TA)
        st = d.get("erfassung") or {}
        laeuft = st.get("laeuft") or d.get("hier")
        still = 0 if laeuft else still + 1
        if still >= 2:
            break
    return st


ADMIN = "jarvis"
TESTUSER = os.environ.get("SQL_TESTUSER") or ziele.wert("JARVIS_DEV_TESTUSER")
TA = M.generate_token(ADMIN)
time.sleep(1.1)   # zwei Tokens derselben Sekunde waeren identisch (Register)
TU = M.generate_token(TESTUSER)
check(TA != TU, "Positivkontrolle: zwei verschiedene Sitzungen")

# ── Ausgangszustand sichern ────────────────────────────────────────────────
code, ad = ruf("/api/auth/ad_status", TA)
if code != 200:
    print(f"ABBRUCH (Exit 2): /api/auth/ad_status {code}")
    sys.exit(2)
VOR_FREIGABE = {"schema_allowed_users": ad.get("schema_users", ""), "schema_allowed_group": ad.get("schema_group", "")}
VOR_SKILL = skill_an()
if VOR_SKILL is None:
    print("ABBRUCH (Exit 2): Skill schema_graph in /api/skills nicht gefunden")
    sys.exit(2)
BASIS_DIR = Path("/opt/jarvis/data/sql_schema_graph")
SICHERUNG = Path(tempfile.mkdtemp(prefix="sql_probe_sich_", dir="/var/tmp"))
BASIS_WAR_DA = BASIS_DIR.exists()
if BASIS_WAR_DA:
    shutil.copytree(BASIS_DIR, SICHERUNG / "sql_schema_graph", symlinks=True)
ERP_SQL = b"""
CREATE TABLE erp.kdst (kdnr integer PRIMARY KEY, kdname varchar(120), lnd char(2));
COMMENT ON TABLE erp.kdst IS 'Kundenstamm';
CREATE TABLE erp.lnd (lnd char(2) PRIMARY KEY, lndbez varchar(80));
COMMENT ON TABLE erp.lnd IS 'Laender';
"""
ERP_DDL = b"""
CREATE TABLE erp.vbkopf (vbeln bigint PRIMARY KEY, kdnr integer, audat date, netwr numeric(15,2));
COMMENT ON TABLE erp.vbkopf IS 'Kundenauftrag Kopf';
COMMENT ON COLUMN erp.vbkopf.netwr IS 'Nettowert';
ALTER TABLE erp.vbkopf ADD FOREIGN KEY (kdnr) REFERENCES erp.kdst(kdnr);
ALTER TABLE erp.kdst ADD FOREIGN KEY (lnd) REFERENCES erp.lnd(lnd);
"""
zpuf = io.BytesIO()
with zipfile.ZipFile(zpuf, "w") as zf:
    zf.writestr("hr/geheim.sql", "CREATE TABLE hr.zz_geheim_q9 (id int PRIMARY KEY, kdnr integer REFERENCES "
                                 "erp.kdst(kdnr), gehalt_q9 numeric);\nCOMMENT ON TABLE hr.zz_geheim_q9 IS "
                                 "'Umsatz Kunde Land Gehalt';\n")
    zf.writestr("../../ausbruch_q9.sql", "x")
ZIP = zpuf.getvalue()
VOR_CFG = None

try:
    code, adm = ruf("/api/sql/admin", TA)
    VOR_CFG = adm.get("cfg") if code == 200 else None
    if VOR_CFG is None:
        print(f"ABBRUCH (Exit 2): /api/sql/admin {code}")
        sys.exit(2)
    print("1. Rechte")
    if not VOR_SKILL:
        code, _ = ruf("/api/skills/schema_graph/enable", TA, "POST", {})
        check(code == 200, "Skill fuer die Probe eingeschaltet", code)
    code, _ = ruf("/api/settings", TA, "POST", {"schema_allowed_users": "", "schema_allowed_group": ""})
    code, me = ruf("/api/me", TU)
    check(code == 200 and not (me.get("permissions") or {}).get("schema"), "Leer = niemand: keine Kachel")
    code, _ = ruf("/api/sql/status", TU)
    check(code == 403, "Leer = niemand: /api/sql/status 403", code)
    code, txt = ruf("/sql", None, roh=True)
    check(code == 200 and 'id="sq-app"' in txt, "Seitenrahmen /sql ohne Anmeldung 200", code)
    code, _ = ruf("/api/sql/status", None)
    check(code == 401, "Daten ohne Anmeldung 401", code)
    code, _ = ruf("/api/settings", TA, "POST", {"schema_allowed_users": TESTUSER, "schema_allowed_group": ""})
    code, me = ruf("/api/me", TU)
    check(code == 200 and (me.get("permissions") or {}).get("schema") is True, "Mit Freigabe: Kachel-Recht", me.get("permissions"))

    print("2. Schemata anlegen und hochladen")
    # Dialekt und Dateimuster stehen JE SCHEMA (seit 2026-11-10): die Probe
    # stellt sie nur an ihren eigenen zwei Schemata ein und laesst die
    # vorgefundenen unberuehrt (vorher verstellte sie das Muster fuer ALLE –
    # auf DEV wurde dabei der echte Bestand neu erfasst).
    PROBE_FELDER = {"dialekt": "postgresql", "dateimuster": "*.sql,*.ddl"}
    gut = dict(VOR_CFG, schemata=list(VOR_CFG.get("schemata") or []) + [
        dict(PROBE_FELDER, name="ERP-Probe-Q9"), dict(PROBE_FELDER, name="Geheim-Probe-Q9")])
    code, d = ruf("/api/sql/admin", TA, "PUT", {"cfg": gut})
    ids = {s["name"]: s["id"] for s in (d.get("cfg") or {}).get("schemata") or []}
    S_ERP, S_GEH = ids.get("ERP-Probe-Q9"), ids.get("Geheim-Probe-Q9")
    check(code == 200 and S_ERP and S_GEH, "Zwei Schemata gespeichert, Kennungen vom Server", (code, ids))
    check(S_ERP and (BASIS_DIR / S_ERP).is_dir() and oct((BASIS_DIR / S_ERP).stat().st_mode & 0o777) == "0o750",
          "Fester Ordner je Schema angelegt (0750)", S_ERP)
    code, d = hochladen(TA, S_ERP, [("erp/stamm/erp.sql", ERP_SQL), ("erp/vb.ddl", ERP_DDL), ("liesmich.txt", b"x"),
                                    ("../ausbruch_q9.sql", b"x")])
    gesp = sorted(x["pfad"] for x in d.get("gespeichert") or [])
    abgl = {a["name"] for a in d.get("abgelehnt") or []}
    check(code == 200 and gesp == ["erp/stamm/erp.sql", "erp/vb.ddl"], "Ordner-Upload: relative Pfade bleiben",
          (code, gesp, d.get("abgelehnt")))
    check({"liesmich.txt", "../ausbruch_q9.sql"} <= abgl, "Falsche Endung und Weg hinaus abgewiesen", abgl)
    check((BASIS_DIR / S_ERP / "erp/stamm/erp.sql").exists() and not (BASIS_DIR / "ausbruch_q9.sql").exists()
          and not Path("/opt/jarvis/data/ausbruch_q9.sql").exists(), "Auf Platte: Datei da, kein Ausbruch")
    code, d = hochladen(TA, S_GEH, [("dump.zip", ZIP)])
    gesp = [x["pfad"] for x in d.get("gespeichert") or []]
    check(code == 200 and gesp == ["hr/geheim.sql"], "ZIP entpackt, Ordnerstruktur erhalten", (code, gesp))
    check(any("ausbruch_q9" in a["name"] for a in d.get("abgelehnt") or []), "ZIP: Zip-Slip benannt abgewiesen",
          d.get("abgelehnt"))
    check(not list(Path("/opt/jarvis/data").glob("ausbruch_q9*")) and not list(BASIS_DIR.glob("ausbruch_q9*")),
          "ZIP: kein Ausbruch auf Platte")
    check(d.get("erfassung") in ("gestartet", "vorgemerkt"), "Upload stoesst die Erfassung an", d.get("erfassung"))
    st = erfassung_abwarten()
    check(st.get("ergebnis") in ("fertig", "unveraendert"), "Automatische Erfassung fertig", (st.get("ergebnis"), st.get("fehler")))
    code, d = ruf(f"/api/sql/admin/schema/{S_ERP}/dateien", TA)
    check(code == 200 and [e["pfad"] for e in d.get("eintraege") or []] == ["erp", "erp/stamm", "erp/stamm/erp.sql", "erp/vb.ddl"],
          "Dateiliste in Baum-Reihenfolge", d.get("eintraege"))
    code, d = ruf(f"/api/sql/admin/schema/{S_ERP}/datei?pfad=..%2F..%2F..%2Fetc%2Fpasswd", TA, "DELETE")
    check(code == 400 and Path("/etc/passwd").exists(), "Loeschen mit Weg hinaus: 400", (code, d))
    tu_admin = bool(M._user_is_admin(TESTUSER))
    code, _ = ruf(f"/api/sql/admin/schema/{S_ERP}/dateien", TU)
    check(code == (200 if tu_admin else 403), f"Verwaltung am Admin-Recht (Testbenutzer {'ist' if tu_admin else 'ist kein'} Admin)", code)

    print("3. Auswahl (Testbenutzer)")
    code, d = ruf("/api/sql/status", TU)
    namen = [q["name"] for q in d.get("schemata") or []]
    check(code == 200 and "ERP-Probe-Q9" in namen and "Geheim-Probe-Q9" in namen, "Status nennt beide Schemata zum Auswaehlen", namen)
    zahlen = {q["id"]: q["tabellen"] for q in d.get("schemata") or []}
    check(zahlen.get(S_ERP) == 3 and zahlen.get(S_GEH) == 1, "Tabellen je Schema gezaehlt", zahlen)
    praef = {q["id"]: q.get("praefixe") for q in d.get("schemata") or []}
    check([p.get("name", "").upper() for p in praef.get(S_ERP) or []] == ["ERP"]
          and (praef.get(S_ERP) or [{}])[0].get("objekte") == 3,
          "Status nennt je Schema seine Datenbankschemata (Praefix) mit Anzahl", praef)
    code, d = ruf("/api/sql/suche?q=gehalt,zz_geheim_q9,umsatz,kunde", TU)
    check(code == 400 and "Schema" in (d.get("error") or ""), "Ohne Auswahl: 400 mit Grund", (code, d))
    code, d = ruf(f"/api/sql/suche?q=gehalt,zz_geheim_q9,umsatz,kunde&schemata={S_ERP}", TU)
    tr = [t["name"] for t in d.get("treffer") or []]
    check(code == 200 and tr and not any("zz_geheim" in n for n in tr), "Suche mit ERP-Auswahl ohne fremde Tabelle", tr)
    code, d = ruf(f"/api/sql/tabelle?name=hr.zz_geheim_q9&schemata={S_ERP}", TU)
    check(code == 404 and d.get("fehler") == "nicht_gefunden", "Nicht gewaehlte Tabelle: nicht gefunden", (code, d))
    code, d = ruf(f"/api/sql/tabelle?name=hr.zz_geheim_q9&schemata={S_GEH}", TU)
    check(code == 200, "Positivkontrolle: mit ihrem Schema gewaehlt ist sie da", code)
    code, d = ruf(f"/api/sql/tabelle?name=erp.kdst&schemata={S_ERP}", TU)
    rein = [k["quelle"] for k in ((d.get("tabelle") or {}).get("rein") or [])]
    check(code == 200 and not any("zz_geheim" in r for r in rein), "Detail ohne Verweis aus dem nicht gewaehlten Schema", rein)
    code, d = ruf(f"/api/sql/tabelle?name=erp.kdst&schemata={S_ERP}", TA)
    check(code == 403, "Admin ohne Freigabe: Benutzer-Endpunkt 403 (kein Admin-Bypass)", code)
    code, d = ruf("/api/sql/frage", TU, "POST", {"frage": "Kunden je Land"})
    check(code == 400 and "Schema" in (d.get("error") or ""), "Frage ohne Auswahl: 400 vor jedem Modellaufruf", (code, d))

    print("4. Fragen (echtes Modell, je zweimal)")
    for frage in ("Wie hoch war der Nettoumsatz je Land im Jahr 2025?",
                  "Welche Kunden haben keinen Auftrag?"):
        for n in (1, 2):
            t0 = time.time()
            code, d = ruf("/api/sql/frage", TU, "POST", {"frage": frage, "schemata": [S_ERP]})
            pr = d.get("pruefung") or {}
            sql = d.get("sql") or ""
            check(code == 200 and d.get("ok") and pr.get("ok") and "zz_geheim" not in sql.lower(),
                  f"[{n}/2] {frage[:45]} – geprüft, ohne fremde Tabelle ({time.time() - t0:.1f} s, "
                  f"{d.get('runden')} Runden)", (code, d.get("error"), pr.get("fehler"), sql[:200]))
            print("       " + " ".join(sql.split())[:240])
    code, d = ruf("/api/sql/frage", TU, "POST", {"frage": "x" * 2001, "schemata": [S_ERP]})
    check(code == 400, "Ueberlange Frage abgewiesen (nicht gekuerzt)", code)
    code, d = ruf("/api/sql/frage", TU, "POST", {"frage": "Kunden je Land", "schemata": [S_ERP], "praefixe": ["a;b"]})
    check(code == 400 and "Präfix" in (d.get("error") or ""), "Ungueltiger Praefix: 400 vor jedem Modellaufruf", (code, d))
    code, d = ruf("/api/sql/frage", TU, "POST", {"frage": "Kunden je Land", "schemata": [S_ERP], "praefixe": ["xx"]})
    check(code == 200 and d.get("ok") is False and "eingegrenzt auf XX" in (d.get("error") or ""),
          "Praefix ohne Tabellen: Fehler nennt die Eingrenzung", (code, d))
    code, d = ruf("/api/sql/frage", TU, "POST", {"frage": "Welche Kunden haben keinen Auftrag?", "schemata": [S_ERP],
                                                 "praefixe": ["erp"]})
    check(code == 200 and d.get("ok") and d.get("praefixe") == ["ERP"]
          and set((d.get("praefixe_kontext") or {})) <= {"erp", "ERP"} and isinstance(d.get("gleichwertig"), list),
          "Mit Praefix: Antwort traegt Wahl, Herkunft des Ausschnitts und Zusammengelegtes",
          (code, d.get("error"), d.get("praefixe"), d.get("praefixe_kontext")))

    print("5. Loeschen wirkt")
    code, d = ruf(f"/api/sql/admin/schema/{S_GEH}/datei?pfad=hr", TA, "DELETE")
    check(code == 200 and d.get("dateien") == 1 and not (BASIS_DIR / S_GEH / "hr").exists(), "Ordner geloescht", (code, d))
    st = erfassung_abwarten()
    code, d = ruf(f"/api/sql/tabelle?name=hr.zz_geheim_q9&schemata={S_GEH}", TU)
    check(code == 404, "Nach der automatischen Erfassung ist die Tabelle weg", (code, st.get("ergebnis")))
    weg = dict(VOR_CFG, schemata=list(VOR_CFG.get("schemata") or []) + [dict(PROBE_FELDER, id=S_ERP, name="ERP-Probe-Q9")])
    code, d = ruf("/api/sql/admin", TA, "PUT", {"cfg": weg})
    check(code == 409 and [s["id"] for s in d.get("zu_loeschen") or []] == [S_GEH] and (BASIS_DIR / S_GEH).exists(),
          "Schema entfernen ohne Bestaetigung: 409, nichts geloescht", (code, d))
    code, d = ruf("/api/sql/admin", TA, "PUT", {"cfg": weg, "loeschen_bestaetigt": True})
    check(code == 200 and not (BASIS_DIR / S_GEH).exists(), "Mit Bestaetigung: Schema samt Ordner weg", (code, d.get("geloescht")))
finally:
    print("6. Wiederherstellen")
    try:
        if VOR_CFG is not None:
            ruf("/api/sql/admin", TA, "PUT", {"cfg": VOR_CFG, "loeschen_bestaetigt": True})
            erfassung_abwarten()
        ruf("/api/settings", TA, "POST", VOR_FREIGABE)
        if not VOR_SKILL:
            ruf("/api/skills/schema_graph/disable", TA, "POST", {})
    finally:
        if BASIS_DIR.exists():
            shutil.rmtree(BASIS_DIR, ignore_errors=True)
        if BASIS_WAR_DA:
            shutil.copytree(SICHERUNG / "sql_schema_graph", BASIS_DIR, symlinks=True)
        shutil.rmtree(SICHERUNG, ignore_errors=True)
    code, ad2 = ruf("/api/auth/ad_status", TA)
    check(ad2.get("schema_users", "") == VOR_FREIGABE["schema_allowed_users"]
          and ad2.get("schema_group", "") == VOR_FREIGABE["schema_allowed_group"], "Freigabe wie vorgefunden")
    code, adm2 = ruf("/api/sql/admin", TA)
    check(VOR_CFG is None or adm2.get("cfg") == VOR_CFG, "SQL-Konfiguration wie vorgefunden")
    check(skill_an() == VOR_SKILL, "Skill-Schalter wie vorgefunden (laut Dienst)", (skill_an(), VOR_SKILL))
    check(BASIS_DIR.exists() == BASIS_WAR_DA, "data/sql_schema_graph wie vorgefunden", BASIS_DIR.exists())

print(f"\nBilanz: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
