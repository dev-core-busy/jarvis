#!/usr/bin/env python3
"""
Optische Abnahme des Tabellenkopfs der Wissensgruppen-Tabelle (/wissen ->
Massenzuordnung): senkrechte Gruppennamen und Spaltenhinterlegung.

Gemeldet war ein Kopf, in dem jede Gruppenspalte nur "● …" zeigte - die
Spalten sind ~46 px breit. Jetzt steht der Name senkrecht, Punkt und Zaehler
waagerecht darunter, und beim Ueberfahren einer Gruppenzelle wird die ganze
Spalte hinterlegt.

Gemessen im ECHTEN Chrome gegen das ECHTE CSS und den ECHTEN Renderer - jsdom
rechnet kein Layout, und ob ein Name abgeschnitten ist, sieht nur ein Browser.
Die Hinterlegung ist ein echtes Element (kein :hover), also auch im Screenshot
sichtbar; ausgeloest wird sie ueber echte Mausereignisse (Input.dispatchMouseEvent).

Die Probeseite liegt in einem Wegwerf-Ordner (nicht unter frontend/), aus
demselben Grund wie in live_kbm_ungrouped_ui.py.
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


# 15 Gruppen wie im gemeldeten Bildschirmfoto, darunter ein ueberlanger Name
# (muss gekuerzt werden) und eine Gruppe mit vierstelligem Zaehler (muss unter
# dem Namen in die schmale Spalte passen).
SEITE = """<!DOCTYPE html><html lang="de"><head><meta charset="utf-8">
<link rel="stylesheet" href="css/theme.css"><link rel="stylesheet" href="css/style.css">
</head><body>
<script>try{if(localStorage.getItem('jarvis_theme')!=='dark')document.body.classList.add('light');}catch(e){}</script>
<script src="js/icons.js"></script>
<script src="js/sitzung.js"></script>
<script src="js/i18n.js"></script>
<script>
localStorage.setItem('jarvis_token','pruef:tok');
const FARBEN=['#5eead4','#a855f7','#eab308','#d946ef','#64748b','#3b82f6','#22c55e','#9ca3af',
              '#dc2626','#ef4444','#f43f5e','#2563eb','#f97316','#4ade80','#38bdf8'];
const NAMEN=['Vertrieb','Recht','Technik','Einkauf','Archiv','Kundenlisten','Produkt',
             'Schnittstellen-Dokumentation-und-Kundenkommunikation-Confluence','Support',
             'Personal','Controlling','Entwicklung','Marketing','Qualitaet','Betrieb'];
const GRUPPEN=NAMEN.map((n,i)=>({id:'g'+i,name:n,color:FARBEN[i]}));
const files=[];const ZUORD={};
for(let i=0;i<1250;i++){const p='data/rag/doku/datei_'+i+'.md';files.push({path:p,name:'datei_'+i+'.md'});
  if(i<1180)ZUORD[p]=['g5'].concat(i%3?[]:['g1']);}
const DATEIEN=[{folder:'data/rag/doku',files}];
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
    arbeit = Path(tempfile.mkdtemp(prefix='kbmkopf-'))
    (arbeit / 'css').symlink_to(REPO / 'frontend/css')
    (arbeit / 'js').symlink_to(REPO / 'frontend/js')
    (arbeit / 'probe.html').write_text(SEITE, encoding='utf-8')
    port = freier_port()
    srv = subprocess.Popen([sys.executable, '-m', 'http.server', str(port), '-b', '127.0.0.1'],
                           cwd=arbeit, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    profil = Path(tempfile.mkdtemp(prefix='kbmkopf-chrome-'))
    dport = freier_port()
    chrome = subprocess.Popen([
        'google-chrome', '--headless=new', '--no-sandbox', '--disable-gpu',
        f'--remote-debugging-port={dport}', f'--user-data-dir={profil}',
        '--remote-allow-origins=*', '--window-size=1340,860', 'about:blank'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    farben = {}
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

        def maus(x, y):
            ruf('Input.dispatchMouseEvent', {'type': 'mouseMoved', 'x': x, 'y': y})
            time.sleep(0.15)

        ruf('Page.enable')
        for thema, dunkel in (('dunkel', True), ('hell', False)):
            print(f'\n\033[1m{thema}\033[0m')
            ruf('Page.addScriptToEvaluateOnNewDocument', {'source':
                f"try{{localStorage.setItem('jarvis_theme','{'dark' if dunkel else 'light'}')}}catch(e){{}}"})
            ruf('Page.navigate', {'url': f'http://127.0.0.1:{port}/probe.html'})
            time.sleep(1.0)
            ruf('Page.reload', {'ignoreCache': True})
            time.sleep(2.2)

            klasse = js('document.body.className')
            check(f'das Thema ist wirklich {thema}',
                  ('light' not in klasse) if dunkel else ('light' in klasse), klasse)

            # POSITIVKONTROLLE: Tabelle mit 15 Gruppenspalten steht. Den Filter
            # "nicht zugeordnet" ausschalten, damit Haken in der Tabelle stehen.
            n_grp = js("(()=>{const ov=document.getElementById('kbm-overlay'); if(!ov) return 0;"
                       "const k=ov.querySelector('.kbm-nogrp'); if(k&&k.checked){k.click();}"
                       "return ov.querySelectorAll('thead th.kbm-c-grp').length;})()")
            if n_grp != 15:
                print(f'\033[31mExit 2: Tabelle nicht aufgebaut ({n_grp} Gruppenspalten)\033[0m')
                sys.exit(2)
            time.sleep(0.3)

            k = js("""(() => {
                const ov = document.getElementById('kbm-overlay');
                const r = e => { const b = e.getBoundingClientRect();
                    return { l:b.left, r:b.right, t:b.top, b:b.bottom, w:b.width, h:b.height }; };
                const grp = [...ov.querySelectorAll('thead th.kbm-c-grp')].map(th => {
                    const v = th.querySelector('.kbm-th-vert'), f = th.querySelector('.kbm-th-foot');
                    return { th: r(th), v: r(v), vScroll: v.scrollHeight, vClient: v.clientHeight,
                             name: v.textContent, footScroll: f.scrollWidth, thClient: th.clientWidth,
                             foot: r(f), count: th.querySelector('.kbm-th-count').textContent };
                });
                const act = [...ov.querySelectorAll('thead th.kbm-c-act')].map(th => {
                    const v = th.querySelector('.kbm-th-vert');
                    return { th: r(th), text: v ? v.textContent : '', vScroll: v ? v.scrollHeight : 0,
                             vClient: v ? v.clientHeight : 0, thScrollW: th.scrollWidth, thClientW: th.clientWidth };
                });
                const wrap = ov.querySelector('.kbm-table-wrap');
                return { grp, act, wrapScrollW: wrap.scrollWidth, wrapClientW: wrap.clientWidth,
                         kopfH: r(ov.querySelector('thead')).h };
            })()""")

            senkrecht = [g for g in k['grp'] if g['v']['h'] > g['v']['w'] * 1.5 or len(g['name']) < 4]
            check('alle 15 Gruppennamen stehen senkrecht', len(senkrecht) == 15,
                  [(g['name'], round(g['v']['w']), round(g['v']['h'])) for g in k['grp']])
            kurz = [g for g in k['grp'] if len(g['name']) < 30]
            ganz = [g['name'] for g in kurz if g['vScroll'] <= g['vClient'] + 1]
            check('⚠ jeder normale Gruppenname ist VOLLSTAENDIG sichtbar (nicht gekuerzt)',
                  len(ganz) == len(kurz), f'{len(ganz)} von {len(kurz)}')
            lang = [g for g in k['grp'] if len(g['name']) >= 30][0]
            check('der ueberlange Name ist auf hoechstens 160 px gedeckelt',
                  lang['v']['h'] <= 161 and lang['vScroll'] > lang['vClient'],
                  f"{lang['v']['h']:.0f}px, scroll {lang['vScroll']}")
            check('jeder Name liegt innerhalb seiner Spalte',
                  all(g['v']['l'] >= g['th']['l'] - 1 and g['v']['r'] <= g['th']['r'] + 1 for g in k['grp']))
            g5 = [g for g in k['grp'] if g['count'] == '1180']
            check('⚠ der vierstellige Zaehler passt in die schmale Spalte',
                  bool(g5) and g5[0]['footScroll'] <= g5[0]['thClient'] + 1,
                  str(g5[0]['footScroll'] if g5 else '-') + ' > ' + str(g5[0]['thClient'] if g5 else '-'))
            check('der Zaehler steht UNTER dem Namen',
                  all(g['foot']['t'] >= g['v']['b'] - 1 for g in k['grp']))
            check('"Öffnen" und "Löschen" stehen vollstaendig und senkrecht',
                  len(k['act']) == 2 and all(a['vScroll'] <= a['vClient'] + 1 and a['th']['h'] > a['th']['w']
                                             for a in k['act']), str([a['text'] for a in k['act']]))
            check('kein waagerechter Ueberlauf der Tabelle',
                  k['wrapScrollW'] <= k['wrapClientW'] + 1, f"{k['wrapScrollW']} > {k['wrapClientW']}")
            check('die Kopfzeile bleibt in vernuenftiger Hoehe (< 230 px)', k['kopfH'] < 230,
                  f"{k['kopfH']:.0f}px")

            # Spaltenhinterlegung ueber ECHTE Mausereignisse.
            z = js("""(() => { const c = document.querySelectorAll('#kbm-overlay tbody tr')[4]
                        .querySelectorAll('.kbm-gcell')[5].getBoundingClientRect();
                        return { x: c.left + c.width/2, y: c.top + c.height/2 }; })()""")
            maus(z['x'], z['y'])
            h = js("""(() => { const ov = document.getElementById('kbm-overlay');
                const m = ov.querySelector('.kbm-col-hl'); const th = ov.querySelectorAll('thead th.kbm-c-grp')[5];
                if (!m || !th) return null;
                const mr = m.getBoundingClientRect(), tr = th.getBoundingClientRect();
                return { sichtbar: !m.hidden && mr.width > 0, l: mr.left, w: mr.width, thL: tr.left, thW: tr.width,
                         thHl: th.classList.contains('kbm-th-hl'),
                         hl: ov.querySelectorAll('thead th.kbm-th-hl').length,
                         mT: mr.top, mB: mr.bottom, wrapB: ov.querySelector('.kbm-table-wrap').getBoundingClientRect().bottom,
                         thFarbe: getComputedStyle(th).color, thGrund: getComputedStyle(th).backgroundColor,
                         grund: getComputedStyle(m).backgroundColor }; })()""")
            # Fehlt die Flaeche, liefert die Messung None - das ist ein FAIL mit
            # Bilanz, kein Abbruch (Register: ein Absturz ist kein Biss).
            h = h or {'sichtbar': False, 'l': -99, 'w': -99, 'thL': 0, 'thW': 0, 'thHl': False, 'hl': 0,
                      'mT': 0, 'mB': -99, 'wrapB': 0, 'thFarbe': 'rgb(0,0,0)', 'thGrund': 'rgb(0,0,0)',
                      'grund': 'rgb(0,0,0)'}
            check('⚠ Ueberfahren einer Gruppenzelle hinterlegt die Spalte', h['sichtbar'], str(h))
            check('die Hinterlegung deckt genau diese Spalte',
                  abs(h['l'] - h['thL']) <= 1 and abs(h['w'] - h['thW']) <= 1,
                  f"{h['l']:.0f}/{h['w']:.0f} gegen {h['thL']:.0f}/{h['thW']:.0f}")
            check('genau EIN Kopf ist hervorgehoben, und zwar der richtige', h['thHl'] and h['hl'] == 1)
            check('die Hinterlegung reicht bis zum unteren Rand',
                  h['mB'] >= h['wrapB'] - 1, f"{h['mB']:.0f} < {h['wrapB']:.0f}")
            farben[thema] = h['thGrund']

            def rgb(s):
                s = s.strip()
                if s.startswith('color('):
                    z = [float(x) for x in s[s.index('srgb') + 4:s.index(')')].replace('/', ' ').split()]
                    return [v * 255 for v in z[:3]] + ([z[3]] if len(z) > 3 else [1.0])
                z = [float(x) for x in s[s.index('(') + 1:s.index(')')].replace(',', ' ').split()]
                return z[:3] + ([z[3]] if len(z) > 3 else [1.0])

            def lum(c):
                def kk(v):
                    v /= 255
                    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
                return .2126 * kk(c[0]) + .7152 * kk(c[1]) + .0722 * kk(c[2])

            vg, hg = rgb(h['thFarbe']), rgb(h['thGrund'])
            check('der hervorgehobene Kopf ist DECKEND (kein Durchscheinen beim Scrollen)',
                  hg[3] >= 0.999, h['thGrund'])
            L1, L2 = lum(vg), lum(hg)
            kon = (max(L1, L2) + .05) / (min(L1, L2) + .05)
            check(f'hervorgehobener Kopf lesbar (Kontrast {kon:.2f}:1)', kon >= 4.5,
                  f"{h['thFarbe']} auf {h['thGrund']}")

            bild = ruf('Page.captureScreenshot', {'format': 'png'})['data']
            ziel_png = Path.home() / f'kbm-kopf-{thema}.png'
            ziel_png.write_bytes(base64.b64decode(bild))
            print(f'  Screenshot: {ziel_png}')

            # Wechsel in eine Textspalte nimmt die Hinterlegung weg.
            t = js("""(() => { const c = document.querySelectorAll('#kbm-overlay tbody tr')[4]
                        .querySelectorAll('.kbm-c-text')[0].getBoundingClientRect();
                        return { x: c.left + c.width/2, y: c.top + c.height/2 }; })()""")
            maus(t['x'], t['y'])
            weg = js("(()=>{const ov=document.getElementById('kbm-overlay');const m=ov.querySelector('.kbm-col-hl');"
                     "return !!m && m.hidden && !ov.querySelector('thead th.kbm-th-hl');})()")
            check('ueber einer Textspalte ist keine Spalte hinterlegt', weg)

            # Nach dem Scrollen sitzt die Hinterlegung weiter an derselben Spalte.
            js("document.querySelector('#kbm-overlay .kbm-table-wrap').scrollTop = 4000")
            time.sleep(0.2)
            z2 = js("""(() => { const rows=[...document.querySelectorAll('#kbm-overlay tbody tr')];
                        const wr=document.querySelector('#kbm-overlay .kbm-table-wrap').getBoundingClientRect();
                        const tr=rows.find(r=>{const b=r.getBoundingClientRect();return b.top>wr.top+250&&b.bottom<wr.bottom;});
                        const c=tr.querySelectorAll('.kbm-gcell')[2].getBoundingClientRect();
                        return { x: c.left + c.width/2, y: c.top + c.height/2 }; })()""")
            maus(z2['x'], z2['y'])
            s = js("""(() => { const ov=document.getElementById('kbm-overlay');
                const me=ov.querySelector('.kbm-col-hl'); if (!me) return null;
                const m=me.getBoundingClientRect();
                const th=ov.querySelectorAll('thead th.kbm-c-grp')[2].getBoundingClientRect();
                const wr=ov.querySelector('.kbm-table-wrap').getBoundingClientRect();
                return { l:m.left, thL:th.left, deckt: m.top <= wr.top + 1 && m.bottom >= wr.bottom - 1 }; })()""")
            check('nach dem Scrollen deckt die Hinterlegung die sichtbare Spalte',
                  bool(s) and abs(s['l'] - s['thL']) <= 1 and s['deckt'], str(s))

        check('⚠ hell und dunkel waren zwei VERSCHIEDENE Messungen',
              len(farben) == 2 and farben['dunkel'] != farben['hell'], str(farben))
        ws.close()
    finally:
        chrome.terminate(); srv.terminate()
        shutil.rmtree(profil, ignore_errors=True)
        shutil.rmtree(arbeit, ignore_errors=True)
    print(f'\n\033[1mErgebnis: {OK} OK, {FAIL} FAIL\033[0m')
    sys.exit(1 if FAIL else 0)


if __name__ == '__main__':
    main()
