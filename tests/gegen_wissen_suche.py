#!/usr/bin/env python3
"""Gegenproben: jede Sabotage EINZELN, danach zaehlen wie viele FAIL kommen.

Sichert auf PLATTE (nicht im Speicher) und nimmt einen Rueckstand beim
naechsten Start selbst zurueck - ein per Timeout abgeschossener Lauf laesst
den Arbeitsbaum sonst gepatcht zurueck (Register)."""
import atexit, hashlib, os, re, signal, subprocess, sys
from pathlib import Path

ROOT = Path("/home/bender/ai/projekte/jarvis")
ABLAGE = Path.home() / ".gegen-wissen-suche"
MARKE = ABLAGE / "LAUFT"
DATEIEN = ["frontend/js/wissen.js", "frontend/wissen.html", "frontend/js/i18n.js",
           "tests/test_wissen_suche_ui.js"]

def md5(p): return hashlib.md5(Path(p).read_bytes()).hexdigest()

def sichern():
    ABLAGE.mkdir(mode=0o700, exist_ok=True)
    for d in DATEIEN:
        ziel = ABLAGE / d.replace("/", "__")
        ziel.write_bytes((ROOT / d).read_bytes())

def zurueck():
    for d in DATEIEN:
        q = ABLAGE / d.replace("/", "__")
        if q.exists():
            (ROOT / d).write_bytes(q.read_bytes())

# Rueckstand eines abgeschossenen Laufs zuerst zuruecknehmen
if MARKE.exists():
    print("! Rueckstand eines frueheren Laufs - stelle wieder her")
    zurueck()
    MARKE.unlink()

def lauf():
    r = subprocess.run(["node", "tests/test_wissen_suche_ui.js"], cwd=ROOT,
                       capture_output=True, text=True, timeout=120)
    m = re.search(r"Ergebnis: (\d+) OK, (\d+) FAIL", r.stdout)
    if not m:
        return None, r.stdout[-400:]
    return (int(m.group(1)), int(m.group(2))), ""

# ── Basislauf: ohne gruene Basis ist keine Gegenprobe deutbar ────────────
b, err = lauf()
if not b or b[1] != 0:
    print("ABBRUCH: Basis nicht gruen:", b, err); sys.exit(2)
print("Basis: %d OK, %d FAIL\n" % b)

sichern()
MARKE.write_text("1")
atexit.register(lambda: (zurueck(), MARKE.unlink(missing_ok=True)))
signal.signal(signal.SIGTERM, lambda *a: sys.exit(1))

# (Name, Datei, alt, neu)
PROBEN = [
    ("Pfad-Normalisierung raus (fuehrender / bleibt)", "frontend/js/wissen.js",
     ".replace(/^\\/+/, '')", ""),
    ("Inhaltssuche gar nicht gerufen", "frontend/js/wissen.js",
     "if (q.length < SUCH_MIN) { _inhaltFuer = null; _inhaltTreffer = null; return; }",
     "if (true) { _inhaltFuer = null; _inhaltTreffer = null; return; }"),
    # Die TRAGENDE Wettlauf-Schranke (der Seq-Zaehler daneben war messbar
    # redundant und ist deshalb entfernt - siehe Kommentar im Code).
    ("Treffer-Zuordnung raus (_inhaltFuer ignoriert)", "frontend/js/wissen.js",
     "return !!(_inhaltTreffer && _inhaltFuer === q\n            && _inhaltTreffer.has(pfadSchluessel(f.path)));",
     "return !!(_inhaltTreffer && _inhaltTreffer.has(pfadSchluessel(f.path)));"),
    ("Render-Sparschranke raus (Korrektheit haengt NICHT daran)", "frontend/js/wissen.js",
     "if (suchText() !== q) return;", ""),
    ("Suche wirkt gar nicht auf die Liste", "frontend/js/wissen.js",
     "var shown = inGruppe.filter(function (f) { return trifftSuche(f, q); });",
     "var shown = inGruppe;"),
    ("Leermeldung nennt den Grund nicht mehr", "frontend/js/wissen.js",
     "var grund = (q && inGruppe.length)\n                ? t('wissen.no_files_search', { q: q })\n                : t('wissen.no_files_filtered');",
     "var grund = t('wissen.no_files_filtered');"),
    ("Suche nicht gebunden", "frontend/js/wissen.js",
     "                bindFileSearch();\n", ""),
    ("Suchzeile nie sichtbar gemacht", "frontend/js/wissen.js",
     "                renderFileSearch();\n", ""),
    ("Escape leert nicht mehr", "frontend/js/wissen.js",
     "if (e.key === 'Escape' && el.value) {", "if (false) {"),
    ("Ordner faellt aus der Sofort-Suche", "frontend/js/wissen.js",
     "(f.name || '') + ' ' + ordnerText(f) + ' ' + (f.path || '') + ' '",
     "(f.name || '') + ' '"),
    ("Suchfeld ohne autocomplete=off", "frontend/wissen.html",
     'name="wissen-suche" autocomplete="off"', 'name="wissen-suche"'),
    # Die Sabotage muss das Feld WIRKLICH in die Gruppen-Filterzeile legen -
    # nur die Klasse zu tauschen erzeugt ein zweites Element und misst nichts.
    ("Suchfeld liegt in der Gruppen-Filterzeile", "frontend/js/wissen.js",
     "        var wrap = $('wi-files-search'), hint = $('wi-files-search-hint');\n        var an = _files.length > 0;",
     "        var wrap = $('wi-files-filter'), hint = $('wi-files-search-hint');\n        var an = _files.length > 0;"),
    ("Hinweiszeile raus", "frontend/wissen.html",
     '<p class="wi-search-hint" id="wi-files-search-hint" style="display:none;"',
     '<p class="wi-search-hint" id="wi-files-search-hint-x" style="display:none;"'),
    ("EN-Text fehlt", "frontend/js/i18n.js",
     "'wissen.search_ph': 'Search (name, folder & content)…',", ""),
]

print("%-52s %s" % ("Gegenprobe", "Ergebnis"))
print("-" * 72)
zahnlos = []
for name, datei, alt, neu in PROBEN:
    zurueck()
    p = ROOT / datei
    s = p.read_text(encoding="utf-8")
    if s.count(alt) < 1:
        print("%-52s ANKER FEHLT (Sabotage verfehlt ihr Ziel)" % name[:52]); zahnlos.append(name); continue
    p.write_text(s.replace(alt, neu, 1), encoding="utf-8")
    assert md5(p) != md5(ABLAGE / datei.replace("/", "__")), "Sabotage hat nicht gegriffen"
    r, err = lauf()
    if r is None:
        print("%-52s ABBRUCH OHNE BILANZ  %s" % (name[:52], err[:60].replace("\n", " ")))
        zahnlos.append(name)
    elif r[1] == 0:
        print("%-52s \x1b[31mBEISST NICHT\x1b[0m (0 FAIL)" % name[:52]); zahnlos.append(name)
    else:
        print("%-52s %d FAIL" % (name[:52], r[1]))

zurueck()
n, err = lauf()
print("\nBasis nach Wiederherstellung: %s" % (n,))
for d in DATEIEN:
    assert md5(ROOT / d) == md5(ABLAGE / d.replace("/", "__")), "nicht byte-gleich: " + d
print("alle Dateien byte-gleich wiederhergestellt")
print("\n%d von %d Gegenproben beissen%s" % (len(PROBEN) - len(zahnlos), len(PROBEN),
      "" if not zahnlos else " - OFFEN: " + "; ".join(zahnlos)))
