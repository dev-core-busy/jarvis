/**
 * Microsoft 365 Copilot – Verbindung je BENUTZER (Reiter "Copilot").
 *
 * Die Zugangsdaten der Anwendung (Mandanten-/Anwendungs-Kennung) rendert
 * skillcfg.js aus dem Manifest in `#skcfg-copilot`. Dieses Modul macht nur den
 * zweiten Teil: jeder Benutzer verbindet SEIN eigenes Microsoft-Konto, denn die
 * Copilot-Chat-API gibt es ausschliesslich delegiert.
 *
 * WARUM DIE ANZEIGE DREI VORBEDINGUNGEN NENNT, STATT EINEN KNOPF ANZUBIETEN
 * Ein Knopf, der mit 403 antwortet, laesst den Benutzer raten. `/api/copilot/
 * status` liefert deshalb Skill-Zustand, Einrichtung UND Internet-Freigabe mit,
 * und die Anzeige nennt genau die Stelle, an der das Fehlende haengt. "Unbekannt"
 * gibt es hier nicht: fehlt die Auskunft, sagt die Anzeige das und behauptet
 * keinen Zustand (Register).
 *
 * WARUM DAS ABHOLEN IM FRONTEND TAKTET
 * Der Server haelt den von Microsoft vorgegebenen Takt selbst ein und antwortet
 * dazwischen mit "pending" – ein Hintergrund-Poller im Backend wuerde einen
 * Dienstneustart nicht ueberleben und seinen Zustand doch wieder herstellen
 * muessen. Hier genuegt ein Intervall; es wird bei JEDEM Ende gestoppt, sonst
 * haelt der Timer die Seite (und in jsdom den Prozess) offen.
 */
(function () {
    'use strict';

    const ABHOL_TAKT_MS = 2500;

    function t(key, rueckfall) {
        return (window.t ? window.t(key) : null) || rueckfall || key;
    }

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
            ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
    }

    /* Die Adresse kommt von Microsoft und landet in einem href. Nur https wird
     * verlinkt – alles andere (javascript:, data:) waere ein Einstieg, und ein
     * nicht verlinkter Text ist der harmlosere Ausfall. */
    function istSicher(url) {
        return typeof url === 'string' && /^https:\/\/[^\s"']+$/.test(url);
    }

    class CopilotVerbindung {
        constructor() {
            this._takt = null;
            this._laeuft = false;      // Geraete-Anmeldung offen?
        }

        async init() {
            this._stoppen();
            this._laeuft = false;
            await this._zeichnen();
        }

        onHide() { this._stoppen(); }

        _stoppen() {
            if (this._takt) { clearInterval(this._takt); this._takt = null; }
        }

        async _holen(pfad, optionen) {
            try {
                const o = Object.assign({ headers: {} }, optionen || {});
                o.headers['Authorization'] = 'Bearer ' + window.JarvisSitzung.token();
                if (o.body) o.headers['Content-Type'] = 'application/json';
                const r = await fetch(pfad, o);
                const d = await r.json().catch(() => ({}));
                return { status: r.status, daten: d || {} };
            } catch (e) {
                return { status: 0, daten: { error: String(e && e.message || e) } };
            }
        }

        // ─── Zustand zeichnen ──────────────────────────────────────────
        async _zeichnen() {
            const box = document.getElementById('copilot-status-container');
            if (!box) return;
            box.innerHTML = '<div class="kb-loading">'
                + esc(t('copilot.laedt', 'Lade…')) + '</div>';

            const { status, daten } = await this._holen('/api/copilot/status');
            if (status !== 200) {
                // Keinen Zustand behaupten, den wir nicht kennen.
                box.innerHTML = '<div class="cp-karte cp-warn">'
                    + '<div class="cp-titel">'
                    + esc(t('copilot.unbekannt', 'Zustand nicht abrufbar'))
                    + '</div><div class="cp-text">'
                    + esc(t('copilot.unbekannt_hinweis',
                            'Die Auskunft des Servers kam nicht an. Bitte die Seite neu laden.'))
                    + ' (HTTP ' + esc(status) + ')</div></div>';
                return;
            }
            box.innerHTML = this._markup(daten);
        }

        _markup(d) {
            const teile = [];

            // 1) Vorbedingungen – jede nennt die Stelle, an der sie haengt.
            if (!d.skill_aktiv) {
                teile.push(this._hinweis(
                    t('copilot.aus_titel', 'Skill nicht aktiv'),
                    t('copilot.aus_text',
                      'Der Skill „Microsoft 365 Copilot" ist abgeschaltet. Solange er aus ist, hat der Agent das Recherche-Werkzeug nicht. Einschalten unter Einstellungen → Skills.')));
            }
            if (!d.eingerichtet) {
                teile.push(this._hinweis(
                    t('copilot.unkonfig_titel', 'Anwendung fehlt'),
                    t('copilot.unkonfig_text',
                      'Mandanten-Kennung und Anwendungs-Kennung sind nicht hinterlegt. Ein Administrator trägt sie oben unter „Zugangsdaten" ein; die Anleitung dazu steht in docs/copilot.md.')));
            }
            if (!d.internet_frei) {
                teile.push(this._hinweis(
                    t('copilot.kein_netz_titel', 'Internet-Zugriff nicht freigegeben'),
                    t('copilot.kein_netz_text',
                      'Für dieses Konto ist der Internet-Zugriff nicht freigegeben – eine Recherche wird deshalb abgelehnt, auch mit verbundenem Microsoft-Konto. Freigabe unter Einstellungen → Sicherheit → Berechtigungen.')));
            }

            // 2) Die Verbindung selbst.
            if (d.verbunden) {
                teile.push(''
                    + '<div class="cp-karte" id="copilot-karte">'
                    + '<div class="cp-titel">'
                    + esc(t('copilot.verbunden_titel', 'Microsoft-Konto verbunden'))
                    + '</div>'
                    + '<div class="cp-konto" id="copilot-konto">'
                    + esc(d.konto || t('copilot.konto_unbekannt', 'Konto nicht übermittelt'))
                    + '</div>'
                    + '<div class="cp-text">'
                    + esc(t('copilot.verbunden_text',
                            'Recherchen laufen unter diesem Konto. Die gestellte Frage geht dabei an Microsoft und an die Bing-Suche.'))
                    + '</div>'
                    + '<button type="button" class="kb-btn-danger" data-cp-aktion="trennen"'
                    + ' data-i18n="copilot.trennen">'
                    + esc(t('copilot.trennen', 'Verbindung lösen')) + '</button>'
                    + '</div>');
            } else {
                const kannVerbinden = !!(d.eingerichtet && d.internet_frei);
                teile.push(''
                    + '<div class="cp-karte" id="copilot-karte">'
                    + '<div class="cp-titel">'
                    + esc(t('copilot.getrennt_titel', 'Noch nicht verbunden'))
                    + '</div>'
                    + '<div class="cp-text">'
                    + esc(t('copilot.getrennt_text',
                            'Melde dein Microsoft-Konto einmalig an. Du brauchst dafür eine Microsoft-365-Copilot-Lizenz; ohne sie lehnt Microsoft die Recherche ab.'))
                    + '</div>'
                    + '<button type="button" class="btn-primary cp-knopf"'
                    + ' data-cp-aktion="verbinden"'
                    + (kannVerbinden ? '' : ' disabled')
                    + ' data-i18n="copilot.verbinden">'
                    + esc(t('copilot.verbinden', 'Microsoft-Konto verbinden'))
                    + '</button>'
                    + '</div>');
            }
            return teile.join('');
        }

        _hinweis(titel, text) {
            return '<div class="cp-karte cp-warn"><div class="cp-titel">'
                + esc(titel) + '</div><div class="cp-text">' + esc(text)
                + '</div></div>';
        }

        // ─── Geraete-Anmeldung ─────────────────────────────────────────
        async verbinden() {
            const knopf = document.querySelector('[data-cp-aktion="verbinden"]');
            if (knopf) { knopf.disabled = true; }

            const { status, daten } = await this._holen(
                '/api/copilot/device-start', { method: 'POST', body: '{}' });
            if (status !== 200) {
                this._melden(daten.error
                    || t('copilot.start_fehler', 'Die Anmeldung konnte nicht gestartet werden.'));
                if (knopf) knopf.disabled = false;
                return;
            }

            const karte = document.getElementById('copilot-karte');
            if (!karte) return;
            const code = String(daten.user_code || '');
            const url = daten.verification_url;
            const min = Math.max(1, Math.ceil((Number(daten.expires_in) || 900) / 60));

            karte.innerHTML = ''
                + '<div class="cp-titel">'
                + esc(t('copilot.schritte_titel', 'Anmeldung in zwei Schritten'))
                + '</div>'
                + '<ol class="cp-schritte">'
                + '<li>' + esc(t('copilot.schritt1', 'Diese Seite öffnen:')) + ' '
                + (istSicher(url)
                    ? '<a href="' + esc(url) + '" target="_blank" rel="noopener noreferrer"'
                      + ' class="cp-url">' + esc(url) + '</a>'
                    : '<span class="cp-url">' + esc(url || '—') + '</span>')
                + '</li>'
                + '<li>' + esc(t('copilot.schritt2', 'Diesen Code eingeben und sich anmelden:'))
                + '</li>'
                + '</ol>'
                + '<div class="cp-code" id="copilot-code">' + esc(code) + '</div>'
                + '<div class="cp-text" id="copilot-wartet">'
                + esc(t('copilot.wartet', 'Warte auf die Bestätigung…'))
                + ' (' + esc(min) + ' min)</div>'
                + '<button type="button" class="btn-secondary cp-knopf"'
                + ' data-cp-aktion="abbrechen">'
                + esc(t('copilot.abbrechen', 'Abbrechen')) + '</button>';

            this._laeuft = true;
            this._stoppen();
            this._takt = setInterval(() => this._abholen(), ABHOL_TAKT_MS);
        }

        async _abholen() {
            if (!this._laeuft) { this._stoppen(); return; }
            const { daten } = await this._holen('/api/copilot/device-status');
            const zeile = document.getElementById('copilot-wartet');
            const zustand = String(daten.status || '');

            if (zustand === 'authorized') {
                this._laeuft = false;
                this._stoppen();
                if (zeile) {
                    zeile.textContent = t('copilot.fertig', 'Verbunden.')
                        + (daten.konto ? ' ' + daten.konto : '');
                }
                setTimeout(() => this._zeichnen(), 900);
            } else if (zustand === 'expired' || zustand === 'error') {
                this._laeuft = false;
                this._stoppen();
                // Ein Fehler darf NICHT von selbst verschwinden – man muss ihn
                // lesen und kopieren koennen (Register).
                if (zeile) {
                    zeile.textContent = (daten.message
                        || t('copilot.abgelaufen', 'Die Anmeldung ist abgelaufen oder fehlgeschlagen.'));
                    zeile.classList.add('cp-fehler');
                }
            } else if (zustand === 'idle') {
                // Der Dienst kennt den Vorgang nicht mehr (Neustart) – nicht
                // weiter fragen und den Grund nennen.
                this._laeuft = false;
                this._stoppen();
                if (zeile) {
                    zeile.textContent = t('copilot.verloren',
                        'Der Anmeldevorgang ist nicht mehr bekannt (wurde der Dienst neu gestartet?). Bitte neu beginnen.');
                    zeile.classList.add('cp-fehler');
                }
            }
        }

        abbrechen() {
            this._laeuft = false;
            this._stoppen();
            this._zeichnen();
        }

        async trennen() {
            // Nicht ruecknehmbar: mit dem Eintrag ist das Token weg.
            const frage = t('copilot.trennen_frage',
                'Verbindung zum Microsoft-Konto lösen? Für eine weitere Recherche muss das Konto neu angemeldet werden.');
            if (typeof window.confirm === 'function' && !window.confirm(frage)) return;
            const { status } = await this._holen('/api/copilot/connection',
                                                { method: 'DELETE' });
            if (status !== 200) {
                this._melden(t('copilot.trennen_fehler',
                               'Die Verbindung konnte nicht gelöst werden.'));
            }
            await this._zeichnen();
        }

        _melden(text) {
            const box = document.getElementById('copilot-status-container');
            if (!box) return;
            const zeile = document.createElement('div');
            zeile.className = 'cp-karte cp-warn cp-fehler';
            zeile.textContent = String(text);
            box.insertBefore(zeile, box.firstChild);
        }
    }

    // Ein delegierter Zuhoerer am Dokument: so wirkt auch ein Bedienelement,
    // das spaeter neu gezeichnet wird (Register – Markup-Regeln).
    const AKTIONEN = {
        verbinden:  (cp) => cp.verbinden(),
        abbrechen:  (cp) => cp.abbrechen(),
        trennen:    (cp) => cp.trennen(),
    };
    document.addEventListener('click', (e) => {
        const el = e.target && e.target.closest
            ? e.target.closest('[data-cp-aktion]') : null;
        if (!el) return;
        const name = el.getAttribute('data-cp-aktion');
        if (!Object.prototype.hasOwnProperty.call(AKTIONEN, name)) return;
        const cp = window.copilotVerbindung;
        if (cp) AKTIONEN[name](cp);
    }, true);

    window.copilotVerbindung = new CopilotVerbindung();
})();
