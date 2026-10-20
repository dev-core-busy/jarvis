/**
 * Sicherheitsprotokoll – Ansicht im Telemetrie-Reiter (nur lesen).
 *
 * Quelle: GET /api/security/log (backend/sicherheits_log.py). Es gibt bewusst
 * KEINEN Loeschweg: das Protokoll ist per Hash-Kette gegen nachtraegliche
 * Aenderung gesichert, und genau das zeigt die Zeile ueber der Tabelle an.
 *
 * Alle Inhalte gehen per textContent ins DOM, nie per innerHTML: Benutzernamen,
 * Pfade und Gruende stammen teils aus Anfragen von aussen (fehlgeschlagene
 * Anmeldungen) – ein eingeschleustes Tag waere hier eine Luecke in genau der
 * Ansicht, mit der ein Angriff untersucht wird.
 */
window.sicherheitsProtokoll = (function () {
    'use strict';

    // Arten, die auf einen Fehlschlag oder Angriff hinweisen (Markierung).
    var WARN = {
        anmeldung_fehlgeschlagen: 1, konto_gesperrt: 1, admin_verweigert: 1,
        spruehangriff: 1, kennwort_pruefung: 1, geheimnis_schluessel_fehlt: 1,
        tls_pruefung_aus: 1
    };
    var OK = { anmeldung: 1, abmeldung: 1, dienst_start: 1 };
    // Gruende aus sicherheits_log.pruefen() -> i18n-Schluessel
    var GRUND = {
        'kein JSON': 'kein_json',
        'Kette unterbrochen': 'unterbrochen',
        'Inhalt veraendert': 'inhalt',
        'ohne Schluessel': 'ohne_schluessel',
        'Schluessel fehlt': 'schluessel_fehlt',
        'letzte Zeile ohne Schluessel': 'letzte'
    };

    var gebunden = false;
    var angewandt = null;     // Filter, mit dem die SICHTBARE Liste geholt wurde
    var anzahl = 0;

    function $(id) { return document.getElementById(id); }

    /** i18n mit Rueckfall: window.t liefert bei fehlendem Schluessel den Schluessel. */
    function T(k, f) {
        var v = window.t ? window.t(k) : k;
        return (v && v !== k) ? v : f;
    }

    function artName(art) {
        return T('sprot.art.' + art, art);
    }

    function stufe(e) {
        var erg = String(e.ergebnis || '').toLowerCase();
        if (WARN[e.art] || /^[45]\d\d$/.test(erg) || erg === 'fehler' || erg === 'gesperrt'
            || erg === 'verweigert') {
            return 'warn';
        }
        return OK[e.art] ? 'ok' : 'neutral';
    }

    function zeit(ts) {
        var lang = window._lang === 'en' ? 'en-GB' : 'de-DE';
        try {
            return new Date(ts * 1000).toLocaleString(lang, { dateStyle: 'short', timeStyle: 'medium' });
        } catch (e) {
            return String(ts);
        }
    }

    function filter() {
        return {
            art: ($('sprot-filter-art') || {}).value || '',
            benutzer: (($('sprot-filter-user') || {}).value || '').trim(),
            ip: (($('sprot-filter-ip') || {}).value || '').trim()
        };
    }

    function binden() {
        if (gebunden) return;
        gebunden = true;
        $('sprot-refresh-btn').addEventListener('click', laden);
        $('sprot-apply-btn').addEventListener('click', laden);
        $('sprot-filter-art').addEventListener('change', laden);
        ['sprot-filter-user', 'sprot-filter-ip'].forEach(function (id) {
            $(id).addEventListener('keydown', function (e) { if (e.key === 'Enter') laden(); });
            ['input', 'change'].forEach(function (ev) { $(id).addEventListener(ev, zaehler); });
        });
        // Bei Sprachwechsel neu zeichnen (Ereignisnamen, Zeitformat)
        document.addEventListener('jarvis-lang-changed', function () {
            if (letzte) zeichnen(letzte);
        });
    }

    var letzte = null;

    function fehler(text) {
        var el = $('sprot-fehler');
        if (!el) return;
        // Ein Fehler verschwindet NICHT von selbst – man muss ihn lesen koennen.
        el.textContent = text || '';
        el.style.display = text ? 'block' : 'none';
    }

    async function laden() {
        var f = filter();
        var p = new URLSearchParams({ limit: ($('sprot-limit') || {}).value || '200' });
        if (f.art) p.set('art', f.art);
        if (f.benutzer) p.set('benutzer', f.benutzer);
        if (f.ip) p.set('ip', f.ip);
        try {
            var tok = window.authToken || (window.JarvisSitzung && window.JarvisSitzung.token());
            var r = await fetch('/api/security/log?' + p.toString(),
                                { headers: { 'Authorization': 'Bearer ' + tok } });
            if (!r.ok) {
                fehler(T('telemetry.sprot_ladefehler', 'Das Protokoll konnte nicht geladen werden ({s}).')
                       .replace('{s}', 'HTTP ' + r.status));
                zaehler();
                return;
            }
            var d = await r.json();
            fehler('');
            angewandt = f;
            letzte = d;
            zeichnen(d);
        } catch (e) {
            fehler(T('telemetry.sprot_ladefehler', 'Das Protokoll konnte nicht geladen werden ({s}).')
                   .replace('{s}', e.message));
            zaehler();
        }
    }

    function zeichnen(d) {
        arten(d.arten || []);
        kette(d);
        tabelle(d.eintraege || []);
    }

    /** Auswahlliste aus den Arten, die im Protokoll VORKOMMEN; Auswahl bleibt. */
    function arten(liste) {
        var sel = $('sprot-filter-art');
        if (!sel) return;
        var gewaehlt = sel.value;
        while (sel.options.length > 1) sel.remove(1);
        liste.map(function (a) { return [artName(a), a]; })
            .sort(function (x, y) { return x[0].localeCompare(y[0]); })
            .forEach(function (paar) {
                var o = document.createElement('option');
                o.value = paar[1];
                o.textContent = paar[0];
                sel.appendChild(o);
            });
        // Eine Auswahl, die es nicht (mehr) gibt, wird nicht still verworfen:
        // sel.value auf eine fehlende Option ergaebe '' = "Alle".
        if (gewaehlt && liste.indexOf(gewaehlt) < 0) {
            var o = document.createElement('option');
            o.value = gewaehlt;
            o.textContent = artName(gewaehlt);
            sel.appendChild(o);
        }
        sel.value = gewaehlt;
    }

    function kette(d) {
        var el = $('sprot-kette');
        if (!el) return;
        el.textContent = '';
        var k = d.kette || {};
        var zeile = document.createElement('div');
        if (!k.zeilen) {
            el.className = 'sprot-kette';
            zeile.textContent = T('telemetry.sprot_kette_leer', 'Noch keine Einträge im Protokoll.');
        } else if (k.ok) {
            el.className = 'sprot-kette sprot-kette-ok';
            zeile.textContent = T('telemetry.sprot_kette_ok',
                'Unverändert: die Prüfkette über alle {n} Einträge ist intakt.').replace('{n}', k.zeilen);
        } else {
            el.className = 'sprot-kette sprot-kette-bruch';
            zeile.textContent = T('telemetry.sprot_kette_bruch',
                'Prüfkette unterbrochen an {n} Stelle(n):').replace('{n}', k.anzahl_brueche || 0);
        }
        el.appendChild(zeile);
        if (!k.ok && k.zeilen) {
            var ul = document.createElement('ul');
            (k.brueche || []).forEach(function (b) {
                var li = document.createElement('li');
                var g = GRUND[b.grund] ? T('telemetry.sprot_grund.' + GRUND[b.grund], b.grund) : b.grund;
                li.textContent = T('telemetry.sprot_zeile', 'Zeile {z}: {g}')
                    .replace('{z}', b.zeile).replace('{g}', g);
                ul.appendChild(li);
            });
            var rest = (k.anzahl_brueche || 0) - (k.brueche || []).length;
            if (rest > 0) {
                var li2 = document.createElement('li');
                li2.textContent = T('telemetry.sprot_weitere', '… und {n} weitere').replace('{n}', rest);
                ul.appendChild(li2);
            }
            el.appendChild(ul);
        }
        // Rahmenangaben: Frist, zweite Ablage, Schreibfehler
        var info = document.createElement('div');
        info.className = 'sprot-kette-info';
        var teile = [];
        var tage = d.aufbewahrung_tage;
        if (tage === 0) teile.push(T('telemetry.sprot_dauerhaft', 'Aufbewahrung: dauerhaft'));
        else if (tage) teile.push(T('telemetry.sprot_aufbewahrung', 'Aufbewahrung: {n} Tage').replace('{n}', tage));
        if (d.syslog === false) teile.push(T('telemetry.sprot_syslog_aus', 'Systemjournal nicht verfügbar.'));
        var sf = (d.schreibfehler || {}).datei || 0;
        if (sf) teile.push(T('telemetry.sprot_schreibfehler', '{n} Schreibfehler').replace('{n}', sf));
        info.textContent = teile.join(' · ');
        if (teile.length) el.appendChild(info);
    }

    function zelle(tr, text, klasse) {
        var td = document.createElement('td');
        if (klasse) td.className = klasse;
        td.textContent = text;
        tr.appendChild(td);
        return td;
    }

    function tabelle(liste) {
        var tbody = $('sprot-tbody');
        if (!tbody) return;
        anzahl = liste.length;
        zaehler();
        tbody.textContent = '';
        if (!liste.length) {
            var tr0 = document.createElement('tr');
            var td0 = zelle(tr0, T('telemetry.sprot_empty', 'Keine Einträge für diese Auswahl.'), 'audit-empty');
            td0.colSpan = 6;
            tbody.appendChild(tr0);
            return;
        }
        liste.forEach(function (e) {
            var tr = document.createElement('tr');
            zelle(tr, zeit(e.ts), 'audit-ts');
            var tdArt = document.createElement('td');
            var badge = document.createElement('span');
            badge.className = 'sprot-art sprot-art-' + stufe(e);
            badge.textContent = artName(e.art || '');
            badge.title = e.art || '';
            tdArt.appendChild(badge);
            tr.appendChild(tdArt);
            zelle(tr, e.benutzer_anzeige || e.benutzer || '—', 'audit-user');
            zelle(tr, e.ip || '—', 'audit-ts');
            zelle(tr, e.ergebnis || '—', 'audit-res');
            var tdD = document.createElement('td');
            tdD.className = 'audit-args';
            var det = e.details || {};
            var schl = Object.keys(det);
            if (!schl.length) {
                tdD.textContent = '—';
            } else {
                schl.forEach(function (k, i) {
                    if (i) tdD.appendChild(document.createTextNode(' '));
                    var a = document.createElement('span');
                    a.className = 'audit-arg-key';
                    a.textContent = k;
                    var b = document.createElement('span');
                    b.className = 'audit-arg-val';
                    var v = det[k];
                    v = typeof v === 'string' ? v : JSON.stringify(v);
                    b.textContent = v.length > 160 ? v.slice(0, 160) + '…' : v;
                    b.title = v;
                    tdD.appendChild(a);
                    tdD.appendChild(document.createTextNode('='));
                    tdD.appendChild(b);
                });
            }
            tr.appendChild(tdD);
            if (stufe(e) === 'warn') tr.className = 'sprot-zeile-warn';
            tbody.appendChild(tr);
        });
    }

    /** Trefferzahl; weicht der Feldinhalt vom angewandten Filter ab, sagt die Zeile es. */
    function zaehler() {
        var el = $('sprot-count');
        if (!el) return;
        el.textContent = T('telemetry.sprot_count', '{n} Einträge').replace('{n}', anzahl);
        var jetzt = filter();
        if (angewandt && (jetzt.benutzer !== angewandt.benutzer || jetzt.ip !== angewandt.ip)) {
            var s = document.createElement('span');
            s.className = 'sprot-veraltet';
            s.textContent = ' · ' + T('telemetry.audit_filter_stale', 'Filter geändert – „Anwenden“ drücken');
            el.appendChild(s);
        }
    }

    return {
        init: function () { binden(); laden(); },
        _laden: laden
    };
})();
