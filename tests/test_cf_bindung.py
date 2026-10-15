#!/usr/bin/env python3
"""Waechter fuer die dynamische Confluence-Einbindung (/wissen), Baum-Fassung
(Vorgabe 2026-09-27: Bereiche + Unterbereiche markieren, EIN Eintrag je
Uebernahme, gespeicherte Eintraege editierbar).

GEMESSEN WIRD DIE EIGENSCHAFT, NICHT DAS VORKOMMEN:

* Abschnitt 2 fuehrt ``backend/confluence_bindung.py`` WIRKLICH aus – ob eine
  Dublette abgewiesen wird oder ein Deckel greift, kann eine Quelltext-Pruefung
  nicht beantworten.
* Abschnitt 3 misst die Endpunkte ueber den AST und prueft REIHENFOLGEN
  (Sichtbarkeits-Pruefung VOR dem Schreiben) – ein Aufruf, der dahinter
  rutscht, ist wirkungslos und bliebe bei einer Textsuche gruen.
* Abschnitt 6 leitet die i18n-Pflicht aus dem CODE ab, nicht aus einer
  gepflegten Liste: ein kuenftiger Schluessel faellt damit von selbst auf.

⚠ SANDKASTEN MIT EXIT 2. ``confluence_bindung`` schreibt sonst in den echten
Bestand unter ``data/`` – ein Test, der die Einbindungen des Betriebs
ueberschreibt, ist teurer als der Fehler, den er sucht.
"""
from __future__ import annotations

import ast
import re
import io
import json
import os
import sys
import tempfile
import types
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = FAIL = 0
def section(t): print(f"\n\033[1m{t}\033[0m")
def check(desc, cond, info=""):
    global OK, FAIL
    if cond:
        OK += 1; print(f"  \033[32m✓\033[0m {desc}")
    else:
        FAIL += 1; print(f"  \033[31m✗\033[0m {desc}" + (f" – {info}" if info else ""))

def sicher(fn, *a, **kw):
    """Nie ungeprueft dereferenzieren: ein Wurf darf FEHLSCHLAGEN, nicht den
    Lauf ohne Bilanzzeile abbrechen (Register)."""
    try:
        return fn(*a, **kw)
    except Exception as e:  # noqa: BLE001
        return e


def ohne_worte(quelle: str) -> str:
    """Kommentare UND Docstrings entfernen.

    ``tokenize`` kennt nur ``#`` – die Begruendungen dieses Projekts stehen
    ueberwiegend in Docstrings, und ein Waechter, der seine eigene Erklaerung
    liest, prueft nichts (18 belegte Faelle im Register)."""
    baum = ast.parse(quelle)
    weg = []
    for k in ast.walk(baum):
        if isinstance(k, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            d = ast.get_docstring(k, clean=False)
            if d is not None and k.body and isinstance(k.body[0], ast.Expr):
                weg.append((k.body[0].lineno, k.body[0].end_lineno))
    zeilen = quelle.splitlines(keepends=True)
    for a, b in weg:
        for i in range(a - 1, b):
            zeilen[i] = "\n"
    txt = "".join(zeilen)
    aus = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(txt).readline):
            if tok.type != tokenize.COMMENT:
                aus.append(tok.string if tok.type != tokenize.NL else "\n")
    except Exception:  # noqa: BLE001
        return txt
    return txt  # Docstrings sind raus; Kommentare unten gezielt je Pruefung


def ohne_kommentar(quelle: str) -> str:
    """Nur die Kommentarzeichen entfernen (fuer Text-Pruefungen)."""
    raus = []
    try:
        for tok in tokenize.generate_tokens(io.StringIO(quelle).readline):
            if tok.type == tokenize.COMMENT:
                raus.append((tok.start, tok.end))
    except Exception:  # noqa: BLE001
        return quelle
    zeilen = quelle.splitlines(keepends=True)
    for (sz, sc), (ez, ec) in reversed(raus):
        z = zeilen[sz - 1]
        zeilen[sz - 1] = z[:sc] + z[ec:] if sz == ez else z[:sc] + "\n"
    return "".join(zeilen)


# ════════════════════════════════════════════════════════════════════════════
section("1. Sandkasten – der echte Bestand wird NICHT angefasst")
import backend.confluence_bindung as cfb  # noqa: E402

ECHT = cfb._pfad()
SAND = Path(tempfile.mkdtemp(prefix="cfb-test-"))
cfb._pfad = lambda: SAND / "confluence_bindung.json"      # type: ignore[assignment]

# Gemessen wird, was das MODUL benutzt – nicht, was der Test zu setzen glaubte.
pfad_jetzt = sicher(cfb._pfad)
if not isinstance(pfad_jetzt, Path) or SAND not in pfad_jetzt.parents:
    print(f"  \033[31m✗\033[0m Sandkasten greift NICHT ({pfad_jetzt}) – Abbruch")
    sys.exit(2)
check("cfb._pfad() zeigt in den Sandkasten", True)
ECHT_VORHER = ECHT.read_bytes() if ECHT.is_file() else None



# ════════════════════════════════════════════════════════════════════════════
section("2. Das Modul laeuft wirklich")

check("leerer Bestand -> leere Liste", sicher(cfb.liste) == [])

A1 = [{"key": "CONTOSO", "name": "aus dem Rumpf", "start": True,
       "seiten": ["11", "12", "11"], "zweige": ["13"]},
      {"key": "OPS", "ganz": True}]
e1 = sicher(cfb.hinzufuegen, A1, "firma\\m.mustermann", ["technik"],
            {"CONTOSO": "CONTOSO Dokumentation", "OPS": "Betrieb"})
check("hinzufuegen liefert EINEN Eintrag fuer mehrere Bereiche", isinstance(e1, dict), str(e1))
if isinstance(e1, dict):
    aw = e1.get("auswahl") or []
    check("Eintrag traegt eine Kennung", bool(e1.get("id")))
    check("beide Bereiche stehen in DERSELBEN Auswahl", [a.get("key") for a in aw] == ["CONTOSO", "OPS"])
    check("⚠ der Anzeigename kommt vom Aufrufer (Server), nicht aus dem Rumpf",
          aw and aw[0].get("name") == "CONTOSO Dokumentation", str(aw[:1]))
    check("der Eintragsname nennt die Bereiche", e1.get("name") == "CONTOSO Dokumentation · Betrieb",
          e1.get("name"))
    check("Seiten werden entdoppelt, Reihenfolge bleibt",
          aw and aw[0].get("seiten")[:2] == ["11", "12"], str(aw[0].get("seiten") if aw else ""))
    check("⚠ ein Zweig ist immer auch eine markierte Seite",
          aw and "13" in aw[0].get("seiten", []), str(aw[0] if aw else ""))
    check("ganz setzt auch start (der Bereich selbst gehoert dazu)",
          len(aw) > 1 and aw[1].get("ganz") is True and aw[1].get("start") is True, str(aw[1:]))
    check("der Anleger wird festgehalten", e1.get("von") == "firma\\m.mustermann")
    check("typ steht in der Ablage", e1.get("typ") == "auswahl")
    check("die Wissensgruppen stehen in der Ablage", e1.get("gruppen") == ["technik"])

check("liste() enthaelt den Eintrag", [b.get("id") for b in cfb.liste()] == [e1.get("id") if isinstance(e1, dict) else None])
check("holen() findet ihn", isinstance(e1, dict) and (cfb.holen(e1["id"]) or {}).get("id") == e1["id"])
check("holen() mit fremder Kennung -> None", cfb.holen("gibtsnicht") is None and cfb.holen("") is None)

# ⚠ Falsyness waere hier falsch: ein "ja" oder eine 1 ist keine Entscheidung.
e3 = sicher(cfb.hinzufuegen, [{"key": "DOCS", "start": "ja", "ganz": 1, "seiten": ["5"]}], "x", ["technik"])
check("⚠ start='ja' / ganz=1 zaehlen NICHT als gesetzt (is True)",
      isinstance(e3, dict) and e3["auswahl"][0]["start"] is False and e3["auswahl"][0]["ganz"] is False,
      str(e3))
check("ohne Namen vom Server faellt der Name auf den Schluessel zurueck",
      isinstance(e3, dict) and e3["auswahl"][0]["name"] == "DOCS")

for boes, was in [([], "leere Auswahl"), ("CONTOSO", "Zeichenkette statt Liste"),
                  ([{"key": "X"}], "Bereich ganz ohne Markierung"),
                  ([{"key": "A", "start": True}, {"key": "A", "start": True}], "Bereich doppelt"),
                  ([{"key": "A", "seiten": ["12a"]}], "Seitenkennung mit Buchstaben"),
                  ([{"key": "A", "seiten": ["1 2"]}], "Seitenkennung mit Leerzeichen"),
                  ([{"key": "A", "seiten": "123"}], "Seiten als Zeichenkette"),
                  ([{"key": "A", "seiten": ["9" * 40]}], "Seitenkennung zu lang"),
                  (["A"], "Element ohne Form")]:
    r = sicher(cfb.hinzufuegen, boes, "x", ["technik"])
    check(f"abgewiesen: {was}", isinstance(r, cfb.BindungFehler), f"kam durch: {r}")

# ⚠ MUSS-FREI: echte Schluessel des DEV-Confluence. Eine erste Fassung liess
# `@` weg und haette 185 von 489 Bereichen abgewiesen – alle persoenlichen.
for gut, was in [("24H", "kurz, gross"), ("CONTOSOKIS", "lang, gross"),
                 ("~Anna-Lena.Musterfrau@beispiel-schweiz.example", "persoenlicher Bereich"),
                 ("~a.weber@beispiel.de", "persoenlich, klein"),
                 ("ds_2024", "Unterstrich"), ("a+b@x.de", "Plus")]:
    r = sicher(cfb.hinzufuegen, [{"key": gut, "start": True}], "x", ["technik"])
    check(f"echter Schluessel wird ANGENOMMEN ({was})", isinstance(r, dict), f"abgewiesen: {r}")
    if isinstance(r, dict):
        check(f"  und ungekuerzt gespeichert ({was})", r["auswahl"][0]["key"] == gut)
        cfb.entfernen(r["id"])

for boes, was in [("", "leer"), ("a b", "Leerzeichen"), ("x" * 200, "zu lang"),
                  ("../../etc", "Pfadanteil"), ("a\nb", "Zeilenumbruch"),
                  ('a"b', "Anfuehrungszeichen"), ("a/b", "Schraegstrich")]:
    r = sicher(cfb.hinzufuegen, [{"key": boes, "start": True}], "x", ["technik"])
    check(f"unbrauchbarer Schluessel abgewiesen ({was})", isinstance(r, cfb.BindungFehler),
          f"kam durch: {r}")

# Deckel
r = sicher(cfb.hinzufuegen, [{"key": f"K{i}", "start": True} for i in range(cfb.MAX_SPACES_JE_EINTRAG + 1)],
           "x", ["technik"])
check(f"Deckel {cfb.MAX_SPACES_JE_EINTRAG} Bereiche je Eintrag greift", isinstance(r, cfb.BindungFehler), str(r)[:80])
r = sicher(cfb.hinzufuegen, [{"key": "VIEL", "seiten": [str(i) for i in range(cfb.MAX_SEITEN_JE_EINTRAG + 1)]}],
           "x", ["technik"])
check(f"Deckel {cfb.MAX_SEITEN_JE_EINTRAG} Seiten je Eintrag greift", isinstance(r, cfb.BindungFehler), str(r)[:80])
bis = cfb.MAX_BEREICHE - len(cfb.liste())
for i in range(bis):
    cfb.hinzufuegen([{"key": f"AUTO{i}", "start": True}], "x", ["technik"])
r = sicher(cfb.hinzufuegen, [{"key": "ZUVIEL", "start": True}], "x", ["technik"])
check(f"Deckel {cfb.MAX_BEREICHE} Eintraege greift", isinstance(r, cfb.BindungFehler), f"kam durch: {r}")
check("der Deckel nennt die Zahl", isinstance(r, cfb.BindungFehler) and str(cfb.MAX_BEREICHE) in str(r))
for b in list(cfb.liste()):
    if b["name"].startswith("AUTO"):
        cfb.entfernen(b["id"])

# Bearbeiten
if isinstance(e1, dict):
    # ⚠ Ein Anlagedatum aus DERSELBEN Sekunde wie die Aenderung beweist nichts
    # (Gegenprobe: "ueberschreibt das Anlagedatum" blieb stumm). Also ein
    # deutlich aelteres Datum in die Ablage schreiben.
    _d = json.loads(cfb._pfad().read_text(encoding="utf-8"))
    for _b in _d["bereiche"]:
        if _b.get("id") == e1["id"]:
            _b["angelegt"] = "2020-01-02T03:04:05"
    cfb._pfad().write_text(json.dumps(_d), encoding="utf-8")
    vor = cfb.holen(e1["id"])
    check("(Positivkontrolle) das alte Anlagedatum steht in der Ablage",
          (vor or {}).get("angelegt") == "2020-01-02T03:04:05")
    g = sicher(cfb.aendern, e1["id"], [{"key": "OPS", "seiten": ["7"]}], "kollege", ["vertrieb"],
               {"OPS": "Betrieb"})
    check("aendern liefert den geaenderten Eintrag", isinstance(g, dict), str(g))
    if isinstance(g, dict):
        check("⚠ Kennung und Anlagedatum bleiben", g["id"] == e1["id"] and g["angelegt"] == vor["angelegt"])
        check("die Auswahl ist ersetzt (CONTOSO entfernt, OPS nur Seite 7)",
              [(a["key"], a["seiten"], a["ganz"]) for a in g["auswahl"]] == [("OPS", ["7"], False)],
              str(g["auswahl"]))
        check("die Gruppen sind ersetzt", g["gruppen"] == ["vertrieb"])
        check("von nennt, wer zuletzt geaendert hat", g["von"] == "kollege")
        check("die Reihenfolge der Liste bleibt", cfb.liste()[0]["id"] == e1["id"])
    r = sicher(cfb.aendern, "gibtsnicht", [{"key": "OPS", "start": True}], "x", ["technik"])
    check("unbekannter Eintrag -> KeyError (Endpunkt macht 404)", isinstance(r, KeyError), str(r))
    r = sicher(cfb.aendern, e1["id"], [], "x", ["technik"])
    check("⚠ leere Auswahl beim Bearbeiten wird abgewiesen (loeschen ist der Muelleimer)",
          isinstance(r, cfb.BindungFehler))
    r = sicher(cfb.aendern, e1["id"], [{"key": "OPS", "start": True}], "x", [])
    check("⚠ ohne Wissensgruppe wird auch beim Bearbeiten nicht gespeichert",
          isinstance(r, cfb.BindungFehler))
    check("und der Eintrag ist nach den Fehlversuchen unveraendert",
          (cfb.holen(e1["id"]) or {}).get("gruppen") == ["vertrieb"])

# Entfernen
check("entfernen meldet Erfolg", isinstance(e1, dict) and cfb.entfernen(e1["id"]) is True)
check("zweites Entfernen meldet FALSE", isinstance(e1, dict) and cfb.entfernen(e1["id"]) is False)
check("unbekannte/leere Kennung entfernt nichts", cfb.entfernen("gibtsnicht") is False and cfb.entfernen("") is False)

mode = sicher(lambda: oct(os.stat(cfb._pfad()).st_mode & 0o777))
check("Ablage ist 0640", mode == "0o640", str(mode))

# ⚠ Eine beschaedigte Datei darf NICHT stillschweigend ersetzt werden.
kaputt = b'{"version": 1, "bereiche": [ das ist kein json'
cfb._pfad().write_bytes(kaputt)
# ⚠ Bis 2026-09-28 hiess es hier "kaputte Datei -> leere Liste". Eine leere
# Liste ist aber eine AUSSAGE ("nichts eingebunden") - der Abgleich raeumte
# daraufhin alles ab, und hinzufuegen schrieb ueber die Datei.
_BU = getattr(cfb, "BestandUnlesbar", ())
check("⚠ kaputte Datei -> BestandUnlesbar, NICHT die leere Liste", isinstance(sicher(cfb.liste), _BU))
check("⚠ kaputte Datei wird beim LESEN nicht ueberschrieben", cfb._pfad().read_bytes() == kaputt)
_r = sicher(cfb.hinzufuegen, [{"key": "NEU", "start": True}], "x", ["technik"])
check("⚠ hinzufuegen verweigert auf einer kaputten Datei", isinstance(_r, _BU), repr(_r))
check("⚠ …und schreibt NICHT darueber", cfb._pfad().read_bytes() == kaputt)
check("BestandUnlesbar ist ein BindungFehler (die Endpunkte fangen ihn)",
      isinstance(_BU, type) and issubclass(_BU, cfb.BindungFehler))
import contextlib, io as _io  # noqa: E402
_buf = _io.StringIO()
with contextlib.redirect_stdout(_buf):
    sicher(cfb.liste)
check("⚠ ein Lesefehler wird BENANNT (Journal), nicht verschluckt",
      "CF-Bindung" in _buf.getvalue() and "nicht lesbar" in _buf.getvalue(), repr(_buf.getvalue()[:120]))
cfb._pfad().unlink()
_buf2 = _io.StringIO()
with contextlib.redirect_stdout(_buf2):
    cfb.liste()
check("(Positivkontrolle) der Normalfall meldet NICHTS", _buf2.getvalue() == "")


# ════════════════════════════════════════════════════════════════════════════
section("2b. Wissensgruppen-Pflicht und Altbestand – AUSGEFUEHRT")
for leer, was in [(None, "gar nicht uebergeben"), ([], "leere Liste"),
                  (["", "  "], "nur Leerraum"), (["", None], "leer und None")]:
    r = sicher(cfb.hinzufuegen, [{"key": "OHNEGRP", "start": True}], "x", leer)
    check(f"⚠ ohne Wissensgruppe wird NICHT gespeichert ({was})",
          isinstance(r, cfb.BindungFehler), f"kam durch: {r}")
check("der Grund nennt die Wissensgruppe",
      "Wissensgruppe" in str(sicher(cfb.hinzufuegen, [{"key": "O", "start": True}], "x", [])))
check("und es bleibt wirklich nichts liegen", cfb.liste() == [])
r = sicher(cfb.hinzufuegen, [{"key": "STR", "start": True}], "x", "technik")
check("⚠ eine Zeichenkette statt einer Gruppenliste wird abgewiesen", isinstance(r, cfb.BindungFehler))
m = sicher(cfb.hinzufuegen, [{"key": "MEHR", "start": True}], "x", ["technik", "vertrieb", "technik"])
check("mehrere Gruppen, Dubletten still zusammengefasst",
      isinstance(m, dict) and m.get("gruppen") == ["technik", "vertrieb"])
if isinstance(m, dict):
    cfb.entfernen(m["id"])
for gid in ["technik", "it-betrieb", "gruppe-2", "a", "abteilung-vertrieb-nord"]:
    r = sicher(cfb.hinzufuegen, [{"key": "OK", "start": True}], "x", [gid])
    check(f"echte Gruppen-Kennung wird ANGENOMMEN ({gid})", isinstance(r, dict), f"abgewiesen: {r}")
    if isinstance(r, dict):
        cfb.entfernen(r["id"])

# ⚠ ALTBESTAND (typ "space", bis 2026-09-26) wird beim LESEN in die neue Form
# gebracht – aber NICHT umgeschrieben und bekommt KEINE geratene Zuordnung.
alt_roh = json.dumps({"version": 1, "bereiche": [
    {"id": "alt1", "typ": "space", "key": "ALT", "name": "Alt", "inkl_unter": True},
    {"id": "alt2", "typ": "space", "key": "ALT2", "name": "Alt 2", "inkl_unter": False,
     "gruppen": ["technik"]}]})
cfb._pfad().write_text(alt_roh, encoding="utf-8")
alt_liste = cfb.liste()
check("Altbestand bleibt lesbar", len(alt_liste) == 2)
a1 = (alt_liste[0].get("auswahl") or [{}])[0] if alt_liste else {}
a2 = (alt_liste[1].get("auswahl") or [{}])[0] if len(alt_liste) > 1 else {}
check("⚠ 'inkl. Unterseiten' AN wird zu ganz", a1.get("key") == "ALT" and a1.get("ganz") is True, str(a1))
check("⚠ 'inkl. Unterseiten' AUS wird zu 'nur der Bereich selbst' (start)",
      a2.get("start") is True and a2.get("ganz") is False and a2.get("seiten") == [], str(a2))
check("⚠ und bekommt KEINE geratene Zuordnung", "gruppen" not in alt_liste[0])
check("⚠ das Lesen schreibt die Ablage NICHT um", cfb._pfad().read_text(encoding="utf-8") == alt_roh)
g = sicher(cfb.aendern, "alt1", [{"key": "ALT", "start": True, "ganz": True}], "x", ["technik"])
check("ein Alteintrag laesst sich bearbeiten (und bekommt so eine Gruppe)",
      isinstance(g, dict) and g.get("gruppen") == ["technik"] and g.get("typ") == "auswahl", str(g))
cfb._pfad().unlink()


# ════════════════════════════════════════════════════════════════════════════
section("3. Endpunkte – Regeln ueber den AST")
MAIN_ROH = (ROOT / "backend" / "main.py").read_text(encoding="utf-8")
MAIN = ohne_worte(MAIN_ROH)
BAUM = ast.parse(MAIN)

def route_fn(methode: str, pfad: str):
    for k in ast.walk(BAUM):
        if not isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in k.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            f = dec.func
            if not (isinstance(f, ast.Attribute) and f.attr == methode):
                continue
            if dec.args and isinstance(dec.args[0], ast.Constant) and dec.args[0].value == pfad:
                return k
    return None

def fn(name: str):
    return next((k for k in ast.walk(BAUM) if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and k.name == name), None)

GET = route_fn("get", "/api/wissen/confluence/bindung")
POST = route_fn("post", "/api/wissen/confluence/bindung")
PUT = route_fn("put", "/api/wissen/confluence/bindung/{bid}")
DEL = route_fn("delete", "/api/wissen/confluence/bindung/{bid}")
LESEN = fn("_cfb_auswahl_lesen")
for nm, k in [("GET", GET), ("POST", POST), ("PUT", PUT), ("DELETE", DEL),
              ("_cfb_auswahl_lesen", LESEN)]:
    check(f"{nm} vorhanden", k is not None)

def rumpf(k):
    return ast.unparse(k) if k is not None else ""

def rufe(k) -> list:
    if k is None:
        return []
    aus = []
    for n in ast.walk(k):
        if isinstance(n, ast.Call):
            f = n.func
            nm = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            if nm:
                aus.append((n.lineno, n.col_offset, nm))
    return [nm for _, _, nm in sorted(aus)]

def pos(folge, nm):
    return folge.index(nm) if nm in folge else -1

for nm, k in [("GET", GET), ("POST", POST), ("PUT", PUT), ("DELETE", DEL)]:
    check(f"{nm}: Wissensbereich wird geprueft", "_editable_groups_for" in rufe(k))
    check(f"{nm}: haengt an require_auth",
          "require_auth" in rumpf(k) and "require_local_auth" not in rumpf(k))
    check(f"{nm}: liefert die Eintraege MIT Gruppennamen", "_cfb_mit_gruppen" in rumpf(k))

# ⚠ Beide schreibenden Wege gehen durch DIESELBE Pruefung – eine zweite
# Fassung liefe beim naechsten Feinschliff auseinander.
for nm, k, schreib in [("POST", POST, "hinzufuegen"), ("PUT", PUT, "aendern")]:
    f = rufe(k)
    check(f"⚠ {nm}: die Pruefung laeuft durch _cfb_auswahl_lesen", "_cfb_auswahl_lesen" in f)
    check(f"⚠ {nm}: und zwar VOR dem Schreiben",
          0 <= pos(f, "_cfb_auswahl_lesen") < pos(f, schreib), f"{f}")
    call = next((n for n in ast.walk(k) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == schreib), None) if k else None
    argn = [a.id for a in (call.args if call else []) if isinstance(a, ast.Name)]
    check(f"⚠ {nm}: die Namen vom Server werden UEBERGEBEN", "namen" in argn, str(argn))
    check(f"{nm}: die geprueften Gruppen werden uebergeben",
          ("req_groups" in argn) if nm == "POST" else ("gruppen" in argn), str(argn))
    pr = rumpf(k)
    for feld in ("'user'", "'von'", "'benutzer'", "'name'"):
        check(f"{nm}: {feld} wird NICHT aus dem Request gelesen", f"body.get({feld})" not in pr)

# Die gemeinsame Pruefung: Reihenfolge ist die Sicherheit.
lf = rufe(LESEN)
i_akt, i_grp = pos(lf, "_cfb_aktiv"), pos(lf, "_wissen_check_groups")
i_form, i_sicht = pos(lf, "_auswahl_pruefen"), pos(lf, "_wissen_visible_spaces")
check("Pruefung: Skill/Konfiguration zuerst", i_akt == 0 or (0 <= i_akt < min(x for x in (i_grp, i_form, i_sicht) if x >= 0)),
      str(lf))
check("⚠ Pruefung: Wissensgruppen gegen den Bereich des Nutzers", i_grp >= 0)
check("Pruefung: die Form der Auswahl wird geprueft", i_form >= 0)
check("⚠ Pruefung: Sichtbarkeit wird abgefragt", i_sicht >= 0)
check("⚠ billig vor teuer: Gruppen und Form VOR dem Confluence-Abruf",
      0 <= i_grp < i_sicht and 0 <= i_form < i_sicht, f"{i_grp}/{i_form}/{i_sicht}")
lr = rumpf(LESEN)
check("⚠ die Kennungen gehen durch die gemeinsame Normierung",
      "_gruppen_normieren(body.get('groups'))" in lr)
# ⚠ ALS WIRKUNG, NICHT ALS VORKOMMEN: die Zeilen `not in namen` und
# `status_code=403` standen auch dann noch da, als die Abfrage mit `if False:`
# stillgelegt war (Gegenprobe). Gemessen wird: es gibt ein `if fremd:`, und
# sein Rumpf gibt 403 zurueck; `fremd` wird aus der Sichtbarkeitsliste gebildet.
_if_fremd = [n for n in ast.walk(LESEN) if isinstance(n, ast.If)
             and isinstance(n.test, ast.Name) and n.test.id == "fremd"] if LESEN else []
check("⚠ JEDER Bereich der Auswahl muss sichtbar sein: `if fremd:` gibt 403 zurueck",
      len(_if_fremd) == 1 and any(isinstance(x, ast.Return) and "status_code=403" in ast.unparse(x)
                                  for x in _if_fremd[0].body), str(len(_if_fremd)))
_fz = [n for n in ast.walk(LESEN) if isinstance(n, ast.Assign)
       and any(isinstance(t, ast.Name) and t.id == "fremd" for t in n.targets)] if LESEN else []
check("fremd = Schluessel der Auswahl, die NICHT in den sichtbaren stehen",
      len(_fz) == 1 and "not in namen" in ast.unparse(_fz[0]), ast.unparse(_fz[0]) if _fz else "")
check("die Namen kommen aus der Sichtbarkeitsliste",
      re.search(r"namen = \{.*s\.get\('name'\)", lr) is not None, "namen nicht aus sichtbar")

# ⚠ PUT: fremde Gruppen bleiben stehen.
pu = rumpf(PUT)
check("PUT: unbekannter Eintrag -> 404 VOR der Pruefung (holen)",
      0 <= pos(rufe(PUT), "holen") < pos(rufe(PUT), "_cfb_auswahl_lesen"))
check("⚠ PUT: Zuordnungen AUSSERHALB des eigenen Bereichs werden behalten",
      "not in eigene" in pu and "alt.get('gruppen')" in pu, "fremde Gruppen gingen verloren")
check("PUT: eigene Gruppen kommen als Kennungen (nicht als Gruppen-Objekte)",
      "g.get('id')" in pu, "set(_editable_groups_for(...)) waere eine Menge von dicts")

# ⚠ Code-Review 2026-09-28: PUT/DELETE prueften nur, OB der Aufrufer irgendeine
# Gruppe bearbeitet - ein Editor von A konnte die Einbindung von B loeschen.
# (a) Die Regel AUSGEFUEHRT, an einer Attrappe mit der echten Rueckgabeform.
_DE = fn("_cfb_darf_eintrag")
check("(Positivkontrolle) _cfb_darf_eintrag gefunden", _DE is not None)
if _DE is not None:
    _kgm = types.ModuleType("backend.knowledge_groups")
    _GRUPPEN = [{"id": "a"}, {"id": "b"}, {"id": "c"}]
    _kgm.list_groups = lambda *x, **k: {"groups": list(_GRUPPEN)}
    _BEREICH = {"ed_a": [{"id": "a"}], "ed_ac": [{"id": "a"}, {"id": "c"}], "global": _GRUPPEN}
    _ns = {"_editable_groups_for": lambda u: list(_BEREICH.get(u, []))}
    _vor = sys.modules.get("backend.knowledge_groups")
    sys.modules["backend.knowledge_groups"] = _kgm
    try:
        # Die Regel steht in drei Teilen (Rechte EINMAL je Abruf, reine Regel,
        # Huelle) - alle drei kommen mit, sonst endet der Aufruf im NameError.
        _teile = [fn(x) for x in ("_cfb_rechte", "_cfb_darf", "_cfb_darf_eintrag")]
        check("(Positivkontrolle) _cfb_rechte/_cfb_darf/_cfb_darf_eintrag gefunden", all(_teile))
        exec(compile(ast.Module(body=[x for x in _teile if x], type_ignores=[]), "main", "exec"), _ns)  # noqa: S102
        _darf = _ns["_cfb_darf_eintrag"]
        for u, g, soll, was in [
                ("ed_a", ["b"], False, "⚠ Editor von A darf die Einbindung von B NICHT"),
                ("ed_a", ["a"], True, "Editor von A darf die von A"),
                ("ed_a", ["a", "b"], True, "gemischte Einbindung: wer EINE davon bearbeitet, darf"),
                ("ed_ac", ["b"], False, "⚠ auch mit zwei fremden Gruppen nicht die von B"),
                ("global", ["b"], True, "globaler Wissens-Editor darf alles"),
                ("ed_a", [], True, "Altbestand OHNE Zuordnung: reparierbar"),
                ("ed_a", ["weg"], True, "nur geloeschte Gruppen: gehoert niemandem, reparierbar"),
                ("ed_a", ["weg", "b"], False, "⚠ geloeschte + fremde Gruppe: bleibt fremd")]:
            r = sicher(_darf, u, {"gruppen": g})
            check(was, r is soll, repr(r))
        _kgm.list_groups = lambda *x, **k: (_ for _ in ()).throw(RuntimeError("weg"))
        check("⚠ Gruppenliste nicht ermittelbar: fail-closed",
              sicher(_darf, "ed_a", {"gruppen": []}) is False)
    finally:
        if _vor is not None:
            sys.modules["backend.knowledge_groups"] = _vor
        else:
            sys.modules.pop("backend.knowledge_groups", None)

# (b) Die Verdrahtung als WIRKUNG: ein `if not _cfb_darf_eintrag(...)`, dessen
# Rumpf 403 zurueckgibt - und das VOR dem Schreiben steht.
def _schranke(k, schreib):
    if k is None:
        return False, "fehlt"
    ifs = [n for n in ast.walk(k) if isinstance(n, ast.If)
           and isinstance(n.test, (ast.UnaryOp, ast.BoolOp))
           and "_cfb_darf_eintrag(user," in ast.unparse(n.test)
           and any(isinstance(x, ast.Return) and "status_code=403" in ast.unparse(x) for x in n.body)]
    f = rufe(k)
    return (len(ifs) == 1 and 0 <= pos(f, "_cfb_darf_eintrag") < pos(f, schreib)), f"{len(ifs)} / {f}"
for nm, k, schreib in [("PUT", PUT, "aendern"), ("DELETE", DEL, "entfernen")]:
    _ok, _info = _schranke(k, schreib)
    check(f"⚠ {nm}: fremde Einbindung -> 403, VOR dem Schreiben", _ok, _info)
# Die Liste liefert je Eintrag `darf_aendern` aus DERSELBEN Regel - danach
# blendet /wissen die Knoepfe aus. Eine zweite Fassung liefe auseinander.
_mgf = fn("_cfb_mit_gruppen")
check("die Liste setzt darf_aendern ueber _cfb_darf (dieselbe Regel wie der 403)",
      _mgf is not None and "_cfb_darf" in rufe(_mgf) and "_cfb_rechte" in rufe(_mgf)
      and "'darf_aendern'" in rumpf(_mgf))
check("⚠ die Rechte werden EINMAL je Abruf ermittelt, nicht je Eintrag",
      _mgf is not None and not any(isinstance(n, (ast.For, ast.comprehension)) and any(
          isinstance(c, ast.Call) and getattr(c.func, "id", "") == "_cfb_rechte" for c in ast.walk(n))
          for n in ast.walk(_mgf)))
for nm, k in [("GET", GET), ("POST", POST), ("PUT", PUT), ("DELETE", DEL)]:
    _aufr = [c for c in ast.walk(k) if isinstance(c, ast.Call)
             and getattr(c.func, "id", "") == "_cfb_mit_gruppen"] if k else []
    check(f"{nm}: die Liste bekommt den Abrufenden (darf_aendern)",
          bool(_aufr) and all(len(c.args) >= 2 and ast.unparse(c.args[1]) == "user" for c in _aufr),
          str([ast.unparse(c) for c in _aufr]))
check("PUT: die Eigentumspruefung laeuft VOR der Netzrundreise (_cfb_auswahl_lesen)",
      0 <= pos(rufe(PUT), "_cfb_darf_eintrag") < pos(rufe(PUT), "_cfb_auswahl_lesen"))

_mg = fn("_cfb_mit_gruppen"); _mgq = rumpf(_mg)
check("⚠ die Namen kommen aus ALLEN Wissensgruppen, nicht aus dem Bereich des Abrufers",
      "list_groups" in _mgq and "_editable_groups_for" not in _mgq)
check("eine Kennung ohne Gruppe bleibt aussen vor", "gruppen_info" in _mgq)
check("⚠ die Liste traegt das Ergebnis des letzten Abgleichs", "eintrag_staende" in _mgq and "'abgleich'" in _mgq)

gr = rumpf(GET)
check("GET: meldet den Zustand mit 200 (kein Fehlercode fuer 'Skill aus')",
      "'aktiv':" in gr and gr.count("status_code=403") == 1 and "status_code=400" not in gr)
check("GET: liefert die Eintraege nur bei aktivem Skill",
      "if skill and conf" in gr or "(skill and conf)" in gr)   # unparse laesst Klammern weg
_akq = rumpf(fn("_cfb_aktiv"))
check("_cfb_aktiv prueft BEIDES (Skill aktiv + konfiguriert)",
      "_skill_active('confluence')" in _akq and ".configured" in _akq)
CFA = (ROOT / "backend" / "confluence_abgleich.py").read_text(encoding="utf-8")
check("⚠ der Abgleich benutzt DIESELBE Regel (_cfb_aktiv), keine eigene Fassung",
      "from backend.main import _cfb_aktiv" in ohne_worte(CFA))


# ════════════════════════════════════════════════════════════════════════════
section("4. Die Ablagen stehen in allen drei Sperrlisten")
SB = ohne_kommentar((ROOT / "backend" / "sandbox.py").read_text(encoding="utf-8"))
import backend.sandbox as sandbox  # noqa: E402
for datei in ("data/confluence_bindung.json", "data/confluence_abgleich.json"):
    check(f"{datei} in _APP_DENY_REL", datei in sandbox._APP_DENY_REL)
    check(f"{datei} in PRIVATE_FILES", datei in sandbox.PRIVATE_FILES)
    check(f"{datei} im Shell-Muster SHELL_SECRET_PATHS",
          bool(sandbox.SHELL_SECRET_PATHS.search("cat " + datei)))
check("(die Eintraege stehen wirklich im Code, nicht nur im Kommentar)",
      SB.count("confluence_abgleich") >= 3, f"{SB.count('confluence_abgleich')}x")


# ════════════════════════════════════════════════════════════════════════════
section("5. Oberflaeche – Ort, Grundzustand, Verdrahtung")
HTML = (ROOT / "frontend" / "wissen.html").read_text(encoding="utf-8")
JS = (ROOT / "frontend" / "js" / "wissen.js").read_text(encoding="utf-8")

i_up = HTML.find('id="wi-sec-upload"')
i_cb = HTML.find('id="wi-sec-cfbind"')
i_fl = HTML.find('id="wi-sec-files"')
check("Container vorhanden", i_cb > 0)
check("⚠ steht ZWISCHEN Informationsextraktor und 'Mein Wissen'",
      0 < i_up < i_cb < i_fl, f"upload={i_up} cfbind={i_cb} files={i_fl}")
block = HTML[i_cb:i_fl] if i_cb > 0 else ""
check("startet verborgen (kein Aufblitzen beim Laden)", 'id="wi-sec-cfbind" style="display:none;"' in HTML)
check("⚠ Baum statt Pulldown", 'id="wi-cfb-tree"' in block and "<select" not in block)
check("⚠ das Kaestchen 'inkl. Unterseiten' ist ENTFALLEN",
      'id="wi-cfb-sub"' not in HTML and "wi-cfb-sub" not in JS and "inkl_unter" not in JS)
check("Suchfeld ueber dem Baum", 0 < block.find('id="wi-cfb-such"') < block.find('id="wi-cfb-tree"'))
check("Liste der gespeicherten Eintraege", 'id="wi-cfb-list"' in block)
check("der Container ist einklappbar wie die uebrigen", "'wi-sec-cfbind'" in JS)
check("Knopf zum Uebernehmen, startet gesperrt",
      re.search(r'id="wi-cfb-add"[^>]*\bdisabled', block) is not None)
check("Knopf zum Abbrechen des Bearbeitens", 'id="wi-cfb-cancel"' in block)
i_grp_box, i_tree = block.find('id="wi-cfb-groups"'), block.find('id="wi-cfb-tree"')
i_add = block.find('id="wi-cfb-add"')
check("⚠ Wissensgruppen UEBER dem Baum, Knopf DARUNTER",
      0 < i_grp_box < i_tree < i_add, f"{i_grp_box}/{i_tree}/{i_add}")
check("sie ist beschriftet (Pflichtfeld)", 'data-i18n="wissen.groups_label"' in block)

def js_fn(name):
    m = re.search(r"function " + name + r"\([^)]*\)\s*\{", JS)
    if not m:
        return ""
    i, tiefe = m.end(), 1
    while i < len(JS) and tiefe:
        tiefe += {"{": 1, "}": -1}.get(JS[i], 0); i += 1
    return JS[m.start():i]

pm, nk = js_fn("cfbPlusMinus"), js_fn("cfbNameKlick")
check("(Positivkontrolle) cfbPlusMinus und cfbNameKlick gefunden", bool(pm) and bool(nk))
check("⚠ [-] klappt zu UND nimmt die Markierung darunter zurueck",
      re.search(r"cfbOeffnen\(li,\s*false\);\s*cfbUnten\(li,\s*false\)", pm) is not None)
check("⚠ [+] klappt auf UND markiert samt allem darunter",
      "cfbUnten(li, true)" in pm and "cb.checked = true" in pm and "cfbOeffnen(li, true)" in pm)
check("⚠ der Name klappt nur auf/zu – er aendert KEINEN Haken",
      "cfbUnten" not in nk and ".checked" not in nk and "cfbOeffnen" in nk)
check("⚠ der Name ist KEIN <label> (ein Klick schaltete sonst den Haken)",
      '<label' not in js_fn("cfbSeiteHtml") and '<label' not in js_fn("cfbRenderBaum"))
chg = re.search(r"tree\.addEventListener\('change',\s*function[^)]*\)\s*\{([^}]*)\}", js_fn("cfbVerdrahten"))
check("⚠ ein Haken wirkt nur auf SEINEN Eintrag (change zieht nichts mit)",
      chg is not None and "checked" not in chg.group(1) and "cfbMarken" in chg.group(1),
      chg.group(1).strip() if chg else "kein change-Handler")
check("[+]/[-] stehen als Zeichen da", "'[+]'" in JS and "'[-]'" in JS)
tg = js_fn("cfbRenderBaum")
check("[+] steht HINTER dem Namen", tg.find("wi-cfb-nm") < tg.find("cfbTogHtml(false)"))
au = js_fn("cfbAuswahl")
check("⚠ ein komplett markierter Bereich geht als 'ganz' raus", "ganz: cfbKomplett(li)" in au)
check("⚠ nur Seiten MIT Unterseiten werden Zweig (ein Blatt ist kein Zweig)",
      "cfbKind(pg, 'wi-cf-kids') && cfbKomplett(pg)" in au)
ad = js_fn("cfbAdd")
check("⚠ die Auswahl UND die Gruppen gehen mit dem Rumpf raus",
      "JSON.stringify({ auswahl: auswahl, groups: grp, tags: cfbTagsLesen() })" in ad)
check("⚠ Bearbeiten speichert per PUT auf den Eintrag, Neues per POST",
      "edit ? 'PUT' : 'POST'" in ad and "encodeURIComponent(edit)" in ad)
check("der Knopf verlangt Markierung UND Wissensgruppe",
      re.search(r"btn\.disabled\s*=[^;]*!n[^;]*!grp", js_fn("cfbAddKnopf")) is not None)
check("⚠ der Grund unterscheidet die beiden Faelle",
      "wissen.cfb_need_group" in js_fn("cfbAddKnopf") and "wissen.cfb_add_hint" in js_fn("cfbAddKnopf"))
check("Klick auf den Knopf ruft cfbAdd", re.search(r"btn\.addEventListener\('click',\s*function\s*\(\)\s*\{\s*cfbAdd\(\)", JS) is not None)
check("die Kaestchen entstehen ueber das vorhandene groupBoxes()", "groupBoxes('cfb')" in JS)
_rg = js_fn("cfbRenderGroups")
check("⚠ die Gruppen werden NICHT bei jedem Render neu gezeichnet",
      "querySelector('.wi-grp-cfb')" in _rg and "return" in _rg)
rb = js_fn("cfbRenderBaum")
check("⚠ der Baum wird NICHT bei jedem Render neu gezeichnet (Haken leben im DOM)",
      "_cfbBaumFuer === _cfSpaces" in rb)
def js_zeilenbau(liste):
    """Der ZEILENBAU der Liste samt der Helfer, die er selbst aufruft.

    Frueher stand alles in cfbRenderList; seit 3633ab5/4b99ce5 baut
    cfbRenderEintraege die Zeilen und cfbAktionen die Knoepfe – der Waechter
    schnitt nur noch 8 Zeilen und meldete 3 Fehler, die es nicht gab. Gesucht
    wird deshalb die EIGENSCHAFT "baut wi-item-Zeilen", nicht ein Name; und nur
    EINE Ebene tiefer, damit nicht das halbe Modul im Fenster liegt."""
    rumpf = js_fn(liste)
    bauer = [n for n in re.findall(r"\b(cfb\w+)\(", rumpf)
             if n != liste and 'class="wi-item"' in js_fn(n)]
    if not bauer:
        return rumpf, []
    zeilen = js_fn(bauer[0])
    helfer = sorted({n for n in re.findall(r"\b(cfb\w+)\(", zeilen)} - {bauer[0], liste})
    return "\n".join([rumpf, zeilen] + [js_fn(n) for n in helfer]), [bauer[0]] + helfer

rl, _rl_teile = js_zeilenbau("cfbRenderList")
# Die Enge kommt aus der Bauart (EINE Ebene), nicht aus einer Zeilenzahl –
# eine feste Grenze waere die naechste Zeitbombe.
check("(Positivkontrolle) der Zeilenbau ist erfasst (wi-item + Loeschknopf)",
      'class="wi-item"' in rl and "wi-cfb-del" in rl, str(_rl_teile))
check("jede Zeile hat Bearbeiten (Text) und Muelleimer (Loeschen, kein ×)",
      "wi-cfb-edit" in rl and "JarvisIcons.trash()" in rl and "JarvisIcons.close" not in rl)
check("die Liste zeigt das Abgleichsergebnis", "cfbSyncZeile(b)" in rl and "b.abgleich" in js_fn("cfbSyncZeile"))
check("⚠ ein Eintrag OHNE Zuordnung wird BENANNT (Altbestand)",
      # exakter Aufruf: "wissen.cfb_nogroup" steckt auch in "..._nogroup_hint"
      "t('wissen.cfb_nogroup')" in rl and "wi-cfb-nogrp" in rl and "t('wissen.cfb_grp_gone'" in rl)
check("die Marke dafuer ist gestaltet", ".wi-cfb-nogrp" in HTML)
check("EINE Quelle fuer die Bereichsliste (der Container fragt nicht selbst ab)",
      JS.count("/api/wissen/confluence/spaces") == 1)
check("wissen.groups_label steht in DE UND EN",
      (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8").count("'wissen.groups_label':") == 2)


# ════════════════════════════════════════════════════════════════════════════
section("6. i18n – REGEL ueber die im Code benutzten Schluessel")
I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
benutzt = set(re.findall(r"wissen\.(?:cfb_[a-z_]+|sec_cfbind(?:_desc)?)", HTML + JS))
check("es werden ueberhaupt Schluessel benutzt (Positivkontrolle)", len(benutzt) >= 20, f"{len(benutzt)}")
fehlt = [k for k in sorted(benutzt) if I18N.count("'" + k + "':") != 2]
check("jeder benutzte Schluessel steht in DE UND EN", not fehlt, ", ".join(fehlt))
tot = sorted(set(re.findall(r"'(wissen\.cfb_[a-z_]+)':", I18N)) - benutzt)
check("kein toter cfb-Schluessel mehr in i18n.js", not tot, ", ".join(tot))


# ════════════════════════════════════════════════════════════════════════════
section("7. Der Hinweis: der Abgleich LAEUFT jetzt (Vorgabe 2026-09-27)")
check("⚠ die Warnung 'noch nicht produktiv' ist weg",
      "wissen.cfb_soon" not in HTML and "'wissen.cfb_soon'" not in I18N and "wi-cfb-soon" not in HTML)
m = re.search(r"'wissen\.cfb_sync_hint':\s*'([^']*)'", I18N)
DE = m.group(1) if m else ""
check("der Hinweis nennt den Wissensabgleich und den Takt", "Wissensabgleich" in DE and "5 Minuten" in DE, DE[:80])
check("⚠ und sagt, dass Abgewaehltes wieder verschwindet", "verschwinden" in DE)
mm = re.search(r'data-i18n="wissen\.cfb_sync_hint">([^<]*)<', HTML)
check("das Rueckfall-Markup traegt denselben Text wie DE",
      bool(mm) and mm.group(1) == DE, (mm.group(1)[:50] if mm else "kein Markup"))
mm = re.search(r'data-i18n="wissen\.cfb_tree_hint">([^<]*)<', HTML)
mt = re.search(r"'wissen\.cfb_tree_hint':\s*'([^']*)'", I18N)
check("die Bedienhilfe am Baum: Markup = DE",
      bool(mm) and bool(mt) and mm.group(1) == mt.group(1))


# ════════════════════════════════════════════════════════════════════════════
section("8. Tags je Eintrag (Vorgabe 2026-09-27)")
T = cfb._tags_pruefen
check("None = kein Filter", sicher(T, None) == [])
check("leere Liste = kein Filter", sicher(T, []) == [])
check("⚠ klein geschrieben, fuehrendes # weg, getrimmt, Dubletten zusammengefasst",
      sicher(T, [" Handbuch ", "#freigegeben", "HANDBUCH", "", "  "]) == ["handbuch", "freigegeben"],
      str(sicher(T, [" Handbuch ", "#freigegeben", "HANDBUCH", "", "  "])))
check("Reihenfolge bleibt", sicher(T, ["b", "a", "c"]) == ["b", "a", "c"])
check("⚠ ein String ist keine Liste (sonst ein Tag je Buchstabe)",
      isinstance(sicher(T, "handbuch"), cfb.BindungFehler))
check("ein Nicht-String in der Liste wird abgewiesen", isinstance(sicher(T, ["a", 5]), cfb.BindungFehler))
for boes in ["zwei worte", "a,b", "a;b", "tab\tx", "zeile\nx", "nul\x00x"]:
    check(f"⚠ Tag {boes!r} wird abgewiesen (Leerraum/Trenner/Steuerzeichen)",
          isinstance(sicher(T, [boes]), cfb.BindungFehler))
check("⚠ ein zu langer Tag wird ABGEWIESEN, nicht gekuerzt",
      isinstance(sicher(T, ["x" * (cfb.TAG_MAX + 1)]), cfb.BindungFehler))
check("ein Tag genau an der Grenze geht", sicher(T, ["x" * cfb.TAG_MAX]) == ["x" * cfb.TAG_MAX])
check("zu viele Tags werden abgewiesen",
      isinstance(sicher(T, [f"t{i}" for i in range(cfb.MAX_TAGS + 1)]), cfb.BindungFehler))
check("Sonderzeichen ohne Leerraum gehen durch (Confluence entscheidet selbst)",
      sicher(T, ["ä-ö_ü.1"]) == ["ä-ö_ü.1"])

et = sicher(cfb.hinzufuegen, [{"key": "TAGS", "start": True}], "x", ["technik"], None,
            ["Handbuch", "#Intern"])
check("(Positivkontrolle) Eintrag mit Tags angelegt", isinstance(et, dict), str(et))
check("⚠ die Tags stehen normiert im Eintrag", isinstance(et, dict) and et.get("tags") == ["handbuch", "intern"],
      str(et))
gespeichert = json.loads(cfb._pfad().read_text(encoding="utf-8"))["bereiche"]
check("⚠ und in der Ablage", any(b.get("tags") == ["handbuch", "intern"] for b in gespeichert), str(gespeichert))
check("hinzufuegen OHNE Tags legt die leere Liste ab",
      (sicher(cfb.hinzufuegen, [{"key": "OHNE", "start": True}], "x", ["technik"]) or {}).get("tags") == [])
check("ungueltige Tags verhindern das Anlegen (nichts geschrieben)",
      isinstance(sicher(cfb.hinzufuegen, [{"key": "B", "start": True}], "x", ["technik"], None, ["a b"]),
                 cfb.BindungFehler)
      and not any(b.get("name") == "B" for b in cfb.liste()))
ga = sicher(cfb.aendern, et["id"] if isinstance(et, dict) else "", [{"key": "TAGS", "start": True}], "y",
            ["technik"], None, ["neu"])
check("⚠ aendern ERSETZT die Tags", isinstance(ga, dict) and ga.get("tags") == ["neu"], str(ga))
gb = sicher(cfb.aendern, et["id"] if isinstance(et, dict) else "", [{"key": "TAGS", "start": True}], "y",
            ["technik"])
check("⚠ aendern ohne Tags hebt den Filter auf (die Oberflaeche schickt immer den ganzen Eintrag)",
      isinstance(gb, dict) and gb.get("tags") == [], str(gb))
check("liste() liefert Tags je Eintrag", all(isinstance(b.get("tags"), list) for b in cfb.liste()))
for b in cfb.liste():
    cfb.entfernen(b["id"])

roh = json.dumps({"version": 1, "bereiche": [
    {"id": "t1", "typ": "auswahl", "name": "vorher", "gruppen": ["technik"],
     "auswahl": [{"key": "A", "start": True}]},
    {"id": "t2", "typ": "auswahl", "name": "kaputt", "gruppen": ["technik"],
     "auswahl": [{"key": "A", "start": True}], "tags": "handbuch"}]})
cfb._pfad().write_text(roh, encoding="utf-8")
ll = cfb.liste()
check("Eintrag von vor den Tags: kein Filter", len(ll) == 2 and ll[0].get("tags") == [] and not ll[0].get("tags_ungueltig"))
check("⚠ kaputte Tag-Angabe wird MARKIERT, nicht zu 'kein Filter' gelesen",
      len(ll) == 2 and ll[1].get("tags_ungueltig") is True, str(ll[1] if len(ll) > 1 else ll))
check("das Lesen schreibt die Ablage nicht um", cfb._pfad().read_text(encoding="utf-8") == roh)
cfb._pfad().unlink()

# Endpunkte: die Tags gehen durch die gemeinsame Pruefung und werden gespeichert.
lf = rufe(LESEN)
i_tag, i_sicht = pos(lf, "_tags_pruefen"), pos(lf, "_wissen_visible_spaces")
check("⚠ die Tags werden in _cfb_auswahl_lesen geprueft", i_tag >= 0, str(lf))
check("⚠ billig vor teuer: Tags VOR dem Confluence-Abruf", 0 <= i_tag < i_sicht, f"{i_tag}/{i_sicht}")
_tp = next((n for n in ast.walk(LESEN) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "_tags_pruefen"), None) if LESEN else None
check("die Tags kommen aus body['tags']",
      _tp is not None and "body.get('tags')" in ast.unparse(_tp), ast.unparse(_tp) if _tp else "")
_ret = [n for n in ast.walk(LESEN) if isinstance(n, ast.Return) and isinstance(n.value, ast.Tuple)
        and isinstance(n.value.elts[0], ast.Constant) and n.value.elts[0].value is None] if LESEN else []
check("die Erfolgsrueckgabe traegt die GEPRUEFTEN Tags",
      len(_ret) == 1 and isinstance(_ret[0].value.elts[-1], ast.Name) and _ret[0].value.elts[-1].id == "tags",
      ast.unparse(_ret[0]) if _ret else "keine")
for nm, k, schreib in [("POST", POST, "hinzufuegen"), ("PUT", PUT, "aendern")]:
    call = next((n for n in ast.walk(k) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Attribute) and n.func.attr == schreib), None) if k else None
    argn = [a.id for a in (call.args if call else []) if isinstance(a, ast.Name)]
    check(f"⚠ {nm}: die geprueften Tags werden an {schreib} UEBERGEBEN", "tags" in argn, str(argn))
    zuw = [n for n in ast.walk(k) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Await)
           and "_cfb_auswahl_lesen" in ast.unparse(n.value)] if k else []
    check(f"{nm}: tags stammt aus _cfb_auswahl_lesen (nicht aus dem Rumpf)",
          len(zuw) == 1 and "tags" in ast.unparse(zuw[0].targets[0]) and "body.get('tags')" not in rumpf(k))
mm = re.search(r'data-i18n="wissen\.cfb_tags_hint">([^<]*)<', HTML)
mt = re.search(r"'wissen\.cfb_tags_hint':\s*'([^']*)'", I18N)
check("der Tag-Hinweis: Markup = DE", bool(mm) and bool(mt) and mm.group(1) == mt.group(1))
check("⚠ der Hinweis sagt, was OHNE Tags passiert", bool(mt) and "Ohne Tags" in mt.group(1))


# ── Aufraeumen ──────────────────────────────────────────────────────────────
import shutil  # noqa: E402
shutil.rmtree(SAND, ignore_errors=True)
nachher = ECHT.read_bytes() if ECHT.is_file() else None
check("⚠ der echte Bestand ist unveraendert", nachher == ECHT_VORHER)

print(f"\n\033[1mErgebnis: {OK}/{OK + FAIL}\033[0m")
sys.exit(1 if FAIL else 0)
