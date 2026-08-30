#!/usr/bin/env python3
"""Waechter: was beim Komprimieren aus dem Kontext faellt, wird BENANNT.

DER BEFUND (live auf DEV gemessen, 2026-08-29): ein hochgeladenes Bild liegt als
`inline_data`-Part im Verlauf. `_compress_history` baut die Zusammenfassung aber
nur aus `text`, `function_call` und `function_response` – ein inline-Part traegt
NICHTS bei und wird mit dem Rest des Abschnitts ersetzt.

Gemessen in einer echten Sitzung (Schwellwert 6, Bild im ersten Zug):
  * `data/chats/jarvis/<sid>/context.json` danach: **0 inline_data-Parts**
  * der Zusammenfassungs-Eintrag erwaehnt den Anhang mit keinem Wort
  * auf die Frage nach dem Bild: „Mir liegt aktuell **kein Bild** vor."

Das Modell erfindet also nichts – es bestreitet, dass je eines da war. Aus Sicht
des Benutzers, dessen eigene Sprechblase den Anhang weiter zeigt, ist das der
schlimmere Ausgang.

Dieser Test fuehrt `_compress_history` WIRKLICH aus (per `ast` aus
`backend/agent.py` geschnitten – ein Import von `backend.agent` zieht
`backend.config` und schriebe die Live-settings.json zurueck).

Exit 0 = bestanden · 1 = FAIL · 2 = konnte nicht laufen.
"""

import ast
import asyncio
import json
import re
import sys
import textwrap
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
AGENT_PY = WURZEL / "backend" / "agent.py"

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


if not AGENT_PY.exists():
    abbruch(f"{AGENT_PY} fehlt")

QUELLE = AGENT_PY.read_text(encoding="utf-8")
ZEILEN = QUELLE.splitlines()
BAUM = ast.parse(QUELLE)


def _segment(node) -> str:
    """Quelltext eines Knotens INKLUSIVE Dekoratoren – `get_source_segment`
    beginnt beim `def`, ein @classmethod ginge dabei verloren."""
    start = node.lineno
    for dec in getattr(node, "decorator_list", []):
        start = min(start, dec.lineno)
    return textwrap.dedent("\n".join(ZEILEN[start - 1:node.end_lineno]))


AGENT_KLS = next((n for n in ast.walk(BAUM)
                  if isinstance(n, ast.ClassDef) and n.name == "JarvisAgent"), None)
if AGENT_KLS is None:
    abbruch("Klasse JarvisAgent nicht gefunden")


def _methode(name):
    for n in AGENT_KLS.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    return None


# ACHTUNG: wer eine Methode in diese Kette einhaengt, MUSS sie hier eintragen –
# sonst fehlt sie in der Attrappe und der AttributeError sieht wie ein Codefehler
# aus. (Register; im Nachbarwaechter test_bilddaten_bergen.py schon einmal
# passiert.)
_METHODEN = ("_verworfene_anhaenge", "_compress_history")
for _m in _METHODEN:
    if _methode(_m) is None:
        abbruch(f"Methode {_m} fehlt in JarvisAgent – Fix nicht vorhanden?")

# Klassen-Attribute NICHT einzeln aufzaehlen: eine gepflegte Liste laeuft beim
# naechsten neuen Wert auseinander, und der Fehler sieht dann wie ein Codefehler
# aus (AttributeError tief in der Methode).
_ATTR_NAMEN = ("_ANHANG_MARKE_RE", "_NOTIZ_KOPF", "_NOTIZ_TRENNER")
_ATTRIBUTE = [_segment(n) for n in AGENT_KLS.body
              if isinstance(n, ast.Assign)
              and any(getattr(z, "id", "") in _ATTR_NAMEN for z in n.targets)]
if len(_ATTRIBUTE) < len(_ATTR_NAMEN):
    abbruch(f"nur {len(_ATTRIBUTE)} von {len(_ATTR_NAMEN)} Klassen-Attributen "
            f"gefunden – Fix nicht vorhanden?")


# ── Attrappen fuer google.genai.types ────────────────────────────────────────
class Part:
    def __init__(self, text=None, inline_data=None, function_call=None,
                 function_response=None):
        self.text = text
        self.inline_data = inline_data
        self.function_call = function_call
        self.function_response = function_response

    @staticmethod
    def from_text(text=None):
        return Part(text=text)


class Content:
    def __init__(self, role="user", parts=None):
        self.role = role
        self.parts = list(parts or [])


class Blob:
    def __init__(self, mime_type, data):
        self.mime_type = mime_type
        self.data = data


class _Types:
    Part = Part
    Content = Content


class Provider:
    """Attrappe des LLM. `fehler=True` stellt den Ausfall der Zusammenfassung nach."""

    def __init__(self, fehler=False, text="Zusammenfassung des Abschnitts."):
        self.fehler, self.text, self.gesehen = fehler, text, None

    async def generate_response(self, **kw):
        self.gesehen = kw
        if self.fehler:
            raise RuntimeError("Modell nicht erreichbar")
        return type("R", (), {"parts": [Part(text=self.text)]})()


_ns = {"json": json, "re": re, "types": _Types, "print": lambda *a, **k: None}
exec("class Attrappe:\n    agent_id = 'test'\n    _compress_threshold = 6\n"
     "    current_model = 'm'\n\n"
     + textwrap.indent("\n".join(_ATTRIBUTE), "    ") + "\n\n"
     + "\n\n".join(textwrap.indent(_segment(_methode(m)), "    ") for m in _METHODEN),
     _ns)
Attrappe = _ns["Attrappe"]


def agent(fehler=False):
    a = Attrappe()
    a.provider = Provider(fehler=fehler)
    return a


def bild_eintrag(name="muster.png", mime="image/png", bytes_=6000, marke=True):
    teile = [Part(text="Schau dir das an.")]
    if marke:
        teile.append(Part(text=f"[Anhang: {name} ({mime})]"))
    teile.append(Part(inline_data=Blob(mime, b"x" * bytes_)))
    return Content("user", teile)


def fuellung(n):
    raus = []
    for i in range(n):
        raus.append(Content("model", [Part(text=f"Antwort {i}")]))
        raus.append(Content("user", [Part(text=f"Frage {i}")]))
    return raus


def lauf(verlauf, fehler=False):
    a = agent(fehler)
    return a, asyncio.run(a._compress_history(verlauf, "SYS"))


def text_von(eintrag):
    return " ".join((p.text or "") for p in eintrag.parts if getattr(p, "text", None))


def bilder_in(liste):
    return sum(1 for c in liste for p in c.parts if getattr(p, "inline_data", None))


NOTIZ = "ANHAENGE NICHT MEHR IM KONTEXT"


# ═══════════════════════════════════════════════════════════════════════════
print("1. Der Befund: das Bild ist nach der Komprimierung weg")
verlauf = [bild_eintrag()] + fuellung(8)
pruef(bilder_in(verlauf) == 1, "Testmaterial traegt kein Bild")
a, raus = lauf(verlauf)
pruef(len(raus) < len(verlauf), "es wurde gar nicht komprimiert – Testaufbau falsch")
pruef(bilder_in(raus) == 0,
      "unerwartet: das Bild ueberlebt die Komprimierung (Test veraltet?)")

print("\n2. …und genau deshalb steht jetzt eine Notiz da")
alle = "\n".join(text_von(c) for c in raus)
pruef(NOTIZ in alle, "der Verlust wird nicht benannt")
pruef("muster.png" in alle, "die Notiz nennt den Anhang nicht beim Namen")
pruef("image/png" in alle, "die Notiz nennt den Typ nicht")
pruef(NOTIZ in text_von(raus[0]),
      "die Notiz steht nicht im ERSTEN Eintrag – dahinter kann sie der naechste Schnitt treffen")
pruef(raus[0].role == "user" and (len(raus) < 2 or raus[1].role != "user"),
      "die Notiz erzeugt zwei aufeinanderfolgende user-Eintraege")

print("   …und sie sagt BEIDES: nicht erfinden UND nicht bestreiten")
notiz = text_von(raus[0]).lower()
pruef("erfinde" in notiz, "die Notiz verbietet das Erfinden nicht")
pruef("nie" in notiz and "geschickt" in notiz,
      "die Notiz verbietet nicht, den Anhang ganz zu bestreiten – das war das "
      "gemessene Verhalten ('Mir liegt aktuell kein Bild vor')")
pruef("erneut" in notiz, "die Notiz nennt keinen Ausweg (erneut senden)")
pruef("dateisystem" in notiz,
      "die Notiz verbietet die Suche im Dateisystem nicht – live gemessen ging das "
      "Modell genau dorthin und antwortete 'in keinem Suchpfad gefunden'")

print("\n2b. Die Notiz UEBERLEBT die naechste Komprimierung")
# Sie ist selbst nur Text: beim naechsten Durchgang landet sie im dialog_text
# und wird vom Modell mitzusammengefasst. Live gemessen (2026-08-29): der
# Dateiname ueberlebte, die Aussage "nicht mehr im Kontext" NICHT.
runde1 = raus
pruef(any(NOTIZ in text_von(c) for c in runde1), "Testaufbau: keine Notiz aus Runde 1")
a, runde2 = lauf(list(runde1) + fuellung(6))
alle2 = "\n".join(text_von(c) for c in runde2)
pruef(NOTIZ in alle2, "die Notiz ist nach der zweiten Komprimierung verschwunden")
pruef("muster.png" in alle2, "der Name des Anhangs ging in Runde 2 verloren")
pruef(alle2.count("muster.png (image/png)") == 1,
      f"der Anhang steht doppelt in der Notiz: {alle2[:220]}")

print("   …und drei Runden spaeter immer noch")
a, runde3 = lauf(list(runde2) + fuellung(6))
alle3 = "\n".join(text_von(c) for c in runde3)
pruef(NOTIZ in alle3 and "muster.png" in alle3,
      "nach der dritten Komprimierung ist der Verlust wieder unsichtbar")

print("\n3. Ohne Anhang bleibt alles wie vorher")
a, raus = lauf(fuellung(9))
pruef(all(NOTIZ not in text_von(c) for c in raus),
      "eine Notiz erscheint, obwohl gar kein Anhang verloren ging")
pruef(len(raus) == 5, f"Komprimierung liefert {len(raus)} statt 5 Eintraegen")

print("\n4. Unter dem Schwellwert passiert gar nichts")
klein = [bild_eintrag()] + fuellung(1)
a, raus = lauf(klein)
pruef(raus is klein, "unterhalb des Schwellwerts wird die Liste angefasst")
pruef(bilder_in(raus) == 1, "das Bild ging unterhalb des Schwellwerts verloren")

print("\n5. Ein Bild in den letzten vier Eintraegen BLEIBT – und wird nicht gemeldet")
verlauf = fuellung(8) + [bild_eintrag(name="frisch.png")]
a, raus = lauf(verlauf)
pruef(bilder_in(raus) == 1, "das juengste Bild wurde entfernt, obwohl es geschont wird")
pruef(all(NOTIZ not in text_von(c) for c in raus),
      "Verlust gemeldet, obwohl der Anhang noch da ist – das waere eine Falschaussage")

print("\n6. Abschnitt NUR mit Bild: der Zweig ohne Zusammenfassung")
# `dialog_text` bleibt leer -> frueher `return keep`, der Anhang verschwand dort
# besonders lautlos (kein Modellaufruf, keine Zeile im Journal).
# Ein Abschnitt ganz OHNE Text: nur inline-Parts. Genau dann bleibt
# `dialog_text` leer. Einen Namen kann es hier nicht geben – die Marke waere
# selbst ein Textteil und der Zweig damit nicht mehr erreichbar.
verlauf = ([Content("user", [Part(inline_data=Blob("image/gif", b"z" * 4000))])
            for _ in range(7)] + fuellung(2))
a, raus = lauf(verlauf)
alle = "\n".join(text_von(c) for c in raus)
pruef(a.provider.gesehen is None, "Testaufbau: es wurde doch zusammengefasst")
pruef(NOTIZ in alle, "im Zweig ohne Zusammenfassung fehlt die Notiz")
pruef("image/gif" in alle, "der Anhang fehlt in der Notiz")
pruef("image/gif, 3 KB (7×)" in alle,
      f"die ANZAHL der verworfenen Anhaenge geht verloren: {alle[:200]}")

print("   …und viele Anhaenge werden gedeckelt statt aufgezaehlt")
verlauf = ([Content("user", [Part(text=f"[Anhang: d{i}.png (image/png)]"),
                             Part(inline_data=Blob("image/png", b"z" * 900))])
            for i in range(14)] + fuellung(2))
a, raus = lauf(verlauf)
alle = "\n".join(text_von(c) for c in raus)
pruef("und 6 weitere" in alle, f"kein Deckel bei 14 Anhaengen: {alle[:220]}")
pruef(alle.count("d0.png") == 1 and "d13.png" not in alle,
      "der Deckel schneidet die falschen Eintraege weg")

print("\n7. Faellt die Zusammenfassung aus, bleibt die Notiz trotzdem")
a, raus = lauf([bild_eintrag(name="trotzdem.png")] + fuellung(8), fehler=True)
alle = "\n".join(text_von(c) for c in raus)
pruef(NOTIZ in alle, "nach einem Modellfehler faellt die Notiz mit weg")
pruef("trotzdem.png" in alle, "die Notiz nennt den Anhang nicht")
pruef(len(raus) == 5, f"Rueckfall liefert {len(raus)} statt 4+1 Eintraegen")

print("\n8. Altbestand ohne Marke: Typ und Groesse statt Name")
# Kontexte, die VOR dieser Aenderung gespeichert wurden, haben keine
# `[Anhang: …]`-Marke. Sie duerfen nicht stillschweigend verschwinden.
a, raus = lauf([bild_eintrag(marke=False, mime="application/pdf", bytes_=50000)]
               + fuellung(8))
alle = "\n".join(text_von(c) for c in raus)
pruef(NOTIZ in alle, "ein Anhang ohne Marke wird gar nicht gemeldet")
pruef("application/pdf" in alle, "der Typ fehlt")
pruef(re.search(r"\b4[89] KB\b", alle) is not None,
      f"die Groesse fehlt oder ist falsch: {alle[:200]}")

print("\n9. Mehrere Anhaenge werden alle genannt")
a, raus = lauf([bild_eintrag(name="eins.png"), bild_eintrag(name="zwei.jpg",
                                                           mime="image/jpeg")]
               + fuellung(8))
alle = "\n".join(text_von(c) for c in raus)
pruef("eins.png" in alle and "zwei.jpg" in alle, "nicht alle Anhaenge werden genannt")

print("\n10. DRIFT-SCHRANKE: die Marke aus run_task muss hier erkannt werden")
# Das Format steht an ZWEI Stellen (run_task schreibt es, _verworfene_anhaenge
# liest es). Laufen sie auseinander, verliert die Notiz still den Namen und
# meldet nur noch 'image/png, 12 KB' – ohne dass irgendetwas fehlschlaegt.
_rt = _methode("run_task")
if _rt is None:
    abbruch("run_task nicht gefunden")


def _marken_literale(fn):
    """Rendert jede f-String-Literal-Zeile, die mit '[Anhang:' beginnt."""
    raus = []
    proben = ["muster.png", "image/png", "X", "Y"]
    for k in ast.walk(fn):
        if not isinstance(k, ast.JoinedStr):
            continue
        stueck, i = "", 0
        for teil in k.values:
            if isinstance(teil, ast.Constant):
                stueck += str(teil.value)
            else:
                stueck += proben[i] if i < len(proben) else "?"
                i += 1
        if stueck.startswith("[Anhang:"):
            raus.append(stueck)
    return raus


_marken = _marken_literale(_rt)
pruef(_marken, "run_task legt gar keine [Anhang: …]-Marke an – die Notiz bleibt namenlos")
_re_marke = _ns["Attrappe"]._ANHANG_MARKE_RE
for _m in _marken:
    pruef(_re_marke.match(_m) is not None,
          f"_ANHANG_MARKE_RE erkennt die von run_task geschriebene Marke nicht: {_m!r}")

# …und die Marke muss VOR dem Datenteil stehen: _verworfene_anhaenge paart
# Namen und inline-Parts der Reihe nach.
_rt_q = _segment(_rt)
_i_marke = _rt_q.find("[Anhang:")
_i_bytes = _rt_q.find("from_bytes(data=_att_bytes")
pruef(_i_marke != -1 and _i_bytes != -1 and _i_marke < _i_bytes,
      "die Marke wird NACH dem Datenteil angehaengt – dann passt die Zuordnung nicht")

# ═══════════════════════════════════════════════════════════════════════════
print(f"\n{'=' * 60}\n{_ok} bestanden, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
