// E-Mail-Versand (Einstellungen -> KI & System -> E-Mail-Versand, 2026-11-24).
// Empfaenger, weiterleitender Mailserver und die vier Meldungsarten; Speichern
// und Einrichten laufen ueber den Broker (backend/broker/meta.py), der auch
// entscheidet, ob der Freigabe-Code noetig ist (Empfaenger/Mailserver aendern,
// Meldungsart abschalten). Die Code-Abfrage kommt aus fernzugang.js
// (window.Fernzugang._code/_codeText) – EINE Fassung.
(function () {
    'use strict';

    function $(id) { return document.getElementById(id); }
    function authHeaders(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + window.JarvisSitzung.token() }, extra || {});
    }
    function T(key, def, vars) {
        var s = (typeof window.t === 'function') ? window.t(key) : '';
        if (!s || s === key) s = def;
        Object.keys(vars || {}).forEach(function (k) { s = s.split('{' + k + '}').join(vars[k]); });
        return s;
    }
    function zeit(ts) {
        try { return new Date(ts * 1000).toLocaleString(); } catch (e) { return ''; }
    }

    var Mv = {
        _bound: false,
        _stand: null,

        onShow: function () { this._bind(); this.laden(); },

        _bind: function () {
            if (this._bound) return;
            this._bound = true;
            var self = this;
            var an = function (id, fn) { var el = $(id); if (el) el.addEventListener('click', fn); };
            an('mv-speichern', function () { self.speichern(); });
            an('mv-test', function () { self.test(); });
            an('mv-einrichten', function () { self.einrichten(); });
        },

        laden: function () {
            var self = this;
            return fetch('/api/broker/mailversand/status', { headers: authHeaders() })
                .then(function (r) { return r.json().catch(function () { return null; }); })
                .then(function (d) { self.zeigen(d && d.ok ? d : null); })
                .catch(function () { self.zeigen(null); });
        },

        // Statuszeilen aus dem Zustand; "unbekannt" bleibt unbekannt.
        statusZeilen: function (d) {
            if (!d) return [T('mv.st_fehler', 'Der Zustand ließ sich nicht abfragen.')];
            if (!d.installiert) return [T('mv.st_fehlt', 'Auf diesem Server ist noch kein Mailserver eingerichtet – es werden keine E-Mails verschickt.')];
            var z = [];
            if (!d.aktiv) z.push(T('mv.st_aus', 'Der Mailserver ist eingerichtet, läuft aber nicht.'));
            else if (!(d.empfaenger || []).length) z.push(T('mv.st_kein_empf', 'Bereit – aber es ist noch kein Empfänger eingetragen.'));
            else z.push(T('mv.st_ok', 'Bereit – Meldungen gehen an {empf}.', { empf: d.empfaenger.join(', ') }));
            if (d.konfig_aktuell === false) z.push(T('mv.st_veraltet', 'Die Konfiguration des Mailservers weicht von diesen Einstellungen ab – bitte einmal speichern.'));
            if ((d.lauscht || []).length) z.push(T('mv.st_lauscht', 'Achtung: der Mailserver nimmt Verbindungen an ({adr}).', { adr: d.lauscht.join(', ') }));
            var w = d.warteschlange || {};
            if (w.anzahl) z.push(T('mv.st_warteschlange', '{n} Nachricht(en) warten auf Zustellung.', { n: w.anzahl }) + (w.grund ? ' (' + w.grund + ')' : ''));
            return z;
        },

        zeigen: function (d) {
            this._stand = d;
            var box = $('mv-status');
            if (box) box.textContent = this.statusZeilen(d).join(' ');
            var ein = $('mv-einrichten');
            if (ein) ein.style.display = (d && !d.installiert) ? '' : 'none';
            var e = $('mv-empfaenger'), r = $('mv-relay');
            if (d) {
                if (e) e.value = (d.empfaenger || []).join(', ');
                if (r) r.value = d.relay || '';
                document.querySelectorAll('#mv-quellen input[data-quelle]').forEach(function (cb) {
                    cb.checked = (d.quellen || []).indexOf(cb.getAttribute('data-quelle')) >= 0;
                });
            }
            ['mv-speichern', 'mv-test'].forEach(function (id) { var b = $(id); if (b) b.disabled = !d; });
            var t = $('mv-test');
            if (t) t.disabled = !d || !d.installiert || !(d.empfaenger || []).length;
            this._letzte(d);
        },

        _letzte: function (d) {
            var el = $('mv-letzte');
            if (!el) return;
            el.textContent = '';
            var liste = (d && d.letzte) || [];
            if (!liste.length) return;
            var kopf = document.createElement('div');
            kopf.className = 'systab-label';
            kopf.textContent = T('mv.letzte_titel', 'Zuletzt verschickt');
            el.appendChild(kopf);
            liste.slice().reverse().slice(0, 5).forEach(function (x) {
                var zeile = document.createElement('div');
                zeile.className = 'kb-hint';
                zeile.style.margin = '0';
                zeile.textContent = zeit(x.zeit) + ' – ' + (x.betreff || '') + ' – '
                    + (x.ok ? T('mv.letzte_ok', 'übergeben') : T('mv.letzte_fehler', 'Fehler') + ': ' + (x.fehler || ''));
                el.appendChild(zeile);
            });
        },

        _ergebnis: function (ok, text) {
            var el = $('mv-result');
            if (!el) return;
            el.className = 'sec-ssh-result ' + (ok ? 'ok' : 'fehler');
            el.textContent = text || '';
            el.style.display = text ? '' : 'none';
        },

        _quellen: function () {
            var q = [];
            document.querySelectorAll('#mv-quellen input[data-quelle]').forEach(function (cb) {
                if (cb.checked) q.push(cb.getAttribute('data-quelle'));
            });
            return q;
        },

        // Braucht die Aenderung den Freigabe-Code? Dieselbe Regel wie
        // mail_meldung.ist_lockerung – der BROKER entscheidet; hier nur, um
        // nicht unnoetig zu fragen.
        brauchtCode: function (alt, empf, relay, quellen) {
            if (!alt) return true;
            var norm = function (l) { return (l || []).map(function (x) { return String(x).toLowerCase(); }).join(','); };
            var teile = empf.split(/[\s,;]+/).filter(Boolean);
            if (norm(teile) !== norm(alt.empfaenger)) return true;
            var rAlt = alt.relay || '';
            var rNeu = relay.trim();
            if (rNeu && rNeu.indexOf(':') < 0) rNeu += ':25';
            if (rNeu !== rAlt) return true;
            return (alt.quellen || []).some(function (q) { return quellen.indexOf(q) < 0; });
        },

        _senden: function (body, okText) {
            var self = this;
            var knoepfe = ['mv-speichern', 'mv-test', 'mv-einrichten'].map($).filter(Boolean);
            knoepfe.forEach(function (b) { b.disabled = true; });
            self._ergebnis(true, T('mv.laeuft', 'Wird ausgeführt …'));
            return fetch('/api/broker/mailversand', {
                method: 'POST', headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(body)
            }).then(function (r) { return r.json().catch(function () { return {}; }); })
              .then(function (d) {
                  if (d && d.ok && d.gedrosselt) self._ergebnis(false, T('mv.gedrosselt', 'Zu viele Testnachrichten in der letzten Stunde – bitte später erneut versuchen.'));
                  else if (d && d.ok) self._ergebnis(true, okText);
                  else {
                      var fz = window.Fernzugang;
                      var text = (d && d.grund && fz && fz._codeText(d.grund)) || (d && (d.meldung || d.error)) || '';
                      self._ergebnis(false, T('mv.fehler', 'Fehlgeschlagen') + (text ? ': ' + text : ''));
                  }
              })
              .catch(function (e) { self._ergebnis(false, T('mv.fehler', 'Fehlgeschlagen') + ': ' + (e && e.message || e)); })
              .then(function () {
                  knoepfe.forEach(function (b) { b.disabled = false; });
                  return self.laden();
              });
        },

        _code: function () {
            var fz = window.Fernzugang;
            return fz && fz._code ? fz._code() : window.prompt('Freigabe-Code:', '');
        },

        speichern: function () {
            var empf = ($('mv-empfaenger') || {}).value || '';
            var relay = ($('mv-relay') || {}).value || '';
            var quellen = this._quellen();
            var body = { aktion: 'speichern', empfaenger: empf, relay: relay, quellen: quellen };
            if (this.brauchtCode(this._stand, empf, relay, quellen)) {
                var c = this._code();
                if (c === null) return;
                body.nachweis = c;
            }
            return this._senden(body, T('mv.ok_gespeichert', 'Gespeichert.'));
        },

        einrichten: function () {
            if (!window.confirm(T('mv.einrichten_frage', 'Den Mailserver installieren und einrichten? Er verschickt nur Meldungen dieses Servers und nimmt keine Verbindungen von außen an.'))) return;
            var c = this._code();
            if (c === null) return;
            return this._senden({ aktion: 'einrichten', nachweis: c }, T('mv.ok_eingerichtet', 'Mailserver eingerichtet.'));
        },

        test: function () {
            return this._senden({ aktion: 'test' }, T('mv.ok_test', 'Testnachricht übergeben – sie sollte in wenigen Minuten ankommen.'));
        }
    };

    window.MailVersand = Mv;
})();
