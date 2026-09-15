#!/usr/bin/env python3
"""LIVE auf DEV: der ECHT-Vorfall vom 2026-09-15 durch die VOLLE Anzeigekette.

Gemeldet aus /chat -> "playground COMMON" (andreas.bender, 13:41): auf
"uebersetze das Bild ... Generiere dazu ein neues Bild" antwortete das Modell

    Hier ist das generierte Bild mit der deutschen Übersetzung:

    ![Wissensebene Slide](/api/generated/8f03991e6d02785630884b246d0390e3.png)

Gemessen am Server: `steps=0` - KEIN Werkzeugaufruf, kein Bild erzeugt, die
Datei existiert nicht. Das Modell hat die Adresse FREI ERFUNDEN.
`_ohne_tote_bildrefs` entfernte die Referenz zu Recht - aber STILL, und uebrig
blieb der Satz mit einer LEERZEILE dahinter.

Hier laeuft der ECHTE agent.py des Servers, nicht eine Attrappe.
Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.
"""
import ast, re, struct, sys, textwrap, zlib
from pathlib import Path

WURZEL = Path("/opt/jarvis")
sys.path.insert(0, str(WURZEL))
QUELLE = (WURZEL / "backend" / "agent.py").read_text(encoding="utf-8")
ZEILEN, BAUM = QUELLE.splitlines(), ast.parse(QUELLE)
ok = fail = 0


def pruef(b, t):
    global ok, fail
    if b:
        ok += 1
    else:
        fail += 1
        print(f"  FAIL: {t}")


def seg(n):
    s = n.lineno
    for d in getattr(n, "decorator_list", []):
        s = min(s, d.lineno)
    return textwrap.dedent("\n".join(ZEILEN[s - 1:n.end_lineno]))


KLS = next(n for n in ast.walk(BAUM) if isinstance(n, ast.ClassDef) and n.name == "JarvisAgent")


def meth(name):
    return next((n for n in KLS.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == name), None)


START = ("_anzeigetext",)


def _mit_abhaengigkeiten(start):
    """TRANSITIV - eine gepflegte Liste laesst genau eine Methode fehlen, und
    der AttributeError landet im breiten `except`: das sieht wie ein Codefehler
    aus und ist keiner."""
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


for m in START:
    if meth(m) is None:
        print(f"KONNTE NICHT LAUFEN: Methode {m} fehlt")
        sys.exit(2)
METHODEN = _mit_abhaengigkeiten(START)
print(f"Geschnittene Methoden: {len(METHODEN)}")

ns = {}
exec("import base64, hashlib, json, re, uuid, os, time", ns)
import backend.tools.image_gen as IG  # noqa: E402

for n in BAUM.body:
    if isinstance(n, ast.Assign):
        for z in n.targets:
            if isinstance(z, ast.Name) and (z.id.startswith("_B64_") or z.id.endswith("_RE")
                                            or z.id.startswith("_TOOL_")):
                try:
                    exec(seg(n), ns)
                except Exception:
                    pass

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

# POSITIVKONTROLLE des Aufbaus: ohne den Hinweistext misst der Rest nichts.
HINWEIS = getattr(ns["A"], "_KEIN_BILD_HINWEIS", None)
if not HINWEIS:
    print("KONNTE NICHT LAUFEN: _KEIN_BILD_HINWEIS fehlt im geschnittenen Code")
    sys.exit(2)


def png(w=32, h=32):
    def ch(t, d):
        r = t + d
        return struct.pack(">I", len(d)) + r + struct.pack(">I", zlib.crc32(r))
    rows = b"".join(b"\x00" + bytes(sum(([0, 180, 90] for _ in range(w)), [])) for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
            + ch(b"IDAT", zlib.compress(rows, 6)) + ch(b"IEND", b""))


def rendern(md):
    """Was der Browser daraus macht - die LUECKE wird so sichtbar."""
    return re.sub(r"!\[([^\]\n]*)\]\(([^)\n]+)\)",
                  lambda m: "<IMG>" if re.match(r"^https?://|^/|^data:image/", m.group(2)) else "",
                  md)


# ══ 1) Der gemeldete Fall, WOERTLICH ═════════════════════════════════════
ECHT = ("Hier ist das generierte Bild mit der deutschen Übersetzung:\n\n"
        "![Wissensebene Slide](/api/generated/8f03991e6d02785630884b246d0390e3.png)\n\n"
        "*(Hinweis: KI-Bildgeneratoren haben oft Schwierigkeiten, sehr lange Texte "
        "akkurat wiederzugeben.)*")

erfunden = Path(IG._IMG_DIR) / "8f03991e6d02785630884b246d0390e3.png"
if erfunden.exists():
    print(f"KONNTE NICHT LAUFEN: {erfunden} existiert - der Fall ist nicht herstellbar")
    sys.exit(2)

IG.current_task_images.set([])          # kein Bild in diesem Lauf entstanden
aus = A._anzeigetext(ECHT)
sicht = rendern(aus)

print("\n1) Der gemeldete Fall (erfundene Adresse, kein Bild erzeugt)")
print(f"   gerendert -> {sicht[:200]!r}")
pruef("/api/generated/" not in aus, "die erfundene Referenz ist entfernt")
pruef(HINWEIS in aus, "der Benutzer erfaehrt, dass kein Bild erzeugt wurde")
pruef("Hier ist das generierte Bild" in aus, "der Modelltext bleibt unangetastet")
pruef("<IMG>" not in sicht, "der Renderer zeigt kein Bild (es gibt ja keines)")
# DAS GEMELDETE SYMPTOM: Satz, dann Leere
lueckig = sicht.strip().endswith(")*") and HINWEIS not in sicht
pruef(not lueckig, "das gemeldete Symptom (Ankuendigung ohne jede Erklaerung) ist weg")

# ══ 2) Gegenrichtung: ein ECHTES Bild -> KEIN Hinweis ════════════════════
print("\n2) Gegenrichtung: ein wirklich erzeugtes Bild")
import hashlib  # noqa: E402
daten = png()
name = hashlib.sha256(daten).hexdigest()[:32] + ".png"
pfad = Path(IG._IMG_DIR) / name
pfad.write_bytes(daten)
try:
    url = f"/api/generated/{name}"
    IG.current_task_images.set([{"path": str(pfad), "url": url, "prompt": "Testbild"}])
    aus2 = A._anzeigetext(f"Hier ist das Bild:\n\n![Testbild]({url})")
    sicht2 = rendern(aus2)
    print(f"   gerendert -> {sicht2[:160]!r}")
    pruef(url in aus2, "die gueltige Referenz bleibt stehen")
    pruef(HINWEIS not in aus2, "KEIN Hinweis, wenn ein Bild da ist")
    pruef("<IMG>" in sicht2, "der Renderer zeigt das Bild")

    # ══ 3) Der Fall, fuer den _ohne_tote_bildrefs gebaut wurde ═══════════
    # Modell verzaehlt sich beim Abschreiben -> tote Referenz, aber
    # _mit_bildern traegt die richtige nach. Hier waere ein Hinweis eine
    # FALSCHAUSSAGE.
    print("\n3) Verstuemmelte Adresse, aber Bild vorhanden (Fall 2026-08-29)")
    kaputt = "/api/generated/" + "f" * 28 + ".png"
    aus3 = A._anzeigetext(f"Hier ist das Bild:\n\n![Testbild]({kaputt})")
    pruef(kaputt not in aus3, "die verstuemmelte Referenz ist weg")
    pruef(url in aus3, "die RICHTIGE Adresse wurde nachgetragen")
    pruef(HINWEIS not in aus3, "…und deshalb KEIN Hinweis (waere eine Falschaussage)")
finally:
    if pfad.exists():
        pfad.unlink()
        print(f"\n   Testdatei wieder entfernt: {pfad.name}")

# ══ 4) Antwort ohne Bildanspruch bleibt unberuehrt ═══════════════════════
print("\n4) Antwort ohne Bildanspruch")
IG.current_task_images.set([])
aus4 = A._anzeigetext("Von heute bis zum 31.12.2026 sind es 113 Tage.")
pruef(HINWEIS not in aus4, "kein Hinweis ohne Bildankuendigung")
pruef(aus4.strip() == "Von heute bis zum 31.12.2026 sind es 113 Tage.",
      "der Text ist unveraendert")

print(f"\n{ok} bestanden, {fail} fehlgeschlagen")
sys.exit(1 if fail else 0)
