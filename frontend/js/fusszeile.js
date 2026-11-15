/* fusszeile.js – Info-/Kontaktzeile des Portals auf allen Kachel-Seiten.

   Die Zeile stand bis 2026-11-15 nur als Markup in portal.html. Damit sie
   auf /sql, /email, /tracks usw. gleich aussieht und dieselben Werte traegt,
   baut sie jetzt dieses eine Skript – eine Quelle statt einer Kopie je Seite.

   Befuellt wird sie weiterhin von branding.js (applyPortalContact): das sucht
   die Elemente ueber ihre IDs (#pt-contact, #pt-contact-info ...). Die IDs
   bleiben deshalb unveraendert.

   REIHENFOLGE: dieses Skript MUSS vor i18n.js und branding.js eingebunden
   sein. i18n.js uebersetzt beim Laden nur, was dann schon im DOM steht, und
   branding.js setzt die Werte beim ersten Durchlauf – eine spaeter erzeugte
   Zeile bliebe deutsch bzw. auf den eingebauten Standardwerten stehen.

   Ort: Gibt es auf der Seite einen Platzhalter `[data-fusszeile]` (Portal:
   unter den Kacheln), wird er befuellt. Sonst haengt die Zeile am Ende von
   <body>. Eine bereits vorhandene #pt-contact wird nicht verdoppelt. */
(function () {
    'use strict';

    // Standardwerte wie bisher im Portal-Markup; branding.js ueberschreibt sie.
    var MARKUP =
        '<span id="pt-contact-info" data-i18n="portal.contact_info_default">universelles, modulares KI Portal</span>' +
        '<span class="pt-contact-sep hidden" id="pt-contact-phone-sep">·</span>' +
        '<span id="pt-contact-phone" class="hidden"><span data-i18n="portal.contact_phone_prefix">Tel.</span> ' +
            '<a id="pt-contact-phone-link" href=""></a></span>' +
        '<span class="pt-contact-sep" id="pt-contact-email-sep">·</span>' +
        '<span id="pt-contact-email"><a id="pt-contact-email-link" href="mailto:dev-core@web.de">dev-core@web.de</a></span>' +
        '<span class="pt-contact-sep hidden" id="pt-contact-manual-sep">·</span>' +
        '<span id="pt-contact-manual" class="hidden"><a id="pt-contact-manual-link" href="" target="_blank" ' +
            'rel="noopener" data-i18n="portal.contact_manual">Benutzerhandbuch</a></span>';

    function baue() {
        if (document.getElementById('pt-contact')) return;   // schon da
        var platz = document.querySelector('[data-fusszeile]');
        var el = platz || document.createElement('footer');
        el.id = 'pt-contact';
        el.classList.add('pt-contact');
        // Am Seitenende (ohne Platzhalter) mit eigenem Abstand, siehe theme.css
        if (!platz) el.classList.add('pt-contact-seite');
        el.innerHTML = MARKUP;
        if (!platz) document.body.appendChild(el);
    }

    if (document.body) baue();
    else document.addEventListener('DOMContentLoaded', baue);
})();
