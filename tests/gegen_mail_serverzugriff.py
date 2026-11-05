#!/usr/bin/env python3
"""Gegenprobe: beissen tests/test_mail_serverzugriff.py und
tests/test_mail_serverzugriff_ui.js? (Outlook-Umbau, Punkt e)

Sabotierte KOPIEN in einem Wegwerf-Verzeichnis (MS_ACCOUNTS / MS_RUNNER /
MS_MAIN / ADDIN_JS / EMAIL_JS) – die echten Dateien werden nie angefasst. Vorher
ein gruener Basislauf; eine Probe "beisst" nur mit Exit 1 UND mindestens einem
FAIL (Exit 2 und Abstuerze zaehlen nicht).

Exit 0 = alle Proben beissen, 1 = mindestens eine nicht, 2 = konnte nicht laufen
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = HIER.parent
WAECHTER = [
    [sys.executable, str(HIER / "test_mail_serverzugriff.py")],
    ["node", str(HIER / "test_mail_serverzugriff_ui.js")],
]
DATEIEN = {
    "konten": (ROOT / "backend" / "mail_accounts.py", "MS_ACCOUNTS"),
    "runner": (ROOT / "backend" / "mail_runner.py", "MS_RUNNER"),
    "main": (ROOT / "backend" / "main.py", "MS_MAIN"),
    "addin": (ROOT / "frontend" / "addin" / "addin.js", "ADDIN_JS"),
    "emailjs": (ROOT / "frontend" / "js" / "email.js", "EMAIL_JS"),
}

# (Name, Datei, alt, neu)
PROBEN = [
    ("konto_fuer ohne Schranke", "konten",
     "    if not server_zugriff(user):\n        raise MailFehler(SERVER_ZUGRIFF_TEXT, \"eingabe\")\n", ""),
    ("leere Auswahl heisst alle", "konten",
     "    return bool(un) and \":\" not in un and un in server_zugriff_liste()",
     "    return bool(un) and \":\" not in un and (not server_zugriff_liste() or un in server_zugriff_liste())"),
    ("Auswahl nicht normalisiert", "konten",
     "        un = norm_user(str(t))\n        if un and \":\" not in un and un not in out:",
     "        un = str(t).strip()\n        if un and un not in out:"),
    ("Automatik laeuft ohne Serverzugriff", "runner",
     "        if not mail_accounts.server_zugriff(regel.get(\"owner\") or \"\"):\n            continue\n", ""),
    ("Vorschlag mit Add-in-Inhalt oeffnet trotzdem das Postfach", "runner",
     "        n = _nachricht_aus_addin(nachricht)\n",
     "        n = _nachricht_aus_addin(nachricht)\n        mail_accounts.konto_fuer(user, trotz_aussetzer=True)\n"),
    ("Add-in-Text unbegrenzt", "runner",
     '                         text=_s("text", VORSCHLAG_MAX))',
     '                         text=_s("text", 10 ** 9))'),
    ("Vorschau reicht den Inhalt nicht durch", "main",
     "            user, msg_id, ordner, hinw, stil_id, nachricht=nachricht,\n",
     "            user, msg_id, ordner, hinw, stil_id,\n"),
    ("reply/form oeffnet das Postfach", "main",
     "    format_ = mail_accounts.format_fuer(user, str((body or {}).get(\"format\") or \"\").strip()[:16])\n",
     "    mail_accounts.konto_fuer(user)\n"
     "    format_ = mail_accounts.format_fuer(user, str((body or {}).get(\"format\") or \"\").strip()[:16])\n"),
    ("Auswahl ohne Berechtigungspruefung", "main",
     "    ohne = [u for u in liste if not _user_may_use_email(u)]\n", "    ohne = []\n"),
    ("Add-in zeigt den Hinweis nie", "addin",
     "                zeichneServerHinweis();\n", ""),
    ("Add-in bietet Regel-Lauf ohne Serverzugriff an", "addin",
     "        if (!serverZugriff()) {\n            teile.push('<div class=\"ad-empty\">' + esc(T('addin.no_server',",
     "        if (false) {\n            teile.push('<div class=\"ad-empty\">' + esc(T('addin.no_server',"),
    ("Auswahl speichert alle statt der angehakten", "emailjs",
     "            if (cb.checked) gew.push(cb.value);\n", "            gew.push(cb.value);\n"),
    ("Auswahl verschweigt fehlende Berechtigung", "emailjs",
     "                    if (!k.berechtigt) zusatz.push(T('mailadm.server_no_right', 'keine E-Mail-Berechtigung mehr'));\n", ""),
]


def lauf(umgebung: dict) -> tuple:
    """Alle Pruefstaende; Rueckgabe (Exit, FAIL-Summe, Ausgabe).

    Exit 2 bei irgendeinem Pruefstand geht vor (konnte nicht messen); eine
    fehlende Bilanzzeile heisst FAIL None – das zaehlt nicht als Biss."""
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", **umgebung)
    codes, summe, aus = [], 0, ""
    for befehl in WAECHTER:
        r = subprocess.run(befehl, cwd=str(ROOT), env=env,
                           capture_output=True, text=True, timeout=300)
        m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
        codes.append(r.returncode)
        aus += r.stdout + r.stderr
        if m is None:
            summe = None
        elif summe is not None:
            summe += int(m.group(2))
    code = 2 if 2 in codes else max(codes)
    return code, summe, aus


def main() -> int:
    nicht_gedeckt = {p[1] for p in PROBEN} - set(DATEIEN)
    if nicht_gedeckt:
        print(f"ABBRUCH: Proben auf unbekannte Dateien: {nicht_gedeckt}")
        return 2
    code, fails, aus = lauf({})
    if code != 0 or fails != 0:
        print(f"ABBRUCH: Basislauf nicht gruen (Exit {code}, FAIL {fails})")
        print(aus[-2000:])
        return 2
    print(f"Basislauf gruen.\n")
    stumm = 0
    with tempfile.TemporaryDirectory(prefix="gegen_sapkachel_") as tmp:
        for i, (name, datei, alt, neu) in enumerate(PROBEN, 1):
            quelle, var = DATEIEN[datei]
            text = quelle.read_text(encoding="utf-8")
            n = text.count(alt)
            if n != 1:
                print(f"  ??  {i:2d} {name} – Anker {n}x gefunden (erwartet 1)")
                stumm += 1
                continue
            ziel = Path(tmp) / f"probe{i}_{quelle.name}"
            ziel.write_text(text.replace(alt, neu), encoding="utf-8")
            code, fails, aus = lauf({var: str(ziel)})
            if code == 1 and fails:
                print(f"  BEISST {i:2d} {name} ({fails} FAIL)")
            else:
                stumm += 1
                print(f"  STUMM  {i:2d} {name} (Exit {code}, FAIL {fails})")
    print(f"\nErgebnis: {len(PROBEN) - stumm}/{len(PROBEN)} Proben beissen")
    return 1 if stumm else 0


if __name__ == "__main__":
    sys.exit(main())
