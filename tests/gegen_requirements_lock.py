#!/usr/bin/env python3
"""Gegenprobe: beisst tests/test_requirements_lock.py ueberhaupt?

Legt dem Waechter sabotierte KOPIEN von requirements.lock / requirements.txt
vor (als Argumente, in einem Wegwerf-Verzeichnis) – die echten Dateien werden
nie angefasst.

Erwartung je Probe: 1 = Verstoss erkannt, 2 = Waechter meldet "konnte nicht
laufen" (Lock leer / torch-Hinweis fehlt).

Lauf:  python3 tests/gegen_requirements_lock.py
Exit 0 = alle Proben wie erwartet, 1 = mindestens eine nicht, 2 = konnte nicht laufen
"""
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
WAECHTER = HIER / "test_requirements_lock.py"
LOCK = HIER.parent / "requirements.lock"
REQ = HIER.parent / "requirements.txt"
DF = HIER.parent / "Dockerfile"
WF = HIER.parent / ".github" / "workflows" / "sicherheit.yml"


def ohne_hashes_bei(text: str, paket: str) -> str:
    """Entfernt die Hash-Zeilen genau eines Eintrags (Eintrag bleibt stehen)."""
    zeilen, raus, im = text.splitlines(keepends=True), [], False
    for z in zeilen:
        if re.match(rf"^{re.escape(paket)}==", z):
            im = True
            raus.append(re.sub(r"\s*\\\s*$", "\n", z))
            continue
        if im and z.lstrip().startswith("--hash="):
            continue
        im = False
        raus.append(z)
    return "".join(raus)


def ohne_eintrag(text: str, paket: str) -> str:
    zeilen, raus, im = text.splitlines(keepends=True), [], False
    for z in zeilen:
        if re.match(rf"^{re.escape(paket)}==", z):
            im = True
            continue
        if im and z.startswith(" "):
            continue
        im = False
        raus.append(z)
    return "".join(raus)


def main() -> int:
    if not all(p.is_file() for p in (LOCK, REQ, DF, WF, WAECHTER)):
        print("ABBRUCH: Lock, requirements.txt, Dockerfile, Workflow oder Waechter fehlt")
        return 2
    lock, req = LOCK.read_text(encoding="utf-8"), REQ.read_text(encoding="utf-8")
    df, wf = DF.read_text(encoding="utf-8"), WF.read_text(encoding="utf-8")
    DF_ANKER = "--require-hashes -Ccompile-args=-j2 \\\n        --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.lock\n"
    WF_ANKER = "--require-hashes -Ccompile-args=-j2 \\\n            --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.lock\n"
    if df.count(DF_ANKER) != 1 or wf.count(WF_ANKER) != 1:
        print("ABBRUCH: Anker der Lock-Installation in Dockerfile/Workflow nicht genau einmal gefunden")
        return 2
    m = re.search(r"(?m)^torch==(\S+) ", lock)
    if not m or "starlette>=1.3.1\n" not in req:
        print("ABBRUCH: Anker (torch in der Lock / starlette-Grenze) nicht gefunden")
        return 2
    PROBEN = [
        ("Eintrag ohne Hash (fastapi)", ohne_hashes_bei(lock, "fastapi"), req, df, wf, 1),
        ("Paket aus requirements.txt fehlt in der Lock (ldap3)", ohne_eintrag(lock, "ldap3"), req, df, wf, 1),
        ("Grenze angehoben, Lock nicht neu erzeugt", lock,
         req.replace("starlette>=1.3.1\n", "starlette>=9.0\n"), df, wf, 1),
        ("neue Anforderung ohne Lock-Eintrag", lock, req + "gibtsnicht-paket>=1.0\n", df, wf, 1),
        ("torch in anderer Fassung als der Hinweis", lock.replace(f"torch=={m.group(1)} ", "torch==2.9.0+cpu "),
         req, df, wf, 1),
        ("CUDA-Paket in der Lock", lock + "nvidia-cublas-cu12==12.4.5.8 \\\n    --hash=sha256:" + "d" * 64 + "\n",
         req, df, wf, 1),
        ("Kopf ohne Erzeuger-Hinweis", "# irgendwas\n" + lock, req, df, wf, 1),
        ("leere Lock -> konnte nicht laufen", "# leer\n", req, df, wf, 2),
        ("Dockerfile wieder aus requirements.txt", lock, req,
         df.replace(DF_ANKER, "--extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt\n"), wf, 1),
        ("CI ohne --require-hashes", lock, req, df,
         wf.replace(WF_ANKER, "-Ccompile-args=-j2 \\\n            --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.lock\n"), 1),
        ("CI installiert zusaetzlich aus requirements.txt", lock, req, df,
         wf.replace(WF_ANKER, WF_ANKER + "          venv/bin/pip install -q -r requirements.txt\n"), 1),
        ("torch-Hinweis fehlt -> konnte nicht laufen", lock, re.sub(r'"torch==[^"]+"', '"torch"', req), df, wf, 2),
    ]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    with tempfile.TemporaryDirectory() as tmp:
        lp, rp = Path(tmp) / "requirements.lock", Path(tmp) / "requirements.txt"
        dp, wp = Path(tmp) / "Dockerfile", Path(tmp) / "sicherheit.yml"
        for pf, inhalt in ((lp, lock), (rp, req), (dp, df), (wp, wf)):
            pf.write_text(inhalt, encoding="utf-8")
        rc = subprocess.run([sys.executable, str(WAECHTER), str(lp), str(rp), str(dp), str(wp)],
                            capture_output=True, text=True, env=env).returncode
        if rc != 0:
            print(f"ABBRUCH: Basislauf nicht gruen (rc={rc})")
            return 2
        print("Basislauf gruen.\n")
        treffer = 0
        for name, l_text, r_text, d_text, w_text, erwartet in PROBEN:
            for pf, inhalt in ((lp, l_text), (rp, r_text), (dp, d_text), (wp, w_text)):
                pf.write_text(inhalt, encoding="utf-8")
            rc = subprocess.run([sys.executable, str(WAECHTER), str(lp), str(rp), str(dp), str(wp)],
                                capture_output=True, text=True, env=env).returncode
            gut = rc == erwartet
            treffer += gut
            print(f"  {'OK  ' if gut else 'ZAHN'} {name:<60} Exit {rc} (erwartet {erwartet})")
    print(f"\n{treffer}/{len(PROBEN)} Proben wie erwartet")
    return 0 if treffer == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
