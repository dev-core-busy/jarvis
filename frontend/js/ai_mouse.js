/**
 * Anleitungs- und Downloadseite fuer AI Mouse (/ai-mouse).
 *
 * Die Seite ist eine LEERE HUELLE: eine Navigation traegt keinen
 * Authorization-Header, die Berechtigung kann also nicht in der Route geprueft
 * werden. Hier wird /api/me geholt und wer nicht darf, landet auf dem Portal –
 * die DATEN liegen ausschliesslich hinter require_aimouse_access.
 */
(function () {
    'use strict';

    var _health = null;

    function tok() {
        try { return localStorage.getItem('jarvis_token') || ''; } catch (e) { return ''; }
    }

    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function hole(pfad, opt) {
        var o = opt || {};
        o.headers = o.headers || {};
        o.headers['Authorization'] = 'Bearer ' + tok();
        return fetch(pfad, o);
    }

    /** Fehlertext aus einer Serverantwort. Jarvis benutzt `error`, FastAPI
     *  `detail` – nur eines zu lesen laesst eine vorhandene Begruendung
     *  verschwinden (dieselbe Stelle wie in `_fehlertext` der uebrigen Module). */
    function fehlertext(d, rueckfall) {
        if (!d) { return rueckfall; }
        return d.error || d.detail || d.message || rueckfall;
    }

    function t(key, fallback) {
        return (window.t ? window.t(key, fallback) : fallback) || fallback;
    }

    // ── Aufklappbare Container ──────────────────────────────────────────────
    //
    // Bauform aus /email (`email_portal.js::klappInit`). Gespeichert werden die
    // ZUGEKLAPPTEN: so ist die Vorgabe fuer einen neuen Benutzer „alles offen",
    // und ein spaeter ergaenzter Container ist automatisch offen statt still
    // versteckt.
    var KLAPP_SPEICHER = 'jarvis_aimouse_zu';

    function klappZustand() {
        try {
            var roh = JSON.parse(localStorage.getItem(KLAPP_SPEICHER) || '[]');
            return Array.isArray(roh) ? roh.filter(function (x) { return typeof x === 'string'; }) : [];
        } catch (e) {
            // Ein kaputter Speicherstand darf nicht dazu fuehren, dass gar
            // nichts mehr aufklappt.
            return [];
        }
    }

    function klappMerken(liste) {
        try { localStorage.setItem(KLAPP_SPEICHER, JSON.stringify(liste)); }
        catch (e) { /* privater Modus: der Zustand gilt dann nur fuer diese Seite */ }
    }

    function klappSetzen(karte, zu) {
        karte.classList.toggle('is-zu', !!zu);
        var kopf = karte.querySelector('.ja-card-head');
        if (kopf) { kopf.setAttribute('aria-expanded', zu ? 'false' : 'true'); }
    }

    function klappUmschalten(karte) {
        var id = karte.getAttribute('data-klapp');
        var zu = !karte.classList.contains('is-zu');
        klappSetzen(karte, zu);
        var liste = klappZustand().filter(function (x) { return x !== id; });
        if (zu) { liste.push(id); }
        klappMerken(liste);
    }

    function klappInit() {
        var zu = klappZustand();
        document.querySelectorAll('.ja-card[data-klapp]').forEach(function (karte) {
            var kopf = karte.querySelector('.ja-card-head');
            if (!kopf) { return; }
            klappSetzen(karte, zu.indexOf(karte.getAttribute('data-klapp')) >= 0);
            kopf.addEventListener('click', function (ev) {
                // ⚠ OHNE DIESE AUSNAHME klappt jeder Knopf in der Kopfzeile den
                // Container zu. Heute steht dort nur der Titel – wer spaeter
                // einen Knopf ergaenzt, waere sonst ratlos (Projektregel).
                if (ev.target.closest('button, input, label, a, select, textarea')) { return; }
                klappUmschalten(karte);
            });
            // Mit der Tastatur bedienbar: das Element ist ein role="button",
            // also muessen Enter und Leertaste wirken.
            kopf.addEventListener('keydown', function (ev) {
                if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
                    ev.preventDefault();
                    klappUmschalten(karte);
                }
            });
        });
    }

    // ── Download-Knopf ──────────────────────────────────────────────────────
    //
    // Der Block „Zustand" ist am 2026-09-09 auf Vorgabe entfallen. Was daraus
    // BLEIBEN musste, ist die Sperre des Knopfes: ein Knopf, der zuverlaessig
    // in eine Fehlermeldung fuehrt, ist schlechter als ein abgeblendeter mit
    // Begruendung (Register).
    // Fuer den Waechter: er muss den Fall "kein Paket gebaut" herstellen
    // koennen, ohne den Server dazu zu bringen.
    window.__amHealth = function (h) { _health = h; downloadKnopfSetzen(); };

    function downloadKnopfSetzen() {
        var dl = document.getElementById('am-download');
        if (!dl || !_health) { return; }
        dl.disabled = !_health.paket_bereit;
        // Der Grund gehoert an den Knopf – sonst ist „grau" unerklaerlich.
        dl.title = _health.paket_bereit ? '' : t('aimouse.st_no_pkg',
            'Die Anwendung wird auf diesem Server gerade gebaut – der Download steht danach bereit.');
    }

    /** Bereiche nur fuer Administratoren – und nur die FREIGESCHALTETEN.
     *  Die uebrigen aufzuzaehlen waere eine Liste von Dingen, die nicht gelten. */
    function bereicheZeichnen(istAdmin) {
        var karte = document.getElementById('am-bereiche-card');
        var box = document.getElementById('am-bereiche');
        if (!karte || !box || !_health) { return; }
        var frei = (_health.bereiche || []).filter(function (b) { return b.freigegeben; });
        if (!istAdmin || frei.length === 0) { return; }
        karte.classList.remove('hidden');
        box.innerHTML = frei.map(function (b) {
            return '<div class="am-bereich"><strong>' + esc(b.name) + '</strong>'
                + '<div class="ja-note">' + esc(b.hinweis) + '</div></div>';
        }).join('');
    }

    // ── Download ────────────────────────────────────────────────────────────
    // Als BLOB, nicht als <a href> mit ?token=: ein Link braeuchte das Token in
    // der Adresse, und das stuende dann in der Adresszeile, im Verlauf und in
    // jedem Proxy-Log (dieselbe Wahl wie beim Paket der Jira-Erweiterung).
    function herunterladen() {
        var knopf = document.getElementById('am-download');
        var msg = document.getElementById('am-download-msg');
        if (!knopf || knopf.disabled) { return; }
        var alt = knopf.textContent;
        knopf.disabled = true;
        knopf.textContent = t('aimouse.get_running', 'Wird zusammengestellt…');
        if (msg) { msg.textContent = ''; }

        hole('/api/ai-mouse/paket').then(function (r) {
            if (!r.ok) {
                return r.json().catch(function () { return null; }).then(function (d) {
                    throw new Error(fehlertext(d, 'HTTP ' + r.status));
                });
            }
            // Den Dateinamen aus dem Kopf nehmen: er traegt die Marke, damit auf
            // einem Arbeitsplatz nicht mehrere gleichnamige ZIPs liegen.
            var name = 'ai-mouse.zip';
            var cd = r.headers.get('Content-Disposition') || '';
            var m = cd.match(/filename="([^"]+)"/);
            if (m) { name = m[1]; }
            return r.blob().then(function (b) { return [name, b]; });
        }).then(function (paar) {
            var url = URL.createObjectURL(paar[1]);
            var a = document.createElement('a');
            a.href = url;
            a.download = paar[0];
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            // Erst nach dem Klick freigeben – vorher ist die Adresse tot.
            setTimeout(function () { URL.revokeObjectURL(url); }, 60000);
            if (msg) { msg.textContent = t('aimouse.get_ok', 'Heruntergeladen: ') + paar[0]; }
        }).catch(function (e) {
            // Ein Fehlschlag bleibt STEHEN – einen Erfolg kann man verpassen,
            // eine Fehlerursache muss man lesen und oft kopieren koennen.
            if (msg) { msg.textContent = String(e.message || e); }
        }).finally(function () {
            knopf.disabled = !(_health && _health.paket_bereit);
            knopf.textContent = alt;
        });
    }

    // ── Fragen ──────────────────────────────────────────────────────────────
    // Sie lagen bis 2026-09-09 als prompts.json neben der Exe. Jetzt hier: sie
    // folgen dem BENUTZER, nicht dem Rechner.
    var _fragen = [];
    var _istAdmin = false;

    function fragenLaden() {
        return hole('/api/ai-mouse/fragen')
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                _fragen = (d && d.fragen) || [];
                fragenZeichnen();
            })
            .catch(function () { /* Liste bleibt, wie sie war */ });
    }

    // ── Die Fragenliste ─────────────────────────────────────────────────────
    //
    // Bauform der Regelliste aus /email (Vorgabe 2026-09-09). Zwei Dinge machen
    // sie aus: eine KARTE je Eintrag, und ein Formular, das UNTER der jeweiligen
    // Zeile aufgeht – nicht am Ende der Liste, wo man den Bezug verliert.

    /** Heimatplatz des Formulars – NUR beim ersten Verschieben gemerkt.
     *  Ein erneutes Auslesen wuerde die verschobene Position als „Heimat"
     *  festschreiben (Register: Rollen-Formular, Extraktions-Vorschau). */
    var _formHeim = null;
    /** Welcher Eintrag gerade bearbeitet wird ('' = keiner, 'neu' = Anlegen). */
    var _editId = '';

    /** Das Formular heimholen, BEVOR die Liste neu gebaut wird.
     *  Ohne das loescht `box.innerHTML = …` es mit – es haengt dann ja in einer
     *  Karte, die gerade ersetzt wird. */
    // Fuer den Waechter erreichbar: er muss ein Neuzeichnen ausloesen koennen,
    // um zu pruefen, dass ein offenes Formular das ueberlebt.
    window.__amFragenZeichnen = function () { fragenZeichnen(); };

    function formHeimholen() {
        var form = document.getElementById('am-frage-form');
        if (!form || !_formHeim) { return; }
        if (form.parentNode !== _formHeim) { _formHeim.appendChild(form); }
    }

    function fragenZeichnen() {
        formHeimholen();
        var box = document.getElementById('am-fragen');
        if (!box) { return; }
        if (!_fragen.length) {
            box.innerHTML = '<div class="am-q-empty">'
                + esc(t('aimouse.q_none',
                    'Noch keine eigene Frage. Mit „Neue Frage" anfangen – zum Beispiel: '
                    + '„Fasse den markierten Text in drei Stichpunkten zusammen."'))
                + '</div>';
            if (_editId === 'neu') { formZeigen(null, null); }
            return;
        }
        box.innerHTML = _fragen.map(function (f) {
            // ⚠ KEIN Stift-SYMBOL aus JarvisIcons: das kennt nur trash/close/
            // eye/eyeOff/lupe. `JarvisIcons.pencil()` waere ein TypeError
            // mitten im Rendern – der landet im catch, die Liste bliebe leer.
            // Das ✎ ist ein Textzeichen, kein Emoji (folgt dem Theme).
            var acts = f.darf_aendern
                ? '<button class="am-q-btn" data-act="edit" title="'
                  + esc(t('common.edit', 'Bearbeiten')) + '" aria-label="'
                  + esc(t('common.edit', 'Bearbeiten')) + '">✎</button>'
                  + '<button class="am-q-btn is-danger" data-act="del" title="'
                  + esc(t('common.delete', 'Löschen')) + '" aria-label="'
                  + esc(t('common.delete', 'Löschen')) + '">'
                  + (window.JarvisIcons ? JarvisIcons.trash() : '') + '</button>'
                : '';
            return '<div class="am-q-card" data-qid="' + esc(f.id) + '">'
                + '<div class="am-q-row">'
                + '<div class="am-q-main">'
                + '<div class="am-q-name">' + esc(f.titel)
                // Farbe UND Wort – die Marke sagt, warum der Eintrag keine
                // Knoepfe hat (Farbe allein ist keine Information).
                + (f.gemeinsam ? '<span class="am-q-badge">'
                    + esc(t('aimouse.q_shared', 'für alle')) + '</span>' : '')
                + '</div>'
                + '<div class="am-q-meta" title="' + esc(f.prompt) + '">'
                + esc(f.prompt) + '</div>'
                + '</div>'
                + '<div class="am-q-acts">' + acts + '</div>'
                + '</div></div>';
        }).join('');

        // Gebunden wird nach jedem Zeichnen: die Knoepfe sind neue Elemente.
        box.querySelectorAll('.am-q-btn').forEach(function (b) {
            b.addEventListener('click', function () {
                var karte = b.closest('.am-q-card');
                var id = karte && karte.getAttribute('data-qid');
                var f = _fragen.filter(function (x) { return x.id === id; })[0];
                if (!f) { return; }
                if (b.getAttribute('data-act') === 'del') { return frageLoeschen(id); }
                // Ein zweiter Klick auf dieselbe Zeile SCHLIESST – sonst tut
                // der Knopf sichtbar nichts (Register: Jira-Vorlagen).
                return (_editId === id) ? formZu() : formZeigen(f, karte);
            });
        });

        // Ein offenes Formular wieder unter SEINE Zeile setzen. Das <div> ist
        // nach dem Neuaufbau ein anderes Element – wiedergefunden ueber die
        // Kennung, nicht ueber eine gemerkte Referenz.
        if (_editId && _editId !== 'neu') {
            var k = box.querySelector('.am-q-card[data-qid="' + _editId + '"]');
            var ff = _fragen.filter(function (x) { return x.id === _editId; })[0];
            if (k && ff) { formZeigen(ff, k); }
            else { formZu(); }   // die Frage gibt es nicht mehr
        }
    }

    /** Formular oeffnen und unter die Karte haengen.
     *  `karte === null` heisst „neue Frage" – dann bleibt es an seinem
     *  Heimatplatz unter der Liste. */
    function formZeigen(f, karte) {
        var form = document.getElementById('am-frage-form');
        if (!form) { return; }
        if (!_formHeim) { _formHeim = form.parentNode; }
        _editId = f ? f.id : 'neu';

        form.classList.remove('hidden');
        form.hidden = false;
        form.dataset.id = (f && f.id) || '';

        // Das Formular wird GEBAUT, nicht im Markup vorgehalten: es wandert
        // zwischen den Karten, und ein vorgehaltener Block muesste beim
        // Verschieben trotzdem jedes Feld neu belegen. Fremdtext ausschliesslich
        // ueber `esc` bzw. `value`-Zuweisung – die Titel kommen von Benutzern.
        form.innerHTML =
            '<div class="am-q-feld"><label for="am-f-titel">'
            + esc(t('aimouse.q_titel', 'Titel (steht im Menü)')) + '</label>'
            + '<input type="text" id="am-f-titel" maxlength="80"></div>'
            + '<div class="am-q-feld"><label for="am-f-prompt">'
            + esc(t('aimouse.q_prompt', 'Anweisung an das Modell')) + '</label>'
            + '<textarea id="am-f-prompt" rows="4" maxlength="2000"></textarea>'
            + '<span class="am-q-hint">'
            + esc(t('aimouse.q_prompt_hint',
                'Sie wird zusammen mit dem Bildausschnitt an das Modell geschickt.'))
            + '</span></div>'
            + (_istAdmin
                ? '<label class="am-q-gem"><input type="checkbox" id="am-f-gemeinsam">'
                  + '<span>' + esc(t('aimouse.q_gem',
                      'Für alle Benutzer (nur Administratoren)')) + '</span></label>'
                : '')
            // ⚠ `.ja-btn`, NICHT `.btn-primary`/`.btn-secondary`: /ai-mouse laedt
            // style.css nicht, diese Klassen sind hier also unbekannt und die
            // Knoepfe waeren nackte Browser-Standardknoepfe. `ja-btn-haupt`
            // markiert die Hauptaktion der Gruppe (Muster des Jira-Zugangs).
            + '<div class="am-q-acts-form">'
            + '<button type="button" class="ja-btn ja-btn-haupt" id="am-f-save">'
            + esc(t('aimouse.q_save', 'Speichern')) + '</button>'
            + '<button type="button" class="ja-btn" id="am-f-cancel">'
            + esc(t('aimouse.q_cancel', 'Abbrechen')) + '</button>'
            + '<span id="am-f-status" style="font-size:0.9em;"></span>'
            + '</div>';

        // Werte NICHT ins Markup interpolieren: ein Anführungszeichen im Titel
        // sprengte sonst das Attribut (Register: die Administratoren-Oberfläche
        // hält das Sitzungstoken im localStorage).
        document.getElementById('am-f-titel').value = (f && f.titel) || '';
        document.getElementById('am-f-prompt').value = (f && f.prompt) || '';
        // Das Kästchen gibt es nur für Administratoren – für alle anderen wäre
        // es ein Bedienelement, das zuverlässig in eine Absage führt.
        var gem = document.getElementById('am-f-gemeinsam');
        if (gem) { gem.checked = !!(f && f.gemeinsam); }
        document.getElementById('am-f-save').addEventListener('click', frageSpeichern);
        document.getElementById('am-f-cancel').addEventListener('click', formZu);

        if (karte) { karte.appendChild(form); }
        else if (_formHeim && form.parentNode !== _formHeim) { _formHeim.appendChild(form); }
        document.getElementById('am-f-titel').focus();
    }

    function formZu() {
        var form = document.getElementById('am-frage-form');
        _editId = '';
        if (!form) { return; }
        form.classList.add('hidden');
        form.hidden = true;
        form.dataset.id = '';
        // Heimholen ist Pflicht, nicht Ordnung: bleibt es in einer Karte
        // haengen, loescht der naechste Neuaufbau der Liste es mit.
        formHeimholen();
    }

    function frageSpeichern() {
        var form = document.getElementById('am-frage-form');
        var st = document.getElementById('am-f-status');
        if (!form) { return; }
        st.textContent = t('common.saving', 'Speichere…');
        hole('/api/ai-mouse/fragen', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id: form.dataset.id || '',
                titel: document.getElementById('am-f-titel').value,
                prompt: document.getElementById('am-f-prompt').value,
                // Ohne Admin-Rechte gibt es das Kaestchen gar nicht.
                gemeinsam: !!(document.getElementById('am-f-gemeinsam') || {}).checked
            })
        }).then(function (r) {
            return r.json().then(function (d) {
                if (!r.ok || !d.ok) { throw new Error(fehlertext(d, 'HTTP ' + r.status)); }
                return d;
            });
        }).then(function () {
            formZu();
            return fragenLaden();
        }).catch(function (e) {
            // Der Fehler bleibt STEHEN – er nennt den Grund (leerer Titel,
            // Deckel erreicht, keine Admin-Rechte).
            st.textContent = String(e.message || e);
        });
    }

    function frageLoeschen(id) {
        var f = _fragen.filter(function (x) { return x.id === id; })[0];
        // Die Rückfrage nennt den TITEL: bei zwei ähnlichen Fragen ist sonst
        // nicht erkennbar, welche gemeint ist.
        if (!confirm(t('aimouse.q_del_q', 'Frage „{t}" wirklich löschen?')
                .replace('{t}', (f && f.titel) || '?'))) { return; }
        hole('/api/ai-mouse/fragen/' + encodeURIComponent(id), { method: 'DELETE' })
            .then(function () { return fragenLaden(); })
            .catch(function () { /* Liste bleibt */ });
    }

    function fragenBinden() {
        var neu = document.getElementById('am-frage-neu');
        if (neu) { neu.addEventListener('click', function () {
            // Ein zweiter Klick schliesst – wie bei den Regeln.
            return (_editId === 'neu') ? formZu() : formZeigen(null, null);
        }); }
    }

    // ── Start ───────────────────────────────────────────────────────────────
    function start() {
        var app = document.getElementById('am-app');
        if (!tok()) { location.replace('/'); return; }

        // ⚠ VOR dem /api/me-Abruf: die Container stehen im Markup und sollen
        // ihren gemerkten Zustand sofort haben – nicht erst, wenn der Server
        // geantwortet hat. Sonst klappen sie sichtbar zu, nachdem die Seite
        // schon dastand.
        klappInit();

        hole('/api/me').then(function (r) {
            if (!r.ok) { throw new Error('auth'); }
            return r.json();
        }).then(function (me) {
            // Freigabe UND aktiver Skill – der Server hat beides schon
            // verrechnet. Wer nicht darf, sieht die Seite gar nicht erst.
            if (!me.permissions || !me.permissions.ai_mouse) {
                location.replace('/portal');
                return null;
            }
            if (app) { app.classList.remove('hidden'); }
            _istAdmin = !!me.is_admin;
            var sb = document.getElementById('am-settings-btn');
            if (sb && me.is_admin) { sb.style.display = ''; }
            fragenBinden();
            fragenLaden();

            var sprache = (window.getLang && window.getLang()) || 'de';
            return hole('/api/ai-mouse/health?lang=' + encodeURIComponent(sprache))
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (h) {
                    _health = h;
                    downloadKnopfSetzen();
                    bereicheZeichnen(!!me.is_admin);
                });
        }).catch(function () {
            location.replace('/');
        });

        var dl = document.getElementById('am-download');
        if (dl) { dl.addEventListener('click', herunterladen); }

        var portal = document.getElementById('am-portal-btn');
        if (portal) { portal.addEventListener('click', function () { location.href = '/portal'; }); }

        var logout = document.getElementById('am-logout-btn');
        if (logout) {
            logout.addEventListener('click', function () {
                // Das Abmelde-Signal MUSS raus, bevor das Token verworfen wird,
                // und braucht keepalive: die Seite navigiert unmittelbar danach
                // weg (Anwesenheits-Buchhaltung, Register).
                try {
                    fetch('/api/logout', {
                        method: 'POST', keepalive: true,
                        headers: { 'Authorization': 'Bearer ' + tok() }
                    });
                } catch (e) { /* Abmelden darf am Signal nicht scheitern. */ }
                try { localStorage.removeItem('jarvis_token'); } catch (e) { }
                location.replace('/');
            });
        }

        // Der Zustand kommt uebersetzt vom Server (Name und Hinweis stehen dort
        // neben der Werkzeugliste, damit Text und Wirkung nicht auseinander
        // laufen). applyLang() erreicht ihn deshalb nicht – bei einem
        // Sprachwechsel wird er neu geholt.
        window.addEventListener('jarvis-lang-changed', function () {
            var sprache = (window.getLang && window.getLang()) || 'de';
            hole('/api/ai-mouse/health?lang=' + encodeURIComponent(sprache))
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (h) {
                    if (!h) { return; }
                    _health = h;
                    downloadKnopfSetzen();
                    var karte = document.getElementById('am-bereiche-card');
                    bereicheZeichnen(karte && !karte.classList.contains('hidden'));
                });
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
