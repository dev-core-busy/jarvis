#!/usr/bin/env python3
"""LIVE auf DEV: was liefert ein FEHLGESCHLAGENER Mount wirklich – und wird
daraus eine Meldung, aus der ein Administrator etwas ableiten kann?

Geprueft wird mit ECHTEN mount-Aufrufen ueber den echten Root-Broker; die
Deutung laeuft danach ueber die ECHTE Funktion aus main.py (per ast
geschnitten, damit fastapi nicht importiert werden muss).
"""
import ast, re, sys, time
sys.path.insert(0, "/opt/jarvis")
from backend import broker_client   # noqa: E402

OK = FAIL = 0
def check(t, b, d=""):
    global OK, FAIL
    if b: OK += 1; print(f"  \033[32m✓\033[0m {t}")
    else: FAIL += 1; print(f"  \033[31m✗\033[0m {t}" + (f"  → {d}" if d else ""))

quelle = open("/opt/jarvis/backend/main.py").read()
code = ""
for k in ast.parse(quelle).body:
    if isinstance(k, ast.FunctionDef) and k.name == "_mount_fehler_deuten":
        code = ast.get_source_segment(quelle, k)
ns = {"re": re}   # die Funktion benutzt re – sonst NameError im Schnitt
exec(compile(code, "<schnitt>", "exec"), ns)
deute = ns["_mount_fehler_deuten"]
print(f"Broker-Modus: {broker_client.mode()}")

faelle = [
    ("SMB auf einen Host, den es nicht gibt", "smb", "//192.0.2.77/freigabe", "/mnt/kb_probe1"),
    ("SMB mit falscher Schreibweise",         "smb", "kein-pfad",             "/mnt/kb_probe2"),
    ("NFS auf einen toten Host",              "nfs", "192.0.2.77:/export",    "/mnt/kb_probe3"),
]
for name, typ, quelle_s, mp in faelle:
    t0 = time.time()
    res = broker_client.call_sync("mount_share", {
        "type": typ, "source": quelle_s, "mountpoint": mp,
        "username": "", "password": ""}, user="livetest", timeout=60)
    d = time.time() - t0
    print(f"\n  ── {name} ({d:.1f}s)")
    print(f"     roh   : {str(res.get('stderr') or res.get('error') or '')[:150]!r}")
    text = deute(res, typ, quelle_s)
    print(f"     gedeut: {text[:260]}")
    check(f"{name}: der Mount scheitert (Ausgangslage)", not res.get("ok"), str(res)[:120])
    check(f"{name}: die Meldung ist nicht leer", len(text.strip()) > 20, repr(text))
    check(f"{name}: sie nennt einen konkreten naechsten Schritt",
          any(w in text.lower() for w in ("erreichbar", "kennwort", "freigabenamen",
                                          "schreibweise", "apt install", "journalctl",
                                          "root-freigaben", "server:/export", "nfs-common")), text[:160])

print(f"\nErgebnis: {OK}/{OK+FAIL}")
sys.exit(1 if FAIL else 0)
