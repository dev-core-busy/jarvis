/* ═══════════════════════════════════════════════════════════════════════
   Einstellungen → Newsfeed: Meldungen pflegen, Verweil- und Scrolldauer
   einstellen, Vorschau. Daten ueber /api/newsfeed/admin/* (nur Admins).

   ⚠ DIE VORSCHAU ZEICHNET MIT DEM ECHTEN LAUFBAND (newsfeed.js) – keine
   Nachbildung. Sie benutzt die Werte aus den FELDERN, nicht die
   gespeicherten: wer an der Geschwindigkeit dreht, will die Wirkung sehen,
   bevor er speichert.

   ⚠ „IM PORTAL SICHTBAR" IN DER LISTE FOLGT DER GESPEICHERTEN ANZAHL, die
   Vorschau der aus dem Feld. Die Liste sagt, was die Benutzer JETZT sehen;
   die Vorschau, was sie nach dem Speichern saehen.

   ⚠ DIE LISTE ZEICHNET AUS DER SERVER-ANTWORT. Nach jedem Speichern/Loeschen
   wird neu geladen, statt den Zwischenstand der Oberflaeche anzuzeigen – das
   Erstellungsdatum und die Reihenfolge setzt der Server.
   ═══════════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    function $(id) { return document.getElementById(id); }
    function kopf(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + window.JarvisSitzung.token() }, extra || {});
    }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function t(k, fb) {
        try { var v = window.t ? window.t(k) : ''; return (v && v !== k) ? v : fb; }
        catch (e) { return fb; }
    }
    // Ein Fehler bleibt stehen (man muss ihn lesen koennen), ein Erfolg geht.
    function status(id, msg, art) {
        var el = $(id); if (!el) return;
        el.textContent = msg || '';
        el.style.color = art === 'error' ? 'var(--danger)'
            : art === 'ok' ? 'var(--success)' : 'var(--text-secondary)';
        if (el._tm) clearTimeout(el._tm);
        if (art === 'ok') el._tm = setTimeout(function () { el.textContent = ''; }, 3500);
    }
    function antwort(r) {
        return r.json().catch(function () { return {}; }).then(function (d) {
            if (!r.ok || !d || d.ok === false) {
                throw new Error((d && (d.error || d.detail)) || ('HTTP ' + r.status));
            }
            return d;
        });
    }

    var Admin = {
        _gebunden: false,
        _eintraege: [],
        _grenzen: {},
        _einst: {},
        _offen: null,        // Kennung des aufgeklappten Formulars ('' = neu)
        _vorschau: null,

        onShow: function () { this._binden(); return this.laden(); },

        _binden: function () {
            if (this._gebunden) return;
            this._gebunden = true;
            var self = this;
            var neu = $('nfadm-neu');
            if (neu) neu.addEventListener('click', function () { self.formular(''); });
            var sp = $('nfadm-anz-save');
            if (sp) sp.addEventListener('click', function () { self.anzeigeSpeichern(); });
            ['nfadm-verweil', 'nfadm-scroll', 'nfadm-anzahl'].forEach(function (id) {
                var f = $(id);
                if (f) f.addEventListener('input', function () { self.vorschau(); });
            });
            var alle = $('nfadm-anzahl-alle');
            if (alle) alle.addEventListener('change', function () {
                self._anzahlSperren();
                self.vorschau();
            });
        },

        laden: function () {
            var self = this;
            return fetch('/api/newsfeed/admin', { headers: kopf() })
                .then(antwort)
                .then(function (d) {
                    self._eintraege = d.eintraege || [];
                    self._grenzen = d.grenzen || {};
                    self._einst = d.einstellungen || {};
                    self._felderSetzen(self._einst);
                    var aus = $('nfadm-skill-aus');
                    if (aus) aus.style.display = d.skill_aktiv ? 'none' : '';
                    self.liste();
                    self.vorschau();
                })
                .catch(function (e) {
                    status('nfadm-status', t('nfadm.load_err', 'Laden fehlgeschlagen') + ': ' + e.message, 'error');
                });
        },

        _alle: function () { return this._grenzen.anzahl_alle || 'alle'; },

        /** Anzahl als Obergrenze fuer slice/Zaehler – „alle" = unbegrenzt. */
        _grenze: function (anzahl) {
            if (anzahl === this._alle()) return Infinity;
            var z = parseInt(anzahl, 10);
            return isNaN(z) ? 3 : z;
        },

        /** Gespeicherte Anzahl (Server) – fuer die Marke in der Liste. */
        _anzahl: function () { return this._grenze(this._einst.anzahl); },

        _felderSetzen: function (e) {
            if ($('nfadm-verweil')) $('nfadm-verweil').value = e.verweil_s;
            if ($('nfadm-scroll')) $('nfadm-scroll').value = e.scroll_s;
            var feld = $('nfadm-anzahl'), alle = $('nfadm-anzahl-alle');
            var g = this._grenzen;
            if (feld) {
                if (g.anzahl_min != null) feld.min = g.anzahl_min;
                if (g.anzahl_max != null) feld.max = g.anzahl_max;
            }
            var istAlle = e.anzahl === this._alle();
            if (alle) alle.checked = istAlle;
            // Bei „alle" bleibt die zuletzt sichtbare Zahl im Feld stehen, damit
            // das Abwaehlen nicht bei einem leeren Feld landet.
            if (feld && !istAlle && e.anzahl != null) feld.value = e.anzahl;
            if (feld && !feld.value) feld.value = 3;
            this._anzahlSperren();
        },

        _anzahlSperren: function () {
            var feld = $('nfadm-anzahl'), alle = $('nfadm-anzahl-alle');
            if (feld && alle) feld.disabled = alle.checked;
        },

        liste: function () {
            var box = $('nfadm-liste'); if (!box) return;
            var self = this, n = this._anzahl();
            if (!this._eintraege.length) {
                box.innerHTML = '<p class="kb-hint">'
                    + esc(t('nfadm.empty', 'Noch keine Meldungen.')) + '</p>';
            } else {
                var fmt = function (iso) {
                    return window.JarvisNewsfeed ? window.JarvisNewsfeed.datum(iso) : iso;
                };
                var aktivZaehler = 0;
                box.innerHTML = this._eintraege.map(function (e) {
                    // Sichtbar im Portal sind die ersten n AKTIVEN (der Server
                    // liefert juengsten Stand zuerst) – als Text, nicht nur als Farbe.
                    var aktiv = e.aktiv !== false;
                    var marke = '';
                    if (!aktiv) {
                        marke = ' <span class="kb-hint" style="color:var(--warning);">· '
                            + esc(t('nfadm.inactive', 'deaktiviert – erscheint nach dem nächsten Bearbeiten wieder')) + '</span>';
                    } else if (aktivZaehler++ < n) {
                        marke = ' <span class="kb-hint" style="color:var(--success);">· '
                            + esc(t('nfadm.visible', 'im Portal sichtbar')) + '</span>';
                    }
                    var geaendert = (e.geaendert && fmt(e.geaendert) !== fmt(e.erstellt))
                        ? ' · ' + esc(t('nfadm.updated', 'bearbeitet')) + ': ' + esc(fmt(e.geaendert)) : '';
                    var deakt = aktiv
                        ? '<button type="button" class="am-vorg-act nf-adm-deakt" data-akt="deakt" title="'
                          + esc(t('nfadm.deactivate_hint', 'Im Portal ausblenden – bleibt hier bearbeitbar. Nach dem nächsten Speichern ist die Meldung wieder sichtbar.'))
                          + '">' + esc(t('nfadm.deactivate', 'Deaktivieren')) + '</button>'
                        : '';
                    return '<div class="am-vorg-card' + (aktiv ? '' : ' nf-adm-inaktiv') + '" data-nid="' + esc(e.id) + '">'
                        + '<div class="am-vorg-row">'
                        + '<div class="am-vorg-main"><b>' + esc(e.titel) + '</b>'
                        + '<span class="kb-hint" style="display:block;">' + esc(e.text) + '</span>'
                        + '<span class="kb-hint" style="display:block;font-size:.8em;">'
                        + esc(t('nfadm.created', 'Erstellt')) + ': ' + esc(fmt(e.erstellt))
                        + geaendert + marke + '</span>'
                        + '</div>'
                        + deakt
                        + '<button type="button" class="am-vorg-act" data-akt="edit" title="'
                        + esc(t('common.edit', 'Bearbeiten')) + '">' + window.JarvisIcons.pencil() + '</button>'
                        + '<button type="button" class="am-vorg-act" data-akt="del" title="'
                        + esc(t('common.delete', 'Löschen')) + '">' + window.JarvisIcons.trash() + '</button>'
                        + '</div></div>';
                }).join('');
                box.querySelectorAll('.am-vorg-act').forEach(function (b) {
                    b.addEventListener('click', function () {
                        var karte = b.closest('.am-vorg-card');
                        var nid = karte ? karte.getAttribute('data-nid') : '';
                        var akt = b.getAttribute('data-akt');
                        if (akt === 'del') self.loeschen(nid);
                        else if (akt === 'deakt') self.deaktivieren(nid);
                        else self.formular(nid);
                    });
                });
            }
            // Ein offenes Formular ueberlebt das Neuzeichnen.
            if (this._offen !== null) this.formular(this._offen, true);
        },

        /** Formular aufklappen – unter der Zeile oder (neu) unter der Liste.
         *  Ein zweiter Klick auf denselben Knopf schliesst es wieder. */
        formular: function (nid, wieder) {
            var alt = $('nfadm-form');
            if (alt && !wieder && this._offen === (nid || '')) {
                this._offen = null; alt.remove(); return;
            }
            if (alt) alt.remove();
            this._offen = nid || '';
            var e = this._eintraege.find(function (x) { return x.id === nid; }) || {};
            var g = this._grenzen;
            var form = document.createElement('div');
            form.id = 'nfadm-form';
            form.className = 'am-vorg-form';
            form.innerHTML =
                '<div class="form-group"><label for="nfadm-f-titel">' + esc(t('nfadm.f_title', 'Überschrift')) + '</label>'
                + '<input type="text" id="nfadm-f-titel" maxlength="' + (g.titel_max || 80) + '"></div>'
                + '<div class="form-group"><label for="nfadm-f-text">' + esc(t('nfadm.f_text', 'Text')) + '</label>'
                + '<textarea id="nfadm-f-text" rows="3" maxlength="' + (g.text_max || 400) + '"></textarea>'
                + '<span class="kb-hint" id="nfadm-f-rest"></span></div>'
                + '<div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center;">'
                + '<button type="button" class="btn-primary" id="nfadm-f-save" style="flex:0 0 auto;">'
                + esc(t('common.save', 'Speichern')) + '</button>'
                + '<button type="button" class="btn-secondary" id="nfadm-f-cancel" style="flex:0 0 auto;">'
                + esc(t('common.cancel', 'Abbrechen')) + '</button>'
                + '<span id="nfadm-f-status" style="font-size:0.9em;"></span></div>';
            var karte = nid ? document.querySelector('#nfadm-liste .am-vorg-card[data-nid="' + nid.replace(/"/g, '') + '"]') : null;
            if (karte) karte.appendChild(form);
            else { var box = $('nfadm-liste'); if (box) box.appendChild(form); }
            // Werte per .value – nie ins Markup gebaut (Fremdtext).
            $('nfadm-f-titel').value = e.titel || '';
            $('nfadm-f-text').value = e.text || '';
            var self = this;
            var rest = function () {
                var max = g.text_max || 400, len = $('nfadm-f-text').value.length;
                $('nfadm-f-rest').textContent = t('nfadm.f_hint', 'Ein bis drei Sätze.') + ' '
                    + len + ' / ' + max;
            };
            $('nfadm-f-text').addEventListener('input', rest);
            rest();
            $('nfadm-f-save').addEventListener('click', function () { self.speichern(nid || ''); });
            $('nfadm-f-cancel').addEventListener('click', function () { self._offen = null; form.remove(); });
            $('nfadm-f-titel').focus();
        },

        speichern: function (nid) {
            var self = this;
            var body = { id: nid, titel: $('nfadm-f-titel').value, text: $('nfadm-f-text').value };
            status('nfadm-f-status', t('nfadm.saving', 'Speichere…'));
            return fetch('/api/newsfeed/admin/eintraege', {
                method: 'POST', headers: kopf({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(body)
            }).then(antwort).then(function () {
                self._offen = null;
                return self.laden().then(function () {
                    status('nfadm-status', t('common.saved', 'Gespeichert'), 'ok');
                });
            }).catch(function (e) {
                // Am Knopf, der es ausgeloest hat – und das Formular bleibt offen.
                status('nfadm-f-status', e.message, 'error');
            });
        },

        /** Deaktivieren – ohne Rueckfrage, es ist umkehrbar (Bearbeiten). */
        deaktivieren: function (nid) {
            var self = this;
            return fetch('/api/newsfeed/admin/eintraege/' + encodeURIComponent(nid) + '/deaktivieren', {
                method: 'POST', headers: kopf()
            }).then(antwort).then(function () {
                return self.laden().then(function () {
                    status('nfadm-status', t('nfadm.deactivated', 'Deaktiviert'), 'ok');
                });
            }).catch(function (err) {
                status('nfadm-status', err.message, 'error');
            });
        },

        loeschen: function (nid) {
            var e = this._eintraege.find(function (x) { return x.id === nid; });
            if (!e) return;
            if (!window.confirm(t('nfadm.del_confirm', 'Meldung wirklich löschen?') + '\n\n' + e.titel)) return;
            var self = this;
            return fetch('/api/newsfeed/admin/eintraege/' + encodeURIComponent(nid), {
                method: 'DELETE', headers: kopf()
            }).then(antwort).then(function () {
                if (self._offen === nid) self._offen = null;
                return self.laden();
            }).catch(function (err) {
                status('nfadm-status', err.message, 'error');
            });
        },

        _felder: function () {
            var alle = $('nfadm-anzahl-alle');
            // Eine Kommazahl geht unveraendert an den Server und wird dort mit
            // Grund abgewiesen – nicht hier still abgeschnitten.
            var anzahl = (alle && alle.checked) ? this._alle()
                : Number(($('nfadm-anzahl') || {}).value);
            return { verweil_s: parseFloat(($('nfadm-verweil') || {}).value),
                     scroll_s: parseFloat(($('nfadm-scroll') || {}).value),
                     anzahl: anzahl };
        },

        anzeigeSpeichern: function () {
            var self = this;
            status('nfadm-anz-status', t('nfadm.saving', 'Speichere…'));
            return fetch('/api/newsfeed/admin/einstellungen', {
                method: 'POST', headers: kopf({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(this._felder())
            }).then(antwort).then(function (d) {
                self._einst = d.einstellungen || {};
                self._felderSetzen(self._einst);
                status('nfadm-anz-status', t('common.saved', 'Gespeichert'), 'ok');
                // Die Marke „im Portal sichtbar" haengt an der Anzahl.
                self.liste();
                self.vorschau();
            }).catch(function (e) {
                status('nfadm-anz-status', e.message, 'error');
            });
        },

        vorschau: function () {
            var wurzel = $('nfadm-vorschau');
            if (!wurzel || !window.JarvisNewsfeed) return;
            if (this._vorschau) this._vorschau.stoppen();
            var leer = $('nfadm-vorschau-leer');
            var n = this._grenze(this._felder().anzahl);
            var liste = this._eintraege.filter(function (e) { return e.aktiv !== false; });
            if (n !== Infinity) liste = liste.slice(0, n);
            if (leer) leer.style.display = liste.length ? 'none' : '';
            this._vorschau = window.JarvisNewsfeed.ticker(wurzel, liste, this._felder());
        }
    };

    window.NewsfeedAdmin = Admin;
})();
