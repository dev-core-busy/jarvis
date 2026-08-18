#!/usr/bin/env python3
"""Waechter fuer die kennwortlose Anmeldung des Outlook-Add-ins.

Die Token werden hier ECHT signiert (eigenes RSA-Schluesselpaar + selbst
ausgestelltes X.509-Zertifikat) und das Metadaten-Dokument des Exchange wird
durch eine Attrappe ersetzt. Ein Test mit gefaelschter Signaturpruefung wuerde
genau den Punkt nicht pruefen, auf dem die ganze Sicherheit ruht.

Laeuft OHNE fastapi. ``backend.config`` wird ausdruecklich NICHT importiert –
der echte Import migriert Profile und schriebe die Live-``settings.json``
zurueck; der Test bricht mit **Exit 2** ab, wenn es doch geladen ist.
"""

import base64
import json
import re
import sys
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Sandkasten ──────────────────────────────────────────────────────────────
_stub = types.ModuleType("backend.config")


class _Cfg:
    def get_setting(self, key, vorgabe=None):
        return vorgabe

    def get_skill_states(self):
        return {}


_stub.config = _Cfg()
sys.modules["backend.config"] = _stub

from backend import addin_sso as sso  # noqa: E402

if getattr(sys.modules.get("backend.config"), "__file__", None):
    print("ABBRUCH: das ECHTE backend.config wurde geladen.", file=sys.stderr)
    sys.exit(2)

# Verknuepfungsdatei in einen Wegwerf-Ordner umbiegen – VOR dem ersten Schreiben.
import tempfile  # noqa: E402

_SAND = Path(tempfile.mkdtemp(prefix="addin_sso_"))
sso.LINK_DATEI = _SAND / "addin_links.json"
if not str(sso.LINK_DATEI).startswith(str(_SAND)):
    print("ABBRUCH: Sandkasten greift nicht.", file=sys.stderr)
    sys.exit(2)

_ok = _fail = 0


def pruefe(bed, text):
    global _ok, _fail
    if bed:
        _ok += 1
    else:
        _fail += 1
        print("  FAIL: %s" % text)


def abschnitt(t):
    print("\n── %s" % t)


# ── Schluessel und Zertifikat fuer die Attrappe ─────────────────────────────
from cryptography import x509  # noqa: E402
from cryptography.hazmat.primitives import hashes, serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric import padding, rsa  # noqa: E402
from cryptography.x509.oid import NameOID  # noqa: E402
import datetime  # noqa: E402


def _zertifikat():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "exchange.test.local")])
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    zert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(jetzt - datetime.timedelta(days=1))
            .not_valid_after(jetzt + datetime.timedelta(days=365))
            .sign(key, hashes.SHA256()))
    return key, zert


KEY, ZERT = _zertifikat()
KEY2, ZERT2 = _zertifikat()          # fremder Schluessel (Angreifer)
ZERT_B64 = base64.b64encode(ZERT.public_bytes(serialization.Encoding.DER)).decode()
X5T = base64.urlsafe_b64encode(ZERT.fingerprint(hashes.SHA1())).decode().rstrip("=")

AMURL = "https://exchange.test.local:443/autodiscover/metadata/json/1"
AUD = "https://jarvis.test.local/addin/taskpane.html"
UID = "53e925fa-76ba-45e1-be0f-4ef08b59d389@exchange.test.local"


def _b64(rohdaten: bytes) -> str:
    return base64.urlsafe_b64encode(rohdaten).decode().rstrip("=")


def token_bauen(kopf_extra=None, rumpf_extra=None, signier_key=None, appctx_als_text=False):
    kopf = {"typ": "JWT", "alg": "RS256", "x5t": X5T}
    kopf.update(kopf_extra or {})
    jetzt = int(time.time())
    appctx = {"msexchuid": UID, "version": "ExIdTok.V1", "amurl": AMURL}
    rumpf = {"aud": AUD, "iss": "00000002-0000-0ff1-ce00-000000000000@exchange.test.local",
             "nbf": str(jetzt - 60), "exp": str(jetzt + 3600),
             "appctx": json.dumps(appctx) if appctx_als_text else appctx}
    if rumpf_extra:
        for k, v in rumpf_extra.items():
            if k == "appctx" and isinstance(v, dict):
                basis = dict(appctx)
                basis.update(v)
                rumpf["appctx"] = json.dumps(basis) if appctx_als_text else basis
            else:
                rumpf[k] = v
    teil1 = _b64(json.dumps(kopf).encode())
    teil2 = _b64(json.dumps(rumpf).encode())
    signiert = ("%s.%s" % (teil1, teil2)).encode()
    key = signier_key or KEY
    sig = key.sign(signiert, padding.PKCS1v15(), hashes.SHA256())
    return "%s.%s.%s" % (teil1, teil2, _b64(sig))


# Metadaten-Abruf und Konfiguration durch Attrappen ersetzen.
_META = [{"usage": "signing", "keyinfo": {"x5t": X5T},
          "keyvalue": {"type": "x509Certificate", "value": ZERT_B64}}]
_meta_abrufe = {"n": 0}


def _fake_meta(amurl):
    _meta_abrufe["n"] += 1
    return list(_META)


sso._signaturschluessel = _fake_meta
sso.erlaubte_hosts = lambda: {"exchange.test.local"}

# ═══ 1. Der gute Fall ═══════════════════════════════════════════════════════
abschnitt("1. Gueltiges Token")
info = sso.pruefe_token(token_bauen(), AUD)
pruefe(bool(info.get("kennung")), "Kennung wird geliefert")
pruefe(info["msexchuid"] == UID, "Postfach-Kennung kommt durch")
pruefe(len(info["kennung"]) == 64, "Kennung ist ein SHA-256-Hex (%d)" % len(info["kennung"]))
pruefe(sso.pruefe_token(token_bauen(), AUD)["kennung"] == info["kennung"],
       "Kennung ist stabil – sonst waere die Verknuepfung nach jedem Start weg")
# appctx kommt je nach Exchange-Fassung als Objekt ODER als JSON-Text.
pruefe(sso.pruefe_token(token_bauen(appctx_als_text=True), AUD)["kennung"] == info["kennung"],
       "appctx als JSON-TEXT liefert dieselbe Kennung")
# Trailing slash und Gross/Kleinschreibung der Adresse duerfen nicht stoeren.
pruefe(sso.pruefe_token(token_bauen(), AUD + "/")["kennung"] == info["kennung"],
       "abschliessender Schraegstrich in der erwarteten Adresse stoert nicht")

# Die Kennung MUSS beide Anteile enthalten – msexchuid allein ist nur
# innerhalb EINES Exchange eindeutig.
pruefe(sso.kennung("a", "b") != sso.kennung("a", "c"),
       "andere Metadaten-Adresse => andere Kennung")
pruefe(sso.kennung("a", "b") != sso.kennung("x", "b"),
       "anderes Postfach => andere Kennung")
pruefe(UID not in sso.kennung(UID, AMURL),
       "die Rohkennung steht nicht in der gespeicherten Kennung")

# ═══ 2. Angriffe auf die Signatur ═══════════════════════════════════════════
abschnitt("2. Signatur")


def muss_scheitern(token, aud, text, teilstring=None):
    try:
        sso.pruefe_token(token, aud)
    except sso.SsoFehler as e:
        if teilstring and teilstring.lower() not in str(e).lower():
            pruefe(False, "%s – aber die Meldung nennt den Grund nicht: %s" % (text, e))
            return
        pruefe(True, text)
    except Exception as e:  # noqa: BLE001
        pruefe(False, "%s – falsche Ausnahmeart: %r" % (text, e))
    else:
        pruefe(False, "%s – WURDE AKZEPTIERT" % text)


muss_scheitern(token_bauen(signier_key=KEY2), AUD,
               "fremd signiertes Token wird abgewiesen", "signatur")
# Der Klassiker: alg auf 'none' setzen und die Signatur weglassen.
_t = token_bauen()
_teile = _t.split(".")
_kopf_none = _b64(json.dumps({"typ": "JWT", "alg": "none", "x5t": X5T}).encode())
muss_scheitern("%s.%s." % (_kopf_none, _teile[1]), AUD,
               "alg=none wird abgewiesen", "signaturverfahren")
muss_scheitern("%s.%s.%s" % (_kopf_none, _teile[1], _teile[2]), AUD,
               "alg=none mit angehaengter Signatur wird abgewiesen")
# Nutzdaten veraendern, Signatur behalten
_boese_rumpf = _b64(json.dumps({"aud": AUD, "nbf": "1", "exp": str(int(time.time()) + 999),
                                "appctx": {"msexchuid": "fremd", "version": "ExIdTok.V1",
                                           "amurl": AMURL}}).encode())
muss_scheitern("%s.%s.%s" % (_teile[0], _boese_rumpf, _teile[2]), AUD,
               "veraenderte Nutzdaten werden abgewiesen", "signatur")
muss_scheitern("nur.zwei", AUD, "kein JWT-Aufbau", "drei teile")
muss_scheitern("", AUD, "leeres Token")

# Unbekanntes x5t darf NICHT scheitern, solange die Signatur passt – den Beweis
# liefert die Signatur, x5t ist nur die Auswahlhilfe (Zertifikatstausch!).
_t_x5t = token_bauen(kopf_extra={"x5t": "voelligAndererFingerabdruck"})
try:
    sso.pruefe_token(_t_x5t, AUD)
    pruefe(True, "unbekanntes x5t bricht nicht ab, solange die Signatur stimmt")
except sso.SsoFehler as e:
    pruefe(False, "unbekanntes x5t sollte durchgehen: %s" % e)

# ═══ 3. Vertrauensanker: welcher Exchange? ══════════════════════════════════
abschnitt("3. Herkunft (amurl) und Zielgruppe (aud)")
muss_scheitern(token_bauen(rumpf_extra={"appctx": {"amurl": "https://boese.example/autodiscover/metadata/json/1"}}),
               AUD, "Token eines FREMDEN Exchange wird abgewiesen", "anderen exchange")
muss_scheitern(token_bauen(), "https://fremd.local/addin/taskpane.html",
               "Token fuer ein anderes Add-in wird abgewiesen", "andere adresse")

# Ohne hinterlegte EWS-Adresse gibt es KEIN SSO (fail-closed).
_echte_hosts = sso.erlaubte_hosts
sso.erlaubte_hosts = lambda: set()
muss_scheitern(token_bauen(), AUD, "ohne hinterlegte EWS-Adresse kein SSO", "ews-adresse")
sso.erlaubte_hosts = _echte_hosts

# ═══ 4. Laufzeit und Formfehler ═════════════════════════════════════════════
abschnitt("4. Laufzeit und Form")
jetzt = int(time.time())
muss_scheitern(token_bauen(rumpf_extra={"exp": str(jetzt - 3600)}), AUD,
               "abgelaufenes Token", "abgelaufen")
muss_scheitern(token_bauen(rumpf_extra={"nbf": str(jetzt + 3600)}), AUD,
               "noch nicht gueltiges Token")
# Uhrenversatz innerhalb der Toleranz muss durchgehen – sonst scheitert die
# Anmeldung auf Systemen mit leicht abweichender Uhr scheinbar zufaellig.
try:
    sso.pruefe_token(token_bauen(rumpf_extra={"exp": str(jetzt - 60)}), AUD)
    pruefe(True, "60 s abgelaufen liegt in der Toleranz (%d s)" % sso.UHR_TOLERANZ_SEK)
except sso.SsoFehler as e:
    pruefe(False, "Toleranz greift nicht: %s" % e)
muss_scheitern(token_bauen(rumpf_extra={"appctx": {"version": "ExIdTok.V9"}}), AUD,
               "unbekannte Token-Fassung", "fassung")
muss_scheitern(token_bauen(kopf_extra={"typ": "XYZ"}), AUD, "typ ist nicht JWT")
muss_scheitern(token_bauen(kopf_extra={"x5t": ""}), AUD, "x5t fehlt", "fingerabdruck")

# ═══ 5. Verknuepfung ════════════════════════════════════════════════════════
abschnitt("5. Verknuepfung Postfach ↔ Konto")
k = info["kennung"]
pruefe(sso.benutzer_fuer(k) == "", "unbekanntes Postfach liefert leer (fail-closed)")
sso.verknuepfe(k, "NEXUS\\Andreas.Bender")
pruefe(sso.benutzer_fuer(k) == "andreas.bender",
       "Name wird normalisiert (%s)" % sso.benutzer_fuer(k))
# Dieselbe Person, andere Tippform beim Anlegen – muss dieselbe Verknuepfung sein.
sso.verknuepfe(k, "andreas.bender@nexus.int")
pruefe(sso.benutzer_fuer(k) == "andreas.bender", "UPN-Form ergibt denselben Benutzer")
pruefe(sso.benutzer_fuer("gibtsnicht") == "", "fremde Kennung liefert leer")

pruefe(len(sso.verknuepfungen()) == 1, "Uebersicht zeigt einen Eintrag")
pruefe(all(len(e["kennung"]) <= 12 for e in sso.verknuepfungen()),
       "die Uebersicht gibt die Postfach-Kennung NICHT vollstaendig heraus")

# Dateirechte: die Datei ist die Grundlage der Anmeldung.
_modus = sso.LINK_DATEI.stat().st_mode & 0o777
pruefe(_modus == 0o640, "Verknuepfungsdatei ist 0640 (ist: %o)" % _modus)
pruefe(not list(sso.LINK_DATEI.parent.glob("*.tmp")),
       "keine Nebendatei bleibt liegen (atomar geschrieben)")

sso.verknuepfe(sso.kennung("zweites", AMURL), "andreas.bender")
pruefe(len(sso.verknuepfungen()) == 2, "zweites Postfach desselben Benutzers geht")
pruefe(sso.loese("NEXUS\\andreas.bender") == 2, "loesen entfernt BEIDE Verknuepfungen")
pruefe(sso.benutzer_fuer(k) == "", "nach dem Loesen ist das Postfach unbekannt")
pruefe(sso.loese("gibtsnicht") == 0, "loesen eines unbekannten Kontos ist folgenlos")

# Beschaedigte Datei darf nicht durchschlagen – fail-closed statt Ausnahme.
sso.LINK_DATEI.write_text("{kaputt", encoding="utf-8")
pruefe(sso.benutzer_fuer(k) == "", "beschaedigte Datei => niemand ist verknuepft")

# ═══ 6. Verdrahtung in main.py ══════════════════════════════════════════════
abschnitt("6. Endpunkte und Sperrlisten")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
SANDBOX = (ROOT / "backend" / "sandbox.py").read_text(encoding="utf-8")
ADDINJS = (ROOT / "frontend" / "addin" / "addin.js").read_text(encoding="utf-8")

_ep = MAIN.split('@app.post("/api/addin/sso")', 1)
pruefe(len(_ep) == 2, "Endpunkt /api/addin/sso existiert")
_ep = _ep[1].split("@app.", 1)[0]
# Der Anmeldeweg muss DIESELBEN Schranken fuehren wie /api/login. Fehlt eine,
# ist SSO der bequemste Weg daran vorbei.
for muss, warum in (
        ("_check_rate_limit", "Ratenbegrenzung"),
        ("_login_still_allowed", "Login-Freigabe (AD-Liste/Gruppe)"),
        ("darf_benutzer_anmelden", "Lizenz-Benutzergrenze"),
        ("security_guard.get_block", "Kontosperre"),
        ("record_login", "Anwesenheits-Buchhaltung"),
        ("totp_enabled", "Zwei-Faktor-Konten bekommen KEIN SSO")):
    pruefe(muss in _ep, "SSO-Endpunkt prueft: %s" % warum)
pruefe("Depends(" not in _ep,
       "keine Dependency – es ist ein Anmeldeweg, es gibt noch keine Sitzung")
pruefe("generate_token" in _ep, "stellt ein regulaeres Jarvis-Token aus")
pruefe('"unbekannt": True' in _ep,
       "unverknuepftes Postfach ist KEIN Fehler, sondern der erste Start")

# Die Erstverknuepfung haengt am regulaeren Login – nicht an einem zweiten,
# halb nachgebauten Anmeldeweg.
_login = MAIN.split('@app.post("/api/login")', 1)[1].split("@app.", 1)[0]
pruefe("addin_token" in _login, "/api/login nimmt das Add-in-Token entgegen")
pruefe("verknuepfe" in _login, "/api/login speichert die Verknuepfung")
_pos_tok = _login.index("token = generate_token")
pruefe(_login.index("addin_token") > _pos_tok,
       "verknuepft wird ERST NACH vollstaendiger Authentifizierung")

pruefe('"data/addin_links.json"' in SANDBOX,
       "die Verknuepfungsdatei steht in den Sandbox-Sperrlisten")
pruefe(SANDBOX.count("addin_links") >= 3,
       "in ALLEN drei Listen (_APP_DENY_REL, PRIVATE_FILES, SHELL_SECRET_PATHS): %d"
       % SANDBOX.count("addin_links"))

_adm = MAIN.split('@app.get("/api/addin/links")', 1)
pruefe(len(_adm) == 2 and "require_local_auth" in _adm[1].split("@app.", 1)[0],
       "die Uebersicht der Verknuepfungen ist Administratoren vorbehalten")
_del = MAIN.split('@app.delete("/api/addin/links/{username}")', 1)
pruefe(len(_del) == 2 and "require_local_auth" in _del[1].split("@app.", 1)[0],
       "das Loesen einer Verknuepfung ist Administratoren vorbehalten")

# ═══ 7. Aufgabenfenster ═════════════════════════════════════════════════════
abschnitt("7. Aufgabenfenster")
pruefe("getUserIdentityTokenAsync" in ADDINJS, "das Fenster holt das Exchange-Token")
pruefe("/api/addin/sso" in ADDINJS, "und schickt es an den SSO-Endpunkt")
pruefe("addin_token" in ADDINJS, "die Erstanmeldung schickt das Token mit")
# DER FUND VOM 2026-08-17: das Fenster sandte `totp`, der Server liest
# `totp_code`. Mit eingeschalteter Zwei-Faktor-Anmeldung war das eine
# Endlosschleife – der Server fragte den Code immer wieder an.
pruefe("totp_code" in ADDINJS, "der 2FA-Code geht unter dem Feldnamen totp_code raus")
pruefe(not re.search(r"rumpf\.totp\s*=", ADDINJS),
       "kein Rueckfall auf den falschen Feldnamen `totp`")
APP = (ROOT / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
pruefe("totp_code" in APP, "derselbe Feldname wie in app.js – Gegenprobe an der Quelle")
# Ein Fehlschlag der kennwortlosen Anmeldung darf NIE die Anmeldemaske
# ueberspringen, und ein Erfolg ohne Token darf nicht in eine Schleife laufen.
pruefe("ok && token()" in ADDINJS,
       "nach erfolgreichem SSO wird der Token GEPRUEFT (sonst Endlosschleife)")
# BEIDE 401-Zweige (Datenabruf und /api/me) muessen zuerst kennwortlos
# nachfassen – sonst steht nach jedem Token-Ablauf wieder die Anmeldemaske da,
# obwohl das Postfach laengst verknuepft ist.
_z401 = [t.split("return r.ok", 1)[0].split("throw new Error", 1)[0]
         for t in ADDINJS.split("status === 401")[1:]]
pruefe(len(_z401) == 2, "genau zwei 401-Zweige gefunden (%d)" % len(_z401))
pruefe(all("ssoVersuch" in z for z in _z401),
       "beide 401-Zweige versuchen zuerst wieder kennwortlos")
pruefe("_ssoProbiert" in ADDINJS, "Endlosschleife-Bremse vorhanden")
I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
for k in ("addin.sso_first", "addin.sso_timeout", "addin.sso_unsupported", "addin.sso_failed"):
    pruefe(I18N.count("'%s'" % k) == 2, "%s in DE und EN" % k)

# ═══ 8. Antwort-Vorschau (erst ansehen, dann senden) ════════════════════════
abschnitt("8. Antwort-Vorschau")
RUNNER = (ROOT / "backend" / "mail_runner.py").read_text(encoding="utf-8")

# DIE ZENTRALE ZUSAGE: der Vorschlags-Lauf hat KEINE Werkzeuge. Damit kann eine
# Prompt-Injektion in der eingegangenen Mail nichts ausloesen – sie kann nur den
# Vorschlagstext beeinflussen, und den liest ein Mensch vor dem Senden.
def _nur_code(py: str) -> str:
    """Docstrings und Kommentare aus einem Python-Ausschnitt entfernen.

    NOETIG, NICHT KOSMETIK: die Pruefung "_role_tools = set() steht im Code"
    war zuerst gruen, obwohl der Code auf `None` stand – der Treffer kam aus dem
    DOCSTRING, der die Zusage erklaert. Ein Waechter, der seine eigene
    Begruendung liest, prueft nichts (dieselbe Falle wie beim Prompt-Waechter
    2026-08-10 und beim Marken-Test 2026-08-11).
    """
    ohne = re.sub(r'"""(?:.|\n)*?"""', "", py)
    return "\n".join(z.split("#", 1)[0] for z in ohne.splitlines())


_vs = RUNNER.split("async def antwort_vorschlag", 1)
pruefe(len(_vs) == 2, "antwort_vorschlag existiert")
_vs_roh = _vs[1].split("\nasync def ", 1)[0].split("\ndef ", 1)[0]
_vs = _nur_code(_vs_roh)
pruefe("_role_tools = set()" in _vs,
       "der Lauf bekommt die LEERE Werkzeugmenge (= keine Werkzeuge)")
pruefe("_role_tools = None" not in _vs.split("finally", 1)[0],
       "vor dem Lauf wird NICHT auf 'keine Beschraenkung' gesetzt")
for verboten in ("email_senden", "email_antworten", "email_weiterleiten",
                 "email_verschieben", "email_loeschen"):
    pruefe(verboten not in _vs, "kein Sendewerkzeug im Vorschlags-Lauf: %s" % verboten)
pruefe("_injektion_pruefen" in _vs,
       "Injektionsmuster werden auch hier protokolliert")
pruefe("_fremdtext_entschaerfen" in _vs,
       "Fremdtext wird entschaerft (Abschnittsmarken)")
pruefe("secrets.token_hex" in _vs, "Echtheitskennung je Lauf")
pruefe("trotz_aussetzer=True" in _vs,
       "eine Handlung des Menschen laeuft trotz Aussetzer (wie Verbindungstest)")

# Senden: KEIN Sprachmodell, und der Empfaenger kommt aus der NACHRICHT.
_snd = RUNNER.split("async def antwort_senden", 1)
pruefe(len(_snd) == 2, "antwort_senden existiert")
_snd = _nur_code(_snd[1].split("\n# ──", 1)[0])
pruefe("run_task_headless" not in _snd and "JarvisAgent" not in _snd,
       "beim Senden laeuft KEIN Sprachmodell")
pruefe("c.antworten" in _snd,
       "gesendet wird ueber antworten() – der Empfaenger ergibt sich aus der Nachricht")
# Geprueft wird die SIGNATUR: gaebe es einen Empfaenger-Parameter, waere dieser
# Endpunkt ein Versandweg an beliebige Adressen. Dass die Rueckgabe den Absender
# der beantworteten Mail NENNT, ist Anzeige und kein Eingabefeld – deshalb auf
# den Parameter pruefen, nicht auf den Teilstring "an".
_sig = RUNNER.split("async def antwort_senden(", 1)[1].split(")", 1)[0]
pruefe(not any(w in _sig for w in ("an:", "an=", "empfaenger", "to:", "to=")),
       "kein Empfaenger-Parameter in antwort_senden (%s)" % " ".join(_sig.split()))
pruefe("protokoll_schreiben" in _snd, "der Versand steht im Protokoll")
pruefe("VORSCHLAG_MAX" in _snd, "die Textlaenge ist gedeckelt")

# Aufbereitung: Codeblock und Betreffzeile duerfen nicht in die Mail.
import importlib  # noqa: E402
_mr = None
try:
    _mr = importlib.import_module("backend.mail_runner")
except Exception as _e:  # noqa: BLE001
    print("  (mail_runner nicht importierbar: %s – Quelltext-Pruefungen greifen weiter)" % _e)
if _mr is not None:
    f = _mr._vorschlag_saeubern
    pruefe(f("```\nHallo Welt\n```") == "Hallo Welt", "umschliessender Codeblock faellt weg")
    pruefe(f("Betreff: Re: Test\n\nHallo") == "Hallo", "fuehrende Betreffzeile faellt weg")
    pruefe(f("Subject: X\nBetreff: Y\n\nText") == "Text", "auch mehrere/englische Betreffzeilen")
    pruefe(f("Hallo,\n\nBetreff: steht mitten drin\n\nGruss").count("Betreff:") == 1,
           "eine Betreffzeile MITTEN im Text bleibt stehen (kein Datenverlust)")
    pruefe(f("  Hallo  ") == "Hallo", "Rand-Leerraum weg")
    pruefe(f("") == "", "leer bleibt leer")
    pruefe(len(f("x" * 40000)) <= _mr.VORSCHLAG_MAX, "Deckel greift")

# Endpunkte
_pv = MAIN.split('@app.post("/api/email/reply/preview")', 1)
pruefe(len(_pv) == 2, "Endpunkt /api/email/reply/preview existiert")
_pv = _pv[1].split("@app.", 1)[0]
pruefe("require_email_access" in _pv, "Vorschau haengt an der E-Mail-Freigabe")
pruefe('owner") == mail_rules.norm_user(user)' in _pv,
       "eine FREMDE Regel wird nicht als Ton-Vorgabe uebernommen")
_sd = MAIN.split('@app.post("/api/email/reply/send")', 1)
pruefe(len(_sd) == 2, "Endpunkt /api/email/reply/send existiert")
_sd = _sd[1].split("@app.", 1)[0]
pruefe("require_email_access" in _sd, "Senden haengt an der E-Mail-Freigabe")
pruefe('body or {}).get("an"' not in _sd and '"empfaenger"' not in _sd,
       "der Empfaenger kommt NICHT aus dem Rumpf")

# Aufgabenfenster
pruefe("/api/email/reply/preview" in ADDINJS and "/api/email/reply/send" in ADDINJS,
       "beide Endpunkte sind verdrahtet")
pruefe("ad-reply-text" in ADDINJS, "der Vorschlag ist bearbeitbar (textarea)")
_zn = ADDINJS.split("function zeichneNachricht", 1)[1].split("\n    function ", 1)[0]
pruefe(_zn.index("addin.reply_head") < _zn.index("addin.run_head"),
       "die Antwort steht VOR dem Regel-Block")
pruefe("aktive.length" in _zn and _zn.index("addin.reply_head") < _zn.index("no_rules"),
       "der Antwort-Weg haengt NICHT an einer vorhandenen Regel")
pruefe("_vorschlag.text = ta.value" in ADDINJS,
       "der bearbeitete Text wird gespiegelt (Neuzeichnen darf ihn nicht verlieren)")
pruefe("ladeProtokoll" not in ADDINJS,
       "kein Aufruf einer Funktion, die es nicht gibt (die heisst ladeLog)")
for k in ("addin.reply_head", "addin.reply_make", "addin.reply_send",
          "addin.reply_draft", "addin.reply_safe", "addin.run_head"):
    pruefe(I18N.count("'%s'" % k) == 2, "%s in DE und EN" % k)

# ═══ 9. Persoenliche Antwort-Vorgabe ════════════════════════════════════════
# Wunsch des Nutzers 2026-08-17: Signatur, Anrede-Form und Tabus gehoeren nicht
# in ein Feld, das man pro Mail neu tippt. Gilt fuer BEIDE Wege (Vorschlag und
# Regel-Lauf), damit die Signatur nicht doppelt gepflegt werden muss.
abschnitt("9. Persoenliche Antwort-Vorgabe")
ACC = (ROOT / "backend" / "mail_accounts.py").read_text(encoding="utf-8")
EMAILHTML2 = (ROOT / "frontend" / "email.html").read_text(encoding="utf-8")
PORTALJS2 = (ROOT / "frontend" / "js" / "email_portal.js").read_text(encoding="utf-8")
TASKPANE2 = (ROOT / "frontend" / "addin" / "taskpane.html").read_text(encoding="utf-8")

_AENDERBAR = ACC.split("AENDERBAR = (", 1)[1].split(")", 1)[0]
pruefe('"antwort_vorgabe"' in _AENDERBAR,
       "das alte Einzelfeld steht weiter in AENDERBAR (ein im Browser "
       "zwischengespeichertes Add-in sendet es noch)")
# ABER: die Stilliste darf NICHT ueber das Postfach-Formular laufen. Sonst
# schriebe ein Klick auf "Postfach speichern" die Liste mit dem Formularstand –
# dieselbe Vermischung wie bei den SAP-Sichtbarkeiten.
pruefe('"stile"' not in _AENDERBAR,
       "die Stilliste steht NICHT in AENDERBAR (eigene Endpunkte)")
pruefe("VORGABE_MAX" in ACC and "MAX_STILE" in ACC and "STIL_NAME_MAX" in ACC,
       "Text, Anzahl und Name sind gedeckelt (der Text geht in JEDEN Auftrag)")
for fn in ("def stile(", "def stil_anlegen(", "def stil_aendern(",
           "def stil_loeschen(", "def stil_fuer(", "def stil_aus_prompt(",
           "def antwort_vorgabe("):
    pruefe(fn in ACC, "vorhanden: %s…)" % fn)
# Ein leerer Wert aus einem alten Client darf die Stiltexte NICHT loeschen.
_sp = ACC.split("def speichern(", 1)[1].split("\ndef ", 1)[0]
pruefe("if _alt:" in _sp,
       "ein LEERES antwort_vorgabe aus einem alten Client loescht nichts")
# Bewusst NICHT in MailKonto: dort stehen Verbindungsdaten fuer MailClient.
# MailKonto steht in mail_client.py, NICHT in mail_accounts.py. Die erste
# Fassung dieser Pruefung las die falsche Datei, fand die Klasse nicht und war
# damit trivial wahr. Bei "X darf in Y nicht vorkommen" immer belegen, dass Y
# ueberhaupt gefunden wurde.
CLIENT = (ROOT / "backend" / "mail_client.py").read_text(encoding="utf-8")
pruefe("class MailKonto" in CLIENT, "MailKonto gefunden (sonst prueft das Folgende nichts)")
_mk = CLIENT.split("class MailKonto", 1)[1].split("\n\n\n", 1)[0]
pruefe(len(_mk) > 200, "der Klassenrumpf ist plausibel gross (%d Zeichen)" % len(_mk))
pruefe("antwort_vorgabe" not in _mk and "stile" not in _mk,
       "die Vorgabe steckt NICHT im Verbindungsobjekt MailKonto")
pruefe('"stile": _stile_von(k)' in ACC,
       "konto_info liefert die Liste zurueck (die Oberflaeche muss sie anzeigen)")

# REIHENFOLGE: Regel → Fremdtext → Stilvorgabe. Umgedreht am 2026-08-17 nach dem
# Vorfall, bei dem die Vorgabe ("immer auf bayrisch antworten") die
# Absender-Bedingung der Regel ueberstimmt hat. Gemessen an den echten Marken,
# nicht am Fliesstext des Vorspanns – der nennt die Abschnitte ebenfalls.
_au = RUNNER.split("def _auftrag(", 1)[1].split("\n\n\n", 1)[0]
pruefe("stil_fuer(" in _au, "der Regel-Lauf loest den Stil auf (Feld > Prompt > Standard)")
_mk_au = [m.group(1).strip() for m in
          re.finditer(r"=====\s*\[%s\]\s*([A-Z][^=]*?)\s*=====", _au)]
_i_regel = [i for i, m in enumerate(_mk_au) if m.startswith("ANWEISUNG")]
_i_stil = [i for i, m in enumerate(_mk_au) if m.startswith("STILVORGABE")]
pruefe(bool(_i_regel) and bool(_i_stil) and _i_regel[0] < _i_stil[0],
       "die Regel steht VOR der Stilvorgabe (Vorfall 2026-08-17)")
_vs2 = RUNNER.split("async def antwort_vorschlag", 1)[1].split("\nasync def ", 1)[0]
pruefe("stil_fuer(" in _vs2, "der Vorschlag loest den Stil ebenfalls auf")
pruefe(_vs2.index("STILVORGABE") < _vs2.index("WUNSCH DES POSTFACH-INHABERS"),
       "beim Vorschlag: Stil vor Wunsch und Hinweis (Spaeteres praezisiert)")
# Die Vorgabe traegt die Echtheitskennung – sie IST eine Angabe des Inhabers
# und darf nicht wie Fremdtext aussehen.
pruefe("[%s] STILVORGABE" in _au and "[%s] STILVORGABE" in _vs2,
       "die Stilvorgabe steht in einem Abschnitt MIT Echtheitskennung")
# Der NAME darf die Marke nicht zerlegen (er kommt aus einem Freitextfeld).
pruefe("_markensicher(" in _au or "_markensicher(" in RUNNER,
       "der Stilname wird fuer die Abschnittszeile entschaerft")

# Oberflaeche: Verwaltung in BEIDEN Masken (Vorgabe des Nutzers), Auswahl im
# Regel-Formular und in der Antwort-Vorschau des Add-ins.
pruefe('id="em-stile-list"' in EMAILHTML2 and 'id="em-stil-edit"' in EMAILHTML2,
       "/email hat Liste und Formular")
pruefe('id="ad-stile"' in TASKPANE2 and 'id="ad-stil-edit"' in TASKPANE2,
       "das Add-in ebenso")
pruefe('id="em-vorgabe"' not in EMAILHTML2 and 'id="ad-vorgabe"' not in TASKPANE2,
       "das alte Einzelfeld ist aus beiden Masken verschwunden")
for js, wo in ((PORTALJS2, "/email"), (ADDINJS, "Add-in")):
    pruefe("/api/email/styles" in js, "%s spricht die Stil-Endpunkte an" % wo)
    pruefe("stilOptionen(" in js, "%s baut das Auswahlfeld" % wo)
# NUR CODE pruefen: im Rumpf steht ein Kommentar, der das Feld beim Namen nennt
# und begruendet, warum es dort nicht mehr steht – ein Waechter, der seine
# eigene Erklaerung liest, prueft nichts (dritter Fall dieser Art im Projekt).
_sk = PORTALJS2.split("function speichereKonto", 1)[1].split("\n    function ", 1)[0]
_sk_code = "\n".join(z for z in _sk.splitlines() if not z.lstrip().startswith("//"))
pruefe("antwort_vorgabe" not in _sk_code,
       "/email sendet das alte Feld NICHT mehr mit (es wuerde den Stil ueberschreiben)")
pruefe("ad-reply-stil" in ADDINJS, "die Antwort-Vorschau hat ein Stil-Pulldown")
pruefe("stil: (($('ad-reply-stil')" in ADDINJS or "stil:" in ADDINJS,
       "die Wahl geht an /api/email/reply/preview")
for k in ("mail.styles_head", "mail.style_new", "mail.style_name",
          "mail.style_is_default", "mail.f_style", "mail.style_opt_off",
          "mail.acct_guide_ph", "mail.acct_guide_hint"):
    pruefe(I18N.count("'%s'" % k) == 2, "%s in DE und EN" % k)

# ── Der Vorspann muss den AUFBAU beschreiben, den der Auftrag hat ──
# BEIM LIVE-TEST AUFGEFALLEN: nach dem Einfuegen des Vorgabe-Abschnitts sagte der
# Vorspann weiter "Unten stehen zuerst die ANWEISUNG ... und danach die
# NACHRICHT" und zusaetzlich "Es gibt in diesem Auftrag NUR EINE Regel". Ein
# Modell, das das ernst nimmt, haette die neue Vorgabe als "Zusatzregel" – also
# als Angriffsversuch – eingestuft und ignoriert. Dieselbe Fehlerklasse wie beim
# alten WA_TASK_PROMPT: ein Prompt, der etwas anderes beschreibt als der Code tut.
for _name in ("_VORSPANN = ", "_VORSCHLAG_VORSPANN = "):
    _txt = RUNNER.split(_name, 1)[1].split('"""', 2)[1]
    pruefe("STILVORGABE" in _txt,
           "%s nennt den Stil-Abschnitt" % _name.strip(" ="))
pruefe("NUR EINE Regel" not in RUNNER,
       "die Aussage 'es gibt NUR EINE Regel' ist weg – es sind jetzt zwei Abschnitte")

# Und maschinell: JEDE Abschnittsmarke, die _auftrag erzeugt, muss im Vorspann
# vorkommen. Ein Test auf einen festen Wortlaut wuerde beim naechsten Abschnitt
# wieder danebenliegen.
_marken = re.findall(r'=====\s*\[%s\]\s*([A-Z][A-Z ()a-z-]+?)\s*=====',
                     RUNNER.split("def _auftrag(", 1)[1].split("\n\n\n", 1)[0])
pruefe(len(_marken) >= 3, "Abschnittsmarken im Auftrag gefunden (%s)" % _marken)
# Vergleich in Kleinbuchstaben: die MARKE steht in Grossbuchstaben, der
# Fliesstext des Vorspanns nicht ("die STILVORGABE des Postfach-Inhabers").
# Schlussmarken ("ENDE …") sind ausgenommen – sie schliessen einen Abschnitt,
# den der Vorspann bereits erklaert hat.
# WHITESPACE NORMALISIEREN: der Vorspann ist auf 79 Zeichen umbrochen, die
# gesuchte Wendung steht deshalb als "STILVORGABE des\n  Postfach-Inhabers".
# Ein roher Teilstring-Vergleich findet das nie (derselbe Fallstrick wie bei den
# zweizeiligen Aufrufen im Transkriptions-Test).
_vorspann = " ".join(RUNNER.split("_VORSPANN = ", 1)[1]
                     .split('"""', 2)[1].lower().split())
for _m in _marken:
    _kern = _m.split("(")[0].strip()
    if _kern.startswith("ENDE"):
        continue
    pruefe(" ".join(_kern.lower().split()) in _vorspann,
           "der Vorspann erklaert den Abschnitt '%s'" % _kern)

# ═══ 10. Feld-Erklaerungen (ⓘ) ══════════════════════════════════════════════
# GEMELDET 2026-08-17: "ein Benutzer kann mit 'Vorgabe' bei 'Entwuerfe' und
# 'Gesendet' genau NICHTS anfangen". Dazu kam eine Wortkollision, die ich selbst
# erzeugt hatte: das neue Feld hiess ebenfalls "Vorgabe", direkt darunter.
abschnitt("10. Feld-Erklaerungen")
EMHTML = (ROOT / "frontend" / "email.html").read_text(encoding="utf-8")
EMJS = (ROOT / "frontend" / "js" / "email_portal.js").read_text(encoding="utf-8")
TP = (ROOT / "frontend" / "addin" / "taskpane.html").read_text(encoding="utf-8")

# Die Wortkollision ist aufgeloest: der Platzhalter sagt, was leer bedeutet,
# und das neue Feld heisst nicht mehr wie er.
pruefe("'mail.default_ph':              'Standardordner'" in I18N,
       "der Ordner-Platzhalter heisst nicht mehr nur 'Vorgabe'")
pruefe('placeholder="Vorgabe"' not in EMHTML and 'placeholder="Vorgabe"' not in TP,
       "auch der HTML-Rueckfall ist nachgezogen (er steht ohne i18n da)")
pruefe("Stil und Signatur" in I18N,
       "das neue Feld heisst nicht mehr 'Vorgabe' (Kollision mit den Ordnern)")
# Kein technischer Fachbegriff in der Oberflaeche: die Zielgruppe sind
# Sachbearbeiter, keine Entwickler.
for wort in ("PrePrompt", "Pre-Prompt", "Prompt-Vorlage"):
    pruefe(wort not in EMHTML and wort not in TP,
           "kein Fachbegriff '%s' in der Oberflaeche" % wort)

# Knopf und Kasten muessen PAARWEISE existieren – ein ⓘ ohne Kasten tut nichts,
# ein Kasten ohne ⓘ ist unerreichbar.
for datei, name, kls in ((EMHTML, "/email", "em"), (TP, "Add-in", "ad")):
    _b = re.findall(r'data-help="([a-z-]+)"', datei)
    _k = re.findall(r'class="%s-help" id="([a-z-]+)"' % kls, datei)
    pruefe(len(_b) >= 4, "%s: mindestens vier Erklaerungen (%d)" % (name, len(_b)))
    pruefe(sorted(_b) == sorted(_k),
           "%s: jeder Knopf hat seinen Kasten (%s / %s)" % (name, sorted(_b), sorted(_k)))
    pruefe(datei.count('aria-expanded="false"') >= len(_b),
           "%s: jeder Knopf meldet seinen Zustand (aria-expanded)" % name)
    # DIE CSS-REGEL MUSS DA SEIN: der Markup-Test allein war gruen, waehrend im
    # Add-in die Regel fehlte – der Browser zeichnete den UA-Default und aus dem
    # dezenten Zeichen wurde ein grauer Kasten (nur im Screenshot zu sehen).
    pruefe(".%s-info {" % kls in datei and "background: none" in
           datei.split(".%s-info {" % kls, 1)[1][:200],
           "%s: das ⓘ ist gestaltet (ohne background:none ein grauer UA-Knopf)" % name)
    pruefe(".%s-help.is-open" % kls in datei,
           "%s: der Erklaerkasten hat seine Aufklapp-Regel" % name)

# EIN delegierter Listener statt Bindung je Knopf – sonst wirkt ein spaeter
# ergaenztes ⓘ nicht, und in nachtraeglich gezeichneten Bereichen nie.
for js, name in ((EMJS, "email_portal.js"), (ADDINJS, "addin.js")):
    pruefe("infoInit" in js, "%s: Erklaerungen sind verdrahtet" % name)
    pruefe("closest('.%s-info')" % ("em" if "email_portal" in name else "ad") in js,
           "%s: delegierter Listener (wirkt auch fuer spaeter ergaenzte Knoepfe)" % name)
    pruefe("_emInfoBound" in js or "_adInfoBound" in js,
           "%s: Mehrfachbindung ausgeschlossen" % name)

# ZWEI LAYOUT-/RENDER-FALLEN, beide erst im echten Browser aufgefallen:
for datei, name, kls in ((EMHTML, "/email", "em"), (TP, "Add-in", "ad")):
    # (1) `.em-field`/`.ad-field` sind SENKRECHTE Flex-Container. Ein Knopf als
    #     Geschwister des Labels wird eigenes Flex-Kind und landet in einer
    #     eigenen Zeile unter dem Feld – im Screenshot gesehen. Er gehoert INS
    #     Label. (Klassen-Falle wie bei .input-group und .role-field.)
    pruefe(not re.search(r"</label>\s*<button[^>]*%s-info" % kls, datei),
           "%s: kein ⓘ ausserhalb seines Labels (sonst eigene Zeile)" % name)
    # (2) `applyLang()` setzt bei `data-i18n` den textContent – ein Knopf IM
    #     Label waere damit beim ersten Sprachwechsel geloescht. Gemessen: der
    #     Knopf war im Browser nicht mehr auffindbar. Der Text gehoert in ein
    #     eigenes <span>, das Label selbst traegt kein data-i18n.
    pruefe(not re.search(r'<label data-i18n="[^"]+">[^<]*<button[^>]*%s-info' % kls, datei),
           "%s: kein ⓘ in einem Label mit eigenem data-i18n (applyLang loescht ihn)" % name)

# Der Klick auf ein ⓘ INNERHALB eines <label> mit Checkbox darf den Haken nicht
# umschalten (Lehre vom AD-Picker 2026-07-29). Im Browser gemessen: mit
# preventDefault bleibt der Haken stehen.
for js, name in ((EMJS, "email_portal.js"), (ADDINJS, "addin.js")):
    pruefe("preventDefault()" in js.split("infoInit", 1)[1][:900],
           "%s: der ⓘ-Handler unterdrueckt die Label-Aktivierung" % name)

for k in ("mail.help", "mail.help_login", "mail.help_channel", "mail.help_folders",
          "mail.help_styles", "mail.help_active"):
    pruefe(I18N.count("'%s'" % k) == 2, "%s in DE und EN" % k)

# ═══ Ergebnis ═══════════════════════════════════════════════════════════════
import shutil  # noqa: E402
shutil.rmtree(_SAND, ignore_errors=True)
print("\n%s  %d bestanden, %d fehlgeschlagen  (Sandkasten: %s)" %
      ("OK  " if not _fail else "FEHL", _ok, _fail, _SAND))
sys.exit(0 if not _fail else 1)
