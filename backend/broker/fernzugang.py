"""Fernzugang (SSH) aus der Oberflaeche – BSI M7 per Klick statt nur per Konsole.

Die REGELN stehen nicht hier, sondern in den Skripten, die auch die Konsole
benutzt – eine zweite Fassung liefe auseinander:

* ``deploy/security/ssh_haertung.sh``  – Drop-in, Aussperr-Schutz, Rueckfall-Timer
* ``deploy/security/firewall.sh``      – SSH_NETZE, Rueckfall auf den letzten
                                         bestaetigten Wert

Dieses Modul ruft sie aus der ROOT-EIGENEN Kopie (``CODE_ROOT``, Befund K1) und
liefert den Zustand als JSON. Jede Aenderung laeuft in ZWEI Schritten:

    test  -> Aenderung wirkt sofort, ein Timer nimmt sie nach FRIST_S zurueck
    bestaetigen -> Timer weg, Aenderung bleibt

Warum: die Web-Sitzung sagt NICHTS darueber, ob ein neues SSH-Login noch geht.
Bestaetigen soll man erst, nachdem man sich in einem neuen Terminal per SSH
angemeldet hat. Vergisst man es oder sperrt sich aus, kommt der alte Stand von
selbst zurueck.

Freigabe-Code: ``test``, ``bestaetigen`` und ``aus`` brauchen ihn (meta.py) –
ohne ihn koennte ein eingeschleuster Prozess des Dienstbenutzers den Betreiber
aussperren oder die Kennwort-Anmeldung wieder einschalten. ``verwerfen`` (nur
waehrend eines Tests) braucht ihn nicht: es stellt den bestaetigten Stand her,
genau das, was der Timer ohnehin taete.

Schluessel HINTERLEGEN und ENTFERNEN (``schluessel``): bis 2026-10-20 bewusst
nicht moeglich (Entscheidung 2026-10-06: wer im Web Admin ist und den Code
kennt, haette einen neuen Weg zu root per SSH). Auf Betreiberentscheid
2026-10-20 aufgehoben, damit niemand mehr ``ssh-copy-id``/``chmod`` von Hand
braucht – mit diesen Schranken:

* immer mit Freigabe-Code (meta.py), jeder Vorgang mit Fingerabdruck im Audit;
* nur fuer die Konten, die ``--konten`` liefert (root + sudo/wheel mit
  Login-Shell) – kein beliebiges Konto, kein Pfad aus der Anfrage;
* genau EIN oeffentlicher Schluessel, nur die Typen aus ``_TYPEN``, RSA erst ab
  3072 Bit; die Zeile wird NEU zusammengesetzt (Typ, Daten, Kommentar), damit
  keine Optionen (``command=``, ``from=`` …) aus der Eingabe in die Datei kommen;
* ``ssh-keygen -lf`` muss den Schluessel annehmen (wirft auch einen privaten ab);
* geschrieben wird ueber Verzeichnis-Deskriptoren mit ``O_NOFOLLOW`` – ein
  Symlink an ``~/.ssh`` oder ``authorized_keys`` laesst root nicht woanders
  hinschreiben; Rechte 700/600 und Eigentuemer setzt der Broker;
* Entfernen beachtet den Aussperr-Schutz, solange die Haertung an ist oder
  getestet wird.

Nur Standardbibliothek (System-Python des Brokers).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

from backend.broker import CODE_ROOT

SKRIPTE = CODE_ROOT / "deploy" / "security"
BROKER_CONF = Path(os.environ.get("JARVIS_BROKER_CONF", "/etc/jarvis/broker.conf"))
RUECKFALL_NETZE = Path(os.environ.get("JARVIS_FW_RUECKFALL", "/etc/jarvis/ssh-netze.rueckfall"))
# Fristende je Test (nur zur Anzeige; massgeblich ist der systemd-Timer)
FRIST_DATEI = Path(os.environ.get("JARVIS_SSH_FRIST", "/run/jarvis-ssh-frist.json"))
FRIST_S = 300
TIMER = {"haertung": "ssh-rollback.timer", "netze": "fw-ssh-rueckfall.timer"}

# sshd -T: was die Oberflaeche zeigt
_SSHD_FELDER = ("passwordauthentication", "kbdinteractiveauthentication",
                "permitrootlogin", "permitemptypasswords", "pubkeyauthentication")
_ROOT_MODI = {"nein": "no", "schluessel": "prohibit-password"}


def _lauf(befehl: list[str], timeout: int = 60) -> subprocess.CompletedProcess:
    umg = dict(os.environ, LC_ALL="C", LANG="C", JARVIS_BROKER_CONF=str(BROKER_CONF))
    return subprocess.run(befehl, capture_output=True, text=True, timeout=timeout, env=umg)


def _konf() -> dict[str, str]:
    """broker.conf lesen – letzte Zeile gewinnt, wie in den Skripten."""
    werte: dict[str, str] = {}
    try:
        for z in BROKER_CONF.read_text(encoding="utf-8").splitlines():
            m = re.match(r"\s*([A-Z_][A-Z0-9_]*)\s*=\s*(.*)$", z)
            if m:
                werte[m.group(1)] = m.group(2).strip().strip("'\"")
    except OSError:
        pass
    return werte


def _konf_setzen(schluessel: str, wert: str) -> None:
    """Eine Zeile ersetzen oder anhaengen; Eigentuemer/Rechte bleiben."""
    try:
        zeilen = BROKER_CONF.read_text(encoding="utf-8").splitlines()
    except OSError:
        zeilen = []
    neu = f"{schluessel}={wert}"
    treffer = False
    for i, z in enumerate(zeilen):
        if re.match(rf"\s*{schluessel}\s*=", z):
            zeilen[i] = neu
            treffer = True
    if not treffer:
        zeilen.append(neu)
    BROKER_CONF.parent.mkdir(parents=True, exist_ok=True)
    BROKER_CONF.write_text("\n".join(zeilen) + "\n", encoding="utf-8")


def _konf_entfernen(schluessel: str) -> None:
    """Alle Zeilen ``schluessel=…`` entfernen (Gegenstueck zu _konf_setzen)."""
    try:
        zeilen = BROKER_CONF.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    rest = [z for z in zeilen if not re.match(rf"\s*{schluessel}\s*=", z)]
    if rest != zeilen:
        BROKER_CONF.write_text("\n".join(rest) + ("\n" if rest else ""), encoding="utf-8")


def _timer_aktiv(name: str) -> bool:
    try:
        return _lauf(["systemctl", "is-active", "--quiet", name], timeout=10).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _fristen() -> dict:
    try:
        return json.loads(FRIST_DATEI.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def _frist_setzen(art: str, bis: float | None) -> None:
    d = _fristen()
    if bis is None:
        d.pop(art, None)
    else:
        d[art] = bis
    try:
        FRIST_DATEI.parent.mkdir(parents=True, exist_ok=True)
        FRIST_DATEI.write_text(json.dumps(d), encoding="utf-8")
    except OSError:
        pass


def _sshd() -> dict[str, str]:
    try:
        r = _lauf(["sshd", "-T"], timeout=15)
    except Exception:  # noqa: BLE001
        return {}
    erg = {}
    for z in r.stdout.splitlines():
        teile = z.split(None, 1)
        if len(teile) == 2 and teile[0] in _SSHD_FELDER:
            erg[teile[0]] = teile[1].strip()
    return erg


def _konten(root_modus: str) -> list[dict]:
    """Konten, die root werden koennen, mit Schluessel-Fingerabdruecken.

    ``zaehlt``: zaehlt dieses Konto fuer den Aussperr-Schutz – root nur bei
    SSH_ROOT=schluessel (sonst darf root sich nach der Umstellung gar nicht
    anmelden), und nur mit mindestens einem Schluessel."""
    try:
        r = _lauf(["bash", str(SKRIPTE / "ssh_haertung.sh"), "--konten"], timeout=30)
    except Exception:  # noqa: BLE001
        return []
    konten: dict[str, dict] = {}
    for z in r.stdout.splitlines():
        teile = z.split()
        if len(teile) >= 4 and teile[0] == "KONTO":
            try:
                anzahl = int(teile[3])
            except ValueError:
                anzahl = 0
            konten[teile[1]] = {"name": teile[1], "art": teile[2], "anzahl": anzahl,
                                "schluessel": []}
        elif len(teile) >= 3 and teile[0] == "FP" and teile[1] in konten:
            # "<bits> <SHA256:…> <kommentar> (<typ>)"
            rest = z.split(None, 2)[2]
            m = re.match(r"(\d+)\s+(\S+)\s+(.*?)\s*\((\w+)\)\s*$", rest)
            if m:
                konten[teile[1]]["schluessel"].append(
                    {"bits": int(m.group(1)), "fingerabdruck": m.group(2),
                     "kommentar": m.group(3), "typ": m.group(4)})
    for k in konten.values():
        k["zaehlt"] = k["anzahl"] > 0 and (k["art"] != "root" or root_modus == "schluessel")
    return list(konten.values())


_ANMELDUNG = re.compile(r"^(\S+)\s.*Accepted (\S+) for (\S+) from (\S+) port \d+")


def _vorschlaege() -> dict:
    """Bausteine fuer den Maus-Helfer "Erlaubte Netze" (nur Anzeige, keine Regel).

    * ``lokal``     – Netze der Schnittstellen dieses Servers (ohne Loopback,
                      Link-local und Einzeladressen wie die eigene Tailnet-IP)
    * ``tailscale`` – ob ein Tailscale-Adapter da ist (dann 100.64.0.0/10)
    * ``anmeldungen`` – Quelladressen ERFOLGREICHER SSH-Anmeldungen der letzten
      30 Tage: wer sich bisher angemeldet hat, muss es nach der Einschraenkung
      meist weiter koennen. Gezaehlt, juengste zuerst, hoechstens 15.
    """
    import ipaddress
    lokal, tailscale = [], False
    try:
        r = _lauf(["ip", "-o", "addr", "show"], timeout=10)
        for z in r.stdout.splitlines():
            t = z.split()
            if len(t) < 4 or t[2] not in ("inet", "inet6"):
                continue
            name = t[1].rstrip(":")
            if name.startswith("tailscale"):
                tailscale = True
                continue
            try:
                netz = ipaddress.ip_interface(t[3]).network
            except ValueError:
                continue
            if netz.is_loopback or netz.is_link_local or netz.prefixlen == netz.max_prefixlen:
                continue
            eintrag = {"netz": str(netz), "schnittstelle": name}
            if eintrag not in lokal:
                lokal.append(eintrag)
    except Exception:  # noqa: BLE001
        pass
    je_ip: dict[str, dict] = {}
    try:
        r = _lauf(["journalctl", "-u", "ssh", "-u", "sshd", "--since", "-30d",
                   "--no-pager", "-o", "short-iso"], timeout=30)
        for z in r.stdout.splitlines():
            m = _ANMELDUNG.search(z)
            if not m:
                continue
            try:
                ip = str(ipaddress.ip_address(m.group(4)))
            except ValueError:
                continue
            e = je_ip.setdefault(ip, {"ip": ip, "anzahl": 0, "zuletzt": "", "konten": []})
            e["anzahl"] += 1
            e["zuletzt"] = max(e["zuletzt"], m.group(1))
            if m.group(3) not in e["konten"]:
                e["konten"].append(m.group(3))
    except Exception:  # noqa: BLE001
        pass
    anmeldungen = sorted(je_ip.values(), key=lambda e: e["zuletzt"], reverse=True)[:15]
    return {"lokal": lokal, "tailscale": tailscale, "anmeldungen": anmeldungen}


# ── SSH-Protokoll (Ansicht unter Einstellungen -> Protokolle) ────────────────
# Gemessen an echten Zeilen (DEV, 2026-10-20): Debian 13 schreibt ueber
# ``sshd-session[pid]`` statt ``sshd[pid]`` – die Muster haengen deshalb NICHT
# am Prozessnamen. Am Ende einer Schluessel-Anmeldung steht der Fingerabdruck
# ("ssh2: RSA SHA256:…") – er sagt, WELCHER Schluessel benutzt wurde.
_SSH_ANGENOMMEN = re.compile(
    r"^(\S+)\s.*?: Accepted (\S+) for (\S+) from (\S+) port \d+\S*(?: ssh2: (\S+) (\S+))?")
_SSH_FEHLGESCHLAGEN = re.compile(
    r"^(\S+)\s.*?: Failed (\S+) for (?:invalid user )?(\S+) from (\S+) port \d+")
_SSH_UNBEKANNT = re.compile(r"^(\S+)\s.*?: Invalid user (\S*) from (\S+) port \d+")
SSH_TAGE_MAX = 30
SSH_EINTRAEGE_MAX = 1000
SSH_ARTEN = ("angenommen", "fehlgeschlagen", "unbekannt")


def ssh_zerlegen(text: str) -> list[dict]:
    """journalctl-Ausgabe (short-iso) -> Ereignisse, in Reihenfolge der Zeilen.

    Eigene Funktion ohne Systemaufruf, damit sie ohne Root und ohne Journal
    pruefbar ist. Unbekannte Zeilen werden uebergangen, nicht geraten."""
    aus = []
    for z in (text or "").splitlines():
        m = _SSH_ANGENOMMEN.search(z)
        if m:
            aus.append({"zeit": m.group(1), "art": "angenommen", "methode": m.group(2),
                        "konto": m.group(3), "ip": m.group(4),
                        "schluessel": ((m.group(5) or "") + " " + (m.group(6) or "")).strip()})
            continue
        m = _SSH_FEHLGESCHLAGEN.search(z)
        if m:
            aus.append({"zeit": m.group(1), "art": "fehlgeschlagen", "methode": m.group(2),
                        "konto": m.group(3), "ip": m.group(4), "schluessel": ""})
            continue
        m = _SSH_UNBEKANNT.search(z)
        if m:
            aus.append({"zeit": m.group(1), "art": "unbekannt", "methode": "",
                        "konto": m.group(2), "ip": m.group(3), "schluessel": ""})
    return aus


def ssh_protokoll(tage=7, art: str = "") -> dict:
    """SSH-Anmeldungen der letzten ``tage`` Tage, JUENGSTE zuerst (nur lesen).

    Gefiltert wird HIER und nicht in der Oberflaeche: auf DEV standen in 30
    Tagen 5146 erfolgreiche Anmeldungen neben 6 Fehlschlaegen – mit Deckel und
    Filter dahinter waeren die Fehlschlaege unter den Erfolgen verschwunden.
    ``anzahl`` zaehlt je Art ueber den GANZEN Zeitraum, vor dem Deckel."""
    try:
        tage = max(1, min(int(tage), SSH_TAGE_MAX))
    except (TypeError, ValueError):
        tage = 7
    art = art if art in SSH_ARTEN else ""
    try:
        r = _lauf(["journalctl", "-u", "ssh", "-u", "sshd", "--since", "-%dd" % tage,
                   "--no-pager", "-o", "short-iso"], timeout=60)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": "journalctl: %s" % e}
    alle = ssh_zerlegen(r.stdout)
    anzahl = {a: sum(1 for e in alle if e["art"] == a) for a in SSH_ARTEN}
    treffer = [e for e in alle if not art or e["art"] == art]
    treffer.reverse()
    return {"ok": True, "tage": tage, "art": art, "anzahl": anzahl,
            "gekappt": max(0, len(treffer) - SSH_EINTRAEGE_MAX),
            "eintraege": treffer[:SSH_EINTRAEGE_MAX]}


def status() -> dict:
    konf = _konf()
    root_modus = "schluessel" if konf.get("SSH_ROOT") == "schluessel" else "nein"
    konten = _konten(root_modus)
    jetzt = time.time()
    fristen = _fristen()
    tests = {}
    for art, timer in TIMER.items():
        laeuft = _timer_aktiv(timer)
        if art == "netze":
            laeuft = laeuft or RUECKFALL_NETZE.is_file()
        bis = fristen.get(art) if laeuft else None
        tests[art] = {"laeuft": laeuft,
                      "rest_s": max(0, int(bis - jetzt)) if bis else None}
    try:
        fw_ok = _lauf(["bash", str(SKRIPTE / "firewall.sh"), "--eingerichtet"],
                      timeout=20).returncode == 0
    except Exception:  # noqa: BLE001
        fw_ok = False
    return {
        "ok": True,
        "sshd": _sshd(),
        "haertung": konf.get("SSH_HAERTUNG", ""),
        "root_modus": root_modus,
        "netze": konf.get("SSH_NETZE", ""),
        "konten": konten,
        "zugang_moeglich": {m: any(k["anzahl"] > 0 and (k["art"] != "root" or m == "schluessel")
                                   for k in konten) for m in _ROOT_MODI},
        "test": tests,
        "firewall_eingerichtet": fw_ok,
        "frist_s": FRIST_S,
        "vorschlaege": _vorschlaege(),
    }


def _antwort(r: subprocess.CompletedProcess) -> dict:
    """Skript-Ergebnis fuer Oberflaeche + Audit: die letzte aussagekraeftige Zeile."""
    text = "\n".join(x for x in (r.stdout.strip(), r.stderr.strip()) if x)
    zeilen = [z for z in text.splitlines() if z.strip()]
    meldung = next((z for z in reversed(zeilen) if "ABBRUCH" in z or "ungueltig" in z),
                   zeilen[-1] if zeilen else "")
    return {"ok": r.returncode == 0, "rc": r.returncode, "meldung": meldung[:400],
            "ausgabe": text[-2000:]}


def haertung(aktion: str, root_modus: str = "") -> dict:
    """aktion: test | bestaetigen | verwerfen | aus."""
    skript = ["bash", str(SKRIPTE / "ssh_haertung.sh")]
    laeuft = _timer_aktiv(TIMER["haertung"])
    if aktion == "test":
        if root_modus not in _ROOT_MODI:
            return {"ok": False, "meldung": "root_modus muss nein oder schluessel sein"}
        # Das Skript liest SSH_ROOT aus broker.conf – der Wert muss VOR dem
        # Test stehen. Scheitert der Test (Exit 6 "Haertung bereits aktiv",
        # Exit 3 Aussperr-Schutz, Abbruch), kommt der ALTE Wert zurueck: sonst
        # schrieb der naechste Broker-Start per --erneuern den gelockerten Wert
        # in die sshd-Konfiguration – ohne Test, ohne Bestaetigung
        # (Code-Review 2026-10-07).
        vorher = _konf().get("SSH_ROOT")
        _konf_setzen("SSH_ROOT", root_modus)
        r = None
        try:
            r = _lauf(skript + ["--test", str(FRIST_S)])
        finally:
            if r is None or r.returncode != 0:
                if vorher is None:
                    _konf_entfernen("SSH_ROOT")
                else:
                    _konf_setzen("SSH_ROOT", vorher)
        if r.returncode == 0:
            _frist_setzen("haertung", time.time() + FRIST_S)
        return _antwort(r)
    if aktion == "bestaetigen":
        if not laeuft:
            return {"ok": False, "meldung": "Kein laufender Test – die Frist ist abgelaufen "
                                            "oder er wurde verworfen."}
        r = _lauf(skript + ["--anwenden"])
        if r.returncode == 0:
            # Das Skript stoppt den Timer selbst; hier ein zweites Mal, weil ein
            # nach der Bestaetigung feuernder Rueckfall die Haertung STILL entfernte
            _lauf(["systemctl", "stop", TIMER["haertung"]], timeout=15)
            _frist_setzen("haertung", None)
        return _antwort(r)
    if aktion == "verwerfen":
        # Nur ein UNBESTAETIGTER Test – sonst waere "verwerfen" (ohne Code) ein
        # Weg, eine bestaetigte Haertung abzuschalten
        if not laeuft or _konf().get("SSH_HAERTUNG") == "an":
            return {"ok": False, "meldung": "Kein laufender Test."}
        r = _lauf(skript + ["--aus"])
        _frist_setzen("haertung", None)
        return _antwort(r)
    if aktion == "aus":
        r = _lauf(skript + ["--aus"])
        _frist_setzen("haertung", None)
        return _antwort(r)
    return {"ok": False, "meldung": f"Unbekannte Aktion: {aktion}"}


_NETZ_ZEICHEN = re.compile(r"^[0-9A-Fa-f.:/,\s]*$")


def netze(aktion: str, liste: str = "") -> dict:
    """aktion: test | bestaetigen | verwerfen. ``liste`` leer = SSH aus allen Netzen."""
    skript = ["bash", str(SKRIPTE / "firewall.sh")]
    laeuft = RUECKFALL_NETZE.is_file()
    if aktion == "test":
        liste = str(liste or "")[:2000]
        # Vorpruefung nur der ZEICHEN – die Bedeutung prueft das Skript (ipaddress)
        if not _NETZ_ZEICHEN.match(liste):
            return {"ok": False, "meldung": "Nur IP-Adressen und Netze (z. B. 192.0.2.0/24) erlaubt."}
        r = _lauf(skript + ["--ssh-netze-test", liste, str(FRIST_S)], timeout=120)
        if r.returncode == 0:
            _frist_setzen("netze", time.time() + FRIST_S)
        return _antwort(r)
    if aktion == "bestaetigen":
        if not laeuft:
            return {"ok": False, "meldung": "Kein laufender Test – die Frist ist abgelaufen "
                                            "oder er wurde verworfen."}
        r = _lauf(skript + ["--ssh-netze-bestaetigen"], timeout=120)
        if r.returncode == 0:
            _frist_setzen("netze", None)
        return _antwort(r)
    if aktion == "verwerfen":
        if not laeuft:
            return {"ok": False, "meldung": "Kein laufender Test."}
        r = _lauf(skript + ["--rueckfall"], timeout=120)
        _frist_setzen("netze", None)
        return _antwort(r)
    return {"ok": False, "meldung": f"Unbekannte Aktion: {aktion}"}


# ── Schluessel hinterlegen / entfernen ───────────────────────────────────────
PASSWD_DATEI = Path(os.environ.get("JARVIS_PASSWD", "/etc/passwd"))
_TYPEN = {
    "ssh-ed25519", "sk-ssh-ed25519@openssh.com",
    "ecdsa-sha2-nistp256", "ecdsa-sha2-nistp384", "ecdsa-sha2-nistp521",
    "sk-ecdsa-sha2-nistp256@openssh.com", "ssh-rsa",
}
RSA_MIN_BITS = 3072
_SCHLUESSEL_DATEIEN = ("authorized_keys", "authorized_keys2")
_ZEILE = re.compile(r"^(\S+)\s+([A-Za-z0-9+/]+={0,3})(?:\s+(.*))?$")
_FP = re.compile(r"^SHA256:[A-Za-z0-9+/]{43}$")


def _passwd_eintrag(name: str) -> tuple[int, int, str] | None:
    """(uid, gid, home) aus derselben passwd-Datei wie ssh_haertung.sh."""
    try:
        for z in PASSWD_DATEI.read_text(encoding="utf-8").splitlines():
            t = z.split(":")
            if len(t) >= 7 and t[0] == name:
                return int(t[2]), int(t[3]), t[5]
    except (OSError, ValueError):
        pass
    return None


def _fingerabdruck(zeile: str) -> tuple[int, str, str] | None:
    """(bits, SHA256:…, TYP) laut ``ssh-keygen -lf -`` – None, wenn abgelehnt."""
    try:
        r = subprocess.run(["ssh-keygen", "-lf", "-"], input=zeile + "\n", capture_output=True,
                           text=True, timeout=10, env=dict(os.environ, LC_ALL="C", LANG="C"))
    except Exception:  # noqa: BLE001
        return None
    zeilen = r.stdout.strip().splitlines()
    if r.returncode != 0 or len(zeilen) != 1:
        return None
    m = re.match(r"(\d+)\s+(\S+)\s+.*\((\w+)\)\s*$", zeilen[0])
    return (int(m.group(1)), m.group(2), m.group(3)) if m else None


def _schluessel_pruefen(text: str) -> tuple[dict | None, str]:
    """Eingabe -> ({typ, daten, kommentar, bits, fingerabdruck}, "") oder (None, Grund)."""
    import base64
    roh = str(text or "").strip()
    if not roh:
        return None, "Kein Schlüssel angegeben."
    if "PRIVATE KEY" in roh:
        return None, ("Das ist ein PRIVATER Schlüssel. Er bleibt auf deinem Rechner – "
                      "hier gehört nur der Inhalt der Datei mit der Endung .pub hinein.")
    if len(roh) > 16384 or "\n" in roh or "\r" in roh:
        return None, "Bitte genau einen öffentlichen Schlüssel (eine Zeile) angeben."
    m = _ZEILE.match(roh)
    if not m or m.group(1) not in _TYPEN:
        return None, ("Kein unterstützter öffentlicher Schlüssel. Erwartet wird eine Zeile wie "
                      "„ssh-ed25519 AAAA… name@rechner“ (ed25519, ecdsa oder rsa).")
    typ, daten, kommentar = m.group(1), m.group(2), (m.group(3) or "").strip()
    try:
        blob = base64.b64decode(daten, validate=True)
        laenge = int.from_bytes(blob[:4], "big")
        innen = blob[4:4 + laenge].decode("ascii")
    except Exception:  # noqa: BLE001
        return None, "Der Schlüssel ist beschädigt (Daten nicht lesbar)."
    if innen != typ:
        return None, "Der Schlüssel ist beschädigt (Typangabe passt nicht zu den Daten)."
    # Kommentar: nur druckbare Zeichen, gekuerzt – er landet in einer Datei, die sshd liest
    kommentar = "".join(c for c in kommentar if c.isprintable())[:200].strip()
    fp = _fingerabdruck(f"{typ} {daten}")
    if fp is None:
        return None, "ssh-keygen lehnt den Schlüssel ab."
    bits, abdruck, ktyp = fp
    if typ == "ssh-rsa" and bits < RSA_MIN_BITS:
        return None, (f"RSA-Schlüssel mit {bits} Bit ist zu schwach (mindestens {RSA_MIN_BITS}). "
                      "Besser: ssh-keygen -t ed25519")
    return {"typ": typ, "daten": daten, "kommentar": kommentar, "bits": bits,
            "fingerabdruck": abdruck, "ktyp": ktyp}, ""


def _ssh_verzeichnis(home: str, uid: int, gid: int, anlegen: bool) -> int | None:
    """Deskriptor auf ``<home>/.ssh`` – nie ueber einen Symlink. None = gibt es nicht."""
    if not home.startswith("/"):
        raise OSError("Heimatverzeichnis ist kein absoluter Pfad")
    hfd = os.open(home, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        try:
            return os.open(".ssh", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=hfd)
        except FileNotFoundError:
            if not anlegen:
                return None
        # 0700 beim Anlegen; die umask kann Rechte nur wegnehmen, nie erweitern
        os.mkdir(".ssh", 0o700, dir_fd=hfd)
        sfd = os.open(".ssh", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=hfd)
        if os.geteuid() == 0:
            os.fchown(sfd, uid, gid)
        return sfd
    finally:
        os.close(hfd)


def _lesen(sfd: int, name: str) -> str | None:
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=sfd)
    except FileNotFoundError:
        return None
    with os.fdopen(fd, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _schreiben(sfd: int, name: str, inhalt: str, uid: int, gid: int) -> None:
    """Atomar ersetzen: Hilfsdatei im selben Verzeichnis, Rechte 600, dann rename.

    Die Hilfsdatei entsteht immer NEU (O_EXCL) mit 0600 – kein fchmod noetig.
    """
    tmp = f".{name}.jarvis-{os.getpid()}"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=sfd)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(inhalt)
            f.flush()
            if os.geteuid() == 0:
                os.fchown(f.fileno(), uid, gid)
            os.fsync(f.fileno())
        os.replace(tmp, name, src_dir_fd=sfd, dst_dir_fd=sfd)
    except BaseException:
        try:
            os.unlink(tmp, dir_fd=sfd)
        except OSError:
            pass
        raise


def _zeilen_fp(inhalt: str) -> list[tuple[str, str | None]]:
    """Jede Zeile mit ihrem Fingerabdruck (None fuer Kommentar/Leerzeile/Unlesbares)."""
    erg = []
    for z in inhalt.splitlines():
        if not z.strip() or z.lstrip().startswith("#"):
            erg.append((z, None))
            continue
        fp = _fingerabdruck(z)
        erg.append((z, fp[1] if fp else None))
    return erg


def schluessel(aktion: str, konto: str, text: str = "", fingerabdruck: str = "") -> dict:
    """aktion: hinzufuegen (``text`` = oeffentlicher Schluessel) | entfernen (``fingerabdruck``)."""
    konf = _konf()
    root_modus = "schluessel" if konf.get("SSH_ROOT") == "schluessel" else "nein"
    konten = _konten(root_modus)
    ziel = next((k for k in konten if k["name"] == konto), None)
    if ziel is None:
        return {"ok": False, "meldung": "Unbekanntes Konto – Schlüssel lassen sich nur für die "
                                        "angezeigten Administrator-Konten hinterlegen."}
    pw = _passwd_eintrag(konto)
    if pw is None:
        return {"ok": False, "meldung": "Konto nicht in der Benutzerliste gefunden."}
    uid, gid, home = pw

    if aktion == "hinzufuegen":
        k, grund = _schluessel_pruefen(text)
        if k is None:
            return {"ok": False, "meldung": grund}
        if any(s["fingerabdruck"] == k["fingerabdruck"] for s in ziel["schluessel"]):
            return {"ok": True, "neu": False, "fingerabdruck": k["fingerabdruck"],
                    "meldung": f"Dieser Schlüssel ist für {konto} bereits hinterlegt."}
        zeile = f"{k['typ']} {k['daten']}" + (f" {k['kommentar']}" if k["kommentar"] else "")
        try:
            sfd = _ssh_verzeichnis(home, uid, gid, anlegen=True)
            try:
                alt = _lesen(sfd, "authorized_keys") or ""
                if alt and not alt.endswith("\n"):
                    alt += "\n"
                _schreiben(sfd, "authorized_keys", alt + zeile + "\n", uid, gid)
            finally:
                os.close(sfd)
        except OSError as e:
            return {"ok": False, "meldung": f"Schreiben fehlgeschlagen: {e.strerror or e}"}
        return {"ok": True, "neu": True, "fingerabdruck": k["fingerabdruck"],
                "meldung": f"Schlüssel {k['fingerabdruck']} ({k['ktyp']}) für {konto} hinterlegt."}

    if aktion == "entfernen":
        fingerabdruck = str(fingerabdruck or "").strip()
        if not _FP.match(fingerabdruck):
            return {"ok": False, "meldung": "Ungültiger Fingerabdruck."}
        if not any(s["fingerabdruck"] == fingerabdruck for s in ziel["schluessel"]):
            return {"ok": False, "meldung": f"Schlüssel ist für {konto} nicht hinterlegt."}
        try:
            sfd = _ssh_verzeichnis(home, uid, gid, anlegen=False)
            if sfd is None:
                return {"ok": False, "meldung": f"Schlüssel ist für {konto} nicht hinterlegt."}
            try:
                neu, weg = {}, 0
                for name in _SCHLUESSEL_DATEIEN:
                    inhalt = _lesen(sfd, name)
                    if inhalt is None:
                        continue
                    zeilen = _zeilen_fp(inhalt)
                    bleibt = [z for z, fp in zeilen if fp != fingerabdruck]
                    if len(bleibt) != len(zeilen):
                        weg += len(zeilen) - len(bleibt)
                        neu[name] = "\n".join(bleibt) + ("\n" if bleibt else "")
                if not weg:
                    return {"ok": False, "meldung": f"Schlüssel ist für {konto} nicht hinterlegt."}
                # Aussperr-Schutz wie ssh_haertung.sh: solange die Haertung an ist
                # (oder getestet wird), muss danach noch jemand mit Schluessel
                # hereinkommen, der root werden kann
                if konf.get("SSH_HAERTUNG") == "an" or _timer_aktiv(TIMER["haertung"]):
                    rest = ziel["anzahl"] - weg
                    zugang = any((k["anzahl"] if k is not ziel else rest) > 0
                                 and (k["art"] != "root" or root_modus == "schluessel")
                                 for k in konten)
                    if not zugang:
                        return {"ok": False, "meldung": (
                            "ABBRUCH: Danach könnte sich niemand mehr per SSH anmelden und "
                            "Administrator werden (Kennwort-Anmeldung ist abgeschaltet). "
                            "Erst einen anderen Schlüssel hinterlegen.")}
                for name, inhalt in neu.items():
                    _schreiben(sfd, name, inhalt, uid, gid)
            finally:
                os.close(sfd)
        except OSError as e:
            return {"ok": False, "meldung": f"Schreiben fehlgeschlagen: {e.strerror or e}"}
        return {"ok": True, "fingerabdruck": fingerabdruck,
                "meldung": f"Schlüssel {fingerabdruck} für {konto} entfernt."}

    return {"ok": False, "meldung": f"Unbekannte Aktion: {aktion}"}
