/* Mein Gedaechtnis (BSI M9): das eigene Gedaechtnis einsehen und
 * einzelne Eintraege loeschen. GET/DELETE /api/memory – der Server liefert und
 * loescht immer nur das Gedaechtnis des angemeldeten Benutzers.
 *
 * 2026-10-15 aus loeschkonzept.js herausgeloest und von den System-
 * Einstellungen in die Wissen-Seite (/wissen, Container wi-sec-gedaechtnis)
 * verschoben: /settings leitet Nicht-Admins nach /portal um, die Funktion war
 * dort also faktisch admin-only – obwohl sie fuer JEDEN Benutzer gedacht ist.
 *
 * Aufruf: JarvisGedaechtnis.laden(box) – box ist der Listen-Container.
 */
(function () {
    'use strict';

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

    async function laden(box) {
        if (!box) return;
        try {
            var r = await fetch('/api/memory', { headers: kopf() });
            if (!r.ok) { box.textContent = T('common.error') + ' (' + r.status + ')'; return; }
            var d = await r.json();
            box.textContent = '';
            var liste = d.eintraege || [];
            if (!liste.length) { box.appendChild(el('div', 'lk-leer', T('lk.gedaechtnis_leer'))); return; }
            liste.forEach(function (e) {
                var z = el('div', 'lk-mem');
                var text = el('div', 'lk-mem-text');
                text.appendChild(el('b', '', e.key));
                text.appendChild(el('span', 'lk-mem-wert', ' – ' + e.value));
                if (e.updated) text.appendChild(el('div', 'lk-mem-zeit', (e.updated || '').replace('T', ' ').slice(0, 16)));
                var btn = el('button', 'kb-hdr-btn lk-mem-del');
                btn.type = 'button';
                btn.title = T('common.delete');
                btn.setAttribute('aria-label', T('common.delete'));
                btn.innerHTML = window.JarvisIcons ? window.JarvisIcons.trash() : '';
                btn.addEventListener('click', function () { eintragLoeschen(e.key, z, btn); });
                z.appendChild(text);
                z.appendChild(btn);
                box.appendChild(z);
            });
        } catch (e) {
            box.textContent = T('common.error') + ': ' + e.message;
        }
    }

    async function eintragLoeschen(key, zeile, btn) {
        btn.disabled = true;
        try {
            var r = await fetch('/api/memory', {
                method: 'DELETE',
                headers: kopf({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ key: key })
            });
            if (!r.ok) {
                var d = await r.json().catch(function () { return {}; });
                btn.disabled = false;
                zeile.appendChild(el('div', 'lk-fehler', d.error || ('HTTP ' + r.status)));
                return;
            }
            var box = zeile.parentNode;
            zeile.remove();
            // Letzter Eintrag weg: dieselbe Leer-Anzeige wie beim Laden
            if (box && !box.querySelector('.lk-mem')) box.appendChild(el('div', 'lk-leer', T('lk.gedaechtnis_leer')));
        } catch (e) {
            btn.disabled = false;
            zeile.appendChild(el('div', 'lk-fehler', e.message));
        }
    }

    window.JarvisGedaechtnis = { laden: laden };
})();
