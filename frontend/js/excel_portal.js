/* ═══════════════════════════════════════════════════════════════════════
   Excel-Assistent – Benutzerseite (/excel)

   Die Seite ist eine WEGWEISUNG, kein Bedienfeld: sie zeigt, ob der Zugang
   steht, bietet das Manifest an und erklaert den Weg nach Excel. Gefragt wird
   im Aufgabenfenster, nicht hier.

   ZWEI DINGE, DIE SIE EHRLICH BEANTWORTEN MUSS:

   1. **Darf ich ueberhaupt?** `/api/me` liefert `permissions.excel` als EINEN
      Wahrheitswert (Freigabe UND aktiver Skill). Fehlt er, wird der Download
      NICHT angeboten – ein Manifest, das man einbindet und das sich danach
      nicht anmelden laesst, ist die schlechtere Erfahrung als ein klarer Satz.

   2. **Taugt die Adresse?** Wird die Seite ueber "localhost" aufgerufen, zeigt
      das erzeugte Manifest auf jedem anderen Rechner ins Leere. Der Server
      weist das mit HTTP 400 ab; hier wird der Grund sichtbar gemacht, statt
      den Benutzer eine kaputte Datei verteilen zu lassen.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];

    function $(id) { return document.getElementById(id); }
    function T(key, fallback) {
        var s = window.t ? window.t(key) : null;
        return (s && s !== key) ? s : fallback;
    }
    function token() {
        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            try { var v = localStorage.getItem(TOKEN_KEYS[i]); if (v) return v; }
            catch (e) { }
        }
        return '';
    }

    /* Ohne Anmeldung gibt es hier nichts zu sehen – zurueck aufs Portal, das
       den Login zeigt. Gleiches Muster wie sap_portal.js/email_portal.js. */
    function zumPortal() {
        try { window.location.href = '/portal'; } catch (e) { }
    }

    function sperren(grund) {
        var w = $('xp-noaccess');
        if (w) {
            w.innerHTML = '<b>' + T('xp.no_access_head', 'Kein Zugriff') + '</b><br>' +
                (grund || T('xp.no_access',
                    'Dein Konto ist für den Excel-Assistenten nicht freigeschaltet. Wende dich an deine Administration – sie trägt dich unter Einstellungen → Sicherheit → Berechtigungen → Excel-Zugriff ein.'));
            w.classList.remove('hidden');
        }
        // Den Download-Block ganz entfernen, nicht nur ausgrauen: ein Knopf,
        // der sichtbar bleibt und nichts Brauchbares liefert, wird trotzdem
        // gedrueckt.
        var c = $('xp-dl-card');
        if (c) c.classList.add('hidden');
    }

    function ladeVersion() {
        fetch('/api/excel-addin/version', { cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var e = $('xp-version');
                if (e && d && d.version) {
                    e.textContent = T('xp.version', 'Fassung') + ' ' + d.version;
                }
            }).catch(function () { });
    }

    /* Der Server lehnt ein Manifest ab, das ueber einen nur lokal gueltigen
       Namen abgerufen wurde (HTTP 400 mit Begruendung). Diese Pruefung holt
       den Grund und zeigt ihn – der Fehler waere sonst erst in Excel sichtbar,
       als leeres Fenster, und niemand braechte ihn mit dem Download in
       Verbindung. */
    function pruefeAdresse() {
        fetch('/excel-addin/manifest.xml', { cache: 'no-store' })
            .then(function (r) {
                if (r.ok) return;
                return r.json().catch(function () { return {}; }).then(function (d) {
                    var w = $('xp-noaccess');
                    if (w) {
                        w.innerHTML = '<b>' + T('xp.bad_url_head', 'Diese Adresse taugt nicht') +
                            '</b><br>' + (d.error || '');
                        w.classList.remove('hidden');
                    }
                    var c = $('xp-dl-card');
                    if (c) c.classList.add('hidden');
                });
            }).catch(function () { });
    }

    function binde() {
        var e;
        if ((e = $('xp-theme'))) e.addEventListener('click', function () {
            if (window.toggleTheme) window.toggleTheme();
        });
        if ((e = $('xp-lang'))) e.addEventListener('click', function () {
            var neu = (window._lang === 'en') ? 'de' : 'en';
            if (window.setLang) window.setLang(neu);
            var b = $('xp-lang');
            if (b) b.textContent = neu.toUpperCase();
            // Der Sperrhinweis wird per innerHTML gesetzt – applyLang()
            // erreicht ihn nicht.
            var w = $('xp-noaccess');
            if (w && !w.classList.contains('hidden')) pruefeZugang();
        });
    }

    function pruefeZugang() {
        if (!token()) { zumPortal(); return; }
        fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + token() } })
            .then(function (r) {
                if (r.status === 401) { zumPortal(); throw new Error('401'); }
                return r.json();
            })
            .then(function (d) {
                // FAIL-CLOSED: fehlt `permissions` ganz (aelteres Backend),
                // gilt "nicht freigegeben".
                if (!(d && d.permissions && d.permissions.excel)) { sperren(''); return; }
                var w = $('xp-noaccess');
                if (w) w.classList.add('hidden');
                var c = $('xp-dl-card');
                if (c) c.classList.remove('hidden');
                ladeVersion();
                pruefeAdresse();
            }).catch(function (e) {
                if (String(e && e.message) !== '401') sperren('');
            });
    }

    function start() {
        binde();
        pruefeZugang();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
