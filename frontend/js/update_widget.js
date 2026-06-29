/* Versions-/Update-Widget – gemeinsam fuer index.html und chat.html.
   Erwartet im DOM: #version-pill, #update-dropdown, #update-badge,
   #update-version, #upd-body, #upd-close. i18n via window.t.
   Token-Quelle: window.authToken oder einer der bekannten localStorage-Keys.
   API: window.JarvisUpdateWidget.init() – idempotent. */
(function () {
    'use strict';

    function token() {
        return window.authToken
            || localStorage.getItem('jarvis_token')
            || localStorage.getItem('jarvis_chat_token')
            || localStorage.getItem('jarvis_uc_token')
            || '';
    }
    function auth() { return { 'Authorization': 'Bearer ' + token() }; }
    function T(key, repl) {
        var s = (window.t ? window.t(key) : key) || key;
        if (repl) Object.keys(repl).forEach(function (k) { s = s.replace('{' + k + '}', repl[k]); });
        return s;
    }
    function esc(s) {
        return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    var widget, dropdown, badge, verEl, body;
    var _open = false, _timer = null, _inited = false;

    function init() {
        widget = document.getElementById('version-pill');
        dropdown = document.getElementById('update-dropdown');
        badge = document.getElementById('update-badge');
        verEl = document.getElementById('update-version');
        body = document.getElementById('upd-body');
        if (!widget || _inited) return;
        _inited = true;
        widget.addEventListener('click', toggle);
        var closeBtn = document.getElementById('upd-close');
        if (closeBtn) closeBtn.addEventListener('click', close);
        document.addEventListener('click', function (e) {
            if (_open && !widget.contains(e.target) && !(dropdown && dropdown.contains(e.target))) close();
        });
        check();
        _timer = setInterval(check, 30 * 60 * 1000);
    }

    function toggle() { _open ? close() : open(); }
    function open() { _open = true; if (dropdown) dropdown.classList.remove('hidden'); check(); }
    function close() { _open = false; if (dropdown) dropdown.classList.add('hidden'); }

    function check() {
        fetch('/api/update/status', { headers: auth() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) { if (d) render(d); })
            .catch(function () {});
    }

    function render(d) {
        if (verEl) verEl.textContent = 'v' + (d.jarvis_version || '?');
        if (badge) {
            badge.style.display = d.has_update ? 'inline' : 'none';
            badge.className = 'update-badge' + (d.has_update ? ' has-update' : '');
            badge.title = d.has_update ? T('update.badge_title', { n: d.commits_behind }) : '';
        }
        if (widget) {
            widget.classList.toggle('has-update', !!d.has_update);
            widget.title = d.has_update
                ? T('update.widget_title_avail', { n: d.commits_behind })
                : T('update.widget_title_ok');
        }
        if (!body) return;
        fetch('/api/update/settings', { headers: auth() })
            .then(function (r) { return r.json(); })
            .then(function (s) { buildBody(d, s.auto_update_schedule || 'never'); })
            .catch(function () { buildBody(d, 'never'); });
    }

    function buildBody(d, schedule) {
        if (!body) return;
        var statusDot = d.has_update ? 'pending' : (d.ok ? 'ok' : 'error');
        var statusText = d.has_update
            ? (d.commits_behind === 1
                ? T('update.commits_singular', { n: d.commits_behind })
                : T('update.commits_plural', { n: d.commits_behind }))
            : (d.ok ? T('update.status_ok') : T('update.status_error', { msg: d.error || '?' }));

        var commitsHtml = '';
        if (d.recent_commits && d.recent_commits.length) {
            commitsHtml = '<div class="upd-commit-list">' + d.recent_commits.map(function (c) {
                return '<div class="upd-commit"><span class="upd-commit-hash">' + esc(c.hash) + '</span>'
                    + '<span class="upd-commit-msg">' + esc(c.message) + '</span>'
                    + '<span class="upd-commit-date">' + esc(c.date) + '</span></div>';
            }).join('') + '</div>';
        }

        var btnHtml = d.has_update
            ? '<button id="upd-apply-btn" class="kb-btn-action">' + T('update.apply_btn') + '</button>'
            : '<button id="upd-check-btn" class="kb-btn-secondary" style="font-size:.78rem;">' + T('update.check_btn') + '</button>';

        body.innerHTML =
            '<div class="upd-status-row"><span class="upd-dot ' + statusDot + '"></span>'
            + '<span style="font-size:.82rem;color:var(--text-primary);">' + esc(statusText) + '</span></div>'
            + '<div style="display:flex;justify-content:space-between;font-size:.75rem;color:var(--text-secondary);">'
            + '<span>' + T('update.current') + ' <code style="color:var(--accent);">' + esc(d.current_hash || '?') + '</code></span>'
            + '<span>' + T('update.branch') + ' <code style="color:var(--text-secondary);">' + esc(d.branch || 'master') + '</code></span></div>'
            + commitsHtml + btnHtml
            + '<div class="upd-auto-row"><span class="upd-auto-label">' + T('update.auto_label') + '</span>'
            + '<select id="upd-schedule" class="upd-schedule-select">'
            + '<option value="never"' + (schedule === 'never' ? ' selected' : '') + '>' + T('update.sched_never') + '</option>'
            + '<option value="daily"' + (schedule === 'daily' ? ' selected' : '') + '>' + T('update.sched_daily') + '</option>'
            + '<option value="weekly"' + (schedule === 'weekly' ? ' selected' : '') + '>' + T('update.sched_weekly') + '</option>'
            + '</select></div>';

        var applyBtn = document.getElementById('upd-apply-btn');
        if (applyBtn) applyBtn.addEventListener('click', applyUpdate);
        var checkBtn = document.getElementById('upd-check-btn');
        if (checkBtn) checkBtn.addEventListener('click', check);
        var sched = document.getElementById('upd-schedule');
        if (sched) sched.addEventListener('change', function (e) { saveSchedule(e.target.value); });
    }

    function applyUpdate() {
        var btn = document.getElementById('upd-apply-btn');
        if (btn) { btn.disabled = true; btn.textContent = T('update.applying'); }
        if (body) {
            var info = document.createElement('p');
            info.className = 'kb-hint';
            info.style.cssText = 'margin:0;color:#f39c12;';
            info.textContent = T('update.in_progress');
            body.prepend(info); body.scrollTop = 0;
        }
        fetch('/api/update/apply', { method: 'POST', headers: auth() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (d.ok) {
                    if (body) body.innerHTML = '<p style="color:#2ecc71;font-size:.85rem;">' + T('update.success') + '</p>';
                    setTimeout(function () { window.location.reload(); }, 5000);
                } else {
                    if (body) {
                        var err = document.createElement('p');
                        err.className = 'kb-hint';
                        err.style.cssText = 'color:#e74c3c;white-space:pre-wrap;word-break:break-word;';
                        err.textContent = T('update.error', { msg: d.error || d.detail || T('update.unknown_error') });
                        body.prepend(err); body.scrollTop = 0;
                    }
                    if (btn) { btn.disabled = false; btn.textContent = T('update.apply_btn'); }
                }
            })
            .catch(function () { if (btn) { btn.disabled = false; btn.textContent = T('update.apply_btn'); } });
    }

    function saveSchedule(val) {
        fetch('/api/update/settings', {
            method: 'POST',
            headers: Object.assign(auth(), { 'Content-Type': 'application/json' }),
            body: JSON.stringify({ auto_update_schedule: val })
        }).catch(function () {});
    }

    window.JarvisUpdateWidget = { init: init };
})();
