#!/usr/bin/env python3
"""Gegenprobe: beisst tests/test_sap_ohne_kennwort.py?

Legt sabotierte KOPIEN von ``backend/sap_accounts.py`` bzw.
``backend/sap_client.py`` in ein Wegwerf-Verzeichnis und gibt sie dem Waechter
ueber ``SAP_OHNEKW_MODUL`` / ``SAP_OHNEKW_CLIENT`` mit – die echten Dateien
werden nie angefasst.

Vorher ein Basislauf gegen die unveraenderten Dateien: ohne gruene Basis ist
keine Probe deutbar. Eine Probe "beisst", wenn der Waechter mit Exit 1 und
mindestens einem FAIL endet – Exit 2 ("konnte nicht laufen") zaehlt NICHT.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = HIER.parent
WAECHTER = HIER / "test_sap_ohne_kennwort.py"
DATEIEN = {
    "modul": (ROOT / "backend" / "sap_accounts.py", "SAP_OHNEKW_MODUL"),
    "client": (ROOT / "backend" / "sap_client.py", "SAP_OHNEKW_CLIENT"),
}

# (Name, Datei, alt, neu)
PROBEN = [
    ("Aufloesung prueft das Geheimnis nicht (Stand vor dem Fix)", "modul",
     "                    if c.configured and _geheimnis_fehlt(cfg):\n",
     "                    if False:\n"),
    ("Basic: fehlendes Kennwort gilt nicht als fehlend", "modul",
     "    return bool(str(cfg.get(\"username\") or \"\").strip()) and not str(cfg.get(\"password\") or \"\")\n",
     "    return False\n"),
    ("Basic ohne Benutzer (anonym) gilt als fehlend", "modul",
     "    return bool(str(cfg.get(\"username\") or \"\").strip()) and not str(cfg.get(\"password\") or \"\")\n",
     "    return not str(cfg.get(\"password\") or \"\")\n"),
    ("Bearer ohne Token gilt nicht als fehlend", "modul",
     "        return not str(cfg.get(\"bearer_token\") or \"\").strip()\n",
     "        return False\n"),
    ("RFC ohne Kennwort gilt nicht als fehlend", "modul",
     "        return not str(cfg.get(\"rfc_password\") or \"\")\n",
     "        return False\n"),
    ("Hinweis fehlt beim Rueckfall", "modul",
     "                        hinweis = KEIN_KENNWORT_TEXT\n",
     "                        hinweis = \"\"\n"),
    ("Geheimnis-Pruefung auch in _vollstaendig (IdP findet den Zugang nicht mehr)", "modul",
     "    if ct == \"odata\":\n        return bool((k.get(\"odata_base_url\") or \"\").strip())\n",
     "    if ct == \"odata\":\n        return bool((k.get(\"odata_base_url\") or \"\").strip()"
     " and (k.get(\"password_enc\") or k.get(\"bearer_token_enc\")))\n"),
    ("get: rohes HTML im Fehlertext (Stand vor dem Fix)", "client",
     "                msg = http_fehlertext(r.status_code, r.text)\n",
     "                msg = (r.text or \"\")[:300]\n"),
    ("get_metadata_xml: rohes HTML im Fehlertext", "client",
     "            raise SapError(r.status_code, http_fehlertext(r.status_code, r.text))\n",
     "            raise SapError(r.status_code, (r.text or \"\")[:300])\n"),
    ("HTML-Titel wird nicht ausgewertet", "client",
     "        for muster in (r\"<title[^>]*>(.*?)</title>\", r\"<h[1-3][^>]*>(.*?)</h[1-3]>\"):\n",
     "        for muster in ():\n"),
    ("Tags im Titel bleiben stehen", "client",
     "    t = _html.unescape(re.sub(r\"<[^>]+>\", \" \", fragment or \"\"))\n",
     "    t = fragment or \"\"\n"),
    ("Gateway-XML wird nicht ausgewertet", "client",
     "    if kopf.startswith(\"<?xml\") or \"<error\" in kopf:\n",
     "    if False:\n"),
    ("HTTP-Status fehlt im Text", "client",
     "                return \"SAP meldet: %s (%s)\" % (_html_text(m.group(1)), kennung)\n",
     "                return \"SAP meldet: %s\" % _html_text(m.group(1))\n"),
]


def lauf(umgebung: dict) -> tuple:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **umgebung)
    r = subprocess.run([sys.executable, str(WAECHTER)], cwd=str(ROOT), env=env,
                       capture_output=True, text=True, timeout=300)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, (int(m.group(2)) if m else None), r.stdout + r.stderr


def main() -> int:
    nicht_gedeckt = {p[1] for p in PROBEN} - set(DATEIEN)
    if nicht_gedeckt:
        print(f"ABBRUCH: Proben auf unbekannte Dateien: {nicht_gedeckt}")
        return 2
    code, fails, aus = lauf({})
    if code != 0 or fails != 0:
        print(f"ABBRUCH: Basislauf nicht gruen (Exit {code}, FAIL {fails})")
        print(aus[-2000:])
        return 2
    print("Basislauf gruen.\n")
    stumm = 0
    with tempfile.TemporaryDirectory(prefix="gegen_sapohnekw_") as tmp:
        for i, (name, datei, alt, neu) in enumerate(PROBEN, 1):
            quelle, var = DATEIEN[datei]
            text = quelle.read_text(encoding="utf-8")
            n = text.count(alt)
            if n != 1:
                print(f"  ??  {i:2d} {name} – Anker {n}x gefunden (erwartet 1)")
                stumm += 1
                continue
            ziel = Path(tmp) / f"probe{i}_{quelle.name}"
            ziel.write_text(text.replace(alt, neu), encoding="utf-8")
            code, fails, aus = lauf({var: str(ziel)})
            if code == 1 and fails:
                print(f"  BEISST {i:2d} {name} ({fails} FAIL)")
            else:
                stumm += 1
                print(f"  STUMM  {i:2d} {name} (Exit {code}, FAIL {fails})")
    print(f"\nErgebnis: {len(PROBEN) - stumm}/{len(PROBEN)} Proben beissen")
    return 1 if stumm else 0


if __name__ == "__main__":
    sys.exit(main())
