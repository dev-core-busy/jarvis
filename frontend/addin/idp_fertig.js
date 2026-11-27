/* Fertigseite der IdP-Anmeldung aus den Office-Add-ins (/addin/idp-fertig.html).

   Liest code bzw. fehler und zustand aus der Adresse und reicht sie per
   Office.context.ui.messageParent an das Aufgabenfenster. Getauscht wird DORT
   (POST /api/login/oidc/app-einloesen mit dem PKCE-verifier) – diese Seite
   kennt den verifier nicht und ruft den Server nicht auf.

   Danach wird die Adresse geleert (history.replaceState): der Code soll nicht
   im Verlauf des Dialogs stehen bleiben, auch wenn er nach dem Einloesen
   ohnehin wertlos ist.

   office.js kommt mit `async` (wie im Aufgabenfenster): fehlt es (kein
   Internet, Firewall), erscheint nach OFFICE_WARTE_MS ein Hinweis statt eines
   ewig drehenden Kreises. */
(function () {
    'use strict';
    var OFFICE_WARTE_MS = 6000;
    var q = new URLSearchParams(location.search);
    var nachricht = JSON.stringify({
        code: q.get('code') || '',
        fehler: q.get('fehler') || '',
        zustand: q.get('zustand') || ''
    });
    try { history.replaceState(null, '', location.pathname); } catch (e) { /* egal */ }

    var erledigt = false;
    function ohneOffice() {
        if (erledigt) return;
        erledigt = true;
        var a = document.getElementById('if-laeuft');
        var b = document.getElementById('if-ohne-office');
        if (a) a.classList.add('hidden');
        if (b) b.classList.remove('hidden');
    }
    function senden() {
        if (erledigt) return;
        try {
            Office.context.ui.messageParent(nachricht);
            erledigt = true;
        } catch (e) {
            ohneOffice();
        }
    }
    var start = Date.now();
    (function warten() {
        if (window.Office && typeof Office.onReady === 'function') {
            Office.onReady(function () {
                if (Office.context && Office.context.ui
                        && typeof Office.context.ui.messageParent === 'function') {
                    senden();
                } else {
                    ohneOffice();
                }
            });
            return;
        }
        if (Date.now() - start > OFFICE_WARTE_MS) { ohneOffice(); return; }
        setTimeout(warten, 100);
    })();
})();
