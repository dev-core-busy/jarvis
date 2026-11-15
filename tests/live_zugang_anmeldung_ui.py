#!/usr/bin/env python3
"""
Optische Abnahme des zweiten Anmeldeschritts "Weitere Anmeldungen" (2026-11-15).

ECHTES Chrome, ECHTES CSS (theme.css + style.css), ECHTES Modul
(zugang_anmeldung.js) und der ECHTE Block #login-screen aus settings.html
(zur Laufzeit herausgeschnitten, nicht abgetippt). jsdom rechnet kein Layout –
Ueberlauf, Breite und Kontrast sieht nur ein Browser.

Die Probeseite liegt NICHT unter frontend/ (Register: test_theme_default laeuft
ueber jede HTML-Datei dort), sondern in einem Wegwerf-Ordner mit Symlinks.

Gemessen je Thema (hell/dunkel) und Breite (1280/380 px), mit einem Fehlerfall:
Schritt sichtbar, Formular verborgen, kein waagerechter Ueberlauf, Felder im
Container, Kontrast von Hinweis und Fehlertext >= 4,5:1. Bilder landen im HOME
(0700), nicht in /tmp (Register).

Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
    python3 tests/live_zugang_anmeldung_ui.py
"""
import base64, json, re, socket, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
BILDER = Path.home() / '.jarvis-abnahme' / 'zugang_anmeldung'
OK = FAIL = 0


def check(name, bed, info=''):
    global OK, FAIL
    if bed:
        print(f'  OK   {name}'); OK += 1
    else:
        print(f'  FAIL {name}' + (f'  [{info}]' if info else '')); FAIL += 1


def freier_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


def login_block() -> str:
    html = (REPO / 'frontend/settings.html').read_text(encoding='utf-8')
    a = html.find('<div id="login-screen"')
    b = html.find('<!-- ═══ Change-Password Modal')
    if a < 0 or b < a:
        print('Exit 2: #login-screen in settings.html nicht gefunden'); sys.exit(2)
    return html[a:b]


SEITE = """<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<link rel="stylesheet" href="css/theme.css"><link rel="stylesheet" href="css/style.css">
</head><body>
<script>try{if(localStorage.getItem('jarvis_theme')!=='dark')document.body.classList.add('light');}catch(e){}</script>
__BLOCK__
<script src="js/i18n.js"></script>
<script>
const EINTRAEGE=[
 {system:'sap',art:'kennwort',feld:'password',benutzer:'MUSTERMANN',benutzer_feld:'username'},
 {system:'vemas',art:'kennwort',feld:'password',benutzer:'mustermann',benutzer_feld:'username'},
 {system:'jira',art:'token',feld:'api_token',benutzer:'',benutzer_feld:''},
 {system:'confluence',art:'token',feld:'api_token',benutzer:'',benutzer_feld:''}];
window.fetch=async(u,i)=>{const p=String(u).split('?')[0];
  const j=(st,d)=>({ok:st<400,status:st,json:async()=>d});
  if(p==='/api/zugaenge/anmeldung')return j(200,{ok:true,anmeldungen:EINTRAEGE});
  if(p==='/api/sap/account')return j(200,{ok:true,account:{}});
  if(p==='/api/sap/test')return j(200,{ok:true});
  if(p==='/api/confluence/account/sitzung')return j(400,{ok:false,
     error:'Confluence lehnt den Token ab: 401 Unauthorized – bitte einen gueltigen persoenlichen Token eintragen'});
  return j(404,{ok:false,error:'?'});};
</script>
<script src="js/zugang_anmeldung.js"></script>
<script>window.addEventListener('load',()=>{window.ZugangAnmeldung.schritt('tok');});</script>
</body></html>"""


def main():
    arbeit = Path(tempfile.mkdtemp(prefix='zganm-'))
    (arbeit / 'css').symlink_to(REPO / 'frontend/css')
    (arbeit / 'js').symlink_to(REPO / 'frontend/js')
    (arbeit / 'probe.html').write_text(SEITE.replace('__BLOCK__', login_block()), encoding='utf-8')
    BILDER.mkdir(parents=True, exist_ok=True)
    BILDER.chmod(0o700)
    port = freier_port()
    srv = subprocess.Popen([sys.executable, '-m', 'http.server', str(port), '-b', '127.0.0.1'],
                           cwd=arbeit, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    profil = Path(tempfile.mkdtemp(prefix='zganm-chrome-'))
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
                seiten = json.load(urllib.request.urlopen(f'http://127.0.0.1:{dport}/json/list'))
                ziel = [s for s in seiten if s.get('type') == 'page']
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

        def rgb(s):
            if s.startswith('color('):
                # Chrome: color(srgb r g b[ / a]) mit Anteilen 0..1 (Register)
                z = [float(x) * 255 for x in s.replace(')', ' ').split()[1:4]]
                return z + [1.0]
            z = [float(x) for x in s[s.index('(') + 1:s.index(')')].replace(',', ' ').replace('/', ' ').split()]
            return z[:3] + ([z[3]] if len(z) > 3 else [1.0])

        def lum(c):
            def k(v):
                v /= 255
                return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
            return .2126 * k(c[0]) + .7152 * k(c[1]) + .0722 * k(c[2])

        def kontrast(vg, hg):
            a = vg[3]
            m = [vg[i] * a + hg[i] * (1 - a) for i in range(3)]
            l1, l2 = sorted((lum(m), lum(hg)), reverse=True)
            return (l1 + .05) / (l2 + .05)

        ruf('Page.enable')
        farben = {}
        for thema, dunkel in (('dunkel', True), ('hell', False)):
            for breite in (1280, 380):
                print(f'\n{thema}, {breite} px')
                ruf('Emulation.setDeviceMetricsOverride', {'width': breite, 'height': 1000,
                                                           'deviceScaleFactor': 1, 'mobile': breite < 500})
                ruf('Page.addScriptToEvaluateOnNewDocument', {'source':
                    f"try{{localStorage.setItem('jarvis_theme','{'dark' if dunkel else 'light'}')}}catch(e){{}}"})
                ruf('Page.navigate', {'url': f'http://127.0.0.1:{port}/probe.html'})
                time.sleep(1.0)
                ruf('Page.reload', {'ignoreCache': True})
                time.sleep(1.8)
                klasse = js('document.body.className') or ''
                check(f'das Thema ist wirklich {thema}',
                      ('light' not in klasse) if dunkel else ('light' in klasse), klasse)
                # Positivkontrolle: der Schritt steht wirklich da.
                zeilen = js("document.querySelectorAll('#zg-liste .zg-zeile').length")
                if not zeilen:
                    print('Exit 2: zweiter Schritt nicht aufgebaut (CSS/JS 404?)'); sys.exit(2)
                check('vier Systeme gezeichnet', zeilen == 4, str(zeilen))
                # Fehlerfall herstellen: SAP gelingt, Confluence scheitert.
                js("""(() => {
                    const z = s => document.querySelector('.zg-zeile[data-system="'+s+'"] .zg-geheim');
                    z('sap').value='x'; z('confluence').value='y';
                    document.getElementById('zg-weiter').click(); })()""")
                time.sleep(0.8)
                m = js("""(() => {
                    const r = e => { const b = e.getBoundingClientRect(); return {l:b.left,r:b.right,w:b.width,h:b.height,t:b.top}; };
                    const box = document.getElementById('zg-schritt');
                    const cont = document.querySelector('.login-container');
                    const form = document.getElementById('login-form');
                    const err = document.querySelector('.zg-zeile[data-system="confluence"] .zg-status');
                    const ok = document.querySelector('.zg-zeile[data-system="sap"] .zg-status');
                    const hint = box.querySelector('.zg-hinweis');
                    const meld = document.getElementById('zg-meldung');
                    const inputs = [...box.querySelectorAll('input, button')].map(r);
                    const zeile = document.querySelector('.zg-zeile');
                    return { box:r(box), cont:r(cont), formSichtbar: form.getBoundingClientRect().height > 0,
                             inputs, docW: document.documentElement.scrollWidth, winW: window.innerWidth,
                             boxScroll: box.scrollWidth, boxClient: box.clientWidth,
                             errText: err.textContent, okText: ok.textContent,
                             meldSichtbar: !meld.hidden && meld.getBoundingClientRect().height > 0,
                             hintFarbe: getComputedStyle(hint).color,
                             errFarbe: getComputedStyle(err).color,
                             meldFarbe: getComputedStyle(meld).color,
                             grund: getComputedStyle(zeile).backgroundColor,
                             cardGrund: getComputedStyle(cont).backgroundColor,
                             bodyGrund: getComputedStyle(document.body).backgroundColor };
                })()""")
                check('Schritt sichtbar, Anmeldeformular verborgen',
                      m['box']['h'] > 100 and not m['formSichtbar'], f"{m['box']['h']} {m['formSichtbar']}")
                check('kein waagerechter Ueberlauf der Seite', m['docW'] <= m['winW'] + 1,
                      f"{m['docW']} > {m['winW']}")
                check('kein Ueberlauf im Schritt', m['boxScroll'] <= m['boxClient'] + 1,
                      f"{m['boxScroll']} > {m['boxClient']}")
                check('alle Felder/Knoepfe liegen im Schritt',
                      all(i['l'] >= m['box']['l'] - 1 and i['r'] <= m['box']['r'] + 1 for i in m['inputs']))
                check('Fehlergrund steht an der Zeile', 'lehnt' in m['errText'], m['errText'])
                check('erfolgreiche Zeile meldet angemeldet', 'angemeldet' in m['okText'] or 'signed' in m['okText'],
                      m['okText'])
                check('Sammelmeldung sichtbar', m['meldSichtbar'])
                hg_zeile = rgb(m['grund'])
                # Der Hinweis steht nicht in einer Zeile, sondern auf der Karte/Seite:
                # Karte, wenn deckend, sonst Seitengrund.
                karte = rgb(m['cardGrund'])
                hg_hint = karte if karte[3] >= 0.99 else rgb(m['bodyGrund'])
                k_hint = kontrast(rgb(m['hintFarbe']), hg_hint)
                k_err = kontrast(rgb(m['errFarbe']), hg_zeile)
                k_meld = kontrast(rgb(m['meldFarbe']), hg_hint)
                farben[thema] = m['bodyGrund']
                check('Kontrast Hinweis >= 4,5:1', k_hint >= 4.5, f'{k_hint:.2f}')
                check('Kontrast Fehlergrund >= 4,5:1', k_err >= 4.5, f'{k_err:.2f}')
                check('Kontrast Sammelmeldung >= 4,5:1', k_meld >= 4.5, f'{k_meld:.2f}')
                bild = ruf('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': True})
                ziel_bild = BILDER / f'{thema}_{breite}.png'
                ziel_bild.write_bytes(base64.b64decode(bild.get('data', '')))
                print(f'  Bild: {ziel_bild}')
        check('Positivkontrolle: hell und dunkel waren zwei verschiedene Messungen',
              farben.get('hell') != farben.get('dunkel'), str(farben))
    finally:
        chrome.kill(); srv.kill()
    print(f'\nERGEBNIS: {OK} OK, {FAIL} FAIL')
    return 1 if FAIL else 0


if __name__ == '__main__':
    sys.exit(main())
