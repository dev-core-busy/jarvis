"""BSI H10 – die harten Grenzen JEDES Sandbox-Laufs, an einer Stelle.

BEFUND H10 (BSI-Abgleich 2026-09-29, ECHT): "Shell-Sandbox ist optional,
Blocklisten-basiert, ohne Netz-Namespace und ohne Ressourcenlimits;
privilegierte Shell laeuft gar nicht isoliert." Massnahme: Sandbox fuer alle,
Abbruch statt Weiterlaufen ohne Isolation, Ressourcenlimits, Loopback fuer
Sandbox-UIDs sperren.

Was dieses Modul dazu beitraegt (die Kennung/der Namespace selbst bleibt in
``lauf_tmp.sandbox_befehl``):

1. **PFLICHT STATT OPTION.** Der Sandbox-Benutzer kommt nicht mehr nur aus der
   Einstellung ``sandbox_shell_user``: ist sie leer, gilt ``jarvis_sandbox``,
   sobald es den OS-Benutzer gibt. Eine leere Einstellung schaltet die Sandbox
   also NICHT mehr ab – genau das war der Befund (auf DEV am 2026-10-05
   gemessen: Einstellung leer, Domain-Shell lief als Dienstbenutzer).
2. **FAIL-CLOSED** (Betreiberentscheid 2026-10-05, ersetzt die fail-open-
   Festlegung vom 2026-08-23 in ``lauf_tmp``): fehlt eine Grenze – kein
   Sandbox-Benutzer, kein ``bwrap``, kein ``systemd-run``, keine
   Loopback-Sperre –, laeuft der Befehl NICHT, und der Benutzer erfaehrt
   warum. ``bereit()`` ist die eine Pruefung dafuer, Broker und Alt-Betrieb
   rufen dieselbe.
3. **RESSOURCEN** ueber ``systemd-run --scope`` (cgroup v2): Speicher, Anzahl
   Prozesse, CPU-Anteil und eine Laufzeitgrenze. Auf DEV gemessen
   (2026-10-05, als jarvis_sandbox im bwrap): 512 MB bei 256 MB Grenze ->
   beendet, 64 MB laufen (Positivkontrolle); 100 Prozesse bei 32 -> Abbruch;
   eine per ``nohup … & disown`` abgehaengte Waise ist nach ``RuntimeMaxSec``
   weg. **Die Laufzeitgrenze ist mehr als ein zweiter Timeout:** ``killpg``
   erreicht nichts, was sich in eine eigene Sitzung abgesetzt hat – den Scope
   schon. Zeilenweises Streaming bleibt erhalten (gemessen).
4. **NETZ.** Benutzer OHNE Internet-Freigabe laufen mit ``bwrap
   --unshare-net``: im Lauf gibt es nur ein eigenes, leeres ``lo`` (gemessen:
   127.0.0.1:443, 8.8.8.8 und die eigene Adresse unerreichbar). Fuer Benutzer
   MIT Internet geht das nicht; fuer sie sperrt eine nftables-Tabelle den
   LOOPBACK fuer alle Sandbox-UIDs. Gemessen VOR der Sperre: Jarvis selbst
   (443), cups (631) und die eigene Adresse waren aus der Sandbox erreichbar –
   und ein Chrome-Debug-Port, ueber den sich der Browser des Dienstes
   fernsteuern liesse. Deshalb ALLE Ports statt der drei aus dem Bericht.
   DNS auf ``lo`` bleibt offen (ein lokaler Resolver waere sonst tot).

Was es NICHT loest, ehrlich benannt: ohne Netz-Namespace bleiben fuer Benutzer
MIT Internet die abstrakten Unix-Sockets des Hosts erreichbar (sie haengen am
Netz-Namespace, nicht am Dateisystem). Gemessen: der X-Server auf :0 weist eine
Verbindung ohne Cookie ab (Antwort-Byte 0). Und die Grenzen gelten je BEFEHL,
nicht fuer alle Laeufe zusammen.
"""

from __future__ import annotations

import os
import pwd
import shutil
import subprocess
import threading
import time
import uuid

SANDBOX_PREFIX = "jarvis_sandbox"
SBX_USER = "jarvis_sandbox"
NOINET_USER = "jarvis_sandbox_noinet"

SYSTEMD_RUN = "/usr/bin/systemd-run"
NFT_TABELLE = "jarvis_sandbox_lo"

# Vorgaben und erlaubte Bereiche. Der BROKER klemmt auf diese Bereiche – die
# Werte kommen aus settings.json, die der Dienstbenutzer schreiben kann, und
# ein "0" oder "-1" darf die Grenze nicht aufheben.
STANDARD = {"speicher_mb": 2048, "prozesse": 256, "cpu_prozent": 200}
BEREICH = {"speicher_mb": (128, 65536), "prozesse": (16, 4096),
           "cpu_prozent": (10, 6400)}
# Einstellungsschluessel je Grenze (eine Stelle, damit Oberflaeche, Dispatch
# und Status dieselben Namen benutzen).
EINSTELLUNG = {"speicher_mb": "sandbox_grenze_speicher_mb",
               "prozesse": "sandbox_grenze_prozesse",
               "cpu_prozent": "sandbox_grenze_cpu_prozent"}
EINSTELLUNG_ADMINS = "sandbox_auch_admins"
# Vorgabe fuer den Admin-Schalter (Betreiberentscheid 2026-10-11: AN, abschaltbar).
# Bestehende Installationen behalten ihr Verhalten: vorgabe_festschreiben()
# schreibt dort beim ersten Start mit diesem Stand ausdruecklich False fest.
VORGABE_ADMINS = True

# Puffer der Laufzeitgrenze ueber dem Befehls-Timeout: der Timeout des
# Aufrufers soll zuerst greifen (er meldet "Timeout"), der Scope ist das Netz
# fuer alles, was sich abgehaengt hat.
LAUFZEIT_PUFFER_S = 15
LAUFZEIT_MAX_S = 6 * 3600


def _log(msg: str) -> None:
    print(f"[SANDBOX-H10] {msg}", flush=True)


# ── Grenzen ─────────────────────────────────────────────────────────────────

def grenzen_pruefen(roh) -> dict:
    """Rohwerte (Einstellung oder Broker-Argument) auf gueltige Grenzen klemmen.

    Unlesbares faellt auf die Vorgabe, Werte ausserhalb des Bereichs auf die
    naechste Bereichsgrenze. ``bool`` zaehlt NICHT als Zahl (``True`` waere
    sonst 1 MB). Es gibt bewusst keinen Wert, der "ohne Grenze" heisst.
    """
    roh = roh if isinstance(roh, dict) else {}
    aus = {}
    for k, vorgabe in STANDARD.items():
        v = roh.get(k)
        if isinstance(v, bool):
            v = None
        try:
            v = int(v)
        except (TypeError, ValueError):
            v = vorgabe
        lo, hi = BEREICH[k]
        aus[k] = max(lo, min(hi, v))
    return aus


def aus_einstellungen() -> dict:
    """Grenzen aus settings.json (geklemmt)."""
    try:
        from backend.config import config
        roh = {k: config.get_setting(s, None) for k, s in EINSTELLUNG.items()}
    except Exception:  # noqa: BLE001
        roh = {}
    return grenzen_pruefen(roh)


def auch_admins() -> bool:
    """Schalter "Sandbox auch fuer Administratoren" (Vorgabe AN seit 2026-10-11).

    Betreiberentscheid 2026-10-05: waehlbar je Installation; 2026-10-11: Vorgabe
    AN, abschaltbar. AUS heisst: die Shell privilegierter Benutzer laeuft wie
    bisher als Dienstbenutzer (H9: nur nach Klick).

    Nur ein echtes ``bool`` ist eine Entscheidung. Alles andere (nicht gesetzt,
    ``"false"`` als Zeichenkette, unlesbare Einstellung) ergibt die Vorgabe –
    also die SICHERERE Richtung. Bis 2026-10-11 war es umgekehrt (nur ``True``
    schaltete ein), weil die Vorgabe AUS war.
    """
    try:
        from backend.config import config
        v = config.get_setting(EINSTELLUNG_ADMINS, None)
    except Exception:  # noqa: BLE001
        return VORGABE_ADMINS
    return v if isinstance(v, bool) else VORGABE_ADMINS


def vorgabe_festschreiben(bestand: bool):
    """Einmalig beim Start: den Admin-Schalter ausdruecklich setzen, wenn er fehlt.

    Ohne diesen Schritt haette die neue Vorgabe (AN) JEDE bestehende
    Installation beim naechsten Update still umgestellt – dort ist der Schalter
    meist nie gesetzt worden. ``bestand`` (settings.json gab es schon vor diesem
    Prozess) -> ``False`` festschreiben: das Verhalten bleibt, wie es war.
    Erstinstallation -> die Vorgabe festschreiben, damit sie sichtbar in der
    Einstellung steht. Ein bereits gesetzter Wert wird NIE angefasst.
    Rueckgabe: der geschriebene Wert oder None (nichts zu tun / Fehler).
    """
    try:
        from backend.config import config
        if config.get_setting(EINSTELLUNG_ADMINS, None) is not None:
            return None
        wert = False if bestand else VORGABE_ADMINS
        config.save_setting(EINSTELLUNG_ADMINS, wert)
        _log(f"'Sandbox auch fuer Administratoren' festgeschrieben: {wert} "
             f"({'bestehende Installation – Verhalten bleibt' if bestand else 'Erstinstallation – Vorgabe'})")
        return wert
    except Exception as e:  # noqa: BLE001
        _log(f"Vorgabe des Admin-Schalters nicht festgeschrieben: {e}")
        return None


def scope_praefix(grenzen: dict, timeout_s: int) -> list:
    """``systemd-run --scope …`` vor den Befehl – die Ressourcengrenzen.

    ``MemorySwapMax=0``: ohne das wiche ein Lauf an der Speichergrenze in den
    Swap aus und braeuchte die Maschine statt sich selbst zu beenden.
    Der Unit-Name traegt eine Zufallskennung, damit gleichzeitige Laeufe sich
    nicht ins Gehege kommen und ein Scope im Journal auffindbar ist.
    """
    g = grenzen_pruefen(grenzen)
    try:
        t = int(timeout_s)
    except (TypeError, ValueError):
        t = 120
    laufzeit = max(30, min(LAUFZEIT_MAX_S, t + LAUFZEIT_PUFFER_S))
    return [
        SYSTEMD_RUN, "--scope", "--quiet", "--collect",
        "--unit=jarvis-sandbox-" + uuid.uuid4().hex[:12],
        "-p", "MemoryMax=%dM" % g["speicher_mb"],
        "-p", "MemorySwapMax=0",
        "-p", "TasksMax=%d" % g["prozesse"],
        "-p", "CPUQuota=%d%%" % g["cpu_prozent"],
        "-p", "RuntimeMaxSec=%d" % laufzeit,
        "--",
    ]


def grenze_vermutlich_getroffen(rc) -> bool:
    """Exit-Code eines Laufs, den der Scope beendet hat (SIGKILL/SIGTERM).

    Unterscheiden laesst sich Speicher von Laufzeit von aussen nicht sicher –
    die Meldung nennt deshalb alle Grenzen, statt eine zu raten.
    """
    return rc in (137, 143, -9, -15)


# ── Sandbox-Benutzer ────────────────────────────────────────────────────────

def _uid(name: str):
    try:
        return pwd.getpwnam(name).pw_uid
    except (KeyError, TypeError):
        return None


def _gueltig(name: str) -> bool:
    uid = _uid(name)
    return bool(name) and name.startswith(SANDBOX_PREFIX) and uid not in (None, 0)


def sandbox_benutzer(internet: bool) -> tuple:
    """(OS-Benutzer, Grund) fuer einen Sandbox-Lauf – Grund nur, wenn keiner da ist.

    Reihenfolge: Einstellung, sonst der Standardbenutzer, sofern er existiert.
    Ohne Internet: ``sandbox_shell_user_noinet`` bzw. ``jarvis_sandbox_noinet``,
    sonst der normale Sandbox-Benutzer – das Netz ist dann ueber
    ``--unshare-net`` trotzdem zu, der eigene Benutzer ist nur die zweite Lage
    (Egress-Firewall).
    """
    try:
        from backend.config import config
        gesetzt = (config.get_setting("sandbox_shell_user", "") or "").strip()
        gesetzt_ni = (config.get_setting("sandbox_shell_user_noinet", "") or "").strip()
    except Exception:  # noqa: BLE001
        gesetzt, gesetzt_ni = "", ""
    kandidaten = []
    if not internet:
        kandidaten += [gesetzt_ni, NOINET_USER]
    kandidaten += [gesetzt, SBX_USER]
    for k in kandidaten:
        if k and _gueltig(k):
            return k, ""
    falsch = [k for k in (gesetzt, gesetzt_ni) if k and not _gueltig(k)]
    if falsch:
        return "", ("eingestellter Sandbox-Benutzer ungueltig oder nicht vorhanden: "
                    + ", ".join(falsch))
    return "", ("kein Sandbox-Benutzer eingerichtet (Einstellungen → Sicherheit → "
                "Systemschutz / Sandbox → Aktivieren / Reparieren)")


def sandbox_uids() -> list:
    """Alle Sandbox-UIDs dieses Systems (fuer die Loopback-Sperre)."""
    uids = set()
    try:
        for pw in pwd.getpwall():
            if pw.pw_name.startswith(SANDBOX_PREFIX) and pw.pw_uid != 0:
                uids.add(pw.pw_uid)
    except Exception:  # noqa: BLE001
        pass
    return sorted(uids)


# ── Loopback-Sperre ─────────────────────────────────────────────────────────

def lo_regeln(uids) -> str:
    """nftables-Text der Sperre. Atomar ersetzt (anlegen, loeschen, neu).

    Nur ``oif "lo"``: Verkehr an die EIGENE Adresse des Servers geht ebenfalls
    ueber lo und ist damit mit erfasst (gemessen: 443 an der eigenen Adresse
    war vorher erreichbar). Kein uid-loses Drop – Kernel-Sockets (CIFS/NFS)
    tragen keine skuid, siehe egress_guard.
    """
    ids = ", ".join(str(int(u)) for u in uids)
    return (
        f"table inet {NFT_TABELLE} {{}}\n"
        f"delete table inet {NFT_TABELLE}\n"
        f"table inet {NFT_TABELLE} {{\n"
        "    chain out {\n"
        "        type filter hook output priority filter; policy accept;\n"
        f"        oif \"lo\" meta skuid {{ {ids} }} udp dport 53 accept\n"
        f"        oif \"lo\" meta skuid {{ {ids} }} tcp dport 53 accept\n"
        f"        oif \"lo\" meta skuid {{ {ids} }} meta l4proto tcp reject with tcp reset\n"
        f"        oif \"lo\" meta skuid {{ {ids} }} reject\n"
        "    }\n"
        "}\n"
    )


_lo_lock = threading.Lock()
_lo_stand = {"zeit": 0.0, "uids": None}
_LO_FRIST_S = 60.0


def _nft() -> str:
    return shutil.which("nft") or "/usr/sbin/nft"


def lo_sperre_sicherstellen(erzwingen: bool = False) -> tuple:
    """(ok, Grund). Setzt die Sperre (root) – hoechstens einmal je Frist.

    Selbstheilend statt "einmal beim Einrichten": eine Regel, die nur ein
    Knopf herstellt, erreicht keinen Bestandsserver (Register, Egress-Fix
    2026-09-04). Hier stellt sie jeder Sandbox-Lauf her; ein ``nft flush
    ruleset`` von aussen ist nach spaetestens einer Minute geheilt.
    """
    if os.geteuid() != 0:
        return False, "Loopback-Sperre braucht root"
    uids = sandbox_uids()
    if not uids:
        return False, "kein Sandbox-Benutzer vorhanden"
    with _lo_lock:
        jetzt = time.monotonic()
        if (not erzwingen and _lo_stand["uids"] == uids
                and (jetzt - _lo_stand["zeit"]) < _LO_FRIST_S):
            return True, ""
        try:
            r = subprocess.run([_nft(), "-f", "-"], input=lo_regeln(uids),
                               capture_output=True, text=True, timeout=15)
        except Exception as e:  # noqa: BLE001
            return False, f"nft nicht ausfuehrbar: {e}"
        if r.returncode != 0:
            _log(f"Loopback-Sperre nicht gesetzt: {(r.stderr or '').strip()[:200]}")
            _lo_stand.update(zeit=0.0, uids=None)
            return False, "Loopback-Sperre nicht setzbar: " + (r.stderr or "").strip()[:160]
        if _lo_stand["uids"] is None:
            _log(f"Loopback-Sperre aktiv fuer uid {uids}")
        _lo_stand.update(zeit=jetzt, uids=uids)
        return True, ""


def lo_sperre_aktiv() -> bool | None:
    """Ist die Tabelle geladen? None = nicht messbar (kein root)."""
    if os.geteuid() != 0:
        return None
    try:
        r = subprocess.run([_nft(), "list", "table", "inet", NFT_TABELLE],
                           capture_output=True, text=True, timeout=10)
        return r.returncode == 0 and "skuid" in (r.stdout or "")
    except Exception:  # noqa: BLE001
        return False


# ── Die Pflichtpruefung ─────────────────────────────────────────────────────

def bereit(sandbox_user: str) -> tuple:
    """(ok, Grund): kann ein Lauf als ``sandbox_user`` MIT allen Grenzen starten?

    EINE Pruefung fuer Broker und Alt-Betrieb. Jede Antwort ausser ``True``
    heisst: der Befehl laeuft nicht (fail-closed). Der Grund ist fuer Benutzer
    und Journal formuliert, nicht fuer Entwickler.
    """
    if not _gueltig(sandbox_user):
        return False, f"Sandbox-Benutzer fehlt oder ist ungueltig: {sandbox_user or '-'}"
    if os.geteuid() != 0:
        return False, "Sandbox-Laeufe brauchen den Root-Broker"
    if not os.path.exists(SYSTEMD_RUN):
        return False, "Ressourcengrenzen nicht verfuegbar (systemd-run fehlt)"
    try:
        from backend import lauf_tmp as _lt
        if not _lt.isolation_gewuenscht():
            return False, "Isolation ist abgeschaltet (JARVIS_LAUF_ISOLATION=0)"
        if not _lt.bwrap_verfuegbar(sandbox_user):
            return False, ("Isolation nicht verfuegbar (bubblewrap fehlt oder "
                           "funktioniert nicht – apt-get install -y bubblewrap)")
    except Exception as e:  # noqa: BLE001
        return False, f"Isolation nicht pruefbar: {e}"
    ok, grund = lo_sperre_sicherstellen()
    if not ok:
        return False, grund
    return True, ""


def status() -> dict:
    """Zustand fuer die Statusanzeige (laeuft im Broker, also als root)."""
    try:
        from backend import lauf_tmp as _lt
        bwrap = os.path.exists(_lt.BWRAP)
        iso = _lt.isolation_gewuenscht()
    except Exception:  # noqa: BLE001
        bwrap, iso = False, False
    return {
        "pflicht": True,
        "auch_admins": auch_admins(),
        "grenzen": aus_einstellungen(),
        "grenzen_bereich": BEREICH,
        "systemd_run": os.path.exists(SYSTEMD_RUN),
        "bwrap": bwrap,
        "isolation_gewuenscht": iso,
        "lo_sperre": lo_sperre_aktiv(),
        "sandbox_uids": sandbox_uids(),
    }
