#!/usr/bin/env python3
"""Waechter: delegiere.py schickt den Schluessel nur ueber eine gepruefte Verbindung.

Befund 2026-11-27: der Delegations-Client setzte CERT_NONE und liess http://
zu – wer im Netzpfad sass, las den Schluessel aus ``X-Jarvis-Key`` mit und
konnte Code-Auftraege im Namen des Benutzers starten.

Gemessen an der WIRKUNG gegen einen echten lokalen HTTPS-Server (Zertifikate
per openssl erzeugt), Wegwerf-HOME fuer Schluessel/Adresse/Fingerabdruck:
  * Positivkontrolle: bestaetigter Fingerabdruck → Anfrage kommt an, mit Schluessel
  * selbst ausgestellt, NICHT bestaetigt → Abbruch (Exit 3), Server sah KEINE Anfrage
  * falscher Fingerabdruck → Abbruch (Exit 3), keine Anfrage
  * von einer vertrauten CA ausgestellt (SSL_CERT_FILE) → geht OHNE Fingerabdruck
  * CA-Zertifikat, aber falscher Name → kein Rueckfall ohne Fingerabdruck
  * http:// → Abbruch (Exit 2), keine Verbindung
  * ``vertrauen --fingerabdruck`` richtig → Datei 0600 mit dem Abdruck; falsch → nichts
Regel (AST): ``_ungeprueft`` (CERT_NONE) wird nur in ``verbindung`` und
``cmd_vertrauen`` gerufen, und beide vergleichen danach per ``compare_digest``.

    python3 tests/test_delegiere_tls.py   Exit 0 gruen, 1 rot, 2 konnte nicht laufen
"""
import ast
import http.server
import importlib.util
import json
import os
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLIENT = ROOT / "deploy" / "claude_subagent" / "delegiere.py"

_ok = 0
_fail = 0


def check(cond, label):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  OK   {label}")
    else:
        _fail += 1
        print(f"  FAIL {label}")


if not shutil.which("openssl"):
    print("ABBRUCH: openssl fehlt – ohne Zertifikate kann nichts gemessen werden")
    sys.exit(2)

spec = importlib.util.spec_from_file_location("_delegiere_tls", CLIENT)
dlg = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dlg)

ARBEIT = Path(tempfile.mkdtemp(prefix="delegiere_tls_"))


def _ossl(*args):
    r = subprocess.run(["openssl", *args], cwd=ARBEIT, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"ABBRUCH: openssl {' '.join(args[:2])}: {r.stderr.strip()[:300]}")
        sys.exit(2)


# Selbst ausgestellt fuer 127.0.0.1
_ossl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
      "-subj", "/CN=selbst", "-addext", "subjectAltName=IP:127.0.0.1",
      "-keyout", "selbst.key", "-out", "selbst.crt")
# Eigene CA + Blatt fuer 127.0.0.1 und ein Blatt fuer einen FREMDEN Namen
_ossl("req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "2",
      "-subj", "/CN=Test-CA", "-addext", "basicConstraints=critical,CA:TRUE",
      "-addext", "keyUsage=critical,keyCertSign,cRLSign",
      "-keyout", "ca.key", "-out", "ca.crt")
for name, san in (("blatt", "IP:127.0.0.1"), ("fremd", "DNS:anderer.beispiel.de")):
    _ossl("req", "-newkey", "rsa:2048", "-nodes", "-subj", f"/CN={name}",
          "-keyout", f"{name}.key", "-out", f"{name}.csr")
    # authorityKeyIdentifier (Blatt) und keyUsage (CA): Python >= 3.13 prueft
    # mit VERIFY_X509_STRICT – ohne sie scheiterte die Kette am Messaufbau
    # ("CA cert does not include key usage extension"), nicht am Client.
    (ARBEIT / f"{name}.ext").write_text(
        f"subjectAltName={san}\nauthorityKeyIdentifier=keyid,issuer\n"
        f"basicConstraints=CA:FALSE\n")
    _ossl("x509", "-req", "-in", f"{name}.csr", "-CA", "ca.crt", "-CAkey", "ca.key",
          "-CAcreateserial", "-days", "2", "-out", f"{name}.crt", "-extfile", f"{name}.ext")


ANFRAGEN = []


class _Handler(http.server.BaseHTTPRequestHandler):
    def _antwort(self):
        ANFRAGEN.append({"pfad": self.path, "key": self.headers.get("X-Jarvis-Key")})
        laenge = int(self.headers.get("Content-Length") or 0)
        if laenge:
            self.rfile.read(laenge)
        b = json.dumps({"ok": True, "pfad": self.path}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    do_GET = _antwort
    do_POST = _antwort

    def log_message(self, *a):
        pass


def _server(name):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(ARBEIT / f"{name}.crt", ARBEIT / f"{name}.key")
    srv.socket = ctx.wrap_socket(srv.socket, server_side=True)
    # Abgebrochene Handshakes (genau die Faelle, die gemessen werden) nicht als
    # Traceback auf stderr – sie sind hier das erwartete Ergebnis.
    srv.handle_error = lambda *a: None
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def _fp(name):
    der = ssl.PEM_cert_to_DER_cert((ARBEIT / f"{name}.crt").read_text())
    return dlg.fingerabdruck(der)


def _lauf(url, pin=None, ca=None, aufruf=None):
    """(ergebnis, exitcode, anfragen) mit Wegwerf-HOME."""
    with tempfile.TemporaryDirectory() as home:
        Path(home, ".probe-csa-key").write_text("PROBE-CSA-1.geheim")
        Path(home, ".probe-csa-url").write_text(url)
        if pin is not None:
            Path(home, ".probe-csa-cert").write_text(pin)
        alt = {k: os.environ.get(k) for k in ("HOME", "SSL_CERT_FILE", "SSL_CERT_DIR")}
        fremd = {k: v for k, v in os.environ.items() if "_CSA_" in k.upper()}
        for k in fremd:
            del os.environ[k]
        os.environ["HOME"] = home
        # Ohne eigene CA: ein LEERER Speicher, damit kein Systemanker zufaellig greift
        os.environ["SSL_CERT_FILE"] = str(ca or (ARBEIT / "leer.pem"))
        os.environ["SSL_CERT_DIR"] = str(ARBEIT / "leerdir")
        vorher = len(ANFRAGEN)
        try:
            erg = (aufruf or (lambda: dlg.ruf("/api/claude/jobs")))()
            code = 0
        except SystemExit as e:
            erg, code = None, e.code
        finally:
            for k, v in alt.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v
            os.environ.update(fremd)
        datei = Path(home, ".probe-csa-cert")
        gespeichert = (datei.read_text().strip(), oct(datei.stat().st_mode & 0o777)) \
            if datei.exists() else None
        return erg, code, ANFRAGEN[vorher:], gespeichert


(ARBEIT / "leer.pem").write_text("")
(ARBEIT / "leerdir").mkdir()

selbst = _server("selbst")
blatt = _server("blatt")
fremd = _server("fremd")
U_SELBST = f"https://127.0.0.1:{selbst.server_address[1]}"
U_BLATT = f"https://127.0.0.1:{blatt.server_address[1]}"
U_FREMD = f"https://127.0.0.1:{fremd.server_address[1]}"

print("Wirkung gegen echte HTTPS-Server")
erg, code, anf, _ = _lauf(U_SELBST, pin=_fp("selbst"))
if not (code == 0 and erg and erg.get("ok") and anf):
    print(f"ABBRUCH: Positivkontrolle – bestaetigter Abdruck kommt nicht durch "
          f"(code {code}, {erg}, {anf})")
    sys.exit(2)
check(anf[0]["key"] == "PROBE-CSA-1.geheim", "Positivkontrolle: Anfrage mit Schluessel kommt an")

erg, code, anf, _ = _lauf(U_SELBST)
check(code == 3 and not anf, f"unbestaetigt → Exit 3, keine Anfrage (code {code}, {len(anf)} Anfr.)")

falsch = _fp("blatt")
erg, code, anf, _ = _lauf(U_SELBST, pin=falsch)
check(code == 3 and not anf, f"falscher Abdruck → Exit 3, keine Anfrage (code {code}, {len(anf)} Anfr.)")

erg, code, anf, _ = _lauf(U_SELBST, pin=_fp("selbst").replace(":", "").lower())
check(code == 0 and anf, "Abdruck ohne Doppelpunkte/klein geschrieben wird erkannt")

erg, code, anf, _ = _lauf(U_BLATT, ca=ARBEIT / "ca.crt")
check(code == 0 and anf and anf[0]["key"], f"CA-vertraut → ohne Abdruck durch (code {code})")

erg, code, anf, _ = _lauf(U_FREMD, ca=ARBEIT / "ca.crt")
check(code == 3 and not anf, f"CA-Zertifikat fuer fremden Namen → Exit 3, keine Anfrage (code {code})")

erg, code, anf, _ = _lauf(U_BLATT)
check(code == 3 and not anf, "CA nicht im Speicher → wie selbst ausgestellt (Exit 3)")

erg, code, anf, _ = _lauf(U_SELBST.replace("https://", "http://"), pin=_fp("selbst"))
check(code == 2 and not anf, f"http:// → Exit 2, keine Anfrage (code {code})")

erg, code, anf, _ = _lauf(U_SELBST.replace("https://", ""), pin=_fp("selbst"))
check(code == 0 and anf, "Adresse ohne Schema → https://")


class _A:
    def __init__(self, fp):
        self.fingerabdruck = fp


print("Bestaetigen (vertrauen)")
erg, code, anf, gesp = _lauf(U_SELBST, aufruf=lambda: dlg.cmd_vertrauen(_A(_fp("selbst"))))
check(code == 0 and gesp and gesp[0] == _fp("selbst") and gesp[1] == "0o600",
      f"richtiger Abdruck → hinterlegt, 0600 ({gesp})")
check(not anf, "vertrauen sendet keinen Schluessel")
erg, code, anf, gesp = _lauf(U_SELBST, aufruf=lambda: dlg.cmd_vertrauen(_A(_fp("blatt"))))
check(code == 3 and gesp is None, f"falscher Abdruck → nichts hinterlegt (code {code})")

print("Regel am Syntaxbaum")
baum = ast.parse(CLIENT.read_text(encoding="utf-8"))
rufer, vergleicht = set(), set()
for fn in ast.walk(baum):
    if isinstance(fn, ast.FunctionDef):
        for k in ast.walk(fn):
            if isinstance(k, ast.Call) and isinstance(k.func, ast.Name) and k.func.id == "_ungeprueft":
                rufer.add(fn.name)
            if (isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute)
                    and k.func.attr == "compare_digest"):
                vergleicht.add(fn.name)
check(rufer == {"verbindung", "cmd_vertrauen"}, f"CERT_NONE nur in verbindung/cmd_vertrauen ({rufer})")
check(rufer <= vergleicht, "beide vergleichen den Abdruck per compare_digest")
cert_none = [k.lineno for k in ast.walk(baum)
             if isinstance(k, ast.Attribute) and k.attr == "CERT_NONE"]
check(len(cert_none) == 1, f"CERT_NONE steht genau einmal (in _ungeprueft) ({cert_none})")

for s in (selbst, blatt, fremd):
    s.shutdown()
shutil.rmtree(ARBEIT, ignore_errors=True)
print(f"\nBilanz: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
