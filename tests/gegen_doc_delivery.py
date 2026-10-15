#!/usr/bin/env python3
"""Gegenproben zur Auslieferung von Ergebnisdateien – beissen die Waechter einzeln?

Gegenstand sind die drei Aenderungen vom 2026-10-06 (Vorfall auf ECHT:
PDF -> JPEG, "weder vorschau noch download link"):
  a) Seiten-Geschwister (`foo.jpg` -> `foo-1.jpg`) werden ausgeliefert, und ein
     blosser Name ohne Datei wird GEMELDET statt still uebergangen,
  b) die Meldung traegt `persist` und ueberlebt damit das Laufende im Frontend,
  c) der Prompt verlangt, den Dateinamen vor dem Nennen GESEHEN zu haben.

Gefahren werden ZWEI Waechter: tests/test_doc_delivery.py (Backend) und
tests/test_chat_status_sichtbar.js (Frontend). Jede Probe dreht GENAU EINE
Zusage zurueck und erwartet FAIL. Eine Probe, die nicht beisst, ist ein
Testmangel – oder die Zusage existiert gar nicht; das ist die erste Frage,
nicht die letzte (Register).

    python3 tests/gegen_doc_delivery.py

⚠ NICHT in einem Sammellauf mitfahren lassen: diese Datei PATCHT den
Arbeitsbaum. Wird sie mitten in einer Probe abgeschossen, nimmt der naechste
Start den Rueckstand ueber die Laufmarke selbst zurueck.

Harness-Regeln, jede aus einem bezahlten Vorfall:
  * VOR jeder Probe auf Platte sichern, danach byte-genau (md5) zuruecklegen.
  * LAUFMARKE gegen Rueckstaende nach `kill -9` (ein `kill` fuehrt kein atexit
    aus).
  * Die Sicherungsliste wird als REGEL geprueft, nicht gepflegt -> Exit 2.
  * Gemessen wird an der BILANZZEILE, nicht am Exit-Code allein.
  * Jede Ersetzung hat eine Trefferkontrolle, sonst "beisst" sie scheinbar
    nicht, weil sie gar nicht griff.
"""
import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

WAECHTER = {
    "py": ROOT / "tests" / "test_doc_delivery.py",
    "js": ROOT / "tests" / "test_chat_status_sichtbar.js",
}

DATEIEN = [
    "backend/agent.py",
    "frontend/js/chat.js",
    "frontend/css/chat.css",
    "tests/test_doc_delivery.py",
    "tests/test_chat_status_sichtbar.js",
]

SICHER = Path.home() / ".gegen-docdelivery"
MARKE = SICHER / ".laeuft"


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def sichern():
    SICHER.mkdir(parents=True, exist_ok=True)
    for rel in DATEIEN:
        # Relativer PFAD als Schluessel, nicht der Basisname: es gibt mehrere
        # gleichnamige Dateien im Projekt.
        (SICHER / rel.replace("/", "__")).write_bytes((ROOT / rel).read_bytes())
    MARKE.write_text("1")


def zurueck(pruefen=True):
    for rel in DATEIEN:
        q = SICHER / rel.replace("/", "__")
        if not q.is_file():
            continue
        (ROOT / rel).write_bytes(q.read_bytes())
        if pruefen and md5(ROOT / rel) != md5(q):
            print(f"  ⚠ {rel} NICHT byte-gleich wiederhergestellt")
    MARKE.unlink(missing_ok=True)


def lauf(welcher: str):
    """Waechter fahren; (fails, bilanz_vorhanden, rc).

    Die beiden Waechter schreiben verschiedene Bilanzzeilen – beide Formen
    werden gelesen, damit ein Formatwechsel nicht als "stumm" durchgeht.
    """
    datei = WAECHTER[welcher]
    befehl = [sys.executable, str(datei)] if welcher == "py" else ["node", str(datei)]
    r = subprocess.run(befehl, capture_output=True, text=True, timeout=300,
                       cwd=str(ROOT))
    m = (re.search(r"(\d+)\s*ok,\s*(\d+)\s*Fehler", r.stdout)
         or re.search(r"Ergebnis:\s*(\d+)\s*OK,\s*(\d+)\s*FAIL", r.stdout))
    if not m:
        return None, False, r.returncode
    return int(m.group(2)), True, r.returncode


def patch(rel, alt, neu):
    """Ersetzt GENAU EINMAL, mit Trefferkontrolle."""
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    if s.count(alt) < 1:
        raise AssertionError(f"SABOTAGE TRIFFT NICHT in {rel}: {alt[:80]!r}")
    p.write_text(s.replace(alt, neu, 1), encoding="utf-8")


# ── Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen ───────────────
if MARKE.exists():
    print("⚠ Rueckstand eines abgebrochenen Laufs gefunden – nehme ihn zurueck")
    zurueck()

PROBEN = []       # (label, welcher_waechter, rel, alt, neu)


def probe(label, welcher, rel, alt, neu):
    PROBEN.append((label, welcher, rel, alt, neu))


# ═════════════════════════════════════════════════════════════════════════════
# A – Seiten-Geschwister (der gemeldete Fall)
probe("Geschwister-Suche abgeschaltet (Zustand vor dem Fix)", "py",
      "backend/agent.py",
      "                _geschwister = _seiten_geschwister(raw)",
      "                _geschwister = []")

probe("Zahlen-Pruefung weg: jeder Zusatz gilt als Seite", "py",
      "backend/agent.py",
      "                    if not t or not t.group(1).isdigit():",
      "                    if not t:")

probe("Suchraum auf das gemeinsame /tmp aufgezogen", "py",
      "backend/agent.py",
      "            for d in _lauf_tmp.such_wurzeln():",
      "            for d in _search_dirs:")

probe("mtime-Schranke der Namenstreffer uebersprungen", "py",
      "backend/agent.py",
      "            if not _aus_diesem_lauf(found):\n"
      "                _log(f\"Namens-Treffer verworfen (nicht aus diesem Lauf): {found}\")\n"
      "                delivered.add(key)\n"
      "                return\n",
      "")

# Der GUERTEL unter dem Suchraum: solange `_search_dirs` das
# Projektverzeichnis nicht enthaelt, kann die Ortsschranke nichts fangen –
# eine Probe, die nur sie entfernt, ist zu Recht stumm. Messbar wird sie,
# wenn man den Suchraum ausweitet UND den Guertel wegnimmt: dann geht eine
# Zustandsdatei aus dem Projektverzeichnis als "Ergebnis" heraus.
probe("Suchraum auf proj ausgeweitet (Guertel haelt)", "py",
      "backend/agent.py",
      "        _search_dirs = [docs_dir] + _arb_roots",
      "        _search_dirs = [docs_dir, proj] + _arb_roots")

probe("Suchraum auf proj AUSGEWEITET und Ortsschranke weg", "py",
      "backend/agent.py",
      "        _search_dirs = [docs_dir] + _arb_roots",
      "        _search_dirs = [docs_dir, proj] + _arb_roots\n"
      "        _unter_arbeit_echt = _unter_arbeit\n"
      "        _unter_arbeit = lambda _p: True")

probe("Secret-Schranke der Namenstreffer uebersprungen", "py",
      "backend/agent.py",
      "            if _ist_geheim(found):\n"
      "                _log(f\"Namens-Treffer abgelehnt (Secret): {found.name}\")\n"
      "                return\n",
      "")

probe("Seiten-Deckel entfernt", "py",
      "backend/agent.py",
      "                    for _g in _geschwister[:_SEITEN_DECKEL]:",
      "                    for _g in _geschwister:")

probe("abgeschnittene Seiten werden NICHT genannt (stiller Verlust)", "py",
      "backend/agent.py",
      "                    if len(_geschwister) > _SEITEN_DECKEL:\n"
      "                        _zuviele.append((raw, len(_geschwister)))",
      "                    pass")

probe("Geschwister NUMERISCH sortiert -> Reihenfolge verdreht", "py",
      "backend/agent.py",
      "            treffer.sort()",
      "            treffer.sort(reverse=True)")

# B – blosser Name ohne Datei: Meldung statt Stille
probe("Meldung fuer blosse Namen entfernt (nacktes continue wie vorher)", "py",
      "backend/agent.py",
      "                elif melden and _nichts_geliefert() and not _ist_anhangname(raw):",
      "                elif False:")

probe("Anhang-Schranke raus (Eingabename wuerde gemeldet)", "py",
      "backend/agent.py",
      "            return False\n\n        async def _liefere_namenstreffer",
      "            return False\n\n        _ist_anhangname = lambda _n: False\n\n"
      "        async def _liefere_namenstreffer")

probe("Meldeauftrag ignoriert – BEIDE Schranken weg (warnt verfrueht)", "py",
      "backend/agent.py",
      "            if not melden or _bereits:\n                return\n",
      "            if _bereits:\n                return\n")

probe("Meldung auch neben fertigem Chip (Fehler vom 2026-09-04 zurueck)", "py",
      "backend/agent.py",
      "                elif melden and _nichts_geliefert() and not _ist_anhangname(raw):",
      "                elif melden and not _ist_anhangname(raw):")

# C – persist: die Meldung ueberlebt das Laufende
probe("persist an der Liefer-Warnung entfernt", "py",
      "backend/agent.py",
      '                "erneut erzeugen lassen.",\n                highlight=True, persist=True)',
      '                "erneut erzeugen lassen.",\n                highlight=True)')

probe("persist-Feld wird nicht gesendet (Backend-Haelfte)", "py",
      "backend/agent.py",
      '            if persist:\n                msg["persist"] = True\n',
      "")

probe("chat.js: persist-Block entfernt (Zustand vor dem Fix)", "js",
      "frontend/js/chat.js",
      "        if (msg.persist) {\n"
      "            if (_detached) return;   // fremde Sitzung: hier nichts zeichnen\n"
      "            _clearActivity();        // Spinner weg, die Meldung bleibt stehen\n"
      "            addStatusLine(text, true);\n"
      "            return;\n"
      "        }\n",
      "")

probe("chat.js: persist-Block HINTER die Praefix-Regel (nie erreicht)", "js",
      "frontend/js/chat.js",
      "        if (msg.persist) {\n"
      "            if (_detached) return;   // fremde Sitzung: hier nichts zeichnen\n"
      "            _clearActivity();        // Spinner weg, die Meldung bleibt stehen\n"
      "            addStatusLine(text, true);\n"
      "            return;\n"
      "        }\n\n"
      "        if (msg.highlight && !isStatus) {",
      "        if (msg.highlight && !isStatus) {")

probe("chat.js: Warn-Aufmachung weggelassen (leise graue Zeile)", "js",
      "frontend/js/chat.js",
      "            addStatusLine(text, true);",
      "            addStatusLine(text);")

probe("chat.js: _clearActivity() im persist-Zweig vergessen (Spinner bleibt)", "js",
      "frontend/js/chat.js",
      "            _clearActivity();        // Spinner weg, die Meldung bleibt stehen\n",
      "")

# Die Schriftfarbe ist THEMENABHAENGIG – jede Haelfte einzeln geprobt.
probe("chat.css: im HELLEN Thema nacktes var(--danger) (3,76:1)", "js",
      "frontend/css/chat.css",
      "body.light .msg-status-warn {\n"
      "    color: color-mix(in srgb, var(--danger) 78%, #000);\n}",
      "body.light .msg-status-warn {\n    color: var(--danger);\n}")

probe("chat.css: EINE Farbe fuer beide Themen (dunkel 3,08:1)", "js",
      "frontend/css/chat.css",
      "    color: var(--danger);\n    background: var(--bg-secondary);",
      "    color: color-mix(in srgb, var(--danger) 78%, #000);\n"
      "    background: var(--bg-secondary);")

probe("chat.css: Themenregel ganz entfernt (hell faellt zurueck)", "js",
      "frontend/css/chat.css",
      "\nbody.light .msg-status-warn {\n"
      "    color: color-mix(in srgb, var(--danger) 78%, #000);\n}\n",
      "\n")

probe("chat.css: Warn-Zeile wieder 12 px und zentriert", "js",
      "frontend/css/chat.css",
      "    font-size: 14px;\n    text-align: left;\n"
      "    color: var(--danger);",
      "    font-size: 12px;\n    text-align: center;\n"
      "    color: var(--danger);")

probe("chat.css: Flaeche durchscheinend (liegt ueber dem Verlauf)", "js",
      "frontend/css/chat.css",
      "    background: var(--bg-secondary);\n    border-left: 3px solid var(--danger);",
      "    border-left: 3px solid var(--danger);")

# D – der Prompt (c)
probe("Prompt-Regel 'Namen erst nennen, wenn gesehen' entfernt", "py",
      "backend/agent.py",
      "    - NENNE einen Dateinamen erst, wenn du ihn GESEHEN hast.",
      "    - (Hinweis entfernt.) Frueher hier: ")

# E – Drift-Schranken an den Waechtern selbst
probe("Prompt nennt den Ausweg -singlefile nicht mehr", "py",
      "backend/agent.py",
      "Soll genau eine Bilddatei ohne Seitenzusatz entstehen: `pdftoppm -singlefile`.",
      "")

probe("Fehler-Praefixliste im Waechter leer (Regel trivial wahr)", "py",
      "tests/test_doc_delivery.py",
      '        _FEHLER_PRAEFIXE = ("⚠️", "❌")',
      '        _FEHLER_PRAEFIXE = ()')


# ── REGEL statt gepflegter Liste ────────────────────────────────────────────
_fremd = {rel for _, _, rel, _, _ in PROBEN} - set(DATEIEN)
if _fremd:
    print(f"ABBRUCH: Proben fassen Dateien an, die nicht gesichert werden: {_fremd}")
    sys.exit(2)

# ── Basislauf BEIDER Waechter MUSS gruen sein ───────────────────────────────
print("Basislauf …")
sichern()
for _w in WAECHTER:
    _f, _b, _rc = lauf(_w)
    if not _b:
        print(f"ABBRUCH: Basislauf {_w} ohne Bilanzzeile (rc={_rc})")
        zurueck()
        sys.exit(2)
    if _f != 0:
        print(f"ABBRUCH: Basislauf {_w} ist NICHT gruen ({_f} FAIL) – "
              "ohne gruene Basis ist keine Gegenprobe deutbar")
        zurueck()
        sys.exit(2)
    print(f"  {_w}: gruen (0 FAIL)")
print()

beissen = stumm = 0
for label, welcher, rel, alt, neu in PROBEN:
    try:
        patch(rel, alt, neu)
    except AssertionError as e:
        print(f"  ⚠ PROBEN-MANGEL  {label}\n      {e}")
        stumm += 1
        zurueck(pruefen=False)
        sichern()
        continue
    fails, bilanz, rc = lauf(welcher)
    zurueck()
    sichern()
    if rc == 2:
        # "Konnte nicht laufen" ist bei einer Schranken-Probe der GEWOLLTE
        # Ausgang und muss von "stumm" unterscheidbar sein.
        print(f"  beisst (Exit 2)    [{welcher}] {label}")
        beissen += 1
    elif not bilanz:
        print(f"  ⚠ OHNE BILANZ     [{welcher}] {label} (abgebrochen statt FAIL, rc={rc})")
        stumm += 1
    elif fails:
        print(f"  beisst ({fails} FAIL)   [{welcher}] {label}")
        beissen += 1
    else:
        print(f"  ⚠ STUMM           [{welcher}] {label}")
        stumm += 1

zurueck()
print(f"\nErgebnis: {beissen} von {len(PROBEN)} Proben beissen, {stumm} stumm")
for rel in DATEIEN:
    q = SICHER / rel.replace("/", "__")
    if q.is_file() and md5(ROOT / rel) != md5(q):
        print(f"  ⚠ RUECKSTAND in {rel}")
sys.exit(1 if stumm else 0)
