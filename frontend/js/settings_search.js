/* Jarvis – Suchfeld im Kopf der Einstellungen (Vorbild: Android-Systemeinstellungen).
 *
 * Der Benutzer tippt, und pro Tastendruck erscheinen Vorschlaege; ein Klick
 * fuehrt zum passenden Konfigurationspunkt.
 *
 * ⚠ DER SUCHRAUM SIND DIE GANZEN EINSTELLUNGEN – Reiter, Abschnitte,
 * Feldbeschriftungen UND die Skills samt ihren Konfigurationsfeldern.
 *
 * ⚠ HIER STAND BIS 2026-09-20 „DER SUCHRAUM SIND DIE SKILLS", mit der
 * Begruendung, ein Feld im Kopf der GANZEN Einstellungen wecke sonst eine
 * Erwartung, die es nicht einloest. Die Erwartung war berechtigt: gemeldet
 * wurde „Eingabe ldap findet nichts" – und „ldap" steht in der Abschnitts-
 * Ueberschrift „Berechtigungen (lokal und Active Directory / LDAP)" im Reiter
 * Sicherheit, also ausserhalb des damaligen Suchraums. Das Ziel der Vorgabe
 * lautete „schnell zu einem passenden Konfigurationspunkt", nicht „zu einem
 * Skill". Den Suchraum zu NENNEN war richtig; ihn so eng zu ziehen nicht.
 *
 * ⚠ DIE OBERFLAECHE WIRD AUS DEM LEBENDEN DOM GELESEN, NICHT AUS EINER LISTE.
 * Eine gepflegte Liste waere an dem Tag unvollstaendig, an dem jemand einen
 * Reiter ergaenzt – und die fehlende Zeile meldet sich nicht (siehe
 * baueOberflaeche).
 *
 * ⚠ WOHIN EIN TREFFER FUEHRT, ENTSCHEIDET NICHT DIESE DATEI.
 * Das beantwortet `window.skillManager.zielFuer()` / `.zumKonfigurationspunkt()`
 * in skills.js – dieselbe Regel, die das Zahnrad in der Skill-Liste benutzt.
 * Eine zweite Fassung hier haette die Reiterzuordnung (SKILL_TABS) nachgebaut,
 * und beim naechsten neuen Reiter fuehrte die Suche woandershin als das
 * Zahnrad daneben, ohne dass es jemand erklaeren koennte.
 *
 * Bedienung wie im Vorbild /portal → „Angemeldete Benutzer" (sessions.js):
 * Eingabefeld, darunter ein abgesetztes Panel, Escape leert erst den Begriff
 * und schliesst erst beim zweiten Druck.
 */
(function () {
    'use strict';

    // Hoechstens so viele Vorschlaege. Eine Liste, durch die man scrollen muss,
    // ist keine Abkuerzung mehr; wer mehr braucht, tippt ein Wort dazu.
    // ⚠ DIE GESAMTZAHL STEHT TROTZDEM IM FUSS: eine gekuerzte Liste, die ihre
    // Kuerzung verschweigt, haelt der Benutzer fuer den ganzen Bestand
    // (dieselbe Regel wie bei cron_list und der Vorfallsliste).
    var MAX_TREFFER = 12;

    // Ab wann gesucht wird. Ein einzelner Buchstabe trifft fast alles und
    // waere kein Vorschlag, sondern die ganze Liste.
    var MIN_ZEICHEN = 2;

    // Gewichte. Ein Treffer im NAMEN ist etwas anderes als einer im Fliesstext
    // eines Hilfetextes – ohne Abstufung stuende ein zufaellig passendes Wort
    // aus einer Beschreibung vor dem Skill, der genauso heisst.
    var G_TITEL = 100, G_KENNUNG = 80, G_SKILL = 60, G_KAT = 40,
        G_WERKZEUG = 25, G_TEXT = 12, G_HILFE = 5;

    var els = {};
    var _bound = false;
    var _index = null;       // gebauter Suchindex (null = noch nicht geladen)
    var _laedt = null;       // laufender Aufbau
    var _treffer = [];
    var _gesamt = 0;         // Treffer VOR der Kuerzung auf MAX_TREFFER
    var _aktiv = -1;         // Tastatur-Auswahl (-1 = keine)
    var _laufNr = 0;         // gegen Wettlaeufe beim Nachladen
    var _fehlteSkills = false;   // Skill-Abruf ausgefallen (Fuss sagt es)

    function t(k, d) { return (window.t && window.t(k)) || d; }

    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }

    // ── Normierung ──────────────────────────────────────────────────────────
    //
    // „email" soll „E-Mail" finden, „loeschen" auch „löschen". Verglichen wird
    // deshalb auf einer gefalteten Fassung: kleingeschrieben, ohne Akzente,
    // ohne Satz- und Leerzeichen.
    //
    // ⚠ GEFALTET WIRD NUR SATZ- UND LEERRAUM, NICHT „alles ausser [a-z0-9]".
    // Ein Skillname in einer anderen Schrift haette sonst einen leeren
    // Heuhaufen und waere NIEMALS auffindbar – und eine Eingabe in jener
    // Schrift ergaebe eine leere Nadel, also eine stille Sackgasse.
    function istTrenner(z) {
        var k = z.charCodeAt(0);
        if (k <= 32) return true;                      // Steuerzeichen + Leerzeichen
        if (k >= 33 && k <= 47) return true;           // ! " # $ % & ' ( ) * + , - . /
        if (k >= 58 && k <= 64) return true;           // : ; < = > ? @
        if (k >= 91 && k <= 96) return true;           // [ \ ] ^ _ `
        if (k >= 123 && k <= 126) return true;         // { | } ~
        if (k === 0xa0) return true;                   // geschuetztes Leerzeichen
        if (k >= 0x2010 && k <= 0x205e) return true;   // typografische Satzzeichen
        if (k === 0xab || k === 0xbb || k === 0xb7 || k === 0x2022 || k === 0xb0) return true;
        return false;
    }

    // Liefert { s, map }: `s` ist die gefaltete Fassung, `map[i]` die Position
    // des Zeichens im ORIGINAL. Ohne diese Abbildung liesse sich ein Treffer
    // nicht hervorheben – „email" traefe in „E-Mail" die Zeichen 0..5, und das
    // weiss nur, wer beim Falten mitgezaehlt hat.
    function falte(roh) {
        var txt = String(roh == null ? '' : roh);
        var out = '', map = [];
        for (var i = 0; i < txt.length; i++) {
            var z = txt.charAt(i);
            if (istTrenner(z)) continue;
            // ⚠ 'ß' ist KEIN diakritisches Zeichen und zerfaellt bei NFD nicht.
            var teil = (z === 'ß' || z === 'ẞ')
                ? 'ss'
                : (z.normalize ? z.normalize('NFD') : z);
            teil = teil.toLowerCase();
            for (var k = 0; k < teil.length; k++) {
                var c = teil.charAt(k), code = c.charCodeAt(0);
                if (code >= 0x300 && code <= 0x36f) continue;   // kombinierende Marke
                out += c;
                map.push(i);
            }
        }
        return { s: out, map: map };
    }

    // ── Index ───────────────────────────────────────────────────────────────

    function feld(text, gewicht, istTitel) {
        var n = falte(text);
        if (!n.s) return null;
        return { n: n, g: gewicht, titel: !!istTitel };
    }

    function kuerze(s, max) {
        var txt = String(s == null ? '' : s).replace(/\s+/g, ' ').trim();
        return txt.length > max ? txt.slice(0, max - 1) + '…' : txt;
    }

    function baueIndex(skills) {
        var raus = [];
        (skills || []).forEach(function (s) {
            if (!s || s.error) return;
            var dirName = s.dir_name
                || String(s.path || '').split('/').pop()
                || s.name;
            if (!dirName) return;
            var name = s.name || dirName;
            // Kein Flag = Altbestand; dann entscheidet enabled (dieselbe Regel
            // wie in skills.js::_renderInstalled).
            var installiert = (s.installed !== undefined) ? s.installed : s.enabled;

            var felderSkill = [
                feld(name, G_TITEL, true),
                feld(s.name_en, G_TITEL, true),
                feld(dirName, G_KENNUNG, false),
                feld(s.category, G_KAT, false),
                feld((s.tools || []).join(' '), G_WERKZEUG, false),
                feld(s.description, G_TEXT, false),
                feld(s.description_en, G_TEXT, false),
                feld(s.help && s.help.details, G_HILFE, false),
            ].filter(Boolean);

            raus.push({
                art: 'skill',
                dirName: dirName,
                skill: s,
                titel: name,
                zusatz: kuerze(s.description || '', 90),
                installiert: !!installiert,
                aus: !!installiert && !s.enabled,
                felder: felderSkill,
            });

            // Konfigurationsfelder als EIGENE Treffer. Das ist der Kern der
            // Aufgabe: „wo stelle ich den Token ein?" fuehrt nicht zu „Jira",
            // sondern zu „Personal Access Token (PAT)" UNTER Jira.
            var schema = s.config_schema || {};
            Object.keys(schema).forEach(function (key) {
                var f = schema[key] || {};
                var label = f.label || key;
                raus.push({
                    art: 'feld',
                    dirName: dirName,
                    skill: s,
                    titel: label,
                    zusatz: kuerze(f.description || '', 90),
                    skillName: name,
                    installiert: !!installiert,
                    aus: !!installiert && !s.enabled,
                    felder: [
                        feld(label, G_TITEL, true),
                        feld(key, G_KENNUNG, false),
                        feld(name, G_SKILL, false),
                        feld(s.name_en, G_SKILL, false),
                        feld(f.description, G_TEXT, false),
                    ].filter(Boolean),
                });
            });
        });
        return raus;
    }

    // ── Index: die OBERFLAECHE ──────────────────────────────────────────────
    //
    // ⚠ GELESEN WIRD DAS LEBENDE DOM, NICHT EINE GEPFLEGTE LISTE.
    // `settings.html` liegt beim Oeffnen des Modals vollstaendig im Dokument.
    // Eine Namensliste im Code waere an dem Tag unvollstaendig, an dem jemand
    // einen Reiter, einen Abschnitt oder ein Feld ergaenzt - und die fehlende
    // Zeile meldet sich nicht, sie laesst den Punkt nur unauffindbar. Aus dem
    // DOM gelesen faellt jeder kuenftige Punkt von selbst hinein.
    // (`app.js::_SETTINGS_SECTIONS` kennt genau ZWEI der 41 Abschnitte - genau
    // deshalb wird sie hier nicht benutzt.)
    //
    // Die Struktur ist regelmaessig und damit eine EIGENSCHAFT, keine Konvention
    // im Einzelfall:
    //   Reiter    .settings-tab-btn[data-settings-tab]  ->  #settings-tab-<X>
    //   Abschnitt .kb-collapse-header > h3              +   #<id>-body
    //   Feld      <label> darin
    function baueOberflaeche(bekannteSkills) {
        var raus = [];
        var d = document;
        if (!d || !d.querySelectorAll) return raus;

        // Reiter, die zu einem Skill gehoeren, ueberspringen: jener steht
        // bereits als Skill-Eintrag im Index und fuehrt ueber dieselbe Regel
        // (skills.js) dorthin. Zwei gleichnamige Zeilen waeren Rauschen - und
        // der Benutzer koennte nicht erklaeren, warum es „Jira" zweimal gibt.
        var ausSkill = bekannteSkills || {};

        function reiterVon(el) {
            var p = el;
            while (p && p !== d.body) {
                var id = p.id || '';
                if (id.indexOf('settings-tab-') === 0) return id.slice(13);
                p = p.parentNode;
            }
            return '';
        }

        // ⚠ EIN VERSTECKTER REITER IST KEIN ZIEL. Reiter abgeschalteter Skills
        // tragen `display:none`; ein Treffer dorthin fuehrte zu einem Knopf,
        // den man nicht sehen und nicht druecken kann.
        var knoepfe = {};
        var alle = d.querySelectorAll('.settings-tab-btn[data-settings-tab]');
        for (var i = 0; i < alle.length; i++) {
            var b = alle[i];
            var tab = b.getAttribute('data-settings-tab') || '';
            if (!tab || b.style.display === 'none') continue;
            var nam = (b.textContent || '').replace(/\s+/g, ' ').trim();
            if (!nam) continue;
            if (!knoepfe[tab]) knoepfe[tab] = nam;       // erster gewinnt
            if (ausSkill[tab]) continue;
            raus.push({
                art: 'reiter', el: b, reiter: tab, reiterName: nam,
                titel: nam, zusatz: '', installiert: true, aus: false,
                felder: [feld(nam, G_TITEL, true), feld(tab, G_KENNUNG, false)].filter(Boolean),
            });
        }

        function reiterName(tab) { return knoepfe[tab] || tab; }

        // Abschnitte
        var gesehen = {};
        var hdrs = d.querySelectorAll('.kb-collapse-header');
        for (var k = 0; k < hdrs.length; k++) {
            var hdr = hdrs[k];
            var tab2 = reiterVon(hdr);
            if (!tab2 || !knoepfe[tab2]) continue;      // Reiter versteckt
            var h3 = hdr.querySelector('h3, h4, .kb-section-title');
            var titel = ((h3 ? h3.textContent : hdr.textContent) || '')
                .replace(/\s+/g, ' ').trim();
            if (!titel || titel.length < 2) continue;
            raus.push({
                art: 'abschnitt', el: hdr, reiter: tab2, reiterName: reiterName(tab2),
                abschnitt: titel, titel: titel, zusatz: '',
                installiert: true, aus: false,
                felder: [feld(titel, G_TITEL, true), feld(reiterName(tab2), G_KAT, false)].filter(Boolean),
            });
            gesehen[tab2 + '\u0000' + falte(titel).s] = true;
        }

        // Beschriftungen einzelner Einstellungen
        var labs = d.querySelectorAll('label');
        var dop = {};
        for (var m = 0; m < labs.length; m++) {
            var lab = labs[m];
            var tab3 = reiterVon(lab);
            if (!tab3 || !knoepfe[tab3]) continue;
            // ⚠ BESCHRIFTUNG UND ERLAEUTERUNG TRENNEN - sonst steht als „Titel"
            // eine ganze Zeile Fliesstext da („Admin-Benutzer – Benutzernamen
            // kommagetrennt, z.B. …"), und die Trefferliste ist unlesbar.
            // Die Bauform ist regelmaessig: das ERSTE Element-Kind mit Text ist
            // die Beschriftung, alles Weitere erlaeutert sie (meist ein <span>
            // in `--text-muted`). Der Rest geht als `zusatz` mit - er bleibt
            // DURCHSUCHBAR („kommagetrennt" ist ein legitimer Suchbegriff), nur
            // ist er kein Titel.
            var teile = [], roh = '';
            for (var c = 0; c < lab.childNodes.length; c++) {
                var kn = lab.childNodes[c];
                if (kn.nodeType === 3) {
                    roh += kn.nodeValue;
                } else if (kn.nodeType === 1 && /^(SPAN|B|STRONG|I|EM|CODE|SMALL)$/.test(kn.tagName)) {
                    if (roh.trim()) { teile.push(roh.trim()); roh = ''; }
                    teile.push((kn.textContent || '').replace(/\s+/g, ' ').trim());
                }
                // <input>, <select> und Gleiches tragen keinen Text und werden
                // uebersprungen - bei einem Kaestchen steht die Beschriftung
                // dahinter, nicht darin.
            }
            if (roh.trim()) teile.push(roh.trim());
            teile = teile.filter(function (x) { return x.length > 0; });
            if (!teile.length) continue;

            function saeubere(x) {
                return x.replace(/\s+/g, ' ').trim()
                        .replace(/^[–—-]\s*/, '').replace(/[:：]\s*$/, '');
            }
            var txt = saeubere(teile[0]);
            var erlaeuterung = saeubere(teile.slice(1).join(' '));
            if (txt.length < 3 || txt.length > 90) continue;

            var absEl = lab.closest ? lab.closest('.kb-collapse-body') : null;
            var absName = '';
            if (absEl && absEl.id) {
                var hEl = d.getElementById(absEl.id.replace(/-body$/, '-hdr'));
                var hh = hEl && hEl.querySelector ? hEl.querySelector('h3, h4') : null;
                if (hh) absName = (hh.textContent || '').replace(/\s+/g, ' ').trim();
            }
            // Eine Beschriftung, die genauso heisst wie ihr Abschnitt, ist
            // keine zweite Aussage.
            var schl = tab3 + '\u0000' + (absName || '') + '\u0000' + falte(txt).s;
            if (dop[schl] || gesehen[tab3 + '\u0000' + falte(txt).s]) continue;
            dop[schl] = true;

            raus.push({
                art: 'einstellung', el: lab, reiter: tab3, reiterName: reiterName(tab3),
                abschnitt: absName, titel: txt, zusatz: kuerze(erlaeuterung, 70),
                installiert: true, aus: false,
                felder: [
                    feld(txt, G_TITEL, true),
                    feld(erlaeuterung, G_TEXT, false),
                    feld(absName, G_KAT, false),
                    feld(reiterName(tab3), G_KAT, false),
                ].filter(Boolean),
            });
        }
        return raus;
    }

    // ── Suche ───────────────────────────────────────────────────────────────

    function worteAus(q) {
        return String(q || '').split(/\s+/)
            .map(function (w) { return falte(w).s; })
            .filter(function (w) { return w.length > 0; });
    }

    // Alle Vorkommen eines Wortes in einem Feld, umgerechnet auf
    // Original-Koordinaten (fuer die Hervorhebung).
    function stellen(f, wort) {
        var raus = [], von = 0, p;
        while ((p = f.n.s.indexOf(wort, von)) >= 0) {
            raus.push([f.n.map[p], f.n.map[p + wort.length - 1] + 1]);
            von = p + 1;
        }
        return raus;
    }

    // ⚠ ALLE Worte muessen vorkommen (UND). „jira token" soll das Token-Feld
    // UNTER Jira finden und nicht jeden Eintrag, in dem irgendwo „jira" steht.
    function bewerte(eintrag, worte) {
        var punkte = 0, markierungen = [];
        for (var i = 0; i < worte.length; i++) {
            var w = worte[i], best = 0, gefunden = false;
            for (var j = 0; j < eintrag.felder.length; j++) {
                var f = eintrag.felder[j];
                var p = f.n.s.indexOf(w);
                if (p < 0) continue;
                gefunden = true;
                // Ein Treffer am ANFANG des Feldes zaehlt mehr: wer „jir" tippt,
                // meint „Jira" und nicht einen Hilfetext, in dem das Wort in der
                // Mitte steht.
                //
                // ⚠ DER BONUS MUSS UNTER DER NAECHSTEN STUFE BLEIBEN – deshalb
                // 1,2 und nicht 2. Am ECHTEN Bestand gemessen: mit Faktor 2
                // schlug der Anfang eines SCHWAECHEREN Feldes den Treffer im
                // staerksten. Der Schluessel `token_praefix` (80 × 2 = 160)
                // stand vor der Beschriftung „Personal Access Token (PAT)"
                // (100) – also vor genau dem Konfigurationspunkt, den man
                // sucht. Mit 1,2 bleibt die Stufenfolge streng:
                // 120 > 100 > 96 > 80 > 72 > 60 > …
                var wert = f.g * (p === 0 ? 1.2 : 1);
                if (wert > best) best = wert;
                if (f.titel) markierungen = markierungen.concat(stellen(f, w));
            }
            if (!gefunden) return null;
            punkte += best;
        }
        return { punkte: punkte, markierungen: markierungen };
    }

    function suche(q) {
        var worte = worteAus(q);
        if (!worte.length || !_index) { _treffer = []; _gesamt = 0; return; }
        var alle = [];
        for (var i = 0; i < _index.length; i++) {
            var b = bewerte(_index[i], worte);
            if (!b) continue;
            alle.push({
                e: _index[i],
                punkte: b.punkte,
                // Ein nicht installierter Skill ist ein Konfigurationspunkt,
                // den es noch nicht gibt – er steht hinter den vorhandenen.
                rang: _index[i].installiert ? 0 : 1,
                mark: b.markierungen,
            });
        }
        alle.sort(function (a, b2) {
            if (a.rang !== b2.rang) return a.rang - b2.rang;
            if (b2.punkte !== a.punkte) return b2.punkte - a.punkte;
            return a.e.titel.localeCompare(b2.e.titel, undefined, { sensitivity: 'base' });
        });
        _gesamt = alle.length;
        _treffer = alle.slice(0, MAX_TREFFER);
    }

    // ── Anzeige ─────────────────────────────────────────────────────────────

    function markiere(text, mark) {
        var txt = String(text == null ? '' : text);
        if (!mark || !mark.length) return esc(txt);
        var s = mark.slice().sort(function (a, b) { return a[0] - b[0]; });
        var zus = [], akt = s[0].slice();
        for (var i = 1; i < s.length; i++) {
            if (s[i][0] <= akt[1]) { if (s[i][1] > akt[1]) akt[1] = s[i][1]; }
            else { zus.push(akt); akt = s[i].slice(); }
        }
        zus.push(akt);
        var out = '', pos = 0;
        for (var j = 0; j < zus.length; j++) {
            out += esc(txt.slice(pos, zus[j][0]))
                + '<mark class="st-such-mark">' + esc(txt.slice(zus[j][0], zus[j][1])) + '</mark>';
            pos = zus[j][1];
        }
        return out + esc(txt.slice(pos));
    }

    function pfadVon(e) {
        var skills = t('settings.tab.skills', 'Skills');
        if (e.art === 'feld') return skills + ' › ' + e.skillName;
        if (e.art === 'skill') return skills;
        // ⚠ DER PFAD IST BEI DER OBERFLAECHE KEINE ZIERDE, SONDERN DIE
        // UNTERSCHEIDUNG: „Aktiv" gibt es in einem Dutzend Abschnitten, und
        // ohne „Reiter › Abschnitt" waeren die Zeilen nicht auseinanderzuhalten.
        if (e.art === 'einstellung') {
            return e.abschnitt ? e.reiterName + ' › ' + e.abschnitt : e.reiterName;
        }
        if (e.art === 'abschnitt') return e.reiterName;
        return e.reiterName || '';
    }

    function zeichne() {
        if (!els.liste) return;
        var q = els.feld ? els.feld.value : '';
        var kurz = worteAus(q).join('').length < MIN_ZEICHEN;

        if (kurz) { schliessePanel(); return; }

        if (!_index) {
            els.liste.innerHTML = '<div class="st-such-leer">'
                + esc(t('stsuche.loading', 'Lade Skills…')) + '</div>';
            els.hinweis.textContent = t('stsuche.scope', 'Durchsucht Reiter, Abschnitte, Felder und Skills.');
            oeffnePanel();
            return;
        }

        suche(q);
        _aktiv = _treffer.length ? 0 : -1;

        if (!_treffer.length) {
            // ⚠ DIE LEERMELDUNG NENNT DEN SUCHRAUM. „Kein Treffer" allein liesse
            // den Benutzer glauben, es gaebe die Einstellung nirgends.
            els.liste.innerHTML = '<div class="st-such-leer">'
                + esc(t('stsuche.none', 'Kein Treffer für „{q}“ in den Einstellungen.')
                        .replace('{q}', q.trim()))
                + '</div>';
        } else {
            els.liste.innerHTML = _treffer.map(function (tr, i) {
                var e = tr.e;
                var marken = '';
                if (!e.installiert) {
                    marken += '<span class="st-such-marke is-neu">'
                        + esc(t('stsuche.not_installed', 'nicht installiert')) + '</span>';
                } else if (e.aus) {
                    marken += '<span class="st-such-marke">'
                        + esc(t('skills.disabled', 'Deaktiviert')) + '</span>';
                }
                var zus = e.zusatz ? ' · ' + esc(e.zusatz) : '';
                // ⚠ MARKE NEBEN DEM TITEL, NICHT DARIN: der Titel kuerzt mit
                // Ellipse (`white-space: nowrap`), eine Marke IM Titel wuerde
                // bei einem langen Feldnamen mit abgeschnitten – und gerade
                // „nicht installiert" ist die Aussage, auf die es ankommt.
                return '<div class="st-such-item' + (i === _aktiv ? ' is-aktiv' : '') + '"'
                    + ' id="st-such-opt-' + i + '" role="option" data-i="' + i + '"'
                    + ' aria-selected="' + (i === _aktiv ? 'true' : 'false') + '">'
                    + '<span class="st-such-kopf">'
                    + '<span class="st-such-titel">' + markiere(e.titel, tr.mark) + '</span>'
                    + marken
                    + '</span>'
                    + '<span class="st-such-pfad">' + esc(pfadVon(e)) + zus + '</span>'
                    + '</div>';
            }).join('');
        }

        // Suchraum IMMER nennen, und die Kuerzung beziffern.
        var fuss = t('stsuche.scope', 'Durchsucht Reiter, Abschnitte, Felder und Skills.');
        // ⚠ EIN FEHLENDER TEIL WIRD BENANNT, NICHT VERSCHWIEGEN: sonst haelt
        // der Benutzer die halbe Liste fuer den ganzen Bestand (dieselbe Regel
        // wie bei cron_list und der Vorfallsliste).
        if (_fehlteSkills) {
            fuss = t('stsuche.no_skills', 'Ohne die Skill-Liste – es wurde nur in der Oberfläche gesucht.')
                + ' ' + fuss;
        }
        if (_gesamt > _treffer.length) {
            fuss = t('stsuche.more', '{n} von {g} Treffern – tippe ein Wort mehr.')
                .replace('{n}', _treffer.length).replace('{g}', _gesamt) + ' ' + fuss;
        }
        els.hinweis.textContent = fuss;
        oeffnePanel();
        aktivZeigen();
    }

    function aktivZeigen() {
        if (!els.liste) return;
        var opts = els.liste.querySelectorAll('.st-such-item');
        for (var i = 0; i < opts.length; i++) {
            var an = (i === _aktiv);
            opts[i].classList.toggle('is-aktiv', an);
            opts[i].setAttribute('aria-selected', an ? 'true' : 'false');
            if (an && typeof opts[i].scrollIntoView === 'function') {
                opts[i].scrollIntoView({ block: 'nearest' });
            }
        }
        if (els.feld) {
            if (_aktiv >= 0 && opts.length) els.feld.setAttribute('aria-activedescendant', 'st-such-opt-' + _aktiv);
            else els.feld.removeAttribute('aria-activedescendant');
        }
    }

    function offen() { return els.panel && !els.panel.hasAttribute('hidden'); }

    function oeffnePanel() {
        if (!els.panel) return;
        els.panel.removeAttribute('hidden');
        if (els.feld) els.feld.setAttribute('aria-expanded', 'true');
    }

    function schliessePanel() {
        if (!els.panel) return;
        els.panel.setAttribute('hidden', '');
        if (els.feld) {
            els.feld.setAttribute('aria-expanded', 'false');
            els.feld.removeAttribute('aria-activedescendant');
        }
        _aktiv = -1;
    }

    // ── Daten ───────────────────────────────────────────────────────────────

    function laden() {
        if (_laedt) return _laedt;
        var nr = ++_laufNr;
        var holen = (typeof window.jarvisSkillsOnce === 'function')
            ? window.jarvisSkillsOnce()
            : Promise.reject(new Error('kein Skills-Abruf'));
        _laedt = Promise.resolve(holen).then(function (liste) {
            if (nr !== _laufNr) return;           // inzwischen verworfen
            var skillTeil = baueIndex(liste);
            // Welche Reiter gehoeren einem Skill? Nur so laesst sich der
            // doppelte Eintrag vermeiden, ohne eine Zuordnung nachzubauen.
            var vonSkill = {};
            skillTeil.forEach(function (e) {
                if (e.art === 'skill' && e.dirName) vonSkill[e.dirName] = true;
            });
            _index = baueOberflaeche(vonSkill).concat(skillTeil);
            _fehlteSkills = false;
            _laedt = null;
            zeichne();
        }).catch(function () {
            if (nr !== _laufNr) return;
            // ⚠ FAIL-OPEN: der Skill-Abruf ist NICHT die Bedingung der Suche.
            // „ldap" steht im Reiter Sicherheit und hat mit Skills nichts zu
            // tun - faellt der Abruf aus, waere eine tote Suche die schlechtere
            // Halbfehlerstellung als eine, der ein Teil fehlt. Der Fuss sagt,
            // dass etwas fehlt; verschwiegen wird es nicht.
            _index = baueOberflaeche({});
            _fehlteSkills = true;
            _laedt = null;
            zeichne();
        });
        return _laedt;
    }

    // Der Bestand kann sich aendern (Skill ein/aus, hinzugefuegt). Der Index
    // wird deshalb beim Schliessen verworfen und beim naechsten Oeffnen neu
    // gebaut – window.jarvisSkillsOnce haelt die Antwort ohnehin nur 5 s.
    function verwerfen() { _index = null; _laufNr++; _laedt = null; }

    // ── Ziel ────────────────────────────────────────────────────────────────

    // Fuehrt zu einem Punkt der OBERFLAECHE: Reiter aktivieren, jeden
    // zugeklappten Vorfahren aufklappen, hinspringen und kurz hervorheben.
    //
    // ⚠ AUFGEKLAPPT WIRD NUR, WAS WIRKLICH ZU IST: ein blindes click() auf die
    // Kopfzeile klappte einen offenen Abschnitt ZU - also genau das Gegenteil.
    // Geklickt wird der vorhandene Kopfzeilen-Handler, damit der gemerkte
    // Zustand mitgeschrieben wird (dieselbe Regel wie in app.js und skills.js).
    function zumElement(e) {
        var tb = null, alle = document.querySelectorAll('.settings-tab-btn[data-settings-tab]');
        for (var i = 0; i < alle.length; i++) {
            if (alle[i].getAttribute('data-settings-tab') === e.reiter) { tb = alle[i]; break; }
        }
        if (tb && tb.style.display !== 'none') tb.click();

        var el = e.el;
        if (!el || e.art === 'reiter') return true;

        // Von AUSSEN nach INNEN aufklappen - ein Abschnitt kann in einem
        // anderen liegen, und ein Handler koennte die Sichtbarkeit pruefen.
        var kette = [], p = el.parentNode;
        while (p && p.nodeType === 1 && p !== document.body) {
            if (p.classList && p.classList.contains('kb-collapse-body')
                && p.style.display === 'none' && p.id) kette.unshift(p);
            p = p.parentNode;
        }
        kette.forEach(function (body) {
            var hdr = document.getElementById(body.id.replace(/-body$/, '-hdr'));
            if (hdr) hdr.click();
        });
        // Der Treffer SELBST ist bei einem Abschnitt die Kopfzeile: sie
        // aufzuklappen ist der Sinn des Klicks.
        if (e.art === 'abschnitt' && el.id) {
            var eig = document.getElementById(el.id.replace(/-hdr$/, '-body'));
            if (eig && eig.style.display === 'none') el.click();
        }

        // Erst im naechsten Frame springen: das Aufklappen aendert die Hoehen
        // darueber, eine Messung davor zeigt auf die alte Position.
        var spaeter = window.requestAnimationFrame || function (cb) { return setTimeout(cb, 0); };
        spaeter(function () {
            try {
                if (el.scrollIntoView) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
            } catch (x) { /* kein Sprung - der Reiter steht trotzdem richtig */ }
        });
        // Die Hervorhebung ist eine ANTWORT auf den Klick („hier ist er"),
        // kein Zustand - sie verfaellt wieder.
        el.classList.add('st-such-treffer');
        setTimeout(function () { el.classList.remove('st-such-treffer'); }, 2600);
        return true;
    }

    function waehle(i) {
        var tr = _treffer[i];
        if (!tr) return;
        var e = tr.e;
        beenden();
        if (e.art === 'reiter' || e.art === 'abschnitt' || e.art === 'einstellung') {
            zumElement(e);
            return;
        }
        var sm = window.skillManager;
        if (sm && typeof sm.zumKonfigurationspunkt === 'function') {
            sm.zumKonfigurationspunkt(e.dirName);
            return;
        }
        // Rueckfall: ohne Skill-Manager wenigstens in den Skills-Reiter. Ein
        // Klick, der gar nichts tut, waere von einem kaputten Feld nicht zu
        // unterscheiden.
        var tb = document.querySelector('.settings-tab-btn[data-settings-tab="skills"]');
        if (tb && tb.style.display !== 'none') tb.click();
    }

    // Feld leeren, Panel zu, Index verwerfen.
    function beenden() {
        if (els.feld) els.feld.value = '';
        schliessePanel();
        verwerfen();
    }

    // ── Verdrahtung ─────────────────────────────────────────────────────────

    function init() {
        els.wrap = document.getElementById('st-such-wrap');
        els.feld = document.getElementById('st-such-feld');
        els.panel = document.getElementById('st-such-panel');
        els.liste = document.getElementById('st-such-liste');
        els.hinweis = document.getElementById('st-such-hinweis');
        if (!els.wrap || !els.feld || !els.panel || !els.liste) return;
        if (_bound) return;
        _bound = true;

        // Lupe = UNTERSUCHEN (icons.js). Kein Emoji: das wuerde je nach System
        // farbig gerendert und folgte keinem Thema.
        var lupe = document.getElementById('st-such-lupe');
        if (lupe && window.JarvisIcons && window.JarvisIcons.lupe) {
            lupe.innerHTML = window.JarvisIcons.lupe();
        }

        els.feld.addEventListener('input', function () {
            // Pro Tastendruck: vorhandener Index → sofort, sonst einmal laden.
            if (!_index && worteAus(els.feld.value).join('').length >= MIN_ZEICHEN) laden();
            zeichne();
        });

        els.feld.addEventListener('focus', function () {
            if (!_index) laden();
            if (els.feld.value) zeichne();
        });

        els.feld.addEventListener('keydown', function (e) {
            if (e.key === 'Escape') {
                // Escape leert ZUERST den Begriff und schliesst erst beim
                // zweiten Druck – sonst verliert man mit dem Panel auch die
                // Eingabe, obwohl man nur die Liste loswerden wollte. Und der
                // Druck darf NICHT bis zum Modal durchlaufen: dort schliesst er
                // die ganzen Einstellungen.
                if (els.feld.value) {
                    els.feld.value = '';
                    schliessePanel();
                    verwerfen();
                    e.stopPropagation();
                    e.preventDefault();
                } else if (offen()) {
                    schliessePanel();
                    e.stopPropagation();
                    e.preventDefault();
                }
                return;
            }
            if (!offen() || !_treffer.length) return;
            if (e.key === 'ArrowDown') {
                _aktiv = (_aktiv + 1) % _treffer.length;
                aktivZeigen(); e.preventDefault();
            } else if (e.key === 'ArrowUp') {
                _aktiv = (_aktiv <= 0 ? _treffer.length : _aktiv) - 1;
                aktivZeigen(); e.preventDefault();
            } else if (e.key === 'Enter') {
                if (_aktiv >= 0) { waehle(_aktiv); e.preventDefault(); }
            }
        });

        // Ein <div role="option"> nimmt keinen Fokus – geklickt wird delegiert,
        // die Zeilen entstehen bei jedem Tastendruck neu.
        els.liste.addEventListener('mousedown', function (e) {
            // Vor dem Klick nicht den Fokus aus dem Feld nehmen: ein blur
            // zwischen mousedown und click schloesse das Panel, und der Klick
            // ginge ins Leere.
            e.preventDefault();
        });
        els.liste.addEventListener('click', function (e) {
            var row = e.target && e.target.closest ? e.target.closest('.st-such-item') : null;
            if (!row) return;
            waehle(parseInt(row.getAttribute('data-i'), 10));
        });
        els.liste.addEventListener('mousemove', function (e) {
            var row = e.target && e.target.closest ? e.target.closest('.st-such-item') : null;
            if (!row) return;
            var i = parseInt(row.getAttribute('data-i'), 10);
            if (i !== _aktiv) { _aktiv = i; aktivZeigen(); }
        });

        // Klick daneben schliesst – wie beim Benutzer-Panel im Portal.
        // ⚠ BEIDE muessen geprueft werden: das Panel ist KIND DES KOPFES, nicht
        // des Feldes (siehe settings.html). Nur `els.wrap` geprueft, waere ein
        // Klick IN die Trefferliste "daneben" – das Panel schloesse sich, bevor
        // die Auswahl greift, und der Klick fuehrte nirgendwohin.
        document.addEventListener('click', function (e) {
            if (!offen() || !els.wrap || !els.panel) return;
            if (els.wrap.contains(e.target) || els.panel.contains(e.target)) return;
            schliessePanel();
        });
    }

    window.SettingsSearch = {
        init: init,
        close: beenden,
        // Fuer Messungen: der gebaute Index bzw. die aktuellen Treffer.
        _index: function () { return _index; },
        // Erzwingt einen Neuaufbau (Messungen, die die Lage veraendern).
        _verwerfen: verwerfen,
        _treffer: function () { return _treffer; },
        _baueIndex: baueIndex,
        _falte: falte,
    };
})();
