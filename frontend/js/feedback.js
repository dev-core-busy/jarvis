/**
 * Feedback-Bereich (/feedback): Formular ausfuellen und absenden.
 *
 * Die Seite ist eine LEERE HUELLE – eine Navigation traegt keinen
 * Authorization-Header, die Berechtigung kann also nicht in der Route geprueft
 * werden. Hier wird /api/me geholt und wer nicht darf, landet auf dem Portal;
 * die DATEN liegen ausschliesslich hinter require_feedback_access.
 *
 * ⚠ DIE SPALTEN KOMMEN VOM SERVER, die Zeilen legt der Benutzer an. Ein
 * Zellwert wird NIE ins Markup interpoliert (`.value =`), sondern gesetzt:
 * ein Anfuehrungszeichen im Text sprengt sonst das Attribut (Register).
 */
(function () {
    'use strict';

    var _formulare = [];
    var _aktiv = null;      // das gewaehlte Formular
    var _zeilen = [];       // [{spalten_id: wert}] – der Arbeitsstand
    var _sendet = false;

    // ⚠ DRIFT-SCHRANKE: beide Werte stehen ebenso in `backend/feedback.py`
    // (`TYP_FEST`, `ZEILEN_ID`). Laufen sie auseinander, rendert die Seite die
    // feste Spalte als Eingabefeld bzw. der Server ordnet keine Zeile mehr zu –
    // beides ohne Fehlermeldung. Ein Waechter vergleicht sie.
    var TYP_FEST = 'fest';
    var ZEILEN_ID = '_zid';

    /** Die vom Administrator vorgegebenen Zeilen des gewaehlten Formulars.
     *  Leer = der Benutzer legt seine Zeilen selbst an (Bestandsverhalten). */
    function festeZeilen() {
        var z = _aktiv && _aktiv.zeilen;
        return Array.isArray(z) ? z : [];
    }

    function tok() {
        try { return localStorage.getItem('jarvis_token') || ''; } catch (e) { return ''; }
    }

    function $(id) { return document.getElementById(id); }

    function hole(pfad, opt) {
        var o = opt || {};
        o.headers = o.headers || {};
        o.headers['Authorization'] = 'Bearer ' + tok();
        return fetch(pfad, o);
    }

    /** Fehlertext aus einer Serverantwort. Jarvis benutzt `error`, FastAPI
     *  `detail` – nur eines zu lesen laesst eine vorhandene Begruendung
     *  verschwinden (Register). */
    function fehlertext(d, rueckfall) {
        if (!d) { return rueckfall; }
        return d.error || d.detail || d.message || rueckfall;
    }

    function t(key, fallback) {
        return (window.t ? window.t(key, fallback) : fallback) || fallback;
    }

    function melde(text, art) {
        var el = $('fb-status');
        if (!el) { return; }
        el.textContent = text || '';
        // Farbe UND Text: die Farbe allein ist keine Information (Projektregel).
        el.className = 'fb-status' + (art === 'ok' ? ' is-ok' : art === 'err' ? ' is-err' : '');
    }

    // ── Aufklappbare Container (Bauform aus /ai-mouse und /email) ───────────
    // Gespeichert werden die ZUGEKLAPPTEN: so ist die Vorgabe fuer einen neuen
    // Benutzer „alles offen", und ein spaeter ergaenzter Container ist
    // automatisch offen statt still versteckt.
    var KLAPP_SPEICHER = 'jarvis_feedback_zu';

    function klappZustand() {
        try {
            var roh = JSON.parse(localStorage.getItem(KLAPP_SPEICHER) || '[]');
            return Array.isArray(roh) ? roh.filter(function (x) { return typeof x === 'string'; }) : [];
        } catch (e) {
            // Ein kaputter Speicherstand darf nicht dazu fuehren, dass gar
            // nichts mehr aufklappt.
            return [];
        }
    }

    /** Einen Container auf- oder zuklappen und den Zustand merken.
     *
     *  ⚠ DIE EINE STELLE DAFUER. `maxUmschalten` braucht sie ebenfalls (eine
     *  zugeklappte Karte zu maximieren ergaebe eine leere Flaeche); eine
     *  zweite Fassung liefe beim naechsten Feinschliff auseinander und der
     *  gemerkte Zustand haette je nach Weg eine andere Bedeutung. */
    function klappSetzen(karte, zu) {
        var kopf = karte.querySelector('.ja-card-head');
        var id = karte.getAttribute('data-klapp');
        karte.classList.toggle('is-zu', !!zu);
        if (kopf) { kopf.setAttribute('aria-expanded', zu ? 'false' : 'true'); }
        // ⚠ BEIM SICHTBARWERDEN NACHMESSEN: in einem zugeklappten Container
        // ist `scrollHeight` 0, die Antwortfelder behalten dort ihre
        // Starthoehe. Ohne dieses Nachziehen stuende ein langer Text nach dem
        // Aufklappen in einem zu kleinen Feld.
        if (!zu) { hoehenNachziehen(); }
        var liste = klappZustand().filter(function (x) { return x !== id; });
        if (zu) { liste.push(id); }
        try { localStorage.setItem(KLAPP_SPEICHER, JSON.stringify(liste)); }
        catch (e) { /* privater Modus: der Zustand gilt nur fuer diese Seite */ }
    }

    function klappInit() {
        var zu = klappZustand();
        document.querySelectorAll('.ja-card[data-klapp]').forEach(function (karte) {
            var kopf = karte.querySelector('.ja-card-head');
            if (!kopf) { return; }
            var id = karte.getAttribute('data-klapp');
            var istZu = zu.indexOf(id) >= 0;
            karte.classList.toggle('is-zu', istZu);
            kopf.setAttribute('aria-expanded', istZu ? 'false' : 'true');
            function um() {
                klappSetzen(karte, !karte.classList.contains('is-zu'));
            }
            kopf.addEventListener('click', function (ev) {
                // ⚠ OHNE DIESE AUSNAHME klappt jeder Knopf in der Kopfzeile den
                // Container zu (Projektregel).
                if (ev.target.closest('button, input, label, a, select, textarea')) { return; }
                um();
            });
            kopf.addEventListener('keydown', function (ev) {
                if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
                    ev.preventDefault();
                    um();
                }
            });
        });
    }

    // ── Maximieren ────────────────────────────────────────
    //
    // Die Karte fuellt den Bereich unter der Titelleiste. Bauform 1:1 aus
    // `/tracks` (`maxSetzen`/`maxUmschalten`/`maxInit`) – dasselbe
    // Bedienelement soll sich ueberall gleich verhalten, und ein zweiter
    // Entwurf fuer dieselbe Sache ist im Projekt regelmaessig auseinander
    // gelaufen.
    //
    // ⚠ DER ZUSTAND WIRD BEWUSST NICHT GEMERKT (anders als Auf/Zu): ein
    // Vollbild, das beim naechsten Oeffnen der Seite noch an ist, sieht wie ein
    // Fehler aus – man sucht die uebrigen Karten. Es ist ein Arbeitsmodus fuer
    // den Moment.
    //
    // Dass ein Klick auf den Knopf nicht zugleich die Karte zuklappt, erledigt
    // die vorhandene Ausnahme in `klappInit` (`closest('button, …')`).

    /** Die Hoehe der Titelleiste MESSEN statt zu raten: sie waechst mit einer
     *  laengeren Markenbezeichnung und bricht auf schmalen Fenstern um. */
    function topAbstandSetzen() {
        var bar = document.querySelector('.topbar');
        var h = bar ? Math.round(bar.getBoundingClientRect().height) : 0;
        if (h > 0) { document.documentElement.style.setProperty('--fb-top', h + 'px'); }
    }

    function maxSetzen(karte, an) {
        karte.classList.toggle('is-max', !!an);
        document.body.classList.toggle('fb-maxed', !!an);
        var b = karte.querySelector('[data-act="max"]');
        if (b) {
            // DIESELBEN ZEICHEN wie der Vollbild-Knopf des Einstellungs-Dialogs
            // (#btn-maximize-settings), `modal_expand.js` und /tracks:
            // ⛶ zum Maximieren, 🗗 zum Verkleinern. Sie sind die
            // ausdrueckliche Ausnahme von der Emoji-Regel des Projekts – wer
            // zwischen den Fenstern wechselt, soll dasselbe Zeichen fuer
            // dieselbe Sache sehen (Vorgabe des Nutzers 2026-08-18).
            b.innerHTML = an ? '&#128471;' : '&#9974;';
            b.classList.toggle('active', !!an);
            b.setAttribute('aria-pressed', an ? 'true' : 'false');
            var k = an ? 'feedback.minimize' : 'feedback.maximize';
            var txt = t(k, an ? 'Verkleinern' : 'Maximieren');
            // Titel UND aria-label: das Zeichen allein wird als
            // „square four corners“ vorgelesen. Die `data-i18n-*`-Attribute
            // muessen mitwandern, sonst holt der naechste Sprachwechsel den
            // Text des ANDEREN Zustands zurueck.
            b.setAttribute('data-i18n-title', k);
            b.setAttribute('data-i18n-aria', k);
            b.title = txt;
            b.setAttribute('aria-label', txt);
        }
        if (an) { topAbstandSetzen(); }
        // ⚠ DIE FELDHOEHEN MUESSEN NACHGEZOGEN WERDEN – das ist der Unterschied
        // zu /tracks: `hoeheAnpassen` schreibt eine feste px-Hoehe, und das
        // Umschalten aendert die BREITE der Tabelle (820 px gegen Fensterbreite).
        // Derselbe Text braucht dann andere Zeilen; ohne Nachmessen steht ein
        // zu hohes oder ein abgeschnittenes Feld da.
        hoehenNachziehen();
    }

    function maxUmschalten(karte) {
        var an = !karte.classList.contains('is-max');
        // Erst alle anderen verkleinern – zwei maximierte Karten uebereinander
        // waeren ein Zustand, den niemand aufloesen kann.
        document.querySelectorAll('.ja-card.is-max').forEach(function (k) {
            if (k !== karte) { maxSetzen(k, false); }
        });
        // Eine zugeklappte Karte zu maximieren ergaebe eine leere Flaeche.
        if (an && karte.classList.contains('is-zu')) { klappSetzen(karte, false); }
        maxSetzen(karte, an);
    }

    function maxInit() {
        document.querySelectorAll('.ja-card[data-klapp]').forEach(function (karte) {
            var b = karte.querySelector('[data-act="max"]');
            if (!b) { return; }
            b.addEventListener('click', function (ev) {
                // `preventDefault` UND `stopPropagation`: der Knopf sitzt in
                // der Klapp-Kopfzeile (Register: AD-Picker).
                ev.preventDefault();
                ev.stopPropagation();
                maxUmschalten(karte);
            });
        });
        // Escape verkleinert – der uebliche Weg heraus aus einem Vollbild.
        document.addEventListener('keydown', function (ev) {
            if (ev.key !== 'Escape') { return; }
            // Hat ein anderer Handler die Taste schon verbraucht (ein offener
            // Dialog), bleibt das Vollbild stehen: sonst raeumt ein Escape
            // zwei Dinge auf einmal weg.
            if (ev.defaultPrevented) { return; }
            var offen = document.querySelector('.ja-card.is-max');
            if (offen) { ev.preventDefault(); maxSetzen(offen, false); }
        });
        // Wird das Fenster schmaler, aendert sich die Hoehe der Titelleiste
        // (Umbruch) – der Abstand muss mitgehen, sonst verdeckt sie den Kopf.
        window.addEventListener('resize', function () {
            if (document.querySelector('.ja-card.is-max')) { topAbstandSetzen(); }
        });
    }

    // ── Sterne ─────────────────────────────────────────────────────────────
    //
    // ⚠ EINE RADIOGRUPPE, KEINE FUENF KNOEPFE OHNE ZUSAMMENHANG. Fuer eine
    // Hilfstechnik ist „3 von 5" die Aussage – fuenf einzelne Knoepfe waeren
    // fuenf unverbundene Bedienelemente. Der Wert steht zusaetzlich als ZAHL
    // daneben: ohne sie muesste man zaehlen.
    function sterneBauen(wert, beschriftung, beiAenderung) {
        var box = document.createElement('div');
        box.className = 'fb-sterne';
        box.setAttribute('role', 'radiogroup');
        box.setAttribute('aria-label', beschriftung);

        var anzeige = document.createElement('span');
        anzeige.className = 'fb-sterne-wert';

        function zeichnen(n) {
            for (var i = 1; i <= 5; i++) {
                var b = box.children[i - 1];
                if (!b) { continue; }
                var an = i <= n;
                b.classList.toggle('is-an', an);
                b.setAttribute('aria-checked', an ? 'true' : 'false');
                // ⚠ Der Knopf bleibt fokussierbar, auch wenn er nicht gewaehlt
                // ist: eine Radiogruppe wird mit den Pfeiltasten bedient.
                b.innerHTML = window.JarvisIcons.star(an);
            }
            anzeige.textContent = n ? (n + '/5') : '–';
            box.setAttribute('data-wert', String(n));
        }

        for (var i = 1; i <= 5; i++) {
            (function (stufe) {
                var b = document.createElement('button');
                b.type = 'button';
                b.className = 'fb-stern';
                b.setAttribute('role', 'radio');
                b.setAttribute('data-stufe', String(stufe));
                b.title = t('feedback.star_set', '{n} von 5').replace('{n}', stufe);
                b.setAttribute('aria-label', b.title);
                b.addEventListener('click', function () {
                    // Ein Klick auf den bereits gesetzten Stern nimmt die
                    // Bewertung ZURUECK. Ohne diesen Weg gaebe es keinen: ein
                    // versehentlicher Klick waere nicht mehr korrigierbar, und
                    // ein eigener „keine"-Knopf waere ein Bedienelement mehr.
                    var alt = parseInt(box.getAttribute('data-wert') || '0', 10);
                    var neu = (alt === stufe) ? 0 : stufe;
                    zeichnen(neu);
                    if (beiAenderung) { beiAenderung(neu); }
                });
                b.addEventListener('keydown', function (ev) {
                    var alt = parseInt(box.getAttribute('data-wert') || '0', 10);
                    var neu = null;
                    if (ev.key === 'ArrowRight' || ev.key === 'ArrowUp') { neu = Math.min(5, alt + 1); }
                    else if (ev.key === 'ArrowLeft' || ev.key === 'ArrowDown') { neu = Math.max(0, alt - 1); }
                    if (neu === null) { return; }
                    ev.preventDefault();
                    zeichnen(neu);
                    if (beiAenderung) { beiAenderung(neu); }
                    // Der Fokus wandert MIT – sonst geht der naechste
                    // Tastendruck ins Leere, weil der Knopf unter dem Fokus
                    // nicht mehr der gewaehlte ist (Register: Ziehgriff).
                    var ziel = box.children[Math.max(1, neu) - 1];
                    if (ziel) { ziel.focus(); }
                });
                box.appendChild(b);
            })(i);
        }
        zeichnen(wert || 0);

        var huelle = document.createElement('span');
        huelle.style.display = 'inline-flex';
        huelle.style.alignItems = 'center';
        huelle.appendChild(box);
        huelle.appendChild(anzeige);
        return huelle;
    }

    // ── Antwortfelder ──────────────────────────────────────────────────────
    //
    // ⚠ EIN `textarea`, KEIN `input` (Vorgabe des Betreibers 2026-09-16).
    // Eine Antwort ist oft ein Absatz; in einem einzeiligen Feld liess sich
    // ueberhaupt kein Umbruch eingeben – der Deckel von 2000 Zeichen stand
    // schon immer da, benutzbar waren sie nicht.
    //
    // ⚠ ENTER FUEGT EINEN UMBRUCH EIN UND SENDET NICHT AB. Das ist hier
    // gefahrlos, weil der Absende-Weg ausschliesslich am Knopf haengt: es gibt
    // kein `<form>` und keinen Enter-Handler auf der Seite. Wer hier je einen
    // ergaenzt, macht aus jedem Absatzwechsel eine Abgabe.

    /** Startzeilen. Zwei statt einer: eine einzeilige `textarea` sieht aus wie
     *  ein `input` – dass man hier einen Absatz schreiben darf, soll man SEHEN,
     *  ohne es auszuprobieren. */
    var FELD_ZEILEN = 2;

    /** Die Hoehe an den Inhalt anpassen.
     *
     *  ⚠ BEI HOEHE 0 WIRD NICHTS GESETZT. In einem zugeklappten Container
     *  (`.ja-card.is-zu`) ist `scrollHeight` 0 – wer das naiv uebernimmt, setzt
     *  die Hoehe auf 0 und das Feld ist nach dem Aufklappen unsichtbar
     *  (Register: dieselbe Falle bei der Verstossliste, 2026-07-30). Deshalb
     *  zieht `klappInit` beim Sichtbarwerden nach.
     *
     *  `height = 'auto'` VOR dem Messen ist Pflicht: `scrollHeight` waechst
     *  sonst nur, es schrumpft nie wieder – geloeschter Text liesse das Feld
     *  hoch stehen.
     *
     *  ⚠ DER RAHMEN MUSS DAZU. Das Feld ist `box-sizing: border-box`, `height`
     *  meint dort die Hoehe MIT Rahmen – `scrollHeight` enthaelt aber nur
     *  Inhalt und Polster. Ohne die zwei Pixel ist das Feld dauerhaft zu klein
     *  und zeigt eine Bildlaufleiste, obwohl gerade nachgemessen wurde.
     */
    function hoeheAnpassen(ta) {
        if (!ta) { return; }
        var alt = ta.style.height;
        ta.style.height = 'auto';
        var inhalt = ta.scrollHeight;
        // offsetHeight - clientHeight = Rahmen (und eine etwaige waagerechte
        // Bildlaufleiste). Negativ kann das nicht werden.
        var rahmen = Math.max(0, ta.offsetHeight - ta.clientHeight);
        if (inhalt > 0) {
            ta.style.height = (inhalt + rahmen) + 'px';
        } else {
            // Unsichtbar (zugeklappt, `display:none`): den vorherigen Stand
            // zuruecklegen, statt eine gemessene Null festzuschreiben.
            ta.style.height = alt;
        }
    }

    /** Alle Antwortfelder nachmessen – nach dem Einhaengen und beim Aufklappen.
     *  Vor dem Einhaengen ins Dokument ist `scrollHeight` 0, ein Aufruf mitten
     *  im Bauen der Tabelle waere also wirkungslos. */
    function hoehenNachziehen() {
        document.querySelectorAll('#fb-tabelle textarea').forEach(hoeheAnpassen);
    }

    function textfeldBauen(spalte, zeile) {
        var ta = document.createElement('textarea');
        ta.rows = FELD_ZEILEN;
        ta.maxLength = 2000;
        ta.className = 'fb-feld-text';
        ta.setAttribute('aria-label', spalte.name);
        // ⚠ .value setzen, NICHT ins Markup interpolieren.
        ta.value = zeile[spalte.id] == null ? '' : String(zeile[spalte.id]);
        ta.addEventListener('input', function () {
            zeile[spalte.id] = ta.value;
            hoeheAnpassen(ta);
        });
        return ta;
    }

    // ── Tabelle ────────────────────────────────────────────────────────────

    function leereZeile() {
        var z = {};
        ((_aktiv && _aktiv.spalten) || []).forEach(function (s) {
            z[s.id] = (s.typ === 'sterne') ? 0 : '';
        });
        return z;
    }

    /** Den Arbeitsstand fuer das gewaehlte Formular aufbauen.
     *
     *  Bei FESTEN Zeilen entsteht je Vorgabe genau eine Zeile, in der
     *  Reihenfolge der Definition. Der feste Text wird mitgenommen – aber nur
     *  ZUR ANZEIGE: `senden()` schickt ihn nicht mit, er kommt serverseitig
     *  wieder aus der Definition (siehe dort).
     */
    function zeilenAufbauen() {
        var fest = festeZeilen();
        if (!fest.length) { return [leereZeile()]; }
        var spalten = (_aktiv && _aktiv.spalten) || [];
        return fest.map(function (fz) {
            var z = leereZeile();
            z[ZEILEN_ID] = fz.id;
            spalten.forEach(function (s) {
                if (s.typ === TYP_FEST) {
                    z[s.id] = (fz.werte || {})[s.id] || '';
                }
            });
            return z;
        });
    }

    function tabelleZeichnen() {
        var box = $('fb-tabelle');
        if (!box) { return; }
        box.innerHTML = '';
        if (!_aktiv) {
            var p = document.createElement('p');
            p.className = 'fb-leer';
            p.textContent = t('feedback.none',
                'Zurzeit ist kein Formular freigeschaltet. Ein Administrator legt sie unter Einstellungen → Feedback an.');
            box.appendChild(p);
            return;
        }
        var spalten = _aktiv.spalten || [];
        // Bei festen Zeilen gibt es nichts zu entfernen und nichts anzulegen –
        // die Struktur gehoert dem Administrator (Vorgabe des Betreibers).
        var fest = festeZeilen().length > 0;

        var wrap = document.createElement('div');
        wrap.className = 'fb-tab-wrap';
        var tab = document.createElement('table');
        tab.className = 'fb-tab' + (fest ? ' is-fest' : '');

        var thead = document.createElement('thead');
        var kopf = document.createElement('tr');
        var thNr = document.createElement('th');
        thNr.className = 'fb-c-nr';
        thNr.textContent = '#';
        kopf.appendChild(thNr);
        spalten.forEach(function (s) {
            var th = document.createElement('th');
            th.textContent = s.name;          // textContent: Fremdtext
            kopf.appendChild(th);
        });
        if (!fest) {
            var thAkt = document.createElement('th');
            thAkt.className = 'fb-c-akt';
            // Leere Ueberschrift ueber der Knopfspalte: ein Wort waere Rauschen,
            // die Bedeutung traegt der Knopf selbst ueber title/aria-label.
            thAkt.setAttribute('aria-label', t('feedback.row_del', 'Zeile entfernen'));
            kopf.appendChild(thAkt);
        }
        thead.appendChild(kopf);
        tab.appendChild(thead);

        var tbody = document.createElement('tbody');
        _zeilen.forEach(function (zeile, idx) {
            var tr = document.createElement('tr');
            var tdNr = document.createElement('td');
            tdNr.className = 'fb-c-nr';
            tdNr.textContent = String(idx + 1);
            tr.appendChild(tdNr);

            spalten.forEach(function (s) {
                var td = document.createElement('td');
                if (s.typ === TYP_FEST) {
                    // Nur zu lesen. textContent, weil der Text vom Server kommt;
                    // und KEIN `disabled`-Eingabefeld: das sieht aus wie ein
                    // Feld, das man fuellen koennte und das gerade klemmt.
                    td.className = 'fb-c-fest';
                    td.textContent = zeile[s.id] == null ? '' : String(zeile[s.id]);
                } else if (s.typ === 'sterne') {
                    td.appendChild(sterneBauen(
                        parseInt(zeile[s.id] || 0, 10),
                        s.name + ' – ' + t('feedback.stars', 'Bewertung'),
                        function (n) { zeile[s.id] = n; }));
                } else {
                    td.appendChild(textfeldBauen(s, zeile));
                }
                tr.appendChild(td);
            });

            if (fest) {
                tbody.appendChild(tr);
                return;
            }
            var tdAkt = document.createElement('td');
            tdAkt.className = 'fb-c-akt';
            var del = document.createElement('button');
            del.type = 'button';
            del.className = 'fb-row-del';
            del.title = t('feedback.row_del', 'Zeile entfernen');
            del.setAttribute('aria-label', del.title);
            // Muelleimer: hier wird wirklich etwas entfernt (Symbol-Semantik).
            del.innerHTML = window.JarvisIcons.trash();
            del.addEventListener('click', function () {
                _zeilen.splice(idx, 1);
                // Die letzte Zeile wird nicht entfernt, sondern GELEERT: eine
                // Tabelle ohne jede Zeile ist ein Zustand, aus dem der Benutzer
                // nur ueber „+ Zeile" herauskommt – der Knopf steht daneben,
                // aber eine leere Tabelle sieht nach einem Fehler aus.
                if (!_zeilen.length) { _zeilen.push(leereZeile()); }
                tabelleZeichnen();
            });
            tdAkt.appendChild(del);
            tr.appendChild(tdAkt);
            tbody.appendChild(tr);
        });
        tab.appendChild(tbody);
        wrap.appendChild(tab);
        box.appendChild(wrap);
        // ⚠ ERST JETZT: vor dem Einhaengen ins Dokument ist `scrollHeight` 0,
        // ein Nachmessen waehrend des Bauens waere wirkungslos.
        hoehenNachziehen();
    }

    function formularWaehlen(fid) {
        _aktiv = _formulare.find(function (f) { return f.id === fid; }) || _formulare[0] || null;
        _zeilen = _aktiv ? zeilenAufbauen() : [];
        var desc = $('fb-form-desc');
        if (desc) {
            desc.textContent = (_aktiv && _aktiv.beschreibung) || '';
            desc.style.display = desc.textContent ? '' : 'none';
        }
        // Die Knoepfe haengen am Formular: ohne eines gibt es nichts zu tun.
        ['fb-zeile-neu', 'fb-senden'].forEach(function (id) {
            var b = $(id);
            if (b) { b.disabled = !_aktiv; }
        });
        // ⚠ „+ Zeile" wird bei festen Zeilen VERSTECKT, nicht nur gesperrt. Die
        // Projektregel „gesperrt mit Begruendung schlaegt verborgen" gilt fuer
        // Bedienelemente mit ZUSTAND – hier gibt es keinen Zustand, in dem der
        // Knopf je etwas tut: die Struktur gehoert dem Administrator. Ein grauer
        // Knopf wuerde eine Moeglichkeit andeuten, die es nicht gibt.
        var neu = $('fb-zeile-neu');
        if (neu) { neu.classList.toggle('hidden', !!(_aktiv && festeZeilen().length)); }
        melde('');
        tabelleZeichnen();
        meineLaden();
    }

    function formulareZeichnen() {
        var pick = $('fb-pick');
        var sel = $('fb-form-sel');
        if (!sel || !pick) { return; }
        sel.innerHTML = '';
        _formulare.forEach(function (f) {
            var o = document.createElement('option');
            o.value = f.id;
            o.textContent = f.titel;        // textContent: Fremdtext
            sel.appendChild(o);
        });
        // ⚠ Die Auswahl erscheint nur bei MEHREREN Formularen: ein Pulldown mit
        // genau einem Eintrag ist ein Bedienelement ohne Wahl.
        pick.classList.toggle('hidden', _formulare.length < 2);
    }

    // ── Absenden ───────────────────────────────────────────────────────────

    function senden() {
        if (!_aktiv || _sendet) { return; }
        var fest = festeZeilen().length > 0;

        /** Hat der BENUTZER in dieser Zeile etwas eingetragen? Eine
         *  `fest`-Spalte zaehlt ausdruecklich NICHT mit – sonst waere jede
         *  feste Zeile „gefuellt", nur weil ihr Kriterium dasteht, und ein
         *  leeres Formular liesse sich absenden. */
        function gefuellt(z) {
            return (_aktiv.spalten || []).some(function (s) {
                if (s.typ === TYP_FEST) { return false; }
                var w = z[s.id];
                return (s.typ === 'sterne') ? (parseInt(w || 0, 10) > 0)
                                            : String(w || '').trim() !== '';
            });
        }

        // Vor dem Senden aufraeumen: leere Zeilen weist der Server ohnehin ab,
        // aber die Meldung „keine Zeile ausgefuellt" ist am Formular ehrlicher
        // als eine Fehlermeldung vom Server.
        if (!_zeilen.some(gefuellt)) {
            melde(t('feedback.err_empty', 'Es ist keine einzige Zeile ausgefüllt.'), 'err');
            return;
        }
        // ⚠ BEI FESTEN ZEILEN GEHEN ALLE RAUS, auch die leeren – der Server
        // braucht sie nicht (er iteriert ueber die Definition), aber die
        // Zuordnung ueber ZEILEN_ID ist damit vollstaendig und der Rumpf sagt,
        // was der Benutzer gesehen hat. Ohne feste Zeilen bleibt es beim
        // Bestand: nur gefuellte Zeilen.
        // Die `fest`-Zellen werden AUSDRUECKLICH NICHT mitgeschickt: ihr Text
        // kommt serverseitig aus der Definition, und was nicht gesendet wird,
        // kann auch nicht gefaelscht aussehen.
        var voll = (fest ? _zeilen : _zeilen.filter(gefuellt)).map(function (z) {
            var raus = {};
            if (z[ZEILEN_ID]) { raus[ZEILEN_ID] = z[ZEILEN_ID]; }
            (_aktiv.spalten || []).forEach(function (s) {
                if (s.typ !== TYP_FEST) { raus[s.id] = z[s.id]; }
            });
            return raus;
        });
        _sendet = true;
        var knopf = $('fb-senden');
        if (knopf) { knopf.disabled = true; }
        melde(t('feedback.sending', 'Wird gesendet…'));
        hole('/api/feedback/abgabe', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ formular_id: _aktiv.id, zeilen: voll })
        }).then(function (r) {
            return r.json().catch(function () { return null; }).then(function (d) {
                if (!r.ok || !d || d.ok === false) {
                    throw new Error(fehlertext(d, 'HTTP ' + r.status));
                }
                return d;
            });
        }).then(function (d) {
            melde(t('feedback.sent', '✓ Gesendet – vielen Dank.') + ' '
                + t('feedback.sent_n', '{n} Zeile(n).').replace('{n}', (d.abgabe.zeilen || []).length),
                'ok');
            // Frisches, leeres Formular: die Abgabe ist raus, der alte Stand
            // stuende sonst da, als waere nichts passiert. Bei festen Zeilen
            // entsteht dabei wieder der vollstaendige Bogen.
            _zeilen = zeilenAufbauen();
            tabelleZeichnen();
            meineLaden();
        }).catch(function (e) {
            melde(e.message, 'err');
        }).then(function () {
            _sendet = false;
            if (knopf) { knopf.disabled = false; }
        });
    }

    // ── Eigene Abgaben ─────────────────────────────────────────────────────

    function meineLaden() {
        var box = $('fb-meine');
        if (!box) { return; }
        hole('/api/feedback/meine' + (_aktiv ? '?fid=' + encodeURIComponent(_aktiv.id) : ''))
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d || !d.ok) { throw new Error('laden'); }
                meineZeichnen(d.abgaben || []);
            })
            .catch(function () {
                // ⚠ Ein Ladefehler LEERT die Liste nicht: eine leere Liste waere
                // von „du hast noch nichts abgegeben" nicht zu unterscheiden.
                box.innerHTML = '<p class="fb-leer">'
                    + t('feedback.mine_err', 'Die bisherigen Abgaben konnten nicht geladen werden.')
                    + '</p>';
            });
    }

    function meineZeichnen(liste) {
        var box = $('fb-meine');
        if (!box) { return; }
        box.innerHTML = '';
        if (!liste.length) {
            var p = document.createElement('p');
            p.className = 'fb-leer';
            p.textContent = t('feedback.mine_none', 'Du hast noch nichts abgegeben.');
            box.appendChild(p);
            return;
        }
        liste.forEach(function (a) {
            box.appendChild(abgabeZeichnen(a));
        });
    }

    /** Eine abgegebene Tabelle nur zum Lesen.
     *
     *  ⚠ DIE SPALTEN KOMMEN AUS DER ABGABE, nicht aus dem heutigen Formular.
     *  Sonst stuenden nach einer Aenderung echte Daten unter einer Ueberschrift,
     *  die zum Zeitpunkt der Abgabe gar nicht galt (deshalb speichert der
     *  Server den Spalten-Snapshot mit).
     */
    function abgabeZeichnen(a) {
        var karte = document.createElement('div');
        karte.className = 'fb-abgabe';

        var kopf = document.createElement('div');
        kopf.className = 'fb-abgabe-kopf';
        var titel = document.createElement('span');
        titel.className = 'fb-abgabe-titel';
        titel.textContent = a.formular_titel || '';
        var zeit = document.createElement('span');
        zeit.className = 'fb-abgabe-zeit';
        zeit.textContent = (a.zeit || '').replace('T', ' ');
        kopf.appendChild(titel);
        kopf.appendChild(zeit);
        karte.appendChild(kopf);

        var body = document.createElement('div');
        body.className = 'fb-abgabe-body';
        var tab = document.createElement('table');
        tab.className = 'fb-tab';
        var spalten = a.spalten || [];

        var thead = document.createElement('thead');
        var kz = document.createElement('tr');
        spalten.forEach(function (s) {
            var th = document.createElement('th');
            th.textContent = s.name;
            kz.appendChild(th);
        });
        thead.appendChild(kz);
        tab.appendChild(thead);

        var tbody = document.createElement('tbody');
        (a.zeilen || []).forEach(function (z) {
            var tr = document.createElement('tr');
            spalten.forEach(function (s) {
                var td = document.createElement('td');
                if (s.typ === 'sterne') {
                    var n = parseInt(z[s.id] || 0, 10);
                    // Nur lesen: gefuellte Sterne plus Zahl, keine Knoepfe.
                    var sp = document.createElement('span');
                    sp.className = 'fb-sterne';
                    sp.setAttribute('aria-label', n + '/5');
                    for (var i = 1; i <= 5; i++) {
                        var s1 = document.createElement('span');
                        s1.className = 'fb-stern' + (i <= n ? ' is-an' : '');
                        s1.innerHTML = window.JarvisIcons.star(i <= n);
                        sp.appendChild(s1);
                    }
                    td.appendChild(sp);
                } else {
                    // Der feste Text steht in der Abgabe selbst (Snapshot) und
                    // bekommt dieselbe Auszeichnung wie im Formular – sonst
                    // saehe die Rueckschau anders aus als das Ausgefuellte.
                    // ⚠ `fb-c-text` traegt `white-space: pre-wrap`: eine
                    // Antwort darf mehrzeilig sein, und HTML macht aus einem
                    // Umbruch sonst ein LEERZEICHEN – der Benutzer saehe seine
                    // Absaetze nicht wieder (Register: /chat, 2026-08-31).
                    td.className = (s.typ === TYP_FEST) ? 'fb-c-fest' : 'fb-c-text';
                    td.textContent = z[s.id] == null ? '' : String(z[s.id]);
                }
                tr.appendChild(td);
            });
            tbody.appendChild(tr);
        });
        tab.appendChild(tbody);
        body.appendChild(tab);
        karte.appendChild(body);
        return karte;
    }

    // ── Start ──────────────────────────────────────────────────────────────

    function binden() {
        var sel = $('fb-form-sel');
        if (sel) { sel.addEventListener('change', function () { formularWaehlen(sel.value); }); }
        var neu = $('fb-zeile-neu');
        if (neu) {
            neu.addEventListener('click', function () {
                // Der Knopf ist bei festen Zeilen versteckt – die Pruefung ist
                // die zweite Schranke: `hidden` laesst sich aus den
                // Entwicklerwerkzeugen entfernen, und eine so entstandene Zeile
                // haette keine Kennung und fiele serverseitig lautlos heraus.
                if (!_aktiv || festeZeilen().length) { return; }
                _zeilen.push(leereZeile());
                tabelleZeichnen();
                // Der Fokus springt in die neue Zeile – sonst muss der Benutzer
                // nach jedem Klick erst wieder hinklicken.
                // ⚠ `textarea`, nicht `input[type="text"]`: der alte Selektor
                // fand nach der Umstellung auf mehrzeilige Felder nichts mehr,
                // und der Knopf tat still weniger als vorher.
                var felder = document.querySelectorAll('#fb-tabelle tbody tr:last-child textarea');
                if (felder.length) { felder[0].focus(); }
            });
        }
        var senden_ = $('fb-senden');
        if (senden_) { senden_.addEventListener('click', senden); }

        var portal = $('fb-portal-btn');
        if (portal) { portal.addEventListener('click', function () { location.href = '/portal'; }); }

        var logout = $('fb-logout-btn');
        if (logout) {
            logout.addEventListener('click', function () {
                // Das Abmelde-Signal MUSS raus, bevor das Token verworfen wird,
                // und braucht keepalive: die Seite navigiert unmittelbar danach
                // weg (Anwesenheits-Buchhaltung, Register).
                try {
                    fetch('/api/logout', {
                        method: 'POST', keepalive: true,
                        headers: { 'Authorization': 'Bearer ' + tok() }
                    });
                } catch (e) { /* Abmelden darf am Signal nicht scheitern. */ }
                try { localStorage.removeItem('jarvis_token'); } catch (e) { }
                location.replace('/');
            });
        }
    }

    function start() {
        var app = $('fb-app');
        if (!tok()) { location.replace('/'); return; }

        // ⚠ VOR dem /api/me-Abruf: die Container stehen im Markup und sollen
        // ihren gemerkten Zustand sofort haben – sonst klappen sie sichtbar zu,
        // nachdem die Seite schon dastand.
        klappInit();
        // Nach `klappInit`: `maxUmschalten` klappt eine zugeklappte Karte erst
        // auf, und dafuer muss der Klapp-Zustand bereits stehen.
        maxInit();
        binden();

        hole('/api/me').then(function (r) {
            if (!r.ok) { throw new Error('auth'); }
            return r.json();
        }).then(function (me) {
            // Freigabe UND aktiver Skill – der Server hat beides verrechnet.
            if (!me.permissions || !me.permissions.feedback) {
                location.replace('/portal');
                return null;
            }
            if (app) { app.classList.remove('hidden'); }
            var sb = $('fb-settings-btn');
            if (sb && me.is_admin) { sb.style.display = ''; }
            return hole('/api/feedback/formulare')
                .then(function (r) { return r.ok ? r.json() : null; })
                .then(function (d) {
                    _formulare = (d && d.formulare) || [];
                    formulareZeichnen();
                    formularWaehlen(_formulare.length ? _formulare[0].id : '');
                });
        }).catch(function () {
            location.replace('/');
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
