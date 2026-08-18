/* ═══════════════════════════════════════════════════════════════════
   Short Tracks – Einstellungs-Reiter (Administrator)
   ───────────────────────────────────────────────────────────────────
   Hier stehen NUR die Dinge, die alle Benutzer betreffen:
     1. Grenzen (gleichzeitige Auftraege, Groesse, Anzahl)
     2. Freigabe der Werkzeug-Bereiche
     3. Uebersicht (globale Ablagen, Anzahl je Benutzer, Warteschlange)

   Die Ablagen selbst pflegt jeder im Bereich /tracks – auch der
   Administrator. Dieser Reiter zeigt absichtlich KEINE fremden
   Aufgaben-Texte: er ist zum Einrichten da, nicht zum Mitlesen (gleiche
   Entscheidung wie beim E-Mail-Reiter).

   ZWEI KNOEPFE, ZWEI TEILMENGEN: „Grenzen speichern" sendet nie
   `bereiche`, „Freigabe speichern" nie die Zahlen. Der Server merged
   (`update_skill_config`) – ein Knopf mit dem ganzen Formularstand
   ueberschriebe den jeweils anderen Teil (dieselbe Trennung wie bei den
   E-Mail-Bereichen und den SAP-Sichtbarkeiten).
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    var _daten = null;
    var _gebunden = false;
    var _lang = '';           // in welcher Sprache gezeichnet wurde
    var _laeuft = false;      // ein Abruf ist unterwegs

    function $(id) { return document.getElementById(id); }
    function token() { return localStorage.getItem('jarvis_token') || ''; }
    function kopf(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function T(key, fallback) {
        var s = window.t ? window.t(key) : null;
        return (s && s !== key) ? s : fallback;
    }
    function sprache() { return (window._lang === 'en') ? 'en' : 'de'; }
    function melde(id, text, art) {
        var e = $(id);
        if (!e) return;
        e.textContent = text || '';
        e.style.color = art === 'ok' ? 'var(--success)'
            : art === 'fehler' ? 'var(--danger)' : 'var(--text-muted)';
    }
    function hole(url, opt) {
        return fetch(url, Object.assign({ headers: kopf() }, opt || {}))
            .then(function (r) {
                return r.json().catch(function () { return {}; })
                    .then(function (d) {
                        if (!r.ok || d.ok === false) throw new Error(d.error || ('HTTP ' + r.status));
                        return d;
                    });
            });
    }
    function sende(url, daten) {
        return hole(url, {
            method: 'POST',
            headers: kopf({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(daten || {})
        });
    }

    function laden() {
        // `_lang` wird SCHON HIER gesetzt, nicht erst in `zeichne()`. Sonst
        // faellt ein `applyLang()` (von irgendwoher) in das Zeitfenster, in dem
        // der Abruf noch laeuft: der Lang-Zuhoerer sieht dann ein leeres `_lang`,
        // haelt das fuer einen Sprachwechsel und laedt ein zweites Mal – gemessen
        // am 2026-08-18 als doppelter Abruf beim Oeffnen des Reiters.
        _lang = sprache();
        // Und ein zweiter Abruf waehrend des ersten bringt nichts: die Antwort
        // ueberschreibt dieselben Felder, kann aber eine gerade gesetzte
        // Auswahl verwerfen.
        if (_laeuft) return Promise.resolve();
        _laeuft = true;
        return hole('/api/tracks/admin/overview?lang=' + sprache()).then(function (d) {
            _daten = d;
            zeichne();
        }).catch(function (e) {
            melde('tr-msg-over', e.message, 'fehler');
        }).then(function () {
            _laeuft = false;
        });
    }

    function zeichne() {
        if (!_daten) return;
        _lang = sprache();
        var g = _daten.grenzen || {};
        if ($('tr-l-parallel')) $('tr-l-parallel').value = g.gleichzeitig || 2;
        if ($('tr-l-size')) $('tr-l-size').value = g.max_datei_mb || 50;
        if ($('tr-l-files')) $('tr-l-files').value = g.max_dateien || 20;
        if ($('tr-l-dumps')) $('tr-l-dumps').value = g.max_dumps || 10;

        var box = $('tr-areas');
        if (box) {
            box.innerHTML = (_daten.bereiche || []).map(function (b) {
                // Der Pflicht-Bereich ist angehakt und gesperrt: ohne Lese- und
                // Erzeugungswerkzeuge koennte eine Ablage nichts tun, und ein
                // abwaehlbares Pflichtfeld waere eine Zusage, die nicht gilt.
                return '<label class="checkbox-group" style="align-items:flex-start;">' +
                    '<input type="checkbox" data-area="' + esc(b.id) + '"' +
                    ((b.freigegeben || b.pflicht) ? ' checked' : '') +
                    (b.pflicht ? ' disabled' : '') + '>' +
                    '<span><b>' + esc(b.name) + '</b>' +
                    (b.pflicht ? ' <span class="kb-hint">(' +
                        esc(T('tracksadm.required', 'Pflicht')) + ')</span>' : '') +
                    '<span class="kb-hint" style="display:block;">' + esc(b.hinweis) + '</span>' +
                    '<span class="kb-hint" style="display:block;opacity:.75;">' +
                    esc((b.werkzeuge || []).join(', ')) + '</span>' +
                    '</span></label>';
            }).join('');
        }

        var over = $('tr-over');
        if (over) {
            var gl = _daten['global'] || [];
            var bu = _daten.benutzer || [];
            var teile = [];
            teile.push('<p class="kb-hint"><b>' +
                esc(T('tracksadm.queue', 'Warteschlange')) + ':</b> ' +
                esc(T('tracksadm.queue_state', '{a} laufend, {w} wartend')
                    .replace(/\{a\}/g, _daten.laufend || 0)
                    .replace(/\{w\}/g, _daten.wartend || 0)) + '</p>');
            teile.push('<p class="kb-hint" style="margin-top:8px;"><b>' +
                esc(T('tracksadm.global_dumps', 'Ablagen für alle')) + ' (' + gl.length + ')</b></p>');
            teile.push(gl.length
                ? '<ul style="margin:4px 0 0 1.1rem;font-size:.85rem;">' + gl.map(function (d) {
                    return '<li>' + esc(d.name) +
                        (d.enabled ? '' : ' <span class="kb-hint">(' +
                            esc(T('tracksadm.off', 'inaktiv')) + ')</span>') +
                        ' <span class="kb-hint">· ' + esc((d.bereiche || []).join(', ')) +
                        ' · ' + (d.laeufe || 0) + ' ' + esc(T('tracksadm.runs', 'Läufe')) +
                        '</span></li>';
                }).join('') + '</ul>'
                : '<p class="kb-hint">' + esc(T('tracksadm.none_global',
                    'Keine – jeder Benutzer arbeitet mit eigenen Ablagen.')) + '</p>');
            teile.push('<p class="kb-hint" style="margin-top:10px;"><b>' +
                esc(T('tracksadm.per_user', 'Eigene Ablagen je Benutzer')) + '</b></p>');
            teile.push(bu.length
                ? '<ul style="margin:4px 0 0 1.1rem;font-size:.85rem;">' + bu.map(function (u) {
                    return '<li>' + esc(u.owner) + ': ' + (u.anzahl || 0) + '</li>';
                }).join('') + '</ul>'
                : '<p class="kb-hint">' + esc(T('tracksadm.none_user', 'Noch keine.')) + '</p>');
            over.innerHTML = teile.join('');
        }
        if (window.applyLang) window.applyLang();
    }

    function speichereGrenzen() {
        melde('tr-msg-limits', T('tracksadm.saving', 'Wird gespeichert …'));
        sende('/api/tracks/admin/limits', {
            gleichzeitig: parseInt($('tr-l-parallel').value || '2', 10),
            max_datei_mb: parseInt($('tr-l-size').value || '50', 10),
            max_dateien: parseInt($('tr-l-files').value || '20', 10),
            max_dumps: parseInt($('tr-l-dumps').value || '10', 10)
        }).then(function () {
            melde('tr-msg-limits', T('tracksadm.saved', '✓ Gespeichert.'), 'ok');
            return laden();
        }).catch(function (e) {
            melde('tr-msg-limits', e.message, 'fehler');
        });
    }

    function speichereBereiche() {
        var gewaehlt = [];
        document.querySelectorAll('#tr-areas input[data-area]').forEach(function (c) {
            if (c.checked) gewaehlt.push(c.getAttribute('data-area'));
        });
        melde('tr-msg-areas', T('tracksadm.saving', 'Wird gespeichert …'));
        sende('/api/tracks/admin/areas', { bereiche: gewaehlt }).then(function (d) {
            melde('tr-msg-areas', T('tracksadm.areas_saved', '✓ Freigegeben:') + ' ' +
                (d.bereiche || []).join(', '), 'ok');
            return laden();
        }).catch(function (e) {
            melde('tr-msg-areas', e.message, 'fehler');
        });
    }

    function nothalt() {
        if (!window.confirm(T('tracksadm.stop_ask',
            'Alle laufenden Aufträge abbrechen? Wartende Aufträge laufen danach normal weiter.'))) return;
        sende('/api/tracks/admin/stop', {}).then(function (d) {
            melde('tr-msg-over', T('tracksadm.stopped', '{n} Auftrag/Aufträge abgebrochen.')
                .replace(/\{n\}/g, d.abgebrochen || 0), 'ok');
            return laden();
        }).catch(function (e) {
            melde('tr-msg-over', e.message, 'fehler');
        });
    }

    function binde() {
        if (_gebunden) return;
        _gebunden = true;
        var b;
        if ((b = $('tr-save-limits'))) b.addEventListener('click', speichereGrenzen);
        if ((b = $('tr-save-areas'))) b.addEventListener('click', speichereBereiche);
        if ((b = $('tr-reload'))) b.addEventListener('click', laden);
        if ((b = $('tr-stop'))) b.addEventListener('click', nothalt);
        // Der Bereichskatalog kommt vom SERVER (Name und Hinweis stehen dort
        // neben der Werkzeugliste). `applyLang()` erreicht ihn nicht – ohne
        // diesen Zuhoerer bliebe er in der Sprache, in der die Seite geladen
        // wurde (Lehre vom 2026-08-13).
        window.addEventListener('jarvis-lang-changed', function () {
            // DER SPRACHVERGLEICH IST PFLICHT, nicht Feinschliff.
            // GEMELDET am 2026-08-18: im Reiter liess sich kein Haken setzen.
            // Ursache war eine ENDLOSSCHLEIFE – `zeichne()` ruft `applyLang()`,
            // und `applyLang()` feuert `jarvis-lang-changed`. Ohne diesen
            // Vergleich rief das Ereignis wieder `laden()`, der Reiter baute
            // sich unentwegt neu auf, und jeder gesetzte Haken war im naechsten
            // Durchlauf weg. Gemessen: >40 Abrufe von /admin/overview in 250 ms.
            // `email.js` und `sap_portal.js` haben denselben Vergleich – nur
            // dieses Modul hatte ihn nicht.
            if (sprache() === _lang) return;
            if ($('settings-tab-tracks') &&
                $('settings-tab-tracks').style.display !== 'none') laden();
        });
    }

    window.TracksAdmin = {
        /* Idempotent – wird bei jedem Reiter-Klick gerufen. */
        onShow: function () {
            binde();
            if (window.initTracksCollapse) window.initTracksCollapse();
            laden();
        }
    };
})();
