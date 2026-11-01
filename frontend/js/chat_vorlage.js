/**
 * Vorlage fuer das Chat-Eingabefeld, uebergeben von einer anderen Seite
 * (Wissensgraph → "Recherche starten").
 *
 * ⚠ VORBELEGT, NIE ABGESCHICKT: der Auftrag stammt aus einer Auswertung, nicht
 * vom Benutzer selbst – er soll ihn lesen und bewusst absenden. Eine Vorlage
 * gilt fuenf Minuten und wird beim Lesen geloescht, damit sie nicht bei jedem
 * spaeteren Oeffnen von /chat wieder auftaucht.
 */
(function () {
    'use strict';
    var SCHLUESSEL = 'jarvis_chat_vorlage';
    var GUELTIG_MS = 5 * 60 * 1000;

    function lesen() {
        var v = null;
        try {
            v = JSON.parse(localStorage.getItem(SCHLUESSEL) || 'null');
            localStorage.removeItem(SCHLUESSEL);
        } catch (e) { return null; }
        if (!v || typeof v.text !== 'string' || !v.text.trim()) { return null; }
        if (typeof v.zeit !== 'number' || Date.now() - v.zeit > GUELTIG_MS) { return null; }
        return v.text.slice(0, 10000);
    }

    function einsetzen() {
        var feld = document.getElementById('msg-input');
        if (!feld) { return; }
        var text = lesen();
        if (!text) { return; }
        feld.value = text;
        // Das Feld waechst ueber sein input-Ereignis mit (Hoehe, Sende-Knopf).
        feld.dispatchEvent(new Event('input', { bubbles: true }));
        feld.focus();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', einsetzen);
    } else {
        einsetzen();
    }
    window.ChatVorlage = { lesen: lesen, einsetzen: einsetzen, SCHLUESSEL: SCHLUESSEL };
})();
