#!/usr/bin/env python3
"""Waechter: Verwaltung der Portal-Info-Dokumente (Hochladen, Loeschen).

Seit 2026-10-28 koennen Administratoren im Ordnerfenster des Portals Dateien
hochladen und loeschen. Geprueft wird:

  A. Dateinamen: nur reine Namen mit bekannter Endung (kein Pfad, kein
     fuehrender Punkt, keine Steuerzeichen, Laengengrenze).
  B. Speichern: Inhalt kommt an, ein belegter Name wird nur mit ``ersetzen``
     ueberschrieben, die Groessengrenze bricht ab und hinterlaesst NICHTS
     (weder Ziel noch Zwischendatei), die Zwischendatei ist nie gelistet.
  C. Loeschen: nur ueber resolve() – nichts ausserhalb des Ordners, auch nicht
     ueber ``..`` oder einen Symlink nach draussen.
  D. Endpunkte (am Syntaxbaum von main.py): POST und DELETE haengen an
     ``require_local_auth``; die Liste meldet ``verwalten`` aus
     ``_user_is_admin(user)``.
  E. Oberflaechentexte: jeder neue i18n-Schluessel steht in DE und EN.

Laeuft vollstaendig im Sandkasten (JARVIS_INFO_DIR vor dem Import gesetzt).
Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""
import ast
import os
import re
import shutil
import stat
import sys
import tempfile
from pathlib import Path

W = Path(__file__).resolve().parent.parent
SANDKASTEN = Path(tempfile.mkdtemp(prefix="infofiles_"))
ORDNER = SANDKASTEN / "info"
os.environ["JARVIS_INFO_DIR"] = str(ORDNER)
sys.path.insert(0, str(W))

_ok = _fail = 0


def check(bed, text, info=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f" – {info}" if info else ""))


def wirft(fn, art):
    try:
        fn()
    except art:
        return True
    except Exception:  # noqa: BLE001 – falsche Ausnahme ist ein Befund, kein Absturz
        return False
    return False


try:
    from backend import info_files as I

    # Positivkontrolle: der Sandkasten ist wirklich das Ziel
    if Path(I.INFO_DIR).resolve() != ORDNER.resolve():
        print(f"ABBRUCH: INFO_DIR zeigt nicht in den Sandkasten ({I.INFO_DIR})")
        sys.exit(2)
    I.ensure_dir()

    print("A. Dateinamen")
    check(I.pruefe_name(" Handbuch 2026.pdf ") == "Handbuch 2026.pdf", "gueltiger Name, Rand entfernt")
    for schlecht in ["", "   ", "a/b.pdf", "..\\x.pdf", "../x.pdf", ".versteckt.pdf",
                     "x.exe", "ohne_endung", "a\x00b.pdf", "a\nb.pdf", "x" * 300 + ".pdf"]:
        check(wirft(lambda n=schlecht: I.pruefe_name(n), ValueError),
              f"abgewiesen: {schlecht[:30]!r}")

    print("B. Speichern")
    e = I.speichern("Merkblatt.pdf", [b"eins", b"zwei"])
    ziel = ORDNER / "Merkblatt.pdf"
    check(ziel.read_bytes() == b"einszwei", "Inhalt kommt vollstaendig an")
    check(e.get("name") == "Merkblatt.pdf" and e.get("size") == 8, "Rueckgabe nennt Name und Groesse", e)
    check(stat.S_IMODE(ziel.stat().st_mode) == 0o644, "Datei ist 0644 (fuer alle lesbar)")
    check(wirft(lambda: I.speichern("Merkblatt.pdf", [b"neu"]), FileExistsError),
          "belegter Name ohne ersetzen -> FileExistsError")
    check(ziel.read_bytes() == b"einszwei", "ohne ersetzen bleibt der alte Inhalt")
    I.speichern("Merkblatt.pdf", [b"neu"], ersetzen=True)
    check(ziel.read_bytes() == b"neu", "mit ersetzen wird ueberschrieben")

    alt = I.MAX_UPLOAD_BYTES
    I.MAX_UPLOAD_BYTES = 10
    try:
        zu_gross = wirft(lambda: I.speichern("Gross.pdf", [b"12345", b"67890", b"x"]), ValueError)
    finally:
        I.MAX_UPLOAD_BYTES = alt
    check(zu_gross, "Groessengrenze -> ValueError")
    check(not (ORDNER / "Gross.pdf").exists(), "nach Abbruch kein Ziel")
    reste = [p.name for p in ORDNER.iterdir() if p.name.startswith(".upload-")]
    check(not reste, "nach Abbruch keine Zwischendatei", reste)

    (ORDNER / ".upload-123-abc").write_bytes(b"halb")
    namen = [f["name"] for f in I.list_files()]
    check(".upload-123-abc" not in namen and "Merkblatt.pdf" in namen,
          "Zwischendatei nie in der Liste, echte Datei schon", namen)
    check(I.resolve(".upload-123-abc") is None, "Zwischendatei nicht abrufbar")
    (ORDNER / ".upload-123-abc").unlink()

    print("C. Loeschen")

    def loesche(n):
        # Eine Ausnahme ist hier ein Befund, kein Absturz – sonst endete der
        # Lauf ohne Bilanzzeile und waere von "nicht gelaufen" nicht zu trennen.
        try:
            return I.loeschen(n)
        except Exception as ex:  # noqa: BLE001
            return f"Ausnahme {type(ex).__name__}"

    aussen = SANDKASTEN / "aussen.pdf"
    aussen.write_bytes(b"darf bleiben")
    check(loesche("../aussen.pdf") is False and aussen.exists(), "'../' loescht nichts ausserhalb")
    if not aussen.exists():
        aussen.write_bytes(b"darf bleiben")
    (ORDNER / "Verweis.pdf").symlink_to(aussen)
    check(loesche("Verweis.pdf") is False and aussen.exists(),
          "Symlink nach draussen wird nicht geloescht und nicht verfolgt")
    check(loesche("gibtsnicht.pdf") is False, "unbekannter Name -> False")
    check(loesche("Merkblatt.pdf") is True and not ziel.exists(), "vorhandene Datei wird entfernt")

    print("D. Endpunkte (main.py, Syntaxbaum)")
    baum = ast.parse((W / "backend" / "main.py").read_text(encoding="utf-8"))
    funk = {}
    for knoten in ast.walk(baum):
        if isinstance(knoten, ast.AsyncFunctionDef):
            for d in knoten.decorator_list:
                if (isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute)
                        and isinstance(d.func.value, ast.Name) and d.func.value.id == "app"
                        and d.args and isinstance(d.args[0], ast.Constant)):
                    funk[(d.func.attr, d.args[0].value)] = knoten
    post = funk.get(("post", "/api/info_files"))
    dele = funk.get(("delete", "/api/info_files/{name}"))
    liste = funk.get(("get", "/api/info_files"))
    if not (post and dele and liste):
        print("ABBRUCH: Routen nicht gefunden", sorted(k for k in funk if "info_files" in k[1]))
        sys.exit(2)

    def abhaengigkeit(f):
        for arg, std in zip(reversed(f.args.args), reversed(f.args.defaults)):
            if arg.arg == "user" and isinstance(std, ast.Call) and getattr(std.func, "id", "") == "Depends":
                return getattr(std.args[0], "id", "") if std.args else ""
        return ""

    check(abhaengigkeit(post) == "require_local_auth", "POST /api/info_files an require_local_auth", abhaengigkeit(post))
    check(abhaengigkeit(dele) == "require_local_auth", "DELETE /api/info_files/{name} an require_local_auth", abhaengigkeit(dele))
    verwalten = False
    for k in ast.walk(liste):
        if isinstance(k, ast.Dict):
            for schl, wert in zip(k.keys, k.values):
                if (isinstance(schl, ast.Constant) and schl.value == "verwalten"
                        and isinstance(wert, ast.Call) and getattr(wert.func, "id", "") == "_user_is_admin"):
                    verwalten = True
    check(verwalten, "Liste meldet verwalten aus _user_is_admin(...)")

    print("E. Oberflaechentexte")
    i18n = (W / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
    js = (W / "frontend" / "js" / "info_files.js").read_text(encoding="utf-8")
    portal = (W / "frontend" / "portal.html").read_text(encoding="utf-8")
    benutzt = set(re.findall(r"T\('(portal\.info_[a-z_]+)'", js))
    benutzt |= set(re.findall(r'data-i18n="(portal\.info_[a-z_]+)"', portal))
    if len(benutzt) < 5:
        print("ABBRUCH: zu wenige i18n-Aufrufe in info_files.js gefunden", benutzt)
        sys.exit(2)
    for k in sorted(benutzt):
        n = len(re.findall(r"'" + re.escape(k) + r"'\s*:", i18n))
        check(n == 2, f"{k} in DE und EN", f"{n}x")
finally:
    shutil.rmtree(SANDKASTEN, ignore_errors=True)

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(0 if _fail == 0 else 1)
