/**
 * Waechter: der Formular-Editor im Feedback-Reiter verliert keine
 * ungespeicherte Arbeit (Review 2026-09-28 #15).
 *
 * ⚠ DIE BEFUNDE:
 *   1. `aktivSetzen` ging ueber `senden()` -> `editorSchliessen()`: der Haken
 *      „aktiv" an Formular A verwarf die ungespeicherten Aenderungen im
 *      Editor von B.
 *   2. Der Editor sitzt IN einer Formular-Karte. Das Ablegen einer Spalte
 *      blubberte zum Drop-Handler der Karte: der sortierte die Spalte in die
 *      Formular-Liste ein, schickte einen Sortier-POST, und der Neuaufbau
 *      setzte Titel/Beschreibung im Editor zurueck.
 *
 * AUSGEFUEHRT gegen die echte settings.html und das echte feedback_admin.js
 * (jsdom). Gemessen wird der Zustand NACH dem Klick bzw. Ablegen.
 *
 *   node tests/test_feedback_admin_editor_ui.js   (JSDOM_PATH setzt den jsdom-Ort)
 */
const fs = require('fs');
const { JSDOM } = require('./lib/jsdom_laden')();

let ok = 0, fail = 0;
const c = (t, b, d) => {
  b ? (ok++, console.log('  OK   ' + t))
    : (fail++, console.log('  FAIL ' + t + (d ? '  – ' + d : '')));
};
const wd = setTimeout(() => {
  console.log('\nWACHHUND: haengt\n' + ok + ' OK, ' + (fail + 1) + ' FAIL');
  process.exit(1);
}, 30000);
const warte = ms => new Promise(r => setTimeout(r, ms));

const A = { id: 'fa', titel: 'Formular A', beschreibung: '', aktiv: true,
            spalten: [{ id: 'a1', name: 'X', typ: 'text' }] };
const B = { id: 'fb', titel: 'Formular B', beschreibung: 'alt', aktiv: true,
            spalten: [{ id: 'b1', name: 'Eins', typ: 'text' },
                      { id: 'b2', name: 'Zwei', typ: 'text' },
                      { id: 'b3', name: 'Drei', typ: 'text' }] };

function seite() {
  const d = new JSDOM(fs.readFileSync('frontend/settings.html', 'utf8'),
                      { url: 'https://x/settings', runScripts: 'outside-only' });
  const w = d.window;
  w.localStorage.setItem('jarvis_token', 't');
  const rufe = [];
  w.fetch = (u, o2) => {
    const p = String(u).split('?')[0];
    rufe.push({ u: p, m: (o2 && o2.method) || 'GET', b: o2 && o2.body });
    const J = x => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(x) });
    if (p === '/api/feedback/admin/formulare' || p === '/api/feedback/admin/formulare/reihenfolge') {
      return J({ ok: true, formulare: [A, B], typen: ['text', 'sterne'],
                 max_spalten: 12, skill_aktiv: true });
    }
    if (p === '/api/feedback/admin/abgaben') { return J({ ok: true, abgaben: [] }); }
    return J({ ok: true });
  };
  w.confirm = () => true;
  for (const f of ['js/icons.js', 'js/i18n.js', 'js/feedback_admin.js']) {
    w.eval(fs.readFileSync('frontend/' + f, 'utf8'));
  }
  w.FeedbackAdmin.onShow();
  return { w, doc: w.document, rufe };
}

function ereignis(w, typ, ziel, extra) {
  const ev = new w.Event(typ, { bubbles: true, cancelable: true });
  Object.assign(ev, extra || {});
  ziel.dispatchEvent(ev);
  return ev;
}

(async () => {
  console.log('\n1. Haken „aktiv" an A verwirft den Editor von B nicht');
  {
    const { w, doc, rufe } = seite();
    await warte(60);
    c('Positivkontrolle: zwei Karten', doc.querySelectorAll('#fbadm-liste .fb-card').length === 2);
    doc.querySelector('.fb-card[data-id="fb"] .fb-act[data-akt="edit"]').click();
    await warte(10);
    c('Positivkontrolle: Editor von B offen',
      !!doc.querySelector('.fb-card[data-id="fb"] #fbadm-form'));
    doc.getElementById('fbadm-f-titel').value = 'B ungespeichert';
    doc.getElementById('fbadm-f-desc').value = 'neue Erklaerung';

    const cb = doc.querySelector('.fb-card[data-id="fa"] input[data-akt="aktiv"]');
    c('Positivkontrolle: Kaestchen „aktiv" an A gefunden', !!cb);
    cb.checked = false;
    ereignis(w, 'change', cb);
    await warte(60);
    const post = rufe.filter(r => r.u === '/api/feedback/admin/formulare' && r.m === 'POST');
    c('Positivkontrolle: A wurde gespeichert',
      post.length === 1 && JSON.parse(post[0].b).id === 'fa' && JSON.parse(post[0].b).aktiv === false,
      JSON.stringify(post.map(p => p.b)));
    c('⚠ der Editor von B ist noch offen',
      !!doc.querySelector('.fb-card[data-id="fb"] #fbadm-form'));
    c('⚠ der ungespeicherte Titel steht noch da',
      (doc.getElementById('fbadm-f-titel') || {}).value === 'B ungespeichert',
      (doc.getElementById('fbadm-f-titel') || {}).value);
    c('⚠ die ungespeicherte Erklaerung steht noch da',
      (doc.getElementById('fbadm-f-desc') || {}).value === 'neue Erklaerung');
    w.close();
  }

  console.log('\n2. Spalte im Editor ablegen erreicht die Formular-Liste nicht');
  {
    const { w, doc, rufe } = seite();
    await warte(60);
    doc.querySelector('.fb-card[data-id="fb"] .fb-act[data-akt="edit"]').click();
    await warte(10);
    doc.getElementById('fbadm-f-titel').value = 'B ungespeichert';
    const zeilen = [...doc.querySelectorAll('#fbadm-spalten .fb-sp')];
    c('Positivkontrolle: drei Spalten im Editor', zeilen.length === 3);
    const griff = zeilen[0].querySelector('.fb-griff');
    c('Positivkontrolle: Ziehgriff an der ersten Spalte', !!griff);
    // Erste Spalte hinter die letzte ziehen (untere Haelfte: clientY > 0,
    // jsdom liefert fuer getBoundingClientRect nur Nullen).
    ereignis(w, 'dragstart', griff);
    ereignis(w, 'dragover', zeilen[2], { clientY: 5 });
    const drop = ereignis(w, 'drop', zeilen[2], { clientY: 5 });
    ereignis(w, 'dragend', griff);
    await warte(60);
    c('Positivkontrolle: das Ablegen wurde angenommen', drop.defaultPrevented);
    const namen = [...doc.querySelectorAll('#fbadm-spalten .fb-sp-name')].map(x => x.value).join(',');
    c('die Spalten sind im Editor umgestellt', namen === 'Zwei,Drei,Eins', namen);
    c('⚠ KEIN Sortier-POST der Formular-Liste',
      !rufe.some(r => r.u === '/api/feedback/admin/formulare/reihenfolge'),
      rufe.map(r => r.m + ' ' + r.u).join(' | '));
    const karten = [...doc.querySelectorAll('#fbadm-liste > .fb-card')].map(k => k.getAttribute('data-id'));
    c('die Formular-Liste ist unveraendert (fa, fb)', karten.join(',') === 'fa,fb', karten.join(','));
    c('keine Spalte ist in die Formular-Liste gerutscht',
      !doc.querySelector('#fbadm-liste > .fb-sp'));
    c('⚠ der ungespeicherte Titel steht noch da',
      (doc.getElementById('fbadm-f-titel') || {}).value === 'B ungespeichert',
      (doc.getElementById('fbadm-f-titel') || {}).value);
    w.close();
  }

  console.log('\n3. Karten ziehen funktioniert weiter (Gegenstueck)');
  {
    const { w, doc, rufe } = seite();
    await warte(60);
    const k = [...doc.querySelectorAll('#fbadm-liste .fb-card')];
    const griff = k[0].querySelector(':scope > * .fb-griff, :scope > .fb-griff') || k[0].querySelector('.fb-griff');
    ereignis(w, 'dragstart', griff);
    ereignis(w, 'dragover', k[1], { clientY: 5 });
    ereignis(w, 'drop', k[1], { clientY: 5 });
    ereignis(w, 'dragend', griff);
    await warte(60);
    const s = rufe.filter(r => r.u === '/api/feedback/admin/formulare/reihenfolge');
    c('Karten-Ziehen schickt die neue Reihenfolge',
      s.length === 1 && JSON.stringify(JSON.parse(s[0].b).ids) === '["fb","fa"]',
      s.map(x => x.b).join(' | '));
    w.close();
  }

  console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
  clearTimeout(wd);
  process.exit(fail ? 1 : 0);
})().catch(e => {
  console.log('\nABBRUCH: ' + (e && e.stack || e));
  console.log(ok + ' OK, ' + (fail + 1) + ' FAIL (ABGEBROCHEN)');
  process.exit(1);
});
