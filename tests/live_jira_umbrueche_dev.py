# -*- coding: utf-8 -*-
"""Live auf DEV: das GEBAUTE Paket traegt den Fix, und der ECHTE Weg erhaelt
die Umbrueche. Gemessen wird am ZIP, nicht am Arbeitsbaum – der Branding-
Schritt schreibt Manifest und popup.html um und koennte etwas verlieren."""
import io, json, re, sys, zipfile
sys.path.insert(0, "/opt/jarvis")
ok = fail = 0
def check(bed, text, extra=""):
    global ok, fail
    if bed: ok += 1; print("  OK   " + text)
    else:   fail += 1; print("  FAIL " + text + (" – " + str(extra) if extra else ""))

from backend import jira_assist

for variante in ("chrome", "firefox"):
    _name, daten = jira_assist.paket_bauen(variante)
    z = zipfile.ZipFile(io.BytesIO(daten))
    namen = z.namelist()
    check("einfuegen.js" in namen, variante + ": einfuegen.js liegt im Paket")
    quelle = z.read("einfuegen.js").decode("utf-8")
    check("{ br: true }" in quelle,
          variante + ": der Umbruch-Marker ueberlebt den Bau")
    check("function textAbsatz" in quelle,
          variante + ": der Klartext-Helfer ist drin")
    # Die REGEL, wie im Waechter: nirgends wird ein Umbruch zum Leerzeichen.
    nackt = re.sub(r"/\*.*?\*/", "", quelle, flags=re.S)
    nackt = re.sub(r"^\s*//.*$", "", nackt, flags=re.M)
    check(not re.search(r'replace\(\s*/\\n/g\s*,\s*" "\s*\)', nackt),
          variante + ": kein `replace(/\\n/g, \" \")` mehr im ausgelieferten Code")
    man = json.loads(z.read("manifest.json").decode("utf-8"))
    check(man.get("version") == "0.6.2",
          variante + ": Version 0.6.2 im Manifest", man.get("version"))
    # Gegenprobe, dass der Bau ueberhaupt brandet bzw. vollstaendig ist:
    check("popup.js" in namen and "ansicht.js" in namen,
          variante + ": das Paket ist vollstaendig (Positivkontrolle)")

print("\n%d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
