#!/usr/bin/env python3
"""Baut aus einzelnen PNG-Frames einen clippy.js-Agenten (map.png + agent.js).

    python3 skills/avatar/tools/build_agent.py <quellordner> <Name> [Optionen]

Erwarteter Quellordner – ein Unterordner je Animation, darin die Einzelbilder
in Abspielreihenfolge (alphabetisch sortiert):

    quelle/
      Idle1_1/     001.png 002.png 003.png     <- Pflicht: mind. eine "Idle*"
      Greeting/    001.png ...
      Explain/     001.png ...

Ein FLACHER Ordner (nur PNGs, keine Unterordner) ist ebenfalls erlaubt und
wird zu einer einzigen Animation "Idle1_1" – der Minimalfall fuer eine
Standbild-Figur (ein einzelnes PNG genuegt).

Erzeugt im Zielordner ``frontend/vendor/clippy/agents/<Name>/``:
  map.png         – Spritesheet (alle Frames in einem Raster)
  agent.js        – clippy.ready('<Name>', {...})
  sounds-mp3.js   – Pflicht-Stummdatei (s.u.)
  sounds-ogg.js   – dito

WARUM DIE STUMMDATEIEN PFLICHT SIND: clippy.js laedt beim Start immer
``sounds-mp3.js`` bzw. ``sounds-ogg.js`` und WARTET auf den Aufruf
``clippy.soundsReady('<Name>', …)``. Fehlt die Datei (404) oder steht darin ein
anderer Name, wird weder der Erfolgs- noch der Fehler-Rueckruf ausgeloest – die
Figur bleibt fuer immer im Ladezustand. Das Widget faellt dann nach 6 s auf
Clippy zurueck, ohne dass irgendwo ein Fehler steht.

Gleiche Bilder werden nur EINMAL ins Spritesheet gelegt (Vergleich ueber den
Pixelinhalt), Wiederholungen verweisen auf dieselbe Position.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:                                        # pragma: no cover
    sys.exit("Pillow fehlt:  pip install Pillow")


BILD_ENDUNGEN = {".png", ".webp", ".gif", ".bmp"}
# Ueber diese Breite hinaus wird umgebrochen. Sehr breite Texturen mag nicht
# jede GPU; 3600 px liegt unter der ueblichen 4096er-Grenze (Clippy: 3348 px).
MAX_BREITE = 3600


def frames_einlesen(ordner: Path) -> dict[str, list[Path]]:
    """{Animationsname: [Bildpfade in Reihenfolge]} aus dem Quellordner."""
    unter = sorted(d for d in ordner.iterdir() if d.is_dir())
    if unter:
        anims: dict[str, list[Path]] = {}
        for d in unter:
            bilder = sorted(p for p in d.iterdir()
                            if p.suffix.lower() in BILD_ENDUNGEN)
            if bilder:
                anims[d.name] = bilder
        return anims
    bilder = sorted(p for p in ordner.iterdir()
                    if p.suffix.lower() in BILD_ENDUNGEN)
    return {"Idle1_1": bilder} if bilder else {}


def main() -> int:
    ap = argparse.ArgumentParser(description="clippy.js-Agent aus PNG-Frames bauen")
    ap.add_argument("quelle", type=Path, help="Ordner mit den Einzelbildern")
    ap.add_argument("name", help="Agentenname = Ordnername (z.B. Nexerius)")
    ap.add_argument("--out", type=Path,
                    default=Path("frontend/vendor/clippy/agents"),
                    help="Zielordner (Vorgabe: frontend/vendor/clippy/agents)")
    ap.add_argument("--framesize", default="",
                    help="BREITExHOEHE, z.B. 124x93 (Vorgabe: Groesse des ersten Bildes)")
    ap.add_argument("--duration", type=int, default=100,
                    help="Anzeigedauer je Frame in ms (Vorgabe: 100)")
    ap.add_argument("--force", action="store_true",
                    help="vorhandenen Zielordner ueberschreiben")
    args = ap.parse_args()

    if not args.quelle.is_dir():
        return _fehler(f"Quellordner nicht gefunden: {args.quelle}")
    if not args.name.replace("_", "").replace("-", "").isalnum():
        return _fehler("Der Name darf nur Buchstaben, Ziffern, - und _ enthalten "
                       "(er wird Ordnername UND Bezeichner in agent.js).")

    anims = frames_einlesen(args.quelle)
    if not anims:
        return _fehler("Keine Bilder gefunden. Erwartet: Unterordner je Animation "
                       "oder ein flacher Ordner mit PNGs.")

    # ── Pflicht: mindestens eine Idle-Animation ──────────────────────
    # clippy spielt nach dem Einblenden von sich aus eine Animation, deren Name
    # mit "Idle" beginnt. Gibt es keine, wird NICHTS gezeichnet und die Ecke
    # bleibt leer – ohne Fehlermeldung.
    if not any(k.startswith("Idle") for k in anims):
        erste = next(iter(anims))
        anims["Idle1_1"] = list(anims[erste])
        print(f"[i] Keine 'Idle*'-Animation vorhanden – '{erste}' zusaetzlich "
              f"als 'Idle1_1' eingetragen (sonst bliebe die Figur unsichtbar).")

    # ── Rahmengroesse ────────────────────────────────────────────────
    erstes = next(iter(anims.values()))[0]
    with Image.open(erstes) as im:
        fw, fh = im.size
    if args.framesize:
        try:
            fw, fh = (int(x) for x in args.framesize.lower().split("x"))
        except ValueError:
            return _fehler("--framesize erwartet BREITExHOEHE, z.B. 124x93")
    if fw < 8 or fh < 8:
        return _fehler(f"Rahmengroesse unplausibel: {fw}x{fh}")

    # ── Frames laden, gleiche Bilder zusammenfassen ──────────────────
    positionen: dict[str, int] = {}      # Pixel-Hash -> laufender Index
    bilder: list[Image.Image] = []
    plan: dict[str, list[int]] = {}      # Animation -> Indizes je Frame
    abweichend = 0

    for anim, pfade in anims.items():
        idx_liste = []
        for p in pfade:
            with Image.open(p) as im:
                im = im.convert("RGBA")
                if im.size != (fw, fh):
                    abweichend += 1
                    im = _einpassen(im, fw, fh)
                key = hashlib.sha1(im.tobytes()).hexdigest()
                if key not in positionen:
                    positionen[key] = len(bilder)
                    bilder.append(im.copy())
                idx_liste.append(positionen[key])
        plan[anim] = idx_liste

    if abweichend:
        print(f"[i] {abweichend} Bild(er) wichen von {fw}x{fh} ab und wurden "
              f"zentriert eingepasst (nicht verzerrt).")

    # ── Spritesheet legen ────────────────────────────────────────────
    # Nie breiter als noetig: bei 8 Frames waere ein 36-Spalten-Raster zwar
    # gueltig, das Blatt bestuende aber fast nur aus leerer Flaeche.
    spalten = max(1, min(MAX_BREITE // fw, len(bilder)))
    zeilen = math.ceil(len(bilder) / spalten)
    blatt = Image.new("RGBA", (spalten * fw, zeilen * fh), (0, 0, 0, 0))
    koord: list[tuple[int, int]] = []
    for i, im in enumerate(bilder):
        x, y = (i % spalten) * fw, (i // spalten) * fh
        blatt.paste(im, (x, y))
        koord.append((x, y))

    ziel = args.out / args.name
    if ziel.exists() and not args.force:
        return _fehler(f"{ziel} existiert bereits – mit --force ueberschreiben.")
    ziel.mkdir(parents=True, exist_ok=True)
    blatt.save(ziel / "map.png", optimize=True)

    # ── agent.js ─────────────────────────────────────────────────────
    daten = {
        "overlayCount": 1,          # eine Ebene je Frame (Clippy nutzt 1)
        "sounds": [],               # keine Toene -> leere Stummdateien reichen
        "framesize": [fw, fh],
        "animations": {
            anim: {"frames": [{"duration": args.duration,
                               "images": [list(koord[i])]} for i in idx]}
            for anim, idx in plan.items()
        },
    }
    js = "clippy.ready('%s', %s);\n" % (args.name, json.dumps(daten, separators=(",", ":")))
    (ziel / "agent.js").write_text(js, encoding="utf-8")

    stumm = "clippy.soundsReady('%s', {});\n" % args.name
    (ziel / "sounds-mp3.js").write_text(stumm, encoding="utf-8")
    (ziel / "sounds-ogg.js").write_text(stumm, encoding="utf-8")

    kb = (ziel / "map.png").stat().st_size / 1024
    print(f"\n[OK] {ziel}")
    print(f"     Rahmen   : {fw}x{fh}")
    print(f"     Frames   : {sum(len(v) for v in plan.values())} "
          f"({len(bilder)} eindeutig, {spalten}x{zeilen}-Raster, {kb:.0f} KB)")
    print(f"     Animation: {', '.join(sorted(plan))}")
    print("\nNaechster Schritt – auf den Server kopieren und in den Einstellungen waehlen:")
    print(f"  scp -r {ziel} root@<server>:/opt/jarvis/frontend/vendor/clippy/agents/")
    print("  Einstellungen -> Avatar -> Figur/Grafik -> "
          f"'{args.name}'   (kein Dienst-Neustart noetig)")
    return 0


def _einpassen(im: Image.Image, fw: int, fh: int) -> Image.Image:
    """Bild proportional in fw x fh einpassen und zentrieren (nie verzerren)."""
    im.thumbnail((fw, fh), Image.LANCZOS)
    leer = Image.new("RGBA", (fw, fh), (0, 0, 0, 0))
    leer.paste(im, ((fw - im.width) // 2, (fh - im.height) // 2))
    return leer


def _fehler(text: str) -> int:
    print("[Fehler] " + text, file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
