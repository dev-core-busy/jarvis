/* Wissens-Destillat – Container unter /wissen.
 *
 * Importiert aus dev-core-busy/knowledge-distiller (2026-09-26). Der dortige
 * Proxy-Teil ist ersatzlos entfallen: er meldet sich bei Jarvis an und schickt
 * den Text per WebSocket – hier laufen wir IN Jarvis, sind angemeldet und
 * rufen die eigenen Endpunkte.
 *
 * ⚠ DIE TEXTEXTRAKTION LAEUFT SERVERSEITIG. Das Original laedt pdf.js und
 * mammoth.js von cdnjs.cloudflare.com; externe Einbindungen sind in diesem
 * Projekt ausdruecklich verboten (Register: "Nie wieder extern einbinden").
 * Gewonnen wird dabei mehr als die Regel – der Server kann OCR fuer gescannte
 * PDFs, XLSX, PPTX und OneNote, der Browser nicht.
 *
 * Schnittstelle: `WissenDestillat.init({ scope, token })` aus wissen.js.
 * Bewusst KEIN eigener Scope-Abruf – `/api/wissen/scope` wird dort ohnehin
 * geholt, und zwei Abrufe liefen beim naechsten Feinschliff auseinander.
 */
(function () {
    'use strict';

    var SCOPE = null, TOKEN = '';
    var dateien = [];        // [{name, size, ok, fehler}]
    var bilder = [];         // data:-URIs, Index = [BILD-N] - 1
    var quellen = [];        // Namen der erfolgreich gelesenen Dateien
    var destillat = '';      // rohes Markdown der letzten Antwort
    var laeuft = false;
    var liest = false;       // Extraktion laeuft (Fortschrittszeile belegt)
    var protokoll = null;    // [{name, art: ok|fehler|uebersprungen|gefiltert, grund, zeichen, bilder}]

    function $(id) { return document.getElementById(id); }
    function t(k, vars) {
        var s = (window.t ? window.t(k) : k) || k;
        if (vars) { for (var v in vars) s = s.split('{' + v + '}').join(vars[v]); }
        return s;
    }
    function esc(s) {
        return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
        });
    }
    function authH(extra) {
        return Object.assign({ 'Authorization': 'Bearer ' + TOKEN }, extra || {});
    }

    // ⚠ LOOKBEHIND ALS STRING, NICHT ALS LITERAL – und das ist kein Stil.
    // Ein `(?<=…)` im Literal wirft schon beim PARSEN der Datei; auf Safari
    // vor 16.4 (alles vor 2023) waere damit nicht die Fettschrift weg, sondern
    // der GANZE Container. Als `new RegExp` im try verschiebt sich das auf die
    // Laufzeit: fehlt die Unterstuetzung, bleibt `**text**` literal stehen und
    // alles andere arbeitet. Steht woertlich im Register (avatar.js, 2026-09-14).
    // Die Fett-Regel ist zeichengleich zu `avatar.js::_FETT_RE` und dem
    // Jira-Plugin – die `\S`-Waechter sind der Unterschied zwischen brauchbar
    // und gefaehrlich: ohne sie werden `2 * 3 * 4` und `*.txt` ausgezeichnet.
    var _FETT = null, _KURSIV = null;
    try {
        _FETT = new RegExp('\\*\\*(?=\\S)([^\\n]+?)(?<=\\S)\\*\\*', 'g');
        _KURSIV = new RegExp('(^|[^*])\\*(?=\\S)([^*\\n]+?)(?<=\\S)\\*(?!\\*)', 'g');
    } catch (e) { _FETT = null; _KURSIV = null; }

    // ── Markdown ────────────────────────────────────────────────────────
    // Minimaler Renderer, uebernommen aus dem Original und GEHAERTET.
    //
    // ⚠ MASKIERT WIRD ZUERST. Der Text kommt vom Modell, das hochgeladene
    // Fremddokumente verarbeitet hat – ein `<img src=x onerror=...>` darin
    // liefe sonst im Origin von /wissen, und dort liegt das Sitzungstoken im
    // localStorage. Erst `esc()`, dann die Markdown-Regeln: danach kann kein
    // Markup mehr aus dem Inhalt entstehen, nur noch aus unseren Regeln.
    function md(text) {
        var s = esc(String(text || ''));

        // Codebloecke zuerst wegsichern, damit die Regeln darunter nicht
        // hineingreifen (ein `**` in einem Codebeispiel ist kein Fettdruck).
        var blocks = [], bi = 0;
        s = s.replace(/```[a-zA-Z0-9]*\n([\s\S]*?)```/g, function (m, code) {
            blocks.push('<pre><code>' + code.replace(/\n$/, '') + '</code></pre>');
            return '\u0000BLOCK' + (bi++) + '\u0000';
        });
        var inline = [], ii = 0;
        s = s.replace(/`([^`\n]+)`/g, function (m, code) {
            inline.push('<code>' + code + '</code>');
            return '\u0000CODE' + (ii++) + '\u0000';
        });

        // Bilder VOR den Links: `![alt](url)` ist sonst ein Link mit `!` davor.
        // Erlaubt sind nur data:-Bilder (unsere eingebetteten) und http(s).
        // ⚠ Das fertige <img> wird WEGGESICHERT wie ein Codeblock (Code-Review
        // 2026-10-07): sonst griff die Linkregel danach IN das alt-Attribut –
        // `![[t](https://q)](https://a/onerror=…)` schloss mit dem `"` des
        // erzeugten href das alt und setzte ein eigenes onerror-Attribut (XSS
        // per Prompt-Injection in einem destillierten Dokument).
        var bilder = [], bli = 0;
        s = s.replace(/!\[([^\]]*)\]\(([^)\s]+)\)/g, function (m, alt, url) {
            if (/^data:image\/(png|jpe?g|gif|webp|bmp);base64,[A-Za-z0-9+/=]+$/.test(url)
                || /^https?:\/\//.test(url)) {
                bilder.push('<img src="' + url + '" alt="' + alt + '">');
                return '\u0000BILD' + (bli++) + '\u0000';
            }
            return alt || '';   // alles andere: nur der Alt-Text
        });
        // Nur http(s) wird verlinkt. `javascript:` und `data:` bleiben damit
        // strukturell aussen vor – ein Link darauf liefe im Origin von /wissen.
        s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
            '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');

        s = s.replace(/^###### (.+)$/gm, '<h3>$1</h3>')
             .replace(/^##### (.+)$/gm, '<h3>$1</h3>')
             .replace(/^#### (.+)$/gm, '<h3>$1</h3>')
             .replace(/^### (.+)$/gm, '<h3>$1</h3>')
             .replace(/^## (.+)$/gm, '<h2>$1</h2>')
             .replace(/^# (.+)$/gm, '<h1>$1</h1>');
        s = s.replace(/^\s*---\s*$/gm, '<hr>');
        if (_FETT) s = s.replace(_FETT, '<strong>$1</strong>');
        if (_KURSIV) s = s.replace(_KURSIV, '$1<em>$2</em>');

        // Listen: zusammenhaengende Zeilen zu EINER Liste buendeln.
        s = s.replace(/(?:^[-*+] .+$\n?)+/gm, function (block) {
            var li = block.trim().split('\n').map(function (z) {
                return '<li>' + z.replace(/^[-*+] /, '') + '</li>';
            }).join('');
            return '<ul>' + li + '</ul>\n';
        });
        s = s.replace(/(?:^\d+\. .+$\n?)+/gm, function (block) {
            var li = block.trim().split('\n').map(function (z) {
                return '<li>' + z.replace(/^\d+\. /, '') + '</li>';
            }).join('');
            return '<ol>' + li + '</ol>\n';
        });

        s = s.split(/\n{2,}/).map(function (abs) {
            var a = abs.trim();
            if (!a) return '';
            if (/^<(h[123]|ul|ol|pre|hr|img)/.test(a)) return a;
            if (a.indexOf('\u0000BLOCK') === 0) return a;
            if (a.indexOf('\u0000BILD') === 0) return a;   // wie vorher ein fuehrendes <img>
            return '<p>' + a.replace(/\n/g, '<br>') + '</p>';
        }).join('\n');

        s = s.replace(/\u0000BLOCK(\d+)\u0000/g, function (m, i) { return blocks[+i]; });
        s = s.replace(/\u0000CODE(\d+)\u0000/g, function (m, i) { return inline[+i]; });
        s = s.replace(/\u0000BILD(\d+)\u0000/g, function (m, i) { return bilder[+i]; });
        return s;
    }

    // `[BILD-N]` -> eingebettetes Bild. NUR fuer Anzeige und Download; was in
    // die Wissensdatenbank geht, ersetzt der Server durch einen Hinweis (ein
    // Base64-Bild wuerde dort zu Dutzenden nutzloser Vektor-Chunks).
    function mitBildern(text) {
        return String(text || '').replace(/\[BILD-(\d+)\]/g, function (m, n) {
            var i = parseInt(n, 10) - 1;
            return (i >= 0 && i < bilder.length)
                ? '\n\n![Bild](' + bilder[i] + ')\n\n' : m;
        });
    }

    // ── Anzeige ─────────────────────────────────────────────────────────
    // art 'busy': derselbe Drehkreis wie beim Upload und beim Lesen der
    // Dateien (`.wi-busy-spin`) statt einer Sanduhr im Text – ein Warte-
    // zeichen je Seite, nicht zwei (Vorgabe 2026-09-28).
    function status(el, msg, art) {
        var e = $(el); if (!e) return;
        if (msg && art === 'busy') {
            e.innerHTML = '<span class="wi-dest-busy"><span class="wi-busy-spin" aria-hidden="true"></span>'
                + '<span>' + esc(msg) + '</span></span>';
            return;
        }
        e.innerHTML = msg
            ? '<span class="' + (art === 'err' ? 'wi-err' : art === 'ok' ? 'wi-ok' : '')
              + '">' + esc(msg) + '</span>' : '';
    }
    function fortschritt(pct) {
        var bar = $('wi-dest-bar'), fill = $('wi-dest-fill');
        if (!bar || !fill) return;
        if (pct == null) { bar.hidden = true; fill.style.width = '0%'; return; }
        bar.hidden = false;
        fill.style.width = Math.max(0, Math.min(100, pct)) + '%';
    }
    function bytes(b) {
        if (b < 1024) return b + ' B';
        if (b < 1024 * 1024) return (b / 1024).toFixed(0) + ' KB';
        return (b / 1024 / 1024).toFixed(1) + ' MB';
    }

    function dateilisteZeichnen() {
        var box = $('wi-dest-filelist'); if (!box) return;
        if (!dateien.length) { box.innerHTML = ''; return; }
        box.innerHTML = dateien.map(function (d, i) {
            return '<div class="wi-item wi-dest-file">'
                + '<span class="nm" title="' + esc(d.name) + '">' + esc(d.name) + '</span>'
                + (d.fehler ? '<span class="er" title="' + esc(d.fehler) + '">'
                              + esc(t('wissen.dest_unreadable')) + '</span>'
                            : '<span class="sz">' + bytes(d.size) + '</span>')
                + '<button type="button" class="wi-icon-btn" data-idx="' + i + '" title="'
                + esc(t('common.delete')) + '" aria-label="' + esc(t('common.delete')) + '">'
                + (window.JarvisIcons ? window.JarvisIcons.trash() : '') + '</button>'
                + '</div>';
        }).join('');
        Array.prototype.forEach.call(box.querySelectorAll('button[data-idx]'), function (b) {
            b.addEventListener('click', function () {
                dateien.splice(parseInt(b.getAttribute('data-idx'), 10), 1);
                dateilisteZeichnen();
            });
        });
    }

    function zaehlerZeichnen() {
        var ta = $('wi-dest-text'), z = $('wi-dest-count');
        if (!ta || !z) return;
        var n = ta.value.length;
        z.textContent = n ? t('wissen.dest_chars', { n: n.toLocaleString() }) : '';
        var run = $('wi-dest-run');
        // Gesperrt MIT GRUND statt verborgen (Projektregel): ein Knopf, der je
        // nach Datenlage verschwindet, ist unerklaerbar.
        if (run) {
            run.disabled = laeuft || !ta.value.trim();
            run.title = laeuft ? t('wissen.dest_running')
                : (ta.value.trim() ? '' : t('wissen.dest_need_text'));
        }
    }

    // ── Dateifilter (Black-/Whitelist, Vorgabe 2026-09-27) ──────────────
    // ⚠ ANGEWANDT WIRD HIER IM BROWSER, VOR DEM HOCHLADEN – nicht auf dem
    // Server: ein Ordner mit 500 Dateien, von denen die Whitelist 50
    // durchlaesst, liefe dort in die Obergrenze der Dateizahl, und jede
    // ausgeschlossene Datei waere umsonst uebertragen. Der Server SPEICHERT nur
    // die Listen (je Benutzer, /api/wissen/destillat/filter).
    // Es gilt, was in den FELDERN steht, nicht der zuletzt gespeicherte Stand:
    // was man sieht, wirkt – auch wenn das Speichern gerade gescheitert ist.
    function musterListe(id) {
        var el = $(id);
        return String((el && el.value) || '').split('\n')
            .map(function (z) { return z.trim(); })
            .filter(function (z) { return !!z; });
    }
    // Glob -> RegExp: `*` beliebig viele Zeichen (auch `/`), `?` genau eines,
    // alles andere woertlich. Ein Muster mit `/` am Ende meint den Ordner
    // samt Inhalt (`archiv/` = `archiv/*`).
    function musterRegex(m) {
        if (m.charAt(m.length - 1) === '/') m += '*';
        var re = m.replace(/[.+^${}()|[\]\\]/g, '\\$&')
                  .replace(/\*/g, '.*').replace(/\?/g, '.');
        return new RegExp('^' + re + '$', 'i');
    }
    // Geprueft wird gegen JEDES Pfadende ab einer Ordnergrenze: fuer
    // `projekt/archiv/a.pdf` also `projekt/archiv/a.pdf`, `archiv/a.pdf` und
    // `a.pdf`. Damit trifft `*.pdf` den Dateinamen und `archiv/*` den Ordner,
    // egal wie tief er liegt.
    function musterTrifft(m, pfad) {
        var re;
        try { re = musterRegex(m); } catch (e) { return false; }
        var teile = String(pfad || '').replace(/\\/g, '/').split('/')
            .filter(function (x) { return !!x; });
        for (var i = 0; i < teile.length; i++) {
            if (re.test(teile.slice(i).join('/'))) return true;
        }
        return false;
    }
    // '' = Datei wird genommen, sonst der Grund fuer das Protokoll.
    // DIE BLACKLIST GEWINNT; eine leere Whitelist heisst „alles erlaubt".
    function filterGrund(pfad) {
        var schwarz = musterListe('wi-dest-schwarz');
        for (var i = 0; i < schwarz.length; i++) {
            if (musterTrifft(schwarz[i], pfad)) return t('wissen.dest_filter_black', { m: schwarz[i] });
        }
        var weiss = musterListe('wi-dest-weiss');
        if (weiss.length && !weiss.some(function (m) { return musterTrifft(m, pfad); })) {
            return t('wissen.dest_filter_notwhite');
        }
        return '';
    }
    function filterZahlZeichnen() {
        var z = $('wi-dest-filterzahl'); if (!z) return;
        var n = musterListe('wi-dest-weiss').length + musterListe('wi-dest-schwarz').length;
        z.textContent = n ? t('wissen.dest_filter_active', { n: n }) : '';
    }
    function filterLaden() {
        fetch('/api/wissen/destillat/filter', { headers: authH() })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || !d.ok) return;
                // Hat der Benutzer schon getippt, gewinnt seine Eingabe.
                [['wi-dest-weiss', d.weiss], ['wi-dest-schwarz', d.schwarz]].forEach(function (x) {
                    var el = $(x[0]);
                    if (el && !el.dataset.beruehrt) el.value = (x[1] || []).join('\n');
                });
                filterZahlZeichnen();
            })
            .catch(function () { /* ohne gespeicherten Filter: keiner */ });
    }
    function filterSpeichern() {
        status('wi-dest-filterstatus', '');
        fetch('/api/wissen/destillat/filter', {
            method: 'PUT', headers: authH({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({ weiss: musterListe('wi-dest-weiss'),
                                   schwarz: musterListe('wi-dest-schwarz') })
        })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || !d.ok) {
                    status('wi-dest-filterstatus', (d && d.error) || t('wissen.dest_filter_save_err'), 'err');
                    return;
                }
                status('wi-dest-filterstatus', t('wissen.dest_filter_saved'), 'ok');
                // Ein Erfolg darf verschwinden, ein Fehler nicht (Register).
                setTimeout(function () {
                    var e = $('wi-dest-filterstatus');
                    if (e && e.querySelector('.wi-ok')) e.innerHTML = '';
                }, 2500);
            })
            .catch(function () {
                status('wi-dest-filterstatus', t('wissen.dest_filter_save_err'), 'err');
            });
    }

    // ── Extraktion ──────────────────────────────────────────────────────
    // Ein Eintrag ist ein File ODER {datei, name}: aus einem Ordner kommt der
    // RELATIVE Pfad als Name mit. Er steht dann in der Kopfzeile
    // `--- <name> ---` und in der Dateiliste – zwei gleichnamige Dateien aus
    // verschiedenen Unterordnern waeren sonst nicht zu unterscheiden, und die
    // Fehlerzuordnung je Datei (d.fehler[name]) traefe beide.
    // `weg` = Zahl der beim Ordner-Import uebersprungenen versteckten Dateien.
    // Sie steht in DERSELBEN Statuszeile wie das Ergebnis – eine eigene
    // Meldung davor ueberschriebe die Extraktion sofort wieder.
    function dateienNehmen(liste, weg) {
        if (!liste || !liste.length) return;
        // Ein zweiter Lauf parallel zeichnete in DIESELBE Fortschrittszeile –
        // "Datei 3 von 8" und "Datei 1 von 2" wechselten sich ab.
        if (liest) { status('wi-dest-exstatus', t('wissen.dest_busy_wait'), 'err'); return; }
        var fd = new FormData();
        var neu = [], gefiltert = [];
        Array.prototype.forEach.call(liste, function (x) {
            var f = x.datei || x, name = x.name && x.datei ? x.name : f.name;
            // Dateifilter VOR dem Anhaengen: was er auslaesst, wird nicht
            // uebertragen - steht aber mit Grund im Protokoll.
            var grund = filterGrund(name);
            if (grund) { gefiltert.push({ name: name, art: 'gefiltert', grund: grund }); return; }
            fd.append('files', f, name);
            neu.push({ name: name, size: f.size });
        });
        if (!neu.length) {
            // Alles ausgelassen: kein Abruf. Gesagt wird es trotzdem - ein
            // Ziehen, auf das gar nichts folgt, saehe wie ein toter Knopf aus.
            status('wi-dest-exstatus', t('wissen.dest_filtered_all', { n: gefiltert.length })
                + (weg ? ' · ' + t('wissen.dest_dir_skipped', { n: weg }) : ''), 'err');
            protokollSetzen(gefiltert);
            return;
        }
        dateien = dateien.concat(neu);
        dateilisteZeichnen();
        status('wi-dest-exstatus', '');
        protokollSetzen(null);
        leseStart(neu.length);

        var fertig = null, fehlerText = '';
        fetch('/api/wissen/destillat/extract?stream=1', {
            method: 'POST', headers: authH(), body: fd
        })
            .then(function (r) {
                return zeilenLesen(r, function (z) {
                    if (z.art === 'datei') leseSchritt(z.i, z.n, z.name);
                    else if (z.art === 'fertig') fertig = z;
                    // Ohne `art`: Antwort VOR dem Strom (403/400/413) – ein
                    // gewoehnliches JSON-Objekt mit `error`.
                    else if (z.art === 'fehler' || z.error) fehlerText = z.error || '';
                }).then(function () { return r.status; });
            })
            .then(function (code) {
                leseEnde(!!fertig);
                if (!fertig) {
                    status('wi-dest-exstatus', fehlerText
                        || (code === 200 ? t('wissen.dest_stream_broken')
                                         : t('wissen.dest_extract_failed')), 'err');
                    return;
                }
                extraktUebernehmen(fertig, weg, gefiltert);
            })
            .catch(function (e) {
                leseEnde(false);
                status('wi-dest-exstatus', t('wissen.dest_extract_failed'), 'err');
            });
    }

    // Antwort ZEILENWEISE (NDJSON) lesen, solange sie noch laeuft – erst das
    // macht "Datei i von n" moeglich. Ohne lesbaren Strom (sehr alter Browser)
    // kommt alles am Ende auf einmal: der Balken springt, das Ergebnis stimmt.
    function zeilenLesen(r, jeZeile) {
        var rest = '';
        function zerlegen(schluss) {
            var teile = rest.split('\n');
            rest = schluss ? '' : teile.pop();
            teile.forEach(function (z) {
                if (!z.trim()) return;
                var o = null;
                try { o = JSON.parse(z); } catch (e) { return; }
                if (o && typeof o === 'object') jeZeile(o);
            });
        }
        if (r.body && r.body.getReader && window.TextDecoder) {
            var leser = r.body.getReader(), dec = new window.TextDecoder();
            return (function weiter() {
                return leser.read().then(function (st) {
                    if (st.done) { rest += dec.decode(); zerlegen(true); return; }
                    rest += dec.decode(st.value, { stream: true });
                    zerlegen(false);
                    return weiter();
                });
            })();
        }
        return r.text().then(function (txt) { rest = String(txt || ''); zerlegen(true); });
    }

    function extraktUebernehmen(d, weg, gefiltert) {
        // Fehler je Datei an der ZEILE vermerken, nicht nur als Summe:
        // "3 Fehler" sagt nicht, WELCHE Datei nicht lesbar war.
        dateien.forEach(function (x) {
            if (d.fehler && d.fehler[x.name]) x.fehler = d.fehler[x.name];
        });
        dateilisteZeichnen();

        var ta = $('wi-dest-text');
        if (ta && d.text) {
            // ANHAENGEN, nicht ersetzen: wer schon Text eingegeben oder
            // eine erste Datei gelesen hat, verliert ihn sonst.
            // ⚠ DANN AUCH BILDER UND QUELLEN ANHAENGEN (Review 2026-09-28 #12).
            // Der Server nummeriert [BILD-n] je Anfrage ab 1. Wurden die
            // Bilder ersetzt, der Text aber angehaengt, zeigten ab der zweiten
            // Datei alle Marken auf falsche Bilder, und die Uebernahme nannte
            // nur die letzte Quelle. Darum die neuen Marken um die Zahl der
            // vorhandenen Bilder verschieben.
            var text = d.text, neu = d.bilder || [];
            if (ta.value.trim()) {
                var versatz = bilder.length;
                if (versatz) {
                    text = text.replace(/\[BILD-(\d+)\]/g, function (m, n) {
                        return '[BILD-' + (parseInt(n, 10) + versatz) + ']';
                    });
                }
                bilder = bilder.concat(neu);
                (d.ok || []).forEach(function (q) {
                    if (quellen.indexOf(q) < 0) quellen.push(q);
                });
                ta.value = ta.value.replace(/\s*$/, '') + '\n\n' + text;
            } else {
                // Leeres Feld = neuer Anfang: alte Bilder gehoeren zu keinem
                // Text mehr.
                bilder = neu.slice();
                quellen = (d.ok || []).slice();
                ta.value = text;
            }
            zaehlerZeichnen();
        }
        // Die vom Dateifilter ausgelassenen Dateien kennt nur der Browser -
        // sie gehoeren trotzdem ins selbe Protokoll, sonst waeren sie spurlos weg.
        var prot = (gefiltert || []).concat(d.protokoll || []);
        var teile = [t('wissen.dest_extracted', { n: (d.ok || []).length })];
        var fehlZahl = Object.keys(d.fehler || {}).length;
        var wegZahl = prot.filter(function (p) { return p.art === 'uebersprungen'; }).length;
        if (fehlZahl) teile.push(t('wissen.dest_failed_n', { n: fehlZahl }));
        if (wegZahl) teile.push(t('wissen.dest_skipped_n', { n: wegZahl }));
        if ((gefiltert || []).length) teile.push(t('wissen.dest_filtered_n', { n: gefiltert.length }));
        // Eine Kuerzung wird BEZIFFERT, nie stillschweigend gemacht.
        if (d.gekappt) teile.push(t('wissen.dest_capped'));
        if (weg) teile.push(t('wissen.dest_dir_skipped', { n: weg }));
        status('wi-dest-exstatus', teile.join(' · '), (fehlZahl || wegZahl) ? 'err' : 'ok');
        protokollSetzen(prot);
    }

    // ── Lesefortschritt ────────────────────────────────────────────────
    // Der Balken ist hier – anders als beim Destillieren – eine MESSUNG: der
    // Server meldet jede Datei, BEVOR er sie liest. Waehrend Datei i laeuft,
    // steht er deshalb auf (i-1)/n, nicht auf i/n – sonst stuende er bei der
    // letzten, langsamsten Datei schon auf 100 %.
    function leseFuellung(pct) {
        var bar = $('wi-dest-exbar'), fill = $('wi-dest-exfill');
        if (!bar || !fill) return;
        if (pct == null) { bar.hidden = true; fill.style.width = '0%'; return; }
        bar.hidden = false;
        fill.style.width = Math.max(0, Math.min(100, pct)) + '%';
    }
    function leseText(txt) {
        var box = $('wi-dest-exbusy'), el = $('wi-dest-exbusy-text');
        if (!box || !el) return;
        box.hidden = txt == null;
        el.textContent = txt == null ? '' : txt;
        el.title = txt == null ? '' : txt;
    }
    function leseStart(n) {
        liest = true;
        var drop = $('wi-dest-drop'); if (drop) drop.classList.add('disabled');
        // Vor der ersten Zeile laeuft noch die UEBERTRAGUNG – bei grossen
        // Ordnern die eigentliche Wartezeit. "0 von n" waere hier falsch.
        leseText(t('wissen.dest_uploading', { n: n }));
        leseFuellung(2);
    }
    function leseSchritt(i, n, name) {
        leseText(t('wissen.dest_reading_n', { i: i, n: n, name: name || '' }));
        leseFuellung(n ? (i - 1) / n * 100 : 0);
    }
    function leseEnde(erfolg) {
        liest = false;
        var drop = $('wi-dest-drop'); if (drop) drop.classList.remove('disabled');
        leseText(null);
        if (!erfolg) { leseFuellung(null); return; }
        leseFuellung(100);
        setTimeout(function () { if (!liest) leseFuellung(null); }, 1200);
    }

    // ── Protokoll ──────────────────────────────────────────────────────
    // Welche Datei gelesen wurde und WARUM eine nicht – die Summe in der
    // Statuszeile allein laesst den Benutzer raten.
    function protokollSetzen(prot) {
        protokoll = prot && prot.length ? prot : null;
        var btn = $('wi-dest-logbtn'), box = $('wi-dest-log');
        if (btn) btn.hidden = !protokoll;
        if (!protokoll && box) box.hidden = true;
        protokollZeichnen();
    }
    function protokollZeichnen() {
        var btn = $('wi-dest-logbtn'), box = $('wi-dest-log');
        if (!btn || !box) return;
        var offen = !box.hidden;
        var key = offen ? 'wissen.dest_log_hide' : 'wissen.dest_log_show';
        // data-i18n MITZIEHEN: sonst setzt der naechste Sprachwechsel den
        // Knopf auf "anzeigen", obwohl das Protokoll offen ist.
        btn.setAttribute('data-i18n', key);
        btn.textContent = t(key);
        btn.setAttribute('aria-expanded', offen ? 'true' : 'false');
        if (!protokoll) { box.innerHTML = ''; return; }
        box.innerHTML = protokoll.map(function (p) {
            var zei = p.art === 'ok' ? '✓' : p.art === 'fehler' ? '✗' : '–';
            var gr = '';
            if (p.art === 'ok') {
                gr = t('wissen.dest_chars', { n: Number(p.zeichen || 0).toLocaleString() });
                if (p.bilder) gr += ' · ' + t('wissen.dest_log_images', { n: p.bilder });
            } else if (p.art === 'uebersprungen') {
                gr = t('wissen.dest_log_skipped');
            } else if (p.art === 'gefiltert') {
                gr = p.grund || '';
            } else {
                gr = p.grund || t('wissen.dest_unreadable');
            }
            var art = { ok: 1, fehler: 1, uebersprungen: 1, gefiltert: 1 }[p.art] ? p.art : 'fehler';
            return '<div class="wi-dest-logzeile ' + art + '">'
                + '<span class="zei" aria-hidden="true">' + zei + '</span>'
                + '<span class="nm">' + esc(p.name) + '</span>'
                + '<span class="gr">' + esc(gr) + '</span>'
                + '</div>';
        }).join('');
    }

    // ── Ordner ──────────────────────────────────────────────────────────
    // Versteckte Dateien und Ordner (".git", ".DS_Store", "__MACOSX") gehoeren
    // nicht zum Inhalt eines Ordners, den jemand destillieren will – sie
    // wuerden nur als "nicht lesbar" in der Liste stehen oder die Obergrenze
    // der Dateizahl aufbrauchen. Gezaehlt und GENANNT, nicht still verworfen.
    function versteckt(pfad) {
        return String(pfad || '').split('/').some(function (teil) {
            return teil.charAt(0) === '.' || teil === '__MACOSX';
        });
    }
    function ordnerNehmen(eintraege) {
        var nehmen = [], weg = 0;
        eintraege.forEach(function (e) {
            if (versteckt(e.name)) { weg++; return; }
            nehmen.push(e);
        });
        // Feste Reihenfolge nach Pfad: der Browser liefert Ordnerinhalte in
        // keiner zugesagten Ordnung, und die Reihenfolge ist die des Textes.
        nehmen.sort(function (a, b) { return a.name < b.name ? -1 : a.name > b.name ? 1 : 0; });
        if (!nehmen.length) {
            status('wi-dest-exstatus', t('wissen.dest_dir_empty')
                + (weg ? ' · ' + t('wissen.dest_dir_skipped', { n: weg }) : ''), 'err');
            return;
        }
        dateienNehmen(nehmen, weg);
    }
    function ausOrdnerwahl(files) {
        ordnerNehmen(Array.prototype.map.call(files || [], function (f) {
            return { datei: f, name: f.webkitRelativePath || f.name };
        }));
    }
    // Rekursiver Durchlauf eines gezogenen Ordners. readEntries() liefert
    // BLOCKWEISE (Chrome: hoechstens 100 je Aufruf) – wer nur einmal liest,
    // verliert bei grossen Ordnern still den Rest. Also lesen, bis leer.
    function eintragLesen(eintrag, raus) {
        return new Promise(function (fertig) {
            if (eintrag.isFile) {
                eintrag.file(function (f) {
                    raus.push({ datei: f, name: eintrag.fullPath.replace(/^\//, '') });
                    fertig();
                }, function () { fertig(); });
                return;
            }
            if (!eintrag.isDirectory) { fertig(); return; }
            var leser = eintrag.createReader(), kinder = [];
            (function weiter() {
                leser.readEntries(function (block) {
                    if (!block.length) {
                        Promise.all(kinder.map(function (k) { return eintragLesen(k, raus); }))
                            .then(fertig);
                        return;
                    }
                    kinder = kinder.concat(Array.prototype.slice.call(block));
                    weiter();
                }, function () { fertig(); });
            })();
        });
    }

    // ── Lauf ────────────────────────────────────────────────────────────
    function destillieren() {
        var ta = $('wi-dest-text');
        if (!ta || !ta.value.trim() || laeuft) return;
        laeuft = true;
        zaehlerZeichnen();
        var run = $('wi-dest-run');
        if (run) { run.disabled = true; run.title = t('wissen.dest_running'); }
        status('wi-dest-status', t('wissen.dest_running'), 'busy');
        fortschritt(8);

        // Der Balken bewegt sich waehrend des Laufs weiter. Es ist bewusst eine
        // SCHAETZUNG und keine Messung – der Endpunkt antwortet erst am Ende;
        // er laeuft deshalb nur bis 90 und nie auf 100.
        var tick = setInterval(function () {
            var f = $('wi-dest-fill');
            if (!f) return;
            var jetzt = parseFloat(f.style.width) || 8;
            if (jetzt < 90) fortschritt(jetzt + 2);
        }, 2000);

        fetch('/api/wissen/destillat/lauf', {
            method: 'POST', headers: authH({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({
                text: ta.value,
                prompt: ($('wi-dest-prompt') || {}).value || '',
                gruppen_prompt: ($('wi-dest-gruppen') || {}).value || '',
                je_datei: ($('wi-dest-mode') || {}).value === 'file'
            })
        })
            .then(antwortLesen)
            .then(function (res) {
                clearInterval(tick);
                if (res.s !== 200 || !res.d.ok) {
                    fortschritt(null);
                    status('wi-dest-status', res.d.error || t('wissen.dest_failed'), 'err');
                    return;
                }
                fortschritt(100);
                destillat = res.d.markdown || '';
                ergebnisZeichnen(res.d);
                status('wi-dest-status', t('wissen.dest_done'), 'ok');
                setTimeout(function () { fortschritt(null); }, 1200);
            })
            .catch(function (e) {
                clearInterval(tick);
                fortschritt(null);
                status('wi-dest-status', t('wissen.dest_failed'), 'err');
            })
            .then(function () {
                laeuft = false;
                zaehlerZeichnen();
            });
    }

    function ergebnisZeichnen(d) {
        var out = $('wi-dest-out'), box = $('wi-dest-md');
        if (!out || !box) return;
        out.hidden = false;
        box.innerHTML = md(mitBildern(destillat));
        var meta = [t('wissen.dest_chars', { n: destillat.length.toLocaleString() })];
        if (d && d.bloecke > 1) meta.push(t('wissen.dest_blocks', { n: d.bloecke }));
        if (d && d.gekappt) meta.push(t('wissen.dest_capped'));
        var m = $('wi-dest-meta'); if (m) m.textContent = meta.join(' · ');
        var tb = $('wi-dest-takebox'); if (tb) tb.hidden = true;
        status('wi-dest-takestatus', '');
        // Ein NEUES Destillat heisst: neuer Titelvorschlag. Ohne das Loeschen
        // der Beruehrt-Marke stuende der Titel des vorigen Laufs im Feld, und
        // die Seite hiesse nach einem Inhalt, der nicht mehr darin steht.
        var cb = $('wi-dest-cfbox'); if (cb) cb.hidden = true;
        var ct = $('wi-dest-cftitel');
        if (ct) { delete ct.dataset.beruehrt; ct.value = ''; }
        status('wi-dest-cfstatus', '');
    }

    // ── Ergebnis verwerten ──────────────────────────────────────────────
    function dateiname() {
        var d = new Date();
        return 'destillat_' + d.toISOString().slice(0, 10) + '.md';
    }
    function kopieren() {
        var text = mitBildern(destillat);
        if (!navigator.clipboard) {
            status('wi-dest-takestatus', t('wissen.dest_copy_manual'), 'err');
            return;
        }
        navigator.clipboard.writeText(text).then(function () {
            status('wi-dest-status', t('wissen.dest_copied'), 'ok');
        }).catch(function () {
            // Fehlschlag MELDEN: in der Zwischenablage sieht man nichts, und
            // `navigator.clipboard` fehlt in unsicheren Kontexten ganz.
            status('wi-dest-status', t('wissen.dest_copy_manual'), 'err');
        });
    }
    function herunterladen() {
        var blob = new Blob([mitBildern(destillat)],
                            { type: 'text/markdown;charset=utf-8' });
        var a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = dateiname();
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        setTimeout(function () { URL.revokeObjectURL(a.href); }, 1000);
        status('wi-dest-status', t('wissen.dest_saved'), 'ok');
    }

    function gruppenBoxen() {
        if (!SCOPE || !SCOPE.groups) return '';
        // "Alle"/"Keine" aus wissen.js (dort auch der Klick-Hoerer).
        var wahl = window.WissenGruppenWahl;
        var leiste = wahl ? wahl.leiste('wi-grp-dest', SCOPE.groups.length) : '';
        return leiste + SCOPE.groups.map(function (g) {
            // Bei genau EINER Gruppe gibt es nichts zu waehlen – vorbelegen.
            var an = SCOPE.groups.length === 1;
            return '<label class="wi-grpbox" style="border-color:' + esc(g.color) + ';">'
                + '<input type="checkbox" class="wi-grp-dest" value="' + esc(g.id) + '"'
                + (an ? ' checked' : '') + '>'
                + '<span style="font-weight:600;">' + esc(g.name) + '</span></label>';
        }).join('');
    }
    function gewaehlteGruppen() {
        return Array.prototype.slice.call(
            document.querySelectorAll('.wi-grp-dest:checked')
        ).map(function (c) { return c.value; });
    }

    function uebernahmeZeigen() {
        var box = $('wi-dest-takebox'); if (!box) return;
        var g = $('wi-dest-groups');
        // Nur EINMAL zeichnen: ein Neuaufbau verwuerfe die gesetzten Haken.
        if (g && !g.innerHTML.trim()) g.innerHTML = gruppenBoxen();
        box.hidden = false;
        status('wi-dest-takestatus', '');
    }

    function uebernehmen() {
        var groups = gewaehlteGruppen();
        if (!groups.length) {
            // VORHANDENER Schluessel, kein neuer: gleiche Bedeutung, gleicher
            // Text – zwei Schluessel dafuer liefen beim naechsten
            // Umformulieren auseinander.
            status('wi-dest-takestatus', t('wissen.pick_group'), 'err');
            return;
        }
        var btn = $('wi-dest-takego');
        if (btn) btn.disabled = true;
        status('wi-dest-takestatus', t('wissen.dest_taking'), 'busy');
        fetch('/api/wissen/destillat/uebernehmen', {
            method: 'POST', headers: authH({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({
                markdown: destillat, groups: groups,
                quelle: quellen.join(', '), bilder: bilder
            })
        })
            .then(antwortLesen)
            .then(function (res) {
                if (res.s !== 201 || !res.d.ok) {
                    status('wi-dest-takestatus', res.d.error || t('wissen.dest_take_failed'), 'err');
                    return;
                }
                status('wi-dest-takestatus',
                       t('wissen.dest_taken', { titel: res.d.title || '' }), 'ok');
                // Die Entwurfsliste weiter unten muss den neuen Eintrag zeigen –
                // sonst sucht der Benutzer ihn dort vergeblich.
                if (window.WissenPortal && window.WissenPortal.reloadPending) {
                    window.WissenPortal.reloadPending();
                }
            })
            .catch(function (e) {
                status('wi-dest-takestatus', t('wissen.dest_take_failed'), 'err');
            })
            .then(function () { if (btn) btn.disabled = false; });
    }

    // ── Als neue Confluence-Seite ───────────────────────────────────────
    // ⚠ ZUSTAND UND BEREICHSLISTE KOMMEN VON wissen.js (cfDestMelden), nicht
    // aus einem eigenen Abruf: sonst boete dieser Container andere Bereiche an
    // als die Einbindung darunter, sobald eine der beiden Stellen angefasst
    // wird. Dieselbe Entscheidung wie beim Scope (siehe Modulkopf).
    var cfAktiv = false;      // Skill aktiv UND konfiguriert
    var cfSpaces = null;      // sichtbare Bereiche (null = noch unterwegs)
    var cfSeiten = {};        // Bereichsschluessel -> Promise auf die Seitenliste
    var cfLaeuft = false;     // Anlegen laeuft (zweiter Klick waere eine zweite Seite)

    function confluence(aktiv, spaces) {
        cfAktiv = !!aktiv;
        cfSpaces = spaces || null;
        cfKnopf();
        // Steht der Kasten offen, waehrend die Bereichsliste eintrifft, muss
        // das Pulldown nachgezogen werden - sonst bliebe dort "Lade ...".
        var box = $('wi-dest-cfbox');
        if (box && !box.hidden) cfSpacesZeichnen();
    }

    function cfKnopf() {
        var b = $('wi-dest-cf');
        if (!b) return;
        b.hidden = !cfAktiv;
        // Ohne aktiven Skill gibt es auch nichts zu schliessen.
        if (!cfAktiv) { var box = $('wi-dest-cfbox'); if (box) box.hidden = true; }
    }

    // Titelvorschlag aus der ersten Ueberschrift - dieselbe Regel wie
    // `titel_aus_markdown` im Backend. Er ist nur VORBELEGUNG: geschickt wird,
    // was im Feld steht (Confluence verlangt je Bereich eindeutige Titel, und
    // eine Kollision loest man genau hier).
    function cfTitelVorschlag() {
        var zeilen = String(destillat || '').split('\n');
        for (var i = 0; i < zeilen.length; i++) {
            var z = zeilen[i].trim();
            if (!z) continue;
            if (z.charAt(0) === '#') {
                var h = z.replace(/^#+\s*/, '').trim();
                if (h) return cfTitelPutzen(h);
                continue;
            }
            return cfTitelPutzen(z);
        }
        return '';
    }
    function cfTitelPutzen(s) {
        // `**Titel**` als Seitenname waere die Auszeichnung im Klartext.
        return s.replace(/^[*_`#\s]+/, '').replace(/[*_`\s]+$/, '').slice(0, 255);
    }

    function cfSpacesZeichnen() {
        var sel = $('wi-dest-cfspace');
        if (!sel) return;
        if (!cfSpaces) {
            sel.innerHTML = '<option value="">' + esc(t('common.loading')) + '</option>';
            sel.disabled = true;
            cfGoKnopf();
            return;
        }
        sel.disabled = false;
        if (!cfSpaces.length) {
            sel.innerHTML = '<option value="">' + esc(t('wissen.cfb_nospaces')) + '</option>';
            cfGoKnopf();
            return;
        }
        // Die bisherige Wahl ueberlebt ein Nachziehen der Liste.
        var vorher = sel.value;
        sel.innerHTML = '<option value="">' + esc(t('wissen.dest_cf_pick')) + '</option>'
            + cfSpaces.map(function (sp) {
                return '<option value="' + esc(sp.key) + '">'
                    + esc((sp.name || sp.key) + ' (' + sp.key + ')') + '</option>';
            }).join('');
        // ⚠ ERST die Optionen, DANN der Wert: an einem leeren <select> verpufft
        // eine Zuweisung still und der Wert waere '' (Register).
        if (vorher) sel.value = vorher;
        cfGoKnopf();
    }

    // Seitenbaum eines Bereichs als eingerueckte Auswahl. Gebaut wird die
    // Hierarchie mit `WissenPortal.cfBaum` - derselben Regel wie im Baum der
    // Einbindung, nicht mit einer zweiten Fassung davon.
    function cfSeitenZeichnen(seiten) {
        var sel = $('wi-dest-cfparent');
        if (!sel) return;
        sel.disabled = false;
        var opt = ['<option value="">' + esc(t('wissen.dest_cf_root')) + '</option>'];
        var bauen = (window.WissenPortal && window.WissenPortal.cfBaum) || null;
        var baum = bauen ? bauen(seiten || []) : [];
        (function lauf(knoten, tiefe) {
            knoten.forEach(function (n) {
                // GESCHUETZTE Leerzeichen (U+00A0): gewoehnliche faltet der
                // Browser in einem <option> zusammen, die Einrueckung waere
                // unsichtbar und der Baum saehe aus wie eine flache Liste.
                var ein = new Array(tiefe + 1).join('\u00a0\u00a0\u00a0');
                opt.push('<option value="' + esc(n.id) + '">'
                         + ein + esc(n.title) + '</option>');
                lauf(n.kids, tiefe + 1);
            });
        })(baum, 0);
        sel.innerHTML = opt.join('');
    }

    function cfSeitenLaden(space) {
        var sel = $('wi-dest-cfparent');
        if (!sel) return;
        if (!space) {
            sel.innerHTML = '<option value="">' + esc(t('wissen.dest_cf_root')) + '</option>';
            sel.disabled = true;
            return;
        }
        sel.innerHTML = '<option value="">' + esc(t('common.loading')) + '</option>';
        sel.disabled = true;
        if (!cfSeiten[space]) {
            cfSeiten[space] = fetch('/api/wissen/confluence/pages?space='
                                    + encodeURIComponent(space), { headers: authH() })
                .then(function (r) { return r.json(); })
                .then(function (d) {
                    if (!d || !d.ok) throw new Error((d && d.error) || 'x');
                    return d.pages || [];
                })
                .catch(function (e) {
                    // Naechster Anlauf darf es erneut versuchen.
                    cfSeiten[space] = null;
                    throw e;
                });
        }
        cfSeiten[space].then(function (seiten) {
            // Der Benutzer kann inzwischen einen anderen Bereich gewaehlt
            // haben - dann gehoert diese Antwort nicht mehr zur Anzeige.
            var akt = $('wi-dest-cfspace');
            if (!akt || akt.value !== space) return;
            cfSeitenZeichnen(seiten);
        }).catch(function () {
            var akt = $('wi-dest-cfspace');
            if (!akt || akt.value !== space) return;
            // Kein stilles Leerfeld: ohne Seitenliste kann man immer noch unter
            // der Startseite anlegen, und genau das sagt die Meldung.
            cfSeitenZeichnen([]);
            status('wi-dest-cfstatus', t('wissen.dest_cf_pages_err'), 'err');
        });
    }

    // Gesperrt MIT Grund, nicht verborgen (Projektregel): der Grund muss der
    // RICHTIGE sein - ein Knopf, der nach dem Bereich fragt, obwohl der
    // Bereich steht, schickt an die falsche Stelle.
    function cfGoKnopf() {
        var btn = $('wi-dest-cfgo');
        if (!btn) return;
        var sp = $('wi-dest-cfspace'), ti = $('wi-dest-cftitel');
        var space = sp ? sp.value : '', titel = ti ? ti.value.trim() : '';
        if (cfLaeuft) { btn.disabled = true; btn.title = t('wissen.dest_cf_busy'); return; }
        if (!space) { btn.disabled = true; btn.title = t('wissen.dest_cf_need_space'); return; }
        if (!titel) { btn.disabled = true; btn.title = t('wissen.dest_cf_need_title'); return; }
        btn.disabled = false;
        btn.title = '';
    }

    function cfZeigen() {
        var box = $('wi-dest-cfbox');
        if (!box) return;
        box.hidden = false;
        status('wi-dest-cfstatus', '');
        cfSpacesZeichnen();
        // Der Titel wird nur vorbelegt, solange ihn niemand angefasst hat -
        // ein erneutes Oeffnen darf die Arbeit des Benutzers nicht verwerfen.
        var ti = $('wi-dest-cftitel');
        if (ti && !ti.dataset.beruehrt) ti.value = cfTitelVorschlag();
        cfGoKnopf();
    }

    function cfAnlegen() {
        var sp = $('wi-dest-cfspace'), pa = $('wi-dest-cfparent'), ti = $('wi-dest-cftitel');
        var space = sp ? sp.value : '', titel = ti ? ti.value.trim() : '';
        if (!space || !titel) { cfGoKnopf(); return; }
        // Die Elternseite zaehlt nur, wenn sie zum GEWAEHLTEN Bereich gehoert -
        // sonst schickte ein Wechsel mitten im Laden eine fremde Seiten-ID mit.
        // Der Server prueft es ebenfalls; hier faellt es frueher auf.
        // ⚠ HIER STAND EINE ZWEITE SCHRANKE ("gilt nur, wenn `data-space` zum
        // gewaehlten Bereich passt") – sie ist WEG, weil ihr Entfernen in der
        // Gegenprobe messbar nichts geaenderte hat: `cfSeitenLaden` setzt das
        // Pulldown bei JEDEM Bereichswechsel zurueck, eine fremde Seiten-ID
        // kann hier gar nicht mehr stehen. Eine Zeile, die niemand pruefen
        // kann, ist keine Schranke, sondern eine, die jede kuenftige
        // Durchsicht mitschleppt (Register: der `IsFile`-Guertel). Die
        // tragende Pruefung macht ohnehin der Server – und die ist gemessen.
        var parent = pa ? pa.value : '';
        cfLaeuft = true;
        cfGoKnopf();
        status('wi-dest-cfstatus', t('wissen.dest_cf_running'), 'busy');
        fetch('/api/wissen/destillat/confluence', {
            method: 'POST', headers: authH({ 'Content-Type': 'application/json' }),
            body: JSON.stringify({
                markdown: destillat, space: space, parent: parent,
                titel: titel, bilder: bilder
            })
        })
            .then(antwortLesen)
            .then(function (res) {
                if (res.s !== 201 || !res.d.ok) {
                    status('wi-dest-cfstatus', res.d.error || t('wissen.dest_cf_failed'), 'err');
                    return;
                }
                cfFertig(res.d);
            })
            .catch(function (e) {
                status('wi-dest-cfstatus', t('wissen.dest_cf_failed'), 'err');
            })
            .then(function () { cfLaeuft = false; cfGoKnopf(); });
    }

    function cfFertig(d) {
        var el = $('wi-dest-cfstatus');
        if (!el) return;
        // Die neue Seite ist der Sinn der Sache - sie gehoert anklickbar da,
        // nicht als Kennung. Ziel ist ein fremder Origin: rel/target gesetzt.
        var html = esc(t('wissen.dest_cf_done'));
        if (d.link) {
            // Ziel ist ein fremder Origin - `noopener` ist hier Pflicht, nicht
            // Stil (sonst greift die neue Seite ueber `window.opener` zurueck).
            html += ' <a href="' + esc(d.link) + '" target="_blank" rel="noopener noreferrer">'
                 + esc(d.title || '') + '</a>';
        } else {
            html += ' ' + esc(d.title || '');
        }
        if (d.bilder) html += ' · ' + esc(t('wissen.dest_cf_images', { n: d.bilder }));
        // Gleiche Auszeichnung wie `status(..., 'ok')` - zwei Schreibweisen
        // fuer dieselbe Meldung liefen beim naechsten Feinschliff auseinander.
        html = '<span class="wi-ok">' + html + '</span>';
        // ⚠ EIN FEHLSCHLAG BEIM ANHANG WIRD GENANNT. Die Seite steht, der Text
        // ist da - aber sie ist unvollstaendig, und das sieht man ihr nicht an.
        if (d.bilder_fehler && d.bilder_fehler.length) {
            html += '<div class="wi-err">'
                 + esc(t('wissen.dest_cf_img_err', { n: d.bilder_fehler.length }))
                 + '</div>';
        }
        el.innerHTML = html;
        // Der Seitenbaum dieses Bereichs ist veraltet - die neue Seite fehlt
        // darin, und beim naechsten Anlegen waere sie nicht als Elternseite
        // waehlbar.
        var sp = $('wi-dest-cfspace');
        if (sp && sp.value) cfSeiten[sp.value] = null;
    }

    // ── Aufbau ──────────────────────────────────────────────────────────
    // Antwort lesen, auch wenn sie KEIN JSON ist (Code-Review 2026-10-07): eine
    // 502-Seite des Proxys oder ein Zeitlimit beim langen Lauf liefert HTML, und
    // r.json() warf – der Benutzer las "Unexpected token '<' …". Jetzt kommt
    // ein leeres Objekt, und der Aufrufer zeigt seinen eigenen Text.
    function antwortLesen(r) {
        return r.json().catch(function () { return null; })
            .then(function (d) { return { s: r.status, d: (d && typeof d === 'object') ? d : {} }; });
    }

    function vorgabenSetzen() {
        // Die Vorgabe-Aufträge kommen aus i18n, damit sie dem Sprachwechsel
        // folgen – der Text ist eine Anweisung an das Modell und gehoert in die
        // Sprache des Benutzers.
        var p = $('wi-dest-prompt'), g = $('wi-dest-gruppen');
        // Zuruecksetzen heisst auch: wieder der Vorgabe folgen (Code-Review
        // 2026-10-07) – mit stehengebliebener Beruehrt-Marke blieb der Auftrag
        // nach einem Sprachwechsel in der alten Sprache stehen.
        if (p) { delete p.dataset.beruehrt; p.value = t('wissen.dest_prompt_default'); }
        if (g) { delete g.dataset.beruehrt; g.value = t('wissen.dest_gruppen_default'); }
    }

    function init(opt) {
        opt = opt || {};
        SCOPE = opt.scope || null;
        TOKEN = opt.token || '';
        var sec = $('wi-sec-destillat');
        if (!sec) return;
        // Sichtbarkeit GENAU WIE DER INFORMATIONSEXTRAKTOR: ohne Wissensgruppe
        // gibt es kein Ziel fuer die Uebernahme und keinen Bereich.
        if (!SCOPE || !SCOPE.groups || !SCOPE.groups.length) {
            sec.classList.add('hidden');
            return;
        }
        sec.classList.remove('hidden');
        if (sec.getAttribute('data-bereit') === '1') return;
        sec.setAttribute('data-bereit', '1');

        vorgabenSetzen();
        zaehlerZeichnen();
        filterLaden();
        ['wi-dest-weiss', 'wi-dest-schwarz'].forEach(function (id) {
            var e = $(id);
            if (!e) return;
            e.addEventListener('input', function () { e.dataset.beruehrt = '1'; filterZahlZeichnen(); });
            // Gespeichert wird beim Verlassen des Feldes (`change`), nicht bei
            // jedem Tastendruck - jeder waere ein Schreibzugriff auf dem Server.
            e.addEventListener('change', filterSpeichern);
        });

        var drop = $('wi-dest-drop'), input = $('wi-dest-files');
        var dirIn = $('wi-dest-dir'), dirBtn = $('wi-dest-dirbtn');
        if (drop && input) {
            drop.addEventListener('click', function () { input.click(); });
            input.addEventListener('change', function () {
                dateienNehmen(input.files);
                input.value = '';   // dieselbe Datei erneut waehlbar
            });
            if (dirIn && dirBtn) {
                dirBtn.addEventListener('click', function (e) {
                    // Der Knopf liegt IN der Drop-Zone: ohne stopPropagation
                    // oeffnete derselbe Klick zusaetzlich den Datei-Dialog.
                    e.stopPropagation();
                    dirIn.click();
                });
                dirIn.addEventListener('click', function (e) { e.stopPropagation(); });
                dirIn.addEventListener('change', function () {
                    ausOrdnerwahl(dirIn.files);
                    dirIn.value = '';
                });
            }
            input.addEventListener('click', function (e) { e.stopPropagation(); });
            ['dragenter', 'dragover'].forEach(function (ev) {
                drop.addEventListener(ev, function (e) {
                    // NUR bei Dateien abfangen – gezogener Text soll sich
                    // weiterhin normal verhalten.
                    if (e.dataTransfer && Array.prototype.indexOf.call(
                            e.dataTransfer.types || [], 'Files') === -1) return;
                    e.preventDefault(); drop.classList.add('drag');
                });
            });
            ['dragleave', 'drop'].forEach(function (ev) {
                drop.addEventListener(ev, function () { drop.classList.remove('drag'); });
            });
            drop.addEventListener('drop', function (e) {
                if (!e.dataTransfer || !e.dataTransfer.files.length) return;
                e.preventDefault();
                // Ein gezogener ORDNER erscheint in `files` als Eintrag ohne
                // Inhalt – nur ueber die Eintraege ist er lesbar.
                // webkitGetAsEntry() MUSS synchron im drop-Handler laufen:
                // danach ist dataTransfer geleert.
                var eintraege = Array.prototype.map.call(e.dataTransfer.items || [], function (it) {
                    return it.kind === 'file' && it.webkitGetAsEntry ? it.webkitGetAsEntry() : null;
                });
                var mitOrdner = eintraege.some(function (x) { return x && x.isDirectory; });
                if (!mitOrdner) { dateienNehmen(e.dataTransfer.files); return; }
                var raus = [];
                Promise.all(eintraege.filter(Boolean).map(function (x) { return eintragLesen(x, raus); }))
                    .then(function () { ordnerNehmen(raus); });
            });
        }

        var lb = $('wi-dest-logbtn');
        if (lb) lb.addEventListener('click', function () {
            var box = $('wi-dest-log'); if (!box) return;
            box.hidden = !box.hidden;
            protokollZeichnen();
        });

        var ta = $('wi-dest-text');
        if (ta) ta.addEventListener('input', zaehlerZeichnen);

        var run = $('wi-dest-run'); if (run) run.addEventListener('click', destillieren);
        var rst = $('wi-dest-reset'); if (rst) rst.addEventListener('click', function () {
            vorgabenSetzen();
            status('wi-dest-status', t('wissen.dest_reset_done'), 'ok');
        });
        var cp = $('wi-dest-copy'); if (cp) cp.addEventListener('click', kopieren);
        var dl = $('wi-dest-dl'); if (dl) dl.addEventListener('click', herunterladen);
        var tk = $('wi-dest-take'); if (tk) tk.addEventListener('click', uebernahmeZeigen);
        var tg = $('wi-dest-takego'); if (tg) tg.addEventListener('click', uebernehmen);
        var tc = $('wi-dest-takecancel');
        if (tc) tc.addEventListener('click', function () {
            var b = $('wi-dest-takebox'); if (b) b.hidden = true;
        });

        var cfb = $('wi-dest-cf'); if (cfb) cfb.addEventListener('click', cfZeigen);
        var cfg = $('wi-dest-cfgo'); if (cfg) cfg.addEventListener('click', cfAnlegen);
        var cfc = $('wi-dest-cfcancel');
        if (cfc) cfc.addEventListener('click', function () {
            var b = $('wi-dest-cfbox'); if (b) b.hidden = true;
        });
        var cfs = $('wi-dest-cfspace');
        if (cfs) cfs.addEventListener('change', function () {
            status('wi-dest-cfstatus', '');
            cfSeitenLaden(cfs.value);
            cfGoKnopf();
        });
        var cft = $('wi-dest-cftitel');
        if (cft) cft.addEventListener('input', function () {
            // Ein bearbeiteter Titel ist Arbeit des Benutzers - ab hier wird
            // nicht mehr vorbelegt (bis zum naechsten Destillat-Lauf).
            cft.dataset.beruehrt = '1';
            cfGoKnopf();
        });
        // Der Zustand kann VOR init() gemeldet worden sein (wissen.js ruft
        // cfbLaden und init im selben Durchgang) - dann steht er schon in
        // `cfAktiv` und der Knopf muss nachgezogen werden.
        cfKnopf();

        // Die Vorgabe-Aufträge folgen dem Sprachwechsel. `applyLang()` erreicht
        // sie nicht – sie stehen als WERT in einem Textfeld, nicht als
        // data-i18n-Text. Ein vom Benutzer geaenderter Auftrag bleibt aber
        // stehen: seine Arbeit gehoert ihm.
        window.addEventListener('jarvis-lang-changed', function () {
            var p = $('wi-dest-prompt'), g = $('wi-dest-gruppen');
            if (p && !p.dataset.beruehrt) p.value = t('wissen.dest_prompt_default');
            if (g && !g.dataset.beruehrt) g.value = t('wissen.dest_gruppen_default');
            zaehlerZeichnen();
            protokollZeichnen();
            filterZahlZeichnen();
        });
        ['wi-dest-prompt', 'wi-dest-gruppen'].forEach(function (id) {
            var e = $(id);
            if (e) e.addEventListener('input', function () { e.dataset.beruehrt = '1'; });
        });
    }

    window.WissenDestillat = { init: init, confluence: confluence,
                               _md: md, _mitBildern: mitBildern,
                               _filterGrund: filterGrund, _musterTrifft: musterTrifft,
                               _storageZiel: cfTitelVorschlag };
})();
