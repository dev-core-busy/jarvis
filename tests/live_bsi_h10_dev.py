#!/usr/bin/env python3
"""LIVE auf DEV: BSI H10 ueber den ECHTEN Broker-Weg (Op sandbox_lauf).

Laeuft als Dienstbenutzer auf DEV (venv), wie live_lauf_rechte_dev.py:

    sudo -u jarvis /opt/jarvis/venv/bin/python tests/live_bsi_h10_dev.py

Gemessen wird am ECHTEN Lauf, nicht am Aufruf:
A. Domain-Benutzer: Identitaet, eigener Scope, die cgroup-Werte (memory.max,
   pids.max, cpu.max) entsprechen den angeforderten Grenzen, ein Speicherfresser
   wird beendet (Positivkontrolle: kleiner Bedarf laeuft), Loopback und eigene
   Adresse zu, Internet offen (Positivkontrolle: Netz gibt es grundsaetzlich).
B. Ohne Internet: eigener Netz-Namespace (nur lo), nichts erreichbar.
C. Administrator-Modus (ohne privates /tmp): echtes /tmp sichtbar, die
   privaten Bereiche der Domain-Benutzer NICHT.
D. Alte Op sandbox_exec -> "unbekannte Op" (ein alter Aufrufer fuehrt nichts aus).
E. Status mit Live-Test: Loopback zu, Grenzen anwendbar, Sperre aktiv.
F. Streaming und Timeout (ganze Gruppe weg, keine Waise).

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import asyncio
import os
import re
import socket
import subprocess
import sys
import time
import uuid

sys.path.insert(0, "/opt/jarvis")
try:
    from backend import lauf_tmp as lt                      # noqa: E402
    from backend import broker_client                        # noqa: E402
    from backend.tools.shell import ShellTool                # noqa: E402
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: Backend nicht ladbar: {e}")
    sys.exit(2)

BEN = "livetest.h10"
SBX = "jarvis_sandbox"
NOINET = "jarvis_sandbox_noinet"
GRENZEN = {"speicher_mb": 256, "prozesse": 64, "cpu_prozent": 100}
ok = fail = 0


def check(bez, bed, detail=""):
    global ok, fail
    if bed:
        ok += 1
        print(f"OK   {bez}")
    else:
        fail += 1
        print(f"FAIL {bez}" + (f" – {detail}" if detail else ""))


ZEILEN = []


async def _cb(z):
    ZEILEN.append(z)


def sh(cmd, user=SBX, timeout=60, **kw):
    return asyncio.run(ShellTool().execute(
        command=cmd, timeout=timeout, _sandbox_user=user, _grenzen=GRENZEN,
        _broker_user=BEN, _broker_context="[live] BSI H10", **kw))


VERBINDE = ("python3 - <<'P'\nimport socket,sys\nfor h,p in %r:\n"
            "    s=socket.socket(); s.settimeout(4)\n"
            "    try: s.connect((h,p)); print('ZIEL',h,p,'OFFEN')\n"
            "    except Exception as e: print('ZIEL',h,p,'ZU',type(e).__name__)\n"
            "try: socket.getaddrinfo('deb.debian.org',443); print('DNS OK')\n"
            "except Exception as e: print('DNS ZU',type(e).__name__)\nP")


def ziele(aus):
    return {(m.group(1), int(m.group(2))): m.group(3)
            for m in re.finditer(r"ZIEL (\S+) (\d+) (OFFEN|ZU)", aus)}


if os.geteuid() == 0:
    print("ABBRUCH: als Dienstbenutzer starten, nicht als root (sonst Alt-Betrieb)")
    sys.exit(2)
eigene_ip = ""
try:
    eigene_ip = subprocess.run(["hostname", "-I"], capture_output=True, text=True).stdout.split()[0]
except Exception:  # noqa: BLE001
    pass
if not eigene_ip:
    print("ABBRUCH: eigene Adresse nicht ermittelbar")
    sys.exit(2)
try:
    extern = socket.gethostbyname("deb.debian.org")
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH: DNS vom Dienst aus nicht moeglich ({e}) – Positivkontrolle Internet unmoeglich")
    sys.exit(2)

kennung = ""
with lt.lauf_scope(BEN, privilegiert=False) as lauf:
    if lauf is None:
        print("ABBRUCH: lauf_scope oeffnet keinen Lauf (bwrap?)")
        sys.exit(2)
    kennung = lauf.kennung
    print(f"Arbeitsverzeichnis: {lauf.verzeichnis}")

    print("\n── A. Domain-Benutzer")
    aus = sh("id -un; cat /proc/self/cgroup; d=/sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup); "
             "echo MEM=$(cat $d/memory.max) PIDS=$(cat $d/pids.max) CPU=$(cat $d/cpu.max) "
             "SWAP=$(cat $d/memory.swap.max)")
    check("laeuft als jarvis_sandbox", "\njarvis_sandbox\n" in "\n" + aus.replace("STDOUT:\n", "") + "\n", aus[:200])
    check("eigener Scope (jarvis-sandbox-*.scope)", "jarvis-sandbox-" in aus and ".scope" in aus, aus[:300])
    m = re.search(r"MEM=(\S+) PIDS=(\S+) CPU=(\S+ \S+) SWAP=(\S+)", aus)
    check("cgroup-Werte lesbar (Positivkontrolle)", bool(m), aus[-200:])
    if m:
        check(f"memory.max = 256 MB ({m.group(1)})", m.group(1) == str(256 * 1024 * 1024))
        check(f"pids.max = 64 ({m.group(2)})", m.group(2) == "64")
        check(f"cpu.max = 100 % ({m.group(3)})", m.group(3) == "100000 100000")
        check(f"memory.swap.max = 0 ({m.group(4)})", m.group(4) == "0")
    aus = sh("python3 -c \"b=bytearray(64*1024*1024); print('KLEIN-OK')\"")
    check("Positivkontrolle: 64 MB laufen", "KLEIN-OK" in aus, aus[-200:])
    t0 = time.monotonic()
    aus = sh("python3 -c \"b=bytearray(1024*1024*1024); print('NICHT BEGRENZT')\"")
    check("1 GB bei 256 MB Grenze wird beendet", "NICHT BEGRENZT" not in aus, aus[-200:])
    check("Benutzer/Modell bekommt den Grenz-Hinweis", "HINWEIS: Der Befehl wurde von der Sandbox" in aus, aus[-300:])
    aus = sh(VERBINDE % ([("127.0.0.1", 443), (eigene_ip, 443), ("127.0.0.1", 631), (extern, 443)],))
    z = ziele(aus)
    check("Positivkontrolle: Internet aus der Sandbox erreichbar (Netz gibt es)",
          z.get((extern, 443)) == "OFFEN", str(z))
    check("Loopback: 127.0.0.1:443 (Jarvis) ZU", z.get(("127.0.0.1", 443)) == "ZU", str(z))
    check("Loopback: 127.0.0.1:631 (cups) ZU", z.get(("127.0.0.1", 631)) == "ZU", str(z))
    check(f"eigene Adresse {eigene_ip}:443 ZU", z.get((eigene_ip, 443)) == "ZU", str(z))
    check("DNS geht (lokale Ausnahme bricht nichts)", "DNS OK" in aus, aus[-200:])

    print("\n── B. ohne Internet")
    aus = sh(VERBINDE % ([("127.0.0.1", 443), (eigene_ip, 443), (extern, 443)],),
             user=NOINET, _ohne_netz=True)
    z = ziele(aus)
    check("alle Ziele ZU (Loopback, eigene Adresse, Internet)",
          len(z) == 3 and all(v == "ZU" for v in z.values()), str(z))
    check("DNS ZU", "DNS ZU" in aus, aus[-200:])
    # Getrennter Aufruf: hinter dem Heredoc-Ende angehaengt liefe es als Python.
    netdev = sh("cat /proc/net/dev", user=NOINET, _ohne_netz=True)
    ifs = re.findall(r"^\s*([A-Za-z0-9_.-]+):\s+\d", netdev, re.M)
    check(f"nur ein Netzgeraet: lo ({ifs})", ifs == ["lo"])

    print("\n── F. Streaming und Timeout")
    ZEILEN.clear()
    aus = sh("for i in 1 2 3; do echo zeile$i; sleep 1; done", _status_callback=_cb)
    check("Zeilen kommen live an", sum("zeile" in z for z in ZEILEN) == 3, str(ZEILEN))
    t0 = time.monotonic()
    aus = sh("sleep 300", timeout=3)
    dauer = time.monotonic() - t0
    check(f"Timeout greift ({dauer:.1f} s)", dauer < 30 and "Timeout" in aus, aus[-120:])
    time.sleep(2)
    r = subprocess.run(["pgrep", "-u", SBX, "-x", "sleep"], capture_output=True, text=True)
    check("keine Waise des Sandbox-Benutzers", r.returncode != 0, r.stdout.strip())

print("\n── C. Administrator-Modus (echtes /tmp)")
marke = f"/tmp/h10_sichtbar_{uuid.uuid4().hex[:8]}"
with open(marke, "w") as f:
    f.write("SICHTBAR")
os.chmod(marke, 0o644)
try:
    host_n = len(os.listdir(lt.ARBEIT_ROOT)) if lt.ARBEIT_ROOT.is_dir() else 0
    aus = sh(f"cat {marke}; echo; echo ANZ=$(ls -A {lt.ARBEIT_ROOT} | wc -l) "
             f"ANH=$(ls -A {lt.ANH_ROOT} 2>/dev/null | wc -l)", _ohne_lauf=True)
    check("Positivkontrolle: auf dem Host gibt es private Bereiche", host_n > 0, str(host_n))
    check("echtes /tmp ist sichtbar", "SICHTBAR" in aus, aus[-200:])
    check("private Bereiche der Domain-Benutzer NICHT VORHANDEN", "ANZ=0" in aus and "ANH=0" in aus, aus[-200:])
finally:
    os.unlink(marke)

print("\n── D. alte Op")
r = broker_client.call_sync("sandbox_exec", {"user": SBX, "command": "id"}, user=BEN, timeout=20) \
    if hasattr(broker_client, "call_sync") else asyncio.run(
        broker_client.call("sandbox_exec", {"user": SBX, "command": "id"}, user=BEN, timeout=20))
check("sandbox_exec -> unbekannte Op, nichts ausgefuehrt",
      r.get("decision") == "unknown-op" and "rc" not in r, str(r)[:160])

print("\n── E. Status mit Live-Test")
r = asyncio.run(broker_client.call("sandbox_status", {"live": True}, user=BEN, timeout=90))
st = r.get("result") or {}
iso = st.get("isolation") or {}
h = st.get("h10") or {}
check("Status lesbar (Positivkontrolle)", bool(st), str(r)[:160])
check("Live: Jarvis aus der Sandbox nicht erreichbar", iso.get("loopback_offen") is False, str(iso))
check("Live: Grenzen anwendbar", iso.get("grenzen_anwendbar") is True, str(iso))
check("Loopback-Sperre aktiv", h.get("lo_sperre") is True, str(h))
check("Gesamtstatus ok", st.get("ok") is True, str({k: st.get(k) for k in ("ok", "active", "secrets_locked")}))

# Aufraeumen: das Arbeitsverzeichnis dieses Testbenutzers (nur root kann es)
if kennung:
    asyncio.run(broker_client.call("lauf_aufraeumen", {"arbeit": kennung}, user=BEN, timeout=30))

print(f"\nErgebnis: {ok} OK, {fail} FAIL")
sys.exit(0 if fail == 0 and ok > 0 else 1)
