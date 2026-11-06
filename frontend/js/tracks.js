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
    var TOKEN_KEYS = window.JarvisSitzung.tokenSchluessel();

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
    var _refZiel = null;      // fuer den Referenz-Upload: welche Ablage
    var _timer = null;
    var _istAdmin = false;

    function $(id) { return document.getElementById(id); }
    function T(key, fallback) {
        var s = window.t ? window.t(key) : null;
        return (s && s !== key) ? s : fallback;
    }
    function sprache() { return (window._lang === 'en') ? 'en' : 'de'; }
    /* Abruf-Schluessel statt Sitzungstoken in ?token= (frontend/js/dlkey.js).
       Rueckfall auf das Sitzungstoken nur, solange das Modul fehlt oder der
       Schluessel noch unterwegs ist – sonst waere ein Bild/Download tot. */
    function _dlk() {
        return (window.JarvisDL && window.JarvisDL.schluessel())
            || window.JarvisSitzung.token();
    }

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

    /* ── Maximieren ────────────────────────────────────────────────────────
       Seit 2026-09-28 EIN Knopf fuer die ganze Seite oben rechts ueber den
       Karten (Vorbild /wissen, Logik in `seite_breit.js`) – kein Vollbild
       einer einzelnen Karte mehr. Hier ist dafuer nichts zu tun. */

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
    // Das Einstellungs-Zahnrad wird NICHT hier eingeblendet, sondern zentral von
    // `settings_btn.js` aus `/api/me`. Grund: es hing an `ist_admin` aus
    // `/api/tracks/status`, und dieser Abruf antwortet fuer einen Administrator
    // OHNE Bereichs-Freigabe mit 403 – der Knopf fehlte damit genau dann, wenn
    // er gebraucht wird, denn die Freigabe wird in den Einstellungen gepflegt.
    // `_istAdmin` bleibt: es steuert, wer GLOBALE Ablagen aendern darf.

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
    function groesseText(b) {
        b = Number(b) || 0;
        if (b < 1024) return b + ' B';
        if (b < 1024 * 1024) return Math.round(b / 1024) + ' KB';
        return (b / (1024 * 1024)).toFixed(1).replace('.', sprache() === 'de' ? ',' : '.') + ' MB';
    }

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
                    // Referenzen NUR mit Namen: wer fragt, soll wissen, worauf
                    // sich seine Frage beziehen kann. Den Inhalt gibt es hier
                    // nicht (kein Download, siehe main.py).
                    ((d.referenzen || []).length
                        ? '<div class="st-dump-refs" data-refs-zeile>' +
                              esc(T('tracks.refs_on_card', 'Referenzen:')) + ' ' +
                              esc((d.referenzen || []).map(function (r) { return r.name; }).join(', ')) +
                          '</div>'
                        : '') +
                  '</div>' +
                  '<div class="st-dump-acts">' +
                    // Zuruecksetzen darf JEDER, der die Ablage benutzt – er
                    // raeumt ausschliesslich seine EIGENEN Auftraege. Deshalb
                    // ausserhalb von `darfAendern`.
                    '<button class="st-icon-btn" data-act="reset" title="' +
                        esc(T('tracks.reset', 'Zurücksetzen – Läufe dieser Ablage verwerfen')) +
                        '">&#10227;</button>' +
                    (darfAendern
                        ? '<button class="st-icon-btn" data-act="edit" title="' +
                              esc(T('tracks.edit', 'Bearbeiten')) + '">' + JarvisIcons.pencil() + '</button>' +
                          // MUELLEIMER = LOESCHEN (Regel in js/icons.js). Hier
                          // verschwindet die Ablage dauerhaft aus der Registry –
                          // ein × waere "schliessen" und damit falsch.
                          '<button class="st-icon-btn is-danger" data-act="del" title="' +
                              esc(T('tracks.delete', 'Löschen')) + '">' +
                              JarvisIcons.trash() + '</button>'
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
                // Fragefeld: nur, wenn die Ablage es eingeschaltet hat UND aktiv
                // ist – eine abgeschaltete nimmt nichts an (404), also auch
                // keine Frage (gleiche Regel wie die Drop-Flaeche).
                ((d.fragen && d.enabled)
                    ? '<div class="st-ask">' +
                          '<textarea class="st-note st-ask-text" rows="2" data-act="ask-text" ' +
                            'maxlength="' + (_grenzen.frage_max || 4000) + '" ' +
                            'placeholder="' + esc(T('tracks.ask_ph', 'Frage stellen …')) + '" ' +
                            'data-i18n-placeholder="tracks.ask_ph" ' +
                            'aria-label="' + esc(T('tracks.ask_ph', 'Frage stellen …')) + '"></textarea>' +
                          '<button type="button" class="st-btn st-btn-primary" data-act="ask">' +
                            esc(T('tracks.ask_btn', 'Fragen')) + '</button>' +
                      '</div>'
                    : '') +
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
        // Die Referenzliste im offenen Formular kommt aus `_dumps` – nach jedem
        // Neuladen (Upload, Loeschen, Sprachwechsel) neu zeichnen, sonst zeigt
        // sie den Stand von vorher.
        if (_editId && $('st-f-refs')) zeichneRefs();
    }

    /* Alle EIGENEN Auftraege dieser Ablage verwerfen – zurueck auf Anfang.

       Rueckfrage NUR, wenn gerade etwas laeuft oder wartet: dann wird ein Lauf
       wirklich abgebrochen. Ist die Ablage ohnehin fertig, waere eine
       Bestaetigung nur ein Klick mehr fuer nichts. */
    function resetDump(d) {
        var aktiv = _jobs.filter(function (j) {
            return j.dump_id === d.id &&
                   (j.status === 'wartet' || j.status === 'laeuft');
        }).length;
        if (aktiv && !window.confirm(T('tracks.reset_ask',
                'Es läuft noch ein Auftrag dieser Ablage. Wirklich abbrechen und zurücksetzen?'))) {
            return;
        }
        sende('/api/tracks/dumps/' + encodeURIComponent(d.id) + '/reset', 'POST')
            .then(function (r) {
                toast(T('tracks.reset_done', 'Zurückgesetzt – {n} Lauf/Läufe entfernt.')
                    .replace(/\{n\}/g, r.entfernt || 0));
                return ladeJobs();
            })
            .catch(function (er) { toast(er.message, true); });
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
        var res = karte.querySelector('[data-act="reset"]');
        if (res) res.addEventListener('click', function (e) {
            e.stopPropagation();
            resetDump(d);
        });
        var ask = karte.querySelector('[data-act="ask"]');
        var askText = karte.querySelector('[data-act="ask-text"]');
        if (ask && askText) {
            ask.addEventListener('click', function (e) {
                e.stopPropagation();
                stelleFrage(d, askText, ask);
            });
            // Enter sendet, Umschalt+Enter macht eine neue Zeile – wie im Chat.
            // `isComposing`: waehrend einer Eingabehilfe (Umlaute per IME)
            // bestaetigt Enter das Zeichen, nicht die Frage.
            askText.addEventListener('keydown', function (ev) {
                if (ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) {
                    ev.preventDefault();
                    stelleFrage(d, askText, ask);
                }
            });
        }
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

    /* ── Fragen ────────────────────────────────────────────────────────────
       Eine Frage ist ein Lauf wie ein Drop – nur ohne Datei. Die Referenzen
       der Ablage legt der Server bei. Das Feld wird erst nach der ANNAHME
       geleert: bei einem Fehler bleibt die Frage stehen und muss nicht neu
       getippt werden. */
    function stelleFrage(d, feld, knopf) {
        var frage = (feld.value || '').trim();
        if (!frage) {
            toast(T('tracks.ask_empty', 'Bitte zuerst eine Frage eingeben.'), true);
            return;
        }
        var max = _grenzen.frage_max || 4000;
        if (frage.length > max) {
            toast(T('tracks.ask_too_long', 'Die Frage ist zu lang (höchstens {n} Zeichen).')
                .replace(/\{n\}/g, max), true);
            return;
        }
        if (knopf) knopf.disabled = true;
        toast(T('tracks.ask_sending', 'Frage wird gestellt …'));
        sende('/api/tracks/ask', 'POST', { dump_id: d.id, frage: frage })
            .then(function () {
                feld.value = '';
                toast(T('tracks.ask_queued', 'Frage eingereiht – die Antwort erscheint unter der Ablage.'));
                // ERST laden, DANN den Takt waehlen: `takt()` entscheidet an
                // `_jobs`, ob gerade etwas laeuft. Vor dem Laden kennt es den
                // neuen Auftrag nicht und waehlt den Ruhetakt (15 s) – die Karte
                // zeigte dann "laeuft …" fuer einen Lauf, der nach 3 s fertig
                // war (im Browser auf DEV gesehen, 2026-11-06).
                ladeJobs().then(takt);
            })
            .catch(function (e) { toast(e.message, true); })
            .then(function () { if (knopf) knopf.disabled = false; });
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
        // Sofort auf den schnellen Takt – aber erst NACH dem Laden, sonst
        // entscheidet takt() an der alten Liste (Begruendung in stelleFrage).
        ladeJobs().then(takt);
    }

    /* ── Ergebnistext als formatierter Text ────────────────────────────────
       Die Antwort ist Markdown (Tabellen, SQL-Bloecke, Listen) und stand bis
       2026-11-06 als ROHTEXT auf der Karte – `|---|` und ```-Zaeune inklusive.
       Gerendert wird mit DEM Renderer des Projekts (chatlib.js, wie Chat, SAP
       und Support): er maskiert HTML und haengt Tokens nur an eigene Pfade.

       ACHTUNG: EXTERNE BILDER WERDEN ENTFERNT, BEVOR SIE LADEN KOENNEN. Die CSP
       erlaubt `img-src https:`, und auf /tracks ist Fremdinhalt der Normalfall
       (eine zugesandte Rechnung, ein Dokument aus dem Netz). Eine praeparierte
       Datei koennte das Modell zu `![x](https://fremd/?d=<Inhalt>)` bringen –
       allein das ANZEIGEN der Karte truege den Inhalt dann nach aussen, ohne
       Klick. Deshalb wird in ein `<template>` gerendert (dessen Inhalt ist
       inaktiv, der Browser laedt dort nichts), dort wird jedes Bild ausser
       eigenen Pfaden und data:-Bildern ersetzt, und ERST DANN kommt der Inhalt
       ins Dokument. Ein Filter NACH dem Einfuegen kaeme zu spaet: der Abruf
       beginnt beim Einfuegen. Links bleiben – sie wirken erst auf einen Klick.

       Diagramm-/Schaubild-Bloecke (```chartjs, ```mermaid) werden als Code
       gezeigt: deren Zeichenmodule laedt diese Seite nicht, der Renderer
       erzeugte sonst einen LEEREN Platzhalter und der Inhalt waere weg. */
    var _ZEICHEN_ZAUN = /```(?:chartjs|jarvis-chart|chart|mermaid|mmd)\b/gi;

    function setzeErgebnis(el, text) {
        if (!el) return;
        var lib = window.JarvisChatLib;
        if (!lib || !lib.renderMarkdown || !('content' in document.createElement('template'))) {
            el.textContent = text || '';      // Rueckfall: Rohtext wie bisher
            return;
        }
        var tpl = document.createElement('template');
        tpl.innerHTML = lib.renderMarkdown(String(text || '').replace(_ZEICHEN_ZAUN, '```text'));
        tpl.content.querySelectorAll('img').forEach(function (img) {
            var src = img.getAttribute('src') || '';
            // Eigener Pfad (`/api/…`, aber NICHT `//host` – das ist eine fremde
            // Adresse ohne Schema) oder ein eingebettetes data:-Bild.
            if (/^\/(?!\/)/.test(src) || /^data:image\//i.test(src)) return;
            var ersatz = document.createElement('span');
            ersatz.className = 'st-img-weg';
            ersatz.textContent = '[' + T('tracks.img_blocked', 'Bild von fremder Adresse ausgeblendet') +
                (img.getAttribute('alt') ? ': ' + img.getAttribute('alt') : '') + ']';
            img.parentNode.replaceChild(ersatz, img);
        });
        el.classList.add('is-md');
        el.appendChild(tpl.content);
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
                    (f.url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(_dlk()) +
                    '" download><span aria-hidden="true">&#10515;</span>' + esc(f.name) + '</a>';
            }).join('');
            var letzter = (j.schritte || [])[(j.schritte || []).length - 1];
            z.innerHTML =
                '<div class="st-job-head">' +
                  // Eine Frage traegt ihre Frage als Titel – die Marke sagt,
                  // dass hier keine Datei bearbeitet wurde.
                  (j.art === 'frage'
                      ? '<span class="st-badge st-job-art">' + esc(T('tracks.job_question', 'Frage')) + '</span>'
                      : '') +
                  '<span class="st-job-name">' + esc(j.titel) + '</span>' +
                  '<span class="st-job-state">' +
                    // Der drehende Kreis nur, solange wirklich gearbeitet wird –
                    // ein wartender Auftrag arbeitet nicht.
                    (j.status === 'laeuft'
                        ? '<span class="st-spin" aria-hidden="true" style="animation-delay:-'
                          + (Date.now() % 800) + 'ms"></span>'
                        : '') +
                    esc(jobZustand(j)) + '</span>' +
                  (j.status === 'fertig' || j.status === 'fehler'
                      ? '<button class="st-icon-btn" data-jobdel="' + esc(j.id) +
                        '" title="' + esc(T('tracks.job_hide', 'Aus der Liste nehmen')) +
                        // × ist hier RICHTIG: der Auftrag wird nur aus der
                        // Anzeige genommen, das Protokoll bleibt (siehe
                        // `job_entfernen`). Kein dauerhaftes Loeschen.
                        '" style="width:22px;height:22px;font-size:.7rem;">&#10005;</button>'
                      : '') +
                '</div>' +
                (j.status === 'laeuft' && letzter
                    ? '<div class="st-job-step">' + esc(T('tracks.step', 'Schritt') + ': ' +
                        (letzter.werkzeug || '')) + '</div>' : '') +
                // Inhalt erst nach dem Aufbau, ueber setzeErgebnis (Bildfilter).
                (j.ergebnis ? '<div class="st-job-res" data-ergebnis></div>' : '') +
                (j.fehler ? '<div class="st-job-res">' + esc(j.fehler) + '</div>' : '') +
                (chips ? '<div class="st-chips">' + chips + '</div>' : '');
            if (j.ergebnis) setzeErgebnis(z.querySelector('[data-ergebnis]'), j.ergebnis);
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
            reasoning_effort: '', max_steps: 0, enabled: true, 'global': false,
            fragen: false, referenzen: []
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
            // ── Fragen und Referenzen ──
            '<div class="st-field">' +
              '<label class="st-hint" style="display:flex;gap:6px;align-items:center;">' +
                '<input type="checkbox" id="st-f-fragen"> <span data-i18n="tracks.f_fragen">Fragefeld anzeigen (Fragen ohne Datei)</span>' +
                '<button type="button" class="st-info" data-help="st-help-fragen" aria-expanded="false" ' +
                  'data-i18n-title="tracks.help" title="Erklärung anzeigen">&#9432;</button>' +
              '</label>' +
              '<div class="st-help" id="st-help-fragen" data-i18n="tracks.help_fragen">Auf der Ablage erscheint ein Eingabefeld. Eine Frage dort startet die Aufgabe ohne Datei – die Aufgabe gibt den Rahmen vor (etwa „Beantworte Fragen zum Datenbankschema und schreibe dazu SQL für PostgreSQL"), die Frage sagt, was diesmal gesucht ist. Die Referenzdateien liegen jeder Frage bei.</div>' +
            '</div>' +
            '<div class="st-field" style="margin-top:10px;">' +
              '<label><span data-i18n="tracks.f_refs">Referenzdateien</span> ' +
                '<button type="button" class="st-info" data-help="st-help-refs" ' +
                  'aria-expanded="false" data-i18n-title="tracks.help" title="Erklärung anzeigen">&#9432;</button>' +
              '</label>' +
              '<div class="st-help" id="st-help-refs" data-i18n-html="tracks.help_refs">' +
                'Feste Unterlagen dieser Ablage, zum Beispiel ein Datenbankschema. Sie liegen <b>jedem Lauf</b> bei – beim Ablegen einer Datei ebenso wie bei einer Frage. Eine Datei mit demselben Namen ersetzt die alte.' +
                '<ul><li><b>Wer die Ablage benutzen darf, erfährt den Inhalt der Referenzen</b> – über seine Fragen. Lege nur ab, was alle Benutzer dieser Ablage sehen dürfen.</li>' +
                '<li>Große Dateien werden im Auftrag gekürzt; der Rest bleibt über die Datei erreichbar.</li></ul>' +
              '</div>' +
              '<div class="st-refs" id="st-f-refs"></div>' +
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
              // Der Haken steht beim ANLEGEN *und* beim BEARBEITEN – die
              // Sichtbarkeit laesst sich seit 2026-09-10 umstellen. Nur fuer
              // Administratoren: eine eigene Ablage "fuer alle" zu machen ist
              // ihre Entscheidung, und eine globale kann ein Nicht-Admin
              // ohnehin nicht bearbeiten (`darfAendern`).
              (_istAdmin
                  ? '<label class="st-hint" style="display:flex;gap:6px;align-items:center;">' +
                    '<input type="checkbox" id="st-f-global"> <span data-i18n="tracks.f_global">Für alle Benutzer</span>' +
                    '<button type="button" class="st-info" data-help="st-help-global" aria-expanded="false" ' +
                      'data-i18n-title="tracks.help" title="Erklärung anzeigen">&#9432;</button></label>'
                  : '') +
            '</div>' +
            (_istAdmin
                ? '<div class="st-help" id="st-help-global" data-i18n="tracks.help_global">Eine Ablage „für alle" erscheint bei jedem Benutzer. Der Lauf trägt immer die Rechte dessen, der etwas ablegt – nicht deine. Der Haken lässt sich später umstellen: Wegnehmen macht die Ablage wieder zu deiner eigenen und entzieht sie allen anderen. Bereits erzeugte Ergebnisse bleiben ihnen erhalten.</div>'
                : '') +
            '<div class="st-row">' +
              '<button class="st-btn st-btn-primary" id="st-f-save" data-i18n="tracks.save">Speichern</button>' +
              // ZWISCHEN Speichern und Abbrechen (Vorgabe des Nutzers). Der
              // Knopf uebernimmt `st-btn`, damit er sich in die Zeile einreiht
              // statt aufzufallen; die Wirkung steckt im delegierten Listener
              // von prompt_check.js - das Formular wird bei jedem Oeffnen neu
              // aus diesem String gebaut, ein direkt gebundener Handler waere
              // danach weg.
              (window.JarvisPromptCheck
                  ? window.JarvisPromptCheck.knopfHtml('st-f-prompt', 'tracks', 'st-btn')
                  : '') +
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
        // Vorbelegen ist Pflicht, nicht Kosmetik: ein leerer Haken an einer
        // Ablage, die "fuer alle" IST, wuerde beim naechsten Speichern als
        // "privatisieren" gelesen – der Benutzer nimmt sie allen weg, ohne es
        // gewollt zu haben.
        var gv = $('st-f-global');
        if (gv) gv.checked = !!d['global'];
        $('st-f-fragen').checked = !!d.fragen;
        zeichneRefs();
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

    /* ── Referenzdateien im Formular ────────────────────────────────────────
       Hochladen und Loeschen wirken SOFORT, nicht erst mit „Speichern": eine
       Datei ist kein Formularfeld, und ein „Abbrechen", das einen schon
       uebertragenen Upload still verwirft, waere eine falsche Zusage. Bei einer
       NEUEN Ablage gibt es noch keine Kennung, an der die Dateien haengen
       koennten – dann steht dort ein Hinweis statt des Knopfs. */
    function zeichneRefs() {
        var box = $('st-f-refs');
        if (!box) return;
        if (!_editId || _editId === 'neu') {
            box.innerHTML = '<div class="st-hint">' + esc(T('tracks.refs_after_save',
                'Referenzdateien lassen sich hinzufügen, sobald die Ablage gespeichert ist.')) + '</div>';
            return;
        }
        var d = _dumps.filter(function (x) { return x.id === _editId; })[0] || {};
        var refs = d.referenzen || [];
        var max = _grenzen.max_referenzen || 10;
        box.innerHTML =
            (refs.length
                ? '<ul class="st-ref-list">' + refs.map(function (r) {
                      return '<li><span class="st-ref-name">' + esc(r.name) + '</span>' +
                          '<span class="st-ref-size">' + esc(groesseText(r.groesse)) + '</span>' +
                          // MUELLEIMER = LOESCHEN: die Datei ist danach weg.
                          '<button type="button" class="st-icon-btn is-danger" data-refdel="' + esc(r.name) +
                          '" title="' + esc(T('tracks.refs_del', 'Referenz löschen')) + '" aria-label="' +
                          esc(T('tracks.refs_del', 'Referenz löschen')) + '">' + JarvisIcons.trash() + '</button></li>';
                  }).join('') + '</ul>'
                : '<div class="st-hint">' + esc(T('tracks.refs_none', 'Noch keine Referenzdateien.')) + '</div>') +
            '<div class="st-row">' +
              '<button type="button" class="st-btn" id="st-f-ref-add"' + (refs.length >= max ? ' disabled' : '') + '>' +
                esc(T('tracks.refs_add', '+ Referenzdatei hinzufügen')) + '</button>' +
              '<span class="st-status">' + esc(T('tracks.refs_limit', 'höchstens {n} Dateien, je {mb} MB')
                  .replace(/\{n\}/g, max).replace(/\{mb\}/g, _grenzen.ref_max_mb || 10)) + '</span>' +
              '<span class="st-status" id="st-f-ref-status"></span>' +
            '</div>';
        var add = $('st-f-ref-add');
        if (add) add.addEventListener('click', function () {
            var inp = $('st-ref-input');
            if (!inp) return;
            _refZiel = _editId;
            inp.value = '';
            inp.click();
        });
        box.querySelectorAll('[data-refdel]').forEach(function (b) {
            b.addEventListener('click', function () { loescheRef(_editId, b.getAttribute('data-refdel')); });
        });
    }

    function nachRefAenderung(id) {
        // Nur die Ablagen neu holen; das offene Formular behaelt seine
        // ungespeicherten Eingaben (zeichneBrett setzt es an seinen Platz zurueck).
        // zeichneBrett() zeichnet dabei auch die Referenzliste neu.
        return ladeStatus();
    }

    function schickeRefs(id, dateien) {
        if (!id || !dateien || !dateien.length) return;
        var fd = new FormData();
        for (var i = 0; i < dateien.length; i++) fd.append('files', dateien[i]);
        melde('st-f-ref-status', T('tracks.refs_uploading', 'Wird hochgeladen …'));
        fetch('/api/tracks/dumps/' + encodeURIComponent(id) + '/refs',
              { method: 'POST', headers: kopf(), body: fd })
            .then(function (r) {
                return r.json().catch(function () { return {}; })
                    .then(function (j) { return { ok: r.ok, status: r.status, d: j }; });
            })
            .then(function (a) {
                var j = a.d || {};
                var abgewiesen = (j.abgewiesen || []).map(function (x) {
                    return x.name + ': ' + x.grund;
                }).join(' | ');
                return nachRefAenderung(id).then(function () {
                    if (!a.ok || j.ok === false) {
                        melde('st-f-ref-status', (j.error || ('HTTP ' + a.status)) +
                              (abgewiesen ? ' – ' + abgewiesen : ''), 'fehler');
                        return;
                    }
                    melde('st-f-ref-status', T('tracks.refs_done', '{n} Datei(en) übernommen.')
                        .replace(/\{n\}/g, (j.uebernommen || []).length) +
                        (abgewiesen ? ' ' + T('tracks.refs_rejected', 'Nicht übernommen:') + ' ' + abgewiesen : ''),
                        abgewiesen ? 'fehler' : 'ok');
                });
            })
            .catch(function (e) { melde('st-f-ref-status', e.message, 'fehler'); });
    }

    function loescheRef(id, name) {
        if (!window.confirm(T('tracks.refs_del_ask', 'Referenz „{n}" wirklich löschen?')
                .replace(/\{n\}/g, name))) return;
        hole('/api/tracks/dumps/' + encodeURIComponent(id) + '/refs/' + encodeURIComponent(name),
             { method: 'DELETE' })
            .then(function () { return nachRefAenderung(id); })
            .then(function () { melde('st-f-ref-status', T('tracks.refs_deleted', 'Referenz gelöscht.'), 'ok'); })
            .catch(function (e) { melde('st-f-ref-status', e.message, 'fehler'); });
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
            enabled: $('st-f-enabled').checked,
            fragen: $('st-f-fragen').checked
        };
    }

    function speichere(id) {
        var daten = formStand();
        if (!daten) return;
        if (!daten.name) { melde('st-f-status', T('tracks.need_name', 'Ein Name fehlt.'), 'fehler'); return; }
        if (!daten.prompt.trim()) { melde('st-f-status', T('tracks.need_prompt', 'Die Aufgabe fehlt.'), 'fehler'); return; }
        melde('st-f-status', T('tracks.saving', 'Wird gespeichert …'));
        // Den Haken gibt es nur fuer Administratoren. Fehlt er, wird `global`
        // NICHT gesendet – und der Server laesst die Sichtbarkeit dann
        // unveraendert. Wer den Wert hier auf `false` vorbelegen wuerde, machte
        // aus jedem Speichern eines Nicht-Admins ein Privatisieren.
        var g = $('st-f-global');
        if (g) daten['global'] = !!g.checked;
        var p;
        if (id === 'neu') {
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
            box.innerHTML = '<div class="st-scroll">' + e.map(function (x, idx) {
                var chips = (x.dateien || []).map(function (f) {
                    return '<a class="st-chip" href="' + esc(f.url) +
                        (f.url.indexOf('?') >= 0 ? '&' : '?') + 'token=' + encodeURIComponent(_dlk()) +
                        '" download><span aria-hidden="true">&#10515;</span>' + esc(f.name) + '</a>';
                }).join('');
                return '<div class="st-log-row' + (x.ok ? '' : ' is-bad') + '">' +
                    '<div class="st-log-head">' +
                      '<b>' + esc(x.dump || '') + '</b>' +
                      '<span>' + esc(x.titel || '') + '</span>' +
                      '<span class="st-log-time">' + esc(zeit(x.ts)) +
                        (x.dauer_s ? ' · ' + x.dauer_s + ' s' : '') + '</span>' +
                    '</div>' +
                    (x.ergebnis ? '<div class="st-log-res" data-log-ergebnis="' + idx + '"></div>' : '') +
                    (chips ? '<div class="st-chips">' + chips + '</div>' : '') +
                    '</div>';
            }).join('') + '</div>';
            box.querySelectorAll('[data-log-ergebnis]').forEach(function (el) {
                var x = e[+el.getAttribute('data-log-ergebnis')];
                if (x) setzeErgebnis(el, x.ergebnis);
            });
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
        // Eigene Variable: `b` wird oben weiter zugewiesen (Closure-Falle vom
        // 2026-08-16, siehe Kommentar am Anfang von binde()).
        var refInp = $('st-ref-input');
        if (refInp) refInp.addEventListener('change', function () {
            if (_refZiel && refInp.files && refInp.files.length) schickeRefs(_refZiel, refInp.files);
            _refZiel = null;
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
            if (!document.hidden) { ladeJobs().then(takt); }
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
