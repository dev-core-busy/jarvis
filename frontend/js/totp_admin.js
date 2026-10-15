/* ═══════════════════════════════════════════════════════════════════
   Einstellungen -> Sicherheit -> Zwei-Faktor-Anmeldung zuruecksetzen (Admin)

   Wer seinen zweiten Faktor verloren hat, kam frueher nie wieder hinein:
   /api/auth/totp/disable setzt eine Anmeldung voraus, die Anmeldung den Code.
   Hier schaltet ein Administrator die 2FA eines ANDEREN Kontos ab
   (POST /api/admin/totp/reset) – bestaetigt mit dem EIGENEN Kennwort.

   Bestaetigung als Zeile im Eintrag statt window.confirm: es braucht ohnehin
   ein Kennwortfeld, und das Ergebnis steht direkt am Knopf. Ein Fehler bleibt
   stehen (verschwindet nicht von selbst), ein Erfolg laedt die Liste neu.

   Dazu (BSI M3) der Anmeldeschutz: Schalter "2FA-Pflicht fuer Administratoren"
   und die Konten, die gerade nach Fehlversuchen gesperrt sind (aufhebbar).

   Aufruf: app.js ruft TotpAdmin.onShow() beim Oeffnen des Sicherheits-Reiters.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    function token() { return (window.JarvisSitzung && window.JarvisSitzung.token()) || ''; }
    function T(key, def) {
        try { var s = window.t ? window.t(key) : ''; if (s && s !== key) return s; } catch (e) {}
        return def;
    }
    function el(tag, attrs, text) {
        var e = document.createElement(tag);
        Object.keys(attrs || {}).forEach(function (k) { e.setAttribute(k, attrs[k]); });
        if (text != null) e.textContent = text;
        return e;
    }

    function liste() { return document.getElementById('sec-totp-list'); }

    function hinweis(box, key, def) {
        box.textContent = '';
        box.appendChild(el('p', { 'class': 'kb-hint' }, T(key, def)));
    }

    function load() {
        var box = liste();
        if (!box) return;
        fetch('/api/admin/totp/users', { headers: { 'Authorization': 'Bearer ' + token() } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d || !Array.isArray(d.users)) {
                    hinweis(box, 'security.totp_load_failed', 'Die Liste konnte nicht geladen werden.');
                    return;
                }
                render(d.users);
            })
            .catch(function () { hinweis(box, 'security.totp_load_failed', 'Die Liste konnte nicht geladen werden.'); });
    }

    function render(users) {
        var box = liste();
        if (!box) return;
        box.textContent = '';
        if (!users.length) {
            hinweis(box, 'security.totp_none', 'Kein Konto hat die Zwei-Faktor-Anmeldung eingeschaltet.');
            return;
        }
        users.forEach(function (u) { box.appendChild(zeile(u)); });
    }

    function zeile(u) {
        var row = el('div', { 'class': 'sec-totp-row', 'data-user': u.user,
            'style': 'border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:8px;' });
        var kopf = el('div', { 'style': 'display:flex;align-items:center;gap:10px;flex-wrap:wrap;' });
        kopf.appendChild(el('strong', { 'style': 'color:var(--text-primary);' }, u.display || u.user));
        kopf.appendChild(el('span', { 'style': 'flex:1;' }));
        if (u.self) {
            // Das eigene Konto geht nicht ueber diesen Weg (Server antwortet SELF)
            kopf.appendChild(el('span', { 'class': 'kb-hint', 'style': 'margin:0;' },
                T('security.totp_self', 'Eigenes Konto – unter „Konto“ mit deinem Kennwort abschalten.')));
            row.appendChild(kopf);
            return row;
        }
        var knopf = el('button', { 'type': 'button', 'class': 'sec-btn small sec-totp-start' },
            T('security.totp_reset_btn', 'Zurücksetzen'));
        kopf.appendChild(knopf);
        row.appendChild(kopf);

        var form = el('div', { 'class': 'sec-totp-confirm', 'hidden': '',
            'style': 'margin-top:10px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;' });
        form.appendChild(el('span', { 'style': 'color:var(--text-secondary);font-size:0.85rem;flex-basis:100%;' },
            T('security.totp_confirm_text', 'Das Konto meldet sich danach nur noch mit Kennwort an und kann die Zwei-Faktor-Anmeldung neu einrichten. Zur Bestätigung dein eigenes Kennwort:')));
        var pw = el('input', { 'type': 'password', 'class': 'sec-totp-pw', 'autocomplete': 'current-password',
            'placeholder': T('security.totp_pw_ph', 'Dein Kennwort'),
            'style': 'flex:1 1 200px;min-width:0;padding:6px 10px;border-radius:6px;border:1px solid var(--border);background:var(--bg-secondary);color:var(--text-primary);' });
        var ok = el('button', { 'type': 'button', 'class': 'sec-btn small primary sec-totp-ok' },
            T('security.totp_confirm_btn', 'Zwei-Faktor-Anmeldung zurücksetzen'));
        var abbr = el('button', { 'type': 'button', 'class': 'sec-btn small sec-totp-cancel' },
            T('common.cancel', 'Abbrechen'));
        var meldung = el('div', { 'class': 'sec-totp-msg', 'role': 'status',
            'style': 'flex-basis:100%;font-size:0.85rem;color:var(--text-primary);' });
        form.appendChild(pw); form.appendChild(ok); form.appendChild(abbr); form.appendChild(meldung);
        row.appendChild(form);

        function zeigen(an) {
            if (an) { form.removeAttribute('hidden'); form.style.display = 'flex'; pw.value = ''; meldung.textContent = ''; pw.focus(); }
            else { form.setAttribute('hidden', ''); form.style.display = 'none'; pw.value = ''; }
            knopf.disabled = !!an;
        }
        form.style.display = 'none';
        knopf.addEventListener('click', function () { zeigen(true); });
        abbr.addEventListener('click', function () { zeigen(false); });
        pw.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); ok.click(); } });
        ok.addEventListener('click', function () {
            if (!pw.value) { meldung.textContent = T('security.totp_pw_needed', 'Bitte dein Kennwort eingeben.'); pw.focus(); return; }
            ok.disabled = true;
            meldung.textContent = '';
            fetch('/api/admin/totp/reset', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + token(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ user: u.user, password: pw.value })
            }).then(function (r) {
                return r.json().catch(function () { return {}; })
                    .then(function (d) { return { status: r.status, d: d || {} }; });
            }).then(function (res) {
                pw.value = '';
                ok.disabled = false;
                if (res.status === 200 && res.d.ok) { load(); return; }
                var text;
                if (res.status === 403 && res.d.error) text = T('security.totp_pw_wrong', 'Falsches Kennwort.');
                else if (res.status === 403) text = T('security.only_local', 'Keine Berechtigung – nur Administratoren.');
                else if (res.status === 404) text = T('security.totp_not_active', 'Für dieses Konto ist keine Zwei-Faktor-Anmeldung mehr eingeschaltet.');
                else text = res.d.detail || res.d.error || T('security.totp_failed', 'Zurücksetzen fehlgeschlagen.');
                meldung.textContent = text;   // bleibt stehen, bis der Admin handelt
            }).catch(function () {
                pw.value = '';
                ok.disabled = false;
                meldung.textContent = T('security.totp_failed', 'Zurücksetzen fehlgeschlagen.');
            });
        });
        return row;
    }

    // ── Anmeldeschutz (BSI M3): 2FA-Pflicht fuer Admins + Konto-Sperren ──
    // GET/POST /api/admin/anmeldeschutz, POST /api/admin/anmeldeschutz/aufheben.
    // Ergebnis/Fehler steht am Bedienelement und verschwindet nicht von selbst.

    function fuellen(text, werte) {
        return String(text).replace(/\{(\w+)\}/g, function (m, k) {
            return Object.prototype.hasOwnProperty.call(werte, k) ? werte[k] : m;
        });
    }

    function schutzLaden() {
        var cb = document.getElementById('sec-admin-2fa-pflicht');
        var box = document.getElementById('sec-anm-sperren');
        if (!cb && !box) return;
        fetch('/api/admin/anmeldeschutz', { headers: { 'Authorization': 'Bearer ' + token() } })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d || !d.ok) {
                    if (box) hinweis(box, 'security.totp_load_failed', 'Die Liste konnte nicht geladen werden.');
                    return;
                }
                var h = document.getElementById('sec-anm-hint');
                if (h) h.textContent = fuellen(T('security.anmeldeschutz_hint',
                    'Nach {max} falschen Anmeldeversuchen innerhalb von {fenster} Minuten ist ein Konto {sperre} Minuten lang für die Anmeldung gesperrt – unabhängig davon, von welchem Gerät aus probiert wird. Die Sperre läuft von selbst ab.'),
                    { max: d.konto_max, fenster: d.konto_fenster_min, sperre: d.konto_sperre_min });
                if (cb) cb.checked = !!d.admin_2fa_pflicht;
                sperrenZeigen(Array.isArray(d.sperren) ? d.sperren : []);
            })
            .catch(function () { if (box) hinweis(box, 'security.totp_load_failed', 'Die Liste konnte nicht geladen werden.'); });
    }

    function sperrenZeigen(sperren) {
        var box = document.getElementById('sec-anm-sperren');
        if (!box) return;
        box.textContent = '';
        if (!sperren.length) {
            hinweis(box, 'security.sperren_none', 'Zurzeit ist kein Konto wegen Fehlversuchen gesperrt.');
            return;
        }
        sperren.forEach(function (s) {
            var row = el('div', { 'class': 'sec-anm-row', 'data-konto': s.konto,
                'style': 'border:1px solid var(--border);border-radius:8px;padding:10px 12px;margin-bottom:8px;display:flex;align-items:center;gap:10px;flex-wrap:wrap;' });
            row.appendChild(el('strong', { 'style': 'color:var(--text-primary);' }, s.display || s.konto));
            var zeit = new Date((s.bis || 0) * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
            row.appendChild(el('span', { 'class': 'kb-hint', 'style': 'margin:0;flex:1;' },
                fuellen(T('security.sperre_bis', 'gesperrt bis {zeit}'), { zeit: zeit })));
            var knopf = el('button', { 'type': 'button', 'class': 'sec-btn small sec-anm-aufheben' },
                T('security.sperre_aufheben', 'Sperre aufheben'));
            var meldung = el('div', { 'role': 'status', 'style': 'flex-basis:100%;font-size:0.85rem;color:var(--text-primary);' });
            knopf.addEventListener('click', function () {
                knopf.disabled = true;
                meldung.textContent = '';
                fetch('/api/admin/anmeldeschutz/aufheben', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + token(), 'Content-Type': 'application/json' },
                    body: JSON.stringify({ konto: s.konto })
                }).then(function (r) {
                    return r.json().catch(function () { return {}; })
                        .then(function (d) { return { status: r.status, d: d || {} }; });
                }).then(function (res) {
                    // 404 = Sperre inzwischen abgelaufen: Liste neu laden ist die richtige Antwort
                    if ((res.status === 200 && res.d.ok) || res.status === 404) { schutzLaden(); return; }
                    knopf.disabled = false;
                    meldung.textContent = res.d.detail || res.d.error || T('security.sperre_failed', 'Die Sperre konnte nicht aufgehoben werden.');
                }).catch(function () {
                    knopf.disabled = false;
                    meldung.textContent = T('security.sperre_failed', 'Die Sperre konnte nicht aufgehoben werden.');
                });
            });
            row.appendChild(knopf);
            row.appendChild(meldung);
            box.appendChild(row);
        });
    }

    function pflichtVerdrahten() {
        var cb = document.getElementById('sec-admin-2fa-pflicht');
        if (!cb || cb.dataset.verdrahtet) return;
        cb.dataset.verdrahtet = '1';
        // Nur auf "change" hoeren – der Browser schaltet im <label> selbst um.
        cb.addEventListener('change', function () {
            var msg = document.getElementById('sec-anm-pflicht-msg');
            var soll = cb.checked;
            cb.disabled = true;
            if (msg) msg.textContent = '';
            fetch('/api/admin/anmeldeschutz', {
                method: 'POST',
                headers: { 'Authorization': 'Bearer ' + token(), 'Content-Type': 'application/json' },
                body: JSON.stringify({ admin_2fa_pflicht: soll })
            }).then(function (r) {
                return r.json().catch(function () { return {}; })
                    .then(function (d) { return { ok: r.ok, d: d || {} }; });
            }).then(function (res) {
                cb.disabled = false;
                if (res.ok && res.d.ok) { cb.checked = !!res.d.admin_2fa_pflicht; return; }
                cb.checked = !soll;
                if (msg) msg.textContent = res.d.detail || res.d.error || T('security.pflicht_failed', 'Die Einstellung konnte nicht gespeichert werden.');
            }).catch(function () {
                cb.disabled = false;
                cb.checked = !soll;
                if (msg) msg.textContent = T('security.pflicht_failed', 'Die Einstellung konnte nicht gespeichert werden.');
            });
        });
    }

    function onShow() {
        load();
        pflichtVerdrahten();
        schutzLaden();
    }

    window.TotpAdmin = { onShow: onShow, _render: render, _sperrenZeigen: sperrenZeigen };
})();
