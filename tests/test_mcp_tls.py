#!/usr/bin/env python3
"""Waechter: MCP-Zertifikat ansehen, pruefen, erlauben (2026-10-25).

GEMELDET (2026-10-24): "ich kann keine Zertifikat Pruefung oder 'akzeptieren'
feststellen". Gemessen stimmte das in jeder Schicht – ein MCP-Server mit
selbstsigniertem Zertifikat war nicht einbindbar, und es gab weder im Backend
noch in der Maske ein Feld dafuer.

DIE ZUSAGE, die dieser Waechter durchsetzt – und sie hat ZWEI Haelften, die
leicht auseinanderlaufen:

  [A] Die Pruefung bleibt AN. Es gibt kein ``verify=False`` und keinen Weg
      dazu. Ein hinterlegtes Zertifikat ERGAENZT die System-CAs, ersetzt sie
      nicht (sonst bricht derselbe Server, sobald er auf ein regulaeres
      Zertifikat wechselt).
  [B] Das ANSEHEN ist kein Vertrauen. Abgeholt wird ohne Pruefung – anders
      kommt man an ein unbekanntes Zertifikat nicht heran – und genau deshalb
      muss der Fingerabdruck sichtbar sein: nur der Mensch, der ihn mit dem
      Server-Betreiber abgleicht, macht den Weg sicher. Ein Dialog, der bloss
      "akzeptieren?" fragt, waere ``verify=False`` mit mehr Schritten.

Gemessen wird am echten ``backend.mcp_tls`` gegen ein SELBST ERZEUGTES
Zertifikat (``cryptography``), nicht gegen einen Mock: ein Zertifikat ist
genau die Sorte Material, die man nicht von Hand tippt (Register –
Testmaterial baut der Erzeuger).

    venv/bin/python tests/test_mcp_tls.py

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import datetime as dt
import os
import ssl
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = 0
FAIL = 0
_bilanz = False


def check(name: str, bed: bool, zusatz: str = "") -> None:
    global OK, FAIL
    if bed:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (" – " + zusatz if zusatz else ""))


def abschnitt(t: str) -> None:
    print("\n" + t)


def ende() -> None:
    global _bilanz
    _bilanz = True
    print("\n" + "=" * 62)
    print("  %d OK, %d FAIL" % (OK, FAIL))
    print("=" * 62)
    sys.exit(1 if FAIL else 0)


def _abbruch():
    # "Exit 1 ohne Bilanz" ist von "ich beisse" nicht zu unterscheiden.
    if not _bilanz:
        print("\nABBRUCH: vor der Bilanz gestorben – 'konnte nicht laufen', "
              "NICHT bestanden (bis hierher: %d OK, %d FAIL)" % (OK, FAIL))
        sys.stdout.flush()
        os._exit(2)



def abbruch(text: str) -> None:
    """'Konnte nicht laufen' – IMMER Exit 2, nie die Bilanz.

    ⚠ BEZAHLT BEIM BAU DER GEGENPROBE (2026-10-25): die Abbruch-Stellen riefen
    `ende()`, und die endet mit `exit(1 if FAIL else 0)`. Bei null
    FAILs meldete ein ABBRUCH damit "bestanden" – genau der Zustand, gegen den
    die Exit-2-Stufe gebaut ist. Gefunden hat es eine Sonde, die den Messaufbau
    blind machte und Exit 0 statt 2 bekam (Register: ein Abbruch ist von einem
    bestandenen Lauf sonst nicht zu unterscheiden). Die Stelle stand schon
    im Commit 649e219e.
    """
    global _bilanz
    _bilanz = True        # der atexit-Melder soll nicht doppelt melden
    print("ABBRUCH: " + text)
    print("  (bis hierher: %d OK, %d FAIL – 'konnte nicht laufen', NICHT "
          "bestanden)" % (OK, FAIL))
    sys.stdout.flush()
    sys.exit(2)

import atexit                                                      # noqa: E402

atexit.register(_abbruch)

# `backend.config` nur als Stub – der echte Import schreibt die Live-
# settings.json zurueck (Register). `mcp_tls` braucht ihn nur transitiv.
_cfg = types.ModuleType("backend.config")
_cfg.config = object()
sys.modules.setdefault("backend.config", _cfg)

try:
    from backend import mcp_tls as T
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: backend.mcp_tls nicht ladbar: %s" % e)
    sys.exit(2)

try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID
except ImportError as e:
    print("ABBRUCH: cryptography fehlt (%s) – ohne sie kann dieser Waechter "
          "kein Testzertifikat erzeugen" % e)
    sys.exit(2)

TMP = Path(tempfile.mkdtemp(prefix="mcp_tls_test_"))


def _zert(cn="probe.beispiel.invalid", namen=("probe.beispiel.invalid",),
          tage_von=-1, tage_bis=30, ca=False):
    """Ein echtes, selbstsigniertes Zertifikat – vom ERZEUGER gebaut."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    jetzt = dt.datetime.now(dt.timezone.utc)
    b = (x509.CertificateBuilder()
         .subject_name(name).issuer_name(name)
         .public_key(key.public_key())
         .serial_number(x509.random_serial_number())
         .not_valid_before(jetzt + dt.timedelta(days=tage_von))
         .not_valid_after(jetzt + dt.timedelta(days=tage_bis)))
    if namen:
        b = b.add_extension(
            x509.SubjectAlternativeName([x509.DNSName(n) for n in namen]),
            critical=False)
    if ca:
        # Eine (Firmen-)Root-CA: selbstsigniert wie ein Server-Zert, aber mit
        # CA:TRUE. Sie darf NIE gepinnt werden – sie signiert viele Server.
        b = b.add_extension(x509.BasicConstraints(ca=True, path_length=None),
                            critical=True)
    cert = b.sign(key, hashes.SHA256())
    pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    schluessel = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()).decode()
    _ZERT_SCHLUESSEL[pem] = schluessel
    return pem


# PEM -> privater Schluessel, damit ein echter TLS-Server damit lauschen kann.
# Ein Zertifikat ohne Schluessel ist zum Vorzeigen nutzlos.
_ZERT_SCHLUESSEL: dict = {}



def _ca_und_leaf(leaf_namen=("andere.invalid",)):
    """Eine ECHTE Root-CA (CA:TRUE, OHNE Server-Namen) und ein von ihr
    signiertes Server-Zertifikat. So sieht eine Firmen-CA aus – sie wird nie
    gepinnt, und ueber sie muss der NAME weiter zaehlen."""
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Firmen-Root")])
    jetzt = dt.datetime.now(dt.timezone.utc)
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(jetzt - dt.timedelta(days=1))
          .not_valid_after(jetzt + dt.timedelta(days=30))
          .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
          # ⚠ RFC 5280: Python 3.13 prueft im Strikt-Modus (VERIFY_X509_STRICT)
          # die Schluessel-Kennungen. Ohne SKI/AKI lehnt OpenSSL mit Code 85
          # ("Missing Authority Key Identifier") ab – und zwar VOR dem
          # Namensabgleich. Die erste Fassung dieses Materials war deshalb
          # untauglich: "fremder Name verbindet nicht" waere aus dem FALSCHEN
          # Grund gruen gewesen. Testmaterial baut der Erzeuger – vollstaendig.
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()),
                         critical=False)
          .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True,
                         crl_sign=True, content_commitment=False,
                         key_encipherment=False, data_encipherment=False,
                         key_agreement=False, encipher_only=False,
                         decipher_only=False), critical=True)
          .sign(ca_key, hashes.SHA256()))
    lk = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    lname = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, leaf_namen[0])])
    leaf = (x509.CertificateBuilder().subject_name(lname).issuer_name(ca_name)
            .public_key(lk.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(jetzt - dt.timedelta(days=1))
            .not_valid_after(jetzt + dt.timedelta(days=30))
            .add_extension(x509.SubjectAlternativeName(
                [x509.DNSName(n) for n in leaf_namen]), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None),
                           critical=True)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(
                ca_key.public_key()), critical=False)
            .add_extension(x509.SubjectKeyIdentifier.from_public_key(lk.public_key()),
                           critical=False)
            .sign(ca_key, hashes.SHA256()))
    ca_pem = ca.public_bytes(serialization.Encoding.PEM).decode()
    leaf_pem = leaf.public_bytes(serialization.Encoding.PEM).decode()
    _ZERT_SCHLUESSEL[leaf_pem] = lk.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption()).decode()
    return ca_pem, leaf_pem

def _tls_server(pem: str):
    """Ein echter TLS-Server, der ``pem`` vorzeigt. Liefert (port, stoppen).

    ⚠ WARUM DAS SEIN MUSS: die Zusagen von `zertifikat_abholen` (Abdruck,
    selbstsigniert, Befunde, vertraut_system) sind am Quelltext nur als
    VORKOMMEN pruefbar – und ein Vorkommen misst keine Wirkung. Drei
    Gegenproben blieben genau deshalb stumm: `aus["befunde"] = []`,
    `if False:` und `= False` lassen das gesuchte Wort stehen (Register).
    Gemessen wird deshalb gegen einen Server, der wirklich ein Zertifikat
    vorzeigt.
    """
    import socket
    import threading
    schluessel = _ZERT_SCHLUESSEL.get(pem)
    if not schluessel:
        return None, (lambda: None)
    kz = TMP / ("srv-%d.pem" % len(_ZERT_SCHLUESSEL))
    kz.write_text(pem + schluessel, encoding="utf-8")
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(str(kz))
    lauscher = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    lauscher.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    lauscher.bind(("127.0.0.1", 0))
    lauscher.listen(8)
    port = lauscher.getsockname()[1]
    laeuft = {"an": True}

    def _bedienen():
        while laeuft["an"]:
            try:
                rohe, _ = lauscher.accept()
            except OSError:
                return
            try:
                with ctx.wrap_socket(rohe, server_side=True):
                    pass
            except Exception:  # noqa: BLE001
                pass            # der Abholer schliesst nach dem Handshake
            finally:
                try:
                    rohe.close()
                except Exception:  # noqa: BLE001
                    pass

    th = threading.Thread(target=_bedienen, daemon=True)
    th.start()

    def _stoppen():
        laeuft["an"] = False
        try:
            lauscher.close()
        except Exception:  # noqa: BLE001
            pass

    return port, _stoppen


# ── 1. Die Pruefung bleibt AN ───────────────────────────────────────────────
abschnitt("1. Die Pruefung bleibt eingeschaltet")
PEM = _zert()
check("Positivkontrolle: ein echtes Testzertifikat ist erzeugt",
      PEM.startswith("-----BEGIN CERTIFICATE-----"), PEM[:30])

# ⚠ ZWEI WEGE SEIT 2026-10-25, und die Sicherheit haengt an ihrer Trennung.
# Gemeldet war "trotz akzeptiertem Zertifikat weiterhin Verbindung
# abgebrochen": der Server wurde per IP angesprochen, das Zertifikat galt nur
# fuer Namen, und `check_hostname` lehnte ab. Ein ERLAUBTES selbstsigniertes
# Server-Zert wird deshalb GEPINNT (Zertifikats- statt Namensabgleich). Das ist
# nur sicher OHNE System-CAs – mit ihnen vertraute `check_hostname=False` jedem
# CA-signierten Zertifikat fuer JEDEN Host. Gemessen wird das direkt an den
# geladenen Ankern (`cert_store_stats`), nicht am Quelltext.
_system = ssl.create_default_context().cert_store_stats()["x509"]
check("Positivkontrolle: der System-Kontext hat Anker", _system > 0, str(_system))

abschnitt("1a. Pinning: ein erlaubtes, selbstsigniertes SERVER-Zertifikat")
pin = T.ssl_kontext(PEM)
check("ein selbstsigniertes Server-Zert wird gepinnt", T.ist_gepinnt(PEM) is True)
check("… mit CERT_REQUIRED (die Pruefung bleibt AN)",
      pin is not None and pin.verify_mode == ssl.CERT_REQUIRED)
check("… Namensabgleich aus – das Zertifikat selbst ist die Identitaet",
      pin is not None and pin.check_hostname is False)
_anker = pin.cert_store_stats()["x509"] if pin is not None else -1
check("⚠ GENAU EIN Anker, KEINE System-CAs (sonst jedes CA-Zert fuer jeden Host)",
      _anker == 1, "%d Anker geladen, System hat %d" % (_anker, _system))

abschnitt("1b. CA-Weg: eine CA wird NIE gepinnt")
PEM_CA = _zert(cn="Firmen-Root", namen=(), ca=True)
check("eine selbstsignierte CA (CA:TRUE) wird NICHT gepinnt",
      T.ist_gepinnt(PEM_CA) is False)
ctx = T.ssl_kontext(PEM_CA)
check("… der Name wird weiter geprueft (check_hostname AN)",
      ctx is not None and ctx.check_hostname is True)
check("… mit CERT_REQUIRED",
      ctx is not None and ctx.verify_mode == ssl.CERT_REQUIRED)
# Die System-CAs bleiben im CA-Weg: ein Firmen-Zert ERGAENZT, ersetzt nicht.
_eigene = ctx.cert_store_stats()["x509"] if ctx is not None else -1
check("… die System-CAs bleiben geladen (ergaenzt, ersetzt nicht)",
      _eigene == _system + 1, "eigene=%d system=%d" % (_eigene, _system))

# Mehrere Bloecke (eine Kette) sind KEIN Einzel-Zert zum Pinnen.
check("eine Kette aus zwei Bloecken wird NICHT gepinnt (fail-closed)",
      T.ist_gepinnt(PEM + PEM_CA) is False)
check("ein kaputter Block wird nicht gepinnt",
      T.ist_gepinnt("-----BEGIN CERTIFICATE-----\nkaputt\n-----END CERTIFICATE-----") is False)
check("ein Pfad wird nie gepinnt", T.ist_gepinnt("/etc/ssl/ca.crt") is False)

check("ohne Eintrag gibt es KEINEN eigenen Kontext (Vorgabe des Systems)",
      T.ssl_kontext(None) is None and T.ssl_kontext("") is None
      and T.ssl_kontext("   ") is None)

# Es darf keinen Weg zu "Pruefung aus" geben – als REGEL am Syntaxbaum, damit
# ein spaeterer Umbau sie nicht beilaeufig einbaut.
_q = (ROOT / "backend" / "mcp_tls.py").read_text(encoding="utf-8")
_baum = ast.parse(_q)
_verdacht = [n for n in ast.walk(_baum)
             if isinstance(n, ast.Attribute) and n.attr == "CERT_NONE"]
# CERT_NONE kommt GENAU EINMAL vor: im Abhol-Kontext, der nur zum ANSEHEN
# dient. Mehr waere der Weg zu "verify aus".
check("ssl.CERT_NONE steht genau einmal (nur im Abholweg)",
      len(_verdacht) == 1, str(len(_verdacht)))
_fn_abholen = next((n for n in ast.walk(_baum)
                    if isinstance(n, ast.FunctionDef)
                    and n.name == "zertifikat_abholen"), None)
check("Positivkontrolle: zertifikat_abholen gefunden", _fn_abholen is not None)
if _fn_abholen is not None:
    _drin = [n for n in ast.walk(_fn_abholen)
             if isinstance(n, ast.Attribute) and n.attr == "CERT_NONE"]
    check("… und genau dort liegt es (nicht im Verbindungsweg)", len(_drin) == 1,
          str(len(_drin)))

# ── 2. Pfad-Eintraege: fail-closed ──────────────────────────────────────────
abschnitt("2. Ein Pfad ist eine Leseanweisung an den Dienst")
_datei = TMP / "probe-ca.crt"
_datei.write_text(PEM, encoding="utf-8")
check("ein absoluter Pfad auf eine PEM-Datei wird geladen",
      T.ssl_kontext(str(_datei)) is not None)

for roh, warum in ((("probe-ca.crt"), "relativ"),
                   (str(TMP / "gibtsnicht.crt"), "nicht vorhanden")):
    try:
        T.ssl_kontext(roh)
        check("ein %s angegebener Pfad wird abgewiesen" % warum, False,
              "durchgelassen")
    except T.CaFehler as e:
        check("ein %s angegebener Pfad wird abgewiesen" % warum, True)
        # ⚠ DER GRUND MUSS DER RICHTIGE SEIN. Die erste Fassung liess
        # "absolut ODER pruefen ODER PEM" gelten – damit bestand jede
        # Abweisung, auch die falsche: ohne die Absolut-Pruefung scheitert ein
        # relativer Pfad spaeter an "gibt es nicht", und die Gegenprobe blieb
        # stumm. Ein Grund, der die Ursache verfehlt, schickt den
        # Administrator in die falsche Richtung (Register).
        _soll = "absolut" if warum == "relativ" else "pruefen"
        check("… und der Grund nennt '%s'" % _soll,
              _soll in str(e) and len(str(e)) > 40, str(e)[:110])

_mull = TMP / "kein-zert.crt"
_mull.write_text("das ist kein Zertifikat\n", encoding="utf-8")
try:
    T.ssl_kontext(str(_mull))
    check("eine Datei OHNE Zertifikat wird abgewiesen", False, "durchgelassen")
except T.CaFehler as e:
    check("eine Datei OHNE Zertifikat wird abgewiesen", True)
    check("… und der Grund nennt das erwartete Format", "PEM" in str(e),
          str(e)[:90])

try:
    T.ssl_kontext("-----BEGIN CERTIFICATE-----\nkein base64\n-----END CERTIFICATE-----")
    check("ein kaputter PEM-Block wird abgewiesen", False, "durchgelassen")
except T.CaFehler:
    check("ein kaputter PEM-Block wird abgewiesen", True)

# ⚠ WELCHE PFADE GESPERRT SIND – und welche NICHT. Die zweite Haelfte ist die
# wichtigere: `sandbox.is_sensitive` fuehrt .crt/.pem/.cer als Geheimnis und
# haette JEDE Zertifikatsdatei abgewiesen (beim ersten Lauf gemessen, 6 von 6
# Probepfaden). Gemessen wird deshalb BEIDE Richtungen am echten `_ist_tabu`.
abschnitt("2b. Gesperrt ist, was dieses Feld nicht werden darf")
for pfad, soll, warum in (
        ("/etc/ssl/certs/ca-certificates.crt", False, "System-CA-Bundle"),
        ("/usr/local/share/ca-certificates/firma.crt", False, "ausgerolltes Firmen-Zert"),
        (str(TMP / "probe-ca.crt"), False, "eine gewoehnliche PEM-Datei"),
        ("/etc/jarvis/ca.pem", True, "Ort des Hauptschluessels"),
        (str(ROOT / "data" / "settings.json"), True, "Konfiguration des Dienstes"),
        (str(ROOT / ".env"), True, "Geheimnisse"),
        ("/home/x/.ssh/id_rsa", True, "SSH-Schluessel"),
        ("/etc/ssl/private/server.key", True, "Schluessel-Format"),
        ("/home/x/ca.p12", True, "Schluessel-Format"),
        ("/root/ca.crt", True, "/root")):
    ist, grund = T._ist_tabu(Path(pfad))
    check("%-44s %s (%s)" % (pfad[:44], "gesperrt" if soll else "erlaubt", warum),
          ist is soll, "ist=%s grund=%s" % (ist, grund[:40]))
check("ein gesperrter Pfad nennt immer einen Grund",
      all(T._ist_tabu(Path(p))[1] for p in ("/root/ca.crt", "/etc/jarvis/ca.pem",
                                            "/etc/ssl/private/server.key")))

abschnitt("2c. Fail-closed, wenn die Schranke selbst nicht antwortet")
_echt = sys.modules.get("backend.sandbox")
_kaputt = types.ModuleType("backend.sandbox")
_kaputt.PROJECT_ROOT = ROOT


class _Wirft(dict):
    def __contains__(self, x):
        raise RuntimeError("Schranke kaputt")


_kaputt._SECRET_NAMES = _Wirft()
_kaputt._SYSTEM_DENY_PREFIX = ()
_kaputt._APP_DENY_REL = ()
# ⚠ `sys.modules` ALLEIN GENUEGT NICHT: `_ist_tabu` macht `from backend import
# sandbox`, und das nimmt das ATTRIBUT des Pakets `backend`, das der echte
# Import dort schon gesetzt hat. Die erste Fassung patchte nur sys.modules –
# die Attrappe kam nie an, und die Pruefung meldete "durchgelassen", also einen
# fail-open-Mangel, den es nicht gab (Register: eine Attrappe, die einen Namen
# stellt, den der echte Prozess selbst importiert, prueft die eigene Annahme).
import backend as _pkg                                             # noqa: E402
_vorher_attr = getattr(_pkg, "sandbox", None)
sys.modules["backend.sandbox"] = _kaputt
_pkg.sandbox = _kaputt
# Positivkontrolle der Attrappe: sie muss wirklich werfen.
_wirft_wirklich = False
try:
    "x" in _kaputt._SECRET_NAMES
except RuntimeError:
    _wirft_wirklich = True
check("Positivkontrolle: die Attrappe wirft wirklich", _wirft_wirklich)
try:
    T.ssl_kontext(str(_datei))
    check("scheitert die Schutzpruefung, wird NICHT gelesen (fail-closed)",
          False, "durchgelassen")
except T.CaFehler as e:
    check("scheitert die Schutzpruefung, wird NICHT gelesen (fail-closed)", True)
    check("… und sagt, dass deshalb nicht gelesen wurde",
          "nicht gelesen" in str(e), str(e)[:90])
finally:
    if _echt is not None:
        sys.modules["backend.sandbox"] = _echt
    else:
        sys.modules.pop("backend.sandbox", None)
    if _vorher_attr is not None:
        _pkg.sandbox = _vorher_attr

# ── 3. Hostname-Vergleich wie TLS ihn macht ─────────────────────────────────
abschnitt("3. Namensvergleich (Wildcards nur eine Ebene, nur links)")
for host, namen, soll in (
        ("a.firma.de", ["*.firma.de"], True),
        ("firma.de", ["*.firma.de"], False),      # der nackte Name NICHT
        ("b.a.firma.de", ["*.firma.de"], False),  # nur EINE Ebene
        ("x.de", ["x.de"], True),
        ("X.DE", ["x.de"], True),                 # ohne Ruecksicht auf Gross
        ("x.de", ["y.de", "x.de"], True),
        ("x.de", [], False)):
    check("%-13s gegen %-18s -> %s" % (host, namen, soll),
          T._host_passt(host, namen) is soll,
          "ist %s" % T._host_passt(host, namen))

# ── 4. ist_pem / passt_zum_gespeicherten / beschreibung ─────────────────────
abschnitt("4. Die Weiche PEM gegen Pfad und der Vergleich")
check("ein PEM-Block wird erkannt", T.ist_pem(PEM) is True)
check("… auch mit Leerraum davor", T.ist_pem("\n  " + PEM) is True)
check("ein Pfad ist KEIN PEM", T.ist_pem("/etc/ssl/ca.crt") is False)
check("leer ist kein PEM", T.ist_pem("") is False and T.ist_pem(None) is False)

check("dasselbe Zertifikat gilt als hinterlegt",
      T.passt_zum_gespeicherten(PEM, PEM) is True)
check("… auch bei anderen Zeilenenden (CRLF gegen LF)",
      T.passt_zum_gespeicherten(PEM, PEM.replace("\n", "\r\n")) is True)
check("ein ANDERES Zertifikat gilt nicht als hinterlegt",
      T.passt_zum_gespeicherten(PEM, _zert(cn="andere.invalid")) is False)
check("ein hinterlegter PFAD gilt nie als 'genau dieses Zertifikat'",
      T.passt_zum_gespeicherten(str(_datei), PEM) is False)

# ⚠ Die Beschreibung darf das Zertifikat NICHT enthalten – sie landet im
# Journal und in der Oberflaeche.
_b = T.beschreibung(PEM)
check("die Beschreibung nennt die FORM, nicht den Inhalt",
      "PEM-Block" in _b and "BEGIN" not in _b and len(_b) < 60, _b[:80])
check("bei einem Pfad nennt sie den Pfad (den braucht der Administrator)",
      str(_datei) in T.beschreibung(str(_datei)))
check("ohne Eintrag ist sie leer", T.beschreibung("") == "")

# ── 5. host_und_port: nur https ─────────────────────────────────────────────
abschnitt("5. Ohne TLS gibt es nichts zu pruefen")
check("https mit Port", T.host_und_port("https://h.invalid:8443/mcp") == ("h.invalid", 8443))
check("https ohne Port -> 443",
      T.host_und_port("https://h.invalid/mcp") == ("h.invalid", 443))
for url, warum in (("http://h.invalid/mcp", "http"),
                   ("https:///mcp", "ohne Hostname"),
                   ("", "leer")):
    try:
        T.host_und_port(url)
        check("%s wird abgewiesen" % warum, False, "durchgelassen")
    except T.CaFehler:
        check("%s wird abgewiesen" % warum, True)

# ── 6. Die Bewertung: Ansehen ist kein Vertrauen ────────────────────────────
abschnitt("6. zertifikat_abholen bewertet, statt zu beruhigen")
_fn = _fn_abholen
if _fn is not None:
    # ⚠ DEN DOCSTRING ENTFERNEN, BEVOR GESUCHT WIRD. `ast.unparse` gibt ihn mit
    # aus, und er NENNT jeden Schluessel, den diese Pruefungen suchen
    # ("fingerprint_sha256", "befunde", "selbstsigniert", "vertraut_system").
    # Fuenf Gegenproben blieben deshalb stumm: der Waechter las seine eigene
    # Begruendung und war trivial wahr (Register – und dort steht ausdruecklich,
    # dass `tokenize` nur #-Kommentare kennt, Docstrings also per AST weg
    # muessen).
    _ohne_doc = ast.FunctionDef(
        name=_fn.name, args=_fn.args,
        body=([n for n in _fn.body][1:]
              if (_fn.body and isinstance(_fn.body[0], ast.Expr)
                  and isinstance(_fn.body[0].value, ast.Constant)
                  and isinstance(_fn.body[0].value.value, str))
              else list(_fn.body)),
        decorator_list=[], returns=None, type_comment=None, type_params=[])
    ast.fix_missing_locations(_ohne_doc)
    _quelle = ast.unparse(_ohne_doc)
    check("Positivkontrolle: der Docstring ist aus der Messung heraus",
          "BLOCKIEREND" not in _quelle and len(_quelle) > 400,
          "Laenge %d" % len(_quelle))
    # Die Funktion MUSS beide Messungen machen: abholen (CERT_NONE) UND
    # regulaer pruefen (create_default_context). Faellt die zweite weg, kann
    # die Oberflaeche "ist schon vertrauenswuerdig" nicht sagen – und jemand
    # schreibt ein Zertifikat fest, das naechsten Monat regulaer erneuert wird.
    check("sie prueft AUCH regulaer (create_default_context)",
          "create_default_context" in _quelle)
    check("… und liefert das Ergebnis getrennt als vertraut_system",
          "vertraut_system" in _quelle)
    check("sie liefert einen Fingerabdruck",
          "fingerprint_sha256" in _quelle)
    check("… ueber SHA256 (nicht SHA1/MD5)",
          "SHA256" in _quelle and "SHA1" not in _quelle and "MD5" not in _quelle)
    check("sie liefert BEFUNDE statt eines blossen ok/nicht-ok",
          "befunde" in _quelle)
    # Selbstsigniert, abgelaufen, Hostname, fehlendes SAN – alle vier muessen
    # als eigener Befund erscheinen; "irgendein Fehler" hilft niemandem.
    for wort, was in (("selbstsigniert", "selbstsigniert"),
                      ("abgelaufen", "abgelaufen"),
                      ("SubjectAlternativeName", "fehlendes SAN"),
                      ("gilt nicht fuer", "Hostname passt nicht")):
        check("Befund vorhanden: %s" % was, wort in _quelle)

# ── 7. DURCHSTICH: gegen einen echten TLS-Server ────────────────────────────
abschnitt("7. Durchstich gegen einen Server, der wirklich ein Zert vorzeigt")
# ⚠ HIER WIRD DIE WIRKUNG GEMESSEN, nicht ein Wort im Quelltext. Abschnitt 6
# kann nur sagen, DASS die Zusagen im Code stehen – drei Gegenproben blieben
# dort stumm, weil `aus["befunde"] = []` das Wort "befunde" stehen laesst.
_PEM7 = _zert(cn="localhost", namen=("localhost",))
_port, _stoppen = _tls_server(_PEM7)
if not _port:
    abbruch("kein TLS-Server – ohne ihn ist Abschnitt 7 nicht messbar")
try:
    _erg = T.zertifikat_abholen("https://localhost:%d/mcp" % _port, frist=5.0)

    # Der Abdruck muss der des vorgezeigten Zertifikats sein – nachgerechnet,
    # nicht uebernommen.
    from cryptography import x509 as _x5
    from cryptography.hazmat.primitives import hashes as _h
    _soll_fp = ":".join("%02X" % b for b in _x5.load_pem_x509_certificate(
        _PEM7.encode()).fingerprint(_h.SHA256()))
    check("der Abdruck ist der des vorgezeigten Zertifikats",
          _erg.get("fingerprint_sha256") == _soll_fp,
          "%s != %s" % (str(_erg.get("fingerprint_sha256"))[:20], _soll_fp[:20]))
    check("das abgeholte PEM ist das vorgezeigte",
          T.passt_zum_gespeicherten(_PEM7, _erg.get("pem", "")))
    check("selbstsigniert wird ERKANNT (nicht nur erwaehnt)",
          _erg.get("selbstsigniert") is True, str(_erg.get("selbstsigniert")))
    check("es gibt einen BEFUND, und er nennt 'selbstsigniert'",
          any("selbstsigniert" in b for b in _erg.get("befunde") or []),
          str(_erg.get("befunde")))
    check("das System vertraut ihm NICHT (getrennt gemessen)",
          _erg.get("vertraut_system") is False,
          str(_erg.get("vertraut_system")))
    check("der Hostname passt (localhost im SAN) – also KEIN Namensbefund",
          not any("gilt nicht fuer" in b for b in _erg.get("befunde") or []),
          str(_erg.get("befunde")))
    check("Host und Port kommen zurueck",
          _erg.get("host") == "localhost" and _erg.get("port") == _port)
    check("die Laufzeit wird gemeldet",
          bool(_erg.get("gueltig_von")) and bool(_erg.get("gueltig_bis")))

    # Und der Gegenfall: ein Zertifikat fuer einen ANDEREN Namen MUSS als
    # Namensbefund erscheinen. Ohne diesen Fall waere die Pruefung oben
    # trivial ("keine Befunde" ist leicht, wenn nie einer entsteht).
    _PEM_FREMD = _zert(cn="andere.invalid", namen=("andere.invalid",))
    _port2, _stop2 = _tls_server(_PEM_FREMD)
    try:
        _e2 = T.zertifikat_abholen("https://localhost:%d/mcp" % _port2, frist=5.0)
        check("ein Zertifikat fuer einen FREMDEN Namen erzeugt einen Namensbefund",
              any("gilt nicht fuer" in b for b in _e2.get("befunde") or []),
              str(_e2.get("befunde")))
    finally:
        _stop2()

    # Abgelaufen: auch das muss am echten Weg auffallen.
    _PEM_ALT = _zert(cn="localhost", namen=("localhost",), tage_von=-40,
                     tage_bis=-10)
    _port3, _stop3 = _tls_server(_PEM_ALT)
    try:
        _e3 = T.zertifikat_abholen("https://localhost:%d/mcp" % _port3, frist=5.0)
        check("ein ABGELAUFENES Zertifikat erzeugt den Befund 'abgelaufen'",
              any("abgelaufen" in b for b in _e3.get("befunde") or []),
              str(_e3.get("befunde")))
    finally:
        _stop3()

    # Ein geschlossener Port: der Grund muss sagen, dass nichts anzusehen ist.
    import socket as _so
    _frei = _so.socket()
    _frei.bind(("127.0.0.1", 0))
    _zu = _frei.getsockname()[1]
    _frei.close()
    try:
        T.zertifikat_abholen("https://localhost:%d/mcp" % _zu, frist=2.0)
        check("ein unerreichbarer Server wird gemeldet", False, "kein Fehler")
    except T.CaFehler as e:
        check("ein unerreichbarer Server wird gemeldet", True)
        check("… und der Grund nennt, dass ohne Verbindung nichts zu sehen ist",
              "nicht erreichbar" in str(e), str(e)[:90])
finally:
    _stoppen()

# ── 8. DER GEMELDETE FALL: Server per IP, Zertifikat nur fuer einen Namen ───
abschnitt("8. Pinning traegt, wo der Name nicht passt (der DEV-Fall)")
# ⚠ So war "theben" eingetragen: https://<IP>:8442, das Zertifikat gilt nur
# fuer `localhost` und einen Rechnernamen. Mit dem CA-Weg lehnte
# `check_hostname` ab ("IP address mismatch", verify_code 64) – AUCH nach dem
# Erlauben. Hier dieselbe Lage: Zertifikat nur fuer "localhost", angesprochen
# ueber 127.0.0.1.
import socket as _so8


def _handshake(ctx, port, sni="127.0.0.1"):
    try:
        with _so8.create_connection(("127.0.0.1", port), timeout=5) as s:
            with ctx.wrap_socket(s, server_hostname=sni):
                return "ok"
    except ssl.SSLCertVerificationError as f:
        return "abgelehnt:%s" % f.verify_code
    except Exception as f:  # noqa: BLE001
        return "fehler:%s" % type(f).__name__


_PEM8 = _zert(cn="localhost", namen=("localhost",))
_port8, _stop8 = _tls_server(_PEM8)
if not _port8:
    abbruch("kein TLS-Server – Abschnitt 8 nicht messbar")
try:
    # Positivkontrolle: der CA-Weg (mit Namensabgleich) lehnt hier ab – genau
    # das war der Vorfall. Ohne das waere "Pinning gelingt" trivial.
    _ca8 = ssl.create_default_context()
    _ca8.load_verify_locations(cadata=_PEM8)
    _r_ca = _handshake(_ca8, _port8)
    check("Positivkontrolle: mit Namensabgleich lehnt die IP ab (der Vorfall)",
          _r_ca.startswith("abgelehnt"), _r_ca)

    _r_pin = _handshake(T.ssl_kontext(_PEM8), _port8)
    check("das ERLAUBTE Zertifikat verbindet ueber die IP (Pinning)",
          _r_pin == "ok", _r_pin)

    # ⚠ DIE SICHERHEITSHAELFTE: ein FREMDES gepinntes Zertifikat darf NICHT
    # durch – sonst waere Pinning ohne Namensabgleich ein offenes Tor.
    _r_fremd = _handshake(T.ssl_kontext(_zert(cn="localhost", namen=("localhost",))),
                          _port8)
    check("ein FREMDES gepinntes Zertifikat (gleicher Name!) wird abgelehnt",
          _r_fremd.startswith("abgelehnt"), _r_fremd)
finally:
    _stop8()

# ⚠ DER THEBEN-FALL: `openssl req -x509` setzt per Vorgabe CA:TRUE. Ein
# selbstsigniertes SERVER-Zertifikat ist damit technisch eine CA – die erste
# Fassung pinnte es deshalb nie, und auf DEV stand nach dem Erlauben weiter
# "IP address mismatch". Hier dasselbe Zertifikat: CA:TRUE, kritisch, mit
# Server-Namen.
_PEM_X509 = _zert(cn="localhost", namen=("localhost",), ca=True)
check("ein Server-Zert MIT CA:TRUE (openssl req -x509) wird gepinnt",
      T.ist_gepinnt(_PEM_X509) is True)
_port8c, _stop8c = _tls_server(_PEM_X509)
try:
    _r_x509 = _handshake(T.ssl_kontext(_PEM_X509), _port8c)
    check("… und verbindet ueber die IP (das war der gemeldete Fall)",
          _r_x509 == "ok", _r_x509)
finally:
    _stop8c()

# Und der CA-Weg bleibt streng: eine ECHTE Root-CA (ohne Server-Namen), die das
# Zertifikat eines Servers mit FREMDEM Namen signiert hat. Sie wird nicht
# gepinnt, der Name zaehlt – und der passt nicht.
_ROOT, _LEAF = _ca_und_leaf(("andere.invalid",))
check("eine echte Root-CA (CA:TRUE, ohne Server-Namen) wird NICHT gepinnt",
      T.ist_gepinnt(_ROOT) is False)
_port8b, _stop8b = _tls_server(_LEAF)
try:
    _r_cab = _handshake(T.ssl_kontext(_ROOT), _port8b)
    # Der GRUND muss der Name sein (62), nicht irgendein Kettenfehler – sonst
    # misst die Pruefung die Untauglichkeit des Materials statt der Zusage.
    # 62 = Hostname, 64 = IP-Adresse passt nicht (hier wird per IP
    # angesprochen). Beides ist der gemeinte Grund; ausgeschlossen ist ein
    # KETTENfehler (85, 18, 20 …), der die Untauglichkeit des Materials maesse.
    check("ueber eine Root-CA verbindet ein FREMDER Name NICHT – wegen des Namens",
          _r_cab in ("abgelehnt:62", "abgelehnt:64"), _r_cab)
    # Positivkontrolle: dieselbe CA mit dem PASSENDEN Namen verbindet – sonst
    # waere "abgelehnt" auch bei einer kaputten Kette gruen.
    _r_cab_ok = _handshake(T.ssl_kontext(_ROOT), _port8b, sni="andere.invalid")
    check("Positivkontrolle: dieselbe Root-CA mit passendem Namen verbindet",
          _r_cab_ok == "ok", _r_cab_ok)
finally:
    _stop8b()

ende()
