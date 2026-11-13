"""Token-Verbrauch je Modellaufruf – Erfassung und Auswertung.

WOZU (Anforderung 2026-11-13)
-----------------------------
Unter Einstellungen -> Protokolle soll sichtbar sein, WELCHE Datenmengen mit
den Sprachmodellen ausgetauscht wurden: ueber die Zeit, und aufteilbar nach
Modell, Benutzer, Dienst, Werkzeug und Kanal. Der LLM-Verlauf (``conv_log``)
kann das nicht: er kennt nur Agentenlaeufe, keine Tokenzahlen und keinen der
rund dreissig Modellaufrufe ausserhalb des Agenten (Wissensgraph,
Sicherheitspruefung, Loesungsarchiv, Fehleranalyse …).

EINE STELLE FUER ALLE AUFRUFE
-----------------------------
Erfasst wird in ``LLMProvider.__init_subclass__`` (``backend/llm.py``): jede
Provider-Klasse dieses Moduls bekommt ihr ``generate_response`` umhuellt. Die
Alternative – jeden der Aufrufer einzeln auszustatten – waere an dem Tag
unvollstaendig, an dem jemand einen neuen Aufruf schreibt, und die fehlende
Stelle meldete sich nicht (Register: „eine gepflegte Liste ist eine
Zeitbombe").

Die Huelle ist bewusst eine GEWOEHNLICHE Funktion, die eine Koroutine
zurueckgibt: Herkunft (Dienst) und Kontext (Benutzer, Kanal, Werkzeug) werden
beim AUFRUF gelesen, also im Rahmen des Aufrufers. Innerhalb der Koroutine
waere die Aufrufkette nach ``asyncio.gather``/``create_task`` an der
Task-Grenze abgeschnitten, und der Dienst hiesse dann „unbekannt".

Nur Klassen aus ``backend.llm`` werden umhuellt – Attrappen in Tests leiten
ebenfalls von ``LLMProvider`` ab und sollen den echten Bestand nicht fuellen.

WAS GESPEICHERT WIRD – UND WAS NICHT
------------------------------------
Je Aufruf eine Zeile in ``data/logs/token/<JJJJ-MM-TT>.jsonl``: Zeit, Anbieter,
Modell, Benutzer, Dienst, Kanal, Werkzeuge, Tokens (Eingabe/Ausgabe/Cache),
Dauer, Fehlerkennung. **Kein Inhalt** – weder Prompt noch Antwort. Die
Inhalte stehen (fuer Agentenlaeufe) im LLM-Verlauf und haben dort ihre eigene,
kuerzere Frist.

Liefert ein Anbieter keine Zaehlung (Sitzungs-Zugang, manche lokalen Server),
steht ``ein``/``aus`` auf ``None`` und der Aufruf zaehlt als „ohne Angabe".
**Er wird NICHT geschaetzt:** eine geschaetzte Zahl saehe in der Summe aus wie
eine gemessene, und die Anzeige behauptete einen Zustand, den sie nicht kennt.

Eingabe-Tokens sind die GESAMTE Eingabe: Anthropic zaehlt Cache-Lese- und
Cache-Schreib-Tokens getrennt von ``input_tokens`` – ohne sie fehlte bei einem
gut gecachten Agentenlauf der groesste Teil der uebertragenen Menge.

ALTERUNG
--------
Wie alle Protokolle nur nach Alter (``log_retention``), keine Mengengrenze.
Eine Tagesdatei je Tag macht das Aufraeumen billig (ganze Dateien loeschen)
und begrenzt das Lesen auf den angefragten Zeitraum.
"""

from __future__ import annotations

import contextvars
import json
import os
import sys
import threading
import time
from pathlib import Path

_DATA_DIR = Path(__file__).parent.parent / "data"
_DIR = _DATA_DIR / "logs" / "token"

_lock = threading.Lock()

# Werkzeug, das GERADE ausgefuehrt wird (gesetzt in agent._execute_tool fuer die
# Dauer eines Aufrufs). Ruft ein Werkzeug selbst ein Modell (bild_text,
# reflection, jira_org_analysis …), gehoert der Verbrauch diesem Werkzeug.
werkzeug_cv: contextvars.ContextVar = contextvars.ContextVar(
    "jarvis_token_werkzeug", default="")

# Kanal des aeussersten Agentenlaufs (client_type aus run_task: browser,
# whatsapp, windows_desktop …). Unter-Agenten erben ihn.
kanal_cv: contextvars.ContextVar = contextvars.ContextVar(
    "jarvis_token_kanal", default="")

# Schutz gegen DOPPELTES Zaehlen: ruft eine umhuellte generate_response eine
# andere umhuellte (Unterklasse -> super()), zaehlt nur die aeussere.
_in_erfassung: contextvars.ContextVar = contextvars.ContextVar(
    "jarvis_token_in_erfassung", default=False)

# Dimensionen der Auswertung (Schluessel in der Zeile -> Name in der API).
DIMENSIONEN = ("llm", "benutzer", "dienst", "werkzeug", "kanal")

# Hoechstzahl eigener Reihen im Diagramm; der Rest wird zu „Uebrige".
MAX_REIHEN = 8
UEBRIGE = "__uebrige__"

# Laengster abfragbarer Zeitraum. Mehr haelt die Aufbewahrung ohnehin selten
# vor, und ein Jahr Tagesdateien zu parsen ist fuer eine Ansicht genug Arbeit.
MAX_TAGE = 366


# ─── Herkunft: welcher Dienst ruft? ──────────────────────────────────────────

# Funktionen, die innerhalb eines Moduls einen EIGENEN Dienst darstellen.
# Alles andere heisst nach seinem Modul (letzter Namensteil). Eine fehlende
# Zeile hier ist harmlos: der Aufruf erscheint dann unter dem Modulnamen.
_FUNKTIONS_DIENSTE = {
    ("backend.agent", "_compress_history"): "kontext_kompression",
    ("backend.main", "_sec_llm_classify"): "sicherheitspruefung",
    ("backend.main", "_feedback_self_improve"): "feedback",
    ("backend.main", "_support_ai_summary"): "support",
    ("backend.main", "_support_summarize_block"): "support",
}

# Module, die nur durchreichen und deshalb nie als Dienst gelten.
_DURCHREICHER = ("backend.llm", __name__, "asyncio", "contextlib", "functools")


def _herkunft(tiefe: int = 2, max_rahmen: int = 40) -> str:
    """Dienst-Kennung aus der Aufrufkette (erster Rahmen ausserhalb von llm.py)."""
    try:
        f = sys._getframe(tiefe)
    except ValueError:
        return "unbekannt"
    n = 0
    while f is not None and n < max_rahmen:
        mod = f.f_globals.get("__name__", "") or ""
        if mod and not mod.startswith(_DURCHREICHER):
            fn = f.f_code.co_name
            eigen = _FUNKTIONS_DIENSTE.get((mod, fn))
            if eigen:
                return eigen
            return mod.rsplit(".", 1)[-1] or "unbekannt"
        f = f.f_back
        n += 1
    return "unbekannt"


# ─── Kontext: wer, ueber welchen Kanal? ──────────────────────────────────────

def _benutzer() -> str:
    """Auftraggeber des Aufrufs – fail-safe leer (= „System")."""
    # 1. Agentenlauf: der Actor des laufenden Auftrags.
    ag = sys.modules.get("backend.agent")
    cv = getattr(ag, "_actor_cv", None) if ag else None
    if cv is not None:
        try:
            wert = cv.get()
            if wert and wert[0]:
                return str(wert[0])
        except Exception:  # noqa: BLE001
            pass
    # 2. Werkzeug-Aufruf eines unprivilegierten Benutzers.
    sb = sys.modules.get("backend.sandbox")
    if sb is not None:
        try:
            u = sb.tool_user()
            if u:
                return str(u)
        except Exception:  # noqa: BLE001
            pass
    # 3. HTTP-Anfrage: das Sitzungskonto (Prompt-Pruefung, Jira-Assistent …).
    mn = sys.modules.get("backend.main")
    cv = getattr(mn, "_sitzung_kontext", None) if mn else None
    if cv is not None:
        try:
            wert = cv.get()
            if wert and wert[0]:
                return str(wert[0])
        except Exception:  # noqa: BLE001
            pass
    return ""


def _kanal() -> str:
    """Kanal des Aufrufs: client_type eines Agentenlaufs, sonst die Quelle eines
    headless-Auftrags (Cron, WhatsApp, Agent-API, Mail-Regel …), sonst leer."""
    k = kanal_cv.get()
    if k:
        return str(k)[:40]
    wk = sys.modules.get("backend.wirkung")
    cv = getattr(wk, "auftrag_cv", None) if wk else None
    if cv is not None:
        try:
            a = cv.get()
            quelle = str(getattr(a, "quelle", "") or "")
            if quelle:
                # „Cron-Auftrag 'Bericht'" -> „Cron-Auftrag", „regel:17" -> „regel"
                for trenner in (" ", "(", ":", "'"):
                    quelle = quelle.split(trenner, 1)[0]
                return quelle[:40]
        except Exception:  # noqa: BLE001
            pass
    return ""


def _angeforderte_werkzeuge(resp) -> list[str]:
    """Namen der Werkzeuge, die die Antwort anfordert (Agentenschritt)."""
    namen: list[str] = []
    for p in (getattr(resp, "parts", None) or []):
        fc = getattr(p, "function_call", None)
        name = getattr(fc, "name", None) if fc is not None else None
        if name and str(name) not in namen:
            namen.append(str(name))
    return namen


def _zahl(v) -> int:
    try:
        return max(0, int(v or 0))
    except (TypeError, ValueError):
        return 0


# ─── Schreiben ───────────────────────────────────────────────────────────────

def _datei(ts: float) -> Path:
    return _DIR / (time.strftime("%Y-%m-%d", time.localtime(ts)) + ".jsonl")


def _anhaengen(zeile: dict) -> None:
    try:
        with _lock:
            _DIR.mkdir(parents=True, exist_ok=True)
            with _datei(zeile["ts"]).open("a", encoding="utf-8") as f:
                f.write(json.dumps(zeile, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception as e:  # noqa: BLE001
        # Die Statistik darf nie einen Modellaufruf kosten.
        print(f"[token_verbrauch] nicht gespeichert: {e}", flush=True)


def erfassen(*, anbieter: str, modell: str, usage, dauer_ms: int, fehler: bool,
             benutzer: str, dienst: str, kanal: str, werkzeuge: list[str],
             ts: float | None = None) -> dict:
    """Legt EINE Zeile ab und gibt sie zurueck (fuer Tests)."""
    zeile: dict = {
        "ts": round(ts if ts is not None else time.time(), 3),
        "an": str(anbieter or "")[:40],
        "m": str(modell or "")[:120],
        "u": str(benutzer or "")[:120],
        "d": str(dienst or "unbekannt")[:60],
        "k": str(kanal or "")[:40],
        "w": [str(w)[:80] for w in (werkzeuge or [])][:8],
        "ms": _zahl(dauer_ms),
    }
    if isinstance(usage, dict):
        cl = _zahl(usage.get("cache_read_input_tokens"))
        cs = _zahl(usage.get("cache_creation_input_tokens"))
        zeile["ein"] = _zahl(usage.get("input_tokens")) + cl + cs
        zeile["aus"] = _zahl(usage.get("output_tokens"))
        if cl:
            zeile["cl"] = cl
        if cs:
            zeile["cs"] = cs
    else:
        zeile["ein"] = None
        zeile["aus"] = None
    if fehler:
        zeile["f"] = 1
    _anhaengen(zeile)
    return zeile


def umhuellen(original):
    """Huelle um ``generate_response`` einer Provider-Klasse.

    Gewoehnliche Funktion (KEIN ``async def``), siehe Modul-Docstring: Kontext
    und Herkunft werden beim Aufruf im Rahmen des Aufrufers gelesen.
    """
    import functools

    @functools.wraps(original)
    def generate_response(self, *args, **kwargs):
        if _in_erfassung.get():
            return original(self, *args, **kwargs)
        modell = kwargs.get("model", args[0] if args else "")
        # Zur LAUFZEIT aus der Instanz: OpenRouter erbt die Huelle von
        # OpenAICompatibleProvider und soll trotzdem als openrouter erscheinen.
        anbieter = str(getattr(self, "anbieter_kennung", "") or type(self).__name__)
        kontext = {
            "dienst": _herkunft(2),
            "benutzer": _benutzer(),
            "kanal": _kanal(),
            "werkzeug": werkzeug_cv.get(),
        }

        async def _lauf():
            marke = _in_erfassung.set(True)
            t0 = time.monotonic()
            resp = None
            fehler = True
            try:
                resp = await original(self, *args, **kwargs)
                fehler = False
                return resp
            finally:
                _in_erfassung.reset(marke)
                try:
                    werkzeuge = ([kontext["werkzeug"]] if kontext["werkzeug"]
                                 else _angeforderte_werkzeuge(resp))
                    erfassen(anbieter=anbieter, modell=modell,
                             usage=getattr(resp, "usage", None),
                             dauer_ms=int((time.monotonic() - t0) * 1000),
                             fehler=fehler, benutzer=kontext["benutzer"],
                             dienst=kontext["dienst"], kanal=kontext["kanal"],
                             werkzeuge=werkzeuge)
                except Exception as e:  # noqa: BLE001
                    print(f"[token_verbrauch] Erfassung fehlgeschlagen: {e}", flush=True)

        return _lauf()

    generate_response.__token_erfassung__ = True
    return generate_response


# ─── Lesen und Auswerten ─────────────────────────────────────────────────────

def _tage_im_bereich(von: float, bis: float) -> list[Path]:
    """Tagesdateien, die den Bereich [von, bis] beruehren (aelteste zuerst)."""
    out = []
    t = time.localtime(von)
    tag = time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))
    while tag <= bis:
        out.append(_datei(tag + 3600))          # +1 h: robust gegen Zeitumstellung
        lt = time.localtime(tag + 86400 + 7200)
        tag = time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, 0, 0, 0, 0, 0, -1))
    return out


def _zeilen(von: float, bis: float):
    for p in _tage_im_bereich(von, bis):
        try:
            if not p.exists():
                continue
            with p.open("r", encoding="utf-8", errors="replace") as f:
                for roh in f:
                    roh = roh.strip()
                    if not roh:
                        continue
                    try:
                        z = json.loads(roh)
                    except Exception:  # noqa: BLE001
                        continue        # halb geschriebene Zeile
                    ts = z.get("ts") or 0
                    if von <= ts <= bis:
                        yield z
        except OSError:
            continue


def _norm_user(name: str) -> str:
    from backend.conv_log import norm_user
    return norm_user(name)


def _schluessel(z: dict, dim: str) -> list[str]:
    """Wert(e) einer Zeile fuer eine Dimension. Werkzeug kann mehrere haben."""
    if dim == "llm":
        an, m = z.get("an") or "", z.get("m") or ""
        return [f"{an} · {m}" if an and m else (m or an or "")]
    if dim == "benutzer":
        return [_norm_user(z.get("u") or "")]
    if dim == "dienst":
        return [z.get("d") or "unbekannt"]
    if dim == "kanal":
        return [z.get("k") or ""]
    if dim == "werkzeug":
        return list(z.get("w") or []) or [""]
    return [""]


def _gruppen_schluessel(z: dict, dim: str) -> str:
    """EIN Schluessel je Zeile fuer die Aufteilung: mehrere angeforderte
    Werkzeuge erscheinen als eine Kombination, damit kein Token doppelt
    gezaehlt wird (die Summe aller Reihen bleibt die Gesamtsumme)."""
    werte = _schluessel(z, dim)
    if dim == "werkzeug":
        return ", ".join(sorted(w for w in werte if w))
    return werte[0] if werte else ""


def raster_fuer(tage: float) -> str:
    return "stunde" if tage <= 2 else "tag"


def _eimer_start(ts: float, raster: str) -> float:
    t = time.localtime(ts)
    if raster == "stunde":
        return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, 0, 0, 0, 0, -1))
    return time.mktime((t.tm_year, t.tm_mon, t.tm_mday, 0, 0, 0, 0, 0, -1))


def _zeitachse(von: float, bis: float, raster: str) -> list[float]:
    achse = []
    e = _eimer_start(von, raster)
    schritt = 3600 if raster == "stunde" else 86400
    while e <= bis:
        achse.append(e)
        # ueber die Zeitumstellung hinweg: naechsten Eimer aus der Ortszeit ableiten
        e = _eimer_start(e + schritt + (0 if raster == "stunde" else 7200), raster)
    return achse


def auswerten(tage: float = 7, gruppe: str = "llm", filter_: dict | None = None,
              jetzt: float | None = None) -> dict:
    """Verdichtet die Zeilen der letzten ``tage`` Tage.

    ``filter_``: {Dimension: Wert} – UND-verknuepft; Benutzer wird normiert
    verglichen (wie im LLM-Verlauf), Werkzeug trifft jede Zeile, die das
    Werkzeug ENTHAELT.
    """
    gruppe = gruppe if gruppe in DIMENSIONEN else "llm"
    tage = min(max(float(tage or 7), 1 / 24), MAX_TAGE)
    bis = float(jetzt if jetzt is not None else time.time())
    von = bis - tage * 86400
    raster = raster_fuer(tage)
    achse = _zeitachse(von, bis, raster)
    index = {e: i for i, e in enumerate(achse)}

    filt = {}
    for k, v in (filter_ or {}).items():
        if k in DIMENSIONEN and v is not None and v != "*":
            filt[k] = _norm_user(v) if k == "benutzer" else str(v)

    optionen: dict[str, dict[str, int]] = {d: {} for d in DIMENSIONEN}
    gruppen: dict[str, dict] = {}
    summe = {"aufrufe": 0, "ein": 0, "aus": 0, "cache_lesen": 0,
             "ohne_angabe": 0, "fehler": 0}

    for z in _zeilen(von, bis):
        # Auswahllisten aus dem UNGEFILTERTEN Bestand des Zeitraums – sonst
        # verschwaende eine Option, sobald ein anderer Filter sie ausschliesst,
        # und man kaeme ohne Zuruecksetzen nicht mehr zu ihr.
        for d in DIMENSIONEN:
            for w in _schluessel(z, d):
                optionen[d][w] = optionen[d].get(w, 0) + 1
        if any(f not in _schluessel(z, d) for d, f in filt.items()):
            continue
        ein, aus = z.get("ein"), z.get("aus")
        ohne = ein is None and aus is None
        ein, aus = _zahl(ein), _zahl(aus)
        summe["aufrufe"] += 1
        summe["ein"] += ein
        summe["aus"] += aus
        summe["cache_lesen"] += _zahl(z.get("cl"))
        summe["ohne_angabe"] += 1 if ohne else 0
        summe["fehler"] += 1 if z.get("f") else 0

        g = _gruppen_schluessel(z, gruppe)
        eintrag = gruppen.get(g)
        if eintrag is None:
            eintrag = gruppen[g] = {
                "schluessel": g, "aufrufe": 0, "ein": 0, "aus": 0,
                "ohne_angabe": 0, "fehler": 0, "ms": 0,
                "ein_reihe": [0] * len(achse), "aus_reihe": [0] * len(achse),
                "aufrufe_reihe": [0] * len(achse),
            }
        eintrag["aufrufe"] += 1
        eintrag["ein"] += ein
        eintrag["aus"] += aus
        eintrag["ohne_angabe"] += 1 if ohne else 0
        eintrag["fehler"] += 1 if z.get("f") else 0
        eintrag["ms"] += _zahl(z.get("ms"))
        i = index.get(_eimer_start(z.get("ts") or 0, raster))
        if i is not None:
            eintrag["ein_reihe"][i] += ein
            eintrag["aus_reihe"][i] += aus
            eintrag["aufrufe_reihe"][i] += 1

    sortiert = sorted(gruppen.values(),
                      key=lambda g: (g["ein"] + g["aus"], g["aufrufe"]), reverse=True)
    reihen = []
    for g in sortiert[:MAX_REIHEN]:
        reihen.append({"schluessel": g["schluessel"], "ein": g["ein_reihe"],
                       "aus": g["aus_reihe"], "aufrufe": g["aufrufe_reihe"]})
    rest = sortiert[MAX_REIHEN:]
    if rest:
        n = len(achse)
        reihen.append({
            "schluessel": UEBRIGE, "anzahl": len(rest),
            "ein": [sum(g["ein_reihe"][i] for g in rest) for i in range(n)],
            "aus": [sum(g["aus_reihe"][i] for g in rest) for i in range(n)],
            "aufrufe": [sum(g["aufrufe_reihe"][i] for g in rest) for i in range(n)],
        })
    tabelle = [{k: g[k] for k in ("schluessel", "aufrufe", "ein", "aus",
                                  "ohne_angabe", "fehler", "ms")}
               for g in sortiert]

    return {
        "von": von, "bis": bis, "tage": tage, "raster": raster, "gruppe": gruppe,
        "filter": filt, "zeitachse": achse, "reihen": reihen, "tabelle": tabelle,
        "summe": summe,
        "optionen": {d: sorted(optionen[d], key=lambda w: (-optionen[d][w], w))
                     for d in DIMENSIONEN},
        "erfasst_seit": erfasst_seit(),
    }


def erfasst_seit() -> float | None:
    """Zeitstempel der aeltesten vorhandenen Zeile – damit ein leerer Zeitraum
    nicht wie „nichts passiert" aussieht, wenn die Erfassung erst seit gestern
    laeuft."""
    try:
        dateien = sorted(_DIR.glob("*.jsonl"))
    except OSError:
        return None
    for p in dateien:
        try:
            with p.open("r", encoding="utf-8", errors="replace") as f:
                for roh in f:
                    try:
                        return float(json.loads(roh).get("ts"))
                    except Exception:  # noqa: BLE001
                        continue
        except OSError:
            continue
    return None


# ─── Aufraeumen ──────────────────────────────────────────────────────────────

def prune_older_than(cutoff_ts: float) -> int:
    """Entfernt Zeilen vor ``cutoff_ts``; Rueckgabe: Anzahl entfernter Zeilen.

    Ganze Tagesdateien vor dem Schnitttag fallen weg; die Datei DES Schnitttags
    wird zeilenweise gefiltert (atomar ersetzt)."""
    entfernt = 0
    schnitt_datei = _datei(cutoff_ts).name
    with _lock:
        try:
            dateien = sorted(_DIR.glob("*.jsonl"))
        except OSError:
            return 0
        for p in dateien:
            if p.name > schnitt_datei:
                continue
            try:
                zeilen = p.read_text(encoding="utf-8", errors="replace").splitlines()
            except OSError:
                continue
            behalten = []
            for roh in zeilen:
                try:
                    ts = float(json.loads(roh).get("ts") or 0)
                except Exception:  # noqa: BLE001
                    # Unlesbare Zeile (halb geschrieben): sie traegt keinen Wert
                    # fuer die Auswertung und faellt mit ihrer Tagesdatei.
                    ts = 0.0
                if ts >= cutoff_ts:
                    behalten.append(roh)
            n = len([z for z in zeilen if z.strip()]) - len(behalten)
            if n <= 0:
                continue
            entfernt += n
            try:
                if behalten:
                    tmp = p.with_suffix(".jsonl.tmp")
                    tmp.write_text("\n".join(behalten) + "\n", encoding="utf-8")
                    os.replace(tmp, p)
                else:
                    p.unlink()
            except OSError as e:
                print(f"[token_verbrauch] Bereinigung {p.name}: {e}", flush=True)
    return entfernt
