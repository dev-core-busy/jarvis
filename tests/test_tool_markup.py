#!/usr/bin/env python3
"""Tool-Syntax darf NIE beim Benutzer landen – und ein Selbstgespraech ist keine Antwort.

DER VORFALL (2026-08-12, ECHT, Lauf 17865353985320004, nexus\\andrea.ladd):
Auf die Bitte, 54 Adressen aus einem PDF zu extrahieren, bekam der Benutzer als
ENDANTWORT das Selbstgespraech des Modells samt Bruchstuecken der Aufruf-Syntax:

    Die PDF-Datei ist bereits von einem vorherigen Schritt als Text extrahiert
    worden … Aber warte - der Prompt enthaelt bereits den extrahierten Text …
    Ich werde den Text aus dem Prompt in eine Datei schreiben und dann parsen.
    </parameter>
    </function>
    </tool_call>

HERGANG (aus dem Verlauf auf ECHT belegt): Qwen3.6-35B hinter vLLM, natives
Tool-Calling (prompt_tool_calling=false). Das Modell schreibt Aufrufe im
Hermes-/Qwen-XML-Format; vLLM hat den Aufruf nur TEILWEISE geparst – ausgefuehrt
wurde er (die Datei entstand, siehe Werkzeug-Ergebnis "✅ Datei geschrieben:
/tmp/parse_pdf.py"), die schliessenden Marken blieben im content zurueck. Der
Agent hatte damit Text ohne Function-Call und hat ihn als Endantwort gesendet.

Bei selbst gehosteten Modellen ist das der Normalfall, nicht die Ausnahme: ein
anderer --tool-call-parser, eine Modell-Aktualisierung oder ein Abbruch an
max_tokens loesen es erneut aus. Deshalb wird die Antwort maschinell
geradegezogen statt das Modell zu bitten.

Lauf:  python3 tests/test_tool_markup.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = 0
fehler = 0


def pruefe(was, bedingung, detail=""):
    global ok, fehler
    if bedingung:
        ok += 1
        print(f"  \033[32m✓\033[0m {was}")
    else:
        fehler += 1
        print(f"  \033[31m✗\033[0m {was}" + (f" – {detail}" if detail else ""))


def abschnitt(t):
    print(f"\n\033[1m{t}\033[0m")


# Der Text aus dem Verlauf, Zeichen fuer Zeichen.
ECHT_ANTWORT = (
    "Die PDF-Datei ist bereits von einem vorherigen Schritt als Text extrahiert "
    "worden (im Prompt sichtbar als [PDF-Inhalt von "
    "Einsender_KIM_Anbindung_compressed.pdf]). Ich muss diesen Text nicht erneut "
    "mit pdftotext extrahieren, sondern kann direkt mit dem bereits vorliegenden "
    "Text arbeiten.\n\nLass mich den Text im Prompt analysieren und eine "
    "Python-Datei erstellen, die diesen Text verwendet.\n\nAber warte - der Prompt "
    "enthält bereits den extrahierten Text. Ich kann diesen direkt in eine Datei "
    "schreiben und dann parsen.\n\nIch werde den Text aus dem Prompt in eine Datei "
    "schreiben und dann parsen.\n</parameter>\n</function>\n</tool_call>"
)

MARKEN = ("</tool_call>", "<tool_call>", "</function>", "<function=",
          "</parameter>", "<parameter=", "<|tool_call|>")


def main() -> int:
    try:
        from backend.llm import berge_tool_syntax, ist_nur_selbstgespraech
    except Exception as e:
        print(f"ABBRUCH: backend.llm nicht ladbar ({e})")
        return 2

    abschnitt("1) DER GEMELDETE TEXT, wortgleich")
    rein, calls = berge_tool_syntax(ECHT_ANTWORT)
    for m in MARKEN:
        pruefe(f"keine Marke {m} mehr im Text", m not in rein)
    pruefe("kein vollstaendiger Aufruf zu bergen (nur Bruchstuecke)", calls == [],
           str([c.name for c in calls]))
    pruefe("der Fliesstext bleibt erhalten", "pdftotext" in rein and "Prompt" in rein)
    pruefe("dieser Text gilt NICHT als Antwort", ist_nur_selbstgespraech(rein),
           repr(rein[-120:]))

    abschnitt("2) Vollstaendige Aufrufe werden GEBORGEN, nicht nur entfernt")
    xml = ('Ich schreibe die Datei.\n<tool_call><function=filesystem>'
           '<parameter=action>write</parameter>'
           '<parameter=path>/tmp/parse_pdf.py</parameter>'
           '<parameter=content>print("hallo")\nprint(2)</parameter>'
           '</function></tool_call>')
    rein, calls = berge_tool_syntax(xml)
    pruefe("ein Aufruf geborgen", len(calls) == 1, str(len(calls)))
    if calls:
        c = calls[0]
        pruefe("Werkzeugname erkannt", c.name == "filesystem", c.name)
        pruefe("Parameter vollstaendig", set(c.args) == {"action", "path", "content"},
               str(sorted(c.args)))
        pruefe("Zeilenumbruch im Inhalt erhalten", c.args.get("content", "").count("\n") == 1,
               repr(c.args.get("content")))
    pruefe("Text ohne Marken", not any(m in rein for m in MARKEN), repr(rein))

    js = ('Kurz nachgesehen.\n<tool_call>\n{"name": "shell_execute", '
          '"arguments": {"command": "ls -la /tmp", "timeout": 30}}\n</tool_call>')
    rein, calls = berge_tool_syntax(js)
    pruefe("JSON-Form geborgen", len(calls) == 1 and calls[0].name == "shell_execute",
           str([c.name for c in calls]))
    if calls:
        pruefe("Argumente typrichtig (Zahl bleibt Zahl)",
               calls[0].args.get("timeout") == 30, repr(calls[0].args))

    abschnitt("3) Werte werden richtig gedeutet")
    x = ('<function=cron_create><parameter=once>true</parameter>'
         '<parameter=n>42</parameter><parameter=liste>[1, 2]</parameter>'
         '<parameter=text>nicht: json</parameter></function>')
    _, calls = berge_tool_syntax(x)
    a = calls[0].args if calls else {}
    pruefe("true -> bool", a.get("once") is True, repr(a.get("once")))
    pruefe("42 -> int", a.get("n") == 42, repr(a.get("n")))
    pruefe("Liste -> list", a.get("liste") == [1, 2], repr(a.get("liste")))
    pruefe("Text bleibt Text", a.get("text") == "nicht: json", repr(a.get("text")))

    abschnitt("4) Echte Antworten bleiben unangetastet")
    for t in (
        "Die Auswertung ergab 54 Adressen. Die wichtigsten drei:\n- Otterberg\n- "
        "Heiligenhaus\n- Neubrandenburg",
        "Der Umsatz lag bei 1.216.500 EUR, das sind 12 % mehr als im Vorquartal.",
        "Ich habe 54 Einträge extrahiert und in eine Tabelle geschrieben.",
        "In der Datei stehen 3 Zeilen mit Fehlern; Zeile 7 ist unvollständig.",
    ):
        rein, calls = berge_tool_syntax(t)
        pruefe(f"unveraendert: {t[:42]}…", rein == t and not calls)
        pruefe(f"gilt als Antwort: {t[:42]}…", not ist_nur_selbstgespraech(rein))

    abschnitt("5) Selbstgespraech-Erkennung ist ENG gefasst")
    pruefe("reine Absicht wird erkannt",
           ist_nur_selbstgespraech("Ich werde jetzt die Datei schreiben und dann parsen."))
    pruefe("englische Absicht wird erkannt",
           ist_nur_selbstgespraech("Let me write the file and parse it."))
    pruefe("Absicht MIT Ergebnis gilt als Antwort",
           not ist_nur_selbstgespraech(
               "Ich habe die Datei geschrieben. Ergebnis: 54 Adressen gefunden."))
    pruefe("langer Text gilt als Antwort",
           not ist_nur_selbstgespraech("Ich werde erklaeren. " + "Fachtext. " * 90))
    pruefe("leerer Text ist keine Antwort", ist_nur_selbstgespraech(""))

    abschnitt("6) Verdrahtung im Provider und im Agenten")
    llm_src = (ROOT / "backend" / "llm.py").read_text(encoding="utf-8")
    ag_src = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
    pruefe("Provider bereinigt den content", "berge_tool_syntax(str(message[" in llm_src)
    pruefe("geborgene Aufrufe werden zu Function-Calls",
           "_geborgen and not message.get(\"tool_calls\")" in llm_src)
    pruefe("kein doppelter Aufruf, wenn der Server schon geparst hat",
           "sonst wuerde ein Aufruf doppelt" in llm_src)
    pruefe("Agent hat die zweite Schicht", "_ohne_tool_markup" in ag_src)
    pruefe("Selbstgespraech setzt _answer_sent NICHT", "_nur_absicht" in ag_src)
    pruefe("kein print/_log-Fehler: llm.py nutzt print",
           "_log(" not in llm_src.split("def berge_tool_syntax")[1][:4000])

    abschnitt("7) ECHTER Lauf: der Benutzer sieht keine Marken und bekommt eine Antwort")
    # Braucht fastapi (agent.py). Fehlt es, wird der Abschnitt ausdruecklich
    # uebersprungen statt gruen gemeldet.
    try:
        import asyncio
        from google.genai import types            # noqa: F401
        import backend.agent as A
        from backend.llm import LLMResponse
        machbar = True
    except Exception as e:                        # noqa: BLE001
        print(f"  (uebersprungen: {type(e).__name__}: {e})")
        machbar = False

    if machbar:
        class WSAttrappe:
            def __init__(self):
                self.nachrichten = []

            async def send_json(self, msg):
                self.nachrichten.append(msg)

            def endantworten(self):
                return [m["message"] for m in self.nachrichten
                        if m.get("type") == "status" and m.get("highlight")
                        and not m.get("intermediate")]

            def alle(self):
                return [str(m.get("message", "")) for m in self.nachrichten]

        def teil(t):
            return types.Part.from_text(text=t)

        class Stub:
            def __init__(self, folge):
                self.folge = list(folge)
                self.aufrufe = []

            async def generate_response(self, model=None, system_prompt=None,
                                        contents=None, tools=None, **kw):
                self.aufrufe.append({"tools": bool(tools)})
                parts = self.folge.pop(0) if self.folge else [teil("Standardantwort")]
                return LLMResponse(parts=parts, raw=None, usage={})

        try:
            agent = A.JarvisAgent()
            halter = {"s": None}
            A.get_provider = lambda *a, **kw: halter["s"]

            # 1. Antwort: genau der gemeldete Muell. 2. Antwort: echtes Ergebnis
            # (das holt der Nachschlag).
            stub = Stub([[teil(ECHT_ANTWORT)],
                         [teil("Ich habe 54 Adressen extrahiert. Die Liste liegt bereit.")]])
            halter["s"] = stub
            agent.provider = stub
            agent._user_histories.clear()
            ws = WSAttrappe()
            outcome = asyncio.run(agent.run_task("Extrahiere die Adressen", ws,
                                                 username="jarvis"))

            alles = "\n".join(ws.alle())
            for m in MARKEN:
                pruefe(f"nichts vom Benutzer Sichtbaren enthaelt {m}", m not in alles)
            pruefe("es wurde ein zweites Mal gefragt (Nachschlag)", len(stub.aufrufe) >= 2,
                   str(len(stub.aufrufe)))
            pruefe("der Nachschlag lief OHNE Werkzeuge",
                   stub.aufrufe and stub.aufrufe[-1]["tools"] is False,
                   str(stub.aufrufe))
            end = ws.endantworten()
            pruefe("der Benutzer bekommt am Ende ein echtes Ergebnis",
                   any("54 Adressen" in t for t in end), str(end)[:200])
            pruefe("das Selbstgespraech gilt NICHT als Endantwort",
                   not any("Aber warte" in t for t in end), str(end)[:200])
            pruefe("Lauf-Ergebnis ist nicht 'empty'", outcome != "empty", str(outcome))
        except Exception as e:                    # noqa: BLE001
            pruefe(f"echter Lauf durchfuehrbar ({type(e).__name__}: {e})", False)

    print(f"\n{ok} ok, {fehler} Fehler ({ok + fehler} Pruefungen)")
    return 1 if fehler else 0


if __name__ == "__main__":
    sys.exit(main())
