#!/usr/bin/env python3
"""Waechter: base64-Bilddaten werden AUSGELAGERT, nicht abgeschnitten.

DER VORFALL (2026-08-26, gemeldet von ECHT): ein ausdruecklich verlangtes
GENERIERTES Bild kam nicht an. Stattdessen stand im Chat "Die Bildgenerierung
als Base64 war zu gross fuer den Chat. Stattdessen habe ich das Bild direkt mit
matplotlib gerendert und gespeichert:" – also ein Plot statt eines Bildes, mit
einer Begruendung, die in keiner Zeile Code steht.

Der wahre Vorgang dahinter: ein Werkzeug-Ergebnis mit base64-Bilddaten lief in
`_ergebnis_kappen` und wurde bei 5000 Zeichen MITTEN IM BLOB abgeschnitten. Ein
150-dpi-PNG sind rund 200.000 base64-Zeichen – das Modell sah 2,5 % eines
Datenklumpens, konnte damit nichts anfangen und erfand eine Erklaerung samt
Ersatzweg.

Dieser Test fuehrt die Bergung WIRKLICH aus (Methoden werden per `ast` aus
`backend/agent.py` geschnitten – ein Import von `backend.agent` zieht
`backend.config` und schriebe die Live-settings.json zurueck).

Exit 0 = bestanden · 1 = FAIL · 2 = konnte nicht laufen.
"""

import ast
import base64
import re
import shutil
import struct
import sys
import tempfile
import textwrap
import uuid
import zlib
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
AGENT_PY = WURZEL / "backend" / "agent.py"
MAIN_PY = WURZEL / "backend" / "main.py"

_ok = 0
_fail = 0


def pruef(bedingung, text):
    global _ok, _fail
    if bedingung:
        _ok += 1
    else:
        _fail += 1
        print(f"  FAIL: {text}")


def abbruch(text):
    print(f"KONNTE NICHT LAUFEN: {text}")
    sys.exit(2)


# ── Quelltext-Teile aus agent.py holen ───────────────────────────────────────
if not AGENT_PY.exists():
    abbruch(f"{AGENT_PY} fehlt")

QUELLE = AGENT_PY.read_text(encoding="utf-8")
ZEILEN = QUELLE.splitlines()
BAUM = ast.parse(QUELLE)


def _segment(node) -> str:
    """Quelltext eines Knotens INKLUSIVE seiner Dekoratoren.

    `ast.get_source_segment` beginnt beim `def` – ein @staticmethod ginge dabei
    verloren und die Methode verhielte sich in der Attrappe anders als im
    Original."""
    start = node.lineno
    for dec in getattr(node, "decorator_list", []):
        start = min(start, dec.lineno)
    return textwrap.dedent("\n".join(ZEILEN[start - 1:node.end_lineno]))


def _klasse(name):
    for n in ast.walk(BAUM):
        if isinstance(n, ast.ClassDef) and n.name == name:
            return n
    return None


def _methode(kls, name):
    for n in kls.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == name:
            return n
    return None


def _konstante(name):
    for n in BAUM.body:
        if isinstance(n, ast.Assign):
            for z in n.targets:
                if isinstance(z, ast.Name) and z.id == name:
                    return _segment(n)
    abbruch(f"Konstante {name} nicht in agent.py gefunden")


AGENT_KLS = _klasse("JarvisAgent")
if AGENT_KLS is None:
    abbruch("Klasse JarvisAgent nicht gefunden")

_METHODEN = ("_b64_endung", "_b64_bloecke", "_bilddaten_bergen",
             "_verlauf_text", "_verlauf_content", "_ergebnis_kappen")
for _m in _METHODEN:
    if _methode(AGENT_KLS, _m) is None:
        abbruch(f"Methode {_m} fehlt in JarvisAgent – Fix nicht vorhanden?")


# ── Attrappe bauen und die ECHTEN Methoden hineinsetzen ──────────────────────
SANDKASTEN = Path(tempfile.mkdtemp(prefix="jv_b64_test_"))
IMG_DIR = SANDKASTEN / "generated_images"

_gemerkt = []          # was record_task_image() zu sehen bekam


class _ImageGenStub:
    _IMG_DIR = IMG_DIR

    @staticmethod
    def record_task_image(path, url):
        _gemerkt.append({"path": str(path), "url": url})


class _ScreenshotStub:
    IMAGE_PREFIX = "IMAGE_BASE64:"


class _ToolsPkgStub:
    image_gen = _ImageGenStub
    screenshot = _ScreenshotStub


class _BackendStub:
    tools = _ToolsPkgStub


import types as _types  # noqa: E402

for _name, _obj in (("backend", _BackendStub), ("backend.tools", _ToolsPkgStub),
                    ("backend.tools.image_gen", _ImageGenStub),
                    ("backend.tools.screenshot", _ScreenshotStub)):
    _mod = _types.ModuleType(_name)
    for _a in dir(_obj):
        if not _a.startswith("__"):
            setattr(_mod, _a, getattr(_obj, _a))
    sys.modules[_name] = _mod

# Standardmodule NICHT einzeln aufzaehlen, sondern die Top-Level-Importe von
# agent.py nachziehen. Ein fehlendes Modul (hier: hashlib) laesst die Bergung
# still in ihr `except` laufen – der Test meldet dann "Blob steht noch im Text"
# und man sucht den Fehler im Code statt in der Attrappe.
_ns = {"print": lambda *a, **k: None}
for _n in BAUM.body:
    if isinstance(_n, ast.Import):
        for _a in _n.names:
            if "." in _a.name or _a.name.startswith("backend"):
                continue
            try:
                _ns[_a.asname or _a.name] = __import__(_a.name)
            except ImportError:
                pass
for _pflicht in ("base64", "re", "uuid", "hashlib"):
    if _pflicht not in _ns:
        abbruch(f"{_pflicht} wird von agent.py nicht importiert – Fix unvollstaendig?")


class _PartStub:
    def __init__(self, text=None):
        self.text = text

    @staticmethod
    def from_text(text=None):
        return _PartStub(text)


class _ContentStub:
    def __init__(self, role="model", parts=None):
        self.role, self.parts = role, list(parts or [])


class _TypesStub:
    Part = _PartStub
    Content = _ContentStub


_ns["types"] = _TypesStub

# Konstanten NICHT aus einer gepflegten Liste holen, sondern alle `_B64_*` aus
# agent.py einsammeln: eine handgepflegte Liste laeuft beim naechsten neuen
# Wert auseinander, und der Fehler sieht dann wie ein Codefehler aus
# (NameError tief in der Methode, vom `except` verschluckt). Genau das ist beim
# Bau dieses Tests passiert.
_konst_namen = ["_TOOL_ERGEBNIS_MAX"]
for _n in BAUM.body:
    if isinstance(_n, ast.Assign):
        for _z in _n.targets:
            if isinstance(_z, ast.Name) and _z.id.startswith("_B64_"):
                _konst_namen.append(_z.id)
if len(_konst_namen) < 5:
    abbruch(f"nur {len(_konst_namen)} Konstanten gefunden – Fix nicht vorhanden?")
for _k in _konst_namen:
    exec(_konstante(_k), _ns)

_körper = "\n\n".join(
    textwrap.indent(_segment(_methode(AGENT_KLS, m)), "    ") for m in _METHODEN
)
exec("class Attrappe:\n    agent_id = 'test'\n    tools_map = {}\n\n" + _körper, _ns)
A = _ns["Attrappe"]()

# SANDKASTEN-WAECHTER: schreibt die Bergung wirklich ins Wegwerf-Verzeichnis?
# Ohne diese Pruefung landen die Testbilder in data/generated_images des
# laufenden Servers – und eine Gegenprobe gegen einen alten Modulstand (dort
# heissen die Namen anders) faellt genau in diese Falle.
import backend.tools.image_gen as _ig_check  # noqa: E402
if Path(_ig_check._IMG_DIR).resolve() != IMG_DIR.resolve():
    abbruch(f"_IMG_DIR zeigt aus dem Sandkasten heraus: {_ig_check._IMG_DIR}")


# ── Echtes Testmaterial: ein GUELTIGES PNG, kein Byte-Haufen ─────────────────
def echtes_png(breite=64, hoehe=64) -> bytes:
    """Ein wirklich dekodierbares PNG. Register: Testmaterial, das ein echter
    Konsument nicht oeffnet, kann nichts belegen."""
    def chunk(typ: bytes, daten: bytes) -> bytes:
        roh = typ + daten
        return struct.pack(">I", len(daten)) + roh + struct.pack(">I", zlib.crc32(roh))

    ihdr = struct.pack(">IIBBBBB", breite, hoehe, 8, 2, 0, 0, 0)
    zeilen = b""
    for y in range(hoehe):
        # Filterbyte 0 (None) + RGB je Pixel – so schreibt es die Spezifikation.
        zeilen += b"\x00" + bytes(
            sum(([(x * 4) % 256, (y * 4) % 256, 128] for x in range(breite)), []))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(zeilen, 6)) + chunk(b"IEND", b""))


PNG = echtes_png()
PNG_B64 = base64.b64encode(PNG).decode()
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 3000 + b"\xff\xd9"
ZIP = b"PK\x03\x04" + b"\x00" * 3000

if len(PNG_B64) <= 5000:
    abbruch(f"Testbild zu klein ({len(PNG_B64)} base64-Zeichen) – der 5000er-Deckel "
            f"wuerde gar nicht greifen, der Test bewiese nichts")

print(f"Testmaterial: PNG {len(PNG)} Bytes = {len(PNG_B64)} base64-Zeichen "
      f"(Deckel: {_ns['_TOOL_ERGEBNIS_MAX']})")


def frisch():
    _gemerkt.clear()
    if IMG_DIR.exists():
        shutil.rmtree(IMG_DIR)


URL_RE = re.compile(r"/api/generated/([0-9a-f]{32}\.[a-z]+)")


# ═══════════════════════════════════════════════════════════════════════════
print("\n1. Data-URL mit echtem PNG")
frisch()
text = f"Fertig.\n![Ergebnis](data:image/png;base64,{PNG_B64})\nViel Erfolg."
raus = A._ergebnis_kappen("shell_execute", text)

pruef(PNG_B64[:200] not in raus, "base64-Nutzlast steht immer noch im Ergebnis")
m = URL_RE.search(raus)
pruef(m is not None, "keine /api/generated/-URL im Ergebnis")
if m:
    datei = IMG_DIR / m.group(1)
    pruef(datei.exists(), "Datei wurde nicht geschrieben")
    pruef(datei.exists() and datei.read_bytes() == PNG,
          "geschriebene Bytes weichen vom Original ab")
    pruef(datei.suffix == ".png", f"falsche Endung: {datei.suffix}")
pruef(len(_gemerkt) == 1, f"record_task_image nicht genau einmal gerufen ({len(_gemerkt)})")
pruef("Viel Erfolg." in raus, "Text NACH dem Blob ging verloren")
pruef(raus.startswith("Fertig."), "Text VOR dem Blob ging verloren")
# Das PRAEFIX muss mit verschwinden. Ohne diese Pruefung bleibt die Gegenprobe
# "Data-URL-Erkennung entfernt" gruen: der allgemeine Lauf-Finder greift die
# Nutzlast dann zwar auch, laesst aber "data:image/png;base64," als Textrest
# stehen. Eine Gegenprobe, die nicht beisst, ist ein Testmangel.
pruef("data:image/" not in raus,
      "das Data-URL-Praefix steht als Rest im Ergebnis")
pruef("gekuerzt" not in raus,
      "trotz Auslagerung wurde noch gekappt – der Blob war also noch drin")

# ── Positivkontrolle: ist das PNG wirklich lesbar? ──
# Register: eine Pruefung darf NICHT werfen. Ein abgeschnittenes PNG laesst
# `bild.load()` mit OSError abbrechen – die Gegenprobe zeigte dann gar keine
# Zaehlzeile mehr und sah aus, als waere sie nicht gelaufen.
try:
    from PIL import Image  # noqa: F401
    import io
    if m:
        try:
            bild = Image.open(io.BytesIO((IMG_DIR / m.group(1)).read_bytes()))
            bild.load()
            pruef(bild.size == (64, 64), f"PIL liest falsche Groesse: {bild.size}")
            print("   (mit PIL als echtes PNG gegengeprueft)")
        except Exception as e:  # noqa: BLE001
            pruef(False, f"PIL kann die ausgelagerte Datei nicht lesen: {e}")
except ImportError:
    print("   (PIL nicht vorhanden – Byte-Gleichheit bleibt der Nachweis)")

# ═══════════════════════════════════════════════════════════════════════════
print("\n2. Nackter, mehrzeiliger Blob (Form von `base64 datei.png`)")
frisch()
umbrochen = "\n".join(PNG_B64[i:i + 76] for i in range(0, len(PNG_B64), 76))
text = f"$ base64 /tmp/bild.png\n{umbrochen}\nfertig\n"
raus = A._ergebnis_kappen("shell_execute", text)
m = URL_RE.search(raus)
pruef(m is not None, "mehrzeiliger Blob wurde nicht erkannt")
if m:
    pruef((IMG_DIR / m.group(1)).read_bytes() == PNG,
          "mehrzeiliger Blob falsch zusammengesetzt")
pruef("fertig" in raus, "Text nach dem Blob ging verloren")
pruef(PNG_B64[100:300] not in raus, "Blob steht noch im Ergebnis")

# ═══════════════════════════════════════════════════════════════════════════
print("\n3. DER GEMELDETE FALL: ohne Bergung wird mitten im Blob geschnitten")
# Gegenprobe gegen das ALTE Verhalten – gerechnet, nicht behauptet.
alt = str(text)
if len(alt) > _ns["_TOOL_ERGEBNIS_MAX"]:
    alt_gekappt = alt[:_ns["_TOOL_ERGEBNIS_MAX"]]
    anteil = 100.0 * _ns["_TOOL_ERGEBNIS_MAX"] / len(alt)
    print(f"   alt: {anteil:.1f} % des Ergebnisses beim Modell, Rest ein Torso")
    pruef(URL_RE.search(alt_gekappt) is None,
          "Gegenprobe untauglich: der alte Weg lieferte schon eine URL")
raus = A._ergebnis_kappen("shell_execute", text)
pruef(len(raus) < 2000,
      f"Ergebnis nach Bergung immer noch riesig ({len(raus)} Zeichen)")
pruef("gekuerzt" not in raus, "nach der Bergung wird immer noch gekappt")

# ═══════════════════════════════════════════════════════════════════════════
print("\n4. Fliesstext wird NICHT angefasst (keine Fehlalarme)")
frisch()
prosa = ("Die Auswertung ist abgeschlossen. " * 200
         + "\nDonaudampfschifffahrtsgesellschaftskapitaenswitwenrentenbescheid\n"
         + "Zusammenfassung: alles in Ordnung.\n")
raus = A._ergebnis_kappen("shell_execute", prosa)
pruef(URL_RE.search(raus) is None, "Fliesstext wurde als Bild ausgelagert")
pruef(len(_gemerkt) == 0, "record_task_image bei Fliesstext gerufen")
pruef("gekuerzt" in raus, "langer Fliesstext wird nicht mehr gekappt – Regression")

# ═══════════════════════════════════════════════════════════════════════════
print("\n5. base64, aber KEIN Bild -> unangetastet (wird gekappt wie bisher)")
frisch()
zip_b64 = base64.b64encode(ZIP).decode()
text = f"Archiv:\ndata:image/png;base64,{zip_b64}\n"
raus = A._ergebnis_kappen("shell_execute", text)
pruef(URL_RE.search(raus) is None,
      "ZIP-Bytes wurden als Bild ausgeliefert – die Typangabe wurde geglaubt")
pruef(len(_gemerkt) == 0, "record_task_image fuer Nicht-Bild gerufen")

# ═══════════════════════════════════════════════════════════════════════════
print("\n6. Die Bytes entscheiden ueber die Endung, nicht die Typangabe")
frisch()
jpeg_b64 = base64.b64encode(JPEG).decode()
raus = A._ergebnis_kappen("shell_execute", f"data:image/png;base64,{jpeg_b64}")
m = URL_RE.search(raus)
pruef(m is not None, "JPEG hinter falscher Typangabe nicht erkannt")
pruef(m is not None and m.group(1).endswith(".jpg"),
      f"Endung folgt der Luege statt den Bytes: {m.group(1) if m else '-'}")

# ═══════════════════════════════════════════════════════════════════════════
print("\n7. Screenshot-Weg bleibt unberuehrt")
frisch()
text = f"IMAGE_BASE64:/tmp/screen.png|{PNG_B64}"
raus = A._ergebnis_kappen("screenshot", text)
pruef(len(_gemerkt) == 0,
      "Screenshot zusaetzlich ausgelagert – erzeugt eine zweite Kopie")
pruef(URL_RE.search(raus) is None, "Screenshot-Ergebnis bekam eine URL")

# ═══════════════════════════════════════════════════════════════════════════
print("\n8. Deckel gegen Bildfluten")
frisch()
viele = "\n".join(f"data:image/png;base64,{PNG_B64}" for _ in range(_ns["_B64_MAX_BILDER"] + 3))
raus = A._ergebnis_kappen("shell_execute", viele)
pruef(len(_gemerkt) <= _ns["_B64_MAX_BILDER"],
      f"Deckel greift nicht: {len(_gemerkt)} Bilder ausgelagert")
pruef(len(_gemerkt) == _ns["_B64_MAX_BILDER"],
      f"Deckel greift zu frueh: {len(_gemerkt)} statt {_ns['_B64_MAX_BILDER']}")

# ═══════════════════════════════════════════════════════════════════════════
print("\n9. Bergung laeuft VOR der Kuerzung")
kappen = _methode(AGENT_KLS, "_ergebnis_kappen")
_reihenfolge = []
for n in ast.walk(kappen):
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) \
            and n.func.attr == "_bilddaten_bergen":
        _reihenfolge.append(("bergen", n.lineno))
    if isinstance(n, ast.Compare) and any(isinstance(o, (ast.LtE, ast.Gt)) for o in n.ops):
        for teil in ast.walk(n):
            if isinstance(teil, ast.Call) and isinstance(teil.func, ast.Name) \
                    and teil.func.id == "len":
                _reihenfolge.append(("laengenpruefung", n.lineno))
                break
pruef(any(t == "bergen" for t, _ in _reihenfolge),
      "_bilddaten_bergen wird in _ergebnis_kappen gar nicht gerufen")
_b = [l for t, l in _reihenfolge if t == "bergen"]
_l = [l for t, l in _reihenfolge if t == "laengenpruefung"]
pruef(bool(_b) and bool(_l) and min(_b) < min(_l),
      "die Laengenpruefung steht VOR der Bergung – der Blob waere schon zerschnitten")

# ═══════════════════════════════════════════════════════════════════════════
print("\n10. Verdrahtet an BEIDEN Wegen (Chat und headless)")
_stellen = []
for n in ast.walk(BAUM):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for k in ast.walk(n):
            if isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute) \
                    and k.func.attr == "_ergebnis_kappen":
                _stellen.append(n.name)
pruef("run_task" in _stellen,
      f"_ergebnis_kappen wird im Chat-Weg nicht gerufen (gefunden: {set(_stellen)})")
pruef(any("headless" in s for s in _stellen),
      f"_ergebnis_kappen wird im headless-Weg nicht gerufen (gefunden: {set(_stellen)})")

# ═══════════════════════════════════════════════════════════════════════════
print("\n11. DRIFT-SCHRANKE: jede erzeugte Endung liefert /api/generated auch aus")
# Die Liste steht an ZWEI Orten. Laufen sie auseinander, entsteht eine URL,
# die mit 400 antwortet – ein Bild, das es gibt und das niemand sieht.
if not MAIN_PY.exists():
    abbruch("backend/main.py fehlt")
_m_src = MAIN_PY.read_text(encoding="utf-8")
_pos = _m_src.find("async def get_generated_image")
if _pos < 0:
    abbruch("get_generated_image nicht in main.py gefunden")
_ausschnitt = _m_src[_pos:_pos + 1200]
_erlaubt = set(re.findall(r'"(png|jpg|jpeg|gif|webp|bmp|svg)"\s*:', _ausschnitt))
pruef(bool(_erlaubt), "Endungsliste in get_generated_image nicht lesbar")

_erzeugt = {e for _, e in _ns["_B64_MAGIC"]}
_erzeugt.add("webp")   # RIFF-Zweig steht ausserhalb der Tabelle
for _e in sorted(_erzeugt):
    pruef(_e in _erlaubt,
          f"_b64_endung erzeugt '.{_e}', /api/generated liefert das aber nicht aus")

# ═══════════════════════════════════════════════════════════════════════════
print("\n12. Fail-safe: ein Fehler laesst das Ergebnis unveraendert")
frisch()
_alt_dir = _ig_check._IMG_DIR
try:
    _ig_check._IMG_DIR = Path("/proc/nicht/beschreibbar")
    _ns["Attrappe"]  # noqa: B018
    raus = A._ergebnis_kappen("shell_execute", f"data:image/png;base64,{PNG_B64}")
    pruef(isinstance(raus, str) and len(raus) > 0,
          "unschreibbares Zielverzeichnis liefert kein Ergebnis")
    pruef("Traceback" not in raus, "Ausnahme ist in das Ergebnis gelaufen")
finally:
    _ig_check._IMG_DIR = _alt_dir

# ═══════════════════════════════════════════════════════════════════════════
print("\n13. JEDE Form, in der ein Werkzeug base64 zurueckgibt")
# Die erste Fassung erkannte nur ganze Zeilen – damit fiel ausgerechnet die
# HAEUFIGSTE Form durch: ein MCP-Server/API-Wrapper liefert JSON, und
# {"image": "iVBOR…"} ist keine base64-ZEILE. Vier von sieben Formen wurden
# zerschnitten. Diese Tabelle haelt alle fest.
import json as _json  # noqa: E402

_formen = {
    "Data-URL einzeilig":      f"data:image/png;base64,{PNG_B64}",
    "Blob mehrzeilig":         "\n".join(PNG_B64[i:i + 76] for i in range(0, len(PNG_B64), 76)),
    "Blob einzeilig":          PNG_B64,
    "JSON-Feld kompakt":       _json.dumps({"image": PNG_B64, "mime": "image/png"}),
    "JSON eingerueckt":        _json.dumps({"image": PNG_B64}, indent=2),
    "in Anfuehrungszeichen":   'Ergebnis: "' + PNG_B64 + '"',
    "key=wert auf einer Zeile": "b64=" + PNG_B64,
    "XML-Element":             f"<data>{PNG_B64}</data>",
    "Markdown-Tabellenzelle":  f"| Bild | {PNG_B64} |",
}
for _name, _text in _formen.items():
    frisch()
    _r = A._ergebnis_kappen("mcp_fremdwerkzeug", _text)
    _m = URL_RE.search(_r)
    pruef(_m is not None, f"Form nicht geborgen: {_name}")
    if _m:
        pruef((IMG_DIR / _m.group(1)).read_bytes() == PNG,
              f"Form falsch zusammengesetzt: {_name}")

print("\n13b. …und die Gegenrichtung: lange Nicht-Bild-Laeufe bleiben liegen")
for _name, _text in {
    "JWT-artiges Token":   "Bearer " + "eyJhbGciOiJIUzI1NiJ9" * 40,
    "Hex-Hash-Liste":      "\n".join("a1b2c3d4e5f6" * 8 for _ in range(60)),
    "base64 eines ZIP":    base64.b64encode(ZIP).decode(),
    "base64 von Klartext": base64.b64encode(b"nur Text, kein Bild " * 200).decode(),
}.items():
    frisch()
    _r = A._ergebnis_kappen("shell_execute", _text)
    pruef(URL_RE.search(_r) is None, f"Fehlalarm: {_name} wurde als Bild ausgelagert")

# ═══════════════════════════════════════════════════════════════════════════
print("\n14. Bilddaten im ANTWORTTEXT des Modells (gemeldet: 'nur Zeichen')")
# Die Bergung an `_ergebnis_kappen` deckt nur den Weg ueber ein Werkzeug-
# ERGEBNIS ab. Gibt das Modell die Daten in seiner ANTWORT aus, blieb der
# Blob stehen – der Benutzer sah eine Zeichenwueste statt eines Bildes.
frisch()
antwort = f"Hier ist das Diagramm:\n\ndata:image/png;base64,{PNG_B64}\n\nViel Erfolg."
raus = A._bilddaten_bergen("(antworttext)", antwort, fuer_anzeige=True)
m = URL_RE.search(raus)
pruef(m is not None, "Bilddaten im Antworttext werden nicht geborgen")
pruef(PNG_B64[:200] not in raus, "roher base64-Blob steht noch im Anzeigetext")
pruef(m is not None and f"![Bild](/api/generated/{m.group(1)})" in raus,
      "keine benutzbare Markdown-Bildreferenz im Anzeigetext")
# Der Ersatztext fuers MODELL ist eine ANWEISUNG – die darf ein Benutzer nie lesen.
pruef("AUSGELAGERT" not in raus and "deine Antwort" not in raus,
      "die Modell-Anweisung steht im Anzeigetext, den der Benutzer liest")
pruef("Viel Erfolg." in raus and raus.startswith("Hier ist das Diagramm:"),
      "umgebender Text ging verloren")
# Gegenrichtung: im WERKZEUG-Ergebnis muss die Anweisung sehr wohl stehen
frisch()
fuers_modell = A._bilddaten_bergen("shell_execute", antwort)
pruef("AUSGELAGERT" in fuers_modell,
      "dem Modell fehlt der Hinweis, was mit den Daten passiert ist")

print("\n14b. …und der Anzeigepfad ruft sie wirklich")
_anz = _methode(AGENT_KLS, "_anzeigetext")
if _anz is None:
    abbruch("_anzeigetext nicht gefunden")
_rufe = [(k.func.attr, k.lineno) for k in ast.walk(_anz)
         if isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute)]
pruef(any(a == "_bilddaten_bergen" for a, _ in _rufe),
      "_anzeigetext ruft die Bergung nicht – Modelltext bleibt ungeborgen")
_b = [l for a, l in _rufe if a == "_bilddaten_bergen"]
_c = [l for a, l in _rufe if a == "_clean_doc_refs"]
pruef(bool(_b) and bool(_c) and min(_b) < min(_c),
      "die Bergung steht NACH _clean_doc_refs – die Bereinigung greift dann in den Blob")
# Und sie muss dort mit fuer_anzeige=True gerufen werden.
_mit_flag = any(
    k.func.attr == "_bilddaten_bergen"
    and any(kw.arg == "fuer_anzeige" and getattr(kw.value, "value", None) is True
            for kw in k.keywords)
    for k in ast.walk(_anz)
    if isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute))
pruef(_mit_flag, "_anzeigetext ruft ohne fuer_anzeige=True – die Modell-Anweisung "
                 "landet dann im Text des Benutzers")

# ═══════════════════════════════════════════════════════════════════════════
print("\n15. Der LLM-VERLAUF bekommt ebenfalls keine Bilddaten")
# Auf ECHT gemessen: der Blob stand nicht nur im Anzeigetext, sondern auch in
# context.json – 43.483 Zeichen, die von da an bei JEDER Folgeanfrage der
# Sitzung mitgeschickt werden. Der Anzeigepfad allein reicht nicht.
frisch()
_roh = f"Hier ist das Bild:\n\n![Drache](data:image/png;base64,{PNG_B64})"
_verl = A._verlauf_text(_roh)
pruef(PNG_B64[:200] not in _verl, "der Blob steht weiterhin im LLM-Verlauf")
pruef(URL_RE.search(_verl) is not None, "im Verlauf fehlt die Bild-URL")
pruef(len(_verl) < 500, f"Verlaufstext immer noch gross ({len(_verl)} Zeichen)")

print("\n15b. Idempotent: Anzeige + Verlauf ergeben EINE Datei")
frisch()
_a = A._bilddaten_bergen("(antworttext)", _roh, fuer_anzeige=True)
_b = A._verlauf_text(_roh)
_dateien = sorted(p.name for p in IMG_DIR.iterdir()) if IMG_DIR.exists() else []
pruef(len(_dateien) == 1,
      f"derselbe Blob erzeugte {len(_dateien)} Dateien – mit uuid4 statt Inhalts-Hash")
pruef(URL_RE.search(_a).group(1) == URL_RE.search(_b).group(1),
      "Anzeige und Verlauf zeigen auf verschiedene URLs desselben Bildes")
pruef(_dateien and len(_dateien[0].split(".")[0]) == 32,
      "Dateiname ist kein 32-stelliger Hex – /api/generated wiese ihn mit 400 ab")

print("\n15c. REGEL: kein Modelltext geht ungeborgen in den Verlauf")
# Die Herkunft der parts-Variablen wird mitverfolgt – eine Pruefung auf die
# Schreibweise haette die drei Stellen falsch gemeldet, an denen die Liste
# einige Zeilen weiter oben befuellt wird.
def _gespeiste_listen(fn):
    raus = set()
    for k in ast.walk(fn):
        if isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute) \
                and k.func.attr == "append":
            ziel = getattr(k.func.value, "id", None)
            if ziel and any(isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)
                            and x.func.attr in ("_verlauf_text", "_verlauf_content")
                            for x in ast.walk(k)):
                raus.add(ziel)
    return raus

_offen = []
for _fn in ast.walk(BAUM):
    if not isinstance(_fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
        continue
    _gespeist = _gespeiste_listen(_fn)
    for _k in ast.walk(_fn):
        if not (isinstance(_k, ast.Call) and isinstance(_k.func, ast.Attribute)
                and _k.func.attr == "append"
                and getattr(_k.func.value, "id", "") == "chat_history"):
            continue
        _d = ast.dump(_k)
        if "model" not in _d and "candidates" not in _d:
            continue                      # Benutzer-/Werkzeug-Turns
        if any(isinstance(x, ast.Call) and isinstance(x.func, ast.Attribute)
               and x.func.attr in ("_verlauf_text", "_verlauf_content")
               for x in ast.walk(_k)):
            continue
        if {getattr(a, "id", None) for a in ast.walk(_k)
                if isinstance(a, ast.Name)} & _gespeist:
            continue
        _offen.append(f"{_fn.name}:{_k.lineno}")
pruef(not _offen, f"ungeborgener Modelltext geht in den Verlauf: {_offen}")

# Und der Google-Rohpfad muss das Objekt unveraendert lassen, wenn nichts anliegt
class _P:
    def __init__(self, t=None): self.text = t
class _C:
    def __init__(self, parts): self.parts = parts; self.role = "model"
_orig = _C([_P("nur Text, keine Bilddaten")])
pruef(A._verlauf_content(_orig) is _orig,
      "der Google-Rohpfad baut das Objekt um, obwohl nichts zu bergen war")

# ═══════════════════════════════════════════════════════════════════════════
shutil.rmtree(SANDKASTEN, ignore_errors=True)
print(f"\n{'=' * 60}\n{_ok} bestanden, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
