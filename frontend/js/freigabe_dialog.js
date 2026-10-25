/* Jarvis – wiederverwendbares Freigabe-Popup (Benutzer UND Gruppen).
 *
 * Fuer jede Stelle, an der ein EINZELNER Eintrag (ein MCP-Server, kuenftig
 * weitere) eine eigene Freigabe traegt – dieselbe Bauform wie die Bereiche unter
 * Einstellungen -> Sicherheit -> Berechtigungen: Benutzerliste (kommagetrennt)
 * ODER Gruppen-DNs (zeilengetrennt, DNs enthalten Kommas), ODER-verknuepft,
 * leer = niemand. Optional eine dritte Stufe "alle Netzwerk-Benutzer".
 *
 *   JarvisFreigabe.oeffnen({
 *       titel:     'Berechtigungen – theben',
 *       hinweis:   'Wer darf …',                     // optional
 *       mitAlle:   true,                              // Stufe "alle" anbieten
 *       alleBestaetigen: 'Wirklich alle …?',          // optional, Rueckfrage
 *       wert:      { alle: false, users: 'a, b', groups: 'CN=…\nCN=…' },
 *       speichern: async (wert) => { … }             // wirft bei Fehler
 *   });
 *   JarvisFreigabe.zusammenfassung(wert)  -> 'nur Administratoren' | …
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
        if (wert.alle === true) return 'alle';
        if (teile(wert.users, 'users').length || teile(wert.groups, 'groups').length) return 'auswahl';
        return 'keine';
    }

    function zusammenfassung(wert) {
        var a = art(wert);
        if (a === 'alle') return T('frg.sum_all', 'alle Netzwerk-Benutzer');
        if (a === 'keine') return T('frg.sum_none', 'nur Administratoren');
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
                '<div class="frg-stufen" role="radiogroup">' +
                  '<label class="frg-stufe"><input type="radio" name="frg-art" value="keine"> <span id="frg-l-keine"></span></label>' +
                  '<label class="frg-stufe" id="frg-stufe-alle"><input type="radio" name="frg-art" value="alle"> <span id="frg-l-alle"></span></label>' +
                  '<label class="frg-stufe"><input type="radio" name="frg-art" value="auswahl"> <span id="frg-l-auswahl"></span></label>' +
                '</div>' +
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
        m.querySelectorAll('input[name="frg-art"]').forEach(function (r) {
            r.addEventListener('change', function () { stufeZeigen(); });
        });
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

    function stufeZeigen() {
        var gew = document.querySelector('#frg-modal input[name="frg-art"]:checked');
        el('frg-auswahl').style.display = (gew && gew.value === 'auswahl') ? '' : 'none';
    }

    function oeffnen(opt) {
        aufbauen();
        _opt = opt || {};
        var wert = _opt.wert || {};
        el('frg-titel').textContent = _opt.titel || T('frg.title', 'Berechtigungen');
        el('frg-hinweis').textContent = _opt.hinweis || '';
        el('frg-hinweis').style.display = _opt.hinweis ? '' : 'none';
        el('frg-l-keine').textContent = T('frg.only_admins', 'Nur Administratoren');
        el('frg-l-alle').textContent = T('frg.all', 'Alle Netzwerk-Benutzer');
        el('frg-l-auswahl').textContent = T('frg.selected', 'Ausgewählte Benutzer und Gruppen');
        el('frg-l-users').textContent = T('frg.users', 'Benutzer');
        el('frg-l-groups').textContent = T('frg.groups', 'Gruppen');
        el('frg-oder').textContent = T('frg.or_hint', 'Benutzer und Gruppen gelten zusammen: wer in einer der beiden Listen steht, darf.');
        el('frg-abbrechen').textContent = T('common.cancel', 'Abbrechen');
        el('frg-speichern').textContent = T('frg.save', 'Übernehmen');
        el('frg-zu').setAttribute('aria-label', T('common.close', 'Schließen'));
        el('frg-stufe-alle').style.display = _opt.mitAlle ? '' : 'none';
        el('frg-fehler').textContent = '';

        var a = art(wert);
        if (a === 'alle' && !_opt.mitAlle) a = 'keine';
        document.querySelectorAll('#frg-modal input[name="frg-art"]').forEach(function (r) {
            r.checked = (r.value === a);
        });
        feldAnlegen('frg-users-wrap', 'users', wert.users);
        feldAnlegen('frg-groups-wrap', 'groups', wert.groups);
        stufeZeigen();
        el('frg-modal').classList.add('open');
    }

    function schliessen() {
        var m = el('frg-modal');
        if (m) m.classList.remove('open');
        _opt = null;
    }

    function lesen() {
        var gew = document.querySelector('#frg-modal input[name="frg-art"]:checked');
        var a = gew ? gew.value : 'keine';
        var u = document.querySelector('#frg-modal [data-frg="users"]');
        var g = document.querySelector('#frg-modal [data-frg="groups"]');
        if (a === 'auswahl') {
            return {
                alle: false,
                users: teile(u && u.value, 'users').join(JOIN.users),
                groups: teile(g && g.value, 'groups').join(JOIN.groups)
            };
        }
        // "Nur Administratoren" und "alle" leeren die Listen: eine liegen-
        // gebliebene Liste unter "alle" waere eine Freigabe, die niemand sieht.
        return { alle: a === 'alle', users: '', groups: '' };
    }

    async function speichern() {
        if (!_opt) return;
        var wert = lesen();
        var vorher = art(_opt.wert || {});
        if (wert.alle && vorher !== 'alle' && _opt.alleBestaetigen
                && !window.confirm(_opt.alleBestaetigen)) {
            return;
        }
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
