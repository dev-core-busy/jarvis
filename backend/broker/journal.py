"""Journal-Einsicht ueber den Root-Broker (BSI M8, 2026-10-12).

WARUM: der Dienstbenutzer ``jarvis`` stand in den Gruppen ``adm`` und
``systemd-journal`` und konnte damit JEDES Systemprotokoll lesen – auch das
anderer Dienste und der Anmeldungen. Jeder Code, der als ``jarvis`` laeuft
(Agenten-Shell eines Administrators, ein uebernommenes Backend), hatte diese
Einsicht mit. ``haertung_installieren.sh`` nimmt die Gruppen bei jedem
Broker-Start weg; die Einsicht in die EIGENEN Dienste laeuft seitdem ueber die
Broker-Op ``journal_lesen``:

* nur Jarvis-Einheiten (``jarvis*.service``, ``whatsapp-bridge.service``) –
  ohne ``-u`` gaebe ``journalctl`` das ganze Systemjournal heraus;
* gedeckelte Zeilenzahl, Werte nur als ``--option=wert`` (kein Wert kann als
  eigene Option gelesen werden), Aufruf als Argumentliste ohne Shell;
* jede Abfrage im Broker-Audit; Geheimnisse in Adressen geschwaerzt (BSI M4).

``aus_befehl`` uebersetzt einen ``journalctl``-Aufruf der Agenten-Shell in die
Op-Argumente. Er kennt bewusst nur die Lese-Optionen; alles andere (``-f``,
``--vacuum-*``, ``-k`` …) gibt ``None`` und laeuft wie bisher als Dienstbenutzer
– also ohne Systemjournal.

Dieses Modul gehoert zum Broker-Paket, weil der Broker es aus SEINER Kopie
laedt (nach einer Aenderung: ``systemctl restart jarvis-broker.service``).
"""
from __future__ import annotations

import re
import shlex

ZEILEN_VORGABE = 200
ZEILEN_MAX = 2000
SUCHE_MAX = 200
AUSGABE_MAX = 1_000_000          # Zeichen; danach wird gekappt und beziffert

_EINHEIT = re.compile(r"^(?:jarvis(?:-[a-z0-9][a-z0-9-]{0,40})?|whatsapp-bridge)(?:\.service)?$")
# Zeitangaben fuer --since/--until: "2026-10-12 08:00", "-1h", "yesterday", "10 min ago"
_ZEIT = re.compile(r"^[0-9A-Za-z][0-9A-Za-z :.+-]{0,39}$|^-[0-9]{1,6}[smhdw]?$")
_PRIO = {"emerg", "alert", "crit", "err", "warning", "notice", "info", "debug"}


def _einheit(wert) -> str:
    e = str(wert or "").strip()
    # fullmatch: der ganze Name, nicht nur ein Anfang (Rand-Leerraum hat strip schon entfernt)
    if not _EINHEIT.fullmatch(e):
        raise ValueError("Einheit nicht erlaubt: %r (nur jarvis*.service, whatsapp-bridge.service)" % e[:60])
    return e if e.endswith(".service") else e + ".service"


def pruefen(args: dict) -> dict:
    """Argumente pruefen und normieren. Wirft ``ValueError`` mit Grund."""
    args = args or {}
    out = {"einheit": _einheit(args.get("einheit"))}
    roh = args.get("zeilen", ZEILEN_VORGABE)
    if isinstance(roh, bool):
        raise ValueError("zeilen muss eine Zahl sein")
    try:
        n = int(str(roh).strip())
    except (TypeError, ValueError):
        raise ValueError("zeilen muss eine Zahl sein") from None
    out["zeilen"] = max(1, min(n, ZEILEN_MAX))
    for k in ("seit", "bis"):
        v = str(args.get(k) or "").strip()
        if v:
            if not _ZEIT.fullmatch(v):
                raise ValueError("%s ungueltig: %r" % (k, v[:40]))
            out[k] = v
    p = str(args.get("prioritaet") or "").strip().lower()
    if p:
        if not (p in _PRIO or (p.isdigit() and 0 <= int(p) <= 7)):
            raise ValueError("prioritaet ungueltig: %r" % p[:20])
        out["prioritaet"] = p
    s = str(args.get("suche") or "")
    if s:
        if len(s) > SUCHE_MAX or "\n" in s or "\x00" in s:
            raise ValueError("suche zu lang oder mit Zeilenumbruch")
        out["suche"] = s
    out["umgekehrt"] = args.get("umgekehrt") is True
    return out


def argv(norm: dict) -> list[str]:
    """journalctl-Aufruf als Argumentliste (ohne Shell)."""
    cmd = ["journalctl", "--no-pager", "-o", "short-iso",
           "--unit=" + norm["einheit"], "--lines=%d" % norm["zeilen"]]
    if norm.get("seit"):
        cmd.append("--since=" + norm["seit"])
    if norm.get("bis"):
        cmd.append("--until=" + norm["bis"])
    if norm.get("prioritaet"):
        cmd.append("--priority=" + norm["prioritaet"])
    if norm.get("suche"):
        cmd.append("--grep=" + norm["suche"])
    if norm.get("umgekehrt"):
        cmd.append("--reverse")
    return cmd


# ── Uebersetzung aus der Agenten-Shell ──────────────────────────────────────

def _erstes_rohr(befehl: str) -> int:
    """Index des ersten '|' ausserhalb von Anfuehrungszeichen, das kein '||' ist;
    -1, wenn es keines gibt."""
    q = None
    i = 0
    while i < len(befehl):
        c = befehl[i]
        if q:
            if c == "\\" and q == '"':
                i += 2
                continue
            if c == q:
                q = None
        elif c in "'\"":
            q = c
        elif c == "\\":
            i += 2
            continue
        elif c == "|":
            if befehl[i + 1:i + 2] == "|":
                return -1          # '||' -> kein einfaches Rohr, nicht uebersetzen
            return i
        i += 1
    return -1


# Optionen, die nur die DARSTELLUNG betreffen und hier fest gesetzt sind
_OHNE_WERT_EGAL = {"--no-pager", "-q", "--quiet", "-x", "--catalog", "--no-hostname",
                   "-l", "--full", "-a", "--all", "--no-full"}
_MIT_WERT_EGAL = {"-o", "--output"}
_ABBILDUNG = {"-u": "einheit", "--unit": "einheit", "-n": "zeilen", "--lines": "zeilen",
              "-S": "seit", "--since": "seit", "-U": "bis", "--until": "bis",
              "-p": "prioritaet", "--priority": "prioritaet", "-g": "suche", "--grep": "suche"}


def aus_befehl(befehl: str):
    """``(args, rest)`` fuer einen einfachen journalctl-Aufruf, sonst ``None``.

    ``rest`` ist die Fortsetzung hinter dem ersten ``|`` (z.B. ``grep -i fehler``)
    oder ``""``. Uebersetzt wird nur, was eindeutig ist: ein Aufruf, genau eine
    Einheit, nur bekannte Lese-Optionen, im ersten Abschnitt keine Umleitung,
    kein ``;``/``&&``/``$(`` und keine Unterschale.
    """
    b = (befehl or "").strip()
    if not b:
        return None
    pos = _erstes_rohr(b)
    kopf, rest = (b, "") if pos < 0 else (b[:pos], b[pos + 1:].strip())
    if pos >= 0 and not rest:
        return None
    if re.search(r"[;&<>`]|\$\(|\n", kopf):
        return None
    try:
        teile = shlex.split(kopf)
    except ValueError:
        return None
    if teile and teile[0] == "sudo":
        teile = teile[1:]
    if not teile or teile[0].rsplit("/", 1)[-1] != "journalctl":
        return None
    args: dict = {}
    i = 1
    while i < len(teile):
        t = teile[i]
        if t in _OHNE_WERT_EGAL:
            i += 1
            continue
        if t in ("-r", "--reverse"):
            args["umgekehrt"] = True
            i += 1
            continue
        name, wert = t, None
        if t.startswith("--") and "=" in t:
            name, wert = t.split("=", 1)
        elif re.match(r"^-[unSUpgo].+", t):
            name, wert = t[:2], t[2:]
        if name in _MIT_WERT_EGAL:
            i += 1 if wert is not None else 2
            continue
        ziel = _ABBILDUNG.get(name)
        if ziel is None:
            return None              # unbekannte Option -> nicht uebersetzen
        if wert is None:
            if i + 1 >= len(teile):
                return None
            wert = teile[i + 1]
            i += 2
        else:
            i += 1
        if ziel in args:
            return None              # doppelt (z.B. zwei -u) -> nicht eindeutig
        args[ziel] = wert
    if "einheit" not in args:
        return None                  # ohne -u waere es das ganze Systemjournal
    return args, rest
