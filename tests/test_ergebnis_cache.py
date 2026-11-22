#!/usr/bin/env python3
"""Waechter: der Ergebnis-Cache der Baum-Waechter liefert nie ein veraltetes Ergebnis.

WARUM (2026-11-22): ``test_keine_echtwerte`` und ``test_kommentare_deutsch``
nehmen ihr Ergebnis je Datei aus ``tests/lib/ergebnis_cache.py``, solange
Pfad, Inhalt und Pruefer gleich sind (35 s bzw. 13 s -> unter 1 s). Ein Cache
in einem Sicherheitswaechter ist nur dann eine Beschleunigung und kein Loch,
wenn er (a) jede Aenderung bemerkt und (b) gespeicherte FUNDE wieder meldet.

Teil A misst den Helfer: Treffer nur bei gleichem Pfad, gleichem Inhalt und
gleichem Pruefer; nur Beruehrtes wird gespeichert; ein kaputter Cache ist
leer; ``JARVIS_WAECHTER_CACHE=aus`` schaltet ab; alte Fingerabdruecke werden
nach Alter abgeraeumt.
Teil B misst die beiden ECHTEN Waechter mit einem Wegwerf-Cache: ein
gespeicherter Fund mit passendem md5 wird gemeldet (Exit 1), derselbe Fund
mit falschem md5 wird verworfen und die Datei neu geprueft (Exit 0).

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht messen.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"
sys.path.insert(0, str(TESTS / "lib"))

ok = fail = 0


def pruefe(text, bedingung, zusatz=""):
    global ok, fail
    if bedingung:
        ok += 1
        print("  OK   " + text)
    else:
        fail += 1
        print("  FAIL " + text + (("  -> %s" % (zusatz,)) if zusatz else ""))


def abbruch(grund):
    print("\nABBRUCH (Exit 2): " + grund)
    print("Ergebnis: %d OK, %d FAIL (nicht deutbar)" % (ok, fail))
    sys.exit(2)


import ergebnis_cache  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="waechter-cache-"))
alt_env = os.environ.get("JARVIS_WAECHTER_CACHE")
try:
    # ═══ Teil A: der Helfer ═════════════════════════════════════════════
    print("Teil A: tests/lib/ergebnis_cache.py")
    os.environ["JARVIS_WAECHTER_CACHE"] = str(tmp / "a")
    dep = tmp / "pruefer.py"
    dep.write_text("REGEL = 1\n")

    def neu():
        return ergebnis_cache.ErgebnisCache("probe", [dep])

    c = neu()
    da, _ = c.holen("x.py", b"inhalt")
    if da or not c.aktiv:
        abbruch("leerer Cache liefert einen Treffer oder ist nicht aktiv")
    c.ablegen("x.py", b"inhalt", [[3, "fund"]])
    c.ablegen("y.py", b"anderes", [])
    c.speichern()

    c = neu()
    da, erg = c.holen("x.py", b"inhalt")
    pruefe("gleicher Pfad + Inhalt + Pruefer: Treffer mit dem gespeicherten FUND",
           da and erg == [[3, "fund"]], (da, erg))
    pruefe("geaenderter Inhalt: kein Treffer", c.holen("x.py", b"inhalt!") == (False, None))
    pruefe("gleicher Inhalt unter anderem Pfad: kein Treffer", c.holen("z.py", b"inhalt") == (False, None))
    c.speichern()   # y.py wurde in diesem Lauf nicht beruehrt
    c = neu()
    pruefe("nur Beruehrtes wird gespeichert (nicht gelesene Datei faellt heraus)",
           c.holen("y.py", b"anderes") == (False, None) and c.holen("x.py", b"inhalt")[0])
    alte_datei = c._datei

    dep.write_text("REGEL = 2\n")
    c2 = neu()
    pruefe("geaenderter Pruefer: anderer Fingerabdruck, kein Treffer",
           c2.fingerabdruck != c.fingerabdruck and c2.holen("x.py", b"inhalt") == (False, None))
    c2.ablegen("x.py", b"inhalt", [])
    c2.speichern()
    pruefe("…und der Cache des alten Pruefers bleibt liegen (eigene Datei je Fingerabdruck)",
           alte_datei.is_file() and c2._datei.is_file() and alte_datei != c2._datei)

    c2._datei.write_text("{kaputt")
    try:
        c3 = neu()
        kaputt_ok = c3.holen("x.py", b"inhalt") == (False, None)
    except Exception as exc:  # noqa: BLE001
        kaputt_ok = f"Absturz {exc}"
    pruefe("kaputte Cache-Datei: leer statt Absturz", kaputt_ok is True, kaputt_ok)
    # Die kaputte Datei nicht in die folgenden Pruefungen mitnehmen - sonst
    # stuerzt dort ein defekter Helfer ab, und der Befund kaeme ohne Bilanz.
    c2._datei.unlink()

    # Aufraeumen nach Alter: ein 8 Tage alter fremder Fingerabdruck verschwindet
    uralt = tmp / "a" / "probe-0000000000000000.json"
    uralt.write_text("{}")
    acht_tage = time.time() - 8 * 24 * 3600
    os.utime(uralt, (acht_tage, acht_tage))
    c4 = neu()
    c4.ablegen("x.py", b"inhalt", [])
    c4.speichern()
    pruefe("Fingerabdruecke aelter als 7 Tage werden abgeraeumt, juengere bleiben",
           not uralt.exists() and alte_datei.is_file())

    os.environ["JARVIS_WAECHTER_CACHE"] = "aus"
    vorher = set((tmp / "a").iterdir())
    # Im Wegwerf-Ordner: ein Helfer, der "aus" fuer einen Pfad haelt, legt ihn
    # relativ zum Arbeitsverzeichnis an - nicht im Repo (so geschehen in der
    # Gegenprobe, 2026-11-22).
    hier = os.getcwd()
    os.chdir(tmp)
    try:
        c5 = neu()
        c5.ablegen("x.py", b"inhalt", [])
        c5.speichern()
    finally:
        os.chdir(hier)
    pruefe("JARVIS_WAECHTER_CACHE=aus: kein Treffer, nichts geschrieben",
           not c5.aktiv and c5.holen("x.py", b"inhalt") == (False, None)
           and set((tmp / "a").iterdir()) == vorher and not (tmp / "aus").exists())

    # ═══ Teil B: die echten Waechter ═══════════════════════════════════
    print("\nTeil B: test_keine_echtwerte.py und test_kommentare_deutsch.py mit Wegwerf-Cache")
    ZIEL = "tests/lib/ergebnis_cache.py"        # liegt im Geltungsbereich beider
    ziel_md5 = ergebnis_cache.ErgebnisCache._md5((ROOT / ZIEL).read_bytes())
    WAECHTER = {
        # Name, Dateiname, erfundenes Ergebnis mit Fund, Text, an dem der Fund zu erkennen ist
        "keine_echtwerte": ("test_keine_echtwerte.py", [[7, "erfundener.wert.sonde"]],
                            "erfundener.wert.sonde"),
        "kommentare_deutsch": ("test_kommentare_deutsch.py",
                               [1, [ZIEL + ":7: this is the erfundene sonde"]],
                               "this is the erfundene sonde"),
    }
    for name, (datei, erfunden, kennung) in WAECHTER.items():
        vz = tmp / ("b-" + name)
        vz.mkdir()
        os.environ["JARVIS_WAECHTER_CACHE"] = str(vz)
        fa = ergebnis_cache.ErgebnisCache(name, [TESTS / datei]).fingerabdruck
        cache_datei = vz / f"{name}-{fa}.json"
        # Vorwaermen aus dem Cache des Betreibers, falls es ihn gibt (nur Tempo:
        # jeder Eintrag wird vom Waechter selbst per md5 geprueft).
        eigen = Path(alt_env) if alt_env and alt_env != "aus" else \
            Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "jarvis" / "waechter"
        vorrat = eigen / cache_datei.name
        if vorrat.is_file():
            shutil.copy2(vorrat, cache_datei)
        umg = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", JARVIS_WAECHTER_CACHE=str(vz))

        def lauf():
            r = subprocess.run([sys.executable, str(TESTS / datei)], capture_output=True, text=True,
                               timeout=900, cwd=ROOT, env=umg)
            return r.returncode, r.stdout + r.stderr

        rc, aus = lauf()
        if rc != 0 or "Cache: " not in aus or not cache_datei.is_file():
            abbruch(f"{datei}: Grundlauf nicht gruen oder ohne Cache (rc={rc})\n{aus[-600:]}")
        try:
            roh = json.loads(cache_datei.read_text())
            eintraege = roh["eintraege"]
        except (OSError, ValueError, KeyError) as exc:
            abbruch(f"{datei}: Cache-Datei unlesbar ({exc})")
        if ZIEL not in eintraege or eintraege[ZIEL][0] != ziel_md5:
            abbruch(f"{datei}: {ZIEL} fehlt im Cache - die Probe traefe nichts")

        eintraege[ZIEL] = [ziel_md5, erfunden]
        cache_datei.write_text(json.dumps(roh))
        rc, aus = lauf()
        pruefe(f"{datei}: gespeicherter Fund (md5 passt) wird gemeldet",
               rc == 1 and kennung in aus, f"rc={rc}")

        roh = json.loads(cache_datei.read_text())
        roh["eintraege"][ZIEL] = ["0" * 32, erfunden]
        cache_datei.write_text(json.dumps(roh))
        rc, aus = lauf()
        pruefe(f"{datei}: derselbe Fund mit falschem md5 wird verworfen, die Datei neu geprueft",
               rc == 0 and kennung not in aus, f"rc={rc}")
finally:
    if alt_env is None:
        os.environ.pop("JARVIS_WAECHTER_CACHE", None)
    else:
        os.environ["JARVIS_WAECHTER_CACHE"] = alt_env
    shutil.rmtree(tmp, ignore_errors=True)

print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
