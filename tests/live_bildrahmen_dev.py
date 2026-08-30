#!/usr/bin/env python3
"""LIVE auf DEV: die VOLLE Anzeigekette mit dem echten agent.py und dem echten
Bildordner. Der Waechter prueft `_bilddaten_bergen` isoliert – hier laufen
zusaetzlich `_clean_doc_refs`, `_ohne_tote_bildrefs` und `_mit_bildern` mit,
also genau die Schritte, die die geborgene Referenz danach noch anfassen.

Nachgestellt wird der ECHT-Vorfall vom 2026-08-30 woertlich.
Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.
"""
import ast, base64, re, struct, sys, textwrap, zlib
from pathlib import Path

WURZEL = Path("/opt/jarvis")
sys.path.insert(0, str(WURZEL))
QUELLE = (WURZEL / "backend" / "agent.py").read_text(encoding="utf-8")
ZEILEN, BAUM = QUELLE.splitlines(), ast.parse(QUELLE)
ok = fail = 0
def pruef(b, t):
    global ok, fail
    if b: ok += 1
    else:
        fail += 1; print(f"  FAIL: {t}")

def seg(n):
    s = n.lineno
    for d in getattr(n, "decorator_list", []): s = min(s, d.lineno)
    return textwrap.dedent("\n".join(ZEILEN[s - 1:n.end_lineno]))

KLS = next(n for n in ast.walk(BAUM) if isinstance(n, ast.ClassDef) and n.name == "JarvisAgent")
def meth(name):
    return next((n for n in KLS.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == name), None)

START = ("_anzeigetext", "_bilddaten_bergen", "_md_bildrahmen", "_ergebnis_kappen")

# Abhaengigkeiten TRANSITIV einsammeln statt eine Liste zu pflegen: jede
# `self.x()`/`cls.x()`-Referenz, die eine Methode der Klasse ist, kommt mit.
# Eine gepflegte Liste laesst genau eine Methode fehlen – der AttributeError
# landet dann im breiten `except` und sieht wie ein Codefehler aus.
def _mit_abhaengigkeiten(start):
    noetig, offen = set(), list(start)
    while offen:
        name = offen.pop()
        if name in noetig or meth(name) is None:
            continue
        noetig.add(name)
        for k in ast.walk(meth(name)):
            if (isinstance(k, ast.Attribute) and isinstance(k.value, ast.Name)
                    and k.value.id in ("self", "cls") and meth(k.attr) is not None):
                offen.append(k.attr)
    return sorted(noetig)

METHODEN = _mit_abhaengigkeiten(START)
for m in START:
    if meth(m) is None:
        print(f"KONNTE NICHT LAUFEN: Methode {m} fehlt"); sys.exit(2)
print(f"Geschnittene Methoden: {len(METHODEN)}")

ns = {}
exec("import base64, hashlib, json, re, uuid, os, time", ns)
# ECHTES image_gen – die Datei entsteht wirklich, _ohne_tote_bildrefs prueft echt.
import backend.tools.image_gen as IG
ns["_GENERATED_URL_RE"] = None
for n in BAUM.body:
    if isinstance(n, ast.Assign):
        for z in n.targets:
            if isinstance(z, ast.Name) and (z.id.startswith("_B64_") or
                                            z.id in ("_GENERATED_URL_RE", "_TOOL_ERGEBNIS_MAX",
                                                     "_CHART_MARKER_RE", "_DOC_URL_RE")):
                try: exec(seg(n), ns)
                except Exception: pass
# Klassen-Attribute NICHT in den Klassenrumpf einruecken – SYSTEM_PROMPT ist ein
# mehrzeiliges Literal, dessen Fortsetzungszeilen dabei verschoben wuerden
# (IndentationError). Stattdessen einzeln auswerten und danach setzen.
attr_ns = dict(ns)
attr_namen = []
for n in KLS.body:
    if isinstance(n, ast.Assign):
        try:
            exec(seg(n), attr_ns)
            attr_namen += [z.id for z in n.targets if isinstance(z, ast.Name)]
        except Exception:
            pass
koerper = "\n\n".join(textwrap.indent(seg(meth(m)), "    ") for m in METHODEN)
exec("class A:\n    agent_id='live'\n    tools_map={}\n    _pending_charts={}\n\n" + koerper, ns)
for _n in attr_namen:
    if _n in attr_ns:
        setattr(ns["A"], _n, attr_ns[_n])
A = ns["A"]()

def png(w=48, h=48):
    def ch(t, d):
        r = t + d
        return struct.pack(">I", len(d)) + r + struct.pack(">I", zlib.crc32(r))
    rows = b"".join(b"\x00" + bytes(sum(([0, 200, 0] for _ in range(w)), [])) for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + ch(b"IDAT", zlib.compress(rows, 6)) + ch(b"IEND", b""))

B64 = base64.b64encode(png()).decode()

def rendern(md):
    def e(m):
        a = m.group(2)
        return "<IMG>" if re.match(r"^https?://|^/|^data:image/", a) else ""
    return re.sub(r"!\[([^\]\n]*)\]\(([^)\n]+)\)", e, md)

print("Der gemeldete Fall, durch die VOLLE Anzeigekette:")
roh = ("Hier ist das Bild der grünen Kuh mit den roten Hörnern:\n\n"
       f"![Grüne Kuh](data:image/png;base64,{B64})")
raus = A._anzeigetext(roh)
sicht = rendern(raus)
print(f"  anzeigetext -> {raus[:110]!r}")
print(f"  gerendert   -> {sicht!r}")

pruef(B64[:150] not in raus, "base64 steht noch im Anzeigetext")
pruef("](![" not in raus, "verschachtelte Bildreferenz in der vollen Kette")
pruef("<IMG>" in sicht, "der Renderer zeigt KEIN Bild")
pruef(sicht.strip() != "Hier ist das Bild der grünen Kuh mit den roten Hörnern:\n\n)".strip(),
      "GENAU das gemeldete Symptom ist noch da")
pruef(not re.search(r"\)\s*$", sicht), f"verwaiste Klammer am Ende -> {sicht!r}")
pruef("/api/generated/" in raus, "keine Bild-URL im Anzeigetext")

m = re.search(r"/api/generated/([0-9a-f]{32}\.png)", raus)
pruef(bool(m), "URL nicht gefunden")
if m:
    p = Path(IG._IMG_DIR) / m.group(1)
    pruef(p.exists(), f"Datei wurde nicht geschrieben: {p}")
    if p.exists():
        pruef(p.read_bytes() == png(), "Datei ist nicht byte-gleich mit dem Original")
        pruef(p.read_bytes()[:8] == b"\x89PNG\r\n\x1a\n", "keine gueltigen PNG-Magic-Bytes")
        p.unlink()          # DEV sauber hinterlassen
        print(f"  Testdatei wieder entfernt: {p.name}")

print(f"\n{ok} bestanden, {fail} fehlgeschlagen")
sys.exit(1 if fail else 0)
