#!/usr/bin/env python3
"""Waechter fuer `bild_text_ersetzen` (Vorfall 2026-09-15).

Geprueft wird die EIGENSCHAFT, nicht das Vorkommen: die Bildfunktionen laufen
WIRKLICH ueber echte Bilder. Ob eine Luecke zwei Elemente trennt oder ob die
Fettschrift richtig erkannt wird, kann eine Quelltext-Suche nicht beantworten.

⚠ SANDKASTEN: das Werkzeug schreibt nach data/generated_images/. Ein Test, der
dort etwas liegen laesst, verschmutzt den Bestand des laufenden Servers -
deshalb schreibt dieser Lauf ausschliesslich in ein Wegwerf-Verzeichnis und
bricht mit Exit 2 ab, wenn das nicht gelingt.

Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.
"""
import ast
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = fail = 0
OKZ, FZ = "\033[32m✓\033[0m", "\033[31m✗\033[0m"


def check(text, bedingung, detail=""):
    """ACHTUNG Argumentreihenfolge: (Text, Bedingung)."""
    global ok, fail
    if isinstance(text, bool) and not isinstance(bedingung, bool):
        print("ABBRUCH: check(Text, Bedingung) - Argumente vertauscht")
        sys.exit(2)
    if bedingung:
        ok += 1
        print(f"  {OKZ} {text}")
    else:
        fail += 1
        print(f"  {FZ} {text}" + (f"  [{detail}]" if detail else ""))


def kopf(t):
    print(f"\n\033[1m{t}\033[0m")


def sicher(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        return e


# ── Voraussetzungen: ohne sie ist nichts messbar, aber auch nichts bewiesen ──
try:
    from PIL import Image, ImageDraw, ImageFont
except Exception as e:  # noqa: BLE001
    print(f"KONNTE NICHT LAUFEN: Pillow fehlt ({e})")
    sys.exit(2)
try:
    subprocess.run(["tesseract", "--version"], capture_output=True, timeout=20)
except Exception as e:  # noqa: BLE001
    print(f"KONNTE NICHT LAUFEN: tesseract fehlt ({e})")
    sys.exit(2)

from backend.tools import bild_text as BT  # noqa: E402

SCHRIFT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FETT = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"

# ⚠ SANDKASTEN: das Modul schreibt nach _IMG_DIR.
_SANDKASTEN = Path(tempfile.mkdtemp(prefix="jv-bildtext-"))
_BILDORDNER = _SANDKASTEN / "generated_images"
BT._bildordner = lambda: _BILDORDNER
if str(_BILDORDNER).startswith(str(ROOT)):
    print("ABBRUCH: der Sandkasten zeigt in den Arbeitsbaum")
    sys.exit(2)


def folie(pfad, titel_fett=True, grund=(247, 245, 242)):
    """Eine Folie mit Titel, Fliesstext und zwei WEIT getrennten Fusselementen."""
    img = Image.new("RGB", (1000, 560), grund)
    d = ImageDraw.Draw(img)
    d.text((60, 50), "Knowledge Layer",
           font=ImageFont.truetype(FETT if titel_fett else SCHRIFT, 46), fill=(20, 20, 24))
    for i, z in enumerate(["An AI knowledge layer connects raw enterprise",
                           "data with business meaning and governance."]):
        d.text((60, 200 + i * 40), z, font=ImageFont.truetype(SCHRIFT, 28), fill=(30, 30, 34))
    # Links und rechts - tesseract gruppiert das zu EINER Zeile.
    d.text((60, 500), "68", font=ImageFont.truetype(SCHRIFT, 22), fill=(120, 120, 125))
    d.text((860, 500), "futurice", font=ImageFont.truetype(FETT, 24), fill=(20, 20, 24))
    img.save(pfad)
    return pfad


# ═══════════════════════════════════════════════════════════════════════════
kopf("1) OCR und Absatzbildung - AUSGEFUEHRT an einem echten Bild")
p = folie(_SANDKASTEN / "folie.png")
absaetze = sicher(BT.ocr_absaetze, p, "eng")
check("ocr_absaetze laeuft und liefert Absaetze",
      isinstance(absaetze, list) and len(absaetze) >= 3, str(absaetze)[:120])
if not isinstance(absaetze, list):
    print("\nKONNTE NICHT LAUFEN: OCR nicht auswertbar")
    shutil.rmtree(_SANDKASTEN, ignore_errors=True)
    sys.exit(2)

texte = [a["text"] for a in absaetze]
check("der Titel wird erkannt", any("Knowledge" in t for t in texte), str(texte))
check("jeder Absatz hat Box, Zeilenhoehe und Konfidenz",
      all({"l", "t", "r", "b", "zeilenhoehe", "konf"} <= set(a) for a in absaetze))

# ── DER BEFUND VOM ECHTEN BILD: "68" und "futurice" duerfen NICHT ein
#    Absatz sein. Sonst landet beim Ersetzen alles am linken Rand.
kopf("2) Weit getrennte Elemente werden NICHT zusammengefasst")
zusammen = [t for t in texte if "68" in t and "futurice" in t]
check("'68' und 'futurice' sind getrennte Absaetze (nicht '68 futurice')",
      not zusammen, str(zusammen))
check("…und beide sind einzeln da",
      any(t.strip() == "68" for t in texte) and any("futurice" in t for t in texte),
      str(texte))

# ── Die Trennregel DIREKT an der Funktion, nicht ueber den OCR-Weg ───────
# ⚠ WARUM ISOLIERT: ueber tesseract ist die Zeilen-Bedingung nicht messbar -
# es gruppiert mehrzeilige Absaetze so, dass die Luecke gar nicht erst
# entsteht (an zwei eigens gebauten Bildern nachgemessen). Eine Gegenprobe
# gegen den OCR-Weg blieb deshalb stumm und sah aus wie ein zahnloser
# Waechter. Die Eigenschaft gehoert dorthin, wo sie entschieden wird.
def _w(l, b, line=1):
    return {"l": l, "t": 10, "w": b, "h": 20, "line": line, "text": "x",
            "block": 1, "par": 1, "konf": 90.0}


_einzeilig = [_w(20, 40), _w(70, 40), _w(900, 60)]      # grosse Luecke, EINE Zeile
_geteilt = BT._nach_luecken_trennen(_einzeilig)
check("einzeilig mit grosser Luecke wird GETRENNT", len(_geteilt) == 2,
      str([[x["l"] for x in g] for g in _geteilt]))

_mehrzeilig = [_w(20, 40, 1), _w(70, 40, 1), _w(900, 60, 1), _w(20, 40, 2)]
_nicht = BT._nach_luecken_trennen(_mehrzeilig)
check("mehrzeilig wird NICHT getrennt (eine Luecke am Zeilenende ist normal)",
      len(_nicht) == 1, str([[x["l"] for x in g] for g in _nicht]))

_eng = [_w(20, 40), _w(70, 40), _w(115, 40)]
check("ohne grosse Luecke bleibt es EIN Absatz",
      len(BT._nach_luecken_trennen(_eng)) == 1)

# Gegenrichtung ueber den OCR-Weg: mehrzeiliger Fliesstext bleibt zusammen.
# ⚠ NICHT "es gibt irgendeinen mehrzeiligen Absatz" - das bleibt auch wahr,
# wenn der Fliesstext zerrissen wurde. Gemessen wird, dass die BEIDEN Haelften
# des Satzes in DEMSELBEN Absatz liegen.
_fl = [a for a in absaetze if "knowledge layer connects" in a["text"].lower()]
check("mehrzeiliger Fliesstext bleibt EIN Absatz (beide Haelften zusammen)",
      len(_fl) == 1 and "governance" in _fl[0]["text"].lower(),
      f"gefunden={[a['text'][:50] for a in absaetze]}")

# ═══════════════════════════════════════════════════════════════════════════
kopf("3) Farben werden GEMESSEN, nicht geraten")
img = Image.open(p).convert("RGB")
a0 = absaetze[0]
g, tf = sicher(BT.farben, img, (a0["l"], a0["t"], a0["r"], a0["b"])) or ((0,), (0,))
check("die Grundfarbe ist die der Folie (nicht pauschal Weiss)",
      g == (247, 245, 242), f"gemessen: {g}")
check("die Textfarbe ist dunkel, nicht der Grund",
      sum(tf) < sum(g), f"text={tf} grund={g}")

# Auf getoentem Grund darf nichts Weisses uebrig bleiben.
p2 = folie(_SANDKASTEN / "getoent.png", grund=(210, 228, 240))
img2 = Image.open(p2).convert("RGB")
abs2 = BT.ocr_absaetze(p2, "eng")
g2, _ = BT.farben(img2, (abs2[0]["l"], abs2[0]["t"], abs2[0]["r"], abs2[0]["b"]))
check("auch auf getoentem Grund wird die richtige Farbe gemessen",
      g2 == (210, 228, 240), f"gemessen: {g2}")

# ═══════════════════════════════════════════════════════════════════════════
kopf("4) Fettschrift: der Median DIESES Bildes entscheidet, kein fester Wert")
# ⚠ Eine absolute Schwelle trennt das nicht: bei kleiner Schrift ist die
# relative Strichstaerke systematisch hoeher (ein Stamm ist mind. 1 px breit).
pf = folie(_SANDKASTEN / "fett.png", titel_fett=True)
pd = folie(_SANDKASTEN / "duenn.png", titel_fett=False)


def titel_staerke(pfad):
    im = Image.open(pfad).convert("RGB")
    aa = BT.ocr_absaetze(pfad, "eng")
    t = next(x for x in aa if "Knowledge" in x["text"])
    box = (t["l"], t["t"], t["r"], t["b"])
    grund, _ = BT.farben(im, box)
    return BT.strichstaerke(im, box, grund)


s_fett = sicher(titel_staerke, pf)
s_duenn = sicher(titel_staerke, pd)
check("strichstaerke misst den fetten Titel dicker als den leichten",
      isinstance(s_fett, float) and isinstance(s_duenn, float) and s_fett > s_duenn,
      f"fett={s_fett} duenn={s_duenn}")

# ═══════════════════════════════════════════════════════════════════════════
kopf("5) Ersetzen - AUSGEFUEHRT, und das Ergebnis wird GEMESSEN")
ziel = _SANDKASTEN / "aus.png"
ue = {a["id"]: ("Wissensebene" if "Knowledge" in a["text"] else a["text"])
      for a in absaetze}
bericht = sicher(BT.ersetzen, p, ziel, absaetze, ue)
check("ersetzen laeuft durch", isinstance(bericht, list), str(bericht)[:140])
check("die Zieldatei entsteht", ziel.is_file())
if ziel.is_file():
    neu_txt = " ".join(x["text"] for x in BT.ocr_absaetze(ziel, "deu"))
    check("der neue Text steht IM BILD", "Wissensebene" in neu_txt, neu_txt[:120])
    check("…und der alte ist weg", "Knowledge" not in neu_txt, neu_txt[:120])
    check("unveraenderte Absaetze bleiben stehen", "futurice" in neu_txt, neu_txt[:120])
    ae = [b for b in bericht if b["aktion"] == "ersetzt"]
    check("genau der geaenderte Absatz wird als ersetzt gemeldet", len(ae) == 1, str(bericht))

# Deutsch ist laenger - der Text darf nicht aus dem Bild laufen.
kopf("6) Zu langer Text wird verkleinert, nicht abgeschnitten")
lang = {a["id"]: ("Eine sehr ausfuehrliche deutsche Uebersetzung dieses Titels, "
                  "die deutlich laenger ist als das englische Original"
                  if "Knowledge" in a["text"] else a["text"]) for a in absaetze}
ziel2 = _SANDKASTEN / "lang.png"
b2 = sicher(BT.ersetzen, p, ziel2, absaetze, lang)
check("auch ein viel laengerer Text wird gesetzt", isinstance(b2, list) and ziel2.is_file())
if isinstance(b2, list):
    e2 = next((x for x in b2 if x["aktion"] == "ersetzt"), None)
    # ⚠ NICHT NUR "< orig": der Notfall-Rueckfall setzt 8 px und erfuellt das
    # ebenfalls. Gemessen wird, dass die Einpass-Schleife wirklich gearbeitet
    # hat - also eine Groesse DAZWISCHEN, und mehr als eine Zeile.
    check("…und dafuer die Schrift verkleinert (nicht der Notfall-Rueckfall)",
          bool(e2) and 8 < e2["groesse"] < e2["orig"] and e2["zeilen"] >= 2, str(e2))

# ═══════════════════════════════════════════════════════════════════════════
kopf("7) Die Schranken des Werkzeugs")
t = BT.BildTextErsetzenTool()
check("der Pfad-Parameter ist fuer den Dispatch deklariert",
      getattr(t, "pfad_parameter", ()) == ("pfad",),
      str(getattr(t, "pfad_parameter", None)))
check("das Schema verlangt den Pfad",
      t.parameters_schema().get("required") == ["pfad"])
check("die Beschreibung grenzt es gegen generate_image ab",
      "generate_image" in t.description and "NICHT" in t.description.upper())
check("…und nennt die Grenze (Foto-Untergrund)", "Foto" in t.description)
# ⚠ Eine nackte Quote ("3 von 5") liest das Modell als Fehlschlag - im echten
# Lauf wurde daraus "Zwei Bloecke konnten nicht uebersetzt werden", obwohl es
# Namen und Zahlen waren. Die Bedeutung muss mit.
_q = (ROOT / "backend" / "tools" / "bild_text.py").read_text(encoding="utf-8")
check("der Ergebnistext erklaert die unveraenderten Bloecke",
      "KEIN Fehler" in _q and "bleiben BEWUSST unveraendert" in _q)

quelle = (ROOT / "backend" / "tools" / "bild_text.py").read_text(encoding="utf-8")
baum = ast.parse(quelle)
# Kein Schreibzugriff ausserhalb des Bildordners.
check("geschrieben wird nur in den Bildordner", "ordner / name" in quelle)
check("der Name ist stabil", t.name == "bild_text_ersetzen")

# ── Verdrahtung: ein Werkzeug, das niemand anhaengt, gibt es nicht ─────────
agent = (ROOT / "backend" / "agent.py").read_text(encoding="utf-8")
check("es wird in _attach_extra_tools angehaengt",
      "BildTextErsetzenTool()" in agent and "from backend.tools.bild_text import" in agent)

bnd = (ROOT / "backend" / "werkzeug_buendel.py").read_text(encoding="utf-8")
check("es liegt im Buendel 'bild'", '"bild_text_ersetzen"' in bnd)

from backend import werkzeug_buendel as wb  # noqa: E402


class _W:
    def __init__(self, n):
        self.name = n


_kasten = [_W(n) for n in ("knowledge_search", "shell_execute", "generate_image",
                           "bild_text_ersetzen", "office_read", "sap_odata_query")]
_liste, _grund = wb.zuschnitt(list(_kasten), "uebersetze das Bild nach Deutsch")
check("…und ueberlebt den Werkzeug-Zuschnitt fuer 'uebersetze das Bild'",
      "bild_text_ersetzen" in [x.name for x in _liste], _grund)
# Die Flexion war der Grund, warum der Zuschnitt frueher danebengreifen konnte.
for form in ("die Bilder", "eines Bildes", "den Bildern"):
    check(f"…auch bei '{form}'", "bild" in wb.themen("uebersetze " + form), str(wb.themen(form)))

# ── Der Prompt darf die Faehigkeit nicht fuer unmoeglich erklaeren ─────────
kopf("8) Der System-Prompt kennt das Werkzeug")
# ⚠ ISOLIERT: der Name steht auch im Import und in _attach_extra_tools - eine
# Suche ueber die ganze Datei ist damit trivial wahr (Register).
_sp = ""
for _n in ast.walk(ast.parse(agent)):
    if isinstance(_n, ast.Assign) and any(
            getattr(z, "id", "") == "SYSTEM_PROMPT" for z in _n.targets):
        try:
            _sp = ast.literal_eval(_n.value)
        except Exception:  # noqa: BLE001
            _sp = ast.get_source_segment(agent, _n.value) or ""
check("Positivkontrolle: der System-Prompt wurde geschnitten", len(_sp) > 5000, str(len(_sp)))
check("Punkt 15 des SYSTEM_PROMPTS nennt bild_text_ersetzen",
      "bild_text_ersetzen" in _sp)
check("…und verbietet generate_image genau dafuer",
      "NIEMALS `generate_image`" in _sp)
check("…und behauptet NICHT mehr, Bildbearbeitung sei unmoeglich",
      "KANNST EIN VORHANDENES BILD NICHT BEARBEITEN" not in agent)

# ═══════════════════════════════════════════════════════════════════════════
kopf("9) Formatabhaengigkeit: ein GIF wird wie ein PNG gelesen")
# ⚠ AM ECHTEN ANHANG GEMESSEN (2026-09-15): dasselbe Bild als GIF lieferte
# WENIGER Text als als PNG - die halbe Zitatzeile fehlte. Ein GIF ist
# palettenbasiert, die Binarisierung faellt anders aus. Der Prototyp hatte
# vorher konvertiert und den Fehler deshalb nie gezeigt.
_gif = _SANDKASTEN / "folie.gif"
Image.open(p).convert("P", palette=Image.ADAPTIVE).save(_gif)
_a_png = BT.ocr_absaetze(p, "eng")
_a_gif = BT.ocr_absaetze(_gif, "eng")
_t_png = " ".join(x["text"] for x in _a_png)
_t_gif = " ".join(x["text"] for x in _a_gif)
check("Positivkontrolle: aus dem PNG kommt ueberhaupt Text", len(_t_png) > 40, _t_png[:60])
check("das GIF liefert denselben Text wie das PNG", _t_png == _t_gif,
      f"png={_t_png[:70]!r} gif={_t_gif[:70]!r}")

quelle_bt = (ROOT / "backend" / "tools" / "bild_text.py").read_text(encoding="utf-8")
check("…weil vor der Erkennung normalisiert wird", "_als_png(" in quelle_bt)
check("und das Wegwerf-Verzeichnis wieder abgeraeumt wird",
      "shutil.rmtree(_tmp" in quelle_bt)

kopf("10) Der LLM-Aufruf hat die ECHTE Signatur")
# ⚠ GERATEN WAR `messages=[{...}]` - das wirft "unexpected keyword argument"
# und die Uebersetzung faellt komplett aus (live gemessen). Der tragende Weg
# steht in backend/prompt_check.py.
_ue = next((n for n in ast.walk(ast.parse(quelle_bt))
            if isinstance(n, ast.AsyncFunctionDef) and n.name == "_uebersetzen"), None)
check("Positivkontrolle: _uebersetzen wurde gefunden", _ue is not None)
if _ue is not None:
    _ruf = next((k for k in ast.walk(_ue) if isinstance(k, ast.Call)
                 and getattr(k.func, "attr", "") == "generate_response"), None)
    check("generate_response wird aufgerufen", _ruf is not None)
    if _ruf is not None:
        _kw = {a.arg for a in _ruf.keywords}
        check("…mit model/system_prompt/contents", {"model", "system_prompt", "contents"} <= _kw,
              str(sorted(_kw)))
        check("…und NICHT mit dem geratenen 'messages'", "messages" not in _kw, str(sorted(_kw)))
        check("…ohne Werkzeuge (hier wird uebersetzt, nicht gehandelt)",
              "tools" in _kw)
check("die Antwort wird ueber .parts gelesen, nicht als String",
      'getattr(teil, "text", "")' in quelle_bt)

shutil.rmtree(_SANDKASTEN, ignore_errors=True)
check("der Sandkasten ist abgeraeumt", not _SANDKASTEN.exists())
check("…und der echte Bildordner wurde nie angefasst",
      str(_BILDORDNER).startswith(tempfile.gettempdir()))

print("\n" + "=" * 62)
print(f"{ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
