/**
 * Weitere Protokolle unter Einstellungen -> Protokolle (nur lesen).
 *
 *   journal  – Dienst-Journal (GET /api/logs/journal, ueber den Root-Broker)
 *   csp      – CSP-Verstoesse (GET /api/security/csp, Feld "berichte")
 *   updates  – Update-Verlauf (GET /api/logs/updates)
 *   ssh      – SSH-Anmeldungen (GET /api/logs/ssh, ueber den Root-Broker)
 *   fixes    – Selbstkorrekturen des Agenten (GET /api/logs/code_fixes)
 *   abh      – Abhaengigkeitspruefung (GET /api/logs/abhaengigkeiten)
 *
 * Wie beim Sicherheitsprotokoll: Inhalte NUR per textContent (Journalzeilen,
 * Pfade und Kontonamen stammen teils von aussen), ein Fehler bleibt stehen,
 * und eine Broker-Antwort ohne Ergebnis wird als Klartext gezeigt – eine leere
 * Tabelle saehe aus wie "nichts passiert".
 */
window.Protokolle = (function () {
    'use strict';

    var gebunden = {};
    var letzte = {};          // je Abschnitt die zuletzt gezeichneten Daten

    function $(id) { return document.getElementById(id); }

    function T(k, f) {
        var v = window.t ? window.t(k) : k;
        return (v && v !== k) ? v : f;
    }

    function token() {
        return window.authToken || (window.JarvisSitzung && window.JarvisSitzung.token());
    }

    function zeit(wert) {
        if (wert === undefined || wert === null || wert === '') return '—';
        var d = typeof wert === 'number' ? new Date(wert * 1000) : new Date(wert);
        if (isNaN(d.getTime())) return String(wert);
        var lang = window._lang === 'en' ? 'en-GB' : 'de-DE';
        try { return d.toLocaleString(lang, { dateStyle: 'short', timeStyle: 'medium' }); }
        catch (e) { return String(wert); }
    }

    function fehler(name, text) {
        var el = $('plog-' + name + '-fehler');
        if (!el) return;
        el.textContent = text || '';
        el.style.display = text ? 'block' : 'none';
    }

    function status(name, teile) {
        var el = $('plog-' + name + '-status');
        if (!el) return;
        el.textContent = (teile || []).filter(Boolean).join(' · ');
    }

    function zaehler(name, n, gesamt) {
        var el = $('plog-' + name + '-count');
        if (!el) return;
        var t = T('telemetry.sprot_count', '{n} Einträge').replace('{n}', n);
        if (gesamt !== undefined && gesamt > n) {
            t += ' · ' + T('plog.von_gesamt', 'von {n}').replace('{n}', gesamt);
        }
        el.textContent = t;
    }

    function badge(text, stufe) {
        var s = document.createElement('span');
        s.className = 'sprot-art sprot-art-' + (stufe || 'neutral');
        s.textContent = text;
        return s;
    }

    function zeile(zellen, warn) {
        var tr = document.createElement('tr');
        zellen.forEach(function (z) {
            var td = document.createElement('td');
            if (z && z.klasse) td.className = z.klasse;
            var inhalt = z && Object.prototype.hasOwnProperty.call(z, 'inhalt') ? z.inhalt : z;
            if (inhalt instanceof window.Node) td.appendChild(inhalt);
            else td.textContent = (inhalt === undefined || inhalt === null || inhalt === '') ? '—' : String(inhalt);
            tr.appendChild(td);
        });
        if (warn) tr.className = 'sprot-zeile-warn';
        return tr;
    }

    function fuellen(name, zeilen, leerText) {
        var tbody = $('plog-' + name + '-tbody');
        if (!tbody) return;
        tbody.textContent = '';
        if (!zeilen.length) {
            var spalten = ($('plog-' + name + '-table') || {}).querySelectorAll
                ? $('plog-' + name + '-table').querySelectorAll('thead th').length : 1;
            var tr = document.createElement('tr');
            var td = document.createElement('td');
            td.colSpan = spalten || 1;
            td.className = 'audit-empty';
            td.textContent = leerText;
            tr.appendChild(td);
            tbody.appendChild(tr);
            return;
        }
        zeilen.forEach(function (tr) { tbody.appendChild(tr); });
    }

    async function hole(url) {
        var r = await fetch(url, { headers: { 'Authorization': 'Bearer ' + token() } });
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
    }

    function wert(id) { return (($(id) || {}).value || '').trim(); }

    // ── Quellen ────────────────────────────────────────────────────────────
    var QUELLEN = {
        journal: {
            url: function () {
                var p = new URLSearchParams({
                    einheit: wert('plog-journal-einheit') || 'jarvis',
                    stufe: wert('plog-journal-stufe'),
                    zeitraum: wert('plog-journal-zeitraum') || '24h'
                });
                var s = wert('plog-journal-suche');
                if (s) p.set('suche', s);
                return '/api/logs/journal?' + p.toString();
            },
            zeichnen: function (d) {
                var liste = d.eintraege || [];
                zaehler('journal', liste.length);
                status('journal', [d.gekappt ? T('plog.gekappt', 'Ausgabe gekappt: {n} Zeichen fehlen')
                    .replace('{n}', d.gekappt) : '']);
                fuellen('journal', liste.map(function (e) {
                    return zeile([{ inhalt: zeit(e.zeit), klasse: 'audit-ts' }, e.prozess,
                                  { inhalt: e.text, klasse: 'plog-text' }]);
                }), T('plog.journal.leer', 'Keine Meldungen in diesem Zeitraum.'));
            }
        },
        csp: {
            url: function () { return '/api/security/csp'; },
            zeichnen: function (d) {
                var liste = d.berichte || [];
                zaehler('csp', liste.length);
                status('csp', [T('plog.csp.modus', 'Modus: {m}').replace('{m}',
                    T('plog.csp.modus_' + (d.modus || ''), d.modus || '—'))]);
                fuellen('csp', liste.map(function (e) {
                    var q = e.quelle ? e.quelle + (e.zeile ? ':' + e.zeile : '') : '';
                    return zeile([{ inhalt: zeit(e.ts), klasse: 'audit-ts' },
                                  { inhalt: e.seite, klasse: 'audit-args' }, e.direktive,
                                  { inhalt: e.blockiert, klasse: 'audit-args' },
                                  { inhalt: q, klasse: 'audit-args' },
                                  e.anzahl_seit_start || '—', e.browser]);
                }), T('plog.csp.leer', 'Keine Verstöße gemeldet.'));
            }
        },
        updates: {
            url: function () { return '/api/logs/updates'; },
            zeichnen: function (d) {
                var st = d.stand || {};
                status('updates', [st.hash ? T('plog.updates.aktuell', 'Aktueller Stand: {h} vom {d} – {t}')
                    .replace('{h}', st.hash).replace('{d}', zeit(st.datum)).replace('{t}', st.titel || '') : '']);
                var liste = d.eintraege || [];
                zaehler('updates', liste.length);
                fuellen('updates', liste.map(function (e) {
                    var fehl = e.art === 'update_knopf' && !e.ok;
                    var name = T('plog.updates.art_' + e.art, e.art);
                    var stand = e.vorher ? e.vorher + ' → ' + (e.nachher || '?') : (e.nachher || '');
                    var det = document.createElement('div');
                    if (e.titel) det.appendChild(document.createTextNode(e.titel));
                    if (e.fehler) det.appendChild(document.createTextNode((e.titel ? ' · ' : '') + e.fehler));
                    if (e.art === 'stand_geaendert' && e.vorgespult === false) {
                        det.appendChild(document.createTextNode(' · ' + T('plog.updates.nicht_vorgespult',
                            'Kein Vorspulen (Historie umgeschrieben oder zurückgesetzt)')));
                    }
                    if (e.commits && e.commits.length) {
                        var ul = document.createElement('ul');
                        ul.className = 'plog-commits';
                        e.commits.forEach(function (c) {
                            var li = document.createElement('li');
                            li.textContent = c.hash + ' ' + c.titel;
                            ul.appendChild(li);
                        });
                        if (e.gekappt) {
                            var li2 = document.createElement('li');
                            li2.textContent = T('plog.updates.weitere', '… und weitere');
                            ul.appendChild(li2);
                        }
                        det.appendChild(ul);
                    }
                    return zeile([{ inhalt: zeit(e.ts), klasse: 'audit-ts' },
                                  badge(name, fehl ? 'warn' : (e.art === 'erfasst' ? 'neutral' : 'ok')),
                                  { inhalt: stand, klasse: 'audit-ts' },   // Hash bricht sonst um
                                  e.benutzer_anzeige || e.benutzer || '',
                                  { inhalt: det, klasse: 'plog-text' }], fehl);
                }), T('plog.updates.leer', 'Noch kein Eintrag – der Verlauf beginnt mit dem nächsten Dienststart.'));
            }
        },
        ssh: {
            url: function () {
                var p = new URLSearchParams({ tage: wert('plog-ssh-tage') || '7' });
                var a = wert('plog-ssh-art');
                if (a) p.set('art', a);
                return '/api/logs/ssh?' + p.toString();
            },
            zeichnen: function (d) {
                var liste = d.eintraege || [];
                var n = d.anzahl || {};
                var summe = (n.angenommen || 0) + (n.fehlgeschlagen || 0) + (n.unbekannt || 0);
                zaehler('ssh', liste.length, d.art ? (n[d.art] || 0) : summe);
                status('ssh', [T('plog.ssh.summe', 'Im Zeitraum: {a} angenommen, {f} fehlgeschlagen, {u} mit unbekanntem Benutzer')
                    .replace('{a}', n.angenommen || 0).replace('{f}', n.fehlgeschlagen || 0)
                    .replace('{u}', n.unbekannt || 0)]);
                fuellen('ssh', liste.map(function (e) {
                    var warn = e.art !== 'angenommen';
                    return zeile([{ inhalt: zeit(e.zeit), klasse: 'audit-ts' },
                                  badge(T('plog.ssh.' + e.art, e.art), warn ? 'warn' : 'ok'),
                                  e.konto, e.ip, e.methode,
                                  { inhalt: e.schluessel, klasse: 'audit-args' }], warn);
                }), T('plog.ssh.leer', 'Keine SSH-Anmeldungen in diesem Zeitraum.'));
            }
        },
        fixes: {
            url: function () { return '/api/logs/code_fixes'; },
            zeichnen: function (d) {
                var liste = d.eintraege || [];
                zaehler('fixes', liste.length, d.anzahl);
                status('fixes', []);
                fuellen('fixes', liste.map(function (e) {
                    return zeile([{ inhalt: e.datum, klasse: 'audit-ts' },
                                  { inhalt: e.datei, klasse: 'audit-args' },
                                  { inhalt: e.grund, klasse: 'plog-text' },
                                  { inhalt: e.backup, klasse: 'audit-args' }, e.deployt]);
                }), T('plog.fixes.leer', 'Der Agent hat bisher keinen Programmcode korrigiert.'));
            }
        },
        abh: {
            url: function () { return '/api/logs/abhaengigkeiten'; },
            zeichnen: function (d) {
                if (!d.vorhanden) {
                    zaehler('abh', 0);
                    status('abh', []);
                    fuellen('abh', [], T('plog.abh.leer', 'Noch keine Prüfung gelaufen.'));
                    return;
                }
                var z = d.zustand || {};
                var teile = [T('plog.abh.stand', 'Geprüft: {z}').replace('{z}', zeit(z.zeit))];
                if (z.fehler) teile.push(T('plog.abh.fehler', 'Fehler: {f}').replace('{f}', z.fehler));
                else teile.push(T('plog.abh.ok', 'ohne Fehler'));
                if (d.alter_s > 2 * 86400) {
                    teile.push(T('plog.abh.alt', 'Achtung: die letzte Prüfung ist {n} Tage alt')
                        .replace('{n}', Math.floor(d.alter_s / 86400)));
                }
                status('abh', teile);
                var zeilen = [];
                // nurKennung: die Liste traegt Befund-Kennungen (GHSA-…, PYSEC-…),
                // keine Pakete – sie gehoeren in "Details", nicht unter "Paket".
                function bereich(key, text, liste, warn, nurKennung) {
                    (liste || []).forEach(function (e) {
                        var paket = '', det = '';
                        if (nurKennung && typeof e === 'string') {
                            det = e;
                        } else if (typeof e === 'string') {
                            var i = e.indexOf(' ');
                            paket = i > 0 ? e.slice(0, i) : e;
                            det = i > 0 ? e.slice(i + 1) : '';
                        } else if (e && typeof e === 'object') {
                            paket = e.paket || '';
                            det = [e.version, e.ziel ? '→ ' + e.ziel : '', e.id,
                                   e.behoben_in ? T('plog.abh.behoben', 'behoben in {v}').replace('{v}', e.behoben_in) : '']
                                .filter(Boolean).join(' · ');
                        }
                        zeilen.push(zeile([badge(T(key, text), warn ? 'warn' : 'neutral'),
                                           { inhalt: paket, klasse: 'audit-args' },
                                           { inhalt: det, klasse: 'audit-args' }], warn));
                    });
                }
                bereich('plog.abh.offen', 'Offene Lücke', z.offen, true);
                bereich('plog.abh.zurueckgesetzt', 'Zurückgesetzt', z.zurueckgesetzt, true);
                bereich('plog.abh.unerfuellt', 'Anforderung nicht erfüllt', z.unerfuellt_danach || z.unerfuellt, true);
                bereich('plog.abh.geaendert', 'Angehoben', z.geaendert, false);
                bereich('plog.abh.ueber_grenze', 'Über der Grenze', z.ueber_grenze, false);
                bereich('plog.abh.ausgenommen', 'Bewusst ausgenommen', z.ausgenommen, false, true);
                zaehler('abh', zeilen.length);
                fuellen('abh', zeilen, T('plog.abh.sauber', 'Keine Befunde – alle Bibliotheken ohne bekannte offene Lücke.'));
            }
        }
    };

    async function laden(name) {
        var q = QUELLEN[name];
        if (!q) return;
        try {
            var d = await hole(q.url());
            if (d && d.ok === false) {
                fehler(name, d.error || T('plog.unbekannt', 'Unbekannter Fehler'));
                return;
            }
            fehler(name, '');
            letzte[name] = d;
            q.zeichnen(d);
        } catch (e) {
            fehler(name, T('telemetry.sprot_ladefehler', 'Das Protokoll konnte nicht geladen werden ({s}).')
                .replace('{s}', e.message));
        }
    }

    function binden(name) {
        if (gebunden[name]) return;
        gebunden[name] = true;
        var r = $('plog-' + name + '-refresh');
        if (r) r.addEventListener('click', function () { laden(name); });
        var a = $('plog-' + name + '-apply');
        if (a) a.addEventListener('click', function () { laden(name); });
        var body = $('plog-' + name + '-body');
        if (body) {
            body.querySelectorAll('select').forEach(function (s) {
                s.addEventListener('change', function () { laden(name); });
            });
            body.querySelectorAll('input[type="text"]').forEach(function (i) {
                i.addEventListener('keydown', function (e) { if (e.key === 'Enter') laden(name); });
            });
        }
    }

    document.addEventListener('jarvis-lang-changed', function () {
        Object.keys(letzte).forEach(function (n) { QUELLEN[n].zeichnen(letzte[n]); });
    });

    return {
        init: function (name) { binden(name); laden(name); },
        _quellen: QUELLEN
    };
})();
