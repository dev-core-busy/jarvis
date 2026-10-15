#!/usr/bin/env python3
"""Waechter: Wissensordner liegen ausschliesslich unter data/rag, und die
Oberflaeche zeigt sie OHNE diesen Praefix.

Geprueft wird die EIGENSCHAFT, nicht die Schreibweise:

* ``rag_pfad`` und die beiden Frontend-Helfer liefern fuer dieselben Faelle
  dasselbe (Drift-Schranke ueber drei Dateien – der Client hat seine Fassung
  nur als Rueckfall, und zwei Fassungen liefen beim naechsten Feinschliff
  auseinander).
* Die Migration wird WIRKLICH AUSGEFUEHRT, in einem Sandkasten. Eine
  Quelltext-Pruefung koennte "verschiebt den Ordner samt Index" gar nicht
  beantworten.
* Die drei Ordner-Endpunkte lassen nur ``data/rag/<name>`` zu – gemessen ueber
  den AST, damit auch eine KUENFTIGE Stelle auffaellt, ohne dass jemand eine
  Liste pflegt.

Sandkasten mit Exit 2: ein Lauf, der die echte settings.json oder den echten
Wissensbestand anfasst, ist teurer als der Fehler, den er sucht.
"""
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = FAIL = 0
def check(beschreibung, bedingung, detail=""):
    global OK, FAIL
    if isinstance(beschreibung, bool):          # vertauschte Argumente
        print("ABBRUCH: check(bedingung, text) – Argumente vertauscht"); sys.exit(2)
    if bedingung:
        OK += 1; print(f"  OK   {beschreibung}")
    else:
        FAIL += 1; print(f"  FAIL {beschreibung}" + (f"  [{detail}]" if detail else ""))

def sicher(fn, *a, **k):
    """Eine Pruefung darf nie WERFEN – sonst bricht der Lauf ohne Bilanzzeile ab
    und ist von 'nicht gelaufen' nicht zu unterscheiden."""
    try:
        return fn(*a, **k)
    except Exception as e:                       # noqa: BLE001
        return f"<<WURF: {type(e).__name__}: {e}>>"

def ohne_kommentare(quelle: str) -> str:
    """Kommentare UND Docstrings raus. Ein Waechter, der die eigene Begruendung
    liest, prueft nichts – im Projekt vierzehnmal bezahlt.

    Docstrings ueber den AST (dort sind sie eindeutig), ``#``-Kommentare
    zeilenweise ueber ``tokenize``. Ersetzt wird durch LEERZEICHEN, nicht
    entfernt: die Zeichen-POSITIONEN bleiben damit erhalten, und darauf beruhen
    die Reihenfolge-Pruefungen weiter unten. Ein Filter, der den Quelltext
    umbaut, prueft nicht mehr den Quelltext.
    """
    import io, tokenize
    zeilen = quelle.splitlines(keepends=True)
    versatz = [0]
    for z in zeilen:
        versatz.append(versatz[-1] + len(z))
    zeichen = list(quelle)

    def loesche(z1, s1, z2, s2):
        a = versatz[z1 - 1] + s1
        b = versatz[z2 - 1] + s2
        for i in range(a, min(b, len(zeichen))):
            if zeichen[i] != "\n":
                zeichen[i] = " "

    try:
        baum = ast.parse(quelle)
    except SyntaxError:
        return quelle
    for knoten in ast.walk(baum):
        if not isinstance(knoten, (ast.Module, ast.ClassDef,
                                   ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        koerper = getattr(knoten, "body", [])
        if (koerper and isinstance(koerper[0], ast.Expr)
                and isinstance(koerper[0].value, ast.Constant)
                and isinstance(koerper[0].value.value, str)):
            d = koerper[0].value
            loesche(d.lineno, d.col_offset, d.end_lineno, d.end_col_offset)
    try:
        for t in tokenize.generate_tokens(io.StringIO(quelle).readline):
            if t.type == tokenize.COMMENT:
                loesche(t.start[0], t.start[1], t.end[0], t.end[1])
    except Exception:                            # noqa: BLE001
        pass
    return "".join(zeichen)


# ═══ 1) Die eine Pfadregel ═══════════════════════════════════════════════════
print("\n[1] rag_pfad – Ort und Anzeige")
from backend import rag_pfad as rp                          # noqa: E402

FAELLE = [
    # (Pfad,                        anzeige,                 ist_rag)
    ("data/rag/community",          "community",             True),
    ("data/rag/community/handbuch", "community/handbuch",    True),
    ("data/rag/a/b/c",              "a/b/c",                 True),
    ("/mnt/rag/share_1/Maris",      "share_1/Maris",         False),
    ("/mnt/jarvis-kb/share_0",      "share_0",               False),
    ("data/knowledge",              "data/knowledge",        False),
    ("data/rag",                    "data/rag",              False),
    ("data/rag2/x",                 "data/rag2/x",           False),   # Praefix-Falle
    ("",                            "",                      False),
]
for pfad, erwartet, ist_rag in FAELLE:
    check(f"anzeige({pfad!r}) = {erwartet!r}", sicher(rp.anzeige, pfad) == erwartet,
          repr(sicher(rp.anzeige, pfad)))
    check(f"ist_rag_ordner({pfad!r}) = {ist_rag}", sicher(rp.ist_rag_ordner, pfad) == ist_rag)

# Die Praefix-Falle einzeln benannt: `data/rag2` steckt NICHT in `data/rag`.
check("data/rag2 gilt nicht als Wissensordner", not rp.ist_rag_ordner("data/rag2/x"))
check("data/rag selbst ist kein Wissensordner (nur Unterordner)", not rp.ist_rag_ordner("data/rag"))

for roh, ziel in [("community", "data/rag/community"), ("data/community", "data/rag/community"),
                  ("data/rag/community", "data/rag/community"), ("", ""), ("/x/", "data/rag/x")]:
    check(f"zu_rag({roh!r}) = {ziel!r}", sicher(rp.zu_rag, roh) == ziel, repr(sicher(rp.zu_rag, roh)))

# ⚠ EINE EINGABE, DIE NUR DIE WURZEL NENNT, BENENNT KEINEN ORDNER. `"data/"`
# wurde von einer frueheren Fassung zu `data/rag/data` – also zu einem Ordner
# namens "data" statt zu einer Absage (vom Bestandstest test_knowledge_sync
# gefunden, nicht beim Lesen).
for roh in ("data/", "data", "data/rag", "data/rag/", "/", "data/../etc", "x/../y"):
    check(f"zu_rag({roh!r}) wird abgewiesen", sicher(rp.zu_rag, roh) == "",
          repr(sicher(rp.zu_rag, roh)))

check("Systemordner erkannt (data/logs)", rp.ist_systemordner("data/logs"))
check("data/rag selbst gilt als Systemordner (nie verschieben)", rp.ist_systemordner("data/rag"))
check("ein Wissensordner ist KEIN Systemordner", not rp.ist_systemordner("data/community"))
check("data/rag/logs ist ein gewoehnlicher Wissensordner", not rp.ist_systemordner("data/rag/logs"))


# ═══ 2) Drift-Schranke: Backend und die BEIDEN Client-Helfer ═════════════════
print("\n[2] Drift – derselbe Anzeigename in Backend und Client")

def js_helfer(datei: str, name: str):
    """Den Helfer aus der echten Datei schneiden und mit node AUSFUEHREN.
    Ein Quelltext-Vergleich koennte nicht sagen, WAS herauskommt."""
    quelle = (ROOT / datei).read_text(encoding="utf-8")
    m = re.search(rf"(?:function\s+)?{re.escape(name)}\s*\(\s*(\w+)\s*\)\s*\{{", quelle)
    if not m:
        return None
    i = quelle.index("{", m.start()); tiefe = 0
    for j in range(i, len(quelle)):
        if quelle[j] == "{": tiefe += 1
        elif quelle[j] == "}":
            tiefe -= 1
            if tiefe == 0:
                return quelle[m.start():j + 1]
    return None

for datei, name in [("frontend/js/knowledge.js", "_anzeigePfad"),
                    ("frontend/js/wissen.js", "anzeigePfad")]:
    schnitt = js_helfer(datei, name)
    check(f"{datei}: {name} gefunden", bool(schnitt))
    if not schnitt:
        continue
    # In eine Funktion heben und gegen dieselben Faelle laufen lassen.
    rumpf = schnitt[schnitt.index("{") + 1: schnitt.rindex("}")]
    param = re.search(rf"{re.escape(name)}\s*\(\s*(\w+)\s*\)", schnitt).group(1)
    skript = ("const f = function(" + param + "){" + rumpf + "};\n"
              "const faelle = " + json.dumps([f[0] for f in FAELLE]) + ";\n"
              "console.log(JSON.stringify(faelle.map(f)));")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as fh:
        fh.write(skript); tmp = fh.name
    try:
        aus = subprocess.run(["node", tmp], capture_output=True, text=True, timeout=20)
        got = (json.loads(aus.stdout.strip()) if aus.returncode == 0
               else f"<<node rc={aus.returncode}: {aus.stderr.strip()[:160]}>>")
    except Exception as e:                       # noqa: BLE001
        got = f"<<{e}>>"
    finally:
        os.unlink(tmp)
    soll = [f[1] for f in FAELLE]
    check(f"{datei}: {name} liefert dasselbe wie rag_pfad.anzeige()", got == soll,
          f"js={got} py={soll}")


# ═══ 3) Die Endpunkte lassen nur data/rag zu ════════════════════════════════
print("\n[3] Ordner-Endpunkte – Ort nicht mehr waehlbar")
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
MAIN_OK = ohne_kommentare(MAIN)
check("Kommentar-Filter greift (Positivkontrolle)",
      "⚠ DER ORT IST NICHT MEHR WAEHLBAR" in MAIN and "⚠ DER ORT IST NICHT MEHR WAEHLBAR" not in MAIN_OK)

baum = ast.parse(MAIN)
funktionen = {n.name: n for n in ast.walk(baum)
              if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

for fname, muss in [("create_knowledge_folder", "zu_rag"),
                    ("rename_knowledge_folder", "ist_rag_ordner"),
                    ("delete_knowledge_folder", "ist_rag_ordner")]:
    node = funktionen.get(fname)
    check(f"{fname} vorhanden", node is not None)
    if node is None:
        continue
    seg = ast.get_source_segment(MAIN, node) or ""
    check(f"{fname} benutzt die eine Regel ({muss})", muss in seg, seg[:80])
    # Die alte Regel darf nicht zurueckkommen: jeder direkte data/-Unterordner.
    check(f"{fname} prueft NICHT mehr gegen data/ als Wurzel",
          'PROJECT_ROOT / "data").resolve()' not in seg)

# ⚠ REGEL, nicht Einzelfall: NIRGENDS im Backend darf ein Pfad
# `data/rag/knowledge` entstehen. Der Betreiber hat ihn ausdruecklich
# ausgeschlossen; ein spaeterer "hilfsweise"-Zweig waere dieselbe
# Missachtung noch einmal. Kommentare und Docstrings sind ausgenommen –
# dort steht die Begruendung, und die muss den Pfad nennen duerfen.
for modul in ("backend/rag_migration.py", "backend/rag_pfad.py",
              "backend/main.py", "backend/tools/knowledge.py"):
    roh = (ROOT / modul).read_text(encoding="utf-8")
    ohne = ohne_kommentare(roh)
    check(f"{modul} baut kein data/rag/knowledge", "rag/knowledge" not in ohne,
          "Treffer im kommentarfreien Code")
    # Auch nicht zusammengesetzt: `rag_wurzel() / "knowledge"`.
    check(f"{modul} setzt ihn auch nicht zusammen",
          'rag_wurzel() / "knowledge"' not in ohne
          and "RAG_REL}/knowledge" not in ohne
          and 'RAG_REL + "/knowledge"' not in ohne,
          "zusammengesetzter Pfad im kommentarfreien Code")

check("die alte Namensliste ist aus main.py verschwunden",
      "_KB_RESERVED_DATA_DIRS" not in MAIN_OK)
check("sie lebt als Migrations-Schutz in rag_pfad weiter",
      hasattr(rp, "SYSTEM_ORDNER") and "logs" in rp.SYSTEM_ORDNER)

# Kein Endpunkt legt einen Wissensordner mehr direkt unter data/ an.
check("kein 'data/{name}'-Pfadbau mehr in den Ordner-Endpunkten",
      'rel = f"data/{name}"' not in MAIN_OK and 'new_rel = f"data/{new_name}"' not in MAIN_OK)

# Das Werkzeug ist der zweite Weg in die Ordnerliste – es MUSS dieselbe Regel haben.
KNOW = (ROOT / "backend" / "tools" / "knowledge.py").read_text(encoding="utf-8")
KNOW_OK = ohne_kommentare(KNOW)
# ⚠ DEN ZWEIG SCHNEIDEN, NICHT DIE DATEI DURCHSUCHEN. Die erste Fassung fragte
# nur, ob `_rag.zu_rag(folder_arg)` IRGENDWO in knowledge.py steht – es steht
# zweimal drin (add_folder UND remove_folder), also blieb die Pruefung wahr,
# waehrend add_folder sabotiert war. Ein Vorkommen irgendwo ist keine Aussage
# ueber eine bestimmte Stelle.
def zweig(quelle: str, von: str, bis: str) -> str:
    i = quelle.find(von)
    if i < 0:
        return ""
    j = quelle.find(bis, i + len(von))
    return quelle[i: j if j > 0 else len(quelle)]

add_zweig = zweig(KNOW_OK, 'elif action == "add_folder":', 'elif action == "remove_folder":')
check("add_folder-Zweig gefunden (Positivkontrolle)", len(add_zweig) > 200, str(len(add_zweig)))
check("knowledge_manage add_folder normiert auf data/rag",
      "_rag.zu_rag(folder_arg)" in add_zweig, add_zweig[:120])
check("knowledge_manage add_folder WEIST ab, was nicht unter data/rag liegt",
      "ist_rag_ordner" in add_zweig, add_zweig[:120])
check("kein Rueckfall mehr auf einen erfundenen Standardordner",
      'cfg.get("folders", DEFAULT_FOLDER)' not in KNOW_OK)

# ⚠ Der gefaehrlichste Zweig: leere Ordnerliste darf NIE vs.clear() ausloesen.
check("leere Ordnerliste bricht den Neuaufbau ab, statt den Index zu leeren",
      "Kein Wissensordner konfiguriert" in KNOW)
kbaum = ast.parse(KNOW)
kfun = {n.name: n for n in ast.walk(kbaum)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
seg_fr = ast.get_source_segment(KNOW, kfun["_do_force_reindex"]) if "_do_force_reindex" in kfun else ""
if not seg_fr:
    seg_fr = ast.get_source_segment(KNOW, kfun.get("force_reindex")) or ""
seg_fr_ok = ohne_kommentare("def _x():\n" + "\n".join("    " + z for z in seg_fr.splitlines()))
check("der Neuaufbau-Rumpf wurde gefunden (Positivkontrolle)",
      "vs.clear()" in seg_fr_ok, seg_fr_ok[:80])
idx_guard = seg_fr_ok.find("if not folders:")
idx_clear = seg_fr_ok.find("vs.clear()")
check("die Schranke steht VOR vs.clear() – im selben Rumpf", 0 < idx_guard < idx_clear,
      f"guard={idx_guard} clear={idx_clear}")


# ═══ 4) Die Migration – AUSGEFUEHRT, nicht gelesen ═════════════════════════
print("\n[4] Migration im Sandkasten")
sand = Path(tempfile.mkdtemp(prefix="ragtest-"))
try:
    # ⚠ SANDKASTEN-WAECHTER: zeigt irgendetwas aus dem Wegwerf-Verzeichnis
    # heraus, bricht der Lauf ab. "Konnte nicht laufen" darf nie wie
    # "bestanden" aussehen – deshalb Exit 2.
    if not str(sand).startswith(tempfile.gettempdir()):
        print("ABBRUCH: Sandkasten liegt nicht im Temp-Verzeichnis"); sys.exit(2)

    from backend import rag_migration as rm

    # Bestand nachbauen, wie er auf DEV wirklich aussieht.
    (sand / "data" / "knowledge" / "pending").mkdir(parents=True)
    (sand / "data" / "knowledge" / "pending" / "e1.json").write_text("{}")
    (sand / "data" / "knowledge" / ".groups.json").write_text("{}")
    (sand / "data" / "knowledge" / "altes_wissen.md").write_text("# Wissen")
    (sand / "data" / "community").mkdir(parents=True)
    (sand / "data" / "community" / "a.md").write_text("A")
    (sand / "data" / "logs").mkdir(parents=True)
    (sand / "data" / "logs" / "darf_nicht_wandern.log").write_text("L")
    (sand / "data" / "kollision").mkdir(parents=True)
    (sand / "data" / "kollision" / "alt.md").write_text("ALT")
    (sand / "data" / "rag" / "kollision").mkdir(parents=True)
    (sand / "data" / "rag" / "kollision" / "schon_da.md").write_text("BESTAND")
    (sand / "data" / "leerziel").mkdir(parents=True)
    (sand / "data" / "leerziel" / "quelle.md").write_text("Q")
    (sand / "data" / "rag" / "leerziel").mkdir(parents=True)   # existiert, ist LEER

    gespeichert = {}
    class FakeConfig:
        def get_skill_states(self):
            return {"knowledge": {"enabled": True, "config": dict(cfg_state)}}
        def save_skill_state(self, name, state):
            gespeichert["state"] = state
            cfg_state.update(state.get("config", {}))
    cfg_state = {"folders": "data/knowledge,data/community,/mnt/jarvis-kb/share_0,"
                            "data/logs,/srv/fremd,data/kollision,data/leerziel",
                 "mounts": [{"type": "smb", "source": "//h/s",
                             "mountpoint": "/mnt/jarvis-kb/share_0"}]}

    bewegt = []
    class FakeKnowledge:
        @staticmethod
        def relocate_folder_index(alt, neu):
            bewegt.append((str(alt), str(neu)))
            return {"vector_chunks": 3}

    import types
    fake_cfg_mod = types.ModuleType("backend.config"); fake_cfg_mod.config = FakeConfig()
    fake_kn = types.ModuleType("backend.tools.knowledge")
    fake_kn.relocate_folder_index = FakeKnowledge.relocate_folder_index
    alt_cfg = sys.modules.get("backend.config")
    alt_kn = sys.modules.get("backend.tools.knowledge")
    sys.modules["backend.config"] = fake_cfg_mod
    sys.modules["backend.tools.knowledge"] = fake_kn
    alt_root_m, alt_root_p = rm.PROJECT_ROOT, rp.PROJECT_ROOT
    rm.PROJECT_ROOT = sand; rp.PROJECT_ROOT = sand
    # /mnt darf im Test nicht wirklich angelegt werden -> in den Sandkasten lenken
    alt_mount, alt_altmount = rp.MOUNT_BASIS, rp.ALT_MOUNT_BASIS
    rp.MOUNT_BASIS = sand / "mnt" / "rag"
    rp.ALT_MOUNT_BASIS = sand / "mnt" / "jarvis-kb"
    cfg_state["folders"] = cfg_state["folders"].replace("/mnt/jarvis-kb", str(rp.ALT_MOUNT_BASIS))
    cfg_state["mounts"][0]["mountpoint"] = str(rp.ALT_MOUNT_BASIS / "share_0")

    erg = sicher(rm.migriere)
    check("Migration lief durch", isinstance(erg, dict), repr(erg))

    if isinstance(erg, dict):
        check("data/community ist umgezogen",
              (sand / "data" / "rag" / "community" / "a.md").exists()
              and not (sand / "data" / "community").exists())
        # ⚠ AUSDRUECKLICHE VORGABE DES BETREIBERS: die Wurzel ist `data/rag`,
        # ein Unterordner `knowledge` war NICHT gewollt. Der Umzug darf ihn
        # unter keinen Umstaenden anlegen – auch nicht "hilfsweise", um Wissen
        # zu retten. Was in data/knowledge liegt, bleibt dort und wird benannt.
        check("⚠ es entsteht KEIN data/rag/knowledge",
              not (sand / "data" / "rag" / "knowledge").exists(),
              str(sorted(x.name for x in (sand / "data" / "rag").iterdir())))
        check("das Wissen in data/knowledge bleibt unangetastet liegen",
              (sand / "data" / "knowledge" / "altes_wissen.md").exists())
        check("data/knowledge steht NICHT mehr in der Ordnerliste",
              "data/knowledge" not in cfg_state.get("folders", ""),
              cfg_state.get("folders", ""))
        check("⚠ pending/ und .groups.json bleiben unangetastet",
              (sand / "data" / "knowledge" / "pending" / "e1.json").exists()
              and (sand / "data" / "knowledge" / ".groups.json").exists())
        rest = sicher(rm._restwissen_zaehlen)
        check("⚠ die Infrastruktur zaehlt NICHT als Restwissen (kein Fehlalarm)",
              isinstance(rest, list) and "pending" not in rest
              and ".groups.json" not in rest, repr(rest))
        check("echtes Wissen dort WIRD gezaehlt (Positivkontrolle)",
              isinstance(rest, list) and "altes_wissen.md" in rest, repr(rest))
        check("⚠ data/logs wurde NICHT verschoben (Systemordner)",
              (sand / "data" / "logs" / "darf_nicht_wandern.log").exists()
              and not (sand / "data" / "rag" / "logs").exists())

        neue_liste = cfg_state.get("folders", "")
        check("Ordnerliste zeigt auf data/rag", "data/rag/community" in neue_liste, neue_liste)
        check("Freigabe zeigt auf die neue Mount-Wurzel",
              str(rp.MOUNT_BASIS / "share_0") in neue_liste, neue_liste)
        check("der alte Mount-Pfad steht nicht mehr in der Liste",
              str(rp.ALT_MOUNT_BASIS) not in neue_liste, neue_liste)
        # Live auf DEV meldete die erste Fassung "6 Freigabe(n)" fuer drei –
        # Ordnerliste und Mount-Eintrag wurden in denselben Zaehler addiert.
        check("die Zaehler von Ordnerliste und Mount-Eintrag sind getrennt",
              erg.get("mounts") == 1 and erg.get("mount_eintraege") == 1,
              f"mounts={erg.get('mounts')} eintraege={erg.get('mount_eintraege')}")
        check("der Mount-EINTRAG wurde ebenfalls umgeschrieben",
              cfg_state["mounts"][0]["mountpoint"] == str(rp.MOUNT_BASIS / "share_0"),
              cfg_state["mounts"][0]["mountpoint"])
        check("der Systemordner bleibt in der Liste stehen (wird benannt, nicht geschluckt)",
              "data/logs" in neue_liste, neue_liste)
        check("⚠ ein vorhandener Zielordner wird NICHT ueberschrieben",
              (sand / "data" / "rag" / "kollision" / "schon_da.md").exists()
              and (sand / "data" / "kollision" / "alt.md").exists()
              and "data/kollision" in neue_liste,
              neue_liste)
        check("⚠ auch ein LEERER Zielordner wird nicht ersetzt (rename gelaenge dort)",
              (sand / "data" / "leerziel" / "quelle.md").exists()
              and not (sand / "data" / "rag" / "leerziel" / "quelle.md").exists(),
              neue_liste)
        check("⚠ der absolute Fremdpfad wurde NICHT in den Wissensbaum geschoben",
              "/srv/fremd" in neue_liste
              and not (sand / "data" / "rag" / "srv").exists(),
              neue_liste)
        check("der Index wurde mit umgeschrieben", len(bewegt) >= 1, str(bewegt))

        # Zweiter Lauf: idempotent UND still.
        bewegt.clear()
        erg2 = sicher(rm.migriere)
        check("zweiter Lauf ist still (idempotent)",
              isinstance(erg2, dict) and erg2.get("still") is True, repr(erg2))
        check("zweiter Lauf fasst den Index nicht an", not bewegt, str(bewegt))

        # ⚠ LIVE AUF DEV GEFUNDEN: `/mnt` gehoert root, das Backend laeuft
        # unprivilegiert – das mkdir scheiterte mit EACCES, der Eintrag blieb in
        # der Ordnerliste stehen, WAEHREND der Mount-Eintrag daneben schon
        # umgeschrieben war. Zwei Seiten, die auf verschiedene Pfade zeigen.
        # Hier wird genau das nachgestellt: Wurzel nicht anlegbar.
        sperr = sand / "gesperrt"
        sperr.mkdir(); os.chmod(sperr, 0o500)
        alt_m2 = rp.MOUNT_BASIS
        rp.MOUNT_BASIS = sperr / "rag"
        cfg_state["folders"] = str(rp.ALT_MOUNT_BASIS / "share_9")
        cfg_state["mounts"] = [{"type": "smb", "source": "//h/s9",
                                "mountpoint": str(rp.ALT_MOUNT_BASIS / "share_9")}]
        try:
            sicher(rm.migriere)
            in_liste = str(rp.MOUNT_BASIS / "share_9") in cfg_state.get("folders", "")
            in_eintrag = cfg_state["mounts"][0]["mountpoint"] == str(rp.MOUNT_BASIS / "share_9")
            check("Ordnerliste und Mount-Eintrag ziehen GEMEINSAM um, auch wenn "
                  "das Verzeichnis nicht anlegbar ist",
                  in_liste and in_eintrag,
                  f"liste={cfg_state.get('folders')} eintrag={cfg_state['mounts'][0]['mountpoint']}")
        finally:
            os.chmod(sperr, 0o700)
            rp.MOUNT_BASIS = alt_m2

finally:
    for name, wert in [("backend.config", alt_cfg), ("backend.tools.knowledge", alt_kn)]:
        if wert is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = wert
    rm.PROJECT_ROOT, rp.PROJECT_ROOT = alt_root_m, alt_root_p
    rp.MOUNT_BASIS, rp.ALT_MOUNT_BASIS = alt_mount, alt_altmount
    shutil.rmtree(sand, ignore_errors=True)


# ═══ 5) Der Startup-Hook ruft sie wirklich – und an der richtigen Stelle ═════
print("\n[5] Verdrahtung im Dienststart")
hooks = [n.name for n in ast.walk(baum)
         if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
         and any(isinstance(d, ast.Call) and getattr(d.func, "attr", "") == "on_event"
                 and d.args and getattr(d.args[0], "value", "") == "startup"
                 for d in n.decorator_list)]
check("startup_rag_umzug ist ein Startup-Hook", "startup_rag_umzug" in hooks, str(hooks[:8]))
if "startup_rag_umzug" in hooks:
    node = funktionen["startup_rag_umzug"]
    seg = ast.get_source_segment(MAIN, node) or ""
    ruft = any(isinstance(n, ast.Call) and
               (getattr(n.func, "id", "") == "migriere" or
                any(getattr(a, "id", "") == "migriere" for a in n.args))
               for n in ast.walk(node))
    check("der Hook ruft migriere() wirklich auf", ruft, seg[:120])
    # Reihenfolge: nach dem Journal-Replay, vor dem BM25-Vorbau.
    i_replay = hooks.index("startup_replay_vector_journal") if "startup_replay_vector_journal" in hooks else -1
    i_umzug = hooks.index("startup_rag_umzug")
    i_warm = hooks.index("startup_warm_lexical_index") if "startup_warm_lexical_index" in hooks else 10**6
    check("Hook laeuft NACH dem Journal-Replay", i_replay < i_umzug, f"{i_replay} < {i_umzug}")
    check("Hook laeuft VOR dem BM25-Vorbau", i_umzug < i_warm, f"{i_umzug} < {i_warm}")


# ═══ 6) Oberflaeche: kein data/xxx mehr in der Liste ════════════════════════
print("\n[6] Anzeige")
KJS = (ROOT / "frontend" / "js" / "knowledge.js").read_text(encoding="utf-8")
check("die Ordnerzeile nimmt den Anzeigenamen, nicht den Pfad",
      "isRoot ? (display || this._anzeigePfad(path))" in KJS)
check("_renderFolders reicht `display` durch", "f.has_children, f.display" in KJS)
# ⚠ DAS FELD MESSEN, NICHT DIE FUNKTION. Die erste Fassung zaehlte Aufrufe von
# `_rag.anzeige(` – eine Sabotage, die nur den SCHLUESSEL umbenennt, liess sie
# gruen: der Client bekaeme dann kein `display` und faellt auf seinen Rueckfall
# zurueck, also genau die Drift, gegen die das Feld gebaut ist.
for fname in ("get_knowledge_stats", "knowledge_folder_tree",
              "browse_knowledge_dir", "wissen_scope"):
    node = funktionen.get(fname)
    check(f"{fname} vorhanden", node is not None)
    if node is None:
        continue
    seg = ohne_kommentare("def _x():\n" + "\n".join(
        "    " + z for z in (ast.get_source_segment(MAIN, node) or "").splitlines()))
    check(f"{fname} liefert das Feld `display`",
          '"display"' in seg and "_rag.anzeige(" in seg, seg[:100])
check("der Knopf fuer BELIEBIGE Pfade ist weg (er hob die Regel auf)",
      "btn-kb-add-folder" not in KJS
      and "btn-kb-add-folder" not in (ROOT / "frontend" / "settings.html").read_text(encoding="utf-8"))
check("und sein toter Helfer auch", "_buildNewFolderList" not in KJS)
# ⚠ NUR DER SCREENSHOT HAT DAS GEZEIGT: ohne `line-height` schneidet
# `overflow: hidden` den Unterstrich ab – aus `share_1` wird sichtbar
# `share 1`, also ein FALSCHER Name. Die Messung las `textContent` und fand
# ihn korrekt; abgeschnitten wurde er erst beim Malen.
CSS = (ROOT / "frontend" / "css" / "style.css").read_text(encoding="utf-8")
i = CSS.find(".kb-folder-path {")
regel = CSS[i: CSS.find("}", i)] if i >= 0 else ""
check("die Ordnerzeile hat eine Regel (Positivkontrolle)", "overflow" in regel, regel[:60])
check("sie gibt dem Unterstrich Hoehe (line-height)", "line-height" in regel, regel)

I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
check("die toten i18n-Schluessel sind entfernt",
      "knowledge.add_btn" not in I18N and "knowledge.add_title" not in I18N)
check("kein Hinweistext nennt data/knowledge als Wissensordner",
      "data/knowledge" not in I18N)

print(f"\nErgebnis: {OK} OK, {FAIL} FAIL")
sys.exit(1 if FAIL else 0)
