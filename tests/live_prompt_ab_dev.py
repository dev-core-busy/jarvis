#!/usr/bin/env python3
"""A/B gegen das ECHTE Modell: kostet der Prompt-Zuschnitt Befolgungsqualitaet?

⚠ DAS IST DIE BEDINGUNG, UNTER DER GESTRICHEN WIRD ("streichen nur gegen
Messung", Vorgabe 2026-09-06). Jede Regel im Basis-Prompt ist im Zweifel von
einem Vorfall bezahlt; sie wegzulassen, weil sie lang ist, waere geraten.

Gemessen wird je Aufgabe n-mal mit VOLLEM und n-mal mit ZUGESCHNITTENEM Prompt:
  - welche Werkzeuge wurden gerufen (Audit-Log, nicht Antwortprosa),
  - kam ein verwertbares Ergebnis,
  - haelt die Aufgabe ihre Pruefbedingung ein.
Eine Modellantwort ist erst nach WIEDERHOLUNG eine Messung (Register): jede
Seite laeuft mindestens WDH mal, verglichen werden Quoten - nie Einzellaeufe.
"""
import argparse, asyncio, json, sys, time

sys.path.insert(0, "/opt/jarvis")
from backend.config import config
from backend import agent as _ag, audit_log

WDH = 5

# Je Fall: (Auftrag, Pruefung(text, tools) -> bool, Was die Pruefung bedeutet)
FAELLE = [
    ("bild/Punkt 16+20 entfallen",
     "Erstelle eine Excel-Arbeitsmappe mit der Spalte 'Monat' und den Werten "
     "Januar, Februar, Maerz.",
     lambda t, w: any("office" in (x or "") or "xlsx" in (x or "") for x in w),
     "Office-Weg trotz Zuschnitt gefunden"),
    ("dokument/Hausvorlage",
     "Erstelle eine Praesentation mit zwei Folien ueber Netzwerksicherheit.",
     lambda t, w: any("powerpoint" in (x or "") for x in w),
     "office_create_powerpoint statt python-pptx von Hand"),
    ("allgemein/keine Regel verloren",
     "Nenne mir in einem Satz, was du gerade fuer eine Uhrzeit hast.",
     lambda t, w: len((t or "").strip()) > 5,
     "der Zeit-Hinweis ueberlebt den Zuschnitt"),
]


def tools_seit(t0):
    try:
        return [e.get("tool") for e in audit_log.read_log(limit=400)
                if float(e.get("ts") or 0) >= t0]
    except Exception:
        return []


async def lauf(auftrag, zuschnitt):
    config.WERKZEUG_BUENDEL = zuschnitt
    a = _ag.JarvisAgent()
    t0 = time.time()
    try:
        with a.actor_scope("jarvis", True):
            txt = await a.run_task_headless(
                auftrag, actor={"user": "jarvis", "privileged": True})
    except Exception as e:                                     # noqa: BLE001
        return f"__FEHLER__ {e}", [], 0.0, 0
    dt = time.time() - t0
    # Prompt-Groesse dieses Laufs - die eigentliche Ersparnis
    a._current_task = auftrag
    return txt or "", tools_seit(t0), dt, len(a._base_system_prompt())


async def haupt(wdh):
    print(f"A/B je {wdh} Laeufe. A = voller Prompt, B = zugeschnitten.\n")
    schlecht = 0
    for name, auftrag, pruef, bedeutung in FAELLE:
        print(f"\033[1m{name}\033[0m  ({bedeutung})")
        zeile = {}
        for kennung, zu in (("A voll      ", False), ("B zugeschn. ", True)):
            ok = 0
            dauer, groesse, alle_tools = [], [], []
            for _ in range(wdh):
                txt, tools, dt, pl = await lauf(auftrag, zu)
                if not txt.startswith("__FEHLER__") and pruef(txt, tools):
                    ok += 1
                dauer.append(dt); groesse.append(pl); alle_tools += tools
            m = sorted(dauer)[len(dauer) // 2]
            zeile[kennung.strip()] = ok
            print(f"  {kennung}: {ok}/{wdh} bestanden | median {m:5.1f}s "
                  f"| Prompt {groesse[0]:6d} Z. | Werkzeuge: "
                  f"{sorted(set(x for x in alle_tools if x))}")
        a_ok, b_ok = zeile["A voll"], zeile["B zugeschn."]
        # ⚠ Das Urteil ist eine QUOTE, kein Einzellauf. Schlechter heisst: der
        # Zuschnitt hat etwas gekostet - dann wird NICHT gestrichen.
        if b_ok < a_ok:
            print(f"  \033[31m✗ der Zuschnitt kostet Befolgung ({b_ok} < {a_ok})"
                  f" - NICHT streichen\033[0m")
            schlecht += 1
        else:
            print(f"  \033[32m✓ kein Verlust ({b_ok} >= {a_ok})\033[0m")
        print()
    config.WERKZEUG_BUENDEL = False
    print(f"\033[1mErgebnis: {len(FAELLE) - schlecht}/{len(FAELLE)} Faelle ohne Verlust\033[0m")
    return 1 if schlecht else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--wdh", type=int, default=WDH)
    sys.exit(asyncio.run(haupt(ap.parse_args().wdh)))
