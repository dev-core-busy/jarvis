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
    // Hinterlegter Katalog-Pfad ('' = keiner, dann gilt der Download).
    var _pfad = '';

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

    // Das Einstellungs-Zahnrad blendet `settings_btn.js` zentral aus
    // `/api/me` ein (EINE Stelle fuer alle Bereichsseiten).

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

    /* Hat die Administration einen Katalog-Pfad hinterlegt, ist der Download
       der FALSCHE Weg: der Benutzer holte sich eine zweite Kopie, die niemand
       aktualisiert, und traegt hinterher einen anderen Ordner ein als alle
       anderen. Deshalb wird der Knopf nicht nur ergaenzt, sondern ERSETZT.

       Der Pfad kommt aus `/api/excel/katalog` (hinter der Excel-Freigabe, nicht
       am unangemeldeten Versions-Endpunkt – ein UNC-Pfad nennt Servernamen und
       Freigabe des Hauses). */
    function ladeKatalog() {
        return fetch('/api/excel/katalog', {
            headers: { 'Authorization': 'Bearer ' + token() }, cache: 'no-store'
        })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                var pfad = (d && d.pfad) || '';
                if (!pfad) return false;        // kein Pfad -> Download bleibt
                var kasten = $('xp-pfad');
                // textContent, nicht innerHTML: der Pfad ist Freitext aus dem
                // Reiter und landet ungeprueft in der Seite.
                if (kasten) kasten.textContent = pfad;
                var dl = $('xp-dl-block'); if (dl) dl.hidden = true;
                var pb = $('xp-pfad-block'); if (pb) pb.hidden = false;
                // Schritt 1 der Anleitung ("Datei in einen Ordner legen") waere
                // jetzt das Gegenteil der Aussage darueber.
                var s1 = $('xp-steps-dl'); if (s1) s1.hidden = true;
                var s2 = $('xp-steps-pfad'); if (s2) s2.hidden = false;
                var h = $('xp-get-head');
                if (h) h.textContent = T('xp.get_head_pfad', '1. Add-in-Ordner eintragen');
                _pfad = pfad;
                bindeKopieren();
                return true;
            }).catch(function () { return false; });
    }

    function bindeKopieren() {
        var b = $('xp-pfad-copy');
        if (!b || b.dataset.gebunden) return;
        b.dataset.gebunden = '1';
        b.addEventListener('click', function () {
            var melde = function (txt) {
                var s = $('xp-pfad-status');
                if (s) { s.textContent = txt; setTimeout(function () { s.textContent = ''; }, 3000); }
            };
            // Ohne Rueckmeldung sieht man nicht, ob es geklappt hat – in der
            // Zwischenablage ist nichts sichtbar. Und `navigator.clipboard`
            // fehlt in unsicherem Kontext; dann bleibt der Kasten markierbar
            // (`user-select: all`), darauf verweist die Fehlermeldung.
            var fertig = function () { melde(T('xp.pfad_copied', 'Kopiert.')); };
            var schief = function () {
                melde(T('xp.pfad_copyfail', 'Kopieren nicht möglich – Pfad markieren und mit Strg+C kopieren.'));
            };
            try {
                if (navigator.clipboard && navigator.clipboard.writeText) {
                    navigator.clipboard.writeText(_pfad).then(fertig, schief);
                } else { schief(); }
            } catch (e) { schief(); }
        });
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
                var w = $('xp-noaccess');
                if (w) w.classList.add('hidden');
                var c = $('xp-dl-card');
                if (c) c.classList.remove('hidden');
                // REIHENFOLGE IST WICHTIG. `pruefeAdresse()` blendet bei
                // einer untauglichen Adresse die GANZE Karte aus – mit
                // hinterlegtem Pfad wuerde es damit auch den Pfad verbergen,
                // obwohl der Benutzer gar nichts herunterlaedt und die vom
                // Administrator abgelegte Datei in Ordnung ist. Und die
                // Fassungsnummer dieses Servers sagt nichts ueber die Datei
                // in der Freigabe – sie zu zeigen waere eine Behauptung.
                ladeKatalog().then(function (hatPfad) {
                    if (hatPfad) return;
                    ladeVersion();
                    pruefeAdresse();
                });
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
