#!/usr/bin/env node
/**
 * Oberflaeche von Short Tracks: Fragefeld und Referenzdateien (seit 2026-11-06).
 *
 * Geprueft wird gegen die ECHTEN Dateien (tracks.html, tracks.js, i18n.js,
 * icons.js, sitzung.js) – ein Test, der sein Markup selbst baut, prueft nur
 * seine eigene Annahme.
 *
 * Teil 1  Karte: Fragefeld nur bei eingeschaltetem Feld UND aktiver Ablage
 * Teil 2  Fragen: leer/zu lang abgewiesen, Senden, Enter, Feld erst nach Annahme leeren
 * Teil 3  Auftrag einer Frage ist erkennbar
 * Teil 4  Formular: Haken vorbelegt und gesendet, Referenzliste, Upload, Loeschen
 * Teil 5  Texte DE+EN, Cache-Buster
 *
 *   node tests/test_short_tracks_fragen_ui.js
 */

require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1
const fs = require('fs');
const path = require('path');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  ✓ ' + t); }
    else { fail++; console.log('  ✗ ' + t + (d ? ' – ' + d : '')); }
};
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');

const ROOT = path.resolve(__dirname, '..');
const { JSDOM } = require('./lib/jsdom_laden')();
const lies = (rel) => fs.readFileSync(path.join(ROOT, rel), 'utf8');
const TR_HTML = lies('frontend/tracks.html');
const TR_JS = lies('frontend/js/tracks.js');
const I18N = lies('frontend/js/i18n.js');
const ICONS = lies('frontend/js/icons.js');
const SITZUNG = lies('frontend/js/sitzung.js');
const SEITE_BREIT = lies('frontend/js/seite_breit.js');
const CHATLIB = lies('frontend/js/chatlib.js');

const GRENZEN = {
    gleichzeitig: 2, max_datei_mb: 50, max_dateien: 3, max_dumps: 10,
    max_dumps_global: 30, prompt_max: 8000, hinweis_max: 1000,
    name_max: 60, beschreibung_max: 200, frage_max: 40,
    max_referenzen: 3, ref_max_mb: 10
};
const BEREICHE = [{ id: 'basis', name: 'Lesen', hinweis: 'h', freigegeben: true,
                    pflicht: true, werkzeuge: ['office_read'] }];
const basisDump = (o) => Object.assign({
    owner: 'm.mustermann', global: false, beschreibung: '', prompt: 'p',
    bereiche: ['basis'], dateitypen: [], mehrfach: 'einzeln', profile_id: '',
    reasoning_effort: '', max_steps: 0, enabled: true, laeufe: 0,
    fragen: false, referenzen: []
}, o);
const DUMPS = [
    basisDump({ id: 'aaaaaaaaaaaa', name: 'Schema', fragen: true,
                referenzen: [{ name: 'schema.sql', groesse: 2048, geaendert: 1 },
                             { name: '<img src=x onerror=alert(1)>.sql', groesse: 10, geaendert: 1 }] }),
    basisDump({ id: 'bbbbbbbbbbbb', name: 'Rechnung', fragen: false }),
    basisDump({ id: 'cccccccccccc', name: 'Aus', fragen: true, enabled: false })
];

function baue(opt) {
    opt = opt || {};
    const dom = new JSDOM(TR_HTML, { url: 'https://x/tracks', runScripts: 'outside-only' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'T');
    Object.defineProperty(w.document, 'hidden', { value: false, configurable: true });
    const rufe = [];
    let dumps = JSON.parse(JSON.stringify(opt.dumps || DUMPS));
    let jobs = JSON.parse(JSON.stringify(opt.jobs || []));
    w.fetch = (url, o) => {
        o = o || {};
        let body = null;
        if (o.body && typeof o.body === 'string') { try { body = JSON.parse(o.body); } catch (e) { } }
        rufe.push({ url: String(url), methode: o.method || 'GET', body: body,
                    form: (o.body && typeof o.body !== 'string') ? o.body : null });
        // Ueber den PFAD routen (Register): `?lang=` haengt am Status.
        const pfad = String(url).split('?')[0];
        const gib = (d, status) => Promise.resolve({
            ok: (status || 200) < 400, status: status || 200,
            json: () => Promise.resolve(d)
        });
        if (pfad === '/api/me') {
            return gib({ username: 'm.mustermann', is_admin: false, permissions: { tracks: true } });
        }
        if (pfad === '/api/tracks/status') {
            return gib({ ok: true, skill_aktiv: true, ist_admin: false, internet: true,
                         dumps: dumps, bereiche: BEREICHE, grenzen: GRENZEN });
        }
        if (pfad === '/api/tracks/jobs') {
            return gib({ ok: true, jobs: jobs, zaehler: { neu: 0, aktiv: 0 } });
        }
        if (pfad === '/api/tracks/ask') {
            if (opt.askFehler) return gib({ ok: false, error: opt.askFehler }, 400);
            jobs = jobs.concat([{ id: 'jf', dump_id: body.dump_id, dump: 'Schema', art: 'frage',
                                  titel: body.frage, status: 'wartet', schritte: [],
                                  ergebnis: '', dateien: [], fehler: '' }]);
            return gib({ ok: true, jobs: [jobs[jobs.length - 1]] });
        }
        let m = /^\/api\/tracks\/dumps\/([^/]+)\/refs$/.exec(pfad);
        if (m && o.method === 'POST') {
            const namen = o.body && o.body.getAll ? o.body.getAll('files').map(f => f.name) : [];
            dumps = dumps.map(x => x.id === m[1] ? Object.assign({}, x, {
                referenzen: x.referenzen.concat(namen.map(n => ({ name: n, groesse: 5, geaendert: 2 })))
            }) : x);
            return gib({ ok: true, uebernommen: namen.map(n => ({ name: n })), abgewiesen: [],
                         referenzen: [] });
        }
        m = /^\/api\/tracks\/dumps\/([^/]+)\/refs\/([^/]+)$/.exec(pfad);
        if (m && o.method === 'DELETE') {
            const name = decodeURIComponent(m[2]);
            dumps = dumps.map(x => x.id === m[1] ? Object.assign({}, x, {
                referenzen: x.referenzen.filter(r => r.name !== name)
            }) : x);
            return gib({ ok: true, referenzen: [] });
        }
        if (pfad === '/api/tracks/log') {
            return gib({ ok: true, eintraege: opt.log || [] });
        }
        if (pfad === '/api/tracks/drop') {
            jobs = jobs.concat([{ id: 'jd', dump_id: 'bbbbbbbbbbbb', dump: 'Rechnung', art: 'datei',
                                  titel: 'neu.pdf', status: 'wartet', schritte: [],
                                  ergebnis: '', dateien: [], fehler: '' }]);
            return gib({ ok: true, jobs: [jobs[jobs.length - 1]], abgewiesen: [] });
        }
        if (/^\/api\/tracks\/dumps\/[^/]+$/.test(pfad) && o.method === 'PUT') {
            const id = pfad.split('/').pop();
            dumps = dumps.map(x => x.id === id ? Object.assign({}, x, body) : x);
            return gib({ ok: true, dump: dumps.filter(x => x.id === id)[0] });
        }
        return gib({ ok: true });
    };
    w.confirm = () => (opt.confirm === undefined ? true : opt.confirm);
    w.eval(SITZUNG);
    w.eval(ICONS);
    w.eval(I18N);
    w.eval(SEITE_BREIT);
    // Wie die Seite: chatlib.js (Renderer) VOR tracks.js – ausser im Test des
    // Rueckfalls ohne Renderer.
    if (opt.ohneChatlib !== true) w.eval(CHATLIB);
    // Beobachter VOR dem ersten Zeichnen: jedes Bild, das je ins Dokument kommt.
    w._eingefuegteBilder = [];
    new w.MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => {
        if (n.nodeType !== 1) return;
        const imgs = n.tagName === 'IMG' ? [n] : Array.from(n.querySelectorAll('img'));
        imgs.forEach((i) => w._eingefuegteBilder.push(i.getAttribute('src') || ''));
    }))).observe(w.document, { childList: true, subtree: true });
    w.eval(TR_JS);
    return { w, rufe, dumps: () => dumps };
}

const warte = (ms) => new Promise(r => setTimeout(r, ms || 50));
const karte = (w, id) => w.document.querySelector('.st-dump[data-dump="' + id + '"]');
const schliesse = async (w) => {
    try { if (w.jarvisTracks && w.jarvisTracks.stop) w.jarvisTracks.stop(); } catch (e) { }
    w.fetch = () => new Promise(() => { });
    await warte(10);
    w.close();
};
const askRufe = (rufe) => rufe.filter(r => r.url.split('?')[0] === '/api/tracks/ask');

(async () => {

abschnitt('1. Karte: Fragefeld und Referenzen');
{
    const { w } = baue({});
    await warte(80);
    const k1 = karte(w, 'aaaaaaaaaaaa'), k2 = karte(w, 'bbbbbbbbbbbb'), k3 = karte(w, 'cccccccccccc');
    // Positivkontrolle: das Brett ist ueberhaupt gezeichnet
    if (!k1 || !k2 || !k3) {
        console.log('ABBRUCH: das Brett wurde nicht gezeichnet – kein Teil dieses Waechters ist deutbar');
        process.exit(2);
    }
    pruefe(!!k1.querySelector('[data-act="ask-text"]') && !!k1.querySelector('[data-act="ask"]'),
        'Ablage mit eingeschaltetem Fragefeld zeigt Feld und Knopf');
    pruefe(!k2.querySelector('[data-act="ask-text"]'), 'Ablage OHNE Fragefeld zeigt keins');
    pruefe(!k3.querySelector('[data-act="ask-text"]'),
        'eine ABGESCHALTETE Ablage zeigt kein Fragefeld (der Server wiese mit 404 ab)');
    pruefe(!!k1.querySelector('[data-act="note"]'), 'das Hinweisfeld fuer Dateien bleibt daneben');
    const refs = k1.querySelector('[data-refs-zeile]');
    pruefe(refs && refs.textContent.indexOf('schema.sql') >= 0, 'Referenzen stehen mit Namen auf der Karte');
    pruefe(refs && !refs.querySelector('img'), 'ein Referenzname wird escaped (kein <img> im DOM)');
    pruefe(!k2.querySelector('[data-refs-zeile]'), 'ohne Referenzen keine Referenzzeile');
    pruefe(!k1.querySelector('a[href*="/refs"]'), 'es gibt keinen Download-Link fuer Referenzen');
    const feld = k1.querySelector('[data-act="ask-text"]');
    pruefe(feld && feld.getAttribute('maxlength') === String(GRENZEN.frage_max),
        'das Feld traegt die Grenze aus dem Status', feld && feld.getAttribute('maxlength'));
    await schliesse(w);
}

abschnitt('2. Fragen stellen');
{
    const { w, rufe } = baue({});
    await warte(80);
    const k = karte(w, 'aaaaaaaaaaaa');
    const feld = k.querySelector('[data-act="ask-text"]');
    const knopf = k.querySelector('[data-act="ask"]');
    feld.value = '   ';
    knopf.click();
    await warte();
    pruefe(askRufe(rufe).length === 0, 'eine leere Frage wird nicht gesendet');
    pruefe(/Frage eingeben/.test((w.document.querySelector('.st-toast') || {}).textContent || ''),
        'und es gibt eine Rueckmeldung');
    feld.value = 'x'.repeat(GRENZEN.frage_max + 1);
    knopf.click();
    await warte();
    pruefe(askRufe(rufe).length === 0, 'eine zu lange Frage wird nicht gesendet (und nicht gekuerzt)');
    pruefe(feld.value.length === GRENZEN.frage_max + 1, 'das Feld bleibt unveraendert stehen');

    feld.value = '  Welche Spalten hat kunde?  ';
    knopf.click();
    await warte(80);
    const a = askRufe(rufe);
    pruefe(a.length === 1 && a[0].methode === 'POST', 'die Frage geht als POST an /api/tracks/ask');
    pruefe(a[0] && a[0].body && a[0].body.dump_id === 'aaaaaaaaaaaa'
           && a[0].body.frage === 'Welche Spalten hat kunde?',
        'mit Ablage und getrimmter Frage', JSON.stringify(a[0] && a[0].body));
    pruefe(feld.value === '', 'nach der ANNAHME ist das Feld leer');
    pruefe(rufe.some(r => r.url.split('?')[0] === '/api/tracks/jobs'
                         && rufe.indexOf(r) > rufe.indexOf(a[0])),
        'danach werden die Auftraege neu geladen');

    // Enter sendet, Umschalt+Enter nicht.
    const vorher = askRufe(rufe).length;
    feld.value = 'zweite';
    feld.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', shiftKey: true, bubbles: true }));
    await warte(60);
    pruefe(askRufe(rufe).length === vorher, 'Umschalt+Enter sendet NICHT (neue Zeile)');
    feld.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    await warte(60);
    pruefe(askRufe(rufe).length === vorher + 1, 'Enter sendet');
    await schliesse(w);
}
{
    const { w, rufe } = baue({ askFehler: 'Diese Ablage nimmt keine Fragen an' });
    await warte(80);
    const k = karte(w, 'aaaaaaaaaaaa');
    const feld = k.querySelector('[data-act="ask-text"]');
    feld.value = 'Bleibt das stehen?';
    k.querySelector('[data-act="ask"]').click();
    await warte(80);
    pruefe(askRufe(rufe).length === 1, '(Vorbedingung) die Frage wurde gesendet');
    pruefe(feld.value === 'Bleibt das stehen?', 'bei einem FEHLER bleibt die Frage im Feld stehen');
    const t = w.document.querySelector('.st-toast');
    pruefe(t && t.classList.contains('is-bad') && /keine Fragen/.test(t.textContent),
        'und der Grund des Servers wird angezeigt');
    pruefe(!k.querySelector('[data-act="ask"]').disabled, 'der Knopf ist danach wieder bedienbar');
    await schliesse(w);
}

abschnitt('2b. Abfragetakt: nach dem Absenden gilt der SCHNELLE Takt');
/* Gesehen im Browser auf DEV (2026-11-06): ein Lauf war nach 3 s fertig, die
   Karte zeigte 15 s lang "laeuft …". `takt()` lief VOR dem Neuladen der
   Auftraege und waehlte an der alten Liste den Ruhetakt. Gemessen wird die
   Verzoegerung, die der Takt plant – nicht ein Vorkommen im Quelltext. */
for (const weg of ['frage', 'drop']) {
    const { w } = baue({});
    await warte(80);
    const plan = [];
    const echt = w.setTimeout.bind(w);
    w.setTimeout = (f, ms, ...a) => { plan.push(ms); return echt(f, ms, ...a); };
    w.jarvisTracks.ladeJobs();
    await warte(30);
    // Positivkontrolle: ohne aktiven Auftrag plant ein Takt den RUHEtakt –
    // sonst unterschiede die Messung nicht.
    const vor = plan.length;
    if (weg === 'frage') {
        const k = karte(w, 'aaaaaaaaaaaa');
        k.querySelector('[data-act="ask-text"]').value = 'Takt?';
        k.querySelector('[data-act="ask"]').click();
    } else {
        const d = karte(w, 'bbbbbbbbbbbb').querySelector('[data-act="drop"]');
        const ev = new w.Event('drop', { bubbles: true, cancelable: true });
        ev.dataTransfer = { files: [new w.File(['x'], 'neu.pdf')], getData: () => '' };
        d.dispatchEvent(ev);
    }
    await warte(120);
    const danach = plan.slice(vor);
    pruefe(danach.indexOf(2000) >= 0,
        weg + ': nach dem Absenden plant der Takt 2 s (schnell), nicht 15 s', JSON.stringify(danach));
    pruefe(danach.indexOf(15000) < 0,
        weg + ': und KEIN Ruhetakt dazwischen', JSON.stringify(danach));
    w.setTimeout = echt;
    await schliesse(w);
}
{
    // Positivkontrolle der Messmethode: ohne Auftrag plant takt() den Ruhetakt.
    const { w } = baue({});
    await warte(80);
    const plan = [];
    const echt = w.setTimeout.bind(w);
    w.setTimeout = (f, ms, ...a) => { plan.push(ms); return echt(f, ms, ...a); };
    w.document.dispatchEvent(new w.Event('visibilitychange'));
    await warte(60);
    pruefe(plan.indexOf(15000) >= 0, 'Positivkontrolle: ohne aktiven Auftrag plant der Takt 15 s',
        JSON.stringify(plan));
    w.setTimeout = echt;
    await schliesse(w);
}

abschnitt('3. Auftrag einer Frage');
{
    const { w } = baue({ jobs: [
        { id: 'j1', dump_id: 'aaaaaaaaaaaa', art: 'frage', titel: 'Welche Spalten?',
          status: 'fertig', schritte: [], ergebnis: 'id, name', dateien: [], fehler: '' },
        { id: 'j2', dump_id: 'aaaaaaaaaaaa', art: 'datei', titel: 'neu.sql',
          status: 'fertig', schritte: [], ergebnis: 'ok', dateien: [], fehler: '' }] });
    await warte(100);
    const zeilen = karte(w, 'aaaaaaaaaaaa').parentNode
        .querySelectorAll('[data-jobs="aaaaaaaaaaaa"] .st-job');
    pruefe(zeilen.length === 2, 'beide Auftraege erscheinen', String(zeilen.length));
    const frage = Array.from(zeilen).filter(z => z.textContent.indexOf('Welche Spalten?') >= 0)[0];
    const datei = Array.from(zeilen).filter(z => z.textContent.indexOf('neu.sql') >= 0)[0];
    pruefe(frage && !!frage.querySelector('.st-job-art'), 'eine Frage traegt die Marke „Frage“');
    pruefe(datei && !datei.querySelector('.st-job-art'), 'ein Datei-Auftrag nicht');
    pruefe(frage && frage.textContent.indexOf('id, name') >= 0, 'die Antwort steht darunter');
    await schliesse(w);
}

abschnitt('3b. Ergebnis als formatierter Text (alle Ablagen)');
{
    const MD = 'Die Tabelle hat drei Spalten:\n\n| Spalte | Typ |\n|---|---|\n| `lfr_kennung` | int |\n' +
        '| lfr_name | text |\n\n```sql\nSELECT lfr_name\nFROM zz_lieferant_q7;\n```\n\n- **fett** und Liste\n' +
        '<img src=x onerror=alert(1)>\n' +
        '![Spur](https://fremd.example/p.png?d=GEHEIM)\n![Spur2](//fremd.example/q.png)\n' +
        '![Eigen](/api/documents/' + 'a'.repeat(32) + '__bild.png)\n' +
        '```mermaid\ngraph TD; A-->B\n```';
    const { w } = baue({ jobs: [{ id: 'j1', dump_id: 'aaaaaaaaaaaa', art: 'frage', titel: 'T',
        status: 'fertig', schritte: [], ergebnis: MD, dateien: [], fehler: '' }],
        log: [{ ts: 1, dump: 'Schema', titel: 'T', ok: true, ergebnis: MD, dauer_s: 1, dateien: [] }] });
    await warte(120);
    const res = w.document.querySelector('[data-jobs="aaaaaaaaaaaa"] .st-job-res');
    // Positivkontrolle: der Renderer ist geladen und das Ergebnis ueberhaupt da
    if (!res || !w.JarvisChatLib) {
        console.log('ABBRUCH: Ergebnisfeld oder Renderer fehlt – Teil 3b nicht deutbar');
        process.exit(2);
    }
    pruefe(res.classList.contains('is-md'), 'das Ergebnis ist als formatierter Text gekennzeichnet');
    pruefe(!!res.querySelector('table th') && res.querySelectorAll('table td').length === 4,
        'eine Markdown-Tabelle wird zur Tabelle', res.querySelectorAll('td').length + ' Zellen');
    pruefe(res.textContent.indexOf('|---|') < 0, 'kein `|---|` mehr im sichtbaren Text');
    const pre = res.querySelector('pre');
    pruefe(pre && /SELECT lfr_name\s*FROM zz_lieferant_q7;/.test(pre.textContent),
        'SQL steht als Codeblock (Zeilen erhalten)', pre && pre.textContent);
    pruefe(res.textContent.indexOf('```') < 0, 'keine Zaeune ``` im sichtbaren Text');
    pruefe(!!res.querySelector('li strong'), 'Liste und Fettdruck werden umgesetzt');
    pruefe(!res.querySelector('[onerror]') && res.textContent.indexOf('<img src=x') >= 0,
        'HTML aus der Antwort wird als Text gezeigt, nicht ausgefuehrt');
    const bilder = Array.from(res.querySelectorAll('img')).map(i => i.getAttribute('src') || '');
    pruefe(!bilder.some(b => /fremd\.example/.test(b)), 'ein Bild von fremder Adresse ist NICHT im Ergebnis',
        bilder.join(' '));
    pruefe(!w._eingefuegteBilder.some(b => /fremd\.example/.test(b)),
        'und es war auch NIE im Dokument (kein Abruf beim Anzeigen)', w._eingefuegteBilder.join(' '));
    pruefe(res.querySelectorAll('.st-img-weg').length === 2,
        'beide fremden Bilder (auch `//host`) sind sichtbar als ausgeblendet benannt',
        String(res.querySelectorAll('.st-img-weg').length));
    pruefe(bilder.some(b => b.indexOf('/api/documents/') === 0), 'ein eigenes Bild (/api/documents/) bleibt');
    pruefe(!res.querySelector('.jarvis-mermaid') && /graph TD/.test(res.textContent),
        'ein Schaubild-Block bleibt als Code lesbar (kein leerer Platzhalter)');
    // Protokoll: dieselbe Darstellung
    w.jarvisTracks.ladeLog();
    await warte(80);
    const log = w.document.querySelector('.st-log-res');
    pruefe(log && log.classList.contains('is-md') && !!log.querySelector('table'),
        'auch das Protokoll zeigt formatierten Text');
    pruefe(!w._eingefuegteBilder.some(b => /fremd\.example/.test(b)),
        'auch dort kein fremdes Bild im Dokument');
    await schliesse(w);
}
{
    const { w } = baue({ ohneChatlib: true, jobs: [{ id: 'j1', dump_id: 'aaaaaaaaaaaa', titel: 'T',
        status: 'fertig', schritte: [], ergebnis: '| a | b |\n<b>x</b>', dateien: [], fehler: '' }] });
    await warte(100);
    const res = w.document.querySelector('[data-jobs="aaaaaaaaaaaa"] .st-job-res');
    pruefe(res && !res.classList.contains('is-md') && res.textContent === '| a | b |\n<b>x</b>'
           && !res.querySelector('b'),
        'ohne Renderer: Rohtext wie bisher, nichts als HTML eingesetzt');
    await schliesse(w);
}

abschnitt('4. Formular: Fragefeld-Haken und Referenzen');
{
    const { w, rufe } = baue({});
    await warte(80);
    w.jarvisTracks.formOeffnen('aaaaaaaaaaaa', karte(w, 'aaaaaaaaaaaa'));
    await warte(30);
    const haken = w.document.getElementById('st-f-fragen');
    pruefe(haken && haken.checked === true, 'der Haken ist aus der Ablage vorbelegt');
    const liste = w.document.querySelectorAll('#st-f-refs .st-ref-list li');
    pruefe(liste.length === 2, 'die Referenzliste nennt beide Dateien', String(liste.length));
    pruefe(liste[0] && liste[0].textContent.indexOf('2 KB') >= 0, 'mit Groesse', liste[0] && liste[0].textContent);
    const del = w.document.querySelector('#st-f-refs [data-refdel="schema.sql"]');
    pruefe(del && !!del.querySelector('svg.jv-ico-trash'), 'Loeschen traegt den Muelleimer (kein ×)');
    pruefe(!w.document.querySelector('#st-f-refs img'), 'auch im Formular wird der Name escaped');
    pruefe(!!w.document.getElementById('st-f-ref-add'), 'es gibt einen Knopf zum Hinzufuegen');
    const help = w.document.getElementById('st-help-refs');
    pruefe(help && /erfährt den Inhalt der Referenzen/.test(help.textContent),
        'der Hilfetext sagt, dass Benutzer der Ablage den Inhalt erfahren');

    // Haken aus → beim Speichern geht fragen:false mit.
    haken.checked = false;
    w.document.getElementById('st-f-save').click();
    await warte(80);
    const put = rufe.filter(r => r.methode === 'PUT').pop();
    pruefe(put && put.body && put.body.fragen === false, 'Speichern sendet `fragen` (false)',
        JSON.stringify(put && put.body));
    await schliesse(w);
}
{
    const { w, rufe } = baue({});
    await warte(80);
    w.jarvisTracks.formOeffnen('aaaaaaaaaaaa', karte(w, 'aaaaaaaaaaaa'));
    await warte(30);
    w.document.getElementById('st-f-name').value = 'ungespeichert';
    // Hochladen: ueber das versteckte Eingabefeld, wie der Knopf es oeffnet.
    w.document.getElementById('st-f-ref-add').click();
    const inp = w.document.getElementById('st-ref-input');
    const datei = new w.File(['CREATE TABLE x;'], 'neu.sql', { type: 'text/plain' });
    Object.defineProperty(inp, 'files', { value: [datei], configurable: true });
    inp.dispatchEvent(new w.Event('change'));
    await warte(120);
    const post = rufe.filter(r => r.methode === 'POST' && /\/refs$/.test(r.url.split('?')[0]));
    pruefe(post.length === 1 && post[0].url.indexOf('/api/tracks/dumps/aaaaaaaaaaaa/refs') === 0,
        'die Datei geht an /api/tracks/dumps/<id>/refs');
    pruefe(post[0] && post[0].form && post[0].form.getAll('files').length === 1,
        'als Multipart mit `files`');
    const namen = Array.from(w.document.querySelectorAll('#st-f-refs .st-ref-name')).map(e => e.textContent);
    pruefe(namen.indexOf('neu.sql') >= 0, 'die Liste im offenen Formular zeigt die neue Datei', namen.join(','));
    pruefe(w.document.getElementById('st-f-name').value === 'ungespeichert',
        'ungespeicherte Eingaben im Formular bleiben dabei erhalten');
    pruefe(!rufe.some(r => r.methode === 'PUT'), 'der Upload speichert die Ablage NICHT mit');
    pruefe(w.document.getElementById('st-f-ref-add').disabled === true,
        'am Deckel (3 von 3) ist der Knopf gesperrt');

    // Loeschen mit Rueckfrage, Name kodiert
    const btn = w.document.querySelector('#st-f-refs [data-refdel="schema.sql"]');
    btn.click();
    await warte(120);
    const dl = rufe.filter(r => r.methode === 'DELETE');
    pruefe(dl.length === 1 && dl[0].url === '/api/tracks/dumps/aaaaaaaaaaaa/refs/schema.sql',
        'Loeschen ruft DELETE …/refs/<name>', dl[0] && dl[0].url);
    const namen2 = Array.from(w.document.querySelectorAll('#st-f-refs .st-ref-name')).map(e => e.textContent);
    pruefe(namen2.indexOf('schema.sql') < 0, 'und die Liste ist danach aktualisiert');
    const xss = w.document.querySelector('#st-f-refs [data-refdel^="<img"]');
    if (xss) {
        xss.click();
        await warte(120);
        const dl2 = rufe.filter(r => r.methode === 'DELETE').pop();
        pruefe(dl2 && dl2.url.indexOf('%3Cimg') > 0 && dl2.url.indexOf('<') < 0,
            'ein Name mit Sonderzeichen wird in der Adresse kodiert', dl2 && dl2.url);
    } else {
        pruefe(false, 'der Knopf fuer den Sonderzeichen-Namen ist auffindbar');
    }
    await schliesse(w);
}
{
    const { w, rufe } = baue({ confirm: false });
    await warte(80);
    w.jarvisTracks.formOeffnen('aaaaaaaaaaaa', karte(w, 'aaaaaaaaaaaa'));
    await warte(30);
    w.document.querySelector('#st-f-refs [data-refdel="schema.sql"]').click();
    await warte(60);
    pruefe(!rufe.some(r => r.methode === 'DELETE'), 'ohne Bestaetigung wird nichts geloescht');
    w.jarvisTracks.formSchliessen();
    w.jarvisTracks.formOeffnen('neu', null);
    await warte(30);
    pruefe(!w.document.getElementById('st-f-ref-add'),
        'eine NEUE Ablage hat noch keinen Upload-Knopf (keine Kennung)');
    pruefe(/sobald die Ablage gespeichert ist/.test(w.document.getElementById('st-f-refs').textContent),
        'sondern einen Hinweis');
    pruefe(w.document.getElementById('st-f-fragen').checked === false,
        'eine neue Ablage hat das Fragefeld aus');
    await schliesse(w);
}

abschnitt('5. Texte und Einbindung');
{
    const keys = ['tracks.ask_ph', 'tracks.ask_btn', 'tracks.ask_empty', 'tracks.ask_too_long',
                  'tracks.ask_sending', 'tracks.ask_queued', 'tracks.job_question',
                  'tracks.refs_on_card', 'tracks.f_fragen', 'tracks.help_fragen', 'tracks.f_refs',
                  'tracks.help_refs', 'tracks.refs_none', 'tracks.refs_add', 'tracks.refs_limit',
                  'tracks.refs_after_save', 'tracks.refs_uploading', 'tracks.refs_done',
                  'tracks.refs_rejected', 'tracks.refs_del', 'tracks.refs_del_ask',
                  'tracks.refs_deleted', 'tracks.img_blocked'];
    // Die Tabelle DIREKT lesen: `t()` faellt fuer Englisch auf Deutsch zurueck –
    // ueber t() geprueft waere "EN vorhanden" trivial wahr.
    const dom = new JSDOM('<!doctype html><body></body>',
                          { url: 'https://x/', runScripts: 'outside-only' });
    dom.window.eval(I18N + '\n;window.__I18N = _I18N;');
    const tab = dom.window.__I18N || {};
    pruefe(!!(tab.de && tab.en && tab.de['tracks.note_ph'] && tab.en['tracks.note_ph']),
        '(Positivkontrolle) die Tabelle ist lesbar und kennt einen Bestandsschluessel');
    const fehlt = { de: keys.filter(k => !(tab.de || {})[k]), en: keys.filter(k => !(tab.en || {})[k]) };
    pruefe(fehlt.de.length === 0, 'alle neuen Schluessel auf Deutsch', fehlt.de.join(','));
    pruefe(fehlt.en.length === 0, 'alle neuen Schluessel auf Englisch', fehlt.en.join(','));
    const gleich = keys.filter(k => (tab.de || {})[k] && (tab.de || {})[k] === (tab.en || {})[k]);
    pruefe(gleich.length === 0, 'kein englischer Wert ist der deutsche', gleich.join(','));
    dom.window.close();
    pruefe(/\/static\/js\/tracks\.js\?v=(\d+)/.test(TR_HTML)
           && Number(/\/static\/js\/tracks\.js\?v=(\d+)/.exec(TR_HTML)[1]) >= 16,
        'tracks.js ist mit erhoehtem Cache-Buster eingebunden');
    pruefe(/<input type="file" id="st-ref-input"/.test(TR_HTML), 'das Eingabefeld fuer Referenzen steht im Markup');
    const iCl = TR_HTML.indexOf('/static/js/chatlib.js?v='), iTr = TR_HTML.indexOf('/static/js/tracks.js?v=');
    pruefe(iCl > 0 && iTr > iCl, 'chatlib.js ist eingebunden, und zwar VOR tracks.js');
    const css = (/<style>([\s\S]*?)<\/style>/.exec(TR_HTML) || ['', ''])[1];
    const neu = css.slice(css.indexOf('Fragefeld und Referenzen'), css.indexOf('.st-job-art') + 80);
    pruefe(neu.length > 100 && !/#[0-9a-fA-F]{3,6}\b|rgb\(\s*\d/.test(neu),
        'die neuen Regeln benutzen nur Theme-Variablen (keine harten Farben)');
}

console.log('\n' + '='.repeat(62));
console.log('  ' + ok + ' OK, ' + fail + ' FAIL');
console.log('='.repeat(62));
process.exit(fail ? 1 : 0);
})();
