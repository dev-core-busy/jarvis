/* Prueft die Willkommens-Beispiele: rendern sie, sind die Texte da, und greift die
 * Aenderung auch in einer BEREITS ausgelieferten Sitzung (Backend liefert nur
 * kind:"welcome" + Notfalltext, die Karte wird bei jeder Anzeige neu gebaut)? */
'use strict';
const fs = require('fs'), path = require('path');
const { JSDOM } = require(process.env.JSDOM_PATH || '/tmp/node_modules/jsdom');
const ROOT = path.resolve(__dirname, '..');
const res = [];
const check = (n, c, d) => { res.push({n, c: !!c, d}); console.log((c ? '  \x1b[32m✓\x1b[0m ' : '  \x1b[31m✗\x1b[0m ') + n + (!c && d ? ' – ' + d : '')); };

const chatjs = fs.readFileSync(path.join(ROOT, 'frontend/js/chat.js'), 'utf8');
const i18njs = fs.readFileSync(path.join(ROOT, 'frontend/js/i18n.js'), 'utf8');

// Liste der Beispiel-Keys aus dem Quelltext ziehen
const arr = chatjs.slice(chatjs.indexOf('_WELCOME_EXAMPLES = ['), chatjs.indexOf('];', chatjs.indexOf('_WELCOME_EXAMPLES = [')));
const keys = [...arr.matchAll(/key:\s*'([a-z0-9]+)'/g)].map(m => m[1]);
console.log('\n\x1b[1mBeispiel-Keys\x1b[0m');
check('genau 10 Beispiele', keys.length === 10, keys.join(','));
// Diese Keys standen fuer Faehigkeiten, die es hier NICHT gibt. Sie duerfen nicht
// zurueckkehren: 'web' (kein Web-Werkzeug), 'image' (generate_image laeuft ueber das
// aktive Profil = Textmodell), 'cron'/'multi' (cron_create und spawn_agent stehen in
// _BLOCKED_TOOLS_FOR_LDAP, also fuer Domaenen-Benutzer gesperrt).
['web', 'image', 'cron', 'multi'].forEach(k =>
  check(`'${k}' nicht mehr enthalten (Faehigkeit fehlt bzw. ist gesperrt)`,
        !keys.includes(k), keys.join(',')));
['jira', 'conf', 'ibs', 'multi2'].forEach(k =>
  check(`'${k}' vorhanden`, keys.includes(k), keys.join(',')));

// Gegenprobe am Backend: keiner der beworbenen Wege darf in der Sperrliste stehen.
const agentpy = fs.readFileSync(path.join(ROOT, 'backend/agent.py'), 'utf8');
const blocked = agentpy.slice(agentpy.indexOf('_BLOCKED_TOOLS_FOR_LDAP = '),
                              agentpy.indexOf('}', agentpy.indexOf('_BLOCKED_TOOLS_FOR_LDAP = ')));
['cron_create', 'spawn_agent'].forEach(t =>
  check(`${t} ist tatsaechlich gesperrt (Begruendung belegt)`, blocked.includes(t)));
const prompts = keys.map(k => {
  const m = i18njs.match(new RegExp("'chat\\.wex_" + k + "_prompt':\\s*'([^']*)'"));
  return (m && m[1]) || '';
}).join(' ');
// Praezise auf die AUFTRAGS-Anlage pruefen. Ein zu weites /wiederkehrend/ trifft
// sonst "wiederkehrende Themen" im IBS-Beispiel – ein Fehlalarm im Test selbst.
check('kein Prompt verlangt einen zeitgesteuerten Auftrag',
      !/wiederkehrenden Auftrag|jeden Montag um|zeitgesteuert|Richte einen .*Auftrag ein/i.test(prompts));
check('kein Prompt verlangt Sub-Agenten', !/eigenen Agenten|Agenten parallel/i.test(prompts));
check('kein Prompt verlangt Bildgenerierung', !/Generiere ein Bild/i.test(prompts));
check('kein Prompt verlangt Web-Recherche', !/im Web/i.test(prompts));

console.log('\n\x1b[1mi18n: jeder Key hat label/desc/prompt in DE UND EN\x1b[0m');
keys.forEach(k => ['label', 'desc', 'prompt'].forEach(part => {
  const key = `chat.wex_${k}_${part}`;
  const n = (i18njs.match(new RegExp("'" + key.replace('.', '\\.') + "'", 'g')) || []).length;
  check(`${key} (${n}x)`, n >= 2, `nur ${n}x`);
}));
check('keine wex_web-Reste', !i18njs.includes('wex_web'));
check('keine wex_image-Reste', !i18njs.includes('wex_image'));

console.log('\n\x1b[1mRendern in einer BESTEHENDEN Sitzung\x1b[0m');
const dom = new JSDOM('<div id="chat-messages"></div>', { runScripts: 'outside-only', url: 'https://localhost/chat' });
const { window } = dom;
window.eval(i18njs);
// Nur die Karten-Funktion isoliert nachbauen (chat.js ganz laden zieht Poll-Timer nach)
const fnStart = chatjs.indexOf('    const _WELCOME_EXAMPLES = [');
const fnEnd = chatjs.indexOf('\n    /** Setzt einen Beispiel-Prompt', fnStart) > 0
  ? chatjs.indexOf('\n    /** Setzt einen Beispiel-Prompt', fnStart)
  : chatjs.indexOf('\n    function _useExamplePrompt', fnStart);
window.eval('var _useExamplePrompt = function(){};' + chatjs.slice(fnStart, fnEnd));
// Backend-Eintrag einer BEREITS ausgelieferten Sitzung (nur kind + Notfalltext)
const entry = { role: 'bot', kind: 'welcome', text: 'Alter Notfalltext vom Server' };
const card = window.eval('_renderWelcomeCard')(entry);
const txt = card.textContent;
check('Karte gerendert', !!card && card.className === 'welcome-card');
check('10 Chips', card.querySelectorAll('.wex-chip').length === 10,
      String(card.querySelectorAll('.wex-chip').length));
check('neues Jira-Beispiel sichtbar', /Tickets auswerten/.test(txt), txt.slice(0, 200));
check('neues Confluence-Beispiel sichtbar', /Confluence durchsuchen/.test(txt));
check('neues IBS-Beispiel sichtbar', /Kundenvorg/.test(txt));
check('neues Mehrquellen-Beispiel sichtbar', /Alle Quellen auf einmal/.test(txt));
check('altes Bild-Beispiel verschwunden', !/Bild generieren/.test(txt));
check('altes Web-Beispiel verschwunden', !/Web-Recherche/.test(txt));
check('altes Cron-Beispiel verschwunden', !/Auftrag wiederholen/.test(txt));
check('altes Multi-Agenten-Beispiel verschwunden', !/Mehrere Agenten/.test(txt));
check('alter Server-Notfalltext NICHT verwendet (i18n gewinnt)',
      !txt.includes('Alter Notfalltext vom Server'));

const bad = res.filter(r => !r.c);
console.log(`\n\x1b[1mErgebnis: ${res.length - bad.length}/${res.length}\x1b[0m`);
window.close();
process.exit(bad.length ? 1 : 0);
