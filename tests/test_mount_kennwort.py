#!/usr/bin/env python3
"""Waechter: Freigabe-Kennwoerter liegen verschluesselt, und "leer" loescht nicht.

Vorgabe 2026-09-13. Zwei Dinge, die zusammengehoeren:

  1. Die Zugangsdaten der SMB-/NFS-Freigaben standen im KLARTEXT in
     data/settings.json - als einziger Zugang des Projekts ohne
     Verschluesselung (SAP, VEMAS, Jira, Postfaecher haben sie laengst).
  2. ⚠ DABEI FIEL EIN BESTANDSFEHLER AUF: `update_mount` setzte
     `"password": data.get("password", "")` und LOESCHTE damit das Kennwort,
     sobald jemand nur die Adresse korrigierte. Der Platzhalter im Formular
     verspricht seit jeher "leer lassen = unveraendert", und im Client stand
     woertlich der Kommentar "leer = wird im Backend nicht geaendert WENN WIR
     DAS SO IMPLEMENTIEREN" - es wurde nie implementiert. Dieselbe Klasse wie
     der Benutzername-Verlust vom 2026-09-04, eine Zeile weiter.

Die Endpunkt-Rumpfe werden per `ast` geschnitten und WIRKLICH AUSGEFUEHRT -
eine Quelltext-Pruefung koennte "loescht das Kennwort" gar nicht beantworten.
Sandkasten mit Exit 2: ein Lauf, der die echte settings.json oder die echte
Schluesseldatei anfasst, waere teurer als der Fehler, den er sucht.
"""
import ast
import io
import os
import tokenize as _tk
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OK = FAIL = 0


def check(t, b, info=""):
    global OK, FAIL
    if not isinstance(b, bool):
        print(f"ABBRUCH: check('{t}') bekam {type(b).__name__} statt bool")
        sys.exit(2)
    print(("  OK   " if b else "  FAIL ") + t + (f"  [{info}]" if info and not b else ""))
    if b:
        OK += 1
    else:
        FAIL += 1


def sicher(fn, *a, **kw):
    """Nie ungeprueft dereferenzieren - ein Wurf darf den Lauf nicht ohne
    Bilanzzeile beenden."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return f"<WURF: {type(e).__name__}: {e}>"


def quelle(rel):
    return io.open(ROOT / rel, encoding="utf-8").read()


# ── SANDKASTEN ──────────────────────────────────────────────────────────────
SAND = Path(tempfile.mkdtemp(prefix="mountpw_"))
import backend.mount_credentials as MC

_echt_key = MC.SCHLUESSEL_DATEI
_echt_data = MC.DATA_DIR
MC.DATA_DIR = SAND / "data"
MC.SCHLUESSEL_DATEI = MC.DATA_DIR / ".mountkey"
if SAND not in MC.SCHLUESSEL_DATEI.resolve().parents:
    print(f"ABBRUCH: Schluesselpfad zeigt aus dem Sandkasten heraus: "
          f"{MC.SCHLUESSEL_DATEI}")
    sys.exit(2)

try:
    print("=== 1. Rundlauf und Schluesseldatei ===")
    enc = sicher(MC.verschluesseln, "Geheim#1!")
    check("verschluesseln liefert etwas anderes als den Klartext",
          isinstance(enc, str) and enc and "Geheim#1!" not in enc, str(enc)[:40])
    check("und zurueck ergibt denselben Klartext",
          sicher(MC.entschluesseln, enc) == "Geheim#1!")
    check("leerer Klartext bleibt leer (kein Token fuer nichts)",
          MC.verschluesseln("") == "" and MC.entschluesseln("") == "")
    check("die Schluesseldatei wurde angelegt", MC.SCHLUESSEL_DATEI.exists())
    modus = MC.SCHLUESSEL_DATEI.stat().st_mode & 0o777
    check("sie ist 0600 (nie kurz 0644)", modus == 0o600, oct(modus))

    print("\n=== 2. Der Eintrag traegt keinen Klartext mehr ===")
    m = {"type": "smb", "source": "//srv/share", "username": "u",
         "password": "Klartext!"}
    MC.setze_kennwort(m, "Klartext!")
    check("Klartext-Feld ist weg", MC.FELD_ALT not in m, str(sorted(m)))
    check("verschluesseltes Feld ist da", bool(m.get(MC.FELD_ENC)))
    check("der Klartext kommt in keinem Wert vor",
          not any("Klartext!" in str(v) for v in m.values()), str(m))
    check("kennwort_aus liest ihn zurueck", MC.kennwort_aus(m) == "Klartext!")
    check("hat_kennwort sagt ja", MC.hat_kennwort(m) is True)
    MC.setze_kennwort(m, "")
    check("leer setzen LOESCHT (das ist Sache des Aufrufers, nicht stille Regel)",
          not MC.hat_kennwort(m))

    print("\n=== 3. Altbestand im Klartext bleibt lesbar ===")
    alt = {"password": "Alt#1"}
    check("kennwort_aus liest auch das alte Feld", MC.kennwort_aus(alt) == "Alt#1")
    check("hat_kennwort erkennt es ohne Schluessel", MC.hat_kennwort(alt) is True)
    beide = {"password": "ALT", MC.FELD_ENC: MC.verschluesseln("NEU")}
    check("stehen BEIDE da, gewinnt der verschluesselte (der gepflegte Stand)",
          MC.kennwort_aus(beide) == "NEU")

    print("\n=== 4. Migration ===")
    mounts = [{"password": "A1"}, {"password": ""}, {MC.FELD_ENC: MC.verschluesseln("B2")},
              "kaputt", {"username": "ohne"}]
    n = sicher(MC.migriere, mounts)
    check("Migration lief ohne Wurf", isinstance(n, int), str(n))
    check("der Klartext-Eintrag ist umgezogen",
          MC.FELD_ALT not in mounts[0] and MC.kennwort_aus(mounts[0]) == "A1",
          str(mounts[0]))
    check("das leere Altfeld ist entfernt", MC.FELD_ALT not in mounts[1])
    check("der bereits verschluesselte bleibt unveraendert",
          MC.kennwort_aus(mounts[2]) == "B2")
    check("ein kaputter Eintrag wirft nicht", mounts[3] == "kaputt")
    check("zweiter Lauf aendert nichts mehr (idempotent)",
          MC.migriere(mounts) == 0)
    check("keine Liste -> 0, kein Wurf", MC.migriere("nix") == 0)

    print("\n=== 5. FAIL-SAFE: Verschluesselung kaputt -> Kennwort bleibt ===")
    orig_f = MC._fernet
    MC._fernet = lambda: (_ for _ in ()).throw(MC.MountKennwortFehler("kein cryptography"))
    try:
        rest = [{"password": "NICHT VERLIEREN"}]
        n2 = sicher(MC.migriere, rest)
        check("Migration wirft nicht", isinstance(n2, int), str(n2))
        check("⚠ das Kennwort bleibt erhalten (Verlust waere schlimmer als Klartext)",
              rest[0].get("password") == "NICHT VERLIEREN", str(rest[0]))
        check("hat_kennwort arbeitet OHNE Schluessel (fuer has_password)",
              MC.hat_kennwort({MC.FELD_ENC: "x"}) is True)
    finally:
        MC._fernet = orig_f

    # ⚠ MIT ECHTEM FERNET: der Werfer oben beantwortet eine ANDERE Frage
    # (fehlendes cryptography), und seine Meldung ist dort richtig. Gemeint ist
    # hier der haeufigste Fall - ein Restore ohne die Schluesseldatei.
    fehler = sicher(MC.entschluesseln, "unbrauchbarer-token")
    check("entschluesseln nennt die Abhilfe statt 'InvalidToken'",
          isinstance(fehler, str) and "mountkey" in fehler.lower(), str(fehler)[:110])

    # ── Die Endpunkt-Rumpfe AUSFUEHREN ──────────────────────────────────────
    print("\n=== 6. update_mount: leer = UNVERAENDERT (der Bestandsfehler) ===")
    mq = quelle("backend/main.py")
    baum = ast.parse(mq)
    rumpf = None
    for n in ast.walk(baum):
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "update_mount":
            rumpf = n
    check("update_mount gefunden", rumpf is not None)

    # Nur den Teil ab dem Neubau des Eintrags - davor liegen Broker-Aufrufe.
    src = ast.get_source_segment(mq, rumpf) or ""
    i = src.find("_alt = mounts[idx]")
    check("der Kennwort-Teil ist im Schnitt (Positivkontrolle)", i > 0, str(i))
    teil = src[i:src.find("_save_mounts_config", i)] if i > 0 else ""
    teil = "\n".join(z[4:] if z.startswith("    ") else z for z in teil.splitlines())

    def lauf(daten, bestand):
        # `_mc` stellen: die Import-Zeile steht VOR dem Schnittanfang. Ein
        # NameError daraus sieht wie ein Codefehler aus und ist keiner.
        ns = {"mounts": [dict(bestand)], "idx": 0, "data": daten,
              "source": "//srv/neu", "mp": Path("/mnt/x"), "_mc": MC}
        exec(compile(ast.parse(teil), "<schnitt>", "exec"), ns)
        return ns["mounts"][0]

    vorhanden = {"type": "smb", "source": "//srv/alt", "username": "u",
                 "mountpoint": "/mnt/x", "auto_mount": False}
    MC.setze_kennwort(vorhanden, "BleibDa!")

    e1 = sicher(lauf, {"type": "smb", "username": "u2"}, vorhanden)
    check("leeres Kennwortfeld -> Kennwort BLEIBT", 
          isinstance(e1, dict) and MC.kennwort_aus(e1) == "BleibDa!", str(e1)[:110])
    check("und der Benutzername wird uebernommen",
          isinstance(e1, dict) and e1.get("username") == "u2")
    check("auto_mount ueberlebt das Bearbeiten (Zustand, nicht Formular)",
          isinstance(e1, dict) and e1.get("auto_mount") is False, str(e1)[:110])

    e2 = sicher(lauf, {"type": "smb", "username": "u", "password": "NeuesPW"}, vorhanden)
    check("ausgefuelltes Feld ersetzt das Kennwort",
          isinstance(e2, dict) and MC.kennwort_aus(e2) == "NeuesPW")
    check("und legt es verschluesselt ab",
          isinstance(e2, dict) and MC.FELD_ALT not in e2 and bool(e2.get(MC.FELD_ENC)))

    print("\n=== 6b. add_mount legt NIE Klartext ab ===")
    # AUSGEFUEHRT, nicht gesucht: die erste Fassung prueste nur den Wortlaut
    # `m.get("password", "")` - eine Sabotage mit `data.get(...)` blieb gruen.
    rumpf_add = None
    for n in ast.walk(baum):
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "add_mount":
            rumpf_add = n
    check("add_mount gefunden", rumpf_add is not None)
    src_a = ast.get_source_segment(mq, rumpf_add) or ""
    ia = src_a.find("mount_entry = {")
    check("der Eintrags-Teil ist im Schnitt (Positivkontrolle)", ia > 0, str(ia))
    teil_a = src_a[ia:src_a.find("mounts.append", ia)] if ia > 0 else ""
    teil_a = "\n".join(y[4:] if y.startswith("    ") else y for y in teil_a.splitlines())

    def lauf_add(daten):
        ns = {"data": daten, "mount_type": "smb", "source": "//srv/s",
              "mp": Path("/mnt/x"), "_mc": MC}
        exec(compile(ast.parse(teil_a), "<schnitt-add>", "exec"), ns)
        return ns["mount_entry"]

    ea = sicher(lauf_add, {"username": "u", "password": "FrischesPW"})
    check("der Eintrag traegt KEIN Klartext-Feld",
          isinstance(ea, dict) and MC.FELD_ALT not in ea, str(ea)[:110])
    check("der Klartext kommt in keinem Wert vor",
          isinstance(ea, dict) and not any("FrischesPW" in str(v) for v in ea.values()),
          str(ea)[:110])
    check("und er ist zurueckzulesen",
          isinstance(ea, dict) and MC.kennwort_aus(ea) == "FrischesPW")
    eb = sicher(lauf_add, {"username": "u"})
    check("ohne Kennwort entsteht kein leeres Feld",
          isinstance(eb, dict) and not MC.hat_kennwort(eb), str(eb)[:110])

    print("\n=== 6c. Die Migration ist VERDRAHTET ===")
    # Die Funktion allein nuetzt nichts - sie muss aus der EINEN Stelle laufen,
    # die die Freigabenliste liest, damit auch der Autostart-Pfad sie erwischt.
    mig = None
    for n in ast.walk(baum):
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "_mounts_migrieren":
            mig = n
    check("_mounts_migrieren gefunden", mig is not None)
    _ruft = set()
    if mig is not None:
        for n in ast.walk(mig):
            if isinstance(n, ast.Call):
                nm = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
                if nm:
                    _ruft.add(nm)
    check("sie ruft mount_credentials.migriere()", "migriere" in _ruft, str(sorted(_ruft)))
    _holt = None
    for n in ast.walk(baum):
        if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name == "_get_mounts_config":
            _holt = n
    _ruft2 = set()
    if _holt is not None:
        for n in ast.walk(_holt):
            if isinstance(n, ast.Call):
                nm = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
                if nm:
                    _ruft2.add(nm)
    check("und _get_mounts_config ruft sie (Autostart-Pfad)",
          "_mounts_migrieren" in _ruft2, str(sorted(_ruft2)))

    print("\n=== 7. Kein Klartext-Pfad mehr in main.py ===")
    zeilen = mq.splitlines(keepends=True)
    weg = []
    try:
        for tok in _tk.generate_tokens(io.StringIO(mq).readline):
            if tok.type == _tk.COMMENT:
                weg.append((tok.start, tok.end))
    except Exception:
        pass
    for (z1, s1), (z2, s2) in reversed(weg):
        if z1 == z2 and z1 - 1 < len(zeilen):
            zl = zeilen[z1 - 1]
            zeilen[z1 - 1] = zl[:s1] + " " * (s2 - s1) + zl[s2:]
    mq_code = "".join(zeilen)
    check("Kommentar-Entferner greift (Positivkontrolle)",
          "def update_mount" in mq_code and "WENN WIR DAS SO IMPLEMENTIEREN" not in mq_code)
    check('kein m.get("password") mehr im Mount-Weg',
          'm.get("password", "")' not in mq_code)
    check("beide Broker-Uebergaben holen es ueber den Helfer",
          mq_code.count("_mc_kennwort(m)") == 2, str(mq_code.count("_mc_kennwort(m)")))
    check("has_password braucht den Schluessel nicht",
          "_mc_hat_kennwort(m)" in mq_code)

    print("\n=== 8. Sperrlisten ===")
    sq_roh = quelle("backend/sandbox.py")
    # ⚠ OHNE KOMMENTARE: die Begruendungen NENNEN den Dateinamen, und der
    # Waechter las damit seinen eigenen Text – die Gegenprobe "Eintrag
    # entfernt" blieb gruen (fuenfzehnter Fall dieser Klasse im Projekt).
    _z = sq_roh.splitlines(keepends=True)
    _w = []
    try:
        for tok in _tk.generate_tokens(io.StringIO(sq_roh).readline):
            if tok.type == _tk.COMMENT:
                _w.append((tok.start, tok.end))
    except Exception:
        pass
    for (z1, s1), (z2, s2) in reversed(_w):
        if z1 == z2 and z1 - 1 < len(_z):
            zl = _z[z1 - 1]
            _z[z1 - 1] = zl[:s1] + " " * (s2 - s1) + zl[s2:]
    sq = "".join(_z)
    check("Kommentar-Entferner greift bei sandbox.py (Positivkontrolle)",
          "_APP_DENY_REL" in sq and "KLARTEXT-Kennwort jedes" not in sq)
    for name in ("_APP_DENY_REL", "PRIVATE_FILES_STRENG", "SHELL_SECRET_PATHS"):
        i = sq.find(name + " =")
        j = sq.find("\n\n", i) if i > 0 else -1
        block = sq[i:j] if i > 0 else ""
        check(f"{name} kennt .mountkey", ".mountkey" in block, f"i={i}")

    print("\n=== 9. secret_reveal entschluesselt ===")
    rq = quelle("backend/secret_reveal.py")
    fn = None
    for n in ast.walk(ast.parse(rq)):
        if isinstance(n, ast.FunctionDef) and n.name == "mount":
            fn = n
    check("Bereich mount gefunden", fn is not None)
    src_r = ast.get_source_segment(rq, fn) or ""
    check("er liest ueber kennwort_aus, nicht roh",
          "kennwort_aus" in src_r and 'get("password")' not in src_r, src_r[-160:])
finally:
    MC.SCHLUESSEL_DATEI, MC.DATA_DIR = _echt_key, _echt_data
    shutil.rmtree(SAND, ignore_errors=True)

print(f"\n{'='*60}\nErgebnis: {OK} OK, {FAIL} FAIL\n{'='*60}")
sys.exit(1 if FAIL else 0)
