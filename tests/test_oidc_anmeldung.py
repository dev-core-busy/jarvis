#!/usr/bin/env python3
"""Waechter fuer die Anmeldung ueber den IdP per OpenID Connect (2026-11-17).

Drei Teile:
  1. ``backend/oidc_anmeldung.py`` mit ECHTER Kryptografie: selbst erzeugte
     RSA- und EC-Schluessel signieren Tokens; gemessen wird, dass jedes
     manipulierte Merkmal (alg, Signatur, iss, aud/azp, exp/nbf/iat, nonce,
     kid) abgewiesen wird – mit Positivkontrolle VORHER (ein gueltiges Token
     muss durchgehen, sonst ist jede Abweisung trivial wahr -> Exit 2).
     Dazu Kontoname, MFA-Nachweis, Ablagen, PKCE, Discovery, Code-Tausch.
  2. ``oidc_callback`` und ``_oidc_einloesen_ablauf`` werden per AST aus
     ``main.py`` GESCHNITTEN und mit Attrappen WIRKLICH ausgefuehrt:
     state/Cookie-Bindung, lokales Konto, Sperre, Freigabe, Einloese-Schein
     einmalig, 2FA nach Einstellung, Admin ohne 2FA ohne Admin-Rechte.
  3. Bestandsschutz: die Kennwortanmeldung ist unveraendert erreichbar, die
     neuen Routen stehen in der Freiliste, das Client-Secret ist ein
     Tresor-Feld und wird von keinem Endpunkt herausgegeben.

Laeuft ohne fastapi und ohne ``backend.config`` (Exit 2, wenn es doch geladen
wird).
"""

import ast
import asyncio
import base64
import hashlib
import hmac
import json
import sys
import time
import types
from pathlib import Path
from urllib.parse import parse_qs, urlparse

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


try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec, padding, rsa, utils
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: cryptography fehlt (%s)" % e, file=sys.stderr)
    sys.exit(2)

from backend import oidc_anmeldung as O  # noqa: E402

if getattr(sys.modules.get("backend.config"), "__file__", None):
    print("ABBRUCH: backend.config wurde geladen (schriebe die Live-settings.json).",
          file=sys.stderr)
    sys.exit(2)


# ── Testmaterial: Schluessel und Signieren ──────────────────────────────────
def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def int_b64(n: int) -> str:
    return b64u(n.to_bytes((n.bit_length() + 7) // 8, "big"))


RSA = rsa.generate_private_key(public_exponent=65537, key_size=2048)
RSA2 = rsa.generate_private_key(public_exponent=65537, key_size=2048)
EC = ec.generate_private_key(ec.SECP256R1())
_rn = RSA.public_key().public_numbers()
_en = EC.public_key().public_numbers()
JWK_RSA = {"kty": "RSA", "kid": "r1", "use": "sig", "n": int_b64(_rn.n), "e": int_b64(_rn.e)}
JWK_EC = {"kty": "EC", "kid": "e1", "crv": "P-256",
          "x": b64u(_en.x.to_bytes(32, "big")), "y": b64u(_en.y.to_bytes(32, "big"))}
JWKS = [JWK_RSA, JWK_EC]

ISS = "https://idp.beispiel.de/oidc"
CID = "jarvis-test"
NONCE = "nonce-123"


def signieren(claims, alg="RS256", kid="r1", key=None, kopf_extra=None):
    kopf = {"alg": alg, "typ": "JWT"}
    if kid is not None:
        kopf["kid"] = kid
    kopf.update(kopf_extra or {})
    roh = (b64u(json.dumps(kopf).encode()) + "." + b64u(json.dumps(claims).encode())).encode()
    if alg == "RS256":
        sig = (key or RSA).sign(roh, padding.PKCS1v15(), hashes.SHA256())
    elif alg == "PS256":
        sig = (key or RSA).sign(roh, padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                                                  salt_length=32), hashes.SHA256())
    elif alg == "ES256":
        r, s = utils.decode_dss_signature((key or EC).sign(roh, ec.ECDSA(hashes.SHA256())))
        sig = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    elif alg == "HS256":
        # Klassische Umgehung: der OEFFENTLICHE Schluessel als HMAC-Geheimnis.
        pem = RSA.public_key().public_bytes(serialization.Encoding.PEM,
                                            serialization.PublicFormat.SubjectPublicKeyInfo)
        sig = hmac.new(pem, roh, hashlib.sha256).digest()
    elif alg == "none":
        sig = b""
    else:
        raise ValueError(alg)
    return roh.decode() + "." + b64u(sig)


def claims(**ueber):
    jetzt = int(time.time())
    c = {"iss": ISS, "aud": CID, "sub": "x1", "preferred_username": "m.muster",
         "exp": jetzt + 300, "iat": jetzt, "nonce": NONCE}
    c.update(ueber)
    return {k: v for k, v in c.items() if v is not None}


def pruefen(tok, **kw):
    args = dict(issuer=ISS, client_id=CID, nonce=NONCE)
    args.update(kw)
    return O.pruefe_id_token(tok, JWKS, **args)


def abgewiesen(tok, text, teil="", **kw):
    try:
        pruefen(tok, **kw)
        pruefe(False, text + " (durchgegangen!)")
    except O.OidcFehler as e:
        pruefe(teil.lower() in str(e).lower(), "%s: %s" % (text, e))


# ═══ 1. Modul ════════════════════════════════════════════════════════════════
abschnitt("1a. Positivkontrolle: gueltige Tokens gehen durch")
_pk = []
for alg, kid in (("RS256", "r1"), ("PS256", "r1"), ("ES256", "e1"), ("RS256", None)):
    try:
        c = pruefen(signieren(claims(), alg=alg, kid=kid))
        _pk.append(c.get("preferred_username") == "m.muster")
    except Exception as e:  # noqa: BLE001
        print("  (Positivkontrolle %s/%s: %s)" % (alg, kid, e))
        _pk.append(False)
if not all(_pk):
    print("ABBRUCH: gueltige Tokens werden abgewiesen – jede Abweisung waere trivial wahr.",
          file=sys.stderr)
    sys.exit(2)
pruefe(True, "RS256, PS256, ES256 und RS256 ohne kid werden angenommen")
pruefe(pruefen(signieren(claims(aud=[CID, "anderer"], azp=CID)))["aud"][0] == CID,
       "mehrere aud mit azp = Client-ID werden angenommen")

abschnitt("1b. Manipulationen werden abgewiesen")
abgewiesen(signieren(claims(), alg="none", kid=None), "alg=none", "signaturverfahren")
abgewiesen(signieren(claims(), alg="HS256"), "HS256 mit oeffentlichem Schluessel",
           "signaturverfahren")
_t = signieren(claims())
_k, _r, _s = _t.split(".")
_r2 = b64u(json.dumps(claims(preferred_username="admin")).encode())
abgewiesen(_k + "." + _r2 + "." + _s, "Nutzlast nach dem Signieren geaendert", "signatur")
abgewiesen(signieren(claims(), key=RSA2), "fremder Schluessel mit bekanntem kid", "signatur")
abgewiesen(signieren(claims(), kid="unbekannt"), "unbekanntes kid", "kein passender")
abgewiesen(signieren(claims(), alg="RS256", kid="e1"), "RS256 mit EC-Schluessel-kid",
           "")
abgewiesen(signieren(claims(iss="https://fremd.beispiel.de")), "fremder iss", "aussteller")
# Rechnername in anderer Schreibweise ist derselbe Aussteller (RFC 3986 3.2.2,
# IdP auf DEV 2026-11-18: Discovery klein, id_token gross) – alles andere exakt.
ISS_GROSS = ISS.replace("idp.beispiel.de", "IDP.Beispiel.DE")
try:
    _gross = pruefen(signieren(claims(iss=ISS_GROSS))).get("sub")
    _grund = ""
except O.OidcFehler as e:  # abgewiesen = FAIL, kein Absturz (sonst fehlt die Bilanz)
    _gross, _grund = None, str(e)
pruefe(ISS_GROSS != ISS and _gross == "x1",
       "iss mit grossgeschriebenem Rechnernamen wird angenommen" + (" – " + _grund if _grund else ""))
abgewiesen(signieren(claims(iss=ISS.replace("/oidc", "/OIDC"))), "iss mit anderer Schreibweise im PFAD", "aussteller")
abgewiesen(signieren(claims(iss=ISS + "/")), "iss mit Schraegstrich am Ende", "aussteller")
abgewiesen(signieren(claims(iss=ISS.replace("https://", "http://"))), "iss ueber http", "aussteller")
abgewiesen(signieren(claims(iss=ISS.replace("idp.beispiel.de", "idp.beispiel.de:8443"))),
           "iss mit anderem Port", "aussteller")
abgewiesen(signieren(claims(iss=ISS.replace("https://", "https://x@"))),
           "iss mit Anmeldedaten in der Adresse", "aussteller")
abgewiesen(signieren(claims(iss=ISS.replace("idp.beispiel.de", "idp.beispiel.de.fremd.de"))),
           "iss mit verlaengertem Rechnernamen", "aussteller")
abgewiesen(signieren(claims(iss=ISS + "?x=1")), "iss mit Abfrage", "aussteller")
abgewiesen(signieren(claims(aud="andere-app")), "fremde aud", "andere anwendung")
abgewiesen(signieren(claims(aud=[CID, "anderer"])), "mehrere aud ohne azp", "azp")
abgewiesen(signieren(claims(azp="andere-app")), "azp einer anderen App", "azp")
abgewiesen(signieren(claims(exp=int(time.time()) - 3600)), "abgelaufen", "abgelaufen")
abgewiesen(signieren(claims(exp=None)), "ohne exp", "exp")
abgewiesen(signieren(claims(nbf=int(time.time()) + 3600)), "nbf in der Zukunft", "nbf")
abgewiesen(signieren(claims(iat=int(time.time()) + 3600)), "iat in der Zukunft", "iat")
abgewiesen(signieren(claims(nonce="fremd")), "falsche nonce", "nonce")
abgewiesen(signieren(claims(nonce=None)), "ohne nonce", "nonce")
abgewiesen(signieren(claims()), "leere erwartete nonce", "nonce", nonce="")
abgewiesen(signieren(claims(), kopf_extra={"crit": ["x"]}), "crit-Erweiterung", "crit")
abgewiesen("a.b", "kein JWT", "drei teile")
_alt = O.UHR_TOLERANZ_S
pruefe(_alt <= 300, "Uhrentoleranz hoechstens 5 Minuten (%s s)" % _alt)
_kurz = signieren(claims(exp=int(time.time()) - 30))
try:
    pruefen(_kurz)
    pruefe(True, "30 s abgelaufen liegt in der Toleranz")
except O.OidcFehler as e:
    pruefe(False, "30 s abgelaufen liegt in der Toleranz (%s)" % e)

abschnitt("1c. Kontoname aus dem Token")
DOM = O.domaenen_aus("firma.local", "firma.de, @beispiel.de")
pruefe(DOM == {"firma.local", "firma", "firma.de", "beispiel.de"},
       "erlaubte Domaenen: AD-Domaene, Kurzform, Zusatz (%s)" % sorted(DOM))
for roh, erw in (("M.Muster", "m.muster"), ("m.muster@firma.local", "m.muster"),
                 ("FIRMA\\m.muster", "m.muster"), ("m.muster@FIRMA.DE", "m.muster")):
    try:
        k = O.konto_aus_claims({"preferred_username": roh}, "preferred_username", DOM)
        pruefe(k == erw, "%r -> %r" % (roh, k))
    except O.OidcFehler as e:
        pruefe(False, "%r angenommen (%s)" % (roh, e))
for roh, warum in (("m.muster@fremd.de", "fremde Domaene"), ("FREMD\\m.muster", "fremde Domaene"),
                   ("", "keinen Namen"), ("a b", "unzulaessig"), ("a/b", "unzulaessig"),
                   ("x@y@firma.local", "fremde Domaene")):
    try:
        O.konto_aus_claims({"preferred_username": roh}, "preferred_username", DOM)
        pruefe(False, "%r abgewiesen (%s)" % (roh, warum))
    except O.OidcFehler as e:
        pruefe(warum.lower() in str(e).lower(), "%r abgewiesen: %s" % (roh, e))
try:
    O.konto_aus_claims({"name": "x"}, "name", DOM)
    pruefe(False, "nicht zugelassener Claim abgewiesen")
except O.OidcFehler as e:
    pruefe(e.code == "konfiguration", "nicht zugelassener Claim abgewiesen")
try:
    O.konto_aus_claims({"preferred_username": ["a"]}, "preferred_username", DOM)
    pruefe(False, "Liste statt Text abgewiesen")
except O.OidcFehler:
    pruefe(True, "Liste statt Text abgewiesen")

abschnitt("1d. MFA-Nachweis")
pruefe(O.mfa_belegt({}, ""), "leerer Nachweis = keiner verlangt")
pruefe(O.mfa_belegt({"amr": ["pwd", "otp"]}, "amr=otp"), "amr-Liste enthaelt otp")
pruefe(not O.mfa_belegt({"amr": ["pwd"]}, "amr=otp"), "amr ohne otp -> nicht belegt")
pruefe(not O.mfa_belegt({}, "amr=otp"), "fehlender Claim -> nicht belegt")
pruefe(O.mfa_belegt({"acr": "mfa"}, "acr=mfa"), "acr gleich")
pruefe(not O.mfa_belegt({"acr": "mfa2"}, "acr=mfa"), "acr ungleich -> nicht belegt")
pruefe(not O.mfa_belegt({"amr": ["otp"]}, "kaputt"), "unlesbarer Nachweis -> nicht belegt")
pruefe(O.nachweis_gueltig("") and O.nachweis_gueltig("amr=otp")
       and not O.nachweis_gueltig("amr") and not O.nachweis_gueltig("a=b c"),
       "Eingabepruefung des Nachweises")

abschnitt("1e. Ablagen, PKCE, Browser-Bindung")
A = O.Ablage(ttl_s=60, max_eintraege=3)
k1 = A.neu({"x": 1})
pruefe(A.lesen(k1) == {"x": 1} and A.lesen(k1) == {"x": 1}, "lesen laesst den Eintrag stehen")
pruefe(A.nehmen(k1) == {"x": 1} and A.nehmen(k1) is None, "nehmen ist einmalig")
pruefe(A.nehmen("gibt-es-nicht") is None and A.nehmen("") is None, "unbekannt -> None")
k2 = A.neu({})
pruefe(A.fehlversuch(k2, 3) == 2 and A.fehlversuch(k2, 3) == 1 and A.fehlversuch(k2, 3) == 0
       and A.lesen(k2) is None, "drei Fehlversuche verbrauchen den Eintrag")
A2 = O.Ablage(ttl_s=0)
k3 = A2.neu({})
time.sleep(0.01)
pruefe(A2.nehmen(k3) is None, "abgelaufener Eintrag -> None")
A3 = O.Ablage(ttl_s=60, max_eintraege=3)
ks = [A3.neu({"i": i}) for i in range(5)]
pruefe(A3.lesen(ks[0]) is None and A3.lesen(ks[-1]) == {"i": 4}, "Obergrenze: Aelteste fallen heraus")
v, ch = O.pkce_paar()
pruefe(ch == b64u(hashlib.sha256(v.encode()).digest()) and len(v) >= 43, "PKCE S256 nach RFC 7636")
w, h = O.browser_bindung()
pruefe(O.bindung_passt(w, h) and not O.bindung_passt(w + "x", h)
       and not O.bindung_passt("", h), "Browser-Bindung: nur der eigene Cookie-Wert passt")

abschnitt("1f. Discovery und Weiterleitung")
DOC = {"issuer": ISS, "authorization_endpoint": ISS + "/auth", "token_endpoint": ISS + "/token",
       "jwks_uri": ISS + "/jwks"}
pruefe(O.pruefe_discovery(dict(DOC), ISS) is not None, "passendes Discovery-Dokument")
try:
    _doc_ok = O.pruefe_discovery(dict(DOC, issuer=ISS.replace("idp.beispiel.de", "IDP.beispiel.de")),
                                 ISS) is not None
except O.OidcFehler:
    _doc_ok = False
pruefe(_doc_ok, "Discovery mit grossgeschriebenem Rechnernamen wird angenommen")
for aend, text in (({"issuer": ISS + "/"}, "anderer issuer"),
                   ({"issuer": ISS.replace("/oidc", "/OIDC")}, "issuer mit anderer Schreibweise im Pfad"),
                   ({"token_endpoint": "http://idp.beispiel.de/token"}, "token_endpoint ohne https"),
                   ({"jwks_uri": ""}, "jwks_uri fehlt"),
                   ({"code_challenge_methods_supported": ["plain"]}, "kein PKCE S256")):
    try:
        O.pruefe_discovery(dict(DOC, **aend), ISS)
        pruefe(False, "Discovery abgewiesen: " + text)
    except O.OidcFehler:
        pruefe(True, "Discovery abgewiesen: " + text)
url = O.autorisierungs_url(DOC, CID, "https://jarvis.beispiel.de/api/login/oidc/callback",
                           "ST", "NO", "CH")
qs = parse_qs(urlparse(url).query)
pruefe(qs.get("response_type") == ["code"] and qs.get("code_challenge_method") == ["S256"]
       and qs.get("state") == ["ST"] and qs.get("nonce") == ["NO"]
       and qs.get("scope") == ["openid profile"], "Autorisierungsadresse: Code-Flow mit PKCE, state, nonce")

abschnitt("1g. Code-Tausch (httpx-Attrappe mit echter Signatur)")
_gesehen = {}


class _Antwort:
    def __init__(self, status, daten):
        self.status_code = status
        self.content = json.dumps(daten).encode()


class _Client:
    def __init__(self, **kw):
        _gesehen["kw"] = kw

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def post(self, url, data=None, headers=None):
        _gesehen.update(url=url, data=data, headers=headers)
        return _gesehen.get("antwort", _Antwort(200, {"id_token": "a.b.c"}))


import httpx  # noqa: E402
_alt_client = httpx.Client
httpx.Client = _Client
try:
    ctx = O.ssl_kontext(None)
    tok = O.code_tauschen(DOC, CID, "geh:eim", "CODE", "https://r/cb", "VER", ctx)
    pruefe(tok == "a.b.c", "id_token wird geliefert")
    pruefe(_gesehen["kw"].get("follow_redirects") is False, "Token-Endpunkt: keine Weiterleitungen")
    pruefe(_gesehen["kw"].get("verify") is ctx, "TLS-Kontext wird benutzt (kein verify=False)")
    erw = "Basic " + base64.b64encode(b"jarvis-test:geh%3Aeim").decode()
    pruefe(_gesehen["headers"].get("Authorization") == erw,
           "client_secret_basic mit URL-kodierten Teilen")
    pruefe(_gesehen["data"].get("code_verifier") == "VER" and "client_secret" not in _gesehen["data"],
           "Verifier im Rumpf, Geheimnis NICHT im Rumpf")
    O.code_tauschen(dict(DOC, token_endpoint_auth_methods_supported=["client_secret_post"]),
                    CID, "g", "C", "https://r/cb", "V", ctx)
    pruefe(_gesehen["data"].get("client_secret") == "g" and "Authorization" not in _gesehen["headers"],
           "nur client_secret_post angeboten -> Geheimnis im Rumpf")
    _gesehen["antwort"] = _Antwort(400, {"error": "invalid_grant"})
    try:
        O.code_tauschen(DOC, CID, "geheim-wert", "C", "https://r/cb", "V", ctx)
        pruefe(False, "Ablehnung des IdP wirft")
    except O.OidcFehler as e:
        pruefe("invalid_grant" in str(e) and "geheim-wert" not in str(e),
               "Ablehnung nennt den Fehler des IdP, nie das Geheimnis")
finally:
    httpx.Client = _alt_client
pruefe(ctx.verify_mode == __import__("ssl").CERT_REQUIRED and ctx.check_hostname,
       "TLS-Pruefung immer an")


# ═══ 2. main.py: geschnitten und ausgefuehrt ═════════════════════════════════
abschnitt("2. Endpunkte (geschnitten, ausgefuehrt)")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(MAIN)
FUNK = {n.name: n for n in BAUM.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
NOETIG = ("_oidc_schalter", "_oidc_konfig", "_oidc_redirect_uri", "_oidc_mfa_anerkennen",
          "_oidc_cookie", "_oidc_cookie_weg", "_oidc_zurueck", "oidc_callback",
          "oidc_einloesen", "_oidc_einloesen_ablauf", "oidc_start", "oidc_status",
          "_oidc_ad_modus", "oidc_einstellungen_lesen", "oidc_einstellungen_setzen")
for n in NOETIG:
    pruefe(n in FUNK, "%s existiert in main.py" % n)
if not all(n in FUNK for n in NOETIG):
    print("ABBRUCH: Funktionen fehlen – Rest nicht messbar.", file=sys.stderr)
    sys.exit(1)


def _dek(fn):
    return [ast.unparse(d) for d in fn.decorator_list]


def _konstante(name):
    """Modulkonstante aus main.py per AST – nicht abgetippt (Drift)."""
    for n in BAUM.body:
        if isinstance(n, ast.Assign) and any(getattr(z, "id", "") == name for z in n.targets):
            return ast.literal_eval(n.value)
    return None


AD_MODI = _konstante("_OIDC_AD_MODI")
pruefe(isinstance(AD_MODI, tuple) and AD_MODI[:1] == ("fallback",) and "zusaetzlich" in AD_MODI,
       "_OIDC_AD_MODI: Vorgabe 'fallback', daneben 'zusaetzlich'")


pruefe("app.get('/api/login/oidc/start')" in _dek(FUNK["oidc_start"])
       and "app.get('/api/login/oidc/callback')" in _dek(FUNK["oidc_callback"])
       and "app.post('/api/login/oidc/einloesen')" in _dek(FUNK["oidc_einloesen"]),
       "Routen start/callback (GET) und einloesen (POST)")
pruefe(not any(isinstance(a, ast.Call) and getattr(a.func, "id", "") == "Depends"
               for n in ("oidc_start", "oidc_callback", "oidc_einloesen", "_oidc_einloesen_ablauf")
               for a in ast.walk(FUNK[n])),
       "Anmeldewege ohne Dependency")
_aufr = {ast.unparse(n.func) for n in ast.walk(FUNK["oidc_einloesen"]) if isinstance(n, ast.Call)}
pruefe("_anmeldung_protokollieren" in _aufr, "einloesen protokolliert jeden Ausgang (BSI M2)")


# Attrappen
class JSONResponse:
    def __init__(self, content, status_code=200, headers=None, **kw):
        self.status_code = status_code
        self.body = json.dumps(content).encode()
        self.headers = dict(headers or {})
        self.cookies = {}

    def set_cookie(self, name, wert, **kw):
        self.cookies[name] = (wert, kw)

    def delete_cookie(self, name, **kw):
        self.cookies[name] = (None, kw)


class RedirectResponse(JSONResponse):
    def __init__(self, url, status_code=307, **kw):
        super().__init__({}, status_code=status_code)
        self.headers["location"] = url


_fr = types.ModuleType("fastapi.responses")
_fr.RedirectResponse = RedirectResponse
_fr.JSONResponse = JSONResponse
sys.modules.setdefault("fastapi", types.ModuleType("fastapi"))
sys.modules["fastapi.responses"] = _fr


class _Req:
    def __init__(self, query=None, cookies=None, body=None):
        self.query_params = dict(query or {})
        self.cookies = dict(cookies or {})
        self.client = types.SimpleNamespace(host="192.0.2.7")
        self.base_url = "https://jarvis.beispiel.de/"
        self._body = body or {}


class AuthStateUnlesbar(RuntimeError):
    pass


def _ns(einst, *, freigabe="ja", gesperrt=None, lizenz=True, auth_state=None,
        admin=False, pflicht=True, totp_ok=True, block=None, log=None):
    log = log if log is not None else {}
    log.setdefault("token", [])
    log.setdefault("versuche", [])
    log.setdefault("sicherheit", [])
    log.setdefault("kontext", [])
    log.setdefault("gespeichert", {})
    cfg = types.SimpleNamespace(get_setting=lambda k, d=None: einst.get(k, d),
                                save_setting=lambda k, v: log["gespeichert"].__setitem__(k, v))
    lic = types.ModuleType("backend.license_enforce")
    lic.darf_benutzer_anmelden = lambda u: (lizenz, "" if lizenz else "Grenze")
    sys.modules["backend.license_enforce"] = lic
    import backend
    backend.license_enforce = lic

    async def _json_objekt(req):
        return req._body

    async def _brk(u, c):
        return (totp_ok, "" if totp_ok else "falsch")

    ns = {
        "config": cfg, "JSONResponse": JSONResponse, "asyncio": asyncio, "Request": _Req,
        "print": lambda *a, **k: None, "ALLOWED_USERS": {"jarvis"},
        "_norm_login": lambda n: (n or "").split("@")[0].split("\\")[-1].strip().lower(),
        "_check_rate_limit": lambda ip: True,
        "_konto_sperre_antwort": lambda u: gesperrt,
        "_ad_windows_freigabe": lambda u: (log.setdefault("freigabe", []).append(u), freigabe)[1],
        "_sicherheits_log": types.SimpleNamespace(
            ereignis=lambda art, **kw: log["sicherheit"].append((art, kw))),
        "_record_login_attempt": lambda ip, u="": log["versuche"].append(u),
        "_json_objekt": _json_objekt,
        "_get_user_auth_state": lambda u: dict(auth_state or {}),
        "_totp_im_broker": lambda s: s == "broker",
        "_totp_broker_pruefen": _brk,
        "_totp_broker_fehlertext": lambda g: "Code falsch",
        "_totp_secret_lesbar": lambda s: True,
        "_totp_schutz": types.SimpleNamespace(OK="ok", pruefen=lambda u, s, c: "ok" if (totp_ok and c == "123456") else "falsch"),
        "_totp_fehlertext": lambda e: "Code falsch",
        "generate_token": lambda u, **kw: (log["token"].append((u, kw)), "TOK")[1],
        "_anmelde_schutz": types.SimpleNamespace(erfolg=lambda u: None),
        "_user_sessions": types.SimpleNamespace(record_login=lambda *a, **k: None),
        "_display_name": lambda u: u,
        "_sitzung_kontext": types.SimpleNamespace(set=log["kontext"].append),
        "_is_admin_user": lambda u: admin,
        "_admin_2fa_pflicht": lambda: pflicht,
        "security_guard": types.SimpleNamespace(get_block=lambda u: block),
        "_sitzung_antwort": lambda req, daten: JSONResponse(daten),
        "AuthStateUnlesbar": AuthStateUnlesbar,
        "_OIDC_COOKIE_VORGANG": "__Host-jarvis_oidc",
        "_OIDC_COOKIE_SCHEIN": "__Host-jarvis_oidc_schein",
        "_OIDC_AD_MODI": AD_MODI,
        "_OIDC_TEXTFELDER": _konstante("_OIDC_TEXTFELDER"),
        "Depends": lambda f=None: None, "require_local_auth": None,
        "_note_activity": lambda u, r: None,
        "_sprot_angaben": lambda **kw: None,
    }
    for n in ("_oidc_schalter", "_oidc_konfig", "_oidc_redirect_uri", "_oidc_mfa_anerkennen",
              "_oidc_cookie", "_oidc_cookie_weg", "_oidc_zurueck", "oidc_callback",
              "_oidc_einloesen_ablauf", "_oidc_ad_modus", "oidc_status",
              "oidc_einstellungen_lesen", "oidc_einstellungen_setzen"):
        fn = FUNK[n]
        fn2 = ast.FunctionDef(name=fn.name, args=fn.args, body=fn.body, decorator_list=[],
                              returns=None, type_params=[]) if isinstance(fn, ast.FunctionDef) else \
            ast.AsyncFunctionDef(name=fn.name, args=fn.args, body=fn.body, decorator_list=[],
                                 returns=None, type_params=[])
        mod = ast.fix_missing_locations(ast.Module(body=[fn2], type_ignores=[]))
        exec(compile(mod, "main.py", "exec"), ns)  # noqa: S102
    return ns, log


EINST = {"oidc_aktiv": True, "oidc_issuer": ISS, "oidc_client_id": CID,
         "oidc_client_secret": "geheim", "ad_server": "dc.beispiel", "ad_domain": "firma.local"}

# Netz des Moduls durch Attrappen ersetzen; die Token-Pruefung bleibt ECHT.
O.discovery = lambda issuer, ctx, neu=False: DOC
O.jwks = lambda uri, ctx, neu=False: JWKS
_tausch = {"tok": None}
O.code_tauschen = lambda doc, cid, sec, code, ru, ver, ctx: _tausch["tok"]


def _vorgang(nonce=NONCE):
    w, h = O.browser_bindung()
    st = O.VORGAENGE.neu({"nonce": nonce, "verifier": "v", "bindung": h,
                          "redirect_uri": "https://r/cb", "issuer": ISS, "client_id": CID})
    return st, w


def _callback(tok=None, query_extra=None, cookie=True, state=None, einst=None, **kw):
    ns, log = _ns(einst or EINST, **kw)
    st, w = _vorgang()
    _tausch["tok"] = tok if tok is not None else signieren(claims())
    q = {"state": state if state is not None else st, "code": "C"}
    q.update(query_extra or {})
    resp = asyncio.run(ns["oidc_callback"](_Req(q, {"__Host-jarvis_oidc": w} if cookie else {})))
    return resp, log


def _ziel(resp):
    return resp.headers.get("location", "")


r, log = _callback()
pruefe(r.status_code == 303 and _ziel(r) == "/?anmeldung=idp", "Erfolg: 303 auf /?anmeldung=idp")
schein = (r.cookies.get("__Host-jarvis_oidc_schein") or (None, {}))
pruefe(bool(schein[0]) and schein[1].get("httponly") and schein[1].get("secure")
       and schein[1].get("samesite") == "lax", "Einloese-Schein im HttpOnly-/Secure-Cookie (Lax)")
pruefe(schein[0] not in _ziel(r), "Schein steht NICHT in der Adresse")
pruefe(r.cookies.get("__Host-jarvis_oidc", ("x",))[0] is None, "Vorgangs-Cookie wird geloescht")
pruefe(log.get("freigabe") == ["m.muster"], "Freigabe ueber das Dienstkonto mit dem normierten Namen")

r, log = _callback(state="erfunden")
pruefe(_ziel(r) == "/?idp_fehler=abgelaufen" and not log.get("freigabe"),
       "unbekannter state -> abgelaufen, keine Freigabepruefung")
r, log = _callback(cookie=False)
pruefe(_ziel(r) == "/?idp_fehler=abgelaufen", "Vorgang ohne Browser-Cookie -> abgewiesen (Login-CSRF)")
ns, _ = _ns(EINST)
st, w = _vorgang()
_tausch["tok"] = signieren(claims())
asyncio.run(ns["oidc_callback"](_Req({"state": st, "code": "C"}, {"__Host-jarvis_oidc": w})))
r2 = asyncio.run(ns["oidc_callback"](_Req({"state": st, "code": "C"}, {"__Host-jarvis_oidc": w})))
pruefe(_ziel(r2) == "/?idp_fehler=abgelaufen", "derselbe state ein zweites Mal -> abgewiesen")
r, log = _callback(query_extra={"error": "access_denied"})
pruefe(_ziel(r) == "/?idp_fehler=abgebrochen", "Fehler des IdP -> abgebrochen")
r, log = _callback(tok=signieren(claims(nonce="fremd")))
pruefe(_ziel(r) == "/?idp_fehler=token" and not log["versuche"],
       "ungueltiges Token -> Fehler, KEIN Fehlversuch des Kontos")
r, log = _callback(tok=signieren(claims(preferred_username="JARVIS")))
pruefe(_ziel(r) == "/?idp_fehler=lokal" and not log.get("freigabe"),
       "Name 'JARVIS' (lokales Konto) -> abgewiesen")
r, log = _callback(tok=signieren(claims(preferred_username="firma\\jarvis")))
pruefe(_ziel(r) == "/?idp_fehler=lokal", "Name 'firma\\jarvis' -> abgewiesen")
r, log = _callback(gesperrt=JSONResponse({}, 423))
pruefe(_ziel(r) == "/?idp_fehler=gesperrt", "gesperrtes Konto -> abgewiesen")
r, log = _callback(freigabe="fehler")
pruefe(_ziel(r) == "/?idp_fehler=pruefung" and "__Host-jarvis_oidc_schein" not in r.cookies,
       "Freigabe nicht pruefbar -> kein Schein (fail-closed)")
r, log = _callback(freigabe="nein")
pruefe(_ziel(r) == "/?idp_fehler=keine_freigabe", "keine Freigabe -> abgewiesen")
r, log = _callback(lizenz=False)
pruefe(_ziel(r) == "/?idp_fehler=lizenz", "Lizenzgrenze -> abgewiesen")
r, log = _callback(einst=dict(EINST, oidc_aktiv=False))
pruefe(_ziel(r) == "/?idp_fehler=nicht_eingerichtet", "IdP-Anmeldung aus -> nicht eingerichtet")
r, log = _callback(einst=dict(EINST, ad_server=""))
pruefe(_ziel(r) == "/?idp_fehler=nicht_eingerichtet", "ohne AD -> nicht eingerichtet")
r, log = _callback(einst=dict(EINST, oidc_client_secret="JGS1:verpackt"))
pruefe(_ziel(r) == "/?idp_fehler=nicht_eingerichtet", "verpacktes, unlesbares Secret -> nicht eingerichtet")
pruefe(any(a == "anmeldung_fehlgeschlagen" and kw.get("weg") == "oidc" for a, kw in log["sicherheit"]),
       "Fehlschlag steht im Sicherheitsprotokoll (weg=oidc)")


def _einloesen(schein_daten=None, body=None, einst=None, schein_id=None, **kw):
    ns, log = _ns(einst or EINST, **kw)
    sid = schein_id or O.SCHEINE.neu(schein_daten or {"konto": "m.muster", "mfa_belegt": False})
    resp = asyncio.run(ns["_oidc_einloesen_ablauf"](
        _Req(cookies={"__Host-jarvis_oidc_schein": sid}, body=body)))
    return resp, json.loads(resp.body), log, sid


r, d, log, sid = _einloesen()
pruefe(r.status_code == 200 and d.get("success") and log["token"] == [("m.muster", {"mit_2fa": False})],
       "ohne 2FA-Konto: Sitzung ohne zweiten Faktor")
r, d, log, _ = _einloesen(schein_id=sid)
pruefe(r.status_code == 401 and d.get("abgelaufen") and not log["token"], "Schein ist einmalig")
r, d, log, _ = _einloesen(schein_id="erfunden")
pruefe(r.status_code == 401 and not log["token"], "unbekannter Schein -> 401")

TOTP = {"totp_enabled": True, "totp_secret": "S"}
r, d, log, sid = _einloesen(auth_state=TOTP)
pruefe(d.get("requires_totp") and not log["token"], "Konto mit 2FA, MFA nicht anerkannt -> Code verlangt")
r, d, log, _ = _einloesen(auth_state=TOTP, schein_id=sid, body={"totp_code": "123456"})
pruefe(d.get("success") and log["token"] == [("m.muster", {"mit_2fa": True})],
       "richtiger Code -> Sitzung MIT zweitem Faktor")
r, d, log, sid = _einloesen(auth_state=TOTP, body={"totp_code": "000000"})
pruefe(r.status_code == 401 and d.get("requires_totp") and log["versuche"] == ["m.muster"],
       "falscher Code -> 401, zaehlt als Fehlversuch des Kontos")
_einloesen(auth_state=TOTP, schein_id=sid, body={"totp_code": "000000"})
r, d, log, _ = _einloesen(auth_state=TOTP, schein_id=sid, body={"totp_code": "000000"})
pruefe(d.get("abgelaufen") and not d.get("requires_totp"), "dritter falscher Code verbraucht den Schein")
r, d, log, _ = _einloesen(auth_state=TOTP, schein_id=sid, body={"totp_code": "123456"})
pruefe(not log["token"], "danach hilft auch der richtige Code nicht mehr")

MFA_AN = dict(EINST, oidc_mfa_anerkennen=True)
r, d, log, _ = _einloesen({"konto": "m.muster", "mfa_belegt": True}, einst=MFA_AN, auth_state=TOTP)
pruefe(d.get("success") and log["token"] == [("m.muster", {"mit_2fa": True})],
       "MFA anerkannt und belegt -> kein Code, Sitzung mit zweitem Faktor")
r, d, log, _ = _einloesen({"konto": "m.muster", "mfa_belegt": False}, einst=MFA_AN, auth_state=TOTP)
pruefe(d.get("requires_totp") and not log["token"], "MFA anerkannt, aber NICHT belegt -> Code verlangt")
MFA_AUS = dict(EINST, oidc_mfa_anerkennen=False)
r, d, log, _ = _einloesen({"konto": "m.muster", "mfa_belegt": True}, einst=MFA_AUS, auth_state=TOTP)
pruefe(d.get("requires_totp"), "MFA belegt, aber Schalter ausdruecklich AUS -> Code verlangt")
# Festlegung 2026-11-18: ohne Eintrag zaehlt die IdP-Anmeldung als zweiter Faktor –
# auch fuer Administratoren bei 2FA-Pflicht, auch fuer ein Konto mit eigenem Code.
r, d, log, _ = _einloesen({"konto": "m.muster", "mfa_belegt": True}, auth_state=TOTP,
                          admin=True, pflicht=True)
pruefe(d.get("success") and d.get("is_admin") is True and not d.get("requires_totp")
       and log["token"] == [("m.muster", {"mit_2fa": True})],
       "Vorgabe: Admin bei 2FA-Pflicht nach IdP-Anmeldung ohne eigenen Code mit Admin-Rechten")
r, d, log, _ = _einloesen({"konto": "m.muster", "mfa_belegt": True}, einst=MFA_AUS,
                          admin=True, pflicht=True)
pruefe(d.get("is_admin") is False, "Schalter AUS: Admin ohne eigenen Code bekommt keine Admin-Rechte")

r, d, log, _ = _einloesen(admin=True, pflicht=True)
pruefe(d.get("success") and d.get("is_admin") is False and d.get("hinweis")
       and log["kontext"] == [("m.muster", False, False)],
       "Admin ohne 2FA bei Pflicht: Sitzung OHNE Admin-Rechte, mit Hinweis")
r, d, log, _ = _einloesen({"konto": "m.muster", "mfa_belegt": True}, einst=MFA_AN,
                          admin=True, pflicht=True)
pruefe(d.get("is_admin") is True and log["kontext"] == [("m.muster", True, False)],
       "Admin mit anerkannter MFA: Admin-Rechte")
r, d, log, _ = _einloesen(gesperrt=JSONResponse({"error": "gesperrt"}, 423))
pruefe(r.status_code == 423 and not log["token"], "gesperrtes Konto beim Einloesen -> keine Sitzung")
r, d, log, _ = _einloesen(einst=dict(EINST, oidc_aktiv=False))
pruefe(r.status_code == 401 and not log["token"], "IdP-Anmeldung inzwischen aus -> keine Sitzung")
r, d, log, _ = _einloesen(block={"reason": "x", "incidents": []}, admin=True, pflicht=False)
pruefe(d.get("account_blocked") and d.get("is_admin") is False, "gesperrter Account (Sicherheit): nur Sperrhinweis")


# ═══ 3. Bestandsschutz und Begleitstellen ════════════════════════════════════
abschnitt("3. Bestandsschutz")
pruefe("login" in FUNK and "app.post('/api/login')" in _dek(FUNK["login"])
       and "_login_ablauf" in FUNK, "Kennwortanmeldung /api/login unveraendert vorhanden")
pruefe("login_windows" in FUNK, "Windows-Anmeldung unveraendert vorhanden")
_login_aufr = {ast.unparse(n.func) for n in ast.walk(FUNK["_login_ablauf"]) if isinstance(n, ast.Call)}
pruefe(not any("oidc" in a for a in _login_aufr), "die Kennwortanmeldung ruft nichts aus dem IdP-Weg")
# Vollstaendige Konfiguration OHNE den Schalter: sonst waere "aus" schon wegen
# des fehlenden Issuers wahr (Gegenprobe "Vorgabe an" blieb damit stumm).
_ohne_schalter = {k: v for k, v in EINST.items() if k != "oidc_aktiv"}
ns, _ = _ns(_ohne_schalter)
pruefe(ns["_oidc_konfig"]() is None, "Vorgabe: IdP-Anmeldung AUS (vollstaendige Konfiguration ohne Schalter)")
ns, _ = _ns(dict(_ohne_schalter, oidc_aktiv=True))
pruefe(ns["_oidc_konfig"]() is not None, "Positivkontrolle: mit Schalter ist dieselbe Konfiguration wirksam")
pruefe(ns["_oidc_mfa_anerkennen"]() is True,
       "Vorgabe: Anmeldung ueber den IdP zaehlt als zweiter Faktor (Festlegung 2026-11-18)")
ns, _ = _ns(dict(EINST, oidc_mfa_anerkennen=False))
pruefe(ns["_oidc_mfa_anerkennen"]() is False, "ausdruecklich aus bleibt aus")

abschnitt("3b. Kennwortanmeldung neben dem IdP (oidc_ad_modus)")
for wert, soll in ((None, "fallback"), ("zusaetzlich", "zusaetzlich"), (" Zusaetzlich ", "zusaetzlich"),
                   ("fallback", "fallback"), ("immer", "fallback"), ("", "fallback")):
    ns, _ = _ns(dict(EINST, **({} if wert is None else {"oidc_ad_modus": wert})))
    pruefe(ns["_oidc_ad_modus"]() == soll, "ad_modus %r -> %r" % (wert, soll))
ns, _ = _ns(EINST)
d = json.loads(asyncio.run(ns["oidc_status"]()).body)
pruefe(d == {"aktiv": True, "ad_modus": "fallback"}, "Status: aktiv + Vorgabe fallback", )
ns, _ = _ns(dict(EINST, oidc_ad_modus="zusaetzlich"))
d = json.loads(asyncio.run(ns["oidc_status"]()).body)
pruefe(d == {"aktiv": True, "ad_modus": "zusaetzlich"}, "Status: zusaetzlich")
ns, _ = _ns(dict(EINST, oidc_aktiv=False, oidc_ad_modus="zusaetzlich"))
d = json.loads(asyncio.run(ns["oidc_status"]()).body)
pruefe(d == {"aktiv": False}, "Status bei ausgeschaltetem IdP unveraendert {aktiv: false}")


def _setzen(body, einst=None):
    ns, log = _ns(einst or EINST)
    r = asyncio.run(ns["oidc_einstellungen_setzen"](_Req(body=body), "admin"))
    return r, json.loads(r.body), log["gespeichert"]


r, d, gesp = _setzen({"oidc_ad_modus": "zusaetzlich"})
pruefe(r.status_code == 200 and gesp.get("oidc_ad_modus") == "zusaetzlich", "Speichern: zusaetzlich")
r, d, gesp = _setzen({"oidc_ad_modus": "fallback"})
pruefe(r.status_code == 200 and gesp.get("oidc_ad_modus") == "fallback", "Speichern: fallback")
for falsch in ("immer", True, "", None, ["zusaetzlich"]):
    r, d, gesp = _setzen({"oidc_ad_modus": falsch, "oidc_client_id": "x"})
    pruefe(r.status_code == 400 and not gesp, "Speichern abgewiesen (nichts geschrieben): %r" % (falsch,))
r, d, gesp = _setzen({"oidc_client_id": "x"})
pruefe(r.status_code == 200 and "oidc_ad_modus" not in gesp, "ohne Feld bleibt der Modus unberuehrt")
ns, _ = _ns(dict(EINST, oidc_ad_modus="zusaetzlich"))
d = json.loads(asyncio.run(ns["oidc_einstellungen_lesen"](_Req(), "admin")).body)
pruefe(d.get("oidc_ad_modus") == "zusaetzlich", "Lesen liefert den Modus")

from backend import zugang_regel as Z  # noqa: E402
for m, p in (("GET", "/api/login/oidc/status"), ("GET", "/api/login/oidc/start"),
             ("GET", "/api/login/oidc/callback"), ("POST", "/api/login/oidc/einloesen")):
    pruefe(Z.AUSNAHMEN.get((m, p), ("",))[0] == "anmeldung", "%s %s ist ein Anmeldeweg" % (m, p))
pruefe(not any(p.startswith("/api/admin/oidc") for _, p in Z.AUSNAHMEN),
       "Verwaltungsrouten stehen NICHT in der Freiliste")
for n in ("oidc_einstellungen_lesen", "oidc_einstellungen_setzen", "oidc_verbindung_testen",
          "anmeldeschutz_idp_mfa"):
    fn = FUNK.get(n)
    pruefe(fn is not None and any(isinstance(a, ast.Call) and ast.unparse(a) == "Depends(require_local_auth)"
                                  for a in ast.walk(fn)), "%s nur fuer Administratoren" % n)

from backend import geheimnis_tresor as G  # noqa: E402
pruefe(G.ist_geheimer_name("oidc_client_secret"), "oidc_client_secret ist ein Tresor-Feld (JGS1)")
_lesen = FUNK["oidc_einstellungen_lesen"]
_rueck = [n for n in ast.walk(_lesen) if isinstance(n, ast.Return)]
_rueck_text = " ".join(ast.unparse(n) for n in _rueck)
_textfelder = [n.value for n in BAUM.body if isinstance(n, ast.Assign)
               and any(getattr(t, "id", "") == "_OIDC_TEXTFELDER" for t in n.targets)]
pruefe(len(_textfelder) == 1 and "oidc_issuer" in ast.unparse(_textfelder[0])
       and "oidc_client_secret" not in ast.unparse(_textfelder[0]),
       "das Secret ist kein Textfeld der Rueckgabe")
pruefe("geheim" in _rueck_text and "client_secret_gesetzt" in _rueck_text
       and "'client_secret':" not in _rueck_text,
       "Lese-Endpunkt meldet nur, OB ein Secret hinterlegt ist")

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(0 if _fail == 0 else 1)
