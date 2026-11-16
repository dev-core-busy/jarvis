/* Mein Gedaechtnis (BSI M9): das eigene Gedaechtnis einsehen und
 * einzelne Eintraege loeschen. GET/DELETE /api/memory – der Server liefert und
 * loescht immer nur das Gedaechtnis des angemeldeten Benutzers.
 *
 * 2026-10-15 aus loeschkonzept.js herausgeloest und von den System-
 * Einstellungen in die Wissen-Seite (/wissen, Container wi-sec-gedaechtnis)
 * verschoben: /settings leitet Nicht-Admins nach /portal um, die Funktion war
 * dort also faktisch admin-only – obwohl sie fuer JEDEN Benutzer gedacht ist.
 *
 * 2026-11-16: Knopf "Alles löschen" (DELETE /api/memory mit {"alle": true}).
 * Er steht nur da, solange es Eintraege gibt – ein Loeschknopf ueber einer
 * leeren Liste verspricht eine Wirkung, die es nicht gibt.
 *
 * Aufruf: JarvisGedaechtnis.laden(box, alleKnopf) – box ist der Listen-
 * Container, alleKnopf (optional) der Knopf "Alles löschen".
 */
(function () {
    'use strict';

    // window.t kennt keine Platzhalter – {name} wird hier ersetzt.
    function T(k, p) {
        var s = window.t ? window.t(k) : k;
        Object.keys(p || {}).forEach(function (n) { s = s.split('{' + n + '}').join(String(p[n])); });
        return s;
    }
    function kopf(extra) {
        return window.JarvisSitzung ? window.JarvisSitzung.kopfsatz(extra) : (extra || {});
    }
    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text !== undefined && text !== null) e.textContent = text;
        return e;
    }

    // Knopf "Alles löschen": sichtbar genau dann, wenn die Liste Eintraege hat.
    var _alleKnopf = null;
    function anzahl(box) { return box ? box.querySelectorAll('.lk-mem').length : 0; }
    function alleKnopfZeigen(box) {
        if (_alleKnopf) _alleKnopf.hidden = anzahl(box) === 0;
    }
    function leerAnzeigen(box) {
        box.textContent = '';
        box.appendChild(el('div', 'lk-leer', T('lk.gedaechtnis_leer')));
        alleKnopfZeigen(box);
    }

    async function laden(box, alleKnopf) {
        if (!box) return;
        if (alleKnopf) {
            _alleKnopf = alleKnopf;
            if (!alleKnopf._gebunden) {
                alleKnopf._gebunden = true;
                alleKnopf.addEventListener('click', function () { alleLoeschen(box, alleKnopf); });
            }
        }
        alleKnopfZeigen(box);
        try {
            var r = await fetch('/api/memory', { headers: kopf() });
            if (!r.ok) { box.textContent = T('common.error') + ' (' + r.status + ')'; return; }
            var d = await r.json();
            box.textContent = '';
            var liste = d.eintraege || [];
            if (!liste.length) { leerAnzeigen(box); return; }
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
            alleKnopfZeigen(box);
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
            if (box && !box.querySelector('.lk-mem')) leerAnzeigen(box);
        } catch (e) {
            btn.disabled = false;
            zeile.appendChild(el('div', 'lk-fehler', e.message));
        }
    }

    async function alleLoeschen(box, knopf) {
        var n = anzahl(box);
        if (!n) return;
        if (!window.confirm(T('wissen.mem_alle_frage', { n: n }))) return;
        knopf.disabled = true;
        // Eine alte Fehlerzeile vom letzten Versuch weg, sonst stehen zwei da
        var alt = knopf.parentNode && knopf.parentNode.querySelector('.lk-fehler');
        if (alt) alt.remove();
        try {
            var r = await fetch('/api/memory', {
                method: 'DELETE',
                headers: kopf({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ alle: true })
            });
            if (!r.ok) {
                var d = await r.json().catch(function () { return {}; });
                // Fehler am Knopf, der ihn ausgeloest hat – und er bleibt stehen
                knopf.parentNode.appendChild(el('div', 'lk-fehler', d.error || ('HTTP ' + r.status)));
                return;
            }
            leerAnzeigen(box);
        } catch (e) {
            knopf.parentNode.appendChild(el('div', 'lk-fehler', e.message));
        } finally {
            knopf.disabled = false;
        }
    }

    window.JarvisGedaechtnis = { laden: laden };
})();
