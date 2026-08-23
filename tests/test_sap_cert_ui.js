#!/usr/bin/env node
/**
 * UI-Tests fuer "Zertifikat pruefen/verankern" (frontend/js/sapcert.js).
 *
 * Geprueft werden BEIDE Oberflaechen gegen die ECHTEN Dateien:
 *   - /sap  -> sap.html + js/sap_portal.js  (persoenlicher Zugang)
 *   - /settings -> settings.html + js/sap.js (Sammelzugang)
 *
 * WICHTIG (Fallstrick vom 2026-08-12): die fetch-Attrappe routet ueber den
 * PFAD, nicht ueber die volle URL – sonst verfehlt sie jeden Aufruf mit
 * Abfrageteil (`?kanal=odata`) und der Test laeuft in "undefined".
 *
 * WICHTIG (Fallstrick vom 2026-07-30): am Ende window.close() und ein
 * ausdrueckliches process.exit(), sonst haengt der Node-Prozess an den
 * Poll-Timern der geladenen Seite.
 *
 * Aufruf:  node tests/test_sap_cert_ui.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom');

const ROOT = path.resolve(__dirname, '..');
const results = [];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function check(name, cond, detail) {
    results.push({ name, ok: !!cond, detail: detail || '' });
    console.log((cond ? '  OK   ' : '  FAIL ') + name + (!cond && detail ? ' – ' + detail : ''));
}
function section(t) { console.log('\n' + t); }

// ── Zertifikats-Antworten in der Form von sap_cert.pruefen ──────────
const FP_A = 'sha256:' + 'a1'.repeat(32);
const FP_B = 'sha256:' + 'b2'.repeat(32);

const ZERT_SELBST = {
    host: 's4.firma.de', port: 443, fingerprint: FP_A,
    inhaber: 's4.firma.de', aussteller: 'Firma Interne CA',
    gueltig_von: '2026-01-01 00:00 UTC', gueltig_bis: '2027-01-01 00:00 UTC',
    namen: ['s4.firma.de', 'sap.firma.de'], selbstsigniert: true,
    system_ok: false, system_grund: 'selbst ausgestelltes Zertifikat',
    pin_ok: true, pin_grund: '', kanal: 'odata',
};
const ZERT_OK = Object.assign({}, ZERT_SELBST,
    { system_ok: true, system_grund: '', aussteller: 'DigiCert Global G2' });
const ZERT_NAME = Object.assign({}, ZERT_SELBST, {
    pin_ok: false, pin_grund: 'der Name im Zertifikat passt nicht zur Adresse',
    namen: ['ganz.woanders.example'],
});
// Fremdserver-Text: der Aussteller kommt von aussen und darf niemals als
// Markup landen.
const ZERT_XSS = Object.assign({}, ZERT_SELBST, {
    aussteller: '<img src=x onerror="window.__pwn=1">',
    inhaber: '<script>window.__pwn2=1</script>',
});

function baueDom(htmlFile, opts) {
    opts = opts || {};
    const html = fs.readFileSync(path.join(ROOT, 'frontend', htmlFile), 'utf8');
    const rufe = [];
    const vc = new VirtualConsole();
    vc.on('jsdomError', () => {});
    const dom = new JSDOM(html, {
        url: 'https://localhost/' + (htmlFile === 'sap.html' ? 'sap' : 'settings'),
        runScripts: 'dangerously',
        virtualConsole: vc,
        beforeParse(win) {
            win.localStorage.setItem('jarvis_token', 'testtoken');
            win.HTMLCanvasElement.prototype.getContext = () => null;
            win.confirm = () => (opts.confirm !== false);
            win.fetch = function (url, init) {
                const voll = String(url);
                const pfad = voll.split('?')[0];      // <- Routing ueber den PFAD
                const methode = (init && init.method) || 'GET';
                const rumpf = (init && init.body) ? JSON.parse(init.body) : null;
                rufe.push({ url: voll, pfad, methode, rumpf });
                const json = (data, status) => Promise.resolve({
                    ok: (status || 200) < 400, status: status || 200,
                    json: () => Promise.resolve(data),
                    text: () => Promise.resolve(JSON.stringify(data)),
                });
                if (pfad === '/api/me') {
                    return json({ username: 'bob', is_admin: true,
                                  permissions: { sap: true } });
                }
                if (/\/cert\/probe$/.test(pfad)) {
                    if (opts.probeFehler) return json({ ok: false, error: opts.probeFehler }, 400);
                    return json({ ok: true, zert: opts.zert || ZERT_SELBST,
                                  account: opts.account || {}, gebunden: {} });
                }
                if (/\/cert\/trust$/.test(pfad)) {
                    if (opts.trustFehler) return json({ ok: false, error: opts.trustFehler }, 400);
                    return json({ ok: true, kanal: 'odata',
                                  account: opts.accountNachher || {}, gebunden: {} });
                }
                if (/\/cert$/.test(pfad) && methode === 'DELETE') {
                    return json({ ok: true, kanal: 'odata', account: {}, gebunden: {} });
                }
                if (pfad === '/api/sap/account') {
                    return json({ ok: true, account: opts.account || {} });
                }
                if (pfad === '/api/skills/sap/config') {
                    return json({ config: opts.config || {} });
                }
                if (pfad === '/api/sap/status') {
                    return json({ ok: true, configured: true, connection_type: 'odata' });
                }
                if (pfad === '/api/sap/analyses') return json({ lang: 'de', categories: [], analyses: [], bi_tools: [] });
                return json({ ok: true });
            };
        },
    });
    dom.__rufe = rufe;
    return dom;
}

function ladeSkript(dom, rel) {
    dom.window.eval(fs.readFileSync(path.join(ROOT, 'frontend', rel), 'utf8'));
}

function txt(dom, sel) {
    const e = dom.window.document.querySelector(sel);
    return e ? e.textContent : null;
}

(async () => {
    // ══ 1. Quelltext-Regeln ══════════════════════════════════════════
    section('1. Der Baustein liegt EINMAL vor');
    {
        const js = fs.readFileSync(path.join(ROOT, 'frontend/js/sapcert.js'), 'utf8');
        check('sapcert.js stellt window.SapCert.mount bereit',
              /window\.SapCert\s*=\s*\{\s*mount/.test(js));
        const sapjs = fs.readFileSync(path.join(ROOT, 'frontend/js/sap.js'), 'utf8');
        const portal = fs.readFileSync(path.join(ROOT, 'frontend/js/sap_portal.js'), 'utf8');
        check('sap.js benutzt den gemeinsamen Baustein', /SapCert\.mount/.test(sapjs));
        check('sap_portal.js benutzt denselben', /SapCert\.mount/.test(portal));
        check('Reiter nimmt die Admin-Endpunkte', /'\/api\/sap\/admin\/cert'/.test(sapjs));
        check('Benutzerkachel nimmt die Benutzer-Endpunkte',
              /'\/api\/sap\/cert'/.test(portal) && !/admin\/cert/.test(portal));
        // Keine zweite Fassung des Kastens – sonst laufen sie auseinander.
        check('keine zweite Renderfassung in sap.js', !/sapcert-box/.test(sapjs));
        check('keine zweite Renderfassung in sap_portal.js', !/sapcert-box/.test(portal));
    }

    // ══ 2. /sap – Benutzerkachel ═════════════════════════════════════
    section('2. /sap: pruefen, verankern, loesen');
    {
        const dom = baueDom('sap.html', {
            account: { vorhanden: true, connection_type: 'odata',
                       odata_base_url: 'https://s4.firma.de/sap/opu',
                       erlaubte_hosts: ['s4.firma.de'], cert: {} },
        });
        ladeSkript(dom, 'js/icons.js');
        ladeSkript(dom, 'js/sapcert.js');
        ladeSkript(dom, 'js/sap_portal.js');
        await sleep(80);
        const d = dom.window.document;

        const box = d.getElementById('sp-cert-odata');
        check('Baustein ist eingehaengt', !!box && !!box.querySelector('.sapcert-btn'));
        check('Ergebniskasten startet verborgen',
              !!box && box.querySelector('.sapcert-box').hidden);

        dom.__rufe.length = 0;
        box.querySelector('.sapcert-btn').click();
        await sleep(60);
        const probe = dom.__rufe.filter((r) => /\/cert\/probe$/.test(r.pfad));
        check('genau EIN Probe-Aufruf', probe.length === 1, String(probe.length));
        check('…gegen den Benutzer-Endpunkt',
              !!probe[0] && probe[0].pfad === '/api/sap/cert/probe',
              probe[0] && probe[0].pfad);
        check('…mit der URL aus dem Formular',
              !!probe[0] && probe[0].rumpf.url === 'https://s4.firma.de/sap/opu',
              probe[0] && JSON.stringify(probe[0].rumpf));
        check('…und dem Kanal', !!probe[0] && probe[0].rumpf.kanal === 'odata');

        const kasten = box.querySelector('.sapcert-box');
        check('Kasten wird sichtbar', !kasten.hidden);
        check('Fingerabdruck steht vollstaendig da',
              (txt(dom, '#sp-cert-odata .sapcert-fp') || '') === FP_A);
        check('Aussteller wird genannt',
              /Firma Interne CA/.test(kasten.textContent));
        check('Namen im Zertifikat werden genannt',
              /sap\.firma\.de/.test(kasten.textContent));
        check('Urteil "verankerbar" ist eine Warnung',
              !!kasten.querySelector('.sapcert-verdict.is-warn'));
        check('Verankern-Knopf ist da',
              !!kasten.querySelector('.sapcert-btn.is-primary'));
        check('Hinweis nennt: der Browser ist nicht beteiligt',
              /Browser/.test(kasten.textContent));

        dom.__rufe.length = 0;
        kasten.querySelector('.sapcert-btn.is-primary').click();
        await sleep(60);
        const trust = dom.__rufe.filter((r) => /\/cert\/trust$/.test(r.pfad));
        check('Verankern ruft /cert/trust', trust.length === 1);
        check('…und sendet NUR den Fingerabdruck, kein PEM',
              !!trust[0] && trust[0].rumpf.fingerprint === FP_A
              && !('pem' in trust[0].rumpf),
              trust[0] && JSON.stringify(trust[0].rumpf));
        dom.window.close();
    }

    // ══ 3. Urteile ═══════════════════════════════════════════════════
    section('3. Die drei Urteile');
    {
        const dom = baueDom('sap.html', {
            zert: ZERT_OK,
            account: { vorhanden: true, connection_type: 'odata',
                       odata_base_url: 'https://s4.firma.de/x', cert: {} },
        });
        ladeSkript(dom, 'js/icons.js');
        ladeSkript(dom, 'js/sapcert.js');
        ladeSkript(dom, 'js/sap_portal.js');
        await sleep(80);
        const box = dom.window.document.getElementById('sp-cert-odata');
        box.querySelector('.sapcert-btn').click();
        await sleep(60);
        check('bekannte CA: gruenes Urteil',
              !!box.querySelector('.sapcert-verdict.is-ok'));
        check('bekannte CA: KEIN Verankern-Knopf',
              !box.querySelector('.sapcert-btn.is-primary'));
        dom.window.close();
    }
    {
        const dom = baueDom('sap.html', {
            zert: ZERT_NAME,
            account: { vorhanden: true, connection_type: 'odata',
                       odata_base_url: 'https://s4.firma.de/x', cert: {} },
        });
        ladeSkript(dom, 'js/icons.js');
        ladeSkript(dom, 'js/sapcert.js');
        ladeSkript(dom, 'js/sap_portal.js');
        await sleep(80);
        const box = dom.window.document.getElementById('sp-cert-odata');
        box.querySelector('.sapcert-btn').click();
        await sleep(60);
        const kasten = box.querySelector('.sapcert-box');
        check('Namensabweichung: Fehler-Urteil',
              !!kasten.querySelector('.sapcert-verdict.is-err'));
        // Der entscheidende Punkt: KEIN Knopf, der etwas verspricht, das die
        // Verbindung nicht haelt.
        check('Namensabweichung: KEIN Verankern-Knopf',
              !kasten.querySelector('.sapcert-btn.is-primary'));
        check('Namensabweichung: der Weg zur Loesung steht da',
              /ganz\.woanders\.example/.test(kasten.textContent));
        dom.window.close();
    }

    // ══ 4. Fremdtext ist Text, nie Markup ════════════════════════════
    section('4. XSS: der Aussteller kommt vom fremden Server');
    {
        const dom = baueDom('sap.html', {
            zert: ZERT_XSS,
            account: { vorhanden: true, connection_type: 'odata',
                       odata_base_url: 'https://s4.firma.de/x', cert: {} },
        });
        ladeSkript(dom, 'js/icons.js');
        ladeSkript(dom, 'js/sapcert.js');
        ladeSkript(dom, 'js/sap_portal.js');
        await sleep(80);
        const box = dom.window.document.getElementById('sp-cert-odata');
        box.querySelector('.sapcert-btn').click();
        await sleep(80);
        const kasten = box.querySelector('.sapcert-box');
        check('kein <img> aus dem Zertifikatstext', !kasten.querySelector('img'));
        check('kein <script> aus dem Zertifikatstext', !kasten.querySelector('script'));
        check('kein Handler ausgefuehrt',
              !dom.window.__pwn && !dom.window.__pwn2);
        check('…der Text ist trotzdem lesbar da',
              /onerror/.test(kasten.textContent));
        dom.window.close();
    }

    // ══ 5. Zustand: verankert / vom Administrator verankert ══════════
    section('5. Zustandszeile und Loesen');
    {
        const dom = baueDom('sap.html', {
            account: {
                vorhanden: true, connection_type: 'odata',
                odata_base_url: 'https://s4.firma.de/x',
                cert: { odata: { eigen: { host: 's4.firma.de', port: 443,
                                          fingerprint: FP_A, gebunden_am: 1755900000 },
                                 admin: {} },
                        hana: { eigen: {}, admin: {} } },
            },
        });
        ladeSkript(dom, 'js/icons.js');
        ladeSkript(dom, 'js/sapcert.js');
        ladeSkript(dom, 'js/sap_portal.js');
        await sleep(80);
        const box = dom.window.document.getElementById('sp-cert-odata');
        const pin = box.querySelector('.sapcert-pinned');
        check('verankertes Zertifikat wird OHNE Pruefung angezeigt', !!pin);
        check('…mit Server und gekuerztem Fingerabdruck',
              !!pin && /s4\.firma\.de:443/.test(pin.textContent) && /a1a1/.test(pin.textContent));
        const loesen = pin.querySelector('.sapcert-icon');
        check('Loesen-Knopf vorhanden', !!loesen);
        // Symbol-Semantik: Muelleimer = loeschen, NIE ein x.
        check('…traegt den Muelleimer, kein x',
              !!loesen && /jv-ico-trash|<svg/.test(loesen.innerHTML)
              && !/[×✕✖]|&times;/.test(loesen.innerHTML),
              loesen && loesen.innerHTML.slice(0, 40));

        dom.__rufe.length = 0;
        loesen.click();
        await sleep(60);
        const del = dom.__rufe.filter((r) => r.methode === 'DELETE');
        check('Loesen schickt DELETE', del.length === 1);
        check('…mit dem Kanal im Abfrageteil',
              !!del[0] && /kanal=odata/.test(del[0].url), del[0] && del[0].url);
        dom.window.close();
    }
    {
        // Rueckfrage abgelehnt -> es darf NICHTS passieren.
        const dom = baueDom('sap.html', {
            confirm: false,
            account: {
                vorhanden: true, connection_type: 'odata',
                cert: { odata: { eigen: { host: 'h', port: 443, fingerprint: FP_A },
                                 admin: {} }, hana: { eigen: {}, admin: {} } },
            },
        });
        ladeSkript(dom, 'js/icons.js');
        ladeSkript(dom, 'js/sapcert.js');
        ladeSkript(dom, 'js/sap_portal.js');
        await sleep(80);
        const box = dom.window.document.getElementById('sp-cert-odata');
        dom.__rufe.length = 0;
        box.querySelector('.sapcert-icon').click();
        await sleep(50);
        check('abgelehnte Rueckfrage loest KEIN DELETE aus',
              dom.__rufe.filter((r) => r.methode === 'DELETE').length === 0);
        dom.window.close();
    }
    {
        // Nur der Administrator hat verankert -> anzeigen, aber kein Loesen.
        const dom = baueDom('sap.html', {
            account: {
                vorhanden: true, connection_type: 'odata',
                cert: { odata: { eigen: {},
                                 admin: { host: 's4.firma.de', port: 443, fingerprint: FP_B } },
                        hana: { eigen: {}, admin: {} } },
            },
        });
        ladeSkript(dom, 'js/icons.js');
        ladeSkript(dom, 'js/sapcert.js');
        ladeSkript(dom, 'js/sap_portal.js');
        await sleep(80);
        const box = dom.window.document.getElementById('sp-cert-odata');
        const pin = box.querySelector('.sapcert-pinned');
        check('Administrator-Anker wird genannt',
              !!pin && /Administrator/.test(pin.textContent));
        check('…aber ohne Loesen-Knopf (gehoert nicht dem Benutzer)',
              !!pin && !pin.querySelector('.sapcert-icon'));
        dom.window.close();
    }

    // ══ 6. Fehlerfaelle ══════════════════════════════════════════════
    section('6. Fehler werden im Klartext gemeldet');
    {
        const dom = baueDom('sap.html', {
            probeFehler: "Der Server 'fremd.de' ist nicht freigegeben.",
            account: { vorhanden: true, connection_type: 'odata',
                       odata_base_url: 'https://fremd.de/x', cert: {} },
        });
        ladeSkript(dom, 'js/icons.js');
        ladeSkript(dom, 'js/sapcert.js');
        ladeSkript(dom, 'js/sap_portal.js');
        await sleep(80);
        const box = dom.window.document.getElementById('sp-cert-odata');
        box.querySelector('.sapcert-btn').click();
        await sleep(60);
        check('Fehlertext des Servers steht in der Zeile',
              /nicht freigegeben/.test(box.querySelector('.sapcert-state').textContent),
              box.querySelector('.sapcert-state').textContent);
        check('…und der Kasten bleibt zu',
              box.querySelector('.sapcert-box').hidden);
        check('…und der Knopf ist wieder bedienbar',
              !box.querySelector('.sapcert-btn').disabled);
        dom.window.close();
    }

    // ══ 7. Sprache ═══════════════════════════════════════════════════
    section('7. DE/EN');
    {
        const dom = baueDom('sap.html', {
            account: { vorhanden: true, connection_type: 'odata',
                       odata_base_url: 'https://s4.firma.de/x', cert: {} },
        });
        ladeSkript(dom, 'js/i18n.js');
        ladeSkript(dom, 'js/icons.js');
        ladeSkript(dom, 'js/sapcert.js');
        ladeSkript(dom, 'js/sap_portal.js');
        await sleep(80);
        const box = dom.window.document.getElementById('sp-cert-odata');
        const btn = box.querySelector('.sapcert-btn');
        check('DE: Knopf beschriftet', /Zertifikat pr/.test(btn.textContent),
              btn.textContent);
        if (dom.window.setLang) {
            dom.window.setLang('en');
            await sleep(30);
            // Der Knopf entsteht beim Einhaengen; ein Sprachwechsel danach
            // greift erst beim naechsten Zeichnen – geprueft wird deshalb der
            // Katalog selbst, nicht das schon gerenderte Label.
            check('EN: Schluessel vorhanden',
                  dom.window.t('sapcert.check') === 'Check certificate',
                  dom.window.t('sapcert.check'));
            check('EN: Urteilstext uebersetzt',
                  /known certificate authority/.test(dom.window.t('sapcert.v_ok')));
        } else {
            check('EN: setLang erreichbar', false, 'setLang fehlt');
        }
        dom.window.close();
    }

    // ══ 8. Einstellungen-Reiter ══════════════════════════════════════
    section('8. Einstellungen -> SAP (Sammelzugang)');
    {
        const dom = baueDom('settings.html', {
            config: { connection_type: 'odata',
                      odata_base_url: 'https://s4.firma.de/sap/opu',
                      cert_odata: { host: 's4.firma.de', port: 443,
                                    fingerprint: FP_B, gebunden_am: 1755900000 } },
        });
        ladeSkript(dom, 'js/icons.js');
        ladeSkript(dom, 'js/sapcert.js');
        ladeSkript(dom, 'js/sap.js');
        dom.window.SapManager.onShow();
        await sleep(80);
        const d = dom.window.document;
        const box = d.getElementById('sapcert-odata');
        check('Baustein im OData-Block', !!box && !!box.querySelector('.sapcert-btn'));
        check('Baustein im HANA-Block',
              !!d.getElementById('sapcert-hana')
              && !!d.getElementById('sapcert-hana').querySelector('.sapcert-btn'));
        check('vorhandener Anker aus der Skill-Config wird angezeigt',
              !!box.querySelector('.sapcert-pinned')
              && /s4\.firma\.de:443/.test(box.querySelector('.sapcert-pinned').textContent));

        dom.__rufe.length = 0;
        box.querySelector('.sapcert-btn').click();
        await sleep(60);
        const probe = dom.__rufe.filter((r) => /\/cert\/probe$/.test(r.pfad));
        check('Reiter ruft den ADMIN-Endpunkt',
              probe.length === 1 && probe[0].pfad === '/api/sap/admin/cert/probe',
              probe[0] && probe[0].pfad);
        check('…mit der URL aus dem Reiter-Formular',
              !!probe[0] && probe[0].rumpf.url === 'https://s4.firma.de/sap/opu');

        // HANA nimmt Host + Port, nicht die URL.
        dom.__rufe.length = 0;
        d.getElementById('sap-hana-host').value = 'hana.firma.de';
        d.getElementById('sap-hana-port').value = '30015';
        d.getElementById('sapcert-hana').querySelector('.sapcert-btn').click();
        await sleep(60);
        const ph = dom.__rufe.filter((r) => /\/cert\/probe$/.test(r.pfad))[0];
        check('HANA-Probe sendet Host und Port',
              !!ph && ph.rumpf.host === 'hana.firma.de' && String(ph.rumpf.port) === '30015'
              && ph.rumpf.kanal === 'hana', ph && JSON.stringify(ph.rumpf));

        // Der Speichern-Knopf darf den Anker NICHT mitschreiben.
        dom.__rufe.length = 0;
        dom.window.SapManager.save();
        await sleep(60);
        const post = dom.__rufe.filter((r) => r.pfad === '/api/skills/sap/config'
                                              && r.methode === 'POST')[0];
        check('Verbindung speichern sendet keine cert_*-Felder',
              !!post && !('cert_odata' in post.rumpf) && !('cert_hana' in post.rumpf),
              post && Object.keys(post.rumpf).filter((k) => /^cert_/.test(k)).join(','));
        dom.window.close();
    }

    const bad = results.filter((r) => !r.ok);
    console.log('\n' + '='.repeat(60));
    console.log(`Ergebnis: ${results.length - bad.length} OK, ${bad.length} FAIL`);
    process.exit(bad.length ? 1 : 0);
})().catch((e) => { console.error(e); process.exit(1); });
