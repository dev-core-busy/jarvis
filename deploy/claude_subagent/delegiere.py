#!/usr/bin/env python3
"""Client fuer den Jarvis-Skill "Claude Subagent".

Gibt eine eng umrissene Codeaufgabe an Jarvis ab und holt das Ergebnis als
PATCH zurueck. Der Patch wird NICHT automatisch angewandt – das entscheidet
Claude nach dem Lesen.

ZUGANG – je Jarvis-Installation zu setzen, es gibt KEINE Vorgabe
    Schluessel  $JARVIS_CSA_KEY  oder  ~/.jarvis-csa-key
    Adresse     $JARVIS_CSA_URL  oder  ~/.jarvis-csa-url

    Bewusst KEIN voreingestellter Host: derselbe Client laeuft gegen jede
    Jarvis-Installation. Eine Vorgabe waere die Adresse genau einer davon – bei
    der naechsten falsch, und der Fehler saehe wie ein Schluesselproblem aus
    (ein fremder Server kennt den Schluessel nicht und antwortet 401).

    Der Schluessel gehoert NICHT ins Repo. ~/.jarvis-csa-key liegt ausserhalb,
    die Umgebungsvariable erst recht.

AUFRUF
    delegiere.py senden --spec-datei auftrag.txt \\
                        --dateien frontend/css/chat.css \\
                        --riegel tests/test_branding_aliase.py
    delegiere.py holen <id>
    delegiere.py warten <id>          # bis fertig, dann Patch auf stdout

Die Basis (Commit-Hash) wird aus dem lokalen Repo ermittelt; der Client bricht
ab, wenn der Arbeitsbaum an den Zieldateien schmutzig ist – ein Patch gegen
einen anderen Stand liesse sich nachher nicht sauber anwenden.
"""

import argparse
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

def fehler(text: str, code: int = 1):
    print(f"FEHLER: {text}", file=sys.stderr)
    sys.exit(code)


def schluessel() -> str:
    k = os.environ.get("JARVIS_CSA_KEY", "").strip()
    if k:
        return k
    p = Path.home() / ".jarvis-csa-key"
    if p.is_file():
        return p.read_text(encoding="utf-8").strip()
    fehler("Kein Delegations-Schluessel. Setze $JARVIS_CSA_KEY oder lege "
           "~/.jarvis-csa-key an (erzeugt wird er in Jarvis unter /claude).", 2)


def basis_url() -> str:
    u = os.environ.get("JARVIS_CSA_URL", "").strip()
    if not u:
        p = Path.home() / ".jarvis-csa-url"
        if p.is_file():
            u = p.read_text(encoding="utf-8").strip()
    if not u:
        fehler("Keine Jarvis-Adresse. Setze $JARVIS_CSA_URL oder lege "
               "~/.jarvis-csa-url an (z.B. https://jarvis.firma.de). Es gibt "
               "bewusst keine Vorgabe – der Client laeuft gegen jede "
               "Installation.", 2)
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    return u.rstrip("/")


def _ctx() -> ssl.SSLContext:
    """Jarvis benutzt ein selbst ausgestelltes Zertifikat (backend/security.py).

    Die Pruefung ist deshalb aus. Das ist hier vertretbar, weil der Schluessel
    nur zu DIESEM Server passt und ueber ihn keine fremden Daten laufen – aber
    es ist eine bewusste Ausnahme, kein Versehen.
    """
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def ruf(pfad: str, methode: str = "GET", rumpf: dict | None = None) -> dict:
    daten = json.dumps(rumpf).encode("utf-8") if rumpf is not None else None
    req = urllib.request.Request(basis_url() + pfad, data=daten, method=methode)
    req.add_header("X-Jarvis-Key", schluessel())
    if daten:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60, context=_ctx()) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read().decode("utf-8"))
        except Exception:  # noqa: BLE001
            return {"ok": False, "error": f"HTTP {e.code}"}
    except Exception as e:  # noqa: BLE001
        fehler(f"{type(e).__name__}: {e}")


def git(*args) -> str:
    p = subprocess.run(["git", *args], capture_output=True, text=True)
    return (p.stdout or "").strip()


def pruefe_arbeitsbaum(dateien: list) -> str:
    """Basis-Commit ermitteln und sicherstellen, dass der Patch spaeter passt."""
    kopf = git("rev-parse", "HEAD")
    if not kopf:
        fehler("Kein git-Repository im aktuellen Verzeichnis.")
    # Liegt der lokale Stand auf origin/master? Der Server klont von dort.
    vor = git("rev-list", "--count", "origin/master..HEAD")
    if vor and vor != "0":
        fehler(f"Der lokale Stand liegt {vor} Commit(s) VOR origin/master. "
               f"Jarvis klont origin/master – pushe zuerst, oder delegiere nicht.")
    schmutzig = [z[3:] for z in git("status", "--porcelain").splitlines()]
    kollision = [d for d in dateien if any(s.strip() == d for s in schmutzig)]
    if kollision:
        fehler("Diese Zieldateien haben lokale Aenderungen – der Patch liesse "
               "sich nachher nicht sauber anwenden: " + ", ".join(kollision))
    return kopf


def cmd_senden(a) -> None:
    spec = Path(a.spec_datei).read_text(encoding="utf-8") if a.spec_datei else a.spec
    if not spec or not spec.strip():
        fehler("Kein Auftragstext (--spec oder --spec-datei).")
    dateien = [x.strip() for x in a.dateien.split(",") if x.strip()]
    if not dateien:
        fehler("--dateien fehlt: nenne die Dateien, die geaendert werden duerfen.")
    basis = a.basis or pruefe_arbeitsbaum(dateien)

    antwort = ruf("/api/claude/jobs", "POST", {
        "spec": spec, "basis": basis, "dateien": dateien, "riegel": a.riegel,
    })
    if not antwort.get("ok"):
        fehler(antwort.get("error", "unbekannt"))
    print(antwort["id"])


def _bericht(job: dict) -> int:
    """Ergebnis ausgeben. Rueckgabe = Exitcode (0 nur bei angenommenem Patch)."""
    erg = job.get("ergebnis") or {}
    print(f"# Auftrag {job.get('id')} – {job.get('status')}", file=sys.stderr)
    if job.get("fehler"):
        print(f"# Fehler: {job['fehler']}", file=sys.stderr)
        return 1
    if not erg:
        return 1
    print(f"# Riegel {erg.get('riegel')}: "
          f"{'GRUEN' if erg.get('riegel_ok') else 'ROT'}", file=sys.stderr)
    print(f"# Dateien: {', '.join(erg.get('dateien') or []) or '(keine)'}", file=sys.stderr)
    if not erg.get("angenommen"):
        print("# VERWORFEN:", file=sys.stderr)
        for g in erg.get("gruende") or []:
            print(f"#   - {g}", file=sys.stderr)
        aus = (erg.get("riegel_ausgabe") or "").strip()
        if aus:
            print("# Riegel-Ausgabe (letzte Zeilen):", file=sys.stderr)
            for z in aus.splitlines()[-15:]:
                print(f"#   {z}", file=sys.stderr)
        return 1
    print("# ANGENOMMEN – Patch folgt auf stdout", file=sys.stderr)
    print(erg.get("diff") or "")
    return 0


def cmd_holen(a) -> None:
    antwort = ruf(f"/api/claude/jobs/{a.id}")
    if not antwort.get("ok"):
        fehler(antwort.get("error", "unbekannt"))
    sys.exit(_bericht(antwort["job"]))


def cmd_warten(a) -> None:
    ende = time.time() + a.timeout
    while time.time() < ende:
        antwort = ruf(f"/api/claude/jobs/{a.id}")
        if not antwort.get("ok"):
            fehler(antwort.get("error", "unbekannt"))
        job = antwort["job"]
        if job.get("status") in ("fertig", "fehler"):
            sys.exit(_bericht(job))
        time.sleep(a.takt)
    fehler(f"Auftrag {a.id} ist nach {a.timeout}s noch nicht fertig.")


def main() -> None:
    p = argparse.ArgumentParser(description="Codeaufgabe an Jarvis abgeben")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("senden")
    s.add_argument("--spec")
    s.add_argument("--spec-datei")
    s.add_argument("--dateien", required=True,
                   help="kommagetrennt, relativ zum Repo")
    s.add_argument("--riegel", required=True,
                   help="Testdatei, die das Ergebnis beweist (tests/*.py|js)")
    s.add_argument("--basis", help="Commit-Hash (Vorgabe: HEAD des Arbeitsbaums)")
    s.set_defaults(fn=cmd_senden)

    h = sub.add_parser("holen")
    h.add_argument("id")
    h.set_defaults(fn=cmd_holen)

    w = sub.add_parser("warten")
    w.add_argument("id")
    w.add_argument("--timeout", type=int, default=900)
    w.add_argument("--takt", type=int, default=10)
    w.set_defaults(fn=cmd_warten)

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
