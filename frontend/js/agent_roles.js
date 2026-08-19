/* Spezialisierte Rollen-Agenten – Verwaltung (Einstellungen → Orchestrator)
   Der Reiter erscheint nur, wenn der Skill "Agent Orchestrator" aktiv ist.
   Backend: backend/agent_roles.py, Endpunkte /api/agent_roles (alle Admin).
   i18n via window.t(), Farben ausschliesslich ueber CSS-Variablen. */
(function () {
    'use strict';

    function token() { return localStorage.getItem('jarvis_token') || ''; }
    function authHeaders(extra) { return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {}); }
    function $(id) { return document.getElementById(id); }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function T(key, def) { return (window.t && window.t(key) !== key ? window.t(key) : null) || def; }

    var Mgr = {
        _bound: false,
        _data: null,       // letzte Antwort von GET /api/agent_roles
        _editId: null,     // null = neue Rolle, sonst Kennung der bearbeiteten
        _home: null,       // Heimatplatz des Formulars (siehe _platziere)

        onShow: function () { this._bind(); this.load(); },

        // ── Das Formular wandert, es gibt aber nur EINEN Container ──────────
        // Es wird direkt unter die bearbeitete Zeile gehaengt, damit man beim
        // Bearbeiten nicht ans Listenende springen muss. Muster und Fallstricke
        // wie bei der Extraktions-Vorschau in /wissen (2026-07-28):
        //  - Der Heimatplatz wird NUR beim ersten Verschieben gemerkt; ein
        //    spaeteres Auslesen wuerde die verschobene Position als "Heimat"
        //    festschreiben.
        //  - Vor dem Neuaufbau der Liste MUSS das Formular heimgeholt werden –
        //    sonst raeumt `innerHTML = ''` es mit ab und `$('role-edit')` ist
        //    danach null.
        // ── Das Formular wandert IN die Karte der bearbeiteten Rolle ────────
        // `karte` ist ein `.role-card` (der Container mit dem Rahmen); das
        // Formular wird sein KIND. Damit ist es zwangslaeufig EINE Box – genau
        // wie `.kb-section` Kopfzeile und Koerper umschliesst. Es als
        // Geschwister danebenzusetzen und die Kanten zu kaschieren hat zweimal
        // nicht funktioniert (Abstand blieb sichtbar).
        _platziere: function (karte) {
            var f = $('role-edit');
            if (!f) return;
            if (!this._home) {
                this._home = { parent: f.parentNode, next: f.nextSibling };
            }
            var box = $('roles-list');
            if (box) {
                Array.prototype.forEach.call(box.querySelectorAll('.role-card.is-editing'),
                    function (k) { k.classList.remove('is-editing'); });
            }
            if (karte && karte.classList && karte.classList.contains('role-card')) {
                karte.appendChild(f);            // KIND der Karte, nicht Geschwister
                karte.classList.add('is-editing');
            } else if (this._home.parent) {
                this._home.parent.insertBefore(f, this._home.next);
            }
        },

        _bind: function () {
            if (this._bound) return;
            this._bound = true;
            var self = this;
            var neu = $('btn-role-new');
            if (neu) neu.onclick = function () { self.openForm(null); };
            ['btn-role-cancel', 'btn-role-cancel2'].forEach(function (id) {
                var b = $(id);
                if (b) b.onclick = function () { self.closeForm(); };
            });
            var sv = $('btn-role-save');
            if (sv) sv.onclick = function () { self.save(); };
        },

        // ── Laden / Liste ───────────────────────────────────────────────
        load: function () {
            var self = this;
            var box = $('roles-list');
            if (!box) return;
            // Formular heimholen, BEVOR die Liste neu gebaut wird (sonst wird es
            // mitgeloescht – siehe _platziere).
            this._platziere(null);
            fetch('/api/agent_roles', { headers: authHeaders() })
                .then(function (r) {
                    if (r.status === 403) throw new Error(T('roles.err_admin', 'Nur für Administratoren.'));
                    if (!r.ok) throw new Error('HTTP ' + r.status);
                    return r.json();
                })
                .then(function (d) { self._data = d; self.render(); })
                .catch(function (e) {
                    box.innerHTML = '<div style="font-size:.8rem;color:var(--danger);">'
                        + esc(e.message) + '</div>';
                });
        },

        render: function () {
            var d = this._data || {}, box = $('roles-list');
            if (!box) return;
            var rollen = d.roles || [];
            var cnt = $('roles-count');
            if (cnt) {
                cnt.textContent = rollen.length
                    ? rollen.length + ' / ' + (d.max_roles || '?')
                    : '';
            }
            // Rollen sind ohne den Skill pflegbar, aber wirkungslos – das muss
            // dastehen, sonst sucht der Administrator den Fehler bei den Rollen.
            var warn = $('roles-skill-warn');
            if (warn) {
                var aus = (d.skill_active === false);
                warn.style.display = aus ? '' : 'none';
                if (aus) {
                    warn.textContent = T('roles.skill_off',
                        '⚠ Der Skill „Agent Orchestrator" ist nicht aktiv – der Hauptagent kann derzeit keine Rolle beauftragen. Unter Einstellungen → Skills einschalten.');
                }
            }
            if (!rollen.length) {
                box.innerHTML = '<div style="opacity:.65;font-size:.8rem;">'
                    + esc(T('roles.empty', 'Keine Rolle eingerichtet. Ohne Rolle verhält sich der Agent wie bisher.'))
                    + '</div>';
                return;
            }
            var self = this;
            box.innerHTML = '';
            rollen.forEach(function (r) {
                // Die KARTE ist die Box (Rahmen/Hintergrund) – die Zeile ist nur
                // ihre Kopfzeile, das Formular kommt als zweites Kind hinein.
                var karte = document.createElement('div');
                karte.className = 'role-card' + (r.enabled ? '' : ' is-off');
                karte.dataset.roleId = r.id;
                var zeile = document.createElement('div');
                zeile.className = 'role-row';
                // KEINE Inline-Styles: die Regeln stehen in style.css (.role-row).
                // Inline wuerde gegen `.role-row.is-editing { margin-bottom: 0 }`
                // gewinnen, und Zeile + Formular waeren wieder zwei Boxen.
                // Abgeschaltete Rollen sind ueber `.is-off` abgeschwaecht (Deckkraft,
                // keine eigene Farbe – die waere in Hell/Dunkel nie beides richtig).
                var links = document.createElement('div');
                links.className = 'role-row-main';
                var kopf = document.createElement('div');
                kopf.className = 'role-row-head';
                // textContent: Name und Beschreibung sind Freitext des Administrators
                var nm = document.createElement('span');
                nm.textContent = r.name || r.id;
                kopf.appendChild(nm);
                var kenn = document.createElement('code');
                kenn.className = 'role-row-id';
                kenn.textContent = r.id;
                kopf.appendChild(kenn);
                if (!r.enabled) {
                    var aus = document.createElement('span');
                    aus.className = 'role-row-badge';
                    aus.textContent = T('roles.off', 'abgeschaltet');
                    kopf.appendChild(aus);
                }
                links.appendChild(kopf);

                var desc = document.createElement('div');
                desc.className = 'role-row-desc';
                desc.textContent = r.description || '';
                links.appendChild(desc);

                var meta = document.createElement('div');
                meta.className = 'role-row-meta';
                var teile = [];
                teile.push((r.tools || []).length + ' ' + T('roles.tools_n', 'Werkzeuge'));
                var pn = this._profileName(r.profile_id);
                teile.push(pn ? T('roles.profile_is', 'Profil') + ': ' + pn
                    : T('roles.profile_inherit', 'Profil des Aufrufers'));
                if (r.reasoning_effort) teile.push(T('roles.effort_is', 'Denktiefe') + ': ' + r.reasoning_effort);
                if (r.max_steps) teile.push(r.max_steps + ' ' + T('roles.steps_n', 'Schritte'));
                meta.textContent = teile.join(' · ');
                links.appendChild(meta);
                zeile.appendChild(links);

                var knopfe = document.createElement('div');
                knopfe.className = 'role-row-btns';
                // Aktiv/Inaktiv DIREKT in der Zeile – das ist der haeufigste
                // Eingriff (eine Rolle kurz stilllegen) und war vorher nur im
                // Formular erreichbar.
                var bT = document.createElement('button');
                bT.className = 'kb-hdr-btn role-toggle';
                bT.textContent = r.enabled ? '⏸' : '▶';
                bT.title = r.enabled ? T('roles.disable', 'Rolle abschalten')
                    : T('roles.enable', 'Rolle einschalten');
                bT.setAttribute('aria-label', bT.title);
                bT.onclick = function () { self.toggle(r); };
                knopfe.appendChild(bT);
                var bE = document.createElement('button');
                bE.className = 'kb-hdr-btn role-edit-btn';
                bE.textContent = '✎';
                bE.title = T('roles.edit', 'Bearbeiten');
                bE.setAttribute('aria-label', bE.title);
                // Die Zeile ist der Anker: das Formular klappt DIREKT darunter auf.
                bE.onclick = function () { self.openForm(r.id, karte); };
                knopfe.appendChild(bE);
                var bD = document.createElement('button');
                bD.className = 'kb-hdr-btn is-danger';
                JarvisIcons.setTrash(bD);
                bD.title = T('roles.delete', 'Löschen');
                bD.setAttribute('aria-label', bD.title);
                bD.onclick = function () { self.remove(r); };
                knopfe.appendChild(bD);
                zeile.appendChild(knopfe);
                karte.appendChild(zeile);
                box.appendChild(karte);
            }, this);

            // Ein offenes Formular wieder unter seine Zeile setzen (die Liste ist
            // gerade neu gebaut worden, die alte Ankerzeile existiert nicht mehr).
            if (this._editId) {
                var anker = box.querySelector('[data-role-id="' + this._editId + '"]');
                if (anker) this._platziere(anker);
            }
        },

        // ── Aktiv/Inaktiv umschalten, ohne das Formular zu oeffnen ──────────
        toggle: function (r) {
            var self = this;
            fetch('/api/agent_roles/' + encodeURIComponent(r.id), {
                method: 'PUT',
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                // NUR dieses Feld senden: der Endpunkt merged ueber
                // UPDATABLE_FIELDS, ein vollstaendiger Rumpf wuerde den
                // Formularstand ueber die gespeicherten Werte schreiben.
                body: JSON.stringify({ enabled: !r.enabled })
            }).then(function () { self.load(); });
        },

        _profileName: function (pid) {
            if (!pid) return '';
            var p = ((this._data || {}).profiles || []).filter(function (x) { return x.id === pid; })[0];
            // Verwaistes Profil sichtbar machen: zur Laufzeit faellt die Rolle auf
            // das Profil des Aufrufers zurueck – das soll man hier schon sehen.
            return p ? p.name : T('roles.profile_gone', '⚠ gelöschtes Profil');
        },

        // ── Formular ────────────────────────────────────────────────────
        openForm: function (rid, anchor) {
            var d = this._data || {};
            this._editId = rid || null;
            // Bearbeiten: direkt unter der Zeile. Anlegen: am Heimatplatz unter
            // der Liste (dort gibt es keine Zeile, zu der es gehoeren koennte).
            this._platziere(anchor || null);
            var r = rid ? (d.roles || []).filter(function (x) { return x.id === rid; })[0] : null;

            var titel = $('role-edit-title');
            if (titel) {
                titel.textContent = r ? (T('roles.edit', 'Bearbeiten') + ': ' + (r.name || r.id))
                    : T('roles.new', '+ Rolle anlegen');
            }
            $('role-f-id').value = r ? r.id : '';
            $('role-f-id').disabled = !!r;   // Kennung ist unveraenderlich
            $('role-f-name').value = r ? (r.name || '') : '';
            $('role-f-desc').value = r ? (r.description || '') : '';
            $('role-f-prompt').value = r ? (r.prompt || '') : '';
            $('role-f-steps').value = r ? (r.max_steps || 0) : 0;
            $('role-f-enabled').checked = r ? !!r.enabled : true;

            // Profile
            var sel = $('role-f-profile');
            sel.innerHTML = '';
            var o0 = document.createElement('option');
            o0.value = '';
            o0.textContent = T('roles.profile_inherit', 'Profil des Aufrufers');
            sel.appendChild(o0);
            (d.profiles || []).forEach(function (p) {
                var o = document.createElement('option');
                o.value = p.id;
                o.textContent = p.name || p.id;
                sel.appendChild(o);
            });
            sel.value = r ? (r.profile_id || '') : '';

            // Denktiefe
            var se = $('role-f-effort');
            se.innerHTML = '';
            (d.efforts || ['', 'off', 'low', 'medium', 'high', 'max']).forEach(function (e) {
                var o = document.createElement('option');
                o.value = e;
                o.textContent = e || T('roles.effort_default', 'Vorgabe (Profil/global)');
                se.appendChild(o);
            });
            se.value = r ? (r.reasoning_effort || '') : '';

            // Hinweis zur Lizenz: mit nur einem erlaubten Profil bringt ein
            // rollen-eigenes Modell nichts – lieber vorher sagen als nach dem 403.
            var note = $('role-profile-note');
            if (note) {
                var lim = d.profile_limit;
                if (lim && (d.profiles || []).length <= lim) {
                    note.textContent = T('roles.profile_limit',
                        'Diese Lizenz erlaubt nur ein LLM-Profil – ein eigenes Modell je Rolle setzt eine ENTERPRISE-Lizenz voraus.');
                    note.style.display = '';
                } else {
                    note.style.display = 'none';
                }
            }

            // Werkzeuge
            var tb = $('role-f-tools');
            tb.innerHTML = '';
            var gewaehlt = {};
            (r ? (r.tools || []) : []).forEach(function (t) { gewaehlt[t] = 1; });
            (d.tools || []).forEach(function (t) {
                var lab = document.createElement('label');
                // Kein Inline-Style: die Regeln stehen in style.css (.role-tools label).
                var cb = document.createElement('input');
                cb.type = 'checkbox';
                cb.value = t.name;
                cb.checked = !!gewaehlt[t.name];
                cb.className = 'role-tool-cb';
                // KEIN eigenes Umschalten im Label: der Browser macht das selbst,
                // ein zusaetzliches Toggle hebt sich auf (Fehler vom 2026-07-29
                // im AD-Picker).
                lab.appendChild(cb);
                var sp = document.createElement('span');
                sp.textContent = t.name;
                sp.title = t.description || '';
                lab.appendChild(sp);
                tb.appendChild(lab);
            });

            $('role-save-status').textContent = '';
            $('role-edit').style.display = '';
        },

        closeForm: function () {
            var f = $('role-edit');
            if (f) f.style.display = 'none';
            this._editId = null;
            // Heimholen, damit es beim naechsten Anlegen nicht mitten in der
            // Liste auftaucht.
            this._platziere(null);
        },

        _gewaehlteTools: function () {
            var out = [];
            document.querySelectorAll('#role-f-tools .role-tool-cb').forEach(function (cb) {
                if (cb.checked) out.push(cb.value);
            });
            return out;
        },

        save: function () {
            var self = this;
            var st = $('role-save-status');
            var body = {
                name: $('role-f-name').value.trim(),
                description: $('role-f-desc').value.trim(),
                prompt: $('role-f-prompt').value,
                tools: this._gewaehlteTools(),
                profile_id: $('role-f-profile').value,
                reasoning_effort: $('role-f-effort').value,
                max_steps: parseInt($('role-f-steps').value || '0', 10) || 0,
                enabled: !!$('role-f-enabled').checked
            };
            var url = '/api/agent_roles', meth = 'POST';
            if (this._editId) {
                url += '/' + encodeURIComponent(this._editId);
                meth = 'PUT';
            } else {
                body.id = $('role-f-id').value.trim();
            }
            st.textContent = '…';
            st.style.color = 'var(--text-secondary)';
            fetch(url, {
                method: meth,
                headers: authHeaders({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(body)
            })
                .then(function (r) { return r.json().then(function (j) { return { ok: r.ok, j: j }; }); })
                .then(function (res) {
                    if (!res.ok || !res.j.success) {
                        // Der Grund kommt im Klartext vom Backend – er ist die
                        // eigentliche Hilfe (welches Feld fehlt).
                        st.textContent = '✗ ' + (res.j.error || 'Fehler');
                        st.style.color = 'var(--danger)';
                        return;
                    }
                    st.textContent = '✓ ' + T('roles.saved', 'gespeichert');
                    st.style.color = 'var(--success)';
                    self.closeForm();
                    self.load();
                })
                .catch(function (e) {
                    st.textContent = '✗ ' + e.message;
                    st.style.color = 'var(--danger)';
                });
        },

        remove: function (r) {
            var self = this;
            var frage = T('roles.confirm_del', 'Rolle wirklich löschen?') + '\n\n' + (r.name || r.id);
            if (!window.confirm(frage)) return;
            fetch('/api/agent_roles/' + encodeURIComponent(r.id), {
                method: 'DELETE', headers: authHeaders()
            }).then(function () { self.load(); });
        }
    };

    window.AgentRoles = Mgr;
})();
