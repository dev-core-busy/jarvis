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
    var _sz = null;           // Abschnitt "Anmeldung fuer die Sitzung" (zugang_sitzung.js)

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
    /* Die Fachprobe steht unter der Aktion, die im jeweiligen Betrieb gilt:
     * "Speichern" bei gespeicherten Zugaengen, "Anmelden/Abmelden" im
     * Sitzungsbetrieb. Grund (gemeldet 2026-11-16, im echten Chrome
     * nachgemessen): im Sitzungsbetrieb ist "Mein …-Zugang" ausgeblendet, und
     * die Probe darin war nach dem Aufklappen des sichtbaren Containers
     * schlicht NICHT DA. Es wird die EINE Huelle verschoben, nicht kopiert –
     * zwei Proben liefen beim naechsten Feinschliff auseinander.
     * Entscheidet dieselbe Bedingung wie das Ausblenden (``ohneEigenen``),
     * damit Ausblenden und Umsetzen nie auseinanderfallen. */
    function probePlatzieren(ohneEigenen) {
        var blk = $('ca-acc-probe-block');
        var anker = ohneEigenen ? $('ca-sz-msg') : $('ca-acc-msg');
        if (blk && anker && anker.nextElementSibling !== blk) {
            anker.parentNode.insertBefore(blk, anker.nextSibling);
        }
    }

    function accZeichnen() {
        var a = _acc || {};
        // Persoenliche Zugaenge vom Administrator abgeschaltet: der Abschnitt
        // entfaellt ganz (gleiche Regel wie in /jira-addon).
        var sect = $('ca-sect-account');
        var ohneEigenen = (a.persoenlich_erlaubt === false);
        if (sect) sect.style.display = ohneEigenen ? 'none' : '';
        probePlatzieren(ohneEigenen);
        // Sitzungsbetrieb (persoenliche Zugaenge aus): eigener Abschnitt mit
        // Anmelden/Abmelden (zugang_sitzung.js).
        if (_sz) _sz.zeichnen(a);
        var pill = $('ca-acc-pill');
        var note = $('ca-acc-note');
        var srv = $('ca-acc-server');
        var akt = $('ca-acc-aktiv');

        if (srv) {
            srv.value = a.basis_url || '';
            // tabfill: nein – Hinweis auf eine fehlende Adresse, kein Wert
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

    /* ── Fachprobe: welche Bereiche liefert Confluence mit DIESEN Rechten? ──
     *
     * "Verbindung testen" beantwortet nur, OB der Token gilt. Ein gueltiger
     * Token ohne Leserechte sieht NICHTS und ist davon nicht zu unterscheiden;
     * gemerkt haette man es erst, wenn eine Suche im Chat leer bleibt. Deshalb
     * eine zweite, FACHLICHE Probe.
     *
     * Gefragt wird `/api/confluence/account/bereiche` – mit der Schranke der
     * Konto-Routen und NUR mit dem eigenen Zugang. Die erste Fassung fragte
     * `/api/confluence/spaces`; das ist Administratoren vorbehalten, und jeder
     * andere Benutzer bekam "Nur Administratoren duerfen diese Aktion
     * ausfuehren" (gemeldet 2026-11-16). Gilt der eigene Zugang nicht, fragt
     * der Server gar nicht erst und nennt den Grund.
     *
     * NULL BEREICHE IST EIN EIGENES ERGEBNIS, kein Fehler: der Token gilt,
     * sieht aber keinen Bereich. Das wird so gesagt – stumm "0" anzuzeigen
     * waere von einem Fehlschlag nicht zu unterscheiden.
     *
     * DIE LISTE IST VOLLSTAENDIG (Vorgabe 2026-11-16: "ICH MOECHTE EINE LISTE
     * DER BEREICHE, DIE der Benutzer sieht"). Die erste Fassung zeigte nur
     * zehn – die Frage "sehe ich Bereich X?" beantwortet ein Ausschnitt nicht,
     * und ein fehlender Eintrag darin liest sich wie "kein Zugriff". Bei
     * hunderten Bereichen traegt ein Filterfeld die Suche, der Kasten rollt.
     *
     * WELCHER ZUGANG: der Endpunkt faellt auf den gemeinsamen Zugang zurueck,
     * wenn der eigene PAT nicht gilt. Ohne `zugang` aus der Antwort saehe
     * diese Liste dann aus wie die des PAT – die Probe behauptete "dein PAT
     * funktioniert", obwohl er gar nicht benutzt wurde. Fehlt die Angabe
     * (aelteres Backend), wird darueber NICHTS behauptet. */
    var _probeLaeuft = false;

    /** 'eigen' | 'sammel' | '' (unbekannt) – aus `zugang` der Antwort. */
    function probeQuelle(d) {
        var z = d && d.zugang;
        if (!z || typeof z !== 'object') return '';
        if (z.quelle === 'persoenlich') return 'eigen';
        if (z.quelle === 'sammel') return 'sammel';
        return '';
    }

    /** Filtert die gezeichnete Liste nach Schluessel ODER Name; die Zahl
     *  daneben nennt Treffer UND Gesamtzahl (eine gefilterte Liste ohne
     *  Gesamtzahl liest sich als ganzer Bestand). */
    function probeFiltern() {
        var out = $('ca-acc-probe-out');
        var feld = $('ca-acc-probe-filter');
        if (!out || !feld) return;
        var q = (feld.value || '').trim().toLowerCase();
        var lis = out.querySelectorAll('li[data-such]');
        var n = 0;
        for (var i = 0; i < lis.length; i++) {
            var treffer = !q || lis[i].getAttribute('data-such').indexOf(q) >= 0;
            lis[i].hidden = !treffer;
            if (treffer) n++;
        }
        var z = $('ca-acc-probe-zahl');
        if (z) {
            z.textContent = q
                ? (n + ' ' + T('caddon.probe_von', 'von') + ' ' + lis.length
                   + ' ' + T('caddon.probe_treffer', 'Bereichen passen.'))
                : '';
        }
    }

    function probeMeld(text, art) {
        var n = $('ca-acc-probe-note');
        if (!n) return;
        n.textContent = text || '';
        n.className = 'ja-probe-note' + (art ? ' is-' + art : '');
    }

    /** Maskiert JEDEN Wert: Bereichsnamen kommen aus Confluence, also aus
     *  Inhalten, die Menschen frei benennen. */
    function probeEsc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }

    async function probeLaufen() {
        if (_probeLaeuft) return;          // Doppelklick: ein Lauf genuegt
        var btn = $('ca-acc-probe');
        var out = $('ca-acc-probe-out');
        _probeLaeuft = true;
        if (btn) btn.disabled = true;
        if (out) { out.hidden = true; out.innerHTML = ''; }
        probeMeld(T('caddon.probe_wait', 'Frage Confluence …'));
        try {
            var r = await fetch('/api/confluence/account/bereiche',
                                { headers: { 'Authorization': 'Bearer ' + token() } });
            var d = null;
            try { d = await r.json(); } catch (e) { d = null; }
            var quelle = probeQuelle(d);
            if (!r.ok || !d || d.ok === false) {
                var grund = (d && (d.error || d.detail))
                            || T('caddon.probe_fail', 'Abfrage fehlgeschlagen.');
                // Mit dem EIGENEN PAT gescheitert heisst: der PAT funktioniert
                // nicht – das gehoert dazugesagt, sonst sucht man beim Server.
                throw new Error(quelle === 'eigen'
                    ? T('caddon.probe_pat_fehler', 'Dein PAT funktioniert nicht:') + ' ' + grund
                    : grund);
            }
            var sp = Array.isArray(d.spaces) ? d.spaces : [];
            var ges = (typeof d.count === 'number') ? d.count : sp.length;
            var hinweis = (d.zugang && d.zugang.hinweis) ? String(d.zugang.hinweis) : '';
            if (!sp.length) {
                probeMeld(T('caddon.probe_leer',
                    'Der Zugang gilt, sieht aber keinen Bereich. Bitte in Confluence pruefen, '
                    + 'ob dein Konto Leserechte hat.'), 'error');
                return;
            }
            if (quelle === 'eigen') {
                probeMeld('✓ ' + T('caddon.probe_pat_ok', 'Dein PAT funktioniert –')
                          + ' ' + ges + ' ' + T('caddon.probe_sichtbar', 'Bereiche sichtbar.'), 'ok');
            } else if (quelle === 'sammel') {
                // Die Liste ist echt, aber sie beantwortet die gestellte Frage
                // NICHT: als Fehler gekennzeichnet, damit niemand sie fuer die
                // eigene haelt.
                probeMeld('⚠ ' + T('caddon.probe_sammel',
                    'Dein PAT wurde NICHT verwendet – die Liste zeigt den gemeinsamen Zugang.')
                    + (hinweis ? ' ' + hinweis : ''), 'error');
            } else {
                probeMeld('✓ ' + T('caddon.probe_ok', 'Sichtbare Bereiche insgesamt:')
                          + ' ' + ges, 'ok');
            }
            var html = '<p class="ja-probe-kopf">'
                + probeEsc(quelle === 'sammel'
                    ? T('caddon.probe_head_sammel', 'Bereiche, die der gemeinsame Zugang lesen darf:')
                    : T('caddon.probe_head', 'Bereiche, die dein Zugang lesen darf:'))
                + ' ' + ges + '</p>'
                + '<div class="ja-probe-filterzeile">'
                + '<input type="search" class="ja-acc-input ja-probe-filter" id="ca-acc-probe-filter"'
                + ' autocomplete="off" placeholder="'
                + probeEsc(T('caddon.probe_filter_ph', 'Bereiche filtern (Schlüssel oder Name)'))
                + '"><span class="ja-probe-zahl" id="ca-acc-probe-zahl"></span></div>'
                + '<ul class="ja-probe-liste">';
            sp.forEach(function (s) {
                var such = (String(s.key || '') + ' ' + String(s.name || '')).toLowerCase();
                html += '<li data-such="' + probeEsc(such) + '"><span class="ja-probe-key">'
                     + probeEsc(s.key || '?') + '</span> ' + probeEsc(s.name || '') + '</li>';
            });
            html += '</ul>';
            if (out) {
                out.innerHTML = html;
                out.hidden = false;
                var feld = $('ca-acc-probe-filter');
                if (feld) {
                    feld.addEventListener('input', probeFiltern);
                    // Escape leert das Feld – sonst muss man den Text von Hand
                    // loeschen, um die volle Liste zurueckzubekommen.
                    feld.addEventListener('keydown', function (ev) {
                        if (ev.key === 'Escape') { feld.value = ''; probeFiltern(); }
                    });
                }
            }
        } catch (e) {
            probeMeld('❌ ' + e.message, 'error');
        } finally {
            _probeLaeuft = false;
            if (btn) btn.disabled = false;
        }
    }

    function accVerdrahten() {
        var pb = $('ca-acc-probe');
        if (pb) pb.addEventListener('click', probeLaufen);

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
        if (window.ZugangSitzung) {
            _sz = window.ZugangSitzung.einrichten({
                praefix: 'ca', name: 'Confluence', pfad: '/api/confluence/account/sitzung', token: token,
                nachher: function (acc) { _acc = acc; accZeichnen(); }
            });
        }
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
