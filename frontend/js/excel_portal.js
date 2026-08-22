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
    // Zuletzt gezeichnete Sprache – siehe Begruendung an `binde()`.
    var _lang = '';

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

    // Zahnrad nur fuer Administratoren – dort werden Freigabe und Skill
    // gepflegt. Der Rueckweg wird gemerkt, damit /settings zurueckfindet
    // (gleiches Muster wie /sap, /support, /wissen, /tracks, /claude, /email).
    function zahnrad(istAdmin) {
        var b = $('xp-settings-btn');
        if (!b || !istAdmin) return;
        b.style.display = '';
        if (b.dataset.gebunden) return;
        b.dataset.gebunden = '1';
        b.addEventListener('click', function () {
            try { sessionStorage.setItem('jarvis_settings_return', '/excel'); } catch (e) { /* egal */ }
            window.location.href = '/settings';
        });
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

    /* SPRACHE UND THEMA WERDEN HIER NICHT MEHR VERDRAHTET (seit 2026-08-21).
       `i18n.js` bedient `.lang-toggle-btn` samt Aktiv-Zustand, `theme.js`
       bedient `#btn-theme-toggle` samt Sonne/Mond. Die frueheren Eigenbauten
       (`xp-lang`, `xp-theme`) waren Verdopplung MIT abweichendem Verhalten –
       ein einzelner Umschaltknopf statt des DE|EN-Paars, das jede andere
       Bereichsseite zeigt. Genau das wurde gemeldet.

       Geblieben ist nur, was wirklich seitenspezifisch ist: das Abmelden und
       das Neuzeichnen des Sperrhinweises beim Sprachwechsel. */
    function binde() {
        var e;
        if ((e = $('xp-logout-btn'))) e.addEventListener('click', function () {
            // Signal MUSS raus, BEVOR der Token verworfen wird (danach ist die
            // Abmeldung nicht mehr authentifizierbar); `keepalive` steckt in
            // JarvisSession, weil die Seite unmittelbar danach wegnavigiert.
            var p = (window.JarvisSession ? window.JarvisSession.logout()
                                          : Promise.resolve());
            TOKEN_KEYS.forEach(function (k) {
                try { localStorage.removeItem(k); } catch (x) { }
            });
            p.catch(function () { }).then(function () {
                window.location.replace('/');
            });
        });

        /* Der Sperrhinweis wird per innerHTML gesetzt – `applyLang()` erreicht
           ihn nicht und wuerde ihn in der alten Sprache stehen lassen. Der
           Vergleich verhindert die Endlosschleife: `applyLang()` feuert dieses
           Ereignis bei JEDEM Aufruf, nicht nur bei einem echten Wechsel
           (Lehre vom Short-Tracks-Reiter, 2026-08-18). */
        window.addEventListener('jarvis-lang-changed', function () {
            var lg = (window._lang || 'de');
            if (lg === _lang) return;
            _lang = lg;
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
                zahnrad(d.is_admin);
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
        // Sprache SOFORT merken, nicht erst beim ersten Zeichnen: `applyLang()`
        // laeuft ebenfalls beim Seitenaufbau und feuert dabei
        // `jarvis-lang-changed`. Mit leerem `_lang` gaelte das als Wechsel und
        // loeste einen ueberfluessigen zweiten Abruf aus.
        _lang = (window._lang || 'de');
        binde();
        pruefeZugang();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
