#!/usr/bin/env python3
"""BSI H4 – Frontend ohne Inline-Skript: Voraussetzung fuer eine CSP ohne 'unsafe-inline'.

Befund H4 (BSI-Abgleich 29.09.2026): keine Content-Security-Policy, das
Sitzungstoken liegt in localStorage – ein einziges XSS ist eine
Kontouebernahme. Massnahme: CSP mit ``script-src 'self'`` (ohne
'unsafe-inline'), zunaechst Report-Only, und dafuer die Inline-Handler abbauen.

Eine solche CSP blockiert JEDEN Inline-Handler und JEDES Inline-Skript. Dieser
Waechter haelt die REGEL fest, nicht eine Liste: in keiner ausgelieferten Seite
und in keinem Markup, das ein Skript zusammenbaut, darf noch eins stehen –
sonst ist die Seite beim Umschalten auf "erzwingen" an dieser Stelle tot.

  [A] HTML-Dateien unter frontend/ (Parser, nicht Text): kein on*-Attribut,
      kein <script> ohne src (ausser Daten-Typen wie application/json), kein
      javascript:-Ziel.
  [B] JS-Dateien unter frontend/ (acorn, Syntaxbaum): kein String- oder
      Template-Literal, das ein on*=-Attribut in Markup schreibt; kein
      setAttribute('on…'); kein eval / new Function / Zeichenketten-Timer.

Ausgenommen: Fremdbibliotheken unter vendor/ (nicht unser Code; sie werden
als Datei geladen, ihr Inhalt zaehlt fuer script-src nicht).

Exit 0 = gruen, 1 = Regelverstoss, 2 = konnte nicht laufen.
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
OK = FAIL = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global OK, FAIL
    if cond:
        OK += 1
        print("  OK   " + name)
    else:
        FAIL += 1
        print("  FAIL " + name + (("\n         " + detail) if detail else ""))


def abbruch(grund: str) -> None:
    print("ABBRUCH (Exit 2): " + grund)
    sys.exit(2)


def ist_fremd(p: Path) -> bool:
    return "vendor" in p.relative_to(FRONTEND).parts


# Skript-Typen, die der Browser NICHT ausfuehrt – fuer script-src belanglos.
DATEN_TYPEN = {"application/json", "application/ld+json", "text/template",
               "text/x-template", "importmap-nein"}


class Fund(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.handler: list[str] = []
        self.inline: list[str] = []
        self.js_ziele: list[str] = []
        self._in_skript = False
        self._skript_zeile = 0
        self._skript_text = ""

    def handle_starttag(self, tag, attrs):
        zeile = self.getpos()[0]
        for k, v in attrs:
            k = (k or "").lower()
            if k.startswith("on") and len(k) > 2:
                self.handler.append("Z.%d <%s %s=…>" % (zeile, tag, k))
            if k in ("href", "src", "action", "formaction") and v \
                    and v.strip().lower().startswith("javascript:"):
                self.js_ziele.append("Z.%d <%s %s=%r>" % (zeile, tag, k, v[:40]))
        if tag == "script":
            a = {k.lower(): (v or "") for k, v in attrs}
            if "src" not in a and a.get("type", "").strip().lower() not in DATEN_TYPEN:
                self._in_skript = True
                self._skript_zeile = zeile
                self._skript_text = ""

    def handle_data(self, data):
        if self._in_skript:
            self._skript_text += data

    def handle_endtag(self, tag):
        if tag == "script" and self._in_skript:
            self._in_skript = False
            if self._skript_text.strip():
                self.inline.append("Z.%d %r" % (self._skript_zeile, self._skript_text.strip()[:60]))


def pruefe_html(text: str) -> Fund:
    f = Fund()
    f.feed(text)
    f.close()
    return f


# ─── Positivkontrolle der HTML-Messung ───────────────────────────────────────
print("[0] Positivkontrolle")
probe = pruefe_html('<body><button onclick="x()">a</button><script>var a=1;</script>'
                    '<a href="javascript:void(0)">b</a><script src="/a.js"></script>'
                    '<script type="application/json">{"a":1}</script>'
                    '<img src=x ONERROR=y></body>')
check("Parser findet zwei Inline-Handler (auch GROSS geschrieben)", len(probe.handler) == 2,
      repr(probe.handler))
check("Parser findet genau ein Inline-Skript (src und JSON zaehlen nicht)", len(probe.inline) == 1,
      repr(probe.inline))
check("Parser findet das javascript:-Ziel", len(probe.js_ziele) == 1, repr(probe.js_ziele))
if FAIL:
    abbruch("Messmethode erkennt die Probe nicht")

# ─── [A] HTML ────────────────────────────────────────────────────────────────
print("[A] HTML-Seiten unter frontend/")
seiten = sorted(p for p in FRONTEND.rglob("*.html") if not ist_fremd(p))
check("HTML-Seiten gefunden (Positivkontrolle, >= 15)", len(seiten) >= 15, str(len(seiten)))
for p in seiten:
    rel = p.relative_to(ROOT)
    f = pruefe_html(p.read_text(encoding="utf-8", errors="replace"))
    check("%s: kein Inline-Handler" % rel, not f.handler, "; ".join(f.handler[:8]))
    check("%s: kein Inline-Skript" % rel, not f.inline, "; ".join(f.inline[:5]))
    check("%s: kein javascript:-Ziel" % rel, not f.js_ziele, "; ".join(f.js_ziele[:5]))

# ─── [B] JS (Syntaxbaum) ─────────────────────────────────────────────────────
print("[B] JS-Dateien unter frontend/ (acorn)")
JS = r"""
const path = require('path'), fs = require('fs');
function hole(name) {
    const orte = [process.env[name.toUpperCase() + '_PATH'], name,
                  path.join(process.argv[2], 'data/node_modules', name),
                  path.join(process.argv[2], 'node_modules', name),
                  '/tmp/node_modules/' + name, '/usr/share/nodejs/' + name,
                  path.join(process.argv[2], 'node_modules/jsdom/node_modules', name)];
    for (const k of orte) { if (!k) continue; try { return require(k); } catch (e) {} }
    return null;
}
const acorn = hole('acorn');
if (!acorn) { console.log(JSON.stringify({fehlt: true})); process.exit(0); }
// Ein on*-Attribut in Markup: Leerraum/Anfuehrung/Tag-Rest davor, Name, '=',
// danach Anfuehrung, Backslash-Anfuehrung oder ein ${…}-Loch (Quasi-Ende).
const HANDLER = /(?:^|[\s"'\/])on[a-z]{3,}\s*=\s*(?:["'\\]|$)/i;
function kinder(n) { const o = []; for (const k in n) { const v = n[k];
    if (Array.isArray(v)) v.forEach(x => x && typeof x.type === 'string' && o.push(x));
    else if (v && typeof v.type === 'string') o.push(v); } return o; }
function walk(n, f) { f(n); kinder(n).forEach(k => walk(k, f)); }
function zeile(src, pos) { return src.slice(0, pos).split('\n').length; }
// Ein Literal ist nur dann Markup, wenn es ein Tag enthaelt ODER Teil eines
// Templates/einer Verkettung ist, die eines enthaelt – ein loses 'onclick='
// in einem Hilfetext waere kein Handler. Gemessen wird deshalb je
// zusammenhaengendem Ausdruck (Template bzw. +-Kette) der Gesamttext.
function textVon(n) {
    if (n.type === 'Literal' && typeof n.value === 'string') return n.value;
    if (n.type === 'TemplateLiteral') return n.quasis.map(q => q.value.cooked || q.value.raw).join('${}');
    if (n.type === 'BinaryExpression' && n.operator === '+') return textVon(n.left) + textVon(n.right);
    return '${}';
}
const res = {dateien: 0, fehler: [], funde: [], probe: null};
function pruefe(src, name) {
    let ast;
    try { ast = acorn.parse(src, {ecmaVersion: 'latest', sourceType: 'script', allowHashBang: true}); }
    catch (e) {
        try { ast = acorn.parse(src, {ecmaVersion: 'latest', sourceType: 'module'}); }
        catch (e2) { res.fehler.push(name + ': ' + e2.message); return []; }
    }
    const funde = [], gesehen = new Set();
    walk(ast, n => {
        // Markup-Ausdruecke: Template, +-Kette (nur die aeusserste), String-Literal
        const markup = n.type === 'TemplateLiteral' || n.type === 'Literal'
            || (n.type === 'BinaryExpression' && n.operator === '+');
        if (markup && !gesehen.has(n)) {
            // Nur die Glieder DERSELBEN Kette als gesehen markieren – ein
            // Bedingungs-Ausdruck darin ist eine eigene Kette und wird selbst gemessen.
            (function kette(m) { gesehen.add(m);
                if (m.type === 'BinaryExpression' && m.operator === '+') { kette(m.left); kette(m.right); } })(n);
            const t = textVon(n);
            if (/<[a-z]/i.test(t) && HANDLER.test(t)) {
                funde.push(name + ':' + zeile(src, n.start) + ' Markup mit on*-Attribut: '
                           + JSON.stringify(t.match(/.{0,40}on[a-z]{3,}\s*=.{0,30}/i)[0]));
            }
        }
        if (n.type === 'CallExpression') {
            const c = n.callee;
            const prop = c.type === 'MemberExpression' && !c.computed ? c.property.name : null;
            const a0 = n.arguments[0];
            if (prop === 'setAttribute' && a0 && a0.type === 'Literal'
                && typeof a0.value === 'string' && /^on/i.test(a0.value))
                funde.push(name + ':' + zeile(src, n.start) + ' setAttribute(' + JSON.stringify(a0.value) + ')');
            if (c.type === 'Identifier' && c.name === 'eval')
                funde.push(name + ':' + zeile(src, n.start) + ' eval()');
            const timer = (c.type === 'Identifier' ? c.name : prop);
            if ((timer === 'setTimeout' || timer === 'setInterval') && a0
                && (a0.type === 'Literal' || a0.type === 'TemplateLiteral' || a0.type === 'BinaryExpression'))
                funde.push(name + ':' + zeile(src, n.start) + ' ' + timer + ' mit Zeichenkette');
        }
        if (n.type === 'NewExpression' && n.callee.type === 'Identifier' && n.callee.name === 'Function')
            funde.push(name + ':' + zeile(src, n.start) + ' new Function()');
    });
    return funde;
}
// Positivkontrolle: jedes Muster muss in der Probe anschlagen
res.probe = pruefe([
    "el.innerHTML = `<button class=\"a\" onclick=\"go('${x}')\">x</button>`;",
    "h += '<img src=\"' + u + '\" ' + `onerror=\"this.remove()\">`;",
    "row.innerHTML = '<span>' + (l ? '<a href=\"' + l + '\" ' + 'onclick=\"x()\">' : '');",
    "b.setAttribute('onclick', 'x()');",
    "eval('1');",
    "setTimeout('tick()', 5);",
    "new Function('a', 'return a');",
    "var hilfe = 'Das Feld onclick= ist kein Markup';",   // darf NICHT anschlagen
    "el.addEventListener('click', go);",                  // darf NICHT anschlagen
].join('\n'), 'probe').length;
const wurzel = path.join(process.argv[2], 'frontend');
(function lauf(d) {
    for (const e of fs.readdirSync(d, {withFileTypes: true})) {
        const p = path.join(d, e.name);
        if (e.isDirectory()) { if (e.name !== 'vendor' && e.name !== 'node_modules') lauf(p); continue; }
        if (!e.name.endsWith('.js')) continue;
        res.dateien++;
        res.funde.push(...pruefe(fs.readFileSync(p, 'utf8'), path.relative(process.argv[2], p)));
    }
})(wurzel);
console.log(JSON.stringify(res));
"""
with tempfile.TemporaryDirectory() as tmp:
    jsdatei = Path(tmp) / "probe.js"
    jsdatei.write_text(JS)
    try:
        r = subprocess.run(["node", str(jsdatei), str(ROOT)], capture_output=True, text=True,
                           timeout=180)
        erg = json.loads((r.stdout or "").strip().splitlines()[-1])
    except Exception as e:  # noqa: BLE001
        abbruch("JS-Probe lief nicht: %s" % e)
if erg.get("fehlt"):
    abbruch("acorn nicht verfuegbar")
check("Positivkontrolle: Probe meldet genau 7 Funde (3 Markup, setAttribute, eval, Timer, Function)",
      erg["probe"] == 7, str(erg["probe"]))
if erg["probe"] != 7:
    abbruch("JS-Messmethode erkennt die Probe nicht")
check("JS-Dateien gefunden (Positivkontrolle, >= 50)", erg["dateien"] >= 50, str(erg["dateien"]))
check("alle JS-Dateien parsebar", not erg["fehler"], "; ".join(erg["fehler"][:5]))
check("kein Inline-Handler / eval in JS (%d Funde)" % len(erg["funde"]), not erg["funde"],
      "\n         ".join(erg["funde"][:80]))

print("\nErgebnis: %d OK, %d FAIL" % (OK, FAIL))
sys.exit(0 if FAIL == 0 else 1)
