#!/usr/bin/env python3
"""Waechter: BSI H6 – TLS 1.2 nur mit Suites nach TR-02102-2.

Befund (BSI-Abgleich 2026-09-29, auf DEV nachgemessen 2026-10-04): Port 443 bot
unter TLS 1.2 nur ``ECDHE-RSA-AES128-SHA`` und ``ECDHE-RSA-AES256-SHA`` an –
uvicorns Vorgabe ``--ssl-ciphers TLSv1``.

Gemessen wird an der WIRKUNG:
  1. uvicorns EIGENE Kontext-Erzeugung (``uvicorn.Config(...).load()``) mit
     ``TLS12_SUITES`` baut den Serverkontext; dagegen laufen echte Handshakes
     ueber localhost – verbotene Suites/Protokolle muessen scheitern, erlaubte
     gelingen. Positivkontrolle je Messung: derselbe Client gegen uvicorns
     Vorgabe ``TLSv1`` (bzw. einen freizuegigen Server) KOMMT durch – sonst
     waere das Scheitern trivial.
  2. Jede Startstelle (Shell: uvicorn mit ``--ssl-certfile``; Python:
     ``uvicorn.run(..., ssl_certfile=...)``) uebergibt GENAU diese Suites. Die
     Shell-Zeilen gehen durch uvicorns eigenen Kommandozeilen-Parser (click),
     damit auch die Quotierung geprueft ist.

Braucht uvicorn (venv); startet sich ohne selbst mit ``venv/bin/python`` neu.
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import os
import re
import shlex
import socket
import ssl
import subprocess
from shutil import which as shutil_which
import sys
import tempfile
import threading
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    import uvicorn  # noqa: F401
    from uvicorn.config import Config
    from uvicorn.main import main as uvicorn_cli
except ImportError:
    venv_py = ROOT / "venv" / "bin" / "python"
    if venv_py.exists() and Path(sys.executable).resolve() != venv_py.resolve():
        os.execv(str(venv_py), [str(venv_py), __file__] + sys.argv[1:])
    print("ABBRUCH: uvicorn fehlt (venv/bin/python tests/test_bsi_tls.py)")
    sys.exit(2)

from backend.tls_richtlinie import TLS12_SUITES  # noqa: E402

OK = 0
FAIL = 0


def check(name: str, bed: bool) -> None:
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name)


def abbruch(grund: str) -> None:
    print("ABBRUCH: " + grund)
    sys.exit(2)


TMP = Path(tempfile.mkdtemp(prefix="waechter-bsi-tls-"))
CRT, KEY = TMP / "s.crt", TMP / "s.key"
r = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                    "-keyout", str(KEY), "-out", str(CRT), "-days", "1",
                    "-subj", "/CN=localhost"], capture_output=True, text=True)
if r.returncode != 0:
    abbruch("openssl req gescheitert: %s" % r.stderr[-300:])


async def _app(scope, receive, send):  # pragma: no cover – wird nie gerufen
    pass


def uvicorn_kontext(ciphers: str | None) -> ssl.SSLContext:
    """Serverkontext ueber uvicorns eigenen Weg (Config.load)."""
    kw = {"ssl_certfile": str(CRT), "ssl_keyfile": str(KEY)}
    if ciphers is not None:
        kw["ssl_ciphers"] = ciphers
    cfg = Config(_app, **kw)
    cfg.load()
    return cfg.ssl


def frei_kontext() -> ssl.SSLContext:
    """Freizuegiger Server fuer die Positivkontrolle alter Protokolle."""
    c = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    c.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
    c.set_ciphers("ALL:@SECLEVEL=0")
    c.load_cert_chain(str(CRT), str(KEY))
    return c


def handshake(server: ssl.SSLContext, *, cipher: str | None = None,
              version: ssl.TLSVersion | None = None):
    """Ein echter Handshake ueber localhost. Rueckgabe (version, cipher) oder None."""
    lsock = socket.socket()
    lsock.bind(("127.0.0.1", 0))
    lsock.listen(1)
    lsock.settimeout(3)  # kein Verbindungsversuch (Suite unbekannt) -> accept endet
    port = lsock.getsockname()[1]

    def bedienen():
        try:
            conn, _ = lsock.accept()
            conn.settimeout(5)
            try:
                s = server.wrap_socket(conn, server_side=True)
                s.close()
            except (ssl.SSLError, OSError):
                conn.close()
        except OSError:
            pass

    t = threading.Thread(target=bedienen, daemon=True)
    t.start()
    cli = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    cli.check_hostname = False
    cli.verify_mode = ssl.CERT_NONE
    if version is not None:
        cli.minimum_version = version
        cli.maximum_version = version
    try:
        # Kennt das lokale OpenSSL die Suite nicht, wirft das hier -> None; die
        # Aufrufer werten None nur nach einer gelungenen Positivkontrolle.
        if cipher is not None or (version is not None and version < ssl.TLSVersion.TLSv1_2):
            cli.set_ciphers((cipher or "ALL") + ":@SECLEVEL=0")
        with socket.create_connection(("127.0.0.1", port), timeout=5) as raw:
            with cli.wrap_socket(raw, server_hostname="localhost") as s:
                return s.version(), s.cipher()[0]
    except (ssl.SSLError, OSError):
        return None
    finally:
        t.join(5)
        lsock.close()


# TLS 1.0/1.1 sind in Python abgekuendigt – genau die messen wir aber.
warnings.filterwarnings("ignore", category=DeprecationWarning, message=".*TLSv1")
T12 = ssl.TLSVersion.TLSv1_2

# ── Positivkontrollen: die Messung kann Erfolg UND Misserfolg sehen ────────
ALT = uvicorn_kontext(None)   # uvicorns Vorgabe "TLSv1" = der Befund
NEU = uvicorn_kontext(TLS12_SUITES)
for c in ("ECDHE-RSA-AES128-SHA", "ECDHE-RSA-AES256-SHA"):
    if handshake(ALT, cipher=c, version=T12) is None:
        abbruch("Positivkontrolle: %s gegen uvicorn-Vorgabe kommt nicht durch – "
                "Messung blind" % c)
print("  (Positivkontrolle: Befund mit uvicorn-Vorgabe reproduziert)")

# ── 1. Wirkung am Serverkontext ────────────────────────────────────────────
print("\n[1] Handshakes gegen den Kontext mit TLS12_SUITES")
for c in ("ECDHE-RSA-AES128-SHA", "ECDHE-RSA-AES256-SHA"):
    check("TLS 1.2 %s (SHA-1-MAC) abgewiesen" % c,
          handshake(NEU, cipher=c, version=T12) is None)

# Statische RSA-Schluesseluebergabe (kein Forward Secrecy) und alte Verfahren:
# nur werten, wo die Positivkontrolle gegen den freizuegigen Server gelingt.
FREI = frei_kontext()
for c in ("AES256-GCM-SHA384", "AES128-SHA256", "AES128-SHA", "DES-CBC3-SHA",
          "ECDHE-RSA-CHACHA20-POLY1305"):
    if handshake(FREI, cipher=c, version=T12) is None:
        print("  --   %s: lokales OpenSSL kann sie nicht – nicht messbar" % c)
        continue
    check("TLS 1.2 %s abgewiesen" % c, handshake(NEU, cipher=c, version=T12) is None)

for c in ("ECDHE-RSA-AES256-GCM-SHA384", "ECDHE-RSA-AES128-GCM-SHA256",
          "ECDHE-RSA-AES256-SHA384", "ECDHE-RSA-AES128-SHA256"):
    erg = handshake(NEU, cipher=c, version=T12)
    check("TLS 1.2 %s angenommen" % c, erg == ("TLSv1.2", c))

erg = handshake(NEU, version=T12)
check("TLS 1.2 ohne Vorgabe des Clients: GCM-Suite gewaehlt (%s)" % (erg,),
      erg is not None and erg[1].startswith("ECDHE-") and "GCM" in erg[1])
erg = handshake(NEU, version=ssl.TLSVersion.TLSv1_3)
check("TLS 1.3 weiter moeglich (%s)" % (erg,), erg is not None and erg[0] == "TLSv1.3")

for v in (ssl.TLSVersion.TLSv1, ssl.TLSVersion.TLSv1_1):
    if handshake(FREI, version=v) is None:
        print("  --   %s: lokales OpenSSL spricht es nicht – nicht messbar" % v.name)
        continue
    check("%s abgewiesen" % v.name, handshake(NEU, version=v) is None)

# Das Angebot selbst: jede TLS-1.2-Suite ist ECDHE mit SHA-2 bzw. AEAD
t12 = [c for c in NEU.get_ciphers() if c.get("protocol") == "TLSv1.2"]
check("Kontext bietet TLS-1.2-Suites an (%d)" % len(t12), len(t12) > 0)
schlecht = [c["name"] for c in t12
            if not c["name"].startswith("ECDHE-")
            or not (c["name"].endswith("-SHA256") or c["name"].endswith("-SHA384"))]
check("…alle ECDHE mit SHA-256/384 (abweichend: %s)" % schlecht, not schlecht)

# ── 2. Jede Startstelle uebergibt GENAU diese Suites ───────────────────────
print("\n[2] Startstellen")
AUSGENOMMEN = {"node_modules", "venv", ".git", ".claude", "tests"}


def dateien(muster: str):
    for p in sorted(ROOT.rglob(muster)):
        if not AUSGENOMMEN.intersection(p.relative_to(ROOT).parts):
            yield p


def befehle(text: str):
    """Logische Zeilen (Fortsetzungen mit \\ zusammengezogen), Kommentare raus."""
    zeilen, akt = [], ""
    for z in text.splitlines():
        if not akt and z.lstrip().startswith("#"):
            continue
        if z.rstrip().endswith("\\"):
            akt += z.rstrip()[:-1] + " "
        else:
            zeilen.append(akt + z)
            akt = ""
    return zeilen


sh_stellen = 0
for p in dateien("*.sh"):
    rel = str(p.relative_to(ROOT))
    for cmd in befehle(p.read_text(encoding="utf-8", errors="replace")):
        if "uvicorn" not in cmd or "--ssl-certfile" not in cmd:
            continue
        sh_stellen += 1
        try:
            woerter = shlex.split(cmd)
        except ValueError as e:
            check("%s: Befehl zerlegbar (%s)" % (rel, e), False)
            continue
        idx = next((i for i, w in enumerate(woerter)
                    if w == "uvicorn" or w.endswith("/uvicorn")), None)
        if idx is None:
            check("%s: uvicorn-Aufruf gefunden" % rel, False)
            continue
        # Shell-Variablen durch einen gueltigen Platzhalter ersetzen, Rest unveraendert
        args = [re.sub(r"\$\{?\w+\}?", "1", w) for w in woerter[idx + 1:]]
        try:
            ctx = uvicorn_cli.make_context("uvicorn", args)
            gesetzt = ctx.params.get("ssl_ciphers")
        except Exception as e:  # noqa: BLE001
            check("%s: uvicorn versteht die Zeile (%s)" % (rel, e), False)
            continue
        check("%s: --ssl-ciphers == TLS12_SUITES" % rel, gesetzt == TLS12_SUITES)

py_stellen = 0
for p in dateien("*.py"):
    rel = str(p.relative_to(ROOT))
    try:
        baum = ast.parse(p.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        continue
    for k in ast.walk(baum):
        if not (isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute)
                and k.func.attr == "run" and isinstance(k.func.value, ast.Name)
                and k.func.value.id == "uvicorn"):
            continue
        kws = {kw.arg: kw.value for kw in k.keywords}
        if "ssl_certfile" not in kws:
            continue
        py_stellen += 1
        v = kws.get("ssl_ciphers")
        name_ok = isinstance(v, ast.Name) and v.id == "TLS12_SUITES"
        import_ok = any(isinstance(n, ast.ImportFrom) and n.module == "backend.tls_richtlinie"
                        and any(a.name == "TLS12_SUITES" and a.asname is None for a in n.names)
                        for n in ast.walk(baum))
        check("%s:%d uvicorn.run(ssl_ciphers=TLS12_SUITES) aus backend.tls_richtlinie"
              % (rel, k.lineno), name_ok and import_ok)

# Positivkontrolle der Suche: der Produktivweg (jarvis.service -> start_jarvis.sh)
# muss erfasst sein, sonst ist "alle Stellen richtig" trivial wahr.
check("Suche erfasst Shell-Startstellen (%d) und Python-Startstellen (%d)"
      % (sh_stellen, py_stellen), sh_stellen >= 1 and py_stellen >= 1)
start = (ROOT / "start_jarvis.sh").read_text(encoding="utf-8")
check("start_jarvis.sh (Produktivweg) ist darunter",
      any("uvicorn" in c and "--ssl-certfile" in c for c in befehle(start)))

# ── 3. TLS 1.3: nur Suiten aus TR-02102-2 (H6-Rest, 2026-10-13) ────────────
print("\n[3] TLS 1.3")
from backend import tls_richtlinie as TR  # noqa: E402

TR_TLS13 = {"TLS_AES_128_GCM_SHA256", "TLS_AES_256_GCM_SHA384", "TLS_AES_128_CCM_SHA256"}
soll = TR.TLS13_SUITES.split(":")
check("TLS13_SUITES nicht leer und alle aus TR-02102-2 (%s)" % soll,
      bool(soll) and set(soll) <= TR_TLS13)
cnf = TR.OPENSSL_KONFIG.read_text(encoding="utf-8") if TR.OPENSSL_KONFIG.is_file() else ""
m = re.search(r"^\s*Ciphersuites\s*=\s*(\S+)\s*$", cnf, re.M)
check("openssl_tls.cnf: Ciphersuites == TLS13_SUITES", bool(m) and m.group(1) == TR.TLS13_SUITES)
check("openssl_tls.cnf bindet die Systemkonfiguration ein",
      re.search(r"^\.include\s+/etc/ssl/openssl\.cnf\s*$", cnf, re.M) is not None)

# Wirkung: eigener Prozess (OpenSSL liest OPENSSL_CONF nur beim Start), der
# den Kontext ueber uvicorns Weg baut, konfig_uebernehmen ruft und dann
# echte Handshakes bedient. Gemessen wird mit `openssl s_client`, weil
# Pythons Client die TLS-1.3-Suite ebenfalls nicht waehlen kann.
KIND = r"""
import json, os, socket, subprocess, sys
sys.path.insert(0, sys.argv[1])
from uvicorn.config import Config
from backend import tls_richtlinie as TR
async def app(scope, receive, send): pass
cfg = Config(app, ssl_certfile=sys.argv[2], ssl_keyfile=sys.argv[3], ssl_ciphers=TR.TLS12_SUITES)
cfg.load()
beschraenkt = TR.konfig_uebernehmen()
kind = subprocess.run(["sh", "-c", "echo ${OPENSSL_CONF:-}"], capture_output=True, text=True).stdout.strip()
t13 = sorted(c["name"] for c in cfg.ssl.get_ciphers() if c.get("protocol") == "TLSv1.3")
l = socket.socket(); l.bind(("127.0.0.1", 0)); l.listen(4); l.settimeout(8)
print(json.dumps({"port": l.getsockname()[1], "beschraenkt": beschraenkt, "kind": kind, "t13": t13}), flush=True)
for _ in range(int(sys.argv[4])):
    try:
        c, _ = l.accept()
        try: cfg.ssl.wrap_socket(c, server_side=True).close()
        except Exception: c.close()
    except OSError: break
"""


def tls13_messen(mit_konfig: bool, suiten):
    env = dict(os.environ)
    env.pop("OPENSSL_CONF", None)
    if mit_konfig:
        TR.konfig_fuer_start(env)
    p = subprocess.Popen([sys.executable, "-c", KIND, str(ROOT), str(CRT), str(KEY), str(len(suiten))],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    try:
        kopf = json.loads(p.stdout.readline() or "{}")
        erg = {}
        for cs in suiten:
            r = subprocess.run(["openssl", "s_client", "-connect", "127.0.0.1:%s" % kopf.get("port"),
                                "-tls1_3", "-ciphersuites", cs], input="", capture_output=True,
                               text=True, timeout=10, env={k: v for k, v in os.environ.items()
                                                           if k != "OPENSSL_CONF"})
            t = re.search(r"Cipher is (\S+)", r.stdout)
            erg[cs] = t.group(1) if t else None
        return kopf, erg
    finally:
        p.wait(timeout=15)


import json  # noqa: E402

if not (TR.SYSTEM_KONFIG.is_file() and shutil_which("openssl")):
    abbruch("TLS 1.3: /etc/ssl/openssl.cnf oder openssl fehlt – nicht messbar")
CHACHA, GCM = "TLS_CHACHA20_POLY1305_SHA256", "TLS_AES_256_GCM_SHA384"
kopf0, erg0 = tls13_messen(False, [CHACHA])
if erg0.get(CHACHA) != CHACHA:
    abbruch("Positivkontrolle TLS 1.3: ohne Konfiguration kommt %s nicht durch (%s) – "
            "Messung blind" % (CHACHA, erg0))
print("  (Positivkontrolle: ohne Konfiguration wird %s angenommen)" % CHACHA)
check("ohne Konfiguration meldet konfig_uebernehmen 'nicht beschraenkt'",
      kopf0.get("beschraenkt") is False)
kopf1, erg1 = tls13_messen(True, [CHACHA, GCM])
check("mit Konfiguration: %s abgewiesen (%s)" % (CHACHA, erg1.get(CHACHA)),
      erg1.get(CHACHA) in (None, "(NONE)"))
check("mit Konfiguration: %s angenommen" % GCM, erg1.get(GCM) == GCM)
check("Angebot TLS 1.3 == TLS13_SUITES (%s)" % kopf1.get("t13"),
      set(kopf1.get("t13") or []) == set(soll))
check("konfig_uebernehmen meldet 'beschraenkt'", kopf1.get("beschraenkt") is True)
check("Kindprozess erbt OPENSSL_CONF nicht (%r)" % kopf1.get("kind"), kopf1.get("kind") == "")

# Startstellen: jede Shell-Startstelle exportiert OPENSSL_CONF VOR dem
# uvicorn-Aufruf; jede Python-Startstelle ruft konfig_fuer_start() vor
# uvicorn.run; backend.main ruft konfig_uebernehmen() auf Modulebene.
sh13 = 0
for p in dateien("*.sh"):
    rel = str(p.relative_to(ROOT))
    cmds = befehle(p.read_text(encoding="utf-8", errors="replace"))
    for i, cmd in enumerate(cmds):
        if "uvicorn" not in cmd or "--ssl-certfile" not in cmd:
            continue
        sh13 += 1
        davor = [c for c in cmds[:i] if re.search(r"\bexport\s+OPENSSL_CONF=\S*backend/openssl_tls\.cnf", c)]
        check("%s: export OPENSSL_CONF=…backend/openssl_tls.cnf vor uvicorn" % rel, bool(davor))
py13 = 0
for p in dateien("*.py"):
    rel = str(p.relative_to(ROOT))
    try:
        baum = ast.parse(p.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        continue
    for k in ast.walk(baum):
        if not (isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute)
                and k.func.attr == "run" and isinstance(k.func.value, ast.Name)
                and k.func.value.id == "uvicorn"
                and any(kw.arg == "ssl_certfile" for kw in k.keywords)):
            continue
        py13 += 1
        vorher = [c for c in ast.walk(baum)
                  if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)
                  and c.func.id == "konfig_fuer_start" and c.lineno < k.lineno]
        check("%s:%d konfig_fuer_start() vor uvicorn.run" % (rel, k.lineno), bool(vorher))
check("TLS-1.3-Suche erfasst dieselben Startstellen (%d Shell, %d Python)" % (sh13, py13),
      sh13 == sh_stellen and py13 == py_stellen and sh13 >= 1 and py13 >= 1)
mb = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
modul = [c for n in mb.body for c in ast.walk(n)
         if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
         and isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
         and c.func.attr == "konfig_uebernehmen"]
check("backend.main ruft konfig_uebernehmen() auf Modulebene", bool(modul))

print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
