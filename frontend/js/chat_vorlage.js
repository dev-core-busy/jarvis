/**
 * Vorlage fuer das Chat-Eingabefeld, uebergeben von einer anderen Seite
 * (Wissensgraph → "Recherche starten").
 *
 * ⚠ VORBELEGT, NIE ABGESCHICKT: der Auftrag stammt aus einer Auswertung, nicht
 * vom Benutzer selbst – er soll ihn lesen und bewusst absenden. Eine Vorlage
 * gilt fuenf Minuten und wird beim Lesen geloescht, damit sie nicht bei jedem
 * spaeteren Oeffnen von /chat wieder auftaucht.
 *
 * Traegt die Vorlage `neu: true`, oeffnet /chat eine NEUE Konversation statt der
 * zuletzt benutzten (`neueSitzung()`, gefragt von chat.js::_initSessions).
 * ⚠ DIE REIHENFOLGE IST NICHT GARANTIERT: `einsetzen()` laeuft an
 * DOMContentLoaded und loescht die Vorlage, `_initSessions()` erst nach der
 * Anmeldepruefung – oder, falls die einmal schneller ist, davor. Deshalb merkt
 * sich `lesen()` den Wunsch, und `neueSitzung()` sieht sonst selbst nach (ohne
 * zu loeschen). Beantwortet wird er genau EINMAL – `_ensureSession()` ruft
 * `_initSessions()` ein zweites Mal, und dann darf keine zweite Konversation
 * entstehen.
 */
(function () {
    'use strict';
    var SCHLUESSEL = 'jarvis_chat_vorlage';
    var GUELTIG_MS = 5 * 60 * 1000;
    // null = noch nicht gelesen, true/false = Wunsch aus der gelesenen Vorlage.
    var _neuGewuenscht = null;
    var _neuBeantwortet = false;

    // Eine gueltige Vorlage oder null – ohne Seiteneffekt.
    function pruefen(roh) {
        var v = null;
        try { v = JSON.parse(roh || 'null'); } catch (e) { return null; }
        if (!v || typeof v.text !== 'string' || !v.text.trim()) { return null; }
        if (typeof v.zeit !== 'number' || Date.now() - v.zeit > GUELTIG_MS) { return null; }
        return v;
    }

    function lesen() {
        var roh = null;
        try {
            roh = localStorage.getItem(SCHLUESSEL);
            localStorage.removeItem(SCHLUESSEL);
        } catch (e) { return null; }
        var v = pruefen(roh);
        if (_neuGewuenscht === null) { _neuGewuenscht = !!(v && v.neu === true); }
        return v ? v.text.slice(0, 10000) : null;
    }

    function neueSitzung() {
        if (_neuBeantwortet) { return false; }
        _neuBeantwortet = true;
        if (_neuGewuenscht !== null) { return _neuGewuenscht; }
        var v = null;
        try { v = pruefen(localStorage.getItem(SCHLUESSEL)); } catch (e) { return false; }
        return !!(v && v.neu === true);
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
    window.ChatVorlage = { lesen: lesen, einsetzen: einsetzen, neueSitzung: neueSitzung, SCHLUESSEL: SCHLUESSEL };
})();
