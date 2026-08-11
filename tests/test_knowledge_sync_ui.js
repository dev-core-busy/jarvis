#!/usr/bin/env node
/**
 * Oberflaeche der Pull-Synchronisation (Einstellungen -> Wissen).
 *
 * Geprueft wird gegen die ECHTEN Dateien (settings.html, knowledge_sync.js,
 * knowledge.js, i18n.js, app.js) – ein Test, der sein Markup selbst baut,
 * prueft nur seine eigene Annahme (Lehre aus dem Medien-Kontextmenue).
 *
 * Teil 1  Container: Reihenfolge im Reiter, Standort-Liste, Zustaende, Lizenz
 * Teil 2  Formular: pruefen -> speichern, Bearbeiten, Pausieren, Loeschen
 * Teil 3  Freigabe-Dialog (Rolle Geber) inkl. Token, Widerruf, XSS, Escape
 * Teil 4  Das 🔗-Symbol in der Ordnerliste (knowledge.js)
 * Teil 5  Verdrahtung und Texte (app.js, i18n DE+EN, CSS ohne harte Farben)
 *
 *   node tests/test_knowledge_sync_ui.js
 */

const fs = require('fs');
const path = require('path');

let ok = 0, fail = 0;
const pruefe = (b, t, d) => {
    if (b) { ok++; console.log('  ✓ ' + t); }
    else { fail++; console.log('  ✗ ' + t + (d ? ' – ' + d : '')); }
};
const abschnitt = (t) => console.log('\n=== ' + t + ' ===');

const ROOT = path.resolve(__dirname, '..');
let JSDOM;
try { JSDOM = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom').JSDOM; }
catch (e) { console.log('ABBRUCH: jsdom nicht installiert'); process.exit(2); }

const HTML = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
const SYNC = fs.readFileSync(path.join(ROOT, 'frontend/js/knowledge_sync.js'), 'utf8');
const KNOW = fs.readFileSync(path.join(ROOT, 'frontend/js/knowledge.js'), 'utf8');
const APP = fs.readFileSync(path.join(ROOT, 'frontend/js/app.js'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'frontend/css/style.css'), 'utf8');

const PEERS = [
    {
        id: 'p1', name: 'Standort 1', url: 'https://s1.example',
        target_folder: 'data/s1_technik', group_id: 'ibs', state: 'active',
        auto: true, interval: 6, unit: 'hours', token_set: true,
        remote_site: 'standort1', remote_label: 'Technik',
        fingerprint: 'sha256:aa', file_count: 12, total_bytes: 2048,
        last_sync: { ts: Math.floor(Date.now() / 1000) - 600, ok: true, added: 2, updated: 1, removed: 0 },
        last_error: '', running: false, progress: {},
        next_run: Math.floor(Date.now() / 1000) + 3600,
    },
    {
        id: 'p2', name: 'Standort 2', url: 'https://s2.example',
        target_folder: 'data/s2_vertrieb', group_id: '', state: 'paused',
        auto: false, interval: 24, unit: 'hours', token_set: true,
        file_count: 0, total_bytes: 0, last_sync: null,
        last_error: '', running: false, progress: {}, next_run: null,
    },
    {
        id: 'p3', name: 'Standort 3', url: 'https://s3.example',
        target_folder: 'data/s3_doku', group_id: '', state: 'active',
        auto: false, interval: 24, unit: 'hours', token_set: true,
        file_count: 4, total_bytes: 100, last_sync: { ts: 1, ok: false },
        last_error: 'Das Zertifikat des Standorts hat sich geändert.',
        running: false, progress: {}, next_run: null,
    },
];

/** Baut die echte Einstellungsseite mit gemockter API. */
function bauen(opt) {
    opt = opt || {};
    const dom = new JSDOM(HTML, { url: 'https://host/settings', runScripts: 'outside-only' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'T');
    const rufe = [];
    w.fetch = (url, o) => {
        o = o || {};
        rufe.push({ url: String(url), method: (o.method || 'GET').toUpperCase(),
                    body: o.body ? JSON.parse(o.body) : null });
        const j = (d, code) => Promise.resolve({
            ok: (code || 200) < 400, status: code || 200, json: () => Promise.resolve(d),
        });
        if (url.startsWith('/api/knowledge/sync/probe')) return j(opt.probe || { ok: false, error: 'Token abgelehnt' },
                                                                  (opt.probe && opt.probe.ok) ? 200 : 400);
        if (/\/api\/knowledge\/sync\/peers\/[^/]+\/run/.test(url)) return j(opt.run || { ok: true, added: 3, updated: 1, removed: 2 });
        if (url.startsWith('/api/knowledge/sync/peers')) return j({ ok: true, peer: PEERS[0] });
        if (url.startsWith('/api/knowledge/sync/site')) return j({ ok: true, site_name: 'Standort 3' });
        if (url.startsWith('/api/knowledge/sync')) return j({
            peers: opt.peers || PEERS, site_name: opt.site || '', hostname: 'jarvis-dev',
            license_ok: opt.license !== false, license_reason: opt.license === false
                ? 'Die Synchronisation mit anderen Standorten ist der ENTERPRISE-Lizenz vorbehalten.' : '',
            token_prefix: 'JARVIS-KBS-1.', units: ['minutes', 'hours', 'days'],
            min_interval_seconds: 300, status: { running: [], progress: {} },
        });
        if (url.startsWith('/api/knowledge/shares')) {
            if ((o.method || 'GET') === 'GET') return j({ shares: opt.shares || [], site_name: 'Standort 1' });
            if (o.method === 'POST' && /rotate/.test(url)) return j({ ok: true, share: Object.assign({}, (opt.shares || [])[0], { token: 'JARVIS-KBS-1.s1.NEU' }) });
            if (o.method === 'POST') return j({ ok: true, share: {
                id: 's1', folder: 'data/knowledge/technik', label: 'Technik',
                token: 'JARVIS-KBS-1.s1.geheim', enabled: true, pulls: [] } });
            if (o.method === 'PATCH') return j({ ok: true, share: Object.assign({}, (opt.shares || [])[0], { enabled: false }) });
            if (o.method === 'DELETE') return j({ ok: true });
        }
        if (url.startsWith('/api/knowledge/groups')) return j({ groups: [
            { id: 'ibs', name: 'IBS' }, { id: 'dc', name: 'DC-Pathos' }] });
        return j({});
    };
    w.eval(I18N);
    w.eval(SYNC);
    return { dom, w, rufe, KS: w.KnowledgeSync };
}

const warten = () => new Promise(r => setTimeout(r, 25));

(async () => {

// ── Teil 1: Container ───────────────────────────────────────────────────────
abschnitt('Teil 1: Container im Wissen-Reiter');
{
    const { dom, w, KS } = bauen();
    const d = w.document;
    const hdr = d.getElementById('kb-sect-sync-hdr');
    const body = d.getElementById('kb-sect-sync-body');
    pruefe(!!hdr && !!body, 'Klapp-Container vorhanden');
    pruefe(body.style.display === 'none', 'startet zugeklappt');
    // Reihenfolge: Ordner -> Pull-Synchronisation -> WebDAV
    const alle = [...d.querySelectorAll('#settings-tab-knowledge .kb-section-header')]
        .map(e => e.id);
    const iO = alle.indexOf('kb-sect-folder-hdr');
    const iS = alle.indexOf('kb-sect-sync-hdr');
    const iW = alle.indexOf('kb-sect-webdav-hdr');
    pruefe(iO >= 0 && iS === iO + 1 && iW === iS + 1,
        'sitzt zwischen „Ordner" und „WebDAV-Server"', alle.join(','));
    pruefe(!!d.getElementById('kbsync-share-modal'), 'Freigabe-Dialog im Markup');
    pruefe(d.getElementById('kbsync-share-modal').classList.contains('open') === false,
        'Freigabe-Dialog ist geschlossen');

    await KS.onShow(); await warten();
    const karten = d.querySelectorAll('#kbsync-peer-list .kbsync-card');
    pruefe(karten.length === 3, 'drei Standorte gerendert', String(karten.length));
    pruefe(d.getElementById('kbsync-count').textContent.trim() === '(3)', 'Zaehler in der Kopfzeile');
    const pillen = [...d.querySelectorAll('.kbsync-pill')].map(e => e.className);
    pruefe(pillen[0].includes('kbsync-ok'), 'aktiver Standort: gruene Pille');
    pruefe(pillen[1].includes('kbsync-paused'), 'pausierter Standort: graue Pille');
    pruefe(pillen[2].includes('kbsync-error'), 'fehlerhafter Standort: rote Pille');
    const texte = [...d.querySelectorAll('.kbsync-pill')].map(e => e.textContent.trim());
    pruefe(texte.every(t => t.length > 2),
        'Zustand steht auch als TEXT da (Farbe allein ist keine Information)', texte.join('|'));
    pruefe(karten[1].className.includes('is-paused'), 'pausierte Karte ist abgeschwaecht');
    pruefe(d.querySelector('#kbsync-peer-list').textContent.includes('data/s1_technik'),
        'Zielordner wird genannt');
    pruefe(d.querySelector('#kbsync-peer-list').textContent.includes('Technik'),
        'Beschriftung des Gebers wird genannt');
    pruefe(karten[2].querySelector('.kbsync-err').textContent.includes('Zertifikat'),
        'Fehler wird im Klartext gezeigt');
    pruefe(karten[1].textContent.includes('noch nie'), 'nie gelaufen wird als solches benannt');
    pruefe(karten[0].textContent.includes('nächster') || karten[0].textContent.includes('next'),
        'naechster Lauf steht an der Karte');
    pruefe(karten[2].textContent.includes('nur manuell'), 'ohne Automatik: „nur manuell"');
    pruefe(d.getElementById('kbsync-license').style.display === 'none',
        'kein Lizenz-Hinweis bei gueltiger Lizenz');
    pruefe(d.getElementById('kbsync-add-btn').disabled === false, 'Hinzufuegen ist moeglich');
    dom.window.close();
}
{
    const { dom, w, KS } = bauen({ license: false });
    await KS.onShow(); await warten();
    const d = w.document;
    pruefe(d.getElementById('kbsync-license').style.display !== 'none',
        'ohne ENTERPRISE: Hinweis sichtbar');
    pruefe(d.getElementById('kbsync-license').textContent.includes('ENTERPRISE'),
        'Hinweis nennt die Lizenzstufe');
    pruefe(d.getElementById('kbsync-add-btn').disabled === true,
        'ohne ENTERPRISE: Hinzufuegen gesperrt');
    pruefe([...d.querySelectorAll('[data-kbsync="run"]')].every(b => b.disabled),
        'ohne ENTERPRISE: „Jetzt holen" gesperrt');
    dom.window.close();
}
{
    const { dom, w, KS } = bauen({ peers: [] });
    await KS.onShow(); await warten();
    pruefe(w.document.getElementById('kbsync-peer-list').textContent.includes('Noch kein Standort'),
        'leere Liste sagt es ausdruecklich');
    pruefe(w.document.getElementById('kbsync-count').textContent === '',
        'kein Zaehler bei leerer Liste');
    dom.window.close();
}

// ── Teil 2: Formular ────────────────────────────────────────────────────────
abschnitt('Teil 2: Standort anlegen, bearbeiten, loeschen');
{
    const { dom, w, rufe, KS } = bauen();
    const d = w.document;
    await KS.onShow(); await warten();
    d.getElementById('kbsync-add-btn').click(); await warten();
    pruefe(d.getElementById('kbsync-form').style.display !== 'none', 'Formular oeffnet');
    pruefe(d.getElementById('kbsync-step2').style.display === 'none',
        'zweiter Schritt bleibt zu, solange nicht geprueft ist');
    pruefe(d.getElementById('kbsync-add-btn').style.display === 'none',
        'Hinzufuegen-Knopf verschwindet solange');
    pruefe([...d.getElementById('kbsync-f-group').options].length === 3,
        'Gruppen-Pulldown gefuellt (inkl. „keine Gruppe")');
    pruefe(d.getElementById('kbsync-f-group').options[0].value === '',
        'erste Wahl ist „keine Gruppe"');

    // Speichern ohne Pruefung
    d.getElementById('kbsync-save-btn').click(); await warten();
    pruefe(d.getElementById('kbsync-form-err').textContent.includes('prüfen'),
        'Speichern ohne Pruefung wird verweigert');
    pruefe(!rufe.some(r => r.method === 'POST' && r.url === '/api/knowledge/sync/peers'),
        'und sendet nichts');

    // Pruefen ohne Eingabe
    d.getElementById('kbsync-probe-btn').click(); await warten();
    pruefe(d.getElementById('kbsync-form-err').textContent.length > 0,
        'Pruefen ohne Adresse/Token wird verweigert');

    // Pruefen mit Fehlschlag
    d.getElementById('kbsync-f-url').value = 'https://s1.example';
    d.getElementById('kbsync-f-token').value = 'JARVIS-KBS-1.a.b';
    d.getElementById('kbsync-probe-btn').click(); await warten();
    pruefe(d.getElementById('kbsync-probe-result').className.includes('is-bad'),
        'fehlgeschlagene Pruefung wird als solche markiert');
    pruefe(d.getElementById('kbsync-probe-result').textContent.includes('abgelehnt'),
        'Grund der Gegenstelle wird gezeigt');
    pruefe(d.getElementById('kbsync-step2').style.display === 'none',
        'nach Fehlschlag bleibt der zweite Schritt zu');
    pruefe(d.getElementById('kbsync-probe-btn').disabled === false,
        'Knopf ist danach wieder bedienbar');
    dom.window.close();
}
{
    const { dom, w, rufe, KS } = bauen({ probe: {
        ok: true, url: 'https://s1.example', fingerprint: 'sha256:abc123',
        remote_site: 'standort1', remote_label: 'Technik', folder_name: 'technik',
        file_count: 12, total_bytes: 4096, suggest_folder: 'data/standort1_technik' } });
    const d = w.document;
    await KS.onShow(); await warten();
    d.getElementById('kbsync-add-btn').click(); await warten();
    d.getElementById('kbsync-f-url').value = 's1.example';
    d.getElementById('kbsync-f-token').value = 'JARVIS-KBS-1.s1.geheim';
    d.getElementById('kbsync-probe-btn').click(); await warten();
    pruefe(d.getElementById('kbsync-probe-result').className.includes('is-good'),
        'erfolgreiche Pruefung wird als solche markiert');
    pruefe(d.getElementById('kbsync-probe-result').textContent.includes('sha256:abc123'),
        'Fingerabdruck wird VOR dem Speichern gezeigt');
    pruefe(d.getElementById('kbsync-probe-result').textContent.includes('12'),
        'Umfang der Freigabe wird gezeigt');
    pruefe(d.getElementById('kbsync-step2').style.display !== 'none', 'zweiter Schritt offen');
    pruefe(d.getElementById('kbsync-f-folder').value === 'data/standort1_technik',
        'Zielordner wird vorbelegt');
    pruefe(d.getElementById('kbsync-f-name').value === 'standort1', 'Bezeichnung wird vorbelegt');

    d.getElementById('kbsync-f-group').value = 'ibs';
    d.getElementById('kbsync-f-auto').checked = true;
    d.getElementById('kbsync-f-interval').value = '30';
    d.getElementById('kbsync-f-unit').value = 'minutes';
    d.getElementById('kbsync-save-btn').click(); await warten();
    const post = rufe.find(r => r.method === 'POST' && r.url === '/api/knowledge/sync/peers');
    pruefe(!!post, 'Standort wird angelegt');
    pruefe(post && post.body.fingerprint === 'sha256:abc123',
        'der geprueefte Fingerabdruck wird mitgesendet (Bindung)');
    pruefe(post && post.body.target_folder === 'data/standort1_technik', 'Zielordner im Aufruf');
    pruefe(post && post.body.group_id === 'ibs', 'Wissensgruppe im Aufruf');
    pruefe(post && post.body.auto === true && post.body.interval === 30
           && post.body.unit === 'minutes', 'Automatik samt Intervall im Aufruf');
    pruefe(post && post.body.token === 'JARVIS-KBS-1.s1.geheim', 'Token im Aufruf');
    pruefe(d.getElementById('kbsync-form').style.display === 'none',
        'Formular schliesst nach dem Speichern');
    dom.window.close();
}
{
    // Bearbeiten
    const { dom, w, rufe, KS } = bauen();
    const d = w.document;
    await KS.onShow(); await warten();
    d.querySelector('[data-kbsync="edit"][data-id="p1"]').click(); await warten();
    pruefe(d.getElementById('kbsync-f-folder').disabled === true,
        'beim Bearbeiten ist der Zielordner gesperrt (kein Umzug des Spiegels)');
    pruefe(d.getElementById('kbsync-f-token').value === ''
           && /unver/.test(d.getElementById('kbsync-f-token').placeholder),
        'Token-Feld leer mit Hinweis „unverändert"');
    pruefe(d.getElementById('kbsync-f-group').value === 'ibs', 'Gruppe ist vorausgewaehlt');
    pruefe(d.getElementById('kbsync-f-interval').value === '6', 'Intervall ist vorbelegt');
    pruefe(d.getElementById('kbsync-step2').style.display !== 'none',
        'beim Bearbeiten sind die Felder direkt sichtbar');
    d.getElementById('kbsync-f-name').value = 'Werk 1';
    d.getElementById('kbsync-save-btn').click(); await warten();
    const patch = rufe.find(r => r.method === 'PATCH' && r.url.includes('/sync/peers/p1'));
    pruefe(!!patch, 'Aenderung wird per PATCH gesendet');
    pruefe(patch && patch.body.name === 'Werk 1', 'neuer Name im Aufruf');
    pruefe(patch && !('target_folder' in patch.body), 'target_folder wird NICHT mitgesendet');
    pruefe(patch && !('fingerprint' in patch.body),
        'ohne erneute Pruefung bleibt die Zertifikats-Bindung unangetastet');
    dom.window.close();
}
{
    // Pausieren und Loeschen
    const { dom, w, rufe, KS } = bauen();
    const d = w.document;
    await KS.onShow(); await warten();
    d.querySelector('[data-kbsync="toggle"][data-id="p1"]').click(); await warten();
    let p = rufe.find(r => r.method === 'PATCH');
    pruefe(p && p.body.state === 'paused', 'aktiver Standort wird pausiert');
    d.querySelector('[data-kbsync="toggle"][data-id="p2"]').click(); await warten();
    p = rufe.filter(r => r.method === 'PATCH').pop();
    pruefe(p && p.body.state === 'active', 'pausierter Standort wird fortgesetzt');

    const fragen = [];
    w.confirm = (t) => { fragen.push(t); return true; };
    d.querySelector('[data-kbsync="del"][data-id="p1"]').click(); await warten();
    pruefe(fragen.length === 2, 'zwei Rueckfragen: Eintrag und Daten getrennt', String(fragen.length));
    pruefe(/Kopie bleibt erhalten/.test(fragen[0]),
        'erste Frage sagt, dass die Kopie bleibt');
    pruefe(/löschen/.test(fragen[1]), 'zweite Frage betrifft ausdruecklich die Daten');
    const del = rufe.find(r => r.method === 'DELETE');
    pruefe(del && del.url.includes('remove_data=1'), 'bei Ja wird remove_data gesetzt');

    const rufe2 = [];
    w.confirm = (t) => fragen.push(t) && false;   // zweite Frage: Abbrechen
    dom.window.close();
}
{
    const { dom, w, rufe, KS } = bauen();
    const d = w.document;
    await KS.onShow(); await warten();
    let n = 0;
    w.confirm = () => { n++; return n === 1; };    // Eintrag ja, Daten nein
    d.querySelector('[data-kbsync="del"][data-id="p1"]').click(); await warten();
    const del = rufe.find(r => r.method === 'DELETE');
    pruefe(del && !del.url.includes('remove_data'),
        'wird die zweite Frage abgebrochen, bleibt die Kopie liegen');
    dom.window.close();
}
{
    // Jetzt synchronisieren
    const { dom, w, rufe, KS } = bauen({ run: { ok: true, added: 3, updated: 1, removed: 2,
                                                error_count: 1, errors: ['x'], skipped_remote: 5 } });
    const d = w.document;
    await KS.onShow(); await warten();
    d.querySelector('[data-kbsync="run"][data-id="p1"]').click(); await warten();
    pruefe(rufe.some(r => r.method === 'POST' && r.url === '/api/knowledge/sync/peers/p1/run'),
        'Lauf wird angestossen');
    const meld = d.getElementById('kb-notification');
    pruefe(meld.textContent.includes('3') && meld.textContent.includes('2'),
        'Ergebnis wird gemeldet', meld.textContent);
    pruefe(/übersprungen/.test(meld.textContent),
        'uebersprungene Dateien werden GENANNT, nicht verschwiegen');
    pruefe(/Grenze/.test(meld.textContent),
        'Kuerzung durch den Geber wird genannt');
    pruefe(meld.className.includes('kb-notification-success'),
        'Erfolgsmeldung nutzt die vorhandene Klasse');
    dom.window.close();
}
{
    const { dom, w, KS } = bauen({ run: { ok: false, error: 'Freigabe entzogen oder Token ungültig' } });
    const d = w.document;
    await KS.onShow(); await warten();
    d.querySelector('[data-kbsync="run"][data-id="p1"]').click(); await warten();
    const meld = d.getElementById('kb-notification');
    pruefe(meld.textContent.includes('entzogen'), 'Fehlschlag wird im Klartext gemeldet');
    pruefe(meld.className.includes('kb-notification-error'), 'als Fehler gekennzeichnet');
    dom.window.close();
}

// ── Teil 3: Freigabe-Dialog ─────────────────────────────────────────────────
abschnitt('Teil 3: Freigabe-Dialog (Rolle Geber)');
{
    const { dom, w, rufe, KS } = bauen({ shares: [] });
    const d = w.document;
    await KS.openShare('data/knowledge/technik'); await warten();
    const modal = d.getElementById('kbsync-share-modal');
    pruefe(modal.classList.contains('open'), 'Dialog oeffnet ueber die Klasse „open"');
    pruefe(d.getElementById('kbsync-share-body').textContent.includes('data/knowledge/technik'),
        'der betroffene Ordner steht im Dialog');
    pruefe(!!d.getElementById('kbsync-share-create'), 'ohne Freigabe: Knopf zum Freigeben');
    pruefe(d.getElementById('kbsync-share-label').value === 'technik',
        'Beschriftung ist mit dem Ordnernamen vorbelegt');
    pruefe(d.getElementById('kbsync-share-body').textContent.includes('Unterordner'),
        'Hinweis nennt, dass der ganze Unterbaum freigegeben wird');
    d.getElementById('kbsync-share-create').click(); await warten();
    const post = rufe.find(r => r.method === 'POST' && r.url === '/api/knowledge/shares');
    pruefe(post && post.body.folder === 'data/knowledge/technik', 'Freigabe wird angelegt');
    pruefe(d.getElementById('kbsync-share-token').value === 'JARVIS-KBS-1.s1.geheim',
        'Token wird direkt danach angezeigt');
    pruefe(d.getElementById('kbsync-share-body').textContent.includes('Bisher hat kein Standort'),
        'leeres Abruf-Protokoll wird benannt');

    // Escape schliesst
    d.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    pruefe(!modal.classList.contains('open'), 'Escape schliesst den Dialog');
    dom.window.close();
}
{
    const share = {
        id: 's1', folder: 'data/knowledge/technik', label: 'Technik <b>fett</b>',
        token: 'JARVIS-KBS-1.s1.geheim', enabled: true,
        pulls: [{ ts: 1754900000, site: 'standort3', ip: '10.0.0.9', files: 12, bytes: 2048 },
                { ts: 1754800000, site: '<img src=x onerror=alert(1)>', ip: '10.0.0.8', files: 1, bytes: 10 }],
    };
    const { dom, w, rufe, KS } = bauen({ shares: [share] });
    const d = w.document;
    await KS.openShare('data/knowledge/technik'); await warten();
    const body = d.getElementById('kbsync-share-body');
    pruefe(body.textContent.includes('JARVIS-KBS-1.s1.geheim') === false,
        'das Token steht in einem Feld, nicht als Text');
    pruefe(d.getElementById('kbsync-share-token').value === 'JARVIS-KBS-1.s1.geheim',
        'Token ist zum Kopieren da');
    pruefe(d.getElementById('kbsync-share-token').readOnly, 'Token-Feld ist nur lesbar');
    pruefe(d.querySelectorAll('.kbsync-pulls tbody tr').length === 2,
        'Abruf-Protokoll zeigt beide Zeilen');
    pruefe(body.textContent.includes('standort3'), 'ziehender Standort steht im Protokoll');
    pruefe(body.textContent.includes('10.0.0.9'), 'Adresse steht im Protokoll');
    pruefe(body.querySelector('img') === null,
        'Fremdtext im Protokoll wird NICHT als HTML ausgefuehrt');
    pruefe(body.innerHTML.includes('&lt;b&gt;fett'), 'Beschriftung wird escaped');

    // Widerruf mit Rueckfrage
    let gefragt = '';
    w.confirm = (t) => { gefragt = t; return false; };
    d.getElementById('kbsync-share-revoke').click(); await warten();
    pruefe(/Kopie bleibt/.test(gefragt),
        'Widerruf-Frage sagt, dass die Kopie beim Nehmer bleibt');
    pruefe(!rufe.some(r => r.method === 'DELETE'), 'Abbrechen sendet nichts');
    w.confirm = () => true;
    d.getElementById('kbsync-share-revoke').click(); await warten();
    pruefe(rufe.some(r => r.method === 'DELETE' && r.url.includes('/shares/s1')),
        'Widerruf wird gesendet');
    pruefe(!!d.getElementById('kbsync-share-create'),
        'nach dem Widerruf steht wieder „Freigeben" da');
    dom.window.close();
}
{
    const share = { id: 's1', folder: 'data/knowledge/technik', label: 'T',
                    token: 'JARVIS-KBS-1.s1.alt', enabled: true, pulls: [] };
    const { dom, w, rufe, KS } = bauen({ shares: [share] });
    const d = w.document;
    await KS.openShare('data/knowledge/technik'); await warten();
    w.confirm = () => true;
    d.getElementById('kbsync-share-rotate').click(); await warten();
    pruefe(rufe.some(r => r.url.includes('/shares/s1/rotate')), 'Token-Rotation wird gesendet');
    pruefe(d.getElementById('kbsync-share-token').value.endsWith('NEU'),
        'neues Token wird sofort angezeigt');
    d.getElementById('kbsync-share-toggle').click(); await warten();
    const patch = rufe.find(r => r.method === 'PATCH' && r.url.includes('/shares/s1'));
    pruefe(patch && patch.body.enabled === false, 'Pausieren sendet nur enabled');
    pruefe(patch && Object.keys(patch.body).length === 1,
        'und NICHTS anderes (kein Formularstand)');
    dom.window.close();
}

// ── Teil 4: Symbol in der Ordnerliste ───────────────────────────────────────
abschnitt('Teil 4: 🔗-Symbol in der Ordnerliste');
{
    const { dom, w } = bauen();
    w.eval(KNOW);
    const km = w.knowledgeManager;
    const wurzel = km._folderNodeHtml('data/knowledge', true, true, false);
    const unter = km._folderNodeHtml('data/knowledge/technik', true, false, false);
    pruefe(wurzel.includes('kb-btn-share'), 'Wurzelordner hat das Freigabe-Symbol');
    pruefe(unter.includes('kb-btn-share'), 'Unterordner hat es ebenfalls');
    pruefe((wurzel.match(/kb-btn-remove/g) || []).length === 4,
        'Wurzelzeile hat jetzt vier Symbole', String((wurzel.match(/kb-btn-remove/g) || []).length));
    pruefe((unter.match(/kb-btn-remove/g) || []).length === 5,
        'Unterordner-Zeile hat fuenf Symbole', String((unter.match(/kb-btn-remove/g) || []).length));
    pruefe(wurzel.includes('KnowledgeSync&&window.KnowledgeSync.openShare'),
        'Klick oeffnet den Freigabe-Dialog');
    pruefe(wurzel.includes('event.stopPropagation()'),
        'Klick klappt die Dateiliste NICHT auf');
    pruefe(!wurzel.includes('is-shared'), 'ohne Freigabe kein Zustand am Symbol');
    km._sharedFolders = new Set(['data/knowledge']);
    const geteiltHtml = km._folderNodeHtml('data/knowledge', true, true, false);
    pruefe(geteiltHtml.includes('is-shared'),
        'freigegebener Ordner wird am Symbol markiert');
    // Gemeldet 2026-08-11: freigegebene Ordner sollen an einem EIGENEN Symbol
    // erkennbar sein, nicht nur an der Farbe des Knopfes am rechten Rand.
    pruefe(geteiltHtml.includes('kb-share-mark') && geteiltHtml.includes('⇄'),
        'freigegebener Ordner traegt eine Marke hinter dem Namen');
    pruefe(geteiltHtml.indexOf('kb-folder-path') < geteiltHtml.indexOf('kb-share-mark')
           && geteiltHtml.indexOf('kb-share-mark') < geteiltHtml.indexOf('kb-folder-arrow'),
        'die Marke steht zwischen Name und Aufklapp-Pfeil');
    pruefe(/kb-share-mark[^>]*title="[^"]{10,}/.test(geteiltHtml),
        'die Marke erklaert sich per Titel');
    pruefe(geteiltHtml.includes('🗂️') === false && geteiltHtml.includes('📁'),
        'das Ordner-Symbol bleibt unveraendert (es traegt eine eigene Aussage)');
    pruefe(!km._folderNodeHtml('data/handbuecher', true, true, false).includes('kb-share-mark'),
        'ein nicht freigegebener Ordner traegt keine Marke');
    pruefe(!km._folderNodeHtml('data/knowledge/technik', true, false, false).includes('is-shared'),
        'Unterordner erbt die Markierung nicht (er hat keine eigene Freigabe)');
    // Reihenfolge: Freigabe VOR dem Loeschen – ✕ bleibt aussen
    pruefe(wurzel.indexOf('kb-btn-share') < wurzel.lastIndexOf('✕'),
        'das ✕ bleibt das letzte Symbol');
    dom.window.close();
}

// ── Teil 4a: Die Ordnerliste darf NICHT auf die Freigaben warten ────────────
// GEMELDET 2026-08-11: „Einstellungen → Wissen → Ordner – Liste wird nicht mehr
// geladen." Ursache war ein `await` auf /api/knowledge/shares vor dem Zeichnen:
// der Reiter feuert beim Oeffnen mehrere Anfragen, und /api/knowledge/mounts
// brauchte auf DEV 20 s (totes CIFS-Mount) – die Liste blieb auf „Lädt…".
abschnitt('Teil 4a: Ordnerliste zeichnet sofort, Marken kommen nach');
{
    const { dom, w } = bauen();
    const d = w.document;
    // /shares antwortet ABSICHTLICH spaet – wie hinter einer langsamen Anfrage.
    let sharesAufloesen;
    const echtesFetch = w.fetch;
    w.fetch = (u, o) => {
        if (String(u).startsWith('/api/knowledge/shares')) {
            return new Promise(res => { sharesAufloesen = () => res({
                ok: true, status: 200, json: () => Promise.resolve({ shares: [
                    { id: 's1', folder: 'data/community', label: 'c', token: 'T', enabled: true, pulls: [] }] }),
            }); });
        }
        if (String(u).startsWith('/api/knowledge/stats')) {
            return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({
                total_files: 2, indexed_files: 2, total_size_bytes: 10,
                folders: [{ path: 'data/knowledge', exists: true, has_children: false },
                          { path: 'data/community', exists: true, has_children: false }] }) });
        }
        return echtesFetch(u, o);
    };
    w.eval(KNOW);
    const km = w.knowledgeManager;
    await km.fetchStats();
    await warten();
    const liste = d.getElementById('kb-folder-list');
    pruefe(liste.querySelectorAll('.kb-folder-item').length === 2,
        'die Liste steht, OBWOHL die Freigaben noch nicht geantwortet haben',
        liste.textContent.trim().slice(0, 40));
    pruefe(liste.querySelectorAll('.kb-share-mark').length === 0,
        'noch keine Marke (die Antwort fehlt ja)');
    sharesAufloesen();
    await warten(); await warten();
    pruefe(liste.querySelectorAll('.kb-share-mark').length === 1,
        'die Marke wird nachgetragen, sobald die Antwort da ist');
    const zeile = liste.querySelector('.kb-folder-item[data-path="data/community"]');
    pruefe(!!zeile.querySelector('.kb-folder-nameflex .kb-share-mark'),
        'die nachgetragene Marke sitzt im Namensbereich (nicht am rechten Rand)');
    pruefe(zeile.querySelector('.kb-btn-share').classList.contains('is-shared'),
        'auch der 🔗-Knopf wird nachgezogen');
    // Idempotent: ein zweiter Durchlauf darf keine zweite Marke erzeugen
    km._markShared(); km._markShared();
    pruefe(liste.querySelectorAll('.kb-share-mark').length === 1,
        'mehrfaches Nachtragen erzeugt keine zweite Marke');
    // Widerruf: Marke muss wieder verschwinden, ohne die Liste neu zu bauen
    km._sharedFolders = new Set();
    km._markShared();
    pruefe(liste.querySelectorAll('.kb-share-mark').length === 0,
        'nach dem Widerruf verschwindet die Marke');
    pruefe(!zeile.querySelector('.kb-btn-share').classList.contains('is-shared'),
        'und der Knopf ist wieder neutral');
    pruefe(liste.querySelectorAll('.kb-folder-item').length === 2,
        'die Liste selbst bleibt dabei unangetastet');
    dom.window.close();
}
{
    // Der Aufruf nach dem Freigabe-Dialog muss eine Methode treffen, DIE ES GIBT:
    // `loadStats` existiert nicht, mit `?.()` blieb das still wirkungslos.
    pruefe(!/knowledgeManager\.loadStats/.test(SYNC),
        'kein Aufruf einer nicht existierenden Methode (loadStats)');
    pruefe(/refreshShareMarks/.test(SYNC) && /refreshShareMarks\(\)/.test(KNOW),
        'nach dem Freigabe-Dialog werden die Marken aufgefrischt');
    pruefe(/fetchStats/.test(KNOW), 'die Lade-Methode heisst fetchStats');
    // Cache-Buster: ohne Hochzaehlen behaelt der Browser die kaputte Fassung.
    const v = /knowledge\.js\?v=(\d+)/.exec(HTML);
    const vs = /knowledge_sync\.js\?v=(\d+)/.exec(HTML);
    pruefe(v && Number(v[1]) >= 92, 'knowledge.js hat einen frischen Cache-Buster', v && v[1]);
    pruefe(vs && Number(vs[1]) >= 2, 'knowledge_sync.js hat einen frischen Cache-Buster', vs && vs[1]);
}

// ── Teil 4b: Funktionsbeschreibung (❓, druckbar) ────────────────────────────
abschnitt('Teil 4b: Funktionsbeschreibung und Druckansicht');
{
    const { dom, w, KS } = bauen();
    const d = w.document;
    const modal = d.getElementById('kbsync-info-modal');
    const btn = d.getElementById('kbsync-info-btn');
    pruefe(!!btn, '❓-Knopf sitzt in der Kopfzeile des Containers');
    pruefe(btn.closest('#kb-sect-sync-hdr') !== null, 'und zwar in DIESER Kopfzeile');
    pruefe(/stopPropagation/.test(btn.getAttribute('onclick') || ''),
        'der Klick klappt den Abschnitt nicht zu');
    pruefe(!!modal && modal.classList.contains('is-print-doc'),
        'Dialog ist als druckbare Doku markiert');
    pruefe(modal.parentElement === d.body,
        'Dialog ist direktes Kind von body (Voraussetzung der Druckregel)');
    pruefe(!modal.classList.contains('open'), 'startet geschlossen');

    KS.openInfo(true);
    pruefe(modal.classList.contains('open'), 'öffnet über die Klasse „open"');
    const txt = modal.textContent;
    for (const begriff of ['Einbahnstraße', 'Token', 'Zertifikat', 'Spiegel',
                           'ENTERPRISE', 'Prüfsumme', 'Manifest'.replace('Manifest', 'Dateiliste'),
                           'Wissensgruppen sind in Jarvis']) {
        pruefe(txt.includes(begriff), `Doku behandelt: ${begriff}`);
    }
    pruefe(/1\. Übersicht/.test(txt) && /9\. Für Administratoren/.test(txt),
        'alle neun Abschnitte sind vorhanden');
    const svg = modal.querySelector('svg.kbsync-svg');
    pruefe(!!svg, 'grafische Übersicht ist ein Inline-SVG');
    pruefe(svg.getAttribute('viewBox') && !svg.getAttribute('width'),
        'SVG skaliert über viewBox statt fester Breite');
    pruefe(!!svg.getAttribute('role') && !!svg.getAttribute('aria-label'),
        'SVG hat eine Textalternative');
    pruefe(!/#[0-9a-fA-F]{3,6}\b/.test(svg.outerHTML),
        'im SVG stehen keine harten Farben (nur Klassen)');
    pruefe(svg.querySelectorAll('rect').length >= 12 && svg.querySelectorAll('line').length >= 8,
        'die Zeichnung hat Kästen UND Pfeile');
    pruefe(modal.querySelectorAll('table.kbsync-doc-tab').length === 3,
        'drei Tabellen (Grenzen, Meldungen, Ablage)');

    // Drucken: Klasse setzen, drucken, Klasse ZURÜCKNEHMEN
    let gedruckt = 0;
    w.print = () => { gedruckt++; };
    KS.drucken();
    pruefe(gedruckt === 1, 'Druckdialog wird geöffnet');
    pruefe(d.body.classList.contains('printing-doc'), 'Druckklasse ist während des Drucks gesetzt');
    w.dispatchEvent(new w.Event('afterprint'));
    pruefe(!d.body.classList.contains('printing-doc'),
        'Druckklasse wird danach entfernt (sonst ist die nächste Seite leer)');
    // Scheitert window.print, darf die Klasse ebenfalls nicht hängenbleiben.
    w.print = () => { throw new Error('kein Drucker'); };
    KS.drucken();
    pruefe(!d.body.classList.contains('printing-doc'),
        'auch bei einem Fehler bleibt die Druckklasse nicht stehen');

    // Escape: die Doku liegt ÜBER dem Freigabe-Dialog und muss zuerst weichen
    KS.openInfo(true);
    d.getElementById('kbsync-share-modal').classList.add('open');
    d.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    pruefe(!modal.classList.contains('open')
           && d.getElementById('kbsync-share-modal').classList.contains('open'),
        'Escape schliesst zuerst die Doku, nicht den Dialog darunter');
    d.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    pruefe(!d.getElementById('kbsync-share-modal').classList.contains('open'),
        'das zweite Escape schliesst den Freigabe-Dialog');
    dom.window.close();
}

// Druck-CSS: generisch statt einer weiteren Kopie je Modal
{
    const druck = CSS.slice(CSS.indexOf('@media print'));
    pruefe(/body\.printing-doc > \*:not\(\.is-print-doc\)/.test(druck),
        'generische Druckregel vorhanden (nicht die sechste Kopie)');
    pruefe(/color-scheme:\s*light\s*!important/.test(druck),
        'color-scheme wird auf light gezwungen – sonst druckt der Browser die Seite dunkel');
    pruefe(/body\.printing-doc \.is-print-doc \.btn-icon[^}]*display:\s*none/s.test(druck),
        'Steuer-Knöpfe werden nicht mitgedruckt');
    pruefe(/\.kbsync-doc-fig\s*\{[^}]*break-inside:\s*avoid/s.test(druck),
        'die Grafik wird nicht über zwei Seiten getrennt');
    pruefe(/\.is-print-doc h3[^}]*break-after:\s*avoid/s.test(druck),
        'eine Überschrift bleibt bei ihrem Abschnitt');
    pruefe(/\.kbsync-svg text\s*\{\s*fill:\s*#000/.test(druck),
        'die Zeichnung wird für den Druck schwarz auf weiss gestellt');
}

// ── Teil 4c: Audit-Log der Root-Freigaben steht unter seinem Knopf ──────────
abschnitt('Teil 4c: Audit-Log der Root-Freigaben (gemeldete Position)');
{
    const SEC = fs.readFileSync(path.join(ROOT, 'frontend/js/security_incidents.js'), 'utf8');
    const iBtn = HTML.indexOf('id="sec-broker-audit-btn"');
    const iBox = HTML.indexOf('id="sec-broker-audit"');
    const iListe = HTML.indexOf('id="sec-broker-list"');
    pruefe(iBtn > 0 && iBox > iBtn, 'der Kasten steht NACH seinem Knopf');
    pruefe(iBox < iListe,
        'der Kasten steht VOR der Freigabeliste (die wird mehrere Seiten lang)');
    pruefe(/max-height:260px;overflow-y:auto/.test(SEC),
        'der Kasten scrollt intern und schiebt die Liste nicht weg');
    pruefe(/_sichtbarScrollen/.test(SEC), 'der geoeffnete Kasten wird sichtbar gescrollt');
    // Auf den AUFRUF pruefen, nicht auf das Wort: der Kommentar im Modul begruendet,
    // warum es NICHT benutzt wird – ein Wort-Test schlaegt daran falsch an
    // (dieselbe Falle wie beim Prompt-Waechter am 2026-08-10).
    pruefe(!/scrollIntoView\s*\(/.test(SEC),
        'kein scrollIntoView-Aufruf – das reisst den angeklickten Knopf aus dem Bild');
    pruefe(/Math\.min\(r\.bottom - unten, r\.top - oben\)/.test(SEC),
        'gescrollt wird nur so weit wie noetig, nie ueber die Oberkante');
    pruefe(/_auditBtnText/.test(SEC) && /broker_audit_hide/.test(SEC),
        'die Knopfbeschriftung folgt dem Zustand');
    for (const k of ['security.broker_audit_hide', 'kbsync.share_mark_title']) {
        pruefe((I18N.match(new RegExp("'" + k.replace('.', '\\.') + "':", 'g')) || []).length === 2,
            `${k} liegt in DE und EN vor`);
    }
    pruefe(/\.kb-share-mark\s*\{[^}]*var\(--accent\)/s.test(CSS),
        'die Marke nutzt die Akzent-Variable');
}

// ── Teil 5: Verdrahtung, Texte, CSS ─────────────────────────────────────────
abschnitt('Teil 5: Verdrahtung, Texte, CSS');
pruefe(/kb-sect-sync-hdr[^\n]*kb-sect-sync-body/.test(APP),
    'app.js kennt den Klapp-Zustand des neuen Containers');
pruefe(APP.includes('window.KnowledgeSync.onShow()'),
    'app.js ruft KnowledgeSync.onShow beim Reiter-Wechsel');
// Auf das SCRIPT-Tag pruefen, nicht auf den Dateinamen: die Doku im Dialog
// nennt `data/knowledge_sync.json`, und das enthaelt „knowledge_sync.js" als
// Praefix – der lockere Vergleich schlug dadurch faelschlich an.
pruefe(/<script src="\/static\/js\/knowledge_sync\.js/.test(HTML), 'Skript ist eingebunden');
pruefe(HTML.indexOf('<script src="/static/js/knowledge.js')
       < HTML.indexOf('<script src="/static/js/knowledge_sync.js'),
    'knowledge_sync.js laedt NACH knowledge.js');

// i18n: jeder benutzte Schluessel existiert in DE und EN
const benutzt = new Set();
for (const m of SYNC.matchAll(/T\('(kbsync\.[a-z_0-9]+)'/g)) benutzt.add(m[1]);
for (const m of HTML.matchAll(/data-i18n(?:-[a-z]+)?="(kbsync\.[a-z_0-9]+)"/g)) benutzt.add(m[1]);
for (const m of KNOW.matchAll(/T\('(kbsync\.[a-z_0-9]+)'/g)) benutzt.add(m[1]);
const fehlend = [...benutzt].filter(k => (I18N.match(new RegExp("'" + k.replace('.', '\\.') + "':", 'g')) || []).length !== 2);
pruefe(fehlend.length === 0, `alle ${benutzt.size} benutzten Texte liegen in DE UND EN vor`,
    fehlend.join(', '));

// Sprachwechsel darf die Oberflaeche nicht zerlegen
{
    const { dom, w, KS } = bauen();
    await KS.onShow(); await warten();
    const vorher = w.document.querySelectorAll('.kbsync-card').length;
    w.setLang('en');            // die Funktion heisst setLang, nicht setLanguage
    await warten();
    const h3 = w.document.querySelector('#kb-sect-sync-hdr span[data-i18n="kbsync.section"]');
    pruefe(h3 && /Pull synchronisation/i.test(h3.textContent),
        'Sprachwechsel uebersetzt die Kopfzeile', h3 && h3.textContent);
    await KS.load(); await warten();
    pruefe(w.document.querySelectorAll('.kbsync-card').length === vorher,
        'die Liste bleibt nach dem Sprachwechsel vollstaendig');
    const pill = w.document.querySelector('.kbsync-pill');
    pruefe(pill && /active|paused|error/i.test(pill.textContent),
        'Zustandstexte kommen auf Englisch', pill && pill.textContent);
    dom.window.close();
}

// Fortschritts-Phase wird uebersetzt, nicht technisch durchgereicht
{
    const laufend = [Object.assign({}, PEERS[0], { running: true,
        progress: { phase: 'download', done: 5, total: 9, current: 'a/b.pdf' } })];
    const { dom, w, KS } = bauen({ peers: laufend });
    await KS.onShow(); await warten();
    const txt = w.document.querySelector('.kbsync-progress').textContent;
    pruefe(!/download/.test(txt) && /lädt/.test(txt),
        'Phasenname wird uebersetzt (kein „download" in der Anzeige)', txt);
    pruefe(/5\/9/.test(txt), 'Fortschritt wird gezeigt', txt);
    pruefe(/a\/b\.pdf/.test(txt), 'aktuelle Datei wird gezeigt', txt);
    // Der Takt darf nur laufen, solange der Abschnitt offen ist – sonst pollt
    // die Seite im Hintergrund weiter (der Fehler von context.js).
    KS._sichtbar = false; KS._takt();
    pruefe(KS._timer === null, 'kein Poll-Timer bei zugeklapptem Abschnitt');
    dom.window.close();
}

// CSS: keine harten Farben im neuen Block
const block = CSS.slice(CSS.indexOf('Pull-Synchronisation zwischen Standorten'));
const hart = [...block.matchAll(/#[0-9a-fA-F]{3,8}\b|rgb\((?!var)/g)].map(m => m[0]);
pruefe(hart.length === 0, 'neuer CSS-Block nutzt nur Theme-Variablen', hart.join(', '));
pruefe(/\.kbsync-card\.is-paused\s*\{\s*opacity/.test(block),
    'pausiert wird abgeschwaecht statt umgefaerbt');
pruefe(block.includes('.kbsync-field') && /flex-direction:\s*column/.test(block),
    'Formularfelder stapeln Label ueber Feld (nicht .input-group)');
pruefe(!SYNC.includes('style.cssText'), 'kein Inline-Style im JS');
pruefe(/word-break/.test(block), 'der lange Fingerabdruck darf umbrechen');
// Layout-Fehler aus der Sichtpruefung: Pille wurde auf ganze Breite gezogen,
// der Kopier-Knopf rutschte unter das Token-Feld.
pruefe(/\.kbsync-pill\s*\{[^}]*align-self:\s*flex-start/s.test(block),
    'Pille wird nicht auf die ganze Breite gezogen');
pruefe(/\.kbsync-row \.kb-input\s*\{[^}]*flex:\s*1 1 auto/s.test(block),
    'Feld in einer Zeile teilt sich den Platz mit dem Knopf');
pruefe(/\.kbsync-field > \.kb-input/.test(block),
    'nur das direkte Feld nimmt die ganze Breite');

console.log('\n' + '='.repeat(70));
console.log(`Ergebnis: ${ok} ok, ${fail} fehlgeschlagen`);
process.exit(fail ? 1 : 0);
})();
