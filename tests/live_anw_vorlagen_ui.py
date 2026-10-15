#!/usr/bin/env python3
"""
Optische Abnahme des Vorlagen-Pulldowns im Dialog "Prompt optimieren".

Gemessen wird im ECHTEN Chrome gegen das ECHTE CSS und den ECHTEN Renderer -
jsdom rechnet kein Layout, Ueberlauf und Kontrast sieht nur ein Browser.

⚠ DIE PROBESEITE LIEGT NICHT UNTER frontend/ (Register): `test_theme_default`
laeuft ueber JEDE HTML-Datei dort und verlangt das Anti-Flacker-Skript - eine
Wegwerfseite dort laesst einen FREMDEN Waechter fehlschlagen. Sie liegt in
einem eigenen Ordner mit Symlinks auf css/ und js/.
"""
import json, os, shutil, socket, subprocess, sys, tempfile, time, urllib.request
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
<div id="kb-cleanup-modal" class="modal open" style="z-index:10001;">
  <div class="modal-card" style="max-width:720px;display:flex;flex-direction:column;max-height:90vh;">
    <div class="modal-header"><h2>&#129529; Prompt optimieren</h2></div>
    <div class="modal-body" id="kb-cleanup-body" style="flex:1 1 auto;min-height:0;overflow:auto;"></div>
  </div>
</div>
<script src="js/i18n.js"></script>
<script src="js/knowledge.js"></script>
<script>
window.knowledgeManager._cleanupDateien = [
  { schluessel:'anweisung:style.md', art:'anweisung', name:'style.md',
    bytes:900, herkunft:'geaendert', zu_gross:false }];
window.knowledgeManager._cleanupListe();
</script></body></html>"""


def cdp(ws, mid, methode, params=None):
    import websocket  # noqa
    return None


def main():
    global FAIL
    arbeit = Path(tempfile.mkdtemp(prefix='anwvorl-'))
    (arbeit / 'css').symlink_to(REPO / 'frontend/css')
    (arbeit / 'js').symlink_to(REPO / 'frontend/js')
    (arbeit / 'probe.html').write_text(SEITE, encoding='utf-8')
    port = freier_port()
    srv = subprocess.Popen([sys.executable, '-m', 'http.server', str(port), '-b', '127.0.0.1'],
                           cwd=arbeit, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    profil = Path(tempfile.mkdtemp(prefix='anwvorl-chrome-'))
    dport = freier_port()
    chrome = subprocess.Popen([
        'google-chrome', '--headless=new', '--no-sandbox', '--disable-gpu',
        f'--remote-debugging-port={dport}', f'--user-data-dir={profil}',
        '--remote-allow-origins=*', '--window-size=760,900', 'about:blank'],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        time.sleep(2.5)
        for _ in range(40):
            try:
                seiten = json.load(urllib.request.urlopen(f'http://127.0.0.1:{dport}/json/list'))
                # ⚠ NUR type == "page" - /json/list liefert auch die eingebauten
                # Chrome-Erweiterungen; wer blind [0] nimmt, haengt an einer
                # background.html und misst eine leere Seite (Register).
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
        gruende = {}
        for thema, dunkel in (('dunkel', True), ('hell', False)):
            print(f'\n\033[1m{thema}\033[0m')
            # ⚠ NICHT ueber Runtime.evaluate auf about:blank - das ist ein
            # ANDERER Origin, der Schreibvorgang erreicht die Seite nie, und
            # der erste Lauf misst das Vorgabe-Thema (gemessen: zweimal hell,
            # das dunkle Thema war ungeprueft). Der Schluessel muss VOR dem
            # ersten Skript der Seite stehen (Register).
            ruf('Page.addScriptToEvaluateOnNewDocument', {'source':
                f"try{{localStorage.setItem('jarvis_theme','{'dark' if dunkel else 'light'}')}}catch(e){{}}"})
            ruf('Page.navigate', {'url': f'http://127.0.0.1:{port}/probe.html'})
            time.sleep(1.0)
            ruf('Page.reload', {'ignoreCache': True})   # jetzt greift der Schluessel
            time.sleep(1.6)
            klasse = js('document.body.className')
            check(f'das Thema ist wirklich {thema}',
                  ('light' not in klasse) if dunkel else ('light' in klasse), klasse)
            # ⚠ POSITIVKONTROLLE: ist die Seite ueberhaupt aufgebaut? Ohne sie
            # ist jede Messung darunter trivial wahr (0 <= 0).
            bereit = js("!!document.getElementById('kb-cl-anw-vorlage') && "
                        "document.getElementById('kb-cl-anw-vorlage').getBoundingClientRect().width")
            if not bereit:
                print('\033[31mExit 2: Seite nicht aufgebaut (CSS/JS 404?)\033[0m')
                sys.exit(2)
            check('das Pulldown ist gerendert und hat eine Groesse', bereit > 60, f'{bereit}')

            masse = js("""(() => {
                const s = document.getElementById('kb-cl-anw-vorlage');
                const l = document.querySelector('.kb-cl-anw-vorl-label');
                const t = document.getElementById('kb-cl-anw-text');
                const k = document.getElementById('kb-cl-anw-start');
                const kasten = document.querySelector('.kb-cl-anw');
                const body = document.getElementById('kb-cleanup-body');
                const r = e => { const b = e.getBoundingClientRect();
                    return { l: b.left, r: b.right, t: b.top, b: b.bottom, w: b.width, h: b.height }; };
                return { s: r(s), l: r(l), t: r(t), k: r(k), kasten: r(kasten),
                         body: r(body), scrollW: body.scrollWidth, clientW: body.clientWidth,
                         farbe: getComputedStyle(l).color,
                         grund: getComputedStyle(kasten).backgroundColor };
            })()""")
            check('Beschriftung und Menue stehen in EINER Zeile',
                  abs(masse['l']['t'] - masse['s']['t']) < 26,
                  f"{masse['l']['t']:.0f} vs {masse['s']['t']:.0f}")
            check('das Menue steht LINKS vom Feldrand und laeuft nicht aus dem Kasten',
                  masse['s']['r'] <= masse['kasten']['r'] + 1,
                  f"{masse['s']['r']:.0f} > {masse['kasten']['r']:.0f}")
            check('es steht UEBER dem Eingabefeld', masse['s']['b'] <= masse['t']['t'] + 1)
            check('der Knopf "Anweisung ausfuehren" bleibt darunter sichtbar',
                  masse['k']['h'] > 10 and masse['k']['t'] > masse['t']['b'] - 1)
            check('kein waagerechter Ueberlauf im Dialog',
                  masse['scrollW'] <= masse['clientW'] + 1,
                  f"{masse['scrollW']} > {masse['clientW']}")

            # Der laengste Eintrag darf die Zeile nicht sprengen.
            js("""(() => { const s = document.getElementById('kb-cl-anw-vorlage');
                   const o = document.createElement('option');
                   o.value='_lang'; o.textContent='Sehr lange Beschriftung ohne jede Trennstelle zum Pruefen';
                   s.appendChild(o); s.value='_lang'; })()""")
            time.sleep(0.4)
            ueber = js("""(() => { const b = document.getElementById('kb-cleanup-body');
                   const s = document.getElementById('kb-cl-anw-vorlage').getBoundingClientRect();
                   const k = document.querySelector('.kb-cl-anw').getBoundingClientRect();
                   return { ueber: b.scrollWidth - b.clientWidth, raus: s.right - k.right }; })()""")
            check('⚠ ein ueberlanger Eintrag sprengt die Zeile nicht',
                  ueber['ueber'] <= 1 and ueber['raus'] <= 1, str(ueber))

            # Kontrast der Beschriftung gegen den Kasten.
            def rgb(s):
                z = [float(x) for x in s[s.index('(') + 1:s.index(')')].replace(',', ' ').split()]
                return z[:3] + ([z[3]] if len(z) > 3 else [1.0])

            def lum(c):
                def k(v):
                    v /= 255
                    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
                return .2126 * k(c[0]) + .7152 * k(c[1]) + .0722 * k(c[2])
            vg, hg = rgb(masse['farbe']), rgb(masse['grund'])
            # ⚠ Halbtransparenz ueber den gemessenen Grund legen - eine
            # rgba-Farbe als deckend zu lesen ergibt Traumwerte (Register).
            a = vg[3]
            misch = [vg[i] * a + hg[i] * (1 - a) for i in range(3)]
            L1, L2 = lum(misch), lum(hg)
            kontrast = (max(L1, L2) + .05) / (min(L1, L2) + .05)
            check(f'Beschriftung lesbar (Kontrast {kontrast:.2f}:1)', kontrast >= 4.5,
                  f'{masse["farbe"]} auf {masse["grund"]}')
            gruende[thema] = (masse['farbe'], masse['grund'])

            # ⚠ Fuer den Augenschein den KUENSTLICHEN Eintrag wieder entfernen
            # und zum Kasten scrollen - ein Screenshot des Sonderfalls sagt
            # ueber den Normalzustand nichts, und angeschnitten sagt er gar nichts.
            js("""(() => { const s = document.getElementById('kb-cl-anw-vorlage');
                   [...s.options].filter(o => o.value === '_lang').forEach(o => o.remove());
                   s.value = 'sicherheit';
                   s.dispatchEvent(new Event('change'));
                   document.querySelector('.kb-cl-anw').scrollIntoView({block:'center'}); })()""")
            time.sleep(0.6)
            bild = ruf('Page.captureScreenshot', {'format': 'png'})['data']
            ziel_png = Path.home() / f'anw-vorlagen-{thema}.png'
            import base64
            ziel_png.write_bytes(base64.b64decode(bild))
            print(f'  Screenshot: {ziel_png}')
        # ⚠ POSITIVKONTROLLE: waren es wirklich ZWEI Laeufe? Identische Farben
        # in beiden Durchgaengen heissen, dass das Thema nie gewechselt hat -
        # dann ist ein Thema schlicht ungeprueft (genau so passiert).
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
