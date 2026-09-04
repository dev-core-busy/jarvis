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
 * ⚠ DAS AUGE ZEIGT AUCH DAS GESPEICHERTE KENNWORT – auf ausdrueckliche,
 * wiederholte Anweisung des Betreibers (2026-09-04): "das Kennwort wird auf
 * Klick darauf Sichtbar !!!! UEBERALL umsetzen". Die frueher hier notierte
 * Zusage ("kein Endpunkt gibt ein Kennwort heraus") ist damit fuer genau
 * diesen einen, protokollierten Abrufweg aufgehoben; fuer alle Listen- und
 * Status-Endpunkte gilt sie unveraendert weiter. Begruendung und Preis stehen
 * im Kopf von backend/secret_reveal.py.
 *
 * WIE: ein Feld, hinter dem ein gespeicherter Wert liegt, traegt
 * `data-pw-quelle="<bereich>"` und `data-pw-kennung="<was genau>"`. Beim ersten
 * Klick auf das Auge holt das Modul den Klartext (POST /api/secret/reveal) und
 * setzt ihn ins Feld.
 *
 * ⚠ GEHOLT WIRD ERST BEIM KLICK, nicht beim Laden der Seite. Das ist der
 * Unterschied zwischen "ein Geheimnis liegt in jeder Seitenantwort und im DOM"
 * und "es geht ueber die Leitung, wenn ein Mensch es ausdruecklich sehen will"
 * – und nur so ist der Abruf ueberhaupt protokollierbar.
 *
 * DIE STERNE BLEIBEN: wo ein Kennwort hinterlegt ist, steht als Platzhalter
 * eine Punktreihe – die Information "hier ist etwas gespeichert", solange
 * niemand hinsieht. Der Satz "leer lassen = unveraendert" darf dabei NICHT
 * verlorengehen (er beschreibt echtes Verhalten): er wandert in den Titel.
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
            // ⚠ HANDVERDRAHTETE AUGEN ERKENNEN – und zwar an der EIGENSCHAFT,
            // nicht an einer Namensliste. Die erste Fassung prueste nur
            // `^btn-eye-`; die vorhandenen Knoepfe heissen aber auch
            // `btn-toggle-profile-apikey`, `cf-token-toggle` oder tragen bloss
            // die Klasse `sap-eye`. Ergebnis war ein ZWEITES Auge daneben – auf
            // DEV am Profil-Formular gemessen. Ein Zeichen-Knopf neben einem
            // KENNWORTFELD ist in diesem Projekt immer ein Auge; ein
            // Themenschalter steht nie dort.
            if (k.tagName === 'BUTTON'
                && /eye|auge|toggle/i.test((k.id || '') + ' ' + (k.className || ''))) {
                return true;
            }
        }
        return false;
    }

    function tokenHolen() {
        try { return localStorage.getItem('jarvis_token') || ''; }
        catch (e) { return ''; }
    }

    /**
     * Den GESPEICHERTEN Wert nachladen und ins Feld setzen.
     *
     * Drei Schranken, jede aus einem eigenen Grund:
     *  - nur wenn das Feld LEER ist: steht dort schon etwas, hat der Benutzer
     *    getippt – ein Abruf darf seine Eingabe nicht ueberschreiben;
     *  - nur EINMAL je Feld (`pwGeholt`), sonst fragt jedes Auf- und Zuklappen
     *    erneut und laeuft in die Drossel des Endpunkts;
     *  - nur mit `data-pw-quelle`: ohne Quelle gibt es nichts zu holen (die
     *    Felder beim Kennwortwechsel etwa haben keinen gespeicherten Wert).
     */
    function klartextHolen(inp, knopf) {
        var quelle = inp.dataset.pwQuelle;
        if (!quelle || inp.value || inp.dataset.pwGeholt) return;
        inp.dataset.pwGeholt = '1';
        knopf.title = t('common.pw_loading', 'Wird geholt…');
        fetch('/api/secret/reveal', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json',
                       'Authorization': 'Bearer ' + tokenHolen() },
            body: JSON.stringify({ bereich: quelle,
                                   kennung: inp.dataset.pwKennung || '' })
        }).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (d) {
                return { ok: r.ok, d: d };
            });
        }).then(function (e) {
            beschriften(inp, knopf);
            if (e.ok && typeof e.d.wert === 'string' && e.d.wert) {
                inp.value = e.d.wert;
                // Der Sterne-Platzhalter hat seinen Zweck erfuellt – er stand
                // fuer genau den Wert, der jetzt im Feld steht.
                if (/^•+$/.test(inp.placeholder || '')) inp.placeholder = '';
                // `input` feuern: Zeichenzaehler und Formular-Spiegel haengen
                // daran (dieselbe Lehre wie beim Uebernehmen-Knopf in /tracks).
                inp.dispatchEvent(new Event('input', { bubbles: true }));
                return;
            }
            // Kein Wert ist keine Stoerung, sondern eine AUSKUNFT (nichts
            // gespeichert / nicht berechtigt / Drossel). Sie gehoert an das
            // Feld – eine Konsolenmeldung liest niemand.
            var txt = (e.d && (e.d.error || e.d.detail))
                || t('common.pw_none', 'Kein gespeicherter Wert abrufbar.');
            inp.dataset.pwGeholt = '';      // ein zweiter Versuch bleibt moeglich
            knopf.title = String(txt).slice(0, 200);
            knopf.setAttribute('aria-label', knopf.title);
        }).catch(function () {
            beschriften(inp, knopf);
            inp.dataset.pwGeholt = '';
        });
    }

    // ⚠ DIE BESCHRIFTUNG WIRD AUS DEM ZUSTAND DES FELDES ABGELEITET, an EINER
    // Stelle. Die erste Fassung merkte sich in `klartextHolen` den Titel VOR
    // dem Abruf und stellte ihn danach wieder her – der Abruf laeuft aber
    // asynchron und war erst fertig, NACHDEM `umschalten` "verbergen"
    // gesetzt hatte: das Auge sagte "Kennwort anzeigen", waehrend es das
    // Kennwort zeigte. Erst der Lauf im echten Chrome hat es gezeigt.
    function beschriften(inp, knopf) {
        var sichtbar = inp.type !== 'password';
        var titel = sichtbar
            ? t('common.pw_hide', 'Kennwort verbergen')
            : (inp.dataset.pwQuelle
                ? t('common.pw_show_stored', 'Kennwort anzeigen')
                : t('common.pw_show', 'Eingabe anzeigen'));
        knopf.title = titel;
        knopf.setAttribute('aria-label', titel);
        knopf.setAttribute('aria-pressed', sichtbar ? 'true' : 'false');
    }

    function umschalten(inp, knopf) {
        // Beim Klick ist das Feld sicher sichtbar – der guenstigste Moment,
        // die Lage des Auges nachzurechnen (Guertel zu den Beobachtern).
        if (inp.parentElement) ausrichten(inp, knopf, inp.parentElement);
        var verborgen = inp.type === 'password';
        if (verborgen) klartextHolen(inp, knopf);
        inp.type = verborgen ? 'text' : 'password';
        knopf.innerHTML = verborgen
            ? (window.JarvisIcons ? window.JarvisIcons.eyeOff() : '&#128065;')
            : (window.JarvisIcons ? window.JarvisIcons.eye() : '&#128065;');
        beschriften(inp, knopf);
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
                breiteUebernehmen(inp, wrap);
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
        ausrichten(inp, knopf, wirt);
        // Anfangszustand ueber dieselbe Funktion setzen (ein zweiter Aufruf
        // kippt sie sonst) – deshalb erst auf 'text' stellen und zurueck.
        inp.type = 'text';
        umschalten(inp, knopf);
        beobachteBreite(inp, knopf, wirt);
    }

    // ⚠ DER WRAPPER MUSS SO BREIT SEIN WIE DAS FELD – sonst klebt das Auge am
    // Rand des CONTAINERS. Auf DEV gemessen: ein 538 px breites Feld in einem
    // 897 px breiten Container, das Auge 351 px daneben.
    //
    // Das laesst sich DETERMINISTISCH loesen, also ohne auf eine Messung zu
    // warten – und das ist der Punkt: die meisten dieser Felder entstehen in
    // einem GESCHLOSSENEN Dialog, wo es nichts zu messen gibt (alle Rechtecke
    // 0). `getComputedStyle` liefert dort trotzdem die ANGEGEBENE Breite.
    //
    //   * Laenge oder Prozent ('60%', '100%', '225px') → der Wrapper bekommt
    //     genau diese Breite, und das Feld darin 100 %. Ohne das zweite waeren
    //     60 % von 60 % = 36 % – das Feld wuerde schmaler.
    //   * 'auto' (Vorgabebreite eines <input>) → 'fit-content'. Bewusst NICHT
    //     'inline-block': das wuerde den Wrapper in den Textfluss stellen und
    //     das Feld neben seinen Nachbarn ziehen, also das Layout aendern.
    function breiteUebernehmen(inp, wrap) {
        var cw = '';
        try { cw = getComputedStyle(inp).width || ''; } catch (e) { return; }
        if (cw && cw !== 'auto' && /(%|px|r?em|v[wh]|ch)$/.test(cw)) {
            wrap.style.width = cw;
            inp.style.width = '100%';
        } else {
            wrap.style.width = 'fit-content';
        }
    }

    // ⚠ DAS AUGE MUSS AN DIE RECHTE KANTE DES FELDES, NICHT DES CONTAINERS.
    // Das CSS setzt `right: 8px` – bezogen ist das auf den Wrapper, und der ist
    // ein Block ueber die ganze Breite. Wo ein Feld den Container NICHT
    // ausfuellt (die Freigaben-Formulare haben 225 px breite Felder in einem
    // 957 px breiten Formular), klebte das Auge damit 700 px daneben – im
    // echten Chrome auf DEV gemessen, in jsdom NICHT sichtbar (dort gibt es
    // kein Layout).
    //
    // Gerechnet wird ueber die RECHTECKE, nicht ueber `offsetLeft`: welches
    // Element `offsetParent` ist, haengt am Positionierungs-Kontext, und der
    // ist bei `jv-pw-host` ein anderer als bei `jv-pw-wrap`.
    function ausrichten(inp, knopf, wirt) {
        try {
            var rw = wirt.getBoundingClientRect(), ri = inp.getBoundingClientRect();
            // Verborgen ist NICHT messbar (alle Rechtecke 0). Dann bleibt der
            // CSS-Wert stehen und der Beobachter unten holt es nach, sobald das
            // Feld sichtbar wird – dieselbe Falle wie bei der Vorfallsliste.
            if (ri.width < 1 || rw.width < 1) return;
            var abstand = Math.round(rw.right - ri.right) + 8;
            knopf.style.right = Math.max(4, abstand) + 'px';
        } catch (e) { /* Layout kann fehlen (jsdom) – dann gilt das CSS */ }
    }

    function beobachteBreite(inp, knopf, wirt) {
        var nach = function () { ausrichten(inp, knopf, wirt); };
        var etwas = false;
        try {
            if (typeof ResizeObserver === 'function') {
                var ro = new ResizeObserver(nach);
                ro.observe(inp);
                ro.observe(wirt);
                etwas = true;
            }
        } catch (e) { /* weiter mit dem Rueckfall */ }
        // ⚠ DER RESIZE-BEOBACHTER ALLEIN GENUEGT NICHT, und das ist gemessen:
        // die meisten dieser Felder entstehen in einem GESCHLOSSENEN Dialog
        // bzw. Klapp-Container. Dort haben sie keine Box; wird der Container
        // spaeter geoeffnet, kam im echten Chrome KEINE Groessenmeldung – das
        // Auge blieb an der rechten Kante des Containers stehen (auf DEV
        // gemessen: 351 px neben dem Feld). Der Sichtbarkeits-Beobachter feuert
        // in genau diesem Moment.
        try {
            if (typeof IntersectionObserver === 'function') {
                var io = new IntersectionObserver(function (eintraege) {
                    for (var i = 0; i < eintraege.length; i++) {
                        if (eintraege[i].isIntersecting) { nach(); return; }
                    }
                });
                io.observe(inp);
                etwas = true;
            }
        } catch (e) { /* weiter mit dem Rueckfall */ }
        // Rueckfall ohne Beobachter (und fuer jsdom): beim naechsten
        // Fensterwechsel und einmal verzoegert nachrechnen.
        try {
            window.addEventListener('resize', nach);
            // Zeigerkontakt und Fokus sind Ereignisse, die nicht am
            // Rendering-Takt haengen – sie kommen auch dort an, wo die
            // Beobachter (headless, gedrosselter Hintergrund-Tab) nichts
            // liefern. Guertel, nicht Hosentraeger: der Regelfall ist die
            // uebernommene Breite oben.
            wirt.addEventListener('pointerenter', nach);
            wirt.addEventListener('focusin', nach);
            if (!etwas) setTimeout(nach, 300);
        } catch (e) { /* egal */ }
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
