#!/usr/bin/env python3
"""Waechter: ein UNTERORDNER kann Speicherordner einer Wissensgruppe sein.

Vorgabe 2026-10-21: zwei Gruppen (nxDeutschland, nxREHA) teilen sich den
Wurzelordner ``data/rag/Test und Demo``, jede bekommt ihren eigenen
Unterordner. Bis dahin hingen die Rechte an der WURZEL – wer einer Gruppe
die Wurzel gab, gab ihr beide Unterordner.

Gemessen wird die WIRKUNG der echten Funktionen aus ``backend/main.py``
(per ``ast`` geschnitten und ausgefuehrt, Sandkasten mit Exit 2):
  1. Speicherordner einer Gruppe: Unterordner unter data/ zaehlen, eine
     Freigabe-Wurzel bleibt wie bisher draussen (sonst taucht sie in /wissen
     als Upload-Ziel auf, das jeder Upload abweist).
  2. Schreibrecht: der eigene Unterordner samt Teilbaum ja, das Geschwister,
     die Wurzel, ein Praefix-Nachbar (``nxREHA2``) und ``..`` nein.
  3. Ein Speicherordner ist in /wissen nicht umbenenn-/verschiebbar.
  4. ``_kb_unterordner_rel`` nimmt nur VORHANDENE Unterordner, aufgeloest.
  5. Als REGEL ueber den AST: Upload, Schreibpruefung, Zuweisungs- und
     Gruppen-Endpunkt rufen die neuen Funktionen wirklich auf.

    python3 tests/test_speicherordner_unterordner.py
"""
import ast
import sys
import tempfile
import types
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
MAIN = (WURZEL / "backend" / "main.py").read_text(encoding="utf-8")
BAUM = ast.parse(MAIN)

_ok = _fail = 0


def check(text, bedingung, detail=""):
    global _ok, _fail
    if bedingung:
        _ok += 1
        print(f"  OK   {text}")
    else:
        _fail += 1
        print(f"  FAIL {text}" + (f"  -> {detail}" if detail else ""))


def sicher(fn, info=""):
    """Eine Pruefung darf NICHT werfen – sonst endet der Lauf ohne Bilanz."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        global _fail
        _fail += 1
        print(f"  FAIL {info or 'Aufruf'} wirft: {type(e).__name__}: {e}")
        return None


def knoten(name):
    for k in BAUM.body:
        if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name == name:
            return k
    print(f"ABBRUCH – Funktion {name} fehlt in main.py (Altstand?)")
    sys.exit(2)


def schneide(name):
    return ast.get_source_segment(MAIN, knoten(name))


GESCHNITTEN = ("_kb_norm_rel", "_kb_configured_root_for", "_kb_safe_within_data",
               "_kb_baum_key", "_kb_unterordner_rel", "_wissen_group_folders",
               "_wissen_unter", "_wissen_allowed_folders", "_wissen_anker_im_weg",
               "_wissen_may_write_path")
for _n in GESCHNITTEN + ("wissen_upload", "assign_knowledge_folder_groups",
                         "knowledge_groups_update", "wissen_rename_subfolder",
                         "wissen_move_subfolder"):
    knoten(_n)


# ── Sandkasten ──────────────────────────────────────────────────────────────
SAND = Path(tempfile.mkdtemp(prefix="speicherordner-test-"))
FREMD = Path(tempfile.mkdtemp(prefix="speicherordner-share-"))   # "Freigabe" ausserhalb
if not str(SAND).startswith(tempfile.gettempdir()):
    print("ABBRUCH – Sandkasten greift nicht")
    sys.exit(2)

TD = "data/rag/Test und Demo"
DE = f"{TD}/nxDeutschland"
REHA = f"{TD}/nxREHA"
for p in (DE, REHA, f"{REHA}/Archiv", f"{TD}/nxREHA2", "data/rag/ibs/x/tief", "data/rag/ibs/y",
          "data/fremd"):
    (SAND / p).mkdir(parents=True, exist_ok=True)
(FREMD / "Kunden").mkdir()
# Symlink im Wurzelordner, der HERAUS zeigt – nur die Aufloesung erkennt ihn.
(SAND / TD / "link_raus").symlink_to(SAND / "data" / "fremd", target_is_directory=True)
FREMD_REL = str(FREMD).lstrip("/")

CONFIGURED = [TD, "data/rag/ibs", "/mnt/rag/share_2", str(FREMD)]

sys.path.insert(0, str(WURZEL))
try:
    from backend import knowledge_groups as kg  # noqa: E402
except Exception as e:  # noqa: BLE001
    print(f"ABBRUCH – knowledge_groups nicht importierbar: {e}")
    sys.exit(2)

kg.MANIFEST_PATH = SAND / "data" / "knowledge" / ".groups.json"
if not str(kg.MANIFEST_PATH).startswith(str(SAND)):
    print("ABBRUCH – Manifest-Sandkasten greift nicht")
    sys.exit(2)

GRUPPEN = [
    {"id": "de", "name": "nxDeutschland", "folders": [DE]},
    {"id": "reha", "name": "nxREHA", "folders": [REHA]},
    {"id": "ibs", "name": "IBS", "folders": ["data/rag/ibs"]},
    {"id": "nxis", "name": "nxIS", "folders": ["mnt/rag/share_2", "mnt/rag/share_2/Kunden"]},
    {"id": "beides", "name": "Beides", "folders": [TD, REHA]},
    {"id": "kaputt", "name": "Kaputt", "folders": ["data/rag/gibtsnicht/x"]},
    # Anker, dessen Eltern SELBST kein Anker sind – ohne ihn waere "Eltern
    # gesperrt" trivial wahr ("Test und Demo" ist bei "beides" selbst Anker).
    {"id": "tief", "name": "Tief", "folders": ["data/rag/ibs/x/tief"]},
]
kg._save_unlocked({"groups": [dict(g) for g in GRUPPEN], "assignments": {}})

wissensmod = types.ModuleType("backend.tools.knowledge")
wissensmod.PROJECT_ROOT = SAND
wissensmod._get_folders = lambda: [Path(f) if f.startswith("/") else SAND / f
                                   for f in CONFIGURED]
sys.modules["backend.tools.knowledge"] = wissensmod

BENUTZER_GRUPPEN = {}      # Benutzer -> Liste Gruppen-Dicts
GLOBALE = {"admin"}


class _Rag:
    @staticmethod
    def anzeige(p):
        return str(p)


NS = {
    "Path": Path,
    "_kb_current_folder_list": lambda: list(CONFIGURED),
    "_may_edit_knowledge": lambda u: u in GLOBALE,
    "_editable_groups_for": lambda u: BENUTZER_GRUPPEN.get(u, []),
    "_WISSEN_HIDDEN_FOLDERS": set(),
    "_rag": _Rag,
}
for _n in GESCHNITTEN:
    exec(schneide(_n), NS)

G = {g["id"]: g for g in GRUPPEN}
BENUTZER_GRUPPEN["reha_user"] = [G["reha"]]
BENUTZER_GRUPPEN["de_user"] = [G["de"]]
BENUTZER_GRUPPEN["ibs_user"] = [G["ibs"]]

gf = NS["_wissen_group_folders"]
erlaubt = NS["_wissen_allowed_folders"]
darf = lambda u, p: (sicher(lambda: NS["_wissen_may_write_path"](u, p), p) or (None,))[0]  # noqa: E731


print("=" * 72)
print("0. POSITIVKONTROLLE – der Aufbau stellt den Regelfall her")
print("=" * 72)
check("Wurzel des Unterordners ist 'Test und Demo'",
      sicher(lambda: NS["_kb_configured_root_for"](REHA, CONFIGURED)) == TD)
check("Wurzelordner bleibt fuer seinen Speicherordner-Benutzer schreibbar (Bestand)",
      darf("ibs_user", "data/rag/ibs/y") is True)
if _fail:
    print("\nABBRUCH – Positivkontrolle fehlgeschlagen, Folgepruefungen waeren wertlos")
    sys.exit(2)

print("\n1. Speicherordner einer Gruppe")
check("nxREHA: Unterordner zaehlt als Speicherordner", sicher(lambda: gf(G["reha"], CONFIGURED)) == [REHA])
check("IBS: Wurzelordner wie bisher", sicher(lambda: gf(G["ibs"], CONFIGURED)) == ["data/rag/ibs"])
check("Freigabe-Wurzel und Freigabe-Unterordner NICHT als /wissen-Ziel",
      sicher(lambda: gf(G["nxis"], CONFIGURED)) == [], gf(G["nxis"], CONFIGURED))
check("Ordner ausserhalb jeder Wurzel faellt weg", sicher(lambda: gf(G["kaputt"], CONFIGURED)) == [])

print("\n2. Erlaubte Ordner und Schreibrecht")
check("nxREHA-Benutzer: genau sein Unterordner",
      sicher(lambda: erlaubt("reha_user", [G["reha"]])) == [REHA])
check("beide Gruppen: beide Unterordner, hierarchisch sortiert",
      sicher(lambda: erlaubt("x", [G["reha"], G["de"]])) == [DE, REHA],
      erlaubt("x", [G["reha"], G["de"]]))
check("Wurzel + eigener Unterordner: nur die Wurzel (keine Doppelung)",
      sicher(lambda: erlaubt("x", [G["beides"]])) == [TD], erlaubt("x", [G["beides"]]))
check("globaler Editor: alle konfigurierten Ordner (Bestand)",
      sicher(lambda: erlaubt("admin", [])) == CONFIGURED)
check("nxREHA darf in nxREHA", darf("reha_user", REHA) is True)
check("nxREHA darf in nxREHA/Archiv (Teilbaum erbt)", darf("reha_user", f"{REHA}/Archiv") is True)
check("nxREHA darf NICHT in nxDeutschland", darf("reha_user", DE) is False)
check("nxDeutschland darf NICHT in nxREHA", darf("de_user", REHA) is False)
check("nxREHA darf NICHT in die gemeinsame Wurzel", darf("reha_user", TD) is False)
check("Praefix-Nachbar nxREHA2 ist NICHT nxREHA", darf("reha_user", f"{TD}/nxREHA2") is False)
check("'..' aus dem eigenen Unterordner ins Geschwister: abgewiesen",
      darf("reha_user", f"{REHA}/../nxDeutschland") is False)
check("'..' aus einer Wurzel in einen fremden data/-Ordner: abgewiesen (Bestandsluecke)",
      darf("ibs_user", "data/rag/ibs/../../fremd") is False)
check("'.' als Pfadteil: abgewiesen", darf("reha_user", f"{REHA}/./Archiv") is False)

print("\n3. Speicherordner sind in /wissen nicht umhaengbar")
anker = NS["_wissen_anker_im_weg"]
check("nxREHA selbst ist Anker", sicher(lambda: anker(REHA)) == REHA)
check("Unterordner darunter ist frei", sicher(lambda: anker(f"{REHA}/Archiv")) is None)
check("Ordner, der einen Anker ENTHAELT (selbst keiner), ist gesperrt",
      sicher(lambda: anker("data/rag/ibs/x")) == "data/rag/ibs/x/tief")
check("unbeteiligter Ordner ist frei", sicher(lambda: anker("data/rag/ibs/y")) is None)

print("\n4. _kb_unterordner_rel")
uo = NS["_kb_unterordner_rel"]
check("vorhandener Unterordner", sicher(lambda: uo(REHA)) == REHA)
check("mit fuehrendem/abschliessendem Schraegstrich", sicher(lambda: uo("/" + REHA + "/")) == REHA)
check("Wurzel selbst ist KEIN Unterordner", sicher(lambda: uo(TD)) is None)
check("nicht vorhanden -> None", sicher(lambda: uo(f"{TD}/gibtsnicht")) is None)
check("'..' aus der Wurzel heraus -> None", sicher(lambda: uo(f"{TD}/../ibs")) is None)
# ⚠ Der Fall INNERHALB der Wurzel ist der gefaehrlichere: die Aufloesung
#   besteht er, gespeichert wuerde der rohe Pfad (live auf DEV gefunden).
check("'..' innerhalb der Wurzel -> None", sicher(lambda: uo(f"{REHA}/../nxDeutschland")) is None)
check("Unterordner einer Freigabe ausserhalb des Projekts",
      sicher(lambda: uo(f"/{FREMD_REL}/Kunden")) == f"{FREMD_REL}/Kunden")
check("nicht konfigurierter Ordner -> None", sicher(lambda: uo("data/fremd")) is None)
check("Symlink aus der Wurzel heraus -> None", sicher(lambda: uo(f"{TD}/link_raus")) is None)


print("\n5. REGEL (AST): die Endpunkte rufen die neuen Pruefungen")


def ruft(funk, name):
    return any(isinstance(n, ast.Call) and getattr(n.func, "id", None) == name
               for n in ast.walk(knoten(funk)))


def ruft_im_lambda(funk, name):
    return any(isinstance(n, ast.Lambda) and any(
        isinstance(c, ast.Call) and getattr(c.func, "id", None) == name for c in ast.walk(n))
        for n in ast.walk(knoten(funk)))


check("Upload prueft den ZIELPFAD ueber _wissen_unter", ruft("wissen_upload", "_wissen_unter"))
check("Schreibpruefung ueber _wissen_unter", ruft("_wissen_may_write_path", "_wissen_unter"))
check("Zuweisungs-Endpunkt nimmt Unterordner (_kb_unterordner_rel)",
      ruft_im_lambda("assign_knowledge_folder_groups", "_kb_unterordner_rel"))
check("Gruppen-PATCH nimmt Unterordner (_kb_unterordner_rel)",
      ruft_im_lambda("knowledge_groups_update", "_kb_unterordner_rel"))
check("/wissen-Umbenennen sperrt Speicherordner",
      ruft("wissen_rename_subfolder", "_wissen_anker_im_weg"))
check("/wissen-Verschieben sperrt Speicherordner",
      ruft("wissen_move_subfolder", "_wissen_anker_im_weg"))
# Die alte Pruefung "Wurzel in Liste" darf nicht zurueckkehren: sie gaebe einer
# Gruppe mit Unterordner-Speicherordner keinen Zugang und einer mit Wurzel ALLE.
alt = [n for f in ("wissen_upload", "_wissen_may_write_path") for n in ast.walk(knoten(f))
       if isinstance(n, ast.Compare) and any(isinstance(o, ast.NotIn) for o in n.ops)
       and getattr(n.left, "id", None) == "root_rel"]
check("keine Pruefung 'root_rel not in …' mehr", not alt)

print(f"\nErgebnis: {_ok} OK, {_fail} FAIL")
sys.exit(1 if _fail else 0)
