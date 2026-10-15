/* Jarvis – Berechtigungen kompakt zuweisen (Sicherheit -> Berechtigungen).
 *
 * Ein Fenster statt zwoelf Unter-Container: Benutzer und Gruppen werden ueber
 * die vorhandene Verzeichnis-Suche (LdapPicker) gewaehlt, je Bereich gibt es
 * ein Kaestchen. Zeilen sind alle Benutzer/Gruppen, die in einem der SICHTBAREN
 * Bereiche schon stehen, plus die neu gewaehlten.
 *
 * Quelle der Wahrheit bleiben die Felder der Unter-Container (ad-allowed-users
 * usw.): "Uebernehmen" schreibt dort hinein und speichert ueber window._adSave –
 * derselbe Weg wie der Speichern-Knopf darunter, also kein zweites Format.
 *
 * Bereiche, deren Unter-Container ausgeblendet ist (Skill aus), erscheinen
 * nicht als Spalte und werden nicht angefasst.
 */
(function () {
    'use strict';

    // sub = data-sub des Unter-Containers; users/group = IDs der Felder
    var BEREICHE = [
        { sub: 'login',      users: 'ad-allowed-users',         group: 'ad-allowed-group',           key: 'rmx.col_login' },
        { sub: 'knowledge',  users: 'ad-knowledge-editors',     group: 'ad-knowledge-editors-group', key: 'rmx.col_knowledge' },
        { sub: 'sap',        users: 'sap-allowed-users',        group: 'sap-allowed-group',          key: 'rmx.col_sap' },
        { sub: 'vemas',      users: 'vemas-allowed-users',      group: 'vemas-allowed-group',        key: 'rmx.col_vemas' },
        { sub: 'email',      users: 'email-allowed-users',      group: 'email-allowed-group',        key: 'rmx.col_email' },
        { sub: 'tracks',     users: 'tracks-allowed-users',     group: 'tracks-allowed-group',       key: 'rmx.col_tracks' },
        { sub: 'jiraassist', users: 'jiraassist-allowed-users', group: 'jiraassist-allowed-group',   key: 'rmx.col_jiraassist' },
        { sub: 'aimouse',    users: 'aimouse-allowed-users',    group: 'aimouse-allowed-group',      key: 'rmx.col_aimouse' },
        { sub: 'claudesub',  users: 'claudesub-allowed-users',  group: 'claudesub-allowed-group',    key: 'rmx.col_claudesub' },
        { sub: 'excel',      users: 'excel-allowed-users',      group: 'excel-allowed-group',        key: 'rmx.col_excel' },
        { sub: 'internet',   users: 'ad-internet-users',        group: 'ad-internet-group',          key: 'rmx.col_internet' },
        { sub: 'admins',     users: 'ad-admins',                group: 'ad-admins-group',            key: 'rmx.col_admins' }
    ];
    // Trenner wie in ldap_picker.js: Benutzer kommagetrennt, Gruppen-DNs
    // zeilengetrennt (DNs enthalten selbst Kommas)
    var SEP = { users: ',', groups: '\n' };
    var JOIN = { users: ', ', groups: '\n' };

    var _spalten = [];   // sichtbare Bereiche beim Oeffnen
    // { kind, wert, an: [bool je Spalte], vorher: [bool je Spalte], neu,
    //   nurGruppe (Zeile entstand nur aus einer Gruppen-Mitgliedschaft), anzeige }
    var _zeilen = [];
    // Direkte Mitglieder je Gruppe, Schluessel = schluessel('groups', dn):
    // { stand: 'laedt'|'ok'|'kein_zugang'|'fehler', mitglieder: {login: anzeige}, grund }
    var _mitglieder = {};
    var _zeigeMitglieder = false;
    // Sortierung: nach 'name' oder nach dem data-sub eines Bereichs (nicht nach
    // dem Spaltenindex – welche Spalten es gibt, haengt an den Skill-Schaltern).
    // Gemerkt je Browser; fehlt die gemerkte Spalte, gilt der Name.
    var SORT_KEY = 'jarvis_rmx_sort';
    var _sort = { nach: 'name', richtung: 1 };

    function el(id) { return document.getElementById(id); }
    function T(k) { return window.t(k); }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function teile(val, kind) {
        return (val || '').split(SEP[kind]).map(function (s) { return s.trim(); }).filter(Boolean);
    }
    // CN aus dem DN; ein Komma im Namen steht im DN maskiert ("CN=IT\\, Team,...")
    function kurzDn(dn) {
        var m = /^CN=((?:\\.|[^,\\])+)/i.exec(dn || '');
        return m ? m[1].replace(/\\(.)/g, '$1') : dn;
    }
    function feldId(b, kind) { return kind === 'users' ? b.users : b.group; }

    // Sichtbar = Unter-Container existiert und ist nicht per Skill-Schalter
    // ausgeblendet. Zugeklappt zaehlt als sichtbar (Register: "Zugeklappt ist
    // nicht versteckt").
    function sichtbareBereiche() {
        return BEREICHE.filter(function (b) {
            var d = document.querySelector('details.sec-sub[data-sub="' + b.sub + '"]');
            return !!(d && d.style.display !== 'none' && el(b.users) && el(b.group));
        });
    }

    // Identitaet eines Eintrags. Benutzer wie im Backend (_norm_login): ohne
    // Domain-Praefix (FIRMA\name) und UPN-Suffix (name@firma), klein – sonst
    // waeren "firma\bob" und "bob" zwei Zeilen, fuer die Anmeldung aber einer.
    function schluessel(kind, w) {
        var s = String(w || '').trim();
        if (kind === 'users') s = s.split('@')[0].split('\\').pop().trim();
        return s.toLowerCase();
    }

    function enthaelt(liste, wert, kind) {
        var w = schluessel(kind, wert);
        return liste.some(function (x) { return schluessel(kind, x) === w; });
    }

    function zeileFinden(kind, wert) {
        var w = schluessel(kind, wert);
        for (var i = 0; i < _zeilen.length; i++) {
            if (_zeilen[i].kind === kind && schluessel(kind, _zeilen[i].wert) === w) return _zeilen[i];
        }
        return null;
    }

    function zeileAnlegen(kind, wert) {
        var z = zeileFinden(kind, wert);
        if (z) return z;
        z = { kind: kind, wert: wert, an: [], vorher: [], neu: true, nurGruppe: false, anzeige: '' };
        _spalten.forEach(function (b) {
            var drin = enthaelt(teile(el(feldId(b, kind)).value, kind), wert, kind);
            z.an.push(drin);
            z.vorher.push(drin);
            if (drin) z.neu = false;
        });
        _zeilen.push(z);
        return z;
    }

    function bestandEinlesen() {
        _spalten = sichtbareBereiche();
        _zeilen = [];
        ['users', 'groups'].forEach(function (kind) {
            _spalten.forEach(function (b) {
                teile(el(feldId(b, kind)).value, kind).forEach(function (w) { zeileAnlegen(kind, w); });
            });
        });
        sortieren();
    }

    function sortLaden() {
        try {
            var g = JSON.parse(localStorage.getItem(SORT_KEY) || 'null');
            if (g && typeof g.nach === 'string' && (g.richtung === 1 || g.richtung === -1)) _sort = g;
        } catch (e) {}
    }
    function sortMerken() {
        try { localStorage.setItem(SORT_KEY, JSON.stringify(_sort)); } catch (e) {}
    }
    function sortSpalte() {
        for (var i = 0; i < _spalten.length; i++) if (_spalten[i].sub === _sort.nach) return i;
        return -1;
    }
    function anzeigeName(z) { return z.kind === 'groups' ? kurzDn(z.wert) : z.wert; }

    // Gruppen bleiben immer vor den Benutzern (sie wirken auf viele). Darin nach
    // Name oder nach Bereich: direkt eingetragen, dann ueber Gruppe, dann keine –
    // bei Gleichstand alphabetisch. Sortiert wird beim Oeffnen und auf Klick,
    // NICHT bei jedem Haken (sonst springt die Zeile unter dem Mauszeiger weg).
    function sortieren() {
        var si = sortSpalte();
        var nachName = si < 0;
        var richtung = (nachName && _sort.nach !== 'name') ? 1 : _sort.richtung;
        // Rang VOR dem Sortieren festhalten: erbe() liest _zeilen, und das
        // Array darf waehrend sort() nicht gelesen werden
        var rang = new Map();
        if (!nachName) _zeilen.forEach(function (z) { rang.set(z, z.an[si] ? 0 : (erbe(z, si).length ? 1 : 2)); });
        _zeilen.sort(function (a, b) {
            if (a.kind !== b.kind) return a.kind === 'groups' ? -1 : 1;
            var r = nachName ? 0 : (rang.get(a) - rang.get(b)) * richtung;
            if (r) return r;
            return anzeigeName(a).localeCompare(anzeigeName(b), undefined, { sensitivity: 'base' }) * (nachName ? richtung : 1);
        });
    }

    // ── Geerbte Berechtigungen (ueber eine Gruppe) ────────────────────────
    // Grundlage sind die DIREKTEN Mitglieder (memberOf) – dieselbe, die auch
    // die Anmeldung und jede andere Bereichs-Freigabe prueft. Verschachtelte
    // Gruppen und die Primaergruppe zaehlen dort nicht, also hier auch nicht.

    // Namen der Gruppen, ueber die Zeile z den Bereich si erhaelt – nach dem
    // AKTUELLEN Stand im Fenster, damit ein Haken an einer Gruppe sofort wirkt.
    function erbe(z, si) {
        if (z.kind !== 'users') return [];
        var w = schluessel('users', z.wert);
        var out = [];
        _zeilen.forEach(function (g) {
            if (g.kind !== 'groups' || !g.an[si]) return;
            var m = _mitglieder[schluessel('groups', g.wert)];
            if (m && m.stand === 'ok' && Object.prototype.hasOwnProperty.call(m.mitglieder, w)) out.push(kurzDn(g.wert));
        });
        return out;
    }

    function mitgliederZeilen() {
        Object.keys(_mitglieder).forEach(function (k) {
            var m = _mitglieder[k];
            if (m.stand !== 'ok') return;
            Object.keys(m.mitglieder).forEach(function (login) {
                if (zeileFinden('users', login)) return;
                var z = zeileAnlegen('users', login);
                z.neu = false;
                z.nurGruppe = true;
                z.anzeige = m.mitglieder[login];
            });
        });
    }

    function mitgliederLaden() {
        var zugang = (window.LdapPicker && window.LdapPicker.zugang) ? window.LdapPicker.zugang() : {};
        var offen = _zeilen.filter(function (g) {
            if (g.kind !== 'groups') return false;
            var m = _mitglieder[schluessel('groups', g.wert)];
            // ohne Zugang gescheiterte Abfragen erneut versuchen, sobald
            // im Verzeichnis-Picker ein Kennwort eingegeben wurde
            return !m || (m.stand === 'kein_zugang' && zugang.password);
        });
        if (!offen.length) { erbeInfo(); return Promise.resolve(); }
        offen.forEach(function (g) { _mitglieder[schluessel('groups', g.wert)] = { stand: 'laedt', mitglieder: {} }; });
        erbeInfo();
        return Promise.all(offen.map(function (g) {
            var key = schluessel('groups', g.wert);
            var body = { group: g.wert };
            if (zugang.password) { body.password = zugang.password; body.bind_user = zugang.bind_user; }
            return fetch('/api/ldap/group_members', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + window.JarvisSitzung.token() },
                body: JSON.stringify(body)
            }).then(function (r) {
                return r.json().then(function (j) { return { status: r.status, j: j }; }, function () { return { status: r.status, j: {} }; });
            }).then(function (res) {
                if (res.status === 428 || res.status === 401) {
                    _mitglieder[key] = { stand: 'kein_zugang', mitglieder: {} };
                } else if (res.status !== 200) {
                    _mitglieder[key] = { stand: 'fehler', mitglieder: {}, grund: (res.j && res.j.error) || ('HTTP ' + res.status) };
                } else {
                    var mg = {};
                    ((res.j && res.j.members) || []).forEach(function (m) {
                        if (m.kind === 'group' || !m.sam) return;   // verschachtelt: zaehlt beim Login nicht
                        mg[schluessel('users', m.sam)] = m.display || m.sam;
                    });
                    _mitglieder[key] = { stand: 'ok', mitglieder: mg };
                }
            }).catch(function () {
                _mitglieder[key] = { stand: 'fehler', mitglieder: {}, grund: T('ldap.network_error') };
            });
        })).then(function () {
            mitgliederZeilen();
            sortieren();
            zeichnen();
        });
    }

    // Zeile unter der Tabelle: Legende plus Zustand der Abfrage. Ein Zustand,
    // der nicht ermittelt werden konnte, wird GENANNT – sonst sieht "kein
    // Strich" wie "nicht ueber eine Gruppe berechtigt" aus.
    function erbeInfo() {
        var box = el('rmx-erbe-info');
        if (!box) return;
        var st = { laedt: 0, kein_zugang: [], fehler: [] };
        _zeilen.forEach(function (g) {
            if (g.kind !== 'groups') return;
            var m = _mitglieder[schluessel('groups', g.wert)];
            if (!m) return;
            if (m.stand === 'laedt') st.laedt++;
            else if (m.stand === 'kein_zugang') st.kein_zugang.push(kurzDn(g.wert));
            else if (m.stand === 'fehler') st.fehler.push(kurzDn(g.wert) + ' (' + m.grund + ')');
        });
        var teileTxt = [T('rmx.inherit_legend')];
        if (st.laedt) teileTxt.push(T('rmx.inherit_loading'));
        if (st.kein_zugang.length) teileTxt.push(T('rmx.inherit_no_cred').replace('{liste}', st.kein_zugang.join(', ')));
        if (st.fehler.length) teileTxt.push(T('rmx.inherit_failed').replace('{liste}', st.fehler.join(', ')));
        box.textContent = teileTxt.join(' ');
        box.classList.toggle('rmx-erbe-warn', !!(st.kein_zugang.length || st.fehler.length));
        var n = _zeilen.filter(function (z) { return z.nurGruppe; }).length;
        var lbl = el('rmx-mitglieder-lbl');
        if (lbl) lbl.textContent = T('rmx.show_members').replace('{n}', n);
    }

    // Kaestchen-Zustaende IN PLACE nachziehen (kein Neuaufbau: Fokus und
    // Rollposition bleiben). Haken = direkt eingetragen; grauer, gesperrter
    // Haken = nur ueber eine Gruppe berechtigt (Vorgabe Betreiber 2026-10-14,
    // vorher ein Strich). Der Haken zeigt die WIRKUNG – berechtigt ist die
    // Zeile ja –, z.an bleibt dabei unberuehrt: geschrieben wird nur Direktes.
    function zustaende() {
        document.querySelectorAll('#rmx-tabwrap .rmx-cb').forEach(function (cb) {
            var z = _zeilen[+cb.getAttribute('data-z')];
            var si = +cb.getAttribute('data-s');
            if (!z) return;
            var gr = erbe(z, si);
            // Wo eine Gruppe den Bereich schon gibt, wird NICHT zusaetzlich direkt
            // eingetragen (Vorgabe Betreiber 2026-10-14). Eine NEU gesetzte Freigabe,
            // die durch einen Gruppen-Haken ueberfluessig wird, faellt deshalb
            // zurueck. Ein BESTEHENDER Doppel-Eintrag bleibt abwaehlbar – sonst
            // liesse er sich nie mehr entfernen.
            if (gr.length && z.an[si] && !z.vorher[si]) z.an[si] = false;
            var td = cb.closest('td');
            var nurGeerbt = gr.length > 0 && !z.an[si];
            cb.disabled = nurGeerbt;
            cb.checked = !!z.an[si] || nurGeerbt;
            cb.indeterminate = false;
            var titel = '';
            if (gr.length && z.an[si]) titel = T('rmx.inherit_both').replace('{liste}', gr.join(', '));
            else if (gr.length) titel = T('rmx.inherit_only').replace('{liste}', gr.join(', '));
            if (td) {
                td.title = titel;
                td.classList.toggle('rmx-geerbt', nurGeerbt);
                td.classList.toggle('rmx-geaendert', z.an[si] !== z.vorher[si]);
            }
        });
    }

    function aenderungen() {
        var n = 0;
        _zeilen.forEach(function (z) {
            z.an.forEach(function (v, i) { if (v !== z.vorher[i]) n++; });
        });
        return n;
    }

    // ── Fenster ───────────────────────────────────────────────────────────
    function fensterAnlegen() {
        if (el('rmx-modal')) return;
        var m = document.createElement('div');
        m.id = 'rmx-modal';
        m.className = 'modal';
        // unter dem Verzeichnis-Picker (10002), der daraus geoeffnet wird
        m.style.zIndex = '10001';
        m.innerHTML =
            '<div class="modal-content glass rmx-inhalt">' +
              '<div class="modal-header">' +
                '<h2 data-i18n="rmx.title">' + esc(T('rmx.title')) + '</h2>' +
                '<button type="button" class="btn-icon" id="rmx-close" data-i18n-aria="common.close" aria-label="' + esc(T('common.close')) + '"></button>' +
              '</div>' +
              '<div class="modal-body rmx-body">' +
                '<p class="kb-hint" data-i18n="rmx.intro">' + esc(T('rmx.intro')) + '</p>' +
                '<div class="rmx-leiste">' +
                  '<button type="button" class="kb-btn-secondary" id="rmx-add-users" data-i18n="rmx.add_users">' + esc(T('rmx.add_users')) + '</button>' +
                  '<button type="button" class="kb-btn-secondary" id="rmx-add-groups" data-i18n="rmx.add_groups">' + esc(T('rmx.add_groups')) + '</button>' +
                  '<input type="text" id="rmx-filter" class="input-field rmx-filter" autocomplete="off" data-i18n-placeholder="rmx.filter_ph" placeholder="' + esc(T('rmx.filter_ph')) + '">' +
                  '<label class="rmx-schalter"><input type="checkbox" id="rmx-mitglieder"><span id="rmx-mitglieder-lbl"></span></label>' +
                '</div>' +
                // Ziel-Felder fuer den Verzeichnis-Picker (nie sichtbar)
                '<input type="hidden" id="rmx-pick-users">' +
                '<input type="hidden" id="rmx-pick-groups">' +
                '<div class="rmx-tabwrap" id="rmx-tabwrap"></div>' +
                '<div class="rmx-erbe-info" id="rmx-erbe-info" role="status"></div>' +
                '<div class="rmx-fuss">' +
                  '<span id="rmx-status" class="rmx-status" role="status"></span>' +
                  '<button type="button" class="kb-btn-secondary" id="rmx-cancel" data-i18n="common.cancel">' + esc(T('common.cancel')) + '</button>' +
                  '<button type="button" class="kb-btn-action" id="rmx-apply"></button>' +
                '</div>' +
              '</div>' +
            '</div>';
        document.body.appendChild(m);
        if (window.JarvisIcons) window.JarvisIcons.setClose(el('rmx-close'));

        el('rmx-close').addEventListener('click', schliessen);
        el('rmx-cancel').addEventListener('click', schliessen);
        m.addEventListener('click', function (e) { if (e.target === m) schliessen(); });
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape' || !m.classList.contains('open')) return;
            // Liegt der Verzeichnis-Picker darueber, schliesst Escape zuerst ihn
            var p = el('ldap-picker-modal');
            if (p && p.classList.contains('open')) return;
            schliessen();
        });
        el('rmx-filter').addEventListener('input', zeichnen);
        el('rmx-mitglieder').addEventListener('change', function () {
            _zeigeMitglieder = el('rmx-mitglieder').checked;
            zeichnen();
        });
        el('rmx-apply').addEventListener('click', uebernehmen);

        ['users', 'groups'].forEach(function (kind) {
            var ziel = el('rmx-pick-' + kind);
            el('rmx-add-' + kind).addEventListener('click', function () {
                if (!window.LdapPicker) return;
                ziel.value = '';
                window.LdapPicker.open({ kind: kind, multi: true, sep: SEP[kind] }, ziel);
            });
            // LdapPicker meldet die Auswahl per 'change' am Zielfeld
            ziel.addEventListener('change', function () {
                var neu = teile(ziel.value, kind);
                ziel.value = '';
                if (!neu.length) return;
                neu.forEach(function (w) {
                    var z = zeileAnlegen(kind, w);
                    // aus einer Gruppe stammende Zeile ist jetzt ausdruecklich gewaehlt
                    if (z.nurGruppe) { z.nurGruppe = false; z.neu = true; }
                    z.entfernt = false;   // erneut gewaehlt: wieder in der Liste
                });
                sortieren();
                el('rmx-filter').value = '';
                zeichnen();
                mitgliederLaden();
            });
        });

        // Delegiert: Kaestchen, Zeile leeren, Spalte setzen
        el('rmx-tabwrap').addEventListener('change', function (e) {
            var cb = e.target;
            if (!cb.classList || !cb.classList.contains('rmx-cb')) return;
            var z = _zeilen[+cb.getAttribute('data-z')];
            if (!z) return;
            z.an[+cb.getAttribute('data-s')] = cb.checked;
            // ein Haken an einer GRUPPE aendert die geerbten Striche aller Mitglieder
            zustaende();
            fussAktualisieren();
        });
        el('rmx-tabwrap').addEventListener('click', function (e) {
            var k = e.target.closest ? e.target.closest('.rmx-sort') : null;
            if (k) {
                var nach = k.getAttribute('data-sort');
                var aktiv = sortSpalte() >= 0 ? _sort.nach : 'name';
                _sort = { nach: nach, richtung: aktiv === nach ? -_sort.richtung : 1 };
                sortMerken();
                sortieren();
                zeichnen();
                return;
            }
            var b = e.target.closest ? e.target.closest('.rmx-row-clear') : null;
            if (!b) return;
            var z = _zeilen[+b.getAttribute('data-z')];
            if (!z) return;
            // Loeschen = aus der LISTE nehmen; "Uebernehmen" entfernt den Eintrag
            // dann aus allen Bereichen. Vorher blieb die Zeile mit leeren
            // Kaestchen stehen – fuer den Benutzer sah der Klick wirkungslos aus.
            z.an = z.an.map(function () { return false; });
            z.entfernt = true;
            zeichnen();
        });
    }

    function zeichnen() {
        var wrap = el('rmx-tabwrap');
        if (!_spalten.length) {
            wrap.innerHTML = '<div class="rmx-leer">' + esc(T('rmx.no_areas')) + '</div>';
            fussAktualisieren();
            return;
        }
        var f = (el('rmx-filter').value || '').trim().toLowerCase();
        var aktiv = sortSpalte() >= 0 ? _sort.nach : 'name';
        var kopfZelle = function (nach, text, titel, klasse) {
            var an = aktiv === nach;
            var r = an ? (nach === 'name' && _sort.nach !== 'name' ? 1 : _sort.richtung) : 0;
            return '<th' + (klasse ? ' class="' + klasse + '"' : '') +
                ' aria-sort="' + (r === 1 ? 'ascending' : r === -1 ? 'descending' : 'none') + '">' +
                '<button type="button" class="rmx-sort' + (an ? ' rmx-sort-an' : '') + '" data-sort="' + esc(nach) +
                '" title="' + esc(titel) + '">' + esc(text) +
                '<span class="rmx-pfeil" aria-hidden="true">' + (r === 1 ? '\u25B2' : r === -1 ? '\u25BC' : '') + '</span></button></th>';
        };
        var kopf = '<thead><tr>' + kopfZelle('name', T('rmx.col_principal'), T('rmx.sort_hint_name'), 'rmx-name-th');
        _spalten.forEach(function (b) {
            var d = document.querySelector('details.sec-sub[data-sub="' + b.sub + '"] summary span');
            var titel = (d ? d.textContent : T(b.key)) + ' – ' + T('rmx.sort_hint_area');
            kopf += kopfZelle(b.sub, T(b.key), titel, '');
        });
        kopf += '<th></th></tr></thead>';

        var koerper = '';
        var sichtbar = 0;
        _zeilen.forEach(function (z, zi) {
            var name = z.kind === 'groups' ? kurzDn(z.wert) : z.wert;
            if (z.entfernt) return;
            var geaendert = z.an.some(function (v, i) { return v !== z.vorher[i]; });
            // Zeilen nur aus Gruppen-Mitgliedschaft: auf Wunsch; geaenderte bleiben stehen
            if (z.nurGruppe && !_zeigeMitglieder && !geaendert) return;
            var anz = (z.anzeige || '').toLowerCase();
            if (f && name.toLowerCase().indexOf(f) < 0 && z.wert.toLowerCase().indexOf(f) < 0 && anz.indexOf(f) < 0) return;
            sichtbar++;
            var art = z.kind === 'groups' ? T('rmx.kind_group') : T('rmx.kind_user');
            koerper += '<tr><th scope="row" class="rmx-name" title="' + esc(z.wert) + '">' +
                '<span class="rmx-art rmx-art-' + z.kind + '">' + esc(art) + '</span>' +
                '<span class="rmx-wert">' + esc(name) + '</span>' +
                (z.anzeige && z.anzeige.toLowerCase() !== name.toLowerCase() ? '<span class="rmx-neu">' + esc(z.anzeige) + '</span>' : '') +
                (z.neu ? '<span class="rmx-neu">' + esc(T('rmx.new')) + '</span>' : '') +
                (z.nurGruppe ? '<span class="rmx-neu">' + esc(T('rmx.only_group')) + '</span>' : '') +
                '</th>';
            _spalten.forEach(function (b, si) {
                var lbl = T(b.key) + ' – ' + name;
                koerper += '<td class="' + (z.an[si] !== z.vorher[si] ? 'rmx-geaendert' : '') + '">' +
                    '<input type="checkbox" class="rmx-cb" data-z="' + zi + '" data-s="' + si + '"' +
                    (z.an[si] ? ' checked' : '') + ' aria-label="' + esc(lbl) + '"></td>';
            });
            // Nur ueber eine Gruppe in der Liste: hier gibt es nichts zu loeschen
            // (die Mitgliedschaft pflegt das Verzeichnis) – also kein Muelleimer
            koerper += '<td>' + (z.nurGruppe ? '' : '<button type="button" class="kb-hdr-btn rmx-row-clear" data-z="' + zi +
                '" title="' + esc(T('rmx.row_clear')) + '" aria-label="' + esc(T('rmx.row_clear')) + '">' +
                (window.JarvisIcons ? window.JarvisIcons.trash() : '') + '</button>') + '</td></tr>';
        });
        if (!sichtbar) {
            koerper = '<tr><td colspan="' + (_spalten.length + 2) + '" class="rmx-leer">' +
                esc(T(f ? 'rmx.no_match' : 'rmx.empty')) + '</td></tr>';
        }
        wrap.innerHTML = '<table class="rmx-tabelle">' + kopf + '<tbody>' + koerper + '</tbody></table>';
        zustaende();   // indeterminate gibt es nur als Eigenschaft, nicht als Attribut
        erbeInfo();
        fussAktualisieren();
    }

    function fussAktualisieren() {
        var n = aenderungen();
        var btn = el('rmx-apply');
        btn.textContent = n ? T('rmx.apply_n').replace('{n}', n) : T('rmx.apply');
        // ohne geladenen Bestand bleibt der Knopf gesperrt (siehe oeffnen)
        btn.disabled = !n || !window._adGeladen;
    }

    function status(text, fehler) {
        var s = el('rmx-status');
        s.textContent = text || '';
        s.classList.toggle('rmx-status-fehler', !!fehler);
    }

    function oeffnen() {
        fensterAnlegen();
        // Fail-closed: ohne geladenen Bestand wuerde "Uebernehmen" leere
        // Listen speichern und damit jede Freigabe loeschen.
        if (!window._adGeladen) {
            status(T('rmx.not_loaded'), true);
        } else {
            status('');
        }
        _mitglieder = {};   // je Oeffnen frisch: die Gruppen koennen sich geaendert haben
        sortLaden();
        bestandEinlesen();
        el('rmx-filter').value = '';
        el('rmx-mitglieder').checked = _zeigeMitglieder;
        zeichnen();
        el('rmx-modal').classList.add('open');
        mitgliederLaden();
    }

    function schliessen() {
        var m = el('rmx-modal');
        if (m) m.classList.remove('open');
    }

    async function uebernehmen() {
        if (!window._adGeladen || typeof window._adSave !== 'function') {
            status(T('rmx.not_loaded'), true);
            return;
        }
        if (!aenderungen()) return;
        // Je Bereich und Art vom AKTUELLEN Feldinhalt ausgehen: Reihenfolge und
        // Schreibweise vorhandener Eintraege bleiben, nur Zu- und Abgaenge aendern sich.
        _spalten.forEach(function (b, si) {
            ['users', 'groups'].forEach(function (kind) {
                var inp = el(feldId(b, kind));
                var liste = teile(inp.value, kind);
                var vorher = liste.join('\u0000');
                _zeilen.forEach(function (z) {
                    if (z.kind !== kind || z.an[si] === z.vorher[si]) return;
                    var w = schluessel(kind, z.wert);
                    if (z.an[si]) {
                        if (!enthaelt(liste, z.wert, kind)) liste.push(z.wert);
                    } else {
                        liste = liste.filter(function (x) { return schluessel(kind, x) !== w; });
                    }
                });
                if (liste.join('\u0000') === vorher) return;
                inp.value = liste.join(JOIN[kind]);
                inp.dispatchEvent(new Event('change', { bubbles: true }));
            });
        });
        var btn = el('rmx-apply');
        btn.disabled = true;
        status(T('common.saving'));
        var ok = await window._adSave();
        if (ok) {
            status('');
            schliessen();
        } else {
            // Fehler bleibt stehen, bis jemand ihn gelesen hat
            status(T('rmx.save_failed'), true);
            btn.disabled = false;
        }
    }

    function knopfAnhaengen() {
        var btn = el('rmx-open');
        if (!btn || btn.dataset.rmx) return;
        btn.dataset.rmx = '1';
        btn.addEventListener('click', oeffnen);
    }

    window.RechteMatrix = { oeffnen: oeffnen };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', knopfAnhaengen);
    } else {
        knopfAnhaengen();
    }
})();
