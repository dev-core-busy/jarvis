/**
 * Findet Platzhalterfelder, die ein Modul als HTML-TEXT erzeugt
 * ('<input … placeholder="' + x + '">' oder `<textarea placeholder="${x}">`).
 *
 * Gemessen am Syntaxbaum: zu einer Ausdruckskette aus '+'-Verknuepfungen bzw.
 * einem Template-Literal wird der Text zusammengesetzt, jeder eingesetzte
 * Ausdruck wird zu einem neutralen Zeichen. Darin werden die <input>/<textarea>-
 * Tags gesucht. Ein Tag, das in der Kette nicht endet, ist UNENTSCHEIDBAR und
 * wird als solches gemeldet – nie still uebergangen.
 *
 * Liefert je Fund { zeile, tag, entscheidung } mit entscheidung in
 * 'tabfill' | 'nein' | 'kennwort' | 'offen' | 'unentscheidbar'.
 */
'use strict';

const LUECKE = '\u0001';

function kettenText(n) {
    if (!n) return null;
    if (n.type === 'Literal' && typeof n.value === 'string') return n.value;
    if (n.type === 'TemplateLiteral') {
        let s = '';
        n.quasis.forEach((q, i) => {
            s += q.value.cooked !== null && q.value.cooked !== undefined ? q.value.cooked : q.value.raw;
            if (i < n.expressions.length) s += LUECKE;
        });
        return s;
    }
    if (n.type === 'BinaryExpression' && n.operator === '+') {
        const l = kettenText(n.left), r = kettenText(n.right);
        return (l === null ? LUECKE : l) + (r === null ? LUECKE : r);
    }
    return null;
}

function entscheide(tag) {
    if (/\sdata-tabfill-nein\s*=\s*["'][^"'\s]/.test(tag)) return 'nein';
    if (/\sdata-(?:i18n-)?tabfill(?=[\s=>\/]|$)/.test(tag)) return 'tabfill';
    if (/\stype\s*=\s*["']password["']/i.test(tag)) return 'kennwort';
    return 'offen';
}

function tagsIn(text) {
    const fund = [];
    const re = /<(input|textarea)\b/gi;
    let m;
    while ((m = re.exec(text))) {
        // Ende des Tags: das erste '>' ausserhalb von Anfuehrungszeichen.
        let i = m.index + m[0].length, q = null, ende = -1;
        for (; i < text.length; i++) {
            const c = text[i];
            if (q) { if (c === q) q = null; }
            else if (c === '"' || c === "'") q = c;
            else if (c === '>') { ende = i; break; }
        }
        const tag = ende < 0 ? text.slice(m.index) : text.slice(m.index, ende + 1);
        if (!/\splaceholder\s*=/.test(tag)) continue;
        fund.push({ tag, entscheidung: ende < 0 ? 'unentscheidbar' : entscheide(tag) });
    }
    return fund;
}

/** Alle Funde einer Quelldatei; null bei Parse-Fehler. */
function sonde(acorn, src) {
    let ast;
    try { ast = acorn.parse(src, { ecmaVersion: 2022, locations: true, sourceType: 'script' }); }
    catch (e) {
        try { ast = acorn.parse(src, { ecmaVersion: 2022, locations: true, sourceType: 'module' }); }
        catch (e2) { return null; }
    }
    const fund = [];
    (function lauf(n, inKette) {
        if (!n || typeof n !== 'object') return;
        const istKette = (n.type === 'BinaryExpression' && n.operator === '+') ||
                         n.type === 'TemplateLiteral' ||
                         (n.type === 'Literal' && typeof n.value === 'string');
        if (istKette && !inKette) {
            const t = kettenText(n);
            if (t) tagsIn(t).forEach(f => fund.push(Object.assign({ zeile: n.loc.start.line }, f)));
        }
        for (const k in n) {
            if (k === 'loc') continue;
            const v = n[k];
            // Eingesetzte Ausdruecke eines Templates sind eigene Ketten.
            const weiter = istKette && !(n.type === 'TemplateLiteral' && k === 'expressions');
            if (Array.isArray(v)) v.forEach(c => lauf(c, weiter));
            else if (v && typeof v.type === 'string') lauf(v, weiter);
        }
    })(ast, false);
    return fund;
}

module.exports = { sonde, tagsIn, entscheide };
