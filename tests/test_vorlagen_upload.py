#!/usr/bin/env python3
"""Waechter: Hochladen von Office-Vorlagen (Code-Review 2026-10-25).

Drei Zusagen, gemessen an den ECHTEN Helfern aus ``backend/main.py`` (per
Syntaxbaum geschnitten und ausgefuehrt – ``backend.main`` wird NICHT
importiert, das zoege die ganze App samt Startup-Hooks nach):

1. Der Ablagename ist nie einer, den die Vorlagenlisten als Zwischenstand
   verwerfen. Vorher wurde aus "Angebot.neu.dotx" ein "Angebot.neu.docx" und
   aus ".intern.pptx" ein versteckter Name – mit Erfolgsmeldung, aber weder
   waehlbar noch ueber die Oberflaeche loeschbar.
2. Die ENTPACKTE Groesse hat einen Deckel (ZIP-Bombe beim Pruefen).
3. Beide Upload-Endpunkte pruefen im Thread (``asyncio.to_thread``) – die
   Pruefung parst die Datei und blockierte sonst den Event-Loop.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.

    python3 tests/test_vorlagen_upload.py
"""
import ast
import io
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN_SRC = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")

_ok = _fail = 0


def pruefe(bedingung, text, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f" – {detail}" if detail else ""))


def _schnitt(namen_fn, namen_var):
    baum = ast.parse(MAIN_SRC)
    teile = []
    gefunden = set()
    for k in baum.body:
        if isinstance(k, ast.FunctionDef) and k.name in namen_fn:
            teile.append(k)
            gefunden.add(k.name)
        if isinstance(k, ast.Assign) and any(getattr(t, "id", "") in namen_var
                                              for t in k.targets):
            teile.append(k)
            gefunden.update(t.id for t in k.targets if getattr(t, "id", "") in namen_var)
    fehlt = (set(namen_fn) | set(namen_var)) - gefunden
    if fehlt:
        print(f"ABBRUCH: in backend/main.py nicht gefunden: {sorted(fehlt)}")
        sys.exit(2)
    ns = {"re": re, "Path": Path}
    exec(compile(ast.Module(body=teile, type_ignores=[]), "main", "exec"), ns)
    return ns


NS = _schnitt({"_vorlagen_dateiname", "_zip_entpackt_pruefen"}, {"_VORLAGE_MAX_ENTPACKT"})
name = NS["_vorlagen_dateiname"]
entpackt = NS["_zip_entpackt_pruefen"]


def zwischenstand(n: str) -> bool:
    """Dieselbe Regel wie die Listen (vorlage_word._ist_zwischenstand und die
    pptx-Listen in vorlage.py): Punkt vorn oder eine Zwischen-Endung."""
    return n.startswith(".") or n.endswith((".tmp.docx", ".neu.docx", ".tmp.pptx",
                                            ".neu.pptx", ".upload.tmp"))


# ── Positivkontrolle der Regel: sie erkennt die gemeldeten Namen ───────────
if not (zwischenstand("Angebot.neu.docx") and zwischenstand(".intern.pptx")):
    print("ABBRUCH: die Zwischenstand-Regel erkennt die gemeldeten Namen nicht")
    sys.exit(2)

print("\n1. Ablagename")
for roh, endung, erwartet in [
        ("Angebot.neu.dotx", ".docx", "Angebot_neu.docx"),
        (".intern.docx", ".docx", "intern.docx"),
        (".intern.pptx", ".pptx", "intern.pptx"),
        ("Vorlage.tmp.potx", ".pptx", "Vorlage_tmp.pptx"),
        ("../../etc/passwd.docx", ".docx", "passwd.docx"),
        ("Mein Bericht.docx", ".docx", "Mein_Bericht.docx"),
        ("standard.docx", ".docx", "standard.docx"),
        ("", ".docx", "vorlage.docx"),
        ("...", ".pptx", "vorlage.pptx")]:
    n = name(roh, endung)
    pruefe(n == erwartet, f"{roh!r} -> {n!r}", f"erwartet {erwartet!r}")
    pruefe(not zwischenstand(n) and "/" not in n,
           f"{n!r} ist sichtbar und ohne Pfadanteil")

print("\n2. Deckel fuer die entpackte Groesse")
klein = io.BytesIO()
with zipfile.ZipFile(klein, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr("word/document.xml", "<w/>")
pruefe(entpackt(klein.getvalue()) == "", "kleine Datei: in Ordnung")
gross = io.BytesIO()
_mb = 1024 * 1024
_ziel = NS["_VORLAGE_MAX_ENTPACKT"] + _mb
with zipfile.ZipFile(gross, "w", zipfile.ZIP_DEFLATED) as z:
    with z.open("blob.bin", "w", force_zip64=True) as f:
        _null = b"\0" * _mb
        for _ in range(_ziel // _mb):
            f.write(_null)
pruefe(len(gross.getvalue()) < 5 * _mb,
       f"Aufbau: die Probe ist GEPACKT klein ({len(gross.getvalue()) // 1024} KB)")
g = entpackt(gross.getvalue())
pruefe(bool(g) and "entpackt" in g, "hoch komprimierte Riesendatei wird abgewiesen", g)
pruefe(entpackt(b"kein zip") == "", "kein ZIP: meldet die eigentliche Pruefung")

print("\n3. Pruefung im Thread, Namen ueber den Helfer")
for ep, pruef in (("upload_branding_docx_template", "_docx_tpl_pruefen"),
                  ("upload_branding_pptx_template", "_pptx_tpl_pruefen")):
    fn = next((k for k in ast.walk(ast.parse(MAIN_SRC))
               if isinstance(k, ast.AsyncFunctionDef) and k.name == ep), None)
    if fn is None:
        print(f"ABBRUCH: Endpunkt {ep} nicht gefunden")
        sys.exit(2)
    src = ast.unparse(fn)
    pruefe(f"asyncio.to_thread({pruef}" in src, f"{ep}: Pruefung laeuft im Thread")
    pruefe(not re.search(r"(?<!to_thread\()\b%s\(" % pruef, src),
           f"{ep}: kein direkter (blockierender) Aufruf mehr")
    pruefe("_vorlage_ablegen(" in src, f"{ep}: Ablage ueber den gemeinsamen Helfer")
_abl = next((k for k in ast.parse(MAIN_SRC).body
             if isinstance(k, ast.FunctionDef) and k.name == "_vorlage_ablegen"), None)
pruefe(_abl is not None and "_vorlagen_dateiname(dateiname, endung)" in ast.unparse(_abl),
       "_vorlage_ablegen: Ablagename ueber _vorlagen_dateiname")
for pruef in ("_docx_tpl_pruefen", "_pptx_tpl_pruefen"):
    fn = next((k for k in ast.parse(MAIN_SRC).body
               if isinstance(k, ast.FunctionDef) and k.name == pruef), None)
    pruefe(fn is not None and "_zip_entpackt_pruefen(daten)" in ast.unparse(fn),
           f"{pruef}: prueft die entpackte Groesse")

print(f"\n{'=' * 60}\n{_ok} OK, {_fail} FAIL\n{'=' * 60}")
sys.exit(1 if _fail else 0)
