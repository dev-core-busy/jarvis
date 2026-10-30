#!/usr/bin/env python3
"""Gegenprobe: beissen die Waechter fuer den Bericht des SAP-Verbindungstests?

Legt sabotierte KOPIEN in ein Wegwerf-Verzeichnis und gibt sie den Waechtern
als Argument bzw. Umgebungsvariable mit – die echten Dateien werden nie
angefasst, ein abgebrochener Lauf hinterlaesst also keinen Rueckstand.

  * tests/test_sap_verbindungstest.py   (--modul sap_client.py, --main main.py)
    – Verbindungstest UND Auswahllisten der Abfrage-Konsole
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
    # ── sap_client.py: Service-Pfade der Konsole ──
    ("Konsole uebernimmt die absolute Katalog-Adresse", "client",
     '            rel = pfad[len(basis):].strip("/")\n',
     '            rel = (s.get("url") or "").strip("/")\n', 1),
    ("Praefix ohne Grenze (/odata4 gilt als unter /odata)", "client",
     '            if basis and not pfad.lower().startswith(basis.lower() + "/"):\n',
     '            if basis and not pfad.lower().startswith(basis.lower()):\n', 1),
    ("Dubletten ueberschreiben den ersten Eintrag", "client",
     "            if rel and rel not in gesehen:\n",
     "            if rel:\n", 1),
    ("Service-Liste immer 'genau'", "client",
     '                "genau": len(svcs) < max(1, min(int(limit or KATALOG_ZAEHL_MAX),\n',
     '                "genau": True or len(svcs) < max(1, min(int(limit or KATALOG_ZAEHL_MAX),\n', 1),
    # ── sap_client.py: Abrufbarkeit und Navigationsweg ──
    ("sap:addressable wird ignoriert", "client",
     '                if lokal(k) == "addressable" and str(v).strip().lower() == "false":\n',
     '                if False:\n', 1),
    ("Navigationsweg nur ueber die Rollennamen (Koeder greift)", "client",
     '                    if (kurz(n.get("Relationship") or "") == assoc and n.get("ToRole") == rolle_s\n',
     '                    if (True and n.get("ToRole") == rolle_s\n', 1),
    ("V4-Ziel mit Container-Praefix nicht aufgeloest", "client",
     '                    v4_wege.append((kurz(b.get("Target").rsplit("/", 1)[-1]),\n',
     '                    v4_wege.append((kurz(b.get("Target")),\n', 1),
    # ── sap_client.py: Mitladen ──
    ("nicht geladene Navigation bleibt als Spalte", "client",
     '    if set(wert) == {"__deferred"}:\n        return _NICHT_GELADEN\n', "", 1),
    ("mitgeladene V2-Liste wird nicht geglaettet", "client",
     '    if isinstance(wert.get("results"), list) and set(wert) <= {"results", "__count", "__next"}:\n',
     '    if False:\n', 1),
    ("Spalten nur aus der ersten Zeile", "client",
     "    for z in sauber:\n        for k in z:\n",
     "    for z in sauber[:1]:\n        for k in z:\n", 1),
    ("V4-Anmerkungen bleiben stehen", "client",
     '        if k == "__metadata" or k.startswith("@odata.") or "@odata." in k:\n',
     '        if k == "__metadata":\n', 1),
    # ── main.py ──
    ("Abfrage-Endpunkt mit eigener, alter Bereinigung", "main",
     "        cols, clean = tabelle_aus(rows)\n",
     '        clean = [{k: v for k, v in r.items() if k != "__metadata"} for r in rows]\n'
     "        cols = list(clean[0].keys()) if clean else []\n", 1),
    ("EntitySet-Endpunkt ohne Details", "main",
     '        return JSONResponse({"ok": True, "service": svc, "entity_sets": sets, "count": len(sets),\n'
     '                             "details": details})\n',
     '        return JSONResponse({"ok": True, "service": svc, "entity_sets": sets, "count": len(sets)})\n', 1),
    ("EntitySets wieder mit der rohen Eingabe", "main",
     "        details = await asyncio.to_thread(c.odata.entity_set_details, svc)\n",
     "        details = await asyncio.to_thread(c.odata.entity_set_details, service.strip())\n", 1),
    ("Service-Liste ohne SAP-Freigabe", "main",
     "async def sap_odata_services_api(user: str = Depends(require_sap_access)):\n",
     "async def sap_odata_services_api(user: str = \"\"):\n", 1),
    ("Service-Liste aus den absoluten Katalog-Adressen", "main",
     "        res = await asyncio.to_thread(c.odata.catalog_service_pfade)\n",
     "        res = await asyncio.to_thread(c.odata.catalog_services)\n", 1),
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
    ("Konsole: veraltete Antwort ueberschreibt die neue Liste", "portal",
     "                if (_odSetsFuer !== key) return;\n                odZeigeSets(d);\n",
     "                odZeigeSets(d);\n", 1),
    ("Konsole: kein Gedaechtnis je Service", "portal",
     "        if (_odSets[key]) { odZeigeSets(_odSets[key]); return; }\n",
     "", 1),
    ("Konsole: laedt auch, wenn OData nicht sichtbar ist", "portal",
     "        if (!odSichtbar()) return;\n",
     "", 1),
    ("Konsole: fehlender Katalog wird immer wieder abgefragt", "portal",
     "                if (!(d && d.ok) && !(d && d.kein_katalog)) _odSvc = null;\n",
     "                if (!(d && d.ok)) _odSvc = null;\n", 1),
    ("Konsole: Titel als Markup eingesetzt", "portal",
     "            if (it.label) o.setAttribute('label', it.label);\n",
     "            if (it.label) o.innerHTML = it.label;\n", 1),
    ("Konsole: neuer Schluessel ohne i18n-Eintrag", "portal",
     "T('sap.od_sets_loading', 'Lade EntitySets…')",
     "T('sap.od_sets_laden', 'Lade EntitySets…')", 1),
    ("404-Erklaerung raet auch bei abrufbarem Set", "portal",
     "        return w.detail.addressable === false ? odNavText(w.detail) : '';\n",
     "        return odNavText(w.detail);\n", 1),
    ("404-Erklaerung aus der Liste eines ANDEREN Service", "portal",
     "        var d = _odSets[odServiceKey()];\n        if (!d || !d.ok) return null;\n",
     "        var d = _odSets[odServiceKey()] || _odSets[Object.keys(_odSets)[0]];\n        if (!d || !d.ok) return null;\n", 1),
    ("Auswahl im EntitySet-Feld ohne sofortigen Hinweis", "portal",
     "        $('sp-od-entity').addEventListener('input', odPruefeEntity);\n",
     "", 1),
    ("Speichern verwirft die gemerkten Listen nicht", "portal",
     "                odVerwerfen();\n                accNote('✓ ' + T('sap.acc_saved', 'Gespeichert.'), 'ok');\n",
     "                accNote('✓ ' + T('sap.acc_saved', 'Gespeichert.'), 'ok');\n", 1),
    ("alte EntitySet-Antwort nach dem Speichern wird gemerkt", "portal",
     "                if (gen !== _odGeneration) return;   // Zugang inzwischen gespeichert/entfernt\n",
     "", 1),
    ("Standard-Service-Liste auch aus dem Sammelzugang", "portal",
     "        if (odEigenerZugang()) {\n            odFill('sp-acc-od-service-list', werte);\n",
     "        if (true) {\n            odFill('sp-acc-od-service-list', werte);\n", 1),
    ("Standard-Service fragt auch ohne eigenen Zugang ab", "portal",
     "        if (!odEigenerZugang()) {\n            odFill('sp-acc-od-service-list', []);\n",
     "        if (false) {\n            odFill('sp-acc-od-service-list', []);\n", 1),
    ("Mitladen wird nicht an die Abfrage uebergeben", "portal",
     "            + (expand ? '&expand=' + encodeURIComponent(expand) : '');\n",
     "            + '';\n", 1),
    ("verschachtelte Daten wieder als [object Object]", "portal",
     "        if (typeof v !== 'object') return esc(v);\n",
     "        return esc(v);\n", 1),
    ("Zellinhalt ungeschuetzt als Markup", "portal",
     "        if (typeof v !== 'object') return esc(v);\n",
     "        if (typeof v !== 'object') return String(v);\n", 1),
    ("keine Tiefenbegrenzung", "portal",
     "        if (tiefe >= 2) return esc(JSON.stringify(v));\n", "", 1),
    ("Mitladen bietet EINGEHENDE statt abgehender Navigationen an", "portal",
     "                if (w.von === name) aus.push({ property: w.property, nach: x.name });\n",
     "                if (x.name === name) aus.push({ property: w.property, nach: w.von });\n", 1),
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
