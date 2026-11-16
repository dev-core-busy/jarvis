#!/usr/bin/env python3
"""Gegenprobe: beisst tests/test_confluence_werkzeuge.py?

Sabotiert KOPIEN in einem Wegwerf-Verzeichnis und reicht sie ueber
CF_CLIENT / CF_SKILL an den Waechter – die echten Dateien werden nie
angefasst (der Betreiber arbeitet parallel im Arbeitsbaum). Vorher ein
gruener Basislauf; eine Probe "beisst" nur mit Exit 1 UND mindestens einem
FAIL (Exit 2 = konnte nicht laufen, zaehlt nicht).

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
WAECHTER = HIER / "test_confluence_werkzeuge.py"
DATEIEN = {
    "client": (ROOT / "backend" / "confluence_client.py", "CF_CLIENT"),
    "skill": (ROOT / "skills" / "confluence" / "main.py", "CF_SKILL"),
    "konten": (ROOT / "backend" / "confluence_accounts.py", "CF_ACCOUNTS"),
}

# (Name, Datei, alt, neu)
PROBEN = [
    ("Liste blaettert nicht (alter Stand)", "skill",
     "alle = c.spaces_detailed(MAX_SPACES_ABRUF)",
     "alle = c.spaces(50)"),
    ("Kuerzungshinweis fehlt", "skill",
     "if len(gezeigt) < len(treffer):",
     "if False:"),
    ("Kuerzungshinweis steht HINTER der Liste", "skill",
     '        return "\\n".join(kopf) + "\\n" + "\\n".join(\n'
     '            "- %s — %s" % (s.get("key") or "?", s.get("name") or "") for s in gezeigt)',
     '        return "\\n".join(\n'
     '            "- %s — %s" % (s.get("key") or "?", s.get("name") or "") for s in gezeigt)'
     ' + "\\n" + "\\n".join(kopf)'),
    ("key-Zweig fehlt", "skill",
     "        if key:\n            return await self._ein_bereich(c, key)",
     "        if False:\n            return await self._ein_bereich(c, key)"),
    ("jeder Fehler gilt als 'nicht sichtbar'", "skill",
     "            if e.status == 404:\n                return (\"❌ Bereich",
     "            if True:\n                return (\"❌ Bereich"),
    ("suche unterscheidet Gross/Klein", "skill",
     "s_cf = suche.casefold()",
     "s_cf = suche"),
    ("Verbindungstest zaehlt wieder 25", "skill",
     "spaces, vollstaendig = await _to_thread(_alle_spaces, c)",
     "spaces, vollstaendig = await _to_thread(c.spaces, 25), True"),
    ("Verbindungstest ohne Konto", "skill",
     'konto = (" als " + wer) if wer else ""',
     'konto = ""'),
    ("'mindestens' entfaellt", "skill",
     'return ("%d" % n) if vollstaendig else ("mindestens %d" % n)',
     'return "%d" % n'),
    ("Makro-Parameter bleiben als Text", "skill",
     'html_to_text(_RE_MAKRO_PARAM.sub("", storage or ""))',
     'html_to_text(storage or "")'),
    ("Erfolgsvermerk der Seite fehlt", "skill",
     " – Seite erfolgreich abgerufen.",
     "."),
    ("Unterseiten werden nicht angeboten", "skill",
     "            if pid:\n                teile.append(await self._unterseiten(c, pid))",
     "            if False:\n                teile.append(await self._unterseiten(c, pid))"),
    ("Unterseiten-Abruf auch bei echtem Inhalt", "skill",
     "if len(text) < KURZ_INHALT:",
     "if True:"),
    ("404 verschweigt die Leseberechtigung (alter Text)", "skill",
     '        return ("❌ Nicht gefunden (HTTP 404): existiert nicht ODER der verwendete "\n'
     '                "Confluence-Zugang darf es nicht lesen – Confluence unterscheidet das "\n'
     '                "nicht. ID/Schluessel/Titel pruefen (Cloud-URL meist mit /wiki).")',
     '        return "❌ Nicht gefunden (HTTP 404). URL/ID/Titel pruefen (Cloud-URL meist mit /wiki)."'),
    ("Client: Einzelabruf fragt die Liste", "client",
     '"/rest/api/space/%s" % quote(k, safe=""),\n                          params={"expand": "homepage"})',
     '"/rest/api/space",\n                          params={"expand": "homepage"})'),
    # ── Zugangszeile (2026-11-16) ──
    ("Zugangszeile wird nicht vorangestellt", "skill",
     'return (kopf + "\\n\\n" + ergebnis) if kopf else ergebnis',
     'return ergebnis'),
    ("ein Werkzeug umgeht die gemeinsame execute", "skill",
     '    async def _ausfuehren(self, c, **kwargs):\n'
     '        page_id = (kwargs.get("page_id") or "").strip()\n'
     '        if not page_id:\n'
     '            return "page_id ist erforderlich."\n'
     '        try:\n'
     '            atts',
     '    async def execute(self, **kwargs):\n'
     '        c = self._guard()\n'
     '        return await self._ausfuehren(c, **kwargs)\n\n'
     '    async def _ausfuehren(self, c, **kwargs):\n'
     '        page_id = (kwargs.get("page_id") or "").strip()\n'
     '        if not page_id:\n'
     '            return "page_id ist erforderlich."\n'
     '        try:\n'
     '            atts'),
    ("Grund des gemeinsamen Zugangs fehlt", "skill",
     '(" Grund: " + grund) if grund else ""',
     '""'),
    ("persoenlicher Zugang wird als gemeinsamer gemeldet", "skill",
     'if z["quelle"] == "persoenlich":',
     'if z["quelle"] == "persoenlich_x":'),
    ("client_fuer_lauf haengt keine Zugangsangabe an", "konten",
     '        c.zugang = {"quelle"',
     '        c._x = {"quelle"'),
    # ── Journal der Sitzungsanmeldung ──
    ("Erfolg wird nicht protokolliert", "konten",
     '    s = _SITZUNG.info(un)\n    print(',
     '    s = _SITZUNG.info(un)\n    if False: print('),
    ("Fehlschlag wird nicht protokolliert", "konten",
     '        print("[Confluence] Sitzungsanmeldung FEHLGESCHLAGEN',
     '        if False: print("[Confluence] Sitzungsanmeldung FEHLGESCHLAGEN'),
    ("Token landet im Journal", "konten",
     'un, s.get("sitzung_konto")',
     'un + token, s.get("sitzung_konto")'),
    ("Fehlschlag wird verschluckt", "konten",
     '        raise\n    s = _SITZUNG.info(un)',
     '        return {}\n    s = _SITZUNG.info(un)'),
    ("Abmelden ohne Zeile", "konten",
     '    if weg:\n        print("[Confluence] Sitzung beendet',
     '    if False:\n        print("[Confluence] Sitzung beendet'),
]


def lauf(env_extra):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **env_extra)
    p = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True, text=True,
                       env=env, timeout=180)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", p.stdout)
    return p.returncode, (int(m.group(2)) if m else None), p.stdout + p.stderr


def main():
    fehlend = {p[1] for p in PROBEN} - set(DATEIEN)
    if fehlend:
        print("ABBRUCH: Proben auf unbekannte Dateien: %s" % sorted(fehlend))
        return 2
    rc, fails, _ = lauf({})
    if rc != 0 or fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (Exit %s, FAIL %s)" % (rc, fails))
        return 2
    print("Basislauf gruen.")
    stumm = 0
    with tempfile.TemporaryDirectory(prefix="gegen_cfw_") as tmp:
        for name, datei, alt, neu in PROBEN:
            quelle, var = DATEIEN[datei]
            text = quelle.read_text(encoding="utf-8")
            n = text.count(alt)
            if n != 1:
                print("ABBRUCH: Anker der Probe '%s' trifft %d-mal statt einmal" % (name, n))
                return 2
            kopie = Path(tmp) / ("%s_%s" % (datei, quelle.name))
            kopie.write_text(text.replace(alt, neu), encoding="utf-8")
            rc, fails, ausgabe = lauf({var: str(kopie)})
            beisst = rc == 1 and (fails or 0) >= 1
            if not beisst:
                stumm += 1
            print("  %-48s %s (Exit %s, %s FAIL)" % (
                name, "beisst" if beisst else "STUMM", rc, fails))
            if rc == 2:
                print("    " + ausgabe.strip().splitlines()[-1][:200])
    print("\n%d von %d Proben beissen" % (len(PROBEN) - stumm, len(PROBEN)))
    return 0 if stumm == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
