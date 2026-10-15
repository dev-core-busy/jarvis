#!/usr/bin/env python3
"""Waechter: EIN Bild wird EINMAL angezeigt, auch bei einer Delegation.

DER VORFALL (ECHT, 2026-08-30): Auf „setze der Kuh einen Helm auf" endete die
Antwort mit ZWEIMAL derselben Zeile:

    ![Bild](/api/generated/cb20b70daaf9e720a7f7591c49b6644e.png)
    ![Bild](/api/generated/cb20b70daaf9e720a7f7591c49b6644e.png)

Identische URL – also kein zweites Bild, sondern dasselbe doppelt. Im Journal
stand dazu passend zweimal dieselbe Auslagerung, aus zwei verschiedenen Agenten:

    [AGENT f93f944a] Bilddaten aus '(verlauf)' ausgelagert            -> …cb20b70d….png
    [AGENT a84e7992] Bilddaten aus 'delegate:image_builder' ausgelagert -> …cb20b70d….png

URSACHE: bei einer Delegation birgt der ROLLEN-Agent die Bilddaten aus seiner
eigenen Antwort und der HAUPT-Agent noch einmal aus dem Werkzeug-Ergebnis. Beide
rufen `record_task_image`, und weil die URL inhaltsadressiert ist (sha256), ist
sie beide Male IDENTISCH. `record_task_image` haengte blind an, und
`_mit_bildern` filterte nur „steht nicht im Text" – zwei identische Eintraege
ueberstehen das beide.

Geprueft wird an BEIDEN Stellen: an der Quelle (`record_task_image` nimmt eine
URL nur einmal) und im Nachtrag (`_mit_bildern` haengt keine URL doppelt an).
Die zweite ist Tiefenverteidigung: ein kuenftiger zweiter Weg in die Liste
wuerde den Fehler sonst neu erzeugen.

Exit 0 = bestanden · 1 = FAIL · 2 = konnte nicht laufen.
"""

import ast
import contextvars
import sys
import textwrap
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
AGENT_PY = WURZEL / "backend" / "agent.py"
IMG_PY = WURZEL / "backend" / "tools" / "image_gen.py"

_ok = 0
_fail = 0


def pruef(bedingung, text):
    global _ok, _fail
    if bedingung:
        _ok += 1
    else:
        _fail += 1
        print(f"  FAIL: {text}")


def abbruch(text):
    print(f"KONNTE NICHT LAUFEN: {text}")
    sys.exit(2)


for _p in (AGENT_PY, IMG_PY):
    if not _p.exists():
        abbruch(f"{_p} fehlt")

A_QUELLE = AGENT_PY.read_text(encoding="utf-8")
A_ZEILEN = A_QUELLE.splitlines()
A_BAUM = ast.parse(A_QUELLE)
I_QUELLE = IMG_PY.read_text(encoding="utf-8")
I_BAUM = ast.parse(I_QUELLE)

URL = "/api/generated/cb20b70daaf9e720a7f7591c49b6644e.png"
URL2 = "/api/generated/8925ebfba91256ec0f9cbefcbf9f0cae.png"


# ═══════════════════════════════════════════════════════════════════════════
print("1. record_task_image: dieselbe URL nur EINMAL (echte Funktion)")

_rti = next((n for n in ast.walk(I_BAUM)
             if isinstance(n, ast.FunctionDef) and n.name == "record_task_image"), None)
if _rti is None:
    abbruch("record_task_image nicht gefunden")

_ns = {"current_task_images": contextvars.ContextVar("t", default=None)}
exec(ast.get_source_segment(I_QUELLE, _rti), _ns)
record = _ns["record_task_image"]

liste = []
_ns["current_task_images"].set(liste)

# Genau der gemeldete Ablauf: Rollen-Agent, dann Hauptagent – dieselbe Datei.
record("/pfad/cb20b70d.png", URL)
record("/pfad/cb20b70d.png", URL)
pruef(len(liste) == 1,
      f"dieselbe URL wurde {len(liste)}x gemerkt – erwartet 1 (der gemeldete Fehler)")

# Ein ANDERES Bild muss weiterhin dazukommen.
record("/pfad/8925ebfb.png", URL2)
pruef(len(liste) == 2, f"ein zweites, anderes Bild fehlt (Liste: {len(liste)})")
pruef([e["url"] for e in liste] == [URL, URL2], "Reihenfolge oder Inhalt falsch")

# Ohne aktiven Task-Kontext darf nichts krachen.
_ns["current_task_images"].set(None)
try:
    record("/pfad/x.png", URL)
    pruef(True, "")
except Exception as e:  # noqa: BLE001
    pruef(False, f"ohne Task-Kontext wirft record_task_image: {e}")


# ═══════════════════════════════════════════════════════════════════════════
print("\n2. _mit_bildern: haengt keine URL doppelt an (echte Methode)")

KLS = next((n for n in ast.walk(A_BAUM)
            if isinstance(n, ast.ClassDef) and n.name == "JarvisAgent"), None)
if KLS is None:
    abbruch("Klasse JarvisAgent nicht gefunden")
_mb = next((n for n in KLS.body
            if isinstance(n, ast.FunctionDef) and n.name == "_mit_bildern"), None)
if _mb is None:
    abbruch("_mit_bildern nicht gefunden")


def _segment(node) -> str:
    start = node.lineno
    for dec in getattr(node, "decorator_list", []):
        start = min(start, dec.lineno)
    return textwrap.dedent("\n".join(A_ZEILEN[start - 1:node.end_lineno]))


# Attrappe fuer den Import INNERHALB der Methode.
import types as _types  # noqa: E402

_cti = contextvars.ContextVar("imgs", default=None)
_mod = _types.ModuleType("backend.tools.image_gen")
_mod.current_task_images = _cti
sys.modules.setdefault("backend", _types.ModuleType("backend"))
sys.modules.setdefault("backend.tools", _types.ModuleType("backend.tools"))
sys.modules["backend.tools.image_gen"] = _mod

_ns2 = {"print": lambda *a, **k: None}
exec("class _A:\n    agent_id = 'test'\n\n" + textwrap.indent(_segment(_mb), "    "), _ns2)
A = _ns2["_A"]()

# (a) DER GEMELDETE FALL: zweimal derselbe Eintrag in der Liste.
_cti.set([{"url": URL, "prompt": "Kuh mit Helm"},
          {"url": URL, "prompt": "Kuh mit Helm"}])
raus = A._mit_bildern("Die Bildgenerierung ist fehlgeschlagen.")
pruef(raus.count(URL) == 1,
      f"die URL steht {raus.count(URL)}x im Text – erwartet 1 (der gemeldete Fehler)")

# (b) Zwei VERSCHIEDENE Bilder muessen beide erscheinen.
_cti.set([{"url": URL, "prompt": "A"}, {"url": URL2, "prompt": "B"}])
raus = A._mit_bildern("Fertig.")
pruef(raus.count(URL) == 1 and raus.count(URL2) == 1,
      f"zwei verschiedene Bilder nicht beide angehaengt: {raus!r}")

# (c) Steht die URL schon im Text, wird sie NICHT nachgetragen.
_cti.set([{"url": URL, "prompt": "A"}, {"url": URL, "prompt": "A"}])
raus = A._mit_bildern(f"Hier: ![Bild]({URL})")
pruef(raus.count(URL) == 1,
      f"bereits genannte URL wurde nachgetragen: {raus.count(URL)}x")

# (d) Ohne Bilder bleibt der Text exakt gleich.
_cti.set([])
pruef(A._mit_bildern("Nur Text.") == "Nur Text.", "Text ohne Bilder wurde veraendert")

# (e) Fail-safe: kaputte Eintraege duerfen nicht werfen.
_cti.set([{"url": None}, {}, {"url": URL}])
try:
    raus = A._mit_bildern("Text.")
    pruef(raus.count(URL) == 1, "gueltiges Bild ging zwischen kaputten Eintraegen verloren")
except Exception as e:  # noqa: BLE001
    pruef(False, f"_mit_bildern wirft bei kaputten Eintraegen: {e}")


# ═══════════════════════════════════════════════════════════════════════════
print("\n3. Die Absicherung steht an BEIDEN Stellen (Quelle und Nachtrag)")


def _ohne_kommentare(text: str) -> str:
    return "\n".join(z for z in text.splitlines() if not z.strip().startswith("#"))


_q_rti = _ohne_kommentare(ast.get_source_segment(I_QUELLE, _rti) or "")
pruef("append" in _q_rti and ("any(" in _q_rti or "url ==" in _q_rti),
      "record_task_image prueft nicht auf eine bereits gemerkte URL")

_q_mb = _ohne_kommentare(_segment(_mb))
pruef("gesehen" in _q_mb or "set(" in _q_mb,
      "_mit_bildern entfernt keine Dubletten – nur die Quelle abzusichern ist die halbe Reparatur")


# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 60}\n{_ok} bestanden, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
