/* Eigener Zugang (PAT) fuer Serverdienste – EIN Modul fuer beide Container.
 *
 * Vorgabe des Betreibers (2026-11-17): Einstellungen → Jira → Loesungsarchiv
 * und Einstellungen → Wissen → "Dynamische Confluence-Einbindung" bekommen je
 * ein Feld fuer einen eigenen PAT, der unabhaengig vom gemeinsamen Zugang
 * benutzt wird (backend/dienst_zugang.py). Ohne eigenen Token gilt weiter der
 * gemeinsame Zugang – die Statuszeile sagt immer, WELCHER gerade gilt.
 *
 * Verdrahtet wird jeder Container mit `data-dienstzugang="<dienst>"`. Zwei
 * Fassungen derselben Bedienung liefen beim naechsten Feinschliff
 * auseinander; deshalb ein Modul und Klassen statt IDs.
 *
 * Der Token kommt NIE vom Server. Das Feld wird ueber JarvisPwEye.geheim()
 * als "gespeichert" markiert; das Auge holt den Wert erst auf Klick ueber
 * /api/secret/reveal (Quelle "skill", erneute Anmeldung, protokolliert).
 */
(function () {
    'use strict';

    function t(k, rueckfall) {
        var v = (typeof window.t === 'function') ? window.t(k) : k;
        return (v && v !== k) ? v : rueckfall;
    }
    function kopf(extra) {
        var tok = (window.JarvisSitzung && window.JarvisSitzung.token) ? window.JarvisSitzung.token() : '';
        return Object.assign({ 'Authorization': 'Bearer ' + tok }, extra || {});
    }
    function abruf(url, opts) {
        return fetch(url, Object.assign({ headers: kopf() }, opts || {})).then(function (r) {
            return r.json().catch(function () { return {}; }).then(function (d) {
                if (!r.ok || (d && d.ok === false)) {
                    var e = new Error((d && (d.error || d.detail)) || ('HTTP ' + r.status));
                    throw e;
                }
                return d;
            });
        });
    }

    /** Statuszeile: welcher Zugang gilt. Text traegt die Aussage, nicht die Farbe. */
    function zustandText(z) {
        if (!z.adresse_gesetzt) {
            return t('dzg.st_keine_adresse',
                'Es ist noch keine Adresse hinterlegt – zuerst die Verbindung des Bereichs einrichten.');
        }
        if (z.quelle === 'dienst') {
            return t('dzg.st_dienst', 'Verwendet wird der eigene Token dieses Dienstes.');
        }
        if (z.quelle === 'sammel') {
            return t('dzg.st_sammel',
                'Kein eigener Token hinterlegt – verwendet wird der gemeinsame Zugang.');
        }
        return t('dzg.st_keiner',
            'Kein Zugang nutzbar – weder ein eigener Token noch der gemeinsame Zugang ist hinterlegt.');
    }

    function Block(el) {
        this.el = el;
        this.dienst = el.getAttribute('data-dienstzugang');
        this.inp = el.querySelector('.dzg-token');
        this.status = el.querySelector('.dzg-status');
        this.meldung = el.querySelector('.dzg-meldung');
        this.del = el.querySelector('.dzg-del');
        this.zustand = null;
        var self = this;
        var s = el.querySelector('.dzg-save');
        if (s) s.addEventListener('click', function () { self.speichern(); });
        var p = el.querySelector('.dzg-test');
        if (p) p.addEventListener('click', function () { self.testen(); });
        if (this.del) {
            if (window.JarvisIcons && window.JarvisIcons.setTrash) window.JarvisIcons.setTrash(this.del);
            this.del.addEventListener('click', function () { self.loeschen(); });
        }
        if (this.inp) {
            this.inp.addEventListener('keydown', function (e) {
                if (e.key === 'Enter') { e.preventDefault(); self.speichern(); }
            });
        }
        window.addEventListener('jarvis-lang-changed', function () {
            if (self.zustand) self.zeigen(self.zustand, true);
        });
    }

    Block.prototype.melden = function (text, fehler) {
        if (!this.meldung) return;
        this.meldung.textContent = text || '';
        this.meldung.hidden = !text;
        // Ein Fehler bleibt stehen (er muss lesbar sein), ein Erfolg auch –
        // er nennt, mit welchem Zugang gemessen wurde.
        this.meldung.classList.toggle('sec-ssh-hinweis', !!fehler);
    };

    Block.prototype.zeigen = function (z, nurText) {
        this.zustand = z;
        if (this.status) this.status.textContent = zustandText(z);
        if (this.del) {
            // Gesperrt MIT Grund statt verborgen (Projektregel).
            this.del.disabled = !z.token_gesetzt;
            this.del.title = z.token_gesetzt
                ? t('dzg.del', 'Eigenen Token entfernen – danach gilt der gemeinsame Zugang')
                : t('dzg.del_leer', 'Es ist kein eigener Token hinterlegt.');
            this.del.setAttribute('aria-label', this.del.title);
        }
        if (nurText || !this.inp) return;
        if (window.JarvisPwEye && window.JarvisPwEye.geheim) {
            window.JarvisPwEye.geheim(this.inp, 'skill', z.kennung, !!z.token_gesetzt);
        } else {
            this.inp.value = '';
        }
        // Der Confluence-Container im Wissen-Reiter erscheint nur mit aktivem
        // Skill – wie der Confluence-Reiter selbst.
        var sekt = this.el.closest('[data-dzg-sektion]');
        if (sekt) sekt.style.display = z.skill_aktiv ? '' : 'none';
    };

    Block.prototype.laden = function () {
        var self = this;
        return abruf('/api/dienstzugang/' + encodeURIComponent(this.dienst))
            .then(function (z) { self.zeigen(z); })
            .catch(function (e) {
                if (self.status) self.status.textContent = t('dzg.st_fehler', 'Zustand nicht abrufbar:') + ' ' + e.message;
            });
    };

    Block.prototype.speichern = function () {
        var self = this;
        var wert = (this.inp ? this.inp.value : '').trim();
        if (!wert) {
            this.melden(t('dzg.leer', 'Bitte einen Token eingeben.'), true);
            return;
        }
        this.melden(t('dzg.speichere', 'Speichere…'), false);
        abruf('/api/dienstzugang/' + encodeURIComponent(this.dienst), {
            method: 'POST',
            headers: kopf({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ token: wert })
        }).then(function (z) {
            self.zeigen(z);
            self.melden('✓ ' + t('dzg.gespeichert', 'Token gespeichert.'), false);
        }).catch(function (e) {
            self.melden('✗ ' + e.message, true);
        });
    };

    Block.prototype.loeschen = function () {
        var self = this;
        if (!this.zustand || !this.zustand.token_gesetzt) return;
        if (!window.confirm(t('dzg.del_confirm',
            'Den eigenen Token dieses Dienstes entfernen? Danach arbeitet der Dienst mit dem gemeinsamen Zugang.'))) {
            return;
        }
        abruf('/api/dienstzugang/' + encodeURIComponent(this.dienst), { method: 'DELETE' })
            .then(function (z) {
                self.zeigen(z);
                self.melden('✓ ' + t('dzg.entfernt', 'Eigener Token entfernt – es gilt der gemeinsame Zugang.'), false);
            })
            .catch(function (e) { self.melden('✗ ' + e.message, true); });
    };

    Block.prototype.testen = function () {
        var self = this;
        this.melden(t('dzg.pruefe', 'Prüfe Verbindung…'), false);
        fetch('/api/dienstzugang/' + encodeURIComponent(this.dienst) + '/test',
              { method: 'POST', headers: kopf() })
            .then(function (r) { return r.json().catch(function () { return {}; }); })
            .then(function (d) {
                // Die Antwort nennt den Zugang – ohne das hiesse "ok" bei
                // fehlendem eigenen Token nur, dass der gemeinsame antwortet.
                var mit = d.quelle === 'dienst'
                    ? t('dzg.mit_dienst', 'mit dem eigenen Token')
                    : (d.quelle === 'sammel' ? t('dzg.mit_sammel', 'mit dem gemeinsamen Zugang') : '');
                if (d.ok) {
                    var wer = d.anzeigename || d.konto || '';
                    self.melden('✓ ' + t('dzg.test_ok', 'Verbindung in Ordnung') + (mit ? ' (' + mit + ')' : '')
                        + (wer ? ' – ' + t('dzg.als', 'angemeldet als') + ' ' + wer : '') + '.', false);
                } else {
                    self.melden('✗ ' + (d.error || d.detail || t('dzg.test_fehler', 'Verbindung fehlgeschlagen'))
                        + (mit ? ' (' + mit + ')' : ''), true);
                }
            })
            .catch(function (e) { self.melden('✗ ' + e.message, true); });
    };

    var bloecke = [];
    function start() {
        var els = document.querySelectorAll('[data-dienstzugang]');
        for (var i = 0; i < els.length; i++) {
            var b = new Block(els[i]);
            bloecke.push(b);
            b.laden();
        }
        // Beim Oeffnen des Reiters frisch holen: eine Aenderung der Verbindung
        // (Adresse, gemeinsamer Token) aendert, welcher Zugang gilt.
        document.addEventListener('click', function (ev) {
            var k = ev.target && ev.target.closest
                ? ev.target.closest('[data-settings-tab="jira"],[data-settings-tab="knowledge"]') : null;
            if (k) bloecke.forEach(function (b) { b.laden(); });
        });
    }
    if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
    else start();

    window.DienstZugang = { neuLaden: function () { bloecke.forEach(function (b) { b.laden(); }); } };
})();
