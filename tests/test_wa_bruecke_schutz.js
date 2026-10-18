#!/usr/bin/env node
/* Waechter: die HTTP-API der WhatsApp-Bridge verlangt das gemeinsame Geheimnis,
 * und /send-media liest nur erzeugte Bilder (Code-Review 2026-10-18).
 *
 *  [1] schutz.js AUSGEFUEHRT in einem Wegwerf-Verzeichnis: Anlegen (0600),
 *      Kopfpruefung, Middleware (401), Pfadschranke inkl. Symlink/../.
 *  [2] index.js am Syntaxbaum (acorn): die Middleware steht VOR der ersten
 *      Route, /send-media liest nur den geprueften Pfad, der Webhook schickt
 *      das Geheimnis mit.
 * Exit 0 = gruen, 1 = FAIL, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs');
const os = require('os');
const path = require('path');
require('./lib/bilanz')();   // Absturz -> Exit 2 statt 1

const W = path.resolve(__dirname, '..');
const acorn = require('./lib/acorn_laden')();
let OK = 0, FAIL = 0, BILANZ = false;
function check(b, t, d) {
    if (b) { OK++; console.log('  OK   ' + t); } else { FAIL++; console.log('  FAIL ' + t + (d ? '  -> ' + d : '')); }
}
process.on('exit', (code) => {
    if (!BILANZ && code === 0) { console.log('ABBRUCH ohne Bilanz'); process.exitCode = 1; }
});
function bilanz() { BILANZ = true; console.log('\nErgebnis: ' + OK + ' OK, ' + FAIL + ' FAIL'); }

const SK = fs.mkdtempSync(path.join(os.tmpdir(), 'wa_schutz_'));
const DATEN = path.join(SK, 'data');
haupt();
async function haupt() {
try {
    console.log('\n[1] schutz.js');
    const { erzeuge, KOPF } = require(path.join(W, 'services/whatsapp-bridge/schutz.js'));
    const s = erzeuge(DATEN);
    const g = s.geheimnis();
    check(typeof g === 'string' && g.length >= 32, '(Positivkontrolle) Geheimnis angelegt');
    if (FAIL) { bilanz(); process.exit(2); }
    check((fs.statSync(s.datei).mode & 0o777) === 0o600, 'Datei 0600',
          (fs.statSync(s.datei).mode & 0o777).toString(8));
    check(erzeuge(DATEN).geheimnis() === g, 'zweite Instanz liest DASSELBE (kein Ueberschreiben)');
    check(s.kopfStimmt(g) === true, 'richtiger Wert stimmt');
    check(s.kopfStimmt(g.slice(0, -1) + (g.endsWith('0') ? '1' : '0')) === false, 'ein Zeichen falsch: nein');
    check(s.kopfStimmt('') === false && s.kopfStimmt(undefined) === false, 'leer/fehlend: nein');
    check(KOPF === 'X-Jarvis-Bridge' && s.KOPF === KOPF, 'Kopfname wie im Backend');
    // Backend ersetzt die Datei: neu lesen
    fs.writeFileSync(s.datei, 'f'.repeat(64));
    check(s.kopfStimmt('f'.repeat(64)) === true, 'ersetzte Datei wird beim Fehlvergleich neu gelesen');

    // Middleware
    function antwort() {
        return { code: 200, body: null, status(c) { this.code = c; return this; }, json(b) { this.body = b; return this; } };
    }
    let weiter = 0;
    let r = antwort();
    s.pruefen({ get: () => undefined }, r, () => weiter++);
    check(r.code === 401 && weiter === 0, 'Middleware: ohne Kopf 401, Route nicht erreicht');
    r = antwort();
    s.pruefen({ get: (k) => (k === KOPF ? 'f'.repeat(64) : undefined) }, r, () => weiter++);
    check(weiter === 1 && r.code === 200, '(Positivkontrolle) Middleware: mit Kopf weiter');

    // Pfadschranke
    fs.mkdirSync(s.bilder, { recursive: true });
    const bild = path.join(s.bilder, 'abc.png');
    fs.writeFileSync(bild, 'PNG');
    const env = path.join(SK, '.env');
    fs.writeFileSync(env, 'GEHEIM=1');
    fs.symlinkSync(env, path.join(s.bilder, 'link.png'));
    fs.mkdirSync(path.join(s.bilder, 'unter'));
    fs.writeFileSync(path.join(s.bilder, 'unter', 'x.png'), 'PNG');
    check(s.medienPfad(bild) === fs.realpathSync(bild), '(Positivkontrolle) erzeugtes Bild erlaubt');
    check(s.medienPfad(env) === null, '.env ausserhalb: abgewiesen');
    check(s.medienPfad(path.join(s.bilder, 'link.png')) === null, 'Symlink im Bildordner auf .env: abgewiesen');
    check(s.medienPfad(path.join(s.bilder, '..', '.env')) === null, '../ aus dem Bildordner: abgewiesen');
    check(s.medienPfad(path.join(s.bilder, 'unter', 'x.png')) === null, 'Unterverzeichnis: abgewiesen');
    check(s.medienPfad(s.bilder) === null, 'der Ordner selbst: abgewiesen');
    check(s.medienPfad('') === null && s.medienPfad(['x']) === null, 'leer/kein Text: abgewiesen');

    console.log('\n[2] index.js (Syntaxbaum)');
    const QUELLE = fs.readFileSync(path.join(W, 'services/whatsapp-bridge/index.js'), 'utf8');
    const baum = acorn.parse(QUELLE, { ecmaVersion: 'latest', sourceType: 'script', locations: true });
    const aufrufe = [];
    (function lauf(n) {
        if (!n || typeof n.type !== 'string') return;
        if (n.type === 'CallExpression') aufrufe.push(n);
        for (const k of Object.keys(n)) {
            const v = n[k];
            if (Array.isArray(v)) v.forEach(lauf); else if (v && typeof v.type === 'string') lauf(v);
        }
    })(baum);
    const istApp = (c, m) => c.callee.type === 'MemberExpression' && c.callee.object.name === 'app'
        && c.callee.property.name === m;
    const routen = aufrufe.filter(c => ['get', 'post', 'delete', 'put'].some(m => istApp(c, m)));
    const mw = aufrufe.filter(c => istApp(c, 'use') && c.arguments[0] && c.arguments[0].type === 'MemberExpression'
        && c.arguments[0].object.name === 'schutz' && c.arguments[0].property.name === 'pruefen');
    check(routen.length >= 8, '(Positivkontrolle) Routen gefunden (' + routen.length + ')');
    check(mw.length === 1, 'app.use(schutz.pruefen) genau einmal');
    const erste = Math.min(...routen.map(r => r.start));
    check(mw.length === 1 && mw[0].start < erste, 'Middleware steht VOR der ersten Route');
    const sm = routen.find(r => r.arguments[0] && r.arguments[0].value === '/send-media');
    check(!!sm, '(Positivkontrolle) /send-media gefunden');
    if (sm) {
        const text = QUELLE.slice(sm.start, sm.end);
        check(/schutz\.medienPfad\(media_path\)/.test(text), '/send-media prueft den Pfad');
        check(!/readFileSync\(media_path\)/.test(text) && /readFileSync\(echt\)/.test(text),
              '/send-media liest NUR den geprueften Pfad');
    }
    const hook = aufrufe.find(c => c.callee.type === 'MemberExpression' && c.callee.object.name === 'schutz'
        && c.callee.property.name === 'webhookSenden' && c.arguments[0] && c.arguments[0].name === 'JARVIS_WEBHOOK');
    check(!!hook, 'Webhook geht ueber schutz.webhookSenden (Geheimnis + gepinntes Zertifikat)');
    check(!aufrufe.some(c => c.callee.name === 'fetch' && c.arguments[0] && c.arguments[0].name === 'JARVIS_WEBHOOK'),
          'kein ungeschuetzter fetch an den Webhook mehr');
    await webhookProbe();
} finally {
    fs.rmSync(SK, { recursive: true, force: true });
}
bilanz();
process.exit(FAIL ? 1 : 0);
}

async function webhookProbe() {
    console.log('\n[3] Webhook mit gepinntem Zertifikat (echter HTTPS-Server)');
    const { execFileSync } = require('child_process');
    const https = require('https');
    const certs = path.join(SK, 'certs');
    fs.mkdirSync(certs, { recursive: true });
    function zert(name) {
        execFileSync('openssl', ['req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-days', '1', '-subj',
            '/CN=jarvis.beispiel.test', '-keyout', path.join(certs, name + '.key'),
            '-out', path.join(certs, name + '.crt')], { stdio: 'ignore' });
        return { key: fs.readFileSync(path.join(certs, name + '.key')), cert: fs.readFileSync(path.join(certs, name + '.crt')) };
    }
    const echt = zert('server');
    const fremd = zert('fremd');
    const { erzeuge, KOPF } = require(path.join(W, 'services/whatsapp-bridge/schutz.js'));
    const s = erzeuge(DATEN);
    async function server(z) {
        const gesehen = [];
        const srv = https.createServer(z, (req, res) => { gesehen.push(req.headers[KOPF.toLowerCase()] || ''); res.end('{}'); });
        await new Promise(r => srv.listen(0, '127.0.0.1', r));
        return { srv, gesehen, url: 'https://localhost:' + srv.address().port + '/api/whatsapp/incoming' };
    }
    const a = await server(echt);
    let erg = null, fehler = null;
    try { erg = await s.webhookSenden(a.url, { type: 'text' }); } catch (e) { fehler = e; }
    check(erg && erg.status === 200, '(Positivkontrolle) gepinntes Zertifikat (Name passt NICHT zu localhost): durch',
          fehler && fehler.message);
    check(a.gesehen.length === 1 && a.gesehen[0] === s.geheimnis(), 'Geheimnis kam beim Backend an');
    a.srv.close();
    const b = await server(fremd);
    erg = null; fehler = null;
    try { erg = await s.webhookSenden(b.url, { type: 'text' }); } catch (e) { fehler = e; }
    check(!erg && fehler, 'fremdes Zertifikat: abgewiesen', erg && JSON.stringify(erg));
    check(b.gesehen.length === 0, '... und das Geheimnis ging NICHT hinaus');
    b.srv.close();
    check(!/NODE_TLS_REJECT_UNAUTHORIZED=0/.test(fs.readFileSync(path.join(W, 'docker/entrypoint.sh'), 'utf8')
        .split('\n').filter(z => !z.trim().startsWith('#')).join('\n')),
          'docker/entrypoint.sh schaltet die TLS-Pruefung nicht mehr prozessweit ab');
}
