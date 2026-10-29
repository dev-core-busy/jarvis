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
    var TOKEN_KEYS = window.JarvisSitzung.tokenSchluessel();
    // Dieselben Wirte wie die CPU-Anzeige – der Knopf steht direkt daneben.
    var ANKER = ['.topbar-left', '.wi-topbar', '.pt-topbar', '.ad-top', '.sa-topbar'];

    // Deckel fuer die gezeichnete Tabelle. 2825 Zeilen sind zwar zeichenbar,
    // aber niemand liest sie am Stueck – und die Suche darueber ist der Weg zum
    // gesuchten Paket. WICHTIG: die Restzahl steht in der Fusszeile; eine
    // stillschweigend gekuerzte Liste haelt der Leser fuer vollstaendig
    // (Projektregel, dieselbe wie beim Badge-Panel und bei `cron_list`).
    var ZEILEN_MAX = 400;

    /* DIE EINZEILER, mit denen ein Administrator die Liste selbst nachrechnen
     * kann. Sie stehen hier als KONSTANTEN und nicht in i18n: ein Befehl ist
     * kein Text, den man uebersetzt – und uebersetzt wuerde er frueher oder
     * spaeter angefasst und damit falsch.
     *
     * ⚠ SIE MUESSEN ZUM BACKEND PASSEN. Das Abfrageformat ist woertlich
     * `_FORMAT` aus `backend/system_packages.py`, der `awk`-Filter ist dessen
     * Statuspruefung (`status[1] != 'i'` -> uebersprungen). Laufen die beiden
     * auseinander, zeigt die Oberflaeche einen Befehl, der ETWAS ANDERES
     * liefert als die Liste darueber – und der Anwender haelt genau diesen
     * Unterschied fuer einen Fehler. `tests/test_system_packages.py` haelt sie
     * deshalb als Drift-Schranke zusammen.
     *
     * Gemessen auf DEV: beide Wege liefern 2825 Pakete und 11036400 KiB; ohne
     * den Filter waeren es 2844 – die 19 `rc`-Eintraege sind der Unterschied,
     * den der Filter macht. */
    var BEFEHLE = {
        liste: "dpkg-query -W -f='${db:Status-Abbrev}|${Package}|${Version}"
             + "|${Architecture}|${Installed-Size}|${binary:Summary}\\n'"
             + " | awk -F'|' 'substr($1,2,1)==\"i\"'",
        stand: "stat -c '%y  %n' /var/lib/dpkg/info/bash.list"
    };

    // Der Aufklapp-Zustand wird GEMERKT: `zeichnen()` baut den Kasten bei jedem
    // Tastendruck in der Suche neu auf – ohne diesen Merker klappte die
    // Erklaerung beim Tippen jedes Mal wieder zu.
    var _wieOffen = false;

    var _admin = false;
    var _bericht = null;      // letzter geholter Stand (nur solange offen)
    var _kasten = null;
    var _sortSpalte = 'package';
    var _sortAb = false;
    var _laeuft = false;

    /* SICHERHEITSLUECKEN (CVE, backend/cve_pruefung.py). Der Stand kommt aus
     * einem EIGENEN Abruf (`/api/system/cve`) und wird NICHT abgewartet: die
     * Paketliste erscheint sofort, die Markierungen kommen dazu, sobald sie da
     * sind (Register: eine Liste wartet nie auf eine zweite Anfrage).
     * Markiert wird je BINAERPAKET, obwohl Debian die Luecke am Quellpaket
     * fuehrt – der Befund nennt die betroffenen Binaerpakete selbst. */
    var _cve = null;          // Antwort von /api/system/cve
    var _cvePoll = null;
    var _nurLuecken = false;  // Filter "nur betroffene Pakete"
    var _cveOffen = {};       // aufgeklappte Detailzeilen je Paket
    var _cveMeldung = '';     // Ergebnis/Fehler am Knopf (bleibt stehen)
    /* BADGE AM ⓘ-KNOPF (Vorgabe 2026-10-29: nicht am Zahnrad). Die Zahl kommt
     * aus `/api/me` (`cve_badge`, nur fuer Admins) – derselbe Abruf, der den
     * Knopf ueberhaupt einblendet. Gezaehlt werden PAKETE mit Handlungsbedarf
     * oder ungesehenen Luecken (backend/cve_pruefung.badge). */
    var _cveBadge = null;
    var _badgeTimer = null;
    var BADGE_MS = 60000;
    // Rangfolge der Markierung: die dringlichste Klasse eines Pakets zeigt sich.
    var CVE_RANG = { behebbar: 0, neustart: 1, nicht_im_index: 2,
                     zurueckgehalten: 3, lock: 4, offen: 5, ausgenommen: 6 };

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
        _cve = null;
        _cveOffen = {};
        _cveMeldung = '';
        if (_cvePoll) { clearTimeout(_cvePoll); _cvePoll = null; }
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

    function oeffnen(opt) {
        if (_laeuft) return;
        if (offen()) { schliessen(); return; }
        // Aus der Zahnrad-Badge: gleich auf die betroffenen Pakete gefiltert.
        // (Ein Klick-Ereignis als Argument ist KEIN Wunsch nach dem Filter.)
        _nurLuecken = !!(opt && opt.nurLuecken === true);
        _laeuft = true;
        cveLaden();
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
            if (s === 'size_kb' || s === 'cve') r = (Number(x) || 0) - (Number(y) || 0);
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

    /** Eine Befehlszeile mit Kopier-Knopf.
     *
     * Der Befehl steht im Klartext DA und wird zusaetzlich zum Kopieren
     * angeboten: wer einen `awk`-Ausdruck abtippen muss, vollzieht nichts nach.
     * Der Knopf traegt nur den SCHLUESSEL, nie den Befehl selbst – so kann aus
     * einem Attributwert nie ein anderer Befehl werden als der angezeigte. */
    function cmdZeile(schluessel) {
        return '<div class="jv-pkg-cmdrow">'
            + '<code class="jv-pkg-cmd">' + esc(BEFEHLE[schluessel]) + '</code>'
            + '<button type="button" class="jv-pkg-copy" data-cmd="' + esc(schluessel)
            + '">' + esc(T('pkg.copy', 'Kopieren')) + '</button></div>';
    }

    /* Kopieren MIT Rueckmeldung. Ohne sie waere ein Fehlschlag unsichtbar – in
     * der Zwischenablage sieht man nichts, und `navigator.clipboard` fehlt in
     * unsicheren Kontexten ganz. Die Meldung nennt dann den Ausweg (markieren),
     * statt den Benutzer glauben zu lassen, es haette geklappt. */
    function kopiere(k, text) {
        var fertig = function (gut) {
            // Beim ERSTEN Klick den Ruhetext sichern - sonst wird beim zweiten
            // Klick "Kopiert" als Ruhetext gemerkt und bleibt fuer immer stehen.
            if (!k.getAttribute('data-ruhe')) k.setAttribute('data-ruhe', k.textContent);
            k.textContent = gut ? T('pkg.copied', 'Kopiert')
                                : T('pkg.copy_fail', 'Nicht möglich – bitte markieren');
            if (gut) k.classList.remove('ist-fehler'); else k.classList.add('ist-fehler');
            setTimeout(function () {
                k.textContent = k.getAttribute('data-ruhe') || '';
                k.classList.remove('ist-fehler');
            }, gut ? 1600 : 3500);
        };
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(text).then(function () { fertig(true); },
                                                         function () { fertig(false); });
                return;
            }
        } catch (e) { /* faellt unten durch */ }
        fertig(false);
    }

    /** „Wie diese Liste entsteht" – zugeklappt per Vorgabe.
     *
     * Der Anlass ist eine Frage des Nutzers: eine Zahl ohne Herkunft ist eine
     * Behauptung. Hier steht, WORAUS sie entsteht – und mit den Einzeilern kann
     * ein Administrator sie auf dem Server selbst nachrechnen, statt sie mir zu
     * glauben. Zugeklappt, weil die Tabelle der Zweck des Kastens ist; der
     * Zustand ueberlebt das Neuzeichnen (`_wieOffen`).
     */
    function wieBlock() {
        return '<details class="jv-pkg-wie"' + (_wieOffen ? ' open' : '') + '>'
            + '<summary>' + esc(T('pkg.how_title', 'Wie diese Liste entsteht'))
            + '</summary><div class="jv-pkg-wie-in">'
            + '<p>' + esc(T('pkg.how_src', '')) + '</p>'
            + '<p>' + esc(T('pkg.how_filter', '')) + '</p>'
            + '<p>' + esc(T('pkg.how_fields', '')) + '</p>'
            + '<p>' + esc(T('pkg.how_cmd1', '')) + '</p>'
            + cmdZeile('liste')
            + '<p>' + esc(T('pkg.how_cmd2', '')) + '</p>'
            + cmdZeile('stand')
            + '</div></details>';
    }

    function zeichnen() {
        if (!_bericht) return;
        var suchfeld = document.getElementById('jv-pkg-suche');
        var q = (suchfeld ? suchfeld.value : '').trim().toLowerCase();
        var jePaket = cveJePaket();
        var alle = (_bericht.pakete || []).map(function (p) {
            // Sortierschluessel fuer die Spalte „Lücken" (Kopie, der Bericht bleibt roh).
            var i = jePaket[p.package];
            return Object.assign({}, p, { cve: i ? i.rang : 99 });
        });
        if (_nurLuecken) alle = alle.filter(function (p) { return p.cve < 99; });
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
                + '<td class="jv-pkg-l">' + cveChip(p.package, jePaket[p.package]) + '</td>'
                + '<td class="jv-pkg-s">' + esc(p.summary) + '</td></tr>'
                + (_cveOffen[p.package] && jePaket[p.package]
                    ? '<tr class="jv-pkg-cve-zeile"><td colspan="6"><ul class="jv-pkg-cve-liste">'
                      + befundZeilen(jePaket[p.package].befunde) + '</ul>'
                      + einzelKnopf(jePaket[p.package].befunde)
                      + (quittierbareIds(jePaket[p.package].befunde).length
                          ? '<button type="button" class="jv-pkg-cve-btn" data-cve-aktion="gesehen" data-cve-paket="'
                            + esc(p.package) + '">' + esc(T('pkg.cve_gesehen_btn', 'Als gesehen markieren')) + '</button>'
                          : '')
                      + '</td></tr>'
                    : '');
        }).join('');

        var meta = esc(T('pkg.count', '{n} Pakete').replace('{n}', String(_bericht.anzahl)))
            + ' · ' + esc(groesse(_bericht.groesse_kb_gesamt))
            + (_bericht.host ? ' · ' + esc(_bericht.host) : '')
            + ' · ' + esc(zeitpunkt(_bericht.erzeugt_am));

        rahmen(
            kopfzeile('<button type="button" class="jv-pkg-dl">'
                + esc(T('pkg.download', 'JSON herunterladen')) + '</button>')
            + '<div class="jv-pkg-meta">' + meta + '</div>'
            + cveBlock()
            + '<input type="search" id="jv-pkg-suche" class="jv-pkg-suche" autocomplete="off"'
            + ' placeholder="' + esc(T('pkg.search', 'Paket, Version oder Beschreibung suchen …'))
            + '" value="' + esc(q) + '">'
            + '<div class="jv-pkg-scroll"><table class="jv-pkg-tab"><thead><tr>'
            + th('package', T('pkg.col_name', 'Paket'))
            + th('version', T('pkg.col_version', 'Version'))
            + th('size_kb', T('pkg.col_size', 'Größe'), 'jv-pkg-r')
            + th('update_date', T('pkg.col_date', 'Stand'))
            + th('cve', T('pkg.col_cve', 'Lücken'))
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
            + wieBlock()
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
        var wie = box.querySelector('.jv-pkg-wie');
        if (wie) wie.addEventListener('toggle', function () { _wieOffen = wie.open; });
        Array.prototype.forEach.call(box.querySelectorAll('.jv-pkg-copy'), function (k) {
            k.addEventListener('click', function () {
                kopiere(k, BEFEHLE[k.getAttribute('data-cmd')] || '');
            });
        });
        var dl = box.querySelector('.jv-pkg-dl');
        if (dl) dl.addEventListener('click', herunterladen);
        var nl = document.getElementById('jv-pkg-nurluecken');
        if (nl) nl.addEventListener('change', function () { _nurLuecken = nl.checked; zeichnen(); });
        Array.prototype.forEach.call(box.querySelectorAll('button.jv-pkg-cve[data-cve-paket]'), function (c) {
            c.addEventListener('click', function () {
                var n = c.getAttribute('data-cve-paket');
                _cveOffen[n] = !_cveOffen[n];
                zeichnen();
            });
        });
        Array.prototype.forEach.call(box.querySelectorAll('[data-cve-aktion]'), function (k) {
            k.addEventListener('click', function () {
                cveAktion(k.getAttribute('data-cve-aktion'), k.getAttribute('data-cve-paket'),
                          k.getAttribute('data-cve-quelle'));
            });
        });
    }

    /* ── Sicherheitsluecken ──────────────────────────────────────────── */

    /* Malt die Badge in den Knopf (bzw. entfernt sie). Die Aufschluesselung
     * steht als `title` an der Badge: das Fenster dahinter zeigt alles
     * Weitere, ein Klick auf die Badge oeffnet es gefiltert. */
    function badgeMalen() {
        var b = knopf();
        if (!b) return;
        var el = b.querySelector('.jv-pkg-badge');
        var n = (_admin && _cveBadge && _cveBadge.anzahl) || 0;
        if (!n) {
            if (el) el.parentNode.removeChild(el);
            return;
        }
        if (!el) {
            el = document.createElement('span');
            el.className = 'jv-pkg-badge';
            // Eigener Klick: die Badge fuehrt direkt zu den betroffenen
            // Paketen, der Knopf darunter oeffnet die ganze Liste.
            el.addEventListener('click', function (e) {
                e.stopPropagation();
                window.JarvisSysPackages.oeffnenLuecken();
            });
            b.appendChild(el);
        }
        var posten = _cveBadge.posten || [];
        var dringend = posten.some(function (p) {
            var z = p.zaehler || {};
            return z.behebbar || z.neustart;
        });
        el.textContent = n > 99 ? '99+' : String(n);
        el.classList.toggle('is-danger', dringend);
        var zeilen = posten.map(function (p) {
            var z = p.zaehler || {};
            var teile = ['behebbar', 'neustart', 'nicht_im_index', 'zurueckgehalten', 'lock', 'offen']
                .filter(function (k) { return z[k]; })
                .map(function (k) { return z[k] + ' ' + klasseText(k); });
            return (p.bereich && p.bereich !== 'debian' ? bereichText(p.bereich) + ' ' : '')
                + p.titel + ': ' + teile.join(', ');
        });
        if (n > posten.length) {
            zeilen.push(T('pkg.cve_badge_mehr', '… und {n} weitere').replace('{n}', String(n - posten.length)));
        }
        var kopf = T('pkg.cve_badge', 'Pakete mit Sicherheitslücken: {n}').replace('{n}', String(n));
        el.title = kopf + '\n' + zeilen.join('\n');
        el.setAttribute('aria-label', kopf);
    }

    function badgeHolen() {
        var t = token();
        if (!t || !_admin) return;
        fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + t } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d) return;
                _cveBadge = d.cve_badge || null;
                badgeMalen();
            })
            .catch(function () { /* letzter Stand bleibt stehen */ });
    }

    function cveLaden() {
        var t = token();
        return fetch('/api/system/cve', { headers: { 'Authorization': 'Bearer ' + t } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!offen()) return;
                _cve = d;
                if (_bericht) zeichnen();
                // Laeuft gerade eine Pruefung, nachfragen, bis sie fertig ist.
                if (d && d.laeuft) {
                    if (_cvePoll) clearTimeout(_cvePoll);
                    _cvePoll = setTimeout(cveLaden, 3000);
                } else {
                    // Nach Lauf oder Quittung: die Badge dem neuen Stand folgen lassen.
                    badgeHolen();
                }
            })
            .catch(function () { /* Liste bleibt stehen, nur ohne Markierung */ });
    }

    function cveBefunde() { return (_cve && _cve.ergebnis && _cve.ergebnis.befunde) || []; }

    function cveGesehen() {
        var m = {};
        ((_cve && _cve.quittiert) || []).forEach(function (k) { m[k] = true; });
        return m;
    }

    /** Binaerpaket -> {rang, klasse, befunde[]} (nur Debian). */
    function cveJePaket() {
        var m = {};
        cveBefunde().forEach(function (b) {
            if (b.bereich !== 'debian') return;
            (b.pakete || []).forEach(function (n) {
                var e = m[n] || (m[n] = { rang: 99, klasse: '', befunde: [] });
                e.befunde.push(b);
                var r = CVE_RANG[b.klasse] != null ? CVE_RANG[b.klasse] : 9;
                if (r < e.rang) { e.rang = r; e.klasse = b.klasse; }
            });
        });
        return m;
    }

    /* Woertliche Schluessel statt zusammengesetzter: der Waechter
     * (test_system_packages.py) prueft, dass jeder benutzte Schluessel in
     * i18n.js existiert – ein `'pkg.cve_k_' + k` kann er nicht nachsehen. */
    function klasseText(k) {
        switch (k) {
            case 'behebbar': return T('pkg.cve_k_behebbar', 'Update verfügbar');
            case 'neustart': return T('pkg.cve_k_neustart', 'Neustart nötig');
            case 'nicht_im_index': return T('pkg.cve_k_nicht_im_index', 'Update noch nicht im Paketindex');
            case 'zurueckgehalten': return T('pkg.cve_k_zurueckgehalten', 'zurückgehalten');
            case 'lock': return T('pkg.cve_k_lock', 'Update nur über die Lock-Datei');
            case 'offen': return T('pkg.cve_k_offen', 'ohne Debian-Update');
            case 'ausgenommen': return T('pkg.cve_k_ausgenommen', 'bewertet');
        }
        return String(k || '');
    }

    function einstufungText(e) {
        switch (e) {
            case 'unimportant': return T('pkg.cve_e_unimportant', 'unwichtig');
            case 'low': return T('pkg.cve_e_low', 'niedrig');
            case 'medium': return T('pkg.cve_e_medium', 'mittel');
            case 'high': return T('pkg.cve_e_high', 'hoch');
        }
        return T('pkg.cve_e_keine', 'nicht eingestuft');
    }

    function bereichText(b) {
        switch (b) {
            case 'debian': return T('pkg.cve_ber_debian', 'Debian');
            case 'python': return T('pkg.cve_ber_python', 'Python');
            case 'npm': return T('pkg.cve_ber_npm', 'WhatsApp-Bridge');
        }
        return String(b || '');
    }

    /** Markierung in der Spalte „Lücken": dringlichste Klasse + Anzahl. */
    function cveChip(name, info) {
        if (!info) return '';
        var gesehen = cveGesehen();
        var alleGesehen = info.befunde.every(function (b) { return gesehen[b.id]; });
        var nurUnwichtig = info.klasse === 'offen' && info.befunde.every(function (b) {
            return b.einstufung === 'unimportant';
        });
        var stufe = nurUnwichtig || (alleGesehen && info.klasse === 'offen')
            ? 'leise' : info.klasse;
        return '<button type="button" class="jv-pkg-cve jv-pkg-cve-' + esc(stufe)
            + '" data-cve-paket="' + esc(name) + '" title="'
            + esc(klasseText(info.klasse) + ' – ' + T('pkg.cve_details', 'Details anzeigen'))
            + '">' + esc(klasseText(info.klasse)) + ' · ' + info.befunde.length + '</button>';
    }

    function trackerLink(cve) {
        // Nur CVE-Kennungen verlinken – eine OSV-/GHSA-Kennung kennt der Tracker nicht.
        if (!/^CVE-\d{4}-\d+$/.test(cve || '')) return esc(cve);
        return '<a href="https://security-tracker.debian.org/tracker/' + esc(cve)
            + '" target="_blank" rel="noopener noreferrer">' + esc(cve) + '</a>';
    }

    function befundZeilen(befunde) {
        var gesehen = cveGesehen();
        var rang = function (b) { return CVE_RANG[b.klasse] != null ? CVE_RANG[b.klasse] : 9; };
        return befunde.slice().sort(function (a, b) {
            return rang(a) - rang(b) || String(a.cve).localeCompare(String(b.cve));
        }).map(function (b) {
            var zusatz = [];
            if (b.fix) zusatz.push(T('pkg.cve_fix', 'behoben in') + ' ' + b.fix);
            if (b.kandidat && b.klasse !== 'offen') zusatz.push(T('pkg.cve_kand', 'verfügbar') + ' ' + b.kandidat);
            if (b.klasse === 'behebbar' && b.bereich === 'debian') {
                zusatz.push(b.aus_sicherheitsquelle ? T('pkg.cve_q_sich', 'aus der Sicherheitsquelle')
                                                    : T('pkg.cve_q_reg', 'nur in der regulären Quelle'));
            }
            if (b.klasse === 'lock') {
                zusatz.push(T('pkg.cve_lock_hinweis', 'Dieser Server folgt der Lock-Datei des Repositorys und hebt Python-Pakete nicht selbst – behoben wird über eine neue Lock-Datei.'));
            }
            if (b.nodsa) zusatz.push(T('pkg.cve_nodsa', 'Debian behebt ohne Sicherheitsmeldung') + ': ' + b.nodsa);
            return '<li class="' + (gesehen[b.id] ? 'ist-gesehen' : '') + '">'
                + '<span class="jv-pkg-cve-id">' + trackerLink(b.cve) + '</span> '
                + '<span class="jv-pkg-cve jv-pkg-cve-' + esc(b.klasse) + ' ist-klein">'
                + esc(klasseText(b.klasse)) + '</span> '
                + '<span class="jv-pkg-cve-e">' + esc(einstufungText(b.einstufung)) + '</span>'
                + (b.veroeffentlicht ? ' <span class="jv-pkg-cve-e">· '
                    + esc(T('pkg.cve_veroeff', 'veröffentlicht') + ' ' + b.veroeffentlicht) + '</span>' : '')
                + (gesehen[b.id] ? ' <span class="jv-pkg-cve-e">· ' + esc(T('pkg.cve_gesehen', 'gesehen')) + '</span>' : '')
                + (zusatz.length ? '<div class="jv-pkg-cve-z">' + esc(zusatz.join(' · ')) + '</div>' : '')
                + (b.text ? '<div class="jv-pkg-cve-t">' + esc(b.text) + '</div>' : '')
                + '</li>';
        }).join('');
    }

    function quittierbareIds(befunde) {
        var gesehen = cveGesehen();
        return befunde.filter(function (b) { return b.quittierbar && !gesehen[b.id]; })
                      .map(function (b) { return b.id; });
    }

    /** Kopfblock: Stand der Pruefung, Zaehler, Knoepfe. */
    function cveBlock() {
        if (!_cve) {
            return '<div class="jv-pkg-cvebar"><span class="jv-pkg-cve-st">'
                + '<span class="jv-pkg-spin" aria-hidden="true"></span>'
                + esc(T('pkg.cve_laedt', 'Sicherheitslücken werden geladen …')) + '</span></div>';
        }
        var erg = _cve.ergebnis;
        var plan = _cve.plan || {};
        var teile = [];
        if (_cve.laeuft) {
            teile.push('<span class="jv-pkg-spin" aria-hidden="true"></span>'
                + esc(T('pkg.cve_laeuft', 'Prüfung läuft …'))
                + (_cve.schritt === 'beheben' ? ' (' + esc(T('pkg.cve_schritt_beheben', 'Pakete werden aktualisiert')) + ')' : ''));
        } else if (!erg) {
            teile.push(esc(T('pkg.cve_nie', 'Noch nicht auf Sicherheitslücken geprüft.')));
        } else if (erg.ok === false) {
            teile.push('<span class="jv-pkg-cve-fehler">' + esc(erg.fehler || '') + '</span>');
        } else {
            var z = erg.zaehler || {};
            var unges = quittierbareIds(cveBefunde()).length;
            teile.push(esc(T('pkg.cve_stand', 'Geprüft {zeit}').replace('{zeit}', zeitpunkt(erg.erzeugt_am))));
            ['behebbar', 'neustart', 'nicht_im_index', 'zurueckgehalten', 'lock', 'offen'].forEach(function (k) {
                if (z[k]) teile.push('<span class="jv-pkg-cve jv-pkg-cve-' + k + ' ist-klein">'
                    + esc(klasseText(k)) + ': ' + z[k] + '</span>');
            });
            if (!z.behebbar && !z.neustart && !z.offen && !z.nicht_im_index && !z.zurueckgehalten && !z.lock) {
                teile.push(esc(T('pkg.cve_keine', 'keine bekannten Lücken')));
            }
            if (unges) teile.push(esc(T('pkg.cve_neu', '{n} noch nicht gesehen').replace('{n}', String(unges))));
            // Was NICHT geprueft wurde, steht da – sonst saehe es wie "keine Luecken" aus.
            var ber = erg.bereiche || {};
            ['debian', 'python', 'npm'].forEach(function (k) {
                var b = ber[k];
                if (b && !b.geprueft) {
                    teile.push(esc(bereichText(k) + ': '
                        + T('pkg.cve_nicht', 'nicht geprüft') + (b.grund ? ' (' + b.grund + ')' : '')));
                }
            });
            if (ber.debian && ber.debian.tracker_hinweis) teile.push(esc(ber.debian.tracker_hinweis));
            // Pakete aus Fremdquellen (z. B. NodeSource) kennt der Debian-Tracker
            // nicht – sie werden genannt, damit "keine Markierung" nicht wie
            // "keine Luecken" aussieht.
            if (ber.debian && ber.debian.fremd && ber.debian.fremd.length) {
                teile.push(esc(T('pkg.cve_fremd', 'Nicht über Debian prüfbar (andere Paketquelle)')
                    + ': ' + ber.debian.fremd.join(', ')));
            }
            // Ergebnis einer Behebung bleibt stehen, bis die naechste Pruefung
            // laeuft – ein Fehler darf nicht von selbst verschwinden (Register).
            var beh = erg.behebung;
            if (beh) {
                var inst = [], fehl = [];
                (beh.debian || []).forEach(function (r) {
                    (r.installiert || []).forEach(function (i) { inst.push(i.paket + ' ' + i.auf); });
                    if (r.fehler) fehl.push(r.fehler);
                    Object.keys(r.uebersprungen || {}).forEach(function (n) {
                        fehl.push(n + ': ' + r.uebersprungen[n]);
                    });
                });
                var py = (beh.python && beh.python.geaendert) || [];
                if (beh.python && beh.python.fehler) fehl.push('Python: ' + beh.python.fehler);
                teile.push('<span class="jv-pkg-cve-beh">' + esc(
                    T('pkg.cve_behoben', 'Aktualisiert: {n} Debian- und {p} Python-Pakete')
                        .replace('{n}', String(inst.length)).replace('{p}', String(py.length)))
                    + (inst.length ? ' (' + esc(inst.join(', ')) + ')' : '') + '</span>');
                if (fehl.length) teile.push('<span class="jv-pkg-cve-fehler">' + esc(fehl.join(' · ')) + '</span>');
            }
            if (ber.debian && ber.debian.neustart_noetig) {
                teile.push(esc(T('pkg.cve_reboot', 'Das System meldet: Neustart erforderlich')));
            }
        }
        var knoepfe = '<button type="button" class="jv-pkg-cve-btn" data-cve-aktion="pruefen"'
            + (_cve.laeuft ? ' disabled' : '') + '>' + esc(T('pkg.cve_pruefen', 'Auf Sicherheitslücken prüfen')) + '</button>';
        var nDeb = (plan.debian || []).length;
        if (!_cve.laeuft && (nDeb || plan.python || plan.index)) {
            knoepfe += '<button type="button" class="jv-pkg-cve-btn ist-haupt" data-cve-aktion="beheben">'
                + esc(T('pkg.cve_beheben', 'Behebbare jetzt beheben')
                      + (nDeb ? ' (' + nDeb + ')' : '')) + '</button>';
        }
        if (!_cve.laeuft && erg && quittierbareIds(cveBefunde()).length) {
            knoepfe += '<button type="button" class="jv-pkg-cve-btn" data-cve-aktion="alle_gesehen">'
                + esc(T('pkg.cve_alle_gesehen', 'Alle ohne Abhilfe als gesehen markieren')) + '</button>';
        }
        var filter = '<label class="jv-pkg-cve-filter"><input type="checkbox" id="jv-pkg-nurluecken"'
            + (_nurLuecken ? ' checked' : '') + '> ' + esc(T('pkg.cve_filter', 'Nur betroffene Pakete')) + '</label>';
        // Python- und npm-Befunde haben keine Zeile in der Debian-Liste.
        var andere = cveBefunde().filter(function (b) { return b.bereich !== 'debian'; });
        // Bewertete Funde (pip_audit_ausnahmen.txt) gesondert nennen – sonst
        // sieht eine abgeschlossene Bewertung aus wie ein offener Alarm.
        var bewertet = andere.filter(function (b) { return b.klasse === 'ausgenommen'; }).length;
        var andereBlock = andere.length
            ? '<details class="jv-pkg-cve-andere"><summary>'
              + esc(T('pkg.cve_andere', 'Python- und npm-Pakete: {n} Lücken').replace('{n}', String(andere.length))
                    + (bewertet ? ' ' + T('pkg.cve_andere_bew', '(davon {b} bewertet)').replace('{b}', String(bewertet)) : ''))
              + '</summary><ul class="jv-pkg-cve-liste">' + andere.map(function (b) {
                  return befundZeilen([b]).replace('<li', '<li data-quelle="' + esc(b.bereich + ':' + b.quelle) + '"')
                      .replace('<span class="jv-pkg-cve-id">', '<span class="jv-pkg-cve-id">'
                               + esc(bereichText(b.bereich) + ' ' + b.quelle + ' ' + b.version) + ' – ');
              }).join('') + '</ul></details>'
            : '';
        return '<div class="jv-pkg-cvebar"><div class="jv-pkg-cve-st">' + teile.join(' · ') + '</div>'
            + '<div class="jv-pkg-cve-knoepfe">' + knoepfe + filter + '</div>'
            + (_cveMeldung ? '<div class="jv-pkg-cve-meldung">' + esc(_cveMeldung) + '</div>' : '')
            + andereBlock + '</div>';
    }

    function cvePost(pfad, daten) {
        return fetch(pfad, { method: 'POST',
            headers: { 'Authorization': 'Bearer ' + token(), 'Content-Type': 'application/json' },
            body: JSON.stringify(daten || {}) })
            .then(function (r) {
                return r.json().catch(function () { return {}; })
                    .then(function (d) { return { ok: r.ok, d: d }; });
            });
    }

    /* „Jetzt aktualisieren" je Quellpaket (Detailzeile). Nur, wenn das letzte
     * Ergebnis fuer dieses Quellpaket ein Update fuehrt – dieselbe Auswahl
     * trifft der Server (cve_pruefung.einzeln_pakete) noch einmal selbst. */
    function einzelBefunde(quelle) {
        return cveBefunde().filter(function (b) {
            return b.bereich === 'debian' && b.quelle === quelle && b.klasse === 'behebbar';
        });
    }

    function einzelKnopf(befunde) {
        if (_cve && _cve.laeuft) return '';
        var quellen = {};
        befunde.forEach(function (b) {
            if (b.bereich === 'debian' && b.klasse === 'behebbar') quellen[b.quelle] = true;
        });
        return Object.keys(quellen).map(function (q) {
            return '<button type="button" class="jv-pkg-cve-btn ist-haupt" data-cve-aktion="einzeln"'
                + ' data-cve-quelle="' + esc(q) + '">'
                + esc(T('pkg.cve_einzeln', 'Jetzt aktualisieren') + (Object.keys(quellen).length > 1 ? ' (' + q + ')' : ''))
                + '</button> ';
        }).join('');
    }

    function cveEinzeln(quelle) {
        var bef = einzelBefunde(quelle);
        var pakete = {}, regulaer = false;
        bef.forEach(function (b) {
            (b.beheben_mit || []).forEach(function (n) { pakete[n] = true; });
            if (!b.aus_sicherheitsquelle) regulaer = true;
        });
        var namen = Object.keys(pakete).sort();
        if (!namen.length) return;
        var text = T('pkg.cve_einzeln_frage', '{quelle} jetzt aktualisieren?').replace('{quelle}', quelle)
            + '\n\n' + namen.join(', ')
            + '\n' + T('pkg.cve_kand', 'verfügbar') + ': ' + (bef[0] && bef[0].kandidat || '')
            + '\n' + (regulaer ? T('pkg.cve_q_reg', 'nur in der regulären Quelle')
                                : T('pkg.cve_q_sich', 'aus der Sicherheitsquelle'))
            + '\n\n' + T('pkg.cve_frage_grenzen', 'Es werden keine Pakete entfernt und der Server startet nicht neu.');
        if (!window.confirm(text)) return;
        _cveMeldung = '';
        cvePost('/api/system/cve/einzeln', { quelle: quelle }).then(function (a) {
            if (!a.ok) _cveMeldung = (a.d && (a.d.error || a.d.detail)) || T('pkg.cve_err', 'Die Prüfung konnte nicht gestartet werden.');
            cveLaden();
        }).catch(function () {
            _cveMeldung = T('pkg.err_net', 'Der Server war nicht erreichbar.');
            if (_bericht) zeichnen();
        });
    }

    function cveAktion(art, paket, quelle) {
        if (art === 'einzeln') { cveEinzeln(quelle); return; }
        if (art === 'pruefen' || art === 'beheben') {
            if (art === 'beheben') {
                var plan = (_cve && _cve.plan) || {};
                var text = T('pkg.cve_frage', 'Diese Pakete jetzt aktualisieren?') + '\n\n'
                    + (plan.debian || []).join(', ')
                    + (plan.python ? '\n' + T('pkg.cve_frage_py', 'Dazu Python-Pakete mit bekannter Behebung (der Dienst startet danach neu).') : '')
                    + (plan.index ? '\n' + T('pkg.cve_frage_idx', 'Vorher wird der Paketindex aktualisiert.') : '')
                    + '\n\n' + T('pkg.cve_frage_grenzen', 'Es werden keine Pakete entfernt und der Server startet nicht neu.');
                if (!window.confirm(text)) return;
            }
            _cveMeldung = '';
            cvePost('/api/system/cve/pruefen', { beheben: art === 'beheben' }).then(function (a) {
                if (!a.ok) _cveMeldung = (a.d && a.d.error) || T('pkg.cve_err', 'Die Prüfung konnte nicht gestartet werden.');
                cveLaden();
            }).catch(function () {
                _cveMeldung = T('pkg.err_net', 'Der Server war nicht erreichbar.');
                if (_bericht) zeichnen();
            });
            return;
        }
        var ids = art === 'alle_gesehen' ? null
            : quittierbareIds((cveJePaket()[paket] || { befunde: [] }).befunde);
        cvePost('/api/system/cve/quittieren', ids ? { ids: ids } : { alle: true }).then(function (a) {
            if (!a.ok) _cveMeldung = (a.d && a.d.detail) || T('pkg.cve_err_q', 'Markieren fehlgeschlagen.');
            cveLaden();
        });
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
                _cveBadge = (d && d.cve_badge) || null;
                badgeMalen();
                if (_admin && !_badgeTimer) _badgeTimer = setInterval(badgeHolen, BADGE_MS);
                return _admin;
            })
            // Kein Zustandswechsel bei Netzfehler: ohne belegten Admin-Status
            // entsteht der Knopf gar nicht erst.
            .catch(function () { return false; });
        return _lauf;
    }

    window.JarvisSysPackages = { pruefe: pruefe, oeffnen: oeffnen,
                                 schliessen: schliessen,
                                 klasseText: klasseText, bereichText: bereichText,
                                 // Zahnrad-Badge: direkt auf die betroffenen Pakete
                                 oeffnenLuecken: function () {
                                     if (offen()) schliessen();
                                     oeffnen({ nurLuecken: true });
                                 } };

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
        badgeMalen();
    });
})();
