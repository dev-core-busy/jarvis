/* ═══════════════════════════════════════════════════════════════════
   E-Mail-Reiter (Administrator) – Einstellungen → E-Mail
   ───────────────────────────────────────────────────────────────────
   Drei Dinge, streng getrennt, weil sie unterschiedlichen Leuten gehoeren:
     1. Verbindung zum firmeninternen Exchange (Serverdaten, EINMAL fuer alle)
     2. Freigabe der Werkzeug-Bereiche, aus denen Benutzer je Regel waehlen
     3. Exchange-Explorer + Uebersicht der angebundenen Postfaecher

   WAS HIER ABSICHTLICH FEHLT: die Regeln. Sie gehoeren dem Benutzer und
   werden im Bereich /email gepflegt (Entscheidung 2026-08-12). Dieser Reiter
   zeigt nur, WER ein Postfach hinterlegt hat und wie viele Regeln laufen –
   keine Prompts, keine Betreffzeilen.

   ZWEI KNOEPFE, ZWEI TEILMENGEN: "Verbindung speichern" sendet nie
   `bereiche`, "Freigabe speichern" nie die Serverdaten. Der Server merged
   (update_skill_config) – ein Knopf, der den ganzen Formularstand
   mitschickt, ueberschriebe den jeweils anderen Teil (dieselbe Trennung wie
   bei den SAP-Sichtbarkeiten).
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    var _gebunden = false;
    var _bereiche = [];        // Katalog vom Server
    var _bereicheLang = '';    // in welcher Sprache er geholt wurde
    var _konten = [];

    function token() { return localStorage.getItem('jarvis_token') || ''; }
    function kopf(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function $(id) { return document.getElementById(id); }
    // Wie in email_portal.js: der Schluessel gewinnt, der deutsche Text im Code
    // ist nur der Rueckfall (und zugleich die lesbare Vorlage fuer i18n.js).
    function T(key, fallback) {
        var s = window.t ? window.t(key) : null;
        return (s && s !== key) ? s : fallback;
    }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function melde(id, text, art) {
        var e = $(id);
        if (!e) return;
        e.textContent = text || '';
        e.style.color = art === 'ok' ? 'var(--success)'
            : art === 'fehler' ? 'var(--danger)' : 'var(--text-muted)';
    }
    function zeit(ts) {
        if (!ts) return '–';
        try { return new Date(ts * 1000).toLocaleString(); } catch (e) { return '–'; }
    }

    /* ── Klapp-Container ───────────────────────────────────────────────── */
    // Die Klapp-Logik liegt in app.js::_collapseInit (kb-collapse-header/-body):
    // sie merkt sich den Zustand je Container im localStorage und nimmt Klicks
    // auf Knoepfe/Felder in der Kopfzeile aus. Eine zweite Umsetzung hier waere
    // Drift – und genau die erste Fassung hatte den Titel rechts stehen, weil
    // sie das Markup-Muster des Projekts nicht benutzte.
    function klappInit() {
        if (typeof window.initEmailCollapse === 'function') window.initEmailCollapse();
    }

    /* ── Verbindung ────────────────────────────────────────────────────── */
    function setzeWert(id, wert) { var e = $(id); if (e) e.value = wert == null ? '' : wert; }
    function setzeHaken(id, wert) { var e = $(id); if (e) e.checked = !!wert; }

    function ladeVerbindung() {
        return fetch('/api/skills/email/config', { headers: kopf() })
            .then(function (r) { return r.ok ? r.json() : {}; })
            .then(function (antwort) {
                // DIE ANTWORT IST VERSCHACHTELT: {config: {...}} – dasselbe Muster
                // wie in skillcfg.js (`(cfgResp && cfgResp.config) || {}`). Eine
                // Ebene zu hoch gelesen, war JEDES Feld `undefined`: das Laden
                // leerte die Eingaben, und ein zweites "Speichern" schrieb die
                // Leere dann wirklich fest – gemeldet als "die EWS-URL wird nicht
                // gespeichert" (2026-08-12).
                var c = (antwort && antwort.config) || {};
                setzeWert('em-kanal', c.kanal || 'auto');
                setzeWert('em-ews-url', c.ews_url);
                // NICHT auf Falsyness pruefen: ein gespeichertes `false` muss als
                // false erscheinen, ein FEHLENDES Feld dagegen als Vorgabe true.
                setzeHaken('em-autodiscover', c.autodiscover === undefined ? true : !!c.autodiscover);
                setzeWert('em-auth-typ', c.auth_typ || 'auto');
                setzeHaken('em-verify-ssl', c.verify_ssl === undefined ? true : !!c.verify_ssl);
                setzeWert('em-imap-host', c.imap_host);
                setzeWert('em-imap-port', c.imap_port == null ? 993 : c.imap_port);
                setzeHaken('em-imap-ssl', c.imap_ssl === undefined ? true : !!c.imap_ssl);
                setzeWert('em-smtp-host', c.smtp_host);
                setzeWert('em-smtp-port', c.smtp_port == null ? 587 : c.smtp_port);
                setzeHaken('em-smtp-starttls', c.smtp_starttls === undefined ? true : !!c.smtp_starttls);
                setzeWert('em-ordner-eingang', c.ordner_eingang || 'INBOX');
                setzeWert('em-ordner-entwuerfe', c.ordner_entwuerfe);
                setzeWert('em-ordner-gesendet', c.ordner_gesendet);
                setzeWert('em-zeitlimit', c.zeitlimit == null ? 30 : c.zeitlimit);
                setzeWert('em-takt', c.takt_sekunden == null ? 60 : c.takt_sekunden);
            })
            .catch(function () { melde('em-conn-status', T('mailadm.m_cfg_unreadable', 'Konfiguration nicht lesbar.'), 'fehler'); });
    }

    function zahl(id, vorgabe) {
        var e = $(id);
        var v = parseInt((e && e.value) || '', 10);
        return isNaN(v) ? vorgabe : v;
    }

    function speichereVerbindung() {
        var daten = {
            kanal: ($('em-kanal') || {}).value || 'auto',
            ews_url: (($('em-ews-url') || {}).value || '').trim(),
            autodiscover: !!(($('em-autodiscover') || {}).checked),
            auth_typ: ($('em-auth-typ') || {}).value || 'auto',
            verify_ssl: !!(($('em-verify-ssl') || {}).checked),
            imap_host: (($('em-imap-host') || {}).value || '').trim(),
            imap_port: zahl('em-imap-port', 993),
            imap_ssl: !!(($('em-imap-ssl') || {}).checked),
            smtp_host: (($('em-smtp-host') || {}).value || '').trim(),
            smtp_port: zahl('em-smtp-port', 587),
            smtp_starttls: !!(($('em-smtp-starttls') || {}).checked),
            ordner_eingang: (($('em-ordner-eingang') || {}).value || '').trim() || 'INBOX',
            ordner_entwuerfe: (($('em-ordner-entwuerfe') || {}).value || '').trim(),
            ordner_gesendet: (($('em-ordner-gesendet') || {}).value || '').trim(),
            zeitlimit: zahl('em-zeitlimit', 30),
            takt_sekunden: zahl('em-takt', 60)
        };
        // `bereiche` ist hier BEWUSST nicht dabei – siehe Modulkopf.
        melde('em-conn-status', T('common.saving', 'Speichere…'));
        return fetch('/api/skills/email/config', {
            method: 'POST',
            headers: kopf({ 'Content-Type': 'application/json' }),
            body: JSON.stringify(daten)
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            melde('em-conn-status', T('mailadm.m_conn_saved', '✓ Verbindung gespeichert.'), 'ok');
        }).catch(function (e) {
            melde('em-conn-status', T('common.error', 'Fehler') + ': ' + e.message, 'fehler');
        });
    }

    /* ── Bereichs-Freigabe ─────────────────────────────────────────────── */
    function zeichneBereiche() {
        var box = $('em-areas');
        if (!box) return;
        box.innerHTML = '';
        _bereiche.forEach(function (b) {
            var lab = document.createElement('label');
            var cb = document.createElement('input');
            cb.type = 'checkbox';
            cb.value = b.id;
            cb.checked = !!b.freigegeben;
            if (b.pflicht) {
                // 'mail' ist nicht abwaehlbar: eine Regel ohne Mail-Werkzeuge
                // koennte nichts tun. Sichtbar gesperrt statt still erzwungen.
                cb.checked = true;
                cb.disabled = true;
                lab.className = 'is-locked';
            }
            lab.appendChild(cb);
            var txt = document.createElement('span');
            var warn = b.id === 'voll' ? ' ⚠' : '';
            txt.innerHTML = '<b>' + esc(b.name) + warn + '</b><br>'
                + '<span class="kb-hint">' + esc(b.hinweis || '') + '</span>';
            lab.appendChild(txt);
            box.appendChild(lab);
        });
    }

    function speichereBereiche() {
        var gewaehlt = [];
        document.querySelectorAll('#em-areas input[type="checkbox"]').forEach(function (cb) {
            if (cb.checked) gewaehlt.push(cb.value);
        });
        melde('em-areas-status', T('common.saving', 'Speichere…'));
        return fetch('/api/email/admin/areas', {
            method: 'POST',
            headers: kopf({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ bereiche: gewaehlt })
        }).then(function (r) { return r.json().then(function (d) { return { r: r, d: d }; }); })
            .then(function (x) {
                if (!x.r.ok || !x.d.ok) throw new Error(x.d.error || ('HTTP ' + x.r.status));
                melde('em-areas-status', T('mailadm.m_areas_saved', '✓ Freigegeben:') + ' ' + (x.d.bereiche || []).join(', '), 'ok');
                return ladeUebersicht();
            }).catch(function (e) {
                melde('em-areas-status', T('common.error', 'Fehler') + ': ' + e.message, 'fehler');
            });
    }

    /* ── Uebersicht / Konten ───────────────────────────────────────────── */
    function ladeUebersicht() {
        // Sprache mitgeben: Name und Hinweis der Bereiche kommen uebersetzt vom
        // Server (sie stehen dort neben der Werkzeugliste, damit Text und
        // Wirkung nicht auseinanderlaufen) – applyLang() erreicht sie nicht.
        var lg = (window._lang === 'en') ? 'en' : 'de';
        _bereicheLang = lg;
        return fetch('/api/email/admin/overview?lang=' + lg, { headers: kopf() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || !d.ok) throw new Error((d && d.error) || 'Abruf fehlgeschlagen');
                _bereiche = d.bereiche || [];
                _konten = d.konten || [];
                zeichneBereiche();
                zeichneKonten(d);
                fuelleExplorer();
            })
            .catch(function (e) {
                var box = $('em-accounts');
                if (box) box.innerHTML = '<p class="kb-hint" style="color:var(--danger);">'
                    + esc(e.message) + '</p>';
            });
    }

    function zeichneKonten(d) {
        var box = $('em-accounts');
        var zaehler = $('em-acc-count');
        if (!box) return;
        if (zaehler) {
            zaehler.textContent = '(' + T('mailadm.cnt', '{m} Postfach/Postfächer, {r} Regeln')
                .replace('{m}', _konten.length).replace('{r}', d.regeln_gesamt || 0) + ')';
        }
        if (!_konten.length) {
            box.innerHTML = '<p class="kb-hint">' + T('mailadm.acc_empty',
                'Noch kein Postfach angebunden. Freigegebene Benutzer hinterlegen ihr '
                + 'Postfach selbst im Bereich <b>E-Mail</b> (Kachel im Portal). '
                + 'Freigabe: Sicherheit → Berechtigungen → E-Mail-Zugriff.') + '</p>';
            return;
        }
        var h = '<table class="audit-table" style="width:100%;"><thead><tr>'
            + '<th>' + T('mailadm.th_user', 'Benutzer') + '</th>'
            + '<th>' + T('mailadm.th_address', 'Adresse') + '</th>'
            + '<th>' + T('mailadm.th_rules', 'Regeln') + '</th>'
            + '<th>' + T('mailadm.th_lastok', 'Zuletzt erfolgreich') + '</th>'
            + '<th>' + T('mailadm.th_lasterr', 'Letzter Fehler') + '</th></tr></thead><tbody>';
        _konten.forEach(function (k) {
            h += '<tr>'
                + '<td>' + esc(k.benutzer) + (k.aktiv ? '' : ' <span class="kb-hint">(' + T('mailadm.inactive', 'inaktiv') + ')</span>') + '</td>'
                + '<td>' + esc(k.adresse) + (k.passwort_gesetzt ? '' : ' <span class="kb-hint">(' + T('mailadm.nopw', 'kein Kennwort') + ')</span>') + '</td>'
                + '<td>' + (k.regeln_aktiv || 0) + ' / ' + (k.regeln || 0) + '</td>'
                + '<td>' + esc(zeit(k.letzter_erfolg)) + '</td>'
                + '<td>' + (k.letzter_fehler
                    ? '<span style="color:var(--danger);">' + esc(k.letzter_fehler) + '</span>'
                    : '–') + '</td>'
                + '</tr>';
        });
        box.innerHTML = h + '</tbody></table>';
    }

    /* ── Explorer ──────────────────────────────────────────────────────── */
    function fuelleExplorer() {
        var sel = $('em-exp-user');
        if (!sel) return;
        var vorher = sel.value;
        sel.innerHTML = '';
        if (!_konten.length) {
            var o = document.createElement('option');
            o.value = '';
            o.textContent = '(' + T('mailadm.exp_none', 'kein Postfach hinterlegt') + ')';
            sel.appendChild(o);
            return;
        }
        _konten.forEach(function (k) {
            var o = document.createElement('option');
            o.value = k.benutzer_norm;
            o.textContent = k.benutzer + ' — ' + k.adresse;
            sel.appendChild(o);
        });
        if (vorher) sel.value = vorher;
    }

    function erkunde() {
        var user = ($('em-exp-user') || {}).value || '';
        if (!user) {
            melde('em-exp-status', T('mailadm.m_no_mailbox', 'Es ist kein Postfach hinterlegt, das untersucht werden könnte.'), 'fehler');
            return Promise.resolve();
        }
        var limit = parseInt(($('em-exp-limit') || {}).value || '0', 10) || 0;
        var knopf = $('em-explore');
        if (knopf) knopf.disabled = true;
        melde('em-exp-status', T('mail.testing', 'Verbinde… (kann bis zu einer halben Minute dauern)'));
        var box = $('em-exp-result');
        if (box) box.innerHTML = '';
        return fetch('/api/email/admin/explore', {
            method: 'POST',
            headers: kopf({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ benutzer: user, limit: limit })
        }).then(function (r) { return r.json().then(function (d) { return { r: r, d: d }; }); })
            .then(function (x) {
                if (!x.r.ok || !x.d.ok) throw new Error((x.d && x.d.error) || ('HTTP ' + x.r.status));
                melde('em-exp-status', T('mail.test_ok', '✓ Verbindung steht')
                    + ' (' + T('mailadm.channel', 'Zugangsweg') + ': '
                    + esc((x.d.ergebnis || {}).kanal || '?') + ')', 'ok');
                zeichneExplorer(x.d.ergebnis || {});
            }).catch(function (e) {
                melde('em-exp-status', T('common.error', 'Fehler') + ': ' + e.message, 'fehler');
            }).finally(function () {
                if (knopf) knopf.disabled = false;
            });
    }

    function zeichneExplorer(res) {
        var box = $('em-exp-result');
        if (!box) return;
        var t = res.test || {};
        var h = '<div style="padding:10px 12px;border:1px solid rgba(var(--fg-rgb),0.09);'
            + 'border-radius:10px;background:rgba(var(--fg-rgb),0.02);margin-bottom:10px;">'
            + '<b>' + T('mailadm.exp_user', 'Postfach (Benutzer)') + ':</b> '
            + esc(t.postfach || '?') + ' &nbsp;·&nbsp; '
            + '<b>' + T('mailadm.channel', 'Zugangsweg') + ':</b> '
            + esc(res.kanal || t.kanal || '?');
        if (t.server_version) h += ' &nbsp;·&nbsp; <b>' + T('mailadm.exp_server', 'Server')
            + ':</b> ' + esc(t.server_version);
        if (t.ews_url) h += '<br><b>EWS:</b> <code>' + esc(t.ews_url) + '</code>';
        if (t.imap_host) h += '<br><b>IMAP:</b> <code>' + esc(t.imap_host) + '</code>';
        if (t.eingang_gesamt >= 0) {
            h += '<br><b>' + T('mail.acct_inbox', 'Posteingang') + ':</b> '
                + T('mailadm.exp_counts', '{g} Nachrichten, {u} ungelesen')
                    .replace('{g}', t.eingang_gesamt).replace('{u}', t.eingang_ungelesen);
        }
        h += '</div>';

        var ordner = res.ordner || [];
        h += '<h4 style="margin:12px 0 6px;">' + T('mailadm.exp_folders', 'Ordner')
            + ' (' + ordner.length + ')</h4>';
        if (!ordner.length) {
            h += '<p class="kb-hint">' + T('mailadm.exp_nofolders', 'Keine Ordner gemeldet.') + '</p>';
        } else {
            h += '<div class="sec-scrollbox" style="max-height:240px;">';
            ordner.forEach(function (o) {
                var z = o.anzahl >= 0
                    ? ' <span class="kb-hint">(' + o.anzahl + ' / ' + o.ungelesen + ' '
                        + T('mail.unread', 'ungelesen') + ')</span>'
                    : '';
                h += '<div style="padding:3px 0;"><code>' + esc(o.pfad || o.name) + '</code>' + z + '</div>';
            });
            h += '</div>';
        }

        var mails = res.nachrichten || [];
        if (mails.length) {
            h += '<h4 style="margin:12px 0 6px;">' + T('mailadm.exp_newest', 'Neueste Nachrichten')
                + ' (' + mails.length + ')</h4>'
                + '<table class="audit-table" style="width:100%;"><thead><tr>'
                + '<th>' + T('mailadm.th_date', 'Datum') + '</th>'
                + '<th>' + T('mailadm.th_from', 'Von') + '</th>'
                + '<th>' + T('mailadm.th_subject', 'Betreff') + '</th></tr></thead><tbody>';
            mails.forEach(function (m) {
                h += '<tr><td>' + esc(m.datum || '?') + '</td><td>' + esc(m.von || '?')
                    + '</td><td>' + esc(m.betreff || T('mail.log_nosubject', '(kein Betreff)')) + '</td></tr>';
            });
            h += '</tbody></table>';
        }
        box.innerHTML = h;
    }

    /* ── Bindung ───────────────────────────────────────────────────────── */
    function binde() {
        if (_gebunden) return;
        _gebunden = true;
        klappInit();
        var b;
        if ((b = $('em-save-conn'))) b.addEventListener('click', speichereVerbindung);
        if ((b = $('em-save-areas'))) b.addEventListener('click', speichereBereiche);
        if ((b = $('em-explore'))) b.addEventListener('click', erkunde);
        // Der Bereichskatalog ist Server-Text; bei DE/EN neu holen. Der
        // Vergleich verhindert einen zweiten Abruf beim Seitenaufbau, wo
        // applyLang() dasselbe Ereignis feuert.
        window.addEventListener('jarvis-lang-changed', function () {
            var lg = (window._lang === 'en') ? 'en' : 'de';
            if (_bereicheLang && _bereicheLang !== lg) ladeUebersicht();
        });
    }

    window.EmailAdmin = {
        // Idempotent: onShow kann mehrfach kommen (Reiter-Klick UND openModal).
        onShow: function () {
            binde();
            klappInit();
            ladeVerbindung();
            ladeUebersicht();
        },
        _test: { zeichneKonten: zeichneKonten, zeichneExplorer: zeichneExplorer }
    };
})();
