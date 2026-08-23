/* ============================================================
 * cpubar.js – CPU-Auslastung in der Titelleiste (shared)
 *
 * Wird auf JEDER Seite mit Titelleiste geladen und baut die Anzeige
 * selbst auf, wenn sie im Markup fehlt. Bis 2026-08-22 gab es VIER
 * eigene Fassungen (chat.js, support.js, userchat.js, wissen.js) und
 * damit auf der Haelfte der Unterseiten gar keine CPU-Anzeige.
 *
 * API (optional – die Anzeige laeuft ohne jeden Aufruf):
 *   JarvisCpuBar.setzeWert(prozent)  – Wert von aussen setzen (/chat
 *                                      bekommt ihn ueber das WS-Ereignis)
 *   JarvisCpuBar.stop()              – Abfrage beenden
 *
 * Der Takt laeuft dauerhaft und prueft bei jedem Durchgang selbst, ob ein
 * Sitzungstoken vorliegt: so erscheint die Anzeige nach dem Anmelden ohne
 * Zutun der Seite und bleibt auf der Anmeldemaske aus. Nach 401/403 wird
 * die Abfrage eingestellt – weiter zu klopfen fuellt nur das Journal.
 * ============================================================ */
(function () {
    'use strict';

    if (window.JarvisCpuBar) return;   // doppeltes Laden vermeiden

    var TAKT_MS = 3000;
    // Gleiche Kette wie issues.js: app.js, chat.js, userchat.js
    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];

    // Titelleisten-Container der einzelnen Seiten, in dieser Reihenfolge
    // durchsucht. Die Anzeige gehoert LINKS neben den Titel, nicht in die
    // Symbolgruppe rechts.
    var ANKER = ['.topbar-left', '.wi-topbar', '.pt-topbar', '.ad-top', '.sa-topbar'];

    var timer = null, balken = null, fuellung = null, beschriftung = null, aus = false;

    function token() {
        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            var v = null;
            try { v = localStorage.getItem(TOKEN_KEYS[i]); } catch (e) { v = null; }
            if (v) return v;
        }
        return '';
    }

    // Vorhandene Anzeige uebernehmen (chat/support/userchat/wissen bringen
    // sie im Markup mit) oder eine neue bauen. Gebaut wird sie NUR, wenn ein
    // Anker gefunden wird – auf einer Seite ohne Titelleiste entsteht nichts.
    function aufbauen() {
        if (balken) return true;
        balken = document.getElementById('cpu-bar');
        if (!balken) {
            var wirt = null;
            for (var i = 0; i < ANKER.length && !wirt; i++) wirt = document.querySelector(ANKER[i]);
            if (!wirt) return false;
            balken = document.createElement('div');
            balken.id = 'cpu-bar';
            balken.className = 'jv-cpu-bar';
            balken.title = 'CPU-Auslastung';
            balken.setAttribute('data-i18n-title', 'wissen.cpu_load');
            balken.innerHTML = '<div class="cpu-bar-fill" id="cpu-bar-fill" style="width:0%"></div>'
                             + '<span class="cpu-bar-label" id="cpu-bar-label">CPU: 0%</span>';
            // Vor den Abstandhalter bzw. ans Ende der linken Gruppe: der
            // Titel und der LLM-Punkt sollen davor stehen bleiben.
            var luecke = wirt.querySelector('.pt-spacer, .wi-spacer, .ad-spacer, .sa-spacer');
            if (luecke) wirt.insertBefore(balken, luecke); else wirt.appendChild(balken);
        }
        fuellung = document.getElementById('cpu-bar-fill');
        beschriftung = document.getElementById('cpu-bar-label');
        return !!(fuellung && beschriftung);
    }

    function sichtbar(an) {
        if (!balken) return;
        balken.style.display = an ? '' : 'none';
        // /wissen versteckt die Anzeige ueber eine Klasse – sonst gewinnt sie
        // gegen das Inline-`display` und die Anzeige bliebe unsichtbar.
        if (an) balken.classList.remove('hidden');
    }

    function setzeWert(prozent) {
        if (!aufbauen()) return;
        var p = Math.max(0, Math.min(100, Number(prozent) || 0));
        fuellung.style.width = p + '%';
        fuellung.style.backgroundPosition = p + '% 0';
        beschriftung.textContent = 'CPU: ' + Math.round(p) + '%';
        sichtbar(true);
    }

    function abfragen() {
        if (aus) return;
        var t = token();
        if (!t) { if (aufbauen()) sichtbar(false); return; }
        if (!aufbauen()) return;
        fetch('/api/cpu', { headers: { 'Authorization': 'Bearer ' + t } })
            .then(function (r) {
                if (r.status === 401 || r.status === 403) { stop(); return null; }
                return r.ok ? r.json() : null;
            })
            .then(function (d) { if (d) setzeWert(d.cpu); })
            .catch(function () {});
    }

    function stop() {
        aus = true;
        if (timer) { clearInterval(timer); timer = null; }
    }

    function start() {
        if (timer || aus) return;
        abfragen();
        timer = setInterval(abfragen, TAKT_MS);
    }

    window.JarvisCpuBar = { setzeWert: setzeWert, stop: stop };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
