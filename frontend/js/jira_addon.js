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

    /* Dateiname aus `Content-Disposition`. Gebildet wird er SERVERSEITIG aus
     * der Marke (jira_assist.paket_dateiname) – hier wird nur gelesen, sonst
     * gaebe es zwei Fassungen derselben Namensregel. Zugelassen ist nur
     * [A-Za-z0-9._-]: der Markenname im Kopf ist Fremdeingabe, und ein
     * Schraegstrich waere im Download-Ordner ein Pfadanteil. */
    function nameAusKopf(kopf) {
        var m = /filename="?([^";]+)"?/i.exec(kopf || '');
        var n = m ? m[1].trim() : '';
        return /^[A-Za-z0-9._-]+$/.test(n) ? n : '';
    }

    /* {marke} in einem Text, den JS selbst zusammenbaut.
     *
     * WARUM NICHT branding.js ueberlassen: dessen Durchlauf sammelt die
     * Fundstellen beim Laden und nach einem Sprachwechsel ein. Was DANACH ins
     * DOM kommt - und diese Zeile entsteht erst nach der Antwort von
     * /api/jira/assist/health - waere nicht dabei; im Fenster stuende dann roh
     * "{marke}-Adresse". `window.jarvisMarke` ist genau fuer diesen Fall da.
     * Ohne Branding liefert es "Jarvis", also den richtigen Rueckfall. */
    function mitMarke(text) {
        var name = 'Jarvis';
        try { if (window.jarvisMarke) name = window.jarvisMarke() || name; }
        catch (e) { /* Rueckfall bleibt */ }
        return String(text || '').split('{marke}').join(name);
    }

    // ── Die Serveradresse, die in die Erweiterung gehoert ───────────────────
    /* Sie stand bis 2026-08-28 in einer eigenen Karte „Einsatzbereit?" ganz
     * oben, zusammen mit zwei Zeilen, die nur bestaetigten, dass alles in
     * Ordnung ist. Auf Vorgabe des Nutzers steht sie jetzt an der Stelle, an
     * der sie gebraucht wird: Schritt 3, Punkt 2 – direkt neben dem Satz
     * „diese Adresse eintragen".
     *
     * DIE ZERTIFIKATSPRUEFUNG IST MITGEWANDERT UND DARF NICHT ENTFALLEN:
     * passt die Adresse nicht zum Serverzertifikat, bricht der
     * Hintergrund-Aufruf der Erweiterung WORTLOS ab – dort gibt es kein
     * „trotzdem fortfahren" wie in einem Tab. Genau dieser Fehler hat beim
     * Outlook-Add-in Tage gekostet. */
    /* `location.origin` ist NICHT immer eine brauchbare Adresse: bei einer
     * lokalen Datei steht dort "file://", in einem abgeschotteten iframe
     * "null". Beides in ein Feld zu schreiben, das der Benutzer KOPIERT und in
     * die Erweiterung eintraegt, waere Unsinn - er bekaeme eine Adresse, unter
     * der nie ein Server geantwortet hat. Dieselbe Absicherung wie in
     * branding.js::eigeneAdresse; hier ohne Platzhaltertext, weil das Feld zum
     * Kopieren da ist: laesst sich nichts ermitteln, steht lieber nichts. */
    function eigeneAdresse() {
        var o = window.location.origin || '';
        if (/^https?:\/\/.+/.test(o)) return o;
        if (window.location.hostname) return 'https://' + window.location.hostname;
        return '';
    }

    function zeigeAdresse(d) {
        var box = $('ja-adresse');
        if (!box) return;
        box.innerHTML = '';

        var adresse = eigeneAdresse();
        var nichtGedeckt = !!(d && d.zert_deckt_adresse === false);
        // Deckt das Zertifikat die aufgerufene Adresse nicht, ist die Adresse
        // im Zertifikat die richtige - nicht die, unter der man gerade steht.
        var namen = (d && d.zert_namen) || [];
        var eintragen = (nichtGedeckt && namen.length)
            ? 'https://' + String(namen[0]).replace(/^\*\./, '')
            : adresse;

        // Ein Kopierfeld ohne brauchbaren Inhalt waere eine Falle - lieber
        // nichts anbieten als eine Adresse, unter der nie ein Server stand.
        if (!eintragen) return;
        box.appendChild(pfadZeile(mitMarke(T('jaddon.adr_lab', '{marke}-Adresse')),
                                  eintragen,
                                  T('jaddon.adr_copy', 'Adresse kopieren')));

        if (nichtGedeckt) {
            var warn = document.createElement('p');
            warn.className = 'ja-warn';
            // textContent: die Namen stammen aus dem Serverzertifikat.
            warn.textContent = T('jaddon.adr_cert_bad',
                'Wichtig: die Adresse, unter der du gerade hier bist (')
                + adresse + T('jaddon.adr_cert_bad2',
                '), steht nicht im Serverzertifikat – über sie erreicht die '
                + 'Erweiterung den Server nicht. Trage genau den Namen oben ein.')
                + (namen.length > 1
                    ? ' ' + T('jaddon.adr_cert_more', 'Ebenfalls möglich: ')
                      + namen.slice(1).join(', ')
                    : '');
            box.appendChild(warn);
        }
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

    /* ── Woher das Paket kommt: Netzfreigabe ODER Download ────────────────
     *
     * Ist unter *Einstellungen → Jira* ein Netzwerkpfad hinterlegt, steht hier
     * dieser Pfad zum Kopieren – sonst wie bisher der Download-Knopf. Die
     * Entscheidung faellt JE VARIANTE: ein Haus kann das Chrome-Paket auf die
     * Freigabe legen und Firefox weiter herunterladen lassen.
     *
     * Der Pfad ist Fremdeingabe aus einem Formular und wird ausschliesslich per
     * textContent gesetzt.
     */
    function kopieren(pfad, knopf) {
        var alt = knopf.textContent;
        var fertig = function (text) {
            knopf.textContent = text;
            setTimeout(function () { knopf.textContent = alt; }, 2000);
        };
        try {
            navigator.clipboard.writeText(pfad).then(function () {
                // Rueckmeldung ist Pflicht: in der Zwischenablage sieht man
                // nichts, ein stiller Fehlschlag waere unsichtbar.
                fertig(T('jaddon.copy_ok', 'kopiert ✓'));
            }, function () {
                meldung(T('jaddon.copy_err',
                    'Kopieren nicht möglich – markiere den Pfad und kopiere ihn '
                    + 'von Hand.'), true);
            });
        } catch (e) {
            meldung(T('jaddon.copy_err',
                'Kopieren nicht möglich – markiere den Pfad und kopiere ihn '
                + 'von Hand.'), true);
        }
    }

    /* `knopfText` ist optional: derselbe Baustein traegt einen Netzwerkpfad UND
     * die Serveradresse - "Pfad kopieren" waere an der Adresse falsch. */
    function pfadZeile(titel, pfad, knopfText) {
        var zeileEl = document.createElement('div');
        zeileEl.className = 'ja-pfad';

        var lab = document.createElement('div');
        lab.className = 'ja-pfad-lab';
        lab.textContent = titel;

        var wert = document.createElement('code');
        wert.className = 'ja-pfad-wert';
        wert.textContent = pfad;          // NIE innerHTML – Fremdeingabe

        var knopf = document.createElement('button');
        knopf.type = 'button';
        knopf.className = 'ja-btn';
        knopf.textContent = knopfText || T('jaddon.copy', 'Pfad kopieren');
        knopf.addEventListener('click', function () { kopieren(pfad, knopf); });

        zeileEl.appendChild(lab);
        zeileEl.appendChild(wert);
        zeileEl.appendChild(knopf);
        return zeileEl;
    }

    function dlKnopf(variante, titel) {
        var b = document.createElement('button');
        b.type = 'button';
        b.id = 'ja-dl-' + variante;
        b.className = 'ja-btn' + (variante === 'chrome' ? ' ja-btn-haupt' : '');
        b.textContent = titel;
        b.addEventListener('click', function () { laden(variante, b); });
        return b;
    }

    function paketBlock(d) {
        var box = $('ja-paket');
        if (!box) return;
        var pfade = (d && d.paket_pfade) || {};
        var varianten = [
            ['chrome', T('jaddon.dl_chrome', 'Für Chrome / Edge')],
            ['firefox', T('jaddon.dl_firefox', 'Für Firefox')]
        ];
        var mitPfad = varianten.some(function (v) {
            return !!(pfade[v[0]] || '').trim();
        });
        box.innerHTML = '';
        // Nebeneinander nur, solange es zwei Knoepfe sind – ein Pfad braucht
        // die ganze Breite, sonst bricht er mitten im Servernamen um.
        box.className = 'ja-dl' + (mitPfad ? ' ja-dl-spalte' : '');
        varianten.forEach(function (v) {
            var pfad = (pfade[v[0]] || '').trim();
            box.appendChild(pfad ? pfadZeile(v[1], pfad) : dlKnopf(v[0], v[1]));
        });
        if (mitPfad) {
            var hinweis = document.createElement('p');
            hinweis.className = 'ja-hint';
            hinweis.textContent = T('jaddon.share_hint',
                'Pfad kopieren und im Windows-Explorer in die Adresszeile '
                + 'einfügen. Kommst du nicht an die Freigabe, wende dich an die '
                + 'Administration.');
            box.appendChild(hinweis);
        }
    }

    /* Der WIRKLICHE Stand der Werkzeug-Bereiche.
     *
     * Ohne Auskunft (aelterer Server, health nicht erreichbar) bleibt die Zeile
     * LEER statt eine Behauptung zu wagen: "nichts freigeschaltet" waere in dem
     * Fall geraten, und der Punkt darueber sagt schon, dass es von einer
     * Freigabe abhaengt.
     */
    function bereicheBlock(d) {
        var box = $('ja-bereiche');
        if (!box) return;
        box.textContent = '';
        if (!d || !Array.isArray(d.assist_bereiche)) return;
        var namen = d.assist_bereiche.map(function (b) {
            return (b && b.name) || (b && b.id) || '';
        }).filter(Boolean);
        if (!namen.length) {
            box.textContent = T('jaddon.ber_off',
                'Auf diesem Server ist kein Bereich freigeschaltet – die '
                + 'Auswertung hat keinerlei Werkzeuge.');
            return;
        }
        // textContent, kein innerHTML: die Namen kommen aus der Konfiguration.
        box.textContent = T('jaddon.ber_on',
            'Freigeschaltet auf diesem Server: {liste}.')
            .replace('{liste}', namen.join(', '));
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
            // ⚠ BEI EINEM BLOB-DOWNLOAD ENTSCHEIDET `a.download`, NICHT der Kopf
            // des Servers. Hier stand der Name hart als "jarvis-jira-…" und
            // blieb es auch, nachdem das Paket laengst gebrandet war.
            var dateiname = nameAusKopf(r.headers.get('Content-Disposition'));
            var blob = await r.blob();
            var url = URL.createObjectURL(blob);
            var a = document.createElement('a');
            a.href = url;
            // Rueckfall markenNEUTRAL – "jarvis" waere auf einem gebrandeten
            // System wieder genau der gemeldete Fehler.
            a.download = dateiname || ('jira-erweiterung-' + variante + '.zip');
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

    /* ══ Mein Jira-Zugang ═══════════════════════════════════════════════════
     *
     * Seit 2026-08-28 ist der in der Skill-Config hinterlegte Token nur noch
     * der RUECKFALL: wer hier einen eigenen hinterlegt, arbeitet damit – im
     * Chat, in der Ticketsuche und in der Erweiterung. Beim Sammelzugang sieht
     * jeder Freigegebene alles, was dem Servertoken offensteht, und in
     * Ticketverlaeufen stehen Kundendaten.
     *
     * DER TOKEN VERLAESST DEN SERVER NIE. Gelesen wird nur `token_gesetzt`
     * (ja/nein) – eine maskierte Form ("****") verriete die Laenge, und ein
     * leeres Feld heisst hier "unveraendert".
     */
    var _acc = null;          // zuletzt gelesener Zustand

    function accMeld(text, art) {
        var p = $('ja-acc-msg');
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
        var pill = $('ja-acc-pill');
        var note = $('ja-acc-note');
        var srv = $('ja-acc-server');
        var akt = $('ja-acc-aktiv');

        if (srv) {
            srv.value = a.basis_url || '';
            srv.placeholder = a.server_konfiguriert ? ''
                : T('jaddon.acc_no_server', '— keine Adresse hinterlegt —');
        }
        if (akt) akt.checked = (a.aktiv !== false);

        /* DIE PILLE SAGT, WELCHER ZUGANG GERADE GILT – und das ist keine
         * Kosmetik: ein stiller Rueckfall auf den Sammelzugang liesse den
         * Benutzer Tickets sehen, die mit FREMDEN Rechten geholt wurden, ohne
         * dass er es merkt. Aussage doppelt (Text UND Farbe). */
        if (pill) {
            pill.className = 'ja-acc-pill';
            if (!a.vorhanden) {
                pill.textContent = T('jaddon.acc_pill_none', 'gemeinsamer Zugang');
            } else if (a.aktiv === false) {
                pill.textContent = T('jaddon.acc_pill_off', 'inaktiv');
                pill.classList.add('is-warn');
            } else if (a.letzter_fehler) {
                pill.textContent = T('jaddon.acc_pill_err', 'Token abgelehnt');
                pill.classList.add('is-warn');
            } else {
                pill.textContent = T('jaddon.acc_pill_own', 'eigener Zugang');
                pill.classList.add('is-own');
            }
        }

        if (note) {
            var zeilen = [];
            if (a.vorhanden && a.anzeigename) {
                zeilen.push(T('jaddon.acc_as', 'Angemeldet in Jira als:') + ' '
                            + a.anzeigename + (a.konto ? ' (' + a.konto + ')' : ''));
            }
            if (a.vorhanden && a.letzter_fehler) {
                zeilen.push(T('jaddon.acc_lasterr', 'Letzter Fehler:') + ' ' + a.letzter_fehler);
            }
            // Ohne Sammelzugang ist ein eigener Token der EINZIGE Weg – dann
            // darf die Oberflaeche ihn nicht als "optional" darstellen.
            if (!a.vorhanden && a.sammel_vorhanden === false) {
                zeilen.push(T('jaddon.acc_none_at_all',
                    'Es ist weder ein gemeinsamer noch ein eigener Zugang hinterlegt – '
                    + 'ohne Token kann kein Ticket geladen werden.'));
            }
            note.textContent = '';
            zeilen.forEach(function (z) {
                var d = document.createElement('div');
                d.textContent = z;      // Fremdtext (Jira-Name, Fehlermeldung)
                note.appendChild(d);
            });
            note.classList.toggle('is-on', zeilen.length > 0);
        }
    }

    async function accLaden() {
        try {
            var r = await fetch('/api/jira/account',
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
        var knoepfe = ['ja-acc-save', 'ja-acc-test', 'ja-acc-del'];
        knoepfe.forEach(function (i) { if ($(i)) $(i).disabled = true; });
        accMeld(T('jaddon.acc_working', 'Einen Moment …'));
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
                                || T('jaddon.acc_fail', 'Vorgang fehlgeschlagen.'));
            }
            if (d.account) { _acc = d.account; accZeichnen(); }
            else if (d.info) { _acc = d.info; accZeichnen(); }
            else { await accLaden(); }
            // Das Token-Feld wird nach JEDEM Schreibzugriff geleert: es stuende
            // sonst im Klartext im Formular, und ein leeres Feld heisst beim
            // naechsten Speichern korrekt "unveraendert".
            if ($('ja-acc-token')) $('ja-acc-token').value = '';
            accMeld(typeof erfolgstext === 'function' ? erfolgstext(d) : erfolgstext, 'ok');
        } catch (e) {
            accMeld(e.message, 'error');
        } finally {
            knoepfe.forEach(function (i) { if ($(i)) $(i).disabled = false; });
        }
    }

    function accVerdrahten() {
        var sp = $('ja-acc-save');
        if (sp) sp.addEventListener('click', function () {
            var tok = ($('ja-acc-token') ? $('ja-acc-token').value : '').trim();
            var aktiv = !!($('ja-acc-aktiv') && $('ja-acc-aktiv').checked);
            if (!tok && !(_acc && _acc.vorhanden)) {
                accMeld(T('jaddon.acc_need_token',
                          'Bitte zuerst einen Token eintragen.'), 'error');
                return;
            }
            // Ein LEERES Feld wird gar nicht erst gesendet – "leer heisst
            // unveraendert" bleibt so eine Regel des Servers und nicht zwei.
            var rumpf = { aktiv: aktiv };
            if (tok) rumpf.api_token = tok;
            accRuf('/api/jira/account', 'POST', rumpf,
                   T('jaddon.acc_saved', '✓ Gespeichert.'));
        });

        var te = $('ja-acc-test');
        if (te) te.addEventListener('click', function () {
            accRuf('/api/jira/account/test', 'POST', null, function (d) {
                return T('jaddon.acc_test_ok', '✓ Verbindung steht – angemeldet als')
                       + ' ' + (d.anzeigename || d.konto || '?');
            });
        });

        var de = $('ja-acc-del');
        if (de) de.addEventListener('click', function () {
            // Eigener Dialog waere hier Aufwand ohne Gewinn: die Seite ist kein
            // Aufgabenfenster (dort ist `confirm` unterdrueckt), und es geht
            // kein Inhalt verloren – nur eine Einstellung, die man neu setzt.
            if (!window.confirm(T('jaddon.acc_del_ask',
                'Eigenen Jira-Token entfernen? Danach gilt wieder der gemeinsame Zugang.'))) return;
            accRuf('/api/jira/account', 'DELETE', null,
                   T('jaddon.acc_deleted', '✓ Entfernt – es gilt wieder der gemeinsame Zugang.'));
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
            var hd = h.ok ? await h.json() : null;
            zeigeAdresse(hd);
            paketBlock(hd);
            bereicheBlock(hd);
        } catch (e) {
            zeigeAdresse(null);
            // Ohne Auskunft bleibt der Download – der funktioniert immer.
            paketBlock(null);
            bereicheBlock(null);
        }

        // Der eigene Zugang wird IMMER geladen, auch wenn der Container zu
        // ist: die Pille am Titel ist der einzige Hinweis darauf, welcher
        // Zugang gerade gilt – und sie muss dastehen, BEVOR jemand aufklappt.
        accVerdrahten();
        accLaden();

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

        // Zustandsblock UND Paket-Block sind gerendert, nicht uebersetzt – nach
        // einem Sprachwechsel muessen sie neu gebaut werden, sonst bleiben sie
        // deutsch (der Paket-Block traegt die Knopf- und Kopiertexte).
        window.addEventListener('jarvis-lang-changed', function () {
            fetch('/api/jira/assist/health',
                  { headers: { 'Authorization': 'Bearer ' + token() } })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) { zeigeAdresse(d); paketBlock(d); bereicheBlock(d); })
                .catch(function () {});
            // Pille und Hinweiskasten des Zugangs werden ebenfalls GERENDERT,
            // nicht per data-i18n uebersetzt – ohne diese Zeile blieben sie
            // nach einem Sprachwechsel deutsch. KEIN Neuladen noetig, der
            // Zustand liegt schon vor.
            accZeichnen();
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
