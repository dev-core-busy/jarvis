#!/usr/bin/env python3
"""Gegenprobe zu test_mail_tls.py, test_gedaechtnis_sperre.py, test_email_ui.js:
beissen die Waechter der BSI-Punkte aus Abschnitt 5 (Skills email + memory)?

Jede Probe dreht EINEN Teil der Massnahme zurueck (Python-Ersetzung ganzer
Zeilen), laesst die Waechter laufen und erwartet mindestens einen FAIL. Ein
Waechter, der dabei nicht laufen kann (Exit 2, keine Bilanz), zaehlt NICHT als
Biss. Vorher gruener Basislauf, danach Byte-Gleichheit per md5, ohne Bytecode,
mit Laufmarke (ein abgeschossener Lauf wird beim naechsten Start zurueckgenommen).

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MARKE = ROOT / "tests" / ".gegen_bsi_skills_hoch.laufmarke"

MT = "backend/mail_tls.py"
MC = "backend/mail_client.py"
SSO = "backend/addin_sso.py"
EJ = "frontend/js/email.js"
ME = "backend/tools/memory.py"
AG = "backend/agent.py"

PROBEN = [
    # ── E-Mail-TLS ──
    ("ohne Anker: ungepruefter Kontext", MT,
     "        return ctx\n    return _system_kontext(kanal)[0]\n",
     "        return ctx\n    _c = ssl.create_default_context()\n    _c.check_hostname = False\n"
     "    _c.verify_mode = ssl.CERT_NONE\n    return _c\n"),
    ("Anker gilt ohne Host/Port-Abgleich", MT,
     "    return eintrag if sap_cert.passt(eintrag, host, port) else None\n",
     "    return eintrag if (eintrag or {}).get(\"pem\") else None\n"),
    ("Uebernahme fuer JEDES Ziel (Liste wirkungslos)", MT,
     "    if key not in list(cfg.get(UEBERNAHME_FELD) or []):\n        return None\n"
     "    with _sperre:\n        cfg = _cfg()\n        offen = list(cfg.get(UEBERNAHME_FELD) or [])\n"
     "        if key not in offen:\n            return anker(kanal, host, port, cfg)\n",
     "    with _sperre:\n        cfg = _cfg()\n        offen = list(cfg.get(UEBERNAHME_FELD) or [])\n"
     "        if key not in offen:\n            offen.append(key)\n"),
    ("Bestand: Altschalter wird nicht ausgewertet (immer vormerken)", MT,
     '            aus = _alt_aus(cfg.get("verify_ssl"))\n',
     "            aus = True\n"),
    ("Bestand: keine Marke (laeuft bei jedem Start erneut)", MT,
     "            if not cfg or cfg.get(BESTAND_FELD):\n",
     "            if not cfg:\n"),
    ("EWS-Adapter laesst Session.verify=False durch", MC,
     '                kwargs["verify"] = mail_tls.requests_verify(request.url)\n',
     '                kwargs.setdefault("verify", mail_tls.requests_verify(request.url))\n'),
    ("Add-in-SSO holt die Metadaten ungeprueft", SSO,
     "        with httpx.Client(verify=_tls_kontext(amurl), timeout=10.0) as c:\n",
     "        with httpx.Client(verify=True, timeout=10.0) as c:\n"),
    ("IMAP: STARTTLS-Fehler verschluckt (Klartext-Anmeldung)", MC,
     "                except imaplib.IMAP4.error as e:\n                    # imaplib meldet",
     "                except imaplib.IMAP4.error as e:\n                    e = None\n"
     "                if False:\n                    # imaplib meldet"),
    ("IMAP: fehlendes STARTTLS gilt als Anmeldefehler", MC,
     "                except imaplib.IMAP4.error as e:\n                    # imaplib meldet",
     "                except ZeroDivisionError as e:\n                    # imaplib meldet"),
    ("SMTP ohne Verschluesselung wieder erlaubt", MC,
     "                if not k.smtp_starttls:\n                    # Ohne Verschluesselung",
     "                if False:\n                    # Ohne Verschluesselung"),
    ("Oberflaeche sendet den Schalter wieder", EJ,
     "            auth_typ: ($('em-auth-typ') || {}).value || 'auto',\n",
     "            auth_typ: ($('em-auth-typ') || {}).value || 'auto',\n            verify_ssl: false,\n"),
    # ── Gedaechtnis ──
    ("Schreibsperre ohne Oberflaeche aus", ME,
     "        return _kanal() is None\n",
     "        return False\n"),
    ("Schreibsperre fail-open", ME,
     "    except Exception:  # noqa: BLE001\n        return True\n\n\ndef _quelle",
     "    except Exception:  # noqa: BLE001\n        return False\n\n\ndef _quelle"),
    ("Loeschen ohne Oberflaeche erlaubt", ME,
     '_SCHREIBEND = ("save", "delete")\n',
     '_SCHREIBEND = ("save",)\n'),
    ("Herkunft wird nicht gespeichert", ME,
     '                "quelle": _quelle(),\n',
     ""),
    ("headless: Gedaechtnis wieder ungerahmt", AG,
     "            # ohne Zuschauer Fremdtext verarbeiten (BSI-Abgleich, Skill memory).\n"
     "            system_prompt += gedaechtnis_block(memory_context)\n",
     "            # ohne Zuschauer Fremdtext verarbeiten (BSI-Abgleich, Skill memory).\n"
     "            system_prompt += f\"\\n\\n{memory_context}\"\n"),
    ("headless: Auto-Learning ohne Bindung an die Sperre", AG,
     "                    and not _memory_schreiben_gesperrt()):\n",
     "                    and True):\n"),
]

DATEIEN = [MT, MC, SSO, EJ, ME, AG]

WAECHTER = [
    ["python3", "tests/test_mail_tls.py"],
    ["python3", "tests/test_gedaechtnis_sperre.py"],
    ["node", "tests/test_email_ui.js"],
]
BILANZ = re.compile(r"(\d+) OK, (\d+) FAIL")


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf():
    """Alle Waechter; Summe der FAILs. -1 = einer konnte nicht laufen."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    summe = 0
    for cmd in WAECHTER:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                               cwd=str(ROOT), env=env)
        except subprocess.TimeoutExpired:
            return -1, "timeout " + cmd[-1]
        treffer = BILANZ.findall(r.stdout)
        if r.returncode == 2 or not treffer:
            return -1, "%s rc=%s %s" % (cmd[-1], r.returncode, r.stdout.strip()[-160:])
        summe += int(treffer[-1][1])
    return summe, 0


def zuruecknehmen():
    if not MARKE.exists():
        return
    try:
        alt = json.loads(MARKE.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        print("ABBRUCH: Laufmarke unlesbar – Arbeitsbaum von Hand pruefen")
        sys.exit(2)
    for d, hexinhalt in alt.items():
        (ROOT / d).write_bytes(bytes.fromhex(hexinhalt))
    MARKE.unlink()
    print("Rueckstand eines abgebrochenen Laufs zurueckgenommen.")


def main() -> int:
    zuruecknehmen()
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, %s)" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")

    MARKE.write_text(json.dumps({d: b.hex() for d, b in sicherung.items()}), encoding="utf-8")
    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu, 1), encoding="utf-8")
            try:
                fails, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-62s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-62s Waechter konnte nicht laufen (%s)" % (name, rc))
            else:
                print("  ZAHN %-62s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)
        if MARKE.exists():
            MARKE.unlink()

    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("\nABBRUCH: Dateien nach der Probe nicht byte-gleich: %s"
              % [d for d in DATEIEN if nachher[d] != vorher[d]])
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)"
          % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
