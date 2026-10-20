"""Root-Broker-Daemon: Unix-Socket-Server fuer privilegierte Operationen.

Laeuft als root (jarvis-broker.service). Das unprivilegierte Backend verbindet
sich ueber /run/jarvis-broker.sock (root:<gruppe> 0660) und sendet EINE
JSON-Zeile pro Verbindung:

    {"op": "...", "args": {...}, "user": "...", "timeout": 120}

Antwort als NDJSON: beliebig viele {"type":"stream","line": "..."}-Zeilen
(Live-Ausgabe fuer shell-artige Ops), abgeschlossen mit
{"type":"result", "ok": ..., "decision": ..., ...}.

Meta-Operationen (Admin-UI), Regeln in backend/broker/meta.py:
- broker.ping           – Erreichbarkeits-/Versionscheck (+ Herkunft des Codes)
- broker.policy_list    – alle Policy-Eintraege
- broker.policy_decide  – {key, decision, by[, nachweis]}; 'allow' nur mit Freigabe-Code
- broker.policy_remove  – {key, nachweis} loeschen
- broker.audit_tail     – {n} letzte Audit-Eintraege
- broker.totp_pruefen   – {code, konto}; 2FA-Code der ANMELDUNG gegen denselben
                          Schluessel wie die Freigaben (ein App-Eintrag, meta.py)
- broker.ssh_status     – Fernzugang (SSH): Zustand, Konten, laufende Tests
- broker.ssh_haertung   – {aktion, root_modus, nachweis}; Regeln in fernzugang.py
- broker.ssh_netze      – {aktion, netze, nachweis}

Start (seit 2026-09-29, Befund K1): aus der root-eigenen Kopie mit dem
System-Python – /usr/local/lib/jarvis-broker/start_jarvis_root.sh. Nie mehr
aus /opt/jarvis und nie mit dessen venv: beides gehoert dem Dienstbenutzer.
"""

import asyncio
import concurrent.futures
import functools
import grp
import json
import os
import pwd
import signal
import socket
import struct
import sys

# Projekt-Root in sys.path (Start via `python -m backend.broker.daemon` aus
# dem Projektverzeichnis funktioniert auch ohne diesen Eintrag; absolute
# Aufrufe aus systemd nicht unbedingt).
_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.broker import SOCKET_PATH, meta, ops, policy  # noqa: E402

SOCKET_GROUP = os.environ.get("JARVIS_BROKER_GROUP", "jarvis")
# Wer ueberhaupt verbinden darf: root und der Dienstbenutzer. Die Socket-Rechte
# (0660, Gruppe jarvis) sagen dasselbe – hier steht es ein zweites Mal, weil
# ein weiteres Mitglied der Gruppe sonst stillschweigend mitreden duerfte.
SERVICE_USER = os.environ.get("JARVIS_BROKER_SERVICE_USER", SOCKET_GROUP)
MAX_REQUEST_BYTES = 512 * 1024
DEFAULT_TIMEOUT = 120
MAX_TIMEOUT = 900

# Eigene Threadpools (Code-Review 2026-10-18): bis dahin liefen Meta-Ops UND
# jede Op ueber asyncio.to_thread, also den Standard-Executor
# (min(32, CPU+4) Threads). Lange Shell-Befehle der Domain-Benutzer
# (sandbox_lauf, bis zu Stunden) belegten ihn – auf einer 4-Kern-VM reichten
# 8 davon, und Ping, Freigaben und systemctl hingen. Jetzt:
#   _KURZ: Meta-Ops und kurze Ops – bleibt bedienbar, auch unter Last
#   _LANG: Ops, die Minuten bis Stunden laufen koennen, gedeckelt; ist er
#          voll, wird abgewiesen statt endlos eingereiht.
LANGE_OPS = frozenset({"sandbox_lauf", "shell_root", "certbot_obtain", "tika_setup",
                       "apt_upgrades_setup", "mount_share", "mount_diagnose",
                       "egress_setup", "sandbox_setup"})
LANG_MAX = int(os.environ.get("JARVIS_BROKER_LANG_MAX", "24"))
_KURZ = concurrent.futures.ThreadPoolExecutor(max_workers=8, thread_name_prefix="broker-kurz")
_LANG = concurrent.futures.ThreadPoolExecutor(max_workers=LANG_MAX, thread_name_prefix="broker-lang")
_lang_aktiv = 0


def _zahl(wert, vorgabe: int) -> int:
    try:
        return int(wert if wert not in (None, "") else vorgabe)
    except (TypeError, ValueError):
        return vorgabe


def _peer(writer) -> tuple[int | None, str]:
    """(uid, Beschreibung) des Aufrufers laut KERNEL (SO_PEERCRED).

    Der Aufrufer schreibt ``user`` und ``by`` selbst in die Anfrage – das ist
    eine Angabe, kein Nachweis. SO_PEERCRED stammt vom Kernel.
    """
    try:
        sock = writer.get_extra_info("socket")
        roh = sock.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
        pid, uid, gid = struct.unpack("3i", roh)
        try:
            name = pwd.getpwuid(uid).pw_name
        except KeyError:
            name = str(uid)
        return uid, f"uid={uid}({name}) pid={pid}"
    except Exception:  # noqa: BLE001
        return None, "unbekannt"


def _zugelassen(uid: int | None) -> bool:
    """Fail-closed: unbekannter Aufrufer ist nicht zugelassen."""
    if uid is None:
        return False
    if uid == 0:
        return True
    try:
        return uid == pwd.getpwnam(SERVICE_USER).pw_uid
    except KeyError:
        return False


async def _handle(reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
    loop = asyncio.get_running_loop()

    async def send(obj: dict):
        writer.write((json.dumps(obj, ensure_ascii=False) + "\n").encode())
        await writer.drain()

    peer_uid, peer = _peer(writer)
    try:
        if not _zugelassen(peer_uid):
            print(f"[Broker] Verbindung abgewiesen: {peer}", flush=True)
            policy.audit("", "broker.verbindung", "", "abgewiesen", peer=peer)
            await send({"type": "result", "ok": False,
                        "error": "Aufrufer nicht zugelassen"})
            return
        try:
            raw = await asyncio.wait_for(reader.readline(), timeout=30)
        except (asyncio.LimitOverrunError, ValueError):
            # readline() wirft ueber dem Puffer (limit beim Serverstart) –
            # vorher war das ein "Separator is not found…" ohne Hinweis.
            await send({"type": "result", "ok": False,
                        "error": f"Anfrage zu gross (hoechstens {MAX_REQUEST_BYTES // 1024} KiB)"})
            return
        if not raw or len(raw) > MAX_REQUEST_BYTES:
            await send({"type": "result", "ok": False, "error": "Leere/zu grosse Anfrage"})
            return
        try:
            req = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            await send({"type": "result", "ok": False, "error": "Ungueltiges JSON"})
            return

        op = str(req.get("op", ""))
        args = req.get("args") or {}
        user = str(req.get("user", ""))
        if not isinstance(args, dict):
            await send({"type": "result", "ok": False, "error": "args muss ein Objekt sein"})
            return
        timeout = max(1, min(_zahl(req.get("timeout"), DEFAULT_TIMEOUT), MAX_TIMEOUT))
        # Wartezeit auf das Ergebnis: mindestens so lang wie das Op-Argument
        # (gleich geklemmt wie in der Op selbst), sonst meldete der Daemon
        # "Timeout", waehrend die Op weiterlief.
        warte = max(timeout, ops.timeout_arg(args, timeout)) if op in LANGE_OPS else timeout

        # Meta-Operationen direkt beantworten – im Thread des KURZ-Pools: die
        # SSH-/Firewall-Ops (fernzugang.py) laufen Sekunden und haetten sonst
        # jede andere Verbindung des Brokers so lange angehalten
        antwort = await loop.run_in_executor(_KURZ, functools.partial(meta.behandeln, op, args, peer=peer))
        if antwort is not None:
            await send({"type": "result", **antwort})
            return

        # Streaming-Callback: aus dem Worker-Thread thread-sicher in den Loop
        def stream_cb(line: str):
            asyncio.run_coroutine_threadsafe(
                send({"type": "stream", "line": str(line)[:4000]}), loop)

        print(f"[Broker] op={op} user={user} {peer} args={ops.redact_args(op, args)}", flush=True)
        global _lang_aktiv
        lang = op in LANGE_OPS
        if lang and _lang_aktiv >= LANG_MAX:
            await send({"type": "result", "ok": False,
                        "error": f"Broker ausgelastet: {LANG_MAX} lange Befehle laufen bereits – "
                                 f"bitte gleich erneut versuchen."})
            return
        if lang:
            _lang_aktiv += 1
        try:
            # ⚠ wait_for bricht den Thread NICHT ab (Register) – die Op selbst
            # beendet ihren Prozessbaum ueber ihren eigenen Wachhund.
            result = await asyncio.wait_for(
                loop.run_in_executor(_LANG if lang else _KURZ,
                                     ops.dispatch, op, args, user, stream_cb, peer),
                timeout=warte + 30,   # Puffer: Op-interne Timeouts greifen zuerst
            )
        except asyncio.TimeoutError:
            result = {"ok": False, "error": f"Broker-Timeout nach {warte}s"}
        finally:
            if lang:
                _lang_aktiv -= 1
        await send({"type": "result", **result})

    except (asyncio.TimeoutError, ConnectionResetError, BrokenPipeError):
        pass
    except Exception as e:  # noqa: BLE001
        try:
            await send({"type": "result", "ok": False, "error": f"Broker-Fehler: {e}"})
        except Exception:  # noqa: BLE001
            pass
    finally:
        try:
            writer.close()
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass


def _sock_kennung():
    """(st_dev, st_ino) des Socket-Pfads oder None."""
    try:
        st = os.stat(SOCKET_PATH)
        return (st.st_dev, st.st_ino)
    except OSError:
        return None


async def main():
    if os.geteuid() != 0:
        print("[Broker] WARNUNG: laeuft nicht als root – Root-Ops werden scheitern.", flush=True)

    # Ops, die ihre Automatik verloren haben: bestehende auto-Eintraege
    # zuruecksetzen, sonst bliebe die Registry-Aenderung wirkungslos.
    for key in policy.herabstufen(ops.OHNE_AUTOMATIK):
        print(f"[Broker] Freigabe zurueckgesetzt (braucht jetzt Admin-Freigabe): {key}", flush=True)
    from backend.broker import CODE_ROOT, PROJECT_ROOT
    print(f"[Broker] Code aus {CODE_ROOT}, Daten in {PROJECT_ROOT}", flush=True)

    # Alten Socket entfernen (Neustart)
    try:
        os.unlink(SOCKET_PATH)
    except FileNotFoundError:
        pass

    # limit: Puffer fuer readline() – Standard waeren 64 KiB, MAX_REQUEST_BYTES
    # war damit toter Code und jede groessere Anfrage scheiterte unverstaendlich.
    server = await asyncio.start_unix_server(_handle, path=SOCKET_PATH,
                                             limit=MAX_REQUEST_BYTES + 1)

    # Socket: root:<gruppe> 0660 – nur der Dienst-Benutzer darf verbinden
    try:
        gid = grp.getgrnam(SOCKET_GROUP).gr_gid
        os.chown(SOCKET_PATH, 0, gid)
    except KeyError:
        print(f"[Broker] WARNUNG: Gruppe '{SOCKET_GROUP}' fehlt – Socket bleibt root-only.", flush=True)
    os.chmod(SOCKET_PATH, 0o660)
    # Eigene Kennung des Sockets merken – beim Beenden wird nur DIESER entfernt.
    eigener = _sock_kennung()

    print(f"[Broker] Bereit auf {SOCKET_PATH} (Gruppe: {SOCKET_GROUP})", flush=True)

    stop = asyncio.Event()
    for sig in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(sig, stop.set)
    async with server:
        await stop.wait()
    # Gesammelte Nutzungszaehler nicht verlieren (policy.ZAEHLER_FLUSH_S)
    try:
        policy.flush()
    except Exception as e:  # noqa: BLE001
        print(f"[Broker] Zaehler nicht geschrieben: {e}", flush=True)
    # Nur den EIGENEN Socket entfernen. Bis 2026-09-30 blind: ein verwaister
    # Alt-Broker (DEV, seit 11.08., sein Socket laengst durch den des Dienstes
    # ersetzt) loeschte beim Beenden den Pfad des LAUFENDEN Brokers – das
    # Backend erreichte ihn danach nicht mehr, bis der Dienst neu startete.
    # Ab Python 3.13 raeumt asyncio beim Schliessen den eigenen Socket bereits
    # selbst weg (``cleanup_socket``, nur wenn er nicht ersetzt wurde) – "Pfad
    # fehlt" ist dann der NORMALFALL. Die erste Fassung (2026-09-30) meldete
    # genau das als "gehoert einem anderen Broker", bei jedem Neustart.
    jetzt = _sock_kennung()
    if jetzt is None:
        pass
    elif jetzt == eigener:
        try:
            os.unlink(SOCKET_PATH)
        except FileNotFoundError:
            pass
    else:
        print("[Broker] Socket-Pfad gehoert inzwischen einem anderen Broker – bleibt stehen.",
              flush=True)
    print("[Broker] Beendet.", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
