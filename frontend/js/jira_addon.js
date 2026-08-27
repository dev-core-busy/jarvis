/* Anleitungs- und Downloadseite fuer die Browser-Erweiterung (/jira-addon).
 *
 * Die Seite ist eine LEERE HUELLE: die Route prueft keine Berechtigung (eine
 * Navigation traegt keinen Authorization-Header). Geprueft wird hier ueber
 * /api/me, und Unberechtigte gehen aufs Portal – die DATEN liegen ohnehin
 * hinter require_jira_assist_access.
 */
(function () {
    'use strict';

    var $ = function (id) { return document.getElementById(id); };

    function token() { return localStorage.getItem('jarvis_token') || ''; }

    function T(key, rueckfall) {
        // i18n.js ist eingebunden; faellt es aus, steht der deutsche Text da.
        try {
            if (window.t) { var s = window.t(key); if (s && s !== key) return s; }
        } catch (e) {}
        return rueckfall;
    }

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }

    // ── Zustand: gemessen, nicht behauptet ──────────────────────────────────
    /* Drei Zeilen mit je eigener Aussage. WICHTIG ist die dritte: passt die
     * Adresse nicht zum Serverzertifikat, bricht der Hintergrund-Aufruf der
     * Erweiterung wortlos ab – dort gibt es kein "trotzdem fortfahren" wie in
     * einem Tab. Genau dieser Fehler hat beim Outlook-Add-in Tage gekostet,
     * deshalb steht er hier VOR der Anleitung. */
    function zeile(art, text) {
        return '<li class="ja-st ja-st-' + art + '">' + esc(text) + '</li>';
    }

    function zeigeStatus(d) {
        var box = $('ja-status');
        if (!box) return;
        var out = [];

        out.push(zeile('ok', T('jaddon.st_free',
            'Dein Konto ist für den Jira-Assistenten freigeschaltet.')));

        if (d && d.jira_konfiguriert) {
            out.push(zeile('ok', T('jaddon.st_jira_ok',
                'Die Jira-Anbindung ist eingerichtet.')));
        } else {
            out.push(zeile('warn', T('jaddon.st_jira_no',
                'Die Jira-Anbindung ist nicht eingerichtet – ohne sie kann kein '
                + 'Ticket gelesen werden. Bitte die Administration ansprechen.')));
        }

        // Die Adresse, die der Benutzer in die Erweiterung eintragen soll.
        var adresse = window.location.origin;
        if (d && d.zert_deckt_adresse === false) {
            // Nicht gedeckt: das ist die haeufigste unerklaerliche Fehlerursache.
            out.push(zeile('warn', T('jaddon.st_cert_bad',
                'Achtung: diese Adresse (' + adresse + ') steht nicht im '
                + 'Serverzertifikat. Die Erweiterung wird den Server darüber '
                + 'nicht erreichen. Benutze stattdessen: '
                + ((d.zert_namen || []).join(', ') || '–'))));
        } else if (d && d.zert_deckt_adresse === true) {
            out.push(zeile('ok', T('jaddon.st_cert_ok',
                'Trage in der Erweiterung diese Adresse ein: ') + adresse));
        } else {
            // null = nicht feststellbar. Das ist NICHT dasselbe wie "passt nicht"
            // (z.B. TLS-Terminierung in einem Rueckwaertsproxy) – hier wird
            // deshalb nichts behauptet.
            out.push(zeile('info', T('jaddon.st_cert_unknown',
                'Trage in der Erweiterung die Adresse ein, unter der du Jarvis '
                + 'aufrufst (aktuell: ') + adresse + ').'));
        }
        box.innerHTML = out.join('');
    }

    // ── Herunterladen ───────────────────────────────────────────────────────
    /* Bewusst per fetch + Blob statt <a href="…?token=">: ein Query-Token
     * landet im Browser-Verlauf und in Proxy-Logs. Hier gibt es keinen Grund
     * dafuer – der Klick kann den Authorization-Header setzen. */
    function meldung(text, warn) {
        var m = $('ja-dl-msg');
        if (!m) return;
        m.textContent = text || '';
        m.hidden = !text;
        m.classList.toggle('ja-warn', !!warn);
    }

    async function laden(variante, knopf) {
        var alt = knopf.textContent;
        knopf.disabled = true;
        knopf.textContent = T('jaddon.dl_running', 'wird erstellt …');
        meldung('');
        try {
            var r = await fetch('/api/jira/assist/paket?variante=' + encodeURIComponent(variante), {
                headers: { 'Authorization': 'Bearer ' + token() }
            });
            if (!r.ok) {
                var d = null;
                try { d = await r.json(); } catch (e) {}
                throw new Error((d && d.error) || ('HTTP ' + r.status));
            }
            var blob = await r.blob();
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            a.download = 'jarvis-jira-' + variante + '.zip';
            document.body.appendChild(a);
            a.click();
            a.remove();
            // Erst nach dem Klick freigeben, sonst ist der Blob schon weg.
            setTimeout(function () { URL.revokeObjectURL(url); }, 5000);
            meldung(T('jaddon.dl_ok', 'Paket heruntergeladen. Weiter bei Schritt 2.'));
        } catch (e) {
            meldung(T('jaddon.dl_err', 'Download fehlgeschlagen: ') + (e.message || e), true);
        } finally {
            knopf.disabled = false;
            knopf.textContent = alt;
        }
    }

    // ── Start ───────────────────────────────────────────────────────────────
    async function start() {
        if (!token()) { window.location.replace('/'); return; }

        var me = null;
        try {
            var r = await fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + token() } });
            me = r.ok ? await r.json() : null;
        } catch (e) { me = null; }

        // Fail-closed: fehlt die Auskunft, gilt "nicht freigegeben".
        var darf = !!(me && me.permissions && me.permissions.jira_assist);
        if (!darf) { window.location.replace('/portal'); return; }

        var app = $('ja-app');
        if (app) app.classList.remove('hidden');

        // Das Zahnrad nur fuer Administratoren – wie auf den anderen Bereichsseiten.
        if (me && me.is_admin) {
            var s = $('ja-settings-btn');
            if (s) s.style.display = '';
        }

        try {
            var h = await fetch('/api/jira/assist/health',
                                { headers: { 'Authorization': 'Bearer ' + token() } });
            zeigeStatus(h.ok ? await h.json() : null);
        } catch (e) {
            zeigeStatus(null);
        }

        var c = $('ja-dl-chrome'), f = $('ja-dl-firefox');
        if (c) c.addEventListener('click', function () { laden('chrome', c); });
        if (f) f.addEventListener('click', function () { laden('firefox', f); });

        var p = $('ja-portal-btn');
        if (p) p.addEventListener('click', function () { window.location.href = '/portal'; });

        var lo = $('ja-logout-btn');
        if (lo) lo.addEventListener('click', async function () {
            // Das Abmelde-Signal muss RAUS, BEVOR das Token verworfen wird –
            // und mit keepalive, weil die Seite unmittelbar danach wegnavigiert.
            try {
                await fetch('/api/logout', {
                    method: 'POST', keepalive: true,
                    headers: { 'Authorization': 'Bearer ' + token() }
                });
            } catch (e) {}
            localStorage.removeItem('jarvis_token');
            window.location.href = '/';
        });

        // Der Zustandsblock ist gerendert, nicht uebersetzt – nach einem
        // Sprachwechsel muss er neu gebaut werden, sonst bleibt er deutsch.
        window.addEventListener('jarvis-lang-changed', function () {
            fetch('/api/jira/assist/health',
                  { headers: { 'Authorization': 'Bearer ' + token() } })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(zeigeStatus)
                .catch(function () {});
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
