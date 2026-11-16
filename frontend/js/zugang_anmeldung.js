/* Weitere Anmeldungen direkt nach der Anmeldung an Jarvis (2026-11-15).
 *
 * Vorgabe des Betreibers: Zugangsdaten nur noch an EINER Stelle eingeben. Wo
 * keine persoenliche Anmeldung fest hinterlegt werden darf (SAP/VEMAS:
 * Anmeldung ueber die Portal-Kachel; Jira/Confluence: "Persoenliche Zugaenge
 * erlauben" aus), zeigt die Anmeldemaske nach dem erfolgreichen Jarvis-Login
 * einen zweiten Schritt – nur fuer die Systeme, die der Server fuer DIESEN
 * Benutzer meldet (GET /api/zugaenge/anmeldung).
 *
 * Angemeldet wird ueber die VORHANDENEN Wege der Bereiche (SAP/VEMAS:
 * POST …/account + GET …/test, Jira/Confluence: POST …/account/sitzung) –
 * eine eigene Anmeldelogik hier liefe auseinander.
 *
 * DIE ANMELDUNG AN JARVIS IST NIE BLOCKIERT: fehlt die Auskunft oder scheitert
 * sie, geht es ohne zweiten Schritt weiter (fail-open in die harmlose
 * Richtung – angemeldet werden kann dann im Bereich).
 *
 * Merken im Browser ist BEWUSST NICHT eingebaut (docs/todo.md: Entscheidung
 * des Teams ausstehend). Die Felder tragen deshalb autocomplete="off".
 */
(function () {
    'use strict';

    var SYSTEME = {
        sap:        { name: 'SAP',        konto: '/api/sap/account',   test: '/api/sap/test' },
        vemas:      { name: 'VEMAS',      konto: '/api/vemas/account', test: '/api/vemas/test' },
        jira:       { name: 'Jira',       sitzung: '/api/jira/account/sitzung' },
        confluence: { name: 'Confluence', sitzung: '/api/confluence/account/sitzung' }
    };

    function T(key, fallback) {
        try {
            var v = window.t ? window.t(key) : '';
            return (v && v !== key) ? v : fallback;
        } catch (e) { return fallback; }
    }
    function $(id) { return document.getElementById(id); }

    /** Fehlertext aus einer Antwort: FastAPI meldet 401/403/422 in `detail`. */
    function fehlerAus(d, fallback) {
        if (d && typeof d.error === 'string' && d.error) return d.error;
        if (d && typeof d.detail === 'string' && d.detail) return d.detail;
        return fallback;
    }

    async function rufe(token, pfad, methode, rumpf) {
        var opt = { method: methode || 'GET',
                    headers: { 'Authorization': 'Bearer ' + token } };
        if (rumpf) {
            opt.headers['Content-Type'] = 'application/json';
            opt.body = JSON.stringify(rumpf);
        }
        var r = await fetch(pfad, opt);
        var d = null;
        try { d = await r.json(); } catch (e) { d = null; }
        return { ok: r.ok && !!d && d.ok !== false, d: d };
    }

    /** Eine Anmeldung ausfuehren. Rueckgabe: '' bei Erfolg, sonst der Grund. */
    async function anmelden(token, eintrag, benutzer, geheim) {
        var sys = SYSTEME[eintrag.system];
        if (!sys) return T('zg.unbekannt', 'Unbekanntes System.');
        if (sys.sitzung) {
            var a = await rufe(token, sys.sitzung, 'POST', { api_token: geheim });
            return a.ok ? '' : fehlerAus(a.d, T('zg.fehlgeschlagen', 'Anmeldung fehlgeschlagen.'));
        }
        var rumpf = {};
        rumpf[eintrag.feld] = geheim;
        // Den Benutzer nur senden, wenn er geaendert wurde – sonst schriebe
        // jede Anmeldung den Zugang neu, ohne dass sich etwas aendert.
        if (eintrag.benutzer_feld && benutzer && benutzer !== (eintrag.benutzer || '')) {
            rumpf[eintrag.benutzer_feld] = benutzer;
        }
        var s = await rufe(token, sys.konto, 'POST', rumpf);
        if (!s.ok) return fehlerAus(s.d, T('zg.fehlgeschlagen', 'Anmeldung fehlgeschlagen.'));
        // Erst der Test beweist die Anmeldung; bei einem Anmeldefehler hat der
        // Server sie bereits wieder verworfen (wie in /sap und /vemas).
        var t = await rufe(token, sys.test, 'GET');
        return t.ok ? '' : fehlerAus(t.d, T('zg.fehlgeschlagen', 'Anmeldung fehlgeschlagen.'));
    }

    function zeileBauen(e) {
        var sys = SYSTEME[e.system] || { name: e.system };
        var zeile = document.createElement('div');
        zeile.className = 'zg-zeile';
        zeile.setAttribute('data-system', e.system);

        // EINE Zeile je System (Vorgabe 2026-11-16): Name links, Felder rechts.
        // Der Status steht darunter ueber die ganze Breite und nimmt nur Platz
        // ein, wenn er etwas meldet (theme.css: .zg-status:empty).
        var name = document.createElement('span');
        name.className = 'zg-name';
        name.textContent = sys.name;
        zeile.appendChild(name);

        var felder = document.createElement('div');
        felder.className = 'zg-felder';
        if (e.art === 'kennwort' && e.benutzer_feld) {
            var u = document.createElement('input');
            u.type = 'text';
            u.className = 'zg-input zg-benutzer';
            u.autocomplete = 'off';
            u.value = e.benutzer || '';
            u.placeholder = T('zg.benutzer_ph', 'Benutzer');
            u.setAttribute('aria-label', sys.name + ' – ' + T('zg.benutzer_ph', 'Benutzer'));
            felder.appendChild(u);
        }
        var g = document.createElement('input');
        g.type = 'password';
        g.className = 'zg-input zg-geheim';
        g.autocomplete = 'off';
        var ph = (e.art === 'token' || e.feld === 'bearer_token' || e.feld === 'api_token')
            ? T('zg.token_ph', 'Persönlicher Token (PAT)')
            : T('zg.kennwort_ph', 'Kennwort');
        g.placeholder = ph;
        g.setAttribute('aria-label', sys.name + ' – ' + ph);
        felder.appendChild(g);
        zeile.appendChild(felder);

        var status = document.createElement('span');
        status.className = 'zg-status';
        zeile.appendChild(status);
        return zeile;
    }

    function statusSetzen(zeile, text, art) {
        var s = zeile.querySelector('.zg-status');
        if (!s) return;
        s.textContent = text || '';
        s.className = 'zg-status' + (art ? ' is-' + art : '');
    }

    /**
     * Zeigt den zweiten Schritt, falls noetig. Das Promise loest auf, sobald es
     * weitergehen kann (fertig, uebersprungen oder nichts zu tun) – NIE mit
     * einem Fehler.
     */
    async function schritt(token) {
        var box = $('zg-schritt'), liste = $('zg-liste');
        if (!token || !box || !liste) return;
        var eintraege = [];
        try {
            var a = await rufe(token, '/api/zugaenge/anmeldung', 'GET');
            eintraege = (a.ok && a.d && Array.isArray(a.d.anmeldungen)) ? a.d.anmeldungen : [];
        } catch (e) { eintraege = []; }
        eintraege = eintraege.filter(function (e) { return e && SYSTEME[e.system]; });
        if (!eintraege.length) return;

        liste.textContent = '';
        var zeilen = eintraege.map(function (e) {
            var z = zeileBauen(e);
            liste.appendChild(z);
            return { e: e, z: z, fertig: false };
        });

        var form = $('login-form');
        if (form) form.hidden = true;
        box.hidden = false;
        var erstes = liste.querySelector('.zg-geheim');
        if (erstes) { try { erstes.focus(); } catch (e) { /* belanglos */ } }

        var meld = $('zg-meldung'), weiter = $('zg-weiter'), skip = $('zg-ueberspringen');
        function meldung(text, art) {
            if (!meld) return;
            meld.textContent = text || '';
            meld.className = 'zg-meldung' + (art ? ' is-' + art : '');
            meld.hidden = !text;
        }

        await new Promise(function (fertig) {
            var laeuft = false;
            function ende() {
                if (weiter) weiter.removeEventListener('click', absenden);
                if (skip) skip.removeEventListener('click', ende);
                liste.removeEventListener('keydown', taste);
                fertig();
            }
            async function absenden() {
                if (laeuft) return;
                laeuft = true;
                if (weiter) weiter.disabled = true;
                meldung('');
                var fehler = 0;
                for (var i = 0; i < zeilen.length; i++) {
                    var r = zeilen[i];
                    if (r.fertig) continue;
                    var gEl = r.z.querySelector('.zg-geheim');
                    var uEl = r.z.querySelector('.zg-benutzer');
                    var geheim = gEl ? gEl.value : '';
                    // Leer gelassen = dieses System jetzt nicht anmelden.
                    if (!geheim) { statusSetzen(r.z, ''); continue; }
                    statusSetzen(r.z, T('zg.laeuft', 'Melde an …'));
                    var grund;
                    try {
                        grund = await anmelden(token, r.e, uEl ? uEl.value.trim() : '', geheim);
                    } catch (e) {
                        grund = T('zg.verbindung', 'Keine Verbindung zum Server.');
                    }
                    // Das Geheimnis bleibt nach keinem Versuch im Formular stehen.
                    if (gEl) gEl.value = '';
                    if (grund) {
                        fehler++;
                        statusSetzen(r.z, grund, 'fehler');
                    } else {
                        r.fertig = true;
                        statusSetzen(r.z, '✓ ' + T('zg.angemeldet', 'angemeldet'), 'ok');
                        r.z.querySelectorAll('input').forEach(function (x) { x.disabled = true; });
                    }
                }
                laeuft = false;
                if (weiter) weiter.disabled = false;
                if (fehler) {
                    meldung(T('zg.teilweise', 'Nicht alle Anmeldungen sind gelungen. Korrigieren und erneut anmelden – oder überspringen und später im Bereich anmelden.'), 'fehler');
                    return;
                }
                ende();
            }
            function taste(ev) {
                if (ev.key === 'Enter') { ev.preventDefault(); absenden(); }
            }
            if (weiter) weiter.addEventListener('click', absenden);
            if (skip) skip.addEventListener('click', ende);
            liste.addEventListener('keydown', taste);
        });
        // Zurueck in den Grundzustand: ohne das stuende nach einer spaeteren
        // Abmeldung (gleiche Seite, /settings) der zweite Schritt statt des
        // Anmeldeformulars da.
        liste.textContent = '';
        meldung('');
        box.hidden = true;
        if (form) form.hidden = false;
    }

    window.ZugangAnmeldung = { schritt: schritt };
})();
