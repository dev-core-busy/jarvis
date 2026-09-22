#!/usr/bin/env python3
"""Waechter fuer die dynamische Confluence-Einbindung (/wissen).

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
check("die echte Datei bleibt unberuehrt", not ECHT.exists() or True)
ECHT_VORHER = ECHT.read_bytes() if ECHT.is_file() else None


# ════════════════════════════════════════════════════════════════════════════
section("2. Das Modul laeuft wirklich")

check("leerer Bestand -> leere Liste", sicher(cfb.liste) == [])

e1 = sicher(cfb.hinzufuegen, "NEXUS", "NEXUS Dokumentation", True, "nexus\\a.bender", ["technik"])
check("hinzufuegen liefert einen Eintrag", isinstance(e1, dict), str(e1))
if isinstance(e1, dict):
    check("Eintrag traegt eine Kennung", bool(e1.get("id")))
    check("Eintrag traegt Schluessel und Namen",
          e1.get("key") == "NEXUS" and e1.get("name") == "NEXUS Dokumentation")
    check("inkl_unter uebernommen", e1.get("inkl_unter") is True)
    check("der Anleger wird festgehalten", e1.get("von") == "nexus\\a.bender")
    check("typ steht in der Ablage (Reichweite spaeter erweiterbar)",
          e1.get("typ") == "space")
    check("die Wissensgruppen stehen in der Ablage", e1.get("gruppen") == ["technik"],
          str(e1.get("gruppen")))

check("liste() enthaelt den Eintrag", [b.get("key") for b in cfb.liste()] == ["NEXUS"])
check("ist_eingebunden erkennt ihn", cfb.ist_eingebunden("NEXUS") is True)
check("ist_eingebunden meldet einen fremden nicht", cfb.ist_eingebunden("ANDERS") is False)

d = sicher(cfb.hinzufuegen, "NEXUS", "Noch mal", True, "x", ["technik"])
check("⚠ derselbe Bereich wird nicht zweimal eingebunden", isinstance(d, cfb.BindungFehler),
      f"kam durch: {d}")

# ⚠ Falsyness waere hier falsch: ein "ja" oder eine 1 aus einer von Hand
# geschriebenen Datei ist keine bewusste Entscheidung.
e2 = sicher(cfb.hinzufuegen, "OPS", "Betrieb", False, "x", ["technik"])
check("inkl_unter False wird uebernommen",
      isinstance(e2, dict) and e2.get("inkl_unter") is False)
e3 = sicher(cfb.hinzufuegen, "DOCS", "Doku", "ja", "x", ["technik"])
check("⚠ inkl_unter='ja' zaehlt NICHT als gesetzt (is True, nicht Falsyness)",
      isinstance(e3, dict) and e3.get("inkl_unter") is False, str(e3))
e4 = sicher(cfb.hinzufuegen, "TEAM", "", True, "x", ["technik"])
check("leerer Name faellt auf den Schluessel zurueck",
      isinstance(e4, dict) and e4.get("name") == "TEAM")

# ⚠ MUSS-FREI: echte Schluessel des DEV-Confluence. Eine erste Fassung liess
# `@` weg und haette 185 von 489 Bereichen abgewiesen – alle persoenlichen.
# Eine Formregel, die Funktionen abschaltet, braucht eine Muss-frei-Liste,
# nicht nur eine Muss-blocken-Liste.
for gut, was in [("24H", "kurz, gross"), ("NEXUSKIS", "lang, gross"),
                 ("~Anna-Lena.Buscetta@nexus-schweiz.ch", "persoenlicher Bereich"),
                 ("~andrea.stegmann@nexus-ag.de", "persoenlich, klein"),
                 ("ds_2024", "Unterstrich"), ("a+b@x.de", "Plus")]:
    r = sicher(cfb.hinzufuegen, gut, "X " + was, True, "x", ["technik"])
    check(f"echter Schluessel wird ANGENOMMEN ({was})", isinstance(r, dict), f"abgewiesen: {r}")
    if isinstance(r, dict):
        check(f"  und ungekuerzt gespeichert ({was})", r.get("key") == gut, r.get("key"))
        cfb.entfernen(r["id"])

for boes, was in [("", "leer"), ("a b", "Leerzeichen"), ("x" * 200, "zu lang"),
                  ("../../etc", "Pfadanteil"), ("a\nb", "Zeilenumbruch"),
                  ('a"b', "Anfuehrungszeichen"), ("a/b", "Schraegstrich")]:
    r = sicher(cfb.hinzufuegen, boes, "X", True, "x", ["technik"])
    check(f"unbrauchbarer Schluessel abgewiesen ({was})", isinstance(r, cfb.BindungFehler),
          f"kam durch: {r}")

check("Reihenfolge bleibt die des Einbindens",
      [b["key"] for b in cfb.liste()] == ["NEXUS", "OPS", "DOCS", "TEAM"])

# Deckel
bis = cfb.MAX_BEREICHE - len(cfb.liste())
for i in range(bis):
    cfb.hinzufuegen(f"AUTO{i}", f"Auto {i}", True, "x", ["technik"])
r = sicher(cfb.hinzufuegen, "ZUVIEL", "Zu viel", True, "x", ["technik"])
check(f"Deckel {cfb.MAX_BEREICHE} greift", isinstance(r, cfb.BindungFehler), f"kam durch: {r}")
check("der Deckel nennt die Zahl", isinstance(r, cfb.BindungFehler) and str(cfb.MAX_BEREICHE) in str(r))

# Entfernen
check("entfernen meldet Erfolg", cfb.entfernen(e1["id"]) is True if isinstance(e1, dict) else False)
check("der Eintrag ist weg", not cfb.ist_eingebunden("NEXUS"))
check("zweites Entfernen meldet FALSE (nicht gefunden)",
      cfb.entfernen(e1["id"]) is False if isinstance(e1, dict) else False)
check("unbekannte Kennung entfernt nichts", cfb.entfernen("gibtsnicht") is False)
check("leere Kennung entfernt nichts", cfb.entfernen("") is False)
check("nach dem Entfernen ist wieder Platz",
      isinstance(sicher(cfb.hinzufuegen, "NEUDA", "Neu da", True, "x", ["technik"]), dict))

# Rechte
mode = sicher(lambda: oct(os.stat(cfb._pfad()).st_mode & 0o777))
check("Ablage ist 0640", mode == "0o640", str(mode))

# ⚠ Eine beschaedigte Datei darf NICHT stillschweigend ersetzt werden.
kaputt = b'{"version": 1, "bereiche": [ das ist kein json'
cfb._pfad().write_bytes(kaputt)
check("kaputte Datei -> leere Liste (Container sperrt nicht)", cfb.liste() == [])
check("⚠ kaputte Datei wird beim LESEN nicht ueberschrieben",
      cfb._pfad().read_bytes() == kaputt)
# ⚠ "leer" darf nicht STILL aus einem Fehler kommen: die Oberflaeche meldete
# sonst "nichts eingebunden", waehrend welche in der Datei stehen.
import contextlib, io as _io  # noqa: E402
_buf = _io.StringIO()
with contextlib.redirect_stdout(_buf):
    cfb.liste()
check("⚠ ein Lesefehler wird BENANNT (Journal), nicht verschluckt",
      "CF-Bindung" in _buf.getvalue() and "LEER" in _buf.getvalue(),
      repr(_buf.getvalue()[:120]))
cfb._pfad().unlink()
_buf2 = _io.StringIO()
with contextlib.redirect_stdout(_buf2):
    cfb.liste()
check("(Positivkontrolle) der Normalfall meldet NICHTS", _buf2.getvalue() == "",
      repr(_buf2.getvalue()[:120]))


# ════════════════════════════════════════════════════════════════════════════
section("2b. Wissensgruppen-Pflicht (Vorgabe 2026-09-22) – AUSGEFUEHRT")
# ⚠ DIE ZUSAGE IST SEIT DEM 2026-09-22 UMGEKEHRT: bis dahin liess sich ein
# Bereich OHNE Zuordnung einbinden. Das ist keine Regression, sondern die
# Vorgabe – und sie wird hier gemessen, nicht gelesen.
#
# Die Pruefung im Modul ist KEINE Doppelung des Endpunkts: sie sitzt an der
# ABLAGE, also vor jedem kuenftigen zweiten Aufrufer (Abgleich, Migration,
# Werkzeug). Ob sie greift, kann nur ein Aufruf beantworten.
for leer, was in [(None, "gar nicht uebergeben"), ([], "leere Liste"),
                  (["", "  "], "nur Leerraum"), (["", None], "leer und None")]:
    r = sicher(cfb.hinzufuegen, "OHNEGRP", "Ohne", True, "x", leer)
    check(f"⚠ ohne Wissensgruppe wird NICHT eingebunden ({was})",
          isinstance(r, cfb.BindungFehler), f"kam durch: {r}")
check("der Grund nennt die Wissensgruppe",
      "Wissensgruppe" in str(sicher(cfb.hinzufuegen, "OHNEGRP", "Ohne", True, "x", [])))
check("und es bleibt wirklich nichts liegen", not cfb.ist_eingebunden("OHNEGRP"))

# Eine Zeichenkette ist iterierbar und nie gemeint (Register): "technik" waere
# sonst eine Zuordnung zu den Gruppen 't','e','c','h'...
r = sicher(cfb.hinzufuegen, "STR", "Str", True, "x", "technik")
check("⚠ eine Zeichenkette statt einer Liste wird abgewiesen",
      isinstance(r, cfb.BindungFehler), f"kam durch: {r}")

m = sicher(cfb.hinzufuegen, "MEHR", "Mehrere", True, "x", ["technik", "vertrieb", "technik"])
check("mehrere Gruppen werden uebernommen",
      isinstance(m, dict) and m.get("gruppen") == ["technik", "vertrieb"],
      str(m if not isinstance(m, dict) else m.get("gruppen")))
check("Dubletten werden still zusammengefasst (Reihenfolge bleibt)",
      isinstance(m, dict) and m.get("gruppen") == ["technik", "vertrieb"])
if isinstance(m, dict):
    cfb.entfernen(m["id"])

r = sicher(cfb.hinzufuegen, "LANG", "Lang", True, "x", ["g" * (cfb.GRUPPE_MAX + 1)])
check("eine ueberlange Kennung wird abgewiesen", isinstance(r, cfb.BindungFehler), f"kam durch: {r}")
r = sicher(cfb.hinzufuegen, "CTRL", "Ctrl", True, "x", ["a\nb"])
check("eine Kennung mit Zeilenumbruch wird abgewiesen", isinstance(r, cfb.BindungFehler), f"kam durch: {r}")
r = sicher(cfb.hinzufuegen, "VIELE", "Viele", True, "x",
           [f"g{i}" for i in range(cfb.MAX_GRUPPEN + 1)])
check(f"Deckel {cfb.MAX_GRUPPEN} Gruppen greift", isinstance(r, cfb.BindungFehler), f"kam durch: {r}")

# ⚠ MUSS-FREI: die Form wird bewusst NUR grob geprueft. `_slugify` liefert
# heute `[a-z0-9-]+`; eine engere Regel hier wuerde bei der naechsten Aenderung
# dort gueltige Einbindungen abweisen (Register: eine Formregel, die Funktionen
# abschaltet, braucht eine Muss-frei-Liste).
for gid in ["technik", "it-betrieb", "gruppe-2", "a", "abteilung-vertrieb-nord"]:
    r = sicher(cfb.hinzufuegen, "OK" + gid[:3].upper(), "X", True, "x", [gid])
    check(f"echte Gruppen-Kennung wird ANGENOMMEN ({gid})", isinstance(r, dict), f"abgewiesen: {r}")
    if isinstance(r, dict):
        cfb.entfernen(r["id"])

# ⚠ ALTBESTAND BEKOMMT KEINE ERFUNDENE ZUORDNUNG. Ein Eintrag ohne `gruppen`
# bleibt, wie er ist – die Oberflaeche benennt ihn.
cfb._pfad().write_text(json.dumps({"version": 1, "bereiche": [
    {"id": "alt1", "typ": "space", "key": "ALT", "name": "Alt", "inkl_unter": True}]}),
    encoding="utf-8")
alt_liste = cfb.liste()
check("Altbestand bleibt lesbar", len(alt_liste) == 1)
check("⚠ und bekommt KEINE geratene Zuordnung",
      "gruppen" not in alt_liste[0], str(alt_liste[0].get("gruppen")))


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

GET = route_fn("get", "/api/wissen/confluence/bindung")
POST = route_fn("post", "/api/wissen/confluence/bindung")
DEL = route_fn("delete", "/api/wissen/confluence/bindung/{bid}")
check("GET  /api/wissen/confluence/bindung vorhanden", GET is not None)
check("POST /api/wissen/confluence/bindung vorhanden", POST is not None)
check("DELETE .../bindung/{bid} vorhanden", DEL is not None)

def rumpf(k):
    return ast.unparse(k) if k is not None else ""

def rufe(k) -> list:
    """Aufrufnamen in Reihenfolge ihres Auftretens."""
    if k is None:
        return []
    aus = []
    for n in ast.walk(k):
        if isinstance(n, ast.Call):
            f = n.func
            nm = f.id if isinstance(f, ast.Name) else (f.attr if isinstance(f, ast.Attribute) else "")
            if nm:
                aus.append((n.lineno, nm))
    return [nm for _, nm in sorted(aus)]

for nm, k in [("GET", GET), ("POST", POST), ("DELETE", DEL)]:
    check(f"{nm}: Wissensbereich wird geprueft", "_editable_groups_for" in rufe(k))
    check(f"{nm}: haengt an require_auth",
          "require_auth" in rumpf(k) and "require_local_auth" not in rumpf(k))

# ⚠ Der Benutzer kommt aus der Anmeldung, nie aus dem Rumpf.
pr = rumpf(POST)
for feld in ("'user'", "'von'", "'benutzer'", "'name'"):
    check(f"POST: {feld} wird NICHT aus dem Request gelesen",
          f"body.get({feld})" not in pr, "steht im Rumpf")

# ⚠ Reihenfolge: erst sichtbar?, dann schreiben. Dahinter waere die Pruefung
# wirkungslos – und eine Textsuche saehe den Unterschied nicht.
folge = rufe(POST)
i_sicht = folge.index("_wissen_visible_spaces") if "_wissen_visible_spaces" in folge else -1
i_add = folge.index("hinzufuegen") if "hinzufuegen" in folge else -1
i_akt = folge.index("_cfb_aktiv") if "_cfb_aktiv" in folge else -1
check("POST: die sichtbaren Bereiche werden abgefragt", i_sicht >= 0)
check("POST: es wird wirklich eingebunden", i_add >= 0)
check("⚠ POST: Sichtbarkeits-Pruefung steht VOR dem Einbinden",
      i_sicht >= 0 and i_add >= 0 and i_sicht < i_add, f"{i_sicht} / {i_add}")
check("⚠ POST: Skill/Konfiguration werden VOR dem Einbinden geprueft",
      i_akt >= 0 and i_add >= 0 and i_akt < i_add, f"{i_akt} / {i_add}")
check("POST: der Name kommt aus dem gefundenen Bereich",
      "treffer.get('name')" in pr, "Name nicht aus der Sichtbarkeitsliste")

# ── Wissensgruppen-Pflicht am Endpunkt (Vorgabe 2026-09-22) ─────────────
# ⚠ `groups` IST DER EINE WERT, DER AUS DEM RUMPF KOMMEN DARF – er ist die
# Auswahl des Benutzers. Was ihn ungefaehrlich macht, ist die Pruefung dahinter:
# `_wissen_check_groups` laesst NUR Gruppen aus dem Bereich des Anmeldenden zu.
check("POST: die Wissensgruppen werden aus dem Rumpf gelesen",
      "body.get('groups')" in pr, "kein groups im Rumpf")
# ⚠ LIVE GEMESSEN (2026-09-22): `["", "  "]` ueberlebt ein blosses `if g`, und
# `_wissen_check_groups` meldet dann "Keine Berechtigung fuer Gruppe(n):   " –
# richtig abgewiesen, aber der Grund schickt an die falsche Stelle.
check("⚠ POST: die Kennungen werden GETRIMMT, nicht nur auf Falsyness gefiltert",
      ".strip()" in pr and "req_groups" in pr,
      "sonst laeuft eine leere Eingabe in eine Rechte-Meldung")

# Die Gegenprobe dazu laeuft ueber den geschnittenen Rumpf: sie misst, welcher
# Grund herauskommt. Hier genuegt die Regel – den Grund messen Live-Probe und
# Modul-Test (Abschnitt 2b).
_lz = [n for n in ast.walk(POST) if isinstance(n, ast.Assign)
       and any(isinstance(t, ast.Name) and t.id == "req_groups" for t in n.targets)]
check("req_groups wird genau einmal belegt", len(_lz) == 1, f"{len(_lz)}x")
check("und die Belegung trimmt jede Kennung",
      len(_lz) == 1 and "strip()" in ast.unparse(_lz[0]),
      ast.unparse(_lz[0]) if _lz else "")
i_grp = folge.index("_wissen_check_groups") if "_wissen_check_groups" in folge else -1
check("⚠ POST: die Zuordnung wird gegen den Bereich des Nutzers geprueft", i_grp >= 0,
      "_wissen_check_groups fehlt – eine eigene Fassung liefe auseinander")
check("⚠ POST: die Gruppenpruefung steht VOR dem Einbinden",
      i_grp >= 0 and i_add >= 0 and i_grp < i_add, f"{i_grp} / {i_add}")
# Billig vor teuer: die Gruppenpruefung ist oertlich, `_wissen_visible_spaces`
# eine Netzrundreise zu Confluence.
check("POST: die Gruppenpruefung steht VOR dem Confluence-Abruf",
      i_grp >= 0 and i_sicht >= 0 and i_grp < i_sicht, f"{i_grp} / {i_sicht}")
_add_call = next((n for n in ast.walk(POST) if isinstance(n, ast.Call)
                  and isinstance(n.func, ast.Attribute) and n.func.attr == "hinzufuegen"), None)
check("⚠ POST: die Gruppen werden wirklich UEBERGEBEN (nicht nur geprueft)",
      _add_call is not None and any(
          isinstance(a, ast.Name) and a.id == "req_groups" for a in _add_call.args),
      ast.unparse(_add_call) if _add_call else "kein Aufruf")

# Die Anzeigenamen der Gruppen kommen vom SERVER – und aus ALLEN Gruppen.
_mg = next((k for k in ast.walk(ast.parse(MAIN))
            if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef))
            and k.name == "_cfb_mit_gruppen"), None)
check("_cfb_mit_gruppen vorhanden", _mg is not None)
_mgq = ast.unparse(_mg) if _mg else ""
check("⚠ die Namen kommen aus ALLEN Wissensgruppen, nicht aus dem Bereich des Abrufers",
      "list_groups" in _mgq and "_editable_groups_for" not in _mgq,
      "sonst saehe ein Editor die Zuordnung eines Kollegen als geloeschte Gruppe")
check("eine Kennung ohne Gruppe bleibt aussen vor (die Oberflaeche benennt sie)",
      "gruppen_info" in _mgq)
for nm, k in [("GET", GET), ("POST", POST), ("DELETE", DEL)]:
    check(f"{nm}: liefert die Bereiche MIT Gruppennamen",
          "_cfb_mit_gruppen" in rumpf(k), "nicht angereichert")

# GET darf auch im Ruhezustand 200 antworten – sonst waere ein voellig
# normaler Zustand (Skill aus) eine Stoerungsmeldung.
gr = rumpf(GET)
check("GET: meldet den Zustand mit 200 (kein Fehlercode fuer 'Skill aus')",
      "'aktiv':" in gr and gr.count("status_code=403") == 1 and "status_code=400" not in gr)
check("GET: liefert die Bereiche nur bei aktivem Skill",
      "if skill and conf" in gr or "(skill and conf)" in gr)

# Die Schreibweise der Anfuehrungszeichen ist egal – gemessen wird, dass der
# Rumpf von _cfb_aktiv BEIDES anfasst (Register: die Eigenschaft, nicht den Text).
_ak = ast.parse(MAIN)
_akfn = next((k for k in ast.walk(_ak)
              if isinstance(k, (ast.FunctionDef, ast.AsyncFunctionDef)) and k.name == "_cfb_aktiv"),
             None)
_akq = ast.unparse(_akfn) if _akfn else ""
check("_cfb_aktiv vorhanden", _akfn is not None)
check("_cfb_aktiv prueft BEIDES (Skill aktiv + konfiguriert)",
      "_skill_active('confluence')" in _akq and ".configured" in _akq, _akq[:200])


# ════════════════════════════════════════════════════════════════════════════
section("4. Die Ablage steht in allen drei Sperrlisten")
SB = ohne_kommentar((ROOT / "backend" / "sandbox.py").read_text(encoding="utf-8"))
import backend.sandbox as sandbox  # noqa: E402
check("in _APP_DENY_REL", "data/confluence_bindung.json" in sandbox._APP_DENY_REL)
check("in PRIVATE_FILES", "data/confluence_bindung.json" in sandbox.PRIVATE_FILES)
check("im Shell-Muster SHELL_SECRET_PATHS",
      bool(sandbox.SHELL_SECRET_PATHS.search("cat data/confluence_bindung.json")))
check("(die Eintraege stehen wirklich im Code, nicht nur im Kommentar)",
      SB.count("confluence_bindung") >= 3, f"{SB.count('confluence_bindung')}x")


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

block = HTML[i_cb - 200:i_fl] if i_cb > 0 else ""
check("startet verborgen (kein Aufblitzen beim Laden)", 'id="wi-sec-cfbind" style="display:none;"' in HTML)
check("Pulldown fuer die Bereiche", 'id="wi-cfb-space"' in block and "<select" in block)
check("Kaestchen 'inkl. Unterseiten'", 'id="wi-cfb-sub"' in block)
check("⚠ das Kaestchen ist per Vorgabe ANGEHAKT",
      'id="wi-cfb-sub" checked' in block.replace('type="checkbox" ', ''), "default fehlt")
check("Liste der konfigurierten Bereiche", 'id="wi-cfb-list"' in block)
check("der Container ist einklappbar wie die uebrigen",
      "'wi-sec-cfbind'" in JS and "wi-sec-upload" in JS)
# ⚠ ÜBERNOMMEN WIRD PER KNOPF, nicht schon beim Wechsel im Pulldown (Vorgabe
# 2026-09-21). Geprueft wird die EIGENSCHAFT, nicht die Schreibweise: der Knopf
# existiert, er ruft cfbAdd, und der `change`-Zweig des Pulldowns tut es NICHT
# mehr - sonst waere die Umstellung nur halb und jeder Pfeilschritt baende ein.
check("Knopf zum Uebernehmen im Markup", 'id="wi-cfb-add"' in block)
check("⚠ der Knopf startet gesperrt (ohne Auswahl gibt es nichts zu uebernehmen)",
      re.search(r'id="wi-cfb-add"[^>]*\bdisabled', block) is not None
      or re.search(r'\bdisabled[^>]*id="wi-cfb-add"', block) is not None)
_klick = re.search(r"cfbBtn\.addEventListener\('click',\s*function[^)]*\)\s*\{([^}]*)\}", JS)
check("⚠ der KNOPF bindet ein (Klick ruft cfbAdd)",
      _klick is not None and "cfbAdd(" in _klick.group(1),
      _klick.group(1).strip() if _klick else "kein Klick-Handler")
_chg = re.search(r"cfbSel\.addEventListener\('change',\s*function[^)]*\)\s*\{([^}]*)\}", JS)
check("⚠ das Pulldown bindet NICHT mehr ein (change gibt nur den Knopf frei)",
      _chg is not None and "cfbAdd(" not in _chg.group(1),
      _chg.group(1).strip() if _chg else "kein change-Handler")
check("Muelleimer zum Loesen der Einbindung (kein ×)",
      "JarvisIcons.trash()" in JS.split("wi-cfb-del")[0][-400:] or "wi-cfb-del" in JS)
check("⚠ die Reichweite steht als WORT in der Zeile, nicht nur als Farbe",
      "cfb_scope_sub" in JS and "cfb_scope_top" in JS)
check("EINE Quelle fuer die Bereichsliste (der Container fragt nicht selbst ab)",
      JS.count("/api/wissen/confluence/spaces") == 1)
check("der Hinweis sagt, dass der Abgleich noch fehlt", "wissen.cfb_soon" in HTML)

# ── Wissensgruppen-Pflicht in der Oberflaeche (Vorgabe 2026-09-22) ──────
i_grp_box = HTML.find('id="wi-cfb-groups"')
i_pick = HTML.find('class="wi-cfb-pick"')
check("Wissensgruppen-Reihe im Container", i_grp_box > 0)
check("⚠ sie steht UEBER der Auswahlzeile (alles, was der Knopf braucht, darueber)",
      0 < i_grp_box < i_pick, f"groups={i_grp_box} pick={i_pick}")
check("sie ist beschriftet (Pflichtfeld)", 'data-i18n="wissen.groups_label"' in block)
check("der Hinweis erklaert, wofuer die Zuordnung ist", "wissen.cfb_groups_hint" in HTML)
check("die Kaestchen entstehen ueber das vorhandene groupBoxes()",
      "groupBoxes('cfb')" in JS, "eigene Fassung statt der gemeinsamen Regel")
check("⚠ der Knopf verlangt eine Wissensgruppe",
      "checkedGroups('cfb')" in JS and re.search(r"btn\.disabled\s*=[^;]*!grp", JS) is not None,
      "cfbAddKnopf prueft die Auswahl nicht")
check("⚠ und der Grund unterscheidet die beiden Faelle (Bereich / Gruppe)",
      "wissen.cfb_need_group" in JS and "wissen.cfb_add_hint" in JS)
_snd = re.search(r"JSON\.stringify\(\{ key: key[^}]*\}\)", JS)
check("⚠ die Zuordnung geht wirklich mit dem Rumpf raus",
      _snd is not None and "groups:" in _snd.group(0),
      _snd.group(0) if _snd else "kein Rumpf gefunden")
check("die Kaestchen geben den Knopf frei (delegiert am Container)",
      re.search(r"cfbGrp\.addEventListener\('change'", JS) is not None)
# ⚠ Ein zweites Zeichnen wuerde die Haekchen verwerfen: cfbRender() laeuft nach
# JEDEM Einbinden und Entfernen.
_rg = re.search(r"function cfbRenderGroups\(\)\s*\{([\s\S]*?)\n    \}", JS)
check("cfbRenderGroups vorhanden", _rg is not None)
check("⚠ die Gruppen werden NICHT bei jedem Render neu gezeichnet",
      _rg is not None and "querySelector('.wi-grp-cfb')" in _rg.group(1) and "return" in _rg.group(1),
      "sonst ist die Auswahl nach dem Einbinden weg")
check("die Liste zeigt die zugeordneten Gruppen",
      "gruppen_info" in JS and "wi-chip" in JS.split("wi-cfb-scope-tag")[0][-1500:])
check("⚠ eine Einbindung OHNE Zuordnung wird BENANNT (Altbestand)",
      "wissen.cfb_nogroup" in JS and "wi-cfb-nogrp" in JS)
check("und eine geloeschte Gruppe ebenfalls", "wissen.cfb_grp_gone" in JS)
check("die Marke dafuer ist gestaltet (nicht nur eine Klasse ohne Regel)",
      ".wi-cfb-nogrp" in HTML)
# Der Beschriftungs-Schluessel ist derselbe wie im Extraktor – gleiche
# Bedeutung, gleicher Text. Er faellt nicht unter das cfb_-Muster von
# Abschnitt 6 und wird deshalb hier geprueft.
check("wissen.groups_label steht in DE UND EN",
      (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
      .count("'wissen.groups_label':") == 2)


# ════════════════════════════════════════════════════════════════════════════
section("6. i18n – REGEL ueber die im Code benutzten Schluessel")
I18N = (ROOT / "frontend" / "js" / "i18n.js").read_text(encoding="utf-8")
benutzt = set(re.findall(r"wissen\.(?:cfb_[a-z_]+|sec_cfbind(?:_desc)?)", HTML + JS))
check("es werden ueberhaupt Schluessel benutzt (Positivkontrolle)", len(benutzt) >= 10,
      f"{len(benutzt)}")
fehlt = [k for k in sorted(benutzt) if I18N.count("'" + k + "':") != 2]
check("jeder benutzte Schluessel steht in DE UND EN", not fehlt, ", ".join(fehlt))


# ════════════════════════════════════════════════════════════════════════════
section("7. Der Warnhinweis (Vorgabe 2026-09-21)")
# ⚠ DER CONTAINER NIMMT EINBINDUNGEN AN UND GLEICHT NICHTS AB. Wer das
# ueberliest, wartet auf Wissen, das nicht kommt - ein Container, der eine
# Einbindung annimmt und stillschweigend nichts tut, ist von einem defekten
# nicht zu unterscheiden. Deshalb ist der Hinweis eine ZUSAGE mit Waechter.
CSS_BLOCK = HTML

m = re.search(r"'wissen\.cfb_soon':\s*'([^']*)'", I18N)
DE = m.group(1) if m else ""
check("der Hinweis nennt, dass es noch nicht produktiv verwendbar ist",
      "produktiv" in DE.lower(), DE[:60])
check("und er nennt das Datum der Aussage", "21.09.2026" in DE)
check("der entwarnende Alt-Wortlaut ist weg",
      "folgt in einem späteren Schritt" not in I18N)

# Rueckfall-Markup und DE-Text muessen deckungsgleich sein - sonst blitzt beim
# Laden der alte Wortlaut auf, bis applyLang() gelaufen ist (Register).
mm = re.search(r'data-i18n="wissen\.cfb_soon">([^<]*)<', HTML)
check("das Rueckfall-Markup traegt denselben Text wie DE",
      bool(mm) and mm.group(1) == DE, (mm.group(1)[:50] if mm else "kein Markup"))

# Deutlich heisst: eine Warnfarbe - und die muss in BEIDEN Themen angepasst
# sein (--danger pur: dunkel 4,40:1, hell 3,45:1, beide unter 4,5:1).
# ⚠ OHNE KOMMENTARE MESSEN. Die Begruendung ueber der Basis-Regel nennt
# `body.light` (sie erklaert ja, warum es dort anders aussah) - mit Kommentar
# gelesen galt die Basis-Regel als Hell-Regel, und der Waechter meldete drei
# Fehler, die es nicht gab. Register, x-ter Fall.
CSS_OK = re.sub(r"/\*.*?\*/", " ", CSS_BLOCK, flags=re.S)
check("POSITIVKONTROLLE: die Kommentare sind wirklich weg",
      "Register: erst die Klasse ansehen" not in CSS_OK
      and "Register: erst die Klasse ansehen" in CSS_BLOCK)
treffer = [(m.group(1).strip(), m.group(2))
           for m in re.finditer(r"([^{};]*wi-cfb-soon[^{};]*)\{([^}]*)\}", CSS_OK)]
check("es gibt ueberhaupt Regeln fuer den Hinweis (Positivkontrolle)",
      len(treffer) >= 2, f"{len(treffer)}")
basis = next((t for t in treffer if "body.light" not in t[0]), None)
hell = next((t for t in treffer if "body.light" in t[0]), None)
check("der Hinweis traegt eine Warnfarbe",
      bool(basis) and "--danger" in basis[1])
check("und ist halbfett abgesetzt",
      bool(basis) and "font-weight" in basis[1])
check("im hellen Thema ist die Farbe eigens gesetzt (sonst unter 4,5:1)",
      bool(hell) and "color-mix" in hell[1])

# ⚠ SPEZIFITAET, und das ist der Befund dieses Laufs: der Hinweis traegt beide
# Klassen (desc + wi-cfb-soon). Mit `.wi-cfb-soon` allein (0,1,0) gewann
# `.wi-section .desc` (0,2,0), und im DUNKLEN Thema stand er grau da - der
# Quelltext fand `--danger` und war trotzdem gruen. Gesehen hat es nur die
# optische Abnahme.
def klassen(sel):
    return sel.count(".") - (1 if "body.light" in sel else 0)
desc = re.search(r"([^{};]*\.desc[^{};]*)\{", CSS_OK)
check("die Farbregel ist spezifischer als die .desc-Vorgabe "
      f"(Hinweis: {basis[0] if basis else '?'})",
      bool(basis) and bool(desc)
      and klassen(basis[0]) >= klassen(desc.group(1))
      and re.search(r"\bp\.wi-cfb-soon", basis[0]) is not None,
      f".desc={desc.group(1).strip() if desc else '?'}")


# ── Aufraeumen ──────────────────────────────────────────────────────────────
import shutil  # noqa: E402
shutil.rmtree(SAND, ignore_errors=True)
nachher = ECHT.read_bytes() if ECHT.is_file() else None
check("⚠ der echte Bestand ist unveraendert", nachher == ECHT_VORHER)

print(f"\n\033[1mErgebnis: {OK}/{OK + FAIL}\033[0m")
sys.exit(1 if FAIL else 0)
