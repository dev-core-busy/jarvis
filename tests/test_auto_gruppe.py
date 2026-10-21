#!/usr/bin/env python3
"""Neue Dateien in einem Speicherordner bekommen dessen Wissensgruppen.

Gemeldet 2026-10-21: Kundenlisten, die direkt auf eine SMB-Freigabe gelegt
wurden, landeten indiziert, aber ohne Wissensgruppe – jede neue Datei musste
von Hand der Gruppe 'Vertrieb' zugeordnet werden. Gemessen auf ECHT: die Freigabe
war bei keiner Gruppe eingetragen, und selbst ein Eintrag haette nur das
Upload-Ziel festgelegt.

Geprueft wird die EIGENSCHAFT, nicht die Schreibweise:
  1. ``knowledge_groups.automatisch_zuordnen`` laeuft WIRKLICH gegen ein
     Wegwerf-Manifest (Exit 2, wenn der Sandkasten nicht greift).
  2. Die Markierung ueberlebt Umbenennen/Loeschen/Aufraeumen.
  3. Als REGEL ueber den AST: der Indexlauf, der Verknuepfungs-Endpunkt und die
     Einzeldatei-Wege rufen die Funktionen wirklich auf.

    python3 tests/test_auto_gruppe.py
"""
import ast
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(name, cond, detail=""):
    global _ok, _fail
    if cond:
        _ok += 1
        print(f"  ✓ {name}")
    else:
        _fail += 1
        print(f"  ✗ {name}" + (f"  → {detail}" if detail else ""))


def section(t):
    print("\n" + t)


try:
    from backend import knowledge_groups as kg
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH – knowledge_groups nicht importierbar: {e}")
    sys.exit(2)

for name in ("automatisch_zuordnen", "gesehen_verschieben", "AUTO_GESEHEN"):
    if not hasattr(kg, name):
        print(f"ABBRUCH – knowledge_groups.{name} fehlt (Altstand?)")
        sys.exit(2)

TMP = Path(tempfile.mkdtemp(prefix="auto_gruppe_"))
kg.MANIFEST_PATH = TMP / ".groups.json"
if not str(kg.MANIFEST_PATH).startswith(str(TMP)):
    print("ABBRUCH – Sandkasten greift nicht")
    sys.exit(2)


def manifest(groups, assignments=None, gesehen=None):
    d = {"groups": groups, "assignments": assignments or {}}
    if gesehen is not None:
        d[kg.AUTO_GESEHEN] = gesehen
    kg.MANIFEST_PATH.write_text(json.dumps(d))


def lesen():
    return json.loads(kg.MANIFEST_PATH.read_text())


def gruppe(gid, folders, order=0):
    return {"id": gid, "name": gid, "color": "#000", "order": order, "folders": folders}


# ── 1. Grundregel ───────────────────────────────────────────────────────────
section("1. Neue Datei in einer Freigabe bekommt die Gruppe")
manifest([gruppe("vertrieb", ["mnt/rag/share_2"]), gruppe("ibs", ["data/rag/ibs"], 1)])
n = kg.automatisch_zuordnen(["/mnt/rag/share_2/Kundenliste_Musterstadt.csv"])
a = lesen()["assignments"]
check("Positivkontrolle: die gemeldete Lage wird zugeordnet",
      a.get("mnt/rag/share_2/Kundenliste_Musterstadt.csv") == ["vertrieb"], a)
check("Rueckgabe zaehlt die neu zugeordneten Dateien", n == 1, n)
check("Datei ist als gesehen markiert",
      "mnt/rag/share_2/Kundenliste_Musterstadt.csv" in lesen()[kg.AUTO_GESEHEN])

# Unterordner zaehlen mit
kg.automatisch_zuordnen(["/mnt/rag/share_2/Archiv/2025/alt.xlsx"])
check("Datei in einem Unterordner der Freigabe wird ebenfalls zugeordnet",
      lesen()["assignments"].get("mnt/rag/share_2/Archiv/2025/alt.xlsx") == ["vertrieb"])

# Projekt-relative Ordner (data/rag/…) mit absolutem Indexpfad
p_ibs = str(kg.PROJECT_ROOT / "data" / "rag" / "ibs" / "handbuch.md")
kg.automatisch_zuordnen([p_ibs])
check("Ordner unter data/rag: absoluter Indexpfad wird auf den Manifest-Schluessel normiert",
      lesen()["assignments"].get("data/rag/ibs/handbuch.md") == ["ibs"], lesen()["assignments"])

# ── 2. Praefix-Falle ────────────────────────────────────────────────────────
section("2. 'share_2' ist nicht Praefix von 'share_20'")
manifest([gruppe("vertrieb", ["mnt/rag/share_2"])])
# Eine passende Datei gehoert in DENSELBEN Lauf: nur dann wird ueberhaupt
# gespeichert – sonst waere "nicht markiert" trivial wahr (im Betrieb kommen
# immer viele Dateien zusammen; von der Gegenprobe aufgedeckt).
n = kg.automatisch_zuordnen(["/mnt/rag/share_20/fremd.csv", "/mnt/rag/share_2",
                             "/mnt/rag/share_2/passt.csv"])
d = lesen()
check("Positivkontrolle: der Lauf hat gespeichert", "mnt/rag/share_2/passt.csv" in d["assignments"])
check("Datei unter share_20 bleibt ohne Gruppe", "mnt/rag/share_20/fremd.csv" not in d["assignments"])
check("…und wird auch NICHT markiert (sonst waere ein spaeteres Verknuepfen wirkungslos)",
      "mnt/rag/share_20/fremd.csv" not in d.get(kg.AUTO_GESEHEN, []))
check("Der Ordner selbst ist keine Datei darin", "mnt/rag/share_2" not in d["assignments"])
check("Genau die passende Datei zugeordnet", n == 1, n)

# ── 3. Ausdrueckliche Wahl gewinnt ──────────────────────────────────────────
section("3. Eine vorhandene Zuordnung bleibt unangetastet")
manifest([gruppe("vertrieb", ["mnt/rag/share_2"]), gruppe("labman", [], 1)],
         assignments={"mnt/rag/share_2/x.csv": ["labman"]})
n = kg.automatisch_zuordnen(["/mnt/rag/share_2/x.csv"])
d = lesen()
check("Zuordnung 'labman' bleibt, vertrieb kommt NICHT dazu",
      d["assignments"]["mnt/rag/share_2/x.csv"] == ["labman"], d["assignments"])
check("…aber die Datei ist danach markiert", "mnt/rag/share_2/x.csv" in d[kg.AUTO_GESEHEN])
check("Rueckgabe 0", n == 0, n)

# ── 4. Von Hand ausgetragen bleibt ausgetragen ──────────────────────────────
section("4. Eine von Hand ausgetragene Datei kommt NICHT zurueck")
manifest([gruppe("vertrieb", ["mnt/rag/share_2"])])
kg.automatisch_zuordnen(["/mnt/rag/share_2/k.csv"])
kg.set_assignment("mnt/rag/share_2/k.csv", [])
check("Positivkontrolle: Austragen hat gewirkt",
      "mnt/rag/share_2/k.csv" not in lesen()["assignments"])
n = kg.automatisch_zuordnen(["/mnt/rag/share_2/k.csv"])
check("Zweiter Lauf ordnet sie NICHT wieder zu",
      "mnt/rag/share_2/k.csv" not in lesen()["assignments"] and n == 0, lesen()["assignments"])

# ── 5. Spaet verknuepfter Ordner ────────────────────────────────────────────
section("5. Ordner wird erst NACH der Indizierung verknuepft")
manifest([gruppe("vertrieb", []), gruppe("andere", ["data/rag/andere"], 1)])
kg.automatisch_zuordnen(["/mnt/rag/share_2/spaet.csv",
                         str(kg.PROJECT_ROOT / "data/rag/andere/x.md")])
check("Positivkontrolle: der Lauf hat gespeichert (andere Datei zugeordnet)",
      lesen()["assignments"].get("data/rag/andere/x.md") == ["andere"])
check("Ohne Verknuepfung: keine Zuordnung, keine Markierung",
      "mnt/rag/share_2/spaet.csv" not in lesen()["assignments"]
      and "mnt/rag/share_2/spaet.csv" not in lesen().get(kg.AUTO_GESEHEN, []))
kg.set_folder_groups("/mnt/rag/share_2", ["vertrieb"])
check("set_folder_groups speichert die Freigabe in der Manifest-Form",
      lesen()["groups"][0]["folders"] == ["mnt/rag/share_2"], lesen()["groups"])
kg.automatisch_zuordnen(["/mnt/rag/share_2/spaet.csv"])
check("Nach dem Verknuepfen wird die noch nie gesehene Datei zugeordnet",
      lesen()["assignments"].get("mnt/rag/share_2/spaet.csv") == ["vertrieb"])

# ── 6. Mehrere Gruppen ──────────────────────────────────────────────────────
section("6. Zwei Gruppen mit demselben/uebergeordneten Ordner")
manifest([gruppe("b", ["mnt/rag/share_2/Unter"], 1), gruppe("a", ["mnt/rag/share_2"], 0),
          gruppe("a2", ["mnt/rag/share_2"], 2)])
kg.automatisch_zuordnen(["/mnt/rag/share_2/Unter/x.csv", "/mnt/rag/share_2/y.csv"])
a = lesen()["assignments"]
check("Datei im Unterordner: Vereinigung in Gruppen-Reihenfolge",
      a.get("mnt/rag/share_2/Unter/x.csv") == ["a", "b", "a2"], a)
check("Datei daneben: nur die Gruppen des Oberordners",
      a.get("mnt/rag/share_2/y.csv") == ["a", "a2"], a)

# ── 7. Nichts verknuepft → kein Schreiben ───────────────────────────────────
section("7. Ohne Speicherordner wird nichts geschrieben")
manifest([gruppe("x", [])])
vorher = kg.MANIFEST_PATH.read_bytes()
n = kg.automatisch_zuordnen(["/mnt/rag/share_2/a.csv", str(kg.PROJECT_ROOT / "data/rag/y/z.md")])
check("Rueckgabe 0 und Manifest byte-gleich", n == 0 and kg.MANIFEST_PATH.read_bytes() == vorher)

# ── 8. Markierung zieht mit ─────────────────────────────────────────────────
section("8. Umbenennen, Loeschen und Aufraeumen nehmen die Markierung mit")
manifest([gruppe("g", ["data/rag/alt"])])
kg.automatisch_zuordnen([str(kg.PROJECT_ROOT / "data/rag/alt/d.md")])
kg.set_assignment("data/rag/alt/d.md", [])            # von Hand ausgetragen
kg.relocate_prefix("data/rag/alt", "data/rag/neu")
d = lesen()
check("relocate_prefix verschiebt die Markierung",
      d[kg.AUTO_GESEHEN] == ["data/rag/neu/d.md"], d.get(kg.AUTO_GESEHEN))
check("relocate_prefix zieht auch den Speicherordner mit", d["groups"][0]["folders"] == ["data/rag/neu"])
kg.automatisch_zuordnen([str(kg.PROJECT_ROOT / "data/rag/neu/d.md")])
check("…und die ausgetragene Datei bleibt auch am neuen Ort ausgetragen",
      "data/rag/neu/d.md" not in lesen()["assignments"])

kg.gesehen_verschieben("data/rag/neu/d.md", "data/rag/neu/e.md")
check("gesehen_verschieben: Einzeldatei umbenannt", lesen()[kg.AUTO_GESEHEN] == ["data/rag/neu/e.md"])
kg.gesehen_verschieben(str(kg.PROJECT_ROOT / "data/rag/neu/e.md"))
check("gesehen_verschieben ohne Ziel: Markierung weg (auch mit absolutem Pfad)",
      lesen()[kg.AUTO_GESEHEN] == [])

manifest([gruppe("g", ["data/rag/x"])], gesehen=["data/rag/x/bleibt.md", "data/rag/x/weg.md"])
kg.prune(["data/rag/x/bleibt.md"])
check("prune raeumt Markierungen verschwundener Dateien ab",
      lesen()[kg.AUTO_GESEHEN] == ["data/rag/x/bleibt.md"], lesen().get(kg.AUTO_GESEHEN))

manifest([gruppe("g", ["data/rag/x"])], gesehen=["data/rag/x/a.md", "data/rag/xy/b.md"])
kg.remove_prefix("data/rag/x")
check("remove_prefix raeumt NUR den Ordner ab (nicht 'xy')",
      lesen()[kg.AUTO_GESEHEN] == ["data/rag/xy/b.md"], lesen().get(kg.AUTO_GESEHEN))


# ── 9. Regeln ueber den AST ─────────────────────────────────────────────────
section("9. Verdrahtung (AST, ohne Kommentare und Docstrings)")


def funktion(datei, name):
    baum = ast.parse((ROOT / datei).read_text(encoding="utf-8"))
    for k in ast.walk(baum):
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name == name:
            return k
    return None


def ruft(knoten, name):
    """Echter Aufruf von ``name`` (auch als Attribut oder als Argument von to_thread)."""
    if knoten is None:
        return False
    for k in ast.walk(knoten):
        if isinstance(k, ast.Call):
            f = k.func
            if (isinstance(f, ast.Attribute) and f.attr == name) or \
               (isinstance(f, ast.Name) and f.id == name):
                return True
            for arg in k.args:
                if isinstance(arg, ast.Attribute) and arg.attr == name:
                    return True
    return False


lauf = funktion("backend/tools/knowledge.py", "_vector_index_lauf")
check("Positivkontrolle: _vector_index_lauf gefunden", lauf is not None)
check("_vector_index_lauf ruft automatisch_zuordnen", ruft(lauf, "automatisch_zuordnen"))
check("Positivkontrolle der Messung: _vector_index_lauf ruft NICHT 'gibt_es_nicht'",
      not ruft(lauf, "gibt_es_nicht"))
ep = funktion("backend/main.py", "assign_knowledge_folder_groups")
check("Verknuepfungs-Endpunkt ruft automatisch_zuordnen", ruft(ep, "automatisch_zuordnen"))
check("…und zwar im Thread (Manifest + Index sind Plattenarbeit)",
      ep is not None and any(isinstance(k, ast.Call) and isinstance(k.func, ast.Attribute)
                             and k.func.attr == "to_thread" and ruft(k, "automatisch_zuordnen")
                             for k in ast.walk(ep)))
check("purge_file_index vergisst die Markierung",
      ruft(funktion("backend/tools/knowledge.py", "purge_file_index"), "gesehen_verschieben"))
check("relocate_file_index zieht die Markierung mit",
      ruft(funktion("backend/tools/knowledge.py", "relocate_file_index"), "gesehen_verschieben"))

print(f"\nERGEBNIS: {_ok} OK, {_fail} FAIL")
sys.exit(0 if _fail == 0 else 1)
