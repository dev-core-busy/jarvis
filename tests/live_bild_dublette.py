#!/usr/bin/env python3
"""LIVE: die DOPPELTE Registrierung einer Delegation, mit dem deployten Code.

Stellt den ECHT-Ablauf nach: Rollen-Agent birgt das Bild aus seiner Antwort,
Hauptagent birgt dasselbe Bild aus dem Werkzeug-Ergebnis - dieselbe URL, weil
inhaltsadressiert. Gemessen wird, wie oft sie am Ende im Anzeigetext steht.

Exit 0 = bestanden, 1 = FAIL, 2 = konnte nicht laufen.
"""
import base64, struct, sys, zlib
sys.path.insert(0, "/opt/jarvis")
from backend.tools.image_gen import current_task_images, record_task_image  # noqa: E402
from backend.agent import JarvisAgent                                        # noqa: E402

ok = fail = 0
def pruef(b, t):
    global ok, fail
    if b: ok += 1
    else: fail += 1; print(f"  FAIL: {t}")

def png(w=32, h=32):
    def ch(t, d):
        r = t + d
        return struct.pack(">I", len(d)) + r + struct.pack(">I", zlib.crc32(r))
    rows = b"".join(b"\x00" + bytes(sum(([0,180,0] for _ in range(w)), [])) for _ in range(h))
    return (b"\x89PNG\r\n\x1a\n" + ch(b"IHDR", struct.pack(">IIBBBBB", w,h,8,2,0,0,0))
            + ch(b"IDAT", zlib.compress(rows,6)) + ch(b"IEND", b""))

B64 = base64.b64encode(png()).decode()
agent = JarvisAgent.__new__(JarvisAgent)
agent.agent_id = "live-dublette"
agent.tools_map = {}

tok = current_task_images.set([])
try:
    # 1) Rollen-Agent birgt aus SEINER Antwort  -> record_task_image #1
    roll_antwort = f"Hier ist das Bild:\n\n![Kuh](data:image/png;base64,{B64})"
    agent._bilddaten_bergen("(verlauf)", roll_antwort, fuer_anzeige=True)
    # 2) Hauptagent birgt dasselbe aus dem Werkzeug-Ergebnis -> record_task_image #2
    agent._bilddaten_bergen("delegate:image_builder", roll_antwort, fuer_anzeige=True)

    bilder = current_task_images.get()
    urls = [b["url"] for b in bilder]
    print(f"  registriert: {len(bilder)} Eintrag/Eintraege -> {set(urls)}")
    pruef(len(bilder) == 1, f"dieselbe URL {len(bilder)}x registriert (erwartet 1)")

    # 3) Der Nachtrag in einer Antwort, die das Bild NICHT nennt (echter Fall:
    #    die Delegation meldete einen Fehler, das Bild lag trotzdem vor).
    text = agent._mit_bildern("Die Bildgenerierung ist fehlgeschlagen.")
    n = text.count("/api/generated/")
    print(f"  Bildrefs im Anzeigetext: {n}")
    pruef(n == 1, f"das Bild steht {n}x im Text (erwartet genau 1) -> {text[-200:]!r}")

    # 4) Gegenrichtung: ein ZWEITES, anderes Bild muss erscheinen.
    record_task_image("/tmp/x.png", "/api/generated/" + "a"*32 + ".png")
    text2 = agent._mit_bildern("Fertig.")
    pruef(text2.count("/api/generated/") == 2,
          f"zwei verschiedene Bilder nicht beide angehaengt ({text2.count('/api/generated/')})")
finally:
    current_task_images.reset(tok)

print(f"\n{ok} bestanden, {fail} fehlgeschlagen")
sys.exit(1 if fail else 0)
