#!/usr/bin/env python3
"""Waechter fuer die Bereitstellung (A) und die Code-Signatur (B) der AI-Maus.

⚠ DAS MODUL WIRD WIRKLICH AUSGEFUEHRT, nicht im Quelltext gelesen. Ob ein
falsches Kennwort ein vorhandenes Zertifikat zerstoert, ob die Rechte stimmen
und ob `ist_signiert` eine Signatur am PE-Header erkennt, kann eine
Textsuche nicht beantworten.

⚠ SANDKASTEN MIT EXIT 2: das Modul legt sonst `data/.aimouse_sign.pfx`,
`data/.aimousesignkey` und `data/ai_mouse_signatur.json` der LAUFENDEN
Installation an. Geprueft wird das als REGEL ueber alle Pfad-Attribute des
Moduls – eine gepflegte Namensliste laesst genau das neue Attribut fehlen
(Register, dort mit einer echten Schreibaktion auf die Produktivdaten bezahlt).

Aufruf:  python3 tests/test_ai_mouse_signatur.py
"""
from __future__ import annotations

import ast
import os
import struct
import sys
import tempfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

OK = 0
FAIL = 0


def check(text: str, bedingung) -> bool:
    """⚠ REIHENFOLGE (text, bedingung) – vertauscht ist eine nicht-leere
    Zeichenkette immer wahr, und der Lauf meldete „alles gruen", ohne eine
    einzige Bedingung ausgewertet zu haben (Register, test_jira_vorlagen)."""
    global OK, FAIL
    if isinstance(text, bool) or not isinstance(text, str):
        print("HARNESS-FEHLER: check(text, bedingung) – Argumente vertauscht?")
        sys.exit(2)
    if bedingung:
        OK += 1
        print("  OK   %s" % text)
        return True
    FAIL += 1
    print("  FAIL %s" % text)
    return False


def sicher(fn, *a, **kw):
    """Aufruf, der nicht werfen darf – sonst bricht der Lauf OHNE Bilanz ab
    und ist von „nicht gelaufen" nicht zu unterscheiden (Register)."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return e


# ── Sandkasten ──────────────────────────────────────────────────────────────
SAND = Path(tempfile.mkdtemp(prefix="aimouse-sig-test-"))
(SAND / "data").mkdir()

from backend import ai_mouse_signatur as sig  # noqa: E402

sig._DATA = SAND / "data"
sig.PFX_DATEI = sig._DATA / ".aimouse_sign.pfx"
sig.SCHLUESSEL_DATEI = sig._DATA / ".aimousesignkey"
sig.KONFIG_DATEI = sig._DATA / "ai_mouse_signatur.json"

# ⚠ DIE SCHRANKE ALS REGEL, NICHT ALS LISTE: JEDES Modul-Attribut, das auf
# einen Pfad zeigt, muss im Sandkasten liegen. Ein kuenftiges viertes faellt
# damit von selbst auf.
_pfade = {n: v for n, v in vars(sig).items()
          if isinstance(v, Path) and not n.startswith("__")}
_aussen = {n: str(v) for n, v in _pfade.items()
           if not str(v).startswith(str(SAND))}
if _aussen or len(_pfade) < 4:
    print("SANDKASTEN NICHT DICHT – Abbruch, damit der Test nicht in die "
          "echte Installation schreibt.")
    print("  ausserhalb: %s" % _aussen)
    print("  gefunden:   %s" % sorted(_pfade))
    sys.exit(2)

print("=== 1. Sandkasten ===")
check("alle %d Pfad-Attribute liegen im Wegwerf-Verzeichnis" % len(_pfade), True)


# ── Testzertifikat ──────────────────────────────────────────────────────────
def pfx_bauen(kennwort: str, tage: int = 365) -> bytes:
    """Ein echtes PKCS#12 – kein erfundenes Bytemuster.

    ⚠ MATERIAL, DAS EIN ECHTER KONSUMENT NICHT OEFFNET, BELEGT NICHTS
    (Register). Erzeugt wird deshalb mit derselben Bibliothek, mit der das
    Modul es spaeter liest.
    """
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.hazmat.primitives.serialization import pkcs12
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, "Testhaus Code Signing"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Testhaus GmbH"),
    ])
    jetzt = datetime.datetime.now(datetime.timezone.utc)
    zert = (x509.CertificateBuilder()
            .subject_name(name).issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(jetzt - datetime.timedelta(days=1))
            .not_valid_after(jetzt + datetime.timedelta(days=tage))
            .sign(key, hashes.SHA256()))
    schutz = (serialization.BestAvailableEncryption(kennwort.encode())
              if kennwort else serialization.NoEncryption())
    return pkcs12.serialize_key_and_certificates(
        b"test", key, zert, None, schutz)


def pe_bauen(mit_signatur: bool) -> bytes:
    """Eine minimale PE32+-Datei mit oder ohne Certificate-Table-Eintrag.

    Gebaut wird der ECHTE Aufbau, den `ist_signiert` liest: DOS-Stub mit
    e_lfanew, PE-Signatur, COFF-Header, Optional Header PE32+ und das Data
    Directory, dessen Index 4 die Signatur fuehrt.
    """
    opt_gr = 240                      # Optional Header PE32+ mit 16 Directories
    lf = 0x80                         # Versatz der PE-Signatur
    b = bytearray(b"\0" * (lf + 24 + opt_gr))
    b[0:2] = b"MZ"
    struct.pack_into("<I", b, 0x3C, lf)
    b[lf:lf + 4] = b"PE\0\0"
    struct.pack_into("<H", b, lf + 20, opt_gr)        # SizeOfOptionalHeader
    struct.pack_into("<H", b, lf + 24, 0x20B)         # Magic = PE32+
    if mit_signatur:
        dd = lf + 24 + 112                            # Data Directories (PE32+)
        struct.pack_into("<II", b, dd + 4 * 8, 0x1000, 0x2000)
    return bytes(b)


KENNWORT = "gehe1m!"
PFX = pfx_bauen(KENNWORT)

print("\n=== 2. Zertifikat pruefen, BEVOR etwas gespeichert wird ===")
r = sicher(sig._pkcs12_lesen, PFX, KENNWORT)
check("ein gueltiges PKCS#12 wird gelesen", isinstance(r, dict))
if isinstance(r, dict):
    check("der Betreff kommt heraus (%r)" % r.get("betreff"),
          r.get("betreff") == "Testhaus Code Signing")
    check("das Ablaufdatum kommt heraus", bool(r.get("gueltig_bis")))

r = sicher(sig._pkcs12_lesen, PFX, "falsch")
check("ein falsches Kennwort wirft SignaturFehler",
      isinstance(r, sig.SignaturFehler))
check("die Meldung nennt das Kennwort als moegliche Ursache",
      isinstance(r, Exception) and "Kennwort" in str(r))

r = sicher(sig._pkcs12_lesen, b"kein pkcs12", KENNWORT)
check("Muell wird abgewiesen", isinstance(r, sig.SignaturFehler))

print("\n=== 3. Hinterlegen ===")
r = sicher(sig.zertifikat_setzen, PFX, KENNWORT, "http://ts.example/tsa")
check("das Zertifikat laesst sich hinterlegen", isinstance(r, dict))
check("die PFX liegt auf Platte", sig.PFX_DATEI.is_file())
check("die PFX ist 0600 (nur der Dienstbenutzer)",
      sig.PFX_DATEI.exists()
      and (sig.PFX_DATEI.stat().st_mode & 0o777) == 0o600)
check("die Schluesseldatei ist 0600",
      sig.SCHLUESSEL_DATEI.exists()
      and (sig.SCHLUESSEL_DATEI.stat().st_mode & 0o777) == 0o600)
check("die Metadaten sind 0640",
      sig.KONFIG_DATEI.exists()
      and (sig.KONFIG_DATEI.stat().st_mode & 0o777) == 0o640)

roh = sig.KONFIG_DATEI.read_text(encoding="utf-8")
check("⚠ das Kennwort steht NICHT im Klartext in der Ablage",
      KENNWORT not in roh)
check("es steht verschluesselt drin", "pw_enc" in roh)
check("es laesst sich wieder entschluesseln",
      sig._entschluesseln(sig._laden().get("pw_enc", "")) == KENNWORT)

z = sicher(sig.zustand)
check("der Zustand nennt das Zertifikat", isinstance(z, dict) and z.get("zertifikat"))
check("⚠ der Zustand gibt WEDER Kennwort NOCH Zertifikat heraus",
      isinstance(z, dict)
      and KENNWORT not in repr(z)
      and "pw_enc" not in z and "pfx" not in repr(z).lower())
check("der Zeitstempel-Dienst ist uebernommen",
      isinstance(z, dict) and z.get("tsa") == "http://ts.example/tsa")

print("\n=== 4. Eine Fehleingabe zerstoert NICHTS ===")
# Register: „eine Fehleingabe darf keine laufende Konfiguration zerstoeren".
vorher_pfx = sig.PFX_DATEI.read_bytes()
vorher_meta = sig.KONFIG_DATEI.read_text(encoding="utf-8")
r = sicher(sig.zertifikat_setzen, pfx_bauen("anderes"), "falsch")
check("ein falsches Kennwort wird abgewiesen", isinstance(r, sig.SignaturFehler))
check("⚠ die vorhandene PFX ist UNVERAENDERT",
      sig.PFX_DATEI.read_bytes() == vorher_pfx)
check("⚠ die Metadaten sind UNVERAENDERT",
      sig.KONFIG_DATEI.read_text(encoding="utf-8") == vorher_meta)

r = sicher(sig.zertifikat_setzen, b"x" * (sig.MAX_PFX_BYTES + 1), KENNWORT)
check("eine zu grosse Datei wird abgewiesen", isinstance(r, sig.SignaturFehler))
check("die Meldung nennt die Grenze",
      isinstance(r, Exception) and "KB" in str(r))
check("die vorhandene PFX ist auch danach unveraendert",
      sig.PFX_DATEI.read_bytes() == vorher_pfx)

print("\n=== 5. Zeitstempel-Adresse ===")
check("eine http-Adresse wird angenommen",
      sig._tsa_normieren(" http://ts.example/x ") == "http://ts.example/x")
check("leer heisst ausdruecklich „ohne Zeitstempel\"", sig._tsa_normieren("") == "")
r = sicher(sig._tsa_normieren, "ftp://ts.example")
check("ein fremdes Schema wird ABGEWIESEN, nicht verworfen",
      isinstance(r, sig.SignaturFehler))
r = sicher(sig._tsa_normieren, "timestamp.example")
check("eine Adresse ohne Schema wird abgewiesen", isinstance(r, sig.SignaturFehler))

print("\n=== 6. „Ist signiert?\" wird am PE-HEADER gemessen ===")
p_sig = SAND / "mit.exe"
p_ohne = SAND / "ohne.exe"
p_sig.write_bytes(pe_bauen(True))
p_ohne.write_bytes(pe_bauen(False))
check("eine PE-Datei MIT Certificate-Table gilt als signiert", sig.ist_signiert(p_sig))
check("eine PE-Datei OHNE gilt als unsigniert", not sig.ist_signiert(p_ohne))
(SAND / "keine.exe").write_bytes(b"das ist kein PE")
check("etwas, das kein PE ist, gilt als unsigniert",
      not sig.ist_signiert(SAND / "keine.exe"))
check("eine fehlende Datei gilt als unsigniert",
      not sig.ist_signiert(SAND / "gibtsnicht.exe"))
(SAND / "kurz.exe").write_bytes(b"MZ")
check("eine abgeschnittene Datei gilt als unsigniert",
      not sig.ist_signiert(SAND / "kurz.exe"))

print("\n=== 7. Signieren ohne Zertifikat und ohne Werkzeug ===")
sig.zertifikat_entfernen()
check("nach dem Entfernen ist kein Zertifikat mehr da", not sig.zertifikat_da())
ok, grund = sicher(sig.signieren, p_ohne) or (None, None)
check("⚠ ohne Zertifikat: kein Erfolg, aber auch KEIN Fehler", ok is False and grund == "")
z = sig.zustand()
check("der Zustand sagt „kein Zertifikat\"", not z.get("zertifikat"))
check("die Metadaten des entfernten Zertifikats sind weg", not z.get("betreff"))

sig.zertifikat_setzen(PFX, KENNWORT, "")
_echt_werkzeug = sig.werkzeug_da
sig.werkzeug_da = lambda: False
try:
    ok, grund = sicher(sig.signieren, p_ohne) or (None, None)
    check("ohne osslsigncode: Fehlschlag MIT Grund", ok is False and bool(grund))
    check("der Grund nennt das fehlende Programm",
          isinstance(grund, str) and "osslsigncode" in grund)
    check("und den Weg, wie es dazukommt",
          isinstance(grund, str) and ("⤓" in grund or "apt-get" in grund))
finally:
    sig.werkzeug_da = _echt_werkzeug

print("\n=== 8. Abgelaufenes Zertifikat ===")
# ⚠ `werkzeug_da` WIRD GESTELLT. Ohne das haengt der Ausgang davon ab, ob auf
# DEM Rechner zufaellig osslsigncode installiert ist – der Lauf waere hier
# gruen und dort rot, ohne dass sich am Code etwas geaendert haette.
sig.zertifikat_setzen(pfx_bauen(KENNWORT, tage=365), KENNWORT, "")
d = sig._laden()
d["ablauf_ts"] = 1.0          # 1970 – sicher abgelaufen
d["gueltig_bis"] = "1970-01-01"
sig._speichern(d)
_echt_werkzeug = sig.werkzeug_da
sig.werkzeug_da = lambda: True
try:
    ok, grund = sicher(sig.signieren, p_ohne) or (None, None)
    check("ein abgelaufenes Zertifikat signiert nicht", ok is False)
    # ⚠ DER ABLAUF MUSS VOR DEM FEHLENDEN WERKZEUG GEMELDET WERDEN: sonst
    #   muesste ein Administrator erst osslsigncode nachinstallieren, um zu
    #   erfahren, dass sein Zertifikat laengst abgelaufen ist.
    check("und der Grund sagt warum",
          isinstance(grund, str) and "abgelaufen" in grund)
    sig.werkzeug_da = lambda: False
    ok2, grund2 = sicher(sig.signieren, p_ohne) or (None, None)
    check("⚠ der Ablauf sticht auch ein FEHLENDES Werkzeug",
          isinstance(grund2, str) and "abgelaufen" in grund2)
finally:
    sig.werkzeug_da = _echt_werkzeug
check("der Zustand meldet „abgelaufen\"", sig.zustand().get("abgelaufen") is True)

print("\n=== 9. Sperrlisten (die drei Geheimnisse) ===")
SB = (WURZEL / "backend" / "sandbox.py").read_text(encoding="utf-8")
# ⚠ OHNE KOMMENTARE UND DOCSTRINGS: die Begruendung nennt die Dateinamen
# woertlich, und der Waechter laese sonst sein eigenes Argument (18 belegte
# Faelle im Projekt).
def ohne_worte(quelle: str) -> str:
    import io
    import tokenize
    aus = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(quelle).readline):
            if tok.type == tokenize.COMMENT:
                continue
            aus.append(tok.string if tok.type != tokenize.STRING
                       or not tok.line.strip().startswith(('"""', "'''"))
                       else '""')
    except Exception:  # noqa: BLE001
        return quelle
    return " ".join(aus)


SB_OK = ohne_worte(SB)
check("Positivkontrolle: der Kommentarfilter hat wirklich gefiltert",
      "SCHWERSTE GEHEIMNIS" in SB and "SCHWERSTE GEHEIMNIS" not in SB_OK)




def liste_aus_sandbox(name: str):
    """Den Wert einer Modul-Konstanten per AST lesen.

    ⚠ NICHT ueber ein Prueffenster (`split(name)[1][:600]`): `PRIVATE_FILES_
    STRENG` kommt VIER mal in der Datei vor, und der erste Treffer ist eine
    Erwaehnung im Kommentar – die Pruefung meldete damit einen Fehler, den es
    nicht gab. Ein Fenster fester Groesse ist ohnehin eine Zeitbombe (Register).
    """
    baum = ast.parse(SB)
    for n in ast.walk(baum):
        if isinstance(n, ast.Assign):
            for z in n.targets:
                if isinstance(z, ast.Name) and z.id == name:
                    try:
                        return list(ast.literal_eval(n.value))
                    except Exception:  # noqa: BLE001
                        return []
    return []


STRENG = liste_aus_sandbox("PRIVATE_FILES_STRENG")
PRIV = liste_aus_sandbox("PRIVATE_FILES")
DENY = liste_aus_sandbox("_APP_DENY_REL")
check("Positivkontrolle: alle drei Listen sind auswertbar",
      len(STRENG) >= 5 and len(PRIV) >= 10 and len(DENY) >= 10)

# ⚠ MITGLIEDSCHAFT IN DER LISTE, NICHT VORKOMMEN IN DER DATEI: die PFX steht
# auch in PRIVATE_FILES_STRENG, und `".aimouse_sign.pfx" in SB` war damit
# wahr, selbst als der Eintrag aus _APP_DENY_REL entfernt war – die
# Gegenprobe blieb stumm. (Register: die Eigenschaft messen, nicht ein
# Vorkommen irgendwo.)
for datei in ("data/.aimouse_sign.pfx", "data/.aimousesignkey",
              "data/ai_mouse_signatur.json"):
    check("%s steht in _APP_DENY_REL" % datei, datei in DENY)
check("die PFX ist in PRIVATE_FILES_STRENG (0600)",
      "data/.aimouse_sign.pfx" in STRENG)
check("die Schluesseldatei ist in PRIVATE_FILES_STRENG (0600)",
      "data/.aimousesignkey" in STRENG)
check("die Metadaten sind in PRIVATE_FILES (0640)",
      "data/ai_mouse_signatur.json" in PRIV)

# ⚠ SHELL_SECRET_PATHS WIRD AUSGEFUEHRT, NICHT GELESEN. Die drei Namen stehen
# auch in _APP_DENY_REL – eine Textsuche ueber die Datei fand sie DORT und
# blieb gruen, als das Regex-Muster entfernt war. Gemessen gehoert, ob das
# kompilierte Muster den Pfad WIRKLICH trifft.
#
# `backend.sandbox` wird dafuer NICHT importiert: das zieht `backend.config`
# nach, und der echte Import schreibt die settings.json der laufenden
# Installation zurueck (Register). Der Regex-Ausdruck wird stattdessen per AST
# herausgeschnitten und hier selbst kompiliert.
import re  # noqa: E402

_secret_re = None
for _n in ast.walk(ast.parse(SB)):
    if isinstance(_n, ast.Assign) and any(
            isinstance(z, ast.Name) and z.id == "SHELL_SECRET_PATHS"
            for z in _n.targets):
        _q = ast.unparse(_n.value)
        _m = re.search(r"re\.compile\((.*)\)\s*$", _q, re.S)
        if _m:
            try:
                _secret_re = re.compile(ast.literal_eval(_m.group(1).split(",")[0]))
            except Exception:  # noqa: BLE001
                # Zusammengesetzt mit Flags o.ae. – dann alle Literale
                # zusammenkleben, das ist genau das, was Python auch tut.
                _teile = [ast.literal_eval(x) for x in
                          re.findall(r"(r?'(?:[^'\\]|\\.)*')", _m.group(1))]
                if _teile:
                    _secret_re = re.compile("".join(_teile))
        break

check("Positivkontrolle: SHELL_SECRET_PATHS liess sich kompilieren",
      _secret_re is not None)
if _secret_re is not None:
    # Positivkontrolle der MESSUNG: ein bekannter Bestandseintrag muss treffen –
    # sonst ist ein „trifft nicht" unten kein Befund, sondern ein kaputter Schnitt.
    check("Positivkontrolle: das Muster trifft einen BESTANDS-Pfad",
          bool(_secret_re.search("data/.sapkey")))
    for pfad in ("data/.aimouse_sign.pfx", "data/.aimousesignkey",
                 "data/ai_mouse_signatur.json"):
        check("SHELL_SECRET_PATHS trifft %s" % pfad,
              bool(_secret_re.search(pfad)))
    check("⚠ und es trifft NICHT irgendeinen harmlosen Pfad",
          not _secret_re.search("data/rag/handbuch.md"))

print("\n=== 10. Endpunkte (Regeln ueber den Syntaxbaum) ===")
MAIN = (WURZEL / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(MAIN)


def endpunkte():
    for n in ast.walk(BAUM):
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for d in n.decorator_list:
                txt = ast.unparse(d)
                if "/api/ai-mouse/admin/signatur" in txt \
                        or "/api/ai-mouse/admin/bereitstellung" in txt:
                    yield txt, n


gefunden = list(endpunkte())
check("es gibt die vier Admin-Endpunkte (3x Signatur, 1x Bereitstellung)",
      len(gefunden) == 4)
for txt, n in gefunden:
    args = [a.arg for a in n.args.args]
    vorgaben = {}
    for a, dflt in zip(n.args.args[-len(n.args.defaults):] if n.args.defaults else [],
                       n.args.defaults):
        vorgaben[a.arg] = ast.unparse(dflt)
    check("%s haengt an require_local_auth"
          % txt.split('"')[1] if '"' in txt else txt,
          "require_local_auth" in vorgaben.get("user", ""))

# ⚠ ES DARF KEINEN WEG GEBEN, DAS GEHEIMNIS WIEDER AUSZULESEN.
for txt, n in gefunden:
    if "get(" not in txt:
        continue
    quelle = ast.get_source_segment(MAIN, n) or ""
    check("der Lese-Endpunkt gibt NUR `zustand()` heraus, kein Geheimnis",
          "zustand()" in quelle and "PFX_DATEI" not in quelle
          and "read_bytes" not in quelle and "_entschluesseln" not in quelle)

check("es gibt KEINEN Endpunkt, der die PFX herunterlaedt",
      "PFX_DATEI" not in MAIN)

print("\n=== 11. Bauskript: signiert NACH dem Bau ===")
SK = (WURZEL / "deploy" / "ai_mouse_build.sh").read_text(encoding="utf-8")
check("das Bauskript ruft das Signaturmodul", "ai_mouse_signatur" in SK)
i_bau = SK.find("dotnet publish")
i_mv = SK.find('mv "$ZIEL/.AiMouse.exe.neu"')
i_sig = SK.find("ai_mouse_signatur")
check("Positivkontrolle: Bau und Einwechseln sind gefunden", i_bau > 0 and i_mv > 0)
check("⚠ signiert wird NACH dem Bau (sonst ist die Signatur ungueltig)",
      i_sig > i_bau)
check("⚠ und NACH dem Einwechseln der fertigen Datei", i_sig > i_mv)
check("„kein Zertifikat\" erzeugt KEINE Warnung (drei Zustaende)",
      '"AUS"' in SK and '"AUS")' in SK)
check("das Kennwort geht NIE als Argument (Prozessliste)",
      "-readpass" in (WURZEL / "backend" / "ai_mouse_signatur.py")
      .read_text(encoding="utf-8"))
MOD = (WURZEL / "backend" / "ai_mouse_signatur.py").read_text(encoding="utf-8")
check("⚠ `-pass` als Argument kommt NICHT vor", '"-pass"' not in MOD)

print("\n=== 12. Bereitstellung (A) ===")
sys.modules.pop("backend.ai_mouse", None)
import backend.ai_mouse as am  # noqa: E402

check("es gibt ein Feld fuer den Netzwerkpfad", hasattr(am, "PFAD_FELD"))
check("und einen Deckel dafuer", getattr(am, "MAX_PFAD", 0) > 0)

_echt_cfg = am.skill_config
am.skill_config = lambda: {}
try:
    check("ohne Eintrag ist der Pfad leer (= Download wie bisher)",
          am.freigabe_pfad() == "")
finally:
    am.skill_config = _echt_cfg

am.skill_config = lambda: {am.PFAD_FELD: "  \\\\srv\\freigabe\\AiMouse.exe  "}
try:
    check("ein Pfad wird getrimmt zurueckgegeben",
          am.freigabe_pfad() == "\\\\srv\\freigabe\\AiMouse.exe")
finally:
    am.skill_config = _echt_cfg

am.skill_config = lambda: {am.PFAD_FELD: "a\nb\rc"}
try:
    check("Zeilenumbrueche zerlegen die einzeilige Anzeige nicht",
          "\n" not in am.freigabe_pfad() and "\r" not in am.freigabe_pfad())
finally:
    am.skill_config = _echt_cfg

am.skill_config = lambda: {am.PFAD_FELD: "x" * 5000}
try:
    check("der Deckel greift", len(am.freigabe_pfad()) == am.MAX_PFAD)
finally:
    am.skill_config = _echt_cfg

# ⚠ DEN HEALTH-ENDPUNKT SCHNEIDEN, nicht die ganze Datei durchsuchen:
# `"freigabe_pfad": ai_mouse.freigabe_pfad()` steht auch im
# `admin/areas`-Endpunkt – die Suche ueber MAIN fand es DORT und blieb gruen,
# als es aus health entfernt war.
_health_q = ""
for n in ast.walk(BAUM):
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        if any("/api/ai-mouse/health" in ast.unparse(d) for d in n.decorator_list):
            _health_q = ast.get_source_segment(MAIN, n) or ""
check("Positivkontrolle: der health-Endpunkt wurde geschnitten",
      "paket_bereit" in _health_q)
check("health liefert den Pfad an die Kachel",
      '"freigabe_pfad"' in _health_q and "freigabe_pfad()" in _health_q)
check("health liefert den Signaturzustand",
      "zustand_kurz()" in _health_q)

print("\n=== 13. Oberflaeche ===")
JS = (WURZEL / "frontend" / "js" / "ai_mouse.js").read_text(encoding="utf-8")
check("die Kachel zeichnet die Freigabe-Zeile", "freigabeZeichnen" in JS)
check("⚠ der Pfad geht per textContent hinaus, NIE per innerHTML",
      "wert.textContent = pfad" in JS)
# ⚠ „Der Admin behaelt den Download-Knopf" wird NICHT hier geprueft.
#   `"_istAdmin" in JS and "am-dl-box" in JS` blieb gruen, als der Knopf
#   unbedingt versteckt wurde – beide Namen stehen ja weiterhin da. Die Zusage
#   ist eine SICHTBARKEITSFRAGE und gehoert in den ausgefuehrten Renderer:
#   tests/test_ai_mouse_freigabe_ui.js, Abschnitt 3.
check("die Sichtbarkeits-Zusage hat einen ausgefuehrten Waechter",
      (WURZEL / "tests" / "test_ai_mouse_freigabe_ui.js").is_file())
HTML = (WURZEL / "frontend" / "ai_mouse.html").read_text(encoding="utf-8")
check("es gibt den Container fuer die Freigabe-Zeile", 'id="am-freigabe"' in HTML)
check("und den Container um den Download-Knopf", 'id="am-dl-box"' in HTML)

SET = (WURZEL / "frontend" / "settings.html").read_text(encoding="utf-8")
for cid in ("am-sect-share", "am-sect-sign"):
    check("%s steht im Reiter" % cid, 'id="%s"' % cid in SET)
APP = (WURZEL / "frontend" / "js" / "app.js").read_text(encoding="utf-8")
# ⚠ REGEL, NICHT LISTE: jede .kb-section des Reiters muss klappbar gebunden
# sein – eine vergessene bleibt zu und laesst sich nicht oeffnen.
import re  # noqa: E402
sektionen = set(re.findall(r'id="(am-sect-[a-z]+)"', SET))
check("Positivkontrolle: es wurden Sektionen gefunden", len(sektionen) >= 5)
for s_id in sorted(sektionen):
    check("%s ist in app.js klappbar gebunden" % s_id,
          "'%s-hdr'" % s_id in APP)

ADM = (WURZEL / "frontend" / "js" / "ai_mouse_admin.js").read_text(encoding="utf-8")
check("der Reiter laedt den Signaturzustand beim Oeffnen",
      "signaturLaden" in ADM and "this.signaturLaden()" in ADM)
check("⚠ das Kennwortfeld wird nach dem Speichern GELEERT",
      "pw.value = ''" in ADM)
check("der Upload setzt KEINEN Content-Type (multipart-Trenner)",
      "FormData" in ADM
      and "'Content-Type': 'multipart" not in ADM)
check("Loeschen fragt nach", "del_ask" in ADM)

print("\n=== 14. i18n (Regel ueber die im CODE benutzten Schluessel) ===")
I18N = (WURZEL / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
benutzt = set(re.findall(r"t\('(am(?:share|sign)\.[a-z_]+)'", ADM))
benutzt |= set(re.findall(r'data-i18n(?:-html|-placeholder)?="(am(?:share|sign)\.[a-z_]+)"', SET))
benutzt |= set(re.findall(r"t\('(aimouse\.(?:share|copy)_[a-z]+)'", JS))
check("Positivkontrolle: es wurden Schluessel gefunden", len(benutzt) >= 15)
for k in sorted(benutzt):
    check("%s gibt es in DE UND EN" % k, I18N.count("'%s'" % k) == 2)

print("\n=== 14b. Eigentuemer-Erhalt: jeder Schreibweg ===")
# ⚠ WARUM DAS EINE REGEL IST UND KEINE LISTE: gemessen am 2026-09-22 auf DEV.
#   `deploy/ai_mouse_build.sh` ruft `signieren()`, und das Skript laeuft im
#   Regelfall ALS ROOT (Bootstrap 6g). Danach gehoerte die Ablage root, der
#   Dienst (User=jarvis) konnte sie nicht mehr lesen, `zertifikat_da()` meldete
#   False – die Signatur war ab dem ersten Bau still tot. Eine gepflegte Liste
#   der Schreibstellen laesst genau die naechste fehlen.
QUELLE_SIG = (WURZEL / "backend" / "ai_mouse_signatur.py").read_text(encoding="utf-8")
BAUM_SIG = ast.parse(QUELLE_SIG)


def _ohne_worte(quelle: str) -> str:
    """Kommentare UND Docstrings weg – sonst liest der Waechter seine eigene
    Begruendung (Register, achtzehn belegte Faelle)."""
    import io
    import tokenize
    zeilen = quelle.splitlines(keepends=True)
    roh = list(tokenize.generate_tokens(io.StringIO(quelle).readline))
    weg = [t for t in roh if t.type == tokenize.COMMENT]
    for k in ast.walk(ast.parse(quelle)):
        if isinstance(k, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                          ast.ClassDef)):
            d = ast.get_docstring(k, clean=False)
            if d is not None and k.body:
                ers = k.body[0]
                # ⚠ DIE ERSTE ZEILE MUSS EIN AUSDRUCK BLEIBEN. Ein Rumpf, der
                #   NUR aus dem Docstring besteht (hier: `class
                #   SignaturFehler`), waere sonst leer und die Datei nicht mehr
                #   parsebar – der Waechter prueefte dann gar nichts mehr
                #   (Register: wer den Quelltext umbaut, misst ihn nicht mehr).
                einr = " " * (ers.col_offset)
                zeilen[ers.lineno - 1] = einr + "''\n"
                for i in range(ers.lineno, ers.end_lineno):
                    zeilen[i] = "\n"
    for t in weg:
        i = t.start[0] - 1
        zeilen[i] = zeilen[i][:t.start[1]] + "\n"
    return "".join(zeilen)


SIG_OHNE = _ohne_worte(QUELLE_SIG)
check("Positivkontrolle: die Begruendung ist wirklich heraus",
      "VORAUSSETZUNG DAFUER" not in SIG_OHNE and "def _eigentuemer_erhalten" in SIG_OHNE)

# Jede Funktion, die eine der drei Ablagen SCHREIBT, muss danach den
# Eigentuemer sichern. Gemessen ueber den Syntaxbaum: `os.replace(<tmp>, ZIEL)`
# bzw. ein `os.chmod` auf eine Ablage-Konstante.
ABLAGEN = {"KONFIG_DATEI", "PFX_DATEI", "SCHLUESSEL_DATEI"}


def _namen(knoten):
    return {n.id for n in ast.walk(knoten) if isinstance(n, ast.Name)}


schreiber = []
for fn in [k for k in ast.walk(ast.parse(SIG_OHNE))
           if isinstance(k, ast.FunctionDef)]:
    schreibt = False
    for c in ast.walk(fn):
        if not isinstance(c, ast.Call):
            continue
        ziel = getattr(c.func, "attr", "")
        if ziel in ("replace", "chmod", "write_bytes", "write_text"):
            if _namen(c) & ABLAGEN:
                schreibt = True
    if schreibt:
        schreiber.append(fn)

check("Positivkontrolle: es wurden Schreibwege gefunden", len(schreiber) >= 2)
for fn in schreiber:
    ruft = any(isinstance(c, ast.Call)
               and getattr(c.func, "id", "") == "_eigentuemer_erhalten"
               for c in ast.walk(fn))
    check("%s() sichert den Eigentuemer" % fn.name, ruft)

# Und der Helfer selbst muss den Rueckfall auf das VERZEICHNIS haben - ohne ihn
# bliebe eine NEU von root angelegte Datei bei root (genau der gemessene Fall).
hlp = next((k for k in ast.walk(BAUM_SIG)
            if isinstance(k, ast.FunctionDef)
            and k.name == "_eigentuemer_erhalten"), None)
check("es gibt den Helfer", hlp is not None)
if hlp is not None:
    q = ast.unparse(hlp)
    check("  er faellt auf das Datenverzeichnis zurueck", "_DATA.stat()" in q)
    check("  er wirkt nur als root", "geteuid" in q)
    check("  und er wirft nie", "except Exception" in q)

print("\n=== 15. Aufraeumen ===")
import shutil  # noqa: E402
shutil.rmtree(SAND, ignore_errors=True)
check("der Sandkasten ist abgeraeumt", not SAND.exists())


# ── 15. Der Paket-Endpunkt hat einen Admin-Zweig (2026-09-22) ───────────────
"""Der Download liegt seit dem Umbau im ADMIN-REITER.

⚠ OHNE DIESEN ZWEIG WAERE DER KNOPF DORT EIN 403: `require_aimouse_access`
kennt bewusst keinen Admin-Bypass (Projektregel), und ein Administrator muss
die AI-Maus nicht selbst benutzen duerfen, um sie bereitzustellen.

KEINE Rechteerweiterung: das ZIP enthaelt die EXE, und die kann ohne Freigabe
nichts – `analyze` und `fragen` haengen unveraendert an `require_aimouse_access`.
"""
print("\n=== 15. Paket-Endpunkt: Freigabe ODER Administrator ===")
_m15 = (WURZEL / "backend" / "main.py").read_text(encoding="utf-8")

# Die Dependency selbst: geschnitten, damit nicht der Nachbar mitgemessen wird.
_i15 = _m15.find("def require_aimouse_paket")
_dep15 = _m15[_i15:_m15.find("\n@app.", _i15)] if _i15 > 0 else ""
check("es gibt require_aimouse_paket", _i15 > 0)
check("…und sie laesst Freigabe ODER Administrator durch",
      re.search(r"_user_may_use_aimouse\(user\)\s+or\s+_is_admin_user\(user\)",
                _dep15) is not None)

# Und der Endpunkt benutzt sie wirklich – „die Funktion allein nuetzt nichts".
_i15b = _m15.find('@app.get("/api/ai-mouse/paket")')
_ep15 = _m15[_i15b:_i15b + 400] if _i15b > 0 else ""
check("der Paket-Endpunkt benutzt sie", "require_aimouse_paket" in _ep15)

# Gegenrichtung: die Arbeits-Endpunkte bleiben eng.
for _pfad15 in ('"/api/ai-mouse/analyze"', '"/api/ai-mouse/fragen"'):
    _j15 = _m15.find("@app.post(" + _pfad15)
    if _j15 < 0:
        _j15 = _m15.find("@app.get(" + _pfad15)
    check("%s bleibt an require_aimouse_access" % _pfad15.strip('"'),
          _j15 > 0 and "require_aimouse_access" in _m15[_j15:_j15 + 400]
          and "require_aimouse_paket" not in _m15[_j15:_j15 + 400])

print("\n%d OK, %d FAIL" % (OK, FAIL))
sys.exit(1 if FAIL else 0)
