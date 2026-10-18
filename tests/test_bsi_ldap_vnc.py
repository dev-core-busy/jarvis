#!/usr/bin/env python3
"""Waechter: zwei Hoch-Befunde aus dem BSI-Abgleich vom 2026-09-29.

  [H5]  LDAP: scheiterte StartTLS, wurde still im Klartext gebunden (AD-Kennwort
        im Klartext zum DC); das Zertifikat wurde nie geprueft.
  [H11] x11vnc (root, -nopw) und websockify waren fuer JEDEN lokalen Prozess
        erreichbar, auch fuer die Agent-Shell der Domain-Benutzer.

Gemessen an der WIRKUNG:
  * H5 – ein echter ldap3-Client spricht mit einem lokalen LDAP-Server
    (BER von Hand, StartTLS verweigert / angenommen / ldaps mit selbst
    ausgestelltem Zertifikat). Der Server protokolliert jedes Byte VOR und
    NACH dem TLS-Aufbau – die Pruefung ist: steht das Kennwort je im Klartext
    auf der Leitung, und kommt mit Anker ein Bind UEBER TLS zustande?
    Login-Pfad (main.authenticate_linux_user, per AST geholt) und
    Verzeichnis-Pfad (ldap_directory._bind) laufen beide.
  * H11 – die nft-Regel aus start_jarvis_root.sh wird in einem eigenen
    Benutzer-/Netz-Namespace (unshare -rn) angewendet und gemessen, wer auf
    5900/6080 verbinden darf.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = 0
FAIL = 0


def check(name: str, bed: bool) -> None:
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name)


def abbruch(grund: str) -> None:
    print("ABBRUCH: " + grund)
    sys.exit(2)


# backend.config NUR als Stub – der echte Import schreibt die Live-settings.json.
EINST: dict = {}
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace(
    get_setting=lambda k, d=None: EINST.get(k, d),
    save_setting=lambda k, v: EINST.__setitem__(k, v),
)
sys.modules["backend.config"] = _cfg

try:
    import ldap3  # noqa: F401
except Exception as e:  # noqa: BLE001
    abbruch("ldap3 nicht importierbar: %s" % e)
if not shutil.which("openssl"):
    abbruch("openssl fehlt")

from backend import ldap_tls, sap_cert  # noqa: E402
from backend import ldap_directory  # noqa: E402

TMP = Path(tempfile.mkdtemp(prefix="waechter-bsi-ldap-"))
KENNWORT = "Geheim-H5-" + hashlib.sha1(os.urandom(8)).hexdigest()[:10]


# ── Zertifikat: lautet auf dc.test, verbunden wird ueber 127.0.0.1 ──────────
# Das ist die Lage auf DEV/ECHT (Zertifikat DS-DC01.firma.local, eingetragen die IP).
def _zert(name: str) -> tuple[Path, Path, bytes]:
    crt, key = TMP / (name + ".crt"), TMP / (name + ".key")
    r = subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
                        "-keyout", str(key), "-out", str(crt), "-days", "2",
                        "-subj", "/CN=dc.test", "-addext", "subjectAltName=DNS:dc.test"],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        abbruch("openssl req gescheitert: %s" % r.stderr[-300:])
    der = ssl.PEM_cert_to_DER_cert(crt.read_text())
    return crt, key, der


CRT, KEY, DER = _zert("dc")
FP = "sha256:" + hashlib.sha256(DER).hexdigest()


# ── Minimaler LDAP-Server (BER von Hand) ────────────────────────────────────
def _laenge(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(tag: int, inhalt: bytes) -> bytes:
    return bytes([tag]) + _laenge(len(inhalt)) + inhalt


def _nachricht(mid: int, op: bytes) -> bytes:
    return _tlv(0x30, _tlv(0x02, mid.to_bytes((mid.bit_length() + 8) // 8, "big")) + op)


def _ext_antwort(code: int) -> bytes:
    rest = _tlv(0x8A, b"1.3.6.1.4.1.1466.20037") if code == 0 else b""
    return _tlv(0x78, _tlv(0x0A, bytes([code])) + _tlv(0x04, b"") + _tlv(0x04, b"") + rest)


BIND_OK = _tlv(0x61, _tlv(0x0A, b"\x00") + _tlv(0x04, b"") + _tlv(0x04, b""))


def _lies(sock, mitschnitt: bytearray):
    """Eine LDAPMessage lesen -> (messageID, op-Tag) oder None bei EOF."""
    def genau(n):
        b = b""
        while len(b) < n:
            s = sock.recv(n - len(b))
            if not s:
                raise EOFError
            b += s
        mitschnitt.extend(b)
        return b
    try:
        kopf = genau(2)
        n = kopf[1]
        if n & 0x80:
            n = int.from_bytes(genau(n & 0x7F), "big")
        inhalt = genau(n)
    except (EOFError, OSError, ssl.SSLError):
        return None
    ml = inhalt[1]
    mid = int.from_bytes(inhalt[2:2 + ml], "big")
    return mid, inhalt[2 + ml]


class LdapAttrappe:
    """modus: 'verweigert' (StartTLS -> protocolError), 'starttls', 'ldaps'.
    klar = alle Bytes VOR TLS, innen = alle Bytes IM TLS-Kanal."""

    def __init__(self, modus: str):
        self.modus = modus
        self.klar = bytearray()
        self.innen = bytearray()
        self.binds_klar = 0
        self.binds_tls = 0
        self.lsock = socket.socket()
        self.lsock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.lsock.bind(("127.0.0.1", 0))
        self.lsock.listen(8)
        self.port = self.lsock.getsockname()[1]
        self.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        self.ctx.load_cert_chain(str(CRT), str(KEY))
        threading.Thread(target=self._annehmen, daemon=True).start()

    def _annehmen(self):
        while True:
            try:
                s, _ = self.lsock.accept()
            except OSError:
                return
            threading.Thread(target=self._bedienen, args=(s,), daemon=True).start()

    def _innen(self, t):
        while True:
            m = _lies(t, self.innen)
            if m is None:
                return
            mid, op = m
            if op == 0x60:
                self.binds_tls += 1
                t.sendall(_nachricht(mid, BIND_OK))
            elif op == 0x42:
                return

    def _bedienen(self, s):
        s.settimeout(10)
        try:
            if self.modus == "ldaps":
                self._innen(self.ctx.wrap_socket(s, server_side=True))
                return
            while True:
                m = _lies(s, self.klar)
                if m is None:
                    return
                mid, op = m
                if op == 0x77:                         # ExtendedRequest (StartTLS)
                    if self.modus == "verweigert":
                        s.sendall(_nachricht(mid, _ext_antwort(2)))
                        continue
                    s.sendall(_nachricht(mid, _ext_antwort(0)))
                    self._innen(self.ctx.wrap_socket(s, server_side=True))
                    return
                if op == 0x60:                         # Bind im KLARTEXT
                    self.binds_klar += 1
                    s.sendall(_nachricht(mid, BIND_OK))
                elif op == 0x42:
                    return
        except Exception:  # noqa: BLE001 – Client lehnt Zertifikat ab usw.
            pass
        finally:
            try:
                s.close()
            except OSError:
                pass

    def klartext_kennwort(self) -> bool:
        return KENNWORT.encode() in bytes(self.klar)


def _adresse(srv: LdapAttrappe) -> str:
    schema = "ldaps" if srv.modus == "ldaps" else "ldap"
    return "%s://127.0.0.1:%d" % (schema, srv.port)


def _einst(srv: LdapAttrappe | None, anker: dict | None = None, uebergang: str = "") -> None:
    """Vorgabe ist STRENG (leere Frist = unlesbar = aus) – sonst liefe jede
    Pruefung unten bis zum 2026-10-13 durch die Uebergangsfrist."""
    EINST.clear()
    EINST[ldap_tls.UEBERGANG_FELD] = uebergang
    if srv is not None:
        EINST.update({"ad_server": _adresse(srv), "ad_domain": "firma.test",
                      "ad_bind_user": "svc@firma.test", "ad_bind_password": KENNWORT})
    if anker is not None:
        EINST[ldap_tls.ANKER_FELD] = anker


def _binden(srv: LdapAttrappe):
    """verbinden + bind wie im Login. Rueckgabe: ('tls'|'ok'|'fehler', text)."""
    try:
        conn = ldap_tls.verbinden(_adresse(srv), "svc@firma.test", KENNWORT, timeout=5)
    except ldap_tls.TlsFehler as e:
        return "tls", str(e)
    except Exception as e:  # noqa: BLE001
        return "fehler", "%s: %s" % (type(e).__name__, e)
    try:
        return ("ok" if conn.bind() else "fehler"), ""
    except Exception as e:  # noqa: BLE001 – zaehlt als FAIL, nicht als Absturz
        return "fehler", "%s: %s" % (type(e).__name__, e)
    finally:
        ldap_tls._schliessen(conn)


# ════════════════════════════════════════════════════════════════════════════
print("\n[H5] Positivkontrolle: die Attrappe spricht LDAP")
# Ein ungeschuetzter ldap3-Client MUSS gegen die Attrappe binden koennen –
# sonst waere jedes "kein Klartext-Kennwort" unten trivial wahr.
roh = LdapAttrappe("verweigert")
_c = ldap3.Connection(ldap3.Server("127.0.0.1", port=roh.port, get_info=ldap3.NONE,
                                   connect_timeout=5),
                      user="svc@firma.test", password=KENNWORT, auto_bind=False)
try:
    _gebunden = _c.bind()
except Exception as e:  # noqa: BLE001
    abbruch("Attrappe beantwortet keinen Bind: %s" % e)
if not (_gebunden and roh.binds_klar == 1 and roh.klartext_kennwort()):
    abbruch("Positivkontrolle: Klartext-Bind kam nicht an (bind=%s, binds=%d)"
            % (_gebunden, roh.binds_klar))
check("Positivkontrolle: ungeschuetzter Client bindet, Kennwort im Mitschnitt", True)

# ── 1. DC verweigert StartTLS ───────────────────────────────────────────────
print("\n[H5] DC ohne StartTLS -> kein Bind, kein Kennwort")
srv = LdapAttrappe("verweigert")
_einst(srv)
art, text = _binden(srv)
check("verbinden: TlsFehler statt Rueckfall (%s)" % text[:60], art == "tls")
check("verbinden: Kennwort nie im Klartext gesendet", not srv.klartext_kennwort())
check("verbinden: kein Bind-Request beim DC angekommen", srv.binds_klar == 0)

srv = LdapAttrappe("verweigert")
_einst(srv)
try:
    ldap_directory._bind()
    _dir = "kein Fehler"
except RuntimeError as e:
    _dir = str(e)
check("ldap_directory._bind: TLS_FAILED (%s)" % _dir[:50], _dir.startswith("TLS_FAILED"))
check("ldap_directory._bind: Kennwort nie im Klartext", not srv.klartext_kennwort()
      and srv.binds_klar == 0)

# ── 2. StartTLS mit Zertifikat, das niemand kennt ───────────────────────────
print("\n[H5] StartTLS, Zertifikat unbekannt, kein Anker -> Abbruch")
srv = LdapAttrappe("starttls")
_einst(srv)
art, text = _binden(srv)
check("verbinden: TlsFehler (%s)" % text[:60], art == "tls")
check("kein Bind – weder im Klartext noch im Tunnel", srv.binds_klar == 0 and srv.binds_tls == 0)
check("Kennwort nie im Klartext", not srv.klartext_kennwort())

# ── 3. Pruefen + Verankern + Anmelden ───────────────────────────────────────
print("\n[H5] Zertifikat pruefen, verankern, dann Bind ueber TLS")
srv = LdapAttrappe("starttls")
_einst(srv)
try:
    erg = ldap_tls.pruefen(_adresse(srv))
except Exception as e:  # noqa: BLE001
    erg = {"fehler": str(e)}
check("pruefen: Fingerabdruck = das Zertifikat des Servers", erg.get("fingerprint") == FP)
check("pruefen: Systemspeicher reicht nicht (system_ok False)", erg.get("system_ok") is False)
check("pruefen: Anker wuerde tragen (pin_ok True)", erg.get("pin_ok") is True)
check("pruefen: Name passt nicht (IP statt dc.test) – gemessen", erg.get("name_abweichung") is True)
check("pruefen: kein Bind waehrend der Pruefung", srv.binds_klar == 0 and srv.binds_tls == 0)

try:
    ldap_tls.bestaetigen(_adresse(srv), "sha256:" + "0" * 64)
    _falsch = "angenommen"
except sap_cert.ZertFehler:
    _falsch = "abgelehnt"
check("bestaetigen: fremder Fingerabdruck abgelehnt", _falsch == "abgelehnt")

try:
    eintrag = ldap_tls.bestaetigen(_adresse(srv), FP)
except Exception as e:  # noqa: BLE001
    eintrag = {}
    print("       bestaetigen:", e)
check("bestaetigen: Eintrag mit Host/Port/Fingerabdruck",
      eintrag.get("fingerprint") == FP and eintrag.get("port") == srv.port
      and eintrag.get("host") == "127.0.0.1")
check("bestaetigen: Namensabweichung im Eintrag vermerkt", eintrag.get("name_abweichung") is True)

_einst(srv, eintrag)
art, text = _binden(srv)
check("mit Anker: Bind gelingt (%s)" % (text[:60] or art), art == "ok")
check("mit Anker: Bind kam IM TLS-Kanal an", srv.binds_tls >= 1 and srv.binds_klar == 0)
check("mit Anker: Kennwort nur im Tunnel, nie im Klartext",
      KENNWORT.encode() in bytes(srv.innen) and not srv.klartext_kennwort())

anders = dict(eintrag, port=eintrag.get("port", 0) + 1)
_einst(srv, anders)
art, _ = _binden(srv)
check("Anker fuer anderen Port gilt nicht -> Abbruch", art == "tls")

gefaelscht = dict(eintrag, name_abweichung=True)
_zb_crt, _zb_key, _zb_der = _zert("fremd")
gefaelscht["pem"] = _zb_crt.read_text()
_einst(srv, gefaelscht)
art, _ = _binden(srv)
check("Anker mit ANDEREM Zertifikat -> Abbruch (Namensverzicht oeffnet nichts)", art == "tls")

# ── 4. ldaps:// ─────────────────────────────────────────────────────────────
print("\n[H5] ldaps:// – gleiche Regeln ohne StartTLS")
srv = LdapAttrappe("ldaps")
_einst(srv)
art, _ = _binden(srv)
check("ldaps ohne Anker: Abbruch", art == "tls" and srv.binds_tls == 0)
try:
    e_ldaps = ldap_tls.bestaetigen(_adresse(srv), FP)
except Exception as e:  # noqa: BLE001
    e_ldaps = {}
    print("       bestaetigen ldaps:", e)
_einst(srv, e_ldaps)
art, text = _binden(srv)
check("ldaps mit Anker: Bind gelingt (%s)" % (text[:60] or art), art == "ok" and srv.binds_tls >= 1)

# ── 4b. Uebergangsfrist ─────────────────────────────────────────────────────
print("\n[H5] Uebergangsfrist: TLS Pflicht, nur die Pruefung ausgesetzt – ohne Anker")
import datetime  # noqa: E402
MORGEN = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
GESTERN = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()

srv = LdapAttrappe("starttls")
_einst(srv, uebergang=MORGEN)
_info: dict = {}
try:
    ldap_tls._schliessen(ldap_tls.verbinden(_adresse(srv), timeout=5, info=_info))
except Exception as e:  # noqa: BLE001
    print("       verbinden:", e)
check("Frist aktiv, unbekanntes Zertifikat: angenommen und als ungeprueft gemeldet",
      _info.get("ungeprueft") is True)
art, text = _binden(srv)
check("Frist aktiv: Bind gelingt (%s)" % (text[:60] or art), art == "ok")
check("Frist aktiv: Bind nur IM TLS-Kanal, Kennwort nie im Klartext",
      srv.binds_tls >= 1 and srv.binds_klar == 0 and not srv.klartext_kennwort())

srv = LdapAttrappe("verweigert")
_einst(srv, uebergang=MORGEN)
art, _ = _binden(srv)
check("Frist aktiv, DC ohne StartTLS: trotzdem Abbruch, kein Klartext",
      art == "tls" and srv.binds_klar == 0 and not srv.klartext_kennwort())

srv = LdapAttrappe("starttls")
_einst(srv, dict(gefaelscht, port=srv.port), uebergang=MORGEN)
art, _ = _binden(srv)
check("Frist aktiv, Anker gesetzt, anderes Zertifikat: Abbruch (kein Uebergang)",
      art == "tls" and srv.binds_tls == 0)

for bis, name in ((GESTERN, "abgelaufen"), ("kaputt", "unlesbar")):
    srv = LdapAttrappe("starttls")
    _einst(srv, uebergang=bis)
    art, _ = _binden(srv)
    check("Frist %s: streng, Abbruch" % name, art == "tls" and srv.binds_tls == 0)

EINST.clear()
_ue = ldap_tls.uebergang()
try:
    _ende = datetime.date.fromisoformat(ldap_tls.UEBERGANG_BIS)
except ValueError:
    _ende = None
check("Vorgabe-Frist ist ein Datum und gilt ohne Einstellung (%s)" % ldap_tls.UEBERGANG_BIS,
      _ende is not None and _ue["bis"] == ldap_tls.UEBERGANG_BIS
      and _ue["aktiv"] == (datetime.date.today() <= _ende))

# ── 5. Login-Pfad aus main.py ───────────────────────────────────────────────
print("\n[H5] main.authenticate_linux_user (per AST geholt)")
MAIN_SRC = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(MAIN_SRC)
_fn = next((n for n in BAUM.body if isinstance(n, ast.FunctionDef)
            and n.name == "authenticate_linux_user"), None)
if _fn is None:
    abbruch("authenticate_linux_user nicht in main.py")
_fn.decorator_list = []
for _a in _fn.args.args:
    _a.annotation = None
_fn.returns = None
_fn.args.defaults = [ast.Constant(None) for _ in _fn.args.defaults]
_ns: dict = {
    "ALLOWED_USERS": set(), "config": _cfg.config, "time": __import__("time"),
    "_ad_user_allowed": lambda *a: True,
    # Vorabpruefung (Password Spraying, 2026-10-15): hier "freigegeben", damit
    # der TLS-Weg erreicht wird – gemessen wird sie in test_anmelde_spruehen.py.
    "_ad_vorab_freigabe": lambda username: "ja",
    "_check_knowledge_edit_permission_with_conn": lambda *a: False,
    "_check_internet_access_with_conn": lambda *a: False,
    "_check_admin_with_conn": lambda *a: False,
    "_fetch_user_group_dns": lambda *a: [],
    "_knowledge_editor_cache": {}, "_internet_access_cache": {}, "_admin_access_cache": {},
    "_user_group_dns_cache": {}, "_ad_seen_users": {}, "_revoked_logins": {},
    "_save_ad_caches": lambda **k: None, "_save_revocations": lambda: None,
}
exec(compile(ast.fix_missing_locations(ast.Module(body=[_fn], type_ignores=[])),
             "main.py", "exec"), _ns)
_auth = _ns["authenticate_linux_user"]

srv = LdapAttrappe("verweigert")
_einst(srv)
det: dict = {}
_r = _auth("max.muster", KENNWORT, det)
check("Login ohne StartTLS: abgelehnt", _r is False)
check("Login ohne StartTLS: reason='ad_tls'", det.get("reason") == "ad_tls")
check("Login ohne StartTLS: Kennwort nie beim DC", not srv.klartext_kennwort()
      and srv.binds_klar == 0)

srv = LdapAttrappe("starttls")
_einst(srv)
EINST[ldap_tls.ANKER_FELD] = dict(eintrag, port=srv.port)
_r = _auth("max.muster", KENNWORT, {})
check("Positivkontrolle Login: mit Anker angemeldet, Bind im Tunnel",
      _r is True and srv.binds_tls >= 1 and srv.binds_klar == 0)

# Login-Endpunkt: 'ad_tls' wird VOR dem Fehlversuchszaehler beantwortet
_login = None
for n in ast.walk(BAUM):
    if isinstance(n, ast.AsyncFunctionDef):
        # Direkt ODER ueber asyncio.to_thread(authenticate_linux_user, u, p, d)
        # (seit 2026-10-18 im Thread, damit PAM/LDAP den Event-Loop nicht halten)
        rufe = [c for c in ast.walk(n) if isinstance(c, ast.Call) and (
                (isinstance(c.func, ast.Name) and c.func.id == "authenticate_linux_user"
                 and len(c.args) == 3)
                or (isinstance(c.func, ast.Attribute) and c.func.attr == "to_thread"
                    and len(c.args) == 4 and isinstance(c.args[0], ast.Name)
                    and c.args[0].id == "authenticate_linux_user"))]
        if rufe:
            _login = n
            break
_zeile_tls = _zeile_zaehler = _zeile_auth = None
if _login is not None:
    for n in ast.walk(_login):
        if (isinstance(n, ast.If) and isinstance(n.test, ast.Compare)
                and any(isinstance(k, ast.Constant) and k.value == "ad_tls"
                        for k in n.test.comparators)
                and any(isinstance(b, ast.Return) for b in n.body)):
            _zeile_tls = n.lineno
    # Massgeblich ist der erste Zaehler NACH der Anmeldung – ein frueherer
    # gehoert zu einem anderen Zweig (gesperrte IP o. ae.).
    _zeile_auth = min(c.lineno for c in rufe)
    _nach = [n.lineno for n in ast.walk(_login) if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name) and n.func.id == "_record_login_attempt"
             and n.lineno > _zeile_auth]
    _zeile_zaehler = min(_nach) if _nach else None
check("Login-Endpunkt: 'ad_tls' kehrt vor _record_login_attempt zurueck",
      None not in (_zeile_tls, _zeile_zaehler, _zeile_auth)
      and _zeile_auth < _zeile_tls < _zeile_zaehler)

# ── 6. Kein Weg an ldap_tls vorbei ──────────────────────────────────────────
print("\n[H5] Kein stiller Rueckfall, keine Anmeldedaten an ldap_tls vorbei")
stumm, direkt = [], []
for py in sorted((ROOT / "backend").rglob("*.py")):
    try:
        baum = ast.parse(py.read_text(encoding="utf-8"))
    except SyntaxError:
        continue
    rel = str(py.relative_to(ROOT))
    for n in ast.walk(baum):
        if isinstance(n, ast.Try):
            tls_im_try = any(isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
                             and c.func.attr == "start_tls"
                             for s in n.body for c in ast.walk(s))
            leer = any(all(isinstance(b, (ast.Pass, ast.Continue)) for b in h.body)
                       for h in n.handlers)
            if tls_im_try and leer:
                stumm.append("%s:%d" % (rel, n.lineno))
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "Connection" and rel != "backend/ldap_tls.py"
                and isinstance(n.func.value, ast.Name) and n.func.value.id == "ldap3"
                and ({k.arg for k in n.keywords} & {"user", "password"} or len(n.args) > 1)):
            direkt.append("%s:%d" % (rel, n.lineno))
check("kein start_tls in try/except-pass (%s)" % (", ".join(stumm) or "keins"), not stumm)
check("keine ldap3.Connection mit Anmeldedaten ausserhalb ldap_tls (%s)"
      % (", ".join(direkt) or "keine"), not direkt)

SET = (ROOT / "frontend" / "settings.html").read_text(encoding="utf-8")
# BSI H4 (CSP ohne Inline-Skript, 2026-10-04): die AD-/Berechtigungs-Logik stand als
# Inline-<script> in settings.html und liegt jetzt in js/settings_ad.js.
SET_AD = (ROOT / "frontend" / "js" / "settings_ad.js").read_text(encoding="utf-8")
check("settings.html: Anker-Container #ad-cert + Einhaengen mit AD-Basis",
      'id="ad-cert"' in SET and "basis: '/api/auth/ad_tls'" in SET_AD)
check("settings.html: Warnhinweis zur Uebergangsfrist, gesteuert ueber tls_uebergang",
      'id="ad-tls-uebergang"' in SET and "d.tls_uebergang" in SET_AD
      and "security.ad_tls_transition" in SET_AD)
_eps = {}
for n in BAUM.body:
    if isinstance(n, ast.AsyncFunctionDef):
        for d in n.decorator_list:
            if (isinstance(d, ast.Call) and d.args and isinstance(d.args[0], ast.Constant)
                    and str(d.args[0].value).startswith("/api/auth/ad_tls")):
                _eps[d.args[0].value + " " + d.func.attr] = [ast.unparse(x) for x in n.args.defaults]
check("drei ad_tls-Endpunkte, alle hinter require_local_auth (%d)" % len(_eps),
      len(_eps) == 3 and all(any("require_local_auth" in x for x in v) for v in _eps.values()))


# ════════════════════════════════════════════════════════════════════════════
print("\n[H11] nft-Regel aus start_jarvis_root.sh")
SKRIPT = (ROOT / "start_jarvis_root.sh").read_text(encoding="utf-8")


def _bash_funktion(name: str) -> str:
    """Funktionsdefinition aus dem Skript schneiden. Das Ende bestimmt bash: ein
    `}` am Zeilenanfang steht auch IM Heredoc (Tabellenende der nft-Regel) – der
    erste Schnitt, nach dem `declare -F name` die Funktion kennt, gilt."""
    m = re.search(r"^%s\(\) \{" % re.escape(name), SKRIPT, re.M)
    if not m:
        return ""
    for ende in re.finditer(r"^\}\n", SKRIPT[m.start():], re.M):
        schnitt = SKRIPT[m.start():m.start() + ende.end()]
        r = subprocess.run(["bash", "-c", schnitt + "\ndeclare -F %s >/dev/null" % name],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and not r.stderr.strip():
            return schnitt
    return ""


F_UIDS, F_REGELN = _bash_funktion("_vnc_erlaubte_uids"), _bash_funktion("_vnc_sperre_regeln")
if not (F_UIDS and F_REGELN):
    abbruch("_vnc_erlaubte_uids/_vnc_sperre_regeln nicht in start_jarvis_root.sh")
NFT = shutil.which("nft") or ("/usr/sbin/nft" if os.path.exists("/usr/sbin/nft") else "")
if not NFT or not shutil.which("unshare"):
    abbruch("nft oder unshare fehlt – H11 nicht messbar")


def _uids(user: str) -> str:
    r = subprocess.run(["bash", "-c", F_UIDS + '\n_vnc_erlaubte_uids "$1"', "x", user],
                       capture_output=True, text=True, timeout=10)
    return r.stdout.strip()


_ich = subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
check("uids: root -> nur 0", _uids("root") == "0")
check("uids: unbekannter Benutzer -> nur 0", _uids("gibt_es_nicht_h11") == "0")
if os.getuid() != 0:
    check("uids: Dienstbenutzer -> 0 + seine uid", _uids(_ich) == "0, %d" % os.getuid())

SONDE = r'''
import json, socket
erg = {}
ls = []
for p in (5900, 6080, 5901):
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("127.0.0.1", p)); s.listen(); ls.append(s)
for p in (5900, 6080, 5901):
    c = socket.socket(); c.settimeout(3)
    try:
        c.connect(("127.0.0.1", p)); erg[p] = "offen"
    except Exception as e:
        erg[p] = type(e).__name__
    c.close()
print(json.dumps(erg))
'''
(TMP / "sonde.py").write_text(SONDE)


def _namespace(erlaubt: str) -> tuple[dict, str, int]:
    """Regel ZWEIMAL anwenden (Broker-Neustart), dann messen. Im Namespace ist
    der Aufrufer uid 0 – 'erlaubt' ohne 0 simuliert den Sandbox-Benutzer."""
    skript = (F_REGELN + "\n"
              "set -e\nip link set lo up\n"
              '_vnc_sperre_regeln "$1" | "$2" -f -\n'
              '_vnc_sperre_regeln "$1" | "$2" -f -\n'
              '"$2" list table inet jarvis_vnc > "$3/regeln.txt"\n'
              'python3 "$3/sonde.py"\n')
    r = subprocess.run(["unshare", "-rn", "bash", "-c", skript, "x", erlaubt, NFT, str(TMP)],
                       capture_output=True, text=True, timeout=30,
                       env=dict(os.environ, PATH=os.environ.get("PATH", "") + ":/usr/sbin:/sbin"))
    try:
        erg = json.loads(r.stdout.strip().splitlines()[-1]) if r.stdout.strip() else {}
    except (ValueError, IndexError):
        erg = {}
    regeln = (TMP / "regeln.txt").read_text() if (TMP / "regeln.txt").exists() else ""
    return erg, regeln + r.stderr, r.returncode


frei, _, rc_frei = _namespace("0, 4242")
if rc_frei != 0 or not frei:
    abbruch("Namespace-Messung lief nicht (rc=%s) – unshare -rn gesperrt?" % rc_frei)
check("Positivkontrolle: erlaubter Aufrufer erreicht 5900 und 6080",
      frei.get("5900") == "offen" and frei.get("6080") == "offen")

zu, regeln, rc_zu = _namespace("4242")
check("fremder Aufrufer: 5900 abgewiesen (%s)" % zu.get("5900"), zu.get("5900") not in (None, "offen"))
check("fremder Aufrufer: 6080 (websockify) abgewiesen (%s)" % zu.get("6080"),
      zu.get("6080") not in (None, "offen"))
check("Regel ist eng: 5901 bleibt offen", zu.get("5901") == "offen")
check("zweimal angewendet -> genau EINE Regel (kein Verdoppeln)",
      len(re.findall(r"dport \{ 5900, 6080 \}", regeln)) == 1)
check("Bedingung haengt an skuid (kein nacktes Verwerfen)",
      # nft schreibt eine einelementige Menge als Einzelwert zurueck
      bool(re.search(r"meta skuid != (\{[^}]*\}|\d+)\s+reject", regeln)))

# Reihenfolge im Skript: Sperre steht, BEVOR x11vnc startet
_z = SKRIPT.splitlines()
_i_sperre = next((i for i, z in enumerate(_z)
                  if z.startswith("    if _vnc_sperre_regeln \"$VNC_UIDS\" | nft -f -")), None)
_i_start = next((i for i, z in enumerate(_z) if z.startswith("# 5. x11vnc starten")), None)
check("Sperre wird vor dem x11vnc-Start gesetzt",
      _i_sperre is not None and _i_start is not None and _i_sperre < _i_start)
check("Dienstbenutzer kommt aus jarvis.service",
      'VNC_UIDS="$(_vnc_erlaubte_uids "$VNC_SVC_USER")"' in SKRIPT
      and "systemctl show -p User --value jarvis.service" in SKRIPT)

shutil.rmtree(TMP, ignore_errors=True)
print("\n" + "=" * 60)
print("Ergebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
