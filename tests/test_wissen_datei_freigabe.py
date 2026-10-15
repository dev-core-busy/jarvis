#!/usr/bin/env python3
"""Waechter: /wissen -> Mein Wissen oeffnet auch Dateien von FREIGABEN.

Befund 2026-09-27, auf ECHT rein lesend gemessen: 1161 Zuordnungen, davon 89
mit dem Schluessel `mnt/rag/share_N/…` – und `GET /api/wissen/file` fand
KEINE davon (0 von 89), weil es den Schluessel gegen PROJECT_ROOT aufloeste
(`/opt/jarvis/mnt/…` gibt es nicht). Jeder Klick darauf war ein 404.

`wissen_file`, `_wissen_datei_ziel` und `_wissen_absolut` werden per `ast`
aus backend/main.py geschnitten und WIRKLICH AUSGEFUEHRT – gegen echte
Dateien in einem Wegwerf-Verzeichnis, mit dem ECHTEN `_bounded_call`.

Geprueft wird die EIGENSCHAFT:
  1. Freigabe-Datei (Schluessel ohne fuehrenden Schraegstrich) wird geliefert
  2. lokale Datei und Altbestand unter PROJECT_ROOT (nicht mehr konfiguriert)
     weiter wie bisher
  3. SCHRANKE: Traversal, fremder absoluter Ort und ein Symlink aus einem
     Wissensordner heraus werden abgewiesen – auch wenn der Schluessel
     zugeordnet ist
  4. fehlende Datei 404, fremde Gruppe 403 (Rechte VOR dem Dateizugriff)
  5. ein haengender Speicherort haelt den Endpunkt nicht auf (504 nach Deckel)
  7. (Code-Review 2026-10-07) Nur WISSENSORTE: `.env`, `data/settings.json`,
     fremde Chats und das Gruppen-Manifest sind trotz Zuordnung 400 – vorher
     galt "alles unter PROJECT_ROOT", und ein Gruppen-Editor las so `.env`;
     der Zuordnungs-Endpunkt nimmt solche Schluessel gar nicht erst an
  6. DELETE geht denselben Weg (Vorgabe 2026-09-27): die Freigabe-Datei wird
     geloescht samt Zuordnung und Index-Eintrag (unter dem ABSOLUTEN Pfad),
     eine nur lesende Freigabe meldet 409 mit Grund statt eines rohen 500,
     Schranke und Deckel gelten auch hier

Exit 2 = konnte nicht laufen.
"""
from __future__ import annotations

import ast
import asyncio
import os
import shutil
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "backend" / "main.py"
KNOW = ROOT / "backend" / "tools" / "knowledge.py"

res: list[bool] = []


def check(name, cond, detail=""):
    res.append(bool(cond))
    mark = "\033[32m✓\033[0m" if cond else "\033[31m✗\033[0m"
    print(f"  {mark} {name}" + ("" if cond else f" – {detail}"))


def abschnitt(t):
    print(f"\n\033[1m{t}\033[0m")


def abbruch(t):
    print(f"\033[31mABBRUCH: {t}\033[0m")
    sys.exit(2)


def funktionen(pfad):
    baum = ast.parse(pfad.read_text(encoding="utf-8"))
    fn = {n.name: n for n in baum.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    kon = {}
    for n in baum.body:
        ziel = (n.targets[0] if isinstance(n, ast.Assign) and len(n.targets) == 1
                else n.target if isinstance(n, ast.AnnAssign) else None)
        if isinstance(ziel, ast.Name):
            kon[ziel.id] = n
    return fn, kon


FN, KON = funktionen(MAIN)
KFN, _ = funktionen(KNOW)
for name in ("wissen_file", "wissen_file_delete", "_wissen_datei_ziel", "_wissen_absolut"):
    if name not in FN:
        abbruch(f"{name} nicht in backend/main.py")
if "_WISSEN_DATEI_DECKEL" not in KON or "_bounded_call" not in KFN:
    abbruch("Deckel oder _bounded_call nicht gefunden")

# ── Sandkasten ────────────────────────────────────────────────────────────
TMP = Path(tempfile.mkdtemp(prefix="wdatei_"))
PROJ = TMP / "proj"
(PROJ / "data" / "rag" / "a").mkdir(parents=True)
(PROJ / "data" / "rag" / "a" / "lokal.md").write_text("lokal")
(PROJ / "data" / "knowledge").mkdir(parents=True)
(PROJ / "data" / "knowledge" / "alt.md").write_text("alt")      # Altbestand, nicht konfiguriert
# Review 2026-10-07: Geheimnisse und Systemdateien UNTER PROJECT_ROOT
(PROJ / ".env").write_text("GEHEIM=1")
(PROJ / "data" / "settings.json").write_text("{}")
(PROJ / "data" / "chats" / "bob").mkdir(parents=True)
(PROJ / "data" / "chats" / "bob" / "preprompt.txt").write_text("bob")
(PROJ / "data" / "knowledge" / ".groups.json").write_text("{}")
SHARE = TMP / "aussen" / "share_1"
SHARE.mkdir(parents=True)
(SHARE / "Anleitungen SAP.one").write_bytes(b"one")
FREMD = TMP / "geheim"
FREMD.mkdir()
(FREMD / "passwd").write_text("geheim")
# Symlink AUS dem Wissensordner heraus – nach resolve() liegt das Ziel fremd
(SHARE / "link.txt").symlink_to(FREMD / "passwd")
HAENGT = TMP / "haengt" / "share_2"       # konfiguriert, aber "stumm"
HAENGT.mkdir(parents=True)
(HAENGT / "x.pdf").write_text("x")

KEY = lambda p: str(p).lstrip("/")        # noqa: E731 – so schreibt _rel() den Schluessel
K_SHARE = KEY(SHARE / "Anleitungen SAP.one")
K_LINK = KEY(SHARE / "link.txt")
K_FREMD = KEY(FREMD / "passwd")
K_HAENGT = KEY(HAENGT / "x.pdf")
K_TRAV = "data/rag/a/../../../../geheim/passwd"   # VIER Ebenen: drei landen noch in proj/
ZUORDNUNG = {
    "data/rag/a/lokal.md": ["g1"], "data/knowledge/alt.md": ["g1"],
    K_SHARE: ["g1"], K_LINK: ["g1"], K_FREMD: ["g1"], K_HAENGT: ["g1"],
    K_TRAV: ["g1"], "data/rag/a/weg.md": ["g1"], "data/rag/a/andere.md": ["g2"],
    ".env": ["g1"], "data/settings.json": ["g1"], "data/chats/bob/preprompt.txt": ["g1"],
    "data/knowledge/.groups.json": ["g1"],
}
if (PROJ / K_SHARE.split("/", 1)[0]).exists():
    abbruch("Sandkasten: Freigabe-Schluessel wuerde unter PROJ aufgeloest")

haengen = {"an": False}
_echtes_resolve = Path.resolve


def _resolve_attrappe(self, *a, **k):
    # Ein toter CIFS-Mount: schon resolve() kehrt nicht zurueck.
    if haengen["an"] and str(self).startswith(str(HAENGT)):
        time.sleep(4)
    return _echtes_resolve(self, *a, **k)


Path.resolve = _resolve_attrappe

kn = types.ModuleType("backend.tools.knowledge")
kn.PROJECT_ROOT = PROJ
kn._get_folders = lambda: [PROJ / "data" / "rag" / "a", SHARE, HAENGT]
sys.modules.setdefault("backend", types.ModuleType("backend"))
sys.modules.setdefault("backend.tools", types.ModuleType("backend.tools"))
sys.modules["backend.tools.knowledge"] = kn
# Die Wurzeln kommen aus der ECHTEN rag_pfad (eine Quelle), Einhaengepunkt-
# Basis im Sandkasten: sonst saehe der Test /mnt/rag des Rechners.
import importlib.util as _ilu  # noqa: E402
_spec = _ilu.spec_from_file_location("backend.rag_pfad", ROOT / "backend" / "rag_pfad.py")
rp = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(rp)
rp.MOUNT_BASIS = TMP / "mnt_rag"
sys.modules["backend.rag_pfad"] = rp
kg = types.ModuleType("backend.knowledge_groups")
kg.get_assignment = lambda rel: ZUORDNUNG.get(rel, [])
entfernt_zuordnung: list = []
kg.set_assignment = lambda rel, gids: entfernt_zuordnung.append((rel, list(gids)))
entfernt_index: list = []


class _VS:
    def remove_file(self, p):
        entfernt_index.append(p)


kn._get_vector_store = lambda: _VS()
sys.modules["backend.knowledge_groups"] = kg
sys.modules["backend"].knowledge_groups = kg

zugriffe_vor_rechten = []


class Antwort:
    def __init__(self, content, status_code=200):
        self.content, self.status_code = content, status_code


class Datei:
    def __init__(self, path, media_type=None, filename=None, content_disposition_type=None):
        self.path, self.status_code, self.filename = path, 200, filename


NS = {"Path": Path, "asyncio": asyncio, "os": os, "time": time, "threading": threading,
      "JSONResponse": Antwort, "FileResponse": Datei,
      "Depends": lambda x: None, "require_auth_or_query": None, "require_auth": None,
      "Request": object,
      "_editable_groups_for": lambda user: [{"id": "g1"}]}
knoten = [ast.parse(ast.unparse(KON["_WISSEN_DATEI_DECKEL"])).body[0]]
for name in ("_wissen_absolut", "_wissen_wurzeln", "_wissen_unter_wurzel",
             "_wissen_schluessel_erlaubt", "_wissen_datei_ziel", "wissen_file",
             "wissen_file_delete"):
    if name not in FN:
        abbruch(f"{name} nicht in backend/main.py")
    k = ast.parse(ast.unparse(FN[name])).body[0]
    k.decorator_list = []
    knoten.append(k)
exec(compile(ast.fix_missing_locations(ast.Module(body=knoten, type_ignores=[])), "<main>", "exec"), NS)
# Der ECHTE _bounded_call – die Begrenzung ist Teil der Zusage.
kns = {"threading": threading}
exec(compile(ast.fix_missing_locations(ast.Module(body=[KFN["_bounded_call"]], type_ignores=[])),
             "<knowledge>", "exec"), kns)
kn._bounded_call = kns["_bounded_call"]


def hole(rel, deckel=None):
    if deckel is not None:
        NS["_WISSEN_DATEI_DECKEL"] = deckel
    try:
        return asyncio.run(NS["wissen_file"](path=rel, user="anna")), None
    except Exception as e:   # noqa: BLE001 – ein Wurf ist ein FAIL, kein Abbruch
        return None, f"{type(e).__name__}: {e}"


def status(a):
    return getattr(a, "status_code", None)


try:
    abschnitt("1 – Freigabe-Datei wird geliefert (der gemeldete Fall)")
    a, w = hole(K_SHARE)
    check("antwortet ohne Wurf", w is None, w)
    check("200 mit der Datei von der Freigabe",
          status(a) == 200 and Path(getattr(a, "path", "")) == (SHARE / "Anleitungen SAP.one"),
          (status(a), getattr(a, "path", None), getattr(a, "content", None)))

    abschnitt("2 – lokale Datei und Altbestand unveraendert")
    a, _ = hole("data/rag/a/lokal.md")
    check("Positivkontrolle: lokale Datei 200", status(a) == 200, (status(a), getattr(a, "content", None)))
    a, _ = hole("data/knowledge/alt.md")
    check("Altbestand unter PROJECT_ROOT (nicht konfiguriert) weiter 200", status(a) == 200,
          (status(a), getattr(a, "content", None)))

    abschnitt("3 – die Schranke")
    a, _ = hole(K_TRAV)
    check("Traversal aus dem Projekt heraus: 400", status(a) == 400, (status(a), getattr(a, "content", None)))
    a, _ = hole(K_FREMD)
    check("fremder absoluter Ort (zugeordnet!): 400", status(a) == 400, (status(a), getattr(a, "content", None)))
    a, _ = hole(K_LINK)
    check("Symlink aus der Freigabe heraus: 400", status(a) == 400, (status(a), getattr(a, "content", None)))

    abschnitt("3b – nur Wissensorte (Code-Review 2026-10-07)")
    for rel in (".env", "data/settings.json", "data/chats/bob/preprompt.txt",
                "data/knowledge/.groups.json"):
        a, _ = hole(rel)
        check(f"zugeordnet, aber kein Wissensort: {rel} -> 400", status(a) == 400,
              (status(a), getattr(a, "content", None)))
    erl = NS["_wissen_schluessel_erlaubt"]
    for rel, soll in (("data/rag/a/lokal.md", True), ("data/rag/a/neu.md", True),
                      ("data/knowledge/alt.md", True), (K_SHARE, True),
                      (KEY(TMP / "mnt_rag" / "share_9" / "x.pdf"), True),
                      (".env", False), ("data/settings.json", False),
                      ("data/chats/bob/preprompt.txt", False), ("data/rag", False),
                      ("data/knowledge/.groups.json", False), (K_TRAV, False),
                      ("data/rag/a/../../../.env", False), (K_FREMD, False)):
        check(f"Zuordnung annehmen? {rel} -> {soll}", erl(rel) is soll, erl(rel))

    # Der Zuordnungs-Endpunkt ist zu verdrahtet, um ihn hier auszufuehren –
    # gemessen wird am SYNTAXBAUM: ein `if not _wissen_schluessel_erlaubt(...)`,
    # dessen Rumpf mit `return` endet, steht VOR dem ersten `set_assignment`.
    zf = FN.get("knowledge_assignments_set")
    check("Positivkontrolle: Zuordnungs-Endpunkt gefunden", zf is not None)
    if zf is not None:
        def _ruft(knoten, name):
            return any(isinstance(n, ast.Call) and (
                (isinstance(n.func, ast.Name) and n.func.id == name)
                or (isinstance(n.func, ast.Attribute) and n.func.attr == name))
                for n in ast.walk(knoten))
        setz = [n.lineno for n in ast.walk(zf) if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute) and n.func.attr == "set_assignment"]
        schranken = [n.lineno for n in ast.walk(zf) if isinstance(n, ast.If)
                     and isinstance(n.test, ast.UnaryOp) and isinstance(n.test.op, ast.Not)
                     and _ruft(n.test, "_wissen_schluessel_erlaubt")
                     and n.body and isinstance(n.body[-1], ast.Return)]
        check("Positivkontrolle: set_assignment im Endpunkt gefunden", bool(setz))
        check("Zuordnung prueft den Wissensort VOR dem Speichern (mit return)",
              bool(schranken) and bool(setz) and min(schranken) < min(setz),
              (schranken, setz))

    abschnitt("4 – fehlend / fremde Gruppe")
    a, _ = hole("data/rag/a/weg.md")
    check("zugeordnet, aber nicht auf Platte: 404", status(a) == 404, status(a))
    a, _ = hole("data/rag/a/andere.md")
    check("fremde Gruppe: 403", status(a) == 403, status(a))

    abschnitt("5 – haengender Speicherort")
    haengen["an"] = True
    t0 = time.monotonic()
    a, w = hole(K_HAENGT, deckel=0.5)
    dauer = time.monotonic() - t0
    haengen["an"] = False
    check("kehrt nach dem Deckel zurueck (< 2 s statt 4 s)", dauer < 2.0, f"{dauer:.2f} s")
    check("… mit 504 und Grund", status(a) == 504 and "antwortet" in str(getattr(a, "content", "")),
          (status(a), getattr(a, "content", None), w))
    NS["_WISSEN_DATEI_DECKEL"] = 5.0
    time.sleep(4.2)            # Daemon-Thread auslaufen lassen
    a, _ = hole(K_HAENGT)
    check("Positivkontrolle: derselbe Ort ohne Haengen 200", status(a) == 200, status(a))

    abschnitt("6 – DELETE auf demselben Weg")

    class _Req:
        def __init__(self, rel):
            self._rel = rel

        async def json(self):
            return {"path": self._rel}

    def loesche(rel):
        try:
            return asyncio.run(NS["wissen_file_delete"](request=_Req(rel), user="anna")), None
        except Exception as e:   # noqa: BLE001
            return None, f"{type(e).__name__}: {e}"

    ziel = SHARE / "Anleitungen SAP.one"
    a, w = loesche(K_SHARE)
    check("Freigabe-Datei: 200", status(a) == 200, (status(a), getattr(a, "content", None), w))
    check("… die Datei ist WIRKLICH weg", not ziel.exists())
    check("… Zuordnung geleert", (K_SHARE, []) in entfernt_zuordnung, entfernt_zuordnung)
    check("… Index-Eintrag unter dem ABSOLUTEN Pfad entfernt (so fuehrt ihn der Index)",
          str(ziel) in entfernt_index, entfernt_index)

    # nur lesende Freigabe: Verzeichnis ohne Schreibrecht -> unlink scheitert
    ro = TMP / "ro" / "share_4"
    ro.mkdir(parents=True)
    (ro / "fest.pdf").write_text("x")
    K_RO = KEY(ro / "fest.pdf")
    ZUORDNUNG[K_RO] = ["g1"]
    alt_folders = kn._get_folders
    kn._get_folders = lambda: alt_folders() + [ro]
    os.chmod(ro, 0o555)
    try:
        if os.geteuid() == 0:
            check("nur-lesend: NICHT PRUEFBAR als root (Rechte greifen nicht)", False)
        else:
            a, w = loesche(K_RO)
            check("nur lesende Freigabe: 409 statt rohem 500", status(a) == 409,
                  (status(a), getattr(a, "content", None), w))
            check("… mit verstaendlichem Grund (kein 'Errno')",
                  "Errno" not in str(getattr(a, "content", "")) and "Löschen" in str(getattr(a, "content", "")),
                  getattr(a, "content", None))
            check("… und die Datei ist noch da", (ro / "fest.pdf").exists())
    finally:
        os.chmod(ro, 0o755)
        kn._get_folders = alt_folders

    vor = (FREMD / "passwd").exists()
    a, _ = loesche(K_TRAV)
    check("DELETE Traversal: 400 und NICHTS geloescht",
          status(a) == 400 and vor and (FREMD / "passwd").exists(), status(a))
    a, _ = loesche(K_LINK)
    check("DELETE ueber Symlink nach aussen: 400, Ziel unberuehrt",
          status(a) == 400 and (FREMD / "passwd").exists() and (SHARE / "link.txt").is_symlink(), status(a))
    a, _ = loesche("data/rag/a/andere.md")
    check("DELETE fremde Gruppe: 403", status(a) == 403, status(a))
    a, _ = loesche(".env")
    check("DELETE .env (zugeordnet): 400 und die Datei steht noch",
          status(a) == 400 and (PROJ / ".env").is_file(), status(a))
    haengen["an"] = True
    NS["_WISSEN_DATEI_DECKEL"] = 0.5
    t0 = time.monotonic()
    a, _ = loesche(K_HAENGT)
    dauer = time.monotonic() - t0
    haengen["an"] = False
    NS["_WISSEN_DATEI_DECKEL"] = 5.0
    check("DELETE haengender Speicherort: 504 nach Deckel", status(a) == 504 and dauer < 2.0,
          (status(a), f"{dauer:.2f} s"))
    time.sleep(4.2)

    # ⚠ Das LOESCHEN selbst haengt (resolve/is_file antworten noch, erst
    # unlink bleibt stehen). Ohne diesen Fall war die Begrenzung des unlink
    # ungeprueft – die Gegenprobe "Loeschen ohne Deckel" blieb stumm.
    _echtes_unlink = Path.unlink
    haengt_unlink = {"an": True}

    def _unlink_attrappe(self, *a, **k):
        if haengt_unlink["an"] and str(self).startswith(str(HAENGT)):
            time.sleep(4)
        return _echtes_unlink(self, *a, **k)

    Path.unlink = _unlink_attrappe
    NS["_WISSEN_DATEI_DECKEL"] = 0.5
    try:
        t0 = time.monotonic()
        a, _ = loesche(K_HAENGT)
        dauer = time.monotonic() - t0
    finally:
        NS["_WISSEN_DATEI_DECKEL"] = 5.0
    check("DELETE: haengendes unlink -> 504 nach Deckel (< 2 s statt 4 s)",
          status(a) == 504 and dauer < 2.0, (status(a), f"{dauer:.2f} s"))
    check("… die Meldung sagt, dass der Ausgang UNBEKANNT ist",
          "unbekannt" in str(getattr(a, "content", "")), getattr(a, "content", None))
    time.sleep(4.2)
    haengt_unlink["an"] = False
    Path.unlink = _echtes_unlink
finally:
    Path.resolve = _echtes_resolve
    shutil.rmtree(TMP, ignore_errors=True)

print(f"\n\033[1mErgebnis: {sum(res)}/{len(res)}\033[0m")
sys.exit(0 if all(res) else 1)
