/* ═══════════════════════════════════════════════════════════════════════
   Einstellungen → SQL-Assistent: Schemata (Name + feste Ablage auf dem
   Server), Dateien hochladen und loeschen, allgemeine Vorgaben, Erfassung.
   Daten ueber /api/sql/admin* (nur Admins).

   EIN SCHEMA IST EIN FESTER ORDNER (data/sql_schema_graph/<kennung>/) –
   seit 2026-11-07 ohne freie Ordnerwahl und ohne Wissensgruppen. Die
   Dateien kommen per Ablage (Dateien, ganze Ordner oder ZIP) wie im
   Informationsextraktor von /wissen; nach jedem Hochladen und Loeschen
   startet die Erfassung von selbst.

   ⚠ GESPEICHERT WIRD DIE GANZE KONFIGURATION ODER NICHTS. Der Server prueft
   alles und speichert bei einem einzigen Fehler NICHTS.

   ⚠ EIN SCHEMA AUS DER LISTE ZU NEHMEN LOESCHT SEINE DATEIEN. Der Server
   verlangt dafuer eine ausdrueckliche Bestaetigung (409 mit der Liste); hier
   wird sie mit Namen und Dateizahl erfragt.

   ⚠ HOCHGELADEN WIRD IN PAKETEN, gefiltert nach den Dateimustern: ein
   Bestand von tausenden Dateien und vielen GB laesst sich nicht in EINER
   Anfrage schicken, und Dateien, die der Server ohnehin ablehnt, muessen
   nicht erst uebertragen werden.

   ⚠ DIE VERSTECKTEN DATEIFELDER STEHEN NEBEN DEM ABLAGEFELD, NICHT DARIN:
   ``input.click()`` erzeugt ein Klick-Ereignis, das nach oben laeuft – im
   Ablagefeld haette es dessen Klick-Zweig erneut ausgeloest.
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

    var Admin = {
        _gebunden: false,
        _cfg: null,
        _graph: null,
        _dateien: {},        // je Schema {dateien, ordner, bytes}
        _erfassung: {},
        _schemata: [],       // Formularstand (Arbeitskopie)
        _offen: {},          // je Schema: Dateiliste aufgeklappt?
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
                self._schemata.push({ id: '', name: '' });
                self._zeichneSchemata();
                var n = document.querySelectorAll('#sqadm-schemata .sqadm-name');
                if (n.length) n[n.length - 1].focus();
            });
            $('sqadm-save').addEventListener('click', function () { self.speichern('sqadm-status'); });
            $('sqadm-save2').addEventListener('click', function () { self.speichern('sqadm-status2'); });
            $('sqadm-start').addEventListener('click', function () { self.starten(); });
            $('sqadm-stop').addEventListener('click', function () { self.abbrechen(); });
            var box = $('sqadm-schemata');
            // Delegiert: die Karten entstehen erst beim Zeichnen.
            box.addEventListener('click', function (e) {
                var el = e.target.closest ? e.target.closest('[data-akt]') : null;
                if (!el || !box.contains(el)) return;
                var sid = el.getAttribute('data-sid') || '';
                var akt = el.getAttribute('data-akt');
                if (akt === 'del-schema') {
                    self._sammeln();
                    var i = parseInt(el.getAttribute('data-i'), 10);
                    if (i >= 0 && i < self._schemata.length) self._schemata.splice(i, 1);
                    self._zeichneSchemata();
                    status('sqadm-status', t('sqladm.removed', 'Schema entfernt – mit „Speichern“ übernehmen. Seine Dateien werden dabei gelöscht.'));
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
                var d = e.target.classList && e.target.classList.contains('sqadm-drop') ? e.target : null;
                if (!d) return;
                e.preventDefault();
                self._feld(d.getAttribute('data-sid'), 'sqadm-fin');
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

        laden: function () {
            var self = this;
            if (this._laedt) return Promise.resolve();
            this._laedt = true;
            this._lang = window._lang;
            return holen('/api/sql/admin', { headers: kopf() }).then(antwort).then(function (d) {
                self._cfg = d.cfg;
                self._graph = d.graph;
                self._dateien = d.dateien || {};
                self._uploadEndungen = d.upload_endungen || null;
                self._erfassung = d.erfassung || {};
                self._schemata = JSON.parse(JSON.stringify(d.cfg.schemata || []));
                self._zeichne(false);
                self._taktPruefen();
            }).catch(function (e) {
                status('sqadm-status', (e && e.message) || t('sqladm.load_failed', 'Laden fehlgeschlagen'), 'error');
            }).then(function () { self._laedt = false; });
        },

        // ── Formular <-> Daten ─────────────────────────────────────────────
        _sammeln: function () {
            var rows = document.querySelectorAll('#sqadm-schemata .sqadm-schema');
            var out = [];
            rows.forEach(function (row) {
                out.push({ id: row.getAttribute('data-id') || '',
                           name: (row.querySelector('.sqadm-name').value || '').trim() });
            });
            if (rows.length || !this._schemata) this._schemata = out;
            return out;
        },
        _formCfg: function () {
            var cfg = JSON.parse(JSON.stringify(this._cfg || {}));
            cfg.schemata = this._sammeln();
            cfg.dialekt = $('sqadm-dialekt').value;
            cfg.dateimuster = ($('sqadm-muster').value || '').trim();
            cfg.prozesse = Number($('sqadm-prozesse').value);
            cfg.max_tabellen = Number($('sqadm-maxtab').value);
            cfg.max_spalten = Number($('sqadm-maxsp').value);
            cfg.fk_ableiten = !!$('sqadm-fk').checked;
            cfg.index_aus_chat = !!$('sqadm-chat').checked;
            return cfg;
        },
        // Endungen fuer den Filter VOR dem Hochladen – aus dem GESPEICHERTEN
        // Muster, denn danach prueft auch der Server.
        _endungen: function () {
            // Was der Server annimmt (Dateimuster + Begleitdokumente) – vom
            // Server, damit Filter und Annahme nicht auseinanderlaufen.
            if (Array.isArray(this._uploadEndungen) && this._uploadEndungen.length) return this._uploadEndungen.slice();
            return String((this._cfg && this._cfg.dateimuster) || '').split(',').map(function (m) {
                m = m.trim().toLowerCase();
                return m.indexOf('*.') === 0 ? m.slice(1) : '';
            }).filter(Boolean);
        },

        // ── Zeichnen ───────────────────────────────────────────────────────
        _zeichne: function (nurTexte) {
            var c = this._cfg || {};
            var sel = $('sqadm-dialekt');
            var akt = nurTexte ? sel.value : c.dialekt;
            sel.innerHTML = DIALEKTE.map(function (d) {
                return '<option value="' + esc(d) + '">' + esc(d === 'allgemein'
                    ? t('sql.dialect_generic', 'allgemein (Standard-SQL)') : d) + '</option>';
            }).join('');
            sel.value = akt || 'allgemein';
            if (!nurTexte) {
                $('sqadm-muster').value = c.dateimuster || '';
                $('sqadm-prozesse').value = c.prozesse;
                $('sqadm-maxtab').value = c.max_tabellen;
                $('sqadm-maxsp').value = c.max_spalten;
                $('sqadm-fk').checked = !!c.fk_ableiten;
                $('sqadm-chat').checked = !!c.index_aus_chat;
            }
            this._zeichneSchemata();
            this._zeichneErfassung();
        },

        _zahlen: function (sid) {
            var z = ((this._graph && this._graph.schemata) || []).filter(function (x) { return x.id === sid; })[0];
            var f = this._dateien[sid] || { dateien: 0, ordner: 0, bytes: 0 };
            var teile = [t('sqladm.files_n', '{n} Dateien ({g})', { n: f.dateien, g: groesse(f.bytes) })];
            if (z && this._graph && this._graph.vorhanden) {
                teile.push(t('sqladm.counts', '{t} Tabellen, {v} Sichten, {s} Spalten im Graphen',
                    { t: z.tabellen, v: z.sichten, s: z.spalten }));
                if (z.dokumente) teile.push(t('sqladm.docs_n', '{n} Begleitdokumente', { n: z.dokumente }));
            }
            return teile.join(' · ');
        },

        _zeichneSchemata: function () {
            var self = this;
            var box = $('sqadm-schemata');
            if (!this._schemata.length) {
                box.innerHTML = '<p class="kb-hint">' + esc(t('sqladm.no_schemas',
                    'Noch kein Schema – lege eines an und speichere, dann können Dateien hochgeladen werden.')) + '</p>';
                return;
            }
            var endungen = this._endungen().concat(['.zip']).join(', ');
            var dropText = t('sqladm.drop', 'Dateien, Ordner oder ZIP-Archiv hierher ziehen oder klicken zum Auswählen');
            box.innerHTML = this._schemata.map(function (s, i) {
                var sid = s.id || '';
                var kopfHtml = '<div class="sqadm-kopf">'
                    + '<input type="text" class="config-input sqadm-name" maxlength="80" autocomplete="off" value="'
                    + esc(s.name) + '" placeholder="' + esc(t('sqladm.name_ph', 'Name, z. B. ERP-Datenbank')) + '"'
                    + ' aria-label="' + esc(t('sqladm.name', 'Name des Schemas')) + '">'
                    + '<button type="button" class="am-vorg-act" data-akt="del-schema" data-i="' + i + '" title="'
                    + esc(t('sqladm.remove', 'Schema samt Dateien löschen')) + '" aria-label="'
                    + esc(t('sqladm.remove', 'Schema samt Dateien löschen')) + '">' + window.JarvisIcons.trash() + '</button>'
                    + '</div>';
                if (!sid) {
                    return '<div class="sqadm-schema" data-id="">' + kopfHtml
                        + '<div class="kb-hint">' + esc(t('sqladm.save_first', 'Erst speichern – danach können Dateien hochgeladen werden.')) + '</div></div>';
                }
                var busy = !!self._hochladen[sid];
                var offen = !!self._offen[sid];
                return '<div class="sqadm-schema" data-id="' + esc(sid) + '">' + kopfHtml
                    + '<div class="kb-hint sqadm-zahlen">' + esc(self._zahlen(sid)) + '</div>'
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
                    + '</div>';
            }).join('');
            this._schemata.forEach(function (s) { if (s.id && self._offen[s.id]) self._zeichneBaum(s.id); });
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

        _zeichneErfassung: function () {
            var st = this._erfassung || {};
            var g = this._graph || {};
            $('sqadm-graph').innerHTML = '<p class="kb-hint">' + esc(g.vorhanden
                ? t('sqladm.graph_stand', 'Graph vom {d}.', { d: g.stand || '?' })
                : t('sqladm.graph_none', 'Noch kein Graph vorhanden.')) + '</p>';
            var laeuft = !!st.laeuft;
            var fw = $('sqadm-fortschritt');
            fw.hidden = !laeuft;
            if (laeuft) {
                var anteil = st.bytes_neu ? Math.min(100, Math.round(100 * (st.bytes_fertig || 0) / st.bytes_neu)) : 0;
                $('sqadm-balken').style.width = anteil + '%';
                var teile = [st.phase || '',
                    t('sqladm.files_of', '{a} von {b} Dateien', { a: st.dateien_fertig || 0, b: st.dateien_neu || 0 })];
                if (st.mb_pro_s) teile.push(st.mb_pro_s + ' MB/s');
                if (st.rest_s) teile.push(t('sqladm.rest', 'noch etwa {m} min', { m: Math.max(1, Math.round(st.rest_s / 60)) }));
                $('sqadm-fortschritt-text').textContent = teile.filter(Boolean).join(' · ');
            }
            $('sqadm-start').disabled = laeuft;
            $('sqadm-stop').style.display = laeuft ? '' : 'none';
            if (!laeuft && st.ergebnis) {
                var txt = t('sqladm.last_run', 'Letzte Erfassung: {e} am {d} – {n} Dateien, davon {m} neu oder geändert.',
                    { e: st.ergebnis, d: st.ende || '?', n: st.dateien_gesamt || 0, m: st.dateien_neu || 0 });
                status('sqadm-erf-status', txt, st.ergebnis === 'fehler' ? 'error' : null);
            } else if (laeuft) {
                status('sqadm-erf-status', '');
            }
            var fehler = (st.fehler || []).slice(-10);
            if ((st.ausgelassen || []).length) {
                fehler.push(t('sqladm.skipped', '{n} Dateien ausgelassen (brachten den Leseprozess zweimal zum Absturz): {l}',
                    { n: st.ausgelassen.length, l: st.ausgelassen.slice(0, 5).join(', ') }));
            }
            liste('sqadm-fehler', fehler);
        },

        // ── Aktionen ───────────────────────────────────────────────────────
        speichern: function (statusId, bestaetigt) {
            var self = this;
            var cfg = this._formCfg();
            status(statusId, t('sqladm.saving', 'Speichere …'));
            return holen('/api/sql/admin', {
                method: 'PUT', headers: kopf({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ cfg: cfg, loeschen_bestaetigt: bestaetigt === true })
            }).then(antwort).then(function (d) {
                self._cfg = d.cfg;
                self._schemata = JSON.parse(JSON.stringify(d.cfg.schemata || []));
                liste('sqadm-hinweise', d.hinweise || []);
                status(statusId, t('sqladm.saved', 'Gespeichert.'), 'ok');
                // Zahlen und Graph neu holen (neue Schemata, geloeschte Dateien).
                return self.laden();
            }).catch(function (e) {
                var weg = (e && e.daten && e.daten.zu_loeschen) || [];
                if (e && e.status === 409 && weg.length) {
                    var namen = weg.map(function (s) {
                        var f = self._dateien[s.id] || {};
                        return '„' + s.name + '“ (' + t('sqladm.files_short', '{n} Dateien', { n: f.dateien || 0 }) + ')';
                    }).join(', ');
                    if (window.confirm(t('sqladm.confirm_del', 'Diese Schemata samt ihrer Dateien endgültig löschen? {l}', { l: namen }))) {
                        return self.speichern(statusId, true);
                    }
                    status(statusId, t('sqladm.not_deleted', 'Nicht gespeichert – das Schema bleibt erhalten.'), 'error');
                    return;
                }
                var f = (e && e.daten && e.daten.fehler) || [];
                liste('sqadm-hinweise', f);
                status(statusId, f.length ? t('sqladm.not_saved', 'Nicht gespeichert – bitte die Punkte unten korrigieren.')
                    : ((e && e.message) || t('sqladm.save_failed', 'Speichern fehlgeschlagen')), 'error');
            });
        },

        hochladen: function (sid, gesammelt) {
            var self = this;
            var box = $('sqadm-schemata');
            function teil(kl) { return box.querySelector('.' + kl + '[data-sid="' + sid + '"]'); }
            var stEl = teil('sqadm-up-status'), fehlerEl = teil('sqadm-up-fehler'), balken = teil('sqadm-up');
            if (!sid || this._hochladen[sid]) return Promise.resolve();
            var wahl = auswaehlen(gesammelt, this._endungen());
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
                // Ergebnistexte ueber das Neuzeichnen retten (laden() baut die Karten neu).
                var txt = stEl ? stEl.textContent : '', fehlerhaft = stEl && stEl.classList.contains('is-fehler');
                return self._nachAenderung().then(function () {
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
                    return self._nachAenderung().then(function () {
                        status($('sqadm-schemata').querySelector('.sqadm-up-status[data-sid="' + sid + '"]'),
                            t('sqladm.deleted', 'Gelöscht ({n} Dateien). Die Erfassung läuft.', { n: d.dateien || 0 }), 'ok');
                    });
                }).catch(function (e) {
                    status($('sqadm-schemata').querySelector('.sqadm-up-status[data-sid="' + sid + '"]'),
                        (e && e.message) || '', 'error');
                });
        },

        // Nach Hochladen/Loeschen: Zahlen, Baum und Erfassungsstand nachziehen.
        _nachAenderung: function () {
            var self = this;
            return this.laden().then(function () {
                // Der Server stoesst die Erfassung an; der Takt holt den Stand.
                self._erfassung = Object.assign({}, self._erfassung, { laeuft: true });
                self._taktPruefen();
            });
        },

        starten: function () {
            var self = this;
            status('sqadm-erf-status', t('sqladm.starting', 'Starte …'));
            return holen('/api/sql/admin/index', { method: 'POST', headers: kopf() }).then(antwort).then(function (d) {
                self._erfassung = d.erfassung || {};
                self._erfassung.laeuft = true;
                self._zeichneErfassung();
                self._taktPruefen();
            }).catch(function (e) { status('sqadm-erf-status', (e && e.message) || '', 'error'); });
        },

        abbrechen: function () {
            var self = this;
            return holen('/api/sql/admin/index/abbrechen', { method: 'POST', headers: kopf() }).then(antwort)
                .then(function () { status('sqadm-erf-status', t('sqladm.cancel_req', 'Abbruch angefordert …')); self._taktPruefen(); })
                .catch(function (e) { status('sqadm-erf-status', (e && e.message) || '', 'error'); });
        },

        // Abfrage-Takt nur, solange eine Erfassung laeuft UND der Reiter
        // sichtbar ist – ein Takt auf einem verborgenen Reiter ist Rauschen.
        _taktPruefen: function () {
            var self = this;
            if (this._takt) { clearTimeout(this._takt); this._takt = null; }
            var reiter = $('settings-tab-sql');
            var sichtbar = reiter && reiter.style.display !== 'none';
            if (!(this._erfassung && this._erfassung.laeuft) || !sichtbar) return;
            this._takt = setTimeout(function () {
                holen('/api/sql/admin/index', { headers: kopf() }).then(antwort).then(function (d) {
                    var war = self._erfassung && self._erfassung.laeuft;
                    self._erfassung = d.erfassung || {};
                    self._zeichneErfassung();
                    // Zum Ende Graph und Zahlen je Schema nachladen.
                    if (war && !self._erfassung.laeuft) self.laden();
                    else self._taktPruefen();
                }).catch(function () { self._taktPruefen(); });
            }, TAKT);
        }
    };

    // Fuer Tests: die reinen Helfer (Auswahl und Pakete) ohne DOM pruefbar.
    Admin._intern = { auswaehlen: auswaehlen, pakete: pakete, PAKET_DATEIEN: PAKET_DATEIEN, PAKET_BYTES: PAKET_BYTES };
    window.SqlAdmin = Admin;
})();
