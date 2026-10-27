/* ═══════════════════════════════════════════════════════════════════════
   Newsfeed-Laufband – EINE Fassung fuer /portal und die Vorschau unter
   Einstellungen → Newsfeed. Gestaltung in css/newsfeed.css.

   ABLAUF: eine Meldung bleibt `verweil_s` Sekunden stehen, rollt dann in
   `scroll_s` Sekunden nach oben aus dem Fenster, die naechste rollt hinterher.
   Hinter der letzten steht eine KOPIE der ersten: das Band rollt von der
   letzten auf die Kopie (sieht aus wie „weiter zur ersten") und springt danach
   ohne Uebergang auf die echte erste zurueck. Ohne die Kopie liefe das Band am
   Ende sichtbar rueckwaerts durch alle Meldungen.

   ⚠ VERSCHOBEN WIRD IN PROZENT DES BANDES, NICHT IN PIXELN. Alle Bloecke
   bekommen die Hoehe des hoechsten; dann ist Schritt i genau i/(n+1) der
   Bandhoehe – und das bleibt richtig, wenn sich die Hoehe nach einem
   Fensterwechsel oder dem Nachladen der Schrift aendert, waehrend ein
   Pixelwert aus der ersten Messung danach zwischen zwei Meldungen stehen
   bliebe.

   ⚠ DIE WARTEZEIT LAEUFT UEBER EINEN RESTWERT. Faehrt die Maus ueber die
   Kachel, haelt das Band an – und zwar Zeitgeber UND Fortschrittsbalken
   gemeinsam. Ein Zeitgeber, der einfach weiterliefe, liesse den Balken auf
   halber Strecke stehen und die Meldung trotzdem wechseln.

   ⚠ ZWEI GRUENDE ZUM ANHALTEN, NICHT EINER. Maus/Fokus halten nur so lange
   an, wie sie auf der Kachel sind; der Pause-Knopf haelt an, bis er wieder
   gedrueckt wird. Laege beides auf EINEM Merker, liefe das Band nach einem
   Klick auf „Pause" weiter, sobald die Maus die Kachel verlaesst.

   VOR/ZURUECK nehmen denselben Rollschritt wie der Ablauf. Zurueck von der
   ersten Meldung springt ohne Uebergang auf die Kopie hinter der letzten und
   rollt von dort eine Stufe hoch – sonst liefe das Band sichtbar vorwaerts
   durch alle Meldungen. Ein Klick mitten im Rollen schliesst den laufenden
   Schritt ab und rollt ab dessen Ziel weiter.

   „Bewegung reduzieren" (prefers-reduced-motion): ueberblenden statt rollen.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    // Neu laden alle fuenf Minuten: eine frische Meldung erreicht ein offen
    // stehendes Portal, ohne dass jemand neu laedt.
    var NACHLADEN_MS = 5 * 60 * 1000;

    function T(k, fb) {
        try { var v = window.t ? window.t(k) : ''; return (v && v !== k) ? v : fb; }
        catch (e) { return fb; }
    }

    function ruhig() {
        try {
            return !!(window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches);
        } catch (e) { return false; }
    }

    function datum(iso) {
        if (!iso) return '';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '';
        var lang = window._lang === 'en' ? 'en-GB' : 'de-DE';
        try {
            return d.toLocaleDateString(lang, { day: '2-digit', month: '2-digit', year: 'numeric' });
        } catch (e) { return iso.slice(0, 10); }
    }

    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) e.className = cls;
        if (text != null) e.textContent = text;
        return e;
    }

    function zahl(v, vorgabe) {
        var z = Number(v);
        return (v == null || isNaN(z) || z <= 0) ? vorgabe : z;
    }

    /**
     * Zeichnet das Laufband in `wurzel` und startet es.
     * @param wurzel     Element (bekommt die Klasse nf-kachel)
     * @param eintraege  [{titel, text, erstellt}] – in Anzeigereihenfolge
     * @param opts       {verweil_s, scroll_s}
     * @returns {stoppen: function} – haelt alle Zeitgeber an und raeumt Zuhoerer ab
     */
    function ticker(wurzel, eintraege, opts) {
        opts = opts || {};
        var verweilMs = zahl(opts.verweil_s, 3) * 1000;
        var scrollMs = zahl(opts.scroll_s, 0.8) * 1000;
        var liste = (eintraege || []).filter(function (e) { return e && (e.titel || e.text); });
        var n = liste.length;

        wurzel.classList.add('nf-kachel');
        wurzel.classList.remove('nf-pause');
        wurzel.setAttribute('role', 'region');
        wurzel.textContent = '';
        if (!n) { wurzel.hidden = true; return { stoppen: function () {} }; }

        var kopf = el('div', 'nf-kopf');
        kopf.appendChild(el('span', 'nf-puls'));
        var kopfText = el('span', 'nf-kopf-text', T('newsfeed.title', 'Neuigkeiten'));
        kopf.appendChild(kopfText);
        var zaehler = el('span', 'nf-zaehler');
        kopf.appendChild(zaehler);
        // Ablauf-Steuerung nur, wo es etwas zu blaettern gibt.
        var zurueckKnopf = null, pauseKnopf = null, vorKnopf = null;
        function knopf(cls, symbol, ersatz, wirkung) {
            var k = el('button', 'nf-knopf ' + cls);
            k.type = 'button';
            k.innerHTML = window.JarvisIcons ? window.JarvisIcons[symbol]() : ersatz;
            k.addEventListener('click', function (ev) {
                ev.preventDefault();
                wirkung();
            });
            kopf.appendChild(k);
            return k;
        }
        if (n > 1) {
            zurueckKnopf = knopf('nf-zurueck', 'prev', '\u2039', function () { springen(-1); });
            pauseKnopf = knopf('nf-pause-knopf', 'pause', '\u2016', umschalten);
            vorKnopf = knopf('nf-vor', 'next', '\u203a', function () { springen(1); });
        }
        // Schliessen (×) nur, wo der Aufrufer weiss, was es bedeutet – im
        // Portal blendet es bis zur naechsten Neuigkeit aus, in der Vorschau
        // des Reiters gibt es nichts zu schliessen.
        var zu = null;
        if (typeof opts.schliessen === 'function') {
            zu = el('button', 'nf-zu');
            zu.type = 'button';
            zu.innerHTML = window.JarvisIcons ? window.JarvisIcons.close() : '\u00d7';
            zu.addEventListener('click', function (ev) {
                ev.preventDefault();
                opts.schliessen(zu);
            });
            kopf.appendChild(zu);
        }
        var fenster = el('div', 'nf-fenster');
        var band = el('div', 'nf-band');
        fenster.appendChild(band);
        var fort = el('div', 'nf-fortschritt');
        var balken = el('div', 'nf-fortschritt-balken');
        fort.appendChild(balken);
        wurzel.appendChild(kopf);
        wurzel.appendChild(fenster);
        wurzel.appendChild(fort);
        wurzel.setAttribute('aria-label', kopfText.textContent);

        // Erstellungsdatum, bei einer Bearbeitung an einem ANDEREN Tag mit dem
        // Zusatz „aktualisiert" – eine Bearbeitung rueckt die Meldung nach vorn,
        // ohne den Zusatz saehe eine alte Meldung an erster Stelle wie ein
        // Sortierfehler aus.
        function datumText(erstellt, geaendert) {
            var t = datum(erstellt), g = datum(geaendert);
            return (g && g !== t) ? t + ' \u00b7 ' + T('newsfeed.updated', 'aktualisiert') + ' ' + g : t;
        }
        function beschriften(k, text) {
            if (!k) return;
            k.title = text;
            k.setAttribute('aria-label', text);
        }
        function zuTitel() {
            beschriften(zu, T('newsfeed.hide', 'Ausblenden, bis es Neues gibt'));
            beschriften(zurueckKnopf, T('newsfeed.prev', 'Vorherige Meldung'));
            beschriften(vorKnopf, T('newsfeed.next', 'Nächste Meldung'));
            if (pauseKnopf) {
                beschriften(pauseKnopf, fest ? T('newsfeed.play', 'Weiterlaufen lassen')
                                             : T('newsfeed.pause', 'Anhalten'));
                pauseKnopf.setAttribute('aria-pressed', fest ? 'true' : 'false');
                if (window.JarvisIcons) pauseKnopf.innerHTML = fest ? window.JarvisIcons.play() : window.JarvisIcons.pause();
                else pauseKnopf.textContent = fest ? '\u25b7' : '\u2016';
            }
        }

        var datumsFelder = [];
        function block(e, kopie) {
            var b = el('article', 'nf-block');
            var dz = el('div', 'nf-datum', datumText(e.erstellt, e.geaendert));
            dz.setAttribute('data-erstellt', e.erstellt || '');
            dz.setAttribute('data-geaendert', e.geaendert || '');
            datumsFelder.push(dz);
            b.appendChild(dz);
            b.appendChild(el('h3', 'nf-titel', e.titel || ''));
            b.appendChild(el('p', 'nf-text', e.text || ''));
            // Die Kopie ist reine Optik – ein Vorleseprogramm soll die erste
            // Meldung nicht zweimal ansagen.
            if (kopie) b.setAttribute('aria-hidden', 'true');
            return b;
        }
        liste.forEach(function (e) { band.appendChild(block(e, false)); });

        var bewegt = n > 1;
        var weich = !ruhig();
        if (bewegt && weich) band.appendChild(block(liste[0], true));
        var bloecke = band.children;
        var schritte = bloecke.length;   // n oder n+1 (mit Kopie)

        if (!bewegt) { fort.hidden = true; zaehler.hidden = true; }
        wurzel.hidden = false;

        // Hoehe: alle Bloecke so hoch wie der hoechste (Begruendung im Kopf).
        function messen() {
            var i, h = 0;
            for (i = 0; i < schritte; i++) bloecke[i].style.height = '';
            for (i = 0; i < schritte; i++) h = Math.max(h, bloecke[i].offsetHeight || 0);
            if (!h) return;   // kein Layout (verborgen) – min-height aus dem CSS traegt
            for (i = 0; i < schritte; i++) bloecke[i].style.height = h + 'px';
            fenster.style.height = h + 'px';
            // ⚠ Das min-height des CSS muss nach der Messung weichen: ist es
            // hoeher als ein Block, ragt der NAECHSTE unten ins Fenster (im
            // Screenshot gesehen: das Datum der Folgemeldung angeschnitten).
            fenster.style.minHeight = '0';
        }
        messen();

        // pausiert = Maus/Fokus auf der Kachel, fest = Pause-Knopf (Kopf).
        var idx = 0, zeitgeber = null, pausiert = false, fest = false, gestoppt = false;
        var startZeit = 0, rest = verweilMs;
        zuTitel();

        function zaehlerSetzen() {
            zaehler.textContent = ((idx % n) + 1) + '/' + n;
        }
        function verschieben(i, mitUebergang) {
            band.style.transition = mitUebergang
                ? 'transform ' + (scrollMs / 1000) + 's ease-in-out' : 'none';
            band.style.transform = i ? 'translateY(' + (-100 * i / schritte) + '%)' : '';
        }
        function balkenStarten(dauer) {
            balken.classList.remove('nf-laeuft');
            balken.style.animationDuration = (dauer / 1000) + 's';
            void balken.offsetWidth;   // Neustart der CSS-Animation erzwingen
            balken.classList.add('nf-laeuft');
        }
        function verweilen(dauer) {
            startZeit = Date.now();
            rest = dauer;
            zeitgeber = setTimeout(weiter, dauer);
        }
        function weiter() { schritt(1); }
        // Ein Schritt um `richtung` (+1/-1) – fuer den Ablauf wie fuer die Knoepfe.
        function schritt(richtung) {
            zeitgeber = null;
            // `startZeit` = 0 heisst: es laeuft gerade kein Verweilen, sondern
            // ein Rollschritt – den darf `anhalten` nicht abbrechen.
            startZeit = 0;
            if (gestoppt) return;
            balken.classList.remove('nf-laeuft');
            if (!weich) {
                // Ueberblenden: aus, umstellen, ein.
                band.style.transition = 'opacity ' + (scrollMs / 2000) + 's ease';
                band.style.opacity = '0';
                zeitgeber = setTimeout(function () {
                    if (gestoppt) return;
                    idx = (idx % n + richtung + n) % n;
                    band.style.transform = idx ? 'translateY(' + (-100 * idx / schritte) + '%)' : '';
                    band.style.opacity = '1';
                    zaehlerSetzen();
                    zeitgeber = setTimeout(naechsteRunde, scrollMs / 2);
                }, scrollMs / 2);
                return;
            }
            if (richtung < 0 && idx === 0) {
                // Von der ersten zurueck: erst ohne Uebergang auf die Kopie.
                idx = n;
                verschieben(idx, false);
                void band.offsetWidth;   // Sprung festschreiben, bevor gerollt wird
            }
            idx += richtung;
            verschieben(idx, true);
            zaehlerSetzen();
            zeitgeber = setTimeout(function () {
                if (gestoppt) return;
                // Auf der Kopie angekommen: ohne Uebergang zur echten ersten.
                if (idx >= n) { idx = 0; verschieben(0, false); }
                naechsteRunde();
            }, scrollMs);
        }
        function naechsteRunde() {
            zeitgeber = null;
            if (gestoppt) return;
            if (pausiert || fest) { rest = verweilMs; balkenStarten(verweilMs); return; }
            balkenStarten(verweilMs);
            verweilen(verweilMs);
        }

        // Anhalten nur WAEHREND des Verweilens: ein halber Rollschritt, der
        // stehen bleibt, zeigte zwei angeschnittene Meldungen.
        function einfrieren() {
            wurzel.classList.add('nf-pause');
            if (zeitgeber && startZeit) {
                // Nur ein laufendes VERWEILEN wird angehalten (startZeit gesetzt).
                clearTimeout(zeitgeber);
                zeitgeber = null;
                rest = Math.max(0, rest - (Date.now() - startZeit));
                startZeit = 0;
            }
        }
        function loslassen() {
            if (pausiert || fest) return;   // der andere Grund haelt noch
            wurzel.classList.remove('nf-pause');
            if (!zeitgeber && !gestoppt) verweilen(rest);
        }
        function anhalten() {
            if (pausiert || !bewegt) return;
            pausiert = true;
            einfrieren();
        }
        function fortsetzen() {
            if (!pausiert) return;
            pausiert = false;
            loslassen();
        }
        // Pause-Knopf: haelt an, bis er wieder gedrueckt wird.
        function umschalten() {
            if (gestoppt || !bewegt) return;
            fest = !fest;
            if (fest) einfrieren(); else loslassen();
            zuTitel();
        }
        // Vor/Zurueck: ein laufender Zeitgeber (Verweilen ODER Rollschritt)
        // wird abgebrochen; ein halb gerollter Schritt auf der Kopie wird erst
        // auf die echte erste Meldung gesetzt. Danach beginnt die Verweilzeit
        // neu – ist das Band angehalten, bleibt es auf der neuen Meldung stehen.
        function springen(richtung) {
            if (gestoppt || !bewegt) return;
            if (zeitgeber) clearTimeout(zeitgeber);
            zeitgeber = null;
            startZeit = 0;
            if (weich && idx >= n) { idx = 0; verschieben(0, false); void band.offsetWidth; }
            schritt(richtung);
        }
        function sprache() {
            kopfText.textContent = T('newsfeed.title', 'Neuigkeiten');
            wurzel.setAttribute('aria-label', kopfText.textContent);
            datumsFelder.forEach(function (d) {
                d.textContent = datumText(d.getAttribute('data-erstellt'), d.getAttribute('data-geaendert'));
            });
            zuTitel();
        }

        wurzel.addEventListener('mouseenter', anhalten);
        wurzel.addEventListener('mouseleave', fortsetzen);
        wurzel.addEventListener('focusin', anhalten);
        wurzel.addEventListener('focusout', fortsetzen);
        window.addEventListener('resize', messen);
        window.addEventListener('jarvis-lang-changed', sprache);
        try {
            if (document.fonts && document.fonts.ready) document.fonts.ready.then(function () {
                if (!gestoppt) messen();
            });
        } catch (e) { /* ohne Font-API genuegt die erste Messung */ }

        zaehlerSetzen();
        verschieben(0, false);
        if (bewegt) { balkenStarten(verweilMs); verweilen(verweilMs); }

        return {
            stoppen: function () {
                gestoppt = true;
                if (zeitgeber) clearTimeout(zeitgeber);
                zeitgeber = null;
                wurzel.removeEventListener('mouseenter', anhalten);
                wurzel.removeEventListener('mouseleave', fortsetzen);
                wurzel.removeEventListener('focusin', anhalten);
                wurzel.removeEventListener('focusout', fortsetzen);
                window.removeEventListener('resize', messen);
                window.removeEventListener('jarvis-lang-changed', sprache);
            },
            // Fuer Pruefstaende: der Index der gerade gezeigten Meldung.
            index: function () { return idx % n; },
            vor: function () { springen(1); },
            zurueck: function () { springen(-1); },
            pause: umschalten
        };
    }

    /* Portal: holt /api/newsfeed und zeichnet in #pt-newsfeed. Aufgerufen von
       portal_seite.js NUR bei permissions.newsfeed – bei ausgeschaltetem Skill
       gaebe es sonst bei jedem Seitenaufruf einen 404.

       Ein Fehlschlag laesst den bisherigen Zustand stehen: die Kachel ist
       Information, kein Zugang – ein Netzhaenger soll weder abmelden noch eine
       schon sichtbare Meldung wegnehmen.

       AUSBLENDEN: das × schickt den Stand, den DIESE Seite zeigt (nicht den
       aktuellen des Servers – Begruendung in backend/newsfeed.py). Die Kachel
       verschwindet erst nach der Bestaetigung; scheitert der Aufruf, bleibt sie
       stehen und sagt es am Knopf – ein Klick, der stumm nichts tut, saehe wie
       ein kaputter Knopf aus. */
    var _portal = null;
    function portalStart() {
        var wurzel = document.getElementById('pt-newsfeed');
        if (!wurzel || _portal) return;
        var laufend = null, signatur = '';
        // Ohne Abfang: fehlt sitzung.js, soll das laut scheitern statt wie
        // „nicht angemeldet" auszusehen (Begruendung in sitzung.js).
        function kopfzeilen(extra) {
            return Object.assign({ 'Authorization': 'Bearer ' + window.JarvisSitzung.token() }, extra || {});
        }
        function zeigen(d) {
            if (laufend) laufend.stoppen();
            laufend = null;
            if (d.ausgeblendet) { wurzel.textContent = ''; wurzel.hidden = true; return; }
            var opts = Object.assign({}, d, {
                schliessen: function (knopf) { ausblenden(d.stand, knopf); }
            });
            laufend = ticker(wurzel, d.eintraege || [], opts);
        }
        function ausblenden(stand, knopf) {
            knopf.disabled = true;
            return fetch('/api/newsfeed/ausblenden', {
                method: 'POST', headers: kopfzeilen({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ stand: stand })
            }).then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status);
                if (laufend) laufend.stoppen();
                laufend = null;
                wurzel.textContent = '';
                wurzel.hidden = true;
            }).catch(function () {
                knopf.disabled = false;
                knopf.classList.add('nf-zu-fehler');
                knopf.title = T('newsfeed.hide_failed', 'Ausblenden fehlgeschlagen – bitte erneut versuchen.');
                knopf.setAttribute('aria-label', knopf.title);
            });
        }
        function laden() {
            return fetch('/api/newsfeed', { headers: kopfzeilen() })
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    if (!d || !d.ok) return;
                    var neu = JSON.stringify([d.eintraege, d.verweil_s, d.scroll_s, d.stand, !!d.ausgeblendet]);
                    if (neu === signatur) return;   // unveraendert: Band nicht zuruecksetzen
                    signatur = neu;
                    zeigen(d);
                })
                .catch(function () {});
        }
        _portal = { laden: laden, intervall: setInterval(laden, NACHLADEN_MS) };
        return laden();
    }

    window.JarvisNewsfeed = { ticker: ticker, portalStart: portalStart, datum: datum };
})();
