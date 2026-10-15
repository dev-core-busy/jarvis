/* Loeschkonzept (BSI M9, 2026-10-12): Fristen je Datenart in den
 * System-Einstellungen. Das eigene Gedaechtnis steht seit 2026-10-15 in der
 * Wissen-Seite (js/gedaechtnis.js) – /settings erreichen nur Admins.
 *
 * Fristen: GET/POST /api/settings/loeschfristen (Admin). Leeres Feld = die
 * Einstellung entfernen (dann gilt Umgebungsvariable bzw. Vorgabe), 0 =
 * dauerhaft. Die Grenzen prueft der Server; hier wird nur angezeigt.
 */
(function () {
    'use strict';

    var ARTEN = ['chats', 'prompts', 'protokoll', 'sicherheit'];

    function T(k) { return (window.t ? window.t(k) : k); }
    function kopf(extra) {
        return window.JarvisSitzung ? window.JarvisSitzung.kopfsatz(extra) : (extra || {});
    }
    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text !== undefined && text !== null) e.textContent = text;
        return e;
    }

    function status(text, fehler) {
        var s = document.getElementById('lk-status');
        if (!s) return;
        s.textContent = text || '';
        s.classList.toggle('lk-fehler', !!fehler);
    }

    function zeileBauen(art, f) {
        var z = el('div', 'lk-zeile');
        var lbl = el('label', 'lk-label', T('lk.art.' + art));
        lbl.setAttribute('for', 'lk-wert-' + art);
        var inp = el('input');
        inp.type = 'number';
        inp.min = '0';
        inp.max = '3650';
        inp.step = '1';
        inp.id = 'lk-wert-' + art;
        inp.className = 'lk-wert';
        inp.dataset.art = art;
        inp.placeholder = String(f.vorgabe);
        if (f.quelle === 'einstellung') inp.value = String(f.tage);
        var info = el('span', 'lk-info');
        var wirksam = f.tage === 0 ? T('lk.dauerhaft') : T('lk.tage').replace('{n}', f.tage);
        info.textContent = T('lk.wirksam').replace('{wert}', wirksam)
            .replace('{quelle}', T('lk.quelle.' + f.quelle));
        z.appendChild(lbl);
        z.appendChild(inp);
        z.appendChild(info);
        return z;
    }

    async function fristenLaden() {
        var box = document.getElementById('lk-zeilen');
        if (!box) return;
        try {
            var r = await fetch('/api/settings/loeschfristen', { headers: kopf() });
            if (!r.ok) {
                // Kein Admin: Abschnitt bleibt ohne Felder, aber mit Grund
                box.textContent = r.status === 403 ? T('lk.nur_admin') : T('common.error') + ' (' + r.status + ')';
                ['lk-speichern', 'lk-jetzt'].forEach(function (id) {
                    var b = document.getElementById(id);
                    if (b) b.hidden = true;
                });
                return;
            }
            var d = await r.json();
            box.textContent = '';
            ARTEN.forEach(function (art) {
                if (d.fristen && d.fristen[art]) box.appendChild(zeileBauen(art, d.fristen[art]));
            });
        } catch (e) {
            box.textContent = T('common.error') + ': ' + e.message;
        }
    }

    async function fristenSpeichern(sofort) {
        var werte = {};
        document.querySelectorAll('#lk-zeilen .lk-wert').forEach(function (inp) {
            var v = inp.value.trim();
            werte[inp.dataset.art] = v === '' ? null : Number(v);
        });
        status(T('lk.speichere'));
        try {
            var r = await fetch('/api/settings/loeschfristen', {
                method: 'POST',
                headers: kopf({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ fristen: werte, sofort: sofort === true })
            });
            var d = await r.json().catch(function () { return {}; });
            if (!r.ok) {
                status(d.error || ('HTTP ' + r.status), true);   // Fehler bleibt stehen
                return;
            }
            var msg = T('lk.gespeichert');
            if (d.lauf && d.lauf.removed) {
                var summe = 0;
                Object.keys(d.lauf.removed).forEach(function (k) { summe += Number(d.lauf.removed[k]) || 0; });
                msg = T('lk.bereinigt').replace('{n}', summe);
            }
            status(msg);
            setTimeout(function () { status(''); }, 6000);
            fristenLaden();
        } catch (e) {
            status(T('common.error') + ': ' + e.message, true);
        }
    }

    function init() {
        if (!document.getElementById('lk-fristen')) return;
        var s = document.getElementById('lk-speichern');
        var j = document.getElementById('lk-jetzt');
        if (s && !s._lk) { s._lk = true; s.addEventListener('click', function () { fristenSpeichern(false); }); }
        if (j && !j._lk) { j._lk = true; j.addEventListener('click', function () { fristenSpeichern(true); }); }
        fristenLaden();
    }

    window.JarvisLoeschkonzept = { init: init, fristenLaden: fristenLaden };
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
    else init();
    // Sprachwechsel: Beschriftungen der dynamischen Zeilen neu aufbauen
    window.addEventListener('jarvis-lang-changed', function () { fristenLaden(); });
})();
