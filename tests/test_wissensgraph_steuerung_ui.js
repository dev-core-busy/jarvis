#!/usr/bin/env node
/**
 * Waechter: Wissensgraph – Aufbau und Pflege in Einstellungen → Wissen
 * (frontend/js/wissensgraph_steuerung.js, seit 2026-11-01 statt auf /wissensgraph).
 *
 * Die ECHTE settings.html, die ECHTE i18n.js und sitzung.js, das ECHTE Modul;
 * nur fetch ist eine Attrappe mit kleinem Server-Zustand (was die Seite schreibt,
 * liest sie zurueck – gemessen wird die Wirkung, nicht der Aufruf).
 *
 *  1. Abschnitt im Reiter „Wissen“, Skript eingebunden, app.js registriert ihn
 *  2. abgefragt wird NUR bei offenem Reiter UND aufgeklapptem Abschnitt
 *  3. Status: Kennzahlen, Kreis genau bei „arbeitet“ (auch im Nachlauf), eigene
 *     Zeile fuer Widersprueche/Wiki, Pause-Hinweis, Kreis beim ersten Abruf
 *  4. Schalter: sendet nur das Feld, abgelehnt springt zurueck
 *  4b. Modell-Last: Felder zeigen den Stand, Tippen bleibt stehen, Grenzen greifen
 *  5. Aufbau: Umfang/Gruppe, Kreis beim Einreihen, gesperrt wenn aus
 *  6. i18n DE/EN, Stilregeln vorhanden, keine Farbliterale
 *
 *     node tests/test_wissensgraph_steuerung_ui.js
 */
const fs = require('fs');
const path = require('path');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  ✓ ' + t); } else { fail++; console.log('  ✗ ' + t + (d !== undefined ? '  → ' + d : '')); }
};
const abschnitt = (t) => console.log('\n' + t);
const ROOT = path.resolve(__dirname, '..');
const lies = (p) => fs.readFileSync(path.join(ROOT, p), 'utf8');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();
const sitzungLaden = require('./lib/sitzung_laden');
const warte = (ms) => new Promise(r => setTimeout(r, ms));

const HTML = lies('frontend/settings.html');
const JS = lies('frontend/js/wissensgraph_steuerung.js');
const APP = lies('frontend/js/app.js');
const STYLE = lies('frontend/css/style.css');
const I18N = lies('frontend/js/i18n.js');

const wachhund = setTimeout(() => { console.log('ABBRUCH: Lauf haengt (Wachhund 40 s)'); process.exit(2); }, 40000);

function baue() {
    const vc = new VirtualConsole();
    const fehler = [];
    vc.on('jsdomError', (er) => { const m = String(er && er.message || er); if (!/navigation|getContext/.test(m)) { fehler.push(m); } });
    const dom = new JSDOM(HTML, { url: 'https://localhost/settings', runScripts: 'outside-only', virtualConsole: vc });
    const w = dom.window;
    sitzungLaden(w);
    w.localStorage.setItem('jarvis_token', 'jarvis:1:deadbeef');
    const server = { aufrufe: [], einst: { aktiv: true, expansion: false, widersprueche: true, wiki_sammellauf: true,
                             rate_min_abstand_s: 2, rate_max_pro_stunde: 800 },
                     zustand: {}, einstFehler: false, pause: false };
    const antwort = (status, body) => Promise.resolve({ ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) });
    w.fetch = function (url, o) {
        const u = String(url).split('?')[0];
        const m = (o && o.method) || 'GET';
        const body = o && o.body ? JSON.parse(o.body) : null;
        server.aufrufe.push({ u, m, body });
        if (u === '/api/wissensgraph/status') {
            return antwort(200, Object.assign({ aktiv: server.einst.aktiv, laeuft: false, aktuell: '', warteschlange: 0,
                erledigt: 3, fehler: 1, zaehler: { aufrufe: 9, token_ein: 90, token_aus: 30 },
                graph: { quellen: 2, entitaeten: 14, kanten: 22, widersprueche: 1 },
                letzte_fehler: [{ pfad: 'data/rag/x/a.md', grund: 'kaputt' }], modell: 'Testmodell',
                einstellungen: Object.assign({}, server.einst),
                nachlauf: { pause: server.pause, widersprueche_offen: 3, wiki_offen: 5, wiki_seiten: 2 } }, server.zustand));
        }
        if (u === '/api/wissensgraph/einstellungen' && m === 'POST') {
            if (server.einstFehler) { return antwort(400, { detail: 'abgelehnt' }); }
            Object.assign(server.einst, body);
            return antwort(200, { ok: true, einstellungen: server.einst });
        }
        if (u === '/api/wissensgraph/neuaufbau') { return antwort(200, { eingereiht: 4, unveraendert: 1, bereinigt: 0 }); }
        if (u === '/api/wissensgraph/abbrechen') { return antwort(200, { ok: true, verworfen: 2 }); }
        if (u === '/api/knowledge/groups') {
            return antwort(200, { ok: true, groups: [{ id: 'g1', name: 'Gruppe 1' }, { id: 'ungrouped', name: 'ohne' }] });
        }
        return antwort(200, { ok: true });
    };
    global.fetch = w.fetch;
    w.eval(lies('frontend/js/i18n.js'));
    w.eval(JS);
    return { w, d: w.document, server, fehler };
}

async function main() {
    abschnitt('1. Einbau');
    pruefe(/\/static\/js\/wissensgraph_steuerung\.js\?v=\d+/.test(HTML), 'settings.html bindet das Modul ein');
    const tabStart = HTML.indexOf('id="settings-tab-knowledge"');
    const tabEnde = HTML.indexOf('<!-- Google-Tab entfernt', tabStart);
    const abs = HTML.indexOf('id="kb-sect-wg-hdr"');
    pruefe(tabStart > 0 && abs > tabStart && abs < tabEnde, 'Abschnitt steht im Reiter „Wissen“', [tabStart, abs, tabEnde].join(','));
    pruefe(/hdr: 'kb-sect-wg-hdr',\s*body: 'kb-sect-wg-body',\s*tog: 'kb-sect-wg-tog'/.test(APP), 'app.js macht ihn klappbar (wie die Nachbarn)');
    pruefe(/target === 'knowledge'[\s\S]{0,600}WissensgraphSteuerung\.onShow\(\)/.test(APP), 'app.js ruft onShow beim Oeffnen des Reiters');
    pruefe(/kb-sect-wg-body[^>]*style="display:none;"/.test(HTML), 'Abschnitt ist zugeklappt vorbelegt');

    const s = baue();
    const { w, d, server } = s;
    const W = w.WissensgraphSteuerung;
    if (!W || !d.getElementById('kb-sect-wg-body')) { console.log('ABBRUCH – Modul oder Markup fehlt'); process.exit(2); }

    abschnitt('2. Abfrage nur, wenn sichtbar');
    const tab = d.getElementById('settings-tab-knowledge'), body = d.getElementById('kb-sect-wg-body');
    await W.onShow();
    pruefe(!server.aufrufe.some(x => x.u === '/api/wissensgraph/status'), 'Reiter zu: kein Statusabruf');
    tab.style.display = '';
    await W.onShow();
    pruefe(!server.aufrufe.some(x => x.u === '/api/wissensgraph/status'), 'Reiter offen, Abschnitt zu: kein Statusabruf');
    body.style.display = '';
    d.getElementById('kb-sect-wg-hdr').dispatchEvent(new w.MouseEvent('click', { bubbles: true }));
    const st0 = d.getElementById('wg-status');
    await warte(5);
    pruefe(server.aufrufe.some(x => x.u === '/api/wissensgraph/status'), 'Aufklappen holt den Status (naechster Takt)');
    await warte(40);

    abschnitt('3. Status');
    const txt = () => d.getElementById('wg-status').textContent;
    pruefe(/14 Begriffe/.test(txt()) && /1 gefunden · 3 Begriffe offen/.test(txt()) && /2 vorhanden · 5 offen/.test(txt()),
           'Kennzahlen, Widersprueche, Wiki-Seiten', txt().slice(0, 300));
    pruefe(/data\/rag\/x\/a\.md: kaputt/.test(txt()), 'letzte Fehler mit Pfad');
    pruefe(d.querySelectorAll('#wg-status dl.kbwg-st').length === 1, 'Statusliste traegt die Stilklasse');
    const zustandDd = () => { const dts = Array.from(d.querySelectorAll('#wg-status dt'));
                              const i = dts.findIndex(x => x.textContent === 'Zustand');
                              return i >= 0 ? d.querySelectorAll('#wg-status dd')[i] : null; };
    pruefe(W.arbeitetGerade({ aktiv: true, laeuft: true }) === true
           && W.arbeitetGerade({ aktiv: true, laeuft: false, aktuell: 'wiki:e:a1' }) === true
           && W.arbeitetGerade({ aktiv: true, laeuft: false, aktuell: '' }) === false
           && W.arbeitetGerade({ aktiv: false, laeuft: true }) === false,
           'arbeitet = an UND (Warteschlange laeuft ODER ein Begriff/Dokument wird bearbeitet)');
    pruefe(!!zustandDd() && /an – wartet/.test(zustandDd().textContent) && !d.querySelector('#wg-status .jv-pkg-spin'),
           'wartet: kein Kreis', zustandDd() && zustandDd().textContent);
    // Der Kreis steht an der Zeile, die ARBEITET (Wunsch des Betreibers 2026-11-01).
    const zeileMitKreis = () => { const dds = Array.from(d.querySelectorAll('#wg-status dd'));
                                  const i = dds.findIndex(x => x.querySelector('.jv-pkg-spin'));
                                  return i >= 0 ? d.querySelectorAll('#wg-status dt')[i].textContent : null; };
    server.zustand = { laeuft: false, aktuell: 'widerspruch:e:sap' };
    await W.statusHolen();
    pruefe(!!zustandDd() && /an – arbeitet/.test(zustandDd().textContent), 'Nachlauf arbeitet: „an – arbeitet“');
    pruefe(zeileMitKreis() === 'Widersprüche', 'Widerspruchspruefung: Kreis bei „Widersprüche“', zeileMitKreis());
    pruefe(d.querySelectorAll('#wg-status dd .jv-pkg-spin').length === 1, 'genau eine Zeile traegt den Kreis');
    server.zustand = { laeuft: false, aktuell: 'wiki:e:sap' };
    await W.statusHolen();
    pruefe(zeileMitKreis() === 'Wiki-Seiten', 'Wiki-Seite: Kreis bei „Wiki-Seiten“', zeileMitKreis());
    server.zustand = { laeuft: true, aktuell: 'data/rag/x/a.md', warteschlange: 7 };
    await W.statusHolen();
    pruefe(zeileMitKreis() === 'Warteschlange', 'Dokument-Extraktion: Kreis bei „Warteschlange“', zeileMitKreis());
    server.zustand = { laeuft: false, aktuell: 'widerspruch:e:sap' };
    await W.statusHolen();
    pruefe(/Widerspruchsprüfung zu „sap“/.test(txt()), '„Gerade“ nennt den Begriff lesbar', txt().slice(-200));
    server.zustand = { zaehler: { aufrufe: 5, token_ein: 50, token_aus: 20, pflege_aufrufe: 12, pflege_token_ein: 345, pflege_token_aus: 67 } };
    await W.statusHolen();
    pruefe(/Widersprüche und Wiki · Modellaufrufe/.test(txt()) && /12 · 345 \/ 67/.test(txt()),
           'eigene Zeile fuer die Modellaufrufe von Widerspruechen und Wiki', txt().slice(0, 300));
    server.zustand = {};
    server.pause = true;
    await W.statusHolen();
    pruefe(/angehalten/.test(txt()), 'angehaltener Nachlauf wird genannt');
    server.pause = false;
    d.getElementById('wg-status').textContent = '';
    const sh = W.statusHolen();
    pruefe(!!d.querySelector('#wg-status .jv-pkg-spin'), 'leerer Status: Kreis waehrend des ersten Abrufs');
    await sh;
    pruefe(!d.querySelector('#wg-status .jv-pkg-spin'), 'nach dem Abruf: Kreis weg');
    pruefe(st0 === d.getElementById('wg-status'), 'Positivkontrolle: dasselbe Statuselement');

    abschnitt('4. Schalter');
    const hk = (k) => d.querySelector('[data-wg-einstellung="' + k + '"]');
    pruefe(hk('aktiv').checked === true && hk('expansion').checked === false && hk('widersprueche').checked === true,
           'Schalter zeigen die Einstellungen');
    hk('expansion').checked = true;
    hk('expansion').dispatchEvent(new w.Event('change'));
    await warte(40);
    const es = server.aufrufe.filter(x => x.u === '/api/wissensgraph/einstellungen').pop();
    pruefe(es && JSON.stringify(es.body) === '{"expansion":true}', 'Umschalten sendet NUR dieses Feld', JSON.stringify(es && es.body));
    pruefe(server.einst.expansion === true && /Gespeichert/.test(d.getElementById('wg-einst-meldung').textContent), '… der Server hat es, Meldung steht da');
    server.einstFehler = true;
    hk('wiki_sammellauf').checked = false;
    hk('wiki_sammellauf').dispatchEvent(new w.Event('change'));
    await warte(40);
    const em = d.getElementById('wg-einst-meldung');
    pruefe(hk('wiki_sammellauf').checked === true && /abgelehnt/.test(em.textContent) && em.classList.contains('is-err'),
           'abgelehnt: Schalter springt zurueck, Begruendung als Fehler', em.className + ' ' + em.textContent);
    server.einstFehler = false;

    abschnitt('4b. Modell-Last');
    const zf = (k) => d.querySelector('[data-wg-zahl="' + k + '"]');
    const tippen = (h, v) => { h.value = v; h.dispatchEvent(new w.Event('input')); };
    const fertig = async (h) => { h.dispatchEvent(new w.Event('change')); await warte(40); };
    const posts = () => server.aufrufe.filter(x => x.u === '/api/wissensgraph/einstellungen').length;
    await W.statusHolen();
    const ab = zf('rate_min_abstand_s'), mx = zf('rate_max_pro_stunde');
    pruefe(!!ab && !!mx && ab.value === '2' && mx.value === '800', 'Felder zeigen den Stand des Servers', ab && ab.value);
    tippen(ab, '7');
    await W.statusHolen();
    pruefe(ab.value === '7', 'Statusabfrage ueberschreibt NICHT, was gerade getippt wird', ab.value);
    pruefe(mx.value === '800', 'Positivkontrolle: das andere Feld folgt weiter dem Server', mx.value);
    await fertig(ab);
    const za = server.aufrufe.filter(x => x.u === '/api/wissensgraph/einstellungen').pop();
    pruefe(za && JSON.stringify(za.body) === '{"rate_min_abstand_s":7}', 'Aendern sendet NUR dieses Feld, als Zahl', JSON.stringify(za && za.body));
    pruefe(server.einst.rate_min_abstand_s === 7 && /Gespeichert/.test(d.getElementById('wg-einst-meldung').textContent), '… der Server hat es, Meldung steht da');
    pruefe(!ab.hasAttribute('data-wg-tippt') && !ab.disabled, 'Feld ist danach wieder frei');
    server.einst.rate_min_abstand_s = 3;
    await W.statusHolen();
    pruefe(ab.value === '3', 'nach dem Speichern folgt das Feld wieder dem Server', ab.value);
    let vor = posts();
    await fertig(ab);
    pruefe(posts() === vor, 'unveraenderter Wert: kein Speichern');
    for (const [h, v, was] of [[ab, '601', 'ueber dem Hoechstwert'], [ab, '-1', 'negativ'], [ab, '', 'leer'], [mx, '10.5', 'Kommazahl bei ganzer Zahl']]) {
        const soll = h.value;
        vor = posts();
        tippen(h, v);
        await fertig(h);
        const m = d.getElementById('wg-einst-meldung');
        pruefe(posts() === vor && h.value === soll && m.classList.contains('is-err') && /Bitte eine Zahl von 0 bis/.test(m.textContent),
               'ungueltig (' + was + '): nichts gesendet, Feld springt zurueck, Fehler steht da', [posts() - vor, h.value, m.textContent].join(' | '));
    }
    vor = posts();
    tippen(ab, '600');
    await fertig(ab);
    pruefe(posts() === vor + 1 && server.einst.rate_min_abstand_s === 600, 'Grenzwert selbst ist erlaubt', server.einst.rate_min_abstand_s);
    vor = posts();
    tippen(mx, '0');
    await fertig(mx);
    pruefe(posts() === vor + 1 && server.einst.rate_max_pro_stunde === 0 && mx.value === '0', '0 = keine Obergrenze wird gesendet und angezeigt', mx.value);
    server.einstFehler = true;
    tippen(ab, '5');
    await fertig(ab);
    pruefe(ab.value === '600' && /abgelehnt/.test(d.getElementById('wg-einst-meldung').textContent),
           'vom Server abgelehnt: Feld springt zurueck, Begruendung steht da', ab.value);
    server.einstFehler = false;
    pruefe(/\.kbwg-zahl input\s*\{/.test(STYLE), 'Feldbreite in style.css');

    abschnitt('5. Aufbau');
    const umf = d.getElementById('wg-umfang'), gr = d.getElementById('wg-umfang-gruppe'), ord = d.getElementById('wg-umfang-ordner');
    pruefe(gr.style.display === 'none' && ord.style.display === 'none', 'Gruppe/Ordner zunaechst verborgen');
    pruefe(Array.from(gr.options).map(o => o.value).join() === 'g1', 'Gruppenliste ohne „ungrouped“', Array.from(gr.options).map(o => o.value).join());
    umf.value = 'gruppe';
    umf.dispatchEvent(new w.Event('change'));
    pruefe(gr.style.display === '' && ord.style.display === 'none', 'Umfang „Gruppe“ zeigt die Gruppenauswahl');
    d.getElementById('wg-start').click();
    pruefe(!!d.querySelector('#wg-aufbau-meldung .jv-pkg-spin'), '„Wird eingereiht“ mit Kreis', d.getElementById('wg-aufbau-meldung').innerHTML);
    await warte(40);
    const nb = server.aufrufe.filter(x => x.u === '/api/wissensgraph/neuaufbau').pop();
    pruefe(nb && nb.body.umfang === 'gruppe' && JSON.stringify(nb.body.groups) === '["g1"]', 'Aufbau sendet Umfang und Gruppe', JSON.stringify(nb && nb.body));
    pruefe(!d.querySelector('#wg-aufbau-meldung .jv-pkg-spin') && /4 Dokumente eingereiht/.test(d.getElementById('wg-aufbau-meldung').textContent),
           'Antwort: Kreis weg, Zahlen stehen da');
    d.getElementById('wg-abbrechen').click();
    await warte(40);
    pruefe(/2 Einträge/.test(d.getElementById('wg-aufbau-meldung').textContent), 'Abbrechen meldet die verworfenen Eintraege');
    server.einst.aktiv = false;
    await W.statusHolen();
    const sb = d.getElementById('wg-start');
    pruefe(sb.disabled && /ausgeschaltet/.test(sb.title), 'Graph aus: Aufbau gesperrt MIT Grund', sb.title);
    pruefe(s.fehler.length === 0, 'keine Skriptfehler', s.fehler.slice(0, 3).join(' | '));

    abschnitt('6. i18n, Stil, Projektregeln');
    const trenner = I18N.indexOf('\n    en: {');
    const de = I18N.slice(0, trenner), en = I18N.slice(trenner);
    const absHtml = HTML.slice(HTML.indexOf('<!-- Wissensgraph: Aufbau und Pflege'), tabEnde);
    const schl = new Set();
    (absHtml.match(/data-i18n(?:-html|-aria)?="([^"]+)"/g) || []).forEach(m => schl.add(m.replace(/^[^"]+"|"$/g, '')));
    (JS.match(/\bt\('(wissensgraph\.[a-z_]+)'/g) || []).forEach(m => schl.add(m.slice(3, -1)));
    pruefe(trenner > 0 && schl.size >= 25, 'Positivkontrolle: Schluessel gesammelt', schl.size);
    const fehlt = [...schl].filter(x => de.indexOf("'" + x + "'") < 0 || en.indexOf("'" + x + "'") < 0);
    pruefe(!fehlt.length, 'alle Schluessel in DE und EN', fehlt.join(', '));
    const klassen = new Set();
    (absHtml.match(/class="([^"]+)"/g) || []).forEach(m => m.slice(7, -1).split(/\s+/).forEach(k => /^kbwg-/.test(k) && klassen.add(k)));
    (JS.match(/'kbwg-[a-z-]+/g) || []).forEach(k => klassen.add(k.slice(1)));
    pruefe(klassen.size >= 7, 'Positivkontrolle: kbwg-Klassen gesammelt', [...klassen].join(','));
    const ohne = [...klassen].filter(k => !new RegExp('(^|\\n|\\s)\\.' + k + '[\\s{.,:]').test(STYLE));
    pruefe(!ohne.length, 'jede kbwg-Klasse hat eine Regel in style.css (Seite laedt style.css)', ohne.join(','));
    pruefe(/href="\/static\/css\/style\.css\?v=\d+"/.test(HTML), 'Positivkontrolle: settings.html laedt style.css');
    pruefe(/body\.light \.kbwg-meldung\.is-err\s*\{\s*color:\s*color-mix\(in srgb, var\(--danger\) 78%, #000\)/.test(STYLE),
           'Fehlermeldung im hellen Thema abgedunkelt (--danger allein unter 4,5:1)');
    pruefe(!/#[0-9a-fA-F]{3,8}\b|rgba?\(/.test(JS.replace(/\/\*[\s\S]*?\*\//g, '').replace(/\/\/.*$/gm, '')), 'Modul ohne Farbliterale');
    pruefe(!/innerHTML/.test(JS), 'Modul setzt kein innerHTML');

    clearTimeout(wachhund);
    w.close();
    console.log('\nErgebnis: ' + ok + ' ok, ' + fail + ' fehlgeschlagen');
    process.exit(fail ? 1 : 0);
}

main().catch(function (er) { console.log('ABBRUCH: ' + (er && er.stack || er)); process.exit(2); });
