/* ═══════════════════════════════════════════════════════════════════
   SQL-Assistent (/sql) – Benutzerseite
   ───────────────────────────────────────────────────────────────────
   Drei Karten: Frage -> gepruefte SQL-Abfrage · Schema durchsuchen
   (Treffer -> Tabellendetail) · Join-Pfad zwischen zwei Tabellen.

   BERECHTIGUNG: jeder Endpunkt haengt serverseitig an der Freigabe. Was
   eine Anfrage sieht, ist die SCHEMA-AUSWAHL oben auf der Seite (Feld
   `schemata`, serverseitig mit den vorhandenen Schemata geschnitten) – seit
   2026-11-07 ohne Wissensgruppen. Die Pruefung hier ist reine
   Benutzerfuehrung – ohne Freigabe geht es zurueck ins Portal statt auf eine
   Seite voller 403-Meldungen.

   AUSWAHL: gemerkt je Benutzer im Browser. Ohne gemerkte Auswahl sind auf
   DIESER Seite alle Schemata gewaehlt – wer /sql oeffnet, will fragen (im
   Chat ist die Vorgabe dagegen "kein Schema", siehe sqlschemafilter.js).

   ALLES, WAS VOM SERVER KOMMT, WIRD MASKIERT (esc) – Tabellen- und
   Spaltennamen, Kommentare und das SQL stammen aus fremden Schema-Dateien
   bzw. aus einer Modellantwort.

   Der Pruefstatus steht OBEN am Ergebnis, mit Zeichen UND Text: ein
   ungeprueftes SQL darf nicht wie ein geprueftes aussehen. Deshalb kippt
   jede Bearbeitung des SQL-Feldes die Anzeige auf "Geaendert – noch nicht
   geprueft", bis "Syntax pruefen" denselben Text erneut geprueft hat.

   SYNTAX: geprueft wird serverseitig (backend/sql_syntax.py) – automatisch
   bei jeder erzeugten Abfrage, auf Knopfdruck fuer bearbeitetes oder
   eigenes SQL (/api/sql/pruefen). "Nicht verfuegbar" ist eine eigene Stufe,
   kein "in Ordnung".

   VERLAUF (wie /sap, rein im Browser, je Benutzer): Frage, Dialekt,
   gewaehlte Schemata, Praefix und das erzeugte SQL samt Pruefung. Ein Klick
   uebernimmt den Eintrag und prueft das SQL gegen den HEUTIGEN Stand neu –
   ohne Modell. Ergebnisdaten gibt es keine (das SQL wird nie ausgefuehrt).
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    var TOKEN_KEYS = window.JarvisSitzung.tokenSchluessel();
    var DIALEKTE = ['allgemein', 'postgresql', 'mysql', 'mariadb', 'oracle', 'mssql', 'sqlite',
                    'db2', 'hana', 'snowflake', 'bigquery', 'teradata'];
    var _status = null;
    var _laeuft = false;
    // Hat der BENUTZER einen Dialekt gewaehlt? Ohne die Unterscheidung galt der
    // Wert der ersten Zeichnung (vor dem Statusabruf: "allgemein") als Wahl,
    // und die Vorgabe des Administrators kam nie an (UI-Waechter, 2026-11-07).
    var _dialektGewaehlt = false;
    var _auswahl = null;   // Set der gewaehlten Schema-Kennungen (null = noch nicht geladen)
    // Schema-PRAEFIX: eine Ablage kann mehrere Datenbankschemata enthalten
    // (z. B. ALT. und NEU.). '' = alle. Gemerkt je Benutzer wie die Auswahl.
    var _praefix = null;
    var HIST_MAX = 25;
    // Text, auf den sich die angezeigte Pruefung bezieht (null = keine Pruefung)
    var _geprueftSql = null;
    // Zeitstempel des Verlaufseintrags, zu dem das angezeigte Ergebnis gehoert
    var _histTs = null;
    var _prueftGerade = false;

    function $(id) { return document.getElementById(id); }
    function token() {
        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            var v = localStorage.getItem(TOKEN_KEYS[i]);
            if (v) return v;
        }
        return '';
    }
    function kopf(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function T(k, fb, werte) {
        var v = '';
        try { v = window.t ? window.t(k) : ''; } catch (e) { v = ''; }
        if (!v || v === k) v = fb;
        if (werte) Object.keys(werte).forEach(function (n) { v = v.split('{' + n + '}').join(String(werte[n])); });
        return v;
    }
    function toPortal() { window.location.replace('/portal'); }
    // Ein Fehler bleibt stehen (man muss ihn lesen koennen), ein Erfolg geht.
    function melde(id, text, art) {
        var e = $(id);
        if (!e) return;
        e.textContent = text || '';
        // Farbe ueber Klassen (je Thema gemischt, siehe sql.html) – ein
        // Inline-var(--danger) haelt den Kontrast in keinem Thema.
        e.classList.toggle('is-fehler', art === 'fehler');
        e.classList.toggle('is-ok', art === 'ok');
        if (e._tm) clearTimeout(e._tm);
        if (art === 'ok') e._tm = setTimeout(function () { e.textContent = ''; }, 3500);
    }
    // FastAPI meldet 4xx in `detail`, unsere Endpunkte in `error`; eine
    // Antwort ohne JSON (Proxy-Seite) darf kein "Unexpected token <" werden.
    // "Failed to fetch" ist der rohe Text des Browsers, wenn GAR KEINE Antwort
    // kam – ohne Ziel und ohne Zeit nicht zuzuordnen (gemeldet 2026-11-08).
    // Die Meldung nennt Pfad und Uhrzeit; die Abfrage-Parameter nicht.
    function netzfehler(url) {
        return function () {
            var zeit = new Date().toLocaleTimeString();
            throw new Error(T('sql.net_error', 'Keine Antwort vom Server ({pfad}, {zeit} Uhr) – Verbindung prüfen und erneut versuchen.',
                { pfad: String(url).split('?')[0], zeit: zeit }));
        };
    }
    function hole(url, opt) {
        return fetch(url, Object.assign({ headers: kopf({ 'Content-Type': 'application/json' }) }, opt || {}))
            .catch(netzfehler(url))
            .then(function (r) {
                return r.json().catch(function () { return {}; }).then(function (d) {
                    if (r.status === 401) { toPortal(); throw new Error(''); }
                    if (!r.ok || d.ok === false) {
                        var err = new Error((d && (d.error || d.detail)) || ('HTTP ' + r.status));
                        err.daten = d; err.status = r.status;
                        throw err;
                    }
                    return d;
                });
            });
    }

    /* ── Klappkarten ───────────────────────────────────────────────────── */
    function klappInit() {
        document.querySelectorAll('.sq-card[data-klapp] > .sq-card-head').forEach(function (h) {
            function um() {
                var karte = h.parentNode;
                var zu = karte.classList.toggle('is-zu');
                h.setAttribute('aria-expanded', zu ? 'false' : 'true');
            }
            h.addEventListener('click', function (e) {
                if (e.target.closest('button, input, select, label, a')) return;
                um();
            });
            h.addEventListener('keydown', function (e) {
                if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); um(); }
            });
        });
    }

    /* ── Status / Schema-Auswahl ───────────────────────────────────────── */
    function speicherSchluessel() {
        var u = '';
        try { u = window.JarvisSitzung.benutzer() || ''; } catch (e) { u = ''; }
        return 'jarvis_sql_schemata_' + (u || 'anon');
    }
    function auswahlLaden(schemata) {
        var ids = schemata.map(function (x) { return x.id; });
        var gemerkt = null;
        try { gemerkt = JSON.parse(localStorage.getItem(speicherSchluessel()) || 'null'); } catch (e) { gemerkt = null; }
        if (!Array.isArray(gemerkt)) return new Set(ids);
        return new Set(gemerkt.filter(function (x) { return ids.indexOf(x) >= 0; }));
    }
    function auswahlMerken() {
        try { localStorage.setItem(speicherSchluessel(), JSON.stringify(Array.from(_auswahl || []))); } catch (e) { }
    }
    function gewaehlt() { return Array.from(_auswahl || []); }

    function praefixSchluessel() { return speicherSchluessel().replace('_schemata_', '_praefix_'); }
    // Datenbankschemata der GEWAEHLTEN Ablagen, Objekte summiert
    function praefixListe() {
        var summe = {};
        ((_status && _status.schemata) || []).forEach(function (q) {
            if (!_auswahl || !_auswahl.has(q.id)) return;
            (q.praefixe || []).forEach(function (p) {
                summe[p.name] = (summe[p.name] || 0) + (p.objekte || 0);
            });
        });
        return Object.keys(summe).sort().map(function (n) { return { name: n, objekte: summe[n] }; });
    }
    function zeichnePraefixe() {
        var sel = $('sq-praefix'), lbl = $('sq-praefix-lbl');
        if (!sel) return;
        if (_praefix === null) {
            try { _praefix = localStorage.getItem(praefixSchluessel()) || ''; } catch (e) { _praefix = ''; }
        }
        var liste = praefixListe();
        var namen = liste.map(function (p) { return p.name; });
        if (namen.indexOf(_praefix) < 0) _praefix = '';
        // Ein einziges Datenbankschema: nichts zu waehlen
        var zeigen = liste.length > 1;
        sel.classList.toggle('hidden', !zeigen);
        if (lbl) lbl.classList.toggle('hidden', !zeigen);
        sel.innerHTML = '<option value="">' + esc(T('sql.prefix_all', 'alle')) + '</option>' + liste.map(function (p) {
            return '<option value="' + esc(p.name) + '">' + esc(p.name) + ' (' + esc(String(p.objekte)) + ')</option>';
        }).join('');
        sel.value = zeigen ? _praefix : '';
    }
    function praefixWahl() { var sel = $('sq-praefix'); return sel && !sel.classList.contains('hidden') && sel.value ? [sel.value] : []; }
    function praefixSetzen(name) {
        _praefix = name || '';
        try { localStorage.setItem(praefixSchluessel(), _praefix); } catch (e) { }
        zeichnePraefixe();
    }
    function schemataParam() { return '&schemata=' + encodeURIComponent(gewaehlt().join(',')); }

    function zeichneQuellen() {
        var bar = $('sq-schemata'), el = $('sq-quellen');
        if (!_status) return;
        var q = _status.schemata || [];
        if (el) {
            el.innerHTML = !_status.vorhanden ? '<span class="sq-warn">' + esc(T('sql.no_graph',
                'Es gibt noch keinen Schema-Graphen. Ein Administrator lädt Schema-Dateien unter Einstellungen → SQL-Assistent hoch.')) + '</span>'
                : !gewaehlt().length && q.length ? '<span class="sq-warn">' + esc(T('sql.choose_schema',
                    'Bitte oben mindestens ein Schema auswählen.')) + '</span>'
                : (_status.stand ? esc(T('sql.stand', 'Stand {d}', { d: _status.stand })) : '');
        }
        if (!bar) return;
        if (!q.length) {
            bar.innerHTML = '<span class="sq-warn">' + esc(T('sql.no_schema',
                'Es ist noch kein Schema angelegt. Ein Administrator legt Schemata unter Einstellungen → SQL-Assistent an.')) + '</span>';
            return;
        }
        bar.innerHTML = '<span class="sq-lbl">' + esc(T('sql.schemas', 'Schemata:')) + '</span>' + q.map(function (x) {
            var an = _auswahl && _auswahl.has(x.id);
            return '<label class="sq-schema' + (an ? ' is-an' : '') + '"><input type="checkbox" data-schema="'
                + esc(x.id) + '"' + (an ? ' checked' : '') + '>' + esc(x.name)
                + ' <span class="sq-schema-n">' + esc(T('sql.n_tables', '{n} Tabellen', { n: x.tabellen })) + '</span></label>';
        }).join('');
        bar.querySelectorAll('input[data-schema]').forEach(function (cb) {
            cb.addEventListener('change', function () {
                var id = cb.getAttribute('data-schema');
                if (cb.checked) _auswahl.add(id); else _auswahl.delete(id);
                auswahlMerken();
                zeichneQuellen();
                zeichneDialekte();
                zeichnePraefixe();
                knopfZustand();
                pruefKnopfZustand();
            });
        });
    }

    // Der Dialekt gehoert zum SCHEMA (Einstellungen → SQL-Assistent, im
    // Container des Schemas): vorgeschlagen wird der des ersten gewaehlten –
    // bis der Benutzer selbst einen waehlt.
    function dialektVorgabe() {
        var gew = ((_status && _status.schemata) || []).filter(function (x) { return _auswahl && _auswahl.has(x.id); });
        return (gew[0] && gew[0].dialekt) || 'allgemein';
    }
    function zeichneDialekte() {
        var sel = $('sq-dialekt');
        if (!sel) return;
        var vorgabe = dialektVorgabe();
        var akt = _dialektGewaehlt ? sel.value : vorgabe;
        sel.innerHTML = DIALEKTE.map(function (d) {
            var name = d === 'allgemein' ? T('sql.dialect_generic', 'allgemein (Standard-SQL)') : d;
            return '<option value="' + esc(d) + '">' + esc(name) + '</option>';
        }).join('');
        sel.value = DIALEKTE.indexOf(akt) >= 0 ? akt : vorgabe;
    }

    function ladeStatus() {
        return hole('/api/sql/status').then(function (d) {
            _status = d;
            _auswahl = auswahlLaden(d.schemata || []);
            zeichneQuellen();
            zeichneDialekte();
            zeichnePraefixe();
            var fm = $('sq-frage');
            if (fm && d.frage_max) fm.setAttribute('maxlength', String(d.frage_max));
            knopfZustand();
            pruefKnopfZustand();
            histZeichnen();
        }).catch(function (e) {
            if (e && e.message) melde('sq-frage-status', e.message, 'fehler');
        });
    }

    /* ── Frage -> SQL ──────────────────────────────────────────────────── */
    // EIN Praedikat fuer Aussehen und Verhalten des Knopfs (Register: zwei
    // Bedingungen fuer dieselbe Frage laufen auseinander).
    function darfFragen() {
        var f = $('sq-frage');
        return !_laeuft && !!(f && f.value.trim()) && !!(_status && _status.vorhanden
            && gewaehlt().length);
    }
    function knopfZustand() {
        var b = $('sq-los');
        if (!b) return;
        var ok = darfFragen();
        b.disabled = !ok;
        b.title = ok ? '' : _laeuft ? T('sql.running', 'Die Frage wird bearbeitet …')
            : !(_status && _status.vorhanden) ? T('sql.no_graph_short', 'Noch kein Schema-Graph vorhanden.')
            : !gewaehlt().length ? T('sql.choose_schema', 'Bitte oben mindestens ein Schema auswählen.')
            : T('sql.need_question', 'Bitte zuerst eine Frage eingeben.');
    }

    function fragen() {
        if (!darfFragen()) return;
        var frage = $('sq-frage').value.trim();
        _laeuft = true;
        knopfZustand();
        $('sq-spin').classList.remove('hidden');
        melde('sq-frage-status', T('sql.running', 'Die Frage wird bearbeitet …'));
        $('sq-ergebnis').classList.add('hidden');
        hole('/api/sql/frage', { method: 'POST', body: JSON.stringify({ frage: frage, dialekt: $('sq-dialekt').value, schemata: gewaehlt(), praefixe: praefixWahl() }) })
            .then(function (d) {
                melde('sq-frage-status', '');
                zeichneErgebnis(d);
                histNeu(frage, d);
            })
            .catch(function (e) { melde('sq-frage-status', (e && e.message) || T('sql.error', 'Fehler'), 'fehler'); })
            .then(function () {
                _laeuft = false;
                $('sq-spin').classList.add('hidden');
                knopfZustand();
            });
    }

    function dialektName(d) {
        return !d || d === 'allgemein' ? T('sql.dialect_generic', 'allgemein (Standard-SQL)') : d;
    }
    // Pill, Syntaxzeile und Befundliste aus EINER Pruefung (Rueckgabe von
    // /api/sql/frage oder /api/sql/pruefen – dieselbe Form, _sql_pruefung_antwort).
    function zeichnePruefung(pr, dialekt) {
        pr = pr || {};
        var syn = pr.syntax || {};
        var dn = dialektName(syn.dialekt || dialekt);
        var pill = $('sq-pill');
        var unbelegt = pr.unbelegte_joins || [];
        if (!pr.ok) {
            pill.className = 'sq-pill is-bad';
            pill.textContent = '✗ ' + T('sql.not_checked', 'Prüfung nicht bestanden – diese Abfrage bitte nicht verwenden');
        } else if (unbelegt.length) {
            // Gueltig, aber ueber eine Verknuepfung ohne Beleg im Schema: eigener
            // Zustand – mit ZEICHEN und TEXT, nicht nur Farbe.
            pill.className = 'sq-pill is-warn';
            pill.textContent = '⚠ ' + T('sql.checked_warn', 'Gültig, aber {n} Verknüpfung(en) ohne Beleg im Schema – bitte fachlich prüfen',
                { n: unbelegt.length });
        } else if (!syn.verfuegbar) {
            // Nur gegen das Schema geprueft: darf nicht wie "alles geprueft" aussehen
            pill.className = 'sq-pill is-warn';
            pill.textContent = '⚠ ' + T('sql.checked_no_syntax', 'Gegen das Schema geprüft ({t} Tabellen, {s} Spalten) – Syntax nicht geprüft',
                { t: (pr.tabellen || []).length, s: pr.spalten_geprueft || 0 });
        } else {
            pill.className = 'sq-pill is-ok';
            pill.textContent = '✓ ' + T('sql.checked', 'Geprüft: nur lesend, {t} Tabellen und {s} Spalten im Schema vorhanden – nicht ausgeführt',
                { t: (pr.tabellen || []).length, s: pr.spalten_geprueft || 0 });
        }
        var sz = $('sq-syntax');
        if (sz) {
            sz.textContent = !syn.verfuegbar ? '– ' + T('sql.syntax_none', 'Syntax nicht geprüft – der Syntaxprüfer ist auf dem Server nicht installiert')
                : syn.ok === false ? '✗ ' + T('sql.syntax_bad', 'Syntaxfehler ({d})', { d: dn })
                : syn.ersatz ? '✓ ' + T('sql.syntax_ersatz', 'Syntax als Standard-SQL geprüft – für {d} gibt es keinen eigenen Prüfer', { d: dn })
                : '✓ ' + T('sql.syntax_ok', 'Syntax in Ordnung ({d})', { d: dn });
        }
        var bef = $('sq-befunde');
        var zeilen = (pr.fehler || []).slice();
        if (pr.ok) unbelegt.forEach(function (u) {
            zeilen.push(T('sql.join_unbelegt', 'Verknüpfung ohne Beleg im Schema: {b}', { b: u }));
        });
        (syn.hinweise || []).forEach(function (h) {
            var ort = h.zeile ? h.zeile + ':' + (h.spalte || '') + ' ' : '';
            zeilen.push(T('sql.syntax_ersatz_hint', 'Hinweis des Standard-SQL-Prüfers (kann eine Besonderheit von {d} sein): {t}',
                { d: dn, t: ort + (h.text || '') + (h.stelle ? ' („' + h.stelle + '“)' : '') }));
        });
        bef.innerHTML = zeilen.map(function (f) { return '<li>' + esc(f) + '</li>'; }).join('');
        bef.classList.toggle('hidden', !zeilen.length);
    }
    // Anzeige "nicht (mehr) geprueft" – nach einer Bearbeitung oder fuer ein
    // leeres Feld. Neutrale Pill, keine Befunde von frueher.
    function zeichneUngeprueft(geaendert) {
        var pill = $('sq-pill');
        pill.className = 'sq-pill';
        pill.textContent = '● ' + (geaendert ? T('sql.changed', 'Geändert – noch nicht geprüft')
            : T('sql.unchecked', 'Noch nicht geprüft'));
        var sz = $('sq-syntax');
        if (sz) sz.textContent = '';
        $('sq-befunde').innerHTML = '';
        $('sq-befunde').classList.add('hidden');
    }
    function sqlFeld() { return $('sq-sql'); }
    function sqlSetzen(text) {
        var f = sqlFeld();
        f.value = text || '';
        // Hoehe nach Zeilenzahl (jsdom rechnet kein Layout, rows schon)
        f.rows = Math.max(6, Math.min(30, (f.value.match(/\n/g) || []).length + 2));
    }

    function zeichneErgebnis(d) {
        var pr = d.pruefung || {};
        zeichnePruefung(pr, d.dialekt);
        sqlSetzen(d.sql || '');
        _geprueftSql = d.sql || '';
        var erk = $('sq-erklaerung');
        erk.innerHTML = d.erklaerung ? '<b>' + esc(T('sql.explanation', 'Erklärung')) + ':</b> ' + esc(d.erklaerung) : '';
        var ann = $('sq-annahmen');
        var a = (d.annahmen || '').trim();
        ann.innerHTML = a && a.toLowerCase() !== 'keine' && a.toLowerCase() !== '- keine'
            ? '<b>' + esc(T('sql.assumptions', 'Annahmen')) + ':</b> ' + esc(a) : '';
        // Woraus der Assistent sein Hintergrundwissen hatte (Begleitdokumente)
        var hw = d.hauswissen || [];
        $('sq-hauswissen').innerHTML = hw.length ? '<b>' + esc(T('sql.hauswissen', 'Hintergrund aus den Hausdokumenten')) + ':</b> '
            + hw.map(function (h) { return esc(h.titel) + ' (' + esc(T('sql.abschnitt', 'Abschnitt {n}', { n: h.nr })) + ')'; }).join(', ') : '';
        zeichneHinweise(d);
        zeichneBasis(d.tabellen_kontext || [], d.verbinder || []);
        $('sq-ergebnis').classList.remove('hidden');
        pruefKnopfZustand();
    }

    // Woher der Ausschnitt kam: eingegrenzt, gemischt oder zusammengelegt
    function zeichneHinweise(d) {
        var box = $('sq-hinweise');
        if (!box) return;
        var h = [];
        // Am SQL, nicht am Ausschnitt: der stammt fast immer aus mehreren
        // Schemata, das SQL selten (DEV 2026-11-08: 2 von 8) – ein staendiger
        // Hinweis wird ueberlesen.
        var pk = d.praefixe_sql || {};
        var namen = Object.keys(pk);
        if ((d.praefixe || []).length) {
            h.push('<div>' + esc(T('sql.prefix_used', 'Eingegrenzt auf das Datenbankschema {p}.', { p: d.praefixe.join(', ') })) + '</div>');
        } else if (namen.length > 1) {
            h.push('<div><b>' + esc(T('sql.prefix_mixed_lbl', 'Mehrere Datenbankschemata')) + ':</b> '
                + esc(T('sql.prefix_mixed', 'Die Abfrage verbindet Tabellen aus {liste}. Ist nur eines gemeint, die Frage darauf eingrenzen:',
                    { liste: namen.map(function (n) { return n + ' (' + pk[n] + ')'; }).join(', ') }))
                + ' ' + namen.map(function (n) {
                    return '<button type="button" class="sq-btn" data-praefix="' + esc(n) + '">'
                        + esc(T('sql.prefix_ask', 'nur {p} fragen', { p: n })) + '</button>';
                }).join(' ') + '</div>');
        }
        var gw = d.gleichwertig || [];
        if (gw.length) {
            h.push('<div><b>' + esc(T('sql.same_lbl', 'Zusammengelegt')) + ':</b> ' + gw.map(function (g) {
                return esc(T('sql.same', '{s} zeigt alle Spalten von {t}', { s: g.sicht, t: g.tabelle }));
            }).join('; ') + '. ' + esc(T('sql.same_hint', 'Im Ausschnitt stand nur die Sicht.')) + '</div>');
        }
        box.innerHTML = h.join('');
        box.querySelectorAll('button[data-praefix]').forEach(function (b) {
            b.addEventListener('click', function () {
                praefixSetzen(b.getAttribute('data-praefix'));
                fragen();
            });
        });
    }

    function kopieren() {
        var text = sqlFeld().value || '';
        if (!text) return;
        var fertig = function () { melde('sq-kopier-status', T('sql.copied', 'In die Zwischenablage kopiert.'), 'ok'); };
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text).then(fertig, function () {
                melde('sq-kopier-status', T('sql.copy_failed', 'Kopieren nicht möglich – bitte markieren und kopieren.'), 'fehler');
            });
        } else {
            melde('sq-kopier-status', T('sql.copy_failed', 'Kopieren nicht möglich – bitte markieren und kopieren.'), 'fehler');
        }
    }

    /* ── SQL pruefen (bearbeitet oder eigenes) ──────────────────────────── */
    // EIN Praedikat fuer Knopf-Aussehen und -Verhalten (Register).
    function darfPruefen() {
        return !_prueftGerade && !!(sqlFeld() && sqlFeld().value.trim())
            && !!(_status && _status.vorhanden && gewaehlt().length);
    }
    function pruefKnopfZustand() {
        var b = $('sq-pruefen');
        if (!b) return;
        var ok = darfPruefen();
        b.disabled = !ok;
        b.title = ok ? T('sql.check_title', 'Prüft das SQL im Feld auf Syntax und gegen die gewählten Schemata – ohne es auszuführen')
            : _prueftGerade ? T('sql.checking', 'Wird geprüft …')
            : !(_status && _status.vorhanden) ? T('sql.no_graph_short', 'Noch kein Schema-Graph vorhanden.')
            : !gewaehlt().length ? T('sql.choose_schema', 'Bitte oben mindestens ein Schema auswählen.')
            : T('sql.need_sql', 'Bitte zuerst ein SQL eingeben.');
    }
    function sqlGeaendert() {
        var v = sqlFeld().value;
        if (_geprueftSql === null || v !== _geprueftSql) zeichneUngeprueft(_geprueftSql !== null);
        pruefKnopfZustand();
    }
    function sqlPruefen(still) {
        if (!darfPruefen()) {
            if (!still && !(sqlFeld().value || '').trim()) melde('sq-kopier-status', T('sql.need_sql', 'Bitte zuerst ein SQL eingeben.'), 'fehler');
            return Promise.resolve(null);
        }
        var text = sqlFeld().value;
        var dialekt = $('sq-dialekt').value;
        _prueftGerade = true;
        pruefKnopfZustand();
        melde('sq-kopier-status', T('sql.checking', 'Wird geprüft …'));
        return hole('/api/sql/pruefen', { method: 'POST', body: JSON.stringify({ sql: text, dialekt: dialekt, schemata: gewaehlt() }) })
            .then(function (d) {
                melde('sq-kopier-status', '');
                // Wurde waehrend der Pruefung weiter getippt, gilt das Ergebnis
                // fuer einen ANDEREN Text – dann bleibt "geaendert" stehen.
                if (sqlFeld().value !== text) return d;
                _geprueftSql = text;
                zeichnePruefung(d.pruefung, d.dialekt);
                // Eigenes SQL: die Grundlage sind die gefundenen Tabellen
                if (!$('sq-basis').innerHTML) zeichneBasis((d.pruefung || {}).tabellen || [], []);
                histPruefungMerken(text, dialekt, d.pruefung);
                return d;
            })
            .catch(function (e) { melde('sq-kopier-status', (e && e.message) || T('sql.error', 'Fehler'), 'fehler'); return null; })
            .then(function (d) {
                _prueftGerade = false;
                pruefKnopfZustand();
                return d;
            });
    }
    // "Eigenes SQL pruefen": leeres Feld, keine Erklaerung von frueher
    function eigenesSql() {
        _histTs = null;
        _geprueftSql = null;
        sqlSetzen('');
        ['sq-erklaerung', 'sq-annahmen', 'sq-hauswissen', 'sq-hinweise', 'sq-basis'].forEach(function (id) { $(id).innerHTML = ''; });
        zeichneUngeprueft(false);
        $('sq-ergebnis').classList.remove('hidden');
        pruefKnopfZustand();
        sqlFeld().focus();
    }
    function zeichneBasis(namen, glieder) {
        $('sq-basis').innerHTML = (namen || []).map(function (n) {
            var g = (glieder || []).indexOf(n) >= 0;
            return '<span class="sq-chip' + (g ? ' is-glied' : '') + '" data-tabelle="' + esc(n) + '" tabindex="0" role="button"'
                + (g ? ' title="' + esc(T('sql.connector', 'als Join-Glied über den Graphen ergänzt')) + '"' : '') + '>'
                + esc(n) + (g ? ' ↔' : '') + '</span>';
        }).join('');
    }

    /* ── Verlauf (rein im Browser, je Benutzer – Bauform wie /sap) ──────── */
    function histSchluessel() { return speicherSchluessel().replace('_schemata_', '_verlauf_'); }
    function histLesen() {
        try {
            var l = JSON.parse(localStorage.getItem(histSchluessel()) || '[]');
            return Array.isArray(l) ? l : [];
        } catch (e) { return []; }
    }
    function histSchreiben(liste) {
        try { localStorage.setItem(histSchluessel(), JSON.stringify(liste.slice(0, HIST_MAX))); } catch (e) { }
        histZeichnen();
    }
    function schemaNamen(ids) {
        var map = {};
        ((_status && _status.schemata) || []).forEach(function (x) { map[x.id] = x.name; });
        return (ids || []).map(function (id) { return map[id] || id; });
    }
    // Nur was zum Wiederherstellen noetig ist – keine Zeiten, kein Verlauf der Runden.
    function histErgebnis(d) {
        return {
            sql: d.sql || '', dialekt: d.dialekt || '', pruefung: d.pruefung || null,
            erklaerung: d.erklaerung || '', annahmen: d.annahmen || '', hauswissen: d.hauswissen || [],
            tabellen_kontext: d.tabellen_kontext || [], verbinder: d.verbinder || [],
            praefixe: d.praefixe || [], praefixe_sql: d.praefixe_sql || {}, gleichwertig: d.gleichwertig || []
        };
    }
    function histNeu(frage, d) {
        var ids = gewaehlt();
        var e = {
            ts: Date.now(), q: frage || '', dialekt: $('sq-dialekt').value, schemata: ids,
            schemata_namen: schemaNamen(ids), praefix: praefixWahl()[0] || '',
            erg: histErgebnis(d), bearbeitet: false
        };
        _histTs = e.ts;
        var l = histLesen();
        l.unshift(e);
        histSchreiben(l);
    }
    // Ein geprueftes, BEARBEITETES SQL ersetzt das des aktuellen Eintrags (der
    // Verlauf haelt den letzten Arbeitsstand); eigenes SQL ohne Eintrag legt
    // einen neuen an.
    function histPruefungMerken(text, dialekt, pr) {
        var l = histLesen();
        var i = -1;
        for (var k = 0; k < l.length; k++) { if (l[k].ts === _histTs) { i = k; break; } }
        if (i < 0) {
            histNeu('', { sql: text, dialekt: dialekt, pruefung: pr, tabellen_kontext: (pr && pr.tabellen) || [] });
            return;
        }
        var e = l[i];
        var erg = e.erg || {};
        if (erg.sql !== text) e.bearbeitet = true;
        erg.sql = text;
        erg.pruefung = pr;
        erg.dialekt = dialekt;
        e.erg = erg;
        histSchreiben(l);
    }
    // Loescht GENAU EINEN Eintrag – ueber den Zeitstempel, nicht den Index
    // (ein zweiter Tab kann den Verlauf verschoben haben, Lehre aus /sap).
    function histLoeschen(ts) {
        var l = histLesen().filter(function (e) { return e.ts !== ts; });
        if (_histTs === ts) _histTs = null;
        histSchreiben(l);
    }
    function histZeichnen() {
        var box = $('sq-hist-list');
        if (!box) return;
        var l = histLesen();
        if (!l.length) {
            box.innerHTML = '<div class="sq-hist-empty">' + esc(T('sql.hist_empty', 'Noch keine Fragen gestellt.')) + '</div>';
            return;
        }
        var delLbl = esc(T('sup.hist_del', 'Eintrag löschen'));
        box.innerHTML = l.map(function (e) {
            var titel = e.q || T('sql.hist_own', 'Eigenes SQL');
            var meta = [new Date(e.ts).toLocaleString(), (e.schemata_namen || []).join(', '),
                dialektName(e.dialekt)].concat(e.praefix ? [e.praefix] : [])
                .concat(e.bearbeitet ? [T('sql.hist_edited', 'bearbeitet')] : []).filter(Boolean).join(' · ');
            // MUELLEIMER, kein ×: der Eintrag wird dauerhaft entfernt.
            return '<div class="sq-hist-item" data-ts="' + esc(String(e.ts)) + '">'
                + '<div class="sq-hist-text"><div class="sq-hist-q">' + esc(titel) + '</div>'
                + '<div class="sq-hist-meta">' + esc(meta) + '</div></div>'
                + '<button type="button" class="sq-hist-del" data-ts="' + esc(String(e.ts)) + '" title="' + delLbl
                + '" aria-label="' + delLbl + '">' + window.JarvisIcons.trash() + '</button></div>';
        }).join('');
        box.querySelectorAll('.sq-hist-del').forEach(function (b) {
            b.addEventListener('click', function (ev) {
                // stopPropagation PFLICHT (wie /sap): sonst uebernaehme der Eintrag
                // darunter, und der Dokument-Zuhoerer schloesse das Feld.
                ev.stopPropagation();
                ev.preventDefault();
                histLoeschen(Number(b.getAttribute('data-ts')));
            });
        });
        box.querySelectorAll('.sq-hist-item').forEach(function (el) {
            el.addEventListener('click', function () { histUebernehmen(Number(el.getAttribute('data-ts'))); });
        });
    }
    // Uebernimmt einen Eintrag: Einstellungen, Frage und Ergebnis – und prueft
    // das SQL gegen den HEUTIGEN Stand neu (kein Modell, die Pruefung von damals
    // kann veraltet sein). Erzeugt wird NICHT neu.
    function histUebernehmen(ts) {
        var e = null;
        histLesen().forEach(function (x) { if (x.ts === ts) e = x; });
        if (!e) return;
        $('sq-hist-panel').classList.add('hidden');
        var vorhanden = ((_status && _status.schemata) || []).map(function (x) { return x.id; });
        var fehlen = [];
        var gew = [];
        (e.schemata || []).forEach(function (id, i) {
            if (vorhanden.indexOf(id) >= 0) gew.push(id);
            else fehlen.push((e.schemata_namen || [])[i] || id);
        });
        _auswahl = new Set(gew);
        auswahlMerken();
        if (e.dialekt && DIALEKTE.indexOf(e.dialekt) >= 0) {
            _dialektGewaehlt = true;
            zeichneDialekte();
            $('sq-dialekt').value = e.dialekt;
        } else {
            zeichneDialekte();
        }
        zeichneQuellen();
        praefixSetzen(e.praefix || '');
        $('sq-frage').value = e.q || '';
        knopfZustand();
        _histTs = e.ts;
        var erg = e.erg || {};
        zeichneErgebnis(Object.assign({}, erg, { dialekt: e.dialekt }));
        var datum = new Date(e.ts).toLocaleString();
        if (fehlen.length) {
            melde('sq-frage-status', T('sql.hist_missing', 'Diese Schemata aus dem Eintrag gibt es nicht mehr: {liste}',
                { liste: fehlen.join(', ') }), 'fehler');
        } else {
            melde('sq-frage-status', T('sql.hist_loaded', 'Aus dem Verlauf vom {d} übernommen – geprüft wird gegen den heutigen Stand.', { d: datum }));
        }
        pruefKnopfZustand();
        if ((erg.sql || '').trim()) sqlPruefen(true);
    }

    /* ── Suche und Tabellendetail ──────────────────────────────────────── */
    function suchen() {
        var q = ($('sq-suchfeld').value || '').trim();
        if (!q) { melde('sq-such-status', T('sql.need_terms', 'Bitte einen Suchbegriff eingeben.'), 'fehler'); return; }
        melde('sq-such-status', T('sql.searching', 'Suche …'));
        hole('/api/sql/suche?q=' + encodeURIComponent(q) + '&limit=25' + schemataParam()).then(function (d) {
            var tr = d.treffer || [];
            melde('sq-such-status', T('sql.n_hits', '{n} Treffer', { n: tr.length }));
            $('sq-treffer').innerHTML = tr.length ? tr.map(function (t) {
                var meta = (t.art === 'sicht' ? T('sql.view', 'Sicht') : T('sql.table', 'Tabelle'))
                    + ' · ' + T('sql.n_cols', '{n} Spalten', { n: t.spalten_n })
                    + (t.bereich ? ' · ' + T('sql.area', 'Bereich') + ': ' + t.bereich : '')
                    + (t.kommentar ? ' – ' + t.kommentar : '');
                return '<div class="sq-treffer" data-tabelle="' + esc(t.name) + '" tabindex="0" role="button">'
                    + '<div class="sq-treffer-name">' + esc(t.name) + '</div>'
                    + '<div class="sq-treffer-meta">' + esc(meta) + '</div></div>';
            }).join('') : '<div class="sq-hint">' + esc(T('sql.no_hits', 'Keine Tabelle gefunden.')) + '</div>';
        }).catch(function (e) { melde('sq-such-status', (e && e.message) || '', 'fehler'); });
    }

    function kanteText(k) {
        if (k.art === 'sicht') return T('sql.view_basis', '(Sicht beruht darauf)');
        var bed = (k.paare || []).map(function (p) { return p[0] + ' = ' + p[1]; }).join(', ') || '?';
        return bed + (k.art === 'fk' ? '' : ' (' + T('sql.guessed', 'vermutet') + ')');
    }

    function zeigeTabelle(name) {
        var box = $('sq-detail');
        box.classList.remove('hidden');
        box.innerHTML = '<div class="sq-hint">' + esc(T('sql.loading', 'Lädt …')) + '</div>';
        // Suche aufklappen, damit das Detail sichtbar ist (Klick kommt evtl.
        // aus der Grundlage des Ergebnisses).
        var karte = box.closest('.sq-card');
        if (karte && karte.classList.contains('is-zu')) {
            karte.classList.remove('is-zu');
            var h = karte.querySelector('.sq-card-head');
            if (h) h.setAttribute('aria-expanded', 'true');
        }
        hole('/api/sql/tabelle?name=' + encodeURIComponent(name) + schemataParam()).then(function (d) {
            var t = d.tabelle || {};
            var sp = t.spalten || [];
            var h = '<h3>' + esc(t.name) + '</h3>';
            if (t.kommentar) h += '<div class="sq-hint">' + esc(t.kommentar) + '</div>';
            if (t.bereich) h += '<div class="sq-hint">' + esc(T('sql.area', 'Bereich')) + ': ' + esc(t.bereich) + '</div>';
            // Kuerzung VOR der Liste und beziffert (Register).
            h += '<div class="sq-lbl" style="margin-top:8px">' + esc(t.spalten_gesamt > sp.length
                ? T('sql.cols_cut', 'Spalten ({n} von {g} gezeigt)', { n: sp.length, g: t.spalten_gesamt })
                : T('sql.cols', 'Spalten ({n})', { n: sp.length })) + '</div>';
            h += '<div class="sq-tab-wrap"><table class="sq-tab"><thead><tr><th>' + esc(T('sql.col_name', 'Name'))
                + '</th><th>' + esc(T('sql.col_type', 'Typ')) + '</th><th>' + esc(T('sql.col_key', 'Schlüssel'))
                + '</th><th>' + esc(T('sql.col_desc', 'Beschreibung')) + '</th></tr></thead><tbody>'
                + sp.map(function (s) {
                    return '<tr><td class="sq-mono">' + esc(s.name) + '</td><td class="sq-mono">' + esc(s.typ)
                        + '</td><td>' + (s.pk ? 'PK' : '') + (s.nullable ? '' : (s.pk ? ', ' : '') + 'NOT NULL')
                        + '</td><td>' + esc(s.kommentar) + '</td></tr>';
                }).join('') + '</tbody></table></div>';
            if ((t.raus || []).length) {
                h += '<div class="sq-lbl" style="margin-top:10px">' + esc(T('sql.refs_out', 'Verweist auf ({n})', { n: t.raus_gesamt })) + '</div>'
                    + '<div class="sq-chips" style="margin-top:4px">' + t.raus.map(function (k) {
                        return '<span class="sq-chip" data-tabelle="' + esc(k.ziel) + '" tabindex="0" role="button" title="'
                            + esc(kanteText(k)) + '">' + esc(k.ziel) + '</span>';
                    }).join('') + '</div>';
            }
            if ((t.rein || []).length) {
                h += '<div class="sq-lbl" style="margin-top:10px">' + esc(T('sql.refs_in', 'Wird referenziert von ({n})', { n: t.rein_gesamt })) + '</div>'
                    + '<div class="sq-chips" style="margin-top:4px">' + t.rein.map(function (k) {
                        return '<span class="sq-chip" data-tabelle="' + esc(k.quelle) + '" tabindex="0" role="button" title="'
                            + esc(kanteText(k)) + '">' + esc(k.quelle) + '</span>';
                    }).join('') + '</div>';
            }
            box.innerHTML = h;
        }).catch(function (e) {
            var v = (e && e.daten && e.daten.vorschlaege) || [];
            box.innerHTML = '<div class="sq-warn">' + esc(e && e.daten && e.daten.fehler === 'mehrdeutig'
                ? T('sql.ambiguous', 'Mehrdeutig – bitte mit Schema angeben.')
                : T('sql.not_found', 'Tabelle nicht gefunden.')) + '</div>'
                + (v.length ? '<div class="sq-chips" style="margin-top:6px">' + v.map(function (n) {
                    return '<span class="sq-chip" data-tabelle="' + esc(n) + '" tabindex="0" role="button">' + esc(n) + '</span>';
                }).join('') + '</div>' : '');
        });
    }

    /* ── Join-Pfad ─────────────────────────────────────────────────────── */
    function pfadSuchen() {
        var von = ($('sq-von').value || '').trim(), nach = ($('sq-nach').value || '').trim();
        if (!von || !nach) { melde('sq-pfad-status', T('sql.need_both', 'Bitte beide Tabellen angeben.'), 'fehler'); return; }
        melde('sq-pfad-status', T('sql.searching', 'Suche …'));
        $('sq-pfad').innerHTML = '';
        hole('/api/sql/verbindung?von=' + encodeURIComponent(von) + '&nach=' + encodeURIComponent(nach) + schemataParam()).then(function (d) {
            melde('sq-pfad-status', T('sql.n_steps', '{n} Schritte', { n: (d.schritte || []).length }));
            $('sq-pfad').innerHTML = (d.schritte || []).map(function (s) {
                var txt = s.art === 'sicht' ? s.von + ' – ' + s.nach + ' (' + T('sql.via_view', 'nur über eine Sicht verbunden') + ')'
                    : s.bedingung + (s.art === 'fk' ? '' : ' (' + T('sql.guessed', 'vermutet') + ')');
                return '<div class="sq-treffer" style="cursor:default"><div class="sq-treffer-name">' + esc(txt) + '</div></div>';
            }).join('');
        }).catch(function (e) {
            var d = (e && e.daten) || {};
            var txt = d.fehler === 'kein_pfad' ? T('sql.no_path', 'Kein Weg in höchstens {n} Schritten.', { n: d.max_tiefe || 6 })
                : d.fehler === 'mehrdeutig' ? T('sql.ambiguous_n', '„{n}“ ist mehrdeutig – bitte mit Schema angeben.', { n: d.name || '' })
                : d.fehler === 'nicht_gefunden' ? T('sql.not_found_n', 'Tabelle „{n}“ nicht gefunden.', { n: d.name || '' })
                : (e && e.message) || '';
            melde('sq-pfad-status', txt, 'fehler');
        });
    }

    /* ── Start ─────────────────────────────────────────────────────────── */
    function binde() {
        klappInit();
        var los = $('sq-los'), fr = $('sq-frage'), kp = $('sq-kopieren');
        los.addEventListener('click', fragen);
        fr.addEventListener('input', knopfZustand);
        // Strg/Cmd+Enter sendet; Enter allein bleibt ein Zeilenumbruch.
        fr.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); fragen(); }
        });
        kp.addEventListener('click', kopieren);
        $('sq-pruefen').addEventListener('click', function () { sqlPruefen(false); });
        $('sq-eigenes').addEventListener('click', eigenesSql);
        var sf2 = sqlFeld();
        sf2.addEventListener('input', sqlGeaendert);
        // Strg/Cmd+Enter im SQL-Feld prueft (wie Senden im Fragefeld)
        sf2.addEventListener('keydown', function (e) {
            if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); sqlPruefen(false); }
        });
        // Ein anderer Dialekt ist eine andere Syntax: die Anzeige gilt nicht mehr
        $('sq-dialekt').addEventListener('change', function () {
            if (_geprueftSql !== null) { _geprueftSql = null; zeichneUngeprueft(true); }
        });
        $('sq-hist-btn').addEventListener('click', function (e) {
            e.stopPropagation();
            histZeichnen();
            $('sq-hist-panel').classList.toggle('hidden');
        });
        $('sq-hist-clear').addEventListener('click', function (e) {
            e.stopPropagation();
            try { localStorage.removeItem(histSchluessel()); } catch (err) { }
            _histTs = null;
            histZeichnen();
        });
        // Klick daneben bzw. Escape schliesst das Verlaufsfeld
        document.addEventListener('click', function (e) {
            var p = $('sq-hist-panel');
            if (p && !p.classList.contains('hidden') && !p.contains(e.target)) p.classList.add('hidden');
        });
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Escape') return;
            var p = $('sq-hist-panel');
            if (p && !p.classList.contains('hidden')) p.classList.add('hidden');
        });
        $('sq-dialekt').addEventListener('change', function () { _dialektGewaehlt = true; });
        $('sq-praefix').addEventListener('change', function () { praefixSetzen($('sq-praefix').value); });
        var sf = $('sq-suchfeld');
        $('sq-suchen').addEventListener('click', suchen);
        sf.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); suchen(); } });
        $('sq-pfad-los').addEventListener('click', pfadSuchen);
        ['sq-von', 'sq-nach'].forEach(function (id) {
            $(id).addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); pfadSuchen(); } });
        });
        // Delegiert: Chips und Treffer entstehen erst beim Zeichnen.
        document.addEventListener('click', function (e) {
            var z = e.target.closest ? e.target.closest('[data-tabelle]') : null;
            if (z) zeigeTabelle(z.getAttribute('data-tabelle'));
        });
        document.addEventListener('keydown', function (e) {
            if (e.key !== 'Enter') return;
            var z = e.target.closest ? e.target.closest('[data-tabelle]') : null;
            if (z && z.tagName !== 'INPUT') { e.preventDefault(); zeigeTabelle(z.getAttribute('data-tabelle')); }
        });
        $('sq-portal-btn').addEventListener('click', toPortal);
        $('sq-logout-btn').addEventListener('click', function () {
            if (window.jarvisLogout) { window.jarvisLogout(); return; }
            TOKEN_KEYS.forEach(function (k) { try { localStorage.removeItem(k); } catch (e) { } });
            window.location.replace('/');
        });
        // Sprachwechsel: Dialekt-Liste und Quellenzeile sind JS-Texte, die
        // applyLang() nicht erreicht. Vergleich, weil das Ereignis bei JEDEM
        // applyLang() feuert (Endlosschleifen-Lehre aus /tracks).
        var lang = window._lang;
        window.addEventListener('jarvis-lang-changed', function () {
            if (window._lang === lang) return;
            lang = window._lang;
            zeichneQuellen(); zeichneDialekte(); zeichnePraefixe(); knopfZustand();
            pruefKnopfZustand(); histZeichnen();
        });
    }

    function start() {
        if (!token()) { toPortal(); return; }
        fetch('/api/me', { headers: kopf() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d) { toPortal(); return; }
                // Fail-closed: fehlt `permissions` (aelteres Backend), gilt
                // "nicht freigegeben".
                if (!d.permissions || !d.permissions.schema) { toPortal(); return; }
                $('sq-app').classList.remove('hidden');
                binde();
                zeichneDialekte();
                knopfZustand();
                return ladeStatus();
            })
            .catch(function () { toPortal(); });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }

    // Fuer Tests und die Konsole
    window.jarvisSql = {
        ladeStatus: ladeStatus, fragen: fragen, suchen: suchen, zeigeTabelle: zeigeTabelle,
        pfadSuchen: pfadSuchen, _darfFragen: darfFragen, _gewaehlt: gewaehlt, _praefixWahl: praefixWahl,
        sqlPruefen: sqlPruefen, eigenesSql: eigenesSql, histUebernehmen: histUebernehmen,
        _histLesen: histLesen, _darfPruefen: darfPruefen
    };
})();
