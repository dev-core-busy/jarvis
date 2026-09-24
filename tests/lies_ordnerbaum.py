#!/usr/bin/env python3
"""MESSUNG (veraendert nichts): in welcher REIHENFOLGE liefert die
Zielordner-Auswahl unter /wissen -> Informationsextraktor ihre Ordner?

Gemeldet wurde, dass der Baum "nicht hierarchisch sortiert" ist. Die Liste
entsteht in ``main._kb_list_subfolders`` und wird vom Client (wissen.js,
``updateFolderOptions``) in der GELIEFERTEN Reihenfolge gezeichnet – der
Client sortiert nicht. Gemessen wird deshalb die Server-Reihenfolge gegen
den Baum, den ein Mensch erwartet (Tiefensuche, Kinder direkt unter ihrem
Elternordner, je Ebene alphabetisch).

Gebaut wird der Baum aus dem gemeldeten Screenshot PLUS einem Ordner weiter
oben, der ebenfalls Unterordner hat: nur daran wird der Unterschied
sichtbar. Mit "Vertraege" allein (alphabetisch zuletzt) sieht selbst eine
falsche Reihenfolge zufaellig richtig aus.
"""
import ast
import os
import sys
import tempfile
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
MAIN = (WURZEL / "backend" / "main.py").read_text(encoding="utf-8")


def schneide(name: str) -> str:
    baum = ast.parse(MAIN)
    for k in baum.body:
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name == name:
            return ast.get_source_segment(MAIN, k)
    raise SystemExit(f"FUNKTION {name} NICHT GEFUNDEN – Messung wertlos")


# ── Sandkasten-Baum (aus dem gemeldeten Screenshot, plus ein frueher Zweig) ──
SOLL = [
    "01 Systembasis",
    "02 Stat. Patientenverwaltung",
    "03 Amb. Patientenverwaltung",
    "04 Station",
    "04 Station/A Visite",
    "04 Station/B Kurve",
    "05 Arzt",
    "06 Pflege",
    "07 Funktionsstelle",
    "08 Ambulanz",
    "09 OP",
    "10 Kommunikation",
    "11 Integration",
    "12 Entwicklungsdokumentation",
    "13 Telematikinfrastruktur",
    "Vertraege",
    "Vertraege/01 Patientenfuehrung",
    "Vertraege/02 Administration",
    "Vertraege/03 Stammdaten",
]


def main() -> int:
    sand = Path(tempfile.mkdtemp(prefix="ordnerbaum-"))
    wurzel_rel = "data/rag/handbuch"
    basis = sand / wurzel_rel
    for p in SOLL:
        (basis / p).mkdir(parents=True, exist_ok=True)

    # Umgebung fuer die geschnittene Funktion stellen
    ns = {
        "os": os,
        "Path": Path,
        "_kb_norm_rel": lambda p: str(p).strip("/"),
    }

    class _Knowledge:
        PROJECT_ROOT = sand

        @staticmethod
        def _is_pending_path(p):
            return "/pending/" in str(p).replace("\\", "/")

        @staticmethod
        def _safe_exists(p):
            return Path(p).exists()

    # Der Rumpf importiert aus backend.tools.knowledge -> Modul stellen
    import types
    mod = types.ModuleType("backend.tools.knowledge")
    mod.PROJECT_ROOT = _Knowledge.PROJECT_ROOT
    mod._is_pending_path = _Knowledge._is_pending_path
    mod._safe_exists = _Knowledge._safe_exists
    paket = types.ModuleType("backend")
    tools = types.ModuleType("backend.tools")
    sys.modules.setdefault("backend", paket)
    sys.modules["backend.tools"] = tools
    sys.modules["backend.tools.knowledge"] = mod

    # Der Rumpf ruft _kb_baum_key -> mitschneiden (eine gepflegte Liste liesse
    # genau die neueste Abhaengigkeit fehlen; der NameError saehe dann wie ein
    # Codefehler aus).
    exec(schneide("_kb_baum_key"), ns)
    exec(schneide("_kb_list_subfolders"), ns)
    ist = [e["path"][len(wurzel_rel) + 1:] for e in ns["_kb_list_subfolders"](wurzel_rel)]

    print("── IST (Server-Reihenfolge, so steht es im Pulldown) ──")
    for e in ns["_kb_list_subfolders"](wurzel_rel):
        rel = e["path"][len(wurzel_rel) + 1:]
        print("   " + "    " * (e["depth"] - 1) + rel.split("/")[-1])

    print()
    print("── SOLL (exakter Baum) ──")
    for p in SOLL:
        print("   " + "    " * p.count("/") + p.split("/")[-1])

    print()
    if ist == SOLL:
        print("ERGEBNIS: Reihenfolge stimmt (kein Befund)")
        return 0
    print("ERGEBNIS: Reihenfolge WEICHT AB")
    for i, (a, b) in enumerate(zip(ist + [""] * len(SOLL), SOLL + [""] * len(ist))):
        if a != b:
            print(f"   erste Abweichung an Position {i}: ist={a!r} soll={b!r}")
            break
    return 1


if __name__ == "__main__":
    sys.exit(main())
