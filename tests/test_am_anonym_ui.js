/**
 * Einstellungen → AI-Maus → Vorgabe-Fragen: die Art „Anonymisieren".
 *
 * Gemessen an der ECHTEN settings.html und dem ECHTEN ai_mouse_admin.js:
 *   - eine Vorgabe mit Aktion ist in der Liste gekennzeichnet (und NUR sie),
 *   - das Formular zeigt die gespeicherte Art und benennt das Textfeld passend,
 *   - beim Speichern geht die gewaehlte Art als `aktion` an den Server – fuer
 *     eine gewoehnliche Frage leer.
 * Der letzte Punkt ist die tragende Zusage: ohne ihn zeigt die Oberflaeche
 * „Anonymisieren", und der Server speichert eine gewoehnliche Frage.
 *
 *   node tests/test_am_anonym_ui.js
 */
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1
const sitzungLaden = require('./lib/sitzung_laden');
const fs = require('fs');
const { JSDOM } = require('./lib/jsdom_laden')();

let ok = 0, fail = 0;
const c = (t, b) => { b ? (ok++, console.log('  OK   ' + t))
                        : (fail++, console.log('  FAIL ' + t)); };
let bilanz = false;
process.on('exit', (code) => {
  if (!bilanz && code === 0) { console.log('\nABGEBROCHEN – keine Bilanz'); process.exitCode = 1; }
});
const wd = setTimeout(() => {
  console.log('\nWACHHUND: haengt\n' + ok + ' OK, ' + (fail + 1) + ' FAIL');
  bilanz = true; process.exit(1);
}, 25000);

function warte(pruef, ms) {
  return new Promise((loese, brich) => {
    const ende = Date.now() + (ms || 5000);
    (function tick() {
      let da = false;
      try { da = pruef(); } catch (e) { da = false; }
      if (da) { return loese(true); }
      if (Date.now() > ende) { return brich(new Error('Zustand kam nicht zustande')); }
      setTimeout(tick, 15);
    })();
  });
}

const VORGABEN = [
  { id: 'v1', titel: 'was ist das ?', prompt: 'Beschreibe knapp.' },
  { id: 'v2', titel: 'Anonymisieren', prompt: 'Namen unkenntlich machen.',
    aktion: 'anonymisieren' },
];

function seite() {
  const d = new JSDOM(fs.readFileSync('frontend/settings.html', 'utf8'),
                      { url: 'https://x/settings', runScripts: 'outside-only' });
  const w = d.window;
  sitzungLaden(w);
  w.localStorage.setItem('jarvis_token', 't');
  w.__posts = [];
  const J = x => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(x) });
  w.fetch = (u, o) => {
    const p = String(u).split('?')[0];
    if (p === '/api/ai-mouse/admin/vorgaben' && (!o || !o.method || o.method === 'GET')) {
      return J({ ok: true, vorgaben: VORGABEN });
    }
    if (p === '/api/ai-mouse/admin/vorgaben' && o && o.method === 'POST') {
      w.__posts.push(JSON.parse(o.body));
      return J({ ok: true, vorgabe: {} });
    }
    return J({});
  };
  for (const f of ['frontend/js/i18n.js', 'frontend/js/icons.js',
                   'frontend/js/ai_mouse_admin.js']) {
    try { w.eval(fs.readFileSync(f, 'utf8')); }
    catch (e) { console.log('LADEFEHLER ' + f + ': ' + e.message); }
  }
  return w;
}

(async () => {
  const w = seite();
  const doc = w.document;
  const A = w.AiMouseAdmin;
  // ── Positivkontrolle des Messaufbaus ────────────────────────────────────
  if (!A || !doc.getElementById('amvorg-liste')) {
    console.log('ABBRUCH: Modul oder Container fehlt – Messaufbau unbrauchbar');
    bilanz = true; process.exit(2);
  }
  A.vorgabenLaden();
  await warte(() => doc.querySelectorAll('.am-vorg-card').length === VORGABEN.length);
  c('Positivkontrolle: beide Vorgaben sind gezeichnet', true);

  console.log('\n=== 1. Kennzeichnung in der Liste ===');
  const karte = id => doc.querySelector('.am-vorg-card[data-vid="' + id + '"]');
  c('die Vorgabe mit Aktion traegt die Kennzeichnung',
    !!karte('v2') && !!karte('v2').querySelector('.am-vorg-art'));
  c('die gewoehnliche Frage traegt sie NICHT',
    !!karte('v1') && !karte('v1').querySelector('.am-vorg-art'));
  c('die Kennzeichnung ist TEXT, nicht nur Farbe',
    !!karte('v2') && /\S/.test((karte('v2').querySelector('.am-vorg-art') || {}).textContent || ''));

  console.log('\n=== 2. Formular einer Anonymisieren-Vorgabe ===');
  A.vorgabeFormular('v2');
  const art = () => doc.getElementById('amvorg-f-art');
  const lbl = () => doc.getElementById('amvorg-f-prompt-label');
  const hint = () => doc.getElementById('amvorg-f-art-hint');
  c('die Auswahl steht auf „Anonymisieren"', !!art() && art().value === 'anonymisieren');
  c('das Textfeld heisst NICHT „Anweisung an das Modell"',
    !!lbl() && !/Anweisung an das Modell/.test(lbl().textContent));
  c('der Hinweis zur Wirkung ist sichtbar', !!hint() && hint().style.display !== 'none');
  doc.getElementById('amvorg-f-save').click();
  await warte(() => w.__posts.length === 1);
  c('Speichern schickt aktion = anonymisieren',
    w.__posts[0] && w.__posts[0].aktion === 'anonymisieren' && w.__posts[0].id === 'v2');

  console.log('\n=== 3. Formular einer gewoehnlichen Frage ===');
  await warte(() => !doc.getElementById('amvorg-form'));
  A.vorgabeFormular('v1');
  c('die Auswahl steht auf „Frage an das Modell"', !!art() && art().value === '');
  c('das Textfeld heisst „Anweisung an das Modell"',
    !!lbl() && /Anweisung an das Modell/.test(lbl().textContent));
  c('der Hinweis ist ausgeblendet', !!hint() && hint().style.display === 'none');
  doc.getElementById('amvorg-f-save').click();
  await warte(() => w.__posts.length === 2);
  c('Speichern schickt eine LEERE aktion', w.__posts[1] && w.__posts[1].aktion === '');

  console.log('\n=== 4. Neue Vorgabe auf „Anonymisieren" umgestellt ===');
  await warte(() => !doc.getElementById('amvorg-form'));
  A.vorgabeFormular(null);
  doc.getElementById('amvorg-f-titel').value = 'Anonym';
  art().value = 'anonymisieren';
  art().dispatchEvent(new w.Event('change'));
  const pr = doc.getElementById('amvorg-f-prompt');
  c('ein leeres Textfeld wird vorbelegt (der Server verlangt einen Text)',
    !!pr && pr.value.trim().length > 0);
  c('Beschriftung wechselt mit der Auswahl',
    !!lbl() && !/Anweisung an das Modell/.test(lbl().textContent));
  doc.getElementById('amvorg-f-save').click();
  await warte(() => w.__posts.length === 3);
  c('die NEUE Vorgabe geht mit aktion = anonymisieren an den Server',
    w.__posts[2] && w.__posts[2].aktion === 'anonymisieren' && w.__posts[2].id === '');

  w.close();
  clearTimeout(wd);
  bilanz = true;
  console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
  process.exit(fail ? 1 : 0);
})().catch(e => {
  clearTimeout(wd);
  bilanz = true;
  console.log('\nABBRUCH: ' + (e && e.message));
  console.log(ok + ' OK, ' + (fail + 1) + ' FAIL');
  process.exit(1);
});
