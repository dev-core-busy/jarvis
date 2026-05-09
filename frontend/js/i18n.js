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
        // ── Formular-Validierung (Browser-Meldung) ─────────────
        'validation.required':  'Bitte dieses Feld ausfüllen.',
        'validation.pw_match':  'Kennwörter stimmen nicht überein.',

        // ── Login ──────────────────────────────────────────────
        'login.subtitle':        'KI Linux Agent',
        'login.username.label':  'BENUTZERNAME',
        'login.username.ph':     'Benutzername',
        'login.password.label':  'KENNWORT',
        'login.password.ph':     'Kennwort',
        'login.totp.label':      '2FA-CODE',
        'login.totp.ph':         '6-stelliger Code',
        'login.submit':          'ANMELDEN',
        'login.connecting':      'VERBINDE…',
        'login.failed':          'Anmeldung fehlgeschlagen',
        'login.server_error':    'Server nicht erreichbar',
        'login.ssl.help':        'SSL Zertifikat & Verbindung Hilfe',

        // ── Header / Navigation ───────────────────────────────
        'header.user_chat':      'Benutzer-Chat',
        'header.settings':       'KI-Einstellungen',
        'header.logout':         'Abmelden',
        'header.connection':     'Verbindungsstatus',

        // ── Agent Log Panel ───────────────────────────────────
        'panel.agent.title':     'Agent Aktivitätslog',
        'panel.minimize':        'Minimieren',
        'panel.maximize':        'Maximieren',
        'panel.restore':         'Wiederherstellen',
        'panel.clear':           'Log leeren',
        'panel.pause':           'Pausieren',
        'panel.resume':          'Fortsetzen',
        'panel.stop':            'Stoppen',
        'panel.debug.on':        'debug aktiv',
        'panel.debug.off':       'debug aktivieren',
        'panel.zoom.out':        'Verkleinern',
        'panel.zoom.reset':      'Zurücksetzen',
        'panel.zoom.in':         'Vergrößern',

        // ── Input Area ────────────────────────────────────────
        'input.placeholder':     'Aufgabe für Jarvis eingeben...',
        'input.placeholder.agent': 'Nachricht an {label}...',
        'input.reset_ctx':       'Kontext zurücksetzen',
        'input.tts':             'Sprachausgabe',
        'input.mic':             'Spracheingabe',
        'input.send':            'Absenden',

        // ── Agent Status ──────────────────────────────────────
        'agent.running':         'Läuft',
        'agent.idle':            'Bereit',
        'agent.paused':          'Pause',
        'agent.stopped':         'Gestoppt',
        'agent.remove':          'Entfernen',
        'context.label':         'Kontext Speicher: {n} Einträge · {pct} %',

        // ── Desktop Panel ─────────────────────────────────────
        'panel.desktop.title':   'Live Desktop',
        'panel.desktop.notconn': 'Nicht verbunden',
        'panel.desktop.loading': 'Desktop-Vorschau wird geladen...',

        // ── Settings Modal ────────────────────────────────────
        'settings.title':           'Einstellungen',
        'settings.tab.profiles':    'KI-Profile',
        'settings.tab.instructions':'Anweisungen',
        'settings.tab.skills':      'Skills',
        'settings.tab.whatsapp':    'WhatsApp',
        'settings.tab.knowledge':   'Wissen',
        'settings.tab.mcp':         'MCP',
        'settings.tab.vision':      'Vision',
        'settings.tab.telemetry':   'Telemetry',
        'settings.tab.security':    'Sicherheit',
        'settings.tab.cron':        'Cron',

        // ── Profile Settings ──────────────────────────────────
        'profile.new':               'Neues Profil',
        'profile.edit':              'Profil bearbeiten',
        'profile.save':              'Speichern',
        'profile.cancel':            'Abbrechen',
        'profile.delete':            'Löschen',
        'profile.test':              'Verbindung testen',
        'profile.testing':           '⏳ Verbindung wird geprüft…',
        'profile.switched':          'Profil gewechselt: {name}',
        'profile.saved':             'Profil gespeichert: {name}',
        'profile.deleted':           'Profil gelöscht: {name}',
        'profile.name_required':     'Bitte einen Profilnamen eingeben.',
        'profile.model_required':    'Bitte ein Modell angeben.',
        'profile.cannot_delete_last':'Das letzte Profil kann nicht gelöscht werden.',
        'profile.confirm_delete':    'Profil "{name}" wirklich löschen?',
        'profile.name_ph':           'z.B. Google Standard',
        'profile.model_ph':          'Modellname eingeben oder aus Liste wählen',

        // ── Security / Password ───────────────────────────────
        'security.change_pw':     '🔒 Kennwort ändern',
        'security.current_pw':    'Aktuelles Kennwort',
        'security.new_pw':        'Neues Kennwort',
        'security.confirm_pw':    'Kennwort bestätigen',
        'security.pw_ph_current': 'Aktuelles Kennwort',
        'security.pw_ph_new':     'Neues Kennwort',
        'security.pw_ph_repeat':  'Kennwort wiederholen',
        'security.generate':      '🔑 Generieren',
        'security.save_pw':       'Kennwort speichern',
        'security.status':        'Sicherheitsstatus',
        'security.password_changed': '✅ Kennwort erfolgreich geändert.',
        'security.change_error':  'Fehler beim Ändern.',
        'security.fill_fields':   'Alle Felder ausfüllen.',
        'security.strength.0':    'Sehr schwach',
        'security.strength.1':    'Schwach',
        'security.strength.2':    'Mittel',
        'security.strength.3':    'Stark',
        'security.strength.4':    'Sehr stark',

        // ── TTS Settings ──────────────────────────────────────
        'tts.title':   'Sprachausgabe (TTS)',
        'tts.voice':   'Stimme',
        'tts.on':      'Sprachausgabe deaktivieren',
        'tts.off':     'Sprachausgabe aktivieren',

        // ── Update Widget ─────────────────────────────────────
        'update.badge_title':       '{n} Commit(s) verfügbar',
        'update.widget_title_ok':   'Version & Updates',
        'update.widget_title_avail':'{n} Update(s) verfügbar – klicken zum Aktualisieren',
        'update.status_ok':         'Aktuell',
        'update.status_error':      'Fehler: {msg}',
        'update.commits_singular':  '{n} neuer Commit verfügbar',
        'update.commits_plural':    '{n} neue Commits verfügbar',
        'update.current':           'Aktuell:',
        'update.branch':            'Branch:',
        'update.apply_btn':         '⬇ Jetzt aktualisieren',
        'update.check_btn':         '🔄 Erneut prüfen',
        'update.auto_label':        'Auto-Update',
        'update.sched_never':       'Aus',
        'update.sched_daily':       'Täglich (03:00)',
        'update.sched_weekly':      'Wöchentlich (Mo 03:00)',
        'update.applying':          '⏳ Aktualisiere…',
        'update.in_progress':       'Update wird durchgeführt – Jarvis startet danach neu…',
        'update.success':           '✅ Update erfolgreich. Verbindung wird in 5 s wiederhergestellt…',
        'update.error':             'Fehler: {msg}',
        'update.unknown_error':     'Unbekannter Fehler',

        // ── Profile Form Labels ───────────────────────────────
        'profile.name_label':       'Profilname',
        'profile.provider_label':   'LLM Anbieter',
        'profile.url_label':        'API URL',
        'profile.model_label':      'Modell',
        'profile.auth_method_label':'Zugangsart',
        'profile.apikey_label':     'API Key',
        'profile.session_key_label':'Session Key',
        'profile.add_btn':          '+ Neues Profil',
        'profile.voice_label':      'Stimme',
        'profile.section_list':     'KI-Profile',
        'profile.section_tts':      'Sprachausgabe (TTS)',
        'profile.section_key':      'Agent API Key',
        'profile.section_ssl':      'HTTPS / SSL-Zertifikat',

        // ── Security Form Labels ──────────────────────────────
        'security.section_pw':      'Kennwort ändern',
        'security.section_ad':      'Active Directory / LDAP',
        'security.section_2fa':     'Zwei-Faktor-Authentifizierung (2FA)',
        'security.section_status':  'Sicherheitsstatus',
        'security.pw_hint':         'Bitte setze ein neues Kennwort. Es muss mindestens 8 Zeichen, einen Großbuchstaben, einen Kleinbuchstaben und eine Ziffer enthalten.',

        // ── Instructions ──────────────────────────────────────
        'instructions.empty':   'Noch keine Instruktionen vorhanden. Erstelle eine neue über das Feld oben.',
        'instructions.save':    'Speichern',
        'instructions.delete':  'Löschen',
        'instructions.confirm_delete': 'Instruktion "{name}" wirklich löschen?',
        'instructions.error':   'Fehler beim Laden der Instruktionen.',
        'instructions.new':     '+ Neue Instruktion',
        'instructions.new_ph':  'Name der neuen Instruktion',

        // ── Knowledge ─────────────────────────────────────────
        'knowledge.title':           'Wissen',
        'knowledge.reindex':         'Neu indizieren',
        'knowledge.learned.title':   'Gelerntes Wissen',
        'knowledge.learned.show':    '📋 Anzeigen',

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
        'common.copy':          'Kopieren',
        'common.copied':        'Kopiert!',
        'common.error_unknown': 'Fehler: {msg}',
        'common.connection_failed': 'Server-Verbindung fehlgeschlagen',
        'common.stt_unsupported': 'Spracherkennung wird von deinem Browser leider nicht unterstützt (nutze Chrome oder Edge).',

        // ── Chat.html ─────────────────────────────────────────
        'chat.domain_login':    'Domain-Anmeldung',
        'chat.domain_ph':       'DOMAIN\\Benutzername',
        'chat.password_ph':     'Kennwort',
        'chat.totp_ph':         '6-stelliger Code',
        'chat.submit':          'Anmelden',
        'chat.connecting':      'Anmelden…',
        'chat.login_failed':    'Anmeldung fehlgeschlagen',
        'chat.connection_error':'Verbindungsfehler',
        'chat.voice_label':     'Stimme',
        'chat.voice_default':   'Standard',
        'chat.tts_toggle':      'Sprachausgabe ein/aus',
        'chat.tts_on':          'Sprachausgabe deaktivieren',
        'chat.tts_off':         'Sprachausgabe aktivieren',
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
        'chat.ctx_label':       'Kontext Speicher: {n} Einträge · {pct} %',

        // ── Notifications ─────────────────────────────────────
        'notif.reconnect':      'Verbindung wird wiederhergestellt... (Versuch {n})',
        'notif.connected':      'Verbindung hergestellt',
        'notif.session_expire': 'Sitzung läuft in {mins} Min. ab.',
    },

    en: {
        // ── Formular-Validierung (Browser-Meldung) ─────────────
        'validation.required':  'Please fill in this field.',
        'validation.pw_match':  'Passwords do not match.',

        // ── Login ──────────────────────────────────────────────
        'login.subtitle':        'AI Linux Agent',
        'login.username.label':  'USERNAME',
        'login.username.ph':     'Username',
        'login.password.label':  'PASSWORD',
        'login.password.ph':     'Password',
        'login.totp.label':      '2FA CODE',
        'login.totp.ph':         '6-digit code',
        'login.submit':          'SIGN IN',
        'login.connecting':      'CONNECTING…',
        'login.failed':          'Login failed',
        'login.server_error':    'Server unreachable',
        'login.ssl.help':        'SSL Certificate & Connection Help',

        // ── Header / Navigation ───────────────────────────────
        'header.user_chat':      'User Chat',
        'header.settings':       'AI Settings',
        'header.logout':         'Sign Out',
        'header.connection':     'Connection Status',

        // ── Agent Log Panel ───────────────────────────────────
        'panel.agent.title':     'Agent Activity Log',
        'panel.minimize':        'Minimize',
        'panel.maximize':        'Maximize',
        'panel.restore':         'Restore',
        'panel.clear':           'Clear Log',
        'panel.pause':           'Pause',
        'panel.resume':          'Resume',
        'panel.stop':            'Stop',
        'panel.debug.on':        'debug on',
        'panel.debug.off':       'debug off',
        'panel.zoom.out':        'Zoom Out',
        'panel.zoom.reset':      'Reset Zoom',
        'panel.zoom.in':         'Zoom In',

        // ── Input Area ────────────────────────────────────────
        'input.placeholder':     'Enter task for Jarvis...',
        'input.placeholder.agent': 'Message to {label}...',
        'input.reset_ctx':       'Reset Context',
        'input.tts':             'Text-to-Speech',
        'input.mic':             'Speech Input',
        'input.send':            'Send',

        // ── Agent Status ──────────────────────────────────────
        'agent.running':         'Running',
        'agent.idle':            'Ready',
        'agent.paused':          'Paused',
        'agent.stopped':         'Stopped',
        'agent.remove':          'Remove',
        'context.label':         'Context Memory: {n} entries · {pct} %',

        // ── Desktop Panel ─────────────────────────────────────
        'panel.desktop.title':   'Live Desktop',
        'panel.desktop.notconn': 'Not connected',
        'panel.desktop.loading': 'Loading desktop preview...',

        // ── Settings Modal ────────────────────────────────────
        'settings.title':           'Settings',
        'settings.tab.profiles':    'AI Profiles',
        'settings.tab.instructions':'Instructions',
        'settings.tab.skills':      'Skills',
        'settings.tab.whatsapp':    'WhatsApp',
        'settings.tab.knowledge':   'Knowledge',
        'settings.tab.mcp':         'MCP',
        'settings.tab.vision':      'Vision',
        'settings.tab.telemetry':   'Telemetry',
        'settings.tab.security':    'Security',
        'settings.tab.cron':        'Cron',

        // ── Profile Settings ──────────────────────────────────
        'profile.new':               'New Profile',
        'profile.edit':              'Edit Profile',
        'profile.save':              'Save',
        'profile.cancel':            'Cancel',
        'profile.delete':            'Delete',
        'profile.test':              'Test Connection',
        'profile.testing':           '⏳ Testing connection…',
        'profile.switched':          'Profile switched: {name}',
        'profile.saved':             'Profile saved: {name}',
        'profile.deleted':           'Profile deleted: {name}',
        'profile.name_required':     'Please enter a profile name.',
        'profile.model_required':    'Please specify a model.',
        'profile.cannot_delete_last':'Cannot delete the last profile.',
        'profile.confirm_delete':    'Really delete profile "{name}"?',
        'profile.name_ph':           'e.g. Google Default',
        'profile.model_ph':          'Enter model name or choose from list',

        // ── Security / Password ───────────────────────────────
        'security.change_pw':     '🔒 Change Password',
        'security.current_pw':    'Current Password',
        'security.new_pw':        'New Password',
        'security.confirm_pw':    'Confirm Password',
        'security.pw_ph_current': 'Current Password',
        'security.pw_ph_new':     'New Password',
        'security.pw_ph_repeat':  'Repeat Password',
        'security.generate':      '🔑 Generate',
        'security.save_pw':       'Save Password',
        'security.status':        'Security Status',
        'security.password_changed': '✅ Password changed successfully.',
        'security.change_error':  'Error changing password.',
        'security.fill_fields':   'Please fill in all fields.',
        'security.strength.0':    'Very weak',
        'security.strength.1':    'Weak',
        'security.strength.2':    'Fair',
        'security.strength.3':    'Strong',
        'security.strength.4':    'Very strong',

        // ── TTS Settings ──────────────────────────────────────
        'tts.title':   'Text-to-Speech (TTS)',
        'tts.voice':   'Voice',
        'tts.on':      'Disable Text-to-Speech',
        'tts.off':     'Enable Text-to-Speech',

        // ── Update Widget ─────────────────────────────────────
        'update.badge_title':       '{n} commit(s) available',
        'update.widget_title_ok':   'Version & Updates',
        'update.widget_title_avail':'{n} update(s) available – click to update',
        'update.status_ok':         'Up to date',
        'update.status_error':      'Error: {msg}',
        'update.commits_singular':  '{n} new commit available',
        'update.commits_plural':    '{n} new commits available',
        'update.current':           'Current:',
        'update.branch':            'Branch:',
        'update.apply_btn':         '⬇ Update now',
        'update.check_btn':         '🔄 Check again',
        'update.auto_label':        'Auto-Update',
        'update.sched_never':       'Off',
        'update.sched_daily':       'Daily (03:00)',
        'update.sched_weekly':      'Weekly (Mon 03:00)',
        'update.applying':          '⏳ Updating…',
        'update.in_progress':       'Update in progress – Jarvis will restart afterwards…',
        'update.success':           '✅ Update successful. Reconnecting in 5 s…',
        'update.error':             'Error: {msg}',
        'update.unknown_error':     'Unknown error',

        // ── Profile Form Labels ───────────────────────────────
        'profile.name_label':       'Profile Name',
        'profile.provider_label':   'LLM Provider',
        'profile.url_label':        'API URL',
        'profile.model_label':      'Model',
        'profile.auth_method_label':'Auth Method',
        'profile.apikey_label':     'API Key',
        'profile.session_key_label':'Session Key',
        'profile.add_btn':          '+ New Profile',
        'profile.voice_label':      'Voice',
        'profile.section_list':     'AI Profiles',
        'profile.section_tts':      'Text-to-Speech (TTS)',
        'profile.section_key':      'Agent API Key',
        'profile.section_ssl':      'HTTPS / SSL Certificate',

        // ── Security Form Labels ──────────────────────────────
        'security.section_pw':      'Change Password',
        'security.section_ad':      'Active Directory / LDAP',
        'security.section_2fa':     'Two-Factor Authentication (2FA)',
        'security.section_status':  'Security Status',
        'security.pw_hint':         'Please set a new password. It must be at least 8 characters with an uppercase letter, lowercase letter, and a digit.',

        // ── Instructions ──────────────────────────────────────
        'instructions.empty':   'No instructions yet. Create one using the field above.',
        'instructions.save':    'Save',
        'instructions.delete':  'Delete',
        'instructions.confirm_delete': 'Really delete instruction "{name}"?',
        'instructions.error':   'Error loading instructions.',
        'instructions.new':     '+ New Instruction',
        'instructions.new_ph':  'New instruction name',

        // ── Knowledge ─────────────────────────────────────────
        'knowledge.title':           'Knowledge',
        'knowledge.reindex':         'Rebuild Index',
        'knowledge.learned.title':   'Learned Knowledge',
        'knowledge.learned.show':    '📋 View',

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
        'common.copy':          'Copy',
        'common.copied':        'Copied!',
        'common.error_unknown': 'Error: {msg}',
        'common.connection_failed': 'Connection failed',
        'common.stt_unsupported': 'Speech recognition is not supported by your browser (use Chrome or Edge).',

        // ── Chat.html ─────────────────────────────────────────
        'chat.domain_login':    'Domain Login',
        'chat.domain_ph':       'DOMAIN\\username',
        'chat.password_ph':     'Password',
        'chat.totp_ph':         '6-digit code',
        'chat.submit':          'Sign In',
        'chat.connecting':      'Signing in…',
        'chat.login_failed':    'Login failed',
        'chat.connection_error':'Connection error',
        'chat.voice_label':     'Voice',
        'chat.voice_default':   'Default',
        'chat.tts_toggle':      'Toggle Text-to-Speech',
        'chat.tts_on':          'Disable Text-to-Speech',
        'chat.tts_off':         'Enable Text-to-Speech',
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
        'chat.ctx_label':       'Context Memory: {n} entries · {pct} %',

        // ── Notifications ─────────────────────────────────────
        'notif.reconnect':      'Reconnecting... (Attempt {n})',
        'notif.connected':      'Connection established',
        'notif.session_expire': 'Session expires in {mins} min.',
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

    // Browser-Formularvalidierung übersetzen (alle required-Inputs)
    document.querySelectorAll('input[required]').forEach(input => {
        input.addEventListener('invalid', _onInvalid, { once: false });
        input.addEventListener('input',   _onInput,   { once: false });
    });

    // Debug-Button Text (falls vorhanden und in localStorage gespeichert)
    const btnDebug = document.getElementById('btn-debug');
    if (btnDebug) {
        const isActive = btnDebug.classList.contains('active');
        btnDebug.textContent = isActive
            ? window.t('panel.debug.on')
            : window.t('panel.debug.off');
    }

    // Sprachschalter-Buttons synchronisieren
    document.querySelectorAll('.lang-toggle-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.lang === window._lang);
    });
};

function _onInvalid(e) {
    e.target.setCustomValidity(window.t('validation.required'));
}
function _onInput(e) {
    e.target.setCustomValidity('');
}

/** Wechselt die Sprache und speichert sie in localStorage. */
window.setLang = function(lang) {
    if (!_I18N[lang]) return;
    window._lang = lang;
    localStorage.setItem('jarvis_lang', lang);
    window.applyLang();
};

// ─── Auto-Apply nach DOM-Ready ─────────────────────────────────────────────

if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', window.applyLang);
} else {
    window.applyLang();
}
