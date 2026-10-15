#!/usr/bin/env python3
"""Gegenprobe zu tests/test_bsi_m12.py: beisst der Waechter?

Jede Probe dreht EINEN Teil von M12 zurueck (Python-Ersetzung ganzer Zeilen),
laesst den Waechter laufen und erwartet mindestens einen FAIL. Vorher gruener
Basislauf, danach Byte-Gleichheit aller Dateien per md5, ohne Bytecode, mit
Laufmarke (abgeschossener Lauf wird beim naechsten Start zurueckgenommen).

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
MARKE = ROOT / "tests" / ".gegen_bsi_m12.laufmarke"

FW = "backend/file_watcher.py"
MA = "backend/main.py"
VE = "skills/vision/vision_engine.py"
KS = "backend/knowledge_sync.py"
MC = "backend/mail_client.py"

PROBEN = [
    # ── Webhook ──
    ("Webhook wieder fest verify=False", FW,
     "        async with httpx.AsyncClient(timeout=15.0, verify=bool(tls_pruefen)) as client:  # nosec B501\n",
     "        async with httpx.AsyncClient(timeout=15.0, verify=False) as client:  # nosec B501\n"),
    ("Webhook ohne Pruefung wird nicht protokolliert", FW,
     '            sicherheits_log.ereignis(\n                "tls_pruefung_aus", benutzer=w.get("owner", ""), ergebnis="webhook",\n',
     '            (lambda *a, **k: None)(\n                "tls_pruefung_aus", benutzer=w.get("owner", ""), ergebnis="webhook",\n'),
    ("add_watcher: Vorgabe Pruefung aus", FW,
     "                    webhook_tls_pruefen: bool = True) -> dict:\n",
     "                    webhook_tls_pruefen: bool = False) -> dict:\n"),
    ("add_watcher: keine Typpruefung", FW,
     "        if not isinstance(webhook_tls_pruefen, bool):\n            raise ValueError(\"webhook_tls_pruefen muss true/false sein\")\n",
     ""),
    ("update_watcher: keine Typpruefung", FW,
     '        if "webhook_tls_pruefen" in fields and not isinstance(fields["webhook_tls_pruefen"], bool):\n',
     '        if False:\n'),
    ("Feld nicht aenderbar", FW,
     '        "webhook_tls_pruefen",\n    }\n', '    }\n'),
    ("Ausloeser: fehlendes Feld = aus", FW,
     "                                                tls_pruefen=watcher.get(\"webhook_tls_pruefen\") is not False,\n",
     "                                                tls_pruefen=bool(watcher.get(\"webhook_tls_pruefen\")),\n"),
    ("Endpunkt: jede falsy Eingabe schaltet ab", MA,
     '            webhook_tls_pruefen=body.get("webhook_tls_pruefen") is not False,\n',
     '            webhook_tls_pruefen=bool(body.get("webhook_tls_pruefen", True)),\n'),
    ("Endpunkt: Einrichten nicht protokolliert", MA,
     '        if w.get("webhook_tls_pruefen") is False:\n            _sicherheits_log.ereignis("tls_pruefung_aus", benutzer=user, ergebnis="eingerichtet",\n                                      watcher=w.get("id", ""))\n        return JSONResponse(w, status_code=201)\n',
     '        return JSONResponse(w, status_code=201)\n'),
    # ── Kamera ──
    ("Kamera wieder fest CERT_NONE (alte Fassung)", VE,
     "                if not self._tls_pruefen:\n                    ctx.check_hostname = False\n                    ctx.verify_mode = ssl.CERT_NONE\n",
     "                ctx.check_hostname = False\n                ctx.verify_mode = ssl.CERT_NONE\n"),
    ("Kamera: Einstellung fehlt = aus", VE,
     '        return cfg.get("stream_tls_pruefen") is not False\n',
     '        return bool(cfg.get("stream_tls_pruefen"))\n'),
    ("Kamera: unlesbare Einstellung = aus (fail-open)", VE,
     "    except Exception:  # noqa: BLE001\n        return True\n\n\nclass MjpegStreamReader:",
     "    except Exception:  # noqa: BLE001\n        return False\n\n\nclass MjpegStreamReader:"),
    ("Kamera: Start ohne Pruefung nicht protokolliert", VE,
     "                self._tls_aus_protokollieren(source)\n", "                pass\n"),
    ("Kamera: Wiederverbinden vergisst die Einstellung", VE,
     "                        time.sleep(2)\n                        reader = MjpegStreamReader(self._source, tls_pruefen=self._tls_pruefen)\n",
     "                        time.sleep(2)\n                        reader = MjpegStreamReader(self._source)\n"),
    # ── Standort-Sync ──
    ("Sync: ohne Zertifikat wieder ungepruefter Kontext", KS,
     '        raise ValueError("Kein Zertifikat gebunden – Verbindung ohne Pruefung abgelehnt.")\n',
     '        return _ermittlungs_kontext()\n'),
    ("Verbindungstest schickt das Token ungeprueft", MA,
     "        with httpx.Client(verify=ks._ssl_kontext(zert), timeout=ks.HTTP_TIMEOUT,\n",
     "        with httpx.Client(verify=ks._ermittlungs_kontext(), timeout=ks.HTTP_TIMEOUT,\n"),
    # ── Regel: feste Abschaltung an einer bisher sauberen Stelle ──
    ("Mail: Pruefung unbedingt aus (Regel muss es sehen)", MC,
     "                c = imaplib.IMAP4_SSL(host, port,\n                                      ssl_context=mail_tls.ssl_kontext(\"imap\", host, port),\n",
     "                _ctx = ssl.create_default_context()\n                _ctx.check_hostname = False\n                _ctx.verify_mode = ssl.CERT_NONE\n                c = imaplib.IMAP4_SSL(host, port,\n                                      ssl_context=_ctx,\n"),
]

DATEIEN = [FW, MA, VE, KS, MC, "tests/test_bsi_m12.py"]

WAECHTER = [
    (["python3", "tests/test_bsi_m12.py"], r"Ergebnis: (\d+) OK, (\d+) FAIL"),
]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf():
    """Alle Waechter; Summe der FAILs. -1 = einer konnte nicht laufen."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    summe = 0
    for cmd, muster in WAECHTER:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                               cwd=str(ROOT), env=env)
        except subprocess.TimeoutExpired:
            return -1, "timeout " + cmd[-1]
        m = re.search(muster, r.stdout)
        if r.returncode == 2 or not m:
            return -1, f"{cmd[-1]} rc={r.returncode} {r.stdout.strip()[-160:]}"
        summe += int(m.group(2))
    return summe, 0


def zuruecknehmen():
    """Rueckstand eines abgeschossenen Laufs zuruecknehmen (Laufmarke)."""
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
