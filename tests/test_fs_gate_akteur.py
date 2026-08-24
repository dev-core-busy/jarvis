#!/usr/bin/env python3
"""Die Pfad-Freigaben im Dispatch muessen den AKTEUR kennen (Vorfall 2026-08-24).

DER VORFALL: Eine Benutzerin haengte auf ECHT eine Excel-Datei an den Chat und
bekam "Zugriff verweigert: dieser Anhang gehoert einem anderen Benutzer" – auf
IHRE EIGENE Datei. Im Journal:

    [AGENT] BLOCKED xlsx_inspect path='/tmp/jarvis-anhaenge/97877cae/anhang_...'
            fuer 'claudia.schmitt': dieser Anhang gehoert einem anderen Benutzer

``97877cae`` IST die Kennung von ``claudia.schmitt`` – die Datei lag also genau
richtig.

DIE URSACHE IST EINE REIHENFOLGE: ``_execute_tool`` prueft die Pfade
(``filesystem``, ``create_chart(source.file)``, ``pfad_parameter``) VOR dem
``set_tool_user``. ``sandbox.authorize_fs`` las den Benutzer aber aus genau
diesem ContextVar – dort stand also der Vorgabewert ``""``.

Das schlug in BEIDE Richtungen aus, und das ist der eigentliche Befund:

  * ``gehoert_anhang(pfad, "")`` vergleicht gegen eine LEERE Kennung und ist
    fail-closed -> jeder Benutzer wurde von seiner eigenen Arbeitskopie
    abgewiesen. Seit dem /tmp-Umbau (2026-08-23) waren damit xlsx_inspect,
    xlsx_read_range, xlsx_merge, xlsx_edit, pdf_formular_extrakt, create_chart
    (source.file) und filesystem auf JEDEN Chat-Anhang eines Netzwerk-Benutzers
    tot.
  * ``may_see_document(name, "")`` liest leer dagegen als "keine
    Einschraenkung" -> die Eigentuemer-Schranke fuer ``data/documents`` wurde an
    dieser Stelle GAR NICHT durchgesetzt. Dieser Teil ist aelter (seit
    2026-07-28) und hing nur nie an einem sichtbaren Symptom.

DIE LEHRE, die dieser Test durchsetzt: eine harte Schranke darf nicht davon
abhaengen, WANN sie aufgerufen wird. Der Akteur wird uebergeben, nicht aus der
Umgebung gelesen.

Laeuft ohne fastapi: ``backend.sandbox``/``backend.lauf_tmp`` werden wirklich
ausgefuehrt, ``backend/agent.py`` nur per ``ast`` gelesen.

KEIN Dateisystem-Zugriff noetig – alle geprueften Funktionen arbeiten rein auf
Pfaden (``Path.resolve()`` braucht die Datei nicht). Deshalb gibt es hier auch
keinen Sandkasten-Waechter: der Test kann nichts anlegen und nichts loeschen.
"""
import ast
import pathlib
import sys

WURZEL = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

from backend import lauf_tmp as lt          # noqa: E402
from backend import sandbox as sbx          # noqa: E402

OK = FAIL = 0


def pruefe(bedingung, text, zusatz=""):
    global OK, FAIL
    if bedingung:
        OK += 1
        print(f"  OK   {text}")
    else:
        FAIL += 1
        print(f"  FAIL {text}" + (f" – {zusatz}" if zusatz else ""))


def frei(action, pfad, benutzer=...):
    """``authorize_fs``, das NIE wirft.

    Ohne diese Kapsel bricht die GEGENPROBE mit einem ``TypeError`` ab (der alte
    Stand kennt ``username`` nicht) – und ein abgebrochener Lauf ist von einem
    bestandenen nicht zu unterscheiden. Genau diese Falle steht im Register.
    """
    try:
        if benutzer is ...:
            return sbx.authorize_fs(action, str(pfad))
        return sbx.authorize_fs(action, str(pfad), username=benutzer)
    except TypeError as e:
        return None, f"AUFRUF NICHT MOEGLICH: {e}"


# Der gemeldete Fall, woertlich.
BEN = "claudia.schmitt"
FREMD = "claudia.schweihofer"
DATEI = "anhang_0f36e76b73c7_Mühlhausen_Tennstedt_Lübeck_Hämatopathologie_Pflege24082026.xlsx"


print("\n=== 1. Kennung: eine Person, eine Kennung ===")
k = lt.benutzer_kennung(BEN)
pruefe(k == "97877cae", f"Kennung von {BEN!r} ist 97877cae (die aus dem Journal)", k)
for schreibweise in (f"nexus\\{BEN}", f"{BEN}@nexus.int", BEN.upper()):
    pruefe(lt.benutzer_kennung(schreibweise) == k,
           f"gleiche Kennung fuer {schreibweise!r}")
pruefe(lt.benutzer_kennung(FREMD) != k, "ein anderer Benutzer bekommt eine andere Kennung")
pruefe(lt.benutzer_kennung("") == "", "leerer Benutzer hat KEINE Kennung (Ursache des Vorfalls)")


print("\n=== 2. Zugehoerigkeit: eigen ja, fremd nein, leer nein ===")
eigen_anh = lt.ANH_ROOT / k / DATEI
fremd_anh = lt.ANH_ROOT / lt.benutzer_kennung(FREMD) / DATEI
eigen_arb = lt.ARBEIT_ROOT / k / "ergebnis.xlsx"
fremd_arb = lt.ARBEIT_ROOT / lt.benutzer_kennung(FREMD) / "ergebnis.xlsx"

pruefe(lt.gehoert_anhang(eigen_anh, BEN) is True, "eigener Anhang gehoert mir")
pruefe(lt.gehoert_anhang(fremd_anh, BEN) is False, "fremder Anhang gehoert mir nicht")
pruefe(lt.gehoert_anhang(eigen_anh, "") is False,
       "OHNE Benutzer gilt auch die eigene Datei als fremd (das war der Vorfall)")
pruefe(lt.gehoert_anhang("/tmp/irgendwas.xlsx", BEN) is None,
       "ausserhalb der Anhang-Wurzel stellt sich die Frage nicht")
pruefe(lt.gehoert_arbeitsbereich(eigen_arb, BEN) is True, "eigener Arbeitsbereich gehoert mir")
pruefe(lt.gehoert_arbeitsbereich(fremd_arb, BEN) is False, "fremder Arbeitsbereich nicht")


print("\n=== 3. authorize_fs MIT Akteur – der gemeldete Aufruf ===")
ok, warum = frei("read", eigen_anh, BEN)
pruefe(ok, "eigener Anhang ist lesbar", warum)
ok, warum = frei("exists", eigen_anh, BEN)
pruefe(ok, "exists auf den eigenen Anhang geht", warum)
ok, warum = frei("read", eigen_arb, BEN)
pruefe(ok, "eigene Ergebnisdatei ist lesbar", warum)

# Positivkontrolle in die Gegenrichtung: die Schranke muss weiter beissen.
ok, warum = frei("read", fremd_anh, BEN)
pruefe(not ok and "anderen Benutzer" in warum, "fremder Anhang bleibt gesperrt", warum)
ok, warum = frei("read", fremd_arb, BEN)
pruefe(not ok and "anderen Benutzer" in warum, "fremde Ergebnisdatei bleibt gesperrt", warum)


print("\n=== 4. Der Rueckfall auf den ContextVar bleibt fail-closed ===")
# Aus einem WERKZEUG heraus ist der ContextVar gesetzt; ohne ihn darf nichts
# durchrutschen. Der Dispatch benutzt diesen Weg nach dem Fix nicht mehr
# (Abschnitt 5), die Eigenschaft muss aber erhalten bleiben.
ok, _ = frei("read", eigen_anh)
pruefe(not ok, "ohne gesetzten ContextVar wird der Anhang abgewiesen (fail-closed)")
tok = sbx.set_tool_user(BEN)
try:
    ok, warum = frei("read", eigen_anh)
    pruefe(ok, "mit gesetztem ContextVar ist derselbe Pfad erlaubt", warum)
finally:
    sbx.reset_tool_user(tok)


print("\n=== 5. Eigentuemer-Schranke in data/documents greift JETZT im Dispatch ===")
from backend import documents as _docs                      # noqa: E402
_echt = _docs.may_access
_docs.may_access = lambda name, user, is_admin=False: user == BEN   # Attrappe
try:
    doc = sbx.DOCS_ROOT / ("a" * 32 + "__Angebot.xlsx")
    ok, _ = frei("read", doc, BEN)
    pruefe(ok, "eigenes Dokument lesbar")
    ok, warum = frei("read", doc, FREMD)
    pruefe(not ok and "anderen Benutzer" in warum,
           "fremdes Dokument gesperrt – vorher liess der Dispatch es durch", warum)
    ok, _ = frei("read", doc, "")
    pruefe(ok, "leerer Benutzer = privilegiert = keine Einschraenkung (unveraendert)")
finally:
    _docs.may_access = _echt


print("\n=== 6. WAECHTER: jede Freigabe im Dispatch uebergibt den Akteur ===")
quelle = (WURZEL / "backend" / "agent.py").read_text(encoding="utf-8")
baum = ast.parse(quelle)
fn = next((n for n in ast.walk(baum)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_execute_tool"), None)
pruefe(fn is not None, "_execute_tool gefunden")

aufrufe = [n for n in ast.walk(fn)
           if isinstance(n, ast.Call)
           and getattr(n.func, "attr", getattr(n.func, "id", "")) == "authorize_fs"]
pruefe(len(aufrufe) == 3, f"drei Pfad-Freigaben im Dispatch (gefunden: {len(aufrufe)})")
ohne = [c.lineno for c in aufrufe if not any(kw.arg == "username" for kw in c.keywords)]
pruefe(not ohne,
       "JEDE davon uebergibt username=",
       f"ohne Akteur in Zeile(n) {ohne} – dort gilt wieder der leere Vorgabewert")

# Der Akteur wird wie bei set_tool_user abgeleitet: nie der leere String.
pruefe("_fs_akteur = _uname or _ANON_ACTOR" in quelle,
       "der Akteur faellt auf den Platzhalter zurueck, nicht auf ''")

setzt = [n.lineno for n in ast.walk(fn)
         if isinstance(n, ast.Call)
         and getattr(n.func, "attr", getattr(n.func, "id", "")) == "set_tool_user"]
spaeter = [c.lineno for c in aufrufe if setzt and c.lineno < setzt[0]]
pruefe(bool(spaeter),
       "die Freigaben laufen weiterhin VOR set_tool_user – genau deshalb ist der "
       "Parameter Pflicht und keine Kosmetik")

print("\n=== 7. WAECHTER: authorize_fs liest den Benutzer nicht mehr direkt ===")
sq = (WURZEL / "backend" / "sandbox.py").read_text(encoding="utf-8")
_sb = ast.parse(sq)
_fn = next(n for n in ast.walk(_sb)
           if isinstance(n, ast.FunctionDef) and n.name == "authorize_fs")
# OHNE Docstring auswerten – sonst liest der Waechter seine eigene Begruendung
# und meldet drei "tool_user()", von denen zwei nur Prosa sind. Genau diese
# Falle steht im Register; sie hat hier beim ersten Lauf zugeschlagen.
_zeilen = sq.splitlines()
_ab = _fn.body[0].end_lineno if (_fn.body and isinstance(_fn.body[0], ast.Expr)
                                 and isinstance(_fn.body[0].value, ast.Constant)) else _fn.lineno
rumpf = "\n".join(_zeilen[_ab:_fn.end_lineno])
pruefe("tool_user() if username is None else username" in rumpf,
       "genau eine Stelle loest den Benutzer auf")
pruefe(rumpf.count("tool_user()") == 1,
       "danach wird tool_user() nicht noch einmal gelesen",
       f"{rumpf.count('tool_user()')} Vorkommen")
for f in ("may_see_document(rp.name, benutzer)",
          "gehoert_anhang(rp, benutzer)",
          "gehoert_arbeitsbereich(rp, benutzer)"):
    pruefe(f in rumpf, f"{f.split('(')[0]} bekommt den aufgeloesten Benutzer")


print("\n=== 8. office_read/office_to_pdf liefen an der Freigabe VORBEI ===")
# Sie deklarieren kein `pfad_parameter` und werden deshalb vom Dispatch nicht
# geprueft. Die Schranke muss dort greifen, wo der Pfad feststeht: in
# `_resolve_existing`/`_sichtbar` des Office-Skills.
import skills.office.main as _off                            # noqa: E402

tok = sbx.set_tool_user(BEN)
try:
    pruefe(_off._sichtbar(eigen_anh) is not None, "eigener Anhang bleibt sichtbar")
    pruefe(_off._sichtbar(fremd_anh) is None,
           "FREMDER Anhang ist fuer office_read nicht mehr erreichbar")
    pruefe(_off._sichtbar(fremd_arb) is None,
           "FREMDE Ergebnisdatei ist fuer office_to_pdf nicht mehr erreichbar")
    pruefe(_off._sichtbar(pathlib.Path("/etc/passwd")) is None,
           "System-Pfade sind fuer den Office-Skill gesperrt")
finally:
    sbx.reset_tool_user(tok)

# Privilegierte Laeufe haben absichtlich KEINEN Benutzerbezug – ihre eigenen
# Anhaenge liegen ebenfalls unter ANH_ROOT und muessen lesbar bleiben.
pruefe(_off._sichtbar(eigen_anh) is not None,
       "ohne Benutzerbezug (privilegiert) bleibt alles wie bisher erreichbar")

_q = (WURZEL / "skills" / "office" / "main.py").read_text(encoding="utf-8")
_sf = _q[_q.index("def _sichtbar("):]
_sf = _sf[:_sf.index("\ndef ", 1)]
pruefe("authorize_fs(" in _sf, "_sichtbar ruft die volle Freigabe auf")
pruefe("if benutzer:" in _sf,
       "nur fuer einen BEKANNTEN Benutzer – leer heisst wie ueberall 'keine Schranke'")


print("\n=== 9. Blosser Dateiname darf nicht am Gate sterben ===")
# Gemeldet: xlsx_edit path='Monatsumsätze_2026.xlsx' -> "Lesen ist nur in den
# Wissens-/Arbeitsverzeichnissen erlaubt". Der rohe Name loest gegen das
# Arbeitsverzeichnis des Dienstes auf; gemeint war eine Datei in data/documents.
ok, warum = frei("read", "Monatsumsätze_2026.xlsx", BEN)
pruefe(ok is False, "der ROHE Name ist tatsaechlich nicht freigegeben (Ursache)", str(warum))

_schleife = quelle[quelle.index('for _pf in getattr(self.tools_map.get(name), "pfad_parameter"'):]
_schleife = _schleife[:2000]
pruefe('if "/" not in _pv' in _schleife,
       "der Dispatch ueberspringt Werte ohne Pfadtrenner")
pruefe("_resolve_existing" in _schleife,
       "und begruendet es mit der Aufloesung im Werkzeug")


print("\n" + "=" * 62)
print(f"  {OK} OK, {FAIL} FAIL")
print("=" * 62)
sys.exit(1 if FAIL else 0)
