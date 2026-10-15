#!/usr/bin/env python3
"""Eigentuemer-Diagnose des Update-Managers (backend/update_manager.py).

Der Fall, um den es geht (ECHT, 2026-07-31): `/opt/jarvis/tests` gehoerte root,
alles andere jarvis. Der als jarvis laufende Update meldete nur

    Fehler: unable to unlink old 'tests/…': Keine Berechtigung
    Schwerwiegend: cannot create directory at 'tests/tools': Keine Berechtigung

Daraus geht nicht hervor, dass ein VERZEICHNIS dem falschen Benutzer gehoert.

Geprueft wird gegen ECHTE Git-Repositories in einem Temp-Ordner, nicht gegen
Attrappen: die Diagnose stuetzt sich auf `git ls-files` und `os.lstat`, ein Test
mit gefaelschten Rueckgaben wuerde genau das ueberspringen, was schiefgehen kann.

Fremde Eigentuemer lassen sich ohne root nicht herstellen. Der Test faelscht
deshalb NICHT die Rechte, sondern die EIGENE Kennung (`os.geteuid`) – aus Sicht
der Funktion ist das derselbe Zustand: „diese Pfade gehoeren jemand anderem".

Lauf:  python3 tests/test_update_permissions.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ergebnis = []


def pruefe(name, bedingung, detail=""):
    ergebnis.append((name, bool(bedingung)))
    print(("  ✅ " if bedingung else "  ❌ ") + name + ("" if bedingung or not detail else f" – {detail}"))


def abschnitt(t):
    print("\n" + t)


def git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)


def baue_repo(basis: Path) -> Path:
    """Kleines echtes Repo mit Unterverzeichnis – so wie /opt/jarvis/tests."""
    repo = basis / "repo"
    (repo / "tests" / "tools").mkdir(parents=True)
    (repo / "backend").mkdir()
    (repo / "readme.md").write_text("hallo\n", encoding="utf-8")
    (repo / "backend" / "main.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "tests" / "test_a.py").write_text("assert True\n", encoding="utf-8")
    (repo / "tests" / "tools" / "werkzeug.py").write_text("pass\n", encoding="utf-8")
    git("init", "-q", cwd=repo)
    git("config", "user.email", "t@t.t", cwd=repo)
    git("config", "user.name", "Test", cwd=repo)
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "start", cwd=repo)
    return repo


def main():
    print("=" * 70)
    print("Update-Manager: Eigentuemer-Diagnose")
    print("=" * 70)

    tmp = Path(tempfile.mkdtemp(prefix="jarvis_upd_"))
    try:
        repo = baue_repo(tmp)
        import backend.update_manager as UM
        UM.PROJECT_ROOT = repo

        abschnitt("1. Textmuster: welche Git-Ausgabe gilt als Rechteproblem?")
        # Der Kern: Git uebersetzt diese Meldungen NICHT, die errno-Beschreibung
        # dahinter schon. Ein Test nur mit englischem errno wuerde den echten Fall
        # (deutsches System) nicht abdecken.
        pruefe("deutsche Meldung von ECHT erkannt",
               UM._gitfehler_riecht_nach_rechten(
                   "Fehler: unable to unlink old 'tests/x.js': Keine Berechtigung"))
        pruefe("zweite Meldung von ECHT erkannt",
               UM._gitfehler_riecht_nach_rechten(
                   "Schwerwiegend: cannot create directory at 'tests/tools': Keine Berechtigung"))
        pruefe("englische Fassung erkannt",
               UM._gitfehler_riecht_nach_rechten(
                   "error: unable to unlink old 'tests/x.js': Permission denied"))
        pruefe("Gross-/Kleinschreibung egal",
               UM._gitfehler_riecht_nach_rechten("UNABLE TO UNLINK OLD 'a'"))
        pruefe("Merge-Konflikt gilt NICHT als Rechteproblem",
               not UM._gitfehler_riecht_nach_rechten(
                   "error: Your local changes would be overwritten by merge"))
        pruefe("Netzfehler gilt NICHT als Rechteproblem",
               not UM._gitfehler_riecht_nach_rechten(
                   "fatal: unable to access 'https://…': Could not resolve host"))

        abschnitt("2. Sauberes Repo: keine Diagnose, keine Falschmeldung")
        d = UM.diagnose_permissions()
        pruefe("alles in Ordnung gemeldet", d.get("ok"), str(d))
        # Wichtig: auch wenn der Text nach Rechten riecht, darf ohne echten Befund
        # nichts angehaengt werden – sonst schickt eine Fehldeutung den Betreiber
        # auf eine falsche Faehrte.
        roh = "error: unable to unlink old 'x': Permission denied"
        pruefe("kein Zusatz ohne tatsaechlichen Befund",
               UM._mit_diagnose(roh, roh) == roh)

        abschnitt("3. Fremdes Verzeichnis (der Fall von ECHT)")
        # Fremde Eigentuemer brauchen root. Stattdessen wird die eigene Kennung
        # verstellt – fuer die Funktion ist das derselbe Zustand.
        echt_geteuid = os.geteuid
        os.geteuid = lambda: echt_geteuid() + 12345
        try:
            d = UM.diagnose_permissions()
        finally:
            os.geteuid = echt_geteuid
        pruefe("Problem erkannt", not d.get("ok"), str(d)[:120])
        pruefe("Verzeichnisse werden genannt, nicht nur Dateien",
               any(p in ("tests", "tests/tools", "backend", ".") for p in d.get("paths", [])),
               str(d.get("paths"))[:150])
        pruefe("Repo-Wurzel ist dabei", "." in d.get("paths", []))
        pruefe(".git ist dabei (dorthin schreibt git beim Fetch)",
               ".git" in d.get("paths", []), str(d.get("paths"))[:150])
        h = d.get("hint", "")
        pruefe("Hinweis nennt den ausfuehrenden Benutzer", d.get("user", "") in h and len(h) > 80)
        pruefe("Hinweis erklaert das Elternverzeichnis",
               "VERZEICHNIS" in h, h[:120])
        pruefe("Hinweis nennt einen ausfuehrbaren Befehl",
               d.get("fix", "").startswith("sudo chown -R") and str(repo) in d.get("fix", ""),
               d.get("fix"))
        pruefe("Befehl steht auch im Hinweistext", d.get("fix", "") in h)
        # Der Befehl muss KOPIERBAR sein. Laesst sich der Name nicht aufloesen
        # (im Test der Fall), gehoert die numerische UID hinein – ein
        # `chown -R UID 1234:UID 1234` waere zwei Argumente statt einem und
        # wuerde beim Hineinkopieren das falsche Verzeichnis treffen.
        pruefe("chown-Befehl enthaelt keine Leerzeichen in der Kennung",
               " " not in d.get("fix", "").split(" -R ")[1].split(" ")[0],
               d.get("fix"))
        pruefe("chown-Befehl hat genau drei Argumente nach sudo",
               len(d.get("fix", "").split()) == 5, d.get("fix"))

        abschnitt("3b. Als root: KEIN Befund (root umgeht die Rechtepruefung)")
        # Ohne diese Schranke meldet die Diagnose aus einer Root-Shell heraus,
        # dass alle Dateien „jemand anderem" gehoeren, und schlaegt
        # `chown -R root:root` vor – das wuerde dem Dienstbenutzer sein
        # Verzeichnis entziehen. Beim Ausrollen auf DEV genau so passiert.
        os.geteuid = lambda: 0
        try:
            dr = UM.diagnose_permissions()
            textr = UM._mit_diagnose(roh, roh)
        finally:
            os.geteuid = echt_geteuid
        pruefe("als root: kein Problem gemeldet", dr.get("ok"), str(dr)[:120])
        pruefe("als root: kein chown-Vorschlag", "fix" not in dr, str(dr)[:120])
        pruefe("als root: Git-Meldung bleibt unveraendert", textr == roh, textr[:100])

        abschnitt("4. Anhaengen an die Git-Meldung")
        os.geteuid = lambda: echt_geteuid() + 12345
        try:
            text = UM._mit_diagnose(roh, roh)
        finally:
            os.geteuid = echt_geteuid
        pruefe("Original-Meldung bleibt erhalten", text.startswith(roh), text[:80])
        pruefe("Diagnose wurde angehaengt", "chown" in text and len(text) > len(roh) + 80)
        pruefe("als Warnung gekennzeichnet", "⚠" in text)

        abschnitt("5. venv wird NICHT durchsucht")
        # PROJECT_ROOT enthaelt im Betrieb ein venv mit ~100.000 Dateien, die git
        # gar nicht anfasst. Wuerde die Diagnose es durchlaufen, waere sie im
        # Fehlerfall minutenlang blockiert – ausgerechnet dann.
        venv = repo / "venv" / "lib" / "python3.13" / "site-packages"
        venv.mkdir(parents=True)
        for i in range(50):
            (venv / f"modul_{i}.py").write_text("pass\n", encoding="utf-8")
        os.geteuid = lambda: echt_geteuid() + 12345
        try:
            d2 = UM.diagnose_permissions()
        finally:
            os.geteuid = echt_geteuid
        pruefe("unversionierte venv-Dateien tauchen nicht auf",
               not any("venv" in p for p in d2.get("paths", [])),
               str([p for p in d2.get("paths", []) if "venv" in p])[:120])

        abschnitt("6. Kein Git-Repo: Diagnose schweigt statt zu werfen")
        leer = tmp / "keinrepo"
        leer.mkdir()
        UM.PROJECT_ROOT = leer
        try:
            d3 = UM.diagnose_permissions()
            pruefe("kein Absturz ohne Repo", isinstance(d3, dict))
            pruefe("meldet ok (nichts Verwertbares gefunden)", d3.get("ok"))
        except Exception as e:
            pruefe("kein Absturz ohne Repo", False, repr(e))
        # Fail-safe: eine kaputte Diagnose darf die Fehlermeldung nie schlucken.
        pruefe("Original-Meldung ueberlebt eine scheiternde Diagnose",
               UM._mit_diagnose(roh, roh) == roh)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ok = sum(1 for _, g in ergebnis if g)
    print("\n" + "=" * 70)
    print(f"ERGEBNIS: {ok}/{len(ergebnis)} Pruefungen bestanden")
    print("=" * 70)
    for name, g in ergebnis:
        if not g:
            print("  FEHLGESCHLAGEN: " + name)
    return ok == len(ergebnis)


if __name__ == "__main__":
    sys.exit(0 if main() else 1)
