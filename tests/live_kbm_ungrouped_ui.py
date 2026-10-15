#!/usr/bin/env python3
"""
Optische Abnahme des Kaestchens "nicht zugeordnet" in der Wissensgruppen-Tabelle.

Gemessen wird im ECHTEN Chrome gegen das ECHTE CSS und den ECHTEN Renderer
(kbmatrix.js) - jsdom rechnet kein Layout; Ueberlauf, Position und Kontrast
sieht nur ein Browser.

⚠ DIE PROBESEITE LIEGT NICHT UNTER frontend/ (Register): `test_theme_default`
laeuft ueber JEDE HTML-Datei dort und verlangt das Anti-Flacker-Skript - eine
Wegwerfseite dort laesst einen FREMDEN Waechter fehlschlagen. Sie liegt in einem
Wegwerf-Ordner mit Symlinks auf css/ und js/.
"""
import base64, json, shutil, socket, subprocess, sys, tempfile, time, urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OK = FAIL = 0


def check(name, bed, info=''):
    global OK, FAIL
    if bed:
        print(f'  \033[32m✓\033[0m {name}'); OK += 1
    else:
        print(f'  \033[31m✗\033[0m {name}' + (f'  [{info}]' if info else '')); FAIL += 1


def freier_port():
    s = socket.socket(); s.bind(('127.0.0.1', 0)); p = s.getsockname()[1]; s.close(); return p


SEITE = """<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<link rel="stylesheet" href="css/theme.css"><link rel="stylesheet" href="css/style.css">
</head><body>
<script>try{if(localStorage.getItem('jarvis_theme')!=='dark')document.body.classList.add('light');}catch(e){}</script>
<script src="js/icons.js"></script>
<script src="js/i18n.js"></script>
<script>
// Attrappen: nur die Endpunkte bzw. Schnittstellen, die kbmatrix.open() liest.
localStorage.setItem('jarvis_token','pruef:tok');
const DATEIEN=[{folder:'data/rag/doku',files:[
  {path:'data/rag/doku/anleitung.md',name:'anleitung.md'},
  {path:'data/rag/doku/preise.md',name:'preise.md'},
  {path:'data/rag/doku/vertrag.pdf',name:'vertrag.pdf'},
  {path:'data/rag/doku/notiz.txt',name:'notiz.txt'},
  {path:'data/rag/doku/handbuch_technik_aussendienst_2026.md',name:'handbuch_technik_aussendienst_2026.md'}]}];
const ZUORD={'data/rag/doku/preise.md':['g1'],'data/rag/doku/vertrag.pdf':['g1','g2']};
const GRUPPEN=[{id:'g1',name:'Vertrieb',color:'#3b82f6'},{id:'g2',name:'Recht',color:'#10b981'},
                {id:'g3',name:'Technik',color:'#f59e0b'}];
window.fetch=async(u)=>{const p=String(u).split('?')[0];
  if(p==='/api/knowledge/files')return{ok:true,json:async()=>DATEIEN};
  if(p==='/api/knowledge/pending')return{ok:true,json:async()=>[]};
  return{ok:true,json:async()=>({ok:true,files:[]})};};
window.KbGroups={UNGROUPED:'ungrouped',all:()=>GRUPPEN,load:async()=>GRUPPEN,
  getMap:async()=>JSON.parse(JSON.stringify(ZUORD)),setAssignment:async()=>({ok:true})};
</script>
<script src="js/kbmatrix.js"></script>
<script>window.addEventListener('load',()=>{window.KbMatrix.open();});</script>
</body></html>"""


def main():
    global FAIL
    arbeit = Path(tempfile.mkdtemp(prefix='kbmung-'))
    (arbeit / 'css').symlink_to(REPO / 'frontend/css')
    (arbeit / 'js').symlink_to(REPO / 'frontend/js')
    (arbeit / 'probe.html').write_text(SEITE, encoding='utf-8')
    port = freier_port()
    srv = subprocess.Popen([sys.executable, '-m', 'http.server', str(port), '-b', '127.0.0.1'],
                           cwd=arbeit, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    profil = Path(tempfile.mkdtemp(prefix='kbmung-chrome-'))
    dport = freier_port()
    chrome = subprocess.Popen([
        'google-chrome', '--headless=new', '--no-sandbox', '--disable-gpu',
        f'--remote-debugging-port={dport}', f'--user-data-dir={profil}',
        '--remote-allow-origins=*', '--window-size=1280,860', 'about:blank'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    gruende = {}
    try:
        time.sleep(2.5)
        for _ in range(40):
            try:
                seiten = json.load(urllib.request.urlopen(f'http://127.0.0.1:{dport}/json/list'))
                # ⚠ NUR type == "page" - /json/list liefert auch die eingebauten
                # Chrome-Erweiterungen; wer blind [0] nimmt, misst eine
                # background.html (Register).
                ziel = [s for s in seiten if s.get('type') == 'page']
                if ziel:
                    break
            except Exception:
                pass
            time.sleep(0.4)
        else:
            print('\033[31mExit 2: kein CDP-Ziel\033[0m'); sys.exit(2)

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

        ruf('Page.enable')
        for thema, dunkel in (('dunkel', True), ('hell', False)):
            print(f'\n\033[1m{thema}\033[0m')
            # ⚠ Der Schluessel muss VOR dem ersten Skript der Seite stehen -
            # Runtime.evaluate auf about:blank ist ein ANDERER Origin und
            # erreicht die Seite nie (gemessen: sonst zweimal hell).
            ruf('Page.addScriptToEvaluateOnNewDocument', {'source':
                f"try{{localStorage.setItem('jarvis_theme','{'dark' if dunkel else 'light'}')}}catch(e){{}}"})
            ruf('Page.navigate', {'url': f'http://127.0.0.1:{port}/probe.html'})
            time.sleep(1.0)
            ruf('Page.reload', {'ignoreCache': True})
            time.sleep(1.8)

            klasse = js('document.body.className')
            check(f'das Thema ist wirklich {thema}',
                  ('light' not in klasse) if dunkel else ('light' in klasse), klasse)

            # ⚠ POSITIVKONTROLLE: steht die Tabelle ueberhaupt? Ohne sie ist
            # jede Messung darunter trivial wahr (0 <= 0).
            bereit = js("!!document.querySelector('#kbm-overlay .kbm-nogrp') && "
                        "document.querySelector('#kbm-overlay .kbm-nogrp-lbl').getBoundingClientRect().width")
            if not bereit:
                print('\033[31mExit 2: Tabelle/Kaestchen nicht aufgebaut (CSS/JS 404?)\033[0m')
                sys.exit(2)
            check('das Kaestchen ist gerendert und hat eine Groesse', bereit > 60, f'{bereit}')

            m = js("""(() => {
                const ov = document.getElementById('kbm-overlay');
                const lbl = ov.querySelector('.kbm-nogrp-lbl');
                const kast = ov.querySelector('.kbm-nogrp');
                const feld = ov.querySelector('.kbm-filter');
                const zu = ov.querySelector('.kbm-close');
                const kopf = ov.querySelector('.kbm-head');
                const cnt = ov.querySelector('.kbm-count');
                const r = e => { const b = e.getBoundingClientRect();
                    return { l:b.left, r:b.right, t:b.top, b:b.bottom, w:b.width, h:b.height }; };
                return { lbl:r(lbl), kast:r(kast), feld:r(feld), zu:r(zu), kopf:r(kopf), cnt:r(cnt),
                         kopfScroll: kopf.scrollWidth, kopfClient: kopf.clientWidth,
                         zaehler: cnt.textContent.trim(),
                         text: lbl.textContent.trim(),
                         cntFarbe: getComputedStyle(cnt).color,
                         lblFarbe: getComputedStyle(lbl).color,
                         grund: getComputedStyle(ov.querySelector('.kbm-panel')).backgroundColor,
                         gezeigt: [...ov.querySelectorAll('tbody tr')].filter(t=>t.style.display!=='none').length };
            })()""")

            check('das Kaestchen steht LINKS vom Filterfeld',
                  m['lbl']['r'] <= m['feld']['l'] + 1,
                  f"Label endet {m['lbl']['r']:.0f}, Feld beginnt {m['feld']['l']:.0f}")
            check('⚠ beide Filter stehen dicht beieinander (kein Raum dazwischen)',
                  (m['feld']['l'] - m['lbl']['r']) <= 30,
                  f"Abstand {m['feld']['l'] - m['lbl']['r']:.0f}px")
            check('Kaestchen und Beschriftung stehen in EINER Zeile',
                  abs(m['lbl']['t'] - m['kast']['t']) < 14,
                  f"{m['lbl']['t']:.0f} vs {m['kast']['t']:.0f}")
            check('das Kaestchen ist sichtbar gross genug', m['kast']['w'] >= 10 and m['kast']['h'] >= 10,
                  f"{m['kast']['w']:.0f}x{m['kast']['h']:.0f}")
            check('der Schliessen-Knopf bleibt ganz rechts erreichbar',
                  m['zu']['r'] <= m['kopf']['r'] + 1 and m['zu']['l'] >= m['feld']['r'] - 1)
            check('kein waagerechter Ueberlauf in der Kopfzeile',
                  m['kopfScroll'] <= m['kopfClient'] + 1,
                  f"{m['kopfScroll']} > {m['kopfClient']}")
            check('⚠ der Zaehler nennt gezeigt UND gesamt', '3' in m['zaehler'] and '5' in m['zaehler'],
                  m['zaehler'])
            check('es sind wirklich nur die ungruppierten sichtbar', m['gezeigt'] == 3,
                  f"sichtbar: {m['gezeigt']}")
            check('die Beschriftung ist gesetzt', len(m['text']) > 3, m['text'])

            # Kontrast: Beschriftung und Zaehler gegen die Kopfzeilen-Flaeche.
            def rgb(s):
                z = [float(x) for x in s[s.index('(') + 1:s.index(')')].replace(',', ' ').split()]
                return z[:3] + ([z[3]] if len(z) > 3 else [1.0])

            def lum(c):
                def k(v):
                    v /= 255
                    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
                return .2126 * k(c[0]) + .7152 * k(c[1]) + .0722 * k(c[2])

            hg = rgb(m['grund'])
            for was, farbe in (('Beschriftung', m['lblFarbe']), ('Zaehler', m['cntFarbe'])):
                vg = rgb(farbe)
                # ⚠ Halbtransparenz ueber den gemessenen Grund legen - eine
                # rgba-Farbe als deckend zu lesen ergibt Traumwerte (Register).
                a = vg[3]
                misch = [vg[i] * a + hg[i] * (1 - a) for i in range(3)]
                L1, L2 = lum(misch), lum(hg)
                k = (max(L1, L2) + .05) / (min(L1, L2) + .05)
                check(f'{was} lesbar (Kontrast {k:.2f}:1)', k >= 4.5, f'{farbe} auf {m["grund"]}')

            gruende[thema] = (m['lblFarbe'], m['grund'])

            # ⚠ Sonderfall messen, danach fuer den Augenschein zuruecknehmen:
            # ein Screenshot des Sonderfalls sagt ueber den Normalzustand nichts.
            lang = js("""(() => {
                const ov = document.getElementById('kbm-overlay');
                const sp = ov.querySelector('.kbm-nogrp-lbl span');
                const alt = sp.textContent;
                sp.textContent = 'nicht zugeordnet und sonst gar nichts weiter ueberhaupt';
                const kopf = ov.querySelector('.kbm-head');
                const feld = ov.querySelector('.kbm-filter').getBoundingClientRect();
                const zu = ov.querySelector('.kbm-close').getBoundingClientRect();
                const r = { ueber: kopf.scrollWidth - kopf.clientWidth,
                            feldW: feld.width, zuR: zu.right, kopfR: kopf.getBoundingClientRect().right };
                sp.textContent = alt;
                return r;
            })()""")
            check('⚠ eine ueberlange Beschriftung sprengt die Kopfzeile nicht',
                  lang['ueber'] <= 1 and lang['zuR'] <= lang['kopfR'] + 1, str(lang))

            # ⚠ Schmaleres Fenster: die Kopfzeile bricht NICHT um - laeuft dort
            # etwas heraus, ist der Schliessen-Knopf unerreichbar. Danach wieder
            # zuruecksetzen, sonst zeigt der Screenshot den Sonderfall.
            ruf('Emulation.setDeviceMetricsOverride',
                {'width': 900, 'height': 860, 'deviceScaleFactor': 1, 'mobile': False})
            time.sleep(0.5)
            eng = js("""(() => { const ov = document.getElementById('kbm-overlay');
                const kopf = ov.querySelector('.kbm-head');
                const lbl = ov.querySelector('.kbm-nogrp-lbl').getBoundingClientRect();
                const zu = ov.querySelector('.kbm-close').getBoundingClientRect();
                const kr = kopf.getBoundingClientRect();
                return { ueber: kopf.scrollWidth - kopf.clientWidth, lblW: lbl.width,
                         zuR: zu.right, kopfR: kr.right, zuW: zu.width }; })()""")
            check('⚠ bei 900px Breite laeuft die Kopfzeile nicht ueber',
                  eng['ueber'] <= 1 and eng['zuR'] <= eng['kopfR'] + 1 and eng['zuW'] > 8,
                  str(eng))
            check('die Beschriftung wird dabei nicht zusammengequetscht',
                  eng['lblW'] > 90, f"{eng['lblW']:.0f}px")
            ruf('Emulation.clearDeviceMetricsOverride')
            time.sleep(0.5)

            bild = ruf('Page.captureScreenshot', {'format': 'png'})['data']
            ziel_png = Path.home() / f'kbm-ungrouped-{thema}.png'
            ziel_png.write_bytes(base64.b64decode(bild))
            print(f'  Screenshot: {ziel_png}')

        # ⚠ POSITIVKONTROLLE: waren es wirklich ZWEI Laeufe? Identische Farben
        # heissen, dass das Thema nie gewechselt hat - dann ist eines ungeprueft.
        check('⚠ hell und dunkel waren zwei VERSCHIEDENE Messungen',
              len(gruende) == 2 and gruende['dunkel'] != gruende['hell'], str(gruende))
        ws.close()
    finally:
        chrome.terminate(); srv.terminate()
        shutil.rmtree(profil, ignore_errors=True)
        shutil.rmtree(arbeit, ignore_errors=True)
    print(f'\n\033[1mErgebnis: {OK} OK, {FAIL} FAIL\033[0m')
    sys.exit(1 if FAIL else 0)


if __name__ == '__main__':
    main()
