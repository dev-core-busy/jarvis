#!/usr/bin/env python3
"""Gegenprobe: beissen die Waechter fuer den Bericht des SAP-Verbindungstests?

Legt sabotierte KOPIEN in ein Wegwerf-Verzeichnis und gibt sie den Waechtern
als Argument bzw. Umgebungsvariable mit – die echten Dateien werden nie
angefasst, ein abgebrochener Lauf hinterlaesst also keinen Rueckstand.

  * tests/test_sap_verbindungstest.py   (--modul sap_client.py, --main main.py)
  * tests/test_sap_portal_ui.js         (SAP_PORTAL_JS=sap_portal.js)

Exit 0 = alle Proben wie erwartet, 1 = mindestens eine nicht, 2 = konnte nicht laufen
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HIER = Path(__file__).resolve().parent
ROOT = HIER.parent
PY_WAECHTER = HIER / "test_sap_verbindungstest.py"
JS_WAECHTER = HIER / "test_sap_portal_ui.js"
DATEIEN = {
    "client": ROOT / "backend" / "sap_client.py",
    "main": ROOT / "backend" / "main.py",
    "portal": ROOT / "frontend" / "js" / "sap_portal.js",
}

# (Name, Datei, alt, neu, erwarteter Exit)
PROBEN = [
    # ── sap_client.py ──
    ("Katalog zaehlt nicht mehr ueber $inlinecount", "client",
     '            data = self.get(KATALOG_PFAD, {"$top": 1, "$inlinecount": "allpages"})\n',
     '            data = self.get(KATALOG_PFAD, {"$top": 1})\n', 1),
    ("an der Obergrenze trotzdem 'genau'", "client",
     "        return len(svcs), len(svcs) < KATALOG_ZAEHL_MAX\n",
     "        return len(svcs), True\n", 1),
    ("400 auf $inlinecount nicht mehr abgefangen", "client",
     "            if e.status != 400:\n                raise\n",
     "            raise\n", 1),
    ("401 am Katalog als 'kein Katalog' verschluckt", "client",
     "            if e.status == 404:\n                info[\"variante\"] = \"katalog_fehlt\"\n",
     "            if e.status in (401, 404):\n                info[\"variante\"] = \"katalog_fehlt\"\n", 1),
    ("Erfolgreiche Anfrage wird nicht gemerkt", "client",
     "        self._merke(r.url, r.status_code, t0)\n        if r.status_code >= 400:\n            msg = \"\"\n",
     "        if r.status_code >= 400:\n            msg = \"\"\n", 1),
    ("Anfrage ohne Antwort wird nicht gemerkt", "client",
     "            r = requests.get(url, params=p, headers=self._headers(),\n"
     "                             auth=self._auth(), verify=self.verify, timeout=_HTTP_TIMEOUT)\n"
     "        except requests.RequestException as e:\n"
     "            self._merke(self._url_mit(url, p), 0, t0)\n",
     "            r = requests.get(url, params=p, headers=self._headers(),\n"
     "                             auth=self._auth(), verify=self.verify, timeout=_HTTP_TIMEOUT)\n"
     "        except requests.RequestException as e:\n", 1),
    ("Bericht uebernimmt die letzte Anfrage nicht", "client",
     "            info.update(self.odata.letzte)\n",
     "            pass\n", 1),
    ("Anmeldung aus der Adresse bleibt im Bericht", "client",
     '        netloc = t.netloc.rsplit("@", 1)[-1]\n',
     "        netloc = t.netloc\n", 1),
    ("$metadata wieder ohne Bearer-Token", "client",
     "        h = self._headers()\n        h[\"Accept\"] = \"application/xml\"\n",
     "        h = {}\n        h[\"Accept\"] = \"application/xml\"\n", 1),
    ("Bericht nennt die EINGESTELLTE statt der gesendeten Anmeldeart", "client",
     '"mandant": o.sap_client, "anmeldeart": art,',
     '"mandant": o.sap_client, "anmeldeart": o.auth_kind,', 1),
    ("EntitySet-Namen fehlen im Bericht", "client",
     '            info["entity_sets"] = sets\n',
     "            pass\n", 1),
    # ── main.py ──
    ("Fehlerzweig ohne Bericht", "main",
     '                             "error": str(e), "info": info})\n',
     '                             "error": str(e)})\n', 1),
    ("Erfolgszweig ohne Bericht", "main",
     '                         "detail": res.get("detail"), "info": res.get("info")})\n',
     '                         "detail": res.get("detail")})\n', 1),
    # ── sap_portal.js ──
    ("Bericht nur bei Erfolg", "portal",
     "                if (d && d.info) {\n",
     "                if (d && d.ok && d.info) {\n", 1),
    ("kopierter Text ohne die Zeilen", "portal",
     "        tiZeilen(d).forEach(function (z) { zeilen.push(z[0] + ': ' + z[1]); });\n",
     "", 1),
    ("Fehlerfall nicht markiert", "portal",
     "        box.classList.toggle('is-error', !d.ok);\n",
     "", 1),
    ("kein Neuzeichnen nach Sprachwechsel", "portal",
     "            if (_letzterTest) accRenderTestInfo();\n",
     "", 1),
    ("leerer Mandant wird nicht erklaert", "portal",
     "            add('sap.ti_mandant', 'Mandant', i.mandant\n"
     "                || T('sap.ti_mandant_default', '— nicht angegeben, es gilt der Standardmandant des Servers —'));\n",
     "            add('sap.ti_mandant', 'Mandant', i.mandant);\n", 1),
    ("neuer Zeilen-Schluessel ohne i18n-Eintrag (ueber add)", "portal",
     "add('sap.ti_time', 'Antwortzeit',",
     "add('sap.ti_zeit', 'Antwortzeit',", 1),
    ("neuer Satz-Schluessel ohne i18n-Eintrag (ueber T)", "portal",
     "T('sap.ti_foot', 'Es wurden keine",
     "T('sap.ti_fuss', 'Es wurden keine", 1),
]


def lauf(kopien: dict) -> int:
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", SAP_PORTAL_JS=str(kopien["portal"]))
    py = subprocess.run([sys.executable, str(PY_WAECHTER), "--modul", str(kopien["client"]),
                         "--main", str(kopien["main"])],
                        capture_output=True, text=True, env=env, timeout=300).returncode
    js = subprocess.run(["node", str(JS_WAECHTER)], capture_output=True, text=True,
                        env=env, timeout=300).returncode
    # Exit 2 (konnte nicht laufen) geht vor 1 (beisst) – sonst verdeckt ein
    # beissender Waechter einen, der gar nicht gemessen hat.
    if 2 in (py, js) or py not in (0, 1) or js not in (0, 1):
        return 2
    return max(py, js)


def main() -> int:
    if set(p[1] for p in PROBEN) - set(DATEIEN):
        print("ABBRUCH: Probe verweist auf eine unbekannte Datei")
        return 2
    texte = {k: v.read_text(encoding="utf-8") for k, v in DATEIEN.items()}
    tmp = Path(tempfile.mkdtemp(prefix="gegen_sapvt_"))
    try:
        kopien = {k: tmp / v.name for k, v in DATEIEN.items()}

        def schreibe(sabotiert=None):
            for k, t in texte.items():
                kopien[k].write_text(sabotiert[1] if sabotiert and sabotiert[0] == k else t,
                                     encoding="utf-8")

        schreibe()
        if lauf(kopien) != 0:
            print("ABBRUCH: Basislauf nicht gruen")
            return 2
        print("Basislauf gruen.\n")
        treffer = 0
        for name, datei, alt, neu, erwartet in PROBEN:
            n = texte[datei].count(alt)
            if n != 1:
                print("  ???  %-62s Anker %dx gefunden" % (name, n))
                continue
            schreibe((datei, texte[datei].replace(alt, neu)))
            rc = lauf(kopien)
            treffer += rc == erwartet
            print("  %s %-62s Exit %d (erwartet %d)"
                  % ("OK  " if rc == erwartet else "ZAHN", name, rc, erwartet))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    print("\n%d/%d Proben wie erwartet" % (treffer, len(PROBEN)))
    return 0 if treffer == len(PROBEN) else 1


if __name__ == "__main__":
    sys.exit(main())
