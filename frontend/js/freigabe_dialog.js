/* Jarvis – wiederverwendbares Freigabe-Popup (Benutzer UND Gruppen).
 *
 * Fuer jede Stelle, an der ein EINZELNER Eintrag (ein MCP-Server, kuenftig
 * weitere) eine eigene Freigabe traegt – dieselbe Regel wie die Bereiche unter
 * Einstellungen -> Sicherheit -> Berechtigungen: Benutzerliste (kommagetrennt)
 * ODER Gruppen-DNs (zeilengetrennt, DNs enthalten Kommas), ODER-verknuepft,
 * **leer = niemand, auch kein Administrator**. Bewusst KEINE Stufen wie
 * "alle" oder "nur Administratoren" (Festlegung des Betreibers 2026-10-25):
 * die gibt es bei keiner anderen Freigabe.
 *
 *   JarvisFreigabe.oeffnen({
 *       titel:     'Berechtigungen – theben',
 *       hinweis:   'Wer darf …',                     // optional
 *       wert:      { users: 'a, b', groups: 'CN=…\nCN=…' },
 *       speichern: async (wert) => { … }             // wirft bei Fehler
 *   });
 *   JarvisFreigabe.zusammenfassung(wert)  -> 'niemand' | '2 Benutzer · 1 Gruppe' 
 *
 * Die Verzeichnis-Suche kommt aus ldap_picker.js (attachField) – dieselben
 * Chip-Listen mit "Durchsuchen" wie in den Berechtigungen. Fehlt der Picker,
 * bleiben es einfache Eingabefelder.
 *
 * ⚠ EIN FEHLER BEIM SPEICHERN BLEIBT STEHEN (Register: man muss ihn lesen und
 * kopieren koennen) – das Fenster schliesst nur nach Erfolg.
 */
(function () {
    'use strict';

    var SEP = { users: ',', groups: '\n' };
    var JOIN = { users: ', ', groups: '\n' };

    // Rueckfalltext, falls ein Browser ein aelteres i18n.js im Cache haelt –
    // sonst stuende der nackte Schluessel auf dem Knopf.
    function T(k, f) {
        var v = window.t ? window.t(k) : k;
        return (v && v !== k) ? v : f;
    }
    function el(id) { return document.getElementById(id); }
    function teile(val, kind) {
        return String(val || '').split(SEP[kind])
            .map(function (s) { return s.trim(); }).filter(Boolean);
    }

    var _opt = null;

    function art(wert) {
        if (!wert) return 'keine';
        if (teile(wert.users, 'users').length || teile(wert.groups, 'groups').length) return 'auswahl';
        return 'keine';
    }

    function zusammenfassung(wert) {
        if (art(wert) === 'keine') return T('frg.sum_none', 'niemand');
        var nu = teile(wert.users, 'users').length;
        var ng = teile(wert.groups, 'groups').length;
        var teileTxt = [];
        if (nu) teileTxt.push(nu + ' ' + (nu === 1 ? T('frg.sum_user', 'Benutzer') : T('frg.sum_users', 'Benutzer')));
        if (ng) teileTxt.push(ng + ' ' + (ng === 1 ? T('frg.sum_group', 'Gruppe') : T('frg.sum_groups', 'Gruppen')));
        return teileTxt.join(' · ');
    }

    function aufbauen() {
        if (el('frg-modal')) return;
        var m = document.createElement('div');
        m.id = 'frg-modal';
        m.className = 'modal';
        // Unter dem Verzeichnis-Picker (10002), der daraus geoeffnet wird.
        m.style.zIndex = '10001';
        m.innerHTML =
            '<div class="modal-content glass frg-box" role="dialog" aria-modal="true" aria-labelledby="frg-titel">' +
              '<div class="modal-header">' +
                '<h2 id="frg-titel"></h2>' +
                '<button type="button" class="btn-icon" id="frg-zu"></button>' +
              '</div>' +
              '<div class="modal-body frg-body">' +
                '<p class="frg-hinweis" id="frg-hinweis"></p>' +
                '<div class="frg-auswahl" id="frg-auswahl">' +
                  '<div class="frg-feld"><div class="frg-feld-titel" id="frg-l-users"></div>' +
                    '<div class="frg-feld-inhalt" id="frg-users-wrap"></div></div>' +
                  '<div class="frg-feld"><div class="frg-feld-titel" id="frg-l-groups"></div>' +
                    '<div class="frg-feld-inhalt" id="frg-groups-wrap"></div></div>' +
                  '<div class="frg-hinweis" id="frg-oder"></div>' +
                '</div>' +
                '<div class="frg-fehler" id="frg-fehler" role="alert"></div>' +
                '<div class="frg-knoepfe">' +
                  '<button type="button" class="mcp-btn-sm" id="frg-abbrechen"></button>' +
                  '<button type="button" class="mcp-btn-primary" id="frg-speichern"></button>' +
                '</div>' +
              '</div>' +
            '</div>';
        document.body.appendChild(m);

        var zu = el('frg-zu');
        if (window.JarvisIcons) zu.innerHTML = window.JarvisIcons.close();
        else zu.textContent = '×';
        zu.addEventListener('click', schliessen);
        el('frg-abbrechen').addEventListener('click', schliessen);
        el('frg-speichern').addEventListener('click', speichern);
        m.addEventListener('click', function (e) { if (e.target === m) schliessen(); });
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape' || !offen()) return;
            // Der Verzeichnis-Picker liegt darueber und schliesst sich selbst.
            var p = el('ldap-picker-modal');
            if (p && p.classList.contains('open')) return;
            schliessen();
        });
    }

    function offen() {
        var m = el('frg-modal');
        return !!(m && m.classList.contains('open'));
    }

    // Felder bei jedem Oeffnen NEU anlegen: attachField merkt sich ein
    // versorgtes Feld (data-ldap-attached) und wuerde sonst den Stand des
    // vorigen Eintrags weiterzeigen.
    function feldAnlegen(wrapId, kind, wert) {
        var wrap = el(wrapId);
        wrap.innerHTML = '';
        var inp;
        if (window.LdapPicker && window.LdapPicker.attachField) {
            inp = document.createElement('input');
            inp.type = 'text';
            inp.value = teile(wert, kind).join(JOIN[kind]);
            wrap.appendChild(inp);
            window.LdapPicker.attachField(inp, { kind: kind });
        } else {
            inp = document.createElement('textarea');
            inp.rows = 3;
            inp.className = 'mcp-input';
            inp.value = teile(wert, kind).join(JOIN[kind]);
            wrap.appendChild(inp);
        }
        inp.setAttribute('data-frg', kind);
        return inp;
    }

    function oeffnen(opt) {
        aufbauen();
        _opt = opt || {};
        var wert = _opt.wert || {};
        el('frg-titel').textContent = _opt.titel || T('frg.title', 'Berechtigungen');
        el('frg-hinweis').textContent = _opt.hinweis || '';
        el('frg-hinweis').style.display = _opt.hinweis ? '' : 'none';
        el('frg-l-users').textContent = T('frg.users', 'Benutzer');
        el('frg-l-groups').textContent = T('frg.groups', 'Gruppen');
        el('frg-oder').textContent = T('frg.or_hint', 'Wer in einer der beiden Listen steht, darf. Sind beide leer, darf niemand – auch kein Administrator.');
        el('frg-abbrechen').textContent = T('common.cancel', 'Abbrechen');
        el('frg-speichern').textContent = T('frg.save', 'Übernehmen');
        el('frg-zu').setAttribute('aria-label', T('common.close', 'Schließen'));
        el('frg-fehler').textContent = '';
        feldAnlegen('frg-users-wrap', 'users', wert.users);
        feldAnlegen('frg-groups-wrap', 'groups', wert.groups);
        el('frg-modal').classList.add('open');
    }

    function schliessen() {
        var m = el('frg-modal');
        if (m) m.classList.remove('open');
        _opt = null;
    }

    function lesen() {
        var u = document.querySelector('#frg-modal [data-frg="users"]');
        var g = document.querySelector('#frg-modal [data-frg="groups"]');
        return {
            users: teile(u && u.value, 'users').join(JOIN.users),
            groups: teile(g && g.value, 'groups').join(JOIN.groups)
        };
    }

    async function speichern() {
        if (!_opt) return;
        var wert = lesen();
        var knopf = el('frg-speichern');
        knopf.disabled = true;
        el('frg-fehler').textContent = '';
        try {
            if (_opt.speichern) await _opt.speichern(wert);
            schliessen();
        } catch (e) {
            el('frg-fehler').textContent = T('frg.save_error', 'Speichern fehlgeschlagen:') +
                ' ' + ((e && e.message) || e);
        } finally {
            knopf.disabled = false;
        }
    }

    window.JarvisFreigabe = { oeffnen: oeffnen, zusammenfassung: zusammenfassung, art: art };
})();
