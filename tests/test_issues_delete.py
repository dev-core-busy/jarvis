#!/usr/bin/env python3
"""Waechter: Meldungen (Issues) duerfen ADMINISTRATOREN loeschen.

Vorher konnte das nur der lokale Benutzer ``jarvis`` – ein Administrator sah den
Knopf nicht einmal, weil die Oberflaeche ihn allein an ``can_delete`` haengt.

Zwei Dinge werden hier gemessen, nicht gelesen:
 1. die RECHTE-MATRIX von ``can_delete``/``delete_issue`` gegen echte Dateien im
    Sandkasten (Autor, Fremder, Administrator, ``jarvis``),
 2. die VERDRAHTUNG – dass ``main.py`` ``is_admin`` wirklich beisteuert. Ohne
    das bliebe die Erweiterung wirkungslos: das Modul kennt die Rechtelage
    nicht selbst und wuerde fail-closed weiter verweigern.
"""
from __future__ import annotations

import re
import sys
import tempfile
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

_ok = _fail = 0


def check(bed, text, extra=""):
    global _ok, _fail
    if bed:
        _ok += 1
        print("  OK   " + text)
    else:
        _fail += 1
        print("  FAIL " + text + (" – " + str(extra) if extra else ""))


def section(t):
    print("\n═══ " + t)


# ── backend.config als STUB ─────────────────────────────────────────────────
# Der echte Import migriert Profile und schreibt die Live-settings.json zurueck
# (Register). Ein Waechter darf den Betrieb nicht anfassen.
_cfg = types.ModuleType("backend.config")
_SANDKASTEN = Path(tempfile.mkdtemp(prefix="jarvis_issues_"))


class _Config:
    _data_dir = _SANDKASTEN

    def get_setting(self, k, d=None):
        return d


_cfg.config = _Config()
_cfg.PROJECT_ROOT = ROOT
sys.modules["backend.config"] = _cfg

from backend import issues as iss  # noqa: E402

# SANDKASTEN-WAECHTER, Exit 2. "Konnte nicht laufen" muss von "bestanden"
# unterscheidbar sein – und ein Test, der die echte data/issues.json leert,
# loescht Meldungen aus dem Betrieb.
for name in ("ISSUES_FILE", "ADMIN_SEEN_FILE", "ATTACH_DIR"):
    p = Path(getattr(iss, name))
    if not str(p).startswith(str(_SANDKASTEN)):
        print("ABBRUCH: Sandkasten verfehlt – %s zeigt auf %s" % (name, p))
        sys.exit(2)


def _neu(autor="max.muster", titel="Drucker geht nicht"):
    it, err = iss.create_issue(autor, {"title": titel, "type": "bug",
                                       "body": "Er druckt nicht."})
    assert it, err
    return it


# ═══════════════════════════════════════════════════════════════════════════
section("1) Wer darf loeschen – die Matrix")
# ═══════════════════════════════════════════════════════════════════════════
it = _neu()
check(iss.can_delete(it, "nexus\\chefin", is_admin=True) is True,
      "ein Administrator darf loeschen")
check(iss.can_delete(it, "jarvis") is True,
      "der lokale 'jarvis' darf es weiterhin – ohne is_admin")
check(iss.can_delete(it, "max.muster", is_admin=False) is False,
      "der AUTOR allein darf es nicht")
check(iss.can_delete(it, "wer.anders", is_admin=False) is False,
      "ein Fremder erst recht nicht")

# FAIL-CLOSED: das Argument ist optional, und die Vorgabe ist die enge Antwort.
# Ein Aufrufer, der es vergisst, bekommt keine stille Rechteerweiterung.
check(iss.can_delete(it, "nexus\\chefin") is False,
      "ohne is_admin gilt weiter das enge Verhalten (fail-closed)")

# Wahrheitswerte, die keine sind: aus einer handgeschriebenen Konfiguration
# oder einem JSON-Feld kann alles kommen.
check(iss.can_delete(it, "wer.anders", is_admin="") is False,
      "ein leerer Wert ist kein Ja")


# ═══════════════════════════════════════════════════════════════════════════
section("2) Loeschen wirkt WIRKLICH – gegen echte Dateien")
# ═══════════════════════════════════════════════════════════════════════════
it = _neu()
ok, err = iss.delete_issue("wer.anders", it["id"], is_admin=False)
check(ok is False and "Berechtigung" in err,
      "ohne Recht: Absage mit dem Wort, aus dem der Endpunkt 403 macht", err)
check(iss.get_issue(it["id"]) is not None,
      "und die Meldung steht noch da (die Absage war keine Fassade)")

# Ein Anhang muss mitgehen – sonst bleibt eine verwaiste Datei liegen, und
# genau die kann der Grund fuer das Loeschen gewesen sein.
gespeichert, err = iss.add_attachment("max.muster", it["id"], "beleg.txt",
                                      b"vertraulich")
check(bool(gespeichert), "Anhang angelegt", err)
att = iss._attach_dir(it["id"])
check(att.exists() and any(att.iterdir()), "der Anhang liegt auf Platte")

ok, err = iss.delete_issue("nexus\\chefin", it["id"], is_admin=True)
check(ok is True, "als Administrator geht es", err)
check(iss.get_issue(it["id"]) is None, "die Meldung ist weg")
check(not att.exists(), "und der Anhang-Ordner ebenfalls")

# Unbekannt bleibt unbekannt – und das ist ein ANDERER Fall als "kein Recht".
ok, err = iss.delete_issue("nexus\\chefin", "gibtsnicht", is_admin=True)
check(ok is False and "nicht gefunden" in err,
      "unbekannte Kennung: 'nicht gefunden', nicht 'keine Berechtigung'", err)

# Fremde Meldungen bleiben unberuehrt.
a, b = _neu("alice", "Meldung A"), _neu("bob", "Meldung B")
iss.delete_issue("chef", a["id"], is_admin=True)
check(iss.get_issue(b["id"]) is not None, "nur die gewaehlte Meldung faellt weg")


# ═══════════════════════════════════════════════════════════════════════════
section("3) 'editieren' bleibt eng – Loeschen ist nicht Umschreiben")
# ═══════════════════════════════════════════════════════════════════════════
# Ein Administrator darf aufraeumen und den Loesungsbereich pflegen. Den TEXT
# einer fremden Meldung umschreiben darf er NICHT: "editieren" und "bearbeiten"
# sind in dieser Oberflaeche zwei verschiedene Dinge.
fremd = _neu("alice", "Alices Meldung")
check(iss.can_edit(fremd, "nexus\\chefin") is False,
      "can_edit wurde NICHT mit erweitert")
check(iss.can_edit(fremd, "alice") is True, "die Autorin darf ihren Text ändern")
check(iss.can_edit(fremd, "jarvis") is True, "und 'jarvis' weiterhin alles")


# ═══════════════════════════════════════════════════════════════════════════
section("4) Verdrahtung: main.py steuert is_admin bei")
# ═══════════════════════════════════════════════════════════════════════════
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")


def funktion(quelle: str, name: str) -> str:
    """Der Rumpf EINER Route – per Quelltext geschnitten, aber nicht zu weit.

    Ein Schnitt „bis zum naechsten @app." wuerde fremde Endpunkte mitlesen und
    die Pruefung trivial wahr machen (im Projekt bezahlt).
    """
    m = re.search(r"\nasync def %s\(" % re.escape(name), quelle)
    if not m:
        return ""
    rest = quelle[m.start() + 1:]
    ende = re.search(r"\n@app\.", rest)
    return rest[:ende.start()] if ende else rest


_del = funktion(MAIN, "api_issues_delete")
check(bool(_del), "der Loesch-Endpunkt existiert (sonst prueft nichts darunter)")
check("_is_admin_user(user)" in _del,
      "er ermittelt den Administrator-Status")
check("is_admin=" in _del, "und reicht ihn an das Modul weiter")
check('"Berechtigung" in err' in _del,
      "die Absage wird zu 403 – nicht zu 404")

_get = funktion(MAIN, "api_issues_get")
check("can_delete(issue, user, _is_admin_user(user))" in _get,
      "auch die Einzelabfrage meldet das Recht mit is_admin")

# ⚠ DIE OBERFLAECHE ZEIGT DEN KNOPF ALLEIN AN can_delete. Meldet die
# Einzelabfrage das Recht nicht, bleibt der Knopf unsichtbar – und der Fix
# waere unbemerkt wirkungslos, obwohl der Endpunkt loeschen wuerde.
JS = (ROOT / "frontend" / "js" / "issues.js").read_text(encoding="utf-8")
check("data.can_delete" in JS, "das Fenster liest can_delete vom Server")
check(re.search(r"if \(canDelete\)[\s\S]{0,200}jv-iss-del-btn", JS) is not None,
      "und zeichnet den Loeschknopf danach")
check("method: 'DELETE'" in JS, "der Knopf ruft wirklich DELETE")

# Das Modul darf die Rechtefrage nicht doppelt beantworten: die Schranke sitzt
# in can_delete, damit sie ein zweiter Aufrufer nicht umgehen kann.
QUELLE = (ROOT / "backend" / "issues.py").read_text(encoding="utf-8")
_dq = re.search(r"def delete_issue\([\s\S]*?\n\n\n", QUELLE).group(0)
check("can_delete(" in _dq, "delete_issue fragt can_delete")
check("is_jarvis(" not in _dq,
      "und beantwortet die Rechtefrage NICHT selbst noch einmal")

# Der Modul-Docstring darf nicht das Gegenteil des Codes behaupten – diese
# Fehlerklasse hat im Projekt mehrfach Stunden gekostet.
kopf = QUELLE[:QUELLE.index('"""', 3) + 3]
check("Loeschen: alle Administratoren" in kopf,
      "der Docstring nennt die neue Regel")
check("editieren/loeschen: nur Benutzer" not in kopf,
      "und behauptet nicht mehr die alte")


section("5) Muelleimer an der Listenzeile")
# Der Loeschknopf sass nur in der Detailansicht: wer aufraeumen wollte, musste
# jede Meldung erst oeffnen. Der Muelleimer an der Zeile ist der kurze Weg –
# und er darf das Recht NICHT selbst herleiten.
_list = funktion(MAIN, "api_issues_list")
check("can_delete(i, user, ist_admin)" in _list,
      "die Liste laesst das MODUL entscheiden, je Eintrag")
# ⚠ KEIN .index() in einer Pruefung – das WIRFT statt fehlzuschlagen, und die
# Gegenprobe braeche dann ab, statt zu zaehlen (Register).
_pos_r = _list.find("rechte = [")
_pos_m = _list.find("_mit_anzeigenamen(issues)")
check(_pos_r >= 0 and _pos_m >= 0 and _pos_r < _pos_m,
      "gerechnet wird auf den Originalen, nicht auf den Anzeige-Kopien",
      "sonst geht eine kuenftige Autor-Regel am Domaenen-Praefix fehl")
check("_is_admin_user" in _list, "und der Administrator-Status kommt aus main.py")

check("i.can_delete" in JS, "die Zeile zeichnet den Muelleimer nur bei can_delete")
check("JarvisIcons.trash()" in JS, "und zwar als Muelleimer, nicht als ×")

# Der Knopf liegt IN der klickbaren Zeile. Ohne stopPropagation oeffnet
# derselbe Klick zusaetzlich das Detail (Register: Klick-Ausnahme).
_delbtn = JS[JS.index(".jv-iss-item-del').forEach"):] if ".jv-iss-item-del').forEach" in JS else ""
check(bool(_delbtn), "der Handler fuer den Zeilen-Muelleimer existiert")
check("stopPropagation()" in _delbtn[:900],
      "er stoppt den Klick, sonst oeffnet sich zugleich die Detailansicht")
check("method: 'DELETE'" in _delbtn[:900], "und ruft wirklich DELETE")

# Nach dem Loeschen darf der Filter NICHT auf die Vorgabe 'offen'
# zurueckspringen – beim Aufraeumen steht er auf 'geschlossen'.
check("_listIssues = _listIssues.filter" in _delbtn[:1200],
      "der Eintrag wird aus dem Bestand genommen")
check("_applyFilter()" in _delbtn[:1200] and "_showList()" not in _delbtn[:1200],
      "und nur neu gefiltert – die gewaehlte Ansicht bleibt stehen")
check("let filtered = _listIssues;" in JS,
      "der Filter liest den Bestand, sonst zeichnet er den Eintrag wieder mit")

# Fremdtext in der Zeile bleibt maskiert (der Titel kommt von einem Melder).
check('data-del="${_escape(i.id)}"' in JS, "die Id im Knopf ist maskiert")

# i18n: kein hart verdrahteter Text mehr an einem Loeschweg.
I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
for key in ("issues.delete", "issues.delete_confirm", "issues.delete_error"):
    check(I18N.count("'%s'" % key) == 2, "%s ist in DE und EN hinterlegt" % key)
check("Issue wirklich loeschen?" not in JS,
      "die Rueckfrage haengt nicht mehr als deutscher Klartext im Code")

print("\n%d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
