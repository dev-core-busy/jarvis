#!/usr/bin/env python3
"""LIVE auf DEV: `bild_text_ersetzen` mit dem ECHTEN Modell an einer ECHTEN Folie.

Der Waechter prueft die Bildarbeit isoliert; hier laeuft zusaetzlich die
Uebersetzung durch das echte LLM - also genau der Teil, den eine Attrappe nicht
beantworten kann.

Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, "/opt/jarvis")
ok = fail = 0


def pruef(b, t, d=""):
    global ok, fail
    if b:
        ok += 1
        print(f"  OK   {t}")
    else:
        fail += 1
        print(f"  FAIL {t}" + (f"  [{d}]" if d else ""))


QUELLE = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/sample.gif")
if not QUELLE.is_file():
    print(f"KONNTE NICHT LAUFEN: {QUELLE} fehlt")
    sys.exit(2)

from backend.tools import bild_text as BT          # noqa: E402
from backend.tools.image_gen import _IMG_DIR, current_task_images  # noqa: E402


async def main():
    global ok, fail
    print(f"Quelle: {QUELLE} ({QUELLE.stat().st_size} Bytes)")

    # ── 1) OCR am echten Bild ────────────────────────────────────────────
    absaetze = BT.ocr_absaetze(QUELLE, "eng")
    print(f"\n1) OCR: {len(absaetze)} Absaetze")
    for a in absaetze:
        print(f"   [{a['id']}] konf={a['konf']:.0f} zh={a['zeilenhoehe']} "
              f"{a['text'][:66]}")
    pruef(len(absaetze) >= 3, "mindestens drei Textbloecke erkannt", str(len(absaetze)))
    pruef(all(a["konf"] >= 70 for a in absaetze), "alle mit brauchbarer Konfidenz",
          str([round(a["konf"]) for a in absaetze]))
    zus = [a["text"] for a in absaetze if "68" in a["text"] and "futurice" in a["text"]]
    pruef(not zus, "'68' und 'futurice' sind NICHT ein Block", str(zus))

    # ── 2) Uebersetzung durch das ECHTE Modell ───────────────────────────
    print("\n2) Uebersetzung (echtes Modell)")
    import time
    t0 = time.time()
    try:
        ue = await BT._uebersetzen(absaetze, "Deutsch")
    except Exception as e:  # noqa: BLE001
        print(f"  FAIL Uebersetzung geworfen: {e}")
        return 1
    dauer = time.time() - t0
    for k, v in sorted(ue.items()):
        print(f"   [{k}] {v[:76]}")
    pruef(bool(ue), f"das Modell hat geantwortet ({dauer:.1f}s)")
    pruef(any("Wissen" in v or "Ebene" in v for v in ue.values()),
          "der Titel ist uebersetzt", str(list(ue.values())[:1]))
    # Eigennamen bleiben - das verlangt der Prompt ausdruecklich.
    fut = [v for v in ue.values() if "futurice" in v.lower()]
    pruef(bool(fut) or not any("futurice" in a["text"].lower() for a in absaetze),
          "der Firmenname bleibt stehen", str(fut))

    # ── 3) Das Bild entsteht wirklich ────────────────────────────────────
    print("\n3) Das Werkzeug, Ende zu Ende")
    current_task_images.set([])
    t = BT.BildTextErsetzenTool()
    erg = await t.execute(pfad=str(QUELLE), zielsprache="Deutsch")
    print(f"   Ergebnis: {erg[:150]}…")
    pruef("BILD_ERZEUGT" in erg, "das Werkzeug meldet Erfolg", erg[:120])
    import re
    m = re.search(r"/api/generated/([0-9a-f]{32}\.png)", erg)
    pruef(bool(m), "eine Bild-URL wird geliefert", erg[:120])
    if m:
        p = Path(_IMG_DIR) / m.group(1)
        pruef(p.is_file(), f"die Datei existiert wirklich: {p.name}")
        if p.is_file():
            from PIL import Image
            im = Image.open(p)
            orig = Image.open(QUELLE)
            pruef(im.size == orig.size, f"gleiche Groesse wie das Original {im.size}")
            neu = " ".join(x["text"] for x in BT.ocr_absaetze(p, "deu"))
            print(f"   Text im neuen Bild: {neu[:150]}")
            pruef("Wissen" in neu or "Ebene" in neu,
                  "der deutsche Text steht IM BILD", neu[:100])
            pruef("Knowledge" not in neu, "…und der englische ist weg", neu[:100])
            pruef("futurice" in neu, "der Firmenname ist unangetastet", neu[:100])
        # Fuer den Bild-Nachtrag registriert?
        pruef(any(b.get("url") == m.group(0) for b in (current_task_images.get() or [])),
              "das Bild ist fuer den Nachtrag registriert")
        # DEV sauber hinterlassen - der Pfad wird im Aufrufer ausgegeben.
        print(f"\n   ERGEBNISBILD: {p}")
    return 1 if fail else 0


rc = asyncio.run(main())
print(f"\n{ok} bestanden, {fail} fehlgeschlagen")
sys.exit(rc)
