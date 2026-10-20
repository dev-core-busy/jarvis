/* Waechter: Abschnitt "Fernzugang (SSH)" im Sicherheits-Reiter – GEKLICKT, nicht gelesen.
 *
 * Laedt die ECHTE settings.html, die ECHTEN icons.js/i18n.js und fernzugang.js
 * in jsdom. Der Server ist eine fetch-Attrappe mit der ECHTEN Antwortform von
 * GET /api/broker/ssh/status (backend/broker/fernzugang.py::status) und der
 * POST-Endpunkte (backend/main.py::_broker_ssh_aktion).
 *
 * Geprueft:
 *   1. Status: Zeilen als TEXT (nicht nur Farbe), Konten mit Fingerabdruck,
 *      "kommt herein"/"kommt nicht herein", Abzeichen.
 *   2. Anleitung: klappt von selbst auf, wenn niemand herein kaeme; sonst zu.
 *   3. Knoepfe je Zustand: kein Test / Test laeuft (mit Restfrist) / aktiv.
 *   4. Test: Rueckfrage abgelehnt -> KEIN Aufruf; Code-Abfrage abgebrochen ->
 *      KEIN Aufruf; sonst POST mit root_modus aus der Auswahl und dem Code.
 *   5. Verwerfen: ohne Code-Abfrage.
 *   6. Abgewiesener Code: Klartext AM Knopf (kein alert, bleibt stehen).
 *   7. Netze: Wert aus dem Feld, Paketfilter fehlt -> Knopf aus + Hinweis.
 *   8. Schluessel hinterlegen/entfernen (seit 2026-10-20): Kontowahl, Vorschau
 *      mit Fingerabdruck (gegen das ECHTE ssh-keygen gerechnet), Rueckfrage
 *      und Code vor jedem POST, privater/mehrzeiliger Schluessel ohne POST,
 *      Muelleimer je Schluessel; keine Handbefehle mehr in der Anleitung.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();
const fertig = require('./lib/bilanz')({ stumm: true });

const FE = path.resolve(__dirname, '..', 'frontend');
let ok = 0, fail = 0;
function check(text, bedingung, zusatz) {
    if (bedingung) { ok++; console.log('  OK   ' + text); }
    else { fail++; console.log('  FAIL ' + text + (zusatz !== undefined ? '  → ' + zusatz : '')); }
}
function lies(rel) { return fs.readFileSync(path.join(FE, rel), 'utf-8'); }
const warte = (ms) => new Promise(r => setTimeout(r, ms || 0));

function stand(teil) {
    const basis = {
        ok: true,
        sshd: { passwordauthentication: 'yes', kbdinteractiveauthentication: 'no',
                permitrootlogin: 'without-password', permitemptypasswords: 'no', pubkeyauthentication: 'yes' },
        haertung: '', root_modus: 'nein', netze: '',
        konten: [
            { name: 'root', art: 'root', anzahl: 1, zaehlt: false,
              schluessel: [{ bits: 256, fingerabdruck: 'SHA256:rootFP', kommentar: 'root@x', typ: 'ED25519' }] },
            { name: 'admin', art: 'sudo', anzahl: 1, zaehlt: true,
              schluessel: [{ bits: 256, fingerabdruck: 'SHA256:adminFP', kommentar: 'admin@x', typ: 'ED25519' }] },
            { name: 'anna', art: 'sudo', anzahl: 0, zaehlt: false, schluessel: [] },
        ],
        zugang_moeglich: { nein: true, schluessel: true },
        test: { haertung: { laeuft: false, rest_s: null }, netze: { laeuft: false, rest_s: null } },
        firewall_eingerichtet: true, frist_s: 300,
    };
    return Object.assign(basis, teil || {});
}

async function seite(status, antworten) {
    const dom = new JSDOM(lies('settings.html'), { url: 'https://localhost/settings', runScripts: 'outside-only' });
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
    const fetchAttrappe = function (url, opt) {
        const pfad = String(url).split('?')[0];
        const methode = (opt && opt.method) || 'GET';
        let body = null;
        try { body = opt && opt.body ? JSON.parse(opt.body) : null; } catch (e) { /* bleibt null */ }
        aufrufe.push({ pfad, methode, body, auth: opt && opt.headers && opt.headers.Authorization });
        let antwort;
        if (pfad === '/api/broker/ssh/status') antwort = aktuell;
        else antwort = (antworten && antworten[pfad]) || { ok: true, meldung: 'erledigt' };
        return Promise.resolve({ ok: true, json: () => Promise.resolve(antwort) });
    };
    w.fetch = fetchAttrappe;
    global.fetch = fetchAttrappe;
    w.__confirm = true; w.__prompt = '123456'; w.__alerts = [];
    w.confirm = () => w.__confirm;
    w.prompt = () => w.__prompt;
    w.alert = (t) => { w.__alerts.push(t); };
    w.eval(lies('js/fernzugang.js'));
    await w.Fernzugang.onShow();
    await warte(5);
    return { dom, w, aufrufe, setzeStatus: (s) => { aktuell = s; } };
}

function sichtbar(w, id) { const el = w.document.getElementById(id); return !!el && el.style.display !== 'none'; }
function text(w, id) { const el = w.document.getElementById(id); return el ? el.textContent.replace(/\s+/g, ' ').trim() : ''; }

(async function () {
    // Positivkontrolle: Abschnitt im echten Markup
    const html = lies('settings.html');
    if (html.indexOf('id="sec-sect-ssh-body"') < 0 || html.indexOf('/static/js/fernzugang.js?v=') < 0) {
        console.log('ABBRUCH: Abschnitt oder Einbindung in settings.html fehlt');
        process.exit(2);
    }

    console.log('\n── 1. Status');
    let s = await seite(stand());
    const st = text(s.w, 'sec-ssh-status');
    check('Positivkontrolle: Status gerendert', st.length > 0, st);
    check('Kennwort-Anmeldung als TEXT "erlaubt"', /Anmeldung per Kennwort\s*erlaubt/.test(st), st);
    check('root "nur per Schlüssel"', /Anmeldung als root\s*nur per Schlüssel/.test(st), st);
    check('Netze "aus allen Netzen"', /aus allen Netzen/.test(st), st);
    const kt = text(s.w, 'sec-ssh-konten');
    check('Fingerabdruck admin sichtbar', kt.indexOf('SHA256:adminFP') >= 0, kt);
    check('anna: "kein Schlüssel hinterlegt"', /anna.*kein Schlüssel hinterlegt/.test(kt), kt);
    check('admin "kommt nach der Umstellung herein"', /admin.*kommt nach der Umstellung herein/.test(kt), kt);
    check('root: nur mit root-per-Schlüssel', /root.*nur wenn root per Schlüssel erlaubt ist/.test(kt), kt);
    check('Abzeichen "Kennwort erlaubt"', text(s.w, 'sec-ssh-badge') === 'Kennwort erlaubt', text(s.w, 'sec-ssh-badge'));
    check('Anleitung zu (es kaeme jemand herein)', s.w.document.getElementById('sec-ssh-anleitung').open === false);
    check('Aufruf mit Sitzungstoken', s.aufrufe[0] && s.aufrufe[0].auth === 'Bearer TOKEN');
    s.w.close();

    console.log('\n── 2. Anleitung');
    s = await seite(stand({ zugang_moeglich: { nein: false, schluessel: false },
                             konten: [{ name: 'root', art: 'root', anzahl: 0, zaehlt: false, schluessel: [] }] }));
    check('niemand kaeme herein -> Anleitung offen', s.w.document.getElementById('sec-ssh-anleitung').open === true);
    const anl = text(s.w, 'sec-ssh-anleitung');
    check('Anleitung nennt ssh-keygen und die .pub-Datei', /ssh-keygen -t ed25519/.test(anl) && /id_ed25519\.pub/.test(anl), anl);
    check('Anleitung verlangt keine Handarbeit auf dem Server mehr (ssh-copy-id, chmod, authorized_keys)',
          !/ssh-copy-id|chmod|authorized_keys/.test(anl), anl);
    check('Anleitung warnt vor dem privaten Schlüssel', /privaten/.test(anl), anl);
    s.w.close();

    console.log('\n── 3. Knoepfe je Zustand');
    s = await seite(stand());
    check('kein Test: "abschalten (Test)" sichtbar', sichtbar(s.w, 'sec-ssh-h-test'));
    check('kein Test: Bestaetigen/Verwerfen/Aus verborgen',
          !sichtbar(s.w, 'sec-ssh-h-ok') && !sichtbar(s.w, 'sec-ssh-h-weg') && !sichtbar(s.w, 'sec-ssh-h-aus'));
    s.w.close();
    s = await seite(stand({ test: { haertung: { laeuft: true, rest_s: 200 }, netze: { laeuft: false, rest_s: null } } }));
    check('Test laeuft: Bestaetigen + Verwerfen sichtbar, Test verborgen',
          sichtbar(s.w, 'sec-ssh-h-ok') && sichtbar(s.w, 'sec-ssh-h-weg') && !sichtbar(s.w, 'sec-ssh-h-test'));
    check('Restfrist als Text (3:20)', /Rücknahme in 3:[12]\d/.test(text(s.w, 'sec-ssh-h-frist')), text(s.w, 'sec-ssh-h-frist'));
    check('Abzeichen fordert zum Bestaetigen auf', /bestätigen/.test(text(s.w, 'sec-ssh-badge')));
    check('Auswahl root gesperrt waehrend des Tests',
          [].every.call(s.w.document.querySelectorAll('input[name="sec-ssh-root"]'), i => i.disabled));
    s.w.close();
    s = await seite(stand({ haertung: 'an', root_modus: 'schluessel',
                            sshd: { passwordauthentication: 'no', kbdinteractiveauthentication: 'no', permitrootlogin: 'prohibit-password' } }));
    check('aktiv: nur "wieder erlauben" sichtbar',
          sichtbar(s.w, 'sec-ssh-h-aus') && !sichtbar(s.w, 'sec-ssh-h-test') && !sichtbar(s.w, 'sec-ssh-h-ok'));
    check('aktiv: gespeicherter root-Modus ausgewaehlt',
          s.w.document.querySelector('input[name="sec-ssh-root"]:checked').value === 'schluessel');
    check('aktiv: Abzeichen "nur Schlüssel"', text(s.w, 'sec-ssh-badge') === 'nur Schlüssel');
    s.w.close();

    console.log('\n── 4. Test starten');
    s = await seite(stand());
    s.w.__confirm = false;
    s.w.document.getElementById('sec-ssh-h-test').click();
    await warte(10);
    check('Rueckfrage abgelehnt -> kein POST', !s.aufrufe.some(a => a.methode === 'POST'));
    s.w.__confirm = true; s.w.__prompt = null;
    s.w.document.getElementById('sec-ssh-h-test').click();
    await warte(10);
    check('Code-Abfrage abgebrochen -> kein POST', !s.aufrufe.some(a => a.methode === 'POST'));
    s.w.__prompt = '12 34 56';
    s.w.document.querySelector('input[name="sec-ssh-root"][value="schluessel"]').checked = true;
    s.w.document.getElementById('sec-ssh-h-test').click();
    await warte(20);
    const p = s.aufrufe.find(a => a.methode === 'POST');
    check('POST an /api/broker/ssh/haertung', p && p.pfad === '/api/broker/ssh/haertung', p && p.pfad);
    check('…mit aktion=test, root_modus aus der Auswahl, Code nur Ziffern',
          p && p.body.aktion === 'test' && p.body.root_modus === 'schluessel' && p.body.nachweis === '123456',
          p && JSON.stringify(p.body));
    check('…danach Zustand neu geholt', s.aufrufe.filter(a => a.pfad === '/api/broker/ssh/status').length >= 2);
    s.w.close();

    console.log('\n── 5. Verwerfen ohne Code');
    s = await seite(stand({ test: { haertung: { laeuft: true, rest_s: 100 }, netze: { laeuft: false, rest_s: null } } }));
    let gefragt = false;
    s.w.prompt = () => { gefragt = true; return '111111'; };
    s.w.document.getElementById('sec-ssh-h-weg').click();
    await warte(20);
    const pv = s.aufrufe.find(a => a.methode === 'POST');
    check('verwerfen: POST ohne Code-Abfrage', pv && pv.body.aktion === 'verwerfen' && !gefragt && !('nachweis' in pv.body),
          pv && JSON.stringify(pv.body));
    s.w.close();

    console.log('\n── 6. Abgewiesener Code');
    s = await seite(stand(), { '/api/broker/ssh/haertung': { ok: false, grund: 'nachweis_falsch', error: 'x' } });
    s.w.document.getElementById('sec-ssh-h-test').click();
    await warte(20);
    const res = s.w.document.getElementById('sec-ssh-h-result');
    check('Klartext am Knopf', res.style.display !== 'none' && /falsch oder abgelaufen/.test(res.textContent), res.textContent);
    check('…als Fehler gekennzeichnet', res.classList.contains('fehler'));
    check('…kein alert', s.w.__alerts.length === 0);
    await warte(50);
    check('…bleibt stehen (verschwindet nicht von selbst)', res.style.display !== 'none' && res.textContent.length > 0);
    s.w.close();

    console.log('\n── 7. Netze');
    s = await seite(stand({ netze: '198.51.100.0/24' }));
    const feld = s.w.document.getElementById('sec-ssh-netze');
    check('gespeicherte Netze im (versteckten) Wert', feld.value === '198.51.100.0/24', feld.value);
    check('…und als Eintrag in der Liste', /198\.51\.100\.0\/24/.test(text(s.w, 'sec-ssh-netze-liste')));
    const neu = s.w.document.getElementById('sec-ssh-netz-neu');
    neu.value = '192.0.2.0/24'; s.w.document.getElementById('sec-ssh-netz-add').click();
    neu.value = '2001:db8::/48'; s.w.document.getElementById('sec-ssh-netz-add').click();
    s.w.document.getElementById('sec-ssh-n-test').click();
    await warte(20);
    const pn = s.aufrufe.find(a => a.methode === 'POST');
    check('POST /api/broker/ssh/netze mit der Liste des Helfers und Code',
          pn && pn.pfad === '/api/broker/ssh/netze'
          && pn.body.netze === '198.51.100.0/24 192.0.2.0/24 2001:db8::/48'
          && pn.body.nachweis === '123456', pn && JSON.stringify(pn));
    s.w.close();
    s = await seite(stand({ firewall_eingerichtet: false }));
    check('Paketfilter fehlt: Knopf gesperrt', s.w.document.getElementById('sec-ssh-n-test').disabled === true);
    check('…mit Hinweis auf die Konsole', /Konsole/.test(text(s.w, 'sec-ssh-n-result')), text(s.w, 'sec-ssh-n-result'));
    s.w.close();
    s = await seite(stand({ test: { haertung: { laeuft: false, rest_s: null }, netze: { laeuft: true, rest_s: 250 } } }));
    check('Netze-Test laeuft: Bestaetigen + Verwerfen sichtbar',
          sichtbar(s.w, 'sec-ssh-n-ok') && sichtbar(s.w, 'sec-ssh-n-weg') && !sichtbar(s.w, 'sec-ssh-n-test'));
    s.w.close();

    console.log('\n── 9. Maus-Helfer "Erlaubte Netze"');
    const vsStand = () => stand({
        netze: '', deine_adresse: '203.0.113.7',
        vorschlaege: {
            lokal: [{ netz: '198.51.100.0/22', schnittstelle: 'ens192' }],
            tailscale: true,
            anmeldungen: [
                { ip: '203.0.113.7', anzahl: 12, zuletzt: '2026-10-06T14:58:30+02:00', konten: ['root'] },
                { ip: '192.0.2.44', anzahl: 3, zuletzt: '2026-10-01T09:00:00+02:00', konten: ['kollege'] },
            ],
        },
    });
    s = await seite(vsStand());
    const W = s.w, D = W.document;
    const liste = () => text(W, 'sec-ssh-netze-liste');
    const wert = () => D.getElementById('sec-ssh-netze').value;
    const knopfFuer = (netz) => D.querySelector('#sec-ssh-netze-vorschlaege [data-netz-dazu="' + netz + '"]');
    check('leer: "Keine Einschränkung" sichtbar', /Keine Einschränkung/.test(liste()), liste());
    check('keine Warnung, solange nichts eingeschraenkt ist', !sichtbar(W, 'sec-ssh-netze-warnung'));
    const vs = D.querySelectorAll('#sec-ssh-netze-vorschlaege [data-netz-dazu]');
    check('Vorschlaege: eigene Adresse (= SSH-Herkunft zusammengefasst), zweite SSH-Herkunft, Tailscale, Server-Netz',
          vs.length === 4 && !!knopfFuer('203.0.113.7/32') && !!knopfFuer('192.0.2.44/32')
          && !!knopfFuer('100.64.0.0/10') && !!knopfFuer('198.51.100.0/22'),
          [].map.call(vs, b => b.getAttribute('data-netz-dazu')).join(' '));
    const deinKnopf = knopfFuer('203.0.113.7/32');
    check('…eigene Adresse nennt beide Gruende (Weboberflaeche + 12× SSH, Konto)',
          /deine aktuelle Adresse/.test(deinKnopf.textContent) && /12× per SSH angemeldet \(root\)/.test(deinKnopf.textContent),
          deinKnopf.textContent);
    deinKnopf.click();
    check('Klick auf Vorschlag: Eintrag erscheint', /203\.0\.113\.7\/32/.test(liste()) && wert() === '203.0.113.7/32', wert());
    check('…Vorschlag ist danach "enthalten" und gesperrt',
          knopfFuer('203.0.113.7/32').disabled && /enthalten/.test(knopfFuer('203.0.113.7/32').textContent));
    check('…Hinweis "noch nicht übernommen"', /Noch nicht übernommen/.test(text(W, 'sec-ssh-netze-warnung')));
    check('…Warnung nennt die zweite SSH-Herkunft, die jetzt ausgesperrt waere',
          /192\.0\.2\.44/.test(text(W, 'sec-ssh-netze-warnung')) && !/Deine aktuelle Adresse/.test(text(W, 'sec-ssh-netze-warnung')),
          text(W, 'sec-ssh-netze-warnung'));
    knopfFuer('198.51.100.0/22').click();
    check('Server-Netz hinzugefuegt', wert() === '203.0.113.7/32 198.51.100.0/22', wert());

    const neuF = D.getElementById('sec-ssh-netz-neu'), umf = D.getElementById('sec-ssh-netz-praefix');
    neuF.value = '192.0.2.77'; umf.value = 'klein';
    D.getElementById('sec-ssh-netz-add').click();
    check('eingetippt + "ihr Netz": 192.0.2.77 -> 192.0.2.0/24', / 192\.0\.2\.0\/24$/.test(wert()) && neuF.value === '', wert());
    check('…deckt die zweite SSH-Herkunft ab: Vorschlag "enthalten", Warnung weg',
          knopfFuer('192.0.2.44/32').disabled && !/192\.0\.2\.44/.test(text(W, 'sec-ssh-netze-warnung')));
    neuF.value = '2001:db8:0:0:0:0:0:1'; umf.value = 'gross';
    neuF.dispatchEvent(new W.KeyboardEvent('keydown', { key: 'Enter', bubbles: true }));
    check('IPv6 per Enter, "großes Netz" -> 2001:db8::/48', / 2001:db8::\/48$/.test(wert()), wert());
    neuF.value = '300.1.1.1'; umf.value = 'einzeln';
    D.getElementById('sec-ssh-netz-add').click();
    check('ungueltige Adresse: Meldung, kein Eintrag',
          /Keine gültige/.test(text(W, 'sec-ssh-netz-fehler')) && !/300\.1\.1\.1/.test(wert()), text(W, 'sec-ssh-netz-fehler'));
    check('…und die Eingabe bleibt zum Korrigieren stehen', neuF.value === '300.1.1.1');
    neuF.value = '198.51.100.5/22';
    D.getElementById('sec-ssh-netz-add').click();
    check('doppelt (nach Normierung): "Schon enthalten"', /Schon enthalten: 198\.51\.100\.0\/22/.test(text(W, 'sec-ssh-netz-fehler')),
          text(W, 'sec-ssh-netz-fehler'));
    const weg = D.querySelector('#sec-ssh-netze-liste [data-netz-weg="203.0.113.7/32"]');
    check('Entfernen-Knopf traegt das Muelleimer-Symbol (SVG, kein Emoji)',
          weg && !!weg.querySelector('svg') && !/[\u{1F300}-\u{1FAFF}]/u.test(weg.textContent));
    weg.click();
    check('Mülleimer entfernt den Eintrag', !/203\.0\.113\.7/.test(wert()), wert());
    check('…und jetzt warnt der Helfer: eigene Adresse nicht enthalten',
          /Deine aktuelle Adresse 203\.0\.113\.7 ist nicht enthalten/.test(text(W, 'sec-ssh-netze-warnung')));

    // Ein Nachladen des Zustands (Aktualisieren) verwirft die angefangene Liste NICHT
    await W.Fernzugang.laden();
    check('Aktualisieren behaelt die noch nicht übernommene Liste', / 2001:db8::\/48$/.test(wert()), wert());
    // Nach erfolgreichem Test zeigt die Liste den Stand des Servers
    s.setzeStatus(stand({ netze: '192.0.2.0/24', deine_adresse: '203.0.113.7',
                          vorschlaege: { lokal: [], tailscale: false, anmeldungen: [] } }));
    D.getElementById('sec-ssh-n-test').click();
    await warte(30);
    check('nach dem Test: Liste = Stand des Servers', wert() === '192.0.2.0/24', wert());
    check('…und kein "noch nicht übernommen" mehr', !/Noch nicht übernommen/.test(text(W, 'sec-ssh-netze-warnung')));
    s.w.close();

    // Rechenhelfer direkt
    s = await seite(stand());
    const R = s.w.Fernzugang._rechnen;
    check('normieren: 10.1.2.3/8 -> 10.0.0.0/8', R.netzNormieren('10.1.2.3/8').text === '10.0.0.0/8');
    check('normieren: einzeln -> /32', R.netzNormieren('192.0.2.9').text === '192.0.2.9/32');
    check('normieren: ::1 -> ::1/128', R.netzNormieren('::1').text === '::1/128', R.netzNormieren('::1') && R.netzNormieren('::1').text);
    check('enthaelt: Tailscale-Adresse im CGNAT-Netz', R.enthaelt('100.64.0.0/10', '100.64.12.34'));
    check('enthaelt nicht: Nachbarnetz', !R.enthaelt('192.0.2.0/24', '192.0.3.1'));
    check('enthaelt: IPv6 im /48', R.enthaelt('2001:db8::/48', '2001:db8:0:ffff::1') && !R.enthaelt('2001:db8::/48', '2001:db9::1'));
    check('ungueltig: 1.2.3, 1.2.3.4/33, a::b::c', !R.netzNormieren('1.2.3') && !R.netzNormieren('1.2.3.4/33') && !R.netzNormieren('a::b::c'));
    s.w.close();

    console.log('\n── 8. Schluessel hinterlegen / entfernen');
    const sek = html.slice(html.indexOf('id="sec-sect-ssh-hdr"'), html.indexOf('id="sec-sect-rem-box"'));
    check('Positivkontrolle: Abschnitt geschnitten', sek.length > 1000 && sek.indexOf('sec-ssh-netze') > 0);
    check('Eingabefeld und Datei-Feld im Abschnitt', /<textarea[^>]*id="sec-ssh-schl-text"/.test(sek) && /type="file"[^>]*id="sec-ssh-schl-datei"|id="sec-ssh-schl-datei"[^>]*type="file"/.test(sek));
    const js = lies('js/fernzugang.js').replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
    const ziele = js.match(/['"]\/api\/[^'"]+['"]/g) || [];
    check('fernzugang.js ruft nur status/haertung/netze/schluessel',
          ziele.length > 0 && ziele.every(z => /\/api\/broker\/ssh\/(status|haertung|netze|schluessel)['"]/.test(z)), ziele.join(' '));

    // Testschluessel: ECHTES ed25519-Paar, Fingerabdruck vom ECHTEN ssh-keygen
    const cp = require('child_process'), os = require('os'), nc = require('crypto');
    const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'jv_fz_ui_'));
    let pub = '', fpEcht = '', privat = '';
    try {
        cp.execFileSync('ssh-keygen', ['-q', '-t', 'ed25519', '-N', '', '-C', 'ich@rechner', '-f', path.join(tmp, 'k')]);
        pub = fs.readFileSync(path.join(tmp, 'k.pub'), 'utf-8').trim();
        privat = fs.readFileSync(path.join(tmp, 'k'), 'utf-8');
        fpEcht = cp.execFileSync('ssh-keygen', ['-lf', path.join(tmp, 'k.pub')]).toString().split(/\s+/)[1] || '';
    } catch (e) { /* unten als Abbruch */ }
    fs.rmSync(tmp, { recursive: true, force: true });
    if (!/^SHA256:/.test(fpEcht) || !pub) { console.log('ABBRUCH: ssh-keygen nicht nutzbar (Messaufbau)'); process.exit(2); }

    s = await seite(stand());
    const W8 = s.w, D8 = W8.document;
    // jsdom bringt kein WebCrypto mit – die ECHTE Implementierung aus Node einsetzen
    if (!(W8.crypto && W8.crypto.subtle)) Object.defineProperty(W8, 'crypto', { value: nc.webcrypto, configurable: true });
    const schlWahl = D8.getElementById('sec-ssh-schl-konto');
    check('Kontowahl: die angezeigten Konten', schlWahl && Array.from(schlWahl.options).map(o => o.value).join(',') === 'root,admin,anna',
          schlWahl && Array.from(schlWahl.options).map(o => o.value).join(','));
    check('Kontowahl: vorbelegt mit dem ersten Nicht-root-Konto', schlWahl && schlWahl.value === 'admin', schlWahl && schlWahl.value);
    const muell = D8.querySelectorAll('#sec-ssh-konten [data-schl-weg]');
    check('Muelleimer je Schluessel (2), mit Symbol statt Emoji',
          muell.length === 2 && Array.from(muell).every(b => b.querySelector('.jv-ico-trash')), muell.length);

    const schlFeld = D8.getElementById('sec-ssh-schl-text');
    schlFeld.value = pub;
    await W8.Fernzugang.schluesselVorschau();
    const vor = text(W8, 'sec-ssh-schl-vorschau');
    const fpVor = (/SHA256:[A-Za-z0-9+/=]+/.exec(vor) || [''])[0];
    check('Vorschau: Fingerabdruck = ssh-keygen -lf (gleich, nicht nur enthalten)', fpVor === fpEcht, fpVor + ' / ' + fpEcht);

    const bestaetigt = [];
    W8.confirm = (t) => { bestaetigt.push(t); return W8.__confirm; };
    const posts = () => s.aufrufe.filter(a => a.pfad === '/api/broker/ssh/schluessel');
    W8.__confirm = false;
    await W8.Fernzugang.schluesselHinzu(); await warte(10);
    check('Rueckfrage abgelehnt -> KEIN Aufruf', posts().length === 0);
    check('Rueckfrage nennt Konto und Fingerabdruck', /als admin anmelden/.test(bestaetigt[0] || '') && (bestaetigt[0] || '').indexOf(fpEcht) >= 0, bestaetigt[0]);
    W8.__confirm = true; W8.__prompt = null;
    await W8.Fernzugang.schluesselHinzu(); await warte(10);
    check('Code-Abfrage abgebrochen -> KEIN Aufruf', posts().length === 0);
    W8.__prompt = '123456';
    schlWahl.value = 'anna';
    await W8.Fernzugang.schluesselHinzu(); await warte(30);
    const p1 = posts()[0] || {};
    check('POST hinzufuegen mit Konto, Schluessel und Code',
          p1.body && p1.body.aktion === 'hinzufuegen' && p1.body.konto === 'anna' && p1.body.schluessel === pub && p1.body.nachweis === '123456',
          JSON.stringify(p1.body));
    check('nach Erfolg: Feld geleert, Ergebnis am Knopf', schlFeld.value === '' && sichtbar(W8, 'sec-ssh-schl-result'), schlFeld.value);

    const vorher = posts().length;
    schlFeld.value = privat;
    await W8.Fernzugang.schluesselHinzu(); await warte(10);
    check('privater Schluessel: Warnung, KEIN Aufruf', /PRIVATER/.test(text(W8, 'sec-ssh-schl-vorschau')) && posts().length === vorher,
          text(W8, 'sec-ssh-schl-vorschau'));
    schlFeld.value = pub + '\n' + pub;
    await W8.Fernzugang.schluesselHinzu(); await warte(10);
    check('zwei Zeilen: Warnung, KEIN Aufruf', /genau einen/.test(text(W8, 'sec-ssh-schl-vorschau')) && posts().length === vorher);
    schlFeld.value = 'command="/bin/sh" ' + pub;
    await W8.Fernzugang.schluesselHinzu(); await warte(10);
    check('Optionen vor dem Schluessel: Warnung, KEIN Aufruf', /Kein unterstützter/.test(text(W8, 'sec-ssh-schl-vorschau')) && posts().length === vorher);
    schlFeld.value = '';
    await W8.Fernzugang.schluesselHinzu(); await warte(10);
    check('leer: Hinweis am Knopf, KEIN Aufruf', /zuerst einen öffentlichen Schlüssel/.test(text(W8, 'sec-ssh-schl-result')) && posts().length === vorher);

    // Entfernen per Muelleimer
    W8.__confirm = false;
    D8.querySelector('#sec-ssh-konten [data-schl-weg="SHA256:adminFP"]').click(); await warte(10);
    check('Entfernen abgelehnt -> KEIN Aufruf', posts().length === vorher);
    W8.__confirm = true;
    D8.querySelector('#sec-ssh-konten [data-schl-weg="SHA256:adminFP"]').click(); await warte(30);
    const p2 = posts()[vorher] || {};
    check('POST entfernen mit Konto, Fingerabdruck und Code',
          p2.body && p2.body.aktion === 'entfernen' && p2.body.konto === 'admin' && p2.body.fingerabdruck === 'SHA256:adminFP' && p2.body.nachweis === '123456',
          JSON.stringify(p2.body));
    check('Ergebnis des Entfernens direkt unter der Liste', sichtbar(W8, 'sec-ssh-konten-result'));
    s.w.close();

    // Abgewiesener Code: Klartext am Knopf
    s = await seite(stand(), { '/api/broker/ssh/schluessel': { ok: false, grund: 'nachweis_falsch', error: 'x' } });
    if (!(s.w.crypto && s.w.crypto.subtle)) Object.defineProperty(s.w, 'crypto', { value: nc.webcrypto, configurable: true });
    s.w.document.getElementById('sec-ssh-schl-text').value = pub;
    await s.w.Fernzugang.schluesselHinzu(); await warte(30);
    check('abgewiesener Code: Klartext am Knopf', /Freigabe-Code ist falsch/.test(text(s.w, 'sec-ssh-schl-result')), text(s.w, 'sec-ssh-schl-result'));
    s.w.close();

    fertig();
    console.log(`\nErgebnis: ${ok} OK, ${fail} FAIL`);
    process.exit(fail ? 1 : 0);
})();
