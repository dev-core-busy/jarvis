/* Seite fuer den persoenlichen Confluence-Zugang (/confluence-addon).
 *
 * Die Seite ist eine LEERE HUELLE: die Route prueft keine Berechtigung (eine
 * Navigation traegt keinen Authorization-Header). Geprueft wird hier ueber
 * /api/me, und Unberechtigte gehen aufs Portal – die DATEN liegen ohnehin
 * hinter require_confluence_account_access.
 *
 * Bauform 1:1 aus `jira_addon.js` (Abschnitt "Mein Jira-Zugang") uebernommen.
 * BEWUSST eine eigene Datei und keine gemeinsame: die beiden Bereiche haengen
 * an verschiedenen Endpunkten, verschiedenen Freigaben und verschiedenen
 * i18n-Schluesseln – ein geteiltes Modul muesste all das parametrisieren und
 * waere an jeder kuenftigen Abweichung eine Verzweigung mehr. Was WIRKLICH
 * geteilt ist, ist das CSS (`jira_addon.css`).
 */
(function () {
    'use strict';

    var $ = function (id) { return document.getElementById(id); };

    function token() { return window.JarvisSitzung.token(); }

    function T(key, rueckfall) {
        // i18n.js ist eingebunden; faellt es aus, steht der deutsche Text da.
        try {
            if (window.t) { var s = window.t(key); if (s && s !== key) return s; }
        } catch (e) {}
        return rueckfall;
    }

    /* ══ Mein Confluence-Zugang ═════════════════════════════════════════════
     *
     * Der in der Skill-Config hinterlegte Token ist nur noch der RUECKFALL: wer
     * hier einen eigenen hinterlegt, arbeitet damit – bei den
     * confluence_*-Werkzeugen im Chat. Beim Sammelzugang sieht jeder alles, was
     * dem Servertoken offensteht, und schreibt unter dessen Namen.
     *
     * DER TOKEN VERLAESST DEN SERVER NIE. Gelesen wird nur `token_gesetzt`
     * (ja/nein) – eine maskierte Form ("****") verriete die Laenge, und ein
     * leeres Feld heisst hier "unveraendert".
     */
    var _acc = null;          // zuletzt gelesener Zustand

    function accMeld(text, art) {
        var p = $('ca-acc-msg');
        if (!p) return;
        if (!text) { p.hidden = true; p.textContent = ''; return; }
        // textContent: die Texte kommen teils vom Server (Fehlermeldungen).
        p.textContent = text;
        p.style.color = (art === 'error') ? 'var(--danger)'
            : (art === 'ok' ? 'var(--success)' : '');
        p.hidden = false;
    }

    /** Zeichnet Pille, Hinweiskasten und Felder aus `_acc`. */
    function accZeichnen() {
        var a = _acc || {};
        var pill = $('ca-acc-pill');
        var note = $('ca-acc-note');
        var srv = $('ca-acc-server');
        var akt = $('ca-acc-aktiv');

        if (srv) {
            srv.value = a.basis_url || '';
            srv.placeholder = a.server_konfiguriert ? ''
                : T('caddon.acc_no_server', '— keine Adresse hinterlegt —');
        }
        if (akt) akt.checked = (a.aktiv !== false);

        /* DIE PILLE SAGT, WELCHER ZUGANG GERADE GILT – und das ist keine
         * Kosmetik: ein stiller Rueckfall auf den Sammelzugang liesse den
         * Benutzer Seiten sehen, die mit FREMDEN Rechten geholt wurden, ohne
         * dass er es merkt. Aussage doppelt (Text UND Farbe). */
        if (pill) {
            pill.className = 'ja-acc-pill';
            if (!a.vorhanden) {
                pill.textContent = T('caddon.acc_pill_none', 'gemeinsamer Zugang');
            } else if (a.aktiv === false) {
                pill.textContent = T('caddon.acc_pill_off', 'inaktiv');
                pill.classList.add('is-warn');
            } else if (a.letzter_fehler) {
                pill.textContent = T('caddon.acc_pill_err', 'Token abgelehnt');
                pill.classList.add('is-warn');
            } else {
                pill.textContent = T('caddon.acc_pill_own', 'eigener Zugang');
                pill.classList.add('is-own');
            }
        }

        if (note) {
            var zeilen = [];
            if (a.vorhanden && a.anzeigename) {
                zeilen.push(T('caddon.acc_as', 'Angemeldet in Confluence als:') + ' '
                            + a.anzeigename + (a.konto ? ' (' + a.konto + ')' : ''));
            }
            if (a.vorhanden && a.letzter_fehler) {
                zeilen.push(T('caddon.acc_lasterr', 'Letzter Fehler:') + ' ' + a.letzter_fehler);
            }
            // Ohne Sammelzugang ist ein eigener Token der EINZIGE Weg – dann
            // darf die Oberflaeche ihn nicht als "optional" darstellen.
            if (!a.vorhanden && a.sammel_vorhanden === false) {
                zeilen.push(T('caddon.acc_none_at_all',
                    'Es ist weder ein gemeinsamer noch ein eigener Zugang hinterlegt – '
                    + 'ohne Token kann keine Seite geladen werden.'));
            }
            note.textContent = '';
            zeilen.forEach(function (z) {
                var d = document.createElement('div');
                d.textContent = z;      // Fremdtext (Confluence-Name, Fehlermeldung)
                note.appendChild(d);
            });
            note.classList.toggle('is-on', zeilen.length > 0);
        }
    }

    async function accLaden() {
        try {
            var r = await fetch('/api/confluence/account',
                                { headers: { 'Authorization': 'Bearer ' + token() } });
            var d = r.ok ? await r.json() : null;
            _acc = (d && d.account) || null;
        } catch (e) { _acc = null; }
        accZeichnen();
    }

    /** Ein Schreibzugriff auf den eigenen Zugang – EINE Stelle fuer alle drei
     *  Knoepfe, damit Fehlerbehandlung und Neuzeichnen nicht dreimal
     *  auseinanderlaufen. */
    async function accRuf(pfad, methode, rumpf, erfolgstext) {
        var knoepfe = ['ca-acc-save', 'ca-acc-test', 'ca-acc-del'];
        knoepfe.forEach(function (i) { if ($(i)) $(i).disabled = true; });
        accMeld(T('caddon.acc_working', 'Einen Moment …'));
        try {
            var opt = { method: methode,
                        headers: { 'Authorization': 'Bearer ' + token() } };
            if (rumpf) {
                opt.headers['Content-Type'] = 'application/json';
                opt.body = JSON.stringify(rumpf);
            }
            var r = await fetch(pfad, opt);
            var d = null;
            try { d = await r.json(); } catch (e) { d = null; }
            if (!r.ok || !d || d.ok === false) {
                throw new Error((d && (d.error || d.detail))
                                || T('caddon.acc_fail', 'Vorgang fehlgeschlagen.'));
            }
            if (d.account) { _acc = d.account; accZeichnen(); }
            else if (d.info) { _acc = d.info; accZeichnen(); }
            else { await accLaden(); }
            // Das Token-Feld wird nach JEDEM Schreibzugriff geleert: es stuende
            // sonst im Klartext im Formular, und ein leeres Feld heisst beim
            // naechsten Speichern korrekt "unveraendert".
            if ($('ca-acc-token')) $('ca-acc-token').value = '';
            accMeld(typeof erfolgstext === 'function' ? erfolgstext(d) : erfolgstext, 'ok');
        } catch (e) {
            accMeld(e.message, 'error');
        } finally {
            knoepfe.forEach(function (i) { if ($(i)) $(i).disabled = false; });
        }
    }

    function accVerdrahten() {
        var sp = $('ca-acc-save');
        if (sp) sp.addEventListener('click', function () {
            var tok = ($('ca-acc-token') ? $('ca-acc-token').value : '').trim();
            var aktiv = !!($('ca-acc-aktiv') && $('ca-acc-aktiv').checked);
            if (!tok && !(_acc && _acc.vorhanden)) {
                accMeld(T('caddon.acc_need_token',
                          'Bitte zuerst einen Token eintragen.'), 'error');
                return;
            }
            // Ein LEERES Feld wird gar nicht erst gesendet – "leer heisst
            // unveraendert" bleibt so eine Regel des Servers und nicht zwei.
            var rumpf = { aktiv: aktiv };
            if (tok) rumpf.api_token = tok;
            accRuf('/api/confluence/account', 'POST', rumpf,
                   T('caddon.acc_saved', '✓ Gespeichert.'));
        });

        var te = $('ca-acc-test');
        if (te) te.addEventListener('click', function () {
            accRuf('/api/confluence/account/test', 'POST', null, function (d) {
                // Der Name kann LEER sein: auf Confluence-Faessungen ohne
                // /user/current gilt eine Lebendpruefung als Erfolg (siehe
                // confluence_accounts.testen). Dann sagt die Meldung genau das,
                // statt ein "?" hinzuschreiben, das nach einem Fehler aussieht.
                var wer = d.anzeigename || d.konto || '';
                return wer
                    ? T('caddon.acc_test_ok', '✓ Verbindung steht – angemeldet als') + ' ' + wer
                    : T('caddon.acc_test_ok_anon',
                        '✓ Verbindung steht. Deinen Namen gibt dieser Confluence-Server nicht heraus.');
            });
        });

        var de = $('ca-acc-del');
        if (de) de.addEventListener('click', function () {
            // Eigener Dialog waere hier Aufwand ohne Gewinn: die Seite ist kein
            // Aufgabenfenster (dort ist `confirm` unterdrueckt), und es geht
            // kein Inhalt verloren – nur eine Einstellung, die man neu setzt.
            if (!window.confirm(T('caddon.acc_del_ask',
                'Eigenen Confluence-Token entfernen? Danach gilt wieder der gemeinsame Zugang.'))) return;
            accRuf('/api/confluence/account', 'DELETE', null,
                   T('caddon.acc_deleted', '✓ Entfernt – es gilt wieder der gemeinsame Zugang.'));
        });
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
        var darf = !!(me && me.permissions && me.permissions.confluence);
        if (!darf) { window.location.replace('/portal'); return; }

        var app = $('ca-app');
        if (app) app.classList.remove('hidden');

        // Das Zahnrad blendet settings_btn.js zentral ueber /api/me ein – hier
        // stand eine zweite Verdrahtung derselben Frage (2026-10-25 entfernt,
        // test_settings_btn: "kein Skript einer Zahnrad-Seite fasst den Knopf an").

        // Der eigene Zugang wird IMMER geladen: die Pille am Titel ist der
        // einzige Hinweis darauf, welcher Zugang gerade gilt.
        accVerdrahten();
        accLaden();

        var p = $('ca-portal-btn');
        if (p) p.addEventListener('click', function () { window.location.href = '/portal'; });

        var lo = $('ca-logout-btn');
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

        // Pille und Hinweiskasten werden GERENDERT, nicht per data-i18n
        // uebersetzt – ohne diese Zeile blieben sie nach einem Sprachwechsel
        // deutsch. KEIN Neuladen noetig, der Zustand liegt schon vor.
        window.addEventListener('jarvis-lang-changed', function () {
            accZeichnen();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
