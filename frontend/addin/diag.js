/* Start-Diagnose des Outlook-Add-ins (Gegenstueck: backend/addin_diag.py).
 *
 * Laedt als ERSTES Skript des Aufgabenfensters und meldet die Startschritte
 * an POST /api/addin/diag – der Server schreibt sie ins Journal. Anlass:
 * Outlook im Web meldete nur "Add-In-Fehler beim Starten", und von aussen
 * war nicht zu sehen, ob das Fenster lud, ob office.js kam und ob Office
 * das Fenster je als bereit meldete.
 *
 * Eigenstaendig: haengt an keinem anderen Modul und fasst addin.js nicht an.
 * Jeder Fehler hier wird geschluckt – die Diagnose darf den Start nie stoeren.
 */
(function () {
    'use strict';
    var START = Date.now();
    var LAUF = Math.random().toString(36).slice(2, 10);
    var MAX_MELDUNGEN = 25;          // je Seitenaufruf – gegen Schleifen
    var OFFICE_GRENZE_MS = 15000;    // laenger als jede Zeitgrenze von Outlook
    var gesendet = 0;

    function melde(schritt, detail) {
        try {
            if (gesendet >= MAX_MELDUNGEN) return;
            gesendet++;
            var koerper = JSON.stringify({
                lauf: LAUF, schritt: schritt, ms: Date.now() - START,
                detail: String(detail || '').slice(0, 300)
            });
            fetch('/api/addin/diag', {
                method: 'POST', keepalive: true, credentials: 'omit',
                headers: { 'Content-Type': 'application/json' }, body: koerper
            }).catch(function () { /* Diagnose ist best effort */ });
        } catch (e) { /* nie werfen */ }
    }

    function hostVon(url) {
        try { return url ? new URL(url).host : '-'; } catch (e) { return '?'; }
    }

    // 1) Das Fenster laeuft: im Rahmen? wer rahmt ein? welche Parameter?
    try {
        var imRahmen = false;
        try { imRahmen = window.top !== window; } catch (e) { imRahmen = true; }
        var namen = [];
        try { new URLSearchParams(location.search).forEach(function (_, k) { namen.push(k); }); }
        catch (e) { /* alter Browser */ }
        var vorfahren = '';
        try {
            var ao = location.ancestorOrigins;   // nur Chromium
            if (ao) for (var i = 0; i < ao.length; i++) vorfahren += (i ? ',' : '') + hostVon(ao[i]);
        } catch (e) { /* Firefox kennt es nicht */ }
        melde('html', 'rahmen=' + imRahmen + ' referrer=' + hostVon(document.referrer) +
            ' vorfahren=' + (vorfahren || '-') + ' params=' + (namen.join(',') || '-') +
            ' name=' + (window.name ? 'gesetzt(' + window.name.length + ')' : 'leer'));
    } catch (e) { /* nie werfen */ }

    // 2) Fehler jeder Art: Skriptfehler, nicht ladbare Ressourcen (Capture),
    //    abgewiesene Versprechen und CSP-Verstoesse.
    window.addEventListener('error', function (ev) {
        try {
            var ziel = ev && ev.target;
            if (ziel && ziel !== window && (ziel.src || ziel.href)) {
                melde('fehler', 'Ressource nicht ladbar: <' + (ziel.tagName || '?').toLowerCase() +
                    '> ' + (ziel.src || ziel.href));
                return;
            }
            melde('fehler', (ev.message || 'Fehler') + ' @ ' + (ev.filename || '?') + ':' +
                (ev.lineno || 0) + ':' + (ev.colno || 0));
        } catch (e) { /* nie werfen */ }
    }, true);
    window.addEventListener('unhandledrejection', function (ev) {
        try {
            var r = ev && ev.reason;
            melde('versprechen', (r && (r.message || r.toString())) || 'ohne Grund');
        } catch (e) { /* nie werfen */ }
    });
    document.addEventListener('securitypolicyviolation', function (ev) {
        try {
            melde('fehler', 'CSP ' + ev.violatedDirective + ' blockiert ' + (ev.blockedURI || '-') +
                ' (' + (ev.sourceFile || '-') + ':' + (ev.lineNumber || 0) + ')');
        } catch (e) { /* nie werfen */ }
    });

    // 3) office.js: kommt es, und meldet Office das Fenster als bereit?
    var officeGemeldet = false;
    var takt = setInterval(function () {
        try {
            if (typeof Office === 'undefined' || !Office.onReady) {
                if (Date.now() - START > OFFICE_GRENZE_MS) {
                    clearInterval(takt);
                    melde('office_zeit', 'office.js nach ' + OFFICE_GRENZE_MS + ' ms nicht da');
                }
                return;
            }
            clearInterval(takt);
            if (officeGemeldet) return;
            officeGemeldet = true;
            melde('office_da', 'office.js geladen');
            var bereit = false;
            setTimeout(function () {
                if (!bereit) melde('office_zeit', 'Office.onReady nach ' + OFFICE_GRENZE_MS + ' ms nicht ausgeloest');
            }, OFFICE_GRENZE_MS);
            Office.onReady(function (info) {
                bereit = true;
                var mb = null;
                try { mb = Office.context && Office.context.mailbox; } catch (e) { mb = null; }
                var diag = '';
                try {
                    var d = mb && mb.diagnostics;
                    if (d) diag = ' host=' + d.hostName + ' ' + d.hostVersion + ' owa=' + (d.OWAView || '-');
                } catch (e) { /* aeltere Anforderungssaetze */ }
                melde('office_bereit', 'host=' + (info && info.host) + ' plattform=' +
                    (info && info.platform) + diag);
                melde('mailbox', 'mailbox=' + !!mb + ' item=' + !!(mb && mb.item));
            });
        } catch (e) {
            clearInterval(takt);
            melde('fehler', 'Diagnose: ' + (e && e.message));
        }
    }, 100);

    // 4) Verlaesst der Rahmen die Seite (Umleitung, Neuladen durch Outlook)?
    window.addEventListener('pagehide', function () { melde('verlassen', 'nach ' + (Date.now() - START) + ' ms'); });
})();
