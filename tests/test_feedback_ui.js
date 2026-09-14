/**
 * Die Feedback-Kachel (/feedback) und der Einstellungs-Reiter.
 *
 * ⚠ DER ECHTE RENDERER LAEUFT gegen die ECHTEN Dateien. Ob eine Tabelle
 * ENTSTEHT, ob ein Stern nach dem Klick wirklich gesetzt ist und ob der
 * Absende-Knopf die richtigen Zeilen schickt, kann eine Quelltext-Suche nicht
 * beantworten – genau daran ist im Projekt schon mehrfach ein Waechter
 * vorbeigelaufen.
 *
 *   node tests/test_feedback_ui.js      (JSDOM_PATH setzt den jsdom-Ort)
 */
const fs = require('fs');
let JSDOM = null;
for (const o of [process.env.JSDOM_PATH, 'jsdom',
                 '/tmp/node_modules/jsdom', './node_modules/jsdom',
                 process.env.HOME + '/node_modules/jsdom',
                 '/opt/jarvis/data/node_modules/jsdom', '/usr/share/nodejs/jsdom']) {
  if (!o) { continue; }
  try { JSDOM = require(o).JSDOM; break; } catch (e) { /* naechster Ort */ }
}
if (!JSDOM) {
  // Exit 2: „konnte nicht laufen" darf nie wie „bestanden" aussehen.
  console.error('jsdom nicht gefunden - Exit 2 (nicht gelaufen, nicht bestanden)');
  process.exit(2);
}

let ok = 0, fail = 0;
const c = (t, b, d) => {
  b ? (ok++, console.log('  OK   ' + t))
    : (fail++, console.log('  FAIL ' + t + (d ? '  – ' + d : '')));
};
// Wachhund: ohne ihn haengt ein Lauf im Fehlerfall bis zum Zeitlimit und
// beendet ohne Bilanzzeile – von „nicht gelaufen" nicht zu unterscheiden.
const wd = setTimeout(() => {
  console.log('\nWACHHUND: haengt\n' + ok + ' OK, ' + (fail + 1) + ' FAIL');
  process.exit(1);
}, 30000);

const FORM = {
  id: 'f1', titel: 'Modulbewertung', beschreibung: 'Bitte bewerte die Module.',
  aktiv: true,
  spalten: [{ id: 'c1', name: 'Modul', typ: 'text' },
            { id: 'c2', name: 'Note', typ: 'sterne' },
            { id: 'c3', name: 'Anmerkung', typ: 'text' }]
};

function seite(opt) {
  opt = opt || {};
  const d = new JSDOM(fs.readFileSync('frontend/feedback.html', 'utf8'),
                      { url: 'https://x/feedback', runScripts: 'outside-only' });
  const w = d.window;
  w.localStorage.setItem('jarvis_token', 't');
  const rufe = [];
  // ⚠ Der Parameter heisst NICHT `opt`: er wuerde die Optionen der Testfunktion
  // ueberschatten und sie still wirkungslos machen (Register, 2026-09-14).
  w.fetch = (u, o2) => {
    const p = String(u).split('?')[0];
    rufe.push({ u: p, m: (o2 && o2.method) || 'GET', b: o2 && o2.body });
    const J = x => Promise.resolve({ ok: true, status: 200,
                                     json: () => Promise.resolve(x) });
    if (p === '/api/me') {
      return J({ is_admin: !!opt.admin,
                 permissions: { feedback: opt.darf !== false } });
    }
    if (p === '/api/feedback/formulare') {
      return J({ ok: true, formulare: opt.formulare || [FORM] });
    }
    if (p === '/api/feedback/meine') {
      return J({ ok: true, abgaben: opt.meine || [] });
    }
    if (p === '/api/feedback/abgabe') {
      return J({ ok: true, abgabe: { id: 'a1', zeilen: JSON.parse(o2.body).zeilen } });
    }
    return J({ ok: true });
  };
  for (const f of ['js/icons.js', 'js/i18n.js', 'js/feedback.js']) {
    w.eval(fs.readFileSync('frontend/' + f, 'utf8'));
  }
  return { w, doc: w.document, rufe };
}

const warte = ms => new Promise(r => setTimeout(r, ms));

(async () => {
  // ═════════════════════════════════════════════════════════════════════════
  console.log('\n1. Die Tabelle entsteht aus den SPALTEN des Servers');
  // ═════════════════════════════════════════════════════════════════════════
  let { w, doc, rufe } = seite({});
  await warte(60);

  c('die Seite ist sichtbar (Positivkontrolle)',
    !doc.getElementById('fb-app').classList.contains('hidden'));
  const kopf = [...doc.querySelectorAll('#fb-tabelle thead th')].map(x => x.textContent);
  c('jede Spalte hat eine Ueberschrift',
    kopf.includes('Modul') && kopf.includes('Note') && kopf.includes('Anmerkung'),
    JSON.stringify(kopf));
  c('es gibt genau EINE Zeile zum Start',
    doc.querySelectorAll('#fb-tabelle tbody tr').length === 1);
  c('eine Text-Spalte ist ein Eingabefeld',
    doc.querySelectorAll('#fb-tabelle tbody input[type="text"]').length === 2);
  c('eine Sterne-Spalte ist eine Radiogruppe',
    !!doc.querySelector('#fb-tabelle tbody .fb-sterne[role="radiogroup"]'));
  c('mit genau fuenf Knoepfen',
    doc.querySelectorAll('#fb-tabelle tbody .fb-sterne button').length === 5);
  c('die Beschreibung des Formulars steht da',
    doc.getElementById('fb-form-desc').textContent.indexOf('bewerte') >= 0);
  c('⚠ die Auswahl ist bei EINEM Formular verborgen',
    doc.getElementById('fb-pick').classList.contains('hidden'),
    'ein Pulldown mit einem Eintrag ist ein Bedienelement ohne Wahl');

  // ═════════════════════════════════════════════════════════════════════════
  console.log('\n2. Zeilen anlegen und entfernen');
  // ═════════════════════════════════════════════════════════════════════════
  doc.getElementById('fb-zeile-neu').click();
  doc.getElementById('fb-zeile-neu').click();
  c('„+ Zeile" legt Zeilen an',
    doc.querySelectorAll('#fb-tabelle tbody tr').length === 3);
  c('die Zeilen sind durchnummeriert',
    [...doc.querySelectorAll('#fb-tabelle tbody .fb-c-nr')]
      .map(x => x.textContent).join(',') === '1,2,3');

  doc.querySelector('#fb-tabelle tbody .fb-row-del').click();
  c('der Muelleimer entfernt eine Zeile',
    doc.querySelectorAll('#fb-tabelle tbody tr').length === 2);
  c('und der Knopf traegt den Muelleimer, nicht ein ×',
    !!doc.querySelector('#fb-tabelle .fb-row-del .jv-ico-trash'));

  // ⚠ IMMER DEN AKTUELLEN ERSTEN KNOPF: die Tabelle wird bei jedem Klick neu
  // gezeichnet, eine vorher geholte NodeList zeigt danach auf tote Elemente –
  // die Schleife tat dann nur EINEN Klick und die Pruefung war trivial wahr
  // (in der Gegenprobe aufgefallen).
  for (let i = 0; i < 10; i++) {
    const b = doc.querySelector('#fb-tabelle tbody .fb-row-del');
    if (!b) { break; }
    b.click();
    if (doc.querySelectorAll('#fb-tabelle tbody tr').length === 0) { break; }
  }
  c('⚠ die LETZTE Zeile wird geleert, nicht entfernt',
    doc.querySelectorAll('#fb-tabelle tbody tr').length === 1,
    'eine leere Tabelle sieht nach einem Fehler aus');

  // ═════════════════════════════════════════════════════════════════════════
  console.log('\n3. Sterne: klicken, zuruecknehmen, Tastatur');
  // ═════════════════════════════════════════════════════════════════════════
  let sterne = doc.querySelector('#fb-tabelle tbody .fb-sterne');
  sterne.children[3].click();                      // vierter Stern
  c('ein Klick setzt den Wert', sterne.getAttribute('data-wert') === '4');
  c('vier Sterne sind gefuellt',
    [...sterne.children].filter(b => b.classList.contains('is-an')).length === 4);
  c('⚠ die Form unterscheidet sie, nicht nur die Farbe',
    !!sterne.children[0].querySelector('.is-gesetzt')
    && !sterne.children[4].querySelector('.is-gesetzt'),
    'Farbe allein ist keine Information');
  c('der Wert steht zusaetzlich als ZAHL da',
    (sterne.parentNode.querySelector('.fb-sterne-wert') || {}).textContent === '4/5');
  c('aria-checked folgt dem Zustand',
    sterne.children[3].getAttribute('aria-checked') === 'true'
    && sterne.children[4].getAttribute('aria-checked') === 'false');

  sterne.children[3].click();
  c('⚠ ein Klick auf denselben Stern nimmt die Bewertung ZURUECK',
    sterne.getAttribute('data-wert') === '0',
    'ohne diesen Weg waere ein Fehlklick nicht korrigierbar');

  const ev = new w.KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true });
  sterne.children[0].dispatchEvent(ev);
  c('Pfeiltaste erhoeht den Wert', sterne.getAttribute('data-wert') === '1');
  sterne.children[0].dispatchEvent(new w.KeyboardEvent('keydown',
    { key: 'ArrowLeft', bubbles: true }));
  c('und die Gegenrichtung senkt ihn', sterne.getAttribute('data-wert') === '0');

  // ═════════════════════════════════════════════════════════════════════════
  console.log('\n4. Absenden');
  // ═════════════════════════════════════════════════════════════════════════
  rufe.length = 0;
  doc.getElementById('fb-senden').click();
  await warte(30);
  c('⚠ eine leere Abgabe wird NICHT gesendet',
    !rufe.some(r => r.u === '/api/feedback/abgabe'),
    'die Meldung am Formular ist ehrlicher als ein Serverfehler');
  c('und die Meldung sagt warum',
    doc.getElementById('fb-status').textContent.length > 5);

  const feld = doc.querySelector('#fb-tabelle tbody input[type="text"]');
  feld.value = 'Rechnungswesen';
  feld.dispatchEvent(new w.Event('input', { bubbles: true }));
  doc.querySelector('#fb-tabelle tbody .fb-sterne').children[2].click();
  rufe.length = 0;
  doc.getElementById('fb-senden').click();
  await warte(60);

  const gesendet = rufe.find(r => r.u === '/api/feedback/abgabe');
  c('eine gefuellte Abgabe wird gesendet', !!gesendet);
  const rumpf = gesendet ? JSON.parse(gesendet.b) : {};
  c('sie traegt die Formular-Kennung', rumpf.formular_id === 'f1');
  c('und genau die gefuellte Zeile', (rumpf.zeilen || []).length === 1);
  c('die Werte stehen unter der SPALTEN-Kennung',
    rumpf.zeilen && rumpf.zeilen[0].c1 === 'Rechnungswesen' && rumpf.zeilen[0].c2 === 3,
    JSON.stringify(rumpf.zeilen));
  c('⚠ der Benutzer steht NICHT im Rumpf',
    !('user' in rumpf) && !('benutzer' in rumpf),
    'er kommt aus der Anmeldung');
  c('nach dem Senden steht ein frisches, leeres Formular da',
    doc.querySelectorAll('#fb-tabelle tbody tr').length === 1
    && doc.querySelector('#fb-tabelle tbody input[type="text"]').value === '');
  c('und eine Bestaetigung', doc.getElementById('fb-status').classList.contains('is-ok'));

  // ═════════════════════════════════════════════════════════════════════════
  console.log('\n5. Mehrere Formulare');
  // ═════════════════════════════════════════════════════════════════════════
  const ZWEI = [FORM, { id: 'f2', titel: 'Schulung', beschreibung: '', aktiv: true,
                        spalten: [{ id: 'x1', name: 'Thema', typ: 'text' }] }];
  ({ w, doc, rufe } = seite({ formulare: ZWEI }));
  await warte(60);
  c('bei MEHREREN Formularen erscheint die Auswahl',
    !doc.getElementById('fb-pick').classList.contains('hidden'));
  c('mit beiden Titeln',
    doc.querySelectorAll('#fb-form-sel option').length === 2);
  const sel = doc.getElementById('fb-form-sel');
  sel.value = 'f2';
  sel.dispatchEvent(new w.Event('change', { bubbles: true }));
  await warte(30);
  c('ein Wechsel zeichnet die Tabelle des anderen Formulars neu',
    [...doc.querySelectorAll('#fb-tabelle thead th')].some(x => x.textContent === 'Thema'));

  // ═════════════════════════════════════════════════════════════════════════
  console.log('\n6. Ohne Formular und ohne Freigabe');
  // ═════════════════════════════════════════════════════════════════════════
  ({ w, doc, rufe } = seite({ formulare: [] }));
  await warte(60);
  c('ohne Formular steht ein erklaerender Text da',
    (doc.getElementById('fb-tabelle').textContent || '').length > 20);
  c('und die Knoepfe sind gesperrt',
    doc.getElementById('fb-senden').disabled
    && doc.getElementById('fb-zeile-neu').disabled);

  // ═════════════════════════════════════════════════════════════════════════
  console.log('\n7. Eigene Abgaben: die Spalten kommen aus der ABGABE');
  // ═════════════════════════════════════════════════════════════════════════
  const ALT = {
    id: 'a9', formular_id: 'f1', formular_titel: 'Modulbewertung',
    zeit: '2026-09-14T10:00:00', benutzer: 'anna',
    // ⚠ Die Spalte heisst hier ANDERS als im heutigen Formular – genau das ist
    // der Sinn des Snapshots.
    spalten: [{ id: 'c1', name: 'Modul (alt)', typ: 'text' },
              { id: 'c2', name: 'Note', typ: 'sterne' }],
    zeilen: [{ c1: 'Lager', c2: 5 }]
  };
  ({ w, doc, rufe } = seite({ meine: [ALT] }));
  await warte(60);
  const mein = doc.getElementById('fb-meine');
  c('die eigene Abgabe wird gezeichnet', !!mein.querySelector('.fb-abgabe'));
  c('⚠ mit den Spalten AUS DER ABGABE, nicht aus dem heutigen Formular',
    (mein.textContent || '').indexOf('Modul (alt)') >= 0,
    'sonst stehen echte Daten unter einer Ueberschrift, die damals nicht galt');
  c('der Wert steht in der Zeile', (mein.textContent || '').indexOf('Lager') >= 0);
  c('die Sterne sind gefuellt gezeichnet',
    mein.querySelectorAll('.fb-stern.is-an').length === 5);
  c('und es gibt dort keine Knoepfe (nur lesen)',
    mein.querySelectorAll('.fb-abgabe-body button').length === 0);

  // ═════════════════════════════════════════════════════════════════════════
  console.log('\n8. Fremdtext wird nie als Markup gelesen');
  // ═════════════════════════════════════════════════════════════════════════
  const BOESE = {
    id: 'fx', titel: '<img src=x onerror="window.__b=1">', beschreibung: '',
    aktiv: true,
    spalten: [{ id: 'c1', name: '<b>fett</b>', typ: 'text' }]
  };
  ({ w, doc, rufe } = seite({ formulare: [BOESE, FORM] }));
  await warte(60);
  c('⚠ kein eingeschleustes Element aus einem Spaltennamen',
    doc.querySelectorAll('#fb-tabelle b').length === 0
    && doc.querySelectorAll('#fb-tabelle img').length === 0);
  c('der Name steht aber als TEXT da',
    [...doc.querySelectorAll('#fb-tabelle thead th')]
      .some(x => x.textContent === '<b>fett</b>'));
  c('und aus dem Titel entsteht kein Bild',
    doc.querySelectorAll('#fb-form-sel img').length === 0 && !w.__b);

  // ═════════════════════════════════════════════════════════════════════════
  console.log('\n9. Der Einstellungs-Reiter');
  // ═════════════════════════════════════════════════════════════════════════
  const ds = new JSDOM(fs.readFileSync('frontend/settings.html', 'utf8'),
                       { url: 'https://x/settings', runScripts: 'outside-only' });
  const ws = ds.window;
  ws.localStorage.setItem('jarvis_token', 't');
  const rufeS = [];
  ws.fetch = (u, o2) => {
    const p = String(u).split('?')[0];
    rufeS.push({ u: p, m: (o2 && o2.method) || 'GET', b: o2 && o2.body });
    const J = x => Promise.resolve({ ok: true, status: 200,
                                     json: () => Promise.resolve(x) });
    if (p === '/api/feedback/admin/formulare') {
      return J({ ok: true, formulare: [FORM], typen: ['text', 'sterne'],
                 max_spalten: 12, skill_aktiv: true });
    }
    if (p === '/api/feedback/admin/abgaben') { return J({ ok: true, abgaben: [] }); }
    return J({ ok: true });
  };
  ws.confirm = () => true;
  for (const f of ['js/icons.js', 'js/i18n.js', 'js/feedback_admin.js']) {
    ws.eval(fs.readFileSync('frontend/' + f, 'utf8'));
  }
  ws.FeedbackAdmin.onShow();
  await warte(60);
  const sdoc = ws.document;

  c('die Formularliste wird gezeichnet',
    sdoc.querySelectorAll('#fbadm-liste .fb-card').length === 1);
  c('mit Titel und Spaltenzahl',
    (sdoc.querySelector('#fbadm-liste .fb-card-name') || {}).textContent === 'Modulbewertung'
    && ((sdoc.querySelector('#fbadm-liste .fb-card-meta') || {}).textContent || '').indexOf('3') >= 0);
  c('jede Karte hat einen Ziehgriff',
    !!sdoc.querySelector('#fbadm-liste .fb-card .fb-griff[draggable="true"]'));
  c('der Griff ist mit der Tastatur erreichbar',
    (sdoc.querySelector('#fbadm-liste .fb-griff') || {}).getAttribute('tabindex') === '0');
  c('der Loeschknopf traegt den Muelleimer',
    !!sdoc.querySelector('#fbadm-liste .fb-card .jv-ico-trash'));

  // Editor oeffnen
  sdoc.querySelector('#fbadm-liste .fb-act[data-akt="edit"]').click();
  c('„Bearbeiten" oeffnet den Editor', !!sdoc.getElementById('fbadm-form'));
  c('⚠ und zwar IN der Karte, unter der Zeile',
    !!sdoc.querySelector('.fb-card[data-id="f1"] #fbadm-form'),
    'sonst sieht es nicht wie EIN Kasten aus');
  c('die Felder sind vorbelegt',
    sdoc.getElementById('fbadm-f-titel').value === 'Modulbewertung');
  c('jede Spalte hat eine Zeile im Editor',
    sdoc.querySelectorAll('#fbadm-spalten .fb-sp').length === 3);
  c('mit Namensfeld und Typ-Auswahl',
    sdoc.querySelector('#fbadm-spalten .fb-sp-name').value === 'Modul'
    && sdoc.querySelector('#fbadm-spalten .fb-sp-typ').value === 'text');
  c('die zweite Spalte steht auf „sterne"',
    sdoc.querySelectorAll('#fbadm-spalten .fb-sp-typ')[1].value === 'sterne');
  c('beide Typen stehen zur Wahl',
    sdoc.querySelectorAll('#fbadm-spalten .fb-sp')[0]
      .querySelectorAll('option').length === 2);
  c('auch die Spalten haben einen Ziehgriff',
    sdoc.querySelectorAll('#fbadm-spalten .fb-sp .fb-griff').length === 3);

  sdoc.getElementById('fbadm-sp-neu').click();
  c('„+ Spalte" haengt eine an',
    sdoc.querySelectorAll('#fbadm-spalten .fb-sp').length === 4);
  sdoc.querySelectorAll('#fbadm-spalten .fb-sp-del')[3].click();
  c('der Muelleimer entfernt sie wieder',
    sdoc.querySelectorAll('#fbadm-spalten .fb-sp').length === 3);

  // Speichern
  rufeS.length = 0;
  sdoc.getElementById('fbadm-f-save').click();
  await warte(40);
  const gesp = rufeS.find(r => r.u === '/api/feedback/admin/formulare' && r.m === 'POST');
  c('„Speichern" sendet an den Admin-Endpunkt', !!gesp);
  const body = gesp ? JSON.parse(gesp.b) : {};
  c('mit der Kennung des bearbeiteten Formulars', body.id === 'f1');
  c('⚠ und die SPALTEN-Kennungen bleiben erhalten',
    (body.spalten || []).map(s => s.id).join(',') === 'c1,c2,c3',
    'sonst ist jede vorhandene Abgabe nicht mehr zuzuordnen');

  // Zweiter Klick auf „Bearbeiten" schliesst
  sdoc.querySelector('#fbadm-liste .fb-act[data-akt="edit"]').click();
  c('ein Klick auf „Bearbeiten" oeffnet wieder', !!sdoc.getElementById('fbadm-form'));
  sdoc.querySelector('#fbadm-liste .fb-act[data-akt="edit"]').click();
  c('⚠ der ZWEITE Klick schliesst', !sdoc.getElementById('fbadm-form'),
    'sonst tut der Knopf sichtbar nichts');

  // Aktiv-Schalter
  rufeS.length = 0;
  const kast = sdoc.querySelector('#fbadm-liste input[data-akt="aktiv"]');
  kast.checked = false;
  kast.dispatchEvent(new ws.Event('change', { bubbles: true }));
  await warte(40);
  const asp = rufeS.find(r => r.u === '/api/feedback/admin/formulare' && r.m === 'POST');
  c('der Aktiv-Schalter speichert', !!asp);
  c('und schickt aktiv: false', asp && JSON.parse(asp.b).aktiv === false);
  c('⚠ ohne die Spalten zu verlieren',
    asp && (JSON.parse(asp.b).spalten || []).length === 3);

  console.log('\n' + '='.repeat(70));
  console.log(ok + ' OK, ' + fail + ' FAIL');
  clearTimeout(wd);
  try { w.close(); ws.close(); } catch (e) { /* egal */ }
  process.exit(fail ? 1 : 0);
})().catch(e => {
  // Ein Absturz darf nicht als Exit 0 ohne Bilanz enden (Register).
  console.log('\nABBRUCH: ' + (e && e.stack || e));
  console.log(ok + ' OK, ' + (fail + 1) + ' FAIL (ABGEBROCHEN)');
  process.exit(1);
});
