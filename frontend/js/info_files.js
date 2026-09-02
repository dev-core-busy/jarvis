/* ═══════════════════════════════════════════════════════════════════════════
   Info-Dokumente im Portal (Ordnersymbol oben rechts)
   ───────────────────────────────────────────────────────────────────────────
   Zeigt den Inhalt von `frontend_info_files/` (Backend: backend/info_files.py,
   API: GET /api/info_files). Das Ordnersymbol erscheint NUR, wenn dort Dateien
   liegen – ein Knopf, der ein leeres Fach oeffnet, ist eine Enttaeuschung.

   Jeder Eintrag traegt ein Symbol passend zum Dateityp; die Kategorie kommt vom
   Backend (`kind`), damit Liste und Auslieferung dieselbe Einteilung benutzen
   und ein neuer Dateityp nur an EINER Stelle nachgetragen wird.

   Farben ausschliesslich ueber Theme-Variablen (CSS-Klassen .pt-ico-*), Texte
   ueber i18n – sonst bricht Branding/Hell-Modus oder die EN-Oberflaeche.
   ═══════════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    // Gleiche Reihenfolge wie support.js::TOKEN_KEYS – das Portal kann mit dem
    // Token jeder Oberflaeche geoeffnet worden sein.
    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];

    function token() {
    /* Abruf-Schluessel statt Sitzungstoken in ?token= (frontend/js/dlkey.js). */
    function _dlk() {
        return (window.JarvisDL && window.JarvisDL.schluessel())
            || localStorage.getItem('jarvis_token') || '';
    }

        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            var t = null;
            try { t = localStorage.getItem(TOKEN_KEYS[i]); } catch (e) { t = null; }
            if (t) return t;
        }
        return '';
    }

    function $(id) { return document.getElementById(id); }

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    function T(key, def) {
        var v = (window.t ? window.t(key) : key);
        return (v && v !== key) ? v : def;
    }

    // Groesse menschenlesbar. Bewusst 1024er-Schritte mit KB/MB/GB – so nennt
    // es auch der Datei-Explorer, aus dem der Admin die Dateien kopiert hat.
    function fmtSize(bytes) {
        var b = Number(bytes) || 0;
        if (b < 1024) return b + ' B';
        var u = ['KB', 'MB', 'GB'], i = -1, v = b;
        do { v /= 1024; i++; } while (v >= 1024 && i < u.length - 1);
        return (v < 10 ? v.toFixed(1) : Math.round(v)) + ' ' + u[i];
    }

    // Symbole je Kategorie (24er-Raster, stroke=currentColor wie die uebrigen
    // Portal-Icons). Die Farbe kommt aus der Klasse .pt-ico-<kind>.
    var P = 'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"';
    var SHEET = '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/>';
    var ICONS = {
        pdf:        SHEET + '<path d="M9 13h1.5a1.5 1.5 0 0 1 0 3H9v-3zm0 3v2"/><path d="M14 13v5"/><path d="M14 13h2"/><path d="M14 15.5h1.6"/>',
        word:       SHEET + '<path d="M8 13l1.4 5 1.6-3.5 1.6 3.5L14 13"/>',
        excel:      SHEET + '<path d="M8.5 13l4 5"/><path d="M12.5 13l-4 5"/>',
        powerpoint: SHEET + '<path d="M9 18v-5h2a1.6 1.6 0 0 1 0 3.2H9"/>',
        text:       SHEET + '<line x1="8" y1="13" x2="15" y2="13"/><line x1="8" y1="16" x2="15" y2="16"/><line x1="8" y1="19" x2="12" y2="19"/>',
        code:       SHEET + '<polyline points="10 13 8 16 10 19"/><polyline points="14 13 16 16 14 19"/>',
        image:      '<rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><circle cx="8.5" cy="8.5" r="1.5"/><polyline points="21 15 16 10 5 21"/>',
        archive:    '<path d="M21 8v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8"/><rect x="1" y="3" width="22" height="5" rx="1"/><line x1="10" y1="12" x2="14" y2="12"/>',
        video:      '<polygon points="23 7 16 12 23 17 23 7"/><rect x="1" y="5" width="15" height="14" rx="2" ry="2"/>',
        audio:      '<path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/>',
        // Verknuepfung (.url): Weltkugel – zeigt an, dass hier eine Seite und
        // keine Datei geoeffnet wird.
        link:       '<circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10A15.3 15.3 0 0 1 12 2z"/>',
        file:       SHEET
    };

    function icon(kind) {
        var k = ICONS[kind] ? kind : 'file';
        return '<svg class="pt-ico-' + k + '" viewBox="0 0 24 24" ' + P + '>' + ICONS[k] + '</svg>';
    }

    // Zweite Schranke neben der Pruefung im Backend: nur http/https ins href.
    // Ein `javascript:`-Ziel wuerde beim Klick im Origin des Portals laufen und
    // an das Sitzungstoken kommen – eine abgelegte Verknuepfung darf kein Skript
    // ausfuehren koennen. Doppelt geprueft, weil der Wert aus einer Datei stammt.
    function isWebUrl(u) {
        return typeof u === 'string' && /^https?:\/\/\S+$/i.test(u.trim());
    }

    // Fuer die Meta-Spalte: bei einer Verknuepfung steht dort der Host statt
    // einer Dateigroesse – so sieht man, wohin der Klick fuehrt.
    function hostOf(u) {
        try { return new URL(u).host; } catch (e) { return ''; }
    }

    // PDF/Bild/Text zeigt der Browser im Tab an; alles andere waere dort
    // Zeichenmuell, deshalb dafuer ein echter Download (Server sendet passend
    // dazu Content-Disposition: attachment).
    var INLINE = { pdf: 1, image: 1, text: 1 };

    var Mgr = {
        _files: [],
        _open: false,
        _bound: false,

        init: function () {
            this._bind();
            this.load();
        },

        _bind: function () {
            if (this._bound) return;
            this._bound = true;
            var btn = $('pt-info-btn');
            if (btn) btn.addEventListener('click', function (e) {
                e.stopPropagation();
                Mgr.toggle();
            });
            // Klick daneben und Escape schliessen – ein Panel, das offen bleibt,
            // verdeckt die Kacheln darunter.
            document.addEventListener('click', function (e) {
                var wrap = $('pt-info-wrap');
                if (Mgr._open && wrap && !wrap.contains(e.target)) Mgr.close();
            });
            document.addEventListener('keydown', function (e) {
                if (e.key === 'Escape' && Mgr._open) Mgr.close();
            });
        },

        load: function () {
            var wrap = $('pt-info-wrap');
            if (!wrap) return;
            var tk = token();
            if (!tk) return;                       // nicht angemeldet – nichts zeigen
            fetch('/api/info_files', { headers: { 'Authorization': 'Bearer ' + tk } })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    Mgr._files = (d && Array.isArray(d.files)) ? d.files : [];
                    // Kernanforderung: ohne Dateien kein Ordnersymbol.
                    wrap.style.display = Mgr._files.length ? '' : 'none';
                    if (!Mgr._files.length) Mgr.close();
                    Mgr._render();
                })
                .catch(function () { /* Fehler => Symbol bleibt aus */ });
        },

        _render: function () {
            var list = $('pt-info-list'), cnt = $('pt-info-count');
            if (!list) return;
            if (cnt) cnt.textContent = Mgr._files.length
                ? Mgr._files.length + ' ' + T('portal.info_files_count', 'Dateien')
                : '';
            if (!Mgr._files.length) {
                list.innerHTML = '<div class="pt-info-meta" style="padding:10px;">'
                    + esc(T('portal.info_files_empty', 'Keine Dokumente vorhanden.')) + '</div>';
                return;
            }
            var tk = token();
            list.innerHTML = Mgr._files.map(function (f) {
                // ── Verknuepfung (.url): oeffnet das Ziel, nicht die Datei ──
                if (f.kind === 'link' && isWebUrl(f.url)) {
                    // rel="noreferrer" zusaetzlich zu noopener: die Zieladresse
                    // soll nicht erfahren, aus welcher internen Seite der Klick kam.
                    return '<a class="pt-info-item" href="' + esc(f.url)
                         + '" target="_blank" rel="noopener noreferrer"'
                         + ' title="' + esc(f.url) + '">'
                         + icon('link')
                         + '<span class="pt-info-name">' + esc(f.label || f.name) + '</span>'
                         + '<span class="pt-info-meta">' + esc(hostOf(f.url)) + '</span>'
                         + '</a>';
                }
                // Der Schluessel gehoert NUR ins DOM (wie chatlib.js::_withToken):
                // die Liste wird bei jedem Laden neu gebaut, nichts gespeichert.
                // Seit 2026-09-02 ist das ein Abruf-Schluessel, kein Sitzungstoken.
                var href = '/api/info_files/' + encodeURIComponent(f.name)
                         + (_dlk() ? '?token=' + encodeURIComponent(_dlk()) : '');
                var inline = !!INLINE[f.kind];
                var attrs = inline
                    ? 'target="_blank" rel="noopener"'
                    : 'download="' + esc(f.name) + '"';
                // Eine Verknuepfung, die hier landet, hatte kein brauchbares Ziel
                // (das Backend degradiert sie normalerweise schon). Dann auch das
                // Datei-Symbol zeigen – ein Globus, der eine Datei herunterlaedt,
                // waere eine falsche Ansage.
                return '<a class="pt-info-item" href="' + esc(href) + '" ' + attrs
                     + ' title="' + esc(f.name) + '">'
                     + icon(f.kind === 'link' ? 'file' : f.kind)
                     + '<span class="pt-info-name">' + esc(f.name) + '</span>'
                     + '<span class="pt-info-meta">' + esc(fmtSize(f.size)) + '</span>'
                     + '</a>';
            }).join('');
        },

        toggle: function () { this._open ? this.close() : this.open(); },

        open: function () {
            var p = $('pt-info-panel'), b = $('pt-info-btn');
            if (!p) return;
            p.hidden = false;
            this._open = true;
            if (b) b.setAttribute('aria-expanded', 'true');
            // Beim Oeffnen neu laden: ein Administrator legt Dateien im Betrieb ab,
            // ohne dass der Benutzer die Seite neu laedt.
            this.load();
        },

        close: function () {
            var p = $('pt-info-panel'), b = $('pt-info-btn');
            if (p) p.hidden = true;
            this._open = false;
            if (b) b.setAttribute('aria-expanded', 'false');
        }
    };

    window.JarvisInfoFiles = Mgr;
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { Mgr.init(); });
    } else {
        Mgr.init();
    }
})();
