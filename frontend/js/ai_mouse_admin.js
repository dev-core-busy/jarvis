/**
 * Einstellungs-Reiter „AI-Maus": Werkzeug-Bereiche freischalten.
 *
 * Zwilling des Containers „Werkzeug-Bereiche freischalten" im Jira-Reiter
 * (jira.js::renderAreas/saveAreas) – bewusst dieselbe Bauart, damit ein
 * Administrator beide Stellen ohne Umdenken bedient.
 *
 * ⚠ DER KATALOG KOMMT VOM SERVER, nicht aus i18n.js. Name, Hinweis und
 * Werkzeugliste stehen dort NEBEN der Werkzeug-Definition (backend/ai_mouse.py:
 * BEREICHE), damit Text und Wirkung nicht auseinanderlaufen – dieselbe
 * Begründung wie beim SAP-Analysekatalog. `applyLang()` erreicht sie deshalb
 * nicht: bei `jarvis-lang-changed` wird neu geholt.
 *
 * ⚠ ADMIN-ENDPUNKT, nicht /api/ai-mouse/health: dessen Freigabe kennt keinen
 * Admin-Bypass, und ein Administrator ohne eigene AI-Mouse-Freigabe könnte den
 * Reiter sonst nicht befüllen (Register: dieselbe Stelle wie beim SAP-Katalog).
 */
(function () {
    'use strict';

    function $(id) { return document.getElementById(id); }

    function esc(s) {
        var d = document.createElement('div');
        d.textContent = s == null ? '' : String(s);
        return d.innerHTML;
    }

    function t(key, fallback) {
        return (window.t ? window.t(key, fallback) : fallback) || fallback;
    }

    function authHeaders(extra) {
        var h = extra || {};
        try { h['Authorization'] = 'Bearer ' + (localStorage.getItem('jarvis_token') || ''); }
        catch (e) { /* ohne Token laeuft der Abruf in 401 – das meldet der Zweig unten. */ }
        return h;
    }

    function setStatus(id, text, art) {
        var el = $(id);
        if (!el) { return; }
        el.textContent = text || '';
        // Farbe UND Text: die Farbe allein ist keine Information (Projektregel).
        el.style.color = art === 'ok' ? 'var(--success)'
            : art === 'error' ? 'var(--danger)' : 'var(--text-secondary)';
    }

    var Admin = {
        _bereiche: null,
        _gebunden: false,

        /** Wird aus app.js gerufen – beim Reiter-Klick UND beim Öffnen des
         *  Modals. Beide Wege sind idempotent (Register: „KI & System" ist der
         *  vorbelegte Reiter, ein Modul, das nur am Klick hängt, bleibt leer). */
        onShow: function () {
            this.bind();
            this.load();
            this.vorgabenLaden();
        },

        bind: function () {
            if (this._gebunden) { return; }
            this._gebunden = true;
            var save = $('amtool-save');
            if (save) { save.addEventListener('click', this.saveAreas.bind(this)); }
            var neu = $('amvorg-neu');
            if (neu) { neu.addEventListener('click', function () { Admin.vorgabeFormular(null); }); }
            window.addEventListener('jarvis-lang-changed', function () {
                // Nur nachladen, wenn der Reiter überhaupt schon einmal
                // gefüllt wurde – sonst holt ein Sprachwechsel auf einer
                // anderen Seite den Katalog ohne Anlass.
                if (Admin._bereiche) { Admin.load(); }
            });
        },

        load: function () {
            var sprache = (window.getLang && window.getLang()) || 'de';
            var self = this;
            fetch('/api/ai-mouse/admin/areas?lang=' + encodeURIComponent(sprache),
                  { headers: authHeaders() })
                .then(function (r) {
                    if (!r.ok) {
                        return r.json().catch(function () { return null; }).then(function (d) {
                            throw new Error((d && (d.error || d.detail)) || ('HTTP ' + r.status));
                        });
                    }
                    return r.json();
                })
                .then(function (d) {
                    self._bereiche = d.bereiche || [];
                    self.renderAreas();
                    self.renderState(d);
                })
                .catch(function (e) {
                    // Ein Fehlschlag bleibt STEHEN. Ein leerer Container wäre
                    // von „es gibt keine Bereiche" nicht zu unterscheiden.
                    setStatus('amtool-status', e.message, 'error');
                });
        },

        renderAreas: function () {
            var box = $('amtool-areas');
            if (!box) { return; }
            var bs = this._bereiche || [];
            if (!bs.length) {
                box.innerHTML = '<span class="kb-hint">'
                    + esc(t('amtool.none', 'Keine Bereiche verfügbar.')) + '</span>';
                return;
            }
            // Die Werkzeugliste steht MIT da: ohne sie ist „Interne Fachsysteme"
            // eine Zusage, deren Umfang niemand prüfen kann.
            box.innerHTML = bs.map(function (b) {
                return '<label class="checkbox-group" style="align-items:flex-start;">'
                    + '<input type="checkbox" data-area="' + esc(b.id) + '"'
                    + (b.freigegeben ? ' checked' : '') + '>'
                    + '<span><b>' + esc(b.name) + '</b>'
                    + '<span class="kb-hint" style="display:block;">' + esc(b.hinweis || '') + '</span>'
                    + '<span class="kb-hint" style="display:block;opacity:.75;">'
                    + esc((b.werkzeuge || []).join(', ')) + '</span>'
                    + '</span></label>';
            }).join('');
        },

        /** Zustand: beantwortet „warum passiert nichts?" ohne einen Blick in
         *  die Skill-Liste oder aufs Portal. */
        renderState: function (d) {
            var box = $('amtool-state');
            if (!box) { return; }
            var zeilen = [];
            if (!d.skill_aktiv) {
                zeilen.push(t('amtool.st_off',
                    '⚠ Der Skill ist nicht aktiv – die Freigabe hier bleibt bis dahin wirkungslos.'));
            } else {
                zeilen.push(t('amtool.st_on', '✓ Der Skill ist aktiv.'));
            }
            if (!d.paket_bereit) {
                // ⚠ KEINE AUFFORDERUNG ZUR HANDARBEIT. Der Bau laeuft von
                // selbst (Startup-Haken, Bootstrap-Schritt 6g, auf Bedarf) –
                // ein Satz, der einen Befehl zum Abtippen nennt, schickt den
                // Administrator zu einer Arbeit, die es nicht gibt.
                zeilen.push(t('amtool.st_nopkg',
                    '⏳ Die Anwendung wird gerade gebaut – der Download im Portal erscheint danach von selbst.'));
            } else {
                zeilen.push(t('amtool.st_pkg', '✓ Die Anwendung liegt zum Download bereit.'));
            }
            box.innerHTML = zeilen.map(function (z) {
                return '<p class="kb-hint">' + esc(z) + '</p>';
            }).join('');
        },

        /** Eigener Knopf, eigene TEILMENGE – wie im Jira-Reiter. Der Endpunkt
         *  schreibt nur das Freigabe-Feld; ein Knopf mit dem ganzen
         *  Formularstand überschriebe andere Skill-Einstellungen (Register). */
        saveAreas: function () {
            var gewaehlt = [];
            document.querySelectorAll('#amtool-areas input[data-area]').forEach(function (c) {
                if (c.checked) { gewaehlt.push(c.getAttribute('data-area')); }
            });
            setStatus('amtool-status', t('common.saving', 'Speichere…'));
            var self = this;
            fetch('/api/ai-mouse/admin/areas', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ bereiche: gewaehlt })
            }).then(function (r) { return r.json(); })
              .then(function (d) {
                    if (!d || d.ok === false) {
                        throw new Error((d && (d.error || d.detail)) || 'Fehler');
                    }
                    // Der GESPEICHERTE Stand, nicht der gesendete: nur so fällt
                    // auf, wenn ein Bereich verworfen wurde.
                    setStatus('amtool-status', t('amtool.saved', '✓ Freigegeben:') + ' '
                        + ((d.bereiche || []).join(', ') || t('amtool.nothing', 'nichts')), 'ok');
                    // Neu laden: die Kästchen müssen den wirklich gültigen Stand
                    // zeigen, nicht den geklickten.
                    return self.load();
              })
              .catch(function (e) { setStatus('amtool-status', e.message, 'error'); });
        },

        // ── Vorgabe-Fragen ───────────────────────────────────────────────────
        // Die VORLAGE fuer neue Benutzer. Bauform bewusst wie die Vorlagenliste
        // im Jira-Reiter: eine Zeile je Eintrag, das Formular klappt DIREKT
        // darunter auf – EIN Container, der wandert (zwei waeren zwei Wege zum
        // Speichern, Register).
        _vorgaben: null,
        _vorgOffen: null,   // Kennung der gerade bearbeiteten Vorgabe ('' = neu)

        vorgabenLaden: function () {
            var self = this;
            fetch('/api/ai-mouse/admin/vorgaben', { headers: authHeaders() })
                .then(function (r) {
                    if (!r.ok) {
                        return r.json().catch(function () { return null; }).then(function (d) {
                            throw new Error((d && (d.error || d.detail)) || ('HTTP ' + r.status));
                        });
                    }
                    return r.json();
                })
                .then(function (d) {
                    self._vorgaben = d.vorgaben || [];
                    self.vorgabenZeichnen();
                })
                .catch(function (e) {
                    // ⚠ Ein Ladefehler bleibt STEHEN und die Liste wird NICHT
                    // geleert: eine leere Liste waere von "es gibt keine
                    // Vorgaben" nicht zu unterscheiden – und wer darauf eine
                    // anlegt, haelt den Bestand fuer weg.
                    setStatus('amvorg-status', e.message, 'error');
                });
        },

        vorgabenZeichnen: function () {
            var box = $('amvorg-liste');
            if (!box) { return; }
            var vs = this._vorgaben || [];
            if (!vs.length) {
                box.innerHTML = '<p class="kb-hint">'
                    + esc(t('amvorg.empty',
                            'Keine Vorgaben – neue Benutzer starten dann mit einem leeren Menü.'))
                    + '</p>';
                return;
            }
            box.innerHTML = vs.map(function (v) {
                return '<div class="am-vorg-card" data-vid="' + esc(v.id) + '">'
                    + '<div class="am-vorg-row">'
                    + '<div class="am-vorg-main"><b>' + esc(v.titel) + '</b>'
                    + '<span class="kb-hint" style="display:block;">' + esc(v.prompt) + '</span>'
                    + '</div>'
                    + '<button type="button" class="am-vorg-act" data-akt="edit" title="'
                    + esc(t('common.edit', 'Bearbeiten')) + '">✎</button>'
                    + '<button type="button" class="am-vorg-act" data-akt="del" title="'
                    + esc(t('common.delete', 'Löschen')) + '">'
                    + window.JarvisIcons.trash() + '</button>'
                    + '</div></div>';
            }).join('');
            box.querySelectorAll('.am-vorg-act').forEach(function (b) {
                b.addEventListener('click', function () {
                    var karte = b.closest('.am-vorg-card');
                    var vid = karte ? karte.getAttribute('data-vid') : '';
                    if (b.getAttribute('data-akt') === 'del') { Admin.vorgabeLoeschen(vid); }
                    else { Admin.vorgabeFormular(vid); }
                });
            });
            // Ein offenes Formular ueberlebt das Neuzeichnen – sonst schliesst
            // sich der Kasten bei jedem Speichern eines Nachbarn.
            if (this._vorgOffen !== null) { this.vorgabeFormular(this._vorgOffen, true); }
        },

        /** Formular unter der Zeile aufklappen. Zweiter Klick schliesst –
         *  sonst tut der Knopf sichtbar nichts. */
        vorgabeFormular: function (vid, wieder) {
            var alt = $('amvorg-form');
            if (alt && !wieder && this._vorgOffen === (vid || '')) {
                this._vorgOffen = null;
                alt.remove();
                return;
            }
            if (alt) { alt.remove(); }
            this._vorgOffen = vid || '';
            var v = (this._vorgaben || []).find(function (x) { return x.id === vid; }) || {};
            var form = document.createElement('div');
            form.id = 'amvorg-form';
            form.className = 'am-vorg-form';
            form.innerHTML =
                '<div class="form-group"><label>' + esc(t('amvorg.f_titel', 'Titel (Menüzeile)'))
                + '</label><input type="text" id="amvorg-f-titel" maxlength="80"></div>'
                + '<div class="form-group"><label>' + esc(t('amvorg.f_prompt', 'Anweisung an das Modell'))
                + '</label><textarea id="amvorg-f-prompt" rows="4" maxlength="2000"></textarea></div>'
                + '<div style="display:flex;gap:10px;flex-wrap:wrap;">'
                + '<button type="button" class="btn-primary" id="amvorg-f-save">'
                + esc(t('common.save', 'Speichern')) + '</button>'
                + '<button type="button" class="btn-secondary" id="amvorg-f-abort">'
                + esc(t('common.cancel', 'Abbrechen')) + '</button></div>';
            // ⚠ Werte per .value setzen, NICHT ins Markup interpolieren: ein
            // Anführungszeichen im Titel sprengt sonst das Attribut.
            var karte = vid
                ? document.querySelector('.am-vorg-card[data-vid="' + vid + '"]')
                : null;
            if (karte) { karte.appendChild(form); }
            else { ($('amvorg-liste') || document.body).appendChild(form); }
            var ti = $('amvorg-f-titel'), pr = $('amvorg-f-prompt');
            if (ti) { ti.value = v.titel || ''; }
            if (pr) { pr.value = v.prompt || ''; }
            var sv = $('amvorg-f-save'), ab = $('amvorg-f-abort');
            if (sv) { sv.addEventListener('click', function () { Admin.vorgabeSpeichern(vid || ''); }); }
            if (ab) {
                ab.addEventListener('click', function () {
                    Admin._vorgOffen = null;
                    var f = $('amvorg-form');
                    if (f) { f.remove(); }
                });
            }
            if (ti && !wieder) { ti.focus(); }
        },

        vorgabeSpeichern: function (vid) {
            var ti = $('amvorg-f-titel'), pr = $('amvorg-f-prompt');
            if (!ti || !pr) { return; }
            setStatus('amvorg-status', t('common.saving', 'Speichere…'));
            var self = this;
            fetch('/api/ai-mouse/admin/vorgaben', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ id: vid || '', titel: ti.value, prompt: pr.value })
            }).then(function (r) { return r.json(); })
              .then(function (d) {
                    if (!d || d.ok === false) {
                        throw new Error((d && (d.error || d.detail)) || 'Fehler');
                    }
                    self._vorgOffen = null;
                    var f = $('amvorg-form');
                    if (f) { f.remove(); }
                    setStatus('amvorg-status', t('amvorg.saved', '✓ Gespeichert.'), 'ok');
                    return self.vorgabenLaden();
              })
              .catch(function (e) { setStatus('amvorg-status', e.message, 'error'); });
        },

        vorgabeLoeschen: function (vid) {
            var v = (this._vorgaben || []).find(function (x) { return x.id === vid; }) || {};
            if (!window.confirm(t('amvorg.del_ask', 'Vorgabe „{t}" wirklich löschen?')
                    .replace('{t}', v.titel || ''))) { return; }
            var self = this;
            fetch('/api/ai-mouse/admin/vorgaben/' + encodeURIComponent(vid),
                  { method: 'DELETE', headers: authHeaders() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d || d.ok === false) {
                        throw new Error((d && (d.error || d.detail)) || 'Fehler');
                    }
                    if (self._vorgOffen === vid) { self._vorgOffen = null; }
                    setStatus('amvorg-status', t('amvorg.deleted', '✓ Entfernt.'), 'ok');
                    return self.vorgabenLaden();
                })
                .catch(function (e) { setStatus('amvorg-status', e.message, 'error'); });
        }
    };

    window.AiMouseAdmin = Admin;
})();
