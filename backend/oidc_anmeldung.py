"""Anmeldung ueber den IdP per OpenID Connect – nur die Pruefung, keine Sitzung.

**Warum es das gibt (2026-11-17):** Der Administrator hat die Nutzung des
Identity Providers (IdP) freigegeben. Bisher lief die Anmeldung per
LDAP-Simple-Bind, das Kennwort ging also durch den Jarvis-Dienst. Mit OIDC
sieht Jarvis das Kennwort nie; Kennwort und Mehrfaktor prueft der IdP.
Plan und Entscheidungen: ``docs/plan-oidc-anmeldung.md``.

VERFAHREN: Authorization Code mit PKCE (S256), vertraulicher Client
-------------------------------------------------------------------
1. ``/api/login/oidc/start`` legt ``state``, ``nonce`` und PKCE-Verifier ab
   (``VORGAENGE``) und bindet den Vorgang per Cookie an den Browser.
2. Der IdP schickt den Browser mit ``code`` und ``state`` zurueck.
3. Der Code wird gegen das ``id_token`` getauscht (``code_tauschen_voll``), das
   Token geprueft (``pruefe_id_token``) und der Kontoname abgeleitet
   (``konto_aus_claims``).
4. Zugangsdaten fuer Jira/Confluence/SAP/VEMAS, falls der IdP sie als Claims
   mitliefert (``zugaenge_aus_claims``, sonst ``userinfo``).
5. Abmelden (2026-11-27): ``abmelde_url`` baut die Adresse fuer die
   RP-initiierte Abmeldung am IdP (``end_session_endpoint``, OIDC RP-Initiated
   Logout 1.0); das ``id_token`` dafuer liegt je Browser in ``IDP_SITZUNGEN``.
   Nach dem Schliessen des Browsers kann der Browser nichts mehr an den IdP
   schicken – dort sorgt ``prompt=login`` beim naechsten Start dafuer, dass
   der IdP neu anmeldet statt seine alte Sitzung still weiterzubenutzen.

WAS GEPRUEFT WIRD – UND WARUM JEDER PUNKT NOETIG IST
-----------------------------------------------------
* **Signaturverfahren aus fester Liste.** ``none`` und ``HS*`` sind die
  klassische JWT-Umgehung (bei ``HS256`` mit dem OEFFENTLICHEN Schluessel als
  "Geheimnis" signiert ein Angreifer selbst).
* **Signatur** gegen den Schluessel aus dem JWKS des IdP; ``kty`` und ``alg``
  muessen zusammenpassen.
* **``iss``** exakt gleich dem konfigurierten Issuer – sonst waere ein Token
  eines anderen IdP gueltig.
* **``aud``** enthaelt die Client-ID; bei mehreren Empfaengern muss ``azp``
  die Client-ID sein. Sonst liesse sich ein Token einloesen, das fuer eine
  ANDERE Anwendung am selben IdP ausgestellt wurde.
* **``exp``/``nbf``/``iat``** mit kleiner Toleranz fuer Uhrenversatz.
* **``nonce``** gleich der beim Start abgelegten – gegen das Wiedereinspielen
  eines abgefangenen Tokens.
* **Discovery**: der ``issuer`` im Dokument muss der konfigurierte sein,
  alle Endpunkte nur ``https``. TLS wird IMMER geprueft (System-CAs, optional
  zusaetzlich ein hinterlegtes CA-Zertifikat ueber ``mcp_tls``).

WAS DIESES MODUL NICHT TUT
---------------------------
Es stellt **keine** Jarvis-Sitzung aus und kennt keine Freigaben. Es sagt nur:
"dieses Token gehoert zu Konto X". Lokales Konto, Kontosperre, AD-Freigabe,
Lizenz, 2FA und Sitzung entscheidet ``main.py`` – dieselbe Trennung wie bei
``kerberos_anmeldung.py`` und ``addin_sso.py``. Bewusst ohne Import von
``backend.config``: die Einstellungen kommen als Argument, damit ein Test das
Modul ohne Live-``settings.json`` pruefen kann.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import ssl
import threading
import time
from typing import Any
from urllib.parse import urlencode, urlparse, urlsplit, quote

# Erlaubte Signaturverfahren. NIE "none", NIE HS* (symmetrisch).
ALGORITHMEN = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512")
UHR_TOLERANZ_S = 60
HTTP_FRIST_S = 10.0
MAX_ANTWORT_BYTES = 512 * 1024
DISCOVERY_TTL_S = 3600
JWKS_TTL_S = 3600
JWKS_NEULADEN_ABSTAND_S = 60
VORGANG_TTL_S = 600
SCHEIN_TTL_S = 120
SCHEIN_MAX_VERSUCHE = 3
# Wie lange das id_token einer Sitzung fuer die Abmeldung (id_token_hint)
# vorgehalten wird. Faellt es heraus, meldet die Abmeldung ohne Hinweis ab
# (nur client_id) – der IdP fragt dann ggf. nach, statt still zu scheitern.
IDP_SITZUNG_TTL_S = 24 * 3600
MAX_EINTRAEGE = 2000
# Claims, aus denen der Kontoname kommen darf (feste Liste fuer die Maske).
NAMENSCLAIMS = ("preferred_username", "sub", "upn", "email", "samaccountname", "username")
# Erlaubte Zeichen eines Kontonamens NACH der Normierung (sAMAccountName ohne
# die im AD verbotenen Zeichen; kein Leerzeichen, kein Pfadtrenner).
_KONTO_RE = re.compile(r"^[\w.$-]{1,64}$", re.UNICODE)


class OidcFehler(Exception):
    """Die Anmeldung ueber den IdP ist gescheitert.

    ``code`` ist eine kurze Kennung fuer die Oberflaeche (uebersetzbar),
    die Meldung nennt fuer das Journal, WAS nicht stimmt."""

    def __init__(self, meldung: str, code: str = "token"):
        super().__init__(meldung)
        self.code = code


# ── Hilfen ──────────────────────────────────────────────────────────────────

def _b64url_dekodieren(teil: str) -> bytes:
    teil = (teil or "").strip()
    return base64.urlsafe_b64decode(teil + "=" * (-len(teil) % 4))


def _b64url(daten: bytes) -> str:
    return base64.urlsafe_b64encode(daten).rstrip(b"=").decode("ascii")


def _ist_https(url: str) -> bool:
    try:
        teile = urlparse(str(url or ""))
    except Exception:  # noqa: BLE001
        return False
    return teile.scheme == "https" and bool(teile.hostname)


def issuer_gleich(a: str, b: str) -> bool:
    """Gleicher Aussteller? Exakt – bis auf die Schreibweise des RECHNERNAMENS.

    OIDC verlangt fuer ``iss`` den exakten Zeichenvergleich. Ein IdP auf DEV
    (2026-11-18) meldet sich im Discovery-Dokument aber klein
    (``https://idp.firma.local/...``) und schreibt ins id_token GROSS
    (``https://IDP.firma.local/...``) – jede Anmeldung scheiterte mit
    "Fremder Aussteller". Der Rechnername ist nach RFC 3986 (3.2.2)
    unabhaengig von Gross-/Kleinschreibung, er bezeichnet denselben Server.
    Deshalb wird NUR er ohne Schreibweise verglichen; Schema, Port, Pfad,
    Abfrage und Fragment bleiben Zeichen fuer Zeichen gleich (ein anderer
    Pfad ist am selben Server ein anderer Aussteller), Anmeldedaten in der
    Adresse und alles ausser https werden abgewiesen.
    """
    a, b = str(a or ""), str(b or "")
    if not a or not b:
        return False
    if a == b:
        return True
    try:
        x, y = urlsplit(a), urlsplit(b)
        x_port, y_port = x.port, y.port
    except ValueError:
        return False
    if x.scheme != "https" or y.scheme != "https":
        return False
    if "@" in x.netloc or "@" in y.netloc or not x.hostname:
        return False
    # urlsplit liefert hostname bereits in Kleinbuchstaben.
    return (x.hostname == y.hostname and x_port == y_port and x.path == y.path
            and x.query == y.query and x.fragment == y.fragment)


def ssl_kontext(ca_cert: str | None) -> ssl.SSLContext:
    """TLS-Kontext fuer alle Abrufe beim IdP – die Pruefung ist IMMER an.

    Ohne hinterlegtes Zertifikat gilt der Systemspeicher (``/etc/ssl/certs``,
    dort liegt auch die Firmen-CA, wenn sie ausgerollt ist). Mit Zertifikat
    derselbe Weg wie bei den MCP-Servern (``mcp_tls``): zusaetzlich vertraut,
    nie ``verify=False``."""
    if str(ca_cert or "").strip():
        from backend import mcp_tls  # noqa: PLC0415
        try:
            ctx = mcp_tls.ssl_kontext(ca_cert)
        except Exception as e:  # noqa: BLE001
            raise OidcFehler("Das hinterlegte CA-Zertifikat des IdP ist nicht "
                             "verwendbar (%s)." % e, "konfiguration") from e
        if ctx is not None:
            return ctx
    ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def _antwort_json(resp) -> dict:
    """JSON einer httpx-Antwort mit Groessendeckel; wirft OidcFehler."""
    roh = resp.content or b""
    if len(roh) > MAX_ANTWORT_BYTES:
        raise OidcFehler("Antwort des IdP ist zu gross (%d Bytes)." % len(roh), "idp")
    try:
        d = json.loads(roh.decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        raise OidcFehler("Antwort des IdP ist kein JSON (HTTP %s)." % resp.status_code,
                         "idp") from e
    if not isinstance(d, dict):
        raise OidcFehler("Antwort des IdP ist kein JSON-Objekt.", "idp")
    return d


def _http_get_json(url: str, ctx: ssl.SSLContext) -> dict:
    if not _ist_https(url):
        raise OidcFehler("Adresse ist nicht https: %s" % url, "konfiguration")
    import httpx  # noqa: PLC0415
    try:
        with httpx.Client(verify=ctx, timeout=HTTP_FRIST_S, follow_redirects=False) as c:
            resp = c.get(url, headers={"Accept": "application/json"})
    except Exception as e:  # noqa: BLE001
        raise OidcFehler("IdP nicht erreichbar (%s: %s)." % (type(e).__name__, e),
                         "nicht_erreichbar") from e
    if resp.status_code != 200:
        raise OidcFehler("IdP antwortet mit HTTP %s auf %s." % (resp.status_code, url), "idp")
    return _antwort_json(resp)


# ── Discovery und Schluessel ────────────────────────────────────────────────

_cache_lock = threading.Lock()
_discovery_cache: dict[str, tuple[float, dict]] = {}
_jwks_cache: dict[str, tuple[float, list]] = {}
_jwks_zuletzt_geladen: dict[str, float] = {}


def discovery_url(issuer: str) -> str:
    return str(issuer or "").rstrip("/") + "/.well-known/openid-configuration"


def pruefe_discovery(doc: dict, issuer: str) -> dict:
    """Prueft ein Discovery-Dokument gegen den konfigurierten Issuer."""
    if not issuer_gleich(doc.get("issuer"), issuer):
        raise OidcFehler("Der Issuer im Discovery-Dokument (%r) weicht vom konfigurierten "
                         "(%r) ab." % (doc.get("issuer"), issuer), "konfiguration")
    for feld in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        if not _ist_https(doc.get(feld)):
            raise OidcFehler("Discovery-Dokument: %s fehlt oder ist nicht https." % feld,
                             "konfiguration")
    methoden = doc.get("code_challenge_methods_supported")
    if isinstance(methoden, list) and methoden and "S256" not in methoden:
        raise OidcFehler("Der IdP bietet kein PKCE mit S256 an.", "konfiguration")
    return doc


def discovery(issuer: str, ctx: ssl.SSLContext, *, neu: bool = False) -> dict:
    """Discovery-Dokument (zwischengespeichert)."""
    jetzt = time.time()
    with _cache_lock:
        ein = _discovery_cache.get(issuer)
        if ein and not neu and jetzt - ein[0] < DISCOVERY_TTL_S:
            return ein[1]
    doc = pruefe_discovery(_http_get_json(discovery_url(issuer), ctx), issuer)
    with _cache_lock:
        _discovery_cache[issuer] = (jetzt, doc)
    return doc


def jwks(uri: str, ctx: ssl.SSLContext, *, neu: bool = False) -> list:
    """Schluessel des IdP (zwischengespeichert). ``neu`` laedt hoechstens alle
    ``JWKS_NEULADEN_ABSTAND_S`` Sekunden – sonst loeste jedes Token mit
    erfundenem ``kid`` einen Abruf beim IdP aus."""
    jetzt = time.time()
    with _cache_lock:
        ein = _jwks_cache.get(uri)
        frisch = ein and jetzt - ein[0] < JWKS_TTL_S
        darf_neu = jetzt - _jwks_zuletzt_geladen.get(uri, 0.0) >= JWKS_NEULADEN_ABSTAND_S
        if ein and frisch and not (neu and darf_neu):
            return ein[1]
        if ein and neu and not darf_neu:
            return ein[1]
        _jwks_zuletzt_geladen[uri] = jetzt
    d = _http_get_json(uri, ctx)
    schluessel = d.get("keys")
    if not isinstance(schluessel, list):
        raise OidcFehler("JWKS des IdP enthaelt keine Schluesselliste.", "idp")
    with _cache_lock:
        _jwks_cache[uri] = (jetzt, schluessel)
    return schluessel


def caches_leeren() -> None:
    """Nach einer Konfigurationsaenderung: nichts Altes weiterverwenden."""
    with _cache_lock:
        _discovery_cache.clear()
        _jwks_cache.clear()
        _jwks_zuletzt_geladen.clear()


# ── PKCE und Weiterleitung ──────────────────────────────────────────────────

def pkce_paar() -> tuple[str, str]:
    """(verifier, challenge) nach RFC 7636, Verfahren S256."""
    verifier = secrets.token_urlsafe(48)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def autorisierungs_url(doc: dict, client_id: str, redirect_uri: str, state: str,
                       nonce: str, challenge: str, scope: str = "openid profile",
                       prompt: str = "") -> str:
    """``prompt="login"`` verlangt vom IdP eine NEUE Anmeldung, auch wenn er
    noch eine Sitzung hat (OIDC Core 3.1.2.1) – siehe ``oidc_start``."""
    ziel = str(doc["authorization_endpoint"])
    werte = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scope,
        "state": state,
        "nonce": nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    if prompt:
        werte["prompt"] = prompt
    param = urlencode(werte, quote_via=quote)
    return ziel + ("&" if "?" in ziel else "?") + param


def abmelde_url(doc: dict, client_id: str, ruecksprung: str, id_token: str = "") -> str | None:
    """Adresse fuer die Abmeldung am IdP (OIDC RP-Initiated Logout 1.0) oder
    None, wenn der IdP keine anbietet.

    Der Browser wird dorthin geschickt; der IdP beendet seine Sitzung und
    leitet auf ``ruecksprung`` zurueck (muss beim IdP als Abmelde-Rueckkehr
    eingetragen sein). ``id_token_hint`` nur, wenn das Token bekannt ist –
    ohne Hinweis traegt ``client_id`` die Zuordnung (Abschnitt 2 der Norm).
    Nur ``https``: die Adresse geht unveraendert als Navigationsziel an den
    Browser."""
    ziel = doc.get("end_session_endpoint")
    if not isinstance(ziel, str) or not _ist_https(ziel):
        return None
    werte = {"client_id": client_id}
    if ruecksprung:
        werte["post_logout_redirect_uri"] = ruecksprung
    if id_token:
        werte["id_token_hint"] = id_token
    return ziel + ("&" if "?" in ziel else "?") + urlencode(werte, quote_via=quote)


def code_tauschen(doc: dict, client_id: str, client_secret: str, code: str,
                  redirect_uri: str, verifier: str, ctx: ssl.SSLContext) -> str:
    """Nur das ``id_token`` – siehe ``code_tauschen_voll``."""
    return code_tauschen_voll(doc, client_id, client_secret, code, redirect_uri,
                              verifier, ctx)["id_token"]


def code_tauschen_voll(doc: dict, client_id: str, client_secret: str, code: str,
                       redirect_uri: str, verifier: str, ctx: ssl.SSLContext) -> dict:
    """Tauscht den Code gegen ``id_token`` und ``access_token`` (vertraulicher
    Client). Rueckgabe ``{"id_token": str, "access_token": str}`` – das
    Access-Token ist leer, wenn der IdP keines liefert; gebraucht wird es nur
    fuer ``userinfo`` (Zugangsdaten aus dem IdP).

    Client-Authentisierung: ``client_secret_basic``, ausser der IdP nennt nur
    ``client_secret_post``. Keine Weiterleitungen – eine Umleitung des
    Token-Endpunkts truege den Code samt Geheimnis an ein anderes Ziel."""
    import httpx  # noqa: PLC0415
    url = str(doc.get("token_endpoint") or "")
    if not _ist_https(url):
        raise OidcFehler("Token-Endpunkt ist nicht https.", "konfiguration")
    daten = {"grant_type": "authorization_code", "code": code,
             "redirect_uri": redirect_uri, "code_verifier": verifier}
    methoden = doc.get("token_endpoint_auth_methods_supported")
    nur_post = (isinstance(methoden, list) and "client_secret_basic" not in methoden
                and "client_secret_post" in methoden)
    kopf = {"Accept": "application/json"}
    if nur_post:
        daten.update({"client_id": client_id, "client_secret": client_secret})
    else:
        # RFC 6749 2.3.1: beide Teile vor dem Base64 URL-kodieren.
        roh = "%s:%s" % (quote(client_id, safe=""), quote(client_secret, safe=""))
        kopf["Authorization"] = "Basic " + base64.b64encode(roh.encode("utf-8")).decode("ascii")
    try:
        with httpx.Client(verify=ctx, timeout=HTTP_FRIST_S, follow_redirects=False) as c:
            resp = c.post(url, data=daten, headers=kopf)
    except Exception as e:  # noqa: BLE001
        raise OidcFehler("Token-Endpunkt nicht erreichbar (%s)." % type(e).__name__,
                         "nicht_erreichbar") from e
    d = _antwort_json(resp)
    if resp.status_code != 200:
        # Nur Fehlerkennung und -text des IdP, nie die Anfrage (enthaelt Geheimnis).
        raise OidcFehler("Token-Endpunkt lehnt ab (HTTP %s: %s %s)." % (
            resp.status_code, str(d.get("error") or "")[:60],
            str(d.get("error_description") or "")[:200]), "idp")
    tok = d.get("id_token")
    if not isinstance(tok, str) or tok.count(".") != 2:
        raise OidcFehler("Der IdP hat kein id_token geliefert.", "idp")
    zugang = d.get("access_token")
    return {"id_token": tok, "access_token": zugang if isinstance(zugang, str) else ""}


def userinfo(doc: dict, access_token: str, ctx: ssl.SSLContext, sub: str) -> dict:
    """Claims vom userinfo-Endpunkt (OIDC Core 5.3).

    **``sub`` muss dem des gepruefte id_token gleichen** (OIDC Core 5.3.2) –
    sonst koennte eine untergeschobene Antwort die Claims eines anderen
    Benutzers liefern. Ohne ``sub`` im id_token gibt es keine Antwort ({}).
    Wie beim Token-Endpunkt: nur https, keine Weiterleitungen (das
    Access-Token ginge sonst an ein anderes Ziel). Eine signierte Antwort
    (``application/jwt``) wird nicht ausgewertet – sie waere ohne eigene
    Pruefung nicht vertrauenswuerdiger als keine."""
    url = str(doc.get("userinfo_endpoint") or "")
    if not url or not access_token or not sub:
        return {}
    if not _ist_https(url):
        raise OidcFehler("userinfo-Endpunkt ist nicht https.", "konfiguration")
    import httpx  # noqa: PLC0415
    try:
        with httpx.Client(verify=ctx, timeout=HTTP_FRIST_S, follow_redirects=False) as c:
            resp = c.get(url, headers={"Accept": "application/json",
                                       "Authorization": "Bearer " + access_token})
    except Exception as e:  # noqa: BLE001
        raise OidcFehler("userinfo nicht erreichbar (%s)." % type(e).__name__,
                         "nicht_erreichbar") from e
    if resp.status_code != 200:
        raise OidcFehler("userinfo antwortet mit HTTP %s." % resp.status_code, "idp")
    d = _antwort_json(resp)
    if str(d.get("sub") or "") != sub:
        raise OidcFehler("userinfo gehoert zu einem anderen Benutzer (sub).", "token")
    return d


# ── Zugangsdaten aus dem IdP (Betreiber 2026-11-18) ─────────────────────────
#
# Persoenliche Zugaenge liegen NICHT auf dem Jarvis-Server (Schalter
# "Persoenliche Zugaenge erlauben" aus bzw. Kachel-Anmeldung bei SAP/VEMAS).
# Statt sie bei jeder Anmeldung einzutippen, pflegt der Betreiber sie im IdP;
# der liefert sie als Claims mit. Jarvis meldet damit fuer die SITZUNG an
# (Arbeitsspeicher, endet mit dem Abmelden) – geschrieben wird nichts.
# Die Namen sind fest vereinbart; Werte erscheinen nie in einem Protokoll.
ZUGANGSCLAIMS = {"jira": "jira_pat", "confluence": "confluence_pat",
                 "sap": "sap_pwd", "vemas": "vemas_pwd"}
MAX_ZUGANG_LAENGE = 4096


def zugaenge_aus_claims(claims: Any) -> dict[str, str]:
    """``{system: wert}`` fuer jeden vorhandenen, brauchbaren Zugangs-Claim.

    Brauchbar = nicht leere Zeichenkette ohne Zeilenumbruch, hoechstens
    ``MAX_ZUGANG_LAENGE`` Zeichen. Der Wert bleibt UNVERAENDERT (ein Kennwort
    darf mit einem Leerzeichen enden); alles andere wird still uebergangen –
    der Benutzer meldet sich dann wie bisher im zweiten Schritt an."""
    aus: dict[str, str] = {}
    if not isinstance(claims, dict):
        return aus
    for system, claim in ZUGANGSCLAIMS.items():
        wert = claims.get(claim)
        if (isinstance(wert, str) and wert.strip() and len(wert) <= MAX_ZUGANG_LAENGE
                and "\n" not in wert and "\r" not in wert):
            aus[system] = wert
    return aus


# ── Token-Pruefung ──────────────────────────────────────────────────────────

def _int_aus_b64(wert: str) -> int:
    return int.from_bytes(_b64url_dekodieren(wert), "big")


def _oeffentlicher_schluessel(jwk: dict, alg: str):
    """JWK -> cryptography-Schluessel; wirft OidcFehler bei unpassendem Typ."""
    from cryptography.hazmat.primitives.asymmetric import ec, rsa  # noqa: PLC0415
    kty = str(jwk.get("kty") or "")
    if alg[:2] in ("RS", "PS"):
        if kty != "RSA":
            raise OidcFehler("Schluesseltyp %r passt nicht zu %s." % (kty, alg))
        return rsa.RSAPublicNumbers(_int_aus_b64(jwk["e"]), _int_aus_b64(jwk["n"])).public_key()
    if alg[:2] == "ES":
        kurven = {"ES256": ("P-256", ec.SECP256R1()), "ES384": ("P-384", ec.SECP384R1()),
                  "ES512": ("P-521", ec.SECP521R1())}
        name, kurve = kurven[alg]
        if kty != "EC" or str(jwk.get("crv") or "") != name:
            raise OidcFehler("Schluessel %r/%r passt nicht zu %s." % (kty, jwk.get("crv"), alg))
        return ec.EllipticCurvePublicNumbers(_int_aus_b64(jwk["x"]), _int_aus_b64(jwk["y"]),
                                             kurve).public_key()
    raise OidcFehler("Signaturverfahren %s nicht unterstuetzt." % alg)


def _signatur_pruefen(alg: str, schluessel, signiert: bytes, signatur: bytes) -> bool:
    from cryptography.hazmat.primitives import hashes  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric import ec, padding, utils  # noqa: PLC0415
    hashfn = {"256": hashes.SHA256, "384": hashes.SHA384, "512": hashes.SHA512}[alg[2:]]()
    try:
        if alg.startswith("RS"):
            schluessel.verify(signatur, signiert, padding.PKCS1v15(), hashfn)
        elif alg.startswith("PS"):
            schluessel.verify(signatur, signiert,
                              padding.PSS(mgf=padding.MGF1(hashfn),
                                          salt_length=hashfn.digest_size), hashfn)
        else:
            # JWS-ES: r||s mit fester Laenge, cryptography erwartet DER.
            n = len(signatur) // 2
            if n == 0 or len(signatur) % 2:
                return False
            der = utils.encode_dss_signature(int.from_bytes(signatur[:n], "big"),
                                             int.from_bytes(signatur[n:], "big"))
            schluessel.verify(der, signiert, ec.ECDSA(hashfn))
        return True
    except Exception:  # noqa: BLE001
        return False


def _passende_schluessel(alle: list, kid: str, alg: str) -> list:
    """Kandidaten: mit ``kid`` genau die passenden; ohne ``kid`` alle zur
    Signatur geeigneten. ``use`` (falls gesetzt) muss ``sig`` sein, ``alg``
    (falls gesetzt) muss gleich sein."""
    treffer = []
    for k in alle if isinstance(alle, list) else []:
        if not isinstance(k, dict):
            continue
        if k.get("use") not in (None, "sig"):
            continue
        if k.get("alg") not in (None, alg):
            continue
        if kid and str(k.get("kid") or "") != kid:
            continue
        treffer.append(k)
    return treffer


def zerlegen(token: str) -> tuple[dict, dict, bytes, bytes]:
    """(kopf, rumpf, signierter Teil, Signatur); wirft OidcFehler."""
    teile = str(token or "").strip().split(".")
    if len(teile) != 3:
        raise OidcFehler("Das id_token hat nicht die Form eines JWT (drei Teile).")
    try:
        kopf = json.loads(_b64url_dekodieren(teile[0]))
        rumpf = json.loads(_b64url_dekodieren(teile[1]))
        signatur = _b64url_dekodieren(teile[2])
    except Exception as e:  # noqa: BLE001
        raise OidcFehler("Das id_token laesst sich nicht dekodieren.") from e
    if not isinstance(kopf, dict) or not isinstance(rumpf, dict):
        raise OidcFehler("Das id_token ist kein JSON-Objekt.")
    return kopf, rumpf, (teile[0] + "." + teile[1]).encode("ascii"), signatur


def pruefe_id_token(token: str, schluessel: list, *, issuer: str, client_id: str,
                    nonce: str, jetzt: float | None = None) -> dict:
    """Prueft das ``id_token`` vollstaendig und liefert die Claims.

    ``schluessel`` ist die JWKS-Liste. Wirft ``OidcFehler`` mit einem Text, der
    sagt, WAS nicht stimmt."""
    kopf, rumpf, signiert, signatur = zerlegen(token)
    alg = str(kopf.get("alg") or "")
    if alg not in ALGORITHMEN:
        raise OidcFehler("Unerlaubtes Signaturverfahren (alg=%r)." % alg)
    if kopf.get("crit"):
        raise OidcFehler("Das id_token verlangt unbekannte Erweiterungen (crit).")
    kid = str(kopf.get("kid") or "")
    kandidaten = _passende_schluessel(schluessel, kid, alg)
    if not kandidaten:
        raise OidcFehler("Kein passender Schluessel des IdP (kid=%r)." % kid, "schluessel")
    gueltig = False
    for k in kandidaten:
        try:
            pub = _oeffentlicher_schluessel(k, alg)
        except OidcFehler:
            continue
        except Exception:  # noqa: BLE001
            continue
        if _signatur_pruefen(alg, pub, signiert, signatur):
            gueltig = True
            break
    if not gueltig:
        raise OidcFehler("Die Signatur des id_token ist ungueltig.")

    if not issuer_gleich(rumpf.get("iss"), issuer):
        raise OidcFehler("Fremder Aussteller (iss=%r)." % rumpf.get("iss"))
    aud = rumpf.get("aud")
    empfaenger = aud if isinstance(aud, list) else [aud]
    if not client_id or client_id not in empfaenger:
        raise OidcFehler("Das id_token ist fuer eine andere Anwendung ausgestellt (aud).")
    if len(empfaenger) > 1 and rumpf.get("azp") != client_id:
        raise OidcFehler("Mehrere Empfaenger, aber azp ist nicht diese Anwendung.")
    if "azp" in rumpf and rumpf.get("azp") != client_id:
        raise OidcFehler("azp ist nicht diese Anwendung.")

    t = time.time() if jetzt is None else float(jetzt)
    exp = rumpf.get("exp")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool):
        raise OidcFehler("Das id_token hat keine Ablaufzeit (exp).")
    if t > exp + UHR_TOLERANZ_S:
        raise OidcFehler("Das id_token ist abgelaufen.")
    nbf = rumpf.get("nbf")
    if isinstance(nbf, (int, float)) and not isinstance(nbf, bool) and t + UHR_TOLERANZ_S < nbf:
        raise OidcFehler("Das id_token ist noch nicht gueltig (nbf).")
    iat = rumpf.get("iat")
    if isinstance(iat, (int, float)) and not isinstance(iat, bool) and t + UHR_TOLERANZ_S < iat:
        raise OidcFehler("Das id_token stammt aus der Zukunft (iat).")
    if not nonce or not secrets.compare_digest(str(rumpf.get("nonce") or ""), nonce):
        raise OidcFehler("Die nonce des id_token passt nicht zum Anmeldevorgang.")
    return rumpf


def domaenen_aus(ad_domain: str, zusatz: str = "") -> set[str]:
    """Erlaubte Domaenenangaben im Namen: die AD-Domaene, ihr erstes Glied
    (NetBIOS-Kurzform, ``firma`` zu ``firma.local``) und zusaetzlich
    eingetragene UPN-Suffixe (Komma/Zeile getrennt)."""
    erg: set[str] = set()
    d = str(ad_domain or "").strip().lower()
    if d:
        erg.add(d)
        erg.add(d.split(".")[0])
    for teil in re.split(r"[,\s]+", str(zusatz or "")):
        teil = teil.strip().lower().lstrip("@")
        if teil:
            erg.add(teil)
    return erg


def konto_aus_claims(claims: dict, claim: str, erlaubte_domaenen: set[str]) -> str:
    """Blosser, kleingeschriebener Kontoname aus dem gewaehlten Claim.

    ``name``, ``name@domaene`` und ``DOMAENE\\name`` werden angenommen – die
    Domaene muss aber zu ``erlaubte_domaenen`` gehoeren (sonst koennte ein
    Konto einer fremden Domaene mit gleichem Kurznamen die Identitaet eines
    eigenen Benutzers uebernehmen). Normiert wird wie bei der Kennwort-
    anmeldung (``benutzername.norm_login``)."""
    if claim not in NAMENSCLAIMS:
        raise OidcFehler("Namensclaim %r ist nicht zugelassen." % claim, "konfiguration")
    roh = claims.get(claim)
    if not isinstance(roh, str) or not roh.strip():
        raise OidcFehler("Das id_token enthaelt keinen Namen im Claim %r." % claim, "name")
    roh = roh.strip()
    if "\\" in roh:
        dom, _, name = roh.partition("\\")
        if "\\" in name or dom.strip().lower() not in erlaubte_domaenen:
            raise OidcFehler("Fremde Domaene im Namen (%r)." % roh, "name")
    elif "@" in roh:
        name, _, dom = roh.rpartition("@")
        if "@" in name or dom.strip().lower() not in erlaubte_domaenen:
            raise OidcFehler("Fremde Domaene im Namen (%r)." % roh, "name")
    else:
        name = roh
    try:
        from backend.benutzername import norm_login  # noqa: PLC0415
    except ImportError:  # Pruefstand ohne Paket
        def norm_login(n):  # type: ignore[no-redef]
            return (n or "").split("@")[0].split("\\")[-1].strip().lower()
    konto = norm_login(name)
    if not _KONTO_RE.match(konto):
        raise OidcFehler("Unzulaessiger Kontoname im id_token (%r)." % roh, "name")
    return konto


# ── Kurzlebige Ablagen (Vorgaenge und Einloese-Scheine) ─────────────────────

class Ablage:
    """Einmal-Eintraege mit Laufzeit, nur im Speicher.

    Ein Neustart verwirft laufende Anmeldungen – der Benutzer klickt dann
    erneut. Obergrenze, damit ein Angreifer mit vielen ``/start``-Aufrufen den
    Speicher nicht fuellt (die aeltesten fallen zuerst heraus)."""

    def __init__(self, ttl_s: int, max_eintraege: int = MAX_EINTRAEGE):
        self.ttl_s = ttl_s
        self.max = max_eintraege
        self._d: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def _aufraeumen(self, jetzt: float) -> None:
        for k in [k for k, (t, _) in self._d.items() if jetzt - t > self.ttl_s]:
            del self._d[k]
        while len(self._d) >= self.max:
            aeltester = min(self._d, key=lambda k: self._d[k][0])
            del self._d[aeltester]

    def neu(self, daten: dict) -> str:
        schluessel = secrets.token_urlsafe(32)
        jetzt = time.time()
        with self._lock:
            self._aufraeumen(jetzt)
            self._d[schluessel] = (jetzt, dict(daten))
        return schluessel

    def lesen(self, schluessel: str) -> dict | None:
        with self._lock:
            ein = self._d.get(str(schluessel or ""))
            if not ein:
                return None
            if time.time() - ein[0] > self.ttl_s:
                del self._d[schluessel]
                return None
            return dict(ein[1])

    def nehmen(self, schluessel: str) -> dict | None:
        """Lesen UND entfernen – ein zweiter Aufruf liefert None."""
        with self._lock:
            ein = self._d.pop(str(schluessel or ""), None)
        if not ein or time.time() - ein[0] > self.ttl_s:
            return None
        return dict(ein[1])

    def fehlversuch(self, schluessel: str, maximal: int) -> int:
        """Zaehlt einen Fehlversuch; ab ``maximal`` ist der Eintrag verbraucht.
        Liefert die verbleibenden Versuche."""
        with self._lock:
            ein = self._d.get(str(schluessel or ""))
            if not ein:
                return 0
            t, daten = ein
            n = int(daten.get("versuche", 0)) + 1
            if n >= maximal:
                del self._d[schluessel]
                return 0
            daten = dict(daten, versuche=n)
            self._d[schluessel] = (t, daten)
            return maximal - n


VORGAENGE = Ablage(VORGANG_TTL_S)
SCHEINE = Ablage(SCHEIN_TTL_S)
# Je Browser, der sich ueber den IdP angemeldet hat: das id_token fuer die
# Abmeldung. Schluessel steht im Sitzungs-Cookie ``__Host-jarvis_idp`` (main.py).
IDP_SITZUNGEN = Ablage(IDP_SITZUNG_TTL_S)


def browser_bindung() -> tuple[str, str]:
    """(Wert fuer das Cookie, Hash fuer die Ablage)."""
    wert = secrets.token_urlsafe(32)
    return wert, hashlib.sha256(wert.encode("ascii")).hexdigest()


def bindung_passt(cookie_wert: str, erwarteter_hash: str) -> bool:
    if not cookie_wert or not erwarteter_hash:
        return False
    ist = hashlib.sha256(str(cookie_wert).encode("utf-8", "replace")).hexdigest()
    return secrets.compare_digest(ist, str(erwarteter_hash))


def verbindung_testen(issuer: str, ca_cert: str | None) -> dict[str, Any]:
    """Fuer den Knopf "Verbindung testen": Discovery und JWKS abrufen.

    Liefert nur Angaben ohne Schutzbedarf (Endpunkte, Algorithmen, Anzahl
    Schluessel)."""
    ctx = ssl_kontext(ca_cert)
    doc = discovery(issuer, ctx, neu=True)
    keys = jwks(str(doc["jwks_uri"]), ctx, neu=True)
    algs = doc.get("id_token_signing_alg_values_supported") or []
    return {
        "issuer": doc.get("issuer"),
        "authorization_endpoint": doc.get("authorization_endpoint"),
        "token_endpoint": doc.get("token_endpoint"),
        "algorithmen": [a for a in algs if isinstance(a, str)][:10],
        "algorithmen_erlaubt": any(a in ALGORITHMEN for a in algs) if algs else None,
        "pkce": doc.get("code_challenge_methods_supported"),
        "schluessel": len(keys),
        "end_session_endpoint": bool(doc.get("end_session_endpoint")),
    }
