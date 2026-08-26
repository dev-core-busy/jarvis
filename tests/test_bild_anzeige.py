#!/usr/bin/env python3
"""Erzeugte Bilder muessen im Chat ANKOMMEN – auch auf den Notpfaden.

DER VORFALL (2026-08-26, ECHT, gemeldet von jonas.reichelt): Orchestrierung mit
Bildgenerierung in /chat. Das Bild wurde erzeugt, die Antwort lautete

    "Die Base64-codierte Bilddaten-URL war vermutlich zu lang fuer die Anzeige.
     Hier ist das Bild als Download:"

– und dahinter stand nichts. Der Satz ist Modell-Prosa: das Modell RAET (daher
"vermutlich"), warum sein Bild nicht erscheint, und erfindet eine Erklaerung.

ZWEI URSACHEN, jede fuer sich hinreichend:

1. `_clean_doc_refs` ZERSTOERTE die Bildreferenz. Die Regel "Markdown-Link auf
   Dokument -> nur Label behalten" trifft jeden absoluten Pfad mit Bildendung,
   also auch `/api/generated/<hex>.png`. Aus
       ![Ein Hund](/api/generated/<hex>.png)
   wurde der Textrest
       !Ein Hund
   Fuer `/api/documents/…` ist das richtig (dort liefert `_deliver_docs` einen
   Chip nach). Fuer `/api/generated/…` ist es das GEGENTEIL: dafuer gibt es
   KEINEN Chip, die Markdown-Referenz im Anzeigetext ist der einzige Weg zum
   Bild.

2. Die NOTPFADE sendeten den Modelltext ROH. `_ohne_tool_markup`,
   `_clean_doc_refs`, `_expand_charts` und vor allem `_mit_bildern` liefen nur
   im Regelweg. Nach MAX_STEPS / Endlosschleife / "Abschluss ohne Antwort"
   uebernimmt `_try_final` – und dessen zweiter Versuch bekommt die
   Werkzeug-Ergebnisse gar nicht mehr zu sehen ("Antworte direkt aus deinem
   Wissen"). Das Modell weiss dort nichts von `/api/generated/…` und formuliert
   frei. `_mit_bildern` haette das Bild deterministisch nachgetragen, lief auf
   diesem Pfad aber nie. Eine Orchestrierung braucht viele Schritte – MAX_STEPS
   ist dort der Normalfall, nicht die Ausnahme.

DIE ZUSAGE, die dieser Test festschreibt:
  a) `/api/generated/…` ueberlebt `_clean_doc_refs` unveraendert, waehrend
     Dokumentpfade weiterhin verschwinden.
  b) JEDE Stelle in `run_task`, die MODELLTEXT als Antwort sendet, laeuft durch
     `_anzeigetext`. Geprueft per `ast` ueber die REGEL (nicht ueber eine
     gepflegte Liste), damit auch ein KUENFTIGER Notpfad auffaellt.
  c) In `_anzeigetext` kommt der Bild-Nachtrag ZULETZT – sonst wuerde
     `_clean_doc_refs` die gerade angehaengte Referenz gleich wieder bearbeiten.

Kein Import von backend.agent (zieht fastapi/config und wuerde die
Live-settings.json anfassen): Methoden und Konstanten werden per Quelltext
herausgeschnitten und wirklich ausgefuehrt.

Lauf:  python3 tests/test_bild_anzeige.py
"""
import ast
import re
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
QUELLE = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
BAUM = ast.parse(QUELLE)

OK = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
_zaehler = {"ok": 0, "fail": 0}


def check(bedingung, text, detail=""):
    if bedingung:
        _zaehler["ok"] += 1
        print(f"  {OK} {text}")
    else:
        _zaehler["fail"] += 1
        print(f"  {FAIL} {text}" + (f"  [{detail}]" if detail else ""))


def kopf(text):
    print(f"\n\033[1m{text}\033[0m")


# ── Quelltext-Werkzeuge ──────────────────────────────────────────────────────

def methode(name: str) -> ast.FunctionDef:
    for node in ast.walk(BAUM):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Methode {name} nicht gefunden")


def quelle_von(name: str) -> str:
    return textwrap.dedent(ast.get_source_segment(QUELLE, methode(name)))


def _ohne_docstring(fn) -> str:
    """Der Rumpf einer Funktion OHNE ihren Docstring.

    Ein Waechter, der den Docstring mitliest, findet dort seine eigene
    Begruendung wieder und ist gruen, ohne den Code geprueft zu haben.
    """
    koerper = fn.body
    if (koerper and isinstance(koerper[0], ast.Expr)
            and isinstance(koerper[0].value, ast.Constant)
            and isinstance(koerper[0].value.value, str)):
        koerper = koerper[1:]
    return "\n".join(ast.get_source_segment(QUELLE, k) or "" for k in koerper)


def konstante(name: str):
    m = re.search(r"^%s = re\.compile\(" % re.escape(name), QUELLE, re.M)
    if not m:
        raise AssertionError(f"Konstante {name} nicht gefunden")
    i = m.start()
    j = QUELLE.index("\n", QUELLE.index(")\n", i))
    u = {"re": re}
    exec(QUELLE[i:j], u)
    return u[name]


def liefer_ext() -> tuple:
    i = QUELLE.index("_LIEFER_EXT = (")
    j = QUELLE.index("\n    )", i) + len("\n    )")
    u = {}
    exec(textwrap.dedent(QUELLE[i:j]), u)
    return u["_LIEFER_EXT"]


# ═════════════════════════════════════════════════════════════════════════════
# 1) _clean_doc_refs laesst generierte Bilder in Ruhe
# ═════════════════════════════════════════════════════════════════════════════

def teil1():
    kopf("1) _clean_doc_refs: /api/generated ueberlebt, Dokumentpfade nicht")

    ext = liefer_ext()
    umg = {"re": re, "_GENERATED_URL_RE": konstante("_GENERATED_URL_RE")}
    exec(quelle_von("_clean_doc_refs"), umg)
    roh = umg["_clean_doc_refs"]

    class Stub:
        def _liefer_ext_re(self):
            return "|".join(re.escape(e) for e in ext)

    stub = Stub()

    def clean(t):
        return roh(stub, t)

    H = "a" * 32
    bild = f"/api/generated/{H}.png"

    # ── Der gemeldete Fall, wortgleich in der Form ───────────────────────────
    aus = clean(f"Hier ist dein Bild:\n\n![Ein Hund]({bild})")
    check(bild in aus, "die Bild-URL ueberlebt", aus)
    check("![Ein Hund](" in aus,
          "die Markdown-Bildreferenz bleibt INTAKT (nicht nur die URL)", aus)
    check("!Ein Hund" not in aus.replace("![Ein Hund]", ""),
          "kein Textrest '!Label' – genau der gemeldete Anblick", aus)

    # Auch die nackte URL (das Modell schreibt sie manchmal ohne Markdown)
    check(bild in clean(f"Das Bild liegt unter {bild}"),
          "auch die nackte Bild-URL ueberlebt")

    # Alle ueblichen Bildendungen, nicht nur png
    for e in ("jpg", "jpeg", "gif", "webp", "svg"):
        u = f"/api/generated/{H}.{e}"
        check(u in clean(f"![x]({u})"), f"…auch als .{e}")

    # ── Die Gegenrichtung: die Bereinigung darf NICHT schwaecher werden ──────
    check("/api/documents/" not in clean(f"![doc](/api/documents/{'c'*32}__Bild.png)"),
          "ein Dokument-Bild wird WEITERHIN entfernt (dafuer gibt es den Chip)")
    check("/tmp/" not in clean("Ergebnis unter /tmp/auswertung.xlsx"),
          "ein /tmp-Pfad wird weiterhin entfernt")
    check("/tmp/" not in clean("Bild unter /tmp/diagramm.png"),
          "ein lokaler /tmp-BILDpfad wird weiterhin entfernt")
    check("JARVIS_DELIVER" not in clean("[[JARVIS_DELIVER:/tmp/x.zip]] fertig"),
          "der Liefer-Marker wird weiterhin entfernt")

    # ── Gemischt: beides im selben Text ──────────────────────────────────────
    aus = clean(f"Bild ![B]({bild}) und Tabelle /tmp/a.csv")
    check(bild in aus and "/tmp/a.csv" not in aus,
          "gemischter Text: Bild bleibt, Dokumentpfad geht")

    # ── Der Platzhalter darf nie sichtbar werden ─────────────────────────────
    check("JVGEN" not in clean(f"![x]({bild}) und ![y]({bild})") and "\x00" not in
          clean(f"![x]({bild}) und ![y]({bild})"),
          "die interne Maskierung ist vollstaendig zurueckgebaut (auch mehrfach)")

    # BESTANDSBEFUND, bewusst festgehalten statt stillschweigend mitgeaendert:
    # eine EXTERNE Bild-URL ueberlebt NICHT. Die Dokument-Link-Regel greift vor
    # den Bild-Regeln und trifft jedes `](…​.png)`, auch `https://…`. Der
    # Kommentar an Regel (2) in `_clean_doc_refs` behauptet das Gegenteil
    # ("Externe http(s)-Bild-URLs bleiben unangetastet") – das gilt nur fuer die
    # Bild-Regeln selbst, nicht fuer die Regel davor. Das ist ein EIGENER Fehler
    # (ein vom Modell verlinktes Firmenbild verschwindet) und gehoert nicht in
    # diesen Fix; der Test haelt den Ist-Zustand fest, damit die Aenderung
    # auffaellt, wenn ihn jemand angeht.
    check("https://example.com/b.png" not in clean("![e](https://example.com/b.png)"),
          "BEFUND: externe Bild-URLs verschwinden weiterhin (eigener Fehler, "
          "siehe Kommentar im Test)")


# ═════════════════════════════════════════════════════════════════════════════
# 2) JEDE Antwort-Ausgabe in run_task laeuft durch _anzeigetext
# ═════════════════════════════════════════════════════════════════════════════

def _ist_fester_text(knoten) -> bool:
    """Ist das Argument ein vom PROGRAMM formulierter Text?

    Konstanten und f-Strings sind Statusmeldungen ("⏳ Warte auf LLM-Antwort…",
    "⚠️ Keine Antwort vom LLM erhalten."). Alles andere – eine Variable oder ein
    Funktionsergebnis – ist MODELLTEXT und muss aufbereitet werden.
    """
    return isinstance(knoten, (ast.Constant, ast.JoinedStr))


def _ist_anzeigetext_aufruf(knoten) -> bool:
    return (isinstance(knoten, ast.Call)
            and isinstance(knoten.func, ast.Attribute)
            and knoten.func.attr == "_anzeigetext")


# Variablen, die KEINEN Modelltext tragen und deshalb nicht aufbereitet werden
# duerfen. EINZELN eingetragen und begruendet – keine Sammelfreigabe.
_KEIN_MODELLTEXT = {
    # `_friendly_api_error(e)`: eine vom PROGRAMM formulierte Fehlermeldung.
    # Durch `_anzeigetext` geschickt wuerde `_mit_bildern` ihr am Ende noch ein
    # Bild anhaengen ("Verbindung fehlgeschlagen" + Katzenbild).
    "err_msg",
}


def _sammle_aufbereitete(fn) -> set:
    """Namen, denen im Rumpf ein `_anzeigetext(...)`-Ergebnis zugewiesen wurde.

    Ohne das meldet die Regel den Regelweg selbst als Verstoss: dort steht
    `_display = self._anzeigetext(...)` und gesendet wird `_display`.
    """
    namen = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and _ist_anzeigetext_aufruf(node.value):
            for ziel in node.targets:
                if isinstance(ziel, ast.Name):
                    namen.add(ziel.id)
    return namen


def teil2():
    kopf("2) Jede Antwort-Ausgabe in run_task wird aufbereitet (Regel, nicht Liste)")

    fn = methode("run_task")
    aufbereitet = _sammle_aufbereitete(fn)
    check("_display" in aufbereitet,
          "der Regelweg weist aufbereiteten Text einer Variablen zu", str(aufbereitet))

    verstoesse = []
    geprueft = 0

    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if not (isinstance(f, ast.Attribute) and f.attr == "_send_status"):
            continue
        # Nur Antworten zaehlen: highlight=True kennzeichnet sie.
        if not any(k.arg == "highlight" and isinstance(k.value, ast.Constant)
                   and k.value.value is True for k in node.keywords):
            continue
        if len(node.args) < 2:
            continue
        arg = node.args[1]
        if _ist_fester_text(arg):
            continue  # Statusmeldung des Programms
        if isinstance(arg, ast.Name) and arg.id in _KEIN_MODELLTEXT:
            continue  # begruendete Ausnahme, siehe _KEIN_MODELLTEXT
        geprueft += 1
        ok = (_ist_anzeigetext_aufruf(arg)
              or (isinstance(arg, ast.Name) and arg.id in aufbereitet))
        if not ok:
            verstoesse.append((node.lineno, ast.unparse(arg)[:70]))

    check(geprueft >= 3,
          f"es wurden {geprueft} Modelltext-Ausgaben gefunden (Regelweg + Notpfade)",
          "zu wenige – schneidet der Test noch den richtigen Rumpf?")
    check(not verstoesse,
          "ALLE senden aufbereiteten Text",
          "; ".join(f"Zeile {z}: {t}" for z, t in verstoesse))

    # Die drei bekannten Pfade muessen einzeln belegt sein – als Positivkontrolle
    # dafuer, dass die Regel oben nicht an einer zu engen Auswahl gruen wird.
    q = quelle_von("run_task")
    check(q.count("self._anzeigetext(") >= 3,
          "mindestens drei Aufrufstellen (Regelweg, Kurz-Neuversuch, _try_final)",
          f"gefunden: {q.count('self._anzeigetext(')}")
    check("_anzeigetext(retry_text" in q.replace(" ", "").replace("\n", ""),
          "der Kurz-Prompt-Neuversuch ist verdrahtet")
    check("_anzeigetext(_final_text" in q.replace(" ", "").replace("\n", ""),
          "der _try_final-Pfad ist verdrahtet")


# ═════════════════════════════════════════════════════════════════════════════
# 3) _anzeigetext: Reihenfolge und Bild-Nachtrag
# ═════════════════════════════════════════════════════════════════════════════

def teil3():
    kopf("3) _anzeigetext: Reihenfolge ist Semantik")

    q = quelle_von("_anzeigetext")
    # OHNE DOCSTRING messen. Er nennt alle vier Namen in erklaerendem Fliesstext
    # und in anderer Reihenfolge – ein Waechter, der ihn mitliest, prueft seine
    # eigene Begruendung statt des Codes (Register).
    rumpf = _ohne_docstring(methode("_anzeigetext"))
    pos = {n: rumpf.index(n) for n in ("_ohne_tool_markup", "_clean_doc_refs",
                                       "_expand_charts", "_mit_bildern")}
    check(pos["_ohne_tool_markup"] < pos["_clean_doc_refs"] < pos["_expand_charts"]
          < pos["_mit_bildern"],
          "Tool-Syntax → Dokumentpfade → Diagramme → BILDER ZULETZT")

    # Der Bild-Nachtrag muss abschaltbar sein (Zwischentexte), sonst erschiene
    # ein Bild, das an einem Zwischenstand haengt, doppelt.
    fn = methode("_anzeigetext")
    args = [a.arg for a in fn.args.args]
    check("mit_bildern" in args, "Zwischentexte koennen den Bild-Nachtrag abschalten")

    # Funktional: mit einem Stub wirklich ausfuehren.
    aufrufe = []

    class Stub:
        def _ohne_tool_markup(self, t):
            aufrufe.append("markup"); return t

        def _clean_doc_refs(self, t):
            aufrufe.append("clean"); return t

        def _expand_charts(self, t):
            aufrufe.append("charts"); return t

        def _mit_bildern(self, t):
            aufrufe.append("bilder"); return t + "\n\n![Bild](/api/generated/x.png)"

    umg = {}
    exec(q, umg)
    Stub._anzeigetext = umg["_anzeigetext"]
    s = Stub()

    aus = s._anzeigetext("Fertig.")
    check(aufrufe == ["markup", "clean", "charts", "bilder"],
          "alle vier Schritte laufen, in dieser Reihenfolge", str(aufrufe))
    check("/api/generated/x.png" in aus, "das Bild wird nachgetragen")

    aufrufe.clear()
    s._anzeigetext("Ich schaue kurz nach…", mit_bildern=False)
    check("bilder" not in aufrufe, "bei einem Zwischentext KEIN Bild-Nachtrag")

    aufrufe.clear()
    check(s._anzeigetext("   ") == "", "leerer Text ergibt leeren Text")
    check("clean" not in aufrufe, "…und laeuft nicht unnoetig durch die Kette")


# ═════════════════════════════════════════════════════════════════════════════

def teil4():
    """ECHTE run_task-Laeufe: der gemeldete Fall, funktional nachgestellt.

    Braucht fastapi (nur im venv auf DEV vorhanden). Ohne die Abschnitte oben
    ist das hier der einzige Beweis, dass die Kette im ZUSAMMENSPIEL haelt –
    Quelltext-Pruefungen koennen eine falsch verdrahtete Reihenfolge uebersehen.
    """
    kopf("4) Echte Laeufe: Bild erreicht den Benutzer (auch ueber den Notpfad)")

    try:
        import asyncio
        from backend import agent as A
        from backend.llm import LLMResponse, LLMPart
        from backend.tools.image_gen import record_task_image
        from google.genai import types
    except Exception as e:  # noqa: BLE001
        print(f"  … uebersprungen: {type(e).__name__} ({e}) – auf DEV im venv ausfuehren")
        return

    import tempfile as _tf
    from backend import conv_log as _CL

    # SANDKASTEN: run_task schreibt in den LLM-Verlauf. Umbiegen UND nachweisen,
    # sonst verschmutzt der Test den echten Verlauf des laufenden Servers.
    _SAND = Path(_tf.mkdtemp(prefix="bild_anzeige_conv_"))
    _ECHT = _CL._CONV_DIR
    _CL._CONV_DIR = _SAND / "conv"
    _CL._INDEX = _CL._CONV_DIR / "index.jsonl"
    _CL._OLD_FILE = _SAND / "conv_log.json"
    if _CL._CONV_DIR.resolve() == _ECHT.resolve() or _SAND not in _CL._CONV_DIR.resolve().parents:
        print("ABBRUCH: conv_log zeigt nicht in das Wegwerf-Verzeichnis.")
        sys.exit(2)

    BILD = "/api/generated/" + "d" * 32 + ".png"

    def teil_text(t):
        return LLMPart(text=t, function_call=None)

    class FCall:
        def __init__(self, name, args):
            self.name, self.args = name, args

    class WSAttrappe:
        def __init__(self):
            self.nachrichten = []

        async def send_json(self, d):
            self.nachrichten.append(d)

    class Stub:
        def __init__(self, folge):
            self.folge = list(folge)

        async def generate_response(self, model=None, system_prompt=None, contents=None,
                                    tools=None, **kw):
            parts = self.folge.pop(0) if self.folge else [teil_text("Standardantwort")]
            return LLMResponse(parts=parts, raw=None, usage={})

    _agent = A.JarvisAgent()
    _halter = {"s": None}
    A.get_provider = lambda *a, **kw: _halter["s"]

    # Das "Werkzeug" traegt ein Bild ein – genau wie generate_image es tut.
    async def _fake_tool(self, name, args, ws=None, **kw):
        if name == "generate_image":
            record_task_image("/tmp/x.png", BILD)
            return ("BILD_ERZEUGT. Gib in deiner finalen Antwort EXAKT die folgende "
                    f"Markdown-Bildreferenz unveraendert aus:\n\n![Hund]({BILD})")
        return "ok"

    _orig_exec = A.JarvisAgent._execute_tool
    A.JarvisAgent._execute_tool = _fake_tool

    def antwort_texte(ws):
        """Alle als Antwort markierten Texte des Laufs."""
        out = []
        for m in ws.nachrichten:
            if m.get("type") == "status" and m.get("highlight") and not m.get("intermediate"):
                out.append(m.get("message") or "")
        return out

    def lauf(folge, max_steps=None):
        _halter["s"] = Stub(folge)
        _agent.provider = _halter["s"]
        _agent._user_histories.clear()
        if max_steps is not None:
            _agent._max_steps = lambda _m=max_steps: _m
        ws = WSAttrappe()
        asyncio.run(_agent.run_task("Erzeuge ein Bild von einem Hund", ws, username="jarvis"))
        return ws

    try:
        # ── Fall A: Regelweg. Das Modell formuliert NEU und nennt das Bild
        #    nicht – genau das Verhalten des Orchestrators bei einer Delegation.
        ws = lauf([
            [LLMPart(text=None, function_call=FCall("generate_image", {"prompt": "Hund"}))],
            [teil_text("Die Base64-codierte Bilddaten-URL war vermutlich zu lang fuer die "
                       "Anzeige. Hier ist das Bild als Download:")],
        ])
        texte = "\n".join(antwort_texte(ws))
        check(BILD in texte,
              "Regelweg: das Bild kommt an, obwohl die Antwort es nicht nennt",
              texte[:160])

        # ── Fall B: DER GEMELDETE FALL. Das Modell gibt die Referenz brav aus –
        #    frueher zerstoerte `_clean_doc_refs` sie zu "!Hund".
        ws = lauf([
            [LLMPart(text=None, function_call=FCall("generate_image", {"prompt": "Hund"}))],
            [teil_text(f"Bitte sehr:\n\n![Hund]({BILD})")],
        ])
        texte = "\n".join(antwort_texte(ws))
        check(f"![Hund]({BILD})" in texte,
              "die vom Modell ausgegebene Bildreferenz bleibt INTAKT", texte[:160])
        check(texte.count(BILD) == 1,
              "…und wird NICHT zusaetzlich angehaengt (kein doppeltes Bild)",
              f"{texte.count(BILD)}x")

        # ── Fall C: DER NOTPFAD. MAX_STEPS erreicht -> _try_final. Der
        #    Reset-Versuch kennt die Werkzeug-Ergebnisse nicht und kann das Bild
        #    unmoeglich nennen. Vor dem Fix ging es hier verloren.
        ws = lauf([
            [LLMPart(text=None, function_call=FCall("generate_image", {"prompt": "Hund"}))],
            [teil_text("Das Bild ist fertig, hier als Download:")],
            [teil_text("Das Bild ist fertig, hier als Download:")],
        ], max_steps=1)
        texte = "\n".join(antwort_texte(ws))
        check(BILD in texte,
              "Notpfad (_try_final nach MAX_STEPS): das Bild kommt trotzdem an",
              texte[:200])
    finally:
        A.JarvisAgent._execute_tool = _orig_exec
        _CL._CONV_DIR, _CL._INDEX = _ECHT, _ECHT / "index.jsonl"


def main():
    print("\033[1mErzeugte Bilder muessen im Chat ankommen (Vorfall 2026-08-26)\033[0m")
    teil1()
    teil2()
    teil3()
    teil4()
    print("\n" + "=" * 62)
    n = _zaehler["ok"] + _zaehler["fail"]
    if _zaehler["fail"]:
        print(f"\033[31m{_zaehler['ok']} ok, {_zaehler['fail']} Fehler ({n} Pruefungen)\033[0m")
        return 1
    print(f"\033[32m{_zaehler['ok']} ok, 0 Fehler ({n} Pruefungen)\033[0m")
    return 0


if __name__ == "__main__":
    sys.exit(main())
