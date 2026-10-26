/**
 * Einstellungen -> Fehleranalyse (nur Administratoren).
 *
 *   GET  /api/conv_log/users            Benutzer mit protokollierten Laeufen
 *   GET  /api/fehleranalyse/laeufe      Laeufe eines Benutzers + Analyse-Profil
 *   POST /api/fehleranalyse/dossier     Dossier (ohne Modell, deterministisch)
 *   POST /api/fehleranalyse/analyse     Dossier + Deutung durch das Modell des Admins
 *
 * Dossier und Analyse enthalten Fremdtext (Benutzereingaben, Werkzeug-
 * Ergebnisse, Modellausgabe) und sind Markdown. mdZeichnen() baut daraus
 * DOM-Knoten mit createElement + Textknoten – NIE innerHTML, deshalb kann
 * kein Fremdtext zu Markup werden. Kopiert wird der Rohtext, nicht die Anzeige.
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
    var roh = { 'fa-analyse': '', 'fa-dossier': '' };

    function $(id) { return document.getElementById(id); }

    /* ── Markdown -> DOM ──────────────────────────────────────────
     * Bewusst klein: Ueberschriften, Code-Bloecke, Listen, Zitat, Linie,
     * Tabelle, **fett**, *kursiv*, `code`. Kein '_' fuer kursiv (snake_case
     * zerfiele), keine Links (Fremdtext soll nichts anklickbar machen).
     * Ein Absatz behaelt Zeilen und Einrueckung (pre-wrap): das Dossier
     * rueckt Argumente und Ergebnisse um vier Zeichen ein, und ab vier
     * Zeichen Einrueckung ist eine Zeile auch KEIN Listenpunkt – sonst
     * wuerde ein "- …" im Werkzeug-Ergebnis zur Liste des Dossiers. */
    var MD_FENCE = /^ {0,3}(`{3,}|~{3,})/;
    var MD_KOPF = /^ {0,3}(#{1,6})\s+(.*?)\s*#*\s*$/;
    var MD_LINIE = /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/;
    var MD_UL = /^ {0,3}[-*+]\s+/;
    var MD_OL = /^ {0,3}(\d{1,9})[.)]\s+/;
    var MD_ZITAT = /^ {0,3}>\s?/;
    var MD_TRENNER = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)+\|?\s*$/;
    var MD_INLINE = /`([^`\n]+)`|\*\*(?=\S)([^\n]*?\S)\*\*|\*(?=[^\s*])([^*\n]*?[^\s*])\*(?![\w*])/g;

    function el(tag, kinder) {
        var e = document.createElement(tag);
        (kinder || []).forEach(function (k) { e.appendChild(k); });
        return e;
    }

    function inline(text) {
        var aus = [], pos = 0, m;
        var re = new RegExp(MD_INLINE.source, 'g');
        while ((m = re.exec(text)) !== null) {
            // *kursiv* nur ausserhalb von Woertern: "a*b*c" und "**" bleiben Text.
            if (m[3] !== undefined && m.index > 0 && /[\w*]/.test(text.charAt(m.index - 1))) {
                re.lastIndex = m.index + 1;
                continue;
            }
            if (m.index > pos) aus.push(document.createTextNode(text.slice(pos, m.index)));
            if (m[1] !== undefined) {
                var c = el('code');
                c.textContent = m[1];
                aus.push(c);
            } else if (m[2] !== undefined) {
                aus.push(el('strong', inline(m[2])));
            } else {
                aus.push(el('em', inline(m[3])));
            }
            pos = m.index + m[0].length;
        }
        if (pos < text.length) aus.push(document.createTextNode(text.slice(pos)));
        return aus;
    }

    function zellen(zeile) {
        var s = zeile.trim().replace(/^\|/, '').replace(/\|$/, '');
        return s.split('|').map(function (z) { return z.trim(); });
    }

    function blockStart(z, naechste) {
        return MD_FENCE.test(z) || MD_KOPF.test(z) || MD_LINIE.test(z) || MD_UL.test(z)
            || MD_OL.test(z) || MD_ZITAT.test(z)
            || (z.indexOf('|') >= 0 && naechste !== undefined && MD_TRENNER.test(naechste));
    }

    function mdZeichnen(ziel, text) {
        ziel.textContent = '';
        var z = String(text == null ? '' : text).replace(/\r\n?/g, '\n').split('\n');
        var i = 0, m, teile;
        while (i < z.length) {
            var zeile = z[i];
            if (!zeile.trim()) { i++; continue; }
            if ((m = zeile.match(MD_FENCE))) {
                var zaun = m[1];
                teile = [];
                i++;
                // Ein offener Zaun laeuft bis zum Ende – wie in CommonMark.
                while (i < z.length && !(z[i].trim().indexOf(zaun) === 0 && !z[i].trim().slice(zaun.length).trim())) {
                    teile.push(z[i++]);
                }
                i++;
                var code = el('code');
                code.textContent = teile.join('\n');
                ziel.appendChild(el('pre', [code]));
                continue;
            }
            if ((m = zeile.match(MD_KOPF))) {
                // Die Box traegt h3 – Inhalte beginnen eine Stufe darunter.
                ziel.appendChild(el('h' + Math.min(m[1].length + 3, 6), inline(m[2])));
                i++;
                continue;
            }
            if (MD_LINIE.test(zeile)) { ziel.appendChild(el('hr')); i++; continue; }
            if (MD_UL.test(zeile) || MD_OL.test(zeile)) {
                var geordnet = !MD_UL.test(zeile);
                var muster = geordnet ? MD_OL : MD_UL;
                var liste = el(geordnet ? 'ol' : 'ul');
                if (geordnet) {
                    var start = parseInt(zeile.match(MD_OL)[1], 10);
                    if (start !== 1) liste.start = start;
                }
                while (i < z.length && muster.test(z[i])) {
                    liste.appendChild(el('li', inline(z[i].replace(muster, ''))));
                    i++;
                }
                ziel.appendChild(liste);
                continue;
            }
            if (MD_ZITAT.test(zeile)) {
                teile = [];
                while (i < z.length && MD_ZITAT.test(z[i])) teile.push(z[i++].replace(MD_ZITAT, ''));
                ziel.appendChild(el('blockquote', inline(teile.join('\n'))));
                continue;
            }
            if (zeile.indexOf('|') >= 0 && i + 1 < z.length && MD_TRENNER.test(z[i + 1])) {
                var kopf = el('tr', zellen(zeile).map(function (c) { return el('th', inline(c)); }));
                var rumpf = el('tbody');
                i += 2;
                while (i < z.length && z[i].trim() && z[i].indexOf('|') >= 0) {
                    rumpf.appendChild(el('tr', zellen(z[i]).map(function (c) { return el('td', inline(c)); })));
                    i++;
                }
                ziel.appendChild(el('div', [el('table', [el('thead', [kopf]), rumpf])]));
                ziel.lastChild.className = 'fa-tabelle';
                continue;
            }
            teile = [];
            while (i < z.length && z[i].trim() && !(teile.length && blockStart(z[i], z[i + 1]))) {
                teile.push(z[i++]);
            }
            ziel.appendChild(el('p', inline(teile.join('\n'))));
        }
    }

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
        roh['fa-dossier'] = d.dossier || '';
        mdZeichnen($('fa-dossier'), roh['fa-dossier']);
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
        roh['fa-analyse'] = d.analyse || '';
        mdZeichnen($('fa-analyse'), roh['fa-analyse']);
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
        // Der Rohtext, nicht die Anzeige: textContent haette **, # und ``` verloren.
        var text = roh[quelleId] || '';
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
