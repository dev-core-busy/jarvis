"""Gegenprobe zu test_docker_kennwort.py: beisst jede Pruefung einzeln?

Arbeitet ausschliesslich auf KOPIEN (JARVIS_TEST_STANDARD_ZUGANG /
JARVIS_TEST_MAIN) – backend/main.py traegt oft fremde, uncommittete Arbeit,
ein abgebrochener Lauf darf sie nicht beruehren.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

W = Path(__file__).resolve().parent.parent
TEST = W / "tests" / "test_docker_kennwort.py"
QUELLEN = {"sz": W / "backend" / "standard_zugang.py", "main": W / "backend" / "main.py"}

PROBEN = [
    ("kein Salz mehr", "sz",
     "    salz = secrets.token_bytes(16)\n", "    salz = bytes(16)\n"),
    ("scrypt-Vergleich nimmt jedes Kennwort", "sz",
     "        return hmac.compare_digest(ist, soll), False\n", "        return True, False\n"),
    ("Altwert wird nicht als veraltet gemeldet", "sz",
     "        return passt, passt\n", "        return passt, False\n"),
    ("Obergrenze N fehlt", "sz",
     "        if not (2 <= n <= _SCRYPT_N_MAX and n & (n - 1) == 0\n",
     "        if not (2 <= n and n & (n - 1) == 0\n"),
    ("Kosten zu niedrig (N=2^10)", "sz", "_SCRYPT_N = 2 ** 15\n", "_SCRYPT_N = 2 ** 10\n"),
    ("unbekanntes Format gilt als passend", "sz",
     "        return passt, passt\n    return False, False\n",
     "        return passt, passt\n    return True, False\n"),
    ("Anmeldung wieder mit eigenem sha256", "main",
     "                local_ok, veraltet = _standard_zugang.kennwort_pruefen(password, docker_pw)\n",
     "                local_ok = hmac.compare_digest(hashlib.sha256(password.encode()).hexdigest(), docker_pw)\n"
     "                veraltet = False\n"),
    ("Altwert wird nicht gespeichert", "main",
     "                    _save_auth_state(state)\n                    print(f\"[AUTH] Docker-Kennwort fuer '{username}' auf scrypt",
     "                    pass\n                    print(f\"[AUTH] Docker-Kennwort fuer '{username}' auf scrypt"),
    ("Umschreiben auch bei falschem Kennwort", "main",
     "                if local_ok and veraltet:\n", "                if veraltet:\n"),
    ("Kennwortwechsel speichert wieder sha256", "main",
     '        state["docker_password"][username] = _standard_zugang.kennwort_hash(new_password)\n',
     '        state["docker_password"][username] = hashlib.sha256(new_password.encode()).hexdigest()\n'),
]


def lauf(pfade):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1",
               JARVIS_TEST_STANDARD_ZUGANG=str(pfade["sz"]), JARVIS_TEST_MAIN=str(pfade["main"]))
    r = subprocess.run([sys.executable, str(TEST)], capture_output=True, text=True, timeout=300, env=env)
    m = re.search(r"(\d+) OK, (\d+) FAIL", r.stdout)
    return r.returncode, bool(m), int(m.group(2)) if m else -1


with tempfile.TemporaryDirectory() as d:
    pfade = {k: Path(d) / f"{k}.py" for k in QUELLEN}
    ORIG = {k: q.read_text(encoding="utf-8") for k, q in QUELLEN.items()}

    def herstellen():
        for k, t in ORIG.items():
            pfade[k].write_text(t, encoding="utf-8")

    herstellen()
    rc, b, f = lauf(pfade)
    if rc or not b or f:
        print(f"ABBRUCH: Basis nicht gruen (rc={rc} bilanz={b} fails={f})"); sys.exit(2)
    print("Basis gruen.\n")
    gut = 0
    for name, ziel, a, n in PROBEN:
        herstellen()
        if ORIG[ziel].count(a) != 1:
            print(f"  ⚠ VERFEHLT  {name} (Anker {ORIG[ziel].count(a)}x)"); continue
        pfade[ziel].write_text(ORIG[ziel].replace(a, n, 1), encoding="utf-8")
        rc, b, f = lauf(pfade)
        ok = rc == 1 and b and f > 0
        gut += ok
        print(f"  {'OK     ' if ok else 'ZAHNLOS'}  {name}: {f} FAIL (rc={rc})" + ("" if b else " OHNE BILANZ"))

# Die Originale wurden nie beschrieben – trotzdem belegen statt annehmen
for k, q in QUELLEN.items():
    if q.read_text(encoding="utf-8") != ORIG[k]:
        print(f"ABBRUCH: {q} wurde veraendert!"); sys.exit(2)
print(f"\n{gut} von {len(PROBEN)} beissen einzeln.")
sys.exit(0 if gut == len(PROBEN) else 1)
