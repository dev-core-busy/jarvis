#!/usr/bin/env node
/**
 * Oberflaeche von Short Tracks (/tracks + Einstellungs-Reiter).
 *
 * Geprueft wird gegen die ECHTEN Dateien (tracks.html, tracks.js,
 * short_tracks_admin.js, settings.html, i18n.js, app.js, portal.html) – ein
 * Test, der sein Markup selbst baut, prueft nur seine eigene Annahme (Lehre aus
 * dem Medien-Kontextmenue, 2026-08-10).
 *
 * Teil 1  Berechtigungs-Weiche und das Brett
 * Teil 2  Ablegen: Dateien, URL, Fehlgriffe, Hinweisfeld
 * Teil 3  Auftraege: Zustaende, Warteposition, Download-Chips, Zaehler
 * Teil 4  Formular: wandern, Umschalter, Speichern, Bereichs-Auswahl, global
 * Teil 5  Protokoll
 * Teil 6  Einstellungs-Reiter: zwei Knoepfe = zwei Teilmengen
 * Teil 7  Verdrahtung und Texte (app.js, portal.html, i18n DE+EN, CSS)
 *
 *   node tests/test_short_tracks_ui.js
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

const TR_HTML = fs.readFileSync(path.join(ROOT, 'frontend/tracks.html'), 'utf8');
const TR_JS = fs.readFileSync(path.join(ROOT, 'frontend/js/tracks.js'), 'utf8');
const ADMIN_JS = fs.readFileSync(path.join(ROOT, 'frontend/js/short_tracks_admin.js'), 'utf8');
const SET_HTML = fs.readFileSync(path.join(ROOT, 'frontend/settings.html'), 'utf8');
const I18N = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');
const APP = fs.readFileSync(path.join(ROOT, 'frontend/js/app.js'), 'utf8');
const SKILLS = fs.readFileSync(path.join(ROOT, 'frontend/js/skills.js'), 'utf8');
const SKILLCFG = fs.readFileSync(path.join(ROOT, 'frontend/js/skillcfg.js'), 'utf8');
const PORTAL_HTML = fs.readFileSync(path.join(ROOT, 'frontend/portal.html'), 'utf8');
// Symbole (Muelleimer/Kreuz) – im Browser das ERSTE Skript jeder Seite.
// Module wie chat.js/knowledge.js rufen JarvisIcons.trash() beim Rendern auf;
// ohne diese Zeile bricht das Zeichnen mit 'JarvisIcons is not defined' ab.
const ICONS_JS = fs.readFileSync(path.join(ROOT, 'frontend/js/icons.js'), 'utf8');

/* Der Bereichskatalog kommt UEBERSETZT vom Server (Name und Hinweis stehen dort
   neben der Werkzeugliste, damit Text und Wirkung nicht auseinanderlaufen). Die
   Attrappe bildet deshalb BEIDE Sprachen ab – eine Attrappe, die nur Deutsch
   kennt, koennte einen fehlenden `?lang=`-Parameter gar nicht zeigen. */
const BEREICHE = [
    { id: 'basis', name: 'Lesen + Dokumente erzeugen (Pflicht)', hinweis: 'Datei lesen…', freigegeben: true, pflicht: true, werkzeuge: ['office_read'] },
    { id: 'wissen', name: 'Wissensdatenbank (lesend)', hinweis: 'Für Abgleiche…', freigegeben: true, pflicht: false, werkzeuge: ['knowledge_search'] },
    { id: 'fach', name: 'Interne Fachsysteme (lesend)', hinweis: 'Tickets…', freigegeben: false, pflicht: false, werkzeuge: ['jira_search'] },
    { id: 'shell', name: 'Shell / Python (Auswertung)', hinweis: 'ACHTUNG…', freigegeben: false, pflicht: false, werkzeuge: ['shell_execute'] }
];
const BEREICHE_EN = BEREICHE.map(b => Object.assign({}, b, {
    name: { basis: 'Read + create documents (required)', wissen: 'Knowledge base (read)',
            fach: 'Internal systems (read)', shell: 'Shell / Python (analysis)' }[b.id],
    hinweis: 'english hint'
}));
const katalog = (url) => (/[?&]lang=en\b/.test(String(url)) ? BEREICHE_EN : BEREICHE);

/* Ein Dump-Name ist FREITEXT – einer traegt deshalb eine XSS-Nutzlast. */
const DUMPS = [
    { id: 'aaaaaaaaaaaa', owner: 'a.bender', global: false, name: 'Rechnung',
      beschreibung: 'Rechnungen auswerten', prompt: 'Lies die Rechnung.',
      bereiche: ['basis'], dateitypen: ['pdf'], mehrfach: 'einzeln',
      profile_id: '', reasoning_effort: '', max_steps: 0, enabled: true, laeufe: 3 },
    { id: 'bbbbbbbbbbbb', owner: 'admin', global: true, name: 'Protokoll',
      beschreibung: '', prompt: 'Fasse zusammen.', bereiche: ['basis', 'wissen'],
      dateitypen: [], mehrfach: 'gemeinsam', profile_id: '', reasoning_effort: '',
      max_steps: 0, enabled: true, laeufe: 0 },
    { id: 'cccccccccccc', owner: 'a.bender', global: false,
      name: '<img src=x onerror=alert(1)>', beschreibung: '', prompt: 'p',
      bereiche: ['basis'], dateitypen: [], mehrfach: 'einzeln', profile_id: '',
      reasoning_effort: '', max_steps: 0, enabled: false, laeufe: 0 }
];

const GRENZEN = {
    gleichzeitig: 2, max_datei_mb: 50, max_dateien: 3, max_dumps: 10,
    max_dumps_global: 30, prompt_max: 8000, hinweis_max: 1000,
    name_max: 60, beschreibung_max: 200
};

/* ── Umgebung fuer /tracks ────────────────────────────────────────────────── */
function baue(opt) {
    opt = opt || {};
    const dom = new JSDOM(TR_HTML, { url: 'https://x/tracks', runScripts: 'outside-only' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'T');
    // jsdom meldet OHNE `pretendToBeVisual` immer `document.hidden === true`.
    // Der Abfrage-Takt und die "als gesehen"-Meldung haengen daran – ohne diese
    // Zeile prueft der Test den Hintergrund-Fall und nie den echten.
    // `pretendToBeVisual: true` scheidet aus: es startet einen
    // requestAnimationFrame-Dauerlauf und der Prozess endet nie.
    Object.defineProperty(w.document, 'hidden', { value: opt.versteckt === true,
                                                  configurable: true });
    const rufe = [];
    let dumps = JSON.parse(JSON.stringify(opt.dumps || DUMPS));
    let jobs = JSON.parse(JSON.stringify(opt.jobs || []));

    w.fetch = (url, o) => {
        o = o || {};
        let body = null;
        if (o.body && typeof o.body === 'string') { try { body = JSON.parse(o.body); } catch (e) { } }
        rufe.push({ url: String(url), methode: o.method || 'GET', body: body,
                    form: (o.body && typeof o.body !== 'string') ? o.body : null,
                    kopf: (o.headers || {}) });
        // FALLSTRICK: geroutet wird ueber den PFAD, nicht ueber die ganze URL.
        // Ein Mock mit `url === '/api/tracks/status'` verfehlt jeden Aufruf mit
        // Abfrageteil (dort haengt `?lang=`) – und ein Mock, der die echte
        // Anfrageform verfehlt, prueft nichts (Lehre vom 2026-08-13).
        const pfad = String(url).split('?')[0];
        const gib = (d, status) => Promise.resolve({
            ok: (status || 200) < 400, status: status || 200,
            json: () => Promise.resolve(d)
        });
        if (pfad === '/api/me') {
            return gib({ username: 'nexus\\a.bender', is_admin: !!opt.admin,
                         permissions: { tracks: opt.darf === false ? false : true } });
        }
        if (pfad === '/api/tracks/status') {
            return gib({ ok: true, skill_aktiv: true, ist_admin: !!opt.admin,
                         internet: opt.internet !== false, dumps: dumps,
                         bereiche: katalog(url), grenzen: GRENZEN });
        }
        if (pfad === '/api/tracks/jobs') {
            const neu = jobs.filter(j => (j.status === 'fertig' || j.status === 'fehler') && !j.gesehen).length;
            const aktiv = jobs.filter(j => j.status === 'wartet' || j.status === 'laeuft').length;
            return gib({ ok: true, jobs: jobs, zaehler: { neu: neu, aktiv: aktiv } });
        }
        if (pfad === '/api/tracks/jobs/seen') { return gib({ ok: true, anzahl: 1 }); }
        if (/\/api\/tracks\/dumps\/[^/]+\/reset$/.test(pfad)) {
            const id = pfad.split('/')[4];
            const vorher = jobs.length;
            jobs = jobs.filter(j => j.dump_id !== id);
            return gib({ ok: true, entfernt: vorher - jobs.length, abgebrochen: 0 });
        }
        if (pfad === '/api/tracks/drop') {
            if (opt.dropFehler) return gib({ ok: false, error: opt.dropFehler,
                                             abgewiesen: opt.abgewiesen || [] }, 400);
            jobs = jobs.concat([{ id: 'j' + jobs.length, dump_id: body ? body.dump_id : 'aaaaaaaaaaaa',
                                  dump: 'Rechnung', titel: 'neu.pdf', status: 'wartet',
                                  schritte: [], ergebnis: '', dateien: [], fehler: '' }]);
            return gib({ ok: true, jobs: [jobs[jobs.length - 1]],
                         abgewiesen: opt.abgewiesen || [] });
        }
        if (pfad === '/api/tracks/drop_url') {
            if (opt.urlFehler) return gib({ ok: false, error: opt.urlFehler }, 400);
            return gib({ ok: true, jobs: [{ id: 'ju', dump_id: body.dump_id,
                          titel: 'Eine Seite', status: 'wartet', schritte: [],
                          ergebnis: '', dateien: [], fehler: '' }], abgewiesen: [] });
        }
        if (pfad === '/api/tracks/dumps' && o.method === 'POST') {
            if (opt.postFehler) return gib({ ok: false, error: opt.postFehler }, 400);
            dumps = dumps.concat([Object.assign({ id: 'neu', owner: 'a.bender',
                                                  global: !!(body && body.global) }, body)]);
            return gib({ ok: true, dump: dumps[dumps.length - 1] });
        }
        if (/\/api\/tracks\/dumps\/[^/]+$/.test(pfad) && o.method === 'PUT') {
            const id = pfad.split('/').pop();
            dumps = dumps.map(x => x.id === id ? Object.assign({}, x, body) : x);
            return gib({ ok: true, dump: dumps.filter(x => x.id === id)[0] });
        }
        if (/\/api\/tracks\/dumps\/[^/]+$/.test(pfad) && o.method === 'DELETE') {
            const id = pfad.split('/').pop();
            dumps = dumps.filter(x => x.id !== id);
            return gib({ ok: true });
        }
        if (/\/api\/tracks\/jobs\/[^/]+$/.test(pfad) && o.method === 'DELETE') {
            const id = pfad.split('/').pop();
            jobs = jobs.filter(j => j.id !== id);
            return gib({ ok: true });
        }
        if (pfad === '/api/tracks/log') {
            return gib({ ok: true, eintraege: opt.log || [
                { ts: 1755000000, dump: 'Rechnung', titel: 're.pdf', ok: true,
                  ergebnis: 'Netto 100 EUR erkannt.', dauer_s: 12.4,
                  dateien: [{ name: 'Auswertung.xlsx', url: '/api/documents/' + 'a'.repeat(32) + '__Auswertung.xlsx' }] },
                { ts: 1754990000, dump: 'Protokoll', titel: '<b>roh</b>', ok: false,
                  ergebnis: 'Fehlgeschlagen', dauer_s: 1.0, dateien: [] }
            ] });
        }
        return gib({ ok: true });
    };
    w.confirm = () => (opt.confirm === undefined ? true : opt.confirm);
    // FormData/File brauchen jsdom-eigene Klassen – die gibt es dort.
    w.eval(I18N);
    w.eval(TR_JS);
    // Die Ruf-Liste zusaetzlich am Fenster ablegen, damit auch Bloecke, die nur
    // `w` festhalten, sie pruefen koennen (siehe rufeVon()).
    w._rufe = rufe;
    return { dom, w, rufe, hatDumps: () => dumps, hatJobs: () => jobs,
             setzeJobs: (j) => { jobs = j; } };
}

const warte = (ms) => new Promise(r => setTimeout(r, ms || 40));
const karte = (w, id) => w.document.querySelector('.st-dump[data-dump="' + id + '"]');
const rufeVon = (w) => w._rufe || [];

/* Sauber schliessen: erst den Abfrage-Takt stoppen und weitere Aufrufe ins
   Leere laufen lassen, dann das Fenster. Sonst loest ein noch schwebendes
   fetch-Promise NACH dem close() auf und greift auf ein `document` zu, das es
   nicht mehr gibt – die Ausnahme sieht dann wie ein Codefehler aus. */
const schliesse = async (w) => {
    try { if (w.jarvisTracks && w.jarvisTracks.stop) w.jarvisTracks.stop(); } catch (e) { }
    w.fetch = () => new Promise(() => { });
    await warte(10);   // schwebende Antworten noch abarbeiten lassen
    w.close();
};

(async () => {

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('1. Berechtigungs-Weiche und das Brett');
/* ═══════════════════════════════════════════════════════════════════════ */
{
    const { w } = baue({});
    await warte(60);
    pruefe(!w.document.getElementById('st-app').classList.contains('hidden'),
        'Angemeldeter Benutzer sieht den Bereich');
    const karten = w.document.querySelectorAll('.st-dump');
    pruefe(karten.length === 3, 'alle sichtbaren Ablagen werden gezeichnet', String(karten.length));
    pruefe(karte(w, 'aaaaaaaaaaaa').textContent.indexOf('Rechnung') > -1, 'Name steht auf der Karte');
    pruefe(karte(w, 'aaaaaaaaaaaa').textContent.indexOf('Rechnungen auswerten') > -1,
        'Beschreibung steht auf der Karte');
    pruefe(karte(w, 'bbbbbbbbbbbb').querySelector('.st-badge.is-global') !== null,
        'globale Ablage ist an einer Marke erkennbar (nicht nur an der Farbe)');
    pruefe(karte(w, 'cccccccccccc').classList.contains('is-off'),
        'abgeschaltete Ablage ist abgeschwaecht');
    pruefe(karte(w, 'cccccccccccc').querySelector('.st-badge') !== null,
        'und traegt eine Marke "inaktiv"');
    // Eine abgeschaltete Ablage nimmt NICHTS an – der Server weist den Drop mit
    // 404 ab, also darf die Flaeche auch nicht dazu einladen (im Screenshot vom
    // 2026-08-18 tat sie es).
    const dropOff = karte(w, 'cccccccccccc').querySelector('[data-act="drop"]');
    pruefe(dropOff.getAttribute('role') === null &&
           dropOff.getAttribute('aria-disabled') === 'true',
        'die Ablageflaeche einer inaktiven Ablage ist kein Knopf');
    pruefe(/nimmt nichts an|accepts nothing/.test(dropOff.textContent),
        'und sagt das im Klartext');
    // DIE BINDUNG, NICHT NUR DAS MARKUP: eine Gegenprobe, die nur role/
    // aria-disabled prueft, bleibt gruen, wenn der Handler weiter haengt.
    const vorherOff = rufeVon(w).length;
    const evOff = new w.Event('drop', { bubbles: true, cancelable: true });
    evOff.dataTransfer = { files: [new w.File(['x'], 'a.pdf')], getData: () => '' };
    dropOff.dispatchEvent(evOff);
    dropOff.click();
    await warte(40);
    pruefe(rufeVon(w).length === vorherOff,
        'ein Drop auf die inaktive Flaeche loest KEINEN Aufruf aus');
    pruefe(w.document.querySelector('.st-dump img') === null,
        'XSS im Namen wird maskiert (kein <img> im DOM)');
    pruefe(karte(w, 'aaaaaaaaaaaa').textContent.indexOf('.pdf') > -1,
        'der Dateityp-Filter steht auf der Ablageflaeche');
    pruefe(karte(w, 'bbbbbbbbbbbb').querySelector('.st-drop-types').textContent
        .indexOf('alle') > -1, 'ohne Filter steht "alle lesbaren Dateien"');
    // Ein globaler Dump gehoert einem Admin – ein normaler Benutzer darf ihn
    // nicht aendern und bekommt deshalb keine Knoepfe.
    pruefe(karte(w, 'bbbbbbbbbbbb').querySelector('[data-act="edit"]') === null,
        'globale Ablage: kein Bearbeiten-Knopf fuer Nicht-Admins');
    pruefe(karte(w, 'aaaaaaaaaaaa').querySelector('[data-act="edit"]') !== null,
        'eigene Ablage: Bearbeiten-Knopf vorhanden');
    pruefe(w.document.getElementById('st-board-empty').classList.contains('hidden'),
        'der Leer-Hinweis ist versteckt, wenn Ablagen da sind');
    await schliesse(w);
}
{
    const { w } = baue({ admin: true });
    await warte(60);
    pruefe(karte(w, 'bbbbbbbbbbbb').querySelector('[data-act="edit"]') !== null,
        'ein Admin darf die globale Ablage bearbeiten');
    await schliesse(w);
}
{
    const { w } = baue({ dumps: [] });
    await warte(60);
    pruefe(!w.document.getElementById('st-board-empty').classList.contains('hidden'),
        'ohne Ablagen erscheint der Leer-Hinweis');
    await schliesse(w);
}
{
    // Nicht freigegeben -> Weiterleitung, KEIN Inhalt. jsdom kann `location`
    // nicht ersetzen; erkennbar ist es daran, dass die App versteckt bleibt.
    const { w } = baue({ darf: false });
    await warte(60);
    pruefe(w.document.getElementById('st-app').classList.contains('hidden'),
        'ohne permissions.tracks bleibt der Bereich verborgen');
    pruefe(TR_JS.indexOf("window.location.replace('/portal')") > -1,
        'und der Benutzer wird auf das Portal zurueckgeschickt');
    pruefe(/!d\.permissions \|\| !d\.permissions\.tracks/.test(TR_JS),
        'fail-closed: fehlendes permissions-Feld gilt als "nicht freigegeben"');
    // Seit dem 2026-08-18 steht hinter permissions.tracks eine eigene Freigabe
    // (Sicherheit → Berechtigungen → Short-Tracks-Zugriff), nicht nur der
    // Skill-Zustand. Die Weiche hier ist dieselbe – geprueft wird, dass sie
    // wirkt, egal warum das Feld false ist.
    pruefe(w.document.getElementById('st-board').children.length === 0,
        'ohne Freigabe wird kein Brett gezeichnet');
    await schliesse(w);
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('2. Ablegen: Dateien, URL, Fehlgriffe');
/* ═══════════════════════════════════════════════════════════════════════ */
{
    const { w, rufe } = baue({});
    await warte(60);
    const k = karte(w, 'aaaaaaaaaaaa');
    const notiz = k.querySelector('[data-act="note"]');
    notiz.value = 'nur Seite 2';
    const drop = k.querySelector('[data-act="drop"]');

    // dragover MUSS preventDefault rufen, sonst nimmt der Browser den Drop
    // nicht an und oeffnet die Datei im Reiter.
    const ev = new w.Event('dragover', { bubbles: true, cancelable: true });
    drop.dispatchEvent(ev);
    pruefe(ev.defaultPrevented, 'dragover ruft preventDefault');
    pruefe(drop.classList.contains('is-over'), 'die Flaeche wird beim Ziehen hervorgehoben');
    drop.dispatchEvent(new w.Event('dragleave', { bubbles: true }));
    pruefe(!drop.classList.contains('is-over'), 'und beim Verlassen wieder normal');

    const datei = new w.File(['x'], 're.pdf', { type: 'application/pdf' });
    const dropEv = new w.Event('drop', { bubbles: true, cancelable: true });
    dropEv.dataTransfer = { files: [datei], getData: () => '' };
    drop.dispatchEvent(dropEv);
    await warte(60);
    const gesendet = rufe.filter(r => r.url === '/api/tracks/drop');
    pruefe(gesendet.length === 1, 'genau EIN Upload-Aufruf', String(gesendet.length));
    pruefe(gesendet[0].methode === 'POST', 'per POST');
    pruefe(gesendet[0].form !== null, 'als FormData (nicht JSON)');
    pruefe(gesendet[0].form.get('dump_id') === 'aaaaaaaaaaaa', 'die Ablage-Kennung geht mit');
    pruefe(gesendet[0].form.get('hinweis') === 'nur Seite 2', 'der Hinweis geht mit');
    pruefe(gesendet[0].form.getAll('files').length === 1, 'die Datei geht mit');
    pruefe(!('Content-Type' in gesendet[0].kopf),
        'KEIN Content-Type gesetzt (den Multipart-Rand setzt der Browser)');
    pruefe(String(gesendet[0].kopf.Authorization || '').indexOf('Bearer ') === 0,
        'der Token steckt im Header');
    pruefe(notiz.value === '', 'das Hinweisfeld wird nach dem Absenden geleert');
    pruefe(w.document.querySelector('.st-toast') !== null, 'es gibt eine Rueckmeldung');
    await schliesse(w);
}
{
    // Eine gezogene Adresse (aus der Adresszeile) kommt als text/uri-list.
    const { w, rufe } = baue({});
    await warte(60);
    const drop = karte(w, 'aaaaaaaaaaaa').querySelector('[data-act="drop"]');
    const ev = new w.Event('drop', { bubbles: true, cancelable: true });
    ev.dataTransfer = { files: [], getData: (t) => t === 'text/uri-list' ? 'https://example.com/seite' : '' };
    drop.dispatchEvent(ev);
    await warte(60);
    const u = rufe.filter(r => r.url === '/api/tracks/drop_url');
    pruefe(u.length === 1, 'eine gezogene Adresse geht an /drop_url');
    pruefe(u[0].body.url === 'https://example.com/seite', 'die Adresse wird uebergeben');
    pruefe(u[0].body.dump_id === 'aaaaaaaaaaaa', 'mit der Ablage-Kennung');
    await schliesse(w);
}
{
    // Weder Datei noch Adresse: Klartext-Hinweis, KEIN Aufruf.
    const { w, rufe } = baue({});
    await warte(60);
    const vorher = rufe.length;
    const drop = karte(w, 'aaaaaaaaaaaa').querySelector('[data-act="drop"]');
    const ev = new w.Event('drop', { bubbles: true, cancelable: true });
    ev.dataTransfer = { files: [], getData: () => 'einfach nur Text' };
    drop.dispatchEvent(ev);
    await warte(40);
    pruefe(rufe.length === vorher, 'unbrauchbarer Drop loest KEINEN Aufruf aus');
    const t = w.document.querySelector('.st-toast');
    pruefe(t && t.classList.contains('is-bad'), 'sondern eine Fehlermeldung');
    await schliesse(w);
}
{
    // Zu viele Dateien: schon im Browser abgefangen, kein Aufruf.
    const { w, rufe } = baue({});
    await warte(60);
    const vorher = rufe.length;
    const drop = karte(w, 'aaaaaaaaaaaa').querySelector('[data-act="drop"]');
    const ev = new w.Event('drop', { bubbles: true, cancelable: true });
    const viele = [1, 2, 3, 4].map(i => new w.File(['x'], i + '.pdf'));
    ev.dataTransfer = { files: viele, getData: () => '' };
    drop.dispatchEvent(ev);
    await warte(40);
    pruefe(rufe.length === vorher, 'ueber der Grenze wird nichts gesendet');
    pruefe((w.document.querySelector('.st-toast') || {}).textContent
        .indexOf('3') > -1, 'die Meldung nennt die Grenze');
    await schliesse(w);
}
{
    // Abgewiesene Dateien werden BENANNT, nicht bloss gezaehlt.
    const { w } = baue({ abgewiesen: [{ name: 'brief.docx', grund: 'Dieser Dump nimmt nur .pdf an' }] });
    await warte(60);
    const drop = karte(w, 'aaaaaaaaaaaa').querySelector('[data-act="drop"]');
    const ev = new w.Event('drop', { bubbles: true, cancelable: true });
    ev.dataTransfer = { files: [new w.File(['x'], 'brief.docx')], getData: () => '' };
    drop.dispatchEvent(ev);
    await warte(60);
    const t = w.document.querySelector('.st-toast');
    pruefe(t && t.textContent.indexOf('brief.docx') > -1, 'die Meldung nennt die Datei');
    pruefe(t && t.textContent.indexOf('nur .pdf') > -1, 'und den Grund');
    await schliesse(w);
}
{
    // Klick-Weg: verstecktes <input type=file> (Touch/Tastatur)
    const { w } = baue({});
    await warte(60);
    const inp = w.document.getElementById('st-file-input');
    let geklickt = 0;
    inp.click = () => { geklickt++; };
    karte(w, 'aaaaaaaaaaaa').querySelector('[data-act="drop"]').click();
    pruefe(geklickt === 1, 'ein Klick auf die Flaeche oeffnet die Dateiauswahl');
    pruefe(inp.multiple === true, 'mehrere Dateien sind waehlbar');
    pruefe(TR_JS.indexOf("inp.value = ''") > -1,
        'das Feld wird geleert (sonst feuert change bei derselben Datei nicht)');
    await schliesse(w);
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('3. Auftraege: Zustaende, Warteposition, Chips, Zaehler');
/* ═══════════════════════════════════════════════════════════════════════ */
{
    const JOBS = [
        { id: 'j1', dump_id: 'aaaaaaaaaaaa', dump: 'Rechnung', titel: 're1.pdf',
          status: 'laeuft', schritte: [{ t: 1.2, werkzeug: 'office_read' }],
          ergebnis: '', dateien: [], fehler: '', dauer_s: 5.0 },
        { id: 'j2', dump_id: 'aaaaaaaaaaaa', dump: 'Rechnung', titel: 're2.pdf',
          status: 'wartet', wartend_vor: 2, schritte: [], ergebnis: '', dateien: [], fehler: '' },
        { id: 'j3', dump_id: 'aaaaaaaaaaaa', dump: 'Rechnung', titel: 're3.pdf',
          status: 'fertig', schritte: [], dauer_s: 12.4, fehler: '',
          ergebnis: 'Netto 100 EUR erkannt.',
          dateien: [{ name: 'Auswertung.xlsx', url: '/api/documents/' + 'a'.repeat(32) + '__Auswertung.xlsx' }] },
        { id: 'j4', dump_id: 'bbbbbbbbbbbb', dump: 'Protokoll', titel: 'x.pdf',
          status: 'fehler', schritte: [], ergebnis: '', dateien: [],
          fehler: 'Das Modell hat keine Antwort formuliert.' }
    ];
    const { w, rufe } = baue({ jobs: JOBS });
    await warte(80);
    const box = w.document.querySelector('[data-jobs="aaaaaaaaaaaa"]');
    pruefe(!box.classList.contains('hidden'), 'die Auftragsliste erscheint in der Karte');
    pruefe(box.querySelectorAll('.st-job').length === 3,
        'drei Auftraege dieser Ablage', String(box.querySelectorAll('.st-job').length));
    pruefe(w.document.querySelector('[data-jobs="bbbbbbbbbbbb"] .st-job') !== null,
        'der Auftrag der anderen Ablage steht in DEREN Karte');
    const zeilen = [...box.querySelectorAll('.st-job')].map(z => z.textContent);
    pruefe(zeilen.some(t => /l(ä|ae)uft/.test(t)), 'laufender Auftrag ist erkennbar');
    pruefe(zeilen.some(t => t.indexOf('office_read') > -1),
        'der aktuelle Schritt wird gezeigt (das ist die Live-Aussage)');
    pruefe(zeilen.some(t => t.indexOf('2') > -1 && /wartet/.test(t)),
        'der wartende Auftrag nennt seine Position');
    pruefe(zeilen.some(t => t.indexOf('Netto 100 EUR') > -1), 'das Ergebnis steht da');
    pruefe(zeilen.some(t => t.indexOf('12.4') > -1), 'mit Laufzeit');
    const chip = box.querySelector('.st-chip');
    pruefe(chip !== null, 'die Ergebnisdatei erscheint als Chip');
    pruefe(chip.getAttribute('href').indexOf('token=T') > -1,
        'der Chip traegt das Sitzungstoken (ein <a download> kann keinen Header setzen)');
    pruefe(chip.hasAttribute('download'), 'und laedt herunter statt zu navigieren');
    pruefe(chip.textContent.indexOf('Auswertung.xlsx') > -1, 'mit dem Dateinamen');
    const fehler = w.document.querySelector('[data-jobs="bbbbbbbbbbbb"] .st-job');
    pruefe(fehler.classList.contains('is-bad'), 'ein Fehlschlag ist abgesetzt');
    pruefe(fehler.textContent.indexOf('keine Antwort') > -1, 'und nennt den Grund');
    const pille = w.document.getElementById('st-queue-pill');
    pruefe(pille.classList.contains('is-run') && /2/.test(pille.textContent),
        'die Pille oben zeigt die laufenden/wartenden Auftraege');
    pruefe(rufe.some(r => r.url === '/api/tracks/jobs/seen'),
        'fertige Auftraege werden als gesehen gemeldet (Kachel-Zaehler)');
    // Abgeschlossene lassen sich aus der Liste nehmen, laufende nicht
    pruefe(w.document.querySelector('[data-jobdel="j3"]') !== null,
        'fertiger Auftrag hat einen Entfernen-Knopf');
    pruefe(w.document.querySelector('[data-jobdel="j1"]') === null,
        'ein LAUFENDER hat keinen (das waere ein Abbruch)');
    w.document.querySelector('[data-jobdel="j3"]').click();
    await warte(60);
    pruefe(rufe.some(r => r.methode === 'DELETE' && /\/api\/tracks\/jobs\/j3$/.test(r.url)),
        'der Knopf entfernt genau diesen Auftrag');
    await schliesse(w);
}
{
    // Im Hintergrund wird NICHT als gesehen gemeldet – sonst loescht ein
    // ruhender Reiter den Zaehler der Portal-Kachel.
    pruefe(/document\.hidden\s*&&/.test(TR_JS) || /!document\.hidden\s*&&/.test(TR_JS),
        'der Takt beachtet document.hidden');
    pruefe(/if \(!document\.hidden && \(d\.zaehler \|\| \{\}\)\.neu\)/.test(TR_JS),
        '"als gesehen" nur bei sichtbarem Reiter');
    pruefe(TR_JS.indexOf('visibilitychange') > -1,
        'bei Rueckkehr wird sofort nachgesehen');
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('4. Formular: wandern, Umschalter, Speichern');
/* ═══════════════════════════════════════════════════════════════════════ */
{
    const { w, rufe } = baue({});
    await warte(60);
    const k = karte(w, 'aaaaaaaaaaaa');
    k.querySelector('[data-act="edit"]').click();
    await warte(20);
    const f = w.document.getElementById('st-form');
    pruefe(f !== null, 'das Formular erscheint');
    pruefe(f.previousElementSibling === k,
        'und zwar DIREKT UNTER der bearbeiteten Karte');
    pruefe(w.document.getElementById('st-f-name').value === 'Rechnung',
        'die Felder sind vorbelegt');
    pruefe(w.document.getElementById('st-f-prompt').value === 'Lies die Rechnung.',
        'auch die Aufgabe');
    pruefe(w.document.getElementById('st-f-types').value === 'pdf', 'auch der Typfilter');
    pruefe(w.document.getElementById('st-f-multi').value === 'einzeln', 'auch die Mehrfach-Wahl');
    pruefe(w.document.getElementById('st-f-enabled').checked === true, 'auch der Aktiv-Haken');

    // Bereichs-Kaesten
    const kaesten = [...f.querySelectorAll('#st-f-areas input[type="checkbox"]')];
    const basis = kaesten.filter(c => c.value === 'basis')[0];
    const shell = kaesten.filter(c => c.value === 'shell')[0];
    pruefe(basis.checked && basis.disabled,
        'der Pflicht-Bereich ist angehakt UND gesperrt');
    pruefe(shell.disabled, 'ein nicht freigegebener Bereich ist gesperrt');
    pruefe(f.querySelector('#st-f-areas').textContent.indexOf('nicht freigegeben') > -1,
        'und als solcher beschriftet (nicht bloss ausgegraut)');
    pruefe(kaesten.filter(c => c.value === 'wissen')[0].disabled === false,
        'ein freigegebener Bereich ist waehlbar');

    // DER RUECKWEG: wird das Brett neu gezeichnet (was schon `applyLang()`
    // ausloest, weil es `jarvis-lang-changed` feuert), muss das Formular wieder
    // unter SEINE Karte wandern. Heimholen allein genuegt nicht – ohne den
    // Rueckweg springt es an den Heimatplatz und gehoert sichtbar zu nichts.
    // Genau diese Haelfte fehlte bis 2026-08-11 der Vorschau in /wissen.
    await w.jarvisTracks.ladeStatus();
    await warte(20);
    const f2 = w.document.getElementById('st-form');
    pruefe(f2 !== null, 'nach einem Neuzeichnen ist das Formular noch da');
    pruefe(f2 && f2.previousElementSibling ===
        w.document.querySelector('.st-dump[data-dump="aaaaaaaaaaaa"]'),
        'und steht WEITER unter seiner Karte (Rueckweg des wandernden Formulars)');
    pruefe(w.document.getElementById('st-f-name').value === 'Rechnung',
        'die Feldinhalte sind dabei erhalten');

    // Umschalter: derselbe Knopf schliesst wieder
    w.document.querySelector('.st-dump[data-dump="aaaaaaaaaaaa"] [data-act="edit"]').click();
    await warte(20);
    pruefe(w.document.getElementById('st-form') === null,
        'ein zweiter Klick schliesst das Formular (Umschalter)');

    // Speichern per PUT
    k.querySelector('[data-act="edit"]').click();
    await warte(20);
    w.document.getElementById('st-f-name').value = 'Rechnung neu';
    w.document.getElementById('st-f-types').value = 'pdf, xlsx';
    w.document.getElementById('st-f-save').click();
    await warte(80);
    const put = rufe.filter(r => r.methode === 'PUT');
    pruefe(put.length === 1, 'genau ein PUT');
    pruefe(/\/api\/tracks\/dumps\/aaaaaaaaaaaa$/.test(put[0].url), 'auf die richtige Ablage');
    pruefe(put[0].body.name === 'Rechnung neu', 'mit dem neuen Namen');
    pruefe(put[0].body.dateitypen === 'pdf, xlsx', 'mit den Typen');
    pruefe(put[0].body.bereiche.indexOf('basis') > -1, 'mit dem Pflicht-Bereich');
    pruefe(!('owner' in put[0].body) && !('global' in put[0].body) && !('id' in put[0].body),
        'OHNE owner/global/id (unveraenderliche Felder werden nicht gesendet)');
    pruefe(w.document.getElementById('st-form') === null, 'das Formular schliesst sich');
    await schliesse(w);
}
{
    // Neue Ablage: POST, Formular am Heimatplatz
    const { w, rufe } = baue({});
    await warte(60);
    w.document.getElementById('st-new-btn').click();
    await warte(20);
    const f = w.document.getElementById('st-form');
    pruefe(f !== null && f.parentNode.id === 'st-form-home',
        'bei "neu" steht das Formular an seinem Heimatplatz');
    pruefe(w.document.getElementById('st-f-name').value === '', 'die Felder sind leer');
    // Pflichtfelder werden im Browser abgefangen
    w.document.getElementById('st-f-save').click();
    await warte(40);
    pruefe(rufe.filter(r => r.methode === 'POST' && r.url === '/api/tracks/dumps').length === 0,
        'ohne Name/Aufgabe wird nichts gesendet');
    pruefe(w.document.getElementById('st-f-status').textContent.length > 0,
        'sondern ein Hinweis gezeigt');
    w.document.getElementById('st-f-name').value = 'Neu';
    w.document.getElementById('st-f-prompt').value = 'Mach was.';
    w.document.getElementById('st-f-save').click();
    await warte(80);
    const post = rufe.filter(r => r.methode === 'POST' && r.url === '/api/tracks/dumps');
    pruefe(post.length === 1, 'dann genau ein POST');
    pruefe(post[0].body.name === 'Neu' && post[0].body.prompt === 'Mach was.',
        'mit Name und Aufgabe');
    pruefe(!('global' in post[0].body),
        'ein Nicht-Admin sendet KEIN global-Feld');
    await schliesse(w);
}
{
    // global nur fuer Admins und nur beim Anlegen
    const { w, rufe } = baue({ admin: true });
    await warte(60);
    w.document.getElementById('st-new-btn').click();
    await warte(20);
    pruefe(w.document.getElementById('st-f-global') !== null,
        'ein Admin sieht das Kaestchen "Fuer alle Benutzer"');
    w.document.getElementById('st-f-global').checked = true;
    w.document.getElementById('st-f-name').value = 'Global neu';
    w.document.getElementById('st-f-prompt').value = 'p';
    w.document.getElementById('st-f-save').click();
    await warte(80);
    const post = rufe.filter(r => r.methode === 'POST' && r.url === '/api/tracks/dumps');
    pruefe(post[0].body.global === true, 'und kann global anlegen');
    // Beim BEARBEITEN gibt es das Kaestchen nicht (global ist unveraenderlich)
    karte(w, 'bbbbbbbbbbbb').querySelector('[data-act="edit"]').click();
    await warte(20);
    pruefe(w.document.getElementById('st-f-global') === null,
        'beim Bearbeiten fehlt es (global ist unveraenderlich)');
    await schliesse(w);
}
{
    // Fehlermeldung des Servers wird im Klartext gezeigt
    const { w } = baue({ postFehler: 'Diese Werkzeug-Bereiche sind nicht freigeschaltet: shell' });
    await warte(60);
    w.document.getElementById('st-new-btn').click();
    await warte(20);
    w.document.getElementById('st-f-name').value = 'X';
    w.document.getElementById('st-f-prompt').value = 'p';
    w.document.getElementById('st-f-save').click();
    await warte(80);
    pruefe(w.document.getElementById('st-f-status').textContent.indexOf('shell') > -1,
        'der Grund des Servers steht im Formular');
    pruefe(w.document.getElementById('st-form') !== null,
        'und das Formular bleibt offen (die Eingabe ist nicht verloren)');
    await schliesse(w);
}
{
    // Loeschen fragt nach und entfernt
    const { w, rufe } = baue({});
    await warte(60);
    karte(w, 'aaaaaaaaaaaa').querySelector('[data-act="del"]').click();
    await warte(80);
    pruefe(rufe.some(r => r.methode === 'DELETE' && /dumps\/aaaaaaaaaaaa$/.test(r.url)),
        'Loeschen ruft DELETE');
    pruefe(TR_JS.indexOf('window.confirm') > -1, 'nach Rueckfrage');
    await schliesse(w);
}
{
    const { w, rufe } = baue({ confirm: false });
    await warte(60);
    karte(w, 'aaaaaaaaaaaa').querySelector('[data-act="del"]').click();
    await warte(40);
    pruefe(!rufe.some(r => r.methode === 'DELETE'),
        'wer die Rueckfrage abbricht, loescht nichts');
    await schliesse(w);
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('4b. Maximieren');
/* ═══════════════════════════════════════════════════════════════════════ */
{
    const { w } = baue({});
    await warte(60);
    const brett = [...w.document.querySelectorAll('.st-card[data-klapp]')]
        .filter(c => c.getAttribute('data-klapp') === 'board')[0];
    const log = [...w.document.querySelectorAll('.st-card[data-klapp]')]
        .filter(c => c.getAttribute('data-klapp') === 'log')[0];
    const knopf = brett.querySelector('[data-act="max"]');
    pruefe(knopf !== null, 'die Ablagen-Karte hat einen Maximieren-Knopf');
    // DIESELBEN ZEICHEN wie der Vollbild-Knopf der Einstellungen – aus DEREN
    // Quelle gelesen, nicht abgetippt: eine zweite Fassung liefe beim naechsten
    // Wechsel auseinander (Vorgabe des Nutzers 2026-08-18).
    const symMax = (SET_HTML.match(/id="btn-maximize-settings"[^>]*>(.)</) || [])[1];
    const EXPAND = fs.readFileSync(path.join(ROOT, 'frontend/js/modal_expand.js'), 'utf8');
    // `u`-Flag ist Pflicht: 🗗 (U+1F5D7) ist ein Surrogatpaar, ohne das Flag
    // matcht `.` nur die halbe Einheit und der Vergleich schlaegt fehl.
    const symMin = (EXPAND.match(/on \? '(.)' : '(.)'/u) || [])[1];
    pruefe(symMax === '\u26f6', 'die Einstellungen nutzen U+26F6 (⛶)', symMax);
    pruefe(knopf.textContent.trim() === symMax,
        'der Knopf hier zeigt dasselbe Zeichen', knopf.textContent.trim());
    pruefe(knopf.getAttribute('aria-pressed') === 'false', 'er startet auf "nicht gedrückt"');
    pruefe(brett.querySelector('.st-head-acts') !== null,
        'Knopf und Klapp-Pfeil stehen in einem gemeinsamen Behälter');
    // REIHENFOLGE: der Titel bleibt VORNE (space-between) – sonst rutscht er
    // an den rechten Rand (Fehler vom 2026-08-13 im Add-in).
    pruefe(brett.querySelector('.st-card-head').firstElementChild.tagName === 'H2',
        'der Titel ist weiter das erste Kind der Kopfzeile');

    knopf.click();
    await warte(20);
    pruefe(brett.classList.contains('is-max'), 'ein Klick maximiert die Karte');
    pruefe(w.document.body.classList.contains('st-maxed'),
        'und sperrt das Scrollen der Seite dahinter');
    pruefe(knopf.getAttribute('aria-pressed') === 'true', 'aria-pressed folgt dem Zustand');
    pruefe(/Verkleinern|Restore/.test(knopf.title),
        'der Titel des Knopfes wechselt mit (kein unveränderlicher Text)');
    pruefe(knopf.textContent.trim() === symMin,
        'im maximierten Zustand dasselbe Zeichen wie modal_expand.js', knopf.textContent.trim());
    pruefe(knopf.classList.contains('active'),
        'und der Knopf traegt `active` – wie .btn-maximize-settings.active');
    pruefe(knopf.getAttribute('data-i18n-title') === 'tracks.minimize',
        'und der i18n-Schlüssel ebenfalls');
    // Der Klick darf die Karte NICHT zuklappen (der Knopf sitzt in der Kopfzeile)
    pruefe(!brett.classList.contains('is-zu'),
        'der Klick auf den Knopf klappt die Karte nicht zu');
    pruefe(w.document.documentElement.style.getPropertyValue('--st-top') !== null,
        'der Abstand zur Titelleiste wird gesetzt (gemessen, nicht geraten)');

    knopf.click();
    await warte(20);
    pruefe(!brett.classList.contains('is-max'), 'ein zweiter Klick verkleinert wieder');
    pruefe(!w.document.body.classList.contains('st-maxed'), 'die Seite scrollt wieder');

    // Escape verkleinert
    knopf.click();
    await warte(20);
    w.document.dispatchEvent(new w.KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await warte(20);
    pruefe(!brett.classList.contains('is-max'), 'Escape verkleinert');

    // Eine ZUGEKLAPPTE Karte wird beim Maximieren aufgeklappt – sonst
    // maximiert man eine leere Fläche.
    pruefe(log.classList.contains('is-zu'), 'das Protokoll ist zugeklappt');
    log.querySelector('[data-act="max"]').click();
    await warte(60);
    pruefe(log.classList.contains('is-max') && !log.classList.contains('is-zu'),
        'Maximieren klappt eine zugeklappte Karte auf');

    // Zwei maximierte Karten gleichzeitig gäbe einen Zustand, den niemand
    // auflösen kann.
    knopf.click();
    await warte(20);
    pruefe(brett.classList.contains('is-max') && !log.classList.contains('is-max'),
        'es ist immer höchstens EINE Karte maximiert');
    await schliesse(w);
}
{
    // Sprachwechsel: der Knopf-Titel wird per JS gesetzt und muss mitgehen
    const { w } = baue({});
    await warte(60);
    const brett = [...w.document.querySelectorAll('.st-card[data-klapp]')]
        .filter(c => c.getAttribute('data-klapp') === 'board')[0];
    brett.querySelector('[data-act="max"]').click();
    await warte(20);
    w.setLang('en');
    await warte(60);
    pruefe(/Restore/.test(brett.querySelector('[data-act="max"]').title),
        'der Titel folgt dem Sprachwechsel (auch im maximierten Zustand)');
    w.setLang('de');
    await warte(40);
    await schliesse(w);
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('5. Protokoll');
/* ═══════════════════════════════════════════════════════════════════════ */
{
    const { w, rufe } = baue({});
    await warte(60);
    const karteLog = [...w.document.querySelectorAll('.st-card[data-klapp]')]
        .filter(c => c.getAttribute('data-klapp') === 'log')[0];
    pruefe(karteLog.classList.contains('is-zu'), 'das Protokoll startet zugeklappt');
    pruefe(!rufe.some(r => r.url.indexOf('/api/tracks/log') === 0),
        'und wird nicht im Voraus geladen');
    karteLog.querySelector('.st-card-head').click();
    await warte(80);
    pruefe(rufe.some(r => r.url.indexOf('/api/tracks/log') === 0),
        'erst beim Aufklappen wird geladen');
    const zeilen = w.document.querySelectorAll('#st-log .st-log-row');
    pruefe(zeilen.length === 2, 'beide Einträge erscheinen', String(zeilen.length));
    pruefe(zeilen[0].textContent.indexOf('Netto 100 EUR') > -1, 'mit Ergebnis');
    pruefe(zeilen[1].classList.contains('is-bad'), 'Fehlschlag abgesetzt');
    pruefe(w.document.querySelector('#st-log b') !== null, 'Ablage-Name fett');
    pruefe(w.document.querySelector('#st-log .st-log-res b') === null,
        'Fremdtext im Titel wird maskiert (kein <b> aus den Daten)');
    pruefe(w.document.querySelector('#st-log .st-chip[href*="token=T"]') !== null,
        'die Chips im Protokoll tragen ebenfalls das Token');
    await schliesse(w);
}
{
    const { w } = baue({ log: [] });
    await warte(60);
    w.jarvisTracks.ladeLog();
    await warte(60);
    pruefe(w.document.querySelector('#st-log .st-empty') !== null,
        'ohne Einträge steht ein Klartext-Hinweis');
    await schliesse(w);
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('6. Sprachwechsel und Hilfe-Kästen');
/* ═══════════════════════════════════════════════════════════════════════ */
{
    const { w, rufe } = baue({});
    await warte(60);
    const vorher = rufe.filter(r => r.url.indexOf('/api/tracks/status') === 0).length;
    w.setLang('en');
    await warte(80);
    const nachher = rufe.filter(r => r.url.indexOf('/api/tracks/status') === 0);
    pruefe(nachher.length === vorher + 1,
        'ein Sprachwechsel holt den SERVER-Katalog neu (applyLang erreicht ihn nicht)');
    pruefe(/[?&]lang=en\b/.test(nachher[nachher.length - 1].url),
        'und zwar mit ?lang=en');
    pruefe(w.document.getElementById('st-board-empty').textContent.indexOf('drop zone') > -1,
        'die Markup-Texte sind uebersetzt');
    w.setLang('de');
    await warte(60);
    await schliesse(w);
}
{
    const { w } = baue({});
    await warte(60);
    const knopf = w.document.querySelector('.st-info[data-help="st-help-board"]');
    const kasten = w.document.getElementById('st-help-board');
    pruefe(knopf !== null && kasten !== null, 'der Hilfe-Kasten ist verdrahtet');
    pruefe(!kasten.classList.contains('is-open'), 'er startet zu');
    knopf.click();
    pruefe(kasten.classList.contains('is-open'), 'ein Klick klappt ihn auf');
    knopf.click();
    pruefe(!kasten.classList.contains('is-open'), 'ein zweiter klappt ihn zu');
    pruefe(kasten.querySelectorAll('li').length >= 4,
        'er nennt die Punkte als Liste (Markup bleibt erhalten)');
    // data-i18n-html ist Pflicht: data-i18n wuerde den textContent setzen und
    // das Markup beim ersten Sprachwechsel loeschen.
    pruefe(kasten.getAttribute('data-i18n-html') !== null && !kasten.hasAttribute('data-i18n'),
        'der Kasten traegt data-i18n-html, NICHT data-i18n');
    w.setLang('en');
    await warte(40);
    pruefe(w.document.getElementById('st-help-board').querySelectorAll('li').length >= 4,
        'auch nach dem Sprachwechsel ist die Auszeichnung da');
    w.setLang('de');
    await schliesse(w);
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('7. Einstellungs-Reiter: zwei Knoepfe = zwei Teilmengen');
/* ═══════════════════════════════════════════════════════════════════════ */
{
    const dom = new JSDOM(SET_HTML, { url: 'https://x/settings', runScripts: 'outside-only' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'T');
    const rufe = [];
    w.fetch = (url, o) => {
        o = o || {};
        rufe.push({ url: String(url), methode: (o.method || 'GET'),
                    body: o.body ? JSON.parse(o.body) : null });
        const gib = (d) => Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(d) });
        if (String(url).split('?')[0] === '/api/tracks/admin/overview') {
            return gib({ ok: true, skill_aktiv: true, bereiche: katalog(url),
                         grenzen: { gleichzeitig: 2, max_datei_mb: 50, max_dateien: 20, max_dumps: 10 },
                         global: [{ id: 'b', name: 'Protokoll', enabled: true,
                                    bereiche: ['basis'], laeufe: 7 }],
                         benutzer: [{ owner: 'a.bender', anzahl: 3 }],
                         laufend: 1, wartend: 2 });
        }
        return gib({ ok: true, bereiche: ['basis', 'wissen'] });
    };
    w.confirm = () => true;
    w.eval(I18N);
    w.eval(ADMIN_JS);
    pruefe(typeof w.TracksAdmin === 'object', 'TracksAdmin ist verfuegbar');
    w.TracksAdmin.onShow();
    await warte(60);
    pruefe(w.document.getElementById('tr-l-parallel').value === '2',
        'die Grenzen sind vorbelegt');
    pruefe(w.document.getElementById('tr-areas').querySelectorAll('input[data-area]').length === 4,
        'alle Bereiche stehen zur Freigabe');
    const basis = w.document.querySelector('#tr-areas input[data-area="basis"]');
    pruefe(basis.checked && basis.disabled,
        'der Pflicht-Bereich ist angehakt und gesperrt');
    pruefe(w.document.querySelector('#tr-areas input[data-area="wissen"]').checked === true,
        'ein freigegebener Bereich ist angehakt');
    pruefe(w.document.querySelector('#tr-areas input[data-area="shell"]').checked === false,
        'ein nicht freigegebener nicht');
    pruefe(w.document.getElementById('tr-over').textContent.indexOf('Protokoll') > -1,
        'globale Ablagen stehen in der Uebersicht');
    pruefe(w.document.getElementById('tr-over').textContent.indexOf('a.bender') > -1,
        'und die Anzahl je Benutzer');
    pruefe(w.document.getElementById('tr-over').textContent.indexOf('Lies die') === -1,
        'aber KEINE Aufgaben-Texte');

    // Grenzen speichern: NIE bereiche
    w.document.getElementById('tr-l-parallel').value = '4';
    w.document.getElementById('tr-save-limits').click();
    await warte(60);
    const lim = rufe.filter(r => r.url === '/api/tracks/admin/limits');
    pruefe(lim.length === 1, 'ein Aufruf auf /admin/limits');
    pruefe(lim[0].body.gleichzeitig === 4, 'mit dem neuen Wert');
    pruefe(!('bereiche' in lim[0].body),
        'der Grenzen-Knopf sendet NIE bereiche (sonst ueberschreibt er die Freigabe)');

    // Freigabe speichern: NIE Zahlen
    w.document.querySelector('#tr-areas input[data-area="shell"]').checked = true;
    w.document.getElementById('tr-save-areas').click();
    await warte(60);
    const ar = rufe.filter(r => r.url === '/api/tracks/admin/areas');
    pruefe(ar.length === 1, 'ein Aufruf auf /admin/areas');
    pruefe(ar[0].body.bereiche.indexOf('shell') > -1, 'mit dem neuen Bereich');
    pruefe(ar[0].body.bereiche.indexOf('basis') > -1, 'und dem Pflicht-Bereich');
    pruefe(Object.keys(ar[0].body).length === 1,
        'der Freigabe-Knopf sendet AUSSCHLIESSLICH bereiche');

    // Nothalt
    w.document.getElementById('tr-stop').click();
    await warte(60);
    pruefe(rufe.some(r => r.url === '/api/tracks/admin/stop'), 'der Nothalt ruft /admin/stop');

    // onShow ist idempotent (wird bei jedem Reiter-Klick gerufen)
    const vorher = rufe.length;
    w.TracksAdmin.onShow();
    await warte(60);
    const lim2 = rufe.slice(vorher).filter(r => r.methode === 'POST');
    pruefe(lim2.length === 0, 'ein zweiter onShow speichert nichts');
    w.document.getElementById('tr-save-limits').click();
    await warte(60);
    pruefe(rufe.filter(r => r.url === '/api/tracks/admin/limits').length === 2,
        'und bindet die Knoepfe nicht doppelt');
    await schliesse(w);
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('7b. Der gemeldete Fehler: im Reiter liess sich kein Haken setzen');
/* ═══════════════════════════════════════════════════════════════════════ */
{
    /* GEMELDET am 2026-08-18. Ursache war eine ENDLOSSCHLEIFE: `zeichne()` ruft
       `applyLang()`, und `applyLang()` feuert `jarvis-lang-changed` – der
       Lang-Zuhoerer lud daraufhin neu, baute die Kaestchen neu auf und verwarf
       den gerade gesetzten Haken. Gemessen: >40 Abrufe in 250 ms.

       EIGENES, FRISCHES DOM: im Block oben laufen vorher Speicher-Tests, die
       legitim neu laden – die Abrufe dort zu zaehlen misst etwas anderes (der
       erste Anlauf dieser Pruefung sah 4 statt 1 und meldete einen Fehler, den
       es nicht gab). Nur das Panel-Markup, keine fremden Timer. */
    const html = SET_HTML.slice(SET_HTML.indexOf('<div id="settings-tab-tracks"'));
    const ende = html.indexOf('<div id="settings-tab-kundenverwaltung"');
    const dom = new JSDOM('<!DOCTYPE html><html><body>' +
        html.slice(0, ende > 0 ? ende : 4000).replace('style="display:none;"', '') +
        '</body></html>', { url: 'https://x/settings', runScripts: 'outside-only' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'T');
    let n = 0;
    w.fetch = (url) => {
        if (String(url).split('?')[0] === '/api/tracks/admin/overview') n++;
        return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve({
            ok: true, skill_aktiv: true, bereiche: BEREICHE,
            grenzen: { gleichzeitig: 2, max_datei_mb: 50, max_dateien: 20, max_dumps: 10 },
            global: [], benutzer: [], laufend: 0, wartend: 0 }) });
    };
    w.eval(I18N);
    w.eval(ADMIN_JS);
    w.TracksAdmin.onShow();
    // DAS ZEITFENSTER, um das es geht: waehrend der Abruf noch laeuft, feuert
    // irgendwo ein `applyLang()`. Sieht der Lang-Zuhoerer dann ein leeres
    // `_lang`, haelt er das fuer einen Sprachwechsel und laedt ein zweites Mal
    // (gemessen am 2026-08-18). Deshalb setzt `laden()` die Sprache SOFORT.
    w.dispatchEvent(new w.CustomEvent('jarvis-lang-changed', { detail: { lang: 'de' } }));
    // Und ein zweites onShow im selben Moment (Reiter-Doppelklick) darf den
    // laufenden Abruf nicht verdoppeln.
    w.TracksAdmin.onShow();
    await warte(150);
    pruefe(n === 1, 'onShow ruft die Uebersicht GENAU EINMAL ab – auch bei einem '
        + 'Lang-Ereignis und einem zweiten onShow waehrend des Abrufs', String(n));
    const shell = w.document.querySelector('#tr-areas input[data-area="shell"]');
    pruefe(shell !== null && !shell.disabled, 'das Kaestchen ist bedienbar');
    shell.click();
    pruefe(shell.checked === true, 'ein Haken laesst sich setzen');
    await warte(150);
    const shell2 = w.document.querySelector('#tr-areas input[data-area="shell"]');
    pruefe(shell2 === shell, 'die Kaestchen werden NICHT neu aufgebaut');
    pruefe(shell2.checked === true, 'UND DER HAKEN BLEIBT GESETZT (der gemeldete Fehler)');
    pruefe(n === 1, 'auch danach nur ein Abruf', String(n));
    shell.click();
    pruefe(shell.checked === false, 'und er laesst sich wieder abwaehlen');
    // Ein Ereignis OHNE Sprachwechsel darf nichts laden …
    w.dispatchEvent(new w.CustomEvent('jarvis-lang-changed', { detail: { lang: 'de' } }));
    await warte(80);
    pruefe(n === 1, 'ein Lang-Ereignis ohne Sprachwechsel laedt nicht', String(n));
    // … ein echter Sprachwechsel schon.
    w._lang = 'en';
    w.dispatchEvent(new w.CustomEvent('jarvis-lang-changed', { detail: { lang: 'en' } }));
    await warte(120);
    pruefe(n === 2, 'ein ECHTER Sprachwechsel laedt genau einmal nach', String(n));
    w.close();
}
{
    /* DER FALL, den allein die fruehe `_lang`-Zuweisung abdeckt: der Abruf
       SCHEITERT (z.B. 403, weil der Skill gerade abgeschaltet wurde). Dann laeuft
       `zeichne()` nie – wuerde die Sprache erst dort gemerkt, bliebe sie leer, und
       jedes weitere `applyLang()` (die feuern staendig) waere fuer den Zuhoerer ein
       "Sprachwechsel": ein Karussell aus Fehlversuchen. Die `_laeuft`-Sperre hilft
       hier nicht, sie ist nach dem Fehlschlag wieder offen. */
    const html = SET_HTML.slice(SET_HTML.indexOf('<div id="settings-tab-tracks"'));
    const ende = html.indexOf('<div id="settings-tab-kundenverwaltung"');
    const dom = new JSDOM('<!DOCTYPE html><html><body>' +
        html.slice(0, ende > 0 ? ende : 4000).replace('style="display:none;"', '') +
        '</body></html>', { url: 'https://x/settings', runScripts: 'outside-only' });
    const w = dom.window;
    w.localStorage.setItem('jarvis_token', 'T');
    let n = 0;
    w.fetch = (url) => {
        if (String(url).split('?')[0] === '/api/tracks/admin/overview') n++;
        return Promise.resolve({ ok: false, status: 403,
            json: () => Promise.resolve({ ok: false, error: 'Kein Zugriff' }) });
    };
    w.eval(I18N);
    w.eval(ADMIN_JS);
    w.TracksAdmin.onShow();
    await warte(120);
    pruefe(n === 1, 'ein Fehlschlag ergibt zunaechst einen Abruf', String(n));
    pruefe(/Kein Zugriff/.test(w.document.getElementById('tr-msg-over').textContent),
        'und der Grund steht im Klartext da');
    for (let i = 0; i < 5; i++) {
        w.dispatchEvent(new w.CustomEvent('jarvis-lang-changed', { detail: { lang: 'de' } }));
    }
    await warte(150);
    pruefe(n === 1, 'NACH einem Fehlschlag loesen Lang-Ereignisse keine weiteren '
        + 'Abrufe aus (kein Karussell)', String(n));
    w.close();
}

/* ═══════════════════════════════════════════════════════════════════════ */
abschnitt('8. Verdrahtung, Portal, i18n, CSS');
/* ═══════════════════════════════════════════════════════════════════════ */
{
    // Berechtigungsblock in Sicherheit → Berechtigungen (analog E-Mail)
    pruefe(/id="sec-sub-tracks"[^>]*style="display:none;"/.test(SET_HTML),
        'der Berechtigungsblock startet versteckt (nur bei aktivem Skill)');
    pruefe(/id="tracks-allowed-users"/.test(SET_HTML) &&
           /id="tracks-allowed-group"/.test(SET_HTML),
        'beide Freigabefelder sind im Markup');
    pruefe(/tracks_allowed_users:/.test(SET_HTML) && /tracks_allowed_group:/.test(SET_HTML),
        'sie werden mit den uebrigen Berechtigungen gespeichert');
    pruefe(/d\.tracks_users/.test(SET_HTML) && /d\.tracks_group/.test(SET_HTML),
        'und beim Oeffnen vorbelegt');
    pruefe(/updateTracksSecVisibility/.test(APP),
        'app.js blendet den Block am Skill-Zustand ein');
    // Der Block muss in DERSELBEN Liste stehen wie die uebrigen Picker-Felder –
    // sonst zeigt er nach dem Laden keine Marken (Lehre vom AD-Picker).
    pruefe(/'tracks-allowed-users','tracks-allowed-group'\]/.test(SET_HTML),
        'die Felder stehen in der Picker-Auffrisch-Liste');

    // Reiter
    pruefe(/data-settings-tab="tracks"/.test(SET_HTML), 'der Reiter-Knopf existiert');
    pruefe(/id="settings-tab-btn-tracks"[^>]*style="display:none;"/.test(SET_HTML),
        'und ist per Vorgabe versteckt (nur bei aktivem Skill)');
    pruefe(/id="settings-tab-tracks"/.test(SET_HTML), 'das Panel existiert');
    pruefe(/'short-tracks':\s*'settings-tab-btn-tracks'/.test(SKILLCFG),
        'skillcfg.js blendet den Reiter am Skill-Zustand ein');
    pruefe(!/short-tracks:\s*\{ container/.test(SKILLCFG) &&
           SKILLCFG.indexOf("'short-tracks':     { container") === -1,
        'aber er steht NICHT in TARGETS (eigene Oberflaeche, kein Formular)');
    pruefe(/'short-tracks':\s*'tracks'/.test(SKILLS),
        'skills.js: das Zahnrad springt in den Reiter');
    pruefe(/target === 'tracks' && tabTracks/.test(APP),
        'app.js zeigt das Panel beim Reiter-Klick');
    pruefe(/window\.TracksAdmin\) window\.TracksAdmin\.onShow\(\)/.test(APP),
        'und ruft TracksAdmin.onShow()');
    pruefe(/tr-sect-limits-hdr/.test(APP),
        'die Klapp-Abschnitte laufen ueber das vorhandene _collapseInit');
    pruefe(/short_tracks_admin\.js\?v=\d+/.test(SET_HTML),
        'das Admin-Skript ist mit Cache-Buster eingebunden');

    // Portal
    pruefe(/id="pt-card-tracks"/.test(PORTAL_HTML), 'die Portal-Kachel existiert');
    pruefe(/pt-card-tracks[^]]*?/.test(PORTAL_HTML) &&
           /class="pt-card hidden" id="pt-card-tracks"/.test(PORTAL_HTML),
        'und startet versteckt');
    pruefe(/d\.permissions\.tracks/.test(PORTAL_HTML),
        'sie wird an permissions.tracks eingeblendet');
    pruefe(/id="pt-tracks-badge"/.test(PORTAL_HTML), 'das Badge existiert');
    pruefe(/\/api\/tracks\/count/.test(PORTAL_HTML),
        'der Zaehler nutzt den kleinen count-Endpunkt (nicht die Auftragsliste)');
    pruefe(/refreshUnread\(\); refreshTracks\(\);/.test(PORTAL_HTML),
        'und wird bei Rueckkehr auf die Seite erneuert');

    // Seite
    pruefe(/tracks\.js\?v=\d+/.test(TR_HTML), 'tracks.js hat einen Cache-Buster');
    pruefe(TR_HTML.indexOf('i18n.js') < TR_HTML.indexOf('tracks.js'),
        'i18n.js wird VOR tracks.js geladen');
    pruefe(/id="btn-theme-toggle"/.test(TR_HTML),
        'der Theme-Knopf traegt die Id, die avatar.js erwartet');
    pruefe(/activity\.js/.test(TR_HTML),
        'activity.js ist eingebunden (Untaetigkeits-Anzeige)');

    // Keine harten Farben – Branding und Hell-Modus wuerden sonst brechen
    // KOMMENTARE ENTFERNEN, bevor geprueft wird: der Wächter fand sonst den
    // eigenen Begruendungs-Kommentar ("historisch ein hartes #888899") und
    // meldete einen Fehler, den es nicht gibt – sechster Fall dieser Art im
    // Projekt (Prompt-Waechter 2026-08-10, Ordner-Marke 2026-08-11, …).
    const css = TR_HTML.split('<style>')[1].split('</style>')[0]
        .replace(/\/\*[\s\S]*?\*\//g, '');
    const hart = (css.match(/#[0-9a-fA-F]{3,6}\b/g) || [])
        .filter(x => x.toLowerCase() !== '#fff' && x.toLowerCase() !== '#ffffff');
    pruefe(hart.length === 0, 'keine harten Farben im CSS', String(hart));
    pruefe(/\.st-row\[hidden\]/.test(css),
        'Flex-Zeilen respektieren das hidden-Attribut (Fallstrick .sp-row)');
    pruefe(/\.st-btn\b[^}]*flex: 0 0 auto/.test(css),
        'Knoepfe strecken sich nicht ueber die ganze Flex-Zeile');
    pruefe(/\.st-toast[^}]*background: var\(--bg-secondary\)/.test(css),
        'die Rueckmeldung hat eine DECKENDE Flaeche');
    pruefe(/align-self: flex-start/.test(css),
        'die Zustands-Pille wird im Flex-Container nicht gestreckt');
    pruefe(/\.st-board\b[^}]*align-items: start/.test(css),
        'das Karten-Raster streckt die Karten nicht auf Zeilenhoehe');
    pruefe(/\.st-dump\.is-off \.st-drop/.test(css),
        'eine inaktive Ablage hat eine eigene, sichtbar unbenutzbare Flaeche');
    // Das Formular ist ein Kind des Rasters und muss die ganze Breite nehmen –
    // in einer Spalte (330 px) sind die Felder abgeschnitten und die
    // Bereichs-Kaestchen unlesbar (Screenshot vom 2026-08-18).
    pruefe(/\.st-form\b[^}]*grid-column: 1 \/ -1/.test(css),
        'das Formular geht ueber die volle Breite des Rasters');
    // Maximieren: unter der Titelleiste, deckende Flaeche, Kopf bleibt stehen
    pruefe(/\.st-card\.is-max\b[^}]*position: fixed/.test(css),
        'die maximierte Karte ist fixiert');
    pruefe(/\.st-card\.is-max\b[^}]*top: var\(--st-top/.test(css),
        'sie beginnt UNTER der Titelleiste (Abmelden/Theme bleiben erreichbar)');
    pruefe(/\.st-card\.is-max\b[^}]*background: var\(--bg-primary\)/.test(css),
        'mit DECKENDER Flaeche – darunter liegt die Seite');
    pruefe(/\.st-card\.is-max > \.st-card-head[^}]*position: sticky/.test(css),
        'die Kopfzeile bleibt beim Scrollen stehen (sonst ist der Knopf weg)');
    pruefe(/\.st-card\.is-max > \.st-card-body[^}]*overflow-y: auto/.test(css),
        'der Inhalt scrollt innen');
    pruefe(/body\.st-maxed[^}]*overflow: hidden/.test(css),
        'die Seite dahinter scrollt nicht mit');
    // z-index: unter der Titelleiste (30), unter der Rueckmeldung (60)
    const zMax = (css.match(/\.st-card\.is-max\b[^}]*z-index:\s*(\d+)/) || [])[1];
    pruefe(zMax && Number(zMax) < 30, 'z-index liegt unter der Titelleiste', String(zMax));
    pruefe(zMax && Number(zMax) < 60, 'und unter der Rueckmeldung', String(zMax));
    // Klapp-Kopfzeile: Titel ZUERST, Pfeil danach (space-between)
    const kopf = TR_HTML.match(/<div class="st-card-head"[^>]*>([\s\S]*?)<\/div>/)[1];
    pruefe(kopf.indexOf('<h2') < kopf.indexOf('st-caret'),
        'in der Kopfzeile steht der Titel VOR dem Pfeil');
    // Emoji: farbig voreingestellte Zeichen folgen keinem Theme
    // AUSNAHME: ⛶ (U+26F6) und 🗗 (U+1F5D7) sind die Zeichen des vorhandenen
    // Vollbild-Knopfes (#btn-maximize-settings, modal_expand.js). Konsistenz mit
    // dem Bestand geht hier vor der Emoji-Regel – ausdrueckliche Vorgabe des
    // Nutzers. Alles ANDERE bleibt gesperrt.
    const emoji = ((TR_HTML + TR_JS).match(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/gu) || [])
        .filter(c => c !== '\u26f6' && c !== '\u{1F5D7}');
    pruefe(emoji.length === 0, 'keine farbig voreingestellten Emoji (ausser den Vollbild-Zeichen)',
        String(emoji.slice(0, 5)));
    pruefe(/&#9974;/.test(TR_HTML) && /&#128471;/.test(TR_JS),
        'die Vollbild-Zeichen stehen als HTML-Entity im Quelltext (nicht als rohes Emoji)');

    // Alle aufgerufenen Hilfsfunktionen existieren auch. Ein `?.()` auf einen
    // falschen Namen ist ein unsichtbarer Fehler (Vorfall 2026-08-11), ein
    // direkter Aufruf ein ReferenceError mitten im .then-Zweig.
    const definiert = new Set();
    for (const m of TR_JS.matchAll(/function\s+(\w+)\s*\(/g)) definiert.add(m[1]);
    const aufgerufen = new Set();
    for (const m of TR_JS.matchAll(/\b(lade|zeichne|form)([A-Z]\w*)\s*\(/g)) {
        aufgerufen.add(m[1] + m[2]);
    }
    const fehlend = [...aufgerufen].filter(n => !definiert.has(n));
    pruefe(fehlend.length === 0, 'jede aufgerufene lade*/zeichne*/form*-Funktion ist definiert',
        String(fehlend));
    // Jede Funktion nur EINMAL definiert (nach einem Blockersatz stand
    // `meldung()` schon einmal doppelt im Projekt – toter Code ohne Symptom).
    const doppelt = [...definiert].filter(n =>
        (TR_JS.match(new RegExp('function\\s+' + n + '\\s*\\(', 'g')) || []).length > 1);
    pruefe(doppelt.length === 0, 'keine Funktion doppelt definiert', String(doppelt));

    // i18n: jeder benutzte Schluessel in DE UND EN
    const keys = new Set();
    for (const m of (TR_HTML + ADMIN_JS + SET_HTML).matchAll(
            /data-i18n(?:-html|-title|-placeholder)?="((?:tracks|tracksadm)\.[^"]+)"/g)) keys.add(m[1]);
    for (const m of (TR_JS + ADMIN_JS).matchAll(/T\('((?:tracks|tracksadm)\.[^']+)'/g)) keys.add(m[1]);
    const fehltI18n = [...keys].filter(k => (I18N.match(new RegExp("'" + k.replace('.', '\\.') + "'", 'g')) || []).length < 2);
    pruefe(fehltI18n.length === 0, keys.size + ' i18n-Schluessel in DE UND EN', String(fehltI18n));
}

abschnitt('9. Reset je Ablage');
/* ═══════════════════════════════════════════════════════════════════════ */
{
    // Ohne aktiven Lauf: kein confirm, direkt zuruecksetzen.
    const { w, rufe } = baue({ jobs: [
        { id: 'j1', dump_id: 'aaaaaaaaaaaa', dump: 'Rechnung', titel: 'a.pdf',
          status: 'fertig', schritte: [], ergebnis: 'fertig', dateien: [], fehler: '' },
        { id: 'j2', dump_id: 'bbbbbbbbbbbb', dump: 'Andere', titel: 'b.pdf',
          status: 'fertig', schritte: [], ergebnis: 'fertig', dateien: [], fehler: '' } ] });
    await warte(80);
    const k = karte(w, 'aaaaaaaaaaaa');
    const b = k.querySelector('[data-act="reset"]');
    pruefe(!!b, 'jede Ablage hat einen Reset-Knopf');
    let gefragt = false;
    w.confirm = () => { gefragt = true; return true; };
    if (b) b.click();
    await warte(80);
    pruefe(!gefragt, 'ohne laufenden Auftrag wird NICHT gefragt (kein Klick fuer nichts)');
    const r = rufe.filter(x => /\/reset$/.test(String(x.url).split('?')[0]));
    pruefe(r.length === 1 && r[0].methode === 'POST',
        'genau EIN POST auf den Reset-Endpunkt', JSON.stringify(r.map(x => x.url + ' ' + x.methode)));
    // Defensiv: ohne Treffer waere `r[0].url` ein TypeError – der Test wuerde
    // ABBRECHEN statt fehlzuschlagen, und ein Abbruch ist von einem bestandenen
    // Lauf nicht zu unterscheiden (dieselbe Falle wie bei `.index()` in Python).
    pruefe(r.length > 0 && /\/api\/tracks\/dumps\/aaaaaaaaaaaa\/reset$/.test(r[0].url),
        'und zwar fuer DIESE Ablage');
    await warte(60);
    pruefe(!!karte(w, 'bbbbbbbbbbbb').querySelector('[data-jobs="bbbbbbbbbbbb"]'),
        'die andere Ablage bleibt stehen');
    w.close();
}
{
    // Mit laufendem Auftrag: Rueckfrage – und ein "Nein" sendet nichts.
    const { w, rufe } = baue({ jobs: [
        { id: 'j1', dump_id: 'aaaaaaaaaaaa', dump: 'Rechnung', titel: 'a.pdf',
          status: 'laeuft', schritte: [{ t: 1, werkzeug: 'office_create_excel' }],
          ergebnis: '', dateien: [], fehler: '' } ] });
    await warte(80);
    const k = karte(w, 'aaaaaaaaaaaa');
    let gefragt = 0;
    w.confirm = () => { gefragt++; return false; };
    // Defensiv: fehlt der Knopf, wuerde `.click()` auf null den Test ABBRECHEN
    // statt fehlzuschlagen – und ein Abbruch sieht aus wie ein Erfolg.
    const rb = k.querySelector('[data-act="reset"]');
    pruefe(!!rb, 'Reset-Knopf vorhanden');
    if (rb) rb.click();
    await warte(60);
    pruefe(gefragt === 1, 'bei laufendem Auftrag wird gefragt');
    pruefe(rufe.filter(x => /\/reset$/.test(String(x.url).split('?')[0])).length === 0,
        'ein "Nein" sendet NICHTS');
    w.confirm = () => true;
    if (rb) rb.click();
    await warte(80);
    pruefe(rufe.filter(x => /\/reset$/.test(String(x.url).split('?')[0])).length === 1,
        'nach Bestaetigung genau ein Aufruf');
    w.close();
}
{
    // Auch bei einer GLOBALEN Ablage und ohne Admin-Rechte: der Reset raeumt
    // nur die eigenen Auftraege, deshalb darf ihn jeder benutzen.
    const { w } = baue({ admin: false });
    await warte(80);
    const g = w.document.querySelector('.st-dump[data-dump] [data-act="reset"]');
    pruefe(!!g, 'der Knopf haengt nicht an darfAendern');
    const global = Array.prototype.slice.call(w.document.querySelectorAll('.st-dump'))
        .filter(c => c.querySelector('.st-badge.is-global'))[0];
    if (global) {
        pruefe(!!global.querySelector('[data-act="reset"]'),
            'auch die globale Ablage hat ihn (ohne Bearbeiten/Loeschen)');
        pruefe(!global.querySelector('[data-act="del"]'),
            'Gegenprobe: Loeschen hat sie fuer Nicht-Admins NICHT');
    }
    w.close();
}

/* ═══════════════════════════════════════════════════════════════════════ */
console.log('\n' + '='.repeat(62));
console.log('  ' + ok + ' OK, ' + fail + ' FAIL');
console.log('='.repeat(62));
process.exit(fail ? 1 : 0);
})();
