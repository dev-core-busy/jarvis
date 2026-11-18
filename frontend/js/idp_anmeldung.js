/* ═══════════════════════════════════════════════════════════════════
   Anmeldung ueber den IdP (OpenID Connect) – Anmeldemaske auf "/"

   1. Zeigt den Knopf "Mit Firmenkonto anmelden", wenn der Server die
      IdP-Anmeldung meldet (/api/login/oidc/status). Der Knopf ist ein Link
      auf /api/login/oidc/start; der Server leitet zum IdP weiter.
   2. Nach der Rueckkehr (/?anmeldung=idp) liegt ein kurzlebiger Einloese-
      Schein im HttpOnly-Cookie. Diese Datei tauscht ihn per fetch gegen die
      Sitzung (/api/login/oidc/einloesen) – auf demselben Weg wie die
      Kennwortanmeldung (Sitzungs-Cookie + CSRF-Token in der Antwort).
      Verlangt der Server den Zwei-Faktor-Code, erscheint #idp-totp.
   3. Fehler (/?idp_fehler=<kennung>) stehen in #login-error, uebersetzt.

   Die Kennwortanmeldung (app.js) bleibt unberuehrt.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    function T(key, def) {
        try { var s = window.t ? window.t(key) : ''; if (s && s !== key) return s; } catch (e) {}
        return def;
    }
    function $(id) { return document.getElementById(id); }

    // Kennungen aus backend/main.py (_oidc_zurueck) und oidc_anmeldung.OidcFehler.code
    var FEHLER = {
        nicht_eingerichtet: 'Die Anmeldung über das Firmenkonto ist auf diesem Server nicht eingerichtet.',
        zu_viele: 'Zu viele Anmeldeversuche. Bitte warte 5 Minuten.',
        abgelaufen: 'Die Anmeldung über das Firmenkonto ist abgelaufen. Bitte erneut versuchen.',
        abgebrochen: 'Die Anmeldung beim Firmenkonto wurde abgebrochen.',
        nicht_erreichbar: 'Der Anmeldedienst des Unternehmens ist gerade nicht erreichbar.',
        konfiguration: 'Die Anmeldung über das Firmenkonto ist falsch eingerichtet. Bitte den Administrator informieren.',
        idp: 'Der Anmeldedienst des Unternehmens hat die Anmeldung abgelehnt.',
        token: 'Die Bestätigung des Anmeldedienstes war ungültig. Bitte den Administrator informieren.',
        schluessel: 'Die Bestätigung des Anmeldedienstes war ungültig. Bitte den Administrator informieren.',
        name: 'Das Firmenkonto passt zu keinem Benutzer dieses Servers.',
        lokal: 'Dieses Konto lässt sich nur mit Kennwort anmelden.',
        gesperrt: 'Das Konto ist nach zu vielen Fehlversuchen vorübergehend gesperrt.',
        keine_freigabe: 'Keine Anmeldeberechtigung.',
        pruefung: 'Die Anmeldeberechtigung ist gerade nicht prüfbar. Bitte mit Kennwort anmelden.',
        lizenz: 'Die Zahl der Benutzer für diese Lizenz ist erreicht.'
    };

    function fehlerZeigen(ziel, text) {
        var e = $(ziel);
        if (!e) return;
        e.textContent = text;
        e.hidden = false;
    }

    function adresseAufraeumen() {
        // Kennungen nicht im Verlauf stehen lassen (ein Neuladen wuerde sonst
        // erneut einloesen bzw. den alten Fehler zeigen).
        try { history.replaceState(null, '', '/'); } catch (e) { /* egal */ }
    }

    function knopfZeigen() {
        var box = $('idp-login');
        if (!box) return;
        fetch('/api/login/oidc/status', { headers: { 'Accept': 'application/json' } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) { box.hidden = !(d && d.aktiv); })
            .catch(function () { box.hidden = true; });
    }

    function codeModus(an) {
        var form = $('login-form'), box = $('idp-totp');
        if (form) form.hidden = !!an;
        if (box) box.hidden = !an;
        if (an && $('idp-totp-code')) $('idp-totp-code').focus();
    }

    async function erfolg(data) {
        var token = data.token;
        localStorage.setItem('jarvis_token', token);
        localStorage.setItem('jarvis_user', data.username || '');
        if (data.account_blocked) {
            codeModus(false);
            if (window.SecurityIncidents) {
                window.SecurityIncidents.showBlockedScreen(data.block_reason, data.block_incidents);
            }
            return;
        }
        // Zweiter Schritt wie nach der Kennwortanmeldung (app.js): weitere
        // Anmeldungen (SAP, Jira …), falls fuer diesen Benutzer noetig.
        if (window.ZugangAnmeldung) {
            try { await window.ZugangAnmeldung.schritt(token); } catch (e) { /* weiter */ }
        }
        window.location.replace('/portal');
    }

    var laeuft = false;
    async function einloesen(code) {
        if (laeuft) return;
        laeuft = true;
        var btn = $('idp-totp-btn');
        if (btn) btn.disabled = true;
        var err = $('idp-totp-error');
        if (err) err.hidden = true;
        try {
            var res = await fetch('/api/login/oidc/einloesen', {
                method: 'POST',
                headers: window.JarvisSitzung.anmeldeKopf({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(code ? { totp_code: code } : {})
            });
            var data = {};
            try { data = await res.json(); } catch (e) { data = {}; }
            if (data.success && data.token) {
                await erfolg(data);
            } else if (data.requires_totp) {
                codeModus(true);
                if (code && data.error) fehlerZeigen('idp-totp-error', data.error);
                var feld = $('idp-totp-code');
                if (feld) feld.value = '';
            } else {
                codeModus(false);
                fehlerZeigen('login-error', data.error || T('login.failed', 'Anmeldung fehlgeschlagen.'));
            }
        } catch (e) {
            codeModus(false);
            fehlerZeigen('login-error', T('login.server_error', 'Server nicht erreichbar.'));
        } finally {
            laeuft = false;
            if (btn) btn.disabled = false;
        }
    }

    function codeVerdrahten() {
        var feld = $('idp-totp-code'), btn = $('idp-totp-btn');
        if (btn) btn.addEventListener('click', function () {
            var c = (feld && feld.value || '').replace(/\D/g, '');
            if (c.length === 6) einloesen(c);
        });
        if (feld) feld.addEventListener('input', function () {
            var c = feld.value.replace(/\D/g, '');
            if (c.length === 6) { feld.value = c; einloesen(c); }
        });
    }

    function start() {
        knopfZeigen();
        codeVerdrahten();
        var q;
        try { q = new URLSearchParams(window.location.search); } catch (e) { return; }
        var fehler = q.get('idp_fehler');
        if (fehler) {
            adresseAufraeumen();
            fehlerZeigen('login-error', T('login.idp_err.' + fehler,
                FEHLER[fehler] || T('login.failed', 'Anmeldung fehlgeschlagen.')));
        } else if (q.get('anmeldung') === 'idp') {
            adresseAufraeumen();
            einloesen('');
        }
    }

    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();

    window.IdpAnmeldung = { _einloesen: einloesen, _FEHLER: FEHLER };
})();
