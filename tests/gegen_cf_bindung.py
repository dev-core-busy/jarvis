#!/usr/bin/env python3
"""Gegenproben zur dynamischen Confluence-Einbindung.

Jede Probe dreht GENAU EINE Zusage zurueck und misst, ob der zustaendige
Waechter das meldet. Eine Probe, die nicht beisst, ist ein Testmangel – kein
Beweis (oder die Zusage gibt es gar nicht; dann gehoert die Probe gestrichen,
nicht der Waechter geschaerft).

DREI REGELN AUS DEM REGISTER, hier als CODE statt als Vorsatz:

* **Jede angefasste Datei steht in der Sicherung** – geprueft, nicht gepflegt
  (Exit 2, sonst laesst ein Abbruch einen Rueckstand im Arbeitsbaum liegen).
* **Laufmarke**: nach einem `kill -9` nimmt der naechste Start den Rueckstand
  selbst zurueck; beim geordneten Ende wird sie abgeraeumt, damit ein spaeterer
  Lauf keine veraltete Sicherung herstellt.
* **Gruener Basislauf ist Bedingung** – ohne ihn ist keine Gegenprobe deutbar.

Gemessen wird EXIT-CODE **und** Bilanzzeile: ein Lauf, der ohne Bilanz
abbricht, ist von "bestanden" nicht zu unterscheiden.
"""
from __future__ import annotations

import atexit
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ABL = Path.home() / ".gegen-cf-bindung"
MARKE = ABL / "LAUF"

DATEIEN = [
    "backend/confluence_bindung.py",
    "backend/main.py",
    "backend/sandbox.py",
    "frontend/wissen.html",
    "frontend/js/wissen.js",
    "frontend/js/i18n.js",
]

PY_W = [sys.executable, str(ROOT / "tests" / "test_cf_bindung.py")]
JS_W = ["node", str(ROOT / "tests" / "test_cf_bindung_ui.js")]


# ── Sicherung ───────────────────────────────────────────────────────────────
def sichern() -> None:
    ABL.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        ziel = ABL / rel.replace("/", "__")
        shutil.copy2(ROOT / rel, ziel)
    MARKE.write_text("laeuft\n", encoding="utf-8")


def zurueck() -> None:
    for rel in DATEIEN:
        q = ABL / rel.replace("/", "__")
        if q.is_file():
            shutil.copy2(q, ROOT / rel)


def aufraeumen() -> None:
    zurueck()
    if MARKE.exists():
        MARKE.unlink()


# Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen.
if MARKE.exists():
    print("⚠ Rueckstand eines frueheren Laufs gefunden – wird zurueckgenommen.")
    zurueck()
    MARKE.unlink()


def lauf(cmd) -> tuple[int, str]:
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=300)
    return p.returncode, p.stdout + p.stderr


def bewerte(cmd) -> tuple[bool, str]:
    """(hat gemeldet?, Kurztext). Eine fehlende Bilanzzeile zaehlt als Meldung
    MIT Vorbehalt – sie bedeutet Abbruch, nicht Erfolg."""
    rc, aus = lauf(cmd)
    bilanz = [z for z in aus.splitlines() if "Ergebnis:" in z]
    if not bilanz:
        return True, "ABGEBROCHEN (keine Bilanz)"
    fails = sum(1 for z in aus.splitlines() if "✗" in z)
    return (rc != 0), f"{bilanz[-1].strip()} / {fails} FAIL"


# ── Proben ──────────────────────────────────────────────────────────────────
CFB = "backend/confluence_bindung.py"
MAIN = "backend/main.py"
SB = "backend/sandbox.py"
HTML = "frontend/wissen.html"
WJS = "frontend/js/wissen.js"
I18N = "frontend/js/i18n.js"

def _tausche_bloecke(s: str) -> str:
    """Vertauscht den Einbindungs-Container mit dem Block "Mein Wissen".

    Damit steht `wi-sec-cfbind` HINTER `wi-sec-files` – genau die Eigenschaft,
    die der Waechter zusichert. Findet die Funktion ihre Marken nicht, gibt sie
    den Text unveraendert zurueck; der Aufrufer wertet das als unbrauchbare
    Probe (und nicht als bestandenen Waechter)."""
    a = s.find("        <!-- Dynamische Confluence-Einbindung.")
    b = s.find("        <!-- Mein Wissen -->")
    e = s.find("    </div>\n\n    <script src=", b if b > 0 else 0)
    if not (0 < a < b < e):
        return s
    return s[:a] + s[b:e] + s[a:b] + s[e:]


PROBEN = [
    ("Dubletten-Pruefung raus", CFB,
     'if isinstance(b, dict) and (b.get("key") or "") == k:\n                raise BindungFehler("Dieser Bereich ist bereits eingebunden.")',
     'if False:\n                raise BindungFehler("Dieser Bereich ist bereits eingebunden.")', PY_W),

    ("Schluessel wird wieder GEKUERZT statt abgewiesen", CFB,
     'if len(k) > KEY_MAX or not _KEY_RE.match(k):',
     'k = k[:KEY_MAX]\n    if not _KEY_RE.match(k):', PY_W),

    # Der gemeldete Fall vom 2026-09-21: ohne `@` fallen alle PERSOENLICHEN
    # Bereiche durch (am echten Bestand 185 von 489).
    ("Zeichenmenge wieder zu eng (kein @)", CFB,
     'r"^[A-Za-z0-9._~@+-]+$"', 'r"^[A-Za-z0-9._~-]+$"', PY_W),

    ("inkl_unter per Falsyness statt 'is True'", CFB,
     '"inkl_unter": inkl_unter is True,', '"inkl_unter": bool(inkl_unter),', PY_W),

    ("Deckel raus", CFB,
     'if len(bereiche) >= MAX_BEREICHE:', 'if False:', PY_W),

    ("kaputte Datei wird ueberschrieben", CFB,
     '        return _leer()\n    if not isinstance(d, dict):',
     '        _speichern(_leer())\n        return _leer()\n    if not isinstance(d, dict):', PY_W),

    ("Lesefehler wird wieder still verschluckt", CFB,
     """        print(f"[CF-Bindung] {p} nicht lesbar ({type(e).__name__}: {e}) – "
              f"die Liste erscheint LEER. Pruefe Eigentuemer/Rechte "
              f"(erwartet: jarvis:jarvis 0640) bzw. den JSON-Inhalt.")""",
     "        pass", PY_W),

    ("entfernen meldet immer Erfolg", CFB,
     '        if len(d["bereiche"]) == vorher:\n            return False',
     '        if False:\n            return False', PY_W),

    ("POST prueft den Wissensbereich nicht", MAIN,
     '''    if not _editable_groups_for(user):
        return JSONResponse({"ok": False, "error": "Dir ist kein Wissensbereich zugewiesen."},
                            status_code=403)
    import backend.confluence_bindung as _cfb
    from backend.confluence_client import ConfluenceError''',
     '''    import backend.confluence_bindung as _cfb
    from backend.confluence_client import ConfluenceError''', PY_W),

    ("Sichtbarkeits-Pruefung NACH dem Einbinden", MAIN,
     '''    treffer = next((s for s in sichtbar if (s.get("key") or "") == key), None)
    if treffer is None:
        return JSONResponse({"ok": False, "error": "Bereich nicht sichtbar/erlaubt."},
                            status_code=403)
    try:
        eintrag = _cfb.hinzufuegen(key, treffer.get("name") or key,''',
     '''    try:
        eintrag = _cfb.hinzufuegen(key, key,''', PY_W),

    ("Anzeigename aus dem Rumpf", MAIN,
     'eintrag = _cfb.hinzufuegen(key, treffer.get("name") or key,',
     'eintrag = _cfb.hinzufuegen(key, body.get("name") or treffer.get("name") or key,', PY_W),

    ("_cfb_aktiv prueft den Skill nicht mehr", MAIN,
     'return bool(_skill_active("confluence")), bool(_confluence_client().configured)',
     'return True, bool(_confluence_client().configured)', PY_W),

    ("Ablage faellt aus _APP_DENY_REL", SB,
     '    "data/confluence_bindung.json",\n', '', PY_W),

    # ⚠ Diese Probe MUSS wirklich verschieben. Ein blosser Kommentar davor
    # laesst die Reihenfolge unveraendert – die erste Fassung sah dadurch wie
    # ein zahnloser Waechter aus und war eine schlecht platzierte Sabotage.
    ("Container steht NACH 'Mein Wissen'", HTML, _tausche_bloecke, None, PY_W),

    ("Kaestchen nicht mehr vorbelegt", HTML,
     '<input type="checkbox" id="wi-cfb-sub" checked>',
     '<input type="checkbox" id="wi-cfb-sub">', PY_W),

    ("Hinweis 'Abgleich folgt spaeter' raus", HTML,
     'data-i18n="wissen.cfb_soon"', 'data-i18n="wissen.cfb_weg"', PY_W),

    ("zweiter, eigener Abruf der Bereichsliste", WJS,
     "    function cfbLaden() {\n        fetch('/api/wissen/confluence/bindung'",
     "    function cfbLaden() {\n        fetch('/api/wissen/confluence/spaces', { headers: authH() });\n        fetch('/api/wissen/confluence/bindung'", PY_W),

    ("EN-Schluessel fehlt", I18N,
     "        'wissen.cfb_scope_top': 'this entry only',\n", "", PY_W),

    # ── Oberflaeche: hier misst nur der ausgefuehrte Renderer ──────────────
    ("die AUSWAHL bindet nicht mehr ein", WJS,
     "if (cfbSel) cfbSel.addEventListener('change', function () { cfbAdd(cfbSel.value); });",
     "if (cfbSel) { /* Verdrahtung weg */ }", JS_W),

    ("Container auch ohne aktiven Skill sichtbar", WJS,
     "        if (!_cfbAktiv) { sec.style.display = 'none'; return; }",
     "        if (false) { sec.style.display = 'none'; return; }", JS_W),

    ("eingebundene Bereiche bleiben im Angebot", WJS,
     "var frei = (_cfSpaces || []).filter(function (sp) { return !drin[sp.key]; });",
     "var frei = (_cfSpaces || []);", JS_W),

    ("inkl_unter wird nicht mitgesendet", WJS,
     "body: JSON.stringify({ key: key, inkl_unter: sub })",
     "body: JSON.stringify({ key: key })", JS_W),

    ("Bereichsname unmaskiert in die Liste", WJS,
     "+ '<span class=\"nm\">' + esc(b.name || b.key) + '</span>'",
     "+ '<span class=\"nm\">' + (b.name || b.key) + '</span>'", JS_W),

    ("Loeschen ohne Rueckfrage", WJS,
     "if (!window.confirm(t('wissen.cfb_del_ask', { n: label || id }))) return;", "", JS_W),

    ("Fehlschlag beim Einbinden wird verschluckt", WJS,
     "                  cfbStatus('⚠️ ' + ((d && d.error) || t('wissen.cfb_err')), true);\n                  cfbRenderPick();   // Auswahl zuruecksetzen, Pulldown wieder frei\n                  return;",
     "                  cfbRenderPick();\n                  return;", JS_W),

    ("Reichweite steht nicht mehr als Wort in der Zeile", WJS,
     "+ '<span class=\"wi-cfb-scope-tag\">' + esc(tag) + '</span>'", "", JS_W),

    ("kein Muelleimer mehr, sondern ×", WJS,
     "esc(t('wissen.cfb_del')) + '\">' + JarvisIcons.trash() + '</button>'",
     "esc(t('wissen.cfb_del')) + '\">×</button>'", JS_W),
]

# ── REGEL: jede angefasste Datei muss gesichert sein ────────────────────────
fremd = sorted({p[1] for p in PROBEN} - set(DATEIEN))
if fremd:
    print(f"⚠ Probe fasst ungesicherte Datei(en) an: {fremd} – Abbruch")
    sys.exit(2)

atexit.register(aufraeumen)
signal.signal(signal.SIGTERM, lambda *_: (aufraeumen(), sys.exit(143)))

sichern()

# ── Basislauf ───────────────────────────────────────────────────────────────
print("\033[1mBasislauf (muss gruen sein – sonst ist keine Probe deutbar)\033[0m")
basis_ok = True
for name, cmd in [("Backend/Regeln", PY_W), ("Oberflaeche (jsdom)", JS_W)]:
    rc, aus = lauf(cmd)
    z = [l for l in aus.splitlines() if "Ergebnis:" in l]
    print(f"  {name}: rc={rc} {z[-1].strip() if z else '(keine Bilanz)'}")
    if rc != 0:
        basis_ok = False
if not basis_ok:
    print("\033[31m⚠ Basis ist NICHT gruen – Abbruch\033[0m")
    sys.exit(2)

# ── Proben ──────────────────────────────────────────────────────────────────
print(f"\n\033[1m{len(PROBEN)} Gegenproben\033[0m")
beissen = 0
stumm = []
for name, rel, alt, neu, cmd in PROBEN:
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    # Trefferkontrolle: eine Ersetzung ohne Treffer ist kein Messwert. Fuer
    # Umbauten, die sich nicht als EIN Textersatz schreiben lassen (etwas
    # wirklich VERSCHIEBEN), darf `alt` eine Funktion sein – sie muss den Text
    # nachweislich aendern, sonst gilt die Probe als unbrauchbar.
    if callable(alt):
        s2 = alt(s)
        if s2 == s:
            print(f"  \033[33m⚠\033[0m {name}: SABOTAGE AENDERT NICHTS – Probe unbrauchbar")
            stumm.append(name + " (aendert nichts)")
            continue
    else:
        if s.count(alt) != 1:
            print(f"  \033[33m⚠\033[0m {name}: SABOTAGE TRIFFT NICHT ({s.count(alt)}x) – Probe unbrauchbar")
            stumm.append(name + " (trifft nicht)")
            continue
        s2 = s.replace(alt, neu, 1)
    p.write_text(s2, encoding="utf-8")
    try:
        gemeldet, info = bewerte(cmd)
    finally:
        zurueck()
    if gemeldet:
        beissen += 1
        print(f"  \033[32m✓\033[0m {name} → {info}")
    else:
        stumm.append(name)
        print(f"  \033[31m✗\033[0m {name} → BEISST NICHT ({info})")

# ── Kontrolle: der Arbeitsbaum ist wieder byte-gleich ───────────────────────
abweichend = [rel for rel in DATEIEN
              if (ROOT / rel).read_bytes() != (ABL / rel.replace("/", "__")).read_bytes()]
print(f"\n\033[1mErgebnis: {beissen}/{len(PROBEN)} Proben beissen\033[0m")
print(f"Arbeitsbaum wiederhergestellt: {'ja' if not abweichend else 'NEIN – ' + str(abweichend)}")
if stumm:
    print("Stumm: " + "; ".join(stumm))
sys.exit(1 if (stumm or abweichend) else 0)
