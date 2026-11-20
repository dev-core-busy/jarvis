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
 * 2026-11-20: Suchfeld. Filtert die geladene Liste im Browser nach Schluessel
 * und Wert (Gross-/Kleinschreibung egal, mehrere Woerter muessen ALLE
 * vorkommen). Kein Serverabruf: /api/memory liefert ohnehin alle Eintraege.
 * Das Feld steht nur da, solange es Eintraege gibt (wie "Alles löschen").
 * "Alles löschen" loescht weiterhin ALLE Eintraege – bei aktiver Suche sagt
 * die Rueckfrage das ausdruecklich, damit niemand "nur die Treffer" erwartet.
 *
 * Aufruf: JarvisGedaechtnis.laden(box, alleKnopf, suche) – box ist der Listen-
 * Container, alleKnopf (optional) der Knopf "Alles löschen", suche (optional)
 * ein Objekt { feld, zahl, leiste }: Eingabefeld, Trefferzaehler und die
 * Zeile, die beides traegt (wird mit der Liste ein-/ausgeblendet).
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

    // Knopf "Alles löschen" und Suchzeile: sichtbar genau dann, wenn die
    // Liste Eintraege hat.
    var _alleKnopf = null;
    var _suche = null;
    function anzahl(box) { return box ? box.querySelectorAll('.lk-mem').length : 0; }
    function alleKnopfZeigen(box) {
        var leer = anzahl(box) === 0;
        if (_alleKnopf) _alleKnopf.hidden = leer;
        if (_suche && _suche.leiste) _suche.leiste.hidden = leer;
        filtern(box);
    }
    function leerAnzeigen(box) {
        box.textContent = '';
        box.appendChild(el('div', 'lk-leer', T('lk.gedaechtnis_leer')));
        alleKnopfZeigen(box);
    }

    // Suchbegriff in Woerter zerlegt, klein geschrieben; leer = kein Filter.
    function suchWoerter() {
        var q = (_suche && _suche.feld && _suche.feld.value) || '';
        return q.toLocaleLowerCase('de').split(/\s+/).filter(Boolean);
    }
    function sucheAktiv() { return suchWoerter().length > 0; }

    // Blendet Zeilen aus, die nicht ALLE Suchwoerter in Schluessel oder Wert
    // tragen. Ausgeblendet per style.display: `.lk-mem` setzt `display:flex`
    // und schluege damit das hidden-Attribut (Register).
    function filtern(box) {
        if (!box) return;
        var woerter = suchWoerter();
        var zeilen = box.querySelectorAll('.lk-mem');
        var sichtbar = 0;
        Array.prototype.forEach.call(zeilen, function (z) {
            var text = z._suchtext || '';
            var passt = woerter.every(function (w) { return text.indexOf(w) !== -1; });
            z.style.display = passt ? '' : 'none';
            if (passt) sichtbar++;
        });
        var alt = box.querySelector('.lk-keine-treffer');
        if (alt) alt.remove();
        if (woerter.length && zeilen.length && !sichtbar) {
            box.appendChild(el('div', 'lk-leer lk-keine-treffer', T('wissen.mem_keine_treffer')));
        }
        if (_suche && _suche.zahl) {
            _suche.zahl.textContent = (woerter.length && zeilen.length)
                ? T('wissen.mem_treffer', { k: sichtbar, n: zeilen.length }) : '';
        }
    }

    function sucheBinden(box, suche) {
        _suche = suche;
        var feld = suche.feld;
        if (!feld || feld._gebunden) return;
        feld._gebunden = true;
        feld.addEventListener('input', function () { filtern(box); });
        // Escape leert das Feld (und zeigt wieder alles)
        feld.addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape' && feld.value) { feld.value = ''; filtern(box); }
        });
    }

    async function laden(box, alleKnopf, suche) {
        if (!box) return;
        if (alleKnopf) {
            _alleKnopf = alleKnopf;
            if (!alleKnopf._gebunden) {
                alleKnopf._gebunden = true;
                alleKnopf.addEventListener('click', function () { alleLoeschen(box, alleKnopf); });
            }
        }
        if (suche) sucheBinden(box, suche);
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
                // Wonach die Suche schaut: Schluessel und Wert, klein geschrieben
                z._suchtext = (String(e.key || '') + ' ' + String(e.value || '')).toLocaleLowerCase('de');
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
            // Letzter Eintrag weg: dieselbe Leer-Anzeige wie beim Laden;
            // sonst Trefferzahl/"keine Treffer" der laufenden Suche nachziehen
            if (box && !box.querySelector('.lk-mem')) leerAnzeigen(box);
            else filtern(box);
        } catch (e) {
            btn.disabled = false;
            zeile.appendChild(el('div', 'lk-fehler', e.message));
        }
    }

    async function alleLoeschen(box, knopf) {
        var n = anzahl(box);
        if (!n) return;
        // Bei aktiver Suche ausdruecklich: geloescht wird ALLES, nicht nur die Treffer
        var frage = sucheAktiv() ? 'wissen.mem_alle_frage_suche' : 'wissen.mem_alle_frage';
        if (!window.confirm(T(frage, { n: n }))) return;
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
            // Die Suche hat danach nichts mehr zu filtern
            if (_suche && _suche.feld) _suche.feld.value = '';
            leerAnzeigen(box);
        } catch (e) {
            knopf.parentNode.appendChild(el('div', 'lk-fehler', e.message));
        } finally {
            knopf.disabled = false;
        }
    }

    window.JarvisGedaechtnis = { laden: laden };
})();
