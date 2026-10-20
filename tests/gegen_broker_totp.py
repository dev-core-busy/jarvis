#!/usr/bin/env python3
"""Gegenprobe zu ``test_broker_totp.py``: beisst der Waechter wirklich?

Ein gruener Waechter beweist nichts, solange niemand gemessen hat, dass er bei
einem echten Rueckfall ROT wird. Diese Probe dreht nacheinander je eine Zusage
im PRODUKT zurueck und verlangt Exit 1.

Gemessen wird das Produkt, nicht der Waechter: eine Sabotage an der tragenden
Zeile des Waechters selbst waere eine falsch platzierte Probe (Register).

Vorgehen je Probe:
  1. Basislauf muss GRUEN sein - ohne gruene Basis ist kein Ergebnis deutbar.
  2. Datei auf Platte sichern, Sabotage einbauen, Waechter laufen lassen.
  3. Zuruecknehmen und die Byte-Gleichheit per md5 NACHSEHEN, nicht annehmen.

Eine Laufmarke faengt den Abbruch mitten in einer Probe ab: beim naechsten Start
wird der Rueckstand zuerst zurueckgenommen. ``kill`` fuehrt kein ``atexit`` aus
(Register) - deshalb die Marke auf Platte und nicht nur ein ``finally``.

NICHT in einem Sammellauf ueber ``tests/*.py`` mitlaufen lassen - diese Datei
patcht den Arbeitsbaum (Register).

Exit 0 = der Waechter beisst, 1 = er beisst nicht, 2 = konnte nicht laufen.
"""
import hashlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
WAECHTER = WURZEL / "tests" / "test_broker_totp.py"
MARKE = Path.home() / ".gegen_broker_totp.laeuft"

FREIGABE = WURZEL / "backend" / "broker" / "freigabe.py"
MAIN = WURZEL / "backend" / "main.py"
ADMIN = WURZEL / "backend" / "broker" / "admin.py"
TRESOR = WURZEL / "backend" / "geheimnis_tresor.py"

# Jede Datei, die eine Probe anfasst, MUSS hier stehen - sonst bleibt eine
# Sabotage liegen und der naechste Lauf meldet einen Fehler, den es nicht gibt
# (Register: zweimal darauf hereingefallen). Die Liste wird unten als REGEL
# gegen die Proben geprueft, nicht gepflegt.
DATEIEN = [FREIGABE, MAIN, ADMIN, TRESOR]

# (Name, Datei, [(alt, neu), ...])
PROBEN = [
    ("Wiederholschutz GETRENNT statt gemeinsam", FREIGABE, [
        ('if s <= z["letzter_schritt"]:', 'if s <= z.get(f"ls_{zweck}", 0):'),
        ('z["letzter_schritt"] = s', 'z[f"ls_{zweck}"] = s'),
    ]),
    ("Sperren GEMEINSAM statt getrennt", FREIGABE, [
        ('if z[f"gesperrt_bis_{zweck}"] > t:',
         'if max(z[f"gesperrt_bis_{x}"] for x in ZWECKE) > t:'),
    ]),
    ("uebernehmen() setzt den laufenden Schritt auf 0", FREIGABE, [
        ('z["letzter_schritt"] = int(t // SCHRITT_S)', 'z["letzter_schritt"] = 0'),
    ]),
    ("unbekannter Zweck laeuft als Freigabe durch", FREIGABE, [
        ('    if zweck not in ZWECKE:\n'
         '        # Kein ratbarer Zweck: ein Tippfehler darf keine Pruefung ohne Sperre erzeugen.\n'
         '        return False, "nachweis_falsch"\n',
         '    if zweck not in ZWECKE:\n'
         '        zweck = ZWECK_FREIGABE\n'),
    ]),
    # Der Vorfall beim Bau dieser Aenderung: ein zweiter Pruefweg uebersehen.
    ("zweiter Pruefweg (/api/auth/bestaetigen) uebergeht den Broker", MAIN, [
        ('        if _totp_im_broker(geheim):', '        if False:'),
    ]),
    ("Broker-Abfrage ist fail-OPEN statt fail-closed", MAIN, [
        ('        return False, "unreachable"\n'
         '    if not isinstance(res, dict):',
         '        return True, "ok"\n'
         '    if not isinstance(res, dict):'),
    ]),
    ("Erfolg haengt an der Wahrheit des Feldes statt an 'is True'", MAIN, [
        ('if res.get("ok") is True:', 'if res.get("ok"):'),
    ]),
    ("die Marke wird abgetippt verglichen", MAIN, [
        ('    from backend.broker import freigabe as _f\n'
         '    return secret == _f.MARKE_IM_BROKER',
         '    return secret == "broker"'),
    ]),
    # Der auf DEV gemessene Mangel: der Verweis wird wie ein Geheimnis verpackt.
    ("die Broker-Marke wird wieder verpackt", TRESOR, [
        ('    if wert in KLARTEXT_WERTE:\n        return wert\n', ''),
    ]),
    ("die Marke zaehlt wieder als Klartext-Altbestand", TRESOR, [
        ('                        and v not in KLARTEXT_WERTE \\\n', ''),
    ]),
    ("Notweg totp-aus entfernt", ADMIN, [
        ('if befehl in ("totp-uebernehmen", "totp-aus"):',
         'if befehl in ("totp-uebernehmen",):'),
    ]),
    ("chmod vor chown (chown loescht setgid)", ADMIN, [
        ('    os.chown(tmp, st.st_uid, st.st_gid)\n'
         '    os.chmod(tmp, st.st_mode & 0o7777)   # chmod NACH chown – chown loescht setgid',
         '    os.chmod(tmp, st.st_mode & 0o7777)\n'
         '    os.chown(tmp, st.st_uid, st.st_gid)'),
    ]),
]


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def sichern() -> dict:
    return {p: shutil.copy2(p, str(p) + ".gegenprobe-bak") for p in DATEIEN}


def zurueck(sicherungen: dict) -> None:
    for ziel, bak in sicherungen.items():
        shutil.copy2(bak, ziel)
        os.unlink(bak)


def waechter_laeuft() -> tuple[int, str]:
    umgebung = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(WAECHTER)], capture_output=True,
                       text=True, cwd=str(WURZEL), env=umgebung, timeout=300)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def main() -> int:
    # REGEL statt gepflegter Liste: jede Probendatei muss gesichert werden.
    fehlend = {p for _, p, _ in PROBEN} - set(DATEIEN)
    if fehlend:
        print("ABBRUCH (Exit 2): Probendatei(en) nicht in DATEIEN: "
              + ", ".join(str(p) for p in fehlend))
        return 2

    # Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen.
    if MARKE.exists():
        print("Rueckstand eines abgebrochenen Laufs gefunden – nehme ihn zurueck.")
        for p in DATEIEN:
            bak = Path(str(p) + ".gegenprobe-bak")
            if bak.exists():
                shutil.copy2(bak, p)
                os.unlink(bak)
        MARKE.unlink()

    # Ohne gruenen Basislauf ist keine Gegenprobe deutbar.
    rc, ausgabe = waechter_laeuft()
    if rc != 0:
        print(f"ABBRUCH (Exit 2): Basislauf ist nicht gruen (Exit {rc}).")
        print(ausgabe[-2000:])
        return 2
    print(f"Basislauf gruen (Exit 0). {len(PROBEN)} Proben.\n")

    MARKE.write_text("laeuft", encoding="utf-8")
    vorher = {p: md5(p) for p in DATEIEN}
    stumm = []
    try:
        for name, datei, ersetzungen in PROBEN:
            sicherungen = sichern()
            try:
                text = datei.read_text(encoding="utf-8")
                for alt, neu in ersetzungen:
                    if alt not in text:
                        print(f"  ABBRUCH (Exit 2): Anker fehlt in {datei.name}: {alt[:70]!r}")
                        return 2
                    text = text.replace(alt, neu, 1)
                datei.write_text(text, encoding="utf-8")
                rc, ausgabe = waechter_laeuft()
            finally:
                zurueck(sicherungen)
            # "Exit 1 mit Bilanz" ist der Biss. Exit 2 waere "konnte nicht laufen",
            # ein Absturz ohne Bilanz ebenfalls - beides zaehlt NICHT als Biss.
            hat_bilanz = " ok, " in ausgabe
            beisst = rc == 1 and hat_bilanz
            zustand = "beisst" if beisst else (
                f"STUMM (Exit {rc})" if hat_bilanz else f"KEINE BILANZ (Exit {rc})")
            print(f"  {name}: {zustand}")
            if not beisst:
                stumm.append(name)
                print(ausgabe[-900:])
    finally:
        if MARKE.exists():
            MARKE.unlink()

    # Byte-Gleichheit NACHSEHEN, nicht annehmen.
    kaputt = [str(p) for p in DATEIEN if md5(p) != vorher[p]]
    if kaputt:
        print("\nABBRUCH (Exit 2): Dateien nach dem Zuruecknehmen NICHT byte-gleich: "
              + ", ".join(kaputt))
        return 2

    print(f"\n{len(PROBEN) - len(stumm)}/{len(PROBEN)} Proben beissen; "
          "alle Dateien byte-gleich zurueckgestellt.")
    for z in stumm:
        print(f"  STUMM: {z}")
    return 1 if stumm else 0


if __name__ == "__main__":
    sys.exit(main())
