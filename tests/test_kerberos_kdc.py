#!/usr/bin/env python3
"""Durchstich der Windows-Anmeldung gegen einen ECHTEN MIT-KDC (Wegwerf-Realm).

Was ``test_kerberos_anmeldung.py`` ohne KDC nicht messen kann, steht hier: der
ERFOLGSWEG von ``kerberos_anmeldung.pruefe`` (Name lesen, Mechanismus pruefen,
Speicher freigeben). Ein Fehler dort waere bei ctypes kein FAIL, sondern ein
Speicherzugriffsfehler, der den ganzen Dienst beendet – deshalb laeuft der Weg
hier hundertfach.

Aufbau (alles in einem Wegwerf-Verzeichnis, KDC nur auf 127.0.0.1):
  Realm TEST.LOCAL · Benutzer ``a.b`` · Dienst ``HTTP/server.test.local`` mit
  Keytab · ``kinit`` holt ein Ticket · ``curl --negotiate`` schickt ein echtes
  SPNEGO-Token (wie Windows) an einen HTTP-Server in diesem Prozess, der
  ``pruefe`` aufruft.

Werkzeuge: ``krb5kdc``, ``kdb5_util``, ``kadmin.local``, ``kinit`` (MIT) aus dem
PATH oder aus einem ENTPACKTEN Paketbaum ``KRB5_TESTWURZEL`` (``apt-get download
krb5-kdc krb5-admin-server krb5-user libkdb5-10t64 libkadm5srv-mit12
libkadm5clnt-mit12 libgssrpc4t64 libverto1t64 libverto-libev1t64 libev4t64`` +
``dpkg-deb -x`` – ohne Root, ohne Installation). Dazu ``curl`` mit SPNEGO.
Fehlt etwas: **Exit 2** („konnte nicht laufen", nicht „bestanden").
"""

import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def pruefe(bed, text):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   " + text)
    else:
        _fail += 1
        print("  FAIL " + text)


def abbruch(text):
    print("ABBRUCH: " + text, file=sys.stderr)
    sys.exit(2)


# ── Werkzeuge finden ────────────────────────────────────────────────────────
WURZEL = Path(os.environ["KRB5_TESTWURZEL"]) if os.environ.get("KRB5_TESTWURZEL") else None


def werkzeug(*namen):
    for n in namen:
        if WURZEL:
            for d in ("usr/sbin", "usr/bin"):
                p = WURZEL / d / n
                if p.is_file():
                    return str(p)
        p = shutil.which(n)
        if p:
            return p
    return None


KDC = werkzeug("krb5kdc")
KDB = werkzeug("kdb5_util")
KADM = werkzeug("kadmin.local")
KINIT = werkzeug("kinit.mit", "kinit")
CURL = shutil.which("curl")
if not all((KDC, KDB, KADM, KINIT, CURL)):
    abbruch("MIT-KDC-Werkzeuge oder curl fehlen (krb5kdc=%s kdb5_util=%s kadmin.local=%s "
            "kinit=%s curl=%s) – KRB5_TESTWURZEL setzen, siehe Docstring"
            % (KDC, KDB, KADM, KINIT, CURL))
_cv = subprocess.run([CURL, "-V"], capture_output=True, text=True).stdout
if "SPNEGO" not in _cv:
    abbruch("curl ohne SPNEGO")

from backend import kerberos_anmeldung as K  # noqa: E402

if "backend.config" in sys.modules:
    abbruch("backend.config wurde geladen")


def freier_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


SAND = Path(tempfile.mkdtemp(prefix="krb_kdc_"))
KPORT, HPORT = freier_port(), freier_port()
LIBS = ""
if WURZEL:
    LIBS = str(WURZEL / "usr/lib/x86_64-linux-gnu")
PLUGIN = (WURZEL / "usr/lib/x86_64-linux-gnu/krb5/plugins") if WURZEL else None

(SAND / "krb5.conf").write_text(f"""[libdefaults]
  default_realm = TEST.LOCAL
  dns_lookup_kdc = false
  dns_lookup_realm = false
  dns_canonicalize_hostname = false
  rdns = false
[realms]
  TEST.LOCAL = {{
    kdc = 127.0.0.1:{KPORT}
  }}
[domain_realm]
  server.test.local = TEST.LOCAL
""" + (f"""[dbmodules]
  db_module_dir = {PLUGIN}/kdb
""" if PLUGIN else ""))
(SAND / "kdc.conf").write_text(f"""[kdcdefaults]
  kdc_listen = 127.0.0.1:{KPORT}
  kdc_tcp_listen = 127.0.0.1:{KPORT}
[realms]
  TEST.LOCAL = {{
    database_name = {SAND}/principal
    key_stash_file = {SAND}/stash
    acl_file = {SAND}/kadm5.acl
    supported_enctypes = aes256-cts-hmac-sha1-96:normal
  }}
[logging]
  kdc = FILE:{SAND}/kdc.log
""")
(SAND / "kadm5.acl").write_text("")

UMG = dict(os.environ, KRB5_CONFIG=str(SAND / "krb5.conf"),
           KRB5_KDC_PROFILE=str(SAND / "kdc.conf"),
           KRB5CCNAME="FILE:" + str(SAND / "cc"), KRB5RCACHEDIR=str(SAND))
# Die entpackten Bibliotheken NUR fuer die KDC-Werkzeuge – curl und dieser
# Prozess benutzen die System-libgssapi, wie der Dienst auch.
UMG_KDC = dict(UMG, LD_LIBRARY_PATH=LIBS) if LIBS else UMG
for k in ("KRB5_CONFIG", "KRB5CCNAME", "KRB5RCACHEDIR"):
    os.environ[k] = UMG[k]


def kdc_lauf(*cmd, eingabe=None):
    return subprocess.run(list(cmd), capture_output=True, text=True, env=UMG_KDC,
                          input=eingabe, timeout=60)


kdc_proc = None
server = None
try:
    r = kdc_lauf(KDB, "create", "-s", "-P", "masterpw", "-r", "TEST.LOCAL")
    if r.returncode:
        abbruch("kdb5_util create: " + (r.stderr or r.stdout)[-300:])
    for q in ("addprinc -pw userpw a.b", "addprinc -randkey HTTP/server.test.local",
              f"ktadd -k {SAND}/http.keytab HTTP/server.test.local",
              "addprinc -randkey HTTP/anders.test.local",
              f"ktadd -k {SAND}/falsch.keytab HTTP/anders.test.local"):
        r = kdc_lauf(KADM, "-q", q)
        if r.returncode:
            abbruch(f"kadmin.local {q}: " + (r.stderr or r.stdout)[-300:])
    kdc_proc = subprocess.Popen([KDC, "-n"], env=UMG_KDC, stdout=subprocess.DEVNULL,
                                stderr=open(SAND / "kdc.err", "w"))
    for _ in range(50):
        with socket.socket() as s:
            if s.connect_ex(("127.0.0.1", KPORT)) == 0:
                break
        time.sleep(0.1)
    r = kdc_lauf(KINIT, "a.b", eingabe="userpw\n")
    # Positivkontrolle: ohne Ticket waere jede Pruefung danach trivial.
    if r.returncode or not (SAND / "cc").is_file():
        abbruch("kinit gescheitert: " + (r.stderr or r.stdout)[-300:]
                + " | kdc.err: " + (SAND / "kdc.err").read_text()[-300:])
    print("Positivkontrolle: KDC laeuft, Ticket fuer a.b@TEST.LOCAL geholt.\n")

    os.environ["JARVIS_KERBEROS_KEYTAB"] = str(SAND / "http.keytab")
    TOKENS = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            auth = self.headers.get("Authorization") or ""
            kopf, daten, code = {}, {}, 401
            if not auth.startswith("Negotiate "):
                kopf["WWW-Authenticate"] = "Negotiate"
            else:
                tok = auth[len("Negotiate "):].strip()
                TOKENS.append(tok)
                try:
                    principal, aus = K.pruefe(base64.b64decode(tok))
                    daten = {"principal": principal,
                             "konto": K.konto_aus_principal(principal, "test.local"),
                             "antwort": len(aus)}
                    code = 200
                    if aus:
                        kopf["WWW-Authenticate"] = "Negotiate " + base64.b64encode(aus).decode()
                except K.KerberosFehler as e:
                    daten = {"fehler": str(e)}
            roh = json.dumps(daten).encode()
            self.send_response(code)
            for k, v in kopf.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(roh)))
            self.end_headers()
            self.wfile.write(roh)

    server = HTTPServer(("127.0.0.1", HPORT), H)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    URL = f"http://server.test.local:{HPORT}/"
    RES = ["--resolve", f"server.test.local:{HPORT}:127.0.0.1"]

    def curl(*extra):
        # Status ueber -w, Koepfe in eine Datei: bei Negotiate liefert curl
        # ZWEI Antworten (401, dann 200) – ein Zerleger ueber die gemischte
        # Ausgabe las beim ersten Lauf "Python/3.13.5" als Status.
        kopf_datei = SAND / "kopf.txt"
        r = subprocess.run([CURL, "-s", "-D", str(kopf_datei), "-w", "\n%{http_code}",
                            *RES, *extra, URL], capture_output=True, text=True, env=UMG,
                           timeout=30)
        rumpf, _, status = r.stdout.rpartition("\n")
        try:
            daten = json.loads(rumpf or "{}")
        except ValueError:
            daten = {}
        kopf = kopf_datei.read_text() if kopf_datei.is_file() else ""
        return status.strip(), kopf, daten

    print("== Erfolgsweg")
    st, kopf, d = curl("--negotiate", "-u", ":")
    pruefe(st == "200", "echtes SPNEGO-Ticket wird angenommen (HTTP %s, %s)" % (st, d))
    pruefe(d.get("principal") == "a.b@TEST.LOCAL", "Principal gelesen: %s" % d.get("principal"))
    pruefe(d.get("konto") == "a.b", "Kontoname: %s" % d.get("konto"))
    pruefe((d.get("antwort") or 0) > 0 and "WWW-Authenticate: Negotiate " in kopf,
           "Antwort-Token fuer gegenseitige Authentisierung (%s Byte)" % d.get("antwort"))

    print("\n== Replay")
    if TOKENS:
        st, _, d = curl("-H", "Authorization: Negotiate " + TOKENS[-1])
        pruefe(st == "401" and "replay" in (d.get("fehler") or "").lower(),
               "dasselbe Token ein zweites Mal: abgewiesen (%s)" % d.get("fehler"))
    else:
        pruefe(False, "kein Token aufgezeichnet")

    print("\n== Dauerlauf (Absturz, Speicher)")
    def rss():
        for z in Path("/proc/self/status").read_text().splitlines():
            if z.startswith("VmRSS:"):
                return int(z.split()[1])
        return 0
    for _ in range(20):
        curl("--negotiate", "-u", ":")
    rss0 = rss()
    codes = [curl("--negotiate", "-u", ":")[0] for _ in range(150)]
    rss1 = rss()
    pruefe(codes.count("200") == 150, "150 Anmeldungen hintereinander: %d x 200"
           % codes.count("200"))
    pruefe(rss1 - rss0 < 4096, "Speicher waechst nicht nennenswert (%+d kB)" % (rss1 - rss0))

    print("\n== Falsche Keytab")
    os.environ["JARVIS_KERBEROS_KEYTAB"] = str(SAND / "falsch.keytab")
    st, _, d = curl("--negotiate", "-u", ":")
    pruefe(st == "401" and "not found in keytab" in (d.get("fehler") or ""),
           "Ticket passt nicht zur Keytab: abgewiesen mit Ursache (%s)" % d.get("fehler"))
    os.environ["JARVIS_KERBEROS_KEYTAB"] = str(SAND / "http.keytab")
    st, _, d = curl("--negotiate", "-u", ":")
    pruefe(st == "200", "Keytab-Wechsel greift ohne Neustart wieder (HTTP %s)" % st)
finally:
    if server:
        server.shutdown()
    if kdc_proc:
        kdc_proc.terminate()
        try:
            kdc_proc.wait(5)
        except subprocess.TimeoutExpired:
            kdc_proc.kill()
    shutil.rmtree(SAND, ignore_errors=True)

print("\nBILANZ: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
