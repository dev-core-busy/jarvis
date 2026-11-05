#!/usr/bin/env python3
"""Add-in-Seiten: Outlook im Web IM HAUS darf das Aufgabenfenster einrahmen.

Gemeldet 2026-11-05 (ECHT): Outlook im Web des eigenen Exchange zeigte nur
"Add-In-Fehler – Beim Starten dieses Add-Ins ist ein Fehler aufgetreten".
Ursache: ``frame-ancestors`` der Add-in-Seiten kannte nur Microsofts
Cloud-Hosts; OWA im Haus rahmt von seinem eigenen Host ein. Dazu blockierte
``script-src`` das von office.js nachgeladene MicrosoftAjax.js.

  [A] Positivkontrolle: Richtlinie fuer eine Add-in-Seite ist zerlegbar.
  [B] Exchange-Hosts aus der Quelle stehen in frame-ancestors der Add-in-
      Seiten – und NUR dort (nicht auf /, /portal).
  [C] Unsaubere Hosts (Platzhalter, Semikolon, Leerzeichen) gelangen nicht in
      die Kopfzeile; eine werfende Quelle bricht die Richtlinie nicht.
  [D] script-src der Add-in-Seiten erlaubt ajax.aspnetcdn.com, andere nicht.
  [D2] Add-in-Seiten: 'unsafe-eval' (microsoftajax.js) und frame-src
      appsforoffice.microsoft.com – beides NUR dort.
  [E] main.py (Syntaxbaum) reicht eine Quelle an csp.office_hosts_quelle,
      die addin_sso.rahmen_hosts aufruft.
  [F] rahmen_hosts: EWS-Host PLUS die DNS-Namen des verankerten
      EWS-Zertifikats (2026-11-05: OWA lief unter einem anderen Namen
      desselben Exchange als EWS – Chrome verweigerte den Rahmen).
      Platzhalter-SANs fallen weg; ohne/kaputtes Zertifikat nur EWS-Host;
      erlaubte_hosts (Token-Anker) bleibt davon unberuehrt.

Exit 0 = gruen, 1 = Regelverstoss, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OK = FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global OK, FAIL
    if cond:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("\n         " + detail) if detail else ""))


def abbruch(grund: str) -> None:
    print("ABBRUCH (Exit 2): " + grund)
    sys.exit(2)


try:
    from backend import csp
except Exception as e:  # noqa: BLE001
    abbruch("backend.csp nicht importierbar: %s" % e)
if "backend.config" in sys.modules:
    abbruch("backend.csp hat backend.config importiert")
if not hasattr(csp, "office_hosts_quelle"):
    abbruch("csp.office_hosts_quelle fehlt – Zusage existiert nicht")


def direktiven(text: str) -> dict:
    d = {}
    for teil in text.split(";"):
        w = teil.split()
        if w:
            d[w[0]] = w[1:]
    return d


HOSTS = {"mail.firma.local"}
csp.office_hosts_quelle(lambda: set(HOSTS))
ADDIN = direktiven(csp.richtlinie("/addin/taskpane.html", "jarvis.beispiel.de"))
WURZEL = direktiven(csp.richtlinie("/", "jarvis.beispiel.de"))
PORTAL = direktiven(csp.richtlinie("/portal", "jarvis.beispiel.de"))

print("[A] Positivkontrolle")
if "frame-ancestors" not in ADDIN or "script-src" not in ADDIN:
    abbruch("Richtlinie ohne frame-ancestors/script-src: %r" % ADDIN)
check("Microsoft-Hosts stehen weiter drin", "https://*.office.com" in ADDIN["frame-ancestors"])

print("[B] Exchange im Haus darf einrahmen")
check("Add-in: https://mail.firma.local in frame-ancestors",
      "https://mail.firma.local" in ADDIN["frame-ancestors"], str(ADDIN["frame-ancestors"]))
check("Excel-Add-in ebenso",
      "https://mail.firma.local" in direktiven(csp.richtlinie("/excel-addin/x.html"))["frame-ancestors"])
check("/ bleibt nur 'self'", WURZEL.get("frame-ancestors") == ["'self'"], str(WURZEL.get("frame-ancestors")))
check("/portal bleibt nur 'self'", PORTAL.get("frame-ancestors") == ["'self'"], str(PORTAL.get("frame-ancestors")))
HOSTS.clear()
HOSTS.update({"b.firma.local", "a.firma.local"})
fa = direktiven(csp.richtlinie("/addin/taskpane.html"))["frame-ancestors"]
check("mehrere Hosts, sortiert", fa[-2:] == ["https://a.firma.local", "https://b.firma.local"], str(fa))

print("[C] Unsaubere Werte")
HOSTS.clear()
HOSTS.update({"*.firma.local", "x.firma.local; script-src *", "a b", "", "[::1]", "GUT.firma.local"})
roh = csp.richtlinie("/addin/taskpane.html")
fa = direktiven(roh)["frame-ancestors"]
check("Platzhalter nicht uebernommen", "https://*.firma.local" not in fa, str(fa))
check("Semikolon erzeugt keine Direktive", roh.count("script-src") == 1, roh)
check("Leerzeichen-Host nicht uebernommen", "https://a" not in fa and "b" not in fa, str(fa))
check("gueltiger Host klein uebernommen", "https://gut.firma.local" in fa, str(fa))


def wirft():
    raise RuntimeError("Konfiguration kaputt")


csp.office_hosts_quelle(wirft)
try:
    fa = direktiven(csp.richtlinie("/addin/taskpane.html"))["frame-ancestors"]
    check("werfende Quelle: Microsoft-Liste bleibt", "https://*.office.com" in fa, str(fa))
except Exception as e:  # noqa: BLE001
    check("werfende Quelle bricht die Richtlinie nicht", False, repr(e))
csp.office_hosts_quelle(lambda: None)
check("Quelle liefert None: kein Fehler",
      "frame-ancestors" in direktiven(csp.richtlinie("/addin/taskpane.html")))

print("[D] MicrosoftAjax.js fuer office.js")
check("Add-in: ajax.aspnetcdn.com in script-src",
      "https://ajax.aspnetcdn.com" in ADDIN["script-src"], str(ADDIN["script-src"]))
check("/ ohne aspnetcdn", "https://ajax.aspnetcdn.com" not in WURZEL.get("script-src", []))

print("[D2] office.js-Kommunikation (ECHT 2026-11-05)")
check("Add-in: 'unsafe-eval' in script-src (microsoftajax.js)",
      "'unsafe-eval'" in ADDIN["script-src"], str(ADDIN["script-src"]))
check("Add-in: appsforoffice.microsoft.com in frame-src",
      "https://appsforoffice.microsoft.com" in ADDIN.get("frame-src", []), str(ADDIN.get("frame-src")))
for _p in ("/", "/portal", "/chat"):
    _d = direktiven(csp.richtlinie(_p))
    check("%s ohne 'unsafe-eval'" % _p, "'unsafe-eval'" not in _d.get("script-src", []), str(_d.get("script-src")))
    check("%s ohne appsforoffice in frame-src" % _p,
          "https://appsforoffice.microsoft.com" not in _d.get("frame-src", []), str(_d.get("frame-src")))

print("[E] main.py reicht die Quelle herein")
baum = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
funcs = {n.name: n for n in ast.walk(baum) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
quelle = None
for n in ast.walk(baum):
    if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "office_hosts_quelle" and n.args
            and isinstance(n.args[0], ast.Name)):
        quelle = n.args[0].id
check("csp.office_hosts_quelle(<funktion>) wird aufgerufen", quelle is not None)
ruft = False
if quelle in funcs:
    for n in ast.walk(funcs[quelle]):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "rahmen_hosts":
            ruft = True
check("Quelle ruft addin_sso.rahmen_hosts", ruft, str(quelle))

print("[F] rahmen_hosts aus EWS-Host und verankertem Zertifikat")
import datetime  # noqa: E402
import types  # noqa: E402
try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
except Exception as e:  # noqa: BLE001
    abbruch("cryptography fehlt: %s" % e)


def zert_pem(namen):
    k = ec.generate_private_key(ec.SECP256R1())
    n = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "test")])
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    z = (x509.CertificateBuilder().subject_name(n).issuer_name(n).public_key(k.public_key())
         .serial_number(1).not_valid_before(jetzt).not_valid_after(jetzt + datetime.timedelta(days=1))
         .add_extension(x509.SubjectAlternativeName([x509.DNSName(x) for x in namen]), critical=False)
         .sign(k, hashes.SHA256()))
    return z.public_bytes(serialization.Encoding.PEM).decode()


_CFG: dict = {}
_ma = types.ModuleType("backend.mail_accounts")
_ma.skill_config = lambda: _CFG
sys.modules["backend.mail_accounts"] = _ma
try:
    from backend import addin_sso as sso
except Exception as e:  # noqa: BLE001
    abbruch("backend.addin_sso nicht importierbar: %s" % e)
if "backend.config" in sys.modules:
    abbruch("addin_sso hat backend.config importiert")
if not hasattr(sso, "rahmen_hosts"):
    abbruch("addin_sso.rahmen_hosts fehlt – Zusage existiert nicht")

_CFG.update({"ews_url": "https://exchange.firma.local/EWS/Exchange.asmx"})
# Positivkontrolle: ohne Anker genau der EWS-Host
check("ohne Anker: nur EWS-Host", sso.rahmen_hosts() == {"exchange.firma.local"}, str(sso.rahmen_hosts()))
_CFG["zert_anker"] = {"ews": {"host": "exchange.firma.local", "port": 443,
                              "pem": zert_pem(["exchange.firma.local", "OWA.firma.local", "*.firma.local"])}}
rh = sso.rahmen_hosts()
check("SAN owa.firma.local kommt dazu (klein)", "owa.firma.local" in rh, str(rh))
check("Platzhalter-SAN faellt weg", not any("*" in h for h in rh), str(rh))
check("erlaubte_hosts (Token-Anker) bleibt eng", sso.erlaubte_hosts() == {"exchange.firma.local"},
      str(sso.erlaubte_hosts()))
_CFG["zert_anker"] = {"ews": {"pem": "-----BEGIN CERTIFICATE-----\nkaputt\n-----END CERTIFICATE-----"}}
check("kaputtes PEM: nur EWS-Host, kein Fehler", sso.rahmen_hosts() == {"exchange.firma.local"})
_CFG["zert_anker"] = {"ews": {"host": "x", "pem": zert_pem(["owa.firma.local"])}}
csp.office_hosts_quelle(sso.rahmen_hosts)
fa = direktiven(csp.richtlinie("/addin/taskpane.html")).get("frame-ancestors", [])
check("Ende zu Ende: https://owa.firma.local in frame-ancestors", "https://owa.firma.local" in fa, str(fa))

print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
