#!/usr/bin/env python3
"""Waechter: ein verankertes DC-Zertifikat, das nicht mehr passt, wird als
solches BENANNT – nicht als "Aussteller unbekannt".

ANLASS (DEV, 2026-10-29): der Domain-Controller hatte am Vortag ein neues
Zertifikat bekommen. ``sap_cert.passt`` prueft nur Host und Port, also blieb das
ALTE Blatt der einzige Vertrauensanker (``ca_certs_data``); OpenSSL meldete
``unable to get local issuer certificate``, ``_verify_grund`` machte daraus
"Aussteller unbekannt (keine bekannte Zertifizierungsstelle)", und genau dieser
Text stand im Journal und an der Anmeldemaske. Er liest sich wie eine fehlende
Zertifizierungsstelle und schickt die Suche in die falsche Richtung – der Grund
war dem Dienst die ganze Zeit zugaenglich.

Gemessen wird die EIGENSCHAFT an ``verbinden()``, nicht der Wortlaut:

  1. passender Anker + anderes vorgelegtes Zertifikat -> der Grund nennt BEIDE
     Fingerabdruecke und den naechsten Schritt (neu verankern),
  2. die Messung des vorgelegten Zertifikats laeuft OHNE Anmeldedaten und
     UNGEPRUEFT (sonst scheiterte sie genauso und liefe ins Leere),
  3. gleicher Fingerabdruck (abgelaufen, Name) oder nichts zu holen -> der
     urspruengliche Grund bleibt stehen; eine Erneuerung wird nicht behauptet,
  4. ohne passenden Anker bleibt das Verhalten unveraendert, auch der
     Rueckfall der Uebergangsfrist.

Geladen wird das echte Modul; ``backend.config`` und ``ldap3`` sind Attrappen
(der echte config-Import schriebe die Live-settings.json zurueck), und
``_oeffnen`` wird durch eine Attrappe mit der ECHTEN Signatur ersetzt.
Lauf:  python3 tests/test_ad_anker_grund.py [pfad/zu/ldap_tls.py]
Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen
"""
import hashlib
import importlib.util
import ssl
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Pfad als Argument, damit gegen_ad_anker_grund.py sabotierte Kopien vorlegt
MODUL = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "backend" / "ldap_tls.py"
ok = fail = 0


def check(name, bed, detail=""):
    global ok, fail
    if bed:
        ok += 1
        print("  OK   " + name)
    else:
        fail += 1
        print("  FAIL " + name + (" – " + str(detail)[:300] if detail else ""))


def abschnitt(titel):
    print("\n" + titel)


# ── Attrappen: config und ldap3 ─────────────────────────────────────────────
_settings: dict = {}
pkg = sys.modules.setdefault("backend", types.ModuleType("backend"))
pkg.__path__ = [str(ROOT / "backend")]        # sap_cert echt dazuladen lassen
_cfg = types.ModuleType("backend.config")
_cfg.config = types.SimpleNamespace(get_setting=lambda k, d=None: _settings.get(k, d))
sys.modules["backend.config"] = _cfg
pkg.config = _cfg


class _Tls:
    """Attrappe von ldap3.Tls – haelt die Argumente, damit messbar ist, ob der
    Aufbau GEPRUEFT war."""

    def __init__(self, **kw):
        self.kw = kw


_ldap3 = types.ModuleType("ldap3")
_ldap3.Tls = _Tls
_ldap3.NONE = "NONE"
sys.modules["ldap3"] = _ldap3

try:
    spec = importlib.util.spec_from_file_location("backend.ldap_tls", MODUL)
    L = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(L)
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: ldap_tls nicht ladbar: %s" % e)
    sys.exit(2)

ZIEL = "dc.firma.local"
HOST, PORT = ZIEL, 389
DER_ALT = b"-zertifikat-alt-"
DER_NEU = b"-zertifikat-neu-"
FP_ALT = "sha256:" + hashlib.sha256(DER_ALT).hexdigest()
FP_NEU = "sha256:" + hashlib.sha256(DER_NEU).hexdigest()
URGRUND = "Aussteller unbekannt (keine bekannte Zertifizierungsstelle)"


class _Conn:
    def __init__(self, der):
        self.socket = types.SimpleNamespace(
            getpeercert=lambda binary_form=False: der)

    def unbind(self):
        pass


class _Oeffnen:
    """Attrappe von ``_oeffnen`` mit der ECHTEN Signatur. Der GEPRUEFTE Aufbau
    scheitert (so sieht der Vorfall aus), der ungepruefte legt ``der`` vor."""

    def __init__(self, der=DER_NEU, ungeprueft_wirft=False):
        self.der = der
        self.ungeprueft_wirft = ungeprueft_wirft
        self.aufrufe = []

    def __call__(self, host, port, ldaps, tls, user=None, password=None,
                 timeout=L.VERBINDUNGS_TIMEOUT):
        self.aufrufe.append({"host": host, "port": port, "tls": tls,
                             "user": user, "password": password})
        if tls.kw.get("validate") == ssl.CERT_REQUIRED:
            raise L.TlsFehler(URGRUND)
        if self.ungeprueft_wirft:
            raise L.TlsFehler("der Domain-Controller hat StartTLS abgelehnt")
        return _Conn(self.der)


def lauf(anker_eintrag, oeffnen, uebergang_bis="2000-01-01"):
    """``verbinden()`` mit gesetzter Lage fahren -> (ergebnis, fehlertext, info)."""
    _settings.clear()
    _settings[L.ANKER_FELD] = anker_eintrag
    _settings[L.UEBERGANG_FELD] = uebergang_bis
    echt, L._oeffnen = L._oeffnen, oeffnen
    info: dict = {}
    try:
        conn = L.verbinden(ZIEL, "wer", "geheim", timeout=3, info=info)
        return conn, "", info
    except L.TlsFehler as e:
        return None, str(e), info
    finally:
        L._oeffnen = echt


ANKER = {"host": HOST, "port": PORT, "pem": "-----BEGIN CERTIFICATE-----x",
         "fingerprint": FP_ALT, "name_abweichung": True}

print("Waechter: Grund bei nicht mehr passendem AD-Anker (%s)" % MODUL.name)

# ── Positivkontrollen VOR den inhaltlichen Pruefungen ───────────────────────
abschnitt("0. Positivkontrollen (ohne sie sind alle weiteren trivial)")
for name in ("verbinden", "_anker_grund", "_vorgelegter_fingerabdruck", "_oeffnen"):
    if not hasattr(L, name):
        print("ABBRUCH: ldap_tls.%s fehlt" % name)
        sys.exit(2)
_mess = _Oeffnen()
_conn, _text, _ = lauf(None, _mess, uebergang_bis="2099-01-01")
if _conn is None:
    print("ABBRUCH: die Attrappe traegt nicht – ohne Anker und in der Frist "
          "muesste eine Verbindung herauskommen (%s)" % _text)
    sys.exit(2)
check("die Attrappe greift: ohne Anker kommt in der Frist eine Verbindung", True)
if FP_ALT == FP_NEU:
    print("ABBRUCH: Probematerial unbrauchbar (beide Fingerabdruecke gleich)")
    sys.exit(2)
check("Probematerial: altes und neues Zertifikat sind unterscheidbar", True)

# ── 1. Der Vorfall: Anker passt zum Ziel, der DC legt etwas anderes vor ─────
abschnitt("1. Passender Anker, erneuertes Zertifikat")
mess = _Oeffnen(der=DER_NEU)
conn, text, _ = lauf(ANKER, mess)
check("kein Rueckfall: es kommt keine Verbindung heraus", conn is None, text)
check("der Grund nennt den VERANKERTEN Fingerabdruck", FP_ALT in text, text)
check("der Grund nennt den VORGELEGTEN Fingerabdruck", FP_NEU in text, text)
check("der Grund nennt den naechsten Schritt (neu verankern)",
      "verankern" in text.lower(), text)
check("der irrefuehrende Urgrund steht nicht mehr allein da",
      text.strip() != URGRUND, text)

abschnitt("2. Die Messung des vorgelegten Zertifikats ist harmlos")
nach = mess.aufrufe[1] if len(mess.aufrufe) > 1 else {}
check("es gab ueberhaupt einen zweiten, messenden Aufbau", bool(nach), mess.aufrufe)
check("dabei wurde KEIN Benutzername gesendet", nach.get("user") is None, nach.get("user"))
check("dabei wurde KEIN Kennwort gesendet", nach.get("password") is None,
      "Kennwort im Mess-Aufruf" if nach.get("password") else "")
check("der messende Aufbau ist ungeprueft (sonst scheiterte er genauso)",
      bool(nach) and nach["tls"].kw.get("validate") != ssl.CERT_REQUIRED,
      nach.get("tls").kw if nach else "")
check("der messende Aufbau geht an dasselbe Ziel",
      nach.get("host") == HOST and nach.get("port") == PORT, nach)

# ── 3. Keine Behauptung, die nicht gemessen ist ─────────────────────────────
abschnitt("3. Gleicher Fingerabdruck oder nichts zu holen -> Urgrund bleibt")
conn, text, _ = lauf(ANKER, _Oeffnen(der=DER_ALT))
check("dasselbe Zertifikat (abgelaufen/Name): Urgrund bleibt", text.strip() == URGRUND, text)
check("dabei wird keine Erneuerung behauptet", "erneuert" not in text.lower(), text)
conn, text, _ = lauf(ANKER, _Oeffnen(ungeprueft_wirft=True))
check("nichts zu holen: Urgrund bleibt", text.strip() == URGRUND, text)

# ── 4. Ohne passenden Anker bleibt alles, wie es war ────────────────────────
abschnitt("4. Unveraendertes Verhalten ohne passenden Anker")
fremd = dict(ANKER, host="ein-anderer-dc")
mess = _Oeffnen(der=DER_NEU)
conn, text, _ = lauf(fremd, mess, uebergang_bis="2000-01-01")
check("Anker eines anderen Ziels, Frist abgelaufen: Urgrund bleibt",
      text.strip() == URGRUND, text)
check("und es wird nicht unnoetig ein zweites Mal verbunden",
      len(mess.aufrufe) == 1, mess.aufrufe)
mess = _Oeffnen(der=DER_NEU)
conn, text, info = lauf(None, mess, uebergang_bis="2099-01-01")
check("kein Anker, Frist laeuft: ungepruefter Rueckfall steht weiter",
      conn is not None and info.get("ungeprueft") is True, (text, info))
mess = _Oeffnen(der=DER_NEU)
conn, text, info = lauf(ANKER, mess, uebergang_bis="2099-01-01")
check("passender Anker faellt NIE in die Frist (Angriffsfall)",
      conn is None, "Verbindung trotz unpassendem Anker")

print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
