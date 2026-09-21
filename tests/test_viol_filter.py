#!/usr/bin/env python3
"""Waechter: Benutzer-Filter der Zugriffs-Verstoesse (2026-09-21).

WARUM ES DIESEN TEST GIBT: die Liste zeigt die neuesten 150 Vorfaelle ueber
ALLE Benutzer, gespeichert werden aber bis zu 100 JE BENUTZER. Ein Filter, der
erst die 150 holt und dann aussiebt, zeigt nicht "die letzten N von X", sondern
"Xs Anteil an den letzten 150" – und der ist bei mehreren aktiven Benutzern
still fast leer. An einem Bestand mit drei Benutzern gemessen: **0 statt 40**.
Dieselbe Lehre wie beim Wissensgruppen-Filter, der deshalb IN die Suche gehoert.

GEMESSEN, NICHT GELESEN: `list_recent_violations` und `known_violation_users`
laufen WIRKLICH gegen einen Sandkasten-Bestand. Eine Quelltext-Pruefung koennte
die Frage "verliert der Filter Eintraege?" gar nicht beantworten.
"""
import ast
import io
import json
import os
import pathlib
import sys
import tempfile
import types

WURZEL = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(WURZEL))

ok = fail = 0


def check(text, bed, zusatz=""):
    global ok, fail
    if isinstance(bed, str) or not isinstance(text, str):
        print("ABBRUCH: check(text, bedingung) vertauscht")
        sys.exit(2)
    if bed:
        ok += 1
        print("  \033[32m✓\033[0m " + text)
    else:
        fail += 1
        print("  \033[31m✗\033[0m " + text + (("  [" + str(zusatz) + "]") if zusatz else ""))


def sicher(fn, *a, **kw):
    """Ein Wurf ist ein FAIL, kein Abbruch – sonst endet der Lauf ohne Bilanz
    und ist von 'nicht gelaufen' nicht zu unterscheiden."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return ("__FEHLER__", "%s: %s" % (type(e).__name__, e))


# ── backend.config NUR als Stub: der echte Import schriebe die Live-settings.json
_cfg = types.ModuleType("backend.config")


class _C:
    def __getattr__(self, n):
        return None

    def get_skill_states(self):
        return {}


_cfg.config = _C()
sys.modules.setdefault("backend.config", _cfg)

import backend.security_guard as sg  # noqa: E402

# ── Sandkasten-Waechter: NIE in den echten Bestand schreiben ─────────────────
_TMP = pathlib.Path(tempfile.mkdtemp(prefix="violfilter-"))
sg._STATE_FILE = _TMP / "security_state.json"
if not str(sg._STATE_FILE).startswith(str(_TMP)):
    print("ABBRUCH: Sandkasten greift nicht – der Test schriebe in den echten Bestand")
    sys.exit(2)

# ── Namens-Guard GANZ OBEN: gegen einen aelteren Stand bricht der Lauf sonst
#    mit AttributeError ab, also ohne Bilanzzeile.
for _n in ("list_recent_violations", "known_violation_users", "norm_user"):
    if not hasattr(sg, _n):
        print("ABBRUCH: security_guard.%s fehlt (alter Stand?)" % _n)
        sys.exit(2)

# ── Bestand: drei Benutzer. ALT hat NUR alte Eintraege und faellt damit
#    vollstaendig aus den neuesten 150 heraus – genau der Fall, den ein
#    nachtraeglicher Filter verschweigt.
BESTAND = {
    "violations": {
        "nexus\\alt.user": [
            {"ts": 1000 + i, "channel": "chat", "pattern": "fs-deny", "detail": "d%d" % i}
            for i in range(40)
        ],
        "nexus\\laut.user": [
            {"ts": 9000 + i, "channel": "chat", "pattern": "shell-write",
             "detail": "x%d" % i, "soft": True}
            for i in range(100)
        ],
        "dritter": [
            {"ts": 9500 + i, "channel": "chat", "pattern": "shell-illegal", "detail": "y%d" % i}
            for i in range(60)
        ],
    },
    "logonly": [
        {"ts": 500, "user": "wa:+49", "channel": "email",
         "pattern": "ignoriere-anweisungen", "snippet": "IGNORIERE"},
        # Ein Eintrag OHNE Benutzer – er erscheint als "?" in der Liste und darf
        # deshalb NICHT im Pulldown stehen (ein Filter, der nichts findet).
        {"ts": 501, "channel": "email", "pattern": "ignoriere-anweisungen", "snippet": "X"},
    ],
}
sg._STATE_FILE.write_text(json.dumps(BESTAND), encoding="utf-8")

print("\n\033[1m1. Der Filter wirkt VOR dem Schnitt – sonst verliert er still\033[0m")
ohne = sicher(sg.list_recent_violations, 150)
check("ohne Filter kommen die neuesten 150", isinstance(ohne, list) and len(ohne) == 150,
      len(ohne) if isinstance(ohne, list) else ohne)
anteil = sum(1 for e in ohne if "alt.user" in (e.get("user") or "")) if isinstance(ohne, list) else -1
check("Positivkontrolle: alt.user faellt aus den neuesten 150 vollstaendig heraus",
      anteil == 0, "Anteil=%s" % anteil)
mit = sicher(sg.list_recent_violations, 150, True, "nexus\\alt.user")
check("mit Filter kommen ALLE 40 Eintraege dieses Benutzers",
      isinstance(mit, list) and len(mit) == 40,
      "%s (nachtraeglich gefiltert waeren es %s)" % (
          len(mit) if isinstance(mit, list) else mit, anteil))
check("und sie gehoeren wirklich diesem Benutzer",
      isinstance(mit, list) and all("alt.user" in (e.get("user") or "") for e in mit))

print("\n\033[1m2. Verglichen wird ROH und normalisiert\033[0m")


def n_treffer(f):
    r = sicher(sg.list_recent_violations, 150, True, f)
    return len(r) if isinstance(r, list) else -1


check("ohne Domaenen-Praefix findet denselben Benutzer", n_treffer("alt.user") == 40,
      n_treffer("alt.user"))
check("Gross-/Kleinschreibung ist egal", n_treffer("NEXUS\\ALT.USER") == 40,
      n_treffer("NEXUS\\ALT.USER"))
check("Leerraum aussen stoert nicht", n_treffer("  alt.user  ") == 40, n_treffer("  alt.user  "))
check("eine Kanal-Kennung bleibt ganz (wa:+49)", n_treffer("wa:+49") == 1, n_treffer("wa:+49"))
check("ein unbekannter Name liefert nichts – und wirft nicht", n_treffer("gibtsnicht") == 0,
      n_treffer("gibtsnicht"))
leer = sicher(sg.list_recent_violations, 150, True, "")
check("leerer Filter ist identisch mit 'kein Filter'", leer == ohne)
check("Teiltreffer zaehlen NICHT als Treffer (ein Name ist kein Suchbegriff)",
      n_treffer("alt") == 0, n_treffer("alt"))

print("\n\033[1m3. Die Benutzerliste kommt aus dem GANZEN Speicher\033[0m")
users = sicher(sg.known_violation_users)
check("sie ist eine Liste", isinstance(users, list), users)
check("⚠ alt.user ist dabei, obwohl ALLE seine Eintraege aus der Anzeige fallen",
      isinstance(users, list) and "nexus\\alt.user" in users, users)
check("der Kanal-Absender ist dabei (er steht ebenfalls in der Liste)",
      isinstance(users, list) and "wa:+49" in users, users)
check("ein Eintrag OHNE Benutzer wird NICHT angeboten (waere ein Filter ohne Treffer)",
      isinstance(users, list) and "" not in users and "?" not in users, users)
check("keine Doppelten", isinstance(users, list) and len(users) == len(set(users)), users)
check("neueste Aktivitaet zuerst",
      isinstance(users, list) and users[:2] == ["dritter", "nexus\\laut.user"], users)
check("jeder angebotene Name findet auch wirklich Eintraege",
      isinstance(users, list) and all(n_treffer(u) > 0 for u in users), users)

print("\n\033[1m4. Der leere Bestand wirft nicht\033[0m")
sg._STATE_FILE.write_text("{}", encoding="utf-8")
check("Liste leer", sicher(sg.list_recent_violations, 150) == [])
check("Benutzerliste leer", sicher(sg.known_violation_users) == [])
check("Filter auf leerem Bestand leer", sicher(sg.list_recent_violations, 150, True, "x") == [])
sg._STATE_FILE.write_text(json.dumps(BESTAND), encoding="utf-8")

print("\n\033[1m5. Der Endpunkt – als REGEL ueber den Syntaxbaum\033[0m")
MAIN = io.open(WURZEL / "backend/main.py", encoding="utf-8").read()


def rumpf(pfad):
    """Rumpf der Endpunkt-Funktion, OHNE Docstring: sonst liest der Waechter
    seine eigene Begruendung (die nennt 'query_params' woertlich)."""
    baum = ast.parse(MAIN)
    for k in ast.walk(baum):
        if not isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for d in k.decorator_list:
            # ast.unparse normiert auf EINFACHE Anfuehrungszeichen – wer hier
            # nach "..." sucht, findet den Endpunkt nie und meldet acht Fehler,
            # die es nicht gibt.
            src = ast.unparse(d).replace('"', "'")
            if pfad in src:
                koerper = list(k.body)
                if (koerper and isinstance(koerper[0], ast.Expr)
                        and isinstance(koerper[0].value, ast.Constant)
                        and isinstance(koerper[0].value.value, str)):
                    koerper = koerper[1:]
                return k, "\n".join(ast.unparse(x) for x in koerper)
    return None, ""


FN, RUMPF = rumpf("'/api/security/violations'")
check("der Endpunkt ist auffindbar (Positivkontrolle)", FN is not None)
check("er ist weiterhin Administratoren vorbehalten",
      FN is not None and "require_local_auth" in ast.unparse(FN.args))
check("⚠ der Filter kommt aus request.query_params, nicht als Argument 'user' "
      "(der Name gehoert der Dependency)",
      "query_params" in RUMPF and "request" in ast.unparse(FN.args) if FN else False)
check("er reicht ihn als user_filter durch", "user_filter" in RUMPF, RUMPF[:120])
check("er liefert die Benutzerliste mit", "known_violation_users" in RUMPF)
check("und die Zahlen OHNE Filter ('gesamt')", "'gesamt'" in RUMPF or '"gesamt"' in RUMPF)
# Die Zusage, auf die der Zaehler baut: `gesamt` darf NIE aus der gefilterten
# Liste stammen. Gemessen am Syntaxbaum: der zweite Aufruf ohne user_filter.
_aufrufe = []
if FN is not None:
    for k in ast.walk(FN):
        if isinstance(k, ast.Call) and "list_recent_violations" in ast.unparse(k.func):
            _aufrufe.append(ast.unparse(k))
check("es gibt einen Aufruf OHNE user_filter – die Grundlage des Zaehlers",
      any("user_filter" not in a for a in _aufrufe), _aufrufe)
check("und einen MIT – die Grundlage der Liste",
      any("user_filter" in a for a in _aufrufe), _aufrufe)

print("\n\033[1m6. Kein anderer Aufrufer ist gebrochen\033[0m")
# Der Parameter ist ANGEHAENGT, nicht eingeschoben: ein Bestandsaufruf mit
# Positionsargumenten (limit, mit_logonly) muss unveraendert arbeiten.
sig = sg.list_recent_violations.__doc__ or ""
check("Aufruf mit nur einem Positionsargument arbeitet wie bisher",
      isinstance(sicher(sg.list_recent_violations, 5), list)
      and len(sicher(sg.list_recent_violations, 5)) == 5)
check("Aufruf mit zwei Positionsargumenten (ohne logonly) arbeitet wie bisher",
      all(e.get("pattern") != "ignoriere-anweisungen"
          for e in sicher(sg.list_recent_violations, 150, False)))
check("der Docstring benennt, warum vor dem Schnitt gefiltert wird",
      "vor" in sig.lower() and "limit" in sig.lower())

print("\n\033[1mErgebnis: %d/%d\033[0m" % (ok, ok + fail))
sys.exit(1 if fail else 0)
