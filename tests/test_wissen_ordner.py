#!/usr/bin/env python3
"""Waechter: die Dateiliste in /wissen nennt den ORDNER, nicht nur den Namen.

Gemeldet 2026-09-07: "unter /wissen -> Mein Wissen erscheint in der Dateiliste
nur der Dateiname. Es ist nicht moeglich zu erkennen, in welchem
Unterverzeichnis die Datei liegt." Zwei gleichnamige Dateien in verschiedenen
Unterordnern waren damit nicht unterscheidbar – auch nicht in der
Loesch-Rueckfrage.

Laeuft OHNE fastapi: Helfer und Endpunkt werden per ``ast`` aus
``backend/main.py`` GESCHNITTEN und WIRKLICH AUSGEFUEHRT. Eine
Quelltext-Pruefung wuerde die eigene Begruendung im Docstring mitlesen (im
Projekt der dreizehnte Fall dieser Klasse), und ein Import zoege den halben
Server nach.

Geprueft wird die REGEL, nicht ein Wortlaut:
  1. der Ordner wird in der Sprache der Oberflaeche gebildet: NAME des
     konfigurierten Wurzelordners + Unterordner darunter
  2. der TIEFSTE passende Wurzelordner gewinnt (Vererbungsregel)
  3. kein Praefix-Fehlschluss: ``data/knowledge2`` gehoert nicht zu
     ``data/knowledge`` (dieselbe Falle wie ``share_1`` in ``share_10``)
  4. FAIL-OPEN: passt kein konfigurierter Wurzelordner, steht der rohe
     Verzeichnispfad da – NIE eine leere Angabe (das waere der gemeldete Zustand)
  5. der Endpunkt liefert je Datei ein ``folder`` und sortiert Name-dann-Ordner
  6. die Ordnerliste wird EINMAL geholt, nicht je Datei

Gemessen wird mit den ECHTEN Pfaden aus dem DEV-Bestand (Assignments und
konfigurierte Ordner vom 2026-09-07) – erfundene Pfade belegen hier nichts.

SANDKASTEN mit Exit 2: zeigt das Gruppen-Manifest nicht ins Wegwerf-Verzeichnis,
bricht der Lauf ab, statt den echten Bestand anzufassen.
"""
import ast
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = fail = 0


def abschnitt(t):
    print("\n\033[1m%s\033[0m" % t)


def check(name, cond, detail=""):
    """(Beschreibung, Bedingung) – NICHT umgekehrt."""
    global ok, fail
    if isinstance(name, bool) or not isinstance(name, str):
        print("\033[31mABBRUCH: check() falsch herum aufgerufen "
              "(erst Beschreibung, dann Bedingung)\033[0m")
        sys.exit(2)
    if bool(cond):
        ok += 1
        print("  \033[32m✓\033[0m %s" % name)
    else:
        fail += 1
        print("  \033[31m✗\033[0m %s%s" % (name, (" – " + str(detail)) if detail else ""))


def abbruch(text):
    print("\033[31mABBRUCH: %s\033[0m" % text)
    sys.exit(2)


# ── Schnitt aus backend/main.py ────────────────────────────────────────────
MAIN = ROOT / "backend" / "main.py"
QUELL = MAIN.read_text(encoding="utf-8")
BAUM = ast.parse(QUELL)

FUNKTIONEN = {}
for n in BAUM.body:
    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
        FUNKTIONEN[n.name] = n

GESCHNITTEN = ["_kb_norm_rel", "_kb_configured_root_for",
               "_wissen_ordner_anzeige", "wissen_files"]
for name in GESCHNITTEN:
    if name not in FUNKTIONEN:
        abbruch("Funktion %s nicht in backend/main.py gefunden" % name)


class Antwort:
    """Steht fuer JSONResponse."""

    def __init__(self, content, status_code=200):
        self.content = content
        self.status_code = status_code


# Zaehlt, wie oft die Ordnerliste geholt wird (Beschleuniger-Zusage, Punkt 6).
_ordner_aufrufe = {"n": 0}
CONFIGURED = ["data/knowledge", "data/community",
              "/mnt/jarvis-kb/share_0", "/mnt/jarvis-kb/share_1"]


def _kb_current_folder_list_attrappe():
    _ordner_aufrufe["n"] += 1
    return list(CONFIGURED)


GRUPPEN = [
    {"id": "erlernt", "name": "Erlernt", "color": "#8b5cf6"},
    {"id": "allgemein", "name": "community", "color": "#22c55e"},
    {"id": "knowledgebase-an-rag", "name": "knowledgebase_an_rag", "color": "#0ea5e9"},
]


def _editable_groups_for_attrappe(user):
    # 'fremd' hat keine Gruppen -> darf keine Datei sehen (Bestandsverhalten).
    return [] if user == "fremd" else [dict(g) for g in GRUPPEN]


NS = {
    "json": json, "print": print, "Path": Path,
    "JSONResponse": Antwort,
    "Depends": lambda x: None, "require_auth": None,
    "app": type("App", (), {"get": staticmethod(lambda *a, **k: (lambda f: f))})(),
    "_kb_current_folder_list": _kb_current_folder_list_attrappe,
    "_editable_groups_for": _editable_groups_for_attrappe,
}

knoten = []
for k in GESCHNITTEN:
    kopie = ast.parse(ast.unparse(FUNKTIONEN[k])).body[0]
    kopie.decorator_list = []
    knoten.append(kopie)
exec(compile(ast.fix_missing_locations(ast.Module(body=knoten, type_ignores=[])),
             "<main-schnitt>", "exec"), NS)

ordner = NS["_wissen_ordner_anzeige"]
files_endpunkt = NS["wissen_files"]

# ── Echtes knowledge_groups im Sandkasten ─────────────────────────────────
# Das Modul ist harmlos (nur stdlib) und wird ECHT benutzt: so laeuft auch die
# echte Pfad-Normalisierung mit (`_rel` streift den fuehrenden Slash von
# /mnt/... ab – genau das steht im echten Bestand).
SANDKASTEN = Path(tempfile.mkdtemp(prefix="jarvis-wissen-ordner-"))
from backend import knowledge_groups as kg   # noqa: E402

kg.MANIFEST_PATH = SANDKASTEN / "groups.json"
if not str(kg.MANIFEST_PATH).startswith(str(SANDKASTEN)):
    abbruch("Gruppen-Manifest zeigt nicht in den Sandkasten: %s" % kg.MANIFEST_PATH)

_LOOP = asyncio.new_event_loop()


def lauf(coro):
    return _LOOP.run_until_complete(coro)


# ══ 1. Die Regel, an den ECHTEN Pfaden des DEV-Bestands ════════════════════
abschnitt("1 – Ordner in der Sprache der Oberflaeche (echte Pfade)")

FAELLE = [
    # (Pfad im Bestand, erwarteter Anzeige-Ordner, Beschreibung)
    ("data/knowledge/learned/2026-09/conv_1758.md", "knowledge/learned/2026-09",
     "Lernnotiz zwei Ebenen unter der Wurzel"),
    ("data/community/Handbuch.pdf", "community",
     "Datei direkt im Wurzelordner"),
    ("mnt/jarvis-kb/share_1/OneNote-Jasmin/0039_Maris/Anleitungen SAP.one",
     "share_1/OneNote-Jasmin/0039_Maris",
     "Netzwerk-Freigabe (Pfad ohne fuehrenden Slash, wie gespeichert)"),
    ("data/knowledge/x.md", "knowledge",
     "Datei direkt in data/knowledge"),
]
for pfad, erwartet, was in FAELLE:
    got = ordner(pfad, CONFIGURED)
    check("%s -> '%s'" % (was, erwartet), got == erwartet, "geliefert: '%s'" % got)

check("Ordner ist NIE leer, solange ein Verzeichnis im Pfad steht",
      all(ordner(p, CONFIGURED) for p, _e, _w in FAELLE))


# ══ 2. Tiefster Wurzelordner gewinnt ══════════════════════════════════════
abschnitt("2 – Der TIEFSTE konfigurierte Wurzelordner gewinnt")

TIEF = CONFIGURED + ["data/knowledge/extra"]
check("data/knowledge/extra/tief/x.md -> 'extra/tief' (nicht 'knowledge/extra/tief')",
      ordner("data/knowledge/extra/tief/x.md", TIEF) == "extra/tief",
      ordner("data/knowledge/extra/tief/x.md", TIEF))
check("die kuerzere Wurzel gilt weiter fuer ihre eigenen Dateien",
      ordner("data/knowledge/learned/x.md", TIEF) == "knowledge/learned")


# ══ 3. Kein Praefix-Fehlschluss ═══════════════════════════════════════════
abschnitt("3 – 'data/knowledge2' gehoert NICHT zu 'data/knowledge'")

check("data/knowledge2/x.md faellt auf den rohen Pfad zurueck",
      ordner("data/knowledge2/x.md", CONFIGURED) == "data/knowledge2",
      ordner("data/knowledge2/x.md", CONFIGURED))
check("mnt/jarvis-kb/share_10/x.md wird nicht share_1 zugeschlagen",
      ordner("mnt/jarvis-kb/share_10/tief/x.md", CONFIGURED)
      == "mnt/jarvis-kb/share_10/tief",
      ordner("mnt/jarvis-kb/share_10/tief/x.md", CONFIGURED))


# ══ 4. Fail-open ══════════════════════════════════════════════════════════
abschnitt("4 – Unbekannte Wurzel: roher Pfad statt Leere")

check("Ordner aus der Konfiguration genommen -> roher Verzeichnispfad",
      ordner("data/fremd/unterordner/x.md", CONFIGURED) == "data/fremd/unterordner")
check("leere Ordnerliste -> roher Verzeichnispfad",
      ordner("data/knowledge/learned/x.md", []) == "data/knowledge/learned")
check("Datei ohne Verzeichnis -> leer (es gibt keinen Ordner zu nennen)",
      ordner("x.md", CONFIGURED) == "")
check("leerer Pfad wirft nicht", ordner("", CONFIGURED) == "")
# Ein ORDNER-Pfad statt eines Datei-Pfads: die Wurzel liegt dann UNTER dem
# Verzeichnis. Statt stillen Unsinns kommt der rohe Pfad.
check("ein Ordner-Pfad liefert den rohen Pfad, keinen falschen Namen",
      ordner("data/knowledge", CONFIGURED) == "data",
      ordner("data/knowledge", CONFIGURED))


# ══ 5. Der Endpunkt liefert den Ordner mit ════════════════════════════════
abschnitt("5 – GET /api/wissen/files: Feld 'folder' und Sortierung")

BESTAND = {
    "data/knowledge/learned/2026-09/conv_1758.md": ["erlernt"],
    "data/knowledge/learned/2026-08/conv_1756.md": ["erlernt"],
    "data/community/Handbuch.pdf": ["allgemein"],
    # ZWEI gleichnamige Dateien in verschiedenen Ordnern – der gemeldete Fall.
    # Die Reihenfolge hier ist ABSICHTLICH die falsche ('share_1' vor
    # 'community/Vertrieb'): sortiert der Endpunkt nur nach dem Namen, bleibt
    # sie stehen und die Pruefung unten beisst. Mit der Einfuegereihenfolge
    # "richtig herum" waere sie zahnlos gewesen.
    "mnt/jarvis-kb/share_1/Preisliste.xlsx": ["knowledgebase-an-rag"],
    "data/community/Vertrieb/Preisliste.xlsx": ["allgemein"],
    # Datei einer fremden Gruppe – darf nicht auftauchen
    "data/knowledge/geheim/x.md": ["nicht-meine-gruppe"],
}
kg.MANIFEST_PATH.write_text(json.dumps({
    "groups": [dict(g, folders=[]) for g in GRUPPEN],
    "assignments": BESTAND,
}, ensure_ascii=False), encoding="utf-8")

_ordner_aufrufe["n"] = 0


def hole(user="anna"):
    """Endpunkt-Aufruf, der NICHT abbricht: wirft er (z.B. weil ein Feld
    fehlt), zaehlt das als FAIL – ein Abbruch waere von "nicht gelaufen"
    nicht zu unterscheiden (Register)."""
    try:
        return lauf(files_endpunkt(user=user)).content["files"], None
    except Exception as e:   # noqa: BLE001
        return [], "%s: %s" % (type(e).__name__, e)


dateien, wurf = hole()
check("der Endpunkt antwortet ohne Fehler", wurf is None, wurf)
check("nur Dateien der eigenen Gruppen (5 von 6)", len(dateien) == 5,
      "geliefert: %d" % len(dateien))
check("JEDE Datei traegt ein nicht-leeres 'folder'",
      bool(dateien) and all(f.get("folder") for f in dateien),
      [f.get("path") for f in dateien if not f.get("folder")])

nach_pfad = {f["path"]: f for f in dateien}


def ord_von(pfad):
    """Ordner einer Datei aus der Antwort – NIE ungeprueft dereferenzieren:
    ein KeyError liesse die Pruefung ABBRECHEN statt fehlschlagen (Register)."""
    return (nach_pfad.get(pfad) or {}).get("folder")


check("Lernnotiz: folder = 'knowledge/learned/2026-09'",
      ord_von("data/knowledge/learned/2026-09/conv_1758.md")
      == "knowledge/learned/2026-09",
      ord_von("data/knowledge/learned/2026-09/conv_1758.md"))
check("Freigabe-Datei: folder = 'share_1'",
      ord_von("mnt/jarvis-kb/share_1/Preisliste.xlsx") == "share_1",
      ord_von("mnt/jarvis-kb/share_1/Preisliste.xlsx"))
check("Unterordner: folder = 'community/Vertrieb'",
      ord_von("data/community/Vertrieb/Preisliste.xlsx") == "community/Vertrieb",
      ord_von("data/community/Vertrieb/Preisliste.xlsx"))
check("die fremde Gruppe bleibt aussen vor",
      ord_von("data/knowledge/geheim/x.md") is None)

# Der gemeldete Kern: gleicher Name, verschiedene Ordner -> unterscheidbar
gleich = [f for f in dateien if f["name"] == "Preisliste.xlsx"]
check("die zwei gleichnamigen Dateien sind ueber 'folder' unterscheidbar",
      len(gleich) == 2 and gleich[0]["folder"] != gleich[1]["folder"],
      [f.get("folder") for f in gleich])
ord_gleich = [f.get("folder", "") for f in gleich]
check("gleichnamige Dateien stehen nach Ordner sortiert nebeneinander",
      len(ord_gleich) == 2 and ord_gleich == sorted(ord_gleich), ord_gleich)
schluessel = [(f.get("name", "").lower(), f.get("folder", "").lower())
              for f in dateien]
check("Name bleibt das erste Sortierkriterium, der Ordner das zweite",
      schluessel == sorted(schluessel), schluessel)
check("'name' bleibt der reine Dateiname (kein Pfad darin)",
      all("/" not in f["name"] for f in dateien))


# ══ 6. Die Ordnerliste wird EINMAL geholt ═════════════════════════════════
abschnitt("6 – Beschleuniger: Ordnerliste einmal je Abruf, nicht je Datei")

check("genau ein Aufruf von _kb_current_folder_list bei 6 Zuordnungen",
      _ordner_aufrufe["n"] == 1, "Aufrufe: %d" % _ordner_aufrufe["n"])
check("_kb_configured_root_for nimmt die Liste als Argument an (Regel bleibt "
      "an EINER Stelle)",
      "configured" in [a.arg for a in FUNKTIONEN["_kb_configured_root_for"].args.args])
# Der Bestand ruft _kb_configured_root_for OHNE Liste (Upload, Unterordner).
# Diese Messung kommt NACH der Zaehlung oben, sonst verfaelscht sie sie.
_vor = _ordner_aufrufe["n"]
_ohne = NS["_kb_configured_root_for"]("data/knowledge/learned/x.md")
check("ohne Argument holt _kb_configured_root_for die Liste weiter selbst "
      "(Bestandsaufrufer unveraendert)",
      _ohne == "data/knowledge" and _ordner_aufrufe["n"] == _vor + 1,
      "root=%r, Aufrufe %d->%d" % (_ohne, _vor, _ordner_aufrufe["n"]))


# ══ Bilanz ════════════════════════════════════════════════════════════════
print("\n\033[1mErgebnis: %d OK, %d FAIL\033[0m" % (ok, fail))
sys.exit(0 if fail == 0 else 1)
