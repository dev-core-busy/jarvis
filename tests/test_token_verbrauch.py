"""Waechter: Token-Verbrauch je Modellaufruf (backend/token_verbrauch.py).

Gemessen werden Eigenschaften, keine Schreibweisen:

0. Positivkontrolle: die Ablage zeigt in einen Sandkasten (sonst Exit 2 – der
   Waechter wuerde den echten Bestand fuellen).
1. JEDE Provider-Klasse in backend/llm.py, die generate_response selbst
   definiert, ist umhuellt (per Inspektion ermittelt, keine Namensliste), jede
   traegt eine Anbieter-Kennung, und eine Attrappe ausserhalb von llm.py wird
   NICHT umhuellt.
2. Die Huelle WIRKLICH ausgefuehrt: Tokens, Cache-Anteile, fehlende Zaehlung,
   Fehlschlag, Werkzeug (laufend vs. angefordert), Benutzer, Kanal – und der
   Dienst bleibt auch hinter asyncio.gather (Task-Grenze) richtig.
3. Kein Doppelzaehlen, wenn eine umhuellte Methode eine umhuellte ruft.
4. Auswertung: Summen-Invariante ueber alle Reihen, Uebrige-Reihe, Filter
   (normierter Benutzer, leerer Wert, Werkzeug enthaelt), Optionen ungefiltert,
   Raster.
5. Alterung: alte Tagesdateien fallen, die Schnitt-Datei wird gefiltert.
6. Verdrahtung am Syntaxbaum: Endpunkt nur fuer Administratoren, Alterung im
   Tageslauf, Werkzeug-/Kanal-Kontext im Agenten mit Reset im finally.

Lauf: python3 tests/test_token_verbrauch.py   (Exit 0 gruen, 1 Befund, 2 konnte nicht laufen)
"""

import ast
import asyncio
import contextvars
import json
import os
import shutil
import sys
import tempfile
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

OK = FAIL = 0


def pruefe(bed, text, detail=""):
    global OK, FAIL
    if bed:
        OK += 1
        print(f"  ✓ {text}")
    else:
        FAIL += 1
        print(f"  ✗ {text}" + (f" – {detail}" if detail else ""))


def abschnitt(t):
    print(f"\n{t}")


def bilanz(code=None):
    print("\n" + "=" * 62)
    print(f"  {OK} OK, {FAIL} FAIL")
    print("=" * 62)
    sys.exit(code if code is not None else (1 if FAIL else 0))


# backend.config NUR als Stub: der echte Import schreibt die Live-settings.json.
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace()
sys.modules["backend.config"] = _cfg

try:
    from backend import token_verbrauch as tv
    from backend import llm
except Exception as e:  # noqa: BLE001
    print(f"  ✗ ABBRUCH: Import fehlgeschlagen: {e}")
    bilanz(2)

SANDKASTEN = Path(tempfile.mkdtemp(prefix="tv_test_"))
tv._DIR = SANDKASTEN / "token"


def zeilen_lesen():
    out = []
    for p in sorted(tv._DIR.glob("*.jsonl")):
        out += [json.loads(z) for z in p.read_text().splitlines() if z.strip()]
    return out


def leeren():
    shutil.rmtree(tv._DIR, ignore_errors=True)


try:
    # ── 0 ────────────────────────────────────────────────────────────────────
    abschnitt("0. Positivkontrolle: Ablage im Sandkasten")
    echt = (ROOT / "data" / "logs" / "token").resolve()
    im_sandkasten = str(tv._DIR.resolve()).startswith(str(SANDKASTEN.resolve()))
    pruefe(im_sandkasten and tv._DIR.resolve() != echt, "Ablage zeigt in den Sandkasten", str(tv._DIR))
    if not im_sandkasten:
        bilanz(2)

    # ── 1 ────────────────────────────────────────────────────────────────────
    abschnitt("1. Jede Provider-Klasse in llm.py ist umhuellt")
    klassen = [c for c in vars(llm).values()
               if isinstance(c, type) and issubclass(c, llm.LLMProvider)
               and c is not llm.LLMProvider and c.__module__ == llm.__name__]
    eigene = [c for c in klassen if "generate_response" in c.__dict__]
    pruefe(len(eigene) >= 4, f"Provider mit eigener generate_response gefunden ({len(eigene)})",
           ", ".join(c.__name__ for c in eigene))
    for c in eigene:
        pruefe(getattr(c.__dict__["generate_response"], "__token_erfassung__", False),
               f"{c.__name__}.generate_response ist umhuellt")
    for c in klassen:
        pruefe(bool(c.__dict__.get("anbieter_kennung")), f"{c.__name__} traegt eine eigene Anbieter-Kennung")
    kenn = [c.__dict__.get("anbieter_kennung") for c in klassen]
    pruefe(len(kenn) == len(set(kenn)), "Anbieter-Kennungen sind eindeutig", str(kenn))

    class Attrappe(llm.LLMProvider):
        async def generate_response(self, model, system_prompt, contents, tools=None,
                                    reasoning_effort=None, temperature=None):
            return llm.LLMResponse(parts=[], raw=None, usage={"input_tokens": 1, "output_tokens": 1})

    pruefe(not getattr(Attrappe.generate_response, "__token_erfassung__", False),
           "Attrappe ausserhalb von llm.py wird NICHT umhuellt (fuellt den Bestand nicht)")

    # ── 2 ────────────────────────────────────────────────────────────────────
    abschnitt("2. Huelle wirklich ausgefuehrt")

    def antwort(usage, werkzeuge=()):
        parts = [llm.LLMPart(text="x")]
        parts += [llm.LLMPart(function_call=llm.MockFC(n, {})) for n in werkzeuge]
        return llm.LLMResponse(parts=parts, raw=None, usage=usage)

    class Gemacht:
        """Provider-Ersatz mit umhuellter Methode (wie in llm.py)."""
        anbieter_kennung = "probe"

        def __init__(self, resp=None, wirf=None):
            self.resp, self.wirf = resp, wirf

        async def _roh(self, model, system_prompt, contents, tools=None,
                       reasoning_effort=None, temperature=None):
            if self.wirf:
                raise self.wirf
            return self.resp

    Gemacht.generate_response = tv.umhuellen(Gemacht._roh)

    def als_modul(modulname, quelltext):
        """Aufrufer mit vorgegebenem Modulnamen – der Dienst wird daraus abgeleitet."""
        ns = {"__name__": modulname, "asyncio": asyncio}
        exec(compile(quelltext, f"<{modulname}>", "exec"), ns)
        return ns

    m_wg = als_modul("backend.wissensgraph_extraktion", (
        "async def direkt(p):\n"
        "    return await p.generate_response('modell-a', 's', [])\n"
        "async def ueber_gather(p):\n"
        "    return (await asyncio.gather(p.generate_response(model='modell-b', system_prompt='s', contents=[])))[0]\n"))
    m_main = als_modul("backend.main", (
        "async def _sec_llm_classify(p):\n"
        "    return await p.generate_response('modell-c', 's', [])\n"))

    leeren()
    asyncio.run(m_wg["direkt"](Gemacht(antwort({"input_tokens": 100, "output_tokens": 20}))))
    z = zeilen_lesen()
    pruefe(len(z) == 1, "ein Aufruf -> eine Zeile", str(len(z)))
    z = z[0] if z else {}
    pruefe(z.get("ein") == 100 and z.get("aus") == 20, "Tokens uebernommen", str(z))
    pruefe(z.get("an") == "probe" and z.get("m") == "modell-a", "Anbieter (zur Laufzeit) und Modell")
    pruefe(z.get("d") == "wissensgraph_extraktion", "Dienst aus dem Aufrufer-Modul", z.get("d"))
    pruefe(not any(k in z for k in ("system_prompt", "contents", "text", "prompt")), "KEIN Inhalt in der Zeile")

    leeren()
    asyncio.run(m_wg["ueber_gather"](Gemacht(antwort({"input_tokens": 5, "output_tokens": 1}))))
    z = (zeilen_lesen() or [{}])[0]
    pruefe(z.get("d") == "wissensgraph_extraktion" and z.get("m") == "modell-b",
           "Dienst bleibt hinter asyncio.gather (Task-Grenze) richtig", str(z))

    leeren()
    asyncio.run(m_main["_sec_llm_classify"](Gemacht(antwort({"input_tokens": 1, "output_tokens": 1}))))
    z = (zeilen_lesen() or [{}])[0]
    pruefe(z.get("d") == "sicherheitspruefung", "Funktion mit eigenem Dienst (main._sec_llm_classify)", z.get("d"))

    leeren()
    asyncio.run(m_wg["direkt"](Gemacht(antwort({"input_tokens": 10, "output_tokens": 3,
                                                 "cache_read_input_tokens": 500,
                                                 "cache_creation_input_tokens": 40}))))
    z = (zeilen_lesen() or [{}])[0]
    pruefe(z.get("ein") == 550 and z.get("cl") == 500 and z.get("cs") == 40,
           "Eingabe = input + Cache-Lesen + Cache-Schreiben (Anthropic)", str(z))

    leeren()
    asyncio.run(m_wg["direkt"](Gemacht(antwort(None))))
    z = (zeilen_lesen() or [{}])[0]
    pruefe("ein" in z and z["ein"] is None and z["aus"] is None,
           "ohne Zaehlung des Anbieters: None, NICHT geschaetzt", str(z))

    leeren()
    try:
        asyncio.run(m_wg["direkt"](Gemacht(wirf=RuntimeError("weg"))))
        geworfen = False
    except RuntimeError:
        geworfen = True
    z = (zeilen_lesen() or [{}])[0]
    pruefe(geworfen, "Fehler des Modellaufrufs geht unveraendert an den Aufrufer")
    pruefe(z.get("f") == 1 and z.get("ein") is None, "Fehlschlag wird als Zeile mit Kennung erfasst", str(z))

    leeren()
    asyncio.run(m_wg["direkt"](Gemacht(antwort({"input_tokens": 1, "output_tokens": 1},
                                                 werkzeuge=("knowledge_search", "shell_execute", "knowledge_search")))))
    z = (zeilen_lesen() or [{}])[0]
    pruefe(z.get("w") == ["knowledge_search", "shell_execute"],
           "angeforderte Werkzeuge der Antwort (ohne Dopplung)", str(z.get("w")))

    leeren()

    async def im_werkzeug():
        marke = tv.werkzeug_cv.set("bild_text")
        try:
            return await m_wg["direkt"](Gemacht(antwort({"input_tokens": 1, "output_tokens": 1},
                                                         werkzeuge=("andere",))))
        finally:
            tv.werkzeug_cv.reset(marke)

    asyncio.run(im_werkzeug())
    z = (zeilen_lesen() or [{}])[0]
    pruefe(z.get("w") == ["bild_text"], "laufendes Werkzeug hat Vorrang vor angeforderten", str(z.get("w")))

    # Benutzer und Kanal ueber die Kontexte, die das Produkt wirklich setzt.
    leeren()
    fremd_agent = "backend.agent" not in sys.modules
    fremd_wirkung = "backend.wirkung" not in sys.modules
    if fremd_agent:
        ag = types.ModuleType("backend.agent")
        ag._actor_cv = contextvars.ContextVar("probe_actor", default=None)
        sys.modules["backend.agent"] = ag
    if fremd_wirkung:
        wk = types.ModuleType("backend.wirkung")
        wk.auftrag_cv = contextvars.ContextVar("probe_auftrag", default=None)
        sys.modules["backend.wirkung"] = wk
    ag = sys.modules["backend.agent"]
    wk = sys.modules["backend.wirkung"]

    async def mit_kontext():
        a = ag._actor_cv.set(("beispiel\\a.nutzer", False))
        k = wk.auftrag_cv.set(types.SimpleNamespace(quelle="Cron-Auftrag 'Bericht'"))
        try:
            await m_wg["direkt"](Gemacht(antwort({"input_tokens": 1, "output_tokens": 1})))
            kk = tv.kanal_cv.set("windows_desktop")
            try:
                await m_wg["direkt"](Gemacht(antwort({"input_tokens": 1, "output_tokens": 1})))
            finally:
                tv.kanal_cv.reset(kk)
        finally:
            ag._actor_cv.reset(a)
            wk.auftrag_cv.reset(k)

    asyncio.run(mit_kontext())
    z = zeilen_lesen()
    pruefe(len(z) == 2 and z[0].get("u") == "beispiel\\a.nutzer", "Benutzer aus dem Auftraggeber des Laufs",
           str([x.get("u") for x in z]))
    pruefe(len(z) == 2 and z[0].get("k") == "Cron-Auftrag", "Kanal aus der Auftragsquelle (gekuerzt)",
           str([x.get("k") for x in z]))
    pruefe(len(z) == 2 and z[1].get("k") == "windows_desktop", "Kanal des Laufs hat Vorrang")
    if fremd_agent:
        del sys.modules["backend.agent"]
    if fremd_wirkung:
        del sys.modules["backend.wirkung"]

    leeren()
    asyncio.run(m_wg["direkt"](Gemacht(antwort({"input_tokens": 1, "output_tokens": 1}))))
    z = (zeilen_lesen() or [{}])[0]
    pruefe(z.get("u") == "" and z.get("k") == "", "ausserhalb jedes Kontexts: leer (System/Hintergrund)", str(z))

    # Speicherfehler kostet keinen Modellaufruf
    leeren()
    alt_dir = tv._DIR
    tv._DIR = SANDKASTEN / "datei_statt_ordner"
    tv._DIR.write_text("x")
    try:
        r = asyncio.run(m_wg["direkt"](Gemacht(antwort({"input_tokens": 1, "output_tokens": 1}))))
        pruefe(r is not None and r.usage, "nicht speicherbar -> Antwort kommt trotzdem an")
    except Exception as e:  # noqa: BLE001
        pruefe(False, "nicht speicherbar -> Antwort kommt trotzdem an", repr(e))
    tv._DIR.unlink()
    tv._DIR = alt_dir

    # ── 3 ────────────────────────────────────────────────────────────────────
    abschnitt("3. Kein Doppelzaehlen bei verschachtelter Huelle")

    class Unter(Gemacht):
        async def _roh2(self, *a, **kw):
            return await Gemacht.generate_response(self, *a, **kw)

    Unter.generate_response = tv.umhuellen(Unter._roh2)
    leeren()
    asyncio.run(m_wg["direkt"](Unter(antwort({"input_tokens": 7, "output_tokens": 2}))))
    z = zeilen_lesen()
    pruefe(len(z) == 1 and z[0].get("ein") == 7, "aeussere Huelle zaehlt, innere reicht durch", str(len(z)))

    # ── 4 ────────────────────────────────────────────────────────────────────
    abschnitt("4. Auswertung")
    leeren()
    jetzt = time.time()
    modelle = [f"m{i}" for i in range(11)]
    for i, m in enumerate(modelle):                 # 11 Modelle, absteigende Menge
        for j in range(3):
            tv.erfassen(anbieter="an", modell=m, usage={"input_tokens": 1000 - i * 50, "output_tokens": 10},
                        dauer_ms=100, fehler=False, benutzer=("BEISPIEL\\A.Nutzer" if i % 2 else "b.nutzer"),
                        dienst="agent" if i < 5 else "loesungsarchiv",
                        kanal="" if i == 3 else "browser",
                        werkzeuge=["knowledge_search", "shell_execute"] if i == 0 else (["knowledge_search"] if i == 1 else []),
                        ts=jetzt - 86400 * j - 60)
    tv.erfassen(anbieter="an", modell="m0", usage=None, dauer_ms=5, fehler=True, benutzer="",
                dienst="agent", kanal="", werkzeuge=[], ts=jetzt - 120)
    tv.erfassen(anbieter="an", modell="alt", usage={"input_tokens": 9, "output_tokens": 9},
                dauer_ms=5, fehler=False, benutzer="", dienst="agent", kanal="", werkzeuge=[],
                ts=jetzt - 86400 * 20)            # ausserhalb von 7 Tagen

    e = tv.auswerten(7, "llm", {}, jetzt=jetzt)
    s = e["summe"]
    pruefe(s["aufrufe"] == 34, "Aufrufe im Zeitraum (ohne den 20 Tage alten)", str(s["aufrufe"]))
    erwartet_ein = sum((1000 - i * 50) * 3 for i in range(11))
    pruefe(s["ein"] == erwartet_ein and s["aus"] == 330, "Summen Eingabe/Ausgabe", f"{s['ein']} / {s['aus']}")
    pruefe(s["ohne_angabe"] == 1 and s["fehler"] == 1, "ohne Angabe und Fehlschlag gezaehlt, nicht in den Summen")
    reihen_ein = sum(sum(r["ein"]) for r in e["reihen"])
    reihen_aus = sum(sum(r["aus"]) for r in e["reihen"])
    pruefe(reihen_ein == s["ein"] and reihen_aus == s["aus"], "Summe aller Reihen == Gesamtsumme",
           f"{reihen_ein} / {s['ein']}")
    pruefe(sum(sum(r["aufrufe"]) for r in e["reihen"]) == s["aufrufe"], "Aufrufe aller Reihen == Gesamt")
    pruefe(len(e["reihen"]) == tv.MAX_REIHEN + 1 and e["reihen"][-1]["schluessel"] == tv.UEBRIGE
           and e["reihen"][-1].get("anzahl") == 11 - tv.MAX_REIHEN,
           "hoechstens MAX_REIHEN eigene Reihen, Rest als Uebrige mit Anzahl",
           str([r["schluessel"] for r in e["reihen"]]))
    pruefe(e["reihen"][0]["schluessel"] == "an · m0", "groesste Gruppe zuerst", e["reihen"][0]["schluessel"])
    pruefe(len(e["tabelle"]) == 11, "Tabelle nennt ALLE Gruppen (auch die zusammengefassten)", str(len(e["tabelle"])))
    pruefe(e["raster"] == "tag" and all(len(r["ein"]) == len(e["zeitachse"]) for r in e["reihen"]),
           "Tagesraster, jede Reihe so lang wie die Zeitachse")
    pruefe(7 <= len(e["zeitachse"]) <= 9, "Zeitachse ueber 7 Tage", str(len(e["zeitachse"])))
    pruefe(tv.auswerten(1, "llm", {}, jetzt=jetzt)["raster"] == "stunde", "24 Stunden -> Stundenraster")

    # Filter in der ANZEIGEFORM (Domaene, andere Schreibweise) – in der
    # normierten Form waere die Pruefung trivial wahr.
    f = tv.auswerten(7, "benutzer", {"benutzer": "Beispiel\\A.NUTZER"}, jetzt=jetzt)
    pruefe(f["summe"]["aufrufe"] == 15, "Benutzerfilter vergleicht normiert (Domaene, Gross/klein)",
           str(f["summe"]["aufrufe"]))
    pruefe([r["schluessel"] for r in f["reihen"]] == ["a.nutzer"], "Gruppe Benutzer normiert")
    f = tv.auswerten(7, "kanal", {"kanal": ""}, jetzt=jetzt)
    pruefe(f["summe"]["aufrufe"] == 4, "leerer Filterwert ist ein gueltiger Filter (Hintergrund)",
           str(f["summe"]["aufrufe"]))
    f = tv.auswerten(7, "llm", {"kanal": "*"}, jetzt=jetzt)
    pruefe(f["summe"]["aufrufe"] == 34, "'*' heisst alle")
    f = tv.auswerten(7, "werkzeug", {"werkzeug": "knowledge_search"}, jetzt=jetzt)
    pruefe(f["summe"]["aufrufe"] == 6, "Werkzeugfilter trifft jede Zeile, die das Werkzeug ENTHAELT",
           str(f["summe"]["aufrufe"]))
    pruefe({r["schluessel"] for r in f["reihen"]} == {"knowledge_search", "knowledge_search, shell_execute"},
           "mehrere Werkzeuge als EINE Kombination (keine Doppelzaehlung)",
           str([r["schluessel"] for r in f["reihen"]]))
    f = tv.auswerten(7, "llm", {"dienst": "loesungsarchiv"}, jetzt=jetzt)
    pruefe(set(f["optionen"]["dienst"]) == {"agent", "loesungsarchiv"},
           "Auswahllisten aus dem UNGEFILTERTEN Zeitraum")
    pruefe("alt" not in " ".join(f["optionen"]["llm"]), "Auswahllisten nur aus dem Zeitraum")
    pruefe(tv.auswerten(7, "unsinn", {}, jetzt=jetzt)["gruppe"] == "llm", "unbekannte Gruppe -> llm")
    pruefe(abs(tv.erfasst_seit() - (jetzt - 86400 * 20)) < 2, "erfasst_seit nennt die aelteste Zeile")

    # ── 5 ────────────────────────────────────────────────────────────────────
    abschnitt("5. Alterung")
    vorher = len(zeilen_lesen())
    schnitt = jetzt - 86400 * 1.5
    weg = tv.prune_older_than(schnitt)
    nachher = zeilen_lesen()
    pruefe(all(z["ts"] >= schnitt for z in nachher), "keine Zeile vor dem Schnitt bleibt")
    pruefe(weg == vorher - len(nachher) and weg > 0, "Rueckgabe = Zahl entfernter Zeilen", f"{weg} / {vorher - len(nachher)}")
    pruefe(any(z["ts"] >= schnitt for z in nachher), "juengere Zeilen bleiben (Positivkontrolle)")
    alt_datei = tv._datei(jetzt - 86400 * 20)
    pruefe(not alt_datei.exists(), "ganze alte Tagesdatei entfernt")

    # Die Datei DES Schnitttags: eine Zeile davor, eine danach – im SELBEN Tag.
    # Ohne diesen Aufbau haengt es an der Uhrzeit des Laufs, ob der Schnitttag
    # ueberhaupt eine Zeile vor dem Schnitt hat (Gegenprobe blieb stumm).
    leeren()
    lt = time.localtime(jetzt - 86400 * 3)
    mittag = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 12, 0, 0, 0, 0, -1))
    for ts in (mittag - 3600, mittag + 3600):
        tv.erfassen(anbieter="an", modell="m", usage={"input_tokens": 1, "output_tokens": 1},
                    dauer_ms=1, fehler=False, benutzer="", dienst="d", kanal="", werkzeuge=[], ts=ts)
    pruefe(tv._datei(mittag - 3600) == tv._datei(mittag + 3600), "Positivkontrolle: beide Zeilen im selben Tag")
    pruefe(tv.prune_older_than(mittag) == 1, "Schnitttag: die Zeile davor faellt")
    rest = zeilen_lesen()
    pruefe(len(rest) == 1 and rest[0]["ts"] >= mittag, "… die Zeile danach bleibt", str(rest))

    # ── 6 ────────────────────────────────────────────────────────────────────
    abschnitt("6. Verdrahtung (Syntaxbaum)")
    main_baum = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
    ep = next((n for n in ast.walk(main_baum) if isinstance(n, ast.AsyncFunctionDef)
               and n.name == "api_logs_token_verbrauch"), None)
    pruefe(ep is not None, "Endpunkt vorhanden")
    if ep is not None:
        deps = [ast.unparse(d) for d in ep.args.defaults]
        pruefe("Depends(require_local_auth)" in deps, "nur Administratoren (require_local_auth)", str(deps))
        deko = [ast.unparse(d) for d in ep.decorator_list]
        pruefe(deko == ["app.get('/api/logs/token_verbrauch')"], "GET /api/logs/token_verbrauch", str(deko))

    lr = ast.parse((ROOT / "backend" / "log_retention.py").read_text(encoding="utf-8"))
    run_all = next(n for n in ast.walk(lr) if isinstance(n, ast.FunctionDef) and n.name == "run_all")
    genannt = {n.id for n in ast.walk(run_all) if isinstance(n, ast.Name)}
    pruefe("_prune_token_verbrauch" in genannt, "Alterung laeuft im Tageslauf mit")
    pr = next((n for n in ast.walk(lr) if isinstance(n, ast.FunctionDef) and n.name == "_prune_token_verbrauch"), None)
    pruefe(pr is not None and "token_verbrauch.prune_older_than" in ast.unparse(pr), "und ruft prune_older_than")

    agent_baum = ast.parse((ROOT / "backend" / "agent.py").read_text(encoding="utf-8"))

    def methode(name):
        return next((n for n in ast.walk(agent_baum)
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name), None)

    def tv_aliase(knoten):
        """Namen, unter denen backend.token_verbrauch in der Funktion importiert ist.

        NICHT ueber die Endung des Aufrufs: wirkung.py hat eine GLEICHNAMIGE
        ``kanal_cv`` (Bestaetigungskanal), und ``_wirkung.kanal_cv.set`` steht in
        run_task – eine Endungs-Pruefung war damit trivial wahr (Gegenprobe
        "Kanal wird nicht gesetzt" blieb stumm, 2026-11-13)."""
        namen = set()
        for n in ast.walk(knoten):
            if isinstance(n, ast.ImportFrom) and n.module == "backend":
                namen |= {a.asname or a.name for a in n.names if a.name == "token_verbrauch"}
        return namen

    def ruft(knoten, attr, aliase):
        return [n for n in ast.walk(knoten) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Attribute)
                and isinstance(n.func.value.value, ast.Name)
                and n.func.value.value.id in aliase
                and ast.unparse(n.func.value).split(".", 1)[1] + "." + n.func.attr == attr]

    def in_finally(knoten, attr, aliase):
        for t in ast.walk(knoten):
            if isinstance(t, ast.Try):
                for st in t.finalbody:
                    if ruft(st, attr, aliase):
                        return True
        return False

    ex = methode("_execute_tool")
    al = tv_aliase(ex) if ex is not None else set()
    pruefe(bool(al), "_execute_tool importiert backend.token_verbrauch", str(al))
    pruefe(ex is not None and ruft(ex, "werkzeug_cv.set", al), "_execute_tool setzt das laufende Werkzeug")
    pruefe(ex is not None and in_finally(ex, "werkzeug_cv.reset", al), "… und nimmt es im finally zurueck")
    rt = methode("run_task")
    al = tv_aliase(rt) if rt is not None else set()
    pruefe(bool(al), "run_task importiert backend.token_verbrauch", str(al))
    pruefe(rt is not None and ruft(rt, "kanal_cv.set", al), "run_task setzt den Kanal (token_verbrauch, nicht wirkung)")
    pruefe(rt is not None and in_finally(rt, "kanal_cv.reset", al), "… und nimmt ihn im finally zurueck")

    llm_baum = ast.parse((ROOT / "backend" / "llm.py").read_text(encoding="utf-8"))
    basis = next(n for n in ast.walk(llm_baum) if isinstance(n, ast.ClassDef) and n.name == "LLMProvider")
    sub = next((n for n in basis.body if isinstance(n, ast.FunctionDef) and n.name == "__init_subclass__"), None)
    pruefe(sub is not None and any(ast.unparse(c.func) == "token_verbrauch.umhuellen"
                                   for c in ast.walk(sub) if isinstance(c, ast.Call)),
           "LLMProvider.__init_subclass__ umhuellt")
finally:
    shutil.rmtree(SANDKASTEN, ignore_errors=True)

bilanz()
