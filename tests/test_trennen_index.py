#!/usr/bin/env python3
"""Waechter: Trennen einer Netzwerk-Freigabe nimmt deren Dateien aus dem Index.

Gebaut nach der Vorgabe vom 2026-09-08 ("ein manuelles Trennen der SMB Freigabe
soll die Dateien aus der Vector-DB entfernen").

⚠ DIE EIGENTLICHE FRAGE IST NICHT "wird geloescht", SONDERN "wird das RICHTIGE
geloescht". Ein Praefix-Vergleich auf einem verrutschten oder leeren Pfad leert
den halben Index, und niemand sieht es, bis eine Suche ins Leere laeuft.
Deshalb laufen die Funktionen hier WIRKLICH - gegen Attrappen des Speichers,
nicht gegen den echten Bestand.
"""
import ast
import os
import sys
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

OK = FAIL = 0


def check(beschreibung, bedingung, detail=""):
    global OK, FAIL
    if isinstance(beschreibung, bool):
        print("\033[31mABBRUCH: check(bedingung, text) - Argumente vertauscht\033[0m")
        sys.exit(2)
    if bedingung:
        OK += 1
        print(f"  \033[32m✓\033[0m {beschreibung}")
    else:
        FAIL += 1
        print(f"  \033[31m✗\033[0m {beschreibung}" + (f"  → {detail}" if detail else ""))


def sicher(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:  # noqa: BLE001
        return f"__FEHLER__ {type(e).__name__}: {e}"


def schneide(datei: Path, name: str) -> str:
    """Holt EINE Funktion/Methode per AST - kein Textfenster (Register: ein zu
    weiter Schnitt misst fremden Code und ist trivial wahr)."""
    baum = ast.parse(datei.read_text(encoding="utf-8"))
    for kn in ast.walk(baum):
        if isinstance(kn, (ast.FunctionDef, ast.AsyncFunctionDef)) and kn.name == name:
            return ast.get_source_segment(datei.read_text(encoding="utf-8"), kn)
    return ""


MAIN = WURZEL / "backend" / "main.py"
KNOW = WURZEL / "backend" / "tools" / "knowledge.py"
VS = WURZEL / "backend" / "tools" / "vector_store.py"

for datei, name in ((MAIN, "_mount_index_raeumen"), (MAIN, "unmount_share"),
                    (KNOW, "purge_folder_index"), (VS, "remove_path_prefix")):
    if not schneide(datei, name):
        print(f"\033[31mABBRUCH: {datei.name}:{name} gibt es nicht (umbenannt?)\033[0m")
        sys.exit(2)

# ═════════════════════════════════════════════════════════════════════════════
print("\033[1m1. Der Praefix trifft genau seinen Ordner\033[0m")
# Die ECHTE Methode, ausgefuehrt gegen eine Mini-Attrappe des Speichers.
# Sonst pruefte man die Nachbildung gegen sich selbst.


class _Lock:
    def __enter__(self): return self
    def __exit__(self, *a): return False


class Store:
    def __init__(self, pfade):
        self._meta = [{"file_path": p, "mtime": 0.0} for p in pfade]
        self._lock = _Lock()
        self.gespeichert = 0

    def _vectors_at(self, idx):
        return idx

    def _rebuild(self, meta, vecs):
        self._meta = meta

    def save(self):
        self.gespeichert += 1


ns = {}
exec(compile(ast.parse("class X:\n" + "\n".join(
    "    " + z for z in schneide(VS, "remove_path_prefix").splitlines())),
    "<vs>", "exec"), ns)
Store.remove_path_prefix = ns["X"].remove_path_prefix

st = Store(["/mnt/jarvis-kb/share_1/a.pdf", "/mnt/jarvis-kb/share_1/tief/b.docx",
            "/mnt/jarvis-kb/share_10/c.pdf", "/mnt/jarvis-kb/share_2/d.pdf",
            "/opt/jarvis/data/knowledge/e.md"])
weg = sicher(st.remove_path_prefix, "/mnt/jarvis-kb/share_1")
check("die Dateien der getrennten Freigabe fallen", weg == 2, repr(weg))
uebrig = [m["file_path"] for m in st._meta]
check("⚠ share_10 bleibt (Praefix-Falle) – dieselbe Falle wie bei den Einhaengepunkten",
      "/mnt/jarvis-kb/share_10/c.pdf" in uebrig, str(uebrig))
check("die Nachbar-Freigabe bleibt", "/mnt/jarvis-kb/share_2/d.pdf" in uebrig)
check("das lokale Wissen bleibt", "/opt/jarvis/data/knowledge/e.md" in uebrig)

# ═════════════════════════════════════════════════════════════════════════════
print("\n\033[1m2. purge_folder_index: Gruppen bleiben beim TRENNEN stehen\033[0m")
import types

kmod = types.ModuleType("k")
cache = {"files": {"/mnt/jarvis-kb/share_1/a.pdf": {}, "/mnt/jarvis-kb/share_1/b.pdf": {},
                   "/opt/jarvis/data/knowledge/e.md": {}}}
gruppen_gerufen = []


class KG:
    @staticmethod
    def remove_prefix(rel):
        gruppen_gerufen.append(rel)
        return 7


store = Store(["/mnt/jarvis-kb/share_1/a.pdf", "/opt/jarvis/data/knowledge/e.md"])
kmod.__dict__.update({
    "os": os, "Path": Path,
    "_cache_lock": _Lock(),
    "_load_cache": lambda: cache,
    "_save_cache": lambda c: None,
    "_get_vector_store": lambda: store,
    "_folder_rel": lambda f: str(f),
    "_log": types.SimpleNamespace(info=lambda *a, **k: None, warning=lambda *a, **k: None),
})
sys.modules.setdefault("backend_kg_stub", types.ModuleType("backend_kg_stub"))
exec(compile(schneide(KNOW, "purge_folder_index"), "<k>", "exec"), kmod.__dict__)
# knowledge_groups wird IM Rumpf importiert - als Modul stellen, nicht als Name
# (Register: eine Attrappe, die nur einen NAMEN stellt, prueft die eigene Annahme).
kg_mod = types.ModuleType("backend.knowledge_groups")
kg_mod.remove_prefix = KG.remove_prefix
sys.modules["backend.knowledge_groups"] = kg_mod

erg = sicher(kmod.__dict__["purge_folder_index"], Path("/mnt/jarvis-kb/share_1"), False)
check("TF-IDF-Eintraege der Freigabe fallen",
      isinstance(erg, dict) and erg.get("tfidf_files") == 2, repr(erg))
check("Vektor-Chunks fallen", isinstance(erg, dict) and erg.get("vector_chunks") == 1, repr(erg))
check("⚠ die Wissensgruppen-Zuordnung bleibt (die Freigabe kommt wieder)",
      not gruppen_gerufen and isinstance(erg, dict) and erg.get("group_assignments") == 0,
      str(gruppen_gerufen))
check("der Index wird auf PLATTE geschrieben – sonst holt der Dienst den "
      "alten Stand aus dem RAM zurueck", store.gespeichert == 1, str(store.gespeichert))
check("lokales Wissen bleibt im TF-IDF-Cache",
      "/opt/jarvis/data/knowledge/e.md" in cache["files"], str(list(cache["files"])))

# Gegenrichtung: beim LOESCHEN eines Ordners muessen die Gruppen weiter fallen.
cache["files"] = {"/mnt/jarvis-kb/share_1/a.pdf": {}}
store2 = Store(["/mnt/jarvis-kb/share_1/a.pdf"])
kmod.__dict__["_get_vector_store"] = lambda: store2
erg2 = sicher(kmod.__dict__["purge_folder_index"], Path("/mnt/jarvis-kb/share_1"))
check("Vorgabe unveraendert: beim Loeschen fallen die Gruppen weiterhin",
      bool(gruppen_gerufen) and isinstance(erg2, dict) and erg2.get("group_assignments") == 7,
      f"{gruppen_gerufen} {erg2}")

# ═════════════════════════════════════════════════════════════════════════════
print("\n\033[1m3. Die Schranke: nur ECHT unterhalb des Mount-Grundpfads\033[0m")
mmod = types.ModuleType("m")
gerufen = []
mmod.__dict__.update({
    "Path": Path,
    "_MOUNT_BASE": Path("/mnt/jarvis-kb"),
    "print": lambda *a, **k: None,
})
_kn = types.ModuleType("backend.tools.knowledge")
_kn.purge_folder_index = lambda ordner, gruppen=True: (
    gerufen.append((str(ordner), gruppen)) or {"vector_chunks": 5})
sys.modules["backend.tools.knowledge"] = _kn
exec(compile(schneide(MAIN, "_mount_index_raeumen"), "<m>", "exec"), mmod.__dict__)
raeumen = mmod.__dict__["_mount_index_raeumen"]

gerufen.clear()
r = sicher(raeumen, Path("/mnt/jarvis-kb/share_1"))
check("ein echter Einhaengepunkt wird bereinigt",
      isinstance(r, dict) and len(gerufen) == 1, f"{r} {gerufen}")
check("und zwar OHNE die Gruppen anzufassen", gerufen and gerufen[0][1] is False, str(gerufen))

for boese, warum in (
    (Path("/mnt/jarvis-kb"), "⚠ der Grundpfad SELBST – wuerde ALLE Freigaben leeren"),
    (Path("/"), "die Wurzel"),
    (Path("/opt/jarvis/data/knowledge"), "der lokale Wissensordner"),
    (Path(""), "ein leerer Pfad"),
    (Path("/mnt"), "eine Ebene zu hoch"),
):
    gerufen.clear()
    r = sicher(raeumen, boese)
    check(f"abgelehnt: {warum}", not gerufen and r is None, f"{r} {gerufen}")

# ═════════════════════════════════════════════════════════════════════════════
print("\n\033[1m4. Reihenfolge im Endpunkt\033[0m")
q_ep = schneide(MAIN, "unmount_share")
baum = ast.parse(q_ep)
fn = baum.body[0]


def _zeile_von(pruef):
    for kn in ast.walk(fn):
        if pruef(kn):
            return kn.lineno
    return -1


# ⚠ Der Name steht als ARGUMENT von to_thread, nicht als aufgerufene Funktion -
# ein Call-Praedikat findet ihn nicht (eigener Testfehler, beim ersten Lauf).
z_raeumen = _zeile_von(lambda k: isinstance(k, ast.Name)
                       and k.id == "_mount_index_raeumen")
z_fehler = _zeile_von(lambda k: isinstance(k, ast.Call)
                      and getattr(k.func, "attr", "") == "get"
                      and getattr(getattr(k.func, "value", None), "id", "") == "result")
check("der Endpunkt bereinigt ueberhaupt", z_raeumen > 0, str(z_raeumen))
check("⚠ ERST nach der Fehlerpruefung des Aushaengens – scheitert das Trennen, "
      "sind die Dateien noch da und der Index bleibt richtig",
      z_fehler > 0 and z_raeumen > z_fehler, f"raeumen={z_raeumen} fehlerpruefung={z_fehler}")
check("es laeuft im Thread, nicht im Event-Loop (Index-Neuaufbau + Platte)",
      "to_thread(_mount_index_raeumen" in q_ep.replace(" ", "").replace("asyncio.", ""),
      q_ep[:0])
check("die Antwort nennt das Ergebnis (sonst sucht der Admin spaeter den Grund "
      "fuer fehlende Treffer)", "index_bereinigt" in q_ep)

# Beide Wege – auch der Fall 'war gar nicht gemountet'.
check("auch der Zweig 'war nicht gemountet' bereinigt",
      q_ep.count("_mount_index_raeumen") == 2, str(q_ep.count("_mount_index_raeumen")))

# ═════════════════════════════════════════════════════════════════════════════
print("\n\033[1m5. Oberflaeche sagt, was passiert ist\033[0m")
js = (WURZEL / "frontend" / "js" / "knowledge.js").read_text(encoding="utf-8")
i18n = (WURZEL / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
check("die Meldung liest das Ergebnis aus der Antwort", "index_bereinigt" in js)
check("und nennt die Zahl", "share_index_purged" in js and "{n}" in js.split("share_index_purged")[1][:120])
check("Text in DE und EN vorhanden", i18n.count("'knowledge.share_index_purged'") == 2)
check("nur beim Trennen, nicht beim Verbinden",
      "if (!mount) {" in js.split("share_unmounted")[1][:400], js[:0])

print(f"\n\033[1mErgebnis: {OK}/{OK + FAIL}\033[0m")
if FAIL:
    print(f"\033[31m{FAIL} Pruefung(en) fehlgeschlagen\033[0m")
sys.exit(1 if FAIL else 0)
