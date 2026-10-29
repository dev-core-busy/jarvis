/* Eigenständige Wissens-Seite /wissen – Domänennutzer pflegen Wissen NUR aus
   ihren Wissensgruppen (Editor-Rechte). Upload, Ordnerwahl, Informationsextraktor.
   Berechtigungen werden serverseitig erzwungen (/api/wissen/*). i18n via window.t. */
(function () {
    'use strict';

    var $ = function (id) { return document.getElementById(id); };
    var token = window.JarvisSitzung.token();
    /* Abruf-Schluessel statt Sitzungstoken in ?token= (frontend/js/dlkey.js).
       Rueckfall auf das Sitzungstoken nur, solange das Modul fehlt oder der
       Schluessel noch unterwegs ist – sonst waere ein Bild/Download tot. */
    function _dlk() {
        return (window.JarvisDL && window.JarvisDL.schluessel())
            || window.JarvisSitzung.token();
    }

    var SCOPE = { groups: [], folders: [], is_editor: false, user: '' };

    // i18n-Helfer: liefert Übersetzung oder (fallback) den Key; {slots} via .replace().
    function t(k, vars) {
        var s = (window.t ? window.t(k) : k) || k;
        if (vars) { for (var v in vars) s = s.split('{' + v + '}').join(vars[v]); }
        return s;
    }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function authH(extra) { return Object.assign({ 'Authorization': 'Bearer ' + token }, extra || {}); }

    // ── Screens ─────────────────────────────────────────────────────────
    function showLogin() {
        $('wi-app').classList.add('hidden');
        $('wi-logout').classList.add('hidden');
        var d = $('wi-status-dot'); if (d) d.classList.add('hidden');
        var c = $('cpu-bar'); if (c) c.classList.add('hidden');
        $('wi-login').classList.remove('hidden');
        var u = $('wi-user'); if (u) u.focus();
    }
    function showApp() {
        $('wi-login').classList.add('hidden');
        $('wi-app').classList.remove('hidden');
        $('wi-logout').classList.remove('hidden');
        var d = $('wi-status-dot'); if (d) d.classList.remove('hidden');
        var c = $('cpu-bar'); if (c) c.classList.remove('hidden');
        // Das Einstellungs-Zahnrad blendet `settings_btn.js` zentral aus
        // `/api/me` ein – nicht hier. Es hing an `is_admin` aus
        // `/api/wissen/scope`; scheitert dieser Abruf (403, Zeitlimit), lief die
        // Einblendung nie, und der Administrator hatte keinen Weg in die
        // Einstellungen.
        mountProfile();
        startLlmStatus();
    }

    // KI-Profil-Pulldown neben "Fragen & Antworten generieren"
    // (per-User-Auswahl, wirkt auf die KI-Analyse)
    var _prof = null;
    function mountProfile() {
        var slot = $('wi-prof-slot');
        if (!slot || !window.ProfileSwitcher) return;
        if (_prof) { _prof.refresh(); return; }
        _prof = window.ProfileSwitcher.mount({
            anchor: slot,
            headers: function () { return authH(); },
            onChange: function () { checkLlmStatus(); }
        });
    }

    // ── LLM-Status-Punkt (die CPU-Auslastung liegt seit 2026-08-22 in
    //    frontend/js/cpubar.js – hier stand eine von vier Kopien) ────────
    var _llmStatusTimer = null;
    function checkLlmStatus() {
        var dot = $('wi-status-dot');
        if (!dot) return;
        fetch('/api/llm/active-status', { headers: authH() })
            .then(function (r) { if (!r.ok) throw new Error('http'); return r.json(); })
            .then(function (d) {
                var reachable = (d.status === 'ok' || d.status === 'degraded');
                // classList statt className: 'hidden' (Login-Screen) muss erhalten bleiben
                dot.classList.toggle('connected', reachable);
                dot.classList.toggle('disconnected', !reachable);
                var name = d.profile_name ? ' – ' + d.profile_name : '';
                dot.title = (d.status === 'ok' ? t('sup.llm_ok')
                    : d.status === 'degraded' ? t('sup.llm_degraded')
                    : t('sup.llm_down')) + name;
            })
            .catch(function () {
                dot.classList.remove('connected');
                dot.classList.add('disconnected');
                dot.title = t('sup.llm_down');
            });
    }
    function startLlmStatus() {
        checkLlmStatus();
        if (!_llmStatusTimer) _llmStatusTimer = setInterval(checkLlmStatus, 30000);
    }
    // ── Login ───────────────────────────────────────────────────────────
    function doLogin() {
        var btn = $('wi-login-btn'), err = $('wi-login-err');
        err.textContent = '';
        var payload = { username: $('wi-user').value.trim(), password: $('wi-pass').value };
        var totp = $('wi-totp').value.trim();
        if (!$('wi-totp-row').classList.contains('hidden') && totp) payload.totp_code = totp;
        if (!payload.username || !payload.password) { err.textContent = t('wissen.err_user_pass'); return; }
        btn.disabled = true; btn.textContent = t('wissen.logging_in');
        fetch('/api/login', { method: 'POST', headers: window.JarvisSitzung.anmeldeKopf({ 'Content-Type': 'application/json' }), body: JSON.stringify(payload) })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.success && d.token) {
                    token = d.token;
                    localStorage.setItem('jarvis_token', token);
                    localStorage.setItem('jarvis_user', d.username || payload.username);
                    $('wi-totp-row').classList.add('hidden');
                    // Lief in diesem Tab schon eine Sitzung (abgelaufen -> Maske),
                    // stehen ihre Inhalte noch im Speicher: neu laden, das Token
                    // liegt bereits im localStorage.
                    if (_hattSitzung) { frischeSeite(); return; }
                    loadScope();
                } else if (d.requires_totp) {
                    $('wi-totp-row').classList.remove('hidden'); $('wi-totp').focus();
                    err.textContent = t('wissen.totp_required');
                } else {
                    err.textContent = d.error || t('wissen.login_failed');
                }
            })
            .catch(function () { err.textContent = t('wissen.conn_error'); })
            .then(function () { btn.disabled = false; btn.textContent = t('wissen.login_title'); });
    }

    /* Nach einer Sitzung im selben Tab NEU LADEN statt nur die Maske zu
       zeigen (Code-Review 2026-10-07): die Module halten ihren Zustand im
       Speicher – Destillat-Ergebnis, Gruppen-Kaestchen (einmal gezeichnet),
       Confluence-Baum, Listen. Meldete sich danach jemand anderes an, sah er
       das alles vom Vorgaenger, und das Destillat bot dessen Gruppen als Ziel
       an. Ein frischer Seitenaufbau ist der einzige Zustand, der sicher leer
       ist; einzeln zuruecksetzen vergisst beim naechsten Modul etwas. */
    var _hattSitzung = false;
    function frischeSeite() {
        try { window.location.reload(); } catch (e) { showLogin(); }
    }

    function logout() {
        localStorage.removeItem('jarvis_token');
        token = '';
        if (_hattSitzung) { frischeSeite(); return; }
        showLogin();
    }

    // ── Bereich laden ───────────────────────────────────────────────────
    function loadScope() {
        if (!token) { showLogin(); return; }
        fetch('/api/wissen/scope', { headers: authH() })
            .then(function (r) {
                if (r.status === 401 || r.status === 403) { showLogin(); return null; }
                return r.json();
            })
            .then(function (d) {
                if (!d || !d.ok) return;
                SCOPE = d;
                _hattSitzung = true;
                showApp();
                renderScope();
                // Mein Gedaechtnis: fuer JEDEN Benutzer (js/gedaechtnis.js)
                if (window.JarvisGedaechtnis) window.JarvisGedaechtnis.laden($('wi-gedaechtnis-liste'));
                // Ohne Wissensbereich gibt es nichts zu pflegen: keine Abrufe fuer
                // Dateien, Entwuerfe, Confluence und Destillat (Abschnitte sind aus).
                if (nurEigenes()) return;
                loadFiles();
                loadPending();
                loadCfSpaces();
                cfbLaden();
                // Wissens-Destillat: eigenes Modul, bekommt Scope und Token von
                // HIER. Bewusst kein eigener /api/wissen/scope-Abruf dort –
                // zwei Abrufe liefen beim naechsten Feinschliff auseinander.
                if (window.WissenDestillat) {
                    window.WissenDestillat.init({ scope: SCOPE, token: token });
                }
            })
            .catch(function () { showLogin(); });
    }

    // Kein Wissensbereich und kein globaler Wissens-Editor: die Seite zeigt nur
    // "Mein Gedaechtnis". Seit 2026-10-15 erreicht JEDER Benutzer die
    // Seite ueber die Portal-Kachel – vorher nur, wer einen Bereich hatte.
    // Ein globaler Wissens-Editor ohne Gruppen wird NICHT reduziert: er sieht
    // die Gruppenverwaltung und legt dort die erste Wissensgruppe an.
    function nurEigenes() {
        return !SCOPE.groups.length && !SCOPE.is_editor;
    }

    var PFLEGE_ABSCHNITTE = ['wi-sec-upload', 'wi-sec-destillat', 'wi-sec-cfbind', 'wi-sec-files'];

    function renderScope() {
        var banner = $('wi-scope-banner');
        if (nurEigenes()) {
            banner.className = 'wi-banner';
            banner.innerHTML = '<div>' + t('wissen.scope_as') + ' <b>' + esc(SCOPE.user) + '</b></div>'
                + '<div class="wi-banner-sub">' + esc(t('wissen.nur_eigenes')) + '</div>';
            PFLEGE_ABSCHNITTE.forEach(function (id) { var x = $(id); if (x) x.style.display = 'none'; });
            return;
        }
        // Massenzuordnung + Gruppenverwaltung VOR der Weiche "keine Gruppen":
        // bis 2026-10-15 stand sie dahinter, und ein globaler Editor ohne jede
        // Wissensgruppe sah die Verwaltung nicht – die erste Gruppe liess sich
        // in /wissen gar nicht anlegen.
        editorAbschnitte();
        if (!SCOPE.groups.length) {
            banner.className = 'wi-banner warn';
            // Editor: er kann selbst Abhilfe schaffen; sonst der Admin-Hinweis
            banner.innerHTML = SCOPE.is_editor ? t('wissen.no_groups_editor') : t('wissen.no_area');
            $('wi-sec-upload').classList.add('hidden');
            return;
        }
        $('wi-sec-upload').classList.remove('hidden');
        banner.className = 'wi-banner';
        // Nur "Angemeldet als <user>" – die Wissensgruppen-Chips entfallen hier,
        // da die Gruppen weiter unten in der Auswahl ohnehin gezeigt werden.
        banner.innerHTML = '<div>' + t('wissen.scope_as') + ' <b>' + esc(SCOPE.user) + '</b>'
            + (SCOPE.is_editor ? ' ' + t('wissen.global_editor') : '') + '</div>';

        $('wi-upload-groups').innerHTML = groupBoxes('up');
        updateFolderOptions();
        updateDropState();   // Ablage-Sperre initial setzen (keine Gruppe = gesperrt + Hinweis)
        updateActionState(); // "Extrahieren" nur bei gewaehlter Gruppe aktiv
    }

    // Massenzuordnung + Wissensgruppen-Verwaltung nur fuer globale Wissens-Editoren
    function editorAbschnitte() {
        var mSec = $('wi-sec-matrix');
        if (mSec) mSec.style.display = SCOPE.is_editor ? '' : 'none';
        var gSec = $('wi-sec-groups');
        if (gSec) {
            gSec.style.display = SCOPE.is_editor ? '' : 'none';
            // Gruppen-Verwaltung (aus Einstellungen verschoben) via knowledge.js rendern
            if (SCOPE.is_editor && window.knowledgeManager && window.knowledgeManager.initGroups) {
                window.knowledgeManager.initGroups();
            }
        }
    }

    // Speicherordner-Auswahl auf die gewaehlten Gruppen eingrenzen: angeboten
    // wird die Union der Speicherordner der angehakten Gruppen (Server liefert
    // pro Gruppe g.folders).
    // Gruppen ohne Zuordnung haben KEIN Speicherziel -> Ablage bleibt gesperrt.
    // Globale Editoren sehen immer alle Ordner ihres Scopes.
    function updateFolderOptions() {
        var sel = $('wi-folder');
        if (!sel) return;
        var offer = SCOPE.folders || [];
        var checked = checkedGroups('up');
        if (!SCOPE.is_editor && checked.length) {
            var want = {};
            checked.forEach(function (gid) {
                var g = null;
                SCOPE.groups.forEach(function (x) { if (x.id === gid) g = x; });
                ((g && g.folders) || []).forEach(function (p) { want[p] = true; });
            });
            // Unterordner erben die Berechtigung ihrer Wurzel -> ueber f.root filtern.
            offer = offer.filter(function (f) { return want[f.root || f.path]; });
        }
        var cur = sel.value;
        sel.innerHTML = offer.map(function (f) {
            // Unterordner eingerueckt darstellen (em-space je Ebene + ↳).
            var d = f.depth || 0;
            var label = d
                ? (new Array(d + 1).join(' ') + '↳ ' + f.name)
                : (f.name + ' (' + (f.display || anzeigePfad(f.path)) + ')');
            return '<option value="' + esc(f.path) + '">' + esc(label) + '</option>';
        }).join('');
        // Bisherige Auswahl erhalten, wenn sie weiterhin angeboten wird
        for (var i = 0; i < offer.length; i++) {
            if (offer[i].path === cur) { sel.value = cur; break; }
        }
        updateFolderBtnState();
    }

    // ── Unterordner anlegen/umbenennen (im eigenen Berechtigungsbereich) ──
    // Der Server prueft die Berechtigung erneut gegen die Wissensgruppen des
    // Nutzers – die Buttons hier steuern nur die Bedienbarkeit.

    // Metadaten des aktuell gewaehlten Ordner-Eintrags aus dem Scope.
    function currentFolderEntry() {
        var sel = $('wi-folder');
        if (!sel || !sel.value) return null;
        var found = null;
        (SCOPE.folders || []).forEach(function (f) { if (f.path === sel.value) found = f; });
        return found;
    }

    function updateFolderBtnState() {
        var entry = currentFolderEntry();
        var bNew = $('wi-folder-new'), bRen = $('wi-folder-rename'), bMov = $('wi-folder-move');
        if (bNew) bNew.disabled = !entry;
        // Wurzelordner (depth 0) bleiben der Admin-Flaeche vorbehalten
        if (bRen) bRen.disabled = !entry || !(entry.depth > 0);
        if (bMov) bMov.disabled = !entry || !(entry.depth > 0);
    }

    // Gruppen in der Verwaltung angelegt/geloescht (knowledge.js meldet es).
    // Neu gezeichnet wird NUR beim Wechsel "keine Gruppe" <-> "Gruppen da":
    // renderScope() baut die Gruppen-Kaestchen des Extraktors neu und wuerde
    // bei jeder Umbenennung die Auswahl des Benutzers verwerfen.
    document.addEventListener('jarvis-kbgroups-geaendert', function () {
        if (!_hattSitzung) return;
        var warLeer = !SCOPE.groups.length;
        fetch('/api/wissen/scope', { headers: authH() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d || !d.ok) return;
                var istLeer = !(d.groups || []).length;
                if (warLeer === istLeer) return;
                SCOPE = d;
                renderScope();
            })
            .catch(function () {});
    });

    // Ordnerliste neu holen und danach denselben (oder einen neuen) Pfad waehlen.
    function reloadFolders(selectPath) {
        return fetch('/api/wissen/scope', { headers: authH() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || !d.ok) return;
                SCOPE = d;
                updateFolderOptions();
                var sel = $('wi-folder');
                if (sel && selectPath) {
                    sel.value = selectPath;
                    updateFolderBtnState();
                }
            });
    }

    function folderStatus(msgText, isError) {
        var st = $('wi-upload-status');
        if (!st) return;
        st.style.color = isError ? 'var(--danger)' : 'var(--success)';
        st.textContent = (isError ? '✗ ' : '') + msgText;
    }

    function createSubfolder() {
        var entry = currentFolderEntry();
        if (!entry) return;
        var name = (window.prompt(t('wissen.subfolder_prompt'), '') || '').trim();
        if (!name) return;
        fetch('/api/wissen/subfolders', {
            method: 'POST', headers: authH({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ parent: entry.path, name: name })
        })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d || {} }; }); })
            .then(function (res) {
                if (!res.ok || res.d.error) { folderStatus(res.d.error || t('common.error'), true); return; }
                folderStatus(t('wissen.subfolder_created'));
                return reloadFolders(res.d.path);
            })
            .catch(function () { folderStatus(t('wissen.conn_error'), true); });
    }

    function renameSubfolder() {
        var entry = currentFolderEntry();
        if (!entry || !(entry.depth > 0)) return;
        var name = (window.prompt(t('wissen.subfolder_rename_prompt'), entry.name) || '').trim();
        if (!name || name === entry.name) return;
        fetch('/api/wissen/subfolders', {
            method: 'PUT', headers: authH({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ path: entry.path, new_name: name })
        })
            .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d || {} }; }); })
            .then(function (res) {
                if (!res.ok || res.d.error) { folderStatus(res.d.error || t('common.error'), true); return; }
                folderStatus(t('wissen.subfolder_renamed'));
                return reloadFolders(res.d.path).then(function () { loadFiles(); });
            })
            .catch(function () { folderStatus(t('wissen.conn_error'), true); });
    }

    // "Alle" / "Keine" vor einer Reihe Gruppen-Kaestchen. Nur ab ZWEI Gruppen -
    // bei einer gibt es nichts zu waehlen. Die Knoepfe stehen AUSSERHALB der
    // <label>; der Klick setzt die Kaestchen und feuert je geaendertem Kaestchen
    // ein bubbelndes `change` - alle vorhandenen Hoerer (Ablage-Sperre,
    // Filter-Cookie, CF-Knopf) laufen so ohne eigenen Sonderweg.
    // Auch von wissen_destillat.js genutzt (window.WissenGruppenWahl).
    function groupBulkBar(cls, anzahl) {
        if (!(anzahl > 1)) return '';
        return '<span class="wi-grp-bulk">'
            + '<button type="button" class="sec-btn small wi-grp-bulkbtn" data-grp-cls="' + esc(cls) + '" data-grp-an="1"'
            + ' data-i18n="wissen.grp_all" data-i18n-title="wissen.grp_all_title" title="' + esc(t('wissen.grp_all_title')) + '">'
            + esc(t('wissen.grp_all')) + '</button>'
            + '<button type="button" class="sec-btn small wi-grp-bulkbtn" data-grp-cls="' + esc(cls) + '" data-grp-an="0"'
            + ' data-i18n="wissen.grp_none" data-i18n-title="wissen.grp_none_title" title="' + esc(t('wissen.grp_none_title')) + '">'
            + esc(t('wissen.grp_none')) + '</button>'
            + '</span>';
    }
    // Delegiert am Dokument: die Kaestchen-Reihen entstehen erst beim Zeichnen.
    // Gesucht wird nur im Container der Leiste - dieselbe Klasse kann (z.B. 'rev')
    // an anderer Stelle nicht mitgeschaltet werden.
    document.addEventListener('click', function (ev) {
        var btn = ev.target && ev.target.closest ? ev.target.closest('.wi-grp-bulkbtn') : null;
        if (!btn) return;
        var bar = btn.closest('.wi-grp-bulk');
        var box = bar && bar.parentNode;
        var cls = btn.getAttribute('data-grp-cls') || '';
        if (!box || !/^wi-grp-[a-z]+$/.test(cls)) return;
        var an = btn.getAttribute('data-grp-an') === '1';
        box.querySelectorAll('input[type="checkbox"].' + cls).forEach(function (cb) {
            if (cb.disabled || cb.checked === an) return;
            cb.checked = an;
            cb.dispatchEvent(new Event('change', { bubbles: true }));
        });
    });
    window.WissenGruppenWahl = { leiste: groupBulkBar };

    function groupBoxes(prefix, preselect) {
        // Im Review ('rev') werden standardmaessig die im Extraktor ('up') gewaehlten
        // Wissensgruppen vorbelegt, damit die Auswahl nach „Prüfen" erhalten bleibt.
        var pre = preselect || (prefix === 'rev' ? checkedGroups('up') : []);
        return groupBulkBar('wi-grp-' + prefix, SCOPE.groups.length) + SCOPE.groups.map(function (g) {
            var checked = (SCOPE.groups.length === 1) || (pre.indexOf(g.id) !== -1);
            return '<label class="wi-grpbox" style="border-color:' + esc(g.color) + ';">'
                + '<input type="checkbox" class="wi-grp-' + prefix + '" value="' + esc(g.id) + '"'
                + (checked ? ' checked' : '') + '>'
                + '<span style="font-weight:600;">' + esc(g.name) + '</span></label>';
        }).join('');
    }
    function checkedGroups(prefix) {
        return Array.prototype.slice.call(document.querySelectorAll('.wi-grp-' + prefix + ':checked'))
            .map(function (c) { return c.value; });
    }

    // ── Upload ──────────────────────────────────────────────────────────
    // Ablage-Sperre: solange keine Wissensgruppe gewaehlt ist ODER eine
    // KI-Analyse/ein Upload laeuft, duerfen keine Dateien abgelegt werden.
    var _busy = false;
    var _uploadAbort = null, _uploadJobId = null;   // laufender Upload/URL-Job (abbrechbar)
    function hasFolder() { var s = $('wi-folder'); return !!(s && s.value); }
    function canUpload() { return !_busy && checkedGroups('up').length > 0 && hasFolder(); }
    function updateDropState() {
        var drop = $('wi-drop'), hint = $('wi-drop-hint');
        if (!drop) return;
        var ok = canUpload();
        drop.classList.toggle('disabled', !ok);
        if (hint) {
            if (_busy) { hint.style.display = 'none'; }                       // Busy-Banner uebernimmt
            else if (!checkedGroups('up').length) { hint.style.display = 'block'; hint.textContent = t('wissen.drop_need_group'); }
            else if (!hasFolder()) { hint.style.display = 'block'; hint.textContent = t('wissen.no_folder'); }
            else { hint.style.display = 'none'; }
        }
    }
    // "Extrahieren" ist nur startbar, wenn mindestens eine Wissensgruppe gewaehlt
    // ist (und keine Analyse laeuft) – gilt fuer alle Eingabearten (URL/Datei/CF).
    function actionEnabled() { return !_busy && !_cfJobId && checkedGroups('up').length > 0; }
    function updateActionState() {
        var b = $('wi-extract-btn'); if (b) b.disabled = !actionEnabled();
    }
    // Fortschritts-/Statuszeile in der Aktionsreihe setzen. ``laeuft``: davor
    // steht der animierte Laufanzeiger (per CSS gezeichnet, .wi-hourglass).
    // Code-Review 2026-10-07: vorher war das Signal ein fuehrendes Sanduhr-Emoji
    // im i18n-Text – Emojis rendern je System farbig oder als grauer Kasten.
    function setProgress(msg, color, laeuft) {
        var el = $('wi-extract-progress'); if (!el) return;
        el.style.color = color || 'var(--text-secondary)';
        var m = msg || '';
        if (laeuft) {
            el.innerHTML = '<span class="wi-hourglass" aria-hidden="true"></span>' + esc(m);
        } else {
            el.textContent = m;
        }
    }
    function setBusy(on, genQ) {
        _busy = !!on;
        var b = $('wi-busy'), bt = $('wi-busy-text');
        if (b) b.classList.toggle('hidden', !_busy);
        if (_busy && bt) bt.textContent = genQ ? t('wissen.busy_genq') : t('wissen.busy_upload');
        updateActionState();   // Aktion mitsperren (Busy ODER keine Gruppe)
        updateDropState();
    }

    // Gewuenschte Fragenanzahl aus dem Zahlenfeld (1..30, Fallback 20)
    // Gewuenschte Fragenanzahl EINSCHLIESSLICH des Haken-Zustands:
    // 0 = ausdruecklich keine Fragen. Gilt fuer alle drei Eingabearten
    // (Datei, URL, Confluence) – der Haken steht bewusst unter allen dreien.
    function qaWish() {
        return ($('wi-genq') && $('wi-genq').checked) ? qaCount() : 0;
    }

    function qaCount() {
        var n = parseInt(($('wi-genq-count') || {}).value, 10);
        if (isNaN(n) || n < 1) n = 20; if (n > 30) n = 30;
        return n;
    }
    // Unterordner an eine andere Stelle im eigenen Bereich haengen. Die Vektor-
    // Eintraege ziehen mit um – kein Neu-Indizieren noetig.
    function moveSubfolder() {
        var entry = currentFolderEntry();
        if (!entry || !(entry.depth > 0)) return;
        var parent = entry.path.split('/').slice(0, -1).join('/');
        // Weder der Ordner selbst, noch seine Unterordner (Schleife), noch der
        // aktuelle Elternordner sind sinnvolle Ziele.
        var options = (SCOPE.folders || []).filter(function (f) {
            return f.path !== entry.path
                && f.path.indexOf(entry.path + '/') !== 0
                && f.path !== parent;
        });
        if (!options.length) {
            folderStatus(t('wissen.move_no_target', 'Kein anderer Zielordner vorhanden'), true);
            return;
        }
        pickFolder(options, entry.name).then(function (target) {
            if (!target) return;
            fetch('/api/wissen/subfolders/move', {
                method: 'POST', headers: authH({ 'Content-Type': 'application/json' }),
                body: JSON.stringify({ path: entry.path, target: target })
            })
                .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d || {} }; }); })
                .then(function (res) {
                    if (!res.ok || res.d.error) { folderStatus(res.d.error || t('common.error'), true); return; }
                    var chunks = (res.d.moved && res.d.moved.vector_chunks) || 0;
                    folderStatus(t('wissen.subfolder_moved', 'Unterordner verschoben, {c} Chunks übernommen')
                        .replace('{c}', chunks));
                    return reloadFolders(res.d.path).then(function () { loadFiles(); });
                })
                .catch(function () { folderStatus(t('wissen.conn_error'), true); });
        });
    }

    // Zielordner-Auswahl als Modal. Loest mit dem Pfad auf oder mit null (Abbruch).
    function pickFolder(options, label) {
        return new Promise(function (resolve) {
            var old = $('wi-move-modal'); if (old) old.remove();
            var modal = document.createElement('div');
            modal.id = 'wi-move-modal';
            modal.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;'
                + 'justify-content:center;background:rgba(0,0,0,0.6);backdrop-filter:blur(4px);';
            var rows = options.map(function (f) {
                var pad = 10 + (f.depth || 0) * 16;
                return '<button class="wi-move-opt" data-path="' + esc(f.path) + '" type="button" '
                    + 'style="display:block;width:100%;text-align:left;background:none;border:none;'
                    + 'border-radius:6px;cursor:pointer;padding:7px 10px;padding-left:' + pad + 'px;'
                    + 'color:var(--text-primary);font-size:0.85rem;">'
                    + ((f.depth || 0) ? '↳' : '▸') + ' ' + esc(f.name)
                    + ' <span style="color:var(--text-secondary);font-size:0.75rem;">' + esc(f.display || anzeigePfad(f.path)) + '</span>'
                    + '</button>';
            }).join('');
            modal.innerHTML = '<div style="background:var(--bg-secondary);border:1px solid var(--border);'
                + 'border-radius:12px;max-width:560px;width:90vw;max-height:75vh;display:flex;'
                + 'flex-direction:column;box-shadow:var(--shadow-md);">'
                + '<div style="display:flex;align-items:center;justify-content:space-between;padding:14px 16px;'
                + 'border-bottom:1px solid var(--border);">'
                + '<span style="font-weight:600;font-size:0.9rem;">'
                + esc(t('wissen.move_title', 'Zielordner wählen')) + ' (' + esc(String(label)) + ')</span>'
                + '<button id="wi-move-close" style="background:none;border:none;color:var(--text-secondary);'
                + 'font-size:1.2rem;cursor:pointer;padding:2px 6px;">✕</button></div>'
                + '<div style="padding:8px;overflow:auto;flex:1;">' + rows + '</div>'
                + '<div style="padding:10px 16px;border-top:1px solid var(--border);color:var(--text-secondary);'
                + 'font-size:0.75rem;">' + esc(t('wissen.move_hint', 'Die Vektor-Einträge ziehen mit um – kein Neu-Indizieren nötig.'))
                + '</div></div>';
            document.body.appendChild(modal);
            function done(v) { modal.remove(); resolve(v); }
            $('wi-move-close').addEventListener('click', function () { done(null); });
            Array.prototype.forEach.call(modal.querySelectorAll('.wi-move-opt'), function (b) {
                b.addEventListener('click', function () { done(b.getAttribute('data-path')); });
            });
        });
    }

    // Klartext zu einem HTTP-Status, wenn der Server keinen eigenen Fehlertext
    // liefert (Proxy-Fehlerseiten, leere Bodies).
    function httpHint(status) {
        var map = {
            401: t('wissen.http_401', 'Nicht angemeldet – bitte neu einloggen.'),
            403: t('wissen.http_403', 'Keine Berechtigung für diesen Ordner bzw. diese Wissensgruppe.'),
            404: t('wissen.http_404', 'Zielordner nicht gefunden.'),
            409: t('wissen.http_409', 'Indizierung läuft gerade – bitte kurz warten.'),
            413: t('wissen.http_413', 'Datei zu groß für den Server.'),
            502: t('wissen.http_502', 'Server nicht erreichbar (502).'),
            504: t('wissen.http_504', 'Zeitüberschreitung beim Hochladen (504).')
        };
        return map[status] || t('wissen.http_other', 'Unerwarteter Serverfehler.');
    }

    function uploadFiles(fileList) {
        var st = $('wi-upload-status');
        var groups = checkedGroups('up');
        if (_busy) return;   // laufende Analyse: keine weitere Ablage
        if (!groups.length) { st.style.color = 'var(--danger)'; st.textContent = t('wissen.pick_group'); updateDropState(); return; }
        if (!hasFolder()) { st.style.color = 'var(--danger)'; st.textContent = t('wissen.no_folder'); updateDropState(); return; }
        if (!fileList || !fileList.length) return;
        var fd = new FormData();
        for (var i = 0; i < fileList.length; i++) fd.append('files', fileList[i]);
        fd.append('folder', $('wi-folder').value);
        fd.append('groups', groups.join(','));
        // Optional: Frage-Antwort-Paare generieren (Checkbox + gewuenschte Anzahl)
        var genQ = $('wi-genq') && $('wi-genq').checked;
        // Bei ausgeschaltetem Haken die 0 AUSDRUECKLICH senden. Frueher blieb das Feld
        // weg und das Backend leitete daraus die Standardregel ab -> es entstanden
        // trotzdem Fragen. Auf ein weggelassenes Feld darf man sich nicht verlassen.
        fd.append('gen_questions', String(qaWish()));
        // Abbrechbar machen (wie bei Confluence): Client-Abort + server-seitiger job_id
        _uploadJobId = 'wup_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
        _uploadAbort = new AbortController();
        fd.append('job_id', _uploadJobId);
        st.textContent = '';
        setBusy(true, genQ);   // prominentes Warten-Banner + Ablage-Sperre
        var cancel = $('wi-extract-cancel'); if (cancel) cancel.style.display = '';
        fetch('/api/wissen/upload', { method: 'POST', headers: authH(), body: fd, signal: _uploadAbort.signal })
            // Antwort IMMER als Text lesen und selbst parsen: bei 413/502/504 oder einer
            // Proxy-Fehlerseite kommt kein JSON – ein blosses r.json() wuerde werfen und
            // die eigentliche Ursache im catch verschlucken.
            .then(function (r) {
                return r.text().then(function (body) {
                    var d = null;
                    try { d = JSON.parse(body); } catch (_) { /* kein JSON */ }
                    if (!r.ok) {
                        var detail = (d && (d.error || d.detail))
                            || (body || '').replace(/<[^>]*>/g, ' ').trim().slice(0, 300)
                            || httpHint(r.status);
                        throw new Error('HTTP ' + r.status + ' – ' + detail);
                    }
                    return d || {};
                });
            })
            .then(function (d) {
                d = d || {};
                if (d.error) { st.style.color = 'var(--danger)'; st.textContent = '✗ ' + d.error; return; }
                st.style.color = 'var(--success)';
                var msg = t('wissen.saved_n', { n: d.total_saved || 0 })
                    + (d.total_rejected ? t('wissen.rejected_n', { n: d.total_rejected }) : '') + '.';
                // ZIP-Upload: neu angelegte Unterordner melden und Ordnerauswahl nachziehen
                if (d.created_dirs) {
                    msg += ' ' + t('wissen.zip_dirs_n', { n: d.created_dirs });
                    reloadFolders($('wi-folder') && $('wi-folder').value);
                }
                // Abgelehntes NIE nur zaehlen – der Grund je Datei muss sichtbar sein
                // (z.B. "tool.exe: Format '.exe' nicht unterstuetzt" aus einem Archiv).
                if (d.rejected && d.rejected.length) {
                    st.style.color = 'var(--warning)';
                    var shown = d.rejected.slice(0, 8).map(function (e) {
                        return (e.name || '?') + ': ' + (e.reason || '?');
                    }).join(' · ');
                    if (d.rejected.length > 8) shown += ' … (+' + (d.rejected.length - 8) + ')';
                    msg += ' ⚠ ' + shown;
                }
                if (d.qa_pending && d.qa_pending.length) msg += ' ' + t('wissen.genq_done', { n: d.qa_pending.length });
                if (d.cancelled) { st.style.color = 'var(--warning)'; msg += ' ' + t('wissen.cancelled', 'Abgebrochen.'); }
                if (d.qa_errors && d.qa_errors.length) {
                    st.style.color = 'var(--warning)';
                    msg += ' ⚠ ' + d.qa_errors.map(function (e) { return e.name + ': ' + e.error; }).join(' · ');
                }
                st.textContent = msg;
                loadFiles();
                // Generierte Entwuerfe: Liste aktualisieren + ersten direkt zum Audit oeffnen
                if (d.qa_pending && d.qa_pending.length) {
                    loadPending();
                    fetch('/api/wissen/pending', { headers: authH() })
                        .then(function (r) { return r.json(); })
                        .then(function (p) {
                            var doc = ((p && p.pending) || []).find(function (x) { return x.id === d.qa_pending[0].id; });
                            if (doc) { showReview(doc); $('wi-ext-review').scrollIntoView({ behavior: 'smooth' }); }
                        }).catch(function () {});
                }
            })
            .catch(function (e) {
                if (e && e.name === 'AbortError') {
                    st.style.color = 'var(--warning)';
                    st.textContent = t('wissen.cancelled', 'Abgebrochen.');
                    loadFiles(); loadPending();
                    return;
                }
                st.style.color = 'var(--danger)';
                // Ursache IMMER mit ausgeben – ohne sie ist die Meldung wertlos.
                // TypeError = fetch selbst gescheitert (Netz weg, Server nicht erreichbar,
                // Verbindung waehrend eines grossen Uploads abgebrochen).
                var why = (e && e.name === 'TypeError')
                    ? t('wissen.upload_neterr', 'Verbindung zum Server abgebrochen (Netzwerk, Zeitüberschreitung oder Datei zu groß).')
                    : (e && e.message ? e.message : String(e || '?'));
                st.textContent = t('wissen.upload_failed') + ' ' + why;
                console.error('[wissen] Upload fehlgeschlagen:', e);
            })
            .then(function () {
                _uploadAbort = null; _uploadJobId = null;
                if (cancel) cancel.style.display = 'none';
                setBusy(false);
            });
    }

    // ── Mein Wissen ─────────────────────────────────────────────────────
    // ── Wissensgruppen-Filter fuer "Mein Wissen" ────────────────────────
    // Gespeichert werden die ABGEWAEHLTEN Gruppen. So sind neu hinzukommende
    // Gruppen automatisch sichtbar (Vorgabe: alles gewaehlt).
    var FILTER_COOKIE = 'jarvis_wissen_gfilter_off';
    var _files = [];   // zuletzt geladene Dateiliste (ungefiltert)

    function readCookie(name) {
        var m = document.cookie.match(new RegExp('(?:^|; )' + name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + '=([^;]*)'));
        return m ? decodeURIComponent(m[1]) : '';
    }

    function writeCookie(name, value) {
        // 1 Jahr haltbar; Lax reicht, der Wert ist reine Anzeige-Praeferenz.
        document.cookie = name + '=' + encodeURIComponent(value)
            + ';path=/;max-age=31536000;SameSite=Lax';
    }

    function hiddenGroups() {
        var raw = readCookie(FILTER_COOKIE);
        return raw ? raw.split(',').filter(Boolean) : [];
    }

    // ── Suche ueber "Mein Wissen" ───────────────────────────────────────
    // Zwei Stufen, wie die Filter-Box der Massenzuordnung: Name/Ordner/Gruppe
    // sofort aus den geladenen Daten, der DATEI-INHALT zusaetzlich (verzoegert)
    // ueber /api/knowledge/content_search.
    var SUCH_VERZUG = 300;     // ms - erst tippen lassen, dann den Server fragen
    var SUCH_MIN = 2;          // kuerzer lohnt keine Inhaltssuche (Endpunkt liefert dann [])
    var _inhaltFuer = null;    // zu WELCHEM Begriff die Treffer unten gehoeren
    var _inhaltTreffer = null; // Set der Pfade oder null (= noch nichts vom Server)
    var _suchTimer = null;

    // Der Suchbegriff wird IMMER aus dem Feld gelesen, nie aus einer zweiten
    // Variablen: so koennen Feldinhalt und gezeigte Liste nicht auseinander-
    // laufen (Chrome-Autofill fuellt Felder ohne `input`-Ereignis - im
    // Audit-Log hat genau das eine Liste "wirkungslos" aussehen lassen).
    function suchText() {
        var el = $('wi-files-q');
        return el ? el.value.trim().toLowerCase() : '';
    }

    // ⚠ DIE PFADFORMEN DER BEIDEN ENDPUNKTE SIND NICHT GLEICH - gemessen:
    // /api/wissen/files normalisiert ueber knowledge_groups._rel und streift
    // dabei den fuehrenden Schraegstrich ab (`mnt/rag/share_1/x.pdf`),
    // content_search gibt ihn zurueck (`/mnt/rag/share_1/x.pdf`). Ohne diese
    // Angleichung traefe die Inhaltssuche bei JEDER Datei aus einer
    // Netzwerk-Freigabe daneben - und das sind im Betrieb die meisten.
    function pfadSchluessel(p) {
        return String(p == null ? '' : p).replace(/\\/g, '/').replace(/^\/+/, '').toLowerCase();
    }

    // Text, den die Sofort-Suche durchsucht: was in der Zeile sichtbar ist.
    function suchHeu(f) {
        return ((f.name || '') + ' ' + ordnerText(f) + ' ' + (f.path || '') + ' '
            + (f.groups || []).map(function (g) { return g.name || ''; }).join(' ')).toLowerCase();
    }

    function trifftSuche(f, q) {
        if (!q) return true;
        if (suchHeu(f).indexOf(q) !== -1) return true;
        // Inhalts-Treffer zaehlen nur, wenn sie zum AKTUELLEN Begriff gehoeren
        return !!(_inhaltTreffer && _inhaltFuer === q
            && _inhaltTreffer.has(pfadSchluessel(f.path)));
    }

    // Sichtbarkeit der Suchzeile: sie gehoert dorthin, wo es etwas zu suchen
    // gibt. Bei leerem Bereich sagt die Leermeldung ohnehin alles.
    function renderFileSearch() {
        var wrap = $('wi-files-search'), hint = $('wi-files-search-hint');
        var an = _files.length > 0;
        if (wrap) wrap.style.display = an ? '' : 'none';
        if (hint) hint.style.display = an ? '' : 'none';
    }

    function bindFileSearch() {
        var el = $('wi-files-q');
        if (!el || el._gebunden) return;
        el._gebunden = true;
        el.addEventListener('input', function () {
            var q = suchText();
            clearTimeout(_suchTimer);
            renderFileList();                 // Name/Ordner sofort
            if (q.length < SUCH_MIN) { _inhaltFuer = null; _inhaltTreffer = null; return; }
            _suchTimer = setTimeout(function () {
                fetch('/api/knowledge/content_search?q=' + encodeURIComponent(q), { headers: authH() })
                    .then(function (r) { return r.json(); })
                    .then(function (d) {
                        // Spart einen Neuaufbau, wenn inzwischen weitergetippt
                        // wurde. Die KORREKTHEIT haengt daran NICHT: darueber
                        // entscheidet `_inhaltFuer === q` beim Zeichnen - ein
                        // Sequenz-Zaehler daneben waere messbar wirkungslos.
                        if (suchText() !== q) return;
                        if (!d || !d.ok) return;
                        _inhaltFuer = q;
                        _inhaltTreffer = new Set((d.files || []).map(pfadSchluessel));
                        renderFileList();
                    })
                    .catch(function () { /* dann eben nur Name/Ordner */ });
            }, SUCH_VERZUG);
        });
        // Escape leert das Feld - sonst muss man den Text von Hand loeschen,
        // um die ganze Liste zurueckzubekommen.
        el.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && el.value) {
                e.preventDefault();
                el.value = '';
                _inhaltFuer = null; _inhaltTreffer = null;
                renderFileList();
            }
        });
    }

    function renderFileFilter() {
        var wrap = $('wi-files-filter'), boxes = $('wi-files-filter-boxes');
        if (!wrap || !boxes) return;
        var groups = (SCOPE && SCOPE.groups) || [];
        if (!groups.length) { wrap.style.display = 'none'; return; }
        wrap.style.display = '';
        var off = hiddenGroups();
        boxes.innerHTML = groupBulkBar('wi-grp-flt', groups.length) + groups.map(function (g) {
            var on = off.indexOf(g.id) === -1;   // Vorgabe: gewaehlt
            return '<label class="wi-grpbox" style="border-color:' + esc(g.color) + ';">'
                + '<input type="checkbox" class="wi-grp-flt" value="' + esc(g.id) + '"'
                + (on ? ' checked' : '') + '>'
                + '<span style="font-weight:600;">' + esc(g.name) + '</span></label>';
        }).join('');
        boxes.querySelectorAll('.wi-grp-flt').forEach(function (cb) {
            cb.addEventListener('change', function () {
                var hidden = groups.map(function (g) { return g.id; })
                    .filter(function (id) { return checkedGroups('flt').indexOf(id) === -1; });
                writeCookie(FILTER_COOKIE, hidden.join(','));
                renderFileList();
            });
        });
    }

    // Ordner einer Datei fuer die Anzeige. Regelweg ist das Feld `folder` vom
    // Server (er kennt die konfigurierten Wurzelordner, der Client nicht
    // vollstaendig). Der Rueckfall greift, solange ein aelteres Backend laeuft
    // (halber Deploy) – dann steht der rohe Verzeichnispfad da, statt nichts.
    // Pfad ohne den Praefix, der in jeder Zeile derselbe ist (data/rag/, /mnt/rag/).
    // Rueckfall zum Server-Feld `display`; ein Test haelt beide deckungsgleich.
    function anzeigePfad(p) {
        var s = String(p == null ? '' : p).replace(/\\/g, '/').trim().replace(/\/+$/, '');
        if (!s) return '';
        var basen = ['data/rag', '/mnt/rag', '/mnt/jarvis-kb'];
        for (var i = 0; i < basen.length; i++) {
            if (s.indexOf(basen[i] + '/') === 0) {
                return s.slice(basen[i].length + 1).replace(/^\/+|\/+$/g, '') || s;
            }
        }
        return s;
    }

    function ordnerText(f) {
        if (f && f.folder) return f.folder;
        var p = String((f && f.path) || '');
        var i = p.lastIndexOf('/');
        return i > 0 ? p.slice(0, i) : '';
    }

    // Zeichnet die Dateiliste aus _files, eingeschraenkt auf die aktiven Gruppen.
    function renderFileList() {
        var box = $('wi-files-list');
        if (!box) return;
        var off = hiddenGroups();
        var q = suchText();
        var inGruppe = _files.filter(function (f) {
            // Datei bleibt sichtbar, solange mindestens eine ihrer Gruppen aktiv ist
            return (f.groups || []).some(function (g) { return off.indexOf(g.id) === -1; });
        });
        var shown = inGruppe.filter(function (f) { return trifftSuche(f, q); });

        var cnt = $('wi-files-count');
        if (cnt) {
            cnt.textContent = shown.length === _files.length
                ? t('wissen.count_all', { n: _files.length })
                : t('wissen.count_filtered', { n: shown.length, total: _files.length });
        }

        if (!_files.length) { box.innerHTML = '<div class="wi-empty">' + t('wissen.no_files') + '</div>'; return; }
        // Die Leermeldung muss den GRUND nennen: "keine Dateien in den gewaehlten
        // Wissensgruppen" waere bei einer erfolglosen Suche eine Falschaussage -
        // der Benutzer sucht dann den Fehler beim Gruppenfilter.
        if (!shown.length) {
            var grund = (q && inGruppe.length)
                ? t('wissen.no_files_search', { q: q })
                : t('wissen.no_files_filtered');
            box.innerHTML = '<div class="wi-empty">' + esc(grund) + '</div>';
            return;
        }
        sortieren(shown);
        var spalten = [
            { key: 'name', lbl: 'wissen.col_name', cls: '' },
            { key: 'folder', lbl: 'wissen.col_folder', cls: '' },
            { key: 'groups', lbl: 'wissen.col_groups', cls: '' },
            { key: 'size', lbl: 'wissen.col_size', cls: 'wi-fsize' }
        ];
        var kopf = spalten.map(function (c) {
            var aktiv = _fsort.key === c.key;
            // aria-sort traegt den Zustand fuer Vorleser, der Pfeil fuer das
            // Auge – ein Pfeil allein waere nur ein Zeichen.
            return '<th scope="col" class="' + c.cls + '" data-sort="' + c.key + '"'
                + ' aria-sort="' + (aktiv ? (_fsort.dir > 0 ? 'ascending' : 'descending') : 'none') + '">'
                + '<button type="button" class="wi-sortbtn" title="' + esc(t('wissen.sort_by', { col: t(c.lbl) })) + '">'
                + esc(t(c.lbl))
                + '<span class="wi-sortpfeil" aria-hidden="true">' + (aktiv ? (_fsort.dir > 0 ? '▲' : '▼') : '') + '</span>'
                + '</button></th>';
        }).join('') + '<th scope="col" class="wi-fdel"></th>';

        var zeilen = shown.map(function (f) {
            var chips = (f.groups || []).map(function (g) {
                return '<span class="wi-chip" style="border-color:' + esc(g.color) + ';font-size:0.7rem;">' + esc(g.name) + '</span>';
            }).join('');
            var url = '/api/wissen/file?path=' + encodeURIComponent(f.path) + '&token=' + encodeURIComponent(_dlk());
            var ord = ordnerText(f);
            var gr = groesseText(f.size);
            // Der Ordner steht in einer EIGENEN, sichtbaren Spalte – ein Tooltip
            // ist unsichtbar, und zwei gleichnamige Dateien in verschiedenen
            // Unterordnern waren sonst nicht zu unterscheiden. Der `title`
            // traegt zusaetzlich den vollen technischen Pfad.
            // ⚠ NICHT `wi-item`: die Klasse traegt `display: flex` (Entwurfsliste)
            // und zerlegte die Tabellenzeile.
            return '<tr class="wi-frow" data-path="' + esc(f.path) + '"'
                + ' data-label="' + esc(ord ? ord + '/' + f.name : f.name) + '">'
                + '<td class="wi-fname"><a class="nm wi-flink" href="' + esc(url) + '" target="_blank" rel="noopener" title="' + esc(t('wissen.open_file')) + '">' + esc(f.name) + '</a></td>'
                + '<td class="wi-fpath" title="' + esc(t('wissen.file_folder', { p: f.path })) + '">' + esc(ord) + '</td>'
                + '<td class="wi-fgrp">' + chips + '</td>'
                + '<td class="wi-fsize"' + (f.size == null ? ' title="' + esc(t('wissen.size_unknown')) + '"' : '') + '>' + esc(gr) + '</td>'
                + '<td class="wi-fdel"><button type="button" class="sec-btn small danger wi-file-del" title="' + esc(t('wissen.delete_file')) + '">' + JarvisIcons.trash() + '</button></td>'
                + '</tr>';
        }).join('');

        box.innerHTML = '<div class="wi-ftable-wrap"><table class="wi-ftable">'
            + '<thead><tr>' + kopf + '</tr></thead><tbody>' + zeilen + '</tbody></table></div>';

        box.querySelectorAll('th[data-sort] .wi-sortbtn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var k = btn.parentNode.getAttribute('data-sort');
                // Gleiche Spalte: Richtung umkehren. Neue Spalte: aufsteigend.
                if (_fsort.key === k) _fsort.dir = -_fsort.dir;
                else { _fsort.key = k; _fsort.dir = 1; }
                renderFileList();
            });
        });
        box.querySelectorAll('.wi-file-del').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var row = btn.closest('.wi-frow');
                // Die Rueckfrage nennt Ordner UND Name (data-label) – bei
                // gleichnamigen Dateien waere "Datei X loeschen?" nicht deutbar,
                // und hier geht es um Datenverlust.
                deleteFile(row.getAttribute('data-path'), row.getAttribute('data-label'));
            });
        });
    }

    // ── Sortierung "Mein Wissen" ────────────────────────────────────────
    // Der Zustand lebt im Modul (wie `_sortKey` der Massenzuordnung): er
    // ueberlebt Suche, Filter und Neuladen der Liste, nach einem Neuladen der
    // Seite gilt wieder die Vorgabe Name aufsteigend – die Reihenfolge, in der
    // auch der Server liefert.
    var _fsort = { key: 'name', dir: 1 };

    function sprache() { return window._lang || 'de'; }

    // Deutsch sortiert "Ä" zu "A" und "Datei 10" hinter "Datei 2" (numeric) –
    // ein reiner Zeichencode-Vergleich stellte Umlaute ans Ende.
    function vergleichText(a, b) {
        return String(a || '').localeCompare(String(b || ''), sprache(), { numeric: true, sensitivity: 'base' });
    }
    function gruppenText(f) {
        return (f.groups || []).map(function (g) { return g.name || ''; }).join(', ');
    }

    function sortieren(liste) {
        var k = _fsort.key, d = _fsort.dir;
        liste.sort(function (a, b) {
            var r;
            if (k === 'size') {
                // Unbekannte Groesse steht IMMER am Ende, in beiden Richtungen:
                // sie ist keine kleine Datei.
                var an = a.size == null, bn = b.size == null;
                if (an || bn) { if (an && bn) r = 0; else return an ? 1 : -1; }
                else r = (a.size - b.size) * d;
            } else if (k === 'folder') {
                r = vergleichText(ordnerText(a), ordnerText(b)) * d;
            } else if (k === 'groups') {
                r = vergleichText(gruppenText(a), gruppenText(b)) * d;
            } else {
                r = vergleichText(a.name, b.name) * d;
            }
            // Stabil und vorhersehbar bei Gleichstand: Name, dann Ordner.
            return r || vergleichText(a.name, b.name) || vergleichText(ordnerText(a), ordnerText(b));
        });
        return liste;
    }

    // Groesse lesbar, in der Sprache der Oberflaeche (1.024er-Stufen wie der
    // Dateimanager). `null` = nicht ermittelt – dann ein Strich, NIE "0 B".
    function groesseText(n) {
        if (n == null || isNaN(n)) return '–';
        var stufen = ['B', 'KB', 'MB', 'GB', 'TB'], i = 0, v = Number(n);
        while (v >= 1024 && i < stufen.length - 1) { v /= 1024; i++; }
        return v.toLocaleString(sprache(), { maximumFractionDigits: i && v < 10 ? 1 : 0 }) + ' ' + stufen[i];
    }

    // ── Maximieren der Seite (Knopf ⛶ hinter "Angemeldet als ...") ──────
    // Seit 2026-09-28 der gemeinsame Baustein aller Seiten (seite_breit.js);
    // der gemerkte Zustand bleibt unter `jarvis_wissen_breit` (data-speicher).

    function loadFiles() {
        fetch('/api/wissen/files', { headers: authH() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                _files = (d && d.files) || [];
                renderFileSearch();
                bindFileSearch();
                renderFileFilter();
                renderFileList();
            })
            .catch(function () {});
    }

    function deleteFile(path, name) {
        if (!path) return;
        if (!window.confirm(t('wissen.delete_confirm', { name: name || path }))) return;
        fetch('/api/wissen/file', {
            method: 'DELETE', headers: authH({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ path: path })
        }).then(function (r) { return r.json(); })
          .then(function (d) {
              if (d && d.ok) { loadFiles(); }
              else { window.alert((d && d.error) || t('wissen.delete_failed')); }
          })
          .catch(function () { window.alert(t('wissen.delete_failed')); });
    }

    // ── Extraktor (Webseite) ────────────────────────────────────────────
    // Fragen & Antworten werden bei der URL-Analyse IMMER generiert
    // (Anzahl aus dem Zahlenfeld); waehrend der Analyse ist die Ablage gesperrt.
    function extractUrl() {
        var url = $('wi-ext-url').value.trim();
        if (!url || _busy) return;
        var st = $('wi-ext-status');
        st.style.color = 'var(--text-secondary)'; st.textContent = t('wissen.extracting');
        // Abbrechbar: Client-Abort trennt die Verbindung -> Server bricht ab.
        _uploadAbort = new AbortController(); _uploadJobId = null;
        setBusy(true, true);
        var cancel = $('wi-extract-cancel'); if (cancel) cancel.style.display = '';
        fetch('/api/wissen/extract', { method: 'POST', headers: authH({ 'Content-Type': 'application/json' }), body: JSON.stringify({ url: url, qa_count: qaWish() }), signal: _uploadAbort.signal })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.error) { st.style.color = 'var(--danger)'; st.textContent = '✗ ' + d.error; return; }
                st.textContent = ''; $('wi-ext-url').value = '';
                showReview(d); loadPending();
            })
            .catch(function (e) {
                if (e && e.name === 'AbortError') { st.style.color = 'var(--warning)'; st.textContent = t('wissen.cancelled', 'Abgebrochen.'); }
                else { st.style.color = 'var(--danger)'; st.textContent = t('wissen.extract_failed'); }
            })
            .then(function () {
                _uploadAbort = null; _uploadJobId = null;
                if (cancel) cancel.style.display = 'none';
                setBusy(false);
            });
    }

    function docPreview(d) {
        var parts = [];
        if (d.summary) parts.push(d.summary);
        if (d.facts && d.facts.length) parts.push('\n' + t('wissen.facts_label') + '\n- ' + d.facts.join('\n- '));
        return parts.join('\n');
    }

    // Q&A-Audit: eine editierbare Zeile pro Frage-Antwort-Paar
    // (Checkbox = freigeben, Textfelder = korrigieren, Muelleimer = loeschen).
    function qaRowHtml(p, i) {
        return '<div class="wi-qa-row" data-qid="' + esc(p.id || String(i)) + '" style="display:flex;gap:8px;align-items:flex-start;margin-bottom:8px;">'
            + '<input type="checkbox" class="wi-qa-keep" ' + (p.approved !== false ? 'checked' : '') + ' title="' + esc(t('wissen.qa_keep')) + '" style="margin-top:8px;">'
            + '<div style="flex:1;min-width:0;">'
            + '<input class="wi-input wi-qa-q" value="' + esc(p.q || '') + '" placeholder="' + esc(t('wissen.qa_q_ph')) + '" style="margin-bottom:4px;font-weight:600;">'
            + '<textarea class="wi-input wi-qa-a" rows="2" placeholder="' + esc(t('wissen.qa_a_ph')) + '" style="resize:vertical;">' + esc(p.a || '') + '</textarea>'
            + '</div>'
            + '<button type="button" class="sec-btn small danger wi-qa-del" title="' + esc(t('wissen.qa_del')) + '" style="margin-top:6px;">' + JarvisIcons.trash() + '</button>'
            + '</div>';
    }

    // ── Platz der Vorschau ──────────────────────────────────────────────
    // Es gibt nur EINEN Vorschau-Container (#wi-ext-review) und damit nur eine
    // Logik zum Freigeben/Verwerfen. Sein Platz wechselt: nach einer Extraktion
    // steht er unter dem Extraktor (Heimatplatz aus dem HTML), beim „Prüfen"
    // eines Entwurfs wird das GLEICHE Element unter die angeklickte Zeile
    // verschoben – dort wird es erwartet, nicht ueber der ganzen Liste.
    var _revHome = null;   // { parent, next } – Heimatplatz laut HTML
    var _revId = '';       // Entwurf, der aktuell in der Vorschau liegt

    function _revPlace(anchor) {
        var el = $('wi-ext-review');
        if (!el) return;
        // Heimatplatz beim ersten Verschieben festhalten (danach nie neu lesen,
        // sonst merkt sich der Merker die verschobene Position).
        if (!_revHome) _revHome = { parent: el.parentNode, next: el.nextSibling };
        if (anchor && anchor.parentNode) anchor.parentNode.insertBefore(el, anchor.nextSibling);
        else if (_revHome.parent) _revHome.parent.insertBefore(el, _revHome.next);
    }

    // Vorschau leeren UND aus der Liste zurueckholen – sonst wuerde sie beim
    // naechsten `innerHTML = ''` der Liste mitgeloescht (Element waere weg).
    function clearReview() {
        _revId = '';
        _revPlace(null);
        var el = $('wi-ext-review');
        if (el) el.innerHTML = '';
    }

    function showReview(d, anchor) {
        _revId = d.id || '';
        _revPlace(anchor || null);
        var box = $('wi-ext-review');
        var qa = (d.qa_pairs || []);
        // Wie viel des Dokuments hat das Modell gesehen? Bis 2026-08-01 waren es
        // immer nur die ersten 8000 Zeichen, und niemand erfuhr davon. Jetzt
        // wird abschnittsweise verarbeitet – faellt trotzdem etwas weg (sehr
        // lange Dokumente ueber MAX_FENSTER), steht es HIER. Ein stiller Verlust
        // ist der schlimmere Fehler als ein sichtbar unvollstaendiges Ergebnis.
        var cov = d.coverage || null;
        var covHtml = '';
        if (cov && cov.chars_total) {
            var pct = Math.round((cov.chars_seen / cov.chars_total) * 100);
            if (cov.truncated || pct < 99) {
                covHtml = '<div style="font-size:.75rem;color:var(--warning);margin:2px 0 8px;">'
                    + esc(t('wissen.coverage_partial', { pct: pct, n: cov.windows })) + '</div>';
            } else if (cov.windows > 1) {
                covHtml = '<div style="font-size:.75rem;color:var(--text-muted);margin:2px 0 8px;">'
                    + esc(t('wissen.coverage_full', { n: cov.windows })) + '</div>';
            }
        }
        var qaHtml = qa.length
            ? '<label style="font-size:0.78rem;color:var(--text-secondary);display:block;margin-top:10px;">' + t('wissen.qa_audit_label', { n: qa.length }) + '</label>'
              + '<div id="wi-rev-qa" style="margin:6px 0 10px;">' + qa.map(qaRowHtml).join('') + '</div>'
            : '';
        // Zusammenfassung und Kernfakten sind BEARBEITBAR. Vorher standen sie in
        // einem reinen Anzeigefeld: der Pruefer konnte einen falschen Kernfakt
        // sehen, aber nicht korrigieren – seine einzige Handlung waere gewesen,
        // den ganzen Entwurf zu verwerfen. Das Backend nimmt beide Felder seit
        // jeher entgegen (PATCH /api/wissen/pending/{id}).
        var facts = (d.facts || []);
        box.innerHTML = '<div class="wi-review">'
            + '<div style="font-weight:600;margin-bottom:6px;">' + t('wissen.review_title') + '</div>'
            + covHtml
            + '<label style="font-size:0.78rem;color:var(--text-secondary);">' + t('wissen.title_label') + '</label>'
            + '<input class="wi-input" id="wi-rev-title" value="' + esc(d.title || '') + '">'
            + '<label style="font-size:0.78rem;color:var(--text-secondary);display:block;margin-top:8px;">'
            + t('wissen.summary_label') + '</label>'
            + '<textarea class="wi-input" id="wi-rev-summary" rows="4" style="resize:vertical;">'
            + esc(d.summary || '') + '</textarea>'
            + '<label style="font-size:0.78rem;color:var(--text-secondary);display:block;margin-top:8px;">'
            + t('wissen.facts_edit_label', { n: facts.length }) + '</label>'
            + '<textarea class="wi-input" id="wi-rev-facts" rows="' + Math.min(10, Math.max(3, facts.length + 1))
            + '" style="resize:vertical;">' + esc(facts.join('\n')) + '</textarea>'
            + qaHtml
            + '<label style="font-size:0.78rem;color:var(--text-secondary);">' + t('wissen.target_groups') + '</label>'
            + '<div class="wi-groups" id="wi-rev-groups" style="margin:6px 0 10px;">' + groupBoxes('rev') + '</div>'
            // Platz fuer die Dubletten-Warnung: sie wird NACHGELADEN und steht
            // bewusst DIREKT ueber den Knoepfen – dort, wo die Entscheidung
            // faellt. Weiter oben wuerde sie beim Durchscrollen uebersehen.
            + '<div id="wi-rev-similar" style="margin:10px 0 0;"></div>'
            + '<button class="sec-btn primary" id="wi-rev-approve" type="button">' + t('wissen.approve') + '</button> '
            + '<button class="sec-btn danger" id="wi-rev-discard" type="button">' + t('wissen.discard') + '</button>'
            + '</div>';
        // Zeilen-Loeschen (Paar komplett entfernen)
        box.querySelectorAll('.wi-qa-del').forEach(function (btn) {
            btn.addEventListener('click', function () { btn.closest('.wi-qa-row').remove(); });
        });
        $('wi-rev-approve').addEventListener('click', function () { approvePending(d.id); });
        $('wi-rev-discard').addEventListener('click', function () { deletePending(d.id, true); });
        loadSimilar(d.id);
    }

    /** Zeigt bereits vorhandenes, sehr aehnliches Wissen zu diesem Entwurf.
     *
     * Bewusst NACHGELADEN statt Teil der Entwurfs-Antwort: die Suche braucht
     * das Einbettungsmodell und kann beim ersten Aufruf Sekunden dauern. Die
     * Pruefansicht soll sofort da sein; die Warnung kommt nach.
     *
     * Blockiert NICHTS. Faellt die Pruefung aus, bleibt der Bereich leer und
     * die Freigabe funktioniert wie bisher – eine Hilfe, die den Vorgang
     * aufhaelt, waere keine.
     */
    function loadSimilar(id) {
        var box = $('wi-rev-similar');
        if (!box || !id) return;
        box.innerHTML = '<div style="font-size:.75rem;color:var(--text-muted);">'
            + esc(t('wissen.similar_checking')) + '</div>';
        fetch('/api/wissen/pending/' + encodeURIComponent(id) + '/similar', { headers: authH() })
            .then(function (res) { return res.json(); })
            .then(function (r) {
            // Der Entwurf koennte inzwischen gewechselt haben (der Nutzer klickt
            // schnell durch die Liste) – dann gehoert diese Antwort nicht hierher.
            if (_revId !== id) return;
            var el = $('wi-rev-similar');
            if (!el) return;
            var items = (r && r.items) || [];
            if (!r || !r.ok || !items.length) { el.innerHTML = ''; return; }
            el.innerHTML = '<details class="wi-similar" open>'
                + '<summary style="cursor:pointer;color:var(--warning);font-size:.8rem;font-weight:600;">'
                + esc(t('wissen.similar_found', { n: items.length })) + '</summary>'
                + '<div style="font-size:.74rem;color:var(--text-muted);margin:4px 0 8px;">'
                + esc(t('wissen.similar_hint')) + '</div>'
                + items.map(function (it) {
                    return '<div style="border-left:2px solid var(--warning);padding:4px 0 4px 8px;margin:6px 0;">'
                        + '<div style="font-size:.74rem;color:var(--text-secondary);">'
                        + '<code>' + esc(it.file) + '</code> · ' + esc(it.matched)
                        + ' · ' + Math.round((it.score || 0) * 100) + '%</div>'
                        + '<div style="font-size:.75rem;margin-top:2px;">' + esc(it.text) + '</div>'
                        + '</div>';
                }).join('')
                + '</details>';
        }).catch(function () {
            var el = $('wi-rev-similar');
            if (el) el.innerHTML = '';
        });
    }

    // Auditierte Q&A-Paare aus einem Review-Formular einsammeln
    // (geloeschte Zeilen fehlen; Checkbox ab = nicht freigeben).
    //
    // `wurzel` benennt den Container. Ohne Argument bleibt es die
    // Entwurfs-Pruefung (#wi-rev-qa); die Bearbeitungsmaske fuer bereits
    // uebernommene Dokumente reicht ihren eigenen Container herein. EINE
    // Fassung fuer beide - eine zweite Lesestelle liefe beim naechsten
    // Feinschliff auseinander, und dann sammelte die eine Maske Felder ein,
    // die die andere nicht kennt.
    function collectQa(wurzel) {
        var el = wurzel || $('wi-rev-qa');
        var rows = el ? el.querySelectorAll('.wi-qa-row') : [];
        if (!rows.length) return null;   // kein Q&A-Audit im Formular
        var out = [];
        rows.forEach(function (row) {
            var q = (row.querySelector('.wi-qa-q') || {}).value || '';
            var a = (row.querySelector('.wi-qa-a') || {}).value || '';
            if (!q.trim()) return;
            out.push({
                id: row.getAttribute('data-qid') || '',
                q: q.trim(), a: a.trim(),
                approved: !!(row.querySelector('.wi-qa-keep') || {}).checked,
            });
        });
        return out;
    }

    function approvePending(id) {
        var groups = checkedGroups('rev');
        var st = $('wi-ext-status');
        if (!groups.length) { st.style.color = 'var(--danger)'; st.textContent = t('wissen.pick_target'); return; }
        var title = ($('wi-rev-title') || {}).value;
        var patch = {};
        if (title != null) patch.title = title;
        // Zusammenfassung + Kernfakten aus dem Formular uebernehmen.
        // `!= null` statt Falsyness: ein absichtlich GELEERTES Feld muss auch
        // leer gespeichert werden, sonst bliebe der alte Text stehen.
        var summary = ($('wi-rev-summary') || {}).value;
        if (summary != null) patch.summary = summary.trim();
        var factsRaw = ($('wi-rev-facts') || {}).value;
        if (factsRaw != null) {
            patch.facts = factsRaw.split('\n')
                .map(function (l) { return l.replace(/^\s*[-*•]\s*/, '').trim(); })
                .filter(function (l) { return l.length > 0; });
        }
        var qa = collectQa();
        if (qa !== null) patch.qa_pairs = qa;
        var chain = Promise.resolve();
        if (Object.keys(patch).length) {
            chain = fetch('/api/wissen/pending/' + encodeURIComponent(id), {
                method: 'PATCH', headers: authH({ 'Content-Type': 'application/json' }), body: JSON.stringify(patch)
            }).catch(function () {});
        }
        chain.then(function () {
            return fetch('/api/wissen/pending/' + encodeURIComponent(id) + '/approve', {
                method: 'POST', headers: authH({ 'Content-Type': 'application/json' }), body: JSON.stringify({ groups: groups })
            });
        }).then(function (r) { return r.json(); })
          .then(function (d) {
              if (d.error) { st.style.color = 'var(--danger)'; st.textContent = '✗ ' + d.error; return; }
              st.style.color = 'var(--success)'; st.textContent = t('wissen.approved_ok');
              clearReview(); loadPending(); loadFiles();
          })
          .catch(function () { st.style.color = 'var(--danger)'; st.textContent = t('wissen.approve_failed'); });
    }

    function deletePending(id, alsoReview) {
        fetch('/api/wissen/pending/' + encodeURIComponent(id), { method: 'DELETE', headers: authH() })
            .then(function () {
                // Auch ohne Flag: liegt der geloeschte Entwurf in der Vorschau,
                // muss sie weg – sonst zeigt sie auf etwas, das es nicht mehr gibt.
                if (alsoReview || _revId === id) clearReview();
                loadPending();
            })
            .catch(function () {});
    }

    // ── Bearbeitungsmaske fuer BEREITS UEBERNOMMENE Dokumente ──────────────
    //
    // Gegenstueck zu showReview(), und ausdruecklich NICHT dasselbe:
    // showReview prueft einen ENTWURF – Knoepfe "Uebernehmen"/"Verwerfen",
    // Endpunkte /api/wissen/pending/* mit created_by-Pruefung. HIER liegt das
    // Dokument BEREITS in der Wissensdatenbank. "Uebernehmen" daran anzubieten
    // waere eine falsche Zusage, und "Verwerfen" statt "Aus DB entfernen"
    // verschweigt, dass wirklich geloescht wird.
    //
    // Gearbeitet wird auf der EDITOREN-Familie /api/knowledge/pending/*: die
    // sieht ALLE Dokumente, waehrend /api/wissen/pending/* nur die eigenen
    // herausgibt. Die Massenzuordnung, aus der die Maske gerufen wird, laedt
    // von dort – und sie ist nur fuer globale Wissens-Editoren sichtbar
    // (SCOPE.is_editor), also genau fuer die, die dort auch PATCH und DELETE
    // duerfen (require_knowledge_editor). Deshalb braucht die Maske KEINE
    // eigene Rechtepruefung: wer sie erreicht, darf schreiben.
    //
    // "Aktualisieren" ist PATCH **und** erneutes Uebernehmen. Das PATCH
    // aendert nur den Entwurfsdatensatz; erst das Uebernehmen schreibt die
    // .md-Datei neu, setzt die Wissensgruppen und indiziert nach. Ohne den
    // zweiten Schritt waere der Knopf eine Zusage, die der Bestand nicht
    // einloest – die Datei in der Wissensdatenbank bliebe unveraendert.
    //
    // Ein EIGENES Fenster, nicht der Vorschau-Container #wi-ext-review: ein
    // uebernommenes Dokument hat in der Entwurfsliste keine Zeile, unter die
    // sich die Vorschau schieben koennte (/api/wissen/pending filtert
    // `approved` ausdruecklich heraus), und sie wuerde beim naechsten
    // Listenaufbau mitgeloescht (siehe clearReview). Die Fenster-Bauform ist
    // die von pickFolder() – bewusst OHNE die globale Klasse `modal`, die
    // `opacity:0` traegt und erst mit `.open` sichtbar wird.
    //
    // opts.gruppen   – vorbelegte Wissensgruppen. Kommen vom AUFRUFER, damit
    //                  die Maske genau das zeigt, was die Tabelle daneben
    //                  zeigt (dieselbe Zuordnungskarte, kein zweiter Abruf).
    // opts.entfernen – Funktion, die das Dokument serverseitig entfernt. Sie
    //                  liegt beim Aufrufer, weil dort schon geloescht wird
    //                  (Muelleimer-Spalte); zwei Fassungen desselben
    //                  Loeschwegs liefen beim naechsten Feinschliff
    //                  auseinander. Fehlt sie, gibt es den Knopf nicht.
    function openDocEdit(doc, opts) {
        if (!doc || !doc.id) return;
        opts = opts || {};
        var alt = $('wi-doc-edit'); if (alt) alt.remove();

        var facts = (doc.facts || []);
        var qa    = (doc.qa_pairs || []);
        var quelle = doc.source_type === 'file'
            ? (doc.source_name || doc.url || '')
            : (doc.url || '');

        var modal = document.createElement('div');
        modal.id = 'wi-doc-edit';
        modal.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;'
            + 'justify-content:center;background:rgba(0,0,0,0.6);backdrop-filter:blur(4px);';

        var qaHtml = qa.length
            ? '<label style="font-size:0.78rem;color:var(--text-secondary);display:block;margin-top:8px;">'
              + t('wissen.qa_audit_label', { n: qa.length }) + '</label>'
              + '<div id="wi-de-qa" style="margin:6px 0 10px;">' + qa.map(qaRowHtml).join('') + '</div>'
            : '';
        // Der Entfernen-Knopf traegt den Muelleimer, weil er WIRKLICH loescht
        // (Datei + Datensatz) – das Symbol darf nicht mit dem Schliessen-×
        // verwechselbar sein (icons.js, Entscheidung vom 2026-08-19).
        var entfBtn = opts.entfernen
            ? ' <button class="sec-btn danger" id="wi-de-remove" type="button">'
              + JarvisIcons.trash() + ' ' + esc(t('ext.remove_from_db')) + '</button>'
            : '';

        modal.innerHTML = '<div style="background:var(--bg-secondary);border:1px solid var(--border);'
            + 'border-radius:12px;max-width:720px;width:92vw;max-height:88vh;display:flex;'
            + 'flex-direction:column;box-shadow:var(--shadow-md);">'
            + '<div style="display:flex;align-items:center;justify-content:space-between;padding:14px 16px;'
            + 'border-bottom:1px solid var(--border);gap:10px;">'
            + '<span style="font-weight:600;font-size:0.9rem;min-width:0;overflow:hidden;'
            + 'text-overflow:ellipsis;white-space:nowrap;">' + esc(t('kbmatrix.edit_title'))
            + ' – ' + esc(doc.title || '') + '</span>'
            + '<button id="wi-de-x" type="button" title="' + esc(t('common.close')) + '" '
            + 'style="background:none;border:none;color:var(--text-secondary);cursor:pointer;'
            + 'padding:2px 6px;flex:0 0 auto;">' + JarvisIcons.close() + '</button></div>'
            + '<div style="padding:14px 16px;overflow:auto;flex:1;">'
            + '<p class="desc" style="margin:0 0 10px;">' + esc(t('kbmatrix.edit_hint')) + '</p>'
            + (quelle ? '<p class="desc" style="margin:0 0 10px;word-break:break-all;">'
                        + esc(t('kbmatrix.col_source')) + ': ' + esc(quelle) + '</p>' : '')
            + '<label style="font-size:0.78rem;color:var(--text-secondary);">' + t('wissen.title_label') + '</label>'
            + '<input class="wi-input" id="wi-de-title" value="' + esc(doc.title || '') + '">'
            + '<label style="font-size:0.78rem;color:var(--text-secondary);display:block;margin-top:8px;">'
            + t('wissen.summary_label') + '</label>'
            + '<textarea class="wi-input" id="wi-de-summary" rows="4" style="resize:vertical;">'
            + esc(doc.summary || '') + '</textarea>'
            + '<label style="font-size:0.78rem;color:var(--text-secondary);display:block;margin-top:8px;">'
            + t('wissen.facts_edit_label', { n: facts.length }) + '</label>'
            + '<textarea class="wi-input" id="wi-de-facts" rows="' + Math.min(10, Math.max(3, facts.length + 1))
            + '" style="resize:vertical;">' + esc(facts.join('\n')) + '</textarea>'
            + qaHtml
            + '<label style="font-size:0.78rem;color:var(--text-secondary);">' + t('wissen.target_groups') + '</label>'
            + '<div class="wi-groups" id="wi-de-groups" style="margin:6px 0 10px;">'
            + groupBoxes('doc', opts.gruppen || []) + '</div>'
            + '<div id="wi-de-status" style="margin:8px 0 0;font-size:0.8rem;"></div>'
            + '</div>'
            + '<div style="padding:12px 16px;border-top:1px solid var(--border);">'
            + '<button class="sec-btn primary" id="wi-de-save" type="button">' + esc(t('ext.update_btn')) + '</button>'
            + entfBtn
            + ' <button class="sec-btn" id="wi-de-close" type="button">' + esc(t('common.close')) + '</button>'
            + '</div></div>';
        document.body.appendChild(modal);

        function zu() { modal.remove(); }
        function melde(msg, farbe) {
            var st = $('wi-de-status');
            if (!st) return;
            st.style.color = 'var(--' + (farbe || 'danger') + ')';
            st.textContent = msg;
        }
        // Waehrend eines Laufs beide Knoepfe sperren: ein zweiter Klick in den
        // ersten hinein schriebe dasselbe Dokument zweimal bzw. loeschte etwas,
        // das gerade aktualisiert wird.
        function sperren(an) {
            ['wi-de-save', 'wi-de-remove'].forEach(function (id) {
                var b = $(id); if (b) b.disabled = an;
            });
        }

        $('wi-de-x').addEventListener('click', zu);
        $('wi-de-close').addEventListener('click', zu);
        // Zeilen-Loeschen im Q&A-Audit (Paar komplett entfernen)
        modal.querySelectorAll('.wi-qa-del').forEach(function (btn) {
            btn.addEventListener('click', function () { btn.closest('.wi-qa-row').remove(); });
        });

        $('wi-de-save').addEventListener('click', function () {
            var groups = checkedGroups('doc');
            if (!groups.length) { melde(t('wissen.pick_target')); return; }
            // `!= null` statt Falsyness: ein absichtlich GELEERTES Feld muss
            // auch leer gespeichert werden, sonst bleibt der alte Text stehen.
            var patch = {};
            var titel = ($('wi-de-title') || {}).value;
            if (titel != null) patch.title = titel.trim();
            var summary = ($('wi-de-summary') || {}).value;
            if (summary != null) patch.summary = summary.trim();
            var factsRaw = ($('wi-de-facts') || {}).value;
            if (factsRaw != null) {
                patch.facts = factsRaw.split('\n')
                    .map(function (l) { return l.replace(/^\s*[-*•]\s*/, '').trim(); })
                    .filter(function (l) { return l.length > 0; });
            }
            /* ⚠ Den Container AUSDRUECKLICH pruefen, nicht `collectQa(null)`
               rufen: ohne Argument faellt collectQa auf die Entwurfs-Pruefung
               (#wi-rev-qa) zurueck – bei einem Dokument OHNE Q&A laese die
               Maske damit die Felder eines fremden, offenen Entwurfs.
               Und existiert der Container, wird auch eine LEERE Liste
               geschickt: wer alle Paare weggeworfen hat, erwartet, dass sie
               weg sind – `null` liesse sie stehen. */
            var qaEl = $('wi-de-qa');
            if (qaEl) patch.qa_pairs = collectQa(qaEl) || [];
            // Ein uebernommenes Dokument ohne jeden Inhalt wuerde eine LEERE
            // .md-Datei in die Wissensdatenbank schreiben – sie waere in der
            // Suche ein Treffer ohne Aussage. Lieber hier abweisen.
            var freigegeben = (patch.qa_pairs || []).filter(function (p) { return p.approved; });
            if (!(patch.facts || []).length && !freigegeben.length) {
                melde(t('kbmatrix.need_content')); return;
            }
            sperren(true);
            melde(t('ext.saving'), 'text-secondary');
            fetch('/api/knowledge/pending/' + encodeURIComponent(doc.id), {
                method: 'PATCH', headers: authH({ 'Content-Type': 'application/json' }),
                body: JSON.stringify(patch),
            }).then(function (r) {
                // Erst pruefen, DANN uebernehmen (Code-Review 2026-10-07): ein
                // gescheitertes PATCH liess die Uebernahme die .md aus dem ALTEN
                // Datensatz schreiben, und die Maske schloss als Erfolg.
                return r.json().catch(function () { return {}; }).then(function (d) {
                    if (!r.ok || !d || d.ok !== true) throw new Error((d && d.error) || httpHint(r.status));
                });
            }).then(function () {
                return fetch('/api/knowledge/pending/' + encodeURIComponent(doc.id) + '/approve', {
                    method: 'POST', headers: authH({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ groups: groups }),
                });
            }).then(function (r) {
                return r.json().catch(function () { return { error: httpHint(r.status) }; });
            }).then(function (d) {
                if (!d || d.error) { melde('✗ ' + ((d && d.error) || t('kbmatrix.update_failed'))); return; }
                zu();
                // Die Datei wurde neu geschrieben und die Zuordnung gesetzt –
                // beide Listen der Seite ziehen nach. Die Zuordnungskarte
                // braucht kein Zuruecksetzen: KbGroups.getMap() cached nicht,
                // die Massenzuordnung holt sie bei jedem Oeffnen neu.
                loadFiles();
                loadPending();
            }).catch(function (e) {
                melde('✗ ' + t('kbmatrix.update_failed') + (e && e.message ? ' (' + e.message + ')' : ''));
            }).then(function () { sperren(false); });
        });

        var rm = $('wi-de-remove');
        if (rm) rm.addEventListener('click', function () {
            if (!confirm(t('ext.delete_approved_confirm'))) return;
            sperren(true);
            Promise.resolve(opts.entfernen()).then(function () {
                zu();
                loadFiles();
                loadPending();
            }).catch(function (e) {
                melde('✗ ' + t('kbmatrix.delete_failed') + (e && e.message ? ' (' + e.message + ')' : ''));
            }).then(function () { sperren(false); });
        });
    }

    function loadPending() {
        fetch('/api/wissen/pending', { headers: authH() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var box = $('wi-pending-list');
                var items = (d && d.pending) || [];
                var bulk = $('wi-drafts-bulk');
                if (bulk) bulk.style.display = items.length ? 'flex' : 'none';
                // Vorschau VOR dem Leeren der Liste heimholen: liegt sie gerade
                // unter einer Zeile, wuerde `innerHTML = ''` sie mitreissen.
                _revPlace(null);
                if (!items.length) {
                    box.innerHTML = '<div class="wi-empty">' + t('wissen.no_drafts') + '</div>';
                    hideBulkApprove();
                    return;
                }
                box.innerHTML = '';
                var zeilen = {};   // Entwurfs-Id -> Zeile (fuer das Wiedereinsetzen unten)
                items.forEach(function (it) {
                    var row = document.createElement('div');
                    row.className = 'wi-item';
                    var cb = document.createElement('input');
                    cb.type = 'checkbox'; cb.className = 'wi-draft-cb'; cb.value = it.id;
                    // Die Markierung dient jetzt BEIDEM (uebernehmen + loeschen),
                    // der alte Titel „Zum Löschen markieren" waere irrefuehrend.
                    cb.title = t('wissen.mark_select');
                    cb.style.cssText = 'flex-shrink:0;width:16px;height:16px;margin:0 2px 0 0;cursor:pointer;';
                    var nm = document.createElement('span'); nm.className = 'nm'; nm.textContent = it.title || t('wissen.untitled');
                    var rev = document.createElement('button'); rev.className = 'sec-btn small'; rev.textContent = t('wissen.review_btn');
                    rev.addEventListener('click', function () {
                        // Umschalter: derselbe Knopf schliesst die eigene Vorschau
                        // wieder. Ohne das ist „Prüfen" eine Einbahnstrasse – die
                        // Vorschau liess sich nur ueber Freigeben/Verwerfen loswerden.
                        var offen = (_revId === it.id) && !!($('wi-ext-review') || {}).innerHTML;
                        // Kein Sprung: die Vorschau wird DIREKT UNTER diese Zeile gesetzt.
                        // Kam sie vom Heimatplatz (oberhalb der Liste), schrumpft der
                        // Bereich darueber und die Zeile rutscht nach oben weg –
                        // deshalb die eigene Verschiebung messen und ausgleichen.
                        var vorher = row.getBoundingClientRect().top;
                        if (offen) clearReview(); else showReview(it, row);
                        var delta = row.getBoundingClientRect().top - vorher;
                        if (delta) window.scrollBy(0, delta);
                    });
                    var del = document.createElement('button'); del.className = 'sec-btn small danger'; JarvisIcons.setTrash(del);
                    del.addEventListener('click', function () { deletePending(it.id, false); });
                    row.appendChild(cb); row.appendChild(nm); row.appendChild(rev); row.appendChild(del);
                    box.appendChild(row);
                    zeilen[it.id] = row;
                });
                // Offene Vorschau wieder unter ihren Entwurf setzen (der Neuaufbau
                // der Liste hat sie eben heimgeholt). Ist der Entwurf verschwunden,
                // bleibt sie am Heimatplatz stehen.
                if (_revId && zeilen[_revId]) _revPlace(zeilen[_revId]);
                bindDraftsBulk(box);
            })
            .catch(function () {});
    }

    // Mehrfachauswahl zum Uebernehmen ODER Verwerfen mehrerer Entwuerfe
    // (analog Einstellungen-Extraktor).
    function bindDraftsBulk(box) {
        var boxes = Array.prototype.slice.call(box.querySelectorAll('.wi-draft-cb'));
        var selAll = $('wi-drafts-selall'), delSel = $('wi-drafts-delsel'),
            appSel = $('wi-drafts-appsel');
        function marked() {
            return boxes.filter(function (b) { return b.checked; }).map(function (b) { return b.value; });
        }
        function sync() {
            var checked = marked().length;
            var alle = boxes.length > 0 && checked === boxes.length;
            if (delSel) {
                delSel.disabled = checked === 0;
                delSel.textContent = checked ? t('wissen.delete_selected') + ' (' + checked + ')' : t('wissen.delete_selected');
            }
            if (appSel) {
                // Sind ALLE markiert, heisst der Knopf auch „Alle übernehmen" –
                // sonst „Auswahl übernehmen (n)".
                appSel.disabled = checked === 0;
                appSel.textContent = alle
                    ? t('wissen.approve_all') + ' (' + checked + ')'
                    : (checked ? t('wissen.approve_selected') + ' (' + checked + ')' : t('wissen.approve_selected'));
            }
            if (selAll) selAll.textContent = alle ? t('wissen.unselect_all') : t('wissen.select_all');
        }
        boxes.forEach(function (b) {
            b.onchange = function () { sync(); hideBulkApprove(); };
        });
        if (selAll) selAll.onclick = function () {
            var all = boxes.length && boxes.every(function (b) { return b.checked; });
            boxes.forEach(function (b) { b.checked = !all; });
            hideBulkApprove(); sync();
        };
        if (delSel) delSel.onclick = function () {
            var ids = marked();
            if (ids.length) bulkDeleteDrafts(ids);
        };
        if (appSel) appSel.onclick = function () {
            var ids = marked();
            if (ids.length) showBulkApprove(ids);
        };
        sync();
    }

    // ── Sammel-Uebernahme ───────────────────────────────────────────────
    // Uebernommen wird der Entwurf, WIE ER IST – Titel und Q&A-Paare koennen
    // nur einzeln unter „Prüfen" korrigiert werden. Die Zielgruppen fehlen
    // aber zwingend, deshalb dieser kleine Auswahlkasten als Zwischenschritt
    // (er ist gleichzeitig die Bestaetigung; ein zusaetzliches confirm() waere
    // eine Klick-Schikane).
    function hideBulkApprove() {
        var p = $('wi-drafts-approve');
        if (p) p.style.display = 'none';
    }

    function showBulkApprove(ids) {
        var p = $('wi-drafts-approve');
        if (!p) return;
        var st = $('wi-drafts-appstatus'); if (st) st.textContent = '';
        var ttl = $('wi-drafts-apptitle');
        if (ttl) ttl.textContent = t('wissen.approve_selected_title', { n: ids.length });
        $('wi-drafts-groups').innerHTML = groupBoxes('bulk', checkedGroups('up'));
        p.style.display = '';
        $('wi-drafts-appcancel').onclick = hideBulkApprove;
        $('wi-drafts-appgo').onclick = function () { bulkApproveDrafts(ids); };
    }

    function bulkApproveDrafts(ids) {
        var st = $('wi-drafts-appstatus');
        var groups = checkedGroups('bulk');
        if (!groups.length) { st.style.color = 'var(--danger)'; st.textContent = t('wissen.pick_target'); return; }
        var go = $('wi-drafts-appgo');
        go.disabled = true;
        st.style.color = 'var(--text-secondary)';
        st.textContent = t('wissen.approve_selected_run', { n: ids.length });
        var ok = 0, fehler = 0;
        // Bewusst SEQUENZIELL: jede Uebernahme schreibt Dateien und indiziert;
        // parallel wuerden sich die Laeufe auf dem Server gegenseitig behindern.
        var chain = Promise.resolve();
        ids.forEach(function (id) {
            chain = chain.then(function () {
                return fetch('/api/wissen/pending/' + encodeURIComponent(id) + '/approve', {
                    method: 'POST', headers: authH({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ groups: groups })
                }).then(function (r) { return r.json(); })
                  .then(function (d) { if (d && d.error) fehler++; else ok++; })
                  .catch(function () { fehler++; });
            });
        });
        chain.then(function () {
            go.disabled = false;
            hideBulkApprove();
            var s = $('wi-ext-status');
            if (s) {
                s.style.color = fehler ? 'var(--warning)' : 'var(--success)';
                s.textContent = fehler
                    ? t('wissen.approve_selected_part', { n: ok, f: fehler })
                    : t('wissen.approve_selected_ok', { n: ok });
            }
            clearReview(); loadPending(); loadFiles();
        });
    }

    function bulkDeleteDrafts(ids) {
        if (!window.confirm(t('wissen.delete_selected_confirm', { n: ids.length }))) return;
        var chain = Promise.resolve();
        ids.forEach(function (id) {
            chain = chain.then(function () {
                return fetch('/api/wissen/pending/' + encodeURIComponent(id), { method: 'DELETE', headers: authH() }).catch(function () {});
            });
        });
        chain.then(function () { hideBulkApprove(); clearReview(); loadPending(); });
    }

    // ── Eingabe-Tabs: URL / Datei / Confluence ──────────────────────────
    var _extTab = 'url';
    function switchExtTab(tab) {
        _extTab = tab;
        [['url', 'wi-tab-url', 'wi-panel-url'], ['file', 'wi-tab-file', 'wi-panel-file'],
         ['cf', 'wi-tab-cf', 'wi-panel-cf']].forEach(function (x) {
            var btn = $(x[1]), pan = $(x[2]);
            if (btn) btn.classList.toggle('active', tab === x[0]);
            if (pan) pan.style.display = (tab === x[0]) ? '' : 'none';
        });
        // Der Abbrechen-Button gehoert zum Confluence-Bulk – bei Tab-Wechsel weg,
        // sofern kein Job laeuft.
        if (!_cfJobId) { var xc = $('wi-extract-cancel'); if (xc) xc.style.display = 'none'; }
        if (tab === 'file') updateDropState();
    }

    // Universeller "Extrahieren"-Button: löst je nach aktivem Tab die passende Aktion aus.
    function doExtract() {
        // Ohne gewaehlte Wissensgruppe kein Start (Button ist ohnehin gesperrt).
        if (checkedGroups('up').length === 0) { setProgress(t('wissen.pick_group'), 'var(--danger)'); return; }
        if (_extTab === 'cf') { importCf(); return; }
        if (_extTab === 'file') {
            if (canUpload()) $('wi-file-input').click(); else updateDropState();
            return;
        }
        extractUrl();
    }

    // ── Dynamische Confluence-Einbindung ────────────────────────────────
    // BAUM STATT PULLDOWN (Vorgabe 2026-09-27): Bereiche und ihre
    // Unterbereiche (der Seitenbaum des Bereichs) werden markiert und mit
    // EINEM Klick als EIN gespeicherter Eintrag uebernommen - auch bei
    // mehreren markierten Bereichen. Gespeicherte Eintraege sind editierbar.
    // Abgeglichen wird vom Cron-Auftrag "Wissensabgleich"
    // (backend/confluence_abgleich.py); die Liste ist global.
    //
    // Bedienung, wie vom Betreiber festgelegt:
    //   [+]  klappt auf UND markiert den Eintrag samt allem darunter
    //   [-]  klappt zu UND nimmt die Markierung darunter zurueck
    //        (der Eintrag selbst bleibt, wie er ist)
    //   Name klappt nur auf/zu - Haken bleiben unveraendert
    //   Haken: nur dieser eine Eintrag, jederzeit einzeln
    var _cfbAktiv = false;       // Skill installiert+aktiv UND konfiguriert
    var _cfbBereiche = null;     // gespeicherte Eintraege (null = noch nicht geladen)
    var _cfbSpacesFertig = false; // Bereichsliste des Extraktors durchgelaufen?
    // ⚠ EIGENER MERKER STATT NUR DES ARGUMENTS von cfbAddKnopf(): waehrend des
    // Speicherns kann der Benutzer ein Kaestchen umstellen, und dessen
    // change-Handler ruft cfbAddKnopf() OHNE Argument - der Knopf waere wieder
    // frei und ein zweiter Aufruf moeglich, mitten im ersten.
    var _cfbLaeuft = false;
    var _cfbEdit = null;         // Kennung des Eintrags, der gerade bearbeitet wird
    var _cfbEditLauf = 0;        // zaehlt jeden Wechsel des Editors (siehe cfbBearbeiten)
    var _cfbNeu = false;         // Editor fuer die Neuanlage offen ("Neuer Bereich")
    var _cfbBaumFuer = null;     // Bereichsliste, fuer die der Baum gezeichnet ist
    var _cfbImporte = {};        // Bereich -> juengster Import (ISO), vom Server

    function cfbStatus(msg, warn) {
        var el = $('wi-cfb-status');
        if (!el) return;
        el.textContent = msg || '';
        el.style.color = warn ? 'var(--danger)' : '';
    }

    // Wird von loadCfSpaces gerufen, sobald die Bereichsliste steht ODER
    // endgueltig gescheitert ist. Beides muss ankommen: ohne den Fehlerfall
    // stuende im Baum fuer immer "Lade...".
    function cfbSpacesFertig() { _cfbSpacesFertig = true; cfbRender(); }

    function cfbLaden() {
        fetch('/api/wissen/confluence/bindung', { headers: authH() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || !d.ok) { _cfbAktiv = false; cfbRender(); return; }
                _cfbAktiv = !!d.aktiv;
                _cfbBereiche = d.bereiche || [];
                _cfbImporte = d.importe || {};
                cfbRender();
            })
            // Faellt der Abruf aus, bleibt der Container weg: lieber nichts
            // anbieten als eine Pflegeflaeche, die nicht speichern kann.
            .catch(function () { _cfbAktiv = false; cfbRender(); });
    }

    // ⚠ DER DESTILLAT-CONTAINER HOLT DIE BEREICHSLISTE NICHT SELBST. Sein Knopf
    // "Als neue Confluence-Seite" braucht dieselbe Liste und dieselbe
    // Aktiv-Aussage wie die Einbindung hier; zwei Abrufe liefen beim naechsten
    // Feinschliff auseinander, und dann boete der eine Container Bereiche an,
    // die der andere nicht kennt (gleiche Regel wie zwischen Extraktor und
    // Einbindung). Gemeldet wird AUCH der ausgeschaltete Zustand – sonst bliebe
    // der Knopf dort stehen, wenn der Skill abgeschaltet wird.
    function cfDestMelden() {
        var d = window.WissenDestillat;
        if (d && d.confluence) d.confluence(_cfbAktiv, _cfSpaces);
    }

    function cfbRender() {
        cfDestMelden();
        var sec = $('wi-sec-cfbind');
        if (!sec) return;
        // Sichtbar GENAU nach der Vorgabe: Skill installiert+aktiv UND
        // konfiguriert. Alles andere (keine Bereiche sichtbar, Abruf noch
        // unterwegs) wird IM Container gesagt - ein Container, der je nach
        // Datenlage auftaucht und verschwindet, ist unerklaerbar.
        if (!_cfbAktiv) { sec.style.display = 'none'; return; }
        sec.style.display = '';
        cfbRenderGroups();
        cfbRenderBaum();
        cfbImpBereiche();
        cfbRenderList();
        cfbEditorZeigen();
    }

    // Datum des letzten Imports ins Wissen (Vorgabe 2026-09-28): in Klammern
    // HINTER [+]/[-], bei einer Zeile ohne Zeichen hinter dem Namen - also
    // immer als letztes Element der Zeile. Die volle Zeit steht im Tooltip.
    function cfbImpHtml(iso) {
        if (!iso) return '';
        var d = new Date(iso);
        if (isNaN(d.getTime())) return '';
        var tag = d.toLocaleDateString(undefined, { day: '2-digit', month: '2-digit', year: 'numeric' });
        var voll = d.toLocaleString(undefined, { day: '2-digit', month: '2-digit', year: 'numeric',
                                                 hour: '2-digit', minute: '2-digit' });
        return ' <span class="wi-cfb-imp" title="' + esc(t('wissen.cfb_imp_hint', { t: voll })) + '">('
            + esc(tag) + ')</span>';
    }

    // ⚠ DIE BEREICHSZEILEN WERDEN NICHT NEU GEZEICHNET (cfbRenderBaum zeichnet
    // nur einmal, sonst gingen Haken verloren) - das Datum wird deshalb an der
    // bestehenden Zeile ersetzt, sobald der Bindungs-Abruf neue Zeiten bringt.
    function cfbImpBereiche() {
        var tree = $('wi-cfb-tree');
        if (!tree) return;
        tree.querySelectorAll('li.wi-cfb-sp').forEach(function (li) {
            var n = cfbKind(li, 'wi-cf-node');
            if (!n) return;
            var alt = cfbKind(n, 'wi-cfb-imp');
            if (alt) alt.remove();
            var html = cfbImpHtml(_cfbImporte[li.getAttribute('data-key')]);
            if (html) n.insertAdjacentHTML('beforeend', html);
        });
    }

    // ⚠ DER EDITOR IST NUR BEI "Neuer Bereich" ODER "Bearbeiten" OFFEN
    // (Vorgabe 2026-09-28). Die Statuszeile ist EIN Element, das wandert:
    // offen steht sie am Ende des Editors (am Knopf, der sie ausloest), zu
    // unter "Neuer Bereich" - sonst waeren "gespeichert"/"entfernt" nach dem
    // Schliessen unsichtbar. Zwei Statuszeilen liefen auseinander.
    function cfbEditorZeigen() {
        var ed = $('wi-cfb-editor'), st = $('wi-cfb-status');
        var zeile = $('wi-cfb-newrow'), neu = $('wi-cfb-new'), ab = $('wi-cfb-cancel');
        var offen = !!(_cfbEdit || _cfbNeu);
        if (ed) ed.style.display = offen ? '' : 'none';
        // Bei der Neuanlage steht der Editor direkt darunter - ein zweiter
        // Klick haette nichts zu tun. Beim Bearbeiten bleibt er: der Weg zur
        // Neuanlage fuehrt dann ueber ihn (das Bearbeiten endet damit).
        if (neu) neu.style.display = _cfbNeu ? 'none' : '';
        // "Abbrechen" ist jetzt der Weg, den Editor wieder zu schliessen -
        // auch bei der Neuanlage, nicht nur beim Bearbeiten.
        if (ab) ab.style.display = offen ? '' : 'none';
        if (st && ed && zeile) {
            if (offen && st.parentNode !== ed) ed.appendChild(st);
            if (!offen && st.parentNode !== zeile) zeile.appendChild(st);
        }
    }

    function cfbNeu() {
        cfbEditModus(null);
        cfbBaumLeeren();
        cfbStatus('');
        _cfbNeu = true;
        cfbEditorZeigen();
    }

    // ⚠ MINDESTENS EINE WISSENSGRUPPE IST PFLICHT (Vorgabe 2026-09-22).
    // ⚠ NUR EINMAL ZEICHNEN: cfbRender() laeuft nach JEDEM Speichern und
    // Loeschen; ein Neuaufbau verwuerfe die Haekchen - und wer mehrere
    // Eintraege derselben Gruppe zuordnet, muesste sie jedes Mal neu setzen.
    function cfbRenderGroups() {
        var box = $('wi-cfb-groups');
        if (!box) return;
        if (box.querySelector('.wi-grp-cfb')) return;
        box.innerHTML = groupBoxes('cfb');
    }

    // ── Der Baum ──
    // Direkte Kinder eines <li> (Register: querySelector am Elternteil sucht
    // im ganzen Teilbaum, nicht bei den Geschwistern).
    function cfbKind(li, klasse) {
        for (var i = 0; li && i < li.children.length; i++) {
            if (li.children[i].classList.contains(klasse)) return li.children[i];
        }
        return null;
    }
    function cfbCb(li) {
        var n = cfbKind(li, 'wi-cf-node');
        return n ? n.querySelector('.wi-cfb-cb') : null;
    }
    function cfbTog(li) {
        var n = cfbKind(li, 'wi-cf-node');
        return n ? n.querySelector('.wi-cfb-tog') : null;
    }

    // ⚠ DER BAUM WIRD NUR NEU GEZEICHNET, WENN SICH DIE BEREICHSLISTE AENDERT.
    // Die Haken leben im DOM; ein Neuaufbau nach jedem Speichern verwuerfe eine
    // Markierung, an der jemand gerade arbeitet.
    function cfbRenderBaum() {
        var tree = $('wi-cfb-tree');
        if (!tree) return;
        if (!_cfbSpacesFertig && !_cfSpaces) {
            tree.innerHTML = '<div class="wi-empty">' + esc(t('common.loading')) + '</div>';
            cfbAddKnopf();
            return;
        }
        if (!(_cfSpaces || []).length) {
            tree.innerHTML = '<div class="wi-empty">' + esc(t('wissen.cfb_nospaces')) + '</div>';
            _cfbBaumFuer = _cfSpaces;
            cfbAddKnopf();
            return;
        }
        if (_cfbBaumFuer === _cfSpaces && tree.querySelector('.wi-cfb-sp')) { cfbAddKnopf(); return; }
        _cfbBaumFuer = _cfSpaces;
        tree.innerHTML = '<ul>' + _cfSpaces.map(function (sp) {
            return '<li role="treeitem" class="wi-cfb-sp" aria-expanded="false" data-key="' + esc(sp.key) + '"'
                + ' data-such="' + esc(((sp.name || '') + ' ' + sp.key).toLowerCase()) + '">'
                + '<div class="wi-cf-node">'
                + '<input type="checkbox" class="wi-cfb-cb" data-art="space" aria-label="' + esc(sp.name || sp.key) + '">'
                + '<span class="wi-cfb-nm" role="button" tabindex="0" title="' + esc(t('wissen.cfb_name_hint')) + '">'
                + esc(sp.name || sp.key) + ' <span class="wi-cfb-key">(' + esc(sp.key) + ')</span></span>'
                // Ob ein Bereich Unterbereiche hat, weiss erst der Abruf seines
                // Seitenbaums - 500 Abrufe vorab waeren teurer als das Zeichen.
                // Stellt sich der Bereich als leer heraus, verschwindet es.
                + cfbTogHtml(false)
                + '</div></li>';
        }).join('') + '</ul>';
        cfbFilter();
        cfbMarken();
    }

    function cfbTogHtml(offen) {
        return '<button type="button" class="wi-cfb-tog" aria-expanded="' + (offen ? 'true' : 'false') + '"'
            + ' title="' + esc(t(offen ? 'wissen.cfb_tog_close' : 'wissen.cfb_tog_open')) + '">'
            + (offen ? '[-]' : '[+]') + '</button>';
    }

    function cfbSeiteHtml(n) {
        var hatKids = n.kids.length > 0;
        return '<li role="treeitem" class="wi-cfb-pg" data-id="' + esc(n.id) + '"'
            + (hatKids ? ' aria-expanded="false"' : '') + '>'
            + '<div class="wi-cf-node">'
            + '<input type="checkbox" class="wi-cfb-cb" data-art="page" value="' + esc(n.id) + '" aria-label="' + esc(n.title) + '">'
            + '<span class="wi-cfb-nm"' + (hatKids ? ' role="button" tabindex="0" title="' + esc(t('wissen.cfb_name_hint')) + '"' : '') + '>'
            + esc(n.title) + '</span>'
            + (hatKids ? ' <span class="wi-cf-cnt">(' + cfZahl(n) + ')</span>' + cfbTogHtml(false) : '')
            + cfbImpHtml(n.importiert)
            + '</div>'
            + (hatKids ? '<ul class="wi-cf-kids" role="group">' + n.kids.map(cfbSeiteHtml).join('') + '</ul>' : '')
            + '</li>';
    }

    // Seitenbaum eines Bereichs EINMAL holen (Promise je Bereich gemerkt).
    function cfbSeitenLaden(li) {
        if (li._cfbLaden) return li._cfbLaden;
        var key = li.getAttribute('data-key');
        li._cfbLaden = fetch('/api/wissen/confluence/pages?space=' + encodeURIComponent(key), { headers: authH() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || !d.ok) throw new Error((d && d.error) || 'x');
                var roots = cfBaum(d.pages || []);
                var alt = cfbKind(li, 'wi-cf-kids');
                if (alt) alt.remove();
                var ul = document.createElement('ul');
                ul.className = 'wi-cf-kids';
                ul.setAttribute('role', 'group');
                if (!roots.length) {
                    // Kein Unterbereich: das [+] verschwindet, der Bereich
                    // bleibt markierbar (dann zaehlt seine Startseite).
                    var tg = cfbTog(li); if (tg) tg.remove();
                    li.removeAttribute('aria-expanded');
                    ul.innerHTML = '<li class="wi-cfb-leer">' + esc(t('wissen.cfb_nopages')) + '</li>';
                } else {
                    ul.innerHTML = roots.map(cfbSeiteHtml).join('');
                }
                li.appendChild(ul);
                li._cfbGeladen = true;
                li._cfbZahl = (d.pages || []).length;
                return li;
            })
            .catch(function (e) {
                li._cfbLaden = null;   // naechster Klick darf es erneut versuchen
                cfbStatus('⚠ ' + t('wissen.cfb_load_err') + ' (' + key + ')', true);
                throw e;
            });
        return li._cfbLaden;
    }

    function cfbOeffnen(li, auf) {
        var ul = cfbKind(li, 'wi-cf-kids');
        if (ul) ul.classList.toggle('open', auf);
        var tg = cfbTog(li);
        if (tg) {
            tg.setAttribute('aria-expanded', auf ? 'true' : 'false');
            tg.textContent = auf ? '[-]' : '[+]';
            tg.title = t(auf ? 'wissen.cfb_tog_close' : 'wissen.cfb_tog_open');
        }
        if (li.hasAttribute('aria-expanded')) li.setAttribute('aria-expanded', auf ? 'true' : 'false');
    }

    function cfbUnten(li, an) {
        var ul = cfbKind(li, 'wi-cf-kids');
        if (ul) ul.querySelectorAll('.wi-cfb-cb').forEach(function (x) { x.checked = an; });
    }

    // [+]: aufklappen UND markieren (samt allem darunter). [-]: zuklappen UND
    // die Markierung darunter zuruecknehmen; der Eintrag selbst bleibt.
    function cfbPlusMinus(li) {
        var tg = cfbTog(li);
        var offen = tg && tg.getAttribute('aria-expanded') === 'true';
        if (offen) {
            cfbOeffnen(li, false);
            cfbUnten(li, false);
            cfbMarken();
            return Promise.resolve();
        }
        var fertig = li.classList.contains('wi-cfb-sp') && !li._cfbGeladen
            ? cfbSeitenLaden(li) : Promise.resolve(li);
        return fertig.then(function () {
            var cb = cfbCb(li); if (cb) cb.checked = true;
            cfbUnten(li, true);
            cfbOeffnen(li, true);
            cfbMarken();
        }, function () { cfbMarken(); });
    }

    // Name: nur auf-/zuklappen - die Haken bleiben, wie sie sind.
    function cfbNameKlick(li) {
        var ul = cfbKind(li, 'wi-cf-kids');
        var offen = !!(ul && ul.classList.contains('open'));
        if (offen) { cfbOeffnen(li, false); return Promise.resolve(); }
        var fertig = li.classList.contains('wi-cfb-sp') && !li._cfbGeladen
            ? cfbSeitenLaden(li) : Promise.resolve(li);
        return fertig.then(function () { cfbOeffnen(li, true); }, function () {});
    }

    // Anzeige nachziehen: halber Haken an einem Eintrag, der selbst NICHT
    // markiert ist, aber Markiertes darunter hat; Zaehler; Knopf.
    function cfbMarken() {
        var tree = $('wi-cfb-tree');
        if (!tree) return;
        tree.querySelectorAll('li[role="treeitem"]').forEach(function (li) {
            var ul = cfbKind(li, 'wi-cf-kids'), cb = cfbCb(li);
            if (!cb) return;
            cb.indeterminate = !cb.checked && !!(ul && ul.querySelector('.wi-cfb-cb:checked'));
        });
        var n = cfbAuswahl().length;
        var m = $('wi-cfb-marked');
        if (m) m.textContent = n ? t('wissen.cfb_marked', { n: n }) : '';
        cfbAddKnopf();
    }

    function cfbFilter() {
        var tree = $('wi-cfb-tree');
        if (!tree) return;
        var q = ((($('wi-cfb-such') || {}).value) || '').trim().toLowerCase();
        tree.querySelectorAll('li.wi-cfb-sp').forEach(function (li) {
            // Ein markierter Bereich bleibt sichtbar - eine Markierung, die
            // hinter einem Suchbegriff verschwindet, uebernimmt man blind.
            var cb = cfbCb(li);
            var drin = !q || li.getAttribute('data-such').indexOf(q) !== -1
                || (cb && (cb.checked || cb.indeterminate));
            li.style.display = drin ? '' : 'none';
        });
    }

    // Ist der Zweig unter `li` komplett markiert (der Knoten eingeschlossen)?
    function cfbKomplett(li) {
        var cb = cfbCb(li), ul = cfbKind(li, 'wi-cf-kids');
        if (!cb || !cb.checked || !ul) return false;
        var alle = ul.querySelectorAll('.wi-cfb-cb');
        return alle.length > 0 && ul.querySelectorAll('.wi-cfb-cb:checked').length === alle.length;
    }

    // Die Markierung als Auswahl fuer den Server. Je Bereich:
    //   start  - der Bereich selbst ist markiert
    //   ganz   - Bereich UND alle Unterbereiche markiert (neue Seiten kommen mit)
    //   seiten - markierte Seiten
    //   zweige - Seiten MIT Unterseiten, deren Zweig komplett markiert ist
    //            (ein Blatt ist kein Zweig - siehe confluence_bindung.py)
    function cfbAuswahl() {
        var tree = $('wi-cfb-tree');
        if (!tree) return [];
        var aus = [];
        tree.querySelectorAll('li.wi-cfb-sp').forEach(function (li) {
            var key = li.getAttribute('data-key');
            var cb = cfbCb(li);
            if (!li._cfbGeladen) {
                // Nie aufgeklappt: beim Bearbeiten gilt die gespeicherte
                // Auswahl weiter (sie ist nicht sichtbar, aber nicht verworfen).
                if (li._cfbVorher && cb && cb.checked === !!li._cfbVorher.start) {
                    aus.push(li._cfbVorher);
                } else if (cb && cb.checked) {
                    aus.push({ key: key, start: true, ganz: false, seiten: [], zweige: [] });
                }
                return;
            }
            var seiten = [], zweige = [];
            li.querySelectorAll('li.wi-cfb-pg').forEach(function (pg) {
                var pcb = cfbCb(pg);
                if (!pcb || !pcb.checked) return;
                var id = pg.getAttribute('data-id');
                seiten.push(id);
                if (cfbKind(pg, 'wi-cf-kids') && cfbKomplett(pg)) zweige.push(id);
            });
            var start = !!(cb && cb.checked);
            if (!start && !seiten.length) return;
            aus.push({ key: key, start: start, ganz: cfbKomplett(li) && (li._cfbZahl || 0) > 0,
                       seiten: seiten, zweige: zweige });
        });
        return aus;
    }

    // Alle Haken weg, alles zu, Bearbeiten beendet.
    function cfbBaumLeeren() {
        var tree = $('wi-cfb-tree');
        if (!tree) return;
        tree.querySelectorAll('.wi-cfb-cb').forEach(function (x) { x.checked = false; x.indeterminate = false; });
        tree.querySelectorAll('li[role="treeitem"]').forEach(function (li) { cfbOeffnen(li, false); li._cfbVorher = null; });
        cfbFilter();
        cfbMarken();
    }

    // Der Knopf folgt der Auswahl. GESPERRT MIT GRUND statt verborgen
    // (Projektregel) - und der Grund muss der RICHTIGE sein: ein Knopf, der
    // "markieren" sagt, obwohl markiert ist und die Wissensgruppe fehlt,
    // schickt an die falsche Stelle.
    function cfbAddKnopf(laeuft) {
        var btn = $('wi-cfb-add');
        if (!btn) return;
        var n = cfbAuswahl().length;
        var grp = checkedGroups('cfb').length;
        btn.disabled = !!laeuft || _cfbLaeuft || !n || !grp;
        btn.title = !btn.disabled ? ''
            : (!n ? t('wissen.cfb_add_hint') : t('wissen.cfb_need_group'));
    }

    // Tags aus dem Eingabefeld. Getrennt wird an Komma, Semikolon und
    // Leerraum - Confluence-Tags enthalten keines davon. Die Normierung
    // (klein, ohne fuehrendes #) macht der SERVER (`_tags_pruefen`); hier nur
    // zerlegen, damit es EINE Fassung der Regel gibt.
    function cfbTagsLesen() {
        var el = $('wi-cfb-tags');
        return String((el && el.value) || '').split(/[\s,;]+/).filter(function (x) { return !!x; });
    }

    function cfbZusammenfassung(b) {
        return (b.auswahl || []).map(function (a) {
            var teile = [];
            if (a.ganz) teile.push(t('wissen.cfb_sum_ganz'));
            else {
                if (a.start) teile.push(t('wissen.cfb_sum_start'));
                if ((a.seiten || []).length) teile.push(t('wissen.cfb_sum_seiten', { n: a.seiten.length }));
                if ((a.zweige || []).length) teile.push(t('wissen.cfb_sum_zweige'));
            }
            return a.key + ': ' + teile.join(', ');
        }).join(' · ');
    }

    // Ergebnis des letzten Abgleichs - ohne diese Zeile nimmt der Container
    // einen Eintrag an, und niemand sieht, ob je etwas ankommt.
    function cfbSyncZeile(b) {
        var s = b.abgleich;
        if (!s) return '<div class="wi-cfb-sync">' + esc(t('wissen.cfb_sync_none')) + '</div>';
        var zeit = '';
        try { zeit = new Date(s.zeit).toLocaleString(undefined, { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }); }
        catch (e) { zeit = s.zeit || ''; }
        var warn = !!s.fehler;
        // Nichts geholt UND ein Fehler: dann ist "Abgeglichen: 0 Seiten" eine
        // Falschaussage - es wurde gar nicht abgeglichen. Nur der Grund steht da.
        if (warn && !s.seiten) {
            return '<div class="wi-cfb-sync warn">' + esc(t('wissen.cfb_sync_err', { e: s.fehler })) + '</div>';
        }
        var txt = t('wissen.cfb_sync_ok', { t: zeit, n: (s.seiten || 0) - (s.offen || 0) });
        if (s.offen) txt += ' · ' + t('wissen.cfb_sync_offen', { n: s.offen });
        if (warn) txt += ' · ' + t('wissen.cfb_sync_err', { e: s.fehler });
        return '<div class="wi-cfb-sync' + (warn ? ' warn' : '') + '">' + esc(txt) + '</div>';
    }

    // ── Ort des Editors ──
    // Beim BEARBEITEN steht der Editor (Gruppen, Tags, Baum, Knoepfe) IN der
    // Box des Eintrags, nicht ueber allen Eintraegen - sonst ist nicht zu
    // sehen, welcher Eintrag gerade bearbeitet wird (Vorgabe 2026-09-27). Die
    // Neuanlage bleibt oberhalb der Liste. Der Editor wird VERSCHOBEN, nie neu
    // gebaut: Haken, geladene Seitenbaeume und Zuhoerer bleiben erhalten.
    // ⚠ Vor jedem Neuzeichnen der Liste zurueckholen - innerHTML loeschte ihn
    // sonst mit (und mit ihm den Baum).
    function cfbEditorParken() {
        var ed = $('wi-cfb-editor'), box = $('wi-cfb-list');
        if (!ed || !box) return;
        var alt = ed.parentNode && ed.parentNode.classList && ed.parentNode.classList.contains('wi-item')
            ? ed.parentNode : null;
        if (alt) alt.classList.remove('wi-cfb-editing');
        if (ed.nextElementSibling !== box) box.parentNode.insertBefore(ed, box);
    }

    // Liefert false, wenn der bearbeitete Eintrag nicht (mehr) in der Liste steht.
    function cfbEditorPlatzieren() {
        var ed = $('wi-cfb-editor'), box = $('wi-cfb-list');
        if (!ed || !box) return true;
        if (!_cfbEdit) { cfbEditorParken(); return true; }
        var item = null;
        box.querySelectorAll('.wi-item').forEach(function (x) {
            if (x.getAttribute('data-id') === _cfbEdit) item = x;
        });
        if (!item) { cfbEditorParken(); return false; }
        if (ed.parentNode !== item) {
            cfbEditorParken();
            item.appendChild(ed);
        }
        item.classList.add('wi-cfb-editing');
        return true;
    }

    function cfbRenderList() {
        var box = $('wi-cfb-list');
        if (!box) return;
        cfbEditorParken();
        cfbRenderEintraege(box);
        // Eintrag weg (anderswo geloescht): Bearbeiten endet, der Editor
        // steht wieder fuer die Neuanlage da.
        if (!cfbEditorPlatzieren()) { cfbEditModus(null); cfbBaumLeeren(); }
    }

    // Bearbeiten + Muelleimer - oder, fuer eine Einbindung fremder
    // Wissensgruppen, ein Hinweis statt der Knoepfe. ⚠ `=== false`, NICHT
    // Falsyness: ein aelteres Backend ohne das Feld behaelt die Knoepfe (der
    // Server weist ohnehin mit 403 ab). Die Entscheidung trifft der SERVER mit
    // derselben Regel wie am 403 (`_cfb_darf`) - der Client kennt nur seinen
    // Bereich und koennte sie nicht nachbauen.
    function cfbAktionen(b) {
        if (b.darf_aendern === false) {
            return '<span class="wi-cfb-fremd" title="' + esc(t('wissen.cfb_foreign_hint')) + '">'
                + esc(t('wissen.cfb_foreign')) + '</span>';
        }
        return '<button type="button" class="sec-btn small wi-cfb-edit" title="'
            + esc(t('wissen.cfb_edit_hint')) + '">' + esc(t('wissen.cfb_edit')) + '</button>'
            + '<button type="button" class="sec-btn small danger wi-cfb-del" title="'
            + esc(t('wissen.cfb_del')) + '">' + JarvisIcons.trash() + '</button>';
    }

    function cfbRenderEintraege(box) {
        var arr = _cfbBereiche || [];
        if (!arr.length) {
            box.innerHTML = '<div class="wi-empty">' + esc(t('wissen.cfb_none')) + '</div>';
            return;
        }
        box.innerHTML = arr.map(function (b) {
            // ⚠ DIE NAMEN KOMMEN VOM SERVER (`gruppen_info`), nicht aus
            // SCOPE.groups: der Client kennt nur SEINEN Bereich. Fehlt das Feld
            // ganz (aelteres Backend), stehen die Kennungen da.
            var ids = b.gruppen || [];
            var gi = b.gruppen_info;
            if (!gi) gi = ids.map(function (id) { return { id: id, name: id, color: '' }; });
            var chips = gi.map(function (g) {
                return '<span class="wi-chip" style="border-color:' + esc(g.color || 'var(--border)')
                    + ';font-size:0.7rem;">' + esc(g.name || g.id) + '</span>';
            }).join(' ');
            // Keine Zuordnung (Altbestand) bzw. eine geloeschte Gruppe: beides
            // wird BENANNT - ein Eintrag ohne Ziel wird nicht abgeglichen.
            if (!gi.length) {
                chips = '<span class="wi-cfb-nogrp" title="' + esc(t('wissen.cfb_nogroup_hint'))
                    + '">' + esc(t('wissen.cfb_nogroup')) + '</span>';
            } else if (gi.length < ids.length) {
                chips += ' <span class="wi-cfb-nogrp">'
                    + esc(t('wissen.cfb_grp_gone', { n: ids.length - gi.length })) + '</span>';
            }
            return '<div class="wi-item" data-id="' + esc(b.id) + '"'
                + ' data-label="' + esc(b.name || b.id) + '">'
                + '<div class="wi-fmeta">'
                + '<span class="nm">' + esc(b.name || b.id) + '</span>'
                + '<div class="wi-fpath wi-cfb-sum">' + esc(cfbZusammenfassung(b)) + '</div>'
                + ((b.tags || []).length
                    ? '<div class="wi-fpath wi-cfb-sum wi-cfb-tagsum">'
                      + esc(t('wissen.cfb_sum_tags', { t: b.tags.join(', ') })) + '</div>'
                    : '')
                + cfbSyncZeile(b)
                + '</div>'
                + chips
                + cfbAktionen(b)
                + '</div>';
        }).join('');
        box.querySelectorAll('.wi-cfb-del').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var row = btn.closest('.wi-item');
                cfbEntfernen(row.getAttribute('data-id'), row.getAttribute('data-label'));
            });
        });
        box.querySelectorAll('.wi-cfb-edit').forEach(function (btn) {
            btn.addEventListener('click', function () {
                cfbBearbeiten(btn.closest('.wi-item').getAttribute('data-id'));
            });
        });
    }

    // cfbEditModus(null) SCHLIESST den Editor (auch eine offene Neuanlage);
    // cfbNeu() oeffnet ihn danach ausdruecklich wieder.
    function cfbEditModus(b) {
        _cfbEdit = b ? b.id : null;
        _cfbEditLauf++;
        _cfbNeu = false;
        var add = $('wi-cfb-add'), note = $('wi-cfb-editnote');
        if (add) add.textContent = t(b ? 'wissen.cfb_save' : 'wissen.cfb_add');
        if (note) {
            note.style.display = b ? '' : 'none';
            note.textContent = b ? t('wissen.cfb_editing', { n: b.name || b.id }) : '';
        }
        // Die Tags gehoeren zum Eintrag: beim Bearbeiten seine, danach leer -
        // sonst truege der naechste NEUE Eintrag still den Filter des alten.
        var tg = $('wi-cfb-tags');
        if (tg) tg.value = b ? (b.tags || []).join(', ') : '';
        cfbEditorPlatzieren();
        cfbEditorZeigen();
    }

    // Einen gespeicherten Eintrag in den Baum laden: Haken und Gruppen so, wie
    // sie gespeichert sind; die betroffenen Bereiche stehen aufgeklappt da.
    function cfbBearbeiten(id) {
        var b = (_cfbBereiche || []).filter(function (x) { return x.id === id; })[0];
        var tree = $('wi-cfb-tree');
        if (!b || !tree) return;
        cfbBaumLeeren();
        cfbEditModus(b);
        // Wettlauf (Code-Review 2026-10-07): laedt der Seitenbaum von A langsam
        // und kommt danach "Bearbeiten" bei B (oder "Neuer Bereich"), setzte
        // As spaete Antwort ihre Haken in Bs Editor – Bs Einbindung uebernahm
        // beim Speichern fremde Seiten. Jede Antwort gilt nur fuer DEN
        // Editor-Lauf, der sie angefordert hat (auch A -> B -> A ist ein
        // neuer Lauf, die Kennung allein reichte nicht).
        var lauf = _cfbEditLauf;
        cfbStatus('');
        // Gruppen: nur die des eigenen Bereichs sind Kaestchen - fremde
        // Zuordnungen haelt der Server beim Speichern fest (PUT).
        var box = $('wi-cfb-groups');
        if (box) box.querySelectorAll('.wi-grp-cfb').forEach(function (x) {
            x.checked = (b.gruppen || []).indexOf(x.value) !== -1;
        });
        var warten = (b.auswahl || []).map(function (a) {
            var li = null;
            tree.querySelectorAll('li.wi-cfb-sp').forEach(function (x) {
                if (x.getAttribute('data-key') === a.key) li = x;
            });
            if (!li) return Promise.resolve();
            li._cfbVorher = a;
            var cb = cfbCb(li); if (cb) cb.checked = !!a.start;
            return cfbSeitenLaden(li).then(function () {
                if (lauf !== _cfbEditLauf) return;
                if (a.ganz) cfbUnten(li, true);
                var zw = {};
                (a.zweige || []).forEach(function (z) { zw[z] = true; });
                li.querySelectorAll('li.wi-cfb-pg').forEach(function (pg) {
                    var id2 = pg.getAttribute('data-id');
                    if ((a.seiten || []).indexOf(id2) !== -1) { var c = cfbCb(pg); if (c) c.checked = true; }
                    if (zw[id2]) cfbUnten(pg, true);
                });
                cfbOeffnen(li, true);
            }, function () { /* nicht ladbar: gespeicherte Auswahl bleibt (_cfbVorher) */ });
        });
        Promise.all(warten).then(function () {
            if (lauf !== _cfbEditLauf) return;
            cfbFilter(); cfbMarken();
        });
        cfbMarken();
    }

    // KNOPFDRUCK = Speichern (Vorgabe 2026-09-21: eine Auswahl ist kein Auftrag).
    function cfbAdd() {
        var auswahl = cfbAuswahl();
        var grp = checkedGroups('cfb');
        if (!auswahl.length) { cfbStatus('⚠ ' + t('wissen.cfb_add_hint'), true); return; }
        // Zweite Schranke neben dem gesperrten Knopf: das Kaestchen laesst sich
        // waehrend eines Laufs umstellen, und der Server weist es ohnehin ab -
        // aber der Benutzer soll den Grund HIER lesen, nicht als Serverfehler.
        if (!grp.length) { cfbStatus('⚠ ' + t('wissen.cfb_need_group'), true); return; }
        var edit = _cfbEdit;
        _cfbLaeuft = true;
        cfbAddKnopf(true);
        cfbStatus(t('common.loading'));
        fetch('/api/wissen/confluence/bindung' + (edit ? '/' + encodeURIComponent(edit) : ''), {
            method: edit ? 'PUT' : 'POST', headers: authH({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ auswahl: auswahl, groups: grp, tags: cfbTagsLesen() })
        }).then(function (r) { return r.json(); })
          .then(function (d) {
              _cfbLaeuft = false;
              if (!d || !d.ok) {
                  // Die Markierung BLEIBT stehen - wer sie korrigieren will,
                  // soll nicht von vorn anfangen.
                  cfbStatus('⚠ ' + ((d && d.error) || t('wissen.cfb_err')), true);
                  cfbAddKnopf();
                  return;
              }
              // Die Antwort des Servers gewinnt: er vergibt die Kennung und
              // kennt die Anzeigenamen der Bereiche.
              _cfbBereiche = d.bereiche || [];
              var nm = (d.bereich && d.bereich.name) || '';
              cfbStatus('✓ ' + t(edit ? 'wissen.cfb_saved' : 'wissen.cfb_added', { n: nm }));
              cfbEditModus(null);
              cfbBaumLeeren();
              cfbRender();
          })
          .catch(function () {
              _cfbLaeuft = false;
              cfbStatus('⚠ ' + t('wissen.cfb_err'), true);
              cfbAddKnopf();
          });
    }

    function cfbAbbrechen() {
        cfbEditModus(null);
        cfbBaumLeeren();
        cfbStatus('');
    }

    function cfbEntfernen(id, label) {
        if (!id) return;
        if (!window.confirm(t('wissen.cfb_del_ask', { n: label || id }))) return;
        fetch('/api/wissen/confluence/bindung/' + encodeURIComponent(id),
              { method: 'DELETE', headers: authH() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || !d.ok) { cfbStatus('⚠ ' + ((d && d.error) || t('wissen.cfb_err')), true); return; }
                _cfbBereiche = d.bereiche || [];
                // Wer den Eintrag loescht, den er gerade bearbeitet, bearbeitet
                // danach nichts mehr - sonst liefe "Speichern" in ein 404.
                if (_cfbEdit === id) { cfbEditModus(null); cfbBaumLeeren(); }
                cfbStatus('✓ ' + t('wissen.cfb_removed', { n: label || id }));
                cfbRender();
            })
            .catch(function () { cfbStatus('⚠ ' + t('wissen.cfb_err'), true); });
    }

    function cfbVerdrahten() {
        var tree = $('wi-cfb-tree');
        if (tree) {
            tree.addEventListener('click', function (ev) {
                var tg = ev.target.closest && ev.target.closest('.wi-cfb-tog');
                if (tg) { cfbPlusMinus(tg.closest('li')); return; }
                var nm = ev.target.closest && ev.target.closest('.wi-cfb-nm');
                if (nm && nm.getAttribute('role') === 'button') cfbNameKlick(nm.closest('li'));
            });
            tree.addEventListener('keydown', function (ev) {
                var nm = ev.target.closest && ev.target.closest('.wi-cfb-nm');
                if (nm && (ev.key === 'Enter' || ev.key === ' ')) { ev.preventDefault(); cfbNameKlick(nm.closest('li')); }
            });
            // Ein Haken wirkt NUR auf seinen Eintrag - nichts wird mitgezogen.
            tree.addEventListener('change', function (ev) {
                if (ev.target.classList && ev.target.classList.contains('wi-cfb-cb')) cfbMarken();
            });
        }
        var such = $('wi-cfb-such');
        if (such) such.addEventListener('input', cfbFilter);
        var btn = $('wi-cfb-add');
        if (btn) btn.addEventListener('click', function () { cfbAdd(); });
        var ab = $('wi-cfb-cancel');
        if (ab) ab.addEventListener('click', cfbAbbrechen);
        var nb = $('wi-cfb-new');
        if (nb) nb.addEventListener('click', cfbNeu);
        // Wissensgruppen-Pflicht: der Knopf folgt der Auswahl. DELEGIERT am
        // Container - die Kaestchen entstehen erst beim Zeichnen. Nur auf
        // `change` hoeren und NIE selbst umschalten (am AD-Picker bezahlt).
        var grp = $('wi-cfb-groups');
        if (grp) grp.addEventListener('change', function () { cfbAddKnopf(); });
    }

    // ── Confluence-Import (alle sichtbaren Bereiche) ────────────────────
    // Suchbare Bereichsauswahl (analog Einstellungen → Wissen → Confluence):
    // Freitext-Suche mit Dropdown, danach Seiten-Mehrfachauswahl.
    var _cfJobId = null, _cfPoll = null;
    var _cfSpaces = null, _selectedSpaceKey = '', _ddOpen = false, _ddIndex = -1, _ddList = [];

    // Laufenden Confluence-Job im Browser merken, damit der Fortschritt einen
    // Seitenrefresh ueberlebt (Server-Job laeuft weiter, nur die job_id ginge sonst verloren).
    var _CF_LS = 'jarvis_wissen_cf_job';
    function saveCfJob(jobId, total) {
        try { localStorage.setItem(_CF_LS, JSON.stringify({ jobId: jobId, total: total || 0 })); } catch (e) {}
    }
    function clearCfJob() { try { localStorage.removeItem(_CF_LS); } catch (e) {} }
    function loadCfJob() {
        try { var s = localStorage.getItem(_CF_LS); return s ? JSON.parse(s) : null; } catch (e) { return null; }
    }

    function loadCfSpaces(force) {
        var tabBtn = $('wi-tab-cf'), input = $('wi-cf-space-search');
        if (_cfSpaces && !force) { if (_ddOpen) renderCfSpaceDropdown(); return; }
        if (input) input.placeholder = t('common.loading');
        fetch('/api/wissen/confluence/spaces', { headers: authH() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                var spaces = (d && d.ok && d.configured) ? (d.spaces || []) : [];
                if (!spaces.length) {
                    _cfSpaces = [];
                    if (tabBtn) tabBtn.style.display = 'none';
                    if (_extTab === 'cf') switchExtTab('url');   // Tab entfaellt -> zurueck auf URL
                    cfbSpacesFertig();
                    return;
                }
                _cfSpaces = spaces;
                if (tabBtn) tabBtn.style.display = '';
                if (input) input.placeholder = t('wissen.cf_space_search') + ' (' + spaces.length + ')';
                if (_ddOpen) renderCfSpaceDropdown();
                // EINE Quelle fuer die Bereichsliste: der Einbindungs-Container
                // benutzt dieselbe wie der Extraktor. Zwei Abrufe liefen beim
                // naechsten Feinschliff auseinander - und dann boete das
                // Pulldown andere Bereiche an als der Import daneben.
                cfbSpacesFertig();
            })
            .catch(function () {
                if (tabBtn) tabBtn.style.display = 'none';
                if (_extTab === 'cf') switchExtTab('url');
                cfbSpacesFertig();
            });
    }

    function filteredSpaces() {
        if (!_cfSpaces) return [];
        var q = (($('wi-cf-space-search') || {}).value || '').trim().toLowerCase();
        if (!q) return _cfSpaces;
        return _cfSpaces.filter(function (s) {
            return (((s.name || '') + ' ' + (s.key || '')).toLowerCase().indexOf(q) !== -1);
        });
    }

    function onSpaceSearchInput() {
        _selectedSpaceKey = '';
        var wrap = $('wi-cf-page-wrap'), hint = $('wi-cf-hint');
        if (wrap) wrap.style.display = 'none';
        if (hint) hint.style.display = 'none';
        _ddIndex = -1;
        openSpaceDropdown();
    }

    function openSpaceDropdown() {
        _ddOpen = true;
        if (!_cfSpaces) { loadCfSpaces(false); return; }
        renderCfSpaceDropdown();
    }
    function closeSpaceDropdown() {
        _ddOpen = false;
        var dd = $('wi-cf-space-dd');
        if (dd) dd.style.display = 'none';
    }

    function renderCfSpaceDropdown() {
        var dd = $('wi-cf-space-dd');
        if (!dd) return;
        var list = filteredSpaces();
        var CAP = 200;
        var shown = list.slice(0, CAP);
        _ddList = shown;
        if (_ddIndex >= shown.length) _ddIndex = -1;
        if (!shown.length) {
            dd.innerHTML = '<div style="padding:8px 10px;color:var(--text-secondary);font-size:0.85rem;">' + esc(t('wissen.cf_no_hits')) + '</div>';
            dd.style.display = '';
            return;
        }
        dd.innerHTML = shown.map(function (s, i) {
            return '<div class="wi-cf-opt" data-key="' + esc(s.key) + '" data-i="' + i + '" '
                + 'style="padding:7px 10px;cursor:pointer;font-size:0.86rem;'
                + (i === _ddIndex ? 'background:rgba(var(--accent-rgb),0.18);' : '') + '">'
                + esc(s.name) + ' <span style="color:var(--text-secondary);">(' + esc(s.key) + ')</span></div>';
        }).join('')
        + (list.length > CAP ? '<div style="padding:6px 10px;color:var(--text-secondary);font-size:0.78rem;">… '
            + (list.length - CAP) + '</div>' : '');
        dd.style.display = '';
        dd.querySelectorAll('.wi-cf-opt').forEach(function (el) {
            el.addEventListener('mousedown', function (ev) {
                ev.preventDefault();   // verhindert blur vor der Auswahl
                selectSpace(el.getAttribute('data-key'));
            });
            el.addEventListener('mouseover', function () {
                _ddIndex = parseInt(el.getAttribute('data-i'), 10);
                highlightDd();
            });
        });
    }

    function highlightDd() {
        var dd = $('wi-cf-space-dd');
        if (!dd) return;
        dd.querySelectorAll('.wi-cf-opt').forEach(function (el) {
            var i = parseInt(el.getAttribute('data-i'), 10);
            el.style.background = (i === _ddIndex) ? 'rgba(var(--accent-rgb),0.18)' : '';
        });
    }

    function spaceSearchKey(e) {
        if (!_ddOpen && (e.key === 'ArrowDown' || e.key === 'ArrowUp')) { openSpaceDropdown(); return; }
        var n = (_ddList || []).length;
        if (e.key === 'ArrowDown') { e.preventDefault(); _ddIndex = Math.min(_ddIndex + 1, n - 1); highlightDd(); scrollDdIntoView(); }
        else if (e.key === 'ArrowUp') { e.preventDefault(); _ddIndex = Math.max(_ddIndex - 1, 0); highlightDd(); scrollDdIntoView(); }
        else if (e.key === 'Enter') { e.preventDefault(); var pick = (_ddList || [])[_ddIndex] || (_ddList || [])[0]; if (pick) selectSpace(pick.key); }
        else if (e.key === 'Escape') { closeSpaceDropdown(); }
    }
    function scrollDdIntoView() {
        var dd = $('wi-cf-space-dd');
        var el = dd && dd.querySelector('.wi-cf-opt[data-i="' + _ddIndex + '"]');
        if (el) el.scrollIntoView({ block: 'nearest' });
    }

    function selectSpace(key) {
        var sp = (_cfSpaces || []).filter(function (s) { return s.key === key; })[0];
        if (!sp) return;
        _selectedSpaceKey = key;
        var input = $('wi-cf-space-search');
        if (input) input.value = sp.name + ' (' + sp.key + ')';
        closeSpaceDropdown();
        loadCfPages(key);
    }

    // Seiten des Bereichs als aufklappbarer Baum (Vorgabe: Zweige eingeklappt).
    // Grundlage ist `parent` je Seite vom Server; eine Seite, deren Eltern-
    // seite nicht in der Liste steht (Kappung, fehlende Rechte), wird zur
    // Wurzel - sie darf nicht still aus der Auswahl fallen.
    var _cfPageCount = 0;

    function cfBaum(pages) {
        var byId = {}, roots = [];
        pages.forEach(function (p) {
            if (p && p.id != null) byId[String(p.id)] = { id: String(p.id), title: p.title || '',
                                                          importiert: p.importiert || '', kids: [] };
        });
        pages.forEach(function (p) {
            if (!p || p.id == null) return;
            var n = byId[String(p.id)], par = p.parent ? String(p.parent) : '';
            if (par && par !== n.id && byId[par]) byId[par].kids.push(n);
            else roots.push(n);
        });
        return roots;
    }

    function cfZahl(n) {
        var c = 0;
        n.kids.forEach(function (k) { c += 1 + cfZahl(k); });
        return c;
    }

    function cfKnotenHtml(n) {
        var hatKids = n.kids.length > 0;
        var tog = hatKids
            ? '<button type="button" class="wi-cf-tog" aria-expanded="false" title="'
              + esc(t('wissen.cf_toggle')) + '">▶</button>'
            : '<span class="wi-cf-tog-leer"></span>';
        return '<li role="treeitem"' + (hatKids ? ' aria-expanded="false"' : '') + '>'
            + '<div class="wi-cf-node">' + tog
            + '<label><input type="checkbox" class="wi-cf-cb" value="' + esc(n.id) + '">'
            + '<span>' + esc(n.title) + '</span>'
            + (hatKids ? ' <span class="wi-cf-cnt">(' + cfZahl(n) + ')</span>' : '')
            + '</label></div>'
            + (hatKids ? '<ul class="wi-cf-kids" role="group">' + n.kids.map(cfKnotenHtml).join('') + '</ul>' : '')
            + '</li>';
    }

    // Direkte Kind-Liste eines <li>. ⚠ NICHT per li.querySelector('.wi-cf-kids …'):
    // der Selektor wird gegen das ganze Dokument ausgewertet, und die
    // .wi-cf-kids-Liste UEBER dem li erfuellt ihn ebenfalls (Register).
    function cfKidsUl(li) {
        for (var i = 0; i < li.children.length; i++) {
            if (li.children[i].classList.contains('wi-cf-kids')) return li.children[i];
        }
        return null;
    }

    // Anzeige nachziehen: halber Haken an Eltern, die selbst NICHT gewaehlt
    // sind, aber gewaehlte Unterseiten haben; "Alles" und Zaehler.
    function cfMarken() {
        var tree = $('wi-cf-tree');
        if (!tree) return;
        tree.querySelectorAll('li[role="treeitem"]').forEach(function (li) {
            var ul = cfKidsUl(li);
            if (!ul) return;
            var cb = li.querySelector('.wi-cf-cb');   // erster Treffer = eigener Haken
            cb.indeterminate = !cb.checked && !!ul.querySelector('.wi-cf-cb:checked');
        });
        var alle = tree.querySelectorAll('.wi-cf-cb').length;
        var an = tree.querySelectorAll('.wi-cf-cb:checked').length;
        var all = $('wi-cf-all');
        if (all) { all.checked = alle > 0 && an === alle; all.indeterminate = an > 0 && an < alle; }
        var cnt = $('wi-cf-sel-cnt');
        if (cnt) cnt.textContent = t('wissen.cf_selected', { k: an, n: alle });
    }

    function cfBaumVerdrahten(tree) {
        if (tree._wiCfBound) return;
        tree._wiCfBound = true;
        tree.addEventListener('click', function (ev) {
            var tog = ev.target.closest && ev.target.closest('.wi-cf-tog');
            if (!tog) return;
            var li = tog.closest('li');
            var ul = li && cfKidsUl(li);
            if (!ul) return;
            var auf = !ul.classList.contains('open');
            ul.classList.toggle('open', auf);
            tog.setAttribute('aria-expanded', auf ? 'true' : 'false');
            li.setAttribute('aria-expanded', auf ? 'true' : 'false');
        });
        tree.addEventListener('change', function (ev) {
            var cb = ev.target;
            if (cb.id === 'wi-cf-all') {
                tree.querySelectorAll('.wi-cf-cb').forEach(function (x) { x.checked = cb.checked; });
            } else if (cb.classList && cb.classList.contains('wi-cf-cb')) {
                // Uebergeordneter Haken setzt/entfernt alle Untergeordneten mit
                var ul = cfKidsUl(cb.closest('li'));
                if (ul) ul.querySelectorAll('.wi-cf-cb').forEach(function (x) { x.checked = cb.checked; });
            } else return;
            cfMarken();
        });
    }

    function loadCfPages(space) {
        var wrap = $('wi-cf-page-wrap'), hint = $('wi-cf-hint'), tree = $('wi-cf-tree'), st = $('wi-cf-status');
        if (st) st.textContent = '';
        if (wrap) wrap.style.display = 'flex';
        if (hint) hint.style.display = 'none';
        _cfPageCount = 0;
        if (tree) { cfBaumVerdrahten(tree); tree.innerHTML = '<div class="wi-empty">' + esc(t('common.loading')) + '</div>'; }
        fetch('/api/wissen/confluence/pages?space=' + encodeURIComponent(space), { headers: authH() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!tree) return;
                // Antwort zu einem inzwischen abgewaehlten Bereich verwerfen
                if (_selectedSpaceKey !== space) return;
                if (!d || !d.ok) { tree.innerHTML = '<div class="wi-empty">' + esc((d && d.error) || t('common.error')) + '</div>'; return; }
                var pages = d.pages || [];
                _cfPageCount = pages.length;
                if (!pages.length) { tree.innerHTML = '<div class="wi-empty">' + esc(t('wissen.cf_no_pages')) + '</div>'; return; }
                tree.innerHTML = '<div class="wi-cf-node wi-cf-all"><span class="wi-cf-tog-leer"></span>'
                    + '<label><input type="checkbox" id="wi-cf-all">'
                    + '<span>' + esc(t('wissen.cf_all', { n: pages.length })) + '</span></label>'
                    + ' <span class="wi-cf-cnt" id="wi-cf-sel-cnt"></span></div>'
                    + '<ul>' + cfBaum(pages).map(cfKnotenHtml).join('') + '</ul>';
                cfMarken();
                if (hint) hint.style.display = 'block';
            })
            .catch(function () { if (tree) tree.innerHTML = '<div class="wi-empty">' + esc(t('common.error')) + '</div>'; });
    }

    function importCf() {
        var tree = $('wi-cf-tree');
        var picked = tree ? Array.prototype.slice.call(tree.querySelectorAll('.wi-cf-cb:checked'))
            .map(function (c) { return c.value; }).filter(Boolean) : [];
        var st = $('wi-cf-status');
        if (!picked.length) { if (st) { st.style.color = 'var(--danger)'; st.textContent = t('wissen.cf_pick'); } return; }
        var space = _selectedSpaceKey || '';
        var body, bulk;
        // Alles angehakt = ganzer Bereich (wie frueher der Eintrag „Alles")
        if (_cfPageCount && picked.length === _cfPageCount) { body = { space: space }; bulk = true; }
        else if (picked.length > 1) { body = { page_ids: picked }; bulk = true; }
        else { body = { page_id: picked[0] }; bulk = false; }
        // Der Haken „Fragen & Antworten generieren (KI)" gilt laut Oberflaeche fuer
        // ALLE drei Eingabearten – wurde beim Confluence-Import aber nie mitgesendet,
        // sodass immer Fragen entstanden. 0 heisst ausdruecklich "keine Fragen".
        body.qa_count = qaWish();
        var jobId = _cfJobId = 'wcf_' + Date.now() + '_' + Math.random().toString(36).slice(2, 8);
        body.job_id = jobId;
        var btn = $('wi-extract-btn'), cancel = $('wi-extract-cancel');
        if (btn) btn.disabled = true;
        if (st) st.textContent = '';                 // Auswahl-Hinweis loeschen
        setProgress(t('wissen.cf_starting'), null, true);   // Fortschritt in der Aktionsreihe
        fetch('/api/wissen/extract/confluence', { method: 'POST', headers: authH({ 'Content-Type': 'application/json' }), body: JSON.stringify(body) })
            .then(function (r) { return r.json().then(function (j) { return { status: r.status, j: j }; }); })
            .then(function (res) {
                var j = res.j || {};
                if (res.status === 499) { setProgress(t('wissen.cf_cancelled')); if (btn) btn.disabled = false; _cfJobId = null; updateActionState(); return; }
                if (res.status >= 400) {
                    setProgress('✗ ' + (j.error || t('common.error')), 'var(--danger)');
                    if (btn) btn.disabled = false; _cfJobId = null; updateActionState(); return;
                }
                if (bulk) {
                    if (cancel) cancel.style.display = '';
                    watchCf(jobId, j.total || 0);
                } else {
                    _cfJobId = null;
                    setProgress('');
                    updateActionState();
                    showReview(j); loadPending();
                    $('wi-ext-review').scrollIntoView({ behavior: 'smooth' });
                }
            })
            .catch(function () { setProgress(t('wissen.cf_failed'), 'var(--danger)'); if (btn) btn.disabled = false; _cfJobId = null; updateActionState(); });
    }

    // Bulk-Fortschritt pollen und Statuszeile mit Countdown stehen lassen.
    function watchCf(jobId, total, started) {
        if (!jobId) return;
        clearInterval(_cfPoll);
        started = started || Date.now();
        saveCfJob(jobId, total);   // fuer Wiederaufnahme nach Refresh
        var cancel = $('wi-extract-cancel');
        function tick() {
            fetch('/api/wissen/extract/progress?job_id=' + encodeURIComponent(jobId), { headers: authH() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    d = d || {};
                    var done = d.done || 0, running = !!d.running;
                    if (d.total) { total = d.total; saveCfJob(jobId, total); }
                    if (_cfJobId !== jobId) { clearInterval(_cfPoll); _cfPoll = null; return; }
                    if (running) {
                        var remaining = Math.max(0, total - done);
                        var secs = Math.round((Date.now() - started) / 1000);
                        setProgress(t('wissen.cf_progress', { r: remaining, n: total, s: secs }), null, true);
                        loadPending();
                        return;
                    }
                    clearInterval(_cfPoll); _cfPoll = null; _cfJobId = null; clearCfJob();
                    if (cancel) cancel.style.display = 'none';
                    updateActionState();
                    loadPending();
                    if (done < total) setProgress(t('wissen.cf_stopped', { done: done, n: total }), 'var(--warning)');
                    else setProgress(t('wissen.cf_done', { n: total }), 'var(--success)');
                })
                .catch(function () { /* Netzfehler -> naechster Tick */ });
        }
        tick();
        _cfPoll = setInterval(tick, 2000);
    }

    // Nach Seitenrefresh: gemerkten Confluence-Job wiederfinden und Polling erneut starten.
    function resumeCf() {
        var saved = loadCfJob();
        if (!saved || !saved.jobId) return;
        // Serverseitig pruefen, ob der Job noch laeuft (sonst Altlast entfernen).
        fetch('/api/wissen/extract/progress?job_id=' + encodeURIComponent(saved.jobId), { headers: authH() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                d = d || {};
                if (!d.running) { clearCfJob(); return; }   // fertig/unbekannt -> nichts wiederherstellen
                _cfJobId = saved.jobId;
                var cancel = $('wi-extract-cancel'); if (cancel) cancel.style.display = '';
                updateActionState();
                watchCf(saved.jobId, d.total || saved.total || 0);
            })
            .catch(function () { /* Netzfehler -> nichts tun, Job bleibt gemerkt */ });
    }

    function abortCf() {
        var jid = _cfJobId; _cfJobId = null; clearCfJob();
        clearInterval(_cfPoll); _cfPoll = null;
        var cancel = $('wi-extract-cancel');
        if (cancel) cancel.style.display = 'none';
        updateActionState();
        if (!jid) return;
        fetch('/api/wissen/extract/cancel', { method: 'POST', headers: authH({ 'Content-Type': 'application/json' }), body: JSON.stringify({ job_id: jid }) })
            .then(function () { setProgress(t('wissen.cf_cancelled')); })
            .catch(function () {});
    }

    // Zentraler Abbruch: je nach laufender Aktion Confluence-Job ODER Datei-/URL-Analyse.
    function doCancel() {
        if (_cfJobId) { abortCf(); return; }
        if (_uploadAbort) {
            try { _uploadAbort.abort(); } catch (e) {}
            if (_uploadJobId) {   // server-seitigen Upload-Job zusaetzlich gezielt stoppen
                fetch('/api/wissen/extract/cancel', {
                    method: 'POST', headers: authH({ 'Content-Type': 'application/json' }),
                    body: JSON.stringify({ job_id: _uploadJobId })
                }).catch(function () {});
            }
        }
    }

    // ── Verdrahtung ─────────────────────────────────────────────────────
    document.addEventListener('DOMContentLoaded', function () {
        $('wi-login-btn').addEventListener('click', doLogin);
        ['wi-user', 'wi-pass', 'wi-totp'].forEach(function (id) {
            $(id).addEventListener('keydown', function (e) { if (e.key === 'Enter') doLogin(); });
        });
        $('wi-logout').addEventListener('click', logout);

        var drop = $('wi-drop'), fin = $('wi-file-input');
        drop.addEventListener('click', function () {
            if (!canUpload()) { updateDropState(); return; }   // gesperrt: Hinweis statt Dateidialog
            fin.click();
        });
        fin.addEventListener('change', function () { uploadFiles(fin.files); fin.value = ''; });
        ['dragover', 'dragleave', 'drop'].forEach(function (ev) {
            drop.addEventListener(ev, function (e) {
                e.preventDefault();
                drop.classList.toggle('drag', ev === 'dragover' && canUpload());
                if (ev === 'drop' && e.dataTransfer) {
                    if (!canUpload()) { updateDropState(); return; }
                    uploadFiles(e.dataTransfer.files);
                }
            });
        });
        // Unterordner im eigenen Bereich anlegen/umbenennen
        var fNew = $('wi-folder-new'), fRen = $('wi-folder-rename'), fSel = $('wi-folder');
        var fMov = $('wi-folder-move');
        if (fNew) fNew.addEventListener('click', createSubfolder);
        if (fRen) fRen.addEventListener('click', renameSubfolder);
        if (fMov) fMov.addEventListener('click', moveSubfolder);
        /* Der Stift kommt aus der EINEN Quelle - und zwar HIER, nicht als
           woertliches SVG im Markup: eine abgetippte Zeichenkette laeuft beim
           naechsten Feinschliff an icons.js auseinander, und niemand sieht es.
           Einmalig in der Verdrahtung, NICHT in `updateFolderBtnState()` - die
           laeuft bei jedem Ordnerwechsel und fasst nur `disabled` an. */
        if (fRen) JarvisIcons.setPencil(fRen);
        if (fSel) fSel.addEventListener('change', updateFolderBtnState);

        // Gruppen-Auswahl schaltet die Ablage frei/gesperrt (Checkboxen kommen per JS)
        $('wi-upload-groups').addEventListener('change', function () {
            updateFolderOptions();   // Ordner-Angebot an die gewaehlten Gruppen anpassen
            updateDropState();
            updateActionState();     // "Extrahieren" frei/gesperrt je nach Gruppenwahl
        });

        // Einklappbare Container (Zustand pro Browser gemerkt, analog Einstellungen).
        // Der Pfeil steht fest im Markup (eigener Span, damit applyLang ihn nicht wegwischt).
        ['wi-sec-matrix', 'wi-sec-groups', 'wi-sec-upload', 'wi-sec-destillat',
         'wi-sec-cfbind', 'wi-sec-files', 'wi-sec-gedaechtnis'].forEach(function (id) {
            var sec = $(id); if (!sec) return;
            var h = sec.querySelector('h2'); if (!h) return;
            var tog = h.querySelector('.wi-sec-tog'); if (!tog) return;
            var key = 'jarvis_wissen_sec_' + id;
            function apply(collapsed, silent) {
                sec.classList.toggle('collapsed', collapsed);
                tog.textContent = collapsed ? '▶' : '▼';
                if (!silent) { try { localStorage.setItem(key, collapsed ? '1' : '0'); } catch (e) {} }
            }
            var saved = null; try { saved = localStorage.getItem(key); } catch (e) {}
            apply(saved === '1', true);
            h.addEventListener('click', function () { apply(!sec.classList.contains('collapsed')); });
        });

        var exBtn = $('wi-extract-btn'); if (exBtn) exBtn.addEventListener('click', doExtract);
        var exCancel = $('wi-extract-cancel'); if (exCancel) exCancel.addEventListener('click', doCancel);
        $('wi-ext-url').addEventListener('keydown', function (e) { if (e.key === 'Enter') doExtract(); });

        // Eingabe-Tabs (URL / Datei / Confluence)
        var tU = $('wi-tab-url'); if (tU) tU.addEventListener('click', function () { switchExtTab('url'); });
        var tF = $('wi-tab-file'); if (tF) tF.addEventListener('click', function () { switchExtTab('file'); });
        var tC = $('wi-tab-cf'); if (tC) tC.addEventListener('click', function () { switchExtTab('cf'); });

        // Confluence-Import (alle sichtbaren Bereiche) – suchbare Bereichsauswahl
        var cfSearch = $('wi-cf-space-search');
        if (cfSearch) {
            cfSearch.addEventListener('input', onSpaceSearchInput);
            cfSearch.addEventListener('focus', openSpaceDropdown);
            cfSearch.addEventListener('keydown', spaceSearchKey);
            cfSearch.addEventListener('blur', function () { setTimeout(closeSpaceDropdown, 150); });
        }
        // Dynamische Confluence-Einbindung: Baum, Suchfeld, Knoepfe.
        // Markieren gibt den Knopf nur FREI - gespeichert wird erst auf
        // Knopfdruck (Vorgabe 2026-09-21, Begruendung an cfbAdd).
        cfbVerdrahten();

        var cfRefresh = $('wi-cf-refresh'); if (cfRefresh) cfRefresh.addEventListener('click', function () { loadCfSpaces(true); });

        // Massenzuordnung: Tabellen-Overlay öffnen (nur für globale Wissens-Editoren sichtbar)
        var mBtn = $('wi-matrix-btn');
        if (mBtn) mBtn.addEventListener('click', function () { if (window.KbMatrix) window.KbMatrix.open(); });

        if (window.applyLang) window.applyLang();
        loadScope();
        resumeCf();   // laufenden Confluence-Import nach Refresh wiederaufnehmen
    });

    // Schmale Schnittstelle nach aussen. Das Destillat-Modul legt seinen
    // Entwurf ueber den VORHANDENEN Pending-Weg ab und muss die Liste darunter
    // nachziehen – ohne das sucht der Benutzer seinen frischen Entwurf dort
    // vergeblich und haelt die Uebernahme fuer fehlgeschlagen.
    // `cfBaum` wandert mit hinaus, damit der Destillat-Container die
    // Seitenhierarchie mit DERSELBEN Regel bildet wie der Baum hier – eine
    // zweite Fassung liefe beim naechsten Feinschliff auseinander, und dann
    // haengte dieselbe Seite je nach Container an einer anderen Elternseite.
    // `openDocEdit` wandert mit hinaus, weil die Massenzuordnung
    // (kbmatrix.js) sie ruft: dort steht die Spalte, von der aus ein bereits
    // uebernommenes Dokument bearbeitet wird. Die MASKE gehoert hierher – sie
    // braucht SCOPE.groups, groupBoxes/checkedGroups, qaRowHtml, collectQa
    // und die Listen der Seite; in kbmatrix.js waere jedes davon eine zweite
    // Fassung. Das LOESCHEN bleibt umgekehrt dort (opts.entfernen), weil die
    // Muelleimer-Spalte es schon kann.
    window.WissenPortal = { reloadPending: function () { loadPending(); },
                            cfBaum: cfBaum,
                            openDocEdit: openDocEdit };
})();
