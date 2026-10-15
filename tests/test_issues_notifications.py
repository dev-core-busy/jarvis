#!/usr/bin/env python3
"""Waechter: die Eintraege HINTER dem Benachrichtigungs-Badge.

Der Badge sagte nur eine Zahl. Fuer den Mouseover liefert `unseen_details()`
jetzt die Eintraege dazu – und `unseen_count()` ist nur noch ein `len()`
darauf.

DAS IST DER KERN DIESES WAECHTERS: Zaehler und Liste duerfen nicht
auseinanderlaufen. Eine zweite, „schnellere" Zaehlschleife neben der Liste
waere eine zweite Fassung derselben Regel; der Badge stuende dann auf 3 und
das Panel zeigte 2, ohne dass jemand sagen koennte, welche Zahl stimmt.
Geprueft wird deshalb die EIGENSCHAFT (count == len(details)) ueber alle
Faelle, nicht ein einzelnes Beispiel.
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


# ── backend.config als STUB (Register: der echte Import schreibt die
#    Live-settings.json zurueck) ──────────────────────────────────────────────
_cfg = types.ModuleType("backend.config")
_SANDKASTEN = Path(tempfile.mkdtemp(prefix="jarvis_notif_"))


class _Config:
    _data_dir = _SANDKASTEN

    def get_setting(self, k, d=None):
        return d


_cfg.config = _Config()
_cfg.PROJECT_ROOT = ROOT
sys.modules["backend.config"] = _cfg

from backend import issues as iss  # noqa: E402

# SANDKASTEN-WAECHTER, Exit 2 – "konnte nicht laufen" muss von "bestanden"
# unterscheidbar sein, und ein Test, der die echte data/issues.json anfasst,
# loescht Meldungen aus dem Betrieb.
for name in ("ISSUES_FILE", "ADMIN_SEEN_FILE", "ATTACH_DIR"):
    p = Path(getattr(iss, name))
    if not str(p).startswith(str(_SANDKASTEN)):
        print("ABBRUCH: Sandkasten verfehlt – %s zeigt auf %s" % (name, p))
        sys.exit(2)


def leeren():
    """Bestand zuruecksetzen – jeder Abschnitt startet auf gruener Wiese."""
    iss._save_all([])
    iss._save_admin_seen({})


def neu(autor, titel="Meldung"):
    it, err = iss.create_issue(autor, {"title": titel, "type": "bug", "body": "x"})
    assert it, err
    return it


# ═══════════════════════════════════════════════════════════════════════════
section("1) Eigene Meldung wurde bearbeitet → ein Eintrag mit Inhalt")
# ═══════════════════════════════════════════════════════════════════════════
leeren()
a = neu("alice", "Drucker geht nicht")
iss.mark_seen("alice")                       # Ausgangsstand: alles gesehen
check(iss.unseen_count("alice") == 0, "vorher nichts offen")

iss.update_issue("chef", a["id"], {"status": "in_progress",
                                   "jarvis_comment": "Wir kuemmern uns."},
                 is_admin=True)
d = iss.unseen_details("alice")
check(len(d) == 1, "eine Benachrichtigung", d)
e = d[0] if d else {}
check(e.get("kind") == "edited", "Art 'edited'", e.get("kind"))
check(e.get("id") == a["id"], "mit der Kennung der Meldung")
check(e.get("title") == "Drucker geht nicht", "und ihrem Titel")
check(e.get("status") == "in_progress", "der neue Status steht drin")
check(e.get("comment") == "Wir kuemmern uns.",
      "und der Admin-Kommentar – ER ist die Nachricht an den Melder", e.get("comment"))
check("author" not in e,
      "bei der EIGENEN Meldung steht kein Melder dabei (das waere man selbst)")

# Der Fremde sieht davon nichts.
check(iss.unseen_details("bob") == [], "ein Fremder bekommt keine Benachrichtigung")

# Ein langer Kommentar wird gekuerzt – die Liste darf nicht zerlaufen.
lang = "W" * (iss.NOTIF_COMMENT_LEN + 80)
iss.update_issue("chef", a["id"], {"jarvis_comment": lang}, is_admin=True)
e = iss.unseen_details("alice")[0]
check(len(e["comment"]) <= iss.NOTIF_COMMENT_LEN + 1,
      "langer Kommentar gekuerzt", len(e["comment"]))
check(e["comment"].endswith("…"), "und die Kuerzung ist SICHTBAR, nicht still")


# ═══════════════════════════════════════════════════════════════════════════
section("2) Administrator: neue Meldungen anderer")
# ═══════════════════════════════════════════════════════════════════════════
leeren()
neu("alice", "Alt und bekannt")
# Lazy-Init: der erste Blick setzt die Marke, meldet den Bestand aber NICHT
# nachtraeglich als neu.
check(iss.unseen_details("chef", is_admin=True) == [],
      "der erste Abruf meldet den Bestand NICHT als neu (Lazy-Init)")
check(iss._load_admin_seen().get("chef"),
      "und hat die Marke gesetzt – die Nebenwirkung ist erhalten geblieben")

b = neu("bob", "Neue Meldung von Bob")
d = iss.unseen_details("chef", is_admin=True)
check(len(d) == 1, "danach meldet sich genau die neue", [x.get("title") for x in d])
check(d and d[0].get("kind") == "new", "Art 'new'")
check(d and d[0].get("author") == "bob",
      "mit dem Melder – ohne ihn ist 'neue Meldung' keine Information")
check(d and d[0].get("id") == b["id"], "und der richtigen Kennung")

check(iss.unseen_details("chef", is_admin=False) == [],
      "OHNE Adminrecht bleibt die Liste leer (dieselbe Schranke wie beim Zaehler)")
check(iss.unseen_details("bob", is_admin=True) == [],
      "und die EIGENE neue Meldung meldet sich einem nicht selbst")


# ═══════════════════════════════════════════════════════════════════════════
section("3) Zaehler und Liste koennen NICHT auseinanderlaufen")
# ═══════════════════════════════════════════════════════════════════════════
# Nicht an einem Beispiel, sondern ueber eine Reihe von Zustaenden – genau die
# Drift ist der Fehler, den dieses Modul strukturell ausschliessen soll.
leeren()
faelle = []
alice1 = neu("alice", "A1")
alice2 = neu("alice", "A2")
iss.mark_seen("alice")
iss.unseen_details("chef", is_admin=True)                  # Marke setzen
faelle.append(("Ausgangsstand", "alice", False))

iss.update_issue("chef", alice1["id"], {"status": "closed"}, is_admin=True)
faelle.append(("eine bearbeitet", "alice", False))
iss.update_issue("chef", alice2["id"], {"jarvis_comment": "Antwort"}, is_admin=True)
faelle.append(("zwei bearbeitet", "alice", False))
neu("bob", "B1")
neu("carol", "C1")
faelle.append(("zwei neue fremde", "chef", True))
faelle.append(("derselbe Stand, aber ohne Adminrecht", "chef", False))
faelle.append(("Melder mit eigenen UND fremden", "alice", True))

for name, wer, adm in faelle:
    n = iss.unseen_count(wer, is_admin=adm)
    liste = iss.unseen_details(wer, is_admin=adm)
    check(n == len(liste),
          "%s: Zaehler == Laenge der Liste (%d)" % (name, n), "%d vs %d" % (n, len(liste)))

# Und der Quelltext haelt fest, WARUM: unseen_count zaehlt nicht selbst.
QUELLE = (ROOT / "backend" / "issues.py").read_text(encoding="utf-8")
_m = re.search(r"\ndef unseen_count\([\s\S]*?\n\n\n", QUELLE)
_uc = _m.group(0) if _m else ""
check(bool(_uc), "unseen_count ist auffindbar")
check("unseen_details(" in _uc, "unseen_count fragt unseen_details")
check("for " not in _uc and "admin_change_pending" not in _uc,
      "und hat KEINE eigene Zaehlschleife mehr – sonst zwei Fassungen derselben Regel")


# ═══════════════════════════════════════════════════════════════════════════
section("4) Reihenfolge, Robustheit, Geheimnisse")
# ═══════════════════════════════════════════════════════════════════════════
leeren()
alle = iss._load_all()
for i, (autor, titel, ts) in enumerate([("alice", "Alt", "2026-01-01T00:00:00"),
                                        ("alice", "Neu", "2026-09-01T00:00:00"),
                                        ("alice", "Mitte", "2026-05-01T00:00:00")]):
    it = neu(autor, titel)
alle = iss._load_all()
for it in alle:
    it["status_seen"] = "open"
    it["status"] = "closed"
    it["updated"] = {"Alt": "2026-01-01T00:00:00", "Neu": "2026-09-01T00:00:00",
                     "Mitte": "2026-05-01T00:00:00"}[it["title"]]
iss._save_all(alle)
d = iss.unseen_details("alice")
check([x["title"] for x in d] == ["Neu", "Mitte", "Alt"],
      "neueste zuerst", [x["title"] for x in d])

# Ein Eintrag OHNE Zeitstempel darf die Liste nicht unbrauchbar machen.
alle = iss._load_all()
alle[0]["updated"] = None
iss._save_all(alle)
try:
    d = iss.unseen_details("alice")
    check(len(d) == 3, "ein Eintrag ohne Zeitstempel wirft nicht – er sortiert nach hinten")
    check(d[-1]["title"] == alle[0]["title"], "und zwar ans Ende", d[-1]["title"])
except Exception as ex:  # noqa: BLE001
    check(False, "ein Eintrag ohne Zeitstempel wirft nicht", ex)

check(iss.unseen_details("", is_admin=True) == [],
      "ohne Benutzernamen gibt es nichts (fail-closed)")

# Es darf NICHTS herausgehen, was `list_issues` nicht ohnehin jedem zeigt.
erlaubt = {"id", "title", "kind", "status", "type", "ts", "author", "comment"}
leeren()
x = neu("alice", "Feld-Pruefung")
iss.update_issue("chef", x["id"], {"jarvis_comment": "k"}, is_admin=True)
felder = set()
for e in iss.unseen_details("alice"):
    felder |= set(e)
check(felder <= erlaubt, "keine unerwarteten Felder in der Antwort", felder - erlaubt)


# ═══════════════════════════════════════════════════════════════════════════
section("5) Verdrahtung: der Endpunkt liefert Liste UND volle Zahl")
# ═══════════════════════════════════════════════════════════════════════════
MAIN = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
_m = re.search(r"\nasync def api_issues_notifications\(", MAIN)
_rest = MAIN[_m.start() + 1:] if _m else ""
_e = re.search(r"\n@app\.", _rest)
_ep = _rest[:_e.start()] if _e else _rest
check(bool(_ep), "der Endpunkt ist auffindbar")
check("unseen_details(" in _ep, "er ruft unseen_details")
check("_is_admin_user(user)" in _ep, "mit dem Administrator-Status")
check("_mit_anzeigenamen(" in _ep,
      "der Melder-Name laeuft durch _mit_anzeigenamen (Domaenen-Praefix)")

# ⚠ DER DECKEL DARF DEN ZAEHLER NICHT VERKUERZEN. Stuende dort
# len(posten[:MAX]), zeigte der Badge hoechstens 12 – und „… und N weitere"
# waere strukturell unmoeglich.
check("len(posten)" in _ep, "count ist die VOLLE Zahl")
check(re.search(r"count.*len\(posten\[", _ep) is None,
      "und NICHT die Laenge der gekuerzten Liste")
check("posten[:" in _ep, "gekuerzt wird nur die Uebertragung")

print("\n%d OK, %d FAIL" % (_ok, _fail))
sys.exit(1 if _fail else 0)
