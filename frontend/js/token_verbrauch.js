/**
 * Token-Verbrauch-Analyse unter Einstellungen -> Protokolle (nur Administratoren).
 *
 * Daten: GET /api/logs/token_verbrauch (backend/token_verbrauch.py). Je
 * Modellaufruf erfasst der Server Anbieter, Modell, Benutzer, Dienst, Kanal,
 * Werkzeuge und Tokenzahlen – keine Inhalte.
 *
 * Darstellung: gestapelte Saeulen je Zeiteimer (Stunde bis 2 Tage, sonst Tag),
 * aufgeteilt nach der gewaehlten Dimension; darunter die vollstaendige Tabelle
 * aller Gruppen. Das Diagramm ist ein selbst gezeichnetes SVG – das Frontend
 * hat bewusst keine Bibliothek (kein Build, keine Fremdeinbindung).
 *
 * Farben kommen ausschliesslich aus theme.css (--tv-farbe-1 … 8, -rest) ueber
 * Klassen; die Reihenfolge ist fest (groesste Gruppe = Farbe 1), damit dieselbe
 * Gruppe beim Umschalten der Messgroesse ihre Farbe behaelt.
 *
 * Alle Werte aus den Daten (Benutzer, Modellnamen, Kanaele kommen teils von
 * aussen) werden NUR per textContent gesetzt.
 */
window.TokenVerbrauch = (function () {
    'use strict';

    var DIMENSIONEN = ['llm', 'benutzer', 'dienst', 'werkzeug', 'kanal'];
    var UEBRIGE = '__uebrige__';
    var SVG_NS = 'http://www.w3.org/2000/svg';

    var gebunden = false;
    var daten = null;          // letzte Antwort des Servers
    var anfrageNr = 0;         // spaete Antworten einer ueberholten Anfrage verwerfen

    function $(id) { return document.getElementById(id); }

    function T(k, f) {
        var v = window.t ? window.t(k) : k;
        return (v && v !== k) ? v : f;
    }

    function token() {
        return window.authToken || (window.JarvisSitzung && window.JarvisSitzung.token());
    }

    function sprache() { return window._lang === 'en' ? 'en-GB' : 'de-DE'; }

    function zahl(n) {
        try { return new Intl.NumberFormat(sprache()).format(n || 0); }
        catch (e) { return String(n || 0); }
    }

    function kurz(n) {
        try {
            return new Intl.NumberFormat(sprache(), { notation: 'compact', maximumFractionDigits: 1 }).format(n || 0);
        } catch (e) { return String(n || 0); }
    }

    /** Kachelwert: unter 100.000 die genaue Zahl (mit Tausenderpunkt), darueber
     *  die Kurzform – die Kurzform gruppiert vierstellige Zahlen nicht ("1994"). */
    function kachelwert(n) { return (n || 0) >= 100000 ? kurz(n) : zahl(n); }

    function fehler(text) {
        var el = $('tv-fehler');
        if (!el) return;
        el.textContent = text || '';
        el.style.display = text ? 'block' : 'none';
    }

    // ── Beschriftungen ───────────────────────────────────────────────────────

    /** Lesbarer Name eines Gruppen-/Filterwerts. */
    function name(dim, wert, d) {
        d = d || daten || {};
        if (wert === UEBRIGE) return T('tv.uebrige', 'Übrige');
        if (wert === '' || wert === null || wert === undefined) {
            return T('tv.leer_' + dim, '—');
        }
        if (dim === 'benutzer') return (d.anzeige_benutzer || {})[wert] || wert;
        if (dim === 'dienst') return T('tv.d.' + wert, wert);
        if (dim === 'kanal') return T('tv.k.' + wert, wert);
        return String(wert);
    }

    // ── Laden ────────────────────────────────────────────────────────────────

    function auswahl() {
        var p = new URLSearchParams();
        p.set('tage', ($('tv-zeitraum') || {}).value || '7');
        p.set('gruppe', ($('tv-gruppe') || {}).value || 'llm');
        DIMENSIONEN.forEach(function (dim) {
            var sel = $('tv-f-' + dim);
            // "*" = alle; ein LEERER Wert ist ein gueltiger Filter (System, Hintergrund …)
            if (sel && sel.value !== '*') p.set(dim, sel.value);
        });
        return p;
    }

    async function laden() {
        binden();
        var nr = ++anfrageNr;
        var status = $('tv-status');
        if (status) status.textContent = T('common.loading', 'Lädt…');
        fehler('');
        try {
            var res = await fetch('/api/logs/token_verbrauch?' + auswahl().toString(), {
                headers: { 'Authorization': 'Bearer ' + token() }
            });
            if (!res.ok) {
                var grund = '';
                try { grund = (await res.json()).detail || ''; } catch (e) { /* kein JSON */ }
                throw new Error('HTTP ' + res.status + (grund ? ' – ' + grund : ''));
            }
            var d = await res.json();
            if (nr !== anfrageNr) return;       // inzwischen neue Auswahl
            daten = d;
            optionenFuellen(d);
            zeichnen();
        } catch (e) {
            if (nr !== anfrageNr) return;
            // Ein Fehler bleibt stehen (Register: nie von selbst verschwinden lassen).
            fehler(T('tv.fehler', 'Token-Verbrauch konnte nicht geladen werden:') + ' ' + e.message);
            if (status) status.textContent = '';
        }
    }

    /** Filter-Auswahllisten aus dem Zeitraum fuellen – die Auswahl bleibt erhalten,
     *  auch wenn ihr Wert im neuen Zeitraum nicht vorkommt (dann als eigene Option). */
    function optionenFuellen(d) {
        DIMENSIONEN.forEach(function (dim) {
            var sel = $('tv-f-' + dim);
            if (!sel) return;
            var gewaehlt = sel.value;
            var werte = ((d.optionen || {})[dim] || []).slice();
            if (gewaehlt !== '*' && werte.indexOf(gewaehlt) < 0) werte.unshift(gewaehlt);
            while (sel.options.length > 1) sel.remove(1);     // erste Option = "Alle"
            werte.forEach(function (w) {
                var o = document.createElement('option');
                o.value = w;
                o.textContent = name(dim, w, d);
                sel.appendChild(o);
            });
            sel.value = gewaehlt;
        });
    }

    // ── Messgroesse ──────────────────────────────────────────────────────────

    function mass() { return ($('tv-mass') || {}).value || 'summe'; }

    function reiheWerte(r) {
        var m = mass();
        return r.ein.map(function (_, i) {
            if (m === 'ein') return r.ein[i];
            if (m === 'aus') return r.aus[i];
            if (m === 'aufrufe') return r.aufrufe[i];
            return r.ein[i] + r.aus[i];
        });
    }

    function farbKlasse(i, schluessel) {
        return schluessel === UEBRIGE ? 'tv-f-rest' : 'tv-f' + (i + 1);
    }

    // ── Zeichnen ─────────────────────────────────────────────────────────────

    function zeichnen() {
        var d = daten;
        if (!d) return;
        kennzahlen(d);
        diagramm(d);
        legende(d);
        tabelle(d);
        var status = $('tv-status');
        if (status) {
            var teile = [];
            if (d.erfasst_seit) {
                teile.push(T('tv.seit', 'Erfassung seit {d}').replace('{d}',
                    new Date(d.erfasst_seit * 1000).toLocaleString(sprache(), { dateStyle: 'short', timeStyle: 'short' })));
            }
            if (d.aufbewahrung_tage) {
                teile.push(T('tv.aufbewahrung', 'aufbewahrt {n} Tage').replace('{n}', d.aufbewahrung_tage));
            }
            status.textContent = teile.join(' · ');
        }
    }

    function kennzahlen(d) {
        var box = $('tv-kennzahlen');
        if (!box) return;
        box.textContent = '';
        var s = d.summe || {};
        var kacheln = [
            ['tv.k_summe', 'Tokens gesamt', kachelwert((s.ein || 0) + (s.aus || 0)), zahl((s.ein || 0) + (s.aus || 0))],
            ['tv.k_ein', 'Eingabe', kachelwert(s.ein), zahl(s.ein)],
            ['tv.k_aus', 'Ausgabe', kachelwert(s.aus), zahl(s.aus)],
            ['tv.k_aufrufe', 'Aufrufe', zahl(s.aufrufe), zahl(s.aufrufe)]
        ];
        kacheln.forEach(function (k) {
            var div = document.createElement('div');
            div.className = 'tv-kachel';
            div.title = k[3];
            var w = document.createElement('div');
            w.className = 'tv-kachel-wert';
            w.textContent = k[2];
            var l = document.createElement('div');
            l.className = 'tv-kachel-name';
            l.textContent = T(k[0], k[1]);
            div.appendChild(w);
            div.appendChild(l);
            box.appendChild(div);
        });
        // Was die Summen NICHT enthalten, steht daneben – sonst laese man sie als vollstaendig.
        var zusatz = [];
        if (s.cache_lesen) zusatz.push(T('tv.k_cache', 'davon {n} Eingabe-Tokens aus dem Cache').replace('{n}', zahl(s.cache_lesen)));
        if (s.ohne_angabe === 1) zusatz.push(T('tv.k_ohne_1', '1 Aufruf ohne Zählung des Anbieters (nicht in den Summen)'));
        else if (s.ohne_angabe) zusatz.push(T('tv.k_ohne', '{n} Aufrufe ohne Zählung des Anbieters (nicht in den Summen)').replace('{n}', zahl(s.ohne_angabe)));
        if (s.fehler) zusatz.push(T('tv.k_fehler', '{n} fehlgeschlagen').replace('{n}', zahl(s.fehler)));
        var z = $('tv-zusatz');
        if (z) z.textContent = zusatz.join(' · ');
    }

    function svgEl(tag, attrs) {
        var el = document.createElementNS(SVG_NS, tag);
        Object.keys(attrs || {}).forEach(function (k) { el.setAttribute(k, attrs[k]); });
        return el;
    }

    function zeitText(ts, raster, lang) {
        var dt = new Date(ts * 1000);
        try {
            if (raster === 'stunde') return dt.toLocaleTimeString(lang, { hour: '2-digit', minute: '2-digit' });
            return dt.toLocaleDateString(lang, { day: '2-digit', month: '2-digit' });
        } catch (e) { return String(ts); }
    }

    function zeitLang(ts, raster) {
        var dt = new Date(ts * 1000);
        try {
            if (raster === 'stunde') {
                return dt.toLocaleString(sprache(), { weekday: 'short', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' });
            }
            return dt.toLocaleDateString(sprache(), { weekday: 'short', day: '2-digit', month: '2-digit', year: 'numeric' });
        } catch (e) { return String(ts); }
    }

    /** Achse mit runden Marken: Schrittweite 1, 2, 2,5 oder 5 × 10^n, so dass
     *  hoechstens ~4 Schritte bis ueber das Maximum reichen. Die erste Fassung
     *  teilte eine "schoene" Obergrenze in Viertel – aus 5 Mio. wurden Marken
     *  bei 1,25 und 3,75 Mio., kompakt gerundet als "1,3 Mio." und "3,8 Mio."
     *  (im Screenshot der Abnahme gesehen). Rueckgabe: {oben, schritt, n}. */
    function achsenteilung(max) {
        if (!(max > 0)) return { oben: 1, schritt: 0.25, n: 4 };
        var roh = max / 4;
        var p = Math.pow(10, Math.floor(Math.log10(roh)));
        var stufen = [1, 2, 2.5, 5, 10];
        var schritt = 10 * p;
        for (var i = 0; i < stufen.length; i++) {
            if (stufen[i] * p >= roh) { schritt = stufen[i] * p; break; }
        }
        // Aufrufe sind ganze Zahlen: keine Marke bei 0,5 Aufrufen.
        if (mass() === 'aufrufe' && schritt < 1) schritt = 1;
        var n = Math.max(1, Math.ceil(max / schritt - 1e-9));
        return { oben: n * schritt, schritt: schritt, n: n };
    }

    function diagramm(d) {
        var box = $('tv-diagramm');
        if (!box) return;
        box.textContent = '';
        var achse = d.zeitachse || [];
        var reihen = d.reihen || [];
        var leer = !reihen.length;
        if (leer) {
            var p = document.createElement('p');
            p.className = 'kb-hint tv-leer';
            p.textContent = d.erfasst_seit
                ? T('tv.leer', 'Im gewählten Zeitraum wurden mit diesen Filtern keine Modellaufrufe erfasst.')
                : T('tv.noch_nie', 'Es wurden noch keine Modellaufrufe erfasst. Die Erfassung beginnt mit dem ersten Modellaufruf nach dem Update.');
            box.appendChild(p);
            return;
        }
        var werte = reihen.map(reiheWerte);
        var summen = achse.map(function (_, i) {
            return werte.reduce(function (a, w) { return a + (w[i] || 0); }, 0);
        });
        var teilung = achsenteilung(Math.max.apply(null, summen.concat([0])));
        var oben = teilung.oben;

        var breite = Math.max(320, box.clientWidth || 800);
        var hoehe = 240;
        var rand = { l: 52, r: 8, o: 10, u: 26 };
        var innenB = breite - rand.l - rand.r;
        var innenH = hoehe - rand.o - rand.u;
        var n = achse.length || 1;
        var schritt = innenB / n;
        var saeule = Math.max(1, Math.min(42, schritt * 0.72));

        var svg = svgEl('svg', {
            'class': 'tv-svg', viewBox: '0 0 ' + breite + ' ' + hoehe,
            width: breite, height: hoehe, role: 'img',
            'aria-label': T('tv.title', 'Token-Verbrauch-Analyse')
        });

        // Gitter + Y-Beschriftung an runden Werten
        for (var g = 0; g <= teilung.n; g++) {
            var wert = teilung.schritt * g;
            var y = rand.o + innenH - innenH * g / teilung.n;
            svg.appendChild(svgEl('line', { x1: rand.l, x2: breite - rand.r, y1: y, y2: y, 'class': g ? 'tv-gitter' : 'tv-achse' }));
            var t = svgEl('text', { x: rand.l - 6, y: y + 4, 'class': 'tv-achsentext', 'text-anchor': 'end' });
            t.textContent = mass() === 'aufrufe' ? zahl(wert) : kurz(wert);
            svg.appendChild(t);
        }

        // X-Beschriftung: hoechstens ~10 Marken, gleichmaessig verteilt
        var jede = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(innenB / 70))));
        var lang = sprache();
        achse.forEach(function (ts, i) {
            if (i % jede !== 0) return;
            var tx = svgEl('text', {
                x: rand.l + schritt * i + schritt / 2, y: hoehe - 8,
                'class': 'tv-achsentext', 'text-anchor': 'middle'
            });
            tx.textContent = zeitText(ts, d.raster, lang);
            svg.appendChild(tx);
        });

        // Saeulen: je Eimer die Reihen von unten nach oben (groesste Gruppe unten)
        achse.forEach(function (ts, i) {
            var x = rand.l + schritt * i + (schritt - saeule) / 2;
            var basis = rand.o + innenH;
            werte.forEach(function (w, r) {
                var v = w[i] || 0;
                if (!v) return;
                var h = innenH * v / oben;
                basis -= h;
                svg.appendChild(svgEl('rect', {
                    x: x, y: basis, width: saeule, height: Math.max(h, 0.5),
                    'class': 'tv-seg ' + farbKlasse(r, reihen[r].schluessel)
                }));
            });
            // Unsichtbare Trefferflaeche ueber die volle Hoehe – auch ein leerer Eimer zeigt seinen Wert.
            var treffer = svgEl('rect', {
                x: rand.l + schritt * i, y: rand.o, width: schritt, height: innenH,
                'class': 'tv-treffer', 'data-i': i, tabindex: '-1'
            });
            svg.appendChild(treffer);
        });

        svg.addEventListener('mousemove', function (ev) {
            var ziel = ev.target;
            if (!ziel || !ziel.getAttribute || ziel.getAttribute('data-i') === null) { tipp(null); return; }
            tipp(+ziel.getAttribute('data-i'), ev, box);
        });
        svg.addEventListener('mouseleave', function () { tipp(null); });
        box.appendChild(svg);

        var tip = document.createElement('div');
        tip.id = 'tv-tipp';
        tip.className = 'tv-tipp';
        tip.hidden = true;
        box.appendChild(tip);
    }

    function tipp(i, ev, box) {
        var tip = $('tv-tipp');
        if (!tip) return;
        if (i === null || !daten) { tip.hidden = true; return; }
        var d = daten;
        var dim = d.gruppe;
        tip.textContent = '';
        var kopf = document.createElement('div');
        kopf.className = 'tv-tipp-kopf';
        kopf.textContent = zeitLang(d.zeitachse[i], d.raster);
        tip.appendChild(kopf);
        var gesamt = 0;
        (d.reihen || []).forEach(function (r, ri) {
            var v = reiheWerte(r)[i] || 0;
            if (!v) return;
            gesamt += v;
            var z = document.createElement('div');
            z.className = 'tv-tipp-zeile';
            var f = document.createElement('span');
            f.className = 'tv-punkt ' + farbKlasse(ri, r.schluessel);
            var nme = document.createElement('span');
            nme.className = 'tv-tipp-name';
            nme.textContent = r.schluessel === UEBRIGE
                ? T('tv.uebrige', 'Übrige') + ' (' + (r.anzahl || 0) + ')'
                : name(dim, r.schluessel);
            var w = document.createElement('span');
            w.className = 'tv-tipp-wert';
            w.textContent = zahl(v);
            z.appendChild(f); z.appendChild(nme); z.appendChild(w);
            tip.appendChild(z);
        });
        var fuss = document.createElement('div');
        fuss.className = 'tv-tipp-fuss';
        fuss.textContent = gesamt
            ? T('tv.tipp_summe', 'Summe: {n}').replace('{n}', zahl(gesamt))
            : T('tv.tipp_leer', 'keine Aufrufe');
        tip.appendChild(fuss);
        tip.hidden = false;
        // Position: rechts neben dem Zeiger, am Rand umklappen
        var rb = box.getBoundingClientRect();
        var x = ev.clientX - rb.left + 14;
        var y = ev.clientY - rb.top + 10;
        var tb = tip.getBoundingClientRect();
        if (x + tb.width > rb.width) x = Math.max(0, ev.clientX - rb.left - tb.width - 14);
        tip.style.left = x + 'px';
        tip.style.top = y + 'px';
    }

    function legende(d) {
        var box = $('tv-legende');
        if (!box) return;
        box.textContent = '';
        (d.reihen || []).forEach(function (r, i) {
            var e = document.createElement('span');
            e.className = 'tv-legende-eintrag';
            var f = document.createElement('span');
            f.className = 'tv-punkt ' + farbKlasse(i, r.schluessel);
            var t = document.createElement('span');
            t.textContent = r.schluessel === UEBRIGE
                ? T('tv.uebrige', 'Übrige') + ' (' + (r.anzahl || 0) + ')'
                : name(d.gruppe, r.schluessel);
            e.appendChild(f);
            e.appendChild(t);
            box.appendChild(e);
        });
    }

    function tabelle(d) {
        var kopf = $('tv-tab-gruppe');
        if (kopf) kopf.textContent = T('tv.g_' + d.gruppe, d.gruppe);
        var tb = $('tv-tbody');
        if (!tb) return;
        tb.textContent = '';
        var zeilen = d.tabelle || [];
        var s = d.summe || {};
        var gesamt = (s.ein || 0) + (s.aus || 0);
        if (!zeilen.length) {
            var tr0 = document.createElement('tr');
            var td0 = document.createElement('td');
            td0.colSpan = 7;
            td0.className = 'audit-empty';
            td0.textContent = T('tv.leer_tabelle', 'Keine Einträge');
            tr0.appendChild(td0);
            tb.appendChild(tr0);
            return;
        }
        // Farbe in der Tabelle nur fuer die Gruppen, die im Diagramm eine eigene Reihe haben.
        var reihenIndex = {};
        (d.reihen || []).forEach(function (r, i) { if (r.schluessel !== UEBRIGE) reihenIndex[r.schluessel] = i; });
        zeilen.forEach(function (z) {
            var tr = document.createElement('tr');
            var summe = (z.ein || 0) + (z.aus || 0);
            var gemessen = (z.aufrufe || 0) - (z.ohne_angabe || 0);
            var zellen = [
                null,
                zahl(z.aufrufe),
                zahl(z.ein),
                zahl(z.aus),
                zahl(summe),
                gesamt ? (100 * summe / gesamt).toLocaleString(sprache(), { maximumFractionDigits: 1 }) + ' %' : '—',
                z.aufrufe ? zahl(Math.round((z.ms || 0) / z.aufrufe)) + ' ms' : '—'
            ];
            var td = document.createElement('td');
            if (Object.prototype.hasOwnProperty.call(reihenIndex, z.schluessel)) {
                var f = document.createElement('span');
                f.className = 'tv-punkt ' + farbKlasse(reihenIndex[z.schluessel], z.schluessel);
                td.appendChild(f);
            }
            var nm = document.createElement('span');
            nm.textContent = name(d.gruppe, z.schluessel);
            td.appendChild(nm);
            if (z.ohne_angabe) {
                var hinweis = document.createElement('span');
                hinweis.className = 'tv-ohne';
                hinweis.textContent = ' · ' + T('tv.ohne_kurz', '{n} ohne Zählung').replace('{n}', zahl(z.ohne_angabe));
                td.appendChild(hinweis);
            }
            if (z.fehler) {
                var fe = document.createElement('span');
                fe.className = 'tv-ohne';
                fe.textContent = ' · ' + T('tv.k_fehler', '{n} fehlgeschlagen').replace('{n}', zahl(z.fehler));
                td.appendChild(fe);
            }
            tr.appendChild(td);
            zellen.slice(1).forEach(function (w, i) {
                var c = document.createElement('td');
                c.className = 'tv-zahl';
                // Spalten Ein/Aus/Summe ohne jede gemessene Zahl: Strich statt einer 0,
                // die wie "nichts uebertragen" aussaehe.
                c.textContent = (i >= 1 && i <= 3 && gemessen <= 0) ? '—' : w;
                tr.appendChild(c);
            });
            tb.appendChild(tr);
        });
    }

    // ── Ereignisse ───────────────────────────────────────────────────────────

    function binden() {
        if (gebunden) return;
        gebunden = true;
        ['tv-zeitraum', 'tv-gruppe'].concat(DIMENSIONEN.map(function (d) { return 'tv-f-' + d; }))
            .forEach(function (id) {
                var el = $(id);
                if (el) el.addEventListener('change', laden);
            });
        var m = $('tv-mass');
        if (m) m.addEventListener('change', zeichnen);   // Messgroesse: keine neue Anfrage
        var r = $('tv-refresh-btn');
        if (r) r.addEventListener('click', laden);
        var z = $('tv-zuruecksetzen');
        if (z) z.addEventListener('click', function () {
            DIMENSIONEN.forEach(function (d) { var s = $('tv-f-' + d); if (s) s.value = '*'; });
            laden();
        });
        // Breite folgt dem Fenster (das SVG wird in Pixeln der Box gezeichnet).
        var warte = null;
        window.addEventListener('resize', function () {
            clearTimeout(warte);
            warte = setTimeout(function () {
                var body = $('tv-section-body');
                if (daten && body && body.style.display !== 'none') diagramm(daten);
            }, 150);
        });
        // Sprachwechsel: Beschriftungen aus den Daten neu setzen.
        document.addEventListener('jarvis-lang-changed', function () {
            if (daten) { optionenFuellen(daten); zeichnen(); }
        });
    }

    return { laden: laden, _name: name, _achsenteilung: achsenteilung };
})();
