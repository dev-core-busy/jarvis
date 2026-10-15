#!/usr/bin/env python3
"""BSI H10 – Sandbox Pflicht, fail-closed, Ressourcengrenzen, Netz.

Befund H10 (BSI-Abgleich 2026-09-29): Shell-Sandbox optional, Blocklisten-
basiert, ohne Netz-Namespace und ohne Ressourcenlimits; privilegierte Shell
gar nicht isoliert. Betreiberentscheid 2026-10-05: Abbruch statt Weiterlaufen
ohne Isolation; Sandbox fuer Administratoren per Schalter (Vorgabe AUS).

Gemessen wird – alles AUSGEFUEHRT, nicht am Text:

1. ``sandbox_grenzen``: Klemmen der Grenzen (kein Wert hebt sie auf),
   ``systemd-run``-Praefix, Wahl des Sandbox-Benutzers (leere Einstellung
   schaltet NICHT ab), nftables-Regeln der Loopback-Sperre, ``bereit()`` mit
   jedem fehlenden Baustein einzeln.
2. ``lauf_tmp.sandbox_befehl``: ``pflicht`` wirft statt still zurueckzufallen;
   Aufbau des Aufrufs; dazu ECHTE bwrap-Laeufe: ``--unshare-net`` trennt einen
   Loopback-Dienst ab, ``verbergen`` macht ein Verzeichnis unsichtbar, beides
   mit Positivkontrolle.
3. Broker-Op ``sandbox_lauf`` mit Attrappen fuer root-Teile: jeder Fehlerweg
   ohne Ausfuehrung, Grenzen werden im Broker geklemmt, der netzgesperrte
   Benutzer laeuft immer ohne Netz, die alte Op ``sandbox_exec`` gibt es
   nicht mehr (ein alter Broker sagt "unbekannte Op" statt auszufuehren).
4. ``ShellTool``: ohne privates /tmp kein Broker-Aufruf; alter Broker und
   Abweisung werden dem Benutzer gemeldet; Grenz-Hinweis.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.

    python3 tests/test_bsi_h10.py
"""
import asyncio
import os
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f" – {detail}" if detail else ""))


def abschnitt(t):
    print(f"\n── {t} " + "─" * max(0, 66 - len(t)))


def abbruch(text):
    print(f"ABBRUCH: {text}")
    sys.exit(2)


# ── Sandkasten + Attrappe fuer backend.config (der echte Import schreibt die
# Live-settings.json zurueck – Register) ──────────────────────────────────────
SANDKASTEN = Path(tempfile.mkdtemp(prefix="jarvis_h10_"))
EINSTELLUNGEN = {}


class _Config:
    COMMAND_TIMEOUT = 30
    SETTINGS_FILE = SANDKASTEN / "settings.json"

    def get_setting(self, key, default=None):
        return EINSTELLUNGEN.get(key, default)

    def save_setting(self, key, value):
        EINSTELLUNGEN[key] = value


_cfg_mod = types.ModuleType("backend.config")
_cfg_mod.config = _Config()
sys.modules["backend.config"] = _cfg_mod

try:
    from backend import sandbox_grenzen as SG
    from backend import lauf_tmp as LT
except Exception as e:  # noqa: BLE001
    abbruch(f"Module nicht importierbar: {type(e).__name__}: {e}")

if "backend.config" not in sys.modules or sys.modules["backend.config"] is not _cfg_mod:
    abbruch("backend.config ist nicht die Attrappe")

# Verwaltungswurzeln in den Sandkasten – nichts in diesem Test darf das echte
# /tmp/jarvis-arbeit anfassen.
LT.ARBEIT_ROOT = SANDKASTEN / "arbeit"
LT.ANH_ROOT = SANDKASTEN / "anhaenge"
if not str(LT.ARBEIT_ROOT).startswith(str(SANDKASTEN)):
    abbruch("ARBEIT_ROOT zeigt aus dem Sandkasten")


# ── 1. sandbox_grenzen ───────────────────────────────────────────────────────
abschnitt("1a. Grenzen werden geklemmt, nie aufgehoben")
g = SG.grenzen_pruefen({})
pruefe(g == SG.STANDARD, "leer -> Vorgabe", str(g))
g = SG.grenzen_pruefen({"speicher_mb": 0, "prozesse": -1, "cpu_prozent": 0})
pruefe(g["speicher_mb"] == SG.BEREICH["speicher_mb"][0]
       and g["prozesse"] == SG.BEREICH["prozesse"][0]
       and g["cpu_prozent"] == SG.BEREICH["cpu_prozent"][0],
       "0 / -1 heben die Grenze NICHT auf, sondern landen an der Untergrenze", str(g))
g = SG.grenzen_pruefen({"speicher_mb": 10 ** 9, "prozesse": 10 ** 9, "cpu_prozent": 10 ** 9})
pruefe(all(g[k] == SG.BEREICH[k][1] for k in g), "riesige Werte landen an der Obergrenze", str(g))
g = SG.grenzen_pruefen({"speicher_mb": True, "prozesse": "abc", "cpu_prozent": None})
pruefe(g == SG.STANDARD, "bool/Text/None -> Vorgabe (True ist NICHT 1 MB)", str(g))
g = SG.grenzen_pruefen("kein dict")
pruefe(g == SG.STANDARD, "kein dict -> Vorgabe")
g = SG.grenzen_pruefen({"speicher_mb": "1024"})
pruefe(g["speicher_mb"] == 1024, "Zahl als Text wird gelesen (Formulareingabe)")

abschnitt("1b. systemd-run-Praefix")
p = SG.scope_praefix({"speicher_mb": 0, "prozesse": 50, "cpu_prozent": 150}, 100)
pruefe(bool(p) and p[0] == SG.SYSTEMD_RUN and "--scope" in p and p[-1] == "--",
       "systemd-run --scope … --", str(p[:3]))
props = [p[i + 1] for i, t in enumerate(p[:-1]) if t == "-p"]
pruefe("MemoryMax=%dM" % SG.BEREICH["speicher_mb"][0] in props,
       "Speichergrenze geklemmt im Praefix", str(props))
pruefe("MemorySwapMax=0" in props, "kein Ausweichen in den Swap")
pruefe("TasksMax=50" in props and "CPUQuota=150%" in props, "Prozesse und CPU", str(props))
lz = [x for x in props if x.startswith("RuntimeMaxSec=")]
lz_s = int(lz[0].split("=", 1)[1]) if len(lz) == 1 else -1
pruefe(lz_s >= 100 + SG.LAUFZEIT_PUFFER_S,
       "Laufzeitgrenze liegt HINTER dem Befehls-Timeout (der Timeout meldet zuerst)", str(lz))
lz2 = [x for x in SG.scope_praefix({}, 10 ** 9) if x.startswith("RuntimeMaxSec=")]
pruefe(len(lz2) == 1 and int(lz2[0].split("=", 1)[1]) <= SG.LAUFZEIT_MAX_S,
       "Laufzeitgrenze hat eine Obergrenze", str(lz2))
u1 = [x for x in SG.scope_praefix({}, 10) if x.startswith("--unit=")]
u2 = [x for x in SG.scope_praefix({}, 10) if x.startswith("--unit=")]
pruefe(len(u1) == 1 and len(u2) == 1 and u1 != u2, "jeder Lauf bekommt einen eigenen Scope-Namen")
pruefe(SG.grenze_vermutlich_getroffen(137) and SG.grenze_vermutlich_getroffen(-9)
       and not SG.grenze_vermutlich_getroffen(1) and not SG.grenze_vermutlich_getroffen(0),
       "beendet-durch-Scope wird erkannt, gewoehnliche Fehler nicht")

abschnitt("1c. Sandbox-Benutzer: Pflicht statt Option")
UIDS = {"jarvis_sandbox": 997, "jarvis_sandbox_noinet": 996, "jarvis": 1001,
        "jarvis_sandbox_root": 0}
_uid_echt = SG._uid


def mit_uids(uids):
    SG._uid = lambda n: uids.get(n)


try:
    mit_uids(UIDS)
    EINSTELLUNGEN.clear()
    pruefe(SG.sandbox_benutzer(True) == ("jarvis_sandbox", ""),
           "LEERE Einstellung -> jarvis_sandbox (schaltet nicht mehr ab)", str(SG.sandbox_benutzer(True)))
    pruefe(SG.sandbox_benutzer(False)[0] == "jarvis_sandbox_noinet",
           "ohne Internet -> netzgesperrter Benutzer")
    mit_uids({"jarvis_sandbox": 997})
    pruefe(SG.sandbox_benutzer(False)[0] == "jarvis_sandbox",
           "ohne Internet, netzgesperrter Benutzer fehlt -> jarvis_sandbox (Netz per Namespace zu)")
    mit_uids({})
    u, grund = SG.sandbox_benutzer(True)
    pruefe(u == "" and bool(grund), "kein Sandbox-Benutzer -> leer MIT Grund", repr(grund))
    mit_uids(UIDS)
    EINSTELLUNGEN["sandbox_shell_user"] = "jarvis"
    u, _ = SG.sandbox_benutzer(True)
    pruefe(u == "jarvis_sandbox", "Einstellung ohne Praefix wird nie benutzt", u)
    EINSTELLUNGEN["sandbox_shell_user"] = "jarvis_sandbox_root"
    u, _ = SG.sandbox_benutzer(True)
    pruefe(u == "jarvis_sandbox", "Einstellung mit uid 0 wird nie benutzt", u)
    mit_uids({"jarvis": 1001, "jarvis_sandbox_root": 0})
    u, grund = SG.sandbox_benutzer(True)
    pruefe(u == "" and "ungueltig" in grund, "ungueltige Einstellung und kein Ersatz -> Grund nennt sie", grund)
    # Regel ueber alle Faelle: zurueck kommt nur, was das Praefix traegt und nicht uid 0 hat
    alle = []
    for uids in (UIDS, {}, {"jarvis": 1001}, {"jarvis_sandbox_root": 0}):
        mit_uids(uids)
        for s in ("", "jarvis", "root", "jarvis_sandbox_root", "jarvis_sandbox", "jarvis_sandbox_noinet"):
            EINSTELLUNGEN["sandbox_shell_user"] = s
            EINSTELLUNGEN["sandbox_shell_user_noinet"] = s
            for inet in (True, False):
                alle.append(SG.sandbox_benutzer(inet)[0])
    schlecht = [u for u in alle if u and (not u.startswith("jarvis_sandbox") or UIDS.get(u) == 0)]
    pruefe(len(alle) == 4 * 6 * 2 and not schlecht,
           f"Regel: kein Ergebnis ohne Praefix oder mit uid 0 ({len(alle)} Faelle)", str(schlecht))
finally:
    SG._uid = _uid_echt
    EINSTELLUNGEN.clear()

abschnitt("1d. Loopback-Sperre (nftables-Text)")
regeln = SG.lo_regeln([996, 997])
zeilen = [z.strip() for z in regeln.splitlines() if z.strip()]
wirk = [z for z in zeilen if z.endswith(("accept", "reject", "drop")) or " reject" in z]
pruefe(any('oif "lo"' in z and "reject" in z for z in wirk), "Positivkontrolle: es gibt eine Loopback-Abweisung")
pruefe(all("skuid" in z for z in wirk if "reject" in z or z.endswith("drop")),
       "jede Abweisung ist an die Sandbox-UIDs gebunden (Kernel-Sockets bleiben frei)")
pruefe(all("996" in z and "997" in z for z in wirk if "skuid" in z), "alle UIDs in jeder Regel")
dns = [i for i, z in enumerate(wirk) if "dport 53 accept" in z]
rej = [i for i, z in enumerate(wirk) if "reject" in z]
pruefe(len(dns) == 2 and rej and max(dns) < min(rej), "DNS-Ausnahme steht VOR der Abweisung")
pruefe(f"delete table inet {SG.NFT_TABELLE}" in regeln and regeln.count(f"table inet {SG.NFT_TABELLE}") == 3,
       "atomarer Ersatz (anlegen, loeschen, neu)")
if os.geteuid() != 0:
    ok_lo, grund_lo = SG.lo_sperre_sicherstellen()
    pruefe(ok_lo is False and "root" in grund_lo, "ohne root: Sperre NICHT als gesetzt gemeldet")

abschnitt("1e. bereit(): jeder fehlende Baustein verhindert den Lauf")


class _OsRoot:
    def __getattr__(self, n):
        return getattr(os, n)

    @staticmethod
    def geteuid():
        return 0


_sicher = {k: getattr(SG, k) for k in ("os", "SYSTEMD_RUN", "lo_sperre_sicherstellen", "_uid")}
_sicher_lt = {k: getattr(LT, k) for k in ("bwrap_verfuegbar", "isolation_gewuenscht")}
_sr = SANDKASTEN / "systemd-run"
_sr.write_text("")


def stand(**ueber):
    SG.os = _OsRoot() if ueber.get("root", True) else os
    SG.SYSTEMD_RUN = str(_sr) if ueber.get("systemd_run", True) else str(SANDKASTEN / "fehlt")
    SG._uid = (lambda n: UIDS.get(n)) if ueber.get("benutzer", True) else (lambda n: None)
    LT.bwrap_verfuegbar = lambda *a, **k: ueber.get("bwrap", True)
    LT.isolation_gewuenscht = lambda: ueber.get("iso", True)
    SG.lo_sperre_sicherstellen = lambda *a, **k: ((True, "") if ueber.get("lo", True)
                                                   else (False, "Loopback-Sperre nicht setzbar"))


try:
    stand()
    pruefe(SG.bereit("jarvis_sandbox") == (True, ""), "Positivkontrolle: alles da -> bereit")
    for name, ueber in (("kein root", {"root": False}), ("kein systemd-run", {"systemd_run": False}),
                        ("kein bwrap", {"bwrap": False}), ("Isolation abgeschaltet", {"iso": False}),
                        ("Loopback-Sperre fehlt", {"lo": False}), ("Benutzer fehlt", {"benutzer": False})):
        stand(**ueber)
        ok, grund = SG.bereit("jarvis_sandbox")
        pruefe(ok is False and bool(grund), f"{name} -> nicht bereit, mit Grund", repr(grund))
    stand()
    pruefe(SG.bereit("jarvis")[0] is False, "Benutzer ohne Praefix -> nicht bereit")
    pruefe(SG.bereit("jarvis_sandbox_root")[0] is False, "Sandbox-Name mit uid 0 -> nicht bereit")
finally:
    for k, v in _sicher.items():
        setattr(SG, k, v)
    for k, v in _sicher_lt.items():
        setattr(LT, k, v)

abschnitt("1f. Schalter 'auch fuer Administratoren'")
# Seit 2026-10-11 Vorgabe AN (Betreiberentscheid), abschaltbar. Nur ein echtes
# bool ist eine Entscheidung; alles andere faellt auf die (sicherere) Vorgabe.
EINSTELLUNGEN.clear()
pruefe(SG.auch_admins() is True, "nicht gesetzt -> Vorgabe AN")
EINSTELLUNGEN[SG.EINSTELLUNG_ADMINS] = True
pruefe(SG.auch_admins() is True, "True schaltet ein")
EINSTELLUNGEN[SG.EINSTELLUNG_ADMINS] = False
pruefe(SG.auch_admins() is False, "False schaltet AUS (abschaltbar)")
for v in ("true", "false", 1, 0, "1", None):
    EINSTELLUNGEN[SG.EINSTELLUNG_ADMINS] = v
    pruefe(SG.auch_admins() is True, f"{v!r} ist keine Entscheidung -> Vorgabe AN")
EINSTELLUNGEN.clear()

abschnitt("1g. Bestand behaelt sein Verhalten (Vorgabe nur fuer neue Installationen)")
EINSTELLUNGEN.clear()
pruefe(SG.vorgabe_festschreiben(bestand=True) is False,
       "Bestand ohne Schalter -> False festgeschrieben")
pruefe(EINSTELLUNGEN.get(SG.EINSTELLUNG_ADMINS) is False and SG.auch_admins() is False,
       "… und wirkt: Admins bleiben ohne Sandbox wie bisher")
pruefe(SG.vorgabe_festschreiben(bestand=False) is None,
       "zweiter Lauf fasst den gesetzten Wert NICHT an")
pruefe(EINSTELLUNGEN.get(SG.EINSTELLUNG_ADMINS) is False, "… Wert unveraendert")
EINSTELLUNGEN.clear()
pruefe(SG.vorgabe_festschreiben(bestand=False) is True,
       "Erstinstallation -> Vorgabe AN festgeschrieben")
pruefe(EINSTELLUNGEN.get(SG.EINSTELLUNG_ADMINS) is True, "… und steht in der Einstellung")
EINSTELLUNGEN.clear()
EINSTELLUNGEN[SG.EINSTELLUNG_ADMINS] = True
pruefe(SG.vorgabe_festschreiben(bestand=True) is None and EINSTELLUNGEN[SG.EINSTELLUNG_ADMINS] is True,
       "ein Bestand, der AN gewaehlt hat, bleibt AN")
EINSTELLUNGEN.clear()

# Verdrahtung: der Startup-Hook ruft die Funktion mit dem Merkmal aus config,
# und config bestimmt das Merkmal VOR Config() (danach existiert die Datei).
import ast as _ast
_main = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
_hook = next((n for n in _ast.walk(_ast.parse(_main))
              if isinstance(n, _ast.AsyncFunctionDef) and n.name == "startup_sandbox_admins_vorgabe"), None)
pruefe(_hook is not None and any(
    isinstance(d, _ast.Call) and getattr(d.func, "attr", "") == "on_event" for d in _hook.decorator_list),
    "Startup-Hook startup_sandbox_admins_vorgabe ist registriert")
_rufe = [c for c in _ast.walk(_hook)] if _hook else []
pruefe(any(isinstance(c, _ast.Call) and getattr(c.func, "attr", "") == "vorgabe_festschreiben"
           for c in _rufe), "… und ruft vorgabe_festschreiben")
pruefe(any(isinstance(c, _ast.Constant) and c.value == "SETTINGS_VORHER_DA" for c in _rufe)
       and any(isinstance(c, _ast.Constant) and c.value is True for c in _rufe),
       "… mit SETTINGS_VORHER_DA, fehlend = Bestand (True)")
_cfg = (ROOT / "backend" / "config.py").read_text(encoding="utf-8")
_i_merk = _cfg.find("\nSETTINGS_VORHER_DA = ")
_i_inst = _cfg.find("\nconfig = Config()")
pruefe(0 < _i_merk < _i_inst, "config.py bestimmt SETTINGS_VORHER_DA VOR config = Config()")


# ── 2. lauf_tmp.sandbox_befehl ──────────────────────────────────────────────
abschnitt("2a. pflicht: kein stiller Rueckfall")
_bv = LT.bwrap_verfuegbar
try:
    LT.bwrap_verfuegbar = lambda *a, **k: False
    alt = LT.sandbox_befehl("jarvis_sandbox", "echo hi", SANDKASTEN)
    pruefe("bwrap" not in alt and "runuser" in alt, "ohne pflicht: Bestandsverhalten (Rueckfall) bleibt")
    try:
        LT.sandbox_befehl("jarvis_sandbox", "echo hi", SANDKASTEN, pflicht=True)
        pruefe(False, "mit pflicht und ohne bwrap wird geworfen")
    except LT.IsolationFehlt:
        pruefe(True, "mit pflicht und ohne bwrap wird geworfen (kein Lauf ohne Isolation)")
    try:
        LT.sandbox_befehl("jarvis_sandbox", "echo hi", None, pflicht=True)
        pruefe(False, "auch ohne Lauf-Verzeichnis wird geworfen")
    except LT.IsolationFehlt:
        pruefe(True, "auch ohne Lauf-Verzeichnis wird geworfen")
finally:
    LT.bwrap_verfuegbar = _bv

abschnitt("2b. Aufbau des Aufrufs")
VERB = SANDKASTEN / "verborgen"
VERB.mkdir()
(VERB / "geheim.txt").write_text("x")
LAUF = SANDKASTEN / "lauf"
LAUF.mkdir()


def argv(**kw):
    basis = dict(sandbox_user="jarvis_sandbox", command="echo hi", lauf_dir=LAUF,
                 _pruefen=True, pflicht=True)
    basis.update(kw)
    return shlex.split(LT.sandbox_befehl(**basis))


a = argv(praefix=SG.scope_praefix({}, 30))
i_sr = a.index(SG.SYSTEMD_RUN) if SG.SYSTEMD_RUN in a else -1   # nur Positionsvergleich, Vorkommen oben geprueft
i_ru = a.index("runuser") if "runuser" in a else -1
pruefe(0 <= i_sr < i_ru, "Grenzen (systemd-run) stehen VOR runuser", f"{i_sr} {i_ru}")
pruefe("--unshare-net" not in argv(), "ohne ohne_netz: kein --unshare-net (Positivkontrolle)")
a = argv(ohne_netz=True)
pruefe("--unshare-net" in a and "--unshare-pid" in a, "ohne_netz -> --unshare-net")
a = argv(lauf_dir=None, verbergen=[str(VERB)])
paare = list(zip(a, a[1:]))
pruefe(("--tmpfs", str(VERB)) in paare, "verbergen -> --tmpfs <verzeichnis>")
pruefe(not any(x == "--bind" and a[i + 2:i + 3] == ["/tmp"] for i, x in enumerate(a)),
       "ohne Lauf-Verzeichnis: KEIN Bind auf /tmp (echtes /tmp)")
pruefe(not any("umask 002" in x for x in a), "ohne Lauf-Verzeichnis: keine umask-Lockerung")
pruefe(any("umask 002" in x for x in argv()), "mit Lauf-Verzeichnis: umask 002 wie bisher (Positivkontrolle)")
try:
    argv(verbergen=[str(SANDKASTEN / "gibts-nicht")])
    pruefe(False, "fehlendes zu verbergendes Verzeichnis wird abgewiesen")
except LT.IsolationFehlt:
    pruefe(True, "fehlendes zu verbergendes Verzeichnis wird abgewiesen (bwrap legte es sonst als Sandbox-Benutzer an)")

abschnitt("2c. ECHTE bwrap-Laeufe")
BW = LT.BWRAP
if not os.path.exists(BW):
    abbruch(f"{BW} fehlt – Abschnitt 2c kann nicht messen")
probe = subprocess.run([BW, "--dev-bind", "/", "/", "--unshare-net", "--unshare-pid", "--proc", "/proc",
                        "--", "/bin/true"], capture_output=True, text=True, timeout=20)
if probe.returncode != 0:
    abbruch(f"bwrap hier nicht lauffaehig: {probe.stderr.strip()[:160]}")

srv = socket.socket()
srv.bind(("127.0.0.1", 0))
srv.listen(8)
PORT = srv.getsockname()[1]


def _annehmen():
    while True:
        try:
            c, _ = srv.accept()
            c.close()
        except OSError:
            return


threading.Thread(target=_annehmen, daemon=True).start()
VERBINDE = ("python3 -c \"import socket;s=socket.socket();s.settimeout(3)\n"
            "try:\n s.connect(('127.0.0.1',%d));print('VERBUNDEN')\n"
            "except Exception as e:\n print('ZU',type(e).__name__)\"" % PORT)


def echt(command, **kw):
    b = LT.sandbox_befehl("", command, kw.pop("lauf_dir", LAUF), _pruefen=True, pflicht=True, **kw)
    r = subprocess.run(["/bin/bash", "-c", b], capture_output=True, text=True, timeout=30)
    return (r.stdout or "") + (r.stderr or "")


aus = echt(VERBINDE)
pruefe("VERBUNDEN" in aus, "Positivkontrolle: ohne Netz-Namespace erreicht der Lauf den Loopback-Dienst", aus.strip())
aus = echt(VERBINDE, ohne_netz=True)
pruefe("ZU" in aus and "VERBUNDEN" not in aus, "mit ohne_netz: Loopback-Dienst des Hosts unerreichbar", aus.strip())
aus = echt("ls " + shlex.quote(str(VERB)), lauf_dir=None)
pruefe("geheim.txt" in aus, "Positivkontrolle: ohne verbergen ist die Datei sichtbar", aus.strip())
aus = echt("ls -A " + shlex.quote(str(VERB)) + "; echo ENDE", lauf_dir=None, verbergen=[str(VERB)])
pruefe("geheim.txt" not in aus and "ENDE" in aus, "mit verbergen: Datei im Lauf NICHT VORHANDEN", aus.strip())
pruefe((VERB / "geheim.txt").exists(), "auf dem Host bleibt sie unberuehrt")
aus = echt("ls /proc | grep -c '^[0-9]'", lauf_dir=None)
try:
    n_innen = int(aus.strip().splitlines()[-1]) if aus.strip() else 10 ** 6
except ValueError:
    n_innen = 10 ** 6
n_host = sum(1 for x in os.listdir("/proc") if x.isdigit())
pruefe(n_host > 20 and n_innen < 10,
       "auch ohne Lauf-Verzeichnis eigene Prozesssicht (Admins mit Schalter)", f"innen {n_innen}, Host {n_host}")
srv.close()


# ── 3. Broker-Op sandbox_lauf ───────────────────────────────────────────────
abschnitt("3. Broker-Op sandbox_lauf")
os.environ.setdefault("JARVIS_BROKER_POLICY", str(SANDKASTEN / "policy.json"))
os.environ.setdefault("JARVIS_BROKER_AUDIT", str(SANDKASTEN / "audit.jsonl"))
try:
    from backend.broker import ops as OPS
except Exception as e:  # noqa: BLE001
    abbruch(f"backend.broker.ops nicht importierbar: {type(e).__name__}: {e}")

pruefe("sandbox_lauf" in OPS._REGISTRY, "Op sandbox_lauf ist registriert")
pruefe("sandbox_exec" not in OPS._REGISTRY,
       "alte Op sandbox_exec ist WEG (ein alter Broker antwortet dem neuen Backend 'unbekannte Op')")
pruefe("sandbox_teardown" not in OPS._REGISTRY, "kein 'Sandbox deaktivieren' mehr im Broker")
r = OPS.dispatch("sandbox_exec", {"user": "jarvis_sandbox", "command": "id"})
pruefe(r.get("decision") == "unknown-op" and "rc" not in r,
       "Positivkontrolle der Ablehnung alter Aufrufer: unknown-op ohne Ausfuehrung", str(r)[:120])

import pwd as _pwd  # noqa: E402

_pw_echt = _pwd.getpwnam


class _Pw:
    def __init__(self, uid):
        self.pw_uid = uid


def _getpwnam(n):
    if n in UIDS:
        return _Pw(UIDS[n])
    raise KeyError(n)


AUFRUFE = []
_ss_echt = OPS._stream_shell
_rc = {"rc": 0}


def _ss(cmd, cwd, timeout, stream):
    AUFRUFE.append((cmd, cwd))
    return {"ok": _rc["rc"] == 0, "rc": _rc["rc"], "stdout": "x", "stderr": ""}


_sicher_op = {k: getattr(SG, k) for k in ("bereit",)}
_sicher_op_lt = {k: getattr(LT, k) for k in ("arbeit_bereitstellen", "einhaengepunkte",
                                              "bwrap_verfuegbar", "_wurzel_sicherstellen")}
_bereit = {"v": (True, "")}
_bereitstellen = {"v": LAUF}
try:
    _pwd.getpwnam = _getpwnam
    OPS._stream_shell = _ss
    SG.bereit = lambda u: _bereit["v"]
    LT.arbeit_bereitstellen = lambda k, u: _bereitstellen["v"]
    LT.einhaengepunkte = lambda *a, **k: None
    LT.bwrap_verfuegbar = lambda *a, **k: True
    LT._wurzel_sicherstellen = lambda p, m=0o755: Path(p).mkdir(parents=True, exist_ok=True)

    def op(**args):
        AUFRUFE.clear()
        basis = {"user": "jarvis_sandbox", "command": "echo hi", "timeout": 30, "arbeit": "0123abcd"}
        basis.update(args)
        res = OPS._op_sandbox_lauf(basis, None)
        return res, list(AUFRUFE)

    res, auf = op()
    w = auf[0][0] if auf else ""
    pruefe(len(auf) == 1 and "rc" in res, "Positivkontrolle: mit allen Bausteinen laeuft der Befehl", str(res)[:120])
    pruefe(SG.SYSTEMD_RUN in w and "MemoryMax=" in w and "TasksMax=" in w,
           "der Befehl laeuft unter Ressourcengrenzen", w[:120])
    pruefe(f"--bind {LAUF} /tmp" in w, "privates /tmp eingebunden")
    pruefe(res.get("isolation") is True and res.get("sandbox") is True and res.get("grenzen"),
           "Antwort bestaetigt Isolation, Sandbox und Grenzen")
    pruefe("--unshare-net" not in w, "jarvis_sandbox ohne ohne_netz: Netz bleibt (Positivkontrolle)")

    res, auf = op(user="jarvis_sandbox_noinet", ohne_netz=False)
    pruefe(auf and "--unshare-net" in auf[0][0], "netzgesperrter Benutzer laeuft IMMER ohne Netz")
    res, auf = op(ohne_netz=True)
    pruefe(auf and "--unshare-net" in auf[0][0] and res.get("ohne_netz") is True, "ohne_netz wird angewandt und gemeldet")

    res, auf = op(grenzen={"speicher_mb": 0, "prozesse": -1, "cpu_prozent": "x"})
    w = auf[0][0] if auf else ""
    pruefe("MemoryMax=%dM" % SG.BEREICH["speicher_mb"][0] in w
           and "TasksMax=%d" % SG.BEREICH["prozesse"][0] in w
           and "CPUQuota=%d%%" % SG.STANDARD["cpu_prozent"] in w,
           "der Broker klemmt die Grenzen selbst (Werte aus dem Backend sind nicht vertrauenswuerdig)", w[:160])

    _bereit["v"] = (False, "Isolation nicht verfuegbar")
    res, auf = op()
    pruefe(not auf and res.get("abgelehnt") and "rc" not in res,
           "nicht bereit -> abgewiesen, NICHTS ausgefuehrt", str(res)[:120])
    _bereit["v"] = (True, "")

    res, auf = op(arbeit="")
    pruefe(not auf and res.get("abgelehnt"), "ohne Kennung und ohne ohne_lauf -> abgewiesen (kein echtes /tmp fuer Domain-Benutzer)")
    res, auf = op(arbeit="", ohne_lauf="ja")
    pruefe(not auf and res.get("abgelehnt"), "ohne_lauf nur mit echtem True")

    _bereitstellen["v"] = None
    res, auf = op()
    pruefe(not auf and res.get("abgelehnt"), "Arbeitsverzeichnis nicht bereitstellbar -> abgewiesen (frueher: gemeinsames /tmp)")
    _bereitstellen["v"] = LAUF

    res, auf = op(arbeit="", ohne_lauf=True)
    w = auf[0][0] if auf else ""
    pruefe(auf and f"--tmpfs {LT.ARBEIT_ROOT}" in w and f"--tmpfs {LT.ANH_ROOT}" in w,
           "Administrator im echten /tmp: private Bereiche der Domain-Benutzer verdeckt", w[-200:])
    # Am ZERLEGTEN Aufruf: " /tmp --" als Text traefe das "--chdir /tmp --".
    _wa = shlex.split(w) if w else []
    pruefe(bool(_wa) and "--chdir" in _wa
           and not any(x == "--bind" and _wa[i + 2:i + 3] == ["/tmp"] for i, x in enumerate(_wa)),
           "Administrator: kein privates /tmp gebunden")
    pruefe(res.get("isolation") is False, "isolation=False (kein privates /tmp) – keine Pfad-Uebersetzung im Backend")

    res, auf = op(user="jarvis")
    pruefe(not auf and res.get("abgelehnt"), "Benutzer ohne Praefix -> abgewiesen")
    res, auf = op(user="jarvis_sandbox_root")
    pruefe(not auf and res.get("abgelehnt"), "Sandbox-Name mit uid 0 -> abgewiesen")

    LT.bwrap_verfuegbar = lambda *a, **k: False
    res, auf = op()
    pruefe(not auf and res.get("abgelehnt"),
           "bwrap faellt NACH bereit() aus -> sandbox_befehl wirft, abgewiesen statt Rueckfall")
    LT.bwrap_verfuegbar = lambda *a, **k: True

    _rc["rc"] = 137
    res, auf = op()
    pruefe(res.get("grenze_getroffen") is True, "rc 137 -> grenze_getroffen gemeldet")
    _rc["rc"] = 0
finally:
    _pwd.getpwnam = _pw_echt
    OPS._stream_shell = _ss_echt
    for k, v in _sicher_op.items():
        setattr(SG, k, v)
    for k, v in _sicher_op_lt.items():
        setattr(LT, k, v)


# ── 4. ShellTool ────────────────────────────────────────────────────────────
abschnitt("4. ShellTool")
BROKER = []
_antwort = {"v": {"ok": True, "rc": 0, "stdout": "hallo", "stderr": "", "decision": "allowed"}}


async def _call(op, args, user="", timeout=0, stream_cb=None):
    BROKER.append((op, dict(args)))
    return dict(_antwort["v"])


_bc = types.ModuleType("backend.broker_client")
_bc.call = _call
sys.modules["backend.broker_client"] = _bc
import backend as _backend_pkg  # noqa: E402
_backend_pkg.broker_client = _bc

try:
    from backend.tools.shell import ShellTool
except Exception as e:  # noqa: BLE001
    abbruch(f"backend.tools.shell nicht importierbar: {type(e).__name__}: {e}")

if os.geteuid() == 0:
    abbruch("Abschnitt 4 misst den Broker-Weg und darf nicht als root laufen (sonst Alt-Betrieb)")

T = ShellTool()


def shell(**kw):
    BROKER.clear()
    return asyncio.run(T.execute(**kw)), list(BROKER)


aus, b = shell(command="ls", _sandbox_user="jarvis_sandbox")
pruefe(not b and "NICHT ausgeführt" in aus,
       "Sandbox ohne privates /tmp und ohne Anforderung -> kein Broker-Aufruf, Meldung", aus[:100])

aus, b = shell(command="ls", _sandbox_user="jarvis_sandbox", _ohne_lauf=True,
               _grenzen={"speicher_mb": 0}, _ohne_netz=True)
pruefe(len(b) == 1 and b[0][0] == "sandbox_lauf", "Administrator mit Schalter: Op sandbox_lauf", str(b)[:120])
a1 = b[0][1] if b else {}
pruefe(a1.get("ohne_lauf") is True and a1.get("arbeit") == "" and a1.get("ohne_netz") is True,
       "Argumente: ohne_lauf, ohne Kennung, ohne_netz", str(a1)[:160])
pruefe(a1.get("grenzen", {}).get("speicher_mb") == SG.BEREICH["speicher_mb"][0],
       "Grenzen gehen geklemmt hinueber", str(a1.get("grenzen")))
pruefe("STDOUT" in aus and "hallo" in aus, "Positivkontrolle: Ergebnis kommt an", aus[:80])

_bv2 = LT.bwrap_verfuegbar
try:
    LT.bwrap_verfuegbar = lambda *a, **k: True
    with LT.lauf_scope("max.muster", False) as _lauf:
        if _lauf is None:
            abbruch("lauf_scope oeffnet trotz bwrap keinen Lauf")
        aus, b = shell(command="ls", _sandbox_user="jarvis_sandbox_noinet", _ohne_netz=True)
    a2 = b[0][1] if b else {}
    pruefe(len(b) == 1 and a2.get("arbeit") == _lauf.kennung and a2.get("ohne_lauf") is False,
           "Domain-Benutzer: Kennung des privaten /tmp geht mit, ohne_lauf=False", str(a2)[:160])
finally:
    LT.bwrap_verfuegbar = _bv2

_antwort["v"] = {"ok": False, "decision": "unknown-op", "error": "Unbekannte Broker-Operation: sandbox_lauf"}
aus, b = shell(command="ls", _sandbox_user="jarvis_sandbox", _ohne_lauf=True)
pruefe("NICHT ausgeführt" in aus and "veraltet" in aus, "alter Broker -> klare Meldung statt 'Fehler'", aus[:120])
_antwort["v"] = {"ok": False, "abgelehnt": "Isolation nicht verfuegbar (bubblewrap fehlt)",
                 "stdout": "", "stderr": "", "isolation": False, "decision": "allowed"}
aus, b = shell(command="ls", _sandbox_user="jarvis_sandbox", _ohne_lauf=True)
pruefe("NICHT ausgeführt" in aus and "bubblewrap" in aus and "KEINE Umgehung" in aus,
       "Abweisung des Brokers: Grund + keine Umgehung", aus[:160])
pruefe("nicht an deinen Rechten" in aus or "Das liegt nicht an" in aus,
       "Meldung sagt, dass es kein Rechtefehler des Benutzers ist")
_antwort["v"] = {"ok": False, "rc": 137, "stdout": "", "stderr": "Beendet", "decision": "allowed",
                 "grenze_getroffen": True, "grenzen": {"speicher_mb": 512}}
aus, b = shell(command="ls", _sandbox_user="jarvis_sandbox", _ohne_lauf=True)
pruefe("HINWEIS" in aus and "512 MB" in aus, "von der Grenze beendet -> Hinweis mit den Werten", aus[-200:])
_antwort["v"] = {"ok": False, "rc": 1, "stdout": "", "stderr": "kaputt", "decision": "allowed"}
aus, b = shell(command="ls", _sandbox_user="jarvis_sandbox", _ohne_lauf=True)
pruefe("HINWEIS: Der Befehl wurde von der Sandbox" not in aus, "gewoehnlicher Fehler -> kein Grenz-Hinweis")

shutil.rmtree(SANDKASTEN, ignore_errors=True)
print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(0 if _fail == 0 and _ok > 0 else 1)
