/* ═══════════════════════════════════════════════════════════════════
   Einstellungen -> Sicherheit: Anmeldung ueber den IdP (OpenID Connect)

   Zwei Stellen:
   * Unter-Container "Anmeldung ueber den IdP" im Bereich Berechtigungen
     (GET/POST /api/admin/oidc, POST /api/admin/oidc/test). Darin der Schalter
     "AD-Anmeldung minimiert anzeigen" (oidc_ad_modus: an = "fallback", aus =
     "zusaetzlich"; bis 2026-11-20 hiess er "AD-Anmeldung zusaetzlich" und war
     umgekehrt gepolt – die gespeicherten Werte sind dieselben; Vorgabe seit
     2026-11-20 "fallback", also an) – nur sichtbar, solange "Anmeldung ueber den IdP
     anbieten" angehakt ist. Geladen wird beim
     ersten Aufklappen. Das Client-Secret kommt nie zurueck – das Feld bleibt
     leer, darunter steht nur, ob eines hinterlegt ist; leer speichern laesst
     es unveraendert.
   * Schalter "Die Anmeldung ueber den IdP zaehlt als zweiter Faktor" im
     Bereich "Pflicht fuer Administratoren" (POST /api/admin/anmeldeschutz/idp-mfa).
     Den Zustand liefert GET /api/admin/anmeldeschutz; totp_admin.js reicht
     ihn ueber IdpEinstellungen.mfaZeigen() weiter.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    function token() { return (window.JarvisSitzung && window.JarvisSitzung.token()) || ''; }
    function T(key, def) {
        try { var s = window.t ? window.t(key) : ''; if (s && s !== key) return s; } catch (e) {}
        return def;
    }
    function $(id) { return document.getElementById(id); }
    function anfrage(pfad, methode, rumpf) {
        var opt = { method: methode || 'GET',
                    headers: { 'Authorization': 'Bearer ' + token() } };
        if (rumpf !== undefined) {
            opt.headers['Content-Type'] = 'application/json';
            opt.body = JSON.stringify(rumpf);
        }
        return fetch(pfad, opt).then(function (r) {
            return r.json().catch(function () { return {}; })
                .then(function (d) { return { ok: r.ok, d: d || {} }; });
        });
    }
    function meldung(id, text, fehler) {
        var e = $(id);
        if (!e) return;
        e.textContent = text || '';
        e.style.color = fehler ? 'var(--danger)' : 'var(--text-primary)';
    }

    // ── Unter-Container: Verbindung zum IdP ─────────────────────────────

    // Der Modus-Schalter gilt nur fuer die IdP-Anmeldung: ohne sie gibt es
    // nichts, neben dem die Kennwortanmeldung minimiert stehen koennte.
    function modusZeile() {
        var z = $('idp-ad-modus-zeile'), cb = $('idp-aktiv');
        if (z) z.hidden = !(cb && cb.checked);
    }

    function zeigen(d) {
        if ($('idp-aktiv')) $('idp-aktiv').checked = !!d.oidc_aktiv;
        if ($('idp-ad-minimiert')) $('idp-ad-minimiert').checked = d.oidc_ad_modus === 'zusaetzlich';
        modusZeile();
        if ($('idp-issuer')) $('idp-issuer').value = d.oidc_issuer || '';
        if ($('idp-client-id')) $('idp-client-id').value = d.oidc_client_id || '';
        if ($('idp-client-secret')) $('idp-client-secret').value = '';
        if ($('idp-upn-suffixe')) $('idp-upn-suffixe').value = d.oidc_upn_suffixe || '';
        if ($('idp-ca-cert')) $('idp-ca-cert').value = d.oidc_ca_cert || '';
        var ru = $('idp-redirect-uri');
        if (ru) {
            ru.value = d.oidc_redirect_uri || '';
            // Der Server rechnet die Adresse aus dem eigenen Namen aus – ein
            // fertiger, richtiger Wert, kein Formbeispiel. Ueber JarvisTabfill,
            // damit TAB ihn uebernimmt (gemeldet 2026-11-19: er liess sich nur
            // abtippen, weil die Markierung fehlte).
            JarvisTabfill.vorschlag(ru, d.redirect_uri_vorschlag);
        }
        var sel = $('idp-namensclaim');
        if (sel) {
            sel.textContent = '';
            (d.namensclaims || []).forEach(function (c) {
                var o = document.createElement('option');
                o.value = c; o.textContent = c;
                sel.appendChild(o);
            });
            sel.value = d.oidc_namensclaim || 'preferred_username';
        }
        var st = $('idp-secret-status');
        if (st) {
            st.textContent = !d.client_secret_gesetzt
                ? T('security.idp_secret_fehlt', 'Kein Client-Secret hinterlegt.')
                : (d.client_secret_lesbar
                    ? T('security.idp_secret_da', 'Ein Client-Secret ist hinterlegt (leer lassen = unverändert).')
                    : T('security.idp_secret_unlesbar', 'Ein Client-Secret ist hinterlegt, aber auf diesem Server nicht lesbar. Bitte neu eintragen.'));
        }
        var hinweise = [];
        if (!d.ad_eingerichtet) hinweise.push(T('security.idp_ohne_ad',
            'Ohne Verbindung zum Active Directory bleibt die Anmeldung über den IdP aus – die Anmeldeberechtigung wird dort geprüft.'));
        if (d.oidc_aktiv && !d.bereit) hinweise.push(T('security.idp_unvollstaendig',
            'Eingeschaltet, aber noch unvollständig: Aussteller, Client-ID und Client-Secret werden gebraucht.'));
        meldung('idp-msg', hinweise.join('\n'), hinweise.length > 0);
    }

    var geladen = false;
    function laden() {
        anfrage('/api/admin/oidc').then(function (res) {
            if (!res.ok || !res.d.ok) {
                meldung('idp-msg', res.d.detail || res.d.error ||
                    T('security.idp_laden_fehler', 'Die Einstellungen konnten nicht geladen werden.'), true);
                return;
            }
            geladen = true;
            zeigen(res.d);
        }).catch(function () {
            meldung('idp-msg', T('security.idp_laden_fehler', 'Die Einstellungen konnten nicht geladen werden.'), true);
        });
    }

    function speichern() {
        var btn = $('idp-speichern');
        var rumpf = {
            oidc_aktiv: !!($('idp-aktiv') && $('idp-aktiv').checked),
            oidc_ad_modus: ($('idp-ad-minimiert') && $('idp-ad-minimiert').checked)
                ? 'fallback' : 'zusaetzlich',
            oidc_issuer: ($('idp-issuer') || {}).value || '',
            oidc_client_id: ($('idp-client-id') || {}).value || '',
            oidc_namensclaim: ($('idp-namensclaim') || {}).value || '',
            oidc_upn_suffixe: ($('idp-upn-suffixe') || {}).value || '',
            oidc_redirect_uri: ($('idp-redirect-uri') || {}).value || '',
            oidc_ca_cert: ($('idp-ca-cert') || {}).value || ''
        };
        var geheim = ($('idp-client-secret') || {}).value || '';
        if (geheim.trim()) rumpf.client_secret = geheim;
        if (btn) btn.disabled = true;
        meldung('idp-msg', '');
        anfrage('/api/admin/oidc', 'POST', rumpf).then(function (res) {
            if (btn) btn.disabled = false;
            if (!res.ok || !res.d.ok) {
                meldung('idp-msg', res.d.detail || res.d.error ||
                    T('security.idp_speichern_fehler', 'Die Einstellungen konnten nicht gespeichert werden.'), true);
                return;
            }
            zeigen(res.d);
            if (!$('idp-msg').textContent) meldung('idp-msg', T('security.idp_gespeichert', 'Gespeichert.'));
        }).catch(function () {
            if (btn) btn.disabled = false;
            meldung('idp-msg', T('security.idp_speichern_fehler', 'Die Einstellungen konnten nicht gespeichert werden.'), true);
        });
    }

    function testen() {
        var btn = $('idp-testen');
        if (btn) btn.disabled = true;
        meldung('idp-msg', T('security.idp_test_laeuft', 'Verbindung wird geprüft …'));
        anfrage('/api/admin/oidc/test', 'POST', {}).then(function (res) {
            if (btn) btn.disabled = false;
            var d = res.d;
            if (!res.ok || !d.ok) {
                meldung('idp-msg', d.detail || d.error || T('security.idp_test_fehler', 'Verbindung fehlgeschlagen.'), true);
                return;
            }
            var zeilen = [T('security.idp_test_ok', 'Verbindung zum IdP steht.'),
                T('security.idp_test_schluessel', 'Signaturschlüssel:') + ' ' + d.schluessel];
            if (d.algorithmen_erlaubt === false) zeilen.push(T('security.idp_test_alg',
                'Achtung: Der IdP bietet kein Signaturverfahren an, das {marke} annimmt.') + ' (' + (d.algorithmen || []).join(', ') + ')');
            meldung('idp-msg', zeilen.join('\n'), d.algorithmen_erlaubt === false);
        }).catch(function () {
            if (btn) btn.disabled = false;
            meldung('idp-msg', T('security.idp_test_fehler', 'Verbindung fehlgeschlagen.'), true);
        });
    }

    function containerVerdrahten() {
        var det = document.querySelector('details.sec-sub[data-sub="idp"]');
        if (det) det.addEventListener('toggle', function () { if (det.open && !geladen) laden(); });
        if ($('idp-speichern')) $('idp-speichern').addEventListener('click', speichern);
        if ($('idp-testen')) $('idp-testen').addEventListener('click', testen);
        if ($('idp-aktiv')) $('idp-aktiv').addEventListener('change', modusZeile);
    }

    // ── Schalter "MFA des IdP zaehlt als zweiter Faktor" ─────────────────

    function mfaZeigen(d) {
        var cb = $('sec-idp-mfa'), f = $('sec-idp-mfa-nachweis');
        if (cb) cb.checked = !!(d && d.idp_mfa_anerkennen);
        if (f && d && typeof d.idp_mfa_nachweis === 'string') f.value = d.idp_mfa_nachweis;
    }

    function mfaSenden(anerkennen, alt) {
        var cb = $('sec-idp-mfa'), btn = $('sec-idp-mfa-speichern');
        var nachweis = (($('sec-idp-mfa-nachweis') || {}).value || '').trim();
        if (cb) cb.disabled = true;
        if (btn) btn.disabled = true;
        meldung('sec-idp-mfa-msg', '');
        return anfrage('/api/admin/anmeldeschutz/idp-mfa', 'POST',
                       { anerkennen: anerkennen, nachweis: nachweis }).then(function (res) {
            if (cb) cb.disabled = false;
            if (btn) btn.disabled = false;
            if (res.ok && res.d.ok) {
                mfaZeigen({ idp_mfa_anerkennen: res.d.idp_mfa_anerkennen,
                            idp_mfa_nachweis: res.d.idp_mfa_nachweis });
                meldung('sec-idp-mfa-msg', T('security.idp_gespeichert', 'Gespeichert.'));
                return;
            }
            if (cb) cb.checked = alt;
            meldung('sec-idp-mfa-msg', res.d.detail || res.d.error ||
                T('security.pflicht_failed', 'Die Einstellung konnte nicht gespeichert werden.'), true);
        }).catch(function () {
            if (cb) { cb.disabled = false; cb.checked = alt; }
            if (btn) btn.disabled = false;
            meldung('sec-idp-mfa-msg', T('security.pflicht_failed', 'Die Einstellung konnte nicht gespeichert werden.'), true);
        });
    }

    function mfaVerdrahten() {
        var cb = $('sec-idp-mfa'), btn = $('sec-idp-mfa-speichern');
        // Nur auf "change" hoeren – der Browser schaltet im <label> selbst um.
        if (cb) cb.addEventListener('change', function () { mfaSenden(cb.checked, !cb.checked); });
        if (btn) btn.addEventListener('click', function () {
            var an = !!(cb && cb.checked);
            mfaSenden(an, an);
        });
    }

    function start() { containerVerdrahten(); mfaVerdrahten(); }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();

    window.IdpEinstellungen = { mfaZeigen: mfaZeigen, _zeigen: zeigen, _laden: laden };
})();
