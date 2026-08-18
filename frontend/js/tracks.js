/* ═══════════════════════════════════════════════════════════════════
   Short Tracks (/tracks) – Benutzerseite
   ───────────────────────────────────────────────────────────────────
   Ein Brett aus Ablagen ("Dumps"). Jede traegt einen gespeicherten Prompt;
   wer eine Datei oder eine URL darauf zieht, loest ihn aus. Drei Dinge auf
   einer Seite:
     1. Das Brett – Ablagen anlegen/aendern und benutzen
     2. Die Auftraege je Ablage (live, per Abfrage-Takt)
     3. Das eigene Protokoll

   BERECHTIGUNG: jeder Endpunkt haengt serverseitig an `require_auth` und
   filtert auf den angemeldeten Benutzer. Die Pruefung hier ist reine
   Benutzerfuehrung – wer nicht angemeldet ist, soll aufs Portal statt auf
   eine Seite voller 401-Meldungen.

   WARUM EIN ABFRAGE-TAKT UND KEIN WEBSOCKET: der vorhandene /ws haengt am
   Chat-Agenten (Sitzung, Verlauf, Sidebar). Ein Dump-Lauf ist headless und
   hat damit nichts zu tun; ein zweiter WS-Kanal waere deutlich mehr Bau fuer
   dieselbe Aussage. Der Takt ist DYNAMISCH (2 s bei aktiven Auftraegen, sonst
   15 s) und ruht, wenn der Reiter im Hintergrund liegt – ein fester
   2-Sekunden-Takt auf jedem offenen Reiter waere genau das Poll-Rauschen, das
   an anderer Stelle die Untaetigkeits-Anzeige verdorben hat.
   ═══════════════════════════════════════════════════════════════════ */
(function () {
    'use strict';

    // Gleiche Schluesselkette wie email_portal.js/sap_portal.js/support.js – wer
    // ueber /chat angemeldet ist, soll sich hier nicht erneut anmelden muessen.
    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];

    var TAKT_AKTIV = 2000;
    var TAKT_RUHE = 15000;

    var _status = null;       // /api/tracks/status
    var _dumps = [];
    var _bereiche = [];
    var _bereicheLang = '';   // in welcher Sprache der Katalog geholt wurde
    var _grenzen = {};
    var _jobs = [];
    var _editId = null;       // welche Ablage ist offen ('neu' = neue Ablage)
    var _formHeim = null;     // Heimatplatz des wandernden Formulars
    var _brettLang = '';      // in welcher Sprache das Brett gezeichnet wurde
    var _dropZiel = null;     // fuer den Klick-Weg: welche Ablage hat gefragt
    var _timer = null;
    var _istAdmin = false;

    function $(id) { return document.getElementById(id); }
    function T(key, fallback) {
        var s = window.t ? window.t(key) : null;
        return (s && s !== key) ? s : fallback;
    }
    function sprache() { return (window._lang === 'en') ? 'en' : 'de'; }
    function token() {
        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            var v = localStorage.getItem(TOKEN_KEYS[i]);
            if (v) return v;
        }
        return '';
    }
    function kopf(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + token() }, extra || {});
    }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function toPortal() { window.location.replace('/portal'); }
    function zeit(ts) {
        if (!ts) return '–';
        try { return new Date(ts * 1000).toLocaleString(); } catch (e) { return '–'; }
    }
    function melde(id, text, art) {
        var e = $(id);
        if (!e) return;
        e.textContent = text || '';
        e.style.color = art === 'ok' ? 'var(--success)'
            : art === 'fehler' ? 'var(--danger)' : 'var(--text-muted)';
    }

    /* Kurze Rueckmeldung. PFLICHT, nicht Kosmetik: ein Drop erzeugt einen
       Auftrag, der erst Sekunden spaeter sichtbar wird – ohne Rueckmeldung sieht
       ein abgewiesener Drop genauso aus wie ein angenommener. */
    function toast(text, schlecht) {
        var alt = document.querySelector('.st-toast');
        if (alt) alt.remove();
        var d = document.createElement('div');
        d.className = 'st-toast' + (schlecht ? ' is-bad' : '');
        d.setAttribute('role', 'status');
        d.textContent = text;
        document.body.appendChild(d);
        setTimeout(function () { if (d.parentNode) d.remove(); }, schlecht ? 7000 : 4000);
    }

    function hole(url, opt) {
        return fetch(url, Object.assign({ headers: kopf() }, opt || {}))
            .then(function (r) {
                return r.json().catch(function () { return {}; })
                    .then(function (d) {
                        if (!r.ok || d.ok === false) {
                            var e = new Error(d.error || ('HTTP ' + r.status));
                            e.daten = d;
                            e.status = r.status;
                            throw e;
                        }
                        return d;
                    });
            });
    }
    function sende(url, methode, daten) {
        return hole(url, {
            method: methode,
            headers: kopf({ 'Content-Type': 'application/json' }),
            body: daten === undefined ? undefined : JSON.stringify(daten)
        });
    }

    /* ── Einklappbare Karten ───────────────────────────────────────────── */
    var KLAPP_KEY = 'jarvis_tracks_zu';   // Liste der ZUGEKLAPPTEN Karten

    function klappZustand() {
        try {
            var v = JSON.parse(localStorage.getItem(KLAPP_KEY) || '[]');
            return Array.isArray(v) ? v : [];
        } catch (e) { return []; }
    }
    function klappMerken(liste) {
        try { localStorage.setItem(KLAPP_KEY, JSON.stringify(liste)); } catch (e) { }
    }
    function setzeKlapp(karte, zu) {
        karte.classList.toggle('is-zu', !!zu);
        var k = karte.querySelector('.st-card-head');
        if (k) k.setAttribute('aria-expanded', zu ? 'false' : 'true');
    }
    function umschalten(karte) {
        var id = karte.getAttribute('data-klapp');
        var zu = !karte.classList.contains('is-zu');
        setzeKlapp(karte, zu);
        var liste = klappZustand().filter(function (x) { return x !== id; });
        if (zu) liste.push(id);
        klappMerken(liste);
        if (!zu && id === 'log') ladeLog();
    }
    function klappInit() {
        // Gespeichert werden die ZUGEKLAPPTEN – so ist die Vorgabe fuer einen
        // neuen Benutzer das, was im Markup steht, und eine spaeter ergaenzte
        // Karte ist nicht still versteckt.
        var zu = klappZustand();
        document.querySelectorAll('.st-card[data-klapp]').forEach(function (karte) {
            var id = karte.getAttribute('data-klapp');
            var k = karte.querySelector('.st-card-head');
            if (!k) return;
            if (zu.indexOf(id) >= 0) setzeKlapp(karte, true);
            else if (id !== 'log') setzeKlapp(karte, false);
            k.addEventListener('click', function (ev) {
                // OHNE DIESE AUSNAHME klappt jeder Knopf in der Kopfzeile die
                // Karte zu (gleiche Regel wie in email_portal.js).
                if (ev.target.closest('button, input, label, a, select, textarea')) return;
                umschalten(karte);
            });
            k.addEventListener('keydown', function (ev) {
                if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
                    ev.preventDefault();
                    umschalten(karte);
                }
            });
        });
    }

    /* ── Feld-Erklaerungen (ⓘ) ──
       EIN delegierter Listener am Dokument statt Bindung je Knopf: so wirkt
       jedes spaeter ergaenzte ⓘ automatisch, auch in nachtraeglich gezeichneten
       Bereichen (das Formular entsteht erst beim Bearbeiten). */
    function infoInit() {
        if (document._stInfoBound) return;
        document._stInfoBound = true;
        document.addEventListener('click', function (e) {
            var knopf = e.target && e.target.closest && e.target.closest('.st-info');
            if (!knopf) return;
            // preventDefault, weil ein ⓘ auch INNERHALB eines <label> sitzen
            // kann – dort wuerde der Klick sonst die Checkbox umschalten
            // (Lehre vom AD-Picker, 2026-07-29).
            e.preventDefault();
            var kasten = document.getElementById(knopf.getAttribute('data-help') || '');
            if (!kasten) return;
            var offen = kasten.classList.toggle('is-open');
            knopf.setAttribute('aria-expanded', offen ? 'true' : 'false');
        });
    }

    /* ── Status laden ──────────────────────────────────────────────────── */
    function ladeStatus() {
        return hole('/api/tracks/status?lang=' + sprache()).then(function (d) {
            _status = d;
            _dumps = d.dumps || [];
            _bereiche = d.bereiche || [];
            _bereicheLang = sprache();
            _grenzen = d.grenzen || {};
            _istAdmin = !!d.ist_admin;
            zeichneBrett();
        }).catch(function (e) {
            melde('st-board-status', e.message, 'fehler');
        });
    }

    /* ── Das Brett ─────────────────────────────────────────────────────── */
    function typenText(d) {
        var t = d.dateitypen || [];
        if (!t.length) return T('tracks.types_any', 'alle lesbaren Dateien');
        return t.map(function (x) { return '.' + x; }).join(' ');
    }

    function zeichneBrett() {
        var box = $('st-board');
        if (!box) return;
        // Formular VOR dem Neuaufbau heimholen – sonst raeumt innerHTML='' es
        // mit ab (Fallstrick der Extraktions-Vorschau in /wissen, 2026-07-28).
        formHeim();
        box.innerHTML = '';
        var leer = $('st-board-empty');
        if (leer) leer.classList.toggle('hidden', _dumps.length > 0);

        // Merker, in welcher Sprache das Brett gezeichnet wurde – der
        // Lang-Zuhoerer unten zeichnet nur bei einer echten Aenderung neu.
        _brettLang = sprache();
        _dumps.forEach(function (d) {
            var karte = document.createElement('div');
            karte.className = 'st-dump' + (d.enabled ? '' : ' is-off');
            karte.setAttribute('data-dump', d.id);
            var darfAendern = d['global'] ? _istAdmin : true;
            karte.innerHTML =
                '<div class="st-dump-head">' +
                  '<div class="st-dump-main">' +
                    '<div class="st-dump-name">' + esc(d.name) +
                      (d['global'] ? '<span class="st-badge is-global">' +
                          esc(T('tracks.badge_global', 'für alle')) + '</span>' : '') +
                      (d.enabled ? '' : '<span class="st-badge">' +
                          esc(T('tracks.badge_off', 'inaktiv')) + '</span>') +
                    '</div>' +
                    (d.beschreibung ? '<div class="st-dump-desc">' + esc(d.beschreibung) + '</div>' : '') +
                  '</div>' +
                  '<div class="st-dump-acts">' +
                    (darfAendern
                        ? '<button class="st-icon-btn" data-act="edit" title="' +
                              esc(T('tracks.edit', 'Bearbeiten')) + '">&#9998;</button>' +
                          '<button class="st-icon-btn is-danger" data-act="del" title="' +
                              esc(T('tracks.delete', 'Löschen')) + '">&#10005;</button>'
                        : '') +
                  '</div>' +
                '</div>' +
                '<div class="st-drop" data-act="drop"' +
                  (d.enabled ? ' role="button" tabindex="0"' : ' aria-disabled="true"') + '>' +
                  '<span class="st-drop-arrow" aria-hidden="true">&#10515;</span>' +
                  '<span>' + esc(d.enabled
                      ? T('tracks.drop_here', 'Dateien hier ablegen')
                      : T('tracks.drop_off', 'Inaktiv – nimmt nichts an')) + '</span>' +
                  '<span class="st-drop-types">' + esc(d.enabled ? typenText(d)
                      : T('tracks.drop_off_hint', 'zum Einschalten bearbeiten')) + '</span>' +
                '</div>' +
                '<div class="st-dump-foot">' +
                  '<textarea class="st-note" rows="1" data-act="note" data-tabfill ' +
                    'placeholder="' + esc(T('tracks.note_ph', 'Hinweis (optional)')) + '" ' +
                    'data-i18n-placeholder="tracks.note_ph"></textarea>' +
                '</div>' +
                '<div class="st-jobs hidden" data-jobs="' + esc(d.id) + '"></div>';
            box.appendChild(karte);
            bindeKarte(karte, d);
        });
        zeichneJobs();
        // DIE ZWEITE HAELFTE DES WANDERNDEN FORMULARS: heimholen allein genuegt
        // nicht – es muss auch zurueck. Ohne diese Zeilen springt ein offenes
        // Formular an den Heimatplatz, sobald das Brett neu gezeichnet wird
        // (und das tut schon `applyLang()`, weil es `jarvis-lang-changed`
        // feuert). Genau diese Haelfte fehlte bis 2026-08-11 der
        // Extraktions-Vorschau in /wissen.
        if (_editId && _editId !== 'neu') {
            var f = $('st-form');
            var ziel = document.querySelector('.st-dump[data-dump="' + _editId + '"]');
            if (f && ziel && ziel.parentNode) {
                ziel.parentNode.insertBefore(f, ziel.nextSibling);
            }
        }
    }

    function bindeKarte(karte, d) {
        var drop = karte.querySelector('[data-act="drop"]');
        var edit = karte.querySelector('[data-act="edit"]');
        var del = karte.querySelector('[data-act="del"]');
        if (edit) edit.addEventListener('click', function (e) {
            e.stopPropagation();
            formOeffnen(d.id, karte);
        });
        if (del) del.addEventListener('click', function (e) {
            e.stopPropagation();
            loescheDump(d);
        });
        // Eine abgeschaltete Ablage bekommt GAR KEINE Drop-Bindung: der Server
        // weist den Versuch mit 404 ab, und eine Flaeche, die zum Fehlgriff
        // einlaedt, ist schlechter als eine, die sichtbar nichts tut.
        if (!drop || !d.enabled) return;

        // Klick-Weg: verstecktes <input type=file>. Ohne ihn waere die Ablage
        // fuer alle unbenutzbar, die nicht ziehen koennen (Touch, Tastatur).
        drop.addEventListener('click', function () { dateiWaehlen(d); });
        drop.addEventListener('keydown', function (ev) {
            if (ev.key === 'Enter' || ev.key === ' ' || ev.key === 'Spacebar') {
                ev.preventDefault();
                dateiWaehlen(d);
            }
        });

        // dragover MUSS preventDefault rufen, sonst nimmt der Browser den Drop
        // nicht an und oeffnet die Datei stattdessen im Reiter.
        drop.addEventListener('dragover', function (ev) {
            ev.preventDefault();
            drop.classList.add('is-over');
        });
        drop.addEventListener('dragleave', function () { drop.classList.remove('is-over'); });
        drop.addEventListener('drop', function (ev) {
            ev.preventDefault();
            drop.classList.remove('is-over');
            var dt = ev.dataTransfer;
            if (!dt) return;
            if (dt.files && dt.files.length) { schickeDateien(d, dt.files); return; }
            // Kein File, aber Text: eine gezogene Adresse aus der Adresszeile
            // kommt als text/uri-list bzw. text/plain.
            var uri = '';
            try { uri = dt.getData('text/uri-list') || dt.getData('text/plain') || ''; }
            catch (e) { uri = ''; }
            uri = (uri || '').trim().split(/\s+/)[0];
            if (/^https?:\/\//i.test(uri)) { schickeUrl(d, uri); return; }
            toast(T('tracks.drop_unknown',
                'Damit kann diese Ablage nichts anfangen – erwartet werden Dateien oder eine Web-Adresse.'), true);
        });
    }

    function hinweisVon(dumpId) {
        var karte = document.querySelector('.st-dump[data-dump="' + dumpId + '"]');
        var n = karte && karte.querySelector('[data-act="note"]');
        return n ? (n.value || '') : '';
    }
    function hinweisLeeren(dumpId) {
        var karte = document.querySelector('.st-dump[data-dump="' + dumpId + '"]');
        var n = karte && karte.querySelector('[data-act="note"]');
        // Nach dem Absenden leeren: der Hinweis gehoert zu DIESEM Vorgang. Bliebe
        // er stehen, waere er beim naechsten Drop still mit dabei.
        if (n) n.value = '';
    }

    function dateiWaehlen(d) {
        var inp = $('st-file-input');
        if (!inp) return;
        _dropZiel = d;
        inp.value = '';        // sonst feuert 'change' bei derselben Datei nicht
        inp.click();
    }

    /* ── Ablegen ───────────────────────────────────────────────────────── */
    function schickeDateien(d, dateien) {
        var max = _grenzen.max_dateien || 20;
        if (dateien.length > max) {
            toast(T('tracks.too_many', 'Es sind höchstens {n} Dateien je Vorgang möglich.')
                .replace(/\{n\}/g, max), true);
            return;
        }
        var fd = new FormData();
        fd.append('dump_id', d.id);
        fd.append('hinweis', hinweisVon(d.id));
        for (var i = 0; i < dateien.length; i++) fd.append('files', dateien[i]);
        toast(T('tracks.sending', 'Wird übertragen …'));
        // KEIN Content-Type setzen: den Multipart-Rand setzt der Browser selbst.
        fetch('/api/tracks/drop', { method: 'POST', headers: kopf(), body: fd })
            .then(function (r) {
                return r.json().catch(function () { return {}; })
                    .then(function (j) { return { ok: r.ok, status: r.status, d: j }; });
            })
            .then(function (a) {
                nachDrop(d, a);
            })
            .catch(function (e) { toast(e.message, true); });
    }

    function schickeUrl(d, url) {
        toast(T('tracks.fetching', 'Seite wird geholt …'));
        sende('/api/tracks/drop_url', 'POST',
              { dump_id: d.id, url: url, hinweis: hinweisVon(d.id) })
            .then(function (j) { nachDrop(d, { ok: true, d: j }); })
            .catch(function (e) { toast(e.message, true); });
    }

    function nachDrop(d, a) {
        var j = a.d || {};
        var abgewiesen = j.abgewiesen || [];
        if (!a.ok || j.ok === false) {
            // Eine abgewiesene Datei wird BENANNT, nicht bloss gezaehlt: der
            // Benutzer muss wissen, WELCHE und WARUM.
            var text = j.error || ('HTTP ' + (a.status || '?'));
            if (abgewiesen.length) {
                text += ' – ' + abgewiesen.map(function (x) {
                    return x.name + ': ' + x.grund;
                }).join(' | ');
            }
            toast(text, true);
            return;
        }
        hinweisLeeren(d.id);
        var n = (j.jobs || []).length;
        var msg = T('tracks.queued', '{n} Auftrag/Aufträge eingereiht.').replace(/\{n\}/g, n);
        if (abgewiesen.length) {
            msg += ' ' + T('tracks.rejected', 'Nicht übernommen:') + ' ' +
                abgewiesen.map(function (x) { return x.name + ' (' + x.grund + ')'; }).join(', ');
        }
        toast(msg, abgewiesen.length > 0);
        ladeJobs();
        takt();      // sofort auf den schnellen Takt umstellen
    }

    /* ── Auftraege ─────────────────────────────────────────────────────── */
    function ladeJobs() {
        return hole('/api/tracks/jobs').then(function (d) {
            _jobs = d.jobs || [];
            zeichneJobs();
            zeichnePille(d.zaehler || {});
            // Fertige als gesehen melden – aber nur, wenn der Reiter wirklich
            // sichtbar ist. Sonst loescht ein im Hintergrund laufender Abruf den
            // Zaehler der Portal-Kachel, ohne dass jemand hingesehen hat.
            if (!document.hidden && (d.zaehler || {}).neu) {
                sende('/api/tracks/jobs/seen', 'POST').catch(function () { });
            }
        }).catch(function (e) {
            // Ein 401 heisst: Sitzung abgelaufen. Weiterpollen waere sinnlos.
            if (e.status === 401 || e.status === 403) { stopTakt(); toPortal(); }
        });
    }

    function zeichnePille(z) {
        var p = $('st-queue-pill');
        if (!p) return;
        var aktiv = z.aktiv || 0;
        p.className = 'st-pill' + (aktiv ? ' is-run' : '');
        p.textContent = aktiv
            ? T('tracks.pill_active', '{n} in Arbeit').replace(/\{n\}/g, aktiv)
            : '';
    }

    function jobZustand(j) {
        if (j.status === 'wartet') {
            return j.wartend_vor
                ? T('tracks.state_queued_pos', 'wartet (Position {n})').replace(/\{n\}/g, j.wartend_vor)
                : T('tracks.state_queued', 'wartet');
        }
        if (j.status === 'laeuft') {
            var s = (j.schritte || [])[Math.max(0, (j.schritte || []).length - 1)];
            var basis = T('tracks.state_running', 'läuft …');
            return s ? basis + ' ' + (s.werkzeug || '') : basis;
        }
        if (j.status === 'fehler') return T('tracks.state_failed', 'fehlgeschlagen');
        return T('tracks.state_done', 'fertig') +
            (j.dauer_s ? ' · ' + j.dauer_s + ' s' : '');
    }

    function zeichneJobs() {
        // Erst alle Bereiche leeren, dann fuellen: eine gerade geloeschte Ablage
        // darf keine Auftragsliste zuruecklassen.
        document.querySelectorAll('[data-jobs]').forEach(function (b) {
            b.innerHTML = '';
            b.classList.add('hidden');
        });
        _jobs.forEach(function (j) {
            var box = document.querySelector('[data-jobs="' + j.dump_id + '"]');
            if (!box) return;      // Auftrag einer inzwischen entfernten Ablage
            box.classList.remove('hidden');
            var z = document.createElement('div');
            z.className = 'st-job' + (j.status === 'laeuft' ? ' is-run' : '')
                + (j.status === 'fehler' ? ' is-bad' : '');
            var chips = (j.dateien || []).map(function (f) {
                // Das Token gehoert an den Link, nicht in gespeicherten Text:
                // <a download> kann keinen Authorization-Header setzen.
                return '<a class="st-chip" href="' + esc(f.url) +
                    (f.url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(token()) +
                    '" download><span aria-hidden="true">&#10515;</span>' + esc(f.name) + '</a>';
            }).join('');
            var letzter = (j.schritte || [])[(j.schritte || []).length - 1];
            z.innerHTML =
                '<div class="st-job-head">' +
                  '<span class="st-job-name">' + esc(j.titel) + '</span>' +
                  '<span class="st-job-state">' + esc(jobZustand(j)) + '</span>' +
                  (j.status === 'fertig' || j.status === 'fehler'
                      ? '<button class="st-icon-btn" data-jobdel="' + esc(j.id) +
                        '" title="' + esc(T('tracks.job_hide', 'Aus der Liste nehmen')) +
                        '" style="width:22px;height:22px;font-size:.7rem;">&#10005;</button>'
                      : '') +
                '</div>' +
                (j.status === 'laeuft' && letzter
                    ? '<div class="st-job-step">' + esc(T('tracks.step', 'Schritt') + ': ' +
                        (letzter.werkzeug || '')) + '</div>' : '') +
                (j.ergebnis ? '<div class="st-job-res">' + esc(j.ergebnis) + '</div>' : '') +
                (j.fehler ? '<div class="st-job-res">' + esc(j.fehler) + '</div>' : '') +
                (chips ? '<div class="st-chips">' + chips + '</div>' : '');
            box.appendChild(z);
        });
        document.querySelectorAll('[data-jobdel]').forEach(function (b) {
            b.addEventListener('click', function (e) {
                e.stopPropagation();
                var id = b.getAttribute('data-jobdel');
                hole('/api/tracks/jobs/' + encodeURIComponent(id), { method: 'DELETE' })
                    .then(ladeJobs).catch(function (er) { toast(er.message, true); });
            });
        });
    }

    /* ── Takt ──────────────────────────────────────────────────────────── */
    function stopTakt() {
        if (_timer) { clearTimeout(_timer); _timer = null; }
    }
    function takt() {
        stopTakt();
        var aktiv = _jobs.some(function (j) {
            return j.status === 'wartet' || j.status === 'laeuft';
        });
        // Im Hintergrund gar nicht abfragen: der Takt lebt fuer die Anzeige, und
        // niemand sieht sie. Bei der Rueckkehr wird sofort nachgeholt.
        var ms = document.hidden ? TAKT_RUHE * 4 : (aktiv ? TAKT_AKTIV : TAKT_RUHE);
        _timer = setTimeout(function () {
            if (document.hidden) { takt(); return; }
            ladeJobs().then(takt);
        }, ms);
    }

    /* ── Formular ──────────────────────────────────────────────────────── */
    function formHeim() {
        var f = $('st-form');
        if (!f) return;
        var heim = $('st-form-home');
        if (heim && f.parentNode !== heim) heim.appendChild(f);
    }

    function bereichKasten(d) {
        return _bereiche.map(function (b) {
            var an = (d.bereiche || ['basis']).indexOf(b.id) >= 0 || b.pflicht;
            var gesperrt = !b.freigegeben || b.pflicht;
            return '<label class="' + (gesperrt ? 'is-locked' : '') + '">' +
                '<input type="checkbox" value="' + esc(b.id) + '"' +
                (an ? ' checked' : '') + (gesperrt ? ' disabled' : '') + '>' +
                '<span><b>' + esc(b.name) + '</b>' +
                (b.pflicht ? ' <span class="st-badge">' +
                    esc(T('tracks.area_required', 'Pflicht')) + '</span>' : '') +
                (!b.freigegeben ? ' <span class="st-badge">' +
                    esc(T('tracks.area_locked', 'nicht freigegeben')) + '</span>' : '') +
                '<span class="st-area-hint">' + esc(b.hinweis) + '</span></span></label>';
        }).join('');
    }

    function formOeffnen(id, karte) {
        // Umschalter: derselbe Knopf schliesst das Formular wieder.
        if (_editId === id && $('st-form')) { formSchliessen(); return; }
        var d = (id === 'neu') ? {
            id: '', name: '', beschreibung: '', prompt: '', bereiche: ['basis'],
            dateitypen: [], mehrfach: 'einzeln', profile_id: '',
            reasoning_effort: '', max_steps: 0, enabled: true, 'global': false
        } : (_dumps.filter(function (x) { return x.id === id; })[0] || null);
        if (!d) return;
        _editId = id;
        var alt = $('st-form');
        if (alt) alt.remove();
        var f = document.createElement('div');
        f.className = 'st-form';
        f.id = 'st-form';
        f.innerHTML =
            '<div class="st-grid">' +
              '<div class="st-field">' +
                '<label data-i18n="tracks.f_name">Name der Ablage</label>' +
                '<input type="text" id="st-f-name" maxlength="' + (_grenzen.name_max || 60) + '">' +
              '</div>' +
              '<div class="st-field">' +
                '<label data-i18n="tracks.f_desc">Kurzbeschreibung (optional)</label>' +
                '<input type="text" id="st-f-desc" maxlength="' + (_grenzen.beschreibung_max || 200) + '">' +
              '</div>' +
              '<div class="st-field st-field-full">' +
                '<label><span data-i18n="tracks.f_prompt">Aufgabe</span> ' +
                  '<button type="button" class="st-info" data-help="st-help-prompt" ' +
                    'aria-expanded="false" data-i18n-title="tracks.help" title="Erklärung anzeigen">&#9432;</button>' +
                '</label>' +
                '<textarea id="st-f-prompt" data-tabfill maxlength="' + (_grenzen.prompt_max || 8000) + '" ' +
                  'placeholder="' + esc(T('tracks.f_prompt_ph',
                      'Was soll mit der abgelegten Datei geschehen? Zum Beispiel: Lies die Rechnung, prüfe Betrag und Steuersatz und erzeuge eine Excel-Zeile mit Lieferant, Datum, Netto, Steuer, Brutto.')) + '" ' +
                  'data-i18n-placeholder="tracks.f_prompt_ph"></textarea>' +
                '<div class="st-help" id="st-help-prompt" data-i18n-html="tracks.help_prompt">' +
                  'Formuliere die Aufgabe wie einen Auftrag an einen Menschen. Der Inhalt der abgelegten Datei wird automatisch beigelegt – du musst ihn nicht erwähnen. Soll eine Datei entstehen, sage welche Art (Word, Excel, PowerPoint, PDF, Diagramm).' +
                '</div>' +
              '</div>' +
              '<div class="st-field">' +
                '<label><span data-i18n="tracks.f_types">Nur diese Dateitypen</span> ' +
                  '<button type="button" class="st-info" data-help="st-help-types" ' +
                    'aria-expanded="false" data-i18n-title="tracks.help" title="Erklärung anzeigen">&#9432;</button>' +
                '</label>' +
                '<input type="text" id="st-f-types" placeholder="' +
                  esc(T('tracks.f_types_ph', 'leer = alle lesbaren')) + '" ' +
                  'data-i18n-placeholder="tracks.f_types_ph">' +
                '<div class="st-help" id="st-help-types" data-i18n="tracks.help_types">Kommagetrennt, ohne Punkt – zum Beispiel: pdf, xlsx. Eine Datei mit anderer Endung wird beim Ablegen abgewiesen, ohne einen Lauf zu starten. Leer heißt: alles, was gelesen werden kann.</div>' +
              '</div>' +
              '<div class="st-field">' +
                '<label><span data-i18n="tracks.f_multi">Mehrere Dateien</span> ' +
                  '<button type="button" class="st-info" data-help="st-help-multi" ' +
                    'aria-expanded="false" data-i18n-title="tracks.help" title="Erklärung anzeigen">&#9432;</button>' +
                '</label>' +
                '<select id="st-f-multi">' +
                  '<option value="einzeln" data-i18n="tracks.f_multi_each">Jede Datei einzeln bearbeiten</option>' +
                  '<option value="gemeinsam" data-i18n="tracks.f_multi_all">Alle gemeinsam in einem Auftrag</option>' +
                '</select>' +
                '<div class="st-help" id="st-help-multi" data-i18n="tracks.help_multi">„Einzeln" ist der Normalfall: zehn Rechnungen ergeben zehn Ergebnisse. „Gemeinsam" braucht man für Aufgaben, die nur zusammen Sinn haben – etwa zwei Verträge vergleichen. Bei vielen großen Dateien wird der Text dabei gekürzt.</div>' +
              '</div>' +
            '</div>' +
            '<div class="st-sep"></div>' +
            '<div class="st-field">' +
              '<label><span data-i18n="tracks.f_areas">Werkzeuge dieser Ablage</span> ' +
                '<button type="button" class="st-info" data-help="st-help-areas" ' +
                  'aria-expanded="false" data-i18n-title="tracks.help" title="Erklärung anzeigen">&#9432;</button>' +
              '</label>' +
              '<div class="st-areas" id="st-f-areas">' + bereichKasten(d) + '</div>' +
              '<div class="st-help" id="st-help-areas" data-i18n="tracks.help_areas">Je weniger, desto besser: der Inhalt einer abgelegten Datei kann von einem Fremden stammen. Nicht freigegebene Bereiche schaltet ein Administrator unter Einstellungen → Short Tracks frei.</div>' +
            '</div>' +
            '<div class="st-sep"></div>' +
            '<div class="st-grid st-grid-3">' +
              '<div class="st-field">' +
                '<label data-i18n="tracks.f_profile">LLM-Profil (optional)</label>' +
                '<input type="text" id="st-f-profile" placeholder="' +
                  esc(T('tracks.f_profile_ph', 'leer = wie im Chat')) + '" ' +
                  'data-i18n-placeholder="tracks.f_profile_ph">' +
              '</div>' +
              '<div class="st-field">' +
                '<label data-i18n="tracks.f_effort">Denktiefe</label>' +
                '<select id="st-f-effort">' +
                  '<option value="" data-i18n="tracks.f_effort_default">Vorgabe</option>' +
                  '<option value="off">off</option><option value="low">low</option>' +
                  '<option value="medium">medium</option><option value="high">high</option>' +
                  '<option value="max">max</option>' +
                '</select>' +
              '</div>' +
              '<div class="st-field">' +
                '<label data-i18n="tracks.f_steps">Schrittgrenze (0 = Vorgabe)</label>' +
                '<input type="number" id="st-f-steps" min="0" max="50">' +
              '</div>' +
            '</div>' +
            '<div class="st-row">' +
              '<label class="st-hint" style="display:flex;gap:6px;align-items:center;">' +
                '<input type="checkbox" id="st-f-enabled"> <span data-i18n="tracks.f_enabled">Aktiv</span>' +
              '</label>' +
              (_istAdmin && (id === 'neu')
                  ? '<label class="st-hint" style="display:flex;gap:6px;align-items:center;">' +
                    '<input type="checkbox" id="st-f-global"> <span data-i18n="tracks.f_global">Für alle Benutzer</span>' +
                    '<button type="button" class="st-info" data-help="st-help-global" aria-expanded="false" ' +
                      'data-i18n-title="tracks.help" title="Erklärung anzeigen">&#9432;</button></label>'
                  : '') +
            '</div>' +
            (_istAdmin && (id === 'neu')
                ? '<div class="st-help" id="st-help-global" data-i18n="tracks.help_global">Eine Ablage „für alle" erscheint bei jedem Benutzer. Der Lauf trägt immer die Rechte dessen, der etwas ablegt – nicht deine. Ob eine Ablage global ist, lässt sich später nicht ändern.</div>'
                : '') +
            '<div class="st-row">' +
              '<button class="st-btn st-btn-primary" id="st-f-save" data-i18n="tracks.save">Speichern</button>' +
              '<button class="st-btn" id="st-f-cancel" data-i18n="tracks.cancel">Abbrechen</button>' +
              '<span class="st-status" id="st-f-status"></span>' +
            '</div>';

        // Das Formular wandert UNTER die bearbeitete Karte – ein Formular am
        // Seitenende gehoert sichtbar zu nichts. Bei "neu" bleibt es am
        // Heimatplatz unter dem Knopf.
        if (karte && karte.parentNode) {
            karte.parentNode.insertBefore(f, karte.nextSibling);
        } else {
            var heim = $('st-form-home');
            if (heim) heim.appendChild(f);
        }

        $('st-f-name').value = d.name || '';
        $('st-f-desc').value = d.beschreibung || '';
        $('st-f-prompt').value = d.prompt || '';
        $('st-f-types').value = (d.dateitypen || []).join(', ');
        $('st-f-multi').value = d.mehrfach || 'einzeln';
        $('st-f-profile').value = d.profile_id || '';
        $('st-f-effort').value = d.reasoning_effort || '';
        $('st-f-steps').value = d.max_steps || 0;
        $('st-f-enabled').checked = d.enabled !== false;
        $('st-f-save').addEventListener('click', function () { speichere(id); });
        $('st-f-cancel').addEventListener('click', formSchliessen);
        if (window.applyLang) window.applyLang();
        // `block: 'nearest'` scrollt nur so weit wie noetig und NIE ueber die
        // Oberkante – ein `scrollTo(0, scrollHeight)` wuerde vom Formular
        // wegspringen (Fehler der Extraktions-Vorschau in /wissen, 2026-07-28).
        // Die Pruefung ist Pflicht: aeltere Umgebungen (und jsdom im Test)
        // kennen die Funktion nicht, und ein Fehler hier wuerde das fertig
        // aufgebaute Formular wieder zerreissen.
        if (f.scrollIntoView) f.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    function formSchliessen() {
        var f = $('st-form');
        if (f) f.remove();
        _editId = null;
    }

    function formStand() {
        if (!$('st-form')) return null;
        var bereiche = [];
        document.querySelectorAll('#st-f-areas input[type="checkbox"]').forEach(function (c) {
            if (c.checked) bereiche.push(c.value);
        });
        return {
            name: $('st-f-name').value.trim(),
            beschreibung: $('st-f-desc').value.trim(),
            prompt: $('st-f-prompt').value,
            dateitypen: $('st-f-types').value,
            mehrfach: $('st-f-multi').value,
            bereiche: bereiche,
            profile_id: $('st-f-profile').value.trim(),
            reasoning_effort: $('st-f-effort').value,
            max_steps: parseInt($('st-f-steps').value || '0', 10) || 0,
            enabled: $('st-f-enabled').checked
        };
    }

    function speichere(id) {
        var daten = formStand();
        if (!daten) return;
        if (!daten.name) { melde('st-f-status', T('tracks.need_name', 'Ein Name fehlt.'), 'fehler'); return; }
        if (!daten.prompt.trim()) { melde('st-f-status', T('tracks.need_prompt', 'Die Aufgabe fehlt.'), 'fehler'); return; }
        melde('st-f-status', T('tracks.saving', 'Wird gespeichert …'));
        var p;
        if (id === 'neu') {
            var g = $('st-f-global');
            if (g && g.checked) daten['global'] = true;
            p = sende('/api/tracks/dumps', 'POST', daten);
        } else {
            p = sende('/api/tracks/dumps/' + encodeURIComponent(id), 'PUT', daten);
        }
        p.then(function () {
            formSchliessen();
            return ladeStatus();
        }).then(function () {
            melde('st-board-status', T('tracks.saved', 'Gespeichert.'), 'ok');
        }).catch(function (e) {
            melde('st-f-status', e.message, 'fehler');
        });
    }

    function loescheDump(d) {
        var frage = T('tracks.del_ask', 'Ablage „{n}" wirklich löschen? Bereits erzeugte Ergebnisse bleiben erhalten.')
            .replace(/\{n\}/g, d.name);
        if (!window.confirm(frage)) return;
        hole('/api/tracks/dumps/' + encodeURIComponent(d.id), { method: 'DELETE' })
            .then(function () {
                if (_editId === d.id) formSchliessen();
                return ladeStatus();
            })
            .catch(function (e) { toast(e.message, true); });
    }

    /* ── Protokoll ─────────────────────────────────────────────────────── */
    function ladeLog() {
        var box = $('st-log');
        if (!box) return;
        box.innerHTML = '<div class="st-empty">' + esc(T('tracks.loading', 'Lädt …')) + '</div>';
        hole('/api/tracks/log?limit=50').then(function (d) {
            var e = d.eintraege || [];
            if (!e.length) {
                box.innerHTML = '<div class="st-empty">' +
                    esc(T('tracks.log_empty', 'Noch keine Läufe.')) + '</div>';
                return;
            }
            box.innerHTML = '<div class="st-scroll">' + e.map(function (x) {
                var chips = (x.dateien || []).map(function (f) {
                    return '<a class="st-chip" href="' + esc(f.url) +
                        (f.url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(token()) +
                        '" download><span aria-hidden="true">&#10515;</span>' + esc(f.name) + '</a>';
                }).join('');
                return '<div class="st-log-row' + (x.ok ? '' : ' is-bad') + '">' +
                    '<div class="st-log-head">' +
                      '<b>' + esc(x.dump || '') + '</b>' +
                      '<span>' + esc(x.titel || '') + '</span>' +
                      '<span class="st-log-time">' + esc(zeit(x.ts)) +
                        (x.dauer_s ? ' · ' + x.dauer_s + ' s' : '') + '</span>' +
                    '</div>' +
                    (x.ergebnis ? '<div class="st-log-res">' + esc(x.ergebnis) + '</div>' : '') +
                    (chips ? '<div class="st-chips">' + chips + '</div>' : '') +
                    '</div>';
            }).join('') + '</div>';
        }).catch(function (er) {
            box.innerHTML = '<div class="st-empty">' + esc(er.message) + '</div>';
        });
    }

    /* ── Start ─────────────────────────────────────────────────────────── */
    function binde() {
        klappInit();
        infoInit();
        var b;
        // Eigene Variable je Handler: `var b` wird hier mehrfach zugewiesen, und
        // eine Inline-Closure saehe beim Klick den ZULETZT zugewiesenen Wert
        // (der Fehler vom 2026-08-16 im Add-in-Fenster).
        if ((b = $('st-new-btn'))) b.addEventListener('click', function () {
            formOeffnen('neu', null);
        });
        if ((b = $('st-log-reload'))) b.addEventListener('click', ladeLog);
        if ((b = $('st-portal-btn'))) b.addEventListener('click', toPortal);
        if ((b = $('st-logout-btn'))) b.addEventListener('click', function () {
            if (window.jarvisLogout) { window.jarvisLogout(); return; }
            TOKEN_KEYS.forEach(function (k) { try { localStorage.removeItem(k); } catch (e) { } });
            window.location.replace('/');
        });
        if ((b = $('st-file-input'))) b.addEventListener('change', function () {
            if (_dropZiel && b.files && b.files.length) schickeDateien(_dropZiel, b.files);
            _dropZiel = null;
        });
        // Sprachwechsel: der Bereichskatalog kommt vom SERVER und wird von
        // applyLang() nicht erreicht – ohne diesen Zuhoerer bliebe er in der
        // Sprache, in der die Seite geladen wurde (Lehre vom 2026-08-13).
        window.addEventListener('jarvis-lang-changed', function () {
            // ACHTUNG: dieses Ereignis feuert auch bei jedem `applyLang()` –
            // also auch dann, wenn sich die Sprache NICHT geaendert hat (etwa
            // nach dem Aufbau des Formulars, das selbst applyLang ruft). Ohne
            // den Vergleich wuerde jeder solche Aufruf das Brett neu zeichnen.
            if (sprache() === _brettLang) return;
            if (_bereicheLang && _bereicheLang !== sprache()) ladeStatus();
            else zeichneBrett();
        });
        // Rueckkehr aus dem Hintergrund: sofort nachsehen statt bis zum
        // naechsten Takt zu warten.
        document.addEventListener('visibilitychange', function () {
            if (!document.hidden) { ladeJobs(); takt(); }
        });
    }

    function start() {
        if (!token()) { toPortal(); return; }
        fetch('/api/me', { headers: kopf() })
            .then(function (r) { return r.ok ? r.json() : null; })
            .then(function (d) {
                if (!d) { toPortal(); return; }
                // Fail-closed: fehlt `permissions` (aelteres Backend), gilt
                // "nicht freigegeben" – dieselbe Regel wie im SAP-Bereich.
                if (!d.permissions || !d.permissions.tracks) { toPortal(); return; }
                var app = $('st-app');
                if (app) app.classList.remove('hidden');
                binde();
                return ladeStatus().then(ladeJobs).then(takt);
            })
            .catch(function () { toPortal(); });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }

    // Fuer Tests und die Konsole
    window.jarvisTracks = {
        ladeStatus: ladeStatus, ladeJobs: ladeJobs, ladeLog: ladeLog,
        formOeffnen: formOeffnen, formSchliessen: formSchliessen,
        stop: stopTakt,
        _stand: function () { return { dumps: _dumps, jobs: _jobs, edit: _editId }; }
    };
})();
