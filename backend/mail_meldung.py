#!/usr/bin/env python3
"""E-Mail-Versand fuer Meldungen des Servers (Warnungen, AIDE, Sicherheitsverletzungen).

WARUM (gemessen auf DEV und ECHT am 24.11.2026)
-----------------------------------------------
Auf keinem der beiden Server lief ein Mailserver (kein ``/usr/sbin/sendmail``).
Alles, was Debian und Jarvis "an root" melden – der taegliche AIDE-Bericht,
unattended-upgrades, cron-Fehler, die Ueberwachung B13 – ging ins Leere oder
stand nur im Journal, das niemand liest, solange nichts auffaellt.

AUFBAU
------
* **Postfix als Null-Client**: nimmt Mail NUR von diesem Rechner an
  (``inet_interfaces = loopback-only``) und lauscht auf KEINEM Port – der
  SMTP-Eingang in ``master.cf`` ist auskommentiert. Abgeben duerfen nur root
  (``authorized_submit_users``): die Sandbox-Benutzer und der Dienstbenutzer
  kommen an ``sendmail`` nicht heran, ein eingeschleuster Lauf kann den Server
  also nicht als Mailschleuder benutzen. Alles geht an EINEN Relay (Vorgabe:
  der interne Exchange, Port 25 – er nahm beim Messen von DEV und ECHT ohne
  Anmeldung Post an die Zieladresse an, bietet aber kein TLS an).
  ``smtp_tls_security_level = may``: bietet ein Relay STARTTLS an, wird es
  benutzt.
* **Konfiguration** in ``/etc/jarvis/broker.conf`` (root-eigen):
  ``MAIL_EMPFAENGER`` (Komma-Liste), ``MAIL_RELAY`` (``host[:port]``),
  ``MAIL_QUELLEN`` (Teilmenge von ``QUELLEN``; fehlt der Schluessel: alle).
  Gepflegt unter Einstellungen -> KI & System -> E-Mail-Versand ueber den
  Broker (``backend/broker/meta.py``, Ops ``broker.mailversand*``).
* **Quellen**
  - ``ueberwachung``: B13 (``ueberwachung.py``) – nur bei einer AENDERUNG,
    genau wie die Journalzeilen, eine Mail je Lauf.
  - ``aide``: der Abgleich (``aide_abgleich.py``) meldet "offen" (nicht
    erklaerte Aenderungen) und "fehler". Debians eigener Tagesbericht wird
    stillgelegt (Drop-in ``MAILCMD=true``): er listet nach jedem Update
    hunderte erklaerte Paketdateien – das ist Laerm, und Laerm laesst die
    eine wichtige Mail ungelesen.
  - ``sicherheit``: gesperrte Konten (Angriffserkennung, Richtlinien-Verstoss,
    Fehlanmeldungen), Spruehangriffe. Kommt vom Dienst ueber die Broker-Op
    ``broker.mail_melden`` – der Dienst selbst darf nicht senden (siehe oben),
    und er schickt nur Metadaten (wer, Kanal, Art), NIE Inhalte.
  - ``system``: alles, was Debian an root schickt (Alias ``root``). Aus =
    ``root: /dev/null``.
* **Drosselung** je Quelle und Stunde (``GRENZE_JE_STUNDE``). Was darueber
  liegt, wird gezaehlt und in der naechsten Mail genannt – eine Mailflut
  begraebt sonst genau die Meldung, um die es geht, und kann den Relay
  fuer andere sperren.
* **AIDE**: Dateien, die dieses Modul schreibt (``/etc/postfix/main.cf``,
  ``/etc/aliases`` …), stehen mit ihrer Pruefsumme in ``GESCHRIEBEN``. Der
  Abgleich erklaert eine Aenderung daran nur, wenn der Inhalt GENAU dieser
  Stand ist (``erklaert``) – sonst haette jede Aenderung in der Oberflaeche
  eine Durchsicht ausgeloest.

Nur Standardbibliothek: laeuft als root aus der root-eigenen Broker-Kopie mit
dem System-Python (Befund K1), auch direkt aus ``ueberwachung.py``.

Aufruf (root):
  python3 -I mail_meldung.py --status | --einrichten | --anwenden | --test
  echo TEXT | python3 -I mail_meldung.py --senden QUELLE BETREFF
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import sys
import time
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid
from pathlib import Path

# Testwurzel: alle Dateipfade unter W (wie aide_abgleich.py), Befehle ueber _lauf
W = os.environ.get("JARVIS_MAIL_WURZEL", "")

BROKER_CONF = os.environ.get("JARVIS_BROKER_CONF", "/etc/jarvis/broker.conf")
ZUSTAND_DIR = "/var/lib/jarvis-mail"
ZUSTAND = ZUSTAND_DIR + "/zustand.json"
GESCHRIEBEN = ZUSTAND_DIR + "/geschrieben.json"
SENDMAIL = "/usr/sbin/sendmail"
POSTFIX = "/usr/sbin/postfix"
MAIN_CF = "/etc/postfix/main.cf"
MASTER_CF = "/etc/postfix/master.cf"
ALIASES = "/etc/aliases"
MAILNAME = "/etc/mailname"
AIDE_DROPIN = "/etc/systemd/system/dailyaidecheck.service.d/81-jarvis-mail.conf"
AIDE_AUSNAHME = "/etc/aide/aide.conf.d/96_jarvis_mailversand"
# Serverueberwachung (B13, jarvis-ueberwachung.service) laeuft mit
# ProtectSystem=strict – ohne diese Freigabe scheitert ihr sendmail an
# "maildrop: Read-only file system" und der Lauf haengt, bis postdrop aufgibt.
UEBERW_DROPIN = "/etc/systemd/system/jarvis-ueberwachung.service.d/81-jarvis-mail.conf"
MAILDROP = "/var/spool/postfix/maildrop"

QUELLEN = ("ueberwachung", "aide", "sicherheit", "system")
GRENZE_JE_STUNDE = {"ueberwachung": 20, "aide": 6, "sicherheit": 12, "test": 5}
EMPFAENGER_MAX = 10
ABSENDER_LOKAL = "jarvis"
# Lokale Ablage der Zustellungsfehler (Rueckmeldungen) – nie an den Relay
ALIAS_ABSENDER = "%s: /dev/null" % ABSENDER_LOKAL

_ADRESSE = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})+$")
# Absender: auch ohne Punkt im Domaenenteil (``name@server``) – der interne
# Exchange nahm ``jarvis@jarvis`` als Absender an (DEV/ECHT 24.11.2026);
# gemeldet wurde ``meldung@server`` als abgewiesen. Empfaenger bleiben streng.
_ABSENDER = re.compile(r"^[A-Za-z0-9._%+-]{1,64}@[A-Za-z0-9-]{1,63}(?:\.[A-Za-z0-9-]{1,63})*$")
_HOST = re.compile(r"^(?=.{1,253}$)[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
                   r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
_MARKE_AN = "# >>> jarvis-mailversand (backend/mail_meldung.py) – nicht von Hand aendern"
_MARKE_AUS = "# <<< jarvis-mailversand"
_AUSKOMMENTIERT = "#jarvis-mailversand# "


def _p(pfad: str) -> Path:
    return Path(W + pfad) if W else Path(pfad)


# ── Rueckmeldungen an die Oberflaeche: Kennung + Werte ──────────────────────
# Die Oberflaeche uebersetzt ``code`` in der gewaehlten Sprache (i18n
# ``mv.m_<code>`` mit ``werte``); ``meldung`` bleibt der deutsche Satz fuer
# Audit und Konsole. Vorher kam jeder Satz fertig deutsch an – bei FR stand
# dann "Échec : Keine gültige Absenderadresse" (gemeldet 2026-11-24).
# Waechter: tests/test_mail_meldung.py (jede Rueckmeldung traegt eine Kennung,
# jede Kennung steht in DE/EN/FR).
class Meldung(str):
    """Ein Satz MIT Kennung und Werten – bleibt ein str fuer alle Aufrufer."""

    def __new__(cls, code: str, satz: str, **werte):
        o = str.__new__(cls, satz)
        o.code = code
        o.werte = {k: (v if isinstance(v, (int, float)) else str(v)) for k, v in werte.items()}
        return o


def antwort(ok: bool, m, **felder) -> dict:
    """Antwort-Objekt mit meldung (deutsch), code und werte."""
    return {"ok": ok, "meldung": str(m), "code": getattr(m, "code", ""),
            "werte": dict(getattr(m, "werte", {}) or {}), **felder}


def _lauf(befehl: list[str], timeout: int = 60, eingabe: str | None = None,
          umgebung: dict | None = None) -> subprocess.CompletedProcess:
    umg = dict(os.environ, LC_ALL="C", LANG="C")
    if umgebung:
        umg.update(umgebung)
    return subprocess.run(befehl, capture_output=True, text=True, timeout=timeout,
                          input=eingabe, env=umg)


# ── Konfiguration ────────────────────────────────────────────────────────────

def _konf_roh() -> dict[str, str]:
    """broker.conf lesen – letzte Zeile gewinnt, wie in den Skripten."""
    werte: dict[str, str] = {}
    try:
        for z in _p(BROKER_CONF).read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", z)
            if m:
                werte[m.group(1)] = m.group(2).strip().strip("'\"")
    except OSError:
        pass
    return werte


def empfaenger_pruefen(text) -> tuple[list[str], str]:
    """Komma-/Leerzeichen-/Semikolon-Liste -> (Adressen, Fehler)."""
    if isinstance(text, (list, tuple)):
        text = ",".join(str(t) for t in text)
    teile = [t for t in re.split(r"[\s,;]+", str(text or "").strip()) if t]
    aus: list[str] = []
    for t in teile:
        if not _ADRESSE.match(t):
            return [], Meldung("empfaenger_ungueltig", "Keine gültige E-Mail-Adresse: %s" % t[:80], wert=t[:80])
        if t.lower() not in (a.lower() for a in aus):
            aus.append(t)
    if len(aus) > EMPFAENGER_MAX:
        return [], Meldung("empfaenger_zuviele", "Höchstens %d Empfänger" % EMPFAENGER_MAX, max=EMPFAENGER_MAX)
    return aus, ""


def relay_pruefen(text) -> tuple[str, str]:
    """``host``, ``host:port`` oder ``[host]:port`` -> (``host:port``, Fehler).
    Leer = Zustellung direkt an den MX des Empfaengers (ohne Relay)."""
    t = str(text or "").strip()
    if not t:
        return "", ""
    m = re.match(r"^\[?([^\]\[:\s]+)\]?(?::(\d{1,5}))?$", t)
    if not m or not _HOST.match(m.group(1)):
        return "", Meldung("relay_ungueltig", "Kein gültiger Servername: %s" % t[:80], wert=t[:80])
    port = int(m.group(2) or 25)
    if not 1 <= port <= 65535:
        return "", Meldung("port_ungueltig", "Ungültiger Port: %s" % m.group(2), wert=m.group(2))
    return "%s:%d" % (m.group(1), port), ""


def quellen_pruefen(werte) -> tuple[list[str], str]:
    if isinstance(werte, str):
        werte = [w for w in re.split(r"[\s,;]+", werte) if w]
    aus = []
    for w in werte or []:
        w = str(w).strip().lower()
        if w not in QUELLEN:
            return [], Meldung("quelle_unbekannt", "Unbekannte Meldungsart: %s" % w[:40], wert=w[:40])
        if w not in aus:
            aus.append(w)
    return [q for q in QUELLEN if q in aus], ""


# Absender und Betreff (Oberflaeche). Leer = Vorgabe. ``{server}`` wird durch den
# kurzen Rechnernamen ersetzt – so passt dieselbe Einstellung auf jeden Server.
VORGABE_NAME = "Jarvis {server}"
VORGABE_BETREFF = "[Jarvis {server}]"
TEXT_MAX = 80


def absender_pruefen(text) -> tuple[str, str]:
    """Absenderadresse: leer (= jarvis@<rechner>) oder eine gueltige Adresse."""
    t = str(text or "").strip()
    if t and not _ABSENDER.match(t):
        return "", Meldung("absender_ungueltig", "Keine gültige Absenderadresse: %s" % t[:80], wert=t[:80])
    return t, ""


def text_pruefen(text, was: str) -> tuple[str, str]:
    """Einzeiliger Text fuer Anzeigename/Betreff (kein Kopf-Einschleusen)."""
    t = str(text or "").strip()
    if re.search(r"[\x00-\x1f\x7f]", t):
        return "", Meldung("steuerzeichen", "%s darf keine Steuerzeichen enthalten" % was, feld=was.lower())
    if len(t) > TEXT_MAX:
        return "", Meldung("zu_lang", "%s: höchstens %d Zeichen" % (was, TEXT_MAX), feld=was.lower(), max=TEXT_MAX)
    return t, ""


def konf() -> dict:
    roh = _konf_roh()
    empf, _ = empfaenger_pruefen(roh.get("MAIL_EMPFAENGER", ""))
    relay, _ = relay_pruefen(roh.get("MAIL_RELAY", ""))
    if "MAIL_QUELLEN" in roh:
        quellen, _ = quellen_pruefen(roh.get("MAIL_QUELLEN", ""))
    else:
        quellen = list(QUELLEN)
    sprache = roh.get("MAIL_SPRACHE", "de")
    sprache = sprache if sprache in SPRACHEN else "de"
    marke = text_pruefen(roh.get("MAIL_MARKE", ""), "Marke")[0] or "Jarvis"
    absender, _ = absender_pruefen(roh.get("MAIL_ABSENDER", ""))
    name, _ = text_pruefen(roh.get("MAIL_ABSENDER_NAME", ""), "Name")
    betreff, _ = text_pruefen(roh.get("MAIL_BETREFF", ""), "Betreff")
    return {"empfaenger": empf, "relay": relay, "quellen": quellen,
            "absender": absender, "absender_name": name, "betreff": betreff,
            "sprache": sprache, "marke": marke}


def _absender_adresse(k: dict, fqdn: str) -> str:
    return k.get("absender") or "%s@%s" % (ABSENDER_LOKAL, fqdn)


def _konf_schreiben(werte: dict[str, str]) -> None:
    """Zeilen ``SCHLUESSEL=wert`` ersetzen oder anhaengen; Rechte bleiben."""
    pfad = _p(BROKER_CONF)
    try:
        zeilen = pfad.read_text(encoding="utf-8").splitlines()
    except OSError:
        zeilen = []
    for schluessel, wert in werte.items():
        neu = "%s=%s" % (schluessel, wert)
        treffer = False
        for i, z in enumerate(zeilen):
            if re.match(r"\s*%s\s*=" % schluessel, z):
                zeilen[i] = neu if not treffer else None
                treffer = True
        zeilen = [z for z in zeilen if z is not None]
        if not treffer:
            zeilen.append(neu)
    # Rechte wie vorgefunden (auf DEV 0644): andere Leser der Datei sollen
    # nicht still ausgesperrt werden; neu angelegt 0600.
    try:
        modus = pfad.stat().st_mode & 0o777
    except OSError:
        modus = 0o600
    _atomar(pfad, "\n".join(zeilen) + "\n", modus, merken=False)


# ── Dateien schreiben (mit Merkzettel fuer AIDE) ─────────────────────────────

def _sha(daten: bytes) -> str:
    return hashlib.sha256(daten).hexdigest()


def _geschrieben_lesen() -> dict:
    try:
        d = json.loads(_p(GESCHRIEBEN).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _merken(pfad: str, sha: str | None) -> None:
    d = _geschrieben_lesen()
    if sha is None:
        d.pop(pfad, None)
    else:
        d[pfad] = sha
    _atomar(_p(GESCHRIEBEN), json.dumps(d, indent=1, sort_keys=True) + "\n", 0o600, merken=False)


def _atomar(pfad: Path, text: str, modus: int, merken: bool = True) -> bool:
    """Schreibt nur bei Aenderung; True = geaendert. root-eigen, ``modus``."""
    daten = text.encode("utf-8")
    try:
        if pfad.read_bytes() == daten:
            if merken:
                _merken(str(pfad)[len(W):] if W else str(pfad), _sha(daten))
            return False
    except OSError:
        pass
    pfad.parent.mkdir(parents=True, exist_ok=True)
    tmp = pfad.with_name(".%s.neu.%d" % (pfad.name, os.getpid()))
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, modus)
    try:
        os.write(fd, daten)
        os.fsync(fd)
    finally:
        os.close(fd)
    os.chmod(tmp, modus)
    if os.geteuid() == 0:
        os.chown(tmp, 0, 0)
    os.replace(tmp, pfad)
    if merken:
        _merken(str(pfad)[len(W):] if W else str(pfad), _sha(daten))
    return True


def erklaert(pfad: str) -> bool:
    """Fuer aide_abgleich: ist die Datei GENAU der Stand, den dieses Modul
    zuletzt geschrieben hat? (Pruefsumme, nicht Zeit oder Name.)"""
    soll = _geschrieben_lesen().get(pfad)
    if not soll:
        return False
    try:
        return _sha(_p(pfad).read_bytes()) == soll
    except OSError:
        return False


# ── Postfix-Konfiguration ────────────────────────────────────────────────────

def _fqdn() -> str:
    """myhostname fuer Postfix: ohne Punkt verweigert Postfix den Start."""
    try:
        name = (_lauf(["hostname", "-f"], timeout=10).stdout or "").strip()
    except Exception:  # noqa: BLE001
        name = ""
    name = name or socket.gethostname() or "localhost"
    if not _HOST.match(name):
        name = "localhost"
    return name if "." in name else name + ".localdomain"


def _db_typ() -> str:
    """Tabellentyp fuer /etc/aliases. ``$default_database_type`` in
    alias_database loest newaliases NICHT auf ("unsupported dictionary type",
    DEV 24.11.2026) – deshalb ausdruecklich (Debian 13: hash)."""
    try:
        t = (_lauf(["postconf", "-d", "-h", "default_database_type"], timeout=15).stdout or "").strip()
    except Exception:  # noqa: BLE001
        t = ""
    return t if re.match(r"^[a-z]{2,12}$", t) else "hash"


def main_cf(k: dict, fqdn: str, db: str = "hash") -> str:
    relay = ""
    if k["relay"]:
        host, port = k["relay"].rsplit(":", 1)
        relay = "[%s]:%s" % (host, port)
    return "\n".join([
        "# Verwaltet von Jarvis (backend/mail_meldung.py) – Einstellungen -> KI & System",
        "# -> E-Mail-Versand. Aenderungen hier gehen beim naechsten Speichern verloren.",
        "# Null-Client: nimmt nur lokal abgegebene Mail von root an und gibt sie an",
        "# den Relay weiter. Kein SMTP-Eingang (master.cf), kein Empfang von aussen.",
        "compatibility_level = 3.6",
        "myhostname = %s" % fqdn,
        "mydomain = %s" % fqdn.split(".", 1)[1],
        "myorigin = $myhostname",
        "mydestination = $myhostname, localhost.$mydomain, localhost",
        "relayhost = %s" % relay,
        "inet_interfaces = loopback-only",
        "inet_protocols = ipv4",
        "mynetworks = 127.0.0.0/8",
        "authorized_submit_users = root",
        "alias_maps = %s:%s" % (db, ALIASES),
        "alias_database = %s:%s" % (db, ALIASES),
        "smtp_tls_security_level = may",
        "smtp_tls_CAfile = /etc/ssl/certs/ca-certificates.crt",
        "smtpd_banner = $myhostname ESMTP",
        "disable_vrfy_command = yes",
        "biff = no",
        "append_dot_mydomain = no",
        "message_size_limit = 10240000",
        "maximal_queue_lifetime = 2d",
        "bounce_queue_lifetime = 1d",
        "",
    ])


def aliases(text_alt: str, k: dict) -> str:
    """``root`` an die Empfaenger (Quelle "system") oder ins Leere; fremde
    ``root:``-Zeilen werden markiert auskommentiert, nie geloescht."""
    zeilen = []
    drin = False
    for z in text_alt.splitlines():
        if z.strip() == _MARKE_AN:
            drin = True
            continue
        if z.strip() == _MARKE_AUS:
            drin = False
            continue
        if drin:
            continue
        if re.match(r"\s*(root|%s)\s*:" % ABSENDER_LOKAL, z):
            z = _AUSKOMMENTIERT + z
        zeilen.append(z)
    while zeilen and not zeilen[-1].strip():
        zeilen.pop()
    ziel = ", ".join(k["empfaenger"]) if ("system" in k["quellen"] and k["empfaenger"]) else "/dev/null"
    if not any(re.match(r"\s*postmaster\s*:", z) for z in zeilen):
        zeilen.append("postmaster: root")
    zeilen += ["", _MARKE_AN, "root: %s" % ziel, ALIAS_ABSENDER, _MARKE_AUS, ""]
    return "\n".join(zeilen)


AIDE_DROPIN_TEXT = (
    "# Jarvis E-Mail-Versand (backend/mail_meldung.py): Debians eigenen AIDE-Bericht\n"
    "# nicht verschicken – er listet nach jedem Update alle erklaerten Paketdateien.\n"
    "# Gemeldet wird der Abgleich (nicht erklaerte Aenderungen, Fehler).\n"
    "[Service]\n"
    "Environment=MAILCMD=true\n")
UEBERW_DROPIN_TEXT = (
    "# Jarvis E-Mail-Versand (backend/mail_meldung.py): die Serverueberwachung\n"
    "# (ProtectSystem=strict) muss Mails abgeben (postdrop -> maildrop) und die\n"
    "# Drosselung fuehren koennen. Gemessen DEV 2026-11-26: ohne diese Zeile\n"
    "# 'maildrop: Read-only file system', keine Mail, Lauf haengt ~60 s.\n"
    "# '-' = fehlt der Pfad (Postfix noch nicht da), startet die Unit trotzdem.\n"
    "[Service]\n"
    "ReadWritePaths=-%s -%s\n" % (MAILDROP, ZUSTAND_DIR))
AIDE_AUSNAHME_TEXT = (
    "# Jarvis E-Mail-Versand (backend/mail_meldung.py): Zustand der Drosselung\n"
    "!/var/lib/jarvis-mail\n")


def installiert() -> bool:
    return _p(POSTFIX).exists() and _p(SENDMAIL).exists()


def anwenden() -> dict:
    """Konfiguration aus broker.conf nach Postfix uebertragen (idempotent). Wirft nie."""
    try:
        return _anwenden()
    except Exception as e:  # noqa: BLE001
        return antwort(False, Meldung("anwenden_fehler", "Fehler beim Anwenden: %s" % e, fehler=e))


def _anwenden() -> dict:
    if not installiert():
        return antwort(False, Meldung("nicht_installiert", "Der Mailserver ist nicht installiert – bitte zuerst einrichten."))
    k = konf()
    schritte = []
    try:
        alt_aliases = _p(ALIASES).read_text(encoding="utf-8")
    except OSError:
        alt_aliases = ""
    fqdn = _fqdn()
    g_main = _atomar(_p(MAIN_CF), main_cf(k, fqdn, _db_typ()), 0o644)
    g_name = _atomar(_p(MAILNAME), fqdn + "\n", 0o644)
    g_alias = _atomar(_p(ALIASES), aliases(alt_aliases, k), 0o644)
    g_drop = _atomar(_p(AIDE_DROPIN), AIDE_DROPIN_TEXT, 0o644)
    g_ueberw = _atomar(_p(UEBERW_DROPIN), UEBERW_DROPIN_TEXT, 0o644)
    if _p("/etc/aide/aide.conf.d").is_dir():
        _atomar(_p(AIDE_AUSNAHME), AIDE_AUSNAHME_TEXT, 0o644)
    # SMTP-Eingang aus: Postfix lauscht dann auf keinem Port
    r = _lauf(["postconf", "-M", "smtp/inet"], timeout=20)
    if r.returncode == 0 and r.stdout.strip():
        r2 = _lauf(["postconf", "-M#", "smtp/inet"], timeout=20)
        schritte.append("SMTP-Eingang abgeschaltet" if r2.returncode == 0 else
                        "SMTP-Eingang abschalten gescheitert: %s" % (r2.stderr or "").strip()[:200])
        if r2.returncode != 0:
            return antwort(False, Meldung("smtp_aus_fehler", schritte[-1], fehler=(r2.stderr or "").strip()[:200]),
                           schritte=schritte)
        try:
            _merken(MASTER_CF, _sha(_p(MASTER_CF).read_bytes()))
        except OSError:
            pass
    if g_alias or not _alias_db_da():
        r = _lauf(["newaliases"], timeout=30)
        if r.returncode != 0:
            return antwort(False, Meldung("newaliases", "newaliases: %s" % (r.stderr or r.stdout).strip()[:300],
                                          fehler=(r.stderr or r.stdout).strip()[:300]), schritte=schritte)
        for db in _alias_dbs():
            _merken(db, _sha(_p(db).read_bytes()))
        schritte.append("Weiterleitung fuer root aktualisiert")
    if g_drop or g_ueberw:
        _lauf(["systemctl", "daemon-reload"], timeout=30)
    if g_drop:
        schritte.append("Debians AIDE-Tagesbericht stillgelegt")
    if g_ueberw:
        schritte.append("Serverueberwachung darf Mails abgeben")
    r = _lauf(["postfix", "check"], timeout=30)
    if r.returncode != 0:
        return antwort(False, Meldung("postfix_check", "postfix check: %s" % (r.stderr or r.stdout).strip()[:300],
                                      fehler=(r.stderr or r.stdout).strip()[:300]), schritte=schritte)
    if g_main or g_name or g_alias or any("SMTP" in s for s in schritte):
        r = _lauf(["systemctl", "restart", "postfix"], timeout=60)
        schritte.append("Postfix neu gestartet" if r.returncode == 0 else
                        "Neustart gescheitert: %s" % (r.stderr or "").strip()[:200])
        if r.returncode != 0:
            return antwort(False, Meldung("neustart_fehler", schritte[-1], fehler=(r.stderr or "").strip()[:200]),
                           schritte=schritte)
    else:
        _lauf(["systemctl", "enable", "--now", "postfix"], timeout=60)
    return antwort(True, Meldung("konfig_uebernommen", "Konfiguration übernommen"), schritte=schritte)


def _alias_dbs() -> list[str]:
    return [ALIASES + e for e in (".db", ".lmdb", ".cdb") if _p(ALIASES + e).exists()]


def _alias_db_da() -> bool:
    return bool(_alias_dbs())


def einrichten() -> dict:
    """Postfix installieren (ohne Rueckfragen) und konfigurieren."""
    if not installiert():
        _lauf(["debconf-set-selections"], timeout=30,
              eingabe="postfix postfix/main_mailer_type select No configuration\n")
        r = _lauf(["apt-get", "install", "-y", "--no-install-recommends", "postfix"], timeout=900,
                  umgebung={"DEBIAN_FRONTEND": "noninteractive"})
        if r.returncode != 0:
            letzte = ((r.stderr or r.stdout).strip().splitlines() or ["?"])[-1][:300]
            return antwort(False, Meldung("installation_fehler", "Installation gescheitert: %s" % letzte, fehler=letzte))
    erg = anwenden()
    if erg.get("ok"):
        erg.update(antwort(True, Meldung("eingerichtet", "Mailserver eingerichtet")), schritte=erg.get("schritte", []))
    return erg


# ── Zustand / Status ─────────────────────────────────────────────────────────

def _zustand_lesen() -> dict:
    try:
        d = json.loads(_p(ZUSTAND).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _zustand_schreiben(z: dict) -> None:
    try:
        _atomar(_p(ZUSTAND), json.dumps(z, ensure_ascii=False, indent=1) + "\n", 0o640, merken=False)
        if os.geteuid() == 0 and not W:
            import grp
            os.chown(_p(ZUSTAND), 0, grp.getgrnam("jarvis").gr_gid)
    except (OSError, KeyError, ImportError):
        pass


def _warteschlange() -> dict:
    """Anzahl Nachrichten in der Postfix-Warteschlange und letzter Grund."""
    try:
        r = _lauf(["postqueue", "-j"], timeout=20)
    except Exception:  # noqa: BLE001
        return {"anzahl": None}
    if r.returncode != 0:
        return {"anzahl": None}
    anzahl, grund = 0, ""
    for z in r.stdout.splitlines():
        try:
            d = json.loads(z)
        except ValueError:
            continue
        anzahl += 1
        for e in d.get("recipients") or []:
            if e.get("delay_reason"):
                grund = str(e["delay_reason"])[:300]
    return {"anzahl": anzahl, "grund": grund}


def _lauscht() -> list[str]:
    """Adressen, auf denen Postfix (master) lauscht – soll leer sein."""
    try:
        r = _lauf(["ss", "-Hltnp"], timeout=15)
    except Exception:  # noqa: BLE001
        return []
    return [z.split()[3] for z in r.stdout.splitlines()
            if '"master"' in z and len(z.split()) > 3]


def status() -> dict:
    k = konf()
    inst = installiert()
    aktiv = False
    if inst:
        try:
            aktiv = _lauf(["systemctl", "is-active", "--quiet", "postfix"], timeout=15).returncode == 0
        except Exception:  # noqa: BLE001
            aktiv = False
    z = _zustand_lesen()
    aktuell = None
    if inst:
        try:
            aktuell = _p(MAIN_CF).read_text(encoding="utf-8") == main_cf(k, _fqdn(), _db_typ())
        except OSError:
            aktuell = False
    return {"ok": True, "installiert": inst, "aktiv": aktiv,
            "konfig_aktuell": aktuell, "lauscht": _lauscht() if aktiv else [],
            "warteschlange": _warteschlange() if aktiv else {"anzahl": None},
            "empfaenger": k["empfaenger"], "relay": k["relay"], "quellen": k["quellen"],
            "absender": k["absender"], "absender_name": k["absender_name"], "betreff": k["betreff"],
            "sprache": k["sprache"],
            "vorgabe": {"absender": "%s@%s" % (ABSENDER_LOKAL, _fqdn()),
                        "absender_name": VORGABE_NAME, "betreff": VORGABE_BETREFF},
            "alle_quellen": list(QUELLEN), "letzte": (z.get("letzte") or [])[-10:],
            "server": _fqdn()}


# ── Senden ───────────────────────────────────────────────────────────────────

def _drossel(z: dict, quelle: str, jetzt: float) -> tuple[bool, int]:
    """(erlaubt, bisher unterdrueckt). Festes Stundenfenster je Quelle."""
    d = z.setdefault("drossel", {}).setdefault(quelle, {"start": jetzt, "anzahl": 0, "unterdrueckt": 0})
    if jetzt - float(d.get("start", 0)) >= 3600:
        d["start"], d["anzahl"] = jetzt, 0
    if d["anzahl"] >= GRENZE_JE_STUNDE.get(quelle, 10):
        d["unterdrueckt"] = int(d.get("unterdrueckt", 0)) + 1
        return False, d["unterdrueckt"]
    d["anzahl"] += 1
    weg = int(d.get("unterdrueckt", 0))
    d["unterdrueckt"] = 0
    return True, weg


def _einzeilig(s, n: int = 200) -> str:
    return re.sub(r"[\r\n\t]+", " ", str(s or "")).strip()[:n]


# ── Sprache der Mails (i18n.js / i18n_fr.js / i18n_nl.js) ─────────────────────
# Die Meldungen sind in der Sprache verfasst, die in der Oberflaeche gewaehlt
# ist (MAIL_SPRACHE, gesetzt beim Speichern und beim Umschalten der Sprache in
# den Einstellungen). Die Texte kommen aus DERSELBEN Quelle wie die Oberflaeche
# – eine zweite Kopie hier liefe auseinander. Gelesen wird die root-eigene
# Kopie neben diesem Modul (broker_installieren.sh kopiert die Woerterbuecher
# mit), nie die des Dienstbenutzers. Fehlt ein Text: Rueckfall fr/nl -> en -> de,
# zuletzt der hier mitgegebene deutsche Text.
SPRACHEN = ("de", "en", "fr", "nl")
_RUECKFALL = {"de": ("de",), "en": ("en", "de"), "fr": ("fr", "en", "de"), "nl": ("nl", "en", "de")}
I18N_JS = Path(__file__).resolve().parent.parent / "frontend" / "js" / "i18n.js"
I18N_FR = Path(__file__).resolve().parent.parent / "frontend" / "js" / "i18n_fr.js"
I18N_NL = Path(__file__).resolve().parent.parent / "frontend" / "js" / "i18n_nl.js"
# Woerterbuecher, die sich als _I18N.<sprache> anhaengen (JSON-Schreibweise)
_ZUSATZ = (("fr", I18N_FR), ("nl", I18N_NL))
_TEXTE_CACHE: dict = {}


def _js_text(roh: str) -> str:
    """Inhalt eines JS-Zeichenkettenliterals (ohne Anfuehrungszeichen) entschluesseln."""
    aus, i = [], 0
    while i < len(roh):
        c = roh[i]
        if c == "\\" and i + 1 < len(roh):
            n = roh[i + 1]
            if n == "u" and re.match(r"[0-9a-fA-F]{4}", roh[i + 2:i + 6]):
                aus.append(chr(int(roh[i + 2:i + 6], 16)))
                i += 6
                continue
            aus.append({"n": "\n", "t": "\t", "r": ""}.get(n, n))
            i += 2
            continue
        aus.append(c)
        i += 1
    return "".join(aus)


def _texte_laden() -> dict:
    """{sprache: {schluessel: text}} fuer die Schluessel, die Mails brauchen."""
    try:
        stempel = (I18N_JS.stat().st_mtime,) + tuple(d.stat().st_mtime if d.exists() else 0 for _, d in _ZUSATZ)
    except OSError:
        return {}
    if _TEXTE_CACHE.get("stempel") == stempel:
        return _TEXTE_CACHE["texte"]
    texte: dict = {s: {} for s in SPRACHEN}
    wichtig = re.compile(r"^(?:mvm\.|ue\.art_)")
    try:
        js = I18N_JS.read_text(encoding="utf-8")
        de_an, en_an = js.find("\n    de: {"), js.find("\n    en: {")
        if de_an >= 0 and en_an > de_an:
            for sprache, teil in (("de", js[de_an:en_an]), ("en", js[en_an:])):
                for m in re.finditer(r"^\s*'([A-Za-z0-9_.\-]+)'\s*:\s*'((?:[^'\\\n]|\\.)*)'", teil, re.M):
                    if wichtig.match(m.group(1)) and m.group(1) not in texte[sprache]:
                        texte[sprache][m.group(1)] = _js_text(m.group(2))
        for sprache, datei in _ZUSATZ:
            if not datei.exists():
                continue
            for m in re.finditer(r'^\s*"([A-Za-z0-9_.\-]+)"\s*:\s*"((?:[^"\\\n]|\\.)*)"',
                                 datei.read_text(encoding="utf-8"), re.M):
                if wichtig.match(m.group(1)):
                    texte[sprache][m.group(1)] = json.loads('"%s"' % m.group(2))
    except (OSError, ValueError):
        return {}
    _TEXTE_CACHE.update(stempel=stempel, texte=texte)
    return texte


def text(schluessel: str, vorgabe: str, sprache: str = "de", **werte) -> str:
    """Text in ``sprache`` mit ``{name}``-Platzhaltern; Rueckfall wie die Oberflaeche."""
    alle = _texte_laden()
    roh = vorgabe
    for s in _RUECKFALL.get(sprache, ("de",)):
        if (alle.get(s) or {}).get(schluessel):
            roh = alle[s][schluessel]
            break
    return re.sub(r"\{(\w+)\}", lambda m: str(werte[m.group(1)]) if m.group(1) in werte else m.group(0), roh)


def zeitpunkt(sek, sprache: str, mit_uhr: bool = True) -> str:
    """Datum (und Uhrzeit) in der Schreibweise der Sprache; leer bei 0."""
    try:
        t = time.localtime(float(sek))
    except (TypeError, ValueError, OverflowError):
        return ""
    if not sek:
        return ""
    datum = time.strftime("%d/%m/%Y" if sprache in ("en", "fr") else ("%d-%m-%Y" if sprache == "nl" else "%d.%m.%Y"), t)
    return datum + (time.strftime(" %H:%M", t) if mit_uhr else "")


def befund_text(b: dict, sprache: str, marke: str = "Jarvis") -> str:
    """Text eines Ueberwachungs-Befunds in ``sprache`` – dieselben Vorlagen und
    Werte wie die Anzeige am Zahnrad (sysload.js ueText). Ohne Vorlage: der
    deutsche Text des Befunds (der auch im Journal steht)."""
    art = str(b.get("art", ""))
    w = b.get("werte") or {}
    try:
        if art == "zert_ablauf" and float(w.get("tage", 0)) < 0:
            art = "zert_abgelaufen"
    except (TypeError, ValueError):
        pass
    if art == "in_drop" and b.get("stufe") == "warnung":
        art = "in_drop_voll"
    werte = {}
    for k_, v in w.items():
        if k_ == "zuletzt":
            v = zeitpunkt(v, sprache)
        elif k_ == "ablauf":
            v = zeitpunkt(v, sprache, mit_uhr=False)
        elif isinstance(v, (list, tuple)):
            v = ", ".join(str(x) for x in v)
        elif isinstance(v, float) and k_ == "prozent":
            v = ("%.1f" % v) if sprache == "en" else ("%.1f" % v).replace(".", ",")
        werte[k_] = "" if v is None else v
    werte["marke"] = marke
    return text("ue.art_" + art, str(b.get("text", "")), sprache, **werte)


QUELLEN_TEXT = {
    "ueberwachung": ("mvm.q_ueberwachung", "Serverüberwachung"),
    "aide": ("mvm.q_aide", "Integritätsprüfung (AIDE)"),
    "sicherheit": ("mvm.q_sicherheit", "Sicherheitsverletzung"),
    "system": ("mvm.q_system", "System"),
    "test": ("mvm.q_test", "Testnachricht"),
}


def quelle_name(quelle: str, sprache: str) -> str:
    k_, d = QUELLEN_TEXT.get(quelle, ("", quelle))
    return text(k_, d, sprache) if k_ else d


def nachricht(quelle: str, betreff: str, inhalt: str, k: dict, fqdn: str,
              unterdrueckt: int = 0) -> EmailMessage:
    kurz = fqdn.split(".", 1)[0]
    m = EmailMessage()
    name = (k.get("absender_name") or VORGABE_NAME).replace("{server}", kurz)
    m["From"] = formataddr((name, _absender_adresse(k, fqdn)))
    m["To"] = ", ".join(k["empfaenger"])
    praefix = (k.get("betreff") or VORGABE_BETREFF).replace("{server}", kurz)
    m["Subject"] = ("%s %s" % (praefix, _einzeilig(betreff, 160))).strip()
    m["Date"] = formatdate(localtime=True)
    m["Message-ID"] = make_msgid(domain=fqdn)
    m["Auto-Submitted"] = "auto-generated"
    m["X-Jarvis-Quelle"] = quelle
    sp = k.get("sprache", "de")
    kopf = ["%s: %s" % (text("mvm.kopf_server", "Server", sp), fqdn),
            "%s: %s" % (text("mvm.kopf_zeit", "Zeit", sp), zeitpunkt(time.time(), sp)),
            "%s: %s" % (text("mvm.kopf_art", "Art", sp), quelle_name(quelle, sp)), ""]
    if unterdrueckt:
        kopf += [text("mvm.gedrosselt", "Hinweis: {n} weitere Meldung(en) dieser Art wurden in der letzten "
                      "Stunde zurückgehalten (Drosselung) – sie stehen im Journal und in der Oberfläche.",
                      sp, n=unterdrueckt), ""]
    fuss = ["", "-- ", text("mvm.fuss", "Diese Nachricht verschickt {server} automatisch. Empfänger und "
                            "Meldungsarten: Einstellungen → KI & System → E-Mail-Versand.", sp, server=fqdn)]
    m.set_content("\n".join(kopf) + str(inhalt or "").rstrip() + "\n" + "\n".join(fuss) + "\n")
    return m


def senden(quelle: str, betreff: str, text: str) -> dict:
    """Eine Meldung verschicken – sofern die Quelle eingeschaltet ist, es
    Empfaenger gibt und die Drosselung es zulaesst. Wirft nie."""
    try:
        return _senden(quelle, betreff, text)
    except Exception as e:  # noqa: BLE001
        return antwort(False, Meldung("fehler", "Fehler: %s" % e, fehler=e), gesendet=False)


def _senden(quelle: str, betreff: str, text: str) -> dict:
    if quelle not in QUELLEN and quelle != "test":
        return antwort(False, Meldung("quelle_unbekannt", "Unbekannte Quelle", wert=quelle), gesendet=False)
    k = konf()
    if not k["empfaenger"]:
        return antwort(True, Meldung("kein_empfaenger", "Kein Empfänger eingetragen"), gesendet=False)
    if quelle != "test" and quelle not in k["quellen"]:
        return antwort(True, Meldung("quelle_aus", "Meldungsart ausgeschaltet"), gesendet=False)
    if not installiert():
        return antwort(False, Meldung("nicht_installiert", "Der Mailserver ist nicht installiert"), gesendet=False)
    jetzt = time.time()
    z = _zustand_lesen()
    erlaubt, unterdrueckt = _drossel(z, quelle, jetzt)
    if not erlaubt:
        _zustand_schreiben(z)
        n = GRENZE_JE_STUNDE.get(quelle, 10)
        return antwort(True, Meldung("gedrosselt", "Gedrosselt (%d je Stunde)" % n, n=n),
                       gesendet=False, gedrosselt=True)
    fqdn = _fqdn()
    m = nachricht(quelle, betreff, text, k, fqdn, unterdrueckt)
    r = _lauf([SENDMAIL, "-oi", "-f", _absender_adresse(k, fqdn), "--"] + k["empfaenger"],
              timeout=60, eingabe=m.as_string())
    ok = r.returncode == 0
    eintrag = {"zeit": jetzt, "quelle": quelle, "betreff": _einzeilig(betreff, 160), "ok": ok,
               "fehler": "" if ok else _einzeilig(r.stderr or r.stdout, 300)}
    z["letzte"] = ((z.get("letzte") or []) + [eintrag])[-20:]
    _zustand_schreiben(z)
    m = Meldung("uebergeben", "An die Warteschlange übergeben") if ok else \
        Meldung("sendmail", "sendmail: %s" % eintrag["fehler"], fehler=eintrag["fehler"])
    return antwort(ok, m, gesendet=ok)


def test() -> dict:
    k = konf()
    sp = k["sprache"]
    liste = ", ".join(quelle_name(q, sp) for q in k["quellen"]) or text("mvm.keine", "keine", sp)
    relay = k["relay"] or text("mvm.relay_keiner", "keiner (direkte Zustellung)", sp)
    return senden("test", text("mvm.test_betreff", "Testnachricht", sp),
                  "\n".join([text("mvm.test_text", "Diese Testnachricht bestätigt, dass der Server Meldungen "
                                   "per E-Mail verschicken kann.", sp), "",
                             text("mvm.test_quellen", "Eingeschaltete Meldungsarten: {liste}", sp, liste=liste),
                             text("mvm.test_relay", "Weiterleitender Mailserver: {relay}", sp, relay=relay)]))


# ── Sicherheitsmeldungen vom Dienst (Broker-Op broker.mail_melden) ──────────

SICHERHEIT_ARTEN = {
    "konto_gesperrt_angriff": "Konto gesperrt: Angriffsversuch erkannt",
    "konto_gesperrt_verstoss": "Konto gesperrt: wiederholte Richtlinien-Verstöße",
    "konto_gesperrt_anmeldung": "Konto gesperrt: zu viele Fehlanmeldungen",
    "spruehangriff": "Sprühangriff auf Anmeldungen erkannt",
    "angriff_protokolliert": "Angriffsversuch erkannt (nur protokolliert)",
}


def sicherheit(args: dict) -> dict:
    """Text aus WENIGEN, gekuerzten Feldern bauen – nie Inhalte (kein Prompt,
    kein Befehl): die Meldung verlaesst den Server."""
    art = str(args.get("art", ""))
    if art not in SICHERHEIT_ARTEN:
        return antwort(False, Meldung("art_unbekannt", "Unbekannte Art", wert=art), gesendet=False)
    sp = konf()["sprache"]
    felder = [("Benutzer", "benutzer"), ("Kanal", "kanal"), ("Erkennung", "muster"),
              ("Quelladresse", "ip"), ("Anzahl", "anzahl"), ("Betroffene Konten", "konten")]
    titel = text("mvm.s_" + art, SICHERHEIT_ARTEN[art], sp)
    zeilen = [titel, ""]
    for name, f in felder:
        w = _einzeilig(args.get(f, ""), 120)
        if not w:
            continue
        # Bekannte Kanaele sind Kennungen (z. B. "anmeldung") und werden
        # uebersetzt; unbekannte (Namen aus dem Dienst) bleiben wie sie sind.
        if f == "kanal" and re.match(r"^[a-z_]{2,30}$", w):
            w = text("mvm.kanal_" + w, w, sp)
        zeilen.append("%s: %s" % (text("mvm.f_" + f, name, sp), w))
    zeilen += ["", text("mvm.s_einzelheiten", "Einzelheiten: Einstellungen → Sicherheit (Vorfälle, "
                        "Sicherheitsprotokoll).", sp)]
    betreff = titel
    if _einzeilig(args.get("benutzer", ""), 60):
        betreff += " (%s)" % _einzeilig(args.get("benutzer"), 60)
    return senden("sicherheit", betreff, "\n".join(zeilen))


# ── Aufruf von der Konsole ───────────────────────────────────────────────────

def main(argv: list[str]) -> int:
    a = argv[1:]
    if a == ["--status"]:
        print(json.dumps(status(), ensure_ascii=False, indent=1))
        return 0
    if os.geteuid() != 0 and not W:
        print("mail_meldung.py: nur als root", file=sys.stderr)
        return 2
    if a in (["--einrichten"], ["--anwenden"], ["--test"]):
        erg = {"--einrichten": einrichten, "--anwenden": anwenden, "--test": test}[a[0]]()
    elif len(a) == 3 and a[0] == "--senden":
        erg = senden(a[1], a[2], sys.stdin.read())
    else:
        print(__doc__.split("Aufruf (root):", 1)[1], file=sys.stderr)
        return 2
    print(json.dumps(erg, ensure_ascii=False, indent=1))
    return 0 if erg.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
