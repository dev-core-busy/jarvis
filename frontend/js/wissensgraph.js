/**
 * Wissensgraph (/wissensgraph) – Admin-Seite: Grafik, Auffaelligkeiten, Pflege.
 *
 * Plan "Wissensgraph fuer das Jarvis-RAG", Phase 4. Die Seite ist eine LEERE
 * HUELLE: sie prueft /api/me (nur Admins), die DATEN liegen ausschliesslich
 * hinter require_local_auth. Eine versteckte Kachel ist keine Berechtigung.
 *
 * Grafik: sigma 4 (WebGL 2) + graphology, Anordnung ForceAtlas2 im Worker,
 * Themen-Inseln per Louvain – alles als selbst gebaute IIFE-Bundles unter
 * js/vendor (HERKUNFT.txt), kein CDN.
 *
 * ⚠ FARBEN NUR AUS theme.css: sigma braucht konkrete Werte, gelesen werden
 * die Variablen --graph-* per getComputedStyle – und bei jedem Themenwechsel
 * neu, sonst bliebe die Grafik nach dem Umschalten im alten Thema.
 *
 * ⚠ DIE AUFFAELLIGKEITEN ENTSTEHEN HIER, nicht im Server: sie bauen auf den
 * Themen-Inseln auf, die die Legende zeigt. Eine zweite Berechnung im Server
 * liefe auseinander, und dann spraeche eine Karte von einer Insel, die es in
 * der Grafik nicht gibt.
 */
(function () {
    'use strict';

    var SEITE = 500;                 // Knoten je Abruf, nach Grad sortiert
    var POS_SPEICHER = 'jarvis_wg_pos';
    var POS_MAX = 6000;
    // Frueher lag "ausgeblendet" je Browser in localStorage; seit Phase 6 beim
    // Server (Rueckkopplung fuer alle Admins). Der alte Schluessel wird geraeumt.
    var WEG_SPEICHER_ALT = 'jarvis_wg_insights_weg';
    // Wie stark ein verworfener Hinweis aehnliche Vorschlaege zurueckstuft:
    // Faktor = 1 - RUECK_GEWICHT x Aehnlichkeit (1 = teilt einen Begriff,
    // 0,5 = gleiche Arten).
    var RUECK_GEWICHT = 0.6;
    var VORLAGE_SPEICHER = 'jarvis_chat_vorlage';
    var KOHAESION_WARNUNG = 0.15;
    var TYPEN = ['system', 'konzept', 'prozess', 'produkt', 'organisation', 'person', 'ort', 'quelle'];

    var G = null;                    // graphology-Graph
    var R = null;                    // sigma-Renderer
    var _layout = null;              // laufender FA2-Worker
    var _modus = 'typ';              // 'typ' | 'insel'
    var _farben = null;
    var _hover = null;               // Knoten unter dem Zeiger
    var _hervor = null;              // {knoten:Set, kanten:Set} – Suche/Auffaelligkeit
    var _inseln = [];                // [{id, mitglieder, wichtigster, kohaesion, farbe}]
    var _offset = 0;
    var _gefiltert = 0;
    var _statusTimer = null;
    var _gruppen = [];
    // Rechte des Betrachters (/api/wissensgraph/zugang): stufe global|gruppen|keine,
    // gruppen [{id,name}], pflegen (globaler Wissenseditor), steuern (Admin).
    var _zugang = { stufe: 'keine', gruppen: [], pflegen: false, steuern: false };
    var _verworfen = [];             // Rueckmeldungen vom Server
    var _widersprueche = [];         // gueltige Befunde vom Server

    // ── Grundlagen ──────────────────────────────────────────────────────────

    function $(id) { return document.getElementById(id); }

    function tok() {
        try { return window.JarvisSitzung.token(); } catch (e) { return ''; }
    }

    function hole(pfad, opt) {
        var o = opt || {};
        o.headers = o.headers || {};
        o.headers['Authorization'] = 'Bearer ' + tok();
        return fetch(pfad, o);
    }

    function holeJson(pfad, opt) {
        return hole(pfad, opt).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (d) {
                if (!r.ok) { throw new Error(fehlertext(d, 'HTTP ' + r.status)); }
                return d;
            });
        });
    }

    function sende(pfad, methode, rumpf) {
        return holeJson(pfad, {
            method: methode,
            headers: { 'Content-Type': 'application/json' },
            body: rumpf === undefined ? undefined : JSON.stringify(rumpf)
        });
    }

    /** Jarvis meldet `error`, FastAPI `detail` – nur eines zu lesen liesse eine
     *  vorhandene Begruendung verschwinden (Register). */
    function fehlertext(d, rueckfall) {
        if (!d) { return rueckfall; }
        return d.error || d.detail || d.message || rueckfall;
    }

    // window.t liefert bei fehlendem Schluessel den Schluessel selbst – der
    // Rueckfall muss das abfangen (Hausweg wie feedback.js).
    function t(key, fallback, werte) {
        var s = (window.t && window.t(key) !== key ? window.t(key) : null) || fallback;
        if (werte) {
            Object.keys(werte).forEach(function (k) { s = s.split('{' + k + '}').join(String(werte[k])); });
        }
        return s;
    }

    function el(tag, klasse, text) {
        var e = document.createElement(tag);
        if (klasse) { e.className = klasse; }
        if (text !== undefined && text !== null) { e.textContent = text; }
        return e;
    }

    function norm(s) {
        return String(s || '').toLowerCase()
            .replace(/ä/g, 'ae').replace(/ö/g, 'oe').replace(/ü/g, 'ue').replace(/ß/g, 'ss')
            .replace(/[^a-z0-9]+/g, ' ').trim();
    }

    function speicherLesen(k, vorgabe) {
        try { var v = JSON.parse(localStorage.getItem(k) || 'null'); return v === null ? vorgabe : v; }
        catch (e) { return vorgabe; }
    }

    function speicherSchreiben(k, v) {
        try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* privater Modus */ }
    }

    /** Drehender Kreis + Text in ``ziel`` (ersetzt den Inhalt). Gestalt
     *  ``.jv-pkg-spin`` aus theme.css – derselbe Kreis wie im uebrigen Haus. */
    function ladeText(ziel, text) {
        if (!ziel) { return; }
        ziel.textContent = '';
        var k = el('span', 'jv-pkg-spin');
        k.setAttribute('aria-hidden', 'true');
        ziel.appendChild(k);
        ziel.appendChild(document.createTextNode(text));
    }

    function hinweis(text, art) {
        var h = $('wg-hinweis');
        if (!h) { return; }
        if (art === 'lade') { ladeText(h, text); } else { h.textContent = text || ''; }
        h.classList.toggle('hidden', !text);
        h.classList.toggle('is-err', art === 'err');
    }

    function artName(typ) {
        return t('wissensgraph.type_' + typ, typ);
    }

    // ── Farben aus theme.css ────────────────────────────────────────────────

    function farbenLesen() {
        var cs = getComputedStyle(document.body);
        function v(n, vorgabe) { return (cs.getPropertyValue(n) || '').trim() || vorgabe; }
        var pal = [];
        for (var i = 1; i <= 12; i++) { pal.push(v('--graph-c' + i, '')); }
        _farben = {
            palette: pal,
            stark: v('--graph-kante-stark', ''),
            schwach: v('--graph-kante-schwach', ''),
            gedimmt: v('--graph-gedimmt', ''),
            widerspruch: v('--graph-widerspruch', ''),
            text: v('--text-primary', ''),
            grund: v('--bg-secondary', ''),
            akzent: v('--accent', '')
        };
        return _farben;
    }

    function farbeFuerTyp(typ) {
        var i = TYPEN.indexOf(typ);
        return _farben.palette[(i < 0 ? 11 : i) % 12];
    }

    // ── WebGL 2 ─────────────────────────────────────────────────────────────

    /** sigma 4 startet ohne WebGL 2 gar nicht (Messbericht Phase 0). Statt einer
     *  leeren Flaeche steht dann eine Meldung – die Listen darunter gehen weiter. */
    function webgl2() {
        try { return !!document.createElement('canvas').getContext('webgl2'); }
        catch (e) { return false; }
    }

    /** Kann die GRAFIK gezeichnet werden? ⚠ sigma wirft schon beim LADEN, wenn
     *  ein Browser `WebGL2RenderingContext` gar nicht kennt – dann fehlt
     *  `JarvisSigma` ganz. Das ist derselbe Fall wie "kein WebGL 2", nicht
     *  "Bibliotheken fehlen": Auffaelligkeiten, Pruefliste und Pflege brauchen
     *  sigma nicht und muessen weiterlaufen (im jsdom-Waechter gemessen). */
    function grafikMoeglich() {
        return !!window.JarvisSigma && webgl2();
    }

    /** Die Rechen-Bibliotheken (ohne sigma) – ohne sie gibt es keine Inseln. */
    function bibliothekenDa() {
        return !!(window.JarvisGraphology && window.JarvisFA2 && window.JarvisLouvain);
    }

    // ── Positions-Cache ─────────────────────────────────────────────────────

    function positionenLaden() { return speicherLesen(POS_SPEICHER, {}) || {}; }

    function positionenSichern() {
        if (!G) { return; }
        var alt = positionenLaden();
        G.forEachNode(function (n, a) { alt[n] = [Math.round(a.x * 100) / 100, Math.round(a.y * 100) / 100]; });
        var schluessel = Object.keys(alt);
        if (schluessel.length > POS_MAX) {
            // Die im Graphen vorhandenen behalten, den Rest abschneiden.
            var neu = {};
            G.forEachNode(function (n) { neu[n] = alt[n]; });
            alt = neu;
        }
        speicherSchreiben(POS_SPEICHER, alt);
    }

    // ── Graph aufbauen ──────────────────────────────────────────────────────

    function filterParameter() {
        var p = new URLSearchParams();
        var typ = $('wg-typ') ? $('wg-typ').value : '';
        var gr = $('wg-gruppe') ? $('wg-gruppe').value : '';
        var ord = $('wg-ordner') ? $('wg-ordner').value : '';
        var dok = $('wg-dokumente') ? $('wg-dokumente').checked : true;
        if (typ) { p.set('typ', typ); }
        if (gr) { p.set('gruppe', gr); }
        if (ord) { p.set('ordner', ord); }
        p.set('dokumente', dok ? 'true' : 'false');
        return p;
    }

    function knotenGroesse(grad) { return 2.5 + 1.8 * Math.sqrt(Math.max(0, grad)); }

    function graphFuellen(d, anhaengen) {
        var pos = positionenLaden();
        // ⚠ DENSELBEN Graphen leeren, nie einen neuen anlegen: sigma (und der
        // FA2-Worker) haengen an der Instanz. Mit einem neuen Objekt zeichnete die
        // Grafik den ALTEN Graphen weiter, die Reduzierer fragten im neuen nach
        // dessen Kanten – "Graph.extremities: could not find the edge", gemeldet
        // als "Laden fehlgeschlagen" bei jedem Filterwechsel (2026-10-31).
        if (!G) {
            G = new window.JarvisGraphology.Graph({ type: 'undirected', multi: false });
        } else if (!anhaengen) {
            G.clear();
        }
        (d.knoten || []).forEach(function (k) {
            if (G.hasNode(k.id)) { return; }
            var p = pos[k.id];
            G.addNode(k.id, {
                label: k.name, typ: k.typ, grad: k.grad, quellen: (k.sources || []).length,
                x: p ? p[0] : Math.random() * 100, y: p ? p[1] : Math.random() * 100,
                size: knotenGroesse(k.grad), _gecacht: !!p
            });
        });
        (d.kanten || []).forEach(function (e) {
            if (!G.hasNode(e.von) || !G.hasNode(e.nach) || e.von === e.nach) { return; }
            var vorhanden = G.edge(e.von, e.nach);
            var erwaehnt = e.art === 'erwaehnt_in';
            var widerspruch = e.art === 'widerspricht';
            if (vorhanden) {
                var a = G.getEdgeAttributes(vorhanden);
                G.mergeEdgeAttributes(vorhanden, {
                    gewicht: Math.max(a.gewicht, e.gewicht),
                    arten: a.arten.concat([e.art]), erwaehnt: a.erwaehnt && erwaehnt,
                    widerspruch: a.widerspruch || widerspruch
                });
            } else {
                G.addEdge(e.von, e.nach, { gewicht: e.gewicht, arten: [e.art], erwaehnt: erwaehnt,
                                           widerspruch: widerspruch });
            }
        });
        _offset = (d.offset || 0) + (d.knoten || []).length;
        _gefiltert = d.gefiltert || 0;
        zaehlerZeichnen(d);
    }

    function zaehlerZeichnen(d) {
        var z = $('wg-zaehler');
        if (z) {
            z.textContent = t('wissensgraph.count', '{n} von {total} Begriffen gezeigt',
                              { n: G ? G.order : 0, total: _gefiltert });
        }
        var m = $('wg-mehr');
        if (m) { m.classList.toggle('hidden', !G || G.order >= _gefiltert); }
    }

    function inselnBerechnen() {
        _inseln = [];
        if (!G || !G.order) { return; }
        var zuordnung = {};
        try {
            zuordnung = window.JarvisLouvain.louvain(G, { getEdgeWeight: 'gewicht' });
        } catch (e) {
            G.forEachNode(function (n) { zuordnung[n] = 0; });
        }
        var gruppen = {};
        G.forEachNode(function (n, a) {
            var c = zuordnung[n];
            G.setNodeAttribute(n, 'insel', c);
            (gruppen[c] = gruppen[c] || []).push(n);
        });
        Object.keys(gruppen).forEach(function (c) {
            var mitglieder = gruppen[c];
            var menge = {};
            mitglieder.forEach(function (n) { menge[n] = true; });
            var innen = 0;
            mitglieder.forEach(function (n) {
                G.forEachNeighbor(n, function (m) { if (menge[m] && n < m) { innen++; } });
            });
            var moeglich = mitglieder.length * (mitglieder.length - 1) / 2;
            var wichtigster = mitglieder.reduce(function (best, n) {
                return G.getNodeAttribute(n, 'grad') > G.getNodeAttribute(best, 'grad') ? n : best;
            }, mitglieder[0]);
            // ⚠ Die Kennung vom KNOTEN nehmen: Object.keys liefert Zeichenketten,
            // am Knoten steht die Zahl aus louvain – ein === dazwischen trifft nie.
            _inseln.push({ id: G.getNodeAttribute(mitglieder[0], 'insel'),
                           mitglieder: mitglieder.length, wichtigster: wichtigster,
                           kohaesion: moeglich ? innen / moeglich : 1 });
        });
        _inseln.sort(function (a, b) { return b.mitglieder - a.mitglieder; });
        _inseln.forEach(function (ins, i) { ins.rang = i; });
        var rang = {};
        _inseln.forEach(function (ins) { rang[ins.id] = ins.rang; });
        G.forEachNode(function (n, a) { G.setNodeAttribute(n, 'inselRang', rang[a.insel]); });
    }

    function grundfarbe(a) {
        if (_modus === 'insel') { return _farben.palette[Math.min(a.inselRang, 11)]; }
        return farbeFuerTyp(a.typ);
    }

    // ── Darstellung ─────────────────────────────────────────────────────────

    function nachbarn(n) {
        var s = {};
        if (G && G.hasNode(n)) { G.forEachNeighbor(n, function (m) { s[m] = true; }); }
        return s;
    }

    function relevanzText(a) {
        if ((a.arten || []).indexOf('widerspricht') >= 0) {
            return t('wissensgraph.rel_contra', 'widersprechen sich');
        }
        var art = (a.arten || []).filter(function (x) { return x !== 'erwaehnt_in'; })[0];
        var belege = t(a.gewicht === 1 ? 'wissensgraph.rel_one' : 'wissensgraph.rel_many',
                       a.gewicht === 1 ? '1 Dokument' : '{n} Dokumente', { n: a.gewicht });
        return art ? art.replace(/_/g, ' ') + ' · ' + belege : belege;
    }

    // ⚠ sigma 4 ruft (key, ANZEIGEDATEN, ATTRIBUTE, …) – die eigenen Attribute
    // (typ, inselRang, gewicht) stehen erst im DRITTEN Argument. Mit dem
    // zweiten waren alle Knoten grau und die Inselfaerbung warf (live gesehen).
    function knotenReduzierer(n, anzeige, a) {
        // Felder nach sigma 4 (types.d.ts DisplayData): die Beschriftungsfarbe
        // steht JE KNOTEN (`labelColor`, keine Einstellung mehr), erzwungene
        // Beschriftung heisst `labelVisibility: 'visible'`.
        // backdropColor: sigma 4 legt beim Ueberfahren einen Kasten unter den
        // Namen – fest WEISS, waehrend die Schrift im dunklen Thema hell ist; der
        // Name war unsichtbar (Screenshot 2026-10-31). Der Kasten nimmt deshalb
        // den Grund des Themas.
        var r = { label: a.label, size: a.size, x: a.x, y: a.y, color: grundfarbe(a), zIndex: 1,
                  labelColor: _farben.text, backdropColor: _farben.grund };
        // Erzwungen beschriftet wird nur eine begrenzte Auswahl (``beschriftet``) –
        // die uebrigen Nachbarn bleiben hell, ihre Beschriftung entscheidet das
        // Raster von sigma (keine Ueberlappung). Bei einem Knoten mit hundert
        // Nachbarn lagen sonst hundert Beschriftungen uebereinander.
        if (_hover) {
            var nb = _hoverNachbarn;
            if (n !== _hover && !nb[n]) { r.color = _farben.gedimmt; r.label = ''; r.zIndex = 0; }
            else {
                r.zIndex = 2;
                if (n === _hover || _hoverAuswahl.knoten[n]) { r.labelVisibility = 'visible'; }
            }
        } else if (_hervor) {
            if (!_hervor.knoten[n]) { r.color = _farben.gedimmt; r.label = ''; r.zIndex = 0; }
            else {
                r.zIndex = 2; r.highlighted = true;
                if (_hervor.beschriftet[n]) { r.labelVisibility = 'visible'; }
            }
        }
        return r;
    }

    var _hoverNachbarn = {};
    var _hoverAuswahl = { knoten: {}, kanten: {} };
    // Hoechstzahl erzwungener Beschriftungen beim Ueberfahren/Hervorheben und
    // der Kantentexte beim Ueberfahren.
    var MAX_BESCHRIFTUNGEN = 12;
    var MAX_KANTENTEXTE = 6;

    /** Aus ``kandidaten`` (beste zuerst) hoechstens ``max`` waehlen, deren
     *  Beschriftungskasten keinen schon gewaehlten schneidet. ``kasten(n)``
     *  liefert {x1,y1,x2,y2} in Bildschirmpunkten oder null (dann zaehlt nur die
     *  Anzahl). ``belegt``: Kaesten, die schon stehen (der ueberfahrene Knoten).
     *  Gemessen: zwoelf erzwungene Namen um einen grossen Knoten lagen
     *  uebereinander, weil seine Nachbarn dicht beieinander liegen. */
    function freiAuswaehlen(kandidaten, kasten, max, belegt) {
        var stehen = (belegt || []).slice(), raus = [];
        function schneidet(a, b) { return a.x1 < b.x2 && b.x1 < a.x2 && a.y1 < b.y2 && b.y1 < a.y2; }
        for (var i = 0; i < kandidaten.length && raus.length < max; i++) {
            var k = kasten ? kasten(kandidaten[i]) : null;
            if (k && stehen.some(function (b) { return schneidet(k, b); })) { continue; }
            if (k) { stehen.push(k); }
            raus.push(kandidaten[i]);
        }
        return raus;
    }

    /** Beschriftungskasten eines Knotens auf dem Bildschirm (sigma setzt den
     *  Namen rechts neben den Punkt). Ohne Renderer: null. */
    function beschriftungsKasten(n) {
        if (!R || !G || !G.hasNode(n)) { return null; }
        var d = R.getNodeDisplayData(n);
        if (!d) { return null; }
        var v = R.framedGraphToViewport(d);
        var gr = 14;
        try { gr = R.getSetting('labelSize') || 14; } catch (e) { /* Vorgabe */ }
        var r = typeof R.scaleSize === 'function' ? R.scaleSize(d.size) : d.size;
        var text = String(G.getNodeAttribute(n, 'label') || '');
        return { x1: v.x - r, y1: v.y - gr / 2 - 2, x2: v.x + r + 4 + text.length * gr * 0.55, y2: v.y + gr / 2 + 2 };
    }

    // Die staerksten Nachbarn eines Knotens: Belegzahl der Kante, dann
    // Knotengroesse, dann Schluessel (feste Reihenfolge).
    function hoverAuswahl(n) {
        var aus = { knoten: {}, kanten: {} };
        if (!G || !G.hasNode(n)) { return aus; }
        var liste = [];
        G.forEachEdge(n, function (k, a, q, z) {
            var m = q === n ? z : q;
            liste.push({ k: k, m: m, g: a.erwaehnt ? 0 : (a.gewicht || 0),
                         s: G.getNodeAttribute(m, 'size') || 0 });
        });
        liste.sort(function (x, y) {
            return (y.g - x.g) || (y.s - x.s) || (x.m < y.m ? -1 : (x.m > y.m ? 1 : 0));
        });
        var nachbarn = [];
        liste.forEach(function (e, i) {
            if (i < MAX_KANTENTEXTE) { aus.kanten[e.k] = true; }
            if (nachbarn.indexOf(e.m) < 0) { nachbarn.push(e.m); }
        });
        var eigener = beschriftungsKasten(n);
        freiAuswaehlen(nachbarn, beschriftungsKasten, MAX_BESCHRIFTUNGEN, eigener ? [eigener] : [])
            .forEach(function (m) { aus.knoten[m] = true; });
        return aus;
    }

    // Die groessten Knoten einer Auswahl – sie werden beim Hervorheben
    // beschriftet, die uebrigen nur hervorgehoben.
    function groessteKnoten(menge) {
        var liste = Object.keys(menge).sort(function (x, y) {
            return ((G.getNodeAttribute(y, 'size') || 0) - (G.getNodeAttribute(x, 'size') || 0))
                || (x < y ? -1 : (x > y ? 1 : 0));
        });
        var raus = {};
        freiAuswaehlen(liste, beschriftungsKasten, MAX_BESCHRIFTUNGEN, [])
            .forEach(function (n) { raus[n] = true; });
        return raus;
    }

    function kantenReduzierer(k, anzeige, a) {
        var stark = !a.erwaehnt && a.gewicht > 1;
        var r = { color: a.widerspruch ? (_farben.widerspruch || _farben.stark) : (stark ? _farben.stark : _farben.schwach),
                  size: a.erwaehnt ? 0.5 : (a.widerspruch ? 2.5 : Math.min(4, 0.8 + 0.9 * a.gewicht)), label: '',
                  labelColor: _farben.text };
        var ende = G.extremities(k);
        if (_hover) {
            if (ende[0] !== _hover && ende[1] !== _hover) { r.visibility = 'hidden'; }
            else {
                r.color = _farben.stark;
                r.label = _hoverAuswahl.kanten[k] ? relevanzText(a) : '';
            }
        } else if (_hervor) {
            if (!_hervor.kanten[k]) { r.color = _farben.gedimmt; }
            else { r.color = _farben.akzent || _farben.stark; r.size = Math.max(r.size, 2); }
        }
        return r;
    }

    function rendererBauen() {
        var box = $('wg-graph');
        if (!box || !G) { return; }
        farbenLesen();          // Thema kann seit dem Start gewechselt haben
        if (R) { try { R.kill(); } catch (e) { } R = null; }
        try {
            R = new window.JarvisSigma.Sigma(G, box, {
                renderEdgeLabels: true,
                labelRenderedSizeThreshold: 7,
                labelDensity: 0.6,
                zIndex: true,
                nodeReducer: knotenReduzierer,
                edgeReducer: kantenReduzierer
            });
        } catch (e) {
            hinweis(t('wissensgraph.no_webgl', 'Die Grafik braucht WebGL 2 – dieser Browser stellt es nicht bereit. Auffälligkeiten, Prüfliste und Pflege darunter funktionieren trotzdem.'), 'err');
            R = null;
            return;
        }
        R.on('enterNode', function (e) {
            _hover = e.node; _hoverNachbarn = nachbarn(e.node);
            _hoverAuswahl = hoverAuswahl(e.node); R.refresh();
        });
        R.on('leaveNode', function () {
            _hover = null; _hoverNachbarn = {}; _hoverAuswahl = { knoten: {}, kanten: {} }; R.refresh();
        });
        R.on('clickNode', function (e) { detailOeffnen(e.node); });
        R.on('clickStage', function () {
            if (_hervor) { _hervor = null; R.refresh(); }
        });
    }

    function anordnen(dauer, danach) {
        if (!G || !G.order || !window.JarvisFA2) { if (danach) { danach(); } return; }
        if (_layout) { try { _layout.kill(); } catch (e) { } _layout = null; }
        var einst = window.JarvisFA2.forceAtlas2.inferSettings(G);
        einst.barnesHutOptimize = G.order > 500;
        try {
            _layout = new window.JarvisFA2.FA2Layout(G, { settings: einst, getEdgeWeight: 'gewicht' });
            _layout.start();
        } catch (e) {
            // Ohne Worker (z. B. gesperrt): synchron und knapp, statt gar nicht.
            try { window.JarvisFA2.forceAtlas2.assign(G, { iterations: 80, settings: einst }); } catch (e2) { }
            positionenSichern();
            if (danach) { danach(); }
            return;
        }
        setTimeout(function () {
            if (_layout) { try { _layout.stop(); _layout.kill(); } catch (e) { } _layout = null; }
            positionenSichern();
            if (danach) { danach(); }
        }, dauer);
    }

    function laden(anhaengen) {
        if (!bibliothekenDa()) {
            hinweis(t('wissensgraph.no_lib', 'Die Grafik-Bibliotheken wurden nicht geladen.'), 'err');
            return Promise.resolve();
        }
        var p = filterParameter();
        p.set('limit', String(SEITE));
        p.set('offset', String(anhaengen ? _offset : 0));
        hinweis(t('wissensgraph.loading', 'Lade …'), 'lade');
        return holeJson('/api/wissensgraph/graph?' + p.toString()).then(function (d) {
            if (!anhaengen) {
                _hervor = null; _hover = null;
                _hoverNachbarn = {}; _hoverAuswahl = { knoten: {}, kanten: {} };
            }
            graphFuellen(d, anhaengen);
            if (!G.order) {
                hinweis(_zugang.steuern
                    ? t('wissensgraph.empty', 'Für diese Auswahl gibt es noch keine Begriffe. Unter „Aufbau und Pflege" lässt sich der Graph aufbauen.')
                    : t('wissensgraph.empty_reader', 'Für diese Auswahl gibt es noch keine Begriffe.'));
            } else {
                hinweis('');
            }
            inselnBerechnen();
            legendeZeichnen();
            insightsZeichnen();
            ordnerFuellen(d.knoten || []);
            var neu = 0;
            G.forEachNode(function (n, a) { if (!a._gecacht) { neu++; } });
            // Zugeklappte Grafik: kein Renderer ohne Flaeche – er entsteht beim Aufklappen.
            if (!R && grafikMoeglich() && !grafikZu()) { rendererBauen(); }
            else if (R) { R.refresh(); }
            if (!grafikMoeglich()) {
                hinweis(t('wissensgraph.no_webgl', 'Die Grafik braucht WebGL 2 – dieser Browser stellt es nicht bereit. Auffälligkeiten, Prüfliste und Pflege darunter funktionieren trotzdem.'), 'err');
                return;
            }
            // Nur neu anordnen, wenn mehr als ein Zehntel ohne gemerkte Lage ist –
            // sonst springt der Graph bei jedem Nachladen (Positions-Cache).
            if (neu > G.order / 10) {
                anordnen(Math.min(8000, 1500 + G.order * 2), function () {
                    if (R) { R.refresh(); R.getCamera().reset({ duration: 300 }); }
                });
            }
        }).catch(function (e) {
            hinweis(t('wissensgraph.load_failed', 'Laden fehlgeschlagen: {grund}', { grund: e.message }), 'err');
        });
    }

    // ── Legende ─────────────────────────────────────────────────────────────

    function farbfleck(farbe) {
        var f = el('span', 'wg-fleck');
        f.style.background = farbe;          // Wert stammt aus theme.css (--graph-*)
        f.setAttribute('aria-hidden', 'true');
        return f;
    }

    function legendeZeichnen() {
        var box = $('wg-legende');
        if (!box) { return; }
        box.textContent = '';
        if (!G || !G.order) { return; }
        if (_modus === 'typ') {
            var zahl = {};
            G.forEachNode(function (n, a) { zahl[a.typ] = (zahl[a.typ] || 0) + 1; });
            TYPEN.filter(function (ty) { return zahl[ty]; }).forEach(function (ty) {
                var z = el('span', 'wg-leg');
                z.appendChild(farbfleck(farbeFuerTyp(ty)));
                z.appendChild(el('span', '', artName(ty) + ' · ' + zahl[ty]));
                box.appendChild(z);
            });
            return;
        }
        _inseln.slice(0, 12).forEach(function (ins) {
            var z = el('div', 'wg-leg wg-leg-insel');
            z.appendChild(farbfleck(_farben.palette[Math.min(ins.rang, 11)]));
            var text = el('span', '', t('wissensgraph.island_line', '{name} · {n} Begriffe · Zusammenhalt {k}',
                { name: G.getNodeAttribute(ins.wichtigster, 'label'), n: ins.mitglieder,
                  k: ins.kohaesion.toFixed(2).replace('.', ',') }));
            z.appendChild(text);
            if (ins.kohaesion < KOHAESION_WARNUNG && ins.mitglieder >= 3) {
                // Farbe allein ist keine Information – der Text sagt es.
                z.appendChild(el('span', 'wg-warn', t('wissensgraph.island_thin', 'dünn verbunden')));
            }
            z.addEventListener('click', function () { inselHervorheben(ins); });
            box.appendChild(z);
        });
        if (_inseln.length > 12) {
            box.appendChild(el('div', 'wg-leg', t('wissensgraph.island_more', 'und {n} kleinere Inseln (grau)',
                { n: _inseln.length - 12 })));
        }
    }

    function inselHervorheben(ins) {
        var k = {};
        G.forEachNode(function (n, a) { if (a.insel === ins.id) { k[n] = true; } });
        hervorheben(Object.keys(k), []);
    }

    // ── Hervorheben, Suche, Kamera ──────────────────────────────────────────

    function hervorheben(knoten, kanten) {
        var hk = {}, he = {};
        knoten.forEach(function (n) { if (G.hasNode(n)) { hk[n] = true; } });
        kanten.forEach(function (paar) {
            var e = G.hasNode(paar[0]) && G.hasNode(paar[1]) ? G.edge(paar[0], paar[1]) : null;
            if (e) { he[e] = true; hk[paar[0]] = true; hk[paar[1]] = true; }
        });
        _hervor = { knoten: hk, kanten: he, beschriftet: groessteKnoten(hk) };
        if (R) { R.refresh(); kameraZu(Object.keys(hk)); }
    }

    function kameraZu(liste) {
        if (!R || !liste.length) { return; }
        var xs = [], ys = [];
        liste.forEach(function (n) {
            var d = R.getNodeDisplayData(n);
            if (d) { xs.push(d.x); ys.push(d.y); }
        });
        if (!xs.length) { return; }
        var x = (Math.min.apply(null, xs) + Math.max.apply(null, xs)) / 2;
        var y = (Math.min.apply(null, ys) + Math.max.apply(null, ys)) / 2;
        var spanne = Math.max(Math.max.apply(null, xs) - Math.min.apply(null, xs),
                              Math.max.apply(null, ys) - Math.min.apply(null, ys));
        R.getCamera().animate({ x: x, y: y, ratio: Math.max(0.08, Math.min(1, spanne * 1.4)) },
                              { duration: 600 });
    }

    var _suchTimer = null;

    function suchen() {
        var q = norm($('wg-suche').value);
        if (!G) { return; }
        if (!q) { _hervor = null; if (R) { R.refresh(); } return; }
        var treffer = [];
        G.forEachNode(function (n, a) { if (norm(a.label).indexOf(q) >= 0) { treffer.push(n); } });
        if (treffer.length) {
            hervorheben(treffer, []);
            hinweis('');
            return;
        }
        // Nicht unter den geladenen: der Server sucht im ganzen Graphen und
        // liefert Treffer samt Nachbarn.
        if (G.order < _gefiltert) {
            var p = filterParameter();
            p.set('q', $('wg-suche').value.trim());
            p.set('limit', String(SEITE));
            hinweis(t('wissensgraph.loading', 'Lade …'), 'lade');
            holeJson('/api/wissensgraph/graph?' + p.toString()).then(function (d) {
                hinweis('');
                graphFuellen(d, true);
                inselnBerechnen(); legendeZeichnen(); insightsZeichnen();
                anordnen(1500, function () {
                    if (R) { R.refresh(); }
                    hervorheben(d.treffer || [], []);
                });
            }).catch(function (e) { hinweis(e.message, 'err'); });
        } else {
            hinweis(t('wissensgraph.search_none', 'Kein Begriff passt zu „{q}".', { q: $('wg-suche').value.trim() }));
        }
    }

    // ── Detail ──────────────────────────────────────────────────────────────

    function quelleOeffnen(pfad) {
        // Mit Kopfzeile holen und als Blob oeffnen – kein Sitzungstoken in einer
        // Adresse (Bauform support.js). Absolut fuer Einhaengepunkte.
        var p = pfad.indexOf('mnt/') === 0 ? '/' + pfad : pfad;
        hole('/api/knowledge/file_raw?path=' + encodeURIComponent(p)).then(function (r) {
            if (!r.ok) { throw new Error('HTTP ' + r.status); }
            return r.blob();
        }).then(function (b) {
            var u = URL.createObjectURL(b);
            window.open(u, '_blank', 'noopener');
            setTimeout(function () { URL.revokeObjectURL(u); }, 60000);
        }).catch(function (e) {
            hinweis(t('wissensgraph.open_failed', 'Die Datei ließ sich nicht öffnen: {grund}', { grund: e.message }), 'err');
        });
    }

    function kantenListe(titel, liste) {
        var box = el('div', 'wg-d-abschnitt');
        box.appendChild(el('h4', '', titel + ' (' + liste.length + ')'));
        var ul = el('ul', 'wg-d-liste');
        liste.slice(0, 40).forEach(function (e) {
            var li = el('li');
            var b = el('button', 'wg-link', e.name);
            b.type = 'button';
            b.addEventListener('click', function () { detailOeffnen(e.id); hervorheben([e.id], []); });
            li.appendChild(b);
            li.appendChild(el('span', 'wg-d-art', ' · ' + relevanzText({ arten: [e.art], gewicht: e.gewicht })));
            ul.appendChild(li);
        });
        if (liste.length > 40) { ul.appendChild(el('li', 'wg-d-art', t('wissensgraph.more_n', '… und {n} weitere', { n: liste.length - 40 }))); }
        box.appendChild(ul);
        return box;
    }

    function detailOeffnen(kid) {
        var box = $('wg-detail'), inhalt = $('wg-detail-inhalt');
        if (!box || !inhalt) { return; }
        box.classList.remove('hidden');
        ladeText(inhalt, t('wissensgraph.loading', 'Lade …'));
        holeJson('/api/wissensgraph/knoten/' + encodeURIComponent(kid)).then(function (d) {
            inhalt.textContent = '';
            inhalt.appendChild(el('h3', 'wg-d-name', d.name));
            inhalt.appendChild(el('div', 'wg-d-typ', artName(d.typ)));
            if (d.zusammenfassung) { inhalt.appendChild(el('p', 'wg-d-text', d.zusammenfassung)); }
            if (d.aliasse && d.aliasse.length) {
                inhalt.appendChild(el('p', 'wg-d-alias', t('wissensgraph.aliases', 'Auch geschrieben als: {liste}',
                    { liste: d.aliasse.join(', ') })));
            }
            var q = el('div', 'wg-d-abschnitt');
            q.appendChild(el('h4', '', t('wissensgraph.sources', 'Quellen') + ' (' + d.sources.length + ')'));
            var ul = el('ul', 'wg-d-liste');
            d.sources.slice(0, 30).forEach(function (s) {
                var li = el('li');
                var b = el('button', 'wg-link', s.split('/').pop());
                b.type = 'button';
                b.title = s;
                b.addEventListener('click', function () { quelleOeffnen(s); });
                li.appendChild(b);
                ul.appendChild(li);
            });
            q.appendChild(ul);
            inhalt.appendChild(q);
            if (d.ausgehend.length) { inhalt.appendChild(kantenListe(t('wissensgraph.out', 'Verweist auf'), d.ausgehend)); }
            if (d.eingehend.length) { inhalt.appendChild(kantenListe(t('wissensgraph.in', 'Wird genannt von'), d.eingehend)); }
            if (d.typ !== 'quelle') {
                var wiki = el('div', 'wg-d-abschnitt wg-wiki');
                inhalt.appendChild(wiki);
                wikiZeigen(d, wiki);
            }
            if (d.typ !== 'quelle' && _zugang.pflegen) {
                var weg = el('button', 'ja-btn wg-loeschen');
                weg.type = 'button';
                weg.innerHTML = window.JarvisIcons ? window.JarvisIcons.trash() : '';
                weg.appendChild(el('span', '', ' ' + t('wissensgraph.delete', 'Begriff entfernen')));
                weg.addEventListener('click', function () { knotenLoeschen(d); });
                inhalt.appendChild(weg);
            }
        }).catch(function (e) {
            inhalt.textContent = t('wissensgraph.load_failed', 'Laden fehlgeschlagen: {grund}', { grund: e.message });
        });
    }

    // ── Wiki-Seite im Detail ────────────────────────────────────────────────

    /** Markdown der Wiki-Seite als DOM (nie innerHTML – der Text stammt vom
     *  Modell und aus Dokumenten): ## → Zwischenueberschrift, - → Liste,
     *  [[Name]] → Knopf zum Begriff, **x** → fett. */
    function markdownZeichnen(md, ziel) {
        var ul = null, absatz = null;
        function inline(text, wohin) {
            var re = /\[\[([^\[\]|]+)\]\]|\*\*([^*]+)\*\*/g, pos = 0, m;
            while ((m = re.exec(text))) {
                if (m.index > pos) { wohin.appendChild(document.createTextNode(text.slice(pos, m.index))); }
                if (m[1]) {
                    var b = el('button', 'wg-link', m[1]);
                    b.type = 'button';
                    b.addEventListener('click', (function (n) { return function () { begriffZeigen(n); }; })(m[1]));
                    wohin.appendChild(b);
                } else {
                    wohin.appendChild(el('strong', '', m[2]));
                }
                pos = re.lastIndex;
            }
            if (pos < text.length) { wohin.appendChild(document.createTextNode(text.slice(pos))); }
        }
        String(md || '').split('\n').forEach(function (z) {
            var zeile = z.trim();
            if (!zeile) { ul = null; absatz = null; return; }
            var h = /^#{2,6}\s+(.*)$/.exec(zeile);
            if (h) { ul = null; absatz = null; ziel.appendChild(el('h5', 'wg-wiki-h', h[1])); return; }
            var li = /^[-*]\s+(.*)$/.exec(zeile);
            if (li) {
                absatz = null;
                if (!ul) { ul = el('ul', 'wg-wiki-liste'); ziel.appendChild(ul); }
                var e = el('li');
                inline(li[1], e);
                ul.appendChild(e);
                return;
            }
            ul = null;
            if (!absatz) { absatz = el('p', 'wg-wiki-text'); ziel.appendChild(absatz); }
            else { absatz.appendChild(document.createTextNode(' ')); }
            inline(zeile, absatz);
        });
    }

    /** Ein Verweis aus der Wiki-Seite: Begriff im geladenen Graphen suchen,
     *  sonst ueber die Suche (der Server kennt den ganzen Graphen). */
    function begriffZeigen(name) {
        var ziel = null, n = norm(name);
        if (G) { G.forEachNode(function (k, a) { if (!ziel && norm(a.label) === n) { ziel = k; } }); }
        if (ziel) { detailOeffnen(ziel); hervorheben([ziel], []); return; }
        $('wg-suche').value = name;
        suchen();
    }

    function wikiZeigen(d, box) {
        box.textContent = '';
        box.appendChild(el('h4', '', t('wissensgraph.wiki_h', 'Wiki-Seite')));
        var inhalt = el('div', 'wg-wiki-inhalt');
        ladeText(inhalt, t('wissensgraph.loading', 'Lade …'));
        box.appendChild(inhalt);
        var knopf = el('button', 'ja-btn wg-wiki-knopf');
        knopf.type = 'button';
        var meldungZeile = el('p', 'wg-meldung');
        function erzeugen() {
            knopf.disabled = true;
            ladeText(meldungZeile, t('wissensgraph.wiki_running', 'Wird erzeugt – das dauert einige Sekunden …'));
            meldungZeile.className = 'wg-meldung';
            sende('/api/wissensgraph/wiki/' + encodeURIComponent(d.id), 'POST').then(function () {
                wikiZeigen(d, box);
            }).catch(function (e) {
                knopf.disabled = false;
                meldungZeile.textContent = t('wissensgraph.wiki_failed', 'Nicht erzeugt: {grund}', { grund: e.message });
                meldungZeile.className = 'wg-meldung is-err';
            });
        }
        knopf.addEventListener('click', erzeugen);
        hole('/api/wissensgraph/wiki/' + encodeURIComponent(d.id)).then(function (r) {
            if (r.status === 404) { return null; }
            return r.json().catch(function () { return {}; }).then(function (j) {
                // 403: die Seite fasst auch Dokumente ausserhalb der eigenen
                // Wissensgruppen zusammen – Grund zeigen, kein Erzeugen anbieten.
                if (r.status === 403) { return { gesperrt: fehlertext(j, 'HTTP 403') }; }
                if (!r.ok) { throw new Error(fehlertext(j, 'HTTP ' + r.status)); }
                return j;
            });
        }).then(function (s) {
            inhalt.textContent = '';
            if (s && s.gesperrt) {
                inhalt.appendChild(el('p', 'ja-note', s.gesperrt));
                return;
            }
            if (!s) {
                inhalt.appendChild(el('p', 'ja-note', t('wissensgraph.wiki_none',
                    'Noch keine Wiki-Seite. Sie fasst zusammen, was die Quellen über diesen Begriff sagen.')));
                knopf.textContent = t('wissensgraph.wiki_create', 'Wiki-Seite erzeugen');
            } else {
                if (s.veraltet) {
                    inhalt.appendChild(el('p', 'wg-meldung', t('wissensgraph.wiki_stale',
                        'Veraltet – die Quellen haben sich seitdem geändert.')));
                }
                markdownZeichnen(s.markdown, inhalt);
                knopf.textContent = t('wissensgraph.wiki_renew', 'Neu erzeugen');
            }
            box.appendChild(knopf);
            box.appendChild(meldungZeile);
        }).catch(function (e) {
            inhalt.textContent = t('wissensgraph.load_failed', 'Laden fehlgeschlagen: {grund}', { grund: e.message });
        });
    }

    function knotenLoeschen(d) {
        if (!window.confirm(t('wissensgraph.delete_confirm',
            '„{name}" aus dem Graphen entfernen? Die Dokumente bleiben unverändert; der Begriff bleibt auch bei jedem Neuaufbau entfernt.',
            { name: d.name }))) { return; }
        sende('/api/wissensgraph/knoten/' + encodeURIComponent(d.id), 'DELETE').then(function () {
            $('wg-detail').classList.add('hidden');
            if (G && G.hasNode(d.id)) { G.dropNode(d.id); }
            inselnBerechnen(); legendeZeichnen(); insightsZeichnen();
            if (R) { R.refresh(); }
        }).catch(function (e) { hinweis(e.message, 'err'); });
    }

    // ── Auffaelligkeiten ────────────────────────────────────────────────────

    function istBegriff(n) { return G.getNodeAttribute(n, 'typ') !== 'quelle'; }

    /** Die Auffaelligkeiten als DATEN – getrennt vom Zeichnen, damit sie sich
     *  pruefen lassen. Nur Begriffe, keine Dokumentknoten. */
    function auffaelligkeiten() {
        var raus = { verbindungen: [], isoliert: [], duenn: [], bruecken: [] };
        if (!G || !G.order) { return raus; }
        var grade = [];
        G.forEachNode(function (n, a) { if (istBegriff(n)) { grade.push(a.grad); } });
        grade.sort(function (a, b) { return a - b; });
        var p90 = grade.length ? grade[Math.floor(grade.length * 0.9)] : 0;

        G.forEachEdge(function (k, a, von, nach, av, an) {
            if (a.erwaehnt || !istBegriff(von) || !istBegriff(nach)) { return; }
            if (av.insel === an.insel) { return; }
            var gruende = ['insel'];
            if (av.typ !== an.typ) { gruende.push('typ'); }
            var klein = Math.min(av.grad, an.grad), gross = Math.max(av.grad, an.grad);
            if (klein <= 2 && gross >= p90 && p90 > 2) { gruende.push('rand'); }
            if (gruende.length >= 2) {
                var typen = [av.typ, an.typ];
                raus.verbindungen.push({ schluessel: 'v:' + [von, nach].sort().join('|'), von: von, nach: nach,
                                         gruende: gruende, gewicht: a.gewicht, typen: typen,
                                         rang: (gruende.length + Math.min(9, a.gewicht) / 10)
                                               * rueckFaktor('v', [von, nach], typen) });
            }
        });
        raus.verbindungen.sort(function (x, y) {
            return (y.rang - x.rang) || (x.schluessel < y.schluessel ? -1 : 1);
        });
        raus.verbindungen = raus.verbindungen.slice(0, 6);

        G.forEachNode(function (n, a) {
            if (!istBegriff(n)) { return; }
            var begriffe = 0, inseln = {};
            G.forEachNeighbor(n, function (m, am) {
                if (am.typ !== 'quelle') { begriffe++; inseln[am.insel] = true; }
            });
            if (begriffe === 0) { raus.isoliert.push(n); }
            if (Object.keys(inseln).length >= 3) {
                var zahl = Object.keys(inseln).length;
                raus.bruecken.push({ knoten: n, inseln: zahl, rang: zahl * rueckFaktor('b', [n], [a.typ]) });
            }
        });
        raus.bruecken.sort(function (x, y) { return (y.rang - x.rang) || (x.knoten < y.knoten ? -1 : 1); });
        raus.bruecken = raus.bruecken.slice(0, 5);
        raus.duenn = _inseln.filter(function (ins) {
            return ins.mitglieder >= 5 && ins.kohaesion < KOHAESION_WARNUNG;
        }).map(function (ins) {
            return { ins: ins, rang: ins.mitglieder * rueckFaktor('d', [ins.wichtigster], []) };
        }).sort(function (x, y) { return y.rang - x.rang; }).slice(0, 5).map(function (x) { return x.ins; });
        raus.widersprueche = _widersprueche.map(function (b) {
            return { befund: b, rang: rueckFaktor('w', [b.kid, 'q:' + b.a, 'q:' + b.b], []) };
        }).sort(function (x, y) { return (y.rang - x.rang) || (x.befund.id < y.befund.id ? -1 : 1); })
          .slice(0, 6).map(function (x) { return x.befund; });
        return raus;
    }

    function ausgeblendet() { return _verworfen.map(function (x) { return x.schluessel; }); }

    /** Aehnlichkeit eines Vorschlags zu den verworfenen derselben Art: 1, wenn
     *  er einen Begriff mit einem verworfenen teilt; 0,5 bei gleichen Arten;
     *  sonst 0. Der verworfene selbst bleibt ohnehin ausgeblendet. */
    function aehnlichkeit(art, knoten, typen) {
        var best = 0;
        var tk = (typen || []).slice().sort().join('|');
        _verworfen.forEach(function (v) {
            if (v.art !== art) { return; }
            var teilt = (v.knoten || []).some(function (k) { return knoten.indexOf(k) >= 0; });
            if (teilt) { best = 1; return; }
            if (tk && (v.typen || []).slice().sort().join('|') === tk) { best = Math.max(best, 0.5); }
        });
        return best;
    }

    function rueckFaktor(art, knoten, typen) { return 1 - RUECK_GEWICHT * aehnlichkeit(art, knoten, typen); }

    function rueckmeldungLaden() {
        return holeJson('/api/wissensgraph/rueckmeldung').then(function (d) {
            _verworfen = d.verworfen || [];
        }).catch(function () { _verworfen = []; });
    }

    function widerspruecheLaden() {
        return holeJson('/api/wissensgraph/widersprueche').then(function (d) {
            _widersprueche = d.befunde || [];
        }).catch(function () { _widersprueche = []; });
    }

    function karte(schluessel, titel, text, knoten, kanten, auftrag, beschreibung) {
        var k = el('div', 'wg-karte');
        k.setAttribute('data-schluessel', schluessel);
        k.setAttribute('role', 'button');
        k.tabIndex = 0;
        var kopf = el('div', 'wg-karte-kopf');
        kopf.appendChild(el('strong', '', titel));
        var zu = el('button', 'wg-zu');
        zu.type = 'button';
        zu.title = t('wissensgraph.dismiss', 'Ausblenden');
        zu.setAttribute('aria-label', zu.title);
        zu.innerHTML = window.JarvisIcons ? window.JarvisIcons.close() : '×';
        zu.addEventListener('click', function (ev) {
            ev.stopPropagation();
            var b = beschreibung || {};
            zu.disabled = true;
            sende('/api/wissensgraph/rueckmeldung', 'POST', {
                schluessel: schluessel, art: schluessel.charAt(0),
                knoten: (b.knoten || []).slice(0, 50), typen: (b.typen || []).slice(0, 10)
            }).then(function (d) {
                _verworfen = d.verworfen || [];
                insightsZeichnen();
            }).catch(function (e) { zu.disabled = false; hinweis(e.message, 'err'); });
        });
        kopf.appendChild(zu);
        k.appendChild(kopf);
        k.appendChild(el('div', 'wg-karte-text', text));
        if (auftrag) {
            var r = el('button', 'ja-btn wg-recherche', t('wissensgraph.research', 'Recherche starten'));
            r.type = 'button';
            r.addEventListener('click', function (ev) { ev.stopPropagation(); rechercheStarten(auftrag); });
            k.appendChild(r);
        }
        function zeigen() { hervorheben(knoten, kanten); }
        k.addEventListener('click', zeigen);
        k.addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter' || ev.key === ' ') { ev.preventDefault(); zeigen(); }
        });
        return k;
    }

    function name(n) { return G.getNodeAttribute(n, 'label'); }

    function insightsZeichnen() {
        var box = $('wg-insights');
        if (!box) { return; }
        box.textContent = '';
        var a = auffaelligkeiten();
        var weg = ausgeblendet();
        var karten = [];
        a.verbindungen.forEach(function (v) {
            var gruende = v.gruende.map(function (g) { return t('wissensgraph.why_' + g, g); }).join(', ');
            karten.push(karte(v.schluessel, name(v.von) + ' ↔ ' + name(v.nach),
                t('wissensgraph.surprise_text', 'Überraschende Verbindung: {gruende}.', { gruende: gruende }),
                [], [[v.von, v.nach]], null, { knoten: [v.von, v.nach], typen: v.typen }));
        });
        a.widersprueche.forEach(function (b) {
            karten.push(karte('w:' + b.id, t('wissensgraph.contra_title', 'Widerspruch: {name}', { name: b.name }),
                (b.frage ? b.frage + ' ' : '')
                    + t('wissensgraph.contra_text', '„{a}": {aa} – „{b}": {ab}', { a: b.name_a, aa: b.aussage_a, b: b.name_b, ab: b.aussage_b })
                    + (b.erklaerung ? ' (' + b.erklaerung + ')' : ''),
                [b.kid, 'q:' + b.a, 'q:' + b.b], [['q:' + b.a, 'q:' + b.b]],
                t('wissensgraph.contra_task', 'Prüfe im Wissen, welche Aussage zu „{name}" gilt: „{a}" sagt: {aa}; „{b}" sagt: {ab}. Nenne die Quellen und welche Aussage aktueller ist.',
                  { name: b.name, a: b.name_a, aa: b.aussage_a, b: b.name_b, ab: b.aussage_b }),
                { knoten: [b.kid, 'q:' + b.a, 'q:' + b.b], typen: [] }));
        });
        a.bruecken.forEach(function (b) {
            karten.push(karte('b:' + b.knoten, name(b.knoten),
                t('wissensgraph.bridge_text', 'Verbindet {n} Themen-Inseln – ein Schlüsselbegriff zwischen sonst getrennten Bereichen.',
                  { n: b.inseln }), [b.knoten], [], null, { knoten: [b.knoten], typen: [G.getNodeAttribute(b.knoten, 'typ')] }));
        });
        a.duenn.forEach(function (ins) {
            var wichtig = name(ins.wichtigster);
            var mitglieder = [];
            G.forEachNode(function (n, at) { if (at.insel === ins.id) { mitglieder.push(n); } });
            karten.push(karte('d:' + wichtig, t('wissensgraph.thin_title', 'Dünnes Thema: {name}', { name: wichtig }),
                t('wissensgraph.thin_text', '{n} Begriffe, aber kaum untereinander verbunden (Zusammenhalt {k}).',
                  { n: ins.mitglieder, k: ins.kohaesion.toFixed(2).replace('.', ',') }),
                mitglieder, [],
                t('wissensgraph.thin_task', 'Recherchiere im Wissen, wie die Begriffe rund um „{name}" zusammenhängen, und fasse die Zusammenhänge zusammen.', { name: wichtig }),
                { knoten: [ins.wichtigster], typen: [] }));
        });
        if (a.isoliert.length) {
            var beispiele = a.isoliert.slice(0, 5).map(name);
            karten.push(karte('i:' + a.isoliert.length, t('wissensgraph.isolated_title', '{n} Begriffe ohne Verbindung', { n: a.isoliert.length }),
                t('wissensgraph.isolated_text', 'Sie kommen vor, stehen aber mit keinem anderen Begriff in Beziehung, z. B. {liste}.',
                  { liste: beispiele.join(', ') }),
                a.isoliert, [],
                t('wissensgraph.isolated_task', 'Recherchiere im Wissen, in welchem Zusammenhang diese Begriffe stehen: {liste}.', { liste: beispiele.join(', ') }),
                { knoten: a.isoliert.slice(0, 50), typen: [] }));
        }
        var gezeigt = 0, versteckt = 0;
        // EINE Stelle entscheidet ueber das Ausblenden – ueber dasselbe Attribut,
        // das der Schliessen-Knopf in die Liste schreibt.
        karten.forEach(function (k) {
            if (weg.indexOf(k.getAttribute('data-schluessel')) >= 0) { versteckt++; return; }
            box.appendChild(k);
            gezeigt++;
        });
        if (!gezeigt) {
            box.appendChild(el('p', 'ja-note', G && G.order
                ? t('wissensgraph.insights_none', 'Keine Auffälligkeiten in dieser Auswahl.')
                : t('wissensgraph.insights_empty', 'Noch kein Graph geladen.')));
        }
        var zurueck = $('wg-insights-zurueck');
        if (zurueck) { zurueck.classList.toggle('hidden', !versteckt); }
    }

    function rechercheStarten(auftrag) {
        // Uebergabe an /chat: das Eingabefeld wird VORBELEGT, nicht abgeschickt –
        // der Administrator sieht den Auftrag und entscheidet (chat_vorlage.js).
        speicherSchreiben(VORLAGE_SPEICHER, { text: auftrag, zeit: Date.now() });
        window.open('/chat', '_blank');
    }

    // ── Pflege: Status, Aufbau, Pruefliste ─────────────────────────────────

    function statusZeichnen(st) {
        var box = $('wg-status');
        if (!box) { return; }
        box.textContent = '';
        var g = st.graph || {}, z = st.zaehler || {};
        var arbeitet = arbeitetGerade(st);
        // Dritter Eintrag: die Zeile bekommt den drehenden Kreis.
        var zeilen = [
            [t('wissensgraph.st_state', 'Zustand'), st.aktiv
                ? (arbeitet ? t('wissensgraph.st_running', 'an – arbeitet') : t('wissensgraph.st_idle', 'an – wartet'))
                : t('wissensgraph.st_off', 'aus'), arbeitet],
            [t('wissensgraph.st_queue', 'Warteschlange'), String(st.warteschlange || 0)],
            [t('wissensgraph.st_done', 'Seit Start erledigt / fehlgeschlagen'), (st.erledigt || 0) + ' / ' + (st.fehler || 0)],
            [t('wissensgraph.st_calls', 'Modellaufrufe · Token ein/aus'),
             (z.aufrufe || 0) + ' · ' + (z.token_ein || 0) + ' / ' + (z.token_aus || 0)],
            [t('wissensgraph.st_calls_care', 'Widersprüche und Wiki · Modellaufrufe · Token ein/aus'),
             (z.pflege_aufrufe || 0) + ' · ' + (z.pflege_token_ein || 0) + ' / ' + (z.pflege_token_aus || 0)],
            [t('wissensgraph.st_graph', 'Graph'), t('wissensgraph.st_graph_v', '{q} Dokumente · {e} Begriffe · {k} Verbindungen',
                { q: g.quellen || 0, e: g.entitaeten || 0, k: g.kanten || 0 })],
            [t('wissensgraph.st_contra', 'Widersprüche'), t('wissensgraph.st_contra_v', '{n} gefunden · {o} Begriffe offen',
                { n: g.widersprueche || 0, o: (st.nachlauf || {}).widersprueche_offen || 0 })],
            [t('wissensgraph.st_wiki', 'Wiki-Seiten'), t('wissensgraph.st_wiki_v', '{n} vorhanden · {o} offen',
                { n: (st.nachlauf || {}).wiki_seiten || 0, o: (st.nachlauf || {}).wiki_offen || 0 })],
            [t('wissensgraph.st_model', 'Modell'), st.modell || '–']
        ];
        var dl = el('dl', 'wg-st');
        zeilen.forEach(function (p) {
            dl.appendChild(el('dt', '', p[0]));
            var dd = el('dd', '');
            if (p[2]) { ladeText(dd, p[1]); } else { dd.textContent = p[1]; }
            dl.appendChild(dd);
        });
        box.appendChild(dl);
        if (st.aktuell) { box.appendChild(el('p', 'ja-note', t('wissensgraph.st_current', 'Gerade: {pfad}', { pfad: aktuellText(st.aktuell) }))); }
        if ((st.nachlauf || {}).pause) {
            box.appendChild(el('p', 'ja-note', t('wissensgraph.st_paused',
                'Widerspruchsprüfung und Wiki-Seiten sind angehalten – sie laufen mit dem nächsten Aufbau weiter.')));
        }
        einstellungenZeichnen(st.einstellungen || {});
        var f = st.letzte_fehler || [];
        if (f.length) {
            box.appendChild(el('h4', '', t('wissensgraph.st_errors', 'Letzte Fehler')));
            var ul = el('ul', 'wg-fehler');
            f.slice(-5).reverse().forEach(function (x) { ul.appendChild(el('li', '', (x.pfad ? x.pfad + ': ' : '') + x.grund)); });
            box.appendChild(ul);
        }
        var start = $('wg-start');
        if (start) {
            start.disabled = !st.aktiv;
            start.title = st.aktiv ? '' : t('wissensgraph.st_off_hint', 'Der Wissensgraph ist ausgeschaltet.');
        }
    }

    /** Arbeitet der Dienst gerade? ⚠ ``laeuft`` gilt nur fuer die Dokument-
     *  Warteschlange – im Nachlauf (Widersprueche, Wiki-Seiten) steht es auf
     *  false, waehrend ``aktuell`` den bearbeiteten Begriff nennt. Nur ``laeuft``
     *  zu lesen zeigte die ganze Nacht "an – wartet" (gemeldet 2026-10-31). */
    function arbeitetGerade(st) {
        return !!(st && st.aktiv && (st.laeuft || st.aktuell));
    }

    function statusHolen() {
        if (!_zugang.steuern) { return Promise.resolve(null); }
        var sb = $('wg-status');
        if (sb && !sb.childNodes.length) { ladeText(sb, t('wissensgraph.loading', 'Lade …')); }
        return holeJson('/api/wissensgraph/status').then(function (st) {
            statusZeichnen(st);
            clearTimeout(_statusTimer);
            var n = st.nachlauf || {};
            var nachlauf = st.aktiv && !n.pause && ((n.widersprueche_offen || 0) + (n.wiki_offen || 0)) > 0;
            if (arbeitetGerade(st) || st.warteschlange || nachlauf) { _statusTimer = setTimeout(statusHolen, 10000); }
            return st;
        }).catch(function (e) {
            var b = $('wg-status');
            if (b) { b.textContent = t('wissensgraph.load_failed', 'Laden fehlgeschlagen: {grund}', { grund: e.message }); }
        });
    }

    /** "widerspruch:e:sap" → lesbarer Text; ein Dateipfad bleibt, wie er ist. */
    function aktuellText(a) {
        var m = /^(widerspruch|wiki):(.*)$/.exec(a || '');
        if (!m) { return a; }
        var kid = m[2], nm = G && G.hasNode(kid) ? G.getNodeAttribute(kid, 'label') : kid.replace(/^e:/, '');
        return m[1] === 'wiki' ? t('wissensgraph.st_cur_wiki', 'Wiki-Seite zu „{name}"', { name: nm })
                               : t('wissensgraph.st_cur_contra', 'Widerspruchsprüfung zu „{name}"', { name: nm });
    }

    // ── Einstellungen (Schalter) ────────────────────────────────────────────

    function einstellungenZeichnen(e) {
        document.querySelectorAll('[data-wg-einstellung]').forEach(function (h) {
            var k = h.getAttribute('data-wg-einstellung');
            if (typeof e[k] === 'boolean' && !h.disabled) { h.checked = e[k]; }
        });
    }

    function einstellungSchreiben(h) {
        var k = h.getAttribute('data-wg-einstellung'), rumpf = {};
        rumpf[k] = h.checked;
        h.disabled = true;
        meldung('wg-einst-meldung', '');
        sende('/api/wissensgraph/einstellungen', 'POST', rumpf).then(function () {
            meldung('wg-einst-meldung', t('wissensgraph.settings_saved', 'Gespeichert.'), 'ok');
        }).catch(function (e) {
            meldung('wg-einst-meldung', e.message, 'err');
        // Der Status danach setzt JEDEN Schalter auf den Stand des Servers –
        // auch einen abgelehnten zurueck.
        }).then(function () { h.disabled = false; statusHolen(); });
    }

    // ── Export ──────────────────────────────────────────────────────────────

    function exportieren() {
        var b = $('wg-export');
        b.disabled = true;
        meldung('wg-export-meldung', '');
        ladeText($('wg-export-meldung'), t('wissensgraph.export_running', 'Wird zusammengestellt …'));
        // Mit Kopfzeile holen und als Blob speichern – kein Sitzungstoken in
        // einer Adresse (wie quelleOeffnen).
        hole('/api/wissensgraph/export').then(function (r) {
            if (!r.ok) { throw new Error('HTTP ' + r.status); }
            var cd = r.headers.get('Content-Disposition') || '';
            var m = /filename="([^"]+)"/.exec(cd);
            return r.blob().then(function (blob) { return { blob: blob, name: m ? m[1] : 'wissensgraph.zip' }; });
        }).then(function (x) {
            var u = URL.createObjectURL(x.blob);
            var a = el('a');
            a.href = u;
            a.download = x.name;
            document.body.appendChild(a);
            a.click();
            a.remove();
            setTimeout(function () { URL.revokeObjectURL(u); }, 60000);
            meldung('wg-export-meldung', t('wissensgraph.export_ok', 'Heruntergeladen: {name}', { name: x.name }), 'ok');
        }).catch(function (e) {
            meldung('wg-export-meldung', e.message, 'err');
        }).then(function () { b.disabled = false; });
    }

    function meldung(id, text, art) {
        var m = $(id);
        if (!m) { return; }
        if (art === 'lade') { ladeText(m, text); } else { m.textContent = text || ''; }
        m.className = 'wg-meldung' + (art === 'err' ? ' is-err' : art === 'ok' ? ' is-ok' : '');
    }

    function aufbauStarten() {
        var umfang = $('wg-umfang').value;
        var rumpf = { umfang: umfang, voll: $('wg-voll').checked };
        if (umfang === 'gruppe') { rumpf.groups = [$('wg-umfang-gruppe').value]; }
        if (umfang === 'ordner') { rumpf.ordner = $('wg-umfang-ordner').value.trim(); }
        $('wg-start').disabled = true;
        meldung('wg-aufbau-meldung', t('wissensgraph.rebuild_running', 'Wird eingereiht …'), 'lade');
        sende('/api/wissensgraph/neuaufbau', 'POST', rumpf).then(function (d) {
            meldung('wg-aufbau-meldung', t('wissensgraph.rebuild_ok',
                '{n} Dokumente eingereiht, {u} unverändert, {b} bereinigt. Der Aufbau läuft im Hintergrund.',
                { n: d.eingereiht || 0, u: d.unveraendert || 0, b: d.bereinigt || 0 }), 'ok');
            statusHolen();
        }).catch(function (e) {
            meldung('wg-aufbau-meldung', e.message, 'err');
        }).then(function () { $('wg-start').disabled = false; });
    }

    function aufbauAbbrechen() {
        sende('/api/wissensgraph/abbrechen', 'POST').then(function (d) {
            meldung('wg-aufbau-meldung', t('wissensgraph.cancel_ok', 'Abgebrochen – {n} Einträge aus der Warteschlange genommen.',
                { n: d.verworfen || 0 }), 'ok');
            statusHolen();
        }).catch(function (e) { meldung('wg-aufbau-meldung', e.message, 'err'); });
    }

    var _pruefTimer = null;
    var PRUEF_NACHFRAGE_MS = 4000;

    /** Der Server antwortet SOFORT mit dem gemerkten Stand und rechnet im
     *  Hintergrund (bei vielen Begriffen dauert der Vergleich eine Weile –
     *  auf DEV 19 s bei 7.500). Solange ``laeuft``, fragt die Seite nach und
     *  zeigt den drehenden Kreis; ein veralteter Stand steht derweil schon da. */
    function prueflisteLaden(nachfrage) {
        var box = $('wg-pruefliste'), knopf = $('wg-pruef-laden');
        clearTimeout(_pruefTimer);
        if (!nachfrage) {
            ladeText(box, t('wissensgraph.loading', 'Lade …'));
            if (knopf) { knopf.disabled = true; }
        }
        holeJson('/api/wissensgraph/pruefliste?limit=40').then(function (d) {
            box.textContent = '';
            var paare = d.paare || [];
            if (d.laeuft) {
                var zeile = el('p', 'ja-note wg-pruef-laeuft');
                ladeText(zeile, paare.length
                    ? t('wissensgraph.review_updating', 'Stand von {zeit} – wird gerade aktualisiert …',
                        { zeit: new Date((d.zeit || 0) * 1000).toLocaleTimeString() })
                    : t('wissensgraph.review_running', 'Ähnliche Begriffe werden verglichen – bei vielen Begriffen dauert das eine Weile …'));
                box.appendChild(zeile);
                _pruefTimer = setTimeout(function () { prueflisteLaden(true); }, PRUEF_NACHFRAGE_MS);
            } else if (knopf) {
                knopf.disabled = false;
            }
            if (d.fehler) {
                box.appendChild(el('p', 'wg-meldung is-err', t('wissensgraph.load_failed', 'Laden fehlgeschlagen: {grund}', { grund: d.fehler })));
            }
            if (!paare.length) {
                if (!d.laeuft) { box.appendChild(el('p', 'ja-note', t('wissensgraph.review_none', 'Nichts zu prüfen.'))); }
                return;
            }
            paare.forEach(function (p) {
                var z = el('div', 'wg-paar');
                var text = el('div', 'wg-paar-text');
                text.appendChild(el('strong', '', p.quelle.name));
                text.appendChild(el('span', 'wg-paar-meta', ' (' + artName(p.quelle.typ) + ', ' + p.quelle.quellen + ')'));
                text.appendChild(el('span', '', '  ~  '));
                text.appendChild(el('strong', '', p.ziel.name));
                text.appendChild(el('span', 'wg-paar-meta', ' (' + artName(p.ziel.typ) + ', ' + p.ziel.quellen + ') · '
                    + t('wissensgraph.similarity', 'Ähnlichkeit {s}', { s: String(p.aehnlichkeit).replace('.', ',') })));
                z.appendChild(text);
                var ja = el('button', 'ja-btn', t('wissensgraph.merge', 'Gleich – zusammenführen'));
                ja.type = 'button';
                ja.title = t('wissensgraph.merge_title', '„{a}" geht in „{b}" auf', { a: p.quelle.name, b: p.ziel.name });
                var nein = el('button', 'ja-btn', t('wissensgraph.split', 'Verschieden'));
                nein.type = 'button';
                // Der Kreis steht im geklickten Knopf – Zusammenfuehren schreibt
                // den Graphen um und dauert bei grossen Begriffen spuerbar.
                function erledigt(knopf, promise) {
                    var text = knopf.textContent;
                    ja.disabled = nein.disabled = true;
                    ladeText(knopf, text);
                    promise.then(function () { z.remove(); laden(false); })
                           .catch(function (e) {
                               knopf.textContent = text;
                               ja.disabled = nein.disabled = false;
                               hinweis(e.message, 'err');
                           });
                }
                ja.addEventListener('click', function () {
                    erledigt(ja, sende('/api/wissensgraph/zusammenfuehren', 'POST', { quelle: p.quelle.id, ziel: p.ziel.id }));
                });
                nein.addEventListener('click', function () {
                    erledigt(nein, sende('/api/wissensgraph/trennen', 'POST', { a: p.quelle.id, b: p.ziel.id }));
                });
                var k = el('div', 'wg-paar-knoepfe');
                k.appendChild(ja); k.appendChild(nein);
                z.appendChild(k);
                box.appendChild(z);
            });
        }).catch(function (e) {
            if (knopf) { knopf.disabled = false; }
            box.textContent = t('wissensgraph.load_failed', 'Laden fehlgeschlagen: {grund}', { grund: e.message });
        });
    }

    // ── Auswahllisten ───────────────────────────────────────────────────────

    function optionenSetzen(id, gruppen) {
        var s = $(id);
        if (!s) { return; }
        gruppen.forEach(function (g) {
            var o = el('option', '', g.name || g.id);
            o.value = g.id;
            s.appendChild(o);
        });
    }

    function gruppenFuellen() {
        // Der Filter ueber der Grafik bietet NUR die Gruppen an, die der
        // Betrachter sehen darf – sie kommen mit seinen Rechten vom Server.
        optionenSetzen('wg-gruppe', _zugang.gruppen || []);
        if (!_zugang.steuern) { return Promise.resolve(); }
        return holeJson('/api/knowledge/groups').then(function (d) {
            _gruppen = (d.groups || []).filter(function (g) { return g && g.id && g.id !== 'ungrouped'; });
            optionenSetzen('wg-umfang-gruppe', _gruppen);
        }).catch(function () { /* ohne Gruppenliste bleibt "Eingestellter Umfang" */ });
    }

    /** Bereiche nach Recht ein-/ausblenden. Die Schranke sitzt am Server –
     *  hier geht es nur darum, keine Knoepfe zu zeigen, die in ein 403 fuehren. */
    function bereicheSetzen() {
        var lesen = _zugang.stufe !== 'keine';
        ['wg-karte-graph', 'wg-karte-insights'].forEach(function (id) {
            var e = $(id);
            if (e) { e.classList.toggle('hidden', !lesen); }
        });
        var bloecke = { 'wg-block-steuerung': _zugang.steuern, 'wg-block-pruefliste': _zugang.pflegen,
                        'wg-block-export': _zugang.pflegen };
        Object.keys(bloecke).forEach(function (id) {
            var e = $(id);
            if (e) { e.classList.toggle('hidden', !bloecke[id]); }
        });
        var pf = $('wg-karte-pflege');
        if (pf) { pf.classList.toggle('hidden', !_zugang.steuern && !_zugang.pflegen); }
        var h = $('wg-umfang-hinweis');
        if (h) {
            var teil = _zugang.stufe === 'gruppen';
            h.classList.toggle('hidden', !teil);
            h.textContent = teil ? t('wissensgraph.scope_reader',
                'Du siehst die Begriffe aus deinen Wissensgruppen: {liste}. Was nur in anderen Gruppen vorkommt, erscheint hier nicht.',
                { liste: (_zugang.gruppen || []).map(function (g) { return g.name || g.id; }).join(', ') }) : '';
        }
    }

    var _ordnerBekannt = {};

    function ordnerFuellen(knoten) {
        var s = $('wg-ordner');
        if (!s) { return; }
        knoten.forEach(function (k) {
            (k.sources || []).forEach(function (q) {
                var teile = q.split('/');
                if (teile.length < 4) { return; }
                var o = teile.slice(0, 3).join('/');
                if (_ordnerBekannt[o]) { return; }
                _ordnerBekannt[o] = true;
                var opt = el('option', '', o.replace(/^data\/rag\//, '').replace(/^mnt\/rag\//, '/mnt/rag/'));
                opt.value = o;
                s.appendChild(opt);
            });
        });
    }

    // ── Bedienung ───────────────────────────────────────────────────────────

    function faerbungSetzen(modus) {
        _modus = modus;
        var b = $('wg-faerbung');
        if (b) {
            // Die Beschriftung wechselt mit dem Zustand (Register).
            b.textContent = modus === 'insel' ? t('wissensgraph.color_island', 'Färbung: nach Themen-Inseln')
                                              : t('wissensgraph.color_type', 'Färbung: nach Art');
            b.setAttribute('aria-pressed', modus === 'insel' ? 'true' : 'false');
        }
        legendeZeichnen();
        if (R) { R.refresh(); }
    }

    function binden() {
        $('wg-faerbung').addEventListener('click', function () { faerbungSetzen(_modus === 'typ' ? 'insel' : 'typ'); });
        $('wg-zoom-plus').addEventListener('click', function () { if (R) { R.getCamera().zoomIn({ duration: 250 }); } });
        $('wg-zoom-minus').addEventListener('click', function () { if (R) { R.getCamera().zoomOut({ duration: 250 }); } });
        $('wg-einpassen').addEventListener('click', function () { if (R) { R.getCamera().reset({ duration: 300 }); } });
        $('wg-anordnen').addEventListener('click', function () {
            anordnen(Math.min(8000, 1500 + (G ? G.order : 0) * 2), function () {
                if (R) { R.refresh(); R.getCamera().reset({ duration: 300 }); }
            });
        });
        $('wg-mehr').addEventListener('click', function () { laden(true); });
        ['wg-typ', 'wg-gruppe', 'wg-ordner', 'wg-dokumente'].forEach(function (id) {
            $(id).addEventListener('change', function () { laden(false); });
        });
        $('wg-suche').addEventListener('input', function () {
            clearTimeout(_suchTimer);
            _suchTimer = setTimeout(suchen, 300);
        });
        $('wg-suche').addEventListener('keydown', function (ev) {
            if (ev.key === 'Escape') { $('wg-suche').value = ''; suchen(); }
        });
        $('wg-detail-zu').addEventListener('click', function () { $('wg-detail').classList.add('hidden'); });
        if (window.JarvisIcons) { window.JarvisIcons.setClose($('wg-detail-zu')); }
        $('wg-insights-zurueck').addEventListener('click', function () {
            sende('/api/wissensgraph/rueckmeldung', 'DELETE').then(function () {
                _verworfen = [];
                insightsZeichnen();
            }).catch(function (e) { hinweis(e.message, 'err'); });
        });
        $('wg-export').addEventListener('click', exportieren);
        document.querySelectorAll('[data-wg-einstellung]').forEach(function (h) {
            h.addEventListener('change', function () { einstellungSchreiben(h); });
        });
        $('wg-umfang').addEventListener('change', function () {
            var u = $('wg-umfang').value;
            $('wg-umfang-gruppe').classList.toggle('hidden', u !== 'gruppe');
            $('wg-umfang-ordner').classList.toggle('hidden', u !== 'ordner');
        });
        $('wg-start').addEventListener('click', aufbauStarten);
        $('wg-abbrechen').addEventListener('click', aufbauAbbrechen);
        $('wg-pruef-laden').addEventListener('click', function () { prueflisteLaden(false); });
        $('wg-portal-btn').addEventListener('click', function () { location.href = '/portal'; });
        $('wg-logout-btn').addEventListener('click', function () {
            try {
                fetch('/api/logout', { method: 'POST', keepalive: true,
                                       headers: { 'Authorization': 'Bearer ' + tok() } });
            } catch (e) { /* Abmelden darf am Signal nicht scheitern */ }
            try { localStorage.removeItem('jarvis_token'); } catch (e) { }
            location.replace('/');
        });
        // Sprachwechsel: selbst gezeichnete Texte neu setzen. ⚠ i18n.js feuert
        // das Ereignis auf WINDOW (themechange dagegen auf document).
        window.addEventListener('jarvis-lang-changed', function () {
            bereicheSetzen();
            faerbungSetzen(_modus);
            insightsZeichnen();
            zaehlerZeichnen();
        });
        klappInit();
        window.addEventListener('jarvis-breit', function () { if (R) { R.resize(); R.refresh(); } });
    }

    // ── Aufklappbare Container (Bauform /feedback, /ai-mouse) ───────────────
    // Gespeichert werden die ZUGEKLAPPTEN: die Vorgabe fuer einen neuen Benutzer
    // ist "alles offen", und ein spaeter ergaenzter Container ist von selbst
    // offen statt still versteckt. Gemeldet 2026-10-31: der Zustand wurde hier
    // nicht gemerkt, anders als auf den uebrigen Seiten.
    var KLAPP_SPEICHER = 'jarvis_wissensgraph_zu';

    function klappZustand() {
        try {
            var roh = JSON.parse(localStorage.getItem(KLAPP_SPEICHER) || '[]');
            return Array.isArray(roh) ? roh.filter(function (x) { return typeof x === 'string'; }) : [];
        } catch (e) {
            // Ein kaputter Speicherstand darf nicht dazu fuehren, dass nichts aufklappt.
            return [];
        }
    }

    function grafikZu() {
        var k = document.querySelector('.ja-card[data-klapp="graph"]');
        return !!k && k.classList.contains('is-zu');
    }

    /** Einen Container auf- oder zuklappen und den Zustand merken – DIE EINE
     *  Stelle dafuer. ⚠ Die Grafik: in einem zugeklappten Container hat sigma
     *  keine Flaeche und bricht beim Aufbau ab – deshalb entsteht der Renderer
     *  erst beim ersten Aufklappen (rendererBauen), danach genuegt resize. */
    function klappSetzen(karte, zu) {
        var kopf = karte.querySelector('.ja-card-head');
        var id = karte.getAttribute('data-klapp');
        karte.classList.toggle('is-zu', !!zu);
        if (kopf) { kopf.setAttribute('aria-expanded', zu ? 'false' : 'true'); }
        if (!zu && id === 'graph') {
            if (R) { R.resize(); R.refresh(); }
            else if (G && G.order && grafikMoeglich()) { rendererBauen(); }
        }
        var liste = klappZustand().filter(function (x) { return x !== id; });
        if (zu) { liste.push(id); }
        speicherSchreiben(KLAPP_SPEICHER, liste);
    }

    function klappInit() {
        var zu = klappZustand();
        document.querySelectorAll('.ja-card[data-klapp]').forEach(function (karte) {
            var kopf = karte.querySelector('.ja-card-head');
            if (!kopf) { return; }
            var istZu = zu.indexOf(karte.getAttribute('data-klapp')) >= 0;
            karte.classList.toggle('is-zu', istZu);
            kopf.setAttribute('aria-expanded', istZu ? 'false' : 'true');
            function um() { klappSetzen(karte, !karte.classList.contains('is-zu')); }
            kopf.addEventListener('click', function (ev) {
                // ⚠ OHNE DIESE AUSNAHME klappt jeder Knopf in der Kopfzeile den Container zu.
                if (ev.target.closest('button, input, label, a, select, textarea')) { return; }
                um();
            });
            kopf.addEventListener('keydown', function (ev) {
                if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') { ev.preventDefault(); um(); }
            });
        });
    }

    // Themenwechsel: Farben neu lesen, sonst bliebe die Grafik im alten Thema.
    // ⚠ SOFORT angemeldet, nicht erst nach /api/me: theme.js stellt das
    // gespeicherte Thema beim Laden um, und ein spaeter Listener verpasste das
    // – die Beschriftungen standen dann dunkel auf dunklem Grund (live gesehen).
    document.addEventListener('jarvis:themechange', function () {
        if (!_farben) { return; }
        farbenLesen();
        if (R) { R.refresh(); }      // die Reduzierer lesen _farben bei jedem Zeichnen
        legendeZeichnen();
    });

    function start() {
        var app = $('wg-app');
        if (!tok()) { location.replace('/'); return; }
        holeJson('/api/wissensgraph/zugang').then(function (z) {
            _zugang = z || _zugang;
            if (_zugang.stufe === 'keine' && !_zugang.steuern) { location.replace('/portal'); return; }
            if (app) { app.classList.remove('hidden'); }
            farbenLesen();
            binden();
            bereicheSetzen();
            faerbungSetzen('typ');
            statusHolen();
            try { localStorage.removeItem(WEG_SPEICHER_ALT); } catch (e) { /* privater Modus */ }
            if (_zugang.stufe === 'keine') { gruppenFuellen(); return; }
            Promise.all([gruppenFuellen(), rueckmeldungLaden(), widerspruecheLaden()])
                .then(function () { laden(false); });
        }).catch(function () { location.replace('/'); });
    }

    // Fuer die Waechter: reine Funktionen ohne DOM-Seiteneffekte.
    window.WissensgraphIntern = {
        norm: norm, knotenGroesse: knotenGroesse, relevanzText: relevanzText,
        auffaelligkeiten: auffaelligkeiten, webgl2: webgl2, grafikMoeglich: grafikMoeglich,
        arbeitetGerade: arbeitetGerade, statusHolen: statusHolen,
        graphSetzen: function (g) { G = g; }, graph: function () { return G; },
        renderer: function () { return R; }, hervor: function () { return _hervor; },
        hoverAuswahl: hoverAuswahl, knotenReduzierer: knotenReduzierer, freiAuswaehlen: freiAuswaehlen,
        kantenReduzierer: kantenReduzierer, MAX_BESCHRIFTUNGEN: MAX_BESCHRIFTUNGEN,
        MAX_KANTENTEXTE: MAX_KANTENTEXTE,
        hoverSetzen: function (n) {
            _hover = n; _hoverNachbarn = n ? nachbarn(n) : {};
            _hoverAuswahl = n ? hoverAuswahl(n) : { knoten: {}, kanten: {} };
        },
        inselnBerechnen: inselnBerechnen,
        farbenLesen: farbenLesen, inseln: function () { return _inseln; },
        detailOeffnen: detailOeffnen, hervorheben: hervorheben,
        aehnlichkeit: aehnlichkeit, rueckFaktor: rueckFaktor, markdownZeichnen: markdownZeichnen,
        verworfenSetzen: function (l) { _verworfen = l || []; },
        widerspruecheSetzen: function (l) { _widersprueche = l || []; },
        insightsZeichnen: insightsZeichnen, zugang: function () { return _zugang; },
        KLAPP_SPEICHER: KLAPP_SPEICHER,
        pruefNachfrageMs: function (ms) { PRUEF_NACHFRAGE_MS = ms; }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
