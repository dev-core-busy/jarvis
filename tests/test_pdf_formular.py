"""Tests fuer skills/office/pdf_formular.py – Formular-PDFs auslesen.

Ohne fastapi lauffaehig. ``backend.config`` wird ausdruecklich NICHT geladen:
der echte Import migriert Profile und schriebe die Live-``settings.json``
zurueck. Deshalb steht ein Stub im ``sys.modules``, und der Waechter unten
bricht mit Exit 2 ab, falls doch das echte Modul haengt.

DIE TESTDATEN SIND SYNTHETISCH. Das PDF, das diesen Umbau ausgeloest hat,
enthaelt Namen und Anschriften von Arztpraxen – solche Daten gehoeren nicht in
ein oeffentliches Repo. Nachgebaut ist die GEOMETRIE, auf die es ankommt: der
eingetragene Wert steht ueber seiner Beschriftung, es gibt mehrzeilige Werte,
einen Stempel rechts aussen und Kopf-/Fusszeilen.
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# ── Sandkasten-Waechter ──────────────────────────────────────────────────
if "backend.config" not in sys.modules:
    _stub = types.ModuleType("backend.config")
    _stub.config = types.SimpleNamespace()
    sys.modules["backend.config"] = _stub
if getattr(sys.modules["backend.config"], "__file__", None):
    print("FEHLER: echtes backend.config geladen – Test wuerde settings.json anfassen")
    sys.exit(2)

from skills.office import pdf_formular as PF  # noqa: E402

ok = 0
fehler = []


def pruefe(bedingung, text):
    global ok
    if bedingung:
        ok += 1
    else:
        fehler.append(text)


# ── Hilfsmittel: eine Seite aus (text, x, y) bauen ───────────────────────
BREITE, HOEHE = 1600.0, 2200.0
ZEILE = 20.0


def wort(t, x, y, h=20):
    return {"t": t, "x": float(x), "y": float(y), "w": len(t) * 9.0, "h": float(h)}


def seite_bauen(felder, stempel=None, kopf=True):
    """felder: [(beschriftung, wert_oder_None, wert_ueber_label?)] von oben nach unten."""
    ws = []
    if kopf:
        ws += [wort("Musterfirma", 1100, 100), wort("GmbH", 1300, 100)]
        ws += [wort("Umsatzsteuer-ID:", 170, 2100), wort("DE 123 456 789", 500, 2100)]
    y = 1100.0
    for name, wert, drueber in felder:
        if wert:
            if drueber:
                ws.append(wort(wert, 500, y - 18))
                ws.append(wort(name + ":", 170, y))
            else:
                ws.append(wort(name + ":", 170, y))
                ws.append(wort(wert, 500, y))
        else:
            ws.append(wort(name + ":", 170, y))
        y += 38
    if stempel:
        # BEWUSST auf der Hoehe eines eingetragenen Wertes (18 px ueber der
        # letzten Beschriftung) und weit rechts: so entscheidet allein die
        # Grenze der Wertspalte, ob der Stempel im Feld landet. Setzt man ihn
        # auf Label-Hoehe, filtert ihn schon das y-Fenster – und die
        # Gegenprobe zum x-Filter blieb gruen, ohne etwas zu pruefen.
        ws.append(wort(stempel, 1250, 1100 + 38 * (len(felder) - 1) - 18))
    return ws


FELDER = [("Name", None, True), ("Strasse", None, True), ("Ort", None, False),
          ("Telefon", None, False), ("Fax", None, False)]


def seiten_satz(werte_liste, **kw):
    """werte_liste: je Seite ein dict {feldname: wert}."""
    seiten = []
    for i, werte in enumerate(werte_liste, 1):
        felder = [(n, werte.get(n), d) for n, _, d in FELDER]
        seiten.append((seite_bauen(felder, **kw), BREITE, HOEHE, i))
    return seiten


def auswerten(seiten, **kw):
    PF._pdf_seiten_woerter = lambda p, q, s: (seiten, "ocr", len(seiten))
    return PF.formular_auswerten(Path("egal.pdf"), **kw)


# ── 0. Kettenbildung im Clustering ───────────────────────────────────────
# Jede Seite ist minimal anders ausgerichtet (Scan-Streuung). Vergleicht das
# Clustering gegen den ZULETZT aufgenommenen Fund statt gegen den Median,
# wandert ein Cluster mit jeder Seite weiter und verschluckt das naechste
# Feld – aus fuenf Feldern wird eines, und die Werte stehen verschoben.
def satz_mit_streuung(n=12):
    seiten = []
    for i in range(n):
        versatz = (i % 9) * 4.0 - 16.0         # +-16 px, wie ein schief eingezogener Scan
        werte = {"Name": f"Person {i}", "Strasse": f"Hauptstrasse {i}",
                 "Ort": f"1000{i % 10} Ortsname", "Telefon": f"030 55 {i:02d}"}
        felder = [(nm, werte.get(nm), d) for nm, _, d in FELDER]
        ws = seite_bauen(felder)
        for w in ws:
            w["y"] += versatz
        seiten.append((ws, BREITE, HOEHE, i + 1))
    return seiten

erg0 = auswerten(satz_mit_streuung())
pruefe(len([s for s in erg0["spalten"] if s != "Seite"]) >= 4,
       f"Felder bleiben getrennt trotz Scan-Streuung (bekam {erg0['spalten']})")
pruefe(all(str(z.get("Name", "")).startswith("Person") for z in erg0["zeilen"]),
       "kein Feld verschluckt das naechste (Name)")
pruefe(all(str(z.get("Strasse", "")).startswith("Hauptstrasse") for z in erg0["zeilen"]),
       f"…und die Strasse bleibt die Strasse (Zeile 1: {erg0['zeilen'][0].get('Strasse')!r})")


# ── 1. Der Kern: Wert steht UEBER der Beschriftung ───────────────────────
daten = [{"Name": f"Person {i}", "Strasse": f"Weg {i}", "Ort": f"1234{i} Stadt",
          "Telefon": f"030 111 {i}"} for i in range(1, 7)]
erg = auswerten(seiten_satz(daten))
pruefe(len(erg["zeilen"]) == 6, "sechs Seiten -> sechs Zeilen")
pruefe(erg["zeilen"][0].get("Name") == "Person 1",
       f"Wert ueber Label wird zugeordnet (bekam {erg['zeilen'][0].get('Name')!r})")
pruefe(erg["zeilen"][0].get("Strasse") == "Weg 1",
       f"zweites Feld nicht verschoben (bekam {erg['zeilen'][0].get('Strasse')!r})")
pruefe(erg["zeilen"][0].get("Ort") == "12341 Stadt",
       f"Wert NEBEN dem Label wird ebenfalls zugeordnet (bekam {erg['zeilen'][0].get('Ort')!r})")
pruefe(all(z.get("Name") == f"Person {i}" for i, z in enumerate(erg["zeilen"], 1)),
       "alle Seiten korrekt")

# Gegenprobe: keine Verschiebung um ein Feld
pruefe(not any(z.get("Name", "").startswith("Weg") for z in erg["zeilen"]),
       "Strassenwert landet NIE im Namensfeld")

# ── 2. Leere Felder bleiben leer (und werden nicht geraten) ──────────────
pruefe(all(not z.get("Fax") for z in erg["zeilen"]),
       "unausgefuelltes Feld bleibt leer")

# ── 3. Kopf-/Fusszeile faellt heraus ─────────────────────────────────────
pruefe("Umsatzsteuer-ID" not in erg["spalten"],
       f"Fusszeile nicht als Feld (Spalten: {erg['spalten']})")

# ── 4. Stempel rechts aussen wandert nicht in ein Feld ───────────────────
# Erst der Gesamtlauf …
erg_s = auswerten(seiten_satz(daten, stempel="9876543"))
pruefe(not any("9876543" in str(v) for z in erg_s["zeilen"] for v in z.values()),
       "Stempel jenseits der Wertspalte bleibt draussen")

# … dann die beiden Mechanismen EINZELN. Der Gesamtlauf allein taugt hier
# nicht als Nachweis: er blieb auch dann gruen, als der Filter ausgebaut war
# (ein anderer Schutz griff zufaellig zuerst) – also haette er nichts geprueft.
zeile_mit_stempel = {
    "ws": [wort("Praxis", 500, 1000), wort("nimmt", 570, 1000),
           wort("teil.", 650, 1000), wort("987654321", 1250, 1000)],
    "breite": BREITE,
}
zeile_mit_stempel["x0"] = 500
nur_wert = PF._ab_spaltenbeginn(zeile_mit_stempel, 0.25, 0.55)
pruefe("987654321" not in nur_wert,
       f"grosse Luecke trennt den Stempel ab (bekam {nur_wert!r})")
pruefe("teil." in nur_wert, f"…und der Wert bleibt vollstaendig (bekam {nur_wert!r})")

# Ein Fragment, das JENSEITS der Wertspalte beginnt, gehoert zu keinem Feld.
frag_fremd = [{"ws": [wort("987654321", 1250, 1000)], "m": 1010.0, "x0": 1250.0}]
wert_f, _ = PF.wert_holen(frag_fremd, [], {"y": 1010 / HOEHE, "name": "X"},
                          HOEHE, BREITE, (40.0, 10.0), set(), x_max=0.55)
pruefe(wert_f == "", f"Fragment jenseits der Wertspalte wird verworfen (bekam {wert_f!r})")
wert_d, _ = PF.wert_holen(frag_fremd, [], {"y": 1010 / HOEHE, "name": "X"},
                          HOEHE, BREITE, (40.0, 10.0), set(), x_max=0.99)
pruefe(wert_d == "987654321",
       "Gegenprobe: mit weiter Spalte wuerde es genommen – der Filter ist die Ursache")

# ── 4b. Clustering trennt Felder auch bei ueberlappenden Hoehen ──────────
# Direkt gegen schablone_lernen, nicht ueber den Gesamtlauf: dort faengt die
# Seitenausrichtung einen Clusterfehler auf, und die Pruefung waere blind.
def label_seite(y_name, y_strasse):
    ws = [wort("Name:", 170, y_name), wort("Strasse:", 170, y_strasse)]
    return zeilen_fuer(ws)


def zeilen_fuer(ws):
    zs = PF.zeilen_bilden(ws)
    for z in zs:
        z["breite"] = BREITE
    return zs

# Zwei Felder, 38 px auseinander, aber je Seite um bis zu +-16 px versetzt:
# die Hoehenbereiche ueberlappen ueber die Seiten hinweg.
seiten_z, hoehen_z = [], []
for i in range(10):
    v = (i % 9) * 4.0 - 16.0
    seiten_z.append(label_seite(1100 + v, 1138 + v))
    hoehen_z.append(HOEHE)
felder_z = PF.schablone_lernen(seiten_z, hoehen_z, BREITE * 0.25)
namen_z = [f["name"] for f in felder_z]
pruefe(namen_z.count("Name") == 1 and namen_z.count("Strasse") == 1,
       f"jedes Feld genau einmal trotz Ueberlappung (bekam {namen_z})")

# ── 5. Mehrzeiliger Wert wird zusammengesetzt – in RICHTIGER Reihenfolge ──
ws = seite_bauen([("Name", None, True), ("Strasse", "Weg 9", True),
                  ("Ort", "10000 Stadt", False), ("Telefon", "030", False),
                  ("Fax", None, False)])
# zweizeiliger Name: Fortsetzung links (x=380) und Rest rechts (x=520)
ws.append(wort("Gemeinschaftspraxis Dr. Meier", 520, 1100 - 30))
ws.append(wort("Grosse", 380, 1100 - 22))
mehr = [(ws, BREITE, HOEHE, 1)] + seiten_satz(daten)[1:]
erg_m = auswerten(mehr)
name1 = erg_m["zeilen"][0].get("Name", "")
pruefe("Grosse" in name1 and "Gemeinschaftspraxis" in name1,
       f"mehrzeiliger Wert vollstaendig (bekam {name1!r})")
# NIE .index() in einer Pruefung – das wirft, statt fehlzuschlagen, und eine
# Gegenprobe saehe dann wie ein bestandener Lauf aus.
pruefe(name1.find("Grosse") >= 0 and name1.find("Gemeinschaftspraxis") > name1.find("Grosse"),
       f"Reihenfolge nach x, nicht nach Hoehe (bekam {name1!r})")

# ── 6. Verlesene Beschriftung: Wert geht trotzdem nicht verloren ─────────
# Alle fuenf Felder bleiben an ihrem Platz – nur die Beschriftung 'Name:'
# ist verlesen (ohne Doppelpunkt), der Wert steht wie sonst daneben.
ws2 = seite_bauen([("XName", None, True), ("Strasse", "Weg 5", True),
                   ("Ort", "20000 Stadt", False), ("Telefon", "040", False),
                   ("Fax", None, False)])
ws2 = [w for w in ws2 if w["t"] != "XName:"]
# Beschriftung und Wert stehen auf DERSELBEN Hoehe – sonst ist der Wert eine
# eigene Zeile und wird ohnehin erfasst; die Rettung waere dann nicht geprueft.
ws2.append(wort("Nana", 175, 1100 - 18))          # 'Name:' ohne Doppelpunkt verlesen
ws2.append(wort("Frau Dr. Schmidt", 520, 1100 - 18))
verl = [(ws2, BREITE, HOEHE, 1)] + seiten_satz(daten)[1:]
erg_v = auswerten(verl)
pruefe("Schmidt" in str(erg_v["zeilen"][0].get("Name", "")),
       f"Wert trotz verlesener Beschriftung erfasst (bekam {erg_v['zeilen'][0].get('Name')!r})")

# ── 7. Kanonischer Feldname aus der Mehrheit ─────────────────────────────
satz = seiten_satz(daten)
for i in (0, 1):
    for w in satz[i][0]:
        if w["t"] == "Telefon:":
            w["t"] = "TeIefon:"                    # OCR-Verlesung auf 2 von 6 Seiten
erg_k = auswerten(satz)
pruefe("Telefon" in erg_k["spalten"],
       f"Mehrheit bestimmt den Feldnamen (Spalten: {erg_k['spalten']})")
pruefe("TeIefon" not in erg_k["spalten"], "Verlesung wird nicht zur eigenen Spalte")

# ── 8. Seitenauswahl ─────────────────────────────────────────────────────
pruefe(PF._seiten_indizes("1-3", 10) == [0, 1, 2], "Bereich '1-3'")
pruefe(PF._seiten_indizes("1,5,9", 10) == [0, 4, 8], "Liste '1,5,9'")
pruefe(PF._seiten_indizes("", 4) == [0, 1, 2, 3], "leer = alle")
try:
    PF._seiten_indizes("99", 4)
    pruefe(False, "Seite ausserhalb -> Fehler")
except PF.FormularFehler:
    pruefe(True, "Seite ausserhalb -> Fehler")

# ── 9. Textguete: erkennt die beschaedigte Zeichentabelle ────────────────
# Nachgebildet nach dem, was die beschaedigte Zeichentabelle im gemeldeten
# PDF wirklich produziert hat – ohne die echten Daten zu uebernehmen.
kaputt = "12395 Musterstadt 0301 / 55 4S 33 2 12345 6789 kontakt@beispiel'de OL.O7.2026"
heil = "12345 Musterstadt 0301 / 55 44 33 2 123456789 kontakt@beispiel.de 01.07.2026"
g_k, t_k = PF.textguete(kaputt)
g_h, t_h = PF.textguete(heil)
pruefe(g_k > g_h, f"beschaedigter Text hat mehr zerhackte Woerter ({g_k:.1f} vs {g_h:.1f})")
pruefe(t_h > t_k, f"heiler Text hat mehr verwertbare Treffer ({t_h} vs {t_k})")
# Das Mass ist ein VERGLEICH, keine absolute Aussage: derselbe Fachtext in
# beiden Fassungen darf keinen Wechsel ausloesen (ICD-10, Pflegekategorien).
fach = "Diagnose O61.0 und A4S1 nach Schema, PLZ 12345, Nummer 123456789"
g_f, t_f = PF.textguete(fach)
pruefe(t_f >= 3, f"Fachtext: PLZ und lange Nummer werden gezaehlt (bekam {t_f})")
pruefe(not (t_f > t_f * 1.1 or g_f < g_f * 0.8),
       "gleicher Text auf beiden Seiten -> kein Quellenwechsel")

# ── 10. Kein Formular -> ehrlicher Fehler statt Muell ────────────────────
fliess = [([wort("Ein Satz ohne jede Beschriftung", 170, 500)], BREITE, HOEHE, 1)]
try:
    auswerten(fliess)
    pruefe(False, "ohne Beschriftungen -> Fehler")
except PF.FormularFehler as e:
    pruefe("office_read" in str(e), f"Fehler nennt den Ausweg (bekam {e})")

# ── 11. Unbekannte Parameter werden GENANNT, nicht verschluckt ───────────
import asyncio  # noqa: E402
werkzeug = PF.FormularExtraktTool()
antwort = asyncio.run(werkzeug.execute(path="x.pdf", seitn="1-3"))
pruefe("seitn" in antwort and antwort.startswith("Fehler"),
       f"Tippfehler im Parameter wird benannt (bekam {antwort[:80]!r})")

# ── 12. Zusagen des Moduls ───────────────────────────────────────────────
quell = (ROOT / "skills/office/pdf_formular.py").read_text(encoding="utf-8")
pruefe('pfad_parameter = ("path",)' in quell,
       "Pfad wird vom Dispatch geprueft (sonst Umgehung des Confinements)")
pruefe("OMP_THREAD_LIMIT" in quell,
       "OCR-Parallelisierung begrenzt (sonst Faktor 15 langsamer)")
pruefe("asyncio.to_thread" in quell,
       "OCR blockiert den Event-Loop nicht")
main_py = (ROOT / "skills/office/main.py").read_text(encoding="utf-8")
pruefe("get_pdf_formular_tools" in main_py, "Werkzeug ist eingehaengt")
backend_main = (ROOT / "backend/main.py").read_text(encoding="utf-8")
pruefe("pdf_formular_extrakt" in backend_main,
       "Anhang-Hinweis nennt das Werkzeug")
pruefe("_tool_namen" in backend_main,
       "…aber nur, wenn es wirklich geladen ist")

print(f"{ok} Pruefungen bestanden, {len(fehler)} fehlgeschlagen")
for f in fehler:
    print("  FAIL:", f)
sys.exit(1 if fehler else 0)
