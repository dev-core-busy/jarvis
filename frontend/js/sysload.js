/* ============================================================
 * sysload.js – Systemauslastung hinter der CPU-Anzeige (/portal)
 *
 * Ein Klick auf die CPU-Anzeige oeffnet – NUR FUER ADMINISTRATOREN – ein
 * Fenster mit CPU (gesamt + je Kern), Speicher, Netzwerk, Festplatte und den
 * 20 Prozessen, die gerade am meisten CPU ziehen.
 *
 * Die Admin-Frage entscheidet `/api/me`, nicht die Seite (dieselbe Lehre wie
 * bei syspackages.js / settings_btn.js). ⚠ SICHTBARKEIT IST KEINE
 * BERECHTIGUNG: die Schranke sitzt am Endpunkt (`/api/system/load`,
 * `require_local_auth`). Fuer Nicht-Admins bleibt die Anzeige ein reiner
 * Balken ohne Klick.
 *
 * Die CPU-Anzeige baut cpubar.js – womoeglich ERST nach diesem Skript (sie
 * entsteht beim ersten Takt mit Token). Deshalb haengt der Klick als
 * Delegation am Dokument und nicht am Element; Tastatur-Attribute werden
 * nachgezogen, sobald die Anzeige existiert.
 *
 * Solange das Fenster offen ist, wird alle TAKT_MS neu gemessen; die Verlaeufe
 * leben nur im Fenster und werden beim Schliessen verworfen. Ein Abruf dauert
 * serverseitig ~0,5 s (Messfenster) – es laeuft nie mehr als einer zugleich.
 * ============================================================ */
(function () {
    'use strict';

    if (window.JarvisSysLoad) return;   // doppeltes Laden vermeiden

    // Gleiche Kette wie cpubar.js/syspackages.js
    var TOKEN_KEYS = window.JarvisSitzung.tokenSchluessel();
    var TAKT_MS = 3000;
    // 40 Punkte x 3 s = 2 Minuten Verlauf
    var VERLAUF_MAX = 40;

    var _admin = false;
    var _kasten = null;
    var _timer = null;
    var _laeuft = false;
    var _letzter = null;
    var _verlauf = null;
    // Sortierung der Prozesstabelle. Sie lebt im MODUL, nicht im DOM: die
    // Tabelle wird bei jedem Takt neu gezeichnet und muesste sonst alle 3 s
    // auf die Vorgabe zurueckspringen. Vorgabe = Reihenfolge des Servers
    // (CPU absteigend), und die bleibt ueber '#' jederzeit erreichbar.
    var _sortSpalte = 'cpu';
    var _sortAb = true;
    // Zahlenspalten fangen absteigend an – "wer zieht am meisten" ist die
    // Frage, die man dort stellt; Textspalten alphabetisch.
    var ZAHL_SPALTEN = { rang: 1, pid: 1, cpu: 1, rss: 1, threads: 1 };

    function T(key, fallback) {
        try { if (window.t) { var v = window.t(key); if (v && v !== key) return v; } } catch (e) {}
        return fallback;
    }

    function token() {
        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            try {
                var t = localStorage.getItem(TOKEN_KEYS[i]);
                if (t) return t;
            } catch (e) { /* Speicher gesperrt */ }
        }
        return '';
    }

    function esc(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    /** Zahl mit fester Nachkommazahl im Format der Oberflaechensprache
     *  (DE: Komma). `toFixed` allein schriebe immer einen Punkt. */
    function zahl(n, stellen) {
        var loc = (window._lang === 'en') ? 'en-US' : 'de-DE';
        try {
            return Number(n).toLocaleString(loc, { minimumFractionDigits: stellen,
                                                   maximumFractionDigits: stellen });
        } catch (e) { return Number(n).toFixed(stellen); }
    }

    /** Bytes in eine lesbare Groesse (Basis 1024, wie `free -h`). */
    function bytes(n) {
        var b = Number(n) || 0;
        var e = ['B', 'KiB', 'MiB', 'GiB', 'TiB'];
        var i = 0;
        while (b >= 1024 && i < e.length - 1) { b /= 1024; i++; }
        return (i === 0 ? String(Math.round(b)) : zahl(b, b >= 100 ? 0 : 1)) + ' ' + e[i];
    }

    function rate(n) {
        if (n == null) return '–';
        return bytes(n) + '/s';
    }

    function prozent(p) {
        var n = Number(p) || 0;
        return (n >= 10 ? String(Math.round(n)) : zahl(n, 1)) + ' %';
    }

    function neuerVerlauf() {
        return { cpu: [], mem: [], rx: [], tx: [], rd: [], wr: [] };
    }

    function schiebe(liste, wert) {
        liste.push(wert == null ? 0 : Number(wert) || 0);
        if (liste.length > VERLAUF_MAX) liste.shift();
    }

    /* ── Die CPU-Anzeige als Knopf ─────────────────────────────────────── */

    function anzeige() { return document.getElementById('cpu-bar'); }

    function anzeigeAusstatten() {
        var el = anzeige();
        if (!el) return false;
        if (_admin) {
            el.classList.add('jv-cpu-klick');
            el.setAttribute('role', 'button');
            el.setAttribute('tabindex', '0');
            el.setAttribute('data-i18n-title', 'load.btn');
            el.title = T('load.btn', 'Systemauslastung anzeigen');
        } else {
            el.classList.remove('jv-cpu-klick');
            el.removeAttribute('role');
            el.removeAttribute('tabindex');
            el.setAttribute('data-i18n-title', 'wissen.cpu_load');
            el.title = T('wissen.cpu_load', 'CPU-Auslastung');
        }
        return true;
    }

    // Die Anzeige entsteht womoeglich erst spaeter (cpubar.js baut sie beim
    // ersten Takt) – ein paar Sekunden nachsehen, dann aufgeben.
    function ausstattenSpaeter() {
        var n = 0;
        var iv = setInterval(function () {
            if (anzeigeAusstatten() || ++n > 40) clearInterval(iv);
        }, 500);
    }

    function aufAnzeige(e) {
        var z = e.target;
        return !!(z && z.closest && z.closest('#cpu-bar'));
    }

    document.addEventListener('click', function (e) {
        if (_admin && aufAnzeige(e)) oeffnen();
    });
    document.addEventListener('keydown', function (e) {
        if (_admin && (e.key === 'Enter' || e.key === ' ') && aufAnzeige(e)) {
            e.preventDefault();
            oeffnen();
        }
    });

    /* ── Der Kasten ────────────────────────────────────────────────────── */

    function kastenEl() {
        if (_kasten) return _kasten;
        _kasten = document.createElement('div');
        // Rahmen, Kopf und Tabelle vom Paket-Fenster: gleiche Bauform, gleiche
        // Regeln (deckend; ein Klick daneben schliesst NICHT).
        _kasten.className = 'jv-pkg-overlay jv-load-overlay';
        _kasten.setAttribute('role', 'dialog');
        _kasten.setAttribute('aria-modal', 'true');
        _kasten.addEventListener('click', function (e) {
            var h = e.target.closest && e.target.closest('th[data-sort]');
            if (h) umsortieren(h.getAttribute('data-sort'));
        });
        // Delegation am Kasten statt je Kopfzelle: die Zellen entstehen bei
        // jedem Takt neu, ein Zuhoerer daran waere nach 3 s weg.
        _kasten.addEventListener('keydown', function (e) {
            if (e.key !== 'Enter' && e.key !== ' ') return;
            var h = e.target.closest && e.target.closest('th[data-sort]');
            if (!h) return;
            e.preventDefault();
            umsortieren(h.getAttribute('data-sort'));
        });
        document.body.appendChild(_kasten);
        return _kasten;
    }

    function offen() { return !!(_kasten && _kasten.classList.contains('an')); }

    function beiTaste(e) {
        if (e.key === 'Escape') { e.stopPropagation(); schliessen(); }
    }

    function schliessen() {
        if (_timer) { clearTimeout(_timer); _timer = null; }
        if (_kasten) _kasten.classList.remove('an');
        _letzter = null;
        _verlauf = null;
        document.removeEventListener('keydown', beiTaste);
        var a = anzeige();
        if (a) a.focus();
    }

    function oeffnen() {
        if (offen()) { schliessen(); return; }
        _verlauf = neuerVerlauf();
        _letzter = null;
        var el = kastenEl();
        el.setAttribute('aria-label', T('load.title', 'Systemauslastung'));
        el.innerHTML = '<div class="jv-pkg-box jv-load-box">' + kopf() + '<div class="jv-load-body">'
            + '<div class="jv-pkg-lade">' + esc(T('load.loading', 'Auslastung wird gemessen …'))
            + '</div></div></div>';
        verdrahteKopf();
        el.classList.add('an');
        document.addEventListener('keydown', beiTaste);
        abrufen();
    }

    function kopf() {
        var kreuz = '&times;';
        try { if (window.JarvisIcons) kreuz = window.JarvisIcons.close(); } catch (e) {}
        return '<div class="jv-pkg-head">'
            + '<div class="jv-pkg-h">' + esc(T('load.title', 'Systemauslastung')) + '</div>'
            + '<span class="jv-load-live" aria-live="off"></span>'
            + '<button type="button" class="jv-pkg-close" title="'
            + esc(T('common.close', 'Schließen')) + '" aria-label="'
            + esc(T('common.close', 'Schließen')) + '">' + kreuz + '</button>'
            + '</div>';
    }

    function verdrahteKopf() {
        var zu = _kasten.querySelector('.jv-pkg-close');
        if (zu) zu.addEventListener('click', schliessen);
    }

    function abrufen() {
        if (_laeuft || !offen()) return;
        _laeuft = true;
        fetch('/api/system/load', { headers: { 'Authorization': 'Bearer ' + token() } })
            .then(function (r) {
                return r.json().catch(function () { return null; })
                    .then(function (d) { return { ok: r.ok, status: r.status, d: d }; });
            })
            .then(function (a) {
                if (!offen()) return;
                if (!a.ok || !a.d || !a.d.prozesse) {
                    fehler((a.d && (a.d.error || a.d.detail)) || (a.status === 403
                        ? T('load.err_admin', 'Nur für Administratoren.')
                        : T('load.err', 'Die Auslastung konnte nicht gemessen werden.')));
                    return;
                }
                _letzter = a.d;
                merken(a.d);
                zeichnen();
                planen();
            })
            .catch(function () {
                if (!offen()) return;
                // Netzfehler mitten im Verlauf: letzten Stand stehen lassen und
                // es erneut versuchen – ein Aussetzer ist kein Grund, das
                // Fenster zu leeren.
                if (_letzter) { setzeLive(T('load.err_net', 'Der Server war nicht erreichbar.'), true); planen(); }
                else fehler(T('load.err_net', 'Der Server war nicht erreichbar.'));
            })
            .then(function () { _laeuft = false; });
    }

    function planen() {
        if (_timer) clearTimeout(_timer);
        _timer = null;
        // Hintergrund-Tab: nicht weiter messen (Code-Review 2026-10-07 – jede
        // Abfrage kostet auf dem Server ~0,5 s Messung, alle 3 s, auch wenn
        // niemand hinsieht). Beim Zurueckkehren holt der visibilitychange-
        // Zuhoerer unten sofort den naechsten Stand.
        if (document.hidden) return;
        _timer = setTimeout(abrufen, TAKT_MS);
    }

    document.addEventListener('visibilitychange', function () {
        if (!document.hidden && offen() && !_timer && !_laeuft) abrufen();
    });

    function fehler(text) {
        var body = _kasten && _kasten.querySelector('.jv-load-body');
        if (body) body.innerHTML = '<div class="jv-pkg-fehler">' + esc(text) + '</div>';
    }

    function setzeLive(text, istFehler) {
        var l = _kasten && _kasten.querySelector('.jv-load-live');
        if (!l) return;
        l.textContent = text;
        l.classList.toggle('ist-fehler', !!istFehler);
    }

    function merken(d) {
        var v = _verlauf || (_verlauf = neuerVerlauf());
        schiebe(v.cpu, d.cpu && d.cpu.prozent);
        schiebe(v.mem, d.speicher && d.speicher.prozent);
        schiebe(v.rx, d.netz && d.netz.rx_rate);
        schiebe(v.tx, d.netz && d.netz.tx_rate);
        var io = (d.platte && d.platte.io) || {};
        schiebe(v.rd, io.lesen_rate);
        schiebe(v.wr, io.schreiben_rate);
    }

    /* ── Grafik ────────────────────────────────────────────────────────── */

    /** Verlaufslinie(n) als SVG. `serien` = [{werte, klasse, name}],
     *  `max` = feste Obergrenze (Prozent) oder null (automatisch). Jeder Punkt
     *  traegt einen <title> – der Wert unter dem Mauszeiger. */
    function verlauf(serien, max, fmt) {
        var B = 240, H = 56, P = 3;
        var n = VERLAUF_MAX;
        var hoch = max;
        if (hoch == null) {
            hoch = 0;
            serien.forEach(function (s) { s.werte.forEach(function (w) { if (w > hoch) hoch = w; }); });
            if (hoch <= 0) hoch = 1;
            hoch *= 1.15;
        }
        var x = function (i, len) { return B - (len - 1 - i) * (B / (n - 1)); };
        var y = function (w) { return H - P - (Math.min(w, hoch) / hoch) * (H - 2 * P); };
        var inhalt = '';
        serien.forEach(function (s) {
            var w = s.werte;
            if (!w.length) return;
            var pts = w.map(function (v, i) { return x(i, w.length).toFixed(1) + ',' + y(v).toFixed(1); });
            if (s.flaeche) {
                inhalt += '<polygon class="jv-load-area ' + s.klasse + '" points="'
                    + x(0, w.length).toFixed(1) + ',' + (H - P) + ' ' + pts.join(' ') + ' '
                    + B + ',' + (H - P) + '"/>';
            }
            inhalt += '<polyline class="jv-load-line ' + s.klasse + '" points="' + pts.join(' ') + '"/>';
        });
        // Trefferflaechen je Zeitpunkt (breiter als die Linie) fuer den Tooltip.
        var len = 0;
        serien.forEach(function (s) { if (s.werte.length > len) len = s.werte.length; });
        var schritt = B / (n - 1);
        for (var i = 0; i < len; i++) {
            var alter = (len - 1 - i) * TAKT_MS / 1000;
            var txt = serien.map(function (s) {
                var v = s.werte[i - (len - s.werte.length)];
                return (s.name ? s.name + ': ' : '') + fmt(v);
            }).join(' · ');
            txt += ' (' + (alter ? T('load.ago', 'vor {n} s').replace('{n}', String(alter))
                                 : T('load.now', 'jetzt')) + ')';
            inhalt += '<rect class="jv-load-hit" x="' + (x(i, len) - schritt / 2).toFixed(1)
                + '" y="0" width="' + schritt.toFixed(1) + '" height="' + H + '"><title>'
                + esc(txt) + '</title></rect>';
        }
        return '<svg class="jv-load-spark" viewBox="0 0 ' + B + ' ' + H + '" preserveAspectRatio="none"'
            + ' role="img" aria-label="' + esc(T('load.history', 'Verlauf der letzten 2 Minuten')) + '">'
            + '<line class="jv-load-base" x1="0" y1="' + (H - P) + '" x2="' + B + '" y2="' + (H - P) + '"/>'
            + inhalt + '</svg>';
    }

    function balken(p, klein) {
        var w = Math.max(0, Math.min(100, Number(p) || 0));
        return '<div class="jv-load-meter' + (klein ? ' klein' : '') + '"><div class="jv-load-meter-fill'
            + (w >= 90 ? ' kritisch' : w >= 70 ? ' hoch' : '') + '" style="width:' + w + '%"></div></div>';
    }

    function legende(eintraege) {
        return '<div class="jv-load-leg">' + eintraege.map(function (e) {
            return '<span><i class="jv-load-dot ' + e.klasse + '"></i>' + esc(e.name)
                + ' <b>' + esc(e.wert) + '</b></span>';
        }).join('') + '</div>';
    }

    function kachel(titel, wert, rest) {
        return '<div class="jv-load-tile"><div class="jv-load-tile-h"><span>' + esc(titel)
            + '</span><b>' + esc(wert) + '</b></div>' + rest + '</div>';
    }

    function zeichnen() {
        var d = _letzter, v = _verlauf;
        if (!d || !v || !_kasten) return;
        var body = _kasten.querySelector('.jv-load-body');
        if (!body) return;

        var cpu = d.cpu || {}, mem = d.speicher || {}, net = d.netz || {};
        var pl = d.platte || {}, io = pl.io || {};

        var kerne = (cpu.je_kern || []).map(function (k, i) {
            return '<div class="jv-load-core" title="' + esc(T('load.core', 'Kern {n}')
                .replace('{n}', String(i))) + ': ' + esc(prozent(k)) + '"><div style="height:'
                + Math.max(0, Math.min(100, k)) + '%"></div></div>';
        }).join('');

        var tCpu = kachel(T('load.cpu', 'CPU'), prozent(cpu.prozent),
            verlauf([{ werte: v.cpu, klasse: 's1', flaeche: true }], 100, prozent)
            + '<div class="jv-load-cores">' + kerne + '</div>'
            + '<div class="jv-load-sub">' + esc(T('load.cores', '{n} Kerne').replace('{n}', String(cpu.kerne || 0)))
            + ((cpu.last && cpu.last.length)
                ? ' · ' + esc(T('load.loadavg', 'Last 1/5/15 min')) + ' ' + esc(cpu.last.map(function (x) { return zahl(x, 2); }).join(' / ')) : '')
            + '</div>');

        var tMem = kachel(T('load.mem', 'Arbeitsspeicher'), prozent(mem.prozent),
            verlauf([{ werte: v.mem, klasse: 's1', flaeche: true }], 100, prozent)
            + balken(mem.prozent)
            + '<div class="jv-load-sub">' + esc(bytes(mem.belegt)) + ' / ' + esc(bytes(mem.gesamt))
            + (mem.swap_gesamt ? ' · ' + esc(T('load.swap', 'Auslagerung')) + ' '
                + esc(bytes(mem.swap_belegt)) + ' / ' + esc(bytes(mem.swap_gesamt)) : '')
            + '</div>');

        var tNet = kachel(T('load.net', 'Netzwerk'), rate((net.rx_rate || 0) + (net.tx_rate || 0)),
            verlauf([{ werte: v.rx, klasse: 's1', name: T('load.rx', 'Empfangen') },
                     { werte: v.tx, klasse: 's2', name: T('load.tx', 'Gesendet') }], null, rate)
            + legende([{ klasse: 's1', name: T('load.rx', 'Empfangen'), wert: rate(net.rx_rate) },
                       { klasse: 's2', name: T('load.tx', 'Gesendet'), wert: rate(net.tx_rate) }])
            + '<div class="jv-load-sub">' + esc(T('load.since_boot', 'Seit Systemstart'))
            + ': ↓ ' + esc(bytes(net.rx_gesamt)) + ' · ↑ ' + esc(bytes(net.tx_gesamt)) + '</div>');

        var parts = (pl.partitionen || []).map(function (p) {
            return '<div class="jv-load-part"><div class="jv-load-part-h"><span class="jv-load-mono">'
                + esc(p.mount) + '</span><span>' + esc(bytes(p.belegt)) + ' / ' + esc(bytes(p.gesamt))
                + ' · ' + esc(prozent(p.prozent)) + '</span></div>' + balken(p.prozent, true) + '</div>';
        }).join('');
        var tDisk = kachel(T('load.disk', 'Festplatte'),
            io.lesen_rate == null ? '–' : rate((io.lesen_rate || 0) + (io.schreiben_rate || 0)),
            verlauf([{ werte: v.rd, klasse: 's1', name: T('load.read', 'Lesen') },
                     { werte: v.wr, klasse: 's2', name: T('load.write', 'Schreiben') }], null, rate)
            + legende([{ klasse: 's1', name: T('load.read', 'Lesen'), wert: rate(io.lesen_rate) },
                       { klasse: 's2', name: T('load.write', 'Schreiben'), wert: rate(io.schreiben_rate) }])
            + parts);

        var kerneN = Math.max(1, cpu.kerne || 1);
        var zeilen = sortiert(d.prozesse || []).map(function (p) {
            // Balken relativ zur ganzen Maschine: ein voller Balken = alle Kerne.
            var anteil = Math.max(0, Math.min(100, (Number(p.cpu) || 0) / kerneN));
            return '<tr title="' + esc(p.cmd || p.name) + '">'
                + '<td class="jv-pkg-r jv-load-rang">' + p._rang + '</td>'
                + '<td><div class="jv-pkg-n">' + esc(p.name) + '</div>'
                + (p.cmd ? '<div class="jv-load-cmd">' + esc(p.cmd) + '</div>' : '') + '</td>'
                + '<td class="jv-pkg-r jv-load-mono">' + esc(p.pid) + '</td>'
                + '<td class="jv-load-mono">' + esc(p.user) + '</td>'
                + '<td class="jv-load-cpucell"><div class="jv-load-cpuwert">' + esc(prozent(p.cpu)) + '</div>'
                + balken(anteil, true) + '</td>'
                + '<td class="jv-pkg-r">' + esc(bytes(p.rss)) + '</td>'
                + '<td class="jv-pkg-r">' + esc(p.threads) + '</td></tr>';
        }).join('');

        var meta = esc(d.host || '') + ' · ' + esc(zeitpunkt(d.erzeugt_am))
            + ' · ' + esc(T('load.procs_total', '{n} Prozesse').replace('{n}', String(d.prozesse_gesamt || 0)));

        // Kopfzellen nach dem Muster des Paket-Fensters (syspackages.js):
        // Pfeil an der aktiven Spalte, aria-sort fuer Vorleseprogramme.
        var th = function (sp, txt, klasse) {
            var aktiv = _sortSpalte === sp;
            return '<th class="jv-load-sort ' + (klasse || '') + '" data-sort="' + sp
                + '" tabindex="0" role="button" title="' + esc(T('load.sort', 'Nach dieser Spalte sortieren'))
                + '" aria-sort="' + (aktiv ? (_sortAb ? 'descending' : 'ascending') : 'none') + '">'
                + esc(txt) + (aktiv ? (_sortAb ? ' ▾' : ' ▴') : '') + '</th>';
        };

        // Das Neuzeichnen ersetzt die Tabelle: Fokus und Rollstand der
        // Prozessliste merken, sonst verliert die Tastatur alle 3 s ihren
        // Platz und die Liste springt nach oben.
        var fokus = document.activeElement && _kasten.contains(document.activeElement)
            && document.activeElement.getAttribute('data-sort');
        var rolle = body.querySelector('.jv-pkg-scroll');
        var rollOben = rolle ? rolle.scrollTop : 0;
        var bodyOben = body.scrollTop;

        body.innerHTML = '<div class="jv-pkg-meta">' + meta + '</div>'
            + '<div class="jv-load-grid">' + tCpu + tMem + tNet + tDisk + '</div>'
            + '<div class="jv-load-top-h">' + esc(T('load.top', 'Die {n} Prozesse mit der höchsten CPU-Last')
                .replace('{n}', String((d.prozesse || []).length))) + '</div>'
            + '<div class="jv-pkg-scroll"><table class="jv-pkg-tab jv-load-tab"><thead><tr>'
            + th('rang', '#', 'jv-pkg-r')
            + th('name', T('load.col_proc', 'Prozess'))
            + th('pid', 'PID', 'jv-pkg-r')
            + th('user', T('load.col_user', 'Benutzer'))
            + th('cpu', T('load.col_cpu', 'CPU'))
            + th('rss', T('load.col_mem', 'Speicher'), 'jv-pkg-r')
            + th('threads', T('load.col_threads', 'Threads'), 'jv-pkg-r')
            + '</tr></thead><tbody>' + zeilen + '</tbody></table></div>'
            + '<div class="jv-pkg-fuss">' + esc(T('load.hint',
                'CPU je Prozess wie bei „top“: 100 % = ein voll ausgelasteter Kern. Der Balken zeigt den Anteil an der ganzen Maschine. Gemessen über {s} s, aktualisiert alle {t} s, solange dieses Fenster offen ist.')
                .replace('{s}', String(d.fenster_s || '')).replace('{t}', String(TAKT_MS / 1000)))
            + '</div>';
        setzeLive(T('load.live', 'live'), false);
        var rolle2 = body.querySelector('.jv-pkg-scroll');
        if (rolle2) rolle2.scrollTop = rollOben;
        body.scrollTop = bodyOben;
        if (fokus) {
            var h = body.querySelector('th[data-sort="' + fokus + '"]');
            if (h) h.focus();
        }
    }

    function umsortieren(sp) {
        if (!sp) return;
        if (_sortSpalte === sp) _sortAb = !_sortAb;
        else { _sortSpalte = sp; _sortAb = sp !== 'rang' && !!ZAHL_SPALTEN[sp]; }
        zeichnen();
    }

    /** Sortiert eine Kopie der Serverliste. Jeder Eintrag behaelt seinen
     *  CPU-Rang (`_rang`) – '#' bedeutet damit immer "Platz nach CPU",
     *  gleich wonach gerade sortiert ist. */
    function sortiert(liste) {
        var s = _sortSpalte, ab = _sortAb;
        var kopie = liste.map(function (p, i) {
            var q = {}; for (var k in p) q[k] = p[k];
            q._rang = i + 1;
            return q;
        });
        kopie.sort(function (a, b) {
            var r;
            if (s === 'rang') r = a._rang - b._rang;
            else if (ZAHL_SPALTEN[s]) r = (Number(a[s]) || 0) - (Number(b[s]) || 0);
            else r = String(a[s] || '').localeCompare(String(b[s] || ''), undefined,
                                                      { numeric: true, sensitivity: 'base' });
            // Gleichstand braucht keinen eigenen Brecher: `sort` ist stabil
            // (ES2019), und die Kopie steht in Serverfolge – gleich grosse
            // Zeilen bleiben damit in CPU-Rang-Folge und springen nicht.
            return ab ? -r : r;
        });
        return kopie;
    }

    function zeitpunkt(iso) {
        try {
            return new Date(iso).toLocaleTimeString(undefined,
                { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        } catch (e) { return String(iso || ''); }
    }

    /* ── Start ─────────────────────────────────────────────────────────── */

    function pruefe() {
        var t = token();
        if (!t) { _admin = false; anzeigeAusstatten(); return Promise.resolve(false); }
        return fetch('/api/me', { headers: { 'Authorization': 'Bearer ' + t } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                _admin = !!(d && d.is_admin);
                if (!anzeigeAusstatten()) ausstattenSpaeter();
                return _admin;
            })
            // Ohne belegten Admin-Status bleibt die Anzeige ohne Klick.
            .catch(function () { return false; });
    }

    window.JarvisSysLoad = { pruefe: pruefe, oeffnen: oeffnen, schliessen: schliessen };

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', pruefe);
    } else {
        pruefe();
    }

    window.addEventListener('jarvis-lang-changed', function () {
        anzeigeAusstatten();
        if (offen() && _letzter) zeichnen();
    });
})();
