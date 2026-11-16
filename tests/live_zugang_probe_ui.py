#!/usr/bin/env python3
"""
Optische Abnahme: die Fachprobe in "Mein …-Zugang" ist nach dem AUFKLAPPEN
sichtbar und bedienbar – auf /confluence, /jira, /sap und /vemas (2026-11-16).

ANLASS: gemeldet "unter /confluence ist WEITERHIN KEIN TEST SICHTBAR – der
Container klappt immer wieder zu und zeigt die gewuenschten Felder nicht".
Vorgabe des Betreibers dazu: standardmaessig zugeklappt (wenn keine Anmeldung
noetig ist), aber "SELBSTVERSTAENDLICH MUSS DER CONTAINER AUFKLAPPBAR UND DANN
VOLLSTAENDIG SICHTBAR SEIN, WENN DER BENUTZER DAS MOECHTE".

ECHTES Chrome, die ECHTEN Seiten aus frontend/ (HTML, CSS, alle Skripte),
nur die API ist nachgebildet (per addScriptToEvaluateOnNewDocument VOR dem
ersten Skript – Register: sonst leitet die Seite ohne Sitzung um). jsdom
taugt hier nicht: es rechnet kein Layout, und ob ein Element hinter einem
zugeklappten <details> oder einem display:none-Vorfahren steckt, sieht nur
ein Browser (checkVisibility + elementFromPoint).

Je Seite und Lage:
  * Positivkontrolle: Seite geladen, Zugangs-Container im DOM.
  * Ausgangslage zugeklappt (die Vorgabe bleibt).
  * ECHTER Mausklick auf die Kopfzeile des SICHTBAREN Zugangs-Containers
    -> offen, und nach 4 s immer noch offen (kein Zurueckschnappen).
  * Der Probe-Knopf ist sichtbar, liegt im geoeffneten Container und ist
    der oberste Treffer an seiner Mitte (also klickbar).
  * Ein Klick darauf fuellt den Ergebniskasten sichtbar.

Lagen: Sitzungsbetrieb (persoenliche Zugaenge AUS – so steht es auf DEV)
und gespeicherter eigener Zugang (persoenliche Zugaenge AN).

Exit 0 gruen, 1 FAIL, 2 konnte nicht laufen.
    python3 tests/live_zugang_probe_ui.py
"""
import json, os, socket, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
FRONT = Path(os.environ.get('PROBE_FRONTEND') or (REPO / 'frontend'))
BILDER = Path.home() / '.jarvis-abnahme' / 'zugang_probe'
OK = FAIL = 0


def check(name, bed, info=''):
    global OK, FAIL
    if bed:
        print(f'  OK   {name}'); OK += 1
    else:
        print(f'  FAIL {name}' + (f'  [{info}]' if info else '')); FAIL += 1


def freier_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


KONTO_SZ = {'server_konfiguriert': True, 'basis_url': 'https://wiki.beispiel.de',
            'persoenlich_erlaubt': False, 'sitzungs_modus': True, 'vorhanden': False,
            'angemeldet': False, 'sammel_vorhanden': True}
KONTO_EIGEN = {'server_konfiguriert': True, 'basis_url': 'https://wiki.beispiel.de',
               'persoenlich_erlaubt': True, 'sitzungs_modus': False, 'vorhanden': True,
               'aktiv': True, 'sammel_vorhanden': True}
SAP_SZ = {'configured': True, 'kachel_pflicht': True, 'quelle': 'sammel',
          'connection_type': 'odata', 'odata': True, 'hana': False, 'rfc': False}
SAP_EIGEN = {'configured': True, 'kachel_pflicht': False, 'quelle': 'persoenlich',
             'connection_type': 'odata', 'odata': True, 'hana': False, 'rfc': False}

# Seite -> (HTML, Freigabe, Probe-Knopf, Ausgabe, Lagen{name: (Antworten)})
SEITEN = {
    'confluence': ('confluence_addon.html', 'confluence', 'ca-acc-probe', 'ca-acc-probe-out', {
        'Sitzungsbetrieb': {'/api/confluence/account': {'ok': True, 'account': KONTO_SZ}},
        'eigener Zugang': {'/api/confluence/account': {'ok': True, 'account': KONTO_EIGEN}},
    }, {'/api/confluence/spaces': {'ok': True, 'count': 2, 'zugang': {'quelle': 'sammel', 'hinweis': 'x'},
                                   'spaces': [{'key': 'SONDEA', 'name': 'Sonde A'},
                                              {'key': 'SONDEB', 'name': 'Sonde B'}]}}),
    'jira': ('jira_addon.html', 'jira_assist', 'ja-acc-probe', 'ja-acc-probe-out', {
        'Sitzungsbetrieb': {'/api/jira/account': {'ok': True, 'account': KONTO_SZ}},
        'eigener Zugang': {'/api/jira/account': {'ok': True, 'account': KONTO_EIGEN}},
    }, {'/api/jira/search': {'ok': True, 'total': 1, 'results': [{'key': 'PRJA-1', 'summary': 'Sonde'}]},
        '/api/jira/assist/health': {'ok': True}}),
    'sap': ('sap.html', 'sap', 'sp-acc-probe', 'sp-acc-probe-out', {
        'Sitzungsbetrieb': {'/api/sap/status': dict(SAP_SZ, ok=True)},
        'eigener Zugang': {'/api/sap/status': dict(SAP_EIGEN, ok=True)},
    }, {'/api/sap/odata/services': {'ok': True, 'count': 1, 'services': ['sap/API_SONDE_SRV']},
        '/api/sap/account': {'ok': True, 'account': {}}}),
    'vemas': ('vemas.html', 'vemas', 'vm-acc-probe', 'vm-acc-probe-out', {
        'Sitzungsbetrieb': {'/api/vemas/status': dict(SAP_SZ, ok=True)},
        'eigener Zugang': {'/api/vemas/status': dict(SAP_EIGEN, ok=True)},
    }, {'/api/vemas/resources': {'ok': True, 'resources': [{'name': 'Projekte', 'pfad': 'projects'}]},
        '/api/vemas/query': {'ok': True, 'columns': ['Nummer'], 'rows': [{'Nummer': 1}]},
        '/api/vemas/account': {'ok': True, 'account': {}}}),
}

ATTRAPPE = r"""
(function(){
  try { localStorage.setItem('jarvis_token', 'testtoken'); } catch(e) {}
  var A = __ANTWORTEN__;
  var j = function(d){ return Promise.resolve({ok: true, status: 200,
      json: function(){ return Promise.resolve(d); },
      text: function(){ return Promise.resolve(JSON.stringify(d)); },
      blob: function(){ return Promise.resolve(new Blob(['x'])); }}); };
  window.fetch = function(u){
    var p = String(u).split('?')[0];
    if (p === '/api/me') { var pm = {}; pm['__PERM__'] = true;
      return j({ok: true, username: 'anna', permissions: pm, is_admin: false}); }
    if (p === '/api/verify-token') return j({ok: true, valid: true, username: 'anna'});
    if (A[p] !== undefined) return j(A[p]);
    return j({ok: true});
  };
})();
"""


def main():
    arbeit = Path(tempfile.mkdtemp(prefix='zgprobe-'))
    (arbeit / 'static').symlink_to(FRONT)
    for html, *_ in SEITEN.values():
        (arbeit / html).symlink_to(FRONT / html)
    port = freier_port()
    srv = subprocess.Popen([sys.executable, '-m', 'http.server', str(port), '-b', '127.0.0.1'],
                           cwd=arbeit, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    profil = Path(tempfile.mkdtemp(prefix='zgprobe-chrome-'))
    dport = freier_port()
    chrome = subprocess.Popen([
        'google-chrome', '--headless=new', '--no-sandbox', '--disable-gpu',
        f'--remote-debugging-port={dport}', f'--user-data-dir={profil}',
        '--remote-allow-origins=*', '--window-size=1280,1000', 'about:blank'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        time.sleep(2.5)
        for _ in range(40):
            try:
                ziel = [s for s in json.load(urllib.request.urlopen(
                    f'http://127.0.0.1:{dport}/json/list')) if s.get('type') == 'page']
                if ziel:
                    break
            except Exception:
                pass
            time.sleep(0.4)
        else:
            print('Exit 2: kein CDP-Ziel'); sys.exit(2)
        import websockets.sync.client as wsc
        ws = wsc.connect(ziel[0]['webSocketDebuggerUrl'], max_size=40 * 1024 * 1024)
        n = [0]

        def ruf(m, p=None):
            n[0] += 1
            ws.send(json.dumps({'id': n[0], 'method': m, 'params': p or {}}))
            while True:
                a = json.loads(ws.recv())
                if a.get('id') == n[0]:
                    return a.get('result', {})

        def js(ausdruck):
            r = ruf('Runtime.evaluate', {'expression': ausdruck, 'returnByValue': True,
                                         'awaitPromise': True})
            return r.get('result', {}).get('value')

        def klick(x, y):
            for t in ('mousePressed', 'mouseReleased'):
                ruf('Input.dispatchMouseEvent', {'type': t, 'x': x, 'y': y,
                                                 'button': 'left', 'clickCount': 1})

        ruf('Page.enable')
        BILDER.mkdir(parents=True, exist_ok=True)
        skript_id = None
        for name, (html, perm, btn, out, lagen, fach) in SEITEN.items():
            for lage, ant in lagen.items():
                print(f'\n── {name} · {lage}')
                alle = dict(fach); alle.update(ant)
                quelle = ATTRAPPE.replace('__ANTWORTEN__', json.dumps(alle)).replace('__PERM__', perm)
                if skript_id:
                    ruf('Page.removeScriptToEvaluateOnNewDocument', {'identifier': skript_id})
                skript_id = ruf('Page.addScriptToEvaluateOnNewDocument',
                                {'source': quelle}).get('identifier')
                ruf('Page.navigate', {'url': f'http://127.0.0.1:{port}/{html}'})
                time.sleep(3.0)
                geladen = js(f"!!document.getElementById('{btn}') && location.pathname.endsWith('{html}')")
                check('Positivkontrolle: Seite geladen, Probe-Knopf im DOM', geladen is True,
                      js('location.href'))
                if not geladen:
                    continue
                # Der SICHTBARE Zugangs-Container: der, dessen <summary> ein
                # Rechteck hat (der andere steht auf display:none).
                info = js(r"""(function(){
                  var c = Array.from(document.querySelectorAll('details')).filter(function(d){
                    return /-sz-sect$|-sect-account$/.test(d.id) && d.getClientRects().length; });
                  return c.map(function(d){ var r = d.querySelector('summary').getBoundingClientRect();
                    return {id: d.id, open: d.open, x: r.left + 12, y: r.top + r.height / 2}; });
                })()""") or []
                check('genau EIN Zugangs-Container sichtbar', len(info) == 1, json.dumps(info))
                if not info:
                    continue
                c = info[0]
                check('Ausgangslage zugeklappt (Vorgabe)', c['open'] is False, json.dumps(c))
                js(f"window.scrollTo(0, 0)")
                c = js(f"""(function(){{ var d = document.getElementById('{c['id']}');
                    d.scrollIntoView({{block: 'start'}}); window.scrollBy(0, -80);
                    var r = d.querySelector('summary').getBoundingClientRect();
                    return {{id: d.id, open: d.open, x: r.left + 12, y: r.top + r.height / 2}}; }})()""")
                klick(c['x'], c['y'])
                time.sleep(0.5)
                check('nach dem Klick offen', js(f"document.getElementById('{c['id']}').open") is True)
                time.sleep(4.0)
                check('nach 4 s weiter offen (kein Zurueckschnappen)',
                      js(f"document.getElementById('{c['id']}').open") is True)
                lage_btn = js(f"""(function(){{ var b = document.getElementById('{btn}');
                    b.scrollIntoView({{block: 'center'}});
                    var r = b.getBoundingClientRect();
                    var t = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
                    return {{sichtbar: b.checkVisibility({{checkVisibilityCSS: true}}),
                            imContainer: !!b.closest('#{c['id']}'),
                            oben: t === b || b.contains(t), x: r.left + r.width / 2,
                            y: r.top + r.height / 2, w: r.width}}; }})()""")
                check('Probe-Knopf sichtbar', bool(lage_btn and lage_btn['sichtbar']), json.dumps(lage_btn))
                check('Probe-Knopf liegt im geoeffneten Container',
                      bool(lage_btn and lage_btn['imContainer']), json.dumps(lage_btn))
                check('Probe-Knopf ist anklickbar (oberster Treffer)',
                      bool(lage_btn and lage_btn['oben']), json.dumps(lage_btn))
                if lage_btn and lage_btn['sichtbar'] and lage_btn['oben']:
                    klick(lage_btn['x'], lage_btn['y'])
                    time.sleep(1.2)
                    erg = js(f"""(function(){{ var o = document.getElementById('{out}');
                        return {{sichtbar: o.checkVisibility(), text: (o.textContent || '').trim().slice(0, 80)}}; }})()""")
                    check('Klick fuellt den Ergebniskasten sichtbar',
                          bool(erg and erg['sichtbar'] and erg['text']), json.dumps(erg))
                bild = ruf('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False})
                if bild.get('data'):
                    import base64
                    (BILDER / f"{name}_{lage.replace(' ', '_')}.png").write_bytes(
                        base64.b64decode(bild['data']))
        ws.close()
    finally:
        chrome.kill(); srv.kill()
        # Profil und Probeseite abraeumen: ein Chrome-Profil ist ~100 MB, und
        # /tmp ist ein tmpfs (am 2026-11-16 dadurch voll gelaufen). Chrome
        # schreibt nach kill() noch – ignore_errors, damit das Aufraeumen das
        # Ergebnis nicht kippt (Register: ENOTEMPTY).
        import shutil
        time.sleep(0.5)
        shutil.rmtree(profil, ignore_errors=True)
        shutil.rmtree(arbeit, ignore_errors=True)
    print(f'\nERGEBNIS: {OK} OK, {FAIL} FAIL   (Bilder: {BILDER})')
    sys.exit(1 if FAIL else 0)


if __name__ == '__main__':
    main()
