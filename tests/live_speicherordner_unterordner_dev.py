#!/usr/bin/env python3
"""Live auf DEV: ein Unterordner als Speicherordner einer Wissensgruppe.

Durchstich ueber die ECHTEN Endpunkte: zwei Probegruppen bekommen je einen
Unterordner DESSELBEN Wurzelordners, ein Probe-Editor der einen Gruppe sieht
in /wissen nur seinen, laedt nur dorthin hoch und kann den Speicherordner
nicht umhaengen. Dazu der Gruppen-Dialog "Berechtigungen" (PATCH mit
Unterordner in ``folders``) – der scheiterte vorher mit 400.

⚠ DIESE PROBE AENDERT DEN BESTAND und stellt ihn wieder her: Probeordner
werden angelegt und entfernt, das Gruppen-Manifest wird am Ende byte-genau
zurueckgeschrieben (knowledge_groups liest es bei jedem Aufruf von der Platte).
Die hochgeladene Probedatei wird geloescht, bevor ein Indexlauf sie sieht.

Aufruf auf DEV (Tokens brauchen den Hauptschluessel):
  bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python \
      tests/live_speicherordner_unterordner_dev.py <globaler-wissens-editor> <testbenutzer>

<testbenutzer> (optional) muss sich anmelden duerfen und darf KEIN globaler
Wissens-Editor sein (auf DEV ist das nur ein AD-Konto: der lokale Admin ist
globaler Editor). Fehlt er, laufen die Abschnitte 0–2, Abschnitt 3 bleibt
ungemessen und der Lauf endet mit Exit 2 – nicht gruen. Ein Konto – ein erfundenes Konto bekommt an jedem Endpunkt 403 (NOT_AUTHORIZED),
die Probe saehe dann nur die Anmeldeschranke. Er wird fuer die Dauer der Probe
Editor der Probegruppe A; die Wiederherstellung des Manifests nimmt das zurueck.
"""
import atexit
import json
import shutil
import ssl
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

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
        # (info,) statt info: ein Tupel als Info wuerde sonst als Argumentliste
        # gelesen, und die Fehlermeldung selbst WARF (live auf DEV gesehen).
        print("  FAIL %s%s" % (text, ("  [%s]" % (info,)) if info else ""))


from backend import main as M                                      # noqa: E402
from backend import knowledge_groups as KG                         # noqa: E402

if len(sys.argv) < 2:
    print("ABBRUCH – Aufruf: … live_speicherordner_unterordner_dev.py "
          "<globaler-wissens-editor> [<testbenutzer>]")
    sys.exit(2)
ADMIN = sys.argv[1]
if not M._may_edit_knowledge(ADMIN):
    print("ABBRUCH – '%s' ist kein globaler Wissens-Editor" % ADMIN)
    sys.exit(2)
SONDE = sys.argv[2] if len(sys.argv) > 2 else None
# Die Anmeldeschranke wird ueber HTTP geprueft (Abschnitt 0), NICHT ueber
# M._login_still_allowed: das schreibt nebenbei in den AD-Cache.
if SONDE and M._may_edit_knowledge(SONDE):
    print("ABBRUCH – '%s' ist globaler Wissens-Editor, sieht also alles" % SONDE)
    sys.exit(2)
# Testmaterial baut der Erzeuger: die echte Anmeldung schreibt _display_name ins Token.
T_ADMIN = M.generate_token(M._display_name(ADMIN))
time.sleep(1.1)                     # Register: zwei Tokens derselben Sekunde
T_SONDE = M.generate_token(M._display_name(SONDE)) if SONDE else None

WURZEL = next((f for f in M._kb_current_folder_list() if f.startswith("data/rag/")), None)
if WURZEL is None:
    print("ABBRUCH – kein Wissensordner unter data/rag konfiguriert")
    sys.exit(2)
PROJ = Path("/opt/jarvis")
A = "%s/_probe_so_a" % WURZEL
B = "%s/_probe_so_b" % WURZEL
B2 = "%s/_probe_so_b2" % WURZEL          # Praefix-Nachbar von B
for p in (A + "/tief", B, B2):
    (PROJ / p).mkdir(parents=True, exist_ok=False)
MANIFEST_VOR = KG.MANIFEST_PATH.read_bytes()


def aufraeumen():
    for p in (A, B, B2):
        shutil.rmtree(PROJ / p, ignore_errors=True)
    if KG.MANIFEST_PATH.read_bytes() != MANIFEST_VOR:
        KG.MANIFEST_PATH.write_bytes(MANIFEST_VOR)


atexit.register(aufraeumen)


def ruf(pfad, methode="GET", rumpf=None, token=T_ADMIN, roh=None, kopf=None):
    daten = roh if roh is not None else (None if rumpf is None else json.dumps(rumpf).encode())
    r = urllib.request.Request(BASIS + pfad, data=daten, method=methode)
    r.add_header("Authorization", "Bearer " + token)
    if rumpf is not None:
        r.add_header("Content-Type", "application/json")
    for k, v in (kopf or {}).items():
        r.add_header(k, v)
    try:
        with urllib.request.urlopen(r, context=_KTX, timeout=120) as a:
            return a.status, json.loads(a.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:                                          # noqa: BLE001
            return e.code, {}
    except Exception as e:                                         # noqa: BLE001
        return 0, {"_fehler": str(e)}


def hochladen(ordner, gruppe, token):
    grenze = "----probe" + uuid.uuid4().hex
    teile = []
    for name, wert in (("folder", ordner), ("groups", gruppe)):
        teile.append(('--%s\r\nContent-Disposition: form-data; name="%s"\r\n\r\n%s\r\n'
                      % (grenze, name, wert)).encode())
    teile.append(('--%s\r\nContent-Disposition: form-data; name="files"; '
                  'filename="_probe_so.md"\r\nContent-Type: text/markdown\r\n\r\n'
                  % grenze).encode() + b"# Probe\r\n")
    roh = b"".join(teile) + ("--%s--\r\n" % grenze).encode()
    return ruf("/api/wissen/upload", "POST", roh=roh, token=token,
               kopf={"Content-Type": "multipart/form-data; boundary=" + grenze})


print("0. Positivkontrolle")
s, d = ruf("/api/wissen/scope")
check("Admin-Token gilt im Dienst (scope 200)", s == 200, s)
if s != 200:
    sys.exit(2)
if SONDE:
    s, d = ruf("/api/wissen/scope", token=T_SONDE)
    check("Sonden-Token gilt im Dienst (scope 200)", s == 200, (s, d))
    if s != 200:
        print("ABBRUCH – die Sonde darf sich nicht anmelden; Abschnitt 3 waere nicht messbar")
        sys.exit(2)
s, ga = ruf("/api/knowledge/groups", "POST", {"name": "_probe_so_A"})
s2, gb = ruf("/api/knowledge/groups", "POST", {"name": "_probe_so_B"})
if s != 200 or s2 != 200:
    print("ABBRUCH – Probegruppen nicht angelegt (%s/%s)" % (s, s2))
    sys.exit(2)
GA, GB = ga["group"]["id"], gb["group"]["id"]

print("\n1. Unterordner als Speicherordner zuweisen (Verwaltung)")
s, d = ruf("/api/knowledge/folders/groups", "POST", {"path": A, "groups": [GA]})
check("Unterordner A -> Gruppe A: 200", s == 200, (s, d))
s, d = ruf("/api/knowledge/folders/groups", "POST", {"path": B, "groups": [GB]})
check("Unterordner B -> Gruppe B: 200", s == 200, (s, d))
s, d = ruf("/api/knowledge/folders/groups", "POST", {"path": WURZEL + "/_gibt_es_nicht", "groups": [GA]})
check("nicht vorhandener Unterordner: 404", s == 404, s)
s, d = ruf("/api/knowledge/folders/groups", "POST", {"path": A + "/../_probe_so_b", "groups": [GA]})
check("'..'-Pfad: 404", s == 404, s)
fa = (KG.get_group(GA) or {}).get("folders")
check("Manifest: Gruppe A fuehrt genau A", fa == [A], fa)

print("\n2. Dialog 'Berechtigungen' (PATCH) mit Unterordnern")
s, d = ruf("/api/knowledge/groups/" + GA, "PATCH",
           {"editors_users": SONDE, "editors_group": "", "folders": [A, A + "/tief"]})
check("PATCH mit neuem Unterordner: 200 (vorher 400)", s == 200, (s, d))
s, d = ruf("/api/knowledge/groups/" + GA, "PATCH", {"folders": [A, WURZEL + "/_gibt_es_nicht"]})
check("PATCH mit nicht vorhandenem Ordner: 400", s == 400, s)
s, d = ruf("/api/knowledge/groups/" + GA, "PATCH", {"folders": [A]})
check("zurueck auf A: 200", s == 200, (s, d))

print("\n3. /wissen als Editor der Gruppe A")
s, d = ruf("/api/wissen/scope", token=T_SONDE) if SONDE else (None, {})
if SONDE:
    check("scope als Editor der Gruppe A: 200", s == 200, s)
else:
    print("  -- NICHT GEMESSEN: kein Testbenutzer angegeben")
if s == 200:
    pfade = [f["path"] for f in d.get("folders", [])]
    check("Sonde sieht A samt Teilbaum", pfade == [A, A + "/tief"], pfade)
    check("Sonde sieht B nicht", B not in pfade and B2 not in pfade, pfade)
    s, d = hochladen(A + "/tief", GA, T_SONDE)
    check("Upload in A/tief: 200", s == 200 and d.get("saved"), (s, d))
    s, d = hochladen(B, GA, T_SONDE)
    check("Upload in B: 403", s == 403, (s, d))
    s, d = hochladen(A + "/../_probe_so_b", GA, T_SONDE)
    check("Upload ueber '..' nach B: 403", s == 403, (s, d))
    s, d = ruf("/api/wissen/subfolders", "PUT", {"path": A, "new_name": "_probe_so_x"}, token=T_SONDE)
    check("Speicherordner A umbenennen: 400", s == 400, (s, d))
    s, d = ruf("/api/wissen/subfolders/move", "POST", {"path": A, "target": A + "/tief"}, token=T_SONDE)
    check("Speicherordner A verschieben: abgewiesen", s in (400, 403), (s, d))
    check("A liegt unveraendert da", (PROJ / A / "tief").is_dir())
    for f in (PROJ / A / "tief").glob("_probe_so*"):
        f.unlink()

aufraeumen()
check("Manifest byte-gleich wiederhergestellt", KG.MANIFEST_PATH.read_bytes() == MANIFEST_VOR)
check("Probeordner entfernt", not any((PROJ / p).exists() for p in (A, B, B2)))
print("\nErgebnis: %d OK, %d FAIL%s" % (_ok, _fail, "" if SONDE else " (Abschnitt 3 nicht gemessen)"))
sys.exit(1 if _fail else (0 if SONDE else 2))
