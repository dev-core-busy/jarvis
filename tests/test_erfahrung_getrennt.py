#!/usr/bin/env python3
"""Waechter: Erfahrungswissen liegt AUSSERHALB der Wissensdatenbank.

Vorgabe 2026-09-13: die Notizen des Auto-Learnings sind Verfahrenswissen des
Agenten, keine Kundendokumentation – sie gehoeren nicht in dieselbe Vektor-DB
wie Handbuecher. Der Schutz ist bewusst KEIN Filter und KEIN Ranking-Gewicht,
sondern ein Ordner ausserhalb jedes Wissensordners: was `_all_files()` nicht
sieht, kann nicht hineinrutschen.

Geprueft werden EIGENSCHAFTEN und REGELN, nicht Vorkommen:
  1. Der Ort liegt ausserhalb jedes Wissensordners – als Regel ueber die
     Vorgabe-Ordnerliste, damit auch ein KUENFTIGER Wissensordner auffaellt.
  2. Kein Modul baut den Pfad oder das Dateinamens-Praefix nach (das waren
     drei bzw. acht Stellen; eine vergessene zeigt still ins Leere).
  3. Der Schreibweg indiziert NICHT – per AST gemessen, nicht per Textsuche:
     `learning.py` hatte mit `_index_immediately` einen ZWEITEN, aktiven Weg
     in die Vektor-DB, den ein blosser Ordnerwechsel offen gelassen haette.
  4. Die Abwertungs-Konstrukte sind weg (LEARNED_PENALTY & Co.).
  5. Die Migration laeuft WIRKLICH: verschieben, umbenennen, Index aufraeumen.
  6. Der Umzugs-Hook steht NACH dem Journal-Replay (sonst spielt der Replay
     die Chunks unmittelbar danach wieder ein).

Sandkasten: die Migration wird gegen ein Wegwerf-Verzeichnis ausgefuehrt.
Zeigt ein Pfad aus ihm heraus, bricht der Lauf mit Exit 2 ab – "konnte nicht
laufen" darf nie wie "bestanden" aussehen.
"""
import ast
import io
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = FAIL = 0


def check(beschreibung, bedingung, info=""):
    global OK, FAIL
    if bedingung:
        OK += 1
        print(f"  OK   {beschreibung}")
    else:
        FAIL += 1
        print(f"  FAIL {beschreibung}" + (f"  [{info}]" if info else ""))


def sicher(fn, *a, **kw):
    """Nie ungeprueft dereferenzieren: ein Wurf darf den Lauf nicht ohne
    Bilanzzeile beenden – das waere von 'nicht gelaufen' nicht zu unterscheiden."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return f"<WURF: {type(e).__name__}: {e}>"


def quelle(rel):
    return io.open(ROOT / rel, encoding="utf-8").read()


def ohne_kommentare(q: str) -> str:
    """Kommentare und Docstrings entfernen – sonst liest der Waechter seine
    eigene Begruendung (im Projekt vierzehnmal bezahlt).

    ⚠ UEBER `tokenize`, NICHT ueber `split("#")`: ein `#` steht auch INNERHALB
    von Zeichenketten (in main.py z.B. in Farbwerten und Byte-Literalen). Die
    naive Fassung zerschnitt dort mehrzeilige Strings und machte den Quelltext
    unparsebar – ein Waechter, der den Quelltext umbaut, prueft nicht mehr den
    Quelltext. Ersetzt werden nur die BEREICHE, alles andere bleibt Zeichen
    fuer Zeichen stehen.
    """
    import tokenize as _tk
    zeilen = q.splitlines(keepends=True)
    weg = []
    try:
        for tok in _tk.generate_tokens(io.StringIO(q).readline):
            if tok.type == _tk.COMMENT:
                weg.append((tok.start, tok.end))
    except Exception:  # noqa: BLE001 – lieber ungefiltert als gar nicht
        pass
    for (z1, s1), (z2, s2) in reversed(weg):
        if z1 == z2 and z1 - 1 < len(zeilen):
            zeile = zeilen[z1 - 1]
            zeilen[z1 - 1] = zeile[:s1] + " " * (s2 - s1) + zeile[s2:]
    ohne = "".join(zeilen)
    # Docstrings zusaetzlich per AST – sie sind keine Kommentar-Tokens.
    try:
        baum = ast.parse(ohne)
    except SyntaxError:
        return ohne
    zl = ohne.splitlines()
    for n in ast.walk(baum):
        if isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) \
                and isinstance(n.value.value, str):
            for i in range(n.lineno - 1, min(n.end_lineno, len(zl))):
                zl[i] = ""
    return "\n".join(zl)


# Positivkontrolle des Kommentar-Entferners: ohne sie waere jede Pruefung
# darunter, die "kommt nicht vor" lautet, moeglicherweise nur deshalb gruen,
# weil der Entferner zu viel weggenommen hat.
_probe = "x = 1  # LEARNED_PENALTY\ny = \"#hash\"  # weg\n"
_pr = ohne_kommentare(_probe)
check("Kommentar-Entferner nimmt Kommentare weg (Positivkontrolle)",
      "LEARNED_PENALTY" not in _pr, _pr)
check("Kommentar-Entferner laesst Code stehen (Positivkontrolle)",
      "x = 1" in _pr and '"#hash"' in _pr, _pr)


print("\n=== 1. Der Ort liegt ausserhalb JEDES Wissensordners ===")
import backend.learning as L  # noqa: E402

# Positivkontrolle: ohne sie waere jede Aussage darunter ueber eine leere
# Menge trivial wahr.
check("LEARNED_DIR ist gesetzt", isinstance(L.LEARNED_DIR, Path), repr(L.LEARNED_DIR))
check("NOTIZ_PRAEFIX ist gesetzt und nicht leer",
      isinstance(L.NOTIZ_PRAEFIX, str) and len(L.NOTIZ_PRAEFIX) > 2, repr(L.NOTIZ_PRAEFIX))

# Die REGEL: gegen die Vorgabe-Ordnerliste des Wissens-Skills, nicht gegen
# einen abgetippten Pfad. Kommt morgen ein Wissensordner dazu, faellt er hier auf.
kq = ohne_kommentare(quelle("backend/tools/knowledge.py"))
vorgabe = None
for n in ast.parse(kq).body:
    if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "DEFAULT_FOLDER":
        vorgabe = n.value.value
check("DEFAULT_FOLDER aus knowledge.py gelesen", isinstance(vorgabe, str), repr(vorgabe))

wissensordner = [(ROOT / p.strip()).resolve()
                 for p in (vorgabe or "").split(",") if p.strip()]
erf = L.LEARNED_DIR.resolve()
for wo in wissensordner:
    drin = erf == wo or wo in erf.parents
    check(f"LEARNED_DIR liegt NICHT unter '{wo.relative_to(ROOT)}'", not drin, str(erf))

check("LEARNED_DIR liegt nicht unter data/knowledge",
      "knowledge" not in erf.relative_to(ROOT).parts, str(erf))

# Die Gegenprobe zur Fehlkonfiguration: der Ordnername ist reserviert, damit
# ihn niemand als Wissensordner eintragen kann.
mq = ohne_kommentare(quelle("backend/main.py"))
reserviert = None
for n in ast.parse(mq).body:
    if isinstance(n, ast.Assign) and getattr(n.targets[0], "id", "") == "_KB_RESERVED_DATA_DIRS":
        reserviert = {e.value for e in n.value.elts}
check("Ordnername steht in _KB_RESERVED_DATA_DIRS",
      isinstance(reserviert, set) and erf.name in reserviert, str(reserviert))


print("\n=== 2. Kein Modul baut Ort oder Praefix nach ===")
# REGEL statt Liste: ausser learning.py (die Quelle) und dem Waechter darf
# nirgends mehr ein data/knowledge/learned-Pfad konstruiert werden.
treffer = []
for pfad in list((ROOT / "backend").rglob("*.py")) + list((ROOT / "deploy").rglob("*.py")):
    rel = pfad.relative_to(ROOT)
    if rel.name == "learning.py":
        continue
    q = sicher(lambda p=pfad: ohne_kommentare(io.open(p, encoding="utf-8").read()))
    if isinstance(q, str) and q.startswith("<WURF"):
        continue
    for muster in ('data/knowledge/learned', '"knowledge" / "learned"',
                   '"knowledge", "learned"'):
        if muster in q:
            treffer.append(f"{rel}: {muster}")
check("kein Modul baut den Erfahrungs-Pfad nach", not treffer, "; ".join(treffer))

praefix_treffer = []
for pfad in list((ROOT / "backend").rglob("*.py")) + list((ROOT / "deploy").rglob("*.py")):
    rel = pfad.relative_to(ROOT)
    if rel.name == "learning.py":
        continue
    q = sicher(lambda p=pfad: ohne_kommentare(io.open(p, encoding="utf-8").read()))
    if not isinstance(q, str) or q.startswith("<WURF"):
        continue
    # ⚠ `conv_log` AUSNEHMEN: das ist das Konversations-Log, eine voellig
    # andere Sache. Das erste Muster traf `f"conv_log fehlgeschlagen"` und
    # meldete zwei Fehler, die es nicht gab – dieselbe Klasse wie
    # `z.benutzer` gegen `z.benutzer_vorschlag` im Register.
    for muster in ('"conv_*', "'conv_*", '"conv_konsolidiert', "'conv_konsolidiert",
                   'f"conv_{', '"conv_" +'):
        if muster in q:
            praefix_treffer.append(f"{rel}: {muster}")
check("kein Modul verdrahtet das alte Dateinamens-Praefix",
      not praefix_treffer, "; ".join(praefix_treffer))
_probe_q = 'x = d.glob("conv_*.md")\ny = f"conv_log fehlgeschlagen"'
_gefunden = [m for m in ('"conv_*', "'conv_*", '"conv_konsolidiert', "'conv_konsolidiert",
                         'f"conv_{', '"conv_" +') if m in _probe_q]
check("das Praefix-Muster greift ueberhaupt (Positivkontrolle)", bool(_gefunden), str(_gefunden))
check("und verschont conv_log (Gegenkontrolle)", len(_gefunden) == 1, str(_gefunden))


print("\n=== 3. Der Schreibweg indiziert NICHT (per AST) ===")
lq = quelle("backend/learning.py")
baum = ast.parse(lq)
schreibweg = None
for n in ast.walk(baum):
    if isinstance(n, ast.FunctionDef) and n.name == "_save_and_index":
        schreibweg = n
check("Schreibfunktion _save_and_index gefunden", schreibweg is not None)

verbotene = {"_get_vector_store", "add_chunks", "add_chunks_deferred",
             "_index_immediately", "auto_assign_system_files"}
gerufen = set()
if schreibweg is not None:
    for n in ast.walk(schreibweg):
        if isinstance(n, ast.Call):
            f = n.func
            name = getattr(f, "id", None) or getattr(f, "attr", None)
            if name:
                gerufen.add(name)
check("Schreibweg ruft nichts Indizierendes", not (gerufen & verbotene),
      str(gerufen & verbotene))

# Positivkontrolle des Schnitts: er enthaelt wirklich den Schreibvorgang.
check("Schnitt enthaelt den Schreibvorgang (Positivkontrolle)",
      "write_text" in gerufen, str(sorted(gerufen)))

check("_index_immediately existiert nicht mehr",
      not any(isinstance(n, ast.FunctionDef) and n.name == "_index_immediately"
              for n in ast.walk(baum)))

# Und das Modul als Ganzes: kein Weg in den Vektor-Index mehr.
lq_ok = ohne_kommentare(lq)
modul_gerufen = {getattr(n.func, "id", None) or getattr(n.func, "attr", None)
                 for n in ast.walk(ast.parse(lq_ok)) if isinstance(n, ast.Call)}
# _get_vector_store bleibt erlaubt: die MIGRATION braucht es, um die alten
# Chunks zu ENTFERNEN. Hinzufuegen darf sie nichts.
check("Modul fuegt nirgends Chunks hinzu",
      not ({"add_chunks", "add_chunks_deferred"} & modul_gerufen),
      str({"add_chunks", "add_chunks_deferred"} & modul_gerufen))


print("\n=== 4. Die Abwertungs-Konstrukte sind weg ===")
for name, datei in (("LEARNED_PENALTY", "backend/tools/knowledge.py"),
                    ("_is_learned_note", "backend/tools/knowledge.py"),
                    ("_learned_weight", "backend/tools/knowledge.py"),
                    ("auto_assign_system_files", "backend/knowledge_groups.py"),
                    ("LEARNED_PATH_PREFIX", "backend/knowledge_groups.py")):
    q = ohne_kommentare(quelle(datei))
    check(f"{name} ist aus {Path(datei).name} entfernt", name not in q)

kq2 = ohne_kommentare(quelle("backend/tools/knowledge.py"))
check("die Suche reicht kein Herkunfts-Gewicht mehr durch",
      "weight_fn=" not in kq2, "weight_fn noch gesetzt")


print("\n=== 5. Die Migration laeuft wirklich ===")
sandkasten = Path(tempfile.mkdtemp(prefix="erfahrung_test_"))
try:
    alt = sandkasten / "data" / "knowledge" / "learned"
    neu = sandkasten / "data" / "erfahrung"
    (alt / "2026-09").mkdir(parents=True)
    (alt / "konsolidiert").mkdir(parents=True)
    (alt / "2026-09" / "conv_111_abc.md").write_text("# Gelernt: Test\n", encoding="utf-8")
    (alt / "2026-09" / "feedback_222.md").write_text("# Feedback\n", encoding="utf-8")
    (alt / "konsolidiert" / "conv_konsolidiert_thema.md").write_text("# T\n", encoding="utf-8")

    # SANDKASTEN-WAECHTER: zeigt ein Pfad heraus, wird nichts ausgefuehrt.
    for p in (alt, neu):
        if sandkasten not in p.resolve().parents and p.resolve() != sandkasten:
            print(f"ABBRUCH: Pfad zeigt aus dem Sandkasten heraus: {p}")
            sys.exit(2)

    entfernt = {"aufgerufen": None}

    class _VS:
        def remove_files(self, pfade):
            entfernt["aufgerufen"] = list(pfade)
            return len(pfade)

    # Ein Attrappen-MODUL in sys.modules, kein Import des echten: das zieht
    # config -> dotenv -> FAISS mit und laeuft ausserhalb des Produktiv-venv
    # gar nicht. Die Migration importiert lazy, greift also die Attrappe.
    # ⚠ DAMIT DIE ATTRAPPE NICHT DIE EIGENE ANNAHME PRUEFT, wird der Name
    # `_get_vector_store` gleich danach am ECHTEN Quelltext gegengeprueft.
    import types as _t
    fake_k = _t.ModuleType("backend.tools.knowledge")
    fake_k._get_vector_store = lambda: _VS()
    fake_kg = _t.ModuleType("backend.knowledge_groups")
    vorher_k = sys.modules.get("backend.tools.knowledge")
    vorher_kg = sys.modules.get("backend.knowledge_groups")
    sys.modules["backend.tools.knowledge"] = fake_k
    sys.modules["backend.knowledge_groups"] = fake_kg

    orig_dir, orig_alt = L.LEARNED_DIR, L._ALTER_ORT
    L.LEARNED_DIR, L._ALTER_ORT = neu, alt
    try:
        erg = sicher(L.migriere_aus_wissensdatenbank)
    finally:
        L.LEARNED_DIR, L._ALTER_ORT = orig_dir, orig_alt
        for name, vorher in (("backend.tools.knowledge", vorher_k),
                             ("backend.knowledge_groups", vorher_kg)):
            if vorher is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = vorher

    # Gegenprobe zur Attrappe: heisst die Funktion im Original wirklich so?
    _kq = ast.parse(quelle("backend/tools/knowledge.py"))
    check("_get_vector_store existiert im ECHTEN knowledge.py (Attrappen-Gegenprobe)",
          any(isinstance(n, ast.FunctionDef) and n.name == "_get_vector_store"
              for n in ast.walk(_kq)))

    check("Migration lief ohne Wurf", isinstance(erg, dict), str(erg))
    if isinstance(erg, dict):
        check("keine Fehler gemeldet", not erg.get("fehler"), str(erg.get("fehler")))
        check("3 Dateien verschoben", erg.get("verschoben") == 3, str(erg))

    check("Notiz ist am neuen Ort UND umbenannt",
          (neu / "2026-09" / f"{L.NOTIZ_PRAEFIX}111_abc.md").exists(),
          str(sorted(p.name for p in neu.rglob("*.md"))))
    check("Konsolidat ist umbenannt",
          (neu / "konsolidiert" / f"{L.NOTIZ_PRAEFIX}konsolidiert_thema.md").exists())
    check("feedback_* bleibt UNANGETASTET (andere Gattung)",
          (neu / "2026-09" / "feedback_222.md").exists(),
          str(sorted(p.name for p in neu.rglob("*.md"))))
    check("der alte Ort ist weg", not alt.exists())
    check("nichts bleibt am alten Ort liegen (verschoben, nicht kopiert)",
          not list(alt.rglob("*.md")) if alt.exists() else True)

    # Der Index MUSS aufgeraeumt werden – sonst bleiben die Chunks bis zum
    # naechsten Voll-Reindex suchbar, und der laeuft nur auf Knopfdruck.
    check("Index-Chunks der alten Pfade wurden entfernt",
          entfernt["aufgerufen"] is not None and len(entfernt["aufgerufen"]) == 3,
          str(entfernt["aufgerufen"]))
    if entfernt["aufgerufen"]:
        check("entfernt wurden die ALTEN Pfade",
              all("knowledge/learned" in p for p in entfernt["aufgerufen"]),
              str(entfernt["aufgerufen"])[:120])

    # Zweiter Lauf: idempotent und still.
    L.LEARNED_DIR, L._ALTER_ORT = neu, alt
    try:
        erg2 = sicher(L.migriere_aus_wissensdatenbank)
    finally:
        L.LEARNED_DIR, L._ALTER_ORT = orig_dir, orig_alt
    check("zweiter Lauf verschiebt nichts mehr (idempotent)",
          isinstance(erg2, dict) and erg2.get("verschoben") == 0 and not erg2.get("umbenannt"),
          str(erg2))
finally:
    shutil.rmtree(sandkasten, ignore_errors=True)


print("\n=== 6. Der Umzugs-Hook steht NACH dem Journal-Replay ===")
mq_roh = quelle("backend/main.py")
pos = {}
for n in ast.walk(ast.parse(mq_roh)):
    if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) and n.name in (
            "startup_replay_vector_journal", "startup_erfahrung_umzug"):
        pos[n.name] = n.lineno
check("beide Startup-Hooks vorhanden", len(pos) == 2, str(pos))
check("der Umzug laeuft NACH dem Journal-Replay",
      pos.get("startup_erfahrung_umzug", 0) > pos.get("startup_replay_vector_journal", 10**9),
      str(pos))


print("\n=== 7. data/knowledge/ traegt NICHTS aus dem Repo ===")
# DIE TRAGENDE REGEL (Vorgabe 2026-09-13): "solche Dateien haben in
# data/knowledge nichts zu suchen". data/knowledge/ ist der Wissensspeicher des
# KUNDEN – was dort aus dem Repo liegt, ist per Definition Projektwissen, also
# Verfahrenswissen, und landet auf jedem Kundenserver in derselben Vektor-DB wie
# seine Handbuecher. Geprueft wird die EIGENSCHAFT (git kennt dort keine Datei),
# nicht eine Namensliste – damit faellt auch eine KUENFTIGE auf.
import subprocess as _sp


def _git(*args):
    """git im Repo – gibt (rc, zeilen) oder (None, Fehlertext)."""
    r = sicher(lambda: _sp.run(["git", *args], cwd=ROOT, capture_output=True,
                               text=True, timeout=30))
    if not hasattr(r, "returncode"):
        return None, str(r)
    if r.returncode not in (0, 1):
        return None, (r.stderr or "").strip().splitlines()[0:1]
    return r.returncode, [z for z in r.stdout.splitlines() if z.strip()]


# ⚠ DIE POSITIVKONTROLLE STEHT ZUERST, UND SIE IST DIE BEDINGUNG.
# Erster Entwurf war fail-OPEN: schlug `git` fehl (auf DEV „dubiose
# Besitzverhaeltnisse", weil das Repo jarvis gehoert und der Lauf als root
# lief), kam eine leere Liste zurueck – und „git verfolgt keine Datei" war
# GRUEN, ohne dass ein einziges Kommando gearbeitet hatte. „Konnte nicht
# laufen" darf nie wie „bestanden" aussehen.
_rc_pk, _pk = _git("ls-files", "data/instructions_default/")
_git_geht = _rc_pk is not None and len(_pk) > 3
check("git arbeitet in diesem Repo (Positivkontrolle – Bedingung fuer 7.)",
      _git_geht, str(_pk)[:120])

if not _git_geht:
    check("git verfolgt KEINE Datei unter data/knowledge/", False,
          "NICHT PRUEFBAR – git arbeitet hier nicht (siehe Positivkontrolle)")
else:
    _rc, _verfolgt = _git("ls-files", "data/knowledge/")
    check("git verfolgt KEINE Datei unter data/knowledge/", not _verfolgt, str(_verfolgt))

# Und die .gitignore darf keine Wieder-Einschluesse darunter tragen: genau drei
# solcher `!`-Zeilen hatten die Regel bis 2026-09-13 unterlaufen.
_gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
_ausnahmen = [z.strip() for z in _gi.splitlines()
              if z.strip().startswith("!") and "/data/knowledge/" in z
              and z.strip() != "!/data/knowledge/"]
check("keine .gitignore-Ausnahme schleust eine Datei wieder ein",
      not _ausnahmen, str(_ausnahmen))

# Neu angelegte Wissensdateien muessen ignoriert bleiben (funktional geprueft).
if _git_geht:
    _probe = ROOT / "data" / "knowledge" / ".waechter_probe.md"
    _probe.parent.mkdir(parents=True, exist_ok=True)
    try:
        _probe.write_text("x\n", encoding="utf-8")
        _rc_ci, _ = _git("check-ignore", "-q", str(_probe))
        check("eine neue Datei unter data/knowledge/ wird ignoriert", _rc_ci == 0,
              f"returncode={_rc_ci}")
    finally:
        _probe.unlink(missing_ok=True)
else:
    check("eine neue Datei unter data/knowledge/ wird ignoriert", False,
          "NICHT PRUEFBAR – git arbeitet hier nicht")


print("\n=== 8. Das Index-Aufraeumen fasst KEINE Datei an ===")
lq8 = ast.parse(quelle("backend/learning.py"))
fn8 = None
for n in ast.walk(lq8):
    if isinstance(n, ast.FunctionDef) and n.name == "verfahrensdateien_aus_index_raeumen":
        fn8 = n
check("Aufraeumfunktion gefunden", fn8 is not None)

schreibend = {"unlink", "rmtree", "move", "write_text", "rename", "remove", "replace"}
gerufen8 = set()
if fn8 is not None:
    for n in ast.walk(fn8):
        if isinstance(n, ast.Call):
            nm = getattr(n.func, "id", None) or getattr(n.func, "attr", None)
            if nm:
                gerufen8.add(nm)
check("sie ruft nichts Schreibendes auf der Platte", not (gerufen8 & schreibend),
      str(gerufen8 & schreibend))
check("sie raeumt den Index (Positivkontrolle)", "remove_files" in gerufen8,
      str(sorted(gerufen8)))
# Die Zusage "nur was WEG ist": ein `not ....exists()` muss in der Bedingung stehen.
_q8 = ast.get_source_segment(quelle("backend/learning.py"), fn8) or ""
check("sie raeumt nur, was nicht mehr existiert",
      "not kandidat.exists()" in _q8 or ("not " in _q8 and ".exists()" in _q8))

# Die Namensliste ist endlich und wird nicht geraten.
import backend.learning as _L8
check("die drei Namen stehen als Konstante",
      isinstance(_L8._REPO_VERFAHRENSDATEIEN, tuple)
      and len(_L8._REPO_VERFAHRENSDATEIEN) == 3,
      str(getattr(_L8, "_REPO_VERFAHRENSDATEIEN", None)))
check("und keine davon ist mehr im Repo",
      not any((ROOT / "data" / "knowledge" / n).exists() and
              n in "\n".join(_verfolgt) for n in _L8._REPO_VERFAHRENSDATEIEN))

# Verdrahtung: die Funktion allein nuetzt nichts.
# ⚠ PER AST AUF DEN AUFRUF, NICHT AUF DAS VORKOMMEN: der erste Versuch suchte
# den Namen im Quelltext – und traf damit die IMPORT-Zeile, die auch dann
# stehenbleibt, wenn der Aufruf entfernt wurde. Die Gegenprobe blieb gruen.
_hook8 = None
for n in ast.walk(ast.parse(quelle("backend/main.py"))):
    if isinstance(n, (ast.AsyncFunctionDef, ast.FunctionDef)) \
            and n.name == "startup_erfahrung_umzug":
        _hook8 = n
check("Startup-Hook gefunden", _hook8 is not None)
_args8 = set()
if _hook8 is not None:
    for n in ast.walk(_hook8):
        if isinstance(n, ast.Call):
            for a in list(n.args) + [n.func]:
                nm = getattr(a, "id", None) or getattr(a, "attr", None)
                if nm:
                    _args8.add(nm)
check("der Startup-Hook ruft sie wirklich",
      "verfahrensdateien_aus_index_raeumen" in _args8, str(sorted(_args8)))
check("und den Umzug ebenfalls (Positivkontrolle)",
      "migriere_aus_wissensdatenbank" in _args8, str(sorted(_args8)))


print(f"\n{'='*60}\nErgebnis: {OK} OK, {FAIL} FAIL\n{'='*60}")
sys.exit(1 if FAIL else 0)
