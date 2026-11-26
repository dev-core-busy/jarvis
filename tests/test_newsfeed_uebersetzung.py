#!/usr/bin/env python3
"""Waechter: Newsfeed in der Oberflaechensprache (backend/newsfeed_uebersetzung.py).

Zusagen (gewuenscht 2026-11-26):
  1. Ohne abgelegte Uebersetzung kommt das ORIGINAL, und der Block steht in
     der Liste der fehlenden; mit Uebersetzung zur AKTUELLEN Fassung kommt
     sie, mit Marke ``uebersetzt``. Nach einer Bearbeitung gilt die alte
     Uebersetzung NICHT mehr (Pruefsumme ueber Ueberschrift und Text).
  2. Unbekannte Sprache = Original, nichts fehlt (kein Modellaufruf).
  3. Die Modellantwort wird auf ihren TYP geprueft (Liste statt Text wird
     abgelehnt), gedeckelt und ohne Werkzeuge erfragt; das Modell bekommt die
     ZIELsprache.
  4. Anstossen laeuft im Hintergrund, doppelt angestossene Bloecke laufen
     EINMAL, ein Fehlschlag wird gemerkt (kein Dauerfeuer); im sensiblen Lauf
     wird nichts angestossen und nichts abgelegt.
  5. Beim Ablegen fallen geloeschte Meldungen heraus; eine unlesbare Ablage
     wird nicht ueberschrieben.
  6. Verdrahtung (Regel am Syntaxbaum von main.py): GET /api/newsfeed liest
     die Sprache aus ?lang= bzw. Cookie, wendet an und stoesst an; der Stand
     wird nicht angefasst.

⚠ SANDKASTEN MIT EXIT 2: kein Schreiben nach data/.
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""

import ast
import asyncio
import json
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = FAIL = 0


def check(text, bed, info=""):
    global OK, FAIL
    if bed:
        OK += 1
        print(f"  OK   {text}")
    else:
        FAIL += 1
        print(f"  FAIL {text}" + (f"  [{info}]" if info else ""))


def abbruch(grund):
    print(f"NICHT PRUEFBAR: {grund}")
    sys.exit(2)


# ── Stubs: config (nie die echte – sie schreibt die Live-settings.json) ─────
if "backend.config" not in sys.modules:
    _cfg = types.ModuleType("backend.config")

    class _C:
        def get_setting(self, k, d=None):
            return d
    _cfg.config = _C()
    sys.modules["backend.config"] = _cfg

try:
    from google.genai import types as _gtypes  # noqa: F401
except Exception:  # noqa: BLE001
    _g = types.ModuleType("google")
    _gg = types.ModuleType("google.genai")
    _gt = types.ModuleType("google.genai.types")

    class _Part:
        def __init__(self, text=""):
            self.text = text

        @staticmethod
        def from_text(text=""):
            return _Part(text)

    class _Content:
        def __init__(self, role="user", parts=None):
            self.role, self.parts = role, parts or []
    _gt.Part, _gt.Content = _Part, _Content
    _gg.types = _gt
    _g.genai = _gg
    sys.modules.update({"google": _g, "google.genai": _gg, "google.genai.types": _gt})

_gefangen = {}


class _Resp:
    def __init__(self, text):
        self.parts = [types.SimpleNamespace(text=text)]


class _Provider:
    """Echte Signatur von LLMProvider.generate_response (backend/llm.py)."""
    antwort = '{"titel": "Maintenance ce soir", "text": "Le serveur redémarre à 20 h."}'
    aufrufe = 0

    async def generate_response(self, model, system_prompt, contents,
                                tools=None, reasoning_effort=None, temperature=None):
        _Provider.aufrufe += 1
        _gefangen.update({"model": model, "sysp": system_prompt, "contents": contents,
                          "tools": tools, "effort": reasoning_effort})
        if isinstance(self.antwort, Exception):
            raise self.antwort
        return _Resp(self.antwort)


_PROV = _Provider()


class _LlmStub(types.ModuleType):
    def provider_fuer_lauf(self, prompt_tool_calling=None):
        _gefangen["ptc"] = prompt_tool_calling
        return (_PROV, "test-modell")

    @staticmethod
    def scrub_secrets(s):
        return s


sys.modules["backend.llm"] = _LlmStub("backend.llm")

try:
    from backend import newsfeed as nf
    from backend import newsfeed_uebersetzung as nfu
    from backend import sensibel
    from backend import atomar
except Exception as e:  # noqa: BLE001
    abbruch(f"Module nicht importierbar: {e}")

SANDKASTEN = Path(tempfile.mkdtemp(prefix="nfu_test_"))
nf.DATEI = SANDKASTEN / "newsfeed.json"
nf.AUSGEBLENDET_DATEI = SANDKASTEN / "ausgeblendet.json"
nfu.DATEI = SANDKASTEN / "uebersetzt.json"
DATA = (ROOT / "data").resolve()
for p in (nf.DATEI, nf.AUSGEBLENDET_DATEI, nfu.DATEI):
    if DATA in p.resolve().parents:
        abbruch(f"{p} zeigt in data/ – der Lauf schriebe in den Bestand")
print("Positivkontrolle: Ablagen liegen im Sandkasten")


def lauf(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


try:
    # ── 1 ───────────────────────────────────────────────────────────────
    print("\n1. Original, Uebersetzung, Bindung an die Fassung")
    e1 = nf.eintrag_speichern("", "Wartung heute Abend", "Der Server startet um 20 Uhr neu.")
    e2 = nf.eintrag_speichern("", "Neue Funktion", "Short Tracks kann jetzt Excel lesen.")
    ein = nf.anzeige("u1")["eintraege"]
    if len(ein) != 2:
        abbruch(f"Anzeige liefert {len(ein)} statt 2 Bloecke")
    aus, offen = nfu.anwenden(ein, "fr")
    check("ohne Ablage: Original-Ueberschriften", [x["titel"] for x in aus] == [x["titel"] for x in ein])
    check("ohne Ablage: keine Marke uebersetzt", not any("uebersetzt" in x for x in aus))
    check("ohne Ablage: beide Bloecke fehlen", sorted(o[0] for o in offen) == sorted([e1["id"], e2["id"]]),
          str(offen))
    check("fehlend traegt Sprache und Pruefsumme der Fassung",
          all(o[1] == "fr" and o[2] == nfu.pruefsumme(o[3], o[4]) for o in offen))
    nfu._ablegen(e1["id"], "fr", nfu.pruefsumme(e1["titel"], e1["text"]),
                 {"titel": "Maintenance ce soir", "text": "Le serveur redémarre à 20 h."})
    aus, offen = nfu.anwenden(nf.anzeige("u1")["eintraege"], "fr")
    t1 = next((x for x in aus if x["id"] == e1["id"]), {})
    check("mit Ablage: Uebersetzung statt Original", t1.get("titel") == "Maintenance ce soir", str(t1))
    check("mit Ablage: Marke uebersetzt = fr", t1.get("uebersetzt") == "fr")
    check("mit Ablage: nur noch der zweite fehlt", [o[0] for o in offen] == [e2["id"]], str(offen))
    aus_en, _ = nfu.anwenden(nf.anzeige("u1")["eintraege"], "en")
    check("andere Sprache: FR-Ablage gilt nicht fuer EN",
          next(x for x in aus_en if x["id"] == e1["id"])["titel"] == "Wartung heute Abend")
    nf.eintrag_speichern(e1["id"], "Wartung heute Abend", "Der Server startet um 21 Uhr neu.")
    aus, offen = nfu.anwenden(nf.anzeige("u1")["eintraege"], "fr")
    t1 = next((x for x in aus if x["id"] == e1["id"]), {})
    check("nach Bearbeiten: alte Uebersetzung gilt NICHT mehr", t1.get("text") == "Der Server startet um 21 Uhr neu.",
          str(t1))
    check("nach Bearbeiten: Block fehlt wieder", e1["id"] in [o[0] for o in offen])

    # ── 2 ───────────────────────────────────────────────────────────────
    print("\n2. Sprache")
    check("sprache_aus: fr/NL/en", (nfu.sprache_aus("fr"), nfu.sprache_aus("NL"), nfu.sprache_aus("en"))
          == ("fr", "nl", "en"))
    check("sprache_aus: unbekannt/leer -> ''", (nfu.sprache_aus("xx"), nfu.sprache_aus(None), nfu.sprache_aus(""))
          == ("", "", ""))
    aus, offen = nfu.anwenden(nf.anzeige("u1")["eintraege"], "")
    check("ohne Sprache: Original und NICHTS fehlt", offen == [] and not any("uebersetzt" in x for x in aus))

    # ── 3 ───────────────────────────────────────────────────────────────
    print("\n3. Modellaufruf")
    r = lauf(nfu.uebersetzen("Wartung", "Heute.", "fr"))
    check("Antwort uebernommen", r == {"titel": "Maintenance ce soir", "text": "Le serveur redémarre à 20 h."}, str(r))
    check("ohne Werkzeuge erfragt", _gefangen.get("tools") == [] and _gefangen.get("ptc") is False)
    check("Zielsprache steht im Systemprompt", "Französisch" in (_gefangen.get("sysp") or ""))
    inhalt = _gefangen["contents"][0].parts[0].text
    check("Inhalt geht als JSON mit titel/text hinein", json.loads(inhalt) == {"titel": "Wartung", "text": "Heute."})
    _PROV.antwort = 'Hier: {"titel": ["a", "b"], "text": "x"}'
    try:
        lauf(nfu.uebersetzen("a", "b", "fr"))
        abgelehnt = False
    except ValueError:
        abgelehnt = True
    except Exception:  # noqa: BLE001 – ein Absturz ist keine Ablehnung (sonst Exit 1 ohne Bilanz)
        abgelehnt = False
    check("Liste statt Text wird ABGELEHNT", abgelehnt)
    _PROV.antwort = json.dumps({"titel": "T" * 999, "text": "X" * 5000})
    r = lauf(nfu.uebersetzen("a", "b", "fr"))
    check("gedeckelt", len(r["titel"]) == nfu.TITEL_MAX and len(r["text"]) == nfu.TEXT_MAX)
    try:
        lauf(nfu.uebersetzen("a", "b", "xx"))
        unbekannt = False
    except ValueError:
        unbekannt = True
    check("unbekannte Zielsprache: kein Aufruf", unbekannt)

    # ── 4 ───────────────────────────────────────────────────────────────
    print("\n4. Anstossen im Hintergrund")
    nfu.DATEI.unlink(missing_ok=True)
    _PROV.antwort = '{"titel": "Nouvelle fonction", "text": "Short Tracks lit Excel."}'
    _Provider.aufrufe = 0

    async def szenario():
        ein = nf.anzeige("u1")["eintraege"]
        _, offen = nfu.anwenden(ein, "fr")
        n1 = nfu.anstossen(offen)
        n2 = nfu.anstossen(offen)       # derselbe Abruf noch einmal
        for _ in range(50):
            if not nfu._LAEUFT:
                break
            await asyncio.sleep(0.02)
        return len(offen), n1, n2
    n_offen, n1, n2 = lauf(szenario())
    check("Positivkontrolle: es gab fehlende Bloecke", n_offen == 2, str(n_offen))
    check("erster Abruf stoesst alle an", n1 == 2, str(n1))
    check("zweiter Abruf meldet sie als laufend (fuer das Nachfragen)", n2 == 2, str(n2))
    check("doppelt angestossen = EIN Aufruf je Block", _Provider.aufrufe == 2, str(_Provider.aufrufe))
    aus, offen = nfu.anwenden(nf.anzeige("u1")["eintraege"], "fr")
    check("danach liegt die Uebersetzung ab", all(x.get("uebersetzt") == "fr" for x in aus) and not offen,
          str([(x.get("titel"), x.get("uebersetzt")) for x in aus]))

    _PROV.antwort = RuntimeError("Modell weg")
    _Provider.aufrufe = 0
    nfu._FEHLSCHLAG.clear()

    async def fehlschlag():
        _, offen = nfu.anwenden(nf.anzeige("u1")["eintraege"], "nl")
        n1 = nfu.anstossen(offen)
        for _ in range(50):
            if not nfu._LAEUFT:
                break
            await asyncio.sleep(0.02)
        return n1, nfu.anstossen(offen)
    n1, n2 = lauf(fehlschlag())
    check("Positivkontrolle: Fehlschlag wurde angestossen", n1 == 2 and _Provider.aufrufe == 2, f"{n1} {_Provider.aufrufe}")
    check("gescheitert: kein neuer Anstoss in der Sperrfrist", n2 == 0 and _Provider.aufrufe == 2,
          f"{n2} {_Provider.aufrufe}")
    nfu._FEHLSCHLAG.clear()

    async def sensibel_lauf():
        _, offen = nfu.anwenden(nf.anzeige("u1")["eintraege"], "nl")
        with sensibel.scope(True):
            return nfu.anstossen(offen)
    _Provider.aufrufe = 0
    check("sensibler Lauf: nichts angestossen", lauf(sensibel_lauf()) == 0 and _Provider.aufrufe == 0)
    vorher = nfu.DATEI.read_bytes()
    with sensibel.scope(True):
        nfu._ablegen(e1["id"], "nl", "x", {"titel": "GEHEIM", "text": "GEHEIM"})
    check("sensibler Lauf: nichts abgelegt", nfu.DATEI.read_bytes() == vorher)
    nfu._ablegen(e1["id"], "nl", "x", {"titel": "Positiv", "text": "Positiv"})
    check("Positivkontrolle: ausserhalb wird abgelegt", b"Positiv" in nfu.DATEI.read_bytes())

    # ── 5 ───────────────────────────────────────────────────────────────
    print("\n5. Ablage")
    nf.eintrag_loeschen(e2["id"])
    nfu._ablegen(e1["id"], "en", "y", {"titel": "Maintenance", "text": "Tonight."})
    ablage = json.loads(nfu.DATEI.read_text(encoding="utf-8"))
    check("geloeschte Meldung faellt beim Ablegen heraus", e2["id"] not in ablage and e1["id"] in ablage,
          str(list(ablage)))
    # atomar heilt eine kaputte Datei aus ihrer .bak – unlesbar ist sie erst,
    # wenn auch die Sicherung kaputt ist.
    nfu.DATEI.write_text("{kaputt", encoding="utf-8")
    nfu.DATEI.with_name(nfu.DATEI.name + ".bak").write_text("{kaputt", encoding="utf-8")
    try:
        atomar.lesen(nfu.DATEI, vorgabe=dict)
        unlesbar = False
    except atomar.Unlesbar:
        unlesbar = True
    if not unlesbar:
        abbruch("Positivkontrolle: Ablage samt Sicherung kaputt, atomar liest sie trotzdem")
    nfu._ablegen(e1["id"], "en", "z", {"titel": "A", "text": "B"})
    check("unlesbare Ablage wird NICHT ueberschrieben", nfu.DATEI.read_text(encoding="utf-8") == "{kaputt")
    aus, offen = nfu.anwenden(nf.anzeige("u1")["eintraege"], "en")
    check("unlesbare Ablage: Original wird gezeigt", aus and aus[0]["titel"] == "Wartung heute Abend")

    # ── 6 ───────────────────────────────────────────────────────────────
    print("\n6. Verdrahtung in main.py")
    baum = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
    fn = next((k for k in ast.walk(baum) if isinstance(k, ast.AsyncFunctionDef) and k.name == "newsfeed_lesen"), None)
    if fn is None:
        abbruch("newsfeed_lesen nicht gefunden")
    rufe = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]

    def attr_ruf(name):
        return [c for c in rufe if isinstance(c.func, ast.Attribute) and c.func.attr == name]
    check("Sprache ueber nfu.sprache_aus", bool(attr_ruf("sprache_aus")))
    quellen = {getattr(a.args[0], "value", None) for c in attr_ruf("sprache_aus") for a in ast.walk(c)
               if isinstance(a, ast.Call) and getattr(a.func, "attr", "") == "get" and a.args}
    check("Sprache aus ?lang= UND Cookie jarvis_lang", {"lang", "jarvis_lang"} <= quellen, str(quellen))
    anw = [c for c in rufe if c.args and isinstance(c.args[0], ast.Attribute) and c.args[0].attr == "anwenden"]
    check("anwenden laeuft in to_thread (liest eine Datei)", bool(anw))
    check("anstossen wird gerufen", bool(attr_ruf("anstossen")))
    stand_geschrieben = any(isinstance(z, ast.Assign) and any(
        isinstance(t, ast.Subscript) and getattr(t.slice, "value", None) == "stand" for t in z.targets)
        for z in ast.walk(fn))
    check("der Stand wird nicht angefasst (Ausblenden haengt am Original)", not stand_geschrieben)
finally:
    shutil.rmtree(SANDKASTEN, ignore_errors=True)

print(f"\nERGEBNIS: {OK}/{OK + FAIL}")
sys.exit(0 if FAIL == 0 else 1)
