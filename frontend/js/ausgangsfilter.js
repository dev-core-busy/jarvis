/*
 * Ausgangsfilter (Haertung D1) – KI & System -> System-Einstellungen.
 *
 * Zeigt und bearbeitet /etc/jarvis/ausgang.conf ueber den Root-Broker
 * (backend/broker/ausgang.py, Regeln in deploy/security/ausgang.sh):
 *   - Freigaben als Tabelle (Benutzer, Protokoll, Ports, Ziele, Notiz)
 *   - Modus: protokollieren oder sperren
 *   - Verbindungen OHNE Freigabe der letzten 24 h, je Ziel ein Knopf
 *     "Freigeben", der die Zeile in die Tabelle uebernimmt
 *   - Pruefen (ohne Code, schreibt nichts), Speichern und anwenden bzw.
 *     Filter entfernen (beides mit Freigabe-Code)
 *
 * Kommentare der Datei bleiben erhalten: Kopfzeilen vor der ersten Regel
 * unveraendert, Kommentarzeilen direkt ueber einer Freigabe als deren Notiz.
 * Gepruft wird NUR im Skript (eine zweite Fassung der Regeln liefe auseinander);
 * die Tabelle prueft lediglich, dass kein Feld leer ist.
 */
(function () {
    'use strict';

    function token() { return window.JarvisSitzung.token(); }
    function authHeaders(extra) { return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {}); }
    function $(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function T(key, def) {
        var v = (typeof window.t === 'function') ? window.t(key) : key;
        return (v && v !== key) ? v : def;
    }
    function fz() { return window.Fernzugang || null; }

    // ── Text <-> Tabelle ─────────────────────────────────────────────────────
    // Zerlegt die Konfiguration: Kopf (Kommentare vor der ersten Regel/MODUS),
    // Modus und Freigaben mit Notiz (Kommentarzeilen direkt darueber oder ein
    // Kommentar am Zeilenende). Unbekannte Zeilen landen als "roh" in der
    // Liste und werden unveraendert zurueckgeschrieben – das Skript meldet sie.
    function zerlegen(text) {
        var kopf = [], modus = 'protokoll', zeilen = [], notiz = [], begonnen = false;
        String(text || '').split('\n').forEach(function (z) {
            var roh = z.replace(/\s+$/, '');
            var ohne = roh.split('#')[0].trim();
            var kommentar = roh.indexOf('#') >= 0 ? roh.slice(roh.indexOf('#') + 1).trim() : '';
            if (!ohne) {
                // Leerzeile: im Kopf behalten; zwischen Regeln faellt sie weg, ein
                // Kommentar darueber geht dann an die naechste Freigabe (nichts geht verloren)
                if (!kommentar) { if (!begonnen) kopf.push(roh); return; }
                if (!begonnen) { kopf.push(roh); return; }
                notiz.push(kommentar);
                return;
            }
            if (/^MODUS=/.test(ohne)) {
                modus = ohne.slice(6).trim();
                if (!begonnen) { begonnen = true; }
                notiz = [];
                return;
            }
            begonnen = true;
            var t = ohne.split(/\s+/);
            if (t.length === 5 && t[0] === 'erlaube') {
                if (kommentar) notiz.push(kommentar);
                zeilen.push({ benutzer: t[1], proto: t[2], ports: t[3], ziele: t[4], notiz: notiz.join(' ') });
            } else {
                zeilen.push({ roh: roh });
            }
            notiz = [];
        });
        while (kopf.length && !kopf[kopf.length - 1].trim()) kopf.pop();
        return { kopf: kopf, modus: modus, zeilen: zeilen };
    }

    function zusammensetzen(stand) {
        var aus = [];
        (stand.kopf || []).forEach(function (z) { aus.push(z); });
        if (aus.length) aus.push('');
        aus.push('MODUS=' + (stand.modus === 'sperre' ? 'sperre' : 'protokoll'));
        (stand.zeilen || []).forEach(function (r) {
            if (r.roh != null) { aus.push(r.roh); return; }
            if (r.notiz) aus.push('# ' + String(r.notiz).replace(/\s*\n\s*/g, ' '));
            aus.push(['erlaube', r.benutzer, r.proto, r.ports, r.ziele].map(function (x) {
                return String(x == null ? '' : x).trim();
            }).join(' '));
        });
        return aus.join('\n') + '\n';
    }

    // Eine Zeile "ohne Freigabe" als Vorschlag fuer die Tabelle
    function vorschlag(tr) {
        var proto = String(tr.proto || '').toLowerCase();
        if (['tcp', 'udp', 'icmp'].indexOf(proto) < 0) return null;
        return {
            benutzer: tr.benutzer || tr.uid || 'alle',
            proto: proto,
            ports: proto === 'icmp' ? '-' : (tr.port || '-'),
            ziele: tr.ziel || '*',
            notiz: ''
        };
    }

    var Af = {
        _stand: null,
        _gezeigt: false,
        _gebunden: false,

        onShow: function () { this._bind(); this._gezeigt = true; this.laden(); },

        _bind: function () {
            if (this._gebunden) return;
            this._gebunden = true;
            var self = this;
            function an(id, fn) { var el = $(id); if (el) el.addEventListener('click', fn); }
            an('af-neu', function () { self._zeileHinzu({ benutzer: '', proto: 'tcp', ports: '', ziele: '', notiz: '' }); });
            an('af-pruefen', function () { self.senden('pruefen'); });
            an('af-speichern', function () { self.senden('speichern'); });
            an('af-entfernen', function () { self.senden('entfernen'); });
            an('af-neu-laden', function () { self.laden(); });
            var tab = $('af-freigaben');
            if (tab) tab.addEventListener('click', function (e) {
                var b = e.target.closest('[data-af-weg]');
                if (!b) return;
                var i = parseInt(b.getAttribute('data-af-weg'), 10);
                self._ausTabelle();
                self._stand.zeilen.splice(i, 1);
                self._tabelle();
            });
            var tr = $('af-treffer');
            if (tr) tr.addEventListener('click', function (e) {
                var b = e.target.closest('[data-af-frei]');
                if (!b) return;
                var t = (self._treffer || [])[parseInt(b.getAttribute('data-af-frei'), 10)];
                var v = t && vorschlag(t);
                if (v) { self._zeileHinzu(v); b.disabled = true; }
            });
        },

        laden: function () {
            var self = this;
            return fetch('/api/broker/ausgang/status', { headers: authHeaders() })
                .then(function (r) { return r.json().catch(function () { return null; }); })
                .then(function (d) { self.zeigen(d && d.ok ? d : null); })
                .catch(function () { self.zeigen(null); });
        },

        // Statuszeile: "unbekannt" (nicht lesbar) wird nicht zu "aus" gemacht.
        statusText: function (d) {
            if (!d) return T('af.st_fehler', 'Der Zustand ließ sich nicht abfragen.');
            if (!d.skript) return T('af.st_ohne_skript', 'Dieser Server hat das Programm für den Ausgangsfilter noch nicht – erst ein Update einspielen.');
            if (!d.konfiguration) return T('af.st_keine', 'Nicht eingerichtet – ausgehende Verbindungen werden nicht gefiltert. Lege Freigaben an und speichere, um den Filter einzurichten.');
            var n = (d.freigaben || []).length;
            var teile = [];
            if (d.geladen === null) teile.push(T('af.st_unbekannt', 'Ob der Filter geladen ist, ließ sich nicht prüfen.'));
            else if (!d.geladen) teile.push(T('af.st_nicht_geladen', 'Die Freigaben sind gespeichert, der Filter ist aber nicht geladen – „Speichern und anwenden“ lädt ihn.'));
            else if (d.policy === 'drop') teile.push(T('af.st_sperre', 'Sperrmodus: Verbindungen ohne Freigabe werden verworfen.'));
            else teile.push(T('af.st_protokoll', 'Protokollmodus: nichts wird gesperrt, Verbindungen ohne Freigabe werden nur aufgezeichnet.'));
            teile.push(T('af.st_anzahl', '{n} Freigaben.').replace('{n}', n));
            teile.push(d.unit === 'enabled'
                ? T('af.st_start_an', 'Wird beim Systemstart geladen.')
                : T('af.st_start_aus', 'Wird beim Systemstart NICHT geladen.'));
            if (d.gueltig === false) teile.push(T('af.st_ungueltig', 'Die gespeicherte Datei ist fehlerhaft:') + ' ' + (d.fehler || ''));
            return teile.join(' ');
        },

        zeigen: function (d) {
            this._daten = d;
            var st = $('af-status');
            if (st) st.textContent = this.statusText(d);
            var z = zerlegen(d && d.text);
            if (d && !d.konfiguration) z.modus = 'protokoll';
            this._stand = z;
            var m = $('af-modus');
            if (m) m.value = z.modus === 'sperre' ? 'sperre' : 'protokoll';
            this._tabelle();
            this._trefferZeigen(d);
            var weg = $('af-entfernen');
            if (weg) weg.style.display = d && d.geladen ? '' : 'none';
        },

        _tabelle: function () {
            var box = $('af-freigaben');
            if (!box) return;
            var zeilen = (this._stand && this._stand.zeilen) || [];
            if (!zeilen.length) {
                box.innerHTML = '<div class="kb-hint">' + esc(T('af.leer', 'Noch keine Freigaben.')) + '</div>';
                return;
            }
            var weg = esc(T('af.weg', 'Freigabe löschen'));
            var muell = window.JarvisIcons ? window.JarvisIcons.trash() : '';
            var html = '<table class="audit-table af-tabelle"><thead><tr>'
                + '<th>' + esc(T('af.sp_benutzer', 'Benutzer')) + '</th>'
                + '<th>' + esc(T('af.sp_proto', 'Protokoll')) + '</th>'
                + '<th>' + esc(T('af.sp_ports', 'Ports')) + '</th>'
                + '<th>' + esc(T('af.sp_ziele', 'Ziele')) + '</th>'
                + '<th>' + esc(T('af.sp_notiz', 'Notiz')) + '</th><th></th></tr></thead><tbody>';
            zeilen.forEach(function (r, i) {
                if (r.roh != null) {
                    html += '<tr data-af-roh="' + i + '"><td colspan="5"><code>' + esc(r.roh) + '</code></td>'
                        + '<td><button type="button" class="sec-btn small danger" data-af-weg="' + i + '" title="' + weg + '" aria-label="' + weg + '">' + muell + '</button></td></tr>';
                    return;
                }
                html += '<tr data-af-zeile="' + i + '">'
                    + '<td><input data-tabfill-nein="Freigabe im Ausgangsfilter – ein Beispielwert darf nicht per Tab zur Regel werden" type="text" data-f="benutzer" value="' + esc(r.benutzer) + '" placeholder="jarvis"></td>'
                    + '<td><select data-f="proto">' + ['tcp', 'udp', 'icmp'].map(function (p) {
                        return '<option value="' + p + '"' + (r.proto === p ? ' selected' : '') + '>' + p + '</option>';
                    }).join('') + '</select></td>'
                    + '<td><input data-tabfill-nein="Freigabe im Ausgangsfilter – ein Beispielwert darf nicht per Tab zur Regel werden" type="text" data-f="ports" value="' + esc(r.ports) + '" placeholder="443"></td>'
                    + '<td><input data-tabfill-nein="Freigabe im Ausgangsfilter – ein Beispielwert darf nicht per Tab zur Regel werden" type="text" data-f="ziele" value="' + esc(r.ziele) + '" placeholder="*"></td>'
                    + '<td><input type="text" data-f="notiz" value="' + esc(r.notiz) + '"></td>'
                    + '<td><button type="button" class="sec-btn small danger" data-af-weg="' + i + '" title="' + weg + '" aria-label="' + weg + '">' + muell + '</button></td></tr>';
            });
            box.innerHTML = html + '</tbody></table>';
        },

        // Eingaben aus der Tabelle in den Stand zurueckholen
        _ausTabelle: function () {
            var self = this;
            var box = $('af-freigaben');
            if (!box || !self._stand) return;
            box.querySelectorAll('tr[data-af-zeile]').forEach(function (tr) {
                var r = self._stand.zeilen[parseInt(tr.getAttribute('data-af-zeile'), 10)];
                if (!r) return;
                tr.querySelectorAll('[data-f]').forEach(function (el) { r[el.getAttribute('data-f')] = el.value.trim(); });
            });
            var m = $('af-modus');
            if (m) self._stand.modus = m.value;
        },

        _zeileHinzu: function (r) {
            if (!this._stand) this._stand = zerlegen('');
            this._ausTabelle();
            this._stand.zeilen.push(r);
            this._tabelle();
        },

        _trefferZeigen: function (d) {
            var box = $('af-treffer');
            if (!box) return;
            this._treffer = (d && d.treffer) || [];
            if (!d) { box.innerHTML = ''; return; }
            if (!d.protokoll_lesbar) {
                box.innerHTML = '<div class="kb-hint">' + esc(T('af.tr_nicht_lesbar', 'Das Protokoll ließ sich nicht lesen.')) + '</div>';
                return;
            }
            if (!this._treffer.length) {
                box.innerHTML = '<div class="kb-hint">' + esc(T('af.tr_leer', 'In den letzten {h} Stunden gab es keine Verbindung ohne Freigabe.').replace('{h}', d.stunden || 24)) + '</div>';
                return;
            }
            var html = '<table class="audit-table af-tabelle"><thead><tr>'
                + '<th>' + esc(T('af.sp_wirkung', 'Wirkung')) + '</th>'
                + '<th>' + esc(T('af.sp_benutzer', 'Benutzer')) + '</th>'
                + '<th>' + esc(T('af.sp_proto', 'Protokoll')) + '</th>'
                + '<th>' + esc(T('af.sp_ziel', 'Ziel')) + '</th>'
                + '<th>' + esc(T('af.sp_port', 'Port')) + '</th>'
                + '<th>' + esc(T('af.sp_anzahl', 'Anzahl')) + '</th>'
                + '<th>' + esc(T('af.sp_zuletzt', 'Zuletzt')) + '</th><th></th></tr></thead><tbody>';
            this._treffer.forEach(function (t, i) {
                var wer = t.benutzer || (t.uid ? 'uid ' + t.uid : T('af.ohne_benutzer', 'ohne Benutzer (Kernel)'));
                var zeit = t.zuletzt ? new Date(t.zuletzt * 1000).toLocaleString() : '';
                var geht = !!vorschlag(t);
                html += '<tr><td>' + esc(t.art === 'drop' ? T('af.art_drop', 'verworfen') : T('af.art_frei', 'nur aufgezeichnet')) + '</td>'
                    + '<td>' + esc(wer) + '</td><td>' + esc(t.proto) + '</td><td>' + esc(t.ziel) + '</td>'
                    + '<td>' + esc(t.port || '–') + '</td><td>' + esc(t.anzahl) + '</td><td>' + esc(zeit) + '</td>'
                    + '<td>' + (geht ? '<button type="button" class="sec-btn small" data-af-frei="' + i + '">' + esc(T('af.freigeben', 'Freigeben')) + '</button>' : '') + '</td></tr>';
            });
            box.innerHTML = html + '</tbody></table>';
        },

        _ergebnis: function (art, text) {
            var el = $('af-result');
            if (!el) return;
            el.className = 'sec-ssh-result ' + (art === 'fehler' ? 'fehler' : 'ok');
            if (art === 'laeuft') el.innerHTML = '<span class="jv-pkg-spin"></span> ' + esc(text);
            else el.textContent = text || '';
            el.style.display = text ? '' : 'none';
        },

        // Eine leere Zelle wuerde das Skript ablehnen – hier schon mit Zeilennummer
        _leereZeile: function () {
            var zeilen = (this._stand && this._stand.zeilen) || [];
            for (var i = 0; i < zeilen.length; i++) {
                var r = zeilen[i];
                if (r.roh != null) continue;
                if (!r.benutzer || !r.proto || !r.ports || !r.ziele) return i + 1;
            }
            return 0;
        },

        senden: function (aktion) {
            var self = this;
            self._ausTabelle();
            var body = { aktion: aktion };
            if (aktion !== 'entfernen') {
                var leer = self._leereZeile();
                if (leer) {
                    self._ergebnis('fehler', T('af.leeres_feld', 'Freigabe {n}: Benutzer, Protokoll, Ports und Ziele müssen ausgefüllt sein („-“ = alle Ports, „*“ = jedes Ziel).').replace('{n}', leer));
                    return;
                }
                body.text = zusammensetzen(self._stand);
            }
            if (aktion !== 'pruefen') {
                var frage = aktion === 'entfernen'
                    ? T('af.frage_entfernen', 'Ausgangsfilter entfernen? Danach werden ausgehende Verbindungen weder gefiltert noch aufgezeichnet. Die Freigaben bleiben gespeichert.')
                    : (self._stand.modus === 'sperre'
                        ? T('af.frage_sperre', 'Im Sperrmodus speichern? Jede Verbindung ohne Freigabe wird ab sofort verworfen – fehlt eine Freigabe, fällt die betroffene Funktion aus.')
                        : T('af.frage_speichern', 'Freigaben speichern und anwenden?'));
                if (!window.confirm(frage)) return;
                var c = fz() ? fz()._code() : window.prompt(T('security.broker_code_prompt', 'Freigabe-Code:'), '');
                if (c === null) return;
                body.nachweis = String(c).replace(/\D/g, '');
            }
            ['af-pruefen', 'af-speichern', 'af-entfernen'].forEach(function (id) { var b = $(id); if (b) b.disabled = true; });
            self._ergebnis('laeuft', aktion === 'pruefen' ? T('af.prueft', 'Wird geprüft …') : T('af.laeuft', 'Wird angewendet …'));
            return fetch('/api/broker/ausgang', {
                method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(body)
            }).then(function (r) { return r.json().catch(function () { return {}; }); })
              .then(function (d) {
                  if (d && d.ok) {
                      self._ergebnis('ok', aktion === 'pruefen'
                          ? T('af.ok_pruefen', 'Die Freigaben sind gültig ({n} Regeln). Gespeichert ist noch nichts.').replace('{n}', d.regeln == null ? '?' : d.regeln)
                          : (aktion === 'entfernen' ? T('af.ok_entfernen', 'Der Ausgangsfilter ist entfernt.') : T('af.ok_speichern', 'Gespeichert und angewendet.')));
                  } else {
                      var text = (d && d.grund && fz() && fz()._codeText(d.grund)) || (d && (d.meldung || d.error)) || '';
                      var vorsatz = d && d.zurueck ? T('af.zurueck', 'Nicht angewendet, die vorherigen Freigaben gelten weiter') : T('af.fehler', 'Fehlgeschlagen');
                      self._ergebnis('fehler', vorsatz + (text ? ': ' + text : ''));
                  }
                  return d;
              })
              .catch(function (e) { self._ergebnis('fehler', T('af.fehler', 'Fehlgeschlagen') + ': ' + (e && e.message || e)); })
              .then(function (d) {
                  ['af-pruefen', 'af-speichern', 'af-entfernen'].forEach(function (id) { var b = $(id); if (b) b.disabled = false; });
                  // Nach Pruefen bleibt die Bearbeitung stehen; sonst den Server-Stand zeigen
                  if (aktion !== 'pruefen' && d && d.ok) return self.laden();
              });
        }
    };

    // Rechenhelfer fuer den Waechter (tests/test_ausgangsfilter_ui.js)
    Af._rechnen = { zerlegen: zerlegen, zusammensetzen: zusammensetzen, vorschlag: vorschlag };
    window.Ausgangsfilter = Af;

    var sprache = window._lang;
    window.addEventListener('jarvis-lang-changed', function () {
        if (window._lang === sprache) return;
        sprache = window._lang;
        // Bearbeitung behalten: nur neu zeichnen, nicht neu zerlegen
        if (Af._gezeigt) {
            Af._ausTabelle();
            var st = $('af-status');
            if (st) st.textContent = Af.statusText(Af._daten);
            Af._tabelle();
            Af._trefferZeigen(Af._daten);
        }
    });
})();
