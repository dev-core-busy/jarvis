/**
 * Einstellungen -> Fehleranalyse (nur Administratoren).
 *
 *   GET  /api/conv_log/users            Benutzer mit protokollierten Laeufen
 *   GET  /api/fehleranalyse/laeufe      Laeufe eines Benutzers + Analyse-Profil
 *   POST /api/fehleranalyse/dossier     Dossier (ohne Modell, deterministisch)
 *   POST /api/fehleranalyse/analyse     Dossier + Deutung durch das Modell des Admins
 *
 * Inhalte werden NUR per textContent gesetzt: Dossier und Analyse enthalten
 * Fremdtext (Benutzereingaben, Werkzeug-Ergebnisse, Modellausgabe).
 * Ein Fehler bleibt stehen, bis die naechste Aktion ihn ersetzt.
 * KEIN applyLang() in den Zeichenfunktionen – es feuert jarvis-lang-changed,
 * und ein Zuhoerer darauf baute die Ansicht endlos neu auf (Register).
 */
window.Fehleranalyse = (function () {
    'use strict';

    var gebunden = false;
    var laeuft = false;
    var profil = null;
    var laeufe = [];
    var lang = null;

    function $(id) { return document.getElementById(id); }

    function T(k, f, werte) {
        var v = window.t ? window.t(k) : k;
        var s = (v && v !== k) ? v : f;
        Object.keys(werte || {}).forEach(function (n) {
            s = s.split('{' + n + '}').join(String(werte[n]));
        });
        return s;
    }

    function token() {
        return window.authToken || window.JarvisSitzung.token();
    }

    function zeit(ts) {
        var d = new Date(Number(ts) * 1000);
        if (isNaN(d.getTime())) return '?';
        var l = window._lang === 'en' ? 'en-GB' : 'de-DE';
        try { return d.toLocaleString(l, { dateStyle: 'short', timeStyle: 'short' }); }
        catch (e) { return d.toISOString(); }
    }

    function fehler(text) {
        var el = $('fa-fehler');
        if (!el) return;
        el.textContent = text || '';
        el.style.display = text ? 'block' : 'none';
    }

    function status(text) {
        var el = $('fa-status');
        if (el) el.textContent = text || '';
    }

    async function hole(url, koerper) {
        var opt = { headers: { 'Authorization': 'Bearer ' + token() } };
        if (koerper !== undefined) {
            opt.method = 'POST';
            opt.headers['Content-Type'] = 'application/json';
            opt.body = JSON.stringify(koerper);
        }
        var r = await fetch(url, opt);
        var d = null;
        try { d = await r.json(); } catch (e) { d = null; }
        if (!r.ok) {
            var grund = (d && (d.error || d.detail)) || ('HTTP ' + r.status);
            throw new Error(String(grund));
        }
        return d || {};
    }

    function option(wert, text) {
        var o = document.createElement('option');
        o.value = wert;
        o.textContent = text;
        return o;
    }

    function knoepfeAktualisieren() {
        var lauf = $('fa-lauf');
        var gewaehlt = !!(lauf && lauf.value);
        var d = $('fa-dossier-btn'), a = $('fa-analyse-btn');
        if (d) d.disabled = laeuft || !gewaehlt;
        // Ohne Profil kein Modell – der Knopf ist dann gesperrt, der Hinweis sagt warum.
        if (a) a.disabled = laeuft || !gewaehlt || !(profil && profil.model);
    }

    function profilZeigen() {
        var el = $('fa-profil');
        if (!el) return;
        if (profil && profil.model) {
            el.textContent = T('fa.profil_hinweis',
                'Die Analyse läuft mit deinem Profil „{name}“ ({anbieter}, {modell}).',
                { name: profil.name || '?', anbieter: profil.provider || '?', modell: profil.model });
        } else if (profil) {
            el.textContent = T('fa.profil_fehlt', 'Für dein Konto ist kein Profil eingestellt.');
        } else {
            el.textContent = '';
        }
    }

    async function benutzerLaden() {
        var sel = $('fa-benutzer');
        if (!sel) return;
        var alt = sel.value;
        try {
            var liste = await hole('/api/conv_log/users');
            sel.textContent = '';
            sel.appendChild(option('', T('fa.benutzer_waehlen', '– Benutzer wählen –')));
            (Array.isArray(liste) ? liste : []).forEach(function (u) {
                sel.appendChild(option(u, u));
            });
            // Erst NACH dem Fuellen waehlen – an eine fehlende Option gesetzt
            // verpufft der Wert still (Register).
            if (alt && Array.prototype.some.call(sel.options, function (o) { return o.value === alt; })) {
                sel.value = alt;
            }
        } catch (e) {
            fehler(T('fa.fehler_laden', 'Konnte nicht geladen werden: {grund}', { grund: e.message }));
        }
    }

    function laeufeZeichnen() {
        var sel = $('fa-lauf');
        if (!sel) return;
        sel.textContent = '';
        if (!$('fa-benutzer') || !$('fa-benutzer').value) {
            sel.appendChild(option('', T('fa.lauf_erst_benutzer', '– zuerst Benutzer wählen –')));
            sel.disabled = true;
        } else if (!laeufe.length) {
            sel.appendChild(option('', T('fa.keine_laeufe', '– keine Läufe protokolliert –')));
            sel.disabled = true;
        } else {
            sel.appendChild(option('', T('fa.lauf_waehlen', '– Lauf wählen ({n}) –', { n: laeufe.length })));
            laeufe.forEach(function (l) {
                var aufgabe = String(l.task || '').replace(/\s+/g, ' ').trim();
                if (aufgabe.length > 80) aufgabe = aufgabe.slice(0, 80) + '…';
                var teile = [zeit(l.ts), aufgabe,
                             T('fa.schritte', '{n} Schritte', { n: l.steps == null ? '?' : l.steps })];
                if (l.error) teile.push(T('fa.lauf_fehler', 'Fehler'));
                sel.appendChild(option(String(l.id), teile.join(' · ')));
            });
            sel.disabled = false;
        }
        knoepfeAktualisieren();
    }

    async function laeufeLaden() {
        var ben = $('fa-benutzer') ? $('fa-benutzer').value : '';
        laeufe = [];
        try {
            var d = await hole('/api/fehleranalyse/laeufe?limit=50&benutzer=' + encodeURIComponent(ben));
            profil = d.profil || null;
            laeufe = Array.isArray(d.laeufe) ? d.laeufe : [];
            fehler('');
        } catch (e) {
            fehler(T('fa.fehler_laden', 'Konnte nicht geladen werden: {grund}', { grund: e.message }));
        }
        profilZeigen();
        laeufeZeichnen();
    }

    function ergebnisLeeren() {
        ['fa-analyse-box', 'fa-dossier-box'].forEach(function (id) {
            var el = $(id);
            if (el) el.hidden = true;
        });
    }

    function dossierZeigen(d) {
        var box = $('fa-dossier-box');
        if (!box) return;
        $('fa-dossier').textContent = d.dossier || '';
        var k = d.kennzahlen || {};
        $('fa-kennzahlen').textContent = T('fa.kennzahlen',
            '{journal} Journalzeilen · {sicherheit} Sicherheitsereignisse · {funde} Code-Fundstellen · {abgeschnitten} abgeschnittene Werkzeugaufrufe',
            { journal: k.journal || 0, sicherheit: k.sicherheit || 0,
              funde: k.fundstellen || 0, abgeschnitten: k.abgeschnitten || 0 });
        box.hidden = false;
    }

    function analyseZeigen(d) {
        var box = $('fa-analyse-box');
        if (!box) return;
        if (!d.analyse_ok) {
            box.hidden = true;
            fehler(T('fa.analyse_fehler', 'Die Analyse ist fehlgeschlagen: {grund}',
                     { grund: d.analyse_fehler || '?' }));
            return;
        }
        $('fa-analyse').textContent = d.analyse || '';
        var meta = T('fa.meta', 'Modell: {modell} · Profil: {profil}',
                     { modell: d.modell || '?', profil: d.profil || '?' });
        if (d.analyse_abgeschnitten) meta += ' · ' + T('fa.abgeschnitten', 'Die Antwort wurde abgeschnitten.');
        $('fa-analyse-meta').textContent = meta;
        box.hidden = false;
    }

    async function ausfuehren(mitAnalyse) {
        var lauf = $('fa-lauf');
        if (laeuft || !lauf || !lauf.value) return;
        laeuft = true;
        knoepfeAktualisieren();
        fehler('');
        ergebnisLeeren();
        status(mitAnalyse ? T('fa.laeuft_analyse', 'Das Modell analysiert …')
                          : T('fa.laeuft_dossier', 'Dossier wird zusammengestellt …'));
        var koerper = { id: lauf.value,
                        beschreibung: $('fa-beschreibung') ? $('fa-beschreibung').value : '' };
        try {
            var url = mitAnalyse
                ? '/api/fehleranalyse/analyse?lang=' + (window._lang === 'en' ? 'en' : 'de')
                : '/api/fehleranalyse/dossier';
            var d = await hole(url, koerper);
            if (mitAnalyse) analyseZeigen(d);
            dossierZeigen(d);
        } catch (e) {
            fehler(T('fa.fehler_laden', 'Konnte nicht geladen werden: {grund}', { grund: e.message }));
        } finally {
            laeuft = false;
            status('');
            knoepfeAktualisieren();
        }
    }

    async function kopieren(quelleId) {
        var text = ($(quelleId) && $(quelleId).textContent) || '';
        try {
            if (navigator.clipboard && navigator.clipboard.writeText) {
                await navigator.clipboard.writeText(text);
            } else {
                var ta = document.createElement('textarea');
                ta.value = text;
                document.body.appendChild(ta);
                ta.select();
                var ok = document.execCommand && document.execCommand('copy');
                ta.remove();
                if (!ok) throw new Error('execCommand');
            }
            status(T('fa.kopiert', 'In die Zwischenablage kopiert.'));
        } catch (e) {
            // Ein Fehler darf nicht von selbst verschwinden (Register).
            fehler(T('fa.kopieren_fehler', 'Kopieren nicht möglich – bitte von Hand kopieren.'));
        }
    }

    function binden() {
        if (gebunden) return;
        gebunden = true;
        $('fa-benutzer').addEventListener('change', function () {
            ergebnisLeeren();
            fehler('');
            laeufeLaden();
        });
        $('fa-lauf').addEventListener('change', function () {
            ergebnisLeeren();
            knoepfeAktualisieren();
        });
        $('fa-dossier-btn').addEventListener('click', function () { ausfuehren(false); });
        $('fa-analyse-btn').addEventListener('click', function () { ausfuehren(true); });
        $('fa-dossier-kopieren').addEventListener('click', function () { kopieren('fa-dossier'); });
        $('fa-analyse-kopieren').addEventListener('click', function () { kopieren('fa-analyse'); });
        // Gerenderte Texte (Optionen, Profilhinweis) folgen dem Sprachwechsel.
        // Nur bei WIRKLICH neuer Sprache – applyLang() feuert das Ereignis auch
        // ohne Wechsel (Register: Endlosschleife im Short-Tracks-Reiter).
        document.addEventListener('jarvis-lang-changed', function () {
            if (lang === window._lang) return;
            lang = window._lang;
            profilZeigen();
            laeufeZeichnen();
        });
    }

    async function onShow() {
        if (!$('settings-tab-fehleranalyse')) return;
        lang = window._lang;
        binden();
        await benutzerLaden();
        await laeufeLaden();
    }

    return { onShow: onShow };
})();
