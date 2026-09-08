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
                // Der Pfad der Add-in-Bereitstellung liegt in derselben
                // Skill-Config und kommt mit diesem Abruf mit - ein eigener
                // Roundtrip fuer ein Feld waere der teuerste Weg.
                ladeAddinPfad(c);
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

    /* ── Add-in-Bereitstellung ─────────────────────────────────────────
       Zwei Aufgaben, und die zweite ist nur eine ANGABE:

       1. Die Manifest-Datei besorgen. `#em-addin-download` ist ein reines
          <a href> und wird NICHT abgefangen: so entscheidet der Browser ueber
          das Ziel, und der Administrator kann die Datei auch auf den Desktop
          legen. Der Endpunkt liefert `Content-Disposition` samt
          Branding-Dateinamen - ein Umweg ueber fetch+Blob muesste den Namen
          selbst bilden und liefe damit dem Branding hinterher (genau der
          Fehler, der beim Jira-Paket gemeldet wurde).

       2. Den Netzwerkordner eintragen, in dem die Datei fuer die Benutzer
          liegt. ⚠ DER EINGETRAGENE PFAD KANN NICHT BENUTZT WERDEN - das ist
          keine Bequemlichkeit dieses Moduls, sondern eine Grenze JEDES
          Browsers: es gibt keine API, die in einen als TEXT genannten Ordner
          schreibt. `showDirectoryPicker`/`showSaveFilePicker` liefern ein
          Handle aus einem Dialog, `startIn` nimmt nur ein Handle oder einen
          festen Namen. Eine Seite, die in `\\server\freigabe\...` schreiben
          duerfte, weil dort jemand den Pfad hingetippt hat, waere genau die
          Luecke, die diese Grenze verhindert. Ausfuehrlich begruendet im Kopf
          von excel_admin.js - dort steht auch, was schon verworfen wurde.

       Der Ordner-Knopf ist deshalb der naechstbeste Weg: der Zielordner wird
       EINMAL im Dialog gewaehlt, das Handle in IndexedDB gemerkt, und danach
       schreibt der Knopf direkt hinein. */

    /* Ein FileSystemDirectoryHandle ist strukturiert klonbar und laesst sich
       deshalb in IndexedDB ablegen - localStorage kann es NICHT (dort landet
       nur "[object FileSystemDirectoryHandle]"). Genau diese Persistenz ist der
       Unterschied zwischen "jedes Mal den Ordner suchen" und "einmal waehlen".
       EIGENER Schluessel neben dem des Excel-Reiters: die beiden Manifeste
       gehoeren in verschiedene Ordner, und ein geteiltes Handle schriebe das
       Outlook-Manifest in den Excel-Katalog. */
    var _FS_DB = 'jarvis-fs', _FS_STORE = 'handles', _FS_KEY = 'outlook-addin-ordner';
    var _ordner = null;            // FileSystemDirectoryHandle oder null
    var _adresseKaputt = false;    // Server lehnt den Abruf ab (localhost-Basis)
    var _dateiname = '';           // aus Content-Disposition, folgt dem Branding
    var _pfadGespeichert = '';

    function fsDb() {
        return new Promise(function (res, rej) {
            if (!window.indexedDB) { rej(new Error('IndexedDB fehlt')); return; }
            var a = indexedDB.open(_FS_DB, 1);
            a.onupgradeneeded = function () {
                if (!a.result.objectStoreNames.contains(_FS_STORE)) a.result.createObjectStore(_FS_STORE);
            };
            a.onsuccess = function () { res(a.result); };
            a.onerror = function () { rej(a.error || new Error('IndexedDB')); };
        });
    }

    function handleLesen() {
        return fsDb().then(function (d) {
            return new Promise(function (res) {
                var r = d.transaction(_FS_STORE, 'readonly').objectStore(_FS_STORE).get(_FS_KEY);
                r.onsuccess = function () { res(r.result || null); };
                r.onerror = function () { res(null); };
            });
        }).catch(function () { return null; });
    }

    function handleSchreiben(h) {
        return fsDb().then(function (d) {
            return new Promise(function (res, rej) {
                var t = d.transaction(_FS_STORE, 'readwrite');
                t.objectStore(_FS_STORE).put(h, _FS_KEY);
                t.oncomplete = function () { res(true); };
                t.onerror = function () { rej(t.error); };
            });
        });
    }

    /* Berechtigung fuer das gemerkte Handle. Sie faellt nach einem
       Browser-Neustart regelmaessig auf "prompt" zurueck - das ist KEIN Fehler
       und darf nicht als solcher gemeldet werden. `fragen=false` prueft nur
       (fuer die Anzeige), `true` fragt nach (braucht eine Nutzergeste). */
    function darfSchreiben(h, fragen) {
        if (!h || !h.queryPermission) return Promise.resolve(false);
        return h.queryPermission({ mode: 'readwrite' }).then(function (z) {
            if (z === 'granted') return true;
            if (!fragen || !h.requestPermission) return false;
            return h.requestPermission({ mode: 'readwrite' })
                    .then(function (z2) { return z2 === 'granted'; });
        }).catch(function () { return false; });
    }

    /* Kann dieser Browser in einen frei gewaehlten Ordner schreiben?
       Die File System Access API gibt es in Chrome und Edge, NICHT in Firefox
       und Safari - und nur im sicheren Kontext. Ohne sie bleibt es beim
       Download; das ist kein Fehler, sondern der Normalfall dieser Browser. */
    function kannSchreiben() {
        return typeof window.showDirectoryPicker === 'function';
    }

    /* Der Pfad, der GERADE gilt: was im Feld steht, sonst der gespeicherte.
       Der Feldinhalt hat Vorrang - wer den Pfad eintippt und sofort auf den
       Knopf drueckt, meint diesen Pfad (im Excel-Reiter war das der gemeldete
       Fehler: dort hing der Knopf am GESPEICHERTEN Wert). */
    function feldPfad() {
        var f = $('em-addin-pfad');
        var v = (f ? f.value : '').trim();
        return v || _pfadGespeichert;
    }

    /* Der Ordner-Knopf erscheint nur, wo er wirklich geht (Chrome/Edge) UND nur
       mit eingetragenem Pfad: einer ohne Zielpfad hat kein Ziel.
       ⚠ DIESE FUNKTION MUSS VOR JEDEM FRUEHEN AUSSTIEG LAUFEN - im Excel-Reiter
       sass sie HINTER dem Ausstieg fuer "kein Pfad", der Zweig war unerreichbar,
       und beim LEEREN des Feldes blieb der Knopf stehen (ohne Ziel). */
    function ordnerKnopf() {
        var ub = $('em-addin-upload');
        if (!ub) return;
        var geht = !!feldPfad() && kannSchreiben() && !_adresseKaputt;
        ub.style.display = geht ? '' : 'none';
        if (geht) {
            ub.textContent = _ordner
                ? T('mailadm.addin_up_named', 'In Ordner „{n}" schreiben').replace('{n}', _ordner.name || '?')
                : T('mailadm.addin_up', 'Ordner wählen und hineinschreiben');
        }
    }

    /* Deckt das Serverzertifikat die Adresse im Manifest? Der Endpunkt legt das
       Urteil in `X-Jarvis-Cert-Warn`; bei einer localhost-Basis lehnt er mit 400
       ab. Geprueft wird per HEAD-artigem GET beim Oeffnen des Reiters - er
       kostet nichts und beantwortet die Frage, die Outlook spaeter nur als
       "vertraut dem Add-in nicht" stellt.

       DER DATEINAME WIRD HIER MITGELESEN: er folgt dem Branding und steht im
       Hinweis, damit der Administrator die Datei im Download-Ordner
       wiederfindet. Nachgebaut liefe er dem Branding hinterher. */
    function pruefeAdresse() {
        var warn = $('em-addin-warn');
        var dl = $('em-addin-download');
        return fetch('/addin/manifest.xml', { cache: 'no-store' })
            .then(function (r) {
                if (r.ok) {
                    _adresseKaputt = false;
                    _dateiname = dateinameAus(r.headers.get('Content-Disposition'));
                    var zw = r.headers.get('X-Jarvis-Cert-Warn');
                    if (warn) {
                        if (zw) {
                            warn.textContent = '⚠ ' + zw;
                            warn.style.color = 'var(--warning, #d98a00)';
                            warn.style.display = '';
                        } else {
                            warn.style.display = 'none';
                        }
                    }
                    zeigeDateiname();
                    return;
                }
                // Der Server antwortet bei fachlichem Fehlschlag mit 400 und
                // Klartext - "HTTP 400" allein waere wertlos.
                return r.json().catch(function () { return {}; }).then(function (d) {
                    _adresseKaputt = true;
                    if (warn) {
                        warn.textContent = '⚠ ' + (d.error || T('mailadm.addin_badbase',
                            'Das Manifest kann über diese Adresse nicht erzeugt werden.'));
                        warn.style.color = 'var(--danger)';
                        warn.style.display = '';
                    }
                    // Eine Datei, die auf jedem Arbeitsplatz ins Leere zeigt,
                    // darf auch der Ordner-Weg nicht in die Freigabe legen.
                    if (dl) { dl.style.opacity = '.5'; dl.style.pointerEvents = 'none'; }
                    ordnerKnopf();
                });
            }).catch(function () { /* Netzfehler: keine Behauptung wagen */ });
    }

    /* Der Dateiname aus `Content-Disposition` - RFC-5987-Form zuerst
       (`filename*=utf-8''…`), sonst die einfache. Faellt der Kopf aus, bleibt
       der Name leer und der Aufrufer benutzt einen sachlichen Rueckfall;
       "jarvis" waere auf einem gebrandeten System genau der Fehler, der beim
       Jira-Paket gemeldet wurde. */
    function dateinameAus(kopf) {
        var s = String(kopf || '');
        var m = /filename\*\s*=\s*utf-8''([^;]+)/i.exec(s);
        if (m) { try { return decodeURIComponent(m[1].trim()); } catch (e) { /* weiter */ } }
        m = /filename\s*=\s*"([^"]+)"/i.exec(s) || /filename\s*=\s*([^;]+)/i.exec(s);
        return m ? m[1].trim() : '';
    }

    function zeigeDateiname() {
        var e = $('em-addin-version');
        if (!e) return;
        e.textContent = _dateiname
            ? T('mailadm.addin_file', 'Datei: {n}').replace('{n}', _dateiname) : '';
    }

    function ladeAddinPfad(c) {
        _pfadGespeichert = String((c && c.addin_ordner_pfad) || '').trim();
        setzeWert('em-addin-pfad', _pfadGespeichert);
        ordnerKnopf();
    }

    /* Eigener Knopf, eigene TEILMENGE.
     * `POST /api/skills/email/config` merged serverseitig - ein Knopf darf
     * deshalb nur seine eigenen Felder senden. Schickte er den ganzen
     * Formularstand mit, ueberschriebe er den Stand der anderen Knoepfe
     * (Register: "Zwei Knoepfe im selben Reiter"): ein leeres Kennwortfeld
     * waere dann ein geloeschter Zugang. */
    function speichereAddinPfad(still) {
        var pfad = (($('em-addin-pfad') || {}).value || '').trim();
        if (!still) melde('em-addin-status', T('common.saving', 'Speichere…'));
        return fetch('/api/skills/email/config', {
            method: 'POST',
            headers: kopf({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ addin_ordner_pfad: pfad })
        }).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            _pfadGespeichert = pfad;
            ordnerKnopf();
            if (!still) {
                melde('em-addin-status', pfad
                    ? T('mailadm.addin_saved', '✓ Gespeichert – die Benutzer sehen jetzt diesen Pfad.')
                    : T('mailadm.addin_cleared', '✓ Gespeichert – die Benutzer laden die Datei wieder selbst.'), 'ok');
                setTimeout(function () { melde('em-addin-status', ''); }, 6000);
            }
        }).catch(function (e) {
            if (!still) melde('em-addin-status', T('common.error', 'Fehler') + ': ' + e.message, 'fehler');
        });
    }

    /* Den Zielordner besorgen - gemerkter zuerst, sonst EINMAL fragen.
       MUSS synchron in der Klick-Geste aufgerufen werden: `showDirectoryPicker`
       verlangt eine frische Benutzergeste, und die laeuft in Chrome nach
       wenigen Sekunden ab. Deshalb steht dieser Aufruf VOR dem Netz-Abruf des
       Manifests - beim Auswaehlen eines VERZEICHNISSES entsteht keine
       0-Byte-Datei, anders als bei einem Speichern-Dialog. */
    function ordnerBesorgen() {
        if (_ordner) return Promise.resolve(_ordner);
        if (!kannSchreiben()) return Promise.resolve(null);
        return window.showDirectoryPicker({ id: 'jarvis-outlook-addin', mode: 'readwrite',
                                            startIn: 'documents' })
            .then(function (h) {
                return darfSchreiben(h, true).then(function (ok) {
                    if (!ok) throw new Error(T('mailadm.addin_noperm',
                        'Schreibrecht für den Ordner wurde nicht erteilt.'));
                    _ordner = h;
                    // Das Merken darf den Vorgang nicht aufhalten und auch nicht
                    // kippen: schlaegt IndexedDB fehl (privates Fenster), wird
                    // beim naechsten Mal eben noch einmal gefragt.
                    handleSchreiben(h).catch(function () { });
                    ordnerKnopf();
                    return h;
                });
            });
    }

    function schreibeInOrdner() {
        var knopf = $('em-addin-upload');
        if (!knopf || knopf.disabled) return;
        if (_adresseKaputt) {
            melde('em-addin-dl-status', T('mailadm.addin_badbase_short',
                'Adresse nicht brauchbar – zuerst die Warnung oben beheben.'), 'fehler');
            return;
        }
        var alt = knopf.textContent;
        knopf.disabled = true;
        melde('em-addin-dl-status', '');
        // ZUERST der Ordner (Benutzergeste!), dann das Manifest holen.
        ordnerBesorgen().then(function (h) {
            if (!h) throw new Error(T('mailadm.addin_nofs',
                'Dieser Browser kann nicht in einen Ordner schreiben – bitte herunterladen.'));
            knopf.textContent = T('mailadm.addin_writing', 'schreibt …');
            return fetch('/addin/manifest.xml', { cache: 'no-store' }).then(function (r) {
                if (!r.ok) {
                    return r.json().catch(function () { return {}; }).then(function (d) {
                        throw new Error((d && d.error) || ('HTTP ' + r.status));
                    });
                }
                _dateiname = dateinameAus(r.headers.get('Content-Disposition')) || _dateiname;
                zeigeDateiname();
                return r.text();
            }).then(function (xml) {
                var name = _dateiname || 'outlook-addin.xml';
                return h.getFileHandle(name, { create: true })
                    .then(function (fh) { return fh.createWritable(); })
                    .then(function (w) {
                        return w.write(xml).then(function () { return w.close(); });
                    }).then(function () { return name; });
            });
        }).then(function (name) {
            melde('em-addin-dl-status', T('mailadm.addin_written',
                '✓ „{n}" in Ordner „{o}" geschrieben.')
                .replace('{n}', name).replace('{o}', (_ordner && _ordner.name) || '?'), 'ok');
        }).catch(function (e) {
            // Ein abgebrochener Dialog ist KEIN Fehler und darf nicht als
            // solcher gemeldet werden - der Benutzer hat sich entschieden.
            if (e && (e.name === 'AbortError' || e.name === 'NotAllowedError')) {
                melde('em-addin-dl-status', '');
            } else {
                melde('em-addin-dl-status', T('common.error', 'Fehler') + ': '
                    + ((e && e.message) || e), 'fehler');
            }
        }).then(function () {
            knopf.disabled = false;
            knopf.textContent = alt;
            ordnerKnopf();
        });
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
        // Eigene Variablen, nicht `b` weiterverwenden: eine geteilte `var` sieht
        // beim Klick den ZULETZT zugewiesenen Wert (Register - in
        // email_portal.js hat genau das den Abmelde-Knopf umbeschriftet).
        var addinSave = $('em-addin-save');
        if (addinSave) addinSave.addEventListener('click', function () { speichereAddinPfad(false); });
        var addinUp = $('em-addin-upload');
        if (addinUp) addinUp.addEventListener('click', schreibeInOrdner);
        // MASSGEBLICH IST DER FELDINHALT, nicht der gespeicherte Wert: wer den
        // Pfad eintippt, sieht den Ordner-Knopf sofort - ohne erst speichern zu
        // muessen. Und wer das Feld LEERT, verliert ihn sofort wieder.
        var addinFeld = $('em-addin-pfad');
        if (addinFeld) addinFeld.addEventListener('input', ordnerKnopf);
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
            pruefeAdresse();
            // Das gemerkte Handle NUR lesen, nicht nachfragen: eine
            // Berechtigungsabfrage braucht eine Nutzergeste, und beim Oeffnen
            // des Reiters gibt es keine. Fehlt das Recht noch, wird beim Klick
            // gefragt - der Knopf traegt dann noch seinen allgemeinen Text.
            handleLesen().then(function (h) {
                if (!h) return;
                return darfSchreiben(h, false).then(function (ok) {
                    if (ok) { _ordner = h; ordnerKnopf(); }
                });
            }).catch(function () { });
        },
        _test: { zeichneKonten: zeichneKonten, zeichneExplorer: zeichneExplorer,
                 dateinameAus: dateinameAus, ordnerKnopf: ordnerKnopf,
                 feldPfad: feldPfad, ladeAddinPfad: ladeAddinPfad,
                 speichereAddinPfad: speichereAddinPfad,
                 schreibeInOrdner: schreibeInOrdner, pruefeAdresse: pruefeAdresse }
    };
})();
