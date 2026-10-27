#!/usr/bin/env python3
"""Gegenprobe zu tests/test_llm_tls.py: beisst der Waechter?

Jede Probe dreht EINE Zusage zurueck und erwartet Exit 1 (Befund) mit
mindestens einem FAIL. Exit 2 einer Probe zaehlt NICHT als Biss.
Vorher ein gruener Basislauf (sonst ist keine Probe deutbar), Sicherung auf
Platte, Rueckstand eines abgebrochenen Laufs wird beim Start zurueckgenommen,
nach jeder Probe Byte-Gleichheit per md5. Ohne Bytecode
(PYTHONDONTWRITEBYTECODE=1), sonst laedt ein spaeterer Lauf die Sabotage.

Exit 0 = alle Proben beissen, 1 = mindestens eine stumm, 2 = konnte nicht laufen.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WAECHTER = ROOT / "tests" / "test_llm_tls.py"
SICHERUNG = Path.home() / ".gegen_llm_tls_sicherung"
MARKE = SICHERUNG / "LAUF"

LLM_TLS = "backend/llm_tls.py"
LLM = "backend/llm.py"
CONFIG = "backend/config.py"

PROBEN = [
    ("Anker nur nach Host, Port egal", LLM_TLS,
     "t = self._gebunden.get(((url.host or \"\").lower(), url.port or 443))",
     "t = next((v for (h, _p), v in self._gebunden.items() "
     "if h == (url.host or \"\").lower()), None)"),
    ("Fingerabdruck wird nicht verglichen", LLM_TLS,
     "if not hmac.compare_digest(erg[\"fingerprint\"], fp):",
     "if False:"),
    ("client_args liefert nie einen Transport", LLM_TLS,
     "    if not a:\n        return {}\n    return {\"transport\": AnkerTransport(a, **kw)}",
     "    return {}"),
    ("SHA-1 wird nicht erkannt", LLM_TLS,
     "    if len(s) == 40:\n",
     "    if False:\n"),
    ("gemeinsamer Client ignoriert Ankerwechsel", LLM,
     "if _shared_client is None or _shared_client.is_closed or stand != _shared_anker:",
     "if _shared_client is None or _shared_client.is_closed:"),
    ("update_profile nimmt 'cert' an", CONFIG,
     "\"prompt_tool_calling\", \"allowed_users\", \"allowed_group\"]:",
     "\"prompt_tool_calling\", \"allowed_users\", \"allowed_group\", \"cert\"]:"),
]
DATEIEN = sorted({p[1] for p in PROBEN})


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def zurueck() -> None:
    for rel in DATEIEN:
        s = SICHERUNG / rel.replace("/", "__")
        if s.exists():
            shutil.copy2(s, ROOT / rel)


def lauf() -> tuple[int, int, str]:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, str(WAECHTER)], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=300)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    fails = int(m.group(2)) if m else -1
    return r.returncode, fails, r.stdout


def main() -> int:
    if {p[1] for p in PROBEN} - set(DATEIEN):
        print("ABBRUCH: Probe faesst eine nicht gesicherte Datei an")
        return 2
    if MARKE.exists():
        print("Rueckstand eines abgebrochenen Laufs – nehme die Sicherung zurueck")
        zurueck()
        MARKE.unlink()

    code, fails, aus = lauf()
    if code != 0 or fails != 0:
        print(aus[-1500:])
        print(f"ABBRUCH: Basislauf nicht gruen (Exit {code}, {fails} FAIL)")
        return 2
    print("Basislauf gruen")

    SICHERUNG.mkdir(mode=0o700, exist_ok=True)
    vorher = {}
    for rel in DATEIEN:
        shutil.copy2(ROOT / rel, SICHERUNG / rel.replace("/", "__"))
        vorher[rel] = md5(ROOT / rel)
    MARKE.write_text("laeuft")

    stumm = 0
    try:
        for name, rel, alt, neu in PROBEN:
            pfad = ROOT / rel
            text = pfad.read_text(encoding="utf-8")
            if text.count(alt) < 1:
                print(f"  ABBRUCH  {name}: Anker nicht gefunden")
                return 2
            pfad.write_text(text.replace(alt, neu), encoding="utf-8")
            try:
                code, fails, _ = lauf()
            finally:
                zurueck()
                if md5(pfad) != vorher[rel]:
                    print(f"ABBRUCH: {rel} nach Probe nicht byte-gleich")
                    return 2
            biss = code == 1 and fails > 0
            if not biss:
                stumm += 1
            print(f"  {'BEISST' if biss else 'STUMM '}  {name}  (Exit {code}, {fails} FAIL)")
    finally:
        zurueck()
        if MARKE.exists():
            MARKE.unlink()

    print(f"\nErgebnis: {len(PROBEN) - stumm}/{len(PROBEN)} Proben beissen")
    return 0 if stumm == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
