#!/usr/bin/env python3
"""Waechter fuer ``deploy/wissensgraph_uebernahme.py`` (Option C des
Vergleichsberichts 2026-11-01): fertigen Graphen eines anderen Servers
uebernehmen, nur wenn die Zeitstempel passen.

Alles laeuft in einem Sandkasten (Quell- und Zielwurzel unter /tmp); Exit 2,
wenn ein Pfad hinausfuehrt. Geprueft wird die WIRKUNG am Dateisystem:
  1. pruefen zaehlt passend / geaendert / fehlt / unlesbar richtig
  2. einspielen lehnt ab: als root, bei Abweichung, bei vorhandenem Graphen
  3. einspielen uebernimmt NUR quellen/ + aliasse.json (ohne Schalter keine
     Widersprueche, kein Wiki, kein graph.json/queue.json/status.json)
  4. --ersetzen sichert den vorhandenen Stand, --trotzdem nimmt Abweichungen mit
  5. das Skript importiert nichts aus backend (kein Nebenweg in die Konfiguration)

    python3 tests/test_wissensgraph_uebernahme.py
"""
import ast
import importlib.util
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKRIPT = ROOT / "deploy" / "wissensgraph_uebernahme.py"
_ok = _fail = 0


def check(name, cond, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  ✓ {name}")
    else:
        _fail += 1
        print(f"  ✗ {name}" + (f"  → {detail}" if detail else ""))


if not SKRIPT.is_file():
    print("ABBRUCH – deploy/wissensgraph_uebernahme.py fehlt")
    sys.exit(2)
spec = importlib.util.spec_from_file_location("wg_uebernahme", SKRIPT)
U = importlib.util.module_from_spec(spec)
spec.loader.exec_module(U)

TMP = Path(tempfile.mkdtemp(prefix="wg_uebernahme_"))
QUELLE = TMP / "quelle_graph"          # entpackter data/graph des Quellservers
ZIEL = TMP / "ziel"                    # Wurzel des Zielservers


def aufbauen():
    if TMP.exists():
        shutil.rmtree(TMP)
    (QUELLE / "quellen").mkdir(parents=True)
    (QUELLE / "wiki").mkdir()
    dok = {"data/rag/a/eins.md": 1000.25, "data/rag/a/zwei.md": 2000.5, "data/rag/b/drei.md": 3000.75}
    for i, (m, mt) in enumerate(dok.items()):
        (QUELLE / "quellen" / f"{i:032x}.json").write_text(
            json.dumps({"pfad": m, "mtime": mt, "entitaeten": [], "relationen": []}), encoding="utf-8")
        lp = ZIEL / m
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text("x", encoding="utf-8")
        os.utime(lp, (mt, mt))
    for n in ("aliasse.json", "widersprueche.json", "graph.json", "queue.json", "status.json"):
        (QUELLE / n).write_text("{}", encoding="utf-8")
    (QUELLE / "wiki" / "index.json").write_text("{}", encoding="utf-8")
    return dok


_einspielen_echt = U.einspielen


def _einspielen_sicher(*a, **k):
    """Ein Wurf ist ein BEFUND (FAIL mit Bilanz), kein Abbruch des Waechters."""
    try:
        return _einspielen_echt(*a, **k)
    except Exception as e:  # noqa: BLE001
        return 99, f"Wurf: {type(e).__name__}: {e}"


U.einspielen = _einspielen_sicher
dok = aufbauen()
if not str(U.lokaler_pfad("data/rag/a/eins.md", ZIEL)).startswith(str(TMP)):
    print("ABBRUCH – Sandkasten greift nicht")
    sys.exit(2)

print("\n1. pruefen")
e = U.pruefen(QUELLE, ZIEL)
check("Positivkontrolle: drei Quellen gelesen", e["gesamt"] == 3, e)
check("alle Zeitstempel passen", e["gleich"] == 3 and not e["geaendert"] and not e["fehlt"], e)
os.utime(ZIEL / "data/rag/a/zwei.md", (2001.0, 2001.0))
(ZIEL / "data/rag/b/drei.md").unlink()
(QUELLE / "quellen" / "kaputt.json").write_text("{nicht json", encoding="utf-8")
(QUELLE / "quellen" / "boese.json").write_text(json.dumps({"pfad": "data/../../etc/passwd", "mtime": 1}),
                                              encoding="utf-8")
e = U.pruefen(QUELLE, ZIEL)
check("geaenderte Datei erkannt", e["geaendert"] == ["data/rag/a/zwei.md"], e)
check("fehlende Datei erkannt", e["fehlt"] == ["data/rag/b/drei.md"], e)
check("unlesbare und Pfad mit '..' werden GENANNT", sorted(e["kaputt"]) == ["boese.json", "kaputt.json"], e)
check("mtime genau verglichen (Nachkommastellen)", e["gleich"] == 1, e)
check("main pruefen: Exit 1 bei Abweichung", U.main(["pruefen", str(QUELLE), "--wurzel", str(ZIEL)]) == 1)
os.utime(ZIEL / "data/rag/a/zwei.md", (2000.5, 2000.5))
(ZIEL / "data/rag/b/drei.md").write_text("x", encoding="utf-8")
os.utime(ZIEL / "data/rag/b/drei.md", (3000.75, 3000.75))
check("nur unlesbare Dateien: pruefen meldet trotzdem Abweichung (Exit 1)",
      U.main(["pruefen", str(QUELLE), "--wurzel", str(ZIEL)]) == 1, U.pruefen(QUELLE, ZIEL))
os.utime(ZIEL / "data/rag/a/zwei.md", (2001.0, 2001.0))
(ZIEL / "data/rag/b/drei.md").unlink()

print("\n2. einspielen lehnt ab")
code, text = U.einspielen(QUELLE, ZIEL, euid=0)
check("als root: abgelehnt, nichts geschrieben", code == 1 and "root" in text and not (ZIEL / "data/graph").exists(), text)
code, text = U.einspielen(QUELLE, ZIEL, euid=1000)
check("Abweichungen ohne --trotzdem: abgelehnt mit Zahlen", code == 1 and "4 von 5" in text
      and not (ZIEL / "data/graph").exists(), text)
check("main einspielen ohne --uebernehmen schreibt nichts",
      U.main(["einspielen", str(QUELLE), "--wurzel", str(ZIEL)]) == 1 and not (ZIEL / "data/graph").exists())

dok = aufbauen()
code, text = U.einspielen(QUELLE, ZIEL, euid=1000)
g = ZIEL / "data" / "graph"
print("\n3. einspielen uebernimmt nur Quellen und Entscheidungen")
check("passend: uebernommen", code == 0 and len(list((g / "quellen").glob("*.json"))) == 3, text)
check("aliasse.json uebernommen", (g / "aliasse.json").is_file())
fremd = [n for n in ("widersprueche.json", "graph.json", "queue.json", "status.json", "wiki") if (g / n).exists()]
check("NICHT uebernommen: Widersprueche, Wiki, abgeleiteter Graph, Laufzustand", not fremd, fremd)
check("Ordner geschlossen (0750)", oct(g.stat().st_mode & 0o777) == "0o750", oct(g.stat().st_mode & 0o777))
check("mtime der Quelldateien bleibt erhalten (copy2)",
      all((g / "quellen" / p.name).stat().st_mtime == p.stat().st_mtime for p in (QUELLE / "quellen").glob("*.json")))
check("Meldung nennt den Neustart", "neu starten" in text, text)
check("kein Zwischenordner bleibt liegen", not (ZIEL / "data" / "graph.uebernahme-tmp").exists())

print("\n4. vorhandener Graph, --ersetzen, --trotzdem, --mit-widerspruechen")
code, text = U.einspielen(QUELLE, ZIEL, euid=1000)
check("vorhandener Graph: abgelehnt ohne --ersetzen", code == 1 and "--ersetzen" in text, text)
check("abgelehnt: keine Sicherung angelegt (nichts bewegt)", not list((ZIEL / "data").glob("graph.vor-uebernahme-*")))
(g / "quellen" / "eigene.json").write_text("{}", encoding="utf-8")
code, text = U.einspielen(QUELLE, ZIEL, ersetzen=True, mit_widerspruechen=True, euid=1000)
sich = sorted((ZIEL / "data").glob("graph.vor-uebernahme-*"))
check("--ersetzen: alter Stand gesichert (samt eigener Datei)", code == 0 and len(sich) == 1
      and (sich[0] / "quellen" / "eigene.json").is_file(), (code, text, sich))
check("--mit-widerspruechen: Widersprueche und Wiki dabei", (g / "widersprueche.json").is_file()
      and (g / "wiki" / "index.json").is_file())
check("ersetzt, nicht vermischt: eigene Datei nicht im neuen Stand", not (g / "quellen" / "eigene.json").exists())
shutil.rmtree(g)
for s_ in sich:
    shutil.rmtree(s_)
os.utime(ZIEL / "data/rag/a/zwei.md", (2001.0, 2001.0))
code, text = U.einspielen(QUELLE, ZIEL, trotzdem=True, euid=1000)
check("--trotzdem: trotz Abweichung uebernommen", code == 0 and len(list((g / "quellen").glob("*.json"))) == 3, text)

print("\n5. keine Abhaengigkeit von backend")
baum = ast.parse(SKRIPT.read_text(encoding="utf-8"))
importe = [ast.unparse(n) for n in ast.walk(baum) if isinstance(n, (ast.Import, ast.ImportFrom))]
check("Positivkontrolle: Importe gelesen", len(importe) >= 3, importe)
check("kein Import aus backend (der echte config-Import schreibt settings.json)",
      not [i for i in importe if "backend" in i], importe)
check("startet keinen Dienst selbst", "systemctl" not in "".join(
    ast.unparse(c) for c in ast.walk(baum) if isinstance(c, ast.Call)))

shutil.rmtree(TMP, ignore_errors=True)
print(f"\nErgebnis: {_ok} ok, {_fail} fehlgeschlagen")
sys.exit(1 if _fail else 0)
