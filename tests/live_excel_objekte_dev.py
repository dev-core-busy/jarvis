#!/usr/bin/env python3
"""Live auf DEV: waehlt das Modell den Objekt-Weg – oder sagt es wieder ab?

Gemessen wird gegen das ECHTE Modell mit dem ECHTEN Prompt und dem ECHTEN
Werkzeug-Schema. Die Gegenprobe faehrt denselben Auftrag mit dem Prompt-Stand
VON VORHER (ohne den Objekt-Abschnitt) – ohne sie waere „es funktioniert" eine
Behauptung ueber eine Aenderung, deren Wirkung niemand gemessen hat.

⚠ MEHRFACH, nicht einmal: eine Modellantwort ist erst nach Wiederholung eine
Messung (Register). Geurteilt wird ueber QUOTEN.

⚠ ALLES IN EINEM asyncio-Loop: der httpx-Client des Providers haengt am ERSTEN
Loop; ein zweites `asyncio.run()` stirbt mit „Event loop is closed", und die
Probe meldet dann „kein Werkzeugaufruf" – ein Messfehler, der wie ein Befund
aussieht.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys

sys.path.insert(0, "/opt/jarvis")

from google.genai import types  # noqa: E402

from backend import excel_ask, llm  # noqa: E402
from backend.tools.excel_vorschlag import ExcelVorschlagTool  # noqa: E402

LAEUFE = 4
AUFTRAG = (
    "Erstelle eine Pivot-Tabelle, die den Umsatz je Region und Quartal "
    "auswertet. Lege sie auf einem neuen Blatt 'Auswertung' an."
)

UEBERBLICK = """### Blatt: Daten (aktiv)
Benutzter Bereich: A1:E201, Kopfzeile Zeile 1, Daten ab Zeile 2
Spalten: A=Region (Text), B=Quartal (Text), C=Produkt (Text),
         D=Menge (Zahl), E=Umsatz (Zahl, Format #,##0.00 €)
Beispielzeilen:
  2: Nord | Q1 | Pumpe | 12 | 4800,00
  3: Sued | Q1 | Ventil | 30 | 2250,00
  4: Nord | Q2 | Pumpe | 18 | 7200,00
Letzte Zeilen:
  201: West | Q4 | Ventil | 9 | 675,00
"""


def werkzeugaufrufe(antwort):
    """Zieht die function_calls aus einer Provider-Antwort – tolerant.

    Die Form unterscheidet sich je Provider; wer nur EINE annimmt, misst bei
    den anderen „kein Aufruf" und haelt das fuer einen Befund.
    """
    raus = []
    for attr in ("parts", "candidates"):
        teil = getattr(antwort, attr, None)
        if not teil:
            continue
        for p in teil:
            fc = getattr(p, "function_call", None)
            if fc is None and hasattr(p, "content"):
                for q in getattr(p.content, "parts", []) or []:
                    fc = getattr(q, "function_call", None) or fc
            if fc is not None:
                args = getattr(fc, "args", None) or {}
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:  # noqa: BLE001
                        args = {}
                raus.append((getattr(fc, "name", "?"), args))
    return raus


def text_von(antwort) -> str:
    t = getattr(antwort, "text", None)
    if t:
        return str(t)
    stuecke = []
    for p in getattr(antwort, "parts", None) or []:
        if getattr(p, "text", None):
            stuecke.append(str(p.text))
    return "\n".join(stuecke)


ABSAGE_RE = re.compile(
    r"nicht m(ö|oe)glich|kann (ich )?(leider )?(keine|nicht)|"
    r"nicht unterst(ü|ue)tzt|steht nicht zur Verf(ü|ue)gung|"
    r"(ü|ue)ber diese Schnittstelle", re.I)


async def einLauf(prompt: str, werkzeug) -> dict:
    # ⚠ DIE SIGNATUR IST ABGESCHRIEBEN, NICHT GERATEN: `provider_fuer_lauf`
    # liefert ein PAAR (provider, model), und `generate_response` nimmt
    # `contents` – nicht `prompt`/`chat_history`. Der erste Anlauf starb an
    # beidem, und ein Aufruf, der nicht stattgefunden hat, ist kein Messwert.
    # Vorbild: agent.py, Zeile ~2642.
    prov, modell = llm.provider_fuer_lauf()
    auftrag = (UEBERBLICK + "\n\nFRAGE DES BENUTZERS:\n" + AUFTRAG)
    antwort = await prov.generate_response(
        model=modell,
        system_prompt=prompt,
        # ⚠ `contents` braucht `types.Content`, keinen String – ein String
        # stirbt mit "'str' object has no attribute 'role'". Steht so im
        # Register; abgeschrieben von agent.py Zeile 2623.
        contents=[types.Content(role="user",
                                parts=[types.Part.from_text(text=auftrag)])],
        tools=[werkzeug],
    )
    rufe = werkzeugaufrufe(antwort)
    txt = text_von(antwort)
    pivot = False
    for name, args in rufe:
        if name != "excel_vorschlag":
            continue
        ae = args.get("aenderungen")
        if isinstance(ae, str):
            try:
                ae = json.loads(ae)
            except Exception:  # noqa: BLE001
                ae = []
        for e in (ae or []):
            if isinstance(e, dict) and str(e.get("typ", "")).lower() == "pivot":
                pivot = True
    return {"pivot": pivot, "rufe": [n for n, _ in rufe],
            "absage": bool(ABSAGE_RE.search(txt)), "text": txt[:200],
            "args": [a for n, a in rufe if n == "excel_vorschlag"]}


async def main() -> int:
    ok = fail = 0

    def check(t, b):
        nonlocal ok, fail
        if b:
            ok += 1
        else:
            fail += 1
            print("  FAIL: " + t)

    neu = excel_ask.rollen_prompt()
    werkzeug = ExcelVorschlagTool()

    # Positivkontrolle des Messaufbaus: ohne sie ist „0 Pivot-Aufrufe" von
    # einem kaputten Aufruf nicht zu unterscheiden.
    check("der neue Prompt nennt den Typ 'pivot'", "typ:\"pivot\"" in neu or "'pivot'" in neu)
    check("das Schema kennt das Feld 'typ'",
          "typ" in werkzeug.parameters_schema()["properties"]["aenderungen"]["items"]["properties"])

    # Der ALTE Prompt: alles ab dem Objekt-Abschnitt abgeschnitten.
    marke = "EXCEL-OBJEKTE: PIVOT, DIAGRAMM, TABELLE, BEDINGTE FORMATIERUNG"
    check("der Objekt-Abschnitt ist im neuen Prompt", marke in neu)
    i = neu.find(marke)
    j = neu.find("WAS DU NICHT TUST")
    alt = (neu[:i] + neu[j:]) if (i > 0 and j > i) else neu

    print("\n── NEUER Prompt (%d Laeufe) ──" % LAEUFE)
    trefferNeu = 0
    eintragNeu = None
    for n in range(LAEUFE):
        try:
            r = await einLauf(neu, werkzeug)
        except Exception as e:  # noqa: BLE001
            print("  ABBRUCH im Lauf %d: %r" % (n + 1, e))
            return 2
        if r["pivot"]:
            trefferNeu += 1
        print("  [%d] pivot=%-5s rufe=%s absage=%s" %
              (n + 1, r["pivot"], r["rufe"] or "-", r["absage"]))
        if r["pivot"] and r["args"] and eintragNeu is None:
            for _a in r["args"]:
                _ae = _a.get("aenderungen")
                if isinstance(_ae, str):
                    _ae = json.loads(_ae)
                for _e in (_ae or []):
                    if isinstance(_e, dict) and str(_e.get("typ","")).lower() == "pivot":
                        eintragNeu = _e
        if r["pivot"] and n == 0 and r["args"]:
            a0 = r["args"][0].get("aenderungen")
            if isinstance(a0, str):
                a0 = json.loads(a0)
            print("      -> " + json.dumps(a0[0], ensure_ascii=False)[:230])

    print("\n── ALTER Prompt (Gegenprobe, %d Laeufe) ──" % LAEUFE)
    trefferAlt = absagenAlt = 0
    for n in range(LAEUFE):
        try:
            r = await einLauf(alt, werkzeug)
        except Exception as e:  # noqa: BLE001
            print("  ABBRUCH im Lauf %d: %r" % (n + 1, e))
            break
        if r["pivot"]:
            trefferAlt += 1
        if r["absage"]:
            absagenAlt += 1
        print("  [%d] pivot=%-5s rufe=%s absage=%s" %
              (n + 1, r["pivot"], r["rufe"] or "-", r["absage"]))
        if r["absage"] and n == 0:
            print("      -> " + r["text"].replace("\n", " ")[:190])

    # ── DER ZUSTAND VON VORHER ────────────────────────────────────────────
    # ⚠ DIE ERSTE GEGENPROBE WAR UNVOLLSTAENDIG: sie nahm nur den
    # Prompt-Abschnitt zurueck – das SCHEMA trug `typ` weiter, und das Modell
    # las es dort. Ergebnis 4/4 fuer beide Varianten, also kein Unterschied
    # messbar. Der gemeldete Zustand braucht BEIDES zurueck.
    class AltesWerkzeug(ExcelVorschlagTool):
        def parameters_schema(self):
            sch = json.loads(json.dumps(ExcelVorschlagTool.parameters_schema(self)))
            props = sch["properties"]["aenderungen"]["items"]["properties"]
            for feld in ("typ", "quelle", "name", "zeilenfelder", "spaltenfelder",
                         "wertfelder", "art", "titel", "kopfzeile", "regel",
                         "operator", "wert2", "farbe", "textfarbe"):
                props.pop(feld, None)
            return sch

    altesWz = AltesWerkzeug()
    check("das alte Schema kennt 'typ' NICHT",
          "typ" not in altesWz.parameters_schema()["properties"]["aenderungen"]["items"]["properties"])
    print("\n── ZUSTAND VON VORHER: alter Prompt UND altes Schema (%d Laeufe) ──"
          % LAEUFE)
    trefferVor = absagenVor = 0
    for n in range(LAEUFE):
        try:
            r = await einLauf(alt, altesWz)
        except Exception as e:  # noqa: BLE001
            print("  ABBRUCH im Lauf %d: %r" % (n + 1, e))
            break
        if r["pivot"]:
            trefferVor += 1
        if r["absage"]:
            absagenVor += 1
        print("  [%d] pivot=%-5s rufe=%s absage=%s" %
              (n + 1, r["pivot"], r["rufe"] or "-", r["absage"]))
        if n == 0 and r["text"]:
            print("      -> " + r["text"].replace("\n", " ")[:190])

    print("\n── Bilanz ──")
    print("  neuer Prompt: %d/%d Laeufe mit Pivot-Eintrag" % (trefferNeu, LAEUFE))
    print("  alter Prompt: %d/%d mit Pivot, %d Absagen" %
          (trefferAlt, LAEUFE, absagenAlt))
    check("der neue Prompt fuehrt mehrheitlich zu einem Pivot-Eintrag",
          trefferNeu > LAEUFE // 2)
    check("der neue Prompt ist nicht schlechter als der alte",
          trefferNeu >= trefferAlt)
    print("  Zustand VORHER: %d/%d mit Pivot, %d Absagen"
          % (trefferVor, LAEUFE, absagenVor))
    # ⚠ BEFUND, DER MEINE ANNAHME WIDERLEGT HAT – und deshalb hier steht:
    # das Modell schickt `typ:"pivot"` AUCH OHNE Schema und ohne Prompt-
    # Abschnitt (4/4). Die Kette war also NICHT am Modell gebrochen, sondern am
    # BACKEND: dieser Eintrag lief dort in die Zell-Pruefung und wurde
    # verworfen. Die belastbare Aussage ist deshalb nicht „das Modell kann es
    # jetzt", sondern „der Eintrag, den das Modell ohnehin liefert, kommt jetzt
    # an". Genau das wird hier gemessen – am ECHTEN Eintrag aus dem Lauf.
    # ⚠ DER EINTRAG AUS DEM NEUEN LAUF, nicht aus der Gegenprobe: mit dem
    # ALTEN Schema liefert das Modell einen UNVOLLSTAENDIGEN Pivot (es kennt
    # `quelle`/`wertfelder` dann nicht) – das belegt zugleich, dass das Schema
    # noetig ist und nicht nur Beiwerk.
    letzter = eintragNeu
    check("der neue Lauf hat einen echten Pivot-Eintrag geliefert",
          letzter is not None)
    if letzter is not None:
        gut, weg = excel_ask.aenderungen_pruefen([letzter])
        check("der vom Modell gelieferte Eintrag wird JETZT angenommen",
              len(gut) == 1 and not weg)
        check("...und traegt seine ExcelApi-Anforderung",
              bool(gut) and gut[0].get("api_min") == "1.8")
        # Gegenprobe am selben Eintrag: ohne den Objekt-Zweig faellt er durch.
        import backend.excel_objekte as _eo
        _alt = _eo.ist_objekt
        _eo.ist_objekt = lambda e: False
        try:
            gut2, weg2 = excel_ask.aenderungen_pruefen([letzter])
        finally:
            _eo.ist_objekt = _alt
        check("...und waere VORHER abgelehnt worden (das war der Fehler)",
              not gut2 and bool(weg2))
        if weg2:
            print("  Grund von vorher: " + str(weg2[0].get("grund"))[:120])

    print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
    return 1 if fail else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
