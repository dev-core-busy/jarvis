#!/usr/bin/env python3
"""Waechter fuer die Windows-Anmeldung per Kerberos (AI-Maus, 2026-10-20).

Drei Teile:
  1. ``backend/kerberos_anmeldung.py`` gegen die ECHTE libgssapi_krb5 – ohne
     KDC, also nur die Fehlerwege (NTLM, Unsinn, leer, fehlende Keytab) und die
     Principal-Zerlegung. Den Erfolgsweg misst ``test_kerberos_kdc.py`` mit
     einem echten MIT-KDC.
  2. ``_ad_windows_freigabe`` und ``_login_windows_ablauf`` werden per AST aus
     ``main.py`` GESCHNITTEN und mit Attrappen WIRKLICH ausgefuehrt – gemessen
     wird das Verhalten (Status, Kopfzeilen, Token-Art), nicht das Vorkommen
     eines Namens.
  3. Die AI-Maus: Windows-Anmeldung vor der Kennwortmaske, Rueckfall bleibt.

Laeuft ohne fastapi und ohne ``backend.config`` (Exit 2, wenn es doch geladen
wird). Exit 2 auch, wenn die GSSAPI-Bibliothek fehlt – dann ist Teil 1 nicht
messbar, und ein gruener Rest saehe wie eine Messung aus.
"""

import ast
import asyncio
import base64
import json
import os
import re
import sys
import tempfile
import types
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


def abschnitt(t):
    print("\n== " + t)


from backend import kerberos_anmeldung as K  # noqa: E402

if getattr(sys.modules.get("backend.config"), "__file__", None):
    print("ABBRUCH: backend.config wurde geladen (schriebe die Live-settings.json).",
          file=sys.stderr)
    sys.exit(2)

# ═══ 1. Modul gegen die echte Bibliothek ════════════════════════════════════
abschnitt("1. kerberos_anmeldung gegen libgssapi_krb5")
try:
    K._bibliothek()
except K.KerberosFehler as e:
    print("ABBRUCH: libgssapi_krb5 nicht nutzbar (%s) – Teil 1 nicht messbar." % e,
          file=sys.stderr)
    sys.exit(2)

_SAND = Path(tempfile.mkdtemp(prefix="krb_test_"))
_alt_env = os.environ.get("JARVIS_KERBEROS_KEYTAB")
try:
    os.environ["JARVIS_KERBEROS_KEYTAB"] = str(_SAND / "fehlt.keytab")
    bereit, grund = K.eingerichtet()
    pruefe(not bereit and "keine Keytab" in grund, "ohne Keytab: nicht eingerichtet (%s)" % grund)
    try:
        K.pruefe(b"\x60\x10" + b"x" * 16)
        pruefe(False, "ohne Keytab wirft pruefe()")
    except K.KerberosFehler as e:
        pruefe("keine Keytab" in str(e), "ohne Keytab wirft pruefe() mit Grund (%s)" % e)

    (_SAND / "leer.keytab").write_bytes(b"")
    os.environ["JARVIS_KERBEROS_KEYTAB"] = str(_SAND / "leer.keytab")
    bereit, grund = K.eingerichtet()
    pruefe(bereit, "mit lesbarer Keytab-Datei: eingerichtet")

    def wirft(token, teil, text):
        try:
            K.pruefe(token)
            pruefe(False, text + " (kein Fehler)")
        except K.KerberosFehler as e:
            pruefe(teil.lower() in str(e).lower(), "%s: %s" % (text, e))

    wirft(b"NTLMSSP\x00\x01\x00\x00\x00", "NTLM statt Kerberos",
          "NTLM wird VOR der Bibliothek abgewiesen")
    wirft(b"", "leeres Token", "leeres Token")
    # Ein kaputtes Token muss als KLARTEXT zurueckkommen (gss_display_status),
    # nicht als Absturz und nicht als nackte Zahl.
    wirft(b"\x60\x10" + b"x" * 16, "token", "kaputtes SPNEGO-Token liefert Klartext")
    wirft(b"Unsinn", "token", "Unsinn liefert Klartext")
finally:
    if _alt_env is None:
        os.environ.pop("JARVIS_KERBEROS_KEYTAB", None)
    else:
        os.environ["JARVIS_KERBEROS_KEYTAB"] = _alt_env

for principal, realm, erwartet in (
        ("a.b@FIRMA.LOCAL", "firma.local", "a.b"),
        ("A.B@firma.local", "FIRMA.LOCAL", "a.b")):
    pruefe(K.konto_aus_principal(principal, realm) == erwartet,
           "%s -> %s" % (principal, erwartet))
for principal, warum in (
        ("a.b@ANDERE.DE", "fremder Realm"),
        ("HTTP/host@FIRMA.LOCAL", "kein Benutzer-Principal"),
        ("ohne_realm", "Principal ohne Realm"),
        ("@FIRMA.LOCAL", "Principal ohne Realm")):
    try:
        K.konto_aus_principal(principal, "firma.local")
        pruefe(False, "%s abgewiesen (%s)" % (principal, warum))
    except K.KerberosFehler as e:
        pruefe(warum.lower() in str(e).lower(), "%s abgewiesen: %s" % (principal, e))
try:
    K.konto_aus_principal("a.b@FIRMA.LOCAL", "")
    pruefe(False, "ohne konfigurierte Domaene wird abgewiesen")
except K.KerberosFehler:
    pruefe(True, "ohne konfigurierte Domaene wird abgewiesen")

# MIT heisst die Funktion krb5_gss_…, Heimdal gsskrb5_… – am 2026-10-20 mit
# dem Heimdal-Namen gebaut und erst beim Messen aufgefallen.
_quelle_k = (ROOT / "backend" / "kerberos_anmeldung.py").read_text(encoding="utf-8")
pruefe("krb5_gss_register_acceptor_identity" in _quelle_k
       and "lib.gsskrb5_register" not in _quelle_k,
       "MIT-Funktionsname fuer die Keytab-Registrierung")

# ═══ 2. main.py: geschnitten und ausgefuehrt ════════════════════════════════
abschnitt("2. Endpunkt und Freigabe (geschnitten, ausgefuehrt)")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(MAIN)
FUNK = {n.name: n for n in BAUM.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

for name in ("_ad_windows_freigabe", "_login_windows_ablauf", "login_windows"):
    pruefe(name in FUNK, "%s existiert in main.py" % name)
if not all(n in FUNK for n in ("_ad_windows_freigabe", "_login_windows_ablauf",
                               "login_windows")):
    print("ABBRUCH: Funktionen fehlen – Rest nicht messbar.", file=sys.stderr)
    sys.exit(1)


def _dekoratoren(fn):
    return [ast.unparse(d) for d in fn.decorator_list]


pruefe("app.post('/api/login/windows')" in _dekoratoren(FUNK["login_windows"]),
       "Route POST /api/login/windows")
pruefe(not any(isinstance(a, ast.Call) and getattr(a.func, "id", "") == "Depends"
               for fn in (FUNK["login_windows"], FUNK["_login_windows_ablauf"])
               for a in ast.walk(fn)),
       "keine Dependency – ein Anmeldeweg hat noch keine Sitzung")


def _aufrufe(fn) -> set:
    namen = set()
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            namen.add(ast.unparse(n.func))
    return namen


_rahmen = _aufrufe(FUNK["login_windows"])
pruefe("_anmeldung_protokollieren" in _rahmen, "Rahmen protokolliert (BSI M2)")
pruefe("_anmelde_schutz.bremse" in _rahmen and "_anmelde_schutz.angleichen" in _rahmen,
       "Rahmen bremst und gleicht die Dauer an wie /api/login")


def _schneiden(name, ns):
    code = compile(ast.Module(body=[FUNK[name]], type_ignores=[]), "main.py", "exec")
    exec(code, ns)  # noqa: S102
    return ns[name]


# ── 2a. _ad_windows_freigabe ────────────────────────────────────────────────
class _Wert:
    def __init__(self, v):
        self.value = v
        self.values = [v]


class _Eintrag(dict):
    def __getitem__(self, k):
        return _Wert(dict.get(self, k))


class _Conn:
    def __init__(self, eintraege, wirft=False):
        self._e = eintraege
        self.entries = []
        self.wirft = wirft
        self.unbound = False

    def search(self, **kw):
        if self.wirft:
            raise RuntimeError("Netz weg")
        self.entries = list(self._e)

    def unbind(self):
        self.unbound = True


def _freigabe_lauf(conn=None, bind_fehler=False, rollen="ok", erlaubt=True):
    ld = types.ModuleType("backend.ldap_directory")

    def _bind():
        if bind_fehler:
            raise RuntimeError("BIND_FAILED")
        return conn, "DC=x"
    ld._bind = _bind
    sys.modules["backend.ldap_directory"] = ld
    import backend
    backend.ldap_directory = ld
    gesehen, gespeichert, gefragt = {}, [], []
    ns = {"_ldap_escape": lambda s: s, "print": lambda *a, **k: None,
          "_ad_rollen_aktualisieren": lambda c, b, p: (rollen, []),
          "_ad_user_allowed": lambda c, p, b: (gefragt.append(p), erlaubt)[1],
          "_ad_seen_users": gesehen, "time": __import__("time"),
          "_save_ad_caches": lambda force=False: gespeichert.append(force)}
    fn = _schneiden("_ad_windows_freigabe", ns)
    return fn("a.b"), gesehen, gespeichert, gefragt


erg, gesehen, gesp, gefragt = _freigabe_lauf(conn=_Conn([_Eintrag(userAccountControl=512)]))
pruefe(erg == "ja", "aktives, freigegebenes Konto -> ja")
pruefe("a.b" in gesehen and gesp == [True],
       "Revalidierung kennt den Benutzer danach, Rollen gespeichert")
pruefe(gefragt == ["a.b"], "Freigabe ueber _ad_user_allowed (dieselbe Funktion wie Kennwortweg)")
pruefe(_freigabe_lauf(bind_fehler=True)[0] == "fehler",
       "Dienst-Bind scheitert -> fehler (fail-closed)")
pruefe(_freigabe_lauf(conn=_Conn([]))[0] == "nein", "Konto unbekannt -> nein")
erg, gesehen, _, gefragt = _freigabe_lauf(conn=_Conn([_Eintrag(userAccountControl=514)]))
pruefe(erg == "nein" and not gefragt and not gesehen,
       "im AD deaktiviertes Konto -> nein, ohne Freigabeabfrage")
pruefe(_freigabe_lauf(conn=_Conn([_Eintrag(userAccountControl=512)]), rollen="fehler")[0]
       == "fehler", "Rollenabgleich scheitert -> fehler")
pruefe(_freigabe_lauf(conn=_Conn([_Eintrag(userAccountControl=512)]), erlaubt=False)[0]
       == "nein", "nicht freigegeben -> nein")
_c = _Conn([], wirft=True)
pruefe(_freigabe_lauf(conn=_c)[0] == "fehler" and _c.unbound,
       "Suche wirft -> fehler, Verbindung trotzdem geschlossen")


# ── 2b. _login_windows_ablauf ───────────────────────────────────────────────
class JSONResponse:
    """Attrappe mit der Signatur von starlette.responses.JSONResponse."""

    def __init__(self, content, status_code=200, headers=None, media_type=None,
                 background=None):
        self.status_code = status_code
        self.body = json.dumps(content).encode()
        self.headers = dict(headers or {})


class _Req:
    def __init__(self, kopf=None):
        self.headers = {k.lower(): v for k, v in (kopf or {}).items()}
        self.client = types.SimpleNamespace(host="192.0.2.7")


def _ablauf(kopf=None, keytab=True, ad=True, krb_wirft=None, principal="a.b@FIRMA.LOCAL",
            freigabe="ja", lizenz=True, gesperrt=None, rate=True, block=None,
            erlaubte=("jarvis", "root")):
    krb = types.ModuleType("backend.kerberos_anmeldung")
    krb.KerberosFehler = K.KerberosFehler
    krb.eingerichtet = lambda: (True, "") if keytab else (False, "keine Keytab unter /x")

    def _pruefe(roh):
        if krb_wirft:
            raise K.KerberosFehler(krb_wirft)
        return principal, b"antwort"
    krb.pruefe = _pruefe
    krb.konto_aus_principal = K.konto_aus_principal
    sys.modules["backend.kerberos_anmeldung"] = krb
    import backend
    alt_krb = getattr(backend, "kerberos_anmeldung", None)
    backend.kerberos_anmeldung = krb
    lic = types.ModuleType("backend.license_enforce")
    lic.darf_benutzer_anmelden = lambda u: (lizenz, "" if lizenz else "Grenze erreicht")
    sys.modules["backend.license_enforce"] = lic
    backend.license_enforce = lic

    tokens, kontext = [], []
    cfg = types.SimpleNamespace(get_setting=lambda k, d=None: {
        "ad_server": "dc.beispiel" if ad else "", "ad_domain": "firma.local" if ad else ""
    }.get(k, d))
    ns = {
        "config": cfg, "JSONResponse": JSONResponse, "asyncio": asyncio, "Request": _Req,
        "print": lambda *a, **k: None, "ALLOWED_USERS": set(erlaubte),
        "_check_rate_limit": lambda ip: rate,
        "_konto_sperre_antwort": lambda u: gesperrt,
        "_ad_windows_freigabe": lambda u: freigabe,
        "generate_token": lambda u, **kw: (tokens.append((u, kw)), "TOK")[1],
        "_anmelde_schutz": types.SimpleNamespace(erfolg=lambda u: None),
        "_user_sessions": types.SimpleNamespace(record_login=lambda *a, **k: None),
        "_display_name": lambda u: u,
        "security_guard": types.SimpleNamespace(get_block=lambda u: block),
        "_sitzung_kontext": types.SimpleNamespace(set=kontext.append),
        "_sitzung_antwort": lambda req, daten: JSONResponse(daten),
    }
    try:
        fn = _schneiden("_login_windows_ablauf", ns)
        resp = asyncio.run(fn(_Req(kopf)))
    finally:
        sys.modules["backend.kerberos_anmeldung"] = K
        backend.kerberos_anmeldung = alt_krb if alt_krb is not None else K
    return resp, json.loads(resp.body), tokens, kontext


NEG = {"Authorization": "Negotiate " + base64.b64encode(b"\x60\x01x").decode()}

r, d, t, _ = _ablauf(kopf=None, keytab=False)
pruefe(r.status_code == 503 and d.get("nicht_eingerichtet"),
       "ohne Keytab: 503 + nicht_eingerichtet (Client nimmt die Kennwortmaske)")
pruefe("WWW-Authenticate" not in r.headers,
       "ohne Keytab KEINE Aufforderung – Windows holt sonst ein Ticket fuer nichts")
r, d, _, _ = _ablauf(kopf=None, ad=False)
pruefe(r.status_code == 503 and "kein AD" in d.get("error", ""), "ohne AD-Konfiguration: 503")

r, d, t, _ = _ablauf(kopf=None)
pruefe(r.status_code == 401 and r.headers.get("WWW-Authenticate") == "Negotiate",
       "ohne Ticket: 401 + WWW-Authenticate: Negotiate")
pruefe(not t, "ohne Ticket kein Token")

r, d, t, kx = _ablauf(kopf=NEG)
pruefe(r.status_code == 200 and d.get("success") and d.get("token") == "TOK",
       "gueltiges Ticket: 200 mit Token")
pruefe(d.get("username") == "a.b", "Benutzername ist der blosse Kontoname (%s)" % d.get("username"))
pruefe(t and t[0][1].get("ohne_admin") is True and t[0][1].get("mit_2fa") is False,
       "Sitzung OHNE Admin-Rechte und ohne 2FA-Vermerk (%s)" % (t[0][1] if t else "-"))
pruefe(d.get("is_admin") is False, "Antwort meldet is_admin=False")
pruefe(kx == [("a.b", False, True)], "Sitzungskontext: (konto, 2fa=False, ohne_admin=True)")
pruefe(r.headers.get("WWW-Authenticate") == "Negotiate " + base64.b64encode(b"antwort").decode(),
       "Antwort-Token fuer gegenseitige Authentisierung im Kopf")

r, d, t, _ = _ablauf(kopf=NEG, krb_wirft="NTLM statt Kerberos")
pruefe(r.status_code == 401 and "NTLM" in d.get("error", "") and not t,
       "abgewiesenes Ticket: 401 mit Grund, kein Token")
pruefe("WWW-Authenticate" not in r.headers,
       "nach abgewiesenem Ticket KEINE neue Aufforderung (sonst Schleife statt Rueckfall)")

r, d, t, _ = _ablauf(kopf=NEG, principal="a.b@ANDERE.DE")
pruefe(r.status_code == 401 and not t, "fremder Realm: 401, kein Token")
r, d, t, _ = _ablauf(kopf=NEG, principal="jarvis@FIRMA.LOCAL")
pruefe(r.status_code == 403 and not t,
       "Domaenenkonto mit dem Namen eines LOKALEN Kontos: 403, kein Token")
r, d, t, _ = _ablauf(kopf=NEG, freigabe="nein")
pruefe(r.status_code == 403 and not t, "keine AD-Freigabe: 403, kein Token")
r, d, t, _ = _ablauf(kopf=NEG, freigabe="fehler")
pruefe(r.status_code == 503 and not t, "Freigabe nicht pruefbar: 503, kein Token (fail-closed)")
# Fail-closed auch fuer einen Wert, den heute niemand liefert: herein kommt
# nur "ja", nicht "alles ausser nein".
r, d, t, _ = _ablauf(kopf=NEG, freigabe="unbekannt")
pruefe(r.status_code == 403 and not t, "unerwartete Freigabe-Antwort: 403, kein Token")
r, d, t, _ = _ablauf(kopf=NEG, lizenz=False)
pruefe(r.status_code == 403 and not t, "Lizenzgrenze: 403, kein Token")
_sperre = JSONResponse({"success": False}, status_code=429)
r, d, t, _ = _ablauf(kopf=NEG, gesperrt=_sperre)
pruefe(r is _sperre and not t, "Kontosperre greift vor der Freigabe")
r, d, t, _ = _ablauf(kopf=NEG, rate=False)
pruefe(r.status_code == 429 and not t, "Ratenbegrenzung: 429")
r, d, t, _ = _ablauf(kopf={"Authorization": "Negotiate !!kein-base64!!"})
pruefe(r.status_code == 400 and not t, "unlesbares Token: 400")
r, d, t, _ = _ablauf(kopf=NEG, block={"reason": "x", "incidents": []})
pruefe(r.status_code == 200 and d.get("account_blocked") is True,
       "gesperrtes Konto: angemeldet, aber account_blocked wie bei /api/login")

# ═══ 3. AI-Maus ═════════════════════════════════════════════════════════════
abschnitt("3. AI-Maus: Windows-Anmeldung zuerst, Kennwort als Rueckfall")
AM = ROOT / "ai-mouse" / "src" / "AiMouse"
CLIENT = (AM / "Vision" / "JarvisClient.cs").read_text(encoding="utf-8")
TRAY = (AM / "TrayApplicationContext.cs").read_text(encoding="utf-8")


def _cs_ohne_kommentare(cs: str) -> str:
    cs = re.sub(r"/\*.*?\*/", "", cs, flags=re.S)
    return "\n".join(z.split("//", 1)[0] for z in cs.splitlines())


def _methode(cs: str, kopf: str) -> str:
    """Rumpf einer C#-Methode ueber Klammerzaehlung ('' wenn nicht gefunden)."""
    i = cs.find(kopf)
    if i < 0:
        return ""
    j = cs.find("{", i)
    tiefe = 0
    for k in range(j, len(cs)):
        if cs[k] == "{":
            tiefe += 1
        elif cs[k] == "}":
            tiefe -= 1
            if tiefe == 0:
                return cs[j:k + 1]
    return ""


C = _cs_ohne_kommentare(CLIENT)
T = _cs_ohne_kommentare(TRAY)
win = _methode(C, "Task<bool> WindowsAnmeldenAsync(")
pruefe(bool(win), "JarvisClient.WindowsAnmeldenAsync existiert")
pruefe("/api/login/windows" in win, "ruft /api/login/windows")
pruefe("UseDefaultCredentials = true" in win, "schickt die Windows-Anmeldung (Default Credentials)")
pruefe("AllowAutoRedirect = false" in win,
       "folgt keiner Umleitung – das Ticket geht nur an den eingestellten Server")
pruefe("_http" not in win.replace("_httpWin", ""),
       "eigener HttpClient: der normale Client schickt nie Windows-Anmeldedaten")
pruefe("return false" in win and "catch" in win, "jeder Fehlschlag endet in false, nicht in einer Ausnahme")

sicher = _methode(T, "Task<bool> SicherstellenAngemeldetAsync(")
pruefe(bool(sicher), "SicherstellenAngemeldetAsync gefunden")
_i_win = sicher.find("WindowsAnmeldenAsync")
_i_maske = sicher.find("FrageAnmeldung(")
pruefe(_i_win >= 0 and _i_maske >= 0 and _i_win < _i_maske,
       "Windows-Anmeldung VOR der Kennwortmaske, die Maske bleibt als Rueckfall")
# Nicht nur das VORKOMMEN: ein `if (false && …)` liesse den Namen stehen. Die
# Bedingung selbst und die Folge (Token merken, fertig) gehoeren geprueft.
pruefe(re.search(r"if \(WindowsKontoPasst\(_settings\) &&\s*await _client\.WindowsAnmeldenAsync"
                 r"\(ct\)\.ConfigureAwait\(true\)\)\s*\{[^}]*SaveToken\(_client\.Token\)[^}]*"
                 r"return true;", sicher) is not None,
       "gelungene Windows-Anmeldung merkt das Token und endet OHNE Maske")
start = _methode(T, "Task StartAnmeldungAsync(")
pruefe(re.search(r"if \(!WindowsKontoPasst\(_settings\) \|\|\s*!await _client\.WindowsAnmeldenAsync"
                 r"\(cts\.Token\)\.ConfigureAwait\(true\)\)\s*\{\s*return;\s*\}\s*"
                 r"ConfigStore\.SaveToken\(_client\.Token\);", start) is not None,
       "beim Start still per Windows anmelden (kein Dialog), Token wird gemerkt")
pruefe("FrageAnmeldung(" not in start, "der Start zeigt weiterhin keine Kennwortmaske")

# ═══ 4. Die Keytab ist fuer Agent und Shell gesperrt ════════════════════════
abschnitt("4. Keytab gesperrt (sonst: Anmeldung als beliebiger Benutzer)")
# backend.sandbox liest backend.config – nur als Attrappe (die echte schriebe
# die Live-settings.json).
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace(get_setting=lambda k, d=None: d,
                                    get_skill_states=lambda: {})
sys.modules.setdefault("backend.config", _cfg)
if getattr(sys.modules["backend.config"], "__file__", None):
    print("ABBRUCH: das ECHTE backend.config wurde geladen.", file=sys.stderr)
    sys.exit(2)
from backend import sandbox as SB  # noqa: E402

_kt = SB.PROJECT_ROOT / "data" / "kerberos" / "http.keytab"
# Positivkontrolle: die Pruefung sagt nicht pauschal "sensibel".
pruefe(not SB.is_sensitive((SB.PROJECT_ROOT / "data" / "knowledge" / "x.txt").resolve()),
       "Positivkontrolle: eine Wissensdatei ist NICHT gesperrt")
pruefe(SB.is_sensitive(_kt.resolve()), "Dateiwerkzeuge: data/kerberos/http.keytab gesperrt")
pruefe(SB.is_sensitive(Path("/tmp/kopie/irgendwas.keytab")),
       "Dateiwerkzeuge: jede *.keytab gesperrt, auch eine Kopie unter /tmp")
# Zwei Schranken mit verschiedenem Zweck: die Endung faengt Kopien ueberall,
# der Ordner faengt eine Keytab OHNE Endung (JARVIS_KERBEROS_KEYTAB ist frei).
pruefe(SB.is_sensitive((SB.PROJECT_ROOT / "data" / "kerberos" / "dienst").resolve()),
       "Dateiwerkzeuge: auch eine Keytab OHNE Endung in data/kerberos gesperrt")
pruefe(not SB.authorize_fs("read", str(_kt), "a.b")[0], "authorize_fs verweigert das Lesen")
for cmd in ("cat /opt/jarvis/data/kerberos/http.keytab", "base64 ../kerberos/http.keytab",
            "cp /x/y.keytab /tmp/"):
    pruefe(bool(SB.SHELL_SECRET_PATHS.search(cmd)), "Shell gesperrt: %s" % cmd)
pruefe(not SB.SHELL_SECRET_PATHS.search("cat data/knowledge/notiz.txt"),
       "Positivkontrolle Shell: gewoehnlicher Pfad bleibt frei")
pruefe("data/kerberos" in SB.PRIVATE_DIRS, "Verzeichnis wird gehaertet (0750)")
pruefe("data/kerberos/http.keytab" in SB.PRIVATE_FILES_STRENG, "Keytab wird gehaertet (0600)")

print("\nBILANZ: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
