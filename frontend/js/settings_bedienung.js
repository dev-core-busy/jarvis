/* ═══════════════════════════════════════════════════════════════════════
   Klick-Zuhoerer der Einstellungsseite (/settings)
   ───────────────────────────────────────────────────────────────────────
   BSI H4, CSP ohne Inline-Skript (2026-10-04): settings.html trug bis hierher
   rund 40 Inline-Handler (onclick="…"). Eine Content-Security-Policy mit
   `script-src 'self'` ohne 'unsafe-inline' blockiert jeden davon – die Knoepfe
   waeren beim Umschalten auf "erzwingen" tot. Die Handler stehen jetzt hier.

   Markierung im Markup: `data-klick="<name>"`. Der Name wird NUR gegen die
   feste Tabelle KLICK unten aufgeloest – ausdruecklich KEIN Dispatcher, der
   einen Funktionspfad aus dem Attribut liest (das waere ein Script-Gadget, mit
   dem eingeschleustes Markup beliebige globale Funktionen aufrufen koennte und
   die CSP aushebelte). Unbekannte Namen tun nichts.

   Gebunden wird ueber die Eigenschaft `el.onclick`, NICHT addEventListener:
   das ist derselbe Platz, den das fruehere Attribut belegte. Das ist wichtig,
   weil vision.js spaeter `vis-wizard-confirm.onclick = …` setzt und den
   Rueckfall-Handler damit bewusst ERSETZT – mit addEventListener liefen beide
   und das Training startete doppelt. `this` ist wie frueher das Element.

   Eingebunden SYNCHRON am Ende von <body> VOR allen anderen Skripten: alle
   markierten Elemente stehen dann schon im Dokument, und wer (vision.js) den
   Platz danach ueberschreibt, tut das wie bisher nach uns.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    // Klappkopf eines Diagnose-Abschnitts (Telemetrie-Reiter): Koerper ist das
    // naechste Geschwister, Pfeil wechselt, beim Oeffnen wird nachgeladen.
    // 1:1 die fruehere Inline-Closure (function(h){…})(this).
    function klappe(h, nachladen) {
        var b = h.nextElementSibling;
        b.style.display = b.style.display === 'none' ? 'block' : 'none';
        h.querySelector('.kb-folder-arrow').textContent = b.style.display === 'none' ? '▶' : '▼';
        if (b.style.display !== 'none') nachladen();
    }

    var KLICK = {
        // Wissens-Synchronisation: Funktionsbeschreibung + Freigabe-Dialog
        'kbsync-info-drucken': function () { window.KnowledgeSync.drucken(); },
        'kbsync-info-schliessen': function () { window.KnowledgeSync.openInfo(false); },
        'kbsync-info-oeffnen': function (event) {
            event.stopPropagation();
            window.KnowledgeSync.openInfo(true);
        },
        'kbsync-share-schliessen': function () { window.KnowledgeSync.closeShare(); },

        // Prompt optimieren (Aufraeumen) + Wissens-Verdichtung
        'kb-cleanup-schliessen': function () { window.knowledgeManager.cleanupSchliessen(); },
        'kb-cleanup-uebernehmen': function () { window.knowledgeManager.cleanupUebernehmen(); },
        'kb-cleanup-oeffnen': function () {
            if (window.knowledgeManager) window.knowledgeManager.cleanupOeffnen();
        },
        'kb-compact-schliessen': function () { window.knowledgeManager.showCompactInfo(false); },

        // Wissen: WebDAV-Zugang und Netzwerk-Freigaben
        'webdav-speichern': function () { window._saveWebdavCredentials(); },
        'mount-verbinden': function () { window.knowledgeManager.saveMount(); },
        'mount-abbrechen': function () {
            document.getElementById('kb-mount-form').style.display = 'none';
        },

        // Vision: Rueckfall, solange vision.js den Platz nicht selbst belegt hat
        'vis-wizard-training': function () {
            if (window.visionManager) {
                window.visionManager._confirmWizardTraining().catch(function (e) { alert('Fehler: ' + e.message); });
            } else {
                alert('visionManager nicht geladen');
            }
        },
        'vis-wizard-speichern': function () {
            if (window.visionManager) {
                window.visionManager._saveWizardAction().catch(function (e) { alert('Fehler: ' + e.message); });
            } else {
                alert('visionManager nicht geladen');
            }
        },
        'vis-stream-tools': function () { window.visionManager._downloadStreamTools(); },

        // Telemetrie-Reiter: Klappkoepfe und Bedienelemente darin
        'tele-convlog-klappen': function () {
            klappe(this, function () { if (window.telemetryManager) window.telemetryManager._loadConvLog(); });
        },
        'tele-errors-klappen': function () {
            klappe(this, function () { if (window.telemetryManager) window.telemetryManager._loadErrors(); });
        },
        'audit-klappen': function () {
            klappe(this, function () { if (window.auditManager) window.auditManager.init(); });
        },
        // Weitere Protokolle (journal, csp, updates, ssh, fixes, abh): EIN Eintrag,
        // der Abschnitt steht im data-plog-Attribut des Kopfes.
        'plog-klappen': function () {
            var name = this.getAttribute('data-plog');
            klappe(this, function () { if (window.Protokolle) window.Protokolle.init(name); });
        },
        'sprot-klappen': function () {
            klappe(this, function () { if (window.sicherheitsProtokoll) window.sicherheitsProtokoll.init(); });
        },
        // Bedienelement im Klappkopf: Klick darf den Abschnitt nicht umklappen
        'nicht-klappen': function (event) { event.stopPropagation(); },

        // Firmenverzeichnis (AD) – Funktionen aus settings_ad.js
        'ad-speichern': function () { window._adSave(); },
        'ad-testen': function () { window._adTest(); },

        // System-Einstellungen als Tabelle: "Details" klappt die Erlaeuterungs-
        // zeile direkt unter der eigenen Zeile auf und zu.
        'systab-details': function () {
            var tr = this.closest('tr');
            var hint = tr && tr.nextElementSibling;
            if (!hint || !hint.classList.contains('systab-hint')) return;
            hint.hidden = !hint.hidden;
            this.setAttribute('aria-expanded', hint.hidden ? 'false' : 'true');
        }
    };

    document.querySelectorAll('[data-klick]').forEach(function (el) {
        var name = el.getAttribute('data-klick');
        if (Object.prototype.hasOwnProperty.call(KLICK, name)) el.onclick = KLICK[name];
    });
})();
