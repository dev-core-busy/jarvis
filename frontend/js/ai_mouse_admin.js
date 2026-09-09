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
        },

        bind: function () {
            if (this._gebunden) { return; }
            this._gebunden = true;
            var save = $('amtool-save');
            if (save) { save.addEventListener('click', this.saveAreas.bind(this)); }
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
        }
    };

    window.AiMouseAdmin = Admin;
})();
