#!/usr/bin/env python3
"""Waechter: selbst erzeugte Serverzertifikate mit RSA >= 3072 (BSI TR-02102-1).

Rest aus dem BSI-Abgleich (H6, gemessen 2026-10-12): das DEV-Zertifikat trug
RSA 2048, weil ``security.ensure_certificates`` mit ``rsa:2048`` erzeugte.
TR-02102-1 verlangt mindestens 3000 Bit.

Gemessen wird an der WIRKUNG: ``ensure_certificates`` erzeugt in einem leeren
Temp-Ordner ein echtes Zertifikat (Adress-/Namenssammlung gestubbt – die
fragt sonst externe Dienste ab), danach liest ``openssl`` die Schluessellaenge.
Positivkontrolle: Zertifikat und Schluessel muessen entstanden sein und die
Laenge muss lesbar sein, sonst Exit 2.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

MIN_BITS = 3072
_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s%s" % (label, (" – %s" % detail) if detail else ""))


if not shutil.which("openssl"):
    print("ABBRUCH (Exit 2): openssl fehlt")
    sys.exit(2)

from backend import security  # noqa: E402  (importiert backend.config nicht)

tmp = Path(tempfile.mkdtemp(prefix="zert_schluessel_"))
try:
    security.CERTS_DIR = tmp
    security.CERT_FILE = tmp / "server.crt"
    security.KEY_FILE = tmp / "server.key"
    security.CERT_DER_FILE = tmp / "jarvis.cer"
    security._collect_server_ips = lambda: ["192.0.2.10"]
    security._collect_server_names = lambda: ["jarvis.beispiel.de"]
    security.ensure_certificates()

    if not (security.CERT_FILE.exists() and security.KEY_FILE.exists()):
        print("ABBRUCH (Exit 2): ensure_certificates hat kein Zertifikat erzeugt")
        sys.exit(2)
    r = subprocess.run(["openssl", "x509", "-in", str(security.CERT_FILE), "-noout", "-text"],
                       capture_output=True, text=True)
    treffer = re.search(r"Public-Key:\s*\((\d+)\s*bit\)", r.stdout)
    if not treffer:
        print("ABBRUCH (Exit 2): Schluessellaenge nicht lesbar: %r" % r.stdout[:300])
        sys.exit(2)
    bits = int(treffer.group(1))
    check(bits >= MIN_BITS, "Zertifikat mit RSA >= %d Bit" % MIN_BITS, "%d Bit" % bits)
    check("rsaEncryption" in r.stdout, "Schluesselart RSA (Messung passt zur Pruefung)")
    check(os.path.getsize(security.CERT_DER_FILE) > 0 if security.CERT_DER_FILE.exists() else False,
          "DER-Fassung fuer Windows erzeugt")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
