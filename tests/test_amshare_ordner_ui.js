/**
 * Einstellungen → AI-Maus → Bereitstellung im Netz: „Ordner wählen und
 * hineinschreiben“ (Vorbild: E-Mail → Outlook-Add-in Bereitstellung).
 *
 * Der ECHTE `ai_mouse_admin.js` laeuft in jsdom gegen die ECHTE settings.html;
 * File System Access API und fetch sind Attrappen mit der echten Form
 * (Handle mit queryPermission/getFileHandle/createWritable, Response mit
 * headers.get/blob/json). Gemessen wird die WIRKUNG:
 *   - Sichtbarkeit haengt am FELDINHALT und an der API (Chrome/Edge),
 *   - der Ordner wird VOR dem Abruf besorgt (Benutzergeste),
 *   - abgerufen wird die EXE (?form=exe), nicht das ZIP,
 *   - geschrieben wird unter dem Namen aus dem Pfadfeld, sonst dem des Servers,
 *   - ein abgebrochener Dialog ist kein Fehler, ein Serverfehler bleibt stehen,
 *   - der gewaehlte Ordner wird gemerkt (zweiter Klick: kein Dialog).
 *
 *   node tests/test_amshare_ordner_ui.js
 */
require('./lib/bilanz')();
const sitzungLaden = require('./lib/sitzung_laden');
const fs = require('fs');
const { JSDOM } = require('./lib/jsdom_laden')();

let ok = 0, fail = 0, bilanz = false;
const c = (t, b) => { b ? (ok++, console.log('  OK   ' + t))
                        : (fail++, console.log('  FAIL ' + t)); };
process.on('exit', (code) => {
  if (!bilanz && code === 0) { console.log('\nABGEBROCHEN – keine Bilanz'); process.exitCode = 1; }
});
const wd = setTimeout(() => {
  console.log('\nWACHHUND: haengt\n' + ok + ' OK, ' + (fail + 1) + ' FAIL');
  bilanz = true; process.exit(1);
}, 25000);

function warte(pruef, ms) {
  return new Promise((loese, brich) => {
    const ende = Date.now() + (ms || 4000);
    (function tick() {
      let da = false;
      try { da = pruef(); } catch (e) { da = false; }
      if (da) { return loese(true); }
      if (Date.now() > ende) { return brich(new Error('Zustand kam nicht zustande')); }
      setTimeout(tick, 10);
    })();
  });
}

/** Seite bauen. `opt.fs` = File System Access API vorhanden. */
function seite(opt) {
  const d = new JSDOM(fs.readFileSync('frontend/settings.html', 'utf8'),
                      { url: 'https://x/settings', runScripts: 'outside-only' });
  const w = d.window;
  sitzungLaden(w);
  w.localStorage.setItem('jarvis_token', 't');
  const log = [];                 // Reihenfolge: picker / fetch
  const geschrieben = {};         // name -> Inhalt
  const stand = { pickerAufrufe: 0, paketUrl: '', abbruch: false,
                  paketFehler: null, pfad: opt.pfad };

  const J = (x, status) => Promise.resolve({
    ok: !status || status < 400, status: status || 200,
    headers: { get: () => null },
    json: () => Promise.resolve(x) });
  const fetchAttr = (u) => {
    const p = String(u).split('?')[0];
    if (p === '/api/ai-mouse/admin/areas') {
      return J({ bereiche: [], freigabe_pfad: stand.pfad });
    }
    if (p === '/api/ai-mouse/paket') {
      log.push('fetch');
      stand.paketUrl = String(u);
      if (stand.paketFehler) { return J({ ok: false, error: stand.paketFehler }, 409); }
      const blob = new w.Blob(['MZ-EXE-INHALT']);
      stand.blob = blob;
      return Promise.resolve({
        ok: true, status: 200,
        headers: { get: (k) => /disposition/i.test(k)
                   ? 'attachment; filename="AiMouse.exe"' : null },
        blob: () => Promise.resolve(blob),
        json: () => Promise.reject(new Error('kein JSON')) });
    }
    return J({});
  };
  w.fetch = fetchAttr;
  global.fetch = fetchAttr;      // Register: Node hat ein eigenes globales fetch

  if (opt.fs) {
    const ordner = {
      name: 'tools',
      queryPermission: () => Promise.resolve('granted'),
      requestPermission: () => Promise.resolve('granted'),
      getFileHandle: (name, o) => Promise.resolve({
        createWritable: () => {
          let puffer = null;
          return Promise.resolve({
            write: (x) => { puffer = x; return Promise.resolve(); },
            // jsdom-Blob kennt kein .text() – festgehalten wird das OBJEKT,
            // verglichen wird die Identitaet mit dem Abruf.
            close: () => { geschrieben[name] = puffer; return Promise.resolve(); } });
        } }) };
    w.showDirectoryPicker = () => {
      stand.pickerAufrufe++;
      log.push('picker');
      if (stand.abbruch) {
        const e = new Error('abgebrochen'); e.name = 'AbortError';
        return Promise.reject(e);
      }
      return Promise.resolve(ordner);
    };
  }
  for (const f of ['frontend/js/i18n.js', 'frontend/js/icons.js',
                   'frontend/js/ai_mouse_admin.js']) {
    w.eval(fs.readFileSync(f, 'utf8'));
  }
  return { w, log, geschrieben, stand };
}

const $ = (w, id) => w.document.getElementById(id);
const sicht = (w, id) => { const e = $(w, id); return !!e && e.style.display !== 'none'; };
const tippe = (w, wert) => {
  const f = $(w, 'amshare-pfad');
  f.value = wert;
  f.dispatchEvent(new w.Event('input'));
};

(async () => {
  // ── Positivkontrolle: Markup + Modul da ───────────────────────────────
  const P = seite({ fs: true, pfad: '' });
  if (!$(P.w, 'amshare-up') || !$(P.w, 'amshare-pfad') || !P.w.AiMouseAdmin) {
    console.log('ABBRUCH: Knopf, Feld oder AiMouseAdmin fehlt – Pruefstand blind');
    bilanz = true; process.exit(2);
  }

  console.log('── Sichtbarkeit');
  {
    const { w } = seite({ fs: false, pfad: '\\\\srv\\tools\\AiMouse.exe' });
    w.AiMouseAdmin.onShow();
    await warte(() => $(w, 'amshare-pfad').value !== '');
    c('ohne File System Access API (Firefox) unsichtbar – trotz Pfad',
      !sicht(w, 'amshare-up'));
  }
  {
    const { w } = seite({ fs: true, pfad: '' });
    w.AiMouseAdmin.onShow();
    await new Promise(r => setTimeout(r, 50));
    c('ohne Pfad unsichtbar (kein Ziel)', !sicht(w, 'amshare-up'));
    tippe(w, '\\\\srv\\tools\\AiMouse.exe');
    c('Pfad eintippen zeigt ihn SOFORT (Feldinhalt, nicht gespeicherter Wert)',
      sicht(w, 'amshare-up'));
    c('Beschriftung vor der Wahl: „Ordner wählen und hineinschreiben“',
      $(w, 'amshare-up').textContent === 'Ordner wählen und hineinschreiben');
    tippe(w, '   ');
    c('Feld leeren verbirgt ihn sofort', !sicht(w, 'amshare-up'));
  }

  console.log('── Schreiben');
  const S = seite({ fs: true, pfad: '\\\\srv\\tools\\Contoso-Maus.exe' });
  S.w.AiMouseAdmin.onShow();
  await warte(() => sicht(S.w, 'amshare-up'));
  $(S.w, 'amshare-up').click();
  await warte(() => Object.keys(S.geschrieben).length > 0);
  await warte(() => !$(S.w, 'amshare-up').disabled);
  c('Ordner wird VOR dem Abruf besorgt (' + S.log.join(' → ') + ')',
    S.log[0] === 'picker' && S.log[1] === 'fetch');
  c('abgerufen wird die EXE (?form=exe), nicht das ZIP (' + S.stand.paketUrl + ')',
    /[?&]form=exe(&|$)/.test(S.stand.paketUrl));
  c('Dateiname aus dem Pfadfeld (' + Object.keys(S.geschrieben).join(',') + ')',
    Object.keys(S.geschrieben).join(',') === 'Contoso-Maus.exe');
  c('Inhalt ist genau das Blob aus dem Abruf',
    !!S.stand.blob && S.geschrieben['Contoso-Maus.exe'] === S.stand.blob);
  c('Erfolg steht am Knopf und nennt Datei und Ordner',
    /Contoso-Maus\.exe/.test($(S.w, 'amshare-dl-hint').textContent)
    && /tools/.test($(S.w, 'amshare-dl-hint').textContent));
  c('Knopf nennt danach den gemerkten Ordner',
    $(S.w, 'amshare-up').textContent === 'In Ordner „tools“ schreiben');

  $(S.w, 'amshare-up').click();
  await warte(() => S.log.filter(x => x === 'fetch').length === 2);
  await warte(() => !$(S.w, 'amshare-up').disabled);
  c('zweiter Klick fragt NICHT erneut nach dem Ordner (' + S.stand.pickerAufrufe + ' Dialoge)',
    S.stand.pickerAufrufe === 1);

  console.log('── Name ohne .exe im Pfad');
  {
    const N = seite({ fs: true, pfad: '\\\\srv\\tools' });
    N.w.AiMouseAdmin.onShow();
    await warte(() => sicht(N.w, 'amshare-up'));
    $(N.w, 'amshare-up').click();
    await warte(() => Object.keys(N.geschrieben).length > 0);
    c('Pfad nennt nur den Ordner → Name vom Server (' + Object.keys(N.geschrieben) + ')',
      Object.keys(N.geschrieben).join(',') === 'AiMouse.exe');
  }

  console.log('── Abbruch und Fehler');
  {
    const A = seite({ fs: true, pfad: '\\\\srv\\tools\\AiMouse.exe' });
    A.stand.abbruch = true;
    A.w.AiMouseAdmin.onShow();
    await warte(() => sicht(A.w, 'amshare-up'));
    $(A.w, 'amshare-up').click();
    await warte(() => A.stand.pickerAufrufe === 1);
    await warte(() => !$(A.w, 'amshare-up').disabled);
    c('abgebrochener Dialog: kein Abruf, keine Fehlermeldung',
      !A.log.includes('fetch') && $(A.w, 'amshare-dl-hint').textContent === '');
  }
  {
    const F = seite({ fs: true, pfad: '\\\\srv\\tools\\AiMouse.exe' });
    F.stand.paketFehler = 'Die Anwendung wird gerade gebaut';
    F.w.AiMouseAdmin.onShow();
    await warte(() => sicht(F.w, 'amshare-up'));
    $(F.w, 'amshare-up').click();
    await warte(() => F.log.includes('fetch'));
    await warte(() => !$(F.w, 'amshare-up').disabled);
    c('Serverfehler steht mit dem Servertext am Knopf',
      /gerade gebaut/.test($(F.w, 'amshare-dl-hint').textContent));
    c('…und es wurde nichts geschrieben', Object.keys(F.geschrieben).length === 0);
  }

  console.log('── i18n');
  {
    const src = fs.readFileSync('frontend/js/ai_mouse_admin.js', 'utf8');
    const schluessel = Array.from(new Set(
      (src.match(/'amshare\.up[a-z_]*'/g) || []).map(s => s.slice(1, -1))));
    schluessel.push('amshare.up_note');
    const i18n = fs.readFileSync('frontend/js/i18n.js', 'utf8');
    for (const k of schluessel) {
      const n = (i18n.match(new RegExp("'" + k.replace('.', '\\.') + "'\\s*:", 'g')) || []).length;
      c(k + ' in DE und EN (' + n + 'x)', n === 2);
    }
    const html = fs.readFileSync('frontend/settings.html', 'utf8');
    c('Knopf traegt data-i18n="amshare.up"', /id="amshare-up"[^>]*data-i18n="amshare\.up"/.test(html));
  }

  clearTimeout(wd);
  console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
  bilanz = true;
  process.exit(fail ? 1 : 0);
})().catch(e => {
  console.log('ABBRUCH: ' + (e && e.stack || e));
  bilanz = true; process.exit(2);
});
