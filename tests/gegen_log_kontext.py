#!/usr/bin/env python3
"""Gegenprobe zu tests/test_log_kontext.py: beisst der Waechter?

Jede Probe dreht EINE Zusage von „wer und wodurch an jeder Protokollzeile"
zurueck, laesst den Waechter laufen und erwartet mindestens einen FAIL. Vorher
gruener Basislauf, danach Byte-Gleichheit aller Dateien per md5. Ohne Bytecode
(Register: eine .pyc aus derselben Sekunde laedt sonst die Sabotage nach).

NIE in einem Sammellauf mitlaufen lassen – sie patcht Produktdateien.

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
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_log_kontext.py"
LK = "backend/log_kontext.py"
TEL = "backend/telemetry.py"
TV = "backend/token_verbrauch.py"
AGENT = "backend/agent.py"
MAIN = "backend/main.py"

PROBEN = [
    # --- das Modul ---
    ("stdout-Huelle setzt nichts davor", LK,
     '                if kz:\n                    s = kz + " " + s\n',
     '                pass\n'),
    ("Logging-Filter wird nicht angehaengt", LK,
     "            h.addFilter(filt)\n", "            pass\n"),
    ("Formatter ohne Vorgabewert fuer kontext", LK,
     '        h.setFormatter(logging.Formatter(LOG_FORMAT, defaults={"kontext": ""}))\n',
     '        h.setFormatter(logging.Formatter(LOG_FORMAT))\n'),
    ("stdout wird nicht umhuellt", LK,
     "        sys.stdout = _KontextStrom(sys.stdout)\n", "        pass\n"),
    ("Unter-Lauf erbt nicht", LK,
     "    neu = dict(alt)\n", "    neu = {}\n"),
    ("ergaenzen ueberschreibt den ersten Benutzer", LK,
     "        d.setdefault(k, v)\n", "        d[k] = v\n"),
    ("Werte behalten Leerraum", LK,
     '    s = _LEER.sub("_", str(v if v is not None else "").strip())\n',
     '    s = str(v if v is not None else "").strip()\n'),
    ("ReadTimeout ohne Deutung", LK,
     "                    msg = _DEUTUNG[kl.__name__]\n", "                    pass\n"),
    ("Vermerke werden nicht angehaengt", LK,
     '            msg = msg + " – " + " – ".join(notizen)\n', "            pass\n"),
    ("Endpunkt mit Benutzer/Kennwort/Query", LK,
     "        t = urlsplit(url)\n", "        return url\n"),
    ("Vermerk mehrfach je Ausnahme", LK,
     '        if isinstance(exc, asyncio.CancelledError) or getattr(exc, "_jarvis_llm_vermerkt", False):\n',
     '        if isinstance(exc, asyncio.CancelledError):\n'),
    ("Stopp wird als Stoerung vermerkt", LK,
     '        if isinstance(exc, asyncio.CancelledError) or getattr(exc, "_jarvis_llm_vermerkt", False):\n',
     '        if getattr(exc, "_jarvis_llm_vermerkt", False):\n'),
    # --- Telemetrie ---
    ("Span nimmt keinen Kontext mit", TEL,
     "            self.kontext: dict = log_kontext.aktuell()\n",
     "            self.kontext: dict = {}\n"),
    ("Fehlerlog-Eintrag ohne kontext", TEL,
     '            "kontext": self.kontext,\n', ""),
    # --- LLM-Huelle ---
    ("LLM-Huelle vermerkt nicht, was gerufen wurde", TV,
     "                    log_kontext.llm_aufruf_vermerken(e, self, modell, time.monotonic() - t0)\n",
     "                    pass\n"),
    # --- Chat-Auftrag ---
    ("run_task oeffnet keinen Kontext", AGENT,
     "        _lk_token = _log_kontext.oeffnen(\n"
     '            wer=username, ip=("" if client_ip in ("", "unknown") else client_ip),\n'
     "            kanal=client_type, chat=session_id, agent=self.agent_id)\n",
     "        _lk_token = None\n"),
    ("run_task schliesst den Kontext nicht", AGENT,
     "            _log_kontext.schliessen(_lk_token)\n        # Benutzer-Stop hat immer Vorrang",
     "        # Benutzer-Stop hat immer Vorrang"),
    ("Fehlerlog nur mit Typname (Altstand)", AGENT,
     "            _err_detail = _log_kontext.fehlertext(e)\n",
     "            _err_detail = str(e).strip() or type(e).__name__\n"),
    ("Journal-Zeile ohne Ursache (Altstand)", AGENT,
     '            _log(f"EXCEPTION {type(e).__name__}: {_log_kontext.fehlertext(e)}\\n{_tb}")\n',
     '            _log(f"EXCEPTION: {e}\\n{_tb}")\n'),
    # --- Lauf ohne Oberflaeche ---
    ("Headless-Lauf ohne Kontext", AGENT,
     "        _lk_token = _log_kontext.oeffnen(**_headless_herkunft(self, actor))\n",
     "        _lk_token = None\n"),
    ("Headless-Fehler ohne Journal-Zeile (Altstand)", AGENT,
     '            _log(f"EXCEPTION {type(e).__name__}: {_hl_error}\\n{_hl_tb}")\n', ""),
    ("Headless ohne Auftragsquelle", AGENT,
     '            felder["auftrag"] = str(getattr(a, "quelle", "") or "")\n', "            pass\n"),
    ("Headless-Fehlerlog nur mit Typname (Altstand)", AGENT,
     "            _hl_error = _log_kontext.fehlertext(e)\n",
     "            _hl_error = str(e).strip() or type(e).__name__\n"),
    # --- HTTP ---
    ("Middleware ohne Kontext", MAIN,
     "        lk = _log_kontext.oeffnen(ip=_log_kontext.ip_aus_scope(scope),\n"
     "                                  weg=_log_kontext.weg_aus_scope(scope))\n",
     "        lk = None\n"),
    ("unbehandelter HTTP-Fehler ohne gekennzeichnete Zeile", MAIN,
     '            print(f"[HTTP] Unbehandelter Fehler {type(e).__name__}: "\n'
     '                  f"{_log_kontext.fehlertext(e)}", flush=True)\n', ""),
    ("Middleware schliesst nicht", MAIN,
     "            _log_kontext.schliessen(lk)\n", ""),
    ("verify_token traegt den Benutzer nicht nach", MAIN,
     "            _log_kontext.ergaenzen(wer=_norm_login(username))\n", ""),
    ("installieren() fehlt in main.py", MAIN,
     "_log_kontext.installieren()\n", ""),
]

DATEIEN = [LK, TEL, TV, AGENT, MAIN, "tests/test_log_kontext.py"]


def md5(pfad: str) -> str:
    return hashlib.md5((ROOT / pfad).read_bytes()).hexdigest()


def lauf() -> tuple[int, int]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    py = ROOT / "venv" / "bin" / "python"
    r = subprocess.run([str(py if py.exists() else sys.executable), str(WAECHTER)],
                       capture_output=True, text=True, timeout=300, cwd=str(ROOT), env=env)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    if r.returncode == 2 or not m:
        return -1, r.returncode
    return int(m.group(2)), r.returncode


def main() -> int:
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe fasst eine nicht gesicherte Datei an")
        return 2
    sicherung = {d: (ROOT / d).read_bytes() for d in DATEIEN}
    vorher = {d: md5(d) for d in DATEIEN}

    fails, rc = lauf()
    if fails != 0:
        print("ABBRUCH: Basislauf nicht gruen (FAIL=%s, rc=%s)" % (fails, rc))
        return 2
    print("Basislauf gruen.\n")

    beissen = 0
    try:
        for name, datei, alt, neu in PROBEN:
            pfad = ROOT / datei
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print("  ???  %s – Anker %dx gefunden" % (name, text.count(alt)))
                continue
            pfad.write_text(text.replace(alt, neu), encoding="utf-8")
            try:
                fails, rc = lauf()
            finally:
                pfad.write_bytes(sicherung[datei])
            if fails > 0:
                beissen += 1
                print("  BISS %-56s %d FAIL" % (name, fails))
            elif fails < 0:
                print("  ABBR %-56s Waechter konnte nicht laufen (rc=%s)" % (name, rc))
            else:
                print("  ZAHN %-56s 0 FAIL – beisst NICHT" % name)
    finally:
        for d, inhalt in sicherung.items():
            (ROOT / d).write_bytes(inhalt)

    nachher = {d: md5(d) for d in DATEIEN}
    if nachher != vorher:
        print("\nABBRUCH: Dateien nach der Probe nicht byte-gleich: %s"
              % [d for d in DATEIEN if nachher[d] != vorher[d]])
        return 2
    print("\n%d/%d Proben beissen (Dateien byte-gleich wiederhergestellt)"
          % (beissen, len(PROBEN)))
    return 0 if beissen == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
