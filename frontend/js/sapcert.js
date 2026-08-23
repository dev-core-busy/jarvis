/* Serverzertifikat eines SAP-Systems pruefen und verankern.
 *
 * EINE Datei fuer BEIDE Oberflaechen – Einstellungen → SAP (Sammelzugang) und
 * /sap → Mein SAP-Zugang (persoenlicher Zugang). Zwei Fassungen desselben
 * Bausteins waeren in drei Wochen auseinandergelaufen; hier unterscheidet nur
 * die Endpunkt-Basis (`/api/sap/admin/cert` gegen `/api/sap/cert`).
 *
 * Der Baustein rendert sich selbst in einen leeren Container. Die Seiten
 * liefern nur `<div class="sapcert" data-kanal="odata">` – so muss ein neuer
 * Kanal nur einmal beschrieben werden.
 *
 * WICHTIG: Alle Angaben im Ergebnis kommen vom FREMDEN Server (Aussteller,
 * Inhaber, Namen). Sie werden ausschliesslich per textContent gesetzt, nie per
 * innerHTML – sonst waere ein praeparierter Zertifikatsname ein Skript in der
 * Administratoren-Oberflaeche, wo das Sitzungstoken liegt.
 */
(function () {
    'use strict';

    function T(key, fb) {
        try { if (window.t) { var s = window.t(key); if (s && s !== key) return s; } }
        catch (e) { /* i18n noch nicht geladen */ }
        return fb;
    }

    function authHeaders(extra) {
        var tok = localStorage.getItem('jarvis_token')
            || localStorage.getItem('jarvis_chat_token')
            || localStorage.getItem('jarvis_uc_token') || '';
        var h = extra || {};
        if (tok) h['Authorization'] = 'Bearer ' + tok;
        return h;
    }

    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text !== undefined && text !== null) e.textContent = String(text);
        return e;
    }

    function fpKurz(fp) {
        // Der volle Fingerabdruck steht im Kasten; in der Zustandszeile reichen
        // die ersten Gruppen – vollstaendig waere sie 71 Zeichen lang.
        var s = String(fp || '').replace(/^sha256:/, '');
        return s ? s.slice(0, 16) + '…' : '';
    }

    function datum(ts) {
        if (!ts) return '';
        try { return new Date(Number(ts) * 1000).toLocaleString(); }
        catch (e) { return ''; }
    }

    /* opts:
     *   basis   – '/api/sap/admin/cert' oder '/api/sap/cert'
     *   kanal   – 'odata' | 'hana'
     *   ziel()  – liefert {url:…} bzw. {host:…, port:…} aus den Formularfeldern
     *   gebunden() – aktuell gespeicherter Anker (dict aus sap_cert.info) oder {}
     *   fremd()    – optional: Anker des Administrators, nur zur Anzeige
     *   nachAenderung(antwort) – nach Verankern/Loesen (Formular neu laden)
     */
    function mount(container, opts) {
        if (!container || container.dataset.sapcertReady === '1') return null;
        container.dataset.sapcertReady = '1';
        container.classList.add('sapcert');

        var zeile = el('div', 'sapcert-row');
        var btnPruef = el('button', 'sapcert-btn',
            T('sapcert.check', 'Zertifikat prüfen'));
        btnPruef.type = 'button';
        var stand = el('span', 'sapcert-state');
        zeile.appendChild(btnPruef);
        zeile.appendChild(stand);
        var kasten = el('div', 'sapcert-box');
        kasten.hidden = true;
        container.appendChild(zeile);
        container.appendChild(kasten);

        var letzte = null;   // zuletzt geprueftes Zertifikat

        function melde(text, art) {
            stand.textContent = text || '';
            stand.className = 'sapcert-state' + (art ? ' is-' + art : '');
        }

        function zustand() {
            // Zeigt, WAS gerade verankert ist – auch ohne Pruefung. Ohne diese
            // Zeile waere ein vorhandener Anker unsichtbar, und niemand faende
            // den Weg, ihn wieder zu loesen.
            var g = (opts.gebunden && opts.gebunden()) || {};
            var f = (opts.fremd && opts.fremd()) || {};
            var alt = container.querySelector('.sapcert-pinned');
            if (alt) alt.remove();
            if (!g.fingerprint && !f.fingerprint) return;
            var box = el('div', 'sapcert-pinned');
            if (g.fingerprint) {
                var txt = T('sapcert.pinned', 'Verankert: {host} · {fp}')
                    .replace('{host}', g.host + ':' + g.port)
                    .replace('{fp}', fpKurz(g.fingerprint));
                var d = datum(g.gebunden_am);
                box.appendChild(el('span', 'sapcert-pinned-txt',
                    txt + (d ? ' · ' + d : '')));
                var loesen = el('button', 'sapcert-icon');
                loesen.type = 'button';
                loesen.title = T('sapcert.unpin', 'Verankerung entfernen');
                // Muelleimer = loeschen (Symbol-Semantik, frontend/js/icons.js).
                if (window.JarvisIcons && window.JarvisIcons.trash) {
                    loesen.innerHTML = window.JarvisIcons.trash();
                } else {
                    loesen.textContent = '−';
                }
                loesen.addEventListener('click', entfernen);
                box.appendChild(loesen);
            } else {
                box.appendChild(el('span', 'sapcert-pinned-txt',
                    T('sapcert.pinned_admin',
                        'Vom Administrator verankert: {host} · {fp}')
                        .replace('{host}', f.host + ':' + f.port)
                        .replace('{fp}', fpKurz(f.fingerprint))));
            }
            container.appendChild(box);
        }

        function zeichne(z) {
            letzte = z;
            kasten.hidden = false;
            kasten.textContent = '';

            var tab = el('div', 'sapcert-grid');
            function zeileAdd(k, v) {
                if (!v) return;
                tab.appendChild(el('span', 'sapcert-k', k));
                tab.appendChild(el('span', 'sapcert-v', v));
            }
            zeileAdd(T('sapcert.server', 'Server'), z.host + ':' + z.port);
            zeileAdd(T('sapcert.subject', 'Inhaber'), z.inhaber);
            zeileAdd(T('sapcert.issuer', 'Aussteller'), z.aussteller);
            if (z.gueltig_von || z.gueltig_bis) {
                zeileAdd(T('sapcert.valid', 'Gültig'),
                    (z.gueltig_von || '?') + ' – ' + (z.gueltig_bis || '?'));
            }
            if (z.namen && z.namen.length) {
                zeileAdd(T('sapcert.names', 'Namen im Zertifikat'), z.namen.join(', '));
            }
            tab.appendChild(el('span', 'sapcert-k', T('sapcert.fp', 'Fingerabdruck')));
            tab.appendChild(el('span', 'sapcert-v sapcert-fp', z.fingerprint || ''));
            kasten.appendChild(tab);

            var urteil = el('p', 'sapcert-verdict');
            var btnTrust = null;
            if (z.system_ok) {
                urteil.className += ' is-ok';
                urteil.textContent = T('sapcert.v_ok',
                    'Von einer bekannten Zertifizierungsstelle bestätigt – hier ist nichts zu tun.');
            } else if (z.pin_ok) {
                urteil.className += ' is-warn';
                urteil.textContent = T('sapcert.v_pin',
                    'Keiner bekannten Zertifizierungsstelle zuzuordnen ({grund}). Wenn dieser '
                    + 'Fingerabdruck stimmt, kannst du genau dieses Zertifikat verankern – die '
                    + 'Prüfung bleibt dann an, statt sie abzuschalten.')
                    .replace('{grund}', z.system_grund || '—');
                btnTrust = el('button', 'sapcert-btn is-primary',
                    T('sapcert.trust', 'Diesem Zertifikat vertrauen'));
                btnTrust.type = 'button';
                btnTrust.addEventListener('click', verankern);
            } else {
                urteil.className += ' is-err';
                // Bewusst KEIN Verankern-Knopf: gemessen (dritter Handshake in
                // sap_cert.pruefen) wuerde die Bindung nicht funktionieren. Ein
                // Knopf, der etwas verspricht, was die Verbindung nicht haelt,
                // ist schlimmer als kein Knopf.
                var weg = (opts.kanal === 'hana')
                    ? T('sapcert.v_no_hana',
                        'Der Name im Zertifikat passt nicht zur Adresse ({grund}). '
                        + 'Für HANA lässt sich das überbrücken – trage besser den Namen ein, '
                        + 'auf den das Zertifikat lautet.')
                    : T('sapcert.v_no',
                        'Verankern würde hier nicht helfen ({grund}). Trage die Adresse ein, '
                        + 'auf die das Zertifikat lautet – oder lass auf dem SAP-Server ein '
                        + 'Zertifikat mit passendem Namen hinterlegen.');
                urteil.textContent = weg.replace('{grund}', z.pin_grund || z.system_grund || '—');
            }
            kasten.appendChild(urteil);
            if (btnTrust) kasten.appendChild(btnTrust);

            var hinweis = el('p', 'sapcert-hint', T('sapcert.browser_hint',
                'Die Verbindung zum SAP-System baut der Server auf, nicht der Browser – '
                + 'ein Eintrag im Browser-Zertifikatsspeicher wirkt hier nicht.'));
            kasten.appendChild(hinweis);
        }

        function ziel() {
            try { return (opts.ziel && opts.ziel()) || {}; }
            catch (e) { return {}; }
        }

        function senden(pfad, rumpf, methode) {
            return fetch(pfad, {
                method: methode || 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: rumpf ? JSON.stringify(rumpf) : undefined
            }).then(function (r) {
                return r.json().catch(function () { return null; })
                    .then(function (d) { return { ok: r.ok, d: d || {} }; });
            });
        }

        function pruefen() {
            var z = ziel();
            z.kanal = opts.kanal;
            melde(T('sapcert.checking', 'Frage das Zertifikat ab…'));
            btnPruef.disabled = true;
            senden(opts.basis + '/probe', z).then(function (res) {
                btnPruef.disabled = false;
                if (!res.ok || !res.d.ok) {
                    kasten.hidden = true;
                    melde(res.d.error || T('sapcert.failed', 'Prüfung fehlgeschlagen.'), 'err');
                    return;
                }
                melde('');
                zeichne(res.d.zert || {});
            }).catch(function () {
                btnPruef.disabled = false;
                melde(T('sapcert.failed', 'Prüfung fehlgeschlagen.'), 'err');
            });
        }

        function verankern() {
            if (!letzte) return;
            var z = ziel();
            z.kanal = opts.kanal;
            // Es geht NUR der Fingerabdruck hinaus, den der Mensch gesehen hat –
            // der Server holt das Zertifikat selbst und vergleicht.
            z.fingerprint = letzte.fingerprint;
            melde(T('sapcert.trusting', 'Verankere…'));
            senden(opts.basis + '/trust', z).then(function (res) {
                if (!res.ok || !res.d.ok) {
                    melde(res.d.error || T('sapcert.trust_failed', 'Verankern fehlgeschlagen.'), 'err');
                    return;
                }
                melde('✓ ' + T('sapcert.trusted', 'Verankert.'), 'ok');
                kasten.hidden = true;
                if (opts.nachAenderung) opts.nachAenderung(res.d);
                zustand();
            }).catch(function () {
                melde(T('sapcert.trust_failed', 'Verankern fehlgeschlagen.'), 'err');
            });
        }

        function entfernen() {
            if (!window.confirm(T('sapcert.unpin_ask',
                'Verankerung entfernen? Danach gilt wieder die normale Zertifikatsprüfung.'))) return;
            senden(opts.basis + '?kanal=' + encodeURIComponent(opts.kanal), null, 'DELETE')
                .then(function (res) {
                    if (!res.ok || !res.d.ok) {
                        melde(res.d.error || T('sapcert.unpin_failed', 'Entfernen fehlgeschlagen.'), 'err');
                        return;
                    }
                    melde('✓ ' + T('sapcert.unpinned', 'Verankerung entfernt.'), 'ok');
                    if (opts.nachAenderung) opts.nachAenderung(res.d);
                    zustand();
                }).catch(function () {
                    melde(T('sapcert.unpin_failed', 'Entfernen fehlgeschlagen.'), 'err');
                });
        }

        btnPruef.addEventListener('click', pruefen);
        zustand();
        return { refresh: zustand };
    }

    window.SapCert = { mount: mount };
})();
