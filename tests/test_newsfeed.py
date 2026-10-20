#!/usr/bin/env python3
"""Waechter fuer den Newsfeed-Skill (backend/newsfeed.py + Endpunkte in main.py).

Die echten Funktionen werden AUSGEFUEHRT (im Sandkasten); die Rechte- und
Verdrahtungszusagen der Endpunkte stehen als REGEL ueber den AST von main.py
– main.py selbst ist nicht importierbar (es zieht die Live-Konfiguration).

Zusagen:
  1. Anlegen setzt Kennung und Erstellungsdatum SERVERSEITIG; ein mitgeschicktes
     `erstellt` wird nicht uebernommen; Bearbeiten laesst das Datum stehen.
  2. Gezeigt werden die DREI NEUESTEN, neueste zuerst.
  3. Leere/zu lange Felder und Einstellungen ausserhalb des Bereichs werden
     ABGEWIESEN (nicht still beschnitten); der Bestand bleibt dabei unveraendert.
  4. Ein unlesbarer Bestand wird nicht ueberschrieben (fail-closed).
  4b. Bearbeiten rueckt nach vorn (Stand); Deaktivieren nimmt aus der Anzeige,
     laesst den Stand stehen, nur Bearbeiten macht wieder aktiv.
  4c. Ausblenden je Benutzer bis zum GEZEIGTEN Stand; neue Meldung oder
     Bearbeitung zeigt wieder; Deaktivieren nicht.
  5. Endpunkte: Lesen haengt an require_auth + _skill_active("newsfeed") und
     antwortet bei aus mit 404 (NICHT 403 – das Portal meldet bei 403 ab);
     jede /api/newsfeed/admin-Route haengt an require_local_auth;
     /api/me liefert permissions.newsfeed aus dem Skill-Zustand.

⚠ SANDKASTEN MIT EXIT 2: der Lauf darf nie in `data/newsfeed.json` schreiben.

Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
"""

import ast
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

OK = FAIL = 0


def check(text, bed, info=""):
    global OK, FAIL
    if not isinstance(text, str) or isinstance(bed, str):
        print(f"ABBRUCH: check(text, bedingung) vertauscht: {text!r}")
        sys.exit(2)
    if bed:
        OK += 1
        print(f"  OK   {text}")
    else:
        FAIL += 1
        print(f"  FAIL {text}" + (f"  [{info}]" if info else ""))


def abbruch(grund):
    print(f"NICHT PRUEFBAR: {grund}")
    sys.exit(2)


def wirft(fn, *a, art=Exception):
    """True, wenn der Aufruf mit `art` scheitert – wirft selbst nie."""
    try:
        fn(*a)
    except art:
        return True
    except Exception:  # noqa: BLE001
        return False
    return False


try:
    from backend import newsfeed as nf
    from backend import atomar
except Exception as e:  # noqa: BLE001
    abbruch(f"backend.newsfeed nicht importierbar: {e}")

SANDKASTEN = Path(tempfile.mkdtemp(prefix="nf_test_"))
ECHT = (ROOT / "data" / "newsfeed.json").resolve()
nf.DATEI = SANDKASTEN / "newsfeed.json"
nf.AUSGEBLENDET_DATEI = SANDKASTEN / "newsfeed_ausgeblendet.json"
# Positivkontrolle: wirklich umgelenkt, sonst schriebe der Lauf in den Bestand.
for _ziel in (nf.DATEI, nf.AUSGEBLENDET_DATEI):
    if SANDKASTEN.resolve() not in _ziel.resolve().parents or _ziel.resolve().parent == ECHT.parent:
        abbruch(f"Ablage {_ziel} zeigt nicht in den Sandkasten")

try:
    print("\n1. Anlegen, Datum, Bearbeiten")
    a = nf.eintrag_speichern("", "  Wartung  ", "Am Freitag ist\n das System  kurz weg.")
    check("Kennung vergeben", bool(a.get("id")))
    check("Erstellungsdatum gesetzt (ISO)", len(a.get("erstellt", "")) >= 19)
    check("Leerraum zusammengefasst", a["text"] == "Am Freitag ist das System kurz weg.", a["text"])
    check("Titel getrimmt", a["titel"] == "Wartung", a["titel"])
    # Ein Client kann kein Datum setzen: die Funktion nimmt gar keines an.
    check("eintrag_speichern kennt keinen Datumsparameter",
          "erstellt" not in nf.eintrag_speichern.__code__.co_varnames[:nf.eintrag_speichern.__code__.co_argcount])
    alt_datum = a["erstellt"]
    # Datum kuenstlich zurueckdatieren, um „bleibt stehen" messbar zu machen.
    d = json.loads(nf.DATEI.read_text(encoding="utf-8"))
    d["eintraege"][0]["erstellt"] = "2020-01-01T00:00:00"
    nf.DATEI.write_text(json.dumps(d), encoding="utf-8")
    b = nf.eintrag_speichern(a["id"], "Wartung neu", "Text neu.")
    check("Bearbeiten aendert Titel", b["titel"] == "Wartung neu")
    check("Bearbeiten laesst Erstellungsdatum stehen", b["erstellt"] == "2020-01-01T00:00:00",
          f"{b['erstellt']} (vorher {alt_datum})")
    check("unbekannte Kennung wird abgewiesen",
          wirft(nf.eintrag_speichern, "gibtsnicht", "x", "y", art=nf.NewsfeedFehler))

    print("\n2. Die drei neuesten, neueste zuerst")
    d = json.loads(nf.DATEI.read_text(encoding="utf-8"))
    d["eintraege"] = [{"id": f"e{i}", "erstellt": f"2026-10-0{i}T10:00:00",
                       "titel": f"T{i}", "text": "x."} for i in range(1, 6)]
    nf.DATEI.write_text(json.dumps(d), encoding="utf-8")
    an = nf.anzeige()
    ids = [e["id"] for e in an["eintraege"]]
    check("genau ANZEIGE_ANZAHL Eintraege", len(ids) == nf.ANZEIGE_ANZAHL == 3, str(ids))
    check("neueste zuerst", ids == ["e5", "e4", "e3"], str(ids))
    check("alle(): ebenfalls neueste zuerst, vollstaendig",
          [e["id"] for e in nf.alle()] == ["e5", "e4", "e3", "e2", "e1"])
    check("Anzeige traegt Vorgabe-Verweilzeit 3 s", an.get("verweil_s") == 3.0, str(an.get("verweil_s")))
    check("Anzeige traegt Scrolldauer", an.get("scroll_s") == nf.SCROLL_VORGABE)

    print("\n3. Abweisen statt beschneiden")
    vorher = nf.DATEI.read_bytes()
    check("leerer Titel abgewiesen", wirft(nf.eintrag_speichern, "", "   ", "Text.", art=nf.NewsfeedFehler))
    check("leerer Text abgewiesen", wirft(nf.eintrag_speichern, "", "T", "", art=nf.NewsfeedFehler))
    check("Text ueber Deckel abgewiesen",
          wirft(nf.eintrag_speichern, "", "T", "x" * (nf.TEXT_MAX + 1), art=nf.NewsfeedFehler))
    check("Titel ueber Deckel abgewiesen",
          wirft(nf.eintrag_speichern, "", "x" * (nf.TITEL_MAX + 1), "Text.", art=nf.NewsfeedFehler))
    check("Text als Liste abgewiesen", wirft(nf.eintrag_speichern, "", "T", ["a"], art=nf.NewsfeedFehler))
    check("Text genau am Deckel angenommen",
          not wirft(nf.eintrag_speichern, "", "T", "x" * nf.TEXT_MAX))
    nf.DATEI.write_bytes(vorher)
    for verweil, scroll, was in ((0.5, 1, "Verweilzeit zu klein"), (61, 1, "Verweilzeit zu gross"),
                                 (3, 0.1, "Scrolldauer zu klein"), (3, 6, "Scrolldauer zu gross"),
                                 ("abc", 1, "Verweilzeit keine Zahl"), (True, 1, "Verweilzeit bool"),
                                 (float("nan"), 1, "Verweilzeit NaN"), (None, 1, "Verweilzeit fehlt")):
        check(f"{was} abgewiesen", wirft(nf.einstellungen_setzen, verweil, scroll, art=nf.NewsfeedFehler))
    check("Bestand nach Abweisungen unveraendert", nf.DATEI.read_bytes() == vorher)
    e = nf.einstellungen_setzen("5", 1.5)
    check("gueltige Einstellungen gespeichert", e == {"verweil_s": 5.0, "scroll_s": 1.5}, str(e))
    check("Anzeige liest sie zurueck", nf.anzeige()["verweil_s"] == 5.0)
    check("Grenzwerte angenommen",
          not wirft(nf.einstellungen_setzen, nf.VERWEIL_MIN, nf.SCROLL_MAX)
          and not wirft(nf.einstellungen_setzen, nf.VERWEIL_MAX, nf.SCROLL_MIN))

    print("\n4b. Bearbeiten rueckt nach vorn, Deaktivieren")
    def setze(eintraege):
        nf.DATEI.write_text(json.dumps({"einstellungen": {}, "eintraege": eintraege}), encoding="utf-8")

    def anz_ids(benutzer=""):
        return [x["id"] for x in nf.anzeige(benutzer)["eintraege"]]

    setze([{"id": f"e{i}", "erstellt": f"2026-10-0{i}T10:00:00", "titel": f"T{i}", "text": "x."}
           for i in range(1, 6)])
    check("Bestand ohne aktiv-Feld gilt als aktiv", anz_ids() == ["e5", "e4", "e3"], str(anz_ids()))
    alt1 = next(x for x in nf.alle() if x["id"] == "e1")
    neu1 = nf.eintrag_speichern("e1", "T1 neu", "y.")
    check("Bearbeiten: Erstellungsdatum bleibt", neu1["erstellt"] == alt1["erstellt"])
    check("Bearbeiten rueckt die aelteste nach vorn", anz_ids() == ["e1", "e5", "e4"], str(anz_ids()))
    vor_stand = nf.anzeige()["stand"]
    d4 = nf.eintrag_deaktivieren("e5")
    check("Deaktivieren liefert den Eintrag mit aktiv=False", isinstance(d4, dict) and d4.get("aktiv") is False)
    check("Deaktivierter fehlt in der Anzeige", "e5" not in anz_ids() and anz_ids() == ["e1", "e4", "e3"], str(anz_ids()))
    check("Deaktivierter bleibt in alle()", any(x["id"] == "e5" and x.get("aktiv") is False for x in nf.alle()))
    check("Deaktivieren aendert den Stand des Eintrags nicht",
          next(x for x in nf.alle() if x["id"] == "e5").get("geaendert") is None)
    check("Stand der Anzeige unveraendert (e1 bleibt juengster)", nf.anzeige()["stand"] == vor_stand)
    check("Deaktivieren unbekannter Kennung -> None", nf.eintrag_deaktivieren("gibtsnicht") is None)
    nf.eintrag_speichern("e5", "T5", "wieder da.")
    check("Bearbeiten macht wieder aktiv und vorn", anz_ids()[0] == "e5"
          and next(x for x in nf.alle() if x["id"] == "e5").get("aktiv") is True, str(anz_ids()))
    check("Neuer Eintrag ist aktiv", nf.eintrag_speichern("", "Neu", "z.").get("aktiv") is True)

    print("\n4c. Ausblenden je Benutzer")
    setze([{"id": f"e{i}", "erstellt": f"2026-10-0{i}T10:00:00", "titel": f"T{i}", "text": "x."}
           for i in range(1, 4)])
    a = nf.anzeige("anna")
    check("Stand = juengster sichtbarer Stand", a["stand"] == "2026-10-03T10:00:00", a["stand"])
    check("vor dem Ausblenden sichtbar", a["ausgeblendet"] is False)
    nf.ausblenden("anna", a["stand"])
    check("nach dem Ausblenden ausgeblendet", nf.anzeige("anna")["ausgeblendet"] is True)
    check("anderer Benutzer nicht betroffen", nf.anzeige("bert")["ausgeblendet"] is False)
    check("ohne Benutzer nie ausgeblendet", nf.anzeige()["ausgeblendet"] is False)
    nf.eintrag_deaktivieren("e3")
    check("Deaktivieren zeigt NICHT wieder", nf.anzeige("anna")["ausgeblendet"] is True)
    nf.eintrag_speichern("e1", "T1", "korrigiert.")
    check("Bearbeitung zeigt wieder", nf.anzeige("anna")["ausgeblendet"] is False)
    nf.ausblenden("anna", nf.anzeige("anna")["stand"])
    check("erneut ausgeblendet", nf.anzeige("anna")["ausgeblendet"] is True)
    gesehen = nf.anzeige("anna")["stand"]
    import time as _t
    _t.sleep(1.1)   # Stand hat Sekundenaufloesung
    nf.eintrag_speichern("", "Ganz neu", "Neuigkeit.")
    check("neue Meldung zeigt wieder", nf.anzeige("anna")["ausgeblendet"] is False)
    nf.ausblenden("anna", gesehen)   # Client zeigte noch den ALTEN Stand
    check("Ausblenden mit dem GEZEIGTEN (aelteren) Stand verschluckt die neue nicht",
          nf.anzeige("anna")["ausgeblendet"] is False)
    for stand, was in ((None, "fehlt"), ("", "leer"), ("morgen", "Freitext"), (123, "Zahl"),
                       ("2026-10-03T10:00:00Z", "mit Zone")):
        check(f"Stand {was} abgewiesen", wirft(nf.ausblenden, "anna", stand, art=nf.NewsfeedFehler))
    check("leerer Benutzer abgewiesen", wirft(nf.ausblenden, "", gesehen, art=nf.NewsfeedFehler))
    nf.AUSGEBLENDET_DATEI.write_text("{kaputt", encoding="utf-8")
    bak2 = nf.AUSGEBLENDET_DATEI.with_name(nf.AUSGEBLENDET_DATEI.name + ".bak")
    if bak2.exists():
        bak2.unlink()
    check("unlesbare Ausblend-Datei: Newsfeed wird gezeigt",
          not wirft(nf.anzeige, "anna") and nf.anzeige("anna")["ausgeblendet"] is False)
    check("unlesbare Ausblend-Datei: Ausblenden wirft Unlesbar",
          wirft(nf.ausblenden, "anna", gesehen, art=atomar.Unlesbar))
    check("unlesbare Ausblend-Datei NICHT ueberschrieben",
          nf.AUSGEBLENDET_DATEI.read_text(encoding="utf-8") == "{kaputt")

    print("\n4. Loeschen und unlesbarer Bestand")
    setze([{"id": f"e{i}", "erstellt": f"2026-10-0{i}T10:00:00", "titel": f"T{i}", "text": "x."}
           for i in range(1, 6)])
    check("Loeschen einer bekannten Kennung", nf.eintrag_loeschen("e5") is True)
    check("e5 ist weg", "e5" not in [x["id"] for x in nf.alle()])
    check("Loeschen einer unbekannten Kennung -> False", nf.eintrag_loeschen("e5") is False)
    nf.DATEI.write_text("{kaputt", encoding="utf-8")
    bak = nf.DATEI.with_name(nf.DATEI.name + ".bak")
    if bak.exists():
        bak.unlink()
    check("unlesbar: Anlegen wirft Unlesbar",
          wirft(nf.eintrag_speichern, "", "T", "Text.", art=atomar.Unlesbar))
    check("unlesbar: Datei NICHT ueberschrieben", nf.DATEI.read_text(encoding="utf-8") == "{kaputt")
finally:
    shutil.rmtree(SANDKASTEN, ignore_errors=True)


print("\n5. Endpunkte (AST von main.py)")
try:
    baum = ast.parse((ROOT / "backend" / "main.py").read_text(encoding="utf-8"))
except Exception as e:  # noqa: BLE001
    abbruch(f"main.py nicht lesbar: {e}")

routen = {}   # (methode, pfad) -> FunctionDef
for k in baum.body:
    if not isinstance(k, ast.AsyncFunctionDef):
        continue
    for dek in k.decorator_list:
        if (isinstance(dek, ast.Call) and isinstance(dek.func, ast.Attribute)
                and isinstance(dek.func.value, ast.Name) and dek.func.value.id == "app"
                and dek.args and isinstance(dek.args[0], ast.Constant)):
            routen[(dek.func.attr, dek.args[0].value)] = k

nf_routen = {mp: f for mp, f in routen.items() if mp[1].startswith("/api/newsfeed")}
# Positivkontrolle: die Erkennung findet die bekannten Routen.
if ("get", "/api/newsfeed") not in nf_routen or ("get", "/api/newsfeed/admin") not in nf_routen:
    abbruch("Routenerkennung findet die Newsfeed-Endpunkte nicht")


def abhaengigkeit(fn):
    """Name der Depends(...)-Abhaengigkeit des Parameters `user` (oder None)."""
    for arg, std in zip(fn.args.args[-len(fn.args.defaults):] if fn.args.defaults else [],
                        fn.args.defaults):
        if (arg.arg == "user" and isinstance(std, ast.Call) and isinstance(std.func, ast.Name)
                and std.func.id == "Depends" and std.args and isinstance(std.args[0], ast.Name)):
            return std.args[0].id
    return None


for (m, pfad), fn in sorted(nf_routen.items()):
    soll = "require_local_auth" if pfad.startswith("/api/newsfeed/admin") else "require_auth"
    check(f"{m.upper()} {pfad}: haengt an {soll}", abhaengigkeit(fn) == soll, str(abhaengigkeit(fn)))

lesen = nf_routen[("get", "/api/newsfeed")]
aufrufe = [c for c in ast.walk(lesen) if isinstance(c, ast.Call)]
check("Lesen prueft _skill_active('newsfeed')",
      any(isinstance(c.func, ast.Name) and c.func.id == "_skill_active" and c.args
          and isinstance(c.args[0], ast.Constant) and c.args[0].value == "newsfeed" for c in aufrufe))
codes = {kw.value.value for c in aufrufe for kw in c.keywords
         if kw.arg == "status_code" and isinstance(kw.value, ast.Constant)}
check("Lesen antwortet bei aus mit 404", 404 in codes, str(codes))
check("Lesen antwortet NIE mit 403 (Portal meldet sonst ab)", 403 not in codes, str(codes))
# Die 404 haengt an der Verzweigung ueber _skill_active (nicht irgendwo).
zweig_ok = False
for knoten in ast.walk(lesen):
    if isinstance(knoten, ast.If) and isinstance(knoten.test, ast.UnaryOp) \
            and isinstance(knoten.test.op, ast.Not) and isinstance(knoten.test.operand, ast.Call) \
            and getattr(knoten.test.operand.func, "id", "") == "_skill_active":
        zweig_ok = any(isinstance(kw.value, ast.Constant) and kw.value.value == 404
                       for c in ast.walk(knoten) if isinstance(c, ast.Call) for kw in c.keywords
                       if kw.arg == "status_code")
check("404 steht im Zweig `if not _skill_active(...)`", zweig_ok)

aus = nf_routen.get(("post", "/api/newsfeed/ausblenden"))
if aus is None:
    check("Route POST /api/newsfeed/ausblenden vorhanden", False)
else:
    a_calls = [x for x in ast.walk(aus) if isinstance(x, ast.Call)]
    check("Ausblenden prueft _skill_active('newsfeed')",
          any(getattr(x.func, "id", "") == "_skill_active" for x in a_calls))
    a_codes = {kw.value.value for x in a_calls for kw in x.keywords
               if kw.arg == "status_code" and isinstance(kw.value, ast.Constant)}
    check("Ausblenden: aus -> 404, nie 403", 404 in a_codes and 403 not in a_codes, str(a_codes))
    # Der Benutzer ist _norm_login(user) aus der Anmeldung – nie ein Rumpffeld.
    ziel = [x for x in a_calls if isinstance(x.func, ast.Name) and x.func.id == "to_thread"
            or (isinstance(x.func, ast.Attribute) and x.func.attr == "to_thread")]
    benutzer_ok = any(len(x.args) >= 2 and isinstance(x.args[1], ast.Call)
                      and getattr(x.args[1].func, "id", "") == "_norm_login"
                      and x.args[1].args and getattr(x.args[1].args[0], "id", "") == "user"
                      for x in ziel)
    check("Ausblenden: Benutzer = _norm_login(user) aus der Anmeldung", benutzer_ok)
check("kein Endpunkt, der ohne Bearbeiten wieder aktiviert",
      not any(p.rstrip("/").endswith("/aktivieren") for _, p in nf_routen))
lesen_benutzer = any(isinstance(x, ast.Call) and len(x.args) >= 2 and isinstance(x.args[1], ast.Call)
                     and getattr(x.args[1].func, "id", "") == "_norm_login" for x in ast.walk(lesen))
check("Lesen reicht _norm_login(user) an die Anzeige", lesen_benutzer)

me = routen.get(("get", "/api/me"))
treffer = False
if me:
    for d in ast.walk(me):
        if isinstance(d, ast.Dict):
            for key, wert in zip(d.keys, d.values):
                if (isinstance(key, ast.Constant) and key.value == "newsfeed"
                        and isinstance(wert, ast.Call) and getattr(wert.func, "id", "") == "_skill_active"
                        and wert.args and getattr(wert.args[0], "value", None) == "newsfeed"):
                    treffer = True
check("/api/me: permissions.newsfeed = _skill_active('newsfeed')", treffer)

print("\n6. Skill-Manifest")
try:
    man = json.loads((ROOT / "skills" / "newsfeed" / "skill.json").read_text(encoding="utf-8"))
except Exception as e:  # noqa: BLE001
    man = {}
    check("skill.json lesbar", False, str(e))
check("Skill vorgabeweise AUS", man.get("enabled") is False)
check("Skill stellt keine Werkzeuge bereit", man.get("tools") == [])

print(f"\nERGEBNIS: {OK}/{OK + FAIL}")
sys.exit(0 if FAIL == 0 else 1)
