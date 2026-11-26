"""Ausgangsfilter (Haertung D1) aus der Oberflaeche: ansehen und bearbeiten.

Die REGELN stehen nicht hier, sondern in ``deploy/security/ausgang.sh`` – dasselbe
Skript, das auch die Konsole benutzt (eine zweite Fassung liefe auseinander).
Dieses Modul ruft es aus der ROOT-EIGENEN Kopie (``CODE_ROOT``, Befund K1):

* ``status()``    liest Konfiguration, geladenen Satz, Boot-Unit und die
                  Protokollzeilen der letzten Stunden (``nft-aus-frei`` /
                  ``nft-aus-drop``), je Benutzer, Ziel und Port gezaehlt.
* ``speichern()`` prueft einen neuen Konfigurationstext mit ``--zeigen`` an
                  einer Wegwerf-Kopie, schreibt ihn erst DANACH nach
                  ``/etc/jarvis/ausgang.conf`` und wendet ihn an. Scheitert das
                  Anwenden, kommt der alte Text zurueck – die Datei beschreibt
                  sonst einen Satz, der gar nicht geladen ist.
* ``entfernen()`` nimmt Tabelle, gespeicherten Satz und Unit weg; die
                  Konfiguration bleibt (zum spaeteren Wiederanwenden).

Freigabe-Code (meta.py): ``speichern`` und ``entfernen`` brauchen ihn. Jede
Aenderung entscheidet, was der Server nach aussen darf – auch eine scheinbar
einschraenkende (MODUS=sperre) kann LLM, Dateiserver oder Verzeichnis
stilllegen, und ``entfernen`` hebt den Filter ganz auf.

AIDE: ``/etc/jarvis/ausgang.conf`` und ``ausgang.nft`` stehen im Register
``backend/eigene_dateien.py``; der Daemon vermerkt die Uebergaenge jeder
Meta-Op, also auch die, die ``ausgang.sh`` selbst schreibt.

Nur Standardbibliothek (System-Python des Brokers).
"""

from __future__ import annotations

import os
import pwd
import re
import subprocess
import tempfile
from pathlib import Path

from backend.broker import CODE_ROOT

SKRIPT = CODE_ROOT / "deploy" / "security" / "ausgang.sh"
KONF = Path(os.environ.get("JARVIS_AUSGANG_CONF", "/etc/jarvis/ausgang.conf"))
ABLAGE = Path(os.environ.get("JARVIS_AUSGANG_ABLAGE", "/etc/jarvis/ausgang.nft"))
UNIT = "jarvis-ausgang.service"
TABELLE = "jarvis_ausgang"
# Groesse einer Konfiguration: eine Zeile je Freigabe, real ~20 Zeilen
MAX_ZEICHEN = 20000
MAX_ZEILEN = 400
# Protokoll: Zeitraum und Obergrenze der gezeigten Ziele
STUNDEN_VORGABE = 24
MAX_STUNDEN = 24 * 14
MAX_TREFFER = 200

_FELD = re.compile(r"\b(PROTO|DST|DPT|UID|OUT)=(\S*)")


def _lauf(befehl: list[str], konf: Path | None = None, timeout: int = 60) -> subprocess.CompletedProcess:
    umg = dict(os.environ, LC_ALL="C", LANG="C", JARVIS_AUSGANG_CONF=str(konf or KONF),
               JARVIS_AUSGANG_ABLAGE=str(ABLAGE))
    return subprocess.run(befehl, capture_output=True, text=True, timeout=timeout, env=umg)


def _fehlertext(r: subprocess.CompletedProcess) -> str:
    """Erste FEHLER-Zeile des Skripts (die nennt Zeile und Grund), sonst stderr."""
    for z in (r.stderr or "").splitlines():
        if z.startswith("FEHLER:"):
            return z[len("FEHLER:"):].strip()[:300]
    return (r.stderr or r.stdout or "").strip()[:300]


def freigaben_lesen(text: str) -> dict:
    """Konfiguration fuer die ANZEIGE zerlegen – geprueft wird nur im Skript.
    Gibt {modus, freigaben: [{benutzer, proto, ports, ziele, zeile}]} zurueck."""
    modus = "protokoll"
    liste = []
    for nr, zeile in enumerate(text.splitlines(), 1):
        z = zeile.split("#", 1)[0].strip()
        if not z:
            continue
        if z.startswith("MODUS="):
            modus = z[len("MODUS="):].strip()
            continue
        t = z.split()
        if len(t) == 5 and t[0] == "erlaube":
            liste.append({"benutzer": t[1], "proto": t[2], "ports": t[3], "ziele": t[4], "zeile": nr})
    return {"modus": modus, "freigaben": liste}


def _name(uid: str) -> str:
    try:
        return pwd.getpwuid(int(uid)).pw_name
    except (KeyError, ValueError):
        return ""


def treffer_lesen(zeilen: list[str]) -> list[dict]:
    """Protokollzeilen (journalctl -o short-unix) je Art, Benutzer, Protokoll,
    Ziel und Port zaehlen. Zeilen ohne nft-aus-Praefix werden uebergangen."""
    zaehler: dict[tuple, dict] = {}
    for z in zeilen:
        art = "drop" if "nft-aus-drop:" in z else ("frei" if "nft-aus-frei:" in z else "")
        if not art:
            continue
        f = dict(_FELD.findall(z))
        try:
            ts = float(z.split(None, 1)[0])
        except (ValueError, IndexError):
            ts = 0.0
        uid = f.get("UID", "")
        schluessel = (art, uid, f.get("PROTO", ""), f.get("DST", ""), f.get("DPT", ""))
        e = zaehler.get(schluessel)
        if e is None:
            e = zaehler[schluessel] = {"art": art, "uid": uid, "benutzer": _name(uid) if uid else "",
                                       "proto": f.get("PROTO", ""), "ziel": f.get("DST", ""),
                                       "port": f.get("DPT", ""), "anzahl": 0, "zuletzt": 0.0}
        e["anzahl"] += 1
        e["zuletzt"] = max(e["zuletzt"], ts)
    return sorted(zaehler.values(), key=lambda e: (-e["anzahl"], -e["zuletzt"]))[:MAX_TREFFER]


def _protokoll(stunden: int) -> tuple[list[dict], bool]:
    """(Treffer, lesbar). Nicht lesbar ist etwas anderes als "keine Zeilen"."""
    # _TRANSPORT=kernel statt -k: -k schliesst -b ein und liest nur den
    # laufenden Systemstart – nach einem Neustart waere der Zeitraum davor
    # leer, obwohl er im Journal steht (DEV 26.11.2026 gesehen)
    try:
        r = _lauf(["journalctl", "_TRANSPORT=kernel", "--no-pager", "-o", "short-unix", "--since",
                   f"-{stunden}h", "--grep", "nft-aus-(frei|drop):"], timeout=60)
    except Exception:  # noqa: BLE001
        return [], False
    # journalctl --grep endet mit 1, wenn nichts passt
    if r.returncode not in (0, 1):
        return [], False
    return treffer_lesen(r.stdout.splitlines()), True


def _geladen() -> dict:
    """Policy der geladenen Kette; None = nicht geladen bzw. nicht lesbar."""
    try:
        r = _lauf(["nft", "list", "chain", "inet", TABELLE, "out"], timeout=20)
    except Exception:  # noqa: BLE001
        return {"geladen": None, "policy": None}
    if r.returncode != 0:
        return {"geladen": False, "policy": None}
    m = re.search(r"policy\s+(accept|drop)", r.stdout)
    return {"geladen": True, "policy": m.group(1) if m else None}


def status(stunden=STUNDEN_VORGABE) -> dict:
    try:
        stunden = max(1, min(MAX_STUNDEN, int(stunden)))
    except (TypeError, ValueError):
        stunden = STUNDEN_VORGABE
    text = ""
    vorhanden = KONF.is_file()
    if vorhanden:
        try:
            text = KONF.read_text(encoding="utf-8")[:MAX_ZEICHEN]
        except OSError:
            vorhanden = False
    gueltig, fehler = None, ""
    if vorhanden:
        try:
            r = _lauf(["bash", str(SKRIPT), "--zeigen"], timeout=30)
            gueltig = r.returncode == 0
            fehler = "" if gueltig else _fehlertext(r)
        except Exception as e:  # noqa: BLE001
            gueltig, fehler = False, str(e)[:200]
    try:
        unit = _lauf(["systemctl", "is-enabled", UNIT], timeout=15).stdout.strip() or "fehlt"
    except Exception:  # noqa: BLE001
        unit = "unbekannt"
    treffer, lesbar = _protokoll(stunden)
    erg = {"ok": True, "konfiguration": vorhanden, "text": text, "gueltig": gueltig,
           "fehler": fehler, "unit": unit, "stunden": stunden, "treffer": treffer,
           "protokoll_lesbar": lesbar, "skript": SKRIPT.is_file()}
    erg.update(freigaben_lesen(text))
    erg.update(_geladen())
    return erg


def _normieren(text) -> str | None:
    """Text als Zeilen mit \\n, abschliessend mit \\n; None = unbrauchbar."""
    if not isinstance(text, str):
        return None
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > MAX_ZEICHEN or text.count("\n") > MAX_ZEILEN or "\x00" in text:
        return None
    return text.rstrip("\n") + "\n"


def _schreiben(p: Path, inhalt: str) -> None:
    """Atomar, 0600 VOR dem Umbenennen – kein Moment mit weiteren Rechten."""
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    fd = os.open(str(tmp), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, inhalt.encode("utf-8"))
        os.fsync(fd)
    finally:
        os.close(fd)
    os.replace(tmp, p)


def pruefen(text) -> dict:
    """Neuen Text an einer Wegwerf-Kopie durch ``--zeigen`` schicken."""
    text = _normieren(text)
    if text is None:
        return {"ok": False, "meldung": f"Konfiguration unbrauchbar (hoechstens {MAX_ZEILEN} Zeilen, {MAX_ZEICHEN} Zeichen)."}
    with tempfile.TemporaryDirectory(prefix="jarvis-ausgang-") as d:
        probe = Path(d) / "ausgang.conf"
        _schreiben(probe, text)
        try:
            r = _lauf(["bash", str(SKRIPT), "--zeigen"], konf=probe, timeout=30)
        except Exception as e:  # noqa: BLE001
            return {"ok": False, "meldung": str(e)[:200]}
    if r.returncode != 0:
        return {"ok": False, "meldung": _fehlertext(r)}
    return {"ok": True, "text": text, "regeln": r.stdout.count(" accept comment ")}


def speichern(text) -> dict:
    """Pruefen, schreiben, anwenden – und bei einem Fehlschlag zurueck."""
    probe = pruefen(text)
    if not probe.get("ok"):
        return probe
    text = probe["text"]
    alt = None
    if KONF.is_file():
        try:
            alt = KONF.read_text(encoding="utf-8")
        except OSError:
            alt = None
    _schreiben(KONF, text)
    try:
        r = _lauf(["bash", str(SKRIPT), "--anwenden"], timeout=120)
    except Exception as e:  # noqa: BLE001
        r = subprocess.CompletedProcess([], 1, "", str(e))
    if r.returncode != 0:
        if alt is None:
            try:
                KONF.unlink()
            except OSError:
                pass
        else:
            _schreiben(KONF, alt)
        return {"ok": False, "rc": r.returncode, "meldung": _fehlertext(r),
                "zurueck": True}
    return {"ok": True, "rc": 0, "meldung": (r.stdout or "").strip()[:300]}


def entfernen() -> dict:
    try:
        r = _lauf(["bash", str(SKRIPT), "--entfernen"], timeout=60)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "meldung": str(e)[:200]}
    return {"ok": r.returncode == 0, "rc": r.returncode,
            "meldung": (r.stdout if r.returncode == 0 else _fehlertext(r)).strip()[:300]}
