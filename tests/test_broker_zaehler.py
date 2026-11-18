#!/usr/bin/env python3
"""Waechter: Nutzungszaehler getrennt von der Freigabeliste (Haertung B7, 18.11.2026).

Solange ``count``/``last_used`` in ``/etc/jarvis/broker-policy.json`` standen,
schrieb der Broker die Freigabeliste im Betrieb alle 30 s neu – AIDE meldete
sie bei JEDER Pruefung als geaendert, und ein deny->allow von Hand waere im
Dauerrauschen untergegangen (auf DEV gemessen). Jetzt stehen die Zaehler in
einer eigenen Datei, die Policy-Datei aendert sich nur noch beim Anlegen,
Entscheiden und Entfernen.

Gemessen am VERHALTEN der echten ``backend/broker/policy.py`` im
Wegwerf-Verzeichnis (Bytes und mtime der Dateien, nicht der Quelltext):
  [1] N Ops auf bestehende Eintraege + flush: Policy-Datei BYTE-GLEICH,
      Zaehlerdatei zaehlt N
  [2] dasselbe mit Flush nach JEDER Op (ZAEHLER_FLUSH_S = 0) – auch das
      Schreiben der Zaehler fasst die Policy nicht an
  [3] neue Op / Entscheidung / Entfernen aendern die Policy-Datei; Entfernen
      nimmt den Zaehler mit
  [4] Altbestand (Zaehler noch IN der Policy): wird beim Lesen uebernommen,
      OHNE die Policy dafuer neu zu schreiben; eine spaetere Entscheidung
      bereinigt die Policy ohne Zaehlerverlust (4b: auch ohne vorherigen Flush)
  [5] Leser: list_ops, decide, Meta-Op broker.policy_list, Admin-Konsole
      ``liste`` und die Felder, die die Oberflaeche (Root-Freigaben) liest
  [6] Rechte: beide Dateien 0600
  [7] Zaehlerdatei nicht schreibbar: Op laeuft trotzdem, nichts geht verloren
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import contextlib
import hashlib
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OK = FAIL = 0


def check(name, bed, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  -> " + str(detail)) if detail != "" else ""))


def abbruch(text):
    print("ABBRUCH: " + text)
    sys.exit(2)


SK = Path(tempfile.mkdtemp(prefix="broker_zaehler_"))
os.environ["JARVIS_BROKER_POLICY"] = str(SK / "broker-policy.json")
os.environ["JARVIS_BROKER_AUDIT"] = str(SK / "audit.jsonl")
os.environ.pop("JARVIS_BROKER_ZAEHLER", None)      # die Ableitung selbst wird gemessen
os.environ["JARVIS_BROKER_FREIGABE_KEY"] = str(SK / "freigabe.key")
os.environ["JARVIS_BROKER_FREIGABE_STATE"] = str(SK / "freigabe.state")
from backend.broker import policy as P  # noqa: E402

for name, pfad in (("Policy", P.POLICY_FILE), ("Zaehler", P.ZAEHLER_FILE), ("Audit", P.AUDIT_FILE)):
    if not str(pfad).startswith(str(SK)):
        abbruch(f"{name}-Datei zeigt aus dem Sandkasten heraus: {pfad}")
if P.ZAEHLER_FILE == P.POLICY_FILE:
    abbruch("Zaehler- und Policy-Datei sind dieselbe Datei")


def md5(pfad):
    try:
        return hashlib.md5(Path(pfad).read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def mtime(pfad):
    try:
        return Path(pfad).stat().st_mtime_ns
    except FileNotFoundError:
        return None


def zaehler(key, feld="count"):
    """Wert aus der Zaehlerdatei; fehlt etwas: None (FAIL statt Absturz)."""
    try:
        return json.loads(P.ZAEHLER_FILE.read_text())["ops"].get(key, {}).get(feld)
    except Exception:  # noqa: BLE001
        return None


def zaehler_keys():
    try:
        return set(json.loads(P.ZAEHLER_FILE.read_text())["ops"])
    except Exception:  # noqa: BLE001
        return set()


def eintrag(key):
    return {e["key"]: e for e in P.list_ops()}.get(key, {})


def zuruecksetzen():
    for f in (P.POLICY_FILE, P.ZAEHLER_FILE):
        with contextlib.suppress(FileNotFoundError):
            f.unlink()
    P._offen.clear()
    P._cache["daten"] = P._cache["stempel"] = None
    P._letzter_flush = 0.0


A = "systemctl:restart:jarvis.service"
B = "unlock_screen"
N = 40
FLUSH_ALT = P.ZAEHLER_FLUSH_S

try:
    # ── [1] gebuendelt, Policy unberuehrt ──────────────────────────────────
    print("\n[1] N Ops auf bestehende Eintraege")
    zuruecksetzen()
    P.check(A, "systemctl", "d", "jarvis", True)
    P.check(B, "unlock_screen", "d", "jarvis", True)
    if not P.POLICY_FILE.exists():
        abbruch("Positivkontrolle: neuer Eintrag hat keine Policy-Datei angelegt")
    md5_vor, mt_vor = md5(P.POLICY_FILE), mtime(P.POLICY_FILE)
    time.sleep(0.02)
    for _ in range(N):
        P.check(A, "systemctl", "d", "jarvis", True)
    P.check(B, "unlock_screen", "d", "jarvis", True)
    P.flush()
    check("Positivkontrolle: Zaehlerdatei existiert nach flush()", P.ZAEHLER_FILE.exists())
    check(f"Policy-Datei byte-gleich nach {N + 1} Ops + flush",
          md5(P.POLICY_FILE) == md5_vor)
    check("Policy-Datei: mtime unveraendert", mtime(P.POLICY_FILE) == mt_vor)
    check(f"Zaehlerdatei zaehlt {N} Wiederholungen (+1 Anlegen) fuer A",
          zaehler(A) == N + 1, zaehler(A))
    check("Zaehlerdatei zaehlt B getrennt (2)", zaehler(B) == 2, zaehler(B))
    check("last_used steht in der Zaehlerdatei", (zaehler(A, "last_used") or 0) > 0,
          zaehler(A, "last_used"))
    pol = json.loads(P.POLICY_FILE.read_text())
    check("Policy-Datei traegt KEINE Zaehlerfelder",
          not any(f in e for e in pol["ops"].values() for f in ("count", "last_used")),
          [sorted(e) for e in pol["ops"].values()])

    # ── [2] Flush nach jeder Op ────────────────────────────────────────────
    print("\n[2] Flush nach JEDER Op (ZAEHLER_FLUSH_S = 0)")
    P.ZAEHLER_FLUSH_S = 0
    md5_vor, mt_vor = md5(P.POLICY_FILE), mtime(P.POLICY_FILE)
    z_vor = mtime(P.ZAEHLER_FILE)
    time.sleep(0.02)
    for _ in range(N):
        P.check(A, "systemctl", "d", "jarvis", True)
    check("Positivkontrolle: Zaehlerdatei wurde wirklich geschrieben",
          mtime(P.ZAEHLER_FILE) != z_vor and zaehler(A) == 2 * N + 1, zaehler(A))
    check("Policy-Datei byte-gleich, obwohl jede Op Zaehler schreibt",
          md5(P.POLICY_FILE) == md5_vor)
    check("Policy-Datei: mtime unveraendert", mtime(P.POLICY_FILE) == mt_vor)
    P.ZAEHLER_FLUSH_S = FLUSH_ALT

    # ── [3] Aenderungen, die die Policy schreiben MUESSEN ──────────────────
    print("\n[3] neue Op / Entscheidung / Entfernen")
    md5_vor = md5(P.POLICY_FILE)
    K = "shell_root:sha256:" + "b" * 64
    check("neue Op: pending", P.check(K, "shell_root", "x", "jarvis", False) == P.PENDING)
    check("neue Op aendert die Policy-Datei sofort", md5(P.POLICY_FILE) != md5_vor)
    check("neue Op: Zaehler 1", eintrag(K).get("count") == 1, eintrag(K).get("count"))
    md5_vor = md5(P.POLICY_FILE)
    P.decide(K, P.ALLOW, "admin")
    check("Entscheidung aendert die Policy-Datei", md5(P.POLICY_FILE) != md5_vor)
    check("... und wirkt", json.loads(P.POLICY_FILE.read_text())["ops"][K]["decision"] == P.ALLOW)
    md5_vor = md5(P.POLICY_FILE)
    P.decide(A, P.DENY, "admin")
    check("deny auf einer Systemop aendert die Policy-Datei", md5(P.POLICY_FILE) != md5_vor)
    check("... Zaehler von A bleibt erhalten", eintrag(A).get("count") == 2 * N + 1,
          eintrag(A).get("count"))
    md5_vor = md5(P.POLICY_FILE)
    check("Entfernen gelingt", P.remove(K) is True)
    check("Entfernen aendert die Policy-Datei", md5(P.POLICY_FILE) != md5_vor)
    check("Entfernen nimmt den Zaehler aus der Zaehlerdatei", K not in zaehler_keys(),
          sorted(zaehler_keys()))
    P.check(K, "shell_root", "x", "jarvis", False)
    check("neu auftauchender Eintrag zaehlt ab 1 (erbt nichts)", eintrag(K).get("count") == 1,
          eintrag(K).get("count"))

    # ── [4] Altbestand ─────────────────────────────────────────────────────
    print("\n[4] Altbestand: Zaehler noch in der Policy-Datei")
    zuruecksetzen()
    t0 = int(time.time()) - 3600
    alt = {"version": 1, "ops": {
        A: {"key": A, "op": "systemctl", "description": "d", "decision": "allow", "auto": True,
            "first_seen": t0, "requested_by": "jarvis", "decided_by": "auto", "decided_at": t0,
            "count": 1000, "last_used": t0},
        B: {"key": B, "op": "unlock_screen", "description": "d", "decision": "deny",
            "auto": False, "first_seen": t0, "requested_by": "jarvis", "decided_by": "admin",
            "decided_at": t0, "count": 7, "last_used": t0},
    }}
    P.POLICY_FILE.write_text(json.dumps(alt, indent=2))
    os.chmod(P.POLICY_FILE, 0o600)
    md5_vor, mt_vor = md5(P.POLICY_FILE), mtime(P.POLICY_FILE)
    time.sleep(0.02)
    check("(Positivkontrolle) Altbestand lesbar: A erlaubt",
          P.check(A, "systemctl", "d", "jarvis", True) == P.ALLOW)
    for _ in range(N - 1):
        P.check(A, "systemctl", "d", "jarvis", True)
    P.flush()
    check("Migration beim Lesen: Policy-Datei byte-gleich", md5(P.POLICY_FILE) == md5_vor)
    check("Migration beim Lesen: Policy-mtime unveraendert", mtime(P.POLICY_FILE) == mt_vor)
    check(f"Zaehlerdatei uebernimmt den Altbestand (1000 + {N})", zaehler(A) == 1000 + N,
          zaehler(A))
    check("Zaehlerdatei uebernimmt auch einen nicht benutzten Eintrag (B = 7)",
          zaehler(B) == 7, zaehler(B))
    check("list_ops zeigt Altbestand + Neues", eintrag(A).get("count") == 1000 + N,
          eintrag(A).get("count"))
    P.decide(B, P.ALLOW, "admin")
    pol = json.loads(P.POLICY_FILE.read_text())
    check("Entscheidung bereinigt die Policy-Datei (keine Zaehlerfelder mehr)",
          not any(f in e for e in pol["ops"].values() for f in ("count", "last_used")),
          [sorted(e) for e in pol["ops"].values()])
    check("... ohne Zaehlerverlust (A, B)",
          eintrag(A).get("count") == 1000 + N and eintrag(B).get("count") == 7,
          (eintrag(A).get("count"), eintrag(B).get("count")))
    check("... last_used aus dem Altbestand bleibt", eintrag(B).get("last_used") == t0,
          eintrag(B).get("last_used"))

    print("\n[4b] Altbestand, Entscheidung OHNE vorherigen Flush")
    zuruecksetzen()
    P.POLICY_FILE.write_text(json.dumps(alt, indent=2))
    check("(Vorbedingung) keine Zaehlerdatei", not P.ZAEHLER_FILE.exists())
    P.decide(B, P.ALLOW, "admin")
    check("Zaehler aus dem Altbestand gerettet (A = 1000, B = 7)",
          eintrag(A).get("count") == 1000 and eintrag(B).get("count") == 7,
          (eintrag(A).get("count"), eintrag(B).get("count")))
    pol = json.loads(P.POLICY_FILE.read_text())
    check("Policy-Datei danach ohne Zaehlerfelder",
          not any(f in e for e in pol["ops"].values() for f in ("count", "last_used")))

    # ── [5] Leser ──────────────────────────────────────────────────────────
    print("\n[5] Leser der Zaehler")
    zuruecksetzen()
    P.check(A, "systemctl", "d", "jarvis", True)
    for _ in range(4):
        P.check(A, "systemctl", "d", "jarvis", True)
    # bewusst OHNE flush: die Leser sehen auch das noch nicht Geschriebene
    e = eintrag(A)
    check("list_ops: count inkl. ungeschriebener Zaehler (5)", e.get("count") == 5, e.get("count"))
    check("list_ops: last_used gesetzt", (e.get("last_used") or 0) > 0, e.get("last_used"))
    rueck = P.decide(A, P.ALLOW, "admin") or {}
    check("decide gibt den Eintrag mit count zurueck", rueck.get("count") == 5, rueck.get("count"))
    from backend.broker import meta  # noqa: E402
    res = meta.behandeln("broker.policy_list", {}) or {}
    m = {x.get("key"): x for x in res.get("ops") or []}.get(A, {})
    check("Meta-Op broker.policy_list (Oberflaeche) liefert count", m.get("count") == 5,
          m.get("count"))
    check("Meta-Op broker.policy_list liefert last_used", (m.get("last_used") or 0) > 0)
    from backend.broker import admin  # noqa: E402
    echt_euid = os.geteuid
    puffer = io.StringIO()
    try:
        os.geteuid = lambda: 0
        with contextlib.redirect_stdout(puffer):
            rc = admin._main(["liste"])
    finally:
        os.geteuid = echt_euid
    zeile = [z for z in puffer.getvalue().splitlines() if A in z]
    check("Admin-Konsole 'liste' zeigt den Zaehler (5x)",
          rc == 0 and len(zeile) == 1 and "(5x," in zeile[0], puffer.getvalue()[-300:])
    js = (ROOT / "frontend" / "js" / "security_incidents.js").read_text()
    a = js.find("renderBrokerOps: function")
    b = js.find("box.querySelectorAll", a)
    felder = set(re.findall(r"\be\.([a-z_]+)\b", js[a:b])) if a >= 0 and b > a else set()
    if not {"count", "last_used"} <= felder:
        abbruch("Schnitt renderBrokerOps findet count/last_used nicht: %s" % sorted(felder))
    fehlend = sorted(f for f in felder if f not in m)
    check("jedes Feld, das die Oberflaeche liest, kommt in der Meta-Antwort an",
          not fehlend, fehlend)

    # ── [6] Rechte ─────────────────────────────────────────────────────────
    print("\n[6] Rechte")
    for name, f in (("Policy", P.POLICY_FILE), ("Zaehler", P.ZAEHLER_FILE)):
        modus = stat.S_IMODE(f.stat().st_mode)
        check(f"{name}-Datei 0600", modus == 0o600, oct(modus))
    alte_umask = os.umask(0)
    try:
        P.check(A, "systemctl", "d", "jarvis", True)
        P.flush()
    finally:
        os.umask(alte_umask)
    check("Zaehlerdatei auch bei umask 0 nur 0600",
          stat.S_IMODE(P.ZAEHLER_FILE.stat().st_mode) == 0o600,
          oct(stat.S_IMODE(P.ZAEHLER_FILE.stat().st_mode)))

    # ── [7] Zaehlerdatei nicht schreibbar ──────────────────────────────────
    print("\n[7] Zaehlerdatei nicht schreibbar")
    vorher = eintrag(A).get("count") or 0         # VOR dem Umbiegen lesen
    check("(Positivkontrolle) Ausgangsstand gelesen", vorher > 0, vorher)
    echt_zf = P.ZAEHLER_FILE
    sperre = SK / "keinordner"
    sperre.write_text("x")                        # eine DATEI, wo ein Ordner sein muesste
    P.ZAEHLER_FILE = sperre / "zaehler.json"
    P.ZAEHLER_FLUSH_S = 0
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            r1 = P.check(A, "systemctl", "d", "jarvis", True)
            r2 = P.check("cert_kopie", "cert_kopie", "x", "system", True)
    except Exception as ex:  # noqa: BLE001
        r1 = r2 = "Ausnahme: %s" % ex
    check("bestehende Op laeuft trotzdem (allow)", r1 == P.ALLOW, r1)
    check("neue Op laeuft trotzdem (allow)", r2 == P.ALLOW, r2)
    P.ZAEHLER_FILE = echt_zf
    P.flush()
    check("nichts verloren: Zaehler holt nach, sobald die Datei wieder geht",
          eintrag(A).get("count") == vorher + 1 and zaehler("cert_kopie") == 1,
          (eintrag(A).get("count"), vorher, zaehler("cert_kopie")))
    P.ZAEHLER_FLUSH_S = FLUSH_ALT
finally:
    shutil.rmtree(SK, ignore_errors=True)

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
