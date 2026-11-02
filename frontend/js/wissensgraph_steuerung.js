/**
 * Wissensgraph – Aufbau und Pflege in Einstellungen → Wissen.
 *
 * Vorgabe des Betreibers 2026-11-01: die Steuerung (Status, Schalter, Neuaufbau)
 * gehoert in die Einstellungen; auf /wissensgraph bleiben Pruefliste und Export.
 * Damit haengt die Portal-Kachel nur noch an den Wissenseditoren, nicht mehr am
 * Admin-Recht. Die Schranke sitzt am Server (require_local_auth fuer Status,
 * Schalter und Aufbau) – hier wird nur gezeichnet.
 *
 * Abgefragt wird NUR, solange der Abschnitt sichtbar ist (Reiter offen, Abschnitt
 * aufgeklappt): die Einstellungsseite bleibt oft stundenlang offen, und ein
 * Abruf alle 10 s fuer einen zugeklappten Kasten waere Last ohne Leser.
 */
(function () {
    'use strict';

    var NACHFRAGE_MS = 10000;
    var _timer = null;
    var _gebunden = false;
    var _gruppenGeladen = false;
    var _zahlStand = {};    // letzter Stand des Servers je Zahlenfeld

    function $(id) { return document.getElementById(id); }

    function tok() {
        try { return window.JarvisSitzung.token(); } catch (e) { return ''; }
    }

    function fehlertext(d, rueckfall) {
        if (!d) { return rueckfall; }
        return d.error || d.detail || d.message || rueckfall;
    }

    function holeJson(pfad, opt) {
        var o = opt || {};
        o.headers = o.headers || {};
        o.headers['Authorization'] = 'Bearer ' + tok();
        return fetch(pfad, o).then(function (r) {
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

    // window.t liefert bei fehlendem Schluessel den Schluessel selbst.
    function t(key, fallback, werte) {
        var s = (window.t && window.t(key) !== key ? window.t(key) : null) || fallback;
        if (werte) {
            Object.keys(werte).forEach(function (k) { s = s.split('{' + k + '}').join(String(werte[k])); });
        }
        return s;
    }

    function el(tag, cls, text) {
        var e = document.createElement(tag);
        if (cls) { e.className = cls; }
        if (text !== undefined && text !== null) { e.textContent = text; }
        return e;
    }

    /** Drehender Kreis + Text (``.jv-pkg-spin`` aus theme.css). */
    function ladeText(ziel, text) {
        if (!ziel) { return; }
        ziel.textContent = '';
        var k = el('span', 'jv-pkg-spin');
        k.setAttribute('aria-hidden', 'true');
        ziel.appendChild(k);
        ziel.appendChild(document.createTextNode(text));
    }

    function meldung(id, text, art) {
        var m = $(id);
        if (!m) { return; }
        if (art === 'lade') { ladeText(m, text); } else { m.textContent = text || ''; }
        m.className = 'kbwg-meldung' + (art === 'err' ? ' is-err' : art === 'ok' ? ' is-ok' : '');
    }

    /** Reiter "Wissen" offen UND Abschnitt aufgeklappt. jsdom rechnet kein
     *  Layout – deshalb ueber ``style.display``, nicht ``offsetParent``. */
    function sichtbar() {
        var b = $('kb-sect-wg-body'), tab = $('settings-tab-knowledge');
        return !!b && b.style.display !== 'none' && !!tab && tab.style.display !== 'none';
    }

    /** Arbeitet der Dienst gerade? ⚠ ``laeuft`` gilt nur fuer die Dokument-
     *  Warteschlange – im Nachlauf (Widersprueche, Wiki-Seiten) steht es auf
     *  false, waehrend ``aktuell`` den bearbeiteten Begriff nennt. Nur ``laeuft``
     *  zu lesen zeigte die ganze Nacht "an – wartet" (gemeldet 2026-10-31). */
    function arbeitetGerade(st) {
        return !!(st && st.aktiv && (st.laeuft || st.aktuell));
    }

    /** WELCHER Teil arbeitet gerade – dort steht der drehende Kreis (Wunsch des
     *  Betreibers 2026-11-01: nicht pauschal bei "Zustand", sondern da, wo
     *  gearbeitet wird). ``aktuell`` nennt im Nachlauf den Begriff mit Praefix
     *  (widerspruch:/wiki:), bei der Extraktion den Dokumentpfad. */
    function arbeitsteil(st) {
        if (!arbeitetGerade(st)) { return null; }
        var m = /^(widerspruch|wiki):/.exec(st.aktuell || '');
        if (m) { return m[1] === 'wiki' ? 'wiki' : 'contra'; }
        return 'queue';
    }

    /** "widerspruch:e:sap" → lesbarer Text; ein Dateipfad bleibt, wie er ist. */
    function aktuellText(a) {
        var m = /^(widerspruch|wiki):(.*)$/.exec(a || '');
        if (!m) { return a; }
        var nm = m[2].replace(/^e:/, '');
        return m[1] === 'wiki' ? t('wissensgraph.st_cur_wiki', 'Wiki-Seite zu „{name}“', { name: nm })
                               : t('wissensgraph.st_cur_contra', 'Widerspruchsprüfung zu „{name}“', { name: nm });
    }

    function statusZeichnen(st) {
        var box = $('wg-status');
        if (!box) { return; }
        box.textContent = '';
        var g = st.graph || {}, z = st.zaehler || {}, n = st.nachlauf || {};
        var arbeitet = arbeitetGerade(st), teil = arbeitsteil(st);
        // Dritter Eintrag: Kennung des Teils – die arbeitende Zeile bekommt den Kreis.
        var zeilen = [
            [t('wissensgraph.st_state', 'Zustand'), st.aktiv
                ? (arbeitet ? t('wissensgraph.st_running', 'an – arbeitet') : t('wissensgraph.st_idle', 'an – wartet'))
                : t('wissensgraph.st_off', 'aus'), 'state'],
            [t('wissensgraph.st_queue', 'Warteschlange'), String(st.warteschlange || 0), 'queue'],
            [t('wissensgraph.st_done', 'Seit Start erledigt / fehlgeschlagen'), (st.erledigt || 0) + ' / ' + (st.fehler || 0)],
            [t('wissensgraph.st_calls', 'Modellaufrufe · Token ein/aus'),
             (z.aufrufe || 0) + ' · ' + (z.token_ein || 0) + ' / ' + (z.token_aus || 0)],
            [t('wissensgraph.st_calls_care', 'Widersprüche und Wiki · Modellaufrufe · Token ein/aus'),
             (z.pflege_aufrufe || 0) + ' · ' + (z.pflege_token_ein || 0) + ' / ' + (z.pflege_token_aus || 0)],
            [t('wissensgraph.st_graph', 'Graph'), t('wissensgraph.st_graph_v', '{q} Dokumente · {e} Begriffe · {k} Verbindungen',
                { q: g.quellen || 0, e: g.entitaeten || 0, k: g.kanten || 0 })],
            [t('wissensgraph.st_contra', 'Widersprüche'), t('wissensgraph.st_contra_v', '{n} gefunden · {o} Begriffe offen',
                { n: g.widersprueche || 0, o: n.widersprueche_offen || 0 }), 'contra'],
            [t('wissensgraph.st_wiki', 'Wiki-Seiten'), t('wissensgraph.st_wiki_v', '{n} vorhanden · {o} offen',
                { n: n.wiki_seiten || 0, o: n.wiki_offen || 0 }), 'wiki'],
            [t('wissensgraph.st_model', 'Modell'), st.modell || '–']
        ];
        var dl = el('dl', 'kbwg-st');
        zeilen.forEach(function (p) {
            dl.appendChild(el('dt', '', p[0]));
            var dd = el('dd', '');
            if (teil && p[2] === teil) { ladeText(dd, p[1]); } else { dd.textContent = p[1]; }
            dl.appendChild(dd);
        });
        box.appendChild(dl);
        if (st.aktuell) {
            box.appendChild(el('p', 'kb-hint', t('wissensgraph.st_current', 'Gerade: {pfad}', { pfad: aktuellText(st.aktuell) })));
        }
        if (n.pause) {
            box.appendChild(el('p', 'kb-hint', t('wissensgraph.st_paused',
                'Widerspruchsprüfung und Wiki-Seiten sind angehalten – sie laufen mit dem nächsten Aufbau weiter.')));
        }
        einstellungenZeichnen(st.einstellungen || {});
        var f = st.letzte_fehler || [];
        if (f.length) {
            box.appendChild(el('h4', '', t('wissensgraph.st_errors', 'Letzte Fehler')));
            var ul = el('ul', 'kbwg-fehler');
            f.slice(-5).reverse().forEach(function (x) { ul.appendChild(el('li', '', (x.pfad ? x.pfad + ': ' : '') + x.grund)); });
            box.appendChild(ul);
        }
        var start = $('wg-start');
        if (start) {
            start.disabled = !st.aktiv;
            start.title = st.aktiv ? '' : t('wissensgraph.st_off_hint', 'Der Wissensgraph ist ausgeschaltet.');
        }
    }

    function statusHolen() {
        clearTimeout(_timer);
        if (!sichtbar()) { return Promise.resolve(null); }
        var sb = $('wg-status');
        if (sb && !sb.childNodes.length) { ladeText(sb, t('wissensgraph.loading', 'Lade …')); }
        return holeJson('/api/wissensgraph/status').then(function (st) {
            statusZeichnen(st);
            clearTimeout(_timer);
            var n = st.nachlauf || {};
            var nachlauf = st.aktiv && !n.pause && ((n.widersprueche_offen || 0) + (n.wiki_offen || 0)) > 0;
            if (arbeitetGerade(st) || st.warteschlange || nachlauf) { _timer = setTimeout(statusHolen, NACHFRAGE_MS); }
            return st;
        }).catch(function (e) {
            var b = $('wg-status');
            if (b) { b.textContent = t('wissensgraph.load_failed', 'Laden fehlgeschlagen: {grund}', { grund: e.message }); }
        });
    }

    function einstellungenZeichnen(e) {
        document.querySelectorAll('[data-wg-einstellung]').forEach(function (h) {
            var k = h.getAttribute('data-wg-einstellung');
            if (typeof e[k] === 'boolean' && !h.disabled) { h.checked = e[k]; }
        });
        // Die Abfrage laeuft waehrend der Arbeit alle 10 s: ein Feld, in dem gerade
        // getippt wird, bleibt deshalb unangetastet (data-wg-tippt).
        document.querySelectorAll('[data-wg-zahl]').forEach(function (h) {
            var k = h.getAttribute('data-wg-zahl');
            if (typeof e[k] !== 'number') { return; }
            _zahlStand[k] = e[k];
            if (!h.disabled && !h.hasAttribute('data-wg-tippt')) { h.value = String(e[k]); }
        });
    }

    function einstellungSchreiben(h) {
        var rumpf = {};
        rumpf[h.getAttribute('data-wg-einstellung')] = h.checked;
        einstellungSenden(h, rumpf);
    }

    /** Zahlenfeld: Grenzen stehen im Markup (min/max), der Server prueft sie
     *  noch einmal. Ungueltiges springt sofort auf den Stand des Servers zurueck. */
    function zahlSchreiben(h) {
        var k = h.getAttribute('data-wg-zahl'), roh = h.value.trim(), v = Number(roh), rumpf = {};
        h.removeAttribute('data-wg-tippt');
        if (roh === '' || !isFinite(v) || v < Number(h.min) || v > Number(h.max)
                || (h.step === '1' && v % 1 !== 0)) {
            if (k in _zahlStand) { h.value = String(_zahlStand[k]); }
            meldung('wg-einst-meldung', t('wissensgraph.rate_invalid', 'Bitte eine Zahl von {min} bis {max} eingeben.',
                { min: h.min, max: h.max }), 'err');
            return;
        }
        if (v === _zahlStand[k]) { return; }
        rumpf[k] = v;
        einstellungSenden(h, rumpf);
    }

    function einstellungSenden(h, rumpf) {
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

    function gruppenFuellen() {
        if (_gruppenGeladen) { return Promise.resolve(); }
        return holeJson('/api/knowledge/groups').then(function (d) {
            var s = $('wg-umfang-gruppe');
            if (!s) { return; }
            s.textContent = '';
            (d.groups || []).filter(function (g) { return g && g.id && g.id !== 'ungrouped'; }).forEach(function (g) {
                var o = el('option', '', g.name || g.id);
                o.value = g.id;
                s.appendChild(o);
            });
            _gruppenGeladen = true;
        }).catch(function () { /* ohne Gruppenliste bleibt "Eingestellter Umfang" */ });
    }

    function umfangZeigen() {
        var u = $('wg-umfang').value;
        $('wg-umfang-gruppe').style.display = u === 'gruppe' ? '' : 'none';
        $('wg-umfang-ordner').style.display = u === 'ordner' ? '' : 'none';
    }

    function binden() {
        if (_gebunden || !$('kb-sect-wg-body')) { return; }
        _gebunden = true;
        document.querySelectorAll('[data-wg-einstellung]').forEach(function (h) {
            h.addEventListener('change', function () { einstellungSchreiben(h); });
        });
        document.querySelectorAll('[data-wg-zahl]').forEach(function (h) {
            h.addEventListener('input', function () { h.setAttribute('data-wg-tippt', '1'); });
            h.addEventListener('change', function () { zahlSchreiben(h); });
            h.addEventListener('blur', function () { h.removeAttribute('data-wg-tippt'); });
        });
        $('wg-umfang').addEventListener('change', umfangZeigen);
        umfangZeigen();
        $('wg-start').addEventListener('click', aufbauStarten);
        $('wg-abbrechen').addEventListener('click', aufbauAbbrechen);
        // Das Auf-/Zuklappen macht app.js (_collapseInit); dessen Zuhoerer
        // kommt beim ersten Oeffnen des Reiters dazu, also NACH diesem – erst
        // im naechsten Takt ist der neue Zustand gesetzt.
        var kopf = $('kb-sect-wg-hdr');
        if (kopf) { kopf.addEventListener('click', function () { setTimeout(onShow, 0); }); }
    }

    /** Reiter "Wissen" geoeffnet (app.js) oder Abschnitt aufgeklappt. */
    function onShow() {
        binden();
        if (!sichtbar()) { clearTimeout(_timer); return Promise.resolve(null); }
        gruppenFuellen();
        return statusHolen();
    }

    window.WissensgraphSteuerung = {
        onShow: onShow, statusHolen: statusHolen, statusZeichnen: statusZeichnen,
        arbeitetGerade: arbeitetGerade, arbeitsteil: arbeitsteil, nachfrageMs: function (ms) { NACHFRAGE_MS = ms; }
    };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', binden);
    } else {
        binden();
    }
})();
