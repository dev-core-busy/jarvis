"""Waechter fuer die Index-Automatik (Vorgabe 2026-09-21).

Gemessen werden EIGENSCHAFTEN, nicht Vorkommen:
  * die Erkennungsregeln laufen WIRKLICH (neu/geaendert/verwaist, Praefix-Falle)
  * ``pruefen()`` schreibt nichts - per AST, gegen jeden schreibenden Aufruf
  * ``lauf()`` stoesst den Reindex NUR bei Bedarf an - ausgefuehrt, an einer
    Attrappe, die ihre Aufrufe zaehlt
  * DRIFT: ``_rebuild_vector_index`` RUFT die beiden Regeln, statt sie nachzubauen
  * es gibt keinen ZWEITEN Indizierweg

``backend.config`` wird NICHT importiert (schriebe die echte settings.json
zurueck) - die Helfer kommen per ast-Schnitt, das Automatik-Modul laeuft gegen
eine Attrappe in ``sys.modules``.
"""
import ast
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

ok = fail = 0


def check(text, bedingung):
    global ok, fail
    if bedingung:
        ok += 1
        print(f"  OK   {text}")
    else:
        fail += 1
        print(f"  FAIL {text}")


def sicher(fn, *a, **kw):
    """Nie ungeprueft dereferenzieren - ein Wurf darf nicht die Bilanz kosten."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return f"WURF: {type(e).__name__}: {e}"


K_SRC = (ROOT / "backend" / "tools" / "knowledge.py").read_text(encoding="utf-8")
AI_SRC = (ROOT / "backend" / "rag_autoindex.py").read_text(encoding="utf-8")
MAIN_SRC = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")


def schneide(src, *namen):
    """Funktionen per AST herausschneiden und ausfuehrbar machen."""
    baum = ast.parse(src)
    teile = [ast.get_source_segment(src, n) for n in baum.body
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in namen]
    fehlend = set(namen) - {n.name for n in baum.body
                            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    if fehlend:
        raise SystemExit(f"Exit 2: Funktion(en) nicht gefunden: {sorted(fehlend)}")
    ns = {"os": os, "Path": Path}
    exec("\n\n".join(teile), ns)  # noqa: S102
    return ns


def ohne_worte(src: str) -> str:
    """Kommentare UND Docstrings entfernen.

    ⚠ Ohne das liest der Waechter seine eigene Begruendung: die Docstrings hier
    nennen ``force_reindex`` und ``add_chunks`` woertlich, um zu erklaeren,
    warum sie NICHT vorkommen duerfen.
    """
    baum = ast.parse(src)
    for knoten in ast.walk(baum):
        if isinstance(knoten, (ast.FunctionDef, ast.AsyncFunctionDef,
                               ast.ClassDef, ast.Module)):
            leib = getattr(knoten, "body", [])
            if (leib and isinstance(leib[0], ast.Expr)
                    and isinstance(leib[0].value, ast.Constant)
                    and isinstance(leib[0].value.value, str)):
                leib.pop(0)
    return ast.unparse(baum)


# ══ 1. Die Erkennungsregeln laufen wirklich ═══════════════════════════════
print("\n1. Erkennungsregeln (ausgefuehrt)")
NS = schneide(K_SRC, "_geaenderte_dateien", "_verwaiste_dateien")
_geaendert = NS["_geaenderte_dateien"]
_verwaist = NS["_verwaiste_dateien"]


class FakePath:
    """Minimale Path-Attrappe: nur str() und stat().st_mtime zaehlen."""

    def __init__(self, pfad, mtime=None):
        self._p = pfad
        self._m = mtime

    def __str__(self):
        return self._p

    def stat(self):
        if self._m is None:
            raise OSError("Netzlaufwerk gerade weg")
        return types.SimpleNamespace(st_mtime=self._m)


indexed = {"/kb/a.md": 100.0, "/kb/b.md": 200.0}
files = [FakePath("/kb/a.md", 100.0),      # unveraendert
         FakePath("/kb/b.md", 999.0),      # geaendert
         FakePath("/kb/c.md", 300.0),      # neu
         FakePath("/kb/d.md", None)]       # stat() wirft

erg = sicher(_geaendert, files, indexed)
namen = sorted(str(f) for f in erg) if isinstance(erg, list) else erg
check("unveraenderte Datei wird NICHT gemeldet", "/kb/a.md" not in (namen or []))
check("geaenderte Datei wird gemeldet", "/kb/b.md" in (namen or []))
check("neue Datei wird gemeldet", "/kb/c.md" in (namen or []))
check("Datei mit geworfenem stat() wird UEBERSPRUNGEN (kein Dauer-Reindex)",
      "/kb/d.md" not in (namen or []))

# Praefix-Falle: share_1 steckt in share_10
idx = {"/mnt/rag/share_1/x.md": 1.0, "/mnt/rag/share_10/y.md": 1.0,
       "/mnt/rag/share_2/z.md": 1.0}
alive = ["/mnt/rag/share_1"]
st = sicher(_verwaist, set(), idx, alive)
check("verwaist: nur aus ERREICHBAREN Ordnern",
      isinstance(st, list) and st == ["/mnt/rag/share_1/x.md"])
check("verwaist: share_10 wird NICHT als Teil von share_1 gezaehlt (Praefix-Falle)",
      isinstance(st, list) and "/mnt/rag/share_10/y.md" not in st)
st2 = sicher(_verwaist, {"/mnt/rag/share_1/x.md"}, idx, alive)
check("verwaist: vorhandene Datei gilt nicht als verwaist",
      isinstance(st2, list) and st2 == [])
st3 = sicher(_verwaist, set(), idx, [])
check("verwaist: KEIN erreichbarer Ordner -> nichts wird abgeraeumt",
      isinstance(st3, list) and st3 == [])

# ══ 2. DRIFT: der Reindex ruft dieselben Regeln ═══════════════════════════
print("\n2. Drift-Schranke: eine Fassung, zwei Aufrufer")
k_baum = ast.parse(K_SRC)
# ⚠ DIE DRIFT-SCHRANKE GILT DEM INDEXLAUF, NICHT EINEM FUNKTIONSNAMEN.
# Seit der Nebenlaeufigkeits-Sperre (2026-09-25) ist `_rebuild_vector_index` nur
# noch die WEICHE; gearbeitet wird in `_vector_index_lauf`. Ein Schnitt auf den
# alten Namen meldete danach zwei Fehler, die es nicht gibt.
_WEG = ("_rebuild_vector_index", "_inline_vector_index", "_vector_index_lauf")
weg_fns = [n for n in ast.walk(k_baum)
           if isinstance(n, ast.FunctionDef) and n.name in _WEG]
check(f"der Vektor-Indexweg gefunden ({len(weg_fns)} Funktionen)", bool(weg_fns))
if weg_fns:
    rufe = {n.func.id for fn in weg_fns for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    check("der Indexlauf RUFT _geaenderte_dateien (baut sie nicht nach)",
          "_geaenderte_dateien" in rufe)
    check("der Indexlauf RUFT _verwaiste_dateien",
          "_verwaiste_dateien" in rufe)

ai_baum = ast.parse(AI_SRC)
pr = next((n for n in ast.walk(ai_baum)
           if isinstance(n, ast.FunctionDef) and n.name == "pruefen"), None)
check("pruefen() gefunden", pr is not None)
if pr is not None:
    attr_rufe = {n.func.attr for n in ast.walk(pr)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    check("pruefen() benutzt _geaenderte_dateien aus knowledge",
          "_geaenderte_dateien" in attr_rufe)
    check("pruefen() benutzt _verwaiste_dateien aus knowledge",
          "_verwaiste_dateien" in attr_rufe)

# ══ 3. pruefen() schreibt NICHTS ══════════════════════════════════════════
print("\n3. Die Vorpruefung ist rein lesend")
SCHREIBEND = {"force_reindex", "add_chunks", "add_chunks_deferred", "remove_file",
              "remove_files", "clear", "save", "_save_last_run", "_set_progress",
              "write_text", "unlink", "mkdir", "replace"}
# ⚠ AUF DER DOCSTRING-FREIEN FASSUNG. Der Docstring von pruefen() erklaert
# woertlich, warum `streng=True` Pflicht ist - auf dem Rohtext geprueft las der
# Waechter seine eigene Begruendung und blieb bei sabotiertem Code gruen.
_clean_baum = ast.parse(ohne_worte(AI_SRC))
pr_clean = next((n for n in ast.walk(_clean_baum)
                 if isinstance(n, ast.FunctionDef) and n.name == "pruefen"), None)
check("Positivkontrolle: pruefen() auch ohne Docstrings gefunden", pr_clean is not None)
if pr_clean is not None:
    q_pr = ast.unparse(pr_clean)
    check("Positivkontrolle: die Begruendung ist aus dem Prueftext entfernt",
          "Pflicht" not in q_pr and "_nutzbare_ordner" in q_pr)
    alle = {n.func.attr for n in ast.walk(pr_clean)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    alle |= {n.func.id for n in ast.walk(pr_clean)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    treffer = alle & SCHREIBEND
    check(f"pruefen() ruft nichts Schreibendes (gefunden: {sorted(treffer) or 'nichts'})",
          not treffer)
    check("pruefen() oeffnet keine Datei zum Schreiben", "open" not in alle)
    # streng=True ist Pflicht: sonst zaehlt ein getrenntes Share als verwaist
    check("pruefen() prueft die Ordner STRENG (getrenntes Share zaehlt nicht als geloescht)",
          "streng=True" in q_pr)

# ══ 4. Kein zweiter Indizierweg ═══════════════════════════════════════════
print("\n4. Es gibt genau EINEN Indizierweg")
ai_clean = ohne_worte(AI_SRC)
check("Positivkontrolle: die Begruendungen sind entfernt",
      "ausdrueckliche Neuaufbau" not in ai_clean and "force_reindex" in ai_clean)
for verboten in ("add_chunks", "_extract_text", "_chunk_text"):
    check(f"rag_autoindex indiziert nicht selbst (kein {verboten})",
          verboten not in ai_clean)
check("rag_autoindex benutzt den vorhandenen Weg (force_reindex)",
      "force_reindex" in ai_clean)
check("und zwar INKREMENTELL (kein vs.clear, Loeschungen werden aufgeraeumt)",
      "incremental=True" in ai_clean)

# ══ 5. lauf() AUSGEFUEHRT: Reindex nur bei Bedarf ═════════════════════════
print("\n5. lauf() ausgefuehrt (Attrappe zaehlt die Aufrufe)")

# ⚠ Die Attrappe stellt die ECHTEN geschnittenen Erkennungsregeln bereit - eine
# nachgebaute Fassung wuerde die eigene Annahme pruefen statt den Code.
class FakeVS:
    def __init__(self, idx):
        self._idx = idx

    def get_indexed_files(self):
        return dict(self._idx)


class FakeK(types.ModuleType):
    def __init__(self):
        super().__init__("backend.tools.knowledge")
        self.reindex_rufe = []
        self.idx = {}
        self.dateien = []
        self.running = False
        self.pruef_wirft = False
        self.reindex_wirft = False
        self._geaenderte_dateien = _geaendert    # ECHT
        self._verwaiste_dateien = _verwaist      # ECHT

    def _get_vector_store(self):
        if self.pruef_wirft:
            raise RuntimeError("Vektor-Store kaputt")
        return FakeVS(self.idx)

    def _get_folders(self):
        return ["/kb"]

    def _nutzbare_ordner(self, folders, indexed, streng=True):
        return list(folders)

    def _all_files(self, alive):
        return list(self.dateien)

    def get_index_progress(self):
        return {"running": self.running}

    def force_reindex(self, **kw):
        self.reindex_rufe.append(kw)
        if self.reindex_wirft:
            raise RuntimeError("Indexlauf gescheitert")
        return {"ok": True}


class FakeCron(types.ModuleType):
    """Scheduler-Attrappe: haelt genau den einen Wartungsauftrag."""

    def __init__(self):
        super().__init__("backend.scheduler")
        self.jobs = {}
        self.angelegt = []

        aussen = self

        class Mgr:
            def get_job(self, jid):
                return aussen.jobs.get(jid)

            def add_job(self, **kw):
                aussen.angelegt.append(kw)
                j = dict(kw); j["id"] = kw.get("job_id")
                aussen.jobs[kw.get("job_id")] = j
                return j

        self.cron_manager = Mgr()


class FakeConfig(types.ModuleType):
    def __init__(self):
        super().__init__("backend.config")
        self.werte = {}
        aussen = self

        class C:
            def get_setting(self, k, d=None):
                return aussen.werte.get(k, d)

            def save_setting(self, k, v):
                aussen.werte[k] = v

        self.config = C()


def frisch(**felder):
    """Automatik-Modul mit frischem Zustand und frischen Attrappen."""
    for m in ("backend.rag_autoindex", "backend.tools.knowledge", "backend.tools",
              "backend.scheduler", "backend.config", "backend"):
        sys.modules.pop(m, None)
    fk = FakeK()
    for k, v in felder.items():
        setattr(fk, k, v)
    import backend  # noqa: F401
    tools = types.ModuleType("backend.tools")
    sys.modules["backend.tools"] = tools
    sys.modules["backend.tools.knowledge"] = fk
    tools.knowledge = fk
    fc = FakeCron(); sys.modules["backend.scheduler"] = fc
    cfg = FakeConfig(); sys.modules["backend.config"] = cfg
    from backend import rag_autoindex as ai
    ai._test_cron = fc
    ai._test_config = cfg
    return ai, fk


os.environ.pop("JARVIS_RAG_AUTOINDEX_SEK", None)

# (a) nichts geaendert -> KEIN Reindex
ai, fk = frisch(idx={"/kb/a.md": 5.0}, dateien=[FakePath("/kb/a.md", 5.0)])
r = sicher(ai.lauf)
check("nichts geaendert: KEIN Indexlauf", fk.reindex_rufe == [])
check("nichts geaendert: Rueckgabe sagt es", isinstance(r, dict) and not r.get("indiziert"))

# (b) eine Datei geaendert -> genau EIN Reindex, inkrementell
ai, fk = frisch(idx={"/kb/a.md": 5.0}, dateien=[FakePath("/kb/a.md", 9.0)])
r = sicher(ai.lauf)
check("geaenderte Datei: genau EIN Indexlauf", len(fk.reindex_rufe) == 1)
check("geaenderte Datei: INKREMENTELL (Index wird nicht geleert)",
      fk.reindex_rufe == [{"incremental": True}])
check("geaenderte Datei: Rueckgabe meldet 'indiziert'",
      isinstance(r, dict) and r.get("indiziert") is True)

# (c) ⚠ DIE ZUSAGE, DIE VORHER FEHLTE: eine GELOESCHTE Datei loest einen Lauf aus
ai, fk = frisch(idx={"/kb/a.md": 5.0, "/kb/weg.md": 7.0},
                dateien=[FakePath("/kb/a.md", 5.0)])
r = sicher(ai.lauf)
check("GELOESCHTE Datei loest einen Indexlauf aus (vorher: nie)",
      len(fk.reindex_rufe) == 1)
check("geloeschte Datei: Grund nennt sie", isinstance(r, dict) and "1 geloescht" in r.get("grund", ""))

# (d) neue Datei
ai, fk = frisch(idx={}, dateien=[FakePath("/kb/neu.md", 1.0)])
sicher(ai.lauf)
check("neue Datei loest einen Indexlauf aus", len(fk.reindex_rufe) == 1)

# (e) Reindex laeuft bereits -> nicht dazwischenfunken
ai, fk = frisch(idx={}, dateien=[FakePath("/kb/neu.md", 1.0)], running=True)
r = sicher(ai.lauf)
check("laufender Indexlauf: kein zweiter wird angestossen", fk.reindex_rufe == [])
check("laufender Indexlauf: Grund wird genannt",
      isinstance(r, dict) and "laeuft bereits" in r.get("grund", ""))

# (f) Notaus
os.environ["JARVIS_RAG_AUTOINDEX"] = "0"
ai, fk = frisch(idx={}, dateien=[FakePath("/kb/neu.md", 1.0)])
r = sicher(ai.lauf)
check("Notaus: kein Indexlauf", fk.reindex_rufe == [])
check("Notaus: Grund wird genannt",
      isinstance(r, dict) and "abgeschaltet" in r.get("grund", ""))
os.environ.pop("JARVIS_RAG_AUTOINDEX", None)

# (g) Pruefung wirft -> lauf() wirft NICHT
ai, fk = frisch(pruef_wirft=True)
r = sicher(ai.lauf)
check("Pruefung wirft: lauf() wirft nicht (Takt laeuft weiter)", isinstance(r, dict))
check("Pruefung wirft: der Grund wird gemeldet, nicht verschluckt",
      isinstance(r, dict) and "fehlgeschlagen" in r.get("grund", ""))

# (h) Reindex wirft -> lauf() wirft NICHT, Fehler steht im Zustand
ai, fk = frisch(idx={}, dateien=[FakePath("/kb/neu.md", 1.0)], reindex_wirft=True)
r = sicher(ai.lauf)
check("Indexlauf wirft: lauf() wirft nicht", isinstance(r, dict))
z = sicher(ai.zustand)
check("Indexlauf wirft: der Fehler steht im Zustand (sichtbar, nicht still)",
      isinstance(z, dict) and bool(z.get("letzter_fehler")))

# (i) Zustand wird gefuehrt
ai, fk = frisch(idx={"/kb/a.md": 5.0}, dateien=[FakePath("/kb/a.md", 9.0)])
sicher(ai.lauf)
z = sicher(ai.zustand)
check("Zustand: Lauf wird gezaehlt", isinstance(z, dict) and z.get("laeufe") == 1)
check("Zustand: Zeitpunkt der Pruefung gesetzt",
      isinstance(z, dict) and float(z.get("letzte_pruefung") or 0) > 0)
check("Zustand: der Grund des Laufs wird gemerkt",
      isinstance(z, dict) and "neu/geaendert" in (z.get("letzter_grund") or ""))
z2 = sicher(ai.zustand)
if isinstance(z, dict) and isinstance(z2, dict):
    z["laeufe"] = 999
    check("Zustand ist eine KOPIE (niemand kann hineinschreiben)",
          sicher(ai.zustand).get("laeufe") == 1)

# ⚠ Schluessel-Kollision: `lauf()` mischt das dict aus `pruefen()` in seine
# Rueckgabe. Trug beides einen "grund", war die Meldung LEER, obwohl gesetzt.
ai, fk = frisch(idx={"/kb/a.md": 5.0}, dateien=[FakePath("/kb/a.md", 5.0)])
r = sicher(ai.lauf)
check("nichts geaendert: der Grund steht wirklich drin (nicht leergemischt)",
      isinstance(r, dict) and r.get("grund") == "nichts geaendert")

# Ohne Vektor-Store ist es NICHT "nichts geaendert" - das waere eine
# Falschaussage, nach der niemand mehr nach der Ursache sucht.
class KeinVS(FakeK):
    def _get_vector_store(self):
        return None


for m in ("backend.rag_autoindex", "backend.tools.knowledge", "backend.tools", "backend"):
    sys.modules.pop(m, None)
import backend  # noqa: F401,E402
_t = types.ModuleType("backend.tools")
_kv = KeinVS()
sys.modules["backend.tools"] = _t
sys.modules["backend.tools.knowledge"] = _kv
_t.knowledge = _kv
from backend import rag_autoindex as _ai2  # noqa: E402
r = sicher(_ai2.lauf)
check("ohne Vektor-Index: KEIN Indexlauf", _kv.reindex_rufe == [])
check("ohne Vektor-Index: meldet die Ursache, nicht 'nichts geaendert'",
      isinstance(r, dict) and "Vektor-Index" in r.get("grund", ""))

# ══ 6. Notaus ════════════════════════════════════════════════════════════
print("\n6. Notaus (JARVIS_RAG_AUTOINDEX)")
ai, _ = frisch()
os.environ.pop("JARVIS_RAG_AUTOINDEX", None)
check("Vorgabe ist AN (kein Eintrag = laeuft)", ai.abgeschaltet() is False)
for wert in ("0", "false", "nein", "off", "aus", "AUS"):
    os.environ["JARVIS_RAG_AUTOINDEX"] = wert
    check(f"'{wert}' schaltet ab", ai.abgeschaltet() is True)
os.environ["JARVIS_RAG_AUTOINDEX"] = "1"
check("'1' laesst laufen", ai.abgeschaltet() is False)
os.environ["JARVIS_RAG_AUTOINDEX"] = "quatsch"
check("unbrauchbarer Wert laesst laufen (nicht aus!)", ai.abgeschaltet() is False)
os.environ["JARVIS_RAG_AUTOINDEX"] = "0"
check("wirkt OHNE Neustart (Funktion, keine Konstante)", ai.abgeschaltet() is True)
os.environ.pop("JARVIS_RAG_AUTOINDEX", None)

# ══ 6b. Der Cron-Auftrag ══════════════════════════════════════════════════
print("\n6b. Cron-Auftrag: Saat, Marke, Rueckweg")
ai, _ = frisch()
cron, cfg = ai._test_cron, ai._test_config

erg = sicher(ai.auftrag_sicherstellen)
check("erster Start legt den Auftrag an", isinstance(erg, dict) and erg.get("angelegt") is True)
check("genau EIN Auftrag angelegt", len(cron.angelegt) == 1)
kw = cron.angelegt[0] if cron.angelegt else {}
check("⚠ kind='wissensabgleich' (sonst waere es ein Agentenlauf)",
      kw.get("kind") == "wissensabgleich")
check("feste Auftrags-Kennung", kw.get("job_id") == ai.AUFTRAG_ID)
check("laeuft OHNE Systemrechte (er fuehrt nichts aus)",
      not kw.get("owner_privileged"))
check("ist beim Anlegen aktiv", kw.get("enabled") is True)

erg2 = sicher(ai.auftrag_sicherstellen)
check("zweiter Start legt NICHTS neu an (idempotent)",
      isinstance(erg2, dict) and erg2.get("angelegt") is False and len(cron.angelegt) == 1)

# ⚠ Bewusst geloescht: darf NICHT beim naechsten Start zurueckkommen.
cron.jobs.clear()
erg3 = sicher(ai.auftrag_sicherstellen)
check("bewusst geloescht: kommt beim Neustart NICHT zurueck",
      isinstance(erg3, dict) and erg3.get("angelegt") is False and len(cron.angelegt) == 1)
check("und der Grund wird genannt",
      isinstance(erg3, dict) and "geloescht" in erg3.get("grund", ""))

# ... aber der Rueckweg legt ihn wieder an (keine Einbahnstrasse).
erg4 = sicher(ai.auftrag_wiederherstellen)
check("Rueckweg legt ihn neu an", isinstance(erg4, dict) and erg4.get("angelegt") is True)
check("Rueckweg fragt die Marke NICHT", len(cron.angelegt) == 2)

# ══ 6c. zustand() leitet 'aktiv' aus dem ECHTEN Auftrag ab ════════════════
print("\n6c. zustand() spiegelt den echten Auftrag")
ai, _ = frisch()
cron = ai._test_cron
z = sicher(ai.zustand)
check("ohne Auftrag: nicht aktiv", isinstance(z, dict) and z.get("aktiv") is False)
check("ohne Auftrag: auftrag_da=False", isinstance(z, dict) and z.get("auftrag_da") is False)

sicher(ai.auftrag_sicherstellen)
z = sicher(ai.zustand)
check("mit aktivem Auftrag: aktiv", isinstance(z, dict) and z.get("aktiv") is True)
check("der Cron-Ausdruck wird gemeldet", isinstance(z, dict) and z.get("cron") == ai.AUFTRAG_CRON)

# Deaktiviert -> die Anzeige darf NICHT "laeuft" behaupten
cron.jobs[ai.AUFTRAG_ID]["enabled"] = False
z = sicher(ai.zustand)
check("⚠ deaktivierter Auftrag: NICHT aktiv (Anzeige luegt nicht)",
      isinstance(z, dict) and z.get("aktiv") is False)
check("deaktivierter Auftrag: auftrag_da bleibt True (er existiert ja)",
      isinstance(z, dict) and z.get("auftrag_da") is True)

cron.jobs[ai.AUFTRAG_ID]["enabled"] = True
os.environ["JARVIS_RAG_AUTOINDEX"] = "0"
z = sicher(ai.zustand)
check("⚠ Notaus schlaegt den aktiven Auftrag (Anzeige sagt die Wahrheit)",
      isinstance(z, dict) and z.get("aktiv") is False and z.get("notaus") is True)
os.environ.pop("JARVIS_RAG_AUTOINDEX", None)

# ══ 6d. Der Scheduler kennt die Art ═══════════════════════════════════════
print("\n6d. Scheduler: dritte Job-Art")
SCHED_SRC = (ROOT / "backend" / "scheduler.py").read_text(encoding="utf-8")
sched_clean = ohne_worte(SCHED_SRC)
sb_roh = ast.parse(SCHED_SRC)
check("Positivkontrolle: Begruendungen aus dem Prueftext entfernt",
      "Erinnerungs-Ausnahme" not in sched_clean and "add_job" in sched_clean)
# ⚠ Steht die Art NICHT in der Whitelist, wird der Job STILL zu einem
# Agentenlauf - er laeuft, tut etwas anderes als bestellt, und niemand sieht es.
# ⚠ Per AST, nicht per Text: `ast.unparse` normiert auf EINFACHE
# Anfuehrungszeichen, ein Prueftext mit doppelten findet nie etwas.
_erlaubt = set()
for _n in ast.walk(sb_roh):
    if isinstance(_n, ast.Compare) and isinstance(_n.ops[0], ast.In) \
            and isinstance(_n.left, ast.Name) and _n.left.id == "kind":
        for _c in ast.walk(_n.comparators[0]):
            if isinstance(_c, ast.Constant) and isinstance(_c.value, str):
                _erlaubt.add(_c.value)
check(f"⚠ 'wissensabgleich' steht in der kind-Whitelist (gefunden: {sorted(_erlaubt)})",
      "wissensabgleich" in _erlaubt)
check("und die beiden alten Arten sind weiterhin drin",
      {"agent", "reminder"} <= _erlaubt)
sb = ast.parse(SCHED_SRC)
sb_roh = sb
ex = next((n for n in ast.walk(sb)
           if isinstance(n, ast.AsyncFunctionDef) and n.name == "_execute"), None)
check("_execute gefunden", ex is not None)
if ex is not None:
    q = ast.unparse(ex)
    check("_execute hat einen Zweig fuer 'wissensabgleich'", "'wissensabgleich'" in q)
    check("und er ruft die Automatik, NICHT den Agenten",
          "rag_autoindex" in q and "lauf" in q)
    # Die Reihenfolge ist tragend: der Zweig muss VOR dem Agenten-Zweig stehen.
    i_w = q.find("'wissensabgleich'")
    i_a = q.find("run_task_headless")
    check("⚠ der Zweig steht VOR dem Agenten-Zweig (sonst nie erreicht)",
          i_w > 0 and i_a > i_w)
# kind darf nicht nachtraeglich umgeschrieben werden koennen
_upd = set()
for _n in ast.walk(sb_roh):
    if isinstance(_n, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "UPDATABLE_FIELDS" for t in _n.targets):
        for _c in ast.walk(_n.value):
            if isinstance(_c, ast.Constant) and isinstance(_c.value, str):
                _upd.add(_c.value)
check(f"UPDATABLE_FIELDS gefunden ({sorted(_upd)})", bool(_upd))
check("⚠ 'kind' steht NICHT darin (kein Umschreiben zum Agentenjob)",
      "kind" not in _upd)
check("⚠ 'payload' steht NICHT darin", "payload" not in _upd)

# ══ 7. Startup-Hook: saet, faehrt aber KEINEN eigenen Takt ════════════════
print("\n7. Startup-Hook")
m_baum = ast.parse(MAIN_SRC)
hook = next((n for n in ast.walk(m_baum)
             if isinstance(n, ast.AsyncFunctionDef) and n.name == "startup_rag_autoindex"), None)
check("startup_rag_autoindex existiert", hook is not None)
if hook is not None:
    dek = [ast.unparse(d) for d in hook.decorator_list]
    check("haengt am Startup", any("on_event" in d and "startup" in d for d in dek))
    # Docstring weg - er erklaert, warum es KEINEN Takt mehr gibt, und nennt
    # dabei die Woerter, auf die geprueft wird.
    hook_clean = ast.parse(ohne_worte(MAIN_SRC))
    hk = next((n for n in ast.walk(hook_clean)
               if isinstance(n, ast.AsyncFunctionDef) and n.name == "startup_rag_autoindex"), None)
    q = ast.unparse(hk) if hk is not None else ""
    check("Positivkontrolle: Hook auch ohne Docstring gefunden", bool(q))
    check("stellt den Auftrag sicher", "auftrag_sicherstellen" in q)
    check("laeuft im Thread (Dateizugriff gehoert nicht in den Event-Loop)",
          "to_thread" in q)
    # ⚠ KEIN zweiter Ausloeser: der Cron-Auftrag ist der einzige.
    check("⚠ faehrt KEINEN eigenen Takt mehr (kein zweiter Ausloeser)",
          "while True" not in q and "create_task" not in q)
    check("ruft die Automatik nicht selbst aus", ".lauf(" not in q)

print(f"\nErgebnis: {ok} OK, {fail} FAIL")
sys.exit(1 if fail else 0)
