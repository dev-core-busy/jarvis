/* Waechter: die Info-/Kontaktzeile des Portals steht auf JEDER Kachel-Seite
 * (Vorgabe 2026-11-15) – gebaut von fusszeile.js, uebersetzt von i18n.js,
 * befuellt von branding.js.
 *
 * Gemessen wird die WIRKUNG an der ECHTEN Seite: das echte HTML jeder
 * Kachel-Seite, darin die echten Module fusszeile.js -> i18n.js -> branding.js
 * in genau der Reihenfolge, in der die Seite sie einbindet. Ob die Zeile
 * erscheint, uebersetzt wird und die Branding-Werte traegt, kann eine Suche im
 * Quelltext nicht beantworten (eine Einbindung HINTER i18n.js waere textlich
 * vorhanden und bliebe trotzdem deutsch).
 *
 * Welche Seiten Kachel-Seiten sind, wird aus portal.html GELESEN (die Ziele der
 * Kacheln), nicht abgetippt – eine neue Kachel faellt automatisch darunter.
 * Ausgenommen, mit Grund:
 *   /chat, /userchat – Messenger-Layout mit fester Fensterhoehe
 *   (`overflow: hidden`); eine Zeile am Seitenende laege unsichtbar unter dem
 *   Eingabefeld bzw. muesste dem Verlauf Hoehe wegnehmen.
 *
 * Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen.
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { JSDOM, VirtualConsole } = require('./lib/jsdom_laden')();

const ROOT = path.resolve(__dirname, '..');
const FE = path.join(ROOT, 'frontend');
const AUSGENOMMEN = { '/chat': 'Messenger-Layout', '/userchat': 'Messenger-Layout' };

let ok = 0, fail = 0, bilanz = false;
function check(name, cond, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + name); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + name + (detail ? ' – ' + detail : '')); }
}
function abbruch(grund) { console.log('ABBRUCH: ' + grund); bilanz = true; process.exit(2); }
process.on('exit', (code) => { if (!bilanz && code === 0) process.exitCode = 1; });
const wachhund = setTimeout(() => { console.log('ABBRUCH: Zeitueberschreitung'); bilanz = true; process.exit(2); }, 90000);

const lies = (p) => fs.readFileSync(p, 'utf8');
const MODUL = {
    fusszeile: lies(path.join(FE, 'js', 'fusszeile.js')),
    i18n: lies(path.join(FE, 'js', 'i18n.js')),
    branding: lies(path.join(FE, 'js', 'branding.js')),
};

// ── 1. Kachel-Seiten aus portal.html ableiten ────────────────────────────
console.log('\n\x1b[1m1. Grundlage\x1b[0m');
const portal = lies(path.join(FE, 'portal.html'));
const ziele = new Set();
for (const m of portal.matchAll(/<a\b[^>]*class="pt-card\b[^"]*"[^>]*href="(\/[a-z][a-z0-9-]*)"/g)) ziele.add(m[1]);
for (const m of portal.matchAll(/<a\b[^>]*href="(\/[a-z][a-z0-9-]*)"[^>]*class="pt-card\b/g)) ziele.add(m[1]);
const seiten = [];
for (const z of [...ziele].sort()) {
    if (AUSGENOMMEN[z]) continue;
    const datei = path.join(FE, z.slice(1).replace(/-/g, '_') + '.html');
    if (!fs.existsSync(datei)) { check('Kachelziel ' + z + ' hat eine Seite', false, datei); continue; }
    seiten.push({ ziel: z, datei });
}
// Positivkontrolle: die Ableitung trifft. Bei Null waere jede Folgepruefung trivial wahr.
if (seiten.length < 10) abbruch('nur ' + seiten.length + ' Kachel-Seiten aus portal.html abgeleitet');
check(seiten.length + ' Kachel-Seiten aus portal.html abgeleitet (ohne ' + Object.keys(AUSGENOMMEN).join(', ') + ')', true);
for (const z of Object.keys(AUSGENOMMEN)) check('Ausnahme ' + z + ' ist wirklich eine Kachel', ziele.has(z));

// ── Lauf einer Seite: echtes HTML + echte Module in Einbindungsreihenfolge ─
const ORDNUNG = ['fusszeile', 'i18n', 'branding'];
function reihenfolge(html) {
    const pos = {};
    for (const n of ORDNUNG) {
        const m = html.match(new RegExp('<script src="/static/js/' + n + '\\.js\\?v=\\d+"'));
        pos[n] = m ? m.index : -1;
    }
    return pos;
}

async function lauf(html, { sprache, branding }) {
    // jsdom kennt HTMLMediaElement.load nicht (Portal-Video) – nur dieses Rauschen schlucken
    const vc = new VirtualConsole();
    vc.on('jsdomError', (e) => { if (!/Not implemented/.test(String(e && e.message))) console.log('jsdom: ' + e); });
    const dom = new JSDOM(html, { url: 'https://beispiel.de/seite', runScripts: 'outside-only', pretendToBeVisual: true, virtualConsole: vc });
    const w = dom.window;
    try { w.localStorage.setItem('jarvis_lang', sprache); } catch (e) {}
    // fetch-Attrappe, ueber den PFAD geroutet. Alles ausser /api/branding: 404.
    w.fetch = async (url) => {
        const p = String(url).split('?')[0];
        if (p === '/api/branding') return { ok: true, status: 200, json: async () => branding };
        return { ok: false, status: 404, json: async () => ({}) };
    };
    const pos = reihenfolge(html);
    const folge = ORDNUNG.filter((n) => pos[n] >= 0).sort((a, b) => pos[a] - pos[b]);
    for (const n of folge) w.eval(MODUL[n]);
    // jsdom feuert DOMContentLoaded selbst – darauf warten, nicht selbst ausloesen
    if (w.document.readyState === 'loading') {
        await new Promise((r) => w.document.addEventListener('DOMContentLoaded', r));
    }
    await new Promise((r) => setTimeout(r, 50));   // fetch().then().then()
    return { w, folge };
}

const BRAND = {
    active: true, contact_info: 'Probefirma Info', contact_phone: '+49 30 1234',
    contact_email: 'kontakt@beispiel.de', manual_url: 'https://beispiel.de/handbuch',
};
const sichtbar = (el) => !!el && !el.classList.contains('hidden');
// Zugriffe, die bei fehlendem Element NICHT werfen: ein Wurf waere ein Abbruch
// ohne Bilanz statt eines Befunds.
const text = (d, id) => { const e = d.getElementById(id); return e ? e.textContent : ''; };
const attr = (d, id, a) => { const e = d.getElementById(id); return e ? e.getAttribute(a) : null; };

(async () => {
    // ── 2. Positivkontrolle der Messmethode am Portal ────────────────────
    console.log('\n\x1b[1m2. Portal (Platzhalter unter den Kacheln)\x1b[0m');
    {
        const { w } = await lauf(portal, { sprache: 'de', branding: { active: false } });
        const d = w.document;
        const fz = d.querySelectorAll('#pt-contact');
        check('genau EINE Kontaktzeile', fz.length === 1, String(fz.length));
        const el = fz[0];
        check('sie IST der Platzhalter in .pt-wrap (nicht am Seitenende)',
            !!el && el.hasAttribute('data-fusszeile') && !!el.closest('.pt-wrap'));
        check('Standardwerte ohne Branding: E-Mail sichtbar',
            sichtbar(d.getElementById('pt-contact-email')) && /@/.test(text(d, 'pt-contact-email-link')));
        check('Portal traegt KEIN zweites, statisches Markup mehr (eine Quelle)',
            !/id="pt-contact-info"/.test(portal));
    }

    // ── 3. Jede Kachel-Seite ─────────────────────────────────────────────
    console.log('\n\x1b[1m3. Kachel-Seiten\x1b[0m');
    for (const s of seiten) {
        const html = lies(s.datei);
        const pos = reihenfolge(html);
        const name = s.ziel;
        if (pos.fusszeile < 0) { check(name + ': bindet fusszeile.js ein', false); continue; }
        check(name + ': fusszeile.js VOR i18n.js und branding.js',
            (pos.i18n < 0 || pos.fusszeile < pos.i18n) && (pos.branding < 0 || pos.fusszeile < pos.branding),
            JSON.stringify(pos));

        // a) Branding aktiv, Sprache EN: Zeile da, uebersetzt, Werte gesetzt
        const { w } = await lauf(html, { sprache: 'en', branding: BRAND });
        const d = w.document;
        const alle = d.querySelectorAll('#pt-contact');
        check(name + ': genau eine Kontaktzeile', alle.length === 1, String(alle.length));
        const el = alle[0];
        if (!el) continue;
        check(name + ': steht am Seitenende (letztes Element im body)',
            el.parentElement === d.body && el.classList.contains('pt-contact-seite'));
        const tel = d.getElementById('pt-contact-phone');
        check(name + ': Branding-Telefon sichtbar', sichtbar(tel) && /1234/.test(text(d, 'pt-contact-phone')));
        check(name + ': Branding-E-Mail gesetzt',
            attr(d, 'pt-contact-email-link', 'href') === 'mailto:kontakt@beispiel.de');
        check(name + ': Handbuch-Link sichtbar', sichtbar(d.getElementById('pt-contact-manual')));
        if (pos.i18n >= 0) {
            check(name + ': Telefon-Praefix uebersetzt (EN)',
                /Phone/.test(text(d, 'pt-contact-phone')), text(d, 'pt-contact-phone').trim());
        }
        w.close();
    }
    clearTimeout(wachhund);
    console.log('\n\x1b[1mErgebnis: ' + ok + ' OK, ' + fail + ' FAIL\x1b[0m');
    bilanz = true;
    process.exit(fail ? 1 : 0);
})().catch((e) => { console.log('ABBRUCH: ' + (e && e.stack || e)); bilanz = true; process.exit(2); });
