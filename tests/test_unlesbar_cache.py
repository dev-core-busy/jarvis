#!/usr/bin/env python3
"""Waechter: eine dauerhaft unlesbare Datei darf nicht bei JEDEM Reindex kosten.

⚠ AUF ECHT BEZAHLT (2026-09-06): `Anleitungen SAP.one` (46,5 MB) lief bei jedem
inkrementellen Reindex in den 120-Sekunden-Deckel von Tika, weil ein Fehlschlag
nirgends gemerkt wurde - und JEDE `knowledge_search` stoesst einen Reindex an.
Gemessen: 120,7 / 120,9 / 120,9 s je Suche; ein Chat-Auftrag mit vier Suchen
dauerte 496,8 Sekunden.

Gemessen wird die EIGENSCHAFT: der Extraktor wird fuer eine bekannt unlesbare,
unveraenderte Datei GAR NICHT MEHR AUFGERUFEN - nicht, dass irgendwo ein Cache
steht.
"""
import io
import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OK = FAIL = 0


def check(name, bed):
    global OK, FAIL
    print(("  \033[32m✓\033[0m " if bed else "  \033[31m✗\033[0m ") + name)
    if bed:
        OK += 1
    else:
        FAIL += 1


def sicher(fn, *a, **k):
    try:
        return fn(*a, **k)
    except Exception as e:                                     # noqa: BLE001
        return f"__WURF__ {type(e).__name__}: {e}"


REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QUELLE = io.open(os.path.join(REPO, "backend/tools/knowledge.py"), encoding="utf-8").read()

# ── Sandkasten: NIE in den echten Index schreiben ─────────────────────────
# ⚠ `backend.config` wird als STUB gestellt: der echte Import migriert Profile
# und schreibt die LIVE-settings.json zurueck (Register). Ausserdem fehlt in
# dieser Umgebung `dotenv` - der Test soll trotzdem ueberall laufen.
import types                                                    # noqa: E402

if "dotenv" not in sys.modules:
    _dv = types.ModuleType("dotenv")
    _dv.load_dotenv = lambda *a, **k: None
    sys.modules["dotenv"] = _dv
if "backend.config" not in sys.modules:
    _cfgmod = types.ModuleType("backend.config")

    class _Cfg:
        KNOWLEDGE_DIR = "/tmp/kb-test"
        MAX_FILE_SIZE_MB = 50
        def __getattr__(self, n):        # jedes weitere Feld: harmloser Wert
            return ""

    _cfgmod.config = _Cfg()
    sys.modules["backend.config"] = _cfgmod

_tmp = tempfile.mkdtemp(prefix="unlesbar_test_")
import backend.tools.knowledge as kn                            # noqa: E402

kn._unlesbar_pfad = lambda: Path(_tmp) / "unlesbar.json"
if not str(kn._unlesbar_pfad()).startswith(_tmp):
    print("ABBRUCH: Sandkasten greift nicht - der Test wuerde in den echten "
          "Index schreiben.")
    sys.exit(2)

print("\n\033[1m1. Der Cache merkt sich einen Fehlschlag\033[0m")
P = "/mnt/kb/riesig.one"
check("frisch: nichts gemerkt", kn._unlesbar_ueberspringen(P, 1000.0, 46_000_000) is None)
kn._unlesbar_merken(P, 1000.0, 46_000_000, "Zeitlimit von 120 s ueberschritten")
g = kn._unlesbar_ueberspringen(P, 1000.0, 46_000_000)
check("⚠ danach wird uebersprungen", g is not None)
check("und der GRUND steht dabei (nicht 'irgendwas ging schief')",
      isinstance(g, str) and "Zeitlimit" in g)

print("\n\033[1m2. Der Cache ist keine Sackgasse\033[0m")
check("⚠ geaenderte mtime -> neue Chance",
      kn._unlesbar_ueberspringen(P, 2000.0, 46_000_000) is None)
check("⚠ geaenderte Groesse -> neue Chance",
      kn._unlesbar_ueberspringen(P, 1000.0, 12_345) is None)
kn._unlesbar_vergessen(P)
check("nach einem Erfolg ist der Eintrag weg",
      kn._unlesbar_ueberspringen(P, 1000.0, 46_000_000) is None)

print("\n\033[1m3. Deckel und Robustheit\033[0m")
for i in range(2050):
    kn._unlesbar_merken(f"/x/{i}.one", 1.0, 1, "grund")
check("der Cache waechst nicht unbegrenzt", len(kn._unlesbar_laden()) <= 2000)
io.open(kn._unlesbar_pfad(), "w").write("{kaputt")
check("⚠ eine beschaedigte Datei wirft nicht (fail-open: wieder versuchen)",
      kn._unlesbar_ueberspringen(P, 1.0, 1) is None)
kn._unlesbar_speichern({})

print("\n\033[1m4. Der GRUND erreicht den Aufrufer\033[0m")
check("_letzter_extrakt_grund liefert '' fuer Unbekanntes",
      kn._letzter_extrakt_grund("/gibt/es/nicht.one") == "")
kn._merke_extrakt_grund("/a/b.one", "Zeitlimit von 120 s ueberschritten")
check("⚠ und den gemerkten Grund fuer eine bekannte Datei",
      "Zeitlimit" in kn._letzter_extrakt_grund("/a/b.one"))
# ⚠ ECHTE Dateien: `_unlesbar_grund` macht ZUERST stat() und antwortet bei
# einer nicht existierenden Datei "nicht lesbar" statt der Formataussage - der
# Fallstrick steht so im Register. Mit erfundenen Pfaden misst der Test den
# falschen Zweig.
_d1 = Path(_tmp) / "mit_grund.one"; _d1.write_bytes(b"x" * 100)
_d2 = Path(_tmp) / "ohne_grund.one"; _d2.write_bytes(b"x" * 100)
kn._merke_extrakt_grund(str(_d1), "Zeitlimit von 120 s ueberschritten")
check("_unlesbar_grund nimmt ihn (statt zu raten)",
      "Zeitlimit" in str(sicher(kn._unlesbar_grund, _d1, 10**9)))
check("⚠ ohne gemerkten Grund bleibt der bisherige Text (kein Rueckschritt)",
      "OneNote" in str(sicher(kn._unlesbar_grund, _d2, 10**9)))
# ⚠ OHNE KOMMENTARE: der Hinweis, dass es `_failure_reason` nie gab, nennt den
# Namen selbst - der Waechter laese sonst seine eigene Begruendung (Register).
import tokenize as _tk, io as _io2                              # noqa: E402
def _ohne_kommentare(q):
    out, letzte = [], (1, 0)
    for tok in _tk.generate_tokens(_io2.StringIO(q).readline):
        if tok.type == _tk.COMMENT:
            continue
        out.append(tok.string if tok.type != _tk.STRING else '""')
    return " ".join(out)
_qk = sicher(_ohne_kommentare, QUELLE)
check("Positivkontrolle: der Kommentar-Filter hat gearbeitet",
      isinstance(_qk, str) and "_unlesbar_merken" in _qk
      and "Der Kommentar in" not in _qk)
check("der tote Verweis auf _failure_reason ist weg (im CODE)",
      isinstance(_qk, str) and "_failure_reason" not in _qk)
# ⚠ DIE VERDRAHTUNG, nicht nur die Funktion: `_merke_extrakt_grund` direkt zu
# rufen beweist nichts darueber, ob der Extraktor sie auch benutzt. Ohne diese
# Pruefung blieb die Gegenprobe "echter Grund wird nicht gemerkt" gruen.
import ast as _ast2                                             # noqa: E402
# ⚠ NICHT die Funktion RATEN: der OneNote-Zweig liegt in `_extract_text_rest`,
# nicht in `_extract_text_raw` - der erste Anlauf schnitt die falsche und
# meldete einen Fehler, den es nicht gab. Gesucht wird die Funktion, die
# `text_aus_datei` WIRKLICH aufruft.
_qr = ""
for _n in _ast2.walk(_ast2.parse(QUELLE)):
    if isinstance(_n, (_ast2.FunctionDef, _ast2.AsyncFunctionDef)):
        _seg = _ast2.get_source_segment(QUELLE, _n) or ""
        if "text_aus_datei(" in _seg:
            _qr = _seg
            break
check("Positivkontrolle: der OneNote-Extraktionszweig wurde gefunden",
      "text_aus_datei" in _qr)
check("⚠ der OneNote-Zweig MERKT den Grund (sonst geht er verloren)",
      "_merke_extrakt_grund(" in _qr)

print("\n\033[1m5. DIE EIGENSCHAFT: der Extraktor wird nicht mehr gerufen\033[0m")
# ⚠ Das ist die Pruefung, auf die es ankommt. Ein Cache, der zwar steht, aber
# im Reindex nicht abgefragt wird, kostet die 120 s trotzdem.
import ast                                                      # noqa: E402
_b = ast.parse(QUELLE)
_fn = next((n for n in ast.walk(_b) if isinstance(n, ast.FunctionDef)
            and n.name == "_rebuild_vector_index"), None)
_q = ast.get_source_segment(QUELLE, _fn) if _fn else ""
check("_rebuild_vector_index gefunden", bool(_q))
i_skip = _q.find("_unlesbar_ueberspringen")
i_extr = _q.find("_extract_text(")
check("⚠ die Cache-Abfrage steht VOR der Extraktion",
      0 <= i_skip < i_extr)
check("und sie ueberspringt wirklich (continue)",
      "continue" in _q[i_skip:i_skip + 400])
check("ein Fehlschlag wird gemerkt", "_unlesbar_merken" in _q)
check("ein Erfolg raeumt den Eintrag weg", "_unlesbar_vergessen" in _q)

print(f"\n\033[1mErgebnis: {OK} OK, {FAIL} FAIL\033[0m")
import shutil                                                   # noqa: E402
shutil.rmtree(_tmp, ignore_errors=True)
sys.exit(1 if FAIL else 0)
