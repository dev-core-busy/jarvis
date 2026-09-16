#!/usr/bin/env python3
"""Anhaenge: ein Bild wird an den BYTES erkannt, nicht am gemeldeten MIME-Typ.

ANLASS (2026-09-16): "unter /chat wird ein GIF als Bild angezeigt, ein JPG als
Text". Gemessen war der Grund NICHT das Format, sondern ``file.type``: den holt
der Browser unter Windows aus der Registry, und hat ein Bildbetrachter die
``.jpg``-Zuordnung uebernommen, steht dort "" oder ``application/octet-stream``.
Der Anhang fiel damit in den Dokument-Zweig - das Bild wurde abgelegt, aber NIE
als Bild an das Modell gegeben.

Der Client korrigiert das seit derselben Aenderung selbst. DIESE Haelfte ist
trotzdem noetig und keine Doppelung: ein offener Tab schickt noch den alten
Stand, und die Android-App wie jeder API-Aufrufer gehen ohnehin an ihm vorbei.

GEMESSEN WIRD DIE EIGENSCHAFT, NICHT DAS VORKOMMEN:
  * ``_bild_mime_aus_bytes`` wird per ``ast`` geschnitten und WIRKLICH
    AUSGEFUEHRT - eine Quelltext-Suche koennte nicht sagen, WAS herauskommt.
  * Die REIHENFOLGE in der Anhang-Schleife: die Korrektur muss VOR der
    Bild-Weiche stehen. Dahinter waere sie wirkungslos, und eine Textsuche
    saehe den Unterschied nicht.
  * Dass der Bild-Zweig einen ``else``-Fall hat: bis 2026-09-16 verschwand ein
    Bild ueber 10 MB WORTLOS.

    python3 tests/test_anhang_bild_mime.py
"""
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
QUELLE = ROOT / "backend" / "main.py"

ok = fail = 0


def check(text: str, bedingung, detail: str = "") -> None:
    global ok, fail
    # Vertauschte Argumente wuerden JEDE Bedingung wahr machen (eine nicht
    # leere Zeichenkette ist wahr) - der Lauf meldete dann lauter OK, ohne
    # etwas ausgewertet zu haben (Register).
    if not isinstance(text, str) or isinstance(bedingung, str):
        print("ABBRUCH: check(text, bedingung) - Argumente vertauscht")
        sys.exit(2)
    if bedingung:
        ok += 1
        print(f"  ✓ {text}")
    else:
        fail += 1
        print(f"  ✗ {text}" + (f" – {detail}" if detail else ""))


def sicher(fn, text):
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        global fail
        fail += 1
        print(f"  ✗ {text} – WURF: {e}")
        return None


SRC = QUELLE.read_text(encoding="utf-8")
BAUM = ast.parse(SRC)


def funktion(name: str):
    for k in ast.walk(BAUM):
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name == name:
            return k
    return None


# ── Die echte Funktion schneiden und ausfuehren ────────────────────────────
_f = funktion("_bild_mime_aus_bytes")
if _f is None:
    # "Konnte nicht laufen" darf nie wie "bestanden" aussehen.
    print("ABBRUCH: _bild_mime_aus_bytes nicht gefunden")
    sys.exit(2)
# ⚠ Modul-Konstanten fallen aus JEDEM Funktions-Schnitt heraus (Register): ohne
# die Tabelle wirft die Funktion einen NameError, und der Lauf meldet lauter
# FAIL fuer einen Code, der in Ordnung ist.
_i_tab = SRC.find("_ANHANG_BILD_MAGIC = (")
if _i_tab < 0:
    print("ABBRUCH: _ANHANG_BILD_MAGIC nicht gefunden")
    sys.exit(2)
_TAB = SRC[_i_tab:SRC.index(")\n", _i_tab) + 1]
_raum: dict = {}
exec(_TAB + "\n" + ast.get_source_segment(SRC, _f), _raum)  # noqa: S102
bild_mime = _raum["_bild_mime_aus_bytes"]

import base64  # noqa: E402

JPG = base64.b64encode(bytes.fromhex("ffd8ffe000104a46494600")).decode()
PNG = base64.b64encode(bytes.fromhex("89504e470d0a1a0a0000000d49484452")).decode()
GIF = base64.b64encode(b"GIF89a\x01\x00\x01\x00\x80\x00\x00").decode()
GIF87 = base64.b64encode(b"GIF87a\x01\x00\x01\x00\x80\x00\x00").decode()
BMP = base64.b64encode(b"BM\x36\x00\x00\x00\x00\x00\x00\x00\x36\x00").decode()
WEBP = base64.b64encode(b"RIFF\x24\x00\x00\x00WEBPVP8 ").decode()
PDF = base64.b64encode(b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\n").decode()
TXT = base64.b64encode(b"Hallo Welt, das ist reiner Text.").decode()
ZIP = base64.b64encode(b"PK\x03\x04\x14\x00\x00\x00\x08\x00\x00\x00").decode()

print("\n=== 1. Die Bytes beweisen den Typ ===")
for name, daten, erwartet in [
    ("JPEG", JPG, "image/jpeg"),
    ("PNG", PNG, "image/png"),
    ("GIF89a", GIF, "image/gif"),
    ("GIF87a", GIF87, "image/gif"),
    ("BMP", BMP, "image/bmp"),
    ("WEBP", WEBP, "image/webp"),
]:
    got = sicher(lambda d=daten: bild_mime(d), f"{name} erkannt")
    check(f"{name} wird erkannt ({erwartet})", got == erwartet, f"ist: {got!r}")

print("\n=== 2. Gegenrichtung: was KEIN Bild ist, wird keines ===")
# Eine Erkennung, die zu viel an sich zieht, waere schlimmer als der behobene
# Fehler: ein PDF landete dann im Bild-Zweig und das Modell bekaeme Muell.
for name, daten in [("PDF", PDF), ("Text", TXT), ("ZIP", ZIP)]:
    got = sicher(lambda d=daten: bild_mime(d), f"{name} abgelehnt")
    check(f"{name} wird NICHT als Bild ausgegeben", got == "", f"ist: {got!r}")
# Fail-open: unbrauchbare Eingaben duerfen nicht werfen - der Aufrufer steht
# mitten in der Anhang-Schleife.
for name, wert in [("leer", ""), ("None", None), ("kein base64", "###"), ("zu kurz", "QQ==")]:
    got = sicher(lambda w=wert: bild_mime(w), f"{name} behandelt")
    check(f"{name}: liefert \"\" statt zu werfen", got == "", f"ist: {got!r}")

print("\n=== 3. Der Helfer holt base64 SELBST ===")
# In main.py ist base64 NICHT auf oberster Ebene importiert. Ohne den lokalen
# Import wirft der Aufruf einen NameError, den das `except` verschluckt - die
# Funktion gaebe dann IMMER "" zurueck und waere still wirkungslos.
_importe = [k for k in ast.walk(_f) if isinstance(k, (ast.Import, ast.ImportFrom))]
check("die Funktion importiert base64 selbst",
      any(getattr(a, "name", "") == "base64" for k in _importe
          for a in getattr(k, "names", [])),
      "sonst ist sie still wirkungslos")
check("base64 ist in main.py wirklich nicht auf Modulebene importiert (Grund der Regel)",
      not any(isinstance(k, (ast.Import, ast.ImportFrom))
              and any(a.name == "base64" for a in k.names)
              for k in BAUM.body))

print("\n=== 4. Reihenfolge in der Anhang-Schleife ===")
# Die Korrektur muss VOR der Bild-Weiche stehen. Dahinter waere sie wirkungslos
# - und eine Textsuche saehe den Unterschied nicht.
_i_korr = SRC.find("_magisch = _bild_mime_aus_bytes(_data)")
_i_weiche = SRC.find("if _mime in _ALLOWED_IMG_MIME:\n                    if len(_data)")
check("die Byte-Korrektur steht im Anhang-Weg", _i_korr > 0)
check("die Bild-Weiche steht im Anhang-Weg", _i_weiche > 0)
check("die Korrektur steht VOR der Bild-Weiche",
      0 < _i_korr < _i_weiche, f"korr={_i_korr}, weiche={_i_weiche}")

print("\n=== 5. Kein wortloses Verwerfen mehr ===")
# Ueber den GANZEN Baum: die umschliessende Funktion zu raten hat beim ersten
# Lauf einen Fehler gemeldet, den es nicht gab (Register).
_gefunden = False
for k in ast.walk(BAUM):
    if not isinstance(k, ast.If):
        continue
    # ⚠ Auf die BEDINGUNG pruefen, nicht auf den Quelltext des Knotens:
    # `ast.walk` liefert die AEUSSERE Weiche zuerst, und deren Quelltext
    # enthaelt die innere mit - der Waechter beurteilte dann den falschen
    # else-Zweig (beim ersten Lauf genau so passiert).
    if (ast.get_source_segment(SRC, k.test) or "") == "len(_data) <= 14_000_000":
        _gefunden = True
        # ⚠ NICHT `bool(k.orelse)` – das ist auch bei einem `elif` wahr, und ein
        # `elif False:` laesst das Bild weiter wortlos verschwinden. Die
        # Eigenschaft lautet: JEDES zu grosse Bild wird gemeldet, also braucht
        # es einen BEDINGUNGSLOSEN else-Zweig. (Gegenprobe hat es aufgedeckt.)
        _ist_elif = bool(k.orelse) and isinstance(k.orelse[0], ast.If)
        check("der Bild-Zweig hat einen bedingungslosen else-Fall",
              bool(k.orelse) and not _ist_elif,
              "elif statt else" if _ist_elif else "bis 2026-09-16 verschwand es wortlos")
        check("die Meldung nennt die Grenze",
              "10 MB" in "".join(ast.get_source_segment(SRC, o) or "" for o in k.orelse))
        break
check("die Groessen-Weiche wurde ueberhaupt gefunden", _gefunden,
      "ohne sie sagen die zwei Pruefungen darueber nichts")

print(f"\nErgebnis: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
