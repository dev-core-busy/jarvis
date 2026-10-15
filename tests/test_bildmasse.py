#!/usr/bin/env python3
"""Tests: Bildaufloesung durchreichen (size/aspect_ratio) + Bild-API der
OpenAI-kompatiblen Provider.

WAS HIER ABGESICHERT WIRD – UND WARUM
-------------------------------------
Gemeldet von ECHT am 2026-09-02: "Die Rolle 'Bild-Erzeuger' nimmt keine
Anweisungen zur Aufloesung des zu erzeugenden Bildes an." Zutreffend, und es
waren DREI Ursachen, jede allein hinreichend:

1. Das Schema von ``generate_image`` kannte nur ``prompt``. Eine Groessenangabe
   konnte das Modell gar nicht uebergeben – sie landete im Bildprompt und wurde
   dort als BILDINHALT gelesen.
2. Die Provider-Signatur lautete ``generate_image(model, prompt)``; die
   Imagen-Config reichte allein ``number_of_images=1`` durch. Projektweit hatte
   ``aspect_ratio|image_size`` GENAU EINEN Treffer – eben diese Zeile.
3. ``OpenAICompatibleProvider`` hatte ueberhaupt kein ``generate_image``, also
   griff die Vorgabe der Basisklasse (``ImageGenNotSupported``). Im
   Produktiv-venv gegen das echte Rollen-Profil gemessen:

       Profil: FLUX.2-klein-4B | provider: openai_compatible
       generate_image ueberschrieben: False
       ERGEBNIS: ImageGenNotSupported

   Das Werkzeug war in der Bild-Rolle also TOT. Bilder entstanden trotzdem, aber
   als Nebenprodukt des gewoehnlichen Chat-Aufrufs (das Bildmodell antwortet mit
   base64, ``_bilddaten_bergen`` sammelt es ein) – und ein Chat-Aufruf hat kein
   Groessenfeld.

AM ECHTEN SERVER GEMESSEN (FLUX.2-klein-4B auf vLLM), das ist die Grundlage:
    Chat-Weg ohne Angabe             2 Laeufe -> 1024x1024
    Chat-Weg "Aufloesung 1536x640"   2 Laeufe -> 1024x1024  (wirkungslos)
    Chat-Weg englisch "1536x640 px"  1 Lauf   -> 1024x1024
    /v1/images/generations size=…    3 Laeufe -> 512x512, 1024x768, 1536x640
    1040x720 (Vielfaches von 16)     ->  9,6 s, exakt geliefert
    1000x700 (kein Vielfaches)       -> Server rundet SELBST auf 992x688
    2048x2048                        -> 78,2 s
    4096x4096                        -> HTTP 000 nach 180 s, keine Antwort

GEMESSEN, NICHT GELESEN
-----------------------
Beide Provider-Wege werden WIRKLICH AUSGEFUEHRT (httpx bzw. der genai-Client
durch eine Attrappe ersetzt) und der abgeschickte Payload eingefangen. Eine
Quelltext-Suche waere hier wertlos: sie bliebe gruen, wenn das Feld gebaut, aber
nie gesendet wird.

SANDKASTEN
----------
``image_gen._IMG_DIR`` wird in ein Wegwerf-Verzeichnis umgebogen und das
ausdruecklich nachgeprueft (Exit 2). Ohne das schreibt der Test in
``data/generated_images`` des laufenden Servers. ``backend.config`` wird
GESTUBBT – der echte Import migriert Profile und schreibt die Live-settings.json
zurueck (siehe tests/test_license.py).

    python3 tests/test_bildmasse.py
"""

import asyncio
import re
import shutil
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = 0
_fail = 0


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  ✓ {text}")
    else:
        _fail += 1
        print(f"  ✗ {text}" + (f" – {detail}" if detail else ""))


def sicher(fn, text):
    """Eine Pruefung darf NICHT werfen – sonst bricht der Lauf ab, statt
    fehlzuschlagen, und ein abgebrochener Waechter ist von einem nicht
    gelaufenen nicht zu unterscheiden (Register, mehrfach bezahlt)."""
    try:
        pruefe(fn(), text)
    except Exception as e:  # noqa: BLE001
        pruefe(False, text, f"wirft {type(e).__name__}: {e}")


def abschnitt(t):
    print(f"\n=== {t} ===")


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("1. Normalisierung (llm.bildmasse)")

from backend import llm  # noqa: E402

bm = llm.bildmasse

pruefe(bm(None, None) is None,
       "nichts angefordert -> None (kein Provider sendet ein Groessenfeld)")
pruefe(bm("", "") is None, "leere Strings zaehlen wie 'nichts angefordert'")

m = bm("1536x640", None)
pruefe(m["size"] == "1536x640" and m["breite"] == 1536 and m["hoehe"] == 640,
       "Pixelmasse werden uebernommen")
pruefe(m["verhaeltnis"] == "16:9", "Verhaeltnis wird fuer Google mitberechnet")
pruefe(m["image_size"] == "1K" and bm("2048x2048", None)["image_size"] == "2K",
       "image_size-Stufe folgt der laengeren Kante")
pruefe(m["hinweis"] == "", "ein exakt passendes Mass erzeugt keinen Hinweis")

pruefe(bm("1536×640", None)["size"] == "1536x640",
       "typografisches ×  wird verstanden (Modelle schreiben es so)")
pruefe(bm("1024 x 768 px", None)["size"] == "1024x768",
       "Leerzeichen und 'px' werden verstanden")
pruefe(bm("16:9", None)["verhaeltnis"] == "16:9",
       "ein Verhaeltnis im size-Feld wird angenommen, nicht abgewiesen")

# Nur ein Verhaeltnis: die Buckets muessen 64er-Masse sein – ein selbst
# gerechnetes 1365x768 ist bei FLUX/SDXL ein Artefakt-Kandidat.
r = bm(None, "16:9")
pruefe((r["breite"], r["hoehe"]) == (1344, 768), "16:9 -> 1344x768 (Diffusions-Bucket)")
pruefe(all(b % 64 == 0 and h % 64 == 0 for b, h in llm.BILD_BUCKETS.values()),
       "alle Buckets sind durch 64 teilbar")
pruefe(set(llm.BILD_BUCKETS) == set(llm.BILD_VERHAELTNISSE),
       "fuer JEDES unterstuetzte Verhaeltnis gibt es einen Bucket")

# Ein nicht unterstuetztes Verhaeltnis wird abgebildet UND benannt – Google
# nimmt nur die fuenf. Stillschweigend zu ersetzen waere die gemeldete
# Fehlerklasse: der Nutzer nennt eines und bekommt ein anderes.
u = bm(None, "21:9")
pruefe(u["verhaeltnis"] == "16:9" and "21:9" in u["hinweis"],
       "unbekanntes Verhaeltnis: naechstliegendes UND Hinweis")

# Rundung: der Server rundet sonst SELBST (1000x700 -> 992x688 gemessen) und
# niemand erfaehrt es.
g = bm("1000x700", None)
pruefe(g["breite"] % llm.BILD_RASTER == 0 and g["hoehe"] % llm.BILD_RASTER == 0,
       f"gerundet auf {llm.BILD_RASTER} px")
pruefe("1000x700" in g["hinweis"] and g["size"] in g["hinweis"],
       "die Anpassung wird BEZIFFERT (alt und neu), nicht stillschweigend")

k = bm("4096x4096", None)
pruefe(k["breite"] == llm.BILD_MAX_KANTE and "angepasst" in k["hinweis"],
       f"gekappt auf {llm.BILD_MAX_KANTE} px und ausgewiesen")
pruefe(bm("100x100", None)["breite"] == llm.BILD_MIN_KANTE,
       f"Untergrenze {llm.BILD_MIN_KANTE} px")
# Raster 16 ist GEMESSEN: 1040x720 lieferte der echte Server exakt aus, ein
# 64er-Raster haette daraus 1024x704 gemacht – also eine Abweichung, die
# niemand verlangt hat.
pruefe(llm.BILD_RASTER == 16, "Raster 16 (am echten Server belegt: 1040x720 exakt)")
pruefe(bm("1040x720", None)["size"] == "1040x720",
       "ein Vielfaches von 16 bleibt unangetastet")

# size GEWINNT gegen aspect_ratio – die konkretere Angabe.
pruefe(bm("512x512", "16:9")["size"] == "512x512", "size sticht aspect_ratio")

# Unbrauchbares wird ABGEWIESEN, nicht geraten.
for schlecht in ("riesig", "gross x klein", "abc", "12x", "x12"):
    try:
        bm(schlecht, None)
        pruefe(False, f"abgewiesen: {schlecht!r}")
    except llm.BildmassFehler as e:
        pruefe("unbrauchbar" in str(e) and ("BREITE" in str(e) or "aspect" in str(e)),
               f"abgewiesen MIT erwarteter Form: {schlecht!r}")
for schlecht in ("0:0", "16:0"):
    try:
        bm(None, schlecht)
        pruefe(False, f"abgewiesen: Verhaeltnis {schlecht!r}")
    except llm.BildmassFehler:
        pruefe(True, f"abgewiesen: Verhaeltnis {schlecht!r}")

pruefe(issubclass(llm.BildmassFehler, ValueError),
       "BildmassFehler ist ein ValueError (bestehende except-Zweige greifen)")


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("2. OpenAI-kompatibel: die Bild-API wird WIRKLICH aufgerufen")

import httpx  # noqa: E402

_HAT_GI = (llm.OpenAICompatibleProvider.generate_image
           is not llm.LLMProvider.generate_image)
pruefe(_HAT_GI, "OpenAICompatibleProvider ueberschreibt generate_image (war der Kernbefund)")


class _Antwort:
    def __init__(self, code=200, daten=None, text=""):
        self.status_code = code
        self._daten = daten
        self.text = text

    def json(self):
        if self._daten is None:
            raise ValueError("kein JSON")
        return self._daten


class _Client:
    """Attrappe des shared httpx-Clients. Faengt den Payload ein."""

    def __init__(self, antwort, get_antwort=None):
        self.antwort = antwort
        self.get_antwort = get_antwort
        self.posts = []
        self.gets = []

    async def post(self, url, headers=None, json=None, timeout=None):
        self.posts.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        if isinstance(self.antwort, Exception):
            raise self.antwort
        return self.antwort

    async def get(self, url, timeout=None):
        self.gets.append(url)
        return self.get_antwort


import base64 as _b64  # noqa: E402

# Ein WIRKLICH dekodierbares 1x1-PNG – Material, das ein echter Konsument nicht
# oeffnet, belegt nichts (Register).
_PNG_1x1 = _b64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8DwHwAFAAH/q842iQAAAABJRU5ErkJggg=="
)
_PNG_B64 = _b64.b64encode(_PNG_1x1).decode()


def _prov(url="http://server:9079/v1"):
    return llm.OpenAICompatibleProvider(api_key="geheim-schluessel-1234567890", base_url=url)


def _post(client, i=0):
    """Eingefangener Payload oder ein leeres dict – NIE ein IndexError."""
    return client.posts[i] if len(client.posts) > i else {"url": "", "headers": {},
                                                          "json": {}, "timeout": None}


def _lauf(client, prompt="ein Wuerfel", masse=None, prov=None):
    if not _HAT_GI:
        return None
    p = prov or _prov()
    orig = llm._get_shared_client

    async def _fake():
        return client
    llm._get_shared_client = _fake
    try:
        return asyncio.run(p.generate_image("modell-x", prompt, masse))
    finally:
        llm._get_shared_client = orig




# ── Der Endpunkt ─────────────────────────────────────────────────────────────
c = _Client(_Antwort(200, {"data": [{"b64_json": _PNG_B64}]}))
daten = _lauf(c, masse=bm("1536x640", None))
pruefe(daten == _PNG_1x1, "b64_json wird dekodiert und als Bytes zurueckgegeben")
pruefe(_post(c)["url"] == "http://server:9079/v1/images/generations",
       "Bild-URL aus derselben Basis wie der Chat-Endpunkt", _post(c)["url"])
pruefe(_post(c)["json"].get("size") == "1536x640",
       "DIE GROESSE WIRD WIRKLICH GESENDET", str(_post(c)["json"]))
pruefe(_post(c)["json"].get("model") == "modell-x" and _post(c)["json"].get("n") == 1,
       "Modell und n=1 gehen mit")
pruefe("Authorization" in (_post(c)["headers"] or {}),
       "der API-Key des Profils geht mit (der Server antwortet sonst 401)")

# Basis MIT /chat/completions (so baut __init__ sie) muss dasselbe ergeben.
c2 = _Client(_Antwort(200, {"data": [{"b64_json": _PNG_B64}]}))
_lauf(c2, masse=None, prov=_prov("http://server:9079/v1/chat/completions"))
pruefe(_post(c2)["url"] == "http://server:9079/v1/images/generations",
       "der Chat-Pfad wird ersetzt, nicht angehaengt", _post(c2)["url"])

# ── OHNE Groesse wird KEIN Feld gesendet ─────────────────────────────────────
# Das ist der Grund, warum es keinen stillen Rueckfall braucht: ein Server ohne
# Groessen-Unterstuetzung sieht das Feld nie und verhaelt sich wie vorher.
c3 = _Client(_Antwort(200, {"data": [{"b64_json": _PNG_B64}]}))
_lauf(c3, masse=None)
pruefe("size" not in _post(c3)["json"],
       "ohne Anforderung KEIN size-Feld (kein Verhaltensbruch fuer alte Server)")
pruefe("response_format" not in _post(c3)["json"],
       "kein response_format (vLLM kennt es nicht zwingend -> 400)")

# ── 404/405 = keine Bild-API, nicht 'fehlgeschlagen' ────────────────────────
for code in (404, 405):
    try:
        _lauf(_Client(_Antwort(code, None, "not found")))
        pruefe(False, f"HTTP {code} -> ImageGenNotSupported")
    except llm.ImageGenNotSupported:
        pruefe(True, f"HTTP {code} -> ImageGenNotSupported (richtige Aussage fuer Textserver)")
    except Exception as e:  # noqa: BLE001
        pruefe(False, f"HTTP {code} -> ImageGenNotSupported", f"kam {type(e).__name__}")

# ── Abgelehnte Groesse: sprechender Fehler, KEIN stiller Rueckfall ──────────
c4 = _Client(_Antwort(400, None, "invalid size parameter"))
try:
    _lauf(c4, masse=bm("1536x640", None))
    pruefe(False, "abgelehnte Groesse wirft")
except llm.ImageGenNotSupported:
    pruefe(False, "abgelehnte Groesse wirft", "wurde als 'nicht unterstuetzt' gemeldet")
except Exception as e:
    txt = str(e)
    pruefe("1536x640" in txt and "abgelehnt" in txt,
           "die Meldung nennt die beanstandete Groesse", txt[:90])
    pruefe("Ohne Groessenangabe" in txt, "und nennt den Weg (ohne Groesse erneut)")
pruefe(_HAT_GI and len(c4.posts) == 1,
       "KEIN zweiter Versuch ohne size – eine andere Aufloesung als verlangt "
       "waere der gemeldete Fehler eine Ebene hoeher")

# ── url-Form (OpenAI/DALL-E liefert per Vorgabe eine URL) ───────────────────
c5 = _Client(_Antwort(200, {"data": [{"url": "http://server/bild.png"}]}),
             get_antwort=_Antwort(200))
c5.get_antwort.content = _PNG_1x1
pruefe(_lauf(c5) == _PNG_1x1, "url-Form wird nachgeladen")
pruefe(_HAT_GI and c5.gets == ["http://server/bild.png"], "genau ein GET auf die Bild-URL")

# ── Fehlerlagen ohne Absturz ────────────────────────────────────────────────
for antwort, erwartet, was in [
    (_Antwort(200, {"data": []}), "Keine Bilddaten", "leere data-Liste"),
    (_Antwort(200, {"data": [{}]}), "weder b64_json noch url", "Eintrag ohne Nutzdaten"),
    (_Antwort(200, None, "<html>"), "kein JSON", "HTML statt JSON"),
    (_Antwort(500, None, "boom"), "HTTP 500", "Serverfehler"),
]:
    try:
        _lauf(_Client(antwort))
        pruefe(False, f"{was} -> Fehler")
    except Exception as e:  # noqa: BLE001
        pruefe(erwartet.lower() in str(e).lower(), f"{was} -> Klartext-Fehler", str(e)[:80])

# ── Der API-Key darf NICHT in der Fehlermeldung stehen ──────────────────────
c6 = _Client(_Antwort(500, None, "Fehler bei Bearer geheim-schluessel-1234567890"))
try:
    _lauf(c6)
except Exception as e:  # noqa: BLE001
    pruefe("geheim-schluessel-1234567890" not in str(e) and "***" in str(e),
           "der API-Key wird aus der Fehlermeldung entfernt (scrub_secrets)", str(e)[:80])

# ── Zertifikatspruefung: KEIN eigener Client mit verify=False ───────────────
# Eine stille Abschwaechung an einer Stelle, an der niemand sie sucht. Der
# Bildweg benutzt denselben Client wie der Chat-Weg.
_QUELLE = (ROOT / "backend" / "llm.py").read_text(encoding="utf-8")
# Geschnitten am eindeutigen Docstring-Satz, NICHT am n-ten Vorkommen von
# "async def generate_image": es gibt drei Definitionen (Basis, Gemini,
# OpenAI-kompatibel), und ein Index traf beim ersten Lauf den Gemini-Block –
# der Waechter meldete einen Fehler, den es nicht gab.
_GI_ROH = _QUELLE.split("Bildgenerierung ueber ``POST /v1/images/generations``")[-1]
_GI_ROH = _GI_ROH.split("def _apply_reasoning")[0]
# KOMMENTARFREI vergleichen – sonst liest der Waechter seine eigene Begruendung.
# Beim ersten Lauf genau so passiert: der Kommentar erklaert, warum es KEIN
# `verify=False` gibt, und nannte es dabei woertlich. Dreizehnter Fall dieser
# Klasse im Projekt.
_GI_BLOCK = "\n".join(z for z in _GI_ROH.splitlines() if not z.strip().startswith("#"))
pruefe("_bild_url()" in _GI_BLOCK and "b64_json" in _GI_BLOCK,
       "Positivkontrolle: der geschnittene Block IST der OpenAI-kompatible Bildweg")
pruefe("stille" in _GI_ROH and "stille" not in _GI_BLOCK,
       "Positivkontrolle: die Kommentare sind wirklich entfernt")
pruefe("verify=False" not in _GI_BLOCK,
       "der Bildweg baut KEINEN eigenen Client mit abgeschalteter Zertifikatspruefung")
pruefe("_get_shared_client()" in _GI_BLOCK,
       "er benutzt denselben Client wie der Chat-Weg")

# ── Eigenes Timeout: Bilder dauern laenger als Text ─────────────────────────
p = _prov()
t = p._bild_timeout()
pruefe(float(t.read) >= 300.0,
       f"Bild-Timeout mind. 300 s (2048x2048 brauchte gemessen 78 s) – ist {t.read}")
pruefe(_post(c)["timeout"] is not None, "das Timeout wird auch uebergeben")


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("3. Google/Imagen: aspect_ratio + image_size kommen in der Config an")


class _ImagenBild:
    def __init__(self, data):
        self.image = types.SimpleNamespace(image_bytes=data)


class _GenaiModels:
    def __init__(self, sammler):
        self.sammler = sammler

    def generate_images(self, model=None, prompt=None, config=None):
        self.sammler.append({"art": "imagen", "model": model, "prompt": prompt, "config": config})
        return types.SimpleNamespace(generated_images=[_ImagenBild(_PNG_1x1)])

    def generate_content(self, model=None, contents=None):
        self.sammler.append({"art": "gemini", "model": model, "contents": contents})
        blob = types.SimpleNamespace(data=_PNG_1x1)
        part = types.SimpleNamespace(inline_data=blob)
        cont = types.SimpleNamespace(parts=[part])
        return types.SimpleNamespace(candidates=[types.SimpleNamespace(content=cont)])


def _gemini_lauf(modell, masse, sammler):
    p = llm.GeminiProvider.__new__(llm.GeminiProvider)   # __init__ braucht einen echten Key
    p.client = types.SimpleNamespace(models=_GenaiModels(sammler))
    return asyncio.run(p.generate_image(modell, "ein Wuerfel", masse))


# Imagen-Weg: das Profil-Modell ist selbst ein Bildmodell -> erster Kandidat.
s = []
pruefe(_gemini_lauf("imagen-4.0-generate-001", bm("1536x640", None), s) == _PNG_1x1,
       "Imagen-Weg liefert die Bytes")
cfg = s[0]["config"]
sicher(lambda: getattr(cfg, "aspect_ratio", None) == "16:9",
       "aspect_ratio landet in der GenerateImagesConfig")
sicher(lambda: getattr(cfg, "image_size", None) == "1K",
       "image_size landet in der GenerateImagesConfig")
sicher(lambda: getattr(cfg, "number_of_images", None) == 1,
       "number_of_images bleibt 1")

# Ohne Anforderung darf NICHTS gesetzt werden (Verhalten wie vor dem Umbau).
s2 = []
_gemini_lauf("imagen-4.0-generate-001", None, s2)
sicher(lambda: getattr(s2[0]["config"], "aspect_ratio", None) is None,
       "ohne Anforderung kein aspect_ratio (kein Verhaltensbruch)")

# Gemini-Weg kennt kein Groessenfeld: die Angabe darf nur als eigene ZEILE am
# Ende des Prompts mitgehen – mitten im Motivtext wuerde sie zum Bildinhalt.
s3 = []
_gemini_lauf("gemini-2.5-flash-image", bm("1536x640", None), s3)
txt = s3[0]["contents"]
pruefe(txt.startswith("ein Wuerfel"), "der Motivtext steht unveraendert am Anfang")
pruefe("16:9" in txt and txt.index("16:9") > txt.index("Wuerfel"),
       "das Verhaeltnis steht DAHINTER, als eigene Zeile")
s4 = []
_gemini_lauf("gemini-2.5-flash-image", None, s4)
pruefe(s4[0]["contents"] == "ein Wuerfel",
       "ohne Anforderung bleibt der Prompt unangetastet")


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("4. Werkzeug generate_image: Schema, Durchreichen, Rueckmeldung")

# backend.config GESTUBBT – der echte Import schreibt die Live-settings.json
# zurueck (Register).
_dot = types.ModuleType("dotenv")
_dot.load_dotenv = lambda *a, **k: None
sys.modules.setdefault("dotenv", _dot)
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace()
sys.modules["backend.config"] = _cfg

from backend.tools import image_gen as IG  # noqa: E402

# ── SANDKASTEN ──────────────────────────────────────────────────────────────
_tmp = Path(tempfile.mkdtemp(prefix="jarvis_bildmasse_"))
IG._IMG_DIR = _tmp / "generated_images"
if not str(IG._IMG_DIR).startswith(str(_tmp)):
    print(f"ABBRUCH: _IMG_DIR zeigt auf {IG._IMG_DIR} – nicht in den Sandkasten!")
    sys.exit(2)
pruefe(str(IG._IMG_DIR).startswith(str(_tmp)),
       "Sandkasten aktiv (data/generated_images des Servers unberuehrt)")

tool = IG.GenerateImageTool()
sch = tool.parameters_schema()
props = sch.get("properties") or {}
# .get statt [] – ein fehlendes Feld muss FEHLSCHLAGEN, nicht den Lauf mit
# KeyError abbrechen (Register: eine Pruefung darf nicht werfen).
_p_size = props.get("size") or {"description": ""}
_p_ratio = props.get("aspect_ratio") or {"description": ""}
_p_prompt = props.get("prompt") or {"description": ""}
pruefe("size" in props and "aspect_ratio" in props,
       "das Schema hat size UND aspect_ratio (der Kernbefund: es hatte nur prompt)")
pruefe("1536x640" in _p_size["description"],
       "die Beschreibung nennt die erwartete Form mit Beispiel")
pruefe(all(v in _p_ratio["description"] for v in llm.BILD_VERHAELTNISSE),
       "die Verhaeltnisse werden aus llm.BILD_VERHAELTNISSE genannt (keine zweite Liste)")
pruefe(str(llm.BILD_MAX_KANTE) in _p_size["description"]
       and str(llm.BILD_RASTER) in _p_size["description"],
       "Grenzen und Raster kommen aus llm.py – laufen also nicht auseinander")
pruefe(sch["required"] == ["prompt"], "Groesse bleibt OPTIONAL")
pruefe(re.search(r"KEINE Pixelmasse", _p_prompt["description"]),
       "der prompt-Text verbietet Pixelmasse ausdruecklich")
pruefe("size" in tool.description and "NIEMALS in den Prompttext" in tool.description,
       "die Werkzeug-BESCHREIBUNG sagt es auch – sie wirkt in JEDER Rolle sofort, "
       "ohne gesaete Rollen-Prompts zu migrieren")


class _Prov:
    """Faengt ab, was das Werkzeug an den Provider uebergibt."""

    def __init__(self, daten=_PNG_1x1):
        self.daten = daten
        self.aufrufe = []

    async def generate_image(self, model, prompt, masse=None):
        self.aufrufe.append({"model": model, "prompt": prompt, "masse": masse})
        if isinstance(self.daten, Exception):
            raise self.daten
        return self.daten


def _tool_lauf(prov, **kw):
    # BEIDE Namen patchen: das Werkzeug benutzt seit 2026-09-02
    # `provider_fuer_bild` (Bildprofil), `provider_fuer_lauf` bleibt als
    # Rueckfall im Modul. Wird nur einer gestellt, ruft der Test den ECHTEN
    # Weg und bricht mit AttributeError am gestubbten config ab – genau so beim
    # Umbau passiert, und ein abgebrochener Waechter sieht wie ein nicht
    # gelaufener aus.
    o1, o2 = IG.provider_fuer_lauf, IG.provider_fuer_bild
    IG.provider_fuer_lauf = lambda **k: (prov, "modell-x")
    IG.provider_fuer_bild = lambda *a, **k: (prov, "modell-x")
    try:
        return asyncio.run(tool.execute(**kw))
    finally:
        IG.provider_fuer_lauf, IG.provider_fuer_bild = o1, o2


pv = _Prov()
erg = _tool_lauf(pv, prompt="ein Wuerfel", size="1536x640")
def _masse_von(prov):
    """Uebergebene Masse oder None – OHNE Index-/None-Zugriff, der werfen kann."""
    if not prov.aufrufe:
        return None
    return prov.aufrufe[0].get("masse")


_m0 = _masse_von(pv)
pruefe(isinstance(_m0, dict) and _m0.get("size") == "1536x640",
       "die Groesse wird an den Provider DURCHGEREICHT", str(_m0))
pruefe(bool(pv.aufrufe) and "1536x640" not in pv.aufrufe[0]["prompt"],
       "und landet NICHT im Bildprompt (dort waere sie Bildinhalt)")
pruefe("BILD_ERZEUGT" in erg and "/api/generated/" in erg,
       "die Markdown-Bildreferenz kommt weiterhin heraus")

# Feldnamen, die Modelle stattdessen benutzen.
for feld in ("aufloesung", "resolution", "groesse"):
    p2 = _Prov()
    _tool_lauf(p2, prompt="x", **{feld: "512x512"})
    pruefe((_masse_von(p2) or {}).get("size") == "512x512", f"toleranter Feldname '{feld}'")
for feld in ("verhaeltnis", "ratio", "seitenverhaeltnis"):
    p3 = _Prov()
    _tool_lauf(p3, prompt="x", **{feld: "16:9"})
    pruefe((_masse_von(p3) or {}).get("verhaeltnis") == "16:9", f"toleranter Feldname '{feld}'")

# Ohne Angabe: masse=None -> kein Provider sendet ein Groessenfeld.
p4 = _Prov()
_tool_lauf(p4, prompt="x")
pruefe(bool(p4.aufrufe) and _masse_von(p4) is None, "ohne Angabe wird None uebergeben")

# Unbrauchbare Angabe: ABWEISEN, und zwar OHNE das Modell zu befragen.
p5 = _Prov()
erg5 = _tool_lauf(p5, prompt="x", size="ganz gross")
pruefe(erg5.startswith("Fehler:") and "unbrauchbar" in erg5,
       "unbrauchbare Groesse -> Klartext-Fehler statt geraten", erg5[:80])
pruefe(len(p5.aufrufe) == 0,
       "und KEIN Bildaufruf (das Modell kann sich im selben Schritt korrigieren)")

# ── Die Rueckmeldung nennt die GEMESSENEN Masse ─────────────────────────────
# Ein Modell, das die Wunschgroesse zurueckmeldet, behauptet einen Zustand, den
# es nicht kennt: der Gemini-Weg kann die Groesse nicht erzwingen, und Server
# runden selbst (1000x700 -> 992x688 gemessen).
_PNG_8x4 = _b64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAgAAAAECAYAAAB2Ba1LAAAAFUlEQVR42mNkYPjPwMDAxMDAwAAAB9wA/wG9pQAAAAAASUVORK5CYII="
)
p6 = _Prov(_PNG_8x4)
erg6 = _tool_lauf(p6, prompt="x", size="1536x640")
pruefe("8x4" in erg6, "die Rueckmeldung nennt die WIRKLICHEN Masse aus den Bytes", erg6[-160:])
pruefe("ABWEICHUNG" in erg6 and "1536x640" in erg6,
       "weicht sie von der Anforderung ab, steht das ausdruecklich dabei")
p7 = _Prov(_PNG_8x4)
# 1000x700 ist kein Vielfaches von 16 – am echten Server rundet er dann SELBST
# (auf 992x688 gemessen). Die Anpassung muss also sichtbar sein.
erg7 = _tool_lauf(p7, prompt="x", size="1000x700")
pruefe("Hinweis zur Groesse" in erg7 and "angepasst" in erg7,
       "eine Anpassung der Anforderung wird ebenfalls gemeldet", erg7[-140:])
# Einstellige Pixelzahlen sind keine Angabe, sondern ein Griff daneben – der
# Wert wird abgewiesen, nicht auf die Untergrenze gehoben.
p7b = _Prov(_PNG_8x4)
pruefe(_tool_lauf(p7b, prompt="x", size="8x4").startswith("Fehler:")
       and len(p7b.aufrufe) == 0,
       "'8x4' wird abgewiesen (einstellige Kanten sind keine Aufloesung)")
p8 = _Prov(_PNG_8x4)
pruefe("ABWEICHUNG" not in _tool_lauf(p8, prompt="x"),
       "ohne Anforderung gibt es auch keine Abweichungsmeldung")

# ── Endung aus den magischen Bytes ──────────────────────────────────────────
pruefe(IG._endung(_PNG_1x1) == "png", "PNG erkannt")
pruefe(IG._endung(b"\xff\xd8\xff\xe0abc") == "jpg", "JPEG erkannt")
pruefe(IG._endung(b"GIF89a...") == "gif", "GIF erkannt")
pruefe(IG._endung(b"RIFF1234WEBPxx") == "webp", "WebP erkannt")
pruefe(IG._endung(b"irgendwas") == "png", "unbekannt -> png (Vorgabe wie bisher)")

# DRIFT-SCHRANKE: jede Endung, die hier entstehen kann, muss
# /api/generated/{name} auch ausliefern – sonst entsteht ein Bild, das es gibt
# und das mit HTTP 400 antwortet.
_MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
_tab = re.search(r'_MEDIA = \{(.*?)\}', _MAIN, re.S)
_erlaubt = set(re.findall(r'"([a-z0-9]+)":\s*"image/', _tab.group(1))) if _tab else set()
_meine = {IG._endung(b) for b in (_PNG_1x1, b"\xff\xd8\xff", b"GIF89a", b"RIFF1234WEBP", b"x")}
pruefe(bool(_erlaubt) and _meine <= _erlaubt,
       "jede erzeugbare Endung liefert /api/generated auch aus",
       f"meine={sorted(_meine)} erlaubt={sorted(_erlaubt)}")

# ...und die Endung wird auch WIRKLICH BENUTZT. Eine Gegenprobe mit fest
# verdrahtetem ".png" blieb gruen, solange nur `_endung()` isoliert geprueft
# wurde – die Funktion kann richtig sein und trotzdem niemand rufen.
_JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 40
p9 = _Prov(_JPEG)
erg9 = _tool_lauf(p9, prompt="x")
_m9 = re.search(r"/api/generated/([0-9a-f]{32}\.[a-z]+)", erg9)
pruefe(bool(_m9) and _m9.group(1).endswith(".jpg"),
       "JPEG-Bytes ergeben eine .jpg-Datei (die Endung wird angewandt, nicht nur berechnet)",
       erg9[:120])
pruefe(bool(_m9) and (IG._IMG_DIR / _m9.group(1)).exists(),
       "und die Datei liegt unter genau diesem Namen")

pruefe(IG._png_masse(_PNG_1x1) == (1, 1), "_png_masse liest den IHDR-Block")
pruefe(IG._png_masse(b"\xff\xd8\xff") is None,
       "fuer JPEG wird NICHTS geraten (keine erfundene Zahl)")
pruefe(IG._png_masse(b"") is None, "leere Bytes werfen nicht")

# Die Datei liegt wirklich im Sandkasten und traegt die richtige Endung.
dateien = sorted(x.name for x in IG._IMG_DIR.glob("*")) if IG._IMG_DIR.exists() else []
pruefe(bool(dateien), f"Bilder im Sandkasten abgelegt ({len(dateien)})")
pruefe(bool(dateien) and all(re.fullmatch(r"[0-9a-f]{32}\.(png|jpg|gif|webp)", d)
                             for d in dateien),
       "Capability-Name bleibt 32 Hex + Endung (der Endpunkt prueft genau das)",
       str(dateien[:3]))


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("5. Delegation: die Groesse muss den 'task' ueberleben")

_DEL = (ROOT / "skills" / "agent_orchestrator" / "main.py").read_text(encoding="utf-8")
_task = re.search(r'"task":\s*\{(.*?)\n                \},', _DEL, re.S)
_taskbeschr = _task.group(1) if _task else ""
pruefe(bool(_taskbeschr), "task-Beschreibung im Schema gefunden (Positivkontrolle)")
pruefe("Aufloesung" in _taskbeschr,
       "die task-Beschreibung verlangt Formatvorgaben im Auftragstext")
pruefe("1536x640" in _taskbeschr,
       "mit konkretem Beispiel – ein Verbot ohne Fall wird ueberlesen")
pruefe("sieht die Anfrage des Nutzers nicht" in _taskbeschr,
       "und nennt den Grund (die Rolle beginnt bei null)")

_ROLLEN = (ROOT / "backend" / "agent_roles.py").read_text(encoding="utf-8")
_bild = _ROLLEN.split('"id": "image_builder"')[1].split('"id": "analyst"')[0]
pruefe("'size'" in _bild and "'aspect_ratio'" in _bild,
       "der Vorgabe-Prompt der Bild-Rolle nennt die Parameter")
pruefe("NICHT im Prompttext" in _bild,
       "und verbietet die Angabe im Prompttext")
pruefe("ZURUECKGEMELDET" in _bild,
       "die Rolle soll die gemeldete Groesse nennen, nicht die gewuenschte")


# ═════════════════════════════════════════════════════════════════════════════
abschnitt("6. Bildprofil: das Modell fuer Bilder ist vom Chat-Modell getrennt")

# WARUM DIESER ABSCHNITT EXISTIERT – der End-zu-End-Lauf hat es aufgedeckt:
# Punkte 1-4 wirken nur, wenn `generate_image` ueberhaupt AUFGERUFEN wird. Am
# echten Haus-Server gemessen: FLUX bekommt `tools` uebergeben und antwortet mit
#   tool_calls: None  +  ein 909-KB-Bild im `content`
# – es kann KEIN Tool-Calling. Ein Rollen-Agent AUF diesem Profil ruft also nie
# ein Werkzeug auf; das Bild entstand aus der Modellantwort (der Dateiname war
# der sha256-Praefix des Inhalts, also aus `_bilddaten_bergen`) und war
# 1024x1024, obwohl der Auftrag 1536x640 verlangte und die Delegation die Zahl
# woertlich weitergab. Umgekehrt sagt `generate_image` mit einem Textprofil ab.
# Aus BEIDEN Richtungen folgt dasselbe: die Trennung ist noetig.

pruefe(hasattr(llm, "provider_fuer_bild"),
       "llm.provider_fuer_bild existiert")


class _Cfg:
    """Attrappe von backend.config – NUR die Felder, die gelesen werden."""

    def __init__(self, image_profile_id="", profiles=None):
        self.IMAGE_PROFILE_ID = image_profile_id
        self.profiles = profiles if profiles is not None else []
        self.LLM_PROVIDER = "google"
        self.current_api_url = "http://chat:1/v1"
        self.current_model = "chat-modell"
        self.current_api_key = "chat-key"
        self.current_auth_method = "api_key"
        self.current_session_key = ""
        self.current_prompt_tool_calling = False


_BILD_PROF = {"id": "bild-1", "name": "FLUX", "provider": "openai_compatible",
              "model": "black-forest-labs/FLUX.2-klein-4B",
              "api_url": "http://bild:9079/v1", "api_key": "bild-key"}
_TEXT_PROF = {"id": "text-1", "name": "Qwen", "provider": "openai_compatible",
              "model": "Qwen/Qwen3.6", "api_url": "http://text:9081/v1",
              "api_key": "text-key"}


def _bild_prov(cfg):
    """(provider, model) oder (None, None) – WIRFT NICHT.

    Eine Pruefung, die abbricht, ist von einem nicht gelaufenen Waechter nicht
    zu unterscheiden (Register). Die Gegenprobe "verwaiste Kennung ist nicht
    fail-safe" hat genau das gezeigt.
    """
    try:
        return _mit_cfg(cfg, llm.provider_fuer_bild)
    except Exception as e:  # noqa: BLE001
        print(f"    (provider_fuer_bild wirft: {type(e).__name__}: {e})")
        return (None, None)


def _mit_cfg(cfg, fn):
    """Fuehrt fn() mit gestubbtem backend.config aus."""
    alt = sys.modules.get("backend.config")
    mod = types.ModuleType("backend.config")
    mod.config = cfg
    sys.modules["backend.config"] = mod
    try:
        return fn()
    finally:
        if alt is not None:
            sys.modules["backend.config"] = alt
        else:
            sys.modules.pop("backend.config", None)


# Der Rollen-Agent laeuft auf dem TEXT-Profil (so muss es sein, damit er
# Werkzeuge aufrufen kann) – gemalt wird trotzdem mit dem Bildprofil.
llm.current_agent_profile.set(_TEXT_PROF)
_p, _m = _bild_prov(_Cfg("bild-1", [_TEXT_PROF, _BILD_PROF]))
pruefe(_m == _BILD_PROF["model"],
       "gesetztes Bildprofil GEWINNT gegen das Laufprofil der Rolle", str(_m))
pruefe(getattr(_p, "base_url", "").startswith("http://bild:9079"),
       "und zwar mit SEINER Adresse", getattr(_p, "base_url", ""))

# Ohne Einstellung bleibt alles wie vorher – das ist der Rueckfall, der einen
# Verhaltensbruch ausschliesst.
_p2, _m2 = _bild_prov(_Cfg("", [_TEXT_PROF, _BILD_PROF]))
pruefe(_m2 == _TEXT_PROF["model"],
       "ohne Einstellung gilt unveraendert das Laufprofil", str(_m2))

# Verwaiste Kennung: FAIL-SAFE auf das Laufprofil, nicht Absturz und nicht
# stillschweigend gar kein Bild.
_p3, _m3 = _bild_prov(_Cfg("gibtsnicht", [_TEXT_PROF]))
pruefe(_m3 == _TEXT_PROF["model"],
       "verwaiste Kennung -> Laufprofil (fail-safe, kein Absturz)", str(_m3))
llm.current_agent_profile.set(None)

# Das Werkzeug muss den neuen Weg BENUTZEN – sonst ist die Einstellung eine
# Anzeige ohne Wirkung.
_IGQ = (ROOT / "backend" / "tools" / "image_gen.py").read_text(encoding="utf-8")
_IGQ_CODE = "\n".join(z for z in _IGQ.splitlines() if not z.strip().startswith("#"))
pruefe("provider_fuer_bild()" in _IGQ_CODE,
       "generate_image benutzt provider_fuer_bild (nicht mehr provider_fuer_lauf)")
pruefe("provider, modell = provider_fuer_lauf(" not in _IGQ_CODE,
       "der alte Aufruf steht nicht mehr im Code")

# ── config.py: NEUES FELD = VIER STELLEN ────────────────────────────────────
# Laden, Speichern (to_dict), Uebernehmen (update) und die Deklaration. Fehlt
# eine, wird das Feld still verworfen – genau die Fehlerklasse, an der
# `prompt_tool_calling` jahrelang wirkungslos war (Register).
_CFGQ = (ROOT / "backend" / "config.py").read_text(encoding="utf-8")
pruefe("IMAGE_PROFILE_ID" in _CFGQ, "Deklaration in config.py")
pruefe('if "image_profile_id" in data:' in _CFGQ, "wird beim LADEN uebernommen")
pruefe('"image_profile_id": self.IMAGE_PROFILE_ID,' in _CFGQ, "steht in to_dict (wird gespeichert)")
pruefe('if "image_profile_id" in settings:' in _CFGQ, "wird von update_settings uebernommen")

# Eine unbekannte Kennung darf NICHT gespeichert werden – sonst zeigt die
# Einstellung ins Leere und niemand sieht den Zusammenhang.
_upd = _CFGQ.split('if "image_profile_id" in settings:')[1][:600]
pruefe('any(p.get("id") == _neu' in _upd,
       "eine unbekannte Kennung wird beim Speichern ABGEWIESEN")
pruefe("if not _neu or" in _upd,
       'aber "" (= abschalten) geht immer durch')

# ── DIE DRITTE STELLE: der GET-Endpunkt ─────────────────────────────────────
# GET /api/settings baut seine Antwort SELBST zusammen und liest NICHT
# config.to_dict(). Beim Einbau am 2026-09-02 hier vergessen: die Einstellung
# wurde gespeichert, die Oberflaeche bekam sie nie zurueck und zeigte dauerhaft
# "wie das Chat-Profil" – ein Feld, das sich nicht anzeigen laesst, sieht wie
# ein kaputtes Feld aus. Aufgefallen NUR in der Live-Probe.
_MAINQ = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
_GET = _MAINQ.split('@app.get("/api/settings")')[1].split("@app.post")[0]
pruefe('"active_profile_id"' in _GET, "Positivkontrolle: der GET-Endpunkt ist geschnitten")
pruefe('"image_profile_id": config.IMAGE_PROFILE_ID,' in _GET,
       "GET /api/settings gibt image_profile_id heraus")

# REGEL, nicht Liste: jedes Feld, das save_global_settings ANNIMMT, muss der
# GET-Endpunkt auch herausgeben – sonst kann die Oberflaeche es speichern, aber
# nie anzeigen. Damit faellt auch ein KUENFTIGES Feld auf.
_SGS = _CFGQ.split("def save_global_settings")[1].split("\n    def ")[0]
_annimmt = set(re.findall(r'if "([a-z0-9_]+)" in settings:', _SGS))
# Ausnahmen, jede einzeln begruendet – keine Sammelfreigabe:
_AUSNAHMEN = {
    "agent_api_key",   # wird MASKIERT herausgegeben (_mask_key), nicht im Klartext
}
_fehlen = {f for f in _annimmt - _AUSNAHMEN if f'"{f}"' not in _GET}
pruefe(bool(_annimmt), f"Positivkontrolle: save_global_settings-Felder gefunden ({len(_annimmt)})")
pruefe(not _fehlen,
       "jedes speicherbare Feld ist im GET-Endpunkt lesbar",
       f"fehlen: {sorted(_fehlen)}")

# ── Oberflaeche ─────────────────────────────────────────────────────────────
_HTML = (ROOT / "frontend" / "settings.html").read_text(encoding="utf-8")
_APP = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
pruefe('id="setting-image-profile"' in _HTML, "Auswahlfeld im Markup")
pruefe('id="btn-save-image-profile"' in _HTML, "eigener Speichern-Knopf")
pruefe('data-i18n="profile.section_imgprof"' in _HTML, "Beschriftung folgt dem Sprachwechsel")
# Das Feld gehoert in die System-Einstellungen, nicht irgendwohin.
_grp = _HTML.split('id="setting-image-profile"')[0]
pruefe('prof-sect-tuning' in _grp.rsplit("tuning-group", 2)[0] or "tuning-group" in _grp,
       "es liegt in den System-Einstellungen (tuning-group)")

_btn = _APP.split("btn-save-image-profile")[1][:900] if "btn-save-image-profile" in _APP else ""
pruefe(bool(_btn), "Positivkontrolle: der Knopf ist in app.js verdrahtet")
pruefe("image_profile_id: v" in _btn or "image_profile_id: v " in _btn,
       "er sendet das Feld")
pruefe(_btn.count("JSON.stringify") == 1 and "llm_max_tokens" not in _btn
       and "docs_retention" not in _btn,
       "und NUR seine eigene Teilmenge – der Server merged, ein voller "
       "Formularstand ueberschriebe die Nachbarfelder")

_LD = _APP.split("setting-image-profile")[-1][:1400]
pruefe("data.profiles" in _LD,
       "die Auswahlliste wird aus den geladenen Profilen gebaut (keine getippte Kennung)")
# Auf die ZEILE geprueft, die die Option beschriftet – ein "textContent"
# irgendwo im Umfeld liess die Gegenprobe gruen bleiben.
_opt = [z for z in _LD.splitlines() if re.search(r"\bo\.(textContent|innerHTML)\s*=", z)]
pruefe(bool(_opt), "Positivkontrolle: die Beschriftungszeile der Option ist gefunden")
pruefe(bool(_opt) and all("textContent" in z for z in _opt),
       "der Profilname wird per textContent gesetzt (Freitext eines Admins)",
       str(_opt[:1]))
pruefe("imgprof_gone" in _APP,
       "eine verwaiste Einstellung wird in der Oberflaeche BENANNT")

_I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
for k in ("profile.section_imgprof", "profile.imgprof_label", "profile.imgprof_none",
          "profile.imgprof_hint", "profile.imgprof_gone"):
    pruefe(_I18N.count(f"'{k}'") == 2, f"{k} in DE UND EN", str(_I18N.count(f"'{k}'")))
_hint_de = _I18N.split("'profile.imgprof_hint':")[1].split("',")[0]
pruefe("Auflösung" in _hint_de and "Werkzeuge" in _hint_de,
       "der Hinweis erklaert die WIRKUNG (warum getrennt), nicht die Technik")


# ═════════════════════════════════════════════════════════════════════════════
shutil.rmtree(_tmp, ignore_errors=True)
print("\n" + "=" * 66)
print(f"Ergebnis: {_ok} bestanden, {_fail} fehlgeschlagen")
sys.exit(0 if _fail == 0 else 1)
