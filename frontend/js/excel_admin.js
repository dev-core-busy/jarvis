/* ═══════════════════════════════════════════════════════════════════════
   Einstellungen → Excel: Add-in verteilen und Grenzen pflegen.

   Der Reiter hat zwei Aufgaben, und die erste ist die wichtigere:

   1. **Das Manifest zum Verteilen bereitstellen.** Anders als beim
      Outlook-Add-in gibt es keinen Exchange-Katalog, der die Datei ausrollt –
      Add-ins fuer Arbeitsmappen verteilt ein Exchange nicht. Der Administrator
      legt sie in einen Netzwerkordner, den die Arbeitsplaetze als
      vertrauenswuerdigen Katalog eintragen. Ohne diesen Knopf muesste er die
      URL kennen; das ist genau die Art verstecktes Wissen, die eine Funktion
      unbenutzbar macht.

   2. Die beiden Grenzwerte des Skills pflegen.

   WARUM DER DOWNLOAD EIN <a> IST UND KEIN fetch: der Endpunkt liefert
   `Content-Disposition: attachment` samt Branding-Dateinamen. Ein Umweg ueber
   fetch + Blob muesste den Dateinamen selbst bilden – und liefe damit dem
   Branding hinterher.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    var SKILL = 'excel-addin';
    var _gebunden = false;
    var _laeuft = false;

    function $(id) { return document.getElementById(id); }
    function token() {
        try { return localStorage.getItem('jarvis_token') || ''; } catch (e) { return ''; }
    }
    function kopf(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function melde(id, text, art) {
        var e = $(id);
        if (!e) return;
        e.textContent = text || '';
        e.style.color = art === 'ok' ? 'var(--success)'
            : art === 'fehler' ? 'var(--danger)' : 'var(--text-muted)';
    }

    /* Die Manifest-Version kommt vom Server. Sie steht auch im Manifest selbst,
       aber ein Administrator soll sie sehen, OHNE die Datei zu oeffnen – sonst
       ist "habe ich die aktuelle verteilt?" nicht beantwortbar. */
    function ladeVersion() {
        fetch('/api/excel-addin/version', { cache: 'no-store' })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d && d.version) {
                    melde('xa-version', 'Manifest-Fassung ' + d.version);
                }
            }).catch(function () { });
    }

    /* Ein Manifest, das ueber "localhost" abgerufen wurde, zeigt auf jedem
       Arbeitsplatz ins Leere – Excel installiert es klaglos, das Fenster bleibt
       danach leer. Der Server weist den Abruf deshalb ab (HTTP 400); hier wird
       der Grund SICHTBAR gemacht, statt den Administrator eine kaputte Datei
       verteilen zu lassen. */
    function pruefeAdresse() {
        var warn = $('xa-warn');
        var dl = $('xa-download');
        if (!warn) return;
        fetch('/excel-addin/manifest.xml', { method: 'GET', cache: 'no-store' })
            .then(function (r) {
                if (r.ok) { warn.style.display = 'none'; return; }
                return r.json().catch(function () { return {}; }).then(function (d) {
                    warn.textContent = '⚠ ' + (d.error ||
                        'Das Manifest kann über diese Adresse nicht erzeugt werden.');
                    warn.style.color = 'var(--danger)';
                    warn.style.display = '';
                    if (dl) { dl.style.opacity = '.5'; dl.style.pointerEvents = 'none'; }
                });
            }).catch(function () { });
    }

    function ladeGrenzen() {
        return fetch('/api/skills/' + SKILL + '/config', { headers: kopf() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                // Der Endpunkt antwortet VERSCHACHTELT ({config: {...}}). Genau
                // das wurde am 2026-08-12 beim E-Mail-Reiter uebersehen: eine
                // Ebene zu hoch gegriffen, alle Felder undefined – und das
                // naechste Speichern schrieb die Leere fest.
                var c = (d && d.config) || {};
                var r1 = $('xa-l-runden'); if (r1) r1.value = c.max_runden || 3;
                var r2 = $('xa-l-aenderungen'); if (r2) r2.value = c.max_aenderungen || 200;
                var k = $('xa-katalog');
                // `|| ''` waere hier richtig, `|| vorgabe` nicht: ein leerer
                // Pfad ist die AUSSAGE "wir verteilen nicht zentral".
                if (k) k.value = c.katalog_pfad || '';
            }).catch(function () { });
    }

    /* Eigener Knopf, eigene Teilmenge. `update_skill_config` merged – ein Knopf,
       der den ganzen Formularstand schickt, ueberschriebe den jeweils anderen
       Teil (Lehre von den SAP-Sichtbarkeiten und den beiden E-Mail-Knoepfen). */
    function speichereKatalog() {
        if (_laeuft) return;
        _laeuft = true;
        var feld = $('xa-katalog');
        var pfad = (feld ? feld.value : '').trim();
        melde('xa-katalog-status', 'Speichert …');
        fetch('/api/skills/' + SKILL + '/config', {
            method: 'POST',
            headers: kopf({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ katalog_pfad: pfad })
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            // Die Folge benennen, nicht nur "gespeichert": der Knopf schaltet
            // die Benutzerseite zwischen Download und Pfad um, und das sieht
            // man von hier aus nicht.
            melde('xa-katalog-status', pfad
                ? 'Gespeichert – /excel zeigt jetzt diesen Pfad statt des Downloads.'
                : 'Gespeichert – /excel bietet wieder den Download an.', 'ok');
            setTimeout(function () { melde('xa-katalog-status', ''); }, 5000);
        }).catch(function (e) {
            melde('xa-katalog-status', 'Fehler: ' + (e && e.message || e), 'fehler');
        }).then(function () { _laeuft = false; });
    }

    function speichere() {
        if (_laeuft) return;
        _laeuft = true;
        melde('xa-save-status', 'Speichert …');
        var runden = parseInt(($('xa-l-runden') || {}).value, 10);
        var aend = parseInt(($('xa-l-aenderungen') || {}).value, 10);
        if (!(runden >= 1 && runden <= 5)) runden = 3;
        if (!(aend >= 10 && aend <= 500)) aend = 200;
        // NUR die eigenen Felder senden. `update_skill_config` merged – ein
        // Knopf, der den ganzen Formularstand schickt, ueberschriebe fremde
        // Teile der Konfiguration (Lehre von den SAP-Sichtbarkeiten).
        fetch('/api/skills/' + SKILL + '/config', {
            method: 'POST',
            headers: kopf({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ max_runden: runden, max_aenderungen: aend })
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            melde('xa-save-status', 'Gespeichert.', 'ok');
            setTimeout(function () { melde('xa-save-status', ''); }, 3000);
        }).catch(function (e) {
            melde('xa-save-status', 'Fehler: ' + (e && e.message || e), 'fehler');
        }).then(function () { _laeuft = false; });
    }

    function binde() {
        if (_gebunden) return;
        _gebunden = true;
        // Klapp-Container verdrahten. MUSS hier passieren: das Markup traegt nur
        // die Klassen, gebunden wird ueber _collapseInit in app.js – das merkt
        // sich zusaetzlich den Auf-/Zu-Zustand je Container.
        if (window.initExcelCollapse) window.initExcelCollapse();
        var b = $('xa-save');
        if (b) b.addEventListener('click', speichere);
        var kb = $('xa-katalog-save');
        if (kb) kb.addEventListener('click', speichereKatalog);
        var g = $('xa-guide-btn');
        if (g) {
            g.addEventListener('click', function () {
                var box = $('xa-guide');
                if (!box) return;
                var auf = box.style.display !== 'none';
                box.style.display = auf ? 'none' : '';
                g.setAttribute('aria-expanded', auf ? 'false' : 'true');
                // Ein Umschalter mit unveraenderlicher Beschriftung sieht beim
                // Zuklappen wie ein wirkungsloser Klick aus (Lehre vom
                // Broker-Audit-Knopf).
                g.textContent = auf ? 'Anleitung für den Arbeitsplatz anzeigen'
                                    : 'Anleitung ausblenden';
            });
        }
    }

    window.ExcelAdmin = {
        onShow: function () {
            binde();
            ladeVersion();
            ladeGrenzen();
            pruefeAdresse();
        }
    };
})();
