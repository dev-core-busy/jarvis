#!/usr/bin/env python3
"""Gegenproben zur AI-Maus-Aktion „Anonymisieren" (2026-10-27).

Jede Probe dreht GENAU EINE Zusage zurueck; gemessen wird, ob
``tests/test_anonymisieren.py`` oder ``tests/test_am_anonym_ui.js`` es meldet.
Eine Gegenprobe, die nicht beisst, ist ein Testmangel – kein Beweis.

Bauart wie ``gegen_am_bild.py``: jede angefasste Datei wird gesichert (die
Liste wird als REGEL geprueft), Laufmarke im HOME, gruene Basis als
Voraussetzung, Bilanzzeile statt Exit-Code, kein Bytecode.
"""
import atexit
import hashlib
import os
import pathlib
import re
import shutil
import signal
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
ABL = pathlib.Path.home() / ".gegen-anonymisieren"
MARKE = ABL / "LAUF"

AN = "backend/anonymisieren.py"
AMF = "backend/ai_mouse_fragen.py"
AM = "backend/ai_mouse.py"
ADM = "frontend/js/ai_mouse_admin.js"

DATEIEN = [AN, AMF, AM, ADM,
           "tests/test_anonymisieren.py", "tests/test_am_anonym_ui.js"]


def sichern():
    ABL.mkdir(mode=0o700, exist_ok=True)
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, ABL / rel.replace("/", "__"))
    MARKE.write_text("laeuft\n", encoding="utf-8")


def zurueck(still=False):
    for rel in DATEIEN:
        q = ABL / rel.replace("/", "__")
        if q.exists():
            shutil.copy2(q, ROOT / rel)
    if not still:
        for rel in DATEIEN:
            a = hashlib.md5((ABL / rel.replace("/", "__")).read_bytes()).hexdigest()
            b = hashlib.md5((ROOT / rel).read_bytes()).hexdigest()
            if a != b:
                print("  ⚠ NICHT wiederhergestellt: " + rel)


def ende():
    zurueck(still=True)
    if MARKE.exists():
        MARKE.unlink()


def lies(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def ersetze(rel, alt, neu):
    s = lies(rel)
    assert s.count(alt) == 1, "Anker %dx in %s: %r" % (s.count(alt), rel, alt[:70])
    (ROOT / rel).write_text(s.replace(alt, neu, 1), encoding="utf-8")


_UMG = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")


def waechter():
    """(fails, bilanz_da) ueber BEIDE Waechter – gemessen an der Bilanzzeile."""
    gesamt, alle_da = 0, True
    for befehl in ([sys.executable, "tests/test_anonymisieren.py"],
                   ["node", "tests/test_am_anonym_ui.js"]):
        try:
            p = subprocess.run(befehl, cwd=ROOT, capture_output=True, text=True,
                               timeout=600, env=_UMG)
            m = re.search(r"^(\d+) OK, (\d+) FAIL$", p.stdout, re.M)
        except subprocess.TimeoutExpired:
            m = None
        if m:
            gesamt += int(m.group(2))
        else:
            alle_da = False
    return gesamt, alle_da


PROBEN = []


def probe(name):
    def deko(fn):
        PROBEN.append((name, fn))
        return fn
    return deko


# ── a) Die Kette ────────────────────────────────────────────────────────────
@probe("Presidio-Treffer werden verworfen")
def _():
    ersetze(AN, "markiert.update(treffer_zuordnen(spannen, a.get(\"treffer\") or []))",
            "treffer_zuordnen(spannen, a.get(\"treffer\") or [])")


@probe("Sprachmodell-Ergaenzung wird ignoriert (keine Vereinigung)")
def _():
    ersetze(AN, "                    markiert.setdefault(i, \"PERSON\")\n",
            "                    pass\n")


@probe("Trefferzuordnung nur bei VOLLER Enthaltung (Komma-Wort faellt raus)")
def _():
    ersetze(AN, "            if we > s and ws < e:", "            if ws >= s and we <= e:")


@probe("Boxen werden nicht auf das Original zurueckgerechnet")
def _():
    ersetze(AN, "            w[k] = int(round(w[k] / fak))", "            w[k] = int(w[k])")


@probe("Spalten werden nicht getrennt")
def _():
    ersetze(AN, "            if luecke > 2.5 * max(a[\"h\"], b[\"h\"]):",
            "            if luecke > 1e9:")


@probe("benachbarte Namensteile werden NICHT zusammengefasst")
def _():
    ersetze(AN, "                if akt is None:\n                    akt = box\n                else:",
            "                if akt is not None:\n                    raus.append(akt)\n"
            "                if True:\n                    akt = box\n                else:")


@probe("Text wird nicht geschwaerzt")
def _():
    ersetze(AN, "        d.rectangle(box, fill=textfarbe)\n", "")


@probe("Gesichter werden nicht verpixelt")
def _():
    ersetze(AN, "        img.paste(klein.resize((r - l, b - t), Image.NEAREST), (l, t))\n", "")


@probe("Ausfall des Hilfsprozesses wird verschwiegen")
def _():
    ersetze(AN, "            luecken.append(\"l_helfer\")\n", "            pass\n")


@probe("Ausfall des Sprachmodells wird verschwiegen")
def _():
    ersetze(AN, "                luecken.append(\"l_llm\")\n", "                pass\n")


@probe("Arbeitsordner mit dem Original bleibt liegen")
def _():
    ersetze(AN, "        shutil.rmtree(arbeit, ignore_errors=True)\n", "        pass\n")


# ── b) Frist ────────────────────────────────────────────────────────────────
@probe("Vorgabe der Frist ist ein Tag statt 30 Minuten")
def _():
    ersetze(AN, 'os.environ.get("JARVIS_ANONYM_TTL_MIN", "30")',
            'os.environ.get("JARVIS_ANONYM_TTL_MIN", "1440")')


@probe("0 heisst wieder „nie loeschen“")
def _():
    ersetze(AN, "    if v <= 0:\n        return 30\n", "    if v <= 0:\n        return 0\n")


@probe("keine Frist-Marke – das Ergebnis bliebe 30 Tage")
def _():
    ersetze(AN, "            _frist_merken(name)\n", "            pass\n")


@probe("Aufraeumen loescht das Bild, aber nicht die Marke")
def _():
    ersetze(AN, "            marke.unlink()\n", "            pass\n")


# ── c) Aktionsfeld ──────────────────────────────────────────────────────────
@probe("unbekannte Aktion wird angenommen")
def _():
    ersetze(AMF, "    if a and a not in AKTIONEN:", "    if False:")


@probe("Teilstring statt exaktem Abgleich")
def _():
    ersetze(AMF, 'str(e.get("prompt") or "").strip() == gesucht',
            'str(e.get("prompt") or "").strip() in gesucht')


@probe("Aktion wird bei fremden Benutzern gesucht")
def _():
    ersetze(AMF, '        eigen = d["benutzer"].get(_norm(user)) or []\n        for e in list(d["global_"])',
            '        eigen = [x for l in d["benutzer"].values() for x in l]\n'
            '        for e in list(d["global_"])')


@probe("Kopie der Vorgabe verliert die Aktion")
def _():
    ersetze(AMF, ', vid,\n                          _aktion_oder_leer(e.get("aktion"))))', ', vid))')


@probe("Umbenennen der Kopie verliert die Aktion")
def _():
    ersetze(AMF, '        if alt is not None and _aktion_oder_leer(alt.get("aktion")):',
            '        if False:')


@probe("analysieren verzweigt nicht mehr")
def _():
    ersetze(AM, '    if aktion_der_frage(user, frage) == "anonymisieren":', '    if False:')


# ── d) Admin-Oberflaeche ────────────────────────────────────────────────────
@probe("die gewaehlte Art geht nicht an den Server")
def _():
    ersetze(ADM, "aktion: art ? art.value : ''", "aktion: ''")


@probe("die Liste kennzeichnet die Aktion nicht")
def _():
    ersetze(ADM, "(v.aktion === 'anonymisieren'\n", "(false\n")


@probe("das Formular zeigt die gespeicherte Art nicht")
def _():
    ersetze(ADM, "art.value = v.aktion === 'anonymisieren' ? 'anonymisieren' : '';",
            "art.value = '';")


@probe("die Beschriftung wechselt nicht mit der Art")
def _():
    ersetze(ADM, "                lbl.textContent = anon\n", "                lbl.textContent = false\n")


def main():
    if MARKE.exists():
        print("⚠ Rueckstand eines abgebrochenen Laufs - nehme ihn zurueck.")
        zurueck(still=True)

    # REGEL: was eine Probe anfasst, muss gesichert sein.
    quelle = pathlib.Path(__file__).read_text(encoding="utf-8")
    genannt = {d for d in re.findall(r'"([\w/.-]+\.(?:py|js))"', quelle) if (ROOT / d).exists()}
    fehlend = genannt - set(DATEIEN)
    if fehlend:
        print("⚠ NICHT GESICHERT: " + ", ".join(sorted(fehlend)))
        sys.exit(2)

    sichern()
    atexit.register(ende)
    signal.signal(signal.SIGTERM, lambda *a: sys.exit(1))

    basis, da = waechter()
    if not da or basis != 0:
        print("⚠ BASIS NICHT GRUEN (%s FAIL, Bilanz %s) - ohne gruene Basis ist keine "
              "Gegenprobe deutbar." % (basis, da))
        sys.exit(2)
    print("Basis gruen (%d Proben)\n" % len(PROBEN))

    stumm = []
    for name, fn in PROBEN:
        zurueck(still=True)
        try:
            fn()
        except AssertionError as e:
            print("  ⚠ SABOTAGE VERFEHLT: %s - %s" % (name, e))
            stumm.append(name + " (verfehlt)")
            continue
        fails, bilanz = waechter()
        if not bilanz:
            print("  ABBRUCH ohne Bilanz: %s" % name)
            stumm.append(name + " (ohne Bilanz)")
        elif fails > 0:
            print("  beisst (%2d FAIL)  %s" % (fails, name))
        else:
            print("  ⚠ STUMM          %s" % name)
            stumm.append(name)

    zurueck()
    print("\n%d von %d Proben beissen." % (len(PROBEN) - len(stumm), len(PROBEN)))
    if stumm:
        print("STUMM: " + "; ".join(stumm))
    sys.exit(1 if stumm else 0)


main()
