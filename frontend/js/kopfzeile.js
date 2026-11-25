/* ============================================================
 * kopfzeile.js – EINE Titelleiste fuer alle Bereichsseiten (shared)
 *
 * VORGABE DES BETREIBERS (2026-11-16): "bei jedem Wechsel der Seiten wird die
 * Headerzeile komplett neu aufgebaut. [...] Logo, Branding, LLM Status Pill,
 * Zertifikathinweis, Update-Pill (nur Admin), CPU (nur Admin), 'i' (nur
 * Admin), Logout sollen immer sichtbar sein [Einstellungen muss dazu auch
 * angepasst werden]". NACHTRAG (derselbe Tag): "CPU sollen wie vorher alle
 * sehen, die Systemauslastung duerfen weiterhin nur Admins sehen" – die
 * CPU-Anzeige ist deshalb KEIN Nur-Admin-Element; das Fenster dahinter
 * schuetzt sysload.js selbst (Klick nur fuer Admins, Endpunkt mit Schranke).
 *
 * WARUM DIE LEISTE NICHT WIRKLICH STEHEN BLEIBT: jede Bereichsseite ist ein
 * eigenes HTML-Dokument – ein Seitenwechsel verwirft das alte Dokument samt
 * Leiste. Eine echte Einzelseiten-Anwendung haette alle 21 Seiten umgebaut.
 * Stattdessen wirken drei Dinge zusammen, damit die Leiste STEHEN BLEIBT, wie
 * man sie sieht:
 *   1. dieselben Kernelemente stehen auf jeder Seite an derselben Stelle
 *      (dieses Modul baut fehlende ein und ordnet vorhandene),
 *   2. der zuletzt bekannte Stand (Admin-Rolle, LLM-Zustand, CPU, Version)
 *      liegt in sessionStorage und wird SOFORT gezeichnet – vorher erschienen
 *      Update-Pille, CPU und ⓘ erst nach der Antwort von /api/me, und genau
 *      dieses Nachschieben sah wie ein Neuaufbau aus,
 *   3. der Browser blendet zwischen den Dokumenten ueber (View Transitions,
 *      Regeln in theme.css) und haelt die Leiste dabei fest.
 *
 * REIHENFOLGE LINKS (auf jeder Seite gleich, hinter Logo und Titel):
 *     LLM-Punkt · Schild · Update-Pille · CPU · ⓘ
 * Seitenspezifische Anzeigen (SAP-Verbindung, Konto-Pille …) folgen dahinter.
 * Abmelden steht als letztes Symbol rechts.
 *
 * NUR-ADMIN-ELEMENTE tragen `jv-kopf-nuradmin`; sichtbar sind sie nur, wenn
 * `<html>` die Klasse `jv-kopf-admin` traegt (Regel in theme.css). Die Klasse
 * setzt dieses Modul – sofort aus dem gemerkten Stand, danach belegt aus
 * /api/me. ⚠ SICHTBARKEIT IST KEINE BERECHTIGUNG: die Endpunkte pruefen selbst.
 *
 * Der gemerkte Stand gehoert zu GENAU EINER Anmeldung: er traegt eine
 * Pruefsumme des Tokens. Meldet sich in demselben Tab jemand anderes an, passt
 * die Summe nicht mehr und der Stand wird verworfen – sonst saehe ein
 * Nicht-Admin bis zur Antwort von /api/me die Admin-Symbole.
 *
 * ⚠ LAEDT DIREKT HINTER sitzung.js (harte Abhaengigkeit, siehe dort) und VOR
 * cpubar.js / syspackages.js / update_widget.js: die bauen ihre Elemente nur,
 * wenn sie fehlen, und uebernehmen sonst die von hier.
 *
 * API:
 *   JarvisKopf.adminBelegt()  – true/false aus /api/me, null = noch offen
 *   JarvisKopf.istAdmin()     – belegter ODER gemerkter Admin-Stand
 *   JarvisKopf.merke(k, v)    – Wert fuer den naechsten Seitenaufbau merken
 *   JarvisKopf.gemerkt(k)     – gemerkten Wert lesen (undefined = keiner)
 * ============================================================ */
(function () {
    'use strict';

    if (window.JarvisKopf) return;   // doppeltes Laden vermeiden

    var S = window.JarvisSitzung;
    var SPEICHER = 'jarvis_kopf';
    var LLM_TAKT_MS = 30000;

    // Bauformen der Titelleiste, in dieser Reihenfolge gesucht. /settings hat
    // keine eigene Leiste – dort ist der Kopf des Einstellungsfensters die
    // Leiste (das Fenster IST die Seite).
    var WIRTE = ['header.topbar', '.pt-topbar', '.wi-topbar', '.ad-top', '.sa-topbar',
                 '#settings-modal .modal-header'];
    var LINKS = '.topbar-left';
    var RECHTS = '.topbar-right, .pt-top-icons, .wi-top-icons, .ad-top-icons, .sa-top-icons, .modal-head-actions';
    var TITEL = '.topbar-title, .pt-title, .wi-title, .ad-title, .sa-title, .jv-kopf-marke';
    // Die LLM-Punkte, die Seiten selbst mitbringen und selbst abfragen.
    var LLM_PUNKTE = '#status-dot, #pt-status-dot, #sup-status-dot, #sp-status-dot, #vm-status-dot, #wi-status-dot';

    function T(key, fallback) {
        try { if (window.t) { var v = window.t(key); if (v && v !== key) return v; } } catch (e) {}
        return fallback;
    }

    /* ── Gemerkter Stand ─────────────────────────────────────────────── */

    // Pruefsumme statt Token: der Token selbst gehoert nicht in einen zweiten
    // Speicher. Es geht nur um "dieselbe Anmeldung wie beim Merken?".
    function summe(s) {
        var h = 5381;
        for (var i = 0; i < s.length; i++) h = ((h << 5) + h + s.charCodeAt(i)) | 0;
        return String(h >>> 0);
    }

    var _schluessel = '';
    var _stand = {};

    function laden() {
        var tok = S.token();
        _schluessel = tok ? summe(tok) : '';
        _stand = {};
        if (!_schluessel) return;
        try {
            var roh = sessionStorage.getItem(SPEICHER);
            var s = roh ? JSON.parse(roh) : null;
            if (s && s.k === _schluessel) _stand = s;
        } catch (e) { /* Speicher gesperrt oder kaputt: ohne Merker weiter */ }
    }

    function sichern() {
        if (!_schluessel) return;
        _stand.k = _schluessel;
        try { sessionStorage.setItem(SPEICHER, JSON.stringify(_stand)); } catch (e) { /* egal */ }
    }

    function merke(k, v) {
        if (!_schluessel) return;
        _stand[k] = v;
        sichern();
    }

    function gemerkt(k) { return _stand[k]; }

    /* ── Admin-Rolle ─────────────────────────────────────────────────── */

    var _adminBelegt = null;   // null = /api/me hat noch nicht geantwortet

    function adminKlasse(an) {
        try { document.documentElement.classList.toggle('jv-kopf-admin', !!an); } catch (e) {}
    }

    function istAdmin() {
        if (_adminBelegt !== null) return _adminBelegt;
        return _stand.admin === true;
    }

    function updateStarten() {
        if (istAdmin() && window.JarvisUpdateWidget) window.JarvisUpdateWidget.init();
        // Angemeldete Benutzer: init() blendet den Knopf ein und startet die
        // Abfrage – idempotent, das Portal ruft es zusaetzlich selbst.
        if (istAdmin() && window.UserSessions) window.UserSessions.init();
    }

    function meHolen() {
        if (!S.token() || typeof fetch !== 'function') return;
        fetch('/api/me', { headers: S.kopfsatz() })
            .then(function (r) {
                if (r.status === 401 || r.status === 403) return { is_admin: false };
                return r.ok ? r.json() : null;
            })
            .then(function (d) {
                if (!d) return;            // technischer Fehler: gemerkten Stand behalten
                if (d.username) { merke('benutzer', String(d.username)); benutzerZeigen(); }
                _adminBelegt = !!d.is_admin;
                merke('admin', _adminBelegt);
                adminKlasse(_adminBelegt);
                updateStarten();
            })
            .catch(function () { /* Netzfehler: gemerkten Stand behalten */ });
    }

    /* ── „Angemeldet als …“ ────────────────────────────────────────────
     * Die Box auf /sap, /vemas, /jira-addon und /confluence-addon (Vorbild
     * /wissen, Vorgabe 2026-11-16) traegt `[data-kopf-benutzer]`. Der Name
     * kommt aus /api/me (sofort aus dem Merker bzw. dem bei der Anmeldung
     * abgelegten Namen, danach belegt). textContent, kein innerHTML: der Name
     * stammt aus dem Verzeichnis und ist fremder Text. */
    function benutzerZeigen() {
        var n = gemerkt('benutzer') || (S.token() ? S.benutzer() : '');
        if (!n) return;
        var els = document.querySelectorAll('[data-kopf-benutzer]');
        for (var i = 0; i < els.length; i++) {
            if (els[i].textContent !== n) els[i].textContent = n;
        }
    }

    /* ── Bausteine ───────────────────────────────────────────────────── */

    function el(tag, attrs, html) {
        var e = document.createElement(tag);
        for (var k in attrs) {
            if (Object.prototype.hasOwnProperty.call(attrs, k)) e.setAttribute(k, attrs[k]);
        }
        if (html) e.innerHTML = html;
        return e;
    }

    function nachDem(anker, neu) {
        if (!anker || !anker.parentNode) return neu;
        if (anker.nextSibling !== neu) anker.parentNode.insertBefore(neu, anker.nextSibling);
        return neu;
    }

    var LLM_KLASSEN = ['connected', 'disconnected'];

    function llmZeigen(punkt, z) {
        if (!z) return;
        LLM_KLASSEN.forEach(function (c) { punkt.classList.toggle(c, z.c === c); });
        if (z.t) punkt.title = z.t;
    }

    // Vorhandener Punkt der Seite: gemerkten Zustand vorzeichnen, solange die
    // Seite selbst noch nichts gesetzt hat, und jeden Wechsel mitschreiben.
    function llmUebernehmen(punkt) {
        if (!LLM_KLASSEN.some(function (c) { return punkt.classList.contains(c); })) {
            llmZeigen(punkt, gemerkt('llm'));
        }
        if (typeof MutationObserver !== 'function') return;
        new MutationObserver(function () {
            var c = punkt.classList.contains('connected') ? 'connected'
                  : punkt.classList.contains('disconnected') ? 'disconnected' : '';
            if (c) merke('llm', { c: c, t: punkt.title || '' });
        }).observe(punkt, { attributes: true, attributeFilter: ['class', 'title'] });
    }

    // Eigener Punkt (Seiten ohne LLM-Anzeige): selbst abfragen.
    var _llmTimer = null;
    function llmAbfragen(punkt) {
        if (!S.token()) return;
        fetch('/api/llm/active-status', { headers: S.kopfsatz() })
            .then(function (r) {
                if (r.status === 401 || r.status === 403) {
                    if (_llmTimer) { clearInterval(_llmTimer); _llmTimer = null; }
                    return null;
                }
                return r.ok ? r.json() : null;
            })
            .then(function (d) {
                if (!d) return;
                var ok = (d.status === 'ok' || d.status === 'degraded');
                var text = (d.status === 'ok' ? T('sup.llm_ok', 'LLM erreichbar')
                          : d.status === 'degraded' ? T('sup.llm_degraded', 'LLM eingeschränkt')
                          : T('sup.llm_down', 'LLM nicht erreichbar'))
                          + (d.profile_name ? ' – ' + d.profile_name : '');
                var z = { c: ok ? 'connected' : 'disconnected', t: text };
                llmZeigen(punkt, z);
                merke('llm', z);
            })
            .catch(function () {
                var z = { c: 'disconnected', t: T('sup.llm_down', 'LLM nicht erreichbar') };
                llmZeigen(punkt, z);
            });
    }

    function llmPunkt(wirt, anker) {
        var p = wirt.querySelector(LLM_PUNKTE);
        if (p) {
            llmUebernehmen(p);
        } else {
            p = el('span', { 'class': 'jv-kopf-llm', id: 'jv-kopf-llm', title: 'LLM-Status',
                             'data-i18n-title': 'portal.llm_status' });
            llmZeigen(p, gemerkt('llm'));
            if (S.token()) {
                var punkt = p;
                setTimeout(function () { llmAbfragen(punkt); }, 0);
                _llmTimer = setInterval(function () { llmAbfragen(punkt); }, LLM_TAKT_MS);
            }
        }
        p.setAttribute('data-kopf', 'llm');
        // Der Punkt der Seite bleibt, wo die Seite ihn hingestellt hat, wenn er
        // schon in der Reihe steht – sonst rueckt er hinter den Titel.
        return nachDem(anker, p);
    }

    /* Schild: gruen = verschluesselt, rot = unverschluesselt. /portal bringt es
     * mit (samt Zertifikat-Dialog). Wo die Seite einen eigenen Dialog hat
     * (/chat), oeffnet der Klick ihn; sonst fuehrt er zum Dialog im Portal. */
    function schild(wirt, anker) {
        var s = wirt.querySelector('#security-indicator, #jv-kopf-schild');
        if (!s) {
            s = el('div', { id: 'jv-kopf-schild', 'class': 'security-badge', role: 'button',
                            tabindex: '0', 'data-i18n-title': 'security.status', title: 'Sicherheitsstatus' },
                   '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" aria-hidden="true">'
                   + '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>');
            var sicher = location.protocol === 'https:'
                || location.hostname === 'localhost' || location.hostname === '127.0.0.1';
            if (sicher) s.classList.add('secure');
            s.setAttribute('data-i18n-title', sicher ? 'panel.security_secure' : 'panel.security_critical');
            s.title = sicher ? T('panel.security_secure', 'Gesichert')
                             : T('panel.security_critical', 'Kritisch: Keine Verschlüsselung');
            var oeffnen = function () {
                var dlg = document.querySelector('#cert-modal.modal-overlay');
                if (dlg) { dlg.classList.remove('hidden'); return; }
                // In einem fremden Rahmen (Jira/Confluence) nicht den Rahmen
                // selbst umleiten – der Dialog gehoert in ein eigenes Fenster.
                var ziel = '/portal?zertifikat=1';
                if (window.top !== window.self) window.open(ziel, '_blank', 'noopener');
                else location.href = ziel;
            };
            s.addEventListener('click', oeffnen);
            s.addEventListener('keydown', function (ev) {
                if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); oeffnen(); }
            });
        }
        return nachDem(anker, s);
    }

    function nurAdmin(e) {
        e.classList.add('jv-kopf-nuradmin');
        // Ein Inline-`display:none` aus dem Markup (portal.html) wuerde die
        // Klassenregel ueberstimmen – die Sichtbarkeit entscheidet jetzt sie.
        if (e.style.display === 'none') e.style.display = '';
        return e;
    }

    function updatePille(wirt, anker) {
        var w = document.getElementById('chat-update-wrap');
        if (!w || !wirt.contains(w)) {
            w = el('div', { 'class': 'update-widget-wrap', id: 'chat-update-wrap' },
                '<div id="version-pill" class="header-version-pill upd-pill-clickable" title="Updates &amp; Version">'
                + '<span id="update-version" class="upd-pill-ver">v?</span>'
                + '<span id="update-badge" class="update-badge" style="display:none;">●</span></div>'
                + '<div id="update-dropdown" class="update-dropdown hidden">'
                + '<div class="update-dropdown-header"><span><span class="brand-app-name">Jarvis</span> Updates</span>'
                + '<button id="upd-close" class="update-close-btn" data-i18n-title="common.close" title="Schließen">✕</button></div>'
                + '<div id="upd-body" class="update-dropdown-body"><p class="kb-hint" style="margin:0;">…</p></div></div>');
        }
        // Gemerkte Version sofort zeigen; update_widget.js setzt Farbe und
        // Badge aus seinem eigenen Merker.
        var v = gemerkt('version');
        var ve = w.querySelector('#update-version');
        if (v && ve && ve.textContent === 'v?') ve.textContent = 'v' + v;
        return nachDem(anker, nurAdmin(w));
    }

    function cpuBalken(wirt, anker) {
        var b = document.getElementById('cpu-bar');
        if (!b || !wirt.contains(b)) {
            b = el('div', { id: 'cpu-bar', 'class': 'jv-cpu-bar', title: 'CPU-Auslastung',
                            'data-i18n-title': 'wissen.cpu_load' },
                '<div class="cpu-bar-fill" id="cpu-bar-fill" style="width:0%"></div>'
                + '<span class="cpu-bar-label" id="cpu-bar-label">CPU: 0%</span>');
            b.style.display = 'none';
        }
        var p = gemerkt('cpu');
        if (typeof p === 'number' && S.token()) {
            var f = b.querySelector('.cpu-bar-fill'), l = b.querySelector('.cpu-bar-label');
            if (f) { f.style.width = p + '%'; f.style.backgroundPosition = p + '% 0'; }
            if (l) l.textContent = 'CPU: ' + Math.round(p) + '%';
            b.style.display = '';
        }
        // Fuer ALLE Angemeldeten sichtbar (Nachtrag 2026-11-16) – nur das
        // Systemauslastungs-Fenster hinter dem Klick ist Admins vorbehalten.
        return nachDem(anker, b);
    }

    function paketKnopf(wirt, anker) {
        var b = document.getElementById('jv-pkg-btn');
        if (!b || !wirt.contains(b)) {
            // Dasselbe Markup wie syspackages.js::aufbauen() – das Modul
            // uebernimmt den Knopf und verdrahtet ihn.
            b = el('button', { type: 'button', id: 'jv-pkg-btn', 'class': 'jv-pkg-btn',
                               'data-i18n-title': 'pkg.btn', 'data-i18n-aria': 'pkg.btn',
                               title: 'Installierte Pakete', 'aria-label': 'Installierte Pakete' },
                '<svg viewBox="0 0 24 24" width="18" height="18" fill="none"'
                + ' stroke="currentColor" stroke-width="2" stroke-linecap="round"'
                + ' stroke-linejoin="round" aria-hidden="true">'
                + '<circle cx="12" cy="12" r="10"/>'
                + '<line x1="12" y1="16" x2="12" y2="11"/>'
                + '<line x1="12" y1="8" x2="12.01" y2="8"/></svg>');
        }
        if (!S.token()) b.style.display = 'none';
        return nachDem(anker, nurAdmin(b));
    }

    /* Abmelden: fast jede Seite bringt den Knopf samt eigener Abmeldung mit.
     * Nur wo er fehlt (/settings, /supportagent), kommt dieser dazu. */
    function abmelden(wirt) {
        if (wirt.querySelector('[id*="logout"], .btn-logout')) return;
        var gruppe = wirt.querySelector(RECHTS);
        if (!gruppe) return;
        var vorlage = gruppe.querySelector('[data-i18n-title="nav.home"]');
        var b = el('button', { type: 'button', id: 'jv-kopf-logout',
                               'class': (vorlage && vorlage.className) || 'btn-theme',
                               'data-i18n-title': 'chat.logout', 'data-i18n-aria': 'chat.logout',
                               title: 'Abmelden', 'aria-label': 'Abmelden' },
            '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"'
            + ' stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'
            + '<path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/>'
            + '<line x1="21" y1="12" x2="9" y2="12"/></svg>');
        if (!S.token()) b.style.display = 'none';
        b.addEventListener('click', function () {
            // Erst dem Server sagen, DANN das Token verwerfen (wie /portal).
            var p = window.JarvisSession ? window.JarvisSession.logout() : Promise.resolve();
            try {
                S.tokenSchluessel().concat(S.benutzerSchluessel())
                    .forEach(function (k) { localStorage.removeItem(k); });
                sessionStorage.removeItem(SPEICHER);
            } catch (e) { /* Speicher gesperrt */ }
            p.catch(function () {}).then(function () { location.replace('/'); });
        });
        gruppe.appendChild(b);
    }

    /* ── Rechte Gruppe (Vorgabe 2026-11-16) ──────────────────────────────
     * „unter Einstellungen fehlt DE/EN, Desktop, angemeldete Benutzer, Issues,
     * Hell/Dunkel“ und „Dokumente fehlt bei fast allen Unterseiten“. Ergaenzt
     * wird nur, was fehlt, in der Reihenfolge des Portals:
     *   DE/EN · … · Desktop · Benutzer · Dokumente · Issues · (Avatar) ·
     *   Hell/Dunkel · Startseite · Einstellungen · Abmelden
     * Die Knoepfe uebernehmen die Klasse des Haus-Symbols der Seite – so
     * passen sie ohne Extrawurst zum Stil jeder Leiste (wie avatar.js). Die
     * SVGs tragen width/height="18": /settings begrenzt sie nicht per CSS
     * (dort fuellten sie den Knopf), die Bereichsseiten setzen 20px darueber.
     * Desktop und Benutzer sind Nur-Admin-Elemente; Dokumente blendet
     * info_files.js ein (nur wenn es Dateien gibt oder fuer Admins). */
    var SVG = {
        mond: '<svg class="theme-icon-moon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>',
        sonne: '<svg class="theme-icon-sun" style="display:none;" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>',
        issues: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>',
        ordner: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/></svg>',
        leute: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
        monitor: '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>'
    };

    function knopf(klasse, attrs, html) {
        var a = { type: 'button', 'class': klasse };
        for (var k in attrs) { if (Object.prototype.hasOwnProperty.call(attrs, k)) a[k] = attrs[k]; }
        return el('button', a, html);
    }

    // Zum Portal mit einem Auftrag (Dialog, der nur dort lebt). In einem
    // fremden Rahmen (Jira/Confluence) nicht den Rahmen umleiten.
    function zumPortal(auftrag) {
        var ziel = '/portal?' + auftrag + '=1';
        if (window.top !== window.self) window.open(ziel, '_blank', 'noopener');
        else location.href = ziel;
    }

    function rechteGruppe(wirt) {
        var g = wirt.querySelector(RECHTS);
        if (!g) return;
        var haus = g.querySelector('[data-i18n-title="nav.home"]');
        var kl = (haus && haus.className) || 'btn-theme';
        var vorHaus = function (e) {
            var nach = haus && haus.parentNode === g ? haus : null;
            if (!nach) nach = g.querySelector('[id*="settings"], [id*="logout"], .btn-logout');
            if (nach && nach.parentNode === g) g.insertBefore(e, nach); else g.appendChild(e);
        };

        // DE/EN/FR: erstes Element der Gruppe (auf /settings hinter dem Suchfeld).
        if (!wirt.querySelector('.lang-toggle')) {
            var lt = el('div', { 'class': 'lang-toggle', id: 'jv-kopf-lang' },
                '<button class="lang-toggle-btn" data-lang="de" data-setlang="de" title="Deutsch">DE</button>'
                + '<button class="lang-toggle-btn" data-lang="en" data-setlang="en" title="English">EN</button>'
                + '<button class="lang-toggle-btn" data-lang="fr" data-setlang="fr" title="Français">FR</button>'
                + '<button class="lang-toggle-btn" data-lang="nl" data-setlang="nl" title="Nederlands">NL</button>');
            var such = g.querySelector('.st-such-wrap');
            if (such) nachDem(such, lt); else g.insertBefore(lt, g.firstChild);
            var lang = window._lang || (function () { try { return localStorage.getItem('jarvis_lang'); } catch (e) { return ''; } })() || 'de';
            Array.prototype.forEach.call(lt.children, function (b) { b.classList.toggle('active', b.getAttribute('data-lang') === lang); });
        }
        // Hell/Dunkel (theme.js bindet #btn-theme-toggle/.btn-theme-toggle).
        var thema = wirt.querySelector('#btn-theme-toggle, .btn-theme-toggle, #btn-theme');
        if (!thema) {
            thema = knopf(kl + ' btn-theme-toggle', { id: 'jv-kopf-thema', 'data-i18n-title': 'chat.theme',
                'data-i18n-aria': 'chat.theme', title: 'Hell/Dunkel umschalten', 'aria-label': 'Hell/Dunkel umschalten' },
                SVG.mond + SVG.sonne);
            vorHaus(thema);
        }
        // Issues (issues.js oeffnet per Delegation ueber data-issues-oeffnen).
        var iss = wirt.querySelector('.jv-issues-btn');
        if (!iss) {
            iss = knopf(kl + ' jv-issues-btn', { id: 'jv-kopf-issues', 'data-issues-oeffnen': '',
                'data-i18n-title': 'sup.issues', 'data-i18n-aria': 'sup.issues',
                title: 'Issues / Feedback', 'aria-label': 'Issues / Feedback' }, SVG.issues);
            if (thema.parentNode === g) g.insertBefore(iss, thema); else vorHaus(iss);
        }
        var vorIssues = function (e) {
            if (iss.parentNode === g) g.insertBefore(e, iss); else vorHaus(e);
        };
        // Dokumente (info_files.js) – Markup wie im Portal.
        if (!document.getElementById('pt-info-wrap')) {
            var doku = el('div', { 'class': 'pt-info-wrap', id: 'pt-info-wrap' },
                '<button class="' + kl + '" id="pt-info-btn" type="button" title="Dokumente" data-i18n-title="portal.info_files" aria-haspopup="true" aria-expanded="false">' + SVG.ordner + '</button>'
                + '<div class="pt-info-panel" id="pt-info-panel" hidden>'
                + '<div class="pt-info-head"><span data-i18n="portal.info_files">Dokumente</span><span class="pt-info-count" id="pt-info-count"></span></div>'
                + '<div class="pt-info-list" id="pt-info-list"></div>'
                + '<div class="pt-info-admin" id="pt-info-admin" hidden><input type="file" id="pt-info-input" multiple hidden>'
                + '<div class="pt-info-admin-row"><button type="button" class="pt-info-upload" id="pt-info-upload" data-i18n="portal.info_upload">Hochladen</button>'
                + '<span class="pt-info-hint" data-i18n="portal.info_admin_hint">Sichtbar für alle angemeldeten Benutzer</span></div>'
                + '<div class="pt-info-status" id="pt-info-status" role="status" aria-live="polite"></div></div>'
                + '</div>');
            // Gemerkt sichtbar -> sofort da (info_files.js entscheidet danach).
            doku.style.display = (gemerkt('dokumente') === true && S.token()) ? '' : 'none';
            vorIssues(doku);
        }
        // Angemeldete Benutzer (sessions.js, nur Admin).
        if (!document.getElementById('pt-usr-wrap')) {
            var usr = el('div', { 'class': 'pt-usr-wrap jv-kopf-nuradmin', id: 'pt-usr-wrap' },
                '<button class="' + kl + '" id="pt-usr-btn" type="button" title="Angemeldete Benutzer" data-i18n-title="sessions.title" aria-haspopup="true" aria-expanded="false">' + SVG.leute + '</button>'
                + '<div class="pt-usr-panel" id="pt-usr-panel" hidden>'
                + '<div class="pt-usr-head"><span data-i18n="sessions.title">Angemeldete Benutzer</span><span class="pt-usr-count" id="pt-usr-count"></span></div>'
                + '<div class="pt-usr-filter" id="pt-usr-filter"><input data-tabfill-nein="Suchfeld – der Platzhalter beschreibt, wonach gesucht wird" type="search" id="pt-usr-search" autocomplete="off" spellcheck="false" placeholder="Benutzer filtern…" data-i18n-placeholder="sessions.search_ph" aria-label="Benutzerliste filtern" data-i18n-aria="sessions.search_aria"></div>'
                + '<div class="pt-usr-list" id="pt-usr-list"></div><div class="pt-usr-hint" id="pt-usr-hint"></div>'
                + '</div>');
            var doc = document.getElementById('pt-info-wrap');
            if (doc && doc.parentNode === g) g.insertBefore(usr, doc); else vorIssues(usr);
        }
        // Desktop (VNC, nur Admin): der Desktop lebt im Portal – von dort
        // geoeffnet (`?desktop=1`), statt noVNC auf jeder Seite mitzuladen.
        if (!document.getElementById('pt-vnc-btn') && !document.getElementById('jv-kopf-desktop')) {
            var vnc = knopf(kl + ' jv-kopf-nuradmin', { id: 'jv-kopf-desktop', 'data-i18n-title': 'chat.desktop',
                'data-i18n-aria': 'chat.desktop', title: 'Desktop (VNC)', 'aria-label': 'Desktop (VNC)' }, SVG.monitor);
            vnc.addEventListener('click', function () { zumPortal('desktop'); });
            var u = document.getElementById('pt-usr-wrap');
            if (u && u.parentNode === g) g.insertBefore(vnc, u); else vorIssues(vnc);
        }
    }

    /* /settings: der Fensterkopf traegt Titel + Symbolgruppe (space-between).
     * Logo, Marke und Titel kommen in EINE linke Gruppe – ein drittes direktes
     * Kind wuerde die Verteilung zerreissen (Lehre aus style.css). */
    function einstellungsKopf(wirt) {
        var links = wirt.querySelector('.jv-kopf-links');
        if (links) return links;
        var titel = wirt.querySelector('#settings-title');
        links = el('div', { 'class': 'jv-kopf-links topbar-left' });
        wirt.insertBefore(links, wirt.firstChild);
        links.appendChild(el('div', { 'class': 'topbar-avatar' }, 'J'));
        links.appendChild(el('span', { 'class': 'jv-kopf-marke brand-app-name' }, 'Jarvis'));
        if (titel) links.appendChild(titel);
        return links;
    }

    var _gebaut = false;

    function aufbauen() {
        if (_gebaut) return true;
        var wirt = null;
        for (var i = 0; i < WIRTE.length && !wirt; i++) wirt = document.querySelector(WIRTE[i]);
        if (!wirt) return false;
        _gebaut = true;
        wirt.classList.add('jv-kopfzeile');

        var links = wirt.matches('#settings-modal .modal-header')
            ? einstellungsKopf(wirt)
            : (wirt.querySelector(LINKS) || wirt);
        var anker = links.querySelector(TITEL)
            || links.querySelector('.topbar-avatar, .sa-logo')
            || null;
        if (!anker) {
            // Ohne Titel und Logo keine Reihe, an die man anhaengen koennte.
            anker = el('span', { 'class': 'jv-kopf-anker' });
            links.insertBefore(anker, links.firstChild);
        }
        // Die Titelgruppe auf /settings steht in `links`; der Titel selbst
        // ist dort das h2 – an das wird angehaengt.
        var h2 = links.querySelector('#settings-title');
        if (h2) anker = h2;

        anker = llmPunkt(wirt, anker);
        anker = schild(wirt, anker);
        anker = updatePille(wirt, anker);
        anker = cpuBalken(wirt, anker);
        paketKnopf(wirt, anker);
        rechteGruppe(wirt);
        abmelden(wirt);
        return true;
    }

    /* ── Start ───────────────────────────────────────────────────────── */

    laden();
    adminKlasse(istAdmin());

    window.JarvisKopf = {
        adminBelegt: function () { return _adminBelegt; },
        istAdmin: istAdmin,
        merke: merke,
        gemerkt: gemerkt,
        aufbauen: aufbauen
    };

    // Auf fast allen Seiten steht die Leiste VOR diesem Skript im Markup und
    // wird sofort ergaenzt. /settings laedt sitzung.js ganz oben – dort erst,
    // wenn das Dokument steht.
    if (!aufbauen() && document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', aufbauen);
    }
    // update_widget.js laedt nach diesem Modul – gestartet wird es, sobald
    // das Dokument steht (gemerkter Admin) bzw. /api/me es belegt.
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', updateStarten);
        // Die Box steht im Seiteninhalt, also HINTER der Leiste im Markup –
        // gesetzt wird der Name deshalb erst, wenn das Dokument steht (EINE
        // Stelle; ein zweiter Aufruf in aufbauen() machte sie unpruefbar).
        document.addEventListener('DOMContentLoaded', benutzerZeigen);
    } else {
        setTimeout(updateStarten, 0);
        benutzerZeigen();
    }
    meHolen();
})();
