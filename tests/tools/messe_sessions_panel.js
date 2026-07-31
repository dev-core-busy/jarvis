/* Baut aus den ECHTEN Dateien (portal.html-Styles + sessions.js) eine
 * eigenstaendige Seite und misst mit headless Chrome die tatsaechliche
 * Zeilenhoehe des Anwesenheits-Panels.
 *
 * Warum nicht jsdom: jsdom hat kein Layout, offsetHeight ist dort immer 0.
 * Die Frage "wie viele Benutzer sieht man ohne Scrollen" ist aber genau eine
 * Layout-Frage.
 *
 * Lauf:  node tests/tools/messe_sessions_panel.js
 */
'use strict';

const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const ROOT = path.resolve(__dirname, '..', '..');
const html = fs.readFileSync(path.join(ROOT, 'frontend', 'portal.html'), 'utf8');

// Styles und Panel-Markup aus der echten Seite herausloesen – so misst der
// Pruefstand die Regeln, die auch ausgeliefert werden.
// theme.css zuerst: dort stehen die CSS-Variablen (--border, --fg-rgb, …).
// Ohne sie faellt jede Farbe auf "transparent" zurueck und die Messung saehe
// zwar richtig aus, das Bild aber nicht.
const styles = [fs.readFileSync(path.join(ROOT, 'frontend/css/theme.css'), 'utf8')]
    .concat((html.match(/<style>([\s\S]*?)<\/style>/g) || [])
        .map((s) => s.replace(/<\/?style>/g, ''))).join('\n');
const wrap = html.match(/<div class="pt-usr-wrap"[\s\S]*?\n    <\/div>/);
if (!wrap) { console.error('Panel-Markup nicht gefunden'); process.exit(1); }

const sessionsJs = fs.readFileSync(path.join(ROOT, 'frontend/js/sessions.js'), 'utf8');

const N = 20;
const jetzt = Math.floor(Date.now() / 1000);
const users = [];
for (let i = 0; i < N; i++) {
    const on = i < 12;
    users.push({
        username: 'benutzer' + (i + 1),
        display: i % 4 === 0 ? 'nexus\\benutzer' + (i + 1) : 'benutzer' + (i + 1),
        online: on, kind: i === 3 ? 'api' : 'user', blocked: i === 5,
        last_login: jetzt - 3600, last_logout: on ? 0 : jetzt - 600,
        last_seen: on ? jetzt - 5 : jetzt - 4000,
        last_action: jetzt - (i * 260),
        last_action_label: ['Chat-Anfrage', 'Wissen durchsucht', 'Datei gespeichert',
                            'Support-Suche', 'Einstellung geändert'][i % 5],
        actions: i, idle_seconds: i * 260,
    });
}
const daten = { ok: true, online_window: 120, online: 12, total: N, may_block: true, users: users };

const seite = `<!DOCTYPE html><html><head><meta charset="utf-8">
<style>${styles}</style>
<style>body{margin:0;padding:60px 12px 12px;} .pt-usr-wrap{justify-content:flex-end;}
  #MESS{position:fixed;left:8px;top:8px;font:12px monospace;color:#0f0;z-index:99999;white-space:pre;}</style>
</head><body class="">
${wrap[0]}
<div id="MESS"></div>
<script>
  localStorage.setItem('jarvis_token','x:1:y');
  window.fetch = function(u){ return Promise.resolve({ok:true,status:200,
      json:function(){return Promise.resolve(${JSON.stringify(daten)});}}); };
<\/script>
<script>${sessionsJs}<\/script>
<script>
  UserSessions.init();
  document.getElementById('pt-usr-btn').click();
  setTimeout(function(){
    var it = document.querySelectorAll('.pt-usr-item');
    var liste = document.getElementById('pt-usr-list');
    var h = [].map.call(it, function(e){ return e.offsetHeight; });
    var einzel = h.length ? Math.round(h.reduce(function(a,b){return a+b;},0)/h.length) : 0;
    var sicht = liste.clientHeight;
    var umbruch = [].filter.call(document.querySelectorAll('.pt-usr-meta'), function(m){
        return m.scrollWidth > m.clientWidth + 1; }).length;
    var ueber = [].filter.call(it, function(e){
        return e.scrollWidth > e.clientWidth + 1; }).length;
    document.getElementById('MESS').textContent =
        'ZEILEN=' + h.length + ' MIN=' + Math.min.apply(null,h) + ' MAX=' + Math.max.apply(null,h) +
        ' SCHNITT=' + einzel + '\\nSICHTFENSTER=' + sicht +
        ' OHNE_SCROLL=' + (einzel ? Math.floor(sicht/einzel) : 0) +
        '\\nPANEL=' + document.getElementById('pt-usr-panel').offsetHeight +
        ' FILTER=' + ((document.getElementById('pt-usr-filter')||{}).offsetHeight || 0) +
        '\\nGEKUERZTE_META=' + umbruch + ' UEBERLAUF_ZEILEN=' + ueber;
  }, 400);
<\/script></body></html>`;

const datei = '/tmp/sess_panel.html';
fs.writeFileSync(datei, seite);

const out = execFileSync('google-chrome', [
    '--headless', '--disable-gpu', '--no-sandbox', '--virtual-time-budget=4000',
    '--screenshot=/tmp/sess_panel.png', '--window-size=560,760', '--dump-dom',
    'file://' + datei,
], { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] });

const m = out.match(/<div id="MESS">([\s\S]*?)<\/div>/);
console.log(m ? m[1].replace(/&#10;|\\n/g, '\n') : '(keine Messung gefunden)');
console.log('Screenshot: /tmp/sess_panel.png');
