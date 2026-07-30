/* Jarvis – Anwesenheit: Abmelde-Signal + Admin-Übersicht „Angemeldete Benutzer".
 *
 * Zwei Dinge in einer Datei, weil sie dieselbe Datenquelle betreffen:
 *
 *   window.JarvisSession.logout(token)  – meldet die Abmeldung am Server, BEVOR
 *       die Seite das Token verwirft. Ohne dieses Signal kann der Server
 *       „abgemeldet" nicht von „still geworden" unterscheiden (Tokens sind
 *       zustandslos, es gibt keine Sitzungstabelle).
 *
 *   window.UserSessions.init()          – das Panel hinter dem Personen-Symbol
 *       im Portal (nur Administratoren). Grüne Pille = online, graue = offline.
 */
(function () {
    'use strict';

    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];

    function anyToken() {
        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            try {
                var v = localStorage.getItem(TOKEN_KEYS[i]);
                if (v) return v;
            } catch (e) { /* localStorage gesperrt */ }
        }
        return '';
    }

    function t(k, d) { return (window.t && window.t(k)) || d; }

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }

    // ── Abmelde-Signal ──────────────────────────────────────────────────────
    // `keepalive` ist hier der Kern: die Seite navigiert unmittelbar danach weg
    // bzw. verwirft das Token. Ohne keepalive bricht der Browser die Anfrage ab
    // und die Abmeldung käme nie an. sendBeacon scheidet aus – es kann keinen
    // Authorization-Header setzen.
    function logout(token) {
        var tok = token || anyToken();
        if (!tok) return Promise.resolve(false);
        try {
            return fetch('/api/logout', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + tok },
                keepalive: true,
            }).then(function () { return true; }).catch(function () { return false; });
        } catch (e) {
            return Promise.resolve(false);
        }
    }

    window.JarvisSession = { logout: logout, tokenKeys: TOKEN_KEYS };

    // ── Admin-Übersicht ─────────────────────────────────────────────────────
    var POLL_MS = 30000;
    var els = {};
    var _timer = null;
    var _bound = false;

    function fmt(ts) {
        if (!ts) return '–';
        var d = new Date(ts * 1000);
        var heute = new Date();
        var gleich = d.toDateString() === heute.toDateString();
        var uhr = d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
        if (gleich) return t('sessions.today', 'heute') + ' ' + uhr;
        return d.toLocaleDateString(undefined, { day: '2-digit', month: '2-digit' }) + ' ' + uhr;
    }

    function relativ(ts) {
        if (!ts) return '';
        var s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
        if (s < 60) return t('sessions.just_now', 'gerade eben');
        if (s < 3600) return Math.floor(s / 60) + ' ' + t('sessions.min_ago', 'Min.');
        if (s < 86400) return Math.floor(s / 3600) + ' ' + t('sessions.h_ago', 'Std.');
        return Math.floor(s / 86400) + ' ' + t('sessions.d_ago', 'Tg.');
    }

    function zeile(u) {
        // Die Pille trägt die Aussage doppelt: Farbe UND Text. Farbe allein wäre
        // für Farbfehlsichtige keine Information.
        var pill = '<span class="pt-usr-pill ' + (u.online ? 'is-on' : 'is-off') + '">'
            + (u.online ? t('sessions.online', 'online') : t('sessions.offline', 'offline'))
            + '</span>';
        var api = u.kind === 'api'
            ? ' <span class="pt-usr-tag">API</span>' : '';
        var zeilen = [];
        zeilen.push('<span class="pt-usr-kv">' + t('sessions.last_login', 'Anmeldung')
            + ': <b>' + esc(fmt(u.last_login)) + '</b></span>');
        zeilen.push('<span class="pt-usr-kv">' + t('sessions.last_logout', 'Abmeldung')
            + ': <b>' + esc(u.last_logout ? fmt(u.last_logout) : t('sessions.never', 'nie')) + '</b></span>');
        if (u.online) {
            zeilen.push('<span class="pt-usr-kv">' + t('sessions.active', 'aktiv')
                + ': <b>' + esc(relativ(u.last_seen)) + '</b></span>');
        }
        return '<div class="pt-usr-item">'
            + '<div class="pt-usr-top">' + pill
            + '<span class="pt-usr-name" title="' + esc(u.username) + '">' + esc(u.display) + '</span>'
            + api + '</div>'
            + '<div class="pt-usr-meta">' + zeilen.join('<span class="pt-usr-sep">·</span>') + '</div>'
            + '</div>';
    }

    function render(d) {
        if (!els.list) return;
        var users = (d && d.users) || [];
        if (!users.length) {
            els.list.innerHTML = '<div class="pt-usr-empty">'
                + esc(t('sessions.empty', 'Noch keine Anmeldungen aufgezeichnet.')) + '</div>';
        } else {
            els.list.innerHTML = users.map(zeile).join('');
        }
        if (els.count) {
            els.count.textContent = (d && d.online != null)
                ? d.online + '/' + d.total : '';
        }
        if (els.hint && d && d.online_window) {
            els.hint.textContent = t('sessions.hint', 'Online = Aktivität in den letzten {n} Sekunden. Wer den Browser schließt, ohne sich abzumelden, erscheint bis dahin weiter als online.')
                .replace('{n}', d.online_window);
        }
    }

    function load() {
        // Kein Abruf für ein geschlossenes Panel – der Poll läuft nur, solange
        // es offen ist (siehe toggle()).
        var tok = anyToken();
        if (!tok || !els.list) return;
        fetch('/api/sessions', { headers: { 'Authorization': 'Bearer ' + tok } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) { if (d && d.ok) render(d); })
            .catch(function () { });
    }

    function offen() { return els.panel && !els.panel.hasAttribute('hidden'); }

    function schliessen() {
        if (els.panel) els.panel.setAttribute('hidden', '');
        if (els.btn) els.btn.setAttribute('aria-expanded', 'false');
        if (_timer) { clearInterval(_timer); _timer = null; }
    }

    function oeffnen() {
        if (els.panel) els.panel.removeAttribute('hidden');
        if (els.btn) els.btn.setAttribute('aria-expanded', 'true');
        load();
        if (!_timer) _timer = setInterval(load, POLL_MS);
    }

    function toggle() { if (offen()) schliessen(); else oeffnen(); }

    function init() {
        els.wrap = document.getElementById('pt-usr-wrap');
        els.btn = document.getElementById('pt-usr-btn');
        els.panel = document.getElementById('pt-usr-panel');
        els.list = document.getElementById('pt-usr-list');
        els.count = document.getElementById('pt-usr-count');
        els.hint = document.getElementById('pt-usr-hint');
        if (!els.wrap || !els.btn) return;
        els.wrap.style.display = '';        // erst jetzt sichtbar (Admin bestätigt)
        if (_bound) return;
        _bound = true;
        els.btn.addEventListener('click', function (e) { e.stopPropagation(); toggle(); });
        // Klick daneben schließt – wie beim Dokumente-Panel.
        document.addEventListener('click', function (e) {
            if (offen() && els.wrap && !els.wrap.contains(e.target)) schliessen();
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && offen()) schliessen();
        });
    }

    window.UserSessions = { init: init, load: load, close: schliessen };
})();
