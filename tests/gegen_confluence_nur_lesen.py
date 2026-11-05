#!/usr/bin/env python3
"""Gegenprobe: beisst tests/test_confluence_nur_lesen.py?

Legt sabotierte KOPIEN in ein Wegwerf-Verzeichnis und gibt sie dem Waechter
ueber CF_CLIENT / CF_SKILL / CF_SKILLJSON / CF_SETTINGS / CF_MAIN mit – die
echten Dateien werden nie angefasst. Vorher ein gruener Basislauf; eine Probe
"beisst" nur mit Exit 1 UND mindestens einem FAIL (Exit 2 zaehlt nicht).

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = HIER.parent
WAECHTER = HIER / "test_confluence_nur_lesen.py"
DATEIEN = {
    "client": (ROOT / "backend" / "confluence_client.py", "CF_CLIENT"),
    "skill": (ROOT / "skills" / "confluence" / "main.py", "CF_SKILL"),
    "manifest": (ROOT / "skills" / "confluence" / "skill.json", "CF_SKILLJSON"),
    "settings": (ROOT / "frontend" / "settings.html", "CF_SETTINGS"),
    "main": (ROOT / "backend" / "main.py", "CF_MAIN"),
}

# (Name, Datei, alt, neu)
PROBEN = [
    ("POST wieder erlaubt", "client",
     'if (method or "").upper() != "GET" and ausnahme not in SCHREIB_AUSNAHMEN:',
     'if (method or "").upper() not in ("GET", "POST") and ausnahme not in SCHREIB_AUSNAHMEN:'),
    ("jede Ausnahme-Kennung oeffnet", "client",
     'if (method or "").upper() != "GET" and ausnahme not in SCHREIB_AUSNAHMEN:',
     'if (method or "").upper() != "GET" and not ausnahme:'),
    ("Sperre erst NACH dem Senden", "client",
     '        if (method or "").upper() != "GET" and ausnahme not in SCHREIB_AUSNAHMEN:\n'
     '            raise ConfluenceError(0, NUR_LESEN_TEXT)\n',
     ''),
    ("Destillat-Bilder ohne Ausnahme (Destillat bricht)", "client",
     '            headers={"X-Atlassian-Token": "no-check"}, files=files,\n            ausnahme="destillat")',
     '            headers={"X-Atlassian-Token": "no-check"}, files=files)'),
    ("neue Schreibmethode im Client", "client",
     '    def list_attachments(self',
     '    def delete_page(self, page_id):\n'
     '        return self._request("DELETE", "/rest/api/content/%s" % page_id, ausnahme="destillat")\n\n'
     '    def list_attachments(self'),
    ("Skill nutzt die Ausnahme", "skill",
     'async def _to_thread(',
     'def _anlegen(c):\n    return c.create_page\n\n\nasync def _to_thread('),
    ("schreibendes Werkzeug im Skill", "skill",
     '    def name(self): return "confluence_get_page"',
     '    def name(self): return "confluence_create_page"'),
    ("schreibendes Werkzeug im Manifest", "manifest",
     '        "confluence_get_page",\n        "confluence_list_attachments"',
     '        "confluence_get_page",\n        "confluence_update_page",\n        "confluence_list_attachments"'),
    ("zweiter Endpunkt nutzt die Ausnahme", "main",
     'def _cf_kein_schreibrecht(quelle: str, space: str) -> str:',
     'def _cf_x(c):\n    return c.create_page\n\n\ndef _cf_kein_schreibrecht(quelle: str, space: str) -> str:'),
    ("Kaestchen abschaltbar", "settings",
     '<input type="checkbox" id="cf-read-only" checked disabled>',
     '<input type="checkbox" id="cf-read-only" checked>'),
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
    print(f"Basislauf gruen.\n")
    stumm = 0
    with tempfile.TemporaryDirectory(prefix="gegen_sapkachel_") as tmp:
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
