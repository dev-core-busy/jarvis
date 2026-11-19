#!/usr/bin/env python3
"""Gegenprobe zu tests/test_idp_anmeldung_ui.js, Abschnitt D ("Automatisch anmelden").

Jede Probe dreht EINE Regel zurueck (Ersetzung ganzer Zeilen), laesst den
Waechter laufen und erwartet mindestens einen FAIL (Exit 1). Exit 2 des
Waechters zaehlt NICHT als Biss (die Positivkontrolle hat dann abgebrochen).
Vorher gruener Basislauf, danach Byte-Gleichheit aller Dateien per md5.
Gepatcht werden nur idp_anmeldung.js und app.js – i18n.js und settings.html
bearbeitet der Betreiber parallel, die bleiben bewusst unangetastet.

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen.
"""
from __future__ import annotations

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)


import hashlib
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_idp_anmeldung_ui.js"
MOD = "frontend/js/idp_anmeldung.js"
APP = "frontend/js/app.js"
SICHERUNG = Path.home() / ".gegen_idp_auto_sicherung"

PROBEN = [
    ("ohne Haken trotzdem Start", MOD,
     "        if (!l.gewuenscht) return 'aus';\n", "        if (false) return 'aus';\n"),
    ("IdP aus trotzdem Start", MOD,
     "        if (!l.aktiv) return 'idp_aus';\n", "        if (false) return 'idp_aus';\n"),
    ("auch unter /settings", MOD,
     "        if (l.pfad !== '/') return 'pfad';\n", "        if (false) return 'pfad';\n"),
    ("Rueckkehr vom IdP startet erneut", MOD,
     "        if (l.rueckkehr) return 'rueckkehr';\n", "        if (false) return 'rueckkehr';\n"),
    ("nach dem Abmelden sofort wieder angemeldet", MOD,
     "        if (l.vonJarvis) return 'von_jarvis';\n", "        if (false) return 'von_jarvis';\n"),
    ("keine Schleifenbremse", MOD,
     "        if (l.letzter && l.jetzt - l.letzter >= 0 && l.jetzt - l.letzter < AUTO_SPERRE_MS) return 'schleife';\n",
     "        if (false) return 'schleife';\n"),
    ("Start, waehrend app.js das Token prueft", MOD,
     "        if (!l.maske) return 'maske';\n", "        if (false) return 'maske';\n"),
    ("mitgebrachtes Token ignoriert", MOD,
     "        autoLage.maske = autoLage.maske || !window.JarvisSitzung.token();\n",
     "        autoLage.maske = true;\n"),
    ("mehrfacher Start", MOD,
     "        if (autoLage.erledigt || autoLage.aktiv === null) return;\n",
     "        if (autoLage.aktiv === null) return;\n"),
    ("Startzeit nicht gemerkt", MOD,
     "        try { sessionStorage.setItem(AUTO_ZEIT, String(Date.now())); } catch (e) { /* Bremse fehlt dann */ }\n",
     ""),
    ("start() laeuft zweimal", MOD,
     "        if (gestartet) return;\n", ""),
    ("Haken wird nicht gespeichert", MOD,
     "        cb.addEventListener('change', function () { autoMerken(cb.checked); });\n", ""),
    ("Haken zeigt den gespeicherten Stand nicht", MOD,
     "        cb.checked = autoGewuenscht();\n", ""),
    ("Ereignis auch aus showLoginScreen", APP,
     "        if (window.JarvisSession) window.JarvisSession.logout(token);\n        mainScreen.classList.remove('active');\n",
     "        if (window.JarvisSession) window.JarvisSession.logout(token);\n"
     "        document.dispatchEvent(new CustomEvent('jarvis-anmeldemaske'));\n"
     "        mainScreen.classList.remove('active');\n"),
    ("Tokenpruefung: Netzfehler ohne Ereignis", APP,
     "        }).catch(() => {\n            _maskeNachTokenpruefung();\n",
     "        }).catch(() => {\n            showLoginScreen();\n"),
]
DATEIEN = sorted({p[1] for p in PROBEN})


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def lauf() -> tuple[int, str]:
    r = subprocess.run(["node", str(WAECHTER)], cwd=ROOT, capture_output=True,
                       text=True, timeout=300)
    zeile = next((z for z in reversed(r.stdout.splitlines())
                  if z.startswith("Ergebnis") or z.startswith("ABBRUCH")), "")
    return r.returncode, zeile


def zurueck() -> None:
    if not SICHERUNG.exists():
        return
    for rel in DATEIEN:
        quelle = SICHERUNG / rel
        if quelle.exists():
            shutil.copy2(quelle, ROOT / rel)
    shutil.rmtree(SICHERUNG)


def main() -> int:
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Dateiliste unvollstaendig.")
        return 2
    zurueck()  # Rueckstand eines abgebrochenen Laufs
    for name, rel, alt, _neu in PROBEN:
        n = (ROOT / rel).read_text(encoding="utf-8").count(alt)
        if n != 1:
            print("ABBRUCH: Anker %dx gefunden – %s" % (n, name))
            return 2
    code, zeile = lauf()
    if code != 0:
        print("ABBRUCH: Basislauf nicht gruen (%s, Exit %d)" % (zeile, code))
        return 2
    print("Basislauf gruen: " + zeile)
    vorher = {rel: md5(ROOT / rel) for rel in DATEIEN}
    SICHERUNG.mkdir(mode=0o700)
    for rel in DATEIEN:
        (SICHERUNG / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / rel, SICHERUNG / rel)
    stumm = []
    try:
        for name, rel, alt, neu in PROBEN:
            pfad = ROOT / rel
            original = pfad.read_text(encoding="utf-8")
            pfad.write_text(original.replace(alt, neu), encoding="utf-8")
            try:
                code, zeile = lauf()
            finally:
                pfad.write_text(original, encoding="utf-8")
            biss = code == 1
            print("%s  %-46s %s (Exit %d)" % ("BEISST" if biss else "STUMM ", name, zeile, code))
            if not biss:
                stumm.append(name)
    finally:
        zurueck()
    nachher = {rel: md5(ROOT / rel) for rel in DATEIEN}
    if nachher != vorher:
        print("FEHLER: Dateien nach der Gegenprobe nicht byte-gleich!")
        return 2
    print("\nDateien byte-gleich wiederhergestellt.")
    print("Bilanz: %d von %d Proben beissen" % (len(PROBEN) - len(stumm), len(PROBEN)))
    return 0 if not stumm else 1


if __name__ == "__main__":
    sys.exit(main())
