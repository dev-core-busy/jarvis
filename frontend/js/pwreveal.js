/* Auge an JEDEM Kennwortfeld – eine Stelle fuer die ganze Anwendung.
 *
 * VORGABE DES BETREIBERS (2026-09-04): "korrigiere im gesamten Kennwort
 * Felder, die nach dem Prinzip 'Passwort (leer = unve...' aufgebaut sind. Ich
 * moechte UEBERALL stattdessen ein Passwortfeld mit Sternen und der Option den
 * Inhalt mit unserem Auge anzuzeigen."
 *
 * WARUM EIN MODUL UND NICHT 43 EINZELAENDERUNGEN (gezaehlt: 43 Felder in 17
 * Dateien): dieselbe Begruendung wie bei cpubar.js und logo_home.js – die
 * Handarbeit-Variante lag bei der CPU-Anzeige in vier Fassungen vor und fehlte
 * auf sechs Seiten. Und mehr als die Haelfte dieser Felder entsteht erst zur
 * LAUFZEIT aus JS-Templates (knowledge.js, skillcfg.js, google.js,
 * ldap_picker.js, sap.js, vemas.js, email*.js): eine Aenderung am Markup
 * erreicht sie ueberhaupt nicht. Deshalb ein MutationObserver – der naechste
 * Dialog bekommt sein Auge ohne eine Zeile Zusatzarbeit.
 *
 * ⚠ WAS DAS AUGE NICHT KANN, und das steht auch in seiner Beschriftung:
 * es zeigt AUSSCHLIESSLICH, was gerade im Feld getippt steht. Ein
 * GESPEICHERTES Kennwort gibt kein Endpunkt dieses Projekts heraus – das ist
 * eine mehrfach dokumentierte Zusage (mail_accounts, sap_accounts,
 * vemas_accounts, jira_accounts: "kein Endpunkt gibt ein Kennwort heraus").
 * Ein Auge, das etwas anderes verspricht, waere eine Zusage, die die
 * Architektur nicht einloest.
 *
 * DESHALB DIE STERNE: wo ein Kennwort hinterlegt ist, steht als Platzhalter
 * eine Punktreihe – das ist die Information "hier ist etwas gespeichert",
 * ohne sie herauszugeben. Der Satz "leer lassen = unveraendert" darf dabei
 * NICHT verlorengehen (er beschreibt echtes Verhalten): er wandert in den
 * Titel des Feldes.
 */
(function () {
    'use strict';

    var MARKE = 'jvPwEye';                 // dataset-Merker: schon versorgt
    var PLATZHALTER_STERNE = '••••••••';

    function t(schluessel, rueckfall) {
        try {
            if (typeof window.t === 'function') {
                var s = window.t(schluessel);
                if (s && s !== schluessel) return s;
            }
        } catch (e) { /* i18n noch nicht geladen */ }
        return rueckfall;
    }

    /**
     * Hat dieses Feld schon ein Auge? Erkennt AUCH die handverdrahteten
     * (settings.html + app.js::_wireEyeBtn) – die funktionieren, haben eigene
     * Zusatzlogik und werden nicht angefasst. Ohne diese Pruefung staenden
     * zwei Augen uebereinander.
     */
    function schonVersorgt(inp) {
        if (inp.dataset[MARKE]) return true;
        var eltern = inp.parentElement;
        if (!eltern) return false;
        // ⚠ NUR DIREKTE GESCHWISTER, NICHT NACHFAHREN. Die erste Fassung nahm
        // `eltern.querySelector('.jv-pw-eye')` – und querySelector sucht im
        // ganzen Teilbaum: sobald ein Container ZWEI Kennwortfelder enthaelt
        // ("neues Kennwort" + "bestaetigen" liegen oft im selben div), fand die
        // Pruefung fuer das zweite Feld das Auge des ERSTEN und uebersprang es.
        // Vom eigenen Waechter gefunden.
        for (var k = eltern.firstElementChild; k; k = k.nextElementSibling) {
            if (k === inp) continue;
            if (k.classList && k.classList.contains('jv-pw-eye')) return true;
            if (k.tagName === 'BUTTON' && /^btn-eye-/.test(k.id || '')) return true;
        }
        return false;
    }

    function umschalten(inp, knopf) {
        var verborgen = inp.type === 'password';
        inp.type = verborgen ? 'text' : 'password';
        knopf.innerHTML = verborgen
            ? (window.JarvisIcons ? window.JarvisIcons.eyeOff() : '&#128065;')
            : (window.JarvisIcons ? window.JarvisIcons.eye() : '&#128065;');
        var titel = verborgen
            ? t('common.pw_hide', 'Eingabe verbergen')
            : t('common.pw_show', 'Eingabe anzeigen (zeigt nur, was du tippst)');
        knopf.title = titel;
        knopf.setAttribute('aria-label', titel);
        knopf.setAttribute('aria-pressed', verborgen ? 'true' : 'false');
    }

    function versorge(inp) {
        if (!inp || inp.type !== 'password' || schonVersorgt(inp)) return;
        inp.dataset[MARKE] = '1';

        // Ein leeres Kennwortfeld, hinter dem ein gespeicherter Wert liegt,
        // zeigt Sterne statt eines erklaerenden Satzes. Die Erklaerung selbst
        // geht nicht verloren – sie steht im Titel.
        var hat = inp.dataset.pwGesetzt === '1'
            || /leer|empty|unver|unchanged/i.test(inp.placeholder || '');
        if (hat) {
            inp.placeholder = PLATZHALTER_STERNE;
            if (!inp.title) inp.title = t('common.pw_keep',
                'Ein Kennwort ist gespeichert. Leer lassen = unverändert.');
        }

        // Der Wrapper wird nur angelegt, wenn es keinen tauglichen gibt: viele
        // Felder liegen schon in einem positionierten Container (dort wuerde
        // ein zweiter das Layout verschieben).
        var wirt = inp.parentElement;
        var eigener = false;
        if (!wirt || !wirt.classList.contains('jv-pw-wrap')) {
            var pos = wirt ? (getComputedStyle(wirt).position || 'static') : 'static';
            if (pos === 'static' || wirt.children.length > 1) {
                var wrap = document.createElement('span');
                wrap.className = 'jv-pw-wrap';
                inp.parentNode.insertBefore(wrap, inp);
                wrap.appendChild(inp);
                wirt = wrap;
                eigener = true;
            }
        }
        if (!wirt) return;
        if (!eigener && !wirt.classList.contains('jv-pw-wrap')) {
            wirt.classList.add('jv-pw-host');
        }

        var knopf = document.createElement('button');
        knopf.type = 'button';                 // NIE submit: das Auge in einem
        knopf.className = 'jv-pw-eye';         // <form> haette sonst abgesendet
        knopf.tabIndex = 0;
        knopf.addEventListener('click', function (ev) {
            ev.preventDefault();
            ev.stopPropagation();              // nicht die Zeile darunter treffen
            umschalten(inp, knopf);
            try { inp.focus(); } catch (e) { /* egal */ }
        });
        wirt.appendChild(knopf);
        // Anfangszustand ueber dieselbe Funktion setzen (ein zweiter Aufruf
        // kippt sie sonst) – deshalb erst auf 'text' stellen und zurueck.
        inp.type = 'text';
        umschalten(inp, knopf);
    }

    function alle(wurzel) {
        try {
            (wurzel || document).querySelectorAll('input[type="password"]')
                .forEach(versorge);
        } catch (e) { /* nichts kaputt machen */ }
    }

    function start() {
        alle(document);
        // ⚠ DER BEOBACHTER IST DER KERN: die meisten Kennwortfelder entstehen
        // erst beim Oeffnen eines Dialogs aus einem Template-String. Ein
        // einmaliger Durchlauf beim Laden erwischt sie NICHT.
        try {
            var beob = new MutationObserver(function (aend) {
                for (var i = 0; i < aend.length; i++) {
                    var a = aend[i];
                    if (a.type === 'attributes' && a.target
                            && a.target.tagName === 'INPUT') {
                        versorge(a.target);     // type nachtraeglich gesetzt
                        continue;
                    }
                    for (var j = 0; j < a.addedNodes.length; j++) {
                        var n = a.addedNodes[j];
                        if (n.nodeType !== 1) continue;
                        if (n.tagName === 'INPUT') versorge(n);
                        else alle(n);
                    }
                }
            });
            beob.observe(document.documentElement,
                         { childList: true, subtree: true,
                           attributes: true, attributeFilter: ['type'] });
        } catch (e) { /* alte Browser: dann nur die Felder beim Laden */ }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }

    window.JarvisPwEye = { versorge: versorge, alle: alle };
})();
