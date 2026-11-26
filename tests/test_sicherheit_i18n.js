#!/usr/bin/env node
/* Waechter: Der Sicherheits-Reiter ist in jeder Oberflaechensprache uebersetzt.
 *
 * GEMELDET 2026-11-26: "bei Einstellung FR sind unter Einstellungen →
 * Sicherheit → Berechtigungen zuweisen einige Buttons und Texte noch deutsch".
 * Drei Ursachen, je eine Pruefung:
 *
 *   1. MARKUP ohne Schluessel – im Reiter und in den beiden Hilfe-Popups
 *      (Sicherheitsschicht, Egress-Sperre) traegt jeder sichtbare Text ein
 *      data-i18n/data-i18n-html, jedes title/placeholder/aria-label sein
 *      data-i18n-*. Ausnahmen (sprachneutral) stehen EINZELN mit Grund in
 *      NEUTRAL. Jeder benutzte Schluessel steht im DE-Block.
 *   2. FESTE TEXTE IM CODE – die Module des Reiters bauen keine deutsche
 *      Zeichenkette ausserhalb von T()/t() (Syntaxbaum, acorn). Rueckfalltexte
 *      neben einem Schluessel ([schluessel, text]) sind keine Festtexte.
 *   3. KEIN NEUAUFBAU BEIM SPRACHWECHSEL – jedes dieser Module hoert auf
 *      'jarvis-lang-changed' (Regel); fuer security_incidents.js gemessen:
 *      FR zeigt den Firewall-Status franzoesisch, und ein Wechsel auf DE baut
 *      ihn deutsch neu auf.
 *
 *   node tests/test_sicherheit_i18n.js   Exit 0 = gruen, 1 = Befund, 2 = konnte nicht laufen
 */
'use strict';
require('./lib/bilanz')();
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('./lib/jsdom_laden')();
const acorn = require('./lib/acorn_laden')();

const ROOT = path.resolve(__dirname, '..');
const FRONT = path.join(ROOT, 'frontend');
let ok = 0, fail = 0;
function check(cond, label, detail) {
    if (cond) { ok++; console.log('  \x1b[32m✓\x1b[0m ' + label); }
    else { fail++; console.log('  \x1b[31m✗\x1b[0m ' + label + (detail ? ' – ' + detail : '')); }
}
function abbruch(grund) { console.log('\nABBRUCH: ' + grund); process.exit(2); }

// ── Woerterbuch ────────────────────────────────────────────────────────────
const SRC_I18N = fs.readFileSync(path.join(FRONT, 'js', 'i18n.js'), 'utf8');
const SRC_FR = fs.readFileSync(path.join(FRONT, 'js', 'i18n_fr.js'), 'utf8');
const SRC_NL = fs.readFileSync(path.join(FRONT, 'js', 'i18n_nl.js'), 'utf8');
let I;
try {
    const a = SRC_I18N.indexOf('const _I18N = {'), e = SRC_I18N.indexOf('\n};', a);
    I = new Function(SRC_I18N.slice(a, e + 3) + ';\n' + SRC_FR + ';\n' + SRC_NL + ';\nreturn _I18N;')();
} catch (e) { abbruch('Woerterbuch nicht auswertbar: ' + e.message); }

// ── 1. Markup ──────────────────────────────────────────────────────────────
console.log('\n1. Markup des Reiters und der Hilfe-Popups');
const HTML = fs.readFileSync(path.join(FRONT, 'settings.html'), 'utf8');
const WURZELN = ['settings-tab-security', 'sec-secdoc-modal', 'sec-fwdoc-modal'];
/* Sprachneutral – je Eintrag der Grund. */
const NEUTRAL = [
    [/^🖨️ PDF$/, 'Knopfbeschriftung "PDF" ist in allen Sprachen gleich'],
    [/^https:\/\/idp\.firma\.local\/…$/, 'Beispieladresse als Platzhalter'],
    [/^firma\.de$/, 'Beispieldomaene als Platzhalter'],
    [/^192\.0\.2\.10$/, 'Dokumentationsadresse als Platzhalter'],
];
function neutral(s) { return NEUTRAL.some(function (n) { return n[0].test(s); }); }

function luecken(doc) {
    const aus = [];
    WURZELN.forEach(function (id) {
        const w = doc.getElementById(id);
        if (!w) { aus.push('Wurzel fehlt: #' + id); return; }
        const it = doc.createTreeWalker(w, 4);
        let n;
        while ((n = it.nextNode())) {
            const s = n.textContent.replace(/\s+/g, ' ').trim();
            if (!s || !/[A-Za-zÄÖÜäöüß]{2,}/.test(s) || neutral(s)) continue;
            const p = n.parentElement;
            if (p.closest('script,style,[data-i18n],[data-i18n-html]')) continue;
            aus.push('#' + id + ' Text: ' + s.slice(0, 70));
        }
        w.querySelectorAll('[title],[placeholder],[aria-label]').forEach(function (el) {
            [['title', 'data-i18n-title'], ['placeholder', 'data-i18n-placeholder'],
             ['aria-label', 'data-i18n-aria']].forEach(function (pa) {
                const v = el.getAttribute(pa[0]);
                if (!v || !/[A-Za-zÄÖÜäöü]{3,}/.test(v) || neutral(v) || el.hasAttribute(pa[1])) return;
                aus.push('#' + id + ' ' + pa[0] + ': ' + v.slice(0, 70));
            });
        });
    });
    return aus;
}

const dom = new JSDOM(HTML);
const doc = dom.window.document;
const nSchluessel = WURZELN.reduce(function (s, id) {
    const w = doc.getElementById(id);
    return s + (w ? w.querySelectorAll('[data-i18n],[data-i18n-html]').length : 0);
}, 0);
if (nSchluessel < 200) abbruch('Positivkontrolle: nur ' + nSchluessel + ' Schluessel-Elemente in den Wurzeln – Schnitt falsch?');
// Positivkontrolle der Sonde: ein eingeschmuggelter Text OHNE Schluessel
// und ein Attribut ohne data-i18n-* werden gefunden.
{
    const d2 = new JSDOM(HTML).window.document;
    const p = d2.createElement('p'); p.textContent = 'Eingeschmuggelter Satz';
    d2.getElementById('sec-fwdoc-modal').appendChild(p);
    const b = d2.createElement('button'); b.setAttribute('title', 'Ohne Schluessel');
    d2.getElementById('settings-tab-security').appendChild(b);
    const l = luecken(d2);
    if (!l.some(function (x) { return x.indexOf('Eingeschmuggelter') >= 0; })
        || !l.some(function (x) { return x.indexOf('Ohne Schluessel') >= 0; })) {
        abbruch('Positivkontrolle: die Sonde findet einen Text/ein Attribut ohne Schluessel nicht');
    }
}
const l1 = luecken(doc);
check(l1.length === 0, 'jeder Text und jedes Attribut traegt einen Schluessel (' + nSchluessel + ' Elemente)',
      l1.slice(0, 8).join(' | ') + (l1.length > 8 ? ' … (+' + (l1.length - 8) + ')' : ''));
const fehlend = [];
WURZELN.forEach(function (id) {
    doc.getElementById(id).querySelectorAll('[data-i18n],[data-i18n-html],[data-i18n-title],[data-i18n-placeholder],[data-i18n-aria]')
        .forEach(function (el) {
            ['data-i18n', 'data-i18n-html', 'data-i18n-title', 'data-i18n-placeholder', 'data-i18n-aria'].forEach(function (a) {
                const k = el.getAttribute(a);
                if (k && !(k in I.de)) fehlend.push(k);
            });
        });
});
check(fehlend.length === 0, 'jeder benutzte Schluessel steht im DE-Block', fehlend.slice(0, 8).join(', '));
['secdoc.b19', 'fwdoc.b09', 'security.eg_intro'].forEach(function (k) {
    check(I.fr[k] && I.fr[k] !== I.de[k] && I.nl[k] && I.nl[k] !== I.de[k],
          k + ': FR und NL sind uebersetzt, nicht kopiert');
});

// ── 2. Feste Texte im Code ─────────────────────────────────────────────────
console.log('\n2. Feste Texte in den Modulen des Reiters');
const MODULE = ['security_incidents.js', 'rechte_matrix.js', 'settings_ad.js', 'settings_idp.js',
                'totp_admin.js', 'fernzugang.js'];
/* "Sieht deutsch aus": ein Umlaut/ß oder ein haeufiges Funktionswort, UND die
 * Zeichenkette ist kein Bezeichner (Klassen, Ids, Schluessel haben keinen
 * Leerraum und keinen Umlaut). Grob, aber mit Positivkontrolle unten. */
const DEUTSCH = /[äöüÄÖÜß]|\b(der|die|das|und|nicht|mit|für|ist|wird|kein|keine|eine?|wurde|bitte|oder|nur|noch|beim|zum|zur|Fehler|Benutzer|aktiv|gesetzt|eingerichtet|läuft|verfügbar)\b/;
const UEBERS = new Set(['T', 't', '_t', 'TX']);
function walk(n, cb, eltern) {
    if (!n || typeof n.type !== 'string') return;
    cb(n, eltern);
    const e2 = eltern.concat([n]);
    for (const k in n) {
        if (k === 'loc' || k === 'start' || k === 'end') continue;
        const v = n[k];
        if (Array.isArray(v)) v.forEach(function (x) { if (x && typeof x.type === 'string') walk(x, cb, e2); });
        else if (v && typeof v.type === 'string') walk(v, cb, e2);
    }
}
function festtexte(src) {
    const ast = acorn.parse(src, { ecmaVersion: 'latest', sourceType: 'script', locations: true });
    const aus = [];
    walk(ast, function (n, eltern) {
        let s = null;
        if (n.type === 'Literal' && typeof n.value === 'string') s = n.value;
        else if (n.type === 'TemplateElement') s = n.value.cooked;
        if (s == null) return;
        // Im Argument eines Uebersetzungsaufrufs / einer Ausnahme? Dann kein Festtext.
        for (let i = eltern.length - 1; i >= 0; i--) {
            const e = eltern[i];
            if (e.type === 'CallExpression') {
                const c = e.callee;
                const nm = c.type === 'Identifier' ? c.name : (c.type === 'MemberExpression' && c.property.name);
                if (UEBERS.has(nm) && !(c.type === 'MemberExpression' && c.object.name !== 'window')) return;
                // Hilfsaufruf mit Schluessel daneben (hinweis(box, 'k.x', 'Rueckfall'))
                if (e.arguments.some(function (x) {
                    return x.type === 'Literal' && /^[a-z]+\.[\w.]+$/.test(String(x.value));
                })) return;
            }
            if (e.type === 'NewExpression' && e.callee.name === 'Error') return;
            // [schluessel, rueckfalltext] – die Rueckfall-Form der Tabellen
            if (e.type === 'ArrayExpression' && e.elements.length === 2 && e.elements[0]
                && e.elements[0].type === 'Literal' && /^[a-z]+\.[\w.]+$/.test(String(e.elements[0].value))) return;
        }
        const txt = s.replace(/data-tabfill(-nein)?="[^"]*"/g, '').replace(/<[^>]+>/g, ' ');
        if (!/\s/.test(txt.trim()) && !/[äöüÄÖÜß]/.test(txt)) return;
        if (!DEUTSCH.test(txt)) return;
        aus.push(n.loc.start.line + ': ' + s.replace(/\s+/g, ' ').slice(0, 70));
    }, []);
    return aus;
}
{
    const probe = festtexte("box.innerHTML = '<b>Nicht vollständig eingerichtet</b>';\n"
        + "x = T('a.b', 'Nicht vollständig eingerichtet');\n"
        + "y = window.t('a.c') + ['security.k', 'Rückfall für den Schlüssel'][1];\n"
        + "throw new Error('unbekannte Freigabe: ' + f);\n"
        + "z = 'sec-ssh-h-aus';\n"
        + "hinweis(box, 'security.totp_none', 'Kein Konto hat die Anmeldung eingeschaltet.');\n");
    if (probe.length !== 1 || probe[0].indexOf('1:') !== 0) {
        abbruch('Positivkontrolle der Literal-Sonde: erwartet genau Zeile 1, gefunden ' + JSON.stringify(probe));
    }
}
MODULE.forEach(function (m) {
    const f = festtexte(fs.readFileSync(path.join(FRONT, 'js', m), 'utf8'));
    check(f.length === 0, m + ': keine deutschen Festtexte ausserhalb von T()', f.slice(0, 5).join(' | '));
});

// ── 3. Sprachwechsel ───────────────────────────────────────────────────────
console.log('\n3. Neuaufbau beim Sprachwechsel');
MODULE.forEach(function (m) {
    const ast = acorn.parse(fs.readFileSync(path.join(FRONT, 'js', m), 'utf8'), { ecmaVersion: 'latest' });
    let gefunden = false;
    walk(ast, function (n) {
        if (n.type === 'CallExpression' && n.callee.type === 'MemberExpression'
            && n.callee.property.name === 'addEventListener' && n.callee.object.name === 'window'
            && n.arguments[0] && n.arguments[0].value === 'jarvis-lang-changed') gefunden = true;
    }, []);
    check(gefunden, m + ': hoert am WINDOW auf jarvis-lang-changed (i18n.js loest es dort aus)');
});

(async function () {
    const html = '<!doctype html><html><body><div id="sec-egress-status"></div>'
        + '<button id="sec-egress-setup"></button></body></html>';
    const w = new JSDOM(html, { runScripts: 'outside-only', url: 'https://x.test/settings' }).window;
    w.localStorage.setItem('jarvis_lang', 'fr');
    w.JarvisSitzung = { token: function () { return 't'; } };
    const STAND = { ok: true, configured: true, user_exists: true, user: 'u', uid: 1,
                    nft_active: true, service_enabled: true, resolvers: ['192.0.2.53'] };
    let abrufe = 0;
    w.fetch = function (url) {
        abrufe++;
        const body = String(url).split('?')[0] === '/api/security/egress' ? STAND : {};
        return Promise.resolve({ ok: true, json: function () { return Promise.resolve(body); } });
    };
    try {
        // EIN eval: die const _I18N aus i18n.js gilt sonst nicht in den Folgedateien
        w.eval(SRC_I18N + '\n' + SRC_FR + '\n' + SRC_NL);
        w.eval(fs.readFileSync(path.join(FRONT, 'js', 'security_incidents.js'), 'utf8'));
    } catch (e) { abbruch('Module nicht ladbar: ' + e.message); }
    const M = w.SecurityIncidents;
    if (!M || w._lang !== 'fr') abbruch('Positivkontrolle: SecurityIncidents fehlt oder Sprache nicht fr');
    M.renderEgress(STAND);
    const fr = w.document.getElementById('sec-egress-status').textContent;
    check(fr.indexOf('Règle de pare-feu active') >= 0 && fr.indexOf('Résolveurs DNS autorisés') >= 0,
          'FR: Firewall-Status franzoesisch', fr.slice(0, 120));
    check(fr.indexOf('Firewall-Regel aktiv') < 0 && fr.indexOf('Erlaubte DNS') < 0, 'FR: kein deutscher Rest', fr.slice(0, 120));
    // Sprachwechsel: Reiter gilt als gezeigt, dann DE waehlen
    M._bind(); M._gezeigt = true;
    abrufe = 0;
    w.setLang('de');
    await new Promise(function (r) { setTimeout(r, 50); });
    const de = w.document.getElementById('sec-egress-status').textContent;
    check(abrufe > 0, 'Sprachwechsel laedt den gezeigten Reiter neu (' + abrufe + ' Abrufe)');
    check(de.indexOf('Firewall-Regel aktiv (nftables)') >= 0, 'nach Wechsel auf DE: Status deutsch', de.slice(0, 120));
    abrufe = 0;
    w.applyLang();
    await new Promise(function (r) { setTimeout(r, 30); });
    check(abrufe === 0, 'applyLang() ohne Sprachwechsel laedt NICHT neu (keine Schleife)');
    w.close();
    console.log('\n' + ok + ' OK, ' + fail + ' FAIL');
    process.exit(fail ? 1 : 0);
})();
