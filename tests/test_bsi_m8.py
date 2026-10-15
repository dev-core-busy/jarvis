#!/usr/bin/env python3
"""Waechter BSI M8 – Dienstbenutzer ohne Systemprotokolle, Einsicht ueber den Broker.

  [A] ``backend/broker/journal.pruefen``: nur Jarvis-Einheiten, Zeilen gedeckelt,
      Zeitangaben/Suche ohne Optionsschmuggel.
  [B] ``argv``: jeder Wert als ``--option=wert``, keine Shell.
  [C] ``aus_befehl``: einfache journalctl-Aufrufe werden uebersetzt (auch mit
      ``| grep``), alles Uneindeutige bleibt unuebersetzt (None).
  [D] Broker-Op ``journal_lesen`` (echter Code, subprocess-Attrappe): Pruefung
      VOR dem Aufruf, Geheimnisse geschwaerzt, Kappung beziffert, auditiert
      (kein READONLY_OPS-Eintrag), automatisch erlaubt.
  [E] Agenten-Shell: ein privilegierter journalctl-Aufruf geht ueber die Op, die
      Fortsetzung hinter ``|`` laeuft lokal auf der Broker-Ausgabe; ohne
      Broker-Recht (Sandbox) und bei unuebersetzbaren Aufrufen kein Op-Aufruf.
  [F] ``haertung_installieren.sh`` mit Attrappen: entfernt adm/systemd-journal,
      startet ein Backend nach, das die Gruppen noch traegt; HAERTUNG=aus und
      ein Testlauf ohne Attrappe fassen nichts an. ``setup_broker.sh`` setzt die
      Gruppen nicht mehr.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

OK = FAIL = 0


def check(name, bed, info=""):
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("  [" + str(info)[:300] + "]") if info else ""))


def abbruch(grund):
    print("ABBRUCH: " + grund)
    sys.exit(2)


TMP = Path(tempfile.mkdtemp(prefix="bsi_m8_"))

# backend.config nur als Stub (der echte Import schreibt die Live-settings.json)
_cfg = types.ModuleType("backend.config")


class _C:
    SECRET_KEY = "testgeheimnis-bsi-m8"
    COMMAND_TIMEOUT = 30

    def get_setting(self, k, d=None):
        return d


_cfg.config = _C()
sys.modules["backend.config"] = _cfg

try:
    from backend.broker import journal
except Exception as e:  # noqa: BLE001
    abbruch("backend.broker.journal nicht importierbar: %s" % e)


def wirft(fn, *a):
    try:
        fn(*a)
        return False
    except ValueError:
        return True


# ═════════════════════════════════════════════════════════════════════════════
print("\n[A] pruefen")
for e, soll in [("jarvis", "jarvis.service"), ("jarvis.service", "jarvis.service"),
                ("jarvis-broker", "jarvis-broker.service"),
                ("whatsapp-bridge.service", "whatsapp-bridge.service"),
                ("jarvis-firewall.service", "jarvis-firewall.service")]:
    check("erlaubt: %s" % e, journal.pruefen({"einheit": e})["einheit"] == soll)
for e in ["", "ssh", "sshd.service", "systemd-logind", "cron.service", "jarvis;id",
          "jarvis service", "../jarvis", "-ujarvis", "jarvis\nssh", "*", "jarvis*", "JARVIS"]:
    check("abgewiesen: %r" % e, wirft(journal.pruefen, {"einheit": e}))
check("Rand-Leerraum wird normiert, weitergegeben wird nur der Name",
      journal.pruefen({"einheit": " jarvis\n"})["einheit"] == "jarvis.service")
check("ohne Einheit abgewiesen (sonst ganzes Systemjournal)", wirft(journal.pruefen, {}))
check("Zeilen-Vorgabe", journal.pruefen({"einheit": "jarvis"})["zeilen"] == journal.ZEILEN_VORGABE)
check("Zeilen gedeckelt", journal.pruefen({"einheit": "jarvis", "zeilen": 10 ** 9})["zeilen"]
      == journal.ZEILEN_MAX)
check("Zeilen mindestens 1", journal.pruefen({"einheit": "jarvis", "zeilen": -5})["zeilen"] == 1)
check("Zeilen keine Zahl -> abgewiesen", wirft(journal.pruefen, {"einheit": "jarvis", "zeilen": "x"}))
check("Zeilen bool -> abgewiesen", wirft(journal.pruefen, {"einheit": "jarvis", "zeilen": True}))
for z in ["2026-10-12 08:00", "-1h", "yesterday", "10 min ago", "today"]:
    check("seit erlaubt: %r" % z, journal.pruefen({"einheit": "jarvis", "seit": z}).get("seit") == z)
for z in ["--output=json", "-o", "--file=/etc/shadow", "a;b", "x" * 41, "1h\n--x"]:
    check("seit abgewiesen: %r" % z[:20], wirft(journal.pruefen, {"einheit": "jarvis", "seit": z}))
check("prioritaet err", journal.pruefen({"einheit": "jarvis", "prioritaet": "err"})["prioritaet"] == "err")
check("prioritaet 3", journal.pruefen({"einheit": "jarvis", "prioritaet": "3"})["prioritaet"] == "3")
check("prioritaet 9 abgewiesen", wirft(journal.pruefen, {"einheit": "jarvis", "prioritaet": "9"}))
check("suche mit Zeilenumbruch abgewiesen", wirft(journal.pruefen, {"einheit": "jarvis", "suche": "a\nb"}))
check("suche zu lang abgewiesen",
      wirft(journal.pruefen, {"einheit": "jarvis", "suche": "x" * (journal.SUCHE_MAX + 1)}))

# ═════════════════════════════════════════════════════════════════════════════
print("\n[B] argv")
a = journal.argv(journal.pruefen({"einheit": "jarvis", "zeilen": 50, "seit": "-1h",
                                  "suche": "--file=/etc/shadow", "prioritaet": "err",
                                  "umgekehrt": True}))
check("erstes Element ist journalctl", a and a[0] == "journalctl", a)
check("Einheit als --unit=", "--unit=jarvis.service" in a, a)
check("Zeilen als --lines=", "--lines=50" in a, a)
check("Suche als EIN Argument --grep=… (kein Optionsschmuggel)",
      "--grep=--file=/etc/shadow" in a and "--file=/etc/shadow" not in a, a)
check("seit als --since=", "--since=-1h" in a, a)
check("ausser den festen Schaltern keine nackten Werte",
      all(x.startswith("-") for x in a[1:] if x not in ("short-iso",)), a)
check("kein --file / -D / --directory", not any(x.startswith(("--file", "-D", "--directory",
                                                              "--root", "-m", "--merge")) for x in a), a)

# ═════════════════════════════════════════════════════════════════════════════
print("\n[C] aus_befehl")
FAELLE = [
    ("journalctl -u jarvis -n 50 --no-pager", ({"einheit": "jarvis", "zeilen": "50"}, "")),
    ("journalctl -u jarvis.service --since '-1h' -p err",
     ({"einheit": "jarvis.service", "seit": "-1h", "prioritaet": "err"}, "")),
    ("journalctl -u jarvis | grep -i fehler | tail -5",
     ({"einheit": "jarvis"}, "grep -i fehler | tail -5")),
    ("sudo journalctl -ujarvis-broker -n10", ({"einheit": "jarvis-broker", "zeilen": "10"}, "")),
    ("/usr/bin/journalctl --unit=jarvis --lines=20 -o cat",
     ({"einheit": "jarvis", "zeilen": "20"}, "")),
    ('journalctl -u jarvis -g "a|b"', ({"einheit": "jarvis", "suche": "a|b"}, "")),
    ("journalctl -u jarvis -r -n 5", ({"einheit": "jarvis", "umgekehrt": True, "zeilen": "5"}, "")),
]
for befehl, soll in FAELLE:
    ist = journal.aus_befehl(befehl)
    check("uebersetzt: %s" % befehl, ist == soll, ist)
for befehl in ["journalctl", "journalctl -n 50", "journalctl -f -u jarvis",
               "journalctl -u jarvis -u ssh", "journalctl -u jarvis; id",
               "journalctl -u jarvis && id", "journalctl -u jarvis || echo x",
               "journalctl -u jarvis > /tmp/x", "journalctl -u $(id -un)",
               "journalctl -u jarvis --vacuum-time=1s", "journalctl -k", "ls | journalctl -u jarvis",
               "journalctl -u jarvis |", "echo journalctl -u jarvis", "journalctl -u 'jarvis",
               "journalctl -u jarvis -D /var/log/journal", "journalctl -u jarvis --file=/x",
               # nur der Kopf-Filter traegt hier: der Wert waere fuer den Broker gueltig,
               # die Shell haette aber `id` ausgefuehrt bzw. umgeleitet
               "journalctl -u jarvis -g x;id", "journalctl -u jarvis -g x>/tmp/y",
               "journalctl -u jarvis -g x&"]:
    check("nicht uebersetzt: %s" % befehl, journal.aus_befehl(befehl) is None,
          journal.aus_befehl(befehl))
# Die Uebersetzung lehnt nicht ab, was der Broker ablehnt – sie reicht weiter, der Broker prueft:
check("Einheit wird erst im Broker geprueft (ssh -> uebersetzt, pruefen wirft)",
      journal.aus_befehl("journalctl -u ssh") == ({"einheit": "ssh"}, "")
      and wirft(journal.pruefen, {"einheit": "ssh"}))

# ═════════════════════════════════════════════════════════════════════════════
print("\n[D] Broker-Op journal_lesen")
try:
    from backend.broker import ops
except Exception as e:  # noqa: BLE001
    abbruch("backend.broker.ops nicht importierbar: %s" % e)

AUFRUFE = []


class _R:
    def __init__(self, out, rc=0, err=""):
        self.stdout, self.returncode, self.stderr = out, rc, err


AUSGABE = {"text": "", "rc": 0}


def _run(cmd, **kw):
    AUFRUFE.append((cmd, kw))
    return _R(AUSGABE["text"], AUSGABE["rc"])


_echt_run = ops.subprocess.run
ops.subprocess.run = _run
try:
    AUSGABE.update(text="2026-10-12T08:00 jarvis GET /ws/vnc?ticket=GEHEIM123 200\nzweite Zeile\n", rc=0)
    r = ops._op_journal_lesen({"einheit": "jarvis", "zeilen": 20}, None)
    check("Op lief (Positivkontrolle: Attrappe erreicht)", len(AUFRUFE) == 1, AUFRUFE)
    cmd, kw = AUFRUFE[0] if AUFRUFE else ([], {})
    check("Aufruf als Argumentliste (keine Shell)", isinstance(cmd, list) and not kw.get("shell"), kw)
    check("Aufruf = journal.argv", cmd == journal.argv(journal.pruefen({"einheit": "jarvis", "zeilen": 20})), cmd)
    check("Zeitdeckel gesetzt", (kw.get("timeout") or 0) > 0, kw)
    check("ok + rc 0", r.get("ok") is True and r.get("rc") == 0, r)
    check("Ticket in der Ausgabe geschwaerzt", "GEHEIM123" not in r.get("stdout", "")
          and "zweite Zeile" in r.get("stdout", ""), r.get("stdout"))
    AUFRUFE.clear()
    r = ops._op_journal_lesen({"einheit": "ssh"}, None)
    check("fremde Einheit: kein journalctl-Aufruf", not AUFRUFE, AUFRUFE)
    check("fremde Einheit: rc 2 mit Grund", r.get("rc") == 2 and "nicht erlaubt" in r.get("stderr", ""), r)
    # kurze Zeilen: die Kappung soll gemessen werden, nicht die Schwaerzung
    _lang = "zeile\n" * (journal.AUSGABE_MAX // 6 + 100)
    _zuviel = len(_lang) - journal.AUSGABE_MAX
    AUSGABE.update(text=_lang, rc=0)
    r = ops._op_journal_lesen({"einheit": "jarvis"}, None)
    out = r.get("stdout", "")
    check("Kappung beziffert, Hinweis VORN",
          out.startswith("[gekappt: die ersten %d Zeichen fehlen]" % _zuviel)
          and r.get("gekappt") == _zuviel, out[:60])
    AUSGABE.update(text="", rc=1)
    r = ops._op_journal_lesen({"einheit": "jarvis", "suche": "nichtda"}, None)
    check("--grep ohne Treffer gilt nicht als Fehler", r.get("ok") is True, r)
finally:
    ops.subprocess.run = _echt_run

# Laufzeit des Schwaerzens ist linear (vorher quadratisch: 1-MB-Zeile hing).
import time  # noqa: E402
from backend import url_geheimnis  # noqa: E402
check("Schwaerzen wirkt noch (Positivkontrolle)",
      url_geheimnis.schwaerzen("https://u:geheim@h/x?token=abc") == "https://u:***@h/x?token=***",
      url_geheimnis.schwaerzen("https://u:geheim@h/x?token=abc"))
_t = time.monotonic()
url_geheimnis.schwaerzen("x" * 40_000)
_d1 = time.monotonic() - _t
_t = time.monotonic()
url_geheimnis.schwaerzen("x" * 4_000)
_d0 = time.monotonic() - _t
check("Schwaerzen: 10-fache Laenge kostet nicht das ~100-fache (%.3f s / %.3f s)" % (_d1, _d0),
      _d1 < max(_d0 * 30, 0.05), (_d1, _d0))

eintrag = ops._REGISTRY.get("journal_lesen")
check("Op registriert", eintrag is not None)
if eintrag:
    check("automatisch erlaubt (default_allow)", eintrag[3] is True)
    check("Key nennt die Einheit", eintrag[1]({"einheit": "jarvis"}) == "journal_lesen:jarvis")
check("auditiert (nicht in READONLY_OPS)", "journal_lesen" not in ops.READONLY_OPS)

# ═════════════════════════════════════════════════════════════════════════════
print("\n[E] Agenten-Shell")
_bc = types.ModuleType("backend.broker_client")
_bc.AUFRUFE = []
_bc.ANTWORT = {}


async def _call(op, args, user="", timeout=0, stream_cb=None):
    _bc.AUFRUFE.append((op, dict(args), user))
    return dict(_bc.ANTWORT)


_bc.call = _call
sys.modules["backend.broker_client"] = _bc
import backend  # noqa: E402
backend.broker_client = _bc
try:
    from backend.tools import shell as sh
except Exception as e:  # noqa: BLE001
    abbruch("backend.tools.shell nicht importierbar: %s" % e)

tool = sh.ShellTool()


async def _lauf(befehl, timeout=20, **kw):
    return await tool.execute(command=befehl, timeout=timeout, **kw)


if os.geteuid() == 0:
    abbruch("als root gestartet – der Broker-Zweig ist fuer root bewusst aus")
_bc.ANTWORT = {"ok": True, "rc": 0, "decision": "allowed",
               "stdout": "a Fehler eins\nb alles gut\nc Fehler zwei\n", "stderr": ""}
LOOP = asyncio.new_event_loop()
erg = LOOP.run_until_complete(_lauf("journalctl -u jarvis -n 30 | grep Fehler",
                                    _root_broker=True, _broker_user="admin"))
check("privilegiert: journal_lesen aufgerufen",
      [a[0] for a in _bc.AUFRUFE] == ["journal_lesen"], _bc.AUFRUFE)
if _bc.AUFRUFE:
    op, args, user = _bc.AUFRUFE[0]
    check("Argumente uebersetzt", args.get("einheit") == "jarvis" and args.get("zeilen") == "30", args)
    check("Benutzer weitergereicht", user == "admin", user)
check("Fortsetzung | grep lief lokal auf der Broker-Ausgabe",
      "Fehler eins" in erg and "Fehler zwei" in erg and "alles gut" not in erg, erg)

_bc.AUFRUFE.clear()
_bc.ANTWORT = {"ok": False, "decision": "unknown-op", "error": "Unbekannte Broker-Operation"}
erg = LOOP.run_until_complete(_lauf("journalctl -u jarvis", _root_broker=True))
check("alter Broker: Meldung nennt Neustart", "neu starten" in erg, erg)
_bc.ANTWORT = {"ok": False, "rc": 2, "decision": "allowed", "stdout": "",
               "stderr": "Einheit nicht erlaubt: 'ssh'"}
erg = LOOP.run_until_complete(_lauf("journalctl -u ssh", _root_broker=True))
check("abgewiesene Einheit: Grund kommt beim Modell an", "nicht erlaubt" in erg, erg)

_bc.AUFRUFE.clear()
LOOP.run_until_complete(_lauf("journalctl -u jarvis -n 1"))
check("ohne Broker-Recht (z.B. Sandbox): keine Op", not _bc.AUFRUFE, _bc.AUFRUFE)
LOOP.run_until_complete(_lauf("journalctl -f -u jarvis --since -1s", timeout=2, _root_broker=True))
check("unuebersetzbar (-f): keine journal_lesen-Op",
      "journal_lesen" not in [a[0] for a in _bc.AUFRUFE], _bc.AUFRUFE)
LOOP.close()

# ═════════════════════════════════════════════════════════════════════════════
print("\n[F] haertung_installieren.sh / setup_broker.sh")
SK = ROOT / "deploy" / "security" / "haertung_installieren.sh"
if not SK.is_file():
    abbruch("haertung_installieren.sh fehlt")


def attrappe(name, rumpf):
    p = TMP / name
    p.write_text("#!/bin/bash\n" + rumpf)
    p.chmod(0o755)
    return p


LOG = TMP / "aufrufe.log"
FID = attrappe("id.sh", 'echo "$FAKE_GRUPPEN"\n')
FGP = attrappe("gpasswd.sh", 'echo "gpasswd $*" >> "%s"\nexit 0\n' % LOG)
FSC = attrappe("systemctl.sh", 'echo "systemctl $*" >> "%s"\n'
               'case "$1" in show) echo 4242;; is-active) exit 1;; esac\nexit 0\n' % LOG)
FGE = attrappe("getent.sh", 'case "$2" in adm) echo "adm:x:4:";; systemd-journal) echo "systemd-journal:x:999:";;'
               ' *) exit 2;; esac\n')


def haertung(gruppen_user, gruppen_proc, conf="", attrappe_gp=True):
    d = TMP / ("h_%d" % len(list(TMP.glob("h_*"))))
    (d / "units").mkdir(parents=True)
    (d / "logrotate").mkdir()
    (d / "proc" / "4242").mkdir(parents=True)
    (d / "proc" / "4242" / "status").write_text("Name:\tpython\nGroups:\t%s\n" % gruppen_proc)
    (d / "units" / "jarvis.service").write_text("[Service]\nUser=jarvis\n")
    if conf:
        (d / "broker.conf").write_text(conf)
    if LOG.exists():
        LOG.unlink()
    env = dict(os.environ, JARVIS_HAERTUNG_TEST="1", JARVIS_UNIT_DIR=str(d / "units"),
               JARVIS_LOGROTATE_DIR=str(d / "logrotate"), JARVIS_BROKER_CONF=str(d / "broker.conf"),
               JARVIS_BROKER_AUDIT=str(d / "audit.jsonl"), JARVIS_SYSTEMCTL=str(FSC),
               JARVIS_ID=str(FID), JARVIS_GETENT=str(FGE), JARVIS_PROC_ROOT=str(d / "proc"),
               JARVIS_CRED_ROOT=str(d / "cred"), FAKE_GRUPPEN=gruppen_user)
    if attrappe_gp:
        env["JARVIS_GPASSWD"] = str(FGP)
    else:
        env.pop("JARVIS_GPASSWD", None)
    env.pop("JARVIS_GEHEIMNIS_DATEI", None)
    r = subprocess.run(["bash", str(SK), "/opt/jarvis"], env=env, capture_output=True,
                       text=True, timeout=60)
    return r, (LOG.read_text() if LOG.exists() else "")


r, log = haertung("jarvis adm video systemd-journal", "4 44 999")
check("Positivkontrolle: Skript lief (rc 0) und fragte systemctl", r.returncode == 0
      and "systemctl show" in log, (r.returncode, log, r.stderr[-300:]))
check("adm entfernt", "gpasswd -d jarvis adm" in log, log)
check("systemd-journal entfernt", "gpasswd -d jarvis systemd-journal" in log, log)
check("video bleibt (Kamera)", "video" not in "".join(z for z in log.splitlines() if "gpasswd" in z), log)
check("Backend mit den Gruppen -> genau ein Nachstart",
      log.count("try-restart --no-block jarvis.service") == 1, log)
r, log = haertung("jarvis video", "44")
check("ohne die Gruppen: kein gpasswd", "gpasswd" not in log, log)
check("Backend ohne die Gruppen: kein Nachstart", "restart" not in log, log)
r, log = haertung("jarvis video", "4 44")
check("Mitgliedschaft schon weg, Prozess traegt adm noch -> Nachstart",
      "try-restart --no-block jarvis.service" in log, log)
r, log = haertung("jarvis adm systemd-journal", "4 999", conf="HAERTUNG=aus\n")
check("HAERTUNG=aus: Gruppen bleiben", "gpasswd" not in log, log)
check("HAERTUNG=aus: kein Nachstart wegen M8", "restart" not in log, log)
r, log = haertung("jarvis adm systemd-journal", "4 999", attrappe_gp=False)
check("Testlauf ohne gpasswd-Attrappe fasst keine echte Gruppe an",
      "gpasswd" not in log and "systemctl show" not in log, log)

sb = (ROOT / "deploy" / "security" / "setup_broker.sh").read_text(encoding="utf-8")
schleifen = [z for z in sb.splitlines() if z.strip().startswith("for grp in")]
check("setup_broker.sh: Gruppenschleife gefunden (Positivkontrolle)", bool(schleifen), schleifen)
check("setup_broker.sh setzt adm/systemd-journal nicht mehr",
      schleifen and not any(("adm" in z.split()) or ("systemd-journal" in z) for z in schleifen), schleifen)

# Kein Backend-Code liest das Systemjournal selbst (ausser ueber den Broker)
treffer = []
for p in (ROOT / "backend").rglob("*.py"):
    if "broker" in p.parts:
        continue
    baum = ast.parse(p.read_text(encoding="utf-8"))
    # Docstrings/blosse Ausdrucks-Zeichenketten sind Begruendung, kein Aufruf
    doku = {id(n.value) for n in ast.walk(baum) if isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Constant)}
    for n in ast.walk(baum):
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doku \
                and n.value.startswith("journalctl"):
            treffer.append(str(p.relative_to(ROOT)))
        if isinstance(n, ast.List) and n.elts and isinstance(n.elts[0], ast.Constant) \
                and n.elts[0].value == "journalctl":
            treffer.append(str(p.relative_to(ROOT)))
check("Backend ruft journalctl nicht selbst auf (nur der Broker)", not treffer, treffer)

shutil.rmtree(TMP, ignore_errors=True)
print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
