/* ============================================================
 * syspackages.js – installierte Pakete, ⓘ in der Titelleiste (shared)
 *
 * NUR FUER ADMINISTRATOREN, und die Frage entscheidet `/api/me` – nicht die
 * Seite. Genau dieselbe Lehre wie beim Einstellungs-Zahnrad (settings_btn.js):
 * drei Seiten hingen ihre Sichtbarkeit an den Abruf ihres BEREICHS, und der
 * scheitert fuer einen Administrator ohne Bereichs-Freigabe – der Knopf blieb
 * dann weg, obwohl `/api/me` `is_admin: true` liefert.
 *
 * ⚠ SICHTBARKEIT IST KEINE BERECHTIGUNG. Der Knopf wird nur Admins gezeigt,
 * die Schranke sitzt aber am Endpunkt (`require_local_auth`). Ein Nicht-Admin,
 * der die URL kennt, bekommt 403 – nicht die Liste.
 *
 * WO ER SITZT: rechts neben der CPU-Anzeige, also in der LINKEN Gruppe der
 * Titelleiste (Vorgabe des Nutzers). Bewusst NICHT in der Symbolgruppe rechts:
 * deren Reihenfolge ist seit 2026-08-22 festgeschrieben und ueber alle Seiten
 * hinweg gleich (`tests/test_topbar_symbole_ui.js`) – ein zusaetzliches Symbol
 * dort haette sie auf jeder Seite verschoben.
 *
 * WARUM EIN GEMEINSAMES MODUL statt Markup je Seite: die CPU-Anzeige lag bis
 * 2026-08-22 in VIER eigenen Fassungen vor und fehlte deshalb auf sechs
 * Unterseiten. Hier gibt es EINE Fassung; eine neue Bereichsseite bindet das
 * Skript ein und hat den Knopf.
 *
 * DER BERICHT WIRD BEI JEDEM OEFFNEN NEU GEHOLT und nirgends zwischengelagert:
 * ein Paketstand ist eine Aussage ueber den Server im Moment der Frage. Ein
 * gemerkter Stand waere genau nach einem `apt upgrade` falsch – also dann, wenn
 * man nachsieht.
 * ============================================================ */
(function () {
    'use strict';

    if (window.JarvisSysPackages) return;   // doppeltes Laden vermeiden

    // Gleiche Kette wie cpubar.js/settings_btn.js: app.js, chat.js, userchat.js
    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];
    // Dieselben Wirte wie die CPU-Anzeige – der Knopf steht direkt daneben.
    var ANKER = ['.topbar-left', '.wi-topbar', '.pt-topbar', '.ad-top', '.sa-topbar'];

    // Deckel fuer die gezeichnete Tabelle. 2825 Zeilen sind zwar zeichenbar,
    // aber niemand liest sie am Stueck – und die Suche darueber ist der Weg zum
    // gesuchten Paket. WICHTIG: die Restzahl steht in der Fusszeile; eine
    // stillschweigend gekuerzte Liste haelt der Leser fuer vollstaendig
    // (Projektregel, dieselbe wie beim Badge-Panel und bei `cron_list`).
    var ZEILEN_MAX = 400;

    var _admin = false;
    var _bericht = null;      // letzter geholter Stand (nur solange offen)
    var _kasten = null;
    var _sortSpalte = 'package';
    var _sortAb = false;
    var _laeuft = false;

    function T(key, fallback) {
        try { if (window.t) return window.t(key) || fallback; } catch (e) {}
        return fallback;
    }

    function token() {
        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            try {
                var t = localStorage.getItem(TOKEN_KEYS[i]);
                if (t) return t;
            } catch (e) { /* Speicher gesperrt (privates Fenster, iframe) */ }
        }
        return '';
    }

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    /** KiB in eine lesbare Groesse. dpkg rechnet in KiB, nicht in KB. */
    function groesse(kb) {
        var n = Number(kb) || 0;
        if (n >= 1048576) return (n / 1048576).toFixed(2) + ' GiB';
        if (n >= 1024) return (n / 1024).toFixed(1) + ' MiB';
        return n + ' KiB';
    }

    /* ── Der Knopf ─────────────────────────────────────────────────────── */

    function knopf() { return document.getElementById('jv-pkg-btn'); }

    function aufbauen() {
        var b = knopf();
        if (b) return b;
        var wirt = null;
        for (var i = 0; i < ANKER.length && !wirt; i++) wirt = document.querySelector(ANKER[i]);
        if (!wirt) return null;                 // Seite ohne Titelleiste
        b = document.createElement('button');
        b.type = 'button';
        b.id = 'jv-pkg-btn';
        b.className = 'jv-pkg-btn';
        b.setAttribute('data-i18n-title', 'pkg.btn');
        b.setAttribute('data-i18n-aria', 'pkg.btn');
        b.title = T('pkg.btn', 'Installierte Pakete');
        b.setAttribute('aria-label', b.title);
        // Inline-SVG, kein Emoji: ein Emoji wird je System farbig gerendert und
        // folgt keinem Theme (Projektregel). Ein Info-Kreis ist die uebliche
        // Form fuer "Auskunft ueber dieses System".
        b.innerHTML = '<svg viewBox="0 0 24 24" width="18" height="18" fill="none"'
            + ' stroke="currentColor" stroke-width="2" stroke-linecap="round"'
            + ' stroke-linejoin="round" aria-hidden="true">'
            + '<circle cx="12" cy="12" r="10"/>'
            + '<line x1="12" y1="16" x2="12" y2="11"/>'
            + '<line x1="12" y1="8" x2="12.01" y2="8"/></svg>';
        b.addEventListener('click', oeffnen);
        // DIREKT hinter die CPU-Anzeige (Vorgabe). Fehlt sie – etwa weil das
        // Token noch nicht da war –, dann vor den Abstandhalter, damit der
        // Knopf nicht in der rechten Symbolgruppe landet.
        var cpu = document.getElementById('cpu-bar');
        if (cpu && cpu.parentNode === wirt) {
            wirt.insertBefore(b, cpu.nextSibling);
        } else {
            var luecke = wirt.querySelector('.pt-spacer, .wi-spacer, .ad-spacer, .sa-spacer');
            if (luecke) wirt.insertBefore(b, luecke); else wirt.appendChild(b);
        }
        return b;
    }

    function zeige(an) {
        var b = an ? aufbauen() : knopf();
        if (!b) return;
        // ZWEI Versteck-Mechanismen wie beim Zahnrad: /wissen benutzt die Klasse
        // `hidden` (dort `display: none !important`), ein blosses
        // `style.display = ''` verliert dagegen.
        b.style.display = an ? '' : 'none';
        if (an) b.classList.remove('hidden'); else b.classList.add('hidden');
    }

    /* ── Der Kasten ────────────────────────────────────────────────────── */

    function kastenEl() {
        if (_kasten) return _kasten;
        _kasten = document.createElement('div');
        _kasten.className = 'jv-pkg-overlay';
        _kasten.setAttribute('role', 'dialog');
        _kasten.setAttribute('aria-modal', 'true');
        _kasten.setAttribute('aria-label', T('pkg.title', 'Installierte Pakete'));
        // Klick auf die Flaeche DANEBEN schliesst – auf den Kasten selbst nicht.
        _kasten.addEventListener('click', function (e) {
            if (e.target === _kasten) schliessen();
        });
        document.body.appendChild(_kasten);
        return _kasten;
    }

    function offen() { return !!(_kasten && _kasten.classList.contains('an')); }

    function schliessen() {
        if (_kasten) _kasten.classList.remove('an');
        // Der Bericht wird NICHT behalten: beim naechsten Oeffnen soll ein
        // frischer Stand geholt werden, nicht der von vorhin.
        _bericht = null;
        document.removeEventListener('keydown', beiTaste);
        var b = knopf();
        if (b) b.focus();
    }

    function beiTaste(e) {
        if (e.key === 'Escape') { e.stopPropagation(); schliessen(); }
    }

    function rahmen(inhalt) {
        var el = kastenEl();
        el.innerHTML = '<div class="jv-pkg-box">' + inhalt + '</div>';
        el.classList.add('an');
        var zu = el.querySelector('.jv-pkg-close');
        if (zu) zu.addEventListener('click', schliessen);
        document.addEventListener('keydown', beiTaste);
    }

    function kopfzeile(rechts) {
        // × = schliessen (Symbol-Semantik des Projekts). Aus icons.js, wenn
        // vorhanden – sonst das Zeichen, damit der Kasten auch auf einer Seite
        // ohne icons.js schliessbar bleibt.
        var kreuz = '&times;';
        try { if (window.JarvisIcons) kreuz = window.JarvisIcons.close(); } catch (e) {}
        return '<div class="jv-pkg-head">'
            + '<div class="jv-pkg-h">' + esc(T('pkg.title', 'Installierte Pakete')) + '</div>'
            + (rechts || '')
            + '<button type="button" class="jv-pkg-close" title="'
            + esc(T('common.close', 'Schließen')) + '" aria-label="'
            + esc(T('common.close', 'Schließen')) + '">' + kreuz + '</button>'
            + '</div>';
    }

    function oeffnen() {
        if (_laeuft) return;
        if (offen()) { schliessen(); return; }
        _laeuft = true;
        rahmen(kopfzeile('') + '<div class="jv-pkg-lade">'
            + esc(T('pkg.loading', 'Paketbestand wird ermittelt …')) + '</div>');
        var t = token();
        fetch('/api/system/packages', { headers: { 'Authorization': 'Bearer ' + t } })
            .then(function (r) {
                return r.json().catch(function () { return null; })
                    .then(function (d) { return { ok: r.ok, status: r.status, d: d }; });
            })
            .then(function (a) {
                if (!a.ok || !a.d || !a.d.pakete) {
                    // Der GRUND steht in der Antwort (503 = dpkg antwortet
                    // nicht, 403 = kein Administrator). Ihn zu verschlucken
                    // hiesse, den Leser im Journal suchen zu lassen.
                    fehlerZeigen((a.d && a.d.error) || (a.status === 403
                        ? T('pkg.err_admin', 'Nur für Administratoren.')
                        : T('pkg.err', 'Der Paketbestand konnte nicht gelesen werden.')));
                    return;
                }
                _bericht = a.d;
                zeichnen();
            })
            .catch(function () {
                fehlerZeigen(T('pkg.err_net', 'Der Server war nicht erreichbar.'));
            })
            .then(function () { _laeuft = false; });
    }

    function fehlerZeigen(text) {
        rahmen(kopfzeile('') + '<div class="jv-pkg-fehler">' + esc(text) + '</div>');
    }

    /** Sortiert eine Kopie – die Reihenfolge im Bericht bleibt unangetastet,
     *  weil der Download genau das ausliefern soll, was die API geliefert hat. */
    function sortiert(liste) {
        var s = _sortSpalte, ab = _sortAb;
        var kopie = liste.slice();
        kopie.sort(function (a, b) {
            var x = a[s], y = b[s];
            var r;
            if (s === 'size_kb') r = (Number(x) || 0) - (Number(y) || 0);
            else r = String(x || '').localeCompare(String(y || ''), undefined,
                                                   { numeric: true, sensitivity: 'base' });
            // Gleichstand nach Namen: sonst springt die Anzeige bei jedem
            // Neuzeichnen, weil `sort` nur stabil ist, solange die Eingabe es ist.
            if (r === 0 && s !== 'package') {
                r = String(a.package).localeCompare(String(b.package));
            }
            return ab ? -r : r;
        });
        return kopie;
    }

    function zeichnen() {
        if (!_bericht) return;
        var suchfeld = document.getElementById('jv-pkg-suche');
        var q = (suchfeld ? suchfeld.value : '').trim().toLowerCase();
        var alle = _bericht.pakete || [];
        var treffer = !q ? alle : alle.filter(function (p) {
            return (p.package || '').toLowerCase().indexOf(q) >= 0
                || (p.summary || '').toLowerCase().indexOf(q) >= 0
                || (p.version || '').toLowerCase().indexOf(q) >= 0;
        });
        var zeigen = sortiert(treffer).slice(0, ZEILEN_MAX);
        var rest = treffer.length - zeigen.length;

        var pfeil = function (sp) {
            return _sortSpalte === sp ? (_sortAb ? ' ▾' : ' ▴') : '';
        };
        var th = function (sp, txt, klasse) {
            return '<th class="' + (klasse || '') + '" data-sort="' + sp + '" tabindex="0" role="button">'
                + esc(txt) + pfeil(sp) + '</th>';
        };

        var zeilen = zeigen.map(function (p) {
            // Alles maskiert: Namen und Zusammenfassungen stammen aus der
            // Paketdatenbank, also aus fremden Quellen.
            return '<tr><td class="jv-pkg-n">' + esc(p.package)
                + (p.status && p.status.charAt(0) === 'h'
                    ? ' <span class="jv-pkg-hold" title="'
                      + esc(T('pkg.hold', 'auf „hold“ – wird nicht aktualisiert'))
                      + '">hold</span>' : '')
                + '</td>'
                + '<td class="jv-pkg-v">' + esc(p.version) + '</td>'
                + '<td class="jv-pkg-r">' + esc(groesse(p.size_kb)) + '</td>'
                + '<td class="jv-pkg-d">' + esc((p.update_date || '').slice(0, 10)) + '</td>'
                + '<td class="jv-pkg-s">' + esc(p.summary) + '</td></tr>';
        }).join('');

        var meta = esc(T('pkg.count', '{n} Pakete').replace('{n}', String(_bericht.anzahl)))
            + ' · ' + esc(groesse(_bericht.groesse_kb_gesamt))
            + (_bericht.host ? ' · ' + esc(_bericht.host) : '')
            + ' · ' + esc(zeitpunkt(_bericht.erzeugt_am));

        rahmen(
            kopfzeile('<button type="button" class="jv-pkg-dl">'
                + esc(T('pkg.download', 'JSON herunterladen')) + '</button>')
            + '<div class="jv-pkg-meta">' + meta + '</div>'
            + '<input type="search" id="jv-pkg-suche" class="jv-pkg-suche" autocomplete="off"'
            + ' placeholder="' + esc(T('pkg.search', 'Paket, Version oder Beschreibung suchen …'))
            + '" value="' + esc(q) + '">'
            + '<div class="jv-pkg-scroll"><table class="jv-pkg-tab"><thead><tr>'
            + th('package', T('pkg.col_name', 'Paket'))
            + th('version', T('pkg.col_version', 'Version'))
            + th('size_kb', T('pkg.col_size', 'Größe'), 'jv-pkg-r')
            + th('update_date', T('pkg.col_date', 'Stand'))
            + th('summary', T('pkg.col_summary', 'Beschreibung'))
            + '</tr></thead><tbody>' + zeilen + '</tbody></table></div>'
            // ⚠ DIE RESTZAHL MUSS DASTEHEN – ohne sie haelt der Leser die
            // gekuerzte Liste fuer den ganzen Bestand.
            + '<div class="jv-pkg-fuss">'
            + (rest > 0
                ? esc(T('pkg.more', '… und {n} weitere – suchen oder JSON herunterladen')
                        .replace('{n}', String(rest)))
                : esc(T('pkg.shown', '{n} angezeigt').replace('{n}', String(zeigen.length))))
            + ' · ' + esc(T('pkg.date_hint',
                'Der Stand ist der Zeitpunkt, zu dem dpkg die Dateiliste zuletzt geschrieben '
                + 'hat (Installation oder Aktualisierung) – dpkg führt kein Installationsdatum.'))
            + '</div>');

        var box = _kasten.querySelector('.jv-pkg-box');
        var s2 = document.getElementById('jv-pkg-suche');
        if (s2) {
            s2.addEventListener('input', zeichnen);
            // Escape im Suchfeld leert erst, schliesst nicht: sonst ist eine
            // Tippkorrektur nicht von "Kasten zu" zu unterscheiden.
            s2.addEventListener('keydown', function (e) {
                if (e.key === 'Escape' && s2.value) { e.stopPropagation(); s2.value = ''; zeichnen(); }
            });
            if (q) { s2.focus(); s2.setSelectionRange(q.length, q.length); }
        }
        Array.prototype.forEach.call(box.querySelectorAll('th[data-sort]'), function (h) {
            var um = function () {
                var sp = h.getAttribute('data-sort');
                // Groesse und Datum fangen absteigend an – "das groesste" und
                // "das neueste" ist die Frage, die man dort stellt.
                if (_sortSpalte === sp) _sortAb = !_sortAb;
                else { _sortSpalte = sp; _sortAb = (sp === 'size_kb' || sp === 'update_date'); }
                zeichnen();
            };
            h.addEventListener('click', um);
            h.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); um(); }
            });
        });
        var dl = box.querySelector('.jv-pkg-dl');
        if (dl) dl.addEventListener('click', herunterladen);
    }

    function zeitpunkt(iso) {
        try {
            return new Date(iso).toLocaleString(undefined,
                { day: '2-digit', month: '2-digit', year: 'numeric',
                  hour: '2-digit', minute: '2-digit' });
        } catch (e) { return String(iso || ''); }
    }

    /* Download aus dem BEREITS GELADENEN Bericht (Blob), nicht ueber einen
     * zweiten Abruf.
     *
     * Der Grund ist nicht Sparsamkeit: ein `<a href>` kann keinen
     * Authorization-Header setzen, der Link braeuchte also `?token=` – und
     * damit stuende das Sitzungstoken in der Adresszeile, im Verlauf und in
     * jedem Proxy-Log. Der Blob umgeht das vollstaendig. Ausgeliefert wird
     * exakt das, was die API geliefert hat. */
    function herunterladen() {
        if (!_bericht) return;
        var name = 'pakete_' + (_bericht.host || 'host').replace(/[^A-Za-z0-9_-]/g, '')
            + '_' + new Date().toISOString().slice(0, 19).replace(/[-:]/g, '').replace('T', '_')
            + '.json';
        var url = '';
        try {
            var blob = new Blob([JSON.stringify(_bericht, null, 2)],
                                { type: 'application/json' });
            url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url; a.download = name;
            document.body.appendChild(a);
            a.click();
            a.parentNode.removeChild(a);
        } catch (e) { /* kein Download moeglich - der Kasten bleibt stehen */ }
        // Erst nach dem Klick freigeben, sonst ist der Blob schon weg.
        if (url) setTimeout(function () { URL.revokeObjectURL(url); }, 30000);
    }

    /* ── Start ─────────────────────────────────────────────────────────── */

    var _lauf = null;

    function pruefe() {
        if (_lauf) return _lauf.then(function (an) { zeige(an); return an; });
        var t = token();
        if (!t) { zeige(false); return Promise.resolve(false); }
        _lauf = fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + t } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                _admin = !!(d && d.is_admin);
                zeige(_admin);
                return _admin;
            })
            // Kein Zustandswechsel bei Netzfehler: ohne belegten Admin-Status
            // entsteht der Knopf gar nicht erst.
            .catch(function () { return false; });
        return _lauf;
    }

    window.JarvisSysPackages = { pruefe: pruefe, oeffnen: oeffnen,
                                 schliessen: schliessen };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', pruefe);
    } else {
        pruefe();
    }

    // Der Kasten wird gerendert und steht nicht im Markup – `applyLang()`
    // erreicht ihn nicht. Neu zeichnen, NICHT neu abrufen.
    window.addEventListener('jarvis-lang-changed', function () {
        var b = knopf();
        if (b) {
            b.title = T('pkg.btn', 'Installierte Pakete');
            b.setAttribute('aria-label', b.title);
        }
        if (offen() && _bericht) zeichnen();
    });
})();
