/* Bereich "Claude Subagent" (/claude)
 * ───────────────────────────────────────────────────────────────────────────
 * Der Benutzer erzeugt hier seinen persoenlichen Delegations-Schluessel und
 * sieht, was seine Auftraege gemacht haben. Mehr nicht – die Auftraege selbst
 * legt Claude Code ueber /api/claude/jobs an.
 *
 * DREI FALLSTRICKE, die hier bewusst vermieden sind:
 *
 * 1. KEINE geteilte `var` mit Inline-Closures in `binde()`. Im Outlook-Add-in
 *    hat genau das dazu gefuehrt, dass ein Klick den ABMELDE-Knopf umbeschriftet
 *    hat: alle Bindungen wiesen dieselbe Variable zu, und die Closure sah beim
 *    Klick den zuletzt zugewiesenen Wert. Hier bekommt jede Bindung ihre eigene.
 *
 * 2. KEIN `applyLang()` aus einer Zeichenfunktion heraus. `applyLang()` feuert
 *    `jarvis-lang-changed` bei JEDEM Aufruf – wer darauf hoert und daraufhin neu
 *    zeichnet, baut eine Endlosschleife (Vorfall 2026-08-18 im Short-Tracks-
 *    Reiter: ueber 40 Abrufe in 250 ms, Haken liessen sich nicht setzen).
 *    Deshalb zusaetzlich der Sprachvergleich `_lang`.
 *
 * 3. Die Liste wartet NIE auf einen schmueckenden Zweitabruf. Ein Symbol, das
 *    200 ms spaeter kommt, sieht niemand – eine Liste, die nie erscheint, jeder.
 */
(function () {
    'use strict';

    // Gleiche Kette wie support.js/chatlib.js – die Bereiche teilen sich die
    // Anmeldung, und je nach Einstiegsseite liegt der Token unter einem
    // anderen Schluessel.
    var TOKEN_KEYS = ['jarvis_token', 'jarvis_chat_token', 'jarvis_uc_token'];

    var _lang = '';
    var _status = null;
    var _laeuft = false;

    function $(id) { return document.getElementById(id); }

    function token() {
        for (var i = 0; i < TOKEN_KEYS.length; i++) {
            try {
                var t = localStorage.getItem(TOKEN_KEYS[i]);
                if (t) return t;
            } catch (e) { /* Speicher gesperrt (privates Fenster) */ }
        }
        return '';
    }

    function T(key, fallback) {
        return (window.t ? window.t(key, fallback) : null) || fallback;
    }

    function sprache() {
        try { return localStorage.getItem('jarvis_lang') || 'de'; } catch (e) { return 'de'; }
    }

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    function melde(text) {
        var alt = document.querySelector('.cs-toast');
        if (alt) alt.remove();
        var d = document.createElement('div');
        d.className = 'cs-toast';
        d.textContent = text;
        document.body.appendChild(d);
        setTimeout(function () { d.remove(); }, 3200);
    }

    function hole(pfad, opt) {
        var o = opt || {};
        o.headers = o.headers || {};
        o.headers['Authorization'] = 'Bearer ' + token();
        if (o.body && !o.headers['Content-Type']) o.headers['Content-Type'] = 'application/json';
        return fetch(pfad, o);
    }

    function zeitText(sek) {
        if (!sek) return '–';
        try { return new Date(sek * 1000).toLocaleString(); } catch (e) { return String(sek); }
    }

    // ── Klapp-Zustand je Karte (wie app.js::_collapseInit) ──────────────────
    function klappInit() {
        var karten = document.querySelectorAll('.cs-card[data-klapp]');
        Array.prototype.forEach.call(karten, function (karte) {
            var name = karte.getAttribute('data-klapp');
            var kopf = karte.querySelector('.cs-card-head');
            if (!kopf) return;
            try {
                if (localStorage.getItem('jarvis_cs_zu:' + name) === '1') {
                    karte.setAttribute('data-zu', '1');
                    kopf.setAttribute('aria-expanded', 'false');
                }
            } catch (e) { /* egal */ }
            kopf.addEventListener('click', function (ev) {
                // Knoepfe in der Kopfzeile duerfen nicht zuklappen.
                if (ev.target.closest('button, input, label, a, select')) return;
                var zu = karte.getAttribute('data-zu') === '1';
                if (zu) karte.removeAttribute('data-zu');
                else karte.setAttribute('data-zu', '1');
                kopf.setAttribute('aria-expanded', zu ? 'true' : 'false');
                try { localStorage.setItem('jarvis_cs_zu:' + name, zu ? '0' : '1'); } catch (e) { /* egal */ }
            });
        });
    }

    // ── ⓘ: EIN delegierter Listener am Dokument ────────────────────────────
    // So wirkt auch jedes spaeter ergaenzte ⓘ, ohne dass es gebunden werden muss.
    function infoInit() {
        document.addEventListener('click', function (e) {
            var knopf = e.target && e.target.closest && e.target.closest('.cs-info');
            if (!knopf) return;
            e.preventDefault();
            var kasten = document.getElementById(knopf.getAttribute('data-help') || '');
            if (!kasten) return;
            var offen = kasten.classList.toggle('is-open');
            knopf.setAttribute('aria-expanded', offen ? 'true' : 'false');
        });
    }

    // ── Zeichnen ───────────────────────────────────────────────────────────
    function zeichneSchluessel() {
        var pille = $('cs-key-pill');
        var meta = $('cs-key-meta');
        var neu = $('cs-key-new');
        var del = $('cs-key-del');
        var k = _status && _status.schluessel;
        if (pille) {
            pille.textContent = k ? T('csub.pill_ok', 'Schlüssel hinterlegt')
                                  : T('csub.pill_off', 'kein Schlüssel');
            pille.className = 'cs-pill ' + (k ? 'is-ok' : 'is-off');
        }
        if (meta) {
            meta.textContent = k
                ? T('csub.key_meta', 'Endet auf …{x} · erzeugt {d} · zuletzt benutzt {l}')
                    .replace('{x}', k.letzte4 || '????')
                    .replace('{d}', zeitText(k.erstellt))
                    .replace('{l}', k.zuletzt ? zeitText(k.zuletzt) : T('csub.never', 'nie'))
                : T('csub.key_none', 'Du hast noch keinen Schlüssel erzeugt.');
        }
        if (neu) {
            neu.textContent = k ? T('csub.key_regen', 'Neuen Schlüssel erzeugen')
                                : T('csub.key_new', 'Schlüssel erzeugen');
        }
        if (del) del.hidden = !k;
    }

    function zeichneJobs() {
        var box = $('cs-jobs-list');
        var zaehler = $('cs-jobs-count');
        if (!box) return;
        var jobs = (_status && _status.jobs) || [];
        if (zaehler) zaehler.textContent = jobs.length ? '(' + jobs.length + ')' : '';
        if (!jobs.length) {
            box.innerHTML = '<div class="cs-leer">'
                + esc(T('csub.jobs_none', 'Noch keine Aufträge. Sie entstehen, sobald Claude Code eine Aufgabe abgibt.'))
                + '</div>';
            return;
        }
        var zustand = {
            wartet: T('csub.st_wait', 'wartet'),
            laeuft: T('csub.st_run', 'läuft'),
            fertig: T('csub.st_done', 'fertig'),
            fehler: T('csub.st_err', 'Fehler')
        };
        box.innerHTML = jobs.map(function (j) {
            var kurz = String(j.spec || '').split('\n')[0].slice(0, 120);
            return '<div class="cs-job">'
                + '<div class="cs-job-head">'
                + '<span class="cs-pill' + (j.status === 'fertig' ? ' is-ok' : (j.status === 'fehler' ? ' is-off' : '')) + '">'
                + esc(zustand[j.status] || j.status) + '</span>'
                + '<span class="cs-job-spec">' + esc(kurz) + '</span>'
                + '</div>'
                + '<div class="cs-job-meta">'
                + esc(T('csub.job_meta', 'Riegel {r} · {n} Datei(en) · {d}')
                    .replace('{r}', j.riegel || '–')
                    .replace('{n}', (j.dateien || []).length)
                    .replace('{d}', zeitText(j.erstellt)))
                + (j.fehler ? ' · ' + esc(String(j.fehler).slice(0, 160)) : '')
                + '</div></div>';
        }).join('');
    }

    function zeichne() {
        zeichneSchluessel();
        zeichneJobs();
        // KEIN applyLang() hier – siehe Kopfkommentar (Endlosschleife).
    }

    // ── Laden ──────────────────────────────────────────────────────────────
    function laden() {
        if (_laeuft) return Promise.resolve();
        _laeuft = true;
        // Sprache FRUEH merken, nicht erst in zeichne(): faellt der Abruf aus
        // (403, weil der Skill gerade abgeschaltet wurde), laeuft zeichne() nie
        // – und ohne gemerkte Sprache loeste jedes weitere applyLang() einen
        // neuen Fehlversuch aus.
        _lang = sprache();
        return hole('/api/claude/status').then(function (r) {
            if (r.status === 401) { location.href = '/'; return null; }
            if (r.status === 403) {
                document.body.innerHTML = '<div style="padding:40px;text-align:center;'
                    + 'font-family:var(--font-body);color:var(--text-primary)">'
                    + esc(T('csub.no_access', 'Kein Zugriff auf diesen Bereich. Ein Administrator kann dich unter Einstellungen → Sicherheit → Berechtigungen freischalten.'))
                    + '</div>';
                return null;
            }
            return r.json();
        }).then(function (d) {
            if (!d || !d.ok) return;
            _status = d;
            zeichne();
        }).catch(function () {
            var box = $('cs-jobs-list');
            if (box) box.innerHTML = '<div class="cs-leer">'
                + esc(T('csub.load_err', 'Der Bereich ist gerade nicht erreichbar.')) + '</div>';
        }).then(function () { _laeuft = false; });
    }

    // ── Aktionen ───────────────────────────────────────────────────────────
    function schluesselErzeugen() {
        var frage = _status && _status.schluessel
            ? T('csub.regen_ask', 'Einen neuen Schlüssel erzeugen? Der bisherige wird dabei sofort ungültig.')
            : null;
        if (frage && !window.confirm(frage)) return;
        hole('/api/claude/key', { method: 'POST' }).then(function (r) {
            return r.json();
        }).then(function (d) {
            if (!d || !d.ok) {
                melde(T('csub.err_generic', 'Das hat nicht geklappt.') + ' ' + ((d && d.error) || ''));
                return;
            }
            var box = $('cs-key-box');
            var wert = $('cs-key-value');
            if (wert) wert.textContent = d.schluessel;
            if (box) box.hidden = false;
            melde(T('csub.key_done', 'Schlüssel erzeugt – jetzt kopieren.'));
            laden();
        }).catch(function () {
            melde(T('csub.err_generic', 'Das hat nicht geklappt.'));
        });
    }

    function schluesselLoeschen() {
        if (!window.confirm(T('csub.del_ask', 'Schlüssel wirklich löschen? Dein Claude-Code-Werkzeug kann danach nichts mehr abgeben.'))) return;
        hole('/api/claude/key', { method: 'DELETE' }).then(function () {
            var box = $('cs-key-box');
            if (box) box.hidden = true;
            melde(T('csub.del_done', 'Schlüssel gelöscht.'));
            laden();
        }).catch(function () {
            melde(T('csub.err_generic', 'Das hat nicht geklappt.'));
        });
    }

    function schluesselKopieren() {
        var wert = $('cs-key-value');
        if (!wert || !wert.textContent) return;
        var fertig = function () { melde(T('csub.copied', 'In die Zwischenablage kopiert.')); };
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(wert.textContent).then(fertig, function () {
                melde(T('csub.copy_err', 'Kopieren nicht möglich – bitte von Hand markieren.'));
            });
        } else {
            melde(T('csub.copy_err', 'Kopieren nicht möglich – bitte von Hand markieren.'));
        }
    }

    // ── Bindung ────────────────────────────────────────────────────────────
    // Jede Bindung mit EIGENER Variable (siehe Kopfkommentar, Punkt 1).
    function binde() {
        klappInit();
        infoInit();

        var neu = $('cs-key-new');
        if (neu) neu.addEventListener('click', schluesselErzeugen);

        var del = $('cs-key-del');
        if (del) del.addEventListener('click', schluesselLoeschen);

        var kopie = $('cs-key-copy');
        if (kopie) kopie.addEventListener('click', schluesselKopieren);

        var portal = $('cs-portal-btn');
        if (portal) portal.addEventListener('click', function () { location.href = '/portal'; });

        var logout = $('cs-logout-btn');
        if (logout) logout.addEventListener('click', function () {
            if (window.jarvisLogout) { window.jarvisLogout(); return; }
            TOKEN_KEYS.forEach(function (k) {
                try { localStorage.removeItem(k); } catch (e) { /* egal */ }
            });
            location.href = '/';
        });

        // Sprachwechsel: nur neu zeichnen, wenn sich die Sprache WIRKLICH
        // geaendert hat – applyLang() feuert dieses Ereignis bei jedem Aufruf.
        window.addEventListener('jarvis-lang-changed', function () {
            var jetzt = sprache();
            if (jetzt === _lang) return;
            _lang = jetzt;
            zeichne();
        });
    }

    function start() {
        if (!token()) { location.href = '/'; return; }
        var app = $('cs-app');
        if (app) app.classList.remove('hidden');
        binde();
        laden();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start);
    } else {
        start();
    }
})();
