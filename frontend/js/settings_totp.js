/* BSI H4, CSP ohne Inline-Skript (2026-10-04): Zwei-Faktor-Authentifizierung (TOTP) des
   eigenen Kontos im Sicherheits-Reiter.
   Bis hierher stand dieser Code als Inline-<script> in settings.html.
   Eine Content-Security-Policy mit script-src 'self' ohne 'unsafe-inline'
   fuehrt kein Inline-Skript aus – deshalb ausgelagert, Inhalt unveraendert.
   Eingebunden SYNCHRON an DERSELBEN Stelle der Seite wie vorher (kein
   defer/async): Zeitpunkt und Reihenfolge bleiben gleich, inklusive dessen,
   was das Skript zu diesem Zeitpunkt vom Dokument schon sieht. */
(function() {
    async function _totpLoad() {
        const t = window.JarvisSitzung.token();
        if (!t) return;
        const statusEl = document.getElementById('totp-settings-status');
        const setupEl = document.getElementById('totp-settings-setup');
        const disableEl = document.getElementById('totp-settings-disable');
        const errEl = document.getElementById('totp-settings-error');
        const startBtn = document.getElementById('btn-totp-settings-start');
        // Bei ausgeschalteter 2FA wird erst auf Knopfdruck ein Secret vorgemerkt:
        // jedes /totp/setup schreibt ein neues totp_pending_secret nach
        // auth_state.json - bis 2026-10-14 geschah das schon beim blossen Oeffnen
        // des Reiters.
        try {
            const r = await fetch('/api/auth/totp/status', { headers: { 'Authorization': 'Bearer ' + t } });
            const d = await r.json();
            setupEl.style.display = 'none';
            if (d.enabled) {
                statusEl.innerHTML = '<p style="color:var(--success);font-size:0.85rem;">' + window.t('security.totp_enabled_msg') + '</p>';
                startBtn.style.display = 'none';
                disableEl.style.display = '';
            } else {
                statusEl.innerHTML = '<p style="color:var(--text-secondary);font-size:0.85rem;">' + window.t('security.totp_disabled_msg') + '</p>';
                disableEl.style.display = 'none';
                startBtn.style.display = '';
            }
        } catch(e) { statusEl.innerHTML = '<p style="color:var(--danger);font-size:0.85rem;">' + window.t('security.totp_error_load') + '</p>'; }

        startBtn.onclick = async function() {
            errEl.textContent = '';
            startBtn.disabled = true;
            try {
                const sr = await fetch('/api/auth/totp/setup', { method: 'POST', headers: { 'Authorization': 'Bearer ' + t } });
                const sd = await sr.json();
                if (!sr.ok || !sd.qr_code) { errEl.textContent = sd.error || window.t('security.totp_error_load'); return; }
                statusEl.innerHTML = '<p style="color:var(--text-secondary);font-size:0.85rem;">' + window.t('security.totp_scan_hint') + '</p>';
                document.getElementById('totp-settings-qr').innerHTML = '<img src="' + sd.qr_code + '" style="border-radius:8px;">';
                document.getElementById('totp-settings-secret').textContent = sd.secret;
                document.getElementById('totp-settings-code').value = '';
                startBtn.style.display = 'none';
                setupEl.style.display = '';
            } catch(e) { errEl.textContent = window.t('security.totp_error_load'); }
            finally { startBtn.disabled = false; }
        };

        document.getElementById('btn-totp-settings-verify').onclick = async function() {
            errEl.textContent = '';
            const code = document.getElementById('totp-settings-code').value.trim();
            if (!code) return;
            try {
                const r = await fetch('/api/auth/totp/verify', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + t, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ code })
                });
                const d = await r.json();
                if (d.success) { _totpLoad(); } else { errEl.textContent = d.error || window.t('security.totp_error_load'); }
            } catch(e) { errEl.textContent = window.t('security.totp_error_load'); }
        };

        document.getElementById('btn-totp-settings-disable').onclick = async function() {
            errEl.textContent = '';
            const pw = document.getElementById('totp-settings-disable-pw').value;
            if (!pw) return;
            try {
                const r = await fetch('/api/auth/totp/disable', {
                    method: 'POST',
                    headers: { 'Authorization': 'Bearer ' + t, 'Content-Type': 'application/json' },
                    body: JSON.stringify({ password: pw })
                });
                const d = await r.json();
                if (d.success) { document.getElementById('totp-settings-disable-pw').value = ''; _totpLoad(); }
                else { errEl.textContent = d.error || window.t('security.totp_error_load'); }
            } catch(e) { errEl.textContent = window.t('security.totp_error_load'); }
        };
    }
    const secBtn = document.querySelector('[data-settings-tab="security"]');
    if (secBtn) secBtn.addEventListener('click', _totpLoad);
})();
