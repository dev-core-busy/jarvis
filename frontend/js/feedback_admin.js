/**
 * Einstellungs-Reiter „Feedback": Formulare definieren, Abgaben auswerten.
 *
 * Bauform der Listen 1:1 wie „AI-Maus → Meine Fragen" (`ai_mouse.js`) und die
 * Vorgabe-Liste in `ai_mouse_admin.js`: eine Karte je Eintrag, das Formular
 * klappt DIREKT darunter auf – EIN Container, der wandert (zwei waeren zwei
 * Wege zum Speichern, Register). Dazu ein Ziehgriff fuer die Reihenfolge.
 *
 * ⚠ ADMIN-ENDPUNKTE (`/api/feedback/admin/*`, `require_local_auth`) und NICHT
 * `/api/feedback/*`: die Bereichs-Freigabe kennt bewusst keinen Admin-Bypass,
 * ein Administrator ohne eigene Feedback-Freigabe koennte die Formulare sonst
 * gar nicht pflegen – dieselbe Stelle und dieselbe Begruendung wie beim
 * SAP-Analysekatalog und bei `/api/ai-mouse/admin/areas`.
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

    /** Fehlertext aus einer Serverantwort. Jarvis benutzt `error`, FastAPI
     *  `detail` – nur eines zu lesen laesst eine vorhandene Begruendung
     *  verschwinden (Register). */
    function fehlertext(d, rueckfall) {
        if (!d) { return rueckfall; }
        return d.error || d.detail || d.message || rueckfall;
    }

    function setStatus(id, text, art) {
        var el = $(id);
        if (!el) { return; }
        el.textContent = text || '';
        // Farbe UND Text: die Farbe allein ist keine Information (Projektregel).
        el.style.color = art === 'ok' ? 'var(--success)'
            : art === 'error' ? 'var(--danger)' : 'var(--text-secondary)';
    }

    function json(r) {
        return r.json().catch(function () { return null; }).then(function (d) {
            if (!r.ok || !d || d.ok === false) {
                throw new Error(fehlertext(d, 'HTTP ' + r.status));
            }
            return d;
        });
    }

    // ── Ziehen: EINE Mechanik fuer beide Listen ────────────────────────────
    //
    // Sie wird von der Formular-Liste (gespeicherte Reihenfolge) UND von der
    // Spalten-Liste im Editor (Arbeitsstand) benutzt. Zwei Fassungen waeren
    // beim naechsten Feinschliff auseinandergelaufen – dieselbe Ueberlegung
    // wie bei den vier `_client()`-Stellen des Jira-Zugangs.
    var _zieht = null;

    function nachbarKarte(karte, schritt, klasse) {
        var n = (schritt < 0) ? karte.previousElementSibling : karte.nextElementSibling;
        while (n && !n.classList.contains(klasse)) {
            n = (schritt < 0) ? n.previousElementSibling : n.nextElementSibling;
        }
        return n;
    }

    function karteSchieben(karte, schritt, klasse) {
        var nachbar = nachbarKarte(karte, schritt, klasse);
        if (!nachbar) { return false; }
        var box = karte.parentNode;
        if (schritt < 0) { box.insertBefore(karte, nachbar); }
        else { box.insertBefore(karte, nachbar.nextElementSibling); }
        return true;
    }

    /** Ziehgriffe und Ablegeziele binden.
     *
     *  `klasse` ist die Karten-Klasse, `beiAenderung(box)` wird nach jeder
     *  Verschiebung gerufen (speichern bzw. Arbeitsstand uebernehmen).
     */
    function ziehenBinden(box, klasse, beiAenderung) {
        box.querySelectorAll('.fb-griff[draggable="true"]').forEach(function (g) {
            var karte = g.closest('.' + klasse);
            if (!karte) { return; }

            g.addEventListener('dragstart', function (ev) {
                _zieht = karte;
                karte.classList.add('is-zieht');
                // Ohne Nutzlast bricht Firefox das Ziehen ab.
                try {
                    ev.dataTransfer.setData('text/plain', karte.getAttribute('data-id') || '');
                    ev.dataTransfer.effectAllowed = 'move';
                } catch (e) { /* aeltere Browser */ }
            });
            g.addEventListener('dragend', function () {
                karte.classList.remove('is-zieht');
                _zieht = null;
                box.querySelectorAll('.is-ziel').forEach(function (x) {
                    x.classList.remove('is-ziel');
                });
            });

            // ⚠ TASTATUR: ein Ziehgriff allein ist nicht bedienbar – ohne Maus
            // (und auf einem Touch-Geraet) gaebe es GAR KEINEN Weg, die
            // Reihenfolge zu aendern.
            g.addEventListener('keydown', function (ev) {
                if (!ev.ctrlKey || (ev.key !== 'ArrowUp' && ev.key !== 'ArrowDown')) {
                    return;
                }
                ev.preventDefault();
                if (karteSchieben(karte, ev.key === 'ArrowUp' ? -1 : 1, klasse)) {
                    var id = karte.getAttribute('data-id');
                    var fertig = beiAenderung(box);
                    // Den Fokus mitnehmen: nach einem Neuzeichnen ist der Griff
                    // ein anderes Element, sonst landet ein zweiter Druck im
                    // Nichts (Register).
                    Promise.resolve(fertig).then(function () {
                        var neu = document.querySelector(
                            '.' + klasse + '[data-id="' + id + '"] .fb-griff');
                        if (neu && neu.focus) { neu.focus(); }
                    });
                }
            });
        });

        box.querySelectorAll('.' + klasse).forEach(function (ziel) {
            ziel.addEventListener('dragover', function (ev) {
                if (!_zieht || ziel === _zieht) { return; }
                if (!ziel.classList.contains(klasse)) { return; }
                ev.preventDefault();          // erst das erlaubt das Ablegen
                ziel.classList.add('is-ziel');
            });
            ziel.addEventListener('dragleave', function () {
                ziel.classList.remove('is-ziel');
            });
            ziel.addEventListener('drop', function (ev) {
                ziel.classList.remove('is-ziel');
                if (!_zieht || ziel === _zieht) { return; }
                ev.preventDefault();
                // Ober- oder untere Haelfte entscheidet, ob davor oder dahinter
                // eingefuegt wird – sonst laesst sich der letzte Platz nicht
                // erreichen.
                var r = ziel.getBoundingClientRect();
                var unten = (ev.clientY - r.top) > (r.height / 2);
                ziel.parentNode.insertBefore(_zieht, unten ? ziel.nextElementSibling : ziel);
                beiAenderung(box);
            });
        });
    }

    function griffMarkup(titel) {
        return '<span class="fb-griff" draggable="true" tabindex="0" role="button" '
            + 'title="' + esc(titel) + '" aria-label="' + esc(titel) + '">&#10287;</span>';
    }

    // ⚠ DRIFT-SCHRANKE: `TYP_FEST` steht ebenso in `backend/feedback.py` und in
    // `feedback.js`. Der Katalog vom Server (`_typen`) liefert die LISTE der
    // Typen – welcher davon Zeilenwerte braucht, muss der Editor aber kennen.
    var TYP_FEST = 'fest';

    /** Eine Kennung, die der Client selbst vergibt.
     *
     *  ⚠ NOETIG, NICHT BEQUEM: beim ANLEGEN eines Formulars mit festen Zeilen
     *  muss der Zeilenwert bereits unter einer Spalten-Kennung stehen – die
     *  vergibt sonst erst der Server, also nach dem Speichern. Alphanumerisch
     *  und kurz, weil `_spalten_pruefen` genau das verlangt und eine unbrauchbare
     *  Kennung serverseitig NEU vergeben wuerde (womit die Zeilenwerte ins
     *  Leere zeigten).
     */
    function neueKennung() {
        return 'c' + Math.random().toString(36).slice(2, 10)
            + Date.now().toString(36).slice(-4);
    }

    var Admin = {
        _formulare: null,
        _typen: ['text', 'sterne', 'fest'],
        _maxSpalten: 12,
        _maxZeilen: 50,
        _offen: null,        // Kennung des gerade bearbeiteten Formulars ('' = neu)
        _entwurf: null,      // Spalten-Arbeitsstand des offenen Editors
        _zeilen: null,       // Arbeitsstand der FESTEN Zeilen
        _gebunden: false,
        _abgaben: null,
        _abgFid: '',

        /** Wird aus app.js gerufen – beim Reiter-Klick UND beim Oeffnen des
         *  Modals. Beide Wege sind idempotent (Register: „KI & System" ist der
         *  vorbelegte Reiter, ein Modul, das nur am Klick haengt, bleibt leer). */
        onShow: function () {
            this.bind();
            this.laden();
        },

        bind: function () {
            if (this._gebunden) { return; }
            this._gebunden = true;
            var neu = $('fbadm-neu');
            if (neu) { neu.addEventListener('click', function () { Admin.editor(''); }); }
            var sel = $('fbadm-abg-sel');
            if (sel) {
                sel.addEventListener('change', function () {
                    Admin._abgFid = sel.value;
                    Admin.abgabenLaden();
                });
            }
            var exp = $('fbadm-export');
            if (exp) { exp.addEventListener('click', this.exportieren.bind(this)); }
        },

        laden: function () {
            var self = this;
            fetch('/api/feedback/admin/formulare', { headers: authHeaders() })
                .then(json)
                .then(function (d) {
                    self._formulare = d.formulare || [];
                    if (Array.isArray(d.typen) && d.typen.length) { self._typen = d.typen; }
                    if (d.max_spalten) { self._maxSpalten = d.max_spalten; }
                    if (d.max_feste_zeilen) { self._maxZeilen = d.max_feste_zeilen; }
                    self.zeichnen();
                    self.zustandZeichnen(d);
                    self.abgabenAuswahl();
                })
                .catch(function (e) {
                    // ⚠ Ein Ladefehler bleibt STEHEN und die Liste wird NICHT
                    // geleert: eine leere Liste waere von „es gibt keine
                    // Formulare" nicht zu unterscheiden – und wer darauf eines
                    // anlegt, haelt den Bestand fuer weg (Register).
                    setStatus('fbadm-status', e.message, 'error');
                });
        },

        /** Zustand: beantwortet „warum sieht niemand das Formular?" ohne einen
         *  Blick in die Skill-Liste. */
        zustandZeichnen: function (d) {
            var box = $('fbadm-state');
            if (!box) { return; }
            var zeilen = [];
            if (!d.skill_aktiv) {
                zeilen.push(t('fbadm.st_off',
                    '⚠ Der Skill „Feedback" ist nicht aktiv – die Kachel erscheint bei niemandem, und die Formulare hier bleiben bis dahin wirkungslos.'));
            } else {
                zeilen.push(t('fbadm.st_on', '✓ Der Skill ist aktiv.'));
            }
            box.innerHTML = zeilen.map(function (z) {
                return '<p class="kb-hint">' + esc(z) + '</p>';
            }).join('');
        },

        // ── Formular-Liste ────────────────────────────────────────────────

        zeichnen: function () {
            var box = $('fbadm-liste');
            if (!box) { return; }
            var fs = this._formulare || [];
            if (!fs.length) {
                box.innerHTML = '<p class="kb-hint">'
                    + esc(t('fbadm.empty',
                            'Noch kein Formular. Mit „+ Formular" legst du das erste an.'))
                    + '</p>';
                return;
            }
            box.innerHTML = fs.map(function (f) {
                var sp = (f.spalten || []).length;
                var zn = (f.zeilen || []).length;
                var aus = (f.aktiv === false);
                return '<div class="fb-card' + (aus ? ' is-aus' : '') + '" data-id="'
                    + esc(f.id) + '">'
                    + '<div class="fb-card-row">'
                    + griffMarkup(t('fbadm.drag', 'Reihenfolge ändern (ziehen oder Strg+Pfeil)'))
                    + '<div class="fb-card-main">'
                    + '<span class="fb-card-name">' + esc(f.titel) + '</span>'
                    + '<span class="fb-card-meta">'
                    + esc(t('fbadm.cols', '{n} Spalte(n)').replace('{n}', sp))
                    // Die Zeilenzahl steht nur bei FESTEN Zeilen da: „0 Zeilen"
                    // waere bei einem freien Formular eine Falschaussage – dort
                    // legt der Benutzer sie an, es sind also beliebig viele.
                    + (zn ? ' · ' + esc(t('fbadm.rows_n', '{n} feste Zeile(n)')
                        .replace('{n}', zn)) : '')
                    + (aus ? ' · ' + esc(t('fbadm.inactive', 'abgeschaltet')) : '')
                    + '</span></div>'
                    + '<label class="fb-aktiv" title="'
                    + esc(t('fbadm.aktiv_t', 'Nimmt Abgaben an')) + '">'
                    + '<input type="checkbox" data-akt="aktiv"' + (aus ? '' : ' checked') + '>'
                    + '<span>' + esc(t('fbadm.aktiv', 'aktiv')) + '</span></label>'
                    + '<button type="button" class="fb-act" data-akt="edit" title="'
                    + esc(t('common.edit', 'Bearbeiten')) + '" aria-label="'
                    + esc(t('common.edit', 'Bearbeiten')) + '">&#9998;</button>'
                    + '<button type="button" class="fb-act" data-akt="del" title="'
                    + esc(t('common.delete', 'Löschen')) + '" aria-label="'
                    + esc(t('common.delete', 'Löschen')) + '">'
                    + window.JarvisIcons.trash() + '</button>'
                    + '</div></div>';
            }).join('');

            box.querySelectorAll('.fb-act').forEach(function (b) {
                b.addEventListener('click', function () {
                    var karte = b.closest('.fb-card');
                    var fid = karte ? karte.getAttribute('data-id') : '';
                    if (b.getAttribute('data-akt') === 'del') { Admin.loeschen(fid); }
                    else { Admin.editor(fid); }
                });
            });
            // ⚠ NUR auf `change` hoeren und NIE selbst umschalten: das Kaestchen
            // sitzt in einem <label>, der Browser schaltet es bereits um – ein
            // zusaetzliches `checked = !checked` hebt sich auf und der Klick tut
            // unterm Strich GAR NICHTS (im Projekt beim AD-Picker bezahlt).
            box.querySelectorAll('input[data-akt="aktiv"]').forEach(function (c) {
                c.addEventListener('change', function () {
                    var karte = c.closest('.fb-card');
                    Admin.aktivSetzen(karte ? karte.getAttribute('data-id') : '', c.checked);
                });
            });
            ziehenBinden(box, 'fb-card', function (b) { return Admin.reihenfolgeSenden(b); });

            // Ein offener Editor ueberlebt das Neuzeichnen – sonst schliesst
            // sich der Kasten bei jedem Speichern eines Nachbarn.
            if (this._offen !== null) { this.editor(this._offen, true); }
        },

        reihenfolgeSenden: function (box) {
            var ids = [];
            box.querySelectorAll('.fb-card').forEach(function (k) {
                ids.push(k.getAttribute('data-id'));
            });
            var self = this;
            setStatus('fbadm-status', t('common.saving', 'Speichere…'));
            return fetch('/api/feedback/admin/formulare/reihenfolge', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ ids: ids })
            }).then(json).then(function (d) {
                // Gezeichnet wird aus der SERVER-Antwort, nicht aus dem
                // Zwischenstand im DOM: nicht genannte Eintraege landen hinten,
                // und die Oberflaeche soll nicht behaupten, was der Server
                // womoeglich anders gespeichert hat.
                self._formulare = d.formulare || self._formulare;
                self.zeichnen();
                setStatus('fbadm-status', t('fbadm.sorted', '✓ Reihenfolge gespeichert.'), 'ok');
            }).catch(function (e) {
                setStatus('fbadm-status', e.message, 'error');
                return self.laden();
            });
        },

        aktivSetzen: function (fid, an) {
            var f = (this._formulare || []).find(function (x) { return x.id === fid; });
            if (!f) { return; }
            // Sendet den GANZEN Datensatz, weil der Endpunkt ein Formular
            // vollstaendig setzt – die Spalten kommen unveraendert aus dem
            // bereits geladenen Stand, nicht aus einem Formularfeld.
            this.senden({ id: f.id, titel: f.titel, beschreibung: f.beschreibung || '',
                          spalten: f.spalten || [], aktiv: !!an });
        },

        // ── Editor ────────────────────────────────────────────────────────

        /** Editor unter der Zeile aufklappen. Zweiter Klick schliesst – sonst
         *  tut der Knopf sichtbar nichts. */
        editor: function (fid, wieder) {
            var alt = $('fbadm-form');
            if (alt && !wieder && this._offen === (fid || '')) {
                this.editorSchliessen();
                return;
            }
            if (alt) { alt.remove(); }
            this._offen = fid || '';
            var f = (this._formulare || []).find(function (x) { return x.id === fid; }) || {};
            // Der Arbeitsstand ist eine KOPIE: wer abbricht, soll den
            // gespeicherten Stand unveraendert vorfinden.
            if (!wieder || !this._entwurf) {
                this._entwurf = (f.spalten || []).map(function (s) {
                    return { id: s.id, name: s.name, typ: s.typ };
                });
                if (!this._entwurf.length) {
                    this._entwurf = [{ id: neueKennung(), name: '', typ: 'text' }];
                }
                // Auch die festen Zeilen sind eine KOPIE (`werte` mit kopieren,
                // sonst schreibt der Editor in den geladenen Bestand und
                // „Abbrechen" waere wirkungslos).
                this._zeilen = (f.zeilen || []).map(function (z) {
                    var w = {};
                    Object.keys(z.werte || {}).forEach(function (k) { w[k] = z.werte[k]; });
                    return { id: z.id, werte: w };
                });
            }

            var form = document.createElement('div');
            form.id = 'fbadm-form';
            form.className = 'fb-edit';
            form.innerHTML =
                '<div class="fb-feld"><label for="fbadm-f-titel">'
                + esc(t('fbadm.f_titel', 'Titel (steht in der Auswahl des Benutzers)'))
                + '</label><input type="text" id="fbadm-f-titel" maxlength="100"></div>'
                + '<div class="fb-feld"><label for="fbadm-f-desc">'
                + esc(t('fbadm.f_desc', 'Erklärung (optional, steht über der Tabelle)'))
                + '</label><textarea id="fbadm-f-desc" rows="2" maxlength="1000"></textarea></div>'
                + '<div class="fb-feld"><label>' + esc(t('fbadm.f_cols', 'Spalten')) + '</label>'
                + '<div id="fbadm-spalten"></div>'
                + '<button type="button" class="ja-btn" id="fbadm-sp-neu">'
                + esc(t('fbadm.col_new', '+ Spalte')) + '</button></div>'
                + '<div class="fb-feld" id="fbadm-zeilen-feld"><label>'
                + esc(t('fbadm.f_rows', 'Feste Zeilen')) + '</label>'
                + '<p class="fb-hint" id="fbadm-zeilen-hint"></p>'
                + '<div id="fbadm-zeilen"></div>'
                + '<button type="button" class="ja-btn" id="fbadm-z-neu">'
                + esc(t('fbadm.row_new', '+ Zeile')) + '</button></div>'
                + '<div class="fb-edit-akt">'
                + '<button type="button" class="ja-btn ja-btn-haupt" id="fbadm-f-save">'
                + esc(t('common.save', 'Speichern')) + '</button>'
                + '<button type="button" class="ja-btn" id="fbadm-f-abort">'
                + esc(t('common.cancel', 'Abbrechen')) + '</button>'
                + '<span id="fbadm-f-status" class="fb-edit-status"></span></div>';

            var karte = fid
                ? document.querySelector('.fb-card[data-id="' + fid + '"]')
                : null;
            if (karte) { karte.appendChild(form); }
            else { ($('fbadm-liste') || document.body).appendChild(form); }

            // ⚠ Werte per .value setzen, NICHT ins Markup interpolieren: ein
            // Anfuehrungszeichen im Titel sprengt sonst das Attribut.
            var ti = $('fbadm-f-titel'), de = $('fbadm-f-desc');
            if (ti) { ti.value = f.titel || ''; }
            if (de) { de.value = f.beschreibung || ''; }
            this.spaltenZeichnen();
            this.zeilenZeichnen();

            var zn = $('fbadm-z-neu');
            if (zn) {
                zn.addEventListener('click', function () {
                    if ((Admin._zeilen || []).length >= Admin._maxZeilen) {
                        setStatus('fbadm-f-status',
                            t('fbadm.row_max', 'Mehr als {n} feste Zeilen sind nicht möglich.')
                                .replace('{n}', Admin._maxZeilen), 'error');
                        return;
                    }
                    Admin._zeilen.push({ id: neueKennung(), werte: {} });
                    Admin.zeilenZeichnen();
                    var felder = document.querySelectorAll('#fbadm-zeilen .fb-z-wert');
                    if (felder.length) { felder[felder.length - 1].focus(); }
                });
            }

            var sn = $('fbadm-sp-neu');
            if (sn) {
                sn.addEventListener('click', function () {
                    if (Admin._entwurf.length >= Admin._maxSpalten) {
                        setStatus('fbadm-f-status',
                            t('fbadm.col_max', 'Mehr als {n} Spalten sind nicht möglich.')
                                .replace('{n}', Admin._maxSpalten), 'error');
                        return;
                    }
                    Admin._entwurf.push({ id: neueKennung(), name: '', typ: 'text' });
                    Admin.spaltenZeichnen();
                    var felder = document.querySelectorAll('#fbadm-spalten .fb-sp-name');
                    if (felder.length) { felder[felder.length - 1].focus(); }
                });
            }
            var sv = $('fbadm-f-save');
            if (sv) { sv.addEventListener('click', function () { Admin.speichern(); }); }
            var ab = $('fbadm-f-abort');
            if (ab) { ab.addEventListener('click', function () { Admin.editorSchliessen(); }); }
            if (ti && !wieder) { ti.focus(); }
        },

        editorSchliessen: function () {
            this._offen = null;
            this._entwurf = null;
            this._zeilen = null;
            var f = $('fbadm-form');
            if (f) { f.remove(); }
        },

        spaltenZeichnen: function () {
            var box = $('fbadm-spalten');
            if (!box) { return; }
            var typen = this._typen;
            box.innerHTML = this._entwurf.map(function (sp, i) {
                var opt = typen.map(function (ty) {
                    return '<option value="' + esc(ty) + '"'
                        + (sp.typ === ty ? ' selected' : '') + '>'
                        + esc(t('fbadm.typ_' + ty, ty)) + '</option>';
                }).join('');
                return '<div class="fb-sp" data-id="sp' + i + '" data-idx="' + i + '">'
                    + griffMarkup(t('fbadm.drag_col', 'Spalte verschieben (ziehen oder Strg+Pfeil)'))
                    + '<input type="text" class="fb-sp-name" maxlength="60" aria-label="'
                    + esc(t('fbadm.col_name', 'Überschrift')) + '" placeholder="'
                    + esc(t('fbadm.col_name', 'Überschrift')) + '">'
                    + '<select class="fb-sp-typ" aria-label="'
                    + esc(t('fbadm.col_typ', 'Spaltentyp')) + '">' + opt + '</select>'
                    + '<button type="button" class="fb-act fb-sp-del" title="'
                    + esc(t('fbadm.col_del', 'Spalte entfernen')) + '" aria-label="'
                    + esc(t('fbadm.col_del', 'Spalte entfernen')) + '">'
                    + window.JarvisIcons.trash() + '</button></div>';
            }).join('');

            // Werte setzen statt interpolieren (siehe oben).
            box.querySelectorAll('.fb-sp').forEach(function (zeile, i) {
                var name = zeile.querySelector('.fb-sp-name');
                if (name) {
                    name.value = Admin._entwurf[i].name || '';
                    name.addEventListener('input', function () {
                        Admin._entwurf[i].name = name.value;
                    });
                }
                var typ = zeile.querySelector('.fb-sp-typ');
                if (typ) {
                    typ.addEventListener('change', function () {
                        Admin._entwurf[i].typ = typ.value;
                        // ⚠ DIE ZEILEN MUESSEN NACHZIEHEN: aus einer Textspalte
                        // eine `fest`-Spalte zu machen heisst, dass je Zeile ein
                        // Eingabefeld dazukommt. Ohne diesen Aufruf bliebe der
                        // Block unveraendert stehen, und der Administrator
                        // saehe erst beim Speichern, dass etwas fehlt.
                        Admin.zeilenZeichnen();
                    });
                }
                var del = zeile.querySelector('.fb-sp-del');
                if (del) {
                    del.addEventListener('click', function () {
                        Admin._entwurf.splice(i, 1);
                        // Die letzte Spalte wird nicht entfernt, sondern
                        // GELEERT: ein Formular ohne Spalte laesst sich nicht
                        // speichern, und eine leere Liste sieht nach einem
                        // Fehler aus.
                        if (!Admin._entwurf.length) {
                            Admin._entwurf.push({ id: neueKennung(), name: '', typ: 'text' });
                        }
                        Admin.spaltenZeichnen();
                        // Mit der Spalte faellt ihr Feld in jeder Zeile weg.
                        Admin.zeilenZeichnen();
                    });
                }
            });

            // Ziehen im ARBEITSSTAND: die Reihenfolge wird hier nur im Entwurf
            // umgestellt und erst mit „Speichern" uebernommen – anders als in
            // der Formular-Liste, wo jede Verschiebung sofort gespeichert wird.
            ziehenBinden(box, 'fb-sp', function (b) {
                var neu = [];
                b.querySelectorAll('.fb-sp').forEach(function (z) {
                    var i = parseInt(z.getAttribute('data-idx'), 10);
                    if (!isNaN(i) && Admin._entwurf[i]) { neu.push(Admin._entwurf[i]); }
                });
                if (neu.length === Admin._entwurf.length) { Admin._entwurf = neu; }
                Admin.spaltenZeichnen();
                // Die Felder der Zeilen folgen der Spaltenreihenfolge.
                Admin.zeilenZeichnen();
            });
        },

        /** Die festen Zeilen des Arbeitsstands zeichnen.
         *
         *  Je Zeile ein Eingabefeld PRO `fest`-Spalte: der Text gehoert der
         *  Zeile, nicht der Spalte – genau das ist der Unterschied zwischen
         *  „Ueberschrift" und „Kriterium". Gibt es keine `fest`-Spalte, bleiben
         *  nummerierte Zeilen ohne Text (zulaessig, siehe Modul-Docstring des
         *  Backends).
         */
        zeilenZeichnen: function () {
            var box = $('fbadm-zeilen');
            if (!box) { return; }
            var feste = (this._entwurf || []).filter(function (s) {
                return s.typ === TYP_FEST;
            });
            var hint = $('fbadm-zeilen-hint');
            if (hint) {
                // ⚠ DREI ZUSTAENDE, NICHT ZWEI – und der mittlere ist der
                // wichtigste: eine `fest`-Spalte OHNE Zeilen laesst sich gar
                // nicht speichern. Der Hinweis sagt das VORHER; sonst drueckt
                // der Administrator auf Speichern und bekommt eine Absage,
                // deren Ursache er im Formular oben sucht.
                var lage = !feste.length ? 'frei'
                    : ((this._zeilen || []).length ? 'fest' : 'fehlt');
                hint.textContent =
                    lage === 'fest' ? t('fbadm.rows_fixed',
                        'Der Benutzer bekommt genau diese Zeilen und kann keine eigenen anlegen. Der Text ist für ihn nur lesbar.')
                    : lage === 'fehlt' ? t('fbadm.rows_need',
                        'Die Spalte „fester Text" braucht mindestens eine Zeile – sonst lässt sich das Formular nicht speichern.')
                    : t('fbadm.rows_free',
                        'Ohne feste Zeilen legt der Benutzer seine Zeilen selbst an. Für eine Spalte vom Typ „fester Text" sind feste Zeilen nötig.');
                // Die Lage steht auch als Klasse da – der Waechter misst die
                // EIGENSCHAFT, nicht einen Wortlaut.
                hint.className = 'fb-hint is-' + lage;
            }
            box.innerHTML = (this._zeilen || []).map(function (z, i) {
                var felder = feste.map(function (sp) {
                    return '<input type="text" class="fb-z-wert" maxlength="2000" '
                        + 'data-sp="' + esc(sp.id) + '" data-idx="' + i + '" aria-label="'
                        + esc((sp.name || t('fbadm.col_name', 'Überschrift'))
                            + ' – ' + t('fbadm.row_n', 'Zeile {n}').replace('{n}', i + 1))
                        + '" placeholder="' + esc(sp.name || '') + '">';
                }).join('');
                return '<div class="fb-z" data-id="z' + i + '" data-idx="' + i + '">'
                    + griffMarkup(t('fbadm.drag_row', 'Zeile verschieben (ziehen oder Strg+Pfeil)'))
                    + '<span class="fb-z-nr">' + (i + 1) + '</span>'
                    + (felder || '<span class="fb-z-leer">'
                        + esc(t('fbadm.row_nolabel', 'ohne Beschriftung')) + '</span>')
                    + '<button type="button" class="fb-act fb-z-del" title="'
                    + esc(t('fbadm.row_del', 'Zeile entfernen')) + '" aria-label="'
                    + esc(t('fbadm.row_del', 'Zeile entfernen')) + '">'
                    + window.JarvisIcons.trash() + '</button></div>';
            }).join('');

            // Werte setzen statt interpolieren: ein Anfuehrungszeichen im
            // Kriteriumstext sprengt sonst das Attribut (Register).
            box.querySelectorAll('.fb-z-wert').forEach(function (inp) {
                var i = parseInt(inp.getAttribute('data-idx'), 10);
                var sid = inp.getAttribute('data-sp');
                var z = Admin._zeilen[i];
                if (!z) { return; }
                inp.value = (z.werte || {})[sid] || '';
                inp.addEventListener('input', function () {
                    if (!z.werte) { z.werte = {}; }
                    z.werte[sid] = inp.value;
                });
            });
            box.querySelectorAll('.fb-z-del').forEach(function (del, i) {
                del.addEventListener('click', function () {
                    Admin._zeilen.splice(i, 1);
                    // Hier wird NICHT die letzte Zeile nachgelegt: „keine festen
                    // Zeilen" ist ein gueltiger Zustand (der Benutzer legt sie
                    // dann selbst an). Nur mit einer `fest`-Spalte ist er es
                    // nicht – das faengt die Regel beim Speichern samt Grund ab.
                    Admin.zeilenZeichnen();
                });
            });

            ziehenBinden(box, 'fb-z', function (b) {
                var neu = [];
                b.querySelectorAll('.fb-z').forEach(function (z) {
                    var i = parseInt(z.getAttribute('data-idx'), 10);
                    if (!isNaN(i) && Admin._zeilen[i]) { neu.push(Admin._zeilen[i]); }
                });
                if (neu.length === Admin._zeilen.length) { Admin._zeilen = neu; }
                Admin.zeilenZeichnen();
            });
        },

        speichern: function () {
            var ti = $('fbadm-f-titel'), de = $('fbadm-f-desc');
            if (!ti) { return; }
            var f = (this._formulare || []).find(function (x) {
                return x.id === Admin._offen;
            }) || {};
            this.senden({
                id: this._offen || '',
                titel: ti.value,
                beschreibung: de ? de.value : '',
                spalten: this._entwurf || [],
                // Immer mitschicken – auch leer. Der Server unterscheidet
                // „nicht angegeben" (behalten) von „leer" (loeschen); wer die
                // letzte feste Zeile entfernt, will sie auch los sein.
                zeilen: this._zeilen || [],
                // Beim Anlegen aktiv; beim Bearbeiten bleibt der Zustand, den
                // der Schalter in der Zeile setzt – das Formular hier fasst ihn
                // nicht an.
                aktiv: (this._offen && f.aktiv === false) ? false : true
            }, 'fbadm-f-status');
        },

        senden: function (daten, statusId) {
            var self = this;
            setStatus(statusId || 'fbadm-status', t('common.saving', 'Speichere…'));
            return fetch('/api/feedback/admin/formulare', {
                method: 'POST',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(daten)
            }).then(json).then(function () {
                self.editorSchliessen();
                setStatus(statusId || 'fbadm-status',
                          t('fbadm.saved', '✓ Gespeichert.'), 'ok');
                return self.laden();
            }).catch(function (e) {
                setStatus(statusId || 'fbadm-status', e.message, 'error');
            });
        },

        loeschen: function (fid) {
            var f = (this._formulare || []).find(function (x) { return x.id === fid; }) || {};
            if (!window.confirm(
                    t('fbadm.del_ask',
                      'Formular „{t}" wirklich löschen? Die bereits abgegebenen Antworten bleiben erhalten.')
                        .replace('{t}', f.titel || ''))) { return; }
            var self = this;
            fetch('/api/feedback/admin/formulare/' + encodeURIComponent(fid),
                  { method: 'DELETE', headers: authHeaders() })
                .then(json)
                .then(function () {
                    if (self._offen === fid) { self.editorSchliessen(); }
                    setStatus('fbadm-status', t('fbadm.deleted', '✓ Entfernt.'), 'ok');
                    return self.laden();
                })
                .catch(function (e) { setStatus('fbadm-status', e.message, 'error'); });
        },

        // ── Abgaben auswerten ─────────────────────────────────────────────

        abgabenAuswahl: function () {
            var sel = $('fbadm-abg-sel');
            if (!sel) { return; }
            var fs = this._formulare || [];
            var vorher = this._abgFid;
            sel.innerHTML = '';
            fs.forEach(function (f) {
                var o = document.createElement('option');
                o.value = f.id;
                o.textContent = f.titel;      // textContent: Fremdtext
                sel.appendChild(o);
            });
            if (!fs.length) {
                this._abgFid = '';
                this.abgabenZeichnen([]);
                this.exportKnopf();
                return;
            }
            // Die Wahl ueberlebt ein Neuladen der Liste – sonst springt die
            // Auswertung nach jedem Speichern auf das erste Formular zurueck.
            var gibts = fs.some(function (f) { return f.id === vorher; });
            this._abgFid = gibts ? vorher : fs[0].id;
            sel.value = this._abgFid;
            this.abgabenLaden();
        },

        exportKnopf: function () {
            var b = $('fbadm-export');
            if (!b) { return; }
            var leer = !this._abgFid || !(this._abgaben || []).length;
            // ⚠ GESPERRT MIT BEGRUENDUNG statt verborgen (Projektregel): ein
            // Knopf, der je nach Datenlage auftaucht und verschwindet, ist
            // nicht erklaerbar.
            b.disabled = leer;
            b.title = leer
                ? t('fbadm.exp_leer', 'Es gibt noch keine Abgaben zum Ausgeben.')
                : t('fbadm.exp_t', 'Alle Abgaben dieses Formulars als CSV-Datei (Excel).');
        },

        abgabenLaden: function () {
            var self = this;
            if (!this._abgFid) { this.abgabenZeichnen([]); this.exportKnopf(); return; }
            setStatus('fbadm-abg-status', t('common.loading', 'Lädt…'));
            fetch('/api/feedback/admin/abgaben?fid=' + encodeURIComponent(this._abgFid),
                  { headers: authHeaders() })
                .then(json)
                .then(function (d) {
                    self._abgaben = d.abgaben || [];
                    self.abgabenZeichnen(self._abgaben);
                    self.exportKnopf();
                    setStatus('fbadm-abg-status',
                        t('fbadm.abg_n', '{n} Abgabe(n).').replace('{n}', self._abgaben.length));
                })
                .catch(function (e) {
                    // Ein Ladefehler LEERT die Liste nicht (siehe `laden`).
                    setStatus('fbadm-abg-status', e.message, 'error');
                });
        },

        abgabenZeichnen: function (liste) {
            var box = $('fbadm-abgaben');
            if (!box) { return; }
            box.innerHTML = '';
            if (!liste.length) {
                box.innerHTML = '<p class="kb-hint">'
                    + esc(t('fbadm.abg_none', 'Zu diesem Formular gibt es noch keine Abgaben.'))
                    + '</p>';
                return;
            }
            liste.forEach(function (a) {
                var karte = document.createElement('div');
                karte.className = 'fb-abgabe';

                var kopf = document.createElement('div');
                kopf.className = 'fb-abgabe-kopf';
                var wer = document.createElement('span');
                wer.className = 'fb-abgabe-titel';
                wer.textContent = a.benutzer || '';
                var zeit = document.createElement('span');
                zeit.className = 'fb-abgabe-zeit';
                zeit.textContent = (a.zeit || '').replace('T', ' ');
                var del = document.createElement('button');
                del.type = 'button';
                del.className = 'fb-act';
                del.title = t('fbadm.abg_del', 'Abgabe löschen');
                del.setAttribute('aria-label', del.title);
                del.innerHTML = window.JarvisIcons.trash();
                del.addEventListener('click', function () {
                    Admin.abgabeLoeschen(a.id, a.benutzer || '');
                });
                kopf.appendChild(wer);
                kopf.appendChild(zeit);
                kopf.appendChild(del);
                karte.appendChild(kopf);

                // ⚠ DIE SPALTEN KOMMEN AUS DER ABGABE, nicht aus dem heutigen
                // Formular: sonst stuenden nach einer Aenderung echte Daten
                // unter einer Ueberschrift, die damals gar nicht galt.
                var body = document.createElement('div');
                body.className = 'fb-abgabe-body';
                var tab = document.createElement('table');
                tab.className = 'fb-tab';
                var spalten = a.spalten || [];
                var thead = document.createElement('thead');
                var kz = document.createElement('tr');
                spalten.forEach(function (sp) {
                    var th = document.createElement('th');
                    th.textContent = sp.name;
                    kz.appendChild(th);
                });
                thead.appendChild(kz);
                tab.appendChild(thead);
                var tbody = document.createElement('tbody');
                (a.zeilen || []).forEach(function (z) {
                    var tr = document.createElement('tr');
                    spalten.forEach(function (sp) {
                        var td = document.createElement('td');
                        if (sp.typ === 'sterne') {
                            var n = parseInt(z[sp.id] || 0, 10);
                            // Zahl UND Sterne: in einer Auswertung liest man
                            // Zahlen, die Sterne sind die schnelle Form.
                            var w = document.createElement('span');
                            w.className = 'fb-sterne';
                            w.setAttribute('aria-label', n + '/5');
                            for (var i = 1; i <= 5; i++) {
                                var st = document.createElement('span');
                                st.className = 'fb-stern' + (i <= n ? ' is-an' : '');
                                st.innerHTML = window.JarvisIcons.star(i <= n);
                                w.appendChild(st);
                            }
                            td.appendChild(w);
                            var zahl = document.createElement('span');
                            zahl.className = 'fb-sterne-wert';
                            zahl.textContent = n ? (n + '/5') : '–';
                            td.appendChild(zahl);
                        } else {
                            td.textContent = z[sp.id] == null ? '' : String(z[sp.id]);
                        }
                        tr.appendChild(td);
                    });
                    tbody.appendChild(tr);
                });
                tab.appendChild(tbody);
                body.appendChild(tab);
                karte.appendChild(body);
                box.appendChild(karte);
            });
        },

        abgabeLoeschen: function (aid, wer) {
            if (!window.confirm(
                    t('fbadm.abg_del_ask', 'Abgabe von „{u}" wirklich löschen?')
                        .replace('{u}', wer))) { return; }
            var self = this;
            fetch('/api/feedback/admin/abgaben/' + encodeURIComponent(aid),
                  { method: 'DELETE', headers: authHeaders() })
                .then(json)
                .then(function () {
                    setStatus('fbadm-abg-status', t('fbadm.deleted', '✓ Entfernt.'), 'ok');
                    return self.abgabenLaden();
                })
                .catch(function (e) { setStatus('fbadm-abg-status', e.message, 'error'); });
        },

        /** CSV holen und als Blob speichern.
         *
         *  ⚠ KEIN `<a href>` MIT `?token=`: ein Link kann keinen
         *  Authorization-Header setzen und braeuchte das Token in der Adresse –
         *  das stuende dann im Browser-Verlauf und in jedem Proxy-Protokoll.
         *  Derselbe Weg wie beim Paketbericht in `syspackages.js`.
         */
        exportieren: function () {
            if (!this._abgFid) { return; }
            setStatus('fbadm-abg-status', t('fbadm.exporting', 'Erzeuge Datei…'));
            var name = 'feedback.csv';
            fetch('/api/feedback/admin/export?fid=' + encodeURIComponent(this._abgFid),
                  { headers: authHeaders() })
                .then(function (r) {
                    if (!r.ok) {
                        return r.json().catch(function () { return null; }).then(function (d) {
                            throw new Error(fehlertext(d, 'HTTP ' + r.status));
                        });
                    }
                    // Der Dateiname steht im Kopf (RFC-5987-Form).
                    var cd = r.headers.get('Content-Disposition') || '';
                    var m = /filename\*=utf-8''([^;]+)/i.exec(cd);
                    if (m) { try { name = decodeURIComponent(m[1]); } catch (e) { } }
                    return r.blob();
                })
                .then(function (blob) {
                    var url = URL.createObjectURL(blob);
                    var a = document.createElement('a');
                    a.href = url;
                    a.download = name;
                    document.body.appendChild(a);
                    a.click();
                    document.body.removeChild(a);
                    // Der Speicher wird erst freigegeben, wenn der Browser die
                    // Adresse nicht mehr braucht – sofort widerrufen bricht den
                    // Download in manchen Browsern ab.
                    setTimeout(function () { URL.revokeObjectURL(url); }, 10000);
                    setStatus('fbadm-abg-status',
                        t('fbadm.exported', '✓ Datei erzeugt: {n}').replace('{n}', name), 'ok');
                })
                .catch(function (e) { setStatus('fbadm-abg-status', e.message, 'error'); });
        }
    };

    window.FeedbackAdmin = Admin;
})();
