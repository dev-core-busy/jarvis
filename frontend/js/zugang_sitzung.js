/* Anmeldung fuer die Sitzung in den Bereichen Jira und Confluence (2026-11-15).
 *
 * Ist "Persoenliche Zugaenge erlauben" AUS, liegt kein persoenlicher Token auf
 * dem Server, und der Abschnitt "Mein …-Zugang" ist ausgeblendet. Statt dessen
 * zeigt dieser Abschnitt – Vorbild ist die SAP-Anmeldung ueber die
 * Portal-Kachel –, ob der Benutzer fuer die Sitzung angemeldet ist, und bietet
 * Anmelden und ABMELDEN an. Angemeldet werden kann auch im zweiten Schritt der
 * Jarvis-Anmeldung (zugang_anmeldung.js); abgemeldet wird hier, bei der
 * Jarvis-Abmeldung oder nach Ablauf.
 *
 * EIN Modul fuer beide Seiten: /jira-addon und /confluence-addon sollen sich
 * gleich verhalten; zwei Kopien liefen beim naechsten Feinschliff auseinander.
 *
 * Markup je Seite (Praefix p = "ja" bzw. "ca"): #p-sz-sect, #p-sz-pill,
 * #p-sz-note, #p-sz-token, #p-sz-login, #p-sz-logout, #p-sz-msg, dazu die
 * Pille #p-sz-kopf – seit 2026-11-16 in der Box „Angemeldet als …“ ueber
 * den Containern, nicht mehr in der Titelleiste.
 */
(function () {
    'use strict';

    function T(key, fallback) {
        try {
            var v = window.t ? window.t(key) : '';
            return (v && v !== key) ? v : fallback;
        } catch (e) { return fallback; }
    }

    function uhrzeit(ts) {
        try {
            return new Date(ts * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        } catch (e) { return ''; }
    }

    /**
     * @param {object} o  { praefix, name, pfad, token: fn, nachher: fn(account) }
     * @returns {{zeichnen: function(object)}}
     */
    function einrichten(o) {
        var $ = function (s) { return document.getElementById(o.praefix + '-sz-' + s); };
        var _acc = null;

        function meld(text, art) {
            var p = $('msg');
            if (!p) return;
            if (!text) { p.hidden = true; p.textContent = ''; return; }
            p.textContent = text;                       // Servertext: nie als HTML
            p.style.color = (art === 'error') ? 'var(--danger)'
                : (art === 'ok' ? 'var(--success)' : '');
            p.hidden = false;
        }

        function zeichnen(a) {
            _acc = a || null;
            var sect = $('sect');
            // Nur im Sitzungsbetrieb ("Persoenliche Zugaenge erlauben" aus) –
            // sonst gilt der gespeicherte Token aus "Mein …-Zugang".
            var an = !!(a && a.sitzungs_modus);
            if (sect) sect.style.display = an ? '' : 'none';
            // Kopf-Pille wie auf /sap und /vemas: sichtbar NUR, wenn im
            // Sitzungsbetrieb keine Anmeldung besteht; leer blendet sie aus.
            var kopf = $('kopf');
            if (kopf) {
                var fehlt = an && !a.angemeldet;
                kopf.className = 'ja-conn' + (fehlt ? ' is-off' : '');
                kopf.textContent = fehlt
                    ? T('zs.kopf_aus', 'Nicht bei {name} angemeldet').replace('{name}', o.name)
                    : '';
                kopf.title = fehlt ? T('zs.nicht_an', 'Nicht angemeldet – es gilt der gemeinsame Zugang.') : '';
            }
            if (!an) return;
            var angemeldet = !!a.angemeldet;

            var pill = $('pill');
            if (pill) {
                pill.className = 'ja-acc-pill' + (angemeldet ? ' is-own' : '');
                pill.textContent = angemeldet ? T('zs.pill_an', 'angemeldet')
                                              : T('zs.pill_aus', 'gemeinsamer Zugang');
            }
            var note = $('note');
            if (note) {
                var zeilen = [];
                if (angemeldet) {
                    var wer = a.sitzung_anzeigename || a.sitzung_konto || '';
                    if (wer) {
                        zeilen.push(T('zs.als', 'Angemeldet als:') + ' ' + wer
                            + (a.sitzung_konto && a.sitzung_anzeigename ? ' (' + a.sitzung_konto + ')' : ''));
                    }
                    if (a.sitzung_bis) {
                        zeilen.push(T('zs.bis', 'Die Anmeldung gilt bis') + ' ' + uhrzeit(a.sitzung_bis)
                            + ' ' + T('zs.bis_nach', 'Uhr oder bis zur Abmeldung.'));
                    }
                } else {
                    zeilen.push(T('zs.nicht_an', 'Nicht angemeldet – es gilt der gemeinsame Zugang.'));
                }
                if (!a.server_konfiguriert) {
                    zeilen.push(T('zs.kein_server', 'Es ist keine Serveradresse hinterlegt – ein Administrator muss sie eintragen.'));
                }
                note.textContent = '';
                zeilen.forEach(function (z) {
                    var d = document.createElement('div');
                    d.textContent = z;
                    note.appendChild(d);
                });
                note.classList.toggle('is-on', zeilen.length > 0);
            }
            var tok = $('token');
            if (tok) { tok.disabled = angemeldet; if (angemeldet) tok.value = ''; }
            var li = $('login');
            if (li) li.disabled = angemeldet || !a.server_konfiguriert;
            var lo = $('logout');
            if (lo) lo.disabled = !angemeldet;
        }

        async function ruf(methode, rumpf, erfolg) {
            var knoepfe = [$('login'), $('logout')];
            knoepfe.forEach(function (b) { if (b) b.disabled = true; });
            meld(T('zs.arbeitet', 'Einen Moment …'));
            try {
                var opt = { method: methode, headers: { 'Authorization': 'Bearer ' + o.token() } };
                if (rumpf) {
                    opt.headers['Content-Type'] = 'application/json';
                    opt.body = JSON.stringify(rumpf);
                }
                var r = await fetch(o.pfad, opt);
                var d = null;
                try { d = await r.json(); } catch (e) { d = null; }
                if (!r.ok || !d || d.ok === false) {
                    throw new Error((d && (d.error || d.detail)) || T('zs.fehler', 'Vorgang fehlgeschlagen.'));
                }
                meld(erfolg, 'ok');
                if (d.account) {
                    zeichnen(d.account);
                    if (typeof o.nachher === 'function') o.nachher(d.account);
                }
            } catch (e) {
                meld(e.message, 'error');
                zeichnen(_acc);
            } finally {
                // Der Token bleibt nach keinem Versuch im Feld stehen.
                var t = $('token'); if (t) t.value = '';
            }
        }

        function anmelden() {
            var t = $('token');
            var wert = t ? t.value.trim() : '';
            if (!wert) { meld(T('zs.token_fehlt', 'Bitte den persönlichen Token (PAT) eingeben.'), 'error'); return; }
            ruf('POST', { api_token: wert }, T('zs.ok_an', '✓ Angemeldet – der Token gilt für diese Sitzung.'));
        }

        var li = $('login');
        if (li) li.addEventListener('click', anmelden);
        var t = $('token');
        if (t) t.addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter') { ev.preventDefault(); anmelden(); }
        });
        var lo = $('logout');
        if (lo) lo.addEventListener('click', function () {
            ruf('DELETE', null, T('zs.ok_ab', '✓ Abgemeldet – es gilt wieder der gemeinsame Zugang.'));
        });
        // Pille und Hinweise sind gerendert, nicht ueber data-i18n gesetzt.
        window.addEventListener('jarvis-lang-changed', function () { if (_acc) zeichnen(_acc); });

        return { zeichnen: zeichnen };
    }

    window.ZugangSitzung = { einrichten: einrichten };
})();
