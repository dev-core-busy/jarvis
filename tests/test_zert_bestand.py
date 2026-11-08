#!/usr/bin/env python3
"""Waechter: ein vorhandenes Serverzertifikat wird NIE neu erzeugt.

Hintergrund: ein neu erzeugtes selbstsigniertes Zertifikat entwertet jede
hinterlegte Vertrauensstellung (Browser-Autofill, Windows-/Android-App mit
Zertifikatspruefung, BSI M11). ``security.ensure_certificates`` laeuft bei
jedem Start – erzeugt es neu, bricht das Vertrauen nach jedem Update.

``test_bsi_n.py`` prueft nur die GESTALT (es gibt einen Bestands-Zweig). Hier
wird die WIRKUNG gemessen: in einem leeren Temp-Ordner erzeugen, dann erneut
aufrufen und Bytes vergleichen – auch nach Adresswechsel und mit einer
Adress-Warnung (die darf melden, aber nichts tauschen).

Positivkontrolle: der erste Aufruf muss alle drei Dateien erzeugen und ein
zweiter Erzeugungslauf (Schluessel entfernt) muss ein ANDERES Zertifikat
liefern – sonst koennte "gleiche Bytes" auch heissen, dass openssl
deterministisch waere und die Pruefung nichts unterscheidet. Fehlt sie: Exit 2.

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
"""
import contextlib
import hashlib
import io
import shutil
import sys
import tempfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

_ok = _fail = 0


def check(cond, label, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print("  OK   %s" % label)
    else:
        _fail += 1
        print("  FAIL %s%s" % (label, (" – %s" % detail) if detail else ""))


def abbruch(text):
    print("ABBRUCH (Exit 2): %s" % text)
    sys.exit(2)


def md5(pfad):
    return hashlib.md5(pfad.read_bytes()).hexdigest() if pfad.exists() else None


def stand(sec):
    return {n: md5(p) for n, p in (("crt", sec.CERT_FILE), ("key", sec.KEY_FILE),
                                   ("der", sec.CERT_DER_FILE))}


def aufruf(sec):
    """ensure_certificates mit abgefangener Ausgabe; liefert den Text."""
    puffer = io.StringIO()
    with contextlib.redirect_stdout(puffer):
        sec.ensure_certificates()
    return puffer.getvalue()


if not shutil.which("openssl"):
    abbruch("openssl fehlt")

from backend import security  # noqa: E402  (importiert backend.config nicht)

tmp = Path(tempfile.mkdtemp(prefix="zert_bestand_"))
try:
    security.CERTS_DIR = tmp
    security.CERT_FILE = tmp / "server.crt"
    security.KEY_FILE = tmp / "server.key"
    security.CERT_DER_FILE = tmp / "jarvis.cer"
    # Adress-/Namenssammlung gestubbt – fragt sonst externe Dienste ab.
    security._collect_server_ips = lambda: ["192.0.2.10"]
    security._collect_server_names = lambda: ["jarvis.beispiel.de"]
    security.zertifikat_adress_warnung = lambda: ""

    aufruf(security)
    erst = stand(security)
    if not all(erst.values()):
        abbruch("erster Aufruf hat nicht alle Dateien erzeugt: %r" % erst)

    # 1) Zweiter Start ohne Aenderung: alles byte-gleich.
    aufruf(security)
    check(stand(security) == erst, "zweiter Start laesst Zertifikat, Schluessel und DER unveraendert")

    # 2) Adresse hat sich geaendert UND die Adress-Warnung schlaegt an:
    #    melden ja, tauschen nein.
    security._collect_server_ips = lambda: ["198.51.100.7"]
    security._collect_server_names = lambda: ["anderer.beispiel.de"]
    security.zertifikat_adress_warnung = lambda: "Testgrund: Adresse fehlt"
    text = aufruf(security)
    check(stand(security) == erst, "Adresswechsel mit Warnung erzeugt NICHT neu")
    check("Testgrund" in text, "die Abweichung wird gemeldet", text[-200:])
    security.zertifikat_adress_warnung = lambda: ""

    # 3) Nur die DER-Fassung fehlt: aus dem BESTEHENDEN Zertifikat ableiten.
    security.CERT_DER_FILE.unlink()
    aufruf(security)
    check(stand(security) == erst,
          "fehlende DER-Datei wird aus dem bestehenden Zertifikat abgeleitet (gleiche Bytes)")

    # Positivkontrolle: fehlt der Schluessel, MUSS neu erzeugt werden – und das
    # Ergebnis muss sich unterscheiden, sonst misst (1)-(3) nichts.
    security.KEY_FILE.unlink()
    aufruf(security)
    neu = stand(security)
    if not all(neu.values()) or neu["crt"] == erst["crt"]:
        abbruch("Positivkontrolle: Neuerzeugung ohne Schluessel liefert kein neues "
                "Zertifikat – die Vergleiche oben unterscheiden nichts")
    check(True, "Positivkontrolle: ohne Schluessel entsteht ein neues Zertifikat")
    check(neu["der"] != erst["der"], "DER-Fassung folgt dem neuen Zertifikat")
finally:
    shutil.rmtree(tmp, ignore_errors=True)

print("\nErgebnis: %d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
