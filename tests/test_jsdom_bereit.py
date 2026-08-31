#!/usr/bin/env python3
"""Waechter: jsdom fuer die UI-Riegel der Delegation (backend/jsdom_bereit.py).

⚠ WARUM ES DIESE DATEI GIBT: 47 der 50 JS-Tests brauchen jsdom, und der Riegel
eines delegierten Auftrags laeuft in einem FRISCHEN Klon, in dem
``node_modules/`` per .gitignore fehlt. Auftrag be31e4825d52 wurde am
2026-08-31 deshalb abgelehnt – 17 Pruefungen gruen, eine rot, und die eine war
"jsdom vorhanden". Der Agent hatte alles richtig gemacht.

DIE WICHTIGSTE PRUEFUNG IST DIE DRIFT-SCHRANKE: `installieren()` schreibt nach
`ZIEL`, und `riegel_laufen()` setzt `JSDOM_PATH` aus `pfad()`. Laufen die beiden
Orte auseinander, bleibt jeder UI-Riegel rot, und niemand sieht warum – genau
die Fehlerklasse, die dieses Projekt schon mehrfach Stunden gekostet hat.

    python3 tests/test_jsdom_bereit.py
"""
import ast
import os
import re
import sys
import tempfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

_ok = _fail = 0


def check(name: str, cond, detail: str = "") -> None:
    """(Beschreibung, Bedingung) – NICHT umgekehrt.

    Harte Abbruchbedingung wie in tests/test_vemas.py: eine nicht-leere
    Zeichenkette ist wahr, vertauschte Argumente liessen jeden Aufruf gruen
    durchlaufen (57 Faelle in test_jira_vorlagen.py).
    """
    global _ok, _fail
    if isinstance(name, bool) or not isinstance(name, str):
        print("\033[31mABBRUCH: check() falsch herum aufgerufen\033[0m")
        sys.exit(2)
    if cond:
        _ok += 1
        print(f"  \033[32m✓\033[0m {name}")
    else:
        _fail += 1
        print(f"  \033[31m✗\033[0m {name}" + (f" – {detail}" if detail else ""))


def abschnitt(t: str) -> None:
    print(f"\n\033[1m{t}\033[0m")


from backend import jsdom_bereit as jb  # noqa: E402

# ══════════════════════════════════════════════════════════════════════════
abschnitt("1) Der Ort ist EINE Quelle – Installation und Riegel dieselbe Stelle")
# ══════════════════════════════════════════════════════════════════════════
check("ZIEL liegt neben dem Repo, nicht darin (data/node_modules)",
      jb.ZIEL == WURZEL / "data" / "node_modules", str(jb.ZIEL))
# Der eigentliche Drift: findet `pfad()` auch das, was `installieren()` anlegt?
check("pfad() sucht genau dort, wo installieren() schreibt",
      any(p == jb.ZIEL / "jsdom" for p in jb._orte()),
      " | ".join(str(p) for p in jb._orte()))
# Und der Ort MUSS in .gitignore stehen: 58 Pakete im oeffentlichen Repo wuerden
# bei jedem `git clone --depth 1` des Auftrags mitkommen.
ignore = (WURZEL / ".gitignore").read_text(encoding="utf-8")
check("data/node_modules/ steht in .gitignore", "data/node_modules/" in ignore)
check("und der npm-Cache ebenfalls", "data/.npm-cache/" in ignore)

# ══════════════════════════════════════════════════════════════════════════
abschnitt("2) Eine gesetzte Umgebungsvariable gewinnt")
# ══════════════════════════════════════════════════════════════════════════
with tempfile.TemporaryDirectory() as tmp:
    eigen = Path(tmp) / "meinjsdom"
    eigen.mkdir()
    (eigen / "package.json").write_text("{}", encoding="utf-8")
    alt = os.environ.get("JSDOM_PATH")
    os.environ["JSDOM_PATH"] = str(eigen)
    try:
        check("JSDOM_PATH steht an erster Stelle", jb._orte()[0] == eigen,
              str(jb._orte()[0]))
        check("und pfad() liefert genau diesen Ort", jb.pfad() == str(eigen),
              jb.pfad())
        # Ein gesetzter, aber LEERER Ort darf nicht als vorhanden gelten.
        os.environ["JSDOM_PATH"] = str(Path(tmp) / "gibtsnicht")
        check("ein Ort ohne package.json zaehlt nicht",
              jb.pfad() != str(Path(tmp) / "gibtsnicht"), jb.pfad())
    finally:
        if alt is None:
            os.environ.pop("JSDOM_PATH", None)
        else:
            os.environ["JSDOM_PATH"] = alt

# ══════════════════════════════════════════════════════════════════════════
abschnitt("3) Die Automatik ist abschaltbar – und eine FUNKTION")
# ══════════════════════════════════════════════════════════════════════════
alt = os.environ.get("JARVIS_JSDOM_AUTO")
try:
    os.environ.pop("JARVIS_JSDOM_AUTO", None)
    check("Vorgabe ist AN", jb.automatik_an() is True)
    os.environ["JARVIS_JSDOM_AUTO"] = "0"
    check("JARVIS_JSDOM_AUTO=0 schaltet sie aus", jb.automatik_an() is False)
    os.environ["JARVIS_JSDOM_AUTO"] = "1"
    check("und 1 wieder an", jb.automatik_an() is True)
finally:
    if alt is None:
        os.environ.pop("JARVIS_JSDOM_AUTO", None)
    else:
        os.environ["JARVIS_JSDOM_AUTO"] = alt
# Eine Modulkonstante waere bis zum Dienstneustart wirkungslos (Register).
quelle = (WURZEL / "backend" / "jsdom_bereit.py").read_text(encoding="utf-8")
check("automatik_an ist eine Funktion, keine Konstante",
      "def automatik_an" in quelle and not re.search(r"^JARVIS_JSDOM_AUTO\s*=", quelle, re.M))

# ══════════════════════════════════════════════════════════════════════════
abschnitt("4) sicherstellen() meldet nur bei einem Problem")
# ══════════════════════════════════════════════════════════════════════════
# Eine Zeile bei jedem Start, die immer dasselbe sagt, wird nach zwei Tagen
# nicht mehr gelesen.
if jb.vorhanden():
    check("bei vorhandenem jsdom bleibt es still", jb.sicherstellen() == "",
          jb.sicherstellen())
else:
    check("(uebersprungen: hier liegt kein jsdom)", True)
check("bericht() sagt in JEDEM Fall etwas", bool(jb.bericht()))

# Abgeschaltete Automatik + fehlendes jsdom = Meldung, KEINE Installation.
alt_a = os.environ.get("JARVIS_JSDOM_AUTO")
alt_p = os.environ.get("JSDOM_PATH")
try:
    os.environ["JARVIS_JSDOM_AUTO"] = "0"
    with tempfile.TemporaryDirectory() as tmp:
        os.environ["JSDOM_PATH"] = str(Path(tmp) / "leer")
        echtes_ziel, echte_wurzel = jb.ZIEL, jb.WURZEL
        jb.ZIEL = Path(tmp) / "ziel"          # nichts am echten Baum anfassen
        # ⚠ AUCH DIE WURZEL UMBIEGEN. Sonst findet `_orte()` das jsdom im
        # node_modules des Entwicklungsrechners, `vorhanden()` ist True und
        # sicherstellen() meldet nichts – der Test prueste dann die falsche
        # Lage und war rot, ohne dass am Code etwas fehlte.
        jb.WURZEL = Path(tmp) / "kein-repo"
        try:
            text = jb.sicherstellen()
            check("ohne Automatik: Meldung statt Installation",
                  "JARVIS_JSDOM_AUTO=0" in text, text)
            check("und nichts wurde angelegt", not (Path(tmp) / "ziel").exists())
        finally:
            jb.ZIEL, jb.WURZEL = echtes_ziel, echte_wurzel
finally:
    for k, v in (("JARVIS_JSDOM_AUTO", alt_a), ("JSDOM_PATH", alt_p)):
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v

# ══════════════════════════════════════════════════════════════════════════
abschnitt("5) Der Riegel-Lauf gibt JSDOM_PATH weiter (Punkt 2)")
# ══════════════════════════════════════════════════════════════════════════
# Geprueft am Syntaxbaum, nicht per Textsuche: `riegel_laufen` muss den Wert
# WIRKLICH an `_lauf` uebergeben – ein `pfad()`-Aufruf ohne Weitergabe waere
# wirkungslos und im Quelltext nicht von der richtigen Fassung zu unterscheiden.
cs = (WURZEL / "backend" / "claude_subagent.py").read_text(encoding="utf-8")
baum = ast.parse(cs)
fn = next((n for n in ast.walk(baum)
           if isinstance(n, ast.FunctionDef) and n.name == "riegel_laufen"), None)
check("riegel_laufen existiert", fn is not None)
if fn:
    rumpf = ast.get_source_segment(cs, fn) or ""
    check("es fragt jsdom_bereit.pfad()", "jsdom_bereit" in rumpf and "pfad()" in rumpf)
    check("setzt JSDOM_PATH", "JSDOM_PATH" in rumpf)
    check("und gibt es an _lauf weiter", re.search(r"_lauf\(.*zusatz=", rumpf, re.S) is not None)
    check("nur fuer JS-Riegel (ein Python-Test braucht kein jsdom)",
          'riegel.endswith(".py")' in rumpf)
# _lauf muss den Zusatz auch anwenden - sonst ginge er ins Leere.
fl = next((n for n in ast.walk(baum)
           if isinstance(n, ast.FunctionDef) and n.name == "_lauf"), None)
check("_lauf nimmt zusatz an", fl is not None and any(
    a.arg == "zusatz" for a in (fl.args.args if fl else [])))
if fl:
    check("und mischt ihn in die Umgebung",
          "**(zusatz or {})" in (ast.get_source_segment(cs, fl) or ""))

# ══════════════════════════════════════════════════════════════════════════
abschnitt("6) Der Start stellt es bereit – auf JEDER Installation")
# ══════════════════════════════════════════════════════════════════════════
mn = (WURZEL / "backend" / "main.py").read_text(encoding="utf-8")
check("es gibt einen Startup-Hook", "async def startup_jsdom" in mn)
hook = mn[mn.find("async def startup_jsdom"):][:1800]
check("er ruft sicherstellen()", "jsdom_bereit.sicherstellen" in hook)
check("im HINTERGRUND (der Start darf nicht warten)", "create_task" in hook)
check("und in einem Thread (npm ist blockierend)", "to_thread" in hook)
check("mit Verzoegerung, damit die Oberflaeche zuerst steht",
      "asyncio.sleep" in hook)
# An keine Freigabe gekoppelt: der Betreiber hat Installationen ohne Zugriff,
# dort soll es auch ohne freigeschaltete Delegation vorhanden sein.
check("nicht an eine Bereichs-Freigabe gekoppelt",
      "claudesub" not in hook and "allowed_users" not in hook)

# ══════════════════════════════════════════════════════════════════════════
abschnitt("7) Die Fassung ist festgenagelt – und LADBARKEIT wird geprueft")
# ══════════════════════════════════════════════════════════════════════════
# ⚠ DER TEUERSTE FUND DES TAGES: `npm install jsdom` zog Fassung 30.0.1, deren
# engines `^22.22.2 || ^24.15.0 || >=26.0.0` verlangt. Auf dem Server laeuft
# Node v20.19.2 – die Installation MELDETE ERFOLG, und `require` warf danach
# "webidl.util.markAsUncloneable is not a function". Der Riegel uebersprang
# seinen jsdom-Abschnitt und war gruen, OHNE etwas zu pruefen.
check("das Paket ist auf eine Fassung festgenagelt",
      "@" in jb.PAKET and jb.PAKET.split("@")[-1][0].isdigit(), jb.PAKET)
check("und auf eine, die Node 18+ genuegt (jsdom 25)",
      jb.PAKET.startswith("jsdom@25"), jb.PAKET)
check("installieren() benutzt PAKET, nicht 'jsdom'",
      "PAKET]" in quelle and '"jsdom"]' not in quelle)
# Der Kern: eine daliegende package.json ist KEIN Nachweis.
check("es gibt eine Ladbarkeits-Pruefung", hasattr(jb, "lauffaehig"))
check("sicherstellen() entscheidet an der LADBARKEIT, nicht am Dateisystem",
      "if lauffaehig():" in quelle)
check("installieren() prueft nach dem npm-Lauf ebenfalls die Ladbarkeit",
      "or not lauffaehig()" in quelle)
with tempfile.TemporaryDirectory() as tmp:
    # Eine Attrappe mit package.json, die sich NICHT laden laesst.
    fake = Path(tmp) / "jsdom"
    fake.mkdir()
    (fake / "package.json").write_text('{"name":"jsdom","main":"index.js"}',
                                       encoding="utf-8")
    (fake / "index.js").write_text("throw new Error('kaputt');", encoding="utf-8")
    check("eine nicht ladbare Attrappe gilt als vorhanden …",
          (fake / "package.json").is_file())
    check("… wird aber NICHT als lauffaehig gemeldet",
          jb.lauffaehig(str(fake)) is False)
    # Und ein Paket ohne JSDOM-Export ebenfalls nicht.
    (fake / "index.js").write_text("module.exports = {};", encoding="utf-8")
    check("ein Paket ohne JSDOM-Export ebenfalls nicht",
          jb.lauffaehig(str(fake)) is False)

print(f"\n{'═' * 52}")
print(f"Ergebnis: {_ok}/{_ok + _fail} bestanden")
sys.exit(0 if _fail == 0 else 1)
