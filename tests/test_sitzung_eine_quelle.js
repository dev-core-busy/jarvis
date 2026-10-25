/* Waechter: Sitzungstoken und Benutzername kommen aus EINER Quelle.
 *
 * DER VORFALL (2026-10-01, ECHT, /chat): eine Benutzerin klickte auf den
 * Download-Chip einer zusammengefuehrten Rechnung und bekam vom Browser eine
 * Frage nach Benutzername und Kennwort. Keine Berechtigung war schuld, sondern
 * ein NAME: jede Seite legt ihre Anmeldung unter einem eigenen Schluessel ab –
 *
 *     app.js (/settings)  -> jarvis_token
 *     chat.js (/chat)     -> jarvis_chat_token
 *     userchat.js         -> jarvis_uc_token
 *
 * – und `dlkey.js` las ausschliesslich `jarvis_token`. Im Chat war der Wert
 * damit leer; die Datei-Adresse bekam GAR KEIN `?token=`, der Server antwortete
 * 401, und Chrome macht daraus die Anmeldefrage. Gemessen: `/api/download-key`
 * wurde nie aufgerufen, und im Journal von ECHT stand ueber drei Tage keine
 * einzige Zeile dazu.
 *
 * Der Radius war nicht die eine Datei: 27 Dateien trugen die Kette KOPIERT,
 * 37 weitere lasen nur EINEN Schluessel. Ob eine Datei richtig lag, entschied
 * allein, ob ihre Seite zufaellig `app.js` mitlud – gemessen waren **10 dieser
 * Blind-Leser auf Seiten ohne `jarvis_token`** eingebunden.
 *
 * GEMESSEN WIRD AM SYNTAXBAUM (acorn), nicht am Text. Drei Gruende:
 *   - Ein Teilstring ist keine Identitaet: `getItem('jarvis_token')` steht auch
 *     in den Begruendungen dieser Dateien, und ein Text-Waechter liest damit
 *     seine eigene Erklaerung (Register: "Ein Waechter, der seine eigene
 *     Begruendung liest, prueft nichts"). Kommentare stehen nicht im AST.
 *   - Der Unterschied zwischen LESEN (verboten) und SCHREIBEN (gewollt – jede
 *     Seite schreibt bewusst ihren eigenen Schluessel) ist der Methodenname am
 *     Aufruf, nicht die Zeichenkette.
 *   - Eine Liste faellt ueber mehrere Zeilen; ein Zeilenmuster findet sie nicht.
 *
 * Abschnitt 3 prueft die REIHENFOLGE der Einbindungen. Das ist keine Kuer:
 * `sessions.js`, `app.js`, `chat.js` und `userchat.js` rufen `JarvisSitzung`
 * beim LADEN auf – steht `sitzung.js` dahinter, stirbt die Seite an einem
 * TypeError, bevor irgendetwas rendert. Ein vergessenes `<script>` saehe dann
 * wie ein Anmeldeproblem aus, nicht wie eine fehlende Datei.
 */
'use strict';
require('./lib/bilanz')();   // Absturz -> Exit 2, nicht 1 (test_waechter_bilanz.js)
const fs = require('fs');
const path = require('path');

const acorn = require('./lib/acorn_laden')();

const WURZEL = path.resolve(__dirname, '..');
const QUELLE = path.join(WURZEL, 'frontend/js/sitzung.js');

const TOKEN_SCHLUESSEL = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];
const BENUTZER_SCHLUESSEL = ['jarvis_user', 'jarvis_chat_user', 'jarvis_uc_user'];
const ALLE = TOKEN_SCHLUESSEL.concat(BENUTZER_SCHLUESSEL);

let ok = 0, fail = 0;
function check(text, bed, detail) {
    if (typeof text !== 'string' || typeof bed !== 'boolean') {
        console.log('ABBRUCH: check(Beschreibung, Bedingung) – Argumente vertauscht: ' + text);
        process.exit(2);
    }
    if (bed) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + text); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + text + (detail ? ' – ' + detail : '')); }
}
function abbruch(grund) {
    console.log('\x1b[31mABBRUCH (Exit 2): ' + grund + '\x1b[0m');
    console.log('Exit 2 = konnte nicht laufen – weder bestanden noch fehlgeschlagen.');
    process.exit(2);
}

/* ── Dateien einsammeln ──────────────────────────────────────────────── */
function sammle(verz, endungen, treffer) {
    for (const name of fs.readdirSync(verz)) {
        const p = path.join(verz, name);
        const st = fs.statSync(p);
        if (st.isDirectory()) {
            if (name === 'vendor' || name === 'node_modules') continue;
            sammle(p, endungen, treffer);
        } else if (endungen.some(e => name.endsWith(e))) {
            treffer.push(p);
        }
    }
    return treffer;
}
const FRONTEND = path.join(WURZEL, 'frontend');
const JS_DATEIEN = sammle(FRONTEND, ['.js'], []);
const HTML_DATEIEN = sammle(FRONTEND, ['.html'], []);

/* ── AST-Hilfen ──────────────────────────────────────────────────────── */
function parse(quelle, wo) {
    try {
        return acorn.parse(quelle, { ecmaVersion: 'latest', sourceType: 'script', locations: true });
    } catch (e) {
        try {
            return acorn.parse(quelle, { ecmaVersion: 'latest', sourceType: 'module', locations: true });
        } catch (e2) {
            return { __fehler: e2.message, __wo: wo };
        }
    }
}
/* Eigener Baumlauf: ueber ALLE Knoten, ohne Abhaengigkeit von acorn-walk
 * (das ist ein getrenntes Paket und laege damit als zweite Fundstelle vor). */
function begehe(knoten, besuch) {
    if (!knoten || typeof knoten !== 'object') return;
    if (Array.isArray(knoten)) { for (const k of knoten) begehe(k, besuch); return; }
    if (typeof knoten.type === 'string') besuch(knoten);
    for (const schl of Object.keys(knoten)) {
        if (schl === 'type' || schl === 'loc' || schl === 'start' || schl === 'end') continue;
        begehe(knoten[schl], besuch);
    }
}
function istSchluesselLiteral(k) {
    return k && k.type === 'Literal' && typeof k.value === 'string' && ALLE.includes(k.value);
}
/** Alle Verstoesse einer Quelle: Lese-Zugriffe und Listen. */
function verstoesse(quelle, wo) {
    const baum = parse(quelle, wo);
    if (baum.__fehler) return { fehler: baum.__fehler, liste: [] };
    const liste = [];
    begehe(baum, (n) => {
        // (a) localStorage.getItem('<schluessel>') – der Blind-Leser
        if (n.type === 'CallExpression' && n.callee && n.callee.type === 'MemberExpression'
            && n.callee.property && n.callee.property.name === 'getItem'
            && n.arguments.length && istSchluesselLiteral(n.arguments[0])) {
            liste.push({ art: 'getItem', wert: n.arguments[0].value, zeile: n.loc && n.loc.start.line });
        }
        // (b) eine Liste mit zwei oder mehr Schluesseln – die zweite Quelle
        if (n.type === 'ArrayExpression') {
            const drin = n.elements.filter(istSchluesselLiteral).map(e => e.value);
            if (drin.length >= 2) {
                liste.push({ art: 'Liste', wert: drin.join(','), zeile: n.loc && n.loc.start.line });
            }
        }
    });
    return { fehler: null, liste };
}

/* ══ 1. Positivkontrolle ═════════════════════════════════════════════════
 * Ohne diese Pruefungen ist Abschnitt 2 TRIVIAL WAHR: eine geloeschte oder
 * leere sitzung.js wuerde ihn muehelos bestehen. */
console.log('\n\x1b[1m1. Positivkontrolle: die Quelle existiert und tut etwas\x1b[0m');
if (!fs.existsSync(QUELLE)) abbruch('frontend/js/sitzung.js fehlt – die Regel ist dann bedeutungslos.');
const Q = fs.readFileSync(QUELLE, 'utf8');
const qBaum = parse(Q, 'sitzung.js');
if (qBaum.__fehler) abbruch('sitzung.js parst nicht: ' + qBaum.__fehler);

const qTreffer = verstoesse(Q, 'sitzung.js').liste;
const qGetItem = qTreffer.filter(t => t.art === 'getItem').length;
const qListen = qTreffer.filter(t => t.art === 'Liste');
// sitzung.js liest ueber die LISTEN, nicht ueber Literale – also sind dort
// keine getItem-Literale zu erwarten, aber BEIDE Listen muessen da sein.
const listenWerte = qListen.map(l => l.wert);
if (!listenWerte.some(w => TOKEN_SCHLUESSEL.every(s => w.includes(s))))
    abbruch('sitzung.js enthaelt die Token-Kette nicht – sie ist dann nicht die Quelle.');
if (!listenWerte.some(w => BENUTZER_SCHLUESSEL.every(s => w.includes(s))))
    abbruch('sitzung.js enthaelt die Benutzer-Kette nicht.');
check('sitzung.js fuehrt beide Schluessel-Ketten', true);

let hatToken = false, hatBenutzer = false, hatListe = false, liestSpeicher = false;
begehe(qBaum, (n) => {
    if (n.type === 'Property' && n.key && (n.key.name || n.key.value)) {
        const name = n.key.name || n.key.value;
        if (name === 'token') hatToken = true;
        if (name === 'benutzer') hatBenutzer = true;
        if (name === 'tokenSchluessel') hatListe = true;
    }
    if (n.type === 'CallExpression' && n.callee && n.callee.type === 'MemberExpression'
        && n.callee.property && n.callee.property.name === 'getItem'
        && n.callee.object && n.callee.object.name === 'localStorage') liestSpeicher = true;
});
check('sitzung.js bietet token()', hatToken);
check('sitzung.js bietet benutzer()', hatBenutzer);
check('sitzung.js bietet tokenSchluessel()', hatListe);
check('sitzung.js liest wirklich aus localStorage', liestSpeicher);
if (fail) abbruch('die Quelle selbst ist unvollstaendig – Abschnitt 2 waere nicht deutbar.');

/* ══ 2. Die Regel ════════════════════════════════════════════════════════ */
console.log('\n\x1b[1m2. Kein zweiter Leser, keine zweite Liste\x1b[0m');
const SKRIPT_RE = /<script\b(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi;
let geprueft = 0, parseFehler = [];
const schuldig = [];

for (const p of JS_DATEIEN) {
    const kurz = path.relative(WURZEL, p);
    if (p === QUELLE) continue;
    const r = verstoesse(fs.readFileSync(p, 'utf8'), kurz);
    geprueft++;
    if (r.fehler) { parseFehler.push(kurz + ': ' + r.fehler); continue; }
    for (const t of r.liste) schuldig.push(`${kurz}:${t.zeile} (${t.art} ${t.wert})`);
}
for (const p of HTML_DATEIEN) {
    const kurz = path.relative(WURZEL, p);
    const txt = fs.readFileSync(p, 'utf8');
    let m;
    SKRIPT_RE.lastIndex = 0;
    while ((m = SKRIPT_RE.exec(txt)) !== null) {
        const inhalt = m[1];
        if (!inhalt.trim()) continue;
        // Zeilennummer des Fundes IM Dokument, nicht im Fragment
        const zeilenVersatz = txt.slice(0, m.index).split('\n').length - 1;
        const r = verstoesse(inhalt, kurz);
        geprueft++;
        if (r.fehler) { parseFehler.push(kurz + ' (Inline-Skript): ' + r.fehler); continue; }
        for (const t of r.liste) {
            schuldig.push(`${kurz}:${zeilenVersatz + (t.zeile || 0)} (${t.art} ${t.wert})`);
        }
    }
}
// Ein nicht parsebares Skript ist eine NICHT GEMESSENE Datei – das darf nicht
// wie "bestanden" aussehen.
if (parseFehler.length) abbruch(parseFehler.length + ' Quelle(n) parsen nicht:\n    '
                                + parseFehler.join('\n    '));
check(geprueft + ' Quellen geprueft (JS + Inline-Skripte)', geprueft >= 60, String(geprueft));
check('kein Schluessel-Literal in getItem oder in einer Liste ausserhalb sitzung.js',
      schuldig.length === 0, schuldig.join('; '));

/* ══ 3. Verfuegbarkeit: sitzung.js wird vor jedem Konsumenten geladen ════ */
console.log('\n\x1b[1m3. Einbindung und Reihenfolge je Seite\x1b[0m');
// Konsument = Datei, die JarvisSitzung benutzt. Ueber den AST bestimmt, damit
// eine Nennung im Kommentar keine Datei zum Konsumenten macht.
const konsumenten = new Set();
for (const p of JS_DATEIEN) {
    if (p === QUELLE) continue;
    const baum = parse(fs.readFileSync(p, 'utf8'), p);
    if (baum.__fehler) continue;
    let nutzt = false;
    begehe(baum, (n) => {
        if (n.type === 'MemberExpression' && n.property && n.property.name === 'JarvisSitzung') nutzt = true;
        if (n.type === 'Identifier' && n.name === 'JarvisSitzung') nutzt = true;
    });
    if (nutzt) konsumenten.add(path.basename(p));
}
check(konsumenten.size + ' Konsumenten-Skripte erkannt', konsumenten.size >= 50, String(konsumenten.size));

const TAG_RE = /<script[^>]*src="\/static\/(?:js|addin|excel-addin)\/([A-Za-z0-9_.-]+\.js)[^"]*"/g;
const fehlt = [], zuSpaet = [];
for (const p of HTML_DATEIEN) {
    const kurz = path.relative(WURZEL, p);
    const txt = fs.readFileSync(p, 'utf8');
    const folge = [];
    let m;
    TAG_RE.lastIndex = 0;
    while ((m = TAG_RE.exec(txt)) !== null) folge.push(m[1]);
    const benutzte = folge.filter(s => konsumenten.has(s));
    const inlineNutzung = /\bJarvisSitzung\b/.test(txt.replace(/<script[^>]*src=[^>]*><\/script>/g, ''));
    if (!benutzte.length && !inlineNutzung) continue;
    const i = folge.indexOf('sitzung.js');
    if (i < 0) { fehlt.push(kurz + ' (laedt ' + benutzte.slice(0, 3).join(', ') + ')'); continue; }
    const davor = folge.slice(0, i).filter(s => konsumenten.has(s));
    if (davor.length) zuSpaet.push(kurz + ' – davor: ' + davor.join(', '));
}
check('jede Seite mit einem Konsumenten laedt sitzung.js', fehlt.length === 0, fehlt.join('; '));
check('sitzung.js steht VOR jedem Konsumenten', zuSpaet.length === 0, zuSpaet.join('; '));

/* ── Bilanz ──────────────────────────────────────────────────────────── */
console.log('\n\x1b[1mErgebnis: ' + ok + '/' + (ok + fail) + '\x1b[0m');
process.exit(fail ? 1 : 0);
