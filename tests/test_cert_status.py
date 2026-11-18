#!/usr/bin/env python3
"""Waechter: Zertifikathinweis auf der Anmeldemaske nur, wenn er gebraucht wird
(gemeldet 2026-11-18: „bei korrekter HTTPS-Anmeldung muss im Loginscreen kein
Zertifikathinweis mehr angezeigt werden").

Der Browser kann per Skript nicht sagen, ob er der Verbindung vertraut – ein
weggeklicktes Warnfenster sieht genauso aus wie eine gueltige Kette. Der Server
weiss aber, was er vorlegt: ``security.zertifikat_von_ca`` (Aussteller !=
Inhaber) und ``GET /api/cert/status`` liefern das als ja/nein/unbekannt.

Geprueft:
  1. die Funktion an ECHTEN Zertifikaten (von cryptography erzeugt, nicht von
     Hand getippt): CA-ausgestellt → True, selbstsigniert → False, fehlend
     oder kaputt → None, Kette dahinter → das ERSTE zaehlt;
  2. der Endpunkt gibt genau diese Auskunft weiter (AST, nicht Teilstring);
  3. er steht als oeffentliche Ausnahme in der Zugangsregel – sonst saehe
     ihn die Anmeldemaske nie (sie hat noch keine Sitzung).

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import datetime
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = fail = 0


def pruefe(text, bedingung, zusatz=""):
    global ok, fail
    if bedingung:
        ok += 1
        print("  OK   " + text)
    else:
        fail += 1
        print("  FAIL " + text + ("  → " + str(zusatz) if zusatz else ""))


try:
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: cryptography fehlt (%s)" % e)
    sys.exit(2)

try:
    from backend.security import zertifikat_von_ca
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: backend.security nicht importierbar (%s)" % e)
    sys.exit(2)


def _name(cn):
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def _zert(inhaber, aussteller, schluessel, aussteller_schluessel):
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    return (x509.CertificateBuilder()
            .subject_name(_name(inhaber)).issuer_name(_name(aussteller))
            .public_key(schluessel.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(jetzt - datetime.timedelta(days=1))
            .not_valid_after(jetzt + datetime.timedelta(days=30))
            .sign(aussteller_schluessel, hashes.SHA256()))


def _pem(*zerts):
    return b"".join(z.public_bytes(serialization.Encoding.PEM) for z in zerts)


ca_k = ec.generate_private_key(ec.SECP256R1())
blatt_k = ec.generate_private_key(ec.SECP256R1())
eigen_k = ec.generate_private_key(ec.SECP256R1())
ca = _zert("Sonde Wurzel-CA", "Sonde Wurzel-CA", ca_k, ca_k)
blatt = _zert("server.beispiel.de", "Sonde Wurzel-CA", blatt_k, ca_k)
eigen = _zert("Jarvis CA", "Jarvis CA", eigen_k, eigen_k)

with tempfile.TemporaryDirectory() as tmp:
    t = pathlib.Path(tmp)
    (t / "blatt.crt").write_bytes(_pem(blatt))
    (t / "eigen.crt").write_bytes(_pem(eigen))
    (t / "blatt_kette.crt").write_bytes(_pem(blatt, ca))
    (t / "eigen_kette.crt").write_bytes(_pem(eigen, blatt))
    (t / "kaputt.crt").write_bytes(b"-----BEGIN CERTIFICATE-----\nquatsch\n")

    # Positivkontrolle: das Material hat die Eigenschaft, die gemessen wird.
    if not (blatt.issuer != blatt.subject and eigen.issuer == eigen.subject):
        print("ABBRUCH: Sonden-Zertifikate haben nicht die erwartete Form")
        sys.exit(2)

    print("── 1. zertifikat_von_ca")
    pruefe("CA-ausgestellt → True", zertifikat_von_ca(t / "blatt.crt") is True,
           zertifikat_von_ca(t / "blatt.crt"))
    pruefe("selbstsigniert → False", zertifikat_von_ca(t / "eigen.crt") is False,
           zertifikat_von_ca(t / "eigen.crt"))
    pruefe("Blatt + Kette → das ERSTE zaehlt (True)",
           zertifikat_von_ca(t / "blatt_kette.crt") is True)
    pruefe("selbstsigniert + angehaengtes Blatt → das ERSTE zaehlt (False)",
           zertifikat_von_ca(t / "eigen_kette.crt") is False)
    # ⚠ None ist eine EIGENE Stufe: „nicht feststellbar" darf weder als
    # „von CA" (Hinweis faellt weg) noch stumm als False gemeldet werden.
    pruefe("fehlende Datei → None (nicht feststellbar)",
           zertifikat_von_ca(t / "gibtsnicht.crt") is None)
    pruefe("kaputte Datei → None", zertifikat_von_ca(t / "kaputt.crt") is None)

# ── 2. Endpunkt ─────────────────────────────────────────────────────────────
print("── 2. GET /api/cert/status")
quelle = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
baum = ast.parse(quelle)
fn = None
for knoten in ast.walk(baum):
    if isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef)):
        for d in knoten.decorator_list:
            if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                    and d.func.attr == "get" and d.args
                    and isinstance(d.args[0], ast.Constant)
                    and d.args[0].value == "/api/cert/status"):
                fn = knoten
pruefe("Route /api/cert/status existiert", fn is not None)
if fn is not None:
    aufrufe = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
               and isinstance(n.func, ast.Name) and n.func.id == "zertifikat_von_ca"]
    pruefe("… und ruft zertifikat_von_ca auf", len(aufrufe) == 1, len(aufrufe))
    # Der Wert geht UNVERAENDERT als ca_ausgestellt hinaus – kein bool(),
    # das aus None ein False (oder aus einem Objekt ein True) machte.
    schluessel_ok = False
    for n in ast.walk(fn):
        if isinstance(n, ast.Dict):
            for k, v in zip(n.keys, n.values):
                if (isinstance(k, ast.Constant) and k.value == "ca_ausgestellt"
                        and isinstance(v, ast.Call) and isinstance(v.func, ast.Name)
                        and v.func.id == "zertifikat_von_ca"):
                    schluessel_ok = True
    pruefe("… und gibt den Wert UNVERAENDERT als ca_ausgestellt weiter", schluessel_ok)
    deps = [a for a in fn.args.args]
    pruefe("… ohne Anmelde-Dependency (die Maske hat noch keine Sitzung)",
           len(deps) == 0, [a.arg for a in deps])

# ── 3. Zugangsregel ─────────────────────────────────────────────────────────
print("── 3. Zugangsregel")
try:
    from backend import zugang_regel
except Exception as e:  # noqa: BLE001
    print("ABBRUCH: zugang_regel nicht importierbar (%s)" % e)
    sys.exit(2)
eintrag = zugang_regel.AUSNAHMEN.get(("GET", "/api/cert/status"))
pruefe("steht als Ausnahme in AUSNAHMEN", eintrag is not None)
pruefe("… mit Art 'oeffentlich'", bool(eintrag) and eintrag[0] == "oeffentlich", eintrag)

print("\nErgebnis: %d OK, %d FAIL" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
