/* ═══════════════════════════════════════════════════════════════════════
   Einstellungen → Newsfeed: Meldungen pflegen, Verweil- und Scrolldauer
   einstellen, Vorschau. Daten ueber /api/newsfeed/admin/* (nur Admins).

   ⚠ DIE VORSCHAU ZEICHNET MIT DEM ECHTEN LAUFBAND (newsfeed.js) – keine
   Nachbildung. Sie benutzt die Werte aus den FELDERN, nicht die
   gespeicherten: wer an der Geschwindigkeit dreht, will die Wirkung sehen,
   bevor er speichert.

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
        _offen: null,        // Kennung des aufgeklappten Formulars ('' = neu)
        _vorschau: null,

        onShow: function () { this._binden(); this.laden(); },

        _binden: function () {
            if (this._gebunden) return;
            this._gebunden = true;
            var self = this;
            var neu = $('nfadm-neu');
            if (neu) neu.addEventListener('click', function () { self.formular(''); });
            var sp = $('nfadm-anz-save');
            if (sp) sp.addEventListener('click', function () { self.anzeigeSpeichern(); });
            ['nfadm-verweil', 'nfadm-scroll'].forEach(function (id) {
                var f = $(id);
                if (f) f.addEventListener('input', function () { self.vorschau(); });
            });
        },

        laden: function () {
            var self = this;
            return fetch('/api/newsfeed/admin', { headers: kopf() })
                .then(antwort)
                .then(function (d) {
                    self._eintraege = d.eintraege || [];
                    self._grenzen = d.grenzen || {};
                    var e = d.einstellungen || {};
                    if ($('nfadm-verweil')) $('nfadm-verweil').value = e.verweil_s;
                    if ($('nfadm-scroll')) $('nfadm-scroll').value = e.scroll_s;
                    var aus = $('nfadm-skill-aus');
                    if (aus) aus.style.display = d.skill_aktiv ? 'none' : '';
                    self.liste();
                    self.vorschau();
                })
                .catch(function (e) {
                    status('nfadm-status', t('nfadm.load_err', 'Laden fehlgeschlagen') + ': ' + e.message, 'error');
                });
        },

        _anzahl: function () { return this._grenzen.anzeige || 3; },

        liste: function () {
            var box = $('nfadm-liste'); if (!box) return;
            var self = this, n = this._anzahl();
            if (!this._eintraege.length) {
                box.innerHTML = '<p class="kb-hint">'
                    + esc(t('nfadm.empty', 'Noch keine Meldungen.')) + '</p>';
            } else {
                box.innerHTML = this._eintraege.map(function (e, i) {
                    // Sichtbar im Portal sind die ersten n (der Server liefert
                    // neueste zuerst) – als Text, nicht nur als Farbe.
                    var marke = i < n
                        ? ' <span class="kb-hint" style="color:var(--success);">· '
                          + esc(t('nfadm.visible', 'im Portal sichtbar')) + '</span>'
                        : '';
                    return '<div class="am-vorg-card" data-nid="' + esc(e.id) + '">'
                        + '<div class="am-vorg-row">'
                        + '<div class="am-vorg-main"><b>' + esc(e.titel) + '</b>'
                        + '<span class="kb-hint" style="display:block;">' + esc(e.text) + '</span>'
                        + '<span class="kb-hint" style="display:block;font-size:.8em;">'
                        + esc(t('nfadm.created', 'Erstellt')) + ': '
                        + esc(window.JarvisNewsfeed ? window.JarvisNewsfeed.datum(e.erstellt) : e.erstellt)
                        + marke + '</span>'
                        + '</div>'
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
                        if (b.getAttribute('data-akt') === 'del') self.loeschen(nid);
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
            return { verweil_s: parseFloat(($('nfadm-verweil') || {}).value),
                     scroll_s: parseFloat(($('nfadm-scroll') || {}).value) };
        },

        anzeigeSpeichern: function () {
            var self = this;
            status('nfadm-anz-status', t('nfadm.saving', 'Speichere…'));
            return fetch('/api/newsfeed/admin/einstellungen', {
                method: 'POST', headers: kopf({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(this._felder())
            }).then(antwort).then(function (d) {
                var e = d.einstellungen || {};
                $('nfadm-verweil').value = e.verweil_s;
                $('nfadm-scroll').value = e.scroll_s;
                status('nfadm-anz-status', t('common.saved', 'Gespeichert'), 'ok');
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
            var liste = this._eintraege.slice(0, this._anzahl());
            if (leer) leer.style.display = liste.length ? 'none' : '';
            this._vorschau = window.JarvisNewsfeed.ticker(wurzel, liste, this._felder());
        }
    };

    window.NewsfeedAdmin = Admin;
})();
