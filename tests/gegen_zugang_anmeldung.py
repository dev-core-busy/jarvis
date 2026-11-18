#!/usr/bin/env python3
"""Gegenprobe zu test_zugang_sitzung.py und test_zugang_anmeldung_ui.js.

Jede Probe sabotiert EINE Zusage in einer KOPIE (Wegwerf-Verzeichnis) und
zaehlt die FAILs des zugehoerigen Waechters. Die echten Dateien werden nie
angefasst – deshalb ist kein Wiederherstellen noetig und ein abgebrochener
Lauf hinterlaesst nichts im Arbeitsbaum.

Vorab: gruener Basislauf beider Waechter (ohne gruene Basis ist keine
Gegenprobe deutbar). Jede Probe prueft, dass ihr Anker GENAU EINMAL trifft.

Exit 0 = alle Proben beissen, 1 = mindestens eine stumm, 2 = konnte nicht laufen.
    python3 tests/gegen_zugang_anmeldung.py
"""

# Schreibschutz (2026-11-18): dieser Harness ueberschreibt keine fremde Arbeit –
# Regeln und Vorfall in tests/lib/schreibschutz.py.
import sys as _sys, pathlib as _pathlib  # noqa: E401
_sys.path.insert(0, str(_pathlib.Path(__file__).resolve().parent / "lib"))
import schreibschutz  # noqa: E402
schreibschutz.aktivieren(__file__)

import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY_TEST = ROOT / "tests" / "test_zugang_sitzung.py"
JS_TEST = ROOT / "tests" / "test_zugang_anmeldung_ui.js"

# (Name, Datei relativ zu ROOT, alt, neu)
PROBEN = [
    # ── Frontend: zweiter Schritt ──
    ("Geheimfeld ohne autocomplete=off", "frontend/js/zugang_anmeldung.js",
     "        g.autocomplete = 'off';\n", ""),
    ("leere Felder werden nicht ausgelassen", "frontend/js/zugang_anmeldung.js",
     "if (!geheim) { statusSetzen(r.z, ''); continue; }", "if (false) { continue; }"),
    ("unveraenderter Benutzer wird immer gesendet", "frontend/js/zugang_anmeldung.js",
     "benutzer !== (eintrag.benutzer || '')", "true"),
    ("SAP/VEMAS ohne Verbindungstest", "frontend/js/zugang_anmeldung.js",
     "var t = await rufe(token, sys.test, 'GET');", "var t = { ok: true };"),
    ("Fehler beendet den Schritt trotzdem", "frontend/js/zugang_anmeldung.js",
     "'fehler');\n                    return;\n", "'fehler');\n"),
    ("Geheimnis bleibt im Feld", "frontend/js/zugang_anmeldung.js",
     "                    if (gEl) gEl.value = '';\n", ""),
    ("Netzfehler blockiert die Anmeldung", "frontend/js/zugang_anmeldung.js",
     "} catch (e) { eintraege = []; }", "} catch (e) { throw e; }"),
    ("kein Grundzustand danach", "frontend/js/zugang_anmeldung.js",
     "        box.hidden = true;\n        if (form) form.hidden = false;\n", ""),
    ("app.js wartet nicht auf den Schritt", "frontend/js/app.js",
     "try { await window.ZugangAnmeldung.schritt(token); } catch (e) { /* weiter */ }", ""),
    # ── Frontend: Bereichsabschnitt ──
    ("Abschnitt auch ohne Sitzungsbetrieb", "frontend/js/zugang_sitzung.js",
     "var an = !!(a && a.sitzungs_modus);", "var an = true;"),
    ("Abmelden mit falscher Methode", "frontend/js/zugang_sitzung.js",
     "ruf('DELETE', null,", "ruf('POST', null,"),
    ("Tokenfeld wird nicht geleert", "frontend/js/zugang_sitzung.js",
     "                var t = $('token'); if (t) t.value = '';\n", ""),
    # ── Backend ──
    ("Jira ignoriert die Sitzung", "backend/jira_accounts.py",
     'token = _SITZUNG.token(un) if (person and basis) else ""', 'token = ""'),
    ("Confluence merkt ungeprueften Token", "backend/confluence_accounts.py",
     "    name, konto = _token_pruefen(basis, tok)\n", '    name, konto = "", ""\n'),
    ("info verraet den Token", "backend/sitzungs_token.py",
     'return {"angemeldet": True, "sitzung_bis"', 'return {"t": s.get("token"), "angemeldet": True, "sitzung_bis"'),
    ("Jira: Kanal-Kennung wird persoenlich", "backend/jira_accounts.py",
     '    person = bool(un) and ":" not in un\n    token = ""\n', '    person = bool(un)\n    token = ""\n'),
    ("Jarvis-Abmeldung beendet Jira nicht", "backend/main.py",
     "        _jiacc.sitzung_beenden(user)\n", "        pass\n"),
    ("Confluence-Sitzung auch bei erlaubten Zugaengen", "backend/confluence_accounts.py",
     "    if persoenlich_erlaubt():\n        raise ConfluenceKontoFehler(\n            \"Persoenliche Zugaenge sind erlaubt",
     "    if False:\n        raise ConfluenceKontoFehler(\n            \"Persoenliche Zugaenge sind erlaubt"),
    # ── Anmeldeschritt fuer jeden Benutzer (seit 2026-11-16) ──
    ("Freigabeliste kehrt zurueck", "backend/main.py",
     '    if not (user or "").strip() or ":" in user:\n        return out\n    from backend import',
     '    if not (user or "").strip() or ":" in user:\n        return out\n'
     '    if user != "anna.beispiel":\n        return out\n    from backend import'),
    ("Kanal-Kennung bekommt den Schritt", "backend/main.py",
     '    if not (user or "").strip() or ":" in user:\n        return out\n    from backend import',
     '    if not (user or "").strip():\n        return out\n    from backend import'),
    ("laufende Sitzung wird erneut angeboten", "backend/main.py",
     '            if m.zugang_info(user).get("angemeldet"):\n                continue\n',
     '            if False:\n                continue\n'),
    ("erlaubte persoenliche Zugaenge werden angeboten", "backend/main.py",
     "            if not m.sitzungs_modus() or not m.basis_url():\n",
     "            if not m.basis_url():\n"),
    # Nicht ueber das Entfernen von ``if not a.get("feld")``: ohne die Zeile
    # wirft ``a["feld"]`` einen KeyError, das try je System laesst SAP trotzdem
    # weg – die Sabotage waere wirkungslos, kein Waechter-Mangel.
    ("SAP/VEMAS ohne Angebot trotzdem gelistet", "backend/main.py",
     "            a = m.anmeldung_anbieten(user) or {}\n",
     '            a = m.anmeldung_anbieten(user) or {"feld": "password"}\n'),
]


def fails(ausgabe: str) -> int | None:
    m = re.search(r"ERGEBNIS: (\d+) OK, (\d+) FAIL", ausgabe)
    return int(m.group(2)) if m else None


def lauf(art: str, kopie: Path) -> tuple[int, str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    if art == "py":
        env["ZS_ROOT"] = str(kopie)
        cmd = [sys.executable, str(PY_TEST)]
    else:
        env["ZA_JS"] = str(kopie / "frontend/js/zugang_anmeldung.js")
        env["ZS_JS"] = str(kopie / "frontend/js/zugang_sitzung.js")
        env["ZA_APP"] = str(kopie / "frontend/js/app.js")
        cmd = ["node", str(JS_TEST)]
    p = subprocess.run(cmd, capture_output=True, text=True, env=env, timeout=300, cwd=str(ROOT))
    return p.returncode, p.stdout + p.stderr


def kopie_anlegen() -> Path:
    d = Path(tempfile.mkdtemp(prefix="gegen-zugang-"))
    shutil.copytree(ROOT / "backend", d / "backend",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (d / "frontend/js").mkdir(parents=True)
    for n in ("zugang_anmeldung.js", "zugang_sitzung.js", "app.js"):
        shutil.copy2(ROOT / "frontend/js" / n, d / "frontend/js" / n)
    return d


def main() -> int:
    basis = kopie_anlegen()
    try:
        for art in ("py", "js"):
            rc, out = lauf(art, basis)
            if rc != 0 or fails(out) != 0:
                print(f"ABBRUCH: Basislauf {art} nicht gruen (rc={rc}, FAIL={fails(out)})")
                print(out[-1500:])
                return 2
        print("Basislauf beider Waechter gruen.\n")
    finally:
        shutil.rmtree(basis, ignore_errors=True)

    stumm = 0
    for name, datei, alt, neu in PROBEN:
        k = kopie_anlegen()
        try:
            ziel = k / datei
            text = ziel.read_text(encoding="utf-8")
            if text.count(alt) != 1:
                print(f"ABBRUCH: Anker trifft {text.count(alt)}x – {name}")
                return 2
            ziel.write_text(text.replace(alt, neu), encoding="utf-8")
            art = "py" if datei.startswith("backend/") else "js"
            rc, out = lauf(art, k)
            n = fails(out)
            if n is None:
                print(f"  STUMM? {name}: keine Bilanzzeile (rc={rc}) – zaehlt nicht als Biss")
                stumm += 1
            elif n > 0:
                print(f"  BEISST {name}: {n} FAIL")
            else:
                print(f"  STUMM  {name}")
                stumm += 1
        finally:
            shutil.rmtree(k, ignore_errors=True)
    print(f"\n{len(PROBEN) - stumm} von {len(PROBEN)} Proben beissen.")
    return 1 if stumm else 0


if __name__ == "__main__":
    sys.exit(main())
