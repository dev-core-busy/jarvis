#!/usr/bin/env python3
"""Gegenproben zu den Vorgabe-Fragen der AI-Maus.

Gemessen wird am EXIT-CODE und an der Bilanzzeile, nie am Zaehlen von FAILs.
Sicherung auf Platte + atexit + SIGTERM (ein per Timeout abgeschossener Lauf
laesst sonst einen sabotierten Arbeitsbaum zurueck).
"""
import atexit
import re
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABLAGE = Path.home() / ".gegen-am-vorgaben"

DATEIEN = ["backend/ai_mouse_fragen.py", "backend/main.py",
           "frontend/js/ai_mouse_admin.js", "frontend/js/app.js",
           "frontend/settings.html", "frontend/css/style.css",
           "frontend/js/i18n.js"]


def sichern():
    ABLAGE.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        (ABLAGE / rel.replace("/", "__")).write_bytes((ROOT / rel).read_bytes())


def zurueck():
    for rel in DATEIEN:
        q = ABLAGE / rel.replace("/", "__")
        if q.exists():
            (ROOT / rel).write_bytes(q.read_bytes())


def rueckstand():
    if ABLAGE.exists() and any(ABLAGE.iterdir()):
        abw = [r for r in DATEIEN
               if (ABLAGE / r.replace("/", "__")).exists()
               and (ABLAGE / r.replace("/", "__")).read_bytes() != (ROOT / r).read_bytes()]
        if abw:
            print(f"⚠ Rueckstand eines frueheren Laufs – nehme zurueck: {abw}")
            zurueck()


def ersetze(rel, alt, neu, anzahl=1):
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    assert s.count(alt) >= anzahl, f"Sabotage verfehlt ihr Ziel in {rel}: {alt[:70]!r}"
    p.write_text(s.replace(alt, neu, anzahl), encoding="utf-8")


def lauf():
    p = subprocess.run([sys.executable, "tests/test_ai_mouse.py"], cwd=ROOT,
                       capture_output=True, text=True, timeout=420)
    aus = p.stdout + p.stderr
    m = re.search(r"(\d+)\s*OK,\s*(\d+)\s*FAIL", aus)
    return p.returncode, bool(m), int(m.group(2)) if m else -1


PROBEN = [
    ("Vorgaben werden gar nicht gesaet", lambda: ersetze(
        "backend/ai_mouse_fragen.py",
        "        d[\"vorgaben\"] = [_neu(t, p) for t, p in _VORGABEN_SAAT]",
        "        d[\"vorgaben\"] = []")),

    ("Vorgaben landen in global_ statt beim Benutzer (nicht anpassbar)", lambda: ersetze(
        "backend/ai_mouse_fragen.py",
        "    eigen = d[\"benutzer\"].setdefault(k, [])\n    frei = max(0, MAX_JE_BENUTZER - len(eigen))",
        "    eigen = d.setdefault(\"global_\", [])\n    frei = max(0, MAX_JE_BENUTZER - len(eigen))")),

    ("Kopien behalten die Kennung der Vorgabe", lambda: ersetze(
        "backend/ai_mouse_fragen.py",
        "            eigen.append(_neu(e.get(\"titel\", \"\"), e.get(\"prompt\", \"\")))",
        "            eigen.append(dict(e))")),

    ("⚠ kein Marker je Benutzer: Geloeschtes kommt zurueck", lambda: ersetze(
        "backend/ai_mouse_fragen.py",
        "    if k in gesaet:\n        return False",
        "    if d[\"benutzer\"].get(k):\n        return False")),

    ("Uebernahme nicht verdrahtet (liste ruft sie nicht)", lambda: ersetze(
        "backend/ai_mouse_fragen.py",
        "        geaendert = _uebernehmen(d, user) or geaendert", "")),

    ("⚠ kein Raeum-Marker: eine neue gemeinsame Frage verschwindet wieder",
     lambda: ersetze(
        "backend/ai_mouse_fragen.py",
        "    if not d.get(\"_global_geraeumt\"):\n        if d.get(\"global_\"):\n"
        "            d[\"global_\"] = []\n        d[\"_global_geraeumt\"] = True\n"
        "        geaendert = True",
        "    if d.get(\"global_\"):\n        d[\"global_\"] = []\n        geaendert = True")),

    ("Altbestand wird gar nicht geraeumt", lambda: ersetze(
        "backend/ai_mouse_fragen.py",
        "        if d.get(\"global_\"):\n            d[\"global_\"] = []\n",
        "")),

    ("Aendern einer unbekannten Vorgabe legt still eine neue an", lambda: ersetze(
        "backend/ai_mouse_fragen.py",
        "            if alt is None:\n                raise FragenFehler(\"Die Vorgabe wurde nicht gefunden.\")",
        "            if alt is None:\n                alt = _neu(t, p); vor.append(alt)")),

    ("Deckel beim Kopieren raus", lambda: ersetze(
        "backend/ai_mouse_fragen.py",
        "    for e in (d.get(\"vorgaben\") or [])[:frei]:",
        "    for e in (d.get(\"vorgaben\") or []):")),

    ("Endpunkt nicht mehr Admin", lambda: ersetze(
        "backend/main.py",
        "async def ai_mouse_vorgabe_loeschen(fid: str, user: str = Depends(require_local_auth)):",
        "async def ai_mouse_vorgabe_loeschen(fid: str, user: str = Depends(require_auth)):")),

    ("Loeschen antwortet 403 statt 404", lambda: ersetze(
        "backend/main.py",
        '        return JSONResponse({"ok": False, "error": "Die Vorgabe wurde nicht gefunden."},\n'
        '                            status_code=404)',
        '        return JSONResponse({"ok": False, "error": "Verboten."}, status_code=403)')),

    ("Container nicht klappbar verdrahtet", lambda: ersetze(
        "frontend/js/app.js",
        "                { hdr: 'am-sect-vorg-hdr', body: 'am-sect-vorg-body', tog: 'am-sect-vorg-tog' },\n",
        "")),

    ("Liste wird beim Oeffnen nicht geladen", lambda: ersetze(
        "frontend/js/ai_mouse_admin.js", "            this.vorgabenLaden();\n", "")),

    ("Loeschen ohne Rueckfrage", lambda: ersetze(
        "frontend/js/ai_mouse_admin.js",
        "            if (!window.confirm(t('amvorg.del_ask', 'Vorgabe „{t}\" wirklich löschen?')\n"
        "                    .replace('{t}', v.titel || ''))) { return; }", "")),

    ("Ladefehler leert die Liste", lambda: ersetze(
        "frontend/js/ai_mouse_admin.js",
        "                .catch(function (e) {\n"
        "                    // ⚠ Ein Ladefehler bleibt STEHEN und die Liste wird NICHT",
        "                .catch(function (e) {\n"
        "                    var _b = $('amvorg-liste'); if (_b) { _b.innerHTML = ''; }\n"
        "                    // ⚠ Ein Ladefehler bleibt STEHEN und die Liste wird NICHT")),

    ("Titel wird ins Markup interpoliert (Attribut sprengbar)", lambda: ersetze(
        "frontend/js/ai_mouse_admin.js",
        "            if (ti) { ti.value = v.titel || ''; }", "")),

    ("Container fehlt im Markup", lambda: ersetze(
        "frontend/settings.html", '<div class="kb-section" id="am-sect-vorg">',
        '<div class="kb-section" id="am-sect-vorg-weg">')),

    ("CSS min-width raus", lambda: ersetze(
        "frontend/css/style.css",
        ".am-vorg-main { flex: 1; min-width: 0; overflow-wrap: anywhere; }",
        ".am-vorg-main { flex: 1; overflow-wrap: anywhere; }")),

    ("i18n nur deutsch", lambda: ersetze(
        "frontend/js/i18n.js", "        'amvorg.h':              'Default questions for new users',\n", "")),

    ("Hinweis (DE) verschweigt, dass Bestandsbenutzer nichts bekommen", lambda: ersetze(
        "frontend/js/i18n.js",
        "die AI-Maus <b>noch nie</b> benutzt haben", "die AI-Maus benutzt haben")),

    ("Hinweis (EN) ebenso", lambda: ersetze(
        "frontend/js/i18n.js",
        "who have <b>never</b> used AI-Mouse", "who have used AI-Mouse")),
]


def main():
    rueckstand()
    sichern()
    atexit.register(zurueck)
    signal.signal(signal.SIGTERM, lambda *a: (zurueck(), sys.exit(143)))

    print("=" * 74)
    print("BASISLAUF")
    print("=" * 74)
    rc, bil, f = lauf()
    print(f"  exit={rc} bilanz={bil} FAIL={f}")
    if rc or not bil or f:
        print("ABBRUCH: Basis ist nicht gruen – keine Gegenprobe deutbar.")
        return 2

    print("\n" + "=" * 74)
    print("GEGENPROBEN")
    print("=" * 74)
    zahnlos = []
    for name, fn in PROBEN:
        zurueck()
        try:
            fn()
        except AssertionError as e:
            print(f"  ⚠ {name}: {e}")
            zahnlos.append(name + " (Sabotage verfehlt)")
            continue
        rc, bil, f = lauf()
        gebissen = rc != 0
        print(("  ✔ " if gebissen else "  ✗ ZAHNLOS ") + name
              + f"  [exit={rc} " + (f"FAIL={f}]" if bil else "OHNE BILANZ]"))
        if not gebissen:
            zahnlos.append(name)

    zurueck()
    schlecht = [r for r in DATEIEN
                if (ROOT / r).read_bytes() != (ABLAGE / r.replace("/", "__")).read_bytes()]
    print("\n" + "=" * 74)
    print(f"Wiederhergestellt: {'OK' if not schlecht else 'ABWEICHUNG ' + str(schlecht)}")
    print(f"Gebissen: {len(PROBEN) - len(zahnlos)} von {len(PROBEN)}"
          + (f" · ZAHNLOS: {zahnlos}" if zahnlos else ""))
    print("=" * 74)
    for f in ABLAGE.iterdir():
        f.unlink()
    return 1 if (zahnlos or schlecht) else 0


if __name__ == "__main__":
    sys.exit(main())
