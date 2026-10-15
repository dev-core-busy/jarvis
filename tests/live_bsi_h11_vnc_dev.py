#!/usr/bin/env python3
"""Live auf DEV: BSI H11-Rest – x11vnc laeuft nicht als root.

  A. Genau ein x11vnc, Eigentuemer jarvis-vnc; kein x11vnc als root.
     /proc: NoNewPrivs 1, keine wirksamen/vererbbaren/Bounding-Faehigkeiten,
     keine Zusatzgruppen.
  B. Cookie-Kopie 0600 jarvis-vnc in einem 0700-Verzeichnis; der Dienstbenutzer
     kann sie NICHT lesen.
  C. Der Dienstbenutzer (Backend-Proxy /ws/vnc) bekommt Handshake UND Bild
     (Positivkontrolle); ein fremder Benutzer (nobody) wird abgewiesen.
  D. Neustart ueber die Broker-Op vnc_restart (als Dienstbenutzer ausgeloest,
     der echte Weg): neue PID, wieder jarvis-vnc, keine root-Segmente dazu.
  E. Eine fremde Unit x11vnc.service laeuft nicht mehr.

Aufruf AUF DEV als root (liest /proc fremder Prozesse, wechselt Benutzer):
  python3 /opt/jarvis/tests/live_bsi_h11_vnc_dev.py
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time

VNC_BENUTZER = "jarvis-vnc"
DIENST = "jarvis"
JARVIS = "/opt/jarvis"
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s%s" % (label, (" – %s" % str(detail)[:300]) if detail else ""))


def rfb_probe():
    """Als Client: Handshake, None-Auth, ein Bild anfordern. Ausgabe 'bytes=<n>' oder 'fehler=<…>'."""
    try:
        s = socket.create_connection(("127.0.0.1", 5900), 5)
        v = s.recv(12)
        if not v.startswith(b"RFB "):
            print("fehler=kein RFB: %r" % v)
            return
        s.send(v)
        n = s.recv(1)[0]
        typen = s.recv(n)
        if 1 not in typen:
            print("fehler=None-Auth fehlt %r" % typen)
            return
        s.send(b"\x01")
        if s.recv(4) != b"\x00\x00\x00\x00":
            print("fehler=Auth abgelehnt")
            return
        s.send(b"\x01")
        kopf = s.recv(24)
        w, h = struct.unpack(">HH", kopf[:4])
        s.recv(struct.unpack(">I", kopf[20:24])[0])
        s.send(struct.pack(">BBHHHH", 3, 0, 0, 0, w, h))
        s.settimeout(2)
        summe, ende = 0, time.time() + 6
        while time.time() < ende:
            try:
                d = s.recv(65536)
            except socket.timeout:
                break
            if not d:
                break
            summe += len(d)
        print("bytes=%d" % summe)
    except Exception as e:  # noqa: BLE001
        print("fehler=%s" % e)


if len(sys.argv) > 1 and sys.argv[1] == "--rfb":
    rfb_probe()
    sys.exit(0)

if os.geteuid() != 0:
    print("NICHT PRUEFBAR: als root auf DEV aufrufen")
    sys.exit(2)


def x11vnc_prozesse():
    r = subprocess.run(["ps", "-eo", "pid=,user:32=,comm="], capture_output=True, text=True)
    return [(int(t[0]), t[1]) for t in (z.split() for z in r.stdout.splitlines())
            if len(t) == 3 and t[2] == "x11vnc"]


def proc_status(pid):
    werte = {}
    with open("/proc/%d/status" % pid) as f:
        for z in f:
            k, _, v = z.partition(":")
            werte[k] = v.strip()
    return werte


def segmente(eigner):
    r = subprocess.run(["ipcs", "-m"], capture_output=True, text=True, env={"LC_ALL": "C", "PATH": os.environ["PATH"]})
    return sum(1 for z in r.stdout.splitlines() if len(z.split()) >= 6 and z.split()[2] == eigner)


def als(user, *cmd, timeout=30):
    return subprocess.run(["runuser", "-u", user, "--", *cmd], capture_output=True, text=True, timeout=timeout)


# ── A ──
print("[A] Prozess")
pz = x11vnc_prozesse()
if not pz:
    print("NICHT PRUEFBAR: kein x11vnc laeuft")
    sys.exit(2)
check(len(pz) == 1, "genau ein x11vnc", pz)
check(all(u == VNC_BENUTZER for _, u in pz), "x11vnc gehoert %s" % VNC_BENUTZER, pz)
check(not any(u == "root" for _, u in pz), "kein x11vnc als root", pz)
pid = pz[0][0]
st = proc_status(pid)
check(st.get("NoNewPrivs") == "1", "NoNewPrivs = 1", st.get("NoNewPrivs"))
for feld in ("CapEff", "CapPrm", "CapInh", "CapBnd", "CapAmb"):
    check(int(st.get(feld, "1"), 16) == 0, "%s leer" % feld, st.get(feld))
check(st.get("Groups", "x") == "", "keine Zusatzgruppen", st.get("Groups"))

# ── B ──
print("\n[B] Cookie")
with open("/proc/%d/cmdline" % pid, "rb") as f:
    argv = f.read().split(b"\0")
auth = argv[argv.index(b"-auth") + 1].decode() if b"-auth" in argv else None
check(auth is not None and auth.startswith("/run/jarvis-vnc/"), "-auth zeigt auf die Kopie", auth)
check(b"guess" not in argv, "kein -auth guess")
if auth and os.path.exists(auth):
    s = os.stat(auth)
    import pwd
    vnc_uid = pwd.getpwnam(VNC_BENUTZER).pw_uid
    check(s.st_uid == vnc_uid and (s.st_mode & 0o777) == 0o600, "Kopie 0600 %s" % VNC_BENUTZER, oct(s.st_mode))
    d = os.stat(os.path.dirname(auth))
    check(d.st_uid == vnc_uid and (d.st_mode & 0o777) == 0o700, "Verzeichnis 0700 %s" % VNC_BENUTZER, oct(d.st_mode))
    r = als(DIENST, "cat", auth)
    check(r.returncode != 0, "Dienstbenutzer kann das Cookie nicht lesen", r.returncode)
else:
    check(False, "Cookie-Kopie existiert", auth)

# ── C ──
print("\n[C] Verbindung")
tmpd = tempfile.mkdtemp(prefix="h11live_")
os.chmod(tmpd, 0o755)
kopie = os.path.join(tmpd, "probe.py")
shutil.copy(os.path.abspath(__file__), kopie)
os.chmod(kopie, 0o644)
try:
    r = als(DIENST, sys.executable, "-I", kopie, "--rfb")
    erg = r.stdout.strip()
    n = int(erg.split("=", 1)[1]) if erg.startswith("bytes=") else 0
    if n <= 0:
        print("ABBRUCH Positivkontrolle: Dienstbenutzer bekommt kein Bild (%s %s)" % (erg, r.stderr[-200:]))
        sys.exit(2)
    check(n > 100000, "Dienstbenutzer: Handshake und Bild (%d Bytes)" % n)
    r = als("nobody", sys.executable, "-I", kopie, "--rfb")
    check(r.stdout.strip().startswith("fehler="), "fremder Benutzer abgewiesen", r.stdout.strip())

    # ── D ──
    print("\n[D] Neustart ueber die Broker-Op vnc_restart")
    root_vorher = segmente("root")
    code = ("import sys; sys.path.insert(0, %r); from backend import broker_client as b; "
            "r = b.call_sync('vnc_restart', {}, user='live_h11'); print('ok' if r.get('ok') else r)" % JARVIS)
    r = als(DIENST, JARVIS + "/venv/bin/python", "-c", code, timeout=90)
    check(r.stdout.strip().endswith("ok"), "Broker-Op vnc_restart ok", (r.stdout + r.stderr)[-300:])
    time.sleep(3)
    pz2 = x11vnc_prozesse()
    check(len(pz2) == 1 and pz2[0][0] != pid, "neuer x11vnc-Prozess", pz2)
    check(all(u == VNC_BENUTZER for _, u in pz2), "nach dem Neustart wieder %s" % VNC_BENUTZER, pz2)
    check(segmente("root") <= root_vorher, "keine neuen root-Segmente", (root_vorher, segmente("root")))
    r = als(DIENST, sys.executable, "-I", kopie, "--rfb")
    check(r.stdout.strip().startswith("bytes=") and int(r.stdout.strip()[6:] or 0) > 100000,
          "nach dem Neustart wieder Bild", r.stdout.strip())
finally:
    shutil.rmtree(tmpd, ignore_errors=True)

# ── E ──
print("\n[E] fremde Unit")
a = subprocess.run(["systemctl", "is-active", "x11vnc.service"], capture_output=True, text=True).stdout.strip()
check(a != "active", "x11vnc.service laeuft nicht", a)

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(0 if _fail == 0 else 1)
