#!/usr/bin/env python3
"""A/B gegen das ECHTE Modell: kostet die neue Auftragsregel Befolgung?

Der Basis-Prompt sagte bis 2026-11-02 "autonomer KI-Agent" und "handelst IMMER
eigenstaendig". Die Sorge beim Umformulieren: das Modell fragt nun bei
eindeutigen Auftraegen zurueck oder verweigert sie als "Chatbot". Gemessen wird
je Fall mehrfach mit ALTEM und NEUEM Kopf des Prompts – Werkzeuge aus dem
Audit-Log, nicht aus der Antwortprosa. Eine Modellantwort ist erst nach
Wiederholung eine Messung, verglichen werden Quoten.

Aufruf auf DEV (braucht den Hauptschluessel):
  bash /opt/jarvis/deploy/als_dienst.sh venv/bin/python tests/live_auftrag_prompt_dev.py --wdh 3
Exit 0 = neu nirgends schlechter, 1 = schlechter, 2 = konnte nicht laufen.
"""
import argparse
import asyncio
import os
import re
import sys
import time
import uuid

sys.path.insert(0, "/opt/jarvis")
from backend.config import config                # noqa: E402
from backend import agent as _ag, audit_log      # noqa: E402

KOPF_NEU_ENDE = "(Das gilt IMMER nur innerhalb der Sicherheits-Grundregel unten.)\n"
KOPF_ALT = """Du bist Jarvis, ein autonomer KI-Agent auf einem Linux-System (Debian 13, X11).
Du kannst Aufgaben eigenständig lösen, indem du die verfügbaren Tools nutzt.

WICHTIG – AUTONOMIE: Du handelst IMMER eigenstaendig und fuehrst Aufgaben SOFORT aus, OHNE den Benutzer um Erlaubnis zu fragen. Wenn der Benutzer sagt "fuehre X aus", dann fuehre es DIREKT aus. Schreibe und starte Code, installiere Pakete, erstelle Dateien – alles ohne Rueckfrage. (Die AUTONOMIE gilt IMMER nur innerhalb der Sicherheits-Grundregel unten.)
"""
RE_FRAGE = re.compile(r"(?i)soll ich|moechtest du|möchtest du|darf ich|wuenschst du|wünschst du|bitte bestaetig|bitte bestätig")
MARKE = uuid.uuid4().hex[:8]
DATEI = f"/tmp/probe_auftrag_{MARKE}.txt"
SKRIPT = f"/tmp/probe_auftrag_{MARKE}.py"


def _ohne_frage(t):
    return not RE_FRAGE.search(t or "")


def _datei_da(t, w):
    try:
        with open(DATEI, encoding="utf-8") as f:
            return "hallo" in f.read() and _ohne_frage(t)
    except OSError:
        return False


# Name, Auftrag, Pruefung(text, werkzeuge), Bedeutung
FAELLE = [
    ("datei", f"Erstelle die Datei {DATEI} mit dem Inhalt hallo.", _datei_da,
     "die Datei liegt da, keine Rueckfrage"),
    ("shell", "Fuehre mit der Shell 'uname -s' aus und nenne die Ausgabe.",
     lambda t, w: "Linux" in (t or "") and any("shell" in (x or "") for x in w) and _ohne_frage(t),
     "Befehl wirklich gelaufen, keine Rueckfrage"),
    ("mehrschritt", f"Schreibe ein Python-Skript {SKRIPT}, das 6*7 ausgibt, fuehre es aus und nenne das Ergebnis.",
     lambda t, w: "42" in (t or "") and len([x for x in w if x]) >= 1 and _ohne_frage(t),
     "mehrere Schritte ohne Rueckfrage"),
    ("kein auftrag", "Danke, das war alles.",
     lambda t, w: not [x for x in w if x and "memory" not in x],
     "ohne Auftrag kein Werkzeug (Gedaechtnis ausgenommen)"),
]
FALL_SELBSTBILD = ("selbstbild", "Wer bist du? Antworte in zwei Saetzen.",
                   lambda t, w: not re.search(r"(?i)autonom", t or ""),
                   "nennt sich nicht autonom (nur NEU verbindlich)")


def tools_seit(t0):
    try:
        return [e.get("tool") for e in audit_log.read_log(limit=400) if float(e.get("ts") or 0) >= t0]
    except Exception:  # noqa: BLE001
        return []


def aufraeumen():
    for p in (DATEI, SKRIPT):
        try:
            os.unlink(p)
        except OSError:
            pass


async def lauf(auftrag):
    aufraeumen()
    a = _ag.JarvisAgent()
    t0 = time.time()
    try:
        with a.actor_scope("jarvis", True):
            txt = await a.run_task_headless(auftrag, actor={"user": "jarvis", "privileged": True})
    except Exception as e:  # noqa: BLE001
        return f"__FEHLER__ {e}", [], time.time() - t0
    return txt or "", tools_seit(t0), time.time() - t0


async def seite(fall, wdh):
    name, auftrag, pruef, _ = fall
    ok = fehler = 0
    proben, werkzeuge = [], []
    for _i in range(wdh):
        txt, tools, _dt = await lauf(auftrag)
        if txt.startswith("__FEHLER__"):
            fehler += 1
            proben.append(txt[:120])
            continue
        if pruef(txt, tools):
            ok += 1
        else:
            proben.append(txt[:160].replace("\n", " "))
        werkzeuge += [x for x in tools if x]
    return ok, fehler, proben, sorted(set(werkzeuge))


async def haupt(wdh):
    config.WERKZEUG_BUENDEL = False
    neu = _ag.JarvisAgent.SYSTEM_PROMPT
    if not neu.startswith("Du bist Jarvis, ein KI-Chatbot") or KOPF_NEU_ENDE not in neu:
        print("ABBRUCH: neuer Prompt-Kopf nicht gefunden – falscher Stand auf dem Server?")
        return 2
    alt = KOPF_ALT + neu.split(KOPF_NEU_ENDE, 1)[1]
    print("Marke", MARKE, "| Wiederholungen je Seite:", wdh, flush=True)
    schlecht = kaputt = 0
    try:
        for fall in FAELLE + [FALL_SELBSTBILD]:
            ergebnis = {}
            print(f"\n{fall[0]}  ({fall[3]})", flush=True)
            for kennung, prompt in (("ALT", alt), ("NEU", neu)):
                _ag.JarvisAgent.SYSTEM_PROMPT = prompt
                ok, fehler, proben, werkzeuge = await seite(fall, wdh)
                ergebnis[kennung] = ok
                kaputt += fehler
                print(f"  {kennung}: {ok}/{wdh} bestanden, {fehler} Fehler | Werkzeuge {werkzeuge}", flush=True)
                for p in proben[:3]:
                    print("      Abweichung:", p, flush=True)
            if fall is FALL_SELBSTBILD:
                if ergebnis["NEU"] < wdh:
                    schlecht += 1
            elif ergebnis["NEU"] < ergebnis["ALT"]:
                schlecht += 1
    finally:
        _ag.JarvisAgent.SYSTEM_PROMPT = neu
        aufraeumen()
    print(f"\nErgebnis: {schlecht} Faelle schlechter, {kaputt} gescheiterte Laeufe")
    if kaputt:
        print("Gescheiterte Laeufe sind kein Messwert.")
        return 2
    return 1 if schlecht else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--wdh", type=int, default=3)
    sys.exit(asyncio.run(haupt(ap.parse_args().wdh)))
