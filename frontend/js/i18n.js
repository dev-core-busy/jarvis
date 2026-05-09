/**
 * Jarvis i18n – Deutsch / English UI Übersetzungen
 *
 * Nutzung:
 *   window.t('key')              → übersetzter String
 *   window.setLang('en'|'de')    → Sprache wechseln + UI neu rendern
 *   window.applyLang()           → manuell nach dynamischem Re-Render aufrufen
 *
 * HTML:  <span data-i18n="key"></span>
 *        <input data-i18n-placeholder="key">
 *        <button data-i18n-title="key">
 */

const _I18N = {
    de: {
        // ── Login ──────────────────────────────────────────────
        'login.subtitle':       'KI Linux Agent',
        'login.username.label': 'BENUTZERNAME',
        'login.username.ph':    'Benutzername',
        'login.password.label': 'KENNWORT',
        'login.password.ph':    'Kennwort',
        'login.totp.label':     '2FA-CODE',
        'login.totp.ph':        '6-stelliger Code',
        'login.submit':         'ANMELDEN',
        'login.ssl.help':       'SSL Zertifikat & Verbindung Hilfe',
        'login.lang.toggle':    'Sprache',

        // ── Header / Navigation ───────────────────────────────
        'header.user_chat':     'Benutzer-Chat',
        'header.settings':      'KI-Einstellungen',
        'header.logout':        'Abmelden',
        'header.connection':    'Verbindungsstatus',

        // ── Agent Log Panel ───────────────────────────────────
        'panel.agent.title':    'Agent Aktivitätslog',
        'panel.minimize':       'Minimieren',
        'panel.maximize':       'Maximieren',
        'panel.restore':        'Wiederherstellen',
        'panel.clear':          'Log leeren',
        'panel.pause':          'Pausieren',
        'panel.resume':         'Fortsetzen',
        'panel.stop':           'Stoppen',
        'panel.debug':          'Debug-Ausgaben ein/ausblenden',
        'panel.zoom.out':       'Verkleinern',
        'panel.zoom.reset':     'Zurücksetzen',
        'panel.zoom.in':        'Vergrößern',

        // ── Input Area ────────────────────────────────────────
        'input.placeholder':    'Aufgabe für Jarvis eingeben...',
        'input.placeholder.agent': 'Nachricht an {label}...',
        'input.reset_ctx':      'Kontext zurücksetzen',
        'input.tts':            'Sprachausgabe',
        'input.mic':            'Spracheingabe',
        'input.send':           'Absenden',

        // ── Agent Status ──────────────────────────────────────
        'agent.running':        'Läuft',
        'agent.idle':           'Bereit',
        'agent.paused':         'Pause',
        'agent.stopped':        'Gestoppt',
        'agent.remove':         'Entfernen',
        'agent.ctx':            'Kontext Speicher',

        // ── Desktop Panel ─────────────────────────────────────
        'panel.desktop.title':  'Live Desktop',
        'panel.desktop.notconn':'Nicht verbunden',
        'panel.desktop.loading':'Desktop-Vorschau wird geladen...',

        // ── Settings Modal ────────────────────────────────────
        'settings.title':          'Einstellungen',
        'settings.tab.profiles':   'KI-Profile',
        'settings.tab.instructions':'Anweisungen',
        'settings.tab.skills':     'Skills',
        'settings.tab.whatsapp':   'WhatsApp',
        'settings.tab.knowledge':  'Wissen',
        'settings.tab.mcp':        'MCP',
        'settings.tab.vision':     'Vision',
        'settings.tab.telemetry':  'Telemetry',
        'settings.tab.security':   'Sicherheit',
        'settings.tab.cron':       'Cron',
        'settings.tab.update':     'Updates & Version',

        // ── Profile Settings ──────────────────────────────────
        'profile.new':          'Neues Profil',
        'profile.edit':         'Profil bearbeiten',
        'profile.save':         'Speichern',
        'profile.cancel':       'Abbrechen',
        'profile.delete':       'Löschen',
        'profile.test':         'Verbindung testen',

        // ── Security / Password ───────────────────────────────
        'security.change_pw':   'Kennwort ändern',
        'security.current_pw':  'Aktuelles Kennwort',
        'security.new_pw':      'Neues Kennwort',
        'security.confirm_pw':  'Kennwort bestätigen',
        'security.pw_ph_current': 'Aktuelles Kennwort',
        'security.pw_ph_new':   'Neues Kennwort',
        'security.pw_ph_repeat':'Kennwort wiederholen',
        'security.generate':    '🔑 Generieren',
        'security.save_pw':     'Kennwort speichern',
        'security.status':      'Sicherheitsstatus',

        // ── TTS Settings ──────────────────────────────────────
        'tts.title':            'Sprachausgabe (TTS)',
        'tts.voice':            'Stimme',
        'tts.on':               'Sprachausgabe aktiv – klicken zum Deaktivieren',
        'tts.off':              'Sprachausgabe inaktiv – klicken zum Aktivieren',

        // ── Update ────────────────────────────────────────────
        'update.title':         'Updates & Version',
        'update.check':         'Auf Updates prüfen',
        'update.install':       'Update installieren',
        'update.auto':          'Auto-Update',
        'update.schedule':      'Zeitplan',

        // ── Instructions ──────────────────────────────────────
        'instructions.empty':   'Noch keine Instruktionen vorhanden...',
        'instructions.save':    'Speichern',
        'instructions.delete':  'Instruktion löschen?',
        'instructions.error':   'Fehler beim Laden der Instruktionen.',

        // ── Knowledge ─────────────────────────────────────────
        'knowledge.title':      'Wissen',
        'knowledge.reindex':    'Neu indizieren',
        'knowledge.learned.title': 'Gelerntes Wissen',
        'knowledge.learned.show': '📋 Anzeigen',

        // ── Common ────────────────────────────────────────────
        'common.save':          'Speichern',
        'common.cancel':        'Abbrechen',
        'common.delete':        'Löschen',
        'common.edit':          'Bearbeiten',
        'common.close':         'Schließen',
        'common.loading':       'Lädt…',
        'common.error':         'Fehler',
        'common.saving':        'Speichere...',
        'common.testing':       'Teste…',
        'common.connecting':    'Verbinde...',
        'common.ok':            'OK',

        // ── Chat.html ─────────────────────────────────────────
        'chat.domain_login':    'Domain-Anmeldung',
        'chat.domain_ph':       'DOMAIN\\Benutzername',
        'chat.password_ph':     'Kennwort',
        'chat.totp_ph':         '6-stelliger Code',
        'chat.submit':          'Anmelden',
        'chat.voice_label':     'Stimme',
        'chat.voice_default':   'Standard',
        'chat.tts_toggle':      'Sprachausgabe ein/aus',
        'chat.theme':           'Hell/Dunkel umschalten',
        'chat.user_chat':       'Benutzer-Chat',
        'chat.ssl_cert':        'SSL-Zertifikat',
        'chat.setup_2fa':       '2FA einrichten',
        'chat.logout':          'Abmelden',
        'chat.greeting':        'Hallo! Ich bin Jarvis.',
        'chat.greeting_sub':    'Wie kann ich dir helfen?',
        'chat.ctx_active':      'Kontext aktiv',
        'chat.ctx_reset':       'Kontext zurücksetzen',
        'chat.stop_agent':      'Agent stoppen',
        'chat.input_ph':        'Nachricht eingeben…',
        'chat.mic':             'Spracheingabe',
        'chat.send':            'Senden',
        'chat.ctx_entries':     'Kontext Speicher',

        // ── Notifications / Misc ──────────────────────────────
        'notif.reconnect':      'Verbindung wird wiederhergestellt... (Versuch {n})',
        'notif.connected':      'Verbindung hergestellt',
        'notif.session_expire': 'Sitzung läuft in {mins} Min. ab.',
        'notif.update_ok':      'Update erfolgreich. Verbindung wird in 5 s wiederhergestellt…',
    },

    en: {
        // ── Login ──────────────────────────────────────────────
        'login.subtitle':       'AI Linux Agent',
        'login.username.label': 'USERNAME',
        'login.username.ph':    'Username',
        'login.password.label': 'PASSWORD',
        'login.password.ph':    'Password',
        'login.totp.label':     '2FA CODE',
        'login.totp.ph':        '6-digit code',
        'login.submit':         'SIGN IN',
        'login.ssl.help':       'SSL Certificate & Connection Help',
        'login.lang.toggle':    'Language',

        // ── Header / Navigation ───────────────────────────────
        'header.user_chat':     'User Chat',
        'header.settings':      'AI Settings',
        'header.logout':        'Sign Out',
        'header.connection':    'Connection Status',

        // ── Agent Log Panel ───────────────────────────────────
        'panel.agent.title':    'Agent Activity Log',
        'panel.minimize':       'Minimize',
        'panel.maximize':       'Maximize',
        'panel.restore':        'Restore',
        'panel.clear':          'Clear Log',
        'panel.pause':          'Pause',
        'panel.resume':         'Resume',
        'panel.stop':           'Stop',
        'panel.debug':          'Toggle Debug Output',
        'panel.zoom.out':       'Zoom Out',
        'panel.zoom.reset':     'Reset Zoom',
        'panel.zoom.in':        'Zoom In',

        // ── Input Area ────────────────────────────────────────
        'input.placeholder':    'Enter task for Jarvis...',
        'input.placeholder.agent': 'Message to {label}...',
        'input.reset_ctx':      'Reset Context',
        'input.tts':            'Text-to-Speech',
        'input.mic':            'Speech Input',
        'input.send':           'Send',

        // ── Agent Status ──────────────────────────────────────
        'agent.running':        'Running',
        'agent.idle':           'Ready',
        'agent.paused':         'Paused',
        'agent.stopped':        'Stopped',
        'agent.remove':         'Remove',
        'agent.ctx':            'Context Memory',

        // ── Desktop Panel ─────────────────────────────────────
        'panel.desktop.title':  'Live Desktop',
        'panel.desktop.notconn':'Not connected',
        'panel.desktop.loading':'Loading desktop preview...',

        // ── Settings Modal ────────────────────────────────────
        'settings.title':          'Settings',
        'settings.tab.profiles':   'AI Profiles',
        'settings.tab.instructions':'Instructions',
        'settings.tab.skills':     'Skills',
        'settings.tab.whatsapp':   'WhatsApp',
        'settings.tab.knowledge':  'Knowledge',
        'settings.tab.mcp':        'MCP',
        'settings.tab.vision':     'Vision',
        'settings.tab.telemetry':  'Telemetry',
        'settings.tab.security':   'Security',
        'settings.tab.cron':       'Cron',
        'settings.tab.update':     'Updates & Version',

        // ── Profile Settings ──────────────────────────────────
        'profile.new':          'New Profile',
        'profile.edit':         'Edit Profile',
        'profile.save':         'Save',
        'profile.cancel':       'Cancel',
        'profile.delete':       'Delete',
        'profile.test':         'Test Connection',

        // ── Security / Password ───────────────────────────────
        'security.change_pw':   'Change Password',
        'security.current_pw':  'Current Password',
        'security.new_pw':      'New Password',
        'security.confirm_pw':  'Confirm Password',
        'security.pw_ph_current': 'Current Password',
        'security.pw_ph_new':   'New Password',
        'security.pw_ph_repeat':'Repeat Password',
        'security.generate':    '🔑 Generate',
        'security.save_pw':     'Save Password',
        'security.status':      'Security Status',

        // ── TTS Settings ──────────────────────────────────────
        'tts.title':            'Text-to-Speech (TTS)',
        'tts.voice':            'Voice',
        'tts.on':               'Text-to-Speech active – click to disable',
        'tts.off':              'Text-to-Speech inactive – click to enable',

        // ── Update ────────────────────────────────────────────
        'update.title':         'Updates & Version',
        'update.check':         'Check for Updates',
        'update.install':       'Install Update',
        'update.auto':          'Auto-Update',
        'update.schedule':      'Schedule',

        // ── Instructions ──────────────────────────────────────
        'instructions.empty':   'No instructions yet...',
        'instructions.save':    'Save',
        'instructions.delete':  'Delete instruction?',
        'instructions.error':   'Error loading instructions.',

        // ── Knowledge ─────────────────────────────────────────
        'knowledge.title':      'Knowledge',
        'knowledge.reindex':    'Rebuild Index',
        'knowledge.learned.title': 'Learned Knowledge',
        'knowledge.learned.show': '📋 View',

        // ── Common ────────────────────────────────────────────
        'common.save':          'Save',
        'common.cancel':        'Cancel',
        'common.delete':        'Delete',
        'common.edit':          'Edit',
        'common.close':         'Close',
        'common.loading':       'Loading…',
        'common.error':         'Error',
        'common.saving':        'Saving...',
        'common.testing':       'Testing…',
        'common.connecting':    'Connecting...',
        'common.ok':            'OK',

        // ── Chat.html ─────────────────────────────────────────
        'chat.domain_login':    'Domain Login',
        'chat.domain_ph':       'DOMAIN\\username',
        'chat.password_ph':     'Password',
        'chat.totp_ph':         '6-digit code',
        'chat.submit':          'Sign In',
        'chat.voice_label':     'Voice',
        'chat.voice_default':   'Default',
        'chat.tts_toggle':      'Toggle Text-to-Speech',
        'chat.theme':           'Toggle Light/Dark',
        'chat.user_chat':       'User Chat',
        'chat.ssl_cert':        'SSL Certificate',
        'chat.setup_2fa':       'Set up 2FA',
        'chat.logout':          'Sign Out',
        'chat.greeting':        'Hello! I\'m Jarvis.',
        'chat.greeting_sub':    'How can I help you?',
        'chat.ctx_active':      'Context active',
        'chat.ctx_reset':       'Reset Context',
        'chat.stop_agent':      'Stop Agent',
        'chat.input_ph':        'Type a message…',
        'chat.mic':             'Speech Input',
        'chat.send':            'Send',
        'chat.ctx_entries':     'Context Memory',

        // ── Notifications / Misc ──────────────────────────────
        'notif.reconnect':      'Reconnecting... (Attempt {n})',
        'notif.connected':      'Connection established',
        'notif.session_expire': 'Session expires in {mins} min.',
        'notif.update_ok':      'Update successful. Reconnecting in 5 s…',
    },
};

// ─── Core ──────────────────────────────────────────────────────────────────

window._lang = localStorage.getItem('jarvis_lang') || 'de';

/** Gibt den übersetzten String zurück (Fallback: Deutsch, dann Key selbst). */
window.t = function(key) {
    return (_I18N[window._lang] && _I18N[window._lang][key])
        || (_I18N.de[key])
        || key;
};

/** Wendet alle data-i18n-Attribute auf das Dokument an. */
window.applyLang = function() {
    // Textinhalt
    document.querySelectorAll('[data-i18n]').forEach(el => {
        el.textContent = window.t(el.dataset.i18n);
    });
    // Placeholder
    document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
        el.placeholder = window.t(el.dataset.i18nPlaceholder);
    });
    // title-Attribut
    document.querySelectorAll('[data-i18n-title]').forEach(el => {
        el.title = window.t(el.dataset.i18nTitle);
    });
    // aria-label
    document.querySelectorAll('[data-i18n-aria]').forEach(el => {
        el.setAttribute('aria-label', window.t(el.dataset.i18nAria));
    });

    // Task-Input Placeholder (wird von app.js dynamisch gesetzt – überschreiben)
    const taskInput = document.getElementById('task-input');
    if (taskInput && !taskInput.dataset.agentActive) {
        taskInput.placeholder = window.t('input.placeholder');
    }

    // Sprachschalter-Buttons synchronisieren
    document.querySelectorAll('.lang-toggle-btn').forEach(btn => {
        const isActive = btn.dataset.lang === window._lang;
        btn.classList.toggle('active', isActive);
    });
};

/** Wechselt die Sprache und speichert sie in localStorage. */
window.setLang = function(lang) {
    if (!_I18N[lang]) return;
    window._lang = lang;
    localStorage.setItem('jarvis_lang', lang);
    window.applyLang();
};

// ─── Sprachschalter HTML-Generator ────────────────────────────────────────

window.createLangToggle = function(extraClass) {
    const div = document.createElement('div');
    div.className = 'lang-toggle ' + (extraClass || '');
    div.innerHTML = `
        <button class="lang-toggle-btn${window._lang === 'de' ? ' active' : ''}"
            data-lang="de" onclick="window.setLang('de')" title="Deutsch">DE</button>
        <button class="lang-toggle-btn${window._lang === 'en' ? ' active' : ''}"
            data-lang="en" onclick="window.setLang('en')" title="English">EN</button>`;
    return div;
};

// ─── Auto-Apply nach DOM-Ready ─────────────────────────────────────────────

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', window.applyLang);
} else {
    window.applyLang();
}
