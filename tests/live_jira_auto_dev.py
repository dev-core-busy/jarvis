#!/usr/bin/env python3
"""Live-Probe auf DEV: baut das Paket mit dem DEPLOYTEN Code und sieht hinein.

Geprueft wird, was nur der echte Bauweg zeigen kann: dass die neue Version
mitgeht, dass das Pulldown im gebrandeten Fenster erhalten bleibt (der
Branding-Schritt schreibt in popup.html) und dass keine Datei verloren geht.
"""
import io, sys, zipfile
sys.path.insert(0, "/opt/jarvis")
from backend import jira_assist  # noqa: E402

ok = fail = 0
def check(text, bed, extra=""):
    global ok, fail
    if bed:
        ok += 1; print("  OK   " + text)
    else:
        fail += 1; print("  FAIL " + text + (" – " + str(extra) if extra else ""))

for variante in ("chrome", "firefox"):
    name, daten = jira_assist.paket_bauen(variante, basis="https://dev.test")
    z = zipfile.ZipFile(io.BytesIO(daten))
    namen = set(z.namelist())
    print("\n=== %s: %s (%d Bytes, %d Dateien)" % (variante, name, len(daten), len(namen)))

    import json
    mf = json.loads(z.read("manifest.json").decode("utf-8"))
    check("%s: Version 0.4.0 im Manifest" % variante, mf.get("version") == "0.4.0",
          mf.get("version"))
    # Die Adresse muss weiterhin als Host-Recht drinstehen (Fix 2026-08-30).
    check("%s: Host-Recht unveraendert eingetragen" % variante,
          mf.get("host_permissions") == ["https://dev.test/*"],
          mf.get("host_permissions"))

    html = z.read("popup.html").decode("utf-8")
    check("%s: das Pulldown ueberlebt den Branding-Schritt" % variante,
          'id="f-auto"' in html)
    check("%s: mit allen drei Moeglichkeiten" % variante,
          html.count('<option value=') >= 3 and 'value="zusammenfassung"' in html
          and 'value="antwort"' in html)
    check("%s: der Knopf heisst 'Antwort ueberarbeiten'" % variante,
          ">Antwort überarbeiten<" in html)
    check("%s: der alte Name ist weg" % variante, ">Überarbeiten<" not in html)
    check("%s: die Adresse steht als Vorgabe im Fenster" % variante,
          'name="basis" content="https://dev.test"' in html)

    js = z.read("popup.js").decode("utf-8")
    bg = z.read("background.js").decode("utf-8")
    check("%s: STAND ist in beiden Dateien gleich" % variante,
          'const STAND = 5;' in js and 'const STAND = 5;' in bg)
    check("%s: der Nachrichtenfall ist im Paket" % variante,
          'case "auto_start":' in bg)
    check("%s: keine Datei fehlt" % variante,
          set(jira_assist.PAKET_DATEIEN).issubset(namen),
          sorted(set(jira_assist.PAKET_DATEIEN) - namen))

print("\n%d OK, %d FAIL" % (ok, fail))
sys.exit(1 if fail else 0)
