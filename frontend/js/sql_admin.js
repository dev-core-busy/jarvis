/* ═══════════════════════════════════════════════════════════════════════
   Einstellungen → SQL-Assistent: je Schema EIN CONTAINER mit allem, was zu
   ihm gehoert – Name, Dateien (feste Ablage auf dem Server), Einstellungen
   (Dialekt, Dateimuster, Beziehungen, Hoechstzahlen) und Erfassung.
   Daten ueber /api/sql/admin* (nur Admins).

   ⚠ EINSTELLUNGEN UND ERFASSUNG GEHOEREN ZUM SCHEMA (Vorgabe des Betreibers
   2026-11-10): zwei Schemata sind zwei Datenbanken. Fuer alle gemeinsam
   bleiben nur die Leseprozesse des Servers und die Erlaubnis, aus dem Chat
   zu erfassen (Abschnitt "Fuer alle Schemata").

   EIN SCHEMA IST EIN FESTER ORDNER (data/sql_schema_graph/<kennung>/) –
   seit 2026-11-07 ohne freie Ordnerwahl und ohne Wissensgruppen. Die
   Dateien kommen per Ablage (Dateien, ganze Ordner oder ZIP) wie im
   Informationsextraktor von /wissen; nach jedem Hochladen und Loeschen
   startet die Erfassung DIESES Schemas von selbst.

   ⚠ GESPEICHERT WIRD DIE GANZE KONFIGURATION ODER NICHTS – auch ueber den
   Speichern-Knopf in einem Container. Der Server prueft alles und speichert
   bei einem einzigen Fehler NICHTS.

   ⚠ EIN SCHEMA AUS DER LISTE ZU NEHMEN LOESCHT SEINE DATEIEN. Der Server
   verlangt dafuer eine ausdrueckliche Bestaetigung (409 mit der Liste); hier
   wird sie mit Namen und Dateizahl erfragt.

   ⚠ HOCHGELADEN WIRD IN PAKETEN, gefiltert nach den Dateimustern des
   Schemas: ein Bestand von tausenden Dateien und vielen GB laesst sich nicht
   in EINER Anfrage schicken, und Dateien, die der Server ohnehin ablehnt,
   muessen nicht erst uebertragen werden.

   ⚠ DIE VERSTECKTEN DATEIFELDER STEHEN NEBEN DEM ABLAGEFELD, NICHT DARIN:
   ``input.click()`` erzeugt ein Klick-Ereignis, das nach oben laeuft – im
   Ablagefeld haette es dessen Klick-Zweig erneut ausgeloest.

   ⚠ DER ERFASSUNGS-TAKT ZEICHNET DIE CONTAINER NICHT NEU, er traegt den
   Stand in die vorhandenen Elemente ein: sonst verloere ein Feld, in dem
   gerade jemand tippt, alle zwei Sekunden seinen Inhalt. Aus demselben Grund
   behaelt das Nachladen nach Upload, Loeschen und Laufende die noch nicht
   gespeicherten Eingaben (``laden(true)``).
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    var DIALEKTE = ['allgemein', 'postgresql', 'mysql', 'mariadb', 'oracle', 'mssql', 'sqlite',
                    'db2', 'hana', 'snowflake', 'bigquery', 'teradata'];
    var TAKT = 2000;
    // Paketgroesse beim Hochladen: Starlette nimmt hoechstens 1000 Teile je
    // Anfrage an; 200 Dateien bzw. 256 MB halten jede Anfrage ueberschaubar
    // und den Fortschritt fein genug.
    var PAKET_DATEIEN = 200;
    var PAKET_BYTES = 256 * 1024 * 1024;
    var ABGELEHNT_ZEIGEN = 50;

    function $(id) { return document.getElementById(id); }
    function token() { return window.JarvisSitzung.token(); }
    function kopf(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function t(k, fb, werte) {
        var v = '';
        try { v = window.t ? window.t(k) : ''; } catch (e) { v = ''; }
        if (!v || v === k) v = fb;
        if (werte) Object.keys(werte).forEach(function (n) { v = v.split('{' + n + '}').join(String(werte[n])); });
        return v;
    }
    function groesse(b) {
        b = Number(b) || 0;
        if (b >= 1024 * 1024 * 1024) return (b / 1024 / 1024 / 1024).toFixed(1) + ' GB';
        if (b >= 1024 * 1024) return (b / 1024 / 1024).toFixed(1) + ' MB';
        if (b >= 1024) return Math.round(b / 1024) + ' KB';
        return b + ' B';
    }
    // Ein Fehler bleibt stehen (man muss ihn lesen koennen), ein Erfolg geht.
    function status(el, msg, art) {
        if (typeof el === 'string') el = $(el);
        if (!el) return;
        el.textContent = msg || '';
        // Farbe ueber Klassen (je Thema gemischt, style.css) – ein
        // Inline-var(--danger) haelt den Kontrast in keinem Thema.
        el.classList.add('sqadm-st');
        el.classList.toggle('is-fehler', art === 'error');
        el.classList.toggle('is-ok', art === 'ok');
        if (el._tm) clearTimeout(el._tm);
        if (art === 'ok') el._tm = setTimeout(function () { el.textContent = ''; }, 3500);
    }
    function antwort(r) {
        return r.json().catch(function () { return {}; }).then(function (d) {
            if (!r.ok || !d || d.ok === false) {
                var e = new Error((d && (d.error || d.detail)) || ('HTTP ' + r.status));
                e.daten = d; e.status = r.status;
                throw e;
            }
            return d;
        });
    }
    // Netzfehler mit Ziel und Uhrzeit statt des rohen "Failed to fetch"
    // (gemeldet 2026-11-08: die Meldung half niemandem weiter).
    function netzText(url) {
        return t('sqladm.net_error', 'Keine Antwort vom Server ({pfad}, {zeit} Uhr) – Verbindung prüfen und erneut versuchen.',
            { pfad: String(url).split('?')[0], zeit: new Date().toLocaleTimeString() });
    }
    function holen(url, opt) {
        return fetch(url, opt).catch(function () { throw new Error(netzText(url)); });
    }
    function liste(id, eintraege) {
        var el = $(id); if (!el) return;
        el.innerHTML = (eintraege || []).map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('');
    }

    /* ── Dateien aus einer Ablage einsammeln ─────────────────────────────
       Ordner kommen beim Ziehen als Verzeichnis-Eintrag (webkitGetAsEntry),
       beim Auswaehlen ueber webkitdirectory mit webkitRelativePath. In beiden
       Faellen bleibt der RELATIVE PFAD erhalten – die Ordnerstruktur wird auf
       dem Server nachgebildet. */
    function eintragLesen(entry, pfad, out) {
        return new Promise(function (fertig) {
            if (entry.isFile) {
                entry.file(function (f) { out.push({ datei: f, pfad: pfad + f.name }); fertig(); },
                    function () { fertig(); });
                return;
            }
            if (!entry.isDirectory) { fertig(); return; }
            var leser = entry.createReader(), alle = [];
            // readEntries liefert in Stuecken (Chrome: 100 je Aufruf) – bis leer lesen.
            (function weiter() {
                leser.readEntries(function (stueck) {
                    if (!stueck.length) {
                        Promise.all(alle.map(function (e) { return eintragLesen(e, pfad + entry.name + '/', out); }))
                            .then(function () { fertig(); });
                        return;
                    }
                    alle = alle.concat(Array.prototype.slice.call(stueck));
                    weiter();
                }, function () { fertig(); });
            })();
        });
    }
    function ausAblage(dt) {
        var out = [];
        var items = dt && dt.items ? Array.prototype.slice.call(dt.items) : [];
        // webkitGetAsEntry MUSS im drop-Ereignis selbst gerufen werden (danach
        // ist die Ablage leer) – deshalb sofort, nicht in einem then().
        var eintraege = items.map(function (it) {
            return it.kind === 'file' && it.webkitGetAsEntry ? it.webkitGetAsEntry() : null;
        });
        if (eintraege.some(Boolean)) {
            return Promise.all(eintraege.filter(Boolean).map(function (e) { return eintragLesen(e, '', out); }))
                .then(function () { return out; });
        }
        Array.prototype.slice.call((dt && dt.files) || []).forEach(function (f) { out.push({ datei: f, pfad: f.name }); });
        return Promise.resolve(out);
    }
    function ausAuswahl(files) {
        return Array.prototype.slice.call(files || []).map(function (f) {
            return { datei: f, pfad: f.webkitRelativePath || f.name };
        });
    }
    // Welche gesammelten Dateien werden uebertragen? Versteckte Teile (.git,
    // .DS_Store) nie; sonst nur die Dateimuster und ZIP-Archive.
    function auswaehlen(gesammelt, endungen) {
        var nehmen = [], gefiltert = 0;
        (gesammelt || []).forEach(function (g) {
            var teile = String(g.pfad || '').split('/');
            var name = (teile[teile.length - 1] || '').toLowerCase();
            if (teile.some(function (x) { return x.charAt(0) === '.'; })) { gefiltert++; return; }
            var passt = name.slice(-4) === '.zip' || endungen.some(function (e) { return name.slice(-e.length) === e; });
            if (passt) nehmen.push(g); else gefiltert++;
        });
        return { nehmen: nehmen, gefiltert: gefiltert };
    }
    function pakete(nehmen) {
        var out = [], akt = [], bytes = 0;
        nehmen.forEach(function (g) {
            if (akt.length && (akt.length >= PAKET_DATEIEN || bytes + g.datei.size > PAKET_BYTES)) {
                out.push(akt); akt = []; bytes = 0;
            }
            akt.push(g); bytes += g.datei.size;
        });
        if (akt.length) out.push(akt);
        return out;
    }
    function paketBytes(p) { return p.reduce(function (s, g) { return s + g.datei.size; }, 0); }

    function kopie(x) { return JSON.parse(JSON.stringify(x)); }
    function dialektOptionen(akt) {
        return DIALEKTE.map(function (d) {
            return '<option value="' + esc(d) + '"' + (d === akt ? ' selected' : '') + '>' + esc(d === 'allgemein'
                ? t('sql.dialect_generic', 'allgemein (Standard-SQL)') : d) + '</option>';
        }).join('');
    }
    function klappSchluessel(sid) { return 'jarvis_sect_collapse_sqadm-' + sid; }
    // Ergebnis eines Laufs als Wort der Oberflaeche (der Status fuehrt es ohne
    // Umlaute). Ausgeschrieben statt zusammengesetzt: einen zusammengesetzten
    // Schluessel findet kein Waechter, der die Texte gegen i18n.js prueft.
    function ergebnisWort(e) {
        var worte = { fertig: t('sqladm.res_fertig', 'fertig'), unveraendert: t('sqladm.res_unveraendert', 'unverändert'),
                      abgebrochen: t('sqladm.res_abgebrochen', 'abgebrochen'), fehler: t('sqladm.res_fehler', 'Fehler') };
        return Object.prototype.hasOwnProperty.call(worte, e) ? worte[e] : String(e || '');
    }

    var Admin = {
        _gebunden: false,
        _cfg: null,
        _graph: null,
        _dateien: {},        // je Schema {dateien, ordner, bytes}
        _uploadEndungen: {}, // je Schema: was der Server annimmt
        _vorgaben: {},       // Einstellungen eines NEUEN Schemas (vom Server)
        _erfassung: {},
        _vorgemerkt: null,   // wartender Nachlauf: {nur: [Kennungen] | null}
        _schemata: [],       // Formularstand (Arbeitskopie)
        _offen: {},          // je Schema: Dateiliste aufgeklappt?
        _zu: {},             // je Schema: Container zugeklappt?
        _laedt: false,
        _hochladen: {},      // je Schema: laeuft gerade ein Upload?
        _takt: null,
        _lang: null,

        onShow: function () { this._binden(); return this.laden(); },

        _binden: function () {
            if (this._gebunden) return;
            this._gebunden = true;
            var self = this;
            $('sqadm-neu').addEventListener('click', function () {
                self._sammeln();
                self._schemata.push(Object.assign({ id: '', name: '' }, kopie(self._vorgaben || {})));
                self._zeichneSchemata();
                var n = document.querySelectorAll('#sqadm-schemata .sqadm-name');
                if (n.length) n[n.length - 1].focus();
            });
            $('sqadm-save').addEventListener('click', function () { self.speichern('sqadm-status'); });
            $('sqadm-save2').addEventListener('click', function () { self.speichern('sqadm-status2'); });
            var box = $('sqadm-schemata');
            // Delegiert: die Container entstehen erst beim Zeichnen.
            box.addEventListener('click', function (e) {
                var el = e.target.closest ? e.target.closest('[data-akt]') : null;
                if (!el || !box.contains(el)) return;
                var sid = el.getAttribute('data-sid') || '';
                var akt = el.getAttribute('data-akt');
                if (akt === 'klappen') {
                    self._klappen(el.closest('.sqadm-schema'));
                } else if (akt === 'del-schema') {
                    self._sammeln();
                    var i = parseInt(el.getAttribute('data-i'), 10);
                    if (i >= 0 && i < self._schemata.length) self._schemata.splice(i, 1);
                    self._zeichneSchemata();
                    status('sqadm-status', t('sqladm.removed', 'Schema entfernt – mit „Speichern“ übernehmen. Seine Dateien werden dabei gelöscht.'));
                } else if (akt === 'speichern') {
                    self.speichern({ i: parseInt(el.getAttribute('data-i'), 10) });
                } else if (akt === 'erfassen') {
                    self.starten(sid);
                } else if (akt === 'erf-stop') {
                    self.abbrechen(sid);
                } else if (akt === 'waehlen') {
                    self._feld(sid, 'sqadm-fin');
                } else if (akt === 'ordner') {
                    self._feld(sid, 'sqadm-din');
                } else if (akt === 'liste') {
                    self._offen[sid] = !self._offen[sid];
                    self._zeichneBaum(sid);
                } else if (akt === 'del-datei') {
                    self.loeschen(sid, el.getAttribute('data-pfad') || '', el.getAttribute('data-art') || 'datei');
                }
            });
            box.addEventListener('keydown', function (e) {
                if (e.key !== 'Enter' && e.key !== ' ') return;
                var cl = e.target.classList;
                if (cl && cl.contains('sqadm-drop')) {
                    e.preventDefault();
                    self._feld(e.target.getAttribute('data-sid'), 'sqadm-fin');
                } else if (cl && cl.contains('kb-collapse-header')) {
                    e.preventDefault();
                    self._klappen(e.target.closest('.sqadm-schema'));
                }
            });
            // Der Titel des Containers folgt dem Namensfeld.
            box.addEventListener('input', function (e) {
                if (!e.target.classList || !e.target.classList.contains('sqadm-name')) return;
                var karte = e.target.closest('.sqadm-schema');
                var titel = karte && karte.querySelector('.sqadm-titel');
                if (titel) titel.textContent = (e.target.value || '').trim() || t('sqladm.new_schema', 'Neues Schema');
            });
            box.addEventListener('change', function (e) {
                var el = e.target;
                if (!el || !el.classList) return;
                if (el.classList.contains('sqadm-fin') || el.classList.contains('sqadm-din')) {
                    var sid = el.getAttribute('data-sid');
                    var gesammelt = ausAuswahl(el.files);
                    el.value = '';
                    self.hochladen(sid, gesammelt);
                }
            });
            ['dragover', 'dragleave', 'drop'].forEach(function (ev) {
                box.addEventListener(ev, function (e) {
                    var d = e.target.closest ? e.target.closest('.sqadm-drop') : null;
                    if (!d) return;
                    e.preventDefault();
                    var sid = d.getAttribute('data-sid');
                    d.classList.toggle('drag', ev === 'dragover' && !self._hochladen[sid]);
                    if (ev === 'drop' && !self._hochladen[sid]) {
                        ausAblage(e.dataTransfer).then(function (g) { self.hochladen(sid, g); });
                    }
                });
            });
            window.addEventListener('jarvis-lang-changed', function () {
                if (window._lang === self._lang || !self._cfg) return;
                self._lang = window._lang;
                self._sammeln();
                self._zeichne(true);
            });
        },

        _feld: function (sid, klasse) {
            if (!sid || this._hochladen[sid]) return;
            var f = $('sqadm-schemata').querySelector('input.' + klasse + '[data-sid="' + sid + '"]');
            if (f) f.click();
        },

        // ``behalten``: Nachladen nach Upload, Loeschen oder Laufende – Zahlen
        // und Erfassungsstand kommen neu, die noch nicht gespeicherten Eingaben
        // (Name, Einstellungen, neue Schemata) bleiben stehen.
        laden: function (behalten) {
            var self = this;
            if (this._laedt) return Promise.resolve();
            this._laedt = true;
            this._lang = window._lang;
            return holen('/api/sql/admin', { headers: kopf() }).then(antwort).then(function (d) {
                var halten = !!behalten && !!self._cfg
                    && document.querySelectorAll('#sqadm-schemata .sqadm-schema').length > 0;
                if (halten) self._sammeln();
                self._cfg = d.cfg;
                self._graph = d.graph;
                self._dateien = d.dateien || {};
                self._uploadEndungen = (d.upload_endungen && typeof d.upload_endungen === 'object'
                    && !Array.isArray(d.upload_endungen)) ? d.upload_endungen : {};
                self._vorgaben = d.schema_vorgaben || {};
                self._erfassung = d.erfassung || {};
                self._vorgemerkt = d.vorgemerkt || null;
                if (!halten) self._schemata = kopie(d.cfg.schemata || []);
                self._zeichne(halten);
                self._taktPruefen();
            }).catch(function (e) {
                status('sqadm-status', (e && e.message) || t('sqladm.load_failed', 'Laden fehlgeschlagen'), 'error');
            }).then(function () { self._laedt = false; });
        },

        // ── Formular <-> Daten ─────────────────────────────────────────────
        // Je Container EIN Schema samt seinen Einstellungen.
        _sammeln: function () {
            var rows = document.querySelectorAll('#sqadm-schemata .sqadm-schema');
            var out = [];
            rows.forEach(function (row) {
                function feld(kl) { return row.querySelector('.' + kl); }
                out.push({ id: row.getAttribute('data-id') || '',
                           name: (feld('sqadm-name').value || '').trim(),
                           dialekt: feld('sqadm-dialekt').value,
                           dateimuster: (feld('sqadm-muster').value || '').trim(),
                           max_tabellen: Number(feld('sqadm-maxtab').value),
                           max_spalten: Number(feld('sqadm-maxsp').value),
                           fk_ableiten: !!feld('sqadm-fk').checked });
            });
            if (rows.length || !this._schemata) this._schemata = out;
            return out;
        },
        _formCfg: function () {
            return { schemata: this._sammeln(),
                     prozesse: Number($('sqadm-prozesse').value),
                     index_aus_chat: !!$('sqadm-chat').checked };
        },
        // Endungen fuer den Filter VOR dem Hochladen – was der Server fuer
        // DIESES Schema annimmt (gespeichertes Dateimuster + Begleitdokumente),
        // vom Server, damit Filter und Annahme nicht auseinanderlaufen.
        _endungen: function (sid) {
            var vom = this._uploadEndungen && this._uploadEndungen[sid];
            if (Array.isArray(vom) && vom.length) return vom.slice();
            var s = ((this._cfg && this._cfg.schemata) || []).filter(function (x) { return x.id === sid; })[0];
            return String((s && s.dateimuster) || '').split(',').map(function (m) {
                m = m.trim().toLowerCase();
                return m.indexOf('*.') === 0 ? m.slice(1) : '';
            }).filter(Boolean);
        },

        // ── Zeichnen ───────────────────────────────────────────────────────
        _zeichne: function (nurTexte) {
            var c = this._cfg || {};
            if (!nurTexte) {
                $('sqadm-prozesse').value = c.prozesse;
                $('sqadm-chat').checked = !!c.index_aus_chat;
            }
            this._zeichneSchemata();
        },

        _zahlen: function (sid) {
            var z = ((this._graph && this._graph.schemata) || []).filter(function (x) { return x.id === sid; })[0];
            var f = this._dateien[sid] || { dateien: 0, ordner: 0, bytes: 0 };
            var teile = [t('sqladm.files_n', '{n} Dateien ({g})', { n: f.dateien, g: groesse(f.bytes) })];
            if (z && this._graph && this._graph.vorhanden) {
                teile.push(t('sqladm.counts', '{t} Tabellen, {v} Sichten, {s} Spalten im Graphen vom {d}',
                    { t: z.tabellen, v: z.sichten, s: z.spalten, d: this._graph.stand || '?' }));
                if (z.dokumente) teile.push(t('sqladm.docs_n', '{n} Begleitdokumente', { n: z.dokumente }));
            }
            return teile.join(' · ');
        },

        _istZu: function (sid) {
            if (!sid) return false;                    // noch nicht gespeichert: offen
            if (typeof this._zu[sid] === 'boolean') return this._zu[sid];
            var gemerkt = null;
            try { gemerkt = window.localStorage.getItem(klappSchluessel(sid)); } catch (e) { gemerkt = null; }
            return gemerkt === '1';
        },
        // Auf-/Zuklappen am vorhandenen Element (kein Neuzeichnen: die Felder
        // im Container behalten ihren Inhalt).
        _klappen: function (karte) {
            if (!karte) return;
            var kopfEl = karte.querySelector('.kb-collapse-header');
            var rumpf = karte.querySelector('.kb-collapse-body');
            var tog = karte.querySelector('.sk-openclaw-toggle');
            if (!kopfEl || !rumpf) return;
            var zu = rumpf.style.display !== 'none';
            rumpf.style.display = zu ? 'none' : '';
            if (tog) tog.textContent = zu ? '▶' : '▼';
            kopfEl.classList.toggle('is-collapsed', zu);
            kopfEl.setAttribute('aria-expanded', zu ? 'false' : 'true');
            var sid = karte.getAttribute('data-id') || '';
            if (!sid) return;
            this._zu[sid] = zu;
            try { window.localStorage.setItem(klappSchluessel(sid), zu ? '1' : '0'); } catch (e) { /* nur Komfort */ }
        },

        // Die Einstellungen EINES Schemas – stehen in seinem Container.
        _einstHtml: function (s, i) {
            function id(f) { return 'sqadm-f-' + f + '-' + i; }
            return '<div class="sqadm-teil sqadm-einst">'
                + '<h4 class="sqadm-teil-h">' + esc(t('sqladm.sect_settings', 'Einstellungen')) + '</h4>'
                + '<div class="form-group"><label for="' + id('dialekt') + '">' + esc(t('sqladm.dialect', 'SQL-Dialekt der Zieldatenbank')) + '</label>'
                + '<select id="' + id('dialekt') + '" class="config-input sqadm-dialekt">' + dialektOptionen(s.dialekt || 'allgemein') + '</select>'
                + '<span class="kb-hint">' + esc(t('sqladm.dialect_hint', 'In diesem Dialekt schreibt der Assistent die Abfragen zu diesem Schema (Funktionen, LIMIT/TOP, Datumsrechnung). Auf der Seite lässt er sich je Frage ändern.')) + '</span></div>'
                + '<div class="form-group"><label for="' + id('muster') + '">' + esc(t('sqladm.pattern', 'Dateimuster')) + '</label>'
                + '<input type="text" id="' + id('muster') + '" class="config-input sqadm-muster" autocomplete="off" value="' + esc(s.dateimuster == null ? '' : s.dateimuster) + '">'
                + '<span class="kb-hint">' + esc(t('sqladm.pattern_hint', 'Kommagetrennte Endungen, z. B. *.sql,*.ddl,*.yaml. Nur diese Dateien (und ZIP-Archive) werden in dieses Schema hochgeladen und erfasst. .sql/.ddl werden als SQL-DDL gelesen, .yaml/.yml als Objektexport (eine Tabelle oder Sicht je Datei).')) + '</span></div>'
                + '<div class="form-group"><label for="' + id('maxtab') + '">' + esc(t('sqladm.maxtab', 'Höchstzahl Tabellen je Frage')) + '</label>'
                + '<input type="number" id="' + id('maxtab') + '" class="config-input sqadm-maxtab" min="3" max="40" step="1" value="' + esc(s.max_tabellen == null ? '' : s.max_tabellen) + '"></div>'
                + '<div class="form-group"><label for="' + id('maxsp') + '">' + esc(t('sqladm.maxcol', 'Höchstzahl Spalten je Tabelle im Ausschnitt')) + '</label>'
                + '<input type="number" id="' + id('maxsp') + '" class="config-input sqadm-maxsp" min="10" max="200" step="1" value="' + esc(s.max_spalten == null ? '' : s.max_spalten) + '"></div>'
                + '<label class="checkbox-group"><input type="checkbox" class="sqadm-fk"' + (s.fk_ableiten === false ? '' : ' checked') + '><span>'
                + esc(t('sqladm.fk', 'Beziehungen aus Spaltennamen ableiten (z. B. kunde_id → kunde.id, oder eine Spalte, die genau wie der Primärschlüssel einer anderen Tabelle heißt; dem Modell als „vermutet“ gezeigt)')) + '</span></label>'
                + '<div class="sqadm-aktionen"><button type="button" class="btn-primary" data-akt="speichern" data-i="' + i + '">'
                + esc(t('common.save', 'Speichern')) + '</button><span class="sqadm-einst-status"></span></div>'
                + '</div>';
        },

        _zeichneSchemata: function () {
            var self = this;
            var box = $('sqadm-schemata');
            if (!this._schemata.length) {
                box.innerHTML = '<p class="kb-hint">' + esc(t('sqladm.no_schemas',
                    'Noch kein Schema – lege eines an und speichere, dann können Dateien hochgeladen werden.')) + '</p>';
                return;
            }
            var dropText = t('sqladm.drop', 'Dateien, Ordner oder ZIP-Archiv hierher ziehen oder klicken zum Auswählen');
            box.innerHTML = this._schemata.map(function (s, i) {
                var sid = s.id || '';
                var zu = self._istZu(sid);
                // Kennungen nach dem Muster der uebrigen Abschnitte (<x>-hdr /
                // <x>-body): daran haengt das Suchfeld der Einstellungen – es
                // nennt den Abschnitt (= das Schema) zu einer Einstellung und
                // klappt ihn beim Sprung auf.
                var kenn = 'sqadm-s-' + (sid || ('neu' + i));
                var kopfHtml = '<div id="' + esc(kenn) + '-hdr" class="kb-section-header kb-collapse-header' + (zu ? ' is-collapsed' : '') + '" data-akt="klappen"'
                    + ' role="button" tabindex="0" aria-expanded="' + (zu ? 'false' : 'true') + '">'
                    + '<h3 class="sqadm-titel">' + esc(s.name || t('sqladm.new_schema', 'Neues Schema')) + '</h3>'
                    + '<span class="sqadm-kopf-re"><span class="sqadm-kopfinfo"></span>'
                    + '<span class="sk-openclaw-toggle">' + (zu ? '▶' : '▼') + '</span></span></div>';
                var nameHtml = '<div class="sqadm-kopf">'
                    + '<input type="text" class="config-input sqadm-name" maxlength="80" autocomplete="off" value="'
                    + esc(s.name) + '" placeholder="' + esc(t('sqladm.name_ph', 'Name, z. B. ERP-Datenbank')) + '"'
                    + ' aria-label="' + esc(t('sqladm.name', 'Name des Schemas')) + '">'
                    + '<button type="button" class="am-vorg-act" data-akt="del-schema" data-i="' + i + '" title="'
                    + esc(t('sqladm.remove', 'Schema samt Dateien löschen')) + '" aria-label="'
                    + esc(t('sqladm.remove', 'Schema samt Dateien löschen')) + '">' + window.JarvisIcons.trash() + '</button>'
                    + '</div>';
                var auf = '<div class="kb-section sqadm-schema" data-id="' + esc(sid) + '">' + kopfHtml
                    + '<div id="' + esc(kenn) + '-body" class="kb-collapse-body sqadm-koerper"' + (zu ? ' style="display:none"' : '') + '>' + nameHtml;
                if (!sid) {
                    // Noch kein Ordner und nichts zu erfassen – die Einstellungen
                    // lassen sich aber schon mit anlegen.
                    return auf + '<div class="kb-hint">' + esc(t('sqladm.save_first', 'Erst speichern – danach können Dateien hochgeladen werden.')) + '</div>'
                        + self._einstHtml(s, i) + '</div></div>';
                }
                var busy = !!self._hochladen[sid];
                var offen = !!self._offen[sid];
                var endungen = self._endungen(sid).concat(['.zip']).join(', ');
                return auf
                    + '<div class="kb-hint sqadm-zahlen">' + esc(self._zahlen(sid)) + '</div>'
                    + '<div class="sqadm-teil sqadm-dateiteil">'
                    + '<h4 class="sqadm-teil-h">' + esc(t('sqladm.sect_files', 'Dateien')) + '</h4>'
                    + '<div class="sqadm-drop' + (busy ? ' disabled' : '') + '" data-sid="' + esc(sid) + '" data-akt="waehlen"'
                    + ' tabindex="0" role="button" aria-label="' + esc(dropText) + '">'
                    + '<div>' + esc(dropText) + '</div>'
                    + '<div class="sqadm-drop-sub">' + esc(t('sqladm.drop_sub',
                        'Übernommen werden: {e}. Begleitdokumente (.docx, .pdf, .md – Konventionen, SQL-Beispiele) gibt der Assistent je Frage als Hintergrund mit. Gleichnamige Dateien werden ersetzt, danach wird automatisch erfasst.', { e: endungen })) + '</div>'
                    + '<button type="button" class="btn-secondary sqadm-dirbtn" data-akt="ordner" data-sid="' + esc(sid) + '">'
                    + esc(t('sqladm.pick_dir', 'Ordner wählen')) + '</button>'
                    + '</div>'
                    + '<input type="file" class="sqadm-fin" data-sid="' + esc(sid) + '" multiple hidden>'
                    + '<input type="file" class="sqadm-din" data-sid="' + esc(sid) + '" webkitdirectory directory multiple hidden>'
                    + '<div class="vis-progress-wrap sqadm-up" data-sid="' + esc(sid) + '" hidden>'
                    + '<div class="vis-progress-bar"><div class="vis-progress-fill" style="width:0%"></div></div>'
                    + '<span class="vis-progress-text"></span></div>'
                    + '<div class="sqadm-up-status" data-sid="' + esc(sid) + '"></div>'
                    + '<ul class="sqadm-hinweise sqadm-up-fehler" data-sid="' + esc(sid) + '"></ul>'
                    + '<button type="button" class="btn-secondary sqadm-listbtn" data-akt="liste" data-sid="' + esc(sid) + '"'
                    + ' aria-expanded="' + (offen ? 'true' : 'false') + '">'
                    + esc(offen ? t('sqladm.hide_files', 'Dateiliste ausblenden') : t('sqladm.show_files', 'Dateiliste zeigen'))
                    + '</button>'
                    + '<div class="sqadm-baum" data-sid="' + esc(sid) + '"' + (offen ? '' : ' hidden') + '></div>'
                    + '</div>'
                    + self._einstHtml(s, i)
                    // Erfassung DIESES Schemas: der Takt traegt den Stand hier ein.
                    + '<div class="sqadm-teil sqadm-erf" data-sid="' + esc(sid) + '">'
                    + '<h4 class="sqadm-teil-h">' + esc(t('sqladm.index_h', 'Erfassung')) + '</h4>'
                    + '<p class="kb-hint">' + esc(t('sqladm.index_hint', 'Liest die Dateien dieses Schemas und trägt sie in den Graphen ein. Das geschieht nach jedem Hochladen und Löschen von selbst und liest nur neue und geänderte Dateien. Von Hand neu erfassen braucht es nur, wenn Dateien direkt auf dem Server geändert wurden.')) + '</p>'
                    + '<div class="sqadm-erf-stand"></div>'
                    + '<div class="vis-progress-wrap sqadm-erf-fort" hidden>'
                    + '<div class="vis-progress-bar"><div class="vis-progress-fill" style="width:0%"></div></div>'
                    + '<span class="vis-progress-text"></span></div>'
                    + '<div class="sqadm-aktionen">'
                    + '<button type="button" class="btn-primary sqadm-erf-start" data-akt="erfassen" data-sid="' + esc(sid) + '">'
                    + esc(t('sqladm.start', 'Neu erfassen')) + '</button>'
                    + '<button type="button" class="btn-secondary sqadm-erf-stop" data-akt="erf-stop" data-sid="' + esc(sid) + '" style="display:none">'
                    + esc(t('sqladm.stop', 'Abbrechen')) + '</button>'
                    + '<span class="sqadm-erf-status"></span></div>'
                    + '<ul class="sqadm-hinweise sqadm-erf-fehler"></ul>'
                    + '</div>'
                    + '</div></div>';
            }).join('');
            this._schemata.forEach(function (s) { if (s.id && self._offen[s.id]) self._zeichneBaum(s.id); });
            this._zeichneErfassung();
        },

        _zeichneBaum: function (sid) {
            var box = $('sqadm-schemata');
            var el = box.querySelector('.sqadm-baum[data-sid="' + sid + '"]');
            var knopf = box.querySelector('.sqadm-listbtn[data-sid="' + sid + '"]');
            if (!el) return Promise.resolve();
            var offen = !!this._offen[sid];
            el.hidden = !offen;
            if (knopf) {
                knopf.setAttribute('aria-expanded', offen ? 'true' : 'false');
                knopf.textContent = offen ? t('sqladm.hide_files', 'Dateiliste ausblenden') : t('sqladm.show_files', 'Dateiliste zeigen');
            }
            if (!offen) return Promise.resolve();
            el.innerHTML = '<p class="kb-hint">' + esc(t('sqladm.loading', 'Lädt …')) + '</p>';
            return holen('/api/sql/admin/schema/' + encodeURIComponent(sid) + '/dateien', { headers: kopf() })
                .then(antwort).then(function (d) {
                    var e = d.eintraege || [];
                    if (!e.length) {
                        el.innerHTML = '<p class="kb-hint">' + esc(t('sqladm.no_files', 'Noch keine Dateien hochgeladen.')) + '</p>';
                        return;
                    }
                    // Kuerzung VOR der Liste und beziffert (Register).
                    var hinweis = d.gekappt ? '<p class="kb-hint">' + esc(t('sqladm.tree_cut',
                        '{n} von {g} Einträgen gezeigt.', { n: e.length, g: d.gesamt })) + '</p>' : '';
                    el.innerHTML = hinweis + '<ul class="sqadm-dateien">' + e.map(function (x) {
                        var teile = x.pfad.split('/');
                        var name = teile[teile.length - 1];
                        var ordner = x.art === 'ordner';
                        var titel = ordner ? t('sqladm.del_dir', 'Ordner samt Inhalt löschen') : t('sqladm.del_file', 'Datei löschen');
                        return '<li class="sqadm-datei' + (ordner ? ' is-ordner' : '') + '" style="padding-left:'
                            + ((teile.length - 1) * 16) + 'px">'
                            + '<span class="sqadm-dname" title="' + esc(x.pfad) + '">' + esc(name) + (ordner ? '/' : '') + '</span>'
                            + (ordner ? '' : '<span class="sqadm-dgr">' + esc(groesse(x.groesse)) + '</span>')
                            + '<button type="button" class="am-vorg-act" data-akt="del-datei" data-sid="' + esc(sid) + '" data-pfad="'
                            + esc(x.pfad) + '" data-art="' + (ordner ? 'ordner' : 'datei') + '" title="' + esc(titel) + '" aria-label="'
                            + esc(titel + ': ' + x.pfad) + '">' + window.JarvisIcons.trash() + '</button></li>';
                    }).join('') + '</ul>';
                }).catch(function (err) {
                    el.innerHTML = '<p class="sqadm-warn">' + esc((err && err.message) || t('sqladm.load_failed', 'Laden fehlgeschlagen')) + '</p>';
                });
        },

        // ── Erfassung je Schema ────────────────────────────────────────────
        // Lage EINES Schemas: laeuft gerade ein Lauf, der es erfasst? wartet
        // einer? was war sein letztes Ergebnis? Ein Lauf ueber Schema A sagt
        // nichts ueber Schema B – deshalb ``schemata`` und ``je_schema``.
        _erfLage: function (sid) {
            var st = this._erfassung || {};
            var laeuft = !!st.laeuft && (!Array.isArray(st.schemata) || st.schemata.indexOf(sid) >= 0);
            var vm = this._vorgemerkt;
            var wartet = !laeuft && !!vm && (vm.nur == null || vm.nur.indexOf(sid) >= 0);
            var je = (st.je_schema && st.je_schema[sid]) || null;
            return { laeuft: laeuft, wartet: wartet, je: je, st: st };
        },

        // Traegt den Stand in die VORHANDENEN Elemente ein (kein Neuzeichnen).
        _zeichneErfassung: function () {
            var self = this;
            document.querySelectorAll('#sqadm-schemata .sqadm-schema').forEach(function (karte) {
                var sid = karte.getAttribute('data-id') || '';
                var erf = karte.querySelector('.sqadm-erf');
                var info = karte.querySelector('.sqadm-kopfinfo');
                if (!sid || !erf) { if (info) info.textContent = ''; return; }
                var L = self._erfLage(sid);
                var f = self._dateien[sid] || { dateien: 0 };
                if (info) {
                    info.textContent = L.laeuft ? t('sqladm.run_active', 'Erfassung läuft')
                        : L.wartet ? t('sqladm.run_queued', 'Erfassung vorgemerkt')
                        : t('sqladm.files_short', '{n} Dateien', { n: f.dateien || 0 });
                }
                var fw = erf.querySelector('.sqadm-erf-fort');
                var stand = erf.querySelector('.sqadm-erf-stand');
                fw.hidden = !L.laeuft;
                var txt = '', fehlerArt = null, fehler = [];
                if (L.laeuft) {
                    // Zaehler DIESES Schemas im laufenden Lauf (ein Eintrag mit
                    // Ergebnis stammt aus einem frueheren Lauf).
                    var z = (L.je && !L.je.ergebnis) ? L.je : {};
                    var anteil = z.bytes_neu ? Math.min(100, Math.round(100 * (z.bytes_fertig || 0) / z.bytes_neu)) : 0;
                    fw.querySelector('.vis-progress-fill').style.width = anteil + '%';
                    var teile = [L.st.phase || '',
                        t('sqladm.files_of', '{a} von {b} Dateien', { a: z.dateien_fertig || 0, b: z.dateien_neu || 0 })];
                    if (L.st.mb_pro_s) teile.push(L.st.mb_pro_s + ' MB/s');
                    if (L.st.rest_s) teile.push(t('sqladm.rest', 'noch etwa {m} min', { m: Math.max(1, Math.round(L.st.rest_s / 60)) }));
                    fw.querySelector('.vis-progress-text').textContent = teile.filter(Boolean).join(' · ');
                    fehler = (z.fehler || []).slice(-10);
                } else if (L.wartet) {
                    txt = t('sqladm.queued', 'Vorgemerkt – beginnt, sobald die laufende Erfassung fertig ist.');
                } else if (L.je && L.je.ergebnis) {
                    txt = t('sqladm.last_run', 'Letzte Erfassung: {e} am {d} – {n} Dateien, davon {m} neu oder geändert.',
                        { e: ergebnisWort(L.je.ergebnis), d: L.je.ende || '?',
                          n: L.je.dateien_gesamt || 0, m: L.je.dateien_neu || 0 });
                    if (L.je.ergebnis === 'fehler') fehlerArt = 'error';
                    fehler = (L.je.fehler || []).slice(-10);
                    if ((L.je.ausgelassen || []).length) {
                        fehler.push(t('sqladm.skipped', '{n} Dateien ausgelassen (brachten den Leseprozess zweimal zum Absturz): {l}',
                            { n: L.je.ausgelassen.length, l: L.je.ausgelassen.slice(0, 5).join(', ') }));
                    }
                    // Ein Fehler des ganzen Laufs (z. B. beim Ableiten des Graphen)
                    // steht nicht bei einer Datei – er gehoert trotzdem hierher.
                    if (L.je.ergebnis === 'fehler' && !fehler.length) fehler = (L.st.fehler || []).slice(-3);
                    // Gelesen, aber nichts uebernommen: NACH dem Lauf-Fehler
                    // angehaengt (ein Hinweis ist kein Fehler und darf dessen
                    // Rueckfall oben nicht verdraengen). Nur der Dateiname –
                    // der Ablageort auf dem Server sagt dem Leser nichts.
                    var leer = L.je.ohne_struktur || [];
                    if (leer.length) {
                        fehler.push(t('sqladm.no_structure', '{n} Dateien gelesen, aber keine Tabelle oder Sicht darin erkannt – sie tragen nichts zum Schema bei: {l}',
                            { n: leer.length, l: leer.slice(0, 5).map(function (x) { return String(x).split('/').pop(); }).join(', ') }));
                    }
                }
                // Kein letzter Lauf bekannt: nichts behaupten (Register).
                status(stand, txt, fehlerArt);
                erf.querySelector('.sqadm-erf-start').disabled = L.laeuft || L.wartet;
                erf.querySelector('.sqadm-erf-stop').style.display = L.laeuft ? '' : 'none';
                erf.querySelector('.sqadm-erf-fehler').innerHTML = fehler.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('');
            });
        },

        // Nach einer Aktion, die eine Erfassung ausloest: steht sie beim Server
        // noch nicht im Status (der Lauf schreibt ihn erst nach dem Start),
        // gilt sie hier schon als laufend – der Takt holt gleich den echten Stand.
        _erwarten: function (ids) {
            var self = this;
            var offen = (ids || []).filter(function (sid) {
                var L = self._erfLage(sid);
                return !L.laeuft && !L.wartet;
            });
            if (offen.length) {
                this._erfassung = Object.assign({}, this._erfassung, { laeuft: true, schemata: offen, phase: '',
                                                                       mb_pro_s: null, rest_s: null });
            }
            this._zeichneErfassung();
            this._taktPruefen();
        },

        // ── Aktionen ───────────────────────────────────────────────────────
        // ``ziel``: wo das Ergebnis steht – die Kennung eines festen Elements
        // oder ``{i}`` fuer den Speichern-Knopf im i-ten Container. Aufgeloest
        // wird bei JEDER Meldung neu: nach dem Speichern sind die Container
        // neu gezeichnet, das alte Element gibt es dann nicht mehr.
        _statusEl: function (ziel) {
            if (typeof ziel === 'string') return $(ziel);
            var karten = document.querySelectorAll('#sqadm-schemata .sqadm-schema');
            var k = ziel && karten[ziel.i];
            return (k && k.querySelector('.sqadm-einst-status')) || $('sqadm-status');
        },

        speichern: function (ziel, bestaetigt) {
            var self = this;
            var cfg = this._formCfg();
            function melde(msg, art) { status(self._statusEl(ziel), msg, art); }
            melde(t('sqladm.saving', 'Speichere …'));
            return holen('/api/sql/admin', {
                method: 'PUT', headers: kopf({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ cfg: cfg, loeschen_bestaetigt: bestaetigt === true })
            }).then(antwort).then(function (d) {
                self._cfg = d.cfg;
                self._schemata = kopie(d.cfg.schemata || []);
                // Sofort mit dem gespeicherten Stand zeichnen (neue Kennungen!):
                // ein gerade laufendes Nachladen sammelt sonst noch das ALTE
                // Formular ein, und ein eben gespeichertes Schema stuende
                // weiter als "noch nicht gespeichert" da.
                self._zeichne(false);
                // Zahlen und Graph neu holen (neue Schemata, geloeschte Dateien) –
                // die Meldung erst DANACH, sonst stuende sie im alten Element.
                return self.laden().then(function () {
                    liste('sqadm-hinweise', d.hinweise || []);
                    var erfasst = d.erfasst || [];
                    var namen = (d.cfg.schemata || []).filter(function (s) { return erfasst.indexOf(s.id) >= 0; })
                        .map(function (s) { return '„' + s.name + '“'; }).join(', ');
                    melde(namen ? t('sqladm.saved_recapture', 'Gespeichert – neu erfasst wird: {l}.', { l: namen })
                        : t('sqladm.saved', 'Gespeichert.'), 'ok');
                    if (erfasst.length) self._erwarten(erfasst);
                });
            }).catch(function (e) {
                var weg = (e && e.daten && e.daten.zu_loeschen) || [];
                if (e && e.status === 409 && weg.length) {
                    var namen = weg.map(function (s) {
                        var f = self._dateien[s.id] || {};
                        return '„' + s.name + '“ (' + t('sqladm.files_short', '{n} Dateien', { n: f.dateien || 0 }) + ')';
                    }).join(', ');
                    if (window.confirm(t('sqladm.confirm_del', 'Diese Schemata samt ihrer Dateien endgültig löschen? {l}', { l: namen }))) {
                        return self.speichern(ziel, true);
                    }
                    melde(t('sqladm.not_deleted', 'Nicht gespeichert – das Schema bleibt erhalten.'), 'error');
                    return;
                }
                var f = (e && e.daten && e.daten.fehler) || [];
                liste('sqadm-hinweise', f);
                // Die Punkte stehen in der Liste unter den Containern – am Knopf
                // im Container der erste davon, damit er dort lesbar ist.
                melde(f.length ? (typeof ziel === 'string'
                        ? t('sqladm.not_saved', 'Nicht gespeichert – bitte die Punkte unten korrigieren.')
                        : t('sqladm.not_saved_first', 'Nicht gespeichert: {f}', { f: f[0] }))
                    : ((e && e.message) || t('sqladm.save_failed', 'Speichern fehlgeschlagen')), 'error');
            });
        },

        hochladen: function (sid, gesammelt) {
            var self = this;
            var box = $('sqadm-schemata');
            function teil(kl) { return box.querySelector('.' + kl + '[data-sid="' + sid + '"]'); }
            var stEl = teil('sqadm-up-status'), fehlerEl = teil('sqadm-up-fehler'), balken = teil('sqadm-up');
            if (!sid || this._hochladen[sid]) return Promise.resolve();
            var wahl = auswaehlen(gesammelt, this._endungen(sid));
            if (fehlerEl) fehlerEl.innerHTML = '';
            if (!wahl.nehmen.length) {
                status(stEl, t('sqladm.nothing', 'Keine passende Datei dabei ({n} übersprungen) – übernommen werden nur die Dateimuster und ZIP-Archive.',
                    { n: wahl.gefiltert }), 'error');
                return Promise.resolve();
            }
            var liste_ = pakete(wahl.nehmen);
            var gesamt = wahl.nehmen.reduce(function (s, g) { return s + g.datei.size; }, 0);
            var fertigBytes = 0, gespeichert = 0, abgelehnt = [];
            this._hochladen[sid] = true;
            var drop = teil('sqadm-drop');
            if (drop) drop.classList.add('disabled');
            if (balken) balken.hidden = false;
            status(stEl, '');
            function zeige(laufend) {
                if (!balken) return;
                var anteil = gesamt ? Math.min(100, Math.round(100 * (fertigBytes + laufend) / gesamt)) : 100;
                balken.querySelector('.vis-progress-fill').style.width = anteil + '%';
                balken.querySelector('.vis-progress-text').textContent = t('sqladm.uploading',
                    'Lade hoch: {a} von {b} ({p} %)', { a: groesse(fertigBytes + laufend), b: groesse(gesamt), p: anteil });
            }
            zeige(0);
            function sende(paket) {
                return new Promise(function (ok, nein) {
                    var fd = new FormData();
                    paket.forEach(function (g) { fd.append('files', g.datei, g.datei.name); });
                    fd.append('pfade', JSON.stringify(paket.map(function (g) { return g.pfad; })));
                    var xhr = new XMLHttpRequest();
                    xhr.open('POST', '/api/sql/admin/schema/' + encodeURIComponent(sid) + '/upload');
                    xhr.setRequestHeader('Authorization', 'Bearer ' + token());
                    var pb = paketBytes(paket);
                    xhr.upload.onprogress = function (ev) { if (ev.lengthComputable && ev.total) zeige(pb * ev.loaded / ev.total); };
                    xhr.onload = function () {
                        var d = {};
                        try { d = JSON.parse(xhr.responseText || '{}'); } catch (e) { d = {}; }
                        if (xhr.status >= 200 && xhr.status < 300 && d.ok !== false) ok(d);
                        else nein(new Error((d && (d.error || d.detail)) || ('HTTP ' + xhr.status)));
                    };
                    xhr.onerror = function () { nein(new Error(netzText('/api/sql/admin/schema/' + sid + '/upload'))); };
                    xhr.send(fd);
                });
            }
            var kette = Promise.resolve();
            liste_.forEach(function (p) {
                kette = kette.then(function () {
                    return sende(p).then(function (d) {
                        fertigBytes += paketBytes(p);
                        gespeichert += (d.gespeichert || []).length;
                        abgelehnt = abgelehnt.concat(d.abgelehnt || []);
                        zeige(0);
                    });
                });
            });
            return kette.then(function () {
                status(stEl, t('sqladm.uploaded', '{n} Dateien übernommen, {a} abgelehnt, {f} übersprungen. Die Erfassung läuft.',
                    { n: gespeichert, a: abgelehnt.length, f: wahl.gefiltert }), abgelehnt.length ? 'error' : null);
            }).catch(function (e) {
                status(stEl, t('sqladm.upload_failed', 'Hochladen abgebrochen nach {n} Dateien: {e}',
                    { n: gespeichert, e: (e && e.message) || '' }), 'error');
            }).then(function () {
                self._hochladen[sid] = false;
                // Ergebnistexte ueber das Neuzeichnen retten (laden() baut die Container neu).
                var txt = stEl ? stEl.textContent : '', fehlerhaft = stEl && stEl.classList.contains('is-fehler');
                // Erfasst wird nur, wenn der Server etwas uebernommen hat.
                return self._nachAenderung(gespeichert ? sid : '').then(function () {
                    var st2 = teil('sqadm-up-status'), fe2 = teil('sqadm-up-fehler');
                    status(st2, txt, fehlerhaft ? 'error' : null);
                    if (fe2) {
                        fe2.innerHTML = abgelehnt.slice(0, ABGELEHNT_ZEIGEN).map(function (a) {
                            return '<li>' + esc(a.name + ': ' + a.grund) + '</li>';
                        }).join('') + (abgelehnt.length > ABGELEHNT_ZEIGEN ? '<li>' + esc(t('sqladm.more_rejected',
                            '… und {n} weitere', { n: abgelehnt.length - ABGELEHNT_ZEIGEN })) + '</li>' : '');
                    }
                });
            });
        },

        loeschen: function (sid, pfad, art) {
            var self = this;
            if (!pfad) return Promise.resolve();
            var frage = art === 'ordner'
                ? t('sqladm.confirm_dir', 'Ordner „{p}“ samt Inhalt endgültig löschen?', { p: pfad })
                : t('sqladm.confirm_file', 'Datei „{p}“ endgültig löschen?', { p: pfad });
            if (!window.confirm(frage)) return Promise.resolve();
            return holen('/api/sql/admin/schema/' + encodeURIComponent(sid) + '/datei?pfad=' + encodeURIComponent(pfad),
                { method: 'DELETE', headers: kopf() }).then(antwort).then(function (d) {
                    return self._nachAenderung(sid).then(function () {
                        status($('sqadm-schemata').querySelector('.sqadm-up-status[data-sid="' + sid + '"]'),
                            t('sqladm.deleted', 'Gelöscht ({n} Dateien). Die Erfassung läuft.', { n: d.dateien || 0 }), 'ok');
                    });
                }).catch(function (e) {
                    status($('sqadm-schemata').querySelector('.sqadm-up-status[data-sid="' + sid + '"]'),
                        (e && e.message) || '', 'error');
                });
        },

        // Nach Hochladen/Loeschen in EINEM Schema: Zahlen, Baum und den
        // Erfassungsstand dieses Schemas nachziehen (Eingaben bleiben stehen).
        _nachAenderung: function (sid) {
            var self = this;
            return this.laden(true).then(function () {
                if (sid) self._erwarten([sid]);
            });
        },

        // Erfassung DIESES Schemas von Hand.
        starten: function (sid) {
            var self = this;
            function stEl() { return $('sqadm-schemata').querySelector('.sqadm-erf[data-sid="' + sid + '"] .sqadm-erf-status'); }
            if (!sid) return Promise.resolve();
            status(stEl(), t('sqladm.starting', 'Starte …'));
            return holen('/api/sql/admin/schema/' + encodeURIComponent(sid) + '/index', { method: 'POST', headers: kopf() })
                .then(antwort).then(function (d) {
                    self._erfassung = d.erfassung || {};
                    self._vorgemerkt = d.vorgemerkt || null;
                    status(stEl(), '');
                    self._erwarten([sid]);
                }).catch(function (e) { status(stEl(), (e && e.message) || '', 'error'); });
        },

        // Es laeuft EIN Lauf zugleich – der Knopf am Schema haelt den an, der
        // dieses Schema gerade erfasst.
        abbrechen: function (sid) {
            var self = this;
            function stEl() { return $('sqadm-schemata').querySelector('.sqadm-erf[data-sid="' + sid + '"] .sqadm-erf-status'); }
            return holen('/api/sql/admin/index/abbrechen', { method: 'POST', headers: kopf() }).then(antwort)
                .then(function () { status(stEl(), t('sqladm.cancel_req', 'Abbruch angefordert …')); self._taktPruefen(); })
                .catch(function (e) { status(stEl(), (e && e.message) || '', 'error'); });
        },

        // Abfrage-Takt nur, solange eine Erfassung laeuft oder wartet UND der
        // Reiter sichtbar ist – ein Takt auf einem verborgenen Reiter ist Rauschen.
        _taktPruefen: function () {
            var self = this;
            if (this._takt) { clearTimeout(this._takt); this._takt = null; }
            var reiter = $('settings-tab-sql');
            var sichtbar = reiter && reiter.style.display !== 'none';
            var aktiv = !!(this._erfassung && this._erfassung.laeuft) || !!this._vorgemerkt;
            if (!aktiv || !sichtbar) return;
            this._takt = setTimeout(function () {
                holen('/api/sql/admin/index', { headers: kopf() }).then(antwort).then(function (d) {
                    self._erfassung = d.erfassung || {};
                    self._vorgemerkt = d.vorgemerkt || null;
                    self._zeichneErfassung();
                    // Zum Ende Graph und Zahlen je Schema nachladen.
                    if (!self._erfassung.laeuft && !self._vorgemerkt) self.laden(true);
                    else self._taktPruefen();
                }).catch(function () { self._taktPruefen(); });
            }, TAKT);
        }
    };

    // Fuer Tests: die reinen Helfer (Auswahl und Pakete) ohne DOM pruefbar.
    Admin._intern = { auswaehlen: auswaehlen, pakete: pakete, PAKET_DATEIEN: PAKET_DATEIEN, PAKET_BYTES: PAKET_BYTES };
    window.SqlAdmin = Admin;
})();
