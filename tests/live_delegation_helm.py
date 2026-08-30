#!/usr/bin/env python3
"""LIVE-A/B: delegiert das Modell bei einem AENDERUNGSWUNSCH vollstaendig?

DER VORFALL (ECHT, 2026-08-30): auf "setzte der Kuh einen silbernen Helm auf"
delegierte das Modell "Generiere ein kleines, fotorealistisches Bild einer
gruenen Kuh" - OHNE den Helm. Die Rolle sieht das Gespraech nicht.

Gemessen wird der ECHTE function_call: enthaelt die delegierte Aufgabe den
Helm UND die Kuh? Einmal mit der alten, einmal mit der neuen Beschreibung.

Ein gescheiterter Aufruf ist KEIN Messwert -> Exit 2.
Exit 0 = neu nicht schlechter, 1 = FAIL, 2 = konnte nicht laufen.
"""
import asyncio, json, sys
sys.path.insert(0, "/opt/jarvis")
from google.genai import types                # noqa: E402
from backend.llm import get_provider          # noqa: E402

ALT = ("Die vollstaendige Teilaufgabe fuer die Rolle. Muss ohne "
       "Gespraechskontext verstaendlich sein (Dateipfade, Zahlen, "
       "Rahmenbedingungen mitgeben).")

NEU = ("Die vollstaendige Teilaufgabe fuer die Rolle. Muss ohne "
       "Gespraechskontext verstaendlich sein (Dateipfade, Zahlen, "
       "Rahmenbedingungen mitgeben). "
       "AENDERUNGSWUNSCH ZU EINEM FRUEHEREN ERGEBNIS: beschreibe "
       "das ERGEBNIS VOLLSTAENDIG NEU - die alte Beschreibung PLUS "
       "die Aenderung. Die Rolle sieht das Gespraech NICHT und kennt "
       "das vorherige Ergebnis nicht; sie beginnt bei null. Aus "
       "'setz der Kuh einen Helm auf' wird also "
       "'gruene Kuh mit roten Hoernern UND einem silbernen Helm, "
       "fotorealistisch' - NIEMALS nur die alte Beschreibung ohne "
       "die Aenderung und niemals nur die Aenderung allein.")

SYS = ("Du bist Jarvis. Fuer Bilder delegierst du an die Rolle 'image_builder' "
       "mit dem Werkzeug 'delegate'. Rufe das Werkzeug auf.")

N = int(sys.argv[1]) if len(sys.argv) > 1 else 5


class _Werkzeug:
    """Werkzeug im Format, das der Provider erwartet: ein OBJEKT mit
    `parameters_schema()`, kein dict (llm.py liest `t.parameters_schema()`)."""

    name = "delegate"
    description = "Gibt eine Teilaufgabe an eine spezialisierte Rolle ab."

    def __init__(self, beschr):
        self._beschr = beschr

    def parameters_schema(self):
        return {"type": "OBJECT",
                "properties": {
                    "role": {"type": "STRING", "enum": ["image_builder"]},
                    "task": {"type": "STRING", "description": self._beschr}},
                "required": ["role", "task"]}


def werkzeug(beschr):
    return [_Werkzeug(beschr)]


def c(rolle, text):
    return types.Content(role=rolle, parts=[types.Part.from_text(text=text)])


def _verlauf(kaputt):
    """kaputt=True stellt den ECHT-Zustand nach: eine unbeantwortete Frage aus
    einem frueheren Lauf steht noch im Kontext (die 'Maus'), gefolgt von der
    naechsten Frage. Genau das lag auf ECHT vor, als der Helm verlorenging."""
    v = []
    if kaputt:
        v.append(c("user", "generiere ein 300 auf 300 Pixel Comic Bild einer schnell rennenden Maus"))
    v += [
        c("user", "generiere ein kleines, fotorealistisches Bild einer gruenen Kuh mit roten Hoernern"),
        c("model", "Hier ist das Bild der gruenen Kuh mit roten Hoernern."),
        c("user", "setzte der Kuh einen silbernen Helm auf"),
    ]
    return v


async def einmal(prov, modell, beschr, kaputt=False):
    verlauf = _verlauf(kaputt)
    r = await prov.generate_response(modell, SYS, verlauf, tools=werkzeug(beschr))
    for p in (getattr(r, "parts", None) or []):
        fc = getattr(p, "function_call", None)
        if fc is not None:
            args = getattr(fc, "args", None) or {}
            if isinstance(args, str):
                args = json.loads(args)
            return str(args.get("task", ""))
    return "<<KEIN WERKZEUGAUFRUF>> " + (getattr(r, "text", "") or "")[:80]


async def main():
    d = json.load(open("/opt/jarvis/data/settings.json"))
    aktiv = d.get("active_profile_id")
    profs = d.get("profiles") or []
    p = next((x for x in profs if x.get("id") == aktiv), None) or (profs[0] if profs else None)
    if not p:
        print("KONNTE NICHT LAUFEN: kein Profil"); return 2
    prov = get_provider(p.get("provider") or "openai_compatible", p.get("api_key") or "",
                        p.get("api_url"), auth_method=p.get("auth_method") or "api_key",
                        session_key=p.get("session_key"),
                        prompt_tool_calling=bool(p.get("prompt_tool_calling")))
    modell = p.get("model")
    print(f"  Modell: {modell!r}  Laeufe je Variante: {N}\n")
    erg = {}
    for name, beschr, kaputt in (("ALT/sauber", ALT, False), ("NEU/sauber", NEU, False),
                                 ("ALT/KAPUTT", ALT, True), ("NEU/KAPUTT", NEU, True)):
        gut = 0
        for i in range(N):
            try:
                t = await einmal(prov, modell, beschr, kaputt)
            except Exception as e:
                print(f"KONNTE NICHT LAUFEN: Modellaufruf scheiterte: {type(e).__name__}: {e}")
                return 2
            tl = t.lower()
            ok = ("helm" in tl) and ("kuh" in tl)
            gut += ok
            print(f"    {name} {i+1}: {'VOLLSTAENDIG' if ok else 'UNVOLLSTAENDIG':14} {t[:78]!r}")
        erg[name] = gut
        print()
    for k, v in erg.items():
        print(f"  {k:12}: {v}/{N} enthalten Kuh UND Helm")
    ok = (erg["NEU/sauber"] >= erg["ALT/sauber"]
          and erg["NEU/KAPUTT"] >= erg["ALT/KAPUTT"])
    print(f"\n  -> {'BESTANDEN' if ok else 'FAIL'}: die neue Beschreibung ist nirgends schlechter")
    if erg["ALT/KAPUTT"] < erg["ALT/sauber"]:
        print("  BEFUND: der verunreinigte Kontext senkt die Trefferquote -> "
              "die Kontext-Heilung ist der eigentliche Hebel.")
    return 0 if ok else 1


sys.exit(asyncio.run(main()))
