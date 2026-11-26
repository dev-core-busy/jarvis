/* Waechter: Container "Verbindungen nach aussen (Ausgangsfilter)" – GEKLICKT, nicht gelesen.
 *
 * Laedt den ECHTEN Ausschnitt aus settings.html (Container #ausgangsfilter),
 * die ECHTEN icons.js, i18n.js, fernzugang.js (Code-Abfrage) und
 * ausgangsfilter.js in jsdom. Der Server ist eine fetch-Attrappe mit der
 * Antwortform von backend/broker/ausgang.py::status bzw. main.py::broker_ausgang.
 *
 * Geprueft:
 *   0. Einbindung: Skript-Tag in settings.html, onShow-Aufruf in app.js,
 *      jeder Text-Schluessel (af.*) in DE und EN vorhanden.
 *   1. Text <-> Tabelle: Kopf, Modus, Notizen (Kommentar darueber oder am
 *      Zeilenende) und unbekannte Zeilen ueberstehen Zerlegen + Zusammensetzen.
 *   2. Anzeige: Statuszeile als TEXT je Zustand, eine Zeile je Freigabe mit
 *      den Werten, Muelleimer-Symbol, Entfernen-Knopf nur bei geladenem Filter.
 *   3. Pruefen: POST mit dem BEARBEITETEN Text, ohne Code-Abfrage.
 *   4. Speichern: Rueckfrage + Code; abgelehnt/abgebrochen -> kein Aufruf;
 *      sonst POST mit Code und danach neu geladen. Sperrmodus fragt eigens.
 *   5. Leeres Feld: kein Aufruf, Meldung mit Zeilennummer AM Knopf.
 *   6. Verbindungen ohne Freigabe: "Freigeben" uebernimmt die Zeile in die
 *      Tabelle (Kleinschrift, icmp ohne Port), Kernel-Protokolle ohne Knopf.
 *   7. Loeschen entfernt genau die Zeile und behaelt die Eingaben der anderen;
 *      ein Sprachwechsel behaelt sie ebenfalls.
 *   8. Laufender Vorgang mit drehendem Kreis; abgewiesener Code im Klartext.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();
const fertig = require('./lib/bilanz')({ stumm: true });
const { ausschnitt } = require('./lib/seite_ausschnitt');

const FE = path.resolve(__dirname, '..', 'frontend');
const MODUL = process.env.JARVIS_AUSGANGSFILTER_PRUEFLING || path.join(FE, 'js', 'ausgangsfilter.js');
let ok = 0, fail = 0;
function check(text, bedingung, zusatz) {
    if (bedingung) { ok++; console.log('  OK   ' + text); }
    else { fail++; console.log('  FAIL ' + text + (zusatz !== undefined ? '  → ' + zusatz : '')); }
}
function lies(rel) { return fs.readFileSync(path.join(FE, rel), 'utf-8'); }
const warte = (ms) => new Promise(r => setTimeout(r, ms || 0));

const KONF = '# Kopfzeile\n# zweite\n\nMODUS=protokoll\n'
    + '# DNS intern\nerlaube alle udp 53 192.0.2.53\n'
    + 'erlaube root tcp 22 *   # Git-Update\n'
    + 'erlaube jarvis tcp - 192.0.2.0/24\n';

function stand(teil) {
    return Object.assign({
        ok: true, konfiguration: true, text: KONF, gueltig: true, fehler: '', unit: 'enabled',
        stunden: 24, protokoll_lesbar: true, skript: true, geladen: true, policy: 'accept', modus: 'protokoll',
        freigaben: [{}, {}, {}],
        treffer: [
            { art: 'frei', uid: '42', benutzer: '_apt', proto: 'TCP', ziel: '198.51.100.7', port: '80', anzahl: 5, zuletzt: 1795600000 },
            { art: 'drop', uid: '', benutzer: '', proto: '2', ziel: '224.0.0.22', port: '', anzahl: 2, zuletzt: 1795600000 },
            { art: 'frei', uid: '110', benutzer: 'colord', proto: 'ICMP', ziel: '192.0.2.9', port: '', anzahl: 1, zuletzt: 1795600000 },
        ]
    }, teil || {});
}

const AUS = ausschnitt(lies('settings.html'), ['ausgangsfilter'], {});

async function seite(status, antworten) {
    const dom = new JSDOM(AUS.html, { url: 'https://localhost/settings', runScripts: 'outside-only' });
    const w = dom.window;
    w.matchMedia = w.matchMedia || function () {
        return { matches: false, addListener() {}, removeListener() {}, addEventListener() {}, removeEventListener() {} };
    };
    w.eval(lies('js/icons.js'));
    w.eval(lies('js/i18n.js'));
    await warte(5);
    w.JarvisSitzung = { token: () => 'TOKEN' };
    const aufrufe = [];
    let aktuell = status;
    const attrappe = function (url, opt) {
        const pfad = String(url).split('?')[0];
        let body = null;
        try { body = opt && opt.body ? JSON.parse(opt.body) : null; } catch (e) { /* bleibt null */ }
        aufrufe.push({ pfad, methode: (opt && opt.method) || 'GET', body });
        const antwort = pfad === '/api/broker/ausgang/status' ? aktuell
            : ((antworten && antworten[pfad]) || { ok: true, regeln: 3 });
        return Promise.resolve({ ok: true, json: () => Promise.resolve(antwort) });
    };
    w.fetch = attrappe;
    global.fetch = attrappe;
    w.__confirm = true; w.__prompt = '123456'; w.__fragen = [];
    w.confirm = (t) => { w.__fragen.push(t); return w.__confirm; };
    w.prompt = () => w.__prompt;
    w.alert = () => {};
    w.eval(lies('js/fernzugang.js'));
    w.eval(fs.readFileSync(MODUL, 'utf-8'));
    await w.Ausgangsfilter.onShow();
    await warte(5);
    return { w, aufrufe, setze: (s) => { aktuell = s; } };
}
function text(w, id) { const el = w.document.getElementById(id); return el ? el.textContent.replace(/\s+/g, ' ').trim() : ''; }
function klick(w, id) { w.document.getElementById(id).click(); }
function zeilen(w) { return Array.from(w.document.querySelectorAll('#af-freigaben tr[data-af-zeile]')); }
function feld(tr, f) { return tr.querySelector('[data-f="' + f + '"]'); }
function posts(s) { return s.aufrufe.filter(a => a.methode === 'POST'); }

(async function () {
    console.log('── 0. Einbindung');
    const html = lies('settings.html');
    if (!AUS.fehlend || AUS.fehlend.length || html.indexOf('id="ausgangsfilter"') < 0) {
        console.log('ABBRUCH: Container #ausgangsfilter fehlt in settings.html'); process.exit(2);
    }
    check('Skript in settings.html eingebunden', /\/static\/js\/ausgangsfilter\.js\?v=\d+/.test(html));
    check('app.js ruft onShow im Reiter', /window\.Ausgangsfilter\.onShow\(\)/.test(lies('js/app.js')));
    const modulText = fs.readFileSync(MODUL, 'utf-8');
    const schluessel = new Set();
    for (const m of modulText.matchAll(/T\('(af\.[a-z_]+)'/g)) schluessel.add(m[1]);
    for (const m of html.matchAll(/data-i18n(?:-html)?="(af\.[a-z_]+)"/g)) schluessel.add(m[1]);
    let s = await seite(stand());
    const i18nText = lies('js/i18n.js');
    const fehltText = [...schluessel].filter(k => (i18nText.match(new RegExp("'" + k.replace('.', '\\.') + "'\\s*:", 'g')) || []).length < 2);
    check('Positivkontrolle: Schluessel gesammelt', schluessel.size > 30, schluessel.size);
    check('jeder af.*-Schluessel steht in DE und EN', fehltText.length === 0, fehltText.join(', '));

    console.log('\n── 1. Text <-> Tabelle');
    const R = s.w.Ausgangsfilter._rechnen;
    const z = R.zerlegen(KONF);
    check('Kopf behalten', z.kopf.join('|') === '# Kopfzeile|# zweite', JSON.stringify(z.kopf));
    check('drei Freigaben, Modus protokoll', z.zeilen.length === 3 && z.modus === 'protokoll');
    check('Notiz aus Kommentar darueber', z.zeilen[0] && z.zeilen[0].notiz === 'DNS intern', JSON.stringify(z.zeilen[0]));
    check('Notiz aus Kommentar am Zeilenende', z.zeilen[1] && z.zeilen[1].notiz === 'Git-Update', JSON.stringify(z.zeilen[1]));
    const wieder = R.zusammensetzen(z);
    const z2 = R.zerlegen(wieder);
    check('Zusammensetzen und erneut Zerlegen ergibt denselben Stand', JSON.stringify(z2) === JSON.stringify(z), wieder);
    check('Ergebnis endet mit Zeilenumbruch und nennt MODUS', /\nMODUS=protokoll\n/.test(wieder) && wieder.endsWith('\n'), wieder);
    const roh = R.zerlegen('MODUS=sperre\nverbiete alle tcp 1 *\n');
    check('unbekannte Zeile bleibt woertlich erhalten', roh.zeilen[0] && roh.zeilen[0].roh === 'verbiete alle tcp 1 *'
          && R.zusammensetzen(roh).indexOf('verbiete alle tcp 1 *') >= 0 && roh.modus === 'sperre');
    check('Vorschlag: TCP -> tcp mit Port', JSON.stringify(R.vorschlag({ proto: 'TCP', port: '80', ziel: '198.51.100.7', benutzer: '_apt' }))
          === JSON.stringify({ benutzer: '_apt', proto: 'tcp', ports: '80', ziele: '198.51.100.7', notiz: '' }));
    check('Vorschlag: ICMP ohne Port', (R.vorschlag({ proto: 'ICMP', ziel: '192.0.2.9', uid: '110' }) || {}).ports === '-');
    check('Vorschlag: ohne Benutzer -> alle', (R.vorschlag({ proto: 'UDP', port: '53', ziel: '192.0.2.53' }) || {}).benutzer === 'alle');
    check('Vorschlag: Protokoll 2 (IGMP) -> keiner', R.vorschlag({ proto: '2', ziel: '224.0.0.22' }) === null);

    console.log('\n── 2. Anzeige');
    const st = text(s.w, 'af-status');
    check('Status: Protokollmodus, Anzahl, Start', /Protokollmodus/.test(st) && /3 Freigaben/.test(st) && /Systemstart geladen/.test(st), st);
    const zs = zeilen(s.w);
    check('drei Tabellenzeilen', zs.length === 3, zs.length);
    check('Werte in den Feldern', zs.length === 3 && feld(zs[1], 'benutzer').value === 'root' && feld(zs[1], 'ports').value === '22'
          && feld(zs[2], 'ziele').value === '192.0.2.0/24' && feld(zs[2], 'ports').value === '-');
    check('Notiz im Feld', zs.length && feld(zs[0], 'notiz').value === 'DNS intern');
    check('Loeschknopf mit Muelleimer', !!s.w.document.querySelector('#af-freigaben [data-af-weg] .jv-ico-trash, #af-freigaben [data-af-weg] svg'));
    check('Modus-Auswahl steht auf protokoll', s.w.document.getElementById('af-modus').value === 'protokoll');
    check('Entfernen sichtbar, wenn geladen', s.w.document.getElementById('af-entfernen').style.display !== 'none');
    s.w.close();
    for (const [teil, muster, name] of [
        [{ konfiguration: false, text: '', geladen: false }, /Nicht eingerichtet/, 'nicht eingerichtet'],
        [{ geladen: false }, /nicht geladen/, 'gespeichert, nicht geladen'],
        [{ policy: 'drop' }, /Sperrmodus/, 'Sperrmodus'],
        [{ geladen: null }, /ließ sich nicht prüfen/, 'unbekannt'],
        [{ unit: 'disabled' }, /NICHT geladen/, 'nicht beim Start'],
        [{ gueltig: false, fehler: 'Zeile 4: Port ungueltig' }, /fehlerhaft:.*Zeile 4/, 'fehlerhafte Datei'],
        [{ skript: false }, /Update einspielen/, 'ohne Skript'],
    ]) {
        s = await seite(stand(teil));
        check('Status ' + name, muster.test(text(s.w, 'af-status')), text(s.w, 'af-status'));
        if (name === 'gespeichert, nicht geladen') check('Entfernen verborgen, wenn nicht geladen', s.w.document.getElementById('af-entfernen').style.display === 'none');
        s.w.close();
    }
    s = await seite(null);
    s.setze({ ok: false });
    await s.w.Ausgangsfilter.laden(); await warte(5);
    check('Status nicht abfragbar: Klartext', /ließ sich nicht abfragen/.test(text(s.w, 'af-status')), text(s.w, 'af-status'));
    s.w.close();

    console.log('\n── 3. Pruefen');
    s = await seite(stand());
    feld(zeilen(s.w)[1], 'ports').value = '22,443';
    const vorher = s.w.__fragen.length;
    klick(s.w, 'af-pruefen'); await warte(10);
    let p = posts(s);
    check('ein POST pruefen', p.length === 1 && p[0].body.aktion === 'pruefen', JSON.stringify(p));
    check('mit dem bearbeiteten Text', p.length && /erlaube root tcp 22,443 \*/.test(p[0].body.text), p.length && p[0].body.text);
    check('Notiz bleibt im Text', p.length && /# Git-Update\nerlaube root/.test(p[0].body.text));
    check('ohne Rueckfrage und ohne Code', s.w.__fragen.length === vorher && p.length && p[0].body.nachweis === undefined);
    check('Ergebnis am Knopf: gueltig, nichts gespeichert', /gültig \(3 Regeln\).*noch nichts/.test(text(s.w, 'af-result')), text(s.w, 'af-result'));
    check('Bearbeitung bleibt nach Pruefen stehen', feld(zeilen(s.w)[1], 'ports').value === '22,443');
    s.w.close();

    console.log('\n── 4. Speichern');
    s = await seite(stand());
    s.w.__confirm = false;
    klick(s.w, 'af-speichern'); await warte(10);
    check('Rueckfrage abgelehnt: kein Aufruf', posts(s).length === 0);
    s.w.__confirm = true; s.w.__prompt = null;
    klick(s.w, 'af-speichern'); await warte(10);
    check('Code-Abfrage abgebrochen: kein Aufruf', posts(s).length === 0);
    s.w.__prompt = '12 34 56';
    const getVorher = s.aufrufe.filter(a => a.methode === 'GET').length;
    klick(s.w, 'af-speichern'); await warte(20);
    p = posts(s);
    check('POST speichern mit Code (nur Ziffern)', p.length === 1 && p[0].body.aktion === 'speichern' && p[0].body.nachweis === '123456', JSON.stringify(p));
    check('danach neu geladen', s.aufrufe.filter(a => a.methode === 'GET').length === getVorher + 1);
    check('Erfolg am Knopf', /Gespeichert und angewendet/.test(text(s.w, 'af-result')), text(s.w, 'af-result'));
    s.w.close();
    s = await seite(stand());
    s.w.document.getElementById('af-modus').value = 'sperre';
    klick(s.w, 'af-speichern'); await warte(20);
    p = posts(s);
    check('Sperrmodus: eigene Rueckfrage', /Sperrmodus/.test(s.w.__fragen[s.w.__fragen.length - 1] || ''), s.w.__fragen.join(' | '));
    check('Sperrmodus im Text', p.length === 1 && /\nMODUS=sperre\n/.test(p[0].body.text));
    s.w.close();
    s = await seite(stand(), { '/api/broker/ausgang': { ok: false, grund: 'nachweis_falsch' } });
    klick(s.w, 'af-speichern'); await warte(20);
    check('abgewiesener Code: Klartext am Knopf', /Freigabe-Code ist falsch/.test(text(s.w, 'af-result')), text(s.w, 'af-result'));
    s.w.close();
    s = await seite(stand(), { '/api/broker/ausgang': { ok: false, zurueck: true, meldung: 'nft: Fehler' } });
    klick(s.w, 'af-speichern'); await warte(20);
    check('Fehlschlag mit zurueck: sagt, dass die alten Freigaben gelten', /vorherigen Freigaben gelten weiter: nft: Fehler/.test(text(s.w, 'af-result')), text(s.w, 'af-result'));
    s.w.close();
    s = await seite(stand());
    klick(s.w, 'af-entfernen'); await warte(20);
    p = posts(s);
    check('Entfernen: Rueckfrage, Code, kein Text', p.length === 1 && p[0].body.aktion === 'entfernen' && p[0].body.nachweis === '123456'
          && p[0].body.text === undefined && /entfernen\?/.test(s.w.__fragen.join(' ')), JSON.stringify(p));
    s.w.close();

    console.log('\n── 5. Leeres Feld');
    s = await seite(stand());
    feld(zeilen(s.w)[2], 'ziele').value = '';
    klick(s.w, 'af-speichern'); await warte(10);
    check('kein Aufruf', posts(s).length === 0);
    check('Meldung mit Zeilennummer am Knopf', /Freigabe 3:/.test(text(s.w, 'af-result')), text(s.w, 'af-result'));
    s.w.close();

    console.log('\n── 6. Verbindungen ohne Freigabe');
    s = await seite(stand());
    const tr = Array.from(s.w.document.querySelectorAll('#af-treffer tbody tr'));
    check('drei Zeilen', tr.length === 3, tr.length);
    check('Wirkung als Text', tr.length === 3 && /nur aufgezeichnet/.test(tr[0].textContent) && /verworfen/.test(tr[1].textContent));
    check('ohne Benutzer: Kernel genannt', tr.length === 3 && /ohne Benutzer \(Kernel\)/.test(tr[1].textContent));
    check('IGMP ohne Freigeben-Knopf', tr.length === 3 && !tr[1].querySelector('[data-af-frei]'));
    // Ohne Knopf (z. B. Vorschlag kaputt) ein FAIL statt eines Wurfs
    const k0 = tr.length ? tr[0].querySelector('[data-af-frei]') : null;
    check('Freigeben-Knopf bei TCP vorhanden', !!k0);
    if (k0) k0.click(); await warte(5);
    let zs2 = zeilen(s.w);
    const neu = zs2[zs2.length - 1];
    check('Freigeben: neue Tabellenzeile mit den Werten', zs2.length === 4 && feld(neu, 'benutzer').value === '_apt'
          && feld(neu, 'proto').value === 'tcp' && feld(neu, 'ports').value === '80' && feld(neu, 'ziele').value === '198.51.100.7');
    const k0b = s.w.document.querySelector('#af-treffer [data-af-frei="0"]');
    check('Freigeben-Knopf danach gesperrt', !!k0b && k0b.disabled === true);
    const k2 = tr.length === 3 ? tr[2].querySelector('[data-af-frei]') : null;
    check('Freigeben-Knopf bei ICMP vorhanden', !!k2);
    if (k2) k2.click(); await warte(5);
    zs2 = zeilen(s.w);
    check('ICMP-Vorschlag: Port "-"', zs2.length === 5 && feld(zs2[4], 'proto').value === 'icmp' && feld(zs2[4], 'ports').value === '-');
    s.w.close();
    s = await seite(stand({ treffer: [] }));
    check('keine Treffer: Klartext mit Zeitraum', /letzten 24 Stunden gab es keine/.test(text(s.w, 'af-treffer')), text(s.w, 'af-treffer'));
    s.w.close();
    s = await seite(stand({ protokoll_lesbar: false, treffer: [] }));
    check('Protokoll nicht lesbar: eigener Text', /ließ sich nicht lesen/.test(text(s.w, 'af-treffer')), text(s.w, 'af-treffer'));
    s.w.close();

    console.log('\n── 7. Loeschen und Sprachwechsel');
    s = await seite(stand());
    feld(zeilen(s.w)[2], 'notiz').value = 'geaendert';
    zeilen(s.w)[1].querySelector('[data-af-weg]').click(); await warte(5);
    let zs3 = zeilen(s.w);
    check('genau eine Zeile weniger, die richtige', zs3.length === 2 && feld(zs3[0], 'benutzer').value === 'alle' && feld(zs3[1], 'benutzer').value === 'jarvis');
    check('Eingabe der anderen behalten', zs3.length === 2 && feld(zs3[1], 'notiz').value === 'geaendert');
    s.w._lang = 'en';
    s.w.dispatchEvent(new s.w.Event('jarvis-lang-changed')); await warte(5);
    zs3 = zeilen(s.w);
    check('Sprachwechsel behaelt die Bearbeitung', zs3.length === 2 && feld(zs3[1], 'notiz').value === 'geaendert');
    s.w.close();

    console.log('\n── 8. Laufender Vorgang');
    s = await seite(stand());
    let loese;
    const langsam = function (url, opt) {
        if (String(url).indexOf('/api/broker/ausgang/status') >= 0) return Promise.resolve({ ok: true, json: () => Promise.resolve(stand()) });
        return new Promise(r => { loese = () => r({ ok: true, json: () => Promise.resolve({ ok: true, regeln: 3 }) }); });
    };
    s.w.fetch = langsam; global.fetch = langsam;
    klick(s.w, 'af-pruefen'); await warte(5);
    check('drehender Kreis waehrend des Pruefens', !!s.w.document.querySelector('#af-result .jv-pkg-spin'));
    check('Knoepfe waehrenddessen gesperrt', s.w.document.getElementById('af-speichern').disabled === true);
    loese(); await warte(10);
    check('danach wieder frei', s.w.document.getElementById('af-speichern').disabled === false);
    s.w.close();

    fertig();
    console.log(`\nErgebnis: ${ok} OK, ${fail} FAIL`);
    process.exit(fail ? 1 : 0);
})();
